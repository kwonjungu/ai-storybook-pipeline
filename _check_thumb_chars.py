#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_check_thumb_chars.py
thumbnail_c_bg.png 의 캐릭터가 캐릭터 시트와 같은지 Vision으로 점검 (02a 이미지 QA와 같은 발상).

2026-09-14: 썸네일 배경을 일괄 재생성했더니 알탐험에서 토토(거북)가 사라지고 병아리가 둘이 된
사례가 나왔다. 프레임 규칙(_audit_thumb_c.py)만 보면 이런 건 못 잡는다 → 종/색을 따로 대조한다.

  python _check_thumb_chars.py --newer-than "2026-09-14 00:00"
  python _check_thumb_chars.py --only 알에서
"""
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def check(bg: Path, sheets, names):
    parts = []
    for sh in sheets:
        parts.append(client.files.upload(file=str(sh)))
    parts.append(client.files.upload(file=str(bg)))
    q = (f"The first {len(sheets)} image(s) are the official character sheets for "
         f"{', '.join(names)}. The LAST image is a thumbnail background that must show "
         f"those same characters.\n"
         "Answer ONLY compact JSON: "
         '{"characters_shown":<how many distinct characters appear>,'
         '"all_sheet_characters_present":true|false,'
         '"duplicated_character":true|false,'
         '"species_or_color_mismatch":true|false,'
         '"why":"<one short sentence>"}')
    r = client.models.generate_content(model="gemini-2.5-flash", contents=parts + [q])
    raw = r.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
        raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--newer-than", default=None, help='예: "2026-09-14 00:00"')
    ap.add_argument("--json", dest="json_out", default="_thumb_char_check.json")
    args = ap.parse_args()

    cutoff = datetime.strptime(args.newer_than, "%Y-%m-%d %H:%M").timestamp() if args.newer_than else None
    dirs = sorted(p.parent for p in Path("output").glob("*/thumbnail_c_bg.png"))
    dirs = [d for d in dirs if not any(d.name.endswith(s) for s in ("_en", "_id", "_pt", "_es"))]
    if args.only:
        dirs = [d for d in dirs if args.only in d.name]
    if cutoff:
        dirs = [d for d in dirs if (d / "thumbnail_c_bg.png").stat().st_mtime >= cutoff]

    out, bad = {}, []
    for i, d in enumerate(dirs, 1):
        story = json.loads((d / "story.json").read_text(encoding="utf-8"))
        chars = story["meta"].get("characters", {})
        names, sheets = [], []
        for k in ("main_1", "main_2"):
            c = chars.get(k) or {}
            sp = c.get("species") or ""
            if c.get("name"):
                names.append(f"{c['name']} ({sp})" if sp else c["name"])
            sh = d / "characters" / f"{k}.png"
            if sh.exists():
                sheets.append(sh)
        if not sheets:
            print(f"[{i}/{len(dirs)}] SKIP 시트 없음 {d.name[:40]}")
            continue
        try:
            res = check(d / "thumbnail_c_bg.png", sheets, names)
        except Exception as e:
            res = {"error": str(e)[:100]}
        ok = (res.get("all_sheet_characters_present") and not res.get("duplicated_character")
              and not res.get("species_or_color_mismatch"))
        out[d.name] = {**res, "ok": bool(ok)}
        print(f"[{i}/{len(dirs)}] {'OK  ' if ok else 'FAIL'} {d.name[:42]}")
        if not ok:
            print(f"         → {res.get('why', res.get('error',''))}")
            bad.append(d.name)

    Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 캐릭터 불합격 {len(bad)} / {len(out)} — {args.json_out} ===")
    for b in bad:
        print("  -", b)


if __name__ == "__main__":
    main()
