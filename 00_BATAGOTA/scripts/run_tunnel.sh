#!/usr/bin/env bash
# Cloudflare Quick Tunnel — 계정 불필요, URL은 재시작마다 변경됨
# 영구 URL이 필요하면 Cloudflare Named Tunnel 사용 (무료 계정 필요)
#
# 설치:
#   brew install cloudflared
#
# 사용법:
#   bash scripts/run_tunnel.sh

set -euo pipefail

if ! command -v cloudflared &>/dev/null; then
    echo "[ERROR] cloudflared not found."
    echo "  Install: brew install cloudflared"
    exit 1
fi

PORT=${APP_SERVER_PORT:-8787}

echo "[INFO] Starting Cloudflare Quick Tunnel → http://localhost:${PORT}"
rm -f /tmp/cloudflared.log

cloudflared tunnel --url "http://localhost:${PORT}" 2>&1 | tee /tmp/cloudflared.log &
CF_PID=$!
echo "[INFO] cloudflared PID: ${CF_PID}"

TUNNEL_URL=""
for i in $(seq 1 20); do
    TUNNEL_URL=$(grep -o 'https://[^[:space:]]*trycloudflare\.com' /tmp/cloudflared.log 2>/dev/null | head -1)
    [ -n "$TUNNEL_URL" ] && break
    sleep 1
done

if [ -n "$TUNNEL_URL" ]; then
    echo ""
    echo "  Tunnel : ${TUNNEL_URL}"
    echo "  Tablet : ${TUNNEL_URL}/tablet/"
    echo "  QR     : ${TUNNEL_URL}/qr"
    echo ""
else
    echo "[WARN] Tunnel URL not yet available. Check /tmp/cloudflared.log"
fi

echo "[INFO] Press Ctrl+C to stop the tunnel."
wait "${CF_PID}"
