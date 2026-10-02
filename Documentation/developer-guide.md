# Developer guide

How the GS1 Digital Link Resolver CE — Expansion Pack is built: the services, every source file written or
changed by the fork, the portal's API and data files, the tests, and how to extend it. Read it together
with the docstrings in the code, which describe each function, and with the
[extensions documentation](extensions/README.md), which records the detailed rules and design decisions.

For installation and configuration see the [README](../README.md); for using the portal, the
[user guide](portal-user-guide.md).

*Versão em português: [guia do desenvolvedor](pt-BR/guia-do-desenvolvedor.md).*

## Contents

1. [Architecture](#1-architecture)
2. [Repository layout](#2-repository-layout)
3. [Services and configuration](#3-services-and-configuration)
4. [Request flows](#4-request-flows)
5. [Portal back end (`portal/`)](#5-portal-back-end-portal)
6. [Portal front end (`portal/static/`)](#6-portal-front-end-portalstatic)
7. [Portal API](#7-portal-api)
8. [Portal data files](#8-portal-data-files)
9. [Changes to the resolver (`web_server/`)](#9-changes-to-the-resolver-web_server)
10. [Changes to the data entry API (`data_entry_server/`)](#10-changes-to-the-data-entry-api-data_entry_server)
11. [Proxy and home page (`frontend_proxy_server/`)](#11-proxy-and-home-page-frontend_proxy_server)
12. [Scripts (`scripts/`)](#12-scripts-scripts)
13. [Development tests (`dev-tests/`)](#13-development-tests-dev-tests)
14. [How to extend](#14-how-to-extend)
15. [Conventions](#15-conventions)

## 1. Architecture

```
 Browser ─── HTTPS ───► host nginx (TLS) ──► 127.0.0.1:8080
                                               │
                     frontend-proxy-service (nginx)
                       ├─ = /, /home/…            → home page (static, in the proxy image)
                       ├─ /                       → web-service:4000         resolution (public)
                       ├─ /api, /swaggerui        → data-entry-service:3000  data entry API (token)
                       └─ /portal/                → portal-service:8000      link management portal
                                                        │ Bearer SESSION_TOKEN, internal network
                                                        ▼
                                              data-entry-service:3000/api
 web-service ─┐
 data-entry ──┴──► database-service (MongoDB 27017)
```

- **web-service** (official, changed) answers GS1 Digital Link URIs: redirects, linksets, HTML pages.
- **data-entry-service** (official, changed) is the JSON API that writes records into MongoDB.
- **portal-service** (new) is a Flask application behind gunicorn. It serves the portal's pages and is the
  only client of the data entry API used by people: the browser talks to `/portal/api/*` with a simple
  JSON document and never sees the API token. The portal validates, reads the current state, chooses a
  safe sequence of API calls, and records who changed what.
- **frontend-proxy-service** (official, changed) routes the paths above and serves the home page.
- **database-service** (official) is MongoDB.

Both the resolver and the portal validate with the **GS1 Barcode Syntax Engine**: the resolver through the
official Node package `gs1encoder` (every request), the portal through the C library and GS1's Python
binding (data attributes). The portal's own key and qualifier rules mirror the engine and are compared
with it by the tests.

## 2. Repository layout

Files added by the fork are marked **new**; the others are official files with changes.

```
.env.example                     configuration defaults (committed); .env holds installation values
docker-compose.yml               five services; .env loaded by every service; bind addresses; named volumes
data_entry_server/src/
  data_entry_namespace.py        /summary, token on /index, BearerAuth in Swagger
  data_entry_logic.py            read_summary()
  data_entry_db.py               read_all_documents()
web_server/src/
  web_logic.py                   walk-up, linkType forms, choice of a link, 404 rules, linkset
  web_namespace.py               raw request path, HTML or JSON answers, description file, query string
  web_pages.py                   new: HTML pages (errors, linkset) in pt-BR and en-GB
  public/gs1resolver.json        description file template
frontend_proxy_server/
  nginx.conf                     routes for /, /home/, /portal/, /api, /swaggerui
  home/                          new: index.html, home.css, home.js, images
portal/                          new: the link management portal
  app.py                         Flask application: pages, API, sessions, jobs
  gs1.py                         keys, qualifiers, prefixes, link types, languages, Digital Link URIs
  syntax.py                      data attributes through the GS1 Barcode Syntax Engine
  label.py                       QR code labels (SVG, PNG)
  sheet.py                       spreadsheet import and export
  linkcheck.py                   link checker with SSRF guard
  users.py                       user store and roles
  meta.py                        who created and last changed each record
  journal.py                     history of records and audit trail
  create_user.py                 command-line user administration
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  tools/build-syntax-engine.sh   builds the engine (C library + Python binding)
  assets/fonts/                  Liberation Sans for the label text (OFL)
  Dockerfile, requirements.txt
scripts/                         new: install.sh, templates/, resolver-backup.sh, resolver-backup.cron
dev-tests/                       new: development tests and the screenshot script
Documentation/                   README index, user guide, features, history, this guide,
                                 pt-BR/ (these documents in Portuguese), extensions/ (detailed
                                 documentation, changelog), images/, upstream-README.md
tests/, useful_external_python_scripts/   official
```

## 3. Services and configuration

| Service | Build | Port | Volumes |
|---|---|---|---|
| `database-service` | `database_server/` | `${DATABASE_BIND_ADDRESS:-0.0.0.0}:27017` | database data |
| `data-entry-service` | `data_entry_server/` | internal 3000 | — |
| `web-service` | `web_server/` | internal 4000 | — |
| `portal-service` | `portal/` (two stages: syntax engine, application) | internal 8000 | `resolver-portal-config:/app/config` |
| `frontend-proxy-service` | `frontend_proxy_server/` | `${PROXY_BIND_ADDRESS:-0.0.0.0}:8080` | — |

Every service reads `.env.example` and then `.env` (Compose ≥ 2.24, `required: false`), so `.env` holds
only what an installation changes. The bind addresses are read by Compose itself, from `.env` only. The
variables are described in `.env.example` and in the README's *Configuration* section; the portal also
reads `PORTAL_SESSION_HOURS`, `PORTAL_SECRET_KEY`, `PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT` and,
for tests, the `PORTAL_*_FILE` / `PORTAL_CONFIG_DIR` paths.

## 4. Request flows

**A scan.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. The engine checks the URI; the
resolver reads the document of `/01/09506000134352`, chooses the entry of the qualifier set (walking up to
a less specific entry when there is none), picks the link by `linkType`, language, media type and context,
and answers `307` to it with the scan's query string appended exactly as sent.

**Saving a record in the portal.** The browser sends `POST /portal/api/record` with `key`, `value`,
`qualifiers`, `description` and `links`. `app.py`:

1. checks the session, the role (editor) and the GS1 Company Prefix of the identifier;
2. `build_document()` validates everything with `gs1.py` and builds the Resolver CE v3 document;
3. `store_record()` reads the current document (`GET /api/01/…`) and chooses the calls:
   new entry → `POST /api/new`; existing entry → `PUT` (merge) and then a partial `DELETE` of the targets
   the user removed, in that order so the record is never without targets;
4. `record_change()` updates `records-meta.json` and appends a version to `journal.jsonl`;
5. answers a message code (`save.created`, `save.updated`), translated by the browser.

**Deleting one record of a key.** The API can only delete a whole document, so `delete_record()` deletes it
and writes the other entries back with `POST /api/new`; if that fails, the original document is restored.

**A spreadsheet import.** `POST /import/preview` reads the file (`sheet.py`), validates every row with the
editor's rules, compares with the resolver and keeps the plan in memory under a token (30 minutes).
`POST /import/apply` runs the plan in a background thread with `store_record()`; the browser polls
`GET /import/status`.

**A link check.** `POST /links/check` (editor) or `POST /links/jobs` (every record, import preview) start a
background job; `linkcheck.check_many()` checks each address once; `GET /links/jobs/{token}` reports
progress and problems; the last full check is kept in memory for `GET /links/last`.

## 5. Portal back end (`portal/`)

### `app.py` — the application

Organised in sections (comment lines `# ---- …`):

| Section | Contents |
|---|---|
| configuration | environment, Flask settings (session cookie `gs1resolver_portal`, HttpOnly, SameSite=Lax, Secure over HTTPS, sliding expiry), loggers (`portal`, `portal.audit`), first user from `PORTAL_ADMIN_*` |
| authentication | `Throttle` (5 failures → 15 minutes, per user name and per address), `current_user()` with the password fingerprint, `require_login`, `role_required()`, `allowed()` / `check_access()` for prefixes, same-origin check for writes, security headers, error handlers |
| resolver API client | `resolver()` (one API call with the token), `read_entries()`, `find_entry()`, `describe_entry()` (product, qualified or other), `record_change()` |
| form → Resolver CE v3 | `request_key()`, `request_qualifiers()`, `build_document()` |
| pages and assets | `/portal/`, `/portal/login`, static files (`PUBLIC_ASSETS` before sign-in, `PRIVATE_ASSETS` after) |
| portal API | sign-in, sign-out, password, health, `/config`, `/record` (GET, POST, DELETE) with `store_record()`, `/records` |
| spreadsheets | `/export`, `/import/preview`, `/import/apply`, `/import/status`, `_run_import()` |
| link checker | `/links/check`, `/links/jobs`, `/links/jobs/{token}`, `/links/last`, `_run_link_job()` |
| governance | `/users` (GET, POST, PUT, DELETE, reset), `/history`, `/audit`, `/audit.csv` |
| labels | `qr_version()`, `qr_error_level()`, `/digital-link`, `/qrcode` |

Errors are exceptions carrying a message code: `gs1.ValidationError` (422), `AccessDenied` (403),
`users.UserError` (422), `UpstreamError` (502/503, detail logged only). Imports, link-check jobs and the
sign-in throttle live in memory, which is why the portal runs a single gunicorn worker with threads.

### `gs1.py` — GS1 rules

- `PRIMARY_KEYS`: AI → (name, validator) for the 16 primary keys of URI Syntax 1.7 §4.3. Validators are
  built from small helpers: `_numeric_key(length)`, `_with_serial(base, serial_max, filler)`,
  `_alnum_key(maximum)`, `_itip`, `_gmn` (check-character pair, `gmn_check_pair()`), `_cpid`, `_gcn`,
  `_gtin` (`normalise_gtin()`, any length → 14 digits).
- `KEY_SHAPES`: for each key, the alternative qualifier sets allowed together and which are required;
  `QUALIFIER_FORMATS` and `QUALIFIER_ORDER`, `normalise_qualifiers()` (format, combination and the order
  of §4.9), `parse_qualifier_text()` (`(10)L1(21)S1` or `/10/L1/21/S1`),
  `is_valid_qualifier_set()`, `qualifier_list()` / `pairs_from()` (Resolver CE `[{AI: value}]` ↔ pairs),
  `qualifier_path()`, `qualifiers_match()`.
- Registration model of GS1-Conformant Resolver 1.2.1 §2.5.9: `INFORMATIVE_QUALIFIERS` (for 01 and 8006,
  with AI 21 the AIs 22 and 10 are informative), `split_informative()` (the qualifiers of a Digital Link →
  the record's own and the informative ones), `join_informative()` (back, in path order) and
  `has_key_level()` (whether a key can have a record without qualifiers: not 415). In `app.py`,
  `request_record()` names a record by its own qualifiers; open, save, delete and history use it, while the
  label and QR code use every qualifier. `key_record_document()` builds the key's own record asked for when
  saving (`keyRecord`).
- `normalise_key()`, `anchor_for()`, `split_anchor()`, `digital_link()`, `hri_lines()`, `element_string()`.
- `company_part()` / `within_prefixes()` for governance; `link_key()` (type + languages + context).
- `normalise_language()` (any BCP 47 tag).
- Text: `without_invisible()`, `ascii_digits()`, `clean_text()` (NFC, no control characters),
  `normalise_url()` (HTTPS only, no spaces or invisible characters), `guess_media_type()`.
- `LINK_TYPES` (29 GS1 link types, grouped), `LANGUAGES`, `MAX_DESCRIPTION`.

### `syntax.py` — data attributes

`Engine` (one instance, `syntax.ENGINE`) loads `libgs1encoders.so` and GS1's Python binding from
`GS1_SYNTAX_ENGINE_DIR` (built by `tools/build-syntax-engine.sh`, release 1.4.1). Without it `available` is
false and the option is hidden. From the engine's Syntax Dictionary (`parse_dictionary()`) it builds the
attributes allowed in a query string (AIs flagged `?`), the families of decimal AIs (`decimal_families()`,
`310n`…) and the AIs that belong in each key's path. `describe()` feeds `/config`; `resolve_decimal()`
converts `123,45` for a family; `digital_link()` checks the attributes of a record (day 00, duplicates,
AIs of the path refused, then the engine's own linters and association rules) and returns the URI and the
HRI lines, or raises `ValidationError` with a message code. Calls to the engine are serialised by a lock.

### `label.py` — QR code labels

`LabelOptions` (URI, HRI lines, show HRI, version, level) → `symbol()` (segno, `micro=False`,
`boost_error=False`; `DoesNotFit` with the needed version and fitting level) → `_layout()` (modules,
quiet zone of 4, text 2.2 mm with Liberation Sans metrics) → `render_svg()` (millimetres at X = 0.495 mm,
text as glyph outlines) or `render_png()`.

### `sheet.py` — spreadsheets

`FORMATS` (limits per format), `detect_format()`, `read_table()` (`_read_xlsx`, `_read_csv` with encoding
and separator detection), `map_header()` (column titles in any language, old `gtin` alias),
`parse_rows()` (rows → records with every row error), `export_rows()`, `write_csv()`, `write_xlsx()`
(with reference sheets), `protect()` / `unprotect()` against formulas.

### `linkcheck.py` — link checker

`check_url()` (cached 10 minutes) → `_check()`: follows redirects by hand (at most 5), resolves every host
and refuses private, loopback and link-local addresses at each step, uses `HEAD` and falls back to `GET`
without reading the body, reports HTTPS → HTTP downgrades. `check_many()` runs a thread pool with progress.

### `users.py`, `meta.py`, `journal.py` — portal files

Small stores for the files of section 8. All writes are atomic (temporary file + rename, mode 600) and
serialised with an advisory lock, so the portal and `create_user.py` can work at the same time. `users.py`
also hashes passwords (Werkzeug), spends the same time for unknown users, and computes the session
fingerprint. `journal.search()` filters events by user, dates, text and prefix permission.

### `create_user.py`

`docker compose exec portal-service python create_user.py <name> [--role …] [--prefixes …] [--remove]`
creates a user or sets a password (asked twice), role and prefixes, or removes a user.

## 6. Portal front end (`portal/static/`)

No framework and no build step: plain HTML, CSS and JavaScript served as static files.

| File | Role |
|---|---|
| `index.html` | the portal page: header with language and user menus, editor (three steps, other records, history), label block, record list, users, audit, dialogs (options, import), the template of a target row |
| `login.html`, `login.js` | sign-in page |
| `password.js` | show/hide button in every password field |
| `i18n.js` | message catalogue (pt-BR, en-GB) and translation engine |
| `app.js` | everything else; a map of its sections is at the top of the file |
| `app.css` | styles; media queries after the rules they change |

**Views.** The address fragment chooses the view (`#records`, `#users`, `#audit`, otherwise the editor),
so the browser's back button and bookmarks work (`applyView()`).

**Translation.** Elements declare their texts: `data-i18n="key"`, `data-i18n-params='{…}'`,
`data-i18n-attr="placeholder:key;aria-label:key"`. `I18N.apply()` renders them all; `I18N.set(el, key,
params)` sets one; `t(key, params)` returns a string. The language comes from the saved choice, the
`gs1resolver_lang` cookie (shared with the home page and the resolver's pages) or the browser. Server
answers carry codes (`save.updated`, `key.checkDigit`…) with parameters, rendered by the same catalogue.

**Validation.** `readKey()` and `readQualifiers()` repeat the server's rules for instant feedback; the
server checks again and is the authority.

**Record list.** `loadRecords()` fetches `/records` once; `renderRecords()` filters in the browser by key
type (`#records-key`), qualifier (`qualifierMatches()`), author, link problems and text (`fold()` ignores
case and accents). `parseCode()` reads a pasted GS1 Digital Link or bracketed element string, and
`codeRank()` orders the records by their relation to it (exact, more general, more specific).

## 7. Portal API

Base `/portal/api`, session cookie, JSON. Writes need the portal's own `Origin` and a JSON body. Every
call checks the role and limits identifiers to the user's GS1 Company Prefixes. Errors answer
`{"code": "...", "params": {...}}`.

| Method and path | Role | Purpose |
|---|---|---|
| `POST /login` `{username, password}` | — | Sign in (429 `auth.locked` when throttled) |
| `POST /logout` | — | Sign out |
| `POST /password` `{currentPassword, newPassword}` | any | Change password; other sessions end |
| `GET /config` | any | User, role, prefixes, resolver address, link types, keys with qualifiers and shapes, languages, import limits, data attributes |
| `GET /record?key=&value=&qualifiers=/10/L1` | reader | One record: `exists`, `description`, `links`, `defaultLinkType`, `sharedDefaultLinkType`, `digitalLink`, `otherEntries` (each with `informative`), `qualifiers` (the record's own), `informative` (typed) and `storedInformative`, `hasKeyRecord` |
| `POST /record` `{key, value, qualifiers, description, links:[{linkType, url, title, hreflang, forwardQueryString}], keyRecord?}` | editor | Create (201) or replace (200); the first link is the default. With a serial number, 22 and 10 in `qualifiers` are stored as informative. `keyRecord: {mode: copy\|target, description, url}` also creates the key's own record first (`save.createdWithKey`, `keyRecordCreated`) |
| `DELETE /record?key=&value=&qualifiers=` | editor | Delete one record, keeping the others of the key |
| `GET /records` | reader | Every record with kind, qualifiers, `informative`, description, default link type, number of links, created/updated by and when, `noKeyRecord`, `breaksRules` |
| `POST /export` `{format: xlsx\|csv, labels}` | reader | Spreadsheet of every record |
| `POST /import/preview` `{filename, data (base64), labels, checkLinks}` | editor | Validation and comparison; `token`, `records` (with `informative`, `informativeBefore`, `noKeyRecord`), `errors`, `counts`, `links`, `keysWithoutRecord` |
| `POST /import/apply` `{token, createKeyRecords?}` · `GET /import/status?token=` | editor | Write a previewed import (with `createKeyRecords`, the keys' own records first); progress and results |
| `POST /links/check` `{urls}` | editor | Check addresses (editor) |
| `POST /links/jobs` `{scope: all\|urls}` · `GET /links/jobs/{token}` · `GET /links/last` | editor · editor · reader | Background link check |
| `GET /history?key=&value=&qualifiers=` | reader | Versions of a record, with content |
| `GET /users` · `POST /users` · `PUT /users/{name}` · `POST /users/{name}/reset` · `DELETE /users/{name}` | admin | User administration; temporary passwords in the answer |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | admin | Audit trail |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | reader | Digital Link with data attributes checked by the engine; nothing stored |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:value` | reader | Label; headers `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`; 422 `qr.tooSmall` / `qr.tooLong` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable"}` |

## 8. Portal data files

All in the `resolver-portal-config` volume (`/app/config`), included in the daily backup.

| File | Content |
|---|---|
| `users.json` | `{"maria": {"hash", "role", "prefixes": ["7891234"], "disabled", "mustChange", "created", "lastLogin"}}`; files from before roles (`{"name": "<hash>"}`) are read as administrators |
| `secret.key` | random key signing the session cookies (unless `PORTAL_SECRET_KEY` is set) |
| `records-meta.json` | `{"09506000134352/10/L2026A": {"createdAt", "createdBy", "updatedAt", "updatedBy"}}`; GTIN records keyed by the 14 digits, other keys by `AI/value` |
| `journal.jsonl` | one JSON event per line: `{"at", "user", "action", "anchor"?, "qpath"?, "doc"?, "detail"?}`; record actions `create`, `update`, `delete` (with the record's content), `import`; others `login`, `login-failed`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove` |

## 9. Changes to the resolver (`web_server/`)

- `web_logic.py`: `normalise_linktype()` (every accepted form of a link type), `_parse_qualifier_path()`
  and `_entry_applies()` (walk-up: an entry applies when all its qualifiers are in the request, templates
  such as `{0}` matching any value; the most specific applicable entry answers first — a serial number or
  TPX (`_UNIT_QUALIFIERS`) before any batch or variant, then more qualifiers before fewer; informative
  qualifiers are never read), `_qualifier_path_from()` (values percent-encoded), `_find_linktype_key()`,
  `_public_link()` (only public fields; `fwqs` dropped), `format_linkset_for_external_use()` (RFC 9264 or
  JSON-LD); 404 when the link type is missing.
  Choosing a link (item 1.5): `_handle_link_type()` follows section 2.6.3 — without `linkType` only
  `gs1:defaultLink` and `gs1:defaultLinkMulti` compete, and a variant wins only when the request decides it;
  `choose_links()` (media type, then `_language_match()` with `language_ranges()` — q-values, RFC 4647
  lookup — then context) replaces the official `_match_*()` helpers; `with_default_multi()` publishes and
  uses several links of the key's default type as `gs1:defaultLinkMulti`; a 300 carries the anchor of its
  level. `_test_gs1_digital_link_syntax()` sends `https://id.gs1.org` + the encoded path to
  `callGS1encoder.js`, which uses the engine's Digital Link parser (`dataStr`) for a URI and keeps
  `aiDataStr` for an element string.
- `web_namespace.py`: `_request_segments()` and `_resolve_path()` (the path from the raw request URI,
  `RAW_URI`, each segment decoded on its own, so `%2F` stays in its value), `_extract_query_strings()` (the
  raw query string), `_wants_html()` (browser, API client, or no `Accept` header: HTML),
  `_resolver_description()` (description file from `FQDN`, `RESOLVER_*` and `RESOLVER_TERMS_URL`, without
  `_id`), `_bad_request()`, `_append_query()` (query string joined with `&`), the 300 as a linkset or a page,
  `_latin1()` (safe `Location` headers), trailing slash accepted.
- `web_pages.py` (new): `render_error()` and `render_linkset()` (also the 300 choice page, with the linkset
  embedded as JSON-LD) in pt-BR / en-GB, `negotiate_locale()`, the operator footer, only `http(s)` targets
  as links.

The table of every behaviour change, with the clause of the standard, is in the extensions documentation
(*Resolver CE changes*).

## 10. Changes to the data entry API (`data_entry_server/`)

- `GET /api/summary[?links=true]` (`DocSummary` → `read_summary()` → `read_all_documents()`): one line per
  entry (anchor, qualifiers, description, default link type, number of links, optionally the links).
- `GET /api/index` now requires the token; every protected operation declares `security='BearerAuth'`.
- `registration_problem()` (called by `create_document()` and `update_document()`): the qualifiers each key
  takes (`KEY_QUALIFIERS`, URI Syntax 1.7 §4.9), 415 needs 8020, and rules 1 and 2 of GS1-Conformant
  Resolver 1.2.1 §2.5.9 (235 alone; no 22 or 10 with 21). Values are not checked, so templates such as
  `{lotnumber}` keep working; the portal checks them in full.
- `informativeQualifiers` (`INFORMATIVE_QUALIFIERS`): on a serial-number entry of 01 or 8006, a list like
  `qualifiers`, stored next to it in MongoDB, returned by `GET` and `/summary`, merged by `PUT` (absent:
  kept; empty list: cleared) and by an upsert on the same entry. Declared in the Swagger model.

## 11. Proxy and home page (`frontend_proxy_server/`)

`nginx.conf` serves `/` and `/home/…` from the image, sends `/` paths to web-service (the raw request URI,
`proxy_pass http://resolver_web/api$request_uri`, so that `%2F` and the query string arrive as sent), `/api` and
`/swaggerui` to data-entry-service, and `/portal/` to portal-service (with `/portal` → `/portal/`).
`home/home.js` reads the operator from `/.well-known/gs1resolver`, takes the resolver root from the address
bar, and shares the language choice with the portal.

## 12. Scripts (`scripts/`)

- `install.sh`: installer for Ubuntu 22.04/24.04 (checks, questions with earlier values as defaults,
  Docker, host nginx with Certbot or an existing certificate or an external proxy, `.env` with generated
  secrets, start-up, backup cron). Safe to re-run; `--non-interactive` reads every answer from
  environment variables. Templates of the nginx site in `templates/`.
- `resolver-backup.sh` + `resolver-backup.cron`: MongoDB dump through the container and archive of the
  portal volume, 14 days kept.

## 13. Development tests (`dev-tests/`)

No Docker needed; each program exits with status 1 on a failure. Setup and commands are in
`dev-tests/README.md`.

| Program | Checks | Covers |
|---|---:|---|
| `resolver/test_resolver.py` | 170 | resolver and data entry code through Flask's test client: every key and qualified record, walk-up, link types, 404 rules, linkset schema, attributes passed on, description file schema, HTML pages |
| `resolver/test_data_entry_api.py` | 53 | token on every protected operation; registration rules of §2.5.9 and informative qualifiers |
| `portal/test_keys.py` | 137 | keys and qualifiers, compared with the GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | roles, prefixes, users, history, audit |
| `portal/test_sheet.py` | 43 | spreadsheets, limits per format |
| `portal/test_special_chars.py` | 57 | special characters |
| `portal/test_data_attributes.py` | 83 | data attributes, decimal families, QR options (needs `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | link checker, SSRF guard |
| `portal/test_portal_config.py` | 9 | configuration and start-up |
| `portal/test_registration.py` | 26 | §2.5.9 through the portal API: informative qualifiers (save, open, history, list, export, import), records against rule 2, the key's own record when saving and importing |
| `portal/test_portal_e2e.py` | 186 | the portal in Chromium against `mock_data_entry.py`, desktop and phone; also run without the engine |
| `home/test_home.py` | 45 | home page through a real nginx |
| `install/test_install.sh` | — | installer through shims (Compose v2) |

`docs/screenshots.py` regenerates the images of the README and of the user guide, in English and in
Portuguese, from the real portal with example data (GS1 logo hidden). Commit only images that really changed.

## 14. How to extend

**A text of the interface.** Add the key to both locales of `i18n.js` (`pt-BR` and `en-GB`), use it with
`data-i18n` or `I18N.set()`. Server messages are codes: raise `ValidationError("my.code", param=…)` and add
`my.code` to both locales.

**A language.** Copy a locale block of `i18n.js`, translate it, add it to `SUPPORTED` and
`LOCALE_MATCHERS`; do the same in `web_pages.py` (`TEXT`, `LINK_TYPE_LABELS`) and `home/home.js`.

**A link type.** Add a row to `LINK_TYPES` in `gs1.py` and its name and description to `linkTypes` in both
locales; consider `activeLinkTypes` in `web_server/src/public/gs1resolver.json`.

**A primary key or qualifier** (a future version of the standard). Add the validator to `PRIMARY_KEYS`,
the shapes to `KEY_SHAPES` and formats to `QUALIFIER_FORMATS` in `gs1.py`; mirror them in `app.js`
(`NUMERIC_KEYS`, `readKey()`, `QUAL_ORDER`, `QUAL_FORMATS`); add `key.<AI>.*` / `qual.<AI>.*` texts; extend
`dev-tests/portal/test_keys.py` and compare with the engine.

**An API endpoint.** Add the route to the right section of `app.py` with `@require_login` and, for writes,
`@role_required("editor")`; call `check_access()` for every identifier; answer with `message()` codes;
log with `audit.info()` and `log_event()`; add tests; list it in this guide and in the README.

**The syntax engine.** Change the tag in `portal/tools/build-syntax-engine.sh` and, to keep both engines
together, pin the same `gs1encoder` version in `web_server/Dockerfile`; run every test.

## 15. Conventions

- Code, comments, identifiers, commit messages and documents in British English; user-facing text in
  pt-BR and en-GB.
- Official variable names and behaviour kept; deliberate changes documented in the changelog.
- No organisation names or instance values in the code: `FQDN`, `RESOLVER_ORG_*`, `RESOLVER_CONTACT_*`.
- Secrets never printed or committed; `.env.example` holds development defaults only.
- One topic per commit, with a message explaining why; every test passes before delivery.
- Docstrings on every function written for the fork; the official functions keep their original form.
- Documents that exist in both languages (`Documentation/` and `Documentation/pt-BR/`) change together.
