from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = PROJECT_ROOT / "interfaces" / "app_server" / "server.py"
DEFAULT_HOST = os.getenv("APP_SERVER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("APP_SERVER_PORT", "8787"))


def _server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


class AppServerHandler:
    def handle_app_dashboard_info(self, params: dict) -> dict:
        host = params.get("host", DEFAULT_HOST)
        port = int(params.get("port", DEFAULT_PORT))
        return {
            "status": "success",
            "intent": "app_dashboard_info",
            "result": {
                "name": "mqtt_app_server",
                "host": host,
                "port": port,
                "url": _server_url(host, port),
                "entry": str(SERVER_PATH),
            },
        }

    def handle_app_dashboard_start(self, params: dict) -> dict:
        host = params.get("host", DEFAULT_HOST)
        port = int(params.get("port", DEFAULT_PORT))

        if not SERVER_PATH.exists():
            return {
                "status": "error",
                "intent": "app_dashboard_start",
                "error": f"server file not found: {SERVER_PATH}",
            }

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "interfaces.app_server.server:app",
            "--host",
            str(host),
            "--port",
            str(port),
        ]

        try:
            subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return {
                "status": "error",
                "intent": "app_dashboard_start",
                "error": str(exc),
            }

        return {
            "status": "success",
            "intent": "app_dashboard_start",
            "result": {
                "url": _server_url(host, port),
                "host": host,
                "port": port,
                "message": "App dashboard start requested",
            },
        }


def app_server_router(intent: str, params: dict | None = None) -> dict:
    if params is None:
        params = {}

    handler = AppServerHandler()

    if intent == "app_dashboard_info":
        return handler.handle_app_dashboard_info(params)
    if intent == "app_dashboard_start":
        return handler.handle_app_dashboard_start(params)

    return {
        "status": "error",
        "intent": intent,
        "error": f"Unknown app server intent: {intent}",
    }
