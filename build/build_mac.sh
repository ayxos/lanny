#!/usr/bin/env bash
# Build Lanny.app and a distributable Lanny.dmg on macOS.
#
# Output:
#   dist/Lanny.app   — menubar-only .app bundle (LSUIElement)
#   dist/Lanny.dmg   — compressed disk image ready to ship
#
# Must be run on macOS (PyInstaller can't cross-compile; hdiutil is mac-only).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: build_mac.sh must run on macOS (got $(uname -s))." >&2
    exit 1
fi

cd "$(dirname "$0")/.."
ROOT="$PWD"

PYTHON="${PYTHON:-python3}"

# 1. Isolated venv with PyInstaller pinned.
if [[ ! -d .venv-build ]]; then
    "$PYTHON" -m venv .venv-build
fi
# shellcheck source=/dev/null
source .venv-build/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller==6.10.0 --quiet

# 2. Build the .app.
rm -rf build/work dist/Lanny dist/Lanny.app dist/Lanny.dmg
pyinstaller --noconfirm --clean \
    --workpath build/work \
    --distpath dist \
    build/lanny.spec

if [[ ! -d dist/Lanny.app ]]; then
    echo "error: dist/Lanny.app was not created by PyInstaller." >&2
    exit 1
fi

# 3. Wrap the .app into a compressed DMG.
DMG="dist/Lanny.dmg"
echo "==> creating $DMG"
hdiutil create \
    -volname "Lanny" \
    -srcfolder "dist/Lanny.app" \
    -ov -format UDZO \
    "$DMG" >/dev/null

echo
echo "Build complete:"
echo "  $ROOT/dist/Lanny.app"
echo "  $ROOT/$DMG"
echo
echo "Run locally:  open dist/Lanny.app"
echo "Ship:         $DMG"
