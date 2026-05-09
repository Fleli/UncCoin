import json
import unittest
from datetime import datetime

from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.transaction import Transaction
from network.p2p_server import P2PServer
from network.p2p_server import PeerAddress


class RecordingWriter:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def write(self, data: bytes) -> None:
        self.messages.append(json.loads(data.decode("utf-8").rstrip("\n")))

    async def drain(self) -> None:
        return


def create_pending_transaction() -> Transaction:
    return Transaction.commit(
        sender="alice",
        request_id="coin",
        commitment_hash="a" * 64,
        fee="0",
        timestamp=datetime(2026, 1, 1),
    )


class P2PServerMempoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mempool_request_sends_pending_transactions_to_peer(self) -> None:
        transaction = create_pending_transaction()
        peer = PeerAddress(host="127.0.0.1", port=9101)
        writer = RecordingWriter()
        server = P2PServer(
            host="127.0.0.1",
            port=9100,
            on_pending_transactions=lambda: [transaction],
        )
        server.active_connections[peer] = writer

        await server._handle_message({"type": "mempool_request"}, peer)

        self.assertEqual(len(writer.messages), 1)
        self.assertEqual(writer.messages[0]["type"], "transaction")
        self.assertEqual(writer.messages[0]["transaction"], transaction.to_dict())

    async def test_handshake_requests_and_sends_mempool(self) -> None:
        transaction = create_pending_transaction()
        socket_peer = PeerAddress(host="127.0.0.1", port=51000)
        advertised_peer = PeerAddress(host="127.0.0.1", port=9101)
        writer = RecordingWriter()
        server = P2PServer(
            host="127.0.0.1",
            port=9100,
            on_chain_summary=lambda: ("tip", 4),
            on_pending_transactions=lambda: [transaction],
        )
        server.active_connections[socket_peer] = writer

        returned_peer = await server._handle_message(
            {
                "type": "handshake",
                "host": advertised_peer.host,
                "port": advertised_peer.port,
                "tip_hash": "tip",
                "height": 4,
            },
            socket_peer,
        )

        self.assertEqual(returned_peer, advertised_peer)
        self.assertNotIn(socket_peer, server.active_connections)
        self.assertIn(advertised_peer, server.active_connections)
        self.assertEqual([message["type"] for message in writer.messages], [
            "mempool_request",
            "transaction",
        ])

    async def test_rebroadcast_pending_transactions_sends_to_connected_peers(self) -> None:
        transaction = create_pending_transaction()
        peer = PeerAddress(host="127.0.0.1", port=9101)
        writer = RecordingWriter()
        server = P2PServer(
            host="127.0.0.1",
            port=9100,
            on_pending_transactions=lambda: [transaction],
        )
        server.active_connections[peer] = writer

        count = await server.broadcast_pending_transactions()

        self.assertEqual(count, 1)
        self.assertEqual(len(writer.messages), 1)
        self.assertEqual(writer.messages[0]["type"], "transaction")

    async def test_accepted_block_requests_peer_mempool(self) -> None:
        peer = PeerAddress(host="127.0.0.1", port=9101)
        writer = RecordingWriter()
        block = create_genesis_block(sha256_block_hash)
        server = P2PServer(
            host="127.0.0.1",
            port=9100,
            on_block=lambda _block: ("accepted", None),
        )
        server.active_connections[peer] = writer

        await server._handle_message(
            {
                "type": "block",
                "block_hash": block.block_hash,
                "block": block.to_dict(),
            },
            peer,
        )

        self.assertEqual(len(writer.messages), 1)
        self.assertEqual(writer.messages[0]["type"], "mempool_request")


if __name__ == "__main__":
    unittest.main()
