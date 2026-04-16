import unittest
from unittest import mock

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from network.p2p_server import CHAIN_SYNC_CHUNK_SIZE
from network.p2p_server import FASTSYNC_BATCH_CHUNKS
from network.p2p_server import FastSyncState
from network.p2p_server import P2PServer
from network.p2p_server import PeerAddress


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


class P2PServerFastSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_chain_sync_default_uses_single_chunk_requests(self) -> None:
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
        self.assertEqual(send_message.await_count, 1)
        self.assertEqual(
            send_message.await_args.args[1],
            {"type": "chain_request", "start_height": 40},
        )

    async def test_request_chain_sync_fast_batches_50_chunk_requests(self) -> None:
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

        sent_message = send_message.await_args.args[1]
        self.assertEqual(sent_message["type"], "chain_batch_request")
        self.assertEqual(len(sent_message["start_heights"]), FASTSYNC_BATCH_CHUNKS)
        self.assertEqual(sent_message["start_heights"][0], 40)
        self.assertEqual(
            sent_message["start_heights"][1],
            40 + CHAIN_SYNC_CHUNK_SIZE,
        )
        self.assertEqual(
            sent_message["start_heights"][-1],
            40 + ((FASTSYNC_BATCH_CHUNKS - 1) * CHAIN_SYNC_CHUNK_SIZE),
        )

    async def test_chain_batch_request_sends_independent_chain_chunk_messages(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9105)
        remote_blockchain = create_blockchain(block_count=45)
        server = P2PServer(
            host="127.0.0.1",
            port=9104,
            on_chain_request=lambda: remote_blockchain.blocks,
        )

        with mock.patch.object(server, "_send_chain_chunk", new=mock.AsyncMock()) as send_chain_chunk:
            await server._handle_message(
                {"type": "chain_batch_request", "start_heights": [21, 1]},
                peer,
            )

        self.assertEqual(
            [call.args[1] for call in send_chain_chunk.await_args_list],
            [1, 21],
        )

    async def test_fastsync_processes_consecutive_chunks_then_requests_next_batch(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9106)
        processed_starts: list[int] = []
        server = P2PServer(
            host="127.0.0.1",
            port=9107,
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
        )

        with mock.patch.object(server, "_request_next_fast_sync_batch", new=mock.AsyncMock()) as request_chain_batch:
            await server._handle_message(
                {
                    "type": "chain_chunk",
                    "start_height": 1,
                    "height": 45,
                    "done": False,
                    "next_start_height": 21,
                    "blocks": [create_blockchain(block_count=45).blocks[1].to_dict()],
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
                    "blocks": [create_blockchain(block_count=45).blocks[21].to_dict()],
                },
                peer,
            )

        self.assertEqual(processed_starts, [1, 21])
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 41)
        request_chain_batch.assert_awaited_once()
        self.assertEqual(request_chain_batch.await_args.args, (peer, 41))

    async def test_handshake_does_not_start_ordinary_sync_during_active_fastsync(self) -> None:
        peer = PeerAddress(host="0.0.0.0", port=5000)
        original_peer = PeerAddress(host="100.71.105.5", port=5000)
        server = P2PServer(
            host="127.0.0.1",
            port=9108,
            on_chain_summary=lambda: ("tip", 4898),
        )
        server.active_connections[original_peer] = object()
        server.fast_sync_states[peer] = FastSyncState(
            expected_start_height=4899,
            batch_end_start_height=5879,
        )

        with mock.patch.object(server, "request_chain", new=mock.AsyncMock()) as request_chain:
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
        request_chain.assert_not_awaited()
