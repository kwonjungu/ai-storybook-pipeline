#!/usr/bin/env python3
"""
11b_key_scene.py — 편당 핵심 장면 1컷을 '말하는 장면'으로 연출 (A안 v2, 2026-10-12)

거인나라 시범(Desktop/햄찌인트로/storybook_proto/kungkung)에서 사람이 손으로 하던 일을 자동화한 판.
움직임: 립싱크 + 말 강세 끄덕/들썩 + 듣는 캐릭터 갸웃·늦은 끄덕 + 깜빡임 + 숨쉬기 + 라인 보일
        + 느린 푸시인(1.00→1.06). 반짝이·낙엽·패닝 없음.

입 처리(v2, "입이 부자연스럽다" 피드백 반영):
  - 쉬는 입 = 원본 그림의 입 그대로 (편집 생성한 '다문 입'으로 바꾸지 않음)
  - 입 부품은 원본 표정에 가까운 2단계만: 원본이 다문 입이면 '조금 열림/중간 열림',
    원본이 벌린 입이면 '조금 더 다묾/조금 더 벌림'. 이빨 보이는 함박웃음 등 다른 표정은 검사로 탈락
  - 입 모양은 음소(Rhubarb)가 아니라 음성 크기 엔벨로프(부드럽게 한 값)로 고름,
    한 모양 최소 3프레임 유지, 모양 사이 2프레임 크로스페이드
  - 입 패치가 원본과 색·선·질감이 다르거나 경계가 튀면 사용하지 않음 → 그 캐릭터는 입 움직임 끔
  - 옆모습/뒷모습 캐릭터는 입 움직임 없이 끄덕·들썩·깜빡임만

입력: 11_animate_scenes.py 산출물 anim/_layers/sXX_bg.png + sXX_A_cut.png (+ sXX_poseA.png 있으면 사용)
출력: anim/key_slide_XX.mp4 (슬라이드 길이와 같은 프레임 수, 오디오 없음)
      anim/key_scene.json (자동 검출·매핑·검사 기록), anim/key_scene_check.png (확인 이미지)
      anim/_key_parts/ (편집 부품 캐시 — --reuse 로 재렌더 시 비용 0)
06_assemble_video.py 가 key_slide_XX.mp4 를 anim/slide_XX.mp4 보다 우선 사용한다.
실패하면 아무 파일도 남기지 않고 exit 0 (정지 그림/11번 애니로 진행).

사용법:
  python 11b_key_scene.py --dir output/폴더              # 장면 자동 선택
  python 11b_key_scene.py --dir output/폴더 --slide 12   # 슬라이드 지정
  python 11b_key_scene.py --dir output/폴더 --force --reuse   # 캐시 부품으로 다시 렌더(이미지 비용 0)
"""
import argparse, json, math, os, random, re, shutil, subprocess, sys, time, traceback, wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
# 좌표 검출은 2.5-flash 가 크게 틀린다(거인나라 실측: 생쥐 박스가 x로 250px 어긋남) → 3-flash 사용
VISION_MODEL = os.getenv("KEYSCENE_VISION_MODEL", "gemini-3-flash-preview")
IMG_COST = 0.039          # 실시간 이미지 1장
BUDGET = 0.40             # 편당 이미지 비용 상한
FPS, OW, OH = 30, 1920, 1080
FF_DEFAULT = r"C:\Users\권준구\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
POS_MAX_DIFF = 38         # 11번 포즈A 위치 검사 기준과 동일


def ffmpeg_bin():
    w = shutil.which("ffmpeg")
    return w if w else os.path.join(os.getenv("FFMPEG_BIN", FF_DEFAULT), "ffmpeg.exe")


def imread_kr(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_UNCHANGED)


def imwrite_kr(p, im):
    ok, buf = cv2.imencode(Path(p).suffix, im)
    if ok:
        buf.tofile(str(p))


def rgb_read(p):
    im = imread_kr(p)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2RGB)


# ───────────────────────── 장면 선택 ─────────────────────────
def slide_windows(timing):
    """06과 같은 규칙: 슬라이드 i 영상 = [이전 슬라이드 end, 이 슬라이드 end] (마지막은 total_duration)."""
    sl = timing["slides"]; out = {}
    for i, s in enumerate(sl):
        st = 0.0 if i == 0 else sl[i - 1].get("end", 0.0)
        en = timing.get("total_duration", s.get("end")) if i == len(sl) - 1 else s.get("end", st + 5.0)
        out[s.get("slide", i)] = (st, max(round(en - st, 3), 0.1))
    return out


def pos_ok(qa_rec):
    if not qa_rec:
        return False
    if qa_rec.get("result") == "ok":
        return True
    tries = qa_rec.get("tries") or []
    return bool(tries) and isinstance(tries[-1].get("A_pos_diff"), (int, float)) and tries[-1]["A_pos_diff"] <= POS_MAX_DIFF


def pick_candidates(ep, story, timing):
    lay = ep / "anim" / "_layers"
    qa = {}
    if (ep / "anim" / "anim_qa.json").exists():
        qa = json.load(open(ep / "anim" / "anim_qa.json", encoding="utf-8"))
    story_sl = [s for s in story.get("slides", []) if s.get("type") == "story"]
    nst = max(len(story_sl), 1)
    order = {s["slide_number"]: i for i, s in enumerate(story_sl)}
    cands = []
    for s in story_sl:
        n = s["slide_number"]
        if not ((lay / f"s{n:02d}_bg.png").exists() and (lay / f"s{n:02d}_A_cut.png").exists()):
            continue
        if not pos_ok(qa.get(str(n))):
            continue
        segs = [g for g in timing["segments"] if g["slide"] == n]
        dia = [g for g in segs if g.get("speaker") != "narrator"]
        if len(dia) < 2:
            continue
        late = order[n] >= nst * 2 / 3
        cands.append(((0 if late else 1, -len(dia), -len({g["speaker"] for g in dia}), -n), n))
    return [n for _, n in sorted(cands)]


# ───────────────────────── 역할(화자) 표 ─────────────────────────
def role_table(meta):
    chars = meta.get("characters") or {}
    roles, sup = {}, chars.get("supporting") or {}
    for k in ("main_1", "main_2", "main_3"):
        c = chars.get(k)
        if not c:
            continue
        g = c.get("gender")
        sp = "child_boy" if g == "boy" else "child_girl" if g == "girl" else k
        if sp in roles:
            sp = k
        roles[sp] = c
    for k, v in sup.items():
        if isinstance(v, dict):
            roles.setdefault(k, v)
    return roles, list(sup.keys())


def speaker_role(spk, roles, sup_keys):
    if spk in roles:
        return spk
    if spk in ("teacher", "adult_female", "adult_male", "elder", "adult") and len(sup_keys) == 1:
        return sup_keys[0]
    return None


# ───────────────────────── Gemini ─────────────────────────
class Gem:
    def __init__(self, cache_dir, reuse):
        from google import genai
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.cache, self.reuse = cache_dir, reuse
        self.img_calls, self.vis_calls = 0, 0

    @property
    def cost(self):
        return self.img_calls * IMG_COST

    def can_image(self):
        return self.cost + IMG_COST <= BUDGET + 1e-9

    def json(self, parts, prompt, tag=None):
        from google.genai import types
        cp = self.cache / f"{tag}.json" if tag else None
        if cp and self.reuse and cp.exists():
            return json.loads(cp.read_text(encoding="utf-8"))
        contents = [types.Part.from_bytes(data=b, mime_type="image/png") for b in parts] + [prompt]
        for a in range(3):
            try:
                r = self.client.models.generate_content(
                    model=VISION_MODEL, contents=contents,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
                self.vis_calls += 1
                t = r.text.strip()
                j = json.loads(t) if t[:1] in "[{" else json.loads(re.search(r"[\[{].*[\]}]", t, re.S).group(0))
                if cp:
                    cp.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
                return j
            except Exception as e:
                print(f"    [vision 재시도 {a + 1}] {str(e)[:100]}")
                time.sleep(3)
        return None

    def edit(self, base_png_bytes, prompt, out_path):
        from google.genai import types
        if self.reuse and out_path.exists():
            return True
        if not self.can_image():
            print("    [비용] 상한 도달 — 이미지 생성 생략")
            return False
        for a in range(2):
            try:
                self.img_calls += 1
                r = self.client.models.generate_content(
                    model=IMAGE_MODEL,
                    contents=[types.Part.from_bytes(data=base_png_bytes, mime_type="image/png"), prompt],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio="16:9", image_size="1K")))
                for c in r.candidates or []:
                    for p in c.content.parts:
                        if getattr(p, "inline_data", None):
                            out_path.write_bytes(bytes(p.inline_data.data))
                            return True
                print("    [편집] 이미지 없음")
            except Exception as e:
                print(f"    [편집 재시도 {a + 1}] {str(e)[:100]}")
                time.sleep(4)
            if not self.can_image():
                break
        return False


def png_bytes(rgb):
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


# ───────────────────────── 누끼 (11번 레이어 → 깨끗한 알파) ─────────────────────────
def build_layers(lay, n):
    """반환: base_green(RGB, 편집·검출 기준), F(전경색), A(0..1 알파).
    알파는 11번 A_cut 알파가 기본. poseA(초록 화면 원본)가 있으면 크로마로 '키 색과 거의 같은 곳'만 더 뚫는다
    (다리·더듬이 사이 틈, 시범 matte_k 방식). 초록 번짐 제거는 바깥 가장자리 띠에서만 — 안쪽 초록 옷·눈 흰자는 그대로
    (말놀이 s12 실측: 크로마를 전체에 쓰면 초록 조끼가 투명·회색이 되고 눈 둘레가 점점이 뚫림)."""
    cut = imread_kr(lay / f"s{n:02d}_A_cut.png")
    cut_rgb = cv2.cvtColor(cut[:, :, :3], cv2.COLOR_BGR2RGB)
    a_cut = cut[:, :, 3].astype(np.float32) / 255
    h, w = a_cut.shape
    pa = lay / f"s{n:02d}_poseA.png"
    f_cut = cut_rgb.astype(np.float32)
    g = (f_cut[..., 1] > f_cut[..., 0] * 1.3) & (f_cut[..., 1] > f_cut[..., 2] * 1.3) & (f_cut[..., 1] > 110) & (a_cut < 0.9) & (a_cut > 0.05)
    key = np.median(f_cut[g], 0) if g.sum() > 200 else np.array([0, 177, 64], np.float32)
    if pa.exists():
        base = rgb_read(pa)
        if base.shape[:2] != (h, w):
            base = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA)
    else:
        base = (f_cut * a_cut[..., None] + key * (1 - a_cut[..., None])).astype(np.uint8)
    f = base.astype(np.float32)
    a = a_cut.copy()
    if pa.exists():
        chars = cv2.dilate((a_cut > 0.05).astype(np.uint8), np.ones((9, 9), np.uint8))
        sm = cv2.resize(base, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
        mk = cv2.resize(chars, (w // 4, h // 4), interpolation=cv2.INTER_NEAREST)
        bgs = cv2.inpaint(sm, mk, 5, cv2.INPAINT_TELEA)
        bgk = cv2.resize(cv2.GaussianBlur(bgs, (0, 0), 3), (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
        d = np.linalg.norm(f - bgk, axis=2)
        ack = np.clip((d - 22) / (60 - 22), 0, 1)
        ack = cv2.morphologyEx(ack, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        keyish = (d < 34) & (f[..., 1] > f[..., 0] * 1.15) & (f[..., 1] > f[..., 2] * 1.15)
        keyish = cv2.dilate(keyish.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        a = np.where(keyish, np.minimum(a_cut, ack), a_cut)
        a = a * cv2.dilate((a_cut > 0.05).astype(np.uint8), np.ones((15, 15), np.uint8))
    else:
        bgk = np.broadcast_to(key, f.shape).astype(np.float32)
    # 바깥 가장자리 띠(알파가 0→1로 바뀌는 곳 근처)에서만 전경색 복원 + 초록 제거
    solid = cv2.erode((a > 0.98).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    band = cv2.dilate(((a > 0.02) & (a < 0.98)).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~solid
    aa = np.maximum(a, 0.05)[..., None]
    F = np.where(((a > 0) & (a < 0.98))[..., None], (f - (1 - a[..., None]) * bgk) / aa, f)
    F = np.clip(F, 0, 255)
    ex = np.clip(F[..., 1] - np.maximum(F[..., 0], F[..., 2]), 0, None)
    greenish = (F[..., 1] > F[..., 0] * 1.12) & (F[..., 1] > F[..., 2] * 1.12)
    F[..., 1] = np.where(band & greenish, F[..., 1] - ex * 0.85, F[..., 1])
    a = np.clip((a - 0.1) / 0.9, 0, 1)
    a8 = (a * 255).astype(np.uint8)
    a8 = cv2.GaussianBlur(cv2.erode(a8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))), (0, 0), 0.6)
    return base, np.clip(F, 0, 255).astype(np.uint8), a8.astype(np.float32) / 255


# ───────────────────────── 검출 ─────────────────────────
def box_px(b, w, h, pad=0.0):
    if not b or len(b) != 4:
        return None
    y0, x0, y1, x1 = [float(v) for v in b]
    if y1 <= y0 or x1 <= x0:
        return None
    x0, x1, y0, y1 = x0 / 1000 * w, x1 / 1000 * w, y0 / 1000 * h, y1 / 1000 * h
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    return [int(max(0, x0 - px)), int(max(0, y0 - py)), int(min(w, x1 + px)), int(min(h, y1 + py))]


def detect(gem, base, roles, slide_speakers, n):
    """1단계: 전체 그림에서 캐릭터별 몸·얼굴 박스와 상태. 2단계: 얼굴을 확대해 입·눈 박스(정밀)."""
    h, w = base.shape[:2]
    role_lines = "\n".join(f'- "{k}": {v.get("name", "")} — {str(v.get("appearance_en", ""))[:220]}' for k, v in roles.items())
    prompt = (
        "This is a storybook illustration with its characters on a plain green screen.\n"
        f"Known story characters (id: description):\n{role_lines}\n"
        f"Characters who speak in this scene: {', '.join(slide_speakers) or 'none'}.\n"
        "Detect EVERY distinct character (animal or person, not props). Output a JSON list; each entry:\n"
        '{"id": one of the ids above or "other", "label": short English description, '
        '"box_2d": [ymin, xmin, ymax, xmax] of the whole body, "face_2d": [ymin, xmin, ymax, xmax] of the head, '
        '"facing": "front"|"three_quarter"|"side"|"back", '
        '"eyes_open": true/false (false if the eyes are drawn closed, e.g. happy arcs), '
        '"mouth_drawn": true/false, "mouth_open": true/false, "teeth_visible": true/false}. '
        "Box coordinates normalized to 0-1000. Each id at most once.")
    j = gem.json([png_bytes(base)], prompt, tag=f"s{n:02d}_detect")
    if isinstance(j, dict):
        j = j.get("characters") or j.get("items") or [j]
    out, used = [], set()
    for k, it in enumerate(j or []):
        bb = box_px(it.get("box_2d"), w, h)
        fb = box_px(it.get("face_2d") or it.get("face_box"), w, h)
        if not bb or not fb:
            continue
        cid = it.get("id") if it.get("id") in roles else "other"
        if cid != "other" and cid in used:
            cid = "other"
        used.add(cid)
        c = dict(id=cid, label=str(it.get("label", ""))[:60], bbox=bb, face=fb, mouth=None, eyes=[],
                 facing=it.get("facing", "front"), eyes_open=bool(it.get("eyes_open")),
                 mouth_open=bool(it.get("mouth_open")), teeth=bool(it.get("teeth_visible")))
        # 2단계: 얼굴 확대 → 입·눈
        x0, y0, x1, y1 = expand(fb, 1.25, w, h)
        crop = base[y0:y1, x0:x1]
        s = 512 / max(crop.shape[:2])
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)), interpolation=cv2.INTER_CUBIC)
        q = ("This is a close-up of a picture-book character's head. Output JSON: "
             '{"mouth_2d": [ymin, xmin, ymax, xmax] tight box around the drawn mouth (lips/mouth line only, not the '
             'muzzle or nose) or null if no mouth is drawn, "eyes_2d": [[ymin, xmin, ymax, xmax], ...] tight box of '
             'each visible eye}. Coordinates normalized to 0-1000 of this close-up.')
        fj = gem.json([png_bytes(crop)], q, tag=f"s{n:02d}_face{k}") or {}
        cw, ch = x1 - x0, y1 - y0
        def sub(b):
            bp = box_px(b, cw, ch)
            return [bp[0] + x0, bp[1] + y0, bp[2] + x0, bp[3] + y0] if bp else None
        if it.get("mouth_drawn", True) is not False:
            c["mouth"] = sub(fj.get("mouth_2d"))
        c["eyes"] = [e for e in (sub(e) for e in (fj.get("eyes_2d") or [])) if e]
        out.append(c)
    return out


def label_sprites(A, chars, F=None):
    """알파 픽셀을 캐릭터별로 나누고, 이어진 변위장을 만들 가중치(블러)를 반환."""
    h, w = A.shape
    m = A > 0.08
    lab = np.full((h, w), -1, np.int16)
    areas = [(c["bbox"][2] - c["bbox"][0]) * (c["bbox"][3] - c["bbox"][1]) for c in chars]
    order = sorted(range(len(chars)), key=lambda i: -areas[i])     # 큰 것 먼저 칠하고 작은 것이 덮음(작은 캐릭터가 앞)
    inbox = []
    for i in order:
        x0, y0, x1, y1 = chars[i]["bbox"]
        sub = np.zeros((h, w), bool); sub[y0:y1, x0:x1] = True
        lab[sub & m] = i
        inbox.append((i, sub))
    # 박스가 겹치는 곳(예: 곰 팔이 무당벌레 위)은 각자 '혼자만 있는 영역'의 색 분포로 판정
    cnt = np.sum([s for _, s in inbox], 0) if inbox else np.zeros((h, w))
    contested = m & (cnt >= 2)
    if contested.any() and F is not None:
        q = (F // 16).astype(np.int32)
        code = q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]
        cand = np.zeros((len(chars), h, w), np.float32)
        for i, sub in inbox:
            ex = m & sub & (cnt == 1)
            if ex.sum() < 200:
                cand[i] = np.where(sub, 1e-6, 0); continue
            hist = np.bincount(code[ex], minlength=4096).astype(np.float32)
            hist = cv2.GaussianBlur(hist.reshape(16, 256), (0, 0), 0.8).reshape(-1)
            hist = hist / hist.sum() + 1e-6
            cand[i] = np.where(sub, hist[code], 0)
        for i in range(len(chars)):                            # 이웃 다수결로 매끈하게
            cand[i] = cv2.GaussianBlur(cand[i] / (cand.max(0) + 1e-9), (0, 0), 2.0) * (cand[i] > 0)
        best = np.argmax(cand, 0)
        lab[contested] = best[contested]
    rest = m & (lab < 0)
    if rest.any():
        ys, xs = np.where(rest)
        dists = []
        for c in chars:
            x0, y0, x1, y1 = c["bbox"]
            dx = np.maximum(np.maximum(x0 - xs, 0), xs - x1); dy = np.maximum(np.maximum(y0 - ys, 0), ys - y1)
            dists.append(dx * dx + dy * dy)
        lab[ys, xs] = np.argmin(np.stack(dists), 0)
    weights = []
    for i in range(len(chars)):
        weights.append(cv2.GaussianBlur((lab == i).astype(np.float32), (0, 0), 7))
    tot = np.sum(weights, 0)
    norm = np.maximum(tot, 1.0)
    weights = [wt / norm for wt in weights]                        # 캐릭터 근처 합=1, 먼 곳은 0(정지)
    for i, c in enumerate(chars):
        ys, xs = np.where(lab == i)
        if len(ys) < 50:
            c["feet"] = ((c["bbox"][0] + c["bbox"][2]) / 2, c["bbox"][3]); c["h"] = c["bbox"][3] - c["bbox"][1]
            c["sbox"] = c["bbox"]; continue
        yb = np.percentile(ys, 99)
        c["feet"] = (float(np.median(xs[ys >= yb - 6])), float(yb))
        c["h"] = float(yb - np.percentile(ys, 1))
        c["sbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return lab, weights


# ───────────────────────── 부품(입·눈) ─────────────────────────
def align_part(base, part, box):
    x0, y0, x1, y1 = box
    a = cv2.cvtColor(base[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    b = cv2.cvtColor(part[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    if a.shape[0] < 16 or a.shape[1] < 16:
        return part, (0.0, 0.0), 0.0
    (dx, dy), resp = cv2.phaseCorrelate(a, b, cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F))
    out = cv2.warpAffine(part, np.float32([[1, 0, -dx], [0, 1, -dy]]), (part.shape[1], part.shape[0]),
                         borderMode=cv2.BORDER_REPLICATE)
    return out, (round(float(dx), 2), round(float(dy), 2)), float(resp)


def expand(b, k, w, h, minpad=0):
    x0, y0, x1, y1 = b
    cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 * k + minpad, (y1 - y0) / 2 * k + minpad
    return [int(max(0, cx - hw)), int(max(0, cy - hh)), int(min(w, cx + hw)), int(min(h, cy + hh))]


def lum(x):
    x = x.astype(np.float32)
    return 0.3 * x[..., 0] + 0.59 * x[..., 1] + 0.11 * x[..., 2]


def make_patch(base, part, A, c, kind):
    """편집 이미지에서 입(또는 눈) 영역만 떼어 원본에 맞춘 패치. 반환 (patch dict | None, 검사 기록)."""
    h, w = A.shape
    rec = {}
    part, sh, resp = align_part(base, part, expand(c["face"], 1.6, w, h))
    rec["shift"], rec["resp"] = sh, round(resp, 3)
    if max(abs(sh[0]), abs(sh[1])) > 0.04 * w:
        rec["fail"] = "정렬 실패(크게 어긋남)"; return None, rec
    regions = [c["mouth"]] if kind == "mouth" else c["eyes"]
    win = np.zeros((h, w), bool)
    for r in regions:
        x0, y0, x1, y1 = expand(r, 2.0 if kind == "mouth" else 1.8, w, h, 6)
        win[y0:y1, x0:x1] = True
    fx0, fy0, fx1, fy1 = expand(c["face"], 1.1, w, h)
    fwin = np.zeros((h, w), bool); fwin[fy0:fy1, fx0:fx1] = True
    win &= fwin
    diff = cv2.GaussianBlur(np.abs(part.astype(np.float32) - base.astype(np.float32)).max(2), (0, 0), 1.0)
    core = ((diff > 32) & win).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    nlab, cl, st, _ = cv2.connectedComponentsWithStats(core)
    keep = np.zeros((h, w), np.uint8)
    for r in regions:
        x0, y0, x1, y1 = expand(r, 1.4, w, h, 3)
        for i in range(1, nlab):
            if st[i][4] >= 12:
                ys, xs = np.where(cl[y0:y1, x0:x1] == i)
                if len(ys):
                    keep[cl == i] = 1
    face_area = (fx1 - fx0) * (fy1 - fy0)
    reg_area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in regions)
    rec["diff_area"] = int(keep.sum())
    if keep.sum() < 8:
        rec["fail"] = "변화 없음"; return None, rec
    # 영역 마스크: 바뀐 곳의 볼록 껍질 + 여유, 검출 박스 기준 크기 제한
    mask = np.zeros((h, w), np.uint8)
    cnts, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for r in regions:
        rx0, ry0, rx1, ry1 = expand(r, 1.4, w, h, 3)
        pts = np.vstack([cn.reshape(-1, 2) for cn in cnts])
        pts = pts[(pts[:, 0] >= rx0 - 4) & (pts[:, 0] <= rx1 + 4) & (pts[:, 1] >= ry0 - 4) & (pts[:, 1] <= ry1 + 4)]
        if len(pts) >= 3:
            cv2.fillConvexPoly(mask, cv2.convexHull(pts), 1)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    if kind == "mouth":
        for e in c["eyes"]:                                   # 입 패치가 눈을 건드리지 않게
            ex0, ey0, ex1, ey1 = expand(e, 1.3, w, h, 2)
            mask[ey0:ey1, ex0:ex1] = 0
    elif c["mouth"]:                                          # 눈 패치가 입을 건드리지 않게(말놀이 기린 실측)
        mx0, my0, mx1, my1 = expand(c["mouth"], 1.3, w, h, 2)
        mask[my0:my1, mx0:mx1] = 0
    mask &= (A > 0.6).astype(np.uint8)
    marea = int(mask.sum())
    rec["mask_area"], rec["region_area"] = marea, int(reg_area)
    lim = 4.0 if kind == "mouth" else 3.0
    if marea > lim * max(reg_area, 40) or marea > 0.35 * face_area:
        rec["fail"] = f"바뀐 영역이 너무 큼({marea}px, 기준 {int(lim * reg_area)})"; return None, rec
    m = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.8)
    # 색 맞춤(경계 고리 평균차)
    ring = (m > 0.03) & (m < 0.5)
    if ring.sum() >= 20:
        off = base[ring].astype(np.float32).mean(0) - part[ring].astype(np.float32).mean(0)
        part = np.clip(part.astype(np.float32) + off, 0, 255)
    part = part.astype(np.float32)
    # 경계 검사: 마스크 바로 바깥 고리에서 편집본이 원본과 많이 다르면 경계가 선을 자른다
    outer = cv2.dilate((m > 0.5).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~(m > 0.5) & (A > 0.6)
    seam = float(np.abs(part[outer] - base[outer].astype(np.float32)).mean()) if outer.sum() > 10 else 0.0
    rec["seam"] = round(seam, 1)
    inside = m > 0.5
    pl, bl = lum(part)[inside], lum(base)[inside]
    rec["dark_p5"] = [round(float(np.percentile(bl, 5)), 1), round(float(np.percentile(pl, 5)), 1)]
    ys, xs = np.where(inside)
    by0, by1, bx0, bx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    lb = cv2.Laplacian(lum(base)[by0:by1, bx0:bx1], cv2.CV_32F).var()
    lp = cv2.Laplacian(lum(part)[by0:by1, bx0:bx1], cv2.CV_32F).var()
    rec["sharp_ratio"] = round(float(lp / max(lb, 1e-3)), 2)
    pw = part[inside]; bw = base[inside].astype(np.float32)
    white_p = ((pw.min(1) > 210) & (pw.max(1) - pw.min(1) < 35)).mean()
    white_b = ((bw.min(1) > 210) & (bw.max(1) - bw.min(1) < 35)).mean()
    rec["white_gain"] = round(float(white_p - white_b), 3)
    gp = float((pw[:, 1] - (pw[:, 0] + pw[:, 2]) / 2).mean()); gb = float((bw[:, 1] - (bw[:, 0] + bw[:, 2]) / 2).mean())
    rec["green_cast"] = round(gp - gb, 1)
    if rec["green_cast"] > 5:                                  # 편집본이 초록 화면 색을 머금은 경우(말놀이 기린 눈 실측)
        rec["fail"] = f"초록 기운({rec['green_cast']})"; return None, rec
    if seam > 16:
        rec["fail"] = f"경계 튐(seam {seam:.1f})"; return None, rec
    if abs(rec["dark_p5"][1] - rec["dark_p5"][0]) > 45:
        rec["fail"] = "선 색/굵기 다름"; return None, rec
    if not (0.3 <= rec["sharp_ratio"] <= 3.2):
        rec["fail"] = "질감(선명도) 다름"; return None, rec
    if kind == "mouth" and not c["teeth"] and rec["white_gain"] > 0.06:
        rec["fail"] = "이빨 보임"; return None, rec
    y0, y1 = max(by0 - 6, 0), min(by1 + 6, h); x0, x1 = max(bx0 - 6, 0), min(bx1 + 6, w)
    return dict(box=(y0, y1, x0, x1), m=m[y0:y1, x0:x1, None].copy(), rgb=part[y0:y1, x0:x1].copy()), rec


def apply_patch(img, p, k=1.0):
    y0, y1, x0, x1 = p["box"]
    sub = img[y0:y1, x0:x1].astype(np.float32)
    mk = p["m"] * k
    img[y0:y1, x0:x1] = np.clip(sub * (1 - mk) + p["rgb"] * mk, 0, 255).astype(np.uint8)


def face_crop(img, c, size=320):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = expand(c["face"], 1.3, w, h)
    cr = img[y0:y1, x0:x1]
    s = size / max(cr.shape[:2])
    return cv2.resize(cr, (max(int(cr.shape[1] * s), 1), max(int(cr.shape[0] * s), 1)), interpolation=cv2.INTER_CUBIC)


def vision_verify(gem, base, cand, c, kind, expect, tag):
    q = ("Image 1 is a character's face from a picture book. Image 2 is the same face after a small edit"
         + (" to its mouth." if kind == "mouth" else " to its eyes.") +
         ' Answer ONLY JSON: {"same_character": true/false, "same_art_style": true/false (same line color, line '
         'thickness, colors and texture), "looks_natural": true/false (no smudge, seam, doubled line or broken '
         'outline), "teeth_visible_in_2": true/false, "eyes_closed_in_2": true/false, '
         '"mouth_change": "smaller"|"same"|"slightly_bigger"|"much_bigger", "other_parts_changed": true/false}')
    j = gem.json([png_bytes(face_crop(base, c)), png_bytes(face_crop(cand, c))], q, tag=tag)
    if not j:
        return False, {"error": "판정 실패"}
    ok = bool(j.get("same_character")) and bool(j.get("same_art_style")) and bool(j.get("looks_natural"))
    ok = ok and not j.get("other_parts_changed")
    if kind == "mouth":
        ok = ok and (c["teeth"] or not j.get("teeth_visible_in_2")) and j.get("mouth_change") in expect
    else:
        ok = ok and bool(j.get("eyes_closed_in_2"))
    return ok, j


KEEP = ("Keep EVERYTHING else exactly identical: every character's identity, outline, size, position, pose, colors, "
        "eyes, blush and accessories, the same plain green background and the same picture-book art style and line "
        "thickness. Do not move, resize or redraw anything else. No teeth, no tongue, no new expression.")


def where(c, w):
    cx = (c["bbox"][0] + c["bbox"][2]) / 2 / w
    return "on the left" if cx < 0.38 else "on the right" if cx > 0.62 else "in the middle"


def mouth_jobs(chars, w):
    """원본 입 상태에 따라 2단계: 다문 입이면 조금/중간 열림, 벌린 입이면 조금 더 다묾/조금 더 벌림."""
    jobs = {"m1": [], "m2": []}
    for c in chars:
        who = f"the {c['label']} {where(c, w)}"
        if c["mouth_open"]:
            jobs["m1"].append((c, f"make the mouth of {who} a little less open (a smaller opening, the same happy shape)",
                               ("smaller",)))
            jobs["m2"].append((c, f"open the mouth of {who} just a little wider than it is now (same shape, same lines)",
                               ("slightly_bigger",)))
        else:
            jobs["m1"].append((c, f"open the mouth of {who} only slightly, a small gap as if softly starting a word "
                                  f"(keep the same mouth line style and the same gentle expression)", ("slightly_bigger",)))
            jobs["m2"].append((c, f"open the mouth of {who} to a medium, relaxed talking shape (small oval, not wide, "
                                  f"same line style and expression)", ("slightly_bigger", "much_bigger")))
    return jobs


def mouth_extent(base, A, c):
    """그려진 입(어두운 선·입 안)의 실제 위·아래·좌·우. 검출 박스는 넉넉해서 그대로 쓰면 주둥이 윤곽까지 휜다."""
    h, w = A.shape
    mx0, my0, mx1, my1 = c["mouth"]
    x0, _, x1, _ = expand(c["mouth"], 1.25, w, h, 2)
    y0, y1 = my0, int(min(my1 + 0.3 * (my1 - my0) + 2, h))  # 위로는 넓히지 않음(코·인중 선 제외)
    L = lum(base[y0:y1, x0:x1])
    skin = np.percentile(L, 80)                               # 입 주변 피부(주둥이) 밝기
    dark = (L < skin - 40) & (A[y0:y1, x0:x1] > 0.6)
    n, cl, st, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8))
    if n <= 1:
        return c["mouth"]
    i = 1 + int(np.argmax(st[1:, 4]))                       # 가장 큰 덩어리 = 입
    ys, xs = np.where(cl == i)
    if len(ys) < 20:
        return c["mouth"]
    return [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max() + 1), int(y0 + ys.max() + 1)]


def warp_mouth_patch(base, A, c, sc):
    """원본 입을 세로로 sc배. 늘릴 때는 윗입술 기준(턱 내림), 줄일 때는 아래쪽 65% 지점 기준
    (입 바로 밑 주둥이 윤곽이 끌려 올라가지 않게 윗입술이 더 많이 내려온다). 바깥으로 갈수록 변위 0 → 경계 없음."""
    h, w = A.shape
    x0, y0, x1, y1 = mouth_extent(base, A, c)
    mw, mh = max(x1 - x0, 4), max(y1 - y0, 4)
    yc = y0 + (0.1 if sc > 1 else 0.65) * mh
    k = 1 - 1 / sc
    d_top, d_bot = (y0 - yc) * k, (y1 - yc) * k
    f_up, f_dn = max(abs(d_top) * 1.7, 0.25 * mh, 2.0), max(abs(d_bot) * 1.7, 2.0)
    bx0, by0, bx1, by1 = (int(max(x0 - 0.4 * mw, 0)), int(max(y0 - f_up - 2, 0)),
                          int(min(x1 + 0.4 * mw, w)), int(min(y1 + f_dn + 2, h)))
    gx, gy = np.meshgrid(np.arange(bx0, bx1, dtype=np.float32), np.arange(by0, by1, dtype=np.float32))
    cx = (x0 + x1) / 2
    ux = np.clip(1 - (np.abs(gx - cx) - mw / 2) / (0.4 * mw), 0, 1)
    ux = ux * ux * (3 - 2 * ux)
    def ease(v):
        v = np.clip(v, 0, 1); return v * v * (3 - 2 * v)
    d = np.where(gy < y0, d_top * ease(1 - (y0 - gy) / f_up),
                 np.where(gy > y1, d_bot * ease(1 - (gy - y1) / f_dn), (gy - yc) * k)) * ux
    src_y = (gy - d).astype(np.float32)
    rgb = cv2.remap(np.ascontiguousarray(base.astype(np.float32)), gx, src_y, cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE)
    m = np.clip(np.abs(d) * 4, 0, 1)[..., None] * (A[by0:by1, bx0:bx1, None] > 0.5)
    return dict(box=(by0, by1, bx0, bx1), m=m.astype(np.float32), rgb=np.clip(rgb, 0, 255))


def build_parts(gem, base, A, talkers, blinkers, n, parts_dir, log):
    """반환: {char_index: {"levels": [patch|None(=원본)...], "rest": idx}}, {char_index: blink_patch}"""
    h, w = A.shape
    bb = png_bytes(base)
    levels = {}
    # 원본이 벌린 입: 원본 입을 '턱 내림' 변형으로 조금/중간 더 벌림(같은 그림이라 색·선 그대로, 이미지 생성 없음).
    #   줄이는 변형은 입 바로 밑 주둥이 윤곽·코가 끌려와서(거인나라 곰 실측) 쓰지 않는다 → 쉬는 입 = 원본(가장 작은 단계)
    for ci, c in [t for t in talkers if t[1]["mouth_open"]]:
        lv = [None]
        for name, sc, expect in (("open1", 1.12, ("slightly_bigger", "same")), ("open2", 1.25, ("slightly_bigger", "much_bigger"))):
            p = warp_mouth_patch(base, A, c, sc)
            cand = base.copy(); apply_patch(cand, p)
            ok, vj = vision_verify(gem, base, cand, c, "mouth", expect, f"s{n:02d}_{name}_c{ci}_verify")
            log.setdefault(str(ci), {})[name] = {"warp_scale": sc, "vision": vj, **({} if ok else {"fail": "비전 검사 불합격"})}
            print(f"    c{ci} {c['id']} {name}(원본 입 변형 x{sc}): {'OK' if ok else 'FAIL'}")
            if ok:
                lv.append(p)
        if len(lv) >= 2:
            levels[ci] = {"levels": lv, "rest": 0, "orig_open": False}
    gen_talkers = [t for t in talkers if not t[1]["mouth_open"]]
    jobs = mouth_jobs([c for _, c in gen_talkers], w)
    got = {}                                                  # (ci, job) -> patch
    for job in ("m1", "m2"):
        pend = list(zip([ci for ci, _ in gen_talkers], jobs[job]))
        for attempt in range(2):
            if not pend:
                break
            prompt = "Edit this exact picture: " + "; ".join(t[1] for _, t in pend) + ". Change ONLY those mouths. " + KEEP
            fp = parts_dir / f"s{n:02d}_{job}_{attempt}.png"
            if not gem.edit(bb, prompt, fp):
                break
            part = cv2.resize(rgb_read(fp), (w, h), interpolation=cv2.INTER_LANCZOS4)
            nxt = []
            for ci, (c, _, expect) in pend:
                p, rec = make_patch(base, part, A, c, "mouth")
                if p:
                    cand = base.copy(); apply_patch(cand, p)
                    ok, vj = vision_verify(gem, base, cand, c, "mouth", expect, f"s{n:02d}_{job}_{attempt}_c{ci}_verify")
                    rec["vision"] = vj
                    if not ok:
                        rec["fail"] = "비전 검사 불합격"; p = None
                log.setdefault(str(ci), {})[f"{job}_try{attempt}"] = rec
                print(f"    c{ci} {c['id']} {job} try{attempt}: {'OK' if p else 'FAIL ' + rec.get('fail', '')}")
                if p:
                    got[(ci, job)] = p
                else:
                    nxt.append((ci, (c, _, expect)))
            pend = nxt
    for ci, c in gen_talkers:
        p1, p2 = got.get((ci, "m1")), got.get((ci, "m2"))
        lv = [None] + ([p1] if p1 else []) + ([p2] if p2 else [])
        if len(lv) >= 2:
            levels[ci] = {"levels": lv, "rest": 0, "orig_open": False}
    blinks = {}
    pend = list(blinkers)
    for attempt in range(2):
        if not pend:
            break
        whos = ", ".join(f"the {c['label']} {where(c, w)}" for _, c in pend)
        prompt = (f"Edit this exact picture: close ONLY the eyes of {whos} as gentle curved closed-eye lines (a blink), "
                  "same line color and thickness. Mouths unchanged. " + KEEP)
        fp = parts_dir / f"s{n:02d}_eyes_{attempt}.png"
        if not gem.edit(bb, prompt, fp):
            break
        part = cv2.resize(rgb_read(fp), (w, h), interpolation=cv2.INTER_LANCZOS4)
        nxt = []
        for ci, c in pend:
            p, rec = make_patch(base, part, A, c, "eyes")
            if p:
                cand = base.copy(); apply_patch(cand, p)
                ok, vj = vision_verify(gem, base, cand, c, "eyes", None, f"s{n:02d}_eyes_{attempt}_c{ci}_verify")
                rec["vision"] = vj
                if not ok:
                    rec["fail"] = "비전 검사 불합격"; p = None
            log.setdefault(str(ci), {})[f"eyes_try{attempt}"] = rec
            print(f"    c{ci} {c['id']} eyes try{attempt}: {'OK' if p else 'FAIL ' + rec.get('fail', '')}")
            if p:
                blinks[ci] = p
            else:
                nxt.append((ci, c))
        pend = nxt
    return levels, blinks


# ───────────────────────── 오디오 → 입 크기·강세 ─────────────────────────
def seg_envelope(wav_path):
    w = wave.open(str(wav_path))
    sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, np.int16 if sw == 2 else np.int32).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(1)
    a /= (32768.0 if sw == 2 else 2 ** 31)
    hop = sr // 100
    env = np.sqrt(np.convolve(a ** 2, np.ones(hop * 3) / (hop * 3), "same")[::hop])
    sm = np.convolve(env, np.ones(7) / 7, "same")             # 70ms 부드럽게
    ref = np.percentile(sm[sm > sm.max() * 0.1], 90) if (sm > sm.max() * 0.1).sum() > 5 else sm.max()
    sm = np.clip(sm / (ref + 1e-6), 0, 1.2)
    envn = env / (env.max() + 1e-6)
    slow = np.convolve(envn, np.ones(40) / 40, "same"); pk, last = [], -1
    for i in range(2, len(envn) - 2):
        if envn[i] == envn[i - 2:i + 3].max() and envn[i] > 0.55 and envn[i] - slow[i] > 0.18 and i - last > 55:
            pk.append(i / 100); last = i
    return sm, pk


def mouth_track(segs, ci, lv, nfr):
    """프레임별 (상태A, 상태B, 섞음비율). 최소 3프레임 유지 + 2프레임 크로스페이드."""
    K, rest, oo = len(lv["levels"]), lv["rest"], lv["orig_open"]
    want = np.full(nfr, rest, np.int16)
    for s in segs:
        if s.get("char") != ci:
            continue
        for fi in range(max(int(s["t"] * FPS), 0), min(int(math.ceil((s["t"] + s["duration"]) * FPS)), nfr)):
            k = int(round((fi / FPS - s["t"] + 0.033) * 100))
            e = float(s["env"][k]) if 0 <= k < len(s["env"]) else 0.0
            if not oo:      # [원본(다묾), 조금, 중간]
                th = (0.18, 0.55) if K == 3 else (0.22,)
            else:           # [조금 다묾?, 원본, 조금 더?]
                th = (0.15, 0.62) if K == 3 else ((0.25,) if rest == 1 else (0.6,))
            want[fi] = sum(e > t for t in th)
    out, cur, prev, since = [], rest, rest, 99
    for fi in range(nfr):
        if want[fi] != cur and since >= 3:
            prev, cur, since = cur, int(want[fi]), 0
        since += 1
        k = 0.5 if since == 1 else 1.0
        out.append((prev, cur, k))
    return out


# ───────────────────────── 렌더 ─────────────────────────
def T(x, y): return np.array([[1, 0, x], [0, 1, y], [0, 0, 1.]])
def Sc(sx, sy=None): return np.diag([sx, sx if sy is None else sy, 1.])
def R(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
def smooth(u):
    u = min(max(u, 0), 1); return u * u * (3 - 2 * u)
def pulse(t, centers, width=0.09, lag=0.06):
    return sum(math.exp(-((t - p - lag) / width) ** 2) for p in centers)


def blink_times(seed, dur):
    rnd, t, out = random.Random(seed * 17 + 3), 0.8, []
    while t < dur:
        t += rnd.uniform(2.2, 5.0); out.append(t)
        if rnd.random() < 0.15:
            out.append(t + 0.35)
    return out


def render(out_mp4, bg, F, A, chars, weights, segs, levels, blinks, dur, keyframes_dir=None):
    h, w = A.shape
    nfr = int(math.ceil(dur * FPS - 1e-6))
    S = OW / w
    OYc = -(h * S - OH) / 2
    # 캐릭터가 있는 영역만 매 프레임 계산(바깥은 정지 배경)
    ys_, xs_ = np.where((A > 0.01) | (np.sum(weights, 0) > 0.001))
    ry0, ry1 = max(int(ys_.min()) - 24, 0), min(int(ys_.max()) + 24, h)
    rx0, rx1 = max(int(xs_.min()) - 24, 0), min(int(xs_.max()) + 24, w)
    gx, gy = np.meshgrid(np.arange(rx0, rx1, dtype=np.float32), np.arange(ry0, ry1, dtype=np.float32))
    wts = [np.ascontiguousarray(wt[ry0:ry1, rx0:rx1]) for wt in weights]
    bgf = bg.astype(np.float32)
    # 그림자(배경 재생성본에는 발밑 그림자가 없다)
    shadow = np.zeros((h, w), np.float32)
    for c in chars:
        fx, fy = c["feet"]; ww = (c["sbox"][2] - c["sbox"][0]) * 0.45
        cv2.ellipse(shadow, (int(fx), int(fy - 2)), (max(int(ww), 4), max(int(ww * 0.12), 3)), 0, 0, 360, 1.0, -1)
    shadow = cv2.GaussianBlur(shadow, (0, 0), 6) * 0.27
    bgf = bgf * (1 - shadow[..., None]) + np.array([30, 40, 60], np.float32) * shadow[..., None]
    talkers = [s.get("char") for s in segs if s.get("char") is not None]
    focus = [((c["face"][0] + c["face"][2]) / 2, (c["face"][1] + c["face"][3]) / 2) for i, c in enumerate(chars) if i in talkers]
    if focus:
        fx = (np.mean([f[0] for f in focus]) * 0.6 + w / 2 * 0.4) * S
        fy = (np.mean([f[1] for f in focus]) * 0.6 + h / 2 * 0.4) * S + OYc
    else:
        fx, fy = OW * 0.5, OH * 0.55
    tracks = {ci: mouth_track(segs, ci, lv, nfr) for ci, lv in levels.items()}
    for i, c in enumerate(chars):
        rnd = random.Random(i + 1)
        c["boil"] = [(rnd.uniform(-0.85, 0.85), rnd.uniform(-0.85, 0.85), rnd.uniform(-0.3, 0.3)) for _ in range(400)]
        c["blinks"] = blink_times(i + 1, dur)
        c["peaks"] = [s["t"] + p for s in segs if s.get("char") == i for p in s["peaks"]]
        c["amp"] = 0.6 if c["h"] > 0.45 * h else 1.0
    ff = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
                           "-r", str(FPS), "-i", "-", "-frames:v", str(nfr), "-c:v", "libx264", "-preset", "medium",
                           "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_mp4)], stdin=subprocess.PIPE)
    keyset = set(np.linspace(0, nfr - 1, 8).astype(int).tolist())
    pre_base = F.astype(np.float32) * A[..., None]
    bg8 = np.clip(bgf, 0, 255).astype(np.uint8)
    try:
        for fi in range(nfr):
            t = fi / FPS; tc = math.floor(t * 12) / 12
            seg = next((s for s in segs if s["t"] <= tc <= s["t"] + s["duration"]), None)
            spk = seg.get("char") if seg else None
            img = F.copy()
            dirty = any(tracks[ci][fi][1] != levels[ci]["rest"] or tracks[ci][fi][2] < 1 for ci in tracks) or                 any(any(-1e-6 <= t - b < 0.14 for b in chars[ci]["blinks"]) for ci in blinks)
            for ci, tr in tracks.items():
                a_, b_, k = tr[fi]
                lv = levels[ci]["levels"]
                if a_ != b_ and k < 1:
                    pa, pb = lv[a_], lv[b_]
                    boxes = [p["box"] for p in (pa, pb) if p is not None]
                    y0, y1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
                    x0, x1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
                    ia = img.copy()
                    if pa is not None: apply_patch(ia, pa)
                    if pb is not None: apply_patch(img, pb)
                    img[y0:y1, x0:x1] = (ia[y0:y1, x0:x1].astype(np.float32) * (1 - k)
                                         + img[y0:y1, x0:x1].astype(np.float32) * k).astype(np.uint8)
                elif lv[b_] is not None:
                    apply_patch(img, lv[b_])
            for ci, p in blinks.items():
                bt = [tc2 for tc2 in chars[ci]["blinks"] if -1e-6 <= t - tc2 < 0.2]
                if bt:
                    d = t - bt[0]
                    if d < 0.14:                               # 반투명 섞음 없이 4프레임 딱 감기(겹쳐 보임 방지)
                        apply_patch(img, p)
            mx = np.zeros_like(gx); my = np.zeros_like(gy); wsum = np.zeros_like(gx)
            for i, c in enumerate(chars):
                bx, by, br = c["boil"][int(t * 6 + i * 31) % 400]
                breathe = 1 + 0.010 * math.sin(2 * math.pi * 0.45 * tc + (i + 1) * 1.7)
                dy, rot, sq, amp = 0.0, 0.0, 1.0, c["amp"]
                nod = pulse(tc, c["peaks"]) if c["peaks"] else 0
                dy += 4.2 * amp * nod; sq *= 1 - 0.018 * nod; rot += 1.6 * amp * nod * [1, -1][int(tc * 1.3) % 2]
                if spk is not None and spk != i:
                    sc = chars[spk]
                    k = smooth((tc - seg["t"]) / 0.5) * smooth((seg["t"] + seg["duration"] - tc) / 0.4)
                    toward = 1 if c["feet"][0] < sc["feet"][0] else -1
                    rot += (1.8 if c["amp"] < 1 else 2.4) * toward * k
                    n2 = pulse(tc, seg["peaks"][::2], 0.12, 0.25) if seg["peaks"] else 0
                    sq *= 1 - 0.010 * n2; dy += 2.5 * amp * n2
                X, Y = c["feet"]
                M = T(X + bx, Y + by + dy) @ R(br + rot) @ Sc(1 / math.sqrt(breathe * sq), breathe * sq) @ T(-X, -Y)
                inv = np.linalg.inv(M)
                wt = wts[i]
                mx += wt * (inv[0, 0] * gx + inv[0, 1] * gy + inv[0, 2])
                my += wt * (inv[1, 0] * gx + inv[1, 1] * gy + inv[1, 2])
                wsum += wt
            mx += (1 - wsum) * gx; my += (1 - wsum) * gy
            wa = cv2.remap(A, mx, my, cv2.INTER_LINEAR, borderValue=0)
            wp = cv2.remap(pre_base if not dirty else img.astype(np.float32) * A[..., None], mx, my, cv2.INTER_LINEAR,
                           borderValue=0)
            comp = bg8.copy()
            comp[ry0:ry1, rx0:rx1] = np.clip(bgf[ry0:ry1, rx0:rx1] * (1 - wa[..., None]) + wp, 0, 255).astype(np.uint8)
            z = 1.0 + 0.06 * (t / dur)
            CAM = T(fx, fy) @ Sc(z) @ T(-fx, -fy) @ T(0, OYc) @ Sc(S)
            frame = cv2.warpAffine(comp, CAM[:2].astype(np.float32), (OW, OH), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REFLECT)
            ff.stdin.write(frame.tobytes())
            if keyframes_dir is not None and fi in keyset:
                imwrite_kr(keyframes_dir / f"f{fi:04d}.png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            if fi % 150 == 0:
                print(f"    frame {fi}/{nfr}", flush=True)
    finally:
        ff.stdin.close(); ff.wait()
    return ff.returncode == 0 and Path(out_mp4).exists(), nfr


# ───────────────────────── 확인 이미지 ─────────────────────────
COLORS = [(230, 60, 60), (40, 120, 230), (40, 170, 70), (220, 150, 20), (160, 60, 200)]


def check_image(path, base, A, lab, chars, levels, blinks, info):
    from PIL import Image, ImageDraw, ImageFont
    h, w = A.shape
    ov = base.astype(np.float32).copy()
    for i in range(len(chars)):
        m = (lab == i)[..., None] * 0.35
        ov = ov * (1 - m) + np.array(COLORS[i % 5], np.float32) * m
    im = Image.fromarray(ov.astype(np.uint8))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for i, c in enumerate(chars):
        col = COLORS[i % 5]
        d.rectangle(c["bbox"], outline=col, width=2); d.rectangle(c["face"], outline=(255, 255, 255), width=1)
        if c["mouth"]: d.rectangle(c["mouth"], outline=(255, 0, 0), width=2)
        for e in c["eyes"]: d.rectangle(e, outline=(0, 120, 255), width=2)
        fx, fy = c["feet"]; d.ellipse((fx - 4, fy - 4, fx + 4, fy + 4), fill=col)
        spk = ",".join(c.get("speakers", [])) or "-"
        txt = (f"c{i} {c['id']} [{spk}] {c['facing']} 입:{'움직임' if i in levels else '끔'} "
               f"눈:{'깜빡' if i in blinks else '-'}")
        d.rectangle((c["bbox"][0], max(c["bbox"][1] - 20, 0), c["bbox"][0] + 9 * len(txt), max(c["bbox"][1], 20)), fill=(0, 0, 0))
        d.text((c["bbox"][0] + 2, max(c["bbox"][1] - 20, 0)), txt, fill=col, font=font)
    tiles = []
    for i, c in enumerate(chars):
        row = [face_crop(base, c, 200)]
        if i in levels:
            for p in levels[i]["levels"]:
                if p is not None:
                    cand = base.copy(); apply_patch(cand, p); row.append(face_crop(cand, c, 200))
        if i in blinks:
            cand = base.copy(); apply_patch(cand, blinks[i]); row.append(face_crop(cand, c, 200))
        tiles.append(row)
    th = sum(max(t.shape[0] for t in r) + 8 for r in tiles) if tiles else 0
    sheet = Image.new("RGB", (max(w, 1100), h + th + 40), (255, 255, 255))
    sheet.paste(im, (0, 0))
    dd = ImageDraw.Draw(sheet)
    dd.text((6, h + 4), info, fill=(0, 0, 0), font=font)
    y = h + 30
    for i, r in enumerate(tiles):
        x = 0
        dd.text((x + 2, y), f"c{i}", fill=COLORS[i % 5], font=font); x += 40
        for t in r:
            sheet.paste(Image.fromarray(t), (x, y)); x += t.shape[1] + 6
        y += max(t.shape[0] for t in r) + 8
    sheet.save(str(path))


# ───────────────────────── 메인 ─────────────────────────
def run(ep, args, outs):
    t0 = time.time()
    story = json.load(open(ep / "story.json", encoding="utf-8"))
    timing = json.load(open(ep / "audio" / "timing.json", encoding="utf-8"))
    anim = ep / "anim"; lay = anim / "_layers"
    roles, sup_keys = role_table(story.get("meta", {}))
    win = slide_windows(timing)
    cands = [args.slide] if args.slide is not None else pick_candidates(ep, story, timing)
    print(f"[11b] 후보 슬라이드: {cands}")
    if not cands:
        print("[11b] 조건(깨끗한 배경·포즈 + 대사 2개 이상)에 맞는 슬라이드 없음 → 건너뜀"); return False
    parts_dir = anim / "_key_parts"; parts_dir.mkdir(parents=True, exist_ok=True)
    outs.append(parts_dir)
    gem = Gem(parts_dir, args.reuse)
    for n in cands[:2]:
        print(f"\n[11b] slide {n}")
        if not ((lay / f"s{n:02d}_bg.png").exists() and (lay / f"s{n:02d}_A_cut.png").exists()):
            print("  레이어 없음"); continue
        base, F, A = build_layers(lay, n)
        h, w = A.shape
        bg = cv2.resize(rgb_read(lay / f"s{n:02d}_bg.png"), (w, h), interpolation=cv2.INTER_AREA)
        segs = [dict(g) for g in timing["segments"] if g["slide"] == n]
        vstart, dur = win[n]
        speakers = sorted({g["speaker"] for g in segs if g["speaker"] != "narrator"})
        chars = detect(gem, base, roles, [speaker_role(s, roles, sup_keys) or s for s in speakers], n)
        if not chars:
            print("  캐릭터 검출 실패"); continue
        spk2char = {}
        for s in speakers:
            r = speaker_role(s, roles, sup_keys)
            for i, c in enumerate(chars):
                if r and c["id"] == r:
                    spk2char[s] = i; c.setdefault("speakers", []).append(s)
        if not spk2char:
            print(f"  화자↔캐릭터 매핑 실패 (화자 {speakers}, 검출 {[c['id'] for c in chars]})"); continue
        lab, weights = label_sprites(A, chars, F)
        for g in segs:
            g["t"] = g["start"] - vstart
            g["char"] = spk2char.get(g["speaker"])
            wp = ep / "audio" / g["file"]
            g["env"], g["peaks"] = seg_envelope(wp) if (wp.exists() and g["char"] is not None) else (np.zeros(1), [])
        talkers = [(i, c) for i, c in enumerate(chars)
                   if i in spk2char.values() and c["mouth"] and c["facing"] in ("front", "three_quarter")]
        blinkers = [(i, c) for i, c in enumerate(chars) if c["eyes_open"] and c["eyes"] and c["facing"] != "back"]
        print(f"  검출 {len(chars)}명: " + ", ".join(f"c{i}={c['id']}({c['facing']},입{'열림' if c['mouth_open'] else '다묾'})"
                                                for i, c in enumerate(chars)))
        print(f"  화자 매핑 {spk2char}, 입 대상 {[i for i, _ in talkers]}, 깜빡임 대상 {[i for i, _ in blinkers]}")
        log = {}
        levels, blinks = build_parts(gem, base, A, talkers, blinkers, n, parts_dir, log)
        out_mp4 = anim / f"key_slide_{n:02d}.mp4"
        tmp_mp4 = anim / f"_key_slide_{n:02d}.tmp.mp4"
        outs.append(tmp_mp4)
        kdir = parts_dir / f"frames_s{n:02d}"; kdir.mkdir(exist_ok=True)
        print(f"  렌더: {dur:.3f}s (슬라이드 영상 시작 {vstart:.3f}s, 입 {sorted(levels)}, 깜빡 {sorted(blinks)})")
        ok, nfr = render(tmp_mp4, bg, F, A, chars, weights, segs, levels, blinks, dur, kdir)
        if not ok:
            print("  렌더 실패"); continue
        os.replace(tmp_mp4, out_mp4); outs.append(out_mp4)
        rec = {
            "slide": n, "video_start_nominal": vstart, "duration": dur, "frames": nfr, "fps": FPS,
            "audio_lead_note": "세그먼트 t = start - video_start_nominal. 06이 실제 누적 시작과의 차(drift)만큼 잘라 맞춘다",
            "speakers": spk2char, "image_calls": gem.img_calls, "vision_calls": gem.vis_calls,
            "image_cost_usd": round(gem.cost, 3), "elapsed_sec": round(time.time() - t0, 1),
            "characters": [{k: v for k, v in c.items() if k in ("id", "label", "bbox", "face", "mouth", "eyes", "facing",
                                                               "eyes_open", "mouth_open", "teeth", "feet", "speakers")}
                           | {"mouth_motion": i in levels, "mouth_levels": len(levels[i]["levels"]) if i in levels else 0,
                              "blink": i in blinks, "checks": log.get(str(i), {})}
                           for i, c in enumerate(chars)],
            "segments": [{k: g[k] for k in ("index", "speaker", "t", "duration")} | {"char": g["char"]} for g in segs],
        }
        jp = anim / "key_scene.json"
        json.dump(rec, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float); outs.append(jp)
        cp = anim / "key_scene_check.png"
        check_image(cp, base, A, lab, chars, levels, blinks,
                    f"slide {n}  화자{spk2char}  이미지 {gem.img_calls}장 ${gem.cost:.2f}  {time.time() - t0:.0f}s")
        outs.append(cp)
        print(f"[11b] 완료 → {out_mp4.name} ({nfr}프레임), 이미지 {gem.img_calls}장 ${gem.cost:.3f}, "
              f"비전 {gem.vis_calls}회, {time.time() - t0:.0f}s")
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--slide", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="기존 key_slide 가 있어도 다시 만든다")
    ap.add_argument("--reuse", action="store_true", help="anim/_key_parts 캐시(편집 이미지·검출) 재사용")
    args = ap.parse_args()
    ep = Path(args.dir)
    anim = ep / "anim"
    old = sorted(anim.glob("key_slide_*.mp4")) if anim.exists() else []
    if old and not args.force:
        print(f"[11b] 이미 있음: {[p.name for p in old]} (다시 만들려면 --force)"); return
    if args.force:
        for p in old + [anim / "key_scene.json", anim / "key_scene_check.png"]:
            Path(p).unlink(missing_ok=True)
    outs = []
    ok = False
    try:
        ok = run(ep, args, outs)
    except Exception:
        traceback.print_exc()
        ok = False
    if not ok:
        for p in outs:
            p = Path(p)
            if p.is_dir() and not args.reuse:
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                p.unlink(missing_ok=True)
        for p in [anim / "key_scene.json", anim / "key_scene_check.png"] + list(anim.glob("key_slide_*.mp4")) + \
                 list(anim.glob("_key_slide_*.tmp.mp4")):
            Path(p).unlink(missing_ok=True)
        print("[11b] 핵심 장면 연출 생략 (정지 그림/11번 애니로 진행)")
    else:
        shutil.rmtree(anim / "_key_parts" / f"frames_s{json.load(open(anim / 'key_scene.json', encoding='utf-8'))['slide']:02d}",
                      ignore_errors=True) if not os.getenv("KEYSCENE_KEEP_FRAMES") else None
    sys.exit(0)


if __name__ == "__main__":
    main()
