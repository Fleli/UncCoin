import json
from pathlib import Path

from state_paths import ensure_state_dir

MSGS_DIR = ensure_state_dir() / "msgs"


def ensure_msgs_dir() -> Path:
    ensure_state_dir()
    MSGS_DIR.mkdir(exist_ok=True)
    return MSGS_DIR


def message_store_path(wallet_address: str) -> Path:
    return ensure_msgs_dir() / f"{wallet_address}.json"


def load_messages(wallet_address: str) -> list[dict]:
    path = message_store_path(wallet_address)
    if not path.exists():
        return []

    return json.loads(path.read_text(encoding="utf-8"))


def save_messages(wallet_address: str, messages: list[dict]) -> Path:
    path = message_store_path(wallet_address)
    path.write_text(json.dumps(messages, indent=2), encoding="utf-8")
    return path
