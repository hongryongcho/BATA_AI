#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

ROOT="/Users/batagota/BATAGOTA/10_AI_BATA"
RUN_USER="batagota"
RUN_GROUP="staff"
LOG_DIR="$ROOT/ops/logs"
DAEMONS_DIR="/Library/LaunchDaemons"
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

mkdir -p "$LOG_DIR" "$DAEMONS_DIR"
chown "$RUN_USER:$RUN_GROUP" "$LOG_DIR"

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
    echo "  <key>UserName</key>"
    echo "  <string>${RUN_USER}</string>"
    echo "  <key>GroupName</key>"
    echo "  <string>${RUN_GROUP}</string>"
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
  "$DAEMONS_DIR/com.batagota.mqtt.logger.plist" \
  "com.batagota.mqtt.logger" \
  "$ROOT/02_BATA_MQTT" \
  "$LOG_DIR/mqtt_logger.out.log" \
  "$LOG_DIR/mqtt_logger.err.log" \
  "$PYTHON_BIN" "$ROOT/02_BATA_MQTT/workers/mqtt_logger.py"

write_plist \
  "$DAEMONS_DIR/com.batagota.mqtt.dashboard.plist" \
  "com.batagota.mqtt.dashboard" \
  "$ROOT/00_BATAGOTA" \
  "$LOG_DIR/mqtt_dashboard.out.log" \
  "$LOG_DIR/mqtt_dashboard.err.log" \
  "$PYTHON_BIN" "$ROOT/00_BATAGOTA/scripts/run_mqtt_app_dashboard.py"

write_plist \
  "$DAEMONS_DIR/com.batagota.telegram.botsvc.plist" \
  "com.batagota.telegram.botsvc" \
  "$ROOT/00_BATAGOTA" \
  "$LOG_DIR/telegram_bot.out.log" \
  "$LOG_DIR/telegram_bot.err.log" \
  "$PYTHON_BIN" "$ROOT/00_BATAGOTA/interfaces/telegram/bot.py"

write_plist \
  "$DAEMONS_DIR/com.batagota.stock.backend.plist" \
  "com.batagota.stock.backend" \
  "$ROOT/01_BATA_STOCK/backend" \
  "$LOG_DIR/stock_backend.out.log" \
  "$LOG_DIR/stock_backend.err.log" \
  "$NODE_BIN" "$ROOT/01_BATA_STOCK/backend/src/index.js"

for plist in \
  "$DAEMONS_DIR/com.batagota.mqtt.logger.plist" \
  "$DAEMONS_DIR/com.batagota.mqtt.dashboard.plist" \
  "$DAEMONS_DIR/com.batagota.telegram.botsvc.plist" \
  "$DAEMONS_DIR/com.batagota.stock.backend.plist"; do
  chown root:wheel "$plist"
  chmod 644 "$plist"
done

for label in \
  com.batagota.mqtt.logger \
  com.batagota.mqtt.dashboard \
  com.batagota.telegram.botsvc \
  com.batagota.stock.backend; do
  launchctl bootout "system/$label" >/dev/null 2>&1 || true
  launchctl bootstrap system "$DAEMONS_DIR/${label}.plist"
  launchctl enable "system/$label"
  launchctl kickstart -k "system/$label"
  echo "OK: loaded daemon $label"
done

echo
echo "System daemons:"
launchctl print system | grep com.batagota || true
