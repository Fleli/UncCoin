#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <wallet-name> <p2p-port> [peer-host:peer-port ...]"
  exit 1
fi

WALLET_NAME="$1"
PORT="$2"
shift 2

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/_python.sh"
PYTHON_BIN="$(unccoin_python "$ROOT_DIR")"

export UNCCOIN_MINING_BACKEND="${UNCCOIN_MINING_BACKEND:-gpu}"
export UNCCOIN_MINING_CPU_WORKERS="${UNCCOIN_MINING_CPU_WORKERS:-0}"
export UNCCOIN_MINING_PROGRESS_INTERVAL="${UNCCOIN_MINING_PROGRESS_INTERVAL:-100000000}"
export UNCCOIN_GPU_CHUNK_MULTIPLIER="${UNCCOIN_GPU_CHUNK_MULTIPLIER:-128}"
export UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS="${UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS:-0}"
export UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS="${UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS:-250}"
export UNCCOIN_CLOUD_NATIVE_BATCH_BLOCKS="${UNCCOIN_CLOUD_NATIVE_BATCH_BLOCKS:-250}"
export UNCCOIN_CLOUD_NATIVE_TRUST_WORKER_HASH="${UNCCOIN_CLOUD_NATIVE_TRUST_WORKER_HASH:-1}"
export UNCCOIN_CLOUD_NATIVE_START_NONCE="${UNCCOIN_CLOUD_NATIVE_START_NONCE:-0}"

API_PORT="${UNCCOIN_API_PORT:-$((PORT + 10000))}"
AUTOMINE_DESCRIPTION="${UNCCOIN_AUTOMINE_DESCRIPTION:-cloud gpu miner}"
SYNC_WAIT_SECONDS="${UNCCOIN_CLOUD_SYNC_WAIT_SECONDS:-180}"
MINED_BLOCK_PERSIST_INTERVAL="${UNCCOIN_MINED_BLOCK_PERSIST_INTERVAL:-0}"
SHUTDOWN_WAIT_SECONDS="${UNCCOIN_CLOUD_SHUTDOWN_WAIT_SECONDS:-600}"
TERM_WAIT_SECONDS="${UNCCOIN_CLOUD_TERM_WAIT_SECONDS:-30}"

ARGS=(
  "$PYTHON_BIN" -m node.cli
  --host 0.0.0.0
  --wallet-name "$WALLET_NAME"
  --port "$PORT"
  --api-host 127.0.0.1
  --api-port "$API_PORT"
  --no-interactive
  --mining-only
  --mined-block-persist-interval "$MINED_BLOCK_PERSIST_INTERVAL"
)

if [[ "${UNCCOIN_CLOUD_NATIVE_AUTOMINE:-1}" == "1" ]]; then
  ARGS+=(--cloud-native-automine)
fi

if [[ "${UNCCOIN_PRIVATE_AUTOMINE:-0}" == "1" ]]; then
  ARGS+=(--private-automine)
fi

for PEER in "$@"; do
  ARGS+=(--peer "$PEER")
done

"${ARGS[@]}" &
NODE_PID=$!

cleanup() {
  trap - EXIT INT TERM
  if kill -0 "$NODE_PID" >/dev/null 2>&1; then
    kill -INT "$NODE_PID" >/dev/null 2>&1 || true
    for ((elapsed = 0; elapsed < SHUTDOWN_WAIT_SECONDS; elapsed++)); do
      if ! kill -0 "$NODE_PID" >/dev/null 2>&1; then
        wait "$NODE_PID" || true
        return
      fi
      sleep 1
    done
    kill -TERM "$NODE_PID" >/dev/null 2>&1 || true
    for ((elapsed = 0; elapsed < TERM_WAIT_SECONDS; elapsed++)); do
      if ! kill -0 "$NODE_PID" >/dev/null 2>&1; then
        wait "$NODE_PID" || true
        return
      fi
      sleep 1
    done
    kill -KILL "$NODE_PID" >/dev/null 2>&1 || true
    wait "$NODE_PID" || true
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

"$PYTHON_BIN" - "$API_PORT" "$AUTOMINE_DESCRIPTION" "$SYNC_WAIT_SECONDS" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

api_port = int(sys.argv[1])
description = sys.argv[2]
sync_wait_seconds = float(sys.argv[3])
base_url = f"http://127.0.0.1:{api_port}/api/v1"


def request(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


deadline = time.monotonic() + 60
while True:
    try:
        info = request("/health")
        print(
            "Node API ready at height "
            f"{info.get('chain', {}).get('height')}.",
            flush=True,
        )
        break
    except (OSError, urllib.error.URLError):
        if time.monotonic() >= deadline:
            raise SystemExit("Timed out waiting for node API.")
        time.sleep(1)

try:
    sync_response = request("/control/sync", "POST", {"fast": True})
    print(
        "Requested fast sync from "
        f"{sync_response.get('requested_peers', 0)} peer(s).",
        flush=True,
    )
except urllib.error.HTTPError as error:
    print(f"Fast sync request failed: {error}", flush=True)

deadline = time.monotonic() + sync_wait_seconds
last_height = None
while time.monotonic() < deadline:
    try:
        sync_status = request("/sync/status")
        node_info = request("/health")
    except (OSError, urllib.error.URLError):
        time.sleep(1)
        continue

    height = node_info.get("chain", {}).get("height")
    if height != last_height:
        print(f"Sync height: {height}", flush=True)
        last_height = height

    fastsync = sync_status.get("fastsync", {})
    if not fastsync.get("active"):
        break
    time.sleep(2)

automine_response = request(
    "/control/automine/start",
    "POST",
    {"description": description},
)
print(
    "Automine started: "
    f"{automine_response.get('description', description)}",
    flush=True,
)
PY

wait "$NODE_PID"
