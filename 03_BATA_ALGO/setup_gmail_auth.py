"""
Gmail OAuth2 인증 설정
━━━━━━━━━━━━━━━━━━━━━
기존 Sheets 토큰과 별도로 Gmail 전용 토큰 생성
스코프: 읽기 + 보내기 + 라벨 수정

실행: python3 setup_gmail_auth.py
"""
import pickle
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

BASE       = Path(__file__).parent
CRED_PATH  = (BASE / "../02_BATA_MQTT/config/google_credentials.json").resolve()
TOKEN_PATH = (BASE / "../02_BATA_MQTT/config/gmail_token.json").resolve()


def main():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        print("✅ 기존 Gmail 토큰 유효:", TOKEN_PATH)
        return

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            print("✅ Gmail 토큰 갱신 완료")
        except Exception:
            creds = None

    if not creds:
        print(f"[인증] credentials: {CRED_PATH}")
        flow = InstalledAppFlow.from_client_secrets_file(str(CRED_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "wb") as f:
        pickle.dump(creds, f)
    print(f"✅ Gmail 토큰 저장: {TOKEN_PATH}")
    print(f"   스코프: {creds.scopes}")


if __name__ == "__main__":
    main()
