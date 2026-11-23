#!/usr/bin/env bash
# Daily backup of a GS1 Resolver CE installation: every MongoDB database (the resolver's records, the portal's own
# database — users with password hashes, record metadata, the daily counts of requests —, the journal's database
# (<PORTAL_DB_NAME>_journal, ADR 0026 section 2.5.2) and the log of
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
#
# Encryption (Documentation/adr/0044-encrypted-backups-and-sealed-secrets.md): every archive is encrypted with age as it
# is written (*.archive.gz.age, *.tar.gz.age), to the public key of the identity in BACKUP_KEY_FILE (default
# /etc/resolver-backup.key) and to the public keys in BACKUP_RECIPIENTS. With neither, the first run creates the key
# file: keep a copy of it off the server, since without it no backup can be restored. age missing is an ERROR (nothing
# is written); BACKUP_ENCRYPTION=off writes the archives unencrypted, with a WARNING.
set -euo pipefail

# Repository root (where docker-compose.yml lives): by default the parent of this script's folder.
RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/resolver}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
STAMP="$(date +%F_%H%M)"
cd "$RESOLVER_DIR"
setting() {   # a setting from the environment, else from .env (else .env.example's default)
  local value="${!1:-}"
  [ -n "$value" ] || value="$(sed -n "s/^$1=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true)"
  printf '%s' "$value"
}
BACKUP_COPY_TO="$(setting BACKUP_COPY_TO)"
BACKUP_ENCRYPTION="$(setting BACKUP_ENCRYPTION)"; BACKUP_ENCRYPTION="${BACKUP_ENCRYPTION:-age}"
BACKUP_KEY_FILE="$(setting BACKUP_KEY_FILE)"; BACKUP_KEY_FILE="${BACKUP_KEY_FILE:-/etc/resolver-backup.key}"
BACKUP_RECIPIENTS="$(setting BACKUP_RECIPIENTS)"

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

# Encryption: the recipients (age -r …), the key file created when there is none. ENCRYPT is the command each archive
# goes through on its way to the disk; SUFFIX its file names' ending.
fail() { echo "$(date -Is) ERROR: $1"; record 0 "" "" "$1"; exit 1; }
if [ "$BACKUP_ENCRYPTION" = off ]; then
  ENCRYPT=(cat); SUFFIX=""
  echo "$(date -Is) WARNING: BACKUP_ENCRYPTION=off: the archives are written unencrypted (ADR 0044)"
else
  [ "$BACKUP_ENCRYPTION" = age ] || fail "BACKUP_ENCRYPTION must be age or off, not $BACKUP_ENCRYPTION"
  command -v age >/dev/null 2>&1 && command -v age-keygen >/dev/null 2>&1 \
    || fail "age is not installed (sudo apt-get install age): nothing was written"
  RECIPIENTS=()
  for recipient in ${BACKUP_RECIPIENTS//,/ }; do RECIPIENTS+=(-r "$recipient"); done
  if [ ! -e "$BACKUP_KEY_FILE" ] && [ ${#RECIPIENTS[@]} -eq 0 ]; then
    mkdir -p "$(dirname "$BACKUP_KEY_FILE")"
    age-keygen -o "$BACKUP_KEY_FILE" 2>/dev/null || fail "the backup key $BACKUP_KEY_FILE could not be created"
    chmod 600 "$BACKUP_KEY_FILE"
    echo "$(date -Is) NOTICE: a backup key was created in $BACKUP_KEY_FILE: keep a copy of it off this server (a password manager); without it no backup can be restored"
  fi
  if [ -e "$BACKUP_KEY_FILE" ]; then
    public="$(age-keygen -y "$BACKUP_KEY_FILE" 2>/dev/null)" || fail "the backup key $BACKUP_KEY_FILE cannot be read"
    RECIPIENTS+=(-r "$public")
  fi
  ENCRYPT=(age "${RECIPIENTS[@]}"); SUFFIX=".age"
fi

# Database. Single quotes: the credentials are read from the container's own environment and
# never appear on the host's command line.
# pipefail: a dump or an encryption that fails fails the run.
DB_ARCHIVE="$BACKUP_DIR/resolver-$STAMP.archive.gz$SUFFIX"
if ! docker compose exec -T database-service sh -c \
  'mongodump -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip' \
  | "${ENCRYPT[@]}" > "$DB_ARCHIVE.tmp"; then
  echo "$(date -Is) ERROR: database backup failed (mongodump's or age's message above)"; rm -f "$DB_ARCHIVE.tmp"
  record 0 "" "" "the database dump failed"; exit 1
fi
[ -s "$DB_ARCHIVE.tmp" ] || { echo "$(date -Is) ERROR: empty database backup"; rm -f "$DB_ARCHIVE.tmp"
                              record 0 "" "" "empty database backup"; exit 1; }
mv "$DB_ARCHIVE.tmp" "$DB_ARCHIVE"

# Portal configuration (skipped when the portal service is not running).
PORTAL_ARCHIVE="$BACKUP_DIR/portal-config-$STAMP.tar.gz$SUFFIX"
if docker compose ps --status running --services 2>/dev/null | grep -qx portal-service; then
  if ! docker compose exec -T portal-service tar -czf - -C /app/config . | "${ENCRYPT[@]}" > "$PORTAL_ARCHIVE.tmp"; then
    rm -f "$PORTAL_ARCHIVE.tmp"; fail "the portal configuration's archive failed (the database's $DB_ARCHIVE is kept)"
  fi
  mv "$PORTAL_ARCHIVE.tmp" "$PORTAL_ARCHIVE"
else
  PORTAL_ARCHIVE="(portal not running, skipped)"
fi

find "$BACKUP_DIR" \( -name 'resolver-*.archive.gz' -o -name 'portal-config-*.tar.gz' \
  -o -name 'resolver-*.archive.gz.age' -o -name 'portal-config-*.tar.gz.age' \) \
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
