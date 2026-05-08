# Getting Started

This guide is for a fresh clone on one machine. For multi-device networking afterward,
see [Tailscale.md](Tailscale.md).

UncCoin has two normal ways to run:

- Desktop app: easiest for most users. It creates/selects wallets, starts the Python node,
  shows chain/network/mining state, and exposes node actions through the local API.
- Terminal node: useful for servers, dedicated miners, and debugging.

## 1. Prerequisites

Required:

- Python 3.12+ with `pip`
- Git

Required for the desktop app:

- Node.js and `npm`

Optional for faster native mining:

- macOS: Xcode command line tools
- Linux: `gcc` plus Python development headers, for example:

```bash
sudo apt install gcc python3-dev build-essential
```

The Python miner is always available. Native C/GPU mining is optional and can be built later.

## 2. Clone

```bash
git clone https://github.com/Fleli/UncCoin.git
cd UncCoin
```

## 3. Install Python API Dependencies

The helper node script starts the local FastAPI node API automatically, so install the API
dependencies before running nodes:

```bash
python3 -m pip install -r requirements-api.txt
```

The node API is local by default and listens on `node_port + 10000`. A node on P2P port
`9000` exposes its API on `127.0.0.1:19000`.

## 4. Desktop App Setup

Install desktop dependencies once:

```bash
./scripts/setup_desktop.sh
```

Start the desktop app:

```bash
./scripts/desktop.sh
```

From the launch screen you can:

- create a new wallet and immediately start a node
- select an existing wallet
- choose the P2P port
- save the wallet's preferred P2P port
- disable any bootstrap peer for that launch
- skip miner warmup if you want the node window to open immediately

The desktop app starts the Python node and API for you. It uses API port `P2P port + 10000`
unless you choose a different API port in the UI. The desktop app also generates a per-run
API bearer token and uses it for wallet-signing control actions automatically.

Multiple desktop instances can run at once. The desktop dev server picks a free local port
automatically; the node P2P/API ports still need to be different per running node.

Build the desktop frontend without launching it:

```bash
./scripts/build_desktop.sh
```

## 5. Terminal Wallet Setup

Create a wallet:

```bash
python3 -m wallet.cli create --name <wallet-name>
```

Inspect a wallet:

```bash
python3 -m wallet.cli show --name <wallet-name>
```

Shortcut:

```bash
./scripts/wallet.sh <wallet-name>
```

## 6. Terminal Node Setup

Run a node:

```bash
./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

Example first local node:

```bash
./scripts/run.sh alice 9000
```

Example second local node connecting to the first:

```bash
./scripts/run.sh bob 9001 127.0.0.1:9000
```

`scripts/run.sh` binds the P2P server to `0.0.0.0` so other machines can connect to it.
The node API stays on `127.0.0.1` by default:

```text
P2P:  0.0.0.0:<p2p-port>
API:  127.0.0.1:<p2p-port + 10000>
Docs: http://127.0.0.1:<api-port>/docs
```

To override the API host or port:

```bash
UNCCOIN_API_HOST=127.0.0.1 UNCCOIN_API_PORT=19001 ./scripts/run.sh alice 9001
```

The terminal node can run without an API token when the API is bound to loopback. If you expose
the API beyond localhost, a bearer token is required because `/api/v1/control/*` can perform
wallet/node actions for the local node:

```bash
UNCCOIN_API_HOST=0.0.0.0 \
UNCCOIN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
./scripts/run.sh alice 9000
```

Use the token with control requests:

```bash
curl -H "Authorization: Bearer $UNCCOIN_API_TOKEN" \
  http://127.0.0.1:19000/api/v1/control/sync \
  -H "Content-Type: application/json" \
  -d '{"fast": true}'
```

## 7. Connecting Nodes

At the interactive prompt:

```text
add-peer <host:port>
sync
peers
```

The desktop app also tries the built-in bootstrap peers on launch. It automatically skips the
peer matching the node's own address and lets you disable any bootstrap peer for that launch.
The private `100.x.x.x` bootstrap addresses require the same Tailscale network.

## 8. Mining Backends

Mining mode is selected at runtime:

- `auto`: default. Uses GPU/native if available, otherwise falls back to Python.
- `gpu`: GPU-only backend when available.
- `native`: native C CPU backend.
- `python`: pure Python fallback.

The desktop Mining tab shows which backends are available. If native mining is not built, the
backend button becomes a build action. Startup can warm up and benchmark the selected backend;
that can be skipped on the launch screen.

Build native proof of work manually:

```bash
./scripts/build_native_pow.sh
```

Force a rebuild:

```bash
./scripts/build_native_pow.sh --force
```

Linux NVIDIA/CUDA setup:

```bash
./scripts/setup_runpod_cuda.sh
python3 scripts/benchmark_gpu_pow.py
```

Dedicated GPU miner:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

## 9. Useful CLI Commands

```text
help
peers
known-peers
discover
sync
localself
add-peer <host:port>
alias <wallet-id> <alias>
autosend <wallet-id>
autosend off
mute
unmute
tx <receiver> <amount> <fee>
commit <request-id> <commitment-hash> <fee>
reveal <request-id> <seed> <fee> [salt]
deploy <fee> <json-or-file>
view-contract <contract>
authorize <contract> <request-id> <fee> [valid-blocks]
execute <contract> <gas-limit> <gas-price> <value> <max-fee> <json>
receipt <txid-prefix>
msg <wallet> <content>
messages
mine [description]
automine [description]
stop
blockchain
balance [address]
balances
balances >100
balances <50
txtbalances <relative-path>
txtblockchain <relative-path>
clear
quit
```

Commands that take wallet ids such as `tx`, `msg`, `balance`, `alias`, and `autosend`
accept either a raw wallet address or a locally stored alias.

## 10. Persistence

Local state is stored under `state/` and is ignored by git:

- wallets
- blockchain state
- messages
- aliases
- desktop preferences
- mining tuning data

Wallet JSON files are the sensitive part. The desktop delete action archives wallet files
under `state/deleted/` instead of permanently deleting them.

## 11. Current Scope

UncCoin is a toy cryptocurrency for learning and experimentation. It is intended for trusted
friends and small test networks, not real-value or adversarial deployment.
