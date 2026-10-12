#!/usr/bin/env python
"""09c_puzzle_shorts.py -- 자체 완결 퍼즐형 숏츠 (2026-10-12 '새 포맷 A~D 순환 채택').

  python 09c_puzzle_shorts.py --dir output/폴더 --format A|B|C|D|auto [--lang ko] [--force]

  A 그림 수수께끼 : 그림 한 조각 확대 -> 힌트 2개 -> 3,2,1 -> 전체 공개
  B 다른 그림 찾기: Gemini 편집 + 차이영역 검사 + 마스크 합성(바뀐 곳 정확히 3곳)
  C 무슨 소리일까 : sfx_lib 효과음 -> 그림 3장 중 고르기 -> 공개
  D 햄찌쌤 질문   : 햄찌쌤(입 움직임)이 주제 질문 -> 본편 장면 3컷

산출: <dir>/shorts_puzzle.mp4 (1080x1920, 30fps, 15~20초, -14 LUFS) + shorts_puzzle.json
작업 파일은 <dir>/_puzzle_work/ 에만 만든다. 기존 파일은 건드리지 않는다. 업로드 안 함.
문구(힌트·정답·질문·VO)는 Gemini 가 story.json 근거로 생성한다(포맷 틀 문구 제외).
"""
import argparse, functools, io, json, math, os, re, subprocess, sys, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.io import wavfile
from scipy.signal import resample_poly
from scipy import ndimage as ndi

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
FFBIN = r"C:\Users\권준구\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
if os.path.isdir(FFBIN): os.environ["PATH"] = FFBIN + os.pathsep + os.environ["PATH"]
import requests
from dotenv import dotenv_values
import sfx_lib

ENV = dotenv_values(PROJ / ".env")
FONT = PROJ / "assets/fonts/Jua-Regular.ttf"
HAMDIR = PROJ / "assets/hamzzi"
RHUBARB = Path(r"C:\Users\Public\rhubarb\rhubarb.exe")
TEXT_MODEL = "gemini-3-flash-preview"      # 11b 와 같은 모델(작은 물건 위치 검출 정확)
TEXT_FALLBACK = "gemini-2.5-flash"
IMG_MODEL = ENV.get("GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
VOICE = "tc_601944fb9089786f78c285ef"      # 햄찌쌤 (Jennifer)
W, H, FPS, SR = 1080, 1920, 30, 48000
SRCW, SRCH = 1344, 768
INK = (58, 66, 84); RED = (232, 65, 60); WHITE = (255, 255, 255)
IMG_COST = 0.039
MAX_UP = 2.2                         # 원본 대비 최대 확대 배율(이 이상이면 흐려짐)


class Infeasible(Exception):
    pass


# ───────────────────────── 공통 유틸 ─────────────────────────
def smooth(u): u = min(max(u, 0), 1); return u * u * (3 - 2 * u)
def lerp(a, b, u): return a + (b - a) * u
def ease_out_back(u, k=2.2):
    u = min(max(u, 0), 1) - 1; return 1 + (k + 1) * u ** 3 + k * u ** 2
def pop_in(t, t0, dur=0.35): return ease_out_back((t - t0) / dur) if t >= t0 else 0.0


@functools.lru_cache(maxsize=None)
def font(sz): return ImageFont.truetype(str(FONT), int(sz))


@functools.lru_cache(maxsize=512)
def text_layer(txt, size, fill=INK, stroke=WHITE, maxw=1000, sw=None, lh=1.18):
    lines = txt.split("\n"); sz = size
    while sz > 30 and max(font(sz).getlength(l) for l in lines) > maxw: sz -= 4
    f = font(sz); sw = sw if sw is not None else max(4, int(sz / 12))
    lw = int(max(f.getlength(l) for l in lines) + sw * 4 + 20); lhp = int(sz * lh)
    im = Image.new("RGBA", (lw, lhp * len(lines) + sw * 4 + 20), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((im.width / 2, 10 + sw * 2 + lhp * (i + .5)), l, font=f, fill=fill + (255,), anchor="mm",
               stroke_width=sw, stroke_fill=stroke + (255,))
    return im


@functools.lru_cache(maxsize=256)
def banner_layer(txt, size, fill=INK, bg=(255, 255, 255, 228), maxw=980, lh=1.14):
    t = text_layer(txt, size, fill, WHITE, maxw=maxw - 90, sw=0, lh=lh)
    w, h = t.width + 90, t.height + 34
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w - 1, h - 1), min(60, h // 2), fill=bg)
    im.alpha_composite(t, (45, 17)); return im


@functools.lru_cache(maxsize=256)
def pill_layer(txt, size, fill=INK, bg=WHITE, maxw=960):
    t = text_layer(txt, size, fill, bg, maxw=maxw - 120, sw=0)
    im = Image.new("RGBA", (t.width + 100, t.height + 44), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, im.width - 1, im.height - 1), im.height // 2, fill=bg + (255,))
    im.alpha_composite(t, (50, 22)); return im


def put(canvas, im, cx, cy, scale=1.0, alpha=1.0, shadow=False):
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
    if alpha < 1:
        a = im.getchannel("A").point(lambda v: int(v * alpha)); im = im.copy(); im.putalpha(a)
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); sh.putalpha(im.getchannel("A").point(lambda v: int(v * 0.18)))
        canvas.paste(sh, (x + 6, y + 12), sh)
    canvas.paste(im, (x, y), im)


def blur_bg(img, veil=0.40, seed_tint=None):
    """(이름만 유지) 그림 평균색에 맞춘 종이 질감 단색 배경."""
    m = np.asarray(img.resize((64, 36)), float).reshape(-1, 3).mean(0)
    base = np.array([250, 246, 236.]) * 0.70 + m * 0.30
    rng = np.random.default_rng(7)
    n = ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 0.7) * 7 + ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 22) * 55
    yy, xx = np.mgrid[0:H, 0:W]; vg = 1 - 0.07 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    arr = (base[None, None, :] + n[..., None]) * vg[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGBA")


def fit_circle(cx, cy, r, x0, y0, x1, y1, rmin, m=6):
    """원이 영역 안에 완전히 들어오도록 반지름(최소 rmin까지)을 줄이고, 그래도 넘으면 중심을 안쪽으로 민다."""
    r = max(rmin, min(r, cx - x0 - m, x1 - cx - m, cy - y0 - m, y1 - cy - m))
    cx = min(max(cx, x0 + r + m), x1 - r - m); cy = min(max(cy, y0 + r + m), y1 - r - m)
    return cx, cy, r


def view(img, cx, cy, w, h, ow, oh):
    w = min(w, img.width); h = min(h, img.height)
    x0 = min(max(cx - w / 2, 0), max(0, img.width - w)); y0 = min(max(cy - h / 2, 0), max(0, img.height - h))
    o = img.resize((ow, oh), Image.LANCZOS, box=(x0, y0, x0 + w, y0 + h))
    if ow > w * 1.6: o = o.filter(ImageFilter.UnsharpMask(2.0, 70, 2))
    return o


def circle_img(im, d, ring=(255, 255, 255)):
    c = im.resize((d, d), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (d * 3, d * 3), 0); ImageDraw.Draw(m).ellipse((0, 0, d * 3 - 1, d * 3 - 1), fill=255); m = m.resize((d, d), Image.LANCZOS)
    out = Image.new("RGBA", (d + 24, d + 24), (0, 0, 0, 0)); rm = Image.new("L", (d + 24,) * 2, 0)
    ImageDraw.Draw(rm).ellipse((0, 0, d + 23, d + 23), fill=255)
    out.paste(Image.new("RGBA", out.size, ring + (255,)), (0, 0), rm); out.paste(c, (12, 12), m); return out


def log(*a): print("[09c]", *a, flush=True)


# ───────────────────────── Gemini ─────────────────────────
_cli = None
def client():
    global _cli
    if _cli is None:
        from google import genai
        from google.genai import types as _gt
        _cli = genai.Client(api_key=ENV["GEMINI_API_KEY"], http_options=_gt.HttpOptions(timeout=120000))
    return _cli


def png_part(img, maxside=1280):
    from google.genai import types as gt
    im = img.copy()
    if max(im.size) > maxside: im.thumbnail((maxside, maxside))
    b = io.BytesIO(); im.convert("RGB").save(b, "PNG")
    return gt.Part.from_bytes(data=b.getvalue(), mime_type="image/png")


def gj(parts, tries=4):
    from google.genai import types as gt
    err = None
    for i in range(tries):
        try:
            r = client().models.generate_content(model=TEXT_MODEL if i < tries - 1 else TEXT_FALLBACK, contents=parts,
                config=gt.GenerateContentConfig(response_mime_type="application/json", temperature=0.4))
            j = json.loads(r.text)
            return j[0] if isinstance(j, list) and j and isinstance(j[0], dict) else j
        except Exception as e:
            err = e; time.sleep(3 + 3 * i)
    raise RuntimeError(f"Gemini 실패: {str(err)[:200]}")


def gemini_edit(img, prompt, tries=5):
    from google.genai import types as gt
    for i in range(tries):
        try:
            r = client().models.generate_content(model=IMG_MODEL, contents=[png_part(img, 1600), prompt],
                config=gt.GenerateContentConfig(response_modalities=["IMAGE"], image_config=gt.ImageConfig(aspect_ratio="16:9")))
            for p in r.candidates[0].content.parts:
                if p.inline_data: return Image.open(io.BytesIO(p.inline_data.data)).convert("RGB")
        except Exception as e:
            log("edit retry", str(e)[:80]); time.sleep(5)
    return None


# ───────────────────────── 에피소드 자료 ─────────────────────────
class Ep:
    def __init__(self, d):
        self.dir = Path(d)
        self.story = json.load(open(self.dir / "story.json", encoding="utf-8"))
        self.meta = self.story["meta"]
        self.title = self.meta.get("story_title", self.dir.name)
        self.work = self.dir / "_puzzle_work"; self.work.mkdir(exist_ok=True)
        self.slides = {}
        for s in self.story["slides"]:
            if s.get("type") != "story": continue
            p = self.dir / "images" / f"slide_{s['slide_number']:02d}.png"
            if p.exists(): self.slides[s["slide_number"]] = self.norm(Image.open(p).convert("RGB"))
        self.texts = {s["slide_number"]: s.get("text", "") for s in self.story["slides"]}
        chars = self.meta.get("characters", {})
        self.chars = [(k, v.get("name"), v.get("species")) for k, v in chars.items() if isinstance(v, dict) and k.startswith("main")]
        pl = self.dir / "publish_log.json"
        self.main_url = json.load(open(pl, encoding="utf-8")).get("youtube_url", "") if pl.exists() else ""
        self.image_calls = 0
        self.no_new_edits = bool(os.environ.get('PUZZLE_NO_NEW_EDITS'))

    @staticmethod
    def norm(im):
        ar = im.width / im.height
        if abs(ar - SRCW / SRCH) > 0.02:
            if ar > SRCW / SRCH:
                nw = int(im.height * SRCW / SRCH); x = (im.width - nw) // 2; im = im.crop((x, 0, x + nw, im.height))
            else:
                nh = int(im.width * SRCH / SRCW); y = (im.height - nh) // 2; im = im.crop((0, y, im.width, y + nh))
        return im.resize((SRCW, SRCH), Image.LANCZOS) if im.size != (SRCW, SRCH) else im

    def ctx(self, n=110):
        cs = ", ".join(f"{c[1]}({c[2]})" for c in self.chars)
        lines = "\n".join(f"{k}: {self.texts[k][:n]}" for k in sorted(self.slides))
        return f"동화 제목: {self.title}\n주인공: {cs}\n장면(번호: 줄거리):\n{lines}"

    def sheet(self, nums=None, cols=4, tw=480):
        nums = nums or sorted(self.slides); th = int(tw * SRCH / SRCW)
        rows = (len(nums) + cols - 1) // cols
        sh = Image.new("RGB", (cols * tw, rows * th), (255, 255, 255)); d = ImageDraw.Draw(sh)
        for i, n in enumerate(nums):
            x, y = (i % cols) * tw, (i // cols) * th
            sh.paste(self.slides[n].resize((tw, th), Image.LANCZOS), (x, y))
            d.rectangle((x, y, x + 74, y + 56), fill=(0, 0, 0)); d.text((x + 8, y + 2), str(n), font=font(48), fill=(255, 255, 0))
        return sh

    def faces(self):
        p = self.work / "faces.json"
        box = json.load(open(p)) if p.exists() else {}
        out = []
        for k, name, _ in self.chars[:2]:
            sp = self.dir / "characters" / f"{k}.png"
            if not sp.exists(): continue
            im = Image.open(sp).convert("RGB")
            if k not in box or len(box[k]) != 4:
                for _ in range(3):
                    try:
                        j = gj([png_part(im), "캐릭터 시트 그림이다. 이 캐릭터의 정면 얼굴(머리 전체, 부리/코/귀 포함)을 감싸는 박스를 JSON 으로: "
                                '{"box":[ymin,xmin,ymax,xmax]} (0~1000 정규화, 숫자 4개)'])
                        b = j.get("box") if isinstance(j, dict) else None
                        if b and len(b) == 4: box[k] = [float(v) for v in b]; break
                    except (Exception,): pass
                else: box[k] = [100, 250, 550, 750]      # 실패 시 윗부분 중앙(캐릭터 시트는 대체로 머리가 위)
                json.dump(box, open(p, "w"))
            y0, x0, y1, x1 = [float(v) / 1000 for v in box[k]]
            cx, cy = (x0 + x1) / 2 * im.width, (y0 + y1) / 2 * im.height
            side = max((x1 - x0) * im.width, (y1 - y0) * im.height) * 1.12
            l, t = int(cx - side / 2), int(cy - side / 2)
            out.append(im.crop((l, t, int(l + side), int(t + side))))
        return out


# ───────────────────────── 음성 ─────────────────────────
def tts_line(ep, text, key):
    """Typecast ssfm-v30 햄찌쌤. 캐시. 반환: 트림된 48k mono float 배열."""
    wd = ep.work / "vo"; wd.mkdir(exist_ok=True)
    raw = wd / f"{key}.wav"
    import hashlib
    h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    raw = wd / f"{key}_{h}.wav"
    if not raw.exists():
        pl = {"voice_id": VOICE, "text": text, "model": "ssfm-v30", "language": "kor",
              "output": {"audio_format": "wav", "target_lufs": -14},
              "prompt": {"emotion_type": "preset", "emotion_preset": "happy", "emotion_intensity": 1.0}}
        for t in range(4):
            try:
                r = requests.post("https://api.typecast.ai/v1/text-to-speech", json=pl,
                                  headers={"X-API-KEY": ENV["TYPECAST_API_KEY"]}, timeout=120)
                if r.ok: raw.write_bytes(r.content); break
                log("tts", r.status_code, r.text[:100])
            except Exception as e: log("tts retry", str(e)[:60])
            time.sleep(4)
        else: raise RuntimeError("TTS 실패: " + text)
    sr, a = wavfile.read(raw); a = a.astype(np.float32)
    if a.ndim > 1: a = a.mean(1)
    a /= (32768 if np.abs(a).max() > 2 else 1)
    idx = np.where(np.abs(a) > 0.01)[0]
    a = a[max(0, idx[0] - int(0.03 * sr)): idx[-1] + int(0.12 * sr)]
    a = resample_poly(a, SR, sr).astype(np.float32)
    wavfile.write(wd / f"{key}_trim.wav", SR, (a * 32767).astype(np.int16))
    return a


def rhubarb_cues(ep, key):
    out = ep.work / "vo" / f"{key}_mouth.json"
    src = ep.work / "vo" / f"{key}_trim.wav"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        r = subprocess.run([str(RHUBARB), "-r", "phonetic", "-f", "json", "-o", str(out), str(src)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode: raise RuntimeError("rhubarb 실패 " + r.stderr[-200:])
    return json.load(open(out))["mouthCues"]


def sfx(name, **kw):
    a = sfx_lib.SFX[name](**kw).astype(np.float32)
    return resample_poly(a, SR, sfx_lib.SR).astype(np.float32)


def tick(f=880, dur=0.11, amp=1.0):
    t = np.arange(int(SR * dur)) / SR
    return (amp * np.sin(2 * np.pi * f * t) * np.exp(-t * 22) * np.minimum(1, t / 0.004)).astype(np.float32)


def ff(*a): return subprocess.run(["ffmpeg", "-hide_banner", "-y", *a], capture_output=True, text=True, encoding="utf-8", errors="replace")


def mix_audio(events, dur, out):
    """events [(t, array, gain)] -> -14 LUFS (loudnorm 2패스 + 실측 보정)."""
    buf = np.zeros(int(SR * dur))
    for t, a, g in events:
        i = int(t * SR); j = min(len(buf), i + len(a))
        if j > i: buf[i:j] += g * a[:j - i]
    buf = np.tanh(buf * 0.9)
    fade = int(0.08 * SR); buf[-fade:] *= np.linspace(1, 0, fade)
    tmp = Path(out).with_suffix(".raw.wav"); wavfile.write(tmp, SR, (buf * 32767 * 0.8).astype(np.int16))
    r = ff("-i", str(tmp), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-")
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr).group(0))
    ln = (f"loudnorm=I=-14:TP=-1:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample={SR}")
    r = ff("-i", str(tmp), "-af", ln, "-ac", "2", str(out))
    if r.returncode: raise RuntimeError(r.stderr[-400:])
    tmp.unlink()
    for _ in range(3):
        chk = ff("-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-").stderr
        I = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", chk)[-1])
        if abs(I + 14) < 0.15: break
        o2 = Path(out).with_suffix(".g.wav")
        ff("-i", str(out), "-af", f"volume={-14 - I:.2f}dB,alimiter=limit=0.89:level=0", str(o2)); o2.replace(out)


def render(fn, dur, out, audio, workdir, tag, probes=()):
    tmpv = workdir / f"{tag}.video.mp4"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(tmpv)], stdin=subprocess.PIPE)
    n = int(round(dur * FPS)); pf = {int(round(t * FPS)): t for t in probes}
    fd = workdir / f"frames_{tag}"; fd.mkdir(exist_ok=True)
    for i in range(n):
        im = fn(i / FPS).convert("RGB")
        if i in pf: im.save(fd / f"t{pf[i]:05.2f}.png")
        p.stdin.write(im.tobytes())
    p.stdin.close(); p.wait()
    r = ff("-i", str(tmpv), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out))
    if r.returncode: raise RuntimeError(r.stderr[-400:])
    for _ in range(10):
        try: tmpv.unlink(); break
        except OSError: time.sleep(1.5)
    chk = ff("-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-").stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", chk)[-1])


# ───────────────────────── 끝 화면 ─────────────────────────
def endcard(bg, t, line, faces, sub, d=None):
    c = bg.copy()
    k = pop_in(t, 0.0, 0.4)
    put(c, text_layer(line, 140, INK, WHITE, maxw=980), W / 2, 560, scale=max(0.01, k))
    n = len(faces); d = d or (330 if n <= 2 else 270 if n == 3 else 215)
    gap = (W - n * (d + 24)) / (n + 1)
    for i, f in enumerate(faces):
        kk = pop_in(t, 0.25 + 0.12 * i, 0.4)
        im = circle_img(f, d)
        yb = 1130 - 10 * math.sin(2 * math.pi * (t * 0.9 + i * 0.3))
        put(c, im, gap * (i + 1) + (d + 24) * (i + .5), yb, scale=max(0.01, kk), shadow=True)
    put(c, text_layer(sub, 62, (80, 95, 120), WHITE, maxw=980, sw=0), W / 2, 1560, alpha=min(1, t * 2))
    return c


def wrap(fn_main, bg, faces, sub, dur, t_end, t_loop, line="정답 이야기는\n본편에서!", d=None):
    def fn(t):
        if t < t_end: return fn_main(t)
        ec = endcard(bg, t - t_end, line, faces, sub, d)
        if t >= t_loop: return Image.blend(ec, fn_main(0.0), smooth((t - t_loop) / (dur - t_loop)))
        return ec
    return fn


# ───────────────────────── 문구 정답 누설 방지 ─────────────────────────
def leak_issues(answer, strict=(), loose=()):
    """strict: 정답 낱말·동의어·핵심 특징 모두 금지(제목·질문·첫 힌트). loose: 정답 낱말·동의어만 금지(둘째 힌트).
    반환: 누설 문구 리스트."""
    strict, loose = [x for x in strict if x], [x for x in loose if x]
    ans = re.sub(r"[^가-힣A-Za-z0-9]", "", answer)
    stems = {ans[i:i + 2] for i in range(len(ans) - 1)} if len(ans) >= 2 else {ans}
    bad = [t for t in strict + loose if any(st and st in re.sub(r"\s", "", t) for st in stems)]
    try:
        r = gj([f"퍼즐의 정답은 '{answer}'. 아래 [엄격] 문구는 정답 낱말·동의어·유의어뿐 아니라 정답의 핵심 모양/색/질감/기능 같은 구별 특징(그것만 들어도 맞힐 수 있는 단서)도 "
                f"담으면 안 된다. [느슨] 문구는 정답 낱말·동의어만 금지, 특징은 허용. 규칙을 어기는 문구를 원문 그대로 나열. JSON {{\"bad\":[...]}}\n[엄격] {strict}\n[느슨] {loose}"])
        bad += [str(b) for b in r.get("bad", []) if str(b) in strict + loose]
    except Exception as e: log("leak 판정 실패", str(e)[:60])
    return sorted(set(bad))


DEFAULT_Q = ["이게 뭘까요?", "무엇일까요?", "맞혀 볼래요?"]


def safe_phrases(ep, answer, phrases, topic):
    """질문형 제목 문구가 정답을 흘리면 다시 생성. 끝내 실패하면 기본 문구."""
    ph = [p for p in phrases if p]
    for _ in range(3):
        bad = leak_issues(answer, ph)
        ph = [p for p in ph if p not in bad]
        if len(ph) >= 3: return ph[:3]
        try:
            j = gj([f"동화 숏츠 퍼즐({topic}) 제목에 쓸 질문형 문구를 5개 만들어라(14자 이내, 초1 말투). 정답은 '{answer}'. 정답 낱말·동의어·정답의 모양/색/기능 특징을 절대 말하지 말고, "
                    '단순히 호기심만 자극할 것(예: 이게 뭘까요? / 어떤 장면일까요?). JSON {"q_phrases":[...]}'])
            ph += [x for x in j.get("q_phrases", []) if x not in ph]
        except Exception: pass
    ph = [p for p in ph if p not in leak_issues(answer, ph)] if ph else []
    return (ph + DEFAULT_Q)[:3]


# ───────────────────────── 포맷 A ─────────────────────────
CARD_H = 1700; CARD_CY = 960; CARD_AR = W / CARD_H          # 세로 꽉 찬 카드(화면 높이의 88%)
FWA = SRCH * CARD_AR                                          # 줌아웃 끝 크롭 너비(원본 높이 전체)


def vbox(img, cx, cy, w, h):
    w = min(w, img.width); h = min(h, img.height)
    return min(max(cx - w / 2, 0), max(0, img.width - w)), min(max(cy - h / 2, 0), max(0, img.height - h)), w, h


def locate_A(ep, img, answer):
    """11b 방식 2단계: 전체에서 대략 위치 -> 그 주변을 확대해 같은 물건을 다시 검출. 반환 (box px, visible) 또는 None."""
    j = gj([png_part(img), f"이 그림에서 '{answer}'를 정확히 감싸는 박스를 찾아라. 동화 맥락:\n{ep.ctx(60)}\n"
            "JSON: {\"found\":true/false,\"visible\":true/false(전체 그림에서 초1이 정답을 분명히 알아볼 수 있나),\"box\":[ymin,xmin,ymax,xmax](0~1000, 그 물건만 타이트하게)}"])
    if not j.get("found", True) or not j.get("box"): return None
    y0, x0, y1, x1 = [v / 1000 for v in j["box"]]
    b = [x0 * SRCW, y0 * SRCH, x1 * SRCW, y1 * SRCH]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2; L = min(max(max(b[2] - b[0], b[3] - b[1]) * 3.5, 260), SRCH)
    X0, Y0, L1, _ = vbox(img, cx, cy, L, L)
    crop = img.resize((768, 768), Image.LANCZOS, box=(X0, Y0, X0 + L1, Y0 + L1))
    j2 = gj([png_part(crop, 768), f"이것은 그림의 일부를 확대한 것이다. 여기서 '{answer}'를 정확히 감싸는 박스를 찾아라(그 물건만 타이트하게). "
             "JSON: {\"found\":true/false,\"box\":[ymin,xmin,ymax,xmax](0~1000, 이 확대 그림 기준)}"])
    if not j2.get("found") or not j2.get("box"): log("A 2단계 못 찾음", answer); return None
    y0, x0, y1, x1 = [v / 1000 for v in j2["box"]]
    b2 = [X0 + x0 * L1, Y0 + y0 * L1, X0 + x1 * L1, Y0 + y1 * L1]
    c2 = ((b2[0] + b2[2]) / 2, (b2[1] + b2[3]) / 2)
    if math.hypot(c2[0] - cx, c2[1] - cy) > L * 0.45: log("A 1·2단계 불일치", answer); return None
    return b2, bool(j.get("visible", True))


def a_texts(ep, img, answer, scene_note):
    fb = ""
    for k in range(4):
        t = gj([png_part(img), f"그림 수수께끼 숏츠 문구. 정답은 '{answer}'({scene_note}). 동화 맥락:\n{ep.ctx(60)}\n초1 말투로 JSON: "
                '{"hint1":"첫 힌트=장소·상황만(12자 이내, 예: 교실에서 볼 수 있어요). 정답 낱말·모양·색·기능 금지",'
                '"hint2":"둘째 힌트=이 물건의 특징(12자 이내). 정답 낱말·동의어 금지",'
                '"answer_banner":"화면 글자(8자 이내, 예: 발바닥!)","answer_vo":"정답 공개 대사(18자 이내, 1학년 말투 ~였어요!)",'
                '"q_phrases":["질문형 제목 문구 3개(14자 이내, 정답 낱말·특징 금지, 예: 이게 뭘까요?)"]}' + fb])
        bad = leak_issues(answer, strict=[t["hint1"]] + list(t.get("q_phrases", [])), loose=[t["hint2"]])
        if not bad: return t
        log("A 문구 누설 재생성", bad); fb = f"\n(이전 시도에서 정답을 흘린 문구: {bad}. 이런 표현은 피하라. 첫 힌트는 반드시 장소·상황.)"
    t["q_phrases"] = safe_phrases(ep, answer, [], "그림 수수께끼")
    if leak_issues(answer, [t["hint1"]]): t["hint1"] = "어디선가 본 물건이에요"
    return t


def plan_A(ep):
    cache = ep.work / "plan_A.json"
    if cache.exists(): return json.load(open(cache, encoding="utf-8"))
    cands = gj([png_part(ep.sheet(), 1800), ep.ctx() + "\n\n위 그림들(번호 표시)로 '그림 수수께끼' 숏츠를 만든다. 그림 일부분만 확대해 보여 주고 "
                "시청자(초1)가 무엇인지 맞히게 하는 퍼즐이다. 조건: 확대해서 보면 질감·색만 보여 바로 알기 어렵지만, 전체 그림에서는 분명히 보이는 "
                "작은 물건·소품·무늬(예: 신발 끈, 숟가락, 모자 리본, 열쇠, 가방 지퍼. 캐릭터의 얼굴·몸이나 그 근처(얼굴에서 먼 곳의 소품만, 목도리·모자 등 얼굴 옆 소품 제외), 크기는 화면 폭의 5~12%)를 가진 장면 6개를 우선순위로. "
                'JSON {"cands":[{"slide":번호,"answer":"정답 명사(예: 발바닥)","why":"..."}]}'])["cands"]
    for cd in cands[:6]:
        n = int(cd["slide"])
        if n not in ep.slides: continue
        img = ep.slides[n]
        lc = locate_A(ep, img, cd["answer"])
        if not lc: log("A 탈락(위치 검출 실패)", cd); continue
        (bx0, by0, bx1, by1), vis_ok = lc
        if not vis_ok: log("A 탈락(전체에서 불분명)", cd); continue
        ocx, ocy = (bx0 + bx1) / 2, (by0 + by1) / 2
        side = max(bx1 - bx0, by1 - by0)
        chk = view(img, ocx, ocy, side * 1.4 + 20, side * 1.4 + 20, 384, 384)
        if not gj([png_part(chk, 384), f"이 그림 조각의 정중앙에 '{cd['answer']}'(이)가 있나? JSON {{\"center_is_answer\":true/false}}"]).get("center_is_answer"):
            log("A 탈락(박스 위치 불일치)", n, cd["answer"]); continue
        if side < 40: log('A 탈락(물건이 너무 작음)', n, cd['answer'], side); continue
        c0 = max(side * 1.7, 250); tries = []; scx, scy = ocx, ocy
        for rnd in range(4):   # 첫 크롭이 너무 쉬우면 최대 2회 더 좁힌다(작게 + 물건 일부만 걸치게 이동)
            crop = view(img, scx, scy, c0, c0 / CARD_AR, 432, int(432 / CARD_AR))
            g = gj([png_part(crop, 768), "이 작은 그림 조각만 보고 보이는 것을 말하라. JSON {\"guesses\":[\"이게 뭘까 추측 3개\"],\"visible_things\":[\"또렷이 알아볼 수 있는 물건/부위 이름 전부\"],"
                    "\"whole_character\":얼굴 전체(두 눈과 입/코)가 보이거나 몸 대부분이 보이면 true(일부만 걸쳐 있으면 false)}"])
            wc = g.get("whole_character"); vis = g.get("visible_things", []); g = g["guesses"]
            jd = gj([f"정답은 '{cd['answer']}'. 추측 {g}, 또렷이 보이는 것 {vis}. 이 중에 정답(또는 같은 물건을 가리키는 말, 그 물건 전체가 또렷한 경우)이 있나? JSON {{\"hit\":true/false}}"])
            jd["hit"] = bool(jd["hit"] or wc); tries.append({"c0": c0, "start": [scx, scy], "guesses": g, "visible": vis, "hit": jd["hit"], "whole_character": wc})
            if not jd["hit"] or rnd == 3: break
            c0 = max(c0 * 0.78, max(side * 0.9, 175)); scx, scy = ocx + (bx1 - bx0) * 0.38 * (rnd + 1), ocy + (by1 - by0) * 0.38 * (rnd + 1)
        if tries[-1]["hit"]: log("A 경고: 최소 크롭에서도 맞힘", n, cd["answer"]); continue
        tx = a_texts(ep, img, cd["answer"], cd.get("why", ""))
        plan = {"slide": n, "answer": cd["answer"], "box_px": [ocx, ocy, bx1 - bx0, by1 - by0], "c0": c0, "start": [scx, scy], "tries": tries,
                "hint1": tx["hint1"], "hint2": tx["hint2"], "answer_banner": tx["answer_banner"], "answer_vo": tx["answer_vo"],
                "q_phrases": tx["q_phrases"], "too_easy": False}
        json.dump(plan, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return plan
    raise Infeasible("A: 적합한 수수께끼 소재 없음")


def build_A(ep, plan):
    img = ep.slides[plan["slide"]]
    ocx, ocy, bw, bh = plan["box_px"]; c0 = min(plan["c0"], FWA); scx, scy = plan.get("start", [ocx, ocy])
    bg = blur_bg(img)
    DUR = 18.0; T_H1, T_H2, T_CNT, T_REV, T_END, T_LOOP = 3.0, 6.0, 9.0, 12.0, 15.5, 17.5
    c1 = min(c0 * 1.5, FWA * 0.88)
    FCX = min(max(ocx, FWA / 2), SRCW - FWA / 2); FX0 = FCX - FWA / 2; s_full = W / FWA; TOP = CARD_CY - CARD_H // 2

    def card_state(t):
        if t < T_CNT: w = lerp(c0, c1, smooth(t / T_CNT)); u = 0.0
        elif t < T_REV: w = lerp(c1, c1 * 1.12, smooth((t - T_CNT) / 3)); u = 0.0
        else:
            k = smooth((t - T_REV) / 0.9); w = lerp(c1 * 1.12, FWA, k); u = k
        w = min(w, FWA)
        pre = smooth(min(t / T_CNT, 1)); bx_, by_ = lerp(scx, ocx, pre), lerp(scy, ocy, pre)
        return w, w / CARD_AR, lerp(bx_, FCX, u), lerp(by_, SRCH / 2, u)

    def main(t):
        c = bg.copy()
        w, h, cx, cy = card_state(t)
        c.paste(view(img, cx, cy, w, h, W, CARD_H).convert("RGBA"), (0, TOP))
        if t >= T_REV + 0.9:
            k = smooth((t - T_REV - 0.9) / 0.35); d = ImageDraw.Draw(c)
            fx = (ocx - FX0) * s_full; fy = TOP + ocy * s_full
            fx, fy, r = fit_circle(fx, fy, max(bw, bh) / 2 * s_full + 22, 0, TOP, W, TOP + CARD_H, max(bw, bh) / 2 * s_full * 0.9)
            r *= k
            for q in range(7): d.ellipse((fx - r - q, fy - r - q, fx + r + q, fy + r + q), outline=RED + (255,))
        if t < T_CNT:
            put(c, banner_layer("이건 뭘까?", 160), W / 2, 215, scale=1 + 0.025 * math.sin(t * 3.2))
        elif t < T_REV:
            n = 3 - int(t - T_CNT); u = (t - T_CNT) % 1
            put(c, banner_layer(str(n), 230, RED), W / 2, 230, scale=max(.3, ease_out_back(u / 0.4)))
        elif t < T_REV + 0.9:
            put(c, banner_layer("정답은?", 160), W / 2, 215)
        else:
            put(c, banner_layer(plan["answer_banner"], 190, RED), W / 2, 225 if TOP + ocy * s_full > 600 else 1420, scale=max(.3, pop_in(t, T_REV + 0.9, .45)))
        if t < T_REV:
            for i, (ts, txt) in enumerate(((T_H1, plan["hint1"]), (T_H2, plan["hint2"]))):
                k = pop_in(t, ts, 0.4)
                if k > 0: put(c, pill_layer(txt, 78), W / 2, 1640 + i * 135, scale=max(.01, k), shadow=True)
        else:
            k = pop_in(t, T_REV + 1.2, 0.45)
            if k > 0: put(c, pill_layer(plan["answer_vo"], 74, WHITE, RED), W / 2, 1640, scale=max(.01, k), shadow=True)
        return c

    return main, DUR, T_END, T_LOOP, bg


def audio_A(ep, plan, DUR):
    T_H1, T_H2, T_CNT, T_REV, T_END = 3.0, 6.0, 9.0, 12.0, 15.5
    ev = [(0.1, tts_line(ep, "이건 뭘까요?", "q"), 1.0), (T_H1, tts_line(ep, plan["hint1"], "h1"), 1.0),
          (T_H2, tts_line(ep, plan["hint2"], "h2"), 1.0), (7.7, tts_line(ep, "자, 정답은?", "go"), 1.0),
          (T_REV + 0.5, tts_line(ep, plan["answer_vo"], "ans"), 1.0), (T_END + 0.35, tts_line(ep, "정답 이야기는 본편에서!", "end"), 1.0)]
    for i in range(3): ev.append((T_CNT + i, tick(880 if i < 2 else 1320, amp=1.0), 0.45))
    ev += [(T_REV, sfx("swish"), 0.35), (T_REV + 0.3, sfx("sparkle"), 0.3), (T_H1 - 0.05, sfx("pop"), 0.3),
           (T_H2 - 0.05, sfx("pop"), 0.3), (T_END, sfx("swish"), 0.3)]
    return ev


# ───────────────────────── 포맷 B ─────────────────────────
def finish_B(ep, n, got, total_edits):
    img = ep.slides[n]
    base = np.asarray(img, float).copy()
    for g in got:
        mk = np.load(ep.work / f"b_s{n}_mask{g['idx']}.npy")
        edi = np.asarray(Image.open(ep.work / f"b_s{n}_edit{g['idx']}.png").convert("RGB"), float)
        base = base * (1 - mk[..., None]) + edi * mk[..., None]
    Image.fromarray(base.clip(0, 255).astype(np.uint8)).save(ep.work / "b_changed.png")
    texts = gj([ep.ctx(60) + f"\n\n'다른 그림 찾기' 숏츠(그림 번호 {n}, 바뀐 곳: {[g['desc'] for g in got]}). 초1 말투로 JSON: "
                '{"q_vo":"문제 대사 16자 이내(다른 곳 세 군데 찾기)","ans_vo":"정답 공개 대사 14자 이내(숫자 금지)","q_phrases":["질문형 제목 문구 3개 14자 이내"]}'])
    texts["q_phrases"] = safe_phrases(ep, " ".join(g["desc"] for g in got), texts.get("q_phrases", []), "다른 그림 찾기")
    plan = {"slide": n, "changes": [{"desc": g["desc"], "bbox": g["bbox"], "area": g["area"], "edit_en": g["edit_en"]} for g in got],
            "q_vo": texts["q_vo"], "ans_vo": texts["ans_vo"], "q_phrases": texts["q_phrases"], "image_calls": total_edits}
    json.dump(plan, open(ep.work / "plan_B.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return plan


def salvage_B(ep):
    """이미 만들어 둔 편집본(b_s*_edit*.png)을 전역 차이 검사로 재평가(이미지 비용 0)."""
    for n in sorted({int(re.match(r"b_s(\d+)_edit", f.name).group(1)) for f in ep.work.glob("b_s*_edit*.png")}):
        if n not in ep.slides: continue
        img = ep.slides[n]
        info = gj([png_part(img), "이 그림의 모든 생물 캐릭터(동물·사람·공룡) 박스를 JSON 으로: {\"chars\":[[ymin,xmin,ymax,xmax]...] (0~1000)}"])
        chars = [[float(v) / 1000 for v in b] for b in info.get("chars", []) if len(b) == 4]
        A = np.asarray(img.filter(ImageFilter.GaussianBlur(3)), float); got = []
        for f in sorted(ep.work.glob(f"b_s{n}_edit*.png")):
            ci = int(re.search(r"edit(\d+)", f.name).group(1))
            ed = Image.open(f).convert("RGB").resize(img.size, Image.LANCZOS)
            m = measure_diff(A, np.asarray(ed.filter(ImageFilter.GaussianBlur(3)), float), None, chars, got)
            log(f"B salvage s{n} edit{ci}: {m['why']}")
            if m["ok"]:
                got.append({"desc": "", "edit_en": "", "idx": ci, "bbox": m["bbox"], "area": m["area"], "m": m["mask"]}); np.save(ep.work / f"b_s{n}_mask{ci}.npy", m["mask"])
        if len(got) > len(getattr(ep, "partial", (0, 0, [], []))[2]): ep.partial = (n, ep.partial[1] if False else n, got, chars)
        if len(got) >= 3:
            got = got[:3]
            d = gj([png_part(img), f"이 그림의 {len(got)}곳에 다음 박스(x0,y0,x1,y1 픽셀, 그림 {img.width}x{img.height})가 있다: {[g['bbox'] for g in got]}. 각 박스 안의 물건을 한국어 짧은 명사구로. JSON {{\"descs\":[...]}}"])
            for g, ds in zip(got, d.get("descs", [])): g["desc"] = str(ds)
            return finish_B(ep, n, got, 0)
    return None


def fill_descs(img, got):
    if all(g.get("desc") for g in got): return
    d = gj([png_part(img), f"이 그림의 {len(got)}곳에 다음 박스(x0,y0,x1,y1 픽셀, 그림 {img.width}x{img.height})가 있다: {[g['bbox'] for g in got]}. 각 박스 안의 물건을 한국어 짧은 명사구로. JSON {{\"descs\":[...]}}"])
    for g, ds in zip(got, d.get("descs", [])):
        if not g.get("desc"): g["desc"] = str(ds)


def augment_B(ep, budget=6):
    """가장 많이 건진 장면에 남은 곳만 새 편집으로 보충(기존 편집·마스크 재사용)."""
    part = getattr(ep, "partial", None)
    if not part or len(part[2]) < 1 or ep.no_new_edits: return None
    n, _, got, chars = part; img = ep.slides[n]; Ww, Hh = img.size
    taken = ", ".join(f"[{int(g['bbox'][1]/Hh*1000)},{int(g['bbox'][0]/Ww*1000)},{int(g['bbox'][3]/Hh*1000)},{int(g['bbox'][2]/Ww*1000)}]" for g in got)
    info = gj([png_part(img), f"이 동화 그림에서 '다른 그림 찾기' 퍼즐을 위해 바꿀 후보 6개를 정하라. 규칙: 캐릭터(생물)는 금지. 배경·소품만. 각 물건은 화면 폭의 4~12%, "
               f"그림 가장자리에서 떨어져 있고 다음 영역(ymin,xmin,ymax,xmax 0~1000)에서 멀리(화면 폭의 25% 이상) 떨어져 있어야 한다: {taken}. "
               "바꾸는 방법은 '아주 다른 색으로 바꾸기'나 '물건 지우기'. JSON {\"cands\":[{\"desc\":\"한국어 설명\",\"box\":[ymin,xmin,ymax,xmax],\"edit_en\":\"영어 편집 지시 1문장\"}]}"])
    A = np.asarray(img.filter(ImageFilter.GaussianBlur(3)), float); used = 0; ci = 20
    for cd in info.get("cands", []):
        if len(got) >= 3 or used >= budget: break
        ci += 1
        ed = gemini_edit(img, f"Edit this children's picture book illustration. Make EXACTLY ONE change: {cd['edit_en']}. "
                         "The change must be big and very noticeable. Keep everything else pixel-identical: same composition, same characters, "
                         "poses, faces, other objects, colors and line style. Do not add text. Do not move or redraw the characters.")
        used += 1; ep.image_calls += 1
        if ed is None: continue
        ed = ed.resize(img.size, Image.LANCZOS); ed.save(ep.work / f"b_s{n}_edit{ci}.png")
        y0, x0, y1, x1 = [v / 1000 for v in cd["box"]]
        m = measure_diff(A, np.asarray(ed.filter(ImageFilter.GaussianBlur(3)), float), (x0, y0, x1, y1), chars, got)
        log(f"B aug s{n} {cd['desc']}: {m['why']}")
        if m["ok"]:
            np.save(ep.work / f"b_s{n}_mask{ci}.npy", m["mask"])
            got.append({"desc": cd["desc"], "edit_en": cd["edit_en"], "idx": ci, "bbox": m["bbox"], "area": m["area"], "m": m["mask"]})
    if len(got) >= 3:
        got = got[:3]; fill_descs(img, got)
        return finish_B(ep, n, got, ep.image_calls)
    return None


def plan_B(ep):
    cache = ep.work / "plan_B.json"
    if cache.exists(): return json.load(open(cache, encoding="utf-8"))
    r = salvage_B(ep)
    if r: return r
    r = augment_B(ep)
    if r: return r
    if getattr(ep, 'no_new_edits', False): raise Infeasible('B: 기존 편집본으로 3곳 불가(예산상 신규 편집 금지)')
    pick = gj([png_part(ep.sheet(), 1800), ep.ctx(60) + "\n\n'다른 그림 찾기'(그림 한 장에서 3곳을 바꾸고 맞히게 하는 퍼즐)에 가장 알맞은 장면 번호 3개를 우선순위로. "
              "조건: 배경·소품(과일, 그릇, 꽃, 신발, 가구, 간판 등)이 또렷하고 큼직하게 여럿 있고, 인물이 적거나 화면 한쪽에 몰려 있는 장면. "
              'JSON {"slides":[번호,번호,번호]}'])["slides"]
    total_edits = 0
    for n in pick[:3]:
        n = int(n)
        if n not in ep.slides: continue
        img = ep.slides[n]
        info = gj([png_part(img), "이 동화 그림에서 '다른 그림 찾기' 퍼즐을 위해 바꿀 후보 6개를 정하라. 규칙: 캐릭터(동물·사람·공룡 등 생물)는 절대 후보 금지. "
                   "배경·소품만. 각 물건은 화면 폭의 6% 이상 큼직해야 하고, 서로 멀리 떨어져 있어야 한다. 바꾸는 방법은 '아주 다른 색으로 바꾸기'(예: 빨강→파랑)나 '물건 지우기'처럼 "
                   "초1이 한눈에 알 만큼 확실한 것. JSON {\"chars\":[[ymin,xmin,ymax,xmax]...(모든 생물 캐릭터 박스, 0~1000)],"
                   "\"cands\":[{\"desc\":\"한국어 설명\",\"box\":[ymin,xmin,ymax,xmax],\"edit_en\":\"영어 편집 지시 1문장(예: Recolor the red apple on the table to bright blue)\"}]}"])
        chars = [[v / 1000 for v in b] for b in info.get("chars", [])]
        got = []
        A = np.asarray(img.filter(ImageFilter.GaussianBlur(3)), float)
        for ci, cd in enumerate(info["cands"]):
            if len(got) >= 3 or total_edits >= 7: break
            ed = gemini_edit(img, f"Edit this children's picture book illustration. Make EXACTLY ONE change: {cd['edit_en']}. "
                             "The change must be big and very noticeable. Keep everything else pixel-identical: same composition, same characters, "
                             "poses, faces, other objects, colors and line style. Do not add text. Do not move or redraw the characters.")
            total_edits += 1; ep.image_calls += 1
            if ed is None: continue
            ed = ed.resize(img.size, Image.LANCZOS); ed.save(ep.work / f"b_s{n}_edit{ci}.png")
            y0, x0, y1, x1 = [v / 1000 for v in cd["box"]]
            m = measure_diff(A, np.asarray(ed.filter(ImageFilter.GaussianBlur(3)), float), (x0, y0, x1, y1), chars, got)
            log(f"B s{n} cand{ci} {cd['desc']}: {m['why']}")
            if m["ok"]: got.append({"desc": cd["desc"], "edit_en": cd["edit_en"], "idx": ci, "bbox": m["bbox"], "area": m["area"], "m": m["mask"]})
            if got and got[-1].get("idx") == ci:
                np.save(ep.work / f"b_s{n}_mask{ci}.npy", m["mask"])
        if len(got) == 3: return finish_B(ep, n, got, total_edits)
    raise Infeasible("B: 바뀐 곳 3곳을 확보하지 못함")


def measure_diff(A, B, box, chars, taken):
    """바뀐 영역 검사: 기대 박스 근처 차이 성분만 취하고 크기·색차·캐릭터 겹침·중복 확인."""
    Hh, Ww = A.shape[:2]
    d = np.abs(A - B).max(2); m = d > 45
    m = ndi.binary_opening(m, iterations=2)
    lab, k = ndi.label(ndi.binary_dilation(m, iterations=6))
    sel = np.zeros_like(m)
    if box is None:      # 기대 박스 없이: 가장 큰 차이 성분 하나(편집본 재활용 모드)
        best, bn = 0, 0
        for i in range(1, k + 1):
            n_ = int(((lab == i) & m).sum())
            if n_ > bn: best, bn = i, n_
        if best: sel = (lab == best) & m
    else:
        x0, y0, x1, y1 = box; pad = 0.05
        ex = (max(0, int((x0 - pad) * Ww)), max(0, int((y0 - pad) * Hh)), min(Ww, int((x1 + pad) * Ww)), min(Hh, int((y1 + pad) * Hh)))
        for i in range(1, k + 1):
            comp = (lab == i) & m
            ys, xs = np.nonzero(comp)
            if len(xs) == 0: continue
            if ex[0] <= xs.mean() <= ex[2] and ex[1] <= ys.mean() <= ex[3]: sel |= comp
    if sel.sum() == 0: return {"ok": False, "why": "차이 없음", "bbox": None, "area": 0, "mask": None}
    ys, xs = np.nonzero(sel); bb = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    barea = (bb[2] - bb[0]) * (bb[3] - bb[1]); frac = barea / (Ww * Hh); mean_d = float(d[sel].mean())
    ov = 0.0
    for c in chars:
        cx0, cy0, cx1, cy1 = c[1] * Ww, c[0] * Hh, c[3] * Ww, c[2] * Hh
        inb = ((xs >= cx0) & (xs <= cx1) & (ys >= cy0) & (ys <= cy1)).mean(); ov = max(ov, inb)
    why = f"bbox면적 {frac*100:.2f}% 색차 {mean_d:.0f} 캐릭터겹침 {ov*100:.0f}%"
    ok = frac >= 0.005 and mean_d >= 55 and ov < 0.12 and frac < 0.16
    mask = ndi.binary_closing(ndi.binary_dilation(sel, iterations=10), iterations=6)
    rr = lambda b: max(b[2] - b[0], b[3] - b[1]) / 2 + 16        # 정답 동그라미 반지름(원본 px)
    ccx, ccy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    if min(ccx, Ww - ccx, ccy, Hh - ccy) < rr(bb) * 0.8:
        ok = False; why += " 가장자리"
    if rr(bb) > 200: ok = False; why += " 너무큼"
    for t in taken:
        tb, tm = t["bbox"], t.get("m")
        c2 = ((tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2)
        far = math.hypot(ccx - c2[0], ccy - c2[1]) > rr(bb) + rr(tb) + 24     # 동그라미끼리 안 겹치게
        ovl = 0.0
        if tm is not None:
            a_, b_ = mask > 0.5, tm > 0.5
            ovl = (a_ & b_).sum() / max(1, min(a_.sum(), b_.sum()))
        if not far or ovl > 0.2: ok = False; why += " 중복"
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), float) / 255
    return {"ok": ok, "why": why + (" OK" if ok else " 탈락"), "bbox": bb, "area": round(frac, 4), "mask": mask}


def build_B(ep, plan):
    A_IMG = ep.slides[plan["slide"]]; B_IMG = Image.open(ep.work / "b_changed.png").convert("RGB")
    bg = blur_bg(A_IMG, 0.45)
    DUR = 17.0; T0, T1, T_REV, T_END, T_LOOP = 0.8, 10.8, 11.0, 14.4, 16.4
    boxes = [g["bbox"] for g in plan["changes"]]
    circ = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, max(b[2] - b[0], b[3] - b[1]) / 2 + 16) for b in boxes]
    circ = [fit_circle(cx, cy, r, 0, 0, SRCW, SRCH, r * 0.85) for cx, cy, r in circ]
    for i in range(3):
        for k in range(i):
            if math.hypot(circ[i][0] - circ[k][0], circ[i][1] - circ[k][1]) < circ[i][2] + circ[k][2]: log("B 경고: 동그라미 겹침", i, k)
    # 세로로 크게: 좌우를 잘라 높이 확보(동그라미 3개는 모두 들어오게)
    cw = SRCH * W / 780                                   # IH=780 기준 크롭 너비(≈1064)
    ux0 = min(c[0] - c[2] for c in circ) - 14; ux1 = max(c[0] + c[2] for c in circ) + 14
    cw = min(SRCW, max(cw, ux1 - ux0))
    X0 = min(max((ux0 + ux1) / 2 - cw / 2, 0), SRCW - cw); S = W / cw; IW = W; IH = int(round(SRCH * S))
    GAPY = 12; Y_TOP0 = 140 + (1560 - (2 * IH + GAPY)) // 2; Y_BOT0 = Y_TOP0 + IH + GAPY
    def prep(img): return img.resize((IW, IH), Image.LANCZOS, box=(X0, 0, X0 + cw, SRCH)).convert("RGBA")
    base_a, base_b = prep(A_IMG), prep(B_IMG)
    def pic(base, k_n, k):
        im = base.copy(); d = ImageDraw.Draw(im)
        for i, (cx, cy, r0) in enumerate(circ[:k_n]):
            r = r0 * S * (k if i == k_n - 1 else 1.0); x, y = (cx - X0) * S, cy * S
            for q in range(7): d.ellipse((x - r - q, y - r - q, x + r + q, y + r + q), outline=RED + (255,))
        return im

    def main(t):
        c = bg.copy(); n = 0; kk = 1.0
        if t >= T_REV: n = min(3, int((t - T_REV) / 0.7) + 1); kk = smooth(((t - T_REV) % 0.7) / 0.3)
        if t < T_REV: put(c, banner_layer("다른 곳 세 군데를 찾아라!", 84), W / 2, 70)
        else: put(c, banner_layer("찾았다!", 110, RED), W / 2, 76, scale=max(.3, pop_in(t, T_REV, .4)))
        if n: c.paste(pic(base_a, n, kk), (0, Y_TOP0)); c.paste(pic(base_b, n, kk), (0, Y_BOT0))
        else: c.paste(base_a, (0, Y_TOP0)); c.paste(base_b, (0, Y_BOT0))
        bw, bx = 900, (W - 900) // 2
        u = min(max((t - T0) / (T1 - T0), 0), 1)
        bar = Image.new("RGBA", (bw + 16, 60), (0, 0, 0, 0)); d = ImageDraw.Draw(bar)
        d.rounded_rectangle((0, 0, bw + 15, 59), 30, fill=(255, 255, 255, 240))
        rem = int(bw * (1 - u))
        if rem > 8: d.rounded_rectangle((8, 8, 8 + rem, 51), 22, fill=(RED if u > 0.7 else (255, 170, 60) if u > 0.4 else (70, 190, 120)) + (255,))
        put(c, bar, W / 2, 1760)
        if T0 <= t < T1 + 0.2: put(c, banner_layer(str(max(1, 10 - int(u * 10))), 80, bg=(255, 255, 255, 200)), W / 2, 1855)
        return c
    return main, DUR, T_END, T_LOOP, bg


def audio_B(ep, plan, DUR):
    T0, T_REV, T_END = 0.8, 11.0, 14.4
    ev = [(0.1, tts_line(ep, plan["q_vo"], "q"), 1.0)]
    for i in range(10): ev.append((T0 + 1 + i, tick(660 if i < 7 else 990, 0.09), 0.25 if i < 7 else 0.5))
    for i in range(3): ev += [(T_REV + 0.7 * i, sfx("pop"), 0.5), (T_REV + 0.7 * i, sfx("swish", dur=0.25), 0.2)]
    ev += [(T_REV + 0.05, tts_line(ep, plan["ans_vo"], "ans"), 1.0), (T_REV + 2.1, sfx("sparkle"), 0.3),
           (T_END, sfx("swish"), 0.3), (T_END + 0.35, tts_line(ep, "정답 이야기는 본편에서!", "end"), 1.0)]
    return ev


# ───────────────────────── 포맷 C ─────────────────────────
SOUNDS = {"thump": "쿵(무겁게 걷거나 떨어지는 소리)", "shutter": "찰칵(사진)", "clap": "짝(박수)", "pop": "퐁(작게 튀거나 솟는 소리)",
          "pop_pop": "퐁퐁", "sparkle": "반짝(마법·별 반짝이는 소리)", "flutter": "펄럭펄럭(날개·종이·깃발)", "swish": "쭈욱/휙(늘어나거나 빠르게 지나감)",
          "roll": "데굴데굴(굴러가는 소리)", "knock": "똑똑(문 두드리기)", "splash": "풍덩(물에 빠지거나 첨벙)", "ding": "딩동(종·초인종·알림)"}
SOUND_LONG = {"roll", "sparkle", "flutter", "splash", "ding"}


def plan_C(ep):
    cache = ep.work / "plan_C.json"
    if cache.exists(): return json.load(open(cache, encoding="utf-8"))
    opts = "\n".join(f"- {k}: {v}" for k, v in SOUNDS.items())
    banned = ""; nogo = set(); spare = []
    for attempt in range(7):
        j = gj([ep.ctx(120) + "\n\n'무슨 소리일까?' 숏츠: 소리만 들려주고 그림 3장 중 어떤 장면의 소리인지 맞히게 한다. 이 동화의 장면에서 실제로 날 법한 소리를 아래 합성 효과음에서 "
               "고른다(없으면 possible=false 로 포기. 억지 금지).\n" + opts + "\n정답 장면 1개와, 그 소리가 전혀 어울리지 않고 정답 장면과 장소·배경이 확실히 다른(같은 연못·같은 방 등 금지) 장면 2개를 번호로. "
               "오답 장면에는 그 소리가 날 만한 요소가 없어야 한다. 소리가 뚜렷한 장면이어야 한다." + banned +
               ' JSON {"possible":true/false,"sound":"효과음 키","sound_word":"한글 의성어 2~4자+느낌표(예: 쿵!)","answer_slide":번호,"distractors":[번호,번호],'
               '"ans_banner":"정답 화면 글자 10자 이내(숫자·번호 금지, 예: 첨벙 물놀이!)","ans_vo":"정답 공개 대사 16자 이내(초1 말투, 숫자·번호 금지, 예: 첨벙 소리였어요!)","count":2또는3,"q_phrases":["질문형 제목 문구 3개 14자 이내(의성어·소리 종류·장면 암시 금지, 예: 무슨 소리일까요?)"],"why":"..."}'])
        if not j.get("possible") or j.get("sound") not in SOUNDS: raise Infeasible("C: 어울리는 효과음 없음 - " + str(j.get("why")))
        ids = [int(j["answer_slide"])] + [int(x) for x in j["distractors"]]
        if any(i not in ep.slides for i in ids) or len(set(ids)) != 3: continue
        log('C 시도', j['sound'], ids, j.get('why','')[:50])
        # 정답과 오답이 같은 장소처럼 보이거나, 오답이 그 소리와 어울려 보이면 탈락(비전 유사도 검사)
        sim = gj([png_part(ep.sheet(ids, cols=3, tw=560), 1700), f"그림 3장(왼쪽부터 번호 {ids[0]}, {ids[1]}, {ids[2]}). 첫째({ids[0]})는 정답 장면이다('{SOUNDS[j['sound']]}' 소리). "
                  f"다른 두 장({ids[1]}, {ids[2]})에 대해 판단하라. confusing = 정답 장면과 배경·장소·구도가 거의 같아서(같은 연못 한 곳을 비슷하게 찍은 것 등) 초1이 구분하기 힘든 것만. "
                  f"sound_plausible = 그 소리를 내는 물체나 동작이 그림 속에 분명히 보여서 그 소리가 날 것 같은 것만(막연히 가능한 정도는 제외). "
                  f'JSON {{"confusing":[번호들],"sound_plausible":[번호들]}}'])
        pl = {int(x) for x in sim.get("sound_plausible", [])} & set(ids[1:]); cf = {int(x) for x in sim.get("confusing", [])} & set(ids[1:])
        conf = pl | cf
        if conf:
            log("C 오답 카드 헷갈림, 재선정", sim); nogo |= conf
            banned = f" 오답으로 쓰면 안 되는 장면 번호(정답과 비슷하거나 소리가 날 법함): {sorted(nogo)}. 반드시 이 번호들을 피하라."
            if not pl: spare.append((len(cf), j, ids, sim))       # 소리와 무관하지만 장소만 비슷 -> 최후 보루 후보
            continue
        r = finalize_C(ep, j, ids, sim)
        if r: return r
    for _, j, ids, sim in sorted(spare, key=lambda x: x[0]):      # 마지막 수단: 소리 무관 + 비슷한 장소 1곳 이하
        if _ <= 1:
            r = finalize_C(ep, j, ids, sim)
            if r: log("C 최후 보루 선택(장소 비슷 1장)"); return r
    raise Infeasible("C: 선택지 검증 실패")


def finalize_C(ep, j, ids, sim):
    rot = {0: [1, 0, 2], 1: [0, 2, 1], 2: [2, 0, 1]}[len(ep.dir.name) % 3]
    order = [ids[i] for i in rot]
    chk = gj([png_part(ep.sheet(order, cols=1, tw=640), 1400), f"그림 3장(번호 표시). '{SOUNDS[j['sound']]}' 소리가 나는 장면은? 가장 알맞은 번호 1개. 동화:\n{ep.ctx(50)}\n"
              'JSON {"slide":번호,"confident":true/false}'])
    if int(chk["slide"]) != ids[0]: log("C 검증 불일치", chk, ids[0]); return None
    fc = gj([png_part(ep.slides[ids[0]]), f"이 그림에서 '{SOUNDS[j['sound']]}' 소리를 내는 곳(주체)의 중심점. JSON {{\"x\":0~1000,\"y\":0~1000}}"])
    j["focus_x"] = float(fc.get("x", 500)) / 1000 * SRCW
    j["q_phrases"] = safe_phrases(ep, f"{j['sound_word']} {SOUNDS[j['sound']]} {j['ans_banner']}", j.get("q_phrases", []), "무슨 소리일까")
    j["order"] = order; j["answer_idx"] = order.index(ids[0]); j["verify"] = chk; j["sim"] = sim
    json.dump(j, open(ep.work / "plan_C.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return j


def build_C(ep, plan):
    order = plan["order"]; ANS = plan["answer_idx"]; snd = plan["sound"]
    bg = blur_bg(ep.slides[order[ANS]], 0.45)
    DUR = 16.0; T_CARDS, T_REV, T_END, T_LOOP = 4.0, 10.0, 13.4, 15.4
    sp = 1.5 if snd in SOUND_LONG else 0.85
    cnt = 2 if snd in SOUND_LONG else int(plan.get("count", 3))
    Q = [1.7 + i * sp for i in range(cnt)]; HINT = [7.3] if snd in SOUND_LONG else [7.3, 8.15]; ANST = [T_REV + 0.1] + ([] if snd in SOUND_LONG else [T_REV + 0.95])
    CW = W; CH = 550; GAP = 12; Y0 = 212; SH0 = CW / CH          # 카드: 화면 폭 꽉, 세 장이 화면 높이의 86%
    YS = [Y0 + CH // 2 + (CH + GAP) * i for i in range(3)]
    FX = float(plan.get("focus_x", SRCW / 2)); RH = 1700
    cards = {}
    def crop_to(n, cx, cy, sw, sh, ow, oh):
        sh = min(sh, SRCH); sw = min(sw, SRCW)
        x0 = min(max(cx - sw / 2, 0), SRCW - sw); y0 = min(max(cy - sh / 2, 0), SRCH - sh)
        o = ep.slides[n].resize((ow, oh), Image.LANCZOS, box=(x0, y0, x0 + sw, y0 + sh)).convert("RGBA")
        return o.filter(ImageFilter.UnsharpMask(2.0, 60, 2)) if ow > sw * 1.5 else o
    def card(n):
        if n not in cards: cards[n] = crop_to(n, SRCW / 2, SRCH / 2, SRCW, SRCW / SH0, CW, CH)
        return cards[n]
    def badge(i):
        d = 100; im = Image.new("RGBA", (d, d), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        dr.ellipse((0, 0, d - 1, d - 1), fill=RED + (255,), outline=WHITE + (255,), width=7)
        dr.text((d / 2, d / 2 + 2), str(i + 1), font=font(70), fill=WHITE + (255,), anchor="mm"); return im
    def fx(t, times):
        best = None
        for i, tt in enumerate(times):
            if 0 <= t - tt < 0.6: best = (i, (t - tt) / 0.6)
        return best
    navy = Image.new("RGBA", (W, H), (36, 50, 82, 255))
    nd = ImageDraw.Draw(navy)
    for y in range(0, H, 4): nd.rectangle((0, y, W, y + 4), fill=(int(36 + 30 * y / H), int(50 + 40 * y / H), int(82 + 40 * y / H), 255))
    qmark = text_layer("?", 900, (222, 236, 250), (222, 236, 250), sw=0)

    def main(t):
        if t < T_CARDS:
            c = navy.copy(); f = fx(t, Q)
            for tt in Q:
                u = (t - tt) / 1.2
                if 0 <= u < 1:
                    r = 150 + 520 * u; ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(ov).ellipse((W / 2 - r, 1000 - r, W / 2 + r, 1000 + r), outline=(150, 190, 235, int(170 * (1 - u))), width=16); c.alpha_composite(ov)
            sh = int(14 * (1 - f[1]) * math.sin(f[1] * 40)) if f else 0
            put(c, qmark, W / 2 + sh, 1000, scale=1 + (0.06 * (1 - f[1]) if f else 0))
            put(c, banner_layer("무슨 소리일까?", 160), W / 2, 215, scale=1 + 0.03 * math.sin(t * 3.2))
            put(c, text_layer("소리를 잘 들어 보세요", 66, (205, 220, 240), (36, 50, 82), sw=0), W / 2, 1700)
            return c
        c = bg.copy()
        if t < T_REV:
            put(c, banner_layer("어떤 그림일까?", 120), W / 2, 100)
            for i, n in enumerate(order):
                k = pop_in(t, T_CARDS + 0.4 * i, 0.4)
                if k <= 0: continue
                bob = 4 * math.sin(t * 3 + i * 1.3)
                put(c, card(n), W / 2, YS[i] + bob, scale=max(.01, k), shadow=True)
                put(c, badge(i), 62, YS[i] - CH / 2 + 62 + bob, scale=max(.01, k))
            return c
        u = t - T_REV; k = smooth(u / 0.5)
        for i, n in enumerate(order):
            if i != ANS: put(c, card(n), W / 2, YS[i], alpha=max(0, 1 - k * 1.4))
        oh = int(lerp(CH, RH, k)); cy = lerp(YS[ANS], CARD_CY, k)
        sh_ = lerp(SRCW / SH0, SRCH, k); sw_ = sh_ * CW / oh
        im = crop_to(order[ANS], lerp(SRCW / 2, FX, k), SRCH / 2, sw_, sh_, CW, oh)
        put(c, im, W / 2, cy, shadow=True)
        if u < 0.5: put(c, banner_layer("정답은?", 160), W / 2, 215)
        else: put(c, banner_layer(plan["ans_banner"], 150, RED), W / 2, 215, scale=max(.3, pop_in(u, 0.5, .45)))
        if u > 0.3:
            f = fx(t, ANST)
            put(c, text_layer(plan["sound_word"], 230, RED, WHITE, sw=14), W / 2, 1420, scale=(1 + (0.3 * (1 - f[1]) if f else 0)) * max(.3, pop_in(u, 0.3, .35)))
        if u > 0.9: put(c, pill_layer(plan["ans_vo"], 70, WHITE, RED), W / 2, 1640, scale=max(.01, pop_in(u, 0.9, .45)), shadow=True)
        return c
    plan["_times"] = {"q": Q, "hint": HINT, "ans": ANST, "T_CARDS": T_CARDS, "T_REV": T_REV, "T_END": T_END}
    return main, DUR, T_END, T_LOOP, bg


def audio_C(ep, plan, DUR):
    tm = plan["_times"]; snd = plan["sound"]
    ev = [(0.1, tts_line(ep, "무슨 소리일까요?", "q"), 1.0)]
    # VO 가 첫 효과음(1.7s)과 겹치지 않게 질문은 짧게 두고 효과음은 1.7s 이후
    for tt in tm["q"]: ev.append((tt, sfx(snd), 0.9))
    ev.append((tm["T_CARDS"] - 0.05, tts_line(ep, "어떤 그림일까요?", "pick"), 1.0))
    for tt in tm["hint"]: ev.append((tt, sfx(snd), 0.6))
    for tt in tm["ans"]: ev.append((tt, sfx(snd), 0.9))
    ev += [(tm["T_REV"] + 0.5, tts_line(ep, plan["ans_vo"], "ans"), 1.0), (tm["T_END"], sfx("swish"), 0.3),
           (tm["T_END"] + 0.35, tts_line(ep, "정답 이야기는 본편에서!", "end"), 1.0)]
    for i in range(3): ev.append((tm["T_CARDS"] + 0.4 * i, sfx("pop"), 0.3))
    return ev


# ───────────────────────── 포맷 D ─────────────────────────
HAM_CROP = (440, 140, 860, 640); HAM_FEET = (651 - 440, 611 - 140)
HAM_EYE = (620, 248, 754, 320); HAM_MOUTH = (626, 322, 718, 394)
MOUTH_MAP = {"A": "mouth_closed", "B": "mouth_i", "C": "base", "D": "mouth_a", "E": "mouth_o", "F": "mouth_o", "G": "mouth_i", "H": "base", "X": "mouth_closed"}


class Ham:
    def __init__(self):
        L = lambda n: Image.open(HAMDIR / f"{n}.png").convert("RGBA")
        self.base = L("base"); self.eye = L("eyes_closed")
        self.mouth = {n: L(n) for n in set(MOUTH_MAP.values())}
        def fm(box, r):
            m = Image.new("L", self.base.size, 0); ImageDraw.Draw(m).rectangle(box, fill=255); return m.filter(ImageFilter.GaussianBlur(r))
        self.eye_m = fm(HAM_EYE, 5); self.mouth_m = fm(HAM_MOUTH, 6); self.cache = {}

    def frame(self, eye, mouth):
        k = (eye, mouth)
        if k in self.cache: return self.cache[k]
        im = self.base.copy()
        if mouth != "base": im.paste(self.mouth[mouth], (0, 0), self.mouth_m)
        if eye > 0:
            ec = Image.composite(self.eye, self.base, self.eye_m.point(lambda v: int(v * eye)))
            im.paste(ec, (0, 0), self.eye_m)
        im = im.crop(HAM_CROP); self.cache[k] = im; return im

    def face(self):
        im = self.base.crop((530, 150, 830, 450)); bg = Image.new("RGBA", im.size, (251, 246, 236, 255)); bg.alpha_composite(im); return bg


def plan_D(ep):
    cache = ep.work / "plan_D.json"
    if cache.exists(): return json.load(open(cache, encoding="utf-8"))
    nm = " 와 ".join(c[1] for c in ep.chars[:2])
    j = gj([png_part(ep.sheet(), 1800), ep.ctx(100) + f"\n\n'햄찌쌤의 한 가지 질문' 숏츠. 햄찌쌤(선생님 햄스터)이 동화 주제에 맞는 질문을 1개 던진다. 1학년이 상상하며 답을 떠올릴 수 있는 열린 질문. "
            f"댓글·구독·좋아요 유도 금지. 이어서 본편에서 {nm}(주인공)이 한 해결/행동 장면 3컷(번호 표시된 그림에서 서로 다른 장면, 오름차순)을 소개한다. JSON "
            '{"question":"햄찌쌤 질문 22자 이내(예: 너라면 ~ 해 볼래?)","q_lines":"화면용 2~3줄 줄바꿈(\\n) 포함 같은 문장","ex_line":"예시 소개 대사 18자 이내(예: 꼬리와 쭈욱이는 이렇게 했어요!)",'
            '"scenes":[{"slide":번호,"caption":"장면 설명 14자 이내"}...3개],"q_phrases":["질문형 제목 문구 3개 16자 이내"]}'])
    sc = [s for s in j["scenes"] if int(s["slide"]) in ep.slides][:3]
    if len(sc) < 3: raise Infeasible("D: 장면 3컷 확보 실패")
    j["scenes"] = sc; json.dump(j, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1); return j


def build_D(ep, plan):
    ham = Ham(); scenes = plan["scenes"]
    bg = blur_bg(ep.slides[int(scenes[0]["slide"])], 0.5)
    DUR = 17.0; T_Q0 = 0.2; T_SCN = 4.4; SEGT = 2.8; T_END = T_SCN + 3 * SEGT + 0.3; T_LOOP = 15.6
    q_vo = tts_line(ep, plan["question"], "q"); ex_vo = tts_line(ep, plan["ex_line"], "ex")
    CUES = {"q": rhubarb_cues(ep, "q"), "ex": rhubarb_cues(ep, "ex")}
    SEG = [(T_Q0, "q"), (T_SCN + 0.1, "ex")]
    BL = [2.0, 5.6, 9.0, 12.2]; SCALE = 1.4
    def mouth_at(t):
        for st, k in SEG:
            tv = t - st
            if 0 <= tv <= CUES[k][-1]["end"]:
                cur = "X"
                for cu in CUES[k]:
                    if cu["start"] <= tv: cur = cu["value"]
                return MOUTH_MAP[cur]
        return "mouth_closed"
    def paste_ham(c, t, feet=(540, 1880)):
        tc = math.floor(t * 12) / 12; eye = 0
        for b in BL:
            d = tc - b
            if -0.09 <= d <= 0.17: eye = 0.5 if (d < 0 or d > 0.08) else 1
        im = ham.frame(eye, mouth_at(tc)); br = 1 + 0.012 * math.sin(2 * math.pi * 0.9 * tc)
        im2 = im.resize((int(im.width * SCALE), int(im.height * SCALE * br)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.2, 60, 2))
        fx_, fy_ = HAM_FEET[0] * SCALE, HAM_FEET[1] * SCALE * br
        sh = Image.new("RGBA", (500, 120), (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse((40, 30, 460, 90), fill=(90, 70, 50, 70)); sh = sh.filter(ImageFilter.GaussianBlur(9))
        c.alpha_composite(sh, (int(feet[0] - 250), int(feet[1] - 60)))
        c.alpha_composite(im2, (int(feet[0] - fx_), int(feet[1] - fy_)))
    ql = plan["q_lines"].replace("\\n", "\n")
    if "\n" not in ql or max(len(x) for x in ql.split("\n")) > 12:
        words, lines, cur = plan["question"].split(), [], ""
        for w_ in words:
            if cur and len(cur) + 1 + len(w_) > 12: lines.append(cur); cur = w_
            else: cur = (cur + " " + w_).strip()
        lines.append(cur); ql = "\n".join(lines)
    def main(t):
        c = bg.copy()
        if t < T_SCN - 0.15:
            put(c, banner_layer(ql, 120, lh=1.16), W / 2, 560)
            paste_ham(c, t)
        else:
            a = smooth((t - (T_SCN - 0.15)) / 0.35)
            put(c, banner_layer(plan["ex_line"], 84), W / 2, 190, alpha=a)
            idx = min(int((t - T_SCN) / SEGT), 2) if t >= T_SCN else 0
            sc = scenes[idx]; ts = T_SCN + SEGT * idx; u = max(t - ts, 0)
            kk = pop_in(t, ts, 0.3) if t >= T_SCN else 0
            n = int(sc["slide"]); s = 1.0 + 0.08 * min(u / SEGT, 1)
            w = int(1080 * s); h = int(w * SRCH / SRCW)
            card = ep.slides[n].resize((w, h), Image.LANCZOS).crop(((w - 1080) // 2, (h - 617) // 2, (w - 1080) // 2 + 1080, (h - 617) // 2 + 617)).convert("RGBA")
            if kk > 0.01: put(c, card, W / 2, 330 + 308, scale=max(.01, kk) if kk < 1 else 1.0, shadow=True)
            if kk > 0.9: put(c, pill_layer(sc["caption"], 70, WHITE, RED), W / 2, 1050, scale=max(.01, pop_in(t, ts + 0.25, .35)))
            paste_ham(c, t)
        return c
    return main, DUR, T_END, T_LOOP, bg, ham, T_SCN, SEGT


def audio_D(ep, plan, DUR, T_SCN, SEGT):
    T_END = T_SCN + 3 * SEGT + 0.3
    ev = [(0.2, tts_line(ep, plan["question"], "q"), 1.0), (T_SCN + 0.1, tts_line(ep, plan["ex_line"], "ex"), 1.0),
          (T_END + 0.35, tts_line(ep, "본편에서 만나요!", "end"), 1.0), (T_END, sfx("swish"), 0.3)]
    for i in range(3): ev += [(T_SCN + SEGT * i, sfx("swish", dur=0.3), 0.3), (T_SCN + SEGT * i + 0.05, sfx("pop"), 0.35)]
    return ev


# ───────────────────────── 실행 ─────────────────────────
ORDER = "ABCD"
NAMES = {"A": "그림수수께끼", "B": "다른그림찾기", "C": "무슨소리일까", "D": "햄찌쌤질문"}


def last_format():
    best = None
    for p in (PROJ / "output").glob("*/shorts_puzzle.json"):
        try: m = p.stat().st_mtime
        except OSError: continue
        if best is None or m > best[0]: best = (m, json.load(open(p, encoding="utf-8")).get("format"))
    return best[1] if best else None


def run(ep, fmt, lang):
    t0 = time.time()
    faces = ep.faces()
    sub = ep.title
    if fmt == "A":
        plan = plan_A(ep); main, DUR, T_END, T_LOOP, bg = build_A(ep, plan); ev = audio_A(ep, plan, DUR)
        probes = [0, 2.0, 5.0, 8.5, 9.5, 12.3, 13.4, 14.5, 16.5, 17.95]; line = "정답 이야기는\n본편에서!"
        meta = {"answer": plan["answer"], "topic": f"슬라이드 {plan['slide']} · {plan['answer']} (첫 크롭 맞힘 시도 {len(plan['tries'])}회)"}
    elif fmt == "B":
        plan = plan_B(ep); main, DUR, T_END, T_LOOP, bg = build_B(ep, plan); ev = audio_B(ep, plan, DUR)
        probes = [0, 3, 8, 10.5, 11.3, 12.8, 14.0, 15.5, 16.9]; line = "정답 이야기는\n본편에서!"
        meta = {"answer": [c["desc"] for c in plan["changes"]], "topic": f"슬라이드 {plan['slide']} 다른 곳 3개"}
    elif fmt == "C":
        plan = plan_C(ep); main, DUR, T_END, T_LOOP, bg = build_C(ep, plan); ev = audio_C(ep, plan, DUR)
        probes = [0, 1.9, 3.7, 4.3, 6.0, 7.5, 9.5, 10.4, 11.5, 13.0, 15.0, 15.95]; line = "정답 이야기는\n본편에서!"
        meta = {"answer": f"{plan['ans_banner']} ({plan['sound']} / {plan['sound_word']})", "topic": f"슬라이드 {plan['answer_slide']} 소리 {plan['sound']}"}
    else:
        plan = plan_D(ep); main, DUR, T_END, T_LOOP, bg, ham, T_SCN, SEGT = build_D(ep, plan); ev = audio_D(ep, plan, DUR, T_SCN, SEGT)
        faces = faces[:2] + [circle_src(ham.face())]; line = "본편에서\n만나요!"
        probes = [0, 1.5, 3.0, 4.8, 7.5, 10.5, 13.0, 14.2, 16.0, 16.95]
        meta = {"answer": plan["question"], "topic": "; ".join(s["caption"] for s in plan["scenes"])}
    fn = wrap(main, bg, faces, sub, DUR, T_END, T_LOOP, line)
    aud = ep.work / f"audio_{fmt}.wav"; mix_audio(ev, DUR, aud)
    out = ep.dir / "shorts_puzzle.mp4"
    lufs = render(fn, DUR, out, aud, ep.work, fmt, probes=[min(p, DUR - 0.04) for p in probes])
    qp = [q.strip() for q in plan.get("q_phrases", []) if q.strip()] or ["이게 뭘까요?"]
    titles = [f"{q} 🔍 {ep.title} #Shorts" for q in qp[:3]]
    res = {"format": fmt, "format_name": NAMES[fmt], "lang": lang, **meta, "story_title": ep.title, "title_candidates": titles,
           "description_first_line": (f"▶ 본편 보러 가기: {ep.main_url}" if ep.main_url else "▶ 본편 보러 가기: {MAIN_URL}"),
           "main_url": ep.main_url, "duration_sec": DUR, "lufs": lufs, "image_calls": plan.get("image_calls", ep.image_calls),
           "cost_usd": round(plan.get("image_calls", ep.image_calls) * IMG_COST, 3), "plan": {k: v for k, v in plan.items() if not k.startswith("_")},
           "frames_dir": str(ep.work / f"frames_{fmt}"), "elapsed_sec": round(time.time() - t0)}
    json.dump(res, open(ep.dir / "shorts_puzzle.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"완료 {fmt} {out} {lufs} LUFS {res['elapsed_sec']}s")
    return res


def circle_src(im): return im.convert("RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--format", default="auto"); ap.add_argument("--lang", default="ko")
    ap.add_argument("--idx", type=int, default=None, help="auto 순환의 시작 위치 강제(0=A)")
    a = ap.parse_args()
    if a.lang != "ko": sys.exit("현재 ko 만 지원")
    ep = Ep(a.dir if Path(a.dir).is_absolute() else PROJ / a.dir)
    if all(c in "ABCD" for c in a.format.upper().replace(",", "")): seq = [c for c in a.format.upper().replace(",", "")]
    else:
        if a.idx is not None: st = a.idx % 4
        else:
            lf = last_format(); st = (ORDER.index(lf) + 1) % 4 if lf in ORDER else 0
        seq = [ORDER[(st + i) % 4] for i in range(4)]
    for f in seq:
        try: run(ep, f, a.lang); return
        except Infeasible as e: log(f"{f} 불가: {e} -> 다음 포맷")
    sys.exit("모든 포맷 실패")


if __name__ == "__main__":
    main()
