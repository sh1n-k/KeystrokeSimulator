#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

fail() {
    echo "[ERROR] $1"
    printf "Press Enter to close..."
    read -r _
    exit 1
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
    fail "uv is not installed or not on PATH. Install guide: https://docs.astral.sh/uv/getting-started/installation/"
fi

"$UV_BIN" python install 3.13 || fail "Failed to install or locate Python 3.13."
"$UV_BIN" sync --locked || fail "Failed to sync the locked environment."

if [[ "${1:-}" == "--check" ]]; then
    echo "Environment check passed."
    exit 0
fi

"$UV_BIN" run python main.py || fail "Failed to launch main.py."
