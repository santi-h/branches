#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"

cd "$ROOT_DIR"

rm -rf .venv
uv sync
