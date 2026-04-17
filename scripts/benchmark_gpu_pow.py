import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DEFAULT_GPU_BATCH_SIZE
from config import DEFAULT_GPU_CHUNK_MULTIPLIER
from config import DEFAULT_GPU_NONCES_PER_THREAD
from config import DEFAULT_GPU_WORKERS
from core.mining_scheduler import get_cpu_chunk_size
from core.mining_scheduler import get_gpu_device_ids
from core.mining_scheduler import run_chunked_mining
from core.native_pow import gpu_available
from core.native_pow import gpu_properties


BENCHMARK_PREFIX = "1||bench|" + ("0" * 64) + "|"
BENCHMARK_START_NONCE = 100_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the active GPU proof-of-work backend.")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_GPU_BATCH_SIZE)
    parser.add_argument("--nonces-per-thread", type=int, default=DEFAULT_GPU_NONCES_PER_THREAD)
    parser.add_argument("--threads-per-group", type=int, default=0)
    parser.add_argument("--chunk-multiplier", type=int, default=DEFAULT_GPU_CHUNK_MULTIPLIER)
    parser.add_argument("--gpu-workers", type=int, default=DEFAULT_GPU_WORKERS)
    parser.add_argument("--cpu-workers", type=int, default=0)
    parser.add_argument(
        "--gpu-device-ids",
        help="Optional comma-separated CUDA device ids. Defaults to all visible devices.",
    )
    args = parser.parse_args()

    if args.gpu_device_ids is not None:
        os.environ["UNCCOIN_GPU_DEVICE_IDS"] = args.gpu_device_ids

    if not gpu_available():
        raise SystemExit("GPU backend unavailable.")

    selected_gpu_device_ids = get_gpu_device_ids()
    print(f"GPU devices: {selected_gpu_device_ids}")
    print(
        "GPU properties:",
        {device_id: gpu_properties(device_id) for device_id in selected_gpu_device_ids},
    )

    result = run_chunked_mining(
        BENCHMARK_PREFIX,
        256,
        BENCHMARK_START_NONCE,
        args.cpu_workers,
        get_cpu_chunk_size(),
        True,
        args.batch_size,
        args.nonces_per_thread,
        args.threads_per_group,
        args.chunk_multiplier,
        args.gpu_workers,
        cancel_after_seconds=args.seconds,
        tolerate_gpu_failure=False,
        gpu_device_ids=selected_gpu_device_ids,
    )

    hash_rate = result.attempts / max(result.elapsed, 1e-9)
    print(f"Attempts: {result.attempts}")
    print(f"Elapsed: {result.elapsed:.3f}s")
    print(f"Hash rate: {hash_rate / 1_000_000:.2f} MH/s")


if __name__ == "__main__":
    main()
