import os
from pathlib import Path
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError
import pickle


SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_credentials(credentials_path: str, token_path: str = None):
    """
    Google Drive API 인증.
    - Service Account JSON이 있으면 사용
    - 없으면 OAuth 클라이언트 시크릿으로 인증
    """
    creds = None

    if token_path and Path(token_path).exists():
        try:
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
        except Exception as e:
            print(f"[gdrive] token load failed: {e}")
            creds = None

    if creds and hasattr(creds, "expired") and creds.expired:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None

    if not creds or not creds.valid:
        cred_path = Path(credentials_path)
        if not cred_path.exists():
            raise FileNotFoundError(
                f"credentials not found: {credentials_path}\n"
                "See: https://developers.google.com/drive/api/quickstart/python"
            )

        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        creds = flow.run_local_server(port=0)

        if token_path:
            token_dir = Path(token_path).parent
            token_dir.mkdir(parents=True, exist_ok=True)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

    return creds
