#!/usr/bin/env python3
"""
08_generate_book_pptx.py
동화 story.json + 이미지를 실제 그림책 같은 PPTX로 변환합니다.
한국어 에피소드 전용.

1분할: 풀블리드 일러스트 + 하단 텍스트 오버레이 (그림책 스타일)
2분할: 이미지 좌측 패널(센터크롭) + 텍스트 우측 패널

사용법:
  python 08_generate_book_pptx.py --dir output/bsl02
  python 08_generate_book_pptx.py --dir output/ep01 --mode 1
  python 08_generate_book_pptx.py --dir output/ep01 --mode 2
  python 08_generate_book_pptx.py --dir output/ep01 --mode both  (기본)
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from pptx import Presentation
    from pptx.util import Cm, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.oxml.ns import qn
    from lxml import etree
except ImportError:
    print("[ERROR] python-pptx 필요: pip install python-pptx")
    sys.exit(1)

# ── 슬라이드 크기 (16:9 와이드스크린) ─────────────────────────
SLIDE_W   = Cm(33.87)
SLIDE_H   = Cm(19.05)
IMG_RATIO = 1344 / 768   # 이미지 원본 가로/세로 비율 (≈1.75)

# ── 색상 ───────────────────────────────────────────────────────
C_WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
C_OFF_WHITE= RGBColor(0xFF, 0xFE, 0xFA)   # 아이보리 화이트
C_PAPER    = RGBColor(0xFA, 0xF8, 0xF3)   # 종이색
C_DARK     = RGBColor(0x1A, 0x1A, 0x1A)   # 본문
C_NARRATOR = RGBColor(0x4A, 0x5A, 0x68)   # 나레이터 청회색
C_GRAY     = RGBColor(0xAA, 0xAA, 0xAA)   # 페이지 번호 등 보조

# ── 폰트 ──────────────────────────────────────────────────────
FONT_TITLE = "Noto Serif KR"   # 제목 / 표지 (세리프, 우아함)
FONT_BODY  = "Noto Sans KR"    # 본문 / 나레이터 / 대사 (산세리프, 가독성)
FONT_KO    = FONT_BODY          # 하위 호환

AUTHOR_KO  = "햄찌쌤"
AUTHOR_EN  = "Teacher Hami"

# ── 폰트 파일 경로 ────────────────────────────────────────────
_ASSETS = Path(__file__).parent / "assets" / "fonts"
_FONT_FILES = {
    "Noto Serif KR": {
        "regular": _ASSETS / "NotoSerifKR-Regular.ttf",
        "bold":    _ASSETS / "NotoSerifKR-SemiBold.ttf",
    },
    "Noto Sans KR": {
        "regular": _ASSETS / "NotoSansKR-Regular.ttf",
        "bold":    _ASSETS / "NotoSansKR-Bold.ttf",
    },
}


# ──────────────────────────────────────────────────────────────
#  색상 유틸
# ──────────────────────────────────────────────────────────────

def _rgb(c: RGBColor):
    """RGBColor → (r, g, b)  (pptx 1.x tuple 서브클래스 대응)."""
    return c[0], c[1], c[2]

def darken(c: RGBColor, f=0.60) -> RGBColor:
    r, g, b = _rgb(c)
    return RGBColor(int(r*f), int(g*f), int(b*f))

def lighten(c: RGBColor, f=0.80) -> RGBColor:
    r, g, b = _rgb(c)
    return RGBColor(int(r+(255-r)*f), int(g+(255-g)*f), int(b+(255-b)*f))

def hex_to_rgb(h: str) -> RGBColor:
    h = h.lstrip("#")
    return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

def rgb_hex(c: RGBColor) -> str:
    r, g, b = _rgb(c)
    return f"{r:02X}{g:02X}{b:02X}"


# ──────────────────────────────────────────────────────────────
#  도형 / 텍스트 기본 헬퍼
# ──────────────────────────────────────────────────────────────

def embed_fonts(prs):
    """Noto Serif KR / Noto Sans KR 를 PPTX에 바이너리 임베드.
    어떤 컴에서 열어도 동일한 폰트로 렌더링.
    """
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    FONT_REL = ("http://schemas.openxmlformats.org/officeDocument/"
                "2006/relationships/font")
    FONT_CT  = "application/x-fontdata"
    R_NS     = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    prs_part = prs.part
    prs_elem = prs.element   # <p:presentation> XML 루트

    efl = prs_elem.find(qn("p:embeddedFontLst"))
    if efl is None:
        efl = etree.SubElement(prs_elem, qn("p:embeddedFontLst"))

    idx = 1
    for typeface, styles in _FONT_FILES.items():
        ef = etree.SubElement(efl, qn("p:embeddedFont"))
        fe = etree.SubElement(ef, qn("p:font"))
        fe.set("typeface", typeface)
        fe.set("pitchFamily", "0")
        fe.set("charset", "-122")   # Korean

        for style_key, xml_tag in [("regular", "p:regular"), ("bold", "p:bold")]:
            path = styles.get(style_key)
            if not path or not path.exists():
                continue
            data    = path.read_bytes()
            pname   = PackURI(f"/ppt/fonts/font{idx}.fntdata")
            f_part  = Part(pname, FONT_CT, data)
            rId     = prs_part.relate_to(f_part, FONT_REL)
            se      = etree.SubElement(ef, qn(xml_tag))
            se.set(f"{{{R_NS}}}id", rId)
            idx += 1

    print(f"[INFO] 폰트 임베드: {idx-1}개 파일 ({typeface} 등)")


def fill_rect(slide, l, t, w, h, fill: RGBColor):
    sp = slide.shapes.add_shape(1, l, t, w, h)
    sp.fill.solid(); sp.fill.fore_color.rgb = fill
    sp.line.fill.background()
    return sp

def no_fill_rect(slide, l, t, w, h):
    sp = slide.shapes.add_shape(1, l, t, w, h)
    sp.fill.background(); sp.line.fill.background()
    return sp

def set_alpha(shape, pct: int):
    """도형 채우기 불투명도 설정 (pct: 0~100)."""
    try:
        val = str(int(pct * 1000))
        sp   = shape._element
        sf   = sp.find(".//" + qn("a:solidFill"))
        if sf is None: return
        for tag in (qn("a:srgbClr"), qn("a:sysClr"), qn("a:prstClr"), qn("a:schemeClr")):
            el = sf.find(tag)
            if el is not None:
                a_el = el.find(qn("a:alpha"))
                if a_el is None:
                    a_el = etree.SubElement(el, qn("a:alpha"))
                a_el.set("val", val)
                break
    except Exception:
        pass

def send_back(slide, shape):
    """shape를 z-order 맨 뒤로."""
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2, shape._element)

def tb(slide, l, t, w, h, anchor=None):
    """텍스트박스 추가 → text_frame 반환.
    anchor: MSO_ANCHOR.TOP / MIDDLE / BOTTOM (None이면 기본값 TOP)
    """
    box = slide.shapes.add_textbox(l, t, w, h)
    tf  = box.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    if anchor is not None:
        tf.vertical_anchor = anchor
    return tf


# ──────────────────────────────────────────────────────────────
#  줄바꿈 알고리즘
# ──────────────────────────────────────────────────────────────

_BREAK = set('.!?,。，')

_CHAR_W = {"ko": 1.05, "default": 0.58}   # CJK=풀폭, Latin=반폭 평균
_CPL_MAX = {"ko": 28, "default": 52}       # 중앙정렬 미관 최대 글자수/줄

def char_w(lang: str) -> float:
    return _CHAR_W.get(lang, _CHAR_W["default"])

def cpl_max(lang: str) -> int:
    return _CPL_MAX.get(lang, _CPL_MAX["default"])

def cpl(box_w_cm: float, font_pt: float, lang: str = "ko") -> int:
    """줄당 추정 글자 수. CJK(한국어)와 Latin(영어 등) 구분."""
    return max(8, int(box_w_cm * 28.35 / (font_pt * char_w(lang))) - 1)

def wrap(text: str, max_cpl: int) -> list[str]:
    """
    텍스트를 max_cpl 기준으로 균형 있게 줄바꿈.
    구두점 뒤를 우선 끊고, 없으면 강제 분할.
    반환: 줄 문자열 리스트
    """
    text = text.strip()
    n    = len(text)
    if n == 0: return []
    if n <= max_cpl: return [text]

    num_lines = math.ceil(n / max_cpl)
    target    = math.ceil(n / num_lines)

    lines, pos = [], 0
    while pos < n:
        rem = n - pos
        if rem <= target:
            lines.append(text[pos:].strip())
            break
        # target 근처 ±7 글자 범위에서 구두점 뒤 탐색 (역방향)
        best = target
        lo   = max(1, target - 7)
        hi   = min(rem - 1, target + 7)
        for k in range(hi, lo - 1, -1):
            if text[pos + k - 1] in _BREAK:
                best = k
                break
        lines.append(text[pos : pos + best].rstrip())
        pos += best
        while pos < n and text[pos] == ' ':
            pos += 1

    return [l for l in lines if l]


# ──────────────────────────────────────────────────────────────
#  텍스트 높이 추정 + 박스 자동 맞춤 알고리즘
# ──────────────────────────────────────────────────────────────
#
#  원칙: 폰트 크기는 절대 줄이지 않음.
#  대신 1분할 오버레이 높이를 내용에 맞게 동적으로 확장.
#  최대 높이 초과 시에만 뒤 아이템부터 제거.
#
#  추정 공식:
#    줄 높이 = font_pt × LINE_SPACING  (Noto Sans KR 실측 근사)
#    총 높이 = Σ(줄수 × 줄높이) + Σ(세그먼트 간격) + 텍스트박스 상하 여백
# ──────────────────────────────────────────────────────────────

LINE_SPACING  = 1.50    # 줄간격 배수 (Noto 한글 실측 보수적 추정)

def auto_title_pt(title: str, box_w_cm: float,
                  max_pt: float = 62.0, min_pt: float = 18.0,
                  max_lines: int = 2, lang: str = "ko") -> float:
    """
    제목이 box_w_cm 너비에서 max_lines줄 이내로 들어오는
    가장 큰 폰트 크기(pt)를 반환. → 표지를 꽉 채우는 최대 크기.
    """
    n = len(title)
    for pt in range(int(max_pt), int(min_pt) - 1, -1):
        lc = cpl(box_w_cm, float(pt), lang)
        if n <= lc * max_lines:
            return float(pt)
    return float(min_pt)
TB_INSET_PT   = 5.0     # 텍스트박스 상하 내부 여백 합계 (pt)
EMU_PER_PT    = 12700   # 1pt = 12700 EMU

# 1분할 오버레이 높이 범위
OV_H_MIN  = Cm(2.80)    # 최소 높이 (짧은 텍스트용)
OV_H_MAX  = Cm(6.00)    # 최대 높이 (이미지 보존 한계)
OV_LINE_H = Cm(0.06)    # 상단 악센트 선 높이
OV_PAD    = Cm(0.40)    # 텍스트 상하 패딩 합계


def estimate_text_height(items: list, lines_cpl: int,
                         font_pt: float, seg_spc_pt: float = 6.0) -> float:
    """
    items 목록의 예상 렌더링 높이 (pt 단위) 반환.
    텍스트박스 내부 여백(TB_INSET_PT) 포함.
    """
    line_h = font_pt * LINE_SPACING
    total  = TB_INSET_PT
    for i, it in enumerate(items):
        n = len(wrap(it["text"], lines_cpl))
        if i > 0:
            total += seg_spc_pt
        total += n * line_h
    return total


def calc_overlay(
    items: list,
    tw_cm: float,
    font_pt: float = 14.0,
    seg_spc: float = 5.0,
    lang: str      = "ko",
) -> tuple:
    """
    1분할 오버레이용. 폰트 크기 고정, 높이를 내용에 맞게 결정.

    반환: (ov_h_emu, lines_cpl, shown_items)
      ov_h_emu  : 오버레이 전체 높이 (EMU) — OV_H_MIN ~ OV_H_MAX 사이
      lines_cpl : wrap() 에 쓸 줄당 글자수
      shown_items: 실제 렌더링할 아이템 (초과 시 뒤에서 제거)
    """
    lc = min(cpl_max(lang), cpl(tw_cm, font_pt, lang))

    # 최대 오버레이에서 허용되는 텍스트 높이 (pt)
    max_text_pt = (OV_H_MAX - OV_LINE_H - OV_PAD) / EMU_PER_PT

    # 초과 시 뒤 아이템 제거
    shown = list(items)
    while len(shown) > 1:
        if estimate_text_height(shown, lc, font_pt, seg_spc) <= max_text_pt:
            break
        dropped = shown.pop()
        print(f"[WARN] 오버레이 초과 → '{dropped['text'][:12]}...' 제외")

    # 실제 필요 높이 → 오버레이 동적 설정
    text_h_pt  = estimate_text_height(shown, lc, font_pt, seg_spc)
    text_h_emu = int(text_h_pt * EMU_PER_PT)
    ov_h = max(OV_H_MIN, min(OV_H_MAX, text_h_emu + OV_LINE_H + OV_PAD))

    return ov_h, lc, shown


def auto_font_fit(
    items: list,
    tw_cm: float,
    th_emu: float,
    max_pt: float = 14.0,
    min_pt: float = 9.0,
    seg_spc: float = 6.0,
    allow_trim: bool = False,
    lang: str = "ko",
) -> tuple:
    """
    2분할 전용: 고정 높이 박스 안에서 폰트 크기 조정 없이 아이템 트림.
    (2분할은 페이지 전체 높이 → 실제로 거의 항상 fits)
    반환: (font_pt, lines_cpl, shown_items) — font_pt는 항상 max_pt
    """
    lc    = cpl(tw_cm, max_pt, lang)
    th_pt = th_emu / EMU_PER_PT

    if estimate_text_height(items, lc, max_pt, seg_spc) <= th_pt:
        return max_pt, lc, items

    # 들어가지 않는 극단적 케이스만 뒤에서 제거
    shown = list(items)
    while len(shown) > 1:
        shown.pop()
        if estimate_text_height(shown, lc, max_pt, seg_spc) <= th_pt:
            break

    return max_pt, lc, shown


# ──────────────────────────────────────────────────────────────
#  단락 렌더링
# ──────────────────────────────────────────────────────────────

def _run(para, text, sz=Pt(12), bold=False, italic=False,
         color: RGBColor = None, font: str = FONT_BODY):
    r = para.add_run()
    r.text = text
    r.font.name  = font
    r.font.size  = sz
    r.font.bold  = bold
    r.font.italic = italic
    if color:
        r.font.color.rgb = color

def _para(tf, first: bool, align=PP_ALIGN.LEFT, spc_before=Pt(0)):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment    = align
    p.space_before = spc_before
    p.space_after  = Pt(0)
    return p


def render_simple(tf, items: list, lines_cpl: int,
                  sz=Pt(12), seg_spc=Pt(6)):
    """
    역할 구분 없이 한 텍스트박스에 전체 렌더링. 전부 중앙 정렬.
    - 나레이터: 중앙 정렬, 이탤릭, 회청색
    - 대화:    중앙 정렬, "" 로만 표시 (이름 없음)
    """
    first = True
    for i, it in enumerate(items):
        spc = Pt(0) if i == 0 else seg_spc

        if it["type"] == "narrate":
            lines = wrap(it["text"], lines_cpl)
            for j, line in enumerate(lines):
                p = _para(tf, first and j == 0,
                          align=PP_ALIGN.CENTER,
                          spc_before=spc if j == 0 else Pt(0))
                _run(p, line, sz=sz, italic=True, color=C_NARRATOR)
                first = False

        else:
            lines = wrap(it["text"], lines_cpl)
            for j, line in enumerate(lines):
                p = _para(tf, first and j == 0,
                          align=PP_ALIGN.CENTER,
                          spc_before=spc if j == 0 else Pt(0))
                is_first = (j == 0)
                is_last  = (j == len(lines) - 1)
                prefix   = "\u201c" if is_first else ""
                suffix   = "\u201d" if is_last  else ""
                _run(p, prefix + line + suffix, sz=sz, color=C_DARK)
                first = False


# ──────────────────────────────────────────────────────────────
#  스피커 해석
# ──────────────────────────────────────────────────────────────

def resolve(speaker: str, characters: dict,
            accent: RGBColor, sub_accent: RGBColor):
    """(이름, 색상). narrator → ("", None)."""
    if speaker in ("narrator", "narration", ""):
        return "", None
    ch = characters.get(speaker, {})
    name = ch.get("name", "")
    if not name:
        for v in characters.get("supporting", {}).values():
            if isinstance(v, dict) and v.get("name"):
                # key 매칭 대신 speaker가 supporting 키면
                pass
        sup = characters.get("supporting", {})
        if speaker in sup:
            name = sup[speaker].get("name", speaker)
    if not name:
        name = speaker

    if   speaker == "main_1": color = accent
    elif speaker == "main_2": color = sub_accent
    else:                      color = RGBColor(0x88, 0x66, 0x44)
    return name, color


def build_items(segs: list, characters: dict,
                accent: RGBColor, sub_accent: RGBColor) -> list:
    """TTS 세그먼트 → [{type, text, name?, color?}]."""
    result = []
    for s in segs:
        text    = s.get("text", "").strip()
        speaker = s.get("speaker", s.get("voice", "narrator"))
        if not text: continue
        name, color = resolve(speaker, characters, accent, sub_accent)
        if name:
            result.append({"type": "dialog", "name": name, "color": color, "text": text})
        else:
            result.append({"type": "narrate", "text": text})
    return result


# ──────────────────────────────────────────────────────────────
#  이미지 배치
# ──────────────────────────────────────────────────────────────

def place_image_fullbleed(slide, img_path: Path):
    """
    이미지를 슬라이드 전체 폭에 맞게 배치.
    높이는 비율 유지 → 슬라이드 높이보다 약간 클 수 있음 (미세 상하 크롭).
    """
    if not img_path or not img_path.exists():
        return
    # 폭만 지정 → 높이 자동 (비율 유지)
    img_w  = SLIDE_W
    img_h  = img_w / IMG_RATIO               # ≈ 19.35cm
    img_top = (SLIDE_H - img_h) / 2          # 중앙 정렬 (≈ -0.15cm)
    pic = slide.shapes.add_picture(str(img_path), 0, img_top, img_w, img_h)
    send_back(slide, pic)
    return pic


def place_image_panel(slide, img_path: Path,
                      panel_l, panel_top, panel_w, panel_h):
    """
    좌측 패널 전체 높이를 채우는 센터크롭 배치.
    이미지를 패널 높이에 맞추고, 가로 중앙 슬라이스만 보이도록
    이미지를 panel_l 기준 음수 x에 배치 (우측 패널이 오른쪽을 가림).
    """
    if not img_path or not img_path.exists():
        return
    img_h  = panel_h
    img_w  = img_h * IMG_RATIO               # 원본 비율 유지
    img_l  = panel_l + (panel_w - img_w) / 2  # 수평 중앙 정렬 (음수 가능)
    pic = slide.shapes.add_picture(str(img_path), img_l, panel_top, img_w, img_h)
    # 이미지를 배경 바로 위에
    tree = slide.shapes._spTree
    tree.remove(pic._element)
    tree.insert(3, pic._element)
    return pic


# ──────────────────────────────────────────────────────────────
#  표지 슬라이드
# ──────────────────────────────────────────────────────────────

def add_cover(prs, sd: dict, img_path: Path, meta: dict, accent: RGBColor,
              lang: str = "ko"):
    """
    표지: 풀블리드 이미지 + 정중앙 제목.
    무거운 오버레이 없이 얇은 텍스트를 슬라이드 정중앙에 배치.
    """
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)

    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_WHITE

    # ── 풀블리드 이미지 ────────────────────────────────────────
    place_image_fullbleed(slide, img_path)

    # ── 메타 정보 (있을 때만) ─────────────────────────────────
    subject    = meta.get("subject", "")
    grade      = meta.get("grade", "")
    series     = meta.get("series", "")
    unit_title = meta.get("unit_title", "")
    parts      = [p for p in [subject,
                               series if series and series != subject else "",
                               unit_title,
                               f"{grade}학년" if grade else ""] if p]
    meta_label = "  ·  ".join(parts)

    # ── 제목 레이아웃 ─────────────────────────────────────────
    title   = meta.get("story_title", sd.get("text", "동화"))
    MARGIN  = Cm(2.0)
    block_w = SLIDE_W - MARGIN * 2
    block_l = MARGIN
    bw_cm   = block_w / 360000

    # 폭을 꽉 채우는 최대 폰트 크기 자동 결정 (최대 2줄)
    title_pt  = auto_title_pt(title, bw_cm, max_pt=62.0, min_pt=18.0, lang=lang)
    title_sz  = Pt(title_pt)
    lc_title  = cpl(bw_cm, title_pt, lang)
    n_lines   = len(wrap(title, lc_title))

    # 제목 박스 높이: 줄수 × 줄간격 + 여유
    title_box_h = Cm(title_pt * LINE_SPACING * n_lines / 28.35) + Cm(0.4)

    # 메타/저자 높이
    meta_h   = Cm(0.70) if meta_label else Cm(0)
    author_h = Cm(0.70)
    GAP      = Cm(0.20)   # 요소 간 간격

    # 전체 블록 높이 (동적)
    block_h = meta_h + title_box_h + author_h + GAP * 2
    block_t = (SLIDE_H - block_h) / 2   # 슬라이드 수직 정중앙

    # ── 반투명 배경 밴드 ─────────────────────────────────────
    bg = fill_rect(slide, 0, block_t - Cm(0.35),
                   SLIDE_W, block_h + Cm(0.70), fill=C_WHITE)
    set_alpha(bg, 55)

    # 악센트 선 (위·아래)
    fill_rect(slide, block_l, block_t - Cm(0.1),
              block_w, Cm(0.04), fill=accent)
    fill_rect(slide, block_l, block_t + block_h + Cm(0.06),
              block_w, Cm(0.04), fill=accent)

    # ── 메타 라벨 (블록 상단) ────────────────────────────────
    cur_y = block_t
    if meta_label:
        tfi = tb(slide, block_l, cur_y, block_w, meta_h)
        pi  = tfi.paragraphs[0]
        pi.alignment = PP_ALIGN.CENTER
        _run(pi, meta_label, sz=Pt(9), color=C_NARRATOR, font=FONT_BODY)
        cur_y += meta_h + GAP

    # ── 제목 (폭을 꽉 채우는 최대 크기, 수직 중앙) ───────────
    tft = tb(slide, block_l, cur_y, block_w, title_box_h, anchor=MSO_ANCHOR.MIDDLE)
    pt  = tft.paragraphs[0]
    pt.alignment = PP_ALIGN.CENTER
    _run(pt, title, sz=title_sz, bold=False, color=C_DARK, font=FONT_TITLE)
    cur_y += title_box_h + GAP

    # ── 저자 (블록 하단) ──────────────────────────────────────
    tfa = tb(slide, block_l, cur_y, block_w, author_h)
    pa  = tfa.paragraphs[0]
    pa.alignment = PP_ALIGN.CENTER
    author_str = AUTHOR_KO if lang == "ko" else AUTHOR_EN
    _run(pa, author_str, sz=Pt(10), color=darken(accent, 0.75), font=FONT_BODY)


# ──────────────────────────────────────────────────────────────
#  1분할: 풀블리드 이미지 + 하단 텍스트 오버레이
# ──────────────────────────────────────────────────────────────
#
#  ┌──────────────────────────────────────────┐
#  │                                          │
#  │         풀블리드 일러스트                  │  SLIDE_H - OV_H
#  │      (슬라이드 폭 꽉 채움, 미세 크롭)      │
#  │                                          │
#  ├══════════════════════════════════════════╡  얇은 악센트 선
#  │ [흰색 패널]                               │
#  │ 나레이터 텍스트 (중앙, 이탤릭, 회청색)    │  OV_H = 3.2cm
#  │ 솔이  "대사 내용..."                      │
#  │                              [page N]    │
#  └──────────────────────────────────────────┘

# OV_H_MIN/MAX/LINE_H/PAD 는 텍스트 높이 추정 섹션에 정의됨 (동적 계산)


def add_1col(prs, sd: dict, img_path: Path,
             meta: dict, page_num: int, total: int,
             accent: RGBColor, sub_accent: RGBColor,
             lang: str = "ko"):
    """
    1분할: 풀블리드 이미지 + 하단 반투명 텍스트 오버레이.
    오버레이가 뒤의 이미지를 약간 비쳐 보이게 함.
    """
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)

    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_WHITE

    characters = meta.get("characters", {})

    # ── 텍스트 → 오버레이 높이 사전 결정 ────────────────────────
    font_pt = 14.0
    tw      = SLIDE_W - Cm(4.0)
    tw_cm   = tw / 360000

    tts_segs = sd.get("tts_segments", [])
    items    = build_items(tts_segs, characters, accent, sub_accent)

    # 폰트 고정, 오버레이 높이를 내용에 맞게 동적 계산
    ov_h, lines_cpl, shown = calc_overlay(
        items, tw_cm, font_pt=font_pt, seg_spc=5.0, lang=lang
    )
    ov_top = SLIDE_H - ov_h
    th     = ov_h - OV_LINE_H - OV_PAD   # 텍스트 박스 높이

    # ── 풀블리드 이미지 ────────────────────────────────────────
    place_image_fullbleed(slide, img_path)

    # ── 반투명 흰색 오버레이 (높이 동적) ─────────────────────────
    ov = fill_rect(slide, 0, ov_top, SLIDE_W, ov_h, fill=C_WHITE)
    set_alpha(ov, 65)   # 65% 불투명 → 이미지 35% 비침

    # 상단 얇은 악센트 라인
    fill_rect(slide, 0, ov_top, SLIDE_W, OV_LINE_H, fill=accent)

    # ── 텍스트 (오버레이 안에서 수직 중앙 정렬) ──────────────────
    tx = Cm(2.0)
    ty = ov_top + OV_LINE_H + OV_PAD / 2

    if shown:
        tframe = tb(slide, tx, ty, tw, th, anchor=MSO_ANCHOR.MIDDLE)
        render_simple(tframe, shown, lines_cpl, sz=Pt(font_pt), seg_spc=Pt(5))

    # ── 페이지 번호 (우하단, 오버레이 안) ────────────────────────
    tfp = tb(slide, SLIDE_W - Cm(2.8), ov_top + ov_h - Cm(0.55), Cm(2.5), Cm(0.45))
    pp  = tfp.paragraphs[0]
    pp.alignment = PP_ALIGN.RIGHT
    _run(pp, str(page_num), sz=Pt(8.5), color=C_GRAY)


# ──────────────────────────────────────────────────────────────
#  2분할: 이미지 좌측 패널 + 텍스트 우측 패널
# ──────────────────────────────────────────────────────────────
#
#  ┌──────────────────────┬────────────────────┐
#  │  [좌측 이미지 패널]   │ 과목 · 단원         │  ← 소형 라벨 (바 아님)
#  │  센터크롭 풀 하이트   │                     │
#  │                      │ 나레이터            │
#  │  이미지 가로 중앙     │ "텍스트..."         │
#  │  슬라이스만 표시      │                     │
#  │                      │ 솔이               │
#  │                      │ "대사 내용..."      │
#  │                      │                     │
#  │                      │          [page N]   │
#  └──────────────────────┴────────────────────┘
#   LEFT_W = 18.0cm          RIGHT_W = 15.87cm

LEFT_W  = Cm(18.5)
RIGHT_W = SLIDE_W - LEFT_W   # 15.37cm


def add_2col(prs, sd: dict, img_path: Path,
             meta: dict, page_num: int, total: int,
             accent: RGBColor, sub_accent: RGBColor,
             lang: str = "ko"):
    """
    2분할: 진짜 책 펼침 레이아웃.
    좌페이지 = 이미지(센터크롭, 풀하이트) / 우페이지 = 종이색 배경 + 텍스트.
    """
    layout = prs.slide_layouts[6]
    slide  = prs.slides.add_slide(layout)

    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_PAPER

    characters  = meta.get("characters", {})
    subject     = meta.get("subject", "")
    unit_title  = meta.get("unit_title", meta.get("sub_unit", ""))
    story_title = meta.get("story_title", "")

    # ── 좌페이지: 이미지 (센터크롭, 풀 하이트) ──────────────────
    place_image_panel(slide, img_path,
                      panel_l=0, panel_top=0,
                      panel_w=LEFT_W, panel_h=SLIDE_H)

    # ── 책 제본 그림자 선 ─────────────────────────────────────
    fill_rect(slide, LEFT_W - Cm(0.04), 0, Cm(0.08), SLIDE_H,
              fill=darken(accent, 0.45))

    # ── 우페이지: 종이색 배경 ─────────────────────────────────
    fill_rect(slide, LEFT_W, 0, RIGHT_W, SLIDE_H, fill=C_PAPER)

    # 상단 얇은 악센트 라인
    fill_rect(slide, LEFT_W, 0, RIGHT_W, Cm(0.05), fill=accent)

    # ── 텍스트 영역 (상하 수직 중앙 정렬) ────────────────────
    inner_pad = Cm(1.0)
    tx    = LEFT_W + inner_pad
    ty    = Cm(0.65)
    tw    = RIGHT_W - inner_pad * 2
    th    = SLIDE_H - Cm(0.65) - Cm(0.9)   # 하단 여백 확보
    tw_cm = tw / 360000

    tts_segs = sd.get("tts_segments", [])
    items    = build_items(tts_segs, characters, accent, sub_accent)

    # ── 자동 검증: 박스를 넘지 않는 최적 폰트 결정 ──────────────
    font_pt, lines_cpl, shown = auto_font_fit(
        items, tw_cm, th, max_pt=14.0, seg_spc=8.0, lang=lang
    )

    if shown:
        tframe = tb(slide, tx, ty, tw, th, anchor=MSO_ANCHOR.MIDDLE)
        render_simple(tframe, shown, lines_cpl, sz=Pt(font_pt), seg_spc=Pt(8))

    # ── 메타 라벨 (우페이지 상단 우측, 소형) ─────────────────
    if subject or unit_title:
        label = f"{subject}  ·  {unit_title}" if subject else unit_title
        tfl  = tb(slide, tx, Cm(0.08), tw - Cm(0.2), Cm(0.52))
        pl   = tfl.paragraphs[0]
        pl.alignment = PP_ALIGN.RIGHT
        _run(pl, label, sz=Pt(7.5), color=darken(accent, 0.7))

    # ── 페이지 번호 + 책 제목 (우페이지 하단) ─────────────────
    bot_y = SLIDE_H - Cm(0.75)
    if story_title:
        tft = tb(slide, tx, bot_y, tw - Cm(2.8), Cm(0.6))
        pt2 = tft.paragraphs[0]
        pt2.alignment = PP_ALIGN.LEFT
        _run(pt2, story_title, sz=Pt(7.5), italic=True, color=C_GRAY)
    tfp = tb(slide, LEFT_W + RIGHT_W - Cm(3.5), bot_y, Cm(3.2), Cm(0.6))
    pp  = tfp.paragraphs[0]
    pp.alignment = PP_ALIGN.RIGHT
    _run(pp, f"{page_num}  /  {total}", sz=Pt(8), color=C_GRAY)


# ──────────────────────────────────────────────────────────────
#  퀴즈 슬라이드 (1·2분할 공용)
# ──────────────────────────────────────────────────────────────

def _quiz_footer(slide, story_title: str, accent: RGBColor):
    """퀴즈 슬라이드 공통 하단 라인 + 제목."""
    fill_rect(slide, 0, SLIDE_H - Cm(0.65), SLIDE_W, Cm(0.05),
              fill=lighten(accent, 0.40))
    tff = tb(slide, Cm(2), SLIDE_H - Cm(0.6), SLIDE_W - Cm(4), Cm(0.5))
    pf  = tff.paragraphs[0]
    pf.alignment = PP_ALIGN.CENTER
    _run(pf, story_title, sz=Pt(8), italic=True, color=C_GRAY)


def _quiz_header(slide, heading: str, accent: RGBColor):
    """퀴즈 슬라이드 공통 상단 바 + 제목 텍스트."""
    fill_rect(slide, 0, 0, SLIDE_W, Cm(2.0), fill=accent)
    tf_h = tb(slide, Cm(1), Cm(0.3), SLIDE_W - Cm(2), Cm(1.4))
    ph   = tf_h.paragraphs[0]
    ph.alignment = PP_ALIGN.CENTER
    _run(ph, heading, sz=Pt(22), bold=True, color=C_WHITE)


def add_quiz(prs, questions: list, meta: dict,
             accent: RGBColor, mode: str):
    """퀴즈를 슬라이드 쌍으로 분리: Q1 → A1 → Q2 → A2 → Q3 → A3 (최대 6슬라이드).

    영상 마지막 구간과 동일한 문제-정답 교대 흐름.
    """
    if not questions:
        return

    story_title = meta.get("story_title", "")
    layout = prs.slide_layouts[6]
    body_x  = Cm(3)
    body_w  = SLIDE_W - Cm(6)
    body_y  = Cm(2.4)
    body_h  = SLIDE_H - Cm(3.2)

    for i, q in enumerate(questions):
        q_text = q.get("question", "")
        a_text = q.get("answer", "")
        q_num  = i + 1

        # ── 문제 슬라이드 ─────────────────────────────────────
        slide_q = prs.slides.add_slide(layout)
        slide_q.background.fill.solid()
        slide_q.background.fill.fore_color.rgb = C_WHITE

        _quiz_header(slide_q, f"Q{q_num}.  문제", accent)

        tf_q = tb(slide_q, body_x, body_y, body_w, body_h,
                  anchor=MSO_ANCHOR.MIDDLE)
        p0 = tf_q.paragraphs[0]
        p0.alignment = PP_ALIGN.CENTER
        qcpl = cpl(body_w / 360000, 20.0)
        qlines = wrap(q_text, qcpl)
        for j, line in enumerate(qlines):
            p = p0 if j == 0 else _para(tf_q, False,
                                         align=PP_ALIGN.CENTER,
                                         spc_before=Pt(0))
            _run(p, line, sz=Pt(20), bold=(j == 0), color=C_DARK)

        _quiz_footer(slide_q, story_title, accent)

        # ── 정답 슬라이드 ─────────────────────────────────────
        slide_a = prs.slides.add_slide(layout)
        slide_a.background.fill.solid()
        slide_a.background.fill.fore_color.rgb = lighten(accent, 0.92)

        _quiz_header(slide_a, f"Q{q_num}.  정답", darken(accent, 0.80))

        tf_a = tb(slide_a, body_x, body_y, body_w, body_h,
                  anchor=MSO_ANCHOR.MIDDLE)
        p_a = tf_a.paragraphs[0]
        p_a.alignment = PP_ALIGN.CENTER
        acpl = cpl(body_w / 360000, 22.0)
        alines = wrap(a_text, acpl)
        for j, line in enumerate(alines):
            p = p_a if j == 0 else _para(tf_a, False,
                                          align=PP_ALIGN.CENTER,
                                          spc_before=Pt(0))
            _run(p, line, sz=Pt(22), bold=True, color=darken(accent, 0.75))

        _quiz_footer(slide_a, story_title, accent)


# ──────────────────────────────────────────────────────────────
#  PPTX 빌드
# ──────────────────────────────────────────────────────────────

def build(ep_dir: Path, mode: str) -> bool:
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}"); return False

    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)

    meta           = story.get("meta", {})
    slides_data    = story.get("slides", [])
    quiz_questions = story.get("activity_sheet", {}).get("quiz_questions", [])

    # language: story.json 우선, 없으면 폴더명 suffix에서 감지
    _dir_lang = ep_dir.name.rsplit("_", 1)[-1]
    _known_langs = {"ko", "en", "pt", "id", "es", "ja"}
    lang = (meta.get("language")
            or (_dir_lang if _dir_lang in _known_langs else None)
            or "ko")
    palette    = meta.get("color_palette", {})
    if not isinstance(palette, dict):   # 구버전: 문자열 설명인 경우
        palette = {}
    accent     = hex_to_rgb(palette.get("primary",   "#4A90D9"))
    sub_accent = hex_to_rgb(palette.get("secondary", "#F9A94B"))

    images_dir = ep_dir / "images"

    def get_img(sd: dict) -> Path:
        n = sd.get("slide_number", 0)
        for fn in (f"slide_{n:02d}.png", f"slide_{n}.png"):
            p = images_dir / fn
            if p.exists(): return p
        return None

    # cover/story/ending 슬라이드만
    story_slides = [s for s in slides_data
                    if s.get("type") in ("cover", "story", "ending")]
    total = len(story_slides)

    modes = ["1", "2"] if mode == "both" else [mode]

    for m in modes:
        prs = Presentation()
        prs.slide_width  = SLIDE_W
        prs.slide_height = SLIDE_H

        # 폰트 임베드 (어떤 컴에서도 동일 렌더링)
        embed_fonts(prs)

        for idx, sd in enumerate(story_slides):
            stype    = sd.get("type")
            img_path = get_img(sd)
            page_num = idx + 1

            if stype == "cover":
                add_cover(prs, sd, img_path, meta, accent, lang=lang)
            elif m == "1":
                add_1col(prs, sd, img_path, meta,
                         page_num, total, accent, sub_accent, lang=lang)
            else:
                add_2col(prs, sd, img_path, meta,
                         page_num, total, accent, sub_accent, lang=lang)

        if quiz_questions:
            add_quiz(prs, quiz_questions, meta, accent, m)

        label    = "1분할" if m == "1" else "2분할"
        out_path = ep_dir / f"book_{label}.pptx"
        # 파일이 열려 있으면 _v2, _v3 ... 로 자동 우회
        candidate = out_path
        for ver in range(2, 20):
            try:
                prs.save(str(candidate))
                break
            except PermissionError:
                candidate = ep_dir / f"book_{label}_v{ver}.pptx"
        else:
            print(f"[ERROR] 저장 실패 (파일 잠김): {out_path}")
            continue
        print(f"[DONE] {candidate.name}  ({len(prs.slides)}페이지)")

        # 자동 축소: 임베드 PNG → JPEG 재압축 (업로드·다운로드 딜레이 감소)
        try:
            import shrink_assets
            old, new = shrink_assets.shrink_pptx(candidate)
            if new < old:
                print(f"[SHRINK] {candidate.name}: "
                      f"{old/1e6:.1f}MB → {new/1e6:.1f}MB")
        except Exception as e:
            print(f"[SHRINK] 축소 건너뜀(원본 그대로 사용): {e}")

    return True


# ──────────────────────────────────────────────────────────────
#  진입점
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="동화 PPTX 그림책 생성 (한국어)")
    parser.add_argument("--dir",  required=True,
                        help="에피소드 디렉토리 (예: output/bsl02)")
    parser.add_argument("--mode", choices=["1","2","both"], default="both",
                        help="1=1분할, 2=2분할, both=둘다 (기본값)")
    args = parser.parse_args()

    base   = os.path.dirname(os.path.abspath(__file__))
    ep_dir = Path(os.path.join(base, args.dir))

    if not ep_dir.exists():
        print(f"[ERROR] 디렉토리 없음: {ep_dir}"); sys.exit(1)

    story_path = ep_dir / "story.json"
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}"); sys.exit(1)

    with open(story_path, encoding="utf-8") as f:
        meta_chk = json.load(f).get("meta", {})

    _dir_sfx = ep_dir.name.rsplit("_", 1)[-1]
    _known   = {"ko","en","pt","id","es","ja"}
    _lang    = meta_chk.get("language") or (_dir_sfx if _dir_sfx in _known else "ko")
    print(f"[INFO] 에피소드  : {ep_dir.name}")
    print(f"[INFO] 제목      : {meta_chk.get('story_title','(없음)')}")
    print(f"[INFO] 언어      : {_lang}")
    print(f"[INFO] 모드      : {args.mode}")
    print()

    ok = build(ep_dir, args.mode)
    if ok:
        print()
        print(f"저장 위치: {ep_dir}")


if __name__ == "__main__":
    main()
