#!/usr/bin/env bash
# =================================================================================================
# GS1 Digital Link Resolver CE — installer for Ubuntu Server 22.04 / 24.04
#
# Run from a clone of the repository:
#     git clone <repository URL> && cd GS1_DigitalLink_Resolver_CE
#     sudo scripts/install.sh
#
# What it does, asking before each part that changes the system:
#   1. checks the machine (Ubuntu, root, repository);
#   2. asks for the domain (FQDN), how TLS is handled, the operator's details and the first portal
#      user, keeping the values of an earlier installation as defaults;
#   3. installs Docker Engine with the Compose plugin (official Docker repository) if needed, plus
#      nginx and Certbot when the host terminates TLS;
#   4. writes .env (mode 600) with generated secrets: MongoDB password, API token;
#   5. configures the host nginx as reverse proxy (checking that ports 80/443 are free) and obtains
#      a Let's Encrypt certificate, or uses an existing certificate, or leaves TLS to an external proxy;
#   6. builds and starts the services and waits until they answer;
#   7. schedules the daily backup and prints a summary.
#
# Running it again is safe: existing secrets, users and data are kept. Options:
#   --non-interactive   take every answer from environment variables (see "Settings" below)
#   --yes               answer "yes" to confirmations (implied by --non-interactive)
#   --help              show this text
#
# Settings (environment variables, also used as defaults in interactive mode):
#   FQDN, TLS_MODE (letsencrypt | certificate | external), CERTBOT_EMAIL, TLS_CERT_FILE,
#   TLS_KEY_FILE, PROXY_BIND_ADDRESS, RESOLVER_ORG_NAME, RESOLVER_ORG_URL, RESOLVER_CONTACT_STREET,
#   RESOLVER_CONTACT_LOCALITY, RESOLVER_CONTACT_REGION, RESOLVER_CONTACT_POSTCODE,
#   RESOLVER_CONTACT_COUNTRY, RESOLVER_CONTACT_TELEPHONE, PORTAL_ADMIN_USERNAME,
#   PORTAL_ADMIN_PASSWORD (empty: generated), INSTALL_BACKUP_CRON (yes | no),
#   INSTALL_DOCKER_GROUP_USER (user to add to the docker group; empty: none)
# =================================================================================================
set -Eeuo pipefail
umask 077

# ------------------------------------------------------------------------------------ constants
REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
TEMPLATE_DIR="$REPO_DIR/scripts/templates"
ENV_FILE="$REPO_DIR/.env"
PROXY_PORT=8080
MIN_COMPOSE_VERSION="2.24.0"
MIN_PASSWORD_LENGTH=12
# Paths below can be redirected for testing.
LOG_FILE="${INSTALL_LOG_FILE:-/var/log/gs1-resolver-install.log}"
NGINX_AVAILABLE="${INSTALL_NGINX_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_ENABLED="${INSTALL_NGINX_ENABLED:-/etc/nginx/sites-enabled}"
CRON_FILE="${INSTALL_CRON_FILE:-/etc/cron.d/resolver-backup}"
SITE_NAME="gs1resolver"
HEALTH_TIMEOUT="${INSTALL_HEALTH_TIMEOUT:-240}"

NON_INTERACTIVE=0
ASSUME_YES=0
GENERATED_ADMIN_PASSWORD=""

# ------------------------------------------------------------------------------------ output
if [[ -t 1 ]]; then
  C_BOLD=$'\e[1m'; C_DIM=$'\e[2m'; C_RED=$'\e[31m'; C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_OFF=$'\e[0m'
else
  C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_OFF=""
fi

log()   { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG_FILE"; }
step()  { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_OFF"; log "STEP $*"; }
info()  { printf '    %s\n' "$*"; log "INFO $*"; }
ok()    { printf '    %s✔%s %s\n' "$C_GREEN" "$C_OFF" "$*"; log "OK   $*"; }
warn()  { printf '    %s!%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; log "WARN $*"; }
die()   { printf '\n%sError:%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; log "FAIL $*"; exit 1; }

on_error() {
  local status=$? line=$1
  log "FAIL line $line status $status"
  printf '\n%sThe installation stopped (line %s, status %s).%s\n' "$C_RED" "$line" "$status" "$C_OFF" >&2
  printf 'Last lines of %s:\n' "$LOG_FILE" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  printf '\nFix the cause and run the installer again: completed steps are kept.\n' >&2
}
trap 'on_error $LINENO' ERR

# Runs a command with its output going to the log only.
run() {
  log "RUN  $*"
  "$@" >> "$LOG_FILE" 2>&1
}

usage() { sed -n '3,/^# =====/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }

# ------------------------------------------------------------------------------------ prompts
# ask VAR "Question" [default] [validator]
# Interactive: shows the default in brackets and repeats until the validator accepts the answer.
# Non-interactive: uses the current value of VAR, else the default.
ask() {
  local var=$1 question=$2 default=${3-} validator=${4-} answer
  local current=${!var-}
  [[ -n $current ]] && default=$current
  if (( NON_INTERACTIVE )); then
    answer=$default
    if [[ -n $validator ]] && ! "$validator" "$answer"; then
      die "$var: invalid or missing value '${answer}' ($question)."
    fi
    printf -v "$var" '%s' "$answer"
    return
  fi
  while true; do
    if [[ -n $default ]]; then
      read -r -p "    $question [$default]: " answer || die "No answer (end of input)."
      answer=${answer:-$default}
    else
      read -r -p "    $question: " answer || die "No answer (end of input)."
    fi
    answer=$(trim "$answer")
    if [[ -z $validator ]] || "$validator" "$answer"; then
      printf -v "$var" '%s' "$answer"
      return
    fi
  done
}

# ask_password VAR "Question" — hidden input, typed twice; empty means "generate".
ask_password() {
  local var=$1 question=$2 first second
  if (( NON_INTERACTIVE )); then
    if [[ -n ${!var-} ]]; then
      valid_password "${!var}" || die "$var must have at least $MIN_PASSWORD_LENGTH characters."
    fi
    return
  fi
  while true; do
    read -r -s -p "    $question (Enter to generate one): " first || die "No answer (end of input)."
    printf '\n'
    if [[ -z $first ]]; then printf -v "$var" '%s' ""; return; fi
    valid_password "$first" || continue
    read -r -s -p "    Type it again: " second || die "No answer (end of input)."
    printf '\n'
    if [[ $first == "$second" ]]; then printf -v "$var" '%s' "$first"; return; fi
    warn "The two entries differ."
  done
}

# confirm "Question" [default y|n]
confirm() {
  local question=$1 default=${2:-y} answer hint="[Y/n]"
  [[ $default == n ]] && hint="[y/N]"
  if (( NON_INTERACTIVE || ASSUME_YES )); then [[ $default == y ]]; return; fi
  read -r -p "    $question $hint " answer || die "No answer (end of input)."
  answer=${answer:-$default}
  [[ ${answer,,} == y || ${answer,,} == yes || ${answer,,} == s || ${answer,,} == sim ]]
}

trim() { local s=$1; s=${s#"${s%%[![:space:]]*}"}; printf '%s' "${s%"${s##*[![:space:]]}"}"; }

# ------------------------------------------------------------------------------------ validators
# Values end up single-quoted in .env, so they must not contain single quotes or line breaks.
safe_text() {
  if [[ $1 == *"'"* || $1 == *$'\n'* ]]; then warn "Single quotes and line breaks are not allowed."; return 1; fi
}
valid_required_text() { [[ -n $1 ]] || { warn "A value is required."; return 1; }; safe_text "$1"; }
valid_optional_text() { safe_text "$1"; }
valid_fqdn() {
  local re='^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$'
  [[ $1 =~ $re && ${#1} -le 253 ]] || { warn "Enter a domain name such as id.example.org (no https://, no path)."; return 1; }
}
valid_email() {
  [[ $1 =~ ^[^@[:space:]\']+@[^@[:space:]\']+\.[^@[:space:]\']+$ ]] || { warn "Enter an e-mail address."; return 1; }
}
valid_optional_url() {
  [[ -z $1 || $1 =~ ^https?://[^[:space:]\']+$ ]] || { warn "Enter a URL starting with https:// (or leave empty)."; return 1; }
}
valid_username() {
  [[ $1 =~ ^[A-Za-z0-9._-]{3,64}$ ]] || { warn "3–64 characters: letters, digits, dot, underscore or hyphen."; return 1; }
}
valid_password() {
  (( ${#1} >= MIN_PASSWORD_LENGTH )) || { warn "At least $MIN_PASSWORD_LENGTH characters."; return 1; }
}
valid_tls_mode() {
  [[ $1 == letsencrypt || $1 == certificate || $1 == external ]] || { warn "Choose letsencrypt, certificate or external."; return 1; }
}
valid_readable_file() { [[ -r $1 ]] || { warn "File not found or not readable: $1"; return 1; }; }
valid_bind_address() {
  [[ $1 == 0.0.0.0 || $1 == 127.0.0.1 || $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { warn "Enter an IPv4 address such as 127.0.0.1 or 0.0.0.0."; return 1; }
}
valid_yes_no() { [[ $1 == yes || $1 == no ]] || { warn "Answer yes or no."; return 1; }; }
valid_user_or_empty() { [[ -z $1 ]] || id -u "$1" >/dev/null 2>&1 || { warn "No such user: $1"; return 1; }; }

# ------------------------------------------------------------------------------------ .env
declare -A EXISTING=() EXISTING_RAW=()
EXISTING_ORDER=()

# Keys written by write_env; any other key found in an existing .env is carried over unchanged.
MANAGED_KEYS=" MONGO_INITDB_ROOT_USERNAME MONGO_INITDB_ROOT_PASSWORD MONGO_URI SESSION_TOKEN FQDN
  RESOLVER_ORG_NAME RESOLVER_ORG_URL RESOLVER_CONTACT_STREET RESOLVER_CONTACT_LOCALITY RESOLVER_CONTACT_REGION
  RESOLVER_CONTACT_POSTCODE RESOLVER_CONTACT_COUNTRY RESOLVER_CONTACT_TELEPHONE PORTAL_ADMIN_USERNAME
  PORTAL_ADMIN_PASSWORD PROXY_BIND_ADDRESS DATABASE_BIND_ADDRESS TLS_MODE CERTBOT_EMAIL TLS_CERT_FILE TLS_KEY_FILE "

# Reads KEY=VALUE lines of an existing .env (quotes removed) into EXISTING.
load_existing_env() {
  [[ -f $ENV_FILE ]] || return 0
  local line key value
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key=${BASH_REMATCH[1]}; value=${BASH_REMATCH[2]}
    if [[ $value =~ ^\"(.*)\"$ || $value =~ ^\'(.*)\'$ ]]; then value=${BASH_REMATCH[1]}; fi
    [[ -n ${EXISTING[$key]+x} ]] || EXISTING_ORDER+=("$key")
    EXISTING[$key]=$value
    EXISTING_RAW[$key]=$line
  done < "$ENV_FILE"
}

existing() { printf '%s' "${EXISTING[$1]-}"; }

# Takes a setting from the environment, else from the existing .env.
preset() { local var=$1; [[ -n ${!var-} ]] || printf -v "$var" '%s' "$(existing "$var")"; }

random_secret() { openssl rand -hex "${1:-24}"; }

env_line() { printf "%s='%s'\n" "$1" "$2"; }

write_env() {
  local tmp owner
  tmp=$(mktemp "$REPO_DIR/.env.tmp.XXXXXX")
  {
    printf '# GS1 Resolver CE installation settings — written by scripts/install.sh on %s\n' "$(date -Is)"
    printf '# Values here replace those in .env.example. Keep this file private (mode 600).\n\n'
    printf '# MongoDB (the password only applies when the database volume is first created)\n'
    env_line MONGO_INITDB_ROOT_USERNAME "$MONGO_USER"
    env_line MONGO_INITDB_ROOT_PASSWORD "$MONGO_PASSWORD"
    env_line MONGO_URI "$MONGO_URI"
    printf '\n# Data entry API token (also used by the portal)\n'
    env_line SESSION_TOKEN "$SESSION_TOKEN"
    printf '\n# Public identity\n'
    env_line FQDN "$FQDN"
    env_line RESOLVER_ORG_NAME "$RESOLVER_ORG_NAME"
    env_line RESOLVER_ORG_URL "$RESOLVER_ORG_URL"
    env_line RESOLVER_CONTACT_STREET "$RESOLVER_CONTACT_STREET"
    env_line RESOLVER_CONTACT_LOCALITY "$RESOLVER_CONTACT_LOCALITY"
    env_line RESOLVER_CONTACT_REGION "$RESOLVER_CONTACT_REGION"
    env_line RESOLVER_CONTACT_POSTCODE "$RESOLVER_CONTACT_POSTCODE"
    env_line RESOLVER_CONTACT_COUNTRY "$RESOLVER_CONTACT_COUNTRY"
    env_line RESOLVER_CONTACT_TELEPHONE "$RESOLVER_CONTACT_TELEPHONE"
    printf '\n# Portal: first user, created only while the portal has no users.\n'
    printf '# The installer clears the password once the user exists.\n'
    env_line PORTAL_ADMIN_USERNAME "$PORTAL_ADMIN_USERNAME"
    env_line PORTAL_ADMIN_PASSWORD "$PORTAL_ADMIN_PASSWORD"
    printf '\n# Read by Docker Compose itself\n'
    env_line PROXY_BIND_ADDRESS "$PROXY_BIND_ADDRESS"
    env_line DATABASE_BIND_ADDRESS "127.0.0.1"
    printf '\n# Installer choices (not used by the services)\n'
    env_line TLS_MODE "$TLS_MODE"
    env_line CERTBOT_EMAIL "${CERTBOT_EMAIL-}"
    env_line TLS_CERT_FILE "${TLS_CERT_FILE-}"
    env_line TLS_KEY_FILE "${TLS_KEY_FILE-}"
    local key header=0
    for key in "${EXISTING_ORDER[@]}"; do
      [[ $MANAGED_KEYS == *" $key "* ]] && continue
      (( header )) || { printf '\n# Other settings kept from the previous .env\n'; header=1; }
      printf '%s\n' "${EXISTING_RAW[$key]}"
    done
  } > "$tmp"
  if [[ -f $ENV_FILE ]]; then
    local backup
    backup="$ENV_FILE.bak-$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$backup" && chmod 600 "$backup"
  fi
  owner=${SUDO_USER:-root}
  chown "$owner": "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# Replaces the value of one variable in .env (used to clear the first-user password).
set_env_value() {
  local key=$1 value=$2 tmp
  tmp=$(mktemp "$REPO_DIR/.env.tmp.XXXXXX")
  awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=\047" v "\047"; next} {print}' "$ENV_FILE" > "$tmp"
  chown --reference="$ENV_FILE" "$tmp"; chmod 600 "$tmp"; mv "$tmp" "$ENV_FILE"
}

# ------------------------------------------------------------------------------------ docker
# Docker Compose in the repository (the installer changes to $REPO_DIR in preflight).
compose() { docker compose "$@"; }

compose_project_name() {
  if [[ -n ${COMPOSE_PROJECT_NAME-} ]]; then printf '%s' "$COMPOSE_PROJECT_NAME"; return; fi
  basename "$REPO_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

volume_exists() {
  local name
  name=$(docker volume ls -q --filter "label=com.docker.compose.project=$(compose_project_name)" \
                                --filter "label=com.docker.compose.volume=$1" 2>/dev/null | head -n 1)
  [[ -n $name ]]
}

version_at_least() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n 1)" == "$2" ]]; }

docker_ready() {
  command -v docker >/dev/null 2>&1 || return 1
  local v
  v=$(docker compose version --short 2>/dev/null) || return 1
  version_at_least "${v#v}" "$MIN_COMPOSE_VERSION"
}

install_docker() {
  info "Installing Docker Engine and the Compose plugin from download.docker.com…"
  # Packages from Ubuntu's own repositories conflict with Docker's (docs.docker.com/engine/install/ubuntu).
  local pkg conflicting=()
  for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    dpkg -s "$pkg" >/dev/null 2>&1 && conflicting+=("$pkg")
  done
  if (( ${#conflicting[@]} )); then
    confirm "Remove the conflicting packages ${conflicting[*]} (containers and volumes are kept)?" y \
      || die "Docker's packages cannot be installed alongside ${conflicting[*]}."
    run apt-get remove -y "${conflicting[@]}"
  fi
  run apt-get update
  run apt-get install -y ca-certificates curl
  run install -m 0755 -d /etc/apt/keyrings
  run curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  local codename arch
  # shellcheck source=/dev/null
  codename=$(. /etc/os-release && printf '%s' "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
  arch=$(dpkg --print-architecture)
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$arch" "$codename" > /etc/apt/sources.list.d/docker.list
  chmod 644 /etc/apt/sources.list.d/docker.list
  run apt-get update
  run apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  run systemctl enable --now docker
}

# ------------------------------------------------------------------------------------ nginx
render_template() {
  local template=$1 target=$2 drop_ipv6=()
  # "listen [::]:…" fails where the kernel has IPv6 disabled; keep those lines only when it is available.
  [[ -e /proc/net/if_inet6 ]] || drop_ipv6=(-e '/listen \[::\]/d')
  sed -e "s|@FQDN@|$FQDN|g" -e "s|@DATE@|$(date -Is)|g" -e "s|@PROXY_PORT@|$PROXY_PORT|g" \
      -e "s|@CERT_FILE@|${TLS_CERT_FILE-}|g" -e "s|@KEY_FILE@|${TLS_KEY_FILE-}|g" "${drop_ipv6[@]}" \
      "$TEMPLATE_DIR/$template" > "$target"
  chmod 644 "$target"
}

site_has_certificate() {
  [[ -f $NGINX_AVAILABLE/$SITE_NAME ]] && grep -q "ssl_certificate" "$NGINX_AVAILABLE/$SITE_NAME"
}

configure_nginx() {
  local site=$NGINX_AVAILABLE/$SITE_NAME template
  if [[ $TLS_MODE == letsencrypt ]] && site_has_certificate && grep -q "server_name $FQDN;" "$site"; then
    ok "nginx site $SITE_NAME already serves $FQDN with a certificate: kept as it is."
    return
  fi
  if [[ -f $site ]]; then
    cp -p "$site" "$site.bak-$(date +%Y%m%d%H%M%S)"
    info "Previous site kept as $site.bak-…"
  fi
  template=nginx-site-http.conf
  [[ $TLS_MODE == certificate ]] && template=nginx-site-https.conf
  mkdir -p "$NGINX_AVAILABLE" "$NGINX_ENABLED"
  umask 022; render_template "$template" "$site"; umask 077
  ln -sfn "$site" "$NGINX_ENABLED/$SITE_NAME"
  if [[ -L $NGINX_ENABLED/default ]] && confirm "Disable nginx's default site (it also answers on port 80)?" y; then
    rm -f "$NGINX_ENABLED/default"
  fi
  run nginx -t || die "nginx rejected the configuration; see $LOG_FILE."
  run systemctl reload nginx
  ok "nginx site $SITE_NAME → 127.0.0.1:$PROXY_PORT"
}

obtain_certificate() {
  if site_has_certificate; then ok "Certificate already configured for $FQDN."; return; fi
  info "Requesting a Let's Encrypt certificate for $FQDN (the domain must point to this server and"
  info "port 80 must be reachable from the Internet)…"
  run certbot --nginx -d "$FQDN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL" \
      --redirect --keep-until-expiring \
    || die "Certbot could not obtain the certificate. Check DNS and port 80, then run the installer again."
  ok "Certificate installed; renewal is automatic (certbot timer)."
}

open_firewall() {
  command -v ufw >/dev/null 2>&1 || return 0
  ufw status 2>/dev/null | grep -q "Status: active" || return 0
  if confirm "ufw is active. Allow HTTP and HTTPS (ports 80 and 443)?" y; then
    run ufw allow 80/tcp
    run ufw allow 443/tcp
    ok "ufw: ports 80 and 443 allowed."
  fi
}

# ------------------------------------------------------------------------------------ steps
preflight() {
  step "Checking this machine"
  (( EUID == 0 )) || die "Run as root: sudo $0"
  mkdir -p "$(dirname "$LOG_FILE")"; touch "$LOG_FILE"; chmod 600 "$LOG_FILE"
  cd "$REPO_DIR"
  log "---- installer started in $REPO_DIR"
  [[ -f $REPO_DIR/docker-compose.yml && -f $REPO_DIR/.env.example ]] \
    || die "Run the installer from the repository (docker-compose.yml not found in $REPO_DIR)."
  if [[ -r /etc/os-release ]]; then
    local id version
    # shellcheck source=/dev/null
    id=$(. /etc/os-release && printf '%s' "$ID")
    # shellcheck source=/dev/null
    version=$(. /etc/os-release && printf '%s' "$VERSION_ID")
    if [[ $id != ubuntu ]]; then
      warn "This installer targets Ubuntu; detected $id $version."
      confirm "Continue anyway?" n || die "Stopped."
    elif [[ $version != 22.04 && $version != 24.04 ]]; then
      warn "Tested on Ubuntu 22.04 and 24.04; detected $version."
    else
      ok "Ubuntu $version"
    fi
  fi
  command -v openssl >/dev/null 2>&1 || run apt-get install -y openssl
  ok "Repository: $REPO_DIR"
  info "Log file: $LOG_FILE"
}

collect_settings() {
  step "Settings"
  load_existing_env
  if [[ -f $ENV_FILE ]]; then info "An existing .env was found: its values are offered as defaults and its secrets are kept."; fi

  local var
  for var in FQDN TLS_MODE CERTBOT_EMAIL TLS_CERT_FILE TLS_KEY_FILE PROXY_BIND_ADDRESS RESOLVER_ORG_NAME \
             RESOLVER_ORG_URL RESOLVER_CONTACT_STREET RESOLVER_CONTACT_LOCALITY RESOLVER_CONTACT_REGION \
             RESOLVER_CONTACT_POSTCODE RESOLVER_CONTACT_COUNTRY RESOLVER_CONTACT_TELEPHONE PORTAL_ADMIN_USERNAME; do
    preset "$var"
  done
  # The development default of .env.example is not a real domain.
  [[ ${FQDN-} == localhost ]] && FQDN=""

  printf '\n    %sResolver address%s\n' "$C_BOLD" "$C_OFF"
  ask FQDN "Domain name of the resolver (e.g. id.example.org)" "" valid_fqdn

  printf '\n    %sHTTPS%s\n' "$C_DIM" "$C_OFF"
  info "letsencrypt  nginx on this server with a free Let's Encrypt certificate (recommended)"
  info "certificate  nginx on this server with a certificate you already have"
  info "external     TLS handled elsewhere (load balancer, another proxy); no nginx here"
  ask TLS_MODE "HTTPS mode" "letsencrypt" valid_tls_mode
  case $TLS_MODE in
    letsencrypt)
      ask CERTBOT_EMAIL "E-mail for Let's Encrypt expiry notices" "" valid_email
      PROXY_BIND_ADDRESS=127.0.0.1 ;;
    certificate)
      ask TLS_CERT_FILE "Certificate file (full chain, PEM)" "" valid_readable_file
      ask TLS_KEY_FILE "Private key file (PEM)" "" valid_readable_file
      PROXY_BIND_ADDRESS=127.0.0.1 ;;
    external)
      info "Port $PROXY_PORT (plain HTTP) will be published on the address below. Use 127.0.0.1 if"
      info "the proxy runs on this machine, 0.0.0.0 if it reaches this server over the network."
      ask PROXY_BIND_ADDRESS "Address for port $PROXY_PORT" "127.0.0.1" valid_bind_address ;;
  esac

  printf '\n    %sOperator%s %s(published in /.well-known/gs1resolver and on the resolver pages)%s\n' "$C_BOLD" "$C_OFF" "$C_DIM" "$C_OFF"
  [[ ${RESOLVER_ORG_NAME-} == "My Organisation" ]] && RESOLVER_ORG_NAME=""
  ask RESOLVER_ORG_NAME "Organisation name" "" valid_required_text
  ask RESOLVER_ORG_URL "Organisation website (optional)" "" valid_optional_url
  ask RESOLVER_CONTACT_STREET "Street address (optional)" "" valid_optional_text
  ask RESOLVER_CONTACT_LOCALITY "City (optional)" "" valid_optional_text
  ask RESOLVER_CONTACT_REGION "State or region (optional)" "" valid_optional_text
  ask RESOLVER_CONTACT_POSTCODE "Postal code (optional)" "" valid_optional_text
  ask RESOLVER_CONTACT_COUNTRY "Country (optional)" "" valid_optional_text
  ask RESOLVER_CONTACT_TELEPHONE "Telephone, international format (optional)" "" valid_optional_text

  printf '\n    %sLink management portal%s\n' "$C_BOLD" "$C_OFF"
  PORTAL_HAS_USERS=0
  if command -v docker >/dev/null 2>&1 && volume_exists resolver-portal-config; then
    PORTAL_HAS_USERS=1
    info "The portal already has its user store: existing users are kept, no first user is created."
    PORTAL_ADMIN_USERNAME=${PORTAL_ADMIN_USERNAME:-admin}
    PORTAL_ADMIN_PASSWORD=""
  else
    ask PORTAL_ADMIN_USERNAME "First portal user" "admin" valid_username
    ask_password PORTAL_ADMIN_PASSWORD "Password for $PORTAL_ADMIN_USERNAME"
    if [[ -z ${PORTAL_ADMIN_PASSWORD-} ]]; then
      GENERATED_ADMIN_PASSWORD=$(random_secret 10)
      PORTAL_ADMIN_PASSWORD=$GENERATED_ADMIN_PASSWORD
    fi
  fi

  printf '\n    %sOperation%s\n' "$C_BOLD" "$C_OFF"
  INSTALL_BACKUP_CRON=${INSTALL_BACKUP_CRON:-yes}
  ask INSTALL_BACKUP_CRON "Schedule the daily backup at 02:30 (yes/no)" "yes" valid_yes_no
  if [[ -z ${INSTALL_DOCKER_GROUP_USER+x} ]]; then INSTALL_DOCKER_GROUP_USER=${SUDO_USER:-}; fi
  [[ $INSTALL_DOCKER_GROUP_USER == root ]] && INSTALL_DOCKER_GROUP_USER=""
  ask INSTALL_DOCKER_GROUP_USER "User allowed to run docker without sudo (empty: none)" "" valid_user_or_empty

  secrets
  summary_before
}

secrets() {
  MONGO_USER=$(existing MONGO_INITDB_ROOT_USERNAME); MONGO_USER=${MONGO_USER:-gs1resolver}
  MONGO_PASSWORD=$(existing MONGO_INITDB_ROOT_PASSWORD)
  SESSION_TOKEN=$(existing SESSION_TOKEN)
  local db_exists=0
  command -v docker >/dev/null 2>&1 && volume_exists resolver-database-volume && db_exists=1

  if [[ -z $MONGO_PASSWORD || $MONGO_PASSWORD == gs1resolver ]]; then
    if (( db_exists )); then
      # The database was created with some password we do not know about (probably .env.example's).
      warn "A database already exists but .env has no specific MongoDB password."
      warn "It was most likely created with the development default of .env.example."
      MONGO_PASSWORD=${MONGO_PASSWORD:-gs1resolver}
      warn "Keeping it; change it later with the password rotation procedure in the documentation."
      MONGO_USER=${MONGO_USER:-gs1resolver}
    else
      MONGO_PASSWORD=$(random_secret 24)
      info "A new MongoDB password was generated."
    fi
  else
    info "MongoDB credentials kept from .env."
  fi
  # Keep an existing connection string (it may hold a percent-encoded password); build it otherwise.
  MONGO_URI=$(existing MONGO_URI)
  if [[ -z $MONGO_URI || $MONGO_PASSWORD != "$(existing MONGO_INITDB_ROOT_PASSWORD)" ]]; then
    MONGO_URI="mongodb://$MONGO_USER:$MONGO_PASSWORD@database-service:27017"
  fi
  if [[ -z $SESSION_TOKEN || $SESSION_TOKEN == secret ]]; then
    SESSION_TOKEN=$(random_secret 32)
    info "A new API token was generated."
  else
    info "API token kept from .env."
  fi
  local value
  for value in "$MONGO_PASSWORD" "$MONGO_URI" "$SESSION_TOKEN"; do
    [[ $value != *"'"* ]] || die "A secret in .env contains a single quote; replace it before running the installer."
  done
}

summary_before() {
  printf '\n    %sSummary%s\n' "$C_BOLD" "$C_OFF"
  printf '      Resolver         https://%s\n' "$FQDN"
  printf '      HTTPS            %s\n' "$TLS_MODE"
  printf '      Port %s        published on %s\n' "$PROXY_PORT" "$PROXY_BIND_ADDRESS"
  printf '      Operator         %s\n' "$RESOLVER_ORG_NAME"
  if (( PORTAL_HAS_USERS )); then
    printf '      Portal users     existing users kept\n'
  else
    printf '      First user       %s (password %s)\n' "$PORTAL_ADMIN_USERNAME" \
      "$([[ -n $GENERATED_ADMIN_PASSWORD ]] && echo 'generated, shown at the end' || echo 'as typed')"
  fi
  printf '      Daily backup     %s\n' "$INSTALL_BACKUP_CRON"
  printf '\n'
  confirm "Proceed with the installation?" y || die "Nothing was changed."
}

install_prerequisites() {
  step "Software"
  if docker_ready; then
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) with Compose $(docker compose version --short)"
  else
    if command -v docker >/dev/null 2>&1; then
      warn "Docker Compose $MIN_COMPOSE_VERSION or later is required."
    fi
    confirm "Install Docker Engine and the Compose plugin from the official Docker repository?" y \
      || die "Docker with Compose $MIN_COMPOSE_VERSION or later is required."
    install_docker
    docker_ready || die "Docker was installed but Compose $MIN_COMPOSE_VERSION or later is not available."
    ok "Docker installed"
  fi
  if [[ $TLS_MODE != external ]]; then
    local packages=(nginx)
    [[ $TLS_MODE == letsencrypt ]] && packages+=(certbot python3-certbot-nginx)
    local missing=() p
    for p in "${packages[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if (( ${#missing[@]} )); then
      info "Installing ${missing[*]}…"
      run apt-get update
      run apt-get install -y "${missing[@]}"
    fi
    ok "nginx$([[ $TLS_MODE == letsencrypt ]] && echo ' and Certbot')"
  fi
  if [[ -n $INSTALL_DOCKER_GROUP_USER ]] && ! id -nG "$INSTALL_DOCKER_GROUP_USER" | grep -qw docker; then
    run usermod -aG docker "$INSTALL_DOCKER_GROUP_USER"
    ok "$INSTALL_DOCKER_GROUP_USER added to the docker group (takes effect at the next login)"
  fi
}

start_services() {
  step "Configuration and services"
  write_env
  ok ".env written (mode 600, owner ${SUDO_USER:-root})"
  run compose config --quiet || die "docker compose rejected the configuration; see $LOG_FILE."
  info "Building and starting the services (the first build takes a few minutes)…"
  run compose up -d --build --remove-orphans
  info "Waiting for the resolver and the portal to answer…"
  local waited=0 answer=""
  until answer=$(curl -fsS --max-time 5 "http://127.0.0.1:$PROXY_PORT/portal/healthz" 2>/dev/null) \
        && [[ $answer == *'"portal":"ok"'* && $answer == *'"resolver":"ok"'* ]]; do
    (( waited >= HEALTH_TIMEOUT )) && die "The services did not become healthy in ${HEALTH_TIMEOUT}s. See: docker compose logs"
    sleep 5; waited=$(( waited + 5 ))
  done
  ok "Services running"
  if (( ! PORTAL_HAS_USERS )) && [[ -n $PORTAL_ADMIN_PASSWORD ]]; then
    local count
    count=$(compose exec -T portal-service python -c 'import users; print(len(users.load()))' 2>>"$LOG_FILE" || true)
    if [[ $count =~ ^[1-9][0-9]*$ ]]; then
      # The portal has created the first user; the password no longer needs to be stored.
      set_env_value PORTAL_ADMIN_PASSWORD ""
      ok "First portal user created; its password was removed from .env"
    else
      warn "Could not confirm that the first portal user exists (see: docker compose logs portal-service)."
      warn "PORTAL_ADMIN_PASSWORD stays in .env until you clear it."
    fi
  fi
}

configure_https() {
  [[ $TLS_MODE == external ]] && { step "HTTPS"; info "Left to the external proxy: forward https://$FQDN to this server's port $PROXY_PORT."; return; }
  step "HTTPS"
  local others
  others=$(ss -H -ltnp '( sport = :80 or sport = :443 )' 2>/dev/null | grep -v '"nginx"' || true)
  if [[ -n $others ]]; then
    warn "Another program is listening on port 80 or 443:"
    warn "$(printf '%s' "$others" | awk '{print $4, $6}' | head -n 3)"
    confirm "Continue anyway (nginx may fail to start)?" n || die "Free ports 80 and 443, then run the installer again."
  fi
  open_firewall
  configure_nginx
  [[ $TLS_MODE == letsencrypt ]] && obtain_certificate
  return 0
}

schedule_backup() {
  step "Backup"
  if [[ $INSTALL_BACKUP_CRON != yes ]]; then info "Not scheduled (run scripts/resolver-backup.sh manually)."; return; fi
  chmod 755 "$REPO_DIR/scripts/resolver-backup.sh"
  umask 022
  sed "s|REPOSITORY|$REPO_DIR|" "$REPO_DIR/scripts/resolver-backup.cron" > "$CRON_FILE"
  chmod 644 "$CRON_FILE"
  umask 077
  ok "Daily at 02:30 → /var/backups/resolver (14 days); log /var/log/resolver-backup.log"
}

final_checks() {
  step "Checks"
  local base="https://$FQDN" code
  [[ $TLS_MODE == external ]] && base="http://127.0.0.1:$PROXY_PORT"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$base/" || true)
  if [[ $code == 200 ]]; then ok "$base/ → 200 (home page)"; else warn "$base/ → ${code:-no answer}"; fi
  if curl -fsS --max-time 10 "$base/.well-known/gs1resolver" 2>/dev/null | grep -q '"resolverRoot"'; then
    ok "$base/.well-known/gs1resolver answers"
  else
    warn "$base/.well-known/gs1resolver did not answer as expected"
  fi
}

summary_after() {
  step "Done"
  printf '      Home page        https://%s/\n' "$FQDN"
  printf '      Portal           https://%s/portal/\n' "$FQDN"
  printf '      API docs         https://%s/api/docs  (token: SESSION_TOKEN in %s)\n' "$FQDN" "$ENV_FILE"
  if [[ -n $GENERATED_ADMIN_PASSWORD ]]; then
    printf '\n      %sFirst portal user:  %s  /  %s%s\n' "$C_BOLD" "$PORTAL_ADMIN_USERNAME" "$GENERATED_ADMIN_PASSWORD" "$C_OFF"
    printf '      This password is shown only now. Sign in and change it under Options.\n'
  elif (( ! PORTAL_HAS_USERS )); then
    printf '\n      First portal user: %s (password as typed). Change it under Options if others saw it.\n' "$PORTAL_ADMIN_USERNAME"
  fi
  printf '\n      More users:  docker compose exec portal-service python create_user.py <name>\n'
  printf '      Update:      git pull && docker compose up -d --build\n'
  printf '      Log:         %s\n\n' "$LOG_FILE"
  log "---- installer finished"
}

# ------------------------------------------------------------------------------------ main
main() {
  while (( $# )); do
    case $1 in
      --non-interactive) NON_INTERACTIVE=1; ASSUME_YES=1 ;;
      --yes|-y) ASSUME_YES=1 ;;
      --help|-h) usage; exit 0 ;;
      *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
  done
  printf '%sGS1 Digital Link Resolver CE — installer%s\n' "$C_BOLD" "$C_OFF"
  preflight
  collect_settings
  install_prerequisites
  start_services
  configure_https
  schedule_backup
  final_checks
  summary_after
}

main "$@"
