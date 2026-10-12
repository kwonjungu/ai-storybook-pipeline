#!/usr/bin/env python3
"""상상2차 다국어 편 검수용 프레임 시트: 인트로 제목 / 퀴즈 / 핵심 장면 (사용: python _review_frames.py en|id [--out 시트.png])"""
import json, subprocess, sys, glob, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
lang = sys.argv[1]; out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"C:/Users/권준구/Desktop/다국어_상상9편/{lang}_시트.png")
ROOT = Path(__file__).parent
tmp = ROOT / "_logs_sangsang2" / f"frames_{lang}"; tmp.mkdir(parents=True, exist_ok=True)
dirs = []
for i in range(28, 37):
    d = Path((ROOT / f"_자료_상상12-20/logs/bsl{i}.dir").read_text(encoding="utf-8").strip())
    dirs.append(ROOT / "output" / f"{d.name}_{lang}")
W, H = 480, 270
rows = []
def grab(v, t, o):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1", "-vf", f"scale={W}:{H}", str(o)], stdin=subprocess.DEVNULL)
for k, d in enumerate(dirs, 28):
    v = d / "video.mp4"
    if not v.exists() or not (d / "intro.json").exists():
        continue
    intro = json.load(open(d / "intro.json"))["sec"]
    tm = json.load(open(d / "audio/timing.json", encoding="utf-8"))
    ending = [s for s in tm["slides"] if s["type"] == "ending"]
    qstart = (ending[0]["end"] if ending else tm["total_duration"] - 60) + intro
    keyf = sorted(glob.glob(str(d / "anim/key_slide_*.mp4")))
    if keyf:
        n = int(re.search(r"key_slide_(\d+)", keyf[0]).group(1))
        s = next(x for x in tm["slides"] if x["slide"] == n); kt = (s["start"] + s["end"]) / 2 + intro
    else:
        kt = (tm["slides"][-3]["start"]) + intro + 3
    ts = [intro * 0.6, qstart + 8, kt]
    fr = []
    for j, t in enumerate(ts):
        o = tmp / f"{k}_{j}.png"; grab(v, t, o); fr.append(o)
    rows.append((k, d.name, fr))
sheet = Image.new("RGB", (W * 3 + 40, (H + 24) * max(1, len(rows))), "white")
dr = ImageDraw.Draw(sheet)
try: f = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 14)
except Exception: f = None
for r, (k, name, fr) in enumerate(rows):
    y = r * (H + 24)
    dr.text((4, y + 3), f"bsl{k} {name[:60]}", fill="black", font=f)
    for j, o in enumerate(fr):
        sheet.paste(Image.open(o), (j * (W + 10), y + 22))
out.parent.mkdir(parents=True, exist_ok=True); sheet.save(out)
print("saved", out, len(rows))
