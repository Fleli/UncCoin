import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from config import DEFAULT_CPU_CHUNK_SIZE
from config import DEFAULT_GPU_CHUNK_MULTIPLIER
from config import DEFAULT_GPU_WORKERS
from core.native_pow import gpu_device_ids as native_gpu_device_ids
from core.native_pow import mine_pow_chunk as native_mine_pow_chunk
from core.native_pow import mine_pow_gpu_chunk as native_mine_pow_gpu_chunk
from core.native_pow import request_pow_cancel
from core.native_pow import reset_pow_cancel


@dataclass
class ChunkedMiningResult:
    winner: tuple[int, str] | None
    attempts: int
    elapsed: float
    cancelled: bool
    gpu_failed: bool


@dataclass
class _WorkerOutcome:
    attempts: int = 0
    cancelled: bool = False
    error: Exception | None = None
    winner: tuple[int, str] | None = None


class _NonceChunkAllocator:
    def __init__(self, start_nonce: int) -> None:
        self._next_nonce = start_nonce
        self._lock = threading.Lock()

    def allocate(self, chunk_size: int) -> int:
        with self._lock:
            chunk_start = self._next_nonce
            self._next_nonce += chunk_size
            return chunk_start


class _ProgressTracker:
    def __init__(
        self,
        start_nonce: int,
        progress_interval: int,
        progress_callback: Callable[[int], None] | None,
    ) -> None:
        self._start_nonce = start_nonce
        self._progress_interval = progress_interval
        self._progress_callback = progress_callback
        self._next_progress_mark = progress_interval
        self._total_attempts = 0
        self._lock = threading.Lock()

    def add_attempts(self, attempts: int) -> None:
        if (
            attempts <= 0
            or self._progress_interval <= 0
            or self._progress_callback is None
        ):
            return

        progress_updates: list[int] = []
        with self._lock:
            self._total_attempts += attempts
            while self._total_attempts >= self._next_progress_mark:
                progress_updates.append(self._start_nonce + self._next_progress_mark)
                self._next_progress_mark += self._progress_interval

        for progress_value in progress_updates:
            self._progress_callback(progress_value)


def get_cpu_chunk_size(default: int = DEFAULT_CPU_CHUNK_SIZE) -> int:
    raw_value = os.environ.get("UNCCOIN_CPU_CHUNK_SIZE")
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    if value < 1:
        return default
    return value


def get_gpu_chunk_multiplier(default: int = DEFAULT_GPU_CHUNK_MULTIPLIER) -> int:
    raw_value = os.environ.get("UNCCOIN_GPU_CHUNK_MULTIPLIER")
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    if value < 1:
        return default
    return value


def get_gpu_worker_count(default: int = DEFAULT_GPU_WORKERS) -> int:
    raw_value = os.environ.get("UNCCOIN_GPU_WORKERS")
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    if value < 1:
        return default
    return value


def get_gpu_device_ids(default: tuple[int, ...] | None = None) -> tuple[int, ...]:
    available_device_ids = tuple(native_gpu_device_ids())
    resolved_default = available_device_ids if default is None else tuple(default)
    raw_value = os.environ.get("UNCCOIN_GPU_DEVICE_IDS")
    if raw_value is None or not raw_value.strip():
        return resolved_default

    parsed_ids: list[int] = []
    seen_ids: set[int] = set()
    for raw_item in raw_value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            device_id = int(item)
        except ValueError as error:
            raise ValueError(
                "UNCCOIN_GPU_DEVICE_IDS must be a comma-separated list of integers."
            ) from error
        if device_id < 0:
            raise ValueError("UNCCOIN_GPU_DEVICE_IDS cannot contain negative device IDs.")
        if device_id in seen_ids:
            continue
        parsed_ids.append(device_id)
        seen_ids.add(device_id)

    if not parsed_ids:
        raise ValueError("UNCCOIN_GPU_DEVICE_IDS did not contain any usable device IDs.")

    if available_device_ids:
        unavailable_device_ids = [
            device_id
            for device_id in parsed_ids
            if device_id not in available_device_ids
        ]
        if unavailable_device_ids:
            unavailable_text = ", ".join(str(device_id) for device_id in unavailable_device_ids)
            available_text = ", ".join(str(device_id) for device_id in available_device_ids)
            raise ValueError(
                "UNCCOIN_GPU_DEVICE_IDS requested unavailable CUDA devices "
                f"({unavailable_text}). Visible devices: {available_text}."
            )

    return tuple(parsed_ids)


def run_chunked_mining(
    prefix: str,
    difficulty_bits: int,
    start_nonce: int,
    cpu_workers: int,
    cpu_chunk_size: int,
    gpu_enabled: bool,
    gpu_chunk_size: int,
    gpu_nonces_per_thread: int = 0,
    gpu_threads_per_group: int = 0,
    gpu_chunk_multiplier: int | None = None,
    gpu_workers: int = 1,
    progress_interval: int = 0,
    progress_callback: Callable[[int], None] | None = None,
    cancel_after_seconds: float | None = None,
    tolerate_gpu_failure: bool = False,
    gpu_device_ids: tuple[int, ...] | None = None,
) -> ChunkedMiningResult:
    gpu_dispatch_batch_size = gpu_chunk_size
    resolved_gpu_device_ids = tuple(gpu_device_ids) if gpu_enabled and gpu_device_ids is not None else (
        get_gpu_device_ids() if gpu_enabled else ()
    )
    resolved_gpu_workers_per_device = gpu_workers if gpu_enabled else 0
    if gpu_chunk_multiplier is None:
        gpu_chunk_multiplier = get_gpu_chunk_multiplier()
    total_gpu_chunk_size = gpu_dispatch_batch_size * gpu_chunk_multiplier
    if resolved_gpu_workers_per_device > 0:
        gpu_chunk_size = max(
            1,
            (
                total_gpu_chunk_size
                + resolved_gpu_workers_per_device
                - 1
            ) // resolved_gpu_workers_per_device,
        )
    else:
        gpu_chunk_size = total_gpu_chunk_size
    allocator = _NonceChunkAllocator(start_nonce)
    progress_tracker = _ProgressTracker(
        start_nonce,
        progress_interval,
        progress_callback,
    )
    stop_event = threading.Event()
    winner_lock = threading.Lock()
    winner: tuple[int, str] | None = None
    cpu_outcomes = [_WorkerOutcome() for _ in range(cpu_workers)]
    total_gpu_workers = len(resolved_gpu_device_ids) * resolved_gpu_workers_per_device
    gpu_outcomes = [_WorkerOutcome() for _ in range(total_gpu_workers)] if gpu_enabled else []
    threads: list[threading.Thread] = []

    if cpu_workers < 0:
        raise ValueError("cpu_workers must be non-negative.")
    if cpu_workers > 0 and cpu_chunk_size < 1:
        raise ValueError("cpu_chunk_size must be at least 1 when CPU mining is enabled.")
    if gpu_workers < 0:
        raise ValueError("gpu_workers must be non-negative.")
    if gpu_enabled and gpu_chunk_size < 1:
        raise ValueError("gpu_chunk_size must be at least 1 when GPU mining is enabled.")
    if gpu_enabled and resolved_gpu_workers_per_device < 1:
        raise ValueError("gpu_workers must be at least 1 when GPU mining is enabled.")
    if gpu_enabled and not resolved_gpu_device_ids:
        raise ValueError("No GPU devices were selected for GPU mining.")

    def record_winner(candidate: tuple[int, str]) -> None:
        nonlocal winner
        with winner_lock:
            if winner is None:
                winner = candidate

    def run_cpu_worker(worker_index: int) -> None:
        outcome = cpu_outcomes[worker_index]
        try:
            while not stop_event.is_set():
                chunk_start = allocator.allocate(cpu_chunk_size)
                nonce, block_hash, found, cancelled, attempts = native_mine_pow_chunk(
                    prefix,
                    difficulty_bits,
                    chunk_start,
                    cpu_chunk_size,
                    0,
                    1,
                )
                outcome.attempts += attempts
                progress_tracker.add_attempts(attempts)

                if found:
                    outcome.winner = (nonce, block_hash)
                    record_winner(outcome.winner)
                    stop_event.set()
                    request_pow_cancel()
                    return
                if cancelled:
                    outcome.cancelled = True
                    return
            if outcome.winner is None:
                outcome.cancelled = True
        except Exception as error:  # pragma: no cover - surfaced to caller
            outcome.error = error
            stop_event.set()
            request_pow_cancel()

    def run_gpu_worker(worker_index: int, device_id: int) -> None:
        outcome = gpu_outcomes[worker_index]
        try:
            while not stop_event.is_set():
                chunk_start = allocator.allocate(gpu_chunk_size)
                nonce, block_hash, found, cancelled, attempts = native_mine_pow_gpu_chunk(
                    prefix,
                    difficulty_bits,
                    chunk_start,
                    gpu_chunk_size,
                    1,
                    gpu_nonces_per_thread,
                    gpu_threads_per_group,
                    gpu_dispatch_batch_size,
                    device_id,
                )
                outcome.attempts += attempts
                progress_tracker.add_attempts(attempts)

                if found:
                    outcome.winner = (nonce, block_hash)
                    record_winner(outcome.winner)
                    stop_event.set()
                    request_pow_cancel()
                    return
                if cancelled:
                    outcome.cancelled = True
                    return
            if outcome.winner is None:
                outcome.cancelled = True
        except Exception as error:  # pragma: no cover - surfaced to caller
            outcome.error = error
            if not tolerate_gpu_failure:
                stop_event.set()
                request_pow_cancel()

    reset_pow_cancel()
    start_time = time.perf_counter()

    try:
        for worker_index in range(cpu_workers):
            worker = threading.Thread(target=run_cpu_worker, args=(worker_index,), daemon=True)
            threads.append(worker)
            worker.start()

        if gpu_enabled:
            for device_index, device_id in enumerate(resolved_gpu_device_ids):
                for worker_offset in range(resolved_gpu_workers_per_device):
                    worker_index = (
                        device_index * resolved_gpu_workers_per_device
                        + worker_offset
                    )
                    gpu_worker = threading.Thread(
                        target=run_gpu_worker,
                        args=(worker_index, device_id),
                        daemon=True,
                    )
                    threads.append(gpu_worker)
                    gpu_worker.start()

        if cancel_after_seconds is not None:
            time.sleep(cancel_after_seconds)
            stop_event.set()
            request_pow_cancel()

        join_deadline = None
        if cancel_after_seconds is not None:
            join_deadline = time.perf_counter() + cancel_after_seconds + 5.0

        for worker in threads:
            if join_deadline is None:
                worker.join()
                continue

            remaining = join_deadline - time.perf_counter()
            if remaining > 0:
                worker.join(remaining)

        if any(worker.is_alive() for worker in threads):
            request_pow_cancel()
            raise RuntimeError("Mining workers did not stop after cancellation.")
    finally:
        elapsed = time.perf_counter() - start_time
        reset_pow_cancel()

    cpu_errors = [outcome.error for outcome in cpu_outcomes if outcome.error is not None]
    if cpu_errors:
        raise cpu_errors[0]

    gpu_errors = [outcome.error for outcome in gpu_outcomes if outcome.error is not None]
    gpu_failed = bool(gpu_errors)
    if gpu_failed and not tolerate_gpu_failure:
        raise gpu_errors[0]  # type: ignore[misc]

    attempts = sum(outcome.attempts for outcome in cpu_outcomes)
    cancelled = any(outcome.cancelled for outcome in cpu_outcomes)
    attempts += sum(outcome.attempts for outcome in gpu_outcomes)
    cancelled = cancelled or any(outcome.cancelled for outcome in gpu_outcomes)

    return ChunkedMiningResult(
        winner=winner,
        attempts=attempts,
        elapsed=elapsed,
        cancelled=winner is None and cancelled,
        gpu_failed=gpu_failed,
    )
