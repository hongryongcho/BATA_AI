"""
Google Drive 업로드 스크립트
────────────────────────────
사전 준비 (최초 1회):
  1. https://console.cloud.google.com/ → 프로젝트 선택/생성
  2. API 및 서비스 → 라이브러리 → "Google Drive API" 검색 → 사용 설정
  3. API 및 서비스 → 사용자 인증 정보
     → + 사용자 인증 정보 만들기 → OAuth 클라이언트 ID
     → 애플리케이션 유형: 데스크톱 앱
     → 이름: bata-gdrive (임의)
     → 만들기 → JSON 다운로드
  4. 다운로드한 파일을 이 스크립트와 같은 폴더에 "credentials.json" 으로 저장
  5. OAuth 동의 화면 → 테스트 사용자에 hongryong.cho@gmail.com 추가

실행:
  python upload_to_gdrive.py
"""

import os
import sys

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE  = os.path.join(os.path.dirname(__file__), "token.json")
UPLOAD_FILE = os.path.join(os.path.dirname(__file__), "investor_strategy_comparison.pptx")
DRIVE_FOLDER = None  # None = 루트(내 드라이브)에 업로드, 또는 폴더 ID 문자열


def get_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print(f"[ERROR] credentials.json 파일이 없습니다.")
                print(f"        경로: {CREDS_FILE}")
                print()
                print("사전 준비:")
                print("  1. https://console.cloud.google.com/ 접속")
                print("  2. API 및 서비스 → Google Drive API → 사용 설정")
                print("  3. 사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱 → JSON 다운로드")
                print(f"  4. 다운로드 파일을 다음 경로로 저장:")
                print(f"     {CREDS_FILE}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_file(service, local_path, folder_id=None):
    from googleapiclient.http import MediaFileUpload

    filename = os.path.basename(local_path)
    mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

    print(f"업로드 중: {filename} ...")
    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink",
    ).execute()

    print(f"[완료] 파일 이름: {result['name']}")
    print(f"       파일 ID:   {result['id']}")
    print(f"       Drive 링크: {result.get('webViewLink', '(링크 없음)')}")
    return result


def upload_ppt(file_path: str, folder_id=None) -> dict:
    """다른 모듈에서 임포트하여 사용하는 업로드 함수. file_path 는 절대 경로."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"업로드 파일 없음: {file_path}")
    service = get_service()
    return upload_file(service, file_path, folder_id=folder_id)


if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FILE):
        print(f"[ERROR] 업로드 파일을 찾을 수 없습니다: {UPLOAD_FILE}")
        sys.exit(1)

    service = get_service()
    upload_file(service, UPLOAD_FILE, folder_id=DRIVE_FOLDER)
