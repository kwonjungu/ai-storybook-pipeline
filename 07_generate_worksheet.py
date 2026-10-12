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
import hashlib
import json
import random
import re
import subprocess
import sys
from datetime import datetime
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
        "title": "글자를 바르게 놓아요!",
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

# v2.1 모드: activity_sheet 데이터(원문 근거 검증됨)가 있는 활동만 고른다.
# 휴리스틱으로만 만들 수 있는 활동(끝말잇기·낱말찾기·별명·편지·나라면 등)은
# 이야기와 무관한 낱말·원문에 없는 사실이 섞이는 결함원이라 제외(2026-09-26 전수조사).
V21_POOL = {
    "CHECK":    ["comprehension_quiz", "ox_quiz", "fill_blank"],
    "GAME":     ["story_sequence", "syllable_order", "consonant_quiz"],
    "CREATIVE": ["speech_bubble", "emotion_card"],
}


def has_v21(story: dict | None) -> bool:
    return (story or {}).get("activity_sheet", {}).get("schema") == "2.1"


def select_activities(grade: int, seed=None, story: dict | None = None) -> dict:
    """
    카테고리별 가중 랜덤으로 활동 선택.
    Returns: {p1_left, p1_right, p2_top, p2_bottom, seed_used}
    """
    rng = random.Random(seed)
    actual_seed = seed if seed is not None else rng.randint(0, 999999)
    rng = random.Random(actual_seed)

    if has_v21(story):
        return {
            "p1_left":  rng.choice(V21_POOL["CHECK"]),
            "p1_right": rng.choice(V21_POOL["GAME"]),
            "p2_top":   rng.choice(V21_POOL["CREATIVE"]),
            "p2_bottom": "drawing",
            "seed_used": actual_seed,
        }

    # v2 fill_blanks가 있으면 fill_blank를 1학년에게도 개방 (보기 상자 제공으로 난도 완화)
    fb_v2 = bool((story or {}).get("activity_sheet", {}).get("fill_blanks"))

    def _grade_ok(aid: str, meta: dict) -> bool:
        if aid == "fill_blank" and fb_v2:
            return True
        return meta["grade_min"] <= grade <= meta["grade_max"]

    def weighted_pick(category: str) -> str:
        pool = [
            aid for aid, meta in ACTIVITY_POOL.items()
            if meta["category"] == category
            and _grade_ok(aid, meta)
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


# 한국어 동물/종 명사 (personality 등에서 종을 복원할 때 사용)
_KO_SPECIES = [
    "병아리", "거북", "달팽이", "개미", "강아지", "판다", "카멜레온", "곰",
    "올빼미", "부엉이", "닭", "여우", "하마", "토끼", "다람쥐", "고양이",
    "사자", "호랑이", "코끼리", "기린", "펭귄", "오리", "수달", "너구리",
    "고슴도치", "사슴", "돼지", "양", "말", "소", "쥐", "새", "물고기",
    "개구리", "나비", "벌", "원숭이", "코알라", "악어", "뱀",
]


def guess_species(*texts) -> str:
    """species 필드가 비었을 때 personality/role/이름 등에서 종 명사를 복원.
    (활동지 캐릭터 카드에서 '종'이 잘려 사라지는 문제 방지)"""
    for t in texts:
        if not t:
            continue
        for kw in _KO_SPECIES:
            if len(kw) <= 1:
                # 한 글자 종('양'·'말'·'소'…)은 '영양 선생님'·'말하기'에 잘못 걸림 → 독립 어절만
                m = re.search(r"(?:^|\s)" + kw + r"(?=$|[\s,.)이가은는을를의와과])", t)
                if not m:
                    continue
                idx = m.start() + (1 if t[m.start()].isspace() else 0)
            elif kw in t:
                idx = t.find(kw)
            else:
                continue
            if True:
                # '아기 거북', '꼬마 달팽이'처럼 수식어까지 포함해 반환
                pre = t[max(0, idx - 3):idx]
                for mod in ("아기", "꼬마", "어린"):
                    if mod in pre:
                        return mod + " " + kw
                return kw
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

    seen_traits: set = set()

    def best_trait(ch: dict, avoid: set) -> str:
        # 종을 우선 노출하되, 이미 쓰인 종과 겹치면 성격으로 대체(매칭 정답 애매 방지)
        sp = (ch.get("species") or "").strip() or guess_species(
            ch.get("personality", ""), ch.get("role", ""))
        if sp and sp not in avoid:
            return sp
        for field in ("personality", "role"):
            v = (ch.get(field) or "").split(",")[0].strip()
            if v and v not in avoid:
                return v[:14] + ("..." if len(v) > 14 else "")
        return sp or ""

    for key in ("main_1", "main_2"):
        ch = chars.get(key) or {}
        if ch.get("name"):
            trait = best_trait(ch, seen_traits) or "주인공"
            seen_traits.add(trait)
            pairs.append({"name": ch["name"], "trait": trait})

    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        # 조연 전원 반영 (매칭 활동은 최대 4쌍까지)
        for v in sup.values():
            if isinstance(v, dict) and v.get("name"):
                trait = best_trait(v, seen_traits)
                # 특징이 비었거나 이미 쓰인 것과 겹치면 매칭에서 제외(정답 애매 방지)
                if not trait or trait in seen_traits:
                    continue
                seen_traits.add(trait)
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
    """OX 문항 생성.
    v2: activity_sheet.ox_items({text, answer:bool})가 있으면 그대로 사용.
    폴백: 나레이터 문장에서 참(O) 2개 + 거짓(X) 1개(이름 교체 휴리스틱).
    """
    v2 = story.get("activity_sheet", {}).get("ox_items")
    if isinstance(v2, list) and v2:
        items = []
        for it in v2:
            text = (it.get("text") or "").strip()
            if not text:
                continue
            ans = it.get("answer")
            # bool / 문자열 O·X 모두 허용
            if isinstance(ans, bool):
                ans_s = "O" if ans else "X"
            else:
                ans_s = "O" if str(ans).strip().upper() in ("O", "TRUE", "참", "T") else "X"
            items.append({"statement": text, "answer": ans_s})
        if len(items) >= 3:
            rng.shuffle(items)
            return items[:3]

    n1, n2 = _main_names(story)

    def _fix_josa(text: str, name: str) -> str:
        """name 바로 뒤 조사를 name의 받침 유무에 맞게 교정."""
        if not name or not ("가" <= name[-1] <= "힣"):
            return text
        has_batchim = (ord(name[-1]) - 0xAC00) % 28 != 0
        for withb, without in [("은", "는"), ("이", "가"), ("을", "를"),
                                ("과", "와"), ("이랑", "랑")]:
            correct = withb if has_batchim else without
            wrong = without if has_batchim else withb
            text = re.sub(re.escape(name) + re.escape(wrong) + r"(?=[\s.,!?)\"']|$)",
                          name + correct, text)
        return text

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

    def _no_dup_name(text: str, name: str) -> bool:
        """교체 결과에 같은 이름이 연속/근접 중복되면 비문 — 최종 검사(W1)."""
        if not name:
            return True
        # 같은 이름이 2회 이상 등장하면 '토토와 토토'류 비문 위험 → 거부
        if text.count(name) >= 2:
            return False
        # 연속(공백/조사 사이) 중복도 방어
        if re.search(re.escape(name) + r"[\s와과랑이가은는을를의도,]{0,3}" + re.escape(name), text):
            return False
        return True

    # 거짓(X) 1개 먼저: n1↔n2 이름 교체 — 원본 문장은 O 후보에서 제외 (정답 유출 방지)
    # 이름 교체 후 바로 뒤 조사를 새 이름 받침에 맞게 교정 (예: '무지가'→'포근가'(X)→'포근이'(O))
    # W1: 두 주인공 이름이 모두 들어간 문장은 교체 시 '토토와 토토'가 되므로 제외.
    fake_source = None
    for sent in narr_sents:
        both = (n1 and n1 in sent) and (n2 and n2 in sent) and n1 != n2
        if both:
            continue  # W1: 두 이름 동시 포함 문장은 교체 대상에서 제외
        if n1 and n1 in sent and n2 and n2 != n1:
            cand = _fix_josa(sent.replace(n1, n2, 1), n2)
            if _no_dup_name(cand, n2):  # W1: 결과 중복 최종 검사
                items.append({"statement": cand, "answer": "X"})
                fake_source = sent
                break
        elif n2 and n2 in sent and n1 and n1 != n2:
            cand = _fix_josa(sent.replace(n2, n1, 1), n1)
            if _no_dup_name(cand, n1):  # W1: 결과 중복 최종 검사
                items.append({"statement": cand, "answer": "X"})
                fake_source = sent
                break

    # 참(O) 2개: X의 원본과 다른 나레이터 문장만
    for sent in narr_sents:
        if sum(1 for it in items if it["answer"] == "O") >= 2:
            break
        if sent != fake_source:
            items.append({"statement": sent, "answer": "O"})

    rng.shuffle(items)

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
    """빈칸 문항 생성.
    v2: activity_sheet.fill_blanks({sentence,example,answer})가 있으면 그대로 사용
        (___ 빈칸 + 보기(example) 상자 표시).
    폴백: 슬라이드 나레이션에서 이름을 빈칸 처리(2학년 전용 휴리스틱)."""
    v2 = story.get("activity_sheet", {}).get("fill_blanks")
    if isinstance(v2, list) and v2:
        items = []
        for it in v2:
            sent = (it.get("sentence") or "").strip()
            if not sent:
                continue
            # ___ 표기를 렌더 공통 형식(____)으로 정규화
            sent = re.sub(r"_{2,}", "____", sent)
            items.append({
                "sentence": sent,
                "answer": (it.get("answer") or "").strip(),
                "example": (it.get("example") or "").strip(),
                "distractor": (it.get("distractor") or "").strip(),
                "hint": "",
            })
        if len(items) >= 2:
            return items[:3]

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
    """핵심 단어 초성 퀴즈.
    v2: activity_sheet.wordplay.consonant_words가 있으면 그 낱말을 사용.
    폴백: 캐릭터 이름 + 주제어 휴리스틱."""
    wp = story.get("activity_sheet", {}).get("wordplay", {})
    ci = wp.get("consonant_items") if isinstance(wp, dict) else None
    if isinstance(ci, list):
        v21 = [it for it in ci if isinstance(it, dict) and (it.get("word") or "").strip()]
        if len(v21) >= 3:
            return [{"consonants": to_consonants(it["word"].strip()),
                     "hint": (it.get("hint") or "").strip(), "answer": it["word"].strip()}
                    for it in v21[:4]]
    cw = wp.get("consonant_words") if isinstance(wp, dict) else None
    if isinstance(cw, list):
        v2_words = [w.strip() for w in cw if isinstance(w, str) and w.strip()]
        if len(v2_words) >= 3:
            return [{"consonants": to_consonants(w), "hint": "", "answer": w}
                    for w in v2_words[:5]]

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
    """감정을 느끼는 장면 추출.
    v2.1: activity_sheet.mood_items({speaker,situation,choices,answer}) — 인물·상황이 명시된
          장면만 (교훈문·배경 묘사로 기분을 고르게 하던 결함 제거)."""
    mi = story.get("activity_sheet", {}).get("mood_items")
    if isinstance(mi, list) and mi:
        out = []
        for it in mi:
            if not isinstance(it, dict):
                continue
            spk = (it.get("speaker") or "").strip()
            sit = (it.get("situation") or "").strip()
            ch = [c for c in (it.get("choices") or []) if isinstance(c, str)]
            if spk and sit and len(ch) >= 3:
                out.append({"speaker": spk, "situation": sit, "choices": ch[:4],
                            "answer": (it.get("answer") or "").strip()})
        if len(out) >= 2:
            return out[:3]
    EMOTIONS = ["기쁨", "슬픔", "설렘", "걱정", "용기", "뿌듯함", "외로움", "따뜻함", "놀람", "부끄러움"]
    slides = story.get("slides", [])
    n1, n2 = _main_names(story)
    scenes = []
    emotion_compositions = {"close_up_face", "medium_two_shot", "realization"}
    for s in slides[1:]:
        if s.get("composition") in emotion_compositions or s.get("color_mood") in ("realization", "tense_worried", "happy_ending"):
            # 첫 나레이터 세그먼트에서 '완결된 문장' 사용 (중간 잘림 방지)
            # 너무 짧으면 다음 문장까지 병합 — 감정 판단 근거 확보
            sent = ""
            for seg in s.get("tts_segments", []):
                if seg.get("speaker") == "narrator":
                    t = seg.get("text", "").strip()
                    sentences = re.findall(r"[^.!?]*[.!?]", t)
                    acc = ""
                    for piece in sentences:
                        acc = (acc + " " + piece.strip()).strip()
                        if len(acc) >= 14:
                            break
                    if 14 <= len(acc) <= 50:
                        sent = acc
                    break
            if not sent:
                continue
            scenes.append({
                "situation": sent,
                "choices": EMOTIONS[:4],
            })
        if len(scenes) >= 3:
            break
    if not scenes:
        j1 = "가" if (n1 and (ord(n1[-1]) - 0xAC00) % 28 == 0) else "이"
        scenes = [{"situation": f"{n1}{j1} 혼자 있을 때", "choices": EMOTIONS[:4]},
                  {"situation": f"{n1}{j1} 친구를 만났을 때", "choices": EMOTIONS[1:5]}]
    return scenes[:3]


def _speaker_name_map(story: dict) -> dict:
    """child_boy/child_girl 각각이 어느 주인공(n1/n2)인지 추론.
    스토리마다 성별 캐스팅이 달라 child_boy=main_1 고정 가정은 틀림.
    화자가 대사에서 '상대 이름'을 부르면 화자는 그 반대편이라는 단서로 판별."""
    n1, n2 = _main_names(story)
    votes = {"child_boy": {n1: 0, n2: 0}, "child_girl": {n1: 0, n2: 0}}
    for s in story.get("slides", []):
        for seg in s.get("tts_segments", []):
            sp = seg.get("speaker", "")
            if sp not in ("child_boy", "child_girl"):
                continue
            t = seg.get("text", "")
            if n1 and n2 and n1 in t and n2 not in t:
                votes[sp][n2] += 1   # n1을 부르면 화자는 n2
            elif n2 and n1 and n2 in t and n1 not in t:
                votes[sp][n1] += 1
    res = {}
    for sp in ("child_boy", "child_girl"):
        v = votes[sp]
        res[sp] = n1 if v[n1] > v[n2] else (n2 if v[n2] > v[n1] else None)
    # 미결정/충돌 시 기본 분리(child_boy=n1, child_girl=n2)
    if res["child_boy"] == res["child_girl"]:
        res["child_boy"], res["child_girl"] = n1, n2
    else:
        res["child_boy"] = res["child_boy"] or (n2 if res["child_girl"] == n1 else n1)
        res["child_girl"] = res["child_girl"] or (n2 if res["child_boy"] == n1 else n1)
    return res


def _speaker_vote_confident(story: dict) -> bool:
    """_speaker_name_map 투표에 실제 근거(누군가 상대 이름을 부름)가 있었는지.
    0:0(근거 없음)이면 화자 표기를 신뢰할 수 없음(W2)."""
    n1, n2 = _main_names(story)
    for s in story.get("slides", []):
        for seg in s.get("tts_segments", []):
            sp = seg.get("speaker", "")
            if sp not in ("child_boy", "child_girl"):
                continue
            t = seg.get("text", "")
            if n1 and n2 and ((n1 in t and n2 not in t) or (n2 in t and n1 not in t)):
                return True
    return False


def _find_teacher_name(story: dict) -> str:
    """teacher 화자의 실제 이름을 supporting 첫 값이 아니라
    role/name/species에 어른 키워드가 든 항목 우선으로 탐색(W2)."""
    sup = _chars(story).get("supporting", {})
    ADULT_KW = ["선생님", "할아버지", "할머니", "아줌마", "아저씨", "박사",
                "엄마", "아빠", "이모", "삼촌", "부엉", "곰", "owl", "bear"]
    if isinstance(sup, dict):
        # 1순위: 어른 키워드가 이름/역할에 든 항목
        for v in sup.values():
            if not (isinstance(v, dict) and v.get("name")):
                continue
            hay = " ".join(str(v.get(k, "")) for k in ("name", "role", "species"))
            if any(kw in hay for kw in ADULT_KW):
                return v["name"]
        # 2순위: 아무 이름
        for v in sup.values():
            if isinstance(v, dict) and v.get("name"):
                return v["name"]
    return "선생님"


# 감정 표현(emotion 필드)에서 뽑아낼 핵심 감정어 사전 (W4 힌트용)
_EMOTION_WORDS = [
    "호기심", "놀라움", "설렘", "신나", "흥분", "당황", "억울", "화난", "화가",
    "미안", "반성", "막막", "무서", "용감", "응원", "감동", "뿌듯", "슬픔", "슬프",
    "기쁨", "즐거", "걱정", "따뜻", "다정", "울먹", "속상", "부끄", "자랑", "명랑",
]


def _emotion_keyword(emo: str) -> str:
    """emotion 서술 문구에서 핵심 감정어 1개 추출.
    예: '억울하고 화난 아이의 목소리' → '억울한', '눈이 동그래져 호기심 가득한' → '호기심 어린'."""
    if not emo:
        return ""
    for kw in _EMOTION_WORDS:
        if kw in emo:
            # 자연스러운 관형형으로 변환
            _SUFFIX = {"화난": "화난", "화가": "화난", "슬프": "슬픈", "즐거": "즐거운",
                       "따뜻": "따뜻한", "무서": "무서운", "억울": "억울한", "막막": "막막한",
                       "속상": "속상한", "부끄": "부끄러운", "울먹": "울먹이는",
                       "신나": "신나는", "흥분": "흥분된", "명랑": "명랑한", "다정": "다정한"}
            if kw in _SUFFIX:
                return _SUFFIX[kw]
            # '호기심/놀라움/설렘/감동...' 등 명사형은 '~ 가득한' / '~ 어린'
            if kw in ("호기심", "놀라움", "감동", "설렘"):
                return kw + " 가득한"
            return kw + "한" if kw[-1] not in "함운은는한" else kw
    return ""


def get_speech_bubbles(story: dict) -> list[dict]:
    """대화 말풍선 채우기 (주요 대화 장면).
    v2: activity_sheet.speech_bubbles({speaker,situation,hint})가 있으면 그대로 사용.
        speaker가 실명이므로 화자 추론 불필요, hint는 정답 미노출 상황·감정 힌트.
    폴백(W2): 화자 투표가 0:0(근거 없음)이면 화자 맞히기 활동으로 전환.
    폴백(W4): 힌트에 대사 전문을 노출하지 않고 감정/첫 어절만 축소 노출."""
    v2 = story.get("activity_sheet", {}).get("speech_bubbles")
    if isinstance(v2, list) and v2:
        bubbles = []
        for b in v2:
            spk = (b.get("speaker") or "").strip()
            situation = (b.get("situation") or "").strip()
            hint = (b.get("hint") or "").strip()
            if not spk or not situation:
                continue
            bubbles.append({"character": spk, "situation": situation,
                            "hint": hint, "guess": False})
        if bubbles:
            return bubbles[:3]

    n1, n2 = _main_names(story)
    name_map = _speaker_name_map(story)
    confident = _speaker_vote_confident(story)
    teacher_name = _find_teacher_name(story)
    slides = story.get("slides", [])
    bubbles = []
    used_situations = set()
    for s in slides:
        # 슬라이드당 대사 1개만 (상황문이 슬라이드 문장이라 여러 개 뽑으면 중복됨)
        for seg in s.get("tts_segments", []):
            spk = seg.get("speaker", "")
            if spk in ("child_boy", "child_girl", "teacher"):
                if spk == "teacher":
                    char = teacher_name
                    guess = False
                elif confident:
                    char = name_map.get(spk, n1)
                    guess = False
                else:
                    # W2: 근거 없는 주인공 화자 → 화자 맞히기로 활동화
                    char = "누가 말했을까요? (　　)"
                    guess = True
                text = seg.get("text", "")
                # 상황문은 완결된 첫 문장만 (중간 잘림 방지), 중복 제외
                m = re.match(r"[^.!?]*[.!?]", s.get("text", ""))
                situation = m.group(0).strip() if m and len(m.group(0)) <= 40 else ""
                if len(text) > 10 and situation not in used_situations:
                    # W4: 대사 전문 대신 감정 힌트 or 첫 어절만
                    emo = (seg.get("emotion", "") or "").strip()
                    emo_word = _emotion_keyword(emo) if emo else ""
                    if emo_word:
                        hint = f"{emo_word} 마음을 담아 말했어요"
                    elif text.strip():
                        first = text.strip().split()[0]
                        hint = f"{first}…"
                    else:
                        hint = ""
                    bubbles.append({"character": char, "situation": situation,
                                    "hint": hint, "guess": guess})
                    used_situations.add(situation)
                    break  # 이 슬라이드에서는 하나만
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


def _slide_narrator_sentence(story: dict, slide_no) -> str:
    """지정한 slide_number의 첫 완결 narrator 문장 반환 (W7 상황문 소스)."""
    if slide_no is None:
        return ""
    for s in story.get("slides", []):
        if s.get("slide_number") != slide_no:
            continue
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            t = (seg.get("text", "") or "").strip()
            m = re.match(r"[^.!?]*[.!?]", t)
            sent = m.group(0).strip() if m else t
            if 8 <= len(sent) <= 60:
                return sent
    return ""


def get_if_i_were(story: dict) -> dict:
    """'나라면' 상황문 (W7):
    - quiz question이 의문문이면 그대로 넣지 않고, 그 question의 related_slide narrator
      문장을 상황문(서술형)으로 사용.
    - related_slide가 없으면 물음표 문장은 제외하고 서술형 quiz(answer 등)만 후보로.
    """
    quiz = _quiz_qs(story)
    situation = ""
    _ACT_KEYS = ["어떻게", "왜", "무서", "용기", "기분", "마음", "이겨", "도와", "하기로"]

    # 1순위: 정서/행동형 질문 → related_slide narrator 서술문으로 변환
    for q in reversed(quiz):
        qt = (q.get("question", "") or "").strip()
        if not (10 <= len(qt) <= 70 and any(k in qt for k in _ACT_KEYS)):
            continue
        if qt.endswith("?"):
            narr = _slide_narrator_sentence(story, q.get("related_slide"))
            if narr:
                situation = narr
                break
            # related_slide 없으면 서술형 answer를 상황문으로 (물음표 문장 배제)
            ans = (q.get("answer", "") or "").strip()
            if ans and not ans.endswith("?") and 8 <= len(ans) <= 60:
                situation = ans
                break
        else:
            situation = qt  # 이미 서술형이면 그대로
            break

    if not situation:
        n1, _ = _main_names(story)
        situation = f"{n1}처럼 어렵고 무서운 일이 생긴다면?"
    return {
        "situation": situation,
        "prompt": "나라면 어떻게 했을까요? 내 생각을 써보세요!",
        "lines": 4,
    }


def get_nickname_data(story: dict) -> list[dict]:
    chars = _chars(story)
    result = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key) or {}
        if ch.get("name"):
            # 첫 절(쉼표·마침표 이전)만 사용해 문장 중간 끊김 방지.
            # 단 첫 절이 너무 짧으면(예: '친구를 잘') 쉼표를 공백으로 펴서 완결 어구를 만든다.
            raw = (ch.get("personality", "") or "").strip()
            p = re.split(r"[,.!?·]", raw)[0].strip()
            if len(p) < 6:
                p = re.sub(r"[,.!?·]", " ", raw).strip()
            if len(p) > 18:
                p = p[:18].rsplit(" ", 1)[0]
            # 마지막 어절이 목적격/주격 조사로 끝나 어색하면 제거 (예: '...친구를' → '...')
            toks = p.split()
            if len(toks) > 1 and toks[-1] and toks[-1][-1] in "를을이가와과에의도":
                p = " ".join(toks[:-1])
            result.append({"name": ch["name"], "trait": p})
    return result


def get_draw_prompt(story: dict) -> tuple[str, bool, str | None, str | None]:
    """이야기 끝부분의 '열린 질문'(상상 유도 발문)이 있으면 그리기 발문으로 사용.
    상상 단원의 핵심 활동(상상해서 표현하기)과 활동지를 직결시키는 장치.
    v2: activity_sheet.draw({prompt,field1_label,field2_label})가 있으면 라벨을 데이터로
        사용 — 발문과 기입란 라벨이 항상 일치(W6' 해결).
    Returns: (발문, is_fallback, field1_label, field2_label).
             field 라벨은 v2가 있을 때만 값이 있고, 없으면 None(휴리스틱 라벨 사용)."""
    v2 = story.get("activity_sheet", {}).get("draw")
    if isinstance(v2, dict) and (v2.get("prompt") or "").strip():
        prompt = v2["prompt"].strip()
        f1 = (v2.get("field1_label") or "").strip() or None
        f2 = (v2.get("field2_label") or "").strip() or None
        return prompt, False, f1, f2

    slides = [s for s in story.get("slides", []) if s.get("type") in ("story", "ending")]
    _KEYS = ["상상", "무엇이", "어떤", "같아", "누가", "어디로", "너라면",
             "너는", "가고 싶", "만들고 싶", "들어 있을"]
    for s in reversed(slides[-3:]):
        for seg in reversed(s.get("tts_segments", [])):
            t = seg.get("text", "").strip()
            # 물음표로 '끝나는' 문장만 추출 (느낌표 문장에 ?를 붙이는 오류 방지)
            questions = [q.strip() for q in re.findall(r"[^.!?]*\?", t)]
            cand = [q for q in questions if any(k in q for k in _KEYS) and len(q) >= 8]
            if cand:
                return cand[-1], False, None, None
    n1, n2 = _main_names(story)
    gwa = "와" if (n1 and (ord(n1[-1]) - 0xAC00) % 28 == 0) else "과"
    return f"{n1}{gwa} {n2}의 이야기에서 가장 기억에 남는 장면을 그려보세요!", True, None, None


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
    # v2.1: 정답은 원문으로 재확인한 quiz_review.answer 우선 (영상 정답이 원문과 어긋난 편 보정)
    review = {r.get("q_index"): r for r in story.get("activity_sheet", {}).get("quiz_review", []) or []
              if isinstance(r, dict)}
    answers = []
    for i, q in enumerate(qs):
        r = review.get(i) or {}
        ans = (r.get("answer") or q.get("answer", "") or "").strip()
        answers.append({"label": f"{i+1}", "ans": ans})
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


def render_fill_blank(story: dict, rng: random.Random | None = None, **_) -> tuple[str, list]:
    items = get_fill_blank_items(story)
    # 보기 상자: v2.1은 정답 + 오답(distractor)을 섞어 제시 — 보기가 곧 정답표가 되지 않게.
    #           (구 v2는 example만 있어 보기=정답이었음)
    if any(it.get("distractor") for it in items):
        examples = [it["answer"] for it in items if it.get("answer")] +                    [it["distractor"] for it in items if it.get("distractor")]
        examples = list(dict.fromkeys(examples))
        (rng or random.Random(0)).shuffle(examples)
    else:
        examples = [it.get("example", "") for it in items if it.get("example")]
    box_html = ""
    if examples:
        chips = "".join(f'<span class="fill-ex-chip">{html_mod.escape(e)}</span>' for e in examples)
        box_html = f'<div class="fill-example-box"><span class="fill-ex-label">보기</span>{chips}</div>'
    html = ""
    for i, item in enumerate(items):
        sent = html_mod.escape(item["sentence"])
        hint = item.get("hint", "")
        hint_html = f' <span class="fill-hint">힌트: {html_mod.escape(hint)}</span>' if hint else ""
        html += f'<div class="fill-item"><span class="num-badge">{i+1}</span>{sent}{hint_html}</div>'
    answers = [{"label": f"{i+1}", "ans": item.get("answer", "")} for i, item in enumerate(items)]
    return f'<div class="fill-list">{box_html}{html}</div>', answers


def render_story_recall(story: dict, **_) -> tuple[str, list]:
    """중요한 장면 3가지를 직접 써보는 활동."""
    quizzes = story.get("activity_sheet", {}).get("quiz_questions", [])
    prompts = []
    for q in quizzes[:3]:
        scene = q.get("question", "").strip()
        if scene:
            # 질문은 자르지 않고 온전히 (자르면 '...동물의 이)'처럼 비문이 됨)
            prompts.append(html_mod.escape(scene))
    # 3개 미만이면 빈 프롬프트로 채움
    while len(prompts) < 3:
        prompts.append("")

    items_html = ""
    for i, prompt in enumerate(prompts):
        # W10: 괄호·회색 이탤릭(placeholder처럼 보임) 제거 → 본문 스타일(진한 검정, 정자)
        q = f'<span class="recall-q">{prompt}</span>' if prompt else ""
        items_html += f"""<div class="recall-item">
  <div class="cq-q"><span class="num-badge">{i+1}</span>{q}</div>
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
        _jo = "으로" if last_char and 0xAC00 <= ord(last_char[-1]) <= 0xD7A3 and (ord(last_char[-1]) - 0xAC00) % 28 not in (0, 8) else "로"
        hint = f'<span class="chain-v-hint">{html_mod.escape(last_char)}{_jo} 시작하는 말</span>' if i == 0 else ""
        steps += f'<div class="chain-v-step"><div class="chain-v-arrow">↓</div><div class="chain-v-box">{hint}</div></div>'
    guide = '<div class="chain-guide">앞 낱말의 마지막 글자로 시작하는 낱말을 이어 써보세요!</div>'
    html = f'<div class="chain-v-wrap"><div class="chain-v-start">{html_mod.escape(start)}</div>{steps}</div>{guide}'
    return html, []


def render_story_sequence(story: dict, rng: random.Random, **_) -> tuple[str, list]:
    """이야기 순서 배열: 사건 문장 3개를 섞어서 번호 쓰기.
    v2: activity_sheet.sequence_items({label,text,order})가 있으면 그대로 사용.
    폴백: 나레이터 문장 3개(초·중·후반)를 섞어서 번호 쓰기."""
    _CIRCLED = ["Ⓐ", "Ⓑ", "Ⓒ", "Ⓓ", "Ⓔ"]

    # 데이터 라벨(A/B/C)을 원문자(Ⓐ/Ⓑ/Ⓒ)로 표시 — 학생이 쓸 순서 번호(1·2·3)와
    # 시각적으로 구분되도록(라벨=항목 이름, 번호=정답). 정답키도 같은 원문자로 통일.
    _CIRCLE_MAP = {"A": "Ⓐ", "B": "Ⓑ", "C": "Ⓒ", "D": "Ⓓ", "E": "Ⓔ"}

    v2 = story.get("activity_sheet", {}).get("sequence_items")
    if isinstance(v2, list) and len(v2) >= 3:
        # order 기준 정답 순서. 표시 순서는 셔플하되 label은 데이터 그대로 유지.
        seq = [it for it in v2 if (it.get("text") or "").strip()][:5]
        if len(seq) >= 3:
            display = seq.copy()
            # 표시 순서가 정답 순서(order 1,2,3)와 같으면 문제가 안 됨 → 다시 섞기
            for _ in range(30):
                rng.shuffle(display)
                if [s.get("order") for s in display] != sorted(s.get("order") for s in display):
                    break
            rows = ""
            answers = []
            for it in display:
                raw = str(it.get("label", "")).strip().upper() or "?"
                label = _CIRCLE_MAP.get(raw, raw)
                order = it.get("order", "")
                rows += f"""<div class="seq-item">
  <div class="seq-label">{html_mod.escape(label)}</div>
  <div class="seq-text">{html_mod.escape((it.get('text') or '').strip())}</div>
  <div class="seq-circle"></div>
</div>"""
                answers.append({"label": label, "ans": str(order)})
            guide = '<div class="seq-guide">문장 오른쪽 ○ 안에, 일이 일어난 순서대로 번호(1·2·3)를 써보세요! (Ⓐ·Ⓑ·Ⓒ는 문장 이름이에요)</div>'
            return f'<div class="seq-list">{rows}</div>{guide}', answers

    # 시청자 안내 멘트는 사건이 아니므로 제외
    _SKIP = ["여러분", "보세요", "볼까요", "해 봐", "해봐", "상상해 봐", "만나요", "찾아 직접"]
    narr = []  # 이야기 시간 순서 그대로 수집
    for s in story.get("slides", []):
        if s.get("type") == "ending":
            continue
        for seg in s.get("tts_segments", []):
            if seg.get("speaker") != "narrator":
                continue
            text = seg.get("text", "").strip()
            if 12 <= len(text) <= 40 and text not in narr \
                    and not any(k in text for k in _SKIP):
                narr.append(text)
    if len(narr) >= 3:
        # 초반·중반·후반에서 하나씩 — 시간 순서 보존 (events가 곧 정답 순서)
        events = [narr[0], narr[len(narr) // 2], narr[-1]]
    else:
        events = narr + [q.get("question", "")[:38] for q in _quiz_qs(story) if q.get("question")]
        events = events[:3]
    correct_order = list(range(1, len(events) + 1))
    # 섞어서 출력 (순서 정답은 숨김 — 아이가 직접 번호 기입)
    display_order = list(range(len(events)))
    for _ in range(30):
        rng.shuffle(display_order)
        if display_order != sorted(display_order):
            break
    # W3: 각 항목에 Ⓐ Ⓑ Ⓒ 라벨 표시 → 정답키('A. 2')와 대조 가능
    _CIRCLED = ["Ⓐ", "Ⓑ", "Ⓒ", "Ⓓ", "Ⓔ"]
    rows = ""
    answers = []
    for display_i, orig_i in enumerate(display_order):
        label = _CIRCLED[display_i] if display_i < len(_CIRCLED) else chr(65 + display_i)
        # W11: 네모 칸 → 번호 쓰기용 원형 칸(seq-circle)
        rows += f"""<div class="seq-item">
  <div class="seq-label">{label}</div>
  <div class="seq-text">{html_mod.escape(events[orig_i])}</div>
  <div class="seq-circle"></div>
</div>"""
        answers.append({"label": chr(65 + display_i), "ans": str(orig_i + 1)})
    guide = '<div class="seq-guide">일이 일어난 순서대로 ○ 안에 번호(1·2·3)를 써보세요!</div>'
    return f'<div class="seq-list">{rows}</div>{guide}', answers


def render_syllable_order(story: dict, rng: random.Random, primary: str, accent: str, **_) -> tuple[str, list]:
    """글자 순서 맞히기: 이야기 핵심 단어의 글자를 섞어서 제시.
    - 같은 글자로만 된 낱말(토토 등)은 섞어도 그대로라 제외
    - 섞은 결과가 원래 낱말과 같으면 다시 섞기 (2글자 낱말 대비)"""
    def _clean(w: str) -> str:
        """W5: 비한글 문자(구두점·공백·영문·숫자) 제거 후 한글 음절만 남김."""
        return "".join(c for c in (w or "") if 0xAC00 <= ord(c) <= 0xD7A3)

    # v2: activity_sheet.wordplay.anagram_words가 있으면 그 낱말을 사용.
    wp = story.get("activity_sheet", {}).get("wordplay", {})
    aw = wp.get("anagram_words") if isinstance(wp, dict) else None
    v2_words = []
    if isinstance(aw, list):
        for w in aw:
            c = _clean(w) if isinstance(w, str) else ""
            if 3 <= len(c) <= 4 and len(set(c)) >= 2 and c not in v2_words:
                v2_words.append(c)

    chars = _chars(story)
    # W9: 캐릭터 이름은 최대 1문항만 (애너그램이 이름 위주로 쏠리는 문제 방지)
    name_words = []
    for key in ("main_1", "main_2"):
        n = _clean((chars.get(key) or {}).get("name", ""))
        # W5+W9: 3글자 미만 낱말 제외(2글자 애너그램은 너무 쉬움)
        if 3 <= len(n) <= 4 and len(set(n)) >= 2:
            name_words.append(n)
    words = name_words[:1]  # 이름은 1개만

    # 추가 단어 — story title에서 추출 (비한글 제거 후)
    title = story.get("meta", {}).get("story_title", "")
    for part in re.split(r"[\s!?의와과]", title):
        p = _clean(part)
        if 3 <= len(p) <= 4 and p not in words and len(set(p)) >= 2:
            words.append(p)
    # 기본 단어 보충 (3글자 이상)
    for w in ["이야기", "골고루", "무지개", "반짝반짝", "두근두근"]:
        if len(words) >= 5:
            break
        w = _clean(w)
        if 3 <= len(w) <= 4 and w not in words and len(set(w)) >= 2:
            words.append(w)
    # v2 anagram_words가 충분하면 그것으로 대체(휴리스틱보다 이야기 핵심어에 밀착)
    if len(v2_words) >= 3:
        words = v2_words[:4]
    rng.shuffle(words)
    words = words[:4]

    items_html = ""
    answers = []
    for i, word in enumerate(words):
        syllables = list(word)
        for _try in range(20):
            rng.shuffle(syllables)
            if "".join(syllables) != word:
                break
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

    guide = '<div class="chain-guide">글자를 바르게 놓아 낱말을 만들어 보세요!</div>'
    return f'<div class="syl-list">{items_html}</div>{guide}', answers


def render_emotion_card(story: dict, secondary: str, **_) -> tuple[str, list]:
    scenes = get_emotion_scenes(story)
    html = ""
    for i, sc in enumerate(scenes):
        q = html_mod.escape(sc["situation"])
        if sc.get("speaker"):
            q = f'<b>{html_mod.escape(sc["speaker"])}</b> — {q} <span class="emotion-ask">{html_mod.escape(sc["speaker"])}의 기분은?</span>'

        chips = "".join(
            f'<label class="emotion-chip"><input type="checkbox"><span>{html_mod.escape(e)}</span></label>'
            for e in sc["choices"]
        )
        html += f"""<div class="emotion-item">
  <div class="emotion-q"><span class="num-badge">{i+1}</span>{q}</div>
  <div class="emotion-chips">{chips}</div>
</div>"""
    answers = [{"label": f"{i+1}", "ans": sc["answer"]} for i, sc in enumerate(scenes) if sc.get("answer")]
    guide = '<div class="seq-guide">알맞은 기분에 ○표 해 보세요!</div>' if answers else ""
    return f'<div class="emotion-list">{html}</div>{guide}', answers


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
</div>"""  # W4: hint는 대사 전문이 아닌 감정/첫 어절 축약본
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
    prompt, is_fallback, v2_f1, v2_f2 = get_draw_prompt(story)
    n1, _n2 = _main_names(story)

    # 주인공 얼굴 + 말풍선 발문 (읽기 부담을 줄이고 캐릭터가 직접 묻는 형식)
    face_html = '<div class="draw-coach-emoji">🗣️</div>'
    if out_dir is not None:
        b64 = sheet_face_b64(out_dir, "main_1", 80)
        if b64:
            face_html = (f'<img src="data:image/png;base64,{b64}" alt="{html_mod.escape(n1)}" '
                         f'style="width:40px;height:40px;flex-shrink:0;">')

    # W6': v2 draw.field1_label/field2_label이 있으면 발문 주제와 일치하는 라벨을
    #   데이터로 사용 (그리기 지시-기입란 불일치 결함 소멸).
    #   없으면 기존 휴리스틱: 상상/창작형 → 이름 짓기, 폴백형 → 기억에 남는 장면.
    if v2_f1 or v2_f2:
        label1 = v2_f1 or "🏷️ 이름을 지어 주세요"
        label2 = v2_f2 or "💬 소개 한 줄"
        placeholder = "여기에 그려요! ✏️"
    elif is_fallback:
        label1, label2 = "🖼️ 어떤 장면인가요?", "💬 왜 기억에 남았나요?"
        placeholder = "여기에 기억에 남는 장면을 그려요! ✏️"
    else:
        label1, label2 = "🏷️ 이름을 지어 주세요", "💬 소개 한 줄 (어디에 살까? 무엇을 잘할까?)"
        placeholder = "여기에 상상해서 그려요! ✏️"

    # 그림틀 모양: v2.1 draw.frame (기본 둥근 사각). 알 모양은 알 차시에서만.
    frame = (story.get("activity_sheet", {}).get("draw", {}) or {}).get("frame") or "rect"
    if frame not in ("rect", "egg", "circle", "window", "plate"):
        frame = "rect"
    if frame == "window" and "창" not in prompt:
        frame = "rect"   # 4칸 창문 틀은 '창문' 발문에만 (한 장면 그리기에 4칸 틀이 붙던 결함)
    window_bars = '<div class="win-bar-v"></div><div class="win-bar-h"></div>' if frame == "window" else ""

    html = f"""<div class="draw-coach">
  {face_html}
  <div class="draw-bubble"><b>{html_mod.escape(n1)}</b>: “{html_mod.escape(prompt)}”</div>
</div>
<div class="imagine-row">
  <div class="imagine-frame frame-{frame}">{window_bars}<span class="draw-placeholder">{placeholder}</span></div>
  <div class="imagine-side">
    <div class="imagine-label">{label1}</div>
    <div class="draw-line"></div>
    <div class="imagine-label">{label2}</div>
    <div class="draw-line"></div>
    <div class="draw-line"></div>
    <div class="imagine-label">🗣️ 내 그림을 소개해요</div>
    <div class="intro-sentence">나는 <span class="intro-blank"></span> 을/를 그렸어요.</div>
    <div class="intro-sentence">왜냐하면 <span class="intro-blank long"></span></div>
    <div class="draw-line"></div>
    <div class="imagine-label">⭐ 오늘 활동 별점 (색칠해요)</div>
    <div class="star-row">☆ ☆ ☆ ☆ ☆</div>
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
    return f'<div class="trace-wrap trace-rows">{rows}</div>{guide}'


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
    """페이지1 남는 공간을 채우는 보너스 활동 HTML.
    ※ 그리기형 필러는 남는 공간이 애매하면 잘리거나 그리기 칸이 너무 좁아지는
    문제가 있어 사용하지 않음 — 그리기는 페이지2의 대형 상상 프레임이 전담.
    낱말 따라쓰기는 행 단위라 공간에 맞춰 자연스럽게 접혀 잘림이 없음."""
    icon, title = "✍️", "낱말을 따라 써요!"
    content = render_filler_letter_trace(story, primary, accent)

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


ANSWER_TAG = {
    "comprehension_quiz": "내용 문답", "ox_quiz": "OX", "fill_blank": "빈칸",
    "story_sequence": "순서", "syllable_order": "글자 놓기", "consonant_quiz": "초성",
    "emotion_card": "기분", "matching": "선 잇기",
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
        # 예전엔 '렌더링 오류' div로 조용히 삼켜 깨진 활동지가 배포됨 → 실패로 올린다
        raise RuntimeError(f"활동 렌더 실패 [{act_id}]: {e}") from e


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

    # v2.1 cast: 본문에 실제로 이름이 나오는 인물만 카드로 (이야기에 없는 '다람 코치'·
    # '엄마 부엉이' 등이 소개되던 결함). meta에 없는 cast 인물은 이름 카드로 추가.
    cast = [c for c in story.get("activity_sheet", {}).get("cast", []) or [] if isinstance(c, str)]
    if cast:
        char_list = [(k, ch) for k, ch in char_list if ch.get("name") in cast]
        have = {ch.get("name") for _, ch in char_list}
        for nm in cast:
            if nm not in have:
                char_list.append((f"cast_{nm}", {"name": nm, "personality": "", "species": ""}))
        char_list = char_list[:5]

    cards = []
    used_slides: set = set()
    for key, ch in char_list:
        name = html_mod.escape(ch.get("name", ""))
        desc = re.split(r"[,.·(]", ch.get("personality", "") or "")[0].strip()
        if len(desc) > 12:
            # 잘라 붙이면 '모양 나라에서 온 살아'처럼 끊긴 말이 됨 → 긴 설명은 싣지 않음(종만 표시)
            desc = ""
        # species 우선, 없으면 personality/role에서 종 복원 (카드에 종이 잘려 사라지는 문제 방지)
        species = ch.get("species", "") or guess_species(ch.get("personality", ""), ch.get("role", ""))

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
.char-name {{ font-size: 13px; font-weight: 900; color: #1a2e40; word-break: keep-all; }}
.char-desc {{ font-size: 10px; color: #5a6a88; margin-top: 1px; line-height: 1.4; word-break: keep-all; }}

/* 2행 (위아래 쌓기) - 활동은 자연 높이, 필러가 남는 공간 채움 */
/* 페이지1: 필러 없이 두 활동이 남는 공간을 자연스럽게 나눠 가짐 (잘림 원천 차단) */
.two-col {{ display: flex; flex-direction: column; gap: 8px; flex: 0 1 auto; min-height: 0; overflow: hidden; }}
/* 1쪽 하단 공백 흡수: 남는 높이만큼 늘고, 모자라면 줄 영역부터 줄어듦 */
.reflect-act {{ flex: 1 1 0px; min-height: 96px; overflow: hidden; }}
.reflect-body {{ display: flex; flex-direction: column; gap: 4px; flex: 1 1 auto; min-height: 0; }}
.reflect-lines {{ flex: 1 1 0px; min-height: 0; overflow: hidden; display: flex; flex-direction: column; gap: 2px; padding-top: 4px; }}
.reflect-lines .cq-line {{ flex-shrink: 0; }}
.reflect-why {{ flex: 1 1 0px; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }}
/* W12: 활동 카드가 콘텐츠보다 커도 상단에 큰 빈 공백이 생기지 않도록
   space-evenly(콘텐츠를 세로 중앙으로 밀어 상단 공백 유발) → flex-start(상단 정렬).
   카드 자체는 콘텐츠에 맞춰 높이를 갖고, 남는 공간은 카드 사이 gap이 흡수. */
.two-col > .act {{ flex: 0 1 auto; min-height: 0; }}
.two-col > .act .act-body {{ display: flex; flex-direction: column; justify-content: flex-start; gap: 6px; flex: 0 1 auto; min-height: 0; }}

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
.recall-q {{ font-size: {cq_q_fs}px; font-weight: 700; color: #222; font-style: normal; line-height: 1.5; }}
.ox-list {{ display: grid; grid-template-columns: 1fr; gap: 7px; }}
.ox-item {{ display: flex; align-items: center; gap: 10px; background: linear-gradient(135deg, #f5f8ff, #eef2ff); border: 1.5px solid #cdd6f4; border-radius: 10px; padding: 9px 11px; }}
.ox-circles {{ display: flex; gap: 7px; flex-shrink: 0; }}
.ox-circle {{ width: 30px; height: 30px; border-radius: 50%; border: 2.5px solid {primary}; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 14px; color: {primary}; }}
.ox-q {{ font-size: {ox_q_fs}px; line-height: 1.55; color: #333; }}
.fill-list {{ display: flex; flex-direction: column; gap: 6px; }}
.fill-item {{ background: #fffdf2; border: 1.5px solid {accent}50; border-radius: 8px; padding: 7px 11px; font-size: {fill_fs}px; line-height: 1.9; }}
.fill-hint {{ font-size: 11px; color: #aaa; font-style: italic; margin-left: 6px; }}
.fill-example-box {{ display: flex; align-items: center; flex-wrap: wrap; gap: 6px; background: {secondary}10; border: 1.5px dashed {secondary}70; border-radius: 8px; padding: 5px 10px; margin-bottom: 3px; }}
.fill-ex-label {{ font-size: 10px; font-weight: 800; color: {secondary}; background: #fff; border-radius: 6px; padding: 1px 7px; }}
.fill-ex-chip {{ font-size: 13px; font-weight: 700; color: #444; background: #fff; border: 1px solid {secondary}40; border-radius: 6px; padding: 2px 9px; }}

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
.seq-label {{ font-size: 15px; font-weight: 900; color: {primary}; flex-shrink: 0; width: 22px; text-align: center; }}
.seq-num {{ width: 26px; height: 26px; border: 2px solid {primary}60; border-radius: 6px; flex-shrink: 0; background: #fff; }}
.seq-circle {{ width: 28px; height: 28px; border: 2px solid {primary}; border-radius: 50%; flex-shrink: 0; background: #fff; margin-left: auto; }}
.seq-text {{ font-size: 13px; line-height: 1.5; color: #333; flex: 1; }}
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
.filler-content {{ display: flex; gap: 8px; flex: 1 1 auto; min-height: 0; align-items: flex-start; overflow: hidden; }}
.filler-ref {{ flex: 0 0 auto; width: 30%; display: flex; flex-direction: column; gap: 3px; }}
.filler-ref img {{ width: 100%; max-height: 110px; object-fit: cover; border-radius: 8px; border: 1.5px solid #e0e4f0; display: block; }}
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
.trace-row {{ display: flex; align-items: center; gap: 6px; break-inside: avoid; }}
.trace-rows, .filler-act-body {{ overflow: hidden; min-height: 0; }}
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
  border-radius: 18px; position: relative;
  background: #fffdf8; display: flex; align-items: center; justify-content: center; }}
/* 그림틀 모양 (activity_sheet.draw.frame) — 알 모양은 알 차시 전용 */
.imagine-frame.frame-egg {{ border-radius: 48% 48% 46% 46% / 58% 58% 40% 40%; }}
.imagine-frame.frame-circle {{ border-radius: 50%; aspect-ratio: 1 / 1; flex: 0 1 auto; align-self: center; width: 58%; min-height: 0; }}
.imagine-frame.frame-plate {{ border-radius: 38% / 30%; }}
.imagine-frame.frame-window {{ border-style: solid; border-width: 5px; border-radius: 14px 14px 6px 6px; }}
.win-bar-v {{ position: absolute; left: 50%; top: 0; bottom: 0; border-left: 4px solid {accent}; }}
.win-bar-h {{ position: absolute; top: 50%; left: 0; right: 0; border-top: 4px solid {accent}; }}
.intro-sentence {{ font-size: 12px; color: #333; display: flex; align-items: flex-end; gap: 3px; margin-top: 4px; white-space: nowrap; }}
.intro-blank {{ display: inline-block; flex: 0 0 70px; border-bottom: 1.5px solid {primary}80; height: 18px; }}
.intro-blank.long {{ flex: 1 1 auto; }}
.star-row {{ font-size: 22px; color: {accent}; letter-spacing: 4px; text-align: center; }}
.emotion-ask {{ color: {primary}; font-weight: 700; font-size: 12px; margin-left: 4px; }}
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

/* 정답 키 (W8: 마지막 페이지 최하단에 거꾸로 인쇄 — 아이가 다 풀고 뒤집어 확인) */
.answer-key {{ margin-top: auto; padding: 5px 10px; flex-shrink: 0; border: 1.5px dashed {primary}30; border-radius: 8px; background: {primary}04; transform: rotate(180deg); }}
.ak-notice {{ font-size: 8px; color: {primary}70; text-align: center; margin-bottom: 2px; font-weight: 700; }}
.ak-title {{ font-size: 8px; font-weight: 700; color: #ccc; letter-spacing: 2px; margin-bottom: 2px; text-align: center; }}
.ak-body {{ font-size: 9px; color: #999; line-height: 1.6; }}
.ak-body b {{ color: #888; }}
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
    # 교과 정보 기본값(2학년·국어) 폐지 — main()에서 누락 시 렌더 중단 (약속 10편 오표기 사고)
    grade = meta.get("grade", "")
    subject = meta.get("subject", "")
    series = meta.get("series", "")

    palette = meta.get("color_palette", {})
    primary   = palette.get("primary", "#4A90D9")
    secondary = palette.get("secondary", "#7EC8A0")
    accent    = palette.get("accent", "#FFC53D")

    css = build_css(primary, secondary, accent, grade if isinstance(grade, int) else 2)
    chars = meta.get("characters", {})
    char_cards_html = render_char_cards_html(chars, story, out_dir, primary, secondary, accent)

    seed_used = selection["seed_used"]
    rng = random.Random(seed_used)

    # 활동 렌더링
    p1l_html, p1l_ans = build_act_html(selection["p1_left"],  story, rng, primary, secondary, accent)
    p1r_html, p1r_ans = build_act_html(selection["p1_right"], story, rng, primary, secondary, accent)
    p2t_html, p2t_ans = build_act_html(selection["p2_top"],   story, rng, primary, secondary, accent)
    p2b_html, _       = build_act_html(selection["p2_bottom"], story, rng, primary, secondary, accent, is_drawing=True, out_dir=out_dir)

    # 페이지1 필러 제거 — 두 활동이 flex로 페이지를 채움 (잘림·빈 박스 원천 차단)
    filler_html = ""

    # 정답 — 활동별로 묶어 표기 (서로 다른 활동의 1·2·3이 이어져 헷갈리던 결함)
    groups = []
    for act_id, ans in ((selection["p1_left"], p1l_ans), (selection["p1_right"], p1r_ans),
                        (selection["p2_top"], p2t_ans)):
        parts = [f"{a['label']}. {html_mod.escape(str(a['ans']))}" for a in ans if a.get("ans")]
        if parts:
            short = ANSWER_TAG.get(act_id, ACTIVITY_POOL.get(act_id, {}).get("title", act_id))
            note = " (예시답)" if act_id == "comprehension_quiz" else ""
            groups.append(f"<b>[{short}{note}]</b> " + " · ".join(parts))
    answers_html = "<br>".join(groups) if groups else "정답이 따로 없는 활동이에요. 자유롭게 써요!"
    ak_note = (" (문답은 예시답이에요 — 비슷한 뜻이면 정답!)"
               if "comprehension_quiz" in (selection["p1_left"], selection["p1_right"], selection["p2_top"]) else "")

    # 1쪽 하단 공백 채우기: 생각 나누기 카드 (남는 높이를 흡수, 모자라면 줄 수만 줄어듦)
    # 약속 단원은 '나의 약속' 문장으로 차시 활동(실천 약속 정하기)과 연결
    if series == "약속":
        second = '<div class="intro-sentence">이야기 속 친구들처럼 나도 약속해요: 나는 <span class="intro-blank long"></span></div>'
        why = "그 약속을 지키면 무엇이 좋아질까요?"
    else:
        second = '<div class="intro-sentence">이야기를 읽고 나는 <span class="intro-blank"></span> 마음이 들었어요.</div>'
        why = "왜 그렇게 생각했는지 써 보세요."
    lines = "".join('<div class="cq-line"></div>' for _ in range(12))
    reflect_html = f"""<div class="act c-purple reflect-act">
  <div class="act-title">💭 이야기를 읽고 생각을 나눠요!</div>
  <div class="reflect-body">
    <div class="intro-sentence">이 이야기에서 가장 기억에 남는 장면은 <span class="intro-blank long"></span> 장면이에요.</div>
    {second}
    <div class="reflect-why">
      <div class="imagine-label">{why}</div>
      <div class="reflect-lines">{lines}</div>
    </div>
  </div>
</div>"""

    # 배지
    grade_badge = f'<span class="badge">초등 {grade}학년</span>' if grade != "" else ""
    subject_badge = f'<span class="badge">{html_mod.escape(subject)}</span>' if subject else ""
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
  </div>
  {reflect_html}
  <!-- seed: {seed_used} -->

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
    <div class="ak-notice">정답은 거꾸로 있어요! 다 풀고 확인해요 😊{ak_note}</div>
    <div class="ak-title">정 &nbsp; 답</div>
    <div class="ak-body">{answers_html}</div>
  </div>

</div>

<script>
document.querySelectorAll('.reflect-why').forEach(function (w) {{
  var l = w.querySelector('.reflect-lines');
  if (!l || l.clientHeight < 60) {{ w.style.display = 'none'; }}
}});
</script>
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
    parser.add_argument("--allow-heuristic", action="store_true",
                        help="activity_sheet v2.1 없이 구 휴리스틱으로 렌더 (배포용 금지)")
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

    meta = story.get("meta", {})
    # 교과 정보 필수 (no_textbook 편 제외) — 기본값으로 '2학년·국어'가 찍히던 사고 방지
    if meta.get("language", "ko") == "ko" and not meta.get("no_textbook"):
        missing = [k for k in ("grade", "subject", "series", "unit_title") if not meta.get(k)]
        if missing:
            print(f"[ERROR] story.json meta에 교과 정보 없음: {missing}\n"
                  f"  → meta를 채우거나 교과 무관 편이면 meta.no_textbook=true", file=sys.stderr)
            sys.exit(2)
    if not has_v21(story) and not args.allow_heuristic:
        print(f"[ERROR] activity_sheet v2.1 없음 → 먼저 실행: python gen_activity_v2.py --dir {out_dir}\n"
              f"  (구 휴리스틱 렌더는 --allow-heuristic, 배포용 금지)", file=sys.stderr)
        sys.exit(3)

    grade = meta.get("grade", 2)
    selection = select_activities(grade, seed=args.seed, story=story)

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

    # 렌더 기록 — 07a·배포 동기화(_resync_worksheets.py)가 이 md5로 '검사한 파일 = 올릴 파일'을 확인
    manifest = {
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "seed": selection["seed_used"],
        "activities": {k: selection[k] for k in ("p1_left", "p1_right", "p2_top", "p2_bottom")},
        "schema": story.get("activity_sheet", {}).get("schema"),
        "pdf_md5": hashlib.md5(pdf_path.read_bytes()).hexdigest() if pdf_ok else None,
    }
    (out_dir / "worksheet_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

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
