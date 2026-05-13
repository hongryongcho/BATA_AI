#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/batagota/BATAGOTA/10_AI_BATA"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/ops/logs"
PYTHON_BIN="/opt/homebrew/bin/python3.10"
NODE_BIN="/opt/homebrew/bin/node"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: python3.10 not found at $PYTHON_BIN"
  exit 1
fi

if [[ ! -x "$NODE_BIN" ]]; then
  NODE_BIN="$(command -v node || true)"
fi

if [[ -z "${NODE_BIN:-}" || ! -x "$NODE_BIN" ]]; then
  echo "ERROR: node binary not found. Install Node.js first."
  exit 1
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

# Legacy labels used by previous setup scripts.
LEGACY_LABELS=(
  "com.batagota.mqtt-logger"
  "com.batagota.telegram.bot"
)

write_plist() {
  local plist_path="$1"
  local label="$2"
  local workdir="$3"
  local stdout_path="$4"
  local stderr_path="$5"
  shift 5
  local args=("$@")

  {
    cat <<'PLIST_HEAD'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
PLIST_HEAD
    echo "  <key>Label</key>"
    echo "  <string>${label}</string>"
    echo "  <key>WorkingDirectory</key>"
    echo "  <string>${workdir}</string>"
    echo "  <key>ProgramArguments</key>"
    echo "  <array>"
    for arg in "${args[@]}"; do
      echo "    <string>${arg}</string>"
    done
    echo "  </array>"
    cat <<PLIST_TAIL
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>${stdout_path}</string>
  <key>StandardErrorPath</key>
  <string>${stderr_path}</string>
</dict>
</plist>
PLIST_TAIL
  } > "$plist_path"
}

write_plist \
  "$LAUNCH_AGENTS_DIR/com.batagota.mqtt.logger.plist" \
  "com.batagota.mqtt.logger" \
  "$ROOT/02_BATA_MQTT" \
  "$LOG_DIR/mqtt_logger.out.log" \
  "$LOG_DIR/mqtt_logger.err.log" \
  "$PYTHON_BIN" "$ROOT/02_BATA_MQTT/workers/mqtt_logger.py"

write_plist \
  "$LAUNCH_AGENTS_DIR/com.batagota.mqtt.dashboard.plist" \
  "com.batagota.mqtt.dashboard" \
  "$ROOT/00_BATAGOTA" \
  "$LOG_DIR/mqtt_dashboard.out.log" \
  "$LOG_DIR/mqtt_dashboard.err.log" \
  "$PYTHON_BIN" "$ROOT/00_BATAGOTA/scripts/run_mqtt_app_dashboard.py"

write_plist \
  "$LAUNCH_AGENTS_DIR/com.batagota.telegram.botsvc.plist" \
  "com.batagota.telegram.botsvc" \
  "$ROOT/00_BATAGOTA" \
  "$LOG_DIR/telegram_bot.out.log" \
  "$LOG_DIR/telegram_bot.err.log" \
  "$PYTHON_BIN" "$ROOT/00_BATAGOTA/interfaces/telegram/bot.py"

write_plist \
  "$LAUNCH_AGENTS_DIR/com.batagota.stock.backend.plist" \
  "com.batagota.stock.backend" \
  "$ROOT/01_BATA_STOCK/backend" \
  "$LOG_DIR/stock_backend.out.log" \
  "$LOG_DIR/stock_backend.err.log" \
  "$NODE_BIN" "$ROOT/01_BATA_STOCK/backend/src/index.js"

for legacy in "${LEGACY_LABELS[@]}"; do
  legacy_plist="$LAUNCH_AGENTS_DIR/${legacy}.plist"
  if [[ -f "$legacy_plist" ]]; then
    launchctl unload -w "$legacy_plist" >/dev/null 2>&1 || true
    rm -f "$legacy_plist"
  fi
done

for label in \
  com.batagota.mqtt.logger \
  com.batagota.mqtt.dashboard \
  com.batagota.telegram.botsvc \
  com.batagota.stock.backend; do
  plist="$LAUNCH_AGENTS_DIR/${label}.plist"
  launchctl unload -w "$plist" >/dev/null 2>&1 || true
  launchctl load -w "$plist"
  echo "OK: loaded $label"
done

echo
echo "Current BATAGOTA services:"
launchctl list | grep com.batagota || true
echo "Logs: $LOG_DIR"
