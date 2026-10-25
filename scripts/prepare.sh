#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"
PYTHON_VERSION=$(cat "$ROOT_DIR/.python-version")

cd "$ROOT_DIR"
export PYENV_VERSION=branches

pyenv virtualenv-delete -f branches
pyenv install --skip-existing "$PYTHON_VERSION"
pyenv virtualenv "$PYTHON_VERSION" branches
pyenv exec pip install -U pip pip-tools
pyenv exec pip-sync requirements-dev.txt
