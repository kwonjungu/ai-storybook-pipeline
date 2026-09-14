#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_push_thumb_en.py
HAMZZI(영어) 채널에 이미 올라간 영상들의 썸네일을 일괄 적용/재적용.

배경: 신규 채널은 전화 인증 전까지 맞춤 썸네일 업로드가 막혀 있어서
      (403 "doesn't have permissions to upload and set custom video thumbnails")
      업로드는 되지만 썸네일만 자동 생성본으로 남는다.
      → https://www.youtube.com/verify 에서 채널 인증 후 이 스크립트를 한 번 돌리면 된다.

  python _push_thumb_en.py            # _en_batch_log.json 의 전 영상에 thumbnail_c(없으면 a) 적용
  python _push_thumb_en.py --only 알에서   # 폴더명에 해당 문자열이 포함된 편만
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import publish_youtube as py
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

LOG_PATH = ROOT / "_en_batch_log.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="폴더명 부분 문자열로 대상 한정")
    args = ap.parse_args()

    if not LOG_PATH.exists():
        print(f"[ERROR] {LOG_PATH.name} 없음"); sys.exit(1)
    log = json.loads(LOG_PATH.read_text(encoding="utf-8"))

    creds = py.get_credentials("en")
    py.verify_channel("en", creds)
    yt = build("youtube", "v3", credentials=creds)

    done = failed = 0
    for src_name, info in log.items():
        vid = info.get("video_id")
        if not vid:
            continue
        if args.only and args.only not in src_name:
            continue

        dst_dir = ROOT / "output" / f"{src_name}_en"
        thumb = dst_dir / "thumbnail_c.png"
        if not thumb.exists():
            thumb = dst_dir / "thumbnail_a.png"
        if not thumb.exists():
            print(f"[SKIP] 썸네일 없음: {dst_dir.name}")
            continue

        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            print(f"[OK] {vid} <- {dst_dir.name}/{thumb.name}")
            done += 1
        except Exception as e:
            print(f"[FAIL] {vid}: {e}")
            failed += 1

    print(f"\n=== 완료 {done}건 / 실패 {failed}건 ===")
    if failed:
        print("전부 403이면 아직 채널 인증 전입니다 → https://www.youtube.com/verify")


if __name__ == "__main__":
    main()
