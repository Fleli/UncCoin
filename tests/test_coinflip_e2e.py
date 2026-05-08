import unittest
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.randomness import create_reveal_commitment_hash
from node.node import Node
from wallet import create_wallet


REQUEST_ID = "coinflip"


def create_blockchain() -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    return blockchain


def build_coinflip_contract(
    player_a: str,
    player_b: str,
    *,
    reveal_deadline: int,
) -> tuple[list[list], dict]:
    metadata = {
        "request_ids": [REQUEST_ID],
        "reveal_deadline": reveal_deadline,
    }
    program = [
        ["LOAD", "settled"],
        ["JUMPI", 51],
        ["HAS_REVEAL", player_a, REQUEST_ID],
        ["MEM_STORE", "a_revealed"],
        ["HAS_REVEAL", player_b, REQUEST_ID],
        ["MEM_STORE", "b_revealed"],
        ["MEM_LOAD", "a_revealed"],
        ["MEM_LOAD", "b_revealed"],
        ["AND"],
        ["JUMPI", 32],
        ["BLOCK_HEIGHT"],
        ["READ_METADATA", "reveal_deadline"],
        ["GT"],
        ["JUMPI", 15],
        ["HALT"],
        ["MEM_LOAD", "a_revealed"],
        ["JUMPI", 22],
        ["MEM_LOAD", "b_revealed"],
        ["JUMPI", 27],
        ["PUSH", 1],
        ["STORE", "settled"],
        ["HALT"],
        ["PUSH", 1],
        ["STORE", "settled"],
        ["PUSH", 100],
        ["TRANSFER_FROM", player_b, player_a, REQUEST_ID],
        ["HALT"],
        ["PUSH", 1],
        ["STORE", "settled"],
        ["PUSH", 100],
        ["TRANSFER_FROM", player_a, player_b, REQUEST_ID],
        ["HALT"],
        ["PUSH", 1],
        ["STORE", "settled"],
        ["PUSH", 100],
        ["TRANSFER_FROM", player_a, "$CONTRACT", REQUEST_ID],
        ["PUSH", 100],
        ["TRANSFER_FROM", player_b, "$CONTRACT", REQUEST_ID],
        ["READ_REVEAL", player_a, REQUEST_ID],
        ["READ_REVEAL", player_b, REQUEST_ID],
        ["XOR"],
        ["SHA256"],
        ["PUSH", 2],
        ["MOD"],
        ["JUMPI", 48],
        ["PUSH", 200],
        ["TRANSFER_FROM", "$CONTRACT", player_a, "coinflip:payout"],
        ["HALT"],
        ["PUSH", 200],
        ["TRANSFER_FROM", "$CONTRACT", player_b, "coinflip:payout"],
        ["HALT"],
        ["HALT"],
    ]
    return program, metadata


class CoinflipEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blockchain = create_blockchain()
        self.player_a = create_wallet(name="player-a")
        self.player_b = create_wallet(name="player-b")
        self.node_a = Node(
            host="127.0.0.1",
            port=9701,
            wallet=self.player_a,
            blockchain=self.blockchain,
        )
        self.node_b = Node(
            host="127.0.0.1",
            port=9702,
            wallet=self.player_b,
            blockchain=self.blockchain,
        )
        self._fund(self.player_a.address, blocks=12)
        self._fund(self.player_b.address, blocks=12)

    def test_coinflip_deploy_authorize_commit_reveal_execute_settles_once(self) -> None:
        contract_address, _program, _metadata = self._deploy_coinflip(
            reveal_deadline=self.blockchain.blocks[-1].block_id + 10,
        )
        authorizations = self._authorizations(contract_address)
        self._commit_and_reveal(self.node_a, self.player_a, seed=12345, salt="a")
        self._commit_and_reveal(self.node_b, self.player_b, seed=67890, salt="b")

        execute_transaction = self.node_a.create_signed_execute(
            contract_address=contract_address,
            input_data=[],
            gas_limit="2000",
            gas_price="0.01",
            value="0",
            fee="20.00",
            authorizations=authorizations,
        )
        execute_transaction_id = self._accept(execute_transaction, "execute coinflip")
        self._mine("execute coinflip")

        receipt = self.blockchain.get_uvm_receipt(execute_transaction_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertTrue(receipt["success"], receipt.get("error"))
        self.assertFalse(receipt["gas_exhausted"])
        self.assertEqual(
            self.blockchain.get_contract_storage(contract_address),
            {"settled": 1},
        )
        self.assertEqual(receipt["fee_escrowed"], "20.00")
        self.assertEqual(
            Decimal(receipt["fee_paid"]),
            Decimal(receipt["gas_used"]) * Decimal("0.01"),
        )
        self.assertEqual(
            Decimal(receipt["fee_refunded"]),
            Decimal("20.00") - Decimal(receipt["fee_paid"]),
        )

        balance_changes = {
            address: Decimal(change)
            for address, change in receipt["balance_changes"].items()
        }
        self.assertEqual(
            set(balance_changes),
            {self.player_a.address, self.player_b.address},
        )
        self.assertIn(
            balance_changes[self.player_a.address],
            {Decimal("100.0"), Decimal("-100.0")},
        )
        self.assertEqual(
            balance_changes[self.player_a.address],
            -balance_changes[self.player_b.address],
        )
        self.assertEqual(len(receipt["transfers"]), 3)

        replay_transaction = self.node_a.create_signed_execute(
            contract_address=contract_address,
            input_data=[],
            gas_limit="100",
            gas_price="0",
            value="0",
            fee="0",
            authorizations=authorizations,
        )
        replay_transaction_id = self._accept(replay_transaction, "replay coinflip")
        self._mine("replay coinflip")
        replay_receipt = self.blockchain.get_uvm_receipt(replay_transaction_id)
        self.assertIsNotNone(replay_receipt)
        assert replay_receipt is not None
        self.assertTrue(replay_receipt["success"], replay_receipt.get("error"))
        self.assertEqual(replay_receipt["balance_changes"], {})
        self.assertEqual(
            self.blockchain.get_contract_storage(contract_address),
            {"settled": 1},
        )

    def test_coinflip_execute_after_deadline_punishes_missing_revealer(self) -> None:
        reveal_deadline = self.blockchain.blocks[-1].block_id + 3
        contract_address, _program, _metadata = self._deploy_coinflip(
            reveal_deadline=reveal_deadline,
        )
        authorizations = self._authorizations(contract_address)
        self._commit_and_reveal(self.node_a, self.player_a, seed=12345, salt="a")

        execute_transaction = self.node_a.create_signed_execute(
            contract_address=contract_address,
            input_data=[],
            gas_limit="2000",
            gas_price="0",
            value="0",
            fee="0",
            authorizations=authorizations,
        )
        execute_transaction_id = self._accept(execute_transaction, "execute timeout")
        execute_height = self._mine("execute timeout")

        receipt = self.blockchain.get_uvm_receipt(execute_transaction_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertGreater(execute_height, reveal_deadline)
        self.assertTrue(receipt["success"], receipt.get("error"))
        self.assertEqual(
            self.blockchain.get_contract_storage(contract_address),
            {"settled": 1},
        )
        self.assertEqual(
            receipt["balance_changes"],
            {
                self.player_b.address: "-100.0",
                self.player_a.address: "100.0",
            },
        )
        self.assertEqual(
            receipt["transfers"],
            [
                {
                    "source": self.player_b.address,
                    "receiver": self.player_a.address,
                    "amount": "100",
                    "request_id": REQUEST_ID,
                }
            ],
        )

    def _fund(self, address: str, *, blocks: int) -> None:
        for _ in range(blocks):
            self._mine(f"fund {address[:12]}", miner_address=address)

    def _deploy_coinflip(self, *, reveal_deadline: int) -> tuple[str, list[list], dict]:
        program, metadata = build_coinflip_contract(
            self.player_a.address,
            self.player_b.address,
            reveal_deadline=reveal_deadline,
        )
        deploy_transaction = self.node_a.create_signed_deploy(
            program=program,
            metadata=metadata,
            fee="0",
        )
        self._accept(deploy_transaction, "deploy coinflip")
        self._mine("deploy coinflip")
        self.assertIsNotNone(self.blockchain.get_contract(deploy_transaction.receiver))
        return deploy_transaction.receiver, program, metadata

    def _authorizations(self, contract_address: str) -> list[dict]:
        return [
            self.node_a.create_uvm_authorization_receipt(
                contract_address=contract_address,
                request_id=REQUEST_ID,
                valid_for_blocks="10",
            ),
            self.node_b.create_uvm_authorization_receipt(
                contract_address=contract_address,
                request_id=REQUEST_ID,
                valid_for_blocks="10",
            ),
        ]

    def _commit_and_reveal(
        self,
        node: Node,
        wallet,
        *,
        seed: int,
        salt: str,
    ) -> None:
        commitment_hash = create_reveal_commitment_hash(
            wallet.address,
            REQUEST_ID,
            seed,
            salt,
        )
        commit_transaction = node.create_signed_commitment(
            REQUEST_ID,
            commitment_hash,
            fee="0",
        )
        self._accept(commit_transaction, "commit")
        self._mine("commit")

        reveal_transaction = node.create_signed_reveal(
            request_id=REQUEST_ID,
            seed=str(seed),
            fee="0",
            salt=salt,
        )
        self._accept(reveal_transaction, "reveal")
        self._mine("reveal")

    def _accept(self, transaction, label: str) -> str:
        accepted, reason = self.node_a._handle_incoming_transaction(transaction)
        self.assertTrue(accepted, f"{label} rejected: {reason}")
        return sha256_transaction_hash(transaction)

    def _mine(self, description: str, *, miner_address: str = "miner") -> int:
        block = self.blockchain.mine_pending_transactions(
            miner_address=miner_address,
            description=description,
        )
        return block.block_id


if __name__ == "__main__":
    unittest.main()
