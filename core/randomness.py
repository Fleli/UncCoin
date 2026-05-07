import hashlib
from typing import Any


REVEAL_COMMITMENT_DOMAIN = "UVM_REVEAL"
REVEAL_COMMITMENT_VERSION = 1
MAX_RANDOMNESS_REQUEST_ID_LENGTH = 128
MAX_REVEAL_SALT_LENGTH = 1024
RANDOMNESS_SEED_MODULUS = 2**256


def create_reveal_commitment_hash(
    sender: str,
    request_id: str,
    seed: int | str,
    salt: str = "",
) -> str:
    return hashlib.sha256(
        reveal_commitment_payload(sender, request_id, seed, salt).encode("utf-8")
    ).hexdigest()


def reveal_commitment_payload(
    sender: str,
    request_id: str,
    seed: int | str,
    salt: str = "",
) -> str:
    return (
        f"{REVEAL_COMMITMENT_DOMAIN}|{REVEAL_COMMITMENT_VERSION}|"
        f"{sender.strip()}|{request_id.strip()}|"
        f"{parse_randomness_seed(seed)}|{salt.strip()}"
    )


def parse_randomness_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer, not a boolean")
    if isinstance(seed, int):
        seed_value = seed
    elif isinstance(seed, str):
        stripped_seed = seed.strip()
        if not stripped_seed:
            raise ValueError("seed must be non-empty")
        if stripped_seed.startswith(("0x", "0X")):
            seed_value = int(stripped_seed, 16)
        else:
            seed_value = int(stripped_seed, 10)
    else:
        raise ValueError("seed must be an integer string")

    if seed_value < 0 or seed_value >= RANDOMNESS_SEED_MODULUS:
        raise ValueError("seed must be between 0 and 2^256 - 1")
    return seed_value
