#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"

check_pid() {
  local name="$1"
  local pid_file="$2"
  local expected="$3"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      local cmdline
      cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
      if [[ -n "$cmdline" && "$cmdline" == *"$expected"* ]]; then
        echo "$name pid: $pid (running)"
        return
      fi
    fi
    rm -f "$pid_file"
  fi
  echo "$name pid: not running"
}

check_http() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -s --connect-timeout 1 --max-time 3 -o /dev/null -w "%{http_code}" "$url" || true)"
  echo "$name http: $code ($url)"
}

check_pid "backend" "$RUNTIME_DIR/backend.pid" "uvicorn main:app"
check_pid "ui" "$RUNTIME_DIR/ui.pid" "http.server 8812"
check_http "backend" "http://127.0.0.1:8000/"
check_http "ui" "http://127.0.0.1:8812/login.html"
