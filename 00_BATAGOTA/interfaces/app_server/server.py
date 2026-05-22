from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import paho.mqtt.client as mqtt
import qrcode
import websockets as _ws
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MQTT_ROOT = PROJECT_ROOT.parent / "02_BATA_MQTT"

load_dotenv(PROJECT_ROOT / "config" / ".env")
load_dotenv(MQTT_ROOT / ".env")

SQLITE_PATH = Path(
    os.getenv("SQLITE_PATH", "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db")
)
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PORT_WS = int(os.getenv("MQTT_PORT_WS", "9001"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

WEB_DIR    = Path(__file__).resolve().parent / "web"
TABLET_DIR = PROJECT_ROOT.parent / "04_BATA_TABLET"

MACHINE_TOPIC_RE = re.compile(r"BAGO/M(?P<machine>\d{1,3})/Status")

app = FastAPI(title="BATAGOTA MQTT Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
if TABLET_DIR.exists():
    app.mount("/tablet", StaticFiles(directory=str(TABLET_DIR), html=True), name="tablet")

_publish_lock = Lock()


class PublishRequest(BaseModel):
    action: str = ""
    payload: dict[str, Any] | None = None
    raw_json: str | None = None  # raw JSON string to publish directly (e.g. {"set":[7,3,1]})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "sqlite_path": str(SQLITE_PATH),
        "mqtt": {"host": MQTT_HOST, "port": MQTT_PORT},
        "now": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
def health_root() -> dict[str, Any]:
    return health()


@app.get("/api/ops/diagnostics")
def ops_diagnostics() -> dict[str, Any]:
    sqlite_exists = SQLITE_PATH.exists()
    sqlite_size = SQLITE_PATH.stat().st_size if sqlite_exists else 0

    return {
        "service": "batagota-app-server",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "mqtt_root": str(MQTT_ROOT),
        "sqlite": {
            "path": str(SQLITE_PATH),
            "exists": sqlite_exists,
            "size": sqlite_size,
        },
        "mqtt": {
            "host": MQTT_HOST,
            "port": MQTT_PORT,
            "username_configured": bool(MQTT_USERNAME),
            "password_configured": bool(MQTT_PASSWORD),
        },
        "web": {
            "dir": str(WEB_DIR),
            "index_exists": (WEB_DIR / "index.html").exists(),
        },
    }


@app.get("/api/machines")
def machines() -> dict[str, Any]:
    machine_set: set[int] = set()

    cfg_path = MQTT_ROOT / "config" / "topic_machines.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            for m in data:
                try:
                    machine_set.add(int(m))
                except Exception:
                    continue
        except Exception:
            pass

    if SQLITE_PATH.exists():
        conn = sqlite3.connect(SQLITE_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT topic
            FROM mqtt_logs
            WHERE topic LIKE 'BAGO/M%/Status'
            ORDER BY topic
            """
        )
        for (topic,) in cur.fetchall():
            match = MACHINE_TOPIC_RE.match(topic or "")
            if match:
                machine_set.add(int(match.group("machine")))
        conn.close()

    machines_sorted = sorted(machine_set)
    return {"status": "success", "machines": machines_sorted, "count": len(machines_sorted)}


@app.get("/api/machine/{machine_no}/overview")
def machine_overview(machine_no: int) -> dict[str, Any]:
    _validate_machine(machine_no)
    _ensure_db_exists()

    topic = f"BAGO/M{machine_no}/Status"
    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM mqtt_logs WHERE topic = ?", (topic,))
    total = cur.fetchone()[0]

    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cur.execute(
        "SELECT COUNT(*) FROM mqtt_logs WHERE topic = ? AND ts_utc > ?",
        (topic, one_hour_ago),
    )
    last_hour = cur.fetchone()[0]

    cur.execute(
        """
        SELECT id, ts_utc, payload_text, qos, retain
        FROM mqtt_logs
        WHERE topic = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (topic,),
    )
    row = cur.fetchone()
    conn.close()

    latest = None
    if row:
        latest = {
            "id": row[0],
            "ts_utc": row[1],
            "payload": row[2],
            "qos": row[3],
            "retain": row[4],
        }

    return {
        "status": "success",
        "machine_no": machine_no,
        "topic": topic,
        "total": total,
        "last_hour": last_hour,
        "latest": latest,
        "has_data": total > 0,
        "message": "ok" if total > 0 else "데이터 없음 (미수신 또는 비구독 topic)",
    }


@app.get("/api/machine/{machine_no}/recent")
def machine_recent(machine_no: int, limit: int = 30) -> dict[str, Any]:
    _validate_machine(machine_no)
    _ensure_db_exists()
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be in range 1..200")

    topic = f"BAGO/M{machine_no}/Status"
    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ts_utc, topic, substr(payload_text, 1, 200) AS payload_preview, qos, retain
        FROM mqtt_logs
        WHERE topic = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (topic, limit),
    )
    rows = [
        {
            "id": r[0],
            "ts_utc": r[1],
            "topic": r[2],
            "payload_preview": r[3],
            "qos": r[4],
            "retain": r[5],
        }
        for r in cur.fetchall()
    ]
    conn.close()

    return {
        "status": "success",
        "machine_no": machine_no,
        "rows": rows,
        "count": len(rows),
        "has_data": len(rows) > 0,
        "message": "ok" if rows else "데이터 없음 (미수신 또는 비구독 topic)",
    }


@app.post("/api/machine/{machine_no}/publish")
def machine_publish(machine_no: int, request: PublishRequest) -> dict[str, Any]:
    _validate_machine(machine_no)

    topic = f"BAGO/M{machine_no}/Cmd"

    # raw_json 우선 사용 (HMI 프로토콜 형식: {"set":[7,3,1]} 등)
    if request.raw_json:
        try:
            parsed = json.loads(request.raw_json)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"raw_json parse error: {exc}") from exc
        payload = json.dumps(parsed, ensure_ascii=False)
    else:
        action = (request.action or "").strip().upper()
        if not action:
            raise HTTPException(status_code=400, detail="action or raw_json is required")
        body = {
            "action": action,
            "payload": request.payload or {},
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "source": "batagota_app_server",
        }
        payload = json.dumps(body, ensure_ascii=False)

    with _publish_lock:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            info = client.publish(topic, payload=payload, qos=1, retain=False)
            client.loop(timeout=0.3)
            mid = getattr(info, "mid", None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"mqtt publish failed: {exc}") from exc
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    return {
        "status": "success",
        "machine_no": machine_no,
        "topic": topic,
        "mid": mid,
        "payload_sent": payload,
    }


_QR_PAGE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BATA Monitor — QR</title>
<style>
  body{{margin:0;background:#0b1220;color:#d9ecff;font-family:'Segoe UI',sans-serif;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        min-height:100vh;gap:20px;padding:24px;box-sizing:border-box}}
  h1{{font-size:22px;letter-spacing:1px;color:#33d7c3;margin:0}}
  .qr-box{{background:#fff;border-radius:16px;padding:12px;display:inline-flex}}
  .qr-box img{{width:240px;height:240px;display:block}}
  .url-box{{background:#16233a;border:1px solid #2f5fa9;border-radius:10px;
             padding:12px 20px;font-size:14px;word-break:break-all;max-width:320px;
             text-align:center;color:#aac7ea}}
  button{{background:#33d7c3;color:#0b1220;border:none;border-radius:8px;
          padding:10px 24px;font-size:15px;font-weight:700;cursor:pointer}}
  button:active{{opacity:0.8}}
  .hint{{font-size:12px;color:#86abd8}}
</style>
</head>
<body>
<h1>BATA Monitor</h1>
<div class="qr-box">
  <img src="/qr.png?url={url}" alt="QR Code">
</div>
<div class="url-box">{url}</div>
<button onclick="navigator.clipboard.writeText('{url}').then(()=>this.textContent='Copied!').catch(()=>this.textContent='Copy failed')">Copy URL</button>
<span class="hint">QR을 스캔하거나 URL을 복사해서 접속하세요</span>
</body>
</html>"""


@app.get("/qr", response_class=HTMLResponse)
def qr_page(request: Request) -> HTMLResponse:
    url = str(request.base_url).rstrip("/") + "/tablet/"
    return HTMLResponse(_QR_PAGE_HTML.format(url=url))


@app.get("/qr.png")
def qr_png(url: str) -> StreamingResponse:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.websocket("/mqtt-ws")
async def mqtt_ws_proxy(ws: WebSocket) -> None:
    await ws.accept()
    try:
        async with _ws.connect(f"ws://127.0.0.1:{MQTT_PORT_WS}") as broker:
            async def c2b() -> None:
                while True:
                    data = await ws.receive_bytes()
                    await broker.send(data)

            async def b2c() -> None:
                while True:
                    data = await broker.recv()
                    if isinstance(data, str):
                        await ws.send_text(data)
                    else:
                        await ws.send_bytes(data)

            done, pending = await asyncio.wait(
                [asyncio.ensure_future(c2b()), asyncio.ensure_future(b2c())],
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for t in pending:
                t.cancel()
    except (WebSocketDisconnect, Exception):
        pass


def _validate_machine(machine_no: int) -> None:
    if machine_no < 1 or machine_no > 999:
        raise HTTPException(status_code=400, detail="machine_no must be in range 1..999")


def _ensure_db_exists() -> None:
    if not SQLITE_PATH.exists():
        raise HTTPException(status_code=500, detail=f"sqlite db not found: {SQLITE_PATH}")
