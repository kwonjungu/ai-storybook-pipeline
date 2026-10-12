#!/usr/bin/env python3
"""
07b_generate_quiz_slides.py
===========================
story.json의 퀴즈 데이터와 장면 이미지를 활용하여
퀴즈 PNG 슬라이드를 생성합니다 (Pillow 기반).

생성 파일 (~8장):
  quiz_intro.png   - 퀴즈 인트로
  quiz_q1~q3.png   - 문제 슬라이드
  quiz_think.png   - 생각 시간
  quiz_a1~a3.png   - 정답 슬라이드

사용법:
  python 07b_generate_quiz_slides.py --ep 1
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1920, 1080

COLOR_BG_DARK = "#2C3E50"

# Per-language label dictionaries
LABELS = {
    "ko": {
        "badge": ["첫 번째 문제!", "두 번째 문제!", "세 번째 문제!"],
        "quiz_intro_title": "퀴즈 타임!",
        "quiz_intro_sub": "재미있는 퀴즈를 풀어볼까요?",
        "think": "생각해 보세요!",
        "correct": "정답!",
        "answer_footer": "{n}번 문제의 정답",
        "wrap_chars": 13,
    },
    "en": {
        "badge": ["Question 1!", "Question 2!", "Question 3!"],
        "quiz_intro_title": "Quiz Time!",
        "quiz_intro_sub": "Let's solve some fun quizzes!",
        "think": "Think about it!",
        "correct": "Correct!",
        "answer_footer": "Answer to Question {n}",
        "wrap_chars": 22,
    },
    "pt": {
        "badge": ["Pergunta 1!", "Pergunta 2!", "Pergunta 3!"],
        "quiz_intro_title": "Hora do Quiz!",
        "quiz_intro_sub": "Vamos resolver alguns quizzes divertidos!",
        "think": "Pense bem!",
        "correct": "Correto!",
        "answer_footer": "Resposta da Pergunta {n}",
        "wrap_chars": 22,
    },
    "ja": {
        "badge": ["第1問!", "第2問!", "第3問!"],
        "quiz_intro_title": "クイズタイム!",
        "quiz_intro_sub": "楽しいクイズを解いてみよう！",
        "think": "考えてみよう！",
        "correct": "正解!",
        "answer_footer": "第{n}問の正解",
        "wrap_chars": 13,
    },
    "id": {
        "badge": ["Soal 1!", "Soal 2!", "Soal 3!"],
        "quiz_intro_title": "Waktu Kuis!",
        "quiz_intro_sub": "Ayo selesaikan kuis yang menyenangkan!",
        "think": "Pikir dulu!",
        "correct": "Benar!",
        "answer_footer": "Jawaban Soal {n}",
        "wrap_chars": 22,
    },
    "es": {
        "badge": ["¡Pregunta 1!", "¡Pregunta 2!", "¡Pregunta 3!"],
        "quiz_intro_title": "¡Hora del quiz!",
        "quiz_intro_sub": "¡Resolvamos unas preguntas divertidas!",
        "think": "¡Piensa bien!",
        "correct": "¡Correcto!",
        "answer_footer": "Respuesta de la Pregunta {n}",
        "wrap_chars": 22,
    },
}

# Legacy constants (kept for compatibility)
BADGE_LABELS = LABELS["ko"]["badge"]
BADGE_LABELS_EN = LABELS["en"]["badge"]


def get_lang(story) -> str:
    """Return language code from story meta, defaulting to 'ko'."""
    if not story:
        return "ko"
    return story.get("meta", {}).get("language", "ko")


def get_labels(story) -> dict:
    """Return label dict for the story's language (falls back to English for unknown)."""
    lang = get_lang(story)
    return LABELS.get(lang, LABELS["en"])

# ---------------------------------------------------------------------------
# Font: Jua (Google Font) with malgun.ttf fallback
# ---------------------------------------------------------------------------
JUA_FONT_DIR = Path("assets/fonts")
JUA_FONT_PATH = JUA_FONT_DIR / "Jua-Regular.ttf"
JUA_DOWNLOAD_URL = "https://github.com/google/fonts/raw/main/ofl/jua/Jua-Regular.ttf"

FALLBACK_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/NanumGothicBold.ttf",
    "C:/Windows/Fonts/NanumGothic.ttf",
]

_resolved_font_path: str | None = None
_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _ensure_jua_font() -> None:
    """Download Jua-Regular.ttf if it does not exist."""
    if JUA_FONT_PATH.exists():
        print(f"  [Font] Jua 폰트 확인됨: {JUA_FONT_PATH}")
        return
    print(f"  [Font] Jua 폰트 다운로드 중... ({JUA_DOWNLOAD_URL})")
    try:
        import requests
        resp = requests.get(JUA_DOWNLOAD_URL, timeout=30)
        resp.raise_for_status()
        JUA_FONT_DIR.mkdir(parents=True, exist_ok=True)
        JUA_FONT_PATH.write_bytes(resp.content)
        print(f"  [Font] 다운로드 완료: {JUA_FONT_PATH}")
    except Exception as e:
        print(f"  [Font] Jua 다운로드 실패 ({e}), fallback 폰트 사용")


def _find_font_path() -> str | None:
    """Return the best available font path: Jua first, then fallback."""
    global _resolved_font_path
    if _resolved_font_path is not None:
        return _resolved_font_path if _resolved_font_path else None

    if JUA_FONT_PATH.exists():
        _resolved_font_path = str(JUA_FONT_PATH)
        return _resolved_font_path

    for p in FALLBACK_FONT_CANDIDATES:
        if Path(p).exists():
            _resolved_font_path = p
            print(f"  [Font] Fallback 폰트 사용: {p}")
            return p

    _resolved_font_path = ""
    return None


_USE_LATIN_FONT = False  # main()에서 story 언어로 결정 (es·pt 등은 Jua에 악센트가 없음)


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    fp = _find_font_path()
    if _USE_LATIN_FONT:
        from latin_font import latin_font
        font = latin_font(size)
    elif fp:
        font = ImageFont.truetype(fp, size)
    else:
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hex_to_rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    r, g, b = hex_to_rgb(h)
    return (r, g, b, a)


def load_bg(path: Path, fallback_color: str = COLOR_BG_DARK) -> Image.Image:
    """Load an image resized to fill 1920x1080. Solid color fallback if missing."""
    if path.exists():
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
            return img
        except Exception:
            pass
    return Image.new("RGBA", (WIDTH, HEIGHT), hex_to_rgba(fallback_color))


def apply_overlay(canvas: Image.Image, color_hex: str, alpha: float) -> Image.Image:
    """Apply a color overlay with given opacity (0.0-1.0) on top of canvas."""
    a = int(alpha * 255)
    r, g, b = hex_to_rgb(color_hex)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (r, g, b, a))
    return Image.alpha_composite(canvas, overlay)


def draw_stroked_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                      font, fill, stroke_width: int = 3,
                      stroke_fill: str = "black", anchor=None):
    """Draw text with stroke outline. Falls back to 8-direction offset for old Pillow."""
    x, y = xy
    try:
        draw.text((x, y), text, font=font, fill=fill,
                  stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)
    except TypeError:
        # Old Pillow fallback: draw in 8 directions
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill, anchor=anchor)
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def get_text_size(font, text: str) -> tuple[int, int]:
    """Return (width, height) of text rendered with given font."""
    bbox = font.getbbox(text)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def is_korean_text(text: str) -> bool:
    """Return True if text contains Hangul characters."""
    return any('\uAC00' <= c <= '\uD7A3' or '\u1100' <= c <= '\u11FF' for c in text)


def is_english_text(text: str) -> bool:
    """Return True if text is non-Korean (Latin, accented, etc.) — use word-wrap."""
    return not is_korean_text(text)


def wrap_text(text: str, max_chars: int = 22, max_lines: int = 3) -> list[str]:
    """Word-wrap text by space boundaries with default max_chars=22 (suits English)."""
    return wrap_korean(text, max_chars=max_chars, max_lines=max_lines)


def wrap_korean(text: str, max_chars: int = 13, max_lines: int = 3) -> list[str]:
    """어절(공백) 단위로 한국어 텍스트를 줄바꿈합니다.

    max_lines 초과분을 마지막 줄에 억지로 합치지 않습니다(가독성 저하 방지).
    초과 시에는 실제 필요한 줄 수를 그대로 반환하며, 호출부(fit_font_for_lines)에서
    폰트 크기를 줄여 max_lines 내에 수용하도록 합니다."""
    text = text.strip()
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (current + " " + word).strip() if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines if lines else [text]


def fit_font_for_lines(text: str, base_size: int, wrap_chars: int,
                       max_lines: int = 3, min_size: int = 48):
    """텍스트가 max_lines 안에 들어가도록 폰트 크기를 자동 축소합니다.

    반환: (font, lines). base_size부터 시작해 줄 수가 max_lines 이하가 될 때까지
    폰트를 줄이고, wrap_chars도 폰트 축소 비율에 맞춰 늘려 한 줄 수용량을 키웁니다.
    min_size에서도 초과하면 그 크기로 줄바꿈한 결과를 그대로 사용."""
    is_en = is_english_text(text)

    def _wrap(chars):
        if is_en:
            return wrap_text(text, max_chars=chars, max_lines=max_lines)
        return wrap_korean(text, max_chars=chars, max_lines=max_lines)

    size = base_size
    lines = _wrap(wrap_chars)
    while len(lines) > max_lines and size > min_size:
        size = max(min_size, size - 6)
        # 폰트가 작아진 만큼 한 줄에 더 많은 글자 수용 (base_size 대비 비례)
        chars = max(wrap_chars, int(wrap_chars * base_size / size))
        lines = _wrap(chars)
    return get_font(size), lines


def draw_rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple, radius: int,
                      fill=None, outline=None, width: int = 1):
    """Draw a rounded rectangle, compatible with older Pillow versions."""
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    except AttributeError:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)


# ---------------------------------------------------------------------------
# Slide generators
# ---------------------------------------------------------------------------
def make_quiz_intro(ep_dir: Path, story: dict | None = None) -> Image.Image:
    """quiz_intro.png -- cover image background with quiz title overlay."""
    bg_path = ep_dir / "images" / "slide_00.png"
    canvas = load_bg(bg_path, COLOR_BG_DARK)

    # Language labels
    lbl = get_labels(story)

    # Black overlay 40%
    canvas = apply_overlay(canvas, "#000000", 0.40)

    draw = ImageDraw.Draw(canvas)

    # Title
    title_font = get_font(130)
    title = lbl["quiz_intro_title"]
    tw, th = get_text_size(title_font, title)
    tx = (WIDTH - tw) // 2
    ty = (HEIGHT // 2) - th - 30

    draw_stroked_text(draw, (tx, ty), title, title_font,
                      fill="#FFD700", stroke_width=7, stroke_fill="black")

    # Sub
    sub_font = get_font(60)
    sub = lbl["quiz_intro_sub"]
    sw, sh = get_text_size(sub_font, sub)
    sx = (WIDTH - sw) // 2
    sy = ty + th + 30

    draw_stroked_text(draw, (sx, sy), sub, sub_font,
                      fill="white", stroke_width=2, stroke_fill="black")

    return canvas


def make_quiz_question(ep_dir: Path, q_index: int, question: dict, story: dict | None = None) -> Image.Image:
    """quiz_q{n}.png -- full-screen scene image with question overlay."""
    related_slide = question.get("related_slide", q_index + 1)
    scene_path = ep_dir / "images" / f"slide_{related_slide:02d}.png"
    canvas = load_bg(scene_path, "#1A1A2E")

    # Language labels
    lbl = get_labels(story)
    lang_badge = lbl["badge"]

    # Black overlay 50%
    canvas = apply_overlay(canvas, "#000000", 0.50)

    draw = ImageDraw.Draw(canvas)

    # --- Badge at top center ---
    badge_font = get_font(68)
    badge_text = lang_badge[q_index] if q_index < len(lang_badge) else lbl["badge"][0]
    btw, bth = get_text_size(badge_font, badge_text)
    badge_pad_x, badge_pad_y = 50, 22
    badge_w = btw + badge_pad_x * 2
    badge_h = bth + badge_pad_y * 2
    badge_x = (WIDTH - badge_w) // 2
    badge_y = 60

    draw_rounded_rect(draw,
                      (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                      radius=badge_h // 2, fill="#7C5CBF")
    draw_stroked_text(draw, (badge_x + badge_pad_x, badge_y + badge_pad_y),
                      badge_text, badge_font, fill="white",
                      stroke_width=2, stroke_fill="#4A3580")

    # --- Big "?" center ---
    q_icon_font = get_font(180)
    qiw, qih = get_text_size(q_icon_font, "?")
    qix = (WIDTH - qiw) // 2
    qiy = badge_y + badge_h + 30

    draw_stroked_text(draw, (qix, qiy), "?", q_icon_font,
                      fill="#FFD700", stroke_width=6, stroke_fill="black")

    # --- Question text below center ---
    q_text = question.get("question", "")
    wrap_chars = lbl.get("wrap_chars", 13)
    # 3줄 초과 시 폰트 자동 축소로 3줄 내 수용
    q_font, lines = fit_font_for_lines(q_text, base_size=90, wrap_chars=wrap_chars, max_lines=3)

    line_y = qiy + qih + 30
    for line in lines:
        lw, lh = get_text_size(q_font, line)
        lx = (WIDTH - lw) // 2
        draw_stroked_text(draw, (lx, line_y), line, q_font,
                          fill="white", stroke_width=4, stroke_fill="black")
        line_y += lh + 18

    return canvas


def make_quiz_think(ep_dir: Path, last_question: dict, story: dict | None = None) -> Image.Image:
    """quiz_think.png -- blurred background with thinking prompt."""
    related_slide = last_question.get("related_slide", 3)
    scene_path = ep_dir / "images" / f"slide_{related_slide:02d}.png"
    canvas = load_bg(scene_path, "#2C1A4A")

    # Language labels
    lbl = get_labels(story)

    # Apply GaussianBlur
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=20))

    # Purple overlay 60%  (#7B2D8E)
    canvas = apply_overlay(canvas, "#7B2D8E", 0.60)

    draw = ImageDraw.Draw(canvas)

    # Center text
    main_font = get_font(110)
    main_text = lbl["think"]
    tw, th = get_text_size(main_font, main_text)
    tx = (WIDTH - tw) // 2
    ty = (HEIGHT // 2) - th - 30

    draw_stroked_text(draw, (tx, ty), main_text, main_font,
                      fill="white", stroke_width=5, stroke_fill="black")

    # Below: countdown
    count_font = get_font(80)
    count_text = "5... 4... 3... 2... 1..."
    cw, ch = get_text_size(count_font, count_text)
    cx = (WIDTH - cw) // 2
    cy = ty + th + 40

    draw_stroked_text(draw, (cx, cy), count_text, count_font,
                      fill="#FFD700", stroke_width=3, stroke_fill="black")

    return canvas


def make_quiz_answer(ep_dir: Path, a_index: int, question: dict, story: dict | None = None) -> Image.Image:
    """quiz_a{n}.png -- answer reveal on full-screen scene background."""
    related_slide = question.get("related_slide", a_index + 1)
    scene_path = ep_dir / "images" / f"slide_{related_slide:02d}.png"
    canvas = load_bg(scene_path, "#1A3A1A")

    # Language labels
    lbl = get_labels(story)

    # Green overlay 30% (#00AA00)
    canvas = apply_overlay(canvas, "#00AA00", 0.30)

    draw = ImageDraw.Draw(canvas)

    # --- Badge at top center ---
    badge_font = get_font(80)
    badge_text = lbl["correct"]
    btw, bth = get_text_size(badge_font, badge_text)
    badge_pad_x, badge_pad_y = 50, 20
    badge_w = btw + badge_pad_x * 2
    badge_h = bth + badge_pad_y * 2
    badge_x = (WIDTH - badge_w) // 2
    badge_y = 80

    draw_rounded_rect(draw,
                      (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                      radius=badge_h // 2, fill="#2ECC71")
    draw_stroked_text(draw, (badge_x + badge_pad_x, badge_y + badge_pad_y),
                      badge_text, badge_font, fill="white",
                      stroke_width=3, stroke_fill="#1A8A4A")

    # --- Answer text center ---
    answer_text = question.get("answer", "")
    wrap_chars = lbl.get("wrap_chars", 13)
    # 3줄 초과 시 폰트 자동 축소로 3줄 내 수용
    answer_font, lines = fit_font_for_lines(answer_text, base_size=96, wrap_chars=wrap_chars, max_lines=3)

    total_line_h = 0
    line_heights = []
    for line in lines:
        _, lh = get_text_size(answer_font, line)
        line_heights.append(lh)
        total_line_h += lh + 14
    total_line_h -= 14  # remove last spacing

    start_y = (HEIGHT - total_line_h) // 2
    for i, line in enumerate(lines):
        lw, lh = get_text_size(answer_font, line)
        lx = (WIDTH - lw) // 2
        draw_stroked_text(draw, (lx, start_y), line, answer_font,
                          fill="white", stroke_width=3, stroke_fill="black")
        start_y += lh + 14

    # --- Bottom center footer ---
    footer_font = get_font(36)
    footer_text = lbl["answer_footer"].format(n=a_index + 1)
    fw, fh = get_text_size(footer_font, footer_text)
    fx = (WIDTH - fw) // 2
    fy = HEIGHT - 120

    draw_stroked_text(draw, (fx, fy), footer_text, footer_font,
                      fill="#90EE90", stroke_width=2, stroke_fill="black")

    return canvas


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="퀴즈 슬라이드 PNG 생성 (Pillow)")
    parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (기본: 1)")
    parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
    args = parser.parse_args()

    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")
    story_path = ep_dir / "story.json"
    quiz_dir = ep_dir / "quiz"

    # Load story
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}")
        sys.exit(1)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    global _USE_LATIN_FONT
    from latin_font import needs_latin_font
    _USE_LATIN_FONT = needs_latin_font(get_lang(story))
    _font_cache.clear()

    quiz_questions = story.get("quiz_questions", []) or story.get("activity_sheet", {}).get("quiz_questions", [])
    if not quiz_questions:
        print("[WARN] quiz_questions가 비어 있습니다. 기본 3문제로 생성합니다.")
        quiz_questions = [
            {"question": "문제가 아직 준비되지 않았어요.", "answer": "곧 추가될 거예요!", "related_slide": 1},
            {"question": "문제가 아직 준비되지 않았어요.", "answer": "곧 추가될 거예요!", "related_slide": 2},
            {"question": "문제가 아직 준비되지 않았어요.", "answer": "곧 추가될 거예요!", "related_slide": 3},
        ]

    quiz_dir.mkdir(parents=True, exist_ok=True)

    meta = story.get("meta", {})
    title = meta.get("story_title", "동화")

    print(f"퀴즈 슬라이드 생성 -- [{ep_dir}] [{title}]")
    print("=" * 55)

    # Ensure Jua font
    _ensure_jua_font()

    generated = []

    # 1. quiz_intro.png
    print("  [1/8] quiz_intro.png 생성 중...")
    img = make_quiz_intro(ep_dir, story)
    out_path = quiz_dir / "quiz_intro.png"
    img.convert("RGB").save(out_path, "PNG")
    generated.append(out_path.name)
    print(f"         -> {out_path}")

    # 2~4. quiz_q1 ~ q3
    for i, q in enumerate(quiz_questions[:3]):
        fname = f"quiz_q{i + 1}.png"
        print(f"  [{i + 2}/8] {fname} 생성 중...")
        img = make_quiz_question(ep_dir, i, q, story)
        out_path = quiz_dir / fname
        img.convert("RGB").save(out_path, "PNG")
        generated.append(fname)
        print(f"         -> {out_path}")

    # 5. quiz_think.png
    print("  [5/8] quiz_think.png 생성 중...")
    last_q = quiz_questions[min(2, len(quiz_questions) - 1)]
    img = make_quiz_think(ep_dir, last_q, story)
    out_path = quiz_dir / "quiz_think.png"
    img.convert("RGB").save(out_path, "PNG")
    generated.append(out_path.name)
    print(f"         -> {out_path}")

    # 6~8. quiz_a1 ~ a3
    for i, q in enumerate(quiz_questions[:3]):
        fname = f"quiz_a{i + 1}.png"
        print(f"  [{i + 6}/8] {fname} 생성 중...")
        img = make_quiz_answer(ep_dir, i, q, story)
        out_path = quiz_dir / fname
        img.convert("RGB").save(out_path, "PNG")
        generated.append(fname)
        print(f"         -> {out_path}")

    print("=" * 55)
    print(f"  총 {len(generated)}개 퀴즈 슬라이드 생성 완료!")
    print(f"  출력 폴더: {quiz_dir}")
    for name in generated:
        print(f"    - {name}")


if __name__ == "__main__":
    main()
