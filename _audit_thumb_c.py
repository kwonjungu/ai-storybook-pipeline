#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_audit_thumb_c.py
thumbnail_c_bg.png 가 '스타일 C 규칙'(10b_batch_thumb_bg.build_prompt)을 지켰는지 일괄 점검.

규칙: 두 주인공 상반신 클로즈업(얼굴+어깨가 화면 60%+), 캐릭터는 왼쪽, 오른쪽은 텍스트 자리,
      이미지 내 글자 없음, 풀블리드.

판정 방식 (2026-09-13):
- '얼굴이 화면의 몇 %냐'를 모델에 직접 물으면 **같은 파일인데 70% / 22% 로 갈릴 만큼 편차가 크다.**
  (실제로 ko/en 폴더의 동일 파일이 서로 다른 판정을 받았음)
  → 그래서 눈으로 확인 가능한 이산적 특징으로 묻는다: **다리·발이 보이는가**(=전신샷),
    몸이 어디서 잘렸는가(chest/waist/none). 이건 재현성이 높다.
- 언어별 폴더는 한국어 원본 c_bg를 그대로 복사하므로 **md5로 중복 제거** 후 1회만 판정한다.

  python _audit_thumb_c.py
  python _audit_thumb_c.py --only _en
"""
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

QUESTION = (
    "This is a YouTube thumbnail background for a children's storybook channel. "
    "Look at the main cartoon characters and answer factually.\n"
    "Answer ONLY compact JSON:\n"
    '{"feet_visible":true|false,   // are the characters\' feet or lower legs visible?\n'
    ' "crop":"chest|waist|knees|full_body",  // where the visible part of the body ends\n'
    ' "heads_big":true|false,      // do the heads alone clearly dominate the picture\n'
    ' "text_in_image":true|false,\n'
    ' "right_side_clear":true|false, // is the right ~40% free enough for a text overlay\n'
    ' "borders":true|false}'
)


def sha(path: Path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def ask(path: Path, retries: int = 4):
    """네트워크 순단(WinError 10054 등)이 잦아 재시도 필수."""
    import time
    last = None
    for attempt in range(retries):
        try:
            return _ask_once(path)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last


def _ask_once(path: Path):
    up = client.files.upload(file=str(path))
    r = client.models.generate_content(model="gemini-2.5-flash", contents=[up, QUESTION])
    raw = r.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
        raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)


def verdict(res):
    """규칙 위반 사유 목록. 비어 있으면 합격."""
    bad = []
    if res.get("feet_visible") or res.get("crop") in ("knees", "full_body"):
        bad.append("전신샷(다리·발 보임) — 상반신 클로즈업 아님")
    if res.get("text_in_image"):
        bad.append("이미지에 글자 있음")
    if res.get("right_side_clear") is False:
        bad.append("오른쪽 텍스트 자리 없음")
    if res.get("borders"):
        bad.append("흰 여백/프레임 있음")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--json", dest="json_out", default="_thumb_c_audit.json")
    args = ap.parse_args()

    targets = sorted(Path("output").glob("*/thumbnail_c_bg.png"))
    if args.only:
        targets = [t for t in targets if args.only in t.parent.name]

    # 동일 이미지(언어별 복사본) 묶기
    groups = defaultdict(list)
    for p in targets:
        groups[sha(p)].append(p)
    print(f"대상 {len(targets)}개 파일 / 고유 이미지 {len(groups)}개\n")

    results, fails = {}, []
    for i, (h, paths) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0].parent.name), 1):
        rep = paths[0]
        try:
            res = ask(rep)
            bad = verdict(res)
        except Exception as e:
            res, bad = {"error": str(e)[:120]}, ["점검 실패"]
        names = [p.parent.name for p in paths]
        mark = "OK  " if not bad else "FAIL"
        extra = f" (+{len(names)-1}개 언어판)" if len(names) > 1 else ""
        print(f"[{i:2d}/{len(groups)}] {mark} crop={res.get('crop','-'):9s} "
              f"feet={str(res.get('feet_visible')):5s} {names[0][:40]}{extra}")
        if bad:
            print(f"         → {', '.join(bad)}")
        for n in names:
            results[n] = {**res, "issues": bad, "md5": h}
        if bad:
            fails.extend(names)

    Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    print(f"\n=== 불합격 이미지 {len({results[n]['md5'] for n in fails})}개 "
          f"(폴더 {len(fails)}개) / 전체 고유 {len(groups)}개 ===")
    print(f"{args.json_out} 저장")


if __name__ == "__main__":
    main()
