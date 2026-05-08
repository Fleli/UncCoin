import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.transaction import Transaction
from node.node import Node
from wallet import create_wallet


def create_blockchain() -> Blockchain:
    blockchain = Blockchain(
        difficulty_bits=0,
        hash_function=sha256_block_hash,
    )
    blockchain.add_block(create_genesis_block(sha256_block_hash))
    return blockchain


def sign_transaction(wallet, transaction: Transaction) -> Transaction:
    transaction.signature = wallet.sign_message(transaction.signing_payload())
    return transaction


class DeployTransactionTests(unittest.TestCase):
    def test_deploy_records_contract_program_and_metadata(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        program = [
            ["PUSH", 7],
            ["STORE", "number"],
            ["HALT"],
        ]
        metadata = {
            "name": "number-store",
            "request_ids": ["casino-play-1"],
        }
        deploy_transaction = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
                contract_address="contract-number-store",
                program=program,
                metadata=metadata,
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(deployer.address),
                sender_public_key=deployer.public_key,
            ),
        )

        blockchain.add_transaction(deploy_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy contract",
        )

        self.assertEqual(
            blockchain.get_contract("contract-number-store"),
            {
                "deployer": deployer.address,
                "program": program,
                "metadata": metadata,
            },
        )

    def test_execute_uses_deployed_program(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        caller = create_wallet(name="caller")
        deploy_transaction = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
                contract_address="contract-number-store",
                program=[
                    ["PUSH", 7],
                    ["STORE", "number"],
                    ["HALT"],
                ],
                metadata={"request_ids": ["casino-play-1"]},
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(deployer.address),
                sender_public_key=deployer.public_key,
            ),
        )
        blockchain.add_transaction(deploy_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy contract",
        )
        execute_transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="contract-number-store",
                input_data=[],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=200,
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(execute_transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="execute deployed contract",
        )

        self.assertEqual(
            blockchain.get_contract_storage("contract-number-store"),
            {"number": 7},
        )

    def test_deploy_rejects_duplicate_contract_address(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        first_deploy = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
                contract_address="contract-number-store",
                program=[["HALT"]],
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(deployer.address),
                sender_public_key=deployer.public_key,
            ),
        )
        blockchain.add_transaction(first_deploy)

        second_deploy = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
                contract_address="contract-number-store",
                program=[["HALT"]],
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(deployer.address),
                sender_public_key=deployer.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "already deployed"):
            blockchain.add_transaction(second_deploy)

    def test_deploy_validates_metadata_request_ids(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        deploy_transaction = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
                contract_address="contract-number-store",
                program=[["HALT"]],
                metadata={"request_ids": [""]},
                fee=Decimal("0"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(deployer.address),
                sender_public_key=deployer.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "request_ids"):
            blockchain.add_transaction(deploy_transaction)

    def test_execute_rejects_undeployed_contract_without_inline_program(self) -> None:
        blockchain = create_blockchain()
        caller = create_wallet(name="caller")
        execute_transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="missing-contract",
                input_data=None,
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=200,
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "undeployed contract"):
            blockchain.add_transaction(execute_transaction)


class NodeDeployTransactionTests(unittest.TestCase):
    def test_node_creates_signed_deploy_transaction(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        node = Node(
            host="127.0.0.1",
            port=9500,
            wallet=deployer,
            blockchain=blockchain,
        )

        deploy_transaction = node.create_signed_deploy(
            contract_address="contract-number-store",
            program=[["HALT"]],
            metadata={"request_ids": ["casino-play-1"]},
            fee="0",
        )

        accepted, reason = node._handle_incoming_transaction(deploy_transaction)
        self.assertTrue(accepted, reason)

    def test_node_creates_signed_execute_transaction_and_formats_receipt(self) -> None:
        blockchain = create_blockchain()
        caller = create_wallet(name="caller")
        node = Node(
            host="127.0.0.1",
            port=9501,
            wallet=caller,
            blockchain=blockchain,
        )

        execute_transaction = node.create_signed_execute(
            contract_address="contract-number-store",
            input_data=[
                ["PUSH", 7],
                ["STORE", "number"],
                ["HALT"],
            ],
            gas_limit="200",
            gas_price="0",
            value="0",
            fee="0",
            authorizations=[],
        )

        accepted, reason = node._handle_incoming_transaction(execute_transaction)
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="execute contract",
        )

        transaction_id = sha256_transaction_hash(execute_transaction)
        formatted_receipt = node.format_uvm_receipt(transaction_id[:12])
        self.assertIn(f"UVM receipt {transaction_id}", formatted_receipt)
        self.assertIn("status: success", formatted_receipt)
        self.assertIn("gas_used: 101", formatted_receipt)
        self.assertIn('storage: {"number": 7}', formatted_receipt)


if __name__ == "__main__":
    unittest.main()
