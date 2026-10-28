#!/usr/bin/env bash

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"

uv run --project "$ROOT_DIR" ruff check "$ROOT_DIR" --fix
uv run --project "$ROOT_DIR" ruff format "$ROOT_DIR"
