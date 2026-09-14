#!/usr/bin/env python3
"""
translate_multilang.py
한국어 story.json → 다국어 번역 범용 스크립트

사용법:
  python translate_multilang.py --src output/bsl08 --lang en
  python translate_multilang.py --src output/bsl08 --lang pt
  python translate_multilang.py --src output/bsl08 --lang id
  python translate_multilang.py --src output/bsl08 --lang es
  python translate_multilang.py --src output/bsl08 --all   # en/pt/id/es 한 번에

출력: output/{src_name}_{lang}/story.json (이미지는 원본에서 심볼릭 링크 또는 복사)
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── 언어별 설정 ─────────────────────────────────────────────
LANG_CONFIG = {
    "en": {
        "name": "English",
        "quiz_tts": {
            "quiz_intro": "Let's do a quiz!",
            "quiz_q1": "Question 1!",
            "quiz_q2": "Question 2!",
            "quiz_q3": "Question 3!",
            "quiz_a1": "That's correct!",
            "quiz_a2": "That's correct!",
            "quiz_a3": "That's correct!",
        },
        "prompt_lang": "English suitable for children aged 7-8. Use natural, expressive, and fun language.",
    },
    "pt": {
        "name": "Portuguese (Brazilian)",
        "quiz_tts": {
            "quiz_intro": "Vamos fazer um quiz!",
            "quiz_q1": "Primeira pergunta!",
            "quiz_q2": "Segunda pergunta!",
            "quiz_q3": "Terceira pergunta!",
            "quiz_a1": "Correto!",
            "quiz_a2": "Correto!",
            "quiz_a3": "Correto!",
        },
        "prompt_lang": "Brazilian Portuguese suitable for children aged 7-8. Use natural, expressive, and fun language.",
    },
    "id": {
        "name": "Bahasa Indonesia",
        "quiz_tts": {
            "quiz_intro": "Saatnya kuis!",
            "quiz_q1": "Pertanyaan pertama!",
            "quiz_q2": "Pertanyaan kedua!",
            "quiz_q3": "Pertanyaan ketiga!",
            "quiz_a1": "Benar sekali!",
            "quiz_a2": "Benar sekali!",
            "quiz_a3": "Benar sekali!",
        },
        "prompt_lang": "Bahasa Indonesia sederhana dan menyenangkan untuk anak usia 7-8 tahun.",
    },
    "es": {
        "name": "Spanish (Latin American)",
        "quiz_tts": {
            "quiz_intro": "¡Hagamos un quiz!",
            "quiz_q1": "¡Primera pregunta!",
            "quiz_q2": "¡Segunda pregunta!",
            "quiz_q3": "¡Tercera pregunta!",
            "quiz_a1": "¡Correcto!",
            "quiz_a2": "¡Correcto!",
            "quiz_a3": "¡Correcto!",
        },
        "prompt_lang": "Spanish (Latin American) suitable for children aged 7-8. Use natural, expressive, and fun language.",
    },
}

# ElevenLabs 보이스 매핑 (다국어 TTS용)
ELEVENLABS_VOICES = {
    "narrator":   {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "stability": 0.5,  "similarity_boost": 0.75},
    "child_boy":  {"voice_id": "ErXwobaYiN019PkySvjV",  "name": "Antoni",  "stability": 0.5,  "similarity_boost": 0.75},
    "child_girl": {"voice_id": "MF3mGyEYCl7XYWbV9V6O",  "name": "Elli",    "stability": 0.5,  "similarity_boost": 0.75},
    "teacher":    {"voice_id": "VR6AewLTigWG4xSOukaG",  "name": "Arnold",  "stability": 0.6,  "similarity_boost": 0.80},
    "main_1":     {"voice_id": "MF3mGyEYCl7XYWbV9V6O",  "name": "Elli",    "stability": 0.5,  "similarity_boost": 0.75},
    "main_2":     {"voice_id": "ErXwobaYiN019PkySvjV",  "name": "Antoni",  "stability": 0.5,  "similarity_boost": 0.75},
}


# ── 캐릭터 이름 로마자 표기 ──────────────────────────────
# 번역 모델에 맡기면 "삐요 → Ppiyo"처럼 TTS가 "Peep-Peep-O"로 읽는 표기가 나온다.
# → 번역 '전에' 한국어 이름을 라틴 표기로 미리 치환하고, 모델에는 "라틴 이름은 그대로 두라"고 지시한다.
# 간판 캐릭터는 채널 브랜딩(HAMZZI 소개문 "Piyo the chick and Toto the turtle")과 반드시 일치해야 함.
FIXED_NAME_ROMAN = {
    "삐요": "Piyo", "토토": "Toto", "햄찌": "Hamzzi",
}

_HANGUL_RE = re.compile(r"[가-힣]")


def romanize_names(names, lang: str) -> dict:
    """등장인물 한국어 이름 → 읽기 쉬운 라틴 표기. 간판 캐릭터는 고정값 사용."""
    out, todo = {}, []
    for n in names:
        n = (n or "").strip()
        if not n or not _HANGUL_RE.search(n):
            continue
        if n in FIXED_NAME_ROMAN:
            out[n] = FIXED_NAME_ROMAN[n]
        else:
            todo.append(n)
    if todo:
        prompt = (
            f"Convert these Korean storybook character names for a {LANG_CONFIG[lang]['name']} audience. "
            "Two cases. "
            "1) INVENTED proper name (a made-up nickname such as 삐요, 토토, 느리): romanize it "
            "phonetically. No doubled initial consonants (never Pp, Tt, Kk), no apostrophes, "
            "no hyphens, short, Title Case. "
            "2) DESCRIPTIVE name made of common nouns (such as 까치 어미 = mother magpie, "
            "개구리 아저씨 = uncle frog): do NOT romanize. Translate it naturally into the target "
            "language as a warm storybook name a child understands, for example Mother Magpie, Mr. Frog. "
            "A text-to-speech engine must read the result correctly. "
            "Return ONLY a JSON object mapping each original name to its converted form. "
            + json.dumps(todo, ensure_ascii=False)
        )
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = r.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                raw = raw[4:] if raw.startswith("json") else raw
                raw = raw.strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            out.update({k: v for k, v in json.loads(raw).items() if v})
        except Exception as e:
            print(f"  [WARN] 이름 로마자 변환 실패 — 원문 유지: {e}")
    return out


def apply_name_map(text: str, name_map: dict) -> str:
    """긴 이름부터 치환 (부분 문자열 충돌 방지)."""
    if not text or not name_map:
        return text
    for ko in sorted(name_map, key=len, reverse=True):
        text = text.replace(ko, name_map[ko])
    return text


def build_translate_prompt(fields_dict: dict, lang: str) -> str:
    cfg = LANG_CONFIG[lang]
    return f"""You are an expert translator for children's content (ages 7-8).
Translate the following Korean text into {cfg['prompt_lang']}

Rules:
- Natural and expressive, NOT literal translation
- Keep the emotional nuance and excitement
- Character names are ALREADY written in the Latin alphabet. Copy them EXACTLY as given,
  never re-spell, translate, or add doubled consonants to them
- No special characters like ..., —, ― (use only periods and commas)
- Return ONLY valid JSON, no extra text, no markdown

Fields to translate:
{json.dumps(fields_dict, ensure_ascii=False, indent=2)}

Return JSON with the exact same structure, only text values translated.
"""


def translate_texts(fields_dict: dict, lang: str, retries: int = 3) -> dict:
    prompt = build_translate_prompt(fields_dict, lang)
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  [WARN] JSON 파싱 실패 (시도 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
        except Exception as e:
            print(f"  [WARN] API 오류 (시도 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"번역 실패: {retries}회 시도 후 포기")


def translate_story(src_dir: Path, lang: str):
    cfg = LANG_CONFIG[lang]
    src_story = src_dir / "story.json"
    dst_dir = src_dir.parent / f"{src_dir.name}_{lang}"
    dst_story = dst_dir / "story.json"

    print(f"\n{'='*60}")
    print(f"[번역] {src_dir.name} → {dst_dir.name}  ({cfg['name']})")
    print(f"{'='*60}")

    data = json.loads(src_story.read_text(encoding="utf-8"))

    # ── [0] 캐릭터 이름 라틴 표기 (번역 전 사전 치환) ──────
    chars = data.get("meta", {}).get("characters", {}) or {}
    cand = []
    for key in ("main_1", "main_2"):
        c = chars.get(key) or {}
        if isinstance(c, dict) and c.get("name"):
            cand.append(c["name"])
    for c in (chars.get("supporting") or {}).values():
        if isinstance(c, dict) and c.get("name"):
            cand.append(c["name"])
    name_map = romanize_names(cand, lang)
    if name_map:
        print("[0] 이름 로마자: " + ", ".join(f"{k}→{v}" for k, v in name_map.items()))

    def tr(fields: dict) -> dict:
        """이름을 라틴 표기로 치환한 뒤 번역."""
        return translate_texts({k: apply_name_map(v, name_map) for k, v in fields.items()}, lang)

    # ── meta 번역 ──────────────────────────────────────────
    print("[1] meta 번역...")
    meta_fields = {
        "story_title":   data["meta"]["story_title"],
        "youtube_title": data["meta"]["youtube_title"],
    }
    if (data["meta"].get("logline") or "").strip():
        meta_fields["logline"] = data["meta"]["logline"]
    meta_tr = tr(meta_fields)

    # ── slides 번역 ────────────────────────────────────────
    print("[2] slides 번역...")
    slide_fields = {}
    for s in data["slides"]:
        n = s["slide_number"]
        slide_fields[f"slide_{n}_text"] = s["text"]
        for i, seg in enumerate(s.get("tts_segments", [])):
            slide_fields[f"slide_{n}_tts_{i}"] = seg["text"]
    slide_tr = tr(slide_fields)

    # ── shorts_strategy 번역 ───────────────────────────────
    print("[3] shorts_strategy 번역...")
    shorts_fields = {
        "hook_line": data["shorts_strategy"]["hook_line"],
        "title":     data["shorts_strategy"]["title"],
    }
    shorts_tr = tr(shorts_fields)

    # ── thumbnail 번역 ─────────────────────────────────────
    print("[4] thumbnail 번역...")
    thumb_fields = {
        "text":     data["thumbnail"]["text"],
        "sub_text": data["thumbnail"]["sub_text"],
    }
    thumb_tr = tr(thumb_fields)

    # ── quiz_questions 번역 ────────────────────────────────
    print("[5] quiz_questions 번역...")
    quiz_fields = {}
    for i, q in enumerate(data["activity_sheet"]["quiz_questions"]):
        quiz_fields[f"q{i}_question"] = q["question"]
        quiz_fields[f"q{i}_answer"]   = q["answer"]
    quiz_tr = tr(quiz_fields)

    # ── 번역 결과 적용 ─────────────────────────────────────
    print("[6] 번역 결과 적용...")

    data["meta"]["language"]      = lang
    data["meta"]["story_title"]   = meta_tr.get("story_title",   data["meta"]["story_title"])
    data["meta"]["youtube_title"] = meta_tr.get("youtube_title", data["meta"]["youtube_title"])
    if "logline" in meta_tr:
        data["meta"]["logline"] = meta_tr["logline"]   # 설명란 본문에 그대로 쓰임

    # 캐릭터 이름을 라틴 표기로 교체 (설명란/태그에 한국어 이름이 새는 것 방지)
    for key in ("main_1", "main_2"):
        c = chars.get(key)
        if isinstance(c, dict) and c.get("name") in name_map:
            c["name"] = name_map[c["name"]]
    for c in (chars.get("supporting") or {}).values():
        if isinstance(c, dict) and c.get("name") in name_map:
            c["name"] = name_map[c["name"]]

    if lang == "en":
        # 영어는 Typecast가 ko/en 둘 다 지원(ssfm-v30) → 기존 캐릭터 보이스 그대로 재사용
        # (같은 voice_id에 language="eng"만 바꿔 호출, 03_generate_tts.py --engine typecast)
        data["meta"].pop("supertone_voices", None)
    else:
        # 그 외 언어는 ElevenLabs 보이스로 교체 (기존 방식 유지)
        data["meta"].pop("typecast_voices", None)
        data["meta"].pop("supertone_voices", None)
        data["meta"]["elevenlabs_voices"] = ELEVENLABS_VOICES

    # quiz_tts 추가
    data["meta"]["quiz_tts"] = cfg["quiz_tts"]

    # slides
    for s in data["slides"]:
        n = s["slide_number"]
        key = f"slide_{n}_text"
        if key in slide_tr:
            s["text"] = slide_tr[key]
        for i, seg in enumerate(s.get("tts_segments", [])):
            tts_key = f"slide_{n}_tts_{i}"
            if tts_key in slide_tr:
                seg["text"] = slide_tr[tts_key]
            # voice 필드 확인 (Gemini/ElevenLabs용)
            if "speaker" in seg and "voice" not in seg:
                seg["voice"] = seg["speaker"]

    # shorts_strategy
    data["shorts_strategy"]["hook_line"] = shorts_tr.get("hook_line", data["shorts_strategy"]["hook_line"])
    data["shorts_strategy"]["title"]     = shorts_tr.get("title",     data["shorts_strategy"]["title"])

    # thumbnail
    data["thumbnail"]["text"]     = thumb_tr.get("text",     data["thumbnail"]["text"])
    data["thumbnail"]["sub_text"] = thumb_tr.get("sub_text", data["thumbnail"]["sub_text"])

    # quiz_questions
    for i, q in enumerate(data["activity_sheet"]["quiz_questions"]):
        if f"q{i}_question" in quiz_tr:
            q["question"] = quiz_tr[f"q{i}_question"]
        if f"q{i}_answer" in quiz_tr:
            q["answer"] = quiz_tr[f"q{i}_answer"]

    # ── 저장 ───────────────────────────────────────────────
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_story.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] story.json 저장: {dst_story}")

    # ── 이미지 복사 ────────────────────────────────────────
    src_images = src_dir / "images"
    dst_images = dst_dir / "images"
    if src_images.exists() and not dst_images.exists():
        print(f"[이미지] {src_images} → {dst_images} 복사...")
        shutil.copytree(src_images, dst_images)
        print(f"[이미지] 복사 완료 ({len(list(dst_images.glob('*.png')))}장)")
    elif dst_images.exists():
        print(f"[이미지] 이미 존재 — 건너뜀")
    else:
        print(f"[이미지] 원본 이미지 없음 — 건너뜀 (먼저 02_generate_images.py 실행)")

    # ── shorts_plan.json 복사 ──────────────────────────────
    src_shorts = src_dir / "shorts_plan.json"
    dst_shorts = dst_dir / "shorts_plan.json"
    if src_shorts.exists() and not dst_shorts.exists():
        shutil.copy2(src_shorts, dst_shorts)
        print(f"[복사] shorts_plan.json")

    # ── 미리보기 ───────────────────────────────────────────
    print("\n=== 번역 미리보기 ===")
    print(f"  story_title:   {data['meta']['story_title']}")
    print(f"  youtube_title: {data['meta']['youtube_title']}")
    if data["slides"]:
        print(f"  slide_1 text:  {data['slides'][1]['text'][:60]}...")
    print(f"  hook_line:     {data['shorts_strategy']['hook_line']}")
    print(f"  thumbnail:     {data['thumbnail']['text']} / {data['thumbnail']['sub_text']}")
    print(f"  quiz_q1:       {data['activity_sheet']['quiz_questions'][0]['question']}")
    print()

    print(f"\n[다음 단계] {dst_dir.name} 파이프라인 실행:")
    print(f"  python 03_generate_tts_gemini.py --dir {dst_dir}")
    print(f"  python 04_concat_audio.py --dir {dst_dir}")
    print(f"  python 05_generate_srt.py --dir {dst_dir}")
    print(f"  python 07b_generate_quiz_slides.py --dir {dst_dir}")
    print(f"  python 09b_smart_shorts.py --dir {dst_dir}")
    print(f"  python 10_generate_thumbnail.py --dir {dst_dir}")
    print(f"  python 06_assemble_video.py --dir {dst_dir}")


def main():
    parser = argparse.ArgumentParser(description="한국어 story.json → 다국어 번역")
    parser.add_argument("--src", required=True, help="원본 폴더 경로 (예: output/bsl08)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--lang", choices=list(LANG_CONFIG.keys()), help="대상 언어")
    group.add_argument("--all", action="store_true", help="en/pt/id/es 모두 번역")
    args = parser.parse_args()

    src_dir = Path(args.src)
    if not (src_dir / "story.json").exists():
        print(f"[ERROR] {src_dir}/story.json 없음")
        sys.exit(1)

    langs = list(LANG_CONFIG.keys()) if args.all else [args.lang]

    for lang in langs:
        translate_story(src_dir, lang)

    print("\n[완료] 모든 번역 작업 종료.")


if __name__ == "__main__":
    main()
