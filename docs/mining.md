# Mining

UncCoin uses a simple proof-of-work rule: find a block hash with enough leading zero bits.
The miner has evolved from pure Python into optional native CPU and GPU backends, while
keeping the Python miner as the always-available fallback.

Shoutout to Niklas Unneland, who built [unccoin.no](https://unccoin.no/) around the project.

## Backends

The default mining backend is `auto`:

- `auto`: uses GPU/native mining when available and falls back to Python.
- `gpu`: GPU-only backend when available.
- `native`: native C CPU backend.
- `python`: pure Python fallback.

The desktop Mining tab shows which backends are available. If native mining is not built, the
backend button becomes a build action. Startup can warm up and benchmark the selected backend
so the first mined block does not pay the full initialization cost; this can be skipped from
the launch screen.

Build native proof of work manually:

```bash
./scripts/build_native_pow.sh
```

Force a rebuild:

```bash
./scripts/build_native_pow.sh --force
```

## Tuning

Mining can be tuned with environment variables:

- `UNCCOIN_MINING_CPU_WORKERS`: override CPU worker count. Set `0` for a GPU-only miner.
- `UNCCOIN_GPU_ONLY`: convenience switch for `scripts/run.sh`; defaults CPU workers to `0`
  unless you set an explicit CPU worker count.
- `UNCCOIN_GPU_BATCH_SIZE`: override GPU batch size.
- `UNCCOIN_GPU_NONCES_PER_THREAD`: override nonces checked by each GPU thread per dispatch.
- `UNCCOIN_GPU_THREADS_PER_GROUP`: override GPU threadgroup or block size.
- `UNCCOIN_GPU_DEVICE_IDS`: choose visible CUDA devices, such as `0,1,3`.
- `UNCCOIN_GPU_CHUNK_MULTIPLIER`: adjust scheduled GPU chunk size.
- `UNCCOIN_GPU_WORKERS`: adjust scheduler threads per configured GPU.
- `UNCCOIN_MINING_PROGRESS_INTERVAL`: control how often progress is printed.
- `UNCCOIN_DISABLE_MINING_AUTOTUNE`: disable local mining worker auto-tuning.

When `UNCCOIN_MINING_CPU_WORKERS` is not set, UncCoin benchmarks a few local worker counts
once and caches the fastest result in `state/mining_tuning.json`.

## Private Automine

For a dedicated fast miner, the node CLI supports `--private-automine`.

The assumption behind preferring a private branch tip is majority network hashpower, so it is
effectively a 51% attack strategy. It is for experimentation, not fair public mining.

In that mode the node:

- keeps mining on a preferred branch tip instead of restarting on every competing head
- still rebases if a newly accepted block extends that same preferred branch
- uses that preferred tip for wallet balances, nonces, and pending transaction validation
- broadcasts locally mined blocks as usual

Enable it with the helper script:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

For a dedicated GPU miner:

```bash
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

For a headless cloud GPU miner, use the dedicated launcher:

```bash
./scripts/cloud_automine.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

The cloud launcher defaults to GPU-only mining, disables transaction/mempool relay, reduces
nonce progress output, requests fast sync, starts automine through the local API, and defers
locally mined block persistence until shutdown. It also enables the cloud-native burst
autominer, a mining-only reward-block path where a long-running worker prepares serialized
reward-block prefixes and mines them through a resident backend call. Python hydrates the
mined prefix into a normal block, validates the same proof-of-work and reward rules used by
consensus, and then broadcasts it. For self-mined reward-only blocks with an empty local
mempool, cloud mode uses a fast reward-state update and periodically reruns full chain
verification as a guard. The dedicated cloud launcher disables that periodic full-chain
guard by default for maximum offline throughput; set
`UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS` to a positive block interval to re-enable it.
It also trusts the resident worker's returned block hash while offline, avoiding a duplicate
Python hash check for each accepted burst block; as soon as a peer is connected, blocks are
fully checked before broadcast.
When the periodic guard is disabled, the node still runs a full verification before
shutdown and before opening a peer connection if it has accepted unverified burst blocks;
on shutdown, it saves a pre-verification snapshot first so a long full-chain check cannot
lose the mined chain if the launcher is interrupted.
Per-block broadcast logs are replaced by compact periodic summaries, and offline cloud
miners skip block broadcast serialization until a peer is connected. Peers still receive
locally mined blocks. If you want periodic mined-block saves, set
`UNCCOIN_MINED_BLOCK_PERSIST_INTERVAL` to a positive block interval.

Cloud summary output can be tuned with:

- `UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS`: print every N accepted burst blocks, default `10`
  for direct node launches and `100` for `scripts/cloud_automine.sh`.
- `UNCCOIN_CLOUD_NATIVE_SUMMARY_SECONDS`: if set, also print after this many seconds even
  if the block interval has not been reached.
- `UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS`: run full chain verification every N fast-path
  reward blocks before broadcast, default `100` for direct node launches and `0` for
  `scripts/cloud_automine.sh`. Set `0` to disable the periodic guard.
- `UNCCOIN_CLOUD_NATIVE_BATCH_BLOCKS`: deliver mined blocks from the native worker to
  Python in batches, default `1` for direct node launches and `50` for
  `scripts/cloud_automine.sh`.
- `UNCCOIN_CLOUD_NATIVE_TRUST_WORKER_HASH`: skip the duplicate Python block-hash
  recompute while the cloud-native miner is offline, default `0` for direct node
  launches and `1` for `scripts/cloud_automine.sh`.
- `UNCCOIN_CLOUD_NATIVE_START_NONCE`: start each cloud-native proof-of-work search at
  this nonce, default `0`.
- `UNCCOIN_GPU_CHUNK_MULTIPLIER`: tune GPU dispatch size, default `128` for
  `scripts/cloud_automine.sh`.
- `UNCCOIN_CLOUD_SHUTDOWN_WAIT_SECONDS`: graceful shutdown wait after SIGINT before the
  launcher escalates to SIGTERM, default `600`.

To fall back to the ordinary cloud automine loop:

```bash
UNCCOIN_CLOUD_NATIVE_AUTOMINE=0 ./scripts/cloud_automine.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

## Linux/CUDA and Runpod

The repo includes a Linux/CUDA proof-of-work backend for NVIDIA GPUs.

For a simple Runpod setup:

```bash
./scripts/setup_runpod_cuda.sh
./.venv/bin/python scripts/benchmark_gpu_pow.py
./scripts/cloud_automine.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

If you also want local CPU workers on the pod, set `UNCCOIN_BUILD_CPU_POW_EXTENSION=1`
before running `./scripts/setup_runpod_cuda.sh` so the native CPU extension is built too.

In one live run, the cloud CUDA miner joined just before the sharp increase near the end of
this chart and was solely responsible for that spike:

![Live supply snapshot from unccoin.no](../assets/readme/unccoin-stat-live-crop.png)
