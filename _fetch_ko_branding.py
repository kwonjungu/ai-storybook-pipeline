#!/usr/bin/env python3
"""한글 채널의 브랜딩(배너/프로필/설명란) 정보를 조회 (HAMZZI 채널에 동일 적용하기 위한 참고용)."""
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from publish_youtube import get_credentials
from googleapiclient.discovery import build

creds = get_credentials("ko")
yt = build("youtube", "v3", credentials=creds)
resp = yt.channels().list(part="snippet,brandingSettings", mine=True).execute()
item = resp["items"][0]
snippet = item["snippet"]
branding = item.get("brandingSettings", {})

out = {
    "title": snippet.get("title"),
    "description": snippet.get("description"),
    "thumbnails": snippet.get("thumbnails"),
    "banner": branding.get("image", {}),
    "channel_settings": branding.get("channel", {}),
}
print(json.dumps(out, ensure_ascii=False, indent=2))
