#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_push_thumb_c_all.py
한국어 채널의 모든 편에 새 thumbnail_c.png 를 일괄 반영.

2026-09-14: 스타일 C 규칙(상반신 클로즈업)을 안 지킨 배경 21장을 _crop_thumb_c_bg.py 로
재조립하고 10_generate_thumbnail --style c 로 다시 렌더한 뒤, 라이브 영상에 소급 적용하기 위해 만듦.
썸네일 교체는 영상 재업로드가 필요 없다(=URL·조회수 유지).

  python _push_thumb_c_all.py --dry-run
  python _push_thumb_c_all.py
  python _push_thumb_c_all.py --only 저금통
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

LANG_SUFFIXES = ("_en", "_id", "_pt", "_es")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = []
    for plog in sorted(Path("output").glob("*/publish_log.json")):
        d = plog.parent
        if any(d.name.endswith(s) for s in LANG_SUFFIXES):
            continue
        if args.only and args.only not in d.name:
            continue
        thumb = d / "thumbnail_c.png"
        vid = json.loads(plog.read_text(encoding="utf-8")).get("youtube_video_id")
        if thumb.exists() and vid:
            targets.append((d, vid, thumb))

    print(f"[INFO] 대상 {len(targets)}편\n")
    for d, vid, _ in targets:
        print(f"  {vid}  {d.name[:50]}")
    if args.dry_run:
        print("\n(--dry-run: 실제 반영 안 함)")
        return

    # SSL 순단(SSLEOFError)이 잦아 인증·요청 모두 재시도로 감싼다
    import time

    def with_retry(fn, what, tries=4):
        last = None
        for a in range(tries):
            try:
                return fn()
            except Exception as e:
                last = e
                print(f"    [재시도 {a+1}/{tries}] {what}: {str(e)[:80]}")
                time.sleep(3 * (a + 1))
        raise last

    creds = with_retry(lambda: py.get_credentials("ko"), "인증")
    with_retry(lambda: py.verify_channel("ko", creds), "채널확인")
    yt = build("youtube", "v3", credentials=creds)

    ok = fail = 0
    for i, (d, vid, thumb) in enumerate(targets, 1):
        try:
            with_retry(
                lambda: yt.thumbnails().set(
                    videoId=vid, media_body=MediaFileUpload(str(thumb))).execute(),
                f"썸네일 {vid}")
            print(f"[{i}/{len(targets)}] OK   {vid} <- {d.name[:42]}")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(targets)}] FAIL {vid}: {str(e)[:120]}")
            fail += 1

    print(f"\n=== 반영 {ok}건 / 실패 {fail}건 ===")


if __name__ == "__main__":
    main()
