#!/usr/bin/env zsh
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <new-python-version>" >&2
  exit 1
fi

ROOT_DIR="$(realpath "$(dirname "$0")"/..)"
NEW_PYTHON_VERSION=$1
OLD_PYTHON_VERSION=$(cat "$ROOT_DIR/.python-version")

cd "$ROOT_DIR"

echo "$NEW_PYTHON_VERSION" > .python-version
uv lock --upgrade
uv sync

git add -A
git commit -m "Upgrade python \`$OLD_PYTHON_VERSION\` -> \`$NEW_PYTHON_VERSION\` and dependencies"

echo "-------------------------------------------------------------"
echo "Remember to update .github/workflows/ci.yml"
echo "Remember to update https://github.com/santi-h/branches/settings/rules/11918879"
