#!/usr/bin/env bash
# Daily backup of a GS1 Resolver CE installation: every MongoDB database (the resolver's records, the portal's own
# database — users with password hashes, record metadata, journal, the daily counts of requests — and the log of
# resolver requests, resolver_log: mongodump cannot leave a whole database out, Documentation/adr/0006-resolver-
# request-log.md, section 3.4) and the portal's configuration volume (the fallback session key and the files of
# earlier versions, *.migrated). A failed dump says ERROR, leaves no partial file and exits with status 1.
#
# Run it from the repository (no copy needed):  sudo scripts/resolver-backup.sh
# Scheduled by scripts/resolver-backup.cron. Settings can be overridden from the environment.
set -euo pipefail

# Repository root (where docker-compose.yml lives): by default the parent of this script's folder.
RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/resolver}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
STAMP="$(date +%F_%H%M)"
cd "$RESOLVER_DIR"

# Database. Single quotes: the credentials are read from the container's own environment and
# never appear on the host's command line.
DB_ARCHIVE="$BACKUP_DIR/resolver-$STAMP.archive.gz"
if ! docker compose exec -T database-service sh -c \
  'mongodump -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip' \
  > "$DB_ARCHIVE.tmp"; then
  echo "$(date -Is) ERROR: database backup failed (mongodump's message above)"; rm -f "$DB_ARCHIVE.tmp"; exit 1
fi
[ -s "$DB_ARCHIVE.tmp" ] || { echo "$(date -Is) ERROR: empty database backup"; rm -f "$DB_ARCHIVE.tmp"; exit 1; }
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
echo "$(date -Is) OK $DB_ARCHIVE $(du -h "$DB_ARCHIVE" | cut -f1) $PORTAL_ARCHIVE"
