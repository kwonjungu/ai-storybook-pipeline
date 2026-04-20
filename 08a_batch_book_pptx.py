#!/usr/bin/env python3
"""
08a_batch_book_pptx.py
모든 output/* 디렉토리에 대해 08_generate_book_pptx.py --mode 1 을 일괄 실행.

사용법:
  python 08a_batch_book_pptx.py               # output/ 전체
  python 08a_batch_book_pptx.py --dir bsl02   # 특정 폴더만
  python 08a_batch_book_pptx.py --skip-done   # book_1분할.pptx 이미 있으면 건너뜀
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE    = Path(__file__).parent
OUTPUT  = BASE / "output"
SCRIPT  = BASE / "08_generate_book_pptx.py"


def has_story(ep_dir: Path) -> bool:
    return (ep_dir / "story.json").exists()


def already_done(ep_dir: Path) -> bool:
    for p in ep_dir.glob("book_1분할*.pptx"):
        return True
    return False


def run_one(ep_dir: Path, skip_done: bool) -> str:
    """반환: 'ok' | 'skip' | 'error'"""
    if not has_story(ep_dir):
        return "no_story"

    if skip_done and already_done(ep_dir):
        return "skip"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(ep_dir.relative_to(BASE)), "--mode", "1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(BASE)
    )

    # WARN / DONE 줄만 출력
    for line in result.stdout.splitlines():
        if any(tag in line for tag in ("[DONE]", "[WARN]", "[INFO]", "[ERROR]")):
            print(f"  {line}")

    if result.returncode != 0:
        if result.stderr:
            print(f"  [ERR] {result.stderr[:200]}")
        return "error"
    return "ok"


def main():
    parser = argparse.ArgumentParser(description="1분할 PPTX 일괄 생성")
    parser.add_argument("--dir",       help="특정 하위 폴더명 (예: bsl02_en)")
    parser.add_argument("--skip-done", action="store_true",
                        help="book_1분할.pptx 이미 있으면 건너뜀")
    args = parser.parse_args()

    if args.dir:
        targets = [OUTPUT / args.dir]
    else:
        targets = sorted(
            p for p in OUTPUT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    ok_cnt = skip_cnt = err_cnt = nostory_cnt = 0

    for ep_dir in targets:
        name = ep_dir.name
        # 언어 표시
        lang = "??"
        sp = ep_dir / "story.json"
        if sp.exists():
            try:
                with open(sp, encoding="utf-8") as f:
                    lang = json.load(f).get("meta", {}).get("language", "ko")
            except Exception:
                pass

        print(f"\n{'─'*50}")
        print(f"[{name}]  lang={lang}")

        status = run_one(ep_dir, args.skip_done)
        if status == "ok":
            ok_cnt += 1
        elif status == "skip":
            print("  → 이미 존재, 건너뜀")
            skip_cnt += 1
        elif status == "no_story":
            print("  → story.json 없음, 건너뜀")
            nostory_cnt += 1
        else:
            err_cnt += 1

    print(f"\n{'='*50}")
    print(f"완료: {ok_cnt}개  /  건너뜀: {skip_cnt}개  /  오류: {err_cnt}개  /  story없음: {nostory_cnt}개")


if __name__ == "__main__":
    main()
