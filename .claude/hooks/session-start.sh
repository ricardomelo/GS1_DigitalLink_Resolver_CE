#!/bin/bash
# Prepares a Claude Code cloud session for the development tests (dev-tests/README.md): the same pieces
# and pinned versions as the CI setup (.github/actions/dev-tests-setup/action.yml), installed once into
# ~/.cache/dev-tests and kept by the environment's cache, and the variables the test programs read.
# Idempotent: a piece already present is not fetched again. Runs only in cloud sessions.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

DEV_TOOLS="$HOME/.cache/dev-tests"
GS1ENCODER_VERSION=$(sed -n 's/^x-gs1-syntax-engine: *&gs1-syntax-engine *"\([^"]*\)".*/\1/p' docker-compose.yml)
[[ -n $GS1ENCODER_VERSION ]] || { echo "x-gs1-syntax-engine not found in docker-compose.yml" >&2; exit 1; }
EPC_TDS_VERSION=1.4.1
AJV_DIST_VERSION=8.17.1
GS1_TESTSUITE_COMMIT=32597c108ac1ecb9e90ce0081bb3a16e5a61e616
GS1_WEBVOC_COMMIT=f8f407bf717233c871dca2f62f4e45b0940e8cad   # GS1 Web Vocabulary 1.16, the link types' source
COMPOSE_VERSION=v2.29.7
NGINX_VERSION=1.30.5
# Playwright stays on the release whose Chromium (1194) was pre-installed in /opt/pw-browsers; a newer build
# there is linked under 1194's names (below).
PLAYWRIGHT_VERSION=1.56.0
mkdir -p "$DEV_TOOLS/bin"

# Python packages (pip skips what is already installed)
python3 -m pip install -q --break-system-packages --ignore-installed blinker \
  -r web_server/src/requirements.txt -r portal/requirements.txt -r data_entry_server/src/requirements.txt \
  pytest jsonschema "playwright==$PLAYWRIGHT_VERSION" opencv-python-headless pillow pypdf mongomock "zxing-cpp>=2.2,<4" \
  "mmdb-writer>=0.2.7,<0.3"

# Chromium for Playwright: the builds the pinned release wants (its browsers.json) when /opt/pw-browsers has them;
# otherwise the newest ones there, linked under the wanted builds' names in $DEV_TOOLS/pw-browsers. The image moved
# from 1194 to 1243 (October 2026), with another folder layout, and every browser program failed to start.
PW_BROWSERS=/opt/pw-browsers
read -r PW_CHROMIUM PW_HEADLESS < <(python3 -c 'import json, os, playwright
d = {b["name"]: b["revision"] for b in json.load(open(os.path.join(os.path.dirname(playwright.__file__),
     "driver", "package", "browsers.json")))["browsers"]}
print(d["chromium"], d["chromium-headless-shell"])')
[[ -n ${PW_HEADLESS:-} ]] || { echo "Playwright's browsers.json not read" >&2; exit 1; }
pw_alias() {  # <folder name> <wanted revision> <executable the pinned release starts> <its name in newer builds>
  local wanted="$PW_PATH/$1-$2" newest exe
  newest=$(ls -d "$PW_BROWSERS/$1"-[0-9]* 2>/dev/null | sort -V | tail -1 || true)
  [[ -n $newest ]] || { echo "no $1 build in $PW_BROWSERS" >&2; exit 1; }
  exe=$(find "$newest" -maxdepth 2 -type f \( -name "$3" -o -name "$4" \) | head -1 || true)
  [[ -n $exe ]] || { echo "no $3 or $4 in $newest" >&2; exit 1; }
  rm -rf "$wanted" && mkdir -p "$wanted/chrome-linux"
  ln -s "$(dirname "$exe")"/* "$wanted/chrome-linux/"
  [[ -e "$wanted/chrome-linux/$3" ]] || ln -s "$exe" "$wanted/chrome-linux/$3"
  touch "$wanted/INSTALLATION_COMPLETE" "$wanted/DEPENDENCIES_VALIDATED"
}
if [[ -d "$PW_BROWSERS/chromium-$PW_CHROMIUM" && -d "$PW_BROWSERS/chromium_headless_shell-$PW_HEADLESS" ]]; then
  PW_PATH=$PW_BROWSERS
else
  PW_PATH="$DEV_TOOLS/pw-browsers"
  mkdir -p "$PW_PATH"
  pw_alias chromium "$PW_CHROMIUM" chrome chrome
  pw_alias chromium_headless_shell "$PW_HEADLESS" headless_shell chrome-headless-shell
  for other in "$PW_BROWSERS"/*; do  # ffmpeg and the rest, as they are
    case "$(basename "$other")" in chromium-[0-9]*|chromium_headless_shell-[0-9]*) ;; *) ln -sfn "$other" "$PW_PATH/" ;; esac
  done
fi

# npm packages: the resolver's engine, the EPC library and the JSON schema validator of GS1's suite
npm_package() {  # <folder> <package@version> [module]
  local dir="$DEV_TOOLS/$1"
  [[ -f "$dir/.installed-$2" ]] && return 0
  rm -rf "$dir" && mkdir -p "$dir"
  (cd "$dir" && npm init -y >/dev/null && { [[ ${3:-} == module ]] && npm pkg set type=module || true; } \
    && npm install -q --no-fund --no-audit "$2" >/dev/null)
  touch "$dir/.installed-$2"
}
npm_package se "gs1encoder@$GS1ENCODER_VERSION" module
npm_package et "epc-tds@$EPC_TDS_VERSION"
npm_package ajv "ajv-dist@$AJV_DIST_VERSION"

# The portal's build of the GS1 Barcode Syntax Engine: the same files as portal/tools/build-syntax-engine.sh,
# from a git clone, because the session's proxy refuses the release tarball that script downloads
if [[ "$(cat "$DEV_TOOLS/gs1se/RELEASE" 2>/dev/null)" != "$GS1ENCODER_VERSION" ]]; then
  rm -rf "$DEV_TOOLS/gs1se"
  src=$(mktemp -d)
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$GS1ENCODER_VERSION" https://github.com/gs1/gs1-syntax-engine "$src"
  S="$src/src"
  make -s -C "$S/c-lib" libshared >/dev/null
  mkdir -p "$DEV_TOOLS/gs1se/source"
  cp -L "$S/c-lib/build/libgs1encoders.so" "$DEV_TOOLS/gs1se/"
  cp "$S/contrib/python3/gs1encoders.py" "$S/c-lib/gs1-syntax-dictionary.txt" "$src/LICENSE" "$DEV_TOOLS/gs1se/"
  cp "$S/c-lib/tr_EN.h" "$S/c-lib/syntax/gs1syntaxdictionary.c" "$S/c-lib/syntax/gs1syntaxdictionary.h" \
    "$DEV_TOOLS/gs1se/source/"
  echo "$GS1ENCODER_VERSION" > "$DEV_TOOLS/gs1se/RELEASE"
  rm -rf "$src"
fi

# GS1's resolver test suite at the commit of the conformance review
if [[ "$(git -C "$DEV_TOOLS/gs1-testsuite" rev-parse HEAD 2>/dev/null)" != "$GS1_TESTSUITE_COMMIT" ]]; then
  rm -rf "$DEV_TOOLS/gs1-testsuite"
  git clone -q https://github.com/gs1/GS1DL-resolver-testsuite "$DEV_TOOLS/gs1-testsuite"
  git -c advice.detachedHead=false -C "$DEV_TOOLS/gs1-testsuite" checkout -q "$GS1_TESTSUITE_COMMIT"
fi

# The GS1 Web Vocabulary, the source of the portal's link types (portal/tools/gen_link_types.py)
if [[ "$(git -C "$DEV_TOOLS/gs1-webvoc" rev-parse HEAD 2>/dev/null)" != "$GS1_WEBVOC_COMMIT" ]]; then
  rm -rf "$DEV_TOOLS/gs1-webvoc"
  git clone -q https://github.com/gs1/WebVoc "$DEV_TOOLS/gs1-webvoc"
  git -c advice.detachedHead=false -C "$DEV_TOOLS/gs1-webvoc" checkout -q "$GS1_WEBVOC_COMMIT"
fi

# Docker Compose v2, for the installer test's "docker compose config"
if [[ ! -x "$DEV_TOOLS/bin/docker-compose" ]]; then
  curl -fsSL -o "$DEV_TOOLS/bin/docker-compose" \
    "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64"
  chmod +x "$DEV_TOOLS/bin/docker-compose"
fi

# Ubuntu's nginx for the installer test (service stopped) and nginx 1.30 built from source for the proxy
# test ("resolve" in upstream blocks needs 1.27.3 or later; Ubuntu 24.04 ships 1.24)
if ! command -v nginx >/dev/null; then
  apt-get update -q >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx libpcre2-dev zlib1g-dev libssl-dev >/dev/null
  service nginx stop >/dev/null 2>&1 || true
fi
if ! "$DEV_TOOLS/nginx/sbin/nginx" -v 2>&1 | grep -q "nginx/$NGINX_VERSION"; then
  src=$(mktemp -d)
  git clone -q --depth 1 --branch "release-$NGINX_VERSION" https://github.com/nginx/nginx.git "$src"
  (cd "$src" && ./auto/configure --prefix="$DEV_TOOLS/nginx" --with-http_ssl_module >/dev/null \
    && make -j"$(nproc)" >/dev/null && make install >/dev/null)
  rm -rf "$src"
fi

# The variables the test programs read
if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
  cat >> "$CLAUDE_ENV_FILE" <<VARS
export GS1_SYNTAX_ENGINE="$DEV_TOOLS/se"
export GS1_SYNTAX_ENGINE_DIR="$DEV_TOOLS/gs1se"
export EPC_TDS="$DEV_TOOLS/et"
export AJV_DIST="$DEV_TOOLS/ajv/node_modules/ajv-dist"
export GS1_RESOLVER_TESTSUITE="$DEV_TOOLS/gs1-testsuite"
export GS1_WEB_VOCABULARY="$DEV_TOOLS/gs1-webvoc/v1.16/gs1Voc.jsonld"
export COMPOSE_BIN="$DEV_TOOLS/bin/docker-compose"
export NGINX_BIN="$DEV_TOOLS/nginx/sbin/nginx"
export PLAYWRIGHT_BROWSERS_PATH="$PW_PATH"
export PYTHONUNBUFFERED=1
VARS
fi
echo "Development test environment ready in $DEV_TOOLS"
