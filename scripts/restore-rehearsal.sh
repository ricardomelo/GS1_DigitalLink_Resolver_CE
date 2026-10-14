#!/usr/bin/env bash
# Restore rehearsal of a GS1 Resolver CE backup (item 7.2): restores a database archive of scripts/resolver-backup.sh
# into a throw-away MongoDB container — the installation's own database image, no network, no published port, nothing
# shared with the running installation — and compares what it holds with the live database, collection by collection.
# The running installation is only read. Proves that the backups can be restored before the day they are needed.
#
#   sudo scripts/restore-rehearsal.sh                       # the newest archive in /var/backups/resolver
#   sudo scripts/restore-rehearsal.sh /path/to/resolver-2026-10-14_0230.archive.gz
#
# Exit status 0 when the archive restored and every database the installation needs is in it with documents (the
# resolver's records, the portal's users); 1 otherwise. Settings can be overridden from the environment.
set -euo pipefail

RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/resolver}"
CONTAINER="${REHEARSAL_CONTAINER:-resolver-restore-rehearsal}"
WAIT_SECONDS="${REHEARSAL_WAIT_SECONDS:-60}"
cd "$RESOLVER_DIR"

archive="${1:-}"
if [[ -z $archive ]]; then
  archive="$(ls -1t "$BACKUP_DIR"/resolver-*.archive.gz 2>/dev/null | head -n 1 || true)"
  [[ -n $archive ]] || { echo "ERROR: no archive in $BACKUP_DIR (run scripts/resolver-backup.sh first)"; exit 1; }
fi
[[ -s $archive ]] || { echo "ERROR: $archive is missing or empty"; exit 1; }

# The names the installation uses (from .env, else .env.example's defaults)
setting() {
  sed -n "s/^$1=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true
}
portal_db="$(setting PORTAL_DB_NAME)"; portal_db="${portal_db:-resolver_portal}"
records_db="resolver_ce"

image="$(docker compose images -q database-service 2>/dev/null | head -n 1 || true)"
[[ -n $image ]] || { echo "ERROR: the database service's image was not found (docker compose images database-service)"; exit 1; }

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
echo "Archive:   $archive ($(du -h "$archive" | cut -f1))"
echo "Container: $CONTAINER (image $image, no network)"
docker run -d --name "$CONTAINER" --network none "$image" >/dev/null

waited=0
until docker exec "$CONTAINER" mongosh --quiet --eval 'db.runCommand({ping: 1}).ok' >/dev/null 2>&1; do
  (( waited >= WAIT_SECONDS )) && { echo "ERROR: the rehearsal's MongoDB did not start in ${WAIT_SECONDS}s"; exit 1; }
  sleep 2; waited=$(( waited + 2 ))
done

if ! docker exec -i "$CONTAINER" mongorestore --archive --gzip --quiet < "$archive"; then
  echo "ERROR: mongorestore could not restore the archive"; exit 1
fi

# Documents per database.collection, one "name count" line each (system and local databases left out)
COUNT_JS='db.adminCommand({listDatabases: 1}).databases.map(d => d.name)
  .filter(n => !["admin", "config", "local"].includes(n)).sort().forEach(n => {
    const d = db.getSiblingDB(n);
    d.getCollectionNames().filter(c => !c.startsWith("system.")).sort()
      .forEach(c => print(n + "." + c + " " + d.getCollection(c).estimatedDocumentCount()));
  });'
restored="$(docker exec "$CONTAINER" mongosh --quiet --eval "$COUNT_JS")"
live="$(docker compose exec -T -e COUNT_JS="$COUNT_JS" database-service sh -c \
  'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet --eval "$COUNT_JS"' \
  2>/dev/null || true)"

printf '\n%-52s %12s %12s\n' "Collection" "Restored" "Live now"
names="$(printf '%s\n%s\n' "$restored" "$live" | awk 'NF == 2 {print $1}' | sort -u)"
for name in $names; do
  r="$(printf '%s\n' "$restored" | awk -v n="$name" '$1 == n {print $2}')"
  l="$(printf '%s\n' "$live" | awk -v n="$name" '$1 == n {print $2}')"
  printf '%-52s %12s %12s\n' "$name" "${r:--}" "${l:--}"
done
[[ -n $live ]] || echo "(the live database could not be read: only the restored counts are shown)"

problems=0
need() {   # database.collection that must hold documents (unless the live one has none either)
  local n l
  n="$(printf '%s\n' "$restored" | awk -v n="$1" '$1 == n {print $2}')"
  l="$(printf '%s\n' "$live" | awk -v n="$1" '$1 == n {print $2}')"
  if [[ -z $n || $n == 0 ]]; then
    if [[ -n $live && ( -z $l || $l == 0 ) ]]; then echo "NOTE: $1 is empty here and in the live database"
    else echo "MISSING: $1 has no documents in the archive"; problems=1; fi
  fi
}
need "$records_db.gs1resolver"
need "$portal_db.users"
echo
if (( problems )); then
  echo "$(date -Is) FAILED: the archive restored but lacks what the installation needs"; exit 1
fi
echo "$(date -Is) OK: the archive restores; differences from the live counts are the changes made since it was taken"
