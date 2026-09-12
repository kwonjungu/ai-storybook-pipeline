# -*- coding: utf-8 -*-
"""
10b_batch_thumb_bg.py
=====================
썸네일 스타일 C 의 '배경' 이미지를 Gemini 배치 API 로 일괄 생성한다.
(02_generate_images.py 배치 패턴 재사용, 모델 gemini-2.5-flash-image, 16:9, 1K)

- 대상: output/*/publish_log.json 이 존재하는 폴더 (에코의탐험복찾기 제외)
- 레퍼런스: characters/main_1.png, main_2.png
- 프롬프트: 두 주인공 상반신 클로즈업, thumbnail.emotion 표정, 얼굴 60%+,
            밝은 수채화풍, 텍스트 없음, 풀블리드. 왼쪽 55% 캐릭터 / 오른쪽 단순 배경.
- 출력: {폴더}/thumbnail_c_bg.png
- 배치 제출 → 폴링 → 저장. 성공 상태여도 저장 누락 가능 → 완료 후 파일검사, 누락분 재제출.
- 네트워크 재시도 루프. 장시간 폴링은 python -u + 로그파일로 detached 실행 가능.

사용:
  python -u 10b_batch_thumb_bg.py
  python 10b_batch_thumb_bg.py --only 초능력
  python 10b_batch_thumb_bg.py --force        # 기존 bg 도 재생성
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
EXCLUDE_KEYWORD = "에코의탐험복찾기"
BG_NAME = "thumbnail_c_bg.png"

EMOTION_WORDS = {
    "surprised": "wide-eyed astonished, mouths open in awe",
    "happy": "bright cheerful smiling, sparkling eyes",
    "sad": "gentle teary worried eyes, soft frown",
    "angry": "determined frowning, energetic",
    "worried": "curious anxious, slightly furrowed brows",
}


def build_prompt(story: dict) -> str:
    meta = story.get("meta", {})
    thumb = story.get("thumbnail", {})
    emotion = thumb.get("emotion", "happy")
    emo_desc = EMOTION_WORDS.get(emotion, "bright cheerful expressive")
    chars = meta.get("characters", {})
    names = []
    for k in ("main_1", "main_2"):
        ch = chars.get(k) or {}
        if ch.get("name"):
            names.append(ch["name"])
    who = " and ".join(names) if names else "the two main characters"

    return (
        f"YouTube thumbnail background, 16:9. An upper-body close-up of {who}, "
        f"the two main characters shown in the attached character sheets. "
        f"Keep their exact same design, colors and art style as the reference sheets. "
        f"Expression: {emo_desc}. Their faces and shoulders fill at least 60% of the frame. "
        f"Place the two characters on the LEFT 55% of the image; leave the RIGHT side a "
        f"simple, softly blurred background (open space for a text overlay to be added later). "
        f"Bright, vivid, clean soft-watercolor children's picture-book style. "
        f"NO text, NO letters, NO words anywhere in the image. "
        f"Full-bleed illustration, NO white borders, NO frames, NO letterboxing, NO vignette."
    )


def target_dirs(only=None, force=False):
    dirs = []
    for pl in sorted(Path("output").glob("*/publish_log.json")):
        d = pl.parent
        if EXCLUDE_KEYWORD in d.name:
            continue
        if only and only not in d.name:
            continue
        if (d / BG_NAME).exists() and not force:
            continue
        # 레퍼런스 존재 확인
        if not (d / "characters" / "main_1.png").exists():
            print(f"  [SKIP] {d.name}: characters/main_1.png 없음")
            continue
        dirs.append(d)
    return dirs


def ref_inline_parts(ref_paths, cache):
    parts = []
    for p in ref_paths:
        p = str(p)
        if p not in cache:
            try:
                cache[p] = base64.b64encode(Path(p).read_bytes()).decode("ascii")
            except Exception as e:
                print(f"  [WARN] 레퍼런스 로드 실패 ({Path(p).name}): {e}")
                cache[p] = None
        if cache[p]:
            parts.append({"inlineData": {"mimeType": "image/png", "data": cache[p]}})
    return parts


def submit_batch(client, tasks):
    """tasks: list of dict {key, prompt, ref_paths, output_path}. 저장 성공 key set 반환."""
    from google.genai import types

    jsonl_path = Path(f"batch_thumbc_{int(time.time())}.jsonl")
    task_map = {}
    cache = {}
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for t in tasks:
            task_map[t["key"]] = t
            parts = ref_inline_parts(t["ref_paths"], cache) + [{"text": t["prompt"]}]
            req = {
                "key": t["key"],
                "request": {
                    "contents": [{"parts": parts}],
                    "generation_config": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": "16:9", "imageSize": "1K"},
                    },
                },
            }
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    print(f"[배치] JSONL 생성: {jsonl_path.name} ({len(tasks)}건)")

    # 업로드 (재시도)
    uploaded = None
    for attempt in range(5):
        try:
            uploaded = client.files.upload(
                file=str(jsonl_path),
                config=types.UploadFileConfig(display_name="batch-thumbc", mime_type="jsonl"),
            )
            break
        except Exception as e:
            print(f"[배치] 업로드 재시도 {attempt+1}/5: {e}")
            time.sleep(min(2 ** attempt, 30))
    if uploaded is None:
        jsonl_path.unlink(missing_ok=True)
        return set()

    batch_job = client.batches.create(
        model=f"models/{GEMINI_IMAGE_MODEL}",
        src=uploaded.name,
        config={"display_name": "thumbc-bg"},
    )
    print(f"[배치] 작업 생성: {batch_job.name}")

    completed = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
    poll_errors = 0
    start = time.time()
    while True:
        state = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
        if state in completed:
            break
        el = int(time.time() - start)
        print(f"\r[배치] 대기 {el//60}분 {el%60}초 (상태: {state})", end="", flush=True)
        time.sleep(15)
        try:
            batch_job = client.batches.get(name=batch_job.name)
            poll_errors = 0
        except Exception as e:
            poll_errors += 1
            print(f"\n[배치] 폴링 오류 {poll_errors}/10: {e} — 15초 후 재시도")
            if poll_errors >= 10:
                raise

    final = batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)
    print(f"\n[배치] 완료: {final}")
    saved = set()
    if final != "JOB_STATE_SUCCEEDED":
        jsonl_path.unlink(missing_ok=True)
        return saved

    # 결과 다운로드 (재시도)
    content = None
    for attempt in range(5):
        try:
            raw = client.files.download(file=batch_job.dest.file_name)
            content = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            break
        except Exception as e:
            print(f"[배치] 결과 다운로드 재시도 {attempt+1}/5: {e}")
            time.sleep(min(2 ** attempt, 30))
    if content is None:
        jsonl_path.unlink(missing_ok=True)
        return saved

    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = parsed.get("key", "")
        t = task_map.get(key)
        if not t:
            continue
        img_bytes = None
        try:
            for cand in parsed.get("response", {}).get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    idata = part.get("inlineData") or part.get("inline_data")
                    if idata and idata.get("data"):
                        img_bytes = base64.b64decode(idata["data"])
                        break
                if img_bytes:
                    break
        except Exception as e:
            print(f"  [배치] {key} 추출 실패: {e}")
        if img_bytes:
            t["output_path"].parent.mkdir(parents=True, exist_ok=True)
            t["output_path"].write_bytes(img_bytes)
            print(f"  [저장] {t['output_path']}  ({len(img_bytes):,} bytes)")
            saved.add(key)
        else:
            print(f"  [배치] {key} 이미지 데이터 없음")

    jsonl_path.unlink(missing_ok=True)
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-rounds", type=int, default=3, help="누락분 재제출 최대 라운드")
    args = ap.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 없음 (.env)")
        sys.exit(1)
    from google import genai
    client = genai.Client(api_key=api_key)

    dirs = target_dirs(args.only, args.force)
    print(f"[INFO] 대상 폴더 {len(dirs)}개")
    if not dirs:
        print("[INFO] 생성할 배경 없음 (모두 존재하거나 대상 없음)")
        return

    # 태스크 구성
    def make_tasks(dir_list):
        tasks = []
        for d in dir_list:
            story = json.loads((d / "story.json").read_text(encoding="utf-8"))
            refs = [d / "characters" / "main_1.png"]
            m2 = d / "characters" / "main_2.png"
            if m2.exists():
                refs.append(m2)
            tasks.append({
                "key": d.name,
                "prompt": build_prompt(story),
                "ref_paths": refs,
                "output_path": d / BG_NAME,
            })
        return tasks

    pending = dirs
    for rnd in range(1, args.max_rounds + 1):
        tasks = make_tasks(pending)
        print(f"\n=== 라운드 {rnd}: {len(tasks)}건 제출 ===")
        saved = submit_batch(client, tasks)
        # 파일 존재 검사로 실제 누락분 확인 (성공 상태여도 저장 누락 가능)
        still_missing = [d for d in pending if not (d / BG_NAME).exists()]
        print(f"[라운드 {rnd}] 저장 {len(saved)} / 누락 {len(still_missing)}")
        if not still_missing:
            break
        pending = still_missing

    done = [d for d in dirs if (d / BG_NAME).exists()]
    missing = [d for d in dirs if not (d / BG_NAME).exists()]
    print(f"\n[완료] 성공 {len(done)} / 누락 {len(missing)}")
    if missing:
        print("[누락 목록]")
        for d in missing:
            print("  -", d.name)


if __name__ == "__main__":
    main()
