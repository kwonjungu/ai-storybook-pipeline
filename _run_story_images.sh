#!/bin/bash
# 스토리+이미지만 (TTS 제외), 중단 지점부터 이어서. 사용법: bash _run_story_images.sh bsl28 [대기할PID]
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
export PYTHONIOENCODING=utf-8
KEY="$1"; WAITPID="$2"; L="_자료_상상12-20/logs"; LOG="$L/$KEY.log"; ST="$L/$KEY.status"
SHEETS="output/통합교과_알에서동물이태어난다면2021_1학년_함께골라요_삐요와토토의신비한알탐험/characters"
step(){ echo "$1" > "$ST"; echo "===== $(date +%T) $1" >> "$LOG"; }
if [ -n "$WAITPID" ]; then while tasklist //FI "PID eq $WAITPID" | grep -q "$WAITPID"; do sleep 15; done; fi
DIR=$(grep -o "출력 폴더 자동 결정: output/.*" "$LOG" 2>/dev/null | tail -1 | sed 's/출력 폴더 자동 결정: //')
if [ -z "$DIR" ] || [ ! -f "$DIR/story.json" ]; then
  step "01 스토리"
  python -u 01_generate_story.py --dir "output/$KEY" >> "$LOG" 2>&1 || { step "FAIL 01"; exit 1; }
  DIR=$(grep -o "출력 폴더 자동 결정: output/.*" "$LOG" | tail -1 | sed 's/출력 폴더 자동 결정: //')
fi
echo "$DIR" > "$L/$KEY.dir"
if [ ! -f "$DIR/story_eval.json" ]; then
  step "01a 평가·개선 ($DIR)"
  python -u 01a_evaluate_story.py --dir "$DIR" --auto-improve >> "$LOG" 2>&1 || echo "[WARN] 01a 실패" >> "$LOG"
fi
if [[ " bsl28 bsl35 " == *" $KEY "* ]] && [ -f "$SHEETS/main_1.png" ]; then
  mkdir -p "$DIR/characters"; cp -n "$SHEETS/main_1.png" "$SHEETS/main_2.png" "$DIR/characters/"
fi
step "02 이미지"
python -u 02_generate_images.py --dir "$DIR" >> "$LOG" 2>&1 || { step "FAIL 02"; exit 1; }
if [ ! -f "$DIR/image_check.json" ]; then
  step "02a 이미지 QA"
  python -u 02a_check_images.py --dir "$DIR" --auto-regen >> "$LOG" 2>&1 || echo "[WARN] 02a 실패" >> "$LOG"
fi
step "DONE"
