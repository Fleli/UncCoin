#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _npm_command() -> str | None:
    if os.name == "nt":
        return shutil.which("npm.cmd") or shutil.which("npm")
    return shutil.which("npm")


def _run(label: str, command: list[str]) -> int:
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(command), flush=True)
    env = os.environ.copy()
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    result = subprocess.run(command, cwd=ROOT_DIR, env=env)
    if result.returncode != 0:
        print(
            f"\n{label} failed with exit code {result.returncode}.",
            file=sys.stderr,
        )
    return result.returncode


def main() -> int:
    checks = [
        (
            "Python tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        )
    ]

    npm = _npm_command()
    if npm is None:
        print(
            "npm was not found. Install Node.js/npm, then run "
            "./scripts/setup_desktop.sh before checking the desktop app.",
            file=sys.stderr,
        )
        return 127

    if not (ROOT_DIR / "desktop" / "node_modules").exists():
        print(
            "desktop/node_modules is missing. Run ./scripts/setup_desktop.sh "
            "before the desktop build check."
        )

    checks.append(("Desktop build", [npm, "--prefix", "desktop", "run", "build"]))

    for label, command in checks:
        exit_code = _run(label, command)
        if exit_code != 0:
            return exit_code

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
