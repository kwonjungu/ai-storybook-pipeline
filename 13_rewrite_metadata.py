# -*- coding: utf-8 -*-
"""
13_rewrite_metadata.py
======================
기존 업로드 영상의 제목/설명란을 yt_meta.py 새 포맷으로 일괄 리라이트한다.
(영상 파일 재업로드 없음 — videos().update(part="snippet") 만 사용)

- 인증: token_ko.json 의 scopes 필드 사용 (SCOPES 하드코딩 금지, _channel_audit.py 참고)
- 대상: output/*/publish_log.json (에코의탐험복찾기 제외)
- 재생목록: playlists().list(mine=True) 에서 제목에 '하루'/'상상' 포함 ID 획득 → 폴더명 배정
- 퀴즈 시작 시각: 표지(5s) + full_audio.wav 길이 로 계산
- 본편: 새 title + 새 description. 쇼츠: 기존 설명 최상단에 본편 링크 삽입.
- --dry-run(기본): _rewrite_preview.md 에 편별 [폴더 / ID / 구제목→신제목 / 신설명] 기록
- --apply: videos().list 로 snippet 읽어 categoryId·tags 보존 후 update, publish_log 에 meta_rewritten 기록
- --only <폴더명>: 특정 폴더만

사용:
  python 13_rewrite_metadata.py                 # dry-run (기본)
  python 13_rewrite_metadata.py --only 초능력
  python 13_rewrite_metadata.py --apply
  python 13_rewrite_metadata.py --apply --only 초능력
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yt_meta

EXCLUDE_KEYWORDS = ("에코의탐험복찾기", "로봇부품교육", "토론_치킨")  # 에코=사용자 결정 유지, 로봇·치킨=비공개 전환됨
TOKEN_FILE = "token_ko.json"
COVER_DURATION = 5.0  # 06_assemble_video 표지 슬라이드 고정 5초 (thumbnail 존재 시)
PREVIEW_PATH = Path("_rewrite_preview.md")

FFPROBE = None  # main 에서 결정


# ─────────────────────────────────────────────────
#  인증 (token 파일 scopes 사용)
# ─────────────────────────────────────────────────

def get_yt():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    tok = json.loads(Path(TOKEN_FILE).read_text(encoding="utf-8"))
    scopes = tok.get("scopes")
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


# ─────────────────────────────────────────────────
#  재생목록 매핑
# ─────────────────────────────────────────────────

def fetch_playlists(yt):
    """{'하루': id, '상상': id} 반환 (제목 키워드 매칭)."""
    mapping = {}
    tok = None
    while True:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=tok).execute()
        for p in r["items"]:
            title = p["snippet"]["title"]
            pid = p["id"]
            if "하루" in title and "하루" not in mapping:
                mapping["하루"] = pid
            if "상상" in title and "상상" not in mapping:
                mapping["상상"] = pid
        tok = r.get("nextPageToken")
        if not tok:
            break
    return mapping


def playlist_url_for(folder_name: str, pl_map: dict):
    """폴더명 → 재생목록 URL (매핑 안 되면 None)."""
    key = None
    if "하루" in folder_name:
        key = "하루"
    elif "통합교과" in folder_name and "함께골라요" in folder_name:
        # 하루가 아닌 통합교과 '함께 골라요' 편 = 상상 단원
        key = "상상"
    if key and key in pl_map:
        return f"https://www.youtube.com/playlist?list={pl_map[key]}"
    return None


# ─────────────────────────────────────────────────
#  퀴즈 시작 시각
# ─────────────────────────────────────────────────

def probe_duration(path: Path):
    import subprocess as _sp
    try:
        out = _sp.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def compute_quiz_start(d: Path):
    """표지(5s) + full_audio.wav 길이 = 최종영상에서 퀴즈 시작 offset.
    (06_assemble_video: 표지 5s + 본편[=full_audio 길이로 트림] + 퀴즈 + 아웃트로.
     assets/intro_bg.png 없으면 인트로 없음 — 현 프로젝트 기준.)
    계산 불가 시 None → 타임스탬프 줄 생략."""
    audio = d / "audio" / "full_audio.wav"
    if not audio.exists():
        return None
    dur = probe_duration(audio)
    if dur is None or dur <= 0:
        return None
    cover = COVER_DURATION if (d / "thumbnail_a.png").exists() or (d / "thumbnail_b.png").exists() else 0.0
    intro = 0.0   # _attach_intro.py 로 공통 인트로를 붙인 편 (2026-10-11~)
    if (d / "intro.json").exists():
        intro = float(json.load(open(d / "intro.json", encoding="utf-8")).get("sec", 0.0))
    return intro + cover + dur


# ─────────────────────────────────────────────────
#  대상 폴더
# ─────────────────────────────────────────────────

def target_dirs(only: str = None):
    dirs = []
    for pl in sorted(Path("output").glob("*/publish_log.json")):
        d = pl.parent
        if any(k in d.name for k in EXCLUDE_KEYWORDS):
            continue
        if only and only not in d.name:
            continue
        dirs.append(d)
    return dirs


# ─────────────────────────────────────────────────
#  쇼츠 설명 최상단에 본편 링크 삽입
# ─────────────────────────────────────────────────

def prepend_shorts_link(existing_desc: str, main_video_id: str) -> str:
    line = f"▶ 본편에서 결말 보기: https://youtu.be/{main_video_id}"
    base = existing_desc or ""
    if f"youtu.be/{main_video_id}" in base or "본편에서 결말 보기" in base:
        return base  # 중복 방지
    return line + "\n\n" + base


# ─────────────────────────────────────────────────
#  메인
# ─────────────────────────────────────────────────

def main():
    global FFPROBE
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 유튜브에 반영 (기본은 dry-run)")
    ap.add_argument("--only", default=None, help="특정 폴더명(부분 매칭)만")
    ap.add_argument("--ffprobe", default="ffprobe", help="ffprobe 경로")
    args = ap.parse_args()
    FFPROBE = args.ffprobe
    dry_run = not args.apply

    dirs = target_dirs(args.only)
    print(f"[INFO] 대상 폴더 {len(dirs)}개 / 모드: {'DRY-RUN' if dry_run else 'APPLY'}")

    yt = get_yt()
    pl_map = fetch_playlists(yt)
    print(f"[INFO] 재생목록 매핑: {list(pl_map.keys())}")

    preview_blocks = []
    stats = {"ok": 0, "skip": 0, "fail": 0, "shorts": 0}
    failed = []

    for d in dirs:
        try:
            story = json.loads((d / "story.json").read_text(encoding="utf-8"))
            log = json.loads((d / "publish_log.json").read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [FAIL] {d.name}: {e}")
            failed.append(d.name)
            stats["fail"] += 1
            continue

        vid = log.get("youtube_video_id")
        sid = log.get("shorts_video_id")
        if not vid:
            print(f"  [SKIP] {d.name}: youtube_video_id 없음")
            stats["skip"] += 1
            continue

        pptx_url = log.get("pptx_drive_url")
        ws_url = log.get("worksheet_drive_url")
        playlist_url = playlist_url_for(d.name, pl_map)
        quiz_start = compute_quiz_start(d)

        new_title = yt_meta.build_title(story)
        new_desc = yt_meta.build_description(
            story, pptx_url=pptx_url, worksheet_url=ws_url,
            playlist_url=playlist_url, quiz_start=quiz_start,
        )

        # 기존 제목 (dry-run 표시용)
        try:
            cur = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
            old_title = cur.get("title", "")
        except Exception as e:
            print(f"  [FAIL] {d.name}: snippet 조회 실패 {e}")
            failed.append(d.name)
            stats["fail"] += 1
            continue

        # 쇼츠 신규 설명 (미리보기)
        shorts_new_desc = None
        if sid:
            try:
                scur = yt.videos().list(part="snippet", id=sid).execute()["items"][0]["snippet"]
                shorts_new_desc = prepend_shorts_link(scur.get("description", ""), vid)
            except Exception:
                shorts_new_desc = None

        # ── 미리보기 기록 ──
        block = [
            f"## {d.name}",
            f"- 본편 ID: `{vid}`" + (f" / 쇼츠 ID: `{sid}`" if sid else ""),
            f"- 재생목록: {playlist_url or '(매핑 없음)'}",
            f"- 퀴즈 시작: {yt_meta._fmt_mmss(quiz_start) if quiz_start else '(계산 불가 → 생략)'}",
            "",
            f"**구제목:** {old_title}",
            "",
            f"**신제목:** {new_title}",
            "",
            "**신설명:**",
            "```",
            new_desc.rstrip(),
            "```",
        ]
        if sid and shorts_new_desc is not None:
            block += [
                "",
                "**쇼츠 신설명(최상단 본편 링크 삽입):**",
                "```",
                shorts_new_desc.rstrip()[:600],
                "```",
            ]
        block.append("\n---\n")
        preview_blocks.append("\n".join(block))

        if dry_run:
            print(f"  [DRY] {d.name}: {old_title[:30]}... → {new_title[:40]}...")
            stats["ok"] += 1
            continue

        # ── APPLY ──
        try:
            # 본편: 기존 snippet 보존 후 title/description 교체
            cur["title"] = new_title[:100]
            cur["description"] = new_desc
            cur["categoryId"] = cur.get("categoryId", "27")
            # tags 보존 (없으면 새로 생성)
            if not cur.get("tags"):
                cur["tags"] = yt_meta.build_tags(story)[:15]
            cur["defaultLanguage"] = cur.get("defaultLanguage", "ko")
            yt.videos().update(part="snippet", body={"id": vid, "snippet": cur}).execute()
            print(f"  [본편 갱신] {vid}")

            # 쇼츠: 기존 설명 최상단에 본편 링크
            if sid and shorts_new_desc is not None:
                scur = yt.videos().list(part="snippet", id=sid).execute()["items"][0]["snippet"]
                new_s = prepend_shorts_link(scur.get("description", ""), vid)
                if new_s != scur.get("description", ""):
                    scur["description"] = new_s
                    scur["categoryId"] = scur.get("categoryId", "27")
                    yt.videos().update(part="snippet", body={"id": sid, "snippet": scur}).execute()
                    print(f"  [쇼츠 갱신] {sid}")
                    stats["shorts"] += 1

            # publish_log 에 기록
            log["meta_rewritten"] = date.today().isoformat()
            (d / "publish_log.json").write_text(
                json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            stats["ok"] += 1
        except Exception as e:
            print(f"  [FAIL] {d.name} 업데이트 실패: {e}")
            failed.append(d.name)
            stats["fail"] += 1

    # ── 미리보기 파일 저장 (dry-run·apply 모두) ──
    header = (
        f"# 메타데이터 리라이트 미리보기\n"
        f"생성일: {date.today().isoformat()} / 모드: {'DRY-RUN' if dry_run else 'APPLY'} / 대상 {len(dirs)}편\n\n"
        f"재생목록 매핑: {json.dumps(pl_map, ensure_ascii=False)}\n\n---\n\n"
    )
    PREVIEW_PATH.write_text(header + "\n".join(preview_blocks), encoding="utf-8")
    print(f"\n[완료] 미리보기 → {PREVIEW_PATH}")
    print(f"  본편 {stats['ok']} / 쇼츠 {stats['shorts']} / 건너뜀 {stats['skip']} / 실패 {stats['fail']}")
    if failed:
        print("[실패]", ", ".join(failed))


if __name__ == "__main__":
    main()
