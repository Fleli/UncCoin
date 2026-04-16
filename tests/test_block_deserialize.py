import unittest
from unittest import mock

from core.block import Block


class BlockDeserializeTests(unittest.TestCase):
    def test_from_dict_uses_provided_block_hash_without_rehashing(self) -> None:
        hash_function = mock.Mock(return_value="rehash-should-not-run")

        block = Block.from_dict(
            {
                "block_id": 7,
                "transactions": [],
                "description": "sync block",
                "previous_hash": "a" * 64,
                "nonce": 3,
                "block_hash": "b" * 64,
            },
            hash_function=hash_function,
        )

        self.assertEqual(block.block_id, 7)
        self.assertEqual(block.block_hash, "b" * 64)
        hash_function.assert_not_called()
