#!/usr/bin/env python3
"""
publish_youtube.py
==================
① Google Drive에 PPT 업로드 → 공유 링크 획득
② YouTube에 동화 영상 업로드 (설명에 PPT 링크 포함)

준비:
  1. Google Cloud Console → YouTube Data API v3 + Google Drive API 활성화
  2. OAuth 2.0 클라이언트 ID (데스크톱 앱) → client_secret.json 저장
  3. 첫 실행 시 브라우저 인증 → token.json 자동 저장

사용법:
  python publish_youtube.py --dir output/bsl08
  python publish_youtube.py --dir output/bsl08 --private
  python publish_youtube.py --dir output/bsl08 --schedule "2026-04-10T09:00:00+09:00"
  python publish_youtube.py --dir output/bsl08 --no-drive   # Drive 업로드 건너뜀
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

CLIENT_SECRET = Path("client_secret.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive.file",
]

# 채널별 토큰 파일
CHANNEL_TOKENS = {
    "ko": Path("token_ko.json"),   # 한국어 채널 (햄찌와 떠나는 동화 여행)
    "id": Path("token_id.json"),   # 인도네시아 채널
}


# ─────────────────────────────────────────────────
#  OAuth 인증 (채널별)
# ─────────────────────────────────────────────────

def get_credentials(channel: str = "ko"):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    token_file = CHANNEL_TOKENS.get(channel, Path(f"token_{channel}.json"))

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                print("[ERROR] client_secret.json 없음", file=sys.stderr)
                sys.exit(1)
            if channel == "id":
                print("\n[인증 안내] 브라우저에서 반드시 인도네시아 채널로 전환 후 승인하세요!")
                print("  YouTube Studio → 채널 전환 → 인도네시아 채널 선택 → 이 창 유지\n")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
        print(f"  [인증 저장] {token_file}")
    return creds


# ─────────────────────────────────────────────────
#  Google Drive 업로드
# ─────────────────────────────────────────────────

def upload_to_drive(pptx_path: Path, story: dict, creds) -> str:
    """
    PPT를 Drive에 업로드하고 '링크 있는 모든 사용자' 공유 설정.
    Returns: 공유 URL (https://drive.google.com/file/d/.../view)
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    meta = story.get("meta", {})
    story_title = meta.get("story_title", "동화")
    grade = meta.get("grade", 2)
    file_name = f"[{grade}학년] {story_title} - 그림책 PPT.pptx"

    drive = build("drive", "v3", credentials=creds)

    print(f"[Drive] PPT 업로드 중: {pptx_path.name} ({pptx_path.stat().st_size // 1024} KB)")

    file_metadata = {"name": file_name}
    media = MediaFileUpload(
        str(pptx_path),
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        resumable=True,
    )
    req = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,name",
    )
    uploaded = resumable_upload(req, "Drive PPT")
    file_id = uploaded["id"]

    # 링크 있는 모든 사용자에게 보기 권한 부여
    drive.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    share_url = f"https://drive.google.com/file/d/{file_id}/view"
    print(f"  [OK] Drive 업로드 완료 → {share_url}")
    return share_url


# ─────────────────────────────────────────────────
#  재개형 업로드 (네트워크 순단 내성)
# ─────────────────────────────────────────────────

def resumable_upload(request, label: str = "업로드"):
    """resumable next_chunk 루프 — 일시적 네트워크 오류는 지수 백오프로 재시도.
    (읽기 타임아웃/SSL 순단 한 번에 87MB 업로드 전체가 죽는 문제 방지)"""
    import time as _t
    response = None
    errors = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  {label} {int(status.progress() * 100)}%...", end="\r", flush=True)
            errors = 0
        except Exception as e:
            errors += 1
            if errors > 8:
                raise
            wait = min(2 ** errors, 60)
            print(f"\n  [재시도 {errors}/8] {label} 청크 실패: {str(e)[:80]} — {wait}초 대기")
            _t.sleep(wait)
    return response


# ─────────────────────────────────────────────────
#  YouTube 설명 빌드
# ─────────────────────────────────────────────────

def build_description(story: dict, pptx_url: str = None) -> str:
    meta = story.get("meta", {})
    grade = meta.get("grade", 2)
    semester = meta.get("semester", "")
    series = meta.get("series", "")
    subject_full = " ".join(str(x) for x in
                            [f"{grade}학년", f"{semester}학기" if semester else "",
                             meta.get("subject", ""), series] if x).strip()
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")
    sub_unit = meta.get("sub_unit", "")
    story_title = meta.get("story_title", "")

    slides = [s for s in story.get("slides", []) if s.get("type") == "story"]
    summary = " ".join(s["text"][:80] for s in slides[:3])

    chars = meta.get("characters", {})
    char_names = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key)
        if ch and ch.get("name"):
            char_names.append(ch["name"])

    edu_goals = meta.get("educational_goals", [])
    goal_lines = "\n".join(f"  • {g}" for g in edu_goals[:3]) if edu_goals else ""

    pptx_section = ""
    if pptx_url:
        pptx_section = f"""
📊 그림책 PPT 무료 다운로드
  👉 {pptx_url}
  (수업·가정학습용으로 자유롭게 사용하세요!)
"""

    return f"""🌟 {story_title}

{summary}...

━━━━━━━━━━━━━━━━━━
📚 교과: {subject_full}  |  {unit_title}
📖 차시: {sub_unit}
🎯 대상: 초등학교 {grade}학년
👥 주인공: {', '.join(char_names)}
━━━━━━━━━━━━━━━━━━
{goal_lines}
{pptx_section}
✏️ 무료 활동지(워크시트)는 블로그 포스트에서 받으세요!
📌 댓글로 문의해 주시면 빠르게 답변드립니다 😊

━━━━━━━━━━━━━━━━━━
#초등동화 #{grade}학년 #독후활동 #무료활동지 #{story_title.replace(' ', '')} #{subject} #그림책PPT
"""


def build_tags(story: dict) -> list[str]:
    meta = story.get("meta", {})
    grade = meta.get("grade", 2)
    story_title = meta.get("story_title", "")
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")
    return [
        f"초등{grade}학년", "초등동화", "독후활동", "무료활동지",
        story_title, subject, unit_title, "어린이동화", "교육동화",
        f"{grade}학년", "초등교육", "그림책PPT", "수업자료",
    ]


# ─────────────────────────────────────────────────
#  YouTube 업로드
# ─────────────────────────────────────────────────

def upload_video(
    out_dir: Path,
    story: dict,
    pptx_url: str = None,
    privacy: str = "public",
    schedule_time: str = None,
    creds=None,
) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video_path = out_dir / "video.mp4"
    thumbnail_path = out_dir / "thumbnail_a.png"
    if not video_path.exists():
        print(f"[ERROR] video.mp4 없음: {video_path}", file=sys.stderr)
        sys.exit(1)

    meta = story.get("meta", {})
    story_title = meta.get("story_title", "동화")
    grade = meta.get("grade", 2)

    # youtube_title 우선, 없으면 자동 생성
    youtube_title = meta.get("youtube_title", "")
    if not youtube_title:
        subject = meta.get("subject", "")
        unit_title = meta.get("unit_title", "")
        parts = [p for p in [subject, unit_title] if p]
        context = " | ".join(parts)
        youtube_title = f"{grade}학년 {context} | {story_title}" if context else f"[초등 {grade}학년 동화] {story_title}"
    title = youtube_title

    youtube = build("youtube", "v3", credentials=creds)

    # 아동 대상 콘텐츠 필수 선언 (COPPA)
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": True}
    if schedule_time:
        status_body["privacyStatus"] = "private"
        status_body["publishAt"] = schedule_time

    body = {
        "snippet": {
            "title":           title[:100],
            "description":     build_description(story, pptx_url),
            "tags":            build_tags(story)[:15],
            "categoryId":      "27",   # Education
            "defaultLanguage": "ko",
        },
        "status": status_body,
    }

    size_mb = video_path.stat().st_size // 1024 // 1024
    print(f"\n[YouTube] 업로드 시작: {video_path.name} ({size_mb} MB)")
    print(f"  제목: {title}")

    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = resumable_upload(request, "본편 업로드")
    video_id = response["id"]
    print(f"\n  [OK] 업로드 완료 → https://youtu.be/{video_id}")

    # 썸네일
    if thumbnail_path.exists():
        print("  썸네일 적용 중...", end=" ", flush=True)
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path))
        ).execute()
        print("OK")

    return video_id


# ─────────────────────────────────────────────────
#  Shorts 업로드
# ─────────────────────────────────────────────────

def upload_shorts(out_dir: Path, story: dict, main_video_id: str, pptx_url: str, creds) -> str:
    """shorts_smart_rank1.mp4 업로드. Returns video_id."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    shorts_path = out_dir / "shorts_smart_rank1.mp4"
    thumb_path  = out_dir / "shorts_thumbnail.png"

    if not shorts_path.exists():
        print(f"[SKIP] Shorts 파일 없음: {shorts_path.name}")
        return ""

    meta = story.get("meta", {})
    grade = meta.get("grade", 2)
    story_title = meta.get("story_title", "")
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")
    sub_unit = meta.get("sub_unit", "")

    # hook_text from shorts_plan.json
    hook = "놓치면 아쉬운 명장면!"
    plan_path = out_dir / "shorts_plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        hook = plan.get("hook_text", hook)

    title = f"{hook} 🎬 {story_title} #Shorts"

    pptx_line = f"\n📊 그림책 PPT → {pptx_url}" if pptx_url else ""
    description = f"""{hook}

{story_title}에서 가장 인상적인 장면!

━━━━━━━━━━━━━━━━━━
📚 {subject} | {unit_title}
📖 {sub_unit}
🎯 초등학교 {grade}학년
━━━━━━━━━━━━━━━━━━

🎬 풀영상 보기 → https://youtu.be/{main_video_id}{pptx_line}

#Shorts #초등동화 #{grade}학년 #{story_title.replace(' ','')} #초등교육
"""

    youtube = build("youtube", "v3", credentials=creds)
    size_mb = shorts_path.stat().st_size // 1024 // 1024
    print(f"\n[Shorts] 업로드 시작: {shorts_path.name} ({size_mb} MB)")
    print(f"  제목: {title[:60]}")

    media = MediaFileUpload(str(shorts_path), chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":           title[:100],
                "description":     description,
                "tags":            ["Shorts", f"초등{grade}학년", "초등동화", subject, story_title, "어린이동화"],
                "categoryId":      "27",
                "defaultLanguage": "ko",
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": True},
        },
        media_body=media,
    )

    response = resumable_upload(request, "Shorts 업로드")
    video_id = response["id"]
    print(f"\n  [OK] Shorts 완료 → https://youtu.be/{video_id}")

    if thumb_path.exists():
        print("  썸네일 적용 중...", end=" ", flush=True)
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb_path))
        ).execute()
        print("OK")

    return video_id


# ─────────────────────────────────────────────────
#  메인
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Drive PPT 업로드 + YouTube 영상/Shorts 업로드")
    parser.add_argument("--dir", dest="dir_path", required=True)
    parser.add_argument("--channel", default="ko", choices=["ko", "id", "en", "pt", "es"],
                        help="업로드 채널: ko=한국어, id=인도네시아, en=영어, pt=포르투갈, es=스페인 (기본: ko). "
                             "새 채널은 첫 실행 시 브라우저 인증 → token_<채널>.json 자동 저장")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--schedule", default=None,
                        help="예약 발행 (ISO 8601, 예: 2026-04-10T09:00:00+09:00)")
    parser.add_argument("--no-drive", action="store_true", help="Drive PPT 업로드 건너뜀")
    parser.add_argument("--shorts", action="store_true", help="Shorts도 함께 업로드")
    parser.add_argument("--yes", "-y", action="store_true", help="확인 프롬프트 건너뜀")
    args = parser.parse_args()

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("[ERROR] pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        sys.exit(1)

    out_dir = Path(args.dir_path)
    story_path = out_dir / "story.json"
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}", file=sys.stderr)
        sys.exit(1)
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)

    channel_names = {"ko": "한국어 채널 (햄찌와 떠나는 동화 여행)", "id": "인도네시아 채널", "pt": "포르투갈 채널", "en": "영어 채널", "es": "스페인어 채널"}
    ch_name = channel_names.get(args.channel, args.channel)
    print(f"\n업로드 대상 채널: {ch_name}")
    print(f"폴더: {args.dir_path}")
    print(f"Shorts: {'포함' if args.shorts else '미포함'}")
    if not args.yes:
        ans = input("\n업로드 진행할까요? (y/n): ").strip().lower()
        if ans != "y":
            print("취소됨.")
            sys.exit(0)

    # 인증 (채널별)
    creds = get_credentials(args.channel)

    # ① Drive PPT 업로드
    pptx_url = None
    if not args.no_drive:
        pptx_path = out_dir / "book_1분할.pptx"
        if pptx_path.exists():
            pptx_url = upload_to_drive(pptx_path, story, creds)
        else:
            print(f"[SKIP] PPT 없음: {pptx_path.name}")

    # ② 본편 YouTube 업로드
    privacy = "private" if (args.private or args.schedule) else "public"
    video_id = upload_video(
        out_dir, story,
        pptx_url=pptx_url,
        privacy=privacy,
        schedule_time=args.schedule,
        creds=creds,
    )

    # ③ Shorts 업로드 (--shorts 옵션 시에만)
    shorts_id = ""
    if args.shorts:
        shorts_id = upload_shorts(out_dir, story, video_id, pptx_url or "", creds)

    # publish_log.json 저장
    log_path = out_dir / "publish_log.json"
    log = {}
    if log_path.exists():
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    log["youtube_video_id"] = video_id
    log["youtube_url"] = f"https://youtu.be/{video_id}"
    if pptx_url:
        log["pptx_drive_url"] = pptx_url
    if shorts_id:
        log["shorts_video_id"] = shorts_id
        log["shorts_url"] = f"https://youtu.be/{shorts_id}"
    if args.schedule:
        log["youtube_scheduled"] = args.schedule
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"[완료] publish_log.json → {log_path}")
    print(f"  YouTube : https://youtu.be/{video_id}")
    if shorts_id:
        print(f"  Shorts  : https://youtu.be/{shorts_id}")
    if pptx_url:
        print(f"  PPT     : {pptx_url}")
    print(f"\n다음 단계: python publish_tistory.py --dir {args.dir_path}")


if __name__ == "__main__":
    main()
