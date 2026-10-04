#!/usr/bin/env bash
set -Eeuo pipefail

cd /app

export DISPLAY="${DISPLAY:-:0}"
export TZ="${TZ:-Europe/Madrid}"
export HOME=/root
export PATH="/root/.local/bin:/root/.cargo/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

WIDTH="${DISPLAY_WIDTH:-1680}"
HEIGHT="${DISPLAY_HEIGHT:-1050}"

VNC_PORT=5900
NOVNC_PORT=6080
NOVNC_DIR="/opt/noVNC"

VNC_DIR="$HOME/.vnc"
VNC_PASSWD_FILE="$VNC_DIR/passwd"

mkdir -p "$VNC_DIR" /app/data
chmod 700 "$VNC_DIR"

if [[ -z "${VNC_PASSWD:-}" ]]; then
    echo "ERROR: VNC_PASSWD is not set"
    exit 1
fi

umask 077
printf '%s\n' "$VNC_PASSWD" | vncpasswd -f > "$VNC_PASSWD_FILE"
chmod 600 "$VNC_PASSWD_FILE"

PIDS=()

cleanup() {
    echo "=== Stopping services ==="

    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done

    wait || true
}

trap cleanup EXIT

if ! pgrep -x Xvnc >/dev/null 2>&1; then
    rm -f /tmp/.X0-lock
    rm -f /tmp/.X11-unix/X0
fi

echo "=== Starting TigerVNC display $DISPLAY ==="

Xvnc "$DISPLAY" \
    -geometry "${WIDTH}x${HEIGHT}" \
    -depth 24 \
    -rfbport "$VNC_PORT" \
    -rfbauth "$VNC_PASSWD_FILE" \
    -localhost yes \
    -AlwaysShared \
    > /tmp/xvnc.log 2>&1 &

PIDS+=("$!")

echo "=== Waiting for X server ==="

for i in $(seq 1 30); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    echo "ERROR: Xvnc failed to start"
    cat /tmp/xvnc.log
    exit 1
fi

echo "=== X server is ready ==="

echo "=== Starting i3 ==="

i3 > /tmp/i3.log 2>&1 &
PIDS+=("$!")

echo "=== Starting noVNC ==="

novnc_proxy \
    --vnc "localhost:$VNC_PORT" \
    --listen "$NOVNC_PORT" \
    --web "$NOVNC_DIR" \
    > /tmp/novnc.log 2>&1 &

PIDS+=("$!")

echo "=== Waiting for noVNC ==="

NOVNC_READY=false

for i in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$NOVNC_PORT/vnc.html" >/dev/null 2>&1; then
        NOVNC_READY=true
        break
    fi
    sleep 1
done

if [[ "$NOVNC_READY" != "true" ]]; then
    echo "ERROR: noVNC failed to start"
    cat /tmp/novnc.log
    exit 1
fi

echo "=== noVNC is ready on port $NOVNC_PORT ==="

echo "=== Installing/syncing AutoApply dependencies ==="

if [[ -f uv.lock ]]; then
    uv sync --frozen
else
    uv sync
fi

echo "=== Installing Playwright Chromium ==="
uv run playwright install chromium

echo "=== Starting AutoApply ==="
echo "DISPLAY=$DISPLAY"

read -r -a AUTOAPPLY_START_ARGS_ARRAY <<< "${AUTOAPPLY_START_ARGS:---skip-docker}"
uv run autoapply start "${AUTOAPPLY_START_ARGS_ARRAY[@]}"
