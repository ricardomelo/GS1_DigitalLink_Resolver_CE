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
# An entry that is not an address or a network is left out with a warning (it opens nothing); the proxy still
# starts, so a typing error never takes the resolver down. For the tests: API_ACCESS_FILE and REAL_IP_FILE (the files
# written) and API_ACCESS_ROUTES (the kernel's routing table, read for the gateway).
set -eu

OUT="${API_ACCESS_FILE:-/etc/nginx/api-access.conf}"
REAL_IP="${REAL_IP_FILE:-/etc/nginx/real-ip.conf}"
ROUTES="${API_ACCESS_ROUTES:-/proc/net/route}"

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
