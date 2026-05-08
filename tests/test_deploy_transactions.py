import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import node.authorization_store as authorization_store
import node.message_store as message_store
from core.blockchain import Blockchain
from core.contracts import compute_contract_code_hash
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
        code_hash = compute_contract_code_hash(program, metadata)

        self.assertEqual(
            blockchain.get_contract(deploy_transaction.receiver),
            {
                "deployer": deployer.address,
                "code_hash": code_hash,
                "program": program,
                "metadata": metadata,
            },
        )

    def test_execute_uses_deployed_program(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        caller = create_wallet(name="caller")
        program = [
            ["READ_METADATA", "number"],
            ["STORE", "number"],
            ["HALT"],
        ]
        metadata = {
            "number": 7,
            "request_ids": ["casino-play-1"],
        }
        deploy_transaction = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
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
        contract_address = deploy_transaction.receiver
        execute_transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address=contract_address,
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
            blockchain.get_contract_storage(contract_address),
            {"number": 7},
        )

    def test_deploy_rejects_non_deterministic_contract_address(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        deploy_transaction = sign_transaction(
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

        with self.assertRaisesRegex(ValueError, "deterministic address"):
            blockchain.add_transaction(deploy_transaction)

    def test_deploy_validates_metadata_request_ids(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        deploy_transaction = sign_transaction(
            deployer,
            Transaction.deploy(
                sender=deployer.address,
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
            program=[["HALT"]],
            metadata={"request_ids": ["casino-play-1"]},
            fee="0",
        )

        accepted, reason = node._handle_incoming_transaction(deploy_transaction)
        self.assertTrue(accepted, reason)
        self.assertEqual(len(deploy_transaction.receiver), 64)

    def test_node_creates_signed_deploy_transaction_from_contract_file(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        node = Node(
            host="127.0.0.1",
            port=9501,
            wallet=deployer,
            blockchain=blockchain,
        )
        contract_source = {
            "metadata": {
                "request_ids": ["coinflip"],
                "reveal_deadline": 10,
            },
            "program": [
                ["READ_METADATA", "reveal_deadline"],
                ["STORE", "deadline"],
                ["HALT"],
            ],
        }

        contracts_parent = Node.REPO_ROOT / "state" / "contracts"
        contracts_parent.mkdir(parents=True, exist_ok=True)
        original_contracts_dir = Node.CONTRACTS_DIR
        with TemporaryDirectory(dir=contracts_parent) as contracts_dir:
            Node.CONTRACTS_DIR = Path(contracts_dir)
            try:
                (Node.CONTRACTS_DIR / "coinflip.uvm").write_text(
                    json.dumps(contract_source),
                    encoding="utf-8",
                )
                deploy_transaction = node.create_signed_deploy_from_source(
                    contract_source="coinflip",
                    fee="0",
                )
            finally:
                Node.CONTRACTS_DIR = original_contracts_dir

        accepted, reason = node._handle_incoming_transaction(deploy_transaction)
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy coinflip contract",
        )

        contract = blockchain.get_contract(deploy_transaction.receiver)
        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract["code_hash"], deploy_transaction.payload["code_hash"])
        self.assertEqual(contract["program"], contract_source["program"])
        self.assertEqual(contract["metadata"], contract_source["metadata"])

    def test_node_creates_contract_bound_authorization_receipt(self) -> None:
        blockchain = create_blockchain()
        wallet = create_wallet(name="wallet")
        node = Node(
            host="127.0.0.1",
            port=9503,
            wallet=wallet,
            blockchain=blockchain,
        )
        deploy_transaction = node.create_signed_deploy(
            program=[["HALT"]],
            fee="0",
        )
        accepted, reason = node._handle_incoming_transaction(deploy_transaction)
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy contract",
        )

        authorization = node.create_uvm_authorization_receipt(
            contract_address=deploy_transaction.receiver,
            request_id="casino-play-1",
            valid_for_blocks="2",
        )

        self.assertEqual(authorization["wallet"], wallet.address)
        self.assertEqual(authorization["contract_address"], deploy_transaction.receiver)
        self.assertEqual(authorization["code_hash"], deploy_transaction.payload["code_hash"])
        self.assertEqual(authorization["request_id"], "casino-play-1")
        self.assertEqual(
            authorization["scope"],
            {
                "valid_from_height": blockchain.blocks[-1].block_id + 1,
                "valid_until_height": blockchain.blocks[-1].block_id + 2,
            },
        )

    def test_node_stores_authorization_message_and_auto_includes_on_execute(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        executor = create_wallet(name="executor")
        source_node = Node(
            host="127.0.0.1",
            port=9505,
            wallet=source,
            blockchain=blockchain,
        )
        executor_node = Node(
            host="127.0.0.1",
            port=9506,
            wallet=executor,
            blockchain=blockchain,
        )
        request_id = "casino-payout-1"
        program = [
            ["PUSH", 3],
            ["TRANSFER_FROM", source.address, receiver.address, request_id],
            ["HALT"],
        ]

        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        deploy_transaction = executor_node.create_signed_deploy(
            program=program,
            fee="0",
        )
        accepted, reason = executor_node._handle_incoming_transaction(
            deploy_transaction,
        )
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy contract",
        )

        original_authorizations_dir = authorization_store.AUTHORIZATIONS_DIR
        original_msgs_dir = message_store.MSGS_DIR
        with (
            TemporaryDirectory() as authorizations_dir,
            TemporaryDirectory() as messages_dir,
        ):
            authorization_store.AUTHORIZATIONS_DIR = Path(authorizations_dir)
            message_store.MSGS_DIR = Path(messages_dir)
            try:
                wallet_message = source_node.create_signed_authorization_message(
                    receiver=executor.address,
                    contract_address=deploy_transaction.receiver,
                    request_id=request_id,
                    valid_for_blocks="3",
                )

                with mock.patch.object(
                    executor_node,
                    "_print_network_notification",
                ):
                    self.assertTrue(executor_node._handle_wallet_message(wallet_message))
                stored_authorizations = authorization_store.load_authorizations(
                    executor.address,
                )
                self.assertEqual(len(stored_authorizations), 1)
                self.assertEqual(stored_authorizations[0]["wallet"], source.address)

                execute_transaction = executor_node.create_signed_execute(
                    contract_address=deploy_transaction.receiver,
                    input_data=[],
                    gas_limit="100",
                    gas_price="0",
                    value="0",
                    fee="0",
                    authorizations=[],
                )
            finally:
                authorization_store.AUTHORIZATIONS_DIR = original_authorizations_dir
                message_store.MSGS_DIR = original_msgs_dir

        self.assertEqual(len(execute_transaction.payload["authorizations"]), 1)
        accepted, reason = executor_node._handle_incoming_transaction(
            execute_transaction,
        )
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="execute with stored authorization",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("7.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("3.0"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(execute_transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertTrue(receipt["success"], receipt.get("error"))
        self.assertEqual(
            receipt["transfers"],
            [
                {
                    "source": source.address,
                    "receiver": receiver.address,
                    "amount": "3",
                    "request_id": request_id,
                }
            ],
        )

    def test_node_formats_deployed_contract_view(self) -> None:
        blockchain = create_blockchain()
        deployer = create_wallet(name="deployer")
        node = Node(
            host="127.0.0.1",
            port=9504,
            wallet=deployer,
            blockchain=blockchain,
        )
        program = [
            ["PUSH", 7],
            ["STORE", "number"],
            ["HALT"],
        ]
        metadata = {"request_ids": ["casino-play-1"]}
        deploy_transaction = node.create_signed_deploy(
            program=program,
            metadata=metadata,
            fee="0",
        )
        accepted, reason = node._handle_incoming_transaction(deploy_transaction)
        self.assertTrue(accepted, reason)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="deploy contract",
        )

        formatted_contract = node.format_contract_view(deploy_transaction.receiver[:12])

        self.assertIn(f"Contract {deploy_transaction.receiver}:", formatted_contract)
        self.assertIn(f"deployer: {deployer.address}", formatted_contract)
        self.assertIn(
            f"code_hash: {deploy_transaction.payload['code_hash']}",
            formatted_contract,
        )
        self.assertIn('metadata: {"request_ids": ["casino-play-1"]}', formatted_contract)
        self.assertIn('"PUSH",', formatted_contract)
        self.assertIn('"STORE",', formatted_contract)
        self.assertIn('"HALT"', formatted_contract)

    def test_node_creates_signed_execute_transaction_and_formats_receipt(self) -> None:
        blockchain = create_blockchain()
        caller = create_wallet(name="caller")
        node = Node(
            host="127.0.0.1",
            port=9502,
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
