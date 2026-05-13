"""
범용 Google Drive 파일 업로더
모든 파일 타입을 처리하는 일반화된 인터페이스
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.http import MediaFileUpload
from gdrive_config import get_credentials
from googleapiclient.discovery import build


def upload_file_to_gdrive(
    file_path: str,
    agent_name: str,
    file_type: str = None,
    metadata: dict = None,
    credentials_path: str = "config/google_credentials.json",
    token_path: str = "config/google_token.json"
) -> dict:
    """
    파일을 Google Drive에 업로드 (모든 파일 타입 지원)
    
    Args:
        file_path: 업로드할 파일 경로
        agent_name: 에이전트 이름 (폴더 구조: BATAGOTA_ARCHIVE/{agent_name}/)
        file_type: 파일 타입 (csv, png, pdf, json, excel 등. 없으면 자동 감지)
        metadata: 추가 메타데이터 {title, description, tags, ...}
        credentials_path: Google 인증 파일 경로
        token_path: 토큰 파일 경로
    
    Returns:
        {
            status: "success" | "error",
            file_id: str,
            file_link: str,
            agent_name: str,
            file_name: str,
            uploaded_at: str,
            error: str (실패 시)
        }
    """
    file_path_obj = Path(file_path)
    
    # 파일 존재 확인
    if not file_path_obj.exists():
        return {
            "status": "error",
            "error": f"File not found: {file_path}",
            "agent_name": agent_name
        }
    
    # 파일 타입 자동 감지
    if file_type is None:
        file_type = file_path_obj.suffix.lstrip(".").lower()
    
    try:
        # Google Drive 인증
        creds = get_credentials(credentials_path, token_path)
        service = build("drive", "v3", credentials=creds)
        
        # 루트 폴더 확인/생성 (BATAGOTA_ARCHIVE)
        root_folder_id = _ensure_folder(service, "BATAGOTA_ARCHIVE")
        
        # Agent 폴더 확인/생성 (BATAGOTA_ARCHIVE/{agent_name})
        agent_folder_id = _ensure_folder(service, agent_name, parent_id=root_folder_id)
        
        # 타입별 서브폴더 생성 (옵션)
        type_folder_id = _ensure_folder(
            service,
            f"type_{file_type}",
            parent_id=agent_folder_id
        )
        
        # 파일 메타데이터 준비
        file_metadata = {
            "name": file_path_obj.name,
            "parents": [type_folder_id],
            "description": metadata.get("description", "") if metadata else ""
        }
        
        # 파일 업로드
        media = MediaFileUpload(str(file_path_obj), mimetype=_get_mimetype(file_type))
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink, createdTime"
        ).execute()
        
        result = {
            "status": "success",
            "file_id": file.get("id"),
            "file_link": file.get("webViewLink"),
            "agent_name": agent_name,
            "file_name": file_path_obj.name,
            "file_type": file_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # 메타데이터 저장
        _save_upload_log(result)
        
        return result
        
    except Exception as e:
        error_result = {
            "status": "error",
            "error": str(e),
            "agent_name": agent_name,
            "file_name": file_path_obj.name,
            "file_type": file_type,
        }
        _save_upload_log(error_result)
        return error_result


def _ensure_folder(service, folder_name: str, parent_id: str = None) -> str:
    """
    Google Drive에 폴더 존재 확인 및 생성
    
    Args:
        service: Google Drive API 서비스
        folder_name: 폴더 이름
        parent_id: 부모 폴더 ID (None이면 루트)
    
    Returns:
        폴더 ID
    """
    try:
        # 쿼리 구성
        if parent_id:
            query = f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        else:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        # 기존 폴더 검색
        results = service.files().list(
            q=query,
            spaces="drive",
            pageSize=10,
            fields="files(id)"
        ).execute()
        
        folders = results.get("files", [])
        if folders:
            return folders[0]["id"]
        
        # 폴더 생성
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        
        if parent_id:
            file_metadata["parents"] = [parent_id]
        
        folder = service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()
        
        return folder.get("id")
    
    except Exception as e:
        raise Exception(f"Folder creation failed for '{folder_name}': {str(e)}")


def _get_mimetype(file_type: str) -> str:
    """파일 타입별 MIME 타입 반환"""
    mime_map = {
        "csv": "text/csv",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "txt": "text/plain",
        "md": "text/markdown",
    }
    return mime_map.get(file_type.lower(), "application/octet-stream")


def _save_upload_log(result: dict, log_dir: Path = None) -> None:
    """업로드 결과를 JSON으로 저장"""
    if log_dir is None:
        log_dir = Path(__file__).parent / "logs"
    
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    agent_name = result.get("agent_name", "unknown")
    log_file = log_dir / f"upload_{agent_name}_{timestamp}.json"
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python gdrive_file_upload.py <file_path> <agent_name>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    agent_name = sys.argv[2]
    
    result = upload_file_to_gdrive(file_path, agent_name)
    print(json.dumps(result, indent=2, ensure_ascii=False))
