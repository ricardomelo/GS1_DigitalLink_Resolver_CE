# ADR 0045 — Only the resolver on an organisation's own domain

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); gap G-20 and threat T-T6 of the [threat model](../threat-model.md); finding F-027 |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken. Not taken: a list of the names that may reach the portal in the installation's proxy (it would close the portal to every name nobody listed — the server's address, development set-ups — as the 421 refused in [ADR 0039](0039-known-public-names.md) would have); refusing the portal's addresses with 404 instead of redirecting them (the home page's links to the portal would break on an organisation's domain); a template of its own for the organisations' sites (the sites written before would keep serving everything) |
| Amends | [ADR 0009](0009-tenant-domains.md) §5 (the organisations' sites on the host) |

## 1. Context

An organisation's verified `direct` domain ([ADR 0009](0009-tenant-domains.md)) gets an nginx site on the host, written
by `scripts/custom-domains.sh` from the installer's template, with a certificate from Let's Encrypt. The template
forwards every path to the installation's proxy, which hands `/portal/` to the portal and `/api`, `/swaggerui` to the
official data entry API. So the organisation's name served the operator's portal and the data entry API as well as the
organisation's codes: a sign-in page under a name the organisation controls, and may one day point at a server of its
own, after people have learnt to type their password there; a session cookie and the portal's links on that name; the
data entry API offered on it to the addresses the operator allowed. Writes from the portal's pages were refused by its
origin check and cookies are per host, so nothing crossed between the names; but nothing on that name needed the
portal at all.

## 2. Decision

1. **A rule file on the host.** `custom-domains.sh` writes `/etc/nginx/snippets/gs1resolver-domain-paths.conf`
   (`NGINX_SNIPPETS`) at each `apply`, only when its content changes:
   - `= /portal` and `^~ /portal/` answer **302** to the same address on the installation's portal — `PORTAL_ORIGIN`,
     else `RESOLVER_PUBLIC_URL`, else `https://FQDN`, as the portal itself works it out — so that the home page's links
     and a bookmark still reach the portal, on its own name;
   - `^~ /api` and `^~ /swaggerui` answer **404**: the data entry API is not offered on an organisation's name at all,
     whatever `DATA_ENTRY_API_ALLOW` lists.

   The prefixes are those of the installation's proxy (`frontend_proxy_server/nginx.conf`), so no path that proxy
   would give to the portal or the data entry API is passed on. Every other path — codes with or without the domain's
   stem, `/.well-known/gs1resolver`, the home page — is passed on as before.
2. **Every organisation's site includes it**, once, before each `location / {` (the HTTP server the template writes,
   which Certbot turns into the HTTPS one). New sites get the include when they are written; sites written before get
   it at the next run (the installer's cron runs `apply` every 5 minutes), nginx is tested once for all of them, and
   each site is put back byte for byte when nginx refuses the result (`ERROR`, the run fails and is shown on the
   portal's domain cards). A site without `location /` (edited by hand) is reported and left alone. `list` names the
   sites that do not include the rule yet.
3. **The portal's address is checked** before it reaches nginx's configuration: a plain `http(s)://host[:port]` origin,
   in lower case; anything else refuses the portal's addresses with 404 instead of redirecting, with a warning.
4. **The installation's own name is unchanged**: the installer's templates do not include the rule.
5. **Stems that cannot resolve are refused.** A domain's path stem whose first segment the installation's proxy gives
   to something other than the resolver — `api…`, `swaggerui…`, `portal`, `home` — or that the resolver answers
   itself (`.well-known`), in any case, is refused by the portal (`domains.stemInvalid`, `domains.clean_stem()`): codes
   printed under it would have reached the portal, the data entry API or the home page, and never their links.

## 3. Consequences

- On an organisation's domain, `/portal/…` leads to the installation's portal and `/api`, `/swaggerui` answer 404; its
  codes, description file and home page answer as before. No step for the operator: the next scheduled run changes the
  sites written before and reloads nginx.
- A tool that called the data entry API or the tenant API (`/portal/api/v1`) through an organisation's domain must use
  the installation's name (the redirect of the tenant API is not followed with its key by common HTTP clients).

## 4. Residuals

- Only the sites `custom-domains.sh` manages carry the rule: a site an operator writes by hand for another name, and
  any name that reaches the installation's own site (the host's default), still reach the portal; the installation's
  proxy serves the portal on whatever name it is given.
- The home page, with the operator's name and links, is still shown at the root of an organisation's domain.
- A domain saved before with one of the stems now refused keeps it (its codes never resolved; the portal refuses the
  stem again only when it is changed).

## 5. Delivery

`scripts/custom-domains.sh` (`portal_origin()`, `write_rule()`, `add_rule()`, `migrate_sites()`, `list`, `apply`);
`portal/domains.py` (`RESERVED_STEM`, `clean_stem()`); the message `domains.stemInvalid` naming the words, in the twelve
languages (`portal/static/i18n.js`, `portal/static/locales/`).
Tests: `test_deploy.py` (`domain_rule_checks()`: the rule's content and the portal's address with its precedence and
its check, the include in new sites and in sites written before — once, before each location, nothing else changed, a
second run idle — a site nginx refuses put back, a site without `location /` reported, `list`; and through a real nginx,
the portal's pages and API redirected and never passed on, the data entry API and its Swagger UI refused, codes with a
stem and `%2F`, the description file and the home page passed on unchanged), `test_domains.py` (the stems refused in
any case, the same words further in or longer accepted); 18 mutations, all caught.
