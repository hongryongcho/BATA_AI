"""
Google Sheets 인증 설정 스크립트

실행: python3 setup_auth.py

- Drive + Sheets 스코프로 OAuth2 인증 수행
- algo_token.json 저장 (02_BATA_MQTT Drive 토큰과 별도 관리)
- Spreadsheet ID 입력 받아 .env 파일 생성
"""

import sys
import os
import pickle
from pathlib import Path

# 현재 디렉토리 기준으로 경로 설정
BASE_DIR = Path(__file__).parent
CREDENTIALS_PATH = BASE_DIR / "../02_BATA_MQTT/config/google_credentials.json"
TOKEN_PATH = BASE_DIR / "../02_BATA_MQTT/config/algo_token.json"
ENV_PATH = BASE_DIR / ".env"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def setup_auth():
    print("=" * 50)
    print("BATA Algo - Google 인증 설정")
    print("=" * 50)

    # credentials.json 확인
    cred_path = CREDENTIALS_PATH.resolve()
    if not cred_path.exists():
        print(f"\n[오류] credentials 파일 없음: {cred_path}")
        print("Google Cloud Console에서 OAuth2 클라이언트 시크릿을 다운로드하세요.")
        print("  1. https://console.cloud.google.com/")
        print("  2. APIs & Services → Credentials")
        print("  3. OAuth 2.0 Client ID → 다운로드")
        print(f"  4. 파일을 {cred_path} 에 저장")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError:
        print("[오류] google-auth-oauthlib 미설치. pip3 install google-auth-oauthlib 실행하세요.")
        sys.exit(1)

    # 기존 토큰 제거 (Drive 전용 토큰과 분리)
    token_path = TOKEN_PATH.resolve()
    if token_path.exists():
        print(f"\n기존 algo 토큰 발견: {token_path}")
        answer = input("토큰 재발급하시겠습니까? (y/N): ").strip().lower()
        if answer == "y":
            token_path.unlink()
            print("토큰 삭제됨. 재인증을 진행합니다.")
        else:
            print("기존 토큰 유지.")

    if not token_path.exists():
        print("\n브라우저에서 Google 계정 인증을 진행합니다...")
        print("(Sheets + Drive 권한 요청)")
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        print(f"[완료] 토큰 저장: {token_path}")
        print(f"  스코프: {list(creds.scopes)}")
    else:
        print("[확인] algo 토큰 존재함 → 인증 건너뜀")

    # Spreadsheet ID 입력
    print("\n" + "-" * 50)
    print("Google Spreadsheet ID 설정")
    print("-" * 50)

    # 기존 .env 에서 읽기
    existing_id = ""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("SPREADSHEET_ID="):
                existing_id = line.split("=", 1)[1].strip()
                break

    if existing_id and not existing_id.startswith("여기에"):
        print(f"현재 설정된 ID: {existing_id}")
        answer = input("변경하시겠습니까? (y/N): ").strip().lower()
        if answer != "y":
            print("기존 ID 유지.")
            _write_env(existing_id, token_path)
            _print_next_steps(existing_id)
            return

    print("\nGoogle Drive에서 새 스프레드시트를 만드세요:")
    print("  1. https://sheets.new 접속 (자동으로 새 시트 생성)")
    print("  2. URL 확인: https://docs.google.com/spreadsheets/d/[ID]/edit")
    print("  3. [ID] 부분을 복사해서 아래에 붙여넣기")
    print()
    sheet_id = input("Spreadsheet ID 입력: ").strip()

    if not sheet_id:
        print("[오류] ID를 입력하지 않았습니다.")
        sys.exit(1)

    _write_env(sheet_id, token_path)
    print(f"\n[완료] .env 저장: {ENV_PATH}")
    _print_next_steps(sheet_id)


def _write_env(sheet_id: str, token_path: Path):
    content = f"""# 03_BATA_ALGO 환경 설정 (자동 생성)
SPREADSHEET_ID={sheet_id}
GOOGLE_CREDENTIALS_PATH=../02_BATA_MQTT/config/google_credentials.json
GOOGLE_TOKEN_PATH=../02_BATA_MQTT/config/algo_token.json
"""
    ENV_PATH.write_text(content)


def _print_next_steps(sheet_id: str):
    print("\n" + "=" * 50)
    print("다음 단계:")
    print("=" * 50)
    print()
    print("1. Summary 시트 템플릿 초기 생성:")
    print(f"   python3 run_backtest.py --sheet-id {sheet_id} --init-sheet")
    print()
    print("2. 백테스트 실행 (기본 SPY):")
    print(f"   python3 run_backtest.py --sheet-id {sheet_id}")
    print()
    print("3. 다른 티커로 실행:")
    print(f"   python3 run_backtest.py --sheet-id {sheet_id} --ticker TQQQ")
    print()
    print("4. 파라미터 변경 후 재실행:")
    print("   → Google Sheets [Summary] 탭에서 값 수정 후 다시 실행")


if __name__ == "__main__":
    setup_auth()
