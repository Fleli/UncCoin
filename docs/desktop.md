# Desktop App

The desktop app is the easiest way to run UncCoin locally. It starts the Python node for you,
creates or selects wallets, passes a per-run API bearer token to the node API, and shows the
current chain, wallet, mining, network, message, and contract state.

## Setup

Install desktop dependencies once:

```bash
./scripts/setup_desktop.sh
```

This creates a local `.venv`, installs Python API dependencies there, and installs desktop
npm dependencies. On Debian/Ubuntu this avoids the system Python
`externally-managed-environment` error.

Start the app:

```bash
./scripts/desktop.sh
```

Build the desktop frontend without launching it:

```bash
./scripts/build_desktop.sh
```

## Launch Flow

The launch screen lets you:

- select an existing wallet by name
- create a new wallet and start it immediately
- choose the P2P port and save it as that wallet's preferred port
- choose the API port, normally `P2P port + 10000`
- disable bootstrap peers for this launch
- skip miner warmup if you want the node window to open immediately
- archive a wallet into `state/deleted/` instead of permanently deleting it

Multiple desktop instances can run at once. The desktop dev server uses a free local port
automatically; running nodes still need distinct P2P/API ports.

## Bootstrap Peers

The app tries the built-in bootstrap peers when a node starts. If one of those peers is the
node's own address, it is skipped automatically. The Network tab can retry bootstrap peers
later if peers disconnect and reconnect in only one direction.

The private `100.x.x.x` bootstrap addresses require the same Tailscale network.

## Main Screens

- Overview: current wallet summary, chain metrics, all balances, and recent blocks.
- Blockchain: canonical blocks, transaction details, metadata, and block search by height or hash.
- Transfer: send funds, pick recipients, and see pending outgoing transfers.
- Mining: backend selection, warmup/build actions, manual mining, automine, nonce progress, and active miners.
- Wallet: aliases, autosend, and hidden-by-default public/private key display.
- Network: peers, sync, bootstrap retry, and ingress/egress stats.
- Messages: local wallet messages and unread counts.
- Contracts: deploy, authorize, execute, commitments, reveals, and receipts.
- Logs: node output captured by the desktop bridge.

## API Token Behavior

The desktop app starts nodes with a per-run `UNCCOIN_API_TOKEN`. It keeps that token in the
Electron main process and uses it for `/api/v1/control/*` actions. Read-only API routes remain
usable without a token.

See [Node API](node-api.md) for the API route layout and security model.
