#!/usr/bin/env python3
"""
02_generate_images.py
story.json의 각 슬라이드에 대해 Gemini 2.5 Flash Image API로 이미지를 생성합니다.

기본: Batch API (50% 할인, 비동기 처리, ~수분~수시간 소요)
옵션: --realtime (즉시 생성, 비용 2배)

사용법:
  python 02_generate_images.py --ep 3           # 배치 모드 (기본, 50% 할인)
  python 02_generate_images.py --ep 3 --realtime  # 실시간 모드 (즉시 생성)
  python 02_generate_images.py --dir output/bsl01  # 디렉터리 지정
"""

import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Windows cp949 인코딩 문제 방지
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv

load_dotenv()

# Gemini image generation model
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


# ======================================================================
# 프롬프트 빌드 (공통)
# ======================================================================

def build_prompts(story, slides, ep_dir, force=False):
    """슬라이드별 이미지 프롬프트를 빌드하고 생성 대상 목록을 반환한다.

    Returns:
        tasks: list of dict {slide_num, prompt, aspect_ratio, output_path}
        skipped: int
    """
    meta = story.get("meta", {})
    characters = meta.get("characters") or {}
    main1_appearance = (characters.get("main_1") or {}).get("appearance_en", "")
    main2_appearance = (characters.get("main_2") or {}).get("appearance_en", "")

    supporting = characters.get("supporting") or {}
    supporting_info = {}
    for key, val in supporting.items():
        if isinstance(val, dict):
            app_en = val.get("appearance_en", "")
            name_en = val.get("name_en", "") or val.get("name", "")
            if app_en:
                supporting_info[key] = {"name": name_en, "appearance_en": app_en}

    # shorts_plan.json
    shorts_slides = set()
    plan_path = ep_dir / "shorts_plan.json"
    if plan_path.exists():
        with open(plan_path, "r", encoding="utf-8") as f:
            shorts_plan = json.load(f)
        s, e = shorts_plan.get("start_slide", -1), shorts_plan.get("end_slide", -1)
        shorts_slides = set(range(s, e + 1))
        print(f"[INFO] shorts_plan.json 발견 — 슬라이드 {s}~{e} 에 9:16 이미지도 생성")

    images_dir = ep_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    skipped = 0

    for slide in slides:
        slide_num = slide.get("slide_number", 0)
        image_path = images_dir / f"slide_{slide_num:02d}.png"

        if image_path.exists() and not force:
            print(f"[슬라이드 {slide_num:02d}] 이미 존재 — 건너뜀")
            skipped += 1
            continue

        image_prompt = slide.get("image_prompt", "")
        if not image_prompt:
            print(f"[슬라이드 {slide_num:02d}] image_prompt가 비어 있음 — 건너뜀")
            skipped += 1
            continue

        # 캐릭터 외모 safety-net
        if main1_appearance and main1_appearance[:50] not in image_prompt:
            image_prompt += " " + main1_appearance
        if main2_appearance and main2_appearance[:50] not in image_prompt:
            image_prompt += " " + main2_appearance
        for key, info in supporting_info.items():
            app = info["appearance_en"]
            name = info["name"]
            key_in_prompt = key.replace("_", " ").lower() in image_prompt.lower()
            name_in_prompt = name and name.split()[0].lower() in image_prompt.lower()
            if (key_in_prompt or name_in_prompt) and app[:50] not in image_prompt:
                image_prompt += " " + app

        # 텍스트/글자 방지
        if "absolutely no text" not in image_prompt:
            image_prompt += (
                " absolutely no text, no speech bubbles, no letters, no words, "
                "no writing, no captions, no signs with text anywhere in the image, "
                "no thought bubbles, no dialogue balloons"
            )
        # 색온도 방지
        if "NEUTRAL to COOL" not in image_prompt:
            image_prompt += (
                " The overall color temperature must be NEUTRAL to COOL, not warm. "
                "Avoid any yellow or amber color cast. White objects must appear pure white."
            )
        # 배경 텍스트 방지
        if "no readable text on any surface" not in image_prompt:
            image_prompt += (
                " no readable text on any surface — "
                "chalkboards and blackboards should be blank or have only abstract marks, "
                "no posters with legible text, no signs with words"
            )

        # 16:9 (기본)
        tasks.append({
            "slide_num": slide_num,
            "prompt": image_prompt,
            "aspect_ratio": "16:9",
            "output_path": image_path,
        })

        # 9:16 (Shorts용)
        if slide_num in shorts_slides:
            v_path = images_dir / f"slide_{slide_num:02d}_9x16.png"
            if v_path.exists() and not force:
                print(f"  [9:16] 이미 존재 — 건너뜀: {v_path.name}")
            else:
                vertical_prompt = (
                    "Vertical portrait composition for 9:16 aspect ratio. "
                    "All important subjects and scene elements centered in the middle of the frame, "
                    "with safe margins on all sides. "
                    "Nothing important cropped near the edges. "
                    + image_prompt
                )
                tasks.append({
                    "slide_num": slide_num,
                    "prompt": vertical_prompt,
                    "aspect_ratio": "9:16",
                    "output_path": v_path,
                })

    return tasks, skipped


# ======================================================================
# 실시간 모드 (기존 방식)
# ======================================================================

def generate_image_gemini(client, prompt: str, output_path: Path,
                          aspect_ratio: str = "16:9",
                          max_retries: int = 3) -> bool:
    """Gemini API로 이미지 생성 후 저장. 성공 시 True 반환."""
    from google.genai import types

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size="1K",
                    ),
                ),
            )

            img_bytes = None
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        raw = part.inline_data.data
                        if isinstance(raw, (bytes, bytearray)):
                            img_bytes = bytes(raw)
                        else:
                            img_bytes = base64.b64decode(raw)
                        break
                if img_bytes:
                    break

            if not img_bytes:
                print(f"    [WARN] 시도 {attempt}/{max_retries}: 이미지 데이터 없음")
                if attempt < max_retries:
                    time.sleep(5)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_bytes)

            print(f"    -> 저장 완료: {output_path.name} ({len(img_bytes):,} bytes)")
            return True

        except Exception as e:
            print(f"    [WARN] 시도 {attempt}/{max_retries} 실패: {e}")
            if attempt < max_retries:
                time.sleep(8)

    return False


def run_realtime(client, tasks):
    """실시간 모드: 슬라이드별 순차/병렬 생성."""
    generated = 0
    failed = 0

    for task in tasks:
        slide_num = task["slide_num"]
        ar = task["aspect_ratio"]
        preview = task["prompt"][:220] + ("..." if len(task["prompt"]) > 220 else "")
        print(f"[슬라이드 {slide_num:02d} {ar}] 생성 중...")
        print(f"  프롬프트 ({len(task['prompt'])}자): {preview}")

        ok = generate_image_gemini(client, task["prompt"], task["output_path"], ar)
        if ok:
            generated += 1
        else:
            print(f"  [ERROR] 슬라이드 {slide_num:02d} {ar} 이미지 생성 실패")
            failed += 1
        time.sleep(1)

    return generated, failed


# ======================================================================
# 배치 모드 (Gemini Batch API — 50% 할인)
# ======================================================================

def run_batch(client, tasks, ep_dir):
    """배치 모드: JSONL 파일 → 업로드 → 배치 작업 → 폴링 → 이미지 저장.

    비용: 실시간 대비 50% 할인 ($0.039 → $0.0195/장)
    소요: 수분~수시간 (비동기 처리)
    """
    from google.genai import types

    if not tasks:
        print("[배치] 생성할 이미지가 없습니다.")
        return 0, 0

    # ------------------------------------------------------------------
    # 1. JSONL 파일 생성
    # ------------------------------------------------------------------
    jsonl_path = ep_dir / f"batch_images_{int(time.time())}.jsonl"
    task_map = {}  # key → task

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i, task in enumerate(tasks):
            key = f"slide_{task['slide_num']:02d}_{task['aspect_ratio'].replace(':', 'x')}"
            task_map[key] = task
            request = {
                "key": key,
                "request": {
                    "contents": [{"parts": [{"text": task["prompt"]}]}],
                    "generation_config": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {
                            "aspectRatio": task["aspect_ratio"],
                            "imageSize": "1K",
                        },
                    },
                },
            }
            f.write(json.dumps(request, ensure_ascii=False) + "\n")

    print(f"[배치] JSONL 생성 완료: {jsonl_path.name} ({len(tasks)}건)")
    print(f"[배치] 예상 비용: ${len(tasks) * 0.0195:.3f} (배치 50% 할인)")

    # ------------------------------------------------------------------
    # 2. 파일 업로드 & 배치 작업 생성
    # ------------------------------------------------------------------
    print("[배치] 파일 업로드 중...")
    uploaded_file = client.files.upload(
        file=str(jsonl_path),
        config=types.UploadFileConfig(
            display_name=f"batch-images-{ep_dir.name}",
            mime_type="jsonl",
        ),
    )
    print(f"[배치] 업로드 완료: {uploaded_file.name}")

    print("[배치] 배치 작업 생성 중...")
    batch_job = client.batches.create(
        model=f"models/{GEMINI_IMAGE_MODEL}",
        src=uploaded_file.name,
        config={"display_name": f"images-{ep_dir.name}"},
    )
    print(f"[배치] 작업 생성 완료: {batch_job.name}")
    print(f"[배치] 상태: {batch_job.state.name if hasattr(batch_job.state, 'name') else batch_job.state}")

    # ------------------------------------------------------------------
    # 3. 완료 대기 (폴링)
    # ------------------------------------------------------------------
    completed_states = {
        "JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED",
    }
    poll_interval = 15  # 초
    start_time = time.time()

    while True:
        state_name = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
        if state_name in completed_states:
            break

        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        print(f"\r[배치] 대기 중... {mins}분 {secs}초 (상태: {state_name})", end="", flush=True)
        time.sleep(poll_interval)
        batch_job = client.batches.get(name=batch_job.name)

    elapsed = int(time.time() - start_time)
    mins, secs = divmod(elapsed, 60)
    final_state = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
    print(f"\n[배치] 완료! 상태: {final_state} (소요: {mins}분 {secs}초)")

    # ------------------------------------------------------------------
    # 4. 결과 다운로드 & 이미지 저장
    # ------------------------------------------------------------------
    generated = 0
    failed = 0

    if final_state != "JOB_STATE_SUCCEEDED":
        print(f"[배치] 작업 실패: {final_state}")
        # JSONL 정리
        try:
            jsonl_path.unlink()
        except OSError:
            pass
        return 0, len(tasks)

    print("[배치] 결과 다운로드 중...")
    result_file_name = batch_job.dest.file_name
    file_content_bytes = client.files.download(file=result_file_name)

    if isinstance(file_content_bytes, bytes):
        file_content = file_content_bytes.decode("utf-8")
    else:
        file_content = str(file_content_bytes)

    for line in file_content.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            print(f"[배치] JSON 파싱 실패: {line[:100]}")
            failed += 1
            continue

        key = parsed.get("key", "")
        task = task_map.get(key)
        if not task:
            print(f"[배치] 알 수 없는 키: {key}")
            failed += 1
            continue

        # 이미지 데이터 추출
        img_bytes = None
        try:
            response = parsed.get("response", {})
            candidates = response.get("candidates", [])
            for candidate in candidates:
                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    inline_data = part.get("inlineData") or part.get("inline_data")
                    if inline_data and inline_data.get("data"):
                        img_bytes = base64.b64decode(inline_data["data"])
                        break
                if img_bytes:
                    break
        except Exception as e:
            print(f"[배치] {key} 이미지 추출 실패: {e}")

        if img_bytes:
            output_path = task["output_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_bytes)
            print(f"  [배치] {output_path.name} 저장 ({len(img_bytes):,} bytes)")
            generated += 1
        else:
            print(f"  [배치] {key} 이미지 데이터 없음")
            failed += 1

    # JSONL 임시 파일 정리
    try:
        jsonl_path.unlink()
    except OSError:
        pass

    return generated, failed


# ======================================================================
# 메인
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="슬라이드별 이미지 생성 (Gemini 2.5 Flash Image)",
        epilog="기본: 배치 모드 (50%% 할인). --realtime으로 즉시 생성 가능.",
    )
    parser.add_argument("--ep", type=int, default=None, help="에피소드 번호 (예: 1 → output/ep01)")
    parser.add_argument("--dir", type=str, default=None, help="출력 디렉터리 직접 지정 (예: output/bsl01)")
    parser.add_argument("--force", action="store_true", help="이미 존재하는 이미지도 재생성")
    parser.add_argument("--realtime", action="store_true", help="실시간 모드 (즉시 생성, 비용 2배)")
    parser.add_argument("--batch", action="store_true", default=True, help="배치 모드 (기본값, 50%% 할인)")
    args = parser.parse_args()

    # --realtime이 지정되면 batch 비활성화
    if args.realtime:
        args.batch = False

    if args.dir:
        ep_dir = Path(args.dir)
    elif args.ep is not None:
        ep_dir = Path(f"output/ep{args.ep:02d}")
    else:
        ep_dir = Path("output/ep01")
    story_path = ep_dir / "story.json"

    # ------------------------------------------------------------------
    # 1. story.json 읽기
    # ------------------------------------------------------------------
    if not story_path.exists():
        print(f"오류: {story_path} 파일을 찾을 수 없습니다.")
        print("먼저 스토리를 생성하세요.")
        return

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    slides = story.get("slides", [])
    meta = story.get("meta", {})

    mode_label = "배치 (Batch API, 50% 할인)" if args.batch else "실시간 (Realtime)"
    print(f"[{ep_dir}] {meta.get('story_title', '제목 없음')}")
    print(f"이미지 엔진: {GEMINI_IMAGE_MODEL}")
    print(f"모드: {mode_label}")
    print(f"총 {len(slides)}장 슬라이드")
    print()

    # ------------------------------------------------------------------
    # 2. Gemini 클라이언트 초기화
    # ------------------------------------------------------------------
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("오류: GEMINI_API_KEY가 .env에 설정되어 있지 않습니다.")
        return

    try:
        from google import genai
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "google-genai"], check=True)
        from google import genai

    client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # 3. 프롬프트 빌드
    # ------------------------------------------------------------------
    tasks, skipped = build_prompts(story, slides, ep_dir, force=args.force)

    if not tasks:
        print("생성할 이미지가 없습니다. (모두 건너뜀)")
        return

    print(f"생성 대상: {len(tasks)}건 | 건너뜀: {skipped}건")
    print()

    # ------------------------------------------------------------------
    # 4. 생성 실행
    # ------------------------------------------------------------------
    if args.batch:
        try:
            generated, failed = run_batch(client, tasks, ep_dir)
        except Exception as e:
            print(f"\n[배치] 배치 API 오류: {e}")
            print("[배치] 실시간 모드로 폴백합니다...")
            generated, failed = run_realtime(client, tasks)
    else:
        generated, failed = run_realtime(client, tasks)

    # ------------------------------------------------------------------
    # 5. 결과 요약
    # ------------------------------------------------------------------
    images_dir = ep_dir / "images"
    cost_per_image = 0.0195 if args.batch else 0.039
    print()
    print("=" * 50)
    print(f"  이미지 생성 완료 [{ep_dir}]")
    print("=" * 50)
    print(f"  모드: {mode_label}")
    print(f"  생성: {generated}장")
    print(f"  건너뜀: {skipped}장")
    print(f"  실패: {failed}장")
    print(f"  예상 비용: ${generated * cost_per_image:.3f}")
    print(f"  출력 폴더: {images_dir.absolute()}")
    print("=" * 50)


if __name__ == "__main__":
    main()
