#!/usr/bin/env bash
# The organisations' own domains on the host (Documentation/adr/0009-tenant-domains.md): the verified domains whose
# mode is "direct" (they point at this server) need an nginx site and a certificate, as the installation's own name.
# This script reads them from the portal's database (mongosh inside the database container: the credentials stay in
# the container) and, for each one without a site, writes one from the installer's template and asks Certbot for its
# certificate. Domains removed in the portal keep their site until it is deleted by hand (printed by "list").
#
#   sudo scripts/custom-domains.sh list     each domain, whether it has a site and a certificate
#   sudo scripts/custom-domains.sh apply    a site and a certificate for each new one (Let's Encrypt; CERTBOT_EMAIL
#                                           from the environment or .env)
#
# Run it after verifying a domain in the portal, or daily from cron. Settings can be overridden from the environment.
set -euo pipefail

RESOLVER_DIR="${RESOLVER_DIR:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
NGINX_AVAILABLE="${NGINX_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_ENABLED="${NGINX_ENABLED:-/etc/nginx/sites-enabled}"
PROXY_PORT="${PROXY_PORT:-8080}"
TEMPLATE="$RESOLVER_DIR/scripts/templates/nginx-site-http.conf"
SITE_PREFIX="gs1resolver-domain-"

cd "$RESOLVER_DIR"

# A value of .env (or .env.example), quotes removed
setting() {
  sed -n "s/^$1=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" .env.example .env 2>/dev/null | tail -1 || true
}

DB="$(setting PORTAL_DB_NAME)"
DB="${DB:-resolver_portal}"

# The verified direct domains, one per line
domains() {
  docker compose exec -T -e PORTAL_DB="$DB" database-service sh -c \
    'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet "$PORTAL_DB" --eval "
      db.domains.find({verified: true, mode: \"direct\"}, {_id: 1}).sort({_id: 1}).forEach(d => print(d._id));"'
}

# A name the portal accepted is a lower-case host name; anything else never reaches a file or a command
valid() {
  [[ $1 =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]
}

site_of() { printf '%s/%s%s' "$NGINX_AVAILABLE" "$SITE_PREFIX" "$1"; }
has_site() { [[ -f $(site_of "$1") ]]; }
has_certificate() { has_site "$1" && grep -q "ssl_certificate" "$(site_of "$1")"; }

write_site() {
  local domain=$1 site drop_ipv6=()
  site="$(site_of "$domain")"
  [[ -e /proc/net/if_inet6 ]] || drop_ipv6=(-e '/listen \[::\]/d')
  mkdir -p "$NGINX_AVAILABLE" "$NGINX_ENABLED"
  sed -e "s|@FQDN@|$domain|g" -e "s|@DATE@|$(date -Is)|g" -e "s|@PROXY_PORT@|$PROXY_PORT|g" \
      -e "s|scripts/install.sh|scripts/custom-domains.sh|" "${drop_ipv6[@]}" "$TEMPLATE" > "$site"
  chmod 644 "$site"
  ln -sfn "$site" "$NGINX_ENABLED/$SITE_PREFIX$domain"
}

list() {
  local found=0 domain
  while IFS= read -r domain; do
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
  done < <(domains)
  [[ $found == 1 ]] || echo "No verified domain points at this server."
  local site name
  for site in "$NGINX_AVAILABLE/$SITE_PREFIX"*; do
    [[ -f $site ]] || continue
    name="${site##*/$SITE_PREFIX}"
    domains | grep -qx "$name" || echo "$name: site of a domain no longer verified ($site; remove it by hand)"
  done
}

apply() {
  local email domain added=0 failed=0
  email="${CERTBOT_EMAIL:-$(setting CERTBOT_EMAIL)}"
  [[ -n $email ]] || { echo "ERROR: CERTBOT_EMAIL is not set (environment or .env)"; exit 1; }
  while IFS= read -r domain; do
    [[ -n $domain ]] || continue
    if ! valid "$domain"; then
      echo "$domain: refused (not a host name)"; continue
    fi
    has_certificate "$domain" && { echo "$domain: already served"; continue; }
    has_site "$domain" || write_site "$domain"
    if ! nginx -t >/dev/null 2>&1; then
      echo "ERROR: nginx rejected the site of $domain; removed"
      rm -f "$(site_of "$domain")" "$NGINX_ENABLED/$SITE_PREFIX$domain"; failed=1; continue
    fi
    systemctl reload nginx
    if certbot --nginx -d "$domain" --non-interactive --agree-tos -m "$email" --redirect --keep-until-expiring; then
      echo "$domain: certificate installed"; added=$((added + 1))
    else
      echo "ERROR: Certbot could not obtain the certificate of $domain (does its DNS point here? is port 80 open?)"
      failed=1
    fi
  done < <(domains)
  echo "$(date -Is) $added domain(s) added"
  [[ $failed == 0 ]]
}

case "${1:-}" in
  list) list ;;
  apply) apply ;;
  *) echo "Usage: $0 list|apply"; exit 2 ;;
esac
