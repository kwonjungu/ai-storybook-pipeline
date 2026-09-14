#!/bin/bash
# 영어 배치가 끝난 뒤에 한국어 큐 디스패처를 시작한다.
# 이유: 영어판도 Typecast를 쓰기 때문에 한국어 03_generate_tts 와 동시에 돌리면
#       TTS 직렬 큐 규칙(편별 03 동시 실행 금지)을 깨뜨린다.
cd "$(dirname "$0")"

echo "[WAIT] 영어 배치 종료 대기 중..."
while ! grep -q "=== 영어 배치 종료 ===" _en_batch_run.log 2>/dev/null; do
  sleep 60
done
echo "[WAIT] 영어 배치 종료 확인 — 한국어 큐 시작"

# 큐가 비면 디스패처가 스스로 끝나도록 종료 신호 파일을 미리 둔다
touch _dispatcher_stop
bash _pipeline_dispatcher.sh >> _dispatcher.log 2>&1
echo "[DONE] 한국어 큐 디스패처 종료"
