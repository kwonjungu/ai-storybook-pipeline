"""sfx_common.py -- 효과음 단계 공용 함수 (wav 입출력, 무음 검출, 텍스트-오디오 시각 추정).

sfx_prep.py / sfx_mix.py 가 쓴다. 경로 전역 상태 없음 (--dir 로 편마다 호출).
"""
import wave
import numpy as np


def read_wav(p):
    with wave.open(str(p)) as w:
        n = w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
        if n > 1:
            x = x.reshape(-1, n).mean(axis=1)
        return x, w.getframerate()


def write_wav(p, x, sr):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def envelope(x, sr, win=0.02):
    h = max(1, int(sr * win))
    return np.sqrt(np.convolve(x ** 2, np.ones(h) / h, "same"))


def silences(x, sr, thr=0.01, min_len=0.1):
    """(시작초, 끝초) 무음 구간 목록."""
    quiet = ~(envelope(x, sr) > thr)
    d = np.diff(np.concatenate([[0], quiet.astype(np.int8), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(a / sr, b / sr) for a, b in zip(starts, ends) if b - a > min_len * sr]


def is_syl(c):
    return '가' <= c <= '힣'


_VOWELS = set("aeiouyáéíóúàâãêõüAEIOUYÁÉÍÓÚÀÂÃÊÕÜ")


def is_latin_text(text):
    """한글이 없고 라틴 글자가 있으면 True (en/es/id/pt) -- 이때만 글자 단위 가중치를 쓴다. 한국어 동작은 그대로."""
    return not any(is_syl(c) for c in text) and any(c.isalpha() for c in text)


def _syl_weight(c, lat=False):
    """음절 발화 길이 가중치: 받침 있는 음절이 조금 더 길다. 라틴 문자는 모음 1.0 / 자음 0.35 (음절 수 근사)."""
    if lat:
        return (1.0 if c in _VOWELS else 0.35) if c.isalpha() else 0.0
    return 1.0 + (0.3 if (ord(c) - 0xAC00) % 28 else 0.0) if is_syl(c) else 0.0


_PUNCT_ALL = ",.?!;:"
_PUNCT_END = ".?!"


def _text_chunks(text, punct, lat=False):
    """구두점으로 끊은 (시작idx, 끝idx) 목록 -- 음절이 있는 덩어리만."""
    out, st = [], 0
    for i, c in enumerate(text):
        if c in punct:
            out.append((st, i + 1)); st = i + 1
    out.append((st, len(text)))
    return [(a, b) for a, b in out if any((c.isalpha() if lat else is_syl(c)) for c in text[a:b])]


def _audio_voiced(x, sr, min_gap):
    """말소리 구간 [(s,e)] -- 앞뒤 무음 제거, min_gap 이상 쉼에서 분할."""
    n = len(x) / sr
    sil = silences(x, sr, min_len=min_gap)
    lead = sil[0][1] if sil and sil[0][0] < 0.01 else 0.0
    tail = sil[-1][0] if sil and sil[-1][1] > n - 0.01 else n
    gaps = [(a, b) for a, b in sil if a > lead + 0.01 and b < tail - 0.01]
    segs, cur = [], lead
    for a, b in gaps:
        segs.append((cur, a)); cur = b
    segs.append((cur, tail))
    return segs, lead, tail


def char_time(x, sr, text, idx):
    """text[idx] 글자의 발화 시작 시각(초).

    1) 구두점 덩어리 수 == 오디오 말소리 덩어리 수면 덩어리끼리 맞춰 덩어리 안에서만 음절 가중치 비례
       (쉼표/마침표 직전의 오차가 다음 덩어리로 번지지 않는다)
    2) 안 맞으면 전체 발화 시간(쉼 제외)에 음절 가중치 비례 (시범판 방식 + 받침 가중)
    """
    idx = max(0, min(idx, len(text) - 1))
    lat = is_latin_text(text)
    for punct in (_PUNCT_ALL, _PUNCT_END):
        tch = _text_chunks(text, punct, lat)
        for gap in (0.12, 0.2, 0.08):
            segs, lead, tail = _audio_voiced(x, sr, gap)
            if len(tch) == len(segs) and len(tch) >= 1:
                for (a, b), (s, e) in zip(tch, segs):
                    if idx < b or (a, b) == tch[-1]:
                        w = [_syl_weight(c, lat) for c in text[a:b]]
                        tot = sum(w) or 1.0
                        before = sum(w[:max(0, min(idx, b) - a)])
                        return s + (e - s) * before / tot
    # 3) 덩어리 수가 안 맞을 때: 감지된 쉼을 가장 가까운 '띄어쓰기' 경계에 닻으로 걸고, 닻 사이를 음절 가중 보간
    segs, lead, tail = _audio_voiced(x, sr, 0.12)
    vt = sum(e - s for s, e in segs)
    w = [_syl_weight(c, lat) for c in text]
    P = np.concatenate([[0.0], np.cumsum(w)])
    T = float(P[-1]) or 1.0
    bounds = [(P[i + 1] / T) for i, c in enumerate(text) if c == " " and i + 1 < len(text)]
    aw, av = [0.0], [0.0]
    cum = 0.0
    for s, e in segs[:-1]:
        cum += e - s
        f = cum / vt if vt > 0 else 0.0
        if bounds:
            W = min(bounds, key=lambda b: abs(b - f))
            if abs(W - f) < 0.1 and W > aw[-1] + 0.02 and W < 1.0 - 0.02:
                aw.append(W); av.append(cum)
    aw.append(1.0); av.append(vt)
    v = float(np.interp(P[idx] / T, aw, av))
    for s, e in segs:
        if v < (e - s) - 1e-6:
            return s + v
        v -= (e - s)
    return segs[-1][1]


def word_time(x, sr, text, word):
    """text 속 word 첫 음절의 시각(초)."""
    return char_time(x, sr, text, text.index(word))
