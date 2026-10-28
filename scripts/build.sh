#!/usr/bin/env zsh
# This script assumes:
# - it's being run on arm64 MacOS
# - uv is installed
set -euo pipefail

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"
PYTHON_VERSION=$(cat "$ROOT_DIR/.python-version")

# The macOS executable bundles the interpreter and the shared libraries it links against, so they
# determine the oldest macOS it runs on. Pyenv/Homebrew pythons link against Homebrew libraries
# built for the current macOS, so only use uv's python-build-standalone interpreters (built for
# old macOS versions), in a throwaway venv so an existing .venv can't leak in a different python.
export UV_PYTHON_PREFERENCE=only-managed
export UV_PROJECT_ENVIRONMENT="$ROOT_DIR/build/venv"
MAX_MACOS_MINOS=${MAX_MACOS_MINOS:-14.0}

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist"

BRANCHES_VERSION=$(PYTHONPATH="$ROOT_DIR/src" uv run --frozen --project "$ROOT_DIR" python -c "from branches import VERSION; print(VERSION)")

echo "        ROOT_DIR=$ROOT_DIR"
echo "  PYTHON_VERSION=$PYTHON_VERSION"
echo "BRANCHES_VERSION=$BRANCHES_VERSION"
echo " MAX_MACOS_MINOS=$MAX_MACOS_MINOS"

uv run --frozen --project "$ROOT_DIR" pyinstaller --onedir \
            --name branches \
            --workpath "$ROOT_DIR/build/macos/arm64" \
            --distpath "$ROOT_DIR/dist/macos/arm64" \
            --paths "$ROOT_DIR/src" \
            "$ROOT_DIR/src/branches/__main__.py"

# Fail if anything in the macOS bundle requires a newer macOS than MAX_MACOS_MINOS
TOO_NEW=$(
  find "$ROOT_DIR/dist/macos/arm64/branches" -type f \( -name '*.dylib' -o -name '*.so' -o -name branches \) |
  while read -r f; do
    minos=$(otool -l "$f" | awk '/minos/{print $2; exit}')
    if [[ -n $minos && $(printf '%s\n%s\n' "$minos" "$MAX_MACOS_MINOS" | sort -V | tail -1) != "$MAX_MACOS_MINOS" ]]; then
      echo "$minos $f"
    fi
  done
)
if [[ -n $TOO_NEW ]]; then
  echo "ERROR: macOS bundle requires macOS newer than $MAX_MACOS_MINOS:" >&2
  echo "$TOO_NEW" >&2
  exit 1
fi

docker run --rm -it \
  --platform=linux/arm64 \
  -v "$ROOT_DIR":/work \
  -w /work \
  python:$PYTHON_VERSION-slim bash -lc '
    set -euo pipefail
    apt-get update
    apt-get install -y --no-install-recommends binutils
    rm -rf /var/lib/apt/lists/*

    pip install -U uv
    export UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=python
    uv sync --frozen
    uv run --frozen pyinstaller --onedir \
                --name branches \
                --workpath build/linux/arm64 \
                --distpath dist/linux/arm64 \
                --paths src \
                src/branches/__main__.py
  '

docker run --rm -it \
  --platform=linux/amd64 \
  -v "$ROOT_DIR":/work \
  -w /work \
  python:$PYTHON_VERSION-slim bash -lc '
    set -euo pipefail
    apt-get update
    apt-get install -y --no-install-recommends binutils
    rm -rf /var/lib/apt/lists/*

    pip install -U uv
    export UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=python
    uv sync --frozen
    uv run --frozen pyinstaller --onedir \
                --name branches \
                --workpath build/linux/amd64 \
                --distpath dist/linux/amd64 \
                --paths src \
                src/branches/__main__.py
  '

for pair_path in linux/amd64 linux/arm64 macos/arm64; do
  TAR_BASENAME=branches-"${pair_path//\//-}"-$BRANCHES_VERSION

  tar -czf "$ROOT_DIR/dist/$TAR_BASENAME.tar.gz" -C "$ROOT_DIR/dist/$pair_path/branches" .
  ( cd "$ROOT_DIR/dist" && shasum -a 256 "$TAR_BASENAME.tar.gz" > "$TAR_BASENAME.sha256" )
done

rm -rf "$ROOT_DIR/build"
