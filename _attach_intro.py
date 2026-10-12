#!/usr/bin/env python3
"""완성된 video.mp4 앞에 햄찌쌤 공통 인트로(Veo, 편 제목 자동)를 붙인다. (2026-10-11)

- 인트로 제작: Desktop/햄찌인트로/finish_veo.py (Veo fast_1 테이크 + Jennifer 다국어 VO + 구독·좋아요 배지)
- 전환 대상(--next)은 본편 첫 프레임 → 인트로 끝이 본편 시작과 그대로 이어진다
- 원본은 video_nointro.mp4 로 보존, 붙인 길이는 intro.json 에 기록 (13_rewrite_metadata 퀴즈 타임스탬프 보정용)
사용법: python _attach_intro.py --dir output/폴더 [--lang ko]
"""
import argparse, json, subprocess, sys
from pathlib import Path

INTRO_DIR = Path.home() / "Desktop/햄찌인트로"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode:
        print(r.stderr[-1500:]); sys.exit(1)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--lang", default=None)
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    story = json.load(open(d / "story.json", encoding="utf-8"))
    lang = a.lang or story.get("meta", {}).get("language", "ko")
    title = story["meta"]["story_title"]
    src = d / "video_nointro.mp4"
    if not src.exists():
        (d / "video.mp4").rename(src)
    first = d / "_intro_next.png"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(first)])
    intro = d / "_intro.mp4"
    run([sys.executable, str(INTRO_DIR / "finish_veo.py"), "--lang", lang, "--vo", str(INTRO_DIR / f"vo/invite_{lang}.wav"),
         "--take", str(INTRO_DIR / "out/veo/B_veo_fast_1.mp4"), "--title", title, "--next", str(first), "--out", str(intro)])
    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(intro)]).stdout.strip())
    fc = ("[0:v]scale=1920:1080,fps=30,setsar=1,format=yuv420p[v0];[1:v]scale=1920:1080,fps=30,setsar=1,format=yuv420p[v1];"
          "[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];"
          "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(intro), "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         str(d / "video.mp4")])
    json.dump({"sec": round(dur, 3), "lang": lang, "title": title}, open(d / "intro.json", "w", encoding="utf-8"), ensure_ascii=False)
    first.unlink(missing_ok=True); intro.unlink(missing_ok=True)
    print(f"[인트로] {dur:.2f}s 붙임 → {d / 'video.mp4'}")


if __name__ == "__main__":
    main()
