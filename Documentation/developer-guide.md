# Developer guide

How the GS1 Digital Link Resolver CE — Expansion Pack is built: the services, every source file written or
changed by the fork, the portal's API and data files, the tests, and how to extend it. Read it together
with the docstrings in the code, which describe each function, and with the
[extensions documentation](extensions/README.md), which records the detailed rules and design decisions.

For installation and configuration see the [README](../README.md); for using the portal, the
[user guide](portal-user-guide.md).

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
binding (data attributes). **One release for all of them**, written once in `docker-compose.yml`
(`x-gs1-syntax-engine`) and given to every image as the build argument `GS1_SYNTAX_ENGINE_RELEASE`
([ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md)); the data entry API installs the same package. The
portal's own key and qualifier rules mirror the engine and are compared with it by the tests.

## 2. Repository layout

Files added by the fork are marked **new**; the others are official files with changes.

```
.env.example                     configuration defaults (committed); .env holds installation values
docker-compose.yml               seven services (four with replicas), plus mailpit in the mail-test profile; .env loaded by every service; bind addresses; named volumes
data_entry_server/src/
  data_entry_namespace.py        /summary, token on /index, BearerAuth in Swagger
  data_entry_logic.py            read_summary()
  data_entry_db.py               read_all_documents()
web_server/src/
  web_logic.py                   walk-up, linkType forms, choice of a link, 404 rules, linkset
  web_namespace.py               raw request path, HTML or JSON answers, description file, query string,
                                 /eh… and /ex… requests
  epc_binary.py                  new: EPC binary strings (eh/ex) decoded to GS1 Digital Link
  request_log.py                 new: the log of resolver requests: what is kept, a queue and a writer thread (ADR 0006)
  domains.py                     new: organisations' own domains: stem removed, keys limited to their prefixes (ADR 0009)
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
  label.py                       labels: QR code and an EAN/UPC beside it, sizes; SVG, PNG, PDF, ZIP (ADR 0010)
  linear.py                      EAN-13, UPC-A, EAN-8 and UPC-E encoding (ADR 0010)
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
  mail.py                        outgoing e-mail through an SMTP relay; "python mail.py test <address>" (ADR 0004)
  mailtexts.py                   the texts of the e-mail messages, in both languages
  tokens.py                      single-use links: invitations and password recovery
  notify.py                      notifications: categories, the user's choices, the "mail" job
  apikeys.py                     API keys of the tenant API: creation, hash, revocation, request limit (ADR 0005)
  api_v1.py                      the tenant API, /portal/api/v1 (imported at the end of app.py), its calls logged
  requestlog.py                  the request log as the portal reads it: scope, listing, daily counts, API calls (ADR 0006)
  overview.py                    the overview's indicators and their exports (ADR 0007)
  monitor.py                     monitoring: the checks, their states and the alerts by e-mail (ADR 0008)
  domains.py                     organisations' own domains: rules, DNS proof, defaults, label address, checks (ADR 0009)
  openapi.json                   its OpenAPI 3.1 description, served at /portal/api/v1/openapi.json
  db_init.py                     creates the portal's database user (portal-db-init service)
  create_user.py                 command-line user administration
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  gs1dict.py                     the GS1 Barcode Syntax Dictionary: parser, gs1_dictionary.json reader (ADR 0003)
  gs1_dictionary.json            the dictionary of the engine release in docker-compose.yml, generated
  engine_messages.py             recognises the engine's messages as message codes (translated in i18n.js)
  engine_messages.json           the engine's message templates and linters' messages, generated
  tools/build-syntax-engine.sh   builds the engine (C library + Python binding, dictionary, message sources)
  tools/gen_dictionary.py        writes (or --check) gs1_dictionary.json from an engine build
  tools/gen_engine_messages.py   writes (or --check, --summary) engine_messages.json from an engine build
  tools/dictionary_diff.py       what changes between two generated dictionaries (the weekly issue)
  assets/fonts/                  Liberation Sans for the label text (OFL)
  Dockerfile, requirements.txt
scripts/                         new: install.sh, templates/, resolver-backup.sh, resolver-backup.cron
dev-tests/                       new: development tests, their pytest layer and the screenshot script
.github/workflows/dev-tests.yml  new: continuous integration (development tests on GitHub Actions)
.github/actions/dev-tests-setup/ new: runner set-up for the tests, with the pinned versions
Documentation/                   README index, user guide, features, history, this guide,
                                 extensions/ (detailed documentation, changelog), images/,
                                 upstream-README.md
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
| `mailpit` | image `axllent/mailpit`, profile `mail-test` only (a test relay, [ADR 0004](adr/0004-e-mail.md)) | `127.0.0.1:8025` (its pages and API) | — | none unless started with `--profile mail-test` |

Every service reads `.env.example` and then `.env` (Compose ≥ 2.24, `required: false`), so `.env` holds
only what an installation changes. The bind addresses, the replica counts (`*_REPLICAS`) and the process
counts (`*_PROCESSES`, passed to the containers as `WEB_CONCURRENCY`) are read by Compose itself, from `.env`
only. The
variables are described in `.env.example` and in the README's *Configuration* section; the portal also
reads `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD`, `PORTAL_DB_HOST` (or `PORTAL_DB_URI`),
`PORTAL_JOURNAL_*_DAYS`, `PORTAL_SESSION_IDLE_MINUTES`, `PORTAL_SESSION_MAX_HOURS`, `PORTAL_SECRET_KEY`,
`PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT`, `PORTAL_WORKER`, `PORTAL_CONFIG_DIR` (and
`PORTAL_*_FILE`, the files the migration reads) and, for e-mail, `PORTAL_MAIL_HOST`, `PORTAL_MAIL_PORT`,
`PORTAL_MAIL_SECURITY`, `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD`, `PORTAL_MAIL_FROM`,
`PORTAL_MAIL_REPLY_TO`, `PORTAL_MAIL_CA_FILE`, `PORTAL_MAIL_TIMEOUT`, `PORTAL_INVITE_HOURS` and
`PORTAL_RESET_MINUTES`, for the tenant API `PORTAL_API_RATE_PER_MINUTE` and `PORTAL_API_KEY_MAX_DAYS`, for the
request log `RESOLVER_LOG_DAYS`, `PORTAL_TIME_ZONE` and `PORTAL_STATS_DAYS`, and for monitoring `PORTAL_MONITOR_*` and
`PORTAL_ALERT_404_*` (ADR 0008). The resolver reads `RESOLVER_LOG_DAYS` and
`RESOLVER_LOG_COUNTRY_HEADER` and writes its log with the root `MONGO_URI` it already has. `portal-db-init` alone
receives the root `MONGO_URI` on the portal's side; the portal's and the worker's are blanked. The worker has the portal's settings (it imports `app.py` and runs the
same start-up, which is safe under the shared locks).

## 4. Request flows

**A scan.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. The engine checks the URI; the
resolver reads the document of `/01/09506000134352`, chooses the entry of the qualifier set (walking up to
a less specific entry when there is none), picks the link by `linkType`, language, media type and context,
and answers `307` to it with the scan's query string appended exactly as sent.

**The request's event** ([ADR 0006](adr/0006-resolver-request-log.md)). Every resolution route calls
`request_log.note()` with what it knows (form, key, qualifiers, query string, link type asked, languages, the level
that answered and, for a 404, whether no record applied or no link of the type); `web_logic.read_document()` passes
the last two in the private keys `_level` and `_outcome`, which `_process_response()` removes before answering. The
application's `after_request` hook (`request_log.record()`) adds status, target host, time taken, device class,
referrer host and country, and puts the event in the process's queue; the writer thread inserts batches into
`resolver_log.requests`. The worker's hourly housekeeping (`requestlog.aggregate()`) counts each day into
`request_daily`.

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

- **Built from the dictionary** ([ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md)): `_build()` reads
  `gs1_dictionary.json` (`gs1dict.load()`) at import. `PRIMARY_KEYS`: AI → (name, validator) for every AI with
  `dlpkey` (the 16 keys of URI Syntax 1.7 §4.3), in the order and with the short names of
  `PORTAL_EXCEPTIONS["key_names"]` (a key added by a later dictionary comes last, under its title).
  `key_validator()` chooses the validator from the shape of the key's components and their linters
  (`_numeric_key`, `_itip`, `_digits_with_serial`, `_with_serial`, `_alnum_key`, `_gmn` with
  `gmn_check_pair()`, `_cpid`, `_gtin` for `short_gtin`), with the dictionary's lengths, and gives it a `.spec`
  the browser repeats. `qualifier_pattern()` makes each qualifier's pattern from its components. Only
  `KNOWN_LINTERS` are accepted: anything else raises `gs1dict.DictionaryError` at import.
- `PORTAL_EXCEPTIONS`: what the portal deliberately does differently, each with its reason (character sets of
  keys, qualifiers and CPID; ITIP without 22; short GTINs; key names). `browser_rules()`: the checks, patterns,
  maximum lengths and order sent to the browser in `/config` (`rules`).
- `KEY_SHAPES`: for each key, the alternative qualifier sets allowed together and which are required (from
  `dlpkey`: a later alternative is told apart by its first qualifier; a qualifier in the key's `req` is
  required); `QUALIFIER_FORMATS` and `QUALIFIER_ORDER`, `normalise_qualifiers()` (format, combination and the order
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
`GS1_SYNTAX_ENGINE_DIR` (built by `tools/build-syntax-engine.sh` at the release of `docker-compose.yml`). Without it `available` is
false and the option is hidden. From the engine's Syntax Dictionary (`parse_dictionary()`) it builds the
attributes allowed in a query string (AIs flagged `?`), the families of decimal AIs (`decimal_families()`,
`310n`…) and the AIs that belong in each key's path. `describe()` feeds `/config`; `resolve_decimal()`
converts `123,45` for a family; `digital_link()` checks the attributes of a record (day 00, duplicates,
AIs of the path refused, then the engine's own linters and association rules) and returns the URI and the
HRI lines, or raises `ValidationError` with a message code. Calls to the engine are serialised by a lock.
The engine's other refusals are `attr.invalid` with its English text in `detail` and, when
`engine_messages.recognise()` knows the text, `message`: `{code: "engine.<CODE>", params: {p1, p2…}}`, a linter's
message inside it being `engine.lint.<CODE>`. `i18n.js` holds both languages of every engine message (the English
one is the engine's text) and shows the translation in place of `detail`.

### `label.py` — QR code labels

`LabelOptions` (URI, HRI lines, show HRI, version, level, `size` — a percentage of the target X-dimensions, one of
`SIZES` —, `linear` — `(kind, digits)` from `linear.symbol_for()` or None) → `symbol()` (segno, `micro=False`,
`boost_error=False`; `DoesNotFit` with the needed version and fitting level) → `_layout()`: a list of dark
rectangles and text lines in units of the QR module (modules as runs, quiet zone of 4, text 2.2 mm whatever the
size, then `_place_linear()` to the right: quiet zones, bars of 0.330/0.495 QR modules per linear module, guard bars
5X longer, digits) → `render_svg()` (millimetres at X = 0.495 mm × size, text as glyph outlines), `render_png()` (12
pixels per QR module, 8 per linear module; DPI from X), `render_pdf()` (one page, rectangles and glyph outlines through
`_PdfPen`, a fontTools pen giving PDF path operators; a FlateDecode content stream, written without a library) and
`render_zip()` (the three and `README.txt`). [ADR 0010](adr/0010-label-studio.md).

### `linear.py` — EAN/UPC symbols

`symbol_for(gtin14, "auto"|"upce")` chooses EAN-8 (six leading zeros), UPC-A (two), EAN-13 (one) or UPC-E (a GTIN-12
that `upce_from_upca()` zero-suppresses, number system 0), raising `NotPossible` otherwise; `encode(kind, digits)`
checks the check digit and gives `Encoded`: the modules from the L/G/R tables and the parity tables (EAN-13's by its
first digit, UPC-E's by its check digit), the extended modules, quiet zones, bar height and the digits with their
centres and relative sizes. `app.label_size()`, `app.label_linear()` read `size=` and `linear=` (`label.sizeInvalid`,
`label.linearInvalid`, `label.linearNotPossible`); `label_response()` adds `format=pdf|zip` and the header
`X-Linear-Symbol`; `zip_name()` keeps the names inside a zip to safe characters.

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
`workers_alive()`, `requeue_stale()`, `claim()` (the oldest queued job whose `notBefore`, if any, has
passed), `Reporter` (`beat()`, `progress()`, `record()`, `check_stop()`, `finish(remove=…)`, `defer(seconds)`
— back in the queue for later, raising `Deferred` —, `give_up(code)`), `release()`, `fail()`. The types are
`import`, `linkcheck` and `mail`. Between jobs, about once an hour (`HOUSEKEEPING_SECONDS`), the worker
runs `app.HOUSEKEEPING` (`Worker.housekeep()`; a failing task is logged and the others run): today
`notify_expiring_keys()` and `requestlog.aggregate()`; and every `monitor_seconds` (`app.MONITOR_SECONDS`, from
`PORTAL_MONITOR_MINUTES`; 0: never) `app.MONITORING`, today `monitor.run()`. Timings are constants at the top (`HEARTBEAT_SECONDS` 10,
`STALE_SECONDS` 120, `MAX_ATTEMPTS` 3, `WORKER_ALIVE_SECONDS` 30, `STALLED_SECONDS` 15, expiries 30 minutes
and one day). `worker.py` has `Worker` (`run_once()`, `loop()`, `stop()`), `start_embedded()`, `wake()` and
`main()` (the service: SIGTERM and SIGINT stop it after the item in hand); `IN_WORKER_PROCESS` keeps
`app.py` from starting an embedded worker inside the worker process.

### `mail.py`, `mailtexts.py`, `tokens.py`, `notify.py` — e-mail

[ADR 0004](adr/0004-e-mail.md). `mail.py` reads `PORTAL_MAIL_*` at every call (`settings()`, `problems()`,
`enabled()`: off without a host, and with an error logged once when the settings do not fit together), builds a
message (`message()`: plain text with an HTML alternative, `Auto-Submitted: auto-generated`, a `Message-ID` of
the sender's domain) and sends it over a connection of its own (`send()`): with `starttls` the relay must offer
STARTTLS before any credential is sent, with `tls` the connection is TLS from the start, with `none` there is
neither encryption nor authentication (test relays). The certificate is always verified (`PORTAL_MAIL_CA_FILE`
adds an authority). `MailError.temporary` tells a missing connection, a timeout or a 4xx answer from a 5xx answer
or a refused certificate. `python mail.py test <address>` sends a test message at once and prints the outcome.

`mailtexts.py` holds `TEXTS` (a subject and a plain text per message and language) and `SIGNATURE`;
`compose(template, language, **params)` fills the placeholders (an unknown one stays visible) and makes the HTML
alternative (escaped, links clickable); `language()` maps a page's language to `pt-BR` or `en-GB`.
`tokens.py` issues single-use links: `issue(user, purpose)` (the earlier link of that purpose stops working;
only the SHA-256 is stored), `peek()`, `consume()` (atomic: `find_one_and_delete`), `purge()`, `link()`; the
validity comes from `PORTAL_INVITE_HOURS` and `PORTAL_RESET_MINUTES`.

`notify.py` maps each message to a category (`TEMPLATES`, `CATEGORIES`: `account` and `security` always sent,
`jobs` optional and off by default), checks the recipient (`reachable()`: enabled, of an enabled tenant;
`wants()`: the user's choice for optional categories), composes the message in the user's language and queues a
`mail` job (`send()`, which never raises: the action that caused the message has happened). `run_mail_job()` (in
`app.JOB_RUNNERS`) skips an account that can no longer receive, sends, puts the job back for `RETRY_MINUTES` (1, 5,
15, 60, 120) after a temporary failure (`Reporter.defer()`), fails it after a permanent one or the last try
(`Reporter.give_up()`, journal `mail-failed` with the template and the relay's answer), and removes `text` and
`html` from the job once it is sent or has failed.

In `app.py`: `send_link()` (issues a link and queues its message; the link is withdrawn when nothing could be
queued), `forgot_password()` (the same answer and at least `RECOVERY_SECONDS` for every input; limits
`RECOVERY_PER_LOGIN` and `RECOVERY_PER_ADDRESS` through `LoginThrottle.over()`), `check_password_link()` and
`set_password_by_link()` (`BAD_LINKS_PER_ADDRESS`; the password set, every other link and session of the account
ended, a locked account opened again), `preferences_of()` and the preferences endpoints, and the calls of
`notify.send()` after a password change, a change of e-mail address, the failed sign-in that locks an account,
an import and a check of every record. `create_user()` invites when asked, mail is on and there is an address;
`reset_user()` sends a link when it can (a new invitation for an invited user) and otherwise makes a temporary
password as before. `users.py` gains the fields `invited`, `language`, `languageChosen` and `notify`, and
`clear_password()`, `find_login()` (a user name, ignoring case, or an address), `note_language()` and
`set_preferences()`; `create()` without a password makes an invited account.

### `apikeys.py`, `api_v1.py`, `openapi.json` — the tenant API

[ADR 0005](adr/0005-tenant-api.md). `apikeys.py` keeps the `api_keys` collection: `create(name, scopes, days,
prefixes, tenant, created_by)` checks the name, scopes, days and prefixes (`users._check_scope()`, under the `users`
lock), refuses more than `MAX_ACTIVE_KEYS` active keys per scope and returns `rk_<id>.<secret>` once (only the
secret's SHA-256 is stored); `load(tenant)`, `public()`, `state()` (`active`, `expired`, `revoked`), `revoke()`
(scoped), `authenticate()` (format, id, constant-time hash comparison, state), `count_request()` (a counter per key
and minute in `api_rate`, shared by the replicas; the first request of a minute writes `lastUsed`) and `expiring()`
(takes each key expiring within a week once, atomically).

`api_v1.py` adds the routes of `/portal/api/v1` to the portal's application. `require_key(scope)` reads the bearer
key, refuses it (401 `api.keyMissing` / `api.keyInvalid`, also for a disabled organisation), counts the request (429
`api.rateLimit` with `Retry-After`), checks the scope (403 `api.scope`) and calls `app.set_scope("api:<id>", …)`
with the key's organisation, the role its scopes imply and its prefixes, so `allowed()` and every rule apply. The
handlers use `build_document()`, `store_record()`, `remove_record()` and `label_response()`, which the portal's own
endpoints use too. `openapi.json` is written by hand; `test_api.py` checks it against the routes and validates
answers with its schemas. In `app.py`: the key endpoints (`list_api_keys()`, `create_api_key()`,
`revoke_api_key()`, always in the account's own scope), `notify_expiring_keys()` and `HOUSEKEEPING`.

### `requestlog.py` — the log of resolver requests

[ADR 0006](adr/0006-resolver-request-log.md). The resolver writes the events (`web_server/src/request_log.py`,
section 9); this module reads them through the portal's own client (`store.db().client["resolver_log"]`, read only
for the portal's user). `scope_filter(tenants, tenant, prefixes, whole)` turns the scope of a request into a filter on
the events' company part `cp` (an organisation's prefixes, anchored; for the operator, keys no organisation's prefix
starts; narrowed to the user's own prefixes); `app.log_sees_everything()` is true for a server administrator outside
support access and not limited to prefixes, who sees every event, also those without a key. `list_events(args,
scope)` applies the filters (`from`/`to` as days of `PORTAL_TIME_ZONE`, `code` as an anchor, a key value, a GTIN-13 or
a prefix, `outcome` with `notFound` for both 404s, `device`, automated requests left out unless asked) and pages with
`before` = `<time>|<id>` of the last row. `per_day()` reads `request_daily` for past days and the raw events for today.
`aggregate()` (in `app.HOUSEKEEPING`) takes the `request-stats` lock without waiting (another replica holding it: skip),
counts every day from the one after `requestStats.finalUntil` (the first time, from the oldest event) up to today with
`count_day()` — one `$match` + `$group` by key, outcome, device, form, language and link type, folded in Python into a
document per key and one per day (`|*`) with percentiles of the time taken, written with a run stamp and the day's
documents of other runs removed — then records the last finished day (ten minutes after midnight, yesterday).
`record_api_call()` and `list_api_calls()` keep and list the tenant API's calls (`api_requests`); `api_v1.py` records
each call in an `after_request` hook, with the key seen (also a refused one), the route's template, status and time.

### `overview.py` — the overview

[ADR 0007](adr/0007-overview-indicators.md). `period(days)` checks the period (7, 30 or 90; `PeriodError`, answered
422 `overview.badPeriod`) and gives its dates and the previous period's in `PORTAL_TIME_ZONE`. `build()` puts the
groups together from what `app.overview_data()` gathers for the scope of the request (`request_log_scope()`,
`visible_records()` — the record list's own function, or `None` when the resolver cannot be read —, the last check of
every link limited to `allowed()`, `overview_operation()` and, for administrators, a function giving the governance
group). `usage_and_quality()` reads `requestlog.collect(scope, whole, first, last)`: the aggregates of the period's
past days (per key, folded with `_add()`; for the whole installation the totals come from the `|*` documents, so
requests without a key count) and today's raw events grouped the same way; usage counts people (`total − automated`),
quality every request. `record_quality()` counts the records, keys by type, `noKeyRecord`, `breaksRules`, records
without a description, keys nobody scanned in the period and records with link problems. `governance()` reads
`journal.counts(scope, start, end, allowed)` (actions, and record changes per user, within the user's prefixes), the
accounts of the scope by role, the API keys (active, expiring within 14 days) and `api_requests` (calls, refused).
`summary_rows()` and `tables()` turn an answer into rows labelled with the texts the browser sends (the message codes
when none are sent); `write_csv()` and `write_xlsx()` make the files (cells protected, sheet names cleaned for Excel).
`api_v1.v1_stats()` serves `usage`, `quality` and `records` to keys with `stats:read`.

### `monitor.py` — monitoring and alerts

[ADR 0008](adr/0008-monitoring-and-alerts.md). `run()` takes the `monitor` lock without waiting (another replica: the
round is skipped) and calls `_run(now)`: `check_resolver()` (`requests.get` of `PORTAL_MONITOR_URL` and of the probe,
redirects not followed; the `failures` counter makes an alert only after `FAILURES_BEFORE_ALERT` rounds),
`check_backup(now)` (the setting `backup.last` the backup script writes), `check_certificate(now)` (once an hour;
`tls_expiry(host)` opens a verified TLS connection: `SSLCertVerificationError` is an alert, any other error unknown)
and `spikes(now, tenants)` (the last hour's `o: "unknown"` grouped by key, bucketed by `requestlog.owner_of()` into
the installation and each organisation, against the usual hour from `request_daily` of the 7 days before). `_update()`
stores each state in `alerts` and decides the message: into alert → the alert template; still in alert after
`REMIND_HOURS` → again; back to `ok` → the resolved template (none for spikes; `unknown` never resolves). `recipients()`
are the enabled server administrators or an organisation's administrators; `notify.send()` applies the category
`alerts` and each user's choice. `states(tenant, server_admin)` gives the overview's `operation.alerts` (the scope's
active alerts) and, for a server administrator outside support access, `operation.checks`. `run()` returns only the
messages sent, so the worker's log stays quiet when nothing changes.

### `domains.py` — organisations' own domains

[ADR 0009](adr/0009-tenant-domains.md). `clean_name()` (IDNA, host name rules, not the installation's), `clean_stem()`,
`clean_mode()`; `create()`, `update()` (mode, stem, `defaultFor` checked by `_check_defaults()`: the organisation's
prefixes, or for the operator none of an organisation's, one domain per prefix), `remove()`, all in the scope of the
account (`app.domain_scope()`, read only during support access: `ReadOnlySupport`, 403 `domains.readOnly`).
`verify()` looks for `gs1resolver-verify=<token>` among `txt_records("_gs1resolver.<domain>")` (dnspython; the tests
replace it) and never un-verifies; `recheck_all()` (in `app.HOUSEKEEPING`) records `seenAt` once a day.
`label_base(anchor, tenant, choice, installation)` gives the address in front of the GS1 path: the default domain of
the record's company part (`default_for()`, longest prefix), the installation's, or a verified domain of the scope
(else `domains.unusable`); `app.link_base()` uses it for the editor's preview, labels, the record's `digitalLink` and the
tenant API. `check()` requests through the domain with `probe()` (no redirects followed, the link checker's guard
against private addresses): the description file at the domain's root, or a redirect of a code of the organisation to
the installation's same path and query.

### `migrate.py`, `db_init.py`

`migrate.run(config_dir)` moves `users.json`, `records-meta.json` and `journal.jsonl` into empty collections
once, under the `migration` lock, with fixed `_id`s so that an interrupted import finishes at the next
start; the files become `*.migrated`. `db_init.py` (the `portal-db-init` service) connects with the root
`MONGO_URI` and creates the portal's user, or updates its password and roles (`readWrite` on its database, `read` on
`resolver_log`); it refuses `admin`, `local`, `config`, `resolver_ce` and `resolver_log` as the portal's database.

### `create_user.py`

`docker compose exec portal-service python create_user.py <name> [--role …] [--prefixes …] [--tenant …] [--email …] [--remove]`
creates a user or sets a password (asked twice), role, prefixes and e-mail, or removes a user. `--tenant`
(name or id) puts a new user in an organisation; without it the user is the operator's.

## 6. Portal front end (`portal/static/`)

No framework and no build step: plain HTML, CSS and JavaScript served as static files.

| File | Role |
|---|---|
| `index.html` | the portal page: header with language and user menus, editor (three steps, other records, history), label block, record list, users, audit, dialogs (options, import), the template of a target row |
| `login.html`, `login.js` | sign-in page; with e-mail also *Forgotten your password?* and the page a link opens (`#invite=…` / `#reset=…`: the token is read, removed from the address bar at once and posted; a link pasted into an open page is caught by `hashchange`) |
| `password.js` | show/hide button in every password field |
| `i18n.js` | message catalogue (pt-BR, en-GB) and translation engine |
| `app.js` | everything else; a map of its sections is at the top of the file |
| `app.css` | styles; media queries after the rules they change |

**Views.** The address fragment chooses the view (`#overview`, `#records`, `#requests`, `#users`, `#audit`, otherwise
the editor, also `#editor`), so the browser's back button and bookmarks work (`applyView()`). Signing in opens
`#overview` (`login.js`).

**Translation.** Elements declare their texts: `data-i18n="key"`, `data-i18n-params='{…}'`,
`data-i18n-attr="placeholder:key;aria-label:key"`. `I18N.apply()` renders them all; `I18N.set(el, key,
params)` sets one; `t(key, params)` returns a string. The language comes from the saved choice, the
`gs1resolver_lang` cookie (shared with the home page and the resolver's pages) or the browser. Server
answers carry codes (`save.updated`, `key.checkDigit`…) with parameters, rendered by the same catalogue.

**Validation.** `readKey()` and `readQualifiers()` repeat the server's rules for instant feedback, from the
checks, patterns, lengths and order the server sends in `CONFIG.rules` (`gs1.browser_rules()`, built from the
dictionary); nothing in `app.js` repeats a length or a format. The server checks again and is the authority.

**E-mail ([ADR 0004](adr/0004-e-mail.md)).** `body[data-mail="on"]` (from `CONFIG.mail.enabled`) shows the
`.needs-mail` elements: the invitation box of the new-user form, the *E-mail* section of Options
(`fillPreferences()`, `savePreferences()`). `mailLink(u)` tells whether a reset goes by e-mail (the question and
the button's label follow it). `init()` signs out and goes back to the sign-in page when it finds an invitation or
recovery fragment (a link opened while someone was signed in: the sign-in page redirected here).

**API keys ([ADR 0005](adr/0005-tenant-api.md)).** The `#apikeys` view (administrators) lists the keys of the
account's own scope (`loadApiKeys()`, `apiKeyRow()`), creates one (`createApiKey()`: the key and an example are
shown once) and revokes (`revokeApiKey()`). `forgetNewKey()` removes a new key from the page when the view is left.

**Requests ([ADR 0006](adr/0006-resolver-request-log.md)).** The `#requests` view (every user) draws the last 30
days (`loadRequestDays()`: one bar per day from `/requests/daily`, answered and not found stacked, automated requests
counted apart), lists the latest requests (`loadRequests()`, `requestRow()`, pages with `next`, the filters of
`requestsQuery()`), exports them (`downloadRequests()`) and, for administrators, the tenant API's calls in a second
tab (`showRequestsTab()`, `loadApiCalls()`). `body[data-requests-whole]` (from `CONFIG.requestLog.whole`) shows the
organisation column. Rows carry `data-label` for the phone layout.

**Overview ([ADR 0007](adr/0007-overview-indicators.md)).** The `#overview` view (every user) asks `GET /overview` for
the period of `#overview-days` (`loadOverview()`, a newer request winning over a slower older one) and draws it
(`renderOverview()`): tiles (`tile()`, the change on the previous period from `changeText()`, green or red by
`better`), the bars per day (as on the Requests screen), tables of codes (a code opens the editor through
`openFromList()`), share tables with bars (`shareTable()`), the operation facts and, when the answer has it, the
governance group (`.needs-admin`). `exportOverview()` posts the period and every `overview.*` text of the current
language (`overviewLabels()`, `I18N.keys()`) and saves the file. The tables stay tables on a phone.

**Domains ([ADR 0009](adr/0009-tenant-domains.md)).** The `#domains` view (administrators) lists the scope's domains
as cards (`loadDomains()`, `domainCard()`: the TXT record while pending, defaults, stem and mode to change, *Verify*,
*Test*, *Remove*) and adds one (`createDomain()`); `refreshDomainConfig()` reloads `CONFIG.domains` after a change.
The label panel's `#opt-domain` (`fillDomainOption()`) offers the default, the installation and the verified domains;
`domainBase()` repeats the server's rule for the address drawn under the code, and `labelOptionsQuery()` and the
preview's request pass `domain`.

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
| `POST /password` `{currentPassword, newPassword}` | any | Change password; other sessions end; a security message when mail is on |
| `GET /login/options` | — | `{passwordRecovery}`: whether the sign-in page offers recovery (mail on) |
| `POST /password/forgot` `{login, language}` | — | Recovery link by e-mail to the account of that user name or address, when it may sign in and has an address; always `password.recoverySent` (404 `password.recoveryOff` when mail is off, 429 `password.recoveryLimit`) |
| `POST /password/link/check` `{token}` · `POST /password/link` `{token, newPassword, language}` | — | A single-use link: `{user, purpose, min}` or 410 `password.linkInvalid`; then the password set (`password.set`, `purpose`), the link used up (429 `password.linkLimit` after ten invalid links from one address) |
| `GET /preferences` · `PUT /preferences` `{language, notify: {jobs}}` | any | The user's e-mail address (read only), the language of his messages and the optional categories (`preferences.saved`, `preferences.languageInvalid`, `preferences.categoryUnknown`) |
| `GET /config` | any | User, role (the one that applies), `accountRole`, `serverAdmin`, `tenant` and `support` (`{id, name, disabled}` or `null`), prefixes, resolver address, link types, keys with qualifiers and shapes, languages, import limits, data attributes, session limits (`session`: `idleSeconds`, `warningSeconds`, `endsIn`, `maxHours`), `mail` (`{enabled}`), `requestLog` (`{days, whole}`: the log's retention, 0 when off, and whether the user sees the whole installation) and `preferences` (as `GET /preferences`) |
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
| `GET /users` · `POST /users` `{username, role, prefixes, email, tenant}` · `PUT /users/{name}` `{role, prefixes, email, disabled}` · `POST /users/{name}/reset` · `DELETE /users/{name}` | admin | User administration: a server admin manages every user (`tenant` chooses the organisation; the answer to GET adds `tenants`), a tenant administrator the users of his tenant; `tenantName` and `invited` on each user; temporary passwords in the answer. With mail on: `POST /users` with `invite` and an address answers `users.invited` without a password; `reset` answers `users.resetSent` (a link by e-mail) for a user with an address |
| `GET /tenants` · `POST /tenants` `{name, prefixes}` · `PUT /tenants/{id}` `{name, prefixes, disabled}` · `DELETE /tenants/{id}` | server admin | Organisations; GET adds `users` and `records` per tenant and `operatorRecords` |
| `POST /support` `{tenant, reason}` · `DELETE /support` | server admin | Open and close read-only support access to a tenant, recorded in its audit trail |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | admin | Audit trail of the scope: a tenant's; the operator's plus what operator users did to tenants; a tenant's during support access. Events carry `tenant`, `tenantName`, `byOperator`; the CSV adds `organisation` and `by_operator` |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | reader | Digital Link with data attributes checked by the engine; nothing stored |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg\|pdf\|zip&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&size=80…200&linear=none\|auto\|upce&domain=&attr=AI:value` | reader | Label; headers `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`, `X-Linear-Symbol`; 422 `qr.tooSmall` / `qr.tooLong`, `label.sizeInvalid`, `label.linearInvalid`, `label.linearNotPossible`, `domains.unusable` |
| `GET /keys` · `POST /keys` `{name, scopes, days, prefixes}` · `DELETE /keys/{id}` | admin | API keys of the account's own scope (a tenant administrator's organisation; the operator for a server administrator, also during support access): the list with `scopes`, `maxDays`, `defaultDays`, `ratePerMinute`; creation answers `key` (shown once) and `item`; delete revokes |
| `GET /requests?from=&to=&code=&outcome=&device=&automated=&before=&limit=` | any | Resolver requests in the scope of the request ([ADR 0006](adr/0006-resolver-request-log.md)), newest first, at most `limit` (1–500, 200): `events` (`at`, `method`, `form`, `epc`, `key`, `value`, `anchor`, `qualifiers`, `attributes`, `linkType`, `status`, `outcome`, `level`, `target`, `ms`, `language`, `device`, `referrer`, `country`, `path`, and `organisation` for the whole installation), `next`, `days`, `whole`; 422 `requests.badDate` / `requests.badFilter`, 503 `requests.unavailable` |
| `GET /requests.csv` (same filters) | any | Up to 50,000 of them as CSV (UTF-8 with BOM, `;`, cells protected); journal `requests-export` |
| `GET /requests/daily?days=30` | any | `days`: `[{day, total, automated, outcome}]`, oldest first, in the scope (past days from `request_daily`, today from the events); `timeZone` |
| `GET /requests/api?from=&to=&key=&before=&limit=` | admin | The tenant API's calls of the scope (every organisation's for a server administrator): `calls` (`at`, `key`, `keyName`, `organisation`, `method`, `operation`, `status`, `ms`), `next`, `whole` |
| `GET /domains` · `POST /domains` `{domain, mode, stem}` · `PUT /domains/{domain}` `{mode, stem, defaultFor}` · `POST /domains/{domain}/verify` · `POST /domains/{domain}/check` · `DELETE /domains/{domain}` | admin | The organisations' own domains ([ADR 0009](adr/0009-tenant-domains.md)) of the account's scope (a server administrator lists every domain with `organisation`; support access: read only, 403 `domains.readOnly`); `domains.*` codes |
| `GET /overview?days=7\|30\|90` | any | The overview of the scope ([ADR 0007](adr/0007-overview-indicators.md)): `period`, `whole`, `logDays`, `usage`, `quality`, `records`, `operation`, `governance` (administrators; otherwise `null`); 422 `overview.badPeriod`, 503 `requests.unavailable` |
| `POST /overview/export` `{format: xlsx\|csv, days, labels}` | any | The overview as a file (lists up to 100); journal `overview-export` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable", "worker": "ok"\|"unavailable", "mail": "on"\|"off"}` |

The **tenant API** (`/portal/api/v1`, an API key instead of the session) is described in `portal/openapi.json`
and in the README (*Tenant API*): `GET /`, `GET /records`, `GET`/`PUT`/`DELETE /records/{key}/{value}`,
`GET /labels/{key}/{value}`, `GET /stats` (scope `stats:read`, ADR 0007), `GET /openapi.json`.

## 8. Portal data

The portal's database (`PORTAL_DB_NAME`, default `resolver_portal`), included in the daily MongoDB dump.
Decisions and the reasons for them: [ADR 0001](adr/0001-portal-state-in-mongodb.md).

| Collection | `_id` and content | Indexes |
|---|---|---|
| `users` | user name; `hash` (empty while invited, or after a reset by link), `role`, `prefixes`, `tenant` (absent for the operator's users), `email` (optional), `disabled`, `mustChange`, `created`, `lastLogin`, `invited`, `language`, `languageChosen`, `notify` (the last four absent when empty) | — |
| `tenants` | `t-` + 12 hexadecimal digits; `name`, `prefixes`, `disabled`, `created`, `createdBy` ([ADR 0002](adr/0002-tenants.md)) | — |
| `record_meta` | record key (GTIN records by the 14 digits, other keys by `AI/value`, plus the qualifier path); `createdAt`, `createdBy`, `updatedAt`, `updatedBy`, `tenant` (absent for the operator) | — |
| `journal` | ObjectId (`jsonl-<line>` for migrated events); `at` (date), `user`, `action`, `category`, `tenant` (absent for the operator), `byOperator`, `anchor`, `qpath`, `doc`, `detail`, `expiresAt`. Record actions `create`, `update`, `delete` (with the record's content), `import`; others `login`, `login-failed`, `login-refused`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove`, `tenant-create`, `tenant-update`, `tenant-remove`, `support-open` (the reason in `detail`), `support-close`, `password-recovery`, `password-reset`, `invite-accepted`, `preferences`, `mail-failed` (never an e-mail address), `api-key-create`, `api-key-revoke`; changes made through the tenant API carry the user `api:<key id>` | date; record + date; user + date; tenant + date; category; TTL on `expiresAt` |
| `login_failures` | `key` (`user:<name>` or `addr:<address>`; recovery requests `forgot-user:<entry>` and `forgot-addr:<address>`; invalid links `link-addr:<address>`), `at` | key + date; TTL 15 minutes on `at` |
| `linkcheck_cache` | address; `result`, `expiresAt` | TTL on `expiresAt` |
| `jobs` | token; `type` (`import`, `linkcheck`, `mail`), `user`, `state`, `created`, `queuedAt`, `startedAt`, `finishedAt`, `heartbeat`, `worker`, `attempts`, `done`, `total`, `expiresAt`, `error`, `notBefore`; imports `plan`, `keyRecords`, `results`; link checks `scope`, `urls` (`[{url, records}]`), `problems`, `records` (`[{record, problems}]`); messages `to`, `subject`, `text` and `html` (removed once sent or failed), `template`, `tries`, `lastError`, `sent` or `skipped` | state + creation; TTL on `expiresAt` |
| `api_keys` | 12 hexadecimal digits (the key's id); `hash` (SHA-256 of the secret), `name`, `tenant` (absent for the operator), `scopes`, `prefixes`, `created`, `createdBy`, `expiresAt`, `lastUsed`, `revoked`, `revokedBy`, `expiryNotice` ([ADR 0005](adr/0005-tenant-api.md)) | tenant + creation; expiry |
| `api_rate` | `<key id>:<minute>`; `n`, `at` | TTL 2 minutes on `at` |
| `tokens` | SHA-256 of a single-use link's token; `purpose` (`invite`, `reset`), `user`, `created`, `expiresAt` ([ADR 0004](adr/0004-e-mail.md)) | user + purpose; TTL on `expiresAt` |
| `workers` | worker name (`host:pid:mode`); `seen`, `mode`, `job` | TTL 10 minutes on `seen` |
| `request_daily` | `<day>\|<AI>\|<value>` (a key's day) or `<day>\|*` (the installation's day); `day`, `ai`, `v`, `cp`, `total`, `automated`, `outcome`, `device`, `form` (counts by name), `language`, `linkType` (`[[name, count]]`, 20 at most), `ms` (sum), `msMax`, on the installation's day also `keys`, `p50`, `p95`, `p99`; `run`, `expiresAt` ([ADR 0006](adr/0006-resolver-request-log.md)) | day; company part + day; TTL on `expiresAt` |
| `domains` | the domain (lower case, Punycode); `tenant`, `mode`, `stem`, `defaultFor`, `token`, `verified`, `verifiedAt`, `seenAt`, `check`, `created`, `createdBy` | — (read by the resolver too) |
| `alerts` | `resolver`, `backup`, `certificate`, `404:*`, `404:<tenant id>`; `state` (`ok`, `alert`, `unknown`), `since`, `checkedAt`, `failures`, `detail`, `notifiedAt`, `resolvedAt`, `tenant` | — (a handful of documents) |
| `api_requests` | ObjectId; `t`, `key` (absent without a valid key), `tenant` (absent for the operator), `m`, `op` (the route's template), `s`, `ms`, `expiresAt` | date; tenant + date; TTL on `expiresAt` |
| `settings` | `lastFullCheck` (the operator's) and `lastFullCheck:<tenant>`, `journalRetention`, `migration`, `requestStats.finalUntil` (the last finished day counted), and the `lock:<name>` documents | — |

The resolver's own log is another database, **`resolver_log`**, which the portal's user may read only: its
collection `requests` holds one event per resolution request (fields in [ADR 0006](adr/0006-resolver-request-log.md),
section 3.1; indexes on time, company part + time, key + time, TTL on `expiresAt`). The daily backup keeps it.

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
- `domains.py` (new, [ADR 0009](adr/0009-tenant-domains.md)): `Middleware` wraps `app.wsgi_app` in `create_app()`;
  `request_host()` reads `X-Forwarded-Host` (else `Host`), lower case, without port; `DomainMap.lookup()` reads the
  verified `direct` domains and the tenants' prefixes from `PORTAL_DB_NAME` (`resolver_portal`) through
  `mongo.cx` at most every `CACHE_SECONDS` (60), keeping the last list when the read fails; for a domain, the
  stem is removed from `PATH_INFO` and `RAW_URI`/`REQUEST_URI` (after the `/api` mount) and the entry (`host`,
  `stem`, `prefixes` or the `excluded` prefixes of the operator's domains) put in `environ[ENV_KEY]`.
  `allows(environ, ai, value)` compares `request_log.company_part()`; `_process_response()` answers a refused key as
  `read_document()` answers an unknown one (404, outcome `unknown`) and does not list its link types on the HTML
  page; `_resolver_description()` gives the domain and stem as `resolverRoot`.
- `request_log.py` (new, [ADR 0006](adr/0006-resolver-request-log.md)): `note()` (called by the routes; marks the
  request as one to log), `start()` and `record()` (the application's `before_request` / `after_request` hooks, set in
  `create_app()`), `event()` (the stored document: `qualifiers()` keeps only the AI of 21 and 235, `attribute_ais()`
  only the AIs of the query string, `masked_level()`, `device_class()` — automated first, then native app stacks,
  tablet, mobile, desktop —, `language()`, `host_of()`, `company_part()`), `outcome()`, and `Writer`: a bounded
  queue per process (started at the first event and again after a fork), a daemon thread writing batches of up to 500
  with one retry, events lost counted (`lost_total`) and reported at most once a minute, `flush()` (tests, and at
  exit). `create_app()` gives the writer `mongo.cx["resolver_log"]["requests"]` unless a test set another collection.
  `web_logic.read_document()` and `_validate_and_fetch_document()` add `_level` (the level that answered a 307 or 300)
  and `_outcome` (`unknown` or `noLink` on a 404) for the log; `web_namespace._process_response()` pops both before
  answering.
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
`/swaggerui` to data-entry-service, and `/portal/` to portal-service (with `/portal` → `/portal/`). The
resolver's location also passes `X-Forwarded-Host: $host`, the public name asked (an organisation's own domain,
ADR 0009).
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
  portal's and the request log included) and archive of the portal volume, 14 days kept; a failed dump says
  `ERROR`, leaves no partial file and exits with status 1.
- `custom-domains.sh` (ADR 0009): `list` and `apply` the organisations' verified `direct` domains (read with
  `mongosh` inside the database container): a site `gs1resolver-domain-<domain>` from `templates/nginx-site-http.conf`
  and `certbot --nginx` for each new one; a name that is not a host name never reaches a file or a command; sites of
  domains no longer verified are listed.
- `resolver-backup.sh` also records each run in the portal's database (`backup.last`, ADR 0008).
- `install.sh` also writes `PORTAL_TIME_ZONE` (not asked: the environment, the existing `.env`, else the server's time
  zone from `timedatectl`, `/etc/timezone` or the `/etc/localtime` link, else UTC).

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
| `resolver/test_domains_resolver.py` | 29 | organisations' own domains in the resolver ([ADR 0009](adr/0009-tenant-domains.md)): a domain with a stem resolving its organisation's codes (also a batch with `%2F`, the raw URI stripped), refusing others with 404 and without their link types or linkset, the description file's `resolverRoot`; a domain without a stem; `X-Forwarded-Host`, `Host`, ports, capitals, several hosts; the operator's domain; hosts that are not registered domains, pending ones, redirecting ones; the cache, a database that cannot be read; the proxy's header |
| `resolver/test_request_log.py` | 73 | the log of resolver requests ([ADR 0006](adr/0006-resolver-request-log.md)) through Flask's test client into mongomock: every field of a redirect's event, levels, unit qualifiers kept as AIs only, every outcome (unknown code, missing link type, choice, linkset, invalid request, probe, compressed link, `?compress`, EPC binary string), HEAD, languages, what is never stored (address, User-Agent, full referrer, values of data attributes and serial numbers), routes not logged, answers unchanged, the country header, retention and the switch, indexes, device classes, and that a database that does not answer or fails never holds a request up (events lost and counted, batches of 500) |
| `portal/test_dictionary.py` | 30 | the GS1 rules from the dictionary (ADR 0003): `gs1_dictionary.json` exactly what the pinned release's dictionary gives, the parser, keys, shapes, order and formats built from it with the portal's exceptions, a longer format or a new key handled with no code, an unknown linter or shape stopping the build, the rules sent to the browser, AIs (7041) and (8040)–(8043) and their Portuguese names, the comparison of the weekly issue |
| `portal/test_engine_messages.py` | 26 | the engine's messages (ADR 0003): `engine_messages.json` exactly what the pinned release's sources give, both languages of every message with the same parameters (the English one the engine's text), every message and linter's message recognised as itself, the portal's refusals carrying the message, the comparison of the weekly issue |
| `portal/test_keys.py` | 138 | keys and qualifiers, compared with the GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | roles, prefixes, users, history, audit |
| `portal/test_sheet.py` | 43 | spreadsheets, limits per format |
| `portal/test_special_chars.py` | 57 | special characters |
| `portal/test_data_attributes.py` | 83 | data attributes, decimal families, QR options (needs `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | link checker, SSRF guard |
| `portal/test_portal_config.py` | 13 | configuration and start-up, session limits |
| `portal/test_session.py` | 30 | session limits (15 s idle in the test): server rules, warning, renewal on use, other tabs, absolute limit, both languages; community notice in the footer (about two minutes) |
| `portal/test_store.py` | 58 | the portal's database layer: connection settings, indexes, the shared lock (also between two administrators at once), users, record metadata, journal and its retention, sign-in throttle, migration of the old files (also interrupted and resumed) |
| `portal/test_tenants.py` | 82 | tenants ([ADR 0002](adr/0002-tenants.md)): an installation without tenants unchanged; tenants and their prefixes (names, overlaps, redundancy, operator users in the way); the operator's records and users; tenant administrators and their users; e-mail addresses; records, history, record list, export and imports per tenant, and the worker's check before each record; prefixes moving between owners; the audit trail per tenant and its CSV; support access; disabled and removed tenants; link check results per scope; ownership by key type; the command line; the messages of both languages (same keys, every key of the page and every message code of the server translated) |
| `portal/test_mail.py` | 138 | e-mail ([ADR 0004](adr/0004-e-mail.md)) against an SMTP relay of the test's own (`fake_smtp.py`: STARTTLS or TLS with a throwaway certificate, authentication, refusals on demand): settings that do not fit, sending with STARTTLS and TLS, headers and the HTML alternative, temporary and permanent failures, credentials never sent without encryption, the test command; the texts of both languages; single-use links (hash only, once, replaced, expired, purged); `notBefore` and `defer()`; with mail off nothing changes; invitations, password recovery (the same answer and time for every input, limits, who gets nothing), resets by an administrator, security notices, preferences, notices of finished jobs; retries, failures, a message skipped for an account disabled meanwhile, no address in the journal; every message code translated. Every protection mutation-checked |
| `portal/test_api.py` | 92 | the tenant API and its keys ([ADR 0005](adr/0005-tenant-api.md)): keys created, listed and revoked only in the administrator's own scope (also during support access), the rules of a key (name, scopes, days, prefixes, 20 active), the full key once and only its hash stored, the creator told by e-mail; authentication (missing, wrong, revoked, expired, disabled organisation), sessions and keys kept apart; records listed in pages, read, written (GS1 rules, another owner's record refused, no CORS), deleted; labels; scopes, a key's prefixes, the operator's keys; the journal (`api:<id>`); the request limit and the last use; the expiry notice and the worker's housekeeping; the OpenAPI description against the routes and the answers; both languages. Every protection mutation-checked |
| `portal/test_overview.py` | 66 | the overview ([ADR 0007](adr/0007-overview-indicators.md)): the period and the previous one (a period refused), usage before and after the worker counted (past days from the aggregates, today from the raw events, the same figures either way), per day, the most scanned codes, shares, quality (a compressed link's answer counted as answered), unknown and noLink codes with whether the key has records; record quality (no key record, keys nobody scanned); operation; each scope (an organisation, a user's prefixes, the operator, the whole installation with requests without a key but only codes in the lists, support access); 7 and 90 days; governance (changes by kind and user, within an administrator's prefixes; users; API keys expiring); `/v1/stats` and its scope, a key's prefixes; the exports (sheet names, labels, protected cells, the journal, the origin); the resolver or the log unreadable; the texts in both languages, the description, the sign-in's landing. 18 mutations, all caught |
| `portal/test_label.py` | 92 | the label studio ([ADR 0010](adr/0010-label-studio.md)): check digits, the symbol each GTIN takes and refusals, UPC-E's zero suppression, reference module patterns (EAN-13, UPC-A, EAN-8 and UPC-E for every check digit) read back by zxing-cpp when written, EAN-13 for every first digit read back by OpenCV; the default label identical to the previous version's (size and PNG pixels); sizes, the 2 mm text, the PNG's DPI; each symbol beside the QR code at 80, 100 and 200 % read back; bar heights, guard bars, quiet zones, digits; the PDF (structure, cross-references, page size, rectangles, no font, title); the zip; through the portal and the tenant API with refusals. 18 mutations, all caught |
| `portal/test_domains.py` | 59 | organisations' own domains in the portal ([ADR 0009](adr/0009-tenant-domains.md)): who manages which (organisation administrators, the operator's by server administrators who list every domain, support access read only, not editors); names, stems, modes, uniqueness, Punycode, the limit; the DNS proof (refused with the record to add, verified, kept when the record goes, the daily look again); default prefixes (the organisation's, one domain each, the operator's not an organisation's); the address of the preview, the record, labels and the tenant API (default, installation, chosen, refused); the check of both modes (resolver, not the resolver, no answer, private address, a redirect that loses the path) and the real probe's guard; removal; the journal; both languages. 25 mutations with the resolver's, all caught |
| `portal/test_monitor.py` | 62 | monitoring ([ADR 0008](adr/0008-monitoring-and-alerts.md)): the settings; the resolver through a stand-in proxy (two failed rounds, no repeat, a reminder after 24 hours, resolved; the probe; no answer); the backup's record (unknown, late, failed, good again, the error in the message); the certificate (valid, once an hour, expiring, invalid, unreachable without a message, valid again); spikes per scope (the last hour only, the codes, the usual hour, both settings, the end without a message); recipients (server administrators, an organisation's administrators, not readers, not a user who switched alerts off, not disabled accounts); the overview's alerts per scope and support access; the lock; the worker's schedule; the category and a user's choice; messages in the recipient's language and both languages' placeholders; the screen's texts. 18 mutations, all caught |
| `portal/test_requestlog.py` | 74 | the request log in the portal ([ADR 0006](adr/0006-resolver-request-log.md)): who sees which events (an organisation, a user's prefixes, the operator, server administrators with each event's organisation, a limited server administrator, support access, a prefix moving between organisations), filters (outcome, device, automated, code as GTIN-13, GTIN-14, prefix, anchor; days of `PORTAL_TIME_ZONE`), pages with ties, the CSV (formulas protected, the organisation column, the journal), the daily aggregates (per key and for the installation, percentiles, expiry, finished days, replacement, the lock, the switch, an unknown time zone), requests per day per scope, the tenant API's calls (never the record or the secret; who sees them), the configuration, an unreadable log, the messages of both languages |
| `portal/test_jobs.py` | 70 | background jobs: states, expiry, atomic claim, ownership of writes, silent workers given back and failed after three attempts, the worker's announcement, `stalled`, the health check, the worker loop (errors, heartbeat, stop and hand-back, `JobLost`), the embedded worker and `PORTAL_WORKER`; imports through the API (queue, worker, journal, another user, a worker dying before and after writing a record, a failure); link checks through the API (every record, a list, a stop that cancels pending addresses) |
| `portal/test_worker_processes.py` | 13 | `worker.py` as real processes on a real MongoDB (run by `test_store_mongodb.py`): two workers share the queue without taking a job twice; SIGTERM hands the job back and the other worker finishes it; after SIGKILL a new worker continues the job once its heartbeat is old |
| `portal/test_store_mongodb.py` | 165 | on a real MongoDB (`PORTAL_TEST_MONGO_URI`, CI only): the user made by `db_init.py` and its privileges (reading the request log, not writing it); `test_store.py`, `test_jobs.py` and `test_worker_processes.py` again as that user (their lines relayed); the TTL monitor, also for jobs and old worker announcements |
| `portal/test_registration.py` | 26 | §2.5.9 through the portal API: informative qualifiers (save, open, history, list, export, import), records against rule 2, the key's own record when saving and importing |
| `portal/test_mail_e2e.py` | 37 | the e-mail screens in Chromium with the relay of `fake_smtp.py`: recovery on the sign-in page (the same answer for every entry), an invitation from the users screen, the page a link opens (user name, the token gone from the address bar, short and different passwords refused, a phone's width), a link used twice, a link opened while someone else is signed in, a recovery ending the user's open session, Options → E-mail kept, a reset by link, every text of the sign-in page translated, and the same screens with e-mail off |
| `portal/test_requests_e2e.py` | 28 | the Requests screen in Chromium ([ADR 0006](adr/0006-resolver-request-log.md)): the menu item for every user (and the menu closing), 30 bars from the aggregates and today's events, the latest requests (organisation column for a server administrator, EPC scheme, level, serial as `/21/*`), the next page, filters (not found, a GTIN-13, automated requests), the CSV export, support access, English, an organisation's reader (no organisation column, no API tab), an administrator's API calls without the key's secret, a phone's width, the log switched off |
| `portal/test_api_e2e.py` | 21 | the API keys screen in Chromium: an organisation's administrator creates a key (shown once with an example), a system uses it through `/portal/api/v1`, the record shows `api:<id>`, leaving the screen removes the key from the page, revoking on screen stops it at once, the audit trail, both languages, a phone's width, the operator's keys for a server administrator, no screen for an editor |
| `portal/test_overview_e2e.py` | 28 | the overview in Chromium: sign-in lands on it, its groups for an organisation's administrator, the period selector, *Register* opening the editor on the code, the Excel and CSV exports, the menu items, Portuguese, a reader without governance, a server administrator's whole installation and server facts, a phone's width |
| `portal/test_domains_e2e.py` | 25 | the Domains screen, the label's domain and the label studio's options (sizes with their X-dimensions, the linear barcode, PDF and ZIP downloads) in Chromium: adding, the TXT record, verifying before and after it exists, defaults, a check, the label offering the domain (default of the prefix, installation, chosen; the address under the code and the downloads), Portuguese, removal, an editor without the screen, a phone's width |
| `portal/test_portal_e2e.py` | 212 | the portal in Chromium against `mock_data_entry.py`, desktop and phone, with an embedded worker (also stopped: the queue and "not running" messages, a job that fails); organisations, a tenant administrator and support access in both languages; also run without the engine (167) |
| `home/test_home.py` | 68 | home page through a real nginx (1.27.3 or later: `NGINX_BIN` or the PATH), no syntax box, community notice; proxy routes, including that the Host header sent to each upstream is one Werkzeug accepts; replicas through a stub DNS server answering the service names with `127.0.0.x` addresses: nginx starts while a service has no address and finds it later, shares the requests between two replicas, follows a third added and two removed without a restart, and no request fails while replicas stop |
| `install/test_install.sh` | 87 | installer through shims (Compose v2), including a portal whose job worker does not start; replica counts written, kept, taken from the environment and refused when invalid; the time zone of the request counts (the server's, from the environment, refused when not a name); the e-mail relay (off by default, written with STARTTLS or TLS, its password kept and never shown, switched off, a test relay set by hand kept, refusals); no setting written twice in `.env` |
| `install/test_deploy.py` | 73 | the daily backup with a stand-in `docker` (only options `mongodump` has; a failed dump: `ERROR`, status 1, no partial file; a good one: the archive, `OK`; each run recorded for the portal's monitoring, a record that cannot be written only a warning, the record's mongosh script valid JavaScript); `custom-domains.sh` with stand-in `docker`, `nginx`, `systemctl` and `certbot` (CERTBOT_EMAIL needed, sites from the template, Certbot per domain, a name that is not a host name refused, domains already served left alone, orphan sites listed); `docker compose config` of the replicas and process counts (defaults, values from `.env`, a refused value, names kept by the database and the proxy); the proxy image's nginx version and `resolve` in every upstream; each image's gunicorn `CMD` started locally (three processes, an answer, the request logged, a clean stop on SIGTERM within 10 s); the portal's fallback session key with six processes starting together and eight threads while writing it is slow; the portal started from the files the `COPY` lines of its Dockerfile put in the image, every module and data file of `portal/` among them; one engine release, in `docker-compose.yml` only, given to every image (ADR 0003) |

**pytest and continuous integration.** `dev-tests/test_programs.py` runs each program above as one pytest
test (a subprocess from the repository root): exit status 0 without a `FAIL` line passes; otherwise the
report shows the `FAIL` lines and the end of the output; a program that only printed `SKIP` is skipped.
Markers group them: `resolver` (resolver, EPC binary, data entry, GS1 suite), `portal` (the portal programs
without a browser), `e2e` (`test_portal_e2e.py` with and without the engine, `test_session.py`, `test_mail_e2e.py`, `test_api_e2e.py`, `test_requests_e2e.py`, `test_overview_e2e.py`, `test_domains_e2e.py`), `home`,
`install` (the installer through password-less `sudo` when not root, and `test_deploy.py`), `database` (`test_store_mongodb.py`). `dev-tests/conftest.py` keeps the programs from
being imported by pytest, registers the markers and prints the check counts of each program at the end (and
in the GitHub Actions run summary). With `DEV_TESTS_STRICT=1` a program fails when an environment variable
it needs is not set or names a missing path (`needs_env`), when a variable that is not a path is not set
(`needs_var`), when a command it needs is not on the PATH, or when it prints `SKIP`. To add a program: write
it with `PASS`/`FAIL` lines and an exit status, add a `Program(...)` line to `PROGRAMS` (group, path, the
variables and commands it needs), and a row to the table above.

A second workflow, `.github/workflows/engine-update.yml` (weekly, Mondays 09:37 UTC, and on demand), opens an
issue when the GS1 Barcode Syntax Engine has a release newer than `x-gs1-syntax-engine`: it uses the new release in
its own copy, regenerates the dictionary, compares it (`tools/dictionary_diff.py`), runs the `portal` group and
writes both in the issue; one issue per release; it never pushes (`contents: read`, `issues: write`). A fork on GitHub has Issues switched off by default, and the
job then fails with "repository has disabled issues": switch them on in Settings → Features → Issues.

`.github/workflows/dev-tests.yml` runs one job per group in parallel on every push and pull request to
`gs1br/develop` (not for changes to `Documentation/` or Markdown files only), in strict mode. The `database`
job starts a `mongo:7` service container and runs the `portal` and `database` groups on it. `database` is
informative (`continue-on-error`) until it proves stable; `e2e` and `install` started that way and are
required since step 4 of item 2.3. The composite action
`.github/actions/dev-tests-setup` installs only what a job asks for and exports the variables: Python 3.12
and Node.js 24 as in the images; `gs1encoder`, `epc-tds` and `ajv-dist` at pinned versions (cache keyed by
the versions, `gs1encoder`'s read from `docker-compose.yml`); the portal's engine built by
`portal/tools/build-syntax-engine.sh` at that release (cache keyed by the release and the script); Chromium (cache keyed by the Playwright version); GS1's suite at commit
`32597c1`; Ubuntu's nginx for the installer, nginx 1.30.5 from nginx.org for the proxy test; Docker
Compose v2.29.7. Change a version there, in one place; the engine's release is not there but in
`docker-compose.yml`.

`docs/screenshots.py` regenerates the images of the README and of the user guide, in English, from the real portal with example data (GS1 logo hidden). The e-mail images (`mail_images()`) are made with e-mail
switched on for them only, against the relay of `fake_smtp.py`. Commit only images that really changed.

## 14. How to extend

**A text of the interface.** Add the key to both locales of `i18n.js` (`pt-BR` and `en-GB`), use it with
`data-i18n` or `I18N.set()`. Server messages are codes: raise `ValidationError("my.code", param=…)` and add
`my.code` to both locales.

**A language.** Copy a locale block of `i18n.js`, translate it, add it to `SUPPORTED` and
`LOCALE_MATCHERS`; do the same in `web_pages.py` (`TEXT`, `LINK_TYPE_LABELS`) and `home/home.js`.

**A link type.** Add a row to `LINK_TYPES` in `gs1.py` and its name and description to `linkTypes` in both
locales; consider `activeLinkTypes` in `web_server/src/public/gs1resolver.json`.

**A primary key or qualifier** (a later dictionary). They come with the dictionary: update the engine (below)
and regenerate `gs1_dictionary.json`. Code is needed only when the new format has a shape or a linter
`key_validator()` / `qualifier_pattern()` do not know (the build stops and names it; the weekly issue says so):
add the check in `gs1.py` and its `.spec` kind in `readKey()` of `app.js`. Add `key.<AI>.*` / `qual.<AI>.*`
texts and a name in `PORTAL_EXCEPTIONS["key_names"]`; extend `dev-tests/portal/test_keys.py`.

**An API endpoint.** Add the route to the right section of `app.py` with `@require_login` and, for writes,
`@role_required("editor")`; call `check_access()` for every identifier; answer with `message()` codes;
log with `audit.info()` and `log_event()`; add tests; list it in this guide and in the README.

**An EPC scheme or a new TDT release.** Copy the new definition files and tables into
`web_server/src/tdt/` (keeping `+` in the names) and update `manifest.json`; schemes before TDS 2.0 then
need no code. A `+` scheme needs code only for a Table F format or TDS 14.5 method that `_component()`
does not know; a `++` scheme only an entry in `PLUS_PLUS` while TDT has no artefact for it. Add its TDS
annex E vector to `test_epc_binary.py`.

**The syntax engine.** The weekly job *GS1 Barcode Syntax Engine update check*
(`.github/workflows/engine-update.yml`) opens an issue when a newer release exists, with what changes in the
dictionary, the engine messages that need a translation and the portal's test results. To update, change the
release in one place, `x-gs1-syntax-engine` in `docker-compose.yml`; build the engine
(`portal/tools/build-syntax-engine.sh <dir>`), regenerate the dictionary (`python portal/tools/gen_dictionary.py
<dir>`) and the messages (`python portal/tools/gen_engine_messages.py <dir>`), add the new or changed messages to
both languages of `i18n.js` (`engine.*`; the English one is the engine's text, parameters as `{p1}`, `{p2}`…), run
every test, commit; on the server `docker compose up -d --build`. Every image, the build script, CI and the tests
follow the one release (`test_deploy.py` fails when something holds a release of its own; `test_dictionary.py` and
`test_engine_messages.py` when a file was made from another or a message has no translation).

## 15. Conventions

- Code, comments, identifiers, commit messages and documents in British English; user-facing text in
  pt-BR and en-GB.
- Official variable names and behaviour kept; deliberate changes documented in the changelog.
- No organisation names or instance values in the code: `FQDN`, `RESOLVER_ORG_*`, `RESOLVER_CONTACT_*`.
- Secrets never printed or committed; `.env.example` holds development defaults only.
- One topic per commit, with a message explaining why; every test passes before delivery.
- Docstrings on every function written for the fork; the official functions keep their original form.
- Documentation in British English only; the interface's texts (`i18n.js`, `mailtexts.py`, `web_pages.py`) stay in
  pt-BR and en-GB.
