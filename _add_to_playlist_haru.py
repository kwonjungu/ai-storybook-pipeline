# -*- coding: utf-8 -*-
"""하루 단원 재생목록(PLbfFBJVMkIK0)에 영상 추가 (중복 시 SKIP)."""
import sys
sys.path.insert(0, '.')
from publish_youtube import get_credentials
from googleapiclient.discovery import build

PLAYLIST_ID = "PLbfFBJVMkIK0"
VIDEOS = [(t, v) for t, v in (a.split('=', 1) for a in sys.argv[1:])]

creds = get_credentials('ko')
yt = build('youtube', 'v3', credentials=creds)

existing = set()
req = yt.playlistItems().list(part='snippet', playlistId=PLAYLIST_ID, maxResults=50)
while req is not None:
    resp = req.execute()
    for it in resp.get('items', []):
        existing.add(it['snippet']['resourceId'].get('videoId'))
    req = yt.playlistItems().list_next(req, resp)

added = 0
for title, vid in VIDEOS:
    if vid in existing:
        print("SKIP already-present %s %s" % (vid, title))
        continue
    yt.playlistItems().insert(
        part='snippet',
        body={'snippet': {'playlistId': PLAYLIST_ID,
                          'resourceId': {'kind': 'youtube#video', 'videoId': vid}}}
    ).execute()
    added += 1
    print("ADD %s %s" % (vid, title))

print("RESULT playlist=%s added=%d total_items=%d" % (PLAYLIST_ID, added, len(existing) + added))
print("URL https://www.youtube.com/playlist?list=%s" % PLAYLIST_ID)
