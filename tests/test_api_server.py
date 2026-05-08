import unittest

from fastapi.testclient import TestClient

from core.block import Block
from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.utils.mining import create_mining_reward_transaction
from network.p2p_server import FastSyncState
from network.p2p_server import PeerAddress
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

    def test_sync_status_reports_active_fast_sync_peers(self) -> None:
        self.node.p2p_server.fast_sync_states[
            PeerAddress(host="100.98.249.35", port=9000)
        ] = FastSyncState(
            expected_start_height=2,
            batch_end_start_height=42,
            batch_chunk_count=2,
            pending_chunks={2: {"blocks": []}},
            active=True,
        )

        response = self.client.get("/api/v1/sync/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["phase"], "fastsync")
        self.assertTrue(body["fastsync"]["active"])
        self.assertEqual(
            body["fastsync"]["peers"],
            [
                {
                    "peer": "100.98.249.35:9000",
                    "expected_start_height": 2,
                    "pending_chunks": 1,
                }
            ],
        )

    def test_network_stats_reports_p2p_traffic(self) -> None:
        peer = PeerAddress(host="100.98.249.35", port=9000)
        self.node.p2p_server._record_ingress(peer, b'{"type":"peer_list"}\n')
        self.node.p2p_server._record_egress(peer, b'{"type":"peer_request"}\n')

        response = self.client.get("/api/v1/network/stats")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ingress"]["bytes"], 21)
        self.assertEqual(body["ingress"]["messages"], 1)
        self.assertEqual(body["egress"]["bytes"], 24)
        self.assertEqual(body["egress"]["messages"], 1)
        self.assertEqual(
            body["peers"],
            [
                {
                    "peer": "100.98.249.35:9000",
                    "connected": False,
                    "ingress": {"bytes": 21, "messages": 1},
                    "egress": {"bytes": 24, "messages": 1},
                }
            ],
        )

    def test_mining_status_reports_progress_and_recent_miners(self) -> None:
        self.node._start_mining_progress(
            mode="automine",
            description="Status test",
            difficulty_bits=7,
            tip_hash=self.node.blockchain.main_tip_hash,
        )
        self.node._report_mining_progress(12345)

        response = self.client.get("/api/v1/mining/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["active"])
        self.assertEqual(body["mode"], "automine")
        self.assertEqual(body["description"], "Status test")
        self.assertEqual(body["nonce"], 12345)
        self.assertEqual(body["difficulty_bits"], 7)
        self.assertEqual(body["backend"], self.node.mining_backend)
        self.assertFalse(body["warmup"]["active"])
        self.assertIsNone(body["last_block"]["nonces_checked"])
        self.assertEqual(
            body["recent_miners"],
            [
                {
                    "address": self.miner_wallet.address,
                    "alias": None,
                    "blocks": 1,
                }
            ],
        )

        self.node._clear_mining_progress()

    def test_mining_backend_endpoints_switch_backend(self) -> None:
        response = self.client.get("/api/v1/mining/backends")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["selected"], self.node.mining_backend)

        update_response = self.client.post(
            "/api/v1/control/mining/backend",
            json={"backend": "python"},
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["selected"], "python")
        self.assertEqual(self.node.mining_backend, "python")

    def test_missing_contract_returns_not_found(self) -> None:
        response = self.client.get("/api/v1/contracts/missing-contract")
        self.assertEqual(response.status_code, 404)

    def test_control_transaction_broadcasts_pending_transaction(self) -> None:
        response = self.client.post(
            "/api/v1/control/transactions",
            json={
                "receiver": self.receiver_wallet.address,
                "amount": "1.25",
                "fee": "0.25",
            },
        )

        self.assertEqual(response.status_code, 200)
        transaction_id = response.json()["transaction_id"]
        pending_response = self.client.get("/api/v1/transactions/pending")
        self.assertEqual(pending_response.status_code, 200)
        self.assertEqual(pending_response.json()["count"], 1)
        self.assertEqual(
            pending_response.json()["transactions"][0]["transaction_id"],
            transaction_id,
        )

    def test_control_mine_updates_chain_head(self) -> None:
        response = self.client.post(
            "/api/v1/control/mine",
            json={"description": "API mined block"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["block"]["height"], 2)
        head_response = self.client.get("/api/v1/chain/head")
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response.json()["height"], 2)

    def test_control_deploy_exposes_contract(self) -> None:
        deploy_response = self.client.post(
            "/api/v1/control/contracts/deploy",
            json={
                "fee": "0",
                "program": [["HALT"]],
                "metadata": {"name": "noop"},
            },
        )
        self.assertEqual(deploy_response.status_code, 200)
        contract_address = deploy_response.json()["contract_address"]

        self.client.post(
            "/api/v1/control/mine",
            json={"description": "deploy contract"},
        )
        contract_response = self.client.get(f"/api/v1/contracts/{contract_address}")

        self.assertEqual(contract_response.status_code, 200)
        self.assertEqual(
            contract_response.json()["contract"]["metadata"]["name"],
            "noop",
        )

    def test_control_authorize_records_on_chain_authorization(self) -> None:
        deploy_response = self.client.post(
            "/api/v1/control/contracts/deploy",
            json={
                "fee": "0",
                "program": [["HALT"]],
                "metadata": {"request_ids": ["casino-play-1"]},
            },
        )
        self.assertEqual(deploy_response.status_code, 200)
        contract_address = deploy_response.json()["contract_address"]
        code_hash = deploy_response.json()["code_hash"]
        self.client.post(
            "/api/v1/control/mine",
            json={"description": "deploy contract"},
        )

        authorize_response = self.client.post(
            "/api/v1/control/contracts/authorize",
            json={
                "contract_address": contract_address,
                "request_id": "casino-play-1",
                "fee": "0",
                "valid_for_blocks": "3",
            },
        )
        self.assertEqual(authorize_response.status_code, 200)
        self.assertEqual(
            authorize_response.json()["transaction"]["kind"],
            "authorize",
        )
        self.client.post(
            "/api/v1/control/mine",
            json={"description": "authorize contract"},
        )

        authorizations_response = self.client.get("/api/v1/authorizations")
        self.assertEqual(authorizations_response.status_code, 200)
        body = authorizations_response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(
            body["authorizations"],
            [
                {
                    "wallet": self.miner_wallet.address,
                    "contract_address": contract_address,
                    "code_hash": code_hash,
                    "request_id": "casino-play-1",
                    "scope": {
                        "valid_from_height": 3,
                        "valid_until_height": 5,
                    },
                    "authorized_at_height": 3,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
