import asyncio
import contextlib
import unittest
from datetime import datetime
from decimal import Decimal
from unittest import mock

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.transaction import Transaction
from node.node import Node
from wallet import create_wallet


def create_blockchain(*, difficulty_bits: int = 0) -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=difficulty_bits,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    return blockchain


class BlockchainPrivateTipMiningTests(unittest.TestCase):
    def test_mines_from_explicit_non_canonical_tip(self) -> None:
        blockchain = create_blockchain()

        canonical_block = blockchain.mine_pending_transactions(
            miner_address="miner-a",
            description="canonical #1",
        )
        canonical_tip = blockchain.mine_pending_transactions(
            miner_address="miner-a",
            description="canonical #2",
        )

        private_block = blockchain.mine_pending_transactions(
            miner_address="miner-b",
            description="private #1",
            tip_hash=canonical_block.block_hash,
        )

        self.assertEqual(private_block.previous_hash, canonical_block.block_hash)
        self.assertEqual(private_block.block_id, canonical_tip.block_id)
        self.assertEqual(blockchain.main_tip_hash, canonical_tip.block_hash)

        private_tip = blockchain.mine_pending_transactions(
            miner_address="miner-b",
            description="private #2",
            tip_hash=private_block.block_hash,
        )

        self.assertEqual(private_tip.previous_hash, private_block.block_hash)
        self.assertEqual(blockchain.main_tip_hash, private_tip.block_hash)


class NodePrivateAutomineTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_automine_only_cancels_for_same_branch_extension(self) -> None:
        blockchain = create_blockchain()
        node = Node(
            host="127.0.0.1",
            port=9000,
            blockchain=blockchain,
            private_automine=True,
        )

        base_block = blockchain.mine_pending_transactions(
            miner_address="miner-a",
            description="base",
        )
        node._private_automine_tip_hash = base_block.block_hash
        node._current_automine_tip_hash = base_block.block_hash
        node.automine_task = asyncio.create_task(asyncio.sleep(60))

        try:
            genesis_hash = blockchain.blocks[0].block_hash
            competing_block = blockchain.mine_pending_transactions(
                miner_address="miner-b",
                description="competing",
                tip_hash=genesis_hash,
            )

            with mock.patch("node.node.request_pow_cancel") as request_cancel:
                node._handle_accepted_block_for_automine(competing_block)
                request_cancel.assert_not_called()

            self.assertEqual(node._private_automine_tip_hash, base_block.block_hash)

            same_branch_block = blockchain.mine_pending_transactions(
                miner_address="miner-c",
                description="same branch",
                tip_hash=base_block.block_hash,
            )

            with mock.patch("node.node.request_pow_cancel") as request_cancel:
                node._handle_accepted_block_for_automine(same_branch_block)
                request_cancel.assert_called_once()

            self.assertEqual(node._private_automine_tip_hash, same_branch_block.block_hash)
        finally:
            node.automine_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await node.automine_task

    async def test_private_mode_uses_private_tip_for_balance_and_transaction_validation(self) -> None:
        blockchain = create_blockchain()
        canonical_tip = blockchain.mine_pending_transactions(
            miner_address="canonical-miner",
            description="canonical #1",
        )
        blockchain.mine_pending_transactions(
            miner_address="canonical-miner",
            description="canonical #2",
        )

        private_wallet = create_wallet(name="private-miner")
        receiver_wallet = create_wallet(name="receiver")
        private_block = blockchain.mine_pending_transactions(
            miner_address=private_wallet.address,
            description="private #1",
            tip_hash=canonical_tip.block_hash,
        )

        private_node = Node(
            host="127.0.0.1",
            port=9001,
            wallet=private_wallet,
            blockchain=blockchain,
            private_automine=True,
        )
        private_node._private_automine_tip_hash = private_block.block_hash

        self.assertEqual(private_node.get_balance(private_wallet.address), "10.0")
        self.assertEqual(private_node.get_next_nonce(private_wallet.address), 0)

        private_transaction = private_node.create_signed_transaction(
            receiver=receiver_wallet.address,
            amount="5",
            fee="0",
        )
        accepted, reason = private_node._handle_incoming_transaction(private_transaction)
        self.assertTrue(accepted, reason)
        self.assertEqual(private_node.get_next_nonce(private_wallet.address), 1)

        normal_blockchain = create_blockchain()
        normal_canonical_tip = normal_blockchain.mine_pending_transactions(
            miner_address="canonical-miner",
            description="canonical #1",
        )
        normal_blockchain.mine_pending_transactions(
            miner_address="canonical-miner",
            description="canonical #2",
        )
        normal_blockchain.mine_pending_transactions(
            miner_address=private_wallet.address,
            description="private #1",
            tip_hash=normal_canonical_tip.block_hash,
        )

        normal_node = Node(
            host="127.0.0.1",
            port=9002,
            wallet=private_wallet,
            blockchain=normal_blockchain,
            private_automine=False,
        )
        rejected_transaction = Transaction(
            sender=private_wallet.address,
            receiver=receiver_wallet.address,
            amount=Decimal("1"),
            fee=Decimal("0"),
            timestamp=datetime.now(),
            nonce=0,
            sender_public_key=private_wallet.public_key,
        )
        rejected_transaction.signature = private_wallet.sign_message(
            rejected_transaction.signing_payload()
        )
        accepted, reason = normal_node._handle_incoming_transaction(rejected_transaction)
        self.assertFalse(accepted)
        self.assertIsNotNone(reason)
