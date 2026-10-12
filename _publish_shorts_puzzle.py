"""숏츠 퍼즐(09c 결과) 단독 예약 업로드 — 한국어 채널.

  python _publish_shorts_puzzle.py --dir output/폴더 --schedule 2026-10-14T18:00:00+09:00 [--dry-run]

- 본편보다 먼저 공개되면 안 된다: 본편 publish_log 의 youtube_scheduled 이후 시각만 허용
- 제목 = shorts_puzzle.json title_candidates[0], 설명란 첫 줄 = 본편 링크 (현재 publish_log 의 youtube_url 로 다시 채움)
- 결과는 publish_log.json 의 shorts_puzzle_video_id / shorts_puzzle_scheduled 에 기록 (이미 있으면 건너뜀)
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

import publish_youtube as pub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir)
    sp = json.loads((d / "shorts_puzzle.json").read_text(encoding="utf-8"))
    story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    log_path = d / "publish_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    if log.get("shorts_puzzle_video_id"):
        print(f"[SKIP] 이미 업로드됨 {log['shorts_puzzle_video_id']}"); return
    main_url = log["youtube_url"]
    main_at = log.get("youtube_scheduled")
    if main_at and datetime.fromisoformat(a.schedule) <= datetime.fromisoformat(main_at):
        sys.exit(f"[중단] 숏츠 {a.schedule} 가 본편 공개 {main_at} 보다 이르다")

    meta = story.get("meta", {})
    title = sp["title_candidates"][0][:100]
    grade = meta.get("grade", 1)
    desc = (f"▶ 본편 보러 가기: {main_url}\n\n"
            f"{sp.get('story_title', meta.get('story_title', ''))} — 햄찌쌤의 짧은 놀이 퀴즈!\n"
            f"정답 이야기는 본편에서 만나요.\n\n"
            f"📚 {meta.get('subject', '')} | {meta.get('unit_title', '')}\n🎯 초등학교 {grade}학년\n\n"
            f"#Shorts #초등동화 #{grade}학년 #{meta.get('story_title', '').replace(' ', '')}")
    print(f"제목: {title}\n예약: {a.schedule}  (본편 {main_at})\n{desc}")
    if a.dry_run:
        return

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = pub.get_credentials("ko")
    pub.verify_channel("ko", creds)   # 우회 금지
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title, "description": desc, "categoryId": "27", "defaultLanguage": "ko",
                        "tags": ["Shorts", f"초등{grade}학년", "초등동화", "어린이퀴즈", meta.get("story_title", "")]},
            "status": {"privacyStatus": "private", "publishAt": a.schedule, "selfDeclaredMadeForKids": True}}
    media = MediaFileUpload(str(d / "shorts_puzzle.mp4"), chunksize=4 * 1024 * 1024, resumable=True)
    vid = pub.resumable_upload(yt.videos().insert(part="snippet,status", body=body, media_body=media), "숏츠 업로드")["id"]
    log["shorts_puzzle_video_id"], log["shorts_puzzle_scheduled"] = vid, a.schedule
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 숏츠 https://youtu.be/{vid} 예약 {a.schedule}")


if __name__ == "__main__":
    main()
