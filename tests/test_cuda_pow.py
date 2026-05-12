import hashlib
import os
import unittest
from unittest import mock

from core.block import Block
from core.block import mine_serialized_block_prefix_resident
from core.block import proof_of_work
from core.cuda_pow import _mine_pow_gpu_range
from core.cuda_pow import _prepare_single_block_words
from core.cuda_pow import _resolve_cuda_dispatch_window
from core.cuda_pow import hash_prepared_prefix_with_nonce
from core.cuda_pow import mine_pow_gpu
from core.cuda_pow import prepare_prefix_context
from core.hashing import sha256_block_hash
from core.mining_scheduler import ChunkedMiningResult
from core.mining_scheduler import get_gpu_device_ids
from core.mining_scheduler import run_chunked_mining


class _FakeCupyArray:
    def __init__(self, values) -> None:
        self._values = list(values)

    def get(self) -> list[int]:
        return self._values


class _FakeCupy:
    uint32 = int
    uint8 = int
    uint64 = int

    @staticmethod
    def asarray(values, dtype=None) -> _FakeCupyArray:
        del dtype
        return _FakeCupyArray(values)


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

    def test_single_block_words_only_apply_when_nonce_and_padding_fit(self) -> None:
        self.assertIsNotNone(
            _prepare_single_block_words(
                prepare_prefix_context("x" * 53),
                2,
            )
        )
        self.assertIsNone(
            _prepare_single_block_words(
                prepare_prefix_context("x" * 54),
                2,
            )
        )


class CudaPowDispatchWindowTests(unittest.TestCase):
    def test_resolve_dispatch_window_clamps_to_digit_boundary(self) -> None:
        self.assertEqual(_resolve_cuda_dispatch_window(98, 10, 10, 1), (2, 2))

    def test_resolve_dispatch_window_skips_fixed_digits_for_non_unit_step(self) -> None:
        self.assertEqual(_resolve_cuda_dispatch_window(98, 10, 10, 2), (10, None))


class CudaPowKernelSelectionTests(unittest.TestCase):
    def test_gpu_mining_without_progress_stays_in_one_resident_range_call(self) -> None:
        with mock.patch(
            "core.cuda_pow._mine_pow_gpu_range",
            return_value=(77, "0" * 64, True, False, 78),
        ) as mine_range:
            result = mine_pow_gpu(
                "prefix|",
                difficulty_bits=30,
                start_nonce=0,
                progress_interval=0,
                batch_size=12345,
                nonces_per_thread=16,
                threads_per_group=256,
                device_id=0,
            )

        self.assertEqual(result, (77, "0" * 64, False))
        mine_range.assert_called_once()
        self.assertGreater(mine_range.call_args.kwargs["max_attempts"], 12345)
        self.assertEqual(mine_range.call_args.kwargs["batch_size"], 12345)

    def test_gpu_range_uses_fixed_digit_kernel_within_digit_band(self) -> None:
        fake_cupy = _FakeCupy()
        kernel_calls: list[tuple[str, int, int]] = []

        def generic_kernel(grid, block, args) -> None:
            del grid, block, args
            self.fail("generic kernel should not be used for a fixed-digit batch")

        def fixed_digits_kernel(grid, block, args) -> None:
            del grid, block
            kernel_calls.append(("fixed", int(args[6]), int(args[8])))

        def single_block_fixed_digits_kernel(grid, block, args) -> None:
            del grid, block, args
            self.fail("single-block kernel should not be used when padding spills")

        with mock.patch("core.cuda_pow.gpu_available", return_value=True):
            with mock.patch("core.cuda_pow._load_cupy", return_value=fake_cupy):
                with mock.patch(
                    "core.cuda_pow._get_kernels",
                    return_value=(
                        generic_kernel,
                        fixed_digits_kernel,
                        single_block_fixed_digits_kernel,
                    ),
                ):
                    prefix = "x" * 54
                    result = _mine_pow_gpu_range(
                        prefix_bytes=prefix.encode("utf-8"),
                        prepared_prefix=prepare_prefix_context(prefix),
                        difficulty_bits=1,
                        start_nonce=98,
                        max_attempts=2,
                        batch_size=10,
                        nonce_step=1,
                        nonces_per_thread=4,
                        threads_per_group=8,
                    )

        self.assertEqual(kernel_calls, [("fixed", 2, 2)])
        self.assertEqual(result, (99, "", False, False, 2))

    def test_gpu_range_uses_single_block_kernel_when_nonce_and_padding_fit(self) -> None:
        fake_cupy = _FakeCupy()
        kernel_calls: list[tuple[str, int, int, int]] = []

        def generic_kernel(grid, block, args) -> None:
            del grid, block, args
            self.fail("generic kernel should not be used for a fixed-digit batch")

        def fixed_digits_kernel(grid, block, args) -> None:
            del grid, block, args
            self.fail("full fixed-digit kernel should not be used when one block fits")

        def single_block_fixed_digits_kernel(grid, block, args) -> None:
            del grid, block
            kernel_calls.append(("single", int(args[2]), int(args[5]), int(args[7])))

        with mock.patch("core.cuda_pow.gpu_available", return_value=True):
            with mock.patch("core.cuda_pow._load_cupy", return_value=fake_cupy):
                with mock.patch(
                    "core.cuda_pow._get_kernels",
                    return_value=(
                        generic_kernel,
                        fixed_digits_kernel,
                        single_block_fixed_digits_kernel,
                    ),
                ):
                    result = _mine_pow_gpu_range(
                        prefix_bytes=b"prefix|",
                        prepared_prefix=prepare_prefix_context("prefix|"),
                        difficulty_bits=1,
                        start_nonce=98,
                        max_attempts=2,
                        batch_size=10,
                        nonce_step=1,
                        nonces_per_thread=4,
                        threads_per_group=8,
                    )

        self.assertEqual(kernel_calls, [("single", 7, 2, 2)])
        self.assertEqual(result, (99, "", False, False, 2))

    def test_gpu_range_uses_generic_kernel_when_nonce_step_is_not_one(self) -> None:
        fake_cupy = _FakeCupy()
        kernel_calls: list[tuple[str, int, int]] = []

        def generic_kernel(grid, block, args) -> None:
            del grid, block
            kernel_calls.append(("generic", int(args[6]), int(args[7])))

        def fixed_digits_kernel(grid, block, args) -> None:
            del grid, block, args
            self.fail("fixed-digit kernel should not be used for stepped nonces")

        with mock.patch("core.cuda_pow.gpu_available", return_value=True):
            with mock.patch("core.cuda_pow._load_cupy", return_value=fake_cupy):
                with mock.patch(
                    "core.cuda_pow._get_kernels",
                    return_value=(generic_kernel, fixed_digits_kernel, fixed_digits_kernel),
                ):
                    result = _mine_pow_gpu_range(
                        prefix_bytes=b"prefix|",
                        prepared_prefix=prepare_prefix_context("prefix|"),
                        difficulty_bits=1,
                        start_nonce=98,
                        max_attempts=4,
                        batch_size=10,
                        nonce_step=2,
                        nonces_per_thread=4,
                        threads_per_group=8,
                    )

        self.assertEqual(kernel_calls, [("generic", 2, 4)])
        self.assertEqual(result, (104, "", False, False, 4))


class MiningSchedulerGpuDeviceSelectionTests(unittest.TestCase):
    @mock.patch("core.mining_scheduler.native_gpu_device_ids", return_value=(0, 1, 2))
    def test_gpu_device_ids_default_to_all_visible_devices(
        self,
        _native_gpu_device_ids: mock.Mock,
    ) -> None:
        self.assertEqual(get_gpu_device_ids(), (0, 1, 2))

    @mock.patch("core.mining_scheduler.native_gpu_device_ids", return_value=(0, 1, 2))
    def test_gpu_device_ids_accept_explicit_selection(
        self,
        _native_gpu_device_ids: mock.Mock,
    ) -> None:
        with mock.patch.dict(os.environ, {"UNCCOIN_GPU_DEVICE_IDS": "2, 0, 2"}, clear=False):
            self.assertEqual(get_gpu_device_ids(), (2, 0))

    @mock.patch("core.mining_scheduler.native_gpu_device_ids", return_value=(0, 1, 2))
    def test_gpu_device_ids_reject_unavailable_devices(
        self,
        _native_gpu_device_ids: mock.Mock,
    ) -> None:
        with mock.patch.dict(os.environ, {"UNCCOIN_GPU_DEVICE_IDS": "1, 4"}, clear=False):
            with self.assertRaises(ValueError):
                get_gpu_device_ids()

    @mock.patch("core.mining_scheduler.native_mine_pow_gpu_chunk")
    def test_chunked_mining_assigns_workers_across_multiple_devices(
        self,
        native_mine_pow_gpu_chunk: mock.Mock,
    ) -> None:
        seen_device_ids: list[int] = []

        def fake_mine_pow_gpu_chunk(*args):
            seen_device_ids.append(int(args[-1]))
            return 0, "", False, True, 1

        native_mine_pow_gpu_chunk.side_effect = fake_mine_pow_gpu_chunk

        result = run_chunked_mining(
            "prefix|",
            0,
            0,
            0,
            1,
            True,
            8,
            gpu_workers=1,
            gpu_device_ids=(1, 3),
        )

        self.assertEqual(sorted(seen_device_ids), [1, 3])
        self.assertTrue(result.cancelled)
        self.assertEqual(result.attempts, 2)


class ProofOfWorkGpuOnlySettingTests(unittest.TestCase):
    @mock.patch("core.block.get_gpu_device_ids", return_value=(0, 1))
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
        _get_gpu_device_ids: mock.Mock,
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

        with mock.patch("core.block.native_extension_built", return_value=True):
            with mock.patch.dict(os.environ, {"UNCCOIN_MINING_CPU_WORKERS": "0"}, clear=False):
                proof_of_work(block, difficulty_bits=0)

        self.assertEqual(run_chunked_mining.call_args.args[3], 0)
        self.assertEqual(run_chunked_mining.call_args.kwargs["gpu_device_ids"], (0, 1))
        self.assertEqual(block.nonces_checked, 8)

    @mock.patch("core.block.get_gpu_device_ids", return_value=(2, 3))
    @mock.patch("core.block.get_tuned_gpu_chunk_multiplier", return_value=4)
    @mock.patch("core.block.get_tuned_gpu_launch_config", return_value=(8, 256))
    @mock.patch("core.block.native_gpu_available", return_value=True)
    @mock.patch("core.block.native_mine_pow_gpu")
    def test_resident_prefix_gpu_uses_one_long_running_gpu_call(
        self,
        native_mine_pow_gpu: mock.Mock,
        _native_gpu_available: mock.Mock,
        _get_tuned_gpu_launch_config: mock.Mock,
        _get_tuned_gpu_chunk_multiplier: mock.Mock,
        _get_gpu_device_ids: mock.Mock,
    ) -> None:
        native_mine_pow_gpu.return_value = (12, "0" * 64, False)

        with mock.patch.dict(os.environ, {}, clear=True):
            result = mine_serialized_block_prefix_resident(
                "prefix|",
                difficulty_bits=0,
                mining_backend="gpu",
            )

        self.assertEqual(result.nonce, 12)
        self.assertEqual(result.block_hash, "0" * 64)
        self.assertEqual(result.attempts, 13)
        native_mine_pow_gpu.assert_called_once_with(
            "prefix|",
            0,
            0,
            0,
            262_144 * 4,
            1,
            8,
            256,
            2,
        )
