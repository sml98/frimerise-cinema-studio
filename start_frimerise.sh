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

# Open browser automatically if invoked with --open (e.g. from Ubuntu .desktop shortcut)
if [[ "${1:-}" == "--open" ]]; then
  (sleep 2 && xdg-open "http://localhost:8000" >/dev/null 2>&1 || true) &
fi

exec "$DIR/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port 8000
