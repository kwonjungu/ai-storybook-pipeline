#!/usr/bin/env python3
"""
09b_smart_shorts.py
AI 동화책 파이프라인 — 9b단계: 스마트 Shorts 생성

두 가지 조립 모드:
  [Mode A] 9:16 이미지 직접 조립 (최고 화질, 블러 없음)
    → 01b_analyze_shorts_plan.py + 02_generate_images.py 실행 후 사용 가능
    → slide_XX_9x16.png + slide_XX.wav 로 직접 조립
  [Mode B] video.mp4 추출 + 블러 배경 합성 (폴백)
    → 9:16 이미지가 없을 때 자동으로 사용

구간 선택 우선순위:
  1. shorts_plan.json (01b에서 생성) → 재분석 없이 즉시 사용
  2. shorts_analysis.json (기존 캐시) → 재분석 없이 즉시 사용
  3. AI 분석 (Gemini) → 신규 실행

사용법:
  python 09b_smart_shorts.py --ep 1
  python 09b_smart_shorts.py --dir output/bsl01
  python 09b_smart_shorts.py --ep 1 --force  (재분석 + 재생성)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HANGUL = re.compile(r'[\uAC00-\uD7A3]')

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    print("[ERROR] GEMINI_API_KEY가 .env에 없습니다.")
    sys.exit(1)

_genai_client = genai.Client(api_key=GEMINI_API_KEY)

# ── 상수 ─────────────────────────────────────────────────────
WIDTH  = 1080
HEIGHT = 1920
FPS    = 30
CRF     = "22"
PRESET  = "fast"
THREADS = "2"   # 스레드 수 고정 (1080x1920 고해상도에서 OOM 방지 — 4 → 2)

ENDING_TEXT     = "전체 이야기는 본편에서!"
ENDING_DURATION = 3.0
HOOK_DURATION   = 3.0

MIN_SHORTS_SEC = 45
MAX_SHORTS_SEC = 75
MIN_SCORE      = 70

SHORTS_SPEED   = 1.3   # 재생 속도 배율 (1.3 = 1.3배 빠르게)


# ── 유틸리티 ─────────────────────────────────────────────────

def run_ffmpeg(cmd: list, label: str = "") -> bool:
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding='utf-8', errors='replace'
    )
    if result.returncode != 0:
        tag = f" ({label})" if label else ""
        print(f"[ERROR] FFmpeg 실패{tag}")
        print(result.stderr[-2000:])
        return False
    return True


def ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0.0


def get_font_path() -> str:
    for fp in [
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothicBold.ttf",
    ]:
        if Path(fp).exists():
            return fp
    return "C:/Windows/Fonts/malgunbd.ttf"


def escape_ffmpeg(s: str) -> str:
    return s.replace("\\", "/").replace(":", "\\:")


def safe_text(s: str) -> str:
    """FFmpeg drawtext 안전 문자열 변환."""
    return (s.replace("'", "")
             .replace('"', "")
             .replace(":", "\\:")
             .replace("%", "%%")
             .replace("\\", ""))


def resolve_ep_dir(args) -> Path:
    if args.dir:
        d = Path(args.dir)
    else:
        d = Path(__file__).parent / "output" / f"ep{int(args.ep):02d}"
    if not d.exists():
        print(f"[ERROR] 디렉토리 없음: {d}")
        sys.exit(1)
    return d


# ── 데이터 로드 ───────────────────────────────────────────────

def load_story(ep_dir: Path) -> dict:
    p = ep_dir / "story.json"
    if not p.exists():
        print(f"[ERROR] story.json 없음: {p}")
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_timing(ep_dir: Path) -> dict | None:
    p = ep_dir / "audio" / "timing.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_plan(ep_dir: Path) -> dict | None:
    """shorts_plan.json (01b) 또는 shorts_analysis.json (구버전 캐시) 로드."""
    for name in ("shorts_plan.json", "shorts_analysis.json"):
        p = ep_dir / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            # shorts_analysis.json 구조 → plan 구조로 변환
            if "shorts" in data:
                top = sorted(data["shorts"], key=lambda x: x.get("rank", 99))[0]
                return {
                    "start_slide": top["start_slide"],
                    "end_slide":   top["end_slide"],
                    "score":       top.get("score", 0),
                    "hook_text":   top.get("hook_text", ""),
                    "reason":      top.get("reason", ""),
                }
            return data
    return None


# ── 윈도우 열거 ───────────────────────────────────────────────

def enumerate_windows(timing_slides: list) -> list:
    story_slides = [s for s in timing_slides if s["type"] == "story"]
    windows = []
    n = len(story_slides)
    for i in range(n):
        total = 0.0
        for j in range(i, n):
            total += story_slides[j]["duration"]
            if total > MAX_SHORTS_SEC:
                break
            if total >= MIN_SHORTS_SEC:
                windows.append({
                    "start_slide": story_slides[i]["slide"],
                    "end_slide":   story_slides[j]["slide"],
                    "start_time":  story_slides[i]["start"],
                    "end_time":    story_slides[j]["end"],
                    "duration":    round(total, 1),
                })
    return windows


# ── AI 분석 ─────────────────────────────────────────────────

def run_ai_analysis(story: dict, timing_slides: list) -> dict:
    """Gemini로 최적 구간 분석 → plan dict 반환."""
    slides_by_num = {sl["slide_number"]: sl for sl in story.get("slides", [])}
    timing_by_num = {t["slide"]: t for t in timing_slides}
    lang = story.get("meta", {}).get("language", "ko")

    windows = enumerate_windows(timing_slides)
    if not windows:
        print("[ERROR] 후보 윈도우 없음")
        sys.exit(1)

    title = story.get("meta", {}).get("story_title", "")

    slide_lines = []
    for t in timing_slides:
        if t["type"] != "story":
            continue
        sl    = slides_by_num.get(t["slide"], {})
        segs  = sl.get("tts_segments", [])
        first = segs[0].get("text", "").strip()[:70] if segs else ""
        mood  = sl.get("color_mood", "")
        slide_lines.append(f'  {t["slide"]}번({t["duration"]}s, {mood}): "{first}"')

    win_lines = []
    for i, w in enumerate(windows):
        moods = [slides_by_num.get(sn, {}).get("color_mood", "")
                 for sn in range(w["start_slide"], w["end_slide"] + 1)
                 if slides_by_num.get(sn, {}).get("type") == "story"]
        first_segs = slides_by_num.get(w["start_slide"], {}).get("tts_segments", [])
        first_line = first_segs[0].get("text", "").strip()[:60] if first_segs else ""
        win_lines.append(
            f'  W{i+1}: 슬라이드 {w["start_slide"]}~{w["end_slide"]} ({w["duration"]}초)'
            f' | 감정: {" → ".join(moods)} | 시작: "{first_line}"'
        )

    HOOK_LANG_INSTRUCTIONS = {
        "ko": '훅 문구는 한국어로 최대 15자. 예: "용기를 내 볼까?"',
        "en": 'Hook text in English, max 12 words. Example: "Can you be brave?"',
        "es": 'Texto del gancho en español, máximo 12 palabras. Ejemplo: "¡Sé valiente!"',
        "id": 'Teks hook dalam bahasa Indonesia, maksimal 12 kata. Contoh: "Beranikan diri!"',
        "pt": 'Texto do gancho em português brasileiro, máximo 12 palavras. Exemplo: "Seja corajoso!"',
        "ja": 'フックテキストは日本語で最大15文字。例：「勇気を出して！」',
    }
    hook_instruction = HOOK_LANG_INSTRUCTIONS.get(lang, HOOK_LANG_INSTRUCTIONS["en"])

    if lang == "id":
        hook_fmt = '"hook_text":"<teks hook Bahasa Indonesia maks 15 karakter>"'
        prompt = f"""Cerita "{title}" — Pilih segmen terbaik untuk YouTube Shorts (hanya 1 terbaik)

Slide:
{chr(10).join(slide_lines)}

Kandidat segmen (berdasarkan nomor slide):
{chr(10).join(win_lines)}

Kriteria skor: kalimat kuat di 3 detik pertama(30)+perubahan emosi(25)+selesai 60dtk(20)+pesan utama(15)+kejutan(10)

Penting: start_slide/end_slide HARUS menggunakan nomor slide nyata dari kandidat di atas.
         Bukan nomor W (indeks kandidat), tapi angka X dan Y dari "Slide X~Y".

Jawab hanya JSON 1 segmen terbaik (tanpa teks lain):
{{"start_slide":<nomor_slide>,"end_slide":<nomor_slide>,"score":<0~100>,{hook_fmt},"reason":"<alasan>"}}"""
    elif lang == "ko":
        prompt = f"""동화 "{title}" — Shorts 최적 구간 (1등만)

슬라이드:
{chr(10).join(slide_lines)}

후보 구간 (슬라이드 번호 기준):
{chr(10).join(win_lines)}

점수 기준: 첫3초강한대사(30)+감정변화(25)+60초완결(20)+핵심메시지(15)+반전(10)

주의: start_slide/end_slide는 반드시 위 후보 구간에 나온 실제 슬라이드 번호를 사용할 것.
      W숫자(구간 인덱스)가 아니라 "슬라이드 X~Y" 중 X와 Y를 쓸 것.

1등 구간만 JSON 응답 (다른 텍스트 없이):
{{"start_slide":<슬라이드번호>,"end_slide":<슬라이드번호>,"score":<0~100>,"hook_text":"<훅 최대15자>","reason":"<이유>"}}"""
    else:
        prompt = f"""Story "{title}" — Select the best segment for YouTube Shorts (top 1 only)

Slides:
{chr(10).join(slide_lines)}

Candidate segments (by slide number):
{chr(10).join(win_lines)}

Scoring: strong opening line in first 3s(30)+emotional shift(25)+complete in 60s(20)+core message(15)+surprise(10)

Important: start_slide/end_slide MUST use real slide numbers from the candidates above.
           Not the W number (index), but the actual X and Y from "Slide X~Y".

Hook instruction: {hook_instruction}

Respond with JSON for top 1 segment only (no other text):
{{"start_slide":<slide_number>,"end_slide":<slide_number>,"score":<0~100>,"hook_text":"<hook>","reason":"<reason>"}}"""

    print("[AI] Gemini 2.5 Flash로 구간 분석 중...")
    resp = _genai_client.models.generate_content(
        model=os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = resp.text.strip()
    s = raw.find("{"); e = raw.rfind("}") + 1
    if s >= 0 and e > s:
        raw = raw[s:e]
    result = json.loads(raw)

    # ── 응답 검증: start_slide/end_slide가 실제 윈도우에 존재하는지 확인 ──
    ss = result.get("start_slide", -1)
    es = result.get("end_slide", -1)
    valid_window = next(
        (w for w in windows if w["start_slide"] == ss and w["end_slide"] == es),
        None
    )
    if ss > es or valid_window is None:
        # AI가 잘못된 슬라이드 번호를 반환한 경우 → 가장 긴 윈도우로 폴백
        print(f"  [WARN] AI 응답 무효 (start={ss}, end={es}) → 최적 윈도우 자동 선택")
        best = max(windows, key=lambda w: w["duration"])
        result["start_slide"] = best["start_slide"]
        result["end_slide"]   = best["end_slide"]

    result["analyzed_by"] = "09b_smart_shorts"
    return result


# ── 자막 drawtext 빌더 ────────────────────────────────────────

def build_subtitle_drawtext(ep_dir: Path, slide_num: int, total_dur: float,
                             font_esc: str, font_size: int = 64) -> str:
    """슬라이드의 tts_segments를 기반으로 자막 drawtext 필터 문자열 생성.
    각 세그먼트 WAV 실제 길이로 타임스탬프 계산."""
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        return ""
    with open(story_path, "r", encoding="utf-8") as f:
        story_data = json.load(f)

    segments = []
    for sl in story_data.get("slides", []):
        if sl.get("slide_number") == slide_num:
            segments = sl.get("tts_segments", [])
            break

    if not segments:
        return ""

    audio_dir = ep_dir / "audio"
    parts = []
    t_cursor = 0.0

    for si, seg in enumerate(segments):
        seg_wav = audio_dir / f"slide_{slide_num:02d}_seg_{si:02d}.wav"
        seg_dur = ffprobe_duration(str(seg_wav)) if seg_wav.exists() else 0.0
        if seg_dur <= 0:
            seg_dur = total_dur / max(len(segments), 1)

        text = seg.get("text", "").strip()
        if not text:
            t_cursor += seg_dur
            continue

        # 어절 단위로 나눠 최대 12자씩 청크
        words = text.split()
        chunks, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if len(cand) <= 12:
                cur = cand
            else:
                if cur:
                    chunks.append(cur)
                cur = w
        if cur:
            chunks.append(cur)
        if not chunks:
            t_cursor += seg_dur
            continue

        chunk_dur = seg_dur / len(chunks)
        for ci, chunk in enumerate(chunks):
            if len(parts) >= 20:  # Windows 명령행 길이 제한 회피
                break
            t_start = t_cursor + ci * chunk_dur
            t_end   = t_cursor + (ci + 1) * chunk_dur
            if t_end > total_dur + 0.1:
                break
            s = safe_text(chunk)
            if not s:
                continue
            parts.append(
                f"drawtext=fontfile='{font_esc}':text='{s}'"
                f":fontsize={font_size}:fontcolor=white"
                f":x=(w-text_w)/2:y=h-text_h-80"
                f":enable='gte(t\\,{t_start:.3f})*lt(t\\,{t_end:.3f})'"
                f":borderw=5:bordercolor=black"
                f":box=1:boxcolor=black@0.55:boxborderw=12"
            )

        t_cursor += seg_dur

    return ",".join(parts)


# ── Mode A: 9:16 이미지 직접 조립 ────────────────────────────

def check_9x16_images(ep_dir: Path, start_slide: int, end_slide: int) -> bool:
    """해당 범위 모든 슬라이드에 9:16 이미지가 있으면 True."""
    for sn in range(start_slide, end_slide + 1):
        if not (ep_dir / "images" / f"slide_{sn:02d}_9x16.png").exists():
            return False
    return True


def assemble_from_9x16_images(
    ep_dir: Path,
    start_slide: int,
    end_slide: int,
    hook_text: str,
    output_path: Path,
) -> bool:
    """9:16 이미지 + 슬라이드 오디오로 Shorts 직접 조립.
    블러/크롭 없음 → 원본 화질 그대로."""
    font_esc = escape_ffmpeg(get_font_path())
    print(f"  [Mode A] 9:16 이미지 직접 조립 (슬라이드 {start_slide}~{end_slide})")

    with tempfile.TemporaryDirectory() as tmp:
        clips = []

        for i, sn in enumerate(range(start_slide, end_slide + 1)):
            img   = ep_dir / "images" / f"slide_{sn:02d}_9x16.png"
            audio = ep_dir / "audio"  / f"slide_{sn:02d}.wav"

            if not img.exists():
                print(f"  [ERROR] 9:16 이미지 없음: {img.name}")
                return False

            dur = ffprobe_duration(str(audio)) if audio.exists() else 5.0
            if dur <= 0:
                dur = 5.0

            # 훅 텍스트: 첫 번째 슬라이드에만, 처음 HOOK_DURATION초
            hook_filter = ""
            if i == 0 and hook_text:
                s = safe_text(hook_text)
                hook_filter = (
                    f",drawtext=fontfile='{font_esc}':text='{s}'"
                    f":fontsize=60:fontcolor=white"
                    f":x=(w-text_w)/2:y=60"
                    f":borderw=4:bordercolor=black"
                    f":box=1:boxcolor=black@0.55:boxborderw=14"
                    f":enable='lt(t\\,{HOOK_DURATION:.1f})'"
                )

            # 자막 drawtext (세그먼트별 타이밍 계산)
            sub_filter = build_subtitle_drawtext(ep_dir, sn, dur, font_esc)
            sub_part = ("," + sub_filter) if sub_filter else ""

            vf = (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black"
                f"{hook_filter}{sub_part},format=yuv420p"
            )

            clip = os.path.join(tmp, f"clip_{i:02d}.mp4")

            # Windows 명령행 길이 제한 회피: 긴 필터는 파일로 저장
            vf_script_path = None
            use_filter_script = len(vf) > 3000
            if use_filter_script:
                vf_script_path = os.path.join(tmp, f"vf_{i:02d}.txt")
                with open(vf_script_path, "w", encoding="utf-8") as vf_f:
                    vf_f.write(vf)

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(FPS),
                "-t", f"{dur:.3f}",
                "-i", str(img),
            ]
            if audio.exists():
                cmd += ["-i", str(audio)]
            if use_filter_script:
                cmd += ["-filter_script:v", vf_script_path]
            else:
                cmd += ["-vf", vf]
            cmd += [
                "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
                "-pix_fmt", "yuv420p",
            ]
            if audio.exists():
                cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                        "-ac", "2", "-shortest"]
            else:
                # 무음 오디오 추가 (concat 구조 통일)
                cmd_base = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(FPS),
                    "-t", f"{dur:.3f}",
                    "-i", str(img),
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                ]
                if use_filter_script:
                    cmd_base += ["-filter_script:v", vf_script_path]
                else:
                    cmd_base += ["-vf", vf]
                cmd = cmd_base + [
                    "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
                    "-c:a", "aac", "-b:a", "128k",
                    "-t", f"{dur:.3f}",
                    "-pix_fmt", "yuv420p",
                    clip,
                ]
            if audio.exists():
                cmd.append(clip)

            if not run_ffmpeg(cmd, f"slide_{sn}"):
                return False
            clips.append(clip)

        # 엔딩 클립
        ending = os.path.join(tmp, "ending.mp4")
        if not make_ending_clip(ending):
            return False
        clips.append(ending)

        return concat_clips(clips, str(output_path))


# ── Mode B: video.mp4 추출 + 블러 배경 ───────────────────────

def extract_from_video(
    video_path: str,
    start_time: float,
    duration: float,
    hook_text: str,
    output_path: str,
) -> bool:
    """video.mp4에서 구간 추출 → 블러 배경 + 중앙 원본 합성 (폴백 모드).
    이미지/자막이 잘리지 않도록:
      bg: 16:9 → 높이=1920 확대 + 중앙 크롭 + 블러
      fg: 16:9 → 1080px 폭 유지 (≈607px 높이) → 세로 중앙 배치
    """
    font_esc = escape_ffmpeg(get_font_path())
    print(f"  [Mode B] 블러 배경 + 중앙 영상 합성 (폴백)")

    hook_filter = ""
    if hook_text:
        s = safe_text(hook_text)
        hook_filter = (
            f",drawtext=fontfile='{font_esc}':text='{s}'"
            f":fontsize=60:fontcolor=white"
            f":x=(w-text_w)/2:y=60"
            f":borderw=4:bordercolor=black"
            f":box=1:boxcolor=black@0.55:boxborderw=14"
            f":enable='lt(t\\,{HOOK_DURATION:.1f})'"
        )

    filter_complex = (
        f"[0:v]scale=-1:{HEIGHT},crop={WIDTH}:{HEIGHT},boxblur=20:5[bg];"
        f"[0:v]scale={WIDTH}:-2[fg];"
        f"[bg][fg]overlay=0:(H-h)/2{hook_filter},format=yuv420p[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.3f}",
        "-i", str(video_path),
        "-t", f"{duration:.3f}",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a",
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-r", str(FPS),
        str(output_path),
    ]
    return run_ffmpeg(cmd, f"extract ({start_time:.1f}~{start_time+duration:.1f}s)")


# ── 공통 빌더 ────────────────────────────────────────────────

def apply_speedup(input_path: str, output_path: str, speed: float = SHORTS_SPEED) -> bool:
    """영상을 speed배 빠르게 인코딩합니다.
    video: setpts=PTS/speed  /  audio: atempo=speed (0.5~2.0 범위)"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", f"setpts=PTS/{speed}",
        "-af", f"atempo={speed}",
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    return run_ffmpeg(cmd, f"speedup_{speed}x")


def make_hook_intro_clip(hook_text: str, output_path: str, duration: float = 2.5) -> bool:
    """Shorts 첫 화면: 검은 배경 + 훅 멘트 크게 표시 (시청자 이탈 방지용 인트로)."""
    font_esc = escape_ffmpeg(get_font_path())
    s = safe_text(hook_text)

    # 두 줄 배치: 큰 텍스트 중앙 + 아래 작은 부제
    vf = (
        f"drawtext=fontfile='{font_esc}':text='{s}'"
        f":fontsize=96:fontcolor=white"
        f":x=(w-text_w)/2:y=(h-text_h)/2-20"
        f":borderw=6:bordercolor=black"
        f":box=1:boxcolor=black@0.0:boxborderw=0"
        f",format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={WIDTH}x{HEIGHT}:d={duration}:r={FPS}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", vf,
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{duration}",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    return run_ffmpeg(cmd, "hook_intro")


def make_ending_clip(output_path: str) -> bool:
    font_esc = escape_ffmpeg(get_font_path())
    s = safe_text(ENDING_TEXT)
    vf = (
        f"drawtext=fontfile='{font_esc}':text='{s}'"
        f":fontsize=60:fontcolor=white"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":borderw=3:bordercolor=black,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:d={ENDING_DURATION}:r={FPS}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", vf,
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{ENDING_DURATION}",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    return run_ffmpeg(cmd, "ending_clip")


def concat_clips(clip_paths: list, output_path: str) -> bool:
    tmp_list = str(Path(output_path).with_suffix("")) + "_concat.txt"
    with open(tmp_list, "w", encoding="utf-8") as f:
        for p in clip_paths:
            safe = str(Path(p).resolve()).replace("\\", "/")
            f.write(f"file '{safe}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", tmp_list,
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET, "-threads", THREADS,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    ok = run_ffmpeg(cmd, "concat")
    try:
        os.remove(tmp_list)
    except Exception:
        pass
    return ok


# ── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="스마트 Shorts 생성 (9:16 이미지 우선)")
    parser.add_argument("--ep",    type=int, help="에피소드 번호")
    parser.add_argument("--dir",   type=str, help="에피소드 디렉토리")
    parser.add_argument("--force", action="store_true",
                        help="기존 계획/캐시 무시하고 재분석 + 재생성")
    parser.add_argument("--speed", type=float, default=None,
                        help="재생 속도 배율 (기본: 1.3, 예: --speed 1.1)")
    args = parser.parse_args()
    if not args.ep and not args.dir:
        parser.print_help()
        sys.exit(1)

    global SHORTS_SPEED
    if args.speed is not None:
        SHORTS_SPEED = args.speed

    ep_dir = resolve_ep_dir(args)
    print(f"\n{'='*60}")
    print(f"  [Smart Shorts] {ep_dir}")
    print(f"{'='*60}")

    # ── 1. 스토리 로드 ─────────────────────────────────────
    story = load_story(ep_dir)
    title = story.get("meta", {}).get("story_title", ep_dir.name)
    print(f"[INFO] 동화: {title}")

    # ── 2. 구간 계획 확인 ──────────────────────────────────
    plan = None if args.force else load_plan(ep_dir)

    if plan:
        print(f"[INFO] 계획 파일 로드 (AI 분석 생략)")
        print(f"  → 슬라이드 {plan['start_slide']}~{plan['end_slide']} | "
              f"점수 {plan.get('score', '?')}점 | 훅: {plan.get('hook_text', '')}")
    else:
        # timing.json 필요
        timing = load_timing(ep_dir)
        if not timing:
            print("[ERROR] timing.json 없음. 먼저 03_generate_tts.py + 04_concat_audio.py 실행")
            sys.exit(1)
        timing_slides = timing.get("slides", [])
        print(f"[INFO] 총 길이: {timing['total_duration']:.1f}초")

        windows = enumerate_windows(timing_slides)
        print(f"[INFO] 후보 윈도우: {len(windows)}개")
        if not windows:
            print("[ERROR] 적합한 구간이 없습니다.")
            sys.exit(1)

        plan = run_ai_analysis(story, timing_slides)

        # 캐시 저장
        plan_path = ep_dir / "shorts_plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"[INFO] shorts_plan.json 저장: {plan_path}")

    start_slide = plan["start_slide"]
    end_slide   = plan["end_slide"]
    hook_text   = plan.get("hook_text", "")
    score       = plan.get("score", 0)

    # 비한국어 에피소드인데 hook_text가 한글이면 story_title 앞부분으로 대체
    lang = story.get("meta", {}).get("language", "ko")
    if lang != "ko" and hook_text and HANGUL.search(hook_text):
        fallback = story.get("meta", {}).get("story_title", "")[:40]
        print(f"  [WARN] hook_text가 한글 감지 (lang={lang}). story_title로 대체: {fallback!r}")
        hook_text = fallback

    if score < MIN_SCORE:
        print(f"[ERROR] 점수({score})가 기준({MIN_SCORE})에 미달")
        sys.exit(1)

    print(f"\n[INFO] 선택 구간: 슬라이드 {start_slide}~{end_slide}")
    print(f"[INFO] 훅: {hook_text}")
    print(f"[INFO] 이유: {plan.get('reason', '')}")

    # ── 3. 출력 파일 확인 ──────────────────────────────────
    output_path = ep_dir / "shorts_smart_rank1.mp4"
    if output_path.exists() and not args.force:
        size_mb = output_path.stat().st_size / 1e6
        dur     = ffprobe_duration(str(output_path))
        print(f"\n[INFO] 이미 존재: {output_path.name} ({dur:.1f}초, {size_mb:.1f}MB)")
        print("  재생성하려면 --force 옵션 사용")
        return

    # ── 4. 조립 모드 선택 ──────────────────────────────────
    print()
    has_9x16 = check_9x16_images(ep_dir, start_slide, end_slide)

    if has_9x16:
        # [Mode A] 9:16 이미지 직접 조립
        with tempfile.TemporaryDirectory() as tmp:
            body_path = os.path.join(tmp, "body.mp4")
            intro_clip = os.path.join(tmp, "intro.mp4")
            ok = assemble_from_9x16_images(
                ep_dir, start_slide, end_slide, hook_text, Path(body_path)
            )
            if ok:
                make_hook_intro_clip(hook_text, intro_clip)
                ok = concat_clips([intro_clip, body_path], str(output_path))
    else:
        # [Mode B] video.mp4 추출 + 블러 배경 합성
        video_path = ep_dir / "video.mp4"
        if not video_path.exists():
            print(f"[ERROR] video.mp4 없음: {video_path}")
            print("  먼저 06_assemble_video.py를 실행하거나,")
            print("  01b → 02(9:16 이미지 생성) 순서로 실행하세요.")
            sys.exit(1)

        # timing.json에서 타임스탬프 가져오기
        timing = load_timing(ep_dir)
        if not timing:
            print("[ERROR] timing.json 없음")
            sys.exit(1)
        slide_timing = {t["slide"]: t for t in timing.get("slides", [])}

        if start_slide not in slide_timing or end_slide not in slide_timing:
            print(f"[ERROR] 슬라이드 {start_slide}~{end_slide} 타임스탬프 없음")
            sys.exit(1)

        start_time = slide_timing[start_slide]["start"]
        end_time   = slide_timing[end_slide]["end"]
        duration   = round(end_time - start_time, 3)
        print(f"  구간: {start_time:.1f}~{end_time:.1f}초 ({duration:.1f}초)")

        with tempfile.TemporaryDirectory() as tmp:
            intro_clip = os.path.join(tmp, "intro.mp4")
            seg_clip   = os.path.join(tmp, "segment.mp4")
            end_clip   = os.path.join(tmp, "ending.mp4")

            make_hook_intro_clip(hook_text, intro_clip)
            ok = (
                extract_from_video(str(video_path), start_time, duration,
                                   hook_text, seg_clip)
                and make_ending_clip(end_clip)
                and concat_clips([intro_clip, seg_clip, end_clip], str(output_path))
            )

    # ── 5. 속도 적용 (SHORTS_SPEED배) ────────────────────────
    if ok and output_path.exists():
        raw_dur = ffprobe_duration(str(output_path))
        print(f"\n[속도] {SHORTS_SPEED}x 배속 적용 중... "
              f"({raw_dur:.1f}초 → 약 {raw_dur/SHORTS_SPEED:.1f}초)")
        fast_path = output_path.with_stem(output_path.stem + "_fast")
        if apply_speedup(str(output_path), str(fast_path)):
            output_path.unlink()
            fast_path.rename(output_path)
        else:
            print("[WARN] 배속 적용 실패 — 원본 속도로 저장됨")

    # ── 6. 결과 ───────────────────────────────────────────────
    if ok and output_path.exists():
        final_dur = ffprobe_duration(str(output_path))
        size_mb   = output_path.stat().st_size / 1e6
        mode      = "A (9:16 이미지)" if has_9x16 else "B (블러 배경)"
        print(f"\n{'='*60}")
        print(f"  [DONE] Shorts 생성 완료!")
        print(f"  파일: {output_path.name}")
        print(f"  길이: {final_dur:.1f}초 ({SHORTS_SPEED}x 배속) | 크기: {size_mb:.1f}MB")
        print(f"  모드: {mode}")
        print(f"  해상도: {WIDTH}x{HEIGHT} (9:16)")
        print(f"{'='*60}")
    else:
        print("\n[ERROR] Shorts 생성 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
