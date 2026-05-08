import os
from dataclasses import dataclass, field
from typing import Callable

from config import DEFAULT_GPU_BATCH_SIZE, DEFAULT_MINING_PROGRESS_INTERVAL
from core.mining_backend import MINING_BACKEND_AUTO
from core.mining_backend import MINING_BACKEND_GPU
from core.mining_backend import MINING_BACKEND_NATIVE
from core.mining_backend import MINING_BACKEND_PYTHON
from core.mining_backend import normalize_mining_backend
from core.mining_backend import selected_mining_backend
from core.mining_tuning import get_tuned_gpu_chunk_multiplier
from core.mining_tuning import get_tuned_gpu_launch_config
from core.mining_tuning import get_tuned_gpu_worker_count
from core.mining_tuning import get_tuned_worker_count
from core.mining_scheduler import get_cpu_chunk_size
from core.mining_scheduler import get_gpu_device_ids
from core.mining_scheduler import run_chunked_mining
from core.native_pow import gpu_available as native_gpu_available
from core.python_pow import run_python_mining
from core.serialization import serialize_block_prefix
from core.transaction import Transaction


@dataclass
class Block:
    block_id: int
    transactions: list[Transaction]
    hash_function: Callable[["Block"], str]
    description: str
    previous_hash: str
    nonce: int = 0
    nonces_checked: int | None = None
    block_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.block_hash = self.hash_function(self)

    def to_dict(self) -> dict:
        block_data = {
            "block_id": self.block_id,
            "transactions": [transaction.to_dict() for transaction in self.transactions],
            "description": self.description,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "block_hash": self.block_hash,
        }
        if self.nonces_checked is not None:
            block_data["nonces_checked"] = self.nonces_checked
        return block_data

    @classmethod
    def from_dict(
        cls,
        block_data: dict,
        hash_function: Callable[["Block"], str],
    ) -> "Block":
        transactions = [
            Transaction.from_dict(transaction_data)
            for transaction_data in block_data["transactions"]
        ]
        provided_block_hash = block_data.get("block_hash")
        if provided_block_hash is None:
            return cls(
                block_id=int(block_data["block_id"]),
                transactions=transactions,
                hash_function=hash_function,
                description=block_data["description"],
                previous_hash=block_data["previous_hash"],
                nonce=int(block_data.get("nonce", 0)),
                nonces_checked=(
                    int(block_data["nonces_checked"])
                    if block_data.get("nonces_checked") is not None
                    else None
                ),
            )

        block = cls.__new__(cls)
        block.block_id = int(block_data["block_id"])
        block.transactions = transactions
        block.hash_function = hash_function
        block.description = block_data["description"]
        block.previous_hash = block_data["previous_hash"]
        block.nonce = int(block_data.get("nonce", 0))
        block.nonces_checked = (
            int(block_data["nonces_checked"])
            if block_data.get("nonces_checked") is not None
            else None
        )
        block.block_hash = provided_block_hash
        return block


class ProofOfWorkCancelled(Exception):
    pass


def _read_int_env(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    if value < minimum:
        return default
    return value


def has_leading_zero_bits(block_hash: str, difficulty_bits: int) -> bool:
    binary_hash = bin(int(block_hash, 16))[2:].zfill(len(block_hash) * 4)
    return binary_hash.startswith("0" * difficulty_bits)


def hash_to_binary(block_hash: str) -> str:
    return bin(int(block_hash, 16))[2:].zfill(len(block_hash) * 4)


def short_binary_hash(block_hash: str, difficulty_bits: int) -> str:
    preview_length = difficulty_bits + 16
    return f"{hash_to_binary(block_hash)[:preview_length]}..."


def proof_of_work(
    block: Block,
    difficulty_bits: int,
    progress_callback: Callable[[int], None] | None = None,
    progress_interval: int = DEFAULT_MINING_PROGRESS_INTERVAL,
    mining_backend: str | None = None,
) -> str:
    if (
        block.hash_function.__module__ != "core.hashing"
        or block.hash_function.__name__ != "sha256_block_hash"
    ):
        raise ValueError("Proof-of-work only supports core.hashing.sha256_block_hash.")

    backend = (
        selected_mining_backend()
        if mining_backend is None
        else normalize_mining_backend(mining_backend)
    )
    if backend == MINING_BACKEND_PYTHON:
        return _python_proof_of_work(
            block,
            difficulty_bits,
            progress_callback,
            progress_interval,
        )
    if backend == MINING_BACKEND_NATIVE:
        return _native_proof_of_work(
            block,
            difficulty_bits,
            progress_callback,
            progress_interval,
            gpu_mode="disabled",
        )
    if backend == MINING_BACKEND_GPU:
        return _native_proof_of_work(
            block,
            difficulty_bits,
            progress_callback,
            progress_interval,
            gpu_mode="required",
        )

    try:
        return _native_proof_of_work(
            block,
            difficulty_bits,
            progress_callback,
            progress_interval,
            gpu_mode=MINING_BACKEND_AUTO,
        )
    except ProofOfWorkCancelled:
        raise
    except Exception:
        return _python_proof_of_work(
            block,
            difficulty_bits,
            progress_callback,
            progress_interval,
        )


def _native_proof_of_work(
    block: Block,
    difficulty_bits: int,
    progress_callback: Callable[[int], None] | None,
    progress_interval: int,
    gpu_mode: str,
) -> str:
    prefix = serialize_block_prefix(block)
    native_progress_interval = 0
    if progress_callback is not None:
        native_progress_interval = _read_int_env(
            "UNCCOIN_MINING_PROGRESS_INTERVAL",
            progress_interval,
            minimum=0,
        )
    default_worker_count = max(1, os.cpu_count() or 1)
    native_gpu_enabled = native_gpu_available()
    if gpu_mode == "required" and not native_gpu_enabled:
        raise ValueError("GPU mining is unavailable.")
    gpu_enabled = native_gpu_enabled and gpu_mode != "disabled"
    gpu_batch_size = _read_int_env(
        "UNCCOIN_GPU_BATCH_SIZE",
        DEFAULT_GPU_BATCH_SIZE,
        minimum=1,
    )
    gpu_device_ids = get_gpu_device_ids() if gpu_enabled else ()
    representative_gpu_device_id = gpu_device_ids[0] if gpu_device_ids else None
    if gpu_enabled:
        default_gpu_nonces_per_thread, default_gpu_threads_per_group = (
            get_tuned_gpu_launch_config(
                gpu_batch_size,
                representative_gpu_device_id,
            )
        )
    else:
        default_gpu_nonces_per_thread, default_gpu_threads_per_group = (0, 0)
    gpu_nonces_per_thread = _read_int_env(
        "UNCCOIN_GPU_NONCES_PER_THREAD",
        default_gpu_nonces_per_thread,
        minimum=1,
    ) if gpu_enabled else 0
    gpu_threads_per_group = _read_int_env(
        "UNCCOIN_GPU_THREADS_PER_GROUP",
        default_gpu_threads_per_group,
        minimum=1,
    ) if gpu_enabled else 0
    gpu_chunk_multiplier = _read_int_env(
        "UNCCOIN_GPU_CHUNK_MULTIPLIER",
        get_tuned_gpu_chunk_multiplier(
            gpu_batch_size,
            gpu_nonces_per_thread,
            gpu_threads_per_group,
            representative_gpu_device_id,
        ) if gpu_enabled else 1,
        minimum=1,
    ) if gpu_enabled else 1
    gpu_worker_count = _read_int_env(
        "UNCCOIN_GPU_WORKERS",
        get_tuned_gpu_worker_count(
            gpu_batch_size,
            gpu_nonces_per_thread,
            gpu_threads_per_group,
            gpu_chunk_multiplier,
            representative_gpu_device_id,
        ) if gpu_enabled else 1,
        minimum=1,
    ) if gpu_enabled else 0
    if gpu_mode == "required":
        worker_count = 0
    elif os.environ.get("UNCCOIN_MINING_CPU_WORKERS") is not None:
        worker_count = _read_int_env(
            "UNCCOIN_MINING_CPU_WORKERS",
            default_worker_count,
            minimum=0,
        )
    else:
        worker_count = get_tuned_worker_count(
            default_worker_count,
            gpu_enabled,
            gpu_batch_size,
            gpu_nonces_per_thread,
            gpu_threads_per_group,
            gpu_chunk_multiplier,
            gpu_worker_count,
            representative_gpu_device_id,
        )
    if worker_count == 0 and not gpu_enabled:
        raise ValueError("GPU mining is unavailable, so UNCCOIN_MINING_CPU_WORKERS cannot be 0.")
    mining_result = run_chunked_mining(
        prefix,
        difficulty_bits,
        block.nonce,
        worker_count,
        get_cpu_chunk_size(),
        gpu_enabled,
        gpu_batch_size,
        gpu_nonces_per_thread,
        gpu_threads_per_group,
        gpu_chunk_multiplier,
        gpu_worker_count,
        native_progress_interval,
        progress_callback,
        tolerate_gpu_failure=True,
        gpu_device_ids=gpu_device_ids,
    )

    if mining_result.winner is None:
        raise ProofOfWorkCancelled("Proof of work was cancelled.")

    block.nonce, block.block_hash = mining_result.winner
    block.nonces_checked = mining_result.attempts

    return block.block_hash


def _python_proof_of_work(
    block: Block,
    difficulty_bits: int,
    progress_callback: Callable[[int], None] | None,
    progress_interval: int,
) -> str:
    mining_result = run_python_mining(
        serialize_block_prefix(block),
        difficulty_bits,
        block.nonce,
        progress_interval,
        progress_callback,
    )
    if mining_result.winner is None:
        raise ProofOfWorkCancelled("Proof of work was cancelled.")

    block.nonce, block.block_hash = mining_result.winner
    block.nonces_checked = mining_result.attempts
    return block.block_hash


def verify_block(block: Block, difficulty_bits: int) -> bool:
    return get_block_verification_error(block, difficulty_bits) is None


def get_block_verification_error(block: Block, difficulty_bits: int) -> str | None:
    expected_hash = block.hash_function(block)
    if block.block_hash != expected_hash:
        return "block hash does not match block contents"
    if not has_leading_zero_bits(block.block_hash, difficulty_bits):
        return (
            f"block hash does not satisfy proof-of-work difficulty "
            f"{difficulty_bits}"
        )
    return None
