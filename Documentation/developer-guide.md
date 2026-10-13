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
 data-entry ──┼──► database-service (MongoDB 27017): resolver_ce (records), resolver_portal (portal)
 portal ──────┘    the portal and portal-worker with its own user, readWrite on resolver_portal only
```

- **web-service** (official, changed) answers GS1 Digital Link URIs: redirects, linksets, HTML pages.
- **data-entry-service** (official, changed) is the JSON API that writes records into MongoDB.
- **portal-service** (new) is a Flask application behind gunicorn. It serves the portal's pages and is the
  only client of the data entry API used by people: the browser talks to `/portal/api/*` with a simple
  JSON document and never sees the API token. The portal validates, reads the current state, chooses a
  safe sequence of API calls, and records who changed what. Its own data (users, record metadata, journal,
  sign-in failures, caches) is in a database of its own, `resolver_portal`, reached with its own user
  ([ADR 0001](adr/0001-portal-state-in-mongodb.md)).
- **portal-db-init** (new, one-shot) creates or updates that user, then exits; the portal starts after it.
- **portal-worker** (new) runs the portal's background jobs (spreadsheet imports, link checks) from the
  `jobs` collection: the portal's image with `python worker.py`. The web process only queues jobs and reads
  their state, so no job depends on the process that accepted it.
- **frontend-proxy-service** (official, changed) routes the paths above and serves the home page.
- **database-service** (official) is MongoDB.

**Replicas.** web-service, data-entry-service, portal-service and portal-worker keep no state of their own, so
each runs as `*_REPLICAS` containers (`.env`, default 1; Compose's `deploy.replicas`), without a fixed
`container_name`. The three web services run gunicorn with `WEB_CONCURRENCY` processes and eight threads
each (`*_PROCESSES` in `.env`, default 2). The proxy finds every replica through Docker's DNS, asked again
every 10 seconds (`resolve` in the upstream blocks of `nginx.conf`, nginx 1.30); the database and the proxy
run once, under their official container names ([ADR 0001](adr/0001-portal-state-in-mongodb.md), step 4).

Both the resolver and the portal validate with the **GS1 Barcode Syntax Engine**: the resolver through the
official Node package `gs1encoder` (every request), the portal through the C library and GS1's Python
binding (data attributes). The portal's own key and qualifier rules mirror the engine and are compared
with it by the tests.

## 2. Repository layout

Files added by the fork are marked **new**; the others are official files with changes.

```
.env.example                     configuration defaults (committed); .env holds installation values
docker-compose.yml               seven services (four with replicas); .env loaded by every service; bind addresses; named volumes
data_entry_server/src/
  data_entry_namespace.py        /summary, token on /index, BearerAuth in Swagger
  data_entry_logic.py            read_summary()
  data_entry_db.py               read_all_documents()
web_server/src/
  web_logic.py                   walk-up, linkType forms, choice of a link, 404 rules, linkset
  web_namespace.py               raw request path, HTML or JSON answers, description file, query string,
                                 /eh… and /ex… requests
  epc_binary.py                  new: EPC binary strings (eh/ex) decoded to GS1 Digital Link
  tdt/                           new: EPC Tag Data Translation 2.2 artefacts (GS1's files, unchanged)
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
  store.py                       the portal's database: connection, indexes, settings, shared lock
  users.py                       user store and roles
  tenants.py                     tenants: organisations that own GS1 Company Prefixes (ADR 0002)
  meta.py                        who created and last changed each record
  journal.py                     history of records and audit trail, retention
  migrate.py                     one-off move of the files of earlier versions into the database
  jobs.py                        background jobs: states, claim, heartbeat, the worker's announcement
  worker.py                      the job worker (portal-worker service, or a thread with PORTAL_WORKER=embedded)
  db_init.py                     creates the portal's database user (portal-db-init service)
  create_user.py                 command-line user administration
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  tools/build-syntax-engine.sh   builds the engine (C library + Python binding)
  assets/fonts/                  Liberation Sans for the label text (OFL)
  Dockerfile, requirements.txt
scripts/                         new: install.sh, templates/, resolver-backup.sh, resolver-backup.cron
dev-tests/                       new: development tests, their pytest layer and the screenshot script
.github/workflows/dev-tests.yml  new: continuous integration (development tests on GitHub Actions)
.github/actions/dev-tests-setup/ new: runner set-up for the tests, with the pinned versions
Documentation/                   README index, user guide, features, history, this guide,
                                 pt-BR/ (these documents in Portuguese), extensions/ (detailed
                                 documentation, changelog), images/, upstream-README.md
tests/, useful_external_python_scripts/   official
```

## 3. Services and configuration

| Service | Build | Port | Volumes | Containers |
|---|---|---|---|---|
| `database-service` | `database_server/` | `${DATABASE_BIND_ADDRESS:-0.0.0.0}:27017` | database data | 1 (`database-server`) |
| `data-entry-service` | `data_entry_server/` (gunicorn) | internal 3000 | — | `DATA_ENTRY_SERVICE_REPLICAS` |
| `web-service` | `web_server/` (gunicorn) | internal 4000 | — | `WEB_SERVICE_REPLICAS` |
| `portal-db-init` | `portal/` (`python db_init.py`, runs once at each start) | — | — | 1 |
| `portal-service` | `portal/` (two stages: syntax engine, application; gunicorn) | internal 8000 | `resolver-portal-config:/app/config` | `PORTAL_SERVICE_REPLICAS` |
| `portal-worker` | `portal/` (`python worker.py`) | — | `resolver-portal-config:/app/config` | `PORTAL_WORKER_REPLICAS` |
| `frontend-proxy-service` | `frontend_proxy_server/` (nginx 1.30) | `${PROXY_BIND_ADDRESS:-0.0.0.0}:8080` | — | 1 (`frontend-proxy-server`) |

Every service reads `.env.example` and then `.env` (Compose ≥ 2.24, `required: false`), so `.env` holds
only what an installation changes. The bind addresses, the replica counts (`*_REPLICAS`) and the process
counts (`*_PROCESSES`, passed to the containers as `WEB_CONCURRENCY`) are read by Compose itself, from `.env`
only. The
variables are described in `.env.example` and in the README's *Configuration* section; the portal also
reads `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD`, `PORTAL_DB_HOST` (or `PORTAL_DB_URI`),
`PORTAL_JOURNAL_*_DAYS`, `PORTAL_SESSION_IDLE_MINUTES`, `PORTAL_SESSION_MAX_HOURS`, `PORTAL_SECRET_KEY`,
`PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT`, `PORTAL_WORKER` and `PORTAL_CONFIG_DIR` (and
`PORTAL_*_FILE`, the files the migration reads). `portal-db-init` alone receives the root `MONGO_URI`; the
portal's and the worker's are blanked. The worker has the portal's settings (it imports `app.py` and runs the
same start-up, which is safe under the shared locks).

## 4. Request flows

**A scan.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. The engine checks the URI; the
resolver reads the document of `/01/09506000134352`, chooses the entry of the qualifier set (walking up to
a less specific entry when there is none), picks the link by `linkType`, language, media type and context,
and answers `307` to it with the scan's query string appended exactly as sent.

**An NFC tag with an EPC.** `GET /eh30164596f40c0e5cbe991a83` (or `/exMBZFlvQMDly-mRqD`) → proxy →
web-service. The single segment matches RE3 of URI Syntax 1.7, so `epc_binary.decompress()` turns it into
`/01/09528765123457/21/123456789123` (plus a query string when the tag carries data attributes); from
there the request is resolved like the scan above, with the decoded attributes in front of the request's
own query string.

**Saving a record in the portal.** The browser sends `POST /portal/api/record` with `key`, `value`,
`qualifiers`, `description` and `links`. `app.py`:

1. checks the session, the role (editor) and the GS1 Company Prefix of the identifier;
2. `build_document()` validates everything with `gs1.py` and builds the Resolver CE v3 document;
3. `store_record()` reads the current document (`GET /api/01/…`) and chooses the calls:
   new entry → `POST /api/new`; existing entry → `PUT` (merge) and then a partial `DELETE` of the targets
   the user removed, in that order so the record is never without targets;
4. `record_change()` updates the record's metadata (`record_meta`) and appends a version to the journal;
5. answers a message code (`save.created`, `save.updated`), translated by the browser.

**Deleting one record of a key.** The API can only delete a whole document, so `delete_record()` deletes it
and writes the other entries back with `POST /api/new`; if that fails, the original document is restored.

**A spreadsheet import.** `POST /import/preview` reads the file (`sheet.py`), validates every row with the
editor's rules, compares with the resolver and keeps the plan as a `prepared` job (30 minutes).
`POST /import/apply` queues it; a worker claims it and `run_import_job()` writes the records one by one with
`store_record()`, storing each result as it goes; the browser polls `GET /import/status`.

**A link check.** `POST /links/check` checks the few targets of one record at once. `POST /links/jobs` (every
record, import preview) queues a job; the worker's `run_link_job()` checks each address once with
`linkcheck.check_many()`; `GET /links/jobs/{token}` reports progress and problems; the last full check is
kept in the database (settings `lastFullCheck`) for `GET /links/last`.

**A background job** ([ADR 0001](adr/0001-portal-state-in-mongodb.md), section 3.3). States `prepared` →
`queued` → `running` → `finished` or `failed`. The worker gives the jobs of silent workers back to the queue
(`requeue_stale()`: heartbeat older than two minutes; after three attempts the job fails with
`job.interrupted`), claims the oldest queued job atomically (`claim()`), and runs it while a thread renews the
heartbeat every 10 seconds. Every write of a running job (`Reporter`) is conditional on the job still being
that worker's; otherwise `JobLost` and the worker lets go. An import continues from the first record not
done (writing a record again is safe); a link check starts again, its cache answering what was done. On
SIGTERM the worker finishes the record in hand and hands the job back at once (`release()`). A queued job
that has waited 15 seconds with no worker announced in the last 30 is reported `stalled`, and the browser
says that the job worker is not running. With `PORTAL_WORKER=embedded` a worker thread runs inside the
portal process (development tests, a minimal installation); the portal wakes it when it queues a job.

## 5. Portal back end (`portal/`)

### `app.py` — the application

Organised in sections (comment lines `# ---- …`):

| Section | Contents |
|---|---|
| configuration | environment, Flask settings (session cookie `gs1resolver_portal`, HttpOnly, SameSite=Lax, Secure over HTTPS, sliding expiry), loggers (`portal`, `portal.audit`); at start-up `migrate.run()`, `journal.apply_retention()`, then the first user from `PORTAL_ADMIN_*` |
| authentication | `LoginThrottle` (5 failures → 15 minutes, per user name and per address, in the `login_failures` collection), `current_user()` with the password fingerprint and `tenant_blocked()`, `set_scope()` and `require_login`, `role_required()`, `admin_required`, `server_admin_required`, `allowed()` / `check_access()` (owner of the identifier = scope of the request, then the user's prefixes), `log_event()` (tenant and `byOperator` of each event), same-origin check for writes, security headers, error handlers |
| resolver API client | `resolver()` (one API call with the token), `read_entries()`, `find_entry()`, `describe_entry()` (product, qualified or other), `record_change()` |
| form → Resolver CE v3 | `request_key()`, `request_qualifiers()`, `build_document()` |
| pages and assets | `/portal/`, `/portal/login`, static files (`PUBLIC_ASSETS` before sign-in, `PRIVATE_ASSETS` after) |
| portal API | sign-in, sign-out, password, health, `/config`, `/record` (GET, POST, DELETE) with `store_record()`, `/records` |
| spreadsheets | `/export`, `/import/preview`, `/import/apply`, `/import/status`, `run_import_job()` (run by the worker) |
| link checker | `/links/check`, `/links/jobs`, `/links/jobs/{token}`, `/links/last`, `run_link_job()` (run by the worker) |
| governance | `/users` (GET, POST, PUT, DELETE, reset) with `managed_account()`; `/tenants` (GET, POST, PUT, DELETE) with `record_owners()`; `/support` (POST, DELETE); `/history`, `/audit`, `/audit.csv` |
| labels | `qr_version()`, `qr_error_level()`, `/digital-link`, `/qrcode` |
| background jobs | `JOB_RUNNERS` (job type → function for `worker.py`); the embedded worker when `PORTAL_WORKER=embedded` |

Errors are exceptions carrying a message code: `gs1.ValidationError` (422), `AccessDenied` (403),
`users.UserError` (422), `UpstreamError` (502/503, detail logged only). Since step 3 of ADR 0001 nothing in
the portal depends on the memory of one process: gunicorn runs `WEB_CONCURRENCY` processes (two by default)
with eight threads each, in every replica. `_secret_key()` writes the fallback `secret.key` to a file of
its own and links it to the final name, so processes starting together all read one complete key.

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

`check_url()` (cached 10 minutes in the `linkcheck_cache` collection, shared by every replica) → `_check()`: follows redirects by hand (at most 5), resolves every host
and refuses private, loopback and link-local addresses at each step, uses `HEAD` and falls back to `GET`
without reading the body, reports HTTPS → HTTP downgrades. `check_many()` runs a thread pool with progress.

### `store.py`, `users.py`, `tenants.py`, `meta.py`, `journal.py` — the portal's database

`store.py` holds one MongoDB client per process (`store.db()`, created and indexed at the first call;
`store.col(name)`), the connection settings (`PORTAL_DB_*`, or `PORTAL_DB_URI`; `mongomock://` for the
development tests), UTC dates (`now()`, `iso()`, `parse_iso()`), values in the `settings` collection
(`get_setting()`, `set_setting()`) and `lock(name)`, an exclusive lock shared by every process (a document
`lock:<name>` in `settings`; a lock older than `hold_seconds` is broken). `users.py` writes under the
`users` lock, so two administrators cannot remove the last enabled one at the same moment; it also hashes
passwords (Werkzeug), spends the same time for unknown users, and computes the session fingerprint.
`users.py` also keeps a user's tenant and e-mail address (`clean_email()`, unique), checks that a tenant
user's prefixes lie inside the tenant's and an operator user's outside every tenant's (`_check_scope()`), and
counts only operator administrators as server administrators (`is_server_admin()`). `tenants.py` creates,
changes and removes tenants under the same `users` lock (the rules cross both collections:
`_check_prefixes()`), and answers `owner(anchor, tenants)`, the tenant that holds an identifier's prefix
([ADR 0002](adr/0002-tenants.md)). `meta.py` keeps creation and last change per record, with the tenant that
made it (`visible()` hides it from other scopes). `journal.py` stores one document per event with its category
(`session`, `record`, `admin`), its `tenant` and `byOperator`, and `expiresAt`; `for_record()` (per scope) and
`search()` (with `scope_query()`) keep the output of the former `journal.jsonl` lines; `apply_retention()`
updates `expiresAt` when `PORTAL_JOURNAL_*_DAYS` change. Section 8 lists the collections.

**Scope of a request (ADR 0002).** `set_scope()` puts on `g` the account (`user`, `account_role`,
`account_tenant`, `server_admin`), every tenant (`tenants`, read once per request) and what applies: `tenant`
(the user's tenant, the tenant of an open support access, or `None` for the operator), `role` and `prefixes`
(reader and the whole tenant during support access), `support`. `allowed()` admits an identifier whose owner
is `g.tenant` and that lies in `g.prefixes`. The worker calls `set_scope()` for the user of an import and
checks `allowed()` again before writing each record.

### `jobs.py`, `worker.py`

`jobs.py` is the queue: `create()`, `get()` (the user's job of a type, not expired), `queue_prepared()`,
`status()` (state, progress, `stalled`, `error`), and for workers `announce()` / `withdraw()` /
`workers_alive()`, `requeue_stale()`, `claim()`, `Reporter` (`beat()`, `progress()`, `record()`,
`check_stop()`, `finish()`), `release()`, `fail()`. Timings are constants at the top (`HEARTBEAT_SECONDS` 10,
`STALE_SECONDS` 120, `MAX_ATTEMPTS` 3, `WORKER_ALIVE_SECONDS` 30, `STALLED_SECONDS` 15, expiries 30 minutes
and one day). `worker.py` has `Worker` (`run_once()`, `loop()`, `stop()`), `start_embedded()`, `wake()` and
`main()` (the service: SIGTERM and SIGINT stop it after the item in hand); `IN_WORKER_PROCESS` keeps
`app.py` from starting an embedded worker inside the worker process.

### `migrate.py`, `db_init.py`

`migrate.run(config_dir)` moves `users.json`, `records-meta.json` and `journal.jsonl` into empty collections
once, under the `migration` lock, with fixed `_id`s so that an interrupted import finishes at the next
start; the files become `*.migrated`. `db_init.py` (the `portal-db-init` service) connects with the root
`MONGO_URI` and creates the portal's user, or updates its password and roles; it refuses `admin`, `local`,
`config` and `resolver_ce` as the portal's database.

### `create_user.py`

`docker compose exec portal-service python create_user.py <name> [--role …] [--prefixes …] [--tenant …] [--email …] [--remove]`
creates a user or sets a password (asked twice), role, prefixes and e-mail, or removes a user. `--tenant`
(name or id) puts a new user in an organisation; without it the user is the operator's.

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
call checks the role and limits identifiers to the scope of the request (the user's tenant, a support
access, or the operator) and to the user's GS1 Company Prefixes. Errors answer `{"code": "...", "params": {...}}`.
"admin" below means a tenant administrator or a server administrator; "server admin" an administrator of the
operator.

| Method and path | Role | Purpose |
|---|---|---|
| `POST /login` `{username, password}` | — | Sign in (429 `auth.locked` when throttled) |
| `POST /logout` | — | Sign out |
| `POST /password` `{currentPassword, newPassword}` | any | Change password; other sessions end |
| `GET /config` | any | User, role (the one that applies), `accountRole`, `serverAdmin`, `tenant` and `support` (`{id, name, disabled}` or `null`), prefixes, resolver address, link types, keys with qualifiers and shapes, languages, import limits, data attributes, session limits (`session`: `idleSeconds`, `warningSeconds`, `endsIn`, `maxHours`) |
| `GET /session` | any (also while a new password is due) | Renews the session; answers the same session limits |
| `GET /record?key=&value=&qualifiers=/10/L1` | reader | One record: `exists`, `description`, `links`, `defaultLinkType`, `sharedDefaultLinkType`, `digitalLink`, `otherEntries` (each with `informative`), `qualifiers` (the record's own), `informative` (typed) and `storedInformative`, `hasKeyRecord` |
| `POST /record` `{key, value, qualifiers, description, links:[{linkType, url, title, hreflang, forwardQueryString}], keyRecord?}` | editor | Create (201) or replace (200); the first link is the default. With a serial number, 22 and 10 in `qualifiers` are stored as informative. `keyRecord: {mode: copy\|target, description, url}` also creates the key's own record first (`save.createdWithKey`, `keyRecordCreated`) |
| `DELETE /record?key=&value=&qualifiers=` | editor | Delete one record, keeping the others of the key |
| `GET /records` | reader | Every record with kind, qualifiers, `informative`, description, default link type, number of links, created/updated by and when, `noKeyRecord`, `breaksRules` |
| `POST /export` `{format: xlsx\|csv, labels}` | reader | Spreadsheet of every record |
| `POST /import/preview` `{filename, data (base64), labels, checkLinks}` | editor | Validation and comparison; `token`, `records` (with `informative`, `informativeBefore`, `noKeyRecord`), `errors`, `counts`, `links`, `keysWithoutRecord` |
| `POST /import/apply` `{token, createKeyRecords?}` · `GET /import/status?token=` | editor | Queue a previewed import for the worker (with `createKeyRecords`, the keys' own records first); `state` (`queued`, `running`, `finished`, `failed`), `done`, `total`, `stalled`, `error`, and the results when finished |
| `POST /links/check` `{urls}` | editor | Check addresses (editor) |
| `POST /links/jobs` `{scope: all\|urls}` · `GET /links/jobs/{token}` · `GET /links/last` | editor · editor · reader | Background link check (status: `state` `queued`\|`running`\|`finished`\|`failed`, `done`, `total`, `stalled`, `error`) |
| `GET /history?key=&value=&qualifiers=` | reader | Versions of a record made in the scope of the request, with content |
| `GET /users` · `POST /users` `{username, role, prefixes, email, tenant}` · `PUT /users/{name}` `{role, prefixes, email, disabled}` · `POST /users/{name}/reset` · `DELETE /users/{name}` | admin | User administration: a server admin manages every user (`tenant` chooses the organisation; the answer to GET adds `tenants`), a tenant administrator the users of his tenant; `tenantName` on each user; temporary passwords in the answer |
| `GET /tenants` · `POST /tenants` `{name, prefixes}` · `PUT /tenants/{id}` `{name, prefixes, disabled}` · `DELETE /tenants/{id}` | server admin | Organisations; GET adds `users` and `records` per tenant and `operatorRecords` |
| `POST /support` `{tenant, reason}` · `DELETE /support` | server admin | Open and close read-only support access to a tenant, recorded in its audit trail |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | admin | Audit trail of the scope: a tenant's; the operator's plus what operator users did to tenants; a tenant's during support access. Events carry `tenant`, `tenantName`, `byOperator`; the CSV adds `organisation` and `by_operator` |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | reader | Digital Link with data attributes checked by the engine; nothing stored |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:value` | reader | Label; headers `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`; 422 `qr.tooSmall` / `qr.tooLong` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable", "worker": "ok"\|"unavailable"}` |

## 8. Portal data

The portal's database (`PORTAL_DB_NAME`, default `resolver_portal`), included in the daily MongoDB dump.
Decisions and the reasons for them: [ADR 0001](adr/0001-portal-state-in-mongodb.md).

| Collection | `_id` and content | Indexes |
|---|---|---|
| `users` | user name; `hash`, `role`, `prefixes`, `tenant` (absent for the operator's users), `email` (optional), `disabled`, `mustChange`, `created`, `lastLogin` | — |
| `tenants` | `t-` + 12 hexadecimal digits; `name`, `prefixes`, `disabled`, `created`, `createdBy` ([ADR 0002](adr/0002-tenants.md)) | — |
| `record_meta` | record key (GTIN records by the 14 digits, other keys by `AI/value`, plus the qualifier path); `createdAt`, `createdBy`, `updatedAt`, `updatedBy`, `tenant` (absent for the operator) | — |
| `journal` | ObjectId (`jsonl-<line>` for migrated events); `at` (date), `user`, `action`, `category`, `tenant` (absent for the operator), `byOperator`, `anchor`, `qpath`, `doc`, `detail`, `expiresAt`. Record actions `create`, `update`, `delete` (with the record's content), `import`; others `login`, `login-failed`, `login-refused`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove`, `tenant-create`, `tenant-update`, `tenant-remove`, `support-open` (the reason in `detail`), `support-close` | date; record + date; user + date; tenant + date; category; TTL on `expiresAt` |
| `login_failures` | `key` (`user:<name>` or `addr:<address>`), `at` | key + date; TTL 15 minutes on `at` |
| `linkcheck_cache` | address; `result`, `expiresAt` | TTL on `expiresAt` |
| `jobs` | token; `type` (`import`, `linkcheck`), `user`, `state`, `created`, `queuedAt`, `startedAt`, `finishedAt`, `heartbeat`, `worker`, `attempts`, `done`, `total`, `expiresAt`, `error`; imports `plan`, `keyRecords`, `results`; link checks `scope`, `urls` (`[{url, records}]`), `problems`, `records` (`[{record, problems}]`) | state + creation; TTL on `expiresAt` |
| `workers` | worker name (`host:pid:mode`); `seen`, `mode`, `job` | TTL 10 minutes on `seen` |
| `settings` | `lastFullCheck` (the operator's) and `lastFullCheck:<tenant>`, `journalRetention`, `migration`, and the `lock:<name>` documents | — |

Journal retention: an event is kept for `PORTAL_JOURNAL_SESSION_DAYS` (180), `PORTAL_JOURNAL_RECORD_DAYS` (0)
or `PORTAL_JOURNAL_ADMIN_DAYS` (0) days from the end of the day it was made; 0 keeps it for ever.

The `resolver-portal-config` volume (`/app/config`, in the daily backup) keeps `secret.key`, the session key
used when `PORTAL_SECRET_KEY` is not set (shared by every portal process and replica on the same Docker host,
which mount the same volume), and the files of earlier versions renamed `*.migrated`.

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
  level. `format_linkset_for_external_use()` writes every link type key through `public_linktype_key()`, so
  clients see the `gs1:` namespace of section 2.14 (`GS1_VOC`, `https://ref.gs1.org/voc/`) while documents
  keep `https://gs1.org/voc/` keys, which `_find_linktype_key()` and the data entry code use. `_test_gs1_digital_link_syntax()` sends `https://id.gs1.org` + the encoded path to
  `callGS1encoder.js`, which uses the engine's Digital Link parser (`dataStr`) for a URI and keeps
  `aiDataStr` for an element string.
- `web_namespace.py`: `_request_segments()` and `_resolve_path()` (the path from the raw request URI,
  `RAW_URI`, each segment decoded on its own, so `%2F` stays in its value), `_extract_query_strings()` (the
  raw query string), `_wants_html()` (browser, API client, or no `Accept` header: HTML),
  `_resolver_description()` (description file from `FQDN`, `RESOLVER_*` and `RESOLVER_TERMS_URL`, without
  `_id`), `_bad_request()`, `_append_query()` (query string joined with `&`), the 300 as a linkset or a page,
  `_latin1()` (safe `Location` headers), trailing slash accepted.
- `web_namespace.py`, item 1.6: `_handle_request()` sends a segment matching
  `epc_binary.COMPRESSED_EPC` (RE3) to `_resolve_compressed_epc()`: decode, check the data attributes with
  the path through `_test_gs1_digital_link_syntax()` (`_SAFE_GS1_PATTERN` admits `?`, `=`, `&` for this),
  then `_process_response()` with the decoded attributes followed by the request's query string; an
  `EpcDecodeError` answers 400 with its reason. Other single segments still go to the official toolkit
  (legacy compression of Digital Link 1.1).
- `epc_binary.py` (new, item 1.6), from EPCB 1.0.0, TDS 2.3 and TDT 2.2:
  - `compression_bits()` (`eh`: 4 bits per character; `ex`: 6 bits, RFC 4648 section 5 alphabet);
    `decode_binary()` picks the scheme by the 8-bit header (`prefixMatch` of the BINARY level; the `++`
    headers of `PLUS_PLUS` map to their `+` scheme); `decompress()` does both. The result, `DecodedEpc`, gives
    `path()` (primary key and its `gs1DigitalLinkKeyQualifiers` in order, values percent-encoded),
    `query()` (every other AI) and `uri(stem)`, plus the scheme, filter value, toggle bit and hostname.
  - Schemes before TDS 2.0, `_decode_tdt_scheme()`: the BINARY option whose `pattern` matches; each field
    as an integer or, with `compaction`, characters (`_decode_characters()`); padding from the output
    level or else the tag-encoding level (TDT figure 3-6); EXTRACT rules of BINARY and FORMAT rules of
    GS1_DIGITAL_LINK (`_call_rule()`: SUBSTR, CONCAT, GS1CHECKSUM, URL/URN encodings); the level's
    `grammar` filled in and read back as AI/value pairs. Nothing scheme-specific is in the code.
  - `+` and `++` schemes, `_decode_plus_scheme()`: toggle, filter and DSGTIN+ date from the artefact; the
    values of `encodedAI` with `_ai_value()` (Table F row → `_component()`, one branch per method of TDS
    14.5); `_hostname()` for `++` (URN Code 40 or 7-bit with the optimisation tables `_HOST_TABLE_A` and
    `_HOST_TABLES_B`, transcribed from TDS Tables 14-11 to 14-15); `_aidc_data()` for what follows (TDS
    15.3: Table K for the AI length, stop on fewer than 8 bits or a zero header with fewer than 72 bits).
  - Strictness: bits after the data must be zero, values must be plausible (dates, digits, character sets,
    lengths), an AI may appear once. Final AI-level checks (associations, formats) are left to the GS1
    Barcode Syntax Engine in the web server.
  - `tdt/` holds GS1's files as published (2024-11-18 drafts for TDT 2.2), with `+` in the names as in
    the manifest; to update, replace the files and run `dev-tests/resolver/test_epc_binary.py`.
    `TDT_DIR` points elsewhere if needed.
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
`proxy_pass http://resolver-web/api$request_uri`, so that `%2F` and the query string arrive as sent; the upstream's
name is also the Host header the web server receives, so it must be a valid host name), `/api` and
`/swaggerui` to data-entry-service, and `/portal/` to portal-service (with `/portal` → `/portal/`).
Each service is an upstream block (`resolver-web`, `data-entry`, `portal`) whose server is the service name
with `resolve` and a shared `zone`: nginx asks Docker's DNS (`resolver 127.0.0.11 valid=10s`) for every
replica's address, again every 10 seconds, shares the requests among them in turn, and goes on to another
replica when one refuses the connection. It starts even while a service has no address yet (that service's
paths answer 502 until it has). This needs nginx 1.27.3 or later; the image is `nginx:1.30-alpine`
(rebuilt with `docker compose build --pull` to take a new security release of the 1.30 branch).
`home/home.js` reads the operator from `/.well-known/gs1resolver` and shares the language choice with the
portal.

## 12. Scripts (`scripts/`)

- `install.sh`: installer for Ubuntu 22.04/24.04 (checks, questions with earlier values as defaults,
  Docker, host nginx with Certbot or an existing certificate or an external proxy, `.env` with generated
  secrets and the replica counts — not asked; 1, the environment or the existing `.env`, 1 to 20 —,
  start-up, backup cron). Safe to re-run; `--non-interactive` reads every answer from
  environment variables. Templates of the nginx site in `templates/`.
- `resolver-backup.sh` + `resolver-backup.cron`: MongoDB dump through the container (every database, the
  portal's included) and archive of the portal volume, 14 days kept.

## 13. Development tests (`dev-tests/`)

No Docker needed; each program exits with status 1 on a failure. The portal programs use `mongomock`
(`PORTAL_DB_URI=mongomock://`, one database per program); with `PORTAL_DB_URI` set to a real MongoDB they
run against it. Setup and commands are in
`dev-tests/README.md`.

| Program | Checks | Covers |
|---|---:|---|
| `resolver/test_resolver.py` | 194 | resolver and data entry code through Flask's test client: every key and qualified record, walk-up, link types, 404 rules, linkset schema, attributes passed on, description file schema, HTML pages, `/eh…` and `/ex…` requests |
| `resolver/test_epc_binary.py` | 163 | EPC binary decoder: EPCB examples, every vector of TDS 2.3 annex E.3 (`eh` and `ex`), +AIDC data, `++` hostnames, refusals, RE3, TDT artefacts against their schema; 800 random EPCs against `epc-tds` when `EPC_TDS` is set (162 without) |
| `resolver/test_gs1_suite.py` | 215 | GS1's resolver test suite, its JavaScript unchanged in Chromium, against the web server code over HTTP; a Python version of its `tester.php`; seven scenarios; needs `GS1_RESOLVER_TESTSUITE` and `AJV_DIST` (skipped without) |
| `resolver/test_data_entry_api.py` | 53 | token on every protected operation; registration rules of §2.5.9 and informative qualifiers |
| `portal/test_keys.py` | 137 | keys and qualifiers, compared with the GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | roles, prefixes, users, history, audit |
| `portal/test_sheet.py` | 43 | spreadsheets, limits per format |
| `portal/test_special_chars.py` | 57 | special characters |
| `portal/test_data_attributes.py` | 83 | data attributes, decimal families, QR options (needs `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | link checker, SSRF guard |
| `portal/test_portal_config.py` | 13 | configuration and start-up, session limits |
| `portal/test_session.py` | 30 | session limits (15 s idle in the test): server rules, warning, renewal on use, other tabs, absolute limit, both languages; community notice in the footer (about two minutes) |
| `portal/test_store.py` | 58 | the portal's database layer: connection settings, indexes, the shared lock (also between two administrators at once), users, record metadata, journal and its retention, sign-in throttle, migration of the old files (also interrupted and resumed) |
| `portal/test_tenants.py` | 82 | tenants ([ADR 0002](adr/0002-tenants.md)): an installation without tenants unchanged; tenants and their prefixes (names, overlaps, redundancy, operator users in the way); the operator's records and users; tenant administrators and their users; e-mail addresses; records, history, record list, export and imports per tenant, and the worker's check before each record; prefixes moving between owners; the audit trail per tenant and its CSV; support access; disabled and removed tenants; link check results per scope; ownership by key type; the command line; the messages of both languages (same keys, every key of the page and every message code of the server translated) |
| `portal/test_jobs.py` | 70 | background jobs: states, expiry, atomic claim, ownership of writes, silent workers given back and failed after three attempts, the worker's announcement, `stalled`, the health check, the worker loop (errors, heartbeat, stop and hand-back, `JobLost`), the embedded worker and `PORTAL_WORKER`; imports through the API (queue, worker, journal, another user, a worker dying before and after writing a record, a failure); link checks through the API (every record, a list, a stop that cancels pending addresses) |
| `portal/test_worker_processes.py` | 13 | `worker.py` as real processes on a real MongoDB (run by `test_store_mongodb.py`): two workers share the queue without taking a job twice; SIGTERM hands the job back and the other worker finishes it; after SIGKILL a new worker continues the job once its heartbeat is old |
| `portal/test_store_mongodb.py` | 161 | on a real MongoDB (`PORTAL_TEST_MONGO_URI`, CI only): the user made by `db_init.py` and its privileges; `test_store.py`, `test_jobs.py` and `test_worker_processes.py` again as that user (their lines relayed); the TTL monitor, also for jobs and old worker announcements |
| `portal/test_registration.py` | 26 | §2.5.9 through the portal API: informative qualifiers (save, open, history, list, export, import), records against rule 2, the key's own record when saving and importing |
| `portal/test_portal_e2e.py` | 208 | the portal in Chromium against `mock_data_entry.py`, desktop and phone, with an embedded worker (also stopped: the queue and "not running" messages, a job that fails); organisations, a tenant administrator and support access in both languages; also run without the engine (164) |
| `home/test_home.py` | 68 | home page through a real nginx (1.27.3 or later: `NGINX_BIN` or the PATH), no syntax box, community notice; proxy routes, including that the Host header sent to each upstream is one Werkzeug accepts; replicas through a stub DNS server answering the service names with `127.0.0.x` addresses: nginx starts while a service has no address and finds it later, shares the requests between two replicas, follows a third added and two removed without a restart, and no request fails while replicas stop |
| `install/test_install.sh` | 68 | installer through shims (Compose v2), including a portal whose job worker does not start; replica counts written, kept, taken from the environment and refused when invalid |
| `install/test_deploy.py` | 51 | `docker compose config` of the replicas and process counts (defaults, values from `.env`, a refused value, names kept by the database and the proxy); the proxy image's nginx version and `resolve` in every upstream; each image's gunicorn `CMD` started locally (three processes, an answer, the request logged, a clean stop on SIGTERM within 10 s); the portal's fallback session key with six processes starting together and eight threads while writing it is slow |

**pytest and continuous integration.** `dev-tests/test_programs.py` runs each program above as one pytest
test (a subprocess from the repository root): exit status 0 without a `FAIL` line passes; otherwise the
report shows the `FAIL` lines and the end of the output; a program that only printed `SKIP` is skipped.
Markers group them: `resolver` (resolver, EPC binary, data entry, GS1 suite), `portal` (the portal programs
without a browser), `e2e` (`test_portal_e2e.py` with and without the engine, `test_session.py`), `home`,
`install` (the installer through password-less `sudo` when not root, and `test_deploy.py`), `database` (`test_store_mongodb.py`). `dev-tests/conftest.py` keeps the programs from
being imported by pytest, registers the markers and prints the check counts of each program at the end (and
in the GitHub Actions run summary). With `DEV_TESTS_STRICT=1` a program fails when an environment variable
it needs is not set or names a missing path (`needs_env`), when a variable that is not a path is not set
(`needs_var`), when a command it needs is not on the PATH, or when it prints `SKIP`. To add a program: write
it with `PASS`/`FAIL` lines and an exit status, add a `Program(...)` line to `PROGRAMS` (group, path, the
variables and commands it needs), and a row to the table above.

`.github/workflows/dev-tests.yml` runs one job per group in parallel on every push and pull request to
`gs1br/develop` (not for changes to `Documentation/` or Markdown files only), in strict mode. The `database`
job starts a `mongo:7` service container and runs the `portal` and `database` groups on it. `database` is
informative (`continue-on-error`) until it proves stable; `e2e` and `install` started that way and are
required since step 4 of item 2.3. The composite action
`.github/actions/dev-tests-setup` installs only what a job asks for and exports the variables: Python 3.12
and Node.js 24 as in the images; `gs1encoder`, `epc-tds` and `ajv-dist` at pinned versions (cache keyed by
the versions); the portal's engine built by `portal/tools/build-syntax-engine.sh` (cache keyed by the
script, which pins the release); Chromium (cache keyed by the Playwright version); GS1's suite at commit
`32597c1`; Ubuntu's nginx for the installer, nginx 1.30.5 from nginx.org for the proxy test; Docker
Compose v2.29.7. Change a version there, in one place; keep `gs1encoder` on the
release the script builds.

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

**An EPC scheme or a new TDT release.** Copy the new definition files and tables into
`web_server/src/tdt/` (keeping `+` in the names) and update `manifest.json`; schemes before TDS 2.0 then
need no code. A `+` scheme needs code only for a Table F format or TDS 14.5 method that `_component()`
does not know; a `++` scheme only an entry in `PLUS_PLUS` while TDT has no artefact for it. Add its TDS
annex E vector to `test_epc_binary.py`.

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
