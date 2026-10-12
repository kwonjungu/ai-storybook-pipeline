#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sfx_prep.py -- 의성어 효과음 전처리 (ko 기본 + en/es/id/pt 어휘표). 2단계로 나뉜다.
(언어는 story.json meta.language. 새 언어는 아래 LATIN_LEX 에 한 항목만 추가하면 된다.)

[1단계: 텍스트]  03(TTS) 실행 *전*     python sfx_prep.py --dir output/폴더
  - 세그먼트의 `sfx` 필드가 있으면 그것을 우선 사용 (01 스토리 생성 프롬프트가 만든다)
  - 없는 기존 스토리는 텍스트에서 감탄형 의성어("쿵! 쿵!", "찰칵!")를 찾아 지우고 효과음으로 대체
    (narrator 문장만, 따옴표 대사/다른 화자 대사/이름("쿵쿵이")/대사 속 감탄("에취!")은 그대로)
  - 문장 속 부사("데굴데굴 굴러왔어요", "손뼉을 짝")는 말로 두고 효과음을 겹쳐 깔기만 한다
  - emotion 필드의 소리 문구("발소리를 묵직하게")도 정리
  - 바뀐 세그먼트의 wav 만 지운다 -> 03 이 그 세그먼트만 (유료 TTS) 다시 만든다
  - 결과: audio/sfx_events.json, 원본 보존: story.pre_sfx.json (1회)

[2단계: 패딩]   tts_gate 통과 후, 04 직전   python sfx_prep.py --dir output/폴더 --pad
  - 대체 효과음 자리를 세그먼트 wav 에 확보(선행 0.5초 무음 / 문장 사이 0.3초 / 끝 0.4~0.5초)
  - timing.json 을 새 길이로 밀어 준다 (04/05/06 은 timing.json 을 그대로 쓴다)

이후 04 -> 직후 sfx_mix.py. 이벤트가 없으면 아무것도 하지 않고 통과(exit 0).
이미 업로드된 편(publish_log.json 있음)은 건드리지 않는다 (--allow-published 로만 우회).
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

import sfx_lib
from sfx_common import read_wav, write_wav, envelope, silences, char_time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---- 어휘 (ko) ---------------------------------------------------------------
# 감탄형으로 단독 문장일 때 -> 대체: 토큰 -> (효과음, 횟수)
REPLACE_LEX = {
    "쿵": ("thump", 1), "쿵쿵": ("thump", 2), "쿵쿵쿵": ("thump", 3),
    "찰칵": ("shutter", 1),
    "짝": ("clap", 1), "짝짝": ("clap", 2),
    "퐁": ("pop", 1), "퐁퐁": ("pop_pop", 1),
    "반짝": ("sparkle", 1), "반짝반짝": ("sparkle", 1),
    "펄럭펄럭": ("flutter", 1), "쭈욱": ("swish", 1), "데굴데굴": ("roll", 1),
}
# 문장 속 부사 -> 겹쳐 깔기: 단어 -> 효과음 (긴 단어 먼저)
WORD_LEX = [("펄럭펄럭", "flutter"), ("데굴데굴", "roll"), ("반짝반짝", "sparkle"), ("퐁퐁", "pop_pop"),
            ("쭈욱", "swish"), ("반짝", "sparkle"), ("쿵", "thump"), ("짝", "clap")]
# 음량: 대사 RMS 대비 dB (피크 기준, 대사 RMS 보다 낮게)
GAIN_REPLACE = {"thump": -4, "shutter": -5, "clap": -6, "pop": -6, "pop_pop": -7, "sparkle": -8,
                "flutter": -9, "swish": -8, "roll": -8}
GAIN_WORD = {"flutter": -11, "swish": -10, "pop_pop": -9, "clap": -8, "roll": -10, "sparkle": -10,
             "thump": -8, "pop": -9, "shutter": -9}
SPACING = {"thump": 0.52}  # 반복 간격(초), 그 외 0.35
HANGUL = "가-힣"

# ---- 어휘 (라틴 문자 언어: en/es/id/pt) -----------------------------------------
# 새 언어 추가 = LATIN_LEX 에 항목 하나. replace: 단독 감탄(문장 전체가 "Boom!") -> (효과음, 횟수),
# word: 문장 속 낱말(정규식, 전체 일치) -> 효과음 [겹쳐 깔기]. 일반 낱말 오탐을 피하려고 동사 활용형 위주로만 둔다.
LATIN_LEX = {
    "en": {
        "replace": {
            "boom": ("thump", 1), "thud": ("thump", 1), "thump": ("thump", 1), "bang": ("thump", 1),
            "click": ("shutter", 1), "snap": ("shutter", 1), "clap": ("clap", 1), "pop": ("pop", 1),
            "crash": ("thump", 1), "whoosh": ("swish", 1), "swoosh": ("swish", 1), "flap": ("flutter", 1),
        },
        "word": [
            (r"fluttered|fluttering|flapped|flapping", "flutter"),
            (r"rolled|rolling", "roll"),
            (r"sparkled|twinkled|glittered|glimmered", "sparkle"),
            (r"clapped|clapping", "clap"),
            (r"popped|popping", "pop"),
            (r"thudded|thumped", "thump"),
            (r"whooshed|swooshed|whoosh|swoosh", "swish"),
        ],
    },
    "es": {
        "replace": {
            "pum": ("thump", 1), "bum": ("thump", 1), "pam": ("thump", 1), "crac": ("shutter", 1), "catapum": ("thump", 1), "zas": ("swish", 1), "clic": ("shutter", 1), "click": ("shutter", 1),
            "plas": ("clap", 1), "pop": ("pop", 1), "plop": ("pop", 1), "zas": ("swish", 1), "fium": ("swish", 1),
        },
        "word": [
            (r"revolote\w*|alete\w*|ondeaba\w*|ondeó|ondeando", "flutter"),
            (r"rodó|rodaron|rodaba|rodaban|rodando", "roll"),
            (r"centelle\w*|destelló|destellaron|titiló|titilaba\w*|titilando", "sparkle"),
            (r"aplaudió|aplaudieron|aplaudiendo|aplaudía\w*", "clap"),
            (r"retumb\w*", "thump"),
        ],
    },
    "id": {
        "replace": {
            "dug": ("thump", 1), "duk": ("thump", 1), "bum": ("thump", 1), "dum": ("thump", 1),
            "cekrek": ("shutter", 1), "klik": ("shutter", 1), "plok": ("pop", 1), "pop": ("pop", 1),
            "plak": ("clap", 1), "prok": ("clap", 1),
        },
        "word": [
            (r"berkibar\w*|mengepak\w*|berkepak\w*", "flutter"),
            (r"berguling\w*|menggelinding|bergulir|menggelundung", "roll"),
            (r"berkilau\w*|berkelap-kelip|gemerlap\w*|berkilat", "sparkle"),
            (r"bertepuk\w*", "clap"),
            (r"berdebum|berdebam|berdebuk", "thump"),
        ],
    },
    "pt": {
        "replace": {
            "bum": ("thump", 1), "pum": ("thump", 1), "baque": ("thump", 1), "clique": ("shutter", 1), "click": ("shutter", 1),
            "plá": ("clap", 1), "pla": ("clap", 1), "pop": ("pop", 1), "pof": ("pop", 1), "zum": ("swish", 1),
        },
        "word": [
            (r"esvoaç\w*|adej\w*|tremul\w*", "flutter"),
            (r"rolou|rolaram|rolava|rolavam|rolando", "roll"),
            (r"cintil\w*|faísc\w*|faisc\w*", "sparkle"),
            (r"aplaudiu|aplaudiram|aplaudindo|aplaudia\w*", "clap"),
        ],
    },
}
_LC = "a-záéíóúàâãêõüñçA-ZÁÉÍÓÚÀÂÃÊÕÜÑÇ"
_LOWER_CONT = re.compile(r"\s*[a-záéíóúàâãêõüñç¿]")


def _spacing(name):
    return SPACING.get(name, 0.35)


def _mask_quotes(text):
    """따옴표 안쪽을 같은 길이의 'Q' 로 가려 매칭에서 제외."""
    def blank(m):
        s = m.group(0)
        return s[0] + "Q" * (len(s) - 2) + s[-1]
    return re.sub(r'“[^”]*”|"[^"]*"|‘[^’]*’', blank, text)


_TOK = "|".join(sorted(map(re.escape, REPLACE_LEX), key=len, reverse=True))
# 문장 시작(문두/마침표 뒤) + (토큰!)+ ; 바로 뒤에 '하고/하며..' 가 이어지면 문장 속 표현이라 제외
_RUN = re.compile(r"(?:(?<=^)|(?<=[.?!]\s)|(?<=[.?!]))\s*((?:(?:%s)!\s*)+)(?!하[고며는게면자더])" % _TOK)


def find_replace_runs(text):
    """text 에서 단독 감탄형 의성어 덩어리 [(start, end, [(sfx, count), ...])]."""
    m_text = _mask_quotes(text)
    out = []
    for m in _RUN.finditer(m_text):
        a, b = m.start(1), m.end(1)
        items = [REPLACE_LEX[tm.group(1)] for tm in re.finditer(r"(%s)!" % _TOK, m_text[a:b])]
        if items:
            out.append((a, b, items))
    return out


def clean_text(text):
    return re.sub(r"\s{2,}", " ", text).strip()


_EMO_DROP_TOK = {"살려서", "살려", "살리며", "늘이며", "늘려서", "느낌을", "순간을"}


def clean_emotion(emo):
    """emotion 에서 소리 묘사 토큰을 걷어낸다 ('발소리를', '쭈욱 소리를 길게 늘이며' ...)."""
    if not emo:
        return emo
    drop_words = {w for w, _ in WORD_LEX} | set(REPLACE_LEX)
    toks = emo.split()
    out = []
    skip_next = None  # 소리/의성어 토큰 바로 뒤의 군더더기 수식 제거용
    for t in toks:
        base = re.sub(r"[을를은는이가의]$", "", t)
        if skip_next == "sound" and t in ("길게", "짧게", "또렷하게"):
            skip_next = None
            continue
        if skip_next == "word" and t.endswith("는"):
            skip_next = None
            continue
        skip_next = None
        if "소리" in t:
            skip_next = "sound"
            continue
        if base in drop_words or t in _EMO_DROP_TOK:
            skip_next = "word" if base in drop_words else None
            continue
        if t in ("하는", "하며", "하고"):
            continue
        out.append(t)
    while out and out[-1] in ("하는", "하며", "하고", "그리고"):
        out.pop()
    res = " ".join(out).strip()
    return res if res else "또박또박 차분하게"


_LATIN_RUN_CACHE = {}


def _latin_run_re(lang):
    if lang not in _LATIN_RUN_CACHE:
        toks = "|".join(sorted(map(re.escape, LATIN_LEX[lang]["replace"]), key=len, reverse=True))
        item = r"¡?(?:%s)(?![%s])" % (toks, _LC)
        run = r"%s(?:[\s,\-]+%s)*\s*!+" % (item, item)
        _LATIN_RUN_CACHE[lang] = (
            re.compile(r"(?:^|(?<=[.?!…])\s*)((?:%s\s*)+)" % run, re.I),
            re.compile(r"(%s)" % item, re.I))
    return _LATIN_RUN_CACHE[lang]


def find_replace_runs_latin(text, lang, names=()):
    """라틴 문자 언어: 문장 전체가 소리 흉내 감탄인 덩어리 [(start, end, [(sfx, count), ...])].
    뒤에 소문자로 이어지면("Pop! went the balloon") 문장 속 표현이라 제외, 등장인물 이름과 같으면 제외."""
    lex = LATIN_LEX[lang]["replace"]
    nm = {n.lower() for n in names}
    run_re, item_re = _latin_run_re(lang)
    m_text = _mask_quotes(text)
    out = []
    for m in run_re.finditer(m_text):
        a, b = m.start(1), m.end(1)
        if _LOWER_CONT.match(m_text, b):
            continue
        toks = [t.lower().lstrip("¡") for t in item_re.findall(m_text[a:b])]
        if not toks or any(t in nm for t in toks):
            continue
        out.append((a, b, [lex[t] for t in toks]))
    return out


def find_word_latin(text, lang, names=()):
    """겹쳐 깔기 후보 [(낱말, 효과음)] -- 낱말은 text 에 나온 그대로(대소문자 포함)."""
    m_text = _mask_quotes(text)
    nm = {n.lower() for n in names}
    out = []
    for pat, name in LATIN_LEX[lang]["word"]:
        m = re.search(r"(?<![%s])(?:%s)(?![%s])" % (_LC, pat, _LC), m_text, re.I)
        if m and m.group(0).lower() not in nm:
            out.append((text[m.start():m.end()], name))
    return out


def _event(slide, seg, sfx, mode, source, note, **kw):
    e = {"slide": slide, "seg": seg, "sfx": sfx, "mode": mode, "source": source, "note": note}
    e.update(kw)
    return e


def _pre_event(slide, seg, sfx, count, source, note, gain):
    sp = _spacing(sfx)
    offsets = [round(0.1 + sp * k, 3) for k in range(max(1, count))]
    pre = max(0.5, offsets[-1] - 0.12) if sfx == "thump" else max(0.5, offsets[-1] + 0.3)
    return _event(slide, seg, sfx, "pre", source, note, offsets=offsets, gain_db=gain,
                  prep={"preroll": round(pre, 3)})


def _post_event(slide, seg, sfx, count, source, note, gain):
    sp = _spacing(sfx)
    offsets = [round(0.05 + sp * k, 3) for k in range(max(1, count))]
    return _event(slide, seg, sfx, "post", source, note, offsets=offsets, gain_db=gain,
                  prep={"postroll": round(offsets[-1] + 0.4, 3)})


def _gap_event(slide, seg, sfx, idx, source, note, gain):
    return _event(slide, seg, sfx, "gap", source, note, gain_db=gain,
                  prep={"gap_insert": 0.3, "after_index": idx})


def _word_event(slide, seg, sfx, word, source, note):
    return _event(slide, seg, sfx, "word", source, note, word=word, gain_db=GAIN_WORD.get(sfx, -10))


# ---- 1단계: 텍스트 -------------------------------------------------------------
def process_segment_legacy(slide, si, seg, lang="ko", names=()):
    """sfx 필드 없는 narrator 세그먼트에서 의성어를 찾아 (새 텍스트, 이벤트들) 반환."""
    text = seg.get("text", "")
    events = []
    latin = lang != "ko"
    runs = find_replace_runs_latin(text, lang, names) if latin else find_replace_runs(text)
    if runs:
        # 지운 뒤 텍스트
        new, prev = "", 0
        for a, b, _ in runs:
            new += text[prev:a]
            prev = b
        new = clean_text(new + text[prev:])
        if not re.search(r"[%s]" % (_LC if latin else HANGUL), new):
            print(f"  [건너뜀] {slide}-{si}: 의성어만 있는 세그먼트라 지우면 비어 있음 (그대로 둠) {text!r}")
        else:
            for a, b, items in runs:
                prefix = clean_text(_remove_runs_before(text, runs, a))
                pos = len(prefix)
                merged = []
                for name, cnt in items:  # '쿵! 쿵!' -> thump x2 한 이벤트
                    if merged and merged[-1][0] == name:
                        merged[-1][1] += cnt
                    else:
                        merged.append([name, cnt])
                for name, cnt in merged:
                    g = GAIN_REPLACE.get(name, -6)
                    note = f"{name} x{cnt} (대체)"
                    if pos <= 0:
                        events.append(_pre_event(slide, si, name, cnt, "text", note, g))
                    elif pos >= len(new):
                        events.append(_post_event(slide, si, name, cnt, "text", note, g))
                    else:
                        events.append(_gap_event(slide, si, name, pos, "text", note, g))
            text = new
    # 겹쳐 깔기 (대체 이벤트가 이미 있는 세그먼트는 건너뜀)
    if not events and latin:
        for w, name in find_word_latin(text, lang, names):
            events.append(_word_event(slide, si, name, w, "text", "겹쳐 깔기"))
    elif not events:
        m_text = _mask_quotes(text)
        seen = set()
        for w, name in WORD_LEX:
            m = re.search(r"(?<![%s])%s(?=\s)" % (HANGUL, re.escape(w)), m_text)
            if m and name not in seen:
                seen.add(name)
                events.append(_word_event(slide, si, name, w, "text", "겹쳐 깔기"))
    return text, events


def _remove_runs_before(text, runs, upto):
    """upto 이전의 모든 run 을 지운 text[:upto]."""
    out, prev = "", 0
    for a, b, _ in runs:
        if a >= upto:
            break
        out += text[prev:a]
        prev = b
    return out + text[prev:upto]


def process_segment_field(slide, si, seg):
    """segment['sfx'] 필드(01 프롬프트 규격)를 이벤트로 변환."""
    text = seg.get("text", "")
    events = []
    for it in seg.get("sfx") or []:
        name = it.get("type")
        where = it.get("where", "start")
        if name not in sfx_lib.SFX:
            print(f"  [경고] {slide}-{si}: 알 수 없는 sfx type {name!r} 무시")
            continue
        cnt = int(it.get("count", 1) or 1)
        g = GAIN_REPLACE.get(name, -6)
        if where == "start":
            events.append(_pre_event(slide, si, name, cnt, "field", f"{name} x{cnt} (필드)", g))
        elif where == "end":
            events.append(_post_event(slide, si, name, cnt, "field", f"{name} x{cnt} (필드)", g))
        elif where == "after":
            at = it.get("after_text", "")
            k = text.find(at) if at else -1
            if k < 0:
                print(f"  [경고] {slide}-{si}: after_text {at!r} 가 text 에 없음 -> 무시")
                continue
            idx = k + len(at)
            if idx >= len(text.rstrip()):
                events.append(_post_event(slide, si, name, cnt, "field", f"{name} (필드,끝)", g))
            else:
                events.append(_gap_event(slide, si, name, idx, "field", f"{name} (필드)", g))
        elif where == "word":
            w = it.get("word", "")
            if not w or w not in text:
                print(f"  [경고] {slide}-{si}: word {w!r} 가 text 에 없음 -> 무시")
                continue
            events.append(_word_event(slide, si, name, w, "field", "겹쳐 깔기(필드)"))
        else:
            print(f"  [경고] {slide}-{si}: 알 수 없는 where {where!r} 무시")
    return events


def _char_names(story):
    """등장인물 이름(번역본은 라틴 표기) -- 의성어 오탐 제외용."""
    ch = story.get("meta", {}).get("characters", {}) or {}
    out = []
    for k, v in ch.items():
        if isinstance(v, dict):
            if v.get("name"):
                out.append(v["name"])
            for vv in v.values():
                if isinstance(vv, dict) and vv.get("name"):
                    out.append(vv["name"])
    return out


def phase_text(ep, allow_published=False, force=False, dry_run=False):
    story_p = ep / "story.json"
    audio = ep / "audio"
    ev_p = audio / "sfx_events.json"
    if (ep / "publish_log.json").exists() and not allow_published and not dry_run:
        print("[sfx_prep] 이미 업로드된 편(publish_log.json) -- 건드리지 않음")
        return 0
    story = json.loads(story_p.read_text(encoding="utf-8"))
    lang = story.get("meta", {}).get("language", "ko")
    if lang != "ko" and lang not in LATIN_LEX:
        print(f"[sfx_prep] 언어 {lang}: 어휘표 없음(LATIN_LEX 에 추가하면 지원) -- 통과")
        return 0
    names = _char_names(story)
    if ev_p.exists() and not force and not dry_run:
        try:
            if json.loads(ev_p.read_text(encoding="utf-8")).get("text_done"):
                print("[sfx_prep] 텍스트 단계 이미 완료 -- 통과")
                return 0
        except Exception:
            pass
    events, changed = [], []
    has_field = lang != "ko" and any(g.get("sfx") for sl in story.get("slides", []) for g in (sl.get("tts_segments") or []))
    for sl in story.get("slides", []):
        n = sl.get("slide_number")
        for si, seg in enumerate(sl.get("tts_segments") or []):
            before = (seg.get("text"), seg.get("emotion"))
            evs = []
            if has_field and not seg.get("sfx"):
                pass  # 번역본이 한국어 이벤트를 이어받은 편: 이벤트 없는 세그먼트는 의도적으로 비운 것 -> 어휘 감지 안 함
            elif seg.get("sfx"):
                evs = process_segment_field(n, si, seg)
            elif seg.get("speaker", "narrator") == "narrator":
                new_text, evs = process_segment_legacy(n, si, seg, lang, names)
                seg["text"] = new_text
            if evs and re.search(r"[%s]" % HANGUL, seg.get("emotion", "")):  # 번역본 emotion 은 한국어 그대로인 경우가 많다
                seg["emotion"] = clean_emotion(seg.get("emotion", ""))
                events.extend(evs)
            if (seg.get("text"), seg.get("emotion")) != before:
                changed.append((n, si))
    if dry_run:
        print(f"[sfx_prep --dry-run] 언어 {lang}: 이벤트 {len(events)}개, 텍스트 수정 세그먼트 {len(changed)}개 (파일 수정 없음)")
        orig = {(sl.get("slide_number"), si): g.get("text") for sl in json.loads(story_p.read_text(encoding="utf-8")).get("slides", [])
                for si, g in enumerate(sl.get("tts_segments") or [])}
        for e in events:
            print(f"   {e['slide']:>2}-{e['seg']} {e['sfx']:8s} {e['mode']:5s} {e.get('word') or ''} {e['note']}")
            print(f"        원문: {orig.get((e['slide'], e['seg']))!r}")
        return 0
    audio.mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "lang": lang, "text_done": True, "events": events}
    if changed:
        bak = ep / "story.pre_sfx.json"
        if not bak.exists():
            bak.write_text(story_p.read_text(encoding="utf-8"), encoding="utf-8")
        story_p.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    ev_p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    # 바뀐 세그먼트 wav 삭제 -> 03 이 그것만 다시 생성
    for n, si in changed:
        for f in (audio / f"slide_{n:02d}_seg_{si:02d}.wav", audio / f"slide_{n:02d}.wav"):
            if f.exists():
                f.unlink()
    print(f"[sfx_prep] 이벤트 {len(events)}개, 텍스트/감정 수정 세그먼트 {len(changed)}개 -> {ev_p}")
    for e in events:
        print(f"   {e['slide']:>2}-{e['seg']} {e['sfx']:8s} {e['mode']:5s} {e.get('word') or ''} {e['note']}")
    for n, si in changed:
        print(f"   (재더빙 대상) slide_{n:02d}_seg_{si:02d}")
    return 0


# ---- 2단계: wav 패딩 -----------------------------------------------------------
def _shift_timing(timing, slide, idx, d):
    """slide/idx 세그먼트가 d초 늘어난 것을 timing.json 에 반영."""
    pivot = None
    for s in timing["segments"]:
        if s["slide"] == slide and s["index"] == idx:
            s["end"] = round(s["end"] + d, 3)
            s["duration"] = round(s["duration"] + d, 3)
            pivot = (s["slide"], s["index"])
    if pivot is None:
        return False
    for s in timing["segments"]:
        if (s["slide"], s["index"]) > pivot:
            s["start"] = round(s["start"] + d, 3)
            s["end"] = round(s["end"] + d, 3)
    for sl in timing["slides"]:
        if sl["slide"] == slide:
            sl["end"] = round(sl["end"] + d, 3)
            sl["duration"] = round(sl["duration"] + d, 3)
        elif sl["slide"] > slide:
            sl["start"] = round(sl["start"] + d, 3)
            sl["end"] = round(sl["end"] + d, 3)
    timing["total_duration"] = round(timing["total_duration"] + d, 3)
    return True


def _pick_cut(x, sr, text, idx):
    """gap 모드: (자를 시각, 무음 시작 시각). 추정 시각에 가장 가까운 무음 중앙, 없으면 에너지 최저점."""
    est = char_time(x, sr, text, idx)
    n = len(x) / sr
    sil = [s for s in silences(x, sr, min_len=0.2) if s[0] > 0.3 and s[1] < n - 0.2]
    near = [s for s in sil if abs((s[0] + s[1]) / 2 - est) < 1.0]
    if near:
        a, b = min(near, key=lambda s: abs((s[0] + s[1]) / 2 - est))
        return (a + b) / 2, a
    env = envelope(x, sr, 0.01)
    lo, hi = int(max(0, est - 0.15) * sr), int(min(n, est + 0.15) * sr)
    c = lo + int(np.argmin(env[lo:hi]))
    return c / sr, c / sr


def phase_pad(ep):
    audio = ep / "audio"
    ev_p = audio / "sfx_events.json"
    if not ev_p.exists():
        print("[sfx_prep --pad] sfx_events.json 없음 -- 통과")
        return 0
    doc = json.loads(ev_p.read_text(encoding="utf-8"))
    events = doc.get("events", [])
    todo = [e for e in events if e.get("prep") and not e.get("prep_done")]
    if not todo:
        print("[sfx_prep --pad] 패딩할 이벤트 없음 -- 통과")
        return 0
    story = json.loads((ep / "story.json").read_text(encoding="utf-8"))
    timing_p = audio / "timing.json"
    timing = json.loads(timing_p.read_text(encoding="utf-8"))
    segtext = {(sl["slide_number"], i): s for sl in story["slides"] for i, s in enumerate(sl.get("tts_segments") or [])}
    order = {"pre": 0, "gap": 1, "post": 2}
    for e in sorted(todo, key=lambda e: (e["slide"], e["seg"], order.get(e["mode"], 9), e.get("prep", {}).get("after_index", 0))):
        f = audio / f"slide_{e['slide']:02d}_seg_{e['seg']:02d}.wav"
        if not f.exists():
            print(f"[sfx_prep --pad] 오류: {f.name} 없음 (03/tts_gate 먼저)")
            return 1
        x, sr = read_wav(f)
        p = e["prep"]
        before = len(x)
        if e["mode"] == "pre":
            x = np.concatenate([np.zeros(int(sr * p["preroll"])), x])
            e["sfx_at_in_seg"] = list(e["offsets"])
        elif e["mode"] == "post":
            t0 = len(x) / sr
            x = np.concatenate([x, np.zeros(int(sr * p["postroll"]))])
            e["sfx_at_in_seg"] = [round(t0 + o, 3) for o in e["offsets"]]
        elif e["mode"] == "gap":
            text = segtext[(e["slide"], e["seg"])]["text"]
            cut_t, gap_start = _pick_cut(x, sr, text, p["after_index"])
            cut = int(sr * cut_t)
            x = np.concatenate([x[:cut], np.zeros(int(sr * p["gap_insert"])), x[cut:]])
            e["sfx_at_in_seg"] = [round(float(gap_start) + 0.04, 3)]
        write_wav(f, x, sr)
        d = (len(x) - before) / sr
        e["prep_done"] = True
        e["pad_added"] = round(d, 3)
        if not _shift_timing(timing, e["slide"], e["seg"], d):
            print(f"[sfx_prep --pad] 경고: timing.json 에 {e['slide']}-{e['seg']} 없음")
        print(f"[sfx_prep --pad] {e['slide']}-{e['seg']} {e['sfx']} {e['mode']} +{d:.2f}s at={e['sfx_at_in_seg']}")
    timing_p.write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    ev_p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--pad", action="store_true", help="2단계: wav 패딩 + timing.json 갱신 (tts_gate 후, 04 전)")
    ap.add_argument("--force", action="store_true", help="텍스트 단계를 다시 수행")
    ap.add_argument("--allow-published", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="감지 결과만 출력 (파일 수정 없음)")
    a = ap.parse_args()
    ep = Path(a.dir)
    if a.pad:
        sys.exit(phase_pad(ep))
    sys.exit(phase_text(ep, a.allow_published, a.force, a.dry_run))


if __name__ == "__main__":
    main()
