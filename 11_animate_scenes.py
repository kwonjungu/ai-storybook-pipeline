#!/usr/bin/env python3
"""
11_animate_scenes.py — 핵심 장면에 '살아있는' 레이어 애니메이션 부여

방식(레이어 합성):
  1) 원본 slide_XX.png 참조 → 캐릭터 없는 '배경'만 생성 (실패하면 그 컷은 애니 생략)
  2) 원본을 '편집' → 캐릭터만 남기고 배경을 그린스크린으로 (포즈A: 원본과 같은 위치·크기·자세)
  3) 포즈A를 '편집' → 팔·손 동작만 바꾼 포즈B (인원·위치·크기 유지)
  4) rembg로 포즈 배경 제거(투명 PNG)
  5) ★ 검사 게이트(anim/anim_qa.json): 포즈A가 원본 자리에 있는가, A↔B 인원·위치·크기가 같은가,
     Vision 이산 판정(인원 수·같은 캐릭터인가). 불합격이면 재생성 2회, 그래도 안 되면 정지 그림 유지
  6) FFmpeg로 배경 고정 + 두 포즈 교차 + 아주 작은 들썩임 → anim/slide_XX.mp4

2026-10-11 개편: 예전에는 포즈A를 '정면 전신'으로 새로 그리고 B를 A에서 다시 그려,
캐릭터가 엉뚱한 자리로 옮겨지거나(구도 소실) B에서 한 명이 사라지고·다른 캐릭터로 바뀌어도
걸러지지 않았다(119컷 중 21컷 신호, 수도꼭지 s00·달팽이 s00·모두의하루 s03 등).

06_assemble_video.py가 anim/slide_XX.mp4가 있으면 정지 대신 루프 사용.

사용법:
  python 11_animate_scenes.py --dir output/폴더               # 핵심 4컷 자동 선정
  python 11_animate_scenes.py --dir output/폴더 --slides 0 5 6 11
"""
import argparse, base64, os, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
from dotenv import load_dotenv
load_dotenv()

GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GREEN = "solid pure bright green background (#00B140), completely flat, no shadow, no floor"

# 포즈 교차 주기(초). 작을수록 빠르게 팔다리 움직임
POSE_PERIOD = 0.9
SWAY_X = 3       # 좌우 살랑 진폭(px, 1920 기준) — 캐릭터가 원본 자리에 있으므로 크게 흔들면 발이 뜬다
BOB_Y = 3        # 상하 진폭

# 검사 게이트 기준
POS_MAX_DIFF = 38      # 포즈A 픽셀이 원본 같은 자리 픽셀과 다른 정도(평균 RGB 차) 상한
AB_MIN_IOU = 0.55      # A↔B 실루엣 겹침
AB_MAX_SHIFT = 0.05    # A↔B 무게중심 이동(화면 비율)
AB_AREA = (0.75, 1.35) # A↔B 면적 비
MAX_TRIES = 3          # 포즈 생성 시도(최초 + 재생성 2회)
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")


def imread_kr(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)

def imwrite_kr(path, im):
    ok, buf = cv2.imencode(Path(path).suffix, im)
    if ok:
        buf.tofile(str(path))


def gen_image(client, prompt, out_path, refs=(), ar="16:9"):
    from google.genai import types
    parts = [types.Part.from_bytes(data=Path(r).read_bytes(), mime_type="image/png") for r in refs]
    contents = parts + [prompt]
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL, contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=ar, image_size="1K")))
            for c in resp.candidates:
                for p in c.content.parts:
                    if getattr(p, "inline_data", None):
                        raw = p.inline_data.data
                        b = raw if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)
                        Path(out_path).write_bytes(bytes(b))
                        return True
        except Exception as e:
            print(f"    [재시도 {attempt+1}] {str(e)[:80]}")
    return False


def cutout(png_path, out_path, session):
    """rembg로 배경 제거 → 투명 PNG."""
    from rembg import remove
    arr = cv2.imdecode(np.frombuffer(remove(Path(png_path).read_bytes(), session=session), np.uint8),
                       cv2.IMREAD_UNCHANGED)
    if arr.shape[2] < 4:
        return False
    a = arr[:, :, 3]
    m = (a > 50).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    m = cv2.GaussianBlur(m, (0, 0), 1.5)
    arr[:, :, 3] = m
    imwrite_kr(out_path, arr)
    return (a > 50).mean() > 0.02  # 캐릭터가 유의미하게 잡혔는지


# ── 검사 게이트 ───────────────────────────────────────────
def _mask(cut_path):
    a = imread_kr(cut_path)[:, :, 3]
    return (a > 128).astype(np.uint8)


def _blobs(m):
    """화면 실루엣의 큰 덩어리 수(전체 면적의 8% 이상)."""
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    tot = max(int(m.sum()), 1)
    return sum(1 for i in range(1, n) if st[i][4] > 0.08 * tot)


def check_position(src, cut_path):
    """포즈A가 원본과 같은 자리에 있는지: 실루엣 안의 픽셀이 원본 같은 자리 픽셀과 비슷해야 한다."""
    orig = imread_kr(src)[:, :, :3].astype(np.int16)
    cut = imread_kr(cut_path)
    m = cut[:, :, 3] > 200
    if m.sum() == 0:
        return False, 999.0
    if orig.shape[:2] != cut.shape[:2]:
        orig = cv2.resize(orig.astype(np.uint8), (cut.shape[1], cut.shape[0])).astype(np.int16)
    d = float(np.abs(cut[:, :, :3].astype(np.int16) - orig)[m].mean())
    return d <= POS_MAX_DIFF, round(d, 1)


def check_pair(cutA, cutB):
    """A↔B 인원·위치·크기 유지."""
    ma, mb = _mask(cutA), _mask(cutB)
    if ma.sum() == 0 or mb.sum() == 0:
        return False, {"reason": "빈 실루엣"}
    H, W = ma.shape
    ya, xa = np.where(ma); yb, xb = np.where(mb)
    shift = max(abs(xb.mean() - xa.mean()) / W, abs(yb.mean() - ya.mean()) / H)
    area = mb.sum() / ma.sum()
    iou = (ma & mb).sum() / max((ma | mb).sum(), 1)
    na, nb = _blobs(ma), _blobs(mb)
    info = {"blobs": [na, nb], "iou": round(float(iou), 2), "shift": round(float(shift), 3),
            "area": round(float(area), 2)}
    ok = (na == nb and iou >= AB_MIN_IOU and shift <= AB_MAX_SHIFT and AB_AREA[0] <= area <= AB_AREA[1])
    return ok, info


def check_vision(client, src, cut_path, names):
    """이산 판정: 원본과 포즈 이미지의 캐릭터 수·정체가 같은가. 판정 실패 시 통과 처리하지 않는다."""
    import json, re
    from google.genai import types
    cut = imread_kr(cut_path)
    white = np.full(cut.shape[:2] + (3,), 255, np.uint8)
    a = cut[:, :, 3:4] / 255.0
    flat = (cut[:, :, :3] * a + white * (1 - a)).astype(np.uint8)
    ok_enc, buf = cv2.imencode(".png", flat)
    who = f" The story characters in this scene may include: {', '.join(names)}." if names else ""
    q = ("Image 1 is a storybook scene. Image 2 should contain the SAME characters cut out from it." + who +
         " Answer ONLY JSON: {\"count_scene\": <number of characters (animals or people) in image 1>, "
         "\"count_cut\": <number of characters in image 2>, \"same_characters\": true/false "
         "(every character in image 2 is the same species and design as one in image 1, none replaced or duplicated), "
         "\"missing\": [short names of characters in image 1 that are absent in image 2]}")
    try:
        r = client.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=[types.Part.from_bytes(data=Path(src).read_bytes(), mime_type="image/png"),
                      types.Part.from_bytes(data=buf.tobytes(), mime_type="image/png"), q])
        j = json.loads(re.search(r"\{.*\}", r.text, re.S).group(0))
    except Exception as e:
        return False, {"error": str(e)[:80]}
    ok = (j.get("count_scene") == j.get("count_cut") and j.get("same_characters") is True and not j.get("missing"))
    return ok, j


def slide_character_names(story, n):
    """슬라이드 n 의 화자·등장 캐릭터 이름(판정 힌트용)."""
    chars = story.get("meta", {}).get("characters") or {}
    slides = story.get("slides", [])
    s = slides[n] if 0 <= n < len(slides) else {}
    text = " ".join(str(seg.get("text", "")) for seg in s.get("tts_segments", [])) + " " + str(s.get("image_prompt", ""))
    names = []
    for c in chars.values():
        nm = (c or {}).get("name", "")
        if nm and (nm in text or (c.get("appearance_en", "")[:30] and c["appearance_en"][:30] in text)):
            names.append(nm)
    return names


def bg_regenerate_clean(client, src, out_path):
    """원본 참조로 '캐릭터만 제거한 동일 배경'을 깨끗하게 새로 생성.
    inpaint는 캐릭터 있던 자리에 얼룩/흔적이 남으므로, 배경 레이어를 아예 분리해
    Gemini가 같은 장소를 캐릭터 없이 다시 그리게 함(흔적 없음). 실패 시 폴백은 호출부에서."""
    return gen_image(client,
        "Recreate the EXACT background scene from the reference image, but with ALL characters "
        "(every animal and person) COMPLETELY REMOVED. Keep the identical setting, composition, "
        "colors, lighting, art style and every background element (sky, ground, grass, plants, "
        "flowers, buildings, furniture, props). Wherever a character used to stand, fill it in "
        "naturally with the surrounding background so there is NO empty hole, NO blur, NO smudge, "
        "NO leftover outline. The result is the same place, simply empty of characters. "
        "Absolutely no characters, no creatures, no figures anywhere.",
        out_path, refs=[src])


def bg_from_original(src, out_path, session):
    """폴백: 캐릭터 자리를 inpaint로 메움(원본 배경 유지, 흔적 가능)."""
    from rembg import remove
    img = imread_kr(src)
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    arr = cv2.imdecode(np.frombuffer(remove(Path(src).read_bytes(), session=session), np.uint8),
                       cv2.IMREAD_UNCHANGED)
    if arr.shape[2] < 4:
        return False
    mask = (arr[:, :, 3] > 40).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((17, 17), np.uint8))
    bg = cv2.inpaint(img, mask, 9, cv2.INPAINT_TELEA)
    imwrite_kr(out_path, bg)
    return True


def make_clip(bg, poseA, poseB, out_mp4, ffbin=""):
    ff = os.path.join(ffbin, "ffmpeg") if ffbin else "ffmpeg"
    half = POSE_PERIOD / 2
    xexpr = f"{SWAY_X}*sin(2*PI*t/3.2)"
    yexpr = f"{BOB_Y}*sin(2*PI*t/2.5)"   # 포즈가 원본 자리에 정렬돼 있으므로 오프셋 없음
    fc = (
        "[0:v]scale=1920:1080,setsar=1[bg];"
        "[1:v]scale=1920:1080,setsar=1[a];"
        "[2:v]scale=1920:1080,setsar=1[b];"
        f"[bg][a]overlay=x='{xexpr}':y='{yexpr}':enable='lt(mod(t,{POSE_PERIOD}),{half})'[t1];"
        f"[t1][b]overlay=x='{xexpr}':y='{yexpr}':enable='gte(mod(t,{POSE_PERIOD}),{half})',format=yuv420p[v]"
    )
    cmd = [ff, "-y", "-loop", "1", "-i", str(bg), "-loop", "1", "-i", str(poseA),
           "-loop", "1", "-i", str(poseB), "-filter_complex", fc,
           "-map", "[v]", "-t", "7.2", "-r", "30",
           "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", str(out_mp4)]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _load_shorts_slides(story_dir):
    """shorts_plan.json에서 쇼츠 사용 구간 슬라이드 번호 집합을 반환."""
    try:
        import json
        sp = json.load(open(Path(story_dir) / "shorts_plan.json", encoding="utf-8"))
    except Exception:
        return set()
    used = sp.get("slides_to_use")
    if isinstance(used, list) and used:
        return set(int(x) for x in used)
    # 폴백: start_slide..end_slide 범위
    start, end = sp.get("start_slide"), sp.get("end_slide")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return set(range(start, end + 1))
    return set()


def pick_key_slides(story, limit=6, story_dir=None):
    """핵심 컷 자동 선정: 도입 1 + 전개 2 + 절정 2 + 결말 1 (기본 6컷).

    - 서사 구간은 story 슬라이드를 위치 기준 4분할(도입/전개/절정/결말)로 배정.
    - 각 구간에서 감정 절정(realization/happy_ending) + 주인공 단독 컷을 우선.
    - shorts_plan.slides_to_use(또는 start~end 범위)에 포함된 슬라이드에 우선 가중치.
    """
    slides = story.get("slides", [])
    story_slides = [s for s in slides if s.get("type") == "story"]
    story_slides.sort(key=lambda s: s.get("slide_number", 0))
    shorts_slides = _load_shorts_slides(story_dir) if story_dir else set()

    picks = []
    # 1) 커버 1컷 (도입 대표)
    for s in slides:
        if s.get("type") == "cover":
            picks.append(s["slide_number"]); break

    if not story_slides:
        return picks[:limit]

    # 서사 4구간 분할 (도입/전개/절정/결말) — 위치 기준
    n = len(story_slides)
    def _seg(a, b):
        return story_slides[int(n * a):max(int(n * a) + 1, int(n * b))]
    stages = {
        "intro":   _seg(0.0, 0.20),
        "rising":  _seg(0.20, 0.55),
        "climax":  _seg(0.55, 0.85),
        "ending":  _seg(0.85, 1.0),
    }
    # 구간별 목표 컷 수 (커버가 도입을 이미 1컷 담당 → intro 0)
    quota = {"intro": 0, "rising": 2, "climax": 2, "ending": 1}

    EMO = ("realization", "happy_ending", "bright_cheerful")

    def only_mains(s):
        sp = {seg.get("speaker") for seg in s.get("tts_segments", [])}
        return sp.issubset({"narrator", "child_boy", "child_girl"})

    def score_key(s):
        # 낮을수록 우선: 쇼츠 구간 > 주인공 단독 > 감정 절정
        in_shorts = s.get("slide_number") in shorts_slides
        return (
            0 if in_shorts else 1,
            0 if only_mains(s) else 1,
            0 if s.get("color_mood") in ("realization", "happy_ending") else 1,
            s.get("slide_number", 0),
        )

    for stage in ("rising", "climax", "ending"):
        cand = sorted(stages[stage], key=score_key)
        taken = 0
        for s in cand:
            if taken >= quota[stage]:
                break
            if s["slide_number"] not in picks:
                picks.append(s["slide_number"]); taken += 1

    # limit 미달 시: 남은 감정 절정/쇼츠 컷으로 보충
    if len(picks) < limit:
        rest = [s for s in story_slides if s["slide_number"] not in picks
                and s.get("color_mood") in EMO]
        rest.sort(key=score_key)
        for s in rest:
            if len(picks) >= limit:
                break
            picks.append(s["slide_number"])

    return picks[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--slides", type=int, nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=6,
                    help="자동 선정 컷 수 (기본 6: 도입1+전개2+절정2+결말1)")
    ap.add_argument("--ffbin", default=os.getenv("FFMPEG_BIN", ""))
    args = ap.parse_args()

    ep = Path(args.dir)
    import json
    story = json.load(open(ep / "story.json", encoding="utf-8"))
    targets = args.slides if args.slides else pick_key_slides(story, limit=args.limit, story_dir=ep)
    print(f"[애니 대상 슬라이드] {targets}")

    from google import genai
    from rembg import new_session
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    session = new_session("u2net")

    anim_dir = ep / "anim"; anim_dir.mkdir(exist_ok=True)
    work = anim_dir / "_layers"; work.mkdir(exist_ok=True)

    qa_path = anim_dir / "anim_qa.json"
    qa = json.load(open(qa_path, encoding="utf-8")) if qa_path.exists() else {}
    ok_list = []
    for n in targets:
        src = ep / "images" / f"slide_{n:02d}.png"
        if not src.exists():
            print(f"  slide {n}: 원본 없음, 건너뜀"); continue
        print(f"\n[slide {n}] 레이어 생성 중...")
        bg = work / f"s{n:02d}_bg.png"
        pA = work / f"s{n:02d}_poseA.png"
        pB = work / f"s{n:02d}_poseB.png"
        tA = work / f"s{n:02d}_A_cut.png"
        tB = work / f"s{n:02d}_B_cut.png"
        out_mp4 = anim_dir / f"slide_{n:02d}.mp4"
        rec = {"result": "skip", "tries": []}
        names = slide_character_names(story, n)

        # 배경: 캐릭터를 제거한 '깨끗한 배경'을 재생성. 실패하면 얼룩 남는 inpaint 대신 애니를 생략한다.
        if not bg_regenerate_clean(client, src, bg):
            print(f"  slide {n}: 배경 재생성 실패 → 정지 그림 유지")
            rec["reason"] = "배경 재생성 실패"
            qa[str(n)] = rec; out_mp4.unlink(missing_ok=True); continue

        passed = False
        for t in range(MAX_TRIES):
            # 포즈A: 원본을 편집해 배경만 그린스크린으로 (위치·크기·자세 그대로)
            gen_image(client,
                "Edit this exact image: keep EVERY character (all animals and people) exactly as drawn — same pose, "
                "same size, same position in the frame, same colors. Remove everything else (background, ground, "
                f"props) and replace it with a {GREEN}. Do not add, remove, move or redraw any character.",
                pA, refs=[src])
            if not (pA.exists() and cutout(pA, tA, session)):
                rec["tries"].append({"A": "생성/추출 실패"}); continue
            okp, pd = check_position(src, tA)
            if not okp:
                rec["tries"].append({"A_pos_diff": pd}); print(f"  slide {n}: 포즈A 위치 불일치({pd}) 재시도"); continue
            # 포즈B: 포즈A를 편집해 팔·손 동작만 변경
            gen_image(client,
                "Edit this exact image: change ONLY the arms and paws of the characters into a lively gesture "
                "(one arm raised waving, or both paws up), happy expression. Keep the SAME number of characters, "
                "each one the same character, same size, same position, feet in the same place, identical design. "
                f"Keep the {GREEN}.",
                pB, refs=[pA])
            if not (pB.exists() and cutout(pB, tB, session)):
                rec["tries"].append({"A_pos_diff": pd, "B": "생성/추출 실패"}); continue
            okab, info = check_pair(tA, tB)
            okv, vj = (check_vision(client, src, tB, names) if okab else (False, None))
            rec["tries"].append({"A_pos_diff": pd, "pair": info, "vision": vj})
            if okab and okv:
                passed = True; break
            print(f"  slide {n}: 포즈 검사 불합격 {info} {vj} 재시도")

        if not passed:
            print(f"  slide {n}: 검사 불합격 {MAX_TRIES}회 → 정지 그림 유지")
            rec["reason"] = "포즈 검사 불합격"
            qa[str(n)] = rec; out_mp4.unlink(missing_ok=True); continue

        if make_clip(bg, tA, tB, out_mp4, args.ffbin):
            print(f"  slide {n}: anim/slide_{n:02d}.mp4 생성 완료")
            rec["result"] = "ok"; ok_list.append(n)
        else:
            print(f"  slide {n}: 클립 합성 실패")
            rec["reason"] = "클립 합성 실패"
        qa[str(n)] = rec
        json.dump(qa, open(qa_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(qa, open(qa_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[완료] 애니 슬라이드 {len(ok_list)}개: {ok_list}  (검사 기록: anim/anim_qa.json)")
    print("  → python 06_assemble_video.py --dir 로 재조립하면 해당 컷이 애니로 들어갑니다.")


if __name__ == "__main__":
    main()
