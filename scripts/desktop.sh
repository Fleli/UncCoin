#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/_python.sh"

if [[ -z "${UNCCOIN_PYTHON:-}" ]]; then
  export UNCCOIN_PYTHON="$(unccoin_python "$ROOT_DIR")"
fi

find_available_port() {
  local start_port="${1:-5173}"
  node - "$start_port" <<'NODE'
const net = require("node:net");

const startPort = Number(process.argv[2] || 5173);
const maxPort = Math.min(65535, startPort + 100);

function canListen(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen({ host: "127.0.0.1", port }, () => {
      server.close(() => resolve(true));
    });
  });
}

(async () => {
  for (let port = startPort; port <= maxPort; port += 1) {
    if (await canListen(port)) {
      console.log(port);
      return;
    }
  }
  process.exit(1);
})();
NODE
}

if [[ -n "${UNCCOIN_DESKTOP_PORT:-}" ]]; then
  if [[ ! "$UNCCOIN_DESKTOP_PORT" =~ ^[0-9]+$ ]] || (( UNCCOIN_DESKTOP_PORT < 1 || UNCCOIN_DESKTOP_PORT > 65535 )); then
    echo "UNCCOIN_DESKTOP_PORT must be between 1 and 65535." >&2
    exit 1
  fi
  VITE_DEV_SERVER_PORT="$UNCCOIN_DESKTOP_PORT"
else
  VITE_DEV_SERVER_PORT="$(find_available_port 5173)" || {
    echo "Could not find an available desktop dev server port." >&2
    exit 1
  }
fi

export VITE_DEV_SERVER_PORT
echo "Starting UncCoin Desktop on http://127.0.0.1:${VITE_DEV_SERVER_PORT}"
echo "Using Python: $UNCCOIN_PYTHON"

exec npm --prefix desktop run dev
