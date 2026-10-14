# ADR 0009 — The tenant's own domain in the QR code

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog item | 5.1 — the tenant's own domain in the QR code |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

Every QR code the portal makes carries the installation's address (`https://FQDN/01/…`). GS1 Digital Link URI Syntax
1.7, section 4.11, lets a brand owner use **its own domain**, optionally with a **path stem** in front of the GS1 path
(`https://id.acme.example/gs1/01/…`): the code then names the brand, and the brand can move to another resolver
without reprinting. The backlog asks for domains registered per organisation and **proved by a DNS record**; a
**default per prefix**, chosen again when the label is made (the installation's domain when none is set); two ways to
serve them — the domain **points at the resolver** (a certificate issued per domain) or **the organisation's server
redirects** to the resolver keeping path and query string; a domain answers **only for its organisation's prefixes**;
an optional path stem.

Constraints:

- Ownership comes from GS1 Company Prefixes (ADR 0002): a domain belongs to an organisation (or to the operator) and
  must never resolve another organisation's codes.
- The resolver is the official component and stays unchanged for the installation's own address.
- TLS for the public names is terminated by nginx on the host (the installer's site, Certbot); containers never hold
  certificates.
- A domain is outside the installation's control: proving it must not need the organisation's DNS credentials.

## 2. Decision

1. **Domains are a record of the portal** (collection `domains`): the name (lower case, ASCII/Punycode), the
   organisation (none: the operator), the **mode** (`direct` — the name points at this server — or `redirect` — the
   organisation's own server redirects to the installation), an optional **path stem** (one to three segments of
   letters, digits, `-`, `.`, `_`, `~`; a segment of 2 to 4 digits is refused because it would read as an AI), the
   prefixes it is the **default** for, a **verification token**, whether it is **verified**, and the last check.
   Organisation administrators manage their organisation's domains; server administrators the operator's, and see
   every domain (support access: the organisation's, read only). At most 10 per organisation.
2. **Proof by DNS**: a TXT record `_gs1resolver.<domain>` containing `gs1resolver-verify=<token>`. *Verify* looks it
   up (dnspython); a verified domain stays verified (a DNS hiccup must not break printed codes); the daily housekeeping
   looks again and the screen shows when the record was last seen.
3. **Which domain a label carries**: the label's *Domain* option — *Default*, the installation's name, or one of the
   scope's verified domains. *Default* is the verified domain whose default prefixes cover the record's company part
   (the longest prefix wins), else the installation's. The same rule gives the `digitalLink` of the record, the tenant
   API's labels (`domain=`) and records.
4. **The resolver answers for registered domains** (`direct`): the proxy passes the public host
   (`X-Forwarded-Host`); the resolver reads the verified domains from the portal's database (a cache of 60 seconds),
   **removes the stem** from the path and **refuses keys outside the domain's organisation's prefixes** (404, as a code
   nobody registered). A host that is not a registered domain is served as before.
5. **Certificates on the host**: `scripts/custom-domains.sh` lists the verified `direct` domains and, for each one
   without a site, writes an nginx site from the installer's template and asks Certbot for its certificate (`apply`);
   run by hand or from cron by the server administrator.
6. **`redirect` mode**: the organisation's server answers `https://<domain><stem>/<path>?<query>` with a redirect
   (301, 302, 307 or 308) to `https://FQDN/<path>?<query>`. The user guide gives the rule for nginx and Apache. *Check*
   in the portal requests a code of the organisation through the domain without following redirects and compares the
   `Location`.
7. **Check** (both modes) requests through the domain (the link checker's guard against private addresses applies):
   `direct` expects the installation's description file at `/.well-known/gs1resolver`; `redirect` the redirect above.

## 3. Design

### 3.1 A domain (`portal/domains.py`)

```
{_id: "id.acme.example", tenant: "t-…" | absent, mode: "direct" | "redirect", stem: "" | "/gs1",
 defaultFor: ["7891234"], token, verified: bool, verifiedAt, seenAt, check: {at, ok, problem, detail},
 created, createdBy}
```

### 3.2 Calls (portal, administrators)

| Call | Answer |
|---|---|
| `GET /portal/api/domains` | the scope's domains (a server administrator outside support access: every domain, with its organisation), the TXT record to add, the installation's name |
| `POST /portal/api/domains` `{domain, mode, stem}` | created, not verified (`domains.*` codes) |
| `PUT /portal/api/domains/<domain>` `{mode, stem, defaultFor}` | changed |
| `POST /portal/api/domains/<domain>/verify` | looks up the TXT record |
| `POST /portal/api/domains/<domain>/check` | requests through the domain |
| `DELETE /portal/api/domains/<domain>` | removed |

`GET /portal/api/config` gains `domains`: the scope's verified domains with their stems and default prefixes, and the
installation's name; `GET /qrcode`, `POST /digital-link`, the tenant API's labels take `domain=` (`default`,
`installation` or a verified domain of the scope; another answers 422 `domains.unusable`).

### 3.3 The resolver (`web_server/src/domains.py`)

A WSGI middleware in front of the application: the host (`X-Forwarded-Host`, else `Host`) without port; a verified
`direct` domain removes its stem from `PATH_INFO` and `RAW_URI`/`REQUEST_URI` and records the domain's prefixes (and,
for the operator, every organisation's prefixes, which it must not answer) in the WSGI environment; `_process_response`
answers 404 for a key outside them.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Proof | a DNS TXT record with a token | an HTTP file on the domain (needs the domain served first); none (any organisation could claim any name) |
| Losing the TXT record | the domain stays verified, the screen shows when it was last seen | un-verified at once (a DNS hiccup breaks printed codes) |
| Where the stem is removed | in the resolver, per verified domain | the container's nginx (a configuration per domain, reloads) |
| Domains of other organisations' keys | 404 | served (a domain would vouch for another brand's products) |
| Certificates | a host script using the installer's template and Certbot | in the containers (the installation terminates TLS on the host); a wildcard (impossible for other organisations' names) |
| Default | per prefix, the longest prefix wins | per organisation (one brand per prefix is common in groups) |

## 5. Consequences

- The proxy passes `X-Forwarded-Host` to the resolver; the resolver reads `resolver_portal.domains` and
  `resolver_portal.tenants` with its root connection.
- A `direct` domain answers only once its DNS points at the server, its certificate exists (`custom-domains.sh
  apply`) and it is verified.
- Labels printed with a domain depend on that domain staying with the resolver; the guide says so.

## 6. Delivery

This record; `portal/domains.py`, the endpoints and the *Domains* view, the label's option, the tenant API's
`domain=`; `web_server/src/domains.py`; the proxy's header; `scripts/custom-domains.sh` and its template; tests
`test_domains.py` (portal), `test_domains_resolver.py`, `test_domains_e2e.py`, the host script in `test_deploy.py`;
the documentation.
