#!/usr/bin/env python3
"""
10_generate_thumbnail.py
========================
story.json의 thumbnail 데이터를 활용하여 YouTube 썸네일 이미지를 생성합니다.
- Thumbnail A (cover-based): 커버 이미지 + 하단 그라디언트 + 텍스트
- Thumbnail B (scene-based): 감정 장면 + 감정 컬러 그라디언트 + 텍스트

사용법:
  python 10_generate_thumbnail.py --ep 1
"""

import argparse
import json
import os
import re as _re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERROR] Pillow가 설치되어 있지 않습니다. pip install Pillow")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
THUMB_W, THUMB_H = 1280, 720

JUA_FONT_PATH = Path("assets/fonts/Jua-Regular.ttf")
JUA_DOWNLOAD_URL = "https://github.com/google/fonts/raw/main/ofl/jua/Jua-Regular.ttf"

FONT_FALLBACKS = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]

# Thumbnail B: emotion-dependent gradient bottom colors (dark, 80% opacity)
EMOTION_GRADIENT_COLORS = {
    "sad":       (0x1A, 0x4A, 0x7A),  # dark blue
    "angry":     (0x7A, 0x1A, 0x1A),  # dark red
    "surprised": (0x7A, 0x6A, 0x1A),  # dark amber
    "happy":     (0x7A, 0x1A, 0x5A),  # dark pink
    "worried":   (0x3A, 0x3A, 0x6A),  # dark purple
}

# Thumbnail B: emotion-dependent sub_text bright colors
EMOTION_SUBTEXT_COLORS = {
    "sad":       "#87CEEB",  # sky blue
    "angry":     "#FF9999",  # light red
    "happy":     "#FFB6C1",  # light pink
    "surprised": "#FFD700",  # gold
    "worried":   "#B0B0FF",  # light lavender
}

BADGE_COLOR = (0x7C, 0x5C, 0xBF, 255)  # #7C5CBF purple

# ---------------------------------------------------------------------------
# Hangul detection & thumbnail text sanitizer
# ---------------------------------------------------------------------------

_HANGUL = _re.compile(r'[\uAC00-\uD7A3]')


def _sanitize_thumbnail_text(thumbnail_data: dict, story: dict) -> dict:
    """비한국어 에피소드에서 한글 썸네일 텍스트를 자동 대체."""
    lang = story.get("meta", {}).get("language", "ko")
    if lang == "ko":
        return thumbnail_data  # 한국어는 그대로

    result = dict(thumbnail_data)

    # text 필드 점검
    text = result.get("text", "")
    if text and _HANGUL.search(text):
        fallback = story.get("meta", {}).get("story_title", text)[:30]
        print(f"  [THUMB] text 한글 감지 → story_title로 대체: {fallback!r}")
        result["text"] = fallback

    # sub_text 필드 점검
    sub = result.get("sub_text", "")
    if sub and _HANGUL.search(sub):
        # youtube_title 또는 unit_title 사용
        fallback_sub = (
            story.get("meta", {}).get("youtube_title")
            or story.get("meta", {}).get("unit_title")
            or story.get("meta", {}).get("story_title", "")
        )
        # 앞 50자만 사용
        fallback_sub = fallback_sub[:50]
        print(f"  [THUMB] sub_text 한글 감지 → youtube_title로 대체: {fallback_sub!r}")
        result["sub_text"] = fallback_sub

    return result


# ---------------------------------------------------------------------------
# Font setup — Jua (Google Font) with auto-download
# ---------------------------------------------------------------------------

def ensure_jua_font() -> Path | None:
    """Jua 폰트가 있으면 경로를 반환, 없으면 다운로드를 시도합니다."""
    if JUA_FONT_PATH.exists():
        print(f"[INFO] Jua 폰트 확인됨: {JUA_FONT_PATH}")
        return JUA_FONT_PATH

    print(f"[INFO] Jua 폰트가 없습니다. 다운로드를 시도합니다...")
    try:
        import requests
        JUA_FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(JUA_DOWNLOAD_URL, timeout=30)
        resp.raise_for_status()
        JUA_FONT_PATH.write_bytes(resp.content)
        print(f"[INFO] Jua 폰트 다운로드 완료: {JUA_FONT_PATH}")
        return JUA_FONT_PATH
    except Exception as e:
        print(f"[WARN] Jua 폰트 다운로드 실패: {e}")
        return None


def _resolve_font_path() -> str | None:
    """사용 가능한 폰트 경로를 결정합니다 (Jua 우선, 폴백 순회)."""
    jua = ensure_jua_font()
    if jua is not None:
        return str(jua)
    for fb in FONT_FALLBACKS:
        if Path(fb).exists():
            print(f"[INFO] 폴백 폰트 사용: {fb}")
            return fb
    return None


# Module-level resolved font path (set in main before use)
_FONT_PATH: str | None = None


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """결정된 폰트 경로에서 지정 크기로 폰트를 로드합니다."""
    if _FONT_PATH is not None:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    print("[WARN] 시스템 폰트를 찾을 수 없어 기본 폰트를 사용합니다.")
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_story(ep_num: int = None, ep_dir: Path = None) -> dict:
    if ep_dir is not None:
        story_path = ep_dir / "story.json"
    else:
        story_path = Path(f"output/ep{ep_num:02d}/story.json")
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}")
        sys.exit(1)
    with open(story_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_image_safe(path: Path, fallback_color: str = "#2C2C2C") -> Image.Image:
    """이미지를 로드하거나, 실패 시 단색 배경을 반환합니다."""
    if path.exists():
        try:
            img = Image.open(path).convert("RGBA")
            return img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        except Exception as e:
            print(f"[WARN] 이미지 로드 실패 ({path}): {e}")
    else:
        print(f"[WARN] 이미지 없음: {path} — 단색 배경으로 대체합니다.")
    return Image.new("RGBA", (THUMB_W, THUMB_H), fallback_color)


def draw_text_with_stroke(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    stroke_width: int = 4,
    stroke_fill: str = "black",
    anchor: str | None = None,
):
    """stroke_width 파라미터를 우선 시도하고, 실패 시 8방향 오프셋으로 폴백합니다."""
    kwargs: dict = {"font": font, "fill": fill}
    if anchor:
        kwargs["anchor"] = anchor

    # Try Pillow 10.0+ stroke_width parameter
    try:
        draw.text(
            xy, text,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            **kwargs,
        )
        return
    except TypeError:
        pass

    # Fallback: 8-direction offset rendering
    x, y = xy
    sw = stroke_width
    stroke_kwargs: dict = {"font": font, "fill": stroke_fill}
    if anchor:
        stroke_kwargs["anchor"] = anchor

    for dx in [-sw, 0, sw]:
        for dy in [-sw, 0, sw]:
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, **stroke_kwargs)
    draw.text(xy, text, **kwargs)


def get_text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    """텍스트의 (width, height)를 반환합니다."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def create_bottom_gradient(
    width: int,
    height: int,
    gradient_height: int,
    color_rgb: tuple[int, int, int],
    target_alpha: int,
) -> Image.Image:
    """하단에서 위로 올라갈수록 투명해지는 그라디언트 RGBA 이미지를 생성합니다.

    numpy가 있으면 빠른 배열 연산을, 없으면 line-by-line 드로잉을 사용합니다.
    """
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    start_y = height - gradient_height
    r, g, b = color_rgb

    try:
        import numpy as np
        arr = np.zeros((height, width, 4), dtype=np.uint8)
        for y_off in range(gradient_height):
            alpha = int((y_off / gradient_height) * target_alpha)
            arr[start_y + y_off, :, 0] = r
            arr[start_y + y_off, :, 1] = g
            arr[start_y + y_off, :, 2] = b
            arr[start_y + y_off, :, 3] = alpha
        gradient = Image.fromarray(arr, "RGBA")
    except ImportError:
        draw = ImageDraw.Draw(gradient)
        for y_off in range(gradient_height):
            alpha = int((y_off / gradient_height) * target_alpha)
            draw.line(
                [(0, start_y + y_off), (width - 1, start_y + y_off)],
                fill=(r, g, b, alpha),
            )

    return gradient


def draw_badge(
    bg: Image.Image,
    unit: str,
    badge_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> Image.Image:
    """좌측 하단에 '국어 {unit}' 배지를 그립니다."""
    if not unit:
        return bg

    badge_text = f"국어 {unit}"
    tmp_draw = ImageDraw.Draw(bg)
    badge_tw, badge_th = get_text_bbox(tmp_draw, badge_text, badge_font)
    badge_pad_x, badge_pad_y = 16, 8
    badge_w = badge_tw + badge_pad_x * 2
    badge_h = badge_th + badge_pad_y * 2
    badge_x = 30
    badge_y = THUMB_H - 50

    # Draw rounded rectangle background on separate layer
    badge_layer = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_layer)
    badge_draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=12,
        fill=BADGE_COLOR,
    )
    bg = Image.alpha_composite(bg, badge_layer)

    # Badge text
    draw = ImageDraw.Draw(bg)
    text_x = badge_x + badge_pad_x
    text_y = badge_y + badge_pad_y
    draw.text((text_x, text_y), badge_text, font=badge_font, fill="white")

    return bg


def paste_logo(bg: Image.Image) -> Image.Image:
    """assets/logo.png가 있으면 우측 상단에 60x60으로 붙입니다."""
    logo_path = Path("assets/logo.png")
    if not logo_path.exists():
        return bg
    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo = logo.resize((60, 60), Image.LANCZOS)
        # Top-right: 1280 - 60 - 20 = 1200
        bg.paste(logo, (THUMB_W - 60 - 20, 20), logo)
    except Exception as e:
        print(f"[WARN] 로고 로드 실패: {e}")
    return bg


# ---------------------------------------------------------------------------
# Book Cover Style Thumbnails
# ---------------------------------------------------------------------------

def make_book_cover(
    ep_dir: Path,
    story: dict,
    thumb_data: dict,
    font_path: str | None,
) -> tuple[Path, Path]:
    """책 표지 스타일 썸네일 A/B를 생성합니다.

    - 배경: 진한 포레스트 그린(A) / 딥 네이비(B)
    - 중앙에 슬라이드 이미지 (1400x700, 흰색+금색 프레임)
    - 상단/하단 금색 바 + 제목/서브타이틀 텍스트
    - 코너 장식
    """
    BOOK_W, BOOK_H = THUMB_W, THUMB_H  # 1280x720

    bg_colors = {
        "a": (0x1B, 0x43, 0x32, 255),   # forest green
        "b": (0x1A, 0x1A, 0x3E, 255),   # deep navy
    }
    GOLD = (0xC9, 0xA8, 0x4C, 255)
    GOLD_HEX = "#C9A84C"
    WHITE = (255, 255, 255, 255)
    BAR_H = 80
    SCENE_W, SCENE_H = 1140, 570   # inner scene area
    WHITE_BORDER = 10
    GOLD_BORDER = 20

    slide_num = thumb_data.get("slide_number", 5)
    scene_path = ep_dir / "images" / f"slide_{slide_num:02d}.png"

    # Load scene image
    if scene_path.exists():
        try:
            scene_img = Image.open(scene_path).convert("RGBA")
            scene_img = scene_img.resize((SCENE_W, SCENE_H), Image.LANCZOS)
        except Exception:
            scene_img = Image.new("RGBA", (SCENE_W, SCENE_H), "#2C2C2C")
    else:
        scene_img = Image.new("RGBA", (SCENE_W, SCENE_H), "#2C2C2C")

    meta = story.get("meta", {})
    story_title = meta.get("story_title", thumb_data.get("text", "Story"))
    sub_text_raw = thumb_data.get("sub_text", "") or thumb_data.get("text_overlay_b", "")

    out_paths = []

    for variant, bg_color in bg_colors.items():
        # --- Canvas ---
        canvas = Image.new("RGBA", (BOOK_W, BOOK_H), bg_color)
        draw = ImageDraw.Draw(canvas)

        # --- Top gold bar ---
        draw.rectangle([0, 0, BOOK_W, BAR_H], fill=GOLD)

        # --- Bottom gold bar ---
        draw.rectangle([0, BOOK_H - BAR_H, BOOK_W, BOOK_H], fill=GOLD)

        # --- Center: frame then scene ---
        # Frame total: SCENE_W + 2*(WHITE_BORDER + GOLD_BORDER)
        frame_w = SCENE_W + 2 * (WHITE_BORDER + GOLD_BORDER)
        frame_h = SCENE_H + 2 * (WHITE_BORDER + GOLD_BORDER)
        frame_x = (BOOK_W - frame_w) // 2
        frame_y = (BOOK_H - frame_h) // 2

        # Outer gold border
        draw.rectangle(
            [frame_x, frame_y, frame_x + frame_w, frame_y + frame_h],
            fill=GOLD,
        )
        # Inner white border
        inner_x = frame_x + GOLD_BORDER
        inner_y = frame_y + GOLD_BORDER
        inner_w = frame_w - 2 * GOLD_BORDER
        inner_h = frame_h - 2 * GOLD_BORDER
        draw.rectangle(
            [inner_x, inner_y, inner_x + inner_w, inner_y + inner_h],
            fill=WHITE,
        )
        # Paste scene image
        scene_x = inner_x + WHITE_BORDER
        scene_y = inner_y + WHITE_BORDER
        canvas.paste(scene_img, (scene_x, scene_y))

        # --- Corner ornaments on bars ---
        orn_r = 20
        for cx_o, cy_o in [(30, BAR_H // 2), (BOOK_W - 30, BAR_H // 2),
                            (30, BOOK_H - BAR_H // 2), (BOOK_W - 30, BOOK_H - BAR_H // 2)]:
            draw.ellipse(
                [cx_o - orn_r, cy_o - orn_r, cx_o + orn_r, cy_o + orn_r],
                fill=(255, 255, 255, 200),
                outline=(255, 255, 255, 255),
                width=2,
            )
        # Small inner circles
        orn_r2 = 10
        for cx_o, cy_o in [(30, BAR_H // 2), (BOOK_W - 30, BAR_H // 2),
                            (30, BOOK_H - BAR_H // 2), (BOOK_W - 30, BOOK_H - BAR_H // 2)]:
            draw.ellipse(
                [cx_o - orn_r2, cy_o - orn_r2, cx_o + orn_r2, cy_o + orn_r2],
                fill=GOLD,
            )

        # --- Text: title in top bar ---
        title_font = load_font(54)
        title_text = story_title

        # Fit title into top bar width (max ~1100px)
        title_w, title_h = get_text_bbox(draw, title_text, title_font)
        while title_w > BOOK_W - 200 and title_font.size > 28:
            title_font = load_font(title_font.size - 4)
            title_w, title_h = get_text_bbox(draw, title_text, title_font)

        title_x = (BOOK_W - title_w) // 2
        title_y = (BAR_H - title_h) // 2

        draw.text((title_x, title_y), title_text, font=title_font, fill="white")

        # --- Sub text: in bottom bar (slightly different between A/B) ---
        sub_font = load_font(32)
        if variant == "b" and meta.get("grade"):
            sub_text = f"Grade {meta['grade']} · {sub_text_raw}" if sub_text_raw else sub_text_raw
        else:
            sub_text = sub_text_raw

        if sub_text:
            sub_w, sub_h = get_text_bbox(draw, sub_text, sub_font)
            sub_x = (BOOK_W - sub_w) // 2
            sub_y = BOOK_H - BAR_H + (BAR_H - sub_h) // 2
            draw.text((sub_x, sub_y), sub_text, font=sub_font, fill="#FFD700")

        # --- Channel logo ---
        canvas = paste_logo(canvas)

        # Save
        out_name = f"thumbnail_{variant}.png"
        out_path = ep_dir / out_name
        canvas.convert("RGB").save(out_path, "PNG")
        out_paths.append(out_path)
        print(f"  [Book Cover {variant.upper()}] 생성 완료 -> {out_path}")

    return tuple(out_paths)


# ---------------------------------------------------------------------------
# Thumbnail A — cover-based (slide_00 + bottom gradient + text)
# ---------------------------------------------------------------------------

def generate_thumbnail_a(
    ep_dir: Path,
    thumbnail_data: dict,
    meta: dict,
) -> Path:
    """커버 이미지(slide_00) 위에 하단 그라디언트 + 텍스트를 그립니다."""
    # Background: cover image (slide_00), full 1280x720
    cover_path = ep_dir / "images" / "slide_00.png"
    bg = load_image_safe(cover_path)

    # Gradient: large overlay from bottom covering center area for text contrast
    gradient = create_bottom_gradient(
        width=THUMB_W,
        height=THUMB_H,
        gradient_height=460,
        color_rgb=(0, 0, 0),
        target_alpha=int(255 * 0.65),
    )
    bg = Image.alpha_composite(bg, gradient)

    draw = ImageDraw.Draw(bg)

    # Fonts (all Jua)
    main_font = load_font(96)
    sub_font = load_font(32)
    badge_font = load_font(20)

    # Text data
    main_text = thumbnail_data.get("text", "동화 이야기")
    sub_text = thumbnail_data.get("sub_text", "")

    # Main text — centered both horizontally and vertically
    main_w, main_h = get_text_bbox(draw, main_text, main_font)
    while main_w > THUMB_W - 80 and main_font.size > 48:
        main_font = load_font(main_font.size - 6)
        main_w, main_h = get_text_bbox(draw, main_text, main_font)
    main_x = (THUMB_W - main_w) // 2
    main_y = (THUMB_H - main_h) // 2

    draw_text_with_stroke(
        draw, (main_x, main_y), main_text, main_font,
        fill="white", stroke_width=5, stroke_fill="black",
    )

    # Sub text — just below main text, yellow #FFD700, stroke 2px
    if sub_text:
        sub_w, sub_h = get_text_bbox(draw, sub_text, sub_font)
        sub_x = (THUMB_W - sub_w) // 2
        sub_y = main_y + main_h + 20

        draw_text_with_stroke(
            draw, (sub_x, sub_y), sub_text, sub_font,
            fill="#FFD700", stroke_width=2, stroke_fill="black",
        )

    # Channel logo — top-right (60x60)
    bg = paste_logo(bg)

    # Unit badge — left-bottom
    unit = meta.get("unit", "")
    bg = draw_badge(bg, unit, badge_font)

    # Save
    out_path = ep_dir / "thumbnail_a.png"
    bg.convert("RGB").save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Thumbnail B — scene-based (emotion slide + emotion gradient + text)
# ---------------------------------------------------------------------------

def generate_thumbnail_b(
    ep_dir: Path,
    thumbnail_data: dict,
    meta: dict,
) -> Path:
    """감정 장면 이미지 위에 감정 컬러 그라디언트 + 텍스트를 그립니다."""
    # Background: the specified emotional scene slide, full 1280x720
    slide_num = thumbnail_data.get("slide_number", 5)
    scene_path = ep_dir / "images" / f"slide_{slide_num:02d}.png"
    bg = load_image_safe(scene_path)

    # Emotion data
    emotion = thumbnail_data.get("emotion", "happy")
    gradient_rgb = EMOTION_GRADIENT_COLORS.get(emotion, (0x7A, 0x1A, 0x5A))
    sub_text_color = EMOTION_SUBTEXT_COLORS.get(emotion, "#FFB6C1")

    # Bottom gradient strip: 260px height, transparent top -> emotion color at 80%
    gradient = create_bottom_gradient(
        width=THUMB_W,
        height=THUMB_H,
        gradient_height=260,
        color_rgb=gradient_rgb,
        target_alpha=int(255 * 0.80),  # 80%
    )
    bg = Image.alpha_composite(bg, gradient)

    draw = ImageDraw.Draw(bg)

    # Fonts (all Jua) — note: 80px main, bigger than thumbnail_a
    main_font = load_font(80)
    sub_font = load_font(30)
    badge_font = load_font(20)

    # Text data
    main_text = thumbnail_data.get("text", "동화 이야기")
    sub_text = thumbnail_data.get("sub_text", "")

    # Main text — centered, y = 720 - 150, white, stroke 5px
    main_w, _ = get_text_bbox(draw, main_text, main_font)
    main_x = (THUMB_W - main_w) // 2
    main_y = THUMB_H - 150

    draw_text_with_stroke(
        draw, (main_x, main_y), main_text, main_font,
        fill="white", stroke_width=5, stroke_fill="black",
    )

    # Sub text — centered, y = main_y + 80, emotion-dependent bright color, stroke 2px
    if sub_text:
        sub_w, _ = get_text_bbox(draw, sub_text, sub_font)
        sub_x = (THUMB_W - sub_w) // 2
        sub_y = main_y + 80

        draw_text_with_stroke(
            draw, (sub_x, sub_y), sub_text, sub_font,
            fill=sub_text_color, stroke_width=2, stroke_fill="black",
        )

    # Channel logo — top-right (60x60)
    bg = paste_logo(bg)

    # Unit badge — left-bottom
    unit = meta.get("unit", "")
    bg = draw_badge(bg, unit, badge_font)

    # Save
    out_path = ep_dir / "thumbnail_b.png"
    bg.convert("RGB").save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Thumbnail C — Gemini close-up background (thumbnail_c_bg.png) + text only
# ---------------------------------------------------------------------------

def _wrap_text_to_width(draw, text, font, max_w):
    """공백 기준 줄바꿈 (한국어는 어절 단위). 반환: 줄 리스트."""
    words = text.split()
    if not words:
        return [text]
    lines = []
    cur = words[0]
    for w in words[1:]:
        trial = cur + " " + w
        tw, _ = get_text_bbox(draw, trial, font)
        if tw <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def generate_thumbnail_c(ep_dir: Path, thumbnail_data: dict, meta: dict) -> Path:
    """thumbnail_c_bg.png(Gemini 클로즈업 배경) 위에 thumbnail.text 만 우측에 배치.

    - 배경: {ep_dir}/thumbnail_c_bg.png (10b_batch_thumb_bg.py 로 미리 생성).
      없으면 감정 장면 슬라이드로 폴백.
    - 텍스트: thumbnail.text 1개만, Jua ~110px, 흰색 + 검정 스트로크, 우측 공간.
    - sub_text 는 그리지 않음.
    - 출력: thumbnail_c.png
    """
    bg_path = ep_dir / "thumbnail_c_bg.png"
    if bg_path.exists():
        bg = load_image_safe(bg_path)
    else:
        # 폴백: 감정 장면 슬라이드
        slide_num = thumbnail_data.get("slide_number", 5)
        scene_path = ep_dir / "images" / f"slide_{slide_num:02d}.png"
        print(f"[WARN] thumbnail_c_bg.png 없음 → 폴백 배경 사용: {scene_path.name}")
        bg = load_image_safe(scene_path)

    # 우측 텍스트 공간에 살짝 어두운 그라디언트 (가독성)
    right_shade = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(right_shade)
    x_start = int(THUMB_W * 0.52)
    for x in range(x_start, THUMB_W):
        # 왼→오 갈수록 진해지는 세로 그라디언트
        a = int(((x - x_start) / (THUMB_W - x_start)) * 130)
        shade_draw.line([(x, 0), (x, THUMB_H)], fill=(0, 0, 0, a))
    bg = Image.alpha_composite(bg, right_shade)

    draw = ImageDraw.Draw(bg)

    main_text = thumbnail_data.get("text", "동화 이야기")

    # 우측 영역 (전체 폭의 우측 ~45%)
    region_x = int(THUMB_W * 0.55)
    region_w = THUMB_W - region_x - 50  # 우측 여백 50px

    # 폰트 크기 자동 축소 + 줄바꿈
    font_size = 110
    while font_size >= 60:
        font = load_font(font_size)
        lines = _wrap_text_to_width(draw, main_text, font, region_w)
        # 최대 3줄, 총 높이가 화면 안에 들어오는지
        _, lh = get_text_bbox(draw, "가", font)
        line_gap = int(lh * 0.35)
        total_h = len(lines) * lh + (len(lines) - 1) * line_gap
        if len(lines) <= 3 and total_h <= THUMB_H - 120:
            break
        font_size -= 8
    else:
        font = load_font(60)
        lines = _wrap_text_to_width(draw, main_text, font, region_w)
        _, lh = get_text_bbox(draw, "가", font)
        line_gap = int(lh * 0.35)
        total_h = len(lines) * lh + (len(lines) - 1) * line_gap

    # 세로 중앙 정렬, 우측 영역 중앙에 배치
    y = (THUMB_H - total_h) // 2
    region_cx = region_x + region_w // 2
    for ln in lines:
        lw, _ = get_text_bbox(draw, ln, font)
        x = region_cx - lw // 2
        draw_text_with_stroke(
            draw, (x, y), ln, font,
            fill="white", stroke_width=6, stroke_fill="black",
        )
        y += lh + line_gap

    bg = paste_logo(bg)

    out_path = ep_dir / "thumbnail_c.png"
    bg.convert("RGB").save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _FONT_PATH

    parser = argparse.ArgumentParser(description="YouTube 썸네일 생성 (A/B 테스트용)")
    parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (기본: 1)")
    parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
    parser.add_argument("--style", type=str, default="default", choices=["default", "book", "c"],
                        help="썸네일 스타일: default (A/B) / book (책 표지) / c (Gemini 클로즈업 배경 + 텍스트)")
    args = parser.parse_args()

    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")

    # Resolve font (Jua with auto-download, then fallbacks)
    _FONT_PATH = _resolve_font_path()
    if _FONT_PATH:
        print(f"[INFO] 사용 폰트: {_FONT_PATH}")
    else:
        print("[WARN] 사용 가능한 폰트를 찾지 못했습니다. 기본 폰트를 사용합니다.")

    story = load_story(ep_dir=ep_dir)
    meta = story.get("meta", {})

    # Thumbnail data (with graceful defaults from meta)
    thumbnail_data = story.get("thumbnail", {})
    if not thumbnail_data:
        print("[WARN] story.json에 thumbnail 데이터가 없습니다. 기본값을 사용합니다.")
        thumbnail_data = {
            "text": meta.get("story_title", "동화 이야기")[:5],
            "slide_number": 5,
            "emotion": "happy",
            "sub_text": f"{meta.get('grade', 2)}학년 국어 {meta.get('unit', '01')}단원",
        }

    # 비한국어 에피소드에서 한글 텍스트 자동 대체 (A/B/book cover 모두 커버)
    thumbnail_data = _sanitize_thumbnail_text(thumbnail_data, story)

    print()
    print(f"썸네일 생성 -- [{ep_dir}]")
    print(f"{'=' * 50}")
    print(f"  스타일: {args.style}")
    print(f"  제목: {meta.get('story_title', '')}")
    print(f"  감정: {thumbnail_data.get('emotion', 'N/A')}")
    print(f"  메인 텍스트: {thumbnail_data.get('text', thumbnail_data.get('text_overlay_a', 'N/A'))}")
    print(f"  서브 텍스트: {thumbnail_data.get('sub_text', thumbnail_data.get('text_overlay_b', 'N/A'))}")
    print(f"  장면 슬라이드: #{thumbnail_data.get('slide_number', 'N/A')}")
    print()

    # Detect style: use --style arg, or fall back to story.json thumbnail.style field
    effective_style = args.style
    if effective_style == "default" and thumbnail_data.get("style") == "book":
        effective_style = "book"

    if effective_style == "c":
        # Style C: Gemini 클로즈업 배경 + 텍스트만 (sub_text 미표시)
        path_c = generate_thumbnail_c(ep_dir, thumbnail_data, meta)
        print(f"  [C] 생성 완료 -> {path_c}")
        print()
        print("썸네일 C 생성 완료!")
        print(f"  C: {path_c}")
        return
    elif effective_style == "book":
        # Generate Book Cover Thumbnails A and B
        path_a, path_b = make_book_cover(ep_dir, story, thumbnail_data, _FONT_PATH)
    else:
        # Generate Thumbnail A (cover-based)
        path_a = generate_thumbnail_a(ep_dir, thumbnail_data, meta)
        print(f"  [A] 생성 완료 -> {path_a}")

        # Generate Thumbnail B (scene-based)
        path_b = generate_thumbnail_b(ep_dir, thumbnail_data, meta)
        print(f"  [B] 생성 완료 -> {path_b}")

    print()
    print(f"썸네일 2장 생성 완료!")
    print(f"  A: {path_a}")
    print(f"  B: {path_b}")


if __name__ == "__main__":
    main()
