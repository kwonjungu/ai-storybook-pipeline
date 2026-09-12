# -*- coding: utf-8 -*-
"""
yt_meta.py
==========
YouTube 제목/설명란 빌더 (신규 업로드 publish_youtube.py 와 소급 리라이트 13_rewrite_metadata.py 공유).

- build_title(story):   {story_title}! | {학년} {학기} {series} {sub_unit} ({쪽수})
- build_description(...): 계획서 2-2 새 템플릿 (재생목록 → logline → 타임스탬프 → 교과 → 링크 → 문의/해시태그)
- build_tags(story):    기존 태그 로직 (publish_youtube 와 동일)

포맷 이원화 방지를 위해 두 스크립트 모두 이 모듈을 import 한다.
"""

import re

# 학부모용 잠자리 동화 재생목록 (2026-08-23 신설, 전 본편 수록)
BEDTIME_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLE6j04849ZfA"

# ─────────────────────────────────────────────────
#  쪽수 추출
# ─────────────────────────────────────────────────

_PAGE_RE = re.compile(r"\((\d+\s*[-~]\s*\d+\s*p?)\)")


def extract_pages(story: dict) -> str:
    """youtube_title / unit_title 에서 (NN-NNp) 패턴을 추출. 없으면 ''."""
    meta = story.get("meta", {})
    for field in ("youtube_title", "unit_title", "sub_unit"):
        val = meta.get(field, "") or ""
        m = _PAGE_RE.search(val)
        if m:
            pages = m.group(1).strip()
            # 'p' 접미사 표준화: 숫자만 있으면 p 붙임
            pages = re.sub(r"\s*", "", pages)
            if not pages.endswith("p"):
                pages += "p"
            return pages
    # meta 에 직접 page 필드가 있을 수 있음
    for field in ("pages", "page"):
        val = meta.get(field)
        if val:
            v = str(val).strip()
            if not v.endswith("p"):
                v += "p"
            return v
    return ""


# ─────────────────────────────────────────────────
#  제목 빌드
# ─────────────────────────────────────────────────

def build_title(story: dict) -> str:
    """새 제목 공식: {story_title}! | {학년}학년 {학기}학기 {series} {sub_unit} ({쪽수})

    - story_title 에 이미 문장부호(! ? . ~)가 있으면 훅 뒤 부호 중복 금지
    - meta.youtube_title 은 무시하고 재조합
    - 쪽수는 extract_pages 로 획득 (없으면 괄호 생략)
    - 100자 컷
    """
    meta = story.get("meta", {})
    grade = meta.get("grade", "")
    semester = meta.get("semester", "")
    series = (meta.get("series", "") or "").strip()
    sub_unit = (meta.get("sub_unit", "") or "").strip()
    unit_title = (meta.get("unit_title", "") or "").strip()
    story_title = (meta.get("story_title", "") or "").strip()

    # 훅: story_title. 끝에 종결부호 없으면 '!' 추가
    hook = story_title
    if hook and hook[-1] not in "!?.~…":
        hook = hook + "!"

    # 컨텍스트 좌측 라벨: {학년}학년 {학기}학기 {series}
    ctx_parts = []
    if grade != "" and grade is not None:
        ctx_parts.append(f"{grade}학년")
    if semester != "" and semester is not None:
        ctx_parts.append(f"{semester}학기")
    if series:
        ctx_parts.append(series)

    # 소단원명: unit_title 에서 쪽수 괄호를 제거한 본문을 우선 사용
    #  (sub_unit 은 '함께 골라요' 차시명이라 단원명은 unit_title 이 정확)
    unit_name = _PAGE_RE.sub("", unit_title).strip() if unit_title else sub_unit
    if unit_name:
        ctx_parts.append(unit_name)

    pages = extract_pages(story)
    ctx = " ".join(ctx_parts).strip()
    if pages:
        ctx = f"{ctx} ({pages})".strip()

    if ctx:
        title = f"{hook} | {ctx}"
    else:
        title = hook

    return title[:100]


# ─────────────────────────────────────────────────
#  시간 포맷
# ─────────────────────────────────────────────────

def _fmt_mmss(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(float(seconds)))
    m, sec = divmod(s, 60)
    return f"{m:02d}:{sec:02d}"


# ─────────────────────────────────────────────────
#  설명란 빌드
# ─────────────────────────────────────────────────

def build_description(
    story: dict,
    pptx_url: str = None,
    worksheet_url: str = None,
    playlist_url: str = None,
    quiz_start: float = None,
) -> str:
    """계획서 2-2 새 설명란 템플릿.

    구조 (위→아래):
      1) ▶ 단원 전체 재생목록: {playlist_url}   (없으면 생략)
      2) meta.logline                             (비스포일러 소개 2~3줄)
      3) ⏰ 00:00 동화 | {mm:ss} 독후 퀴즈       (quiz_start None 이면 생략)
      4) 구분선 + 교과 정보 블록
      5) PPT / 활동지 링크 블록
      6) 문의 + 해시태그

    시그니처는 publish_youtube 의 build_description(story, pptx_url, worksheet_url)
    과 하위호환 (playlist_url / quiz_start 는 선택 인자).
    """
    meta = story.get("meta", {})
    grade = meta.get("grade", 2)
    semester = meta.get("semester", "")
    series = meta.get("series", "")
    subject = meta.get("subject", "")
    unit_title = meta.get("unit_title", "")
    sub_unit = meta.get("sub_unit", "")
    story_title = meta.get("story_title", "")

    subject_full = " ".join(str(x) for x in
                            [f"{grade}학년", f"{semester}학기" if semester else "",
                             subject, series] if x).strip()

    # logline (비스포일러). 없으면 폴백: story_title 한 줄
    logline = (meta.get("logline") or "").strip()
    if not logline:
        logline = f"{story_title} 이야기"

    # 주인공
    chars = meta.get("characters", {})
    char_names = []
    for key in ("main_1", "main_2"):
        ch = chars.get(key)
        if ch and ch.get("name"):
            char_names.append(ch["name"])

    blocks = []

    # 1) 재생목록 (최상단)
    if playlist_url:
        blocks.append(f"▶ 단원 전체 재생목록 보기\n👉 {playlist_url}")

    # 2) logline (제목 한 줄 + 소개)
    intro = f"🌟 {story_title}\n\n{logline}" if story_title else logline
    blocks.append(intro)

    # 3) 타임스탬프
    if quiz_start is not None:
        blocks.append(f"⏰ 00:00 동화  |  {_fmt_mmss(quiz_start)} 독후 퀴즈")

    # 4) 교과 정보 블록
    info_lines = [
        "━━━━━━━━━━━━━━━━━━",
        f"📚 교과: {subject_full}  |  {unit_title}".rstrip(" |"),
        f"📖 차시: {sub_unit}",
        f"🎯 대상: 초등학교 {grade}학년",
    ]
    if char_names:
        info_lines.append(f"👥 주인공: {', '.join(char_names)}")
    info_lines.append("━━━━━━━━━━━━━━━━━━")
    blocks.append("\n".join(info_lines))

    # 5) PPT / 활동지 링크 블록 + 학부모용 잠자리 재생목록
    link_lines = []
    link_lines.append(
        "🌙 잠자리 동화 모음 (자기 전 한 편씩)\n"
        f"  👉 {BEDTIME_PLAYLIST_URL}"
    )
    if pptx_url:
        link_lines.append(
            "📊 그림책 PPT 무료 다운로드\n"
            f"  👉 {pptx_url}\n"
            "  (수업·가정학습용으로 자유롭게 사용하세요!)"
        )
    if worksheet_url:
        link_lines.append(
            "✏️ 독후 활동지(워크시트) 무료 다운로드\n"
            f"  👉 {worksheet_url}\n"
            "  (인쇄해서 바로 수업에 활용하세요!)"
        )
    if link_lines:
        blocks.append("\n\n".join(link_lines))

    # 6) 문의 + 해시태그 (해시태그는 공백·문장부호 제거)
    tag_title = re.sub(r"[^0-9A-Za-z가-힣]", "", story_title)
    hashtags = (
        f"#초등동화 #{grade}학년 #독후활동 #무료활동지 #{tag_title} #{subject} #그림책PPT"
        " #잠자리동화 #읽어주는동화 #자기전동화"
    )
    blocks.append(
        "📌 문의는 메일로 주세요: kdhdhdbdbr@gmail.com 😊\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{hashtags}"
    )

    return "\n\n".join(blocks) + "\n"


# ─────────────────────────────────────────────────
#  태그 빌드 (publish_youtube 와 동일)
# ─────────────────────────────────────────────────

def build_tags(story: dict) -> list:
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
