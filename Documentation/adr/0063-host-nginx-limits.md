# ADR 0063 — Limits of the host's nginx

| | |
|---|---|
| Status | **Accepted** (28 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-R3 of the [threat model](../threat-model.md); the fourth residual of finding F-013 ([ADR 0031](0031-request-limits.md)) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — one file of the installer in the host nginx's `conf.d`, limiting per client address the connections and requests of every site it serves and the time a slow client may take, with two settings. Not taken: the limits inside the installer's site template (the same template writes each organisation's domain site, where a zone defined twice stops nginx, and Certbot rewrites the site; a site kept from an earlier run would stay without them); limits as fine as the installation's proxy's (they are the proxy's job, per path, with exempt addresses) |
| Amends | [ADR 0031](0031-request-limits.md) (its residual *the host's nginx has no limit of its own*) |

## 1. Context

Since ADR 0031 the installation's proxy limits each client address per kind of path and answers 429 before any
service is reached. In front of it, the host's nginx ends TLS for the installation's name and the organisations'
domains (modes `letsencrypt` and `certificate`; not `external`) and had no limit of its own: one address could hold as
many connections, TLS handshakes and slow requests open on the host as it liked, all of them relayed to the proxy.

## 2. Decision

1. **One file for every site.** `scripts/install.sh` (`write_nginx_limits()`) writes
   `/etc/nginx/conf.d/gs1resolver-limits.conf` from `scripts/templates/nginx-limits.conf`; Debian's and Ubuntu's
   `nginx.conf` include `conf.d` in their `http` block, so the limits apply to the installation's site, the
   organisations' domain sites (`custom-domains.sh`) and a site kept from an earlier run alike. The installer writes it
   on every run, also when it keeps a site with its certificate, and then tests and reloads nginx when it changed.
2. **What it limits, per client address** (`$binary_remote_addr`; the host's nginx receives the clients directly):
   connections at once (`limit_conn`, `HOST_NGINX_LIMIT_CONNECTIONS`, 200) and requests a second
   (`limit_req`, `HOST_NGINX_LIMIT_RATE`, 200, a burst of twice as many, `nodelay`), both answered **429**; and the
   time a slow client may take: 10 s for the request's headers, 15 s between two reads of its body, 30 s between two
   writes of the answer. 0 leaves a limit out; a value that is not a whole number from 0 to 100,000 gives the default
   with a warning. `keepalive_timeout` is left to the distribution's `nginx.conf`, which already sets it (a second one
   would stop nginx).
3. **Above the proxy's limits.** The defaults are twice the proxy's per-address connections and above the sum of its
   request rates: the host's limits are a backstop for the host itself, not a second policy.

## 3. Consequences

- One address can no longer hold more than 200 connections on the host, nor send more than 200 requests a second
  (bursts of 400), nor keep a connection with a request trickled in byte by byte.
- The limits apply to every site of the host's nginx: on a host shared with other sites, those are limited too. An
  address exempted at the proxy (`PROXY_LIMIT_EXEMPT`: a monitoring service, an integrator resolving in bulk) is not
  exempt here: raise `HOST_NGINX_LIMIT_RATE`, or set it to 0, and run the installer again.
- Behind an external load balancer (`TLS_MODE=external`) there is no host nginx and nothing changes.

## 4. Checks

`test_install` (the file with its defaults, written before `nginx -t`; beside a kept site, then tested and reloaded;
the two settings from the environment and from `.env`, 0 and a malformed value) and `test_deploy` (through a real
nginx: accepted with the installer's site in an `http` block that sets `keepalive_timeout`; one address over the rate
answered 429). 5 mutations, all caught.
