import json
from pathlib import Path

from state_paths import ensure_state_dir

ALIASES_DIR = ensure_state_dir() / "aliases"


def ensure_aliases_dir() -> Path:
    ensure_state_dir()
    ALIASES_DIR.mkdir(exist_ok=True)
    return ALIASES_DIR


def alias_store_path(owner_key: str) -> Path:
    return ensure_aliases_dir() / f"{owner_key}.json"


def load_aliases(owner_key: str) -> dict[str, str]:
    path = alias_store_path(owner_key)
    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def save_aliases(owner_key: str, aliases: dict[str, str]) -> Path:
    path = alias_store_path(owner_key)
    path.write_text(json.dumps(aliases, indent=2, sort_keys=True), encoding="utf-8")
    return path
