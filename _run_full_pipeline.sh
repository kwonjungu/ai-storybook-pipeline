#!/bin/bash
# 하나의 output 폴더에 대해 스토리 생성 이후 전체 파이프라인을 예약발행까지 실행.
# 사용법: bash _run_full_pipeline.sh "output/폴더명" "2026-09-16T09:00:00+09:00"
set -e
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"

DIR="$1"
SCHEDULE="$2"

if [ ! -f "$DIR/story.json" ]; then
  echo "[FAIL] story.json 없음: $DIR"
  exit 1
fi

echo "===== [$DIR] 파이프라인 시작 ====="

python -u 01a_evaluate_story.py --dir "$DIR" --auto-improve || echo "[WARN] 01a 실패, 계속 진행"
python -u 01b_analyze_shorts_plan.py --dir "$DIR" --with-images
python -u 02a_check_images.py --dir "$DIR" --auto-regen || echo "[WARN] 02a 실패, 계속 진행"
python -u 11_animate_scenes.py --dir "$DIR" --limit 6 || echo "[WARN] 11 실패, 계속 진행"
python -u 03_generate_tts.py --dir "$DIR"
# TTS 세그먼트 완전성 게이트 — 대사 빠진 영상이 조립되는 것을 막는다 (2026-09-14 사고)
python -u tts_gate.py --dir "$DIR" || { echo "[FAIL] TTS 세그먼트 결손 — 중단"; exit 1; }
python -u 03a_check_narration.py --dir "$DIR" --auto-fix || echo "[WARN] 03a 실패, 계속 진행"
python -u 04_concat_audio.py --dir "$DIR"
python -u 05_generate_srt.py --dir "$DIR"
python -u 07_generate_worksheet.py --dir "$DIR"
python -u 07a_check_worksheet.py --dir "$DIR" || echo "[WARN] 07a 실패, 계속 진행"
python -u 07b_generate_quiz_slides.py --dir "$DIR"
python -u 09b_smart_shorts.py --dir "$DIR" || echo "[WARN] 09b 실패, 계속 진행"
python -u 10_generate_thumbnail.py --dir "$DIR"
python -u 06_assemble_video.py --dir "$DIR"
python -u 08_generate_book_pptx.py --dir "$DIR" --mode 1 || echo "[WARN] 08 실패, 계속 진행"

echo "===== [$DIR] 예약 발행 (schedule=$SCHEDULE) ====="
python -u publish_youtube.py --dir "$DIR" --channel ko --schedule "$SCHEDULE" --yes

# ★ 썸네일 C(사진 배경분리 액션) — publish_log.json(video_id)이 있어야 10b가 대상으로 인식함
#   → 반드시 publish 이후에 실행. 배경 생성 → 스타일C 합성 → 라이브 썸네일 교체까지.
BASENAME=$(basename "$DIR")
echo "===== [$DIR] 썸네일 C 배경분리 액션 ====="
python -u 10b_batch_thumb_bg.py --only "$BASENAME" || echo "[WARN] 10b 실패, 계속 진행"
python -u 10_generate_thumbnail.py --dir "$DIR" --style c || echo "[WARN] 썸네일 C 생성 실패, 계속 진행"
python -u _push_thumb_c_live.py "$DIR" || echo "[WARN] 썸네일 C 라이브 반영 실패"

echo "===== [$DIR] 완료 ====="
