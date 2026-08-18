#!/usr/bin/env python3
"""
05_generate_srt.py — timing.json에서 SRT 자막 직접 생성

사용법:
  python 05_generate_srt.py              # ep01
  python 05_generate_srt.py --ep 3       # ep03
"""

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================================
# 한국어 조사/어미 목록 (줄바꿈 분리 기준)
# ============================================================
PARTICLES = [
    "에서", "으로", "까지", "부터", "처럼", "보다", "한테", "에게",
    "은", "는", "이", "가", "을", "를", "에", "로", "와", "과",
    "의", "도", "만",
]

PUNCTUATION = ".,!?~"

MAX_LINE_LENGTH = 18
MAX_LINES = 2
MAX_CHARS_PER_SUBTITLE = 30  # 한 자막당 최대 글자수 (초과 시 분할) — 쇼츠 스타일

# 언어별 청자 기준 자막 길이 설정
# CJK(ko/ja)는 전각 문자라 18자/줄이 적정, 라틴 문자는 폭이 절반이라 2배 허용
# (스토리 언어는 story.json meta.language에서 자동 감지)
SUBTITLE_LANG_CFG = {
    "ko": {"max_line": 18, "max_chars": 30},
    "ja": {"max_line": 16, "max_chars": 28},
    # 라틴 문자권 (en/es/pt/id 등)
    "_latin": {"max_line": 36, "max_chars": 60},
}


def format_srt_time(seconds: float) -> str:
    """초를 SRT 타임스탬프 형식(HH:MM:SS,mmm)으로 변환"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_subtitle(text: str) -> str:
    """자막 텍스트를 자연스러운 위치에서 줄바꿈 (최대 2줄, 줄당 30자)"""
    text = text.strip()
    if len(text) <= MAX_LINE_LENGTH:
        return text

    best_pos = -1
    best_score = -1

    # 가능한 분리 지점을 탐색
    for i in range(1, len(text)):
        line1 = text[:i].rstrip()
        line2 = text[i:].lstrip()

        if not line1 or not line2:
            continue

        # 각 줄이 MAX_LINE_LENGTH를 초과하면 건너뛰기
        if len(line1) > MAX_LINE_LENGTH and len(line2) > MAX_LINE_LENGTH:
            continue

        # 두 줄의 길이 균형 점수 (균형잡힐수록 높음)
        balance = 1.0 - abs(len(line1) - len(line2)) / max(len(text), 1)
        score = balance * 10

        # 구두점 뒤에서 분리 (가장 높은 우선순위)
        if i > 0 and text[i - 1] in PUNCTUATION:
            score += 50

        # 공백에서 분리
        if text[i - 1] == ' ' or (i < len(text) and text[i] == ' '):
            score += 30

        # 조사 앞에서 분리
        for particle in PARTICLES:
            if text[i:].startswith(particle):
                score += 20
                break

        if score > best_score:
            best_score = score
            best_pos = i

    if best_pos > 0:
        line1 = text[:best_pos].rstrip()
        line2 = text[best_pos:].lstrip()
        return f"{line1}\n{line2}"

    # 분리 지점을 찾지 못하면 중간에서 분리
    mid = len(text) // 2
    # 중간 근처의 공백 찾기
    for offset in range(0, mid):
        for pos in [mid + offset, mid - offset]:
            if 0 < pos < len(text) and text[pos] == ' ':
                return f"{text[:pos]}\n{text[pos + 1:]}"

    return f"{text[:mid]}\n{text[mid:]}"


# ============================================================
# 인자 파싱
# ============================================================
parser = argparse.ArgumentParser(description="timing.json에서 SRT 자막 생성")
parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (예: 1 → output/ep01)")
parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
args = parser.parse_args()

if args.dir:
    ep_dir = Path(args.dir)
    ep_tag = ep_dir.name
elif args.ep is not None:
    ep_tag = f"ep{args.ep:02d}"
    ep_dir = Path(f"output/{ep_tag}")
else:
    ep_tag = "ep01"
    ep_dir = Path("output/ep01")
timing_path = ep_dir / "audio" / "timing.json"
srt_path = ep_dir / "subtitles.srt"

print(f"{'=' * 50}")
print(f"SRT 자막 생성 -- {ep_tag}")
print(f"{'=' * 50}")

# ============================================================
# 언어 감지 → 자막 길이 기준 적용
# ============================================================
story_lang = "ko"
_story_path = ep_dir / "story.json"
if _story_path.exists():
    try:
        with open(_story_path, "r", encoding="utf-8") as f:
            story_lang = json.load(f).get("meta", {}).get("language", "ko")
    except Exception:
        pass

_sub_cfg = SUBTITLE_LANG_CFG.get(story_lang, SUBTITLE_LANG_CFG["_latin"])
MAX_LINE_LENGTH = _sub_cfg["max_line"]
MAX_CHARS_PER_SUBTITLE = _sub_cfg["max_chars"]
print(f"[INFO] 언어: {story_lang} → 자막 기준 {MAX_LINE_LENGTH}자/줄, {MAX_CHARS_PER_SUBTITLE}자/자막")

# ============================================================
# timing.json 읽기
# ============================================================
if not timing_path.exists():
    print(f"[ERROR] timing.json을 찾을 수 없습니다: {timing_path}")
    sys.exit(1)

print(f"[INFO] timing.json 로드: {timing_path}")

with open(timing_path, "r", encoding="utf-8") as f:
    timing_data = json.load(f)

segments = timing_data.get("segments", [])
total_duration = timing_data.get("total_duration", 0.0)

if not segments:
    print("[ERROR] timing.json에 segments가 비어있습니다.")
    sys.exit(1)

print(f"[INFO] 세그먼트 수: {len(segments)}개")
print(f"[INFO] 전체 길이: {total_duration:.1f}초")

# ============================================================
# 긴 텍스트 분할 함수
# ============================================================
def split_long_text(text: str, max_chars: int = None) -> list[str]:
    """긴 텍스트를 자연스러운 위치에서 분할합니다.
    1순위: 문장 끝(.!?~), 2순위: 쉼표, 3순위: 공백/조사 뒤"""
    if max_chars is None:
        max_chars = MAX_CHARS_PER_SUBTITLE  # 언어별 설정 반영 (호출 시점 값)
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # 먼저 문장 단위로 분리 (. ! ? 기준)
    import re
    sentences = re.split(r'(?<=[.!?~])\s*', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 각 문장이 max_chars 이하면 그대로, 초과면 쉼표/공백에서 추가 분할
    chunks = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue

        remaining = sentence
        min_pos = max(8, max_chars // 4)  # 최소 8자 이상 확보

        while len(remaining) > max_chars:
            best_pos = -1

            # 쉼표에서 분할
            for i in range(min(max_chars, len(remaining)) - 1, min_pos, -1):
                if remaining[i] == ',':
                    best_pos = i + 1
                    break

            # 공백에서 분할
            if best_pos == -1:
                for i in range(min(max_chars, len(remaining)) - 1, min_pos, -1):
                    if remaining[i] == ' ':
                        best_pos = i + 1
                        break

            # 조사 뒤에서 분할 (한국어)
            if best_pos == -1:
                ko_breaks = ["에서 ", "으로 ", "처럼 ", "까지 ", "부터 ",
                              "에 ", "를 ", "을 ", "는 ", "은 ", "가 ", "이 ",
                              "도 ", "만 ", "와 ", "과 "]
                for kb in ko_breaks:
                    idx = remaining.rfind(kb, min_pos, max_chars)
                    if idx != -1:
                        best_pos = idx + len(kb)
                        break

            if best_pos == -1:
                best_pos = max_chars

            chunks.append(remaining[:best_pos].strip())
            remaining = remaining[best_pos:].strip()

        if remaining:
            chunks.append(remaining)

    # 너무 짧은 조각(5자 이하)은 이전 조각에 합치기
    merged = []
    for chunk in chunks:
        if merged and len(chunk) <= 5:
            merged[-1] = merged[-1] + " " + chunk
        else:
            merged.append(chunk)

    return merged


# ============================================================
# SRT 생성
# ============================================================
print(f"\n[PROC] SRT 자막 생성 중...")

srt_lines = []
subtitle_count = 0

for i, seg in enumerate(segments):
    text = seg.get("text", "").strip()
    if not text:
        continue

    start = seg.get("start", 0.0)
    end = seg.get("end", 0.0)

    if end <= start:
        continue

    # 긴 텍스트는 시간 비례로 여러 자막으로 분할
    chunks = split_long_text(text)
    seg_duration = end - start

    for ci, chunk in enumerate(chunks):
        subtitle_count += 1

        # 시간을 글자 수 비례로 분배
        chunk_ratio = len(chunk) / max(len(text), 1)
        chunk_start = start + seg_duration * (sum(len(c) for c in chunks[:ci]) / max(len(text), 1))
        chunk_end = start + seg_duration * (sum(len(c) for c in chunks[:ci + 1]) / max(len(text), 1))

        # 최소 0.5초 보장
        if chunk_end - chunk_start < 0.5:
            chunk_end = min(chunk_start + 0.5, end)

        start_ts = format_srt_time(chunk_start)
        end_ts = format_srt_time(chunk_end)

        # 줄바꿈 처리
        wrapped_text = wrap_subtitle(chunk)

        srt_lines.append(f"{subtitle_count}")
        srt_lines.append(f"{start_ts} --> {end_ts}")
        srt_lines.append(wrapped_text)
        srt_lines.append("")

    # 진행 상황 출력 (10개마다)
    if subtitle_count % 10 == 0:
        print(f"  ... {subtitle_count}개 처리 완료")

srt_text = "\n".join(srt_lines)

# ============================================================
# 파일 저장
# ============================================================
srt_path.parent.mkdir(parents=True, exist_ok=True)

with open(srt_path, "w", encoding="utf-8") as f:
    f.write(srt_text)

# ============================================================
# 요약 출력
# ============================================================
# 실제 커버된 시간 계산
if segments:
    covered_start = segments[0].get("start", 0.0)
    covered_end = segments[-1].get("end", 0.0)
    covered_duration = covered_end - covered_start
else:
    covered_duration = 0.0

print(f"\n[OK] SRT 자막 생성 완료!")
print(f"  출력 파일: {srt_path}")
print(f"  자막 수: {subtitle_count}개")
print(f"  커버 시간: {covered_duration:.1f}초 / 전체 {total_duration:.1f}초")
print(f"  파일 크기: {srt_path.stat().st_size:,} bytes")

print(f"\n{'=' * 50}")
print(f"완료 -- {srt_path}")
print(f"{'=' * 50}")
