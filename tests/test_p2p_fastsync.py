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

    async def test_chain_batch_processes_consecutive_chunks_then_requests_next_batch(self) -> None:
        remote_blockchain = create_blockchain(block_count=45)
        remote_server = P2PServer(
            host="127.0.0.1",
            port=9104,
            on_chain_request=lambda: remote_blockchain.blocks,
        )
        peer = PeerAddress(host="127.0.0.1", port=9105)
        processed_starts: list[int] = []

        def on_chain_response(blocks: list) -> dict[str, int]:
            processed_starts.append(blocks[0].block_id)
            return {
                "accepted": len(blocks),
                "duplicates": 0,
                "orphans": 0,
                "rejected": 0,
            }

        server = P2PServer(
            host="127.0.0.1",
            port=9106,
            on_chain_response=on_chain_response,
        )
        server.fast_sync_states[peer] = FastSyncState(expected_start_height=1)
        message = {
            "type": "chain_batch",
            "height": 45,
            "chunks": [
                remote_server._build_chain_chunk_payload(1),
                remote_server._build_chain_chunk_payload(21),
            ],
        }

        with mock.patch.object(server, "request_chain_batch", new=mock.AsyncMock()) as request_chain_batch:
            await server._handle_chain_batch(message, peer)

        self.assertEqual(processed_starts, [1, 21])
        self.assertEqual(server.fast_sync_states[peer].expected_start_height, 41)
        request_chain_batch.assert_awaited_once()
        self.assertEqual(request_chain_batch.await_args.args[0:2], (peer.host, peer.port))
        next_batch_starts = request_chain_batch.await_args.args[2]
        self.assertEqual(next_batch_starts[0], 41)
        self.assertEqual(next_batch_starts[1], 41 + CHAIN_SYNC_CHUNK_SIZE)
