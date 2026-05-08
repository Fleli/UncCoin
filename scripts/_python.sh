#!/usr/bin/env bash

unccoin_venv_python() {
  local root_dir="$1"
  if [[ -x "$root_dir/.venv/bin/python" ]]; then
    printf '%s\n' "$root_dir/.venv/bin/python"
    return 0
  fi
  if [[ -x "$root_dir/.venv/Scripts/python.exe" ]]; then
    printf '%s\n' "$root_dir/.venv/Scripts/python.exe"
    return 0
  fi
  return 1
}

unccoin_python() {
  local root_dir="$1"
  if [[ -n "${UNCCOIN_PYTHON:-}" ]]; then
    printf '%s\n' "$UNCCOIN_PYTHON"
    return 0
  fi
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return 0
  fi
  if unccoin_venv_python "$root_dir"; then
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  printf '%s\n' "python"
}
