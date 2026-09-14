#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_repair_id_tts.py
인니(_id) 편의 'TTS 세그먼트 결손'을 찾아 채우고, 필요하면 영상을 다시 만들어 재업로드한다.

배경 (2026-09-14):
  Gemini TTS(gemini-2.5-flash-preview-tts)가 간헐적으로 빈 응답을 준다
  ("'NoneType' object has no attribute 'parts'"). 3회 재시도까지 실패하면 그 대사만 조용히
  빠진 채 다음 단계로 넘어가고, 영상에는 그 문장이 통째로 사라진 상태로 나간다.
  상상 단원 10편 중 4편에서 1~4개씩 빠진 걸 업로드 후에 발견했다.
  -> 03은 이미 만든 wav 를 건너뛰므로 다시 돌리면 '빠진 것만' 생성된다.

  python _repair_id_tts.py --check          # 결손 현황만 출력
  python _repair_id_tts.py                  # 보수 + 영상 재조립 + 재업로드(구버전 private)
  python _repair_id_tts.py --no-upload      # 보수·재조립까지만
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import publish_youtube as py

PY = sys.executable
BATCH_LOGS = ["_id_batch_log.json", "_id_haru_batch_log.json"]


def seg_status(d: Path):
    story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    want = sum(len(sl.get("tts_segments", [])) for sl in story["slides"])
    have = len(list((d / "audio").glob("slide_*_seg_*.wav"))) if (d / "audio").is_dir() else 0
    return want, have, story


def run(cmd):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"실패({r.returncode})")


def find_log_entry(folder_id_name: str):
    """_id_*_batch_log.json 에서 이 폴더(원본 한국어 폴더명 기준) 항목 찾기."""
    src_name = folder_id_name[:-3] if folder_id_name.endswith("_id") else folder_id_name
    for lf in BATCH_LOGS:
        p = ROOT / lf
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if src_name in data and data[src_name].get("video_id"):
            return p, data, src_name
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="현황만 출력")
    ap.add_argument("--no-upload", action="store_true", help="재업로드 생략")
    ap.add_argument("--only", default=None)
    ap.add_argument("--reupload", action="store_true",
                    help="결손이 없어도 --only 대상 폴더를 강제로 재업로드 "
                         "(보수는 끝났는데 업로드만 SSL 순단으로 실패한 편 복구용)")
    args = ap.parse_args()

    targets = []
    for d in sorted(Path("output").glob("*_id")):
        if not (d / "story.json").exists():
            continue
        if args.only and args.only not in d.name:
            continue
        want, have, _ = seg_status(d)
        if have < want:
            targets.append((d, want, have))
            print(f"[결손] {d.name[:46]:48s} {have}/{want} ({want-have}개 빠짐)")
        elif args.reupload and args.only:
            targets.append((d, want, have))
            print(f"[재업로드] {d.name[:46]:48s} {have}/{want} (결손 없음, 강제)")

    if not targets:
        print("[OK] 결손 없음")
        return
    print(f"\n총 {len(targets)}편 결손")
    if args.check:
        return

    creds = None
    if not args.no_upload:
        creds = py.retry(lambda: py.get_credentials("id"), "인증")
        py.retry(lambda: py.verify_channel("id", creds), "채널확인")

    for i, (d, want, have) in enumerate(targets, 1):
        print(f"\n{'='*70}\n[{i}/{len(targets)}] {d.name}\n{'='*70}")
        try:
            run([PY, "-u", "03_generate_tts.py", "--dir", str(d)])   # 빠진 것만 생성됨
            want2, have2, story = seg_status(d)
            if have2 < want2:
                print(f"  [WARN] 아직 {want2-have2}개 부족 — 다시 시도")
                run([PY, "-u", "03_generate_tts.py", "--dir", str(d)])
                want2, have2, story = seg_status(d)
            if have2 < want2:
                print(f"  [SKIP] {want2-have2}개를 끝내 못 만듦 — 재업로드 보류")
                continue

            run([PY, "-u", "04_concat_audio.py", "--dir", str(d)])
            run([PY, "-u", "05_generate_srt.py", "--dir", str(d)])
            (d / "video.mp4").unlink(missing_ok=True)
            run([PY, "-u", "06_assemble_video.py", "--dir", str(d)])

            if args.no_upload:
                print("  [완료] 재조립까지 (업로드 생략)")
                continue

            log_path, data, src_name = find_log_entry(d.name)
            if not log_path:
                print("  [SKIP] 업로드 기록 없음 — 아직 안 올린 편이라 배치가 올릴 것")
                continue

            old_id = data[src_name]["video_id"]
            schedule = data[src_name].get("schedule")

            # 배치 스크립트의 업로드 함수를 그대로 재사용 (제목·설명·태그 동일)
            import importlib.util
            mod_name = "run_id_haru_batch" if "haru" in log_path.name else "run_id_sangsang_batch"
            spec = importlib.util.spec_from_file_location(mod_name, ROOT / f"{mod_name}.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ep = next((e for e in mod.EPISODES if e["src"] == src_name), None)
            if ep is None:
                print("  [SKIP] EPISODES 에서 항목을 못 찾음")
                continue

            story_data = json.loads((d / "story.json").read_text(encoding="utf-8"))
            new_id = py.retry(
                lambda: mod.upload_id(d, story_data, creds, schedule, ep["unit_id"]),
                "재업로드", tries=3, delay=10)

            from googleapiclient.discovery import build
            yt = build("youtube", "v3", credentials=creds)
            cur = yt.videos().list(part="status", id=old_id).execute()["items"][0]["status"]
            yt.videos().update(part="status", body={"id": old_id, "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": cur.get("selfDeclaredMadeForKids", True)}}).execute()
            print(f"  [OK] 구버전 비공개: {old_id}")

            data[src_name] = {"video_id": new_id, "url": f"https://youtu.be/{new_id}",
                              "schedule": schedule, "uploaded_at": datetime.now().isoformat(),
                              "replaced_video_id": old_id,
                              "note": "TTS 세그먼트 결손 보수 후 재업로드"}
            log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [완료] https://youtu.be/{new_id}")

        except Exception as e:
            print(f"  [ERROR] {d.name}: {e}")
            continue

    print("\n=== 보수 종료 ===")


if __name__ == "__main__":
    main()
