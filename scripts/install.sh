#!/usr/bin/env bash
set -eu # Strict mode. Exit if any any command (like `checksum`) returns non-zero

TAG_NAME=$(
  curl -s https://api.github.com/repos/santi-h/branches/releases/latest |
  grep -m1 '"tag_name"' |
  sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/'
)

case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
  darwin) NORM_OS="macos" ;;
  linux)  NORM_OS="linux" ;;
  *)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

case "$(uname -m | tr '[:upper:]' '[:lower:]')" in
  x86_64)  NORM_ARCH="amd64" ;;
  aarch64) NORM_ARCH="arm64" ;;
  arm64)   NORM_ARCH="arm64" ;;
  *)
    echo "Unsupported Arch: $(uname -m)" >&2
    exit 1
    ;;
esac

TMPDIR="$(mktemp -d)"
VERSION="${TAG_NAME#v}"
BASENAME="branches-$NORM_OS-$NORM_ARCH-$VERSION"
FILENAME_TARBALL="$BASENAME.tar.gz"
FILENAME_SHA="$BASENAME.sha256"
FILEPATH_DOWNLOADED_TARBALL="$TMPDIR/$FILENAME_TARBALL"
FILEPATH_DOWNLOADED_SHA="$TMPDIR/$FILENAME_SHA"
DIRPATH_FOR_INSTALLATION="$HOME/.local/opt/branches/$VERSION"
DIRPATH_FOR_BIN_LN="$HOME/.local/bin"

echo "                     TMPDIR=$TMPDIR"
echo "                    VERSION=$VERSION"
echo "                  NORM_ARCH=$NORM_ARCH"
echo "                    NORM_OS=$NORM_OS"
echo "                   BASENAME=$BASENAME"
echo "           FILENAME_TARBALL=$FILENAME_TARBALL"
echo "               FILENAME_SHA=$FILENAME_SHA"
echo "FILEPATH_DOWNLOADED_TARBALL=$FILEPATH_DOWNLOADED_TARBALL"
echo "    FILEPATH_DOWNLOADED_SHA=$FILEPATH_DOWNLOADED_SHA"
echo "   DIRPATH_FOR_INSTALLATION=$DIRPATH_FOR_INSTALLATION"
echo "         DIRPATH_FOR_BIN_LN=$DIRPATH_FOR_BIN_LN"
echo

curl -fL \
  -o "$FILEPATH_DOWNLOADED_TARBALL" \
  "https://github.com/santi-h/branches/releases/download/$TAG_NAME/$FILENAME_TARBALL"

curl -fL \
  -o "$FILEPATH_DOWNLOADED_SHA" \
  "https://github.com/santi-h/branches/releases/download/$TAG_NAME/$FILENAME_SHA"

if command -v shasum >/dev/null 2>&1; then
  (cd "$TMPDIR" && shasum -a 256 -c "$FILEPATH_DOWNLOADED_SHA")
elif command -v sha256sum >/dev/null 2>&1; then
  (cd "$TMPDIR" && sha256sum -c "$FILEPATH_DOWNLOADED_SHA")
else
  echo "Warning: shasum and sha256sum not found; skipping checksum verification." >&2
fi

flags=""
if [ "$NORM_OS" = "linux" ]; then
  flags="--warning=no-unknown-keyword"
fi
mkdir -p "$DIRPATH_FOR_INSTALLATION" "$DIRPATH_FOR_BIN_LN"
tar --no-xattrs $flags -xzf "$FILEPATH_DOWNLOADED_TARBALL" -C "$DIRPATH_FOR_INSTALLATION"
ln -sfn "$DIRPATH_FOR_INSTALLATION/branches" "$DIRPATH_FOR_BIN_LN"

echo
echo "Installation complete, make sure $DIRPATH_FOR_BIN_LN is in your PATH"
