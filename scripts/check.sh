#!/usr/bin/env bash
# Run from any directory. Dependencies must already be installed.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

check_backend() {
    local python_bin="${PYTHON_BIN:-python3}"
    if [[ -z "${PYTHON_BIN:-}" && -x .venv/bin/python ]]; then
        python_bin="$repo_root/.venv/bin/python"
    fi
    "$python_bin" -m compileall -q src tests
    "$python_bin" -m unittest discover -s tests -v
}

check_firmware() {
    # Host-side test of pure firmware logic; the sketch itself needs arduino-cli + the ESP32 core.
    local bin
    bin="$(mktemp)"
    trap 'rm -f "$bin"' RETURN
    "${CC:-cc}" -std=c99 -Wall -Wextra -Werror -o "$bin" firmware/test/test_encoder_math.c
    "$bin"
}

check_frontend() {
    (cd frontend && npm run build)
    test -s static/bundle.js
    test -s static/style.css
}

case "${1:-all}" in
    backend) check_backend ;;
    firmware) check_firmware ;;
    frontend) check_frontend ;;
    all) check_backend; check_firmware; check_frontend ;;
    *) echo "Usage: bash scripts/check.sh [all|backend|firmware|frontend]" >&2; exit 2 ;;
esac
