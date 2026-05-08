#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -m pip install -r requirements-api.txt
npm --prefix desktop install

echo "Desktop dependencies installed."
echo "Run ./scripts/desktop.sh to start the desktop app."
