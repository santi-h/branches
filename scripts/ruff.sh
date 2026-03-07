#!/usr/bin/env bash

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"
VIRTUALENV="$(basename "$(basename "$ROOT_DIR")")"

$PYENV_ROOT/versions/$VIRTUALENV/bin/python -m ruff check "$ROOT_DIR" --fix
$PYENV_ROOT/versions/$VIRTUALENV/bin/python -m ruff format "$ROOT_DIR"
