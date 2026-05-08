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

## Linux/CUDA and Runpod

The repo includes a Linux/CUDA proof-of-work backend for NVIDIA GPUs.

For a simple Runpod setup:

```bash
./scripts/setup_runpod_cuda.sh
python3 scripts/benchmark_gpu_pow.py
UNCCOIN_PRIVATE_AUTOMINE=1 UNCCOIN_GPU_ONLY=1 ./scripts/run.sh <wallet-name> <p2p-port> [peer-host:peer-port ...]
```

If you also want local CPU workers on the pod, set `UNCCOIN_BUILD_CPU_POW_EXTENSION=1`
before running `./scripts/setup_runpod_cuda.sh` so the native CPU extension is built too.

In one live run, the cloud CUDA miner joined just before the sharp increase near the end of
this chart and was solely responsible for that spike:

![Live supply snapshot from unccoin.no](../assets/readme/unccoin-stat-live-crop.png)
