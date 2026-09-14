#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_attach_thumb_batch.py
이미 제출된 썸네일 배경 배치(batches/...)에 다시 붙어서 결과만 저장한다.

쓰는 상황: 10b_batch_thumb_bg.py 를 백그라운드로 돌렸는데 폴링 프로세스만 죽은 경우.
배치 자체는 서버에서 계속 돌기 때문에, 새로 제출(=재과금)하지 말고 이 스크립트로 회수한다.
key 는 output 폴더명이고 저장 위치는 output/<key>/thumbnail_c_bg.png (10b와 동일 규약).

  python _attach_thumb_batch.py batches/4cnacl7f9qd94aa4w1t4m644yjhyimicsn6s
  python _attach_thumb_batch.py --latest     # 가장 최근 thumbc-bg 배치
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
DONE = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def state_of(job):
    return job.state.name if hasattr(job.state, "name") else str(job.state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default=None, help="batches/... 이름")
    ap.add_argument("--latest", action="store_true", help="가장 최근 thumbc-bg 배치 사용")
    args = ap.parse_args()

    name = args.name
    if args.latest or not name:
        cands = [b for b in client.batches.list(config={"page_size": 20})
                 if (getattr(b, "display_name", "") or "") == "thumbc-bg"]
        if not cands:
            print("[ERROR] thumbc-bg 배치를 찾지 못했습니다"); sys.exit(1)
        name = cands[0].name
        print(f"[INFO] 최근 배치 사용: {name}")

    job = client.batches.get(name=name)
    start = time.time()
    while state_of(job) not in DONE:
        el = int(time.time() - start)
        print(f"\r[배치] 대기 {el//60}분 {el%60}초 (상태: {state_of(job)})", end="", flush=True)
        time.sleep(15)
        try:
            job = client.batches.get(name=name)
        except Exception as e:
            print(f"\n[배치] 폴링 오류: {e} — 재시도")

    final = state_of(job)
    print(f"\n[배치] 완료: {final}")
    if final != "JOB_STATE_SUCCEEDED":
        sys.exit(1)

    raw = client.files.download(file=job.dest.file_name)
    content = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    saved = missing = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = parsed.get("key", "")
        out_dir = Path("output") / key
        if not out_dir.is_dir():
            print(f"  [SKIP] 폴더 없음: {key}")
            continue
        img = None
        for cand in parsed.get("response", {}).get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                idata = part.get("inlineData") or part.get("inline_data")
                if idata and idata.get("data"):
                    img = base64.b64decode(idata["data"])
                    break
            if img:
                break
        if img:
            # 기존 배경은 _prev 로 한 번 보존 (되돌릴 수 있게)
            dst = out_dir / "thumbnail_c_bg.png"
            prev = out_dir / "thumbnail_c_bg_prev.png"
            if dst.exists() and not prev.exists():
                prev.write_bytes(dst.read_bytes())
            dst.write_bytes(img)
            print(f"  [저장] {key}  ({len(img):,} bytes)")
            saved += 1
        else:
            print(f"  [없음] {key} — 이미지 데이터 없음")
            missing += 1

    print(f"\n=== 저장 {saved}건 / 누락 {missing}건 ===")
    if missing:
        print("누락분은 python 10b_batch_thumb_bg.py --from-audit 로 재제출하세요")


if __name__ == "__main__":
    main()
