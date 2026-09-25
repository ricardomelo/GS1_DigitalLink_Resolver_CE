# Changelog

## Unreleased (branch gs1br/develop)

Work moved from a patch + package into commits on a fork of the official repository, in preparation
for contributing upstream.

### Configuration
- Layered configuration: every service reads `.env.example` (committed development defaults, token
  `secret` as upstream) and then `.env` (installation values, never committed). Fixes upstream's mix of
  `.env.example` (database, data entry) and `.env` interpolation (web server).
- New variables: `FQDN` documented, `RESOLVER_ORG_NAME`, `RESOLVER_ORG_URL`, `RESOLVER_CONTACT_*`,
  `RESOLVER_PUBLIC_URL`, `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD`, and the Compose-level
  `PROXY_BIND_ADDRESS` / `DATABASE_BIND_ADDRESS` (replace `docker-compose.override.yml`).
- `tests/setup_test.py` reads the token from `SESSION_TOKEN`.

### Resolver
- `/.well-known/gs1resolver` built at request time: `resolverRoot` from `FQDN`, `contact` from
  `RESOLVER_*`; `gs1resolver.json` keeps neutral placeholders.
- HTML page footer from `RESOLVER_ORG_NAME` / `RESOLVER_ORG_URL`, omitted when unset (no built-in operator).

### Portal
- Service defined in `docker-compose.yml`; no instance values in the code (public address from
  `RESOLVER_PUBLIC_URL` or `https://FQDN`; Secure cookie follows its scheme).
- First user created from `PORTAL_ADMIN_*` while the user store is empty.
- User store and session key in the named volume `resolver-portal-config` (no host chown).

### Home page
- Files copied into the proxy image instead of a bind mount; neutral path `/usr/share/nginx/home`.

### Backup
- Also archives the portal configuration volume; locates the repository from its own path; settings
  overridable from the environment.

### Development tests
- Moved into the repository; new `portal/test_portal_config.py`; description-file checks.


## 1.1.0 — 23 September 2026

### Home page
- New home page at `/` in the portal's look and feel, with a menu to the link management portal
  (`/portal/`), the Resolver API documentation (`/api/docs`, the Swagger UI previously shown at `/`),
  the GS1 Digital Link standard on ref.gs1.org, gs1.org and the Resolver CE repository on GitHub.
- Domain independent: root-relative links, resolver root read from the address bar, operator name read
  from `/.well-known/gs1resolver` (`contact.fn`).
- pt-BR / en-GB with the portal's detection rules and shared choice (cookie `gs1resolver_lang` and the
  portal's storage key); collapsible menu on small screens; English fallback without JavaScript.
- Served statically by the front-end proxy (`location = /`, `location ^~ /home/`) from
  `frontend_proxy_server/home`, mounted read-only by `docker-compose.override.yml`; strict Content
  Security Policy, `nosniff`, `Referrer-Policy`.

### Development tests
- `dev-tests/home/test_home.py`: the real nginx.conf against mock upstreams (routing of `/`, assets and
  every existing path) and the page in Chromium (links, languages, domain independence, phone menu,
  CSP, no-JavaScript fallback). 41 checks.


## 1.0.0 — 23 September 2026 (checkpoint)

Installed on the GS1 Brasil staging resolver and reported working by the operator.

### Portal
- Back-end-for-front-end (Flask) holding the resolver token; safe orchestration of Resolver CE calls
  (POST /new for new entries, PUT + partial DELETE for edits, rebuild for batch deletion).
- Three-step form: product (GTIN with live check-digit feedback, optional batch/lot), name, targets.
- First target is the default link (`gs1:defaultLink`); "Make default"; link-type menu shows the code first.
- Per-target "pass query parameters on" option (`fwqs`).
- Label preview = exported label: PNG and SVG, 4X quiet zone, optional HRI, optional GS1® branding (pilot)
  per the QR Codes powered by GS1 design guidelines; SVG at 100 % target size in millimetres.
- Brazilian Portuguese and British English: detected from the system, switchable live, message codes
  translated in the browser, choice shared with the resolver pages through a cookie.
- Sign-in page with session cookie, lockout after five failures, user menu (Options → change password,
  Sign out); password change signs out other sessions; audit trail.
- gs1.org look and feel; product name "GS1 Resolver Community Edition".

### Resolver CE patch (against bf885fd)
- Hierarchy walk-up for qualifiers (unknown batch → GTIN; serial → batch); trailing slash accepted.
- linkType accepted as `x`, `gs1:x`, full vocabulary URIs, case-insensitive; `defaultLink` redirect fixed.
- 404 instead of 200-with-error for a missing linkType at batch level; 500 on unknown batch fixed.
- Linkset: plain RFC 9264 that validates against the GS1 schema; JSON-LD on request; correct context
  Link header, exposed through CORS.
- `fwqs` stored and honoured; query string joined with `&` when the target already has one.
- HTML pages for browsers (not found, information not available with the available links, invalid code,
  linkset list) in the gs1.org style, with logo and pt-BR/en-GB language menu.

### Deployment
- `docker-compose.override.yml`: portal service; ports 8080 and 27017 bound to 127.0.0.1.
- `gs1resolver.json` with real resolver root, GS1 Brasil contact, JSON-LD context location.
- Daily MongoDB backup script and cron entry.
