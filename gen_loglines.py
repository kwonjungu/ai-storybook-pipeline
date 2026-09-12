# -*- coding: utf-8 -*-
"""
gen_loglines.py
===============
대상 폴더의 story.json 에 meta.logline (비스포일러 2~3줄 소개문) 이 없으면
claude -p 서브프로세스로 생성해 저장한다. (01_generate_story.py 호출 방식 참고)

- 대상: output/*/publish_log.json 이 존재하는 모든 폴더 (에코의탐험복찾기 제외)
- 이미 meta.logline 이 있으면 건너뜀
- 결과에서 따옴표·마크다운 제거 후 저장

사용:
  python gen_loglines.py            # 전 대상 폴더
  python gen_loglines.py --only <폴더명>
  python gen_loglines.py --force    # 기존 logline 도 재생성
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
_CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

EXCLUDE_KEYWORD = "에코의탐험복찾기"


def clean_logline(text: str) -> str:
    """따옴표·마크다운·불필요한 라벨 제거."""
    t = text.strip()
    # 코드블록 제거
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        t = t.strip()
    # 앞뒤 따옴표 제거
    t = t.strip().strip('"').strip("'").strip("“”‘’").strip()
    # 흔한 접두 라벨 제거
    t = re.sub(r"^(소개문|logline|로그라인|소개)\s*[:：]\s*", "", t, flags=re.I)
    # 마크다운 강조 제거
    t = re.sub(r"[*_`#]+", "", t)
    # 금지 특수문자 정리 (CLAUDE.md 규칙 준수: … — ― 금지)
    t = t.replace("…", "").replace("—", " ").replace("―", " ")
    # 여러 빈 줄 축소
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def build_prompt(meta: dict, slide_texts: list) -> str:
    grade = meta.get("grade", "")
    series = meta.get("series", "")
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")
    sub_unit = meta.get("sub_unit", "")
    story_title = meta.get("story_title", "")
    chars = meta.get("characters", {})
    names = []
    for k in ("main_1", "main_2"):
        ch = chars.get(k) or {}
        if ch.get("name"):
            names.append(ch["name"])
    theme = f"{subject} {series} '{unit_title}' 단원".strip()

    front = "\n".join(f"- {t}" for t in slide_texts[:2] if t)

    return f"""당신은 초등 저학년 동화 채널의 카피라이터입니다.
아래 동화의 유튜브 설명란 최상단에 넣을 '소개문(logline)'을 작성하세요.

[동화 제목] {story_title}
[주인공] {', '.join(names) if names else '주인공'}
[단원 주제] {theme}
[대상] 초등학교 {grade}학년
[도입부 장면 2장]
{front}

[요구사항]
1. 초등 저학년 학부모와 교사가 읽을 2~3줄(80~140자)의 짧은 소개문.
2. 결말과 반전은 절대 포함하지 마세요. 궁금증만 유발하세요.
3. 슬라이드 문장을 그대로 베끼지 말고, 새로 자연스럽게 쓰세요.
4. 특수문자(…, —, ―)와 이모지, 해시태그, 따옴표는 쓰지 마세요.
5. 마크다운, 라벨(예: 소개문:) 없이 소개문 본문만 출력하세요."""


def target_dirs(only: str = None):
    dirs = []
    for pl in sorted(Path("output").glob("*/publish_log.json")):
        d = pl.parent
        if EXCLUDE_KEYWORD in d.name:
            continue
        if only and only not in d.name:
            continue
        dirs.append(d)
    return dirs


def gen_one(d: Path, force: bool) -> str:
    """반환: 'skip' / 'ok' / 'fail'"""
    story_path = d / "story.json"
    if not story_path.exists():
        return "fail"
    story = json.loads(story_path.read_text(encoding="utf-8"))
    meta = story.setdefault("meta", {})
    if meta.get("logline") and not force:
        print(f"  [SKIP] 이미 logline 있음: {d.name}")
        return "skip"

    slides = [s for s in story.get("slides", []) if s.get("type") == "story"]
    slide_texts = [s.get("text", "") for s in slides]
    prompt = build_prompt(meta, slide_texts)

    for attempt in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
                env=_CLAUDE_ENV,
            )
            if r.returncode != 0:
                raise RuntimeError(f"claude 종료코드 {r.returncode}: {r.stderr.strip()[:200]}")
            logline = clean_logline(r.stdout)
            if not logline or len(logline) < 10:
                raise ValueError(f"logline 너무 짧음: {logline!r}")
            meta["logline"] = logline
            story_path.write_text(
                json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [OK] {d.name}\n       → {logline[:80]}...")
            return "ok"
        except Exception as e:
            print(f"  [WARN] {d.name} 시도 {attempt+1}/3 실패: {e}")
    print(f"  [FAIL] {d.name}")
    return "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="특정 폴더명(부분 매칭)만")
    ap.add_argument("--force", action="store_true", help="기존 logline 도 재생성")
    args = ap.parse_args()

    dirs = target_dirs(args.only)
    print(f"[INFO] 대상 폴더 {len(dirs)}개")
    stats = {"ok": 0, "skip": 0, "fail": 0}
    failed = []
    for d in dirs:
        res = gen_one(d, args.force)
        stats[res] = stats.get(res, 0) + 1
        if res == "fail":
            failed.append(d.name)
    print(f"\n[완료] 생성={stats['ok']} 건너뜀={stats['skip']} 실패={stats['fail']}")
    if failed:
        print("[실패 목록]")
        for f in failed:
            print("  -", f)


if __name__ == "__main__":
    main()
