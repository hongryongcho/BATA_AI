#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

for label in \
  com.batagota.mqtt-logger \
  com.batagota.mqtt.logger \
  com.batagota.mqtt.dashboard \
  com.batagota.telegram.bot \
  com.batagota.telegram.botsvc \
  com.batagota.stock.backend; do
  plist="$LAUNCH_AGENTS_DIR/${label}.plist"
  if [[ -f "$plist" ]]; then
    launchctl unload -w "$plist" >/dev/null 2>&1 || true
    rm -f "$plist"
  fi
  echo "REMOVED: $label"
done

echo "Done"
