#!/bin/bash
# 인니 채널: 상상 단원 배치가 끝나면 이어서 하루 단원 배치까지 자동 실행.
# (두 배치 모두 Gemini TTS 를 쓰므로 동시에 돌리지 않고 직렬로 잇는다)
cd "$(dirname "$0")"
PY=C:/Python313/python.exe

echo "[CHAIN] 상상 단원 배치 종료 대기..."
while ! grep -q "=== 전체 배치 종료 ===" _id_batch_upload.log 2>/dev/null; do
  sleep 60
done
echo "[CHAIN] 상상 완료 확인 — 하루 단원 시작"

$PY -u run_id_haru_batch.py > _id_haru_upload.log 2>&1
echo "[CHAIN] 하루 단원 배치 종료"
