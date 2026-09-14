#!/bin/bash
# 중단된 에피소드를 '이미 만든 산출물은 건드리지 않고' 썸네일~업로드까지만 이어서 마무리.
# (_run_full_pipeline.sh 를 다시 돌리면 01a가 스토리를 재생성하고 01b가 이미지를 다시 사거나
#  03이 TTS를 다시 태워서 돈과 시간이 낭비된다. 재개는 반드시 이 스크립트로.)
#
# 사용법: bash _resume_pipeline.sh "output/폴더명" "2026-09-20T09:00:00+09:00"
set -e
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"

DIR="$1"
SCHEDULE="$2"
PY=C:/Python313/python.exe

for f in story.json subtitles.srt audio/timing.json; do
  if [ ! -f "$DIR/$f" ]; then
    echo "[FAIL] $f 없음 — 이 폴더는 재개 대상이 아닙니다: $DIR"; exit 1
  fi
done

echo "===== [$DIR] 재개 (썸네일 -> 조립 -> 업로드) ====="
[ -f "$DIR/thumbnail_a.png" ] || $PY -u 10_generate_thumbnail.py --dir "$DIR"
[ -f "$DIR/video.mp4" ]       || $PY -u 06_assemble_video.py --dir "$DIR"
[ -f "$DIR/book_1분할.pptx" ] || $PY -u 08_generate_book_pptx.py --dir "$DIR" --mode 1 || echo "[WARN] 08 실패, 계속 진행"

echo "===== [$DIR] 예약 발행 (schedule=$SCHEDULE) ====="
$PY -u publish_youtube.py --dir "$DIR" --channel ko --schedule "$SCHEDULE" --yes

# 썸네일 C는 publish_log.json(video_id)이 생긴 뒤에만 동작 (CLAUDE.md 14번)
BASENAME=$(basename "$DIR")
$PY -u 10b_batch_thumb_bg.py --only "$BASENAME" || echo "[WARN] 10b 실패, 계속 진행"
$PY -u 10_generate_thumbnail.py --dir "$DIR" --style c || echo "[WARN] 썸네일 C 생성 실패"
$PY -u _push_thumb_c_live.py "$DIR" || echo "[WARN] 썸네일 C 라이브 반영 실패"

echo "===== [$DIR] 완료 ====="
