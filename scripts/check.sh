#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/_python.sh"
PYTHON_BIN="$(unccoin_python "$ROOT_DIR")"

exec "$PYTHON_BIN" "$ROOT_DIR/scripts/check.py"
