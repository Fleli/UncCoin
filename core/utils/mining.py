from datetime import datetime
from decimal import Decimal

from core.block import Block
from core.transaction import Transaction
from core.utils.constants import MINING_REWARD_AMOUNT, MINING_REWARD_SENDER


def create_mining_reward_transaction(
    miner_address: str,
    total_fees: Decimal = Decimal("0.0"),
    timestamp: datetime | None = None,
) -> Transaction:
    return Transaction(
        sender=MINING_REWARD_SENDER,
        receiver=miner_address,
        amount=MINING_REWARD_AMOUNT + total_fees,
        fee=Decimal("0.0"),
        timestamp=timestamp or datetime.now(),
    )


def is_mining_reward_transaction(transaction: Transaction) -> bool:
    return transaction.sender == MINING_REWARD_SENDER


def validate_mining_reward_transaction(block: Block) -> bool:
    return get_mining_reward_validation_error(block) is None


def get_mining_reward_validation_error(block: Block) -> str | None:
    structure_error = get_mining_reward_structure_error(block)
    if structure_error is not None:
        return structure_error

    if block.block_id == 0:
        return None

    expected_total_fees = sum(
        (
            transaction.fee
            for transaction in block.transactions
            if not is_mining_reward_transaction(transaction)
        ),
        start=Decimal("0.0"),
    )
    return get_mining_reward_amount_validation_error(block, expected_total_fees)


def get_mining_reward_structure_error(block: Block) -> str | None:
    reward_transactions = [
        transaction
        for transaction in block.transactions
        if is_mining_reward_transaction(transaction)
    ]

    if block.block_id == 0:
        if reward_transactions:
            return "genesis block must not contain a mining reward transaction"
        return None

    if len(reward_transactions) != 1:
        if not reward_transactions:
            return "non-genesis block must contain exactly one mining reward transaction"
        return "block contains multiple mining reward transactions"

    reward_transaction = reward_transactions[0]
    if block.transactions[0] != reward_transaction:
        return "mining reward transaction must be the first transaction in the block"
    if reward_transaction.fee != Decimal("0.0"):
        return "mining reward transaction fee must be 0.0"
    if not reward_transaction.receiver:
        return "mining reward transaction receiver is empty"

    return None


def get_mining_reward_amount_validation_error(
    block: Block,
    total_fees: Decimal,
) -> str | None:
    if block.block_id == 0:
        return None

    reward_transaction = next(
        transaction
        for transaction in block.transactions
        if is_mining_reward_transaction(transaction)
    )
    expected_reward_amount = MINING_REWARD_AMOUNT + total_fees
    if reward_transaction.amount != expected_reward_amount:
        return (
            f"mining reward amount {reward_transaction.amount} does not match "
            f"expected reward {expected_reward_amount}"
        )
    return None
