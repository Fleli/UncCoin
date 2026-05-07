import unittest

from core.uvm_authorization import authorization_signing_payload
from core.uvm_authorization import build_authorization_index
from core.uvm_authorization import create_uvm_authorization
from core.uvm_authorization import is_request_authorized
from wallet import create_wallet


class UvmAuthorizationTests(unittest.TestCase):
    def test_build_authorization_index_groups_request_ids_by_wallet(self) -> None:
        alice = create_wallet(name="alice")
        bob = create_wallet(name="bob")
        authorizations = [
            create_uvm_authorization(alice, "casino-play-2").to_dict(),
            create_uvm_authorization(bob, "casino-play-1").to_dict(),
            create_uvm_authorization(alice, "casino-play-1").to_dict(),
        ]

        authorization_index = build_authorization_index(authorizations)

        self.assertEqual(
            authorization_index,
            {
                alice.address: ["casino-play-1", "casino-play-2"],
                bob.address: ["casino-play-1"],
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
        authorization = create_uvm_authorization(alice, "casino-play-1").to_dict()

        authorization_index = build_authorization_index([authorization, authorization])

        self.assertEqual(
            authorization_index,
            {alice.address: ["casino-play-1"]},
        )

    def test_invalid_signature_is_rejected(self) -> None:
        alice = create_wallet(name="alice")
        mallory = create_wallet(name="mallory")
        invalid_authorization = create_uvm_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["signature"] = mallory.sign_message(
            authorization_signing_payload(alice.address, "casino-play-1")
        )

        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_authorization_index([invalid_authorization])

    def test_public_key_must_match_wallet(self) -> None:
        alice = create_wallet(name="alice")
        mallory = create_wallet(name="mallory")
        invalid_authorization = create_uvm_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["public_key"] = {
            "exponent": str(mallory.public_key[0]),
            "modulus": str(mallory.public_key[1]),
        }

        with self.assertRaisesRegex(ValueError, "wallet does not match public key"):
            build_authorization_index([invalid_authorization])

    def test_request_id_is_part_of_signed_payload(self) -> None:
        alice = create_wallet(name="alice")
        invalid_authorization = create_uvm_authorization(alice, "casino-play-1").to_dict()
        invalid_authorization["request_id"] = "casino-play-2"

        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            build_authorization_index([invalid_authorization])


if __name__ == "__main__":
    unittest.main()
