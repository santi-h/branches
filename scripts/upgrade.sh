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
export PYENV_VERSION=branches

pyenv virtualenv-delete -f branches
pyenv install --skip-existing "$NEW_PYTHON_VERSION"
echo "$NEW_PYTHON_VERSION" > .python-version
pyenv virtualenv "$NEW_PYTHON_VERSION" branches
pyenv exec pip install -U pip pip-tools
pyenv exec pip-compile --output-file=requirements.txt requirements.in --upgrade
pyenv exec pip-compile --output-file=requirements-dev.txt requirements-dev.in --upgrade
pyenv exec pip-sync requirements-dev.txt

git add -A
git commit -m "Upgrade python \`$OLD_PYTHON_VERSION\` -> \`$NEW_PYTHON_VERSION\` and dependencies"

echo "-------------------------------------------------------------"
echo "Remember to update .github/workflows/ci.yml"
echo "Remember to update https://github.com/santi-h/branches/settings/rules/11918879"
