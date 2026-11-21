#!/usr/bin/env bash
# Writes the Python lock files (Documentation/adr/0033-supply-chain.md): every package, direct or not, at one
# version, with the SHA-256 of each of its files on PyPI, so that pip installs exactly what was locked
# (--require-hashes) and refuses a file replaced since.
#
#   dev-tests/lock-dependencies.sh                       # keep the locked versions, add what an .in file gained
#   dev-tests/lock-dependencies.sh --upgrade             # the newest versions the .in files allow
#   dev-tests/lock-dependencies.sh --upgrade-package X   # the newest X only (repeatable)
#
# The development tests' environment (dev-tests/requirements.in: the three services and the test tools) is
# resolved first, for Python 3.12 (the images' version) and every platform; each service's lock is then
# resolved inside it (-c), so that a package has the same version in every image and in the tests.
# The supply-chain workflow's tools (.github/supply-chain/requirements.in) are locked last, on their own.
# Needs uv (https://docs.astral.sh/uv/) and PyPI. Then run every development test and commit the .in and .txt
# files together; dev-tests/install/test_supply_chain.py fails when they are out of step.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

compile() {  # <input .in> <output .txt> [extra uv arguments]
  local in=$1 out=$2; shift 2
  uv pip compile --quiet --universal --python-version 3.12 --generate-hashes \
    --custom-compile-command "dev-tests/lock-dependencies.sh" "$@" "$in" -o "$out"
  echo "$out: $(grep -cE '^[A-Za-z0-9]' "$out") packages"
}
compile dev-tests/requirements.in dev-tests/requirements.txt "$@"
for service in portal web_server/src data_entry_server/src; do
  compile "$service/requirements.in" "$service/requirements.txt" -c dev-tests/requirements.txt
done
# The supply-chain workflow's own tools (pip-audit): never in an image or the tests, so resolved on their own
compile .github/supply-chain/requirements.in .github/supply-chain/requirements.txt "$@"
