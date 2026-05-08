import unittest

from fastapi.testclient import TestClient

from core.block import Block
from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.utils.mining import create_mining_reward_transaction
from node.api_server import create_api_app
from node.node import Node
from wallet import create_wallet


def create_funded_node() -> tuple[Node, object, object]:
    miner_wallet = create_wallet(name="miner")
    receiver_wallet = create_wallet(name="receiver")
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
        genesis_difficulty_bits=0,
    )
    genesis_block = create_genesis_block(sha256_block_hash)
    blockchain.add_block(genesis_block)
    reward_block = Block(
        block_id=1,
        transactions=[create_mining_reward_transaction(miner_wallet.address)],
        hash_function=sha256_block_hash,
        description="Reward",
        previous_hash=genesis_block.block_hash,
    )
    blockchain.add_block(reward_block)
    node = Node(
        host="127.0.0.1",
        port=9000,
        wallet=miner_wallet,
        blockchain=blockchain,
    )
    return node, miner_wallet, receiver_wallet


class NodeApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.node, self.miner_wallet, self.receiver_wallet = create_funded_node()
        self.client = TestClient(create_api_app(self.node))

    def test_chain_and_balance_endpoints_return_current_state(self) -> None:
        head_response = self.client.get("/api/v1/chain/head")
        self.assertEqual(head_response.status_code, 200)
        head = head_response.json()
        self.assertEqual(head["height"], 1)
        self.assertEqual(head["block_count"], 2)
        self.assertEqual(head["pending_transaction_count"], 0)

        blocks_response = self.client.get("/api/v1/chain/blocks", params={"limit": 1})
        self.assertEqual(blocks_response.status_code, 200)
        blocks = blocks_response.json()
        self.assertEqual(blocks["count"], 1)
        self.assertEqual(blocks["blocks"][0]["height"], 0)
        self.assertEqual(blocks["next_from_height"], 1)

        balance_response = self.client.get(
            f"/api/v1/balances/{self.miner_wallet.address}"
        )
        self.assertEqual(balance_response.status_code, 200)
        self.assertEqual(balance_response.json()["balance"], "10.0")

    def test_pending_transactions_endpoint_includes_transaction_ids(self) -> None:
        transaction = self.node.create_signed_transaction(
            receiver=self.receiver_wallet.address,
            amount="1.25",
            fee="0.25",
        )
        self.node.blockchain.add_transaction(transaction)

        response = self.client.get("/api/v1/transactions/pending")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(
            body["transactions"][0]["transaction_id"],
            sha256_transaction_hash(transaction),
        )
        self.assertEqual(body["transactions"][0]["amount"], "1.25")

    def test_commitments_and_reveals_return_empty_objects_when_missing(self) -> None:
        commitments_response = self.client.get("/api/v1/commitments/missing-request")
        reveals_response = self.client.get("/api/v1/reveals/missing-request")

        self.assertEqual(commitments_response.status_code, 200)
        self.assertEqual(reveals_response.status_code, 200)
        self.assertEqual(commitments_response.json()["commitments"], {})
        self.assertEqual(reveals_response.json()["reveals"], {})

    def test_missing_contract_returns_not_found(self) -> None:
        response = self.client.get("/api/v1/contracts/missing-contract")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
