#!/usr/bin/env python3
"""
07_generate_worksheet.py  (v6 — 랜덤 활동 선택, A4 2페이지, PDF 출력)
======================================================================
story.json → worksheet.html + worksheet.pdf  (A4 2페이지)

[ 활동 풀 ]
  CHECK   : comprehension_quiz / ox_quiz / fill_blank / story_recall
  GAME    : word_search / matching / consonant_quiz / word_chain / story_sequence / syllable_order
  CREATIVE: emotion_card / speech_bubble / letter_writing /
            story_continue / if_i_were / nickname
  ART     : drawing  (항상 고정)

[ 선택 알고리즘 ]
  페이지1 좌  ← 가중 랜덤 CHECK
  페이지1 우  ← 가중 랜덤 GAME
  페이지2 상  ← 가중 랜덤 CREATIVE  (학년 필터 적용)
  페이지2 하  ← drawing  (고정)

사용법:
  python 07_generate_worksheet.py --dir output/폴더명
  python 07_generate_worksheet.py --dir output/폴더명 --seed 7
  python 07_generate_worksheet.py --ep 1 --seed 42 --no-pdf
"""

import argparse
import base64
import html as html_mod
import io
import json
import random
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 낱말 찾기 채움용 음절 ─────────────────────────────────────────────────
_FILL = list(
    "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"
    "기니디리미비시이지치키티피히구누두루무부수우주추쿠투푸후"
    "갈날달랄말발살알잘찰칼탈팔할"
)

# ── 초성 추출 ─────────────────────────────────────────────────────────────
_CONS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"

def to_consonants(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            out.append(_CONS[(code - 0xAC00) // 28 // 21])
        else:
            out.append(ch)
    return "".join(out)


# ══════════════════════════════════════════════════════════════════════════
# 활동 풀 정의
# ══════════════════════════════════════════════════════════════════════════

ACTIVITY_POOL = {
    # ── CHECK ──────────────────────────────────────────────────
    "comprehension_quiz": {
        "title": "이야기 내용을 확인해요!",
        "icon": "❓",
        "category": "CHECK",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-blue",
    },
    "ox_quiz": {
        "title": "맞으면 O, 틀리면 X!",
        "icon": "⭕",
        "category": "CHECK",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-blue",
    },
    "fill_blank": {
        "title": "빈칸을 채워요!",
        "icon": "📝",
        "category": "CHECK",
        "grade_min": 2, "grade_max": 2,
        "weight": 1,
        "color": "c-blue",
    },
    "story_recall": {
        "title": "이야기 내용을 떠올려요!",
        "icon": "💭",
        "category": "CHECK",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-blue",
    },
    # ── GAME ───────────────────────────────────────────────────
    "word_search": {
        "title": "낱말을 찾아보세요!",
        "icon": "🔍",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    "matching": {
        "title": "선으로 이어보세요!",
        "icon": "✏️",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    "consonant_quiz": {
        "title": "초성 퀴즈를 풀어요!",
        "icon": "🔤",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    "word_chain": {
        "title": "끝말잇기 놀이!",
        "icon": "🔗",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    "story_sequence": {
        "title": "이야기 순서를 맞혀요!",
        "icon": "📋",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    "syllable_order": {
        "title": "음절을 순서대로 놓아요!",
        "icon": "🔀",
        "category": "GAME",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-orange",
    },
    # ── CREATIVE ───────────────────────────────────────────────
    "emotion_card": {
        "title": "등장인물의 기분을 알아봐요!",
        "icon": "💛",
        "category": "CREATIVE",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-purple",
    },
    "speech_bubble": {
        "title": "말풍선을 채워요!",
        "icon": "💬",
        "category": "CREATIVE",
        "grade_min": 1, "grade_max": 1,   # 1학년 위주
        "weight": 1,
        "color": "c-purple",
    },
    "if_i_were": {
        "title": "나라면 어떻게 했을까요?",
        "icon": "🤔",
        "category": "CREATIVE",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-purple",
    },
    "nickname": {
        "title": "등장인물에게 별명을 지어요!",
        "icon": "🏷️",
        "category": "CREATIVE",
        "grade_min": 1, "grade_max": 2,
        "weight": 1,
        "color": "c-purple",
    },
    "letter_writing": {
        "title": "등장인물에게 편지를 써요!",
        "icon": "✉️",
        "category": "CREATIVE",
        "grade_min": 2, "grade_max": 2,   # 2학년 위주
        "weight": 1,
        "color": "c-purple",
    },
    "story_continue": {
        "title": "이야기를 이어써요!",
        "icon": "📖",
        "category": "CREATIVE",
        "grade_min": 2, "grade_max": 2,
        "weight": 1,
        "color": "c-purple",
    },
    # ── ART (항상 고정) ────────────────────────────────────────
    "drawing": {
        "title": "상상해서 그리고 소개해요!",
        "icon": "🎨",
        "category": "ART",
        "grade_min": 1, "grade_max": 2,
        "weight": 99,
        "color": "c-green",
    },
}


# ══════════════════════════════════════════════════════════════════════════
# 랜덤 선택 알고리즘
# ══════════════════════════════════════════════════════════════════════════

def select_activities(grade: int, seed=None) -> dict:
    """
    카테고리별 가중 랜덤으로 활동 선택.
    Returns: {p1_left, p1_right, p2_top, p2_bottom, seed_used}
    """
    rng = random.Random(seed)
    actual_seed = seed if seed is not None else rng.randint(0, 999999)
    rng = random.Random(actual_seed)

    def weighted_pick(category: str) -> str:
        pool = [
            aid for aid, meta in ACTIVITY_POOL.items()
            if meta["category"] == category
            and meta["grade_min"] <= grade <= meta["grade_max"]
        ]
        if not pool:
            # grade 필터 실패 시 카테고리 전체에서 선택
            pool = [aid for aid, meta in ACTIVITY_POOL.items()
                    if meta["category"] == category]
        weights = [ACTIVITY_POOL[aid]["weight"] for aid in pool]
        return rng.choices(pool, weights=weights, k=1)[0]

    return {
        "p1_left":  weighted_pick("CHECK"),
        "p1_right": weighted_pick("GAME"),
        "p2_top":   weighted_pick("CREATIVE"),
        "p2_bottom": "drawing",
        "seed_used": actual_seed,
    }


# ══════════════════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════════════════

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def img_b64(path: Path) -> str | None:
    if path and path.exists():
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


def b64_img_tag(path: Path, alt: str = "", style: str = "") -> str:
    data = img_b64(path)
    if not data:
        return ""
    s = f' style="{style}"' if style else ""
    return f'<img src="data:image/png;base64,{data}" alt="{html_mod.escape(alt)}"{s}>'


# ══════════════════════════════════════════════════════════════════════════
# 캐릭터 얼굴 추출 (PIL)
# ══════════════════════════════════════════════════════════════════════════

# 스피커 → char_key 매핑 (구형 child_boy/child_girl + 신형 main_1/main_2 모두 지원)
# species 키워드 → 이모지 (한/영 혼용)
_SPECIES_EMOJI: dict[str, str] = {
    "고슴도치": "🦔", "토끼": "🐰", "강아지": "🐶", "개": "🐶", "puppy": "🐶",
    "고양이": "🐱", "곰": "🐻", "여우": "🦊", "다람쥐": "🐿️", "햄스터": "🐹",
    "올빼미": "🦉", "부엉이": "🦉", "새": "🐦", "참새": "🐦", "까치": "🐦", "두루미": "🕊️",
    "거북": "🐢", "병아리": "🐥", "뱀": "🐍", "turtle": "🐢", "snake": "🐍", "magpie": "🐦",
    "펭귄": "🐧", "물고기": "🐟", "개구리": "🐸", "사자": "🦁", "호랑이": "🐯",
    "코끼리": "🐘", "원숭이": "🐒", "오리": "🦆", "닭": "🐔", "나비": "🦋",
    "달팽이": "🐌", "수달": "🦦", "너구리": "🦝", "판다": "🐼", "쥐": "🐭",
    "잠수함": "🚢", "로봇": "🤖", "요정": "🧚", "정령": "🌳", "나무": "🌳",
    "달": "🌙", "별": "⭐", "우주": "🚀", "구름": "☁️", "불꽃": "🔥",
    "블록": "🟦", "말랑": "🫧", "통통": "🫐", "뽀글": "🌀", "솜": "☁️",
    "몽실": "🌟", "반점": "🔵", "두루": "🕊️", "에코": "🌿", "아미": "🌸",
    "hedgehog": "🦔", "rabbit": "🐰", "bunny": "🐰", "dog": "🐶",
    "cat": "🐱", "bear": "🐻", "fox": "🦊", "squirrel": "🐿️",
    "owl": "🦉", "bird": "🐦", "penguin": "🐧", "fish": "🐟",
    "frog": "🐸", "lion": "🦁", "tiger": "🐯", "elephant": "🐘",
    "monkey": "🐒", "duck": "🦆", "hamster": "🐹", "raccoon": "🦝",
    "panda": "🐼", "spirit": "🌟", "fairy": "🧚", "moon": "🌙",
    "star": "⭐", "robot": "🤖", "chick": "🐥", "sheep": "🐑",
}


def species_to_emoji(species: str) -> str:
    """species 문자열에서 이모지 추출. 없으면 빈 문자열."""
    if not species:
        return ""
    low = species.lower()
    for kw, emoji in _SPECIES_EMOJI.items():
        if kw in low:
            return emoji
    return ""


_CHAR_SPEAKERS: dict[str, set] = {
    "main_1": {"child_boy", "main_1"},
    "main_2": {"child_girl", "main_2"},
}
# face로 인정할 composition 목록 (좁은 클로즈업 우선, 미디엄도 허용)
_FACE_COMPS = {"close_up_face", "close_up_emotion", "medium_close_up", "medium_close"}


def find_best_face_slide(story: dict, char_key: str,
                         exclude_slides: set | None = None) -> int | None:
    """캐릭터에 맞는 얼굴 슬라이드 번호 반환.
    main_1/main_2: child_boy|main_1, child_girl|main_2 스피커 매칭
    supporting: char_key 자체가 스피커명 (teacher, woodland_spirit 등)
    composition 우선순위: _FACE_COMPS > 기타
    """
    slides = story.get("slides", [])
    exclude_slides = exclude_slides or set()

    # 이 캐릭터의 target speaker 집합
    target = _CHAR_SPEAKERS.get(char_key, {char_key})

    best_score = -1
    best_slide = None

    for s in slides:
        if s["slide_number"] in exclude_slides:
            continue
        speakers = {seg.get("speaker") for seg in s.get("tts_segments", [])}
        match = len(target & speakers)
        if match == 0:
            continue
        comp = s.get("composition", "")
        comp_bonus = 2 if comp in _FACE_COMPS else 1
        score = match * 10 + comp_bonus
        if score > best_score:
            best_score = score
            best_slide = s["slide_number"]

    return best_slide


def sheet_face_b64(out_dir: Path, char_key: str, size: int = 120) -> str | None:
    """02가 생성한 캐릭터 시트(characters/*.png)에서 얼굴 원형 크롭.
    전신 정면 시트이므로 상단 중앙이 얼굴 — 슬라이드 고정좌표 크롭보다 항상 정확."""
    if not _PIL_OK or out_dir is None:
        return None
    for name in (f"{char_key}.png", f"supporting_{char_key}.png"):
        p = out_dir / "characters" / name
        if not p.exists():
            continue
        try:
            img = Image.open(p).convert("RGBA")
            w, h = img.size
            side = int(w * 0.62)
            x0 = (w - side) // 2
            y0 = int(h * 0.03)
            crop = img.crop((x0, y0, x0 + side, y0 + side))
            mask = Image.new("L", (side, side), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
            crop = crop.resize((size, size), Image.LANCZOS)
            mask = mask.resize((size, size), Image.LANCZOS)
            result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            result.paste(crop, (0, 0), mask)
            buf = io.BytesIO()
            result.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            print(f"[WARN] 캐릭터 시트 크롭 실패({name}): {e}", file=sys.stderr)
    return None


def crop_face_b64(img_path: Path, size: int = 120) -> str | None:
    if not _PIL_OK or not img_path.exists():
        return None
    try:
        img = Image.open(img_path).convert("RGBA")
        w, h = img.size
        x0, x1 = int(w * 0.20), int(w * 0.80)
        y0, y1 = int(h * 0.00), int(h * 0.72)
        crop = img.crop((x0, y0, x1, y1))
        cw, ch = crop.size
        sq = min(cw, ch)
        crop = crop.crop(((cw - sq) // 2, (ch - sq) // 2,
                          (cw + sq) // 2, (ch + sq) // 2))
        mask = Image.new("L", (sq, sq), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, sq - 1, sq - 1), fill=255)
        crop = crop.resize((size, size), Image.LANCZOS)
        mask = mask.resize((size, size), Image.LANCZOS)
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(crop, (0, 0), mask)
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"[WARN] 얼굴 크롭 실패: {e}", file=sys.stderr)
        return None


def get_char_face_html(story: dict, char_key: str, char_name: str,
                       out_dir: Path, primary: str, accent: str,
                       size: int = 56,
                       exclude_slides: set | None = None,
                       species: str = "") -> tuple[str, int | None]:
    """얼굴 img HTML과 사용한 slide_number를 함께 반환.
    이미지 없으면 species 이모지 → 이름 첫 글자 순으로 폴백.
    """
    # 1순위: 캐릭터 시트 (정확한 단독 정면 얼굴) / 2순위: 슬라이드 크롭 (구방식 폴백)
    slide_num = None
    face_b64 = sheet_face_b64(out_dir, char_key, size * 2)
    if not face_b64:
        slide_num = find_best_face_slide(story, char_key, exclude_slides=exclude_slides)
        if slide_num is not None:
            face_b64 = crop_face_b64(out_dir / "images" / f"slide_{slide_num:02d}.png", size * 2)
    if face_b64:
        border = primary if char_key == "main_1" else accent
        html = (
            f'<img src="data:image/png;base64,{face_b64}" alt="{html_mod.escape(char_name)}" '
            f'style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;'
            f'border:2.5px solid {border};flex-shrink:0;">'
        )
        return html, slide_num
    # 이미지 없을 때: species 이모지 우선, 없으면 이름 첫 글자
    emoji = species_to_emoji(species)
    display = emoji if emoji else (char_name[0] if char_name else "?")
    font_size = "26px" if emoji else "20px"
    return (
        f'<div class="char-avatar" style="background:{accent}30;border:2.5px solid {accent};'
        f'font-size:{font_size};">'
        f'{display}</div>'
    ), None


# ══════════════════════════════════════════════════════════════════════════
# 스토리 데이터 추출 (활동 내용 생성용)
# ══════════════════════════════════════════════════════════════════════════

def _chars(story: dict) -> dict:
    return story.get("meta", {}).get("characters", {})


def _quiz_qs(story: dict) -> list:
    return story.get("activity_sheet", {}).get("quiz_questions", [])


def _main_names(story: dict) -> tuple[str, str]:
    chars = _chars(story)
    n1 = (chars.get("main_1") or {}).get("name", "주인공")
    n2 = (chars.get("main_2") or {}).get("name", "친구")
    return n1, n2


def get_word_search_words(story: dict) -> list[str]:
    chars = _chars(story)
    words = []
    for key in ("main_1", "main_2"):
        n = (chars.get(key) or {}).get("name", "")
        if 2 <= len(n) <= 5:
            words.append(n)
    title = story.get("meta", {}).get("story_title", "")
    words += [w for w in re.split(r"[\s,!?의와과]", title) if 2 <= len(w) <= 4]
    for w in ["이야기", "친구", "용기", "노래", "봄", "학교", "마음"]:
        if w not in words:
            words.append(w)
    return list(dict.fromkeys(words))[:7]


def get_matching_pairs(story: dict) -> list[dict]:
    """캐릭터 이름 ↔ 특징 매칭 쌍 생성.
    personality → species → role → narr 문장 순으로 폴백.
    """
    chars = _chars(story)
    pairs = []

    def best_trait(ch: dict) -> str:
        for field in ("personality", "species", "role"):
            v = (ch.get(field) or "").split(",")[0].strip()
            if v:
                return v[:20] + ("..." if len(v) > 20 else "")
        return ""

    for key in ("main_1", "main_2"):
        ch = chars.get(key) or {}
        if ch.get("name"):
            trait = best_trait(ch)
            if not trait:
                trait = "주인공"
            pairs.append({"name": ch["name"], "trait": trait})

    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        # 조연 전원 반영 (매칭 활동은 최대 4쌍까지)
        for v in sup.values():
            if isinstance(v, dict) and v.get("name"):
                trait = best_trait(v)
                if not trait:
                    trait = "조연"
                pairs.append({"name": v["name"], "trait": trait})
    pairs = pairs[:4]

    # 쌍이 2개 미만이면 나레이터 문장에서 이벤트 키워드 추가
    if len(pairs) < 2:
        n1, n2 = _main_names(story)
        fallback_traits = ["용기 있는", "친절한", "씩씩한", "호기심 많은"]
        for i, name in enumerate([n1, n2]):
            if name and len(pairs) <= i:
                pairs.append({"name": name, "trait": fallback_traits[i % len(fallback_traits)]})

    return pairs


def get_ox_items(story: dict, rng: random.Random) -> list[dict]:
    """OX 문항 생성: 나레이터 문장에서 참(O) 2개 + 거짓(X) 1개.
    나레이터 문장을 직접 사용하므로 내용이 자연스럽고 정확함.
    거짓 문항은 주인공 이름 교체로 생성.
    """
    n1, n2 = _main_names(story)

    # 나레이터 문장 수집 (15~50자, 주인공 이름 포함 우선)
    narr_sents: list[str] = []
    for s in story.get("slides", []):
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            text = seg.get("text", "").strip()
            # 문장 끝 마침표 통일
            if not text.endswith((".", "요.", "다.", "어.", "야.")):
                continue
            if 14 <= len(text) <= 52:
                narr_sents.append(text)

    rng.shuffle(narr_sents)

    items: list[dict] = []

    # 참(O) 2개: 나레이터 문장 그대로
    for sent in narr_sents:
        if len(items) >= 2:
            break
        items.append({"statement": sent, "answer": "O"})

    # 거짓(X) 1개: n1↔n2 이름 교체한 문장
    false_added = False
    for sent in narr_sents:
        if false_added:
            break
        if n1 and n1 in sent and n2 and n2 != n1:
            fake = sent.replace(n1, n2, 1)
            items.append({"statement": fake, "answer": "X"})
            false_added = True
        elif n2 and n2 in sent and n1 and n1 != n2:
            fake = sent.replace(n2, n1, 1)
            items.append({"statement": fake, "answer": "X"})
            false_added = True

    # fallback: 문장 없으면 quiz_questions 답변 사용
    if len(items) < 3:
        for q in _quiz_qs(story):
            if len(items) >= 3:
                break
            ans = q.get("answer", "")
            if len(ans) > 8:  # 단어 단답 제외, 문장형만
                items.append({"statement": ans[:48], "answer": "O"})

    rng.shuffle(items)
    return items[:3]


def get_fill_blank_items(story: dict) -> list[dict]:
    """슬라이드 나레이션에서 빈칸 문항 생성."""
    chars = _chars(story)
    key_words = [
        (chars.get(k) or {}).get("name", "")
        for k in ("main_1", "main_2")
        if (chars.get(k) or {}).get("name")
    ]
    slides = story.get("slides", [])
    items = []
    for s in slides:
        if s.get("type") not in ("story",):
            continue
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            text = seg.get("text", "")
            for kw in key_words:
                if kw and kw in text and len(text) < 50:
                    blanked = text.replace(kw, "____", 1)
                    items.append({"sentence": blanked, "answer": kw, "hint": kw[0] + "ㅇ"})
                    break
        if len(items) >= 3:
            break
    # fallback
    while len(items) < 2:
        items.append({"sentence": "이야기 속 주인공의 이름은 ____예요.", "answer": key_words[0] if key_words else "?", "hint": ""})
    return items[:3]


def get_consonant_items(story: dict) -> list[dict]:
    """핵심 단어 초성 퀴즈."""
    chars = _chars(story)
    words = []
    for key in ("main_1", "main_2"):
        n = (chars.get(key) or {}).get("name", "")
        if n:
            words.append({"word": n, "hint": (chars.get(key) or {}).get("species", "등장인물")})
    theme_words = [
        ("어깨동무", "서로 어깨에 팔을 얹는 것"),
        ("친구", "함께 놀고 공부하는 사이"),
        ("이야기", "책 속의 내용"),
        ("용기", "무서워도 해내는 힘"),
        ("마음", "느낌과 생각이 있는 곳"),
    ]
    for w, h in theme_words:
        if len(words) >= 5:
            break
        if not any(x["word"] == w for x in words):
            words.append({"word": w, "hint": h})
    items = [{"consonants": to_consonants(x["word"]), "hint": x["hint"], "answer": x["word"]}
             for x in words[:5]]
    return items


def get_word_chain_starts(story: dict) -> list[str]:
    """끝말잇기 시작 단어 (등장인물 이름에서 시작)."""
    n1, n2 = _main_names(story)
    return [n1, n2] if n2 != "친구" else [n1]


def get_emotion_scenes(story: dict) -> list[dict]:
    """감정을 느끼는 장면 추출."""
    EMOTIONS = ["기쁨", "슬픔", "설렘", "걱정", "용기", "뿌듯함", "외로움", "따뜻함", "놀람", "부끄러움"]
    slides = story.get("slides", [])
    n1, n2 = _main_names(story)
    scenes = []
    emotion_compositions = {"close_up_face", "medium_two_shot", "realization"}
    for s in slides[1:]:
        if s.get("composition") in emotion_compositions or s.get("color_mood") in ("realization", "tense_worried", "happy_ending"):
            text = s.get("text", "")[:40]
            if not text:
                continue
            # 3~4개 감정 선택지
            chosen = EMOTIONS[:4]
            scenes.append({
                "situation": f"{n1}이(가): {text}",
                "choices": chosen,
            })
        if len(scenes) >= 3:
            break
    if not scenes:
        scenes = [{"situation": f"{n1}이(가) 혼자 있을 때", "choices": EMOTIONS[:4]},
                  {"situation": f"{n1}이(가) 친구를 만났을 때", "choices": EMOTIONS[1:5]}]
    return scenes[:3]


def get_speech_bubbles(story: dict) -> list[dict]:
    """대화 말풍선 채우기 (주요 대화 장면)."""
    n1, n2 = _main_names(story)
    slides = story.get("slides", [])
    bubbles = []
    for s in slides:
        for seg in s.get("tts_segments", []):
            spk = seg.get("speaker", "")
            if spk in ("child_boy", "child_girl", "teacher"):
                char = n1 if spk == "child_boy" else (n2 if spk == "child_girl" else "선생님")
                text = seg.get("text", "")
                situation = s.get("text", "")[:30]
                if len(text) > 10:
                    bubbles.append({"character": char, "situation": situation, "hint": text[:15] + "..."})
        if len(bubbles) >= 3:
            break
    return bubbles[:3]


def get_letter_prompt(story: dict) -> dict:
    n1, _ = _main_names(story)
    return {
        "to": n1,
        "prompt": f"이야기 속 {n1}에게 하고 싶은 말을 편지로 써보세요!",
        "lines": 5,
    }


def get_story_continue_prompt(story: dict) -> dict:
    slides = story.get("slides", [])
    last_story = next((s for s in reversed(slides) if s.get("type") == "story"), {})
    return {
        "last_scene": last_story.get("text", "")[:35],
        "prompt": "이 다음에는 어떤 일이 일어났을까요? 이어서 써보세요!",
        "lines": 5,
    }


def get_if_i_were(story: dict) -> dict:
    quiz = _quiz_qs(story)
    situation = quiz[0].get("question", "") if quiz else "주인공과 같은 상황이라면?"
    n1, _ = _main_names(story)
    return {
        "situation": f"{n1}처럼 {situation[:30]}",
        "prompt": "나라면 어떻게 했을까요? 내 생각을 써보세요!",
        "lines": 4,
    }


def get_nickname_data(story: dict) -> list[dict]:
    chars = _chars(story)
    result = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key) or {}
        if ch.get("name"):
            p = ch.get("personality", "").split(",")[0].strip()[:20]
            result.append({"name": ch["name"], "trait": p})
    return result


def get_draw_prompt(story: dict) -> str:
    """이야기 끝부분의 '열린 질문'(상상 유도 발문)이 있으면 그리기 발문으로 사용.
    상상 단원의 핵심 활동(상상해서 표현하기)과 활동지를 직결시키는 장치."""
    slides = [s for s in story.get("slides", []) if s.get("type") == "story"]
    for s in reversed(slides[-3:]):
        for seg in reversed(s.get("tts_segments", [])):
            t = seg.get("text", "").strip()
            if t.endswith("?") and any(k in t for k in ["상상", "무엇이", "어떤", "같아", "какое", "누가"]):
                return t
    n1, n2 = _main_names(story)
    return f"{n1}와(과) {n2}의 이야기에서 가장 기억에 남는 장면은 무엇인가요?"


# ══════════════════════════════════════════════════════════════════════════
# 낱말 찾기 그리드
# ══════════════════════════════════════════════════════════════════════════

def build_word_search(words: list[str], grid_size: int = 9, rng: random.Random = None) -> list[list[str]]:
    if rng is None:
        rng = random.Random()
    grid = [[""] * grid_size for _ in range(grid_size)]
    for word in words:
        chars = list(word)
        wlen = len(chars)
        if wlen > grid_size:
            continue
        for _ in range(400):
            direction = rng.choice(["H", "V"])
            if direction == "H":
                r, c = rng.randint(0, grid_size - 1), rng.randint(0, grid_size - wlen)
                if all(grid[r][c + i] in ("", chars[i]) for i in range(wlen)):
                    for i in range(wlen):
                        grid[r][c + i] = chars[i]
                    break
            else:
                r, c = rng.randint(0, grid_size - wlen), rng.randint(0, grid_size - 1)
                if all(grid[r + i][c] in ("", chars[i]) for i in range(wlen)):
                    for i in range(wlen):
                        grid[r + i][c] = chars[i]
                    break
    for r in range(grid_size):
        for c in range(grid_size):
            if grid[r][c] == "":
                grid[r][c] = rng.choice(_FILL)
    return grid


# ══════════════════════════════════════════════════════════════════════════
# HTML 렌더러 (활동 유형별)
# ══════════════════════════════════════════════════════════════════════════

def _make_fallback_quiz_qs(story: dict) -> list[dict]:
    """quiz_questions 없을 때 나레이터 문장 + 캐릭터 정보로 문항 생성."""
    n1, n2 = _main_names(story)
    chars = _chars(story)
    sp1 = (chars.get("main_1") or {}).get("species", "")
    qs = []
    # 나레이터 문장에서 사건 중심 문장 추출
    for s in story.get("slides", []):
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            text = seg.get("text", "").strip()
            if 14 <= len(text) <= 48 and (n1 in text or n2 in text):
                qs.append({"question": text + " 왜 그랬을까요?", "answer": ""})
            if len(qs) >= 2:
                break
        if len(qs) >= 2:
            break
    # 캐릭터 기본 문항 보충
    if n1:
        qs.insert(0, {"question": f"이 이야기의 주인공 '{n1}'은 어떤 성격인가요?", "answer": ""})
    while len(qs) < 3:
        qs.append({"question": "이야기에서 가장 기억에 남는 장면을 써보세요.", "answer": ""})
    return qs[:3]


def render_comprehension_quiz(story: dict, **_) -> tuple[str, list]:
    qs = _quiz_qs(story)[:3]
    if not qs:
        qs = _make_fallback_quiz_qs(story)
    items = ""
    for i, q in enumerate(qs):
        text = html_mod.escape(q.get("question", ""))
        items += f"""<div class="cq-item">
  <div class="cq-q"><span class="num-badge">{i + 1}</span>{text}</div>
  <div class="cq-lines"><div class="cq-line"></div><div class="cq-line"></div></div>
</div>"""
    answers = [{"label": f"{i+1}", "ans": q.get("answer", "")} for i, q in enumerate(qs)]
    return f'<div class="cq-list">{items}</div>', answers


def render_ox_quiz(story: dict, rng: random.Random, **_) -> tuple[str, list]:
    items = get_ox_items(story, rng)
    html = ""
    for item in items:
        stmt = html_mod.escape(item["statement"])
        html += f"""<div class="ox-item">
  <div class="ox-circles">
    <div class="ox-circle">O</div>
    <div class="ox-circle">X</div>
  </div>
  <span class="ox-q">{stmt}</span>
</div>"""
    answers = [{"label": f"{i+1}", "ans": item["answer"]} for i, item in enumerate(items)]
    return f'<div class="ox-list">{html}</div>', answers


def render_fill_blank(story: dict, **_) -> tuple[str, list]:
    items = get_fill_blank_items(story)
    html = ""
    for i, item in enumerate(items):
        sent = html_mod.escape(item["sentence"])
        hint = item.get("hint", "")
        hint_html = f' <span class="fill-hint">힌트: {html_mod.escape(hint)}</span>' if hint else ""
        html += f'<div class="fill-item"><span class="num-badge">{i+1}</span>{sent}{hint_html}</div>'
    answers = [{"label": f"{i+1}", "ans": item.get("answer", "")} for i, item in enumerate(items)]
    return f'<div class="fill-list">{html}</div>', answers


def render_story_recall(story: dict, **_) -> tuple[str, list]:
    """중요한 장면 3가지를 직접 써보는 활동."""
    quizzes = story.get("activity_sheet", {}).get("quiz_questions", [])
    prompts = []
    for q in quizzes[:3]:
        scene = q.get("question", "")
        if scene:
            prompts.append(html_mod.escape(scene[:30]))
    # 3개 미만이면 빈 프롬프트로 채움
    while len(prompts) < 3:
        prompts.append("")

    items_html = ""
    for i, prompt in enumerate(prompts):
        hint = f'<span class="fill-hint">({prompt})</span>' if prompt else ""
        items_html += f"""<div class="recall-item">
  <span class="num-badge">{i+1}</span>{hint}
  <div class="cq-lines"><div class="cq-line"></div><div class="cq-line"></div></div>
</div>"""
    guide = '<p style="font-size:11px;color:#888;font-style:italic;margin-top:5px;">이야기에서 중요한 장면이나 내용을 떠올려 써보세요.</p>'
    return f'<div class="cq-list">{items_html}</div>{guide}', []


def render_word_search(story: dict, rng: random.Random, primary: str, accent: str, **_) -> tuple[str, list]:
    words = get_word_search_words(story)
    ws_words = [w for w in words if 2 <= len(w) <= 5][:7]
    grid = build_word_search(ws_words, rng=rng)
    rows = "".join(
        "<tr>" + "".join(f'<td class="ws-cell">{c}</td>' for c in row) + "</tr>"
        for row in grid
    )
    chips = "".join(f'<span class="word-chip">{html_mod.escape(w)}</span>' for w in ws_words)
    html = f"""<div class="ws-wrap">
<table class="ws-table"><tbody>{rows}</tbody></table>
<div class="word-list"><span class="wl-label">찾을 낱말 ▶</span>{chips}</div>
</div>"""
    return html, []


def render_matching(story: dict, rng: random.Random, **_) -> tuple[str, list]:
    pairs = get_matching_pairs(story)
    if not pairs:
        return "<div>데이터 없음</div>", []
    left = [p["name"] for p in pairs]
    right_orig = [p["trait"] for p in pairs]
    right = right_orig.copy()
    for _ in range(20):
        rng.shuffle(right)
        if right != right_orig:
            break
    left_html = "".join(
        f'<div class="match-item"><div class="match-num">{i+1}</div>'
        f'<span class="match-text">{html_mod.escape(n)}</span>'
        f'<div class="match-dot-r"></div></div>'
        for i, n in enumerate(left)
    )
    right_html = "".join(
        f'<div class="match-item"><div class="match-dot-l"></div>'
        f'<div class="match-num">{chr(65+i)}</div>'
        f'<span class="match-text">{html_mod.escape(d)}</span></div>'
        for i, d in enumerate(right)
    )
    # 정답: 1→A, 2→B... (셔플 기준)
    answer_map = {n: chr(65 + right.index(t)) for n, t in zip(left, right_orig)}
    answers = [{"label": f"{i+1}", "ans": answer_map.get(n, "?")} for i, n in enumerate(left)]
    html = f"""<div class="match-wrap">
  <div class="match-col left">{left_html}</div>
  <div class="match-gap"></div>
  <div class="match-col right">{right_html}</div>
</div>
<div class="match-hint">● 에서 ● 로 연필로 선을 이어보세요!</div>"""
    return html, answers


def render_consonant_quiz(story: dict, **_) -> tuple[str, list]:
    items = get_consonant_items(story)
    rows = ""
    for i, item in enumerate(items):
        cons = html_mod.escape(item["consonants"])
        hint = html_mod.escape(item.get("hint", ""))
        rows += f"""<div class="cons-item">
  <div class="cons-num">{i+1}</div>
  <div class="cons-box">{cons}</div>
  <div class="cons-arrow">→</div>
  <div class="cons-blank"></div>
  {f'<div class="cons-hint">({hint})</div>' if hint else ""}
</div>"""
    answers = [{"label": f"{i+1}", "ans": item.get("answer", "")} for i, item in enumerate(items)]
    return f'<div class="cons-list">{rows}</div>', answers


def render_word_chain(story: dict, rng: random.Random, **_) -> tuple[str, list]:
    starts = get_word_chain_starts(story)
    start = starts[0] if starts else "이야기"
    last_char = start[-1]
    # 세로 알고리즘 흐름: 시작단어 ↓ 빈칸 ↓ 빈칸 ...
    steps = ""
    for i in range(5):
        hint = f'<span class="chain-v-hint">{html_mod.escape(last_char)}으로 시작하는 말</span>' if i == 0 else ""
        steps += f'<div class="chain-v-step"><div class="chain-v-arrow">↓</div><div class="chain-v-box">{hint}</div></div>'
    guide = '<div class="chain-guide">앞 낱말의 마지막 글자로 시작하는 낱말을 이어 써보세요!</div>'
    html = f'<div class="chain-v-wrap"><div class="chain-v-start">{html_mod.escape(start)}</div>{steps}</div>{guide}'
    return html, []


def render_story_sequence(story: dict, rng: random.Random, **_) -> tuple[str, list]:
    """이야기 순서 배열: 나레이터 문장 3개를 섞어서 번호 쓰기."""
    narr = []
    for s in story.get("slides", []):
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            text = seg.get("text", "").strip()
            if 12 <= len(text) <= 40 and text not in narr:
                narr.append(text)
    if len(narr) < 3:
        # fallback: quiz questions
        for q in _quiz_qs(story):
            t = q.get("question", "")[:38]
            if t and t not in narr:
                narr.append(t)
    rng.shuffle(narr)
    events = narr[:3]
    correct_order = list(range(1, len(events) + 1))
    # 섞어서 출력 (순서 정답은 숨김 — 아이가 직접 번호 기입)
    display_order = list(range(len(events)))
    rng.shuffle(display_order)
    rows = ""
    answers = []
    for display_i, orig_i in enumerate(display_order):
        rows += f"""<div class="seq-item">
  <div class="seq-num"></div>
  <div class="seq-text">{html_mod.escape(events[orig_i])}</div>
</div>"""
        answers.append({"label": chr(65 + display_i), "ans": str(orig_i + 1)})
    guide = '<div class="seq-guide">이야기 순서에 맞게 번호를 써보세요! (1·2·3)</div>'
    return f'<div class="seq-list">{rows}</div>{guide}', answers


def render_syllable_order(story: dict, rng: random.Random, primary: str, accent: str, **_) -> tuple[str, list]:
    """음절 순서 맞히기: 이야기 핵심 단어의 음절을 섞어서 제시."""
    chars = _chars(story)
    words = []
    for key in ("main_1", "main_2"):
        n = (chars.get(key) or {}).get("name", "")
        if 2 <= len(n) <= 4:
            words.append(n)
    # 추가 단어 — story title에서 추출
    title = story.get("meta", {}).get("story_title", "")
    for part in re.split(r"[\s!?의와과]", title):
        if 2 <= len(part) <= 4 and part not in words:
            words.append(part)
    # 기본 단어 보충
    for w in ["친구", "용기", "행복", "마음", "이야기"]:
        if len(words) >= 5:
            break
        if w not in words:
            words.append(w)
    rng.shuffle(words)
    words = words[:4]

    items_html = ""
    answers = []
    for i, word in enumerate(words):
        syllables = list(word)
        rng.shuffle(syllables)
        chips = "".join(
            f'<span class="syl-chip">{html_mod.escape(s)}</span>' for s in syllables
        )
        items_html += f"""<div class="syl-item">
  <span class="syl-num">{i+1}</span>
  <div class="syl-chips">{chips}</div>
  <span class="syl-arrow">→</span>
  <div class="syl-blank"></div>
</div>"""
        answers.append({"label": str(i + 1), "ans": word})

    guide = '<div class="chain-guide">음절을 순서대로 놓아 낱말을 완성하세요!</div>'
    return f'<div class="syl-list">{items_html}</div>{guide}', answers


def render_emotion_card(story: dict, secondary: str, **_) -> tuple[str, list]:
    scenes = get_emotion_scenes(story)
    html = ""
    for i, sc in enumerate(scenes):
        q = html_mod.escape(sc["situation"])
        chips = "".join(
            f'<label class="emotion-chip"><input type="checkbox"><span>{html_mod.escape(e)}</span></label>'
            for e in sc["choices"]
        )
        html += f"""<div class="emotion-item">
  <div class="emotion-q"><span class="num-badge">{i+1}</span>{q}</div>
  <div class="emotion-chips">{chips}</div>
</div>"""
    return f'<div class="emotion-list">{html}</div>', []


def render_speech_bubble(story: dict, secondary: str, **_) -> tuple[str, list]:
    bubbles = get_speech_bubbles(story)
    html = ""
    for i, b in enumerate(bubbles):
        char = html_mod.escape(b["character"])
        situation = html_mod.escape(b.get("situation", ""))
        hint = b.get("hint", "")
        html += f"""<div class="bubble-item">
  <div class="bubble-char">{char}</div>
  <div class="bubble-right">
    <div class="bubble-situation">{situation}</div>
    <div class="bubble-shape">뭐라고 말했을까요?</div>
    {f'<div class="bubble-hint">힌트: {html_mod.escape(hint)}</div>' if hint else ""}
  </div>
</div>"""
    return f'<div class="bubble-list">{html}</div>', []


def render_letter_writing(story: dict, **_) -> tuple[str, list]:
    d = get_letter_prompt(story)
    lines = "".join('<div class="letter-line"></div>' for _ in range(d["lines"]))
    html = f"""<div class="letter-wrap">
  <div class="letter-to">받는 사람: {html_mod.escape(d["to"])} 에게</div>
  <div class="letter-prompt">{html_mod.escape(d["prompt"])}</div>
  <div class="letter-body">{lines}</div>
  <div class="letter-from">보내는 사람: ________________</div>
</div>"""
    return html, []


def render_story_continue(story: dict, **_) -> tuple[str, list]:
    d = get_story_continue_prompt(story)
    lines = "".join('<div class="continue-line"></div>' for _ in range(d["lines"]))
    html = f"""<div class="continue-wrap">
  {f'<div class="continue-last">...{html_mod.escape(d["last_scene"])}</div>' if d["last_scene"] else ""}
  <div class="continue-prompt">{html_mod.escape(d["prompt"])}</div>
  <div class="continue-body">{lines}</div>
</div>"""
    return html, []


def render_if_i_were(story: dict, primary: str, **_) -> tuple[str, list]:
    d = get_if_i_were(story)
    lines = "".join('<div class="iiw-line"></div>' for _ in range(d["lines"]))
    html = f"""<div class="iiw-wrap">
  <div class="iiw-situation">상황: {html_mod.escape(d["situation"])}</div>
  <div class="iiw-prompt">{html_mod.escape(d["prompt"])}</div>
  <div class="iiw-body">{lines}</div>
</div>"""
    return html, []


def render_nickname(story: dict, accent: str, **_) -> tuple[str, list]:
    chars = get_nickname_data(story)
    cards = ""
    for ch in chars:
        name = html_mod.escape(ch["name"])
        trait = html_mod.escape(ch["trait"])
        cards += f"""<div class="nickname-card">
  <div class="nickname-char">{name}</div>
  <div class="nickname-trait">특징: {trait}</div>
  <div class="nickname-blank-label">내가 지어줄 별명</div>
  <div class="nickname-blank"></div>
  <div class="nickname-reason-label">이유:</div>
  <div class="nickname-reason-blank"></div>
</div>"""
    return f'<div class="nickname-wrap">{cards}</div>', []


def render_drawing(story: dict, out_dir: Path | None = None,
                   rng: random.Random | None = None, **_) -> tuple[str, list]:
    """저학년용 상상 표현 활동:
    주인공 말풍선 발문 → 큰 상상 프레임에 그리기 → 이름 짓기 → 한 줄 소개 → 칭찬 도장.
    (이야기의 열린 질문을 발문으로 연결해 수업 흐름과 직결)"""
    prompt = get_draw_prompt(story)
    n1, _n2 = _main_names(story)

    # 주인공 얼굴 + 말풍선 발문 (읽기 부담을 줄이고 캐릭터가 직접 묻는 형식)
    face_html = '<div class="draw-coach-emoji">🗣️</div>'
    if out_dir is not None:
        b64 = sheet_face_b64(out_dir, "main_1", 80)
        if b64:
            face_html = (f'<img src="data:image/png;base64,{b64}" alt="{html_mod.escape(n1)}" '
                         f'style="width:40px;height:40px;flex-shrink:0;">')

    html = f"""<div class="draw-coach">
  {face_html}
  <div class="draw-bubble"><b>{html_mod.escape(n1)}</b>: “{html_mod.escape(prompt)}”</div>
</div>
<div class="imagine-row">
  <div class="imagine-frame"><span class="draw-placeholder">여기에 상상해서 그려요! ✏️</span></div>
  <div class="imagine-side">
    <div class="imagine-label">🏷️ 이름을 지어 주세요</div>
    <div class="draw-line"></div>
    <div class="imagine-label">💬 소개 한 줄 (어디에 살까? 무엇을 잘할까?)</div>
    <div class="draw-line"></div>
    <div class="draw-line"></div>
    <div class="stamp-row">
      <div class="stamp">참<br>잘했어요</div>
      <div class="stamp">상상력<br>최고</div>
      <div class="stamp">발표<br>완료</div>
    </div>
  </div>
</div>"""
    return html, []


# ══════════════════════════════════════════════════════════════════════════
# 공간 채우기 필러 (page-filler)
# ══════════════════════════════════════════════════════════════════════════

def crop_scene_b64(out_dir: Path, story: dict, rng: random.Random) -> tuple[str | None, int | None]:
    """랜덤 스토리 슬라이드를 리사이즈하여 base64로 반환 (참고 이미지용)."""
    if not _PIL_OK:
        return None, None
    slides = story.get("slides", [])
    story_slides = [s for s in slides if s.get("type") == "story" and s.get("slide_number", 0) >= 3]
    if not story_slides:
        story_slides = [s for s in slides if s.get("slide_number", 0) >= 2]
    if not story_slides:
        return None, None
    slide = rng.choice(story_slides[:8])
    slide_num = slide["slide_number"]
    img_path = out_dir / "images" / f"slide_{slide_num:02d}.png"
    if not img_path.exists():
        return None, None
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        target_w = 160  # 참고 이미지는 작게 — 그리기 공간 우선
        target_h = int(h * target_w / w)
        img_resized = img.resize((target_w, target_h), Image.LANCZOS)
        buf = io.BytesIO()
        img_resized.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode(), slide_num
    except Exception as e:
        print(f"[WARN] 장면 크롭 실패: {e}", file=sys.stderr)
        return None, None


def render_filler_scene_draw(story: dict, out_dir: Path, rng: random.Random,
                              primary: str, secondary: str, accent: str) -> str:
    """장면 참고 이미지 + 따라 그리기 공간."""
    scene_b64, _ = crop_scene_b64(out_dir, story, rng)
    if scene_b64:
        ref_html = (
            f'<div class="filler-ref">'
            f'<img src="data:image/png;base64,{scene_b64}" alt="참고 장면">'
            f'<div class="filler-ref-label">참고 장면</div>'
            f'</div>'
        )
    else:
        ref_html = ""
    return (
        f'<div class="filler-content">'
        f'{ref_html}'
        f'<div class="filler-draw-area">'
        f'<div class="filler-draw-label">✏️ 참고해서 따라 그려보세요!</div>'
        f'<div class="filler-draw-box"><span class="draw-placeholder">여기에 그려요</span></div>'
        f'</div>'
        f'</div>'
    )


def render_filler_letter_trace(story: dict, primary: str, accent: str) -> str:
    """낱말 따라쓰기 (1학년용): 핵심 단어를 보여주고 따라 쓰기."""
    chars = _chars(story)
    words = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key) or {}
        name = ch.get("name", "")
        if name and 2 <= len(name) <= 4:
            words.append(name)
    for w in ["친구", "이야기", "학교", "행복"]:
        if len(words) >= 4:
            break
        if w not in words:
            words.append(w)
    words = words[:4]

    rows = ""
    for i, w in enumerate(words):
        model = "".join(f'<span class="trace-char">{html_mod.escape(c)}</span>' for c in w)
        blanks = "".join('<span class="trace-blank"></span>' for _ in w)
        rows += (
            f'<div class="trace-row">'
            f'<span class="trace-label">{i+1}</span>'
            f'<div class="trace-model">{model}</div>'
            f'<div class="trace-blanks">{blanks}</div>'
            f'</div>'
        )
    guide = '<div style="font-size:10px;color:#aaa;font-style:italic;margin-top:3px;">글자를 보고 오른쪽 칸에 따라 써보세요!</div>'
    return f'<div class="trace-wrap">{rows}</div>{guide}'


def render_filler_char_draw(story: dict, out_dir: Path, rng: random.Random,
                             primary: str, accent: str) -> str:
    """등장인물 그리기: 캐릭터 아바타 + 그리기 공간."""
    n1, n2 = _main_names(story)
    choices = [n for n in [n1, n2] if n and n != "친구"]
    char_name = rng.choice(choices) if choices else n1
    char_key = "main_1" if char_name == n1 else "main_2"
    ch = _chars(story).get(char_key, {})
    species = ch.get("species", "")
    img_html, _ = get_char_face_html(
        story, char_key, char_name, out_dir, primary, accent, size=44, species=species
    )
    return (
        f'<div class="filler-char-wrap">'
        f'<div class="filler-char-header">{img_html}'
        f'<div class="filler-char-name">{html_mod.escape(char_name)}</div></div>'
        f'<div class="filler-char-prompt">✏️ {html_mod.escape(char_name)}의 모습을 자유롭게 그려보세요!</div>'
        f'<div class="filler-draw-box" style="flex:1 1 auto;min-height:45px;">'
        f'<span class="draw-placeholder">여기에 그려요</span></div>'
        f'</div>'
    )


def render_page_filler(story: dict, grade: int, out_dir: Path, rng: random.Random,
                        primary: str, secondary: str, accent: str) -> str:
    """페이지 남는 공간을 채우는 보너스 활동 HTML."""
    images_dir = out_dir / "images"
    has_images = images_dir.exists() and any(images_dir.glob("slide_*.png"))

    if has_images:
        icon, title = "🖼️", "장면을 따라 그려요!"
        content = render_filler_scene_draw(story, out_dir, rng, primary, secondary, accent)
    elif grade == 1:
        icon, title = "✍️", "낱말을 따라 써요!"
        content = render_filler_letter_trace(story, primary, accent)
    else:
        icon, title = "🎨", "등장인물을 그려요!"
        content = render_filler_char_draw(story, out_dir, rng, primary, accent)

    return (
        f'<div class="page-filler">'
        f'<div class="filler-act">'
        f'<div class="filler-act-title">{icon} {title}</div>'
        f'<div class="filler-act-body">{content}</div>'
        f'</div>'
        f'</div>'
    )


# ── 렌더러 맵 ─────────────────────────────────────────────────────────────

RENDERERS = {
    "comprehension_quiz": render_comprehension_quiz,
    "ox_quiz":            render_ox_quiz,
    "fill_blank":         render_fill_blank,
    "story_recall":       render_story_recall,
    "word_search":        render_word_search,
    "matching":           render_matching,
    "consonant_quiz":     render_consonant_quiz,
    "word_chain":         render_word_chain,
    "story_sequence":     render_story_sequence,
    "syllable_order":     render_syllable_order,
    "emotion_card":       render_emotion_card,
    "speech_bubble":      render_speech_bubble,
    "letter_writing":     render_letter_writing,
    "story_continue":     render_story_continue,
    "if_i_were":          render_if_i_were,
    "nickname":           render_nickname,
    "drawing":            render_drawing,
}


def render_activity(act_id: str, story: dict, rng: random.Random,
                    primary: str, secondary: str, accent: str,
                    out_dir: Path | None = None) -> tuple[str, list]:
    fn = RENDERERS.get(act_id)
    if not fn:
        return f"<div>알 수 없는 활동: {act_id}</div>", []
    try:
        return fn(story=story, rng=rng, primary=primary, secondary=secondary, accent=accent,
                  out_dir=out_dir)
    except Exception as e:
        return f'<div class="act-error">렌더링 오류: {html_mod.escape(str(e))}</div>', []


def build_act_html(act_id: str, story: dict, rng: random.Random,
                   primary: str, secondary: str, accent: str,
                   is_drawing: bool = False,
                   out_dir: Path | None = None) -> tuple[str, list]:
    meta = ACTIVITY_POOL.get(act_id, {})
    title = html_mod.escape(meta.get("title", act_id))
    icon = meta.get("icon", "★")
    color = meta.get("color", "c-blue")
    drawing_cls = " drawing-act" if is_drawing else ""
    chain_cls   = " chain-act"   if act_id == "word_chain" else ""
    body_html, answers = render_activity(act_id, story, rng, primary, secondary, accent, out_dir=out_dir)
    return f"""<div class="act {color}{drawing_cls}{chain_cls}">
  <div class="act-title">{icon} {title}</div>
  <div class="act-body">{body_html}</div>
</div>""", answers


# ══════════════════════════════════════════════════════════════════════════
# 등장인물 카드
# ══════════════════════════════════════════════════════════════════════════

def render_char_cards_html(chars: dict, story: dict, out_dir: Path,
                           primary: str, secondary: str, accent: str) -> str:
    char_list = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key)
        if ch and ch.get("name"):
            char_list.append((key, ch))
    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        # 조연 전원 카드 생성 (까치 어미·개구리 아저씨 등 누락 방지)
        for k, v in sup.items():
            if isinstance(v, dict) and v.get("name"):
                char_list.append((k, {"name": v["name"], "personality": v.get("role", ""), "species": v.get("species", "")}))

    cards = []
    used_slides: set = set()
    for key, ch in char_list:
        name = html_mod.escape(ch.get("name", ""))
        desc = ch.get("personality", "").split(",")[0].strip()
        if len(desc) > 22:
            desc = desc[:22] + "..."
        species = ch.get("species", "")

        # 모든 캐릭터(main + supporting)에 대해 얼굴 추출 시도
        img_html, used = get_char_face_html(
            story, key, ch.get("name", ""), out_dir, primary, accent,
            size=56, exclude_slides=used_slides, species=species
        )
        if used is not None:
            used_slides.add(used)

        # 추출 실패 시 파일 경로 폴백
        if "char-avatar" in img_html:
            slug = re.sub(r"[^a-zA-Z0-9가-힣]", "_", ch.get("name", key)).lower()
            for p in [out_dir / "images" / "characters" / f"{slug}.png",
                      out_dir / "images" / f"char_{key}.png"]:
                if p.exists():
                    img_html = b64_img_tag(p, alt=ch.get("name", ""),
                                           style="width:56px;height:56px;border-radius:50%;object-fit:cover;"
                                                 f"border:2.5px solid {primary};flex-shrink:0;")
                    break

        sub_text = species if species else desc
        cards.append(f"""<div class="char-card">
  {img_html}
  <div class="char-info">
    <div class="char-name">{name}</div>
    <div class="char-desc">{html_mod.escape(sub_text)}</div>
  </div>
</div>""")

    return "<div class='char-cards'>" + "".join(cards) + "</div>"


# ══════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════

def build_css(primary: str, secondary: str, accent: str, grade: int = 2) -> str:
    # Grade-dynamic font sizes: grade 1 is bigger (less proficient readers)
    body_fs   = 16 if grade == 1 else 15
    cq_q_fs   = 15 if grade == 1 else 14
    cq_line_h = 28 if grade == 1 else 24
    ox_q_fs   = 14 if grade == 1 else 12
    match_fs  = 14 if grade == 1 else 13
    fill_fs   = 15 if grade == 1 else 14
    draw_line_h = 32 if grade == 1 else 28
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
@page {{ size: A4 portrait; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: "Noto Sans KR", "Malgun Gothic", sans-serif;
  color: #222; background: #fff; font-size: {body_fs}px; line-height: 1.6;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}
.page {{
  width: 210mm; height: 297mm; padding: 10mm 13mm 9mm 13mm;
  overflow: hidden; display: flex; flex-direction: column; gap: 6px;
  page-break-after: always;
}}
.page:last-child {{ page-break-after: auto; }}

/* 헤더 */
.hdr {{
  text-align: center; padding: 9px 14px 7px;
  background: linear-gradient(135deg, {primary}22 0%, {secondary}18 100%);
  border-radius: 14px; border: 2px solid {primary}50; flex-shrink: 0;
}}
.badge-row {{ display: flex; justify-content: center; gap: 5px; flex-wrap: wrap; margin-bottom: 4px; }}
.badge {{ display: inline-block; background: {primary}; color: #fff; font-size: 9px; font-weight: 800; padding: 2px 9px; border-radius: 11px; }}
.badge.alt {{ background: #fff; color: {primary}; border: 1.5px solid {primary}60; }}
.hdr h1 {{ font-size: 17px; font-weight: 900; color: #1a2e40; line-height: 1.3; }}
.hdr .sub {{ font-size: 10px; color: #6b7a99; margin-top: 2px; }}

/* 학생 정보 바 */
.stu-bar {{
  display: flex; justify-content: space-between; align-items: center;
  font-size: 12px; flex-shrink: 0;
  border: 1.5px solid {primary}30; border-radius: 8px;
  padding: 6px 12px; background: {primary}05;
}}
.stu-fields {{ display: flex; gap: 16px; }}
.field {{ display: flex; align-items: center; gap: 6px; }}
.field-label {{ font-weight: 800; color: {primary}; font-size: 12px; white-space: nowrap; }}
.field-blank {{ width: 72px; height: 32px; border: 1.5px solid {primary}60; border-radius: 5px; background: #fff; }}
.stamp-box {{
  width: 52px; height: 52px; border: 2px solid {primary}35; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 8px; font-weight: 800; color: {primary}60;
  background: {primary}05; text-align: center; line-height: 1.3; flex-shrink: 0;
}}

/* 등장인물 */
.chars {{ flex-shrink: 0; }}
.section-title {{
  font-size: 12px; font-weight: 900; color: {primary};
  margin-bottom: 5px; padding: 4px 10px;
  background: linear-gradient(90deg, {primary}18, transparent);
  border-radius: 8px; border-left: 4px solid {primary};
  display: flex; align-items: center; gap: 5px;
}}
.char-cards {{ display: flex; gap: 7px; flex-wrap: wrap; }}
.char-card {{
  display: flex; align-items: center; gap: 8px;
  background: linear-gradient(135deg, {secondary}18, {secondary}08);
  border: 1.5px solid {secondary}55; border-radius: 12px;
  padding: 6px 11px; flex: 1; min-width: 110px;
}}
.char-avatar {{
  width: 56px; height: 56px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 900; color: {primary};
}}
.char-name {{ font-size: 13px; font-weight: 900; color: #1a2e40; }}
.char-desc {{ font-size: 10px; color: #5a6a88; margin-top: 1px; line-height: 1.4; }}

/* 2행 (위아래 쌓기) - 활동은 자연 높이, 필러가 남는 공간 채움 */
.two-col {{ display: flex; flex-direction: column; gap: 8px; flex: 1 1 auto; min-height: 0; overflow: hidden; }}
.two-col > .act {{ flex: 0 1 auto; }}

/* 활동 카드 */
.act {{
  display: flex; flex-direction: column;
  border-radius: 12px; border: 2px solid #e8ecf8;
  padding: 9px 11px; flex-shrink: 0;
}}
.act.c-blue  {{ border-color: {primary}50; background: {primary}05; border-left: 4px solid {primary}; }}
.act.c-purple {{ border-color: {secondary}60; background: {secondary}05; border-left: 4px solid {secondary}; }}
.act.c-green {{ border-color: #5ecf93; background: #f0fff8; border-left: 4px solid #5ecf93; }}
.act.c-orange {{ border-color: {accent}80; background: {accent}08; border-left: 4px solid {accent}; }}
.act.drawing-act {{ flex: 1 1 auto; min-height: 0; }}
.act.drawing-act .act-body {{ display: flex; flex-direction: column; flex: 1; min-height: 0; }}
.act-title {{
  font-size: 13px; font-weight: 900; color: {primary};
  margin-bottom: 7px; padding-bottom: 5px;
  border-bottom: 1.5px dashed {primary}25; flex-shrink: 0;
}}

/* ─ CHECK 활동 ─ */
.cq-list {{ display: flex; flex-direction: column; gap: 7px; }}
.cq-item {{ background: linear-gradient(135deg, #f5f8ff, #eef2ff); border: 1.5px solid #cdd6f4; border-radius: 10px; padding: 8px 10px; }}
.cq-q {{ font-size: {cq_q_fs}px; line-height: 1.6; margin-bottom: 5px; }}
.cq-lines {{ display: flex; flex-direction: column; gap: 4px; }}
.cq-line {{ border-bottom: 1px solid #b0b8d4; height: {cq_line_h}px; }}
.num-badge {{ display: inline-block; background: {accent}; color: #fff; font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 8px; margin-right: 4px; }}
.ox-list {{ display: grid; grid-template-columns: 1fr; gap: 7px; }}
.ox-item {{ display: flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #f5f8ff, #eef2ff); border: 1.5px solid #cdd6f4; border-radius: 10px; padding: 9px 11px; }}
.ox-circles {{ display: flex; gap: 7px; flex-shrink: 0; }}
.ox-circle {{ width: 30px; height: 30px; border-radius: 50%; border: 2.5px solid {primary}; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 14px; color: {primary}; }}
.ox-q {{ font-size: {ox_q_fs}px; line-height: 1.55; color: #333; }}
.fill-list {{ display: flex; flex-direction: column; gap: 6px; }}
.fill-item {{ background: #fffdf2; border: 1.5px solid {accent}50; border-radius: 8px; padding: 7px 11px; font-size: {fill_fs}px; line-height: 1.9; }}
.fill-hint {{ font-size: 11px; color: #aaa; font-style: italic; margin-left: 6px; }}

/* ─ GAME 활동 ─ */
.ws-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 6px; }}
.ws-table {{ border-collapse: collapse; }}
.ws-cell {{ width: 26px; height: 26px; text-align: center; vertical-align: middle; font-size: 13px; font-weight: 700; color: #333; border: 1px solid {primary}25; background: #fafbff; }}
.ws-table tr:nth-child(odd) .ws-cell {{ background: {primary}08; }}
.word-list {{ display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }}
.wl-label {{ font-size: 9px; font-weight: 700; color: #888; width: 100%; text-align: center; margin-bottom: 2px; }}
.word-chip {{ background: {accent}35; border: 1.5px solid {accent}; border-radius: 16px; padding: 2px 9px; font-size: 12px; font-weight: 700; color: #333; }}
.match-wrap {{ display: flex; align-items: stretch; border: 1.5px solid {secondary}50; border-radius: 10px; overflow: hidden; }}
.match-col {{ flex: 1; display: flex; flex-direction: column; }}
.match-col.left {{ background: {primary}08; }}
.match-col.right {{ background: {secondary}08; }}
.match-gap {{ width: 60px; background: #fff; border-left: 1px dashed {primary}20; border-right: 1px dashed {secondary}20; flex-shrink: 0; }}
.match-item {{ padding: 10px 10px; font-size: {match_fs}px; font-weight: 600; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 6px; min-height: 46px; }}
.match-item:last-child {{ border-bottom: none; }}
.match-col.left .match-item {{ justify-content: flex-end; }}
.match-col.right .match-item {{ justify-content: flex-start; }}
.match-num {{ font-size: 10px; font-weight: 800; color: {primary}; background: {primary}20; border-radius: 50%; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
.match-text {{ font-size: {match_fs}px; font-weight: 600; }}
.match-dot-r {{ width: 13px; height: 13px; border-radius: 50%; border: 2.5px solid {primary}; background: #fff; flex-shrink: 0; margin-left: 6px; }}
.match-dot-l {{ width: 13px; height: 13px; border-radius: 50%; border: 2.5px solid {secondary}; background: #fff; flex-shrink: 0; margin-right: 6px; }}
.match-hint {{ font-size: 10px; color: #888; font-style: italic; text-align: center; margin-top: 4px; }}
.cons-list {{ display: flex; flex-direction: column; gap: 6px; }}
.cons-item {{ display: flex; align-items: center; gap: 8px; }}
.cons-num {{ font-size: 11px; font-weight: 800; color: {primary}; width: 16px; flex-shrink: 0; }}
.cons-box {{ background: {primary}15; border: 1.5px solid {primary}40; border-radius: 7px; padding: 3px 10px; font-size: 15px; font-weight: 900; letter-spacing: 4px; color: {primary}; min-width: 56px; text-align: center; }}
.cons-arrow {{ color: #bbb; font-size: 13px; flex-shrink: 0; }}
.cons-blank {{ border-bottom: 2px solid {primary}; min-width: 70px; height: 1.2em; flex: 1; }}
.cons-hint {{ font-size: 11px; color: #aaa; font-style: italic; }}
/* 끝말잇기 - 세로 알고리즘 흐름 */
.act.chain-act .act-body {{ display: flex; flex-direction: column; flex: 1; min-height: 0; }}
.chain-v-wrap {{ display: flex; flex-direction: column; align-items: center; flex: 1; min-height: 0; gap: 0; padding: 4px 0; }}
.chain-v-start {{ background: {primary}; color: #fff; border-radius: 10px; padding: 8px 22px; font-size: 15px; font-weight: 900; flex-shrink: 0; }}
.chain-v-step {{ display: flex; flex-direction: column; align-items: center; flex: 1; width: 100%; min-height: 0; }}
.chain-v-arrow {{ font-size: 20px; font-weight: 900; color: {accent}; line-height: 1.1; flex-shrink: 0; }}
.chain-v-box {{ flex: 1; width: 90%; border: 2px solid {primary}40; border-radius: 10px; background: #fafbff; display: flex; align-items: center; padding: 4px 12px; min-height: 28px; }}
.chain-v-hint {{ font-size: 10px; color: #bbb; font-style: italic; }}
.chain-guide {{ font-size: 11px; color: #888; font-style: italic; flex-shrink: 0; margin-top: 4px; text-align: center; }}

/* ─ 이야기 순서 ─ */
.seq-list {{ display: flex; flex-direction: column; gap: 7px; }}
.seq-item {{ display: flex; align-items: center; gap: 8px; background: #fafbff; border: 1.5px solid {primary}25; border-radius: 9px; padding: 8px 10px; }}
.seq-num {{ width: 26px; height: 26px; border: 2px solid {primary}60; border-radius: 6px; flex-shrink: 0; background: #fff; }}
.seq-text {{ font-size: 13px; line-height: 1.5; color: #333; }}
.seq-guide {{ font-size: 11px; color: #888; font-style: italic; margin-top: 5px; }}

/* ─ 음절 순서 ─ */
.syl-list {{ display: flex; flex-direction: column; gap: 8px; }}
.syl-item {{ display: flex; align-items: center; gap: 6px; }}
.syl-num {{ font-size: 11px; font-weight: 800; color: {primary}; width: 16px; flex-shrink: 0; }}
.syl-chips {{ display: flex; gap: 4px; flex-shrink: 0; }}
.syl-chip {{ background: {accent}30; border: 1.5px solid {accent}; border-radius: 7px; padding: 4px 9px; font-size: 15px; font-weight: 900; color: #333; }}
.syl-arrow {{ color: #bbb; font-size: 13px; flex-shrink: 0; }}
.syl-blank {{ flex: 1; border-bottom: 2px solid {primary}50; min-width: 60px; height: 28px; }}

/* ─ CREATIVE 활동 ─ */
.emotion-list {{ display: flex; flex-direction: column; gap: 6px; }}
.emotion-item {{ background: {secondary}12; border: 1px solid {secondary}40; border-radius: 8px; padding: 6px 9px; }}
.emotion-q {{ font-size: 13px; margin-bottom: 5px; line-height: 1.5; }}
.emotion-chips {{ display: flex; gap: 5px; flex-wrap: wrap; }}
.emotion-chip {{ display: inline-flex; align-items: center; background: #fff; border: 1.5px solid {secondary}; border-radius: 18px; padding: 2px 9px; font-size: 12px; font-weight: 700; color: #555; cursor: pointer; }}
.emotion-chip input {{ display: none; }}
.bubble-list {{ display: flex; flex-direction: column; gap: 7px; }}
.bubble-item {{ display: flex; gap: 8px; align-items: flex-start; }}
.bubble-char {{ font-size: 11px; font-weight: 700; color: {primary}; background: {primary}15; border-radius: 8px; padding: 4px 7px; flex-shrink: 0; text-align: center; min-width: 40px; }}
.bubble-right {{ flex: 1; }}
.bubble-situation {{ font-size: 11px; color: #555; margin-bottom: 3px; }}
.bubble-shape {{ background: {secondary}12; border: 1.5px dashed {secondary}; border-radius: 12px; padding: 9px 13px; font-size: 12px; color: #ccc; min-height: 38px; }}
.bubble-hint {{ font-size: 11px; color: #aaa; font-style: italic; margin-top: 2px; }}
.letter-wrap {{ background: #fffbf0; border: 1.5px solid {accent}50; border-radius: 10px; padding: 9px 13px; }}
.letter-to {{ font-size: 13px; font-weight: 700; color: {primary}; margin-bottom: 4px; }}
.letter-prompt {{ font-size: 12px; color: #666; margin-bottom: 7px; font-style: italic; }}
.letter-body {{ display: flex; flex-direction: column; }}
.letter-line {{ border-bottom: 1px solid #ddd; height: 27px; margin-bottom: 2px; }}
.letter-from {{ font-size: 11px; font-weight: 600; color: #888; text-align: right; margin-top: 6px; }}
.continue-wrap {{ background: #f8f9ff; border: 1.5px solid {primary}30; border-radius: 10px; padding: 9px 13px; }}
.continue-last {{ font-size: 12px; color: #555; margin-bottom: 5px; background: {primary}10; padding: 4px 8px; border-radius: 6px; font-style: italic; }}
.continue-prompt {{ font-size: 12px; color: #666; margin-bottom: 6px; font-weight: 600; }}
.continue-line {{ border-bottom: 1px solid #ddd; height: 26px; margin-bottom: 2px; }}
.iiw-wrap {{ background: {secondary}10; border: 1.5px solid {secondary}40; border-radius: 10px; padding: 9px 13px; }}
.iiw-situation {{ font-size: 12px; font-weight: 700; color: #333; margin-bottom: 5px; background: {secondary}20; padding: 4px 8px; border-radius: 6px; }}
.iiw-prompt {{ font-size: 12px; font-weight: 700; color: {primary}; margin-bottom: 6px; }}
.iiw-line {{ border-bottom: 1px solid #ddd; height: 26px; margin-bottom: 2px; }}
.nickname-wrap {{ display: flex; gap: 10px; flex-wrap: wrap; }}
.nickname-card {{ flex: 1; min-width: 120px; background: {accent}10; border: 1.5px solid {accent}60; border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }}
.nickname-char {{ font-size: 16px; font-weight: 900; color: {primary}; text-align: center; padding: 4px; background: {primary}10; border-radius: 7px; }}
.nickname-trait {{ font-size: 11px; color: #555; }}
.nickname-blank-label, .nickname-reason-label {{ font-size: 10px; font-weight: 700; color: {primary}; margin-top: 4px; }}
.nickname-blank {{ border-bottom: 2px solid {accent}; height: 28px; margin-top: 2px; }}
.nickname-reason-blank {{ border-bottom: 1px solid #ccc; height: 22px; margin-top: 2px; }}

/* ── 공간 채우기 필러 ── */
.page-filler {{ flex: 1 1 0px; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }}
.filler-act {{
  flex: 1 1 auto; display: flex; flex-direction: column;
  border-radius: 12px; border: 2px dashed #5ecf9370;
  padding: 9px 11px; background: #f4fff9; min-height: 0;
}}
.filler-act-title {{
  font-size: 12px; font-weight: 900; color: #3dba7d;
  margin-bottom: 6px; padding-bottom: 5px;
  border-bottom: 1.5px dashed #5ecf9340; flex-shrink: 0;
}}
.filler-act-body {{ flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }}
/* 장면 따라 그리기 */
.filler-content {{ display: flex; gap: 8px; flex: 1 1 auto; min-height: 0; align-items: flex-start; }}
.filler-ref {{ flex: 0 0 auto; width: 42%; display: flex; flex-direction: column; gap: 3px; }}
.filler-ref img {{ width: 100%; border-radius: 8px; border: 1.5px solid #e0e4f0; display: block; }}
.filler-ref-label {{ font-size: 9px; color: #aaa; text-align: center; font-style: italic; }}
.filler-draw-area {{ flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; min-height: 0; }}
.filler-draw-label {{ font-size: 11px; font-weight: 700; color: #5ecf93; flex-shrink: 0; }}
.filler-draw-box {{
  flex: 1 1 auto; border: 2.5px dashed #a5b4fc; border-radius: 10px;
  min-height: 45px; display: flex; align-items: center; justify-content: center;
  background: #fefcfb;
}}
/* 글자 따라쓰기 (1학년) */
.trace-wrap {{ display: flex; flex-direction: column; gap: 5px; flex: 1 1 auto; }}
.trace-row {{ display: flex; align-items: center; gap: 6px; }}
.trace-label {{ font-size: 10px; font-weight: 700; color: {primary}60; width: 16px; flex-shrink: 0; }}
.trace-model {{ display: flex; gap: 2px; flex-shrink: 0; }}
.trace-char {{
  width: 28px; height: 28px; border: 1.5px dashed {accent}90; border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 700; color: {accent}80;
}}
.trace-blanks {{ display: flex; gap: 2px; flex-wrap: wrap; }}
.trace-blank {{ width: 28px; height: 28px; border: 1px solid #ddd; border-radius: 5px; background: #fff; }}
/* 캐릭터 그리기 */
.filler-char-wrap {{ display: flex; flex-direction: column; gap: 5px; flex: 1 1 auto; min-height: 0; }}
.filler-char-header {{ display: flex; align-items: center; gap: 8px; flex-shrink: 0; }}
.filler-char-name {{ font-size: 14px; font-weight: 900; color: {primary}; }}
.filler-char-prompt {{ font-size: 11px; color: #555; flex-shrink: 0; padding: 3px 8px; background: {primary}08; border-radius: 6px; }}

/* ─ ART 활동 ─ */
.draw-prompt {{ font-size: 11px; color: #555; margin-bottom: 6px; font-weight: 500; background: {secondary}18; padding: 4px 9px; border-radius: 7px; border-left: 3px solid {secondary}; flex-shrink: 0; }}
.draw-write-section {{ display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; margin-bottom: 6px; }}
.draw-write-label {{ font-size: 10px; font-weight: 700; color: {primary}; margin-bottom: 2px; }}
.draw-line {{ border-bottom: 1.5px solid #c0c8e0; height: {draw_line_h}px; }}
.draw-box-section {{ flex: 1; display: flex; flex-direction: column; min-height: 0; }}
.draw-box-label {{ font-size: 10px; font-weight: 700; color: {primary}; margin-bottom: 3px; flex-shrink: 0; }}
.draw-box {{ border: 2.5px dashed #a5b4fc; border-radius: 14px; flex: 1; min-height: 190px; width: 100%; display: flex; align-items: center; justify-content: center; color: #ddd; background: #fefcfb; }}
.draw-placeholder {{ font-size: 11px; color: #ccc; }}
/* 따라 그리기 (참고 이미지 + 그리기 나란히) */
/* 상상 표현 활동 (저학년) */
.draw-coach {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-shrink: 0; }}
.draw-coach-emoji {{ font-size: 24px; flex-shrink: 0; }}
.draw-bubble {{ background: {primary}14; border: 1.5px solid {primary}55; border-radius: 12px;
  padding: 6px 10px; font-size: 11.5px; line-height: 1.45; color: #333; position: relative; }}
.imagine-row {{ display: flex; gap: 12px; flex: 1 1 auto; min-height: 0; }}
.imagine-frame {{ flex: 1 1 58%; min-height: 200px; border: 3px dashed {accent};
  border-radius: 48% 48% 46% 46% / 58% 58% 40% 40%;  /* 알 모양 프레임 */
  background: #fffdf8; display: flex; align-items: center; justify-content: center; }}
.imagine-side {{ flex: 1 1 42%; display: flex; flex-direction: column; gap: 5px; min-width: 0; }}
.imagine-label {{ font-size: 10.5px; font-weight: 700; color: {primary}; margin-top: 2px; }}
.stamp-row {{ display: flex; gap: 8px; margin-top: auto; padding-top: 6px; justify-content: flex-end; }}
.stamp {{ width: 44px; height: 44px; border: 2px dashed #d8b4fe; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; text-align: center;
  font-size: 7.5px; color: #b39ddb; line-height: 1.3; flex-shrink: 0; }}
.draw-ref-row {{ display: flex; gap: 10px; flex: 1 1 auto; min-height: 0; }}
.draw-ref-panel {{ flex: 0 0 28%; display: flex; flex-direction: column; gap: 4px; }}
.draw-ref-label {{ font-size: 10px; font-weight: 700; color: #5ecf93; flex-shrink: 0; }}
.draw-copy-panel {{ flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; min-height: 0; }}

/* 페이지 하단 */
.page-footer {{ margin-top: auto; padding: 5px 8px; flex-shrink: 0; border-top: 1.5px dashed {primary}20; display: flex; justify-content: center; align-items: center; }}
.footer-msg {{ font-size: 9px; color: {primary}50; font-style: italic; letter-spacing: 0.5px; }}

/* mini 헤더 */
.mini-hdr {{ display: flex; align-items: center; justify-content: space-between; padding: 5px 11px; background: {primary}12; border-radius: 7px; border: 1.5px solid {primary}30; flex-shrink: 0; }}
.mini-hdr-title {{ font-size: 12px; font-weight: 700; color: {primary}; }}
.mini-hdr-fields {{ display: flex; gap: 11px; font-size: 11px; }}

/* 정답 키 */
.answer-key {{ margin-top: auto; padding: 5px 10px; flex-shrink: 0; border: 1.5px dashed {primary}30; border-radius: 8px; background: {primary}04; }}
.ak-title {{ font-size: 8px; font-weight: 700; color: #ccc; letter-spacing: 2px; margin-bottom: 2px; text-align: center; }}
.ak-body {{ font-size: 9px; color: #aaa; line-height: 1.6; }}
.act-error {{ color: red; font-size: 11px; padding: 8px; }}

@media screen {{
  body {{ background: #e0e4f0; }}
  .page {{ margin: 6mm auto; box-shadow: 0 4px 20px rgba(0,0,0,0.12); }}
}}
@media print {{
  body {{ background: #fff; margin: 0 !important; padding: 0 !important; }}
  .page {{ margin: 0 !important; box-shadow: none !important; }}
  .emotion-chip input {{ display: none; }}
}}
"""


# ══════════════════════════════════════════════════════════════════════════
# HTML 조립
# ══════════════════════════════════════════════════════════════════════════

def build_html(story: dict, selection: dict, out_dir: Path) -> str:
    meta = story.get("meta", {})
    title = html_mod.escape(meta.get("story_title", meta.get("title", "동화")))
    unit_title = meta.get("unit_title", "")
    sub_unit = meta.get("sub_unit", "")
    grade = meta.get("grade", 2)
    subject = meta.get("subject", "국어")
    series = meta.get("series", "")

    palette = meta.get("color_palette", {})
    primary   = palette.get("primary", "#4A90D9")
    secondary = palette.get("secondary", "#7EC8A0")
    accent    = palette.get("accent", "#FFC53D")

    css = build_css(primary, secondary, accent, grade)
    chars = meta.get("characters", {})
    char_cards_html = render_char_cards_html(chars, story, out_dir, primary, secondary, accent)

    seed_used = selection["seed_used"]
    rng = random.Random(seed_used)

    # 활동 렌더링
    p1l_html, p1l_ans = build_act_html(selection["p1_left"],  story, rng, primary, secondary, accent)
    p1r_html, p1r_ans = build_act_html(selection["p1_right"], story, rng, primary, secondary, accent)
    p2t_html, p2t_ans = build_act_html(selection["p2_top"],   story, rng, primary, secondary, accent)
    p2b_html, _       = build_act_html(selection["p2_bottom"], story, rng, primary, secondary, accent, is_drawing=True, out_dir=out_dir)

    # 페이지1 남는 공간 채우기
    filler_html = render_page_filler(story, grade, out_dir, rng, primary, secondary, accent)

    # 정답
    all_answers = p1l_ans + p1r_ans + p2t_ans
    answer_parts = [f"{a['label']}. {a['ans'][:25]}{'...' if len(a['ans']) > 25 else ''}"
                    for a in all_answers if a.get("ans")]
    answers_html = " &nbsp;|&nbsp; ".join(answer_parts) if answer_parts else "—"

    # 배지
    grade_badge = f'<span class="badge">초등 {grade}학년</span>'
    subject_badge = f'<span class="badge">{html_mod.escape(subject)}</span>'
    series_badge = f'<span class="badge alt">{html_mod.escape(series)}</span>' if series else ""
    unit_badge = f'<span class="badge alt">{html_mod.escape(unit_title)}</span>' if unit_title else ""
    sub_unit_html = f'<div class="sub">{html_mod.escape(sub_unit)}</div>' if sub_unit else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>독후 활동지 - {title}</title>
<style>{css}</style>
</head>
<body>

<!-- ======== 페이지 1 ======== -->
<div class="page">

  <div class="hdr">
    <div class="badge-row">{grade_badge}{subject_badge}{series_badge}{unit_badge}</div>
    <h1>📖 {title}</h1>
    {sub_unit_html}
  </div>

  <div class="stu-bar">
    <div class="stu-fields">
      <div class="field"><span class="field-label">이름</span><div class="field-blank"></div></div>
      <div class="field"><span class="field-label">반</span><div class="field-blank" style="width:48px;"></div></div>
      <div class="field"><span class="field-label">번호</span><div class="field-blank" style="width:48px;"></div></div>
      <div class="field"><span class="field-label">날짜</span><div class="field-blank"></div></div>
    </div>
    <div class="stamp-box">선생님<br>도장</div>
  </div>

  <div class="chars">
    <div class="section-title"><span>👥</span> 등장인물을 만나볼까요?</div>
    {char_cards_html}
  </div>

  <div class="two-col">
    {p1l_html}
    {p1r_html}
    {filler_html}
  </div>

  <div class="page-footer">
    <span class="footer-msg">☆ 오늘도 열심히 읽었어요! ☆ &nbsp;[seed: {seed_used}]</span>
  </div>

</div>

<!-- ======== 페이지 2 ======== -->
<div class="page">

  <div class="mini-hdr">
    <div class="mini-hdr-title">📖 {title}</div>
    <div class="mini-hdr-fields">
      <div class="field"><span class="field-label">이름</span><div class="field-blank"></div></div>
    </div>
  </div>

  {p2t_html}
  {p2b_html}

  <div class="answer-key">
    <div class="ak-title">정 &nbsp; 답</div>
    <div class="ak-body">{answers_html}</div>
  </div>

</div>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# PDF 변환
# ══════════════════════════════════════════════════════════════════════════

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


def html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    browser = find_browser()
    if not browser:
        return False
    cmd = [browser, "--headless", "--disable-gpu", "--no-sandbox",
           "--disable-extensions", "--run-all-compositor-stages-before-draw",
           f"--print-to-pdf={pdf_path.resolve()}",
           "--no-pdf-header-footer", "--print-to-pdf-no-header",
           html_path.resolve().as_uri()]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                encoding="utf-8", errors="replace")
        return pdf_path.exists() and pdf_path.stat().st_size > 0
    except Exception as e:
        print(f"[WARN] PDF 변환 오류: {e}", file=sys.stderr)
        return False


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="독후 활동지 생성 v6 (랜덤 활동 선택, A4 2페이지, PDF)")
    parser.add_argument("--ep", type=int, default=None)
    parser.add_argument("--dir", dest="dir_path", type=str, default=None)
    parser.add_argument("--seed", type=int, default=None,
                        help="랜덤 시드 (미지정 시 매번 다른 활동 조합)")
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()

    if args.dir_path:
        out_dir = Path(args.dir_path)
    else:
        ep_num = args.ep if args.ep is not None else 1
        out_dir = Path(f"output/ep{ep_num:02d}")

    out_dir.mkdir(parents=True, exist_ok=True)

    story = load_json(out_dir / "story.json")
    if not story:
        print(f"[ERROR] story.json 없음: {out_dir / 'story.json'}", file=sys.stderr)
        sys.exit(1)

    grade = story.get("meta", {}).get("grade", 2)
    selection = select_activities(grade, seed=args.seed)

    print(f"\n[활동 선택] seed={selection['seed_used']}")
    print(f"  페이지1 좌: {selection['p1_left']}  ({ACTIVITY_POOL[selection['p1_left']]['title']})")
    print(f"  페이지1 우: {selection['p1_right']}  ({ACTIVITY_POOL[selection['p1_right']]['title']})")
    print(f"  페이지2 상: {selection['p2_top']}  ({ACTIVITY_POOL[selection['p2_top']]['title']})")
    print(f"  페이지2 하: drawing  (그리기 - 고정)")

    html_content = build_html(story, selection, out_dir)
    html_path = out_dir / "worksheet.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    pdf_path = out_dir / "worksheet.pdf"
    pdf_ok = False
    if not args.no_pdf:
        print("[INFO] PDF 변환 중...")
        pdf_ok = html_to_pdf(html_path, pdf_path)

    print(f"\n활동지 생성 완료")
    print(f"{'=' * 50}")
    print(f"  제목: {story.get('meta', {}).get('story_title', '')}")
    print(f"  형식: A4 2페이지  |  seed: {selection['seed_used']}")
    print(f"  HTML: {html_path}  ({html_path.stat().st_size // 1024} KB)")
    if pdf_ok:
        print(f"  PDF:  {pdf_path}  ({pdf_path.stat().st_size // 1024} KB)")
    else:
        print(f"  PDF:  생성 실패 (브라우저에서 인쇄 가능)")
    print(f"\n  다른 조합 재생성: python 07_generate_worksheet.py --dir {out_dir}")
    print(f"  동일 재현:        python 07_generate_worksheet.py --dir {out_dir} --seed {selection['seed_used']}")


if __name__ == "__main__":
    main()
