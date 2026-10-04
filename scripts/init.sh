#!/usr/bin/env bash
set -euo pipefail

NOVNC_VERSION="1.6.0"
NOVNC_DIR="/opt/noVNC"

echo "=== Installing noVNC ==="

rm -rf "$NOVNC_DIR"

curl -fsSL \
  "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" \
  | tar -xz -C /opt

mv "/opt/noVNC-${NOVNC_VERSION}" "$NOVNC_DIR"

chmod +x "$NOVNC_DIR/utils/novnc_proxy"

ln -sf "$NOVNC_DIR/utils/novnc_proxy" /usr/local/bin/novnc_proxy

mkdir -p /root/.vnc /app/data
chmod 700 /root/.vnc

echo "=== Installed versions ==="

uv --version
python --version
chromium --version

echo "=== TigerVNC ==="
command -v Xvnc || command -v Xtigervnc
Xvnc -version 2>&1 | head -5 || true

echo "=== noVNC ==="
ls -la "$NOVNC_DIR"
ls -la "$NOVNC_DIR/utils"

echo "=== noVNC proxy ==="
command -v novnc_proxy

echo "=== Installation complete ==="
