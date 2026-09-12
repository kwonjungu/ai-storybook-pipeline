#!/usr/bin/env python3
"""
11_animate_scenes.py — 핵심 장면에 '살아있는' 레이어 애니메이션 부여

방식(레이어 합성):
  1) 원본 slide_XX.png 참조 → 캐릭터 없는 '배경'만 생성
  2) 원본 참조 → 캐릭터 '포즈A'(그린스크린, 기본 자세)
  3) 포즈A 참조 → 캐릭터 '포즈B'(그린스크린, 팔·다리 다른 자세)
  4) rembg로 포즈 배경 제거(투명 PNG)
  5) FFmpeg로 배경 고정 + 두 포즈 교차(팔다리 모션) + 살랑 이동 → anim/slide_XX.mp4

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
SWAY_X = 14      # 좌우 살랑 진폭(px, 1920 기준)
BOB_Y = 7        # 상하 진폭


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
    yexpr = f"20+{BOB_Y}*sin(2*PI*t/2.5)"
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

    ok_list = []
    for n in targets:
        src = ep / "images" / f"slide_{n:02d}.png"
        if not src.exists():
            print(f"  slide {n}: 원본 없음, 건너뜀"); continue
        print(f"\n[slide {n}] 레이어 생성 중...")
        bg = work / f"s{n:02d}_bg.png"; bg = bg.with_suffix(".png")
        pA = work / f"s{n:02d}_poseA.png"
        pB = work / f"s{n:02d}_poseB.png"
        tA = work / f"s{n:02d}_A_cut.png"
        tB = work / f"s{n:02d}_B_cut.png"

        # 배경: 캐릭터를 제거한 '깨끗한 배경'을 재생성(흔적 없음). 실패 시 inpaint 폴백.
        if not bg_regenerate_clean(client, src, bg):
            print(f"  slide {n}: 배경 재생성 실패 → inpaint 폴백")
            if not bg_from_original(src, bg, session):
                print(f"  slide {n}: 배경 분리 실패"); continue
        gen_image(client,
            "Take the main character(s) from the reference image and redraw them, FULL BODY head to toe, "
            "in a natural standing pose facing forward, arms relaxed. Keep their EXACT design, colors and "
            f"style. Place them alone on a {GREEN}. Nothing else.",
            pA, refs=[src])
        gen_image(client,
            "The exact same character(s) as the reference, identical design, but now in a lively pose: "
            "arms raised up and one foot lifted, happy smiling, mid-motion (as if waving/dancing). "
            f"FULL BODY, same size and position, on the same {GREEN}.",
            pB, refs=[pA])

        if not (bg.exists() and pA.exists() and pB.exists()):
            print(f"  slide {n}: 레이어 생성 실패"); continue
        okA = cutout(pA, tA, session)
        okB = cutout(pB, tB, session)
        if not (okA and okB):
            print(f"  slide {n}: 캐릭터 추출 실패, 건너뜀"); continue

        out_mp4 = anim_dir / f"slide_{n:02d}.mp4"
        if make_clip(bg, tA, tB, out_mp4, args.ffbin):
            print(f"  slide {n}: anim/slide_{n:02d}.mp4 생성 완료")
            ok_list.append(n)
        else:
            print(f"  slide {n}: 클립 합성 실패")

    print(f"\n[완료] 애니 슬라이드 {len(ok_list)}개: {ok_list}")
    print("  → python 06_assemble_video.py --dir 로 재조립하면 해당 컷이 애니로 들어갑니다.")


if __name__ == "__main__":
    main()
