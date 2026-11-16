#!/usr/bin/env sh
# AutoApply: install what is missing, then start. Safe to run every time.
# Optional: AUTOAPPLY_PORT=8010 ./start.sh to use another port.
set -e
cd "$(dirname "$0")"
PORT="${AUTOAPPLY_PORT:-8000}"

if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
  PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "[AutoApply] uv is needed (a small tool from astral.sh that prepares the Python environment)."
  printf "[AutoApply] Download and install it now? (y/N) "
  read -r ANS
  case "$ANS" in
    y|Y) curl -LsSf https://astral.sh/uv/install.sh | sh; PATH="$HOME/.local/bin:$PATH" ;;
    *) echo "[AutoApply] OK. Install it yourself, then run this again: https://docs.astral.sh/uv/"; exit 1 ;;
  esac
fi

echo "[AutoApply] checking dependencies (a few minutes the first time)..."
[ -x "./tools/uv" ] && PATH="$PWD/tools:$PATH"      # an installed copy brings its own uv
# --inexact: keep optional components added later (the ChatGPT sign-in component); a plain sync would remove them on every start
uv sync --inexact

# the program's own browser. Asked for every time: it returns at once when the right build is there, and a newer
# Playwright needs a newer build - "the folder exists" does not say which one is in it
echo "[AutoApply] checking the browser the program uses (a download the first time and after some upgrades)..."
uv run playwright install chromium

if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[AutoApply] this copy has no built interface. Download the release package (it includes one), or install Node.js and run this again: https://nodejs.org/"
    exit 1
  fi
  echo "[AutoApply] building the interface (once)..."
  (cd frontend && npm install && npm run build)
fi

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1 && [ ! -d "/Applications/LibreOffice.app" ]; then
  echo "[AutoApply] note: LibreOffice is not installed. Cover letters and résumé tailoring need it to make PDFs: https://www.libreoffice.org/"
fi

if [ -z "$AUTOAPPLY_CONSOLE" ] && { [ "$(uname)" = "Darwin" ] || [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; }; then
  echo
  echo "[AutoApply] starting. An AutoApply icon appears in the menu bar / tray; the page opens by itself."
  echo "[AutoApply] Use the icon to open the page, see the status, start at sign-in, or quit. (AUTOAPPLY_CONSOLE=1 runs it in this window instead.)"
  nohup uv run autoapply tray --port "$PORT" >/dev/null 2>&1 &
  exit 0
fi
echo
echo "[AutoApply] starting. Open http://127.0.0.1:$PORT in your browser (Ctrl+C stops it)."
echo
exec uv run autoapply serve --port "$PORT"
