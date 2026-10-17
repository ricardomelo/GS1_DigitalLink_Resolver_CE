#!/usr/bin/env bash
# Monthly update of the GeoIP database the resolver reads to record the approximate location (country, region, city)
# of each request in its log (Documentation/adr/0006-resolver-request-log.md, section 8). The client's address is used
# for the lookup only and never stored.
#
# By default it downloads DB-IP's "IP to City Lite" of the current month (or of the previous one while the current is
# not out yet): free, no account, Creative Commons Attribution 4.0 ("IP Geolocation by DB-IP", https://db-ip.com — the
# portal shows the attribution beside the locations). GEOIP_URL (in .env or the environment) takes another source of a
# file in the same format, gzip-compressed or not: MaxMind's GeoLite2 City, for instance, with an account's licence key
# in the address. The file is checked (an MMDB, not too small) and replaces the old one in one step, so the resolver,
# which looks for a newer file at most once a minute, never reads half a file. A failed update keeps the old file, says
# ERROR and exits with status 1.
#
# Run it from the repository:  sudo scripts/geoip-update.sh
# Scheduled monthly by scripts/geoip-update.cron (the installer installs it and runs this once).
set -euo pipefail

RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
GEOIP_DIR="${GEOIP_DIR:-$RESOLVER_DIR/geoip}"            # mounted read only in the resolver as /geoip
GEOIP_FILE="${GEOIP_FILE:-dbip-city-lite.mmdb}"
GEOIP_MIN_BYTES="${GEOIP_MIN_BYTES:-1000000}"           # a city database is far larger; a smaller file is an error page
MARKER=$'\xab\xcd\xefMaxMind.com'                        # the MMDB format's metadata marker, near the file's end

cd "$RESOLVER_DIR"
if [ -z "${GEOIP_URL:-}" ]; then
  GEOIP_URL="$(sed -n "s/^GEOIP_URL=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true)"
fi
if [ -n "$GEOIP_URL" ]; then
  SOURCES=("$GEOIP_URL")
else
  SOURCES=()
  for month in "$(date -u +%Y-%m)" "$(date -u -d "$(date -u +%Y-%m-01) -1 day" +%Y-%m)"; do
    SOURCES+=("https://download.db-ip.com/free/dbip-city-lite-$month.mmdb.gz")
  done
fi

umask 022
mkdir -p "$GEOIP_DIR"
WORK="$(mktemp -d "$GEOIP_DIR/.update-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

for url in "${SOURCES[@]}"; do
  shown="${url%%\?*}"                                    # never print a query string (a licence key)
  rm -f "$WORK/download" "$WORK/database"
  if ! curl -fsSL --retry 2 --max-time 900 -o "$WORK/download" "$url"; then
    echo "$(date -Is) $shown: not downloaded"
    continue
  fi
  if gzip -t "$WORK/download" 2>/dev/null; then
    gzip -dc "$WORK/download" > "$WORK/database"
  else
    mv "$WORK/download" "$WORK/database"
  fi
  size=$(stat -c %s "$WORK/database")
  if [ "$size" -lt "$GEOIP_MIN_BYTES" ] || ! tail -c 131072 "$WORK/database" | LC_ALL=C grep -qaF "$MARKER"; then
    echo "$(date -Is) $shown: not a GeoIP database (MMDB) of the expected size ($size bytes)"
    continue
  fi
  chmod 644 "$WORK/database"
  mv -f "$WORK/database" "$GEOIP_DIR/$GEOIP_FILE"
  echo "$(date -Is) OK: $GEOIP_DIR/$GEOIP_FILE from $shown ($size bytes)"
  exit 0
done
echo "$(date -Is) ERROR: the GeoIP database was not updated; the resolver keeps the file it has (if any)"
exit 1
