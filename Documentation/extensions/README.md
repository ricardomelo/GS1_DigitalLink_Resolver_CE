# GS1 Resolver CE extensions: link management portal, home page and conformance fixes

This document describes what this branch adds to GS1 Resolver Community Edition v3:

- a **link management portal** (`/portal/`) that lets non-technical users enter a GTIN (optionally a
  batch/lot), a product name and targets, and publish them without JSON, tokens or link-type codes;
- a **home page** at `/`;
- **conformance fixes** to the web server (GS1-Conformant Resolver standard 1.2.1) and HTML pages for
  browsers;
- a **resolver description file** built from the configuration;
- a **layered configuration** (`.env.example` defaults, `.env` per installation) and a **daily backup**.

Interfaces are available in Brazilian Portuguese and British English.

## Architecture

```
 Browser (non-technical user)
      │ HTTPS  https://<FQDN>/portal/   (sign-in page, session cookie)
      ▼
 host nginx (Certbot, TLS) ──► 127.0.0.1:8080   (PROXY_BIND_ADDRESS=127.0.0.1)
      ▼
 frontend-proxy-service (resolver nginx) ─┬─ = / , /home/ → static home page (in the proxy image)
                                          ├─ /          → web-service:4000        (public resolution)
                                          ├─ /api       → data-entry-service:3000 (data entry API)
                                          └─ /portal/   → portal-service:8000
                                                              │
                                     internal Docker network  │ Bearer SESSION_TOKEN
                                                              ▼
                                                  data-entry-service:3000/api
```

One additional service (`portal-service`, Flask + gunicorn) serves the page **and** bridges to the API.
The resolver token stays on the server; the browser talks to `/portal/api/*` with a simple JSON document.

### Why a back end rather than an HTML page calling the API directly

Resolver CE behaves in ways that a naive form would turn into bad data:

| API behaviour | Consequence | What the portal does |
|---|---|---|
| `POST /api/new` on an existing document **appends** links (`extend`) | Saving a form twice duplicates targets | POST only for a new GTIN/batch; edits use `PUT` + partial `DELETE` |
| `PUT`/`DELETE` with unknown qualifiers fall back to **index 0** | Editing a new batch would change another one | Reads the document first and chooses the right call |
| `defaultLinktype` is **one per GTIN** (shared by all batches) | Changing it on one batch affects the others | Blocks the change when other records exist and explains why |
| No route removes a whole **batch entry** | — | Recreates the document without it and restores the original on failure |
| `SESSION_TOKEN` grants full write access | A token in the browser lets anyone change anything | Token only in the container; portal users have their own passwords |


## Configuration

Every service loads `.env.example` and then `.env` if it exists; a value in `.env` replaces the one in
`.env.example`. `.env.example` is committed and holds development defaults (as upstream: user
`gs1resolver`, token `secret`), so `docker compose up -d` works out of the box on a development machine.
`.env` holds the values of a real installation and is never committed.

| Variable | Used by | Development default | For a server |
|---|---|---|---|
| `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` | database (first start only), backup | `gs1resolver` / `gs1resolver` | new password |
| `MONGO_URI` | web, data entry | matches the above | same credentials as above |
| `SESSION_TOKEN` | data entry API, portal | `secret` | long random value |
| `FQDN` | web (linksets, description file), portal | `localhost` | the resolver's domain |
| `RESOLVER_ORG_NAME`, `RESOLVER_ORG_URL`, `RESOLVER_CONTACT_*` | description file `contact`, footer of the resolver pages | `My Organisation` | the operator |
| `RESOLVER_PUBLIC_URL` | portal (printed links, Origin check, cookie flag) | empty → `https://FQDN` | usually empty |
| `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD` | portal, first user only | `admin` / `change-me-please` | chosen at installation |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Docker Compose (**only from `.env`**) | `0.0.0.0` | `127.0.0.1` behind a TLS proxy |

Rules worth knowing:

- Use URL-safe secrets (e.g. `openssl rand -hex 24`), so the MongoDB password goes into `MONGO_URI`
  without percent-encoding.
- `MONGO_INITDB_ROOT_*` only apply when the database volume is created. To change the password later,
  change it in MongoDB first (`db.changeUserPassword`), then update `.env` and recreate the services.
- After editing `.env` run `docker compose up -d` (not `restart`, which keeps the old environment).
- For local development of the portal over plain HTTP, set `RESOLVER_PUBLIC_URL=http://localhost:8080`
  in `.env`.
- Requires Docker Compose 2.24 or later (`env_file` with `required`).

## Quick start (development)

```bash
git clone <this repository> && cd GS1_DigitalLink_Resolver_CE
printf 'RESOLVER_PUBLIC_URL=http://localhost:8080\n' > .env   # portal over plain HTTP on this machine
docker compose up -d --build
```

Then open http://localhost:8080/ (home page) and http://localhost:8080/portal/ (sign in as `admin` /
`change-me-please`, then change the password under Options).

A server installation (TLS, domain, secrets, backup) will be covered by the installation script.

## Portal users

The first user comes from `PORTAL_ADMIN_USERNAME` / `PORTAL_ADMIN_PASSWORD` and is created only while the
portal has no users. Further users, resets and removals:

```bash
docker compose exec portal-service python create_user.py maria            # create or reset (asks twice)
docker compose exec portal-service python create_user.py maria --remove   # remove
```

The user store (`users.json`, password hashes) and the session key (`secret.key`) live in the named
volume `resolver-portal-config`, which the image initialises with the right owner.

## Sign-in, sessions and passwords

- `/portal/login` is a sign-in page (no more browser pop-up). A successful sign-in sets a session cookie
  (`gs1resolver_portal`: HttpOnly, Secure, SameSite=Lax, path `/portal`) valid for 8 hours after the last
  use; afterwards the user is sent back to the sign-in page with a "session ended" message.
- After five failed attempts a username (and, separately, a client address) is locked for 15 minutes.
  The counter lives in memory, which is why the portal runs one gunicorn worker with eight threads.
- The user icon on the right of the header opens a menu (on hover with a mouse, or on click/keyboard)
  showing the username, **Options** and **Sign out**. Options lets users change their own password
  (current password required, at least 12 characters). Changing the password signs out every other
  session of that account.
- Sessions are signed with `secret.key` in the portal's configuration volume, created automatically on first start. Deleting that file
  (in the `resolver-portal-config` volume) and restarting signs everybody out. `PORTAL_SECRET_KEY` in the environment takes precedence.
- Environment settings: `PORTAL_SESSION_HOURS` (default 8), `PORTAL_COOKIE_SECURE` (default: on when the
  public address is `https://`, off for plain-HTTP development).
- The audit trail records `login`, `login-failed`, `logout` and `password-change` alongside the record
  changes.

## Home page

`https://<FQDN>/` shows a home page in the same look and feel as the portal, with a menu to:

| Menu entry | Target |
|---|---|
| Manage links / Cadastro de links | `/portal/` |
| Resolver API / API do Resolver | `/api/docs` (Swagger UI, the page previously shown at `/`) |
| GS1 Digital Link standard | https://ref.gs1.org/standards/digital-link/ |
| GS1 Global | https://www.gs1.org/ |
| Source code (GitHub) | https://github.com/gs1/GS1_DigitalLink_Resolver_CE |

**Domain independent.** Links to this installation are root-relative (`/portal/`, `/api/docs`,
`/.well-known/gs1resolver`), the resolver root shown in the example link is read from the address bar,
and the operator's name in the footer comes from `contact.fn` in the resolver description file. Nothing
in the page names a domain or an organisation, so another installation needs no edits.

**What `/` showed before.** Upstream, the proxy sends `/` to the web server's API root, which is
flask-restx's Swagger UI; that page loads `/api/swagger.json`, which the proxy routes to the data entry
service, so it displayed exactly the data entry API documentation that `/api/docs` serves. The menu
therefore links to `/api/docs`. If `/api` is later restricted at the edge (see "Hardening"), that menu
entry will need the same exception or removal.

**How it is served.** The front-end proxy (nginx) answers `location = /` and `location ^~ /home/` from
`frontend_proxy_server/home`, copied into the proxy image; `/home` and `/home/` redirect to `/`.
`/` with any query string also gets the home page; every other path reaches the resolver as before
(`/` on its own is not a GS1 Digital Link). The page does not depend on the portal or the resolver being up;
only the operator's name needs the description file. Responses carry a strict Content Security Policy
(scripts and styles from the page's own files; fonts from Google Fonts as in the portal).

**Language.** Same rules and same storage as the portal: saved choice, then the `gs1resolver_lang`
cookie, then the browser/system languages; the globe menu switches live and writes both, so the portal
and the resolver's pages follow. Text lives in `frontend_proxy_server/home/home.js`; the English text
in `index.html` is shown when JavaScript is off.

**Editing.** After changing `index.html`, `home.css` or `home.js` run
`docker compose up -d --build frontend-proxy-service`. `home.css` repeats the design tokens of
`portal/static/app.css`; keep them in step.

## Look and feel

Both the portal and the resolver's own pages follow gs1.org: white header with the GS1 logo and the
product name "GS1 Resolver Community Edition", a GS1 blue band with the page title, white panels on a pale
blue-grey page, GS1 orange for the main action and teal links. gs1.org uses the licensed Gotham SSm
typeface; these pages use Montserrat, the closest free match, with Verdana as the same fallback. The logo
is the supplied GS1 artwork converted to transparent PNG.

## Languages

**Portal.** On first visit the language follows the browser/operating system (`navigator.languages`):
any `pt-*` tag selects Brazilian Portuguese, any `en-*` tag British English, and anything else falls back
to British English. The globe menu in the header (also on the sign-in page) switches language instantly,
without reloading or losing what has been typed. The choice is remembered in the browser and in the
`gs1resolver_lang` cookie, which the resolver's own pages also read.

The back end is language-neutral: validation errors and results travel as message codes with parameters
(e.g. `{"code": "gtin.checkDigit", "params": {"expected": 5}}`) and the browser renders them from the
catalogue, so a message already on screen is re-translated when the language changes.

To add a language: copy one locale block in `portal/static/i18n.js`, translate it, and add it to
`SUPPORTED` and `LOCALE_MATCHERS` at the top of the file. Link target languages (`hreflang`) are named
by the browser (`Intl.DisplayNames`), so they need no translation.

**Resolver pages.** The HTML pages served by the resolver (link list, "not found", "information not
available", "invalid code") have their own language menu. The language comes from the `gs1resolver_lang`
cookie when set (by that menu or by the portal); otherwise from the phone's `Accept-Language` header, with
q-values honoured: Portuguese → pt-BR, English → en-GB, anything else → en-GB. A cookie is used rather
than a query parameter so the GS1 Digital Link URI is left untouched (query parameters are passed on to
redirect targets).

**Stored data.** When a target's title is left blank the portal stores the GS1 Web Vocabulary title in
English (e.g. "Product information page"), whatever the interface language.

## What each action does on the API

| On screen | Portal API | Resolver calls |
|---|---|---|
| Sign in / sign out | `POST /portal/api/login`, `POST /portal/api/logout` | — |
| Change password (Options) | `POST /portal/api/password` | — |
| Open record | `GET /portal/api/record` | `GET /api/01/{gtin14}` |
| Save (GTIN or batch without a record) | `POST /portal/api/record` | `POST /api/new` (the first target sets `defaultLinktype`; each target carries `fwqs`) |
| Save (existing record) | `POST /portal/api/record` | `PUT /api/01/{gtin14}` and, if targets were removed, `DELETE /api/01/{gtin14}` with `{qualifiers, links}` |
| Delete (only entry for the GTIN) | `DELETE /portal/api/record` | `DELETE /api/01/{gtin14}` |
| Delete (a batch, or a GTIN that has batches) | `DELETE /portal/api/record` | document `DELETE` + `POST /api/new` with the remaining entries |
| QR code label | `GET /portal/api/qrcode?format=png\|svg&hri=0\|1&brand=0\|1` | generated locally from `{RESOLVER_PUBLIC_URL}/01/{gtin14}[/10/{lot}]` (see "QR code label") |

Rules applied before calling the API: GTIN of 8/12/13/14 digits with a valid check digit, normalised to
14; GTIN-13 starting with 2 (restricted circulation) rejected; batch/lot of up to 20 characters
`[A-Za-z0-9._-]`; `https://` URLs; media type inferred from the extension (`.pdf` → `application/pdf`);
no duplicate resolver key (link type, language, context). Targets with a `context` created by other tools
are preserved when saving.

On screen: the link type menu shows the code first (`gs1:pip — Product information page`); the first
target is the default link (`gs1:defaultLink`) and "Make default" moves another one to the top; each target
has "Pass the request's query parameters on to this target" (stored as `fwqs`); the QR code downloads as
PNG or SVG and the address beneath it is a link.

## QR code label

The image in the preview panel is the exported label itself, so what is shown is what is downloaded.
It follows *QR Codes powered by GS1 design guidelines* (GS1 branding pilot, v1.0, May 2024, draft V6):

- **Size:** the SVG is sized in millimetres at the 100 % target X-dimension, 0.495 mm per module. The PNG
  uses 12 pixels per module and carries a DPI value (≈ 616) that prints at the same size. Do not print
  below 100 %: the text is 2.2 mm high at that size and must not fall under the 2 mm minimum.
- **Quiet zone:** 4X on all four sides, always blank.
- **Human readable interpretation** (checkbox, on by default): the element strings below the quiet zone,
  `(01)` followed by the GTIN-14 and, for a batch, `(10)` followed by the batch/lot on a second line, in
  Liberation Sans (metrically equivalent to Arial). The guidelines require it when the QR code stands alone
  on pack; it may be omitted when the code sits next to the linear barcode that already carries the GTIN,
  or on a consumer-engagement panel.
- **GS1® branding** (checkbox, off by default, pilot): the supplied "GS1®" artwork above the top-left
  corner of the symbol, left-aligned with it and outside the quiet zone, with the same 2.2 mm cap height.
  The artwork is already outlined, so no font is needed to display or print it.
- **SVG** is fully vector: QR modules, wordmark and HRI glyph outlines, so it opens identically anywhere
  and is the format to hand to packaging designers. PNG suits documents and quick use.
- The choices are remembered in the browser. Branded files are named `…_gs1.svg` / `…_gs1.png`.

## Resolver CE changes

| Before | After | Standard reference |
|---|---|---|
| `/10/<unregistered batch>` → 500 | uses the GTIN's links (walks up the tree) | 2.5.9, 2.5.10, item 16 |
| batch with a missing linkType → 200 with an error inside | 404 | 2.6.2, items 9 and 18 |
| `/10/123/` (trailing slash) → 400 | treated as `/10/123` | 2.13, item 25 |
| `?linkType=defaultLink` → 300 with an object | redirects to the default target | 2.5.8 |
| only `x` and `gs1:x` | also `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, case-insensitive | 2.5.2, 2.14 |
| linkset with JSON-LD keys, relative anchor | plain RFC 9264, validates against the linkset schema; JSON-LD only with `Accept: application/ld+json` | 2.10, item 10 |
| JSON-LD context Link header malformed and hidden from CORS | `<…/linkset-context>; rel="http://www.w3.org/ns/json-ld#context"`, exposed | 2.10, item 13 |
| query string always passed on, with a second `?` if the target already had one | passed on by default; `fwqs: false` on a target switches it off; joined with `&` | 2.12, item 19; `fwqs` attribute of the linkset schema |
| browsers get raw JSON on errors | HTML page in the gs1.org style (logo, pt-BR/en-GB language menu) with the same HTTP status; a 404 for a linkType lists the available links | 2.6.2 (MAY list other links) |
| `?linkType=linkset` in a browser → JSON | HTML page listing the links per level (product/batch) | 2.10 |

An unknown linkType **still** returns 404: the standard requires it (2.6.2, item 18). Up to GS1 Digital
Link 1.1 the resolver redirected to the default target; that is no longer permitted. Apps and scripts that
ask for JSON keep receiving JSON.

Without these changes the portal still works, but the "pass parameters on" option has no effect (the resolver
ignores `fwqs`) and the defects in the table remain.

## Operations

Audit trail (who changed what):
```bash
docker compose logs -f portal-service | grep portal.audit
# ... user=maria action=update anchor=/01/07891234567895 lot=L2026A links=3 removed=1
```

To offer more link types, add a row to `LINK_TYPES` in `portal/gs1.py` and its labels to every locale in
`portal/static/i18n.js`, then run `docker compose up -d --build portal-service`.

## Hardening

- Behind a TLS reverse proxy on the same host set `PROXY_BIND_ADDRESS=127.0.0.1` and
  `DATABASE_BIND_ADDRESS=127.0.0.1` in `.env`: plain HTTP (port 8080) and MongoDB (27017) then stay off the
  network. Docker publishes ports past the host firewall (ufw/iptables), so this setting matters.
- With the portal live, restrict `/api` and `/swaggerui` at the edge proxy to the integrations that
  genuinely need them.
- For many users, consider single sign-on (e.g. `oauth2-proxy` in front of `/portal/`) instead of local
  passwords, passing the authenticated user to `app.py` in a header.

## Daily backup

`scripts/resolver-backup.sh` dumps MongoDB (through the database container, so the credentials never
appear on the host) and archives the portal's configuration volume, keeping 14 days in
`/var/backups/resolver`. It finds the repository from its own location.

```bash
sudo scripts/resolver-backup.sh                                     # test: prints OK and the sizes
sed "s|REPOSITORY|$PWD|" scripts/resolver-backup.cron | sudo tee /etc/cron.d/resolver-backup >/dev/null
sudo chmod 644 /etc/cron.d/resolver-backup                          # daily at 02:30
```

Restore the database (replaces the current one):
```bash
docker compose exec -T database-service sh -c 'mongorestore -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --drop' < /var/backups/resolver/ARCHIVE.archive.gz
```
Restore the portal configuration:
```bash
docker compose exec -T portal-service tar -xzf - -C /app/config < /var/backups/resolver/portal-config-ARCHIVE.tar.gz
```
Keep a copy of the archives on another machine as well.

## Development tests

See `dev-tests/README.md`.
