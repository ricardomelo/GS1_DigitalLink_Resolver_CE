# ADR 0057 — The portal on a host name of its own

| | |
|---|---|
| Status | **Accepted** (27 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-B1 and gap G-16 of the [threat model](../threat-model.md); the first residual of finding F-021 ([ADR 0038](0038-browser-hardening.md) §3.1) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — the portal on a name of its own **when the operator chooses one**, by the setting that already names the portal's address (`PORTAL_ORIGIN`); the installation's proxy then serves the portal only on that name and nothing else there, and sends the portal's addresses on every other name to it, except the tenant API and the public files the home page reads; the installer adds the name to the host's site and to the certificate. Not taken: a second name required of every installation (a new name, a DNS record and a certificate at the next update, every bookmark and single sign-on callback changed, for operators who never asked); a name made up by the installer (`portal.<FQDN>`: a DNS record the operator may not control); the tenant API moved with the portal (every organisation's integration would break at the update, for a route that reads no cookie) |
| Amends | [ADR 0038](0038-browser-hardening.md) §2.5 (*One origin, kept*: now the default, no longer the only way); closes its residual 1 for installations that set the name |

## 1. Context

The portal, the resolver's pages, the home page and the official data entry API's Swagger UI answer on one name, the
installation's (`FQDN`), so they share one origin. ADR 0038 gave every answer a Content-Security-Policy and kept the
single origin, recording the cost as its first residual: a script flaw in any page of that name would run with the
portal's origin, reach the portal's API with the user's cookie (path `/portal`, `SameSite=Lax`) and read its answers;
and the Swagger UI, open to the addresses the operator lists (ADR 0021), allows inline script.

The portal already has a setting for its own address: `PORTAL_ORIGIN` (default `RESOLVER_PUBLIC_URL`, else
`https://FQDN`). The portal uses it for the `Origin` check of every write, the single sign-on callback, the addresses in
its e-mail messages, the tenant API's description and whether its cookie is `Secure`; the organisations' domains send
the portal's addresses to it (ADR 0045). But the installation's proxy served `/portal/` on every name it received, so
an operator who set `PORTAL_ORIGIN` to another name still had the portal on the resolver's name too, and its writes
refused there by the `Origin` check.

## 2. Decision

### 2.1 When

The portal is on a name of its own when `PORTAL_ORIGIN` is an `http(s)` origin whose host is not the resolver's (the
host of `RESOLVER_PUBLIC_URL`, else `FQDN`). Otherwise — `PORTAL_ORIGIN` empty, the same host, or a value that is not a
plain origin (a warning) — nothing changes: one origin, as before. No new setting.

### 2.2 The installation's proxy

`frontend_proxy_server/api-access.sh` reads `PORTAL_ORIGIN`, `RESOLVER_PUBLIC_URL` and `FQDN` when the container starts
(`docker-compose.yml` passes them) and writes `/etc/nginx/portal-host.conf`, a `map` of the request's host and path to
an address; `nginx.conf` answers 302 to that address before any location when it is not empty. The file baked into the
image maps nothing (one origin).

| Request | Answer |
|---|---|
| the portal's name, `/portal` and below | the portal, as before |
| the portal's name, any other path (`/`, a GS1 Digital Link, `/.well-known/…`, `/api`, `/swaggerui`, `/home/…`) | 302 to the resolver's address, same path and query: nothing but the portal on the portal's origin |
| any other name, `/portal/api/v1` and below (the tenant API) | the portal, as before: it reads an API key from the `Authorization` header and never a cookie, so a page of the resolver's origin gains nothing from it; the organisations' integrations keep working |
| any other name, the public files the home page reads: `/portal/api/appearance`, `/portal/appearance.css`, `/portal/appearance/logo`, `/portal/appearance/icon`, `/portal/logo.svg`, `/portal/favicon.png` | the portal, as before: the same for every visitor, no cookie read, and a browser would refuse them after a redirect to another origin |
| any other name, every other path of the portal (pages, sign-in, single sign-on, the portal's API, its files) | 302 to the portal's address, same path and query |

The comparison is on nginx's `$host` (lower case, without the port) and `$uri` (the path as nginx routes it, decoded
and normalised), so a path written another way (`/%70ortal/`) is sent where the location would have sent it.

### 2.3 The installer

`scripts/install.sh` asks nothing new. When `PORTAL_ORIGIN` (from the environment or the existing `.env`) is
`https://<name>` with a name other than `FQDN`, it writes it to `.env`, adds the name to the host's site
(`server_name FQDN <name>`, both templates) and asks Certbot for one certificate covering both (`-d FQDN -d <name>
--expand`); with a certificate of its own the operator's must cover both. The final checks and the summary use the
portal's address; with TLS handled elsewhere the summary says that both names must be forwarded. Any other value of
`PORTAL_ORIGIN` stops the installer with the reason.

### 2.4 What the portal does not change

The portal's code reads `PORTAL_ORIGIN` as before. Its cookie names no domain, so the browser sends it to the portal's
name only. A session cookie set on the resolver's name before the change stays in the browser until it expires, and is
never read again there (every page and API path of the portal is redirected on that name).

## 3. Consequences

- **Operators who change nothing**: nothing changes.
- **Operators who choose a name**: a DNS record and the certificate for it (the installer asks Certbot), then
  `PORTAL_ORIGIN=https://<name>` in `.env` and `docker compose up -d` (or the installer again). The single sign-on
  callbacks registered with the providers become `https://<name>/portal/sso/callback`; bookmarks of the old addresses
  are redirected; users sign in once more on the new name.
- A script on the resolver's pages, the home page or the Swagger UI can no longer read the portal's pages or call its
  API with the user's cookie: another origin, refused by the browser.
- The language chosen on one name is not carried to the other (the choice lives in the browser's storage and a cookie
  of each name).
- The portal's own links to `/` (the brand in the header, *Home* in the menu) lead to the resolver's home page through
  the redirect.

## 4. Residuals

- **Opt-in**: an installation without a name of its own keeps one origin, as ADR 0038 §2.5 described.
- **Same site**: when the portal's name is under the same registrable domain as the resolver's (`portal.example.org`
  and `id.example.org`), the browser still sends the portal's cookie with requests that a page of the resolver's origin
  starts (`SameSite` is about sites, not origins); the portal's `Origin` check refuses those writes and the browser
  refuses to let the page read the answers.
- **The host's nginx** passes every name to the installation, which redirects the ones it does not serve (ADR 0039).

## 5. Delivery

`frontend_proxy_server/api-access.sh` (`PORTAL_ORIGIN`, `RESOLVER_PUBLIC_URL`, `FQDN`; `portal-host.conf`;
`PORTAL_HOST_FILE` for the tests); `frontend_proxy_server/nginx.conf` (the include and the redirect);
`frontend_proxy_server/Dockerfile` (the empty map baked in); `docker-compose.yml` (the three settings to the proxy);
`scripts/install.sh` (`portal_host()`, `PORTAL_ORIGIN` managed, the site's names, Certbot, checks and summary);
`.env.example`. Tests: `test_home.py` (the real nginx: each row of §2.2 on both names, a path written another way, the
query kept, an invalid value and the same host keeping one origin, the file the script writes); `test_install.sh` (a
scenario with the portal's name: `.env`, the site, Certbot, the checks and the summary; an invalid value refused).
