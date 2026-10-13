#!/bin/bash
# 인니 상상2(bsl28~36) 하루 1편: Gemini TTS 무료 한도(100req/일, 편당 ~75) 때문에 매일 한 편씩 만들고 예약 업로드.
# 작업 스케줄러가 매일 1회 실행. 9편 다 올라가면 아무것도 안 함.
#   1) 다음 미완성 편 1편 생성(--no-upload)  2) 완성본 표식 누출 검사(S1/<s1/>)  3) 통과분 예약 업로드
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
L="_logs_sangsang2"; mkdir -p "$L"; LOG="$L/id_daily_$(date +%m%d).log"
exec >> "$LOG" 2>&1 </dev/null
echo "===== $(date '+%F %T') 시작"
DIRS=$(for k in 28 29 30 31 32 33 34 35 36; do echo "$(cat _자료_상상12-20/logs/bsl$k.dir)_id"; done)
done_n=0; for d in $DIRS; do [ -f "$d/video.mp4" ] && [ -f "$d/intro.json" ] && done_n=$((done_n+1)) || break; done
echo "완성 $done_n/9"
if [ "$done_n" -lt 9 ]; then
  python -u run_id_sangsang_batch.py --unit sangsang2 --no-upload --limit $((done_n+1))
  done_n=0; for d in $DIRS; do [ -f "$d/video.mp4" ] && [ -f "$d/intro.json" ] && done_n=$((done_n+1)) || break; done
fi
# 번역 표식 누출 검사 — 걸리면 그 편부터 업로드하지 않음 (10-12 bsl28 'S1' 사고)
ok_n=0; for d in $DIRS; do
  [ $ok_n -ge $done_n ] && break
  if grep -qE '\bS[0-9]\b|<s[0-9]|</?w[0-9]>' "$d/subtitles.srt"; then echo "[중단] 표식 누출: $d"; break; fi
  ok_n=$((ok_n+1))
done
echo "업로드 대상 앞 $ok_n 편"
[ $ok_n -gt 0 ] && python -u run_id_sangsang_batch.py --unit sangsang2 --limit $ok_n
echo "===== $(date '+%F %T') 끝"
