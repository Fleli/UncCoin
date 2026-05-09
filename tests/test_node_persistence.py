import unittest
from pathlib import Path
from unittest import mock

from node.node import Node
from wallet import create_wallet


class NodePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_mining_persists_blockchain_state(self) -> None:
        wallet = create_wallet(name="persist-miner")
        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )
        node.mining_backend = "python"
        node._ensure_genesis_block()

        with mock.patch(
            "node.node.save_blockchain_state",
            return_value=Path("state/blockchains/test.json"),
        ) as save_state:
            block = await node.mine_pending_transactions("persist test")

        self.assertEqual(block.block_id, 1)
        save_state.assert_called_once_with(wallet.address, node.blockchain)

    def test_explicit_test_blockchain_does_not_auto_persist(self) -> None:
        wallet = create_wallet(name="explicit-chain")
        seeded_node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            difficulty_bits=0,
            genesis_difficulty_bits=0,
        )

        node = Node(
            host="127.0.0.1",
            port=0,
            wallet=wallet,
            blockchain=seeded_node.blockchain,
        )

        with mock.patch("node.node.save_blockchain_state") as save_state:
            node._save_persisted_blockchain("test")

        save_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
