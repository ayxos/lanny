#!/usr/bin/env bash
# Lanny launcher for macOS / Linux.
#   * Creates .venv on first run, installs deps.
#   * Starts the tray app (which boots Flask in-process).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [[ ! -d .venv ]]; then
    echo "==> creating virtualenv (.venv)"
    "$PYTHON" -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# Install/refresh deps only if the manifest changed since last install.
STAMP=".venv/.deps.sha"
CUR=$(shasum requirements.txt 2>/dev/null | cut -d' ' -f1 || sha256sum requirements.txt | cut -d' ' -f1)
if [[ ! -f "$STAMP" ]] || [[ "$(cat "$STAMP")" != "$CUR" ]]; then
    echo "==> installing dependencies"
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    echo "$CUR" > "$STAMP"
fi

echo "==> launching Lanny (open http://127.0.0.1:5050 or use the tray icon)"
exec python tray.py
