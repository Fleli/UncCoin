import json
import unittest
from pathlib import Path
from unittest import mock

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from node.node import Node
from network.p2p_server import FASTSYNC_INITIAL_BATCH_CHUNKS
from network.p2p_server import FastSyncState
from network.p2p_server import P2PServer
from network.p2p_server import PeerAddress
from wallet import create_wallet


def create_blockchain(*, block_count: int) -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    for index in range(block_count):
        blockchain.mine_pending_transactions(
            miner_address=f"miner-{index}",
            description=f"block-{index}",
        )
    return blockchain


class RecordingWriter:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def write(self, data: bytes) -> None:
        self.messages.append(json.loads(data.decode("utf-8").rstrip("\n")))

    async def drain(self) -> None:
        return


class P2PServerFastSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_chain_sync_default_uses_fastsync_stream_request(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9101)
        writer = object()
        server = P2PServer(
            host="127.0.0.1",
            port=9100,
            on_chain_summary=lambda: ("tip", 39),
        )
        server.active_connections[peer] = writer

        with mock.patch.object(P2PServer, "_send_message", new=mock.AsyncMock()) as send_message:
            peer_count = await server.request_chain_sync()

        self.assertEqual(peer_count, 1)
        self.assertEqual(
            send_message.await_args.args[1],
            {"type": "chain_stream_request", "start_height": 40},
        )
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 40)
        self.assertEqual(server.fast_sync_states[peer].batch_chunk_count, 1)

    async def test_request_chain_sync_fast_uses_stream_request(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9103)
        writer = object()
        server = P2PServer(
            host="127.0.0.1",
            port=9102,
            on_chain_summary=lambda: ("tip", 39),
        )
        server.active_connections[peer] = writer

        with mock.patch.object(P2PServer, "_send_message", new=mock.AsyncMock()) as send_message:
            peer_count = await server.request_chain_sync(fast=True)

        self.assertEqual(peer_count, 1)
        self.assertIn(peer, server.fast_sync_states)
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 40)
        self.assertEqual(server.fast_sync_states[peer].batch_chunk_count, 1)

        self.assertEqual(
            send_message.await_args.args[1],
            {"type": "chain_stream_request", "start_height": 40},
        )

    async def test_request_chain_sync_can_still_use_ordinary_sync_explicitly(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9102)
        server = P2PServer(
            host="127.0.0.1",
            port=9103,
            on_chain_summary=lambda: ("tip", 39),
        )
        server.active_connections[peer] = object()

        with mock.patch.object(P2PServer, "_send_message", new=mock.AsyncMock()) as send_message:
            peer_count = await server.request_chain_sync(fast=False)

        self.assertEqual(peer_count, 1)
        self.assertEqual(
            send_message.await_args.args[1],
            {"type": "chain_request", "start_height": 40},
        )

    async def test_request_chain_sync_skips_peer_with_active_fastsync(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9104)
        server = P2PServer(
            host="127.0.0.1",
            port=9105,
            on_chain_summary=lambda: ("tip", 39),
        )
        server.active_connections[peer] = object()
        server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=60,
            batch_end_start_height=1040,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )

        with mock.patch.object(server, "_request_fast_sync_stream", new=mock.AsyncMock()) as request_fast_sync_stream:
            peer_count = await server.request_chain_sync()

        self.assertEqual(peer_count, 1)
        request_fast_sync_stream.assert_not_awaited()

    async def test_chain_stream_request_sends_only_real_chunks_then_done(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9105)
        remote_blockchain = create_blockchain(block_count=45)
        writer = RecordingWriter()
        server = P2PServer(
            host="127.0.0.1",
            port=9104,
            on_chain_request=lambda: remote_blockchain.blocks,
        )
        server.active_connections[peer] = writer

        await server._handle_message(
            {"type": "chain_stream_request", "start_height": 1},
            peer,
        )

        self.assertEqual(
            [message["start_height"] for message in writer.messages],
            [1, 21, 41],
        )
        self.assertFalse(writer.messages[0]["done"])
        self.assertFalse(writer.messages[1]["done"])
        self.assertTrue(writer.messages[2]["done"])
        self.assertEqual(len(writer.messages[2]["blocks"]), 5)

    async def test_fastsync_processes_consecutive_chunks_until_done(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9106)
        processed_starts: list[int] = []
        completed_syncs: list[bool] = []
        blockchain = create_blockchain(block_count=45)
        server = P2PServer(
            host="127.0.0.1",
            port=9107,
            on_chain_response=lambda blocks: {
                "accepted": processed_starts.append(blocks[0].block_id) or len(blocks),
                "duplicates": 0,
                "orphans": 0,
                "rejected": 0,
            },
            on_chain_sync_complete=lambda: completed_syncs.append(True),
        )
        server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=1,
            batch_end_start_height=21,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )

        await server._handle_message(
            {
                "type": "chain_chunk",
                "start_height": 1,
                "height": 45,
                "done": False,
                "next_start_height": 21,
                "blocks": [blockchain.blocks[1].to_dict()],
            },
            peer,
        )
        await server._handle_message(
            {
                "type": "chain_chunk",
                "start_height": 21,
                "height": 45,
                "done": False,
                "next_start_height": 41,
                "blocks": [blockchain.blocks[21].to_dict()],
            },
            peer,
        )
        await server._handle_message(
            {
                "type": "chain_chunk",
                "start_height": 41,
                "height": 45,
                "done": True,
                "next_start_height": None,
                "blocks": [blockchain.blocks[41].to_dict()],
            },
            peer,
        )

        self.assertEqual(processed_starts, [1, 21, 41])
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 42)
        self.assertFalse(server.fast_sync_states[peer].active)
        self.assertEqual(completed_syncs, [True])

    async def test_fastsync_buffers_ahead_chunk_until_missing_chunk_arrives(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9107)
        processed_starts: list[int] = []
        blockchain = create_blockchain(block_count=45)
        server = P2PServer(
            host="127.0.0.1",
            port=9108,
            on_chain_response=lambda blocks: {
                "accepted": processed_starts.append(blocks[0].block_id) or len(blocks),
                "duplicates": 0,
                "orphans": 0,
                "rejected": 0,
            },
        )
        server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=1,
            batch_end_start_height=21,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )

        await server._handle_message(
            {
                "type": "chain_chunk",
                "start_height": 21,
                "height": 45,
                "done": False,
                "next_start_height": 41,
                "blocks": [blockchain.blocks[21].to_dict()],
            },
            peer,
        )
        self.assertEqual(processed_starts, [])

        await server._handle_message(
            {
                "type": "chain_chunk",
                "start_height": 1,
                "height": 45,
                "done": False,
                "next_start_height": 21,
                "blocks": [blockchain.blocks[1].to_dict()],
            },
            peer,
        )

        self.assertEqual(processed_starts, [1, 21])
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 41)
        self.assertTrue(server.fast_sync_states[peer].active)

    async def test_handshake_starts_initial_fastsync_stream(self) -> None:
        peer = PeerAddress(host="100.71.105.5", port=5000)
        original_peer = PeerAddress(host="100.71.105.5", port=51000)
        server = P2PServer(
            host="127.0.0.1",
            port=9108,
            on_chain_summary=lambda: ("tip", 4898),
        )
        server.active_connections[original_peer] = object()

        with mock.patch.object(server, "_request_fast_sync_stream", new=mock.AsyncMock()) as request_fast_sync_stream:
            returned_peer = await server._handle_message(
                {
                    "type": "handshake",
                    "host": "0.0.0.0",
                    "port": 5000,
                    "tip_hash": "abc",
                    "height": 30939,
                },
                original_peer,
            )

        self.assertEqual(returned_peer, peer)
        request_fast_sync_stream.assert_awaited_once_with(
            peer,
            4899,
        )

    async def test_transaction_relay_disabled_handshake_still_starts_fastsync(self) -> None:
        peer = PeerAddress(host="100.71.105.5", port=5000)
        original_peer = PeerAddress(host="100.71.105.5", port=51000)
        writer = RecordingWriter()
        server = P2PServer(
            host="127.0.0.1",
            port=9108,
            on_chain_summary=lambda: ("local-tip", 4898),
            transaction_relay=False,
        )
        server.active_connections[original_peer] = writer

        returned_peer = await server._handle_message(
            {
                "type": "handshake",
                "host": "0.0.0.0",
                "port": 5000,
                "tip_hash": "abc",
                "height": 30939,
            },
            original_peer,
        )

        self.assertEqual(returned_peer, peer)
        self.assertEqual(
            writer.messages,
            [{"type": "chain_stream_request", "start_height": 4899}],
        )
        self.assertIn(peer, server.fast_sync_states)
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 4899)

    async def test_handshake_moves_existing_fastsync_state_to_advertised_peer(self) -> None:
        peer = PeerAddress(host="100.71.105.5", port=5000)
        original_peer = PeerAddress(host="100.71.105.5", port=51000)
        server = P2PServer(
            host="127.0.0.1",
            port=9109,
            on_chain_summary=lambda: ("tip", 4898),
        )
        server.active_connections[original_peer] = object()
        server.fast_sync_states[original_peer] = FastSyncState(
            expected_start_height=5039,
            batch_end_start_height=6019,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )

        with mock.patch.object(server, "_request_fast_sync_stream", new=mock.AsyncMock()) as request_fast_sync_stream:
            returned_peer = await server._handle_message(
                {
                    "type": "handshake",
                    "host": "0.0.0.0",
                    "port": 5000,
                    "tip_hash": "abc",
                    "height": 30939,
                },
                original_peer,
            )

        self.assertEqual(returned_peer, peer)
        self.assertNotIn(original_peer, server.fast_sync_states)
        self.assertIn(peer, server.fast_sync_states)
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 5039)
        request_fast_sync_stream.assert_not_awaited()

    async def test_handshake_does_not_start_second_sync_during_active_fastsync(self) -> None:
        peer = PeerAddress(host="100.71.105.5", port=5000)
        original_peer = PeerAddress(host="100.71.105.5", port=51000)
        server = P2PServer(
            host="127.0.0.1",
            port=9108,
            on_chain_summary=lambda: ("tip", 4898),
        )
        server.active_connections[original_peer] = object()
        server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=4899,
            batch_end_start_height=5879,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )

        with mock.patch.object(server, "_request_fast_sync_stream", new=mock.AsyncMock()) as request_fast_sync_stream:
            returned_peer = await server._handle_message(
                {
                    "type": "handshake",
                    "host": "0.0.0.0",
                    "port": 5000,
                    "tip_hash": "abc",
                    "height": 30939,
                },
                original_peer,
            )

        self.assertEqual(returned_peer, peer)
        request_fast_sync_stream.assert_not_awaited()


class NodeFastSyncImportTests(unittest.TestCase):
    def test_handle_chain_response_reconciles_pending_transactions_once_per_chunk(self) -> None:
        source_chain = create_blockchain(block_count=3)
        dest_chain = Blockchain(
            difficulty_bits=0,
            hash_function=sha256_block_hash,
        )
        dest_chain.add_block(create_genesis_block(sha256_block_hash))
        node = Node(
            host="127.0.0.1",
            port=9200,
            blockchain=dest_chain,
        )

        imported_blocks = [
            source_chain.blocks[1],
            source_chain.blocks[2],
            source_chain.blocks[3],
        ]

        with mock.patch.object(
            dest_chain,
            "reconcile_pending_transactions",
            wraps=dest_chain.reconcile_pending_transactions,
        ) as reconcile_pending_transactions:
            result = node._handle_chain_response(imported_blocks)

        self.assertEqual(result["accepted"], 3)
        reconcile_pending_transactions.assert_called_once()

    def test_fastsync_defers_persistence_until_sync_completes(self) -> None:
        source_chain = create_blockchain(block_count=45)
        wallet = create_wallet(name="persisted-sync")
        node = Node(
            host="127.0.0.1",
            port=9201,
            wallet=wallet,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )
        node._ensure_genesis_block()
        peer = PeerAddress(host="127.0.0.1", port=9202)
        node.p2p_server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=1,
            batch_end_start_height=41,
            batch_chunk_count=FASTSYNC_INITIAL_BATCH_CHUNKS,
        )
        chunks = [
            source_chain.blocks[1:21],
            source_chain.blocks[21:41],
            source_chain.blocks[41:46],
        ]

        with mock.patch(
            "node.node.save_blockchain_state",
            return_value=Path("state/blockchains/test.json"),
        ) as save_state:
            for chunk in chunks:
                result = node._handle_chain_response(chunk)
                self.assertGreater(result["accepted"], 0)

            save_state.assert_not_called()

            node.p2p_server._complete_fast_sync(peer)

        save_state.assert_called_once_with(wallet.address, node.blockchain)
