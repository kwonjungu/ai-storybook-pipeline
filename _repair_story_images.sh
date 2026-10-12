#!/bin/bash
# 재평가 → (스토리가 바뀌었거나 FORCE_IMG=1 이면) 이미지 전부 재생성 → 이미지 QA
export PYTHONIOENCODING=utf-8
KEY="$1"; FORCE_IMG="$2"; L="_자료_상상12-20/logs"; LOG="$L/$KEY.repair.log"; ST="$L/$KEY.status"
DIR=$(cat "$L/$KEY.dir"); step(){ echo "$1" > "$ST"; echo "===== $(date +%T) $1" >> "$LOG"; }
h0=$(md5sum "$DIR/story.json" | cut -d' ' -f1)
step "재평가·개선"
python -u 01a_evaluate_story.py --dir "$DIR" --auto-improve --force >> "$LOG" 2>&1 || echo "[WARN] 01a 실패" >> "$LOG"
h1=$(md5sum "$DIR/story.json" | cut -d' ' -f1)
if [ "$h0" != "$h1" ] || [ "$FORCE_IMG" = "1" ]; then
  step "이미지 재생성"
  mkdir -p "$DIR/_images_old"; mv "$DIR"/images/* "$DIR/_images_old/" 2>/dev/null; rm -f "$DIR/image_check.json"
  python -u 02_generate_images.py --dir "$DIR" >> "$LOG" 2>&1 || { step "FAIL 02"; exit 1; }
  step "이미지 QA"
  python -u 02a_check_images.py --dir "$DIR" --auto-regen >> "$LOG" 2>&1 || echo "[WARN] 02a 실패" >> "$LOG"
fi
step "DONE"
