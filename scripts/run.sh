#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <wallet-name> <port> [peer-host:peer-port ...]"
  exit 1
fi

WALLET_NAME="$1"
PORT="$2"
shift 2

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${UNCCOIN_GPU_ONLY:-0}" == "1" && -z "${UNCCOIN_MINING_CPU_WORKERS:-}" ]]; then
  export UNCCOIN_MINING_CPU_WORKERS=0
fi

ARGS=(python3 -m node.cli --host 0.0.0.0 --wallet-name "$WALLET_NAME" --port "$PORT")

if [[ "${UNCCOIN_PRIVATE_AUTOMINE:-0}" == "1" ]]; then
  ARGS+=(--private-automine)
fi

API_PORT="${UNCCOIN_API_PORT:-$((PORT + 10000))}"
ARGS+=(--api-host "${UNCCOIN_API_HOST:-127.0.0.1}" --api-port "$API_PORT")

for PEER in "$@"; do
  ARGS+=(--peer "$PEER")
done

exec "${ARGS[@]}"
