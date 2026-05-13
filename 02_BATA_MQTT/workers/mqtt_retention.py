import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH)

SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db",
)
RETENTION_DAYS = 90  # 3개월


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cleanup_old_logs(db_path: str, retention_days: int = 90) -> dict:
    """3개월 이상 된 로그를 삭제하고 통계를 반환"""
    db_file = Path(db_path)
    if not db_file.exists():
        return {"status": "db_not_found", "deleted_count": 0}

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    # 기준 날짜: 현재 - retention_days
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()

    # 삭제 전 통계
    before = conn.execute(
        "SELECT COUNT(*) as cnt FROM mqtt_logs WHERE ts_utc < ?",
        (cutoff_iso,),
    ).fetchone()
    before_count = before["cnt"] if before else 0

    # 삭제 전 전체 로그
    total_before = conn.execute("SELECT COUNT(*) as cnt FROM mqtt_logs").fetchone()
    total_before_count = total_before["cnt"] if total_before else 0

    # 삭제 실행
    cursor = conn.execute(
        "DELETE FROM mqtt_logs WHERE ts_utc < ?",
        (cutoff_iso,),
    )
    conn.commit()

    # 삭제 후 통계
    total_after = conn.execute("SELECT COUNT(*) as cnt FROM mqtt_logs").fetchone()
    total_after_count = total_after["cnt"] if total_after else 0

    conn.close()

    result = {
        "status": "success",
        "cutoff_date": cutoff_iso,
        "deleted_count": before_count,
        "total_before": total_before_count,
        "total_after": total_after_count,
        "executed_at": utc_now_iso(),
    }

    return result


def save_retention_log(result: dict, log_dir: str = None) -> None:
    """삭제 통계를 JSON 파일에 저장"""
    if log_dir is None:
        log_dir = str(Path(SQLITE_PATH).parent.parent / "logs")

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir_path / f"retention_{timestamp}.json"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[retention] log saved: {log_file}")


def main() -> None:
    print(f"[retention] starting cleanup (retention_days={RETENTION_DAYS})")
    result = cleanup_old_logs(SQLITE_PATH, RETENTION_DAYS)
    print(f"[retention] result: {result}")
    save_retention_log(result)


if __name__ == "__main__":
    main()
