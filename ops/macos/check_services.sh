#!/usr/bin/env bash
set -euo pipefail

echo "launchctl services"
launchctl list | grep com.batagota || true

echo
echo "python processes"
ps aux | grep -E "run_mqtt_app_dashboard.py|interfaces/telegram/bot.py|workers/mqtt_logger.py" | grep -v grep || true

echo
echo "node processes"
ps aux | grep -E "01_BATA_STOCK/backend/src/index.js" | grep -v grep || true

echo
echo "ports"
lsof -nP -iTCP:8787 -sTCP:LISTEN || true
lsof -nP -iTCP:4000 -sTCP:LISTEN || true
