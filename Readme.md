# UncCoin

UncCoin is a toy but fairly complete proof-of-work cryptocurrency built in Python. It supports signed wallets and transactions, balances and nonces, miner rewards and fees, peer-to-peer transaction and block relay, chain sync, orphan handling, persistence, and an interactive node CLI.

## What It Does

- signed transactions with balances and nonces
- fixed mining rewards and miner fees
- SHA-256 proof of work
- P2P transaction, block, and wallet-message relay
- chain sync on connect
- orphan block handling
- canonical-chain persistence
- interactive node CLI
- private automine mode for dedicated miners

## PoW Evolution

The proof-of-work rule stayed simple: find a block hash with enough leading zero bits. The implementation evolved like this:

- started as a pure Python miner
- moved the hot nonce-search loop into a native C extension
- added Apple Metal support for local GPU mining on macOS
- added a Linux/CUDA backend, chunked CPU/GPU scheduling, and local autotuning

Shoutout to Niklas Unneland, who built [unccoin.no](https://unccoin.no/) around the project.

## Docs

- [GettingStarted.md](/Users/frederikedvardsen/Desktop/unccoin/GettingStarted.md)
  First local setup, wallet creation, native build, and running nodes.
- [Tailscale.md](/Users/frederikedvardsen/Desktop/unccoin/Tailscale.md)
  Running UncCoin across multiple devices over Tailscale.

## Interactive Node Commands

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
send <host:port> <json>
clear
quit
<raw json>
```

Commands that take wallet ids such as `tx`, `msg`, `balance`, and `alias` accept either a raw wallet address or a locally stored alias.

## Local Convenience Commands

These are mainly for local testing on one machine.

```bash
make wallet name=alice
make show-wallet name=alice
make 9000
make 9001
make 9002
```

## Mining Tuning

Mining can be tuned with environment variables:

- `UNCCOIN_MINING_CPU_WORKERS`
  Override the number of CPU workers used for proof of work. Set it to `0` for a GPU-only miner.
- `UNCCOIN_GPU_ONLY`
  Convenience switch for `scripts/run.sh`. When set to `1`, it defaults
  `UNCCOIN_MINING_CPU_WORKERS=0` unless you already set an explicit CPU worker count.
- `UNCCOIN_GPU_BATCH_SIZE`
  Override the GPU batch size. The best value depends on the machine and backend.
- `UNCCOIN_GPU_NONCES_PER_THREAD`
  Override the number of nonces each GPU thread checks before the next dispatch.
- `UNCCOIN_GPU_THREADS_PER_GROUP`
  Override the GPU threadgroup or block size.
- `UNCCOIN_GPU_DEVICE_IDS`
  Override which visible CUDA devices are used, as a comma-separated list such as `0,1,3`.
  By default, the Linux/CUDA backend uses all visible GPUs.
- `UNCCOIN_GPU_CHUNK_MULTIPLIER`
  Override how much work each scheduled GPU chunk contains beyond a single dispatch.
- `UNCCOIN_GPU_WORKERS`
  Override how many scheduler threads feed each configured GPU device.
- `UNCCOIN_MINING_PROGRESS_INTERVAL`
  Control how often mining progress is printed. Larger values reduce terminal overhead.
- `UNCCOIN_DISABLE_MINING_AUTOTUNE`
  Disable the local mining worker auto-tuner.

When `UNCCOIN_MINING_CPU_WORKERS` is not set, UncCoin benchmarks a few local worker counts once and
caches the fastest result in `state/mining_tuning.json`. This only affects local mining execution.

## Private Automine Mode

For a dedicated fast miner, the node CLI supports `--private-automine`.

The assumption behind preferring a private branch tip is majority network hashpower, so it is effectively a 51% attack strategy.

In that mode the node:

- keeps mining on a preferred branch tip instead of restarting on every competing head
- still rebases if a newly accepted block extends that same preferred branch
- uses that preferred tip for wallet balances, nonces, and pending transaction validation
- broadcasts locally mined blocks as usual

With the helper script you can enable it like this:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 ./scripts/run.sh <wallet-name> <port> [peer-host:peer-port ...]
```

For a dedicated cloud GPU miner, combine it with GPU-only mode:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <port> [peer-host:peer-port ...]
```

## Runpod 4090

The repo now has a Linux/CUDA proof-of-work backend for NVIDIA GPUs.

In the live run shown below, the cloud CUDA miner joined just before the very sharp increase near the end of the chart and was solely responsible for that spike. It only ran for a couple of hours, but in that window it pushed issuance up by several thousand block rewards at `10` coins each.

![Live supply snapshot from unccoin.no](assets/readme/unccoin-stat-live-crop.png)

For a simple Runpod setup:

```bash
./scripts/setup_runpod_cuda.sh
python3 scripts/benchmark_gpu_pow.py
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <port> [peer-host:peer-port ...]
```

If you also want local CPU workers on the pod, set `UNCCOIN_BUILD_CPU_POW_EXTENSION=1`
before `./scripts/setup_runpod_cuda.sh` so the native CPU extension is built too.
