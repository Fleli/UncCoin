import hashlib
import time
from dataclasses import dataclass
from typing import Callable

from core.native_pow import pow_cancel_requested


@dataclass(frozen=True)
class PythonMiningResult:
    winner: tuple[int, str] | None
    attempts: int
    elapsed: float
    cancelled: bool


def _has_leading_zero_bits(block_hash: str, difficulty_bits: int) -> bool:
    if difficulty_bits <= 0:
        return True
    binary_hash = bin(int(block_hash, 16))[2:].zfill(len(block_hash) * 4)
    return binary_hash.startswith("0" * difficulty_bits)


def run_python_mining(
    prefix: str,
    difficulty_bits: int,
    start_nonce: int,
    progress_interval: int = 0,
    progress_callback: Callable[[int], None] | None = None,
) -> PythonMiningResult:
    started_at = time.perf_counter()
    nonce = int(start_nonce)
    attempts = 0
    next_progress_mark = max(1, progress_interval) if progress_callback is not None else 0

    while True:
        if pow_cancel_requested():
            return PythonMiningResult(
                winner=None,
                attempts=attempts,
                elapsed=time.perf_counter() - started_at,
                cancelled=True,
            )

        block_hash = hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).hexdigest()
        attempts += 1
        if _has_leading_zero_bits(block_hash, difficulty_bits):
            return PythonMiningResult(
                winner=(nonce, block_hash),
                attempts=attempts,
                elapsed=time.perf_counter() - started_at,
                cancelled=False,
            )

        if (
            progress_callback is not None
            and progress_interval > 0
            and attempts >= next_progress_mark
        ):
            progress_callback(start_nonce + next_progress_mark)
            next_progress_mark += progress_interval

        nonce += 1
