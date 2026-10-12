#!/bin/bash
# 상상 12~20차시 한국어 예약 업로드 (화·목 09:00, 10/14~11/11). 편별 제작(READY)을 기다렸다가
# 06 조립 → 공통 인트로 → 예약 업로드(Drive 링크 포함) → 썸네일 C. 차시 순서대로 한 편씩.
export PYTHONIOENCODING=utf-8
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
L="_자료_상상12-20/logs"
# 여유 메모리 2GB 이상일 때만 다음 무거운 단계 시작 (10-12 메모리 부족으로 체인이 두 번 끊김)
wait_mem(){ while true; do f=$(python _free_mem_mb.py); [ "${f:-0}" -ge 2048 ] && break; echo "$(date +%T) [메모리 대기] ${f}MB" >> "$L/chain_mem.log"; sleep 30; done; }
PLAN="bsl28 2026-10-14
bsl29 2026-10-16
bsl30 2026-10-21
bsl31 2026-10-23
bsl32 2026-10-28
bsl33 2026-10-30
bsl34 2026-11-04
bsl35 2026-11-06
bsl36 2026-11-11"
while read KEY DAY; do
  SCHED="${DAY}T09:00:00+09:00"; DIR=$(cat "$L/$KEY.dir"); LOG="$L/$KEY.publish.log"; ST="$L/$KEY.publish.status"
  s(){ echo "$1" > "$ST"; echo "===== $(date +%T) $1" >> "$LOG"; }
  [ -f "$DIR/publish_log.json" ] && { s "SKIP 이미 업로드됨"; continue; }
  wait_mem
  # 메모리 부족으로 체인이 끊긴 뒤(10-12) 제작·업로드를 한 줄로: 제작이 안 끝난 편은 여기서 직접 만든다
  if ! grep -q "^READY" "$L/$KEY.produce.status" 2>/dev/null; then
    if [ "$KEY" = "bsl34" ]; then   # 80점(기준 88) — 01a 개선이 'slide_number' 오류로 실패했던 편. 2회 재시도
      for try in 1 2; do
        passed=$(python -c "import json,sys;e=json.load(open(sys.argv[1],encoding='utf-8'));e=e[-1] if isinstance(e,list) else e;print(e.get('passed'))" "$DIR/story_eval.json")
        [ "$passed" = "True" ] && break
        s "스토리 재개선 $try"; bash _repair_story_images.sh bsl34 0 </dev/null
      done
      passed=$(python -c "import json,sys;e=json.load(open(sys.argv[1],encoding='utf-8'));e=e[-1] if isinstance(e,list) else e;print(e.get('passed'))" "$DIR/story_eval.json")
      [ "$passed" = "True" ] || { s "SKIP 스토리 미달(88점 미만) — 사용자 확인 필요"; continue; }
    fi
    s "제작"; bash _produce_until_publish.sh "$KEY" </dev/null
  fi
  grep -q "^FAIL" "$L/$KEY.produce.status" && { s "SKIP 제작 실패: $(cat $L/$KEY.produce.status)"; continue; }
  wait_mem; s "06 조립"; rm -f "$DIR/video.mp4" "$DIR/video_nointro.mp4" "$DIR/intro.json"
  python -u 06_assemble_video.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 06"; continue; }
  wait_mem; s "인트로"; python -u _attach_intro.py --dir "$DIR" >> "$LOG" 2>&1 </dev/null || { s "FAIL 인트로"; continue; }
  s "업로드 예약 $SCHED"
  python -u publish_youtube.py --dir "$DIR" --channel ko --schedule "$SCHED" --yes >> "$LOG" 2>&1 </dev/null || { s "FAIL 업로드"; continue; }
  B=$(basename "$DIR")
  s "썸네일 C"
  python -u 10b_batch_thumb_bg.py --only "$B" >> "$LOG" 2>&1 </dev/null || echo "[WARN] 10b" >> "$LOG"
  python -u 10_generate_thumbnail.py --dir "$DIR" --style c >> "$LOG" 2>&1 </dev/null || echo "[WARN] 썸네일C" >> "$LOG"
  python -u _push_thumb_c_live.py "$DIR" >> "$LOG" 2>&1 </dev/null || echo "[WARN] 썸네일C 반영" >> "$LOG"
  rm -rf "$DIR/_images_old" "$DIR/anim/_layers"/*_poseA.png "$DIR/anim/_layers"/*_poseB.png 2>/dev/null   # 임시물 정리
  s "DONE 예약 $SCHED"
done <<< "$PLAN"
