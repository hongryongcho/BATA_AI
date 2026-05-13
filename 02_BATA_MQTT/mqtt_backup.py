"""
MQTT 로그를 Google Drive에 백업
"""
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from gdrive_config import get_credentials


def export_to_csv(db_path: str, csv_path: str, year_month: str = None) -> dict:
    """
    MQTT 로그를 CSV로 내보내기
    
    Args:
        db_path: SQLite DB 경로
        csv_path: 저장할 CSV 경로
        year_month: 추출 대상 연월 (YYYY-MM, 기본값: 전월)
    
    Returns:
        {status, exported_rows, csv_path}
    """
    if year_month is None:
        # 전월 계산
        today = datetime.now(timezone.utc)
        first_day = today.replace(day=1)
        last_day_prev = first_day - timedelta(days=1)
        year_month = last_day_prev.strftime("%Y-%m")
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # 해당 연월의 데이터 추출
        start_date = f"{year_month}-01"
        end_date_obj = datetime.fromisoformat(f"{year_month}-01").replace(
            day=1
        ) + timedelta(days=32)
        end_date = end_date_obj.replace(day=1).isoformat()
        
        cur.execute(
            "SELECT id, ts_utc, topic, payload_text, payload_json, qos, retain, mid "
            "FROM mqtt_logs WHERE ts_utc >= ? AND ts_utc < ? "
            "ORDER BY ts_utc ASC",
            (start_date, end_date)
        )
        rows = cur.fetchall()
        
        # CSV 작성
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "ts_utc", "topic", "payload_text", "payload_json", "qos", "retain", "mid"])
            writer.writerows(rows)
        
        conn.close()
        
        return {
            "status": "success",
            "exported_rows": len(rows),
            "csv_path": csv_path,
            "year_month": year_month,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def ensure_gdrive_folder(service, folder_name: str) -> str:
    """
    Google Drive에 폴더 존재 확인 및 생성
    
    Args:
        service: Google Drive API 서비스
        folder_name: 생성할 폴더 이름
    
    Returns:
        폴더 ID
    """
    try:
        # 기존 폴더 검색
        results = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive",
            pageSize=10,
            fields="files(id, name)"
        ).execute()
        
        folders = results.get("files", [])
        if folders:
            return folders[0]["id"]
        
        # 폴더 생성
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()
        
        return folder.get("id")
    except Exception as e:
        raise Exception(f"Google Drive 폴더 생성 실패: {str(e)}")


def upload_to_gdrive(service, folder_id: str, csv_path: str, year_month: str = None) -> dict:
    """
    CSV를 Google Drive의 YYYY/MM 구조로 업로드
    
    Args:
        service: Google Drive API 서비스
        folder_id: 루트 폴더 ID
        csv_path: 업로드할 CSV 파일 경로
        year_month: 연월 (YYYY-MM)
    
    Returns:
        {status, file_id, file_link, year_month, uploaded_at}
    """
    if year_month is None:
        today = datetime.now(timezone.utc)
        first_day = today.replace(day=1)
        last_day_prev = first_day - timedelta(days=1)
        year_month = last_day_prev.strftime("%Y-%m")
    
    year, month = year_month.split("-")
    
    try:
        # YYYY 폴더 확인/생성
        year_folder_id = None
        results = service.files().list(
            q=f"'{folder_id}' in parents and name='{year}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive",
            pageSize=10,
            fields="files(id)"
        ).execute()
        
        folders = results.get("files", [])
        if folders:
            year_folder_id = folders[0]["id"]
        else:
            file_metadata = {
                "name": year,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [folder_id]
            }
            year_folder = service.files().create(
                body=file_metadata,
                fields="id"
            ).execute()
            year_folder_id = year_folder.get("id")
        
        # MM 폴더 확인/생성
        month_folder_id = None
        results = service.files().list(
            q=f"'{year_folder_id}' in parents and name='{month}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive",
            pageSize=10,
            fields="files(id)"
        ).execute()
        
        folders = results.get("files", [])
        if folders:
            month_folder_id = folders[0]["id"]
        else:
            file_metadata = {
                "name": month,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [year_folder_id]
            }
            month_folder = service.files().create(
                body=file_metadata,
                fields="id"
            ).execute()
            month_folder_id = month_folder.get("id")
        
        # CSV 파일 업로드
        file_metadata = {
            "name": f"mqtt_{year_month}.csv",
            "parents": [month_folder_id]
        }
        media = MediaFileUpload(csv_path, mimetype="text/csv")
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()
        
        return {
            "status": "success",
            "file_id": file.get("id"),
            "file_link": file.get("webViewLink"),
            "year_month": year_month,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def save_backup_log(result: dict, log_dir: Path = None) -> None:
    """백업 결과를 JSON으로 저장"""
    if log_dir is None:
        log_dir = Path(__file__).parent / "logs"
    
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"backup_{timestamp}.json"
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def backup_mqtt_logs(
    db_path: str,
    credentials_path: str,
    token_path: str,
    folder_name: str = "BATAGOTA_MQTT_ARCHIVE"
) -> dict:
    """
    MQTT 로그를 내보내서 Google Drive에 백업
    
    Args:
        db_path: SQLite DB 경로
        credentials_path: google_credentials.json 경로
        token_path: google_token.json 경로
        folder_name: Google Drive 폴더 이름
    
    Returns:
        {status, details}
    """
    try:
        # Google Drive 인증
        creds = get_credentials(credentials_path, token_path)
        service = build("drive", "v3", credentials=creds)
        
        # 루트 폴더 확인/생성
        root_folder_id = ensure_gdrive_folder(service, folder_name)
        
        # CSV 내보내기
        csv_path = Path(__file__).parent / "backups" / "mqtt_backup.csv"
        csv_path.parent.mkdir(exist_ok=True)
        
        export_result = export_to_csv(db_path, str(csv_path))
        if export_result["status"] != "success":
            return export_result
        
        # Google Drive에 업로드
        year_month = export_result.get("year_month")
        upload_result = upload_to_gdrive(
            service,
            root_folder_id,
            str(csv_path),
            year_month
        )
        
        # 결과 저장
        save_backup_log(upload_result)
        
        return upload_result
    except Exception as e:
        error_result = {"status": "error", "error": str(e)}
        save_backup_log(error_result)
        return error_result


if __name__ == "__main__":
    import sys
    
    db_path = os.getenv("SQLITE_PATH", "data/mqtt_logs.db")
    creds_path = os.getenv("GDRIVE_CREDENTIALS_JSON", "config/google_credentials.json")
    token_path = os.getenv("GDRIVE_TOKEN_JSON", "config/google_token.json")
    folder_name = os.getenv("GDRIVE_FOLDER_NAME", "BATAGOTA_MQTT_ARCHIVE")
    
    result = backup_mqtt_logs(db_path, creds_path, token_path, folder_name)
    print(json.dumps(result, indent=2, ensure_ascii=False))
