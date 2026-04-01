from pathlib import Path


STATE_DIR = Path("state")


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    return STATE_DIR
