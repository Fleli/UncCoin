import unittest
from datetime import datetime
from decimal import Decimal

from core.serialization import serialize_transaction
from core.transaction import TRANSACTION_KIND_COMMIT
from core.transaction import TRANSACTION_KIND_DEPLOY
from core.transaction import TRANSACTION_KIND_EXECUTE
from core.transaction import TRANSACTION_KIND_REVEAL
from core.transaction import TRANSACTION_KIND_TRANSFER
from core.transaction import TRANSACTION_VERSION_LEGACY
from core.transaction import TRANSACTION_VERSION_TYPED
from core.transaction import Transaction
from core.uvm_authorization import create_uvm_authorization
from wallet import create_wallet


class TransactionModelTests(unittest.TestCase):
    def test_transfer_constructor_builds_typed_payload(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")

        transaction = Transaction.transfer(
            sender="alice",
            receiver="bob",
            amount=Decimal("3.5"),
            fee=Decimal("0.1"),
            timestamp=timestamp,
            nonce=7,
        )

        self.assertEqual(transaction.version, TRANSACTION_VERSION_TYPED)
        self.assertEqual(transaction.kind, TRANSACTION_KIND_TRANSFER)
        self.assertEqual(
            transaction.payload,
            {
                "receiver": "bob",
                "amount": "3.5",
            },
        )

    def test_commit_constructor_records_request_id_and_hash(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")

        transaction = Transaction.commit(
            sender="alice",
            request_id="lottery-round-1",
            commitment_hash="a" * 64,
            fee=Decimal("0.1"),
            timestamp=timestamp,
            nonce=3,
        )

        self.assertEqual(transaction.kind, TRANSACTION_KIND_COMMIT)
        self.assertEqual(transaction.receiver, "")
        self.assertEqual(transaction.amount, Decimal("0.0"))
        self.assertEqual(
            transaction.payload,
            {
                "request_id": "lottery-round-1",
                "commitment_hash": "a" * 64,
            },
        )

    def test_reveal_constructor_records_request_id_seed_and_salt(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")

        transaction = Transaction.reveal(
            sender="alice",
            request_id="lottery-round-1",
            seed="42",
            salt="salt",
            fee=Decimal("0.1"),
            timestamp=timestamp,
            nonce=4,
        )

        self.assertEqual(transaction.kind, TRANSACTION_KIND_REVEAL)
        self.assertEqual(transaction.receiver, "")
        self.assertEqual(transaction.amount, Decimal("0.0"))
        self.assertEqual(
            transaction.payload,
            {
                "request_id": "lottery-round-1",
                "seed": "42",
                "salt": "salt",
            },
        )

    def test_deploy_constructor_records_program_and_metadata(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")
        program = [
            ["PUSH", 7],
            ["STORE", "number"],
            ["HALT"],
        ]
        metadata = {
            "name": "number-store",
            "request_ids": ["casino-play-1"],
        }

        transaction = Transaction.deploy(
            sender="alice",
            contract_address="contract-number-store",
            program=program,
            metadata=metadata,
            fee=Decimal("0.1"),
            timestamp=timestamp,
            nonce=5,
        )

        self.assertEqual(transaction.kind, TRANSACTION_KIND_DEPLOY)
        self.assertEqual(transaction.receiver, "contract-number-store")
        self.assertEqual(transaction.amount, Decimal("0.0"))
        self.assertEqual(
            transaction.payload,
            {
                "contract_address": "contract-number-store",
                "program": program,
                "metadata": metadata,
            },
        )

    def test_execute_constructor_carries_future_uvm_payload(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")
        wallet = create_wallet(name="authorizer")
        authorization = create_uvm_authorization(wallet, "casino-play-1").to_dict()

        transaction = Transaction.execute(
            sender="alice",
            contract_address="contract-1",
            input_data="010203",
            value=Decimal("2"),
            fee=Decimal("0.2"),
            gas_limit=50_000,
            authorizations=[authorization],
            timestamp=timestamp,
            nonce=4,
        )

        self.assertEqual(transaction.kind, TRANSACTION_KIND_EXECUTE)
        self.assertEqual(transaction.receiver, "contract-1")
        self.assertEqual(transaction.amount, Decimal("2"))
        self.assertEqual(
            transaction.payload,
            {
                "contract_address": "contract-1",
                "input": "010203",
                "value": "2",
                "gas_limit": 50_000,
                "authorizations": [authorization],
            },
        )

    def test_payload_serialization_is_canonical(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-07T10:00:00")

        left = Transaction(
            sender="alice",
            receiver="",
            amount=Decimal("0"),
            fee=Decimal("0"),
            timestamp=timestamp,
            kind=TRANSACTION_KIND_COMMIT,
            payload={"b": 2, "a": {"d": 4, "c": 3}},
        )
        right = Transaction(
            sender="alice",
            receiver="",
            amount=Decimal("0"),
            fee=Decimal("0"),
            timestamp=timestamp,
            kind=TRANSACTION_KIND_COMMIT,
            payload={"a": {"c": 3, "d": 4}, "b": 2},
        )

        self.assertEqual(left.canonical_payload(), right.canonical_payload())
        self.assertEqual(serialize_transaction(left), serialize_transaction(right))

    def test_legacy_transactions_keep_legacy_signing_payload(self) -> None:
        transaction = Transaction.from_dict(
            {
                "sender": "alice",
                "receiver": "bob",
                "amount": "1.5",
                "fee": "0.1",
                "timestamp": "2026-05-07T10:00:00",
                "nonce": 2,
                "sender_public_key": None,
                "signature": "abc",
            }
        )

        self.assertEqual(transaction.version, TRANSACTION_VERSION_LEGACY)
        self.assertEqual(
            transaction.signing_payload(),
            "alice|bob|1.5|0.1|2|2026-05-07T10:00:00",
        )
        self.assertEqual(
            serialize_transaction(transaction),
            "alice|bob|1.5|0.1|2026-05-07T10:00:00|2||abc",
        )


if __name__ == "__main__":
    unittest.main()
