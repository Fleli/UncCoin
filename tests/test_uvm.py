import hashlib
import unittest
from decimal import Decimal

from core.uvm import UvmExecutionContext
from core.uvm import execute_uvm_program
from core.uvm_authorization import build_authorization_index
from core.uvm_authorization import create_uvm_authorization
from wallet import create_wallet


class UvmExecutionTests(unittest.TestCase):
    def test_arithmetic_and_storage(self) -> None:
        result = execute_uvm_program(
            [
                ["PUSH", 2],
                ["PUSH", 3],
                ["ADD"],
                ["STORE", "sum"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"sum": 5})
        self.assertEqual(result.gas_used, 105)
        self.assertFalse(result.used_all_gas)

    def test_memory_is_transient_and_separate_from_storage(self) -> None:
        result = execute_uvm_program(
            """
            PUSH 9
            MEM_STORE temp
            MEM_LOAD temp
            STORE persisted
            HALT
            """,
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.memory, {"temp": 9})
        self.assertEqual(result.storage, {"persisted": 9})

    def test_sha256_hashes_stack_value_to_integer(self) -> None:
        result = execute_uvm_program(
            [
                ["PUSH", 123],
                ["SHA256"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=30,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.stack,
            (int(hashlib.sha256(b"123").hexdigest(), 16),),
        )

    def test_conditional_jump(self) -> None:
        result = execute_uvm_program(
            [
                ["PUSH", 1],
                ["JUMPI", 4],
                ["PUSH", 999],
                ["STORE", "result"],
                ["PUSH", 42],
                ["STORE", "result"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"result": 42})

    def test_out_of_gas_is_reported(self) -> None:
        result = execute_uvm_program(
            [
                ["PUSH", 1],
                ["STORE", "value"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
            ),
        )

        self.assertFalse(result.success)
        self.assertTrue(result.gas_exhausted)
        self.assertTrue(result.used_all_gas)
        self.assertEqual(result.gas_remaining, 0)

    def test_read_commit_requires_authorization(self) -> None:
        wallet = create_wallet(name="authorizer")
        result = execute_uvm_program(
            [
                ["READ_COMMIT", wallet.address, "casino-play-1"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                commitments={
                    "casino-play-1": {
                        wallet.address: "a" * 64,
                    }
                },
                authorization_index={},
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("not authorized", result.error or "")

    def test_read_commit_pushes_authorized_commitment_hash_as_integer(self) -> None:
        wallet = create_wallet(name="authorizer")
        authorization_index = build_authorization_index(
            [create_uvm_authorization(wallet, "casino-play-1")]
        )

        result = execute_uvm_program(
            [
                ["HAS_AUTH", wallet.address, "casino-play-1"],
                ["STORE", "has_auth"],
                ["READ_COMMIT", wallet.address, "casino-play-1"],
                ["STORE", "commitment"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=300,
                commitments={
                    "casino-play-1": {
                        wallet.address: "b" * 64,
                    }
                },
                authorization_index=authorization_index,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage["has_auth"], 1)
        self.assertEqual(result.storage["commitment"], int("b" * 64, 16))

    def test_read_reveal_pushes_revealed_seed_without_extra_authorization(self) -> None:
        wallet = create_wallet(name="revealer")

        result = execute_uvm_program(
            [
                ["READ_REVEAL", wallet.address, "casino-play-1"],
                ["STORE", "seed"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
                reveals={
                    "casino-play-1": {
                        wallet.address: {
                            "seed": "12345",
                            "salt": "salt",
                            "commitment_hash": "c" * 64,
                        }
                    }
                },
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.storage, {"seed": 12345})

    def test_transfer_from_debits_authorized_source_and_credits_receiver(self) -> None:
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        authorization_index = build_authorization_index(
            [create_uvm_authorization(source, "casino-payout-1")]
        )

        result = execute_uvm_program(
            [
                ["PUSH", 4],
                ["TRANSFER_FROM", source.address, receiver.address, "casino-payout-1"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                balances={source.address: Decimal("10")},
                authorization_index=authorization_index,
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.balance_changes,
            {
                source.address: Decimal("-4"),
                receiver.address: Decimal("4"),
            },
        )
        self.assertEqual(
            result.transfers,
            (
                {
                    "source": source.address,
                    "receiver": receiver.address,
                    "amount": "4",
                    "request_id": "casino-payout-1",
                },
            ),
        )

    def test_transfer_from_rejects_missing_source_authorization(self) -> None:
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")

        result = execute_uvm_program(
            [
                ["PUSH", 4],
                ["TRANSFER_FROM", source.address, receiver.address, "casino-payout-1"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                balances={source.address: Decimal("10")},
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("not authorized", result.error or "")

    def test_transfer_from_allows_transaction_sender_without_extra_authorization(self) -> None:
        sender = create_wallet(name="sender")
        receiver = create_wallet(name="receiver")

        result = execute_uvm_program(
            [
                ["PUSH", 4],
                ["TRANSFER_FROM", sender.address, receiver.address, "self-pay"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender=sender.address,
                contract_address="contract",
                gas_limit=100,
                balances={sender.address: Decimal("10")},
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.balance_changes[sender.address], Decimal("-4"))
        self.assertEqual(result.balance_changes[receiver.address], Decimal("4"))

    def test_transfer_from_allows_contract_balance_without_extra_authorization(self) -> None:
        receiver = create_wallet(name="receiver")

        result = execute_uvm_program(
            [
                ["PUSH", 4],
                ["TRANSFER_FROM", "contract", receiver.address, "contract-pay"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                balances={"contract": Decimal("10")},
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.balance_changes["contract"], Decimal("-4"))
        self.assertEqual(result.balance_changes[receiver.address], Decimal("4"))

    def test_transfer_from_enforces_authorization_amount_limit_cumulatively(self) -> None:
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        authorization_index = build_authorization_index(
            [
                create_uvm_authorization(
                    source,
                    "limited-payout",
                    max_amount=Decimal("5"),
                ).to_dict()
            ]
        )

        result = execute_uvm_program(
            [
                ["PUSH", 3],
                ["TRANSFER_FROM", source.address, receiver.address, "limited-payout"],
                ["PUSH", 3],
                ["TRANSFER_FROM", source.address, receiver.address, "limited-payout"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
                balances={source.address: Decimal("10")},
                authorization_index=authorization_index,
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("exceeds amount limit 5", result.error or "")

    def test_require_auth_fails_without_matching_request_id(self) -> None:
        wallet = create_wallet(name="authorizer")
        authorization_index = build_authorization_index(
            [create_uvm_authorization(wallet, "casino-play-1")]
        )

        result = execute_uvm_program(
            [
                ["REQUIRE_AUTH", wallet.address, "casino-play-2"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                authorization_index=authorization_index,
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("not authorized", result.error or "")

    def test_revert_is_distinct_from_gas_exhaustion(self) -> None:
        result = execute_uvm_program(
            [
                ["REVERT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
            ),
        )

        self.assertFalse(result.success)
        self.assertTrue(result.reverted)
        self.assertFalse(result.gas_exhausted)


if __name__ == "__main__":
    unittest.main()
