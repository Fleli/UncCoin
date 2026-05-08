# UncCoin

UncCoin is a toy but fairly complete proof-of-work cryptocurrency built in Python. It has
signed wallets and transactions, miner rewards and fees, peer-to-peer relay, chain sync,
persistence, smart-contract-style UVM execution, a local FastAPI node API, and an Electron
desktop app.

It is built for learning, experimentation, and small trusted friend networks. It is not a
real-money chain and is not hardened for adversarial deployment.

## Quick Start

Fetch and install dependencies:

```bash
git clone https://github.com/Fleli/UncCoin.git
cd UncCoin
./scripts/setup_desktop.sh
```

Run the desktop app:

```bash
./scripts/desktop.sh
```

Or run a terminal node:

```bash
python3 -m wallet.cli create --name alice
./scripts/run.sh alice 9000
```

Check a checkout before sharing or running it:

```bash
./scripts/check.sh
```

## Documentation

- [Getting started](docs/getting-started.md): install dependencies, create wallets, run desktop or terminal nodes, connect peers, and understand local state.
- [Desktop app](docs/desktop.md): launch flow, wallet selection, node startup, miner warmup, and the main desktop screens.
- [Node API](docs/node-api.md): local FastAPI read endpoints, authenticated control endpoints, API ports, and bearer-token behavior.
- [Node CLI](docs/node-cli.md): terminal commands for peers, transfers, messages, contracts, mining, balances, and local aliases.
- [Contracts and UVM](docs/contracts-and-uvm.md): typed transactions, commitments, reveals, deploy/authorize/execute flows, receipts, and UVM instructions.
- [Mining](docs/mining.md): proof-of-work backends, tuning variables, private automine mode, GPU setup, and Runpod notes.
- [Tailscale networking](docs/tailscale.md): run a small multi-device UncCoin network without opening router ports.
- [Assembler](assembler/README.md): compile readable `.uvm-asm` programs into deployable UVM JSON.

## Main Features

- Signed wallet transactions with balances and nonces.
- SHA-256 proof of work with Python, native CPU, and GPU-oriented mining paths.
- P2P transaction, block, and wallet-message relay.
- Chain sync, orphan handling, and canonical-chain persistence.
- Local state/control API for desktop and other local programs.
- Desktop GUI for wallet, transfer, mining, blockchain, network, messages, and contract workflows.
- Typed transactions for transfers, commitments, reveals, deploys, authorizations, and UVM execution.

## License

UncCoin is released under the [MIT License](LICENSE).
