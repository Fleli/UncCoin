from typing import Callable

from core.block import Block
from core.utils.constants import GENESIS_BLOCK_ID
from core.utils.constants import GENESIS_DESCRIPTION
from core.utils.constants import GENESIS_HASH
from core.utils.constants import GENESIS_NONCE
from core.utils.constants import GENESIS_PREVIOUS_HASH


def create_genesis_block(hash_function: Callable[[Block], str]) -> Block:
    block = Block(
        block_id=GENESIS_BLOCK_ID,
        transactions=[],
        hash_function=hash_function,
        description=GENESIS_DESCRIPTION,
        previous_hash=GENESIS_PREVIOUS_HASH,
    )
    block.nonce = GENESIS_NONCE
    block.block_hash = hash_function(block)
    if block.block_hash != GENESIS_HASH:
        raise ValueError("Configured genesis block constants do not match the hash function.")
    return block


def get_genesis_block_validation_error(block: Block) -> str | None:
    if block.block_id != GENESIS_BLOCK_ID:
        return f"genesis block must have block_id {GENESIS_BLOCK_ID}, got {block.block_id}"
    if block.transactions:
        return "genesis block must not contain transactions"
    if block.description != GENESIS_DESCRIPTION:
        return "genesis block description does not match the canonical genesis block"
    if block.previous_hash != GENESIS_PREVIOUS_HASH:
        return "genesis block previous hash does not match the canonical genesis block"
    if block.nonce != GENESIS_NONCE:
        return "genesis block nonce does not match the canonical genesis block"
    if block.hash_function(block) != GENESIS_HASH or block.block_hash != GENESIS_HASH:
        return "genesis block hash does not match the canonical genesis block"
    return None
