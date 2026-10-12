#!/bin/bash
# 스토리·이미지가 끝난 편을 업로드 직전까지 (애니→더빙→자막→활동지 게이트→퀴즈→썸네일). 조립(06)·업로드는 별도.
# 사용법: bash _produce_until_publish.sh bsl28 bsl29 ...   (한 편씩 순서대로 — Typecast 직렬 규칙)
export PYTHONIOENCODING=utf-8
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
L="_자료_상상12-20/logs"
for KEY in "$@"; do
  DIR=$(cat "$L/$KEY.dir"); LOG="$L/$KEY.produce.log"; ST="$L/$KEY.produce.status"
  s(){ echo "$1" > "$ST"; echo "===== $(date +%T) $1" >> "$LOG"; }
  [ -d "$DIR/anim" ] || { s "11 애니"; python -u 11_animate_scenes.py --dir "$DIR" --limit 6 >> "$LOG" 2>&1 </dev/null || echo "[WARN] 11" >> "$LOG"; }
  s "SFX 전처리"; python -u sfx_prep.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || echo "[WARN] sfx_prep" >> "$LOG"
  s "03 더빙";  python -u 03_generate_tts.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 03"; continue; }
  s "TTS 게이트"; python -u tts_gate.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL TTS게이트"; continue; }
  s "03a 점검"; python -u 03a_check_narration.py --dir "$DIR" --auto-fix >> "$LOG" 2>&1 </dev/null || echo "[WARN] 03a" >> "$LOG"
  s "SFX 패딩"; python -u sfx_prep.py --dir "$DIR" --pad >> "$LOG" 2>&1 </dev/null || { s "FAIL SFX패딩"; continue; }
  s "04 오디오"; python -u 04_concat_audio.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null
  s "SFX 믹스"; python -u sfx_mix.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL SFX믹스"; continue; }
  s "11b 핵심장면"; python -u 11b_key_scene.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || echo "[WARN] 11b" >> "$LOG"   # A안: 항상 exit 0
  s "05 자막";  python -u 05_generate_srt.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null
  s "활동지 데이터"; python -u gen_activity_v2.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 활동지데이터"; continue; }
  s "07 활동지";  python -u 07_generate_worksheet.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 07"; continue; }
  s "07a 활동지QA"; python -u 07a_check_worksheet.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 07a"; continue; }
  s "07b 퀴즈";  python -u 07b_generate_quiz_slides.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null
  s "10 썸네일"; python -u 10_generate_thumbnail.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null
  s "08 그림책PPT"; python -u 08_generate_book_pptx.py --dir "$DIR" --mode 1 >> "$LOG" 2>&1 </dev/null || echo "[WARN] 08" >> "$LOG"
  s "READY(조립·업로드 대기)"
done
