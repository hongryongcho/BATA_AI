import json
import os
import sqlite3
import threading
import time
import uuid
import base64
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "schedule.db"
TIMEZONE = ZoneInfo("Asia/Seoul")
DEFAULT_STATE = {
    "school": {"start": "09:00", "classMinutes": 40, "breakMinutes": 10, "morningClasses": 4, "lunchMinutes": 60, "afternoonClasses": 3},
    "life": [
        {"id": "medicine", "title": "아침 약 복용", "time": "08:00", "category": "health", "repeat": "daily", "message": "아침 약을 복용할 시간입니다.", "sound": True, "browser": True},
        {"id": "breakfast", "title": "아침 식사", "time": "08:30", "category": "meal", "repeat": "daily", "message": "아침 식사 시간입니다.", "sound": True, "browser": True},
        {"id": "dinner", "title": "저녁 식사", "time": "18:30", "category": "meal", "repeat": "daily", "message": "저녁 식사 시간입니다.", "sound": True, "browser": True},
        {"id": "sleep", "title": "취침 준비", "time": "21:30", "category": "sleep", "repeat": "daily", "message": "하루를 정리하고 잠자리에 들 시간입니다.", "sound": True, "browser": True}
    ]
}

app = FastAPI(title="BATA Schedule")
_scheduler = None

class PushSubscription(BaseModel):
    endpoint: str
    keys: dict[str, str] = Field(default_factory=dict)


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS push_subscriptions (endpoint TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS alarm_log (alarm_key TEXT PRIMARY KEY, title TEXT NOT NULL, sent_at TEXT NOT NULL)")
    conn.commit()
    return conn


def vapid_private_key():
    configured = os.getenv("VAPID_PRIVATE_KEY", "")
    if configured:
        return configured
    key_path = ROOT / "data" / "vapid_private.pem"
    return key_path.read_text(encoding="utf-8") if key_path.exists() else ""


def vapid_public_key():
    configured = os.getenv("VAPID_PUBLIC_KEY", "")
    if configured:
        return configured
    key_path = ROOT / "data" / "vapid_private.pem"
    if not key_path.exists():
        return ""
    vapid = Vapid.from_pem(key_path.read_bytes())
    public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")


def get_state():
    conn = db()
    row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        conn.execute("INSERT INTO app_state(id, payload) VALUES(1, ?)", (json.dumps(DEFAULT_STATE, ensure_ascii=False),))
        conn.commit()
        payload = DEFAULT_STATE
    else:
        payload = json.loads(row[0])
    conn.close()
    return payload


def build_school_events(config):
    def fmt(total):
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"
    cursor = int(config["start"].split(":")[0]) * 60 + int(config["start"].split(":")[1])
    events = [{"id": "arrival", "time": fmt(cursor), "title": "등교 알림", "message": "학교 하루를 시작합니다.", "soundType": config.get("startSound", "school-start")}]
    total = config["morningClasses"] + config["afternoonClasses"]
    for period in range(1, total + 1):
        events.append({"id": f"class-{period}-start", "time": fmt(cursor), "title": f"{period}교시 시작", "message": f"{period}교시 수업을 시작합니다.", "soundType": config.get("startSound", "school-start")})
        cursor += config["classMinutes"]
        if period == config["morningClasses"]:
            events.append({"id": "lunch", "time": fmt(cursor), "title": "점심시간", "message": "점심시간입니다.", "soundType": "message"})
            cursor += config["lunchMinutes"]
        elif period < total:
            events.append({"id": f"break-{period}", "time": fmt(cursor), "title": "쉬는 시간", "message": "쉬는 시간입니다.", "soundType": "message"})
            cursor += config["breakMinutes"]
        if period == total:
            events.append({"id": "dismissal", "time": fmt(cursor), "title": "하교 알림", "message": "오늘 수업이 끝났습니다.", "soundType": config.get("endSound", "school-end")})
    return events


def due_events(state, now):
    if now.weekday() >= 5:
        return []
    current = now.strftime("%H:%M")
    events = build_school_events(state["school"])
    for item in state.get("life", []):
        repeat = item.get("repeat", "daily")
        if repeat == "weekdays" and now.weekday() >= 5:
            continue
        if repeat == "weekends":
            continue
        events.append({"id": item["id"], "time": item["time"], "title": item["title"], "message": item.get("message", "알림 시간입니다."), "soundType": item.get("soundType", "message")})
    return [event for event in events if event["time"] == current]


def play_local_sound(sound_type):
    sound_files = {"school-start": ROOT / "sounds" / "school-start.mp3", "school-end": ROOT / "sounds" / "school-end.mp3", "message": ROOT / "sounds" / "message.mp3"}
    sound_path = sound_files.get(sound_type)
    player = os.getenv("SCHEDULE_AUDIO_PLAYER") or shutil.which("afplay")
    if not sound_path or not sound_path.exists() or not player:
        return False
    try:
        subprocess.Popen([player, str(sound_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        print(f"[schedule] local sound failed: {exc}")
        return False


def send_pushes():
    now = datetime.now(TIMEZONE)
    state = get_state()
    for event in due_events(state, now):
        alarm_key = f"{now.date()}-{event['id']}-{event['time']}"
        conn = db()
        already_sent = conn.execute("SELECT 1 FROM alarm_log WHERE alarm_key = ?", (alarm_key,)).fetchone()
        if already_sent:
            conn.close()
            continue
        subscriptions = conn.execute("SELECT endpoint, payload FROM push_subscriptions").fetchall()
        conn.execute("INSERT INTO alarm_log(alarm_key, title, sent_at) VALUES(?, ?, ?)", (alarm_key, event["title"], now.isoformat()))
        conn.commit()
        conn.close()
        play_local_sound(event.get("soundType", "message"))
        payload = json.dumps({"title": event["title"], "body": event["message"], "tag": alarm_key}, ensure_ascii=False)
        vapid_private = vapid_private_key()
        vapid_email = os.getenv("VAPID_EMAIL", "mailto:admin@batagota.com")
        if not vapid_private:
            print(f"[schedule] Web Push skipped: VAPID_PRIVATE_KEY missing ({event['title']})")
            continue
        try:
            from pywebpush import webpush
            for endpoint, raw_subscription in subscriptions:
                try:
                    webpush(json.loads(raw_subscription), payload, vapid_private_key=vapid_private, vapid_claims={"sub": vapid_email})
                except Exception as exc:
                    print(f"[schedule] push failed: {exc}")
        except ImportError:
            print("[schedule] Web Push skipped: install pywebpush")


@app.get("/api/state")
def read_state():
    return get_state()

@app.put("/api/state")
def write_state(payload: dict):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO app_state(id, payload) VALUES(1, ?)", (json.dumps(payload, ensure_ascii=False),))
    conn.commit()
    conn.close()
    return payload

@app.get("/api/push/public-key")
def public_key():
    return {"publicKey": vapid_public_key()}

@app.post("/api/push/subscribe")
def subscribe(subscription: PushSubscription):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO push_subscriptions(endpoint, payload, created_at) VALUES(?, ?, ?)", (subscription.endpoint, subscription.model_dump_json(), datetime.now(TIMEZONE).isoformat()))
    conn.commit()
    conn.close()
    return {"status": "subscribed"}

@app.post("/api/sounds/test")
def test_sound(sound_type: str = "message"):
    if sound_type not in {"school-start", "school-end", "message"}:
        raise HTTPException(status_code=400, detail="unsupported sound type")
    return {"status": "played" if play_local_sound(sound_type) else "unavailable", "soundType": sound_type}

@app.get("/api/health")
def health():
    return {"status": "ok", "timezone": "Asia/Seoul", "push": bool(vapid_private_key())}

app.mount("/", StaticFiles(directory=ROOT, html=True), name="static")

@app.on_event("startup")
def start_scheduler():
    global _scheduler
    db().close()
    _scheduler = BackgroundScheduler(timezone=TIMEZONE)
    _scheduler.add_job(send_pushes, "interval", seconds=20, id="alarm-dispatcher", replace_existing=True, max_instances=1)
    _scheduler.start()

@app.on_event("shutdown")
def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)
