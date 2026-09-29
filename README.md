# GS1 Digital Link Resolver CE — Expansion Pack

> **Important notice and disclaimer (from the official project).** This freely licensed open source
> software is not maintained by GS1. Issues raised here may be answered by the community but will not be
> handled by GS1 itself. Users of this software should not assume that it conforms fully to the published
> [GS1-Conformant Resolver standard](https://ref.gs1.org/standards/resolver/).

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

The changes are meant to be offered back to the official project.

<p align="center">
  <img src="Documentation/images/home.png" alt="Home page of the resolver" width="820">
</p>

---

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
13. [Repository layout](#repository-layout)
14. [Licence and credits](#licence-and-credits)

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
| **Portal** (`/portal/`) | Sign-in with per-user passwords; editor for any primary key and qualifiers, with live GS1 checks; targets by GS1 link type, language and title; default link; per-link query-string forwarding; QR code labels (PNG/SVG) with the dimensions of the *QR Codes powered by GS1* guidelines, optionally with GS1 Digital Link data attributes (expiry, weight, price…); record list with search; spreadsheet import/export (XLSX, CSV) with preview; link checker |
| **Governance** | Roles (administrator, editor, reader); access limited to GS1 Company Prefixes per user; user administration screen with temporary passwords; history of every record with restore; audit trail with filters and CSV export |
| **Keys and qualifiers** | All 16 primary keys of URI Syntax §4.3 and all key qualifiers of §4.4, with the formats of §4.6, the path order and compound paths of §4.9, validated as the GS1 Barcode Syntax Engine does |
| **Data attributes** | Every data attribute of URI Syntax §4.10 in QR codes, validated by the GS1 Barcode Syntax Engine (formats, check digits, dates, code lists and the association rules of the General Specifications); passed on by the resolver to the targets |
| **Resolver** | Qualifier walk-up (serial → batch → variant → key), 404 rules, `linkType` forms, `defaultLink`, RFC 9264 linkset valid against GS1's schema, JSON-LD on request, `fwqs` per link, HTML pages in pt-BR / en-GB for browsers |
| **Data entry API** | `GET /api/summary` (all records in one request); `GET /api/index` now requires the token; Swagger "Authorize" works on every protected operation |
| **Configuration** | `.env.example` defaults + optional `.env` for every service; description file (`/.well-known/gs1resolver`) built from the configuration; bind addresses for the published ports |
| **Home page** (`/`) | Menu to the portal, the API documentation, the GS1 Digital Link standard, gs1.org and this code; domain independent |
| **Operations** | Interactive installer for Ubuntu 22.04 / 24.04; daily backup of the database and the portal's configuration; Compose restarts the proxy when a service behind it is recreated |
| **Quality** | Development tests for the resolver, the data entry API, the portal (unit and browser end-to-end), the home page, the installer and the link checker; comparison with the GS1 Syntax Engine |

The full change log is in [Documentation/extensions/CHANGELOG.md](Documentation/extensions/CHANGELOG.md) and
the detailed documentation in [Documentation/extensions/README.md](Documentation/extensions/README.md).

## Architecture

```mermaid
flowchart LR
    client["Scanner / browser"] -->|HTTPS| edge["Host nginx + Certbot<br/>(TLS, port 443)"]
    edge -->|"127.0.0.1:8080"| proxy["frontend-proxy-service<br/>nginx"]
    proxy -->|"/  and  /home/"| home["Home page<br/>(static, in the proxy image)"]
    proxy -->|"/{AI}/{value}…"| web["web-service<br/>resolver"]
    proxy -->|"/api"| de["data-entry-service<br/>REST API + Swagger"]
    proxy -->|"/portal/"| portal["portal-service<br/>link management portal"]
    portal -->|"bearer token"| de
    web --> db[("MongoDB<br/>database-service")]
    de --> db
    portal -.->|"users, history"| vol[("volume<br/>resolver-portal-config")]
```

| Service | Container | Role | Published |
|---|---|---|---|
| `frontend-proxy-service` | `frontend-proxy-server` | Routes `/`, `/api`, `/portal/` and every Digital Link; serves the home page | `${PROXY_BIND_ADDRESS}:8080` |
| `web-service` | `resolver-web-server` | Resolves GS1 Digital Links (redirects, linksets, HTML pages) | internal |
| `data-entry-service` | `data-entry-server` | REST API to create, read, update and delete records | internal (via `/api`) |
| `portal-service` | `resolver-portal` | Link management portal (Flask + static front end) | internal (via `/portal/`) |
| `database-service` | `database-server` | MongoDB | `${DATABASE_BIND_ADDRESS}:27017` |

The portal is a back end between the browser and the data entry API: the API token never reaches the
browser, and the portal reads before writing to use the API's operations safely (POST appends, PUT merges,
DELETE removes links, the default link type is shared by all records of a key).

## The link management portal

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
X-dimension 0.495 mm, 4X quiet zone, optional human-readable interpretation) and buttons to
try or copy the link. After each save the targets are checked (see below).

<p align="center">
  <img src="Documentation/images/portal-attributes.png" alt="QR code panel with an expiry date and a net weight as data attributes" width="300">
</p>

**Data attributes** — ticking *Include data attributes* below the QR code adds GS1 Digital Link data
attributes (URI Syntax §4.10) such as expiry date (17), net weight (3103) or price to the QR code:
`https://id.example.org/01/…/10/B42?17=271231&3103=000500`. Attributes are chosen by number or name from
the 500-odd AIs the standard allows, with their format explained, and checked as they are typed by the GS1
Barcode Syntax Engine. They describe the item the code is printed for, so they are **not stored**: they
go only in the code drawn at that moment and are cleared when another record is opened. The resolver
passes them on to targets that forward the query string. An attribute can never change the
identification: batch, serial or variant of a GTIN are qualifiers of their own record, not attributes.

<p align="center">
  <img src="Documentation/images/portal-records.png" alt="Record list with search, spreadsheet buttons and link check result" width="820">
</p>

**Record list** (`/portal/#records`) — every record on the resolver with identifier, qualifiers, number of
links and last change (date and user); search by identifier (leading zeros optional), description or
qualifier, ignoring case and accents; filter by who changed it; open a record in the editor.

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
failures, 8-hour sliding sessions. The interface follows the browser's language (pt-BR or en-GB) and can be
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

Users, history and audit trail live in the portal's configuration volume, which the daily backup includes.
Users created before roles existed become administrators. The command line tool accepts roles too:
`docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234`.

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
GS1 Barcode Syntax Engine itself (release 1.4.1, the one the resolver uses), including the invalid pairs
and mandatory associations of the GS1 General Specifications §4.13; values of any character of CSET 82
are percent-encoded as needed. Up to 10 attributes per QR code.

## API reference

### Resolver (public)

| Request | Result |
|---|---|
| `GET /{AI}/{value}[/{qualifier AI}/{value}…]` | `307` redirect to the default link; walks up the qualifiers (serial → batch → variant → key) when a level has no record |
| `…?linkType=gs1:pip` (also `pip`, `https://gs1.org/voc/pip`, `defaultLink`) | Redirect to that link type; `404` if the record has none |
| `…?linkType=linkset` or `Accept: application/linkset+json` | Linkset (RFC 9264, valid against GS1's linkset schema); `application/ld+json` for JSON-LD |
| `Accept-Language`, `Accept`, `context` | Choose between links of the same type by language, media type or context |
| Browser (`Accept: text/html`) on an error | HTML page (not found, information not available with the available links, invalid code), pt-BR / en-GB |
| `GET /.well-known/gs1resolver` | Resolver description file; `resolverRoot` and `contact` from the configuration |
| `GET /` | Home page |

The query string of the scan is passed on to the target unless the link has `"fwqs": false`.

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
| `GET /config` | Resolver address, link types, languages, keys and their qualifier shapes, import limits, data attributes |
| `GET /record?key=&value=&qualifiers=` | Read one record (and the other records of the key) |
| `POST /record` | Create or replace one record (`key`, `value`, `qualifiers`, `description`, `links`) |
| `DELETE /record?key=&value=&qualifiers=` | Delete one record, keeping the others of the key |
| `GET /records` | Every record with its change history |
| `POST /export` | XLSX or CSV of every record |
| `POST /import/preview`, `POST /import/apply`, `GET /import/status` | Spreadsheet import: check, confirm, progress |
| `POST /links/check`, `POST /links/jobs`, `GET /links/jobs/{token}`, `GET /links/last` | Link checker |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&attr=AI:value…` | QR code label, optionally with data attributes |
| `POST /digital-link` | The GS1 Digital Link URI of a record with data attributes (`attributes: [{ai, value}]`), checked by the syntax engine; nothing is stored |
| `GET /history?key=&value=&qualifiers=` | Versions of a record (with content) |
| `GET /users`, `POST /users`, `PUT /users/{name}`, `POST /users/{name}/reset`, `DELETE /users/{name}` | User administration (administrators) |
| `GET /audit`, `GET /audit.csv` (`user`, `from`, `to`, `q`) | Audit trail (administrators) |
| `GET /portal/healthz` | Health of the portal and of its access to the API |

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
   (`{"portal":"ok","resolver":"ok"}`).
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
| `RESOLVER_PUBLIC_URL` | Portal's public address when it is not `https://FQDN` (e.g. development) |
| `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD` | First portal user, created only while there are none |
| `PORTAL_SESSION_HOURS`, `PORTAL_SECRET_KEY`, `PORTAL_COOKIE_SECURE` | Optional portal settings |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Host addresses of ports 8080 and 27017 (read by Compose from `.env` only) |

## Operation

```bash
git pull && docker compose up -d --build                         # update
docker compose exec portal-service python create_user.py maria --role editor   # add or reset a user
# who changed what: user menu → Audit trail (administrators), or the container log:
docker compose logs -f portal-service | grep portal.audit
sudo scripts/resolver-backup.sh                                  # backup now (database + portal users)
```

Backups go to `/var/backups/resolver` (14 days). Restore the database with
`mongorestore … --archive --gzip --drop` through `docker compose exec -T database-service`, and the portal's
configuration by extracting its archive into `/app/config` of `portal-service`; the exact commands are in
[Documentation/extensions/README.md](Documentation/extensions/README.md#daily-backup). Keep copies on
another machine.

## Development and tests

The tests in [`dev-tests/`](dev-tests/README.md) run without Docker or MongoDB:

| Test | Covers |
|---|---|
| `resolver/test_resolver.py` | Resolver behaviour, walk-up, linksets, HTML pages, description file, every key and qualified record |
| `resolver/test_data_entry_api.py` | Token protection of every data entry operation and the Swagger declarations |
| `portal/test_keys.py` | Every primary key and qualifier combination, compared with the GS1 Syntax Engine |
| `portal/test_portal_e2e.py` | The portal in Chromium: editor, keys, qualifiers, labels, list, spreadsheets, link checker, users |
| `portal/test_governance.py` | Roles, prefixes, user administration, temporary passwords, history, audit trail |
| `portal/test_data_attributes.py` | Data attributes: syntax engine and dictionary, every refusal, the API and QR codes, the portal without the engine |
| `portal/test_sheet.py`, `test_special_chars.py`, `test_linkcheck.py`, `test_portal_config.py` | Spreadsheets, special characters, link checker, start-up configuration |
| `home/test_home.py` | Home page through the real nginx configuration |
| `install/test_install.sh` | Installer in eight scenarios, with the real `docker compose config` and `nginx -t` |

```bash
pip install -r web_server/src/requirements.txt -r portal/requirements.txt jsonschema playwright opencv-python-headless
playwright install chromium
python dev-tests/resolver/test_resolver.py
# GS1 Barcode Syntax Engine for data attributes, as the portal image builds it:
bash portal/tools/build-syntax-engine.sh /tmp/gs1se
GS1_SYNTAX_ENGINE_DIR=/tmp/gs1se python dev-tests/portal/test_data_attributes.py
# optional, compares with the GS1 Syntax Engine used by the resolver:
mkdir -p /tmp/se && (cd /tmp/se && npm init -y && npm pkg set type=module && npm install gs1encoder)
GS1_SYNTAX_ENGINE=/tmp/se python dev-tests/portal/test_keys.py
```

The official integration test `tests/setup_test.py` needs the running stack and reads the token from
`SESSION_TOKEN`. The screenshots of this README are produced by `dev-tests/docs/screenshots.py`.

## Repository layout

```
.env.example                    configuration defaults (committed); .env holds installation values
docker-compose.yml              the five services
data_entry_server/              data entry API (official, with /summary and token on /index)
web_server/                     resolver (official, with conformance fixes and HTML pages)
database_server/                MongoDB image (official)
frontend_proxy_server/          nginx: routes, home page (home/), portal
portal/                         link management portal: app.py, gs1.py (keys, qualifiers), label.py,
                                sheet.py, linkcheck.py, users.py (roles), journal.py (history, audit),
                                meta.py, syntax.py (data attributes), static/ (HTML, CSS, JS, i18n),
                                tools/build-syntax-engine.sh (GS1 Barcode Syntax Engine)
scripts/                        install.sh, templates/ (nginx), resolver-backup.sh and its cron entry
dev-tests/                      development tests (see above)
Documentation/                  extensions/ (detailed documentation, changelog), images/, upstream-README.md
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
