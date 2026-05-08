import hashlib
import json
from pathlib import Path

from state_paths import ensure_state_dir


AUTHORIZATIONS_DIR = ensure_state_dir() / "authorizations"


def ensure_authorizations_dir() -> Path:
    ensure_state_dir()
    AUTHORIZATIONS_DIR.mkdir(exist_ok=True)
    return AUTHORIZATIONS_DIR


def authorization_store_path(wallet_address: str) -> Path:
    return ensure_authorizations_dir() / f"{wallet_address}.json"


def load_authorizations(wallet_address: str) -> list[dict]:
    path = authorization_store_path(wallet_address)
    if not path.exists():
        return []

    authorizations = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(authorizations, list):
        return []
    return [
        authorization
        for authorization in authorizations
        if isinstance(authorization, dict)
    ]


def save_authorizations(wallet_address: str, authorizations: list[dict]) -> Path:
    path = authorization_store_path(wallet_address)
    path.write_text(json.dumps(authorizations, indent=2, sort_keys=True), encoding="utf-8")
    return path


def add_authorization(wallet_address: str, authorization: dict) -> bool:
    authorizations = load_authorizations(wallet_address)
    authorization_id = authorization_store_id(authorization)
    if any(
        authorization_store_id(existing_authorization) == authorization_id
        for existing_authorization in authorizations
    ):
        return False

    authorizations.append(authorization)
    save_authorizations(wallet_address, authorizations)
    return True


def authorization_store_id(authorization: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            authorization,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
