# -*- coding: utf-8 -*-
"""
gen_activity_v2.py
==================
story.json 에 activity_sheet v2.1 필드를 생성한다. (07 활동지는 이 데이터를 그리기만 한다)

v2.1 (2026-09-26, 활동지 전수조사 후속):
- 모든 문항에 evidence(근거가 된 원문 문장)를 붙이고, evidence가 실제 원문에
  들어 있는지 기계 대조 → 원문에 없는 사실·인물·낱말 차단
- quiz_review: 영상 퀴즈(quiz_questions)의 문구는 그대로 두고 활동지용 정답·예시답을
  원문 근거로 다시 확인 (영상 퀴즈 정답이 원문과 어긋난 편 보정)
- mood_items(화자·상황이 있는 기분 고르기), cast(본문에 실제 나오는 인물),
  draw.frame(그림틀 모양), wordplay.consonant_items(초성+뜻 힌트) 신설

- 대상: output/*/publish_log.json 이 존재하는 모든 폴더 (에코의탐험복찾기 제외)
- claude -p 로 슬라이드 전문을 주고 스키마 JSON 생성 → 기계 검증 →
  불합격 시 사유를 붙여 재생성(최대 3회) → activity_sheet 에 병합 저장

사용:
  python gen_activity_v2.py                 # 전 대상 폴더 (v2.1 없는 편만)
  python gen_activity_v2.py --only <폴더명>  # 부분 매칭 폴더만
  python gen_activity_v2.py --force          # 이미 v2.1 있어도 재생성
  python gen_activity_v2.py --workers 4      # 병렬 생성
  python gen_activity_v2.py --check          # 생성 없이 기존 데이터 검증만
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

EXCLUDE_KEYWORD = "에코의탐험복찾기"

SCHEMA_VERSION = "2.1"
V2_KEYS = ("ox_items", "sequence_items", "speech_bubbles", "fill_blanks", "draw", "wordplay",
           "mood_items", "cast", "quiz_review")
DRAW_FRAMES = ("rect", "egg", "circle", "window", "plate")
MOOD_POOL = ["기쁨", "슬픔", "설렘", "걱정", "신남", "속상함", "놀람", "뿌듯함",
             "무서움", "미안함", "고마움", "부끄러움", "화남", "편안함"]


# ══════════════════════════════════════════════════════════════════════════
# 프롬프트
# ══════════════════════════════════════════════════════════════════════════

def _main_names(meta: dict):
    chars = meta.get("characters", {})
    names = []
    for k in ("main_1", "main_2"):
        ch = chars.get(k) or {}
        if ch.get("name"):
            names.append(ch["name"])
    return names


def _all_char_names(meta: dict):
    chars = meta.get("characters", {})
    names = []
    for k in ("main_1", "main_2"):
        ch = chars.get(k) or {}
        if ch.get("name"):
            names.append(ch["name"])
    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        for v in sup.values():
            if isinstance(v, dict) and v.get("name"):
                names.append(v["name"])
    return names


def story_lines(story: dict) -> list[str]:
    """슬라이드 전문(나레이션+대사)을 순서대로 '[슬라이드N/화자] 문장' 목록으로."""
    lines = []
    for s in story.get("slides", []):
        if s.get("type") == "cover":
            continue
        num = s.get("slide_number")
        for seg in s.get("tts_segments", []):
            spk = seg.get("speaker", "")
            t = (seg.get("text", "") or "").strip()
            if t:
                lines.append(f"[슬라이드{num}/{spk}] {t}")
    return lines


def _norm(t: str) -> str:
    """대조용 정규화: 한글·영숫자만 남김 (공백·문장부호·따옴표 차이 무시)."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", t or "")


def story_corpus(story: dict) -> str:
    """원문 대조용 코퍼스: 슬라이드 본문(text) + TTS 세그먼트 전부."""
    parts = []
    for s in story.get("slides", []):
        if s.get("type") == "cover":
            continue
        parts.append(s.get("text", "") or "")
        for seg in s.get("tts_segments", []):
            parts.append(seg.get("text", "") or "")
    return _norm(" ".join(parts))


def build_prompt(story: dict, feedback: list[str] | None = None) -> str:
    meta = story.get("meta", {})
    title = meta.get("story_title", "")
    grade = meta.get("grade", 1)
    names = _main_names(meta)
    body = "\n".join(story_lines(story))
    unit = " ".join(str(x) for x in (meta.get("series", ""), meta.get("unit_title", ""),
                                      meta.get("sub_unit", "")) if x)
    quiz = story.get("activity_sheet", {}).get("quiz_questions", []) or []
    quiz_txt = "\n".join(f"{i}. {q.get('question','')} (영상 정답: {q.get('answer','')})"
                         for i, q in enumerate(quiz)) or "(없음)"
    fb = ""
    if feedback:
        fb = "\n[직전 생성본의 검증 불합격 사유 — 반드시 고쳐서 다시 만드세요]\n" + \
             "\n".join(f"- {e}" for e in feedback[:12]) + "\n"

    return f"""당신은 초등 저학년 독후 활동지를 만드는 선생님입니다.
아래 동화의 슬라이드 전문을 읽고, 활동지 데이터(activity_sheet v2.1)를 JSON으로 만드세요.

[동화 제목] {title}
[주인공] {', '.join(names) if names else '주인공'}
[대상] 초등학교 {grade}학년
[교과 단원] {unit or '(없음)'}

[슬라이드 전문]
{body}

[영상 퀴즈 문항 — 문구는 바꾸지 않습니다]
{quiz_txt}
{fb}
[공통 원칙]
- 초등학교 1학년이 읽고 풀 수 있는 쉬운 어휘. 조사(은/는, 이/가, 을/를)와 맞춤법을 정확히.
- 모든 문항은 위 이야기 실제 내용에 근거. 없는 사실·인물·낱말을 지어내지 마세요.
- 모든 문항의 "evidence"에는 근거가 된 원문 문장을 슬라이드 전문에서 **글자 그대로 복사**하세요
  (앞의 [슬라이드N/화자] 표시는 빼고, 한 문장 또는 한 세그먼트). 요약·변형 금지.
- 힌트에는 정답(정답 낱말·정답 대사)을 절대 노출하지 마세요.

[생성할 JSON 스키마]
{{
  "cast": ["이야기 본문에 실제로 이름이 나오는 등장인물 이름"],
  "quiz_review": [
    {{"q_index": 0, "answer": "원문으로 확인한 정답(25자 이내)", "example_answer": "교사용 예시답 한 문장",
      "evidence": "원문 문장 그대로", "video_answer_ok": true}}
  ],
  "ox_items": [
    {{"text": "이야기 속 사실 문장", "answer": true, "evidence": "원문 문장 그대로"}},
    {{"text": "이야기 속 사실 문장", "answer": true, "evidence": "..."}},
    {{"text": "틀린 사실 문장", "answer": false, "evidence": "이 문장을 틀리게 만든 근거 원문"}}
  ],
  "sequence_items": [
    {{"label": "A", "text": "사건 1문장", "order": 2, "evidence": "..."}},
    {{"label": "B", "text": "사건 1문장", "order": 3, "evidence": "..."}},
    {{"label": "C", "text": "사건 1문장", "order": 1, "evidence": "..."}}
  ],
  "speech_bubbles": [
    {{"speaker": "캐릭터 실명", "situation": "대사 직전 상황 1문장", "hint": "감정·주제 힌트", "evidence": "그 인물이 실제로 한 대사 원문"}}
  ],
  "fill_blanks": [
    {{"sentence": "___ 빈칸이 든 완성형 문장", "answer": "정답", "distractor": "그럴듯한 오답 낱말", "evidence": "..."}}
  ],
  "mood_items": [
    {{"speaker": "캐릭터 실명", "situation": "그 인물이 겪은 구체적 상황 1문장", "choices": ["기쁨","슬픔","설렘","걱정"], "answer": "기쁨", "evidence": "..."}}
  ],
  "draw": {{"prompt": "이야기·단원 연계 그리기 발문", "frame": "rect", "field1_label": "발문 주제에 맞는 라벨1", "field2_label": "발문 주제에 맞는 라벨2"}},
  "wordplay": {{
    "anagram_words": ["핵심낱말1", "핵심낱말2", "핵심낱말3", "핵심낱말4"],
    "consonant_items": [{{"word": "낱말", "hint": "뜻 힌트(낱말 미노출)"}}]
  }}
}}

[세부 규칙]
- cast: 슬라이드 전문에 이름이 실제로 등장하는 인물만 (주인공 포함, 2~5명).
- quiz_review: 영상 퀴즈 문항마다 1개(q_index 0부터). 원문으로 정답을 다시 확인해 answer에 쓰고,
  영상 정답이 원문과 어긋나면 video_answer_ok=false. evidence는 정답의 근거 문장.
- ox_items: 정확히 3개. O·X 비율은 2:1 또는 1:2. 거짓 문장은 자연스럽고 비문 없이 새로 쓰되,
  한 문장에 같은 이름을 두 번 넣지 마세요. 참 문장도 원문을 그대로 베끼지 말고 쉬운 말로 바꿔 쓰세요.
- sequence_items: 정확히 3개. 초·중·후반 사건 각 1문장. label은 A·B·C, order는 실제 순서(1~3).
  A·B·C의 order가 1·2·3 순서 그대로가 되지 않게 섞어서 배정하세요.
- speech_bubbles: 2~3개. speaker는 cast 안의 이름. situation은 대사 직전 상황. hint는 감정·주제만.
- fill_blanks: 2개. 빈칸(___) 1개. 두 정답은 서로 달라야 하고, 주인공 이름이 정답인 문항은 최대 1개.
  정답 낱말은 evidence 문장 안에 들어 있어야 합니다. distractor는 보기 상자에 섞을 오답 낱말
  (정답과 품사·길이가 비슷하지만 이야기상 틀린 말, 정답들과 겹치지 않게).
- mood_items: 2~3개. 인물(speaker)과 구체적 상황이 있는 장면만. 교훈 문장·배경 묘사 금지.
  choices는 서로 다른 감정 낱말 4개, answer는 choices 중 원문 근거로 가장 알맞은 것 1개.
- draw.frame: rect(기본 사각), egg(알 차시만), circle(얼굴·해·접시 등 둥근 대상), window(상상 창문),
  plate(음식·식판). field 라벨은 반드시 prompt 주제와 일치.
- wordplay.anagram_words: 이야기에 나오는 3~4글자 낱말 4개 (캐릭터 이름은 최대 1개).
  consonant_items: 이야기에 나오는 2~4글자 낱말 3개, 각각 1학년이 알 수 있는 뜻 힌트.

순수 JSON만 출력하세요. 마크다운 코드블록(```)이나 설명 텍스트를 절대 포함하지 마세요."""


# ══════════════════════════════════════════════════════════════════════════
# 파싱 + 검증
# ══════════════════════════════════════════════════════════════════════════

def extract_json(text: str) -> dict | None:
    """claude 출력에서 첫 번째 완결 JSON 오브젝트 추출."""
    t = text.strip()
    # 코드블록 제거
    if "```" in t:
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
        if m:
            t = m.group(1).strip()
    # 첫 { ~ 대응하는 } 까지 균형 스캔
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


def _clean_han(w: str) -> str:
    return "".join(c for c in (w or "") if 0xAC00 <= ord(c) <= 0xD7A3)



def _in_corpus(ev: str, corpus: str) -> bool:
    n = _norm(ev)
    return len(n) >= 4 and n in corpus


def validate(v2: dict, story: dict) -> list[str]:
    """스키마 + 원문 근거 기계 검증. 반환: 위반 사유 리스트(비어 있으면 합격)."""
    errs = []
    if not isinstance(v2, dict):
        return ["최상위가 dict가 아님"]
    for k in V2_KEYS:
        if not v2.get(k):
            errs.append(f"필수 키 없음: {k}")
    if errs:
        return errs

    meta = story.get("meta", {})
    corpus = story_corpus(story)
    main_names = _main_names(meta)
    quiz = story.get("activity_sheet", {}).get("quiz_questions", []) or []

    def ev_check(tag, it):
        ev = (it.get("evidence") or "").strip() if isinstance(it, dict) else ""
        if not ev:
            errs.append(f"{tag}: evidence 없음")
        elif not _in_corpus(ev, corpus):
            errs.append(f"{tag}: evidence가 원문에 없음 → '{ev[:30]}'")

    # cast
    cast = v2.get("cast")
    if not isinstance(cast, list) or not cast:
        errs.append("cast 비어 있음")
        cast = []
    for nm in cast:
        if not isinstance(nm, str) or _norm(nm) not in corpus:
            errs.append(f"cast에 원문에 없는 이름: {nm}")
    cast_set = {c for c in cast if isinstance(c, str)}

    # quiz_review
    qr = v2.get("quiz_review")
    if not isinstance(qr, list) or len(qr) != len(quiz):
        errs.append(f"quiz_review 개수({len(qr) if isinstance(qr, list) else 0}) != 퀴즈 수({len(quiz)})")
    else:
        for i, it in enumerate(qr):
            if not isinstance(it, dict) or not (it.get("answer") or "").strip():
                errs.append(f"quiz_review[{i}] answer 없음")
                continue
            if it.get("q_index") != i:
                errs.append(f"quiz_review[{i}] q_index 불일치")
            ev_check(f"quiz_review[{i}]", it)

    # ox
    ox = v2.get("ox_items")
    if not isinstance(ox, list) or len(ox) != 3:
        errs.append("ox_items 개수 != 3")
    else:
        bools = []
        for i, it in enumerate(ox):
            if not isinstance(it, dict) or not (it.get("text") or "").strip():
                errs.append("ox_items 항목에 text 없음")
                continue
            if not isinstance(it.get("answer"), bool):
                errs.append("ox_items answer가 bool 아님")
            else:
                bools.append(it["answer"])
            ev_check(f"ox_items[{i}]", it)
            for nm in main_names:
                if nm and it["text"].count(nm) >= 2:
                    errs.append(f"ox 문장에 이름 중복: '{nm}'")
        if bools and (all(bools) or not any(bools)):
            errs.append("ox_items O·X 비율 불량(전부 같은 답)")

    # sequence
    seq = v2.get("sequence_items")
    if not isinstance(seq, list) or len(seq) != 3:
        errs.append("sequence_items 개수 != 3")
    else:
        orders = []
        for i, it in enumerate(seq):
            if not isinstance(it, dict) or not (it.get("text") or "").strip():
                errs.append("sequence_items 항목에 text 없음")
                continue
            if str(it.get("label", "")).strip().upper() not in ("A", "B", "C"):
                errs.append("sequence_items label이 A·B·C 아님")
            orders.append(it.get("order"))
            ev_check(f"sequence_items[{i}]", it)
        if sorted([o for o in orders if isinstance(o, int)]) != [1, 2, 3]:
            errs.append("sequence_items order가 1,2,3 아님")

    # speech bubbles
    sb = v2.get("speech_bubbles")
    if not isinstance(sb, list) or not (2 <= len(sb) <= 3):
        errs.append("speech_bubbles 개수가 2~3 아님")
    else:
        for i, it in enumerate(sb):
            if not isinstance(it, dict):
                errs.append("speech_bubbles 항목 형식 오류")
                continue
            spk = (it.get("speaker") or "").strip()
            if spk not in cast_set:
                errs.append(f"speech_bubbles speaker가 cast에 없음: {spk}")
            if not (it.get("situation") or "").strip():
                errs.append("speech_bubbles situation 없음")
            hint = (it.get("hint") or "").strip()
            if not hint:
                errs.append("speech_bubbles hint 없음")
            elif len(_norm(hint)) >= 8 and _norm(hint) in corpus:
                errs.append(f"speech_bubbles[{i}] hint가 원문 대사를 그대로 노출")
            ev_check(f"speech_bubbles[{i}]", it)

    # fill blanks
    fb = v2.get("fill_blanks")
    if not isinstance(fb, list) or len(fb) < 2:
        errs.append("fill_blanks 개수 < 2")
    else:
        answers = []
        for i, it in enumerate(fb[:3]):
            if not isinstance(it, dict):
                errs.append("fill_blanks 항목 형식 오류")
                continue
            sent = it.get("sentence", "") or ""
            ans = (it.get("answer") or "").strip()
            if "_" not in sent:
                errs.append("fill_blanks sentence에 빈칸(___) 없음")
            if not ans:
                errs.append("fill_blanks answer 없음")
            answers.append(ans)
            ev_check(f"fill_blanks[{i}]", it)
            if ans and _norm(ans) not in _norm(it.get("evidence", "")):
                errs.append(f"fill_blanks[{i}] 정답 '{ans}'이 evidence 문장에 없음")
            dis = (it.get("distractor") or "").strip()
            if not dis or dis == ans:
                errs.append(f"fill_blanks[{i}] distractor 없음 또는 정답과 같음")
        if len(set(answers)) != len(answers):
            errs.append("fill_blanks 정답이 중복됨")
        if sum(1 for a in answers if a in main_names) > 1:
            errs.append("fill_blanks 정답 중 주인공 이름이 2개 이상")

    # mood
    mi = v2.get("mood_items")
    if not isinstance(mi, list) or not (2 <= len(mi) <= 3):
        errs.append("mood_items 개수가 2~3 아님")
    else:
        for i, it in enumerate(mi):
            if not isinstance(it, dict):
                errs.append("mood_items 형식 오류")
                continue
            spk = (it.get("speaker") or "").strip()
            if spk not in cast_set:
                errs.append(f"mood_items speaker가 cast에 없음: {spk}")
            ch = it.get("choices")
            if not isinstance(ch, list) or len(ch) != 4 or len(set(ch)) != 4:
                errs.append(f"mood_items[{i}] choices가 서로 다른 4개 아님")
            elif it.get("answer") not in ch:
                errs.append(f"mood_items[{i}] answer가 choices에 없음")
            ev_check(f"mood_items[{i}]", it)

    # draw
    dr = v2.get("draw")
    if not isinstance(dr, dict) or not (dr.get("prompt") or "").strip():
        errs.append("draw.prompt 없음")
    else:
        if not (dr.get("field1_label") or "").strip() or not (dr.get("field2_label") or "").strip():
            errs.append("draw field 라벨 누락")
        if dr.get("frame") not in DRAW_FRAMES:
            errs.append(f"draw.frame이 {DRAW_FRAMES} 중 하나가 아님")

    # wordplay
    wp = v2.get("wordplay")
    if not isinstance(wp, dict):
        errs.append("wordplay 형식 오류")
    else:
        aw = [w for w in (wp.get("anagram_words") or []) if isinstance(w, str)]
        good_aw = [w for w in aw if 3 <= len(_clean_han(w)) <= 4 and len(set(_clean_han(w))) >= 2]
        if len(good_aw) < 3:
            errs.append("anagram_words 3~4글자 낱말 3개 미만")
        for w in aw:
            if _clean_han(w) and _clean_han(w) not in corpus:
                errs.append(f"anagram_words '{w}'가 원문에 없음")
        if sum(1 for w in aw if w.strip() in cast_set) > 1:
            errs.append("anagram_words에 캐릭터명 2개 이상")
        ci = wp.get("consonant_items")
        if not isinstance(ci, list) or len(ci) < 3:
            errs.append("consonant_items 3개 미만")
        else:
            for it in ci:
                w = _clean_han((it or {}).get("word", ""))
                h = ((it or {}).get("hint") or "").strip()
                if not (2 <= len(w) <= 4):
                    errs.append(f"consonant_items 낱말 길이 불량: {w}")
                elif w not in corpus:
                    errs.append(f"consonant_items '{w}'가 원문에 없음")
                if not h:
                    errs.append(f"consonant_items '{w}' 뜻 힌트 없음")
                elif w and w in _norm(h):
                    errs.append(f"consonant_items '{w}' 힌트에 정답 노출")
    return errs


# ══════════════════════════════════════════════════════════════════════════
# 생성
# ══════════════════════════════════════════════════════════════════════════

def call_claude(prompt: str) -> str:
    r = subprocess.run(
        ["claude", "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env=_CLAUDE_ENV,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude 종료코드 {r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout



def gen_one(d: Path, force: bool, check_only: bool = False):
    """반환: (결과문자열, 재생성횟수)  결과: 'skip'/'ok'/'fail'"""
    story_path = d / "story.json"
    if not story_path.exists():
        return "fail", 0
    story = json.loads(story_path.read_text(encoding="utf-8"))
    act = story.setdefault("activity_sheet", {})

    if check_only:
        errs = validate({k: act.get(k) for k in V2_KEYS}, story)
        print(f"  [{'PASS' if not errs else 'FAIL'}] {d.name}" + (f": {errs[:5]}" if errs else ""))
        return ("ok" if not errs else "fail"), 0

    if act.get("schema") == SCHEMA_VERSION and not force:
        print(f"  [SKIP] 이미 v{SCHEMA_VERSION}: {d.name}")
        return "skip", 0

    regens = 0
    v2 = None
    feedback = None
    for attempt in range(3):
        try:
            out = call_claude(build_prompt(story, feedback))
            cand = extract_json(out)
            if cand is None:
                raise ValueError("JSON 파싱 실패")
            errs = validate(cand, story)
            if not errs:
                v2 = cand
                break
            print(f"  [검증불합격] {d.name} 시도{attempt+1}: {errs[:4]}")
            feedback = errs
        except Exception as e:
            print(f"  [WARN] {d.name} 시도{attempt+1} 실패: {e}")
        regens += 1

    if v2 is None:
        print(f"  [FAIL] {d.name}")
        return "fail", regens

    # 병합: quiz_questions(영상과 공유)는 유지, v2.1 필드만 덮어씀
    story = json.loads(story_path.read_text(encoding="utf-8"))
    act = story.setdefault("activity_sheet", {})
    for k in V2_KEYS:
        act[k] = v2[k]
    act["schema"] = SCHEMA_VERSION
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = [r["q_index"] for r in v2["quiz_review"] if r.get("video_answer_ok") is False]
    note = f"  ⚠ 영상 퀴즈 정답 불일치 q{bad}" if bad else ""
    print(f"  [OK] {d.name}  (재생성 {regens}회){note}")
    return "ok", regens


def target_dirs(only: str = None):
    dirs = []
    for pl in sorted(Path("output").glob("*/publish_log.json")):
        d = pl.parent
        if EXCLUDE_KEYWORD in d.name:
            continue
        if only and only not in d.name:
            continue
        dirs.append(d)
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="특정 폴더명(부분 매칭)만")
    ap.add_argument("--dir", default=None, help="publish_log 없는 폴더도 직접 지정")
    ap.add_argument("--force", action="store_true", help="이미 v2.1 있어도 재생성")
    ap.add_argument("--check", action="store_true", help="생성 없이 기존 데이터 검증만")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    dirs = [Path(args.dir)] if args.dir else target_dirs(args.only)
    print(f"[INFO] 대상 폴더 {len(dirs)}개")
    stats = {"ok": 0, "skip": 0, "fail": 0}
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        results = list(ex.map(lambda d: (d, gen_one(d, args.force, args.check)), dirs))
    total_regens = 0
    for d, (res, regens) in results:
        stats[res] = stats.get(res, 0) + 1
        total_regens += regens
        if res == "fail":
            failed.append(d.name)
    print(f"\n[완료] 합격/생성={stats['ok']} 건너뜀={stats['skip']} 실패={stats['fail']} 재생성총={total_regens}")
    if failed:
        print("[실패 목록]")
        for f in failed:
            print("  -", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
