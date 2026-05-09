import asyncio
import unittest
from unittest.mock import patch

from network.p2p_server import P2PServer, PeerAddress


class _FakeServer:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _HangingWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        await asyncio.Future()


class _ResettingReader:
    async def readline(self) -> bytes:
        raise ConnectionResetError("connection reset by peer")


class _ResettingWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        raise ConnectionResetError("connection reset by peer")


class P2PServerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_does_not_hang_on_peer_wait_closed(self) -> None:
        notifications: list[str] = []
        server = P2PServer(
            host="127.0.0.1",
            port=9999,
            on_notification=notifications.append,
        )
        writer = _HangingWriter()
        peer = PeerAddress("127.0.0.1", 9100)
        server.server = _FakeServer()
        server.active_connections[peer] = writer

        with patch("network.p2p_server.P2P_CLOSE_TIMEOUT_SECONDS", 0.01):
            await server.stop()

        self.assertTrue(writer.closed)
        self.assertEqual(server.active_connections, {})
        self.assertTrue(
            any("Timed out waiting for peer" in message for message in notifications)
        )

    async def test_disconnect_peer_closes_one_connection(self) -> None:
        server = P2PServer(host="127.0.0.1", port=9999)
        writer = _HangingWriter()
        peer = PeerAddress("127.0.0.1", 9100)
        other_peer = PeerAddress("127.0.0.1", 9101)
        other_writer = _HangingWriter()
        server.active_connections[peer] = writer
        server.active_connections[other_peer] = other_writer

        with patch("network.p2p_server.P2P_CLOSE_TIMEOUT_SECONDS", 0.01):
            await server.disconnect_peer(peer.host, peer.port)

        self.assertTrue(writer.closed)
        self.assertFalse(other_writer.closed)
        self.assertNotIn(peer, server.active_connections)
        self.assertIn(other_peer, server.active_connections)

    async def test_peer_reset_during_read_disconnects_without_traceback(self) -> None:
        notifications: list[str] = []
        server = P2PServer(
            host="127.0.0.1",
            port=9999,
            on_notification=notifications.append,
        )
        peer = PeerAddress("0.0.0.0", 4001)
        writer = _ResettingWriter()
        server.active_connections[peer] = writer

        await server._read_messages(_ResettingReader(), writer, peer)

        self.assertTrue(writer.closed)
        self.assertNotIn(peer, server.active_connections)
        self.assertEqual(notifications, ["Disconnected from peer 0.0.0.0:4001"])


if __name__ == "__main__":
    unittest.main()
