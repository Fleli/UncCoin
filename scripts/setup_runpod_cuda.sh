#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install --upgrade pip
python3 -m pip install "cupy-cuda12x[ctk]"

if [[ "${UNCCOIN_BUILD_CPU_POW_EXTENSION:-0}" == "1" ]]; then
  ./scripts/build_native_pow.sh
fi

echo "Runpod CUDA setup complete."
echo "Recommended dedicated miner launch:"
echo "  UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <port> [peer-host:peer-port ...]"
