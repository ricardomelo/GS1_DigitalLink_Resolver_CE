# ADR 0039 — The resolver writes only the installation's known names

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-R2 of the [threat model](../threat-model.md); finding F-022 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): the name a request was made on is written only when the installation knows it (`FQDN`, a new setting `FQDN_ALIASES`, an organisation's verified domain), any other gets `FQDN`; the redirects the proxies write themselves no longer carry the `Host` the client sent. Refusing unknown names (421) was not taken |
| Amends | [ADR 0009](0009-tenant-domains.md) §8 (the addresses written on the name requested): the option *a list of the installation's names in `.env`*, not chosen there, is now taken |

## 1. Context

Since ADR 0009 §8 the resolver writes the name a request was made on — the host the installation's proxy passes in
`X-Forwarded-Host` — in the linkset's anchors (plain and JSON-LD), the JSON-LD `@id`, the `Link` header of linksets
and redirects, the `Resolution-Anchor` header (ADR 0022) and the description file's `resolverRoot`, so that GS1's
conformance suite finds an anchor equal to the URI it asked for on every name of the installation. Any syntactically
valid host name was accepted, on the reasoning that the host's nginx decides which names reach the resolver.

It does not: the installer's site (`scripts/templates/nginx-site-*.conf`) is the host's only site and therefore its
default for **any** name, and the installation's proxy listens without a `server_name`. A client can send
`Host: evil.example` and receive anchors, a `Link` header and a description file on `evil.example`. On its own that
only fools the client that forged the header. It becomes harmful behind a shared cache (a CDN or a caching proxy an
operator puts in front) that does not key on the host: the forged answer is kept and served to everyone, and the
description file — which clients read to learn where the resolver is — then names another site. The same reflection
was in two redirects nginx writes itself: `return 301 /portal/` and `/home` (nginx made them absolute with the
client's `Host`, and with `http:` behind a TLS proxy), and the host's site redirected plain HTTP to
`https://$host…`, a permanent redirect that caches keep.

## 2. Decision

### 2.1 Known names only

`domains.public_name()` returns, in this order: an organisation's verified `direct` domain with its stem (unchanged);
the host in `X-Forwarded-Host` when it is one of the installation's own names (`domains.known_names()`); otherwise
nothing, and the caller writes `FQDN`. The installation's names are `FQDN` and those listed in the new setting
**`FQDN_ALIASES`** (separated by commas or spaces; read in lower case, without port or final dot; a value that is not a
valid host name ignored), read from the environment at each call. A domain that is not verified, a redirecting
domain, and any name nobody listed get `FQDN`. The request is still answered: only the name written changes.

### 2.2 Redirects written by the proxies

- The installation's proxy sets `absolute_redirect off`: its own redirects give the path alone (`Location: /portal/`),
  which the browser applies to the name and scheme it used.
- The host's site for an existing certificate redirects plain HTTP to `https://$server_name$request_uri` (the
  installation's name), never to the client's `Host`. Certbot's own redirect (Let's Encrypt mode) already compares
  `$host` with the site's name before redirecting.

### 2.3 Alternatives not taken

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| An unknown name | answered, with `FQDN` written | refused with 421 *Misdirected Request* (breaks development set-ups and any name an operator forgot to list, for no gain once nothing is reflected) |
| Where the names are kept | `.env` (`FQDN_ALIASES`), next to `FQDN` | derived from the host's nginx sites (the containers cannot read them); a portal setting (one more thing a database write could change) |
| The host's nginx | the HTTP redirect to `$server_name` | a default site refusing other names (a certificate for it, or `ssl_reject_handshake`, which Ubuntu 22.04's nginx 1.18 lacks) |
| Caches | nothing written that a forged header chose | `Vary: Host` or `Cache-Control: private` on every answer (relies on every cache honouring it; the description file is meant to be cached) |

## 3. Consequences

- An operator whose installation answers on a second name (its own server block and certificate on the host) must
  list it in `FQDN_ALIASES`; until then the linksets on that name carry `FQDN` and GS1's conformance suite fails there
  (*No default link found*). The release notes say so. Organisations' verified domains need nothing.
- A forged `Host` no longer reaches an answer: anchors, headers, the description file and the proxies' redirects
  carry the installation's names only.
- Residuals: the portal does not use the request's host for addresses (it writes `FQDN` or `RESOLVER_PUBLIC_URL`) and
  is unchanged; the host's nginx still passes every name to the installation (a request on an unknown name is
  answered); the list is a setting to keep in step with the host's sites by hand.

## 4. Delivery

`web_server/src/domains.py` (`known_names()`, `public_name()`), `.env.example` (`FQDN_ALIASES`),
`frontend_proxy_server/nginx.conf` (`absolute_redirect off`), `scripts/templates/nginx-site-https.conf`. Tests:
`test_domains_resolver.py` (names nobody listed, an unverified and a redirecting domain, the list's parsing, every
place a name is written, the host's template), `test_resolver.py` (`Resolution-Anchor`), `test_gs1_suite.py` (the
second name listed), `test_home.py` (the proxy's redirects with a forged `Host`, through a real nginx); 9 mutations, all
caught.
