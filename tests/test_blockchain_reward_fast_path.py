import unittest
from unittest import mock

from core.block import Block
from core.blockchain import Blockchain
from core.blockchain import ChainState
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.utils.constants import MINING_REWARD_AMOUNT
from core.utils.mining import create_mining_reward_transaction


class BlockchainRewardFastPathTests(unittest.TestCase):
    def test_reward_only_block_does_not_deepcopy_full_state(self) -> None:
        blockchain = Blockchain(
            difficulty_bits=0,
            hash_function=sha256_block_hash,
            genesis_difficulty_bits=0,
        )
        blockchain.add_block(create_genesis_block(sha256_block_hash))
        reward_transaction = create_mining_reward_transaction("miner")
        block = Block(
            block_id=1,
            transactions=[reward_transaction],
            hash_function=sha256_block_hash,
            description="reward only",
            previous_hash=blockchain.main_tip_hash,
        )

        with mock.patch.object(
            ChainState,
            "copy",
            side_effect=AssertionError("reward-only blocks should avoid full state copy"),
        ):
            self.assertTrue(blockchain.add_block(block))

        self.assertEqual(blockchain.get_balance("miner"), MINING_REWARD_AMOUNT)
        self.assertTrue(blockchain.verify_chain())

    def test_reward_only_fast_path_keeps_signature_validation(self) -> None:
        blockchain = Blockchain(
            difficulty_bits=0,
            hash_function=sha256_block_hash,
            genesis_difficulty_bits=0,
        )
        blockchain.add_block(create_genesis_block(sha256_block_hash))
        reward_transaction = create_mining_reward_transaction("miner")
        reward_transaction.sender_public_key = (3, 33)
        reward_transaction.signature = "invalid"
        block = Block(
            block_id=1,
            transactions=[reward_transaction],
            hash_function=sha256_block_hash,
            description="bad reward",
            previous_hash=blockchain.main_tip_hash,
        )

        self.assertFalse(blockchain.add_block(block))
        self.assertNotIn(block.block_hash, blockchain.blocks_by_hash)


if __name__ == "__main__":
    unittest.main()
