#!/usr/bin/env bash
set -euo pipefail

# BATAGOTA Family Photo Service installer
# Purpose: deploy Immich as an isolated Docker service at picture.batagota.com
# without modifying the existing BATAGOTA apps.

INSTALL_DIR="/opt/batagota/photo"
DOMAIN="picture.batagota.com"
CADDY_CFG="/etc/caddy/Caddyfile"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_NAME="$(uname -s)"

echo "[1/5] ensuring prerequisites"
if ! command -v docker >/dev/null 2>&1; then
  if [ "$OS_NAME" = "Darwin" ]; then
    echo "Docker Desktop is required on macOS. Install it and rerun this script."
    exit 1
  fi
  echo "Docker not found. Installing Docker on Linux..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg lsb-release
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable docker
  sudo systemctl start docker
  sudo usermod -aG docker "$USER"
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running. Start Docker Desktop or the Docker service and rerun this script."
  exit 1
fi

echo "[2/5] creating isolated install directory"
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER:$USER" "$INSTALL_DIR"

if [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
  cp "$SOURCE_DIR/docker-compose.yml" "$INSTALL_DIR/docker-compose.yml"
fi

if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$SOURCE_DIR/.env" "$INSTALL_DIR/.env"
fi

if [ ! -f "$INSTALL_DIR/Caddyfile" ]; then
  cp "$SOURCE_DIR/Caddyfile" "$INSTALL_DIR/Caddyfile"
fi

echo "[3/5] installing Caddy"
if ! command -v caddy >/dev/null 2>&1; then
  if [ "$OS_NAME" = "Darwin" ]; then
    brew install caddy
  else
    sudo apt-get install -y caddy
  fi
fi

sudo mkdir -p /etc/caddy
sudo cp "$SOURCE_DIR/Caddyfile" "$CADDY_CFG"
sudo caddy validate --config "$CADDY_CFG"

if [ "$OS_NAME" = "Linux" ]; then
  sudo systemctl enable caddy
  sudo systemctl restart caddy
else
  echo "Caddy configuration installed. Start it with: sudo caddy start --config $CADDY_CFG --adapter caddyfile"
fi

echo "[4/5] starting Immich containers"
cd "$INSTALL_DIR"
docker compose up -d

echo "[5/5] checking service status"
docker compose ps
curl -I "http://127.0.0.1:2283" || true

cat <<EOF

BATAGOTA Family Photo Service is being set up.

Next steps:
1. confirm DNS entry for $DOMAIN points to this server
2. open https://$DOMAIN
3. login with dad / happytree
4. create users: mom, chan, ji
5. create album structure:
   - dad_private
   - mom_private
   - chan_private
   - ji_private
   - family_shared

Important:
- Existing BATAGOTA services are left untouched.
- Only the subdomain $DOMAIN is routed to Immich.
- No existing BATAGOTA port or startup script is modified.
EOF
