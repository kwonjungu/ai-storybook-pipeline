#!/bin/bash
# 하루 단원 배치가 끝나면 인니 전 편의 TTS 세그먼트 결손을 보수하고 필요한 편만 재업로드.
# (Gemini TTS 가 간헐적으로 빈 응답을 줘서 대사가 통째로 빠지는 일이 있음 — 배치와 동시에
#  돌리면 같은 API를 두 곳에서 두드려 실패가 더 늘기 때문에 반드시 배치 종료 후에 실행)
cd "$(dirname "$0")"
echo "[REPAIR] 하루 단원 배치 종료 대기..."
while ! grep -q "=== 하루 배치 종료 ===" _id_haru_upload.log 2>/dev/null; do
  sleep 60
done
echo "[REPAIR] 배치 종료 확인 — 결손 점검 시작"
C:/Python313/python.exe -u _repair_id_tts.py > _id_repair.log 2>&1
echo "[REPAIR] 종료"
