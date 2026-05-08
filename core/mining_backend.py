import os
from typing import Any

from core.native_pow import build_native_pow_extension
from core.native_pow import gpu_available
from core.native_pow import gpu_device_ids
from core.native_pow import native_extension_built
from core.native_pow import native_extension_status


MINING_BACKEND_AUTO = "auto"
MINING_BACKEND_GPU = "gpu"
MINING_BACKEND_NATIVE = "native"
MINING_BACKEND_PYTHON = "python"
MINING_BACKENDS = (
    MINING_BACKEND_AUTO,
    MINING_BACKEND_GPU,
    MINING_BACKEND_NATIVE,
    MINING_BACKEND_PYTHON,
)


def normalize_mining_backend(value: str | None) -> str:
    backend = (value or MINING_BACKEND_AUTO).strip().lower()
    if backend not in MINING_BACKENDS:
        raise ValueError(
            "Mining backend must be one of: "
            + ", ".join(MINING_BACKENDS)
            + "."
        )
    return backend


def selected_mining_backend(default: str = MINING_BACKEND_AUTO) -> str:
    return normalize_mining_backend(os.environ.get("UNCCOIN_MINING_BACKEND", default))


def _safe_gpu_status() -> tuple[bool, tuple[int, ...], str | None]:
    try:
        available = bool(gpu_available())
        device_ids = tuple(gpu_device_ids()) if available else ()
        return available, device_ids, None
    except Exception as error:
        return False, (), str(error)


def mining_backend_capabilities(selected: str = MINING_BACKEND_AUTO) -> dict[str, Any]:
    selected_backend = normalize_mining_backend(selected)
    native_status = native_extension_status()
    native_available = native_extension_built()
    gpu_available_now, device_ids, gpu_error = _safe_gpu_status() if native_available else (
        False,
        (),
        "Native miner is not built.",
    )

    return {
        "selected": selected_backend,
        "native": native_status,
        "backends": [
            {
                "id": MINING_BACKEND_AUTO,
                "label": "Auto",
                "available": True,
                "can_build": False,
                "description": "Use GPU if available, then native C, then Python.",
            },
            {
                "id": MINING_BACKEND_GPU,
                "label": "GPU",
                "available": gpu_available_now,
                "can_build": not native_available,
                "description": (
                    f"Native GPU miner ({len(device_ids)} device"
                    f"{'' if len(device_ids) == 1 else 's'})."
                    if gpu_available_now
                    else gpu_error or "No GPU miner is available."
                ),
            },
            {
                "id": MINING_BACKEND_NATIVE,
                "label": "Native C",
                "available": native_available,
                "can_build": not native_available,
                "description": (
                    "Compiled native CPU miner."
                    if native_available
                    else "Build the native C miner for faster CPU mining."
                ),
            },
            {
                "id": MINING_BACKEND_PYTHON,
                "label": "Python",
                "available": True,
                "can_build": False,
                "description": "Pure Python fallback miner.",
            },
        ],
    }


def build_mining_backend(backend: str) -> dict[str, Any]:
    requested_backend = normalize_mining_backend(backend)
    if requested_backend not in {
        MINING_BACKEND_AUTO,
        MINING_BACKEND_GPU,
        MINING_BACKEND_NATIVE,
    }:
        raise ValueError(f"Mining backend {requested_backend} does not need a build step.")
    extension_path = build_native_pow_extension(force=False)
    return {
        "built": True,
        "path": str(extension_path),
        "capabilities": mining_backend_capabilities(requested_backend),
    }
