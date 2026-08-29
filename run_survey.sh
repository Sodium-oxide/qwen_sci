#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if command -v qwensci >/dev/null 2>&1; then
    exec qwensci survey "$@"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/qwensci" ]]; then
    exec "$SCRIPT_DIR/.venv/bin/qwensci" survey "$@"
fi

if command -v xcientist >/dev/null 2>&1; then
    exec xcientist survey "$@"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/xcientist" ]]; then
    exec "$SCRIPT_DIR/.venv/bin/xcientist" survey "$@"
fi

exec python -m src survey "$@"
