#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
UI_DIR="$PROJECT_DIR/ui"
RUNTIME_DIR="$PROJECT_DIR/.runtime"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
UI_PID_FILE="$RUNTIME_DIR/ui.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
UI_LOG="$RUNTIME_DIR/ui.log"

mkdir -p "$RUNTIME_DIR"

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

free_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

wait_http_ok() {
  local url="$1"
  local retries="${2:-20}"
  local delay="${3:-0.5}"
  for _ in $(seq 1 "$retries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

stop_pid_file "$BACKEND_PID_FILE"
stop_pid_file "$UI_PID_FILE"
free_port 8000
free_port 8812

cd "$BACKEND_DIR"
nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload >"$BACKEND_LOG" 2>&1 &
echo $! >"$BACKEND_PID_FILE"

cd "$UI_DIR"
nohup python3 -m http.server 8812 --bind 127.0.0.1 >"$UI_LOG" 2>&1 &
echo $! >"$UI_PID_FILE"

cd "$RUNTIME_DIR"

if ! wait_http_ok "http://127.0.0.1:8000/" 40 0.5; then
  echo "[ERROR] backend did not become healthy. Check $BACKEND_LOG"
  exit 1
fi

if ! wait_http_ok "http://127.0.0.1:8812/login.html" 40 0.5; then
  echo "[ERROR] ui server did not become healthy. Check $UI_LOG"
  exit 1
fi

echo "[OK] backend: http://127.0.0.1:8000/"
echo "[OK] ui:      http://127.0.0.1:8812/login.html"
echo "[INFO] logs:  $BACKEND_LOG, $UI_LOG"
