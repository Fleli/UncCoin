import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime

from core.blockchain import Blockchain
from core.transaction import Transaction
from network.p2p_server import P2PServer
from wallet import Wallet


@dataclass
class Node:
    host: str
    port: int
    wallet: Wallet | None = None
    blockchain: Blockchain | None = None
    p2p_server: P2PServer = field(init=False)

    def __post_init__(self) -> None:
        self.p2p_server = P2PServer(
            host=self.host,
            port=self.port,
            on_transaction=self._handle_incoming_transaction,
        )

    async def start(self) -> None:
        await self.p2p_server.start()
        if self.wallet is not None:
            wallet_name = self.wallet.name or "unnamed"
            print(f"Loaded wallet '{wallet_name}' with address {self.wallet.address}")

    async def serve_forever(self) -> None:
        await self.p2p_server.serve_forever()

    async def stop(self) -> None:
        await self.p2p_server.stop()

    async def connect_to_peer(self, host: str, port: int) -> None:
        await self.p2p_server.connect_to_peer(host, port)

    async def broadcast(self, message: dict) -> None:
        await self.p2p_server.broadcast(message)

    async def broadcast_transaction(self, transaction: Transaction) -> None:
        await self.p2p_server.broadcast_transaction(transaction)

    async def discover_peers(self) -> None:
        await self.p2p_server.discover_peers()

    async def send_to_peer(self, host: str, port: int, message: dict) -> None:
        await self.p2p_server.send_to_peer(host, port, message)

    def list_peers(self) -> list[str]:
        return self.p2p_server.list_peers()

    def list_known_peers(self) -> list[str]:
        return self.p2p_server.list_known_peers()

    def get_next_nonce(self, address: str) -> int:
        if self.blockchain is None:
            return 0
        return self.blockchain.get_next_nonce(address)

    def create_signed_transaction(
        self,
        receiver: str,
        amount: str,
        fee: str,
    ) -> Transaction:
        if self.wallet is None:
            raise ValueError("A loaded wallet is required to create signed transactions.")

        transaction = Transaction(
            sender=self.wallet.address,
            receiver=receiver,
            amount=amount,
            fee=fee,
            timestamp=datetime.now(),
            nonce=self.get_next_nonce(self.wallet.address),
            sender_public_key=self.wallet.public_key,
        )
        transaction.signature = self.wallet.sign_message(transaction.signing_payload())
        return transaction

    async def interactive_console(self) -> None:
        print("Interactive mode enabled.")
        print(
            'Enter JSON to broadcast, "/send host:port {...}" for a direct message, '
            '"/peers" to list connected peers, "/known-peers" to list discovered peers, '
            '"/discover" to ask peers for more peers, "/tx receiver amount fee" '
            'to broadcast a transaction, "/clear" to clear the screen, or "/quit" to exit.'
        )

        while True:
            try:
                raw_input_line = await asyncio.to_thread(input, "p2p> ")
            except EOFError:
                return

            line = raw_input_line.strip()
            if not line:
                continue

            if line == "/quit":
                return

            if line == "/clear":
                print("\033[2J\033[H", end="")
                continue

            if line == "/peers":
                peers = self.list_peers()
                print("Connected peers:" if peers else "No connected peers.")
                for peer in peers:
                    print(peer)
                continue

            if line == "/known-peers":
                peers = self.list_known_peers()
                print("Known peers:" if peers else "No known peers.")
                for peer in peers:
                    print(peer)
                continue

            if line == "/discover":
                await self.discover_peers()
                print("Peer discovery request sent.")
                continue

            if line.startswith("/tx "):
                try:
                    receiver, amount, fee = line[len("/tx "):].split(" ", maxsplit=2)
                    transaction = self.create_signed_transaction(
                        receiver=receiver,
                        amount=amount,
                        fee=fee,
                    )
                    await self.broadcast_transaction(transaction)
                except ValueError as error:
                    print(f"Invalid /tx command: {error}")
                continue

            if line.startswith("/send "):
                try:
                    peer_part, message_part = line[len("/send "):].split(" ", maxsplit=1)
                    host, port = peer_part.split(":", maxsplit=1)
                    message = json.loads(message_part)
                    await self.send_to_peer(host, int(port), message)
                    print(f"Sent direct message to {host}:{port}")
                except (ValueError, json.JSONDecodeError) as error:
                    print(f"Invalid /send command: {error}")
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                print(f"Invalid JSON: {error}")
                continue

            await self.broadcast(message)
            print("Broadcast message sent.")

    def _handle_incoming_transaction(self, transaction: Transaction) -> None:
        # Cleanup-only step: keep network transport and core orchestration separate for now.
        # The actual node-to-blockchain integration comes next.
        return
