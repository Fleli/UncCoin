import unittest

from core.uvm_authorization import authorization_signing_payload
from core.uvm_authorization import build_authorization_index
from core.uvm_authorization import create_uvm_authorization
from core.uvm_authorization import is_request_authorized
from wallet import create_wallet


CONTRACT_ADDRESS = "contract"
CODE_HASH = "a" * 64


def create_authorization(wallet, request_id: str, **kwargs):
    return create_uvm_authorization(
        wallet,
        request_id,
        contract_address=CONTRACT_ADDRESS,
        code_hash=CODE_HASH,
        **kwargs,
    )


def build_index(authorizations, **kwargs):
    return build_authorization_index(
        authorizations,
        contract_address=CONTRACT_ADDRESS,
        code_hash=CODE_HASH,
        **kwargs,
    )


class UvmAuthorizationTests(unittest.TestCase):
    def test_build_authorization_index_groups_request_ids_by_wallet(self) -> None:
        alice = create_wallet(name="alice")
        bob = create_wallet(name="bob")
        authorizations = [
            create_authorization(alice, "casino-play-2").to_dict(),
            create_authorization(bob, "casino-play-1").to_dict(),
            create_authorization(alice, "casino-play-1").to_dict(),
        ]

        authorization_index = build_index(authorizations)

        self.assertEqual(
            authorization_index,
            {
                alice.address: {
                    "casino-play-1": {},
                    "casino-play-2": {},
                },
                bob.address: {
                    "casino-play-1": {},
                },
            },
        )
        self.assertTrue(
            is_request_authorized(
                authorization_index,
                alice.address,
                "casino-play-1",
            )
        )
        self.assertFalse(
            is_request_authorized(
                authorization_index,
                bob.address,
                "casino-play-2",
            )
        )

    def test_duplicate_authorizations_are_deduplicated(self) -> None:
        alice = create_wallet(name="alice")
        authorization = create_authorization(alice, "casino-play-1").to_dict()

        authorization_index = build_index([authorization, authorization])

        self.assertEqual(
            authorization_index,
            {alice.address: {"casino-play-1": {}}},
        )

    def test_scoped_authorization_includes_height_window_in_signed_payload(self) -> None:
        alice = create_wallet(name="alice")
        authorization = create_authorization(
            alice,
            "casino-play-1",
            valid_from_height=2,
            valid_until_height=5,
        ).to_dict()

        self.assertEqual(
            authorization["scope"],
            {
                "valid_from_height": 2,
                "valid_until_height": 5,
            },
        )
        authorization_index = build_index(
            [authorization],
            block_height=3,
        )
        self.assertEqual(
            authorization_index,
            {
                alice.address: {
                    "casino-play-1": {
                        "valid_from_height": 2,
                        "valid_until_height": 5,
                    }
                }
            },
        )

        authorization["scope"]["valid_until_height"] = 6
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_index([authorization], block_height=3)

    def test_valid_for_blocks_scope_uses_next_block_window(self) -> None:
        alice = create_wallet(name="alice")
        authorization = create_authorization(
            alice,
            "casino-play-1",
            current_height=7,
            valid_for_blocks=2,
        ).to_dict()

        self.assertEqual(
            authorization["scope"],
            {
                "valid_from_height": 8,
                "valid_until_height": 9,
            },
        )
        self.assertTrue(
            is_request_authorized(
                build_index([authorization], block_height=8),
                alice.address,
                "casino-play-1",
            )
        )
        self.assertTrue(
            is_request_authorized(
                build_index([authorization], block_height=9),
                alice.address,
                "casino-play-1",
            )
        )
        with self.assertRaisesRegex(ValueError, "not valid until block 8"):
            build_index([authorization], block_height=7)
        with self.assertRaisesRegex(ValueError, "expired at block 9"):
            build_index([authorization], block_height=10)

    def test_contract_and_code_hash_are_part_of_signed_payload(self) -> None:
        alice = create_wallet(name="alice")
        authorization = create_authorization(alice, "casino-play-1").to_dict()

        with self.assertRaisesRegex(ValueError, "contract_address does not match"):
            build_authorization_index(
                [authorization],
                contract_address="other-contract",
                code_hash=CODE_HASH,
            )
        with self.assertRaisesRegex(ValueError, "code_hash does not match"):
            build_authorization_index(
                [authorization],
                contract_address=CONTRACT_ADDRESS,
                code_hash="b" * 64,
            )

    def test_invalid_signature_is_rejected(self) -> None:
        alice = create_wallet(name="alice")
        mallory = create_wallet(name="mallory")
        invalid_authorization = create_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["signature"] = mallory.sign_message(
            authorization_signing_payload(
                alice.address,
                CONTRACT_ADDRESS,
                CODE_HASH,
                "casino-play-1",
            )
        )

        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_index([invalid_authorization])

    def test_public_key_must_match_wallet(self) -> None:
        alice = create_wallet(name="alice")
        mallory = create_wallet(name="mallory")
        invalid_authorization = create_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["public_key"] = {
            "exponent": str(mallory.public_key[0]),
            "modulus": str(mallory.public_key[1]),
        }

        with self.assertRaisesRegex(ValueError, "wallet does not match public key"):
            build_index([invalid_authorization])

    def test_request_id_is_part_of_signed_payload(self) -> None:
        alice = create_wallet(name="alice")
        invalid_authorization = create_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["request_id"] = "casino-play-2"

        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_index([invalid_authorization])


if __name__ == "__main__":
    unittest.main()
