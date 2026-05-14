#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"

check_pid() {
  local name="$1"
  local pid_file="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$name pid: $pid (running)"
      return
    fi
  fi
  echo "$name pid: not running"
}

check_http() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)"
  echo "$name http: $code ($url)"
}

check_pid "backend" "$RUNTIME_DIR/backend.pid"
check_pid "ui" "$RUNTIME_DIR/ui.pid"
check_http "backend" "http://127.0.0.1:8000/"
check_http "ui" "http://127.0.0.1:8812/login.html"
