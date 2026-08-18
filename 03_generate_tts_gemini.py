#!/usr/bin/env python3
"""
03_generate_tts_gemini.py — Gemini 2.5 Flash TTS 음성 생성 (다국어)

영어·일본어 등 비한국어 동화를 동화 구연 스타일로 생성합니다.
Gemini TTS는 괄호 안 스타일 지시를 이해하여 캐릭터별 표현력 있는 발화를 생성합니다.

사용법:
  python 03_generate_tts_gemini.py --dir output/bsl02_en
  python 03_generate_tts_gemini.py --ep 1
"""

import argparse
import io
import json
import os
import requests
import sys
import time
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

GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_FALLBACK_MODEL = os.getenv("GEMINI_TTS_FALLBACK_MODEL", "gemini-3.1-flash-tts-preview")
_current_model: str = GEMINI_TTS_MODEL  # 실행 중 폴백 시 교체됨

# ---------------------------------------------------------------------------
# ElevenLabs 폴백 설정
# ---------------------------------------------------------------------------
ELEVEN_API_KEY   = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
ELEVEN_MODEL     = os.getenv("ELEVEN_TTS_MODEL", "eleven_v3")
ELEVEN_IS_V3     = ELEVEN_MODEL.startswith(("eleven_v3", "eleven_ttv_v3"))
ELEVEN_BASE_URL  = "https://api.elevenlabs.io/v1"
# 언어별 청자(아동) 기준 속도 보정 — 평균 음절 발화 속도가 빠른 언어일수록 감속
#   es·pt: 음절 속도 최상위권(스페인어 ~7.8음절/초) → 가장 크게 감속
#   en: 강세박자 언어, 비원어민 아동 청취 고려 소폭 감속
#   id: 음절박자 언어, 학습자 청취 고려
#   ja: 모라 박자로 음절 밀도 높음
#   ko: 화자별 speed(내레이터 0.9 등)에서 이미 보정 → 1.0
LANG_SPEED       = {"ko": 1.0, "en": 0.95, "id": 0.92, "es": 0.88, "pt": 0.90, "ja": 0.93}

# Gemini voice → ElevenLabs voice_id 매핑
ELEVEN_VOICE_MAP = {
    "narrator":        {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "stability": 0.5,  "similarity_boost": 0.75},
    "main_1":          {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli",    "stability": 0.5,  "similarity_boost": 0.75},
    "main_2":          {"voice_id": "ErXwobaYiN019PkySvjV",  "name": "Antoni",  "stability": 0.5,  "similarity_boost": 0.75},
    "child_girl":      {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli",    "stability": 0.5,  "similarity_boost": 0.75},
    "child_boy":       {"voice_id": "ErXwobaYiN019PkySvjV",  "name": "Antoni",  "stability": 0.5,  "similarity_boost": 0.75},
    "teacher":         {"voice_id": "VR6AewLTigWG4xSOukaG",  "name": "Arnold",  "stability": 0.6,  "similarity_boost": 0.80},
    "supporting":      {"voice_id": "EXAVITQu4vr4xnSDxMaL",  "name": "Bella",   "stability": 0.5,  "similarity_boost": 0.75},
    "wise_tree":       {"voice_id": "VR6AewLTigWG4xSOukaG",  "name": "Arnold",  "stability": 0.6,  "similarity_boost": 0.80},
    "woodland_spirit": {"voice_id": "EXAVITQu4vr4xnSDxMaL",  "name": "Bella",   "stability": 0.55, "similarity_boost": 0.80},
    "dream_goblin":    {"voice_id": "yoZ06aMxZJJ28mfd3POQ",  "name": "Sam",     "stability": 0.45, "similarity_boost": 0.70},
}

_eleven_fallback_active: bool = False  # Gemini 완전 실패 시 True로 전환

# 요청 간 딜레이 (분당 10개 한도 → 7초 간격 = 분당 ~8개)
REQUEST_INTERVAL_SEC = 7.0
_last_request_time: float = 0.0

# 동화 구연 스타일 기본 보이스 배정
# Gemini 2.5 Flash TTS voices: Aoede, Puck, Charon, Kore, Fenrir, Leda, Orus, Zephyr
DEFAULT_VOICE_MAP = {
    "narrator": {
        "voice": "Aoede",
        "style": "warm gentle fairy tale narrator, speaking expressively to young children aged 7 to 8, storybook reading style",
    },
    "main_1": {
        "voice": "Leda",
        "style": "bright curious 8-year-old girl, cheerful and expressive, natural child voice",
    },
    "main_2": {
        "voice": "Puck",
        "style": "cheerful energetic squirrel character, playful and excited, slightly squeaky animal voice",
    },
    "wise_tree": {
        "voice": "Charon",
        "style": "deep wise grandfather tree, speaking slowly and warmly with great authority and kindness",
    },
    "woodland_spirit": {
        "voice": "Zephyr",
        "style": "ethereal magical forest spirit, soft and mysterious voice",
    },
    "dream_goblin": {
        "voice": "Fenrir",
        "style": "mischievous elderly goblin, raspy but friendly old voice",
    },
}

# 퀴즈 TTS 기본 텍스트 (영어)
QUIZ_TTS_EN = [
    ("quiz_intro", "Let's do a quiz!"),
    ("quiz_q1",    "Question 1!"),
    ("quiz_q2",    "Question 2!"),
    ("quiz_q3",    "Question 3!"),
    ("quiz_a1",    "That's correct!"),
    ("quiz_a2",    "That's correct!"),
    ("quiz_a3",    "That's correct!"),
]


# ---------------------------------------------------------------------------
# ElevenLabs TTS 폴백
# ---------------------------------------------------------------------------
def _apply_speed_ffmpeg(path: Path, speed: float) -> None:
    """생성된 WAV에 ffmpeg atempo로 재생 속도 적용.
    v3 계열은 API voice_settings.speed를 지원하지 않으므로 후처리로 보정."""
    if abs(speed - 1.0) < 0.02:
        return
    import subprocess
    speed = max(0.5, min(2.0, speed))
    tmp = path.with_suffix(".spd.wav")
    r = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-af", f"atempo={speed}",
                        "-ar", "44100", "-ac", "1", str(tmp)], capture_output=True)
    if r.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        try: tmp.unlink()
        except OSError: pass


def _eleven_tts(speaker: str, text: str, output_path: Path, speed: float = 1.0) -> bool:
    """ElevenLabs TTS 폴백 생성. 성공 시 True 반환."""
    if not ELEVEN_API_KEY:
        print("    [FALLBACK] ELEVENLABS_API_KEY 없음 — ElevenLabs 폴백 불가")
        return False
    vi  = ELEVEN_VOICE_MAP.get(speaker, ELEVEN_VOICE_MAP["narrator"])
    url = f"{ELEVEN_BASE_URL}/text-to-speech/{vi['voice_id']}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "model_id": ELEVEN_MODEL}
    if not ELEVEN_IS_V3:
        # v3 계열은 세밀 stability/speed 미지원 → v2 계열에서만 적용
        vs = {"stability": vi["stability"], "similarity_boost": vi["similarity_boost"]}
        if speed != 1.0:
            vs["speed"] = speed
        payload["voice_settings"] = vs
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                mp3_bytes = r.content
                # MP3 → WAV 변환
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
                    seg = seg.set_frame_rate(44100).set_channels(1).set_sample_width(2)
                    buf = io.BytesIO()
                    seg.export(buf, format="wav")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(buf.getvalue())
                    if ELEVEN_IS_V3:
                        _apply_speed_ffmpeg(output_path, speed)
                    return True
                except ImportError:
                    import subprocess, tempfile
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                        tf.write(mp3_bytes)
                        mp3_p = tf.name
                    wav_p = mp3_p.replace(".mp3", ".wav")
                    try:
                        subprocess.run(["ffmpeg","-y","-i",mp3_p,"-ar","44100","-ac","1","-acodec","pcm_s16le",wav_p], capture_output=True, check=True)
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(open(wav_p,"rb").read())
                        if ELEVEN_IS_V3:
                            _apply_speed_ffmpeg(output_path, speed)
                        return True
                    finally:
                        for p in [mp3_p, wav_p]:
                            try: os.unlink(p)
                            except: pass
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            print(f"    [FALLBACK-ERR] ElevenLabs {r.status_code}: {r.text[:80]}")
            return False
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"    [FALLBACK-ERR] ElevenLabs 예외: {e}")
                return False
    return False


# ---------------------------------------------------------------------------
# Gemini TTS 생성
# ---------------------------------------------------------------------------
def _rate_limit():
    """요청 간 최소 간격을 보장합니다 (분당 10개 한도 대응)."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL_SEC:
        time.sleep(REQUEST_INTERVAL_SEC - elapsed)
    _last_request_time = time.time()


def _save_wav(audio_bytes: bytes, mime_type: str, output_path: Path):
    """PCM 또는 WAV 바이트를 WAV 파일로 저장합니다."""
    sample_rate = 24000
    if "rate=" in mime_type:
        try:
            sample_rate = int(mime_type.split("rate=")[1].split(";")[0].split(",")[0])
        except ValueError:
            pass
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if "wav" in mime_type.lower():
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
    else:
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)


def generate_tts_gemini(client, voice: str, text: str, output_path: Path, style: str = "") -> bool:
    """Gemini 2.5 Flash TTS로 단일 세그먼트를 생성하여 WAV로 저장합니다.

    - 요청 간 7초 간격 유지 (분당 10개 한도 대응)
    - 분당 쿼터 초과(429) 시 retryDelay만큼 대기 후 1회 재시도
    - 일일 쿼터 초과(429 per_day) 시 즉시 False 반환
    """
    from google.genai import types

    styled_text = f"({style}) {text}" if style else text

    def _do_request():
        _rate_limit()
        return client.models.generate_content(
            model=_current_model,
            contents=styled_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            ),
        )

    for attempt in range(3):  # 최대 3회 시도 (Flash → 분당재시도 → Pro 폴백)
        try:
            response = _do_request()
            part = response.candidates[0].content.parts[0]
            _save_wav(part.inline_data.data, part.inline_data.mime_type, output_path)
            return True

        except Exception as e:
            err_str = str(e)
            if "429" in err_str:
                # retryDelay로 일일 vs 분당 한도 정확히 구분
                import re
                m = re.search(r'"retryDelay":\s*"(\d+)s"', err_str)
                retry_sec = int(m.group(1)) if m else 0

                if retry_sec > 300:  # 5분 초과 → 일일 한도
                    global _current_model
                    if _current_model != GEMINI_TTS_FALLBACK_MODEL:
                        _current_model = GEMINI_TTS_FALLBACK_MODEL
                        print(f"    [QUOTA-DAY] Flash 한도 초과 → Pro 모델로 자동 전환 ({GEMINI_TTS_FALLBACK_MODEL})")
                        continue  # Pro로 재시도
                    print(f"    [QUOTA-DAY] Pro 한도도 초과. ElevenLabs 폴백 활성화.")
                    global _eleven_fallback_active
                    _eleven_fallback_active = True
                    return False
                else:  # 분당 한도 → 대기 후 재시도
                    wait_sec = max(retry_sec + 5, 65)
                    print(f"    [QUOTA-MIN] 분당 한도 초과. {wait_sec}초 대기 후 재시도...")
                    time.sleep(wait_sec)
                    continue
            print(f"    [ERROR] Gemini TTS 실패 (voice={voice}): {e}")
            return False

    return False


# ---------------------------------------------------------------------------
# WAV 유틸
# ---------------------------------------------------------------------------
def get_wav_duration(wav_path: Path) -> float:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / rate if rate else 0.0
    except Exception:
        return 0.0


def concat_wav_files(wav_paths: list, output_path: Path):
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
    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.setnframes(len(all_data) // (nchannels * sampwidth))
        out.writeframesraw(all_data)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Gemini 2.5 Flash TTS 음성 생성 (영어/일본어 등)")
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

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY가 .env에 없습니다")
        return

    from google import genai
    client = genai.Client(api_key=api_key)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    slides = story.get("slides", [])
    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # gemini_voices → 없으면 DEFAULT 사용
    gv = story.get("meta", {}).get("gemini_voices", {})
    voice_map = {**DEFAULT_VOICE_MAP}
    for k, v in gv.items():
        voice_map[k] = {**DEFAULT_VOICE_MAP.get(k, {}), **v}

    global _current_model
    _current_model = GEMINI_TTS_MODEL  # 에피소드마다 초기화
    print(f"[{ep_dir}] Gemini TTS 생성 시작 (모델: {_current_model}, 폴백: {GEMINI_TTS_FALLBACK_MODEL})")
    print(f"  슬라이드 수: {len(slides)}")
    print(f"  캐릭터 보이스:")
    used_speakers = {
        seg.get("voice", seg.get("speaker", "narrator"))
        for sl in slides for seg in sl.get("tts_segments", [])
    }
    for sp in sorted(used_speakers):
        vi = voice_map.get(sp, voice_map.get("narrator", {}))
        print(f"    {sp:15s} → {vi.get('voice','?'):10s} | {vi.get('style','')[:50]}")
    print()

    # ------------------------------------------------------------------
    # 1단계: TTS 세그먼트 생성
    # ------------------------------------------------------------------
    slide_segments_map: dict[int, list] = {}
    lang = story.get("meta", {}).get("language", "en")

    global _eleven_fallback_active
    _eleven_fallback_active = False  # 에피소드마다 초기화

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

            vi = voice_map.get(speaker, voice_map.get("narrator", DEFAULT_VOICE_MAP["narrator"]))
            voice_name = vi.get("voice", "Aoede")
            style = vi.get("style", "")

            if _eleven_fallback_active:
                # 이미 폴백 모드 — ElevenLabs 직접 사용
                ok = _eleven_tts(speaker, text, seg_path, LANG_SPEED.get(lang, 1.0))
                engine = "ElevenLabs"
            else:
                ok = generate_tts_gemini(client, voice_name, text, seg_path, style=style)
                engine = "Gemini"
                if not ok and _eleven_fallback_active:
                    # 방금 generate_tts_gemini에서 폴백 활성화됨 → ElevenLabs로 재시도
                    print(f"    [FALLBACK] Gemini 실패 → ElevenLabs로 재시도...")
                    ok = _eleven_tts(speaker, text, seg_path, LANG_SPEED.get(lang, 1.0))
                    engine = "ElevenLabs"

            if ok:
                print(f"  seg{seg_idx:02d}[{speaker}] {engine} 완료")
            else:
                print(f"  seg{seg_idx:02d}[{speaker}] 생성 실패 (Gemini+ElevenLabs 모두 실패)")

        slide_segments_map[slide_num] = seg_entries

        existing = [p for _, _, p in seg_entries if p.exists()]
        if existing:
            slide_wav = audio_dir / f"slide_{slide_num:02d}.wav"
            try:
                concat_wav_files(existing, slide_wav)
                print(f"  -> slide_{slide_num:02d}.wav ({len(existing)}개 합침)")
            except Exception as e:
                print(f"  -> 합치기 실패: {e}")
        print()

    # ------------------------------------------------------------------
    # 2단계: 퀴즈 TTS 생성
    # ------------------------------------------------------------------
    print("[퀴즈 TTS] 생성 중...")
    quiz_tts_override = story.get("quiz_tts", {})
    narrator_vi = voice_map.get("narrator", DEFAULT_VOICE_MAP["narrator"])

    for name, default_text in QUIZ_TTS_EN:
        wav_path = audio_dir / f"{name}.wav"
        if wav_path.exists():
            print(f"  {name}.wav — 이미 존재, 건너뜀")
            continue
        text = quiz_tts_override.get(name, default_text)
        if _eleven_fallback_active:
            ok = _eleven_tts("narrator", text, wav_path, LANG_SPEED.get(lang, 1.0))
            engine = "ElevenLabs"
        else:
            quiz_style = "cheerful excited quiz show host voice for children"
            ok = generate_tts_gemini(client, narrator_vi.get("voice", "Aoede"), text,
                                      wav_path, style=quiz_style)
            engine = "Gemini"
            if not ok and _eleven_fallback_active:
                ok = _eleven_tts("narrator", text, wav_path, LANG_SPEED.get(lang, 1.0))
                engine = "ElevenLabs"
        print(f"  {name}.wav — {'완료' if ok else '실패'} ({engine})")
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

    print(f"  timing.json 완료: {total_segment_count}개 세그먼트, 총 {total_duration:.1f}초")
    print(f"\n[DONE] Gemini TTS 생성 완료 — {ep_dir}")
    print(f"\n다음 단계:")
    print(f"  python 04_concat_audio.py --dir {ep_dir}")
    print(f"  python 05_generate_srt.py --dir {ep_dir}")


if __name__ == "__main__":
    main()
