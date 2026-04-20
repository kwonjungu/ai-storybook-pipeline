#!/usr/bin/env python3
"""
publish_tistory.py
==================
Tistory 내부 API (/manage/post.json) 기반 자동 포스팅.
Open API 종료 이후 쿠키 세션 방식으로 동작.

사용 전 준비:
  1. 브라우저에서 tistory.com 로그인
  2. 개발자도구(F12) → Application → Cookies → www.tistory.com
  3. TISTORY_TSESSION, TISTORY_TSESSION_MEMBER 값을 .env에 저장

.env 설정:
  TISTORY_BLOG_NAME=your-blog-name   (your-blog-name.tistory.com)
  TISTORY_CATEGORY_ID=0              (관리자 → 카테고리 → ID 확인)
  TISTORY_TSESSION=xxxxxxxx
  TISTORY_TSESSION_MEMBER=xxxxxxxx   (없으면 생략 가능)

사용법:
  python publish_tistory.py --dir output/bsl08
  python publish_tistory.py --dir output/bsl08 --draft   # 임시저장
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BLOG_NAME      = os.environ.get("TISTORY_BLOG_NAME", "")
CATEGORY_ID    = os.environ.get("TISTORY_CATEGORY_ID", "0")
TSESSION       = os.environ.get("TISTORY_TSESSION", "")
TSESSION_MB    = os.environ.get("TISTORY_TSESSION_MEMBER", "")


# ─────────────────────────────────────────────────
#  쿠키 세션 빌드
# ─────────────────────────────────────────────────

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://{BLOG_NAME}.tistory.com/manage/post",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.tistory.com",
    })
    cookies = {"TSESSION": TSESSION}
    if TSESSION_MB:
        cookies["TSESSION_MEMBER"] = TSESSION_MB
    s.cookies.update(cookies)
    return s


# ─────────────────────────────────────────────────
#  포스트 발행
# ─────────────────────────────────────────────────

def publish_post(
    title: str,
    html_content: str,
    tags: list[str] = None,
    category_id: str = None,
    draft: bool = False,
    slug: str = "",
) -> dict:
    """
    Returns: {"post_id": "...", "url": "..."}
    """
    if not TSESSION:
        print("[ERROR] TISTORY_TSESSION 미설정 (.env 확인)", file=sys.stderr)
        sys.exit(1)
    if not BLOG_NAME:
        print("[ERROR] TISTORY_BLOG_NAME 미설정 (.env 확인)", file=sys.stderr)
        sys.exit(1)

    session = build_session()
    url = "https://www.tistory.com/manage/post.json"

    data = {
        "blog":          BLOG_NAME,
        "title":         title,
        "content":       html_content,
        "contentType":   "html",
        "category":      category_id or CATEGORY_ID,
        "tag":           ",".join(tags or []),
        "published":     "0" if draft else "1",
        "visibility":    "0" if draft else "20",   # 20=공개, 0=비공개
        "slogan":        slug,
        "acceptComment": "1",
    }

    try:
        resp = session.post(url, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP {e.response.status_code}: {e.response.text[:300]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 요청 실패: {e}", file=sys.stderr)
        sys.exit(1)

    if result.get("status") != "200":
        print(f"[ERROR] Tistory 응답 오류: {result}", file=sys.stderr)
        sys.exit(1)

    post_id = result.get("postId") or result.get("id", "")
    post_url = f"https://{BLOG_NAME}.tistory.com/{post_id}"
    return {"post_id": str(post_id), "url": post_url}


# ─────────────────────────────────────────────────
#  HTML 포스트 본문 빌드
# ─────────────────────────────────────────────────

def build_post_html(story: dict, youtube_video_id: str) -> tuple[str, str, list[str]]:
    """
    Returns (title, html_body, tags)
    """
    meta = story.get("meta", {})
    story_title = meta.get("story_title", "동화")
    grade = meta.get("grade", 2)
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")

    # 등장인물
    chars = meta.get("characters", {})
    char_items = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key)
        if ch and ch.get("name"):
            char_items.append(f"<li><strong>{ch['name']}</strong> — {ch.get('personality','')[:40]}</li>")
    supporting = chars.get("supporting", {})
    if isinstance(supporting, dict):
        for v in supporting.values():
            if isinstance(v, dict) and v.get("name"):
                char_items.append(f"<li>{v['name']} — {v.get('role','')[:30]}</li>")

    # 줄거리 (스토리 슬라이드 첫 4개)
    slides = [s for s in story.get("slides", []) if s.get("type") == "story"]
    summary_lines = "".join(f"<p>{s['text'][:120]}</p>" for s in slides[:4])

    # 교육 목표
    edu_goals = meta.get("educational_goals", [])
    goal_items = "".join(f"<li>{g}</li>" for g in edu_goals[:4])

    title = f"[초등 {grade}학년 동화] {story_title}"

    html = f"""
<div style="max-width:700px;margin:0 auto;font-family:'Noto Sans KR',sans-serif;line-height:1.8">

<!-- 유튜브 영상 임베드 -->
<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px;margin-bottom:28px">
  <iframe
    src="https://www.youtube.com/embed/{youtube_video_id}?rel=0"
    style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    allowfullscreen>
  </iframe>
</div>

<!-- 기본 정보 -->
<div style="background:#f0f7ff;border-left:4px solid #4a90e2;padding:16px 20px;border-radius:8px;margin-bottom:24px">
  <p style="margin:0 0 6px;font-size:15px">📚 <strong>교과</strong>: {subject} &nbsp;|&nbsp; <strong>단원</strong>: {unit_title}</p>
  <p style="margin:0;font-size:15px">🎯 <strong>대상</strong>: 초등학교 {grade}학년</p>
</div>

<!-- 줄거리 -->
<h2 style="color:#2c5aa0;border-bottom:2px solid #e0eaff;padding-bottom:8px">📖 이야기 줄거리</h2>
{summary_lines}

<!-- 등장인물 -->
<h2 style="color:#2c5aa0;border-bottom:2px solid #e0eaff;padding-bottom:8px">👥 등장인물</h2>
<ul style="padding-left:20px">
  {''.join(char_items)}
</ul>

<!-- 학습 목표 -->
{"" if not edu_goals else f'''
<h2 style="color:#2c5aa0;border-bottom:2px solid #e0eaff;padding-bottom:8px">🎯 학습 목표</h2>
<ul style="padding-left:20px">{goal_items}</ul>
'''}

<!-- 활동지 안내 -->
<div style="background:#fff8e1;border:1px solid #ffc107;border-radius:10px;padding:18px 20px;margin-top:28px">
  <h3 style="margin:0 0 10px;color:#e65100">📋 무료 활동지 (워크시트)</h3>
  <p style="margin:0;color:#555">영상을 보고 함께 풀어볼 수 있는 독후 활동지를 무료로 제공합니다.<br>
  아래 댓글로 이메일을 남겨주시면 PDF를 보내드립니다! 😊</p>
</div>

<!-- 태그 안내 -->
<p style="margin-top:32px;font-size:13px;color:#999;text-align:center">
  #초등동화 #{grade}학년 #독후활동 #{story_title.replace(' ','')} #무료활동지
</p>

</div>
"""

    tags = [
        f"초등{grade}학년", "초등동화", "독후활동지", "무료활동지",
        story_title.replace(" ", ""), subject, "어린이동화",
    ]

    return title, html, tags


# ─────────────────────────────────────────────────
#  메인
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tistory 자동 포스팅")
    parser.add_argument("--dir", dest="dir_path", required=True, help="output/bsl08 등")
    parser.add_argument("--video-id", dest="video_id", default=None,
                        help="YouTube 영상 ID (없으면 publish_log.json에서 읽음)")
    parser.add_argument("--draft", action="store_true", help="임시저장 (발행 안 함)")
    parser.add_argument("--category", default=None, help="카테고리 ID (기본: .env)")
    args = parser.parse_args()

    out_dir = Path(args.dir_path)

    # story.json 로드
    story_path = out_dir / "story.json"
    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}", file=sys.stderr)
        sys.exit(1)
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)

    # YouTube 영상 ID 확인
    video_id = args.video_id
    if not video_id:
        log_path = out_dir / "publish_log.json"
        if log_path.exists():
            with open(log_path, encoding="utf-8") as f:
                log = json.load(f)
            video_id = log.get("youtube_video_id", "")
    if not video_id:
        print("[ERROR] YouTube 영상 ID 필요. --video-id 또는 publish_log.json 확인", file=sys.stderr)
        sys.exit(1)

    print(f"[Tistory] 포스트 생성 중... (영상 ID: {video_id})")

    title, html, tags = build_post_html(story, video_id)
    print(f"  제목: {title}")
    print(f"  태그: {', '.join(tags[:5])}")

    result = publish_post(
        title=title,
        html_content=html,
        tags=tags,
        category_id=args.category,
        draft=args.draft,
    )

    print(f"\n[완료] {'임시저장' if args.draft else '발행'} 성공!")
    print(f"  포스트 URL: {result['url']}")

    # publish_log.json 업데이트
    log_path = out_dir / "publish_log.json"
    log = {}
    if log_path.exists():
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    log["tistory_post_id"] = result["post_id"]
    log["tistory_url"] = result["url"]
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"  로그 저장 → {log_path}")


if __name__ == "__main__":
    main()
