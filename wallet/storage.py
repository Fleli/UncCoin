import json
import re
from pathlib import Path

from state_paths import ensure_state_dir
from wallet.wallet import Wallet


WALLETS_DIR = ensure_state_dir() / "wallets"
WALLET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def ensure_wallets_dir() -> Path:
    ensure_state_dir()
    WALLETS_DIR.mkdir(exist_ok=True)
    return WALLETS_DIR


def wallet_path(name: str) -> Path:
    return ensure_wallets_dir() / f"{normalize_wallet_name(name)}.json"


def normalize_wallet_name(name: str) -> str:
    wallet_name = str(name).strip()
    if not WALLET_NAME_PATTERN.fullmatch(wallet_name):
        raise ValueError(
            "Wallet name must be 1-64 characters and contain only letters, "
            "numbers, dots, underscores, or hyphens. It must start with a "
            "letter or number."
        )
    if Path(wallet_name).name != wallet_name:
        raise ValueError("Wallet name must not contain path separators.")
    return wallet_name


def save_wallet(wallet: Wallet) -> Path:
    if not wallet.name:
        raise ValueError("Wallet name is required for persistence.")

    wallet.name = normalize_wallet_name(wallet.name)
    path = wallet_path(wallet.name)
    if path.exists():
        raise FileExistsError(f"Wallet '{wallet.name}' already exists at {path}.")

    path.write_text(json.dumps(wallet.to_dict(), indent=2), encoding="utf-8")
    return path


def load_wallet(name: str) -> Wallet:
    path = wallet_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Wallet '{name}' does not exist at {path}.")

    wallet_data = json.loads(path.read_text(encoding="utf-8"))
    return Wallet.from_dict(wallet_data)
