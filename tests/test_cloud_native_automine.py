import asyncio
import hashlib
import os
import queue
import threading
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

from core.block import proof_of_work
from core.block import PrefixProofOfWorkResult
from core.block import ProofOfWorkCancelled
from core.cloud_native_automine import CloudNativeAutomineConfig
from core.cloud_native_automine import CloudNativeDifficultySchedule
from core.cloud_native_automine import CloudNativeMiningPlan
from core.cloud_native_automine import RewardOnlyBlockTemplate
from core.cloud_native_automine import _build_cloud_native_mining_plan
from core.cloud_native_automine import _mine_serialized_block_prefix_with_plan
from core.cloud_native_automine import build_reward_only_block
from core.cloud_native_automine import mine_reward_only_blocks
from core.hashing import sha256_block_hash
from core.serialization import serialize_block_prefix
from core.serialization import serialize_transaction
from core.transaction import Transaction
from core.utils.constants import MINING_REWARD_AMOUNT
from core.utils.constants import MINING_REWARD_SENDER
from core.utils.mining import create_mining_reward_transaction
from node.node import CloudNativeAutomineStaleTip
from node.node import Node
from network.p2p_server import PeerAddress
from wallet import create_wallet


class CloudNativeAutomineConsensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._gpu_plan_patcher = mock.patch(
            "core.cloud_native_automine.cuda_pow.gpu_available",
            return_value=False,
        )
        self._gpu_plan_patcher.start()

    def tearDown(self) -> None:
        self._gpu_plan_patcher.stop()

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

    def test_reward_only_template_matches_consensus_serialization(self) -> None:
        wallet = create_wallet(name="cloud-native-template")
        timestamp = datetime(2026, 5, 11, 12, 30, 0)
        template = RewardOnlyBlockTemplate(
            miner_address=wallet.address,
            description="cloud native template",
        )
        reward_transaction = template.reward_transaction(timestamp)

        self.assertEqual(
            template.serialized_reward_transaction(timestamp),
            serialize_transaction(reward_transaction),
        )
        self.assertEqual(
            template.block_prefix(
                block_id=18,
                previous_hash="b" * 64,
                timestamp=timestamp,
            ),
            (
                f"18|{serialize_transaction(reward_transaction)}|"
                f"cloud native template|{'b' * 64}|"
            ),
        )

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

    def test_cloud_native_node_disables_per_block_broadcast_logs(self) -> None:
        node = Node(
            host="127.0.0.1",
            port=0,
            mining_only=True,
            cloud_native_automine=True,
        )

        self.assertFalse(node.p2p_server.log_block_broadcasts)
        self.assertTrue(node.p2p_server.skip_empty_block_broadcasts)

    def test_reward_only_worker_mines_serialized_prefix_then_hydrates_block(self) -> None:
        wallet = create_wallet(name="cloud-native-prefix")
        output_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        seen_prefixes: list[str] = []

        def fake_mine_prefix(
            prefix: str,
            difficulty_bits: int,
            start_nonce: int = 0,
            mining_backend: str = "auto",
        ):
            del difficulty_bits, start_nonce, mining_backend
            seen_prefixes.append(prefix)
            if len(seen_prefixes) > 1:
                raise ProofOfWorkCancelled("stop")
            return PrefixProofOfWorkResult(
                nonce=7,
                block_hash=hashlib.sha256(f"{prefix}7".encode("utf-8")).hexdigest(),
                attempts=8,
            )

        with mock.patch(
            "core.cloud_native_automine.mine_serialized_block_prefix_resident",
            side_effect=fake_mine_prefix,
        ):
            mine_reward_only_blocks(
                CloudNativeAutomineConfig(
                    miner_address=wallet.address,
                    description="cloud native prefix",
                    start_tip_hash="a" * 64,
                    start_height=10,
                    difficulty_schedule=CloudNativeDifficultySchedule(
                        difficulty_bits=0,
                        genesis_difficulty_bits=0,
                        difficulty_growth_factor=10,
                        difficulty_growth_start_height=100,
                        difficulty_growth_bits=1,
                        difficulty_schedule_activation_height=0,
                    ),
                    mining_backend="gpu",
                ),
                output_queue,
                stop_event,
            )

        block_event = output_queue.get_nowait()
        self.assertEqual(block_event.kind, "block")
        self.assertIsNotNone(block_event.block)
        self.assertEqual(serialize_block_prefix(block_event.block), seen_prefixes[0])
        self.assertEqual(block_event.block.nonce, 7)
        self.assertEqual(block_event.block.nonces_checked, 8)
        self.assertEqual(block_event.block.block_hash, sha256_block_hash(block_event.block))
        self.assertEqual(output_queue.get_nowait().kind, "cancelled")

    def test_reward_only_worker_can_batch_mined_blocks(self) -> None:
        wallet = create_wallet(name="cloud-native-prefix-batch")
        output_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        seen_prefixes: list[str] = []

        def fake_mine_prefix(
            prefix: str,
            difficulty_bits: int,
            start_nonce: int = 0,
            mining_backend: str = "auto",
        ):
            del difficulty_bits, start_nonce, mining_backend
            seen_prefixes.append(prefix)
            if len(seen_prefixes) > 2:
                raise ProofOfWorkCancelled("stop")
            nonce = len(seen_prefixes)
            return PrefixProofOfWorkResult(
                nonce=nonce,
                block_hash=hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).hexdigest(),
                attempts=nonce + 1,
            )

        with mock.patch(
            "core.cloud_native_automine.mine_serialized_block_prefix_resident",
            side_effect=fake_mine_prefix,
        ):
            mine_reward_only_blocks(
                CloudNativeAutomineConfig(
                    miner_address=wallet.address,
                    description="cloud native prefix batch",
                    start_tip_hash="a" * 64,
                    start_height=10,
                    difficulty_schedule=CloudNativeDifficultySchedule(
                        difficulty_bits=0,
                        genesis_difficulty_bits=0,
                        difficulty_growth_factor=10,
                        difficulty_growth_start_height=100,
                        difficulty_growth_bits=1,
                        difficulty_schedule_activation_height=0,
                    ),
                    mining_backend="gpu",
                    batch_blocks=2,
                ),
                output_queue,
                stop_event,
            )

        batch_event = output_queue.get_nowait()
        self.assertEqual(batch_event.kind, "blocks")
        self.assertEqual(len(batch_event.blocks), 2)
        self.assertEqual(batch_event.blocks[0].block_id, 11)
        self.assertEqual(batch_event.blocks[1].block_id, 12)
        self.assertEqual(batch_event.blocks[1].previous_hash, batch_event.blocks[0].block_hash)
        self.assertEqual(output_queue.get_nowait().kind, "cancelled")

    def test_reward_only_worker_uses_configured_start_nonce(self) -> None:
        wallet = create_wallet(name="cloud-native-start-nonce")
        output_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        seen_start_nonces: list[int] = []

        def fake_mine_prefix(
            prefix: str,
            difficulty_bits: int,
            start_nonce: int = 0,
            mining_backend: str = "auto",
        ):
            del difficulty_bits, mining_backend
            seen_start_nonces.append(start_nonce)
            if len(seen_start_nonces) > 1:
                raise ProofOfWorkCancelled("stop")
            nonce = start_nonce + 7
            return PrefixProofOfWorkResult(
                nonce=nonce,
                block_hash=hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).hexdigest(),
                attempts=8,
            )

        with mock.patch(
            "core.cloud_native_automine.mine_serialized_block_prefix_resident",
            side_effect=fake_mine_prefix,
        ):
            mine_reward_only_blocks(
                CloudNativeAutomineConfig(
                    miner_address=wallet.address,
                    description="cloud native start nonce",
                    start_tip_hash="a" * 64,
                    start_height=10,
                    difficulty_schedule=CloudNativeDifficultySchedule(
                        difficulty_bits=0,
                        genesis_difficulty_bits=0,
                        difficulty_growth_factor=10,
                        difficulty_growth_start_height=100,
                        difficulty_growth_bits=1,
                        difficulty_schedule_activation_height=0,
                    ),
                    mining_backend="gpu",
                    start_nonce=100_000_000,
                ),
                output_queue,
                stop_event,
            )

        block_event = output_queue.get_nowait()
        self.assertEqual(block_event.kind, "block")
        self.assertEqual(block_event.block.nonce, 100_000_007)
        self.assertEqual(seen_start_nonces[0], 100_000_000)

    def test_cloud_native_gpu_plan_resolves_launch_settings_once(self) -> None:
        with mock.patch(
            "core.cloud_native_automine.cuda_pow.gpu_available",
            return_value=True,
        ) as gpu_available:
            with mock.patch(
                "core.cloud_native_automine.get_gpu_device_ids",
                return_value=(0,),
            ) as gpu_device_ids:
                with mock.patch(
                    "core.cloud_native_automine.get_tuned_gpu_launch_config",
                    return_value=(16, 256),
                ) as launch_config:
                    with mock.patch(
                        "core.cloud_native_automine.get_tuned_gpu_chunk_multiplier",
                        return_value=64,
                    ) as chunk_multiplier:
                        with mock.patch.dict(os.environ, {}, clear=True):
                            plan = _build_cloud_native_mining_plan("gpu")

        self.assertTrue(plan.gpu_enabled)
        self.assertEqual(plan.device_id, 0)
        self.assertEqual(plan.dispatch_batch_size, 262_144 * 64)
        self.assertEqual(plan.nonces_per_thread, 16)
        self.assertEqual(plan.threads_per_group, 256)
        gpu_available.assert_called_once()
        gpu_device_ids.assert_called_once()
        launch_config.assert_called_once_with(262_144, 0)
        chunk_multiplier.assert_called_once_with(262_144, 16, 256, 0)

    def test_cloud_native_gpu_plan_mines_without_resolving_backend_each_block(self) -> None:
        plan = CloudNativeMiningPlan(
            gpu_enabled=True,
            device_id=0,
            dispatch_batch_size=12345,
            nonces_per_thread=16,
            threads_per_group=256,
        )

        with mock.patch(
            "core.cloud_native_automine.cuda_pow.mine_pow_gpu",
            return_value=(107, "0" * 64, False),
        ) as mine_pow_gpu:
            with mock.patch(
                "core.cloud_native_automine.mine_serialized_block_prefix_resident",
                side_effect=AssertionError("generic backend should not be used"),
            ):
                result = _mine_serialized_block_prefix_with_plan(
                    "prefix|",
                    30,
                    start_nonce=100,
                    mining_backend="gpu",
                    mining_plan=plan,
                )

        self.assertEqual(result.nonce, 107)
        self.assertEqual(result.block_hash, "0" * 64)
        self.assertEqual(result.attempts, 8)
        mine_pow_gpu.assert_called_once_with(
            "prefix|",
            30,
            100,
            0,
            12345,
            1,
            16,
            256,
            0,
        )

    def test_reward_only_worker_flushes_partial_batch_on_cancel(self) -> None:
        wallet = create_wallet(name="cloud-native-partial-flush")
        output_queue: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        mined_prefixes = 0

        def fake_mine_prefix(
            prefix: str,
            difficulty_bits: int,
            start_nonce: int = 0,
            mining_backend: str = "auto",
        ):
            nonlocal mined_prefixes
            del difficulty_bits, start_nonce, mining_backend
            mined_prefixes += 1
            if mined_prefixes > 3:
                raise ProofOfWorkCancelled("stop")
            nonce = mined_prefixes
            return PrefixProofOfWorkResult(
                nonce=nonce,
                block_hash=hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).hexdigest(),
                attempts=nonce + 1,
            )

        with mock.patch(
            "core.cloud_native_automine.mine_serialized_block_prefix_resident",
            side_effect=fake_mine_prefix,
        ):
            mine_reward_only_blocks(
                CloudNativeAutomineConfig(
                    miner_address=wallet.address,
                    description="cloud native partial flush",
                    start_tip_hash="a" * 64,
                    start_height=10,
                    difficulty_schedule=CloudNativeDifficultySchedule(
                        difficulty_bits=0,
                        genesis_difficulty_bits=0,
                        difficulty_growth_factor=10,
                        difficulty_growth_start_height=100,
                        difficulty_growth_bits=1,
                        difficulty_schedule_activation_height=0,
                    ),
                    mining_backend="gpu",
                    batch_blocks=10,
                ),
                output_queue,
                stop_event,
            )

        batch_event = output_queue.get_nowait()
        self.assertEqual(batch_event.kind, "blocks")
        self.assertEqual(len(batch_event.blocks), 3)
        self.assertEqual(batch_event.blocks[0].block_id, 11)
        self.assertEqual(batch_event.blocks[-1].block_id, 13)
        self.assertEqual(output_queue.get_nowait().kind, "cancelled")


class CloudNativeAutomineNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_native_automine_accepts_only_consensus_valid_blocks(self) -> None:
        wallet = create_wallet(name="cloud-native-invalid")
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
            mined_block_persist_interval=0,
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

    async def test_cloud_native_fast_path_updates_reward_state_without_generic_add(self) -> None:
        wallet = create_wallet(name="cloud-native-fast")
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
        node._ensure_genesis_block()
        block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")

        with mock.patch.object(node.blockchain, "add_block_result") as add_block_result:
            await node._accept_cloud_native_mined_block(block)

        add_block_result.assert_not_called()
        self.assertEqual(node.blockchain.main_tip_hash, block.block_hash)
        genesis_state = node.blockchain.block_states[block.previous_hash]
        child_state = node.blockchain.block_states[block.block_hash]
        self.assertIsNot(child_state.balances, genesis_state.balances)
        self.assertIs(child_state.nonces, genesis_state.nonces)
        self.assertIs(child_state.contracts, genesis_state.contracts)
        self.assertEqual(
            node.blockchain.get_balance(wallet.address),
            MINING_REWARD_AMOUNT,
        )
        self.assertTrue(node.blockchain.verify_chain())

    async def test_cloud_native_batch_fast_path_updates_once(self) -> None:
        wallet = create_wallet(name="cloud-native-fast-batch")
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
        node._ensure_genesis_block()
        first_block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native batch 1",
        )
        proof_of_work(first_block, difficulty_bits=0, mining_backend="python")
        second_block = build_reward_only_block(
            block_id=2,
            previous_hash=first_block.block_hash,
            miner_address=wallet.address,
            description="fast cloud native batch 2",
        )
        proof_of_work(second_block, difficulty_bits=0, mining_backend="python")

        with mock.patch.object(node.blockchain, "add_block_result") as add_block_result:
            with mock.patch.object(node, "_maybe_schedule_autosend") as autosend:
                accepted = await node._accept_cloud_native_mined_blocks(
                    (first_block, second_block),
                )

        self.assertEqual(accepted, (first_block, second_block))
        add_block_result.assert_not_called()
        autosend.assert_called_once()
        self.assertEqual(node.blockchain.main_tip_hash, second_block.block_hash)
        self.assertEqual(
            node.blockchain.get_balance(wallet.address),
            MINING_REWARD_AMOUNT * 2,
        )
        self.assertEqual(node._mined_blocks_since_persist, 2)
        self.assertTrue(node.blockchain.verify_chain())

    def test_autosend_off_does_not_recompute_balance(self) -> None:
        wallet = create_wallet(name="cloud-native-autosend-off")
        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            mining_only=True,
            cloud_native_automine=True,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )

        with mock.patch.object(node, "_reset_autosend_balance_baseline") as reset_baseline:
            node._maybe_schedule_autosend()

        reset_baseline.assert_not_called()

    def test_cloud_native_summary_waits_for_configured_block_interval(self) -> None:
        node = Node(
            host="127.0.0.1",
            port=0,
            mining_only=True,
            cloud_native_automine=True,
        )
        block = mock.Mock(block_id=123)

        with mock.patch.dict(
            os.environ,
            {"UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS": "250"},
            clear=True,
        ):
            with mock.patch("node.node.time.perf_counter", return_value=30.0):
                with mock.patch("builtins.print") as print_mock:
                    last_summary_at, last_summary_accepted = (
                        node._maybe_print_cloud_native_summary(
                            block=block,
                            accepted_blocks=50,
                            stale_restarts=0,
                            started_at=0.0,
                            last_summary_at=0.0,
                            last_summary_accepted=0,
                        )
                    )

        print_mock.assert_not_called()
        self.assertEqual(last_summary_at, 0.0)
        self.assertEqual(last_summary_accepted, 0)

    def test_cloud_native_summary_prints_recent_rate(self) -> None:
        node = Node(
            host="127.0.0.1",
            port=0,
            mining_only=True,
            cloud_native_automine=True,
        )
        block = mock.Mock(block_id=456)

        with mock.patch.dict(
            os.environ,
            {"UNCCOIN_CLOUD_NATIVE_SUMMARY_BLOCKS": "250"},
            clear=True,
        ):
            with mock.patch("node.node.time.perf_counter", return_value=75.0):
                with mock.patch("builtins.print") as print_mock:
                    last_summary_at, last_summary_accepted = (
                        node._maybe_print_cloud_native_summary(
                            block=block,
                            accepted_blocks=250,
                            stale_restarts=0,
                            started_at=0.0,
                            last_summary_at=0.0,
                            last_summary_accepted=0,
                        )
                    )

        print_mock.assert_called_once()
        printed = print_mock.call_args.args[0]
        self.assertIn("accepted=250", printed)
        self.assertIn("rate=200.0/min", printed)
        self.assertIn("recent=200.0/min", printed)
        self.assertEqual(last_summary_at, 75.0)
        self.assertEqual(last_summary_accepted, 250)

    async def test_cloud_native_fast_path_runs_periodic_full_verify_before_broadcast(self) -> None:
        wallet = create_wallet(name="cloud-native-fast-verify")
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
        node._ensure_genesis_block()
        block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native verify",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")

        with mock.patch.dict(os.environ, {"UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS": "1"}):
            with mock.patch.object(node.blockchain, "verify_chain", return_value=True) as verify_chain:
                await node._accept_cloud_native_mined_block(block)

        verify_chain.assert_called_once()

    async def test_cloud_native_fast_path_can_disable_periodic_full_verify(self) -> None:
        wallet = create_wallet(name="cloud-native-fast-no-verify")
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
        node._ensure_genesis_block()
        block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native no verify",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")

        with mock.patch.dict(os.environ, {"UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS": "0"}):
            with mock.patch.object(node.blockchain, "verify_chain") as verify_chain:
                await node._accept_cloud_native_mined_block(block)

        verify_chain.assert_not_called()
        self.assertEqual(node._cloud_native_fast_blocks_since_verify, 1)

    async def test_cloud_native_offline_trusts_worker_hash_when_enabled(self) -> None:
        wallet = create_wallet(name="cloud-native-trust-worker-hash")
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
        node._ensure_genesis_block()
        block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native trust worker hash",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")

        with mock.patch.dict(
            os.environ,
            {"UNCCOIN_CLOUD_NATIVE_TRUST_WORKER_HASH": "1"},
        ):
            with mock.patch(
                "node.node.get_block_verification_error",
                side_effect=AssertionError("duplicate hash check should be skipped"),
            ):
                await node._accept_cloud_native_mined_block(block)

        self.assertEqual(node.blockchain.main_tip_hash, block.block_hash)
        self.assertTrue(node.blockchain.verify_chain())

    async def test_cloud_native_rechecks_worker_hash_before_broadcast(self) -> None:
        wallet = create_wallet(name="cloud-native-trust-worker-hash-peer")
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
        node._ensure_genesis_block()
        block = build_reward_only_block(
            block_id=1,
            previous_hash=node.blockchain.main_tip_hash,
            miner_address=wallet.address,
            description="fast cloud native trust worker hash peer",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")
        node.p2p_server.active_connections[PeerAddress("127.0.0.1", 9000)] = mock.Mock()

        with mock.patch.dict(
            os.environ,
            {"UNCCOIN_CLOUD_NATIVE_TRUST_WORKER_HASH": "1"},
        ):
            with mock.patch(
                "node.node.get_block_verification_error",
                return_value="forced hash mismatch",
            ) as verify_block_hash:
                with self.assertRaisesRegex(ValueError, "forced hash mismatch"):
                    await node._accept_cloud_native_mined_block(block)

        verify_block_hash.assert_called_once()

    async def test_cloud_native_connect_verifies_pending_fast_blocks(self) -> None:
        node = Node(
            host="127.0.0.1",
            port=0,
            mining_only=True,
            cloud_native_automine=True,
        )
        node._cloud_native_fast_blocks_since_verify = 3

        with mock.patch.object(node.blockchain, "verify_chain", return_value=True) as verify_chain:
            with mock.patch.object(node.p2p_server, "connect_to_peer", new=mock.AsyncMock()) as connect_to_peer:
                await node.connect_to_peer("127.0.0.1", 9000)

        verify_chain.assert_called_once()
        connect_to_peer.assert_awaited_once_with("127.0.0.1", 9000)
        self.assertEqual(node._cloud_native_fast_blocks_since_verify, 0)

    async def test_cloud_native_skips_empty_block_broadcast_work(self) -> None:
        wallet = create_wallet(name="cloud-native-empty-broadcast")
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
        block = build_reward_only_block(
            block_id=1,
            previous_hash="a" * 64,
            miner_address=wallet.address,
            description="empty broadcast",
        )

        with mock.patch.object(block, "to_dict", side_effect=AssertionError):
            await node.broadcast_block(block)

        self.assertNotIn(block.block_hash, node.p2p_server.seen_block_hashes)

    async def test_cloud_native_fast_path_rolls_back_when_full_verify_fails(self) -> None:
        wallet = create_wallet(name="cloud-native-fast-rollback")
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
        node._ensure_genesis_block()
        genesis_hash = node.blockchain.main_tip_hash
        block = build_reward_only_block(
            block_id=1,
            previous_hash=genesis_hash,
            miner_address=wallet.address,
            description="fast cloud native rollback",
        )
        proof_of_work(block, difficulty_bits=0, mining_backend="python")

        with mock.patch.dict(os.environ, {"UNCCOIN_CLOUD_NATIVE_FULL_VERIFY_BLOCKS": "1"}):
            with mock.patch.object(node.blockchain, "verify_chain", return_value=False):
                with self.assertRaisesRegex(ValueError, "full chain verification failed"):
                    await node._accept_cloud_native_mined_block(block)

        self.assertNotIn(block.block_hash, node.blockchain.blocks_by_hash)
        self.assertEqual(node.blockchain.main_tip_hash, genesis_hash)
        self.assertEqual(node._cloud_native_fast_blocks_since_verify, 0)

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
