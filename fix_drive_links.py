# -*- coding: utf-8 -*-
"""⚠ 소급 재배포에 쓰지 말 것 — 새 Drive 파일을 만들고 설명란을 구 템플릿으로 덮어씀.
   활동지 교체는 _resync_worksheets.py (같은 파일 ID 덮어쓰기).
   이미 업로드된 영상에 대해 활동지PDF·책PPTX를 Drive에 올리고
   본편/Shorts 설명란에 링크를 사후 반영. (재업로드 없음)
   사용: python fix_drive_links.py --dir output/<폴더>
   --no-drive 로 올린 영상 보정용."""
import sys, json, argparse
sys.path.insert(0, '.')
from pathlib import Path
from publish_youtube import (get_credentials, upload_to_drive,
    upload_worksheet_to_drive, build_description)
from googleapiclient.discovery import build

ap = argparse.ArgumentParser()
ap.add_argument('--dir', required=True)
args = ap.parse_args()

ep = Path(args.dir)
story = json.load(open(ep / 'story.json', encoding='utf-8'))
log = json.load(open(ep / 'publish_log.json', encoding='utf-8'))
vid = log.get('youtube_video_id'); sid = log.get('shorts_video_id')
creds = get_credentials('ko')
yt = build('youtube', 'v3', credentials=creds)

pptx_url = None; ws_url = None
p = ep / 'book_1분할.pptx'
if p.exists():
    pptx_url = upload_to_drive(p, story, creds)
w = ep / 'worksheet.pdf'
if w.exists():
    ws_url = upload_worksheet_to_drive(w, story, creds)

desc = build_description(story, pptx_url, ws_url)

# 본편: 기존 snippet 유지하고 description만 교체
cur = yt.videos().list(part='snippet', id=vid).execute()['items'][0]['snippet']
cur['description'] = desc
yt.videos().update(part='snippet', body={'id': vid, 'snippet': cur}).execute()
print(f'[본편] 설명 갱신: {vid}')

# Shorts: 설명 끝에 PPT 링크 반영
if sid and pptx_url:
    scur = yt.videos().list(part='snippet', id=sid).execute()['items'][0]['snippet']
    base = scur.get('description', '')
    if pptx_url not in base:
        scur['description'] = base.rstrip() + f"\n\n📊 그림책 PPT → {pptx_url}"
        if ws_url and ws_url not in base:
            scur['description'] += f"\n📝 활동지 → {ws_url}"
        yt.videos().update(part='snippet', body={'id': sid, 'snippet': scur}).execute()
        print(f'[Shorts] 설명 갱신: {sid}')

log['pptx_drive_url'] = pptx_url
log['worksheet_drive_url'] = ws_url
json.dump(log, open(ep / 'publish_log.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'  PPT     : {pptx_url}')
print(f'  활동지  : {ws_url}')
