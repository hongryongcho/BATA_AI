#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

DAEMONS_DIR="/Library/LaunchDaemons"

for label in \
  com.batagota.mqtt.logger \
  com.batagota.mqtt.dashboard \
  com.batagota.telegram.bot \
  com.batagota.telegram.botsvc \
  com.batagota.stock.backend; do
  launchctl bootout "system/$label" >/dev/null 2>&1 || true
  launchctl disable "system/$label" >/dev/null 2>&1 || true
  rm -f "$DAEMONS_DIR/${label}.plist"
  echo "REMOVED: $label"
done

echo "Done"
