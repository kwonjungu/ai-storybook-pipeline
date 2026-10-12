"""교체된 옛 영상 삭제 (한국어 채널).  python _delete_replaced.py <옛ID> <새ID>
새 영상이 예약돼 있는지 확인한 뒤에만 옛 영상을 지운다."""
import sys
import publish_youtube as pub
from googleapiclient.discovery import build

old, new = sys.argv[1], sys.argv[2]
c = pub.get_credentials("ko"); pub.verify_channel("ko", c)
yt = build("youtube", "v3", credentials=c)
st = yt.videos().list(part="status", id=new).execute()["items"][0]["status"]
if not st.get("publishAt"):
    sys.exit(f"[중단] 새 영상 {new} 예약이 확인되지 않음 — 옛 영상 유지")
print(f"새 영상 {new} 예약 {st['publishAt']} 확인")
pub.retry(lambda: yt.videos().delete(id=old).execute(), "옛 영상 삭제")
left = yt.videos().list(part="id", id=old).execute()["items"]
print("옛 영상 삭제 완료" if not left else "[경고] 아직 남아 있음")
