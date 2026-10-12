#!/usr/bin/env python3
"""
07a_check_worksheet.py  (v2, 2026-09-26 활동지 전수조사 후속)
AI 동화책 파이프라인 — 7a단계: 활동지 QA 게이트

구 v1(이미지만 보고 Vision이 판정)은 인쇄본에 없는 글자를 인용하는 판독 오탐이 많았고,
정작 머리글 오표기·seed 노출·원문 불일치는 놓쳤다. 불합격이어도 파이프라인은 계속 진행됐다.
→ v2는 3단으로 나눈다.

  ① 규칙 검사 (결정적, 차단)   worksheet.html·story.json을 코드로 검사
       머리글=meta · seed/렌더오류 문자열 없음 · 인물 카드 ⊂ cast · 순서 문항이 정답 순서로
       배치되지 않음 · 정답지 존재 · 알 모양 틀은 알 차시에만 · 고정 라벨('이름을 지어 주세요') 없음
       · PDF 2쪽 · manifest md5 = 실제 PDF md5
  ② 원문 대조 (결정적, 차단)   activity_sheet v2.1 을 gen_activity_v2.validate 로 재검증
       (모든 문항 evidence가 원문에 실재 · 정답 중복·힌트 노출·cast 밖 화자 등)
  ③ 이미지 레이아웃 (--vision, 경고만)  잘림·겹침·큰 공백만 본다 (글자 판독은 하지 않음)

출력: worksheet_qa.json (pdf_md5 포함 — 배포 스크립트가 '검사한 파일 = 올릴 파일'을 확인)
종료코드: ①② 전부 합격 0 / 하나라도 불합격 1

사용법:
  python 07a_check_worksheet.py --dir output/폴더 [--vision]
  python 07a_check_worksheet.py --all            (Drive 배포 중인 편 전부)
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_activity_v2", BASE_DIR / "gen_activity_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GEN = _load_gen()


def _visible_text(html: str) -> str:
    """주석·style 제거 후 태그를 벗긴 보이는 텍스트."""
    h = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", h)


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


# ── ① 규칙 검사 ─────────────────────────────────────────────────

def rule_checks(ep_dir: Path, story: dict) -> list[str]:
    errs = []
    html_p, pdf_p = ep_dir / "worksheet.html", ep_dir / "worksheet.pdf"
    if not html_p.exists() or not pdf_p.exists():
        return ["worksheet.html 또는 worksheet.pdf 없음"]
    html = html_p.read_text(encoding="utf-8")
    text = _visible_text(html)
    meta = story.get("meta", {})
    act = story.get("activity_sheet", {})

    # 머리글
    if not meta.get("no_textbook"):
        for label, val in (("학년", f"초등 {meta.get('grade')}학년"), ("교과", meta.get("subject")),
                           ("단원", meta.get("series")), ("차시", meta.get("unit_title"))):
            if not val or str(val) not in text:
                errs.append(f"머리글에 {label} 표기 없음/불일치 (기대: {val})")

    # 디버그·오류 문자열
    for bad in ("seed:", "렌더링 오류", "활동 렌더 실패", "데이터 없음", "알 수 없는 활동"):
        if bad in text:
            errs.append(f"보이는 글자에 '{bad}' 노출")

    # 고정 라벨(상상 동물 전용)이 다른 발문에 붙는 결함
    if "이름을 지어 주세요" in text and "이름" not in ((act.get("draw") or {}).get("field1_label") or ""):
        errs.append("그리기 기입란에 고정 라벨 '이름을 지어 주세요'")

    # 그림틀: 알 모양은 알 차시에만
    body = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    if "frame-egg" in body and "알" not in (meta.get("unit_title", "") + meta.get("story_title", "")):
        errs.append("알 차시가 아닌데 알 모양 그림틀")

    # 인물 카드 ⊂ cast
    cast = set(act.get("cast") or [])
    names = re.findall(r'<div class="char-name">(.*?)</div>', html)
    if cast:
        extra = [n for n in names if n not in cast]
        if extra:
            errs.append(f"본문에 없는 인물 카드: {extra}")
    if not names:
        errs.append("인물 카드 없음")

    # 순서 문항: 표시 순서가 정답 순서(1,2,3)와 같으면 문제가 안 됨
    if 'class="seq-list"' in html:
        m = re.search(r'\[순서\]</b>\s*(.*?)(?:<br>|</div>)', html)
        if m:
            orders = re.findall(r"\.\s*(\d)", m.group(1))
            if orders and orders == sorted(orders):
                errs.append(f"순서 문항이 이미 정답 순서로 배치됨 ({orders})")
            labels_q = re.findall(r'<div class="seq-label">(.*?)</div>', html)
            labels_a = re.findall(r"([ⒶⒷⒸⒹⒺA-E])\.", m.group(1))
            if labels_q and set(labels_a) - set(labels_q):
                errs.append("순서 정답 라벨이 문제 라벨과 불일치")
        else:
            errs.append("순서 문항 정답이 정답지에 없음")

    # 정답지
    if 'class="ak-body"' not in html:
        errs.append("정답지 없음")

    # PDF: 2쪽 + manifest md5
    try:
        import fitz
        n = len(fitz.open(str(pdf_p)))
        if n != 2:
            errs.append(f"PDF 쪽수 {n} (2쪽이어야 함 — 넘침)")
    except Exception as e:
        errs.append(f"PDF 열기 실패: {e}")
    mf = ep_dir / "worksheet_manifest.json"
    if mf.exists():
        man = json.loads(mf.read_text(encoding="utf-8"))
        if man.get("pdf_md5") and man["pdf_md5"] != _md5(pdf_p):
            errs.append("worksheet.pdf가 07 렌더 이후 바뀜 (manifest md5 불일치)")
    else:
        errs.append("worksheet_manifest.json 없음 (07 신버전으로 재렌더 필요)")
    return errs


# ── ② 원문 대조 ─────────────────────────────────────────────────

def data_checks(story: dict) -> list[str]:
    act = story.get("activity_sheet", {})
    if act.get("schema") != _GEN.SCHEMA_VERSION:
        return [f"activity_sheet v{_GEN.SCHEMA_VERSION} 아님 → gen_activity_v2.py 실행 필요"]
    return _GEN.validate({k: act.get(k) for k in _GEN.V2_KEYS}, story)


# ── ③ 이미지 레이아웃 (경고) ───────────────────────────────────

LAYOUT_PROMPT = """초등 1학년용 A4 활동지 {n}쪽 이미지입니다. 글자 내용은 판정하지 말고 **레이아웃만** 보세요.
다음만 확인해 JSON으로 답하세요:
- 잘림: 글자·칸·그림틀이 페이지나 카드 경계에서 잘렸는가
- 겹침: 글자끼리 또는 글자와 칸이 겹쳤는가
- 공백: 한 쪽의 1/4 이상이 아무것도 없이 비었는가 (정답지·그림 그리는 칸은 빈 게 정상)
문구를 인용하지 말고 위치(쪽, 위/가운데/아래, 어느 카드)로만 설명하세요.
{{"ok": true/false, "issues": ["2쪽 아래 정답지 카드 오른쪽이 잘림", ...]}}"""


def vision_layout(ep_dir: Path) -> dict:
    try:
        import fitz
        from dotenv import load_dotenv
        from google import genai
        from google.genai import types as T
        load_dotenv(BASE_DIR / ".env")
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=key)
        doc = fitz.open(str(ep_dir / "worksheet.pdf"))
        parts = [T.Part.from_bytes(data=p.get_pixmap(dpi=110).tobytes("png"), mime_type="image/png")
                 for p in doc]
        parts.append(T.Part.from_text(text=LAYOUT_PROMPT.format(n=len(doc))))
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"), contents=parts,
            config=T.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"))
        raw = resp.text
        r = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return {"ok": bool(r.get("ok", True)), "issues": r.get("issues", []) or []}
    except Exception as e:
        return {"ok": True, "issues": [], "_error": f"vision 실패(경고 생략): {e}"}


# ── 실행 ────────────────────────────────────────────────────────

def check_one(ep_dir: Path, vision: bool = False, quiet: bool = False) -> dict:
    story = json.loads((ep_dir / "story.json").read_text(encoding="utf-8"))
    rules = rule_checks(ep_dir, story)
    data = data_checks(story)
    res = {
        "dir": ep_dir.name,
        "story_title": story.get("meta", {}).get("story_title", ""),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "qa_version": 2,
        "pdf_md5": _md5(ep_dir / "worksheet.pdf") if (ep_dir / "worksheet.pdf").exists() else None,
        "rules": {"ok": not rules, "issues": rules},
        "data": {"ok": not data, "issues": data},
        "all_ok": not rules and not data,
    }
    if vision:
        res["layout_warn"] = vision_layout(ep_dir)
    (ep_dir / "worksheet_qa.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        print(f"[07a] {ep_dir.name}: {'PASS' if res['all_ok'] else 'FAIL'}")
        for tag in ("rules", "data"):
            for i in res[tag]["issues"]:
                print(f"   ✗ [{tag}] {i}")
        if vision:
            for i in res["layout_warn"].get("issues", []):
                print(f"   △ [layout] {i}")
    return res


def deployed_dirs() -> list[Path]:
    out = []
    for pl in sorted((BASE_DIR / "output").glob("*/publish_log.json")):
        try:
            if json.loads(pl.read_text(encoding="utf-8")).get("worksheet_drive_url"):
                out.append(pl.parent)
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description="활동지 QA 게이트 v2 (규칙+원문대조 차단, 레이아웃 경고)")
    ap.add_argument("--dir", dest="dir_path")
    ap.add_argument("--all", action="store_true", help="Drive 배포 중인 편 전부")
    ap.add_argument("--vision", action="store_true", help="레이아웃 이미지 검사(경고만)")
    args = ap.parse_args()

    if args.all:
        rows = [check_one(d, args.vision, quiet=True) for d in deployed_dirs()]
        for r in rows:
            n = len(r["rules"]["issues"]) + len(r["data"]["issues"])
            w = len(r.get("layout_warn", {}).get("issues", []))
            print(f"  {'PASS' if r['all_ok'] else 'FAIL'}  {r['dir'][:60]}" +
                  (f"  (불합격 {n})" if n else "") + (f"  (레이아웃 경고 {w})" if w else ""))
        n_fail = sum(1 for r in rows if not r["all_ok"])
        print(f"\n[07a] {len(rows)}편 중 불합격 {n_fail}편")
        sys.exit(1 if n_fail else 0)

    if not args.dir_path:
        ap.error("--dir 또는 --all 필요")
    d = Path(args.dir_path)
    if not d.is_absolute():
        d = BASE_DIR / d
    sys.exit(0 if check_one(d, args.vision)["all_ok"] else 1)


if __name__ == "__main__":
    main()
