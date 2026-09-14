#!/usr/bin/env python3
"""HAMZZI(영어) 채널 설명란/키워드 브랜딩 적용 (2026-09 적용 완료, 재실행해도 안전/멱등)."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from publish_youtube import get_credentials
from googleapiclient.discovery import build

CHANNEL_ID = "UC_JAT6vjJoDtwJ5eRqjdJdQ"

# 설명란 1000자 제한 — 반드시 len() 확인 후 적용
DESCRIPTION = """🐹 Storybook read-alouds for young learners, made by a Korean elementary school teacher.

Piyo the chick and Toto the turtle turn everyday classroom topics into gentle 4-6 minute adventures — no fast cuts, no flashy effects. Just a calm voice, soft watercolor pictures, and a story kids can actually follow.

English retelling of "Hamzzi's Storytime Journey," a Korean elementary curriculum project — same characters, same calm pace.

📚 For teachers
- Each story comes with a read-aloud quiz + free printable worksheet and picture-book slides
- Made for classroom read-alouds, not for chasing the algorithm

🌙 For families
- A quiet story before bed — no jump cuts, no loud effects, nothing overstimulating
- A slower, gentler alternative to fast-paced Shorts and Reels for kids

New stories added gradually, a few at a time.
Free to use in class. Questions: kdhdhdbdbr@gmail.com"""

KEYWORDS = ('"read aloud for kids" "bedtime story" "kids story english" '
            '"classroom story" "picture book" "elementary story"')

if __name__ == "__main__":
    assert len(DESCRIPTION) <= 1000, f"설명란 {len(DESCRIPTION)}자 — 1000자 초과"

    creds = get_credentials("en")
    yt = build("youtube", "v3", credentials=creds)
    yt.channels().update(
        part="brandingSettings",
        body={"id": CHANNEL_ID, "brandingSettings": {
            "channel": {"title": "HAMZZI", "description": DESCRIPTION, "keywords": KEYWORDS}
        }},
    ).execute()
    print("[OK] HAMZZI 채널 설명란/키워드 업데이트 완료")
