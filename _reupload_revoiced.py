#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_reupload_revoiced.py
teacher 보이스를 재캐스팅해 다시 조립한 6편을 유튜브에 재업로드.

배경: 2026-09-12 _audit_voice_gender.py 로 'teacher' 화자가 전부 Hyunseung(젊은 남성)으로
      깔려 있어 '부엉 할머니', '포근 아줌마' 같은 배역까지 남성 목소리였던 걸 잡아냈다.
      _revoice_teacher.py 로 재캐스팅(Ilho/Emma/Seohyeon/Hakchul) → 오디오·영상까지
      다시 만들어 뒀지만 업로드가 안 된 상태였다.

유튜브는 올라간 영상의 파일 교체가 불가능하므로:
  새 영상 업로드 -> 재생목록 교체 -> 구버전 private -> publish_log.json 갱신

  python _reupload_revoiced.py --dry-run   # 무엇이 바뀔지만 출력
  python _reupload_revoiced.py             # 실제 수행
  python _reupload_revoiced.py --only 저금통
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import publish_youtube as py
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TARGETS = [
    "통합교과_세상을바꿀초능력이생긴다면38_1학년_함께골라요_삐요와토토별똥별초능력",
    "통합교과_하늘의하루2223p_1학년_함께골라요_삐요와토토하늘의색을세어봐요",
    "통합교과_물건이악기가된다면3637p_1학년_함께골라요_통통이와두리의둥둥팅팅음악회",
    "통합교과_하루세번3637p_1학년_함께골라요_까까와냠냠의골고루하루",
    "통합교과_하루의리듬4041p_1학년_함께골라요_통통이와짤랑이의하루리듬",
    "통합교과_하루저금통3031p_1학년_함께골라요_삐요와토토의반짝반짝하루저금통",
]

# 본편이 소속될 수 있는 재생목록 (하루 / 상상 / 학부모용 잠자리)
PLAYLISTS = ["PLbfFBJVMkIK0", "PLD7saDT0aReU", "PLE6j04849ZfA"]

LOG_PATH = ROOT / "_revoice_reupload_log.json"


def find_playlist_items(yt, video_id):
    """이 영상이 들어있는 (playlist_id, item_id, position) 목록."""
    found = []
    for pl in PLAYLISTS:
        token = None
        while True:
            resp = yt.playlistItems().list(part="id,contentDetails,snippet", playlistId=pl,
                                           maxResults=50, pageToken=token).execute()
            for it in resp.get("items", []):
                if it["contentDetails"]["videoId"] == video_id:
                    found.append((pl, it["id"], it["snippet"].get("position", 0)))
            token = resp.get("nextPageToken")
            if not token:
                break
    return found


def set_private(yt, video_id):
    cur = yt.videos().list(part="status", id=video_id).execute()["items"][0]["status"]
    body = {
        "id": video_id,
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": cur.get("selfDeclaredMadeForKids", True),
            "license": cur.get("license", "youtube"),
            "embeddable": cur.get("embeddable", True),
            "publicStatsViewable": cur.get("publicStatsViewable", True),
        },
    }
    yt.videos().update(part="status", body=body).execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="폴더명 부분 문자열로 대상 한정")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log = json.loads(LOG_PATH.read_text(encoding="utf-8")) if LOG_PATH.exists() else {}

    creds = py.get_credentials("ko")
    py.verify_channel("ko", creds)
    yt = build("youtube", "v3", credentials=creds)

    targets = [t for t in TARGETS if not args.only or args.only in t]
    for i, name in enumerate(targets, 1):
        if log.get(name, {}).get("new_video_id"):
            print(f"\n[SKIP] {i}/{len(targets)} 이미 재업로드됨: {log[name]['new_video_id']}")
            continue

        out_dir = ROOT / "output" / name
        plog_path = out_dir / "publish_log.json"
        if not plog_path.exists():
            print(f"[SKIP] publish_log.json 없음: {name}")
            continue
        plog = json.loads(plog_path.read_text(encoding="utf-8"))
        old_id = plog.get("youtube_video_id")
        story = json.loads((out_dir / "story.json").read_text(encoding="utf-8"))
        teacher = story["meta"].get("typecast_voices", {}).get("teacher", {}).get("name")
        sup = (story["meta"].get("characters", {}).get("supporting") or {}).get("teacher", {})

        print(f"\n{'='*70}\n[{i}/{len(targets)}] {name}")
        print(f"  구버전: https://youtu.be/{old_id}")
        print(f"  재캐스팅: teacher='{sup.get('name')}' -> {teacher}")

        pls = find_playlist_items(yt, old_id) if old_id else []
        print(f"  재생목록: {[p[0] for p in pls] or '없음'}")

        if args.dry_run:
            continue

        try:
            new_id = py.upload_video(
                out_dir, story,
                pptx_url=plog.get("pptx_drive_url"),
                worksheet_url=plog.get("worksheet_drive_url"),
                privacy="public",
                creds=creds,
            )

            # 썸네일 C가 있으면 그쪽으로 덮어쓰기 (upload_video는 thumbnail_a를 붙임)
            thumb_c = out_dir / "thumbnail_c.png"
            if thumb_c.exists():
                yt.thumbnails().set(videoId=new_id,
                                    media_body=MediaFileUpload(str(thumb_c))).execute()
                print("  [OK] 썸네일 C 적용")

            # 재생목록 교체 (구버전 항목 제거 -> 신버전 같은 자리 삽입)
            for pl, item_id, pos in pls:
                yt.playlistItems().insert(
                    part="snippet",
                    body={"snippet": {"playlistId": pl, "position": pos,
                                      "resourceId": {"kind": "youtube#video", "videoId": new_id}}},
                ).execute()
                yt.playlistItems().delete(id=item_id).execute()
                print(f"  [OK] 재생목록 교체: {pl} (position {pos})")

            # 구버전 비공개
            if old_id:
                set_private(yt, old_id)
                print(f"  [OK] 구버전 비공개: {old_id}")

            plog["youtube_video_id"] = new_id
            plog["youtube_url"] = f"https://youtu.be/{new_id}"
            plog["replaced_video_id"] = old_id
            plog["revoiced_teacher"] = f"{date.today()}: teacher -> {teacher}"
            plog_path.write_text(json.dumps(plog, ensure_ascii=False, indent=2), encoding="utf-8")

            log[name] = {"old_video_id": old_id, "new_video_id": new_id,
                         "teacher_voice": teacher, "done_at": str(date.today())}
            LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [완료] https://youtu.be/{new_id}")

        except Exception as e:
            print(f"  [ERROR] {name} 실패: {e}")
            log[name] = {"error": str(e)}
            LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            if "quotaExceeded" in str(e) or "uploadLimitExceeded" in str(e):
                print("\n[중단] 유튜브 일일 업로드 쿼터 초과 — 내일 다시 실행하면 남은 편부터 이어집니다.")
                break
            continue

    print("\n=== 재업로드 종료 ===")
    for k, v in log.items():
        print(k[:40], "->", v)


if __name__ == "__main__":
    main()
