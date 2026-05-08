import unittest

from core.uvm_authorization import UvmAuthorizationScope
from core.uvm_authorization import is_request_authorized


class UvmAuthorizationTests(unittest.TestCase):
    def test_authorization_index_checks_wallet_and_request_id(self) -> None:
        authorization_index = {
            "alice": {
                "casino-play-1": {},
                "casino-play-2": {},
            },
            "bob": {
                "casino-play-1": {},
            },
        }

        self.assertTrue(
            is_request_authorized(
                authorization_index,
                "alice",
                "casino-play-1",
            )
        )
        self.assertFalse(
            is_request_authorized(
                authorization_index,
                "bob",
                "casino-play-2",
            )
        )

    def test_authorization_index_supports_legacy_request_id_lists(self) -> None:
        authorization_index = {"alice": ["casino-play-1"]}

        self.assertTrue(
            is_request_authorized(
                authorization_index,
                "alice",
                "casino-play-1",
            )
        )
        self.assertFalse(
            is_request_authorized(
                authorization_index,
                "alice",
                "casino-play-2",
            )
        )

    def test_scope_validates_height_window(self) -> None:
        scope = UvmAuthorizationScope.from_dict(
            {
                "valid_from_height": 8,
                "valid_until_height": 9,
            }
        )

        self.assertIsNone(scope.validation_error(block_height=8))
        self.assertIsNone(scope.validation_error(block_height=9))
        self.assertEqual(
            scope.validation_error(block_height=7),
            "authorization is not valid until block 8",
        )
        self.assertEqual(
            scope.validation_error(block_height=10),
            "authorization expired at block 9",
        )

    def test_scope_rejects_invalid_height_window(self) -> None:
        scope = UvmAuthorizationScope.from_dict(
            {
                "valid_from_height": 9,
                "valid_until_height": 8,
            }
        )

        self.assertEqual(
            scope.validation_error(),
            "scope.valid_until_height must be greater than or equal to valid_from_height",
        )

    def test_scope_rejects_non_integer_heights(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope.valid_from_height"):
            UvmAuthorizationScope.from_dict({"valid_from_height": "soon"})


if __name__ == "__main__":
    unittest.main()
