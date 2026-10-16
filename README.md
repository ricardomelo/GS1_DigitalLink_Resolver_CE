# GS1 Digital Link Resolver CE — Expansion Pack

[![Development tests](https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE/actions/workflows/dev-tests.yml/badge.svg?branch=gs1br/develop)](https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE/actions/workflows/dev-tests.yml)

> **Important notice and disclaimer (from the official project).** This freely licensed open source
> software is not maintained by GS1. Issues raised here may be answered by the community but will not be
> handled by GS1 itself. Users of this software should not assume that it conforms fully to the published
> [GS1-Conformant Resolver standard](https://ref.gs1.org/standards/resolver/).

> **Community software; the operator is responsible.** Both the official GS1 Resolver Community Edition
> and this fork are maintained by their communities of contributors, not by GS1 or any GS1 Member
> Organisation. The software is provided "as is", without warranties or conditions of any kind (Apache
> License 2.0, sections 7 and 8).
> Whoever installs and operates an installation is solely responsible for it and for its use: its security
> and availability, the records and links it serves, and their conformance to the GS1 standards.

This repository is a fork of the official
[**GS1 Resolver Community Edition v3**](https://github.com/gs1/GS1_DigitalLink_Resolver_CE) (based on commit
[`bf885fd`](https://github.com/gs1/GS1_DigitalLink_Resolver_CE/commit/bf885fdf4888f0395229478bf6b50342c1f761a8))
maintained on branch `gs1br/develop`. It keeps the official resolver and data entry API and
adds what an organisation needs to run one for its members:

- a **link management portal** that simplifies the management of links, in Brazilian Portuguese and British English;
- every **primary identification key and key qualifier** of the
  [GS1 Digital Link URI Syntax 1.7](https://ref.gs1.org/standards/digital-link/uri-syntax/);
- **conformance fixes** to the resolver ([GS1-Conformant Resolver 1.2.1](https://ref.gs1.org/standards/resolver/))
  and HTML pages for people who open a link in a browser;
- a **home page**, a **configurable resolver description file**, **security hardening**;
- an **interactive installer for Ubuntu**, a **daily backup** and **development tests** for everything.

<p align="center">
  <img src="Documentation/images/home.png" alt="Home page of the resolver" width="820">
</p>

---

## Documentation

| | |
|---|---|
| [Portal user guide](Documentation/portal-user-guide.md) | every task in the portal, step by step, with screenshots |
| [Features](Documentation/features.md) | every feature, what it does and when it was added |
| [History](Documentation/history.md) | how the project evolved, decisions and lessons |
| [Developer guide](Documentation/developer-guide.md) | services, source files, portal API, data files, tests, how to extend |
| [Conformance review](Documentation/conformance-review.md) | the branch against GS1 Digital Link URI Syntax 1.7 and GS1-Conformant Resolver 1.2.1, clause by clause |
| [Extensions documentation](Documentation/extensions/README.md) · [Changelog](Documentation/extensions/CHANGELOG.md) | detailed rules and decisions · every change |
| [Architecture decisions](Documentation/adr/0001-portal-state-in-mongodb.md) | ADR 0001: the portal's state in MongoDB, background jobs in a worker, replicas |
| [Tenants](Documentation/adr/0002-tenants.md) | ADR 0002: organisations that own GS1 Company Prefixes, support access, an audit trail per tenant |
| [GS1 rules from the dictionary](Documentation/adr/0003-gs1-rules-from-the-dictionary.md) | ADR 0003: one source for the GS1 rules, one engine release, engine messages translated |
| [E-mail](Documentation/adr/0004-e-mail.md) | ADR 0004: an authenticated relay, invitations, password recovery, notifications |
| [Tenant API](Documentation/adr/0005-tenant-api.md) | ADR 0005: a versioned API of the portal for organisations, API keys with scopes, expiry and a request limit |
| [Request log](Documentation/adr/0006-resolver-request-log.md) | ADR 0006: the resolver records each request without personal data, daily aggregates per key, each organisation seeing its own |
| [Overview](Documentation/adr/0007-overview-indicators.md) | ADR 0007: the page after sign-in with indicators of usage, resolution quality, records, operation and governance |
| [Label studio](Documentation/adr/0010-label-studio.md) | ADR 0010: label sizes, PDF, an EAN/UPC beside the QR code, every format in one zip |
| [The organisation's own domain](Documentation/adr/0009-tenant-domains.md) | ADR 0009: domains proved by DNS, default per prefix, the resolver answering on them for their organisation only, certificates on the host |
| [Monitoring and alerts](Documentation/adr/0008-monitoring-and-alerts.md) | ADR 0008: the worker checks the resolver, the backup, the certificate and spikes of 404, and e-mails the administrators |
| [Single sign-on](Documentation/adr/0012-single-sign-on.md) | ADR 0012: each organisation's OpenID Connect provider for its users' sign-in, password sign-in off per organisation, per-role limits on exports |
| [The item's page](Documentation/adr/0011-item-page.md) | ADR 0011: the resolver's page of an item's links as the default target, branded per prefix, clicks logged, Verified by GS1 |

This README covers the overview, the API, installation and operation. The index of every document is
[Documentation/README.md](Documentation/README.md).

## Contents

1. [The original project](#the-original-project)
2. [What this fork adds](#what-this-fork-adds)
3. [Architecture](#architecture)
4. [The link management portal](#the-link-management-portal)
5. [GS1 Digital Link coverage](#gs1-digital-link-coverage)
6. [API reference](#api-reference)
7. [System requirements](#system-requirements)
8. [Installation with the Ubuntu script](#installation-with-the-ubuntu-script)
9. [Manual installation](#manual-installation)
10. [Configuration](#configuration)
11. [Operation](#operation)
12. [Development and tests](#development-and-tests)
13. [Open backlog](#open-backlog)
14. [Repository layout](#repository-layout)
15. [Licence and credits](#licence-and-credits)

---

## The original project

GS1 Resolver Community Edition is a free, open-source web application, developed by the GS1 Resolver
Community, that resolves GS1 identifiers carried in GS1 Digital Link URIs (typically in QR codes) to the web
resources registered for them: product pages, instructions, patient leaflets, recipes, traceability data and
more — the right one for *why* the code was scanned.

Version 3 is written in Python and runs as a Docker composition of four services: a **data entry service**
(REST API with a bearer token), a **web (resolving) service**, a **MongoDB** document database and a
**front-end proxy** (nginx). It stores links in the IETF Linkset format and serves multiple links per
identifier, key qualifiers, content negotiation by language and media type, and compressed Digital Links.

The original README is kept, unchanged, in [Documentation/upstream-README.md](Documentation/upstream-README.md);
the official Postman collection is at
[documenter.getpostman.com/view/10078469/2sA3JKeNb2](https://documenter.getpostman.com/view/10078469/2sA3JKeNb2).

## What this fork adds

| Area | Addition |
|---|---|
| **Portal** (`/portal/`) | Sign-in with per-user passwords (with a show/hide button); editor for any primary key and qualifiers, with live GS1 checks; targets by GS1 link type, language and title; default link; QR code labels (SVG, PNG, PDF, or all three in a ZIP) with the dimensions of the *QR Codes powered by GS1* guidelines, sizes from 80 to 200 %, an optional EAN-13, UPC-A, EAN-8 or UPC-E beside the QR code for the transition to 2D, a choice of QR version, error correction and human readable text, optionally with GS1 Digital Link data attributes (expiry, weight, price…); record list with search and filters by key type and qualifier; spreadsheet import/export (XLSX, CSV) with preview; link checker; for a serial number, its EPC (SGTIN-96 or SGTIN-198) and the compressed link (`eh…`, `ex…`) for RFID and NFC tags |
| **Governance** | Roles (administrator, editor, reader); organisations (tenants) that own GS1 Company Prefixes, each with its own users and audit trail, and a server administrator with recorded, read-only support access; access limited to GS1 Company Prefixes per user; user administration screen with temporary passwords or, with an e-mail relay, invitations by e-mail; API keys for the organisations' own systems (tenant API); password recovery by e-mail; security notices; history of every record with restore; audit trail with filters and CSV export; single sign-on with each organisation's own identity provider (OpenID Connect), password sign-in off per organisation; per-role limits on exports ([ADR 0012](Documentation/adr/0012-single-sign-on.md)) |
| **Own domains** | An organisation's own domain in its QR codes (URI Syntax §4.11), with an optional path stem: proved by a DNS TXT record, default per GS1 Company Prefix or chosen on the label; either pointing at the resolver (which then answers on it for that organisation's codes only, certificates by `scripts/custom-domains.sh`) or redirected by the organisation's own server ([ADR 0009](Documentation/adr/0009-tenant-domains.md)) |
| **Item page** | A page of all the links of an item as the default target of its code: made by the resolver, mobile first, an icon per link type, the visitor's language first, the logo and colours of the brand of each GS1 Company Prefix (uploaded in the portal), page views and clicks counted apart from scans, and a link to Verified by GS1 for GTINs and GLNs when the installation switches it on ([ADR 0011](Documentation/adr/0011-item-page.md)) |
| **Keys and qualifiers** | All 16 primary keys of URI Syntax §4.3 and all key qualifiers of §4.4, with the formats of §4.6, the path order and compound paths of §4.9, built from the GS1 Barcode Syntax Dictionary of the engine release every service uses |
| **Data attributes** | Every data attribute of URI Syntax §4.10 in QR codes, validated by the GS1 Barcode Syntax Engine (formats, check digits, dates, code lists and the association rules of the General Specifications), its messages in the user's language; passed on by the resolver to the targets |
| **Resolver** | Qualifier walk-up (serial → batch → variant → key), 404 rules, `linkType` forms, `defaultLink`, RFC 9264 linkset valid against GS1's schema, JSON-LD on request, the default link unless the request decides a language variant, request paths checked by the GS1 Barcode Syntax Engine, values with `%2F`, the query string passed on exactly as sent, EPC binary strings (`/eh…`, `/ex…`) from NFC tags decompressed, HTML pages in pt-BR / en-GB for browsers |
| **Data entry API** | `GET /api/summary` (all records in one request); `GET /api/index` now requires the token; Swagger "Authorize" works on every protected operation |
| **Configuration** | `.env.example` defaults + optional `.env` for every service; description file (`/.well-known/gs1resolver`) built from the configuration; bind addresses for the published ports |
| **Request log** | The resolver records each request it answers — code, outcome, level, target, time, language, device class — without the client's address, User-Agent, serial numbers or data attribute values; daily counts per key; a *Requests* screen per user's reach, with a CSV export; the tenant API's calls ([ADR 0006](Documentation/adr/0006-resolver-request-log.md)); an **overview** opened after sign-in — usage, scanned codes nobody registered, record quality, operation and governance for the last 7, 30 or 90 days against the period before, exported to Excel and CSV and read by organisations' systems through the tenant API ([ADR 0007](Documentation/adr/0007-overview-indicators.md)) |
| **Home page** (`/`) | Menu to the portal, the API documentation, the GS1 Digital Link standard, gs1.org and this code; domain independent |
| **Operations** | Interactive installer for Ubuntu 22.04 / 24.04; daily backup of the database and the portal's configuration; monitoring by the worker with alerts by e-mail — the resolver down through the proxy, a failed or late backup, the certificate expiring, spikes of codes nobody registered ([ADR 0008](Documentation/adr/0008-monitoring-and-alerts.md)); Compose restarts the proxy when a service behind it is recreated |
| **Quality** | Development tests for the resolver, the data entry API, the portal (unit and browser end-to-end), the home page, the installer and the link checker; comparison with the GS1 Syntax Engine; GS1's own resolver test suite passed (31 of 31) and also run in the development tests |

The full change log is in [Documentation/extensions/CHANGELOG.md](Documentation/extensions/CHANGELOG.md) and
the detailed documentation in [Documentation/extensions/README.md](Documentation/extensions/README.md).

## Architecture

```mermaid
flowchart LR
    client["Scanner / browser"] -->|HTTPS| edge["Host nginx + Certbot<br/>(TLS, port 443)"]
    edge -->|"127.0.0.1:8080"| proxy["frontend-proxy-service<br/>nginx"]
    proxy -->|"/  and  /home/"| home["Home page<br/>(static, in the proxy image)"]
    proxy -->|"/{AI}/{value}…"| web["web-service ×n<br/>resolver"]
    proxy -->|"/api"| de["data-entry-service ×n<br/>REST API + Swagger"]
    proxy -->|"/portal/"| portal["portal-service ×n<br/>link management portal"]
    portal -->|"bearer token"| de
    web --> db[("MongoDB<br/>database-service")]
    de --> db
    portal -->|"own user: users, history"| db
    init["portal-db-init<br/>(one-shot)"] -.->|"creates the portal's user"| db
    worker["portal-worker ×n<br/>imports, link checks"] -->|"jobs"| db
    worker -->|"bearer token"| de
```

| Service | Containers | Role | Published |
|---|---|---|---|
| `frontend-proxy-service` | `frontend-proxy-server` | Routes `/`, `/api`, `/portal/` and every Digital Link to every replica of the services; serves the home page | `${PROXY_BIND_ADDRESS}:8080` |
| `web-service` | `WEB_SERVICE_REPLICAS` (1) | Resolves GS1 Digital Links (redirects, linksets, HTML pages) | internal |
| `data-entry-service` | `DATA_ENTRY_SERVICE_REPLICAS` (1) | REST API to create, read, update and delete records | internal (via `/api`) |
| `portal-service` | `PORTAL_SERVICE_REPLICAS` (1) | Link management portal (Flask + static front end) | internal (via `/portal/`) |
| `portal-db-init` | one, at every start | Creates or updates the portal's database user, then exits | — |
| `portal-worker` | `PORTAL_WORKER_REPLICAS` (1) | Runs the portal's background jobs (spreadsheet imports, link checks, e-mail messages) from its database; the portal's image | — |
| `mailpit` | none unless started (profile `mail-test`) | A test relay that keeps every e-mail, for trying the portal's e-mail before a real relay exists; never in production | `127.0.0.1:8025` |
| `database-service` | `database-server` | MongoDB | `${DATABASE_BIND_ADDRESS}:27017` |

The portal is a back end between the browser and the data entry API: the API token never reaches the
browser, and the portal reads before writing to use the API's operations safely (POST appends, PUT merges,
DELETE removes links, the default link type is shared by all records of a key). Its own data (users, record
metadata, history and audit trail) is in a database of its own in the same MongoDB, `resolver_portal`,
reached with a user that may use that database only; the resolver's database is never touched
([ADR 0001](Documentation/adr/0001-portal-state-in-mongodb.md)). Spreadsheet imports and checks of many links
are jobs in that database, run by `portal-worker`: they go on when the portal restarts, and a job interrupted
by a worker restart continues where it was.

None of the four services in the middle of the table keeps state of its own, so each can run as several
containers (replicas); their number is set in `.env` (one of each by default). Compose names them
`<project>-<service>-<n>`, for example `gs1_digitallink_resolver_ce-web-service-2`. The proxy asks Docker's
DNS for the addresses of each service every 10 seconds and shares the requests among them, so replicas can
be added or removed without restarting it. Inside each container of the three web services, gunicorn runs
two processes by default (`*_PROCESSES`). The database and the proxy run once, under their official names.

## The link management portal

Step-by-step instructions for every task are in the [portal user guide](Documentation/portal-user-guide.md).

<p align="center">
  <img src="Documentation/images/portal-editor.png" alt="Portal editor with a GTIN, its qualifiers, targets and QR code" width="640">
</p>

**Editor** — three steps:

1. **What the code identifies:** identifier type (GTIN, SSCC, GLN, GIAI…), value and key qualifiers
   (variant, batch, serial…). Check digits, the GMN check-character pair, the GS1 Company Prefix and the
   allowed combinations are checked as you type.
2. **Description** of the item.
3. **Targets:** one row per web address, with its GS1 link type (e.g. `gs1:pip`, `gs1:epil`,
   `gs1:recallStatus`), language (any BCP 47 tag) and title. The first target is the default link
   (`gs1:defaultLink`); each target can forward the scan's query string or not.

The preview shows the Digital Link with its parts coloured, the **QR code label** (download as PNG or SVG,
X-dimension 0.495 mm, 4X quiet zone) and buttons to try or copy the link. Label options: human readable
text in full (every element string), for the key only or none; QR code version (automatic, the
smallest that fits, or 1 to 40) and error correction level (L, M — the default —, Q, H), shown under the
code as used. If a chosen version is too small for the content, an explanation with the version needed
replaces the image. When the key has other records (the product, its batches, serials, variants…), a list
under *Open record* shows them five at a time, with a search, a filter by key qualifier and a button to open
each one (after a confirmation if the record being edited has unsaved changes). The label block sits under the form, with the code and its buttons on the left and the
options on the right. After each save the targets are checked (see below).

<p align="center">
  <img src="Documentation/images/portal-attributes.png" alt="Label block with the QR code, its options and an expiry date and a net weight as data attributes" width="820">
</p>

**Data attributes** — ticking *Include data attributes* below the QR code adds GS1 Digital Link data
attributes (URI Syntax §4.10) such as expiry date (17), net weight (3103) or price to the QR code:
`https://id.example.org/01/…/10/B42?17=271231&3103=000500`. Attributes are chosen by number or name from
the 500-odd AIs the standard allows (the record's own key and qualifiers are left out), in a list that
opens with a click and filters as you type, with their format explained, put in order with ↑ ↓, and
checked as they are typed by the GS1 Barcode Syntax Engine. Measures and amounts whose last digit is the
number of decimal places are offered as families — (310n) NET WEIGHT (kg), (392n) PRICE — and take the
number as people write it, with a comma or point: `123,45` becomes `3102=012345`. Day 00 in dates ("end of month" in GS1
syntax) is refused in favour of an explicit first or last day of the month. They describe the item the code is printed for, so they are **not stored**: they
go only in the code drawn at that moment and are cleared when another record is opened. The resolver
passes them on to targets that forward the query string. An attribute can never change the
identification: batch, serial or variant of a GTIN are qualifiers of their own record, not attributes.

<p align="center">
  <img src="Documentation/images/portal-records.png" alt="Record list with search, filters by key type and qualifier, spreadsheet buttons and link check result" width="820">
</p>

**Record list** (`/portal/#records`) — every record on the resolver with identifier, qualifiers, number of
links and last change (date and user); search by identifier (leading zeros optional), description or
qualifier, ignoring case and accents; filter by primary key type (GTIN, SSCC, GLN…), by key qualifier
(batch, serial, variant… or none) and by who changed it; paste a GS1 Digital Link or an element string
such as `(01)…(10)…` to find its exact record and the related ones; open a record in the editor.

**Spreadsheets** — export every record as XLSX (with reference sheets for link types, keys and languages)
or CSV; import in two steps: a preview validates every row with the editor's rules and shows what will be
new, changed, unchanged or wrong (with the row and the reason), and nothing is written until you confirm.
Records not in the file are never deleted. Limits per imported file (also shown in the import dialog):

| Format | Files accepted | Data rows (header not counted) | Size |
|---|---|---|---|
| Excel | `.xlsx` (first sheet) | up to 5 000 | up to 700 KB |
| CSV or text | `.csv`, `.txt` | up to 5 000 | up to 700 KB |

Whichever limit is reached first applies. 5 000 rows take about 200–300 KB in XLSX, so the row limit
counts there; in CSV each row takes about 180–370 bytes, so 700 KB is usually reached first, at about
2 000–3 900 rows. Use XLSX or split the file for larger batches. The size limit follows from the portal's
1 MB request limit (the file travels base64-encoded); the values are set in `FORMATS` in `portal/sheet.py`.

CSV and text files may be separated by `;`, `,` or tab and encoded in UTF-8, UTF-16 or Windows-1252. How
the portal treats accents, invisible characters, line breaks and formulas is described in
[Special characters](Documentation/extensions/README.md#special-characters).

<p align="center">
  <img src="Documentation/images/portal-import.png" alt="Spreadsheet import preview" width="720">
</p>

**Link checker** — after each save, on demand in the editor, for every record in the background (with a
filter for records with problems) and, optionally, in the import preview. It reports HTTP errors, addresses
that do not answer, redirects from HTTPS to HTTP and endless redirects; sites that refuse robots (401, 403,
429) are reported as such. Only public addresses are contacted, so the portal cannot be used to probe the
server's own network. Sites that answer "200" for missing pages ("soft 404") cannot be detected.

**Users and sessions** — per-user passwords (salted scrypt hashes), sign-in lockout after repeated
failures, sessions that end after 30 minutes without use (with a warning before) and 12 hours after the
sign-in at the latest. The interface follows the browser's language (pt-BR or en-GB) and can be
switched at any time.

### Governance

| Role | May |
|---|---|
| **Administrator** | everything, including user administration and the audit trail |
| **Editor** | create, change and delete records, import spreadsheets, check links |
| **Reader** | consult records and the list, export spreadsheets, download labels |

- **GS1 Company Prefixes per user** — a user limited to one or more prefixes only sees and changes
  identifiers of those prefixes (the prefix is looked for after the indicator digit of a GTIN-14, the
  extension digit of an SSCC and the filler zero of a GRAI); without prefixes, every identifier.
- **Users screen** (administrators, user menu → *Users*): create users with a **temporary password** shown
  once and changed at the first sign-in; change role and prefixes; reset a password (which ends the user's
  open sessions); disable, enable or remove. The last active administrator cannot be removed or demoted,
  and nobody can lock themselves out.
- **History** of every record (editor → *History*): who changed it, when and how, with the full content
  of each version; *Restore this version* brings an earlier version (or a deleted record) back into the
  form for review before saving.
- **Audit trail** (administrators, user menu → *Audit trail*): sign-ins, refused sign-ins, record
  changes, imports, exports and user administration, filtered by user, period and identifier, with CSV
  export.

Users, organisations, history and audit trail live in the portal's own MongoDB database, which the daily
backup includes. Users created before roles existed become administrators. The command line tool accepts roles
and organisations too:
`docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234`.

- **Organisations** (server administrators, user menu → *Organisations*): an installation may serve several
  organisations, each owning its GS1 Company Prefixes, with its own users and audit trail. The operator's
  administrators are server administrators; they reach an organisation's records only through read-only support
  access, recorded in its audit trail. An installation without organisations works as before
  ([ADR 0002](Documentation/adr/0002-tenants.md)).

<p align="center">
  <img src="Documentation/images/portal-users.png" alt="User administration with roles, prefixes and a temporary password" width="720">
</p>

## GS1 Digital Link coverage

**Primary identification keys** (URI Syntax 1.7, §4.3):

| AI | Key | AI | Key |
|---|---|---|---|
| 01 | GTIN | 8017 / 8018 | GSRN (provider / recipient) |
| 8006 | ITIP | 255 | GCN |
| 8013 | GMN | 00 | SSCC |
| 8010 | CPID | 253 | GDTI |
| 414 | GLN (physical location) | 401 | GINC |
| 415 | GLN (invoicing party) | 402 | GSIN |
| 417 | GLN (party) | 8003 / 8004 | GRAI / GIAI |

**Key qualifiers** (§4.4, formats of §4.6, path order and compound paths of §4.9):

| Key | Qualifiers, in path order |
|---|---|
| GTIN (01) | 22 variant → 10 batch/lot → 21 serial, **or** 235 (UPUI) |
| ITIP (8006) | 10 batch/lot → 21 serial |
| CPID (8010) | 8011 CPID serial |
| GLN (414) | 254 GLN extension, **or** 7040 (FID) |
| GLN (415) | 8020 payment reference (**required**) |
| GLN (417), GIAI (8004) | 7040 (EOID, MID) |
| GSRN (8017, 8018) | 8019 service relation instance |

Validation matches the [GS1 Barcode Syntax Engine](https://github.com/gs1/gs1-syntax-engine), which the
resolver uses to accept every request (the development tests compare both case by case). Two deliberate
limits: alphanumeric values use letters, digits, `.`, `-` (and `_` in qualifiers) only, because the data
entry service maps `/` to `_` in document ids and other symbols would need percent-encoding; and ITIP is
offered without 22, which the Syntax Engine refuses without a GTIN.

**Data attributes** (§4.10): every AI the GS1 Barcode Syntax Dictionary marks as a GS1 Digital Link data
attribute, which excludes (8200), (03) and (8014) as the standard does. The portal validates them with the
GS1 Barcode Syntax Engine itself (the release written in `docker-compose.yml`, the one the resolver uses), including the invalid pairs
and mandatory associations of the GS1 General Specifications §4.13; values of any character of CSET 82
are percent-encoded as needed. There is no fixed number of attributes per QR code: the label says when the
content no longer fits the chosen QR version.

## API reference

### Resolver (public)

| Request | Result |
|---|---|
| `GET /{AI}/{value}[/{qualifier AI}/{value}…]` | `307` redirect to the default link; walks up the qualifiers (serial → batch → variant → key) when a level has no record |
| `…?linkType=gs1:pip` (also `pip`, `https://gs1.org/voc/pip`, `defaultLink`) | Redirect to that link type; `404` if the record has none |
| `…?linkType=linkset` or `Accept: application/linkset+json` | Linkset (RFC 9264, valid against GS1's linkset schema); `application/ld+json` for JSON-LD |
| `Accept-Language`, `Accept`, `context` | Choose between links of the same type by language, media type or context |
| Browser (`Accept: text/html`) on an error | HTML page (not found, information not available with the available links, invalid code), pt-BR / en-GB |
| `GET /eh{hexadecimal}`, `GET /ex{base 64}` | EPC binary string (e.g. from an NFC tag) resolved as the GS1 Digital Link it stands for; data attributes it carries are passed on in the query string; `400` if it does not decode |
| `GET /.well-known/gs1resolver` | Resolver description file; `resolverRoot` and `contact` from the configuration (`resolverRoot` is the organisation's domain and stem when asked on one) |
| `…?linkType=linkset` in a browser; `…?linkType=linkset&view=page` | The item's page: the brand of the prefix, a button per link, the visitor's language first, Verified by GS1 when switched on; with `view=page` (a record's default target) counted as a page view ([ADR 0011](Documentation/adr/0011-item-page.md)) |
| `GET /_click?a=&l=&i=&t=` · `GET /_brand/{prefix}` | A button of the item's page: the link found again in the record, counted as a click, `302` to it (never to an address taken from the request) · a brand's logo |
| The same requests on an organisation's verified domain (`https://id.brand.example[/stem]/01/…`) | Resolved for that organisation's codes only (others: `404`), the stem removed ([ADR 0009](Documentation/adr/0009-tenant-domains.md)) |
| `GET /` | Home page |

The query string of the scan is passed on to the target exactly as it was sent (GS1-Conformant Resolver 2.12).

### Data entry API (`/api`, bearer token)

Every operation except `/api/heartbeat` requires `Authorization: Bearer <SESSION_TOKEN>`. Interactive
documentation: `https://<FQDN>/api/docs` (**Authorize** with `Bearer <token>`).

| Operation | Origin | Purpose |
|---|---|---|
| `POST /api/new` | official | Create records; appends to an existing document (v3 format, list accepted, v2 converted) |
| `GET /api/{AI}/{value}` | official | Read every record (entry) of a key |
| `GET /api/{AI}/{value}/{qualifiers…}` | official | Read the entry of a qualifier set |
| `PUT /api/{AI}/{value}` | official | Merge-update an entry (links matched by type, language and context) |
| `DELETE /api/{AI}/{value}` | official | Delete the document, or only the links sent in the body |
| `GET /api/index` | official, **now protected** | Identifiers of every document |
| `GET /api/summary[?links=true]` | **new** | One line per record: anchor, qualifiers, description, default link type, number of links (and the links) |
| `POST /api/validate` | **new** | What `POST /new` would refuse in one or more entries (registration rules and values), nothing stored: `{"problems": [{"item", "error"}]}` |
| `GET /api/heartbeat` | official | Liveness (public) |

```bash
TOKEN=…   # SESSION_TOKEN from .env
curl -s -X POST https://id.example.org/api/new -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{
  "anchor": "/01/09506000134352", "qualifiers": [{"10": "L2026A"}], "itemDescription": "Organic açaí 500 g",
  "defaultLinktype": "gs1:pip",
  "links": [{"linktype": "gs1:pip", "href": "https://brand.example/acai", "title": "Product information", "hreflang": ["en"]}]
}'
curl -s -H "Authorization: Bearer $TOKEN" "https://id.example.org/api/summary?links=true"
curl -sI https://id.example.org/01/09506000134352/10/L2026A        # 307 → https://brand.example/acai
```

### Portal API (`/portal/api`, session cookie)

Used by the portal's own pages; listed for integrators and reviewers. Writes require a same-origin request
with a JSON body; messages are returned as language-neutral codes translated by the browser. Every call
checks the user's role and GS1 Company Prefixes.

| Operation | Purpose |
|---|---|
| `POST /login`, `POST /logout`, `POST /password` | Sign in, sign out, change password |
| `GET /config` | Resolver address, link types, languages, keys and their qualifier shapes, import limits, data attributes, session limits |
| `GET /session` | Renews the session (used by the page while the user works without server calls) |
| `GET /record?key=&value=&qualifiers=` | Read one record (and the other records of the key) |
| `POST /record` | Create or replace one record (`key`, `value`, `qualifiers`, `description`, `links`, `landingPage`) |
| `DELETE /record?key=&value=&qualifiers=` | Delete one record, keeping the others of the key |
| `GET /records` | Every record with its change history |
| `POST /export` | XLSX or CSV of every record, or of the records a filtered list shows (`only`) |
| `POST /import/preview`, `POST /import/apply`, `GET /import/status` | Spreadsheet import: check, confirm, progress |
| `POST /links/check`, `POST /links/jobs`, `GET /links/jobs/{token}`, `GET /links/last` | Link checker |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:value…` | QR code label, optionally with data attributes; headers `X-QR-Version`, `X-QR-Level`, `X-QR-Modules` |
| `POST /digital-link` | The GS1 Digital Link URI of a record with data attributes (`attributes: [{ai, value}]`), checked by the syntax engine; nothing is stored |
| `GET /history?key=&value=&qualifiers=` | Versions of a record (with content) |
| `GET /users`, `POST /users`, `PUT /users/{name}`, `POST /users/{name}/reset`, `DELETE /users/{name}` | User administration (administrators) |
| `GET /audit`, `GET /audit.csv` (`user`, `from`, `to`, `q`) | Audit trail (administrators) |
| `GET /portal/healthz` | Health of the portal, of its access to the API and of its job worker (`worker`: `ok` or `unavailable`); whether e-mail is configured (`mail`: `on` or `off`) |
| `GET /keys`, `POST /keys`, `DELETE /keys/{id}` | API keys of the tenant API (administrators, for their own organisation or the operator) |
| `POST /sso/start` `{email}`, `GET /portal/sso/callback` · `GET /sso`, `PUT /sso/{scope}`, `DELETE /sso/{scope}`, `POST /sso/{scope}/test` | Single sign-on: the provider's address for an e-mail, the provider's answer · each organisation's OpenID Connect configuration (administrators; server administrators every one) |
| `GET /branding`, `PUT /branding/{prefix}`, `DELETE /branding/{prefix}`, `GET /branding/{prefix}/logo` | Brands of the item's page per GS1 Company Prefix (administrators; `*` the installation's default, server administrators) |

### Tenant API (`/portal/api/v1`, API key)

For an organisation's own systems (an ERP, a PIM, a shop): the same rules as the portal, limited to the
organisation's records ([ADR 0005](Documentation/adr/0005-tenant-api.md)). An administrator creates a key in the
portal (user menu → **API keys**: scopes, optional prefixes, validity) and sees it once; every call sends it as
`Authorization: Bearer rk_<id>.<secret>`. The description is public: `GET /portal/api/v1/openapi.json`
(OpenAPI 3.1). Requests are limited per key (120 a minute by default; then 429 with `Retry-After`).

| Operation | Scope | Purpose |
|---|---|---|
| `GET /portal/api/v1/` | any | The key, its organisation, its limit |
| `GET /portal/api/v1/records?key=&limit=&after=` | `records:read` | The records within reach, a page at a time |
| `GET /portal/api/v1/records/{key}/{value}?qualifiers=/10/L1` | `records:read` | One record: description, links, Digital Link |
| `PUT /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | Create (201) or replace (200): `{description, links: [{linkType, url, title, hreflang}], landingPage}` (`landingPage: true`: the item's page as the default target) |
| `DELETE /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | Delete one record |
| `GET /portal/api/v1/labels/{key}/{value}?format=svg\|png&…` | `labels:read` | The QR code label, with the options of the portal's (also `domain=default\|installation\|<verified domain>`, `size=80…200`, `linear=auto\|upce`, `format=pdf\|zip`) |
| `GET /portal/api/v1/stats?days=7\|30\|90` | `stats:read` | Usage, resolution quality and record quality of the key's reach, as on the portal's overview |

```bash
curl -s -H "Authorization: Bearer $KEY" https://id.example.org/portal/api/v1/records/01/09506000134352
curl -s -X PUT -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"description":"Organic açaí 500 g","links":[{"linkType":"gs1:pip","url":"https://brand.example/acai","hreflang":["en"]}]}' \
  https://id.example.org/portal/api/v1/records/01/09506000134352
```

## System requirements

| | Requirement |
|---|---|
| **Operating system** | Ubuntu Server 22.04 or 24.04 LTS for the installer; any Linux (x86-64 or ARM64) with Docker for a manual installation |
| **Software** | Docker Engine with the Compose plugin **2.24 or later** (the installer installs both); nginx and Certbot when the server terminates TLS; `git` |
| **Hardware** (guidance) | 2 vCPU, 2 GB RAM (4 GB recommended), 10 GB free disk for images, database and backups |
| **Network** | A DNS name (e.g. `id.example.org`) pointing to the server; ports 80 and 443 reachable (or a load balancer/proxy that terminates TLS); outbound HTTPS for building the images (Docker Hub, PyPI, npm, NodeSource, GitHub for the GS1 Barcode Syntax Engine) and for the link checker |
| **Portal users** | A current browser (Chrome, Edge, Firefox, Safari) |
| **Development** (optional) | Python 3.12, nginx, Playwright with Chromium; a C compiler and `make` for the GS1 Barcode Syntax Engine; Node.js for the comparison with the GS1 Syntax Engine |

## Installation with the Ubuntu script

On a server with a DNS name pointing to it:

```bash
git clone https://github.com/ricardomelo/GS1_DigitalLink_Resolver_CE.git
cd GS1_DigitalLink_Resolver_CE
git switch gs1br/develop            # if it is not the default branch
sudo scripts/install.sh
```

The script asks, validating each answer:

| Question | Notes |
|---|---|
| Domain name | Without `https://` |
| HTTPS mode | `letsencrypt` (nginx + free certificate, renewed automatically), `certificate` (your PEM files), `external` (TLS on a load balancer or another proxy) |
| E-mail / certificate files | Let's Encrypt notices, or the paths of your certificate and key |
| Operator | Organisation name (required), website, address, telephone — published in `/.well-known/gs1resolver` |
| First portal user | Name and password; leave the password empty to have one generated and shown once |
| Daily backup, docker user | Cron at 02:30; the account allowed to run `docker` without `sudo` |

After a summary and your confirmation it installs Docker and nginx/Certbot if needed, **generates the
MongoDB password and the API token**, writes `.env` (mode 600), builds and starts the services, waits until
they answer, removes the first user's password from `.env`, configures nginx and the certificate, schedules
the backup and checks the public address. The log is `/var/log/gs1-resolver-install.log` (never the
passwords).

**Running it again** is how settings change or an installation is repaired: current values are offered as
defaults, secrets, users and data are kept, a site that already has a certificate is kept, the previous
`.env` is saved as `.env.bak-<date>`. For automation:

```bash
sudo FQDN=id.example.org TLS_MODE=letsencrypt CERTBOT_EMAIL=ops@example.org \
     RESOLVER_ORG_NAME="Example Org" PORTAL_ADMIN_USERNAME=admin \
     scripts/install.sh --non-interactive
```

## Manual installation

1. **Docker.** Install Docker Engine and the Compose plugin (≥ 2.24) following
   [docs.docker.com/engine/install](https://docs.docker.com/engine/install/).
2. **Code.** Clone this repository and switch to `gs1br/develop`.
3. **Configuration.** Create `.env` next to `docker-compose.yml` (values here replace `.env.example`):

   ```bash
   PASS=$(openssl rand -hex 24); TOKEN=$(openssl rand -hex 32)
   cat > .env <<EOF
   MONGO_INITDB_ROOT_USERNAME='gs1resolver'
   MONGO_INITDB_ROOT_PASSWORD='$PASS'
   MONGO_URI='mongodb://gs1resolver:$PASS@database-service:27017'
   SESSION_TOKEN='$TOKEN'
   FQDN='id.example.org'
   RESOLVER_ORG_NAME='Example Org'
   PORTAL_ADMIN_USERNAME='admin'
   PORTAL_ADMIN_PASSWORD='choose-a-long-password'
   PROXY_BIND_ADDRESS='127.0.0.1'
   DATABASE_BIND_ADDRESS='127.0.0.1'
   EOF
   chmod 600 .env
   ```

4. **Start.** `docker compose up -d --build`, then check `curl -s http://127.0.0.1:8080/portal/healthz`
   (`{"portal":"ok","resolver":"ok","worker":"ok","mail":"off"}`) and a request that reaches the resolver through the proxy:
   `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/.well-known/gs1resolver` (`200`). The
   health check reaches the web server directly, without the proxy's resolver route.
5. **HTTPS.** Put a TLS reverse proxy in front of `127.0.0.1:8080`. With nginx: copy
   `scripts/templates/nginx-site-http.conf` to `/etc/nginx/sites-available/gs1resolver`, replace `@FQDN@`
   and `@PROXY_PORT@` (8080), enable it, then `sudo certbot --nginx -d id.example.org --redirect`.
6. **First user.** Sign in at `https://id.example.org/portal/` with `PORTAL_ADMIN_*`, change the password
   under Options, then clear `PORTAL_ADMIN_PASSWORD` in `.env`. Or create users with
   `docker compose exec portal-service python create_user.py <name>`.
7. **Backup.** `sed "s|REPOSITORY|$PWD|" scripts/resolver-backup.cron | sudo tee /etc/cron.d/resolver-backup`.

For a **development machine** no `.env` is needed: `docker compose up -d --build` runs with the defaults of
`.env.example` (token `secret`, as in the official project). Add `RESOLVER_PUBLIC_URL=http://localhost:8080`
to `.env` to use the portal over plain HTTP, then open http://localhost:8080/.

## Configuration

Every service reads `.env.example` (committed development defaults) and then `.env` (installation values,
never committed).

| Variable | Purpose |
|---|---|
| `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` | MongoDB root user (applied when the database volume is created) |
| `MONGO_URI` | Connection string of the web and data entry services |
| `SESSION_TOKEN` | Bearer token of the data entry API (also used by the portal) |
| `FQDN` | Domain of the resolver; the resolver root is `https://FQDN` |
| `RESOLVER_ORG_NAME`, `RESOLVER_ORG_URL`, `RESOLVER_CONTACT_*` | Operator in the description file, on the home page and on the resolver's pages (name linked to `RESOLVER_ORG_URL`) |
| `RESOLVER_TERMS_URL` | Optional: the operator's terms of use, published as `termsOfUse` in the description file (left out when empty) |
| `RESOLVER_PUBLIC_URL` | Portal's public address when it is not `https://FQDN` (e.g. development) |
| `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD` | First portal user, created only while there are none |
| `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD` | The portal's own database and user (created by `portal-db-init`); the installer generates the password |
| `PORTAL_SECRET_KEY` | Key that signs the portal's sessions; every portal replica must share it (the installer generates it; empty: a key kept in the portal's volume) |
| `PORTAL_JOURNAL_SESSION_DAYS` (180), `PORTAL_JOURNAL_RECORD_DAYS` (0), `PORTAL_JOURNAL_ADMIN_DAYS` (0) | Days the journal keeps sign-ins, record changes and administration events (0 = for ever) |
| `PORTAL_MAIL_HOST`, `PORTAL_MAIL_PORT`, `PORTAL_MAIL_SECURITY` (`starttls`), `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD`, `PORTAL_MAIL_FROM` | The portal's e-mail relay ([ADR 0004](Documentation/adr/0004-e-mail.md)): invitations, password recovery, security notices; empty host: e-mail off. Port 587 (STARTTLS) or 465 (TLS); the installer asks for them; details and a test command in [the extensions documentation](Documentation/extensions/README.md#e-mail) |
| `PORTAL_API_RATE_PER_MINUTE` (120), `PORTAL_API_KEY_MAX_DAYS` (365) | The tenant API: requests per key and minute; the longest validity of an API key |
| `PORTAL_EXPORT_LIMITS`, `PORTAL_SSO_ALLOW_INSECURE` | The most rows one export of a role may hold, e.g. `reader:0,editor:20000` (0: none; administrators and roles not named: no limit); `1` accepts identity providers on `http` or private addresses ([ADR 0012](Documentation/adr/0012-single-sign-on.md)) |
| `RESOLVER_LOG_DAYS` (90), `RESOLVER_LOG_COUNTRY_HEADER` | The log of resolver requests ([ADR 0006](Documentation/adr/0006-resolver-request-log.md)): days each event (and each call of the tenant API) is kept, 0 switches it off; a header with a two-letter country set by a proxy in front (empty: no country) |
| `RESOLVER_VERIFIED_BY_GS1_URL` | The item's page ([ADR 0011](Documentation/adr/0011-item-page.md)): the Verified by GS1 address for a GTIN or GLN, a template with `{key}` (`gtin`, `gln`) and `{value}`; empty (default): no link |
| `PORTAL_TIME_ZONE` (UTC), `PORTAL_STATS_DAYS` (800) | The days of the daily request counts (an IANA name; the installer writes the server's) and how long the counts are kept |
| `PORTAL_MONITOR_MINUTES` (5), `PORTAL_MONITOR_URL`, `PORTAL_MONITOR_PROBE`, `PORTAL_MONITOR_BACKUP_HOURS` (26), `PORTAL_MONITOR_TLS_HOST` (`FQDN`), `PORTAL_MONITOR_CERT_DAYS` (21), `PORTAL_ALERT_404_MIN` (20), `PORTAL_ALERT_404_FACTOR` (3) | Monitoring and alerts by e-mail ([ADR 0008](Documentation/adr/0008-monitoring-and-alerts.md)): how often the worker checks (0: off), the resolver's address through the proxy and a registered code to try, the longest time without a good backup, the certificate's host and days of warning, what makes a spike of 404 |
| `PORTAL_WORKER` (`external`) | Where imports and link checks run: `external`, the `portal-worker` service; `embedded`, a thread of the portal, for a set-up without that service |
| `PORTAL_SESSION_IDLE_MINUTES` (30), `PORTAL_SESSION_MAX_HOURS` (12), `PORTAL_COOKIE_SECURE` | Optional portal settings: minutes without use and hours after the sign-in before the session ends, Secure cookie |
| `BACKUP_COPY_TO` | An rsync destination (`user@host:/path`, or a mounted folder) to which each daily backup is copied; empty: no copy ([Documentation/extensions/README.md](Documentation/extensions/README.md#daily-backup)) |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Host addresses of ports 8080 and 27017 (read by Compose from `.env` only) |
| `WEB_SERVICE_REPLICAS`, `DATA_ENTRY_SERVICE_REPLICAS`, `PORTAL_SERVICE_REPLICAS`, `PORTAL_WORKER_REPLICAS` (1) | Containers of each service, 1 to 20 (read by Compose from `.env` only; the installer writes them) |
| `WEB_SERVICE_PROCESSES`, `DATA_ENTRY_SERVICE_PROCESSES`, `PORTAL_SERVICE_PROCESSES` (2) | gunicorn processes in each container of the three web services (read by Compose from `.env` only) |

## Operation

```bash
git pull && docker compose up -d --build                         # update
curl -s http://127.0.0.1:8080/portal/healthz                     # {"portal":"ok","resolver":"ok","worker":"ok","mail":"off"}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/.well-known/gs1resolver   # 200: resolver through the proxy
docker compose exec portal-service python create_user.py maria --role editor   # add or reset a user
# who changed what: user menu → Audit trail (administrators), or the container log:
docker compose logs -f portal-service | grep portal.audit
docker compose logs --tail=60 portal-worker                      # imports and link checks (background jobs)
sudo scripts/resolver-backup.sh                                  # backup now (every database + portal volume)
sudo scripts/restore-rehearsal.sh                                # prove the newest backup restores (a throw-away container)
sudo scripts/rotate-secrets.sh                                   # new secrets in .env and in MongoDB; services recreated
# more replicas: change e.g. WEB_SERVICE_REPLICAS=2 in .env, then
docker compose up -d                                             # adds or removes containers; the proxy follows within 10 s
docker compose ps                                                # one line per container (…-web-service-1, …-web-service-2)
docker compose build --pull frontend-proxy-service && docker compose up -d   # the latest nginx 1.30 security release
```

Set the number of replicas in `.env`, not with `docker compose up --scale`: the next `docker compose up`
(every update) goes back to the numbers in `.env`. The logs of a service show every replica, each line
prefixed with its container's name.

Backups go to `/var/backups/resolver` (14 days). Restore the database with
`mongorestore … --archive --gzip --drop` through `docker compose exec -T database-service`, then run
`docker compose up -d` (the portal's database user gets the password in `.env` again); the portal's volume
holds only the fallback session key and copies of older files. The exact commands are in
[Documentation/extensions/README.md](Documentation/extensions/README.md#daily-backup). Set `BACKUP_COPY_TO` to keep
copies on another machine. Before going live, work through the
[production checklist](Documentation/extensions/README.md#going-to-production).

## Development and tests

The tests in [`dev-tests/`](dev-tests/README.md) run without Docker or MongoDB (the portal's database is
replaced by `mongomock`; CI also runs them on a real MongoDB):

| Test | Covers |
|---|---|
| `resolver/test_resolver.py` | Resolver behaviour, walk-up, linksets, HTML pages, description file, every key and qualified record, EPC binary strings |
| `resolver/test_epc_binary.py` | EPC binary decoder: every example of the EPC Tag Data Standard, +AIDC data, `++` hostnames, refusals; optionally compared with `epc-tds` |
| `resolver/test_gs1_suite.py` | GS1's resolver test suite, its code unchanged, in Chromium against the resolver code, in seven scenarios |
| `resolver/test_data_entry_api.py` | Token protection of every data entry operation and the Swagger declarations |
| `portal/test_keys.py` | Every primary key and qualifier combination, compared with the GS1 Syntax Engine |
| `portal/test_portal_e2e.py` | The portal in Chromium: editor, keys, qualifiers, labels, list, spreadsheets, link checker, users |
| `portal/test_governance.py` | Roles, prefixes, user administration, temporary passwords, history, audit trail |
| `portal/test_data_attributes.py` | Data attributes: syntax engine and dictionary, every refusal, the API and QR codes, the portal without the engine |
| `portal/test_sheet.py`, `test_special_chars.py`, `test_linkcheck.py`, `test_portal_config.py` | Spreadsheets, special characters, link checker, start-up configuration |
| `portal/test_session.py` | Session limits, the warning before the end, renewal while the user works, other tabs; the community notice |
| `portal/test_store.py`, `test_store_mongodb.py` | The portal's database: users and the shared lock, record metadata, journal and retention, sign-in lockout, migration of older files; on a real MongoDB, the portal user's privileges and expiry by MongoDB |
| `portal/test_jobs.py`, `test_worker_processes.py` | Background jobs: the queue, claims, heartbeats, workers that stop or die, imports and link checks through the worker; on a real MongoDB, worker processes sharing the queue |
| `home/test_home.py` | Home page (with the community notice) and proxy routes through the real nginx configuration, including the Host header each service receives; replicas found through a stub DNS, added and removed while nginx runs |
| `install/test_install.sh` | Installer in nine scenarios, with the real `docker compose config` and `nginx -t` |
| `install/test_deploy.py` | Replicas and processes in `docker-compose.yml`, the proxy's run-time name resolution, each image's gunicorn command started locally, the portal's fallback session key under concurrent starts |

```bash
pip install -r web_server/src/requirements.txt -r portal/requirements.txt jsonschema playwright opencv-python-headless mongomock
playwright install chromium
python dev-tests/resolver/test_resolver.py
# GS1 Barcode Syntax Engine for data attributes, as the portal image builds it:
bash portal/tools/build-syntax-engine.sh /tmp/gs1se
GS1_SYNTAX_ENGINE_DIR=/tmp/gs1se python dev-tests/portal/test_data_attributes.py
# optional, compares with the GS1 Syntax Engine used by the resolver:
mkdir -p /tmp/se && (cd /tmp/se && npm init -y && npm pkg set type=module && npm install gs1encoder)
GS1_SYNTAX_ENGINE=/tmp/se python dev-tests/portal/test_keys.py
```

Every program can also be run through pytest, by a thin layer (`dev-tests/test_programs.py`) that runs each
one as a subprocess and prints the number of checks of each program at the end; the groups `resolver`,
`portal`, `e2e`, `home`, `install` and `database` can be chosen with `-m`:

```bash
pip install pytest
python -m pytest dev-tests                 # all (programs missing what they need are skipped)
python -m pytest dev-tests -m resolver     # one group
DEV_TESTS_STRICT=1 python -m pytest dev-tests -m portal   # as in CI: what is missing fails, not skips
```

**Continuous integration.** The workflow `.github/workflows/dev-tests.yml` runs the tests on GitHub Actions on
every push and pull request to `gs1br/develop` (changes to documentation only do not start it), in six jobs
in parallel: resolver (with EPC binary strings, the data entry API and GS1's suite), portal, portal on a
real MongoDB (a `mongo:7` service container), portal in Chromium, home page through nginx, and installer.
The portal on MongoDB is an informative job: a failure there is shown but does not fail the run (the
portal in Chromium and the installer started that way too and are required since item 2.3). The proxy test
runs on nginx 1.30 from nginx.org, as in the proxy image. The versions of Python, Node.js, the engines,
GS1's suite, Docker Compose and nginx are pinned in `.github/actions/dev-tests-setup/action.yml`; engines,
packages and the browser are cached. Each job's result, with its check counts, is on the run's summary page.

**Claude Code cloud sessions.** `CLAUDE.md` holds the conventions of this repository for Claude Code, and
`.claude/hooks/session-start.sh` prepares a cloud session for the tests: the same pieces and pinned versions as
the CI setup, installed into `~/.cache/dev-tests`, with the variables the programs read.

The official integration test `tests/setup_test.py` needs the running stack and reads the token from
`SESSION_TOKEN`. The screenshots of this README and of the user guide are produced by
`dev-tests/docs/screenshots.py`.

## Open backlog

Status on 16 October 2026 (items 4.2 to 7.1 done in session 14; 7.2 to 7.4 partly; items 9.1 to 9.7 from the staging tests of 15 and 16 October). Phase 1, the conformance baseline, is complete: the clause-by-clause review, the
registration model of GS1-Conformant Resolver 2.5.9, a default link above every record, the resolution
fixes, EPC binary strings and GS1's own resolver test suite (passed on a staging installation). Item 2.1,
the quick wins (session limits, home page, community notice), item 2.2, continuous integration (the
development tests through pytest on GitHub Actions), item 2.3, the architecture for scale (the portal's
data in MongoDB, background jobs in a worker service, replicas of every stateless service;
[ADR 0001](Documentation/adr/0001-portal-state-in-mongodb.md)), item 2.4, tenants (organisations that own
GS1 Company Prefixes, the server administrator and support access, an audit trail per organisation;
[ADR 0002](Documentation/adr/0002-tenants.md)), and item 2.5, one source for the GS1 rules (keys, qualifiers and
formats from the GS1 Barcode Syntax Dictionary, one engine release for every service, the engine's messages
translated, a weekly update check; [ADR 0003](Documentation/adr/0003-gs1-rules-from-the-dictionary.md)), and item
3.1, e-mail (an authenticated relay, invitations, password recovery by single-use link, notifications with
per-user preferences; [ADR 0004](Documentation/adr/0004-e-mail.md)), and item 3.2, the tenant API (a versioned API of
the portal for organisations' own systems, API keys with scopes, expiry and a request limit;
[ADR 0005](Documentation/adr/0005-tenant-api.md)), and item 4.1, the log of resolver requests (each request recorded
by the resolver without personal data, daily counts per key, a Requests screen;
[ADR 0006](Documentation/adr/0006-resolver-request-log.md)), and item 4.2, the overview after sign-in (indicators of
usage, resolution quality, records, operation and governance per scope, exports, `/v1/stats`;
[ADR 0007](Documentation/adr/0007-overview-indicators.md)), and item 4.3, monitoring and alerts by e-mail (the
resolver through the proxy, the backup, the certificate, spikes of 404;
[ADR 0008](Documentation/adr/0008-monitoring-and-alerts.md)), and item 5.1, the organisation's own domain in the QR
code ([ADR 0009](Documentation/adr/0009-tenant-domains.md)), and items 5.2 to 5.4, the label studio (sizes, PDF, an
EAN/UPC beside the QR code, every format in a zip; [ADR 0010](Documentation/adr/0010-label-studio.md)), and items
6.1 and 6.2, the item's page (the resolver's page of an item's links as the default target, branded per prefix, with
Verified by GS1; [ADR 0011](Documentation/adr/0011-item-page.md)), and item 7.1, single sign-on per organisation
with OpenID Connect and per-role limits on exports ([ADR 0012](Documentation/adr/0012-single-sign-on.md)), are
complete too. What was
done is in the [history](Documentation/history.md) and the [changelog](Documentation/extensions/CHANGELOG.md).
The items below are in the agreed order; sizes are relative (S, M, L). The order puts first what later items
build on: the portal's data store and tenants come before the API, e-mail and analytics, which all need to
know whose data they handle.

| Phase | # | Item | Size | Depends on |
|---|---|---|---|---|
| Production | 7.2 | **Production readiness**, on the servers: an installation on a clean machine, the off-server copy set up, a restore rehearsal, the staging secrets rotated and the [production checklist](Documentation/extensions/README.md#going-to-production) worked through (the scripts and the installer's final check of a scan through the proxy are done) | S | — |
| | 7.3 | **Polish**: review of the Portuguese AI names, logo on the home page and the resolver's pages (default link titles in the link's language, conformance review F21: done) | S | — |
| | 7.4 | **Load test and scale-out rehearsal** on staging with `dev-tests/load/load_test.py` (done): target load agreed, several replicas of the resolver and the portal, MongoDB replica set if needed, results recorded ([procedure](Documentation/extensions/README.md#load-test-and-scale-out-rehearsal)) | S | 2.3 |
| Standards | 8.1 | **Errata and Work Requests to GS1** (drafted; to be reviewed and sent by the owner): E1–E12 of the [conformance review](Documentation/conformance-review.md), and an issue on GS1's resolver test suite for erratum E12 | S | — |
| Staging feedback | 9.1 | **Item's page per record**: each record's default target may be its page, each batch or serial number deciding for itself (fixes the editor losing the option on reopening: the data entry API drops a `gs1:defaultLink`); the key's other records shown when a new one is made; the page grouped by link type, each in the phone's language or the best one available; the brand's logo as favicon; brands owned through their prefix (a moved prefix kept its brand with the old owner) | M | 6.1 |
| | 9.2 | **Administration and navigation**: a collapsible left sidebar (the current menu on phones) and every screen reviewed at phone width; an organisation's page with its prefixes, users, domains, brands, single sign-on, API keys and alerts; prefixes as rows with add and remove buttons; users' prefixes picked from the organisation's; the portal's own dialogs instead of the browser's; the overview filtered by organisation for server administrators, *Operation* for them only; a history of alerts with filters | L | 2.4, 4.3 |
| | 9.3 | **Labels**: GS1 DataMatrix and DataMatrix with a GS1 Digital Link URI; HRI as editable text in the SVG (option); module size by scanning environment from the General Specifications' symbol specification tables | M | 5.2 |
| | 9.4 | **Every link type and language of the targets**: the GS1 Web Vocabulary's link types generated with a check, ordered by key type; every ISO 639 language in a searchable list | S | 2.5 |
| | 9.5 | **Request log**: browser family and approximate location (country, region, city) derived at capture, the IP address never stored; retention set in the portal, global and per organisation | M | 4.1 |
| | 9.6 | **Domains without the terminal**: the operator's script scheduled every 5 minutes, the domain card showing the certificate's state | S | 5.1 |
| | 9.7 | **Interface languages**: Spanish, French, German, Korean, Mandarin (Simplified Chinese), Italian, Hindi, Arabic (right to left) and Japanese in the portal, the item's page, the resolver's pages, the home page and the e-mails, each named in its own language; every later delivery ends with its texts in every language | L | 9.1–9.6 |

The items of the "later" list are done: the record search reads scanners and RFID readers, exports follow the
filters (which stay in the address), serial numbers registered with their batch can be fixed, the data entry API
checks values with the engine, and the label offers the EPC of a serial number for RFID and NFC tags.

## Repository layout

```
.env.example                    configuration defaults (committed); .env holds installation values
docker-compose.yml              the services (seven: one run once at start, four with replicas; mailpit for tests)
data_entry_server/              data entry API (official, with /summary and token on /index)
web_server/                     resolver (official, with conformance fixes and HTML pages)
database_server/                MongoDB image (official)
frontend_proxy_server/          nginx: routes, home page (home/), portal
portal/                         link management portal: app.py, gs1.py (keys, qualifiers), label.py,
                                sheet.py, linkcheck.py, users.py (roles), journal.py (history, audit),
                                meta.py, store.py (database), jobs.py and worker.py (background jobs),
                                syntax.py (data attributes), static/ (HTML, CSS, JS, i18n),
                                tools/build-syntax-engine.sh (GS1 Barcode Syntax Engine)
scripts/                        install.sh, templates/ (nginx), resolver-backup.sh and its cron entry,
                                custom-domains.sh (sites and certificates of organisations' own domains),
                                restore-rehearsal.sh, rotate-secrets.sh
dev-tests/                      development tests (see above)
.github/                        workflows/dev-tests.yml (continuous integration), actions/dev-tests-setup/
CLAUDE.md, .claude/             conventions and the session start hook for Claude Code cloud sessions
Documentation/                  README.md (index), portal-user-guide.md, features.md, history.md,
                                developer-guide.md, extensions/ (detailed documentation, changelog),
                                images/ (README), adr/ (architecture decision records),
                                images/guide/ (user guide), upstream-README.md
tests/, useful_external_python_scripts/   official tests and conversion scripts
```

## Licence and credits

Licensed under the [Apache License 2.0](LICENSE), like the official project.

- **GS1 Resolver Community Edition** — the GS1 Resolver Community (original design and code by Nick
  Lansley and contributors).
- **GS1 Barcode Syntax Engine** and **GS1 Barcode Syntax Dictionary** — GS1 AISBL (Terry Burton), used by the
  resolver to validate every request and by the portal to validate data attributes (Apache License 2.0,
  downloaded and built when the images are built).

GS1, the GS1 logo and GS1 Digital Link are trademarks of GS1 AISBL.
