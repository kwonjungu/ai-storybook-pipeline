"""예약 업로드된 편을 고친 뒤 같은 예약 시각으로 갈아끼운다 (한국어 채널).

  python _reupload_fixed.py --dir output/폴더 [--dry-run]

1) book_1분할.pptx 를 기존 Drive 파일 ID에 덮어쓰기 (링크 불변)
2) 새 video.mp4 를 publish_log 의 youtube_scheduled 시각으로 예약 업로드 (기존 Drive 링크 재사용)
3) 기존 영상은 예약 해제 + 비공개 유지 (삭제 안 함)
4) publish_log 갱신, 옛 ID 는 replaced_video_ids 에 남김
"""
import argparse, json, re, sys
from pathlib import Path

import publish_youtube as pub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir)
    story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    log_path = d / "publish_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    old_id, sched = log["youtube_video_id"], log.get("youtube_scheduled")
    if not sched:
        sys.exit("[ERROR] 예약 업로드가 아닌 편 — 공개 영상은 이 스크립트로 바꾸지 않는다")
    pptx_url, ws_url = log.get("pptx_drive_url"), log.get("worksheet_drive_url")
    print(f"기존 {old_id}  예약 {sched}\n  PPT {pptx_url}\n  활동지 {ws_url}")
    if a.dry_run:
        return

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = pub.get_credentials("ko")
    pub.verify_channel("ko", creds)   # 우회 금지

    # 1) PPT 같은 ID 덮어쓰기
    pptx = d / "book_1분할.pptx"
    m = re.search(r"/d/([^/]+)", pptx_url or "")
    if pptx.exists() and m:
        try:
            import shrink_assets
            shrink_assets.shrink_pptx(pptx)
        except Exception as e:
            print(f"[SHRINK] 건너뜀: {e}")
        drive = build("drive", "v3", credentials=creds)
        media = MediaFileUpload(str(pptx), resumable=False,
                                mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation")
        pub.retry(lambda: drive.files().update(fileId=m.group(1), media_body=media).execute(), "Drive PPT 덮어쓰기")
        print(f"[Drive] PPT 덮어씀 (ID {m.group(1)})")

    # 2) 새 영상 예약 업로드
    new_id = pub.upload_video(d, story, pptx_url=pptx_url, worksheet_url=ws_url,
                              privacy="private", schedule_time=sched, creds=creds)
    if not new_id:
        sys.exit("[ERROR] 새 업로드 실패 — 기존 예약은 그대로 둠")

    # 4) 로그 먼저 갱신 (3이 실패해도 새 ID 는 남게)
    log.setdefault("replaced_video_ids", []).append(old_id)
    log["youtube_video_id"], log["youtube_url"] = new_id, f"https://youtu.be/{new_id}"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) 기존 영상 예약 해제 (비공개 유지)
    yt = build("youtube", "v3", credentials=creds)
    st = pub.retry(lambda: yt.videos().list(part="status", id=old_id).execute(), "기존 상태")["items"][0]["status"]
    body = {"privacyStatus": "private",
            "selfDeclaredMadeForKids": st.get("selfDeclaredMadeForKids", st.get("madeForKids", True))}
    for k in ("license", "embeddable", "publicStatsViewable"):
        if k in st:
            body[k] = st[k]
    pub.retry(lambda: yt.videos().update(part="status", body={"id": old_id, "status": body}).execute(), "기존 예약 해제")
    after = yt.videos().list(part="status", id=old_id).execute()["items"][0]["status"]
    print(f"[기존] {old_id} → {after.get('privacyStatus')}, publishAt={after.get('publishAt')}")
    print(f"[새] {new_id} 예약 {sched}")


if __name__ == "__main__":
    main()
