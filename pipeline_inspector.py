#!/usr/bin/env python3
"""
pipeline_inspector.py
AI 동화 파이프라인 — 공식 품질 점검기

6개 영역별 점수 계산 + 문제 발견 시 자체 순환 자동 수정.

영역 및 배점:
  1. story.json 품질          25점
  2. 이미지 완성도            20점
  3. TTS / 오디오 완성도      20점
  4. 타이밍 일관성            10점
  5. Shorts 선정 품질         15점
  6. 최종 산출물 완성도       10점
  총점 100점

자체 순환 점검:
  - 자동 수정 가능한 이슈(특수문자, 누락 파일 등) 발견 시 파이프라인 재실행
  - 재실행 후 점수 재계산 → 개선 없으면 중단
  - 최대 --max-cycles 회 순환

사용법:
  python pipeline_inspector.py --dir output/id01
  python pipeline_inspector.py --ep 1
  python pipeline_inspector.py --dir output/id01 --auto-fix        (자동 수정)
  python pipeline_inspector.py --dir output/id01 --auto-fix --max-cycles 3
  python pipeline_inspector.py --dir output/id01 --json report.json (JSON 리포트 저장)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# .env의 FFMPEG_BIN 우선, 없으면 시스템 PATH의 ffmpeg 사용
import shutil as _shutil
FFMPEG_BIN = os.getenv("FFMPEG_BIN") or (
    r"C:\Users\권준구\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin"
)

# 내레이터 혼입 감지 패턴 (한국어 / 인도네시아어)
NARRATOR_LEAKAGE_KO = re.compile(
    r'(라고\s*(말했|외쳤|소리쳤|속삭였|물었|답했|웃었)'
    r'|이라며|이라고\s*했|라고\s*했'
    r'|목소리로|표정으로|눈물을\s*흘리며)'
)
NARRATOR_LEAKAGE_ID = re.compile(
    r'(bisik\s+\w+|kata\s+\w+|seru\w*\s+\w+|ucap\w*\s+\w+'
    r'|jawab\w*\s+\w+|tanya\w*\s+\w+|ujar\w*\s+\w+'
    r'|bisiknya|serunya|katanya|ujarnya|jawabnya)'
)
SPECIAL_CHARS = re.compile(r'[…—―·•]')

# 한글 유니코드 범위
HANGUL_RE = re.compile(r'[\uAC00-\uD7A3]')


# ──────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────

@dataclass
class Issue:
    severity: str        # ERROR / WARN / INFO
    area: str
    code: str            # 고유 코드
    message: str
    auto_fixable: bool = False
    fix_action: str = ""  # 수정에 필요한 파이프라인 단계

@dataclass
class AreaResult:
    name: str
    max_score: int
    score: int
    issues: List[Issue] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return round(self.score / self.max_score * 100, 1) if self.max_score else 0.0

@dataclass
class InspectionReport:
    ep_dir: str
    timestamp: str
    cycle: int
    areas: List[AreaResult] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        return sum(a.score for a in self.areas)

    @property
    def total_max(self) -> int:
        return sum(a.max_score for a in self.areas)

    @property
    def all_issues(self) -> List[Issue]:
        return [i for a in self.areas for i in a.issues]

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.all_issues if i.severity == "ERROR"]

    @property
    def warns(self) -> List[Issue]:
        return [i for i in self.all_issues if i.severity == "WARN"]


# ──────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────

def get_wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), 'rb') as wf:
            frames = wf.getnframes()
            rate   = wf.getframerate()
            ch     = wf.getnchannels()
            sw     = wf.getsampwidth()
            if rate == 0:
                return 0.0
            if frames >= 2147483647:
                data = path.stat().st_size - 44
                return max(data // (ch * sw), 0) / float(rate)
            return frames / float(rate)
    except Exception:
        return -1.0


def get_media_duration(path: Path) -> Optional[float]:
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', str(path)],
            capture_output=True, text=True, timeout=30,
            env=_ffmpeg_env()
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def _ffmpeg_env():
    env = os.environ.copy()
    if FFMPEG_BIN and FFMPEG_BIN not in env.get("PATH", ""):
        env["PATH"] = FFMPEG_BIN + os.pathsep + env.get("PATH", "")
    return env


def parse_srt_last_end(path: Path) -> Optional[float]:
    try:
        content = path.read_text(encoding='utf-8')
        matches = re.findall(r'\d+:\d+:\d+,\d+\s*-->\s*(\d+:\d+:\d+,\d+)', content)
        if not matches:
            return None
        m = re.match(r'(\d+):(\d+):(\d+),(\d+)', matches[-1])
        if not m:
            return None
        h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        return h * 3600 + mi * 60 + s + ms / 1000.0
    except Exception:
        return None


def run_script(script: str, ep_dir: Path) -> bool:
    cmd = [sys.executable, script, "--dir", str(ep_dir)]
    print(f"    [AUTO-FIX] 실행: {' '.join(cmd)}", flush=True)
    try:
        r = subprocess.run(
            cmd, cwd=Path(__file__).parent,
            env=_ffmpeg_env()
        )
        return r.returncode == 0
    except Exception as e:
        print(f"    [AUTO-FIX] 예외: {e}")
        return False


# ──────────────────────────────────────────────────────────
# 1. story.json 품질 (25점)
# ──────────────────────────────────────────────────────────

def check_story(ep_dir: Path) -> AreaResult:
    area = AreaResult("story.json 품질", max_score=25, score=0)
    story_path = ep_dir / "story.json"

    # 존재 (5점)
    if not story_path.exists():
        area.issues.append(Issue("ERROR", "story", "S01", "story.json 없음", True, "generate_story"))
        return area
    area.score += 5

    try:
        story = json.loads(story_path.read_text(encoding='utf-8'))
    except Exception as e:
        area.issues.append(Issue("ERROR", "story", "S02", f"story.json 파싱 실패: {e}"))
        return area

    meta = story.get("meta", {})
    lang = meta.get("language", "ko")
    slides = story.get("slides", [])

    # meta 필드 (3점)
    for field_name in ("language", "story_title"):
        if not meta.get(field_name):
            area.issues.append(Issue("WARN", "story", "S03", f"meta.{field_name} 누락"))
        else:
            area.score += 1
    if lang in ("ko", "id"):
        area.score += 1

    # image_prompt 완성도 (4점)
    missing_prompt = [s["slide_number"] for s in slides if not s.get("image_prompt")]
    if missing_prompt:
        area.issues.append(Issue("WARN", "story", "S04",
            f"image_prompt 누락 슬라이드: {missing_prompt}"))
    else:
        area.score += 4

    # speaker/voice 일치 (5점)
    speaker_mismatch = []
    for sl in slides:
        for i, seg in enumerate(sl.get("tts_segments", [])):
            sp = seg.get("speaker", "")
            vo = seg.get("voice", "")
            if sp and vo and sp != vo:
                speaker_mismatch.append(f"슬라이드{sl['slide_number']}-seg{i}: speaker={sp} voice={vo}")
    if speaker_mismatch:
        area.issues.append(Issue("ERROR", "story", "S05",
            f"speaker/voice 불일치 {len(speaker_mismatch)}건: {speaker_mismatch[:3]}",
            False))
    else:
        area.score += 5

    # 특수문자 사용 금지 (4점)
    special_hits = []
    for sl in slides:
        for seg in sl.get("tts_segments", []):
            text = seg.get("text", "")
            if SPECIAL_CHARS.search(text):
                special_hits.append(f"슬라이드{sl['slide_number']}: {text[:40]}")
    if special_hits:
        area.issues.append(Issue("WARN", "story", "S06",
            f"TTS 특수문자 감지 {len(special_hits)}건 (…—― 금지): {special_hits[:2]}",
            True, "fix_special_chars"))
    else:
        area.score += 4

    # 내레이터 텍스트 대화 세그먼트 혼입 점검 (4점)
    leakage_pattern = NARRATOR_LEAKAGE_ID if lang == "id" else NARRATOR_LEAKAGE_KO
    leakage_hits = []
    for sl in slides:
        for i, seg in enumerate(sl.get("tts_segments", [])):
            sp   = seg.get("speaker", "narrator")
            text = seg.get("text", "")
            if sp != "narrator" and leakage_pattern.search(text):
                leakage_hits.append(
                    f"슬라이드{sl['slide_number']}-seg{i} [{sp}]: {text[:60]}"
                )
    if leakage_hits:
        area.issues.append(Issue("WARN", "story", "S07",
            f"내레이터 서술문 대화 혼입 의심 {len(leakage_hits)}건: {leakage_hits[:2]}",
            False))
    else:
        area.score += 4

    return area


# ──────────────────────────────────────────────────────────
# 2. 이미지 완성도 (20점)
# ──────────────────────────────────────────────────────────

def check_images(ep_dir: Path) -> AreaResult:
    area = AreaResult("이미지 완성도", max_score=20, score=0)
    story_path = ep_dir / "story.json"
    images_dir = ep_dir / "images"
    plan_path  = ep_dir / "shorts_plan.json"

    if not story_path.exists():
        area.issues.append(Issue("ERROR", "images", "I00", "story.json 없어 이미지 검사 불가"))
        return area
    story = json.loads(story_path.read_text(encoding='utf-8'))
    slides = story.get("slides", [])

    # 16:9 이미지 존재 (12점)
    missing_16 = []
    small_files = []
    for sl in slides:
        n = sl["slide_number"]
        p = images_dir / f"slide_{n:02d}.png"
        if not p.exists():
            missing_16.append(n)
        elif p.stat().st_size < 10_000:
            small_files.append(n)

    if missing_16:
        area.issues.append(Issue("ERROR", "images", "I01",
            f"16:9 이미지 {len(missing_16)}개 누락: {missing_16}", True, "generate_images"))
    else:
        area.score += 12

    if small_files:
        area.issues.append(Issue("WARN", "images", "I02",
            f"이미지 크기 너무 작음(<10KB) {len(small_files)}개: {small_files} (생성 실패 의심)",
            True, "generate_images"))

    # 9:16 이미지 (Shorts 대상) (5점)
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        ss = plan.get("start_slide", 0)
        es = plan.get("end_slide", 0)
        missing_916 = []
        for n in range(ss, es + 1):
            p = images_dir / f"slide_{n:02d}_9x16.png"
            if not p.exists():
                missing_916.append(n)
        if missing_916:
            area.issues.append(Issue("WARN", "images", "I03",
                f"Shorts 9:16 이미지 {len(missing_916)}개 누락 (Mode B로 fallback): {missing_916}",
                True, "generate_images"))
        else:
            area.score += 5
    else:
        area.issues.append(Issue("INFO", "images", "I04",
            "shorts_plan.json 없음 — 9:16 이미지 점검 건너뜀"))
        area.score += 3   # 부분 점수

    # 이미지 디렉토리 존재 (3점)
    if images_dir.exists():
        area.score += 3
    else:
        area.issues.append(Issue("ERROR", "images", "I05",
            "images/ 디렉토리 없음", True, "generate_images"))

    return area


# ──────────────────────────────────────────────────────────
# 3. TTS / 오디오 완성도 (20점)
# ──────────────────────────────────────────────────────────

def check_audio(ep_dir: Path) -> AreaResult:
    area  = AreaResult("TTS/오디오 완성도", max_score=20, score=0)
    audio_dir   = ep_dir / "audio"
    timing_path = audio_dir / "timing.json"
    full_wav    = audio_dir / "full_audio.wav"
    story_path  = ep_dir / "story.json"

    # timing.json (5점)
    if not timing_path.exists():
        area.issues.append(Issue("ERROR", "audio", "A01",
            "timing.json 없음", True, "generate_tts"))
        return area
    area.score += 5

    timing = json.loads(timing_path.read_text(encoding='utf-8'))

    # 세그먼트 파일 존재 (10점)
    if not story_path.exists():
        area.issues.append(Issue("ERROR", "audio", "A02", "story.json 없어 세그먼트 검사 불가"))
    else:
        story  = json.loads(story_path.read_text(encoding='utf-8'))
        slides = story.get("slides", [])
        missing_segs = []
        zero_dur_segs = []
        for sl in slides:
            n    = sl["slide_number"]
            segs = sl.get("tts_segments", [])
            for i in range(len(segs)):
                p = audio_dir / f"slide_{n:02d}_seg_{i:02d}.wav"
                if not p.exists():
                    missing_segs.append(p.name)
                else:
                    dur = get_wav_duration(p)
                    if dur <= 0.1:
                        zero_dur_segs.append(p.name)

        if missing_segs:
            area.issues.append(Issue("ERROR", "audio", "A03",
                f"TTS 세그먼트 {len(missing_segs)}개 누락: {missing_segs[:5]}",
                True, "generate_tts"))
        else:
            area.score += 8

        if zero_dur_segs:
            area.issues.append(Issue("WARN", "audio", "A04",
                f"재생 시간 0초 세그먼트 {len(zero_dur_segs)}개: {zero_dur_segs[:3]}",
                True, "generate_tts"))
        elif not missing_segs:
            area.score += 2

    # full_audio.wav (5점)
    if not full_wav.exists():
        area.issues.append(Issue("ERROR", "audio", "A05",
            "full_audio.wav 없음", True, "concat_audio"))
    else:
        dur = get_wav_duration(full_wav)
        if dur < 5.0:
            area.issues.append(Issue("ERROR", "audio", "A06",
                f"full_audio.wav 너무 짧음: {dur:.1f}초", True, "concat_audio"))
        else:
            area.score += 5

    return area


# ──────────────────────────────────────────────────────────
# 4. 타이밍 일관성 (10점)
# ──────────────────────────────────────────────────────────

def check_timing(ep_dir: Path) -> AreaResult:
    area = AreaResult("타이밍 일관성", max_score=10, score=0)
    timing_path = ep_dir / "audio" / "timing.json"

    if not timing_path.exists():
        area.issues.append(Issue("ERROR", "timing", "T01", "timing.json 없음"))
        return area

    timing   = json.loads(timing_path.read_text(encoding='utf-8'))
    segments = timing.get("segments", [])
    slides   = timing.get("slides", [])
    total    = timing.get("total_duration", 0)

    # start+duration=end 일관성 (5점)
    timing_errors = []
    for i, seg in enumerate(segments):
        s, d, e = seg.get("start", 0), seg.get("duration", 0), seg.get("end", 0)
        if abs(s + d - e) > 0.02:
            timing_errors.append(f"seg{i}: {s:.3f}+{d:.3f}≠{e:.3f}")
    if timing_errors:
        area.issues.append(Issue("ERROR", "timing", "T02",
            f"세그먼트 타이밍 불일치 {len(timing_errors)}건: {timing_errors[:3]}"))
    else:
        area.score += 5

    # 슬라이드 연속성 (3점)
    gap_errors = []
    for i in range(1, len(slides)):
        prev_end   = slides[i-1].get("end", 0)
        curr_start = slides[i].get("start", 0)
        gap        = curr_start - prev_end
        if gap < -0.05 or gap > 3.0:
            gap_errors.append(f"슬라이드{slides[i-1]['slide']}→{slides[i]['slide']}: 갭={gap:.2f}초")
    if gap_errors:
        area.issues.append(Issue("WARN", "timing", "T03",
            f"슬라이드 간 비정상 갭 {len(gap_errors)}건: {gap_errors[:3]}"))
    else:
        area.score += 3

    # total_duration 합리적 범위 (2점)
    if total < 30:
        area.issues.append(Issue("ERROR", "timing", "T04",
            f"total_duration 너무 짧음: {total:.1f}초 (최소 30초)"))
    elif total > 900:
        area.issues.append(Issue("WARN", "timing", "T05",
            f"total_duration 매우 긺: {total:.1f}초 (15분 초과)"))
    else:
        area.score += 2

    return area


# ──────────────────────────────────────────────────────────
# 5. Shorts 선정 품질 (15점)
# ──────────────────────────────────────────────────────────

def check_shorts_plan(ep_dir: Path) -> AreaResult:
    area = AreaResult("Shorts 선정 품질", max_score=15, score=0)
    plan_path   = ep_dir / "shorts_plan.json"
    story_path  = ep_dir / "story.json"
    timing_path = ep_dir / "audio" / "timing.json"
    images_dir  = ep_dir / "images"

    # shorts_plan.json 존재 (3점)
    if not plan_path.exists():
        area.issues.append(Issue("WARN", "shorts", "SH01",
            "shorts_plan.json 없음 (09b가 실시간 분석으로 대체)", True, "analyze_shorts"))
        area.score += 1   # 부분 점수
        return area
    area.score += 3

    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    ss   = plan.get("start_slide", 0)
    es   = plan.get("end_slide", 0)
    hook = plan.get("hook_text", "")
    score_val = plan.get("score", 0)

    # start_slide <= end_slide 검증 (3점)
    if ss > es:
        area.issues.append(Issue("ERROR", "shorts", "SH02",
            f"start_slide({ss}) > end_slide({es}) — 범위 역전!",
            True, "analyze_shorts"))
    elif ss == es:
        area.issues.append(Issue("WARN", "shorts", "SH03",
            f"단일 슬라이드 선정 (start=end={ss}) — 너무 짧을 수 있음"))
        area.score += 2
    else:
        area.score += 3

    # 구간 길이 45~75초 검증 (3점)
    if timing_path.exists():
        timing = json.loads(timing_path.read_text(encoding='utf-8'))
        by_slide = {s["slide"]: s for s in timing.get("slides", [])}
        if ss in by_slide and es in by_slide:
            duration = by_slide[es]["end"] - by_slide[ss]["start"]
            if duration < 30:
                area.issues.append(Issue("ERROR", "shorts", "SH04",
                    f"Shorts 구간 너무 짧음: {duration:.1f}초 (최소 30초)",
                    True, "analyze_shorts"))
            elif duration < 45:
                area.issues.append(Issue("WARN", "shorts", "SH05",
                    f"Shorts 구간 짧음: {duration:.1f}초 (권장 45~75초)"))
                area.score += 2
            elif duration > 90:
                area.issues.append(Issue("WARN", "shorts", "SH06",
                    f"Shorts 구간 너무 긺: {duration:.1f}초 (권장 45~75초)"))
                area.score += 2
            else:
                area.score += 3
        else:
            area.issues.append(Issue("WARN", "shorts", "SH07",
                f"timing.json에서 슬라이드 {ss} 또는 {es} 찾을 수 없음"))
    else:
        area.issues.append(Issue("INFO", "shorts", "SH08",
            "timing.json 없어 Shorts 구간 길이 검증 불가"))
        area.score += 1

    # hook_text 언어 일치 (3점)
    if not hook:
        area.issues.append(Issue("WARN", "shorts", "SH09",
            "hook_text 비어있음", True, "analyze_shorts"))
    else:
        lang = "ko"
        if story_path.exists():
            story = json.loads(story_path.read_text(encoding='utf-8'))
            lang  = story.get("meta", {}).get("language", "ko")

        has_hangul = bool(HANGUL_RE.search(hook))
        if lang == "ko" and not has_hangul:
            area.issues.append(Issue("WARN", "shorts", "SH10",
                f"한국어 에피소드인데 hook_text에 한글 없음: '{hook}'",
                True, "analyze_shorts"))
        elif lang == "id" and has_hangul:
            area.issues.append(Issue("ERROR", "shorts", "SH11",
                f"인도네시아어 에피소드인데 hook_text에 한글 포함: '{hook}'",
                True, "analyze_shorts"))
        elif len(hook) > 20:
            area.issues.append(Issue("WARN", "shorts", "SH12",
                f"hook_text가 너무 김: {len(hook)}자 (권장 15자 이내): '{hook}'"))
            area.score += 2
        else:
            area.score += 3

    # 선정 슬라이드 이미지 존재 (3점)
    missing_imgs = [n for n in range(ss, es + 1)
                    if not (images_dir / f"slide_{n:02d}.png").exists()]
    if missing_imgs:
        area.issues.append(Issue("ERROR", "shorts", "SH13",
            f"Shorts 구간 이미지 {len(missing_imgs)}개 누락: {missing_imgs}",
            True, "generate_images"))
    else:
        area.score += 3

    return area


# ──────────────────────────────────────────────────────────
# 6. 최종 산출물 완성도 (10점)
# ──────────────────────────────────────────────────────────

def check_outputs(ep_dir: Path) -> AreaResult:
    area = AreaResult("최종 산출물 완성도", max_score=10, score=0)
    timing_path = ep_dir / "audio" / "timing.json"

    ref_duration = None
    if timing_path.exists():
        t = json.loads(timing_path.read_text(encoding='utf-8'))
        ref_duration = t.get("total_duration")

    # video.mp4 (5점)
    video = ep_dir / "video.mp4"
    if not video.exists():
        area.issues.append(Issue("WARN", "outputs", "O01",
            "video.mp4 없음", True, "assemble_video"))
    else:
        dur = get_media_duration(video)
        if dur is None or dur < 5:
            area.issues.append(Issue("ERROR", "outputs", "O02",
                f"video.mp4 재생 불가 또는 너무 짧음 ({dur}초)"))
        elif ref_duration and abs(dur - ref_duration) > 1.0:
            area.issues.append(Issue("WARN", "outputs", "O03",
                f"video.mp4({dur:.1f}s) vs audio({ref_duration:.1f}s) 차이 1초 초과"))
            area.score += 3
        else:
            area.score += 5

    # shorts.mp4 또는 shorts_smart_rank1.mp4 (3점)
    shorts = next(
        (ep_dir / name for name in ("shorts.mp4", "shorts_smart_rank1.mp4")
         if (ep_dir / name).exists()),
        None,
    )
    if shorts is None:
        area.issues.append(Issue("WARN", "outputs", "O04",
            "shorts.mp4 없음", True, "smart_shorts"))
    else:
        dur = get_media_duration(shorts)
        if dur is None or dur < 10:
            area.issues.append(Issue("ERROR", "outputs", "O05",
                f"shorts 재생 불가 또는 너무 짧음 ({dur}초)"))
        else:
            area.score += 3

    # 썸네일 (2점)
    for t in ("thumbnail_a.png", "thumbnail_b.png"):
        if not (ep_dir / t).exists():
            area.issues.append(Issue("INFO", "outputs", "O06", f"{t} 없음"))
        else:
            area.score += 1

    return area


# ──────────────────────────────────────────────────────────
# 특수문자 자동 수정
# ──────────────────────────────────────────────────────────

def auto_fix_special_chars(ep_dir: Path) -> bool:
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        return False
    text = story_path.read_text(encoding='utf-8')
    fixed = text.replace('…', ',').replace('—', ',').replace('―', ',').replace('·', ' ').replace('•', ' ')
    if fixed == text:
        return False
    story_path.write_text(fixed, encoding='utf-8')
    print("    [AUTO-FIX] 특수문자 자동 치환 완료 (…→, —→, ―→,)")
    return True


# ──────────────────────────────────────────────────────────
# 전체 점검 실행
# ──────────────────────────────────────────────────────────

STEP_SCRIPTS = {
    "generate_story":   "01_generate_story.py",
    "analyze_shorts":   "01b_analyze_shorts_plan.py",
    "generate_images":  "02_generate_images.py",
    "generate_tts":     "03_generate_tts.py",
    "concat_audio":     "04_concat_audio.py",
    "generate_srt":     "05_generate_srt.py",
    "smart_shorts":     "09b_smart_shorts.py",
    "assemble_video":   "06_assemble_video.py",
}


def run_inspection(ep_dir: Path, cycle: int = 1) -> InspectionReport:
    report = InspectionReport(
        ep_dir    = str(ep_dir),
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cycle     = cycle,
        areas     = [
            check_story(ep_dir),
            check_images(ep_dir),
            check_audio(ep_dir),
            check_timing(ep_dir),
            check_shorts_plan(ep_dir),
            check_outputs(ep_dir),
        ]
    )
    return report


def auto_fix(report: InspectionReport, ep_dir: Path, dry_run: bool = False) -> set:
    """ERROR/WARN 이슈 중 auto_fixable=True 인 것을 수정. 실행된 액션 집합 반환."""
    actions_done = set()
    for issue in report.all_issues:
        if issue.severity not in ("ERROR", "WARN"):
            continue
        if not issue.auto_fixable or not issue.fix_action:
            continue
        action = issue.fix_action

        if action == "fix_special_chars":
            if "fix_special_chars" not in actions_done:
                print(f"  [FIX] 특수문자 치환")
                if not dry_run:
                    auto_fix_special_chars(ep_dir)
                actions_done.add("fix_special_chars")

        elif action in STEP_SCRIPTS and action not in actions_done:
            script = STEP_SCRIPTS[action]
            flags = []
            if action == "analyze_shorts":
                flags = ["--force"]
            print(f"  [FIX] {script} 재실행")
            if not dry_run:
                cmd = [sys.executable, script, "--dir", str(ep_dir)] + flags
                success = subprocess.run(
                    cmd, cwd=Path(__file__).parent, env=_ffmpeg_env()
                ).returncode == 0
                if success:
                    print(f"    [검증] 수정 후 재점검 중...")
                    # fix_action 종류에 따라 해당 check 함수 재실행
                    if action == "generate_story":
                        recheck = check_story(ep_dir)
                    elif action in ("generate_images", "analyze_shorts"):
                        recheck = check_images(ep_dir)
                    elif action in ("generate_tts", "concat_audio"):
                        recheck = check_audio(ep_dir)
                    else:
                        recheck = None
                    if recheck is not None:
                        remaining = [i for i in recheck.issues if i.severity == "ERROR"]
                        if remaining:
                            print(f"    [검증] 수정 후에도 {len(remaining)}개 오류 남음")
                        else:
                            print(f"    [검증] 수정 성공 — 해당 영역 오류 해소")
            actions_done.add(action)

    return actions_done


# ──────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────

SEVERITY_ICON = {"ERROR": "✗", "WARN": "⚠", "INFO": "·"}
SEV_COLOR     = {"ERROR": "\033[91m", "WARN": "\033[93m", "INFO": "\033[37m"}
RESET         = "\033[0m"

def grade(pct: float) -> str:
    if pct >= 95: return "S"
    if pct >= 85: return "A"
    if pct >= 70: return "B"
    if pct >= 55: return "C"
    return "F"

def print_report(report: InspectionReport):
    total = report.total_score
    maxi  = report.total_max
    pct   = round(total / maxi * 100, 1) if maxi else 0
    g     = grade(pct)

    print(f"\n{'='*65}")
    print(f"  파이프라인 품질 점검  [{report.ep_dir}]")
    print(f"  {report.timestamp}  |  Cycle #{report.cycle}")
    print(f"{'='*65}")

    for area in report.areas:
        bar_len = 20
        filled  = round(area.pct / 100 * bar_len)
        bar     = "█" * filled + "░" * (bar_len - filled)
        color   = "\033[92m" if area.pct >= 85 else "\033[93m" if area.pct >= 60 else "\033[91m"
        print(f"  {area.name:<22} {color}{bar}{RESET}  {area.score:2d}/{area.max_score:2d}점 ({area.pct:5.1f}%)")
        for issue in area.issues:
            icon  = SEVERITY_ICON.get(issue.severity, "·")
            color = SEV_COLOR.get(issue.severity, "")
            fix   = " [자동수정가능]" if issue.auto_fixable else ""
            print(f"      {color}{icon} [{issue.code}] {issue.message}{fix}{RESET}")

    print(f"{'─'*65}")
    score_color = "\033[92m" if pct >= 85 else "\033[93m" if pct >= 60 else "\033[91m"
    print(f"  총점: {score_color}{total}/{maxi}점  ({pct:.1f}%)  등급: {g}{RESET}")
    print(f"  오류: {len(report.errors)}건  경고: {len(report.warns)}건")
    print(f"{'='*65}\n")


# ──────────────────────────────────────────────────────────
# 메인 (순환 점검 루프)
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="파이프라인 품질 점검기 (영역별 점수 + 자체 순환 수정)")
    parser.add_argument("--ep",          type=int, help="에피소드 번호")
    parser.add_argument("--dir",         type=str, help="에피소드 디렉토리")
    parser.add_argument("--auto-fix",    action="store_true", help="자동 수정 활성화")
    parser.add_argument("--max-cycles",  type=int, default=3,  help="최대 순환 횟수 (기본: 3)")
    parser.add_argument("--dry-run",     action="store_true",  help="수정 없이 계획만 출력")
    parser.add_argument("--json",        type=str, default="", help="JSON 리포트 저장 경로")
    args = parser.parse_args()

    if not args.ep and not args.dir:
        parser.print_help(); sys.exit(1)

    if args.dir:
        ep_dir = Path(args.dir)
        if not ep_dir.is_absolute():
            ep_dir = Path(__file__).parent / ep_dir
    else:
        ep_dir = Path(__file__).parent / "output" / f"ep{int(args.ep):02d}"

    if not ep_dir.exists():
        print(f"[ERROR] 디렉토리 없음: {ep_dir}"); sys.exit(1)

    prev_fixed_codes: set = set()
    final_report = None

    for cycle in range(1, args.max_cycles + 1):
        print(f"\n{'━'*65}")
        print(f"  ▶ 점검 Cycle #{cycle}/{args.max_cycles}  —  {ep_dir.name}")
        print(f"{'━'*65}")

        report = run_inspection(ep_dir, cycle)
        print_report(report)
        final_report = report

        # 자동 수정 없으면 1회만 실행
        if not args.auto_fix:
            break

        # 수정 가능한 이슈가 없으면 종료
        fixable = [i for i in report.all_issues
                   if i.severity in ("ERROR", "WARN") and i.auto_fixable]
        if not fixable:
            print("  모든 자동 수정 가능 이슈 해결 완료.")
            break

        # 수정 대상 이슈 코드 세트가 이전 cycle과 동일하면 무한 루프 방지를 위해 중단
        fixed_codes = {i.code for i in report.all_issues if i.auto_fixable}
        if fixed_codes == prev_fixed_codes and cycle > 1:
            print("  수정 가능 이슈 변화 없음. 순환 중단.")
            break
        prev_fixed_codes = fixed_codes

        if cycle < args.max_cycles:
            print(f"\n  [AUTO-FIX] 자동 수정 시작...")
            actions = auto_fix(report, ep_dir, args.dry_run)
            if not actions:
                print("  수정할 항목 없음. 순환 종료.")
                break
            print(f"  수정 완료: {', '.join(actions)}")
        else:
            print(f"\n  최대 순환 횟수({args.max_cycles}) 도달.")

    # JSON 리포트 저장
    if args.json and final_report:
        out_path = Path(args.json)
        json_data = {
            "ep_dir":      final_report.ep_dir,
            "timestamp":   final_report.timestamp,
            "cycle":       final_report.cycle,
            "total_score": final_report.total_score,
            "total_max":   final_report.total_max,
            "grade":       grade(final_report.total_score / final_report.total_max * 100),
            "areas": [
                {
                    "name":  a.name,
                    "score": a.score,
                    "max":   a.max_score,
                    "pct":   a.pct,
                    "issues": [
                        {"severity": i.severity, "code": i.code,
                         "message": i.message, "auto_fixable": i.auto_fixable}
                        for i in a.issues
                    ]
                }
                for a in final_report.areas
            ]
        }
        out_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"  JSON 리포트 저장: {out_path}")

    # 최종 상태 코드
    if final_report and final_report.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
