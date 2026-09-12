# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')
from publish_youtube import get_credentials
from googleapiclient.discovery import build

TITLE = "1학년 2학기 통합교과 상상 (동화)"
DESC = "초등 1학년 2학기 통합교과 상상 단원 동화 시리즈. 문의: kdhdhdbdbr@gmail.com"

VIDEOS = [
    ("알에서 동물이 태어난다면", "9pesF2dl5eY"),
    ("상자에 물건이 들어 있다면", "9AqcliiRl0U"),
    ("함께 간다면", "DdICDrP4p3E"),
    ("여기저기에서 본다면", "0kiKw5v-yEc"),
    ("여러 가지 모양이 살아난다면", "g65g7cSi3as"),
    ("장난감이 춤을 춘다면", "8mfa5_DORlw"),
    ("새로운 동물이 나타난다면", "H2Dn_GDzGek"),
    ("비눗방울이 그림이 된다면", "RTAN1N_cc-M"),
    ("물건이 악기가 된다면", "ZLLDQbOsDS0"),
]

creds = get_credentials('ko')
yt = build('youtube', 'v3', credentials=creds)

# 1) 기존 재생목록 확인
pid = None
req = yt.playlists().list(part='snippet', mine=True, maxResults=50)
while req is not None:
    resp = req.execute()
    for it in resp.get('items', []):
        if it['snippet']['title'].strip() == TITLE:
            pid = it['id']
            break
    if pid:
        break
    req = yt.playlists().list_next(req, resp)

if pid:
    created = False
    print(f"[EXISTS] 기존 재생목록 발견: {pid}")
else:
    resp = yt.playlists().insert(
        part='snippet,status',
        body={'snippet': {'title': TITLE, 'description': DESC},
              'status': {'privacyStatus': 'public'}}
    ).execute()
    pid = resp['id']
    created = True
    print(f"[CREATED] 새 재생목록 생성: {pid}")

# 2) 기존 항목 videoId 수집
existing = set()
req = yt.playlistItems().list(part='snippet', playlistId=pid, maxResults=50)
while req is not None:
    resp = req.execute()
    for it in resp.get('items', []):
        existing.add(it['snippet']['resourceId'].get('videoId'))
    req = yt.playlistItems().list_next(req, resp)

# 3) 순서대로 없는 것만 추가
added = 0
for title, vid in VIDEOS:
    if vid in existing:
        print(f"  [SKIP] 이미 있음: {title} ({vid})")
        continue
    yt.playlistItems().insert(
        part='snippet',
        body={'snippet': {'playlistId': pid,
                          'resourceId': {'kind': 'youtube#video', 'videoId': vid}}}
    ).execute()
    added += 1
    print(f"  [ADD] {title} ({vid})")

print("=" * 40)
print(f"RESULT created={created} pid={pid} added={added} total_target={len(VIDEOS)}")
print(f"URL https://www.youtube.com/playlist?list={pid}")
