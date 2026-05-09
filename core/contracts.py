import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any


CONTRACT_ADDRESS_DOMAIN = "UVM_CONTRACT"
CONTRACT_ADDRESS_VERSION = 1
CONTRACT_CODE_DOMAIN = "UVM_CODE"
CONTRACT_CODE_VERSION = 1
CONTRACT_SELF_ADDRESS = "$CONTRACT"
NFT_TEMPLATE = "nft"
NFT_OWNER_STORAGE_KEY = "owner"
NFT_RECIPIENT_INPUT_KEY = "recipient"
NFT_TRANSFER_GAS_LIMIT = 1000


def nft_contract_program() -> list[list[str | int]]:
    return [
        ["LOAD", NFT_OWNER_STORAGE_KEY],
        ["JUMPI", 4],
        ["READ_METADATA", "initial_owner"],
        ["STORE", NFT_OWNER_STORAGE_KEY],
        ["LOAD", NFT_OWNER_STORAGE_KEY],
        ["TX_SENDER"],
        ["EQ"],
        ["JUMPI", 9],
        ["REVERT"],
        ["READ_INPUT", NFT_RECIPIENT_INPUT_KEY],
        ["DUP"],
        ["JUMPI", 13],
        ["REVERT"],
        ["STORE", NFT_OWNER_STORAGE_KEY],
        ["HALT"],
    ]


def build_nft_contract(
    *,
    name: str,
    description: str,
    image_data_uri: str,
    initial_owner: str,
) -> tuple[list[list[str | int]], dict[str, Any]]:
    owner_address = normalize_wallet_address(initial_owner, "initial_owner")
    nft_name = str(name).strip()
    if not nft_name:
        raise ValueError("NFT name is required.")
    image_value = str(image_data_uri).strip()
    if not image_value:
        raise ValueError("NFT image is required.")

    return (
        nft_contract_program(),
        {
            "name": nft_name,
            "description": str(description).strip(),
            "template": NFT_TEMPLATE,
            "nft_version": 1,
            "initial_owner": owner_address,
            "image_data_uri": image_value,
        },
    )


def normalize_wallet_address(address: str, label: str = "wallet") -> str:
    normalized_address = str(address).strip().lower()
    if (
        len(normalized_address) != 64
        or any(character not in "0123456789abcdef" for character in normalized_address)
    ):
        raise ValueError(f"{label} must be a 64-character hex wallet address.")
    return normalized_address


def compute_contract_code_hash(program: Any, metadata: dict[str, Any] | None = None) -> str:
    payload = {
        "domain": CONTRACT_CODE_DOMAIN,
        "version": CONTRACT_CODE_VERSION,
        "program": program,
        "metadata": metadata or {},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_contract_address(deployer: str, nonce: int, code_hash: str) -> str:
    payload = (
        f"{CONTRACT_ADDRESS_DOMAIN}|{CONTRACT_ADDRESS_VERSION}|"
        f"{deployer.strip()}|{int(nonce)}|{code_hash.strip().lower()}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(value[key])
            for key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value
