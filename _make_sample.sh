#!/bin/bash
# 상상 신작 샘플 1편: 애니(새 11) → 더빙 → 조립 → Veo 인트로 붙이기. 업로드 없음.
export PYTHONIOENCODING=utf-8
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
DIR="output/통합교과_거인나라에간다면5051p_1학년_함께골라요_콩알이와점점이의거인나라여행"; LOG="_자료_상상12-20/logs/sample.log"
s(){ echo "===== $(date +%T) $1" >> "$LOG"; echo "$1" > _자료_상상12-20/logs/sample.status; }
s "11 애니"; python -u 11_animate_scenes.py --dir "$DIR" --limit 6 >> "$LOG" 2>&1 || echo "[WARN] 11" >> "$LOG"
s "SFX 전처리"; python -u sfx_prep.py --dir "$DIR" >> "$LOG" 2>&1 || echo "[WARN] sfx_prep" >> "$LOG"
s "03 더빙"; python -u 03_generate_tts.py --dir "$DIR" >> "$LOG" 2>&1 || { s "FAIL 03"; exit 1; }
s "TTS 게이트"; python -u tts_gate.py --dir "$DIR" >> "$LOG" 2>&1 || { s "FAIL gate"; exit 1; }
s "03a 점검"; python -u 03a_check_narration.py --dir "$DIR" --auto-fix >> "$LOG" 2>&1 || echo "[WARN] 03a" >> "$LOG"
s "SFX 패딩"; python -u sfx_prep.py --dir "$DIR" --pad >> "$LOG" 2>&1 || { s "FAIL sfx pad"; exit 1; }
s "04 오디오"; python -u 04_concat_audio.py --dir "$DIR" >> "$LOG" 2>&1
s "SFX 믹스"; python -u sfx_mix.py --dir "$DIR" >> "$LOG" 2>&1 || { s "FAIL sfx mix"; exit 1; }
s "05 자막"; python -u 05_generate_srt.py --dir "$DIR" >> "$LOG" 2>&1
s "07b 퀴즈"; python -u 07b_generate_quiz_slides.py --dir "$DIR" >> "$LOG" 2>&1
s "10 썸네일"; python -u 10_generate_thumbnail.py --dir "$DIR" >> "$LOG" 2>&1
s "11b 핵심장면"; python -u 11b_key_scene.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || echo "[WARN] 11b" >> "$LOG"
s "06 조립"; python -u 06_assemble_video.py --dir "$DIR" >> "$LOG" 2>&1 || { s "FAIL 06"; exit 1; }
s "DONE"
