from __future__ import annotations

import hashlib
import os
import platform
import threading
from dataclasses import dataclass

from config import DEFAULT_GPU_BATCH_SIZE
from config import DEFAULT_GPU_NONCES_PER_THREAD


_INITIAL_SHA256_STATE = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
)
_SHA256_K = (
    0x428A2F98,
    0x71374491,
    0xB5C0FBCF,
    0xE9B5DBA5,
    0x3956C25B,
    0x59F111F1,
    0x923F82A4,
    0xAB1C5ED5,
    0xD807AA98,
    0x12835B01,
    0x243185BE,
    0x550C7DC3,
    0x72BE5D74,
    0x80DEB1FE,
    0x9BDC06A7,
    0xC19BF174,
    0xE49B69C1,
    0xEFBE4786,
    0x0FC19DC6,
    0x240CA1CC,
    0x2DE92C6F,
    0x4A7484AA,
    0x5CB0A9DC,
    0x76F988DA,
    0x983E5152,
    0xA831C66D,
    0xB00327C8,
    0xBF597FC7,
    0xC6E00BF3,
    0xD5A79147,
    0x06CA6351,
    0x14292967,
    0x27B70A85,
    0x2E1B2138,
    0x4D2C6DFC,
    0x53380D13,
    0x650A7354,
    0x766A0ABB,
    0x81C2C92E,
    0x92722C85,
    0xA2BFE8A1,
    0xA81A664B,
    0xC24B8B70,
    0xC76C51A3,
    0xD192E819,
    0xD6990624,
    0xF40E3585,
    0x106AA070,
    0x19A4C116,
    0x1E376C08,
    0x2748774C,
    0x34B0BCB5,
    0x391C0CB3,
    0x4ED8AA4A,
    0x5B9CCA4F,
    0x682E6FF3,
    0x748F82EE,
    0x78A5636F,
    0x84C87814,
    0x8CC70208,
    0x90BEFFFA,
    0xA4506CEB,
    0xBEF9A3F7,
    0xC67178F2,
)
_U64_MAX = (1 << 64) - 1
_DECIMAL_DIGIT_BOUNDARIES = tuple((10 ** digits) - 1 for digits in range(1, 20)) + (_U64_MAX,)
_MAX_FIXED_DIGIT_LENGTH = len(_DECIMAL_DIGIT_BOUNDARIES)
_CUDA_KERNEL_SOURCE = r"""
extern "C" {

__device__ __forceinline__ unsigned int rotr32(unsigned int value, unsigned int bits) {
    return (value >> bits) | (value << (32U - bits));
}

__constant__ unsigned int SHA256_K[64] = {
    0x428A2F98U, 0x71374491U, 0xB5C0FBCFU, 0xE9B5DBA5U,
    0x3956C25BU, 0x59F111F1U, 0x923F82A4U, 0xAB1C5ED5U,
    0xD807AA98U, 0x12835B01U, 0x243185BEU, 0x550C7DC3U,
    0x72BE5D74U, 0x80DEB1FEU, 0x9BDC06A7U, 0xC19BF174U,
    0xE49B69C1U, 0xEFBE4786U, 0x0FC19DC6U, 0x240CA1CCU,
    0x2DE92C6FU, 0x4A7484AAU, 0x5CB0A9DCU, 0x76F988DAU,
    0x983E5152U, 0xA831C66DU, 0xB00327C8U, 0xBF597FC7U,
    0xC6E00BF3U, 0xD5A79147U, 0x06CA6351U, 0x14292967U,
    0x27B70A85U, 0x2E1B2138U, 0x4D2C6DFCU, 0x53380D13U,
    0x650A7354U, 0x766A0ABBU, 0x81C2C92EU, 0x92722C85U,
    0xA2BFE8A1U, 0xA81A664BU, 0xC24B8B70U, 0xC76C51A3U,
    0xD192E819U, 0xD6990624U, 0xF40E3585U, 0x106AA070U,
    0x19A4C116U, 0x1E376C08U, 0x2748774CU, 0x34B0BCB5U,
    0x391C0CB3U, 0x4ED8AA4AU, 0x5B9CCA4FU, 0x682E6FF3U,
    0x748F82EEU, 0x78A5636FU, 0x84C87814U, 0x8CC70208U,
    0x90BEFFFAU, 0xA4506CEBU, 0xBEF9A3F7U, 0xC67178F2U
};

__device__ void sha256_transform(unsigned int state[8], const unsigned char block[64]) {
    unsigned int schedule[64];

    for (int index = 0; index < 16; ++index) {
        schedule[index] =
            ((unsigned int)block[index * 4] << 24) |
            ((unsigned int)block[index * 4 + 1] << 16) |
            ((unsigned int)block[index * 4 + 2] << 8) |
            ((unsigned int)block[index * 4 + 3]);
    }

    for (int index = 16; index < 64; ++index) {
        unsigned int sigma0 =
            rotr32(schedule[index - 15], 7) ^
            rotr32(schedule[index - 15], 18) ^
            (schedule[index - 15] >> 3);
        unsigned int sigma1 =
            rotr32(schedule[index - 2], 17) ^
            rotr32(schedule[index - 2], 19) ^
            (schedule[index - 2] >> 10);
        schedule[index] = schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1;
    }

    unsigned int a = state[0];
    unsigned int b = state[1];
    unsigned int c = state[2];
    unsigned int d = state[3];
    unsigned int e = state[4];
    unsigned int f = state[5];
    unsigned int g = state[6];
    unsigned int h = state[7];

    for (int index = 0; index < 64; ++index) {
        unsigned int sum1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        unsigned int choose = (e & f) ^ ((~e) & g);
        unsigned int temp1 = h + sum1 + choose + SHA256_K[index] + schedule[index];
        unsigned int sum0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        unsigned int majority = (a & b) ^ (a & c) ^ (b & c);
        unsigned int temp2 = sum0 + majority;

        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    state[0] += a;
    state[1] += b;
    state[2] += c;
    state[3] += d;
    state[4] += e;
    state[5] += f;
    state[6] += g;
    state[7] += h;
}

__device__ int u64_to_ascii(unsigned long long value, unsigned char output[32]) {
    if (value == 0ULL) {
        output[0] = (unsigned char)'0';
        return 1;
    }

    int length = 0;
    while (value > 0ULL && length < 32) {
        output[length] = (unsigned char)('0' + (value % 10ULL));
        value /= 10ULL;
        ++length;
    }

    for (int index = 0; index < length / 2; ++index) {
        unsigned char temp = output[index];
        output[index] = output[length - 1 - index];
        output[length - 1 - index] = temp;
    }

    return length;
}

__device__ int has_leading_zero_bits_state(const unsigned int state[8], int difficulty_bits) {
    if (difficulty_bits <= 0) {
        return 1;
    }
    if (difficulty_bits <= 32) {
        if (difficulty_bits == 32) {
            return state[0] == 0U;
        }
        return (state[0] >> (32 - difficulty_bits)) == 0U;
    }

    int full_words = difficulty_bits >> 5;
    int remaining_bits = difficulty_bits & 31;

    for (int index = 0; index < full_words; ++index) {
        if (state[index] != 0U) {
            return 0;
        }
    }

    if (remaining_bits == 0) {
        return 1;
    }

    return (state[full_words] >> (32 - remaining_bits)) == 0U;
}

__device__ void write_sha256_length(unsigned char block[64], unsigned long long total_bits) {
    for (int index = 0; index < 8; ++index) {
        block[63 - index] = (unsigned char)((total_bits >> (index * 8)) & 0xFFULL);
    }
}

__device__ void nonce_to_ascii_fixed_digits(
    unsigned long long nonce,
    int digit_count,
    unsigned char output[32]
) {
    for (int index = digit_count - 1; index >= 0; --index) {
        output[index] = (unsigned char)('0' + (nonce % 10ULL));
        nonce /= 10ULL;
    }
}

__device__ int increment_ascii_fixed_digits_one(unsigned char buffer[32], int digit_count) {
    int index = digit_count - 1;

    while (index >= 0 && buffer[index] == '9') {
        buffer[index] = '0';
        --index;
    }

    if (index < 0) {
        return -1;
    }

    buffer[index] = (unsigned char)(buffer[index] + 1);
    return index;
}

__device__ void initialize_fixed_nonce_blocks(
    const unsigned char* prefix_data,
    int prefix_data_length,
    unsigned long long prefix_bit_length,
    const unsigned char nonce_buffer[32],
    int digit_count,
    unsigned char first_block[64],
    unsigned char second_block[64],
    int* first_nonce_length,
    int* second_nonce_length,
    int* uses_second_block
) {
    for (int index = 0; index < 64; ++index) {
        first_block[index] = 0U;
        second_block[index] = 0U;
    }

    for (int index = 0; index < prefix_data_length; ++index) {
        first_block[index] = prefix_data[index];
    }

    *first_nonce_length = digit_count;
    int first_available = 64 - prefix_data_length;
    if (*first_nonce_length > first_available) {
        *first_nonce_length = first_available;
    }

    *second_nonce_length = digit_count - *first_nonce_length;
    *uses_second_block = *second_nonce_length > 0 ? 1 : 0;

    for (int index = 0; index < *first_nonce_length; ++index) {
        first_block[prefix_data_length + index] = nonce_buffer[index];
    }
    for (int index = 0; index < *second_nonce_length; ++index) {
        second_block[index] = nonce_buffer[*first_nonce_length + index];
    }

    unsigned long long total_bits =
        prefix_bit_length + ((unsigned long long)(prefix_data_length + digit_count) * 8ULL);

    if (*uses_second_block != 0) {
        second_block[*second_nonce_length] = 0x80U;
        write_sha256_length(second_block, total_bits);
        return;
    }

    int total_suffix_offset = prefix_data_length + *first_nonce_length;
    if (total_suffix_offset < 56) {
        first_block[total_suffix_offset] = 0x80U;
        write_sha256_length(first_block, total_bits);
        return;
    }

    *uses_second_block = 1;
    if (total_suffix_offset < 64) {
        first_block[total_suffix_offset] = 0x80U;
    } else {
        second_block[0] = 0x80U;
    }
    write_sha256_length(second_block, total_bits);
}

__device__ void update_fixed_nonce_blocks(
    unsigned char first_block[64],
    unsigned char second_block[64],
    int prefix_data_length,
    int first_nonce_length,
    int second_nonce_length,
    const unsigned char nonce_buffer[32],
    int changed_index
) {
    if (changed_index < 0) {
        changed_index = 0;
    }

    if (changed_index < first_nonce_length) {
        for (int index = changed_index; index < first_nonce_length; ++index) {
            first_block[prefix_data_length + index] = nonce_buffer[index];
        }
        for (int index = 0; index < second_nonce_length; ++index) {
            second_block[index] = nonce_buffer[first_nonce_length + index];
        }
        return;
    }

    int second_changed_index = changed_index - first_nonce_length;
    if (second_changed_index < second_nonce_length) {
        for (int index = second_changed_index; index < second_nonce_length; ++index) {
            second_block[index] = nonce_buffer[first_nonce_length + index];
        }
    }
}

__device__ void hash_prepared_nonce_blocks(
    const unsigned int prefix_state[8],
    const unsigned char first_block[64],
    const unsigned char second_block[64],
    int uses_second_block,
    unsigned int output_state[8]
) {
    unsigned int state[8];

    for (int index = 0; index < 8; ++index) {
        state[index] = prefix_state[index];
    }

    sha256_transform(state, first_block);
    if (uses_second_block != 0) {
        sha256_transform(state, second_block);
    }

    for (int index = 0; index < 8; ++index) {
        output_state[index] = state[index];
    }
}

__device__ void hash_prefix_with_nonce(
    const unsigned int prefix_state[8],
    const unsigned char prefix_data[64],
    unsigned long long prefix_bit_length,
    int prefix_data_length,
    unsigned long long nonce,
    unsigned int output_state[8]
) {
    unsigned int state[8];
    unsigned char data[64];
    unsigned char nonce_buffer[32];
    unsigned long long bit_length = prefix_bit_length;
    int data_length = prefix_data_length;
    int nonce_length = u64_to_ascii(nonce, nonce_buffer);

    for (int index = 0; index < 8; ++index) {
        state[index] = prefix_state[index];
    }
    for (int index = 0; index < 64; ++index) {
        data[index] = prefix_data[index];
    }

    for (int index = 0; index < nonce_length; ++index) {
        data[data_length] = nonce_buffer[index];
        ++data_length;
        if (data_length == 64) {
            sha256_transform(state, data);
            bit_length += 512ULL;
            data_length = 0;
        }
    }

    unsigned long long total_bits = bit_length + ((unsigned long long)data_length * 8ULL);
    data[data_length] = 0x80U;
    ++data_length;

    if (data_length > 56) {
        while (data_length < 64) {
            data[data_length] = 0U;
            ++data_length;
        }
        sha256_transform(state, data);
        for (int index = 0; index < 56; ++index) {
            data[index] = 0U;
        }
        data_length = 56;
    }

    while (data_length < 56) {
        data[data_length] = 0U;
        ++data_length;
    }

    for (int index = 0; index < 8; ++index) {
        data[56 + index] = (unsigned char)((total_bits >> ((7 - index) * 8)) & 0xFFULL);
    }

    sha256_transform(state, data);

    for (int index = 0; index < 8; ++index) {
        output_state[index] = state[index];
    }
}

__global__ void mine_pow_generic(
    const unsigned int* prefix_state,
    const unsigned char* prefix_data,
    unsigned long long prefix_bit_length,
    int prefix_data_length,
    int difficulty_bits,
    unsigned long long start_nonce,
    unsigned long long nonce_step,
    unsigned long long total_attempts,
    unsigned long long nonces_per_thread,
    unsigned long long* best_index
) {
    unsigned long long thread_index =
        (unsigned long long)blockIdx.x * (unsigned long long)blockDim.x +
        (unsigned long long)threadIdx.x;
    unsigned long long first_index = thread_index * nonces_per_thread;

    if (first_index >= total_attempts) {
        return;
    }
    if (first_index >= *best_index) {
        return;
    }

    unsigned long long limit = first_index + nonces_per_thread;
    if (limit > total_attempts) {
        limit = total_attempts;
    }

    for (unsigned long long candidate_index = first_index;
         candidate_index < limit;
         ++candidate_index) {
        unsigned long long nonce = start_nonce + (candidate_index * nonce_step);
        unsigned int digest_state[8];
        hash_prefix_with_nonce(
            prefix_state,
            prefix_data,
            prefix_bit_length,
            prefix_data_length,
            nonce,
            digest_state
        );

        if (has_leading_zero_bits_state(digest_state, difficulty_bits)) {
            atomicMin(best_index, candidate_index);
            return;
        }
    }
}

__global__ void mine_pow_fixed_digits(
    const unsigned int* prefix_state,
    const unsigned char* prefix_data,
    unsigned long long prefix_bit_length,
    int prefix_data_length,
    int difficulty_bits,
    unsigned long long start_nonce,
    unsigned long long total_attempts,
    unsigned long long nonces_per_thread,
    int digit_count,
    unsigned long long* best_index
) {
    unsigned long long thread_index =
        (unsigned long long)blockIdx.x * (unsigned long long)blockDim.x +
        (unsigned long long)threadIdx.x;
    unsigned long long first_index = thread_index * nonces_per_thread;

    if (first_index >= total_attempts) {
        return;
    }
    if (first_index >= *best_index) {
        return;
    }

    unsigned long long limit = first_index + nonces_per_thread;
    if (limit > total_attempts) {
        limit = total_attempts;
    }

    unsigned long long nonce = start_nonce + first_index;
    unsigned char nonce_buffer[32];
    unsigned char first_block[64];
    unsigned char second_block[64];
    unsigned int digest_state[8];
    int first_nonce_length = 0;
    int second_nonce_length = 0;
    int uses_second_block = 0;

    nonce_to_ascii_fixed_digits(nonce, digit_count, nonce_buffer);
    initialize_fixed_nonce_blocks(
        prefix_data,
        prefix_data_length,
        prefix_bit_length,
        nonce_buffer,
        digit_count,
        first_block,
        second_block,
        &first_nonce_length,
        &second_nonce_length,
        &uses_second_block
    );

    for (unsigned long long candidate_index = first_index;
         candidate_index < limit;
         ++candidate_index) {
        hash_prepared_nonce_blocks(
            prefix_state,
            first_block,
            second_block,
            uses_second_block,
            digest_state
        );
        if (has_leading_zero_bits_state(digest_state, difficulty_bits)) {
            atomicMin(best_index, candidate_index);
            return;
        }

        if (candidate_index + 1ULL >= limit) {
            return;
        }

        int changed_index = increment_ascii_fixed_digits_one(nonce_buffer, digit_count);
        if (changed_index < 0) {
            return;
        }
        update_fixed_nonce_blocks(
            first_block,
            second_block,
            prefix_data_length,
            first_nonce_length,
            second_nonce_length,
            nonce_buffer,
            changed_index
        );
    }
}

}
"""

_cupy_module = None
_raw_modules: dict[int, object] = {}
_generic_kernels: dict[int, object] = {}
_fixed_digits_kernels: dict[int, object] = {}
_cupy_lock = threading.RLock()
_cancel_event = threading.Event()


@dataclass(frozen=True)
class PreparedPrefixContext:
    state: tuple[int, ...]
    data: bytes
    data_length: int
    bit_length: int


def prepare_prefix_context(prefix: str | bytes) -> PreparedPrefixContext:
    prefix_bytes = prefix.encode("utf-8") if isinstance(prefix, str) else bytes(prefix)
    state = list(_INITIAL_SHA256_STATE)
    offset = 0
    bit_length = 0

    while offset + 64 <= len(prefix_bytes):
        _sha256_transform(state, prefix_bytes[offset:offset + 64])
        bit_length += 512
        offset += 64

    remaining = prefix_bytes[offset:]
    return PreparedPrefixContext(
        state=tuple(state),
        data=remaining + b"\x00" * (64 - len(remaining)),
        data_length=len(remaining),
        bit_length=bit_length,
    )


def hash_prepared_prefix_with_nonce(
    prepared_prefix: PreparedPrefixContext,
    nonce: int,
) -> str:
    if nonce < 0:
        raise ValueError("nonce must be non-negative.")

    state = list(prepared_prefix.state)
    data = bytearray(prepared_prefix.data)
    data_length = prepared_prefix.data_length
    bit_length = prepared_prefix.bit_length

    for byte in str(nonce).encode("ascii"):
        data[data_length] = byte
        data_length += 1
        if data_length == 64:
            _sha256_transform(state, data)
            bit_length += 512
            data = bytearray(64)
            data_length = 0

    total_bits = bit_length + (data_length * 8)
    data[data_length] = 0x80
    data_length += 1

    if data_length > 56:
        for index in range(data_length, 64):
            data[index] = 0
        _sha256_transform(state, data)
        data = bytearray(64)
        data_length = 0

    for index in range(data_length, 56):
        data[index] = 0
    data[56:64] = total_bits.to_bytes(8, "big")
    _sha256_transform(state, data)

    return "".join(f"{word:08x}" for word in state)


def gpu_device_count() -> int:
    if platform.system() != "Linux" or _cuda_backend_disabled():
        return 0

    try:
        cupy = _load_cupy()
        return max(0, int(cupy.cuda.runtime.getDeviceCount()))
    except Exception:
        return 0


def gpu_device_ids() -> tuple[int, ...]:
    return tuple(range(gpu_device_count()))


def gpu_available(device_id: int | None = None) -> bool:
    device_count = gpu_device_count()
    if device_id is None:
        return device_count > 0
    return 0 <= device_id < device_count


def gpu_properties(device_id: int | None = None) -> tuple[int, int] | None:
    if not gpu_available(device_id):
        return None

    previous_device_id = _activate_cuda_device(device_id)
    try:
        cupy = _load_cupy()
        properties = cupy.cuda.runtime.getDeviceProperties(_current_cuda_device_id())
        warp_size = int(_read_runtime_property(properties, "warpSize", 32))
        max_threads_per_block = int(
            _read_runtime_property(properties, "maxThreadsPerBlock", 256)
        )
        return warp_size, max_threads_per_block
    finally:
        _restore_cuda_device(previous_device_id)


def mine_pow_gpu(
    prefix: str,
    difficulty_bits: int,
    start_nonce: int = 0,
    progress_interval: int = 0,
    batch_size: int = DEFAULT_GPU_BATCH_SIZE,
    nonce_step: int = 1,
    nonces_per_thread: int = 0,
    threads_per_group: int = 0,
    device_id: int | None = None,
) -> tuple[int, str, bool]:
    prepared_prefix = prepare_prefix_context(prefix)
    prefix_bytes = prefix.encode("utf-8")
    total_attempts = 0
    next_progress_mark = progress_interval
    current_nonce = start_nonce
    last_nonce = start_nonce

    while True:
        nonce, block_hash, found, cancelled, attempts = _mine_pow_gpu_range(
            prefix_bytes=prefix_bytes,
            prepared_prefix=prepared_prefix,
            difficulty_bits=difficulty_bits,
            start_nonce=current_nonce,
            max_attempts=batch_size,
            batch_size=batch_size,
            nonce_step=nonce_step,
            nonces_per_thread=nonces_per_thread,
            threads_per_group=threads_per_group,
            device_id=device_id,
        )
        total_attempts += attempts
        if attempts > 0:
            last_nonce = start_nonce + ((total_attempts - 1) * nonce_step)

        while progress_interval > 0 and total_attempts >= next_progress_mark:
            progress_nonce = start_nonce + (next_progress_mark * nonce_step)
            print(f"\rTried {progress_nonce} nonces...", end="", flush=True)
            next_progress_mark += progress_interval

        if found:
            return nonce, block_hash, False
        if cancelled:
            return last_nonce, "", True

        current_nonce += max(1, attempts) * nonce_step


def mine_pow_gpu_chunk(
    prefix: str,
    difficulty_bits: int,
    start_nonce: int,
    max_attempts: int,
    nonce_step: int = 1,
    nonces_per_thread: int = 0,
    threads_per_group: int = 0,
    batch_size: int = 0,
    device_id: int | None = None,
) -> tuple[int, str, bool, bool, int]:
    prepared_prefix = prepare_prefix_context(prefix)
    return _mine_pow_gpu_range(
        prefix_bytes=prefix.encode("utf-8"),
        prepared_prefix=prepared_prefix,
        difficulty_bits=difficulty_bits,
        start_nonce=start_nonce,
        max_attempts=max_attempts,
        batch_size=batch_size,
        nonce_step=nonce_step,
        nonces_per_thread=nonces_per_thread,
        threads_per_group=threads_per_group,
        device_id=device_id,
    )


def request_cancel() -> None:
    _cancel_event.set()


def reset_cancel() -> None:
    _cancel_event.clear()


def _resolve_cuda_dispatch_window(
    start_nonce: int,
    remaining_attempts: int,
    dispatch_batch_size: int,
    nonce_step: int,
) -> tuple[int, int | None]:
    dispatch_attempts = min(dispatch_batch_size, remaining_attempts)
    if dispatch_attempts < 1 or nonce_step != 1:
        return dispatch_attempts, None

    digit_count = _decimal_length_u64(start_nonce)
    if digit_count > _MAX_FIXED_DIGIT_LENGTH:
        return dispatch_attempts, None

    digit_boundary = _DECIMAL_DIGIT_BOUNDARIES[digit_count - 1]
    boundary_remaining = digit_boundary - start_nonce + 1
    if boundary_remaining < dispatch_attempts:
        dispatch_attempts = boundary_remaining

    return dispatch_attempts, digit_count


def _mine_pow_gpu_range(
    prefix_bytes: bytes,
    prepared_prefix: PreparedPrefixContext,
    difficulty_bits: int,
    start_nonce: int,
    max_attempts: int,
    batch_size: int,
    nonce_step: int,
    nonces_per_thread: int,
    threads_per_group: int,
    device_id: int | None = None,
) -> tuple[int, str, bool, bool, int]:
    if not gpu_available(device_id):
        raise RuntimeError(
            "CUDA proof-of-work backend is unavailable. "
            "Install cupy-cuda12x[ctk] on a Linux NVIDIA host."
        )
    if difficulty_bits < 0 or difficulty_bits > 256:
        raise ValueError("difficulty_bits must be between 0 and 256.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")
    if nonce_step < 1:
        raise ValueError("nonce_step must be at least 1.")

    previous_device_id = _activate_cuda_device(device_id)
    try:
        cupy = _load_cupy()
        generic_kernel, fixed_digits_kernel = _get_kernels()
        launch_threads = _resolve_threads_per_group(threads_per_group)
        launch_nonces_per_thread = max(1, nonces_per_thread or DEFAULT_GPU_NONCES_PER_THREAD)
        dispatch_batch_size = max(1, batch_size or DEFAULT_GPU_BATCH_SIZE)
        prefix_state = cupy.asarray(prepared_prefix.state, dtype=cupy.uint32)
        prefix_data = cupy.asarray(list(prepared_prefix.data), dtype=cupy.uint8)

        attempts = 0
        current_start_nonce = start_nonce
        last_nonce = start_nonce

        while attempts < max_attempts:
            if _cancel_event.is_set():
                return last_nonce, "", False, True, attempts

            remaining_attempts = max_attempts - attempts
            dispatch_attempts, fixed_digit_count = _resolve_cuda_dispatch_window(
                current_start_nonce,
                remaining_attempts,
                dispatch_batch_size,
                nonce_step,
            )
            thread_count = (dispatch_attempts + launch_nonces_per_thread - 1) // launch_nonces_per_thread
            block_count = max(1, (thread_count + launch_threads - 1) // launch_threads)
            best_index = cupy.asarray([dispatch_attempts], dtype=cupy.uint64)

            try:
                if fixed_digit_count is None:
                    generic_kernel(
                        (block_count,),
                        (launch_threads,),
                        (
                            prefix_state,
                            prefix_data,
                            prepared_prefix.bit_length,
                            prepared_prefix.data_length,
                            difficulty_bits,
                            current_start_nonce,
                            nonce_step,
                            dispatch_attempts,
                            launch_nonces_per_thread,
                            best_index,
                        ),
                    )
                else:
                    fixed_digits_kernel(
                        (block_count,),
                        (launch_threads,),
                        (
                            prefix_state,
                            prefix_data,
                            prepared_prefix.bit_length,
                            prepared_prefix.data_length,
                            difficulty_bits,
                            current_start_nonce,
                            dispatch_attempts,
                            launch_nonces_per_thread,
                            fixed_digit_count,
                            best_index,
                        ),
                    )
                found_index = int(best_index.get()[0])
            except Exception as error:
                raise RuntimeError(f"CUDA proof-of-work failed: {error}") from error

            if found_index < dispatch_attempts:
                winning_nonce = current_start_nonce + (found_index * nonce_step)
                winning_hash = hashlib.sha256(
                    prefix_bytes + str(winning_nonce).encode("ascii")
                ).hexdigest()
                return winning_nonce, winning_hash, True, False, attempts + found_index + 1

            attempts += dispatch_attempts
            current_start_nonce += dispatch_attempts * nonce_step
            last_nonce = current_start_nonce - nonce_step

        return last_nonce, "", False, False, attempts
    finally:
        _restore_cuda_device(previous_device_id)


def _load_cupy():
    global _cupy_module

    if _cupy_module is not None:
        return _cupy_module

    with _cupy_lock:
        if _cupy_module is None:
            import cupy

            _cupy_module = cupy
    return _cupy_module


def _get_kernels():
    device_id = _current_cuda_device_id()
    generic_kernel = _generic_kernels.get(device_id)
    fixed_digits_kernel = _fixed_digits_kernels.get(device_id)

    if generic_kernel is not None and fixed_digits_kernel is not None:
        return generic_kernel, fixed_digits_kernel

    with _cupy_lock:
        generic_kernel = _generic_kernels.get(device_id)
        fixed_digits_kernel = _fixed_digits_kernels.get(device_id)
        if generic_kernel is None or fixed_digits_kernel is None:
            cupy = _load_cupy()
            raw_module = _raw_modules.get(device_id)
            if raw_module is None:
                raw_module = cupy.RawModule(code=_CUDA_KERNEL_SOURCE)
                _raw_modules[device_id] = raw_module
            generic_kernel = raw_module.get_function("mine_pow_generic")
            fixed_digits_kernel = raw_module.get_function("mine_pow_fixed_digits")
            _generic_kernels[device_id] = generic_kernel
            _fixed_digits_kernels[device_id] = fixed_digits_kernel
    return generic_kernel, fixed_digits_kernel


def _decimal_length_u64(value: int) -> int:
    if value < 0:
        raise ValueError("value must be non-negative.")
    return len(str(value))


def _current_cuda_device_id() -> int:
    cupy = _load_cupy()
    return int(cupy.cuda.runtime.getDevice())


def _activate_cuda_device(device_id: int | None) -> int | None:
    if device_id is None:
        return None
    if not gpu_available(device_id):
        raise ValueError(f"CUDA device {device_id} is unavailable.")

    cupy = _load_cupy()
    previous_device_id = _current_cuda_device_id()
    if previous_device_id != device_id:
        cupy.cuda.runtime.setDevice(device_id)
    return previous_device_id


def _restore_cuda_device(previous_device_id: int | None) -> None:
    if previous_device_id is None:
        return

    cupy = _load_cupy()
    if _current_cuda_device_id() != previous_device_id:
        cupy.cuda.runtime.setDevice(previous_device_id)


def _resolve_threads_per_group(threads_per_group: int) -> int:
    if threads_per_group > 0:
        return threads_per_group

    properties = gpu_properties()
    if properties is None:
        return 256

    warp_size, max_threads_per_block = properties
    return max(1, min(max_threads_per_block, max(1, warp_size) * 8))


def _read_runtime_property(properties, name: str, default: int) -> int:
    if isinstance(properties, dict):
        if name in properties:
            return int(properties[name])
        encoded_name = name.encode("utf-8")
        if encoded_name in properties:
            return int(properties[encoded_name])
    return default


def _cuda_backend_disabled() -> bool:
    raw_value = os.environ.get("UNCCOIN_DISABLE_CUDA_POW", "")
    return raw_value.lower() in {"1", "true", "yes", "on"}


def _sha256_transform(state: list[int], block: bytes | bytearray) -> None:
    schedule = [0] * 64

    for index in range(16):
        offset = index * 4
        schedule[index] = (
            (block[offset] << 24)
            | (block[offset + 1] << 16)
            | (block[offset + 2] << 8)
            | block[offset + 3]
        )

    for index in range(16, 64):
        sigma0 = (
            _right_rotate(schedule[index - 15], 7)
            ^ _right_rotate(schedule[index - 15], 18)
            ^ (schedule[index - 15] >> 3)
        )
        sigma1 = (
            _right_rotate(schedule[index - 2], 17)
            ^ _right_rotate(schedule[index - 2], 19)
            ^ (schedule[index - 2] >> 10)
        )
        schedule[index] = (
            schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1
        ) & 0xFFFFFFFF

    a, b, c, d, e, f, g, h = state

    for index in range(64):
        sum1 = _right_rotate(e, 6) ^ _right_rotate(e, 11) ^ _right_rotate(e, 25)
        choose = (e & f) ^ ((~e) & g)
        temp1 = (h + sum1 + choose + _SHA256_K[index] + schedule[index]) & 0xFFFFFFFF
        sum0 = _right_rotate(a, 2) ^ _right_rotate(a, 13) ^ _right_rotate(a, 22)
        majority = (a & b) ^ (a & c) ^ (b & c)
        temp2 = (sum0 + majority) & 0xFFFFFFFF

        h = g
        g = f
        f = e
        e = (d + temp1) & 0xFFFFFFFF
        d = c
        c = b
        b = a
        a = (temp1 + temp2) & 0xFFFFFFFF

    state[0] = (state[0] + a) & 0xFFFFFFFF
    state[1] = (state[1] + b) & 0xFFFFFFFF
    state[2] = (state[2] + c) & 0xFFFFFFFF
    state[3] = (state[3] + d) & 0xFFFFFFFF
    state[4] = (state[4] + e) & 0xFFFFFFFF
    state[5] = (state[5] + f) & 0xFFFFFFFF
    state[6] = (state[6] + g) & 0xFFFFFFFF
    state[7] = (state[7] + h) & 0xFFFFFFFF


def _right_rotate(value: int, bits: int) -> int:
    return ((value >> bits) | (value << (32 - bits))) & 0xFFFFFFFF
