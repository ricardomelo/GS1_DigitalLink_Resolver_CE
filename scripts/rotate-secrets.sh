#!/usr/bin/env bash
# Rotation of the secrets of a GS1 Resolver CE installation (item 7.2): new random values in .env for the secrets the
# installer generated, the database's own passwords changed to match, and the services recreated with them. A secret
# is never printed or put on a command line; the previous .env is kept as .env.bak-<time> (mode 600).
#
#   sudo scripts/rotate-secrets.sh                 # every secret below
#   sudo scripts/rotate-secrets.sh token session   # only those named
#
#   token       SESSION_TOKEN               the data entry API's bearer token: systems that call /api need the new one
#   session     PORTAL_SECRET_KEY           signs the portal's sessions: everyone is signed out
#   portal-db   PORTAL_DB_PASSWORD          the portal's MongoDB user (portal-db-init sets it on the next start)
#   mongo       MONGO_INITDB_ROOT_PASSWORD  MongoDB's root user, changed in the database first, then in .env and in
#                                           MONGO_URI; skipped (nothing changed) when the database refuses
#
# The services are recreated at the end (docker compose up -d): about a minute without the resolver, so run it at a
# quiet hour. Take a backup first (scripts/resolver-backup.sh). Exit status 0 when every secret asked was rotated.
set -euo pipefail

RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
cd "$RESOLVER_DIR"
ENV_FILE=.env
ALL=(token session portal-db mongo)

asked=("$@")
(( ${#asked[@]} )) || asked=("${ALL[@]}")
for name in "${asked[@]}"; do
  [[ " ${ALL[*]} " == *" $name "* ]] || { echo "Unknown secret: $name (one of: ${ALL[*]})"; exit 2; }
done
[[ -f $ENV_FILE ]] || { echo "ERROR: no .env here ($RESOLVER_DIR): nothing to rotate"; exit 1; }

value() {     # the value of a setting in .env, without the quotes the installer writes
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed -E "s/^'(.*)'$/\1/; s/^\"(.*)\"$/\1/"
}
put() {       # sets a setting in .env (replacing every line of it), keeping the file's owner and mode
  local name=$1 new=$2 tmp
  tmp="$(mktemp "$ENV_FILE.XXXXXX")"
  awk -v n="$name" -v v="$new" 'BEGIN { done = 0 }
    index($0, n "=") == 1 { if (!done) { print n "='"'"'" v "'"'"'"; done = 1 } ; next }
    { print } END { if (!done) print n "='"'"'" v "'"'"'" }' "$ENV_FILE" > "$tmp"
  chmod --reference="$ENV_FILE" "$tmp"; chown --reference="$ENV_FILE" "$tmp" 2>/dev/null || true
  mv "$tmp" "$ENV_FILE"
}
random() { openssl rand -hex "$1"; }

stamp="$(date +%Y%m%d-%H%M%S)"
umask 077
cp -p "$ENV_FILE" "$ENV_FILE.bak-$stamp"
chmod 600 "$ENV_FILE.bak-$stamp"
echo "Previous settings kept in $ENV_FILE.bak-$stamp"

rotated=() failed=0
for name in "${asked[@]}"; do
  case $name in
    token)     put SESSION_TOKEN "$(random 32)"; rotated+=("SESSION_TOKEN (systems calling /api need the new value)") ;;
    session)   put PORTAL_SECRET_KEY "$(random 32)"; rotated+=("PORTAL_SECRET_KEY (portal users sign in again)") ;;
    portal-db) put PORTAL_DB_PASSWORD "$(random 24)"; rotated+=("PORTAL_DB_PASSWORD") ;;
    mongo)
      user="$(value MONGO_INITDB_ROOT_USERNAME)"; uri="$(value MONGO_URI)"
      if [[ -z $user || ! $uri =~ ^mongodb://[^:/@]+:[^@]*@ ]]; then
        echo "SKIPPED mongo: MONGO_INITDB_ROOT_USERNAME or a MONGO_URI with a password is missing from .env"; failed=1; continue
      fi
      new="$(random 24)"
      # The new password goes to mongosh on standard input, never on a command line; the current one is the
      # container's own environment, as in scripts/resolver-backup.sh
      if printf '%s\n' "$new" | docker compose exec -T database-service sh -c \
           'IFS= read -r NEW_PASSWORD; export NEW_PASSWORD; mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet --eval "db.getSiblingDB(\"admin\").changeUserPassword(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.NEW_PASSWORD)"' \
           >/dev/null 2>&1; then
        put MONGO_INITDB_ROOT_PASSWORD "$new"
        put MONGO_URI "$(printf '%s' "$uri" | sed -E "s#^(mongodb://[^:/@]+:)[^@]*@#\1$new@#")"
        rotated+=("MONGO_INITDB_ROOT_PASSWORD and MONGO_URI (changed in the database first)")
      else
        echo "SKIPPED mongo: the database did not accept the change (is database-service running?); .env keeps the old password"
        failed=1
      fi ;;
  esac
done

if (( ${#rotated[@]} )); then
  echo "Rotated:"; printf '  %s\n' "${rotated[@]}"
  echo "Recreating the services with the new values…"
  docker compose up -d
  echo "$(date -Is) OK: done. The previous values are only in $ENV_FILE.bak-$stamp: delete it once the installation works."
fi
exit "$failed"
