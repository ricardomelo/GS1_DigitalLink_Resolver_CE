#!/usr/bin/env bash
# Upgrade of an installation of the official GS1 Resolver CE v3 (github.com/gs1/GS1_DigitalLink_Resolver_CE) to the
# Expansion Pack, in place: the same folder, the same database volume, the records kept.
#
# Run it in the folder of the official installation (the git clone where "docker compose up" was run):
#
#   sudo scripts/upgrade-from-official.sh               # asks before each change
#   sudo scripts/upgrade-from-official.sh --check       # only the checks: changes nothing
#   sudo scripts/upgrade-from-official.sh --yes         # no questions (the installer's own still come)
#
# A copy of this script can be fetched into the official folder first (the official project does not have it):
#
#   curl -fsSLo upgrade-from-official.sh \
#     https://raw.githubusercontent.com/ricardomelo/GS1_DigitalLink_Resolver_CE/gs1br/develop/scripts/upgrade-from-official.sh
#   sudo bash upgrade-from-official.sh
#
# Steps: (1) checks — an official installation, no uncommitted changes to the official files, the database answers
# with the credentials it was created with; (2) a full backup of the database (mongodump, gzip) in BACKUP_DIR, and the
# number of records per collection; (3) the official containers stopped (the database volume is kept); (4) the
# Expansion Pack's branch fetched and checked out in the same folder (the official branch stays, for a rollback);
# (5) the database credentials and the data entry API token written into .env so that the installer keeps them;
# (6) scripts/install.sh, which builds and starts every service, the portal included; (7) the records counted again
# and compared. Rollback instructions are printed at the end and kept in the log.
#
# Settings (environment): UPGRADE_REPOSITORY (the Expansion Pack's git address), UPGRADE_BRANCH (gs1br/develop),
# UPGRADE_REMOTE (expansion), BACKUP_DIR (/var/backups/resolver), INSTALL_ARGS (passed to scripts/install.sh).
set -euo pipefail

UPGRADE_REPOSITORY="${UPGRADE_REPOSITORY:-https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE.git}"
UPGRADE_BRANCH="${UPGRADE_BRANCH:-gs1br/develop}"
UPGRADE_REMOTE="${UPGRADE_REMOTE:-expansion}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/resolver}"
INSTALL_ARGS="${INSTALL_ARGS:-}"
LOG_FILE="${UPGRADE_LOG:-/var/log/gs1-resolver-upgrade.log}"
RECORDS_DB="resolver_ce"
CHECK_ONLY=0
ASSUME_YES=0

for arg in "$@"; do
  case $arg in
    --check) CHECK_ONLY=1 ;;
    --yes) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)"; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*" | tee -a "$LOG_FILE"; }
step() { say ""; say "== $*"; }
die() { say "ERROR: $*"; exit 1; }
confirm() {
  (( ASSUME_YES )) && return 0
  local answer
  read -r -p "$1 [y/N] " answer
  [[ $answer == [yYsS]* ]]
}

# The whole run is one compound command, read before it starts: "git switch" may replace this file while it runs.
{
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="./upgrade-from-official.log"
say "Upgrade to the Expansion Pack — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# ------------------------------------------------------------------------------------------------ 1. checks
step "1. Checks"
[[ -f docker-compose.yml ]] || die "no docker-compose.yml here: run this in the folder of the official installation."
command -v docker >/dev/null 2>&1 || die "docker is not installed."
command -v git >/dev/null 2>&1 || die "git is not installed."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "this folder is not a git clone."
if grep -q 'portal-service' docker-compose.yml; then
  die "this folder already runs the Expansion Pack: update it with 'git pull' and 'sudo scripts/install.sh'."
fi
grep -q 'database-service' docker-compose.yml && grep -q 'resolver-database-volume' docker-compose.yml \
  || die "docker-compose.yml is not the official GS1 Resolver CE v3's (database-service, resolver-database-volume)."
changed="$(git status --porcelain --untracked-files=no)"
if [[ -n $changed ]]; then
  say "Files of the official project changed in this folder:"
  say "$changed"
  die "commit or put them aside first (git stash), so that they are not lost when the branch changes."
fi
official_ref="$(git rev-parse --abbrev-ref HEAD)"
official_commit="$(git rev-parse --short HEAD)"
say "Official installation: branch $official_ref, commit $official_commit, folder $PWD"

# The credentials the database was created with: .env, else .env.example (the official default gs1resolver)
setting() {
  sed -n "s/^$1=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true
}
mongo_user="$(setting MONGO_INITDB_ROOT_USERNAME)"; mongo_user="${mongo_user:-gs1resolver}"
mongo_password="$(setting MONGO_INITDB_ROOT_PASSWORD)"; mongo_password="${mongo_password:-gs1resolver}"
mongo_uri="$(setting MONGO_URI)"
session_token="$(setting SESSION_TOKEN)"

docker compose ps --status running --services 2>/dev/null | grep -qx database-service \
  || die "the database service is not running: start the official installation (docker compose up -d) first."
mongo() {   # mongosh in the database container with the installation's credentials; the script on standard input
  docker compose exec -T -e U="$mongo_user" -e P="$mongo_password" database-service \
    sh -c 'mongosh -u "$U" -p "$P" --authenticationDatabase admin --quiet' 2>/dev/null
}
ping="$(printf 'db.runCommand({ping: 1}).ok\n' | mongo || true)"
[[ $ping == *1* ]] || die "the database did not accept the credentials of .env / .env.example (user $mongo_user)."
say "Database: answers, user $mongo_user$([[ $mongo_password == gs1resolver ]] && echo ' (the official default password)')"

COUNT_JS='const d = db.getSiblingDB("'"$RECORDS_DB"'");
d.getCollectionNames().filter(c => !c.startsWith("system.")).sort()
  .forEach(c => print(c + " " + d.getCollection(c).countDocuments({})));'
before="$(printf '%s\n' "$COUNT_JS" | mongo || true)"
say "Records before the upgrade ($RECORDS_DB):"
say "${before:-  (no collections)}"
free_kb="$(df -Pk "$PWD" | awk 'NR == 2 {print $4}')"
(( free_kb > 3 * 1024 * 1024 )) || say "WARNING: less than 3 GB free on this disk; the new images need about 2 GB."

if (( CHECK_ONLY )); then
  say ""
  say "Checks passed. Nothing was changed (--check)."
  exit 0
fi
confirm "Back up the database and upgrade this installation to the Expansion Pack?" || die "cancelled; nothing was changed."

# ------------------------------------------------------------------------------------------------ 2. backup
step "2. Backup"
mkdir -p "$BACKUP_DIR"
archive="$BACKUP_DIR/pre-upgrade-$(date '+%Y-%m-%d_%H%M%S').archive.gz"
docker compose exec -T -e U="$mongo_user" -e P="$mongo_password" database-service \
  sh -c 'mongodump -u "$U" -p "$P" --authenticationDatabase admin --archive --gzip --quiet' > "$archive" \
  || { rm -f "$archive"; die "mongodump failed; nothing was changed."; }
[[ -s $archive ]] || { rm -f "$archive"; die "the backup is empty; nothing was changed."; }
chmod 600 "$archive"
say "Backup: $archive ($(du -h "$archive" | cut -f1))"

# ------------------------------------------------------------------------------------------------ 3. stop
step "3. The official containers stopped (the database volume is kept)"
docker compose down --remove-orphans 2>&1 | tee -a "$LOG_FILE" >/dev/null || die "docker compose down failed."
say "Stopped."

rollback() {
  say ""
  say "To go back to the official installation:"
  say "  git switch $official_ref    # commit $official_commit"
  say "  docker compose down --remove-orphans && docker compose up -d --build"
  say "and, only if its records are not as they were, restore the backup into the running database:"
  say "  docker compose exec -T database-service sh -c 'mongorestore -u \"\$MONGO_INITDB_ROOT_USERNAME\" -p \"\$MONGO_INITDB_ROOT_PASSWORD\" --authenticationDatabase admin --archive --gzip --drop' < $archive"
}
trap 'say "The upgrade stopped before the end."; rollback' ERR

# ------------------------------------------------------------------------------------------------ 4. code
step "4. The Expansion Pack's code ($UPGRADE_BRANCH)"
if git remote | grep -qx "$UPGRADE_REMOTE"; then
  git remote set-url "$UPGRADE_REMOTE" "$UPGRADE_REPOSITORY"
else
  git remote add "$UPGRADE_REMOTE" "$UPGRADE_REPOSITORY"
fi
git fetch "$UPGRADE_REMOTE" "$UPGRADE_BRANCH" 2>&1 | tee -a "$LOG_FILE" >/dev/null
if git show-ref --verify --quiet "refs/heads/$UPGRADE_BRANCH"; then
  git switch "$UPGRADE_BRANCH" 2>&1 | tee -a "$LOG_FILE" >/dev/null
  git merge --ff-only "$UPGRADE_REMOTE/$UPGRADE_BRANCH" 2>&1 | tee -a "$LOG_FILE" >/dev/null
else
  git switch -c "$UPGRADE_BRANCH" --track "$UPGRADE_REMOTE/$UPGRADE_BRANCH" 2>&1 | tee -a "$LOG_FILE" >/dev/null
fi
grep -q 'portal-service' docker-compose.yml || die "the branch checked out is not the Expansion Pack's."
say "Checked out: $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)"

# ------------------------------------------------------------------------------------------------ 5. .env
step "5. The database credentials and the API token kept in .env"
touch .env
cp -p .env ".env.bak-$(date '+%Y%m%d%H%M%S')"
keep() {   # writes NAME='value' when .env does not set NAME yet
  local name=$1 value=$2
  [[ -n $value ]] || return 0
  grep -q "^$name=" .env || printf "%s='%s'\n" "$name" "$value" >> .env
}
keep MONGO_INITDB_ROOT_USERNAME "$mongo_user"
keep MONGO_INITDB_ROOT_PASSWORD "$mongo_password"
keep MONGO_URI "${mongo_uri:-mongodb://$mongo_user:$mongo_password@database-service:27017}"
keep SESSION_TOKEN "$session_token"
chmod 600 .env
say ".env: the database's user and password kept$([[ -n $session_token ]] && echo ', and the data entry API token')."
[[ $session_token == secret ]] && say "Note: the API token is the official default 'secret'; the installer replaces it with a new one (update the systems that call /api)."

# ------------------------------------------------------------------------------------------------ 6. installer
step "6. The installer (scripts/install.sh)"
say "It asks for the domain, HTTPS, the operator and the portal's first user; the answers of an existing .env are"
say "offered as defaults. With your own reverse proxy in front, choose the HTTPS mode 'external'."
# shellcheck disable=SC2086
bash scripts/install.sh $INSTALL_ARGS

# ------------------------------------------------------------------------------------------------ 7. compare
step "7. Records after the upgrade"
trap - ERR
mongo_password_now="$(setting MONGO_INITDB_ROOT_PASSWORD)"; mongo_password="${mongo_password_now:-$mongo_password}"
after="$(printf '%s\n' "$COUNT_JS" | mongo || true)"
problems=0
while read -r name count; do
  [[ -n $name ]] || continue
  now="$(printf '%s\n' "$after" | awk -v n="$name" '$1 == n {print $2}')"
  if [[ ${now:-0} -lt $count ]]; then
    say "  $name: $count before, ${now:-none} now"; problems=1
  else
    say "  $name: $count before, $now now"
  fi
done <<< "$before"
if (( problems )); then
  say "WARNING: fewer records than before the upgrade."
  rollback
  exit 1
fi
say ""
say "Upgrade done: the records are all there. Sign in at the portal with the first user the installer created."
[[ $mongo_password == gs1resolver ]] && say "Recommended: replace the official default database password with scripts/rotate-secrets.sh."
say "The backup taken before the upgrade: $archive"
rollback
exit 0
}
