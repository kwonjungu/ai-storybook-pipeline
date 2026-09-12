# -*- coding: utf-8 -*-
"""
gen_activity_v2.py
==================
기존 편의 story.json 에 activity_sheet v2 필드(ox_items / sequence_items /
speech_bubbles / fill_blanks / draw / wordplay)를 소급 생성한다.
(gen_loglines.py 의 claude -p 서브프로세스 방식 참고)

- 대상: output/*/publish_log.json 이 존재하는 모든 폴더 (에코의탐험복찾기 제외)
- story.json 에 v2 필드(ox_items 등)가 이미 있으면 건너뜀
- claude -p 로 슬라이드 전문을 주고 스키마 JSON 생성 → 기계 검증 →
  불합격 시 1회 재생성 → activity_sheet 에 병합 저장 (quiz_questions 는 기존 유지)

사용:
  python gen_activity_v2.py                 # 전 대상 폴더
  python gen_activity_v2.py --only <폴더명>  # 부분 매칭 폴더만
  python gen_activity_v2.py --force          # 이미 v2 있어도 재생성
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

EXCLUDE_KEYWORD = "에코의탐험복찾기"

# v2 필드 (이 중 하나라도 있으면 '생성됨'으로 간주)
V2_KEYS = ("ox_items", "sequence_items", "speech_bubbles", "fill_blanks", "draw", "wordplay")


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


def build_prompt(story: dict) -> str:
    meta = story.get("meta", {})
    title = meta.get("story_title", "")
    grade = meta.get("grade", 1)
    names = _main_names(meta)

    # 슬라이드 전문(나레이션 + 대사)을 순서대로
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
    body = "\n".join(lines)

    return f"""당신은 초등 저학년 독후 활동지를 만드는 선생님입니다.
아래 동화의 슬라이드 전문을 읽고, 활동지 데이터(activity_sheet v2)를 JSON으로 만드세요.

[동화 제목] {title}
[주인공] {', '.join(names) if names else '주인공'}
[대상] 초등학교 {grade}학년

[슬라이드 전문]
{body}

[공통 원칙]
- 초등학교 1학년이 읽고 풀 수 있는 쉬운 어휘. 조사(은/는, 이/가, 을/를)와 맞춤법을 정확히.
- 모든 문장은 위 이야기 실제 내용에 근거. 없는 사실을 지어내지 마세요.
- 힌트에는 정답(정답 낱말·정답 대사)을 절대 노출하지 마세요.

[생성할 JSON 스키마]
{{
  "ox_items": [
    {{"text": "이야기 속 사실 문장", "answer": true}},
    {{"text": "이야기 속 사실 문장", "answer": true}},
    {{"text": "틀린 사실 문장", "answer": false}}
  ],
  "sequence_items": [
    {{"label": "A", "text": "초반 사건 1문장", "order": 1}},
    {{"label": "B", "text": "중반 사건 1문장", "order": 2}},
    {{"label": "C", "text": "후반 사건 1문장", "order": 3}}
  ],
  "speech_bubbles": [
    {{"speaker": "캐릭터 실명", "situation": "대사 직전 상황 1문장", "hint": "감정·주제 힌트"}},
    {{"speaker": "캐릭터 실명", "situation": "대사 직전 상황 1문장", "hint": "감정·주제 힌트"}}
  ],
  "fill_blanks": [
    {{"sentence": "___ 빈칸이 든 완성형 문장", "example": "보기 낱말", "answer": "정답"}},
    {{"sentence": "___ 빈칸이 든 완성형 문장", "example": "보기 낱말", "answer": "정답"}}
  ],
  "draw": {{"prompt": "이야기 연계 그리기 발문", "field1_label": "발문 주제에 맞는 라벨1", "field2_label": "발문 주제에 맞는 라벨2"}},
  "wordplay": {{"anagram_words": ["핵심낱말1", "핵심낱말2", "핵심낱말3", "핵심낱말4"], "consonant_words": ["낱말1", "낱말2", "낱말3"]}}
}}

[세부 규칙]
- ox_items: 정확히 3개. O·X(true·false) 비율은 2:1 또는 1:2 (전부 같은 답 금지).
  거짓(false) 문항은 자연스럽고 비문 없는 문장을 새로 쓰되, 같은 인물 이름을 한 문장에
  두 번 넣지 마세요.
- sequence_items: 정확히 3개. 초·중·후반에서 각 1문장. label은 A·B·C, order는 실제 순서.
- speech_bubbles: 2~3개. speaker는 반드시 등장인물의 실제 이름. situation은 대사 직전 상황.
  hint는 정답 대사를 노출하지 말고 감정·주제만.
- fill_blanks: 2개. 완결된 문장 안에 ___ 로 빈칸 1~2개. example은 보기 낱말, answer는 정답.
- draw: field 라벨은 반드시 prompt 주제와 일치. (발문이 음식이면 "음식 이름",
  동물이면 "동물 이름", 초능력이면 "초능력 이름"처럼.)
- wordplay.anagram_words: 3~4글자 핵심 낱말 4개(캐릭터 이름은 최대 1개까지).
  consonant_words: 3~4글자 낱말 3개.

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


def validate(v2: dict, story: dict) -> list[str]:
    """스키마 기계 검증. 반환: 위반 사유 리스트(비어 있으면 합격)."""
    errs = []
    if not isinstance(v2, dict):
        return ["최상위가 dict가 아님"]

    # 필수 키
    for k in V2_KEYS:
        if k not in v2:
            errs.append(f"필수 키 없음: {k}")
    if errs:
        return errs

    names = _all_char_names(story.get("meta", {}))
    main_names = _main_names(story.get("meta", {}))

    # ox_items: 3개, answer bool, O·X 혼재, 거짓문 주인공 이름 중복 없음
    ox = v2.get("ox_items")
    if not isinstance(ox, list) or len(ox) != 3:
        errs.append("ox_items 개수 != 3")
    else:
        bools = []
        for it in ox:
            if not isinstance(it, dict) or not (it.get("text") or "").strip():
                errs.append("ox_items 항목에 text 없음")
                continue
            if not isinstance(it.get("answer"), bool):
                errs.append("ox_items answer가 bool 아님")
            else:
                bools.append(it["answer"])
        if bools and (all(bools) or not any(bools)):
            errs.append("ox_items O·X 비율 불량(전부 같은 답)")
        # 거짓문에 주인공 이름 2회 이상 중복 금지
        for it in ox:
            if isinstance(it, dict) and it.get("answer") is False:
                txt = it.get("text", "")
                for nm in main_names:
                    if nm and txt.count(nm) >= 2:
                        errs.append(f"ox 거짓문에 이름 중복: '{nm}'")

    # sequence_items: 3개, label/order
    seq = v2.get("sequence_items")
    if not isinstance(seq, list) or len(seq) != 3:
        errs.append("sequence_items 개수 != 3")
    else:
        orders = []
        for it in seq:
            if not isinstance(it, dict) or not (it.get("text") or "").strip():
                errs.append("sequence_items 항목에 text 없음")
                continue
            if not str(it.get("label", "")).strip():
                errs.append("sequence_items label 없음")
            orders.append(it.get("order"))
        if sorted([o for o in orders if isinstance(o, int)]) != [1, 2, 3]:
            errs.append("sequence_items order가 1,2,3 아님")

    # speech_bubbles: 2~3개, speaker 실명, situation·hint
    sb = v2.get("speech_bubbles")
    if not isinstance(sb, list) or not (2 <= len(sb) <= 3):
        errs.append("speech_bubbles 개수가 2~3 아님")
    else:
        for it in sb:
            if not isinstance(it, dict):
                errs.append("speech_bubbles 항목 형식 오류")
                continue
            if not (it.get("speaker") or "").strip():
                errs.append("speech_bubbles speaker 없음")
            if not (it.get("situation") or "").strip():
                errs.append("speech_bubbles situation 없음")
            if not (it.get("hint") or "").strip():
                errs.append("speech_bubbles hint 없음")

    # fill_blanks: 2개, sentence에 빈칸, answer
    fb = v2.get("fill_blanks")
    if not isinstance(fb, list) or len(fb) < 2:
        errs.append("fill_blanks 개수 < 2")
    else:
        for it in fb[:2]:
            if not isinstance(it, dict):
                errs.append("fill_blanks 항목 형식 오류")
                continue
            sent = it.get("sentence", "") or ""
            if "_" not in sent:
                errs.append("fill_blanks sentence에 빈칸(___) 없음")
            if not (it.get("answer") or "").strip():
                errs.append("fill_blanks answer 없음")

    # draw: prompt + field 라벨, 라벨-prompt 주제 일치(기계 근사 검사)
    dr = v2.get("draw")
    if not isinstance(dr, dict) or not (dr.get("prompt") or "").strip():
        errs.append("draw.prompt 없음")
    else:
        f1 = (dr.get("field1_label") or "").strip()
        f2 = (dr.get("field2_label") or "").strip()
        if not f1 or not f2:
            errs.append("draw field 라벨 누락")

    # wordplay
    wp = v2.get("wordplay")
    if not isinstance(wp, dict):
        errs.append("wordplay 형식 오류")
    else:
        aw = wp.get("anagram_words")
        cw = wp.get("consonant_words")
        good_aw = [w for w in (aw or []) if isinstance(w, str) and 3 <= len(_clean_han(w)) <= 4]
        if len(good_aw) < 3:
            errs.append("wordplay.anagram_words 3~4글자 낱말 3개 미만")
        # 캐릭터명 최대 1개
        name_hits = sum(1 for w in (aw or []) if isinstance(w, str) and w.strip() in names)
        if name_hits > 1:
            errs.append("wordplay.anagram_words에 캐릭터명 2개 이상")
        good_cw = [w for w in (cw or []) if isinstance(w, str) and len(_clean_han(w)) >= 2]
        if len(good_cw) < 3:
            errs.append("wordplay.consonant_words 3개 미만")

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


def gen_one(d: Path, force: bool):
    """반환: (결과문자열, 재생성횟수)  결과: 'skip'/'ok'/'fail'"""
    story_path = d / "story.json"
    if not story_path.exists():
        return "fail", 0
    story = json.loads(story_path.read_text(encoding="utf-8"))
    act = story.setdefault("activity_sheet", {})

    if any(k in act for k in V2_KEYS) and not force:
        print(f"  [SKIP] 이미 v2 있음: {d.name}")
        return "skip", 0

    prompt = build_prompt(story)
    regens = 0
    v2 = None
    # 최초 1회 + 불합격 시 1회 재생성 = 최대 2회
    for attempt in range(2):
        try:
            out = call_claude(prompt)
            cand = extract_json(out)
            if cand is None:
                raise ValueError("JSON 파싱 실패")
            errs = validate(cand, story)
            if not errs:
                v2 = cand
                break
            print(f"  [검증불합격] {d.name} 시도{attempt+1}: {errs[:4]}")
            if attempt == 0:
                regens += 1
        except Exception as e:
            print(f"  [WARN] {d.name} 시도{attempt+1} 실패: {e}")
            if attempt == 0:
                regens += 1

    if v2 is None:
        print(f"  [FAIL] {d.name}")
        return "fail", regens

    # 병합: quiz_questions 등 기존 값은 유지, v2 필드만 덮어씀
    for k in V2_KEYS:
        if k in v2:
            act[k] = v2[k]
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {d.name}  (재생성 {regens}회)")
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
    ap.add_argument("--force", action="store_true", help="이미 v2 있어도 재생성")
    args = ap.parse_args()

    dirs = target_dirs(args.only)
    print(f"[INFO] 대상 폴더 {len(dirs)}개")
    stats = {"ok": 0, "skip": 0, "fail": 0}
    total_regens = 0
    failed = []
    for d in dirs:
        res, regens = gen_one(d, args.force)
        stats[res] = stats.get(res, 0) + 1
        total_regens += regens
        if res == "fail":
            failed.append(d.name)
    print(f"\n[완료] 생성={stats['ok']} 건너뜀={stats['skip']} 실패={stats['fail']} 재생성총={total_regens}")
    if failed:
        print("[실패 목록]")
        for f in failed:
            print("  -", f)


if __name__ == "__main__":
    main()
