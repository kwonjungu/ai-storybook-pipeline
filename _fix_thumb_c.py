#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_fix_thumb_c.py
thumbnail_c_bg.png 를 '생성 -> Vision 검사 -> 불합격이면 재생성' 루프로 규칙에 맞을 때까지 고친다.

왜 루프인가 (2026-09-13):
  10b 배치로 한 번에 21장을 다시 뽑아봤지만 절반 이상이 또 전신샷으로 나왔다.
  이미지 모델은 같은 프롬프트에도 결과 편차가 크다 → 한 장씩 즉시 생성하고 바로 검사해서
  통과할 때까지 돌리는 게 확실하다. (realtime $0.039/장, 보통 1~3회)

검사 기준 = _audit_thumb_c.verdict (다리·발이 보이면 전신샷 = 불합격, 오른쪽 텍스트 자리 필요)
라운드마다 프롬프트 강도를 높인다.

  python _fix_thumb_c.py --from-audit          # 감사 불합격분 전부
  python _fix_thumb_c.py --only 알에서 --rounds 4
  python _fix_thumb_c.py --propagate           # 통과한 한국어 원본을 _en/_id 폴더로 복사
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()
from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
_spec = importlib.util.spec_from_file_location("thumb10b", "10b_batch_thumb_bg.py")
_t10b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t10b)
from _audit_thumb_c import ask as audit_ask, verdict as audit_verdict

MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
LANG_SUFFIXES = ("_en", "_id", "_pt", "_es")

# 라운드가 올라갈수록 구도 지시를 강하게
EXTRA_BY_ROUND = [
    "",
    (" The picture is CUT OFF by the bottom edge of the frame at chest level: no waist, no legs, "
     "no feet anywhere. Think of a passport-photo style framing but for two characters."),
    (" EXTREME CLOSE-UP: only the heads and the very top of the shoulders are inside the frame, "
     "cropped by the bottom edge. Both characters are pushed to the LEFT; the entire RIGHT HALF "
     "of the image is nothing but empty soft background."),
    (" Draw ONLY the two heads, tightly cropped, filling the left third of a wide empty background. "
     "No bodies at all. The right two thirds are a plain soft gradient with nothing on it."),
]


def refs_for(d: Path):
    refs = []
    for n in ("main_1.png", "main_2.png"):
        p = d / "characters" / n
        if p.exists():
            refs.append(p)
    return refs


def gen_once(d: Path, prompt: str, out: Path) -> bool:
    parts = []
    for p in refs_for(d):
        parts.append(types.Part.from_bytes(data=p.read_bytes(), mime_type="image/png"))
    parts.append(types.Part.from_text(text=prompt))
    try:
        r = client.models.generate_content(
            model=MODEL,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9", image_size="1K"),
            ),
        )
    except Exception as e:
        print(f"    [WARN] 생성 실패: {e}")
        return False
    for cand in r.candidates or []:
        for part in cand.content.parts or []:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                out.write_bytes(data if isinstance(data, (bytes, bytearray)) else base64.b64decode(data))
                return True
    print("    [WARN] 이미지 데이터 없음")
    return False


def fix_one(d: Path, rounds: int) -> bool:
    story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    base_prompt = _t10b.build_prompt(story)
    bg = d / "thumbnail_c_bg.png"
    keep = d / "thumbnail_c_bg_prev.png"
    if bg.exists() and not keep.exists():
        keep.write_bytes(bg.read_bytes())

    tmp = d / "_thumb_try.png"
    for r in range(rounds):
        extra = EXTRA_BY_ROUND[min(r, len(EXTRA_BY_ROUND) - 1)]
        print(f"  [라운드 {r+1}/{rounds}] 생성 중...")
        if not gen_once(d, base_prompt + extra, tmp):
            time.sleep(5)
            continue
        try:
            res = audit_ask(tmp)
            bad = audit_verdict(res)
        except Exception as e:
            print(f"    [WARN] 검사 실패: {e}")
            bad = ["검사 실패"]
        if not bad:
            bg.write_bytes(tmp.read_bytes())
            tmp.unlink(missing_ok=True)
            print(f"    [합격] crop={res.get('crop')} feet={res.get('feet_visible')}")
            return True
        print(f"    [불합격] {', '.join(bad)} (crop={res.get('crop')})")
    # 마지막 시도 결과라도 남긴다 (이전 것보다 나쁘진 않게: 통과 못 하면 원본 유지)
    tmp.unlink(missing_ok=True)
    print("    [실패] 라운드 소진 — 기존 배경 유지")
    return False


def propagate():
    """통과한 한국어 원본 c_bg 를 같은 에피소드의 언어판 폴더로 복사."""
    n = 0
    for d in sorted(Path("output").glob("*/thumbnail_c_bg.png")):
        src_dir = d.parent
        if any(src_dir.name.endswith(s) for s in LANG_SUFFIXES):
            continue
        for sfx in LANG_SUFFIXES:
            dst_dir = src_dir.parent / f"{src_dir.name}{sfx}"
            if dst_dir.is_dir():
                (dst_dir / "thumbnail_c_bg.png").write_bytes(d.read_bytes())
                print(f"  [복사] {src_dir.name[:34]} -> {sfx}")
                n += 1
    print(f"\n=== 언어판 {n}개 갱신 ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--from-audit", action="store_true")
    ap.add_argument("--audit-json", default="_thumb_c_audit_v2.json")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--propagate", action="store_true", help="언어판 복사만 수행")
    args = ap.parse_args()

    if args.propagate:
        propagate()
        return

    dirs = sorted(p.parent for p in Path("output").glob("*/thumbnail_c_bg.png"))
    dirs = [d for d in dirs if not any(d.name.endswith(s) for s in LANG_SUFFIXES)]
    if args.only:
        dirs = [d for d in dirs if args.only in d.name]
    if args.from_audit:
        data = json.loads(Path(args.audit_json).read_text(encoding="utf-8"))
        fails = {k for k, v in data.items() if v.get("issues")}
        dirs = [d for d in dirs if d.name in fails]

    print(f"[INFO] 대상 {len(dirs)}개 / 라운드 최대 {args.rounds}\n")
    ok = []
    for i, d in enumerate(dirs, 1):
        print(f"[{i}/{len(dirs)}] {d.name[:46]}")
        if fix_one(d, args.rounds):
            ok.append(d.name)

    print(f"\n=== 합격 {len(ok)} / 시도 {len(dirs)} ===")
    print("언어판 반영: python _fix_thumb_c.py --propagate")


if __name__ == "__main__":
    main()
