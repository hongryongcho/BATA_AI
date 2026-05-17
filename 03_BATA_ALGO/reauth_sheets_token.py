"""
Google Sheets 전용 OAuth 토큰 재인증 스크립트

목적:
- 03_BATA_ALGO에서 사용하는 분리 토큰(algo_token.json)을 강제로 재발급
- 기존 02_BATA_MQTT 토큰과 혼용되는 문제를 방지

실행:
  python3 reauth_sheets_token.py
"""

from __future__ import annotations

import pickle
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from _env_loader import load_env_config
from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main():
    base_dir = Path(__file__).parent
    env = load_env_config()

    cred_rel = env.get("GOOGLE_CREDENTIALS_PATH", GOOGLE_CREDENTIALS_PATH)
    token_rel = env.get("GOOGLE_TOKEN_PATH", GOOGLE_TOKEN_PATH)

    cred_path = (base_dir / cred_rel).resolve()
    token_path = (base_dir / token_rel).resolve()

    print("=" * 60)
    print("Google Sheets 토큰 재인증")
    print("=" * 60)
    print(f"credentials: {cred_path}")
    print(f"token:       {token_path}")

    if not cred_path.exists():
        raise FileNotFoundError(
            f"credentials 파일을 찾지 못했습니다: {cred_path}\n"
            "Google Cloud OAuth 클라이언트 시크릿을 준비한 뒤 다시 실행하세요."
        )

    if token_path.exists():
        backup = token_path.with_suffix(token_path.suffix + ".bak")
        token_path.replace(backup)
        print(f"기존 토큰 백업: {backup}")

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)

    print("재인증 완료")
    print(f"새 토큰 저장: {token_path}")
    print(f"승인 스코프: {sorted(list(creds.scopes or []))}")


if __name__ == "__main__":
    main()
