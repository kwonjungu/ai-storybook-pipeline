#!/usr/bin/env python3
"""
04_concat_audio.py — timing.json 기반으로 세그먼트 오디오를 하나의 full_audio.wav 로 합치기

03_generate_tts.py 가 생성한 timing.json 을 단일 진실 소스(single source of truth)로 사용하여
세그먼트 WAV 파일들을 올바른 순서와 간격으로 합친다.
FFmpeg 없이 Python wave 모듈만으로 처리한다.

사용법:
    python 04_concat_audio.py             # ep01
    python 04_concat_audio.py --ep 3      # ep03
"""

import argparse
import json
import sys
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def get_wav_duration(wav_path: Path) -> float:
    """WAV 파일의 재생 시간(초)을 반환한다.

    OpenAI TTS가 nframes를 INT32_MAX로 설정하는 경우 파일 크기 기반으로 계산.
    """
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        if rate == 0:
            return 0.0
        if frames >= 2147483647:
            file_size = wav_path.stat().st_size
            data_size = file_size - 44
            if data_size <= 0:
                return 0.0
            actual_frames = data_size // (channels * sampwidth)
            return actual_frames / rate
        return frames / rate


def get_wav_params(wav_path: Path):
    """WAV 파일의 (channels, sampwidth, framerate) 를 반환한다."""
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate()


def generate_silence_frames(duration: float, sample_rate: int, channels: int, sampwidth: int) -> bytes:
    """지정 길이의 무음 프레임 데이터를 반환한다."""
    n_frames = int(sample_rate * duration)
    return b"\x00" * (n_frames * channels * sampwidth)


def main():
    parser = argparse.ArgumentParser(description="timing.json 기반 오디오 합치기")
    parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (예: 1 → output/ep01)")
    parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
    args = parser.parse_args()

    if args.dir:
        audio_dir = Path(args.dir) / "audio"
    elif args.ep is not None:
        audio_dir = Path(f"output/ep{args.ep:02d}/audio")
    else:
        audio_dir = Path("output/ep01/audio")
    timing_path = audio_dir / "timing.json"
    output_path = audio_dir / "full_audio.wav"

    # ------------------------------------------------------------------
    # 1. timing.json 읽기
    # ------------------------------------------------------------------
    if not timing_path.exists():
        print(f"오류: {timing_path} 파일이 없습니다.")
        print("  먼저 03_generate_tts.py 를 실행하여 timing.json 을 생성하세요.")
        sys.exit(1)

    with open(timing_path, "r", encoding="utf-8") as f:
        timing = json.load(f)

    segments = timing["segments"]
    slides = timing["slides"]
    expected_total = timing["total_duration"]

    print(f"오디오 폴더: {audio_dir}")
    print(f"타이밍 파일: {timing_path}")
    print(f"세그먼트 수: {len(segments)}개")
    print(f"슬라이드 수: {len(slides)}개")
    print(f"예상 전체 길이: {expected_total:.2f}s "
          f"({int(expected_total // 60)}분 {expected_total % 60:.1f}초)\n")

    # ------------------------------------------------------------------
    # 2. 첫 번째 세그먼트에서 오디오 파라미터 가져오기
    # ------------------------------------------------------------------
    if not segments:
        print("오류: timing.json 에 세그먼트가 없습니다.")
        sys.exit(1)

    first_seg_path = audio_dir / segments[0]["file"]
    if not first_seg_path.exists():
        print(f"오류: 첫 번째 세그먼트 파일이 없습니다: {first_seg_path}")
        sys.exit(1)

    ref_channels, ref_sampwidth, ref_rate = get_wav_params(first_seg_path)
    print(f"오디오 파라미터: {ref_rate}Hz, {ref_channels}ch, {ref_sampwidth * 8}bit\n")

    # ------------------------------------------------------------------
    # 3. 세그먼트를 start 시간 순으로 정렬하고 오디오 빌드
    # ------------------------------------------------------------------
    sorted_segments = sorted(segments, key=lambda s: s["start"])

    # full_audio 에 쓸 전체 프레임 데이터를 모은다
    audio_data = bytearray()
    current_pos = 0.0  # 현재까지 기록한 위치 (초)

    for i, seg in enumerate(sorted_segments):
        seg_file = audio_dir / seg["file"]
        seg_start = seg["start"]
        seg_end = seg["end"]

        # 이 세그먼트 시작 전에 필요한 묵음 삽입
        gap = seg_start - current_pos
        if gap > 0.001:  # 1ms 이상의 간격만 삽입
            silence = generate_silence_frames(gap, ref_rate, ref_channels, ref_sampwidth)
            audio_data.extend(silence)
            current_pos += gap
            print(f"  [묵음] {gap:.3f}s 삽입 (위치: {current_pos - gap:.3f}s ~ {current_pos:.3f}s)")

        # 세그먼트 WAV 읽기
        if not seg_file.exists():
            print(f"경고: 세그먼트 파일 없음, 건너뜀: {seg_file}")
            # 해당 구간을 묵음으로 대체
            seg_duration = seg_end - seg_start
            silence = generate_silence_frames(seg_duration, ref_rate, ref_channels, ref_sampwidth)
            audio_data.extend(silence)
            current_pos = seg_end
            continue

        with wave.open(str(seg_file), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio_data.extend(frames)

        actual_dur = seg["duration"]
        current_pos = seg_end
        print(f"  [{i + 1}/{len(sorted_segments)}] {seg['file']}  "
              f"duration={actual_dur:.3f}s  "
              f"start={seg_start:.3f}s  end={seg_end:.3f}s  "
              f"speaker={seg.get('speaker', '?')}")

    # 마지막 세그먼트 이후, expected_total 까지 남은 묵음이 있으면 추가
    remaining = expected_total - current_pos
    if remaining > 0.001:
        silence = generate_silence_frames(remaining, ref_rate, ref_channels, ref_sampwidth)
        audio_data.extend(silence)
        current_pos += remaining
        print(f"  [묵음] 마지막 {remaining:.3f}s 추가")

    # ------------------------------------------------------------------
    # 4. full_audio.wav 쓰기
    # ------------------------------------------------------------------
    print(f"\nfull_audio.wav 쓰는 중...")

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(ref_channels)
        wf.setsampwidth(ref_sampwidth)
        wf.setframerate(ref_rate)
        wf.writeframes(bytes(audio_data))

    # ------------------------------------------------------------------
    # 5. 검증: 실제 길이와 expected_total 비교
    # ------------------------------------------------------------------
    actual_duration = get_wav_duration(output_path)
    diff = abs(actual_duration - expected_total)

    print(f"생성 완료: {output_path}")
    print(f"  실제 길이: {actual_duration:.3f}s")
    print(f"  예상 길이: {expected_total:.3f}s")
    print(f"  차이: {diff:.3f}s")

    if diff > 0.1:
        print(f"\n*** 오류: 실제 길이와 예상 길이의 차이가 ±0.1초를 초과합니다! ***")
        print(f"    실제={actual_duration:.3f}s vs 예상={expected_total:.3f}s (차이={diff:.3f}s)")
    else:
        print(f"  검증 통과: 차이 {diff:.3f}s (허용 범위 ±0.1s 이내)")

    # ------------------------------------------------------------------
    # 요약
    # ------------------------------------------------------------------
    print()
    print("=" * 50)
    print(f"  출력폴더     : {audio_dir}")
    print(f"  세그먼트 수  : {len(sorted_segments)}개")
    print(f"  슬라이드 수  : {len(slides)}개")
    print(f"  전체 길이    : {actual_duration:.1f}초 "
          f"({int(actual_duration // 60)}분 {actual_duration % 60:.1f}초)")
    print(f"  출력 파일    : {output_path}")
    print(f"  타이밍 파일  : {timing_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
