#!/bin/bash
# _pipeline_queue.txt 를 큐로 사용해 폴더를 한 번에 하나씩(TTS 직렬 제약 준수) 전체 파이프라인 처리.
# 큐 파일 한 줄 형식: <output 폴더 경로>\t<예약발행 ISO8601>
QUEUE="_pipeline_queue.txt"
DONE_LOG="_pipeline_done.txt"
touch "$QUEUE" "$DONE_LOG"

while true; do
  LINE=$(head -n 1 "$QUEUE")
  if [ -z "$LINE" ]; then
    sleep 20
    # 종료 신호 파일이 있으면 큐가 계속 비어있을 때 종료
    if [ -f "_dispatcher_stop" ]; then
      echo "[DISPATCHER] 종료 신호 감지, 큐 비어있어 종료"
      break
    fi
    continue
  fi
  # 큐에서 첫 줄 제거
  tail -n +2 "$QUEUE" > "${QUEUE}.tmp" && mv "${QUEUE}.tmp" "$QUEUE"

  DIR=$(echo "$LINE" | cut -f1)
  SCHEDULE=$(echo "$LINE" | cut -f2)
  SAFE_NAME=$(echo "$DIR" | tr '/\\ ' '___')
  echo "[DISPATCHER] 처리 시작: $DIR (schedule=$SCHEDULE)"
  bash _run_full_pipeline.sh "$DIR" "$SCHEDULE" >> "_pipeline_log_${SAFE_NAME}.log" 2>&1
  echo -e "$DIR\t$?" >> "$DONE_LOG"
  echo "[DISPATCHER] 처리 완료: $DIR"
done
