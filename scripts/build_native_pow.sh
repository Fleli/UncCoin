#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/_python.sh"
PYTHON_BIN="$(unccoin_python "$ROOT_DIR")"

"$PYTHON_BIN" -m core.native_pow "$@"
