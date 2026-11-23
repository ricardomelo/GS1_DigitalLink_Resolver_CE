#!/usr/bin/env bash
# The organisations' own domains on the host (Documentation/adr/0009-tenant-domains.md): the verified domains whose
# mode is "direct" (they point at this server) need an nginx site and a certificate, as the installation's own name.
# This script reads them from the portal's database (mongosh inside the database container: the credentials stay in
# the container) and, for each one without a site, writes one from the installer's template and asks Certbot for its
# certificate. Domains removed in the portal keep their site until it is deleted by hand (printed by "list").
#
# Only the resolver answers on an organisation's domain (Documentation/adr/0045-organisation-domains-resolver-only.md):
# each site includes a rule file this script writes (NGINX_SNIPPETS/gs1resolver-domain-paths.conf) that sends the
# portal's addresses to the installation's own name (PORTAL_ORIGIN, else RESOLVER_PUBLIC_URL, else https://FQDN) and
# refuses the official data entry API (/api, /swaggerui) with 404. Sites written before get the include at the next
# run, nginx tested first and the sites put back as they were when nginx refuses them.
#
#   sudo scripts/custom-domains.sh list             each domain, whether it has a site and a certificate
#   sudo scripts/custom-domains.sh apply [--quiet]  a site and a certificate for each new one (Let's Encrypt;
#                                                   CERTBOT_EMAIL from the environment or .env)
#
# The installer schedules "apply --quiet" every 5 minutes (scripts/custom-domains.cron; ADR 0009, section 7), so a domain
# verified in the portal is served within minutes without the terminal. Each run reports to the portal, which shows it
# on the domain's card: one document per domain in the collection domain_hosts (served or failed, the certificate's end
# date, the next attempt) and the setting domains.hostRun. After a failed certificate the next attempt waits 5, 10, 20…
# up to 360 minutes, so a domain whose DNS does not point here yet stays below Let's Encrypt's limits. A run holds a
# lock: a slow Certbot never overlaps the next run. --quiet prints nothing when nothing changed.
# Settings can be overridden from the environment.
set -euo pipefail

RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
NGINX_AVAILABLE="${NGINX_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_ENABLED="${NGINX_ENABLED:-/etc/nginx/sites-enabled}"
PROXY_PORT="${PROXY_PORT:-8080}"
NGINX_SNIPPETS="${NGINX_SNIPPETS:-/etc/nginx/snippets}"
TEMPLATE="$RESOLVER_DIR/scripts/templates/nginx-site-http.conf"
SITE_PREFIX="gs1resolver-domain-"
RULE_FILE="$NGINX_SNIPPETS/gs1resolver-domain-paths.conf"
LOCK_FILE="${LOCK_FILE:-/run/lock/gs1resolver-domains.lock}"
MAX_WAIT_MINUTES=360
QUIET=0

cd "$RESOLVER_DIR"

# A value of .env (or .env.example), quotes removed
setting() {
  sed -n "s/^$1=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true
}

DB="$(setting PORTAL_DB_NAME)"
DB="${DB:-resolver_portal}"

# JavaScript run by mongosh in the portal's database, inside the database container (the credentials stay there); the
# script and its values travel as environment variables, never on the host's command line or through a shell.
#   portal_js <JavaScript> [NAME=value …]
portal_js() {
  local js=$1 pairs=() pair
  shift
  for pair in "$@"; do pairs+=(-e "$pair"); done
  docker compose exec -T -e PORTAL_DB="$DB" -e JS="$js" "${pairs[@]}" database-service sh -c \
    'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet "$PORTAL_DB" --eval "$JS"'
}

# The verified direct domains, one per line: name, failed attempts, next attempt, state and the certificate's end
# (seconds since 1970; 0 for none), separated by tabs
DOMAINS_JS='const hosts = {}; db.domain_hosts.find().forEach(h => { hosts[h._id] = h; });
const secs = d => d ? Math.floor(d.getTime() / 1000) : 0;
db.domains.find({verified: true, mode: "direct"}, {_id: 1}).sort({_id: 1}).forEach(d => {
  const h = hosts[d._id] || {};
  print([d._id, h.attempts || 0, secs(h.nextAttemptAt), h.state || "", secs(h.certificateUntil)].join("\t"));
});'
domains() { portal_js "$DOMAINS_JS"; }

# What happened to a domain, for its card in the portal:  record <domain> <state> <attempts> <next> <error> <until>
RECORD_JS='const e = process.env; const at = s => Number(s) ? new Date(Number(s) * 1000) : null;
db.domain_hosts.updateOne({_id: e.D_NAME}, {$set: {state: e.D_STATE, checkedAt: new Date(), attempts: Number(e.D_ATTEMPTS),
  nextAttemptAt: at(e.D_NEXT), error: e.D_ERROR || null, certificateUntil: at(e.D_UNTIL)}}, {upsert: true});'
record() {
  portal_js "$RECORD_JS" "D_NAME=$1" "D_STATE=$2" "D_ATTEMPTS=$3" "D_NEXT=$4" "D_ERROR=$5" "D_UNTIL=$6" >/dev/null \
    || echo "WARNING: the state of $1 was not recorded for the portal"
}

# The run itself, for the portal's server administrators:  host_run <1|0>
RUN_JS='db.settings.replaceOne({_id: "domains.hostRun"}, {_id: "domains.hostRun",
  value: {at: new Date(), ok: process.env.D_OK === "1"}}, {upsert: true});'
host_run() { portal_js "$RUN_JS" "D_OK=$1" >/dev/null || echo "WARNING: the run was not recorded for the portal"; }

# A name the portal accepted is a lower-case host name; anything else never reaches a file or a command
valid() {
  [[ $1 =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]
}

site_of() { printf '%s/%s%s' "$NGINX_AVAILABLE" "$SITE_PREFIX" "$1"; }
has_site() { [[ -f $(site_of "$1") ]]; }
has_certificate() { has_site "$1" && grep -q "ssl_certificate" "$(site_of "$1")"; }

# The end of a served domain's certificate (seconds since 1970), or 0 when it cannot be read
certificate_until() {
  local file end
  file="$(sed -n 's/^[[:space:]]*ssl_certificate[[:space:]]\{1,\}\([^;]*\);.*/\1/p' "$(site_of "$1")" | head -1)"
  end="$(openssl x509 -enddate -noout -in "$file" 2>/dev/null | sed 's/^notAfter=//')" || true
  if [[ -n $end ]] && date -d "$end" +%s 2>/dev/null; then return 0; fi
  echo 0
}

# Minutes to wait after the n-th failure in a row: 5, 10, 20… at most MAX_WAIT_MINUTES
wait_minutes() {
  local minutes=5 n=$1
  while (( n > 1 && minutes < MAX_WAIT_MINUTES )); do minutes=$((minutes * 2)); n=$((n - 1)); done
  (( minutes > MAX_WAIT_MINUTES )) && minutes=$MAX_WAIT_MINUTES
  echo "$minutes"
}

say() { [[ $QUIET == 1 ]] || echo "$@"; }

# The address of the installation's portal, as the portal itself works it out (portal/app.py: PORTAL_ORIGIN, else
# RESOLVER_PUBLIC_URL, else https://FQDN), in lower case and without a final slash; nothing when it is not a plain
# http(s) origin, so that nothing else reaches nginx's configuration
portal_origin() {
  local origin
  origin="${PORTAL_ORIGIN:-$(setting PORTAL_ORIGIN)}"
  [[ -n $origin ]] || origin="${RESOLVER_PUBLIC_URL:-$(setting RESOLVER_PUBLIC_URL)}"
  if [[ -z $origin ]]; then
    origin="${FQDN:-$(setting FQDN)}"
    [[ -n $origin ]] && origin="https://$origin"
  fi
  origin="${origin,,}"
  origin="${origin%/}"
  if [[ $origin =~ ^https?://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$ ]]; then echo "$origin"; fi
  return 0
}

# The rule every organisation's site includes (ADR 0045): the portal's addresses redirected to the installation's own
# name, the official data entry API refused. The prefixes are those of the installation's proxy
# (frontend_proxy_server/nginx.conf: "= /portal", "/portal/", "/api", "/swaggerui"), so that no path it would hand to
# the portal or the data entry API is passed on from here. Written only when its content changes; prints "changed".
write_rule() {
  local origin portal tmp
  origin="$(portal_origin)"
  if [[ -n $origin ]]; then
    portal="location = /portal { return 302 $origin/portal/; }
location ^~ /portal/ { return 302 $origin\$request_uri; }"
  else
    echo "WARNING: PORTAL_ORIGIN, RESOLVER_PUBLIC_URL or FQDN gives no address for the portal: it is refused on the" \
         "organisations' domains instead of redirected" >&2
    portal="location = /portal { return 404; }
location ^~ /portal/ { return 404; }"
  fi
  mkdir -p "$NGINX_SNIPPETS"
  tmp="$(mktemp "$RULE_FILE.XXXXXX")"
  {
    echo "# Generated by scripts/custom-domains.sh: on an organisation's own domain only the resolver answers"
    echo "# (Documentation/adr/0045-organisation-domains-resolver-only.md). The portal is on the installation's own name;"
    echo "# the official data entry API is not offered on these names at all."
    echo "$portal"
    echo "location ^~ /api { return 404; }"
    echo "location ^~ /swaggerui { return 404; }"
  } > "$tmp"
  chmod 644 "$tmp"
  if cmp -s "$tmp" "$RULE_FILE"; then
    rm -f "$tmp"
    return 0
  fi
  mv -f "$tmp" "$RULE_FILE"
  echo changed
}

# The include of the rule before each "location / {" of a site (the HTTP server the template writes, which Certbot
# turns into the HTTPS one), once. 0 when it was added, 1 when the site already had it, 2 when the site has no
# "location /" to put it before (edited by hand: reported, left alone).
add_rule() {
  local site=$1
  grep -qF "include $RULE_FILE;" "$site" && return 1
  grep -q '^[[:space:]]*location / {' "$site" || return 2
  sed -i "s|^\([[:space:]]*\)\(location / {\)|\1include $RULE_FILE;\n\n\1\2|" "$site"
}

# Sites written before ADR 0045 get the rule: every organisation's site without its include, nginx tested once for all
# of them, each put back as it was when nginx refuses the result. Sets RELOAD; 0 when nothing failed.
migrate_sites() {
  local site name status saved changed=()
  saved="$(mktemp -d)"
  for site in "$NGINX_AVAILABLE/$SITE_PREFIX"*; do
    [[ -f $site ]] || continue
    name="${site##*/$SITE_PREFIX}"
    cp -p "$site" "$saved/$name"
    status=0
    add_rule "$site" || status=$?
    case $status in
      0) changed+=("$name") ;;
      2) echo "WARNING: the site of $name has no 'location /': the portal and the data entry API are not refused" \
              "there (add 'include $RULE_FILE;' to its server blocks by hand)" ;;
    esac
  done
  if (( ${#changed[@]} )); then
    if ! nginx -t >/dev/null 2>&1; then
      for name in "${changed[@]}"; do cp -p "$saved/$name" "$NGINX_AVAILABLE/$SITE_PREFIX$name"; done
      rm -rf "$saved"
      echo "ERROR: nginx rejected the sites with the resolver-only rule; put back as they were: ${changed[*]}"
      return 1
    fi
    for name in "${changed[@]}"; do
      echo "$name: only the resolver answers on this domain now (the portal and the data entry API are off it)"
    done
    RELOAD=1
  fi
  rm -rf "$saved"
  return 0
}

write_site() {
  local domain=$1 site drop_ipv6=()
  site="$(site_of "$domain")"
  [[ -e /proc/net/if_inet6 ]] || drop_ipv6=(-e '/listen \[::\]/d')
  mkdir -p "$NGINX_AVAILABLE" "$NGINX_ENABLED"
  sed -e "s|@FQDN@|$domain|g" -e "s|@DATE@|$(date -Is)|g" -e "s|@PROXY_PORT@|$PROXY_PORT|g" \
      -e "s|scripts/install.sh|scripts/custom-domains.sh|" "${drop_ipv6[@]}" "$TEMPLATE" > "$site"
  add_rule "$site" || true
  chmod 644 "$site"
  ln -sfn "$site" "$NGINX_ENABLED/$SITE_PREFIX$domain"
}

list() {
  local found=0 domain _rest
  while IFS=$'\t' read -r domain _rest; do
    [[ -n $domain ]] || continue
    found=1
    if ! valid "$domain"; then
      echo "$domain: refused (not a host name)"
    elif has_certificate "$domain"; then
      echo "$domain: site and certificate"
    elif has_site "$domain"; then
      echo "$domain: site without a certificate (run apply)"
    else
      echo "$domain: no site yet (run apply)"
    fi
    if has_site "$domain" && ! grep -qF "include $RULE_FILE;" "$(site_of "$domain")"; then
      echo "$domain: the site still serves the portal and the data entry API (run apply)"
    fi
  done < <(domains)
  [[ $found == 1 ]] || echo "No verified domain points at this server."
  local site name
  for site in "$NGINX_AVAILABLE/$SITE_PREFIX"*; do
    [[ -f $site ]] || continue
    name="${site##*/$SITE_PREFIX}"
    domains | cut -f1 | grep -qx "$name" || echo "$name: site of a domain no longer verified ($site; remove it by hand)"
  done
}

# A failure of a domain, recorded with the next attempt:   failure <domain> <attempts so far> <error>
failure() {
  local attempts=$(($2 + 1)) next
  next=$(( $(date +%s) + $(wait_minutes "$attempts") * 60 ))
  record "$1" failed "$attempts" "$next" "$3" 0
  echo "  next attempt at $(date -d "@$next" -Is)"
}

apply() {
  local email domain attempts next state until now end added=0 failed=0
  [[ ${1:-} == --quiet ]] && QUIET=1
  exec 9>"$LOCK_FILE"
  flock -n 9 || { say "Another run is in progress."; return 0; }
  email="${CERTBOT_EMAIL:-$(setting CERTBOT_EMAIL)}"
  [[ -n $email ]] || { echo "ERROR: CERTBOT_EMAIL is not set (environment or .env)"; host_run 0; exit 1; }
  now=$(date +%s)
  # the resolver-only rule first (ADR 0045), and every site written before given it
  RELOAD=0
  [[ $(write_rule) == changed ]] && RELOAD=1
  migrate_sites || failed=1
  if [[ $RELOAD == 1 ]]; then
    if nginx -t >/dev/null 2>&1; then
      systemctl reload nginx
    else
      echo "ERROR: nginx rejected its configuration with the resolver-only rule"
      failed=1
    fi
  fi
  while IFS=$'\t' read -r domain attempts next state until; do
    [[ -n $domain ]] || continue
    attempts=${attempts:-0}; next=${next:-0}; until=${until:-0}
    if ! valid "$domain"; then
      say "$domain: refused (not a host name)"; continue
    fi
    if has_certificate "$domain"; then
      end=$(certificate_until "$domain")
      say "$domain: already served"
      # reported again only when something changed (the state, a renewed certificate)
      [[ $state == served && $end == "$until" ]] || record "$domain" served 0 0 "" "$end"
      continue
    fi
    if (( next > now )); then
      say "$domain: waiting after $attempts failed attempt(s); next at $(date -d "@$next" -Is)"; continue
    fi
    has_site "$domain" || write_site "$domain"
    if ! nginx -t >/dev/null 2>&1; then
      echo "ERROR: nginx rejected the site of $domain; removed"
      rm -f "$(site_of "$domain")" "${NGINX_ENABLED:?}/${SITE_PREFIX:?}${domain:?}"; failed=1
      failure "$domain" "$attempts" nginx; continue
    fi
    systemctl reload nginx
    if certbot --nginx -d "$domain" --non-interactive --agree-tos -m "$email" --redirect --keep-until-expiring; then
      echo "$domain: certificate installed"; added=$((added + 1))
      record "$domain" served 0 0 "" "$(certificate_until "$domain")"
    else
      echo "ERROR: Certbot could not obtain the certificate of $domain (does its DNS point here? is port 80 open?)"
      failed=1
      failure "$domain" "$attempts" certificate
    fi
  done < <(domains)
  host_run "$((1 - failed))"
  if [[ $QUIET == 0 || $added -gt 0 || $failed == 1 ]]; then echo "$(date -Is) $added domain(s) added"; fi
  [[ $failed == 0 ]]
}

case "${1:-}" in
  list) list ;;
  apply) apply "${2:-}" ;;
  *) echo "Usage: $0 list|apply [--quiet]"; exit 2 ;;
esac
