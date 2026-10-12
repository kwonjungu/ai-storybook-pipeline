"""채널 OAuth 재인증 — 로그인 URL을 파일에 남기고 브라우저를 직접 연다.  python _auth_url.py en"""
import sys, os, webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
import publish_youtube as py
ch = sys.argv[1]
scopes = py.YOUTUBE_ONLY_SCOPES if ch in py.NO_DRIVE_CHANNELS else py.SCOPES
token = py.CHANNEL_TOKENS.get(ch, Path(f"token_{ch}.json"))
flow = InstalledAppFlow.from_client_secrets_file(str(py.CLIENT_SECRET), scopes)
class B:
    def open(self, url, *a, **k):
        Path(f"_auth_url_{ch}.txt").write_text(url, encoding="utf-8")
        print("URL:", url, flush=True)
        os.startfile(url)
        return True
webbrowser.register("force", None, B(), preferred=True)
creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
token.write_text(creds.to_json())
print("[인증 저장]", token, flush=True)
