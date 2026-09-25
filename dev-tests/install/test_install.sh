#!/usr/bin/env bash
# Development test for scripts/install.sh without touching the machine.
#
# Each scenario copies the repository to a temporary folder and runs the installer as root with
# stand-ins ("shims") for apt-get, systemctl, docker, certbot and curl. What stays real:
#   * the installer's own logic, prompts and validation;
#   * the .env it writes, checked with the real "docker compose config" (Compose binary required);
#   * the nginx site it renders, checked with the real "nginx -t".
#
# Requirements: bash, root (or a user namespace where root is emulated), nginx, openssl, and a
# Docker Compose v2 binary at $COMPOSE_BIN (default: /tmp/docker-compose or "docker compose").
#   sudo COMPOSE_BIN=/path/to/docker-compose dev-tests/install/test_install.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
COMPOSE_BIN=${COMPOSE_BIN:-/tmp/docker-compose}
REAL_NGINX=$(command -v nginx || echo /usr/sbin/nginx)
PASS=0; FAIL=0

check() { if eval "$2"; then echo "PASS $1"; PASS=$((PASS+1)); else echo "FAIL $1"; FAIL=$((FAIL+1)); fi; }

# ------------------------------------------------------------------------------ sandbox
new_sandbox() {
  SB=$(mktemp -d /tmp/install-test.XXXXXX); LAST_SB=$SB
  mkdir -p "$SB/repo" "$SB/bin" "$SB/state" "$SB/nginx/sites-available" "$SB/nginx/sites-enabled"
  (cd "$REPO" && git ls-files -co --exclude-standard -z | xargs -0 cp --parents -t "$SB/repo" 2>/dev/null)
  cp -r "$REPO/scripts" "$SB/repo/"            # includes files not yet committed
  write_shims
}

write_shims() {
  local b=$SB/bin s=$SB/state
  cat > "$b/apt-get" <<EOF
#!/bin/bash
echo "apt-get \$*" >> $s/calls
EOF
  cat > "$b/systemctl" <<EOF
#!/bin/bash
echo "systemctl \$*" >> $s/calls
EOF
  cat > "$b/usermod" <<EOF
#!/bin/bash
echo "usermod \$*" >> $s/calls
EOF
  # certbot: records the call and adds a certificate to the site, as the nginx plugin does
  cat > "$b/certbot" <<EOF
#!/bin/bash
echo "certbot \$*" >> $s/calls
printf '    ssl_certificate /etc/letsencrypt/live/x/fullchain.pem; # managed by Certbot\n' >> $SB/nginx/sites-available/gs1resolver.certbot-marker
echo "# ssl_certificate added by certbot" >> $SB/nginx/sites-available/gs1resolver
EOF
  # nginx -t against a minimal main configuration that includes the rendered sites
  cat > "$SB/nginx/nginx.conf" <<EOF
pid $SB/nginx/nginx.pid;
error_log $SB/nginx/error.log;
events {}
http { include $SB/nginx/sites-enabled/*; }
EOF
  cat > "$b/nginx" <<EOF
#!/bin/bash
echo "nginx \$*" >> $s/calls
exec $REAL_NGINX -t -q -c $SB/nginx/nginx.conf -p $SB/nginx
EOF
  # curl: health and final checks answer as a healthy installation would
  cat > "$b/curl" <<'EOF'
#!/bin/bash
args="$*"
case $args in
  *healthz*) [[ -e STATE/proxy-stale ]] && exit 22; echo '{"portal":"ok","resolver":"ok"}' ;;
  *http_code*) printf 200 ;;
  *gs1resolver*) echo '{"resolverRoot": "https://x"}' ;;
  *) exit 22 ;;
esac
EOF
  # docker: version checks, volumes from marker files, compose config via the real binary
  cat > "$b/docker" <<EOF
#!/bin/bash
echo "docker \$*" >> $s/calls
if [[ \$1 == --version ]]; then echo "Docker version 28.0.0, build x"; exit 0; fi
if [[ \$1 == volume && \$2 == ls ]]; then
  for f in $s/volume-*; do [[ -e \$f ]] || continue; v=\${f##*/volume-}; [[ "\$*" == *"volume=\$v"* ]] && echo "proj_\$v"; done
  exit 0
fi
if [[ \$1 == compose ]]; then
  shift
  case \$1 in
    version) echo "2.39.2" ;;
    config) exec $COMPOSE_BIN config "\${@:2}" ;;
    up) touch $s/volume-resolver-database-volume $s/volume-resolver-portal-config; echo up >> $s/compose-up ;;
    exec) echo 1 ;;          # number of portal users
    restart) echo "restart \$*" >> $s/calls; rm -f $s/proxy-stale ;;
    *) ;;
  esac
  exit 0
fi
exit 0
EOF
  sed -i "s|STATE|$s|g" "$b/curl"
  chmod +x "$b"/*
}

run_installer() {   # extra environment as arguments; answers (if any) on stdin
  # INSTALLER_ARGS is split on purpose: " " means "no arguments" (interactive mode).
  # shellcheck disable=SC2086
  env -i PATH="$SB/bin:/usr/sbin:/usr/bin:/sbin:/bin" HOME=/root TERM=dumb \
    INSTALL_LOG_FILE="$SB/state/install.log" INSTALL_NGINX_AVAILABLE="$SB/nginx/sites-available" \
    INSTALL_NGINX_ENABLED="$SB/nginx/sites-enabled" INSTALL_CRON_FILE="$SB/state/cron" \
    INSTALL_HEALTH_TIMEOUT=30 INSTALL_PROXY_RESTART_AFTER=5 INSTALL_DOCKER_GROUP_USER= "$@" \
    bash "$SB/repo/scripts/install.sh" ${INSTALLER_ARGS:---non-interactive} > "$SB/state/out" 2>&1
}

envval() { grep -E "^$1=" "$SB/repo/.env" | tail -n 1 | sed -E "s/^$1=//; s/^'(.*)'$/\1/"; }
compose_cfg() { (cd "$SB/repo" && $COMPOSE_BIN config 2>/dev/null); }

BASE=(FQDN=id.example.org TLS_MODE=letsencrypt CERTBOT_EMAIL=ops@example.org
      RESOLVER_ORG_NAME="Example Org" RESOLVER_CONTACT_LOCALITY="São Paulo" RESOLVER_CONTACT_COUNTRY=Brazil)

# ------------------------------------------------------------------------------ A. fresh, Let's Encrypt
echo "--- A. fresh installation, letsencrypt, non-interactive"
new_sandbox
run_installer "${BASE[@]}"; rc=$?
check "A: exit status 0" "[[ $rc == 0 ]]"
check "A: .env mode 600" "[[ \$(stat -c %a $SB/repo/.env) == 600 ]]"
check "A: MongoDB password generated (48 hex)" "[[ \$(envval MONGO_INITDB_ROOT_PASSWORD) =~ ^[0-9a-f]{48}$ ]]"
check "A: MONGO_URI matches the password" "[[ \$(envval MONGO_URI) == mongodb://gs1resolver:\$(envval MONGO_INITDB_ROOT_PASSWORD)@database-service:27017 ]]"
check "A: API token generated (64 hex)" "[[ \$(envval SESSION_TOKEN) =~ ^[0-9a-f]{64}$ ]]"
check "A: first-user password cleared after start" "[[ -z \$(envval PORTAL_ADMIN_PASSWORD) && \$(envval PORTAL_ADMIN_USERNAME) == admin ]]"
check "A: generated password shown once in the summary" "grep -Eq 'First portal user: +admin +/ +[0-9a-f]{20}' $SB/state/out"
A_ADMIN=$(grep -Eo 'First portal user: +admin +/ +[0-9a-f]{20}' "$SB/state/out" | grep -Eo '[0-9a-f]{20}$')
check "A: generated password not in the log" "[[ -n '$A_ADMIN' ]] && ! grep -q '$A_ADMIN' $SB/state/install.log"
check "A: Compose accepts .env; values reach the services" "compose_cfg | grep -q 'RESOLVER_CONTACT_LOCALITY: São Paulo'"
check "A: ports bound to 127.0.0.1" "[[ \$(compose_cfg | grep -c 'host_ip: 127.0.0.1') == 2 ]]"
check "A: nginx site rendered for the domain" "grep -q 'server_name id.example.org;' $SB/nginx/sites-available/gs1resolver"
check "A: nginx site enabled" "[[ -L $SB/nginx/sites-enabled/gs1resolver ]]"
check "A: nginx -t passed" "grep -q '^nginx -t' $SB/state/calls"
check "A: certbot called for the domain" "grep -q 'certbot --nginx -d id.example.org --non-interactive --agree-tos -m ops@example.org --redirect' $SB/state/calls"
check "A: nginx and certbot packages requested" "grep -q 'apt-get install -y.*certbot python3-certbot-nginx' $SB/state/calls"
check "A: backup cron points at the repository" "grep -q \"root $SB/repo/scripts/resolver-backup.sh\" $SB/state/cron"
A_TOKEN=$(envval SESSION_TOKEN); A_PWD=$(envval MONGO_INITDB_ROOT_PASSWORD)

# ------------------------------------------------------------------------------ B. re-run
echo "--- B. second run on the same installation"
echo "PORTAL_SESSION_HOURS='12'" >> "$SB/repo/.env"
: > "$SB/state/calls"
run_installer FQDN=id.example.org CERTBOT_EMAIL=ops@example.org; rc=$?
check "B: exit status 0" "[[ $rc == 0 ]]"
check "B: secrets kept" "[[ \$(envval SESSION_TOKEN) == $A_TOKEN && \$(envval MONGO_INITDB_ROOT_PASSWORD) == $A_PWD ]]"
check "B: settings kept from .env (operator)" "[[ \$(envval RESOLVER_ORG_NAME) == 'Example Org' ]]"
check "B: unmanaged setting carried over" "grep -q \"^PORTAL_SESSION_HOURS='12'\" $SB/repo/.env"
check "B: previous .env backed up with mode 600" "ls $SB/repo/.env.bak-* >/dev/null && [[ \$(stat -c %a \$(ls $SB/repo/.env.bak-* | head -n 1)) == 600 ]]"
check "B: existing portal users detected, no first user" "grep -q 'existing users are kept' $SB/state/out && [[ -z \$(envval PORTAL_ADMIN_PASSWORD) ]]"
check "B: site with certificate kept, certbot not called" "! grep -q '^certbot' $SB/state/calls"

# ------------------------------------------------------------------------------ C. server migrated by hand
echo "--- C. existing .env written by hand (double quotes, percent-encoded URI), volumes present"
new_sandbox
cat > "$SB/repo/.env" <<'EOF'
MONGO_INITDB_ROOT_USERNAME=resolveradmin
MONGO_INITDB_ROOT_PASSWORD=p@ss:w0rd!xyz
MONGO_URI=mongodb://resolveradmin:p%40ss%3Aw0rd%21xyz@database-service:27017
SESSION_TOKEN=0123456789abcdef0123456789abcdef
FQDN=idhml.example.org
RESOLVER_ORG_NAME="GS1 Example"
RESOLVER_CONTACT_STREET="Av. Exemplo, 328 - Pinheiros"
EOF
touch "$SB/state/volume-resolver-database-volume" "$SB/state/volume-resolver-portal-config"
cat > "$SB/nginx/sites-available/gs1resolver" <<'EOF'
server { listen 80; server_name idhml.example.org; return 301 https://$host$request_uri; }
server {
    listen 443 ssl; server_name idhml.example.org;
    ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;
    ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;
    location / { proxy_pass http://127.0.0.1:8080; }
}
EOF
run_installer TLS_MODE=letsencrypt CERTBOT_EMAIL=ops@example.org; rc=$?
check "C: exit status 0" "[[ $rc == 0 ]]"
check "C: percent-encoded MONGO_URI kept as is" "[[ \$(envval MONGO_URI) == 'mongodb://resolveradmin:p%40ss%3Aw0rd%21xyz@database-service:27017' ]]"
check "C: MongoDB user and token kept" "[[ \$(envval MONGO_INITDB_ROOT_USERNAME) == resolveradmin && \$(envval SESSION_TOKEN) == 0123456789abcdef0123456789abcdef ]]"
check "C: quoted values read correctly" "[[ \$(envval RESOLVER_CONTACT_STREET) == 'Av. Exemplo, 328 - Pinheiros' ]]"
check "C: existing certificate site kept" "grep -q snakeoil $SB/nginx/sites-available/gs1resolver && ! grep -q '^certbot' $SB/state/calls"
check "C: Compose accepts the rewritten .env" "compose_cfg | grep -q 'MONGO_URI: mongodb://resolveradmin:p%40ss'"

# ------------------------------------------------------------------------------ D. own certificate
echo "--- D. certificate mode"
new_sandbox
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=id.example.org \
  -keyout "$SB/state/key.pem" -out "$SB/state/cert.pem" >/dev/null 2>&1
run_installer FQDN=id.example.org TLS_MODE=certificate TLS_CERT_FILE="$SB/state/cert.pem" \
  TLS_KEY_FILE="$SB/state/key.pem" RESOLVER_ORG_NAME=Org; rc=$?
check "D: exit status 0" "[[ $rc == 0 ]]"
check "D: HTTPS site with the given files" "grep -Eq \"ssl_certificate +$SB/state/cert.pem;\" $SB/nginx/sites-available/gs1resolver"
check "D: nginx -t passed with the certificate" "grep -q '^nginx -t' $SB/state/calls && ! grep -q 'rejected' $SB/state/out"
check "D: certbot not used" "! grep -q '^certbot' $SB/state/calls"

# ------------------------------------------------------------------------------ E. external proxy
echo "--- E. external mode"
new_sandbox
run_installer FQDN=id.example.org TLS_MODE=external PROXY_BIND_ADDRESS=0.0.0.0 RESOLVER_ORG_NAME=Org \
  INSTALL_BACKUP_CRON=no; rc=$?
check "E: exit status 0" "[[ $rc == 0 ]]"
check "E: no nginx site" "[[ ! -e $SB/nginx/sites-available/gs1resolver ]]"
check "E: proxy published on 0.0.0.0" "compose_cfg | grep -B3 'published: \"8080\"' | grep -q 'host_ip: 0.0.0.0'"
check "E: database stays on 127.0.0.1" "compose_cfg | grep -B3 'published: \"27017\"' | grep -q 'host_ip: 127.0.0.1'"
check "E: no cron when declined" "[[ ! -e $SB/state/cron ]]"

# ------------------------------------------------------------------------------ F. interactive
echo "--- F. interactive answers"
new_sandbox
answers=$(printf '%s\n' \
  "not a domain" "id.example.org" \
  "" "ops@example.org" \
  "Example Org" "ftp://bad" "https://www.example.org" "" "Rio de Janeiro" "RJ" "" "Brazil" "" \
  "maria" "short" "correct horse battery" "correct horse battery" \
  "" "" "y")
INSTALLER_ARGS=" " run_installer <<< "$answers"; rc=$?
check "F: exit status 0" "[[ $rc == 0 ]]"
check "F: invalid domain rejected, then accepted" "grep -q 'Enter a domain name' $SB/state/out && [[ \$(envval FQDN) == id.example.org ]]"
check "F: invalid URL rejected" "grep -q 'Enter a URL starting with https://' $SB/state/out && [[ \$(envval RESOLVER_ORG_URL) == https://www.example.org ]]"
check "F: default HTTPS mode taken" "[[ \$(envval TLS_MODE) == letsencrypt ]]"
check "F: short password rejected; typed user used" "grep -q 'At least 12 characters' $SB/state/out && [[ \$(envval PORTAL_ADMIN_USERNAME) == maria ]]"
check "F: typed password not printed" "! grep -q 'correct horse' $SB/state/out"

# ------------------------------------------------------------------------------ G. refusals
echo "--- G. invalid non-interactive input"
new_sandbox
run_installer FQDN=https://id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org; rc=$?
check "G: invalid FQDN stops the installer" "[[ $rc != 0 ]] && grep -q 'FQDN: invalid' $SB/state/out"
check "G: nothing written" "[[ ! -e $SB/repo/.env ]]"
new_sandbox
run_installer FQDN=id.example.org RESOLVER_ORG_NAME="O'Brien" CERTBOT_EMAIL=a@b.org; rc=$?
check "G: single quote refused" "[[ $rc != 0 ]] && grep -q 'Single quotes' $SB/state/out"

# ------------------------------------------------------------------------------ H. stale proxy
echo "--- H. proxy still pointing at the old containers (502) after the services were recreated"
new_sandbox
printf "FQDN='id.example.org'\nRESOLVER_ORG_NAME='Org'\nCERTBOT_EMAIL='a@b.org'\n" > "$SB/repo/.env"
chown nobody: "$SB/repo/.env"
touch "$SB/state/proxy-stale" "$SB/state/volume-resolver-portal-config"
run_installer SUDO_USER=nobody; rc=$?
check "H: exit status 0" "[[ $rc == 0 ]]"
check "H: proxy restarted once" "[[ \$(grep -c 'compose restart frontend-proxy-service' $SB/state/calls) == 1 ]]"
check "H: .env and its backup keep the sudo user as owner" "[[ \$(stat -c %U $SB/repo/.env) == nobody && \$(stat -c %U \$(ls $SB/repo/.env.bak-* | head -n 1)) == nobody ]]"

echo
echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
