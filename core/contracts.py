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
