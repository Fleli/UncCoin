import unittest
from datetime import datetime
from decimal import Decimal

from core.blockchain import Blockchain
from core.contracts import compute_contract_code_hash
from core.genesis import create_genesis_block
from core.hashing import sha256_block_hash
from core.hashing import sha256_transaction_hash
from core.transaction import Transaction
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


def create_authorization_transaction(
    wallet,
    request_id: str,
    contract_address: str,
    program,
    blockchain: Blockchain,
    scope: dict | None = None,
) -> Transaction:
    return sign_transaction(
        wallet,
        Transaction.authorize(
            sender=wallet.address,
            contract_address=contract_address,
            code_hash=compute_contract_code_hash(program, {}),
            request_id=request_id,
            scope=scope or {},
            fee=Decimal("0"),
            timestamp=datetime.now(),
            nonce=blockchain.get_next_nonce(wallet.address),
            sender_public_key=wallet.public_key,
        ),
    )


class UvmBalanceTransferTests(unittest.TestCase):
    def test_execute_applies_authorized_balance_transfer(self) -> None:
        blockchain = create_blockchain()
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        caller = create_wallet(name="caller")
        request_id = "casino-payout-1"
        contract_address = "casino-contract"
        program = [
            ["PUSH", 3],
            ["TRANSFER_FROM", source.address, receiver.address, request_id],
            ["HALT"],
        ]
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        blockchain.add_transaction(
            create_authorization_transaction(
                source,
                request_id,
                contract_address,
                program,
                blockchain,
            )
        )
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="authorize payout",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address=contract_address,
                input_data=program,
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
                fee=Decimal("1.00"),
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
        contract_address = "casino-contract"
        program = [
            ["PUSH", 3],
            ["TRANSFER_FROM", source.address, receiver.address, request_id],
            ["HALT"],
        ]
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        current_height = blockchain.blocks[-1].block_id
        blockchain.add_transaction(
            create_authorization_transaction(
                source,
                request_id,
                contract_address,
                program,
                blockchain,
                scope={
                    "valid_from_height": current_height + 1,
                    "valid_until_height": current_height + 1,
                },
            )
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address=contract_address,
                input_data=program,
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
        contract_address = "casino-contract"
        program = [
            ["PUSH", 3],
            ["TRANSFER_FROM", source.address, receiver.address, request_id],
            ["HALT"],
        ]
        blockchain.mine_pending_transactions(
            miner_address=source.address,
            description="fund source",
        )
        current_height = blockchain.blocks[-1].block_id
        blockchain.add_transaction(
            create_authorization_transaction(
                source,
                request_id,
                contract_address,
                program,
                blockchain,
                scope={
                    "valid_from_height": current_height + 1,
                    "valid_until_height": current_height + 1,
                },
            )
        )
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="include short authorization",
        )
        blockchain.mine_pending_transactions(
            miner_address="miner",
            description="advance past authorization window",
        )
        transaction = sign_transaction(
            caller,
            Transaction.execute(
                sender=caller.address,
                contract_address=contract_address,
                input_data=program,
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
            description="execute with expired authorization",
        )

        self.assertEqual(blockchain.get_balance(source.address), Decimal("10.0"))
        self.assertEqual(blockchain.get_balance(receiver.address), Decimal("0.0"))
        receipt = blockchain.get_uvm_receipt(sha256_transaction_hash(transaction))
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertFalse(receipt["success"])
        self.assertIn("not authorized", receipt["error"] or "")

    def test_execute_refunds_unused_fuel_escrow_for_sender_transfer(self) -> None:
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
                fee=Decimal("1.00"),
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
        self.assertEqual(receipt["fee_escrowed"], "1.00")
        self.assertEqual(receipt["fee_paid"], "0.51")
        self.assertEqual(receipt["fee_refunded"], "0.49")

    def test_execute_rejects_insufficient_fuel_escrow(self) -> None:
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

        with self.assertRaisesRegex(ValueError, "below maximum fuel cost"):
            blockchain.add_transaction(transaction)

        self.assertEqual(blockchain.get_balance(caller.address), Decimal("10.0"))


if __name__ == "__main__":
    unittest.main()
