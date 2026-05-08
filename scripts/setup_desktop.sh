#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/_python.sh"

BOOTSTRAP_PYTHON="${PYTHON:-python3}"
VENV_DIR="$ROOT_DIR/.venv"
if ! unccoin_venv_python "$ROOT_DIR" >/dev/null 2>&1; then
  echo "Creating Python virtual environment at .venv"
  if ! "$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR"; then
    echo "Could not create .venv. On Debian/Ubuntu, install python3-venv and retry:" >&2
    echo "  sudo apt install python3-venv" >&2
    exit 1
  fi
fi

PYTHON_BIN="$(unccoin_venv_python "$ROOT_DIR")"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements-api.txt
npm --prefix desktop install

echo "Desktop dependencies installed."
echo "Python environment: $PYTHON_BIN"
echo "Run ./scripts/desktop.sh to start the desktop app."
