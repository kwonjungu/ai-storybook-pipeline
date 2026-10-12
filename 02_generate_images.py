#!/usr/bin/env python3
"""
02_generate_images.py
story.json의 각 슬라이드에 대해 Gemini 2.5 Flash Image API로 이미지를 생성합니다.

캐릭터 일관성 (multicultural-board 패턴 이식):
  Phase A. 캐릭터 시트(전신·정면·중립 포즈)를 먼저 생성 → characters/
  Phase B. 슬라이드 이미지 생성 시 해당 캐릭터 시트를 레퍼런스로 첨부
           + 프롬프트 최상단 STRICT 가드로 동일 디자인 강제

기본: Batch API (50% 할인, 비동기 처리, ~수분~수시간 소요)
옵션: --realtime (즉시 생성, 비용 2배)

사용법:
  python 02_generate_images.py --ep 3             # 배치 모드 (기본, 50% 할인)
  python 02_generate_images.py --ep 3 --realtime  # 실시간 모드 (즉시 생성)
  python 02_generate_images.py --dir output/bsl01 # 디렉터리 지정
  python 02_generate_images.py --ep 3 --no-char-ref  # 캐릭터 레퍼런스 없이 (구 방식)
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

# 슬라이드당 최대 캐릭터 레퍼런스 수 (요청 크기·품질 균형)
MAX_REFS_PER_IMAGE = 3

# 캐릭터 레퍼런스 사용 시 프롬프트 최상단에 삽입하는 STRICT 가드
# (문장 중간에 넣으면 무시되는 경향이 있어 반드시 맨 앞에 배치)
CHAR_REF_GUARD = (
    "CHARACTER REFERENCE (STRICT): The attached image(s) show the exact "
    "character design(s) for this story. Redraw the SAME character(s) in the "
    "new scene — identical species, body shape, colors, face, and "
    "clothing/accessories. Do NOT invent a different-looking character. "
)

# 글자 노출 방지 가드 — 반드시 프롬프트 최상단에 배치
# (기존에는 프롬프트 끝에만 붙였는데, 뒤쪽 지시는 무시되는 경향이 있어
#  꼬인 글자·간판·말풍선이 계속 새어 나왔다. 최상단 STRICT + 끝단 이중 앵커.)
NO_TEXT_GUARD = (
    "NO TEXT (STRICT): The image must contain ZERO text of any kind — "
    "no letters, no words, no numbers, no speech bubbles, no captions, "
    "no signs with writing, no logos, no watermarks, in ANY language "
    "including Korean and English. Blackboards, books, posters, labels and "
    "banners must be completely blank or show only abstract scribbles. "
)

# 화풍 고정 + 풀블리드 가드 (모든 슬라이드·시트 프롬프트에 결합)
# 슬라이드마다 치비체↔수채화체가 요동하는 문제와, 생성 이미지에 구워진 흰 테두리를 차단.
STYLE_GUARD = (
    "Soft watercolor children's picture-book style, rounded chibi proportions, "
    "EXACTLY the same rendering style as the attached character sheet. "
    "Same art style across ALL slides. "
    "Full-bleed illustration: NO white borders, NO frames, NO letterboxing, "
    "NO vignette. "
)

# 구도별 캐릭터 절대 크기 (프레임 높이 대비 %) — 슬라이드 간 크기 널뛰기 방지
# 절댓값을 명시해 앞뒤 장면의 캐릭터 스케일 점프를 억제한다.
SIZE_BY_COMPOSITION = {
    "wide_establishing": "the main characters' full bodies stand at about 30% of the frame height, clearly visible within the landscape",
    "birds_eye":         "the characters occupy about 30% of the frame height",
    "low_angle":         "the characters' full bodies at about 35% of the frame height",
    "silhouette":        "the characters' full bodies at about 35% of the frame height",
    "group_scene":       "each character stands at about 40% of the frame height",
    "full_body_action":  "the characters' full bodies at about 45% of the frame height",
    "detail_shot":       "the object of interest fills about 45% of the frame height, any visible characters at about 35%",
    "over_shoulder":     "the focus character at about 45% of the frame height",
    "medium_two_shot":   "the characters from the waist up fill about 55% of the frame height",
    "medium_shot":       "the characters from the waist up fill about 55% of the frame height",
    "close_up_face":     "the faces fill about 60% of the frame height, heads never cropped",
}
DEFAULT_SIZE_GUARD = "the main characters at about 40% of the frame height"

def size_guard_for(composition: str) -> str:
    rule = SIZE_BY_COMPOSITION.get(composition, DEFAULT_SIZE_GUARD)
    return (f" CHARACTER SCALE (STRICT): {rule}. Keep the characters' apparent "
            "size consistent with neighboring pages of the same book — "
            "no extreme size jumps between scenes, no extreme close-ups, "
            "characters never larger than 70% or smaller than 25% of frame height.")


# ======================================================================
# Phase A: 캐릭터 시트 선행 생성 (일관성 레퍼런스)
# ======================================================================

def collect_characters(story) -> dict:
    """meta.characters에서 시트 생성 대상 캐릭터를 수집합니다.
    Returns: {key: {"name": str, "appearance_en": str}}
    """
    characters = story.get("meta", {}).get("characters") or {}
    result = {}
    for key, val in characters.items():
        if key == "supporting":
            continue
        if isinstance(val, dict) and val.get("appearance_en"):
            result[key] = {
                "name": val.get("name_en") or val.get("name") or key,
                "appearance_en": val["appearance_en"],
            }
    for key, val in (characters.get("supporting") or {}).items():
        if isinstance(val, dict) and val.get("appearance_en"):
            result[f"supporting_{key}"] = {
                "name": val.get("name_en") or val.get("name") or key,
                "appearance_en": val["appearance_en"],
                "match_key": key,
            }
    return result


def build_char_sheet_prompt(info: dict) -> str:
    """전신 캐릭터 시트 프롬프트 (정면·중립 포즈·깨끗한 단색 배경)."""
    return (
        NO_TEXT_GUARD + STYLE_GUARD +
        f"Full-body character sheet of {info['name']}: {info['appearance_en']} "
        "Front view, standing, neutral friendly pose, whole body visible from "
        "head to toe, centered, clean solid soft pastel background, "
        "no other characters, no props, no text, no letters, no words. "
        "Children's picture book illustration style, bright clean natural "
        "colors, NEUTRAL to COOL color temperature, no yellow or amber cast."
    )


def generate_character_sheets(client, story, ep_dir, force=False) -> dict:
    """캐릭터 시트를 먼저 생성합니다 (실시간, 소량).
    Returns: {key: Path} — 생성/기존 시트 경로 맵
    """
    chars = collect_characters(story)
    if not chars:
        print("[캐릭터] meta.characters에 appearance_en 없음 — 캐릭터 시트 생략")
        return {}

    char_dir = ep_dir / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}

    print(f"[캐릭터] 시트 선행 생성 — {len(chars)}명 (일관성 레퍼런스)")
    for key, info in chars.items():
        sheet_path = char_dir / f"{key}.png"
        if sheet_path.exists() and not force:
            print(f"  {key:20s} — 이미 존재, 재사용")
            sheets[key] = sheet_path
            continue
        prompt = build_char_sheet_prompt(info)
        print(f"  {key:20s} ({info['name']}) 생성 중...")
        ok = generate_image_gemini(client, prompt, sheet_path, aspect_ratio="1:1")
        if ok:
            sheets[key] = sheet_path
        else:
            print(f"  [WARN] {key} 캐릭터 시트 생성 실패 — 해당 캐릭터는 텍스트 잠금만 적용")
        time.sleep(1)
    print()
    return sheets


def _refs_for_slide(image_prompt: str, chars: dict, char_sheets: dict, extra_text: str = "") -> list:
    """슬라이드에 등장하는 캐릭터의 시트 경로 목록 (최대 MAX_REFS_PER_IMAGE).
    main_* 캐릭터는 항상 포함, supporting은 프롬프트/나레이션에 언급될 때만.
    조연 이름이 한글이어도 잡도록 image_prompt + slide 나레이션(extra_text)을 함께 검색하고
    이름을 어절 단위로 매칭한다(예: '반디 할미' → '반디' 또는 '할미')."""
    refs = []
    hay = (image_prompt + " " + (extra_text or "")).lower()
    for key, path in char_sheets.items():
        info = chars.get(key, {})
        if key.startswith("main_"):
            refs.append(path)
            continue
        match_key = info.get("match_key", key)
        cands = [match_key.replace("_", " ").lower()]
        for tok in (info.get("name") or "").replace("_", " ").split():
            if len(tok) >= 2:
                cands.append(tok.lower())
        for tok in (info.get("name_en") or "").split():
            if len(tok) >= 2:
                cands.append(tok.lower())
        if any(c and c in hay for c in cands):
            refs.append(path)
    return refs[:MAX_REFS_PER_IMAGE]


# ======================================================================
# 프롬프트 빌드 (공통)
# ======================================================================

def build_prompts(story, slides, ep_dir, force=False, char_sheets=None):
    """슬라이드별 이미지 프롬프트를 빌드하고 생성 대상 목록을 반환한다.

    Returns:
        tasks: list of dict {slide_num, prompt, aspect_ratio, output_path, ref_paths}
        skipped: int
    """
    char_sheets = char_sheets or {}
    all_chars = collect_characters(story)
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
        # 캐릭터 절대 크기 가드 (구도별) — 슬라이드 간 스케일 일관성
        if "CHARACTER SCALE" not in image_prompt and slide.get("type") != "cover":
            image_prompt += size_guard_for(slide.get("composition", ""))

        # 캐릭터 레퍼런스 (Phase A에서 생성한 시트) + STRICT 가드 (반드시 최상단)
        slide_text = " ".join(seg.get("text", "") for seg in slide.get("tts_segments", []))
        ref_paths = _refs_for_slide(image_prompt, all_chars, char_sheets, slide_text)
        guard = (CHAR_REF_GUARD if ref_paths else "") + NO_TEXT_GUARD + STYLE_GUARD

        # 16:9 (기본)
        tasks.append({
            "slide_num": slide_num,
            "prompt": guard + image_prompt,
            "aspect_ratio": "16:9",
            "output_path": image_path,
            "ref_paths": ref_paths,
        })

        # 9:16 (Shorts용)
        if slide_num in shorts_slides:
            v_path = images_dir / f"slide_{slide_num:02d}_9x16.png"
            if v_path.exists() and not force:
                print(f"  [9:16] 이미 존재 — 건너뜀: {v_path.name}")
            else:
                vertical_prompt = (
                    guard +
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
                    "ref_paths": ref_paths,
                })

    return tasks, skipped


# ======================================================================
# 실시간 모드 (기존 방식)
# ======================================================================

def _load_ref_parts(ref_paths):
    """캐릭터 시트 파일 → google-genai Part 목록 (레퍼런스 먼저, 텍스트는 뒤)."""
    from google.genai import types
    parts = []
    for p in ref_paths or []:
        try:
            parts.append(types.Part.from_bytes(
                data=Path(p).read_bytes(), mime_type="image/png"))
        except Exception as e:
            print(f"    [WARN] 레퍼런스 로드 실패 ({Path(p).name}): {e}")
    return parts


def generate_image_gemini(client, prompt: str, output_path: Path,
                          aspect_ratio: str = "16:9",
                          max_retries: int = 3,
                          ref_paths: list = None) -> bool:
    """Gemini API로 이미지 생성 후 저장. 성공 시 True 반환.
    ref_paths가 있으면 캐릭터 시트를 레퍼런스로 첨부 (동일 디자인 유지)."""
    from google.genai import types

    ref_parts = _load_ref_parts(ref_paths)
    contents = ref_parts + [prompt] if ref_parts else prompt

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=contents,
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
        n_refs = len(task.get("ref_paths") or [])
        print(f"[슬라이드 {slide_num:02d} {ar}] 생성 중..." +
              (f" (캐릭터 레퍼런스 {n_refs}장)" if n_refs else ""))
        print(f"  프롬프트 ({len(task['prompt'])}자): {preview}")

        ok = generate_image_gemini(client, task["prompt"], task["output_path"], ar,
                                   ref_paths=task.get("ref_paths"))
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

    # 캐릭터 시트 base64 캐시 (여러 슬라이드가 같은 시트 공유)
    ref_b64_cache = {}

    def _ref_inline_parts(ref_paths):
        parts = []
        for p in ref_paths or []:
            p = str(p)
            if p not in ref_b64_cache:
                try:
                    ref_b64_cache[p] = base64.b64encode(Path(p).read_bytes()).decode("ascii")
                except Exception as e:
                    print(f"  [WARN] 레퍼런스 로드 실패 ({Path(p).name}): {e}")
                    ref_b64_cache[p] = None
            if ref_b64_cache[p]:
                parts.append({"inlineData": {"mimeType": "image/png",
                                             "data": ref_b64_cache[p]}})
        return parts

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i, task in enumerate(tasks):
            key = f"slide_{task['slide_num']:02d}_{task['aspect_ratio'].replace(':', 'x')}"
            task_map[key] = task
            # 레퍼런스 이미지 먼저, 텍스트는 마지막 (일관성 조건부 생성)
            parts = _ref_inline_parts(task.get("ref_paths")) + [{"text": task["prompt"]}]
            request = {
                "key": key,
                "request": {
                    "contents": [{"parts": parts}],
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

    poll_errors = 0
    while True:
        state_name = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
        if state_name in completed_states:
            break

        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        print(f"\r[배치] 대기 중... {mins}분 {secs}초 (상태: {state_name})", end="", flush=True)
        time.sleep(poll_interval)
        try:
            batch_job = client.batches.get(name=batch_job.name)
            poll_errors = 0
        except Exception as e:
            # 일시적 네트워크 오류(SSL EOF 등)는 재시도 — 실시간 폴백으로 넘기면
            # 서버의 배치 작업과 이중 과금이 발생함
            poll_errors += 1
            print(f"\n[배치] 폴링 오류 ({poll_errors}/10): {e} — {poll_interval}초 후 재시도")
            if poll_errors >= 10:
                raise

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
    parser.add_argument("--no-char-ref", action="store_true",
                        help="캐릭터 시트 선행 생성/레퍼런스 첨부 비활성화 (구 방식)")
    parser.add_argument("--force-chars", action="store_true",
                        help="캐릭터 시트도 강제 재생성 (주의: 캐릭터 디자인이 바뀜)")
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
    # 3. Phase A — 캐릭터 시트 선행 생성 (일관성 레퍼런스)
    # ------------------------------------------------------------------
    # 시트는 --force에도 보존 (캐릭터 정체성 앵커) — --force-chars 지정 시에만 재생성
    char_sheets = {}
    if not args.no_char_ref:
        char_sheets = generate_character_sheets(client, story, ep_dir,
                                                force=args.force_chars)

    # ------------------------------------------------------------------
    # 3b. Phase B — 슬라이드 프롬프트 빌드 (레퍼런스 연결)
    # ------------------------------------------------------------------
    tasks, skipped = build_prompts(story, slides, ep_dir, force=args.force,
                                   char_sheets=char_sheets)

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
    # 4b. 저장 전수 검증 + 누락분 자동 복구
    # 배치가 JOB_STATE_SUCCEEDED여도 1~2장이 조용히 저장 누락되는 사례가
    # 반복됨 → 파일 존재를 전수 대조하고, 빠진 슬라이드만 실시간 재생성.
    # ------------------------------------------------------------------
    missing = [t for t in tasks if not t["output_path"].exists()]
    if missing:
        print()
        print(f"[검증] 저장 누락 {len(missing)}건 감지 → 실시간 자동 재생성")
        for t in missing:
            print(f"  - {t['output_path'].name}")
        re_gen, _ = run_realtime(client, missing)
        generated += re_gen

    still_missing = [t for t in tasks if not t["output_path"].exists()]
    failed = len(still_missing)
    if still_missing:
        print(f"\n[검증] 자동 복구 후에도 {failed}건 누락: "
              + ", ".join(t["output_path"].name for t in still_missing))
    else:
        print(f"\n[검증] 대상 {len(tasks)}건 전부 저장 확인 (누락 0)")

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

    # 누락이 남으면 비정상 종료 → 후속 단계(06 조립 등)가 빈 슬라이드로
    # 조용히 진행되지 않도록 게이트 역할 (tts_gate와 같은 원칙)
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
