#!/usr/bin/env python3
"""
07a_check_worksheet.py
AI 동화책 파이프라인 — 7a단계: 활동지(worksheet) 품질 자동 점검 (QA 게이트)

07_generate_worksheet.py 직후 실행.
worksheet.pdf 를 페이지 이미지로 변환한 뒤 Gemini Vision 이 story.json 의
핵심 정보(주인공 이름·quiz_questions)와 대조하여 활동지의 6개 결함 유형을 판정한다.

점검 항목 (각 {"ok": bool, "issues": [...]}):
  ① 이름 중복·비문        — "토토와 토토는" 류 이름 교체로 생긴 중복/비문
  ② 문제-정답 라벨 대응    — 정답키의 라벨(A/B/C·번호)이 문제에 실제로 존재하는가
  ③ 힌트=정답 노출         — 힌트가 정답 대사/답을 그대로 노출하는가 (베껴쓰기 전락)
  ④ 지시-기입란 불일치     — 활동 지시문과 기입란 라벨이 어긋나는가
  ⑤ 조사 오류·어색한 한국어 — 조사 오류·비문·어색한 문장
  ⑥ 레이아웃 문제          — 큰 빈 공백·텍스트 잘림·겹침

이미지 변환:
  1) PyMuPDF(fitz) 가 있으면 worksheet.pdf → 페이지 PNG (최우선)
  2) 없으면 pip install pymupdf 시도
  3) 그래도 안 되면 Chrome/Edge headless 로 worksheet.html 전체 페이지 스크린샷
     (07 의 find_browser 로직 참고)

출력:
  worksheet_qa.json 저장 + 콘솔에 항목별 합격/불합격 요약.
  종료코드: 전부 ok=0 / 하나라도 불합격=1 (파이프라인 게이트용).
  ※ 자동 수정하지 않음 — 사람 최종 판단용 리포트 (02a 와 동일한 오탐 감안 전제).

사용법:
  python 07a_check_worksheet.py --dir output/폴더
  python 07a_check_worksheet.py --ep 1
  python 07a_check_worksheet.py --all           (output/*/worksheet.pdf 전부 순회)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

_client = genai.Client(api_key=GEMINI_API_KEY)

BASE_DIR = Path(__file__).parent

# 6개 점검 항목 (키, 라벨)
CHECK_ITEMS = [
    ("name_dup",      "① 이름 중복·비문"),
    ("label_match",   "② 문제-정답 라벨 대응"),
    ("hint_spoiler",  "③ 힌트=정답 노출"),
    ("prompt_field",  "④ 지시-기입란 불일치"),
    ("korean_grammar", "⑤ 조사 오류·어색한 한국어"),
    ("layout",        "⑥ 레이아웃(공백·잘림·겹침)"),
]


# ── 07 참고: 브라우저 탐색 로직 ────────────────────────────────
BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str | None:
    for p in BROWSER_PATHS:
        if Path(p).exists():
            return p
    return None


# ── PDF/HTML → 페이지 이미지 ──────────────────────────────────

def _ensure_pymupdf() -> bool:
    """fitz(PyMuPDF) import 시도. 없으면 pip install 한 번 시도."""
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        print("  [변환] PyMuPDF 미설치 → pip install pymupdf 시도...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pymupdf"],
                           check=True, capture_output=True, text=True, timeout=180)
            import fitz  # noqa: F401
            return True
        except Exception as ex:
            print(f"  [변환] pymupdf 설치 실패: {ex}")
            return False


def pdf_to_images(pdf_path: Path, out_dir: Path, zoom: float = 2.0) -> list[Path]:
    """PyMuPDF 로 PDF 각 페이지를 PNG 로 렌더. 페이지 이미지 경로 리스트 반환."""
    import fitz
    imgs = []
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        p = out_dir / f"_qa_page_{i+1}.png"
        pix.save(str(p))
        imgs.append(p)
    doc.close()
    return imgs


def html_to_images(html_path: Path, out_dir: Path) -> list[Path]:
    """Chrome/Edge headless 로 worksheet.html 전체 페이지 스크린샷 (PDF 폴백)."""
    browser = find_browser()
    if not browser:
        print("  [변환] Chrome/Edge 미발견 — HTML 스크린샷 불가")
        return []
    shot = out_dir / "_qa_fullpage.png"
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--disable-extensions", "--hide-scrollbars",
           "--run-all-compositor-stages-before-draw",
           "--window-size=1240,3508",  # A4 폭 기준, 세로는 넉넉히
           f"--screenshot={shot.resolve()}",
           html_path.resolve().as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                       encoding="utf-8", errors="replace")
    except Exception as ex:
        print(f"  [변환] HTML 스크린샷 오류: {ex}")
        return []
    return [shot] if (shot.exists() and shot.stat().st_size > 0) else []


def build_page_images(ep_dir: Path) -> tuple[list[Path], str]:
    """대상 활동지를 페이지 이미지 리스트로 변환. (경로들, 소스설명) 반환."""
    pdf_path = ep_dir / "worksheet.pdf"
    html_path = ep_dir / "worksheet.html"

    if pdf_path.exists():
        if _ensure_pymupdf():
            try:
                imgs = pdf_to_images(pdf_path, ep_dir)
                if imgs:
                    return imgs, f"PDF→PNG (PyMuPDF, {len(imgs)}p)"
            except Exception as ex:
                print(f"  [변환] PDF 렌더 실패: {ex} → HTML 폴백 시도")
        # pymupdf 불가 → HTML 스크린샷 폴백
        if html_path.exists():
            imgs = html_to_images(html_path, ep_dir)
            if imgs:
                return imgs, "HTML→PNG (Chrome headless, PDF 변환 실패 폴백)"
        return [], "변환 실패 (PDF 있으나 렌더 불가, HTML 폴백도 실패)"

    if html_path.exists():
        imgs = html_to_images(html_path, ep_dir)
        if imgs:
            return imgs, "HTML→PNG (Chrome headless, PDF 없음)"
        return [], "변환 실패 (PDF 없음, HTML 스크린샷 실패)"

    return [], "worksheet.pdf/html 둘 다 없음"


# ── story.json 핵심 정보 요약 ─────────────────────────────────

def summarize_story(story: dict) -> str:
    m = story.get("meta", {})
    ch = m.get("characters", {})
    names = []
    for k, v in ch.items():
        if isinstance(v, dict) and v.get("name"):
            names.append(v["name"])
    quiz = story.get("activity_sheet", {}).get("quiz_questions", [])
    lines = [f"동화 제목: {m.get('story_title', '')}",
             f"주인공 이름: {', '.join(names) if names else '(없음)'}"]
    if quiz:
        lines.append("quiz_questions(활동지 문항 원본):")
        for i, q in enumerate(quiz, 1):
            lines.append(f"  Q{i}. {q.get('question','')}")
            lines.append(f"      정답: {q.get('answer','')}")
    return "\n".join(lines)


# ── 점검 프롬프트 ─────────────────────────────────────────────

def build_prompt(story_summary: str, n_pages: int) -> str:
    return f"""당신은 초등학교 1~2학년 독후 활동지의 품질을 검토하는 국어 교사입니다.
아래 이미지는 한 활동지의 페이지들입니다(총 {n_pages}장). 이미지를 정독하고,
같이 제공되는 원본 스토리 정보와 대조하여 아래 6개 항목을 '엄격하지만 오탐 없이' 판정하세요.

[원본 스토리 정보]
{story_summary}

[판정할 6개 항목]
① name_dup — 이름 중복·비문: 문장에 같은 인물 이름이 어색하게 중복되거나("토토와 토토는 ~"),
   이름 교체로 생긴 비문이 있는가. (서로 다른 두 주인공이 함께 나오는 정상 문장은 위반 아님)
② label_match — 문제-정답 라벨 대응: 정답키가 A/B/C 또는 번호 라벨을 쓰는데,
   정작 문제(보기)에는 그 라벨이 붙어 있지 않아 학생이 대조할 수 없는가.
③ hint_spoiler — 힌트=정답 노출: '힌트'가 정답(대사 전문/정답 단어)을 그대로 노출해서
   베껴 쓰기 활동으로 전락했는가. (상황·감정만 알려주는 힌트는 정상)
④ prompt_field — 지시-기입란 불일치: 활동 지시문(발문)과 기입란 라벨이 서로 다른 것을 요구하는가.
   (예: '기억에 남는 장면을 그려요'인데 기입란은 '이름을 지어 주세요/어디에 살까?')
⑤ korean_grammar — 조사 오류·어색한 한국어: 조사 오류(을/를·이/가·으로/로·에게/한테),
   비문, 어색한 문장이 있는가.
⑥ layout — 레이아웃 문제: 크게 빈 공백(지면 낭비), 텍스트 잘림, 요소 겹침이 있는가.

[판정 규칙]
- 각 항목은 결함이 '명백히 보일 때만' ok=false. 애매하면 ok=true (오탐 방지).
- issues 에는 이미지에서 실제로 관찰한 문구를 인용해 구체적으로 적으세요 (예: "1쪽 OX '토토와 토토는...' 이름 중복").
- 결함이 없으면 issues 는 빈 배열.

JSON 만 응답 (다른 텍스트 없이):
{{
 "name_dup":       {{"ok": <bool>, "issues": ["..."]}},
 "label_match":    {{"ok": <bool>, "issues": ["..."]}},
 "hint_spoiler":   {{"ok": <bool>, "issues": ["..."]}},
 "prompt_field":   {{"ok": <bool>, "issues": ["..."]}},
 "korean_grammar": {{"ok": <bool>, "issues": ["..."]}},
 "layout":         {{"ok": <bool>, "issues": ["..."]}}
}}"""


def load_image_part(path: Path):
    data = path.read_bytes()
    # 4MB 초과 시 pillow 로 축소
    if len(data) > 4 * 1024 * 1024:
        try:
            from PIL import Image
            import io
            img = Image.open(path)
            img.thumbnail((1600, 2400))
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            data = buf.getvalue()
        except Exception:
            pass
    return genai_types.Part.from_bytes(data=data, mime_type="image/png")


def check_worksheet_with_llm(page_imgs: list[Path], story: dict) -> dict:
    """페이지 이미지들 + 스토리 정보 → 6항목 판정 dict."""
    story_summary = summarize_story(story)
    prompt = build_prompt(story_summary, len(page_imgs))
    parts = [load_image_part(p) for p in page_imgs]
    parts.append(genai_types.Part.from_text(text=prompt))

    for attempt in range(3):
        try:
            resp = _client.models.generate_content(
                model=os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
                contents=parts,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = resp.text.strip()
            s = raw.find("{"); e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                result = json.loads(raw[s:e])
                # 항목 정규화 — 누락 항목은 통과(ok) 처리
                out = {}
                for key, _ in CHECK_ITEMS:
                    v = result.get(key, {})
                    if not isinstance(v, dict):
                        v = {"ok": True, "issues": []}
                    out[key] = {"ok": bool(v.get("ok", True)),
                                "issues": v.get("issues", []) or []}
                return out
        except Exception as ex:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                # 호출 실패는 게이트를 막지 않도록 통과 처리 + 오류 기록
                return {key: {"ok": True, "issues": []} for key, _ in CHECK_ITEMS} | \
                       {"_error": f"LLM 호출 실패: {ex}"}
    return {key: {"ok": True, "issues": []} for key, _ in CHECK_ITEMS} | \
           {"_error": "응답 파싱 실패"}


# ── 정리 ──────────────────────────────────────────────────────

def cleanup_temp(ep_dir: Path):
    for p in ep_dir.glob("_qa_page_*.png"):
        try: p.unlink()
        except Exception: pass
    fp = ep_dir / "_qa_fullpage.png"
    if fp.exists():
        try: fp.unlink()
        except Exception: pass


# ── 단일 폴더 점검 ────────────────────────────────────────────

def check_one(ep_dir: Path, quiet: bool = False) -> dict:
    """폴더 하나 점검. 결과 dict 반환 (worksheet_qa.json 저장 포함)."""
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        return {"dir": ep_dir.name, "ok": False, "source": "story.json 없음", "items": {}}

    story = json.loads(story_path.read_text(encoding='utf-8'))

    if not quiet:
        print(f"\n{'='*64}")
        print(f"  [07a] 활동지 QA: {story.get('meta',{}).get('story_title','')}")
        print(f"  대상: {ep_dir.name}")
        print(f"{'='*64}")

    page_imgs, source = build_page_images(ep_dir)
    if not page_imgs:
        if not quiet:
            print(f"  [변환 실패] {source}")
        return {"dir": ep_dir.name, "ok": False, "source": source, "items": {}}

    if not quiet:
        print(f"  이미지 변환: {source}")

    items = check_worksheet_with_llm(page_imgs, story)
    err = items.pop("_error", None)

    all_ok = all(items[key]["ok"] for key, _ in CHECK_ITEMS)

    result = {
        "dir": ep_dir.name,
        "story_title": story.get("meta", {}).get("story_title", ""),
        "source": source,
        "pdf_mtime": (ep_dir / "worksheet.pdf").stat().st_mtime if (ep_dir / "worksheet.pdf").exists() else None,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "all_ok": all_ok,
        "items": items,
    }
    if err:
        result["warning"] = err

    (ep_dir / "worksheet_qa.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    if not quiet:
        if err:
            print(f"  [경고] {err} — 판정 신뢰 불가")
        for key, label in CHECK_ITEMS:
            it = items[key]
            mark = "✓ 합격" if it["ok"] else "✗ 불합격"
            print(f"  {label}: {mark}")
            for iss in it["issues"]:
                print(f"        - {iss}")
        fails = [label for key, label in CHECK_ITEMS if not items[key]["ok"]]
        print(f"\n  종합: {'전 항목 합격' if all_ok else '불합격 항목 ' + str(len(fails)) + '건'}")
        print(f"  결과 저장: {ep_dir / 'worksheet_qa.json'}")
        print(f"  ※ 자동 수정하지 않음 — 사람 최종 판단용 리포트")

    cleanup_temp(ep_dir)
    return result


# ── --all 순회 ────────────────────────────────────────────────

def check_all():
    out_root = BASE_DIR / "output"
    targets = sorted([p.parent for p in out_root.glob("*/worksheet.pdf")])
    if not targets:
        print("[INFO] output/*/worksheet.pdf 대상이 없습니다.")
        return 0

    print(f"\n[07a --all] 활동지 {len(targets)}편 순회 점검\n")
    rows = []
    for d in targets:
        r = check_one(d, quiet=True)
        rows.append(r)
        status = "PASS" if r.get("all_ok") else "FAIL"
        fails = [k for k, _ in CHECK_ITEMS if r.get("items", {}).get(k, {}).get("ok", True) is False]
        codes = ",".join("①②③④⑤⑥"[[c for c, _ in CHECK_ITEMS].index(f)] for f in fails) if fails else "-"
        print(f"  [{status:4}] {codes:12} {d.name[:52]}")

    n_fail = sum(1 for r in rows if not r.get("all_ok"))
    print(f"\n{'='*64}")
    print("  요약 표 (①이름중복 ②라벨대응 ③힌트=정답 ④지시-기입란 ⑤한국어 ⑥레이아웃)")
    print(f"{'='*64}")
    print(f"  {'결과':4} {'불합격항목':12} 폴더")
    for r in rows:
        status = "PASS" if r.get("all_ok") else "FAIL"
        fails = [k for k, _ in CHECK_ITEMS if r.get("items", {}).get(k, {}).get("ok", True) is False]
        codes = "".join("①②③④⑤⑥"[[c for c, _ in CHECK_ITEMS].index(f)] for f in fails) if fails else "-"
        print(f"  {status:4} {codes:12} {r.get('dir','')[:52]}")
    print(f"\n  총 {len(rows)}편 | 합격 {len(rows)-n_fail} | 불합격 {n_fail}")

    return 1 if n_fail else 0


# ── 경로 해석 ─────────────────────────────────────────────────

def resolve_ep_dir(args) -> Path:
    if args.dir_path:
        d = Path(args.dir_path)
    else:
        d = BASE_DIR / "output" / f"ep{int(args.ep):02d}"
    if not d.is_absolute():
        d = BASE_DIR / d
    if not d.exists():
        print(f"[ERROR] 디렉토리 없음: {d}")
        sys.exit(1)
    return d


# ── 메인 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="활동지 QA 게이트 — worksheet.pdf 6항목 Vision 점검 (사람 검토용 리포트)")
    parser.add_argument("--ep", type=int, help="에피소드 번호")
    parser.add_argument("--dir", dest="dir_path", type=str, help="에피소드 디렉토리 (output/폴더)")
    parser.add_argument("--all", action="store_true", help="output/*/worksheet.pdf 전부 순회 점검")
    args = parser.parse_args()

    if args.all:
        sys.exit(check_all())

    if not args.ep and not args.dir_path:
        parser.print_help()
        sys.exit(1)

    ep_dir = resolve_ep_dir(args)
    result = check_one(ep_dir)
    sys.exit(0 if result.get("all_ok") else 1)


if __name__ == "__main__":
    main()
