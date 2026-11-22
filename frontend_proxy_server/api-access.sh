#!/bin/sh
# Who may reach the official data entry API through the proxy (/api and /swaggerui;
# Documentation/adr/0021-data-entry-api-closed.md) and which proxies in front name the client. The nginx image runs
# this script from /docker-entrypoint.d before nginx starts; it writes the body of the "geo $data_entry_api_allowed"
# block of nginx.conf (/etc/nginx/api-access.conf) and the trusted proxies of its real_ip settings
# (/etc/nginx/real-ip.conf: the client's address for the allowed list, the portal's sign-in throttle and its audit
# trail, and the resolver's location lookup):
#
#   DATA_ENTRY_API_ALLOW    addresses or networks (CIDR) that may use /api and /swaggerui, separated by spaces or
#                           commas; "all" opens both to everyone. Empty (the default): closed to every address, and
#                           the portal, which calls the service inside Docker's network, is not affected.
#   PROXY_TRUSTED_PROXIES   addresses or networks of proxies in front of this one whose X-Forwarded-For names the
#                           client (an external load balancer); a chain of them is walked from its end. The host's nginx is trusted without being listed when
#                           PROXY_BIND_ADDRESS is a loopback address: only processes on the server reach the port then,
#                           and they arrive from the address of the container's gateway.
#   PROXY_BIND_ADDRESS      the address Docker publishes the proxy on (docker-compose.yml).
#
# and the request limits per client address (Documentation/adr/0031-request-limits.md): limits-http.conf (the zones),
# limit-exempt.conf, and limit-server.conf, limit-resolve.conf, limit-portal.conf, limit-signin.conf (what nginx.conf
# includes where each applies):
#
#   PROXY_LIMIT_RESOLVE     requests a second to resolution and the home page (default 50; bursts of twice as many)
#   PROXY_LIMIT_PORTAL      requests a second to the portal: pages, its API and the tenant API (default 30; bursts of
#                           three times as many)
#   PROXY_LIMIT_SIGNIN      requests a minute to sign-in, password recovery and single sign-on (default 60; bursts of
#                           half as many)
#   PROXY_LIMIT_CONNECTIONS connections at once, whatever the path (default 100)
#   PROXY_LIMIT_EXEMPT      addresses or networks (CIDR) counted by none of these: the operator's monitoring, an
#                           integrator's servers that resolve in bulk
#
# and what the access log keeps (Documentation/adr/0043-access-logs.md), access-log.conf:
#
#   PROXY_ACCESS_LOG        minimal (the default: no client address, no query string, the path's first segment only),
#                           full (the address and the whole request line: personal data) or off
#
# 0 turns a limit off; a value that is not a whole number keeps the default, with a warning.
#
# An entry that is not an address or a network is left out with a warning (it opens nothing); the proxy still
# starts, so a typing error never takes the resolver down. For the tests: API_ACCESS_FILE and REAL_IP_FILE (the files
# written), LIMITS_DIR (the folder of the limits' files) and API_ACCESS_ROUTES (the kernel's routing table, read for
# the gateway), ACCESS_LOG_FILE (the access log's file).
set -eu

OUT="${API_ACCESS_FILE:-/etc/nginx/api-access.conf}"
REAL_IP="${REAL_IP_FILE:-/etc/nginx/real-ip.conf}"
ROUTES="${API_ACCESS_ROUTES:-/proc/net/route}"
LIMITS="${LIMITS_DIR:-/etc/nginx}"
ACCESS_LOG="${ACCESS_LOG_FILE:-/etc/nginx/access-log.conf}"

say() { echo "api-access: $*" >&2; }

# An IPv4 or IPv6 address, with an optional prefix length, in a form nginx accepts (a value nginx refused would
# stop it from starting)
is_address() {
  addr=${1%/*}; len=none
  case $1 in */*) len=${1#*/} ;; esac
  if printf '%s\n' "$addr" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
    printf '%s\n' "$addr" | awk -F. '{ for (i = 1; i <= 4; i++) if ($i > 255) exit 1 }' || return 1
    max=32
  elif printf '%s\n' "$addr" | grep -Eq '^[0-9A-Fa-f:]+$'; then
    groups=$(printf '%s\n' "$addr" | awk -F: '{ print NF }')
    case $addr in
      *::*::*|*:::*) return 1 ;;
      *::*) [ "$groups" -le 8 ] || return 1 ;;
      *) [ "$groups" -eq 8 ] || return 1 ;;
    esac
    printf '%s\n' "$addr" | awk -F: '{ for (i = 1; i <= NF; i++) if (length($i) > 4) exit 1 }' || return 1
    case $addr in :[!:]*|*[!:]:) return 1 ;; esac
    max=128
  else
    return 1
  fi
  [ "$len" = none ] && return 0
  printf '%s\n' "$len" | grep -Eq '^[0-9]{1,3}$' && [ "$len" -le "$max" ]
}

# The default gateway of the container (the Docker bridge's address on the host), from the routing table
gateway() {
  [ -r "$ROUTES" ] || return 0
  hex=$(awk '$2 == "00000000" && $3 != "00000000" { print $3; exit }' "$ROUTES")
  [ -n "$hex" ] || return 0
  # the table holds the address in hexadecimal, least significant byte first
  printf '%d.%d.%d.%d\n' "0x$(echo "$hex" | cut -c7-8)" "0x$(echo "$hex" | cut -c5-6)" \
    "0x$(echo "$hex" | cut -c3-4)" "0x$(echo "$hex" | cut -c1-2)"
}

entries() { printf '%s\n' "$1" | tr ',' ' '; }

tmp="$REAL_IP.tmp.$$"
{
  echo "# Written by api-access.sh when the proxy starts; changes here are lost. See nginx.conf."
  case "${PROXY_BIND_ADDRESS:-}" in
    127.*|::1|localhost)
      gw=$(gateway)
      [ -n "$gw" ] && echo "set_real_ip_from $gw;   # the host's own proxy (PROXY_BIND_ADDRESS is a loopback address)" ;;
  esac
  for entry in $(entries "${PROXY_TRUSTED_PROXIES:-}"); do
    if is_address "$entry"; then echo "set_real_ip_from $entry;"; else say "PROXY_TRUSTED_PROXIES: '$entry' left out (not an address)"; fi
  done
} > "$tmp"
mv "$tmp" "$REAL_IP"

tmp="$OUT.tmp.$$"
{
  echo "# Written by api-access.sh when the proxy starts; changes here are lost. See nginx.conf."
  for entry in $(entries "${DATA_ENTRY_API_ALLOW:-}"); do
    if [ "$entry" = all ]; then
      echo "0.0.0.0/0 1;"; echo "::/0 1;"
    elif is_address "$entry"; then
      echo "$entry 1;"
    else
      say "DATA_ENTRY_API_ALLOW: '$entry' left out (not an address, a network or \"all\")"
    fi
  done
} > "$tmp"
mv "$tmp" "$OUT"

if grep -q ' 1;$' "$OUT"; then
  say "/api and /swaggerui open to: $(grep ' 1;$' "$OUT" | sed 's/ 1;$//' | tr '\n' ' ')"
else
  say "/api and /swaggerui closed to every address (DATA_ENTRY_API_ALLOW is empty)"
fi

# ---- Request limits per client address (ADR 0031) ----
# A whole number of 0 or more, else the default with a warning
number() {
  value=$(printf '%s' "$2" | tr -d ' ')
  if [ -z "$value" ]; then echo "$3"
  elif printf '%s\n' "$value" | grep -Eq '^[0-9]{1,6}$'; then echo "$value" | sed 's/^0*\([0-9]\)/\1/'
  else say "$1: '$2' is not a whole number; $3 kept"; echo "$3"
  fi
}

resolve=$(number PROXY_LIMIT_RESOLVE "${PROXY_LIMIT_RESOLVE:-}" 50)
portal=$(number PROXY_LIMIT_PORTAL "${PROXY_LIMIT_PORTAL:-}" 30)
signin=$(number PROXY_LIMIT_SIGNIN "${PROXY_LIMIT_SIGNIN:-}" 60)
connections=$(number PROXY_LIMIT_CONNECTIONS "${PROXY_LIMIT_CONNECTIONS:-}" 100)

# write <file> <text>: through a temporary file, so nginx never reads half a file
write() { printf '%s\n' "# Written by api-access.sh when the proxy starts; changes here are lost. See nginx.conf." "$2" > "$1.tmp.$$"; mv "$1.tmp.$$" "$1"; }

# the zones exist whatever the settings (a rate of 0 would be refused by nginx: 1 stands for "not used")
zone_rate() { if [ "$1" -gt 0 ]; then echo "$1"; else echo 1; fi; }
write "$LIMITS/limits-http.conf" "limit_req_zone \$limit_key zone=limit_resolve:10m rate=$(zone_rate "$resolve")r/s;
limit_req_zone \$limit_key zone=limit_portal:10m rate=$(zone_rate "$portal")r/s;
limit_req_zone \$limit_key zone=limit_signin:10m rate=$(zone_rate "$signin")r/m;
limit_conn_zone \$limit_key zone=limit_conn:10m;"

burst() { b=$(( $1 * $2 / $3 )); [ "$b" -ge 1 ] || b=1; echo "$b"; }
rule() { [ "$2" -gt 0 ] && echo "limit_req zone=limit_$1 burst=$3 nodelay;" || true; }
write "$LIMITS/limit-resolve.conf" "$(rule resolve "$resolve" "$(burst "$resolve" 2 1)")"
write "$LIMITS/limit-portal.conf" "$(rule portal "$portal" "$(burst "$portal" 3 1)")"
write "$LIMITS/limit-signin.conf" "$(rule signin "$signin" "$(burst "$signin" 1 2)")"
write "$LIMITS/limit-server.conf" "$([ "$connections" -gt 0 ] && echo "limit_conn limit_conn $connections;" || true)"

exempt=""
for entry in $(entries "${PROXY_LIMIT_EXEMPT:-}"); do
  if is_address "$entry"; then exempt="$exempt$entry 1;
"; else say "PROXY_LIMIT_EXEMPT: '$entry' left out (not an address or a network)"; fi
done
write "$LIMITS/limit-exempt.conf" "$exempt"

shown() { if [ "$1" -gt 0 ]; then echo "$1$2"; else echo "off"; fi; }
say "request limits per address: resolution $(shown "$resolve" /s), portal $(shown "$portal" /s), sign-in $(shown "$signin" /min), connections $(shown "$connections" '')$( [ -n "$exempt" ] && printf '; exempt: %s' "$(printf '%s' "$exempt" | sed 's/ 1;$//' | tr '\n' ' ' | sed 's/ $//')" )"

# ---- The access log (ADR 0043) ----
mode=$(printf '%s' "${PROXY_ACCESS_LOG:-}" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
case $mode in
  ""|minimal) mode=minimal ;;
  full|off) ;;
  *) say "PROXY_ACCESS_LOG: '${PROXY_ACCESS_LOG}' is not minimal, full or off; minimal kept"; mode=minimal ;;
esac
minimal=0; full=0; level=info
case $mode in minimal) minimal=1 ;; full) full=1; level=warn ;; esac
write "$ACCESS_LOG" "map \$host \$access_log_minimal { default $minimal; }
map \$host \$access_log_full { default $full; }
limit_req_log_level $level;
limit_conn_log_level $level;"
case $mode in
  minimal) say "access log: minimal (no client address, no query string)" ;;
  full) say "access log: full (client addresses and whole request lines: personal data; see the privacy notice)" ;;
  off) say "access log: off" ;;
esac
