"""
MQTT 로거
MQTT 브로커의 모든 메시지를 SQLite에 저장
"""
import os
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from topic_registry import get_registry_summary, is_managed_status_topic

# 환경변수 로드
load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "#")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
SQLITE_PATH = os.getenv("SQLITE_PATH", "data/mqtt_logs.db")
MQTT_TOPIC_MODE = os.getenv("MQTT_TOPIC_MODE", "managed")  # managed|single|all


def utc_now_iso() -> str:
    """현재 UTC 시간을 ISO 형식으로"""
    return datetime.now(timezone.utc).isoformat()


def ensure_db(db_path: str) -> None:
    """SQLite DB 및 테이블 생성"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mqtt_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            topic TEXT NOT NULL,
            payload_text TEXT,
            payload_json TEXT,
            qos INTEGER,
            retain BOOLEAN,
            mid INTEGER
        )
    """)
    
    # 인덱스 생성
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_logs_ts ON mqtt_logs(ts_utc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mqtt_logs_topic ON mqtt_logs(topic)")
    
    conn.commit()
    conn.close()


def parse_payload(payload: bytes) -> tuple:
    """
    MQTT 페이로드 파싱
    
    Returns:
        (text_payload, json_payload)
    """
    try:
        text = payload.decode("utf-8", errors="ignore")
    except:
        text = str(payload)
    
    try:
        json_obj = json.loads(text)
        json_str = json.dumps(json_obj, ensure_ascii=False)
    except:
        json_obj = None
        json_str = None
    
    return text, json_str


def on_connect(client, userdata, flags, rc):
    """연결 콜백"""
    if rc == 0:
        print(f"[MQTT] Connected to {MQTT_HOST}:{MQTT_PORT}")
        if MQTT_TOPIC_MODE == "all":
            client.subscribe("#")
            print("[MQTT] Subscribed to topic: #")
        elif MQTT_TOPIC_MODE == "single":
            client.subscribe(MQTT_TOPIC)
            print(f"[MQTT] Subscribed to topic: {MQTT_TOPIC}")
        else:
            # 관리 모드: 상태 토픽을 와일드카드로 받고, 저장 단계에서 machine 번호 필터링
            client.subscribe("BAGO/+/Status")
            summary = get_registry_summary()
            print("[MQTT] Subscribed to topic: BAGO/+/Status (managed mode)")
            print(f"[MQTT] Managed machines: {summary.get('machine_numbers', [])}")
    else:
        print(f"[MQTT] Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """메시지 수신 콜백"""
    try:
        if MQTT_TOPIC_MODE == "managed" and not is_managed_status_topic(msg.topic):
            # 관리 대상이 아닌 Machine number 토픽은 무시
            return

        db_path = userdata.get("db_path")
        
        # 페이로드 파싱
        payload_text, payload_json = parse_payload(msg.payload)
        
        # DB에 저장
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO mqtt_logs (ts_utc, topic, payload_text, payload_json, qos, retain, mid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            utc_now_iso(),
            msg.topic,
            payload_text,
            payload_json,
            msg.qos,
            msg.retain,
            msg.mid
        ))
        
        conn.commit()
        conn.close()
        
        print(f"[MQTT] {msg.topic}: {payload_text[:50]}")
    
    except Exception as e:
        print(f"[MQTT] Error processing message: {str(e)}")


def on_disconnect(client, userdata, rc):
    """연결 해제 콜백"""
    if rc != 0:
        print(f"[MQTT] Unexpected disconnection with code {rc}")


def main():
    """메인 루프"""
    # DB 초기화
    ensure_db(SQLITE_PATH)
    
    # MQTT 클라이언트 생성
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    
    # 콜백 등록
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    
    # 사용자 데이터 전달
    client.user_data_set({"db_path": SQLITE_PATH})
    
    # 인증 설정
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    # 연결
    print(f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    
    # 루프 시작
    client.loop_forever()


if __name__ == "__main__":
    main()
