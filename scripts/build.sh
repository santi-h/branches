#!/usr/bin/env zsh
# This script assumes:
# - it's being run on arm64 MacOS
# - pip-sync requirements-dev.txt was run
set -euo pipefail

ME=`basename "$0"`
ME_LOCATION=`dirname "$0"`
ROOT_DIR="$(realpath "$ME_LOCATION/..")"
PYTHON_VERSION=$(cat "$ROOT_DIR/.python-version")
BRANCHES_VERSION=$(PYTHONPATH="$ROOT_DIR/src" python -c "from branches import VERSION; print(VERSION)")

echo "        ROOT_DIR=$ROOT_DIR"
echo "  PYTHON_VERSION=$PYTHON_VERSION"
echo "BRANCHES_VERSION=$BRANCHES_VERSION"

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist"

pyinstaller --onedir \
            --name branches \
            --workpath "$ROOT_DIR/build/macos/arm64" \
            --distpath "$ROOT_DIR/dist/macos/arm64" \
            --paths "$ROOT_DIR/src" \
            "$ROOT_DIR/src/branches/__main__.py"

docker run --rm -it \
  --platform=linux/arm64 \
  -v "$ROOT_DIR":/work \
  -w /work \
  python:$PYTHON_VERSION-slim bash -lc '
    set -euo pipefail
    apt-get update
    apt-get install -y --no-install-recommends binutils
    rm -rf /var/lib/apt/lists/*

    pip install -U pip
    pip install -U pip-tools
    pip-sync requirements-dev.txt
    pyinstaller --onedir \
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

    pip install -U pip
    pip install -U pip-tools
    pip-sync requirements-dev.txt
    pyinstaller --onedir \
                --name branches \
                --workpath build/linux/amd64 \
                --distpath dist/linux/amd64 \
                --paths src \
                src/branches/__main__.py
  '

for pair_path in linux/amd64 linux/arm64 macos/arm64; do
  TAR_BASENAME=$ROOT_DIR/dist/branches-"${pair_path//\//-}"-$BRANCHES_VERSION

  tar -czf "$TAR_BASENAME.tar.gz" -C "$ROOT_DIR/dist/$pair_path/branches" .
  shasum -a 256 "$TAR_BASENAME.tar.gz" > "$TAR_BASENAME.sha256"
done

rm -rf "$ROOT_DIR/build"
