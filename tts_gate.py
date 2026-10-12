#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_gate.py
TTS 세그먼트 완전성 게이트 — 03 직후, 04(오디오 합치기) 전에 반드시 통과시킬 것.

왜 필요한가 (2026-09-14 사고):
  Gemini TTS(gemini-2.5-flash-preview-tts)가 간헐적으로 빈 응답을 준다
  ("'NoneType' object has no attribute 'parts'"). 03은 3회 재시도 후 그 세그먼트를 포기하고
  다음으로 넘어가는데, 04는 '만들어진 wav만' 이어붙이므로 **그 대사가 통째로 사라진 영상**이
  조용히 완성된다. 인니 20편 중 9편이 이 상태로 업로드된 뒤에야 발견했다(재업로드 비용 발생).

  03은 이미 만든 wav 를 건너뛰므로, 다시 돌리면 '빠진 것만' 생성된다 → 재시도가 싸다.

사용:
  python tts_gate.py --dir output/폴더        # 검사 + 부족하면 03 재실행(최대 2회) + 실패 시 exit 1
  python tts_gate.py --dir output/폴더 --check-only
  # 파이썬에서: from tts_gate import ensure_complete; ensure_complete(Path(dir))
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent


def expected_segments(story: dict):
    """story.json 이 요구하는 (슬라이드번호, 세그먼트인덱스) 목록."""
    out = []
    for sl in story.get("slides", []):
        n = sl.get("slide_number")
        for i, _ in enumerate(sl.get("tts_segments", []) or []):
            out.append((n, i))
    return out


def missing_segments(ep_dir: Path):
    """story.json 기준으로 실제로 없는 세그먼트 wav 목록."""
    story = json.loads((ep_dir / "story.json").read_text(encoding="utf-8"))
    audio = ep_dir / "audio"
    missing = []
    for n, i in expected_segments(story):
        if not (audio / f"slide_{n:02d}_seg_{i:02d}.wav").exists():
            missing.append(f"slide_{n:02d}_seg_{i:02d}")
    return missing, len(expected_segments(story))


def detect_engine(ep_dir: Path):
    """이 편을 만든 TTS 엔진을 알아낸다 (03 재실행 시 같은 엔진을 넘기기 위함).
    우선순위: audio/tts_engine.json(03이 기록) > Typecast 보이스 캐시 흔적 > None(03 기본값=.env TTS_ENGINE_KO)
    2026-10-12 버그: --engine 없이 03 을 불러 Typecast 편에 Gemini 목소리가 섞였다."""
    audio = ep_dir / "audio"
    try:
        rec = json.loads((audio / "tts_engine.json").read_text(encoding="utf-8"))
        if rec.get("engine") in ("gemini", "typecast"):
            return rec["engine"]
    except Exception:
        pass
    try:  # 구버전 편: Typecast 는 voice_selection.json 에 tc_/uc_ voice_id 를 남긴다
        vs = json.loads((audio / "voice_selection.json").read_text(encoding="utf-8"))
        ids = [v.get("voice_id", "") for v in vs.values() if isinstance(v, dict)]
        if ids and all(str(i).startswith(("tc_", "uc_")) for i in ids):
            return "typecast"
    except Exception:
        pass
    try:
        meta = json.loads((ep_dir / "story.json").read_text(encoding="utf-8")).get("meta", {})
        if meta.get("typecast_voices"):
            return "typecast"
    except Exception:
        pass
    return None


def ensure_complete(ep_dir: Path, retries: int = 2, python_exe: str = None, engine: str = None) -> bool:
    """부족하면 03 을 다시 돌려 빠진 것만 채운다. 끝내 미달이면 False."""
    python_exe = python_exe or sys.executable
    engine = engine or detect_engine(ep_dir)
    print(f"[TTS게이트] 03 재실행 엔진: {engine or '(기본값 .env TTS_ENGINE_KO)'}")
    for attempt in range(retries + 1):
        missing, total = missing_segments(ep_dir)
        if not missing:
            print(f"[TTS게이트] OK — 세그먼트 {total}/{total}")
            return True
        print(f"[TTS게이트] {len(missing)}/{total} 누락: {', '.join(missing[:6])}"
              f"{' ...' if len(missing) > 6 else ''}")
        if attempt == retries:
            break
        print(f"[TTS게이트] 03 재실행 (빠진 것만 생성) — 시도 {attempt+1}/{retries}")
        cmd = [python_exe, "-u", "03_generate_tts.py", "--dir", str(ep_dir)]
        if engine:
            cmd += ["--engine", engine]
        subprocess.run(cmd, cwd=ROOT)

    missing, total = missing_segments(ep_dir)
    print(f"[TTS게이트] 실패 — {len(missing)}개를 못 만들었습니다. "
          f"이 상태로 조립하면 해당 대사가 영상에서 사라집니다.")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", dest="dir_path", required=True)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--engine", choices=["gemini", "typecast"], default=None,
                    help="03 재실행 엔진 강제 (생략 시 편에서 자동 판별)")
    args = ap.parse_args()

    ep_dir = Path(args.dir_path)
    if args.check_only:
        missing, total = missing_segments(ep_dir)
        print(f"[TTS게이트] {total - len(missing)}/{total}" +
              (f" — 누락 {len(missing)}개" if missing else " — OK"))
        sys.exit(1 if missing else 0)

    sys.exit(0 if ensure_complete(ep_dir, args.retries, engine=args.engine) else 1)


if __name__ == "__main__":
    main()
