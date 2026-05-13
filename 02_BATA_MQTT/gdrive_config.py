"""
Google Drive OAuth 2.0 인증 핸들러
"""
import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_credentials(credentials_path: str, token_path: str = None) -> Credentials:
    """
    Google Drive OAuth 2.0 인증
    
    Args:
        credentials_path: google_credentials.json 경로
        token_path: 저장된 토큰 pickle 경로 (기본값: credentials_path 같은 폴더)
    
    Returns:
        Credentials 객체
    """
    if token_path is None:
        token_path = os.path.join(
            os.path.dirname(credentials_path),
            "google_token.json"
        )
    
    creds = None
    
    # 저장된 토큰이 있으면 로드
    if os.path.exists(token_path):
        with open(token_path, "rb") as token_file:
            creds = pickle.load(token_file)
    
    # 토큰이 없거나 유효하지 않으면 새로 생성
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # 만료된 토큰 갱신
            creds.refresh(Request())
        else:
            # 새 인증 플로우
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"{credentials_path}이 없습니다.\n"
                    "Google Cloud Console에서 OAuth 2.0 Desktop App 인증 정보를 다운로드하세요."
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path,
                SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # 토큰 저장
        with open(token_path, "wb") as token_file:
            pickle.dump(creds, token_file)
    
    return creds
