#!/usr/bin/env bash
# Daily backup of a GS1 Resolver CE installation: every MongoDB database (the resolver's records, the portal's own
# database — users with password hashes, record metadata, journal, the daily counts of requests — and the log of
# resolver requests, resolver_log: mongodump cannot leave a whole database out, Documentation/adr/0006-resolver-
# request-log.md, section 3.4) and the portal's configuration volume (the fallback session key and the files of
# earlier versions, *.migrated). A failed dump says ERROR, leaves no partial file and exits with status 1. Each run's
# result is recorded in the portal's database for its monitoring (record, below).
#
# Run it from the repository (no copy needed):  sudo scripts/resolver-backup.sh
# Scheduled by scripts/resolver-backup.cron. Settings can be overridden from the environment.
#
# Off-server copy (item 7.2): with BACKUP_COPY_TO (in .env or the environment) set to an rsync destination — e.g.
# backup@vault.example.org:/srv/resolver or a mounted /mnt/offsite/resolver — each run's files are copied there too;
# a copy that fails makes the run fail (ERROR, status 1, recorded for the monitoring), so that it is noticed. The
# destination keeps what it receives: its own retention is the destination's business. scripts/restore-rehearsal.sh
# checks that an archive restores.
set -euo pipefail

# Repository root (where docker-compose.yml lives): by default the parent of this script's folder.
RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/resolver}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
STAMP="$(date +%F_%H%M)"
cd "$RESOLVER_DIR"
if [ -z "${BACKUP_COPY_TO:-}" ]; then
  BACKUP_COPY_TO="$(sed -n "s/^BACKUP_COPY_TO=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true)"
fi

# The result of each run, for the portal's monitoring (Documentation/adr/0008-monitoring-and-alerts.md): written as the
# setting "backup.last" of the portal's database with mongosh inside the database container (the credentials stay in
# the container). A failure to write it never fails the backup.   record <1|0> <file> <size> <error>
record() {
  local db
  db="$(sed -n "s/^PORTAL_DB_NAME=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true)"
  docker compose exec -T -e BACKUP_OK="$1" -e BACKUP_FILE="$2" -e BACKUP_SIZE="$3" -e BACKUP_ERROR="$4" \
    -e BACKUP_DB="${db:-resolver_portal}" database-service sh -c \
    'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet "$BACKUP_DB" --eval "
      const ok = process.env.BACKUP_OK === \"1\"; const now = new Date();
      const before = db.settings.findOne({_id: \"backup.last\"});
      const lastOk = ok ? now : (before && before.value && before.value.lastOk) || null;
      db.settings.replaceOne({_id: \"backup.last\"}, {_id: \"backup.last\", value: {at: now, ok: ok,
        file: process.env.BACKUP_FILE || null, size: process.env.BACKUP_SIZE || null,
        error: process.env.BACKUP_ERROR || null, lastOk: lastOk}}, {upsert: true});"' >/dev/null 2>&1 \
    || echo "$(date -Is) WARNING: the result was not recorded for the portal's monitoring"
}

# Database. Single quotes: the credentials are read from the container's own environment and
# never appear on the host's command line.
DB_ARCHIVE="$BACKUP_DIR/resolver-$STAMP.archive.gz"
if ! docker compose exec -T database-service sh -c \
  'mongodump -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip' \
  > "$DB_ARCHIVE.tmp"; then
  echo "$(date -Is) ERROR: database backup failed (mongodump's message above)"; rm -f "$DB_ARCHIVE.tmp"
  record 0 "" "" "the database dump failed"; exit 1
fi
[ -s "$DB_ARCHIVE.tmp" ] || { echo "$(date -Is) ERROR: empty database backup"; rm -f "$DB_ARCHIVE.tmp"
                              record 0 "" "" "empty database backup"; exit 1; }
mv "$DB_ARCHIVE.tmp" "$DB_ARCHIVE"

# Portal configuration (skipped when the portal service is not running).
PORTAL_ARCHIVE="$BACKUP_DIR/portal-config-$STAMP.tar.gz"
if docker compose ps --status running --services 2>/dev/null | grep -qx portal-service; then
  docker compose exec -T portal-service tar -czf - -C /app/config . > "$PORTAL_ARCHIVE.tmp"
  mv "$PORTAL_ARCHIVE.tmp" "$PORTAL_ARCHIVE"
else
  PORTAL_ARCHIVE="(portal not running, skipped)"
fi

find "$BACKUP_DIR" \( -name 'resolver-*.archive.gz' -o -name 'portal-config-*.tar.gz' \) \
  -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name '*.tmp' -mtime +1 -delete     # left by a run that was killed
SIZE="$(du -h "$DB_ARCHIVE" | cut -f1)"
if [ -n "$BACKUP_COPY_TO" ]; then
  COPY=("$DB_ARCHIVE")
  [ -f "$PORTAL_ARCHIVE" ] && COPY+=("$PORTAL_ARCHIVE")
  if ! rsync -a --chmod=F600 --timeout=600 "${COPY[@]}" "${BACKUP_COPY_TO%/}/"; then
    echo "$(date -Is) ERROR: the off-server copy to $BACKUP_COPY_TO failed (rsync's message above); the local backup $DB_ARCHIVE is kept"
    record 0 "$DB_ARCHIVE" "$SIZE" "the off-server copy failed"; exit 1
  fi
  echo "$(date -Is) copied to $BACKUP_COPY_TO"
fi
echo "$(date -Is) OK $DB_ARCHIVE $SIZE $PORTAL_ARCHIVE"
record 1 "$DB_ARCHIVE" "$SIZE" ""
