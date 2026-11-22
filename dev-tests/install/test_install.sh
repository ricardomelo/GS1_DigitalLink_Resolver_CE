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
  # dpkg-query: the version of the host's nginx package, from a state file (a fixed Ubuntu 24.04 build by default)
  cat > "$b/dpkg-query" <<EOF
#!/bin/bash
if [[ "\$*" == *" nginx" ]]; then cat $s/nginx-version 2>/dev/null || printf '1.24.0-2ubuntu7.20'; exit 0; fi
exec /usr/bin/dpkg-query "\$@"
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
  *healthz*) [[ -e STATE/proxy-stale ]] && exit 22
             if [[ -e STATE/worker-down ]]; then echo '{"portal":"ok","resolver":"ok","worker":"unavailable"}'
             else echo '{"portal":"ok","resolver":"ok","worker":"ok"}'; fi ;;
  *http_code*/01/*) if [[ -e STATE/resolver-down ]]; then printf 502; else printf 404; fi ;;
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
    INSTALL_BACKUP_KEY_FILE="$SB/state/keys/backup.key" \
    INSTALL_GEOIP_CRON_FILE="$SB/state/geoip-cron" INSTALL_DOMAINS_CRON_FILE="$SB/state/domains-cron" \
    INSTALL_OS_CODENAME=noble INSTALL_HEALTH_TIMEOUT=30 INSTALL_PROXY_RESTART_AFTER=5 INSTALL_WORKER_TIMEOUT=5 INSTALL_DOCKER_GROUP_USER= "$@" \
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
check "A: portal database password generated (48 hex)" "[[ \$(envval PORTAL_DB_PASSWORD) =~ ^[0-9a-f]{48}$ ]]"
check "A: passwords of the resolver's and the data entry API's database users generated (48 hex, different; ADR 0030)" "[[ \$(envval RESOLVER_DB_PASSWORD) =~ ^[0-9a-f]{48}$ && \$(envval DATA_ENTRY_DB_PASSWORD) =~ ^[0-9a-f]{48}$ && \$(envval RESOLVER_DB_PASSWORD) != \$(envval DATA_ENTRY_DB_PASSWORD) ]]"
check "A: MongoDB's root connection given to the database and portal-db-init only" "[[ \$(compose_cfg | grep -c 'MONGO_URI: mongodb') == 2 ]]"
check "A: portal session key generated (64 hex)" "[[ \$(envval PORTAL_SECRET_KEY) =~ ^[0-9a-f]{64}$ ]]"
check "A: job worker reported running" "grep -q 'Job worker running' $SB/state/out"
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
check "A: the host's nginx installed or updated even when already there (ADR 0042)" "dpkg -s nginx >/dev/null 2>&1 && grep -q '^apt-get install -y nginx certbot python3-certbot-nginx' $SB/state/calls && grep -q '^apt-get update' $SB/state/calls"
check "A: a fixed nginx package reported as carrying the November 2026 fixes" "grep -q 'nginx 1.24.0-2ubuntu7.20 carries the security fixes of November 2026' $SB/state/out && ! grep -q 'predates the security fixes' $SB/state/out"
check "A: the site served over HTTP/1.1 only (no http2)" "! grep -q http2 $SB/nginx/sites-available/gs1resolver"
check "A: the site keeps no access log (ADR 0043)" "[[ \$(grep -c 'access_log off;' $SB/nginx/sites-available/gs1resolver) == \$(grep -c '^ *server_name ' $SB/nginx/sites-available/gs1resolver) ]] && grep -q 'server_name id.example.org;' $SB/nginx/sites-available/gs1resolver"
check "A: one replica of each service written to .env" "[[ \$(envval WEB_SERVICE_REPLICAS)\$(envval DATA_ENTRY_SERVICE_REPLICAS)\$(envval PORTAL_SERVICE_REPLICAS)\$(envval PORTAL_WORKER_REPLICAS) == 1111 ]]"
check "A: Compose reads the replica counts" "[[ \$(compose_cfg | grep -c 'replicas: 1') == 4 ]]"
check "A: replicas in the summary" "grep -q 'Replicas *resolver 1, data entry API 1, portal 1, job worker 1' $SB/state/out"
check "A: no e-mail relay asked for: e-mail off" "[[ -z \$(envval PORTAL_MAIL_HOST) && -z \$(envval PORTAL_MAIL_PASSWORD) ]] && grep -q 'E-mail relay *none (e-mail off)' $SB/state/out"
check "A: time zone of the daily request counts written (the server's, else UTC)" "[[ -n \$(envval PORTAL_TIME_ZONE) ]] && compose_cfg | grep -q \"PORTAL_TIME_ZONE: \$(envval PORTAL_TIME_ZONE)\" && grep -q 'Time zone *'\$(envval PORTAL_TIME_ZONE) $SB/state/out"
check "A: a scan through the proxy checked at the end (404: not registered, but the resolver answered)" "grep -q 'https://id.example.org/01/09506000134352 → 404 (a scan reaches the resolver' $SB/state/out"
check "A: the portal checked through HTTPS at the end" "grep -q 'https://id.example.org/portal/ answers' $SB/state/out"
check "A: backup cron points at the repository" "grep -q \"root $SB/repo/scripts/resolver-backup.sh\" $SB/state/cron"
check "A: the GeoIP database's monthly update scheduled from the repository" "grep -q \"root $SB/repo/scripts/geoip-update.sh\" $SB/state/geoip-cron && [[ \$(stat -c %a $SB/state/geoip-cron) == 644 ]]"
check "A: its first download tried at once; a failure only a warning" "grep -q 'The GeoIP database was not downloaded' $SB/state/out && grep -q 'not downloaded' $SB/state/install.log"
check "A: scan locations in the summary" "grep -q 'Scan locations *yes' $SB/state/out"
check "A: the organisations' own domains applied every 5 minutes, quietly" "grep -q \"^\\*/5 \\* \\* \\* \\* root $SB/repo/scripts/custom-domains.sh apply --quiet\" $SB/state/domains-cron && [[ \$(stat -c %a $SB/state/domains-cron) == 644 ]]"
check "A: age installed for the backups (ADR 0044)" "grep -q '^apt-get install -y nginx certbot python3-certbot-nginx age\$' $SB/state/calls"
check "A: a backup key made with age-keygen, mode 600" "[[ \$(stat -c %a $SB/state/keys/backup.key 2>/dev/null) == 600 ]] && grep -q '^AGE-SECRET-KEY-1' $SB/state/keys/backup.key"
check "A: the backup key named in the summary, with the advice to keep a copy off the server" "grep -q 'Backup key:  $SB/state/keys/backup.key' $SB/state/out && grep -q 'without it no backup can be restored' $SB/state/out"
check "A: the portal's data key generated (64 hex; ADR 0044)" "[[ \$(envval PORTAL_DATA_KEY) =~ ^[0-9a-f]{64}$ && \$(envval PORTAL_DATA_KEY) != \$(envval PORTAL_JOURNAL_KEY) ]]"
A_TOKEN=$(envval SESSION_TOKEN); A_PWD=$(envval MONGO_INITDB_ROOT_PASSWORD)
A_PORTAL_DB=$(envval PORTAL_DB_PASSWORD); A_KEY=$(envval PORTAL_SECRET_KEY); A_RESOLVER_DB=$(envval RESOLVER_DB_PASSWORD)
A_DATA_KEY=$(envval PORTAL_DATA_KEY); A_BACKUP_KEY=$(sha256sum < "$SB/state/keys/backup.key")

# ------------------------------------------------------------------------------ B. re-run
echo "--- B. second run on the same installation"
printf '1.24.0-2ubuntu7.19' > "$SB/state/nginx-version"
printf 'server {\n    listen 443 ssl http2;\n    listen [::]:443 ssl http2;\n    server_name id.example.org;\n}\n' >> "$SB/nginx/sites-available/gs1resolver"
echo "PORTAL_SESSION_IDLE_MINUTES='20'" >> "$SB/repo/.env"
sed -i "s/^WEB_SERVICE_REPLICAS=.*/WEB_SERVICE_REPLICAS='2'/" "$SB/repo/.env"
: > "$SB/state/calls"
run_installer FQDN=id.example.org CERTBOT_EMAIL=ops@example.org PORTAL_WORKER_REPLICAS=3 PORTAL_TIME_ZONE=America/Sao_Paulo \
  PORTAL_MAIL_HOST=smtp.example.org \
  PORTAL_MAIL_USERNAME=portal@example.org PORTAL_MAIL_PASSWORD='relay pass phrase $1' \
  PORTAL_MAIL_FROM='Link portal <noreply@example.org>'; rc=$?
check "B: exit status 0" "[[ $rc == 0 ]]"
check "B: e-mail relay written: STARTTLS on 587 by default" "[[ \$(envval PORTAL_MAIL_HOST) == smtp.example.org && \$(envval PORTAL_MAIL_PORT) == 587 && \$(envval PORTAL_MAIL_SECURITY) == starttls && \$(envval PORTAL_MAIL_USERNAME) == portal@example.org ]]"
check "B: relay password and sender written as given" "[[ \$(envval PORTAL_MAIL_PASSWORD) == 'relay pass phrase \$1' && \$(envval PORTAL_MAIL_FROM) == 'Link portal <noreply@example.org>' ]]"
check "B: relay password neither printed nor logged" "! grep -q 'relay pass phrase' $SB/state/out && ! grep -q 'relay pass phrase' $SB/state/install.log"
check "B: relay in the summary" "grep -q 'E-mail relay *smtp.example.org:587 (starttls), from Link portal <noreply@example.org>' $SB/state/out"
check "B: the portal and its worker receive the relay settings" "[[ \$(compose_cfg | grep -c 'PORTAL_MAIL_HOST: smtp.example.org') -ge 2 ]]"
check "B: no setting written twice (the last line of .env would win)" "[[ -z \$(grep -oE '^[A-Z_]+=' $SB/repo/.env | sort | uniq -d) ]]"
check "B: secrets kept" "[[ \$(envval SESSION_TOKEN) == $A_TOKEN && \$(envval MONGO_INITDB_ROOT_PASSWORD) == $A_PWD ]]"
check "B: portal database password and session key kept" "[[ \$(envval PORTAL_DB_PASSWORD) == $A_PORTAL_DB && \$(envval PORTAL_SECRET_KEY) == $A_KEY ]]"
check "B: the resolver's database password kept" "[[ \$(envval RESOLVER_DB_PASSWORD) == $A_RESOLVER_DB ]]"
check "B: the data key and the backup key kept" "[[ \$(envval PORTAL_DATA_KEY) == $A_DATA_KEY && \$(sha256sum < $SB/state/keys/backup.key) == '$A_BACKUP_KEY' ]] && grep -q 'Backups encrypted with the key in $SB/state/keys/backup.key (kept)' $SB/state/out"
check "B: settings kept from .env (operator)" "[[ \$(envval RESOLVER_ORG_NAME) == 'Example Org' ]]"
check "B: a time zone taken from the environment" "[[ \$(envval PORTAL_TIME_ZONE) == America/Sao_Paulo ]]"
check "B: unmanaged setting carried over" "grep -q \"^PORTAL_SESSION_IDLE_MINUTES='20'\" $SB/repo/.env"
check "B: replica count kept from .env; another taken from the environment" "[[ \$(envval WEB_SERVICE_REPLICAS) == 2 && \$(envval PORTAL_WORKER_REPLICAS) == 3 && \$(envval PORTAL_SERVICE_REPLICAS) == 1 ]]"
check "B: Compose scales the services as written" "[[ \$(compose_cfg | grep -c 'replicas: 2') == 1 && \$(compose_cfg | grep -c 'replicas: 3') == 1 ]]"
check "B: previous .env backed up with mode 600" "ls $SB/repo/.env.bak-* >/dev/null && [[ \$(stat -c %a \$(ls $SB/repo/.env.bak-* | head -n 1)) == 600 ]]"
check "B: existing portal users detected, no first user" "grep -q 'existing users are kept' $SB/state/out && [[ -z \$(envval PORTAL_ADMIN_PASSWORD) ]]"
check "B: site with certificate kept, certbot not called" "! grep -q '^certbot' $SB/state/calls"
check "B: an nginx package without the November 2026 fixes: warned, with the command that updates it" "grep -q 'nginx 1.24.0-2ubuntu7.19 predates the security fixes of November 2026' $SB/state/out && grep -q 'sudo apt-get install --only-upgrade nginx' $SB/state/out"
check "B: a kept site that serves HTTP/2: warned, with the command that turns it off" "grep -q 'The site serves HTTP/2' $SB/state/out && grep -q 'To turn it off: sudo sed -i -E' $SB/state/out"
B_SED=$(grep -o "sed -i -E '[^']*'" "$SB/state/out" | head -n 1)
cp "$SB/nginx/sites-available/gs1resolver" "$SB/state/h2-site"
eval "$B_SED $SB/state/h2-site"
check "B: ... and that command leaves the listen lines without http2, the rest unchanged" "[[ -n \"$B_SED\" ]] && ! grep -q http2 $SB/state/h2-site && [[ \$(grep -c 'listen 443 ssl;' $SB/state/h2-site) == 1 ]] && diff <(grep -v listen $SB/state/h2-site) <(grep -v listen $SB/nginx/sites-available/gs1resolver) >/dev/null"
check "B: a kept site with a server that keeps an access log: warned, with the command that turns it off" "grep -q 'The site keeps an access log' $SB/state/out && grep -q \"To turn it off: sudo sed -i -E -e '/\" $SB/state/out"
B_LOG_SED=$(grep "The site keeps an access log" -A1 "$SB/state/out" | grep -o "sed -i -E -e '[^']*' -e '[^']*'" | head -n 1)
cp "$SB/nginx/sites-available/gs1resolver" "$SB/state/log-site"
eval "$B_LOG_SED $SB/state/log-site"
check "B: ... and that command gives each server one access_log off, the rest unchanged" "[[ -n \"$B_LOG_SED\" ]] && [[ \$(grep -c 'access_log off;' $SB/state/log-site) == 2 ]] && [[ \$(grep -A1 'server_name' $SB/state/log-site | grep -c 'access_log off;') == 2 ]] && diff <(grep -v access_log $SB/state/log-site) <(grep -v access_log $SB/nginx/sites-available/gs1resolver) >/dev/null"

# ------------------------------------------------------------------------------ C. server migrated by hand
echo "--- C. existing .env written by hand (double quotes, percent-encoded URI), volumes present"
new_sandbox
cat > "$SB/repo/.env" <<'EOF'
MONGO_INITDB_ROOT_USERNAME=resolveradmin
MONGO_INITDB_ROOT_PASSWORD=p@ss:w0rd!xyz
MONGO_URI=mongodb://resolveradmin:p%40ss%3Aw0rd%21xyz@database-service:27017
SESSION_TOKEN=0123456789abcdef0123456789abcdef
DATA_ENTRY_DB_PASSWORD=resolver_data_entry
FQDN=idhml.example.org
RESOLVER_ORG_NAME="GS1 Example"
RESOLVER_CONTACT_STREET="Av. Exemplo, 328 - Pinheiros"
BACKUP_RECIPIENTS=age1lggyhqrw2nlhcxprm67z43rta597azn8gknawjehu9d9dl0jq3yqqvfafg
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
check "C: an installation from before the portal's database gets its password and session key" "[[ \$(envval PORTAL_DB_PASSWORD) =~ ^[0-9a-f]{48}$ && \$(envval PORTAL_SECRET_KEY) =~ ^[0-9a-f]{64}$ ]]"
check "C: an installation from before ADR 0030 gets the services' database passwords, the example one replaced" "[[ \$(envval RESOLVER_DB_PASSWORD) =~ ^[0-9a-f]{48}$ && \$(envval DATA_ENTRY_DB_PASSWORD) =~ ^[0-9a-f]{48}$ ]]"
check "C: quoted values read correctly" "[[ \$(envval RESOLVER_CONTACT_STREET) == 'Av. Exemplo, 328 - Pinheiros' ]]"
check "C: existing certificate site kept" "grep -q snakeoil $SB/nginx/sites-available/gs1resolver && ! grep -q '^certbot' $SB/state/calls"
check "C: BACKUP_RECIPIENTS in .env: no backup key made on the server, the recipients kept" "[[ ! -e $SB/state/keys/backup.key ]] && grep -q 'Backups encrypted to BACKUP_RECIPIENTS of .env' $SB/state/out && ! grep -q 'Backup key:' $SB/state/out && [[ \$(envval BACKUP_RECIPIENTS) == age1lggyhqrw2nlhcxprm67z43rta597azn8gknawjehu9d9dl0jq3yqqvfafg ]]"
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
check "D: the HTTPS site without HTTP/2 (listen 443 ssl, ADR 0042)" "grep -q 'listen 443 ssl;' $SB/nginx/sites-available/gs1resolver && ! grep -Eq '^[^#]*http2' $SB/nginx/sites-available/gs1resolver"
check "D: neither of the HTTPS site's servers keeps an access log (ADR 0043)" "[[ \$(grep -c 'access_log off;' $SB/nginx/sites-available/gs1resolver) == 2 && \$(grep -c '^ *server_name ' $SB/nginx/sites-available/gs1resolver) == 2 ]]"
check "D: no schedule for the organisations' domains (no Let's Encrypt), and how to add one" "[[ ! -e $SB/state/domains-cron ]] && grep -q 'install scripts/custom-domains.cron' $SB/state/out"

# ------------------------------------------------------------------------------ E. external proxy
echo "--- E. external mode"
new_sandbox
run_installer FQDN=id.example.org TLS_MODE=external PROXY_BIND_ADDRESS=0.0.0.0 RESOLVER_ORG_NAME=Org \
  INSTALL_BACKUP_CRON=no INSTALL_GEOIP=no; rc=$?
check "E: exit status 0" "[[ $rc == 0 ]]"
check "E: no nginx site" "[[ ! -e $SB/nginx/sites-available/gs1resolver ]]"
check "E: proxy published on 0.0.0.0" "compose_cfg | grep -B3 'published: \"8080\"' | grep -q 'host_ip: 0.0.0.0'"
check "E: database stays on 127.0.0.1" "compose_cfg | grep -B3 'published: \"27017\"' | grep -q 'host_ip: 127.0.0.1'"
check "E: no cron when declined" "[[ ! -e $SB/state/cron ]]"
check "E: no schedule for the organisations' domains behind an external proxy" "[[ ! -e $SB/state/domains-cron ]]"
check "E: no GeoIP update when declined" "[[ ! -e $SB/state/geoip-cron ]] && grep -q 'Not recorded (no GeoIP database' $SB/state/out"
check "E: age installed without nginx; the backup key made though the backup is not scheduled" "grep -q '^apt-get install -y age\$' $SB/state/calls && ! grep -q 'install -y.*nginx' $SB/state/calls && [[ -e $SB/state/keys/backup.key ]]"

# ------------------------------------------------------------------------------ F. interactive
echo "--- F. interactive answers"
new_sandbox
answers=$(printf '%s\n' \
  "not a domain" "id.example.org" \
  "" "ops@example.org" \
  "Example Org" "ftp://bad" "https://www.example.org" "" "Rio de Janeiro" "RJ" "" "Brazil" "" \
  "maria" "short" "it's a long password" "correct horse battery" "correct horse battery" \
  "" \
  "" "" "" "y")
INSTALLER_ARGS=" " run_installer <<< "$answers"; rc=$?
check "F: exit status 0" "[[ $rc == 0 ]]"
check "F: invalid domain rejected, then accepted" "grep -q 'Enter a domain name' $SB/state/out && [[ \$(envval FQDN) == id.example.org ]]"
check "F: invalid URL rejected" "grep -q 'Enter a URL starting with https://' $SB/state/out && [[ \$(envval RESOLVER_ORG_URL) == https://www.example.org ]]"
check "F: default HTTPS mode taken" "[[ \$(envval TLS_MODE) == letsencrypt ]]"
check "F: short password rejected; typed user used" "grep -q 'At least 12 characters' $SB/state/out && [[ \$(envval PORTAL_ADMIN_USERNAME) == maria ]]"
check "F: typed password not printed" "! grep -q 'correct horse' $SB/state/out"
check "F: e-mail relay left empty: e-mail off" "grep -q 'An authenticated SMTP relay' $SB/state/out && [[ -z \$(envval PORTAL_MAIL_HOST) ]]"
check "F: password with a single quote rejected, then another accepted" "grep -q 'Single quotes' $SB/state/out && [[ \$(envval PORTAL_ADMIN_USERNAME) == maria ]]"

# ------------------------------------------------------------------------------ G. refusals
echo "--- G. invalid non-interactive input"
new_sandbox
run_installer FQDN=https://id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org; rc=$?
check "G: invalid FQDN stops the installer" "[[ $rc != 0 ]] && grep -q 'FQDN: invalid' $SB/state/out"
check "G: nothing written" "[[ ! -e $SB/repo/.env ]]"
new_sandbox
run_installer FQDN=id.example.org RESOLVER_ORG_NAME="O'Brien" CERTBOT_EMAIL=a@b.org; rc=$?
check "G: single quote refused" "[[ $rc != 0 ]] && grep -q 'Single quotes' $SB/state/out"
new_sandbox
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_ADMIN_PASSWORD="it's a long password"; rc=$?
check "G: password with a single quote refused" "[[ $rc != 0 ]] && grep -q 'Single quotes' $SB/state/out && grep -q 'PORTAL_ADMIN_PASSWORD: invalid password' $SB/state/out"
check "G: nothing written for the refused password" "[[ ! -e $SB/repo/.env ]]"

run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_SERVICE_REPLICAS=0; rc=$?
check "G: zero replicas refused" "[[ $rc != 0 ]] && grep -q 'PORTAL_SERVICE_REPLICAS: invalid value' $SB/state/out && [[ ! -e $SB/repo/.env ]]"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org WEB_SERVICE_REPLICAS=two; rc=$?
check "G: a replica count that is not a number refused" "[[ $rc != 0 ]] && grep -q 'WEB_SERVICE_REPLICAS: invalid value' $SB/state/out"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_TIME_ZONE='../../etc/passwd'; rc=$?
check "G: a time zone that is not an IANA name refused" "[[ $rc != 0 ]] && grep -q 'PORTAL_TIME_ZONE: invalid value' $SB/state/out"

new_sandbox
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_MAIL_HOST=smtp.example.org \
  PORTAL_MAIL_USERNAME=portal PORTAL_MAIL_FROM=noreply@example.org; rc=$?
check "G: a relay user name without a password refused" "[[ $rc != 0 ]] && grep -q 'PORTAL_MAIL_PASSWORD: a password is required' $SB/state/out && [[ ! -e $SB/repo/.env ]]"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_MAIL_HOST=smtp.example.org \
  PORTAL_MAIL_FROM=noreply; rc=$?
check "G: a sender that is not an address refused" "[[ $rc != 0 ]] && grep -q 'PORTAL_MAIL_FROM: invalid' $SB/state/out"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org PORTAL_MAIL_HOST='smtp example' \
  PORTAL_MAIL_FROM=noreply@example.org; rc=$?
check "G: a relay host that is not a host name refused" "[[ $rc != 0 ]] && grep -q 'PORTAL_MAIL_HOST: invalid' $SB/state/out"

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

# ------------------------------------------------------------------------------ I. job worker
echo "--- I. the portal answers but its job worker does not"
new_sandbox
touch "$SB/state/worker-down"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org; rc=$?
check "I: exit status 0 (the portal works; only background jobs wait)" "[[ $rc == 0 ]]"
check "I: warning naming the portal-worker log" "grep -q 'job worker is not running' $SB/state/out && grep -q 'docker compose logs portal-worker' $SB/state/out"
check "I: no 'Job worker running' line" "! grep -q 'Job worker running' $SB/state/out"

# ------------------------------------------------------------------------------ K. resolver down behind the proxy
echo "--- K. the portal answers but a scan gets 502 through the proxy"
new_sandbox
touch "$SB/state/resolver-down"
run_installer FQDN=id.example.org RESOLVER_ORG_NAME=Org CERTBOT_EMAIL=a@b.org; rc=$?
check "K: exit status 0 (a warning, as the other final checks)" "[[ $rc == 0 ]]"
check "K: the warning names the code, the answer and the log to read" "grep -q '/01/09506000134352 → 502: a scan does not reach the resolver' $SB/state/out && grep -q 'docker compose logs web-service' $SB/state/out"

# ------------------------------------------------------------------------------ J. e-mail relay
echo "--- J. e-mail relay: TLS, kept on a second run, switched off"
new_sandbox
run_installer "${BASE[@]}" PORTAL_MAIL_HOST=smtp.example.org PORTAL_MAIL_SECURITY=tls PORTAL_MAIL_USERNAME=portal \
  PORTAL_MAIL_PASSWORD=relay-secret PORTAL_MAIL_FROM=noreply@example.org; rc=$?
check "J: exit status 0" "[[ $rc == 0 ]]"
check "J: TLS on 465 by default" "[[ \$(envval PORTAL_MAIL_SECURITY) == tls && \$(envval PORTAL_MAIL_PORT) == 465 ]]"
run_installer FQDN=id.example.org CERTBOT_EMAIL=ops@example.org; rc=$?
check "J: a second run keeps the relay and its password" "[[ $rc == 0 && \$(envval PORTAL_MAIL_HOST) == smtp.example.org && \$(envval PORTAL_MAIL_PASSWORD) == relay-secret && \$(envval PORTAL_MAIL_PORT) == 465 ]]"
run_installer FQDN=id.example.org CERTBOT_EMAIL=ops@example.org PORTAL_MAIL_HOST=off; rc=$?
check "J: \"off\" switches e-mail off and forgets the credentials" "[[ $rc == 0 && -z \$(envval PORTAL_MAIL_HOST) && -z \$(envval PORTAL_MAIL_PASSWORD) && -z \$(envval PORTAL_MAIL_USERNAME) ]]"
printf "PORTAL_MAIL_HOST='mailpit'\nPORTAL_MAIL_PORT='1025'\nPORTAL_MAIL_SECURITY='none'\nPORTAL_MAIL_FROM='portal@example.org'\n" >> "$SB/repo/.env"
run_installer FQDN=id.example.org CERTBOT_EMAIL=ops@example.org; rc=$?
check "J: a test relay set by hand (mailpit, no encryption) is kept" "[[ $rc == 0 && \$(envval PORTAL_MAIL_HOST) == mailpit && \$(envval PORTAL_MAIL_SECURITY) == none && \$(envval PORTAL_MAIL_PORT) == 1025 ]]"

# ------------------------------------------------------------------------------ L. the host's nginx versions
echo "--- L. which nginx packages carry the security fixes of November 2026 (ADR 0042)"
eval "$(sed -n '/^declare -A HOST_NGINX_FIXED/,/^}/p' "$HERE/../../scripts/install.sh")"
for case in "1.24.0-2ubuntu7.19 noble no" "1.24.0-2ubuntu7.20 noble yes" "1.24.0-2ubuntu8 noble yes" \
            "1.18.0-6ubuntu14.23 jammy no" "1.18.0-6ubuntu14.24 jammy yes" "1.18.0-6ubuntu14.24 focal unknown" \
            "1.30.6-1~noble noble no" "1.30.7-1~noble noble yes" "1.31.8-1~jammy jammy no" "1.31.9-1~jammy jammy yes" \
            "1.28.3-1~noble noble no" "1.32.0-1~noble noble yes"; do
  read -r version codename expected <<< "$case"
  check "L: nginx $version on $codename: $expected" "[[ \$(host_nginx_fixed $version $codename) == $expected ]]"
done

echo
echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
