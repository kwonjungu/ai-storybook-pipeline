# -*- coding: utf-8 -*-
"""Phase 1 채널 클린업 (일회성).
- 유령/브랜드 불일치 영상 4개 비공개 전환
- 채널 설명·키워드 갱신
사용:
  python -X utf8 12_channel_cleanup.py            # dry-run (기본)
  python -X utf8 12_channel_cleanup.py --apply    # 실제 적용
★ hSFx-jPB1wo(마크의 탐험복, 1170회)는 유지 결정 — 절대 건드리지 않음.
"""
import sys, json, argparse
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 비공개 전환 대상 (정확히 이 4개만)
PRIVATE_TARGETS = [
    ("rHKyq21mpVI", "유령 영상 (P0D, 알 탐험 중복본)"),
    ("yzRXwceugtk", "우주여행 (해시태그 스팸)"),
    ("BzH201-VuUA", "치킨 토론"),
    ("ML18dfCE7FU", "로봇 센서"),
]
KEEP = "hSFx-jPB1wo"  # 마크의 탐험복 (1170회) — 유지, 절대 제외

NEW_DESC = (
    "초등 1~2학년 통합교과 단원에 딱 맞춘 창작 동화 채널입니다.\n"
    "교과서 쪽수 그대로, 4~6분 동화 + 독후 퀴즈 + 무료 활동지·그림책 PPT까지.\n"
    "선생님은 수업 도입에, 부모님은 잠들기 전 한 편에 활용하세요."
)
NEW_KEYWORDS = (
    '"1학년 통합교과" "2학기 상상" "하루" "초등 동화" '
    '"독후 활동지" "그림책 PPT" "교과 연계 동화"'
)


def get_yt():
    tok = json.loads(Path("token_ko.json").read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_file("token_ko.json", tok["scopes"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 적용 (미지정 시 dry-run)")
    args = ap.parse_args()
    apply = args.apply
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"===== 12_channel_cleanup [{mode}] =====\n")

    yt = get_yt()

    # --- 안전장치: KEEP 영상이 대상 목록에 없는지 확인 ---
    target_ids = [t[0] for t in PRIVATE_TARGETS]
    assert KEEP not in target_ids, f"치명적 오류: 유지 대상 {KEEP} 이 비공개 목록에 포함됨!"
    print(f"[안전확인] 유지 영상 {KEEP} 는 비공개 대상 목록에 없음 (OK)\n")

    # --- 1. 영상 비공개 전환 ---
    print("--- 1. 비공개 전환 대상 ---")
    for vid, label in PRIVATE_TARGETS:
        try:
            resp = yt.videos().list(part="status", id=vid).execute()
            items = resp.get("items", [])
            if not items:
                print(f"  [경고] {vid} ({label}) : 영상을 찾을 수 없음 — 건너뜀")
                continue
            status = items[0]["status"]  # 기존 필드 보존
            cur_privacy = status.get("privacyStatus")
            print(f"  {vid} ({label}) : {cur_privacy} -> private")
            if apply:
                if cur_privacy == "private":
                    print(f"    이미 private — 건너뜀")
                    continue
                status["privacyStatus"] = "private"
                yt.videos().update(
                    part="status",
                    body={"id": vid, "status": status},
                ).execute()
                print(f"    적용 완료")
        except Exception as e:
            print(f"  [실패] {vid} ({label}) : {e}")

    # --- 2. 채널 설명·키워드 갱신 ---
    print("\n--- 2. 채널 설명·키워드 갱신 ---")
    ch = yt.channels().list(part="brandingSettings", mine=True).execute()
    bs = ch["items"][0]["brandingSettings"]
    channel = dict(bs.get("channel", {}))  # 기존 하위 필드 보존
    old_desc = channel.get("description", "")
    old_kw = channel.get("keywords", "")
    print("  [설명 old]")
    print("    " + old_desc.replace("\n", "\n    "))
    print("  [설명 new]")
    print("    " + NEW_DESC.replace("\n", "\n    "))
    print(f"  [키워드 old] {old_kw}")
    print(f"  [키워드 new] {NEW_KEYWORDS}")

    if apply:
        channel["description"] = NEW_DESC
        channel["keywords"] = NEW_KEYWORDS
        body = {"id": ch["items"][0]["id"], "brandingSettings": {"channel": channel}}
        # image 등 다른 brandingSettings 하위 블록도 보존
        for k, v in bs.items():
            if k != "channel":
                body["brandingSettings"][k] = v
        yt.channels().update(part="brandingSettings", body=body).execute()
        print("  채널 설명·키워드 적용 완료")

    print(f"\n===== 완료 [{mode}] =====")
    if not apply:
        print("실제 적용하려면 --apply 로 재실행하세요.")


if __name__ == "__main__":
    main()
