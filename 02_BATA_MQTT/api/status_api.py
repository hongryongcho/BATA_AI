import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class MQTTStatusAPI:
    """MQTT 프로젝트 상태 조회 API"""
    
    def __init__(self, sqlite_path: str):
        self.sqlite_path = sqlite_path
    
    def get_db_stats(self) -> dict:
        """현재 DB 통계"""
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cur = conn.cursor()
            
            # 전체 로그 수
            cur.execute("SELECT COUNT(*) FROM mqtt_logs")
            total_count = cur.fetchone()[0]
            
            # 최근 1시간
            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            cur.execute("SELECT COUNT(*) FROM mqtt_logs WHERE ts_utc > ?", (one_hour_ago,))
            last_hour = cur.fetchone()[0]
            
            # 최근 24시간
            one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            cur.execute("SELECT COUNT(*) FROM mqtt_logs WHERE ts_utc > ?", (one_day_ago,))
            last_day = cur.fetchone()[0]
            
            # 최근 메시지 시간
            cur.execute("SELECT ts_utc FROM mqtt_logs ORDER BY id DESC LIMIT 1")
            last_msg = cur.fetchone()
            
            conn.close()
            
            return {
                "status": "ok",
                "total_logs": total_count,
                "last_hour": last_hour,
                "last_24h": last_day,
                "last_message_at": last_msg[0] if last_msg else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_backup_logs(self, limit: int = 5) -> dict:
        """최근 백업 로그"""
        try:
            log_dir = Path(self.sqlite_path).parent.parent / "logs"
            backup_logs = sorted(
                log_dir.glob("backup_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )[:limit]
            
            results = []
            for log_file in backup_logs:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append({
                        "file": log_file.name,
                        "status": data.get("status"),
                        "year_month": data.get("year_month"),
                        "executed_at": data.get("executed_at"),
                    })
            
            return {
                "status": "ok",
                "backup_logs": results,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_retention_logs(self, limit: int = 5) -> dict:
        """최근 정리 로그"""
        try:
            log_dir = Path(self.sqlite_path).parent.parent / "logs"
            retention_logs = sorted(
                log_dir.glob("retention_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )[:limit]
            
            results = []
            for log_file in retention_logs:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append({
                        "file": log_file.name,
                        "status": data.get("status"),
                        "deleted_count": data.get("deleted_count"),
                        "total_before": data.get("total_before"),
                        "total_after": data.get("total_after"),
                        "executed_at": data.get("executed_at"),
                    })
            
            return {
                "status": "ok",
                "retention_logs": results,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def health_check(self) -> dict:
        """전체 상태 체크"""
        try:
            stats = self.get_db_stats()
            backups = self.get_backup_logs(limit=1)
            retentions = self.get_retention_logs(limit=1)
            
            return {
                "mqtt_project": "02_BATA_MQTT",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "db": stats,
                "latest_backup": backups.get("backup_logs", [{}])[0] if backups.get("status") == "ok" and backups.get("backup_logs") else {},
                "latest_retention": retentions.get("retention_logs", [{}])[0] if retentions.get("status") == "ok" and retentions.get("retention_logs") else {},
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "error": str(e)}
