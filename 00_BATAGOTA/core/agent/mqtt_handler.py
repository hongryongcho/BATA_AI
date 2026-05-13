import os
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# 02_BATA_MQTT 폴더를 sys.path에 추가
MQTT_ROOT = Path(__file__).parent.parent.parent.parent / "02_BATA_MQTT"
sys.path.insert(0, str(MQTT_ROOT))

# 실행 컨텍스트와 무관하게 MQTT 설정을 읽는다.
load_dotenv(MQTT_ROOT / ".env")

from api.status_api import MQTTStatusAPI
from topic_registry import get_registry_summary, add_machine, remove_machine


SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db",
)


class MQTTHandler:
    """BATAGOTA 마스터에서 MQTT 프로젝트를 호출하는 핸들러"""
    
    def __init__(self):
        self.api = MQTTStatusAPI(SQLITE_PATH)
    
    def handle_mqtt_report(self, params: dict) -> dict:
        """MQTT 리포트 요청"""
        return {
            "status": "success",
            "intent": "mqtt_report",
            "result": self.api.health_check(),
        }
    
    def handle_backup_status(self, params: dict) -> dict:
        """백업 상태 조회"""
        return {
            "status": "success",
            "intent": "backup_status",
            "result": self.api.get_backup_logs(limit=3),
        }
    
    def handle_retention_status(self, params: dict) -> dict:
        """정리 상태 조회"""
        return {
            "status": "success",
            "intent": "retention_status",
            "result": self.api.get_retention_logs(limit=3),
        }

    def handle_mqtt_connection_info(self, params: dict) -> dict:
        """MQTT 브로커 접속 정보 조회"""
        managed = get_registry_summary()
        return {
            "status": "success",
            "intent": "mqtt_connection_info",
            "result": {
                "host": os.getenv("MQTT_HOST", "127.0.0.1"),
                "port": int(os.getenv("MQTT_PORT", "1883")),
                "topic": os.getenv("MQTT_TOPIC", "#"),
                "topic_mode": os.getenv("MQTT_TOPIC_MODE", "managed"),
                "username_set": bool(os.getenv("MQTT_USERNAME", "")),
                "tls_enabled": bool(os.getenv("MQTT_TLS_ENABLED", "").strip()),
                "managed_machines": managed.get("machine_numbers", []),
                "managed_topics": managed.get("topics", []),
            },
        }

    def handle_topic_list(self, params: dict) -> dict:
        return {
            "status": "success",
            "intent": "mqtt_topic_list",
            "result": get_registry_summary(),
        }

    def handle_topic_add(self, params: dict) -> dict:
        machine_no = params.get("machine_no")
        if machine_no is None:
            return {"status": "error", "error": "machine_no is required"}
        return {
            "status": "success",
            "intent": "mqtt_topic_add",
            "result": add_machine(int(machine_no)),
        }

    def handle_topic_remove(self, params: dict) -> dict:
        machine_no = params.get("machine_no")
        if machine_no is None:
            return {"status": "error", "error": "machine_no is required"}
        return {
            "status": "success",
            "intent": "mqtt_topic_remove",
            "result": remove_machine(int(machine_no)),
        }

    def handle_mqtt_clients(self, params: dict) -> dict:
        """현재 MQTT 동시 접속자 수 조회 ($SYS/broker/clients/connected)"""
        host = os.getenv("MQTT_HOST", "127.0.0.1")
        port = int(os.getenv("MQTT_PORT", "1883"))
        topic = "$SYS/broker/clients/connected"

        result = {
            "status": "success",
            "intent": "mqtt_clients",
            "result": {
                "host": host,
                "port": port,
                "topic": topic,
                "connected_clients": None,
            },
        }

        event = threading.Event()

        def on_connect(client, userdata, flags, rc, properties=None):
            client.subscribe(topic)

        def on_message(client, userdata, msg):
            try:
                payload = msg.payload.decode("utf-8", errors="ignore").strip()
                result["result"]["connected_clients"] = int(payload)
            except Exception:
                result["result"]["connected_clients"] = None
            event.set()

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message

        try:
            client.connect(host, port, keepalive=30)
            client.loop_start()
            event.wait(8)
        except Exception as e:
            return {
                "status": "error",
                "intent": "mqtt_clients",
                "error": str(e),
            }
        finally:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

        if result["result"]["connected_clients"] is None:
            result["result"]["note"] = "No $SYS response within timeout"

        return result

    def handle_db_recent(self, params: dict) -> dict:
        """DB 최근 로그 조회 및 저장 상태 요약"""
        limit = params.get("limit", 20)
        try:
            limit = int(limit)
        except Exception:
            return {
                "status": "error",
                "intent": "db_recent",
                "error": "limit must be integer",
            }

        if limit < 1 or limit > 100:
            return {
                "status": "error",
                "intent": "db_recent",
                "error": "limit must be in range 1..100",
            }

        try:
            conn = sqlite3.connect(SQLITE_PATH)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT id, ts_utc, topic, substr(payload_text, 1, 120) AS payload_preview, qos, retain
                FROM mqtt_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM mqtt_logs")
            total_count = cur.fetchone()[0]

            five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            cur.execute("SELECT COUNT(*) FROM mqtt_logs WHERE ts_utc > ?", (five_min_ago,))
            last_5m_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT id, ts_utc, topic
                FROM mqtt_logs
                ORDER BY id DESC
                LIMIT 1
                """
            )
            latest_row = cur.fetchone()
            conn.close()

            latest = None
            if latest_row:
                latest = {
                    "id": latest_row[0],
                    "ts_utc": latest_row[1],
                    "topic": latest_row[2],
                }

            return {
                "status": "success",
                "intent": "db_recent",
                "result": {
                    "limit": limit,
                    "count": len(rows),
                    "total_logs": total_count,
                    "last_5m_count": last_5m_count,
                    "latest": latest,
                    "rows": [
                        {
                            "id": r[0],
                            "ts_utc": r[1],
                            "topic": r[2],
                            "payload_preview": r[3],
                            "qos": r[4],
                            "retain": r[5],
                        }
                        for r in rows
                    ],
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "intent": "db_recent",
                "error": str(e),
            }


def mqtt_router(intent: str, params: dict = None) -> dict:
    """MQTT 요청 라우터"""
    if params is None:
        params = {}
    
    handler = MQTTHandler()
    
    if intent == "mqtt_report":
        return handler.handle_mqtt_report(params)
    elif intent == "backup_status":
        return handler.handle_backup_status(params)
    elif intent == "retention_status":
        return handler.handle_retention_status(params)
    elif intent == "mqtt_connection_info":
        return handler.handle_mqtt_connection_info(params)
    elif intent == "mqtt_topic_list":
        return handler.handle_topic_list(params)
    elif intent == "mqtt_topic_add":
        return handler.handle_topic_add(params)
    elif intent == "mqtt_topic_remove":
        return handler.handle_topic_remove(params)
    elif intent == "mqtt_clients":
        return handler.handle_mqtt_clients(params)
    elif intent == "db_recent":
        return handler.handle_db_recent(params)
    else:
        return {"status": "error", "error": f"Unknown intent: {intent}"}
