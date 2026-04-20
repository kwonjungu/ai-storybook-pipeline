#!/usr/bin/env python3
"""
03_generate_tts_openai.py — OpenAI TTS 음성 생성 (영어/일본어 등 다국어)

story.json의 openai_voices 섹션을 읽어 OpenAI TTS API로 각 tts_segment를 생성합니다.
timing.json 구조는 03_generate_tts.py와 동일합니다.

사용법:
  python 03_generate_tts_openai.py --dir output/bsl02_en
  python 03_generate_tts_openai.py --ep 1
"""

import argparse
import json
import os
import sys
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 상수 (03_generate_tts.py와 동일)
# ---------------------------------------------------------------------------
SILENCE_SAME_SPEAKER = 0.2
SILENCE_SPEAKER_CHANGE = 0.5
SILENCE_SLIDE_TRANSITION = 1.0
COVER_SLIDE_DURATION = 3.0

OPENAI_TTS_MODEL = "tts-1-hd"

# 기본 보이스 배정 (openai_voices가 없을 때 폴백)
DEFAULT_VOICE_MAP = {
    "narrator":   {"voice": "nova",    "speed": 0.95},
    "main_1":     {"voice": "shimmer", "speed": 1.0},
    "main_2":     {"voice": "alloy",   "speed": 1.05},
    "supporting": {"voice": "alloy",   "speed": 1.05},
    "wise_tree":  {"voice": "onyx",    "speed": 0.85},
    "woodland_spirit": {"voice": "fable", "speed": 0.95},
    "dream_goblin":    {"voice": "echo",  "speed": 1.0},
    "child_girl": {"voice": "shimmer", "speed": 1.0},
    "child_boy":  {"voice": "echo",    "speed": 1.05},
}


# ---------------------------------------------------------------------------
# OpenAI TTS 생성
# ---------------------------------------------------------------------------
def generate_tts_openai(client, voice: str, text: str, output_path: Path, speed: float = 1.0) -> bool:
    """OpenAI TTS로 단일 세그먼트를 생성하여 WAV로 저장합니다."""
    try:
        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=voice,
            input=text,
            response_format="wav",
            speed=round(max(0.25, min(4.0, speed)), 2),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"    [ERROR] OpenAI TTS 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# WAV 유틸
# ---------------------------------------------------------------------------
def get_wav_duration(wav_path: Path) -> float:
    """WAV 파일의 정확한 길이(초)를 측정합니다.

    OpenAI TTS가 반환하는 스트리밍 WAV는 nframes=INT_MAX로 설정되어 있어,
    파일 크기에서 실제 프레임 수를 역산합니다.
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            if rate == 0:
                return 0.0
            # INT_MAX(2147483647) 또는 비정상적으로 큰 값 → 파일 크기로 역산
            if frames > 2 ** 30:
                file_size = wav_path.stat().st_size
                data_bytes = max(0, file_size - 44)  # WAV 헤더 44바이트 제외
                frames = data_bytes // (nchannels * sampwidth)
            return frames / rate
    except Exception:
        return 0.0


def concat_wav_files(wav_paths: list, output_path: Path):
    """WAV 파일들을 하나로 합칩니다."""
    if not wav_paths:
        return
    with wave.open(str(wav_paths[0]), "rb") as first:
        nchannels = first.getnchannels()
        sampwidth = first.getsampwidth()
        framerate = first.getframerate()
        frames = [first.readframes(first.getnframes())]
    for p in wav_paths[1:]:
        with wave.open(str(p), "rb") as wf:
            frames.append(wf.readframes(wf.getnframes()))
    all_data = b"".join(frames)
    total_frames = len(all_data) // (nchannels * sampwidth)
    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.setnframes(total_frames)
        out.writeframesraw(all_data)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="OpenAI TTS 음성 생성 (영어/일본어 등)")
    parser.add_argument("--ep", type=int, default=None)
    parser.add_argument("--dir", type=str, default=None)
    args = parser.parse_args()

    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")

    story_path = ep_dir / "story.json"
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}")
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[ERROR] OPENAI_API_KEY가 .env에 없습니다")
        return

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    slides = story.get("slides", [])
    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # openai_voices 로드 (story.json에 없으면 DEFAULT 사용)
    ov = story.get("meta", {}).get("openai_voices", {})
    voice_map = {**DEFAULT_VOICE_MAP, **ov}

    print(f"[{ep_dir}] OpenAI TTS 생성 시작 (모델: {OPENAI_TTS_MODEL})")
    print(f"  슬라이드 수: {len(slides)}")
    print(f"  보이스 배정:")
    for sp, vi in voice_map.items():
        if any(seg.get("voice") == sp or seg.get("speaker") == sp
               for sl in slides for seg in sl.get("tts_segments", [])):
            print(f"    {sp:15s} → {vi['voice']:10s} speed={vi['speed']}")
    print()

    # ------------------------------------------------------------------
    # 1단계: TTS 세그먼트 생성
    # ------------------------------------------------------------------
    slide_segments_map: dict[int, list] = {}

    for slide in slides:
        slide_num = slide.get("slide_number", 0)
        segments = slide.get("tts_segments", [])
        if not segments:
            print(f"[슬라이드 {slide_num:02d}] tts_segments 없음 — 건너뜀")
            continue

        print(f"[슬라이드 {slide_num:02d}] 세그먼트 {len(segments)}개 처리 중...")
        seg_entries = []

        for seg_idx, seg in enumerate(segments):
            seg_path = audio_dir / f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav"
            speaker = seg.get("voice", seg.get("speaker", "narrator"))
            text = seg.get("text", "").strip()

            seg_entries.append((seg_idx, seg, seg_path))

            if seg_path.exists():
                print(f"  seg {seg_idx:02d} [{speaker}] — 이미 존재, 건너뜀")
                continue

            if not text:
                print(f"  seg {seg_idx:02d} [{speaker}] — 텍스트 비어있음, 건너뜀")
                continue

            vi = voice_map.get(speaker, voice_map.get("narrator", {"voice": "nova", "speed": 1.0}))
            voice_name = vi["voice"]
            speed = vi.get("speed", 1.0)

            ok = generate_tts_openai(client, voice_name, text, seg_path, speed=speed)
            status = "완료" if ok else "실패"
            print(f"  seg {seg_idx:02d} [{speaker}] voice={voice_name} — {status}")

        slide_segments_map[slide_num] = seg_entries

        existing = [p for _, _, p in seg_entries if p.exists()]
        if existing:
            slide_wav = audio_dir / f"slide_{slide_num:02d}.wav"
            try:
                concat_wav_files(existing, slide_wav)
                print(f"  -> slide_{slide_num:02d}.wav 생성 완료 ({len(existing)}개 합침)")
            except Exception as e:
                print(f"  -> slide_{slide_num:02d}.wav 합치기 실패: {e}")
        print()

    # ------------------------------------------------------------------
    # 2단계: 퀴즈 TTS 생성
    # ------------------------------------------------------------------
    print("[퀴즈 TTS] 생성 중...")
    quiz_lines_en = [
        ("quiz_intro", "Let's do a quiz!"),
        ("quiz_q1", "Question 1!"),
        ("quiz_q2", "Question 2!"),
        ("quiz_q3", "Question 3!"),
        ("quiz_a1", "That's correct!"),
        ("quiz_a2", "That's correct!"),
        ("quiz_a3", "That's correct!"),
    ]
    # story.json에 quiz_tts 섹션이 있으면 우선 사용
    quiz_tts_override = story.get("quiz_tts", {})
    narrator_voice = voice_map.get("narrator", {"voice": "nova", "speed": 0.95})

    for name, default_text in quiz_lines_en:
        wav_path = audio_dir / f"{name}.wav"
        if wav_path.exists():
            print(f"  {name}.wav — 이미 존재, 건너뜀")
            continue
        text = quiz_tts_override.get(name, default_text)
        ok = generate_tts_openai(client, narrator_voice["voice"], text, wav_path,
                                 speed=narrator_voice.get("speed", 0.95))
        print(f"  {name}.wav — {'완료' if ok else '실패'}")
    print()

    # ------------------------------------------------------------------
    # 3단계: timing.json 생성
    # ------------------------------------------------------------------
    print("timing.json 생성 중...")
    timing_segments = []
    timing_slides = []
    cumulative_time = 0.0
    all_slide_nums = sorted(set(s.get("slide_number", 0) for s in slides))
    total_segment_count = 0

    for slide_num in all_slide_nums:
        slide_start = cumulative_time

        if slide_num == 0:
            cumulative_time += COVER_SLIDE_DURATION
            timing_slides.append({
                "slide": 0,
                "type": "cover",
                "start": round(slide_start, 3),
                "end": round(cumulative_time, 3),
                "duration": round(COVER_SLIDE_DURATION, 3),
            })
            continue

        if slide_num > 1 or (slide_num == 1 and 0 in all_slide_nums):
            cumulative_time += SILENCE_SLIDE_TRANSITION
            slide_start = cumulative_time

        seg_entries = slide_segments_map.get(slide_num, [])
        prev_speaker = None

        for seg_idx, seg, seg_path in seg_entries:
            if not seg_path.exists():
                continue
            speaker = seg.get("voice", seg.get("speaker", "narrator"))
            text = seg.get("text", "")
            duration = get_wav_duration(seg_path)

            if prev_speaker is not None:
                if speaker == prev_speaker:
                    cumulative_time += SILENCE_SAME_SPEAKER
                else:
                    cumulative_time += SILENCE_SPEAKER_CHANGE

            seg_start = cumulative_time
            seg_end = cumulative_time + duration

            timing_segments.append({
                "file": f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav",
                "slide": slide_num,
                "index": seg_idx,
                "speaker": speaker,
                "text": text,
                "duration": round(duration, 3),
                "start": round(seg_start, 3),
                "end": round(seg_end, 3),
            })

            cumulative_time = seg_end
            prev_speaker = speaker
            total_segment_count += 1

        slide_end = cumulative_time
        timing_slides.append({
            "slide": slide_num,
            "start": round(slide_start, 3),
            "end": round(slide_end, 3),
            "duration": round(slide_end - slide_start, 3),
        })

    total_duration = cumulative_time

    timing_data = {
        "slides": timing_slides,
        "segments": timing_segments,
        "total_duration": round(total_duration, 3),
        "total_segments": total_segment_count,
    }

    timing_path = audio_dir / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing_data, f, ensure_ascii=False, indent=2)

    print(f"  timing.json 저장 완료: {total_segment_count}개 세그먼트, 총 {total_duration:.1f}초")
    print(f"\n[DONE] OpenAI TTS 생성 완료")
    print(f"  출력 폴더: {audio_dir}")
    print(f"\n다음 단계:")
    print(f"  python 04_concat_audio.py --dir {ep_dir}")
    print(f"  python 05_generate_srt.py --dir {ep_dir}")


if __name__ == "__main__":
    main()
