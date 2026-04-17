import asyncio
import contextlib
import os
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


@mock.patch.dict(os.environ, {"UNCCOIN_DISABLE_MINING_AUTOTUNE": "1"}, clear=False)
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


@mock.patch.dict(os.environ, {"UNCCOIN_DISABLE_MINING_AUTOTUNE": "1"}, clear=False)
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

    async def test_private_automine_loop_reconciles_pending_transactions_for_private_tip(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="private-autominer")
        node = Node(
            host="127.0.0.1",
            port=9003,
            wallet=wallet,
            blockchain=blockchain,
            private_automine=True,
        )
        node.automine_description = "private automine"

        original_mine_pending_transactions = blockchain.mine_pending_transactions
        original_reconcile_pending_transactions = blockchain.reconcile_pending_transactions
        mined_call_kwargs: dict | None = None
        reconcile_calls: list[tuple[str | None, str | None]] = []

        def mining_wrapper(*args, **kwargs):
            nonlocal mined_call_kwargs
            mined_call_kwargs = dict(kwargs)
            block = original_mine_pending_transactions(*args, **kwargs)
            node._automine_stop_requested = True
            return block

        def reconcile_wrapper(previous_head: str | None, current_head: str | None = None) -> None:
            reconcile_calls.append((previous_head, current_head))
            original_reconcile_pending_transactions(previous_head, current_head)

        with mock.patch.object(
            blockchain,
            "mine_pending_transactions",
            side_effect=mining_wrapper,
        ):
            with mock.patch.object(
                blockchain,
                "reconcile_pending_transactions",
                side_effect=reconcile_wrapper,
            ):
                with mock.patch.object(node, "broadcast_block", new=mock.AsyncMock()):
                    with mock.patch.object(node, "_maybe_schedule_autosend"):
                        with mock.patch("builtins.print"):
                            await node._automine_loop()

        self.assertIsNotNone(mined_call_kwargs)
        assert mined_call_kwargs is not None
        self.assertFalse(mined_call_kwargs["reconcile_pending_transactions"])
        self.assertEqual(mined_call_kwargs["tip_hash"], blockchain.blocks[0].block_hash)
        self.assertEqual(
            reconcile_calls,
            [(blockchain.blocks[0].block_hash, node._private_automine_tip_hash)],
        )
        self.assertIsNotNone(node._private_automine_tip_hash)


class NodeStartupStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_prints_available_gpu_count(self) -> None:
        node = Node(host="127.0.0.1", port=9010)

        with mock.patch.object(node, "_load_persisted_aliases"):
            with mock.patch.object(node, "_load_persisted_messages"):
                with mock.patch.object(node, "_load_persisted_blockchain"):
                    with mock.patch.object(node, "_ensure_genesis_block"):
                        with mock.patch.object(node, "_reset_autosend_balance_baseline"):
                            with mock.patch.object(node.p2p_server, "start", new=mock.AsyncMock()):
                                with mock.patch("node.node.gpu_device_ids", return_value=(0, 1, 2, 3)):
                                    with mock.patch("builtins.print") as print_mock:
                                        await node.start()

        print_mock.assert_any_call(
            "GPU devices available: 4 (ids: 0, 1, 2, 3)",
            flush=True,
        )
