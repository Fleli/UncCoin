import unittest
from unittest import mock

from core.block import Block
from core.block import proof_of_work
from core.hashing import sha256_block_hash


class MiningBackendTests(unittest.TestCase):
    def test_python_backend_mines_valid_block(self) -> None:
        block = Block(1, [], sha256_block_hash, "python", "0")

        proof_of_work(block, difficulty_bits=4, mining_backend="python")

        self.assertTrue(block.block_hash.startswith("0"))
        self.assertIsNotNone(block.nonces_checked)
        self.assertEqual(block.block_hash, sha256_block_hash(block))

    def test_auto_backend_falls_back_to_python_when_native_is_unavailable(self) -> None:
        block = Block(1, [], sha256_block_hash, "fallback", "0")

        with mock.patch(
            "core.block._native_proof_of_work",
            side_effect=RuntimeError("native unavailable"),
        ):
            proof_of_work(block, difficulty_bits=4, mining_backend="auto")

        self.assertTrue(block.block_hash.startswith("0"))
        self.assertIsNotNone(block.nonces_checked)
        self.assertEqual(block.block_hash, sha256_block_hash(block))

    def test_auto_backend_uses_python_when_native_is_not_built(self) -> None:
        block = Block(1, [], sha256_block_hash, "not built", "0")

        with mock.patch("core.block.platform.system", return_value="Darwin"):
            with mock.patch("core.block.native_extension_built", return_value=False):
                with mock.patch("core.block._native_proof_of_work") as native_proof:
                    proof_of_work(block, difficulty_bits=4, mining_backend="auto")

        native_proof.assert_not_called()
        self.assertTrue(block.block_hash.startswith("0"))
        self.assertEqual(block.block_hash, sha256_block_hash(block))


if __name__ == "__main__":
    unittest.main()
