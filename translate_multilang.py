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


def romanize_names(names, lang: str, kinds: dict = None) -> dict:
    """등장인물 한국어 이름 → 읽기 쉬운 라틴 표기. 간판 캐릭터는 고정값 사용.
    kinds(dict)를 주면 새로 정한 이름의 종류(roman=로마자 / meaning=의미번역)를 채워 준다."""
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
            "Return ONLY a JSON object mapping each original name to an object "
            '{"text": converted form, "kind": "roman" or "meaning"} (roman = case 1, meaning = case 2). '
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
            for k, v in json.loads(raw).items():
                if isinstance(v, dict):
                    txt, kind = (v.get("text") or "").strip(), v.get("kind")
                else:
                    txt, kind = (str(v) if v else "").strip(), None
                if not txt:
                    continue
                out[k] = txt
                if kinds is not None:
                    kinds[k] = kind if kind in ("roman", "meaning") else                         ("meaning" if re.search(r"\s", txt) else "roman")
        except Exception as e:
            print(f"  [WARN] 이름 로마자 변환 실패 — 원문 유지: {e}")
    return out


LATIN_LANGS = ("en", "id", "es", "pt")


def resolve_name_map(src_story_path: Path, data: dict, names, lang: str) -> dict:
    """편별 이름표 고정: 한국어 story 의 meta.name_map[lang] 이 있으면 그대로 재사용하고,
    없는 이름만 새로 정해 거기에 저장한다 (실행마다 Kongal/Kongali 처럼 달라지는 것 방지).
    로마자형(kind=roman) 이름은 이미 다른 라틴 언어에서 정했으면 그걸 그대로 쓴다.
    의미번역형(kind=meaning)은 언어별로 따로 정한다."""
    meta = data.setdefault("meta", {})
    nm = meta.setdefault("name_map", {})
    kinds = meta.setdefault("name_map_kind", {})
    cur = nm.setdefault(lang, {})
    changed = False
    todo = []
    for n in names:
        n = (n or "").strip()
        if not n or not _HANGUL_RE.search(n) or n in cur:
            continue
        if n in FIXED_NAME_ROMAN:
            cur[n] = FIXED_NAME_ROMAN[n]; kinds[n] = "roman"; changed = True
            continue
        shared = next((nm[l][n] for l in LATIN_LANGS if l != lang and n in nm.get(l, {})
                       and kinds.get(n) == "roman"), None)
        if shared:
            cur[n] = shared; changed = True
        else:
            todo.append(n)
    if todo:
        new_kinds = {}
        got = romanize_names(todo, lang, new_kinds)
        for k, v in got.items():
            cur[k] = v; kinds[k] = new_kinds.get(k, "roman"); changed = True
    if changed and src_story_path is not None:
        # 한국어 원본에는 meta.name_map / name_map_kind 만 추가 (다른 필드는 그대로)
        raw = json.loads(src_story_path.read_text(encoding="utf-8"))
        rm = raw.setdefault("meta", {})
        rm["name_map"] = nm
        rm["name_map_kind"] = kinds
        src_story_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [이름표 저장] {src_story_path}")
    return {n: cur[n] for n in names if n in cur}


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
- NEVER write sound-effect interjections as narration or dialogue (BOOM!, Thud!, Bang!, Click!, Pop!,
  Pum!, Dor!, Bum! and the like). Sound effects are added later in audio editing. If the Korean has no
  such interjection, do not invent one. Describe the action in words instead
- Some texts contain markup tags: <w1>word</w1> wraps a sound-making word or action in the Korean
  (rolling, fluttering, clapping, sparkling...). Keep the tag and wrap the EXACT matching word or short
  phrase (1-3 words, same grammatical form as in your sentence) in your translation, for example
  "The bean <w1>rolled</w1> in." If the translation has no natural counterpart, drop that tag and keep the text.
  <s1/> marks a pause between two sentences. Keep it at the same sentence boundary, directly after the
  sentence-ending punctuation. Never put a tag inside a quotation or in the middle of a sentence.
  Copy tag names exactly (w1, s1, w2 ...). Do not add tags of your own
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


# ── 효과음 이어받기 (2026-10-12) ───────────────────────────
# 한국어 story 의 의성어 효과음 이벤트(sfx 필드 / audio/sfx_events.json / 텍스트 감지)를 번역본 세그먼트의 `sfx` 필드로 옮긴다.
# start/end 는 그대로, 문장 사이(<sN/>)·겹쳐 깔기(<wN>낱말</wN>)는 번역 때 표식으로 대응 위치를 받아오고,
# 대응을 못 찾으면 그 이벤트는 삭제한다 (엉뚱한 자리에서 소리 나는 것보다 없는 게 낫다).
def plan_sfx(src_dir: Path, data: dict) -> dict:
    """{(slide, seg): [event, ...]} -- 아직 sfx_prep 을 안 거친 편이면 data 의 한국어 텍스트는 의성어를 지운 상태로 바뀐다(메모리만)."""
    import sfx_prep
    ev_p = src_dir / "audio" / "sfx_events.json"
    events = None
    if ev_p.exists():
        try:
            doc = json.loads(ev_p.read_text(encoding="utf-8"))
            if doc.get("text_done"):
                events = doc.get("events", [])
        except Exception:
            events = None
    if events is None:  # sfx_prep 을 안 거친 한국어 편: 메모리에서 같은 규칙으로 감지
        events = []
        for sl in data.get("slides", []):
            n = sl.get("slide_number")
            for si, seg in enumerate(sl.get("tts_segments") or []):
                if seg.get("sfx"):
                    events.extend(sfx_prep.process_segment_field(n, si, seg))
                elif seg.get("speaker", "narrator") == "narrator":
                    new_text, evs = sfx_prep.process_segment_legacy(n, si, seg)
                    seg["text"] = new_text
                    events.extend(evs)
    by = {}
    for e in events:
        by.setdefault((e["slide"], e["seg"]), []).append(e)
    return by


def mark_segment(text: str, evs: list):
    """한국어 text 에 표식을 심는다 -> (표식 text, [mark dict])."""
    marks, ins = [], []  # ins: (pos, kind, event)
    for e in evs:
        if e["mode"] == "pre":
            marks.append({"kind": "start", "type": e["sfx"], "count": len(e.get("offsets") or [1])})
        elif e["mode"] == "post":
            marks.append({"kind": "end", "type": e["sfx"], "count": len(e.get("offsets") or [1])})
        elif e["mode"] == "gap":
            idx = (e.get("prep") or {}).get("after_index")
            if idx is None or idx <= 0 or idx >= len(text.rstrip()):
                continue
            ins.append((idx, "s", e))
        elif e["mode"] == "word":
            k = text.find(e.get("word", ""))
            if e.get("word") and k >= 0:
                ins.append((k, "w", e))
    n = 0
    marked = text
    for pos, kind, e in sorted(ins, key=lambda t: -t[0]):
        n += 1
        mid = f"{kind}{n}"
        if kind == "s":
            marked = marked[:pos].rstrip() + f" <{mid}/> " + marked[pos:].lstrip()
        else:
            w = e["word"]
            marked = marked[:pos] + f"<{mid}>{w}</{mid}>" + marked[pos + len(w):]
        marks.append({"kind": "gap" if kind == "s" else "word", "type": e["sfx"], "id": mid})
    return marked, marks


_END_PUNCT = tuple(".?!…\"”'’)")


def resolve_segment(translated: str, marks: list, lang: str = None, names=()):
    """번역문에서 표식을 걷어 -> (최종 text, sfx 필드 목록, 버린 표식 수). 대응을 못 찾은 표식은 이벤트째 삭제."""
    sfx, dropped = [], 0
    text = translated
    if lang:  # 모델이 규칙을 어기고 쓴 소리 흉내 감탄("Snap!", "¡Pum!")은 대사에서 뺀다 (효과음은 sfx 필드가 맡는다)
        import sfx_prep
        if lang in sfx_prep.LATIN_LEX:
            for a, b, _ in reversed(sfx_prep.find_replace_runs_latin(text, lang, names)):
                rest = (text[:a] + text[b:]).strip()
                if re.search(r"[A-Za-zÀ-ÿ]", rest):
                    text = (text[:a].rstrip() + " " + text[b:].lstrip()).strip()
    for m in [m for m in marks if m["kind"] in ("gap", "word")]:
        mid = m["id"]
        if m["kind"] == "gap":
            mt = re.search(r"\s*<%s\s*/>\s*" % mid, text)
            if not mt:  # 모델이 태그를 'S1' 처럼 맨 글자로 바꿔 쓴 경우(2026-10-13 인니 사고)
                mt = re.search(r"\s*(?<![A-Za-z0-9])%s(?![A-Za-z0-9])\s*" % mid.upper(), text)
            if not mt:
                dropped += 1
                continue
            pre, post = text[:mt.start()].rstrip(), text[mt.end():].lstrip()
            text = (pre + " " + post).strip()
            if not pre or not pre.endswith(_END_PUNCT):
                dropped += 1
            elif not post:
                sfx.append({"type": m["type"], "where": "end", "count": 1})
            else:
                sfx.append({"type": m["type"], "where": "after", "after_text": pre, "count": 1})
        else:
            mt = re.search(r"<%s>(.*?)</%s>" % (mid, mid), text, re.S)
            if not mt:
                dropped += 1
                continue
            w = mt.group(1).strip()
            text = text[:mt.start()] + mt.group(1) + text[mt.end():]
            if w and len(w.split()) <= 4 and w in text:
                sfx.append({"type": m["type"], "where": "word", "word": w})
            else:
                dropped += 1
    text = re.sub(r"</?[sw]\d+\s*/?>", "", text)  # 남은 표식 제거
    text = re.sub(r"(?<![A-Za-z0-9])S\d{1,2}(?![A-Za-z0-9])\s*", "", text)  # 맨 글자로 남은 문장 사이 표식
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    simple = [{"type": m["type"], "where": m["kind"], "count": m["count"]} for m in marks if m["kind"] in ("start", "end")]
    return text, simple + sfx, dropped


def translate_story(src_dir: Path, lang: str, dst_dir: Path = None, copy_anim: bool = False):
    cfg = LANG_CONFIG[lang]
    src_story = src_dir / "story.json"
    dst_dir = Path(dst_dir) if dst_dir else src_dir.parent / f"{src_dir.name}_{lang}"
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
    name_map = resolve_name_map(src_story, data, cand, lang)
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
    sfx_by = plan_sfx(src_dir, data)
    seg_marks = {}
    slide_fields = {}
    for s in data["slides"]:
        n = s["slide_number"]
        slide_fields[f"slide_{n}_text"] = s["text"]
        for i, seg in enumerate(s.get("tts_segments", [])):
            mk_text, mk = mark_segment(seg["text"], sfx_by.get((n, i), []))
            seg_marks[(n, i)] = mk
            slide_fields[f"slide_{n}_tts_{i}"] = mk_text
    print(f"    효과음 이벤트 {sum(len(v) for v in sfx_by.values())}개 이어받기 대상")
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

    if lang in ("en", "es"):
        # 영어·스페인어는 Typecast ssfm-v30이 지원(es는 2026-10-11 실측) → 기존 캐릭터 보이스 그대로 재사용
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
            s["text"] = re.sub(r"\s*</?[sw]\d+\s*/?>\s*", " ", slide_tr[key]).strip()  # 슬라이드 본문엔 표식이 없어야 한다
        for i, seg in enumerate(s.get("tts_segments", [])):
            tts_key = f"slide_{n}_tts_{i}"
            seg.pop("sfx", None)  # 한국어 sfx 필드(after_text/word 가 한국어)는 그대로 못 쓴다
            if tts_key in slide_tr:
                seg["text"], new_sfx, nd = resolve_segment(slide_tr[tts_key], seg_marks.get((n, i), []), lang, list(name_map.values()))
                if new_sfx:
                    seg["sfx"] = new_sfx
                if nd:
                    print(f"    [효과음 삭제] {n}-{i}: 번역문에서 대응 위치를 못 찾은 표식 {nd}개")
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
        _clean = lambda x: re.sub(r"\s*</?[sw]\d+\s*/?>\s*", " ", x).strip()   # 번역 모델이 흘린 표식 제거
        if f"q{i}_question" in quiz_tr:
            q["question"] = _clean(quiz_tr[f"q{i}_question"])
        if f"q{i}_answer" in quiz_tr:
            q["answer"] = _clean(quiz_tr[f"q{i}_answer"])

    # ── 저장 ───────────────────────────────────────────────
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_story.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] story.json 저장: {dst_story}")

    # ── 애니 클립 복사 (옵션) ─────────────────────────────
    if copy_anim and (src_dir / "anim").exists() and not (dst_dir / "anim").exists():
        shutil.copytree(src_dir / "anim", dst_dir / "anim")
        print("[애니] anim 복사")

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
    parser.add_argument("--dst", default=None, help="출력 폴더 직접 지정 (--lang 하나일 때만)")
    parser.add_argument("--copy-anim", action="store_true", help="원본 anim/ 클립도 복사")
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
        translate_story(src_dir, lang, Path(args.dst) if (args.dst and not args.all) else None, args.copy_anim)

    print("\n[완료] 모든 번역 작업 종료.")


if __name__ == "__main__":
    main()
