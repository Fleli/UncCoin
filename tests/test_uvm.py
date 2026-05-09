import hashlib
import unittest
from decimal import Decimal

from core.contracts import build_nft_contract
from core.uvm import UvmExecutionContext
from core.uvm import execute_uvm_program
from wallet import create_wallet


def build_index(wallet, request_id: str):
    return {wallet.address: {request_id: {}}}


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

    def test_read_metadata_pushes_integer_metadata_value(self) -> None:
        wallet = create_wallet(name="metadata-owner")
        result = execute_uvm_program(
            [
                ["READ_METADATA", "deadline"],
                ["STORE", "deadline"],
                ["READ_METADATA", "hex_value"],
                ["STORE", "hex_value"],
                ["READ_METADATA", "owner"],
                ["STORE", "owner"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=400,
                metadata={
                    "deadline": 10,
                    "hex_value": "0x2a",
                    "owner": wallet.address,
                },
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.storage,
            {
                "deadline": 10,
                "hex_value": 42,
                "owner": int(wallet.address, 16),
            },
        )

    def test_read_input_and_transaction_sender_push_wallet_words(self) -> None:
        sender = create_wallet(name="sender")
        recipient = create_wallet(name="recipient")
        result = execute_uvm_program(
            [
                ["TX_SENDER"],
                ["STORE", "sender"],
                ["READ_INPUT", "recipient"],
                ["STORE", "recipient"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender=sender.address,
                contract_address="contract",
                gas_limit=300,
                input_data={"recipient": recipient.address},
            ),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.storage,
            {
                "sender": int(sender.address, 16),
                "recipient": int(recipient.address, 16),
            },
        )

    def test_nft_template_transfers_only_from_current_owner(self) -> None:
        owner = create_wallet(name="owner")
        recipient = create_wallet(name="recipient")
        intruder = create_wallet(name="intruder")
        program, metadata = build_nft_contract(
            name="Photo",
            description="Test image",
            image_data_uri="data:image/png;base64,abc",
            initial_owner=owner.address,
        )

        transfer_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender=owner.address,
                contract_address="contract",
                gas_limit=500,
                metadata=metadata,
                input_data={"recipient": recipient.address},
            ),
        )
        intruder_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender=intruder.address,
                contract_address="contract",
                gas_limit=500,
                metadata=metadata,
                storage=transfer_result.storage,
                input_data={"recipient": owner.address},
            ),
        )

        self.assertTrue(transfer_result.success, transfer_result.error)
        self.assertEqual(transfer_result.storage["owner"], int(recipient.address, 16))
        self.assertFalse(intruder_result.success)
        self.assertTrue(intruder_result.reverted)

    def test_read_metadata_rejects_missing_or_non_integer_value(self) -> None:
        missing_result = execute_uvm_program(
            [
                ["READ_METADATA", "missing"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
            ),
        )
        invalid_result = execute_uvm_program(
            [
                ["READ_METADATA", "name"],
                ["HALT"],
            ],
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=100,
                metadata={"name": "coinflip"},
            ),
        )

        self.assertFalse(missing_result.success)
        self.assertIn("missing metadata key missing", missing_result.error or "")
        self.assertFalse(invalid_result.success)
        self.assertIn("metadata key name must be an integer", invalid_result.error or "")

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

    def test_xor_mixes_words_bitwise(self) -> None:
        result = execute_uvm_program(
            [
                ["PUSH", 0b1010],
                ["PUSH", 0b1100],
                ["XOR"],
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
            (int(hashlib.sha256(b"6").hexdigest(), 16),),
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
        authorization_index = build_index(wallet, "casino-play-1")

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

    def test_has_reveal_allows_branching_before_reading_reveal(self) -> None:
        wallet = create_wallet(name="revealer")
        program = [
            ["HAS_REVEAL", wallet.address, "casino-play-1"],
            ["JUMPI", 5],
            ["PUSH", 0],
            ["STORE", "status"],
            ["HALT"],
            ["READ_REVEAL", wallet.address, "casino-play-1"],
            ["STORE", "seed"],
            ["HALT"],
        ]

        missing_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
            ),
        )
        revealed_result = execute_uvm_program(
            program,
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

        self.assertTrue(missing_result.success, missing_result.error)
        self.assertEqual(missing_result.storage, {"status": 0})
        self.assertTrue(revealed_result.success, revealed_result.error)
        self.assertEqual(revealed_result.storage, {"seed": 12345})

    def test_block_height_supports_deadline_branching(self) -> None:
        wallet = create_wallet(name="revealer")
        program = [
            ["HAS_REVEAL", wallet.address, "coinflip"],
            ["JUMPI", 12],
            ["BLOCK_HEIGHT"],
            ["PUSH", 10],
            ["GT"],
            ["JUMPI", 9],
            ["PUSH", 0],
            ["STORE", "status"],
            ["HALT"],
            ["PUSH", 2],
            ["STORE", "status"],
            ["HALT"],
            ["PUSH", 1],
            ["STORE", "status"],
            ["HALT"],
        ]

        early_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
                block_height=10,
            ),
        )
        expired_result = execute_uvm_program(
            program,
            UvmExecutionContext(
                tx_sender="caller",
                contract_address="contract",
                gas_limit=200,
                block_height=11,
            ),
        )

        self.assertTrue(early_result.success, early_result.error)
        self.assertEqual(early_result.storage, {"status": 0})
        self.assertTrue(expired_result.success, expired_result.error)
        self.assertEqual(expired_result.storage, {"status": 2})

    def test_transfer_from_debits_authorized_source_and_credits_receiver(self) -> None:
        source = create_wallet(name="source")
        receiver = create_wallet(name="receiver")
        authorization_index = build_index(source, "casino-payout-1")

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
                ["TRANSFER_FROM", "$CONTRACT", receiver.address, "contract-pay"],
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

    def test_require_auth_fails_without_matching_request_id(self) -> None:
        wallet = create_wallet(name="authorizer")
        authorization_index = build_index(wallet, "casino-play-1")

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
