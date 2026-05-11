import asyncio
import unittest
from unittest.mock import patch

from network.p2p_server import P2P_MESSAGE_LIMIT_BYTES, P2PServer, PeerAddress


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


class _OversizedReader:
    async def readline(self) -> bytes:
        raise ValueError("Separator is found, but chunk is longer than limit")


class _EmptyReader:
    async def readline(self) -> bytes:
        return b""


class _WritableWriter:
    def __init__(self) -> None:
        self.closed = False
        self.messages: list[bytes] = []

    def write(self, message: bytes) -> None:
        self.messages.append(message)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _ResettingWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        raise ConnectionResetError("connection reset by peer")


class P2PServerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_uses_large_p2p_message_limit(self) -> None:
        captured_limit: int | None = None

        async def fake_start_server(*args, **kwargs):
            nonlocal captured_limit
            del args
            captured_limit = kwargs.get("limit")
            return _FakeServer()

        server = P2PServer(host="127.0.0.1", port=9999)
        with patch("network.p2p_server.asyncio.start_server", new=fake_start_server):
            await server.start()

        self.assertEqual(captured_limit, P2P_MESSAGE_LIMIT_BYTES)

    async def test_connect_to_peer_uses_large_p2p_message_limit(self) -> None:
        captured_limit: int | None = None

        async def fake_open_connection(*args, **kwargs):
            nonlocal captured_limit
            del args
            captured_limit = kwargs.get("limit")
            return _EmptyReader(), _WritableWriter()

        server = P2PServer(host="127.0.0.1", port=9999)
        with patch("network.p2p_server.asyncio.open_connection", new=fake_open_connection):
            await server.connect_to_peer("127.0.0.1", 9100)
            await asyncio.sleep(0)

        self.assertEqual(captured_limit, P2P_MESSAGE_LIMIT_BYTES)

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

    async def test_oversized_message_disconnects_without_traceback(self) -> None:
        notifications: list[str] = []
        server = P2PServer(
            host="127.0.0.1",
            port=9999,
            on_notification=notifications.append,
        )
        peer = PeerAddress("80.202.146.65", 9000)
        writer = _ResettingWriter()
        server.active_connections[peer] = writer

        await server._read_messages(_OversizedReader(), writer, peer)

        self.assertTrue(writer.closed)
        self.assertNotIn(peer, server.active_connections)
        self.assertEqual(
            notifications,
            [
                (
                    "Dropped peer 80.202.146.65:9000: invalid or oversized message "
                    "(Separator is found, but chunk is longer than limit)"
                ),
                "Disconnected from peer 80.202.146.65:9000",
            ],
        )


if __name__ == "__main__":
    unittest.main()
