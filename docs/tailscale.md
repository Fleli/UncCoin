# UncCoin Over Tailscale

This guide assumes you have already gone through [Getting started](getting-started.md).

Tailscale is the easiest way to run a small UncCoin network with friends without opening
router ports or exposing nodes to the public internet.

## 1. Install Tailscale

Each participant should install Tailscale and join the same tailnet.

Official docs:

- https://tailscale.com/docs/install
- https://tailscale.com/docs/install/start

## 2. Find Each Node Address

On each machine:

```bash
tailscale ip -4
```

Test connectivity to a friend:

```bash
tailscale ping <peer-tailscale-ip>
```

If `tailscale ping` works, the machines should be able to connect UncCoin nodes over TCP.

## 3. Install UncCoin Dependencies

On each machine:

```bash
git clone https://github.com/Fleli/UncCoin.git
cd UncCoin
python3 -m pip install -r requirements-api.txt
```

For the desktop app, also run:

```bash
./scripts/setup_desktop.sh
```

Native mining is optional. The Python miner works without building anything. Native/GPU
mining can be built from the desktop Mining tab or with:

```bash
./scripts/build_native_pow.sh
```

## 4. Create Wallets

Each participant should create their own wallet:

```bash
python3 -m wallet.cli create --name <wallet-name>
```

Desktop users can create a wallet from the launch screen instead.

## 5. Start Nodes

The helper script binds the P2P node to `0.0.0.0`, so it is reachable over Tailscale:

```bash
./scripts/run.sh <wallet-name> <p2p-port> [peer-tailscale-ip:peer-port ...]
```

First node:

```bash
./scripts/run.sh alice 9000
```

Second node connecting to the first:

```bash
./scripts/run.sh bob 9001 <alice-tailscale-ip>:9000
```

Third node:

```bash
./scripts/run.sh charlie 9002 <alice-tailscale-ip>:9000
```

The node state/control API stays local by default:

```text
P2P:  0.0.0.0:<p2p-port>
API:  127.0.0.1:<p2p-port + 10000>
```

Do not expose the API over Tailscale unless you intentionally want remote programs to control
that local node. If you do need that for a trusted machine, set a bearer token:

```bash
UNCCOIN_API_HOST=0.0.0.0 \
UNCCOIN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
./scripts/run.sh alice 9000
```

Control requests under `/api/v1/control/*` must then include
`Authorization: Bearer <token>`. The desktop app handles this automatically for nodes it
starts and keeps the token in the Electron main process.

## 6. Desktop App With Tailscale

Start the desktop app:

```bash
./scripts/desktop.sh
```

The launch screen lets you choose/create a wallet and select a P2P port. It also shows the
built-in bootstrap peers. The `100.x.x.x` bootstrap peers are Tailscale addresses, so they
only work for machines on the same tailnet. You can disable any bootstrap peer for a specific
launch.

When one of the bootstrap peers is the local node's own address, the desktop launcher skips it
automatically.

## 7. Connect Manually

From the terminal node prompt:

```text
add-peer <peer-tailscale-ip>:<peer-port>
sync
peers
```

From the desktop app, use the Network tab to connect to a peer or retry bootstrap peers.

## 8. Mining

For normal testnet use, the desktop app's default `auto` miner is enough. It uses GPU/native
mining when available and falls back to Python when native mining is not built.

For a dedicated miner:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-tailscale-ip:peer-port ...]
```

For a dedicated Linux NVIDIA/CUDA miner:

```bash
./scripts/setup_runpod_cuda.sh
python3 scripts/benchmark_gpu_pow.py
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-tailscale-ip:peer-port ...]
```

## 9. Notes

- Tailscale is only networking; it is not a Python dependency.
- Keep wallet JSON files private.
- Keep API tokens private; they authorize wallet-signing control actions.
- The current node sync is intended for small trusted test networks.
- UncCoin is not hardened for real-value or adversarial deployment.
