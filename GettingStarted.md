# Getting Started

This guide is for running UncCoin locally on one machine first.

If you want multi-device networking afterward, see [Tailscale.md](/Users/frederikedvardsen/Desktop/unccoin/Tailscale.md).

## 0. Prerequisites (maybe)

```bash
sudo apt install gcc
sudo apt install python3.12-dev build-essential
```

## 1. Clone the Repository

```bash
git clone https://github.com/Fleli/UncCoin.git
cd UncCoin
```

## 2. Build Native Proof of Work

UncCoin can build the native proof-of-work module on first mining use, but it is better to build it explicitly once:

```bash
./scripts/build_native_pow.sh
```

Force a rebuild if needed:

```bash
./scripts/build_native_pow.sh --force
```

On a Linux NVIDIA machine such as Runpod, GPU mining can run without building the CPU extension.
Use:

```bash
./scripts/setup_runpod_cuda.sh
```

## 3. Create a Wallet

Each user should create their own wallet:

```bash
python3 -m wallet.cli create --name <wallet-name>
```

Inspect it with:

```bash
python3 -m wallet.cli show --name <wallet-name>
```

Or use the shortcut:

```bash
./scripts/wallet.sh <wallet-name>
```

## 4. Start a Node

Run a node with your wallet:

```bash
./scripts/run.sh <wallet-name> <port>
```

Example:

```bash
./scripts/run.sh mywallet 9000
```

To run a dedicated miner that keeps extending its own preferred branch tip:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 ./scripts/run.sh mywallet 9000
```

In that mode, wallet balances, nonces, and pending transaction checks also follow the preferred tip.

For a dedicated cloud GPU node, use GPU-only mode so the pod does not spin CPU mining workers:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh mywallet 9000
```

You can verify the active GPU backend first with:

```bash
python3 scripts/benchmark_gpu_pow.py
```

## 5. Connect to Other Nodes

After the node is running, connect from the interactive prompt:

```text
add-peer <host:port>
```

Example:

```text
add-peer 127.0.0.1:9000
sync
peers
```

## 6. Use the Interactive CLI

Useful commands:

```text
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

Notes:

- `tx`, `msg`, `balance`, `alias`, and `autosend` accept either a raw wallet address or a locally stored alias.
- `balance` uses the loaded wallet address if no address is given.
- `commit` stores a signed 64-character hex commitment hash under a `request-id`.
- `reveal` uploads a seed for a prior commitment. Seeds are unsigned 256-bit integers.
- `mine` mines one block.
- `automine` keeps mining until `stop` is entered.

## 7. Optional Local Shortcuts

For local testing only, the repo also includes fixed-name wrappers:

```bash
make 9000
make 9001
make 9002
```

These are convenience targets for one-machine testing and are not the recommended way to run real user wallets.

## 8. Persistence

On shutdown, the node persists:

- the canonical blockchain
- pending transactions

That state is keyed by wallet address and reloaded automatically on startup with the same wallet.

## 9. Current Scope

UncCoin is a toy cryptocurrency for learning and experimentation. It is not hardened for real adversarial deployment or real-value use.
