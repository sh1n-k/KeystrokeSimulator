#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

fail() {
    echo "[ERROR] $1"
    printf "Press Enter to close..."
    read -r _
    exit 1
}

info() {
    echo "[INFO] $1"
}

is_python_313() {
    local candidate="$1"
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)' >/dev/null 2>&1
}

resolve_python() {
    local candidate
    for candidate in "${PYTHON_BIN:-}" "$VENV_PY" python3.13 python3; do
        if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1; then
            if is_python_313 "$candidate"; then
                command -v "$candidate"
                return 0
            fi
        elif [[ -n "$candidate" && -x "$candidate" ]]; then
            if is_python_313 "$candidate"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done

    return 1
}

bootstrap_with_pip() {
    local python_bin requirements_file

    python_bin="$(resolve_python)" || fail "Python 3.13 is required when uv is unavailable. Install Python 3.13 or install uv: https://docs.astral.sh/uv/getting-started/installation/"

    if [[ -x "$VENV_PY" ]] && ! is_python_313 "$VENV_PY"; then
        fail "Existing .venv is not using Python 3.13. Remove .venv and rerun this launcher, or set PYTHON_BIN to a Python 3.13 executable."
    fi

    if [[ ! -x "$VENV_PY" ]]; then
        info "uv not found. Creating local virtual environment with $python_bin"
        "$python_bin" -m venv "$VENV_DIR" || fail "Failed to create .venv with $python_bin."
    fi

    if ! "$VENV_PY" - <<'PY' >/dev/null 2>&1
import importlib
import sys

module_names = [
    "dotenv",
    "loguru",
    "mss",
    "numpy",
    "PIL",
    "pygame",
    "pynput",
    "requests",
    "screeninfo",
]

if sys.platform == "darwin":
    module_names.extend(["AppKit", "ApplicationServices", "Quartz"])

for module_name in module_names:
    importlib.import_module(module_name)
PY
    then
        requirements_file="$(mktemp)"
        "$python_bin" - <<'PY' > "$requirements_file"
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
for dependency in data["project"]["dependencies"]:
    print(dependency)
PY

        info "Installing project dependencies into .venv using pip"
        "$VENV_PY" -m pip install -r "$requirements_file" || {
            rm -f "$requirements_file"
            fail "Failed to install project dependencies with pip."
        }
        rm -f "$requirements_file"
    else
        info "Reusing existing .venv runtime environment"
    fi

    if [[ "${1:-}" == "--check" ]]; then
        echo "Environment check passed (.venv + pip fallback)."
        exit 0
    fi

    "$VENV_PY" main.py || fail "Failed to launch main.py with the local virtual environment."
    exit 0
}

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
    else
        for candidate in "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
            if [[ -x "$candidate" ]]; then
                UV_BIN="$candidate"
                break
            fi
        done
    fi
fi

if [[ -z "$UV_BIN" ]]; then
    bootstrap_with_pip "${1:-}"
fi

"$UV_BIN" python install 3.13 || fail "Failed to install or locate Python 3.13."
"$UV_BIN" sync --locked || fail "Failed to sync the locked environment."

if [[ "${1:-}" == "--check" ]]; then
    echo "Environment check passed."
    exit 0
fi

"$UV_BIN" run python main.py || fail "Failed to launch main.py."
