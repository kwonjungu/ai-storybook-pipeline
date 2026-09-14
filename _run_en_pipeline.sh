#!/bin/bash
# 영어(HAMZZI) 에피소드: 번역 완료된 _en 폴더를 TTS부터 영상까지 조립.
# 사용법: bash _run_en_pipeline.sh "output/폴더명_en"
set -e
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
DIR="$1"
PY=C:/Python313/python.exe

echo "===== [$DIR] 영어 파이프라인 시작 ====="
$PY -u 03_generate_tts.py --dir "$DIR"          # Typecast eng (ssfm-v30, 한국어판과 같은 캐릭터 보이스)
# TTS 세그먼트 완전성 게이트 — 대사 빠진 영상이 조립되는 것을 막는다 (2026-09-14 사고)
$PY -u tts_gate.py --dir "$DIR" || { echo "[FAIL] TTS 세그먼트 결손 — 중단"; exit 1; }
$PY -u 04_concat_audio.py --dir "$DIR"
$PY -u 05_generate_srt.py --dir "$DIR"
$PY -u 07b_generate_quiz_slides.py --dir "$DIR"
$PY -u 10_generate_thumbnail.py --dir "$DIR"
if [ -f "$DIR/thumbnail_c_bg.png" ]; then
  $PY -u 10_generate_thumbnail.py --dir "$DIR" --style c || echo "[WARN] 썸네일 C 실패"
fi
$PY -u 06_assemble_video.py --dir "$DIR"
echo "===== [$DIR] 완료 ====="
