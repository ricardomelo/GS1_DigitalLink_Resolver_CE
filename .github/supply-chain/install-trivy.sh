#!/usr/bin/env bash
# Installs Trivy, the scanner of the images' known vulnerabilities and the writer of their CycloneDX SBOMs
# (.github/workflows/supply-chain.yml; Documentation/adr/0033-supply-chain.md, section 2.2), from its GitHub
# release, by version, and refuses a file whose SHA-256 is not the one written here: no third-party action, no
# "latest", no install script.
#
#   .github/supply-chain/install-trivy.sh <directory>     # puts <directory>/trivy
#
# Updating (by hand: Dependabot does not see it): read the release notes, take a release at least two weeks old,
# and copy the Linux-64bit line of its trivy_<version>_checksums.txt into TRIVY_SHA256.
set -euo pipefail
TRIVY_VERSION=0.76.2
TRIVY_SHA256=bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf

dest=${1:?usage: install-trivy.sh <directory>}
file="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL --retry 3 -o "$tmp/$file" "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${file}"
echo "${TRIVY_SHA256}  $tmp/$file" | sha256sum --check --strict -
mkdir -p "$dest"
tar -xzf "$tmp/$file" -C "$dest" trivy
"$dest/trivy" --version
