# -*- coding: utf-8 -*-
"""채널 현황 감사: 채널 통계 + 전체 업로드 영상 메타 + 재생목록 덤프"""
import json, sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

tok_data = json.loads(Path("token_ko.json").read_text(encoding="utf-8"))
SCOPES = tok_data.get("scopes")

creds = Credentials.from_authorized_user_file("token_ko.json", SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

yt = build("youtube", "v3", credentials=creds)

ch = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
c = ch["items"][0]
out = {
    "channel": {
        "title": c["snippet"]["title"],
        "description": c["snippet"].get("description", ""),
        "publishedAt": c["snippet"]["publishedAt"],
        "stats": c["statistics"],
        "customUrl": c["snippet"].get("customUrl"),
    },
    "videos": [],
    "playlists": [],
}
uploads = c["contentDetails"]["relatedPlaylists"]["uploads"]

vids = []
tok = None
while True:
    r = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50, pageToken=tok).execute()
    vids += [i["contentDetails"]["videoId"] for i in r["items"]]
    tok = r.get("nextPageToken")
    if not tok:
        break

for i in range(0, len(vids), 50):
    r = yt.videos().list(part="snippet,statistics,status,contentDetails", id=",".join(vids[i:i+50])).execute()
    for v in r["items"]:
        sn, st, s2 = v["snippet"], v.get("statistics", {}), v["status"]
        out["videos"].append({
            "id": v["id"],
            "title": sn["title"],
            "publishedAt": sn["publishedAt"],
            "privacy": s2["privacyStatus"],
            "duration": v["contentDetails"]["duration"],
            "views": st.get("viewCount"),
            "likes": st.get("likeCount"),
            "comments": st.get("commentCount"),
            "tags": sn.get("tags", [])[:10],
            "thumb": sn["thumbnails"].get("high", {}).get("url"),
            "desc_head": sn.get("description", "")[:400],
        })

tok = None
while True:
    r = yt.playlists().list(part="snippet,contentDetails,status", mine=True, maxResults=50, pageToken=tok).execute()
    for p in r["items"]:
        out["playlists"].append({
            "id": p["id"], "title": p["snippet"]["title"],
            "count": p["contentDetails"]["itemCount"],
            "privacy": p["status"]["privacyStatus"],
        })
    tok = r.get("nextPageToken")
    if not tok:
        break

Path("_channel_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
pub = [v for v in out["videos"] if v["privacy"] == "public"]
print(f"channel={out['channel']['title']} subs={out['channel']['stats'].get('subscriberCount')} views={out['channel']['stats'].get('viewCount')} videos_total={len(out['videos'])} public={len(pub)} playlists={len(out['playlists'])}")
