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
    echo "  apt update && apt install -y python3-venv" >&2
    exit 1
  fi
fi

PYTHON_BIN="$(unccoin_venv_python "$ROOT_DIR")"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements-api.txt "cupy-cuda12x[ctk]"

if [[ "${UNCCOIN_BUILD_CPU_POW_EXTENSION:-0}" == "1" ]]; then
  ./scripts/build_native_pow.sh
fi

echo "Runpod CUDA setup complete."
echo "Python environment: $PYTHON_BIN"
echo "Recommended dedicated miner launch:"
echo "  ./scripts/cloud_automine.sh <wallet-name> <port> [peer-host:peer-port ...]"
