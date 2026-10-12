"""sfx_lib.py -- 동화 영상용 효과음 합성 모듈 (저작권 0, numpy/scipy 만 사용).

모든 함수는 SR(44100Hz) 모노 float 배열을 돌려준다. 피크는 대략 1.0 로 정규화돼 있고,
실제 음량은 mix 단계에서 '대사 RMS 대비 dB' 로 정한다 (sfx_mix.py).
아이 그림책 톤: 어택을 둥글게, 고음 쏘는 소리 없이 부드럽게.
"""
import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100


def _t(dur):
    return np.arange(int(SR * dur)) / SR


def _bp(x, lo, hi, order=2):
    sos = butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return sosfilt(sos, x)


def _lp(x, hi, order=2):
    sos = butter(order, hi, btype="low", fs=SR, output="sos")
    return sosfilt(sos, x)


def _norm(y, peak=1.0):
    m = np.abs(y).max()
    return y * (peak / m) if m > 0 else y


def _fade(y, a=0.004, r=0.02):
    n = len(y)
    ia, ir = int(SR * a), int(SR * r)
    y = y.copy()
    if ia: y[:ia] *= np.linspace(0, 1, ia)
    if ir: y[-ir:] *= np.linspace(1, 0, ir)
    return y


def thump(dur=0.42, f_start=95, f_end=42):
    """쿵: 곰 발소리. 낮은 사인 스윕 + 아주 짧은 둔탁한 노이즈 어택."""
    t = _t(dur)
    f = f_end + (f_start - f_end) * np.exp(-t * 14)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    rng = np.random.default_rng(3)
    tap = _lp(rng.standard_normal(len(t)), 260) * np.exp(-t * 55) * 2.0
    return _fade(_norm(body + 0.5 * tap), 0.003, 0.05)


def flutter(dur=0.9, seed=5):
    """펄럭펄럭: 종이/날개가 바람에 펄럭이는 소리. 대역 노이즈 + 13Hz 진폭 흔들림."""
    t = _t(dur)
    rng = np.random.default_rng(seed)
    n = _bp(rng.standard_normal(len(t)), 500, 2600)
    am = 0.55 + 0.45 * np.sin(2 * np.pi * 13 * t + 0.4 * np.sin(2 * np.pi * 3 * t)) ** 2
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.8
    return _fade(_norm(n * am * env), 0.02, 0.08)


def swish(dur=0.5, seed=1):
    """쭈욱: 미끄러지는 소리. 대역이 낮은 곳에서 높은 곳으로 올라가는 노이즈."""
    rng = np.random.default_rng(seed)
    n = len(_t(dur))
    x = rng.standard_normal(n)
    out = np.zeros(n)
    blk = 441
    for k in range(0, n, blk):
        c = 500 + 2200 * (k / n)
        seg = _bp(x[k:k + blk + 400], c * 0.6, c * 1.5)[:blk]
        out[k:k + len(seg)] = seg
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.4
    return _fade(_norm(out * env), 0.02, 0.05)


def pop(dur=0.14, f0=620, f1=240):
    """퐁: 물방울/탄성 팝. 주파수가 내려가는 짧은 사인."""
    t = _t(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 24)
    return _fade(_norm(y), 0.003, 0.02)


def pop_pop(gap=0.22):
    """퐁퐁: 팝 두 번 (두 번째는 살짝 높고 작게)."""
    a, b = pop(), pop(f0=700, f1=280) * 0.8
    out = np.zeros(int(SR * (gap + 0.16)))
    out[:len(a)] += a
    i = int(SR * gap)
    out[i:i + len(b)] += b
    return _norm(out)


def clap(dur=0.16, seed=7):
    """짝: 작은 손뼉. 중고역 노이즈의 짧은 버스트 두 겹(살짝 번지게)."""
    rng = np.random.default_rng(seed)
    t = _t(dur)
    n = _bp(rng.standard_normal(len(t)), 900, 4200)
    y = n * np.exp(-t * 38)
    j = int(SR * 0.009)
    y2 = np.zeros_like(y); y2[j:] = y[:-j] * 0.6
    return _fade(_norm(_lp(y + y2, 5000)), 0.001, 0.03)


def roll(dur=1.1, seed=11):
    """데굴데굴: 콩이 굴러가는 소리. 낮은 럼블 노이즈 + 점점 느려지지 않는 부드러운 쿵쿵 주기."""
    t = _t(dur)
    rng = np.random.default_rng(seed)
    rumble = _bp(rng.standard_normal(len(t)), 90, 420) * (0.6 + 0.4 * np.sin(2 * np.pi * 5.5 * t)) ** 2
    thumps = np.zeros(len(t))
    for k in range(int(dur * 5.5)):
        at = k / 5.5 + 0.05
        i = int(at * SR)
        h = thump(0.16, 130, 80) * (0.55 + 0.1 * (k % 2))
        j = min(len(t), i + len(h))
        if j > i: thumps[i:j] += h[: j - i]
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.7
    return _fade(_norm((0.8 * _norm(rumble) + 0.7 * thumps) * env), 0.03, 0.12)


def sparkle(dur=1.2):
    """반짝: 작은 글로켄 세 음 (E6 G6 C7)."""
    out = np.zeros(int(SR * dur))
    for k, m in enumerate((88, 91, 96)):
        f = 440 * 2 ** ((m - 69) / 12)
        t = _t(0.7)
        y = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 6)) * np.exp(-t * 6.5)
        y = _fade(y, 0.002, 0.05)
        i = int(SR * 0.07 * k)
        out[i:i + len(y)] += y
    return _norm(out)


def shutter(dur=0.32, seed=9):
    """찰칵: 카메라 셔터. 짧은 틱 두 번(열림/닫힘) + 작은 몸통 울림."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(SR * dur))

    def click(at, f, g):
        t = _t(0.05)
        n = _bp(rng.standard_normal(len(t)), 1500, 5500) * np.exp(-t * 110)
        tone = np.sin(2 * np.pi * f * t) * np.exp(-t * 90)
        y = _fade(n + 0.8 * tone, 0.0005, 0.01) * g
        i = int(SR * at)
        out[i:i + len(y)] += y

    click(0.0, 1900, 1.0)
    click(0.11, 1300, 0.75)
    return _norm(_lp(out, 6000))


SFX = {
    "thump": thump, "pop": pop, "flutter": flutter, "swish": swish, "pop_pop": pop_pop,
    "clap": clap, "roll": roll, "sparkle": sparkle, "shutter": shutter,
}


# ── 2026-10-12 추가: 09c_puzzle_shorts.py(무슨 소리일까)용. 위 함수들은 변경 없음 ──
def knock(dur=0.2, seed=21):
    """똑: 나무 문을 두드리는 짧고 마른 소리."""
    t = _t(dur)
    rng = np.random.default_rng(seed)
    body = (np.sin(2 * np.pi * 330 * t) + 0.5 * np.sin(2 * np.pi * 620 * t)) * np.exp(-t * 45)
    tap = _bp(rng.standard_normal(len(t)), 700, 2500) * np.exp(-t * 120)
    return _fade(_norm(_lp(body + 0.6 * tap, 3500)), 0.001, 0.03)


def splash(dur=0.8, seed=31):
    """풍덩: 낮은 물방울 울림 + 흩어지는 물소리 노이즈."""
    t = _t(dur)
    rng = np.random.default_rng(seed)
    f = 70 + 330 * np.exp(-t * 18)
    plop = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    spray = _bp(rng.standard_normal(len(t)), 600, 4500) * np.exp(-t * 7) * np.minimum(1, t / 0.01)
    return _fade(_norm(_lp(plop + 0.55 * spray, 5500)), 0.002, 0.08)


def ding(dur=1.1):
    """딩동: 부드러운 두 음 종소리."""
    out = np.zeros(int(SR * dur))
    for at, fr in ((0.0, 988.0), (0.28, 784.0)):
        t = _t(0.8)
        y = (np.sin(2 * np.pi * fr * t) + 0.3 * np.sin(2 * np.pi * fr * 2.01 * t) * np.exp(-t * 5)) * np.exp(-t * 4.2)
        y = _fade(y, 0.003, 0.05)
        i = int(SR * at)
        out[i:i + len(y)] += y[:len(out) - i]
    return _norm(out)


SFX.update({"knock": knock, "splash": splash, "ding": ding})
