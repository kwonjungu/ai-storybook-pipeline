#!/usr/bin/env python3
"""
03_generate_tts.py — TTS 음성 생성 + timing.json 생성

기본 엔진: Google Gemini TTS (전 언어, 화자별 보이스+페르소나 지시)
  한국어 대안: Typecast API (--engine typecast, TYPECAST_API_KEY 필요)

참고: Supertone API는 2026-08-31 서비스 종료로 제거됨.

사용법:
  python 03_generate_tts.py --ep 1                   # 한국어 (Gemini TTS)
  python 03_generate_tts.py --dir output/id01        # 인도네시아어 (자동 감지)
  python 03_generate_tts.py --ep 1 --engine typecast # Typecast 사용 시
"""

import argparse
import base64
import io
import json
import os
import random
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Gemini TTS 설정 (인도네시아어 등) ──────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
# 프리뷰 모델 순차 폴백 체인 (앞에서부터 시도)
GEMINI_TTS_FALLBACK_MODELS = [
    GEMINI_TTS_MODEL,
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-preview-tts",
]
GEMINI_TTS_SAMPLE_RATE = 24000  # PCM 24kHz, 16-bit, mono

# 기본 보이스 매핑 (story.json의 meta.gemini_voices로 덮어씌울 수 있음)
# voice_name: Gemini TTS 프리빌트 보이스 / style: 화자 페르소나 (읽기 지시문에 결합)
# ★ 시그니처 명확화: 음색 대비 최대 조합 + 음높이·발성 특징을 페르소나에 명시
GEMINI_VOICE_DEFAULTS = {
    "narrator":     {"voice_name": "Sulafat",  "speed": 0.95,
                     "style": "따뜻하고 포근한 어른 여성 동화 구연가, 중간 음높이로 부드럽고 차분하게"},
    "child_girl":   {"voice_name": "Leda",     "speed": 1.02,
                     "style": "높고 가늘고 귀여운 어린 여자아이 목소리, 통통 튀며 밝게"},
    "child_boy":    {"voice_name": "Puck",     "speed": 1.05,
                     "style": "카랑카랑하고 씩씩한 어린 남자아이 목소리, 에너지 넘치고 빠릿하게"},
    "teacher":      {"voice_name": "Vindemiatrix", "speed": 0.9,
                     "style": "부드럽고 신뢰감 있는 선생님 목소리, 또박또박 친절하게"},
    "adult_female": {"voice_name": "Gacrux",   "speed": 0.93,
                     "style": "낮고 그윽한 어른 여성 엄마 목소리, 푸근하고 느긋하게"},
    "adult_male":   {"voice_name": "Algenib",  "speed": 0.92,
                     "style": "굵고 걸걸한 저음의 아저씨 목소리, 듬직하고 호탕하게"},
    "default":      {"voice_name": "Achird",   "speed": 1.0,
                     "style": "개성 있고 생기 넘치는 동화 캐릭터 목소리"},
}

# 언어별 청자(아동) 기준 속도 보정 계수 — 화자별 speed에 곱해서 적용
#   es·pt: 평균 음절 발화 속도 최상위권(스페인어 ~7.8음절/초) → 가장 크게 감속
#   en: 강세박자 언어, 비원어민 아동 청취 고려 소폭 감속
#   id: 음절박자 언어, 학습자 청취 고려
#   ja: 모라 박자로 음절 밀도 높음
#   ko: Typecast 화자별 speed(내레이터 0.9 등)에서 이미 보정 → 1.0
LISTENER_LANG_SPEED = {
    "ko": 1.0, "en": 0.95, "id": 0.92, "es": 0.88, "pt": 0.90, "ja": 0.93,
}

# Gemini 파이프라인용 언어별 퀴즈 안내 멘트
GEMINI_QUIZ_LINES = {
    "ko": [
        ("quiz_intro", "자, 이제 퀴즈를 풀어볼까요?", "cheerful, inviting"),
        ("quiz_q1",    "1번 문제입니다!",             "excited, encouraging"),
        ("quiz_q2",    "2번 문제입니다!",             "excited, encouraging"),
        ("quiz_q3",    "3번 문제입니다!",             "excited, encouraging"),
        ("quiz_a1",    "정답입니다!",                 "joyful, praising"),
        ("quiz_a2",    "정답입니다!",                 "joyful, praising"),
        ("quiz_a3",    "정답입니다!",                 "joyful, praising"),
    ],
    "id": [
        ("quiz_intro", "Yuk, kita jawab kuisnya!", "cheerful, inviting"),
        ("quiz_q1",    "Soal nomor satu!",          "excited, encouraging"),
        ("quiz_q2",    "Soal nomor dua!",           "excited, encouraging"),
        ("quiz_q3",    "Soal nomor tiga!",          "excited, encouraging"),
        ("quiz_a1",    "Jawabannya benar!",         "joyful, praising"),
        ("quiz_a2",    "Jawabannya benar!",         "joyful, praising"),
        ("quiz_a3",    "Jawabannya benar!",         "joyful, praising"),
    ],
    "en": [
        ("quiz_intro", "Now, let's try the quiz!", "cheerful, inviting"),
        ("quiz_q1",    "Question one!",             "excited, encouraging"),
        ("quiz_q2",    "Question two!",             "excited, encouraging"),
        ("quiz_q3",    "Question three!",           "excited, encouraging"),
        ("quiz_a1",    "That's correct!",           "joyful, praising"),
        ("quiz_a2",    "That's correct!",           "joyful, praising"),
        ("quiz_a3",    "That's correct!",           "joyful, praising"),
    ],
    "es": [
        ("quiz_intro", "¡Ahora, vamos con el quiz!", "cheerful, inviting"),
        ("quiz_q1",    "¡Pregunta uno!",              "excited, encouraging"),
        ("quiz_q2",    "¡Pregunta dos!",              "excited, encouraging"),
        ("quiz_q3",    "¡Pregunta tres!",             "excited, encouraging"),
        ("quiz_a1",    "¡Correcto!",                  "joyful, praising"),
        ("quiz_a2",    "¡Correcto!",                  "joyful, praising"),
        ("quiz_a3",    "¡Correcto!",                  "joyful, praising"),
    ],
    "pt": [
        ("quiz_intro", "Agora, vamos ao quiz!", "cheerful, inviting"),
        ("quiz_q1",    "Pergunta um!",           "excited, encouraging"),
        ("quiz_q2",    "Pergunta dois!",         "excited, encouraging"),
        ("quiz_q3",    "Pergunta três!",         "excited, encouraging"),
        ("quiz_a1",    "Correto!",               "joyful, praising"),
        ("quiz_a2",    "Correto!",               "joyful, praising"),
        ("quiz_a3",    "Correto!",               "joyful, praising"),
    ],
}

# ---------------------------------------------------------------------------
# Typecast API 설정 (한국어)
# 문서: https://typecast.ai/docs/api-reference/text-to-speech/text-to-speech
# ---------------------------------------------------------------------------
TYPECAST_BASE_URL = "https://api.typecast.ai"
TYPECAST_MODEL = os.getenv("TYPECAST_MODEL", "ssfm-v30")  # ssfm-v30(최신) | ssfm-v21(안정)
TYPECAST_TEXT_LIMIT = 2000  # 요청당 최대 글자 수

# ---------------------------------------------------------------------------
# 캐릭터별 보이스 선택 기준
# speaker → 검색 필터 (gender, age, use_cases — Typecast /v2/voices 값 체계)
# age: child | teenager | young_adult | middle_age | elder
# ---------------------------------------------------------------------------
VOICE_SEARCH_CRITERIA = {
    "narrator": {
        "gender": "female",
        "age": ["young_adult", "middle_age"],
        "use_case": ["narration", "audiobook", "storytelling", "documentary"],
        "speed": 0.9,
    },
    "child_boy": {
        "gender": "male",
        "age": ["child"],
        "use_case": ["storytelling", "game", "conversational", "acting"],
        "speed": 1.05,
    },
    "child_girl": {
        "gender": "female",
        "age": ["child"],
        "use_case": ["storytelling", "game", "conversational", "acting"],
        "speed": 1.0,
    },
    "teacher": {
        "gender": "female",
        "age": ["young_adult", "middle_age"],
        "use_case": ["education", "narration", "announcement", "business"],
        "speed": 0.95,
    },
}

# 기본 폴백 (위 기준에 맞는 보이스 없을 때)
DEFAULT_CRITERIA = {
    "gender": None,
    "age": ["young_adult"],
    "use_case": ["storytelling", "acting"],
    "speed": 1.0,
}

# seg["emotion"] 자유 텍스트 → Typecast ssfm-v30 emotion_preset 매핑
# 프리셋: normal, happy, sad, angry, whisper, toneup, tonedown
_EMOTION_KEYWORDS = [
    ("happy",   ["기쁨", "기뻐", "신남", "신나", "즐거", "행복", "happy", "joy", "excit", "cheer"]),
    ("sad",     ["슬픔", "슬퍼", "우울", "눈물", "sad", "sorrow", "cry"]),
    ("angry",   ["화남", "화가", "분노", "짜증", "angry", "mad", "furious"]),
    ("whisper", ["속삭", "귓속말", "whisper", "quiet"]),
]


def emotion_to_preset(emotion: str):
    """세그먼트 emotion 텍스트를 Typecast 프리셋으로 변환. 매칭 없으면 None(자동 문맥)."""
    if not emotion:
        return None
    e = emotion.lower()
    for preset, keywords in _EMOTION_KEYWORDS:
        if any(k in e for k in keywords):
            return preset
    return None


def build_dynamic_criteria(speaker: str, story: dict) -> dict:
    """스토리 캐릭터 정보를 이용해 커스텀 speaker에 맞는 보이스 기준을 생성합니다."""
    # 표준 기준에 있으면 그걸 그대로 사용
    if speaker in VOICE_SEARCH_CRITERIA:
        return VOICE_SEARCH_CRITERIA[speaker]

    meta = story.get("meta", {})
    chars = meta.get("characters", {})

    # main_1 / main_2 / main_3 / sub_1 등 → 캐릭터 gender/species 활용
    import re as _re
    if _re.match(r'^(main|sub)_\d+$', speaker):
        ch = chars.get(speaker, {})
        gender = ch.get("gender", "female")
        if gender not in ("male", "female"):
            gender = "female"
        species = (ch.get("species", "") + " " + ch.get("personality", "")).lower()
        # 아이·어린·요정·말랑이 계열 → 아동 보이스
        if any(w in species for w in ["아이", "child", "소년", "소녀", "요정", "fairy", "어린", "말랑", "젤리"]):
            return {
                "gender": gender,
                "age": ["child"],
                "use_case": ["storytelling", "game", "acting", "conversational"],
                "speed": 1.05 if gender == "male" else 1.0,
            }
        # 나머지 주인공 → 젊은 성인
        return {
            "gender": gender,
            "age": ["young_adult"],
            "use_case": ["storytelling", "acting", "conversational"],
            "speed": 1.0,
        }

    # supporting 캐릭터
    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        for k, v in sup.items():
            if not isinstance(v, dict):
                continue
            if k != speaker and v.get("name") != speaker:
                continue
            role = v.get("role", "").lower()
            app = v.get("appearance_en", "").lower()
            combined = role + " " + app
            # 마녀 / 빌런 / 악당
            if any(w in combined for w in ["마녀", "witch", "villain", "dark", "shadow", "evil", "악당"]):
                return {
                    "gender": "female",
                    "age": ["middle_age"],
                    "use_case": ["acting", "game", "storytelling"],
                    "speed": 0.88,
                }
            # 현자 / 나무 / 장로
            if any(w in combined for w in ["나무", "tree", "wise", "elder", "ancient", "현인", "장로", "할아버지", "할머니"]):
                return {
                    "gender": "female",
                    "age": ["middle_age", "elder"],
                    "use_case": ["narration", "audiobook", "storytelling"],
                    "speed": 0.85,
                }
            # 기타 조연 → 젊은 성인
            return {
                "gender": "female",
                "age": ["young_adult"],
                "use_case": ["storytelling", "acting"],
                "speed": 0.95,
            }

    return DEFAULT_CRITERIA

# ---------------------------------------------------------------------------
# 세그먼트 간 무음 간격 (초)
# ---------------------------------------------------------------------------
SILENCE_SAME_SPEAKER = 0.2
SILENCE_SPEAKER_CHANGE = 0.5
SILENCE_SLIDE_TRANSITION = 1.0
COVER_SLIDE_DURATION = 3.0
ENDING_EXTRA_SECONDS = 2.0


def parse_args():
    parser = argparse.ArgumentParser(description="TTS 음성 생성 + timing.json (한국어: Typecast / 기타: Gemini)")
    parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (예: 1 → output/ep01)")
    parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
    parser.add_argument("--engine", type=str, default=os.getenv("TTS_ENGINE_KO", "gemini"),
                        choices=["gemini", "typecast"],
                        help="한국어 TTS 엔진 (기본 gemini — 품질 확인됨. typecast는 선택)")
    parser.add_argument("--force-voice", action="store_true",
                        help="story.json meta 보이스 캐시 무시하고 새로 선택")
    parser.add_argument("--revoice", action="store_true",
                        help="보이스 캐시/메타 모두 무시하고 새로 선택 (--force-voice와 동일)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Typecast 보이스 자동 선택
# ---------------------------------------------------------------------------
def _norm_voice(v: dict) -> dict:
    """Typecast /v2/voices 응답 필드를 내부 표준 형태로 정규화합니다."""
    use_cases = v.get("use_cases") or v.get("use_case") or []
    if isinstance(use_cases, str):
        use_cases = [use_cases]
    models = v.get("models") or ([v["model"]] if v.get("model") else [])
    if isinstance(models, str):
        models = [models]
    return {
        "voice_id": v.get("voice_id") or v.get("id", ""),
        "name": v.get("voice_name") or v.get("name", "?"),
        "gender": v.get("gender", "?"),
        "age": v.get("age", "?"),
        "use_cases": [str(u).lower() for u in use_cases],
        "models": models,
        "emotions": v.get("emotions", []),
    }


def fetch_voices(api_key: str, language: str = "ko") -> list:
    """Typecast API에서 보이스 목록을 가져옵니다 (모델 필터 적용)."""
    headers = {"X-API-KEY": api_key}
    try:
        resp = requests.get(
            f"{TYPECAST_BASE_URL}/v2/voices",
            params={"model": TYPECAST_MODEL},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            # 모델 필터 미지원 시 전체 목록으로 재시도
            resp = requests.get(f"{TYPECAST_BASE_URL}/v2/voices",
                                headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"  [ERROR] 보이스 목록 HTTP {resp.status_code}: {resp.text[:150]}")
                return []
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("voices") or data.get("items") or data.get("result") or []
        return [_norm_voice(v) for v in data if isinstance(v, dict)]
    except Exception as e:
        print(f"  [ERROR] 보이스 목록 조회 실패: {e}")
        return []


def score_voice(voice: dict, criteria: dict) -> int:
    """보이스가 기준에 얼마나 맞는지 점수를 매깁니다 (높을수록 좋음)."""
    score = 0

    # 성별 일치
    if criteria.get("gender") and voice.get("gender") == criteria["gender"]:
        score += 100

    # 나이 일치
    target_ages = criteria.get("age", [])
    if voice.get("age") in target_ages:
        score += 80

    # use_case 일치 (하나라도 겹치면 점수)
    target_uses = set(criteria.get("use_case", []))
    voice_uses = set(voice.get("use_cases", []))
    overlap = target_uses & voice_uses
    score += len(overlap) * 20

    # 현재 사용 모델(ssfm-v30 등) 지원 시 가산
    if TYPECAST_MODEL in voice.get("models", []):
        score += 10

    return score


def build_voice_query(speaker: str, story: dict) -> str:
    """캐릭터 정보를 바탕으로 Typecast 보이스 추천용 자연어 쿼리를 만듭니다.
    '맥락에 맞는 목소리 캐스팅'의 핵심 — 성격·종족·역할을 설명에 녹입니다."""
    meta = story.get("meta", {})
    chars = meta.get("characters", {})

    base_queries = {
        "narrator":   "어린이 동화책을 따뜻하고 차분하게 낭독하는 여성 성우 목소리",
        "child_boy":  "밝고 활기찬 어린 남자아이 목소리, 애니메이션 더빙",
        "child_girl": "명랑하고 귀여운 어린 여자아이 목소리, 애니메이션 더빙",
        "teacher":    "친절하고 신뢰감 있는 선생님 목소리, 어린이 교육 콘텐츠",
    }
    if speaker in base_queries:
        return base_queries[speaker]

    # main_1 / sub_1 등 커스텀 캐릭터 → 캐릭터 메타로 쿼리 구성
    ch = chars.get(speaker)
    if isinstance(ch, dict):
        gender = "남성" if ch.get("gender") == "male" else "여성"
        parts = [p for p in [ch.get("species", ""), ch.get("personality", "")] if p]
        desc = ", ".join(parts) or "동화 주인공"
        return f"어린이 동화 속 캐릭터({desc})에 어울리는 {gender} 목소리, 애니메이션 더빙"

    # supporting 캐릭터
    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        for k, v in sup.items():
            if isinstance(v, dict) and (k == speaker or v.get("name") == speaker):
                role = v.get("role", "조연 캐릭터")
                return f"어린이 동화 속 {role} 역할에 어울리는 개성 있는 목소리, 애니메이션 더빙"

    return f"어린이 동화 캐릭터 {speaker}에 어울리는 목소리, 애니메이션 더빙"


def recommend_voice(api_key: str, query: str, used_ids: set):
    """Typecast /v1/voices/recommendations — 자연어 설명으로 보이스 추천.
    사용 중/블랙리스트 제외 후 첫 추천을 반환. 실패 시 None."""
    try:
        resp = requests.get(
            f"{TYPECAST_BASE_URL}/v1/voices/recommendations",
            params={"query": query},
            headers={"X-API-KEY": api_key},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, dict):
            data = (data.get("voices") or data.get("recommendations")
                    or data.get("items") or data.get("result") or [])
        for v in data:
            nv = _norm_voice(v)
            if nv["voice_id"] and nv["voice_id"] not in used_ids \
                    and nv["voice_id"] not in FORBIDDEN_VOICE_IDS:
                return nv
    except Exception:
        pass
    return None


def cast_voices(api_key: str, voices: list, speakers: set, story: dict) -> dict:
    """맥락 기반 캐스팅: 추천 API 우선 → 실패 시 점수 기반 선택 폴백."""
    assigned = {}
    used_ids = set()
    priority = ["narrator", "child_boy", "child_girl", "teacher"]
    sorted_speakers = sorted(
        speakers,
        key=lambda s: priority.index(s) if s in priority else 99,
    )

    for speaker in sorted_speakers:
        query = build_voice_query(speaker, story)
        chosen = recommend_voice(api_key, query, used_ids)
        how = "맥락추천"

        if not chosen:
            how = "점수폴백"
            criteria = build_dynamic_criteria(speaker, story)
            candidates = []
            for v in voices:
                if v["voice_id"] in used_ids:
                    continue
                s = score_voice(v, criteria)
                if s > 0:
                    candidates.append((s, v))
            candidates.sort(key=lambda x: -x[0])
            if candidates:
                top_n = min(3, len(candidates))
                chosen = random.choice(candidates[:top_n])[1]
            else:
                remaining = [v for v in voices if v["voice_id"] not in used_ids]
                chosen = random.choice(remaining) if remaining else None

        if chosen:
            assigned[speaker] = chosen
            used_ids.add(chosen["voice_id"])
            print(f"  {speaker:12s} → {chosen['name']:15s} "
                  f"({chosen.get('gender','?')}, {chosen.get('age','?')}) [{how}]")

    return assigned


def select_voices(voices: list, speakers: set) -> dict:
    """각 speaker에 대해 가장 적합한 보이스를 자동 선택합니다.
    같은 에피소드 내에서 중복 보이스를 피합니다."""

    assigned = {}  # speaker -> voice dict
    used_ids = set()

    # speaker를 우선순위대로 정렬 (narrator 먼저, 그 다음 child, teacher 등)
    priority = ["narrator", "child_boy", "child_girl", "teacher"]
    sorted_speakers = sorted(
        speakers,
        key=lambda s: priority.index(s) if s in priority else 99,
    )

    for speaker in sorted_speakers:
        criteria = VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)

        # 점수 계산 후 정렬
        candidates = []
        for v in voices:
            if v["voice_id"] in used_ids:
                continue
            s = score_voice(v, criteria)
            if s > 0:
                candidates.append((s, v))

        candidates.sort(key=lambda x: -x[0])

        if not candidates:
            # 폴백: 아무 보이스나 선택
            remaining = [v for v in voices if v["voice_id"] not in used_ids]
            if remaining:
                chosen = random.choice(remaining)
            else:
                chosen = voices[0] if voices else None
        else:
            # 상위 3개 중 랜덤 선택 (다양성 부여)
            top_n = min(3, len(candidates))
            chosen = random.choice(candidates[:top_n])[1]

        if chosen:
            assigned[speaker] = chosen
            used_ids.add(chosen["voice_id"])
            print(f"  {speaker:12s} → {chosen['name']:15s} "
                  f"({chosen['gender']}, {chosen['age']}, "
                  f"id={chosen['voice_id'][:12]}...)")

    return assigned


# ---------------------------------------------------------------------------
# TTS 생성 & WAV 유틸
# ---------------------------------------------------------------------------
FORBIDDEN_VOICE_IDS: set = set()  # 403이 발생한 voice_id 블랙리스트


def load_voice_blacklist(ep_dir: Path) -> set:
    """ep_dir/voice_blacklist.json에서 블랙리스트 로드."""
    p = ep_dir / "voice_blacklist.json"
    if p.exists():
        try:
            return set(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return set()

def save_voice_blacklist(ep_dir: Path, blacklist: set):
    """블랙리스트를 ep_dir/voice_blacklist.json에 저장."""
    p = ep_dir / "voice_blacklist.json"
    p.write_text(json.dumps(sorted(blacklist), ensure_ascii=False, indent=2), encoding="utf-8")


def generate_tts_typecast(api_key: str, voice_id: str, text: str,
                          output_path: Path, speed: float = 1.0,
                          pitch_shift: int = 0, emotion: str = "",
                          prev_text: str = "", next_text: str = "",
                          ep_dir: Path = None, max_retries: int = 3) -> str:
    """Typecast API로 TTS를 생성하고 WAV로 저장합니다.
    감정: 문맥(prev/next)이 있으면 Smart Emotion(공식 권장), 고정 멘트는 프리셋.
    Returns: "ok" | "forbidden" | "error"
    """
    headers = {
        "X-API-KEY": api_key,
        # Typecast 통합 어트리뷰션 (llms.txt 지침)
        "User-Agent": "typecast-direct/1 requests typecast-integration/1 "
                      "(source=llms; generated_by=claude-code)",
    }
    url = f"{TYPECAST_BASE_URL}/v1/text-to-speech"
    payload = {
        "voice_id": voice_id,
        "text": text[:TYPECAST_TEXT_LIMIT],
        "model": TYPECAST_MODEL,
        "language": "kor",  # ISO 639-3
        "output": {
            "audio_format": "wav",
            "audio_tempo": max(0.5, min(2.0, speed)),
            "audio_pitch": max(-12, min(12, int(pitch_shift))),
            "target_lufs": -14,  # 세그먼트 간 음량 일관성
        },
    }
    if prev_text or next_text:
        # 이야기 흐름 문맥으로 감정을 자동 추론 (동화 낭독에 최적)
        payload["prompt"] = {
            "emotion_type": "smart",
            "previous_text": prev_text[:300],
            "next_text": next_text[:300],
        }
    else:
        preset = emotion_to_preset(emotion)
        if preset:
            payload["prompt"] = {
                "emotion_type": "preset",
                "emotion_preset": preset,
                "emotion_intensity": 1.2,
            }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code in (403, 404):
                FORBIDDEN_VOICE_IDS.add(voice_id)
                if ep_dir is not None:
                    save_voice_blacklist(ep_dir, FORBIDDEN_VOICE_IDS)
                print(f"    [{resp.status_code}] voice_id={voice_id[:14]}... 사용 불가 — 블랙리스트 추가")
                return "forbidden"
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"    [429] 레이트리밋 — {wait}초 대기 후 재시도 ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            if resp.status_code == 402:
                print(f"    [402] Typecast 크레딧 부족: {resp.text[:150]}")
                return "error"
            if resp.status_code != 200:
                print(f"    [ERROR] HTTP {resp.status_code}: {resp.text[:150]}")
                return "error"
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return "ok"
        except Exception as e:
            print(f"    [ERROR] 요청 실패 ({attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(3)
    return "error"


def get_wav_duration(wav_path: Path) -> float:
    """WAV 파일의 정확한 길이(초)를 측정합니다."""
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        if rate == 0:
            return 0.0
        if frames >= 2147483647:
            file_size = wav_path.stat().st_size
            data_size = file_size - 44
            if data_size <= 0:
                return 0.0
            actual_frames = data_size // (channels * sampwidth)
            return actual_frames / rate
        return frames / rate


def concat_wav_files(wav_paths: list, output_path: Path):
    """Python wave 모듈만 사용하여 WAV 파일들을 하나로 합칩니다.
    파라미터가 다른 파일이 섞이면 경고 후 제외합니다 (wave는 리샘플 불가)."""
    if not wav_paths:
        return

    with wave.open(str(wav_paths[0]), "rb") as first:
        nchannels = first.getnchannels()
        sampwidth = first.getsampwidth()
        framerate = first.getframerate()
        frames = [first.readframes(first.getnframes())]

    for p in wav_paths[1:]:
        with wave.open(str(p), "rb") as wf:
            if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != \
                    (nchannels, sampwidth, framerate):
                print(f"    [경고] {Path(p).name}: 오디오 파라미터 불일치 "
                      f"({wf.getframerate()}Hz≠{framerate}Hz) — 합치기에서 제외. "
                      f"해당 세그먼트를 같은 엔진으로 재생성하세요.")
                continue
            frames.append(wf.readframes(wf.getnframes()))

    all_data = b"".join(frames)
    total_frames = len(all_data) // (nchannels * sampwidth)

    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.setnframes(total_frames)
        out.writeframesraw(all_data)


# ---------------------------------------------------------------------------
# Gemini TTS (인도네시아어 + 다국어)
# ---------------------------------------------------------------------------

def pcm_to_wav(pcm_data: bytes, output_path: Path,
               sample_rate: int = GEMINI_TTS_SAMPLE_RATE):
    """Raw PCM (16-bit mono) → WAV 파일 저장."""
    n_channels = 1
    samp_width = 2  # 16-bit
    n_frames = len(pcm_data) // (n_channels * samp_width)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(samp_width)
        wf.setframerate(sample_rate)
        wf.setnframes(n_frames)
        wf.writeframesraw(pcm_data)


def apply_speed_ffmpeg(input_path: Path, output_path: Path, speed: float) -> bool:
    """FFmpeg atempo로 WAV 재생속도를 조정합니다."""
    import subprocess
    if abs(speed - 1.0) < 0.02:
        input_path.rename(output_path)
        return True
    # atempo 범위: 0.5~2.0 (연속 적용으로 범위 확장 가능하나 여기선 불필요)
    speed = max(0.5, min(2.0, speed))
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"atempo={speed}",
        "-ar", str(GEMINI_TTS_SAMPLE_RATE),
        "-ac", "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if input_path.exists() and str(input_path) != str(output_path):
        input_path.unlink(missing_ok=True)
    return result.returncode == 0


_gemini_model_idx = 0  # 폴백 체인 진행 상태 (한 번 폴백하면 이후 요청도 유지)


def _gemini_models() -> list:
    """중복 제거된 Gemini TTS 폴백 모델 체인."""
    seen = []
    for m in GEMINI_TTS_FALLBACK_MODELS:
        if m and m not in seen:
            seen.append(m)
    return seen


def generate_tts_gemini(voice_name: str, text: str, emotion: str,
                        output_path: Path, speed: float = 1.0,
                        max_retries: int = 3) -> str:
    """Gemini TTS API로 음성 생성 → WAV 저장.
    Returns: "ok" | "error"
    """
    global _gemini_model_idx
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        import subprocess as sp
        sp.run([sys.executable, "-m", "pip", "install", "google-genai"], check=True)
        from google import genai
        from google.genai import types as gt

    if not GEMINI_API_KEY:
        print("    [ERROR] GEMINI_API_KEY 없음")
        return "error"

    client = genai.Client(api_key=GEMINI_API_KEY)

    # 감정 지시어는 '지시문: 대사' 콜론 구문으로 전달 (공식 권장 형식).
    # 대괄호/괄호로 앞에 붙이면 지시문을 그대로 읽어버리는 문제가 있음.
    # 감정 명확화: 감정을 지시문 맨 앞에 두고 '뚜렷하게' 강조.
    if emotion:
        prompt = f"{emotion}. 이 감정이 뚜렷하게 드러나도록 다음 문장을 읽어줘: {text}"
    else:
        prompt = text

    models = _gemini_models()
    for attempt in range(1, max_retries + 1):
        model = models[min(_gemini_model_idx, len(models) - 1)]
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=gt.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=gt.SpeechConfig(
                        voice_config=gt.VoiceConfig(
                            prebuilt_voice_config=gt.PrebuiltVoiceConfig(
                                voice_name=voice_name
                            )
                        )
                    ),
                ),
            )

            # 오디오 데이터 추출
            audio_data = None
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        raw = part.inline_data.data
                        if isinstance(raw, (bytes, bytearray)):
                            audio_data = bytes(raw)
                        else:
                            audio_data = base64.b64decode(raw)
                        break
                if audio_data:
                    break

            if not audio_data:
                print(f"    [WARN] 시도 {attempt}/{max_retries}: 오디오 데이터 없음")
                if attempt < max_retries:
                    time.sleep(3)
                continue

            # PCM → WAV 저장
            tmp_path = output_path.with_suffix(".pcm.tmp.wav")
            pcm_to_wav(audio_data, tmp_path)

            # 속도 조정 (필요 시)
            if abs(speed - 1.0) > 0.02:
                apply_speed_ffmpeg(tmp_path, output_path, speed)
            else:
                tmp_path.rename(output_path)

            return "ok"

        except Exception as e:
            msg = str(e).lower()
            print(f"    [WARN] 시도 {attempt}/{max_retries} 실패 ({model}): {e}")
            # 모델 미지원/쿼터 초과 → 다음 폴백 모델로 전환
            if (_gemini_model_idx < len(models) - 1 and
                    any(k in msg for k in ["not found", "404", "quota",
                                           "resource_exhausted", "429", "permission"])):
                _gemini_model_idx += 1
                print(f"    [폴백] Gemini TTS 모델 전환 → {models[_gemini_model_idx]}")
            if attempt < max_retries:
                time.sleep(5)

    return "error"


def run_gemini_tts_pipeline(ep_dir: Path, story: dict, lang: str = "id"):
    """Gemini TTS로 전체 음성을 생성합니다 (id 기본, ko 폴백 및 기타 언어 지원)."""
    slides = story.get("slides", [])
    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 보이스 맵: story.json의 gemini_voices 우선, 없으면 기본값
    voice_cfg = story.get("meta", {}).get("gemini_voices", GEMINI_VOICE_DEFAULTS)
    # 언어별 청자 기준 속도 보정 (미등록 언어는 보수적으로 0.95)
    lang_factor = LISTENER_LANG_SPEED.get(lang, 0.95)
    print(f"[{lang} TTS] Gemini TTS 엔진 ({GEMINI_TTS_MODEL}) | 언어 속도 보정 x{lang_factor}")
    print(f"  보이스 설정:")
    for spk, cfg in voice_cfg.items():
        if spk != "default":
            print(f"    {spk:12s} → {cfg['voice_name']} (speed={cfg['speed']})")
    print()

    slide_segments_map: dict = {}

    for slide in slides:
        slide_num = slide.get("slide_number", 0)
        segments = slide.get("tts_segments", [])

        if not segments:
            print(f"[슬라이드 {slide_num:02d}] tts_segments 없음 — 건너뜀")
            continue

        print(f"[슬라이드 {slide_num:02d}] 세그먼트 {len(segments)}개 처리 중...")
        seg_entries = []

        for seg_idx, seg in enumerate(segments):
            seg_path = audio_dir / f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav"
            speaker = seg.get("speaker", "narrator")
            text    = seg.get("text", "").strip()
            emotion = seg.get("emotion", "warm storytelling tone")

            seg_entries.append((seg_idx, seg, seg_path))

            if seg_path.exists():
                print(f"  seg {seg_idx:02d} [{speaker}] — 이미 존재, 건너뜀")
                continue
            if not text:
                print(f"  seg {seg_idx:02d} [{speaker}] — 텍스트 비어있음, 건너뜀")
                continue

            # 보이스 선택 (화자 페르소나 + 세그먼트 감정을 결합해 지시)
            vc = voice_cfg.get(speaker, voice_cfg.get("default", {"voice_name": "Aoede", "speed": 1.0}))
            voice_name = vc["voice_name"]
            speed      = float(vc.get("speed", 1.0)) * lang_factor
            persona    = vc.get("style", "")
            full_style = ", ".join(x for x in (persona, emotion) if x)

            result = generate_tts_gemini(voice_name, text, full_style, seg_path, speed)
            if result == "ok":
                dur = get_wav_duration(seg_path) if seg_path.exists() else 0.0
                print(f"  seg {seg_idx:02d} [{speaker}] voice={voice_name} — 완료 ({dur:.2f}s)")
            else:
                print(f"  seg {seg_idx:02d} [{speaker}] — 실패")

            # API 레이트 제한 방지
            time.sleep(1)

        slide_segments_map[slide_num] = seg_entries

        # 슬라이드별 합치기
        existing = [p for _, _, p in seg_entries if p.exists()]
        if existing:
            slide_wav = audio_dir / f"slide_{slide_num:02d}.wav"
            try:
                concat_wav_files(existing, slide_wav)
                print(f"  -> slide_{slide_num:02d}.wav ({len(existing)}개 합침)")
            except Exception as e:
                print(f"  -> 합치기 실패: {e}")
        print()

    # ── 퀴즈 TTS (언어별 안내 멘트) ──────────────────────────
    narrator_vc = voice_cfg.get("narrator", voice_cfg.get("default", {"voice_name": "Kore", "speed": 0.95}))
    quiz_voice  = narrator_vc["voice_name"]
    quiz_speed  = float(narrator_vc.get("speed", 0.95)) * lang_factor

    print(f"[퀴즈 TTS] {lang} 안내 멘트 생성 중...")
    quiz_lines = GEMINI_QUIZ_LINES.get(lang, GEMINI_QUIZ_LINES["en"])
    for fname, text, emotion in quiz_lines:
        out_path = audio_dir / f"{fname}.wav"
        if out_path.exists():
            print(f"  {fname}.wav — 이미 존재, 건너뜀")
            continue
        result = generate_tts_gemini(quiz_voice, text, emotion, out_path, quiz_speed)
        print(f"  {fname}.wav — {'완료' if result == 'ok' else '실패'}")
        time.sleep(1)

    # ── Shorts 훅 TTS ────────────────────────────────────────
    hook_line = story.get("shorts_strategy", {}).get("hook_line", "")
    if hook_line:
        hook_path = audio_dir / "shorts_hook.wav"
        if hook_path.exists():
            print(f"\n[INFO] shorts_hook.wav — 이미 존재, 건너뜀")
        else:
            print(f"\n[INFO] Shorts 훅 TTS: {hook_line}")
            result = generate_tts_gemini(quiz_voice, hook_line, "exciting, dramatic hook",
                                         hook_path, quiz_speed)
            print(f"  shorts_hook.wav — {'완료' if result == 'ok' else '실패'}")

    return slide_segments_map


# ---------------------------------------------------------------------------
# timing.json 빌더 (Typecast / Gemini TTS 공통)
# ---------------------------------------------------------------------------

def _build_timing_json(ep_dir: Path, story: dict, slides: list,
                        audio_dir: Path, slide_segments_map: dict):
    """slide_segments_map을 바탕으로 timing.json을 생성합니다."""
    print("timing.json 생성 중...")

    timing_segments = []
    timing_slides = []
    cumulative_time = 0.0
    all_slide_nums = sorted(set(s.get("slide_number", 0) for s in slides))
    total_segment_count = 0

    for slide_num in all_slide_nums:
        slide_start = cumulative_time

        if slide_num == 0:
            cumulative_time += COVER_SLIDE_DURATION
            timing_slides.append({
                "slide": 0, "type": "cover",
                "start": round(slide_start, 3),
                "end": round(cumulative_time, 3),
                "duration": round(COVER_SLIDE_DURATION, 3),
            })
            continue

        if slide_num > 1 or (slide_num == 1 and 0 in {s.get("slide_number", 0) for s in slides}):
            cumulative_time += SILENCE_SLIDE_TRANSITION
            slide_start = cumulative_time

        seg_entries = slide_segments_map.get(slide_num, [])
        prev_speaker = None

        for seg_idx, seg, seg_path in seg_entries:
            if not seg_path.exists():
                continue
            speaker = seg.get("speaker", "narrator")
            text = seg.get("text", "")
            duration = get_wav_duration(seg_path)

            if prev_speaker is not None:
                cumulative_time += SILENCE_SAME_SPEAKER if speaker == prev_speaker else SILENCE_SPEAKER_CHANGE

            seg_start = cumulative_time
            seg_end = cumulative_time + duration
            timing_segments.append({
                "file": f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav",
                "slide": slide_num, "index": seg_idx,
                "speaker": speaker, "text": text,
                "duration": round(duration, 3),
                "start": round(seg_start, 3), "end": round(seg_end, 3),
            })
            cumulative_time = seg_end
            prev_speaker = speaker
            total_segment_count += 1

        is_last = (slide_num == all_slide_nums[-1])
        slide_type = "ending" if is_last else "story"
        if is_last:
            cumulative_time += ENDING_EXTRA_SECONDS

        timing_slides.append({
            "slide": slide_num, "type": slide_type,
            "start": round(slide_start, 3),
            "end": round(cumulative_time, 3),
            "duration": round(cumulative_time - slide_start, 3),
        })

    total_duration = round(cumulative_time, 3)
    timing_data = {
        "segments": timing_segments,
        "slides": timing_slides,
        "total_duration": total_duration,
    }
    timing_path = audio_dir / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing_data, f, ensure_ascii=False, indent=2)

    print(f"  총 세그먼트 {total_segment_count}개 | 총 {total_duration:.1f}초 ({total_duration/60:.1f}분)")
    print(f"  -> {timing_path} 저장 완료\n")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")
    story_path = ep_dir / "story.json"

    if not story_path.exists():
        print(f"story.json을 찾을 수 없습니다: {story_path}")
        return

    # 블랙리스트 영구 로드 (ep_dir/voice_blacklist.json)
    FORBIDDEN_VOICE_IDS.update(load_voice_blacklist(ep_dir))
    if FORBIDDEN_VOICE_IDS:
        print(f"[블랙리스트] {len(FORBIDDEN_VOICE_IDS)}개 voice_id 로드됨")

    # --force-voice / --revoice 플래그
    ignore_voice_cache = getattr(args, "force_voice", False) or getattr(args, "revoice", False)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    # ── 언어 감지 → TTS 엔진 자동 선택 ────────────────────
    lang = story.get("meta", {}).get("language", "ko")
    slides = story.get("slides", [])
    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{ep_dir}] TTS 생성 시작 (언어: {lang})")
    print(f"  슬라이드 수: {len(slides)}")
    print(f"  출력 폴더: {audio_dir}")
    print()

    # ── 비한국어 또는 --engine gemini → Gemini TTS 분기 ────
    if lang != "ko" or args.engine == "gemini":
        slide_segments_map = run_gemini_tts_pipeline(ep_dir, story, lang=lang)
        # timing.json 생성은 아래 공통 로직에서 처리
        _build_timing_json(ep_dir, story, slides, audio_dir, slide_segments_map)
        return

    # ── 한국어 → Typecast TTS ──────────────────────────────
    api_key = os.getenv("TYPECAST_API_KEY")
    if not api_key:
        print("[ERROR] TYPECAST_API_KEY가 .env에 없습니다")
        print("  발급: https://studio.typecast.ai/developers/api (모델: ssfm-v30)")
        print("  임시 대안: --engine gemini 로 Gemini TTS 사용 가능")
        return

    # ------------------------------------------------------------------
    # 0단계: 보이스 자동 선택
    # ------------------------------------------------------------------
    # 모든 슬라이드에서 사용되는 speaker 목록 수집
    all_speakers = set()
    for slide in slides:
        for seg in slide.get("tts_segments", []):
            all_speakers.add(seg.get("speaker", "narrator"))

    # story.json meta에 저장된 보이스 캐시 (Typecast 전환 후 구 supertone_voices는 무시)
    meta_voice_cache = story.get("meta", {}).get("typecast_voices", {})

    voice_cache_path = audio_dir / "voice_selection.json"
    all_voices = None  # 보이스 목록 캐시 (한 번만 API 조회)

    def _is_typecast_map(vmap: dict) -> bool:
        """캐시된 보이스맵이 Typecast voice_id(tc_/uc_ 접두사)인지 검증.
        구 Supertone 캐시가 남아 있으면 자동 폐기하기 위함."""
        ids = [v.get("voice_id", "") for v in vmap.values() if isinstance(v, dict)]
        return bool(ids) and all(str(i).startswith(("tc_", "uc_")) for i in ids)

    # --force-voice / --revoice: 캐시 파일 삭제 후 재선택
    if ignore_voice_cache:
        print("[보이스 선택] --force-voice / --revoice: 기존 캐시 무시, 새로 선택합니다")
        if voice_cache_path.exists():
            voice_cache_path.unlink()
        meta_voice_cache = {}

    voice_map = None

    if voice_cache_path.exists():
        # 캐시 파일이 있으면 (직접 편집 포함) 우선 사용
        with open(voice_cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if _is_typecast_map(cached):
            print("[보이스 선택] 파일 캐시에서 로드:")
            voice_map = cached
            for speaker, info in voice_map.items():
                print(f"  {speaker:12s} → {info['name']:15s} ({info.get('gender','?')}, {info.get('age','?')})")
        else:
            print("[보이스 선택] 구 Supertone 캐시 감지 — 폐기 후 Typecast 보이스 새로 선택")
            voice_cache_path.unlink()

    if voice_map is None and meta_voice_cache and not ignore_voice_cache \
            and _is_typecast_map(meta_voice_cache):
        # story.json meta.typecast_voices 캐시 사용 (API fetch 생략)
        print("[보이스 선택] story.json meta 캐시에서 로드 (API fetch 생략):")
        voice_map = {}
        for speaker, info in meta_voice_cache.items():
            criteria = VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)
            voice_map[speaker] = {
                "voice_id": info["voice_id"],
                "name": info["name"],
                "gender": info.get("gender", "?"),
                "age": info.get("age", "?"),
                "speed": criteria.get("speed", 1.0),
            }
            print(f"  {speaker:12s} → {info['name']:15s} ({info.get('gender','?')}, {info.get('age','?')})")
        # 파일 캐시도 동기화
        with open(voice_cache_path, "w", encoding="utf-8") as f:
            json.dump(voice_map, f, ensure_ascii=False, indent=2)

    if voice_map is None:
        print(f"[보이스 선택] Typecast 보이스 목록 조회 중... (model={TYPECAST_MODEL})")
        all_voices = fetch_voices(api_key)
        if not all_voices:
            print("[ERROR] 보이스 목록을 가져올 수 없습니다.")
            return
        print(f"  총 {len(all_voices)}개 보이스 중 캐릭터별 맥락 캐스팅:")
        selected = cast_voices(api_key, all_voices, all_speakers, story)
        voice_map = {}
        for speaker, voice in selected.items():
            criteria = VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)
            voice_map[speaker] = {
                "voice_id": voice["voice_id"],
                "name": voice["name"],
                "gender": voice["gender"],
                "age": voice["age"],
                "speed": criteria.get("speed", 1.0),
            }
        # 파일 캐시 저장
        with open(voice_cache_path, "w", encoding="utf-8") as f:
            json.dump(voice_map, f, ensure_ascii=False, indent=2)
        # story.json meta.typecast_voices 에도 저장 (다음 실행 시 API fetch 생략)
        try:
            story.setdefault("meta", {})["typecast_voices"] = {
                spk: {
                    "voice_id": vi["voice_id"],
                    "name": vi["name"],
                    "gender": vi["gender"],
                    "age": vi["age"],
                }
                for spk, vi in voice_map.items()
            }
            # 구 Supertone 캐시 제거 (혼동 방지)
            story.get("meta", {}).pop("supertone_voices", None)
            with open(story_path, "w", encoding="utf-8") as f:
                json.dump(story, f, ensure_ascii=False, indent=2)
            print("  [meta] story.json meta.typecast_voices 저장 완료")
        except Exception as e:
            print(f"  [WARN] story.json meta 저장 실패: {e}")

    # ------------------------------------------------------------------
    # voice_map 보완: 스토리에서 실제 사용되는 speaker 중 아직 배정 안 된 것 처리
    # ------------------------------------------------------------------
    missing_speakers = all_speakers - set(voice_map.keys())
    if missing_speakers:
        print(f"[보이스 보완] {len(missing_speakers)}개 추가 캐릭터 보이스 자동 배정 중...")
        # 보이스 목록 (아직 안 가져왔으면 API 조회, 재시도 포함)
        if all_voices is None:
            for attempt in range(3):
                try:
                    all_voices = fetch_voices(api_key)
                    if all_voices:
                        break
                except Exception as e:
                    print(f"  [WARN] 보이스 목록 조회 실패 (시도 {attempt+1}/3): {e}")
                    import time; time.sleep(3)

        if not all_voices:
            print("  [WARN] 보이스 목록 조회 실패 — 미배정 캐릭터는 narrator 보이스 사용")
        else:
            used_ids = {v["voice_id"] for v in voice_map.values()}
            supplemented = {}
            for speaker in sorted(missing_speakers):
                criteria = build_dynamic_criteria(speaker, story)
                # 1순위: 맥락 기반 추천
                chosen = recommend_voice(api_key, build_voice_query(speaker, story), used_ids)
                candidates = [(0, chosen)] if chosen else []
                if not candidates:
                    # 2순위: 점수 기반 폴백
                    for v in all_voices:
                        if v["voice_id"] in used_ids:
                            continue
                        s = score_voice(v, criteria)
                        if s > 0:
                            candidates.append((s, v))
                    candidates.sort(key=lambda x: -x[0])
                if not candidates:
                    # 점수 0이어도 미사용 보이스에서 랜덤 선택
                    remaining = [v for v in all_voices if v["voice_id"] not in used_ids]
                    if remaining:
                        candidates = [(0, random.choice(remaining))]
                if candidates:
                    top_n = min(3, len(candidates))
                    chosen = random.choice(candidates[:top_n])[1]
                    voice_map[speaker] = {
                        "voice_id": chosen["voice_id"],
                        "name": chosen["name"],
                        "gender": chosen["gender"],
                        "age": chosen["age"],
                        "speed": criteria.get("speed", 1.0),
                    }
                    used_ids.add(chosen["voice_id"])
                    supplemented[speaker] = voice_map[speaker]
                    print(f"  {speaker:15s} → {chosen['name']:15s} "
                          f"({chosen['gender']}, {chosen['age']})")
            # 보완된 내용을 파일 캐시 + story.json meta 에 저장
            if supplemented:
                cache_data = {}
                if voice_cache_path.exists():
                    with open(voice_cache_path, "r", encoding="utf-8") as f:
                        cache_data = json.load(f)
                cache_data.update(supplemented)
                with open(voice_cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                # story.json meta도 업데이트
                try:
                    story.setdefault("meta", {}).setdefault("typecast_voices", {}).update({
                        spk: {
                            "voice_id": vi["voice_id"],
                            "name": vi["name"],
                            "gender": vi["gender"],
                            "age": vi["age"],
                        }
                        for spk, vi in supplemented.items()
                    })
                    with open(story_path, "w", encoding="utf-8") as f:
                        json.dump(story, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"  [WARN] story.json meta 보완 저장 실패: {e}")
    print()

    # ------------------------------------------------------------------
    # 1단계: 모든 TTS 세그먼트 생성 (ThreadPoolExecutor, max_workers=4)
    # ------------------------------------------------------------------
    slide_segments_map: dict[int, list] = {}

    # 403 폴백 처리 시 voice_map / all_voices 공유 상태 보호용 Lock
    _voice_lock = threading.Lock()

    def _generate_one_segment(slide_num: int, seg_idx: int, seg: dict,
                               seg_path: Path) -> tuple:
        """단일 세그먼트 TTS 생성 (스레드 안전).
        Returns: (slide_num, seg_idx, seg, seg_path)
        """
        nonlocal all_voices

        speaker = seg.get("speaker", "narrator")
        text = seg.get("text", "")

        if seg_path.exists():
            print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 이미 존재, 건너뜀")
            return (slide_num, seg_idx, seg, seg_path)

        if not text.strip():
            print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 텍스트 비어있음, 건너뜀")
            return (slide_num, seg_idx, seg, seg_path)

        with _voice_lock:
            vi = voice_map.get(speaker, voice_map.get("narrator", {}))
            voice_id = vi.get("voice_id", "")
            voice_name = vi.get("name", "?")
            speed = vi.get("speed", 1.0)
            pitch_shift = vi.get("pitch_shift", 0)

        if not voice_id:
            print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 보이스 없음, 건너뜀")
            return (slide_num, seg_idx, seg, seg_path)

        # Smart Emotion용 문맥: 같은 슬라이드의 앞/뒤 세그먼트 텍스트
        _slide_texts = _segment_texts.get(slide_num, [])
        prev_text = _slide_texts[seg_idx - 1] if seg_idx > 0 else ""
        next_text = _slide_texts[seg_idx + 1] if seg_idx + 1 < len(_slide_texts) else ""

        result = generate_tts_typecast(api_key, voice_id, text, seg_path,
                                       speed=speed, pitch_shift=pitch_shift,
                                       emotion=seg.get("emotion", ""),
                                       prev_text=prev_text, next_text=next_text,
                                       ep_dir=ep_dir)
        if result == "ok":
            print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] voice={voice_name} — 완료")
        elif result == "forbidden":
            # 403: 해당 speaker의 보이스를 교체하고 재시도 (Lock 보호)
            with _voice_lock:
                if all_voices is None:
                    all_voices = fetch_voices(api_key)
                fallback = None
                if all_voices:
                    used_ids = {v["voice_id"] for v in voice_map.values()} | FORBIDDEN_VOICE_IDS
                    candidates = [(score_voice(v, VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)), v)
                                  for v in all_voices if v["voice_id"] not in used_ids]
                    candidates = [(s, v) for s, v in candidates if s > 0]
                    candidates.sort(key=lambda x: -x[0])
                    if candidates:
                        fallback = candidates[0][1]
                    else:
                        remaining = [v for v in all_voices if v["voice_id"] not in FORBIDDEN_VOICE_IDS
                                     and v["voice_id"] != voice_id]
                        if remaining:
                            fallback = remaining[0]
                if fallback:
                    criteria = VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)
                    voice_map[speaker] = {
                        "voice_id": fallback["voice_id"],
                        "name": fallback["name"],
                        "gender": fallback["gender"],
                        "age": fallback["age"],
                        "speed": criteria.get("speed", 1.0),
                    }
                    # 캐시 즉시 업데이트 (다음 실행 시 403 없이 바로 사용)
                    try:
                        cache_data = {}
                        if voice_cache_path.exists():
                            with open(voice_cache_path, "r", encoding="utf-8") as f:
                                cache_data = json.load(f)
                        cache_data[speaker] = voice_map[speaker]
                        with open(voice_cache_path, "w", encoding="utf-8") as f:
                            json.dump(cache_data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
            if fallback:
                criteria = VOICE_SEARCH_CRITERIA.get(speaker, DEFAULT_CRITERIA)
                print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] 교체 보이스 → {fallback['name']} 재시도...")
                r2 = generate_tts_typecast(api_key, fallback["voice_id"], text, seg_path,
                                           speed=criteria.get("speed", 1.0),
                                           emotion=seg.get("emotion", ""),
                                           ep_dir=ep_dir)
                if r2 == "ok":
                    print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] voice={fallback['name']} — 완료(교체)")
                else:
                    print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 교체 후에도 실패")
            else:
                print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 대체 보이스 없음, 건너뜀")
        else:
            print(f"  [{slide_num:02d}-{seg_idx:02d}] [{speaker}] — 실패")

        return (slide_num, seg_idx, seg, seg_path)

    # Smart Emotion 문맥용: 슬라이드별 세그먼트 텍스트 목록
    _segment_texts = {
        sl.get("slide_number", 0): [sg.get("text", "") for sg in sl.get("tts_segments", [])]
        for sl in slides
    }

    # 전체 세그먼트 목록 수집 (슬라이드 순서 보존)
    all_tasks = []  # (slide_num, seg_idx, seg, seg_path)
    for slide in slides:
        slide_num = slide.get("slide_number", 0)
        segments = slide.get("tts_segments", [])
        if not segments:
            print(f"[슬라이드 {slide_num:02d}] tts_segments 없음 — 건너뜀")
            slide_segments_map[slide_num] = []
            continue
        for seg_idx, seg in enumerate(segments):
            seg_path = audio_dir / f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav"
            all_tasks.append((slide_num, seg_idx, seg, seg_path))

    print(f"[TTS 병렬 생성] 총 {len(all_tasks)}개 세그먼트, max_workers=4")

    # 병렬 실행 — 결과는 완료 순서대로 수신
    results_map: dict[tuple, tuple] = {}  # (slide_num, seg_idx) -> (slide_num, seg_idx, seg, seg_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {
            executor.submit(_generate_one_segment, sn, si, sg, sp): (sn, si)
            for sn, si, sg, sp in all_tasks
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                res = future.result()
                results_map[key] = res
            except Exception as exc:
                sn, si = key
                print(f"  [{sn:02d}-{si:02d}] 예외 발생: {exc}")

    # 결과를 슬라이드/세그먼트 인덱스 순서대로 재정렬하여 slide_segments_map 구성
    for slide in slides:
        slide_num = slide.get("slide_number", 0)
        segments = slide.get("tts_segments", [])
        if not segments:
            continue
        seg_entries = []
        for seg_idx, seg in enumerate(segments):
            key = (slide_num, seg_idx)
            if key in results_map:
                _, _, seg_out, seg_path = results_map[key]
                seg_entries.append((seg_idx, seg_out, seg_path))
            else:
                seg_path = audio_dir / f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav"
                seg_entries.append((seg_idx, seg, seg_path))
        slide_segments_map[slide_num] = seg_entries

        # 슬라이드별 합치기
        existing_seg_paths = [p for _, _, p in seg_entries if p.exists()]
        if existing_seg_paths:
            slide_wav = audio_dir / f"slide_{slide_num:02d}.wav"
            try:
                concat_wav_files(existing_seg_paths, slide_wav)
                print(f"  -> slide_{slide_num:02d}.wav 생성 완료 ({len(existing_seg_paths)}개 합침)")
            except Exception as e:
                print(f"  -> slide_{slide_num:02d}.wav 합치기 실패: {e}")
        print()

    # ------------------------------------------------------------------
    # 2단계: 각 세그먼트 WAV 길이 측정 & timing.json 생성
    # ------------------------------------------------------------------
    print("timing.json 생성 중...")

    timing_segments = []
    timing_slides = []
    cumulative_time = 0.0

    all_slide_nums = sorted(
        set(s.get("slide_number", 0) for s in slides)
    )

    total_segment_count = 0

    for slide_num in all_slide_nums:
        slide_start = cumulative_time

        # 커버 슬라이드 (slide 0, TTS 없음)
        if slide_num == 0:
            cumulative_time += COVER_SLIDE_DURATION
            timing_slides.append({
                "slide": 0,
                "type": "cover",
                "start": round(slide_start, 3),
                "end": round(cumulative_time, 3),
                "duration": round(COVER_SLIDE_DURATION, 3),
            })
            continue

        # 슬라이드 전환 간격
        if slide_num > 1 or (slide_num == 1 and 0 in {s.get("slide_number", 0) for s in slides}):
            cumulative_time += SILENCE_SLIDE_TRANSITION
            slide_start = cumulative_time

        seg_entries = slide_segments_map.get(slide_num, [])
        prev_speaker = None

        for seg_idx, seg, seg_path in seg_entries:
            if not seg_path.exists():
                continue

            speaker = seg.get("speaker", "narrator")
            text = seg.get("text", "")
            duration = get_wav_duration(seg_path)

            # 세그먼트 간 무음 간격
            if prev_speaker is not None:
                if speaker == prev_speaker:
                    cumulative_time += SILENCE_SAME_SPEAKER
                else:
                    cumulative_time += SILENCE_SPEAKER_CHANGE

            seg_start = cumulative_time
            seg_end = cumulative_time + duration

            timing_segments.append({
                "file": f"slide_{slide_num:02d}_seg_{seg_idx:02d}.wav",
                "slide": slide_num,
                "index": seg_idx,
                "speaker": speaker,
                "text": text,
                "duration": round(duration, 3),
                "start": round(seg_start, 3),
                "end": round(seg_end, 3),
            })

            cumulative_time = seg_end
            prev_speaker = speaker
            total_segment_count += 1

        is_last_slide = (slide_num == all_slide_nums[-1])

        slide_type = "story"
        if is_last_slide:
            slide_type = "ending"
            cumulative_time += ENDING_EXTRA_SECONDS

        slide_end = cumulative_time
        slide_duration = slide_end - slide_start

        timing_slides.append({
            "slide": slide_num,
            "type": slide_type,
            "start": round(slide_start, 3),
            "end": round(slide_end, 3),
            "duration": round(slide_duration, 3),
        })

    total_duration = round(cumulative_time, 3)

    timing_data = {
        "segments": timing_segments,
        "slides": timing_slides,
        "total_duration": total_duration,
    }

    timing_path = audio_dir / "timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(timing_data, f, ensure_ascii=False, indent=2)

    print(f"  -> {timing_path} 저장 완료")
    print()

    # ------------------------------------------------------------------
    # 3단계: 요약 출력
    # ------------------------------------------------------------------
    print("=" * 55)
    print(f"  TTS 생성 완료 — 요약 (Typecast {TYPECAST_MODEL})")
    print("=" * 55)
    print(f"  총 세그먼트 수 : {total_segment_count}")
    print(f"  총 재생 시간   : {total_duration:.3f}초 ({total_duration/60:.1f}분)")
    print(f"  보이스 배정    :")
    for speaker, vi in voice_map.items():
        print(f"    {speaker:12s} → {vi['name']} ({vi['gender']}, {vi['age']})")
    print(f"  슬라이드 구성  :")
    for ts in timing_slides:
        print(
            f"    슬라이드 {ts['slide']:02d} [{ts['type']:>7s}] "
            f"{ts['start']:7.3f}s ~ {ts['end']:7.3f}s "
            f"(길이 {ts['duration']:.3f}s)"
        )
    print("=" * 55)

    # ------------------------------------------------------------------
    # 4단계: 퀴즈 대사 TTS 생성
    # ------------------------------------------------------------------
    print("\n[INFO] 퀴즈 대사 TTS 생성 중...")

    # 마스코트 보이스 선택: child_girl → narrator 폴백
    mascot_vi = voice_map.get("child_girl", voice_map.get("narrator", {}))
    mascot_voice_id = mascot_vi.get("voice_id", "")
    mascot_speed = mascot_vi.get("speed", 1.0)

    if not mascot_voice_id:
        print("  [WARN] 마스코트 보이스를 찾을 수 없음 — 퀴즈 TTS 건너뜀")
    else:
        mascot_name = mascot_vi.get("name", "?")
        print(f"  마스코트 보이스: {mascot_name}")

        # 퀴즈 TTS: 문제/정답 읽기 없이 안내 멘트만 생성
        # 문제 슬라이드는 5초 무음으로 표시 (시청자가 직접 읽기)
        # 정답 슬라이드도 5초 무음으로 표시
        quiz_lines = [
            ("quiz_intro", "자, 이제 퀴즈를 풀어볼까요?"),
            ("quiz_q1", "1번 문제입니다!"),
            ("quiz_q2", "2번 문제입니다!"),
            ("quiz_q3", "3번 문제입니다!"),
            ("quiz_a1", "정답입니다!"),
            ("quiz_a2", "정답입니다!"),
            ("quiz_a3", "정답입니다!"),
        ]

        for fname, text in quiz_lines:
            out_path = audio_dir / f"{fname}.wav"
            if out_path.exists():
                print(f"  {fname}.wav — 이미 존재, 건너뜀")
                continue
            ok = generate_tts_typecast(api_key, mascot_voice_id, text, out_path,
                                       speed=mascot_speed, emotion="기쁨",
                                       ep_dir=ep_dir)
            if ok == "ok":
                print(f"  {fname}.wav — 완료")
            else:
                print(f"  {fname}.wav — 실패")

    # ------------------------------------------------------------------
    # 5단계: Shorts 훅 대사 TTS 생성
    # ------------------------------------------------------------------
    shorts_strategy = story.get("shorts_strategy", {})
    hook_line = shorts_strategy.get("hook_line", "")

    if hook_line and mascot_voice_id:
        print(f"\n[INFO] Shorts 훅 TTS 생성 중...")
        print(f"  훅 대사: {hook_line}")
        shorts_hook_path = audio_dir / "shorts_hook.wav"
        if shorts_hook_path.exists():
            print(f"  shorts_hook.wav — 이미 존재, 건너뜀")
        else:
            ok = generate_tts_typecast(api_key, mascot_voice_id, hook_line, shorts_hook_path,
                                       speed=mascot_speed, emotion="신남",
                                       ep_dir=ep_dir)
            if ok == "ok":
                print(f"  shorts_hook.wav — 완료")
            else:
                print(f"  shorts_hook.wav — 실패")
    elif not hook_line:
        print("\n[INFO] shorts_strategy.hook_line 없음 — Shorts 훅 TTS 건너뜀")

    print("\n[DONE] 전체 TTS 생성 완료")


if __name__ == "__main__":
    main()
