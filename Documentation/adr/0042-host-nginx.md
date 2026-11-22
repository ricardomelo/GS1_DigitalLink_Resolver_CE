# ADR 0042 — The host's nginx kept up to date, over HTTP/1.1

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-I7 of the [threat model](../threat-model.md) |
| Decided by | the owner's request to assess nginx's security release of 18 November 2026 and correct what it touches: the installer updates the host's nginx on every run and checks its version, and the HTTPS site it writes no longer serves HTTP/2. Leaving the package to the operator, and keeping HTTP/2 once the package is fixed, were not taken |

## 1. Context

On 18 November 2026 F5 published ten flaws of nginx, fixed in nginx 1.30.7 (stable) and 1.31.9 (mainline). The most
serious, CVE-2026-123007 (memory corruption in HTTP/2 flow control, CVSS 4.0 9.2, public proof of concept, code
execution shown on 64-bit systems), and CVE-2026-123633 (a use-after-free on HTTP/2 connections passed to a backend)
need HTTP/2; CVE-2026-118899 (an endless loop reading a request body over TLS 1.3) needs TLS 1.3; the others need
HTTP/3, the mail proxy, `stream`, PROXY protocol v2, `alias` with `try_files` in one location, or a resolver lookup
from an SSI or mirror subrequest. Ubuntu published fixed packages: 1.24.0-2ubuntu7.20 for 24.04 and
1.18.0-6ubuntu14.24 for 22.04.

An installation runs two nginx:

- **The front-end proxy** (`frontend_proxy_server`, the official image by digest, ADR 0033). Its digest of
  21 November is the image of `nginx:1.30.7-alpine`, and its configuration has none of the preconditions (HTTP/1.1 on
  port 80 inside Docker, no TLS, `alias` and `try_files` in different locations, `resolve` without subrequests).
- **The host's nginx** (Ubuntu's package, installed by `scripts/install.sh`), which faces the Internet and ends TLS.
  The installer installed it only when missing, so an nginx already on the server — by hand or by an earlier run —
  kept its version until the operator updated it; and the site it writes for an existing certificate
  (`templates/nginx-site-https.conf`) served HTTP/2. Sites made by Certbot do not.

## 2. Decision

1. **Installed or brought up to date.** `install_prerequisites()` runs `apt-get update` and `apt-get install -y nginx`
   (with Certbot and its plugin for Let's Encrypt) on every run, so a re-run of the installer also updates them.
2. **The version checked.** `check_host_nginx()` compares the package's version with the first one carrying the
   fixes — Ubuntu's own builds per release (`HOST_NGINX_FIXED`: `jammy`, `noble`), nginx.org's by branch (1.30.7 for an
   even minor version, 1.31.9 for an odd one) — and warns, with the command that updates it, when it is older; a
   release not in the table is reported as not checked. The table names the November 2026 fixes; a later advisory
   updates it.
3. **HTTP/1.1 only.** The HTTPS site listens with `listen 443 ssl;`. A scan asks for one redirect: HTTP/2's
   multiplexing brings it nothing, and HTTP/2 is where nginx's most serious flaws of recent years lie (2023's rapid
   reset, these). When the installer keeps a Let's Encrypt site that serves HTTP/2 (an operator's change), it warns
   and prints the `sed` command that removes it.
4. The development tests and the CI build or install nginx 1.30.7, the version the proxy image runs.

## 3. Consequences

- A re-run of the installer, or `sudo apt-get update && sudo apt-get install --only-upgrade nginx`, fixes the host;
  Ubuntu's unattended upgrades, on by default, install the security pocket's packages by themselves.
- Browsers and apps reach the resolver over HTTP/1.1 with keep-alive; nothing else changes.
- Residuals: sites written before this change for an existing certificate keep `http2` until the installer runs
  again (it rewrites them) or the operator removes it; the version table needs updating with each advisory; the
  organisations' domain sites (`custom-domains.sh`, through Certbot) are HTTP/1.1 already; TLS 1.3 stays on (its flaw
  is fixed by the package, and turning it off would weaken every connection).
