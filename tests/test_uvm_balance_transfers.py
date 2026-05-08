import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.transaction import Transaction
from core.uvm_authorization import create_uvm_authorization
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


class UvmBalanceTransferTests(unittest.TestCase):
    def test_execute_applies_authorized_balance_transfer(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        request_id = "casino-payout-1"
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    ["TRANSFER_FROM", source.address, receiver.address, request_id],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=100,
                authorizations=[
                    create_uvm_authorization(source, request_id).to_dict()
                ],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="execute authorized payout",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("7.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("3.0"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(
            receipt["balance_changes"],
            {
                source.address: "-3.0",
                receiver.address: "3.0",
            },
        )
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

    def test_execute_records_unsigned_balance_transfer_as_failed(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    [
                        "TRANSFER_FROM",
                        source.address,
                        receiver.address,
                        "casino-payout-1",
                    ],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=100,
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include failed unsigned transfer",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("10.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("0.0"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertFalse(receipt["success"])
        self.assertIn("not authorized", receipt["error"] or "")

    def test_execute_records_amount_limit_failure_and_burns_fuel(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        miner = create_wallet(name="miner")
        request_id = "casino-payout-1"
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        blockchain.mine_pending_transactions(
            miner_address=caller.address,
            description="fund caller",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    ["TRANSFER_FROM", source.address, receiver.address, request_id],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0.51"),
                gas_limit=100,
                gas_price=Decimal("0.01"),
                authorizations=[
                    create_uvm_authorization(
                        source,
                        request_id,
                        max_amount=Decimal("2"),
                    ).to_dict()
                ],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address=miner.address,
            description="include failed amount-limited transfer",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("10.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("0.0"))
        self.assertEqual(blockchain.get_balance(caller.address), Decimal("9.49"))
        self.assertEqual(blockchain.get_balance(miner.address), Decimal("10.51"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["gas_used"], 51)
        self.assertIn("exceeds amount limit", receipt["error"] or "")

    def test_execute_reverts_value_transfer_on_failed_run(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        blockchain.mine_pending_transactions(
            miner_address=caller.address,
            description="fund caller",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    [
                        "TRANSFER_FROM",
                        source.address,
                        receiver.address,
                        "casino-payout-1",
                    ],
                    ["HALT"],
                ],
                value=Decimal("2"),
                fee=Decimal("0.51"),
                gas_limit=100,
                gas_price=Decimal("0.01"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include failed value transfer",
        )

        self.assertEqual(blockchain.get_balance(caller.address), Decimal("9.49"))
        self.assertEqual(blockchain.get_balance("casino-contract"), Decimal("0.0"))
        self.assertEqual(blockchain.get_balance(source.address), Decimal("10.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("0.0"))

    def test_execute_accepts_authorization_scoped_to_next_block(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        request_id = "casino-payout-1"
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        current_height = blockchain.blocks[-1].block_id
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    ["TRANSFER_FROM", source.address, receiver.address, request_id],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=100,
                authorizations=[
                    create_uvm_authorization(
                        source,
                        request_id,
                        current_height=current_height,
                        valid_for_blocks=1,
                    ).to_dict()
                ],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="execute next-block payout",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("7.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("3.0"))

    def test_execute_rejects_expired_block_height_authorization(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        request_id = "casino-payout-1"
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        current_height = blockchain.blocks[-1].block_id
        authorization = create_uvm_authorization(
            source,
            request_id,
            current_height=current_height,
            valid_for_blocks=1,
        ).to_dict()
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="advance past authorization window",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="casino-contract",
                input_data=[
                    ["PUSH", 3],
                    ["TRANSFER_FROM", source.address, receiver.address, request_id],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0"),
                gas_limit=100,
                authorizations=[authorization],
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "expired at block"):
            blockchain.add_transaction(transaction)

        self.assertEqual(blockchain.get_balance(source.address), Decimal("10.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("0.0"))

    def test_execute_charges_exact_fuel_fee_for_sender_transfer(self) -> None:
        blockchain = create_blockchain()
        caller = create_wallet(name="caller")
        receiver = create_wallet(name="receiver")
        miner = create_wallet(name="miner")
        blockchain.mine_pending_transactions(
            miner_address=caller.address,
            description="fund caller",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="wallet-contract",
                input_data=[
                    ["PUSH", 2],
                    ["TRANSFER_FROM", caller.address, receiver.address, "self-pay"],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0.51"),
                gas_limit=100,
                gas_price=Decimal("0.01"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        blockchain.add_transaction(transaction)
        blockchain.mine_pending_transactions(
            miner_address=miner.address,
            description="execute paid self-transfer",
        )

        self.assertEqual(blockchain.get_balance(caller.address), Decimal("7.49"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("2.0"))
        self.assertEqual(blockchain.get_balance(miner.address), Decimal("10.51"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["gas_used"], 51)

    def test_execute_rejects_fuel_fee_mismatch(self) -> None:
        blockchain = create_blockchain()
        caller = create_wallet(name="caller")
        blockchain.mine_pending_transactions(
            miner_address=caller.address,
            description="fund caller",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address="wallet-contract",
                input_data=[
                    ["PUSH", 1],
                    ["HALT"],
                ],
                value=Decimal("0"),
                fee=Decimal("0.09"),
                gas_limit=100,
                gas_price=Decimal("0.10"),
                timestamp=datetime.now(),
                nonce=blockchain.get_next_nonce(caller.address),
                sender_public_key=caller.public_key,
            ),
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            blockchain.add_transaction(transaction)

        self.assertEqual(blockchain.get_balance(caller.address), Decimal("10.0"))


if __name__ == "__main__":
    unittest.main()
