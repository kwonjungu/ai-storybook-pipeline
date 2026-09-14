#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_auth_setup_channel.py
새 언어 채널(id/en/pt/es)을 안전하게 인증 + channel_registry.json 등록.

2026-09-12 사고 배경: token_id.json 이 인도네시아 채널이 아니라 한국어 본채널로 인증돼 있어서
'인니 업로드'가 본채널에 공개됐다. 그래서 인증 직후 반드시 실측 channel_id를 확인하고,
그 값을 레지스트리에 적어야 한다. (publish_youtube.verify_channel 이 이 값과 대조한다.)

브라우저가 열리므로 사용자가 직접 실행해야 함:

  python _auth_setup_channel.py id              # 인증 후 실제 채널만 보여줌 (등록 안 함)
  python _auth_setup_channel.py id --register   # 확인한 채널을 레지스트리에 등록

★ 브라우저 계정 선택 화면에서 반드시 '해당 언어 브랜드 채널'로 전환한 뒤 승인할 것.
  (프로필 → 채널 전환 → 대상 채널 선택 → 그 상태에서 승인)
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import publish_youtube as py
from googleapiclient.discovery import build

REGISTRY = ROOT / "channel_registry.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channel", choices=["id", "en", "pt", "es"], help="채널 코드")
    ap.add_argument("--register", action="store_true",
                    help="인증된 채널을 channel_registry.json에 등록")
    ap.add_argument("--force-reauth", action="store_true",
                    help="기존 token_{code}.json을 백업하고 처음부터 다시 인증")
    args = ap.parse_args()

    token = py.CHANNEL_TOKENS.get(args.channel, ROOT / f"token_{args.channel}.json")
    if args.force_reauth and token.exists():
        bak = token.with_suffix(".json.bak")
        token.replace(bak)
        print(f"[백업] {token.name} -> {bak.name} (새로 인증합니다)")

    print(f"\n[인증] --channel {args.channel}")
    print("  브라우저가 열리면 반드시 '대상 언어 채널'로 전환한 상태에서 승인하세요.\n")
    creds = py.get_credentials(args.channel)

    yt = build("youtube", "v3", credentials=creds)
    items = yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if not items:
        print("[실패] mine=True 채널 조회 결과 없음 — 인증은 됐지만 채널이 없습니다.")
        sys.exit(1)

    ch = items[0]
    cid = ch["id"]
    title = ch["snippet"]["title"]
    custom = ch["snippet"].get("customUrl")
    stats = ch.get("statistics", {})

    print("\n" + "=" * 60)
    print(f"  실제 인증된 채널: {title}")
    print(f"  channel_id     : {cid}")
    print(f"  custom_url     : {custom}")
    print(f"  영상 수        : {stats.get('videoCount')} / 구독자 {stats.get('subscriberCount')}")
    print("=" * 60)

    registry = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
    other = [(k, v) for k, v in registry.items()
             if isinstance(v, dict) and v.get("channel_id") == cid and k != args.channel]
    if other:
        print(f"\n[경고] 이 channel_id는 이미 '{other[0][0]}' 채널로 등록돼 있습니다"
              f" ({other[0][1].get('title')}).")
        print("       채널 전환을 안 하고 승인했을 가능성이 큽니다. --force-reauth 로 다시 인증하세요.")
        print("       (이 상태로 등록하면 2026-09-12와 같은 오업로드 사고가 재발합니다)")
        sys.exit(2)

    if not args.register:
        print("\n위 채널이 맞으면 --register 를 붙여 다시 실행하세요:")
        print(f"  python _auth_setup_channel.py {args.channel} --register")
        return

    registry[args.channel] = {
        "channel_id": cid,
        "title": title,
        "custom_url": custom,
        "_verified": f"{__import__('datetime').date.today()}: _auth_setup_channel.py 로 실측 확인",
    }
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] channel_registry.json 에 '{args.channel}' 등록 완료 → 이제 업로드 게이트를 통과합니다.")


if __name__ == "__main__":
    main()
