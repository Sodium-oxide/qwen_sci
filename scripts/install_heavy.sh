#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$ROOT_DIR/.venv}"
export UV_PROJECT_ENVIRONMENT="$PROJECT_ENVIRONMENT"
VENV_PYTHON="$PROJECT_ENVIRONMENT/bin/python"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install the dependency groups"
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: ./scripts/install_heavy.sh [memory] [ml] [paper] [all]

Installs selected heavy dependency groups with uv while preserving the
project's headless-only OpenCV dependency override.
Examples:
  ./scripts/install_heavy.sh ml
  ./scripts/install_heavy.sh memory ml
  ./scripts/install_heavy.sh all

Pass package-index settings through uv environment variables if needed:
  UV_INDEX_URL=...
  UV_EXTRA_INDEX_URL=...
EOF
}

if [[ $# -eq 0 ]]; then
  set -- all
fi

declare -A selected_groups=()
declare -a sync_groups=()

for group in "$@"; do
  case "$group" in
    memory|ml|paper)
      if [[ -z "${selected_groups[$group]:-}" ]]; then
        selected_groups["$group"]=1
        if [[ "$group" == "paper" ]]; then
          sync_groups+=(--group pdf)
        else
          sync_groups+=(--group "$group")
        fi
      fi
      ;;
    all)
      if [[ -z "${selected_groups[memory]:-}" ]]; then
        selected_groups[memory]=1
        sync_groups+=(--group memory)
      fi
      if [[ -z "${selected_groups[ml]:-}" ]]; then
        selected_groups[ml]=1
        sync_groups+=(--group ml)
      fi
      if [[ -z "${selected_groups[paper]:-}" ]]; then
        selected_groups[paper]=1
        sync_groups+=(--group pdf)
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown group: $group" >&2
      usage >&2
      exit 1
      ;;
  esac
done

echo "syncing selected dependency groups with uv"
uv sync --locked --inexact "${sync_groups[@]}"

echo "removing GUI OpenCV distributions from the target environment"
uv pip uninstall --python "$VENV_PYTHON" opencv-python opencv-contrib-python || true

if [[ -n "${selected_groups[paper]:-}" ]]; then
  echo "repairing the headless OpenCV distribution"
  uv pip install --python "$VENV_PYTHON" --reinstall --no-deps \
    "opencv-python-headless==5.0.0.93"
  "$VENV_PYTHON" -c 'import cv2; assert hasattr(cv2, "INTER_NEAREST"); print(f"cv2={cv2.__version__} ({cv2.__file__})")'
fi
