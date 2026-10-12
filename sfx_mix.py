#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sfx_mix.py -- 04(오디오 합치기) 직후 · 06(조립) 직전. timing.json 기준으로 효과음을 full_audio.wav 에 믹스.

  python sfx_mix.py --dir output/폴더

- audio/sfx_events.json 이 없거나 이벤트가 비어 있으면 아무것도 하지 않고 통과 (기존 편 영향 0)
- 멱등: 04 를 다시 돌리면 깨끗한 full_audio.wav 에서, 04 없이 다시 돌리면 full_audio.nosfx.wav 에서 시작한다
- 음량: 효과음 피크 = 대사 RMS(발화 구간) 대비 gain_db (모두 음수 = 대사 RMS 보다 낮게)
- 합산 피크가 천장(0.95)을 넘으면 look-ahead 리미터로 눌러 클리핑을 막는다
- 가능하면(ffmpeg) 믹스 전 통합 라우드니스(LUFS)에 맞춰 둔다 (대사 TTS 가 이미 약 -14 LUFS)
- 겹쳐 깔기(word) 위치: 세그먼트 wav 안에서 구두점 덩어리별 쉼/에너지에 맞춘 음절 가중 추정 (sfx_common.char_time)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import resample_poly

import sfx_lib
from sfx_common import read_wav, write_wav, envelope, word_time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CEILING = 0.95


def limiter(y, sr, ceiling=CEILING, look=0.006):
    """look-ahead 리미터. 천장을 넘지 않으면 원본 그대로."""
    peak = np.abs(y).max()
    if peak <= ceiling:
        return y, 0.0
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(y), 1e-9))
    w = 2 * int(sr * look) + 1
    g = uniform_filter1d(minimum_filter1d(need, w), w)
    return y * g, float(20 * np.log10(g.min()))


def measure_lufs(path):
    """ffmpeg ebur128 로 통합 라우드니스 (없으면 None)."""
    try:
        r = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
        return float(m[-1]) if m else None
    except Exception:
        return None


def _stat_sig(p):
    st = p.stat()
    return [st.st_size, st.st_mtime_ns]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--no-loudness", action="store_true", help="LUFS 보정 생략")
    a = ap.parse_args()
    ep = Path(a.dir)
    audio = ep / "audio"
    ev_p = audio / "sfx_events.json"
    if not ev_p.exists():
        print("[sfx_mix] sfx_events.json 없음 -- 통과")
        return 0
    events = json.loads(ev_p.read_text(encoding="utf-8")).get("events", [])
    if not events:
        print("[sfx_mix] 이벤트 없음 -- 통과")
        return 0
    notready = [e for e in events if e.get("prep") and not e.get("prep_done")]
    if notready:
        print(f"[sfx_mix] 오류: 패딩 안 된 이벤트 {len(notready)}개 -- 먼저 python sfx_prep.py --dir {ep} --pad")
        return 1

    timing = json.loads((audio / "timing.json").read_text(encoding="utf-8"))
    segmap = {(s["slide"], s["index"]): s for s in timing["segments"]}
    full_p, nosfx_p, marker_p = audio / "full_audio.wav", audio / "full_audio.nosfx.wav", audio / "full_audio.sfx.json"

    # 기준(효과음 없는) 오디오 결정
    already = False
    if marker_p.exists() and nosfx_p.exists():
        try:
            already = json.loads(marker_p.read_text(encoding="utf-8")).get("sig") == _stat_sig(full_p)
        except Exception:
            already = False
    if not already:
        nosfx_p.write_bytes(full_p.read_bytes())  # 04 가 새로 만든 깨끗한 파일
    base, sr = read_wav(nosfx_p)
    env = envelope(base, sr)
    speech_rms = float(np.sqrt((base[env > 0.01] ** 2).mean()))
    print(f"[sfx_mix] 대사 RMS {20*np.log10(speech_rms):.1f} dBFS, 이벤트 {len(events)}개")

    mix = np.zeros_like(base)
    log = []
    for e in events:
        seg = segmap.get((e["slide"], e["seg"]))
        if seg is None:
            print(f"  [경고] timing 에 {e['slide']}-{e['seg']} 없음 -- 건너뜀")
            continue
        if e["mode"] == "word":
            x, _ = read_wav(audio / seg["file"])
            rel = [word_time(x, sr, seg["text"], e["word"])]
            if e["sfx"] == "clap":
                rel = [r + 0.12 for r in rel]  # '짝' 음절 중간
        else:
            rel = e["sfx_at_in_seg"]
        y = sfx_lib.SFX[e["sfx"]]()
        if sr != sfx_lib.SR:
            y = resample_poly(y, sr, sfx_lib.SR)
        peak = speech_rms * 10 ** (e["gain_db"] / 20)
        y = y / np.abs(y).max() * peak
        for r in rel:
            t = seg["start"] + r
            i = int(t * sr)
            j = min(len(mix), i + len(y))
            if j > i:
                mix[i:j] += y[: j - i]
            log.append({"slide": e["slide"], "seg": e["seg"], "sfx": e["sfx"], "mode": e["mode"],
                        "t_audio": round(t, 3), "peak_dBFS": round(20 * np.log10(peak), 1),
                        "note": e.get("note"), "word": e.get("word")})
    out = base + mix
    raw_peak = float(np.abs(out).max())

    # 라우드니스: 믹스 전 기준 유지 (효과음이 더한 몇 dB 이하)
    gain_db = 0.0
    if not a.no_loudness:
        L0 = measure_lufs(nosfx_p)
        tmp = audio / "_sfx_tmp.wav"
        write_wav(tmp, out, sr)
        L1 = measure_lufs(tmp)
        tmp.unlink(missing_ok=True)
        if L0 is not None and L1 is not None and abs(L1 - L0) > 0.1:
            gain_db = max(-1.5, min(1.5, L0 - L1))
            out = out * 10 ** (gain_db / 20)
            print(f"[sfx_mix] LUFS 보정 {L1:.2f} -> {L0:.2f} (gain {gain_db:+.2f} dB)")
    out, lim_db = limiter(out, sr)
    write_wav(full_p, out, sr)
    marker_p.write_text(json.dumps({"sig": _stat_sig(full_p), "events": len(log)}), encoding="utf-8")
    (audio / "sfx_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sfx_mix] 합산 피크(리미터 전) {raw_peak:.3f}, 리미터 최대 감쇠 {lim_db:.2f} dB, 최종 피크 {np.abs(out).max():.3f}")
    for l in sorted(log, key=lambda l: l["t_audio"]):
        print(f"   {l['t_audio']:8.2f}s  {l['slide']:>2}-{l['seg']}  {l['sfx']:8s} {l['mode']:5s} {l.get('word') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
