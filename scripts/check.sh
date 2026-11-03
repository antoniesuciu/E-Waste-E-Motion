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

check_frontend() {
    (cd frontend && npm run build)
    test -s static/bundle.js
    test -s static/style.css
}

case "${1:-all}" in
    backend) check_backend ;;
    frontend) check_frontend ;;
    all) check_backend; check_frontend ;;
    *) echo "Usage: bash scripts/check.sh [all|backend|frontend]" >&2; exit 2 ;;
esac
