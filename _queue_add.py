#!/usr/bin/env python3
"""task output 파일에서 '출력 폴더 자동 결정' 라인을 읽어 _pipeline_queue.txt에 큐잉.
스케줄은 _next_schedule.txt에 저장된 다음 화/목 09:00 KST를 사용하고 자동으로 다음 슬롯 계산.
사용법: python _queue_add.py <task_output_file>
"""
import sys, re
from pathlib import Path
from datetime import datetime, timedelta

task_file = Path(sys.argv[1])
text = task_file.read_text(encoding="utf-8", errors="replace")
m = re.search(r"출력 폴더 자동 결정: (output/\S+)", text)
if not m:
    print("[FAIL] 출력 폴더를 찾지 못함")
    sys.exit(1)
folder = m.group(1)

sched_file = Path("_next_schedule.txt")
if sched_file.exists():
    cur = datetime.fromisoformat(sched_file.read_text().strip())
else:
    # 오늘(2026-09-12, 토) 이후 첫 화요일 09:00 KST
    cur = datetime(2026, 9, 15, 9, 0, 0)

sched_str = cur.strftime("%Y-%m-%dT%H:%M:%S+09:00")

# 하루 간격 매일 업로드로 전환 (사용자 요청)
nxt = cur + timedelta(days=1)
sched_file.write_text(nxt.isoformat())

with open("_pipeline_queue.txt", "a", encoding="utf-8") as f:
    f.write(f"{folder}\t{sched_str}\n")

print(f"[QUEUED] {folder} -> {sched_str}")
