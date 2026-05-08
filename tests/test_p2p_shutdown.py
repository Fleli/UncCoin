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


if __name__ == "__main__":
    unittest.main()
