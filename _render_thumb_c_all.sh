#!/bin/bash
# thumbnail_c_bg.png 가 있는 모든 폴더에 스타일 C 썸네일을 다시 렌더 (배경 재조립 후 반영용)
cd "$(dirname "$0")"
PY=C:/Python313/python.exe
n=0
for d in output/*/thumbnail_c_bg.png; do
  dir=$(dirname "$d")
  $PY -u 10_generate_thumbnail.py --dir "$dir" --style c >/dev/null 2>&1 \
    && { echo "[OK] $(basename "$dir")"; n=$((n+1)); } \
    || echo "[FAIL] $(basename "$dir")"
done
echo "=== 렌더 완료 $n 건 ==="
