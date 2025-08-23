# Branches

## Create the distribution file

```shell
rm -rf dist/ build/ && \
pip freeze | xargs pip uninstall -y && \
pip install -r requirements.txt && \
pip install pyinstaller && \
pyinstaller --onedir --name branches --paths src src/branches/__main__.py &&
rm -rf build/
```

The last line could be replaced with `pyinstaller branches.spec`

## Create github release

```shell
# from repo root after build
VERSION=0.1.0
BASENAME=branches-macos-arm64-$VERSION
cd dist
tar -czf $BASENAME.tar.gz branches/
shasum -a 256 $BASENAME.tar.gz > $BASENAME.sha256
git tag v$VERSION && git push origin v$VERSION
```

Then on GitHub, go to [New Release](https://github.com/santi-h/branches/releases/new) and fill out the fields. Remember to upload the .tar.gz and .sha256

For pre-releases, use versions with the following format examples:

- `VERSION=0.1.0-alpha`
- `VERSION=0.1.0-alpha.1`
- `VERSION=0.1.0-beta.3`
- `VERSION=0.1.0-rc.1`

Remember the precedence:
`0.1.0-alpha`< `0.1.0-alpha.1`< `0.1.0-beta.3`< `0.1.0-rc.1` < `0.1.0`

The first four are considered "pre-releases". For those, select the "Set as a pre-release" option in the Github UI.
