# -*- coding: utf-8 -*-
"""
_resync_worksheets.py — 로컬 최신 활동지 PDF를 Drive의 **같은 파일 ID**에 덮어쓴다.

왜: 2026-09-26 전수조사에서 하루·상상 20편이 8/19~22 구버전 PDF 그대로 배포 중인 게 드러남
    (코드는 고쳤지만 다시 올리는 단계가 없었음). fix_drive_links.py 는 새 파일을 만들고 설명란을
    구 템플릿으로 덮어쓰므로 소급 배포에 쓰면 안 된다.

- 대상: publish_log.json 에 worksheet_drive_url 이 있는 편
- 조건: worksheet_qa.json(v2) 합격 + 그 QA의 pdf_md5 == 현재 PDF md5 (검사한 파일 = 올릴 파일)
- files().update(fileId=기존ID) → 링크·공유 권한 그대로, 설명란 수정 불필요
- 덮어쓰기 전 Drive 원본을 _drive_backup_YYYYMMDD/ 에 내려받아 보관
- 결과를 publish_log.json 에 worksheet_md5 / worksheet_synced_at 으로 기록

사용:
  python _resync_worksheets.py                # dry-run: Drive md5 vs 로컬 md5 표
  python _resync_worksheets.py --apply        # 다른 것만 덮어쓰기
  python _resync_worksheets.py --only 수도꼭지  # 부분 매칭
"""
import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

BASE = Path(__file__).parent


def drive_client():
    t = json.loads((BASE / "token_ko.json").read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(t, t.get("scopes"))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def retry(fn, tries=4):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    재시도 {i+1}: {str(e)[:80]}")
            time.sleep(2 ** i)


def targets(only):
    out = []
    for pl in sorted((BASE / "output").glob("*/publish_log.json")):
        log = json.loads(pl.read_text(encoding="utf-8"))
        url = log.get("worksheet_drive_url")
        if not url or (only and only not in pl.parent.name):
            continue
        m = re.search(r"/d/([^/]+)", url)
        if m:
            out.append((pl.parent, m.group(1), log))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    drive = drive_client()
    bk = BASE / f"_drive_backup_{date.today():%Y%m%d}"
    rows = {"same": 0, "update": 0, "blocked": 0, "done": 0, "fail": 0}

    for d, fid, log in targets(args.only):
        pdf = d / "worksheet.pdf"
        qa_p = d / "worksheet_qa.json"
        local = md5(pdf)
        qa = json.loads(qa_p.read_text(encoding="utf-8")) if qa_p.exists() else {}
        meta = retry(lambda: drive.files().get(fileId=fid, fields="md5Checksum,name").execute())
        name = d.name[:48]

        if meta.get("md5Checksum") == local:
            rows["same"] += 1
            print(f"  동일      {name}")
            continue
        if qa.get("qa_version") != 2 or not qa.get("all_ok") or qa.get("pdf_md5") != local:
            rows["blocked"] += 1
            why = ("QA v2 없음" if qa.get("qa_version") != 2 else
                   "QA 불합격" if not qa.get("all_ok") else "QA 이후 PDF 바뀜")
            print(f"  차단      {name}  ({why} → 07a 다시 실행)")
            continue
        rows["update"] += 1
        if not args.apply:
            print(f"  덮어쓸것  {name}")
            continue

        try:
            # 1) Drive 원본 백업
            bk.mkdir(exist_ok=True)
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fid))
            done = False
            while not done:
                _, done = dl.next_chunk()
            (bk / f"{d.name}__{fid}.pdf").write_bytes(buf.getvalue())
            # 2) 같은 ID에 덮어쓰기
            media = MediaFileUpload(str(pdf), mimetype="application/pdf", resumable=False)
            retry(lambda: drive.files().update(fileId=fid, media_body=media).execute())
            # 3) 검증
            after = retry(lambda: drive.files().get(fileId=fid, fields="md5Checksum").execute())
            if after.get("md5Checksum") != local:
                raise RuntimeError("업로드 후 md5 불일치")
            log["worksheet_md5"] = local
            log["worksheet_synced_at"] = datetime.now().isoformat(timespec="seconds")
            (d / "publish_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            rows["done"] += 1
            print(f"  갱신완료  {name}")
        except Exception as e:
            rows["fail"] += 1
            print(f"  실패      {name}: {e}")

    print(f"\n[resync] 동일 {rows['same']} / 덮어쓸 대상 {rows['update']} / 차단 {rows['blocked']}"
          + (f" / 갱신완료 {rows['done']} / 실패 {rows['fail']}" if args.apply else "  (dry-run)"))
    sys.exit(1 if rows["fail"] or rows["blocked"] else 0)


if __name__ == "__main__":
    main()
