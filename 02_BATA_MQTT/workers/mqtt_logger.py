import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH)

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "#")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_db(db_path: str) -> sqlite3.Connection:
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mqtt_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            topic TEXT NOT NULL,
            payload_text TEXT,
            payload_json TEXT,
            qos INTEGER NOT NULL,
            retain INTEGER NOT NULL,
            mid INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mqtt_logs_ts
        ON mqtt_logs(ts_utc)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mqtt_logs_topic
        ON mqtt_logs(topic)
        """
    )
    conn.commit()
    return conn


def parse_payload(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    text = text.strip()
    payload_json = None

    if text:
        try:
            obj = json.loads(text)
            payload_json = json.dumps(obj, ensure_ascii=False)
        except Exception:
            payload_json = None

    return text, payload_json


def main() -> None:
    conn = ensure_db(SQLITE_PATH)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"[mqtt-logger] connected rc={reason_code}")
        client.subscribe(MQTT_TOPIC)
        print(f"[mqtt-logger] subscribed topic={MQTT_TOPIC}")

    def on_message(client, userdata, msg):
        payload_text, payload_json = parse_payload(msg.payload)
        conn.execute(
            """
            INSERT INTO mqtt_logs
            (ts_utc, topic, payload_text, payload_json, qos, retain, mid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                msg.topic,
                payload_text,
                payload_json,
                int(msg.qos),
                int(msg.retain),
                int(msg.mid),
            ),
        )
        conn.commit()
        print(f"[mqtt-logger] saved topic={msg.topic} qos={msg.qos}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[mqtt-logger] broker={MQTT_HOST}:{MQTT_PORT} db={SQLITE_PATH}")
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
