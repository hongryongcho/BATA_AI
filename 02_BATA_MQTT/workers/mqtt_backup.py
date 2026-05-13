import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import googleapiclient.discovery
import googleapiclient.errors

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

from config.gdrive_config import get_credentials


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH)

SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db",
)
GDRIVE_CREDENTIALS_JSON = os.getenv(
    "GDRIVE_CREDENTIALS_JSON",
    "config/google_credentials.json",
)
GDRIVE_TOKEN_JSON = os.getenv(
    "GDRIVE_TOKEN_JSON",
    "config/google_token.json",
)
GDRIVE_FOLDER_NAME = os.getenv(
    "GDRIVE_FOLDER_NAME",
    "BATAGOTA_MQTT_ARCHIVE",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_to_csv(db_path: str, csv_path: str, year_month: str = None) -> int:
    """
    지정된 월의 로그를 CSV로 추출
    year_month: YYYY-MM 형식 (없으면 직전월)
    """
    if year_month is None:
        now = datetime.now()
        if now.month == 1:
            year_month = f"{now.year - 1}-12"
        else:
            year_month = f"{now.year}-{now.month - 1:02d}"

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"[backup] db not found: {db_path}")
        return 0

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    # 해당 월의 데이터 조회
    prefix = f"{year_month}-"
    cursor = conn.execute(
        """
        SELECT id, ts_utc, topic, payload_text, qos, retain
        FROM mqtt_logs
        WHERE ts_utc LIKE ?
        ORDER BY id ASC
        """,
        (f"{prefix}%",),
    )
    rows = cursor.fetchall()

    if not rows:
        print(f"[backup] no data for {year_month}")
        conn.close()
        return 0

    # CSV 작성
    csv_file = Path(csv_path)
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "ts_utc", "topic", "payload_text", "qos", "retain"])
        for row in rows:
            writer.writerow(row)

    conn.close()
    print(f"[backup] exported {len(rows)} rows to {csv_path}")
    return len(rows)


def ensure_gdrive_folder(service, folder_name: str) -> str:
    """
    Google Drive에서 폴더 찾기 또는 생성.
    폴더 ID 반환
    """
    try:
        # 기존 폴더 검색
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = (
            service.files()
            .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
            print(f"[backup] found gdrive folder: {folder_id}")
            return folder_id

        # 폴더 생성
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(body=file_metadata, fields="id").execute()
        folder_id = folder.get("id")
        print(f"[backup] created gdrive folder: {folder_id}")
        return folder_id

    except googleapiclient.errors.HttpError as error:
        print(f"[backup] gdrive error: {error}")
        return None


def upload_to_gdrive(
    service, folder_id: str, csv_path: str, year_month: str
) -> dict:
    """
    CSV 파일을 Google Drive 폴더에 업로드
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        return {"status": "file_not_found", "error": str(csv_path)}

    try:
        # 월별 폴더 생성 (YYYY/MM 구조)
        year, month = year_month.split("-")
        month_folder_name = f"{year}/{month}"

        # 연도 폴더 찾기/생성
        year_query = f"name='{year}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{folder_id}' in parents"
        year_results = (
            service.files()
            .list(q=year_query, spaces="drive", fields="files(id)", pageSize=1)
            .execute()
        )
        year_files = year_results.get("files", [])

        if year_files:
            year_folder_id = year_files[0]["id"]
        else:
            year_metadata = {
                "name": year,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [folder_id],
            }
            year_folder = service.files().create(body=year_metadata, fields="id").execute()
            year_folder_id = year_folder.get("id")

        # 월 폴더 찾기/생성
        month_query = f"name='{month}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{year_folder_id}' in parents"
        month_results = (
            service.files()
            .list(q=month_query, spaces="drive", fields="files(id)", pageSize=1)
            .execute()
        )
        month_files = month_results.get("files", [])

        if month_files:
            month_folder_id = month_files[0]["id"]
        else:
            month_metadata = {
                "name": month,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [year_folder_id],
            }
            month_folder = (
                service.files().create(body=month_metadata, fields="id").execute()
            )
            month_folder_id = month_folder.get("id")

        # CSV 파일 업로드
        file_metadata = {
            "name": f"mqtt_{year_month}.csv",
            "parents": [month_folder_id],
        }
        with open(csv_file, "rb") as f:
            media = googleapiclient.http.MediaFileUpload(
                str(csv_file), mimetype="text/csv"
            )
            file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()

        file_id = file.get("id")
        file_link = file.get("webViewLink")
        print(f"[backup] uploaded to gdrive: {file_id}")

        return {
            "status": "success",
            "file_id": file_id,
            "file_link": file_link,
            "year_month": year_month,
            "uploaded_at": utc_now_iso(),
        }

    except googleapiclient.errors.HttpError as error:
        print(f"[backup] upload error: {error}")
        return {"status": "upload_failed", "error": str(error)}


def save_backup_log(result: dict, log_dir: str = None) -> None:
    """백업 통계를 JSON 파일에 저장"""
    if log_dir is None:
        log_dir = str(Path(SQLITE_PATH).parent.parent / "logs")

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir_path / f"backup_{timestamp}.json"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[backup] log saved: {log_file}")


def main() -> None:
    try:
        # Google Drive 인증
        creds = get_credentials(GDRIVE_CREDENTIALS_JSON, GDRIVE_TOKEN_JSON)
        service = googleapiclient.discovery.build("drive", "v3", credentials=creds)

        # 폴더 준비
        folder_id = ensure_gdrive_folder(service, GDRIVE_FOLDER_NAME)
        if not folder_id:
            raise Exception("Failed to get/create Google Drive folder")

        # CSV 내보내기 (직전월)
        now = datetime.now()
        if now.month == 1:
            year_month = f"{now.year - 1}-12"
        else:
            year_month = f"{now.year}-{now.month - 1:02d}"

        csv_path = (
            Path(SQLITE_PATH).parent.parent
            / "backups"
            / f"mqtt_{year_month}.csv"
        )
        exported_count = export_to_csv(SQLITE_PATH, str(csv_path), year_month)

        if exported_count == 0:
            print("[backup] no data to backup")
            save_backup_log(
                {
                    "status": "no_data",
                    "year_month": year_month,
                    "executed_at": utc_now_iso(),
                }
            )
            return

        # Google Drive에 업로드
        upload_result = upload_to_gdrive(service, folder_id, str(csv_path), year_month)
        save_backup_log(upload_result)

        print(f"[backup] completed: {upload_result['status']}")

    except Exception as e:
        print(f"[backup] error: {e}")
        save_backup_log(
            {
                "status": "failed",
                "error": str(e),
                "executed_at": utc_now_iso(),
            }
        )


if __name__ == "__main__":
    main()
