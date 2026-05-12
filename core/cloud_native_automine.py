import json
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from core.block import Block
from core.block import ProofOfWorkCancelled
from core.block import PrefixProofOfWorkResult
from core.block import mine_serialized_block_prefix_resident
from core.hashing import sha256_block_hash
from core.serialization import serialize_transaction
from core.transaction import TRANSACTION_KIND_TRANSFER
from core.transaction import TRANSACTION_VERSION_TYPED
from core.transaction import Transaction
from core.utils.constants import MINING_REWARD_AMOUNT
from core.utils.constants import MINING_REWARD_SENDER
from core.utils.mining import create_mining_reward_transaction


CloudNativeAutomineEventKind = Literal["block", "blocks", "cancelled", "error"]


@dataclass(frozen=True)
class CloudNativeDifficultySchedule:
    difficulty_bits: int
    genesis_difficulty_bits: int | None
    difficulty_growth_factor: int
    difficulty_growth_start_height: int
    difficulty_growth_bits: int
    difficulty_schedule_activation_height: int

    def difficulty_bits_for_height(self, block_height: int) -> int:
        if block_height < 0:
            raise ValueError("block_height must be non-negative.")
        if self.genesis_difficulty_bits is not None and self.genesis_difficulty_bits < 0:
            raise ValueError("genesis_difficulty_bits must be non-negative.")
        if self.difficulty_growth_factor < 2:
            raise ValueError("difficulty_growth_factor must be at least 2.")
        if self.difficulty_growth_start_height < 1:
            raise ValueError("difficulty_growth_start_height must be at least 1.")
        if self.difficulty_growth_bits < 1:
            raise ValueError("difficulty_growth_bits must be at least 1.")

        if block_height == 0:
            return (
                self.genesis_difficulty_bits
                if self.genesis_difficulty_bits is not None
                else self.difficulty_bits
            )

        if block_height < self.difficulty_schedule_activation_height:
            return self.difficulty_bits

        if block_height < self.difficulty_growth_start_height:
            return self.difficulty_bits

        growth_steps = 0
        threshold = self.difficulty_growth_start_height
        while block_height >= threshold:
            growth_steps += 1
            threshold *= self.difficulty_growth_factor

        return self.difficulty_bits + (growth_steps * self.difficulty_growth_bits)


@dataclass(frozen=True)
class CloudNativeAutomineConfig:
    miner_address: str
    description: str
    start_tip_hash: str
    start_height: int
    difficulty_schedule: CloudNativeDifficultySchedule
    mining_backend: str
    batch_blocks: int = 1
    start_nonce: int = 0


@dataclass(frozen=True)
class CloudNativeAutomineEvent:
    kind: CloudNativeAutomineEventKind
    block: Block | None = None
    blocks: tuple[Block, ...] = ()
    error: BaseException | None = None


@dataclass(frozen=True)
class RewardOnlyBlockTemplate:
    miner_address: str
    description: str
    payload_text: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload_text",
            json.dumps(
                {
                    "amount": str(MINING_REWARD_AMOUNT),
                    "receiver": self.miner_address,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def reward_transaction(self, timestamp: datetime) -> Transaction:
        return Transaction(
            sender=MINING_REWARD_SENDER,
            receiver=self.miner_address,
            amount=MINING_REWARD_AMOUNT,
            fee=Decimal("0.0"),
            timestamp=timestamp,
            nonce=0,
            kind=TRANSACTION_KIND_TRANSFER,
            payload={
                "receiver": self.miner_address,
                "amount": str(MINING_REWARD_AMOUNT),
            },
            version=TRANSACTION_VERSION_TYPED,
        )

    def serialized_reward_transaction(self, timestamp: datetime) -> str:
        return (
            f"{TRANSACTION_VERSION_TYPED}|{TRANSACTION_KIND_TRANSFER}|"
            f"{MINING_REWARD_SENDER}|{self.miner_address}|"
            f"{MINING_REWARD_AMOUNT}|0.0|{timestamp.isoformat()}|0|||"
            f"{self.payload_text}"
        )

    def block_prefix(
        self,
        *,
        block_id: int,
        previous_hash: str,
        timestamp: datetime,
    ) -> str:
        return (
            f"{block_id}|{self.serialized_reward_transaction(timestamp)}|"
            f"{self.description}|{previous_hash}|"
        )


def build_reward_only_block(
    *,
    block_id: int,
    previous_hash: str,
    miner_address: str,
    description: str,
    timestamp: datetime | None = None,
) -> Block:
    return Block(
        block_id=block_id,
        transactions=[
            create_mining_reward_transaction(
                miner_address,
                timestamp=timestamp,
            ),
        ],
        hash_function=sha256_block_hash,
        description=description,
        previous_hash=previous_hash,
    )


def build_reward_only_block_prefix(
    *,
    block_id: int,
    previous_hash: str,
    reward_transaction: Transaction,
    description: str,
) -> str:
    return (
        f"{block_id}|{serialize_transaction(reward_transaction)}|"
        f"{description}|{previous_hash}|"
    )


def hydrate_mined_reward_only_block(
    *,
    block_id: int,
    previous_hash: str,
    reward_transaction: Transaction,
    description: str,
    proof_of_work_result: PrefixProofOfWorkResult,
) -> Block:
    block = Block.__new__(Block)
    block.block_id = block_id
    block.transactions = [reward_transaction]
    block.hash_function = sha256_block_hash
    block.description = description
    block.previous_hash = previous_hash
    block.nonce = proof_of_work_result.nonce
    block.nonces_checked = proof_of_work_result.attempts
    block.block_hash = proof_of_work_result.block_hash
    return block


def mine_reward_only_blocks(
    config: CloudNativeAutomineConfig,
    output_queue: "queue.Queue[CloudNativeAutomineEvent]",
    stop_event: threading.Event,
) -> None:
    previous_hash = config.start_tip_hash
    block_height = config.start_height + 1
    batch_blocks = max(1, int(config.batch_blocks))
    start_nonce = max(0, int(config.start_nonce))
    mined_batch: list[Block] = []
    block_template = RewardOnlyBlockTemplate(
        miner_address=config.miner_address,
        description=config.description,
    )

    try:
        while not stop_event.is_set():
            timestamp = datetime.now()
            prefix = block_template.block_prefix(
                block_id=block_height,
                previous_hash=previous_hash,
                timestamp=timestamp,
            )
            proof_of_work_result = mine_serialized_block_prefix_resident(
                prefix,
                config.difficulty_schedule.difficulty_bits_for_height(block_height),
                start_nonce=start_nonce,
                mining_backend=config.mining_backend,
            )
            reward_transaction = block_template.reward_transaction(timestamp)
            block = hydrate_mined_reward_only_block(
                block_id=block_height,
                previous_hash=previous_hash,
                reward_transaction=reward_transaction,
                description=config.description,
                proof_of_work_result=proof_of_work_result,
            )

            if stop_event.is_set():
                return
            mined_batch.append(block)

            previous_hash = block.block_hash
            block_height += 1
            if len(mined_batch) >= batch_blocks:
                if not _put_block_batch(output_queue, mined_batch, stop_event):
                    return
                mined_batch = []
    except ProofOfWorkCancelled:
        if mined_batch:
            _put_block_batch(output_queue, mined_batch, stop_event)
        if not stop_event.is_set():
            _put_event(
                output_queue,
                CloudNativeAutomineEvent(kind="cancelled"),
                stop_event,
            )
    except BaseException as error:
        if mined_batch:
            _put_block_batch(output_queue, mined_batch, stop_event)
        _put_event(
            output_queue,
            CloudNativeAutomineEvent(kind="error", error=error),
            stop_event,
        )


def _put_block_batch(
    output_queue: "queue.Queue[CloudNativeAutomineEvent]",
    blocks: list[Block],
    stop_event: threading.Event,
) -> bool:
    if not blocks:
        return True
    if len(blocks) == 1:
        event = CloudNativeAutomineEvent(kind="block", block=blocks[0])
    else:
        event = CloudNativeAutomineEvent(kind="blocks", blocks=tuple(blocks))
    return _put_event(output_queue, event, stop_event)


def _put_event(
    output_queue: "queue.Queue[CloudNativeAutomineEvent]",
    event: CloudNativeAutomineEvent,
    stop_event: threading.Event,
) -> bool:
    while not stop_event.is_set():
        try:
            output_queue.put(event, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False
