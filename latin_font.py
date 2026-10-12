"""악센트가 있는 라틴 문자 언어(es·pt 등)용 폰트.

Jua에는 ñ·é·ã·¿ 같은 글자가 없어 퀴즈·썸네일에서 네모(□)로 깨진다(2026-10-11 스페인어 시범편에서 발견).
이런 언어는 둥근 오픈 폰트 Fredoka(Bold)로 그린다. ko·en·id 는 기존 Jua 그대로.
"""
from pathlib import Path
from PIL import ImageFont

FREDOKA = Path(__file__).parent / "assets/fonts/Fredoka.ttf"
ACCENT_LANGS = {"es", "pt", "fr", "de", "tr", "vi"}


def needs_latin_font(lang: str) -> bool:
    return (lang or "ko") in ACCENT_LANGS and FREDOKA.exists()


def latin_font(size: int):
    f = ImageFont.truetype(str(FREDOKA), size)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    return f
