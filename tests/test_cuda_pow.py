import hashlib
import os
import unittest
from unittest import mock

from core.block import Block
from core.block import proof_of_work
from core.cuda_pow import hash_prepared_prefix_with_nonce
from core.cuda_pow import prepare_prefix_context
from core.hashing import sha256_block_hash
from core.mining_scheduler import ChunkedMiningResult


class CudaPowPreparationTests(unittest.TestCase):
    def test_prepared_prefix_hash_matches_hashlib(self) -> None:
        cases = (
            ("1|||", 0),
            ("x" * 63, 17),
            ("y" * 64, 91),
            ("z" * 143 + "|tail|", 1234567890123),
        )

        for prefix, nonce in cases:
            with self.subTest(prefix_length=len(prefix), nonce=nonce):
                prepared_prefix = prepare_prefix_context(prefix)
                self.assertEqual(
                    hash_prepared_prefix_with_nonce(prepared_prefix, nonce),
                    hashlib.sha256((prefix + str(nonce)).encode("utf-8")).hexdigest(),
                )


class ProofOfWorkGpuOnlySettingTests(unittest.TestCase):
    @mock.patch("core.block.get_tuned_gpu_worker_count", return_value=1)
    @mock.patch("core.block.get_tuned_gpu_chunk_multiplier", return_value=1)
    @mock.patch("core.block.get_tuned_gpu_launch_config", return_value=(8, 256))
    @mock.patch("core.block.native_gpu_available", return_value=True)
    @mock.patch("core.block.run_chunked_mining")
    def test_cpu_worker_override_accepts_zero(
        self,
        run_chunked_mining: mock.Mock,
        _native_gpu_available: mock.Mock,
        _get_tuned_gpu_launch_config: mock.Mock,
        _get_tuned_gpu_chunk_multiplier: mock.Mock,
        _get_tuned_gpu_worker_count: mock.Mock,
    ) -> None:
        block = Block(
            block_id=1,
            transactions=[],
            hash_function=sha256_block_hash,
            description="gpu-only",
            previous_hash="0" * 64,
        )
        run_chunked_mining.return_value = ChunkedMiningResult(
            winner=(7, "0" * 64),
            attempts=8,
            elapsed=0.01,
            cancelled=False,
            gpu_failed=False,
        )

        with mock.patch.dict(os.environ, {"UNCCOIN_MINING_CPU_WORKERS": "0"}, clear=False):
            proof_of_work(block, difficulty_bits=0)

        self.assertEqual(run_chunked_mining.call_args.args[3], 0)
