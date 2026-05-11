import asyncio
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

from core.block import proof_of_work
from core.cloud_native_automine import CloudNativeDifficultySchedule
from core.cloud_native_automine import build_reward_only_block
from core.hashing import sha256_block_hash
from core.serialization import serialize_block_prefix
from core.serialization import serialize_transaction
from core.transaction import Transaction
from core.utils.constants import MINING_REWARD_SENDER
from core.utils.mining import create_mining_reward_transaction
from node.node import CloudNativeAutomineStaleTip
from node.node import Node
from wallet import create_wallet


class CloudNativeAutomineConsensusTests(unittest.TestCase):
    def test_reward_only_block_uses_existing_consensus_serialization(self) -> None:
        wallet = create_wallet(name="cloud-native-serialization")
        timestamp = datetime(2026, 5, 11, 12, 30, 0)
        block = build_reward_only_block(
            block_id=17,
            previous_hash="a" * 64,
            miner_address=wallet.address,
            description="cloud native",
            timestamp=timestamp,
        )
        expected_reward = create_mining_reward_transaction(
            wallet.address,
            timestamp=timestamp,
        )

        self.assertEqual(block.transactions, [expected_reward])
        self.assertEqual(
            serialize_block_prefix(block),
            (
                f"17|{serialize_transaction(expected_reward)}|"
                f"cloud native|{'a' * 64}|"
            ),
        )
        self.assertEqual(block.block_hash, sha256_block_hash(block))

    def test_cloud_native_difficulty_schedule_matches_blockchain(self) -> None:
        node = Node(
            host="127.0.0.1",
            port=0,
            mining_only=True,
            cloud_native_automine=True,
            difficulty_bits=7,
            genesis_difficulty_bits=2,
            difficulty_growth_factor=3,
            difficulty_growth_start_height=5,
            difficulty_growth_bits=2,
        )
        schedule = CloudNativeDifficultySchedule(
            difficulty_bits=node.blockchain.difficulty_bits,
            genesis_difficulty_bits=node.blockchain.genesis_difficulty_bits,
            difficulty_growth_factor=node.blockchain.difficulty_growth_factor,
            difficulty_growth_start_height=node.blockchain.difficulty_growth_start_height,
            difficulty_growth_bits=node.blockchain.difficulty_growth_bits,
            difficulty_schedule_activation_height=(
                node.blockchain.difficulty_schedule_activation_height
            ),
        )

        for height in range(0, 40):
            self.assertEqual(
                schedule.difficulty_bits_for_height(height),
                node.blockchain.get_difficulty_bits_for_height(height),
            )

    def test_cloud_native_mode_requires_mining_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires mining_only"):
            Node(
                host="127.0.0.1",
                port=0,
                cloud_native_automine=True,
            )


class CloudNativeAutomineNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_native_automine_accepts_only_consensus_valid_blocks(self) -> None:
        wallet = create_wallet(name="cloud-native-invalid")
        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            mining_only=True,
            cloud_native_automine=True,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )
        node._ensure_genesis_block()
        bad_reward = Transaction(
            sender=MINING_REWARD_SENDER,
            receiver=wallet.address,
            amount=Decimal("999.0"),
            fee=Decimal("0.0"),
            timestamp=datetime(2026, 5, 11, 12, 30, 0),
        )
        bad_block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="invalid cloud native",
        )
        bad_block.transactions = [bad_reward]
        proof_of_work(bad_block, difficulty_bits=0, mining_backend="python")

        with self.assertRaisesRegex(ValueError, "consensus validation"):
            await node._accept_cloud_native_mined_block(bad_block)

    async def test_cloud_native_automine_rejects_stale_tip(self) -> None:
        wallet = create_wallet(name="cloud-native-stale")
        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            mining_only=True,
            cloud_native_automine=True,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )
        node._ensure_genesis_block()
        stale_block = build_reward_only_block(
            block_id=1,
            previous_hash="b" * 64,
            miner_address=wallet.address,
            description="stale cloud native",
        )
        proof_of_work(stale_block, difficulty_bits=0, mining_backend="python")

        with self.assertRaises(CloudNativeAutomineStaleTip):
            await node._accept_cloud_native_mined_block(stale_block)

    async def test_cloud_native_automine_mines_valid_chain_until_stopped(self) -> None:
        wallet = create_wallet(name="cloud-native-runner")
        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            mining_only=True,
            cloud_native_automine=True,
            mined_block_persist_interval=0,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )
        node.mining_backend = "python"
        node._ensure_genesis_block()

        with mock.patch(
            "node.node.save_blockchain_state",
            return_value=Path("state/blockchains/test.json"),
        ) as save_state:
            await node.start_automine("cloud native test")
            deadline = asyncio.get_running_loop().time() + 2
            while node.blockchain.blocks[-1].block_id < 3:
                if asyncio.get_running_loop().time() >= deadline:
                    self.fail("cloud native automine did not mine enough blocks")
                await asyncio.sleep(0.01)
            await node.stop_automine(wait=True)

        self.assertGreaterEqual(node.blockchain.blocks[-1].block_id, 3)
        self.assertTrue(node.blockchain.verify_chain())
        save_state.assert_not_called()
        for block in node.blockchain.blocks[1:]:
            self.assertEqual(block.block_hash, sha256_block_hash(block))
            self.assertEqual(len(block.transactions), 1)
            self.assertEqual(block.transactions[0].sender, MINING_REWARD_SENDER)
            self.assertEqual(block.transactions[0].receiver, wallet.address)


if __name__ == "__main__":
    unittest.main()
