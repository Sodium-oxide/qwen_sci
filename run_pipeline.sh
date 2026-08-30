#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if command -v qwensci >/dev/null 2>&1; then
    exec qwensci pipeline "$@"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/qwensci" ]]; then
    exec "$SCRIPT_DIR/.venv/bin/qwensci" pipeline "$@"
fi

exec python -m src pipeline "$@"
