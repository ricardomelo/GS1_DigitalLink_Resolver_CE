#!/usr/bin/env bash
# Builds the GS1 Barcode Syntax Engine (https://github.com/gs1/gs1-syntax-engine) for the portal:
# the native library, its Python binding and the GS1 Barcode Syntax Dictionary of the same release.
# The portal uses them to validate GS1 Digital Link data attributes (portal/syntax.py).
#
#   portal/tools/build-syntax-engine.sh <destination directory> [release]
#
# Used by portal/Dockerfile and by the development tests. Needs curl, tar, make and a C compiler.
# The release is pinned so that validation does not change without a deliberate update; keep it in
# step with the gs1encoder package the resolver installs (web_server/Dockerfile).
set -euo pipefail

DEST=${1:?destination directory}
RELEASE=${2:-1.4.1}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

curl -fsSL "https://github.com/gs1/gs1-syntax-engine/archive/refs/tags/${RELEASE}.tar.gz" | tar -xz -C "$WORK"
SRC="$WORK/gs1-syntax-engine-${RELEASE}/src"
make -s -C "$SRC/c-lib" libshared >/dev/null

mkdir -p "$DEST"
cp -L "$SRC/c-lib/build/libgs1encoders.so" "$DEST/libgs1encoders.so"
cp "$SRC/contrib/python3/gs1encoders.py" "$DEST/gs1encoders.py"
cp "$SRC/c-lib/gs1-syntax-dictionary.txt" "$DEST/gs1-syntax-dictionary.txt"
cp "$WORK/gs1-syntax-engine-${RELEASE}/LICENSE" "$DEST/LICENSE"
echo "$RELEASE" > "$DEST/RELEASE"
echo "GS1 Barcode Syntax Engine $RELEASE built in $DEST"
