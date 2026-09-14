#!/usr/bin/env python3
"""publish_log.json의 video_id에 thumbnail_c.png를 라이브로 반영 (없으면 스킵)."""
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from publish_youtube import get_credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ep_dir = Path(sys.argv[1])
thumb_c = ep_dir / "thumbnail_c.png"
plog = ep_dir / "publish_log.json"

if not thumb_c.exists():
    print(f"[SKIP] thumbnail_c.png 없음: {ep_dir}")
    sys.exit(0)
if not plog.exists():
    print(f"[SKIP] publish_log.json 없음: {ep_dir}")
    sys.exit(0)

vid = json.loads(plog.read_text(encoding="utf-8")).get("youtube_video_id")
if not vid:
    print(f"[SKIP] video_id 없음: {ep_dir}")
    sys.exit(0)

creds = get_credentials("ko")
yt = build("youtube", "v3", credentials=creds)
yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb_c))).execute()
print(f"[OK] {vid} <- {thumb_c}")
