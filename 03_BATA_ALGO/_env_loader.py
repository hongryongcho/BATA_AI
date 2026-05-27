"""
.env 파일 로더 유틸리티
03_BATA_ALGO/.env 파일에서 환경 변수를 읽음
"""

from pathlib import Path


def load_env_config() -> dict:
    env_path = Path(__file__).parent / ".env"
    result = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def get_spreadsheet_id() -> str:
    env = load_env_config()
    sid = env.get("SPREADSHEET_ID", "")
    if not sid or sid.startswith("여기에"):
        raise ValueError(
            "Spreadsheet ID가 설정되지 않았습니다.\n"
            "먼저 setup_auth.py 를 실행하세요:\n"
            "  python3 setup_auth.py"
        )
    return sid


def get_qqq_guard_spreadsheet_id() -> str:
    """QQQ Crash Guard 신호 시트 ID 반환."""
    env = load_env_config()
    sid = env.get("QQQ_GUARD_SPREADSHEET_ID", "")
    if not sid:
        raise ValueError(
            "QQQ Guard Spreadsheet ID가 설정되지 않았습니다.\n"
            "python3 create_qqq_guard_daily.py 를 먼저 실행하세요."
        )
    return sid
