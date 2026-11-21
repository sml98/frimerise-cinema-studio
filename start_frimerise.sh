#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRIVERS_PATH="$DIR/vendor/syslibs/usr/lib/x86_64-linux-gnu/dri:/usr/lib/x86_64-linux-gnu/dri"
export LD_LIBRARY_PATH="$DIR/vendor/syslibs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"

if [ ! -f "$DIR/data/frimerise.db" ] || [ ! -f "$DIR/assets/brand/frimerise_logo.png" ]; then
  "$DIR/.venv/bin/python" "$DIR/bootstrap_assets.py"
fi

OPEN_BROWSER=0
KEEP_AWAKE=0
for arg in "$@"; do
  case "$arg" in
    --open) OPEN_BROWSER=1 ;;
    --keep-awake) KEEP_AWAKE=1 ;;
  esac
done

# Open browser automatically if invoked with --open (e.g. from Ubuntu .desktop shortcut)
if [ "$OPEN_BROWSER" -eq 1 ]; then
  (sleep 2 && xdg-open "http://localhost:8000" >/dev/null 2>&1 || true) &
fi

# Bind strictly to 127.0.0.1 by default (Tailscale Serve proxies securely to 127.0.0.1:8000)
HOST="${FRIMERISE_HOST:-127.0.0.1}"
PORT="${FRIMERISE_PORT:-8000}"

UVICORN_CMD=(
  "$DIR/.venv/bin/uvicorn" app:app
  --host "$HOST"
  --port "$PORT"
  --proxy-headers
  --forwarded-allow-ips="127.0.0.1"
)

if [ "$KEEP_AWAKE" -eq 1 ] && command -v systemd-inhibit >/dev/null 2>&1; then
  exec systemd-inhibit --what=idle:sleep --who="FrimeRise" --why="Servidor FrimeRise ativo para acesso remoto Tailscale" "${UVICORN_CMD[@]}"
fi

exec "${UVICORN_CMD[@]}"
