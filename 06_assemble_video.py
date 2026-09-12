#!/usr/bin/env python3
"""
06_assemble_video.py
AI 동화책 파이프라인 — 6단계: 최종 영상 조립 (가로 16:9)

이미지 + 오디오 + 자막을 FFmpeg로 합쳐 최종 MP4 영상을 생성합니다.
- timing.json을 단일 진실 공급원(single source of truth)으로 사용
- 정적 스케일 (흔들림 없음, zoompan 제거)
- 슬라이드 간 0.3초 페이드 인/아웃 전환
- 커버 슬라이드(slide 0)에 story_title + 단원 정보 오버레이
- [선택] 인트로 / 퀴즈 / 아웃트로 섹션 자동 감지 및 포함
- BGM 루프 (assets/bgm.mp3) 자동 감지 및 믹스

사용법: python 06_assemble_video.py --ep 1
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
FPS = 30
FADE_FRAMES = 9  # 0.3s @ 30fps
FADE_SEC = FADE_FRAMES / FPS  # 0.3


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────
def ffmpeg_safe(p: Path) -> str:
    """Path를 FFmpeg가 인식하는 문자열로 변환 (Windows 역슬래시 → 슬래시)."""
    return str(p.resolve()).replace("\\", "/")


def ffmpeg_safe_filter(p: Path) -> str:
    """필터 문자열 내부용 — 콜론도 이스케이프."""
    return ffmpeg_safe(p).replace(":", "\\:")


def check_ffmpeg() -> bool:
    """FFmpeg 설치 여부를 확인합니다."""
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"[OK] FFmpeg 확인: {r.stdout.split(chr(10))[0]}")
            return True
    except FileNotFoundError:
        pass
    print("[ERROR] FFmpeg를 찾을 수 없습니다.")
    print("  설치: https://ffmpeg.org/download.html")
    return False


def get_duration_ffprobe(file_path: str) -> float:
    """ffprobe로 미디어 파일의 재생 시간(초)을 반환합니다."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return -1.0


def find_korean_font() -> str:
    """시스템에서 한국어 폰트 경로를 탐색하여 반환합니다."""
    candidates = [
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf"),
        Path("C:/Windows/Fonts/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ]
    for c in candidates:
        if c.exists():
            return ffmpeg_safe(c)
    return "C\\:/Windows/Fonts/malgun.ttf"


def _subtitle_style(font_name: str) -> str:
    """ASS force_style 문자열 반환."""
    return (
        f"FontName={font_name},"
        "Bold=1,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"
        "BackColour=&H60000000,"
        "BorderStyle=4,"
        "Outline=0,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=40"
    )


def ensure_subtitle_font(assets_dir: Path) -> Path:
    """외국어 자막용 Nunito ExtraBold 폰트를 assets/fonts/에 준비합니다."""
    font_dir = assets_dir / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    font_path = font_dir / "Nunito-ExtraBold.ttf"
    if not font_path.exists():
        url = "https://github.com/google/fonts/raw/main/ofl/nunito/static/Nunito-ExtraBold.ttf"
        print(f"  [폰트] Nunito ExtraBold 다운로드 중...")
        try:
            urllib.request.urlretrieve(url, font_path)
            print(f"  [폰트] 다운로드 완료: {font_path}")
        except Exception as e:
            print(f"  [폰트] 다운로드 실패 ({e}), Arial로 대체합니다.")
            return None
    return font_path


def run_ffmpeg(cmd: list, label: str = "ffmpeg", timeout: int = 1800) -> None:
    """FFmpeg 명령을 실행하고 실패 시 에러를 출력합니다."""
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if r.returncode != 0:
        print(f"[ERROR] {label} 실패")
        err_tail = r.stderr[-3000:] if len(r.stderr) > 3000 else r.stderr
        print(err_tail)
        sys.exit(1)


# ──────────────────────────────────────────────
# timing.json / story.json 로더
# ──────────────────────────────────────────────
def load_timing(ep_dir: Path) -> dict:
    """timing.json을 읽어 전체 데이터를 반환합니다."""
    timing_path = ep_dir / "audio" / "timing.json"
    if not timing_path.exists():
        print(f"[ERROR] timing.json을 찾을 수 없습니다: {timing_path}")
        sys.exit(1)

    with open(timing_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "slides" in data:
        slides = data["slides"]
        total_duration = data.get("total_duration", None)
    elif isinstance(data, list):
        slides = data
        total_duration = None
    else:
        print("[ERROR] timing.json 형식을 인식할 수 없습니다")
        sys.exit(1)

    if total_duration is None and slides:
        last = slides[-1]
        total_duration = last.get("end", last.get("start", 0) + last.get("duration", 5.0))

    print(f"[OK] timing.json 로드 완료 ({len(slides)} 슬라이드, 총 {total_duration:.1f}초)")
    return {"slides": slides, "total_duration": total_duration}


def load_story_meta(ep_dir: Path) -> dict:
    """story.json에서 meta 정보를 읽어 반환합니다."""
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        print(f"[WARNING] story.json 없음: {story_path}")
        return {}
    with open(story_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("meta", {})


# ──────────────────────────────────────────────
# 이미지 탐색
# ──────────────────────────────────────────────
def find_images(ep_dir: Path, slides: list) -> list:
    """슬라이드 이미지 파일 경로 목록을 반환합니다."""
    images_dir = ep_dir / "images"
    image_files = []

    for i, entry in enumerate(slides):
        slide_num = entry.get("slide", entry.get("slide_number", i))
        img_path = images_dir / f"slide_{slide_num:02d}.png"
        if not img_path.exists():
            img_path = images_dir / f"slide_{slide_num}.png"
        if not img_path.exists():
            print(f"[WARNING] 이미지 없음: slide_{slide_num:02d}.png (검은 화면으로 대체)")
            image_files.append(None)
        else:
            image_files.append(img_path)

    found = sum(1 for f in image_files if f is not None)
    print(f"[OK] 이미지 {found}/{len(slides)}장 발견")
    return image_files


def get_slide_duration(entry: dict) -> float:
    """슬라이드 항목에서 duration을 추출합니다."""
    if "duration" in entry:
        return float(entry["duration"])
    if "duration_sec" in entry:
        return float(entry["duration_sec"])
    if "start" in entry and "end" in entry:
        return float(entry["end"]) - float(entry["start"])
    return 5.0


# ──────────────────────────────────────────────
# 개별 슬라이드 영상 생성 (Ken Burns + Fade)
# ──────────────────────────────────────────────
def build_slide_mp4(
    idx: int,
    img_path: Path | None,
    duration: float,
    tmp_dir: str,
    *,
    is_first: bool = False,
    is_last: bool = False,
) -> str:
    """한 장의 슬라이드 이미지를 Ken Burns + fade 효과가 적용된 mp4로 생성합니다.

    Args:
        idx: 슬라이드 인덱스 (0-based). 짝수=zoom-out, 홀수=zoom-in
        img_path: 원본 PNG 경로 (None이면 검은 화면)
        duration: 표시 시간(초)
        tmp_dir: 임시 디렉토리

    Returns:
        생성된 mp4 파일 경로
    """
    import re as _re
    out_mp4 = os.path.join(tmp_dir, f"slide_{idx:03d}.mp4")
    total_frames = max(int(round(duration * FPS)), 2)

    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT

    # ── 커버 포함 모든 슬라이드: 원본 이미지 그대로 사용 ──
    actual_img = img_path

    # ── 애니 클립 우선: anim/slide_XX.mp4 있으면 정지 이미지 대신 루프 사용 ──
    anim_clip = None
    if actual_img:
        m = _re.search(r"slide_(\d+)", Path(actual_img).stem)
        if m:
            cand = Path(actual_img).parent.parent / "anim" / f"slide_{int(m.group(1)):02d}.mp4"
            if cand.exists():
                anim_clip = cand
    if anim_clip:
        vf_parts = [
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        ]
        if is_first:
            vf_parts.append(f"fade=in:0:{FADE_FRAMES}")
        if is_last:
            fo = max(total_frames - FADE_FRAMES, FADE_FRAMES + 1)
            vf_parts.append(f"fade=out:{fo}:{FADE_FRAMES}")
        vf_parts.append("format=yuv420p")
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", ffmpeg_safe(anim_clip),
            "-t", f"{duration:.3f}",
            "-vf", ",".join(vf_parts),
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-threads", "4", "-pix_fmt", "yuv420p", "-an",
            "-t", f"{duration:.3f}", out_mp4,
        ]
        run_ffmpeg(cmd, label=f"slide_{idx:03d}(anim)")
        return out_mp4

    # ── 입력 ──
    if actual_img and actual_img.exists():
        input_args = ["-i", ffmpeg_safe(actual_img)]
        # 이미지를 W x H에 맞춤 (비율 유지, 검정 패딩)
        scale_filter = (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    else:
        input_args = [
            "-f", "lavfi",
            "-i", f"color=c=black:s={W}x{H}:d={duration:.3f}:r={FPS}",
        ]
        scale_filter = None

    # ── Fade — 첫 슬라이드만 fade-in, 마지막만 fade-out ──
    fade_parts = []
    if is_first:
        fade_parts.append(f"fade=in:0:{FADE_FRAMES}")
    if is_last:
        fade_out_start = max(total_frames - FADE_FRAMES, FADE_FRAMES + 1)
        fade_parts.append(f"fade=out:{fade_out_start}:{FADE_FRAMES}")
    fade_filter = ",".join(fade_parts) if fade_parts else None

    # ── 필터 체인 조합 (zoompan 제거 — 흔들림 방지) ──
    vf_parts = []
    if scale_filter:
        vf_parts.append(scale_filter)
    if fade_filter:
        vf_parts.append(fade_filter)
    vf_parts.append("format=yuv420p")

    vf_str = ",".join(vf_parts)

    # lavfi 소스 사용 시 -loop 옵션 제외 (FFmpeg 8.x 호환)
    loop_args = [] if (not actual_img or not actual_img.exists()) else ["-loop", "1"]

    cmd = [
        "ffmpeg", "-y",
        *loop_args,
        "-framerate", str(FPS),
        "-t", f"{duration:.3f}",
        *input_args,
        "-vf", vf_str,
        "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
        "-threads", "4",
        "-pix_fmt", "yuv420p",
        "-t", f"{duration:.3f}",
        out_mp4,
    ]
    run_ffmpeg(cmd, label=f"slide_{idx:03d}")
    return out_mp4


def _escape_drawtext(text: str) -> str:
    """drawtext 필터용 텍스트 이스케이프 (single-quote 없이 사용)."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    text = text.replace(";", "\\;")
    text = text.replace("%", "%%")
    return text


def _fontfile_arg(fontpath: str) -> str:
    """drawtext fontfile 인자용 — 콜론을 이스케이프."""
    return fontpath.replace("\\", "/").replace(":", "\\:")


# ──────────────────────────────────────────────
# 인트로 생성
# ──────────────────────────────────────────────
def build_intro(tmp_dir: str, assets_dir: Path) -> str | None:
    """인트로 섹션 (5초). assets/intro_bg.png가 없으면 None."""
    bg = assets_dir / "intro_bg.png"
    if not bg.exists():
        print("[INFO] 인트로 건너뜀 (assets/intro_bg.png 없음)")
        return None

    print("[INFO] 인트로 생성 중...")
    dur = 5.0
    total_frames = int(dur * FPS)
    out_mp4 = os.path.join(tmp_dir, "intro.mp4")

    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
    )

    # ── 오디오 ──
    intro_voice = assets_dir / "mascot" / "intro_voice.wav"
    jingle = assets_dir / "jingle.mp3"

    input_args = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", ffmpeg_safe(bg)]
    audio_filter = []
    audio_input_idx = 1

    has_voice = intro_voice.exists()
    has_jingle = jingle.exists()

    if has_voice:
        input_args += ["-i", ffmpeg_safe(intro_voice)]
    if has_jingle:
        input_args += ["-i", ffmpeg_safe(jingle)]

    if has_voice and has_jingle:
        voice_idx = 1
        jingle_idx = 2
        af = f"[{jingle_idx}:a]volume=-12dB[jbg];[{voice_idx}:a][jbg]amix=inputs=2:duration=first[aout]"
        cmd = [
            "ffmpeg", "-y", *input_args,
            "-filter_complex", f"{vf.replace(',', ',')}; {af}".replace("; ", ";"),
            # 실제로는 -vf 와 -filter_complex 병용 불가 → filter_complex로 통합
        ]
        # filter_complex 방식으로 재구성
        fc = f"[0:v]{vf}[vout];[{jingle_idx}:a]volume=-12dB[jbg];[{voice_idx}:a][jbg]amix=inputs=2:duration=first[aout]"
        cmd = [
            "ffmpeg", "-y", *input_args,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.3f}",
            out_mp4,
        ]
    elif has_voice:
        cmd = [
            "ffmpeg", "-y", *input_args,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-t", f"{dur:.3f}",
            out_mp4,
        ]
    else:
        # 오디오 없이 영상만
        cmd = [
            "ffmpeg", "-y", *input_args,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-t", f"{dur:.3f}",
            out_mp4,
        ]

    run_ffmpeg(cmd, label="intro")
    print("[OK] 인트로 생성 완료")
    return out_mp4


# ──────────────────────────────────────────────
# 퀴즈 섹션 생성
# ──────────────────────────────────────────────
def build_quiz(tmp_dir: str, ep_dir: Path) -> list:
    """퀴즈 섹션 mp4 리스트를 반환합니다.

    output/ep{N}/quiz/ 폴더에서 PNG + WAV를 읽어 슬라이드별로 mp4 생성.
    구조:
      quiz_intro(3s) → q1(3s) + 관련장면(3s) + think(5s) + a1(3s) → q2 → q3
    """
    quiz_dir = ep_dir / "quiz"
    audio_dir = ep_dir / "audio"

    if not quiz_dir.exists() or not any(quiz_dir.iterdir()):
        print("[INFO] 퀴즈 건너뜀 (quiz/ 폴더 없음 또는 비어 있음)")
        return []

    print("[INFO] 퀴즈 섹션 생성 중...")
    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    quiz_mp4s = []

    def _make_quiz_slide(name: str, dur: float) -> str | None:
        """quiz_dir/{name}.png + audio_dir/{name}.wav → mp4"""
        png = quiz_dir / f"{name}.png"
        wav = audio_dir / f"{name}.wav"
        if not png.exists():
            print(f"  [WARNING] {name}.png 없음 — 건너뜀")
            return None

        out = os.path.join(tmp_dir, f"quiz_{name}.mp4")
        total_frames = max(int(dur * FPS), 2)

        prescale = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=yuv420p"

        input_args = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", ffmpeg_safe(png)]
        if wav.exists():
            input_args += ["-i", ffmpeg_safe(wav)]

        cmd = [
            "ffmpeg", "-y", *input_args,
            "-vf", prescale,
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-threads", "4",
            "-pix_fmt", "yuv420p",
        ]
        if wav.exists():
            # apad로 오디오를 dur까지 무음 패딩, 44100Hz stereo로 정규화
            cmd += ["-af", f"apad=whole_dur={dur:.3f}", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "44100", "-ac", "2"]
        cmd += ["-t", f"{dur:.3f}", out]

        run_ffmpeg(cmd, label=f"quiz_{name}")
        return out

    def _make_countdown_slide(q_png_path: str, out_path: str):
        """카운트다운 슬라이드 생성 (5,4,3,2,1 + 비프음, 5초)"""
        dur = 5.0
        fontfile = _fontfile_arg(find_korean_font())
        prescale = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1"
        )
        # enable 표현식에 콤마 없이: (t>=i)*(t<i+1) 방식 사용
        drawtext_filters = ",".join([
            f"drawtext=fontfile='{fontfile}':text='{num}'"
            f":fontsize=200:fontcolor=yellow"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":enable='gte(t\\,{i})*lt(t\\,{i + 1})'"
            f":borderw=8:bordercolor=black"
            for i, num in enumerate([5, 4, 3, 2, 1])
        ])
        vf = f"{prescale},{drawtext_filters},format=yuv420p"

        # 비프음: 매 초 시작 0.08초 880Hz 사인파
        beep_wav = os.path.join(tmp_dir, f"countdown_beep_{os.path.basename(out_path)}.wav")
        beep_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"aevalsrc=sin(2*PI*880*t)*(lt(mod(t\\,1)\\,0.08)):s=24000:c=mono",
            "-t", f"{dur:.3f}",
            "-c:a", "pcm_s16le",
            beep_wav,
        ]
        run_ffmpeg(beep_cmd, "countdown_beep")

        if Path(q_png_path).exists():
            img_input = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}",
                         "-i", ffmpeg_safe(Path(q_png_path))]
        else:
            img_input = ["-f", "lavfi",
                         "-i", f"color=c=0x1a1a2e:s={W}x{H}:d={dur:.3f}:r={FPS}"]

        cmd = [
            "ffmpeg", "-y",
            *img_input,
            "-i", beep_wav,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-threads", "4",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", f"{dur:.3f}",
            out_path,
        ]
        run_ffmpeg(cmd, f"countdown_slide_{os.path.basename(out_path)}")

    def _make_quiz_slide_custom(png_path: str, out_path: str, wav_path: str, dur: float):
        """이미지 + 오디오로 고정 길이 슬라이드 생성 (배경 이미지 사용)"""
        prescale = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=yuv420p"
        if Path(png_path).exists():
            img_input = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", ffmpeg_safe(Path(png_path))]
        else:
            img_input = ["-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={W}x{H}:d={dur:.3f}:r={FPS}"]
        cmd = ["ffmpeg", "-y", *img_input, "-i", wav_path,
               "-vf", prescale,
               "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
               "-threads", "4",
               "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
               "-t", f"{dur:.3f}", out_path]
        run_ffmpeg(cmd, "quiz_slide_custom")

    def _concat_wavs(wavs: list, out_wav: str) -> bool:
        """여러 wav를 순서대로 이어붙여 하나의 wav로 저장. 성공 시 True."""
        existing = [w for w in wavs if Path(w).exists()]
        if not existing:
            return False
        if len(existing) == 1:
            # 단일 파일이면 그대로 복사(포맷 정규화)
            cmd = ["ffmpeg", "-y", "-i", ffmpeg_safe(Path(existing[0])),
                   "-ar", "44100", "-ac", "2", out_wav]
            run_ffmpeg(cmd, "quiz_wav_norm")
            return Path(out_wav).exists()
        inputs = []
        for w in existing:
            inputs += ["-i", ffmpeg_safe(Path(w))]
        n = len(existing)
        # 각 입력을 44100/stereo로 정규화 후 concat
        parts = "".join(f"[{i}:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo[a{i}];"
                        for i in range(n))
        concat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
        cmd = ["ffmpeg", "-y", *inputs,
               "-filter_complex", parts + concat,
               "-map", "[aout]", out_wav]
        run_ffmpeg(cmd, "quiz_wav_concat")
        return Path(out_wav).exists()

    # quiz_intro (3s)
    mp4 = _make_quiz_slide("quiz_intro", 3.0)
    if mp4:
        quiz_mp4s.append(mp4)

    # q1, q2, q3 — 문제(안내+본문 낭독) → 카운트다운 5초(비프) → 정답(안내+본문 낭독)
    for qi in range(1, 4):
        # ── 문제 슬라이드: quiz_q{i}.wav(안내) + quiz_q{i}_body.wav(본문) concat ──
        wav_q = audio_dir / f"quiz_q{qi}.wav"
        wav_q_body = audio_dir / f"quiz_q{qi}_body.wav"
        q_png = quiz_dir / f"quiz_q{qi}.png"
        if wav_q_body.exists():
            # 본문 낭독 파일이 있으면 안내+본문 합성 후 낭독 길이만큼 표시
            combined_q = os.path.join(tmp_dir, f"quiz_q{qi}_combined.wav")
            if _concat_wavs([wav_q, wav_q_body], combined_q):
                q_dur = max(get_duration_ffprobe(combined_q), 5.0)
                out_q = os.path.join(tmp_dir, f"quiz_quiz_q{qi}.mp4")
                if q_png.exists():
                    _make_quiz_slide_custom(str(q_png), out_q, combined_q, q_dur)
                    quiz_mp4s.append(out_q)
            else:
                # 폴백: 기존 동작
                q_dur = max(get_duration_ffprobe(str(wav_q)), 5.0) if wav_q.exists() else 5.0
                mp4 = _make_quiz_slide(f"quiz_q{qi}", q_dur)
                if mp4:
                    quiz_mp4s.append(mp4)
        else:
            # 폴백: 본문 wav 없음 → 기존 동작 (안내 TTS + 무음 패딩 5초)
            q_dur = max(get_duration_ffprobe(str(wav_q)), 5.0) if wav_q.exists() else 5.0
            mp4 = _make_quiz_slide(f"quiz_q{qi}", q_dur)
            if mp4:
                quiz_mp4s.append(mp4)

        # ── 카운트다운 슬라이드 (5초 + 비프) — 문제 뒤에 삽입 ──
        countdown_mp4 = os.path.join(tmp_dir, f"quiz_countdown_{qi}.mp4")
        _make_countdown_slide(str(q_png) if q_png.exists() else "", countdown_mp4)
        if Path(countdown_mp4).exists():
            quiz_mp4s.append(countdown_mp4)

        # ── 정답 슬라이드: quiz_a{i}.wav(안내) + quiz_a{i}_body.wav(본문), 최소 3초 ──
        wav_a = audio_dir / f"quiz_a{qi}.wav"
        wav_a_body = audio_dir / f"quiz_a{qi}_body.wav"
        a_png = quiz_dir / f"quiz_a{qi}.png"
        if wav_a_body.exists():
            combined_a = os.path.join(tmp_dir, f"quiz_a{qi}_combined.wav")
            if _concat_wavs([wav_a, wav_a_body], combined_a):
                a_dur = max(get_duration_ffprobe(combined_a), 3.0)
                out_a = os.path.join(tmp_dir, f"quiz_quiz_a{qi}.mp4")
                if a_png.exists():
                    _make_quiz_slide_custom(str(a_png), out_a, combined_a, a_dur)
                    quiz_mp4s.append(out_a)
            else:
                a_dur = max(get_duration_ffprobe(str(wav_a)), 3.0) if wav_a.exists() else 3.0
                mp4 = _make_quiz_slide(f"quiz_a{qi}", a_dur)
                if mp4:
                    quiz_mp4s.append(mp4)
        else:
            # 폴백: 본문 wav 없음 → 기존 동작 (대기 5.0→3.0 단축)
            a_dur = max(get_duration_ffprobe(str(wav_a)), 3.0) if wav_a.exists() else 3.0
            mp4 = _make_quiz_slide(f"quiz_a{qi}", a_dur)
            if mp4:
                quiz_mp4s.append(mp4)

    print(f"[OK] 퀴즈 슬라이드 {len(quiz_mp4s)}개 생성 완료")
    return quiz_mp4s


# ──────────────────────────────────────────────
# 아웃트로 생성
# ──────────────────────────────────────────────
def build_outro(tmp_dir: str, assets_dir: Path) -> str | None:
    """아웃트로 섹션 (10초). mascot_thumbsup.png가 없으면 None."""
    mascot = assets_dir / "mascot" / "mascot_thumbsup.png"
    if not mascot.exists():
        print("[INFO] 아웃트로 건너뜀 (assets/mascot/mascot_thumbsup.png 없음)")
        return None

    print("[INFO] 아웃트로 생성 중...")
    dur = 10.0
    out_mp4 = os.path.join(tmp_dir, "outro.mp4")
    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT

    fontfile = _fontfile_arg(find_korean_font())
    cta_text = _escape_drawtext("구독과 좋아요를 눌러주세요!")

    # 크림 배경(#FFF8E7) 위에 마스코트 오버레이 + 텍스트
    # 배경 생성 → 마스코트 오버레이
    outro_voice = assets_dir / "mascot" / "outro_end.wav"

    input_args = [
        "-f", "lavfi", "-i", f"color=c=0xFFF8E7:s={W}x{H}:d={dur:.1f}:r={FPS}",
        "-loop", "1", "-t", f"{dur:.3f}", "-i", ffmpeg_safe(mascot),
    ]
    if outro_voice.exists():
        input_args += ["-i", ffmpeg_safe(outro_voice)]

    # 마스코트를 중앙에 오버레이 + 텍스트
    vf = (
        f"[1:v]scale=-1:{int(H * 0.6)}[mascot];"
        f"[0:v][mascot]overlay=(W-w)/2:(H-h)/2-40[bg];"
        f"[bg]drawtext=fontfile={fontfile}"
        f":text={cta_text}:fontsize=28:fontcolor=0x333333"
        f":x=(w-text_w)/2:y=h-100[vout]"
    )

    cmd = ["ffmpeg", "-y", *input_args, "-filter_complex", vf, "-map", "[vout]"]
    if outro_voice.exists():
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-t", f"{dur:.3f}",
        out_mp4,
    ]
    run_ffmpeg(cmd, label="outro")
    print("[OK] 아웃트로 생성 완료")
    return out_mp4


# ──────────────────────────────────────────────
# 표지 슬라이드 (썸네일 5초)
# ──────────────────────────────────────────────
def build_cover_slide(tmp_dir: str, ep_dir: Path, assets_dir: Path) -> str | None:
    """표지(썸네일) 슬라이드 5초. thumbnail_a.png → thumbnail_b.png → None."""
    thumbnail = ep_dir / "thumbnail_a.png"
    if not thumbnail.exists():
        thumbnail = ep_dir / "thumbnail_b.png"
    if not thumbnail.exists():
        print("[INFO] 표지 슬라이드 건너뜀 (thumbnail_a.png 없음)")
        return None

    print("[INFO] 표지 슬라이드 생성 중...")
    dur = 5.0
    out_mp4 = os.path.join(tmp_dir, "cover.mp4")
    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT

    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
    )

    img_args = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", ffmpeg_safe(thumbnail)]
    bgm_path = assets_dir / "bgm.mp3"

    if bgm_path.exists():
        fc = f"[0:v]{vf}[vout];[1:a]volume=-20dB[aout]"
        cmd = [
            "ffmpeg", "-y",
            *img_args,
            "-stream_loop", "-1", "-i", ffmpeg_safe(bgm_path),
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.3f}",
            out_mp4,
        ]
    else:
        # 무음 오디오 (concat 호환성)
        fc = f"[0:v]{vf}[vout]"
        cmd = [
            "ffmpeg", "-y",
            *img_args,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.3f}",
            out_mp4,
        ]

    run_ffmpeg(cmd, label="cover_slide")
    print("[OK] 표지 슬라이드 생성 완료")
    return out_mp4


# ──────────────────────────────────────────────
# 메인 조립
# ──────────────────────────────────────────────
def assemble_video(
    ep_dir: Path,
    slides: list,
    image_files: list,
    total_duration: float,
    tmp_dir: str,
    meta: dict,
    assets_dir: Path,
):
    """FFmpeg로 최종 영상을 조립합니다."""
    audio_path = ep_dir / "audio" / "full_audio.wav"
    srt_path = ep_dir / "subtitles.srt"
    output_path = ep_dir / "video.mp4"

    # 오디오 파일 확인
    if not audio_path.exists():
        print(f"[ERROR] 오디오 파일을 찾을 수 없습니다: {audio_path}")
        sys.exit(1)
    print(f"[OK] 오디오: {audio_path}")

    has_subtitles = srt_path.exists()
    if has_subtitles:
        print(f"[OK] 자막: {srt_path}")
    else:
        print(f"[WARNING] 자막 파일 없음: {srt_path} (자막 없이 진행)")

    # ── 각 슬라이드 표시 시간 계산 ──
    durations = []
    for i in range(len(slides)):
        if i == 0:
            img_start = 0.0
        else:
            img_start = slides[i - 1].get("end", 0.0)
        if i == len(slides) - 1:
            img_end = total_duration
        else:
            img_end = slides[i].get("end", img_start + 5.0)
        dur = round(img_end - img_start, 3)
        if dur < 0.1:
            dur = 0.1
        durations.append(dur)
        print(f"  슬라이드 {slides[i].get('slide', i):2d}: {img_start:.1f}s ~ {img_end:.1f}s ({dur:.1f}s)")

    # ── 1단계: 개별 슬라이드 mp4 생성 (Ken Burns + Fade) ──
    print(f"\n[1/4] 각 슬라이드 영상 생성 중 ({len(slides)}개)...")

    story_title = meta.get("story_title", "")
    unit = meta.get("unit", "")

    slide_mp4s = []
    n_slides = len(image_files)
    for i, (img, dur) in enumerate(zip(image_files, durations)):
        mp4 = build_slide_mp4(
            idx=i,
            is_first=(i == 0),
            is_last=(i == n_slides - 1),
            img_path=img,
            duration=dur,
            tmp_dir=tmp_dir,
        )
        slide_mp4s.append(mp4)
        print(f"  슬라이드 {i:2d}: {dur:.1f}s OK")

    # ── 2단계: 표지 / 인트로 / 퀴즈 / 아웃트로 ──
    print(f"\n[2/4] 부가 섹션 생성...")
    cover_mp4 = build_cover_slide(tmp_dir, ep_dir, assets_dir)
    intro_mp4 = build_intro(tmp_dir, assets_dir)
    quiz_mp4s = build_quiz(tmp_dir, ep_dir)
    outro_mp4 = build_outro(tmp_dir, assets_dir)

    # ── 3단계: 본편 조립 (슬라이드 + full_audio + 자막) ──
    print(f"\n[3/5] 본편 영상 조립 중 (slides + audio + subtitles)...")

    # 3a. 본편 슬라이드만 concat (video only)
    main_segments = []
    if intro_mp4:
        main_segments.append(intro_mp4)
    main_segments.extend(slide_mp4s)

    main_concat_path = os.path.join(tmp_dir, "concat_main.txt")
    with open(main_concat_path, "w", encoding="utf-8") as f:
        for seg in main_segments:
            safe = str(Path(seg).resolve()).replace("\\", "/")
            f.write(f"file '{safe}'\n")

    raw_main = os.path.join(tmp_dir, "raw_main.mp4")
    cmd_main = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", main_concat_path,
        "-c:v", "libx264", "-crf", "20", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-an",
        raw_main,
    ]
    run_ffmpeg(cmd_main, label="concat_main")
    print("[OK] 본편 슬라이드 연결 완료")

    # ── 4단계: 본편에 오디오 + 자막 합성 ──
    print(f"\n[4/5] 본편 오디오+자막 합성 중 ({OUTPUT_WIDTH}x{OUTPUT_HEIGHT})...")

    bgm_path = assets_dir / "bgm.mp3"
    has_bgm = bgm_path.exists()

    # 본편 영상 (audio 길이에 맞춰 정확히 자르기)
    main_video = os.path.join(tmp_dir, "main_with_audio.mp4")
    cmd_final = [
        "ffmpeg", "-y",
        "-i", raw_main,
        "-i", ffmpeg_safe(audio_path),
    ]
    next_input_idx = 2

    if has_bgm:
        cmd_final += ["-stream_loop", "-1", "-i", ffmpeg_safe(bgm_path)]
        bgm_idx = next_input_idx
        next_input_idx += 1

    # 오디오 필터 구성
    if has_bgm:
        af = f"[{bgm_idx}:a]volume=-20dB[bgm];[1:a][bgm]amix=inputs=2:duration=first[aout]"
        audio_map = ["-map", "[aout]"]
    else:
        af = None
        audio_map = ["-map", "1:a"]

    # 비디오 필터: 자막
    vf_parts = []
    if has_subtitles:
        srt_escaped = ffmpeg_safe_filter(srt_path)
        lang = meta.get("language", "ko")
        if lang == "ko":
            subtitle_font = "Malgun Gothic"
            sub_filter = f"subtitles='{srt_escaped}':force_style='{_subtitle_style(subtitle_font)}'"
        else:
            nunito_path = ensure_subtitle_font(assets_dir)
            if nunito_path:
                fontsdir_escaped = ffmpeg_safe_filter(nunito_path.parent)
                subtitle_font = "Nunito ExtraBold"
                sub_filter = (
                    f"subtitles='{srt_escaped}'"
                    f":fontsdir='{fontsdir_escaped}'"
                    f":force_style='{_subtitle_style(subtitle_font)}'"
                )
            else:
                _fallback_style = _subtitle_style("Arial")
                sub_filter = f"subtitles='{srt_escaped}':force_style='{_fallback_style}'"
        vf_parts.append(sub_filter)

    if af and vf_parts:
        fc = f"[0:v]{','.join(vf_parts)}[vout];{af}"
        cmd_final += ["-filter_complex", fc, "-map", "[vout]", *audio_map]
    elif af:
        cmd_final += ["-filter_complex", af, "-map", "0:v", *audio_map]
    elif vf_parts:
        cmd_final += ["-vf", ",".join(vf_parts), "-map", "0:v", *audio_map]
    else:
        cmd_final += ["-map", "0:v", *audio_map]

    # 오디오 길이에 맞춰 정확히 자르기 (-t 사용)
    audio_dur = get_duration_ffprobe(ffmpeg_safe(audio_path))
    if audio_dur > 0:
        cmd_final += ["-t", f"{audio_dur:.3f}"]

    cmd_final += [
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-ar", "44100",   # 오디오 샘플레이트 정규화 (24kHz→44.1kHz concat 호환)
        "-ac", "2",       # 스테레오 정규화
        "-movflags", "+faststart",
        main_video,
    ]

    print(f"  명령: {' '.join(cmd_final[:12])}...")
    run_ffmpeg(cmd_final, label="main_merge")
    print("[OK] 본편 영상 완성")

    # ── 5단계: 퀴즈/아웃트로 연결 → 최종 영상 ──
    print(f"\n[5/5] 최종 영상 결합 중...")

    # 표지 → 본편 → 퀴즈 → 아웃트로
    final_segments = []
    if cover_mp4:
        final_segments.append(cover_mp4)
    final_segments.append(main_video)
    if quiz_mp4s:
        # 퀴즈 mp4들을 하나로 합치기 (각각 자체 오디오 포함)
        quiz_concat_path = os.path.join(tmp_dir, "concat_quiz.txt")
        with open(quiz_concat_path, "w", encoding="utf-8") as f:
            for qm in quiz_mp4s:
                safe = str(Path(qm).resolve()).replace("\\", "/")
                f.write(f"file '{safe}'\n")
        quiz_merged = os.path.join(tmp_dir, "quiz_merged.mp4")
        # 퀴즈 mp4들은 이미 오디오를 포함하므로 copy로 연결
        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", quiz_concat_path,
            "-c:v", "libx264", "-crf", "20", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-ac", "2",
            quiz_merged,
        ], label="quiz_concat")
        final_segments.append(quiz_merged)
        print(f"[OK] 퀴즈 섹션 합성 완료 ({len(quiz_mp4s)}개)")

    if outro_mp4:
        final_segments.append(outro_mp4)

    if len(final_segments) == 1:
        # 본편만 있으면 그대로 복사
        import shutil
        shutil.copy2(main_video, str(output_path))
    else:
        # 본편 + 퀴즈 + 아웃트로 연결
        final_concat_path = os.path.join(tmp_dir, "concat_final.txt")
        with open(final_concat_path, "w", encoding="utf-8") as f:
            for seg in final_segments:
                safe = str(Path(seg).resolve()).replace("\\", "/")
                f.write(f"file '{safe}'\n")
        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", final_concat_path,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ], label="final_concat")

    # ── 결과 확인 ──
    if not output_path.exists():
        print(f"[ERROR] 출력 파일이 생성되지 않았습니다: {output_path}")
        sys.exit(1)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\n[DONE] 영상 생성 완료!")
    print(f"  파일: {output_path}")
    print(f"  크기: {size_mb:.1f} MB")
    print(f"  해상도: {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} (16:9 가로)")
    print(f"  코덱: H.264 CRF 20 + AAC 192k")

    # ── 길이 검증 ──
    verify_duration(output_path, audio_path, total_duration)


def verify_duration(video_path: Path, audio_path: Path, expected_duration: float):
    """출력 영상의 길이가 오디오/timing과 일치하는지 검증합니다."""
    print("\n[검증] 영상 길이 확인...")

    video_dur = get_duration_ffprobe(str(video_path))
    audio_dur = get_duration_ffprobe(str(audio_path))

    if video_dur > 0:
        print(f"  영상 길이: {video_dur:.2f}초")
    if audio_dur > 0:
        print(f"  오디오 길이: {audio_dur:.2f}초")
    print(f"  timing.json 예상: {expected_duration:.2f}초")

    if video_dur > 0 and audio_dur > 0:
        diff = abs(video_dur - audio_dur)
        if diff > 1.0:
            print(f"  [WARNING] 영상-오디오 길이 차이: {diff:.2f}초 (인트로/퀴즈/아웃트로 포함 시 정상)")
        else:
            print(f"  [OK] 영상-오디오 길이 일치 (차이: {diff:.2f}초)")

    if video_dur > 0 and expected_duration > 0:
        diff_timing = abs(video_dur - expected_duration)
        if diff_timing > 1.0:
            print(f"  [WARNING] 영상-timing 길이 차이: {diff_timing:.2f}초 (인트로/퀴즈/아웃트로 포함 시 정상)")
        else:
            print(f"  [OK] 영상-timing 길이 일치 (차이: {diff_timing:.2f}초)")


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="AI 동화책 최종 영상 조립 — 가로 16:9 (Ken Burns + 자막 + BGM)"
    )
    parser.add_argument(
        "--ep", type=int, default=None,
        help="에피소드 번호 (예: 1 → output/ep01)"
    )
    parser.add_argument(
        "--dir", type=str, default=None,
        help="출력 디렉터리 직접 지정 (예: output/bsl01)"
    )
    args = parser.parse_args()

    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")
    assets_dir = Path("assets")

    print("=" * 60)
    print(f"  06_assemble_video.py — {ep_dir}")
    print(f"  출력 해상도: {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} (가로 16:9)")
    print(f"  작업 폴더: {ep_dir.resolve()}")
    print("=" * 60)

    if not ep_dir.exists():
        print(f"[ERROR] 에피소드 폴더가 없습니다: {ep_dir}")
        print("  먼저 이전 단계(01~05)를 실행하세요.")
        sys.exit(1)

    if not check_ffmpeg():
        sys.exit(1)

    # timing.json 로드
    timing_data = load_timing(ep_dir)
    slides = timing_data["slides"]
    total_duration = timing_data["total_duration"]

    # story.json meta 로드
    meta = load_story_meta(ep_dir)

    # 이미지 파일 확인
    image_files = find_images(ep_dir, slides)

    # 임시 디렉토리에서 작업
    with tempfile.TemporaryDirectory(prefix="fairytale_video_") as tmp_dir:
        print(f"\n[INFO] 임시 폴더: {tmp_dir}")
        assemble_video(ep_dir, slides, image_files, total_duration, tmp_dir, meta, assets_dir)

    print("\n다음 단계:")
    print(f"  영상 확인: {ep_dir}/video.mp4 재생")
    print(f"  YouTube 업로드 준비 완료! (16:9 가로 영상)")


if __name__ == "__main__":
    main()
