# GS1 Resolver CE extensions: link management portal, home page and conformance fixes

This document describes what this branch adds to GS1 Resolver Community Edition v3:

- a **link management portal** (`/portal/`) that simplifies the management of links: enter an identifier
  (with its qualifiers), a description and targets, and publish them without JSON, tokens or link-type codes;
- a **home page** at `/`;
- **conformance fixes** to the web server (GS1-Conformant Resolver standard 1.2.1) and HTML pages for
  browsers;
- a **resolver description file** built from the configuration;
- a **layered configuration** (`.env.example` defaults, `.env` per installation) and a **daily backup**.

Interfaces are available in Brazilian Portuguese and British English.

## Architecture

```
 Browser (portal user)
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
A second service from the same image, `portal-worker`, runs the long tasks (spreadsheet imports, checks of
many links): the portal stores them as jobs in its database and the worker claims and runs them, so a
restart of the portal does not stop them.

Every service in the middle of the diagram, and the worker, can run as several containers (replicas, set in
`.env`); the proxy finds each one through Docker's DNS and shares the requests among them (see
*Replicas* under [Operations](#operations)).

### Why a back end rather than an HTML page calling the API directly

Resolver CE behaves in ways that a naive form would turn into bad data:

| API behaviour | Consequence | What the portal does |
|---|---|---|
| `POST /api/new` on an existing document **appends** links (`extend`) | Saving a form twice duplicates targets | POST only for a record (key + qualifier set) not yet on the resolver; edits use `PUT` + partial `DELETE` |
| `PUT`/`DELETE` with unknown qualifiers fall back to **index 0** | Editing a new qualified record (a batch, a serial) would change another record of the same key | Reads the document first and chooses the right call |
| `defaultLinktype` is **one per key** (shared by every qualifier set of the key's document) | Changing it on one record (e.g. one batch) affects the others | Blocks the change when other records of the key exist and explains why |
| No route removes a whole **qualifier entry** | — | Recreates the document without it and restores the original on failure |
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
| `RESOLVER_ORG_NAME`, `RESOLVER_ORG_URL`, `RESOLVER_CONTACT_*` | description file `contact` (`RESOLVER_ORG_URL` as `hasURL`), footer of the home page and of the resolver pages (name linked to `RESOLVER_ORG_URL`) | `My Organisation` | the operator |
| `RESOLVER_PUBLIC_URL` | portal (printed links, Origin check, cookie flag) | empty → `https://FQDN` | usually empty |
| `PORTAL_ADMIN_USERNAME`, `PORTAL_ADMIN_PASSWORD` | portal, first user only | `admin` / `change-me-please` | chosen at installation |
| `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD` | portal, portal-db-init | `resolver_portal` (all three) | random password (installer) |
| `PORTAL_SECRET_KEY` | portal (session cookies) | empty → `secret.key` in the volume | random (installer); required when the portal's replicas run on more than one Docker host |
| `PORTAL_JOURNAL_SESSION_DAYS`, `PORTAL_JOURNAL_RECORD_DAYS`, `PORTAL_JOURNAL_ADMIN_DAYS` | portal (journal retention) | 180, 0, 0 (0 = for ever) | as the operator's policy requires |
| `PORTAL_MAIL_HOST`, `PORTAL_MAIL_PORT`, `PORTAL_MAIL_SECURITY`, `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD`, `PORTAL_MAIL_FROM` (and the optional `PORTAL_MAIL_REPLY_TO`, `PORTAL_MAIL_CA_FILE`, `PORTAL_MAIL_TIMEOUT`, `PORTAL_INVITE_HOURS`, `PORTAL_RESET_MINUTES`) | portal and its worker (e-mail, see *E-mail* below) | empty host: e-mail off | the organisation's relay (installer); the password only in `.env` |
| `PORTAL_WORKER` | portal (where background jobs run) | `external` (the `portal-worker` service) | `external`; `embedded` (a thread of the portal) only for a set-up without `portal-worker` |
| `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` | Docker Compose (**only from `.env`**) | `0.0.0.0` | `127.0.0.1` behind a TLS proxy |
| `WEB_SERVICE_REPLICAS`, `DATA_ENTRY_SERVICE_REPLICAS`, `PORTAL_SERVICE_REPLICAS`, `PORTAL_WORKER_REPLICAS` | Docker Compose (**only from `.env`**): containers of each service | 1 | as the load requires (1 to 20; the installer writes them) |
| `WEB_SERVICE_PROCESSES`, `DATA_ENTRY_SERVICE_PROCESSES`, `PORTAL_SERVICE_PROCESSES` | Docker Compose (**only from `.env`**): gunicorn processes per container (`WEB_CONCURRENCY`) | 2 | about two per CPU core the service may use (gunicorn advises 2 × cores + 1 in all) |

Rules worth knowing:

- Use URL-safe secrets (e.g. `openssl rand -hex 24`), so the MongoDB password goes into `MONGO_URI`
  without percent-encoding.
- `MONGO_INITDB_ROOT_*` only apply when the database volume is created. To change the password later,
  change it in MongoDB first (`db.changeUserPassword`), then update `.env` and recreate the services.
- After editing `.env` run `docker compose up -d` (not `restart`, which keeps the old environment).
- `PORTAL_DB_PASSWORD` can be changed at any time: `portal-db-init` sets the portal user's password to the
  value in `.env` at every `docker compose up -d`, before the portal starts.
- For local development of the portal over plain HTTP, set `RESOLVER_PUBLIC_URL=http://localhost:8080`
  in `.env`.
- Requires Docker Compose 2.24 or later (`env_file` with `required`).

## Quick start (development machine)

```bash
git clone <this repository> && cd GS1_DigitalLink_Resolver_CE
printf 'RESOLVER_PUBLIC_URL=http://localhost:8080\n' > .env   # portal over plain HTTP on this machine
docker compose up -d --build
```

Then open http://localhost:8080/ (home page) and http://localhost:8080/portal/ (sign in as `admin` /
`change-me-please`, then change the password under Options).

## Installation on a server (Ubuntu)

`scripts/install.sh` installs or updates a complete resolver on Ubuntu Server 22.04 or 24.04.

**Before you start**

- A DNS record for the resolver's domain (e.g. `id.example.org`) pointing to the server.
- Ports 80 and 443 reachable from the Internet (for Let's Encrypt and for users), or a certificate
  of your own, or a load balancer / proxy that terminates TLS.
- A user with `sudo`, and `git` (present on Ubuntu Server images).

**Run it**

```bash
git clone https://github.com/<account>/GS1_DigitalLink_Resolver_CE.git
cd GS1_DigitalLink_Resolver_CE
sudo scripts/install.sh
```

The installer asks for:

| Question | Notes |
|---|---|
| Domain name | Without `https://`; becomes `FQDN` |
| HTTPS mode | `letsencrypt` (nginx on the server + free certificate, renewed automatically), `certificate` (nginx with a certificate you provide), `external` (TLS elsewhere; port 8080 published on the address you choose) |
| E-mail / certificate files | For Let's Encrypt notices, or the PEM files of your certificate |
| Operator | Organisation name (required), website, address and telephone (optional); published in `/.well-known/gs1resolver` and on the resolver's pages |
| First portal user | Name and password; leave the password empty to have one generated and shown once at the end |
| Daily backup | Cron at 02:30 running `scripts/resolver-backup.sh` |
| Docker user | Account allowed to run `docker` without `sudo` (defaults to the one that ran `sudo`) |

Then, after a summary and a confirmation, it:

1. installs Docker Engine with the Compose plugin from Docker's official repository when Docker or a
   recent enough Compose (2.24+) is missing (replacing Ubuntu's `docker.io` packages if present, after
   asking), and nginx and Certbot when the server terminates TLS;
2. generates the MongoDB password and the API token (`openssl rand -hex`) and writes `.env` with mode
   600, owned by the user who ran `sudo`;
3. builds and starts the services and waits until the resolver and the portal answer; once the first
   portal user exists, its password is removed from `.env`;
4. writes the nginx site `/etc/nginx/sites-available/gs1resolver` (reverse proxy to `127.0.0.1:8080`),
   opens ports 80/443 in ufw if ufw is active, and runs Certbot (`--redirect`);
5. installs `/etc/cron.d/resolver-backup` and checks `https://FQDN/` and `/.well-known/gs1resolver`.

Everything goes to `/var/log/gs1-resolver-install.log` (never the passwords). If a step fails, the
installer shows the end of the log; fix the cause and run it again.

**Running it again** is how you change settings or repair an installation: current values are offered
as defaults, secrets are kept, existing portal users and data are untouched, an nginx site that already
has a certificate for the domain is kept, the previous `.env` is saved as `.env.bak-<date>` (mode 600),
and settings the installer does not manage are carried over. A `.env` written by hand is understood,
including a percent-encoded `MONGO_URI`.

**Unattended use:** `sudo -E scripts/install.sh --non-interactive` takes every answer from environment
variables with the names listed in the table of the Configuration section, plus `TLS_MODE`,
`CERTBOT_EMAIL`, `TLS_CERT_FILE`, `TLS_KEY_FILE`, `INSTALL_BACKUP_CRON` and `INSTALL_DOCKER_GROUP_USER`
(see `scripts/install.sh --help`).

**What it does not do (yet):** rotate existing secrets, move an installation to another domain's
certificate automatically, or configure off-server copies of the backups.

## Portal users

The first user comes from `PORTAL_ADMIN_USERNAME` / `PORTAL_ADMIN_PASSWORD` and is created only while the
portal has no users. Further users, resets and removals:

```bash
docker compose exec portal-service python create_user.py maria            # create or reset (asks twice)
docker compose exec portal-service python create_user.py ana --role admin --tenant "Acme Foods"   # in an organisation
docker compose exec portal-service python create_user.py maria --remove   # remove
```

A user created without `--tenant` is the operator's; an administrator of the operator is a server
administrator (see *Tenants* below).

Users (with password hashes), record metadata and the journal live in the portal's own MongoDB database
(`PORTAL_DB_NAME`, default `resolver_portal`), reached with a user that may read and write that database
only; the one-shot `portal-db-init` service creates that user, or updates its password, at every start.
The session key is `PORTAL_SECRET_KEY` from `.env`; without it, `secret.key` in the named volume
`resolver-portal-config`, which the image initialises with the right owner and which every portal process
and replica on the same Docker host shares. The reasons for this design
are in [ADR 0001](../adr/0001-portal-state-in-mongodb.md).

**Moving from the files of earlier versions.** Earlier versions kept `users.json`, `records-meta.json` and
`journal.jsonl` in the volume. At its first start with the database, the portal imports each file into its
empty collection, renames it `*.migrated` (kept as a copy) and logs the counts
(`docker compose logs portal-service | grep -i moved`). Nothing else is needed; the `*.lock` files left
next to them are no longer used.

## Primary identification keys

The portal manages every primary identification key of the GS1 Digital Link URI Syntax 1.7
(section 4.3), chosen in step 1 of the editor:

| AI | Key | Value (as in the URI) |
|---|---|---|
| 01 | GTIN | 8, 12, 13 or 14 digits (stored as 14), check digit |
| 8006 | ITIP | GTIN (14) + piece number (2) + total pieces (2); piece 01 … total |
| 8013 | GMN | up to 25 characters, GS1 Company Prefix first, check-character pair last |
| 8010 | CPID | up to 30 characters: digits, capital letters, hyphen; GS1 Company Prefix first |
| 414 / 415 / 417 | GLN (physical location / invoicing party / party) | 13 digits, check digit |
| 8017 / 8018 | GSRN (provider / recipient) | 18 digits, check digit |
| 255 | GCN | 13 digits with check digit + up to 12 serial digits |
| 00 | SSCC | 18 digits, check digit |
| 253 | GDTI | 13 digits with check digit + up to 17 serial characters |
| 401 | GINC | up to 30 characters, GS1 Company Prefix first |
| 402 | GSIN | 17 digits, check digit |
| 8003 | GRAI | 0 + 13 digits with check digit + up to 16 serial characters |
| 8004 | GIAI | up to 30 characters, GS1 Company Prefix first |

- The checks are those of the GS1 Barcode Syntax Engine, the library the resolver uses to accept every
  request (check digits, GMN check-character pair, GS1 Company Prefix, ITIP piece/total, GRAI filler
  zero); `dev-tests/portal/test_keys.py` compares the portal with it case by case.
- Alphanumeric values use letters, digits, full stop and hyphen only: stricter than the standard's
  82-character set, because the data entry service turns "/" into "_" in document ids and other symbols
  would need percent-encoding.
- Spreadsheets have a *Key (AI)* column (`01`, `00`, `414`, …; empty means `01`), an *Identifier* column
  and a *Qualifiers* column; files exported before, with *GTIN* and *Batch/lot* columns, still import.

### Key qualifiers

Step 1 shows one field per key qualifier the chosen key accepts (sections 4.4 and 4.9), in path order.
Empty fields mean "every unit"; a record is one combination of key and qualifiers.

| Key | Qualifiers (path order) | Notes |
|---|---|---|
| GTIN (01) | 22 consumer product variant → 10 batch/lot → 21 serial | all optional |
| GTIN (01) | 235 third-party controlled serialised extension | UPUI; alone, not with 22/10/21 |
| ITIP (8006) | 10 batch/lot → 21 serial | 22 is in the grammar of 4.9, but the GS1 Syntax Engine (and so the resolver) refuses it without 01 |
| CPID (8010) | 8011 CPID serial | 1-12 digits, no leading zero |
| GLN (414) | 254 GLN extension, **or** 7040 UIC with extension | 7040: FID |
| GLN (415) | 8020 payment reference | **required** |
| Party GLN (417) | 7040 UIC with extension | EOID |
| GSRN (8017, 8018) | 8019 service relation instance | 1-10 digits |
| GIAI (8004) | 7040 UIC with extension | MID |

Formats follow section 4.6 (7040: one digit, two characters and an importer index; 8011 and 8019 digits
only). Alphanumeric values use letters, digits, ".", "_" and "-". Combinations the standard does not
allow (e.g. 235 with a batch) are refused with a message; the portal's rules are compared case by case
with the GS1 Syntax Engine in `dev-tests/portal/test_keys.py`.

Resolution walks up from the most specific record: serial → variant + batch → variant → key, e.g. a
request for `/01/…/22/V1/10/L2` uses the V1 record when there is none for batch L2. Registering every
serial number is rarely needed: register the batch or the product and let the walk-up serve the serials;
use a serial record for a single item (e.g. a recall).

## Governance

Roles (checked by the server on every call; the interface hides what a role cannot do):

| Role | May |
|---|---|
| admin | everything, user administration, audit trail (of its tenant; of the operator for a server administrator) |
| editor | create, change, delete records; import; link checks |
| reader | consult, list, export, labels |

- The `users` collection holds, per user: password hash, role, GS1 Company Prefixes, tenant (none for the
  operator's users), e-mail address (optional, unique), disabled, must-change flag, creation and last sign-in.
  Users of a `users.json` from before roles (`{"name": "<hash>"}`) are imported as administrators. Changes to
  users are serialised by a lock shared by every portal replica, so the last enabled server administrator can
  never be removed or demoted.
- GS1 Company Prefixes (4-12 digits) limit a user to identifiers whose company part starts with one of
  them (`gs1.company_part`: after the indicator digit of GTIN-14 and ITIP, the extension digit of SSCC and
  the filler zero of GRAI). Records, lists, exports, imports, labels, history and link checks are filtered
  or refused (`access.prefix`).
- Temporary passwords (16 characters without look-alikes) are shown once; the account can only call
  `/config`, `/password` and `/logout` until it sets its own password.
- A password reset, disabling or removal ends the user's open sessions (session fingerprint).
- The journal (the `journal` collection of the portal's database) records every event: `login`,
  `login-failed`, `login-refused`, `logout`, `password-change`, `create`, `update`, `delete` (with the
  record's content), `import`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove`,
  `tenant-create`, `tenant-update`, `tenant-remove`, `support-open`, `support-close`, each with the tenant whose
  trail it belongs to. The editor's History panel shows the last 20 versions of a record made in the scope of
  the request; the audit trail shows events without record contents.
- **Retention.** Events are kept by age, per category, counted from the end of the day they happened:
  sign-ins and sign-outs `PORTAL_JOURNAL_SESSION_DAYS` (default 180); record changes and imports
  `PORTAL_JOURNAL_RECORD_DAYS` (default 0, for ever); user administration, password changes and exports
  `PORTAL_JOURNAL_ADMIN_DAYS` (default 0, for ever). MongoDB deletes expired events itself (TTL index).
  A record can be restored only from versions still in the journal, so a limit on record changes also
  limits how far back a record can be restored. A changed value applies to older events at the next start.

### Tenants

An installation can serve several organisations ([ADR 0002](../adr/0002-tenants.md)). A **tenant** (an
*organisation* on screen) owns GS1 Company Prefixes; **a record belongs to the tenant whose prefix starts its
key**, worked out on every request (nothing is stored in the resolver's database). **The operator owns every
record no tenant holds.**

| Account | Reaches |
|---|---|
| user of a tenant | the tenant's records (or his own prefixes inside them), the tenant's users and audit trail if administrator |
| user of the operator | the records no tenant holds (or his prefixes among them); the operator's administrators are **server administrators** |
| server administrator | creates, renames, disables and removes tenants and assigns their prefixes; manages every user; reaches a tenant's records, history and audit trail only through **support access**: read only, opened with a reason (5 to 200 characters), recorded in the tenant's trail, closed when he leaves it or signs out |

Rules, checked on the server:
- a prefix belongs to one tenant at most; prefixes of different tenants may not overlap (`789835741` and
  `7898357410` cannot belong to two), and a tenant may not hold a prefix covered by another of its own;
- a tenant user's prefixes lie inside the tenant's; an operator user's may not lie inside a tenant's;
- a prefix is not given to a tenant while an operator user is limited to a prefix inside it, nor taken from a
  tenant while one of its users is;
- a tenant with users cannot be removed; once removed, its prefixes and records go back to the operator;
- a disabled tenant's users cannot sign in and their sessions end; its records still resolve and stay out of
  the operator's reach;
- a spreadsheet import checks each record again when it is written, so a prefix that changed hands since the
  preview is not written (`access.prefix` in the result).

Upgrading changes nothing until the first tenant is created: every existing user becomes a user of the operator.
**Creating a tenant takes its records away from the operator's users, server administrators included.** Each
tenant's last "check every record" result is its own. The record list shows who created or changed a record
only to users of the tenant that made the change. E-mail addresses are not used yet (item 3.1) and are never
written to the journal.

## Record list

The portal's user menu (and the link under the page title) opens **Registered records**
(`/portal/#records`): every record on the resolver (any primary key and qualifiers), most recently changed
first, with description, identifier (key and value), scope (every unit of the key, or its qualifiers:
variant, batch/lot, serial, …), number of links with link-check warnings, and the last change made through
the portal (date and user).

- Search by identifier (a GTIN with or without leading zeros), key name (GTIN, SSCC, GLN, …),
  description or qualifier value; several words narrow the result; case and accents are ignored. Filter
  by the user who made the last change, or show only records whose targets had problems in the last link
  check.
- Filter by **primary key type** (URI Syntax 4.3) and by **key qualifier** (4.4). Each filter lists only
  what the records contain, with how many records each option selects ("Batch/lot (10) · 4"); the
  qualifier filter follows the key type chosen. A qualifier selects the records that have it, alone or with
  others (a serial-number record also has its batch); "None" selects the records of the whole key and
  "Others" those created elsewhere with qualifiers the portal does not manage. *Clear search and filters*
  appears while any of them is in use. Data attributes (4.10) are not a filter: they are never stored.
- **Code search** — a GS1 Digital Link URI (any domain, any path before the key) or an element string with
  the AIs in brackets, `(01)07898357410015(10)L1`, pasted or typed in the search box is read as a code
  instead of words. The list then shows the records of that key related to it: the **exact** record first
  (marked), then the more general ones (e.g. the batch and the product of a serial number, most qualifiers
  first), then the more specific ones (e.g. the serial numbers of a batch); other batches, variants and so
  on are left out. A line under the filters shows the code as read; AIs that are not qualifiers of the key,
  including data attributes in the query string, are named as ignored. A GTIN-8, -12 or -13 is completed to
  14 digits. A Digital Link of the key alone lists every record of the key. Element strings scanned
  without brackets (with FNC1/GS separators) are not read as codes.
- Selecting a record opens it in the editor; the browser's back button returns to the list.
- Records created by other tools with a qualifier set the portal does not manage (a lot template such as
  `{lotnumber}`, characters outside the portal's rules, a combination section 4.9 does not allow) are
  listed but not opened.

Data comes from the data entry API's `GET /api/summary` (one request for all records) and from the
portal's own record metadata (the `record_meta` collection of its database), which records who created and
last changed each record through the portal. Changes made through the API directly show "no history".
The whole list is sent to the browser, which is comfortable up to a few thousand records.

## Other records of the same key

When the record opened in the editor has siblings on the same key — the product itself, its batches,
serials, variants — a list appears under *Open record*: "Other records of this GTIN (21)". It shows, for each
one, what it applies to ("Batch L2026-03 · Serial S0001", "Every unit"), its description, number of links and
the last change made through the portal (date and user); a search by text (qualifier values, description),
a filter by key qualifier (only the qualifiers present, plus "no qualifiers"), and *Open*. Five rows are in
view at a time (measured, as rows may wrap) and the list scrolls, so the page does not grow with the number
of records; on phones only what it applies to and the button remain. The data comes with the record itself
(`otherEntries` of `GET /portal/api/record`: kind, qualifiers, description, links, `updatedAt`,
`updatedBy`), so no extra request is made. Records created by other tools with qualifiers the portal does
not edit are listed but cannot be opened.

*Open* fills the qualifier fields and opens that record. If the description or the links of the record
being edited differ from what was opened or last saved, the browser asks first ("This record has unsaved
changes. Opening another one discards them."); cancelling keeps everything as it was.

## Spreadsheet import and export

In **Registered records**, *Export spreadsheet (Excel)* and *Export CSV* download every record the
portal can edit, and *Import spreadsheet* reads one back.

**Layout** — one row per target (link); rows with the same key, identifier and qualifiers form one record:

| Key (AI) | Identifier | Qualifiers | Description | Link type | URL | Language | Title | Default | Forward query string |
|---|---|---|---|---|---|---|---|---|---|
| 01 | 07898357410015 | | Coffee 500 g | gs1:pip | https://… | pt, en | | yes | yes |
| 01 | 07898357410015 | | Coffee 500 g | gs1:instructions | https://…/manual.pdf | pt | Manual | | no |
| 01 | 07898357410015 | (10)L2026A | Coffee 500 g, batch L2026A | gs1:pip | https://…/l2026a | pt | | yes | yes |
| 414 | 7898357400009 | | Main warehouse | gs1:pip | https://… | pt | | yes | yes |

- The default link type is one per key, so every record of `01 07898357410015` (the product and batch
  L2026A) marks a `gs1:pip` target as *Default*; see the note on the default link type below.
- *Key (AI)* is the AI of the primary key (`01`, `00`, `414`, `8004`, …, with or without brackets);
  empty means `01`. *Qualifiers* holds the key qualifiers as element strings, `(22)V1(10)L1(21)S1`, or as
  a path, `/10/L1/21/S1`; empty means the record of the key itself. Values follow the rules of
  [Primary identification keys](#primary-identification-keys) and [Key qualifiers](#key-qualifiers).
- Headers are written in the user's language and recognised in any of the portal's languages (or as the
  keys `key`, `value`, `qualifiers`, `description`, `linkType`, `url`, `language`, `title`, `default`,
  `forward`). Only Identifier, Description, Link type and URL are required. Files exported before other
  keys existed, with *GTIN* and *Batch/lot* columns (keys `gtin`, `lot`), still import.
- The XLSX file has three more sheets listing the link type codes, the key codes and the language codes.
  Key, identifier and qualifiers are written as text, so Excel keeps the leading zeros. The CSV uses `;` and UTF-8 with BOM, as Excel
  expects in Brazil; imports also accept `,` or tab as separator and Windows-1252 or UTF-16 (Excel's
  "Unicode text", `.txt`) as encoding.
- Link types may omit `gs1:`; addresses without `https://` get it, as in the editor; several languages
  go in one cell separated by commas; *Default* marks the target that opens first (the first row if
  none is marked); *Forward query string* is yes unless it says no.
- Languages: any well-formed BCP 47 tag (`pt`, `pt-BR`, `en-US`, `vi`, `und`, …), written in canonical
  case. The editor's menu offers the common ones and keeps any other tag a record already has.
- Records created by other tools with a qualifier set the portal does not manage (see
  [Record list](#record-list)) are listed but neither exported nor imported.

**Import** is in two steps. The portal first checks the whole file with the editor's own rules and shows,
record by record, what will be **new**, **changed**, **unchanged** or **with errors** (with the file's row
number and the reason, e.g. a GTIN that Excel turned into scientific notation). Nothing is written until
*Import records* is confirmed; records with errors are skipped. Each record in the file replaces the
record on the resolver entirely, as a save in the editor does; records that are not in the file are not
touched (import never deletes). The import runs in the background with a progress counter, records who
made each change, and writes one audit line (`action=import created=… updated=… failed=…`). It is a job run
by the `portal-worker` service: while it waits its turn the page says it is in the queue, and after about
15 seconds with no worker running it warns that the job worker is not running. If the worker stops in the
middle (an update, a restart), the next worker continues from the first record not yet written; a job
interrupted three times stops with a message, keeping what was written.

**Limits per file** — set in `FORMATS` in `portal/sheet.py`, sent to the browser in `GET /portal/api/config`
(`importLimits`), shown in the import dialog and checked by the browser before sending and again by the
server:

| Format | Extensions | Data rows (header not counted) | Size |
|---|---|---|---|
| `xlsx` | `.xlsx` (first sheet only) | 5 000 | 700 KB |
| `csv` | `.csv`, `.txt` | 5 000 | 700 KB |

The file is sent base64-encoded inside a JSON request, which the portal (`MAX_CONTENT_LENGTH`) and the proxy
(`client_max_body_size 1m` on `/portal/`, and on the host nginx site written by the installer) limit to
1 MB; 700 KB of file becomes about 935 KB. Measured with exported files: 5 000 rows take 200–290 KB in
XLSX (compressed, repeated texts stored once) but 900–1 800 KB in CSV, so a CSV reaches 700 KB at about
2 000–3 900 rows. Raising the size limit needs the three request limits raised together.

The default link type is shared by all the records of a key, so an import cannot change it while the key
has other records.

## Special characters

What the portal does with characters outside plain letters and digits, and why:

| Where | Rule |
|---|---|
| Keys and qualifiers | ASCII only, as GS1 defines them. Digits of other scripts (full-width `７`, Arabic-Indic `٧`, superscript `²`) are refused: Python's `isdigit()` and `\d` accept them, which let them be stored or, for `²`, fail with an internal error. Alphanumeric values use letters, digits, `.`, `-` (and `_` in qualifiers), as decided in [Primary identification keys](#primary-identification-keys). |
| Keys and qualifiers | Invisible characters that come with copied text are removed before the checks: zero-width space and joiners, word joiner, byte order mark, soft hyphen, direction marks. Spaces are removed from keys (people type `7 898357 41001 5`), not from qualifiers. Same rule in the browser and the server (`INVISIBLE` in `app.js`, `gs1.without_invisible`). |
| Descriptions and titles | Any character, emoji included, stored in Unicode normal form C (text typed on macOS or read from some files arrives decomposed: `e` + combining accent) with line breaks, tabs and other control characters turned into one space (`gs1.clean_text`). Excel's Alt+Enter line breaks therefore become spaces. |
| Target addresses | Spaces, line breaks, tabs, invisible characters and backslashes are refused (`link.urlChars`): they are never part of a correctly copied address, a line break made the resolver answer 500 when redirecting, and a backslash is read differently by browsers and servers. Accented paths and internationalised domain names are kept as typed: the resolver sends them percent-encoded and in Punycode in `Location` (e.g. `https://açúcar.com.br/` → `https://xn--acar-0oa8i.com.br/`). |
| Language tags | ASCII only (`re.ASCII`). |
| Spreadsheet export | XLSX cells are always text, never formulas. CSV cells starting with `=`, `+`, `-`, `@`, tab or carriage return get a leading apostrophe, so Excel and LibreOffice do not run them as formulas ("CSV injection"); imports remove that apostrophe, so a round trip returns the same text. The audit trail CSV is protected the same way. |
| Spreadsheet import | UTF-8 (with or without BOM), UTF-16 with BOM and Windows-1252; a cell above 128 KB is reported as an unreadable file. |
| Sign-in | A user name typed at a failed sign-in (anyone can type it) is written to the log and the audit trail with unprintable characters as `?` and cut at 64 characters, so it cannot forge log lines. |
| Pages | The portal writes text with `textContent` only and the resolver's pages are Jinja templates with escaping, so `<`, `>`, `&` and quotes in descriptions and titles are shown, never interpreted. |

Records created through the API by other tools can hold qualifier values the portal refuses (a lot
`A/B`, a template `{lotnumber}`); the portal lists them but does not edit, export or import them. A `/`
inside a value cannot be resolved (the resolver splits the path at every `/`, encoded or not; this comes
from the official project).

## Link checker

The portal checks whether the target addresses answer, from the server (which therefore needs outbound
HTTPS access to the Internet):

- **Editor** — after each save, and with *Check targets* at any time, every target gets a note: answered
  normally, or the problem. A problem never stops a save.
- **Record list** — *Check links* checks every target of every record in the background (with a
  progress counter), marks the records with problems (⚠ and the count; hovering lists the addresses)
  and offers *Only with problems*. The check is a job of the `portal-worker` service, like an import. The
  latest result is kept in the portal's database and shown again when the list opens; opening a marked
  record checks its targets in the editor.
- **Spreadsheet import** — the optional *Also check that the addresses answer* lists the rows whose
  addresses have problems; they do not stop the import.

What is reported: HTTP errors (404, 500, …), no answer (unknown domain, site down, more than 8 s),
a redirect from HTTPS to plain HTTP, more than 5 redirects. 401, 403 and 429 are reported as "the site
refused the automated check": many sites block robots while the page works for people. Each address is
checked with HEAD (GET if the server refuses HEAD, without reading the body), and results are cached for
10 minutes.

**Limit: "soft 404".** Some sites answer "200 OK" with an empty or generic page for addresses that do
not exist (some organisations' sites do). The checker relies on the status the site sends,
so such addresses pass as valid; open them with *Try now* after registering. Guessing from the page
content would raise false alarms on legitimate pages.

Only public addresses are contacted: host names that resolve to private, loopback, link-local or other
non-global addresses (the Docker network, the cloud metadata service) are refused at every redirect, so
the checker cannot be used to probe the server's own network.

## Sign-in, sessions and passwords

- `/portal/login` is a sign-in page (no more browser pop-up). A successful sign-in sets a session cookie
  (`gs1resolver_portal`: HttpOnly, Secure, SameSite=Lax, path `/portal`). The session ends after 30
  minutes without use (`PORTAL_SESSION_IDLE_MINUTES`) and, whatever the use, 12 hours after the sign-in
  (`PORTAL_SESSION_MAX_HOURS`); afterwards the user is sent back to the sign-in page with a "session ended"
  message.
  - Idle limit: the cookie's signed time is renewed by every request and checked against the idle limit
    (`PERMANENT_SESSION_LIFETIME`). Absolute limit: the session keeps its sign-in time (`since`); a request
    after the limit clears it (audit log line `action=session-limit`). Sessions opened before the limit
    existed start counting at their next request.
  - The page mirrors both limits (`SessionClock` in `static/app.js`, from `session` in
    `GET /portal/api/config`, with relative seconds so the browser's clock does not matter). Every answered
    call renews the idle limit; key presses, clicks, scrolling and touches without server calls count as
    use too, and the page then calls `GET /portal/api/session` quietly (at most every 5 minutes, or a third
    of a short idle limit). Other tabs share the time of the last call through `localStorage`.
  - Two minutes before either end (a quarter of a short idle limit) a dialog appears: before the idle end
    it offers **Stay signed in** (or Esc) and **Sign out**; before the absolute end it explains that a new
    sign-in is needed, and can only be closed. At the end the page goes to the sign-in page.
- Every password field (sign-in, password change) has an eye button that shows or hides what is typed
  (`static/password.js`, `aria-pressed`, labelled in the user's language). The field is hidden again when
  its form is submitted, so password managers still see a password field. The script is one of the few
  files served without a session (`PUBLIC_ASSETS`), because the sign-in page needs it.
- After five failed attempts a username (and, separately, a client address) is locked for 15 minutes.
  The failures are kept in the portal's database (`login_failures`, emptied by MongoDB after 15 minutes),
  so the lock holds across every replica of the portal and across restarts.
- The user icon on the right of the header opens a menu (on hover with a mouse, or on click/keyboard)
  showing the username, **Options** and **Sign out**. Options lets users change their own password
  (current password required, at least 12 characters). Changing the password signs out every other
  session of that account.
- Sessions are signed with `PORTAL_SECRET_KEY` (written to `.env` by the installer; every portal replica
  must share it). Without it, a `secret.key` created automatically in the `resolver-portal-config` volume is
  used; every process and replica on the same Docker host mounts that volume and reads the same key (the
  file is written under another name and then linked, so processes starting together never read it half
  written). Changing the key signs everybody out.
- Environment settings: `PORTAL_SESSION_IDLE_MINUTES` (default 30), `PORTAL_SESSION_MAX_HOURS` (default 12),
  `PORTAL_COOKIE_SECURE` (default: on when the public address is `https://`, off for plain-HTTP
  development). `PORTAL_SESSION_HOURS`, the former sliding limit, is ignored with a warning in the log.
- The sign-in page and the portal end with a notice in the footer: the software is maintained by its
  community, not by GS1 or any GS1 Member Organisation, and whoever operates the installation is
  responsible for its use (`footer.notice`).
- The audit trail records `login`, `login-failed`, `logout` and `password-change` alongside the record
  changes.

## E-mail

The portal sends mail through an SMTP relay the operator chooses ([ADR 0004](../adr/0004-e-mail.md)). Without
`PORTAL_MAIL_HOST` e-mail is off and nothing below happens: users get temporary passwords, as before.

**What is sent.**

| Message | When | Category |
|---|---|---|
| Invitation (a link to choose a password, 72 hours) | an administrator creates a user with an address, *Send an invitation by e-mail* ticked | account (always) |
| Password recovery (a link, 60 minutes) | *Forgot your password?* on the sign-in page, for an account that may sign in and has an address | account (always) |
| Password reset by an administrator (a link, 60 minutes) | *Reset password* on a user with an address; the old password stops working at once | account (always) |
| Your password was changed | the user changed it, or chose one through a recovery or reset link | security (always) |
| Your e-mail address was changed | an administrator changed it: to the old and to the new address | security (always) |
| Sign-in attempts to your account | the failed sign-in that locks the account for 15 minutes, once per lock | security (always) |
| Your import / your link check has finished | an import, or a check of every record, the user started | my background jobs (optional, off by default; *Options → E-mail*) |

Messages go in the user's language (`pt-BR` or `en-GB`): the page's language at each sign-in until the user
chooses one in *Options*; an invitation goes in the inviting administrator's. Nothing is sent to a disabled
account or to a user of a disabled organisation.

**The relay.** Ask the organisation's mail administrators for:

- a host name and port: 587 with STARTTLS (`PORTAL_MAIL_SECURITY=starttls`, the default) or 465 with TLS
  (`tls`). Port 25 is blocked by most cloud providers (Azure does) and is not used;
- a user name and password allowed to submit mail (Microsoft 365 calls it *Authenticated SMTP* and enables it
  per mailbox; Google Workspace uses `smtp-relay.gmail.com` or an app password; sending services such as Amazon
  SES, SendGrid or Mailgun give SMTP credentials). A relay that accepts the server by its address needs none;
- a sender address the organisation's domain allows (`PORTAL_MAIL_FROM`, e.g.
  `Link portal <noreply@example.org>`): the domain's SPF record must include the relay, and the relay should
  sign with DKIM, or messages may be marked as spam. Give `PORTAL_MAIL_REPLY_TO` a help-desk address if users
  should be able to answer;
- a certificate signed by a public authority, or the private authority's certificate for
  `PORTAL_MAIL_CA_FILE` (the file must be inside the containers, e.g. in the `resolver-portal-config` volume).

The relay's certificate is always verified; with `starttls` a relay that does not offer STARTTLS is refused
before any credential is sent. `PORTAL_MAIL_SECURITY=none` (no encryption) is accepted only without
credentials, for a test relay. Settings that do not fit together switch e-mail off with an error in the log
(`docker compose logs portal-service | grep -i e-mail`).

**Checking it.** After setting the values in `.env` (or running the installer) and `docker compose up -d`:

```bash
curl -s http://127.0.0.1:8080/portal/healthz                     # … "mail":"on"
docker compose exec portal-service python mail.py test you@example.org
# Relay smtp.example.org:587 (starttls), from …, to you@example.org …
# Sent: the relay accepted the message. Check the mailbox (and its spam folder).
```

A refusal is printed with the relay's answer (`535` wrong credentials, `550` sender not allowed, a certificate
refused …).

**How it is sent.** A message is a job of the worker (`type: "mail"`): the request that causes it only queues
it, so a slow relay never slows the portal. After a temporary failure (no connection, a timeout, a 4xx answer)
the job goes back to the queue for 1, 5, 15, 60 and 120 minutes; after a permanent one (5xx) or the last try it
fails and the audit trail records `mail-failed` with the relay's answer (never the address). The message text,
which may carry a link, leaves the job as soon as it is sent or has failed. The worker logs each message
(`docker compose logs portal-worker | grep Message`).

**Links.** Invitation and recovery links carry a random 256-bit token in the fragment of the address
(`…/portal/login#reset=…`), which browsers never send to a server, so it reaches no access log. Only the token's
SHA-256 is stored (`tokens` collection, removed by MongoDB when it expires). A link works once; a newer one of
the same kind replaces it; choosing a password through it ends every session and every other link of the
account. Validity: `PORTAL_INVITE_HOURS` (72) and `PORTAL_RESET_MINUTES` (60).

**Password recovery** answers the same message, after at least half a second, whether or not the user name or
address belongs to an account; requests are limited to 3 per entry and 10 per browser address in 15 minutes,
and ten invalid links from one address pause link checks for 15 minutes.

**Trying it without a relay.** On a test installation, Mailpit accepts every message and shows it:

```bash
docker compose --profile mail-test up -d mailpit
cp .env .env.before-mailpit && sed -i '/^PORTAL_MAIL_/d' .env       # keep a copy; drop earlier mail lines
printf "PORTAL_MAIL_HOST='mailpit'\nPORTAL_MAIL_PORT='1025'\nPORTAL_MAIL_SECURITY='none'\nPORTAL_MAIL_FROM='portal@example.org'\n" >> .env
docker compose up -d
curl -s http://127.0.0.1:8025/api/v1/messages | python3 -m json.tool | grep -E '"(Subject|Address)"'
curl -s http://127.0.0.1:8025/api/v1/message/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["Text"])'
```

Put the copy back (`mv .env.before-mailpit .env`, then `docker compose up -d`) and stop Mailpit
(`docker compose --profile mail-test rm -sf mailpit`) when done. Never use it in production: it keeps every
message, links included.

## Single sign-on

Each organisation can let its people sign in with the account they already have — Microsoft Entra ID, Google
Workspace, Okta, Keycloak or any OpenID Connect provider ([ADR 0012](../adr/0012-single-sign-on.md)).

**At the provider**: register a web application with the return address shown on the portal's screen
(`https://<FQDN>/portal/sso/callback`), the scopes `openid email profile`, and note the issuer, the client ID and the
client secret. Examples of issuers: Entra ID `https://login.microsoftonline.com/<tenant id>/v2.0`, Google
`https://accounts.google.com`, Keycloak `https://<host>/realms/<realm>`, Okta `https://<domain>.okta.com`.

**In the portal** (user menu → **Organisation sign-in**, administrators): the issuer, client ID and secret (the secret
is write-only: leave the field empty to keep it), the organisation's **e-mail domains** (each domain belongs to one
configuration in the installation), **On**, then **Test the provider** (reads the discovery document and the keys).
A server administrator sees every organisation's configuration and the operator's own.

**Signing in**: *Sign in with your organisation's account* on the sign-in page asks for the e-mail address; its
domain chooses the provider; after the provider, the portal signs in the account **with that e-mail in that
organisation** (the provider's `email`, not marked unverified). Nobody is created: administrators still create or
invite the users and choose their roles and prefixes. A temporary password is not asked for after single sign-on.

**Password sign-in off**: once single sign-on works, the organisation can switch password sign-in off for its users
(their passwords are kept and work again if it is switched back on); password recovery then sends them nothing. It
never applies to server administrators, who can always sign in and switch it off — for example when the
organisation's provider is down.

The provider's addresses must be `https` on public addresses; `PORTAL_SSO_ALLOW_INSECURE=1` accepts `http` and private
addresses (tests, or a provider on the operator's own network). The journal records each sign-in through a provider
and each refusal with its reason; the screen shows the last sign-in and the last failure.

### Limits on exports per role

`PORTAL_EXPORT_LIMITS` in `.env` sets the most rows one export of a role may hold — the record spreadsheet and the
requests' CSV — and `0` for no export at all (the overview's export is then refused too). Administrators, and roles not
named, have no limit. A refused export says the numbers and goes into the journal (`export-refused`); the page hides
the export buttons of a role that may not export.
```bash
grep -q '^PORTAL_EXPORT_LIMITS=' .env || printf "PORTAL_EXPORT_LIMITS='%s'\n" 'reader:0,editor:20000' >> .env
docker compose up -d portal-service portal-worker
```

## Tenant API

An organisation's own systems reach its records through `/portal/api/v1` with an API key
([ADR 0005](../adr/0005-tenant-api.md)); the operations are in the README (*Tenant API*) and in the public
description `GET /portal/api/v1/openapi.json` (OpenAPI 3.1, the installation's address as its server).

**Keys.** Administrators create them in the portal (user menu → **API keys**): a tenant administrator for his
organisation, a server administrator for the operator's records only (a server administrator never gets a key
into an organisation; support access stays the only way in). A key has a name, scopes (`records:read`,
`records:write`, `labels:read`, `stats:read` for the overview's figures), optional GS1 Company Prefixes inside the organisation's, and a validity of 1 to
`PORTAL_API_KEY_MAX_DAYS` days (90 by default); at most 20 active keys per organisation. The key —
`rk_<12 hex>.<43 characters>` — is shown once; only the SHA-256 of its secret is stored, so a lost key is revoked
and replaced. Revoking takes effect on the next request. The administrator who created a key receives an e-mail
when it is created and a week before it expires (installations with e-mail); revoked and expired keys stay listed.

**What a key may do.** Exactly what a user of its organisation with the matching role may do: `records:write`
gives the editor's rights, otherwise the reader's; its prefixes limit it further. Every rule of the portal applies
(GS1 rules, 2.5.9, the default link type shared by the records of a key). A key of a disabled or removed
organisation is refused. Changes appear in the history and the audit trail with the user `api:<key id>`;
`api-key-create` and `api-key-revoke` are recorded in the organisation's trail.

**Limits.** `PORTAL_API_RATE_PER_MINUTE` requests per key and minute (120 by default), counted in the portal's
database for every replica; above it the answer is 429 with `Retry-After`. Pages of `GET /records` hold up to 1,000
records (`limit`, `after`). The API is for servers: it sends no CORS headers, and a browser request from another
site is refused by the portal's Origin check.

**Trying it.**

```bash
KEY='rk_…'                                       # from the API keys screen
curl -s -H "Authorization: Bearer $KEY" https://id.example.org/portal/api/v1/
curl -s -H "Authorization: Bearer $KEY" 'https://id.example.org/portal/api/v1/records?limit=5'
curl -s -o label.svg -H "Authorization: Bearer $KEY" 'https://id.example.org/portal/api/v1/labels/01/09506000134352?format=svg'
```

Errors come as `{"code": "...", "params": {...}}` with the portal's message codes (`api.keyMissing`,
`api.keyInvalid`, `api.scope`, `api.rateLimit`, `access.prefix`, `record.notFound`, the GS1 and validation codes).

## Request log

The resolver records each resolution request — a GS1 Digital Link URI, a compressed one, an EPC binary string,
a `?compress` request — as one event in its own database, `resolver_log` (collection `requests`;
[ADR 0006](../adr/0006-resolver-request-log.md)). `/heartbeat`, `/favicon.ico`, `/robots.txt`,
`/.well-known/gs1resolver`, the home page, the portal and the data entry API are not recorded.

**What an event holds.** Time, method, form (`uri`, `compressed`, `epc` and the EPC scheme), the primary key and
its company part, the key qualifiers (only the AI of a serial number or a TPX), the AIs of the data attributes in
the query string, the link type asked, the status and the outcome — `redirect`, `choice` (300), `linkset`,
`unknown` (no record applies: a code nobody registered), `noLink` (a record applies but has no link of that type),
`invalid` (400), `error`, `compressed` — the level of the record that answered (unit values as `*`), the target's
host, the time taken, the preferred language, a device class (`mobile`, `tablet`, `desktop`, `automated`,
`unknown`), the browser family (`chrome`, `safari`, `firefox`, `edge`, `samsung`, `opera`, `app`, `other`), the
referrer's host and the approximate location: country, region and city from the GeoIP database (below), the country
from the header `RESOLVER_LOG_COUNTRY_HEADER` names when a proxy in front sets one. For an invalid request whose key
cannot be read, the first 200 characters of the path.

**What is never stored.** The client's address in any form, the User-Agent, the full referrer, cookies, the values of
data attributes and of serial numbers, any other header, coordinates. A privacy notice of the operator can say so,
and that the browser family and the city are derived when a scan arrives (section 8 of the ADR).

**Approximate location (GeoIP).** The resolver looks up the client's address — from `RESOLVER_LOG_ADDRESS_HEADER`,
`X-Real-IP` by default, which the host's nginx sets; behind an external proxy, the header that proxy sets — in the
file `RESOLVER_GEOIP_DB` (`/geoip/dbip-city-lite.mmdb`, the repository's `geoip/` folder mounted read only) and
forgets it. `scripts/geoip-update.sh` downloads DB-IP's *IP to City Lite* (free, Creative Commons Attribution 4.0:
the portal credits "IP Geolocation by DB-IP" beside the locations) into that folder; the installer schedules it
monthly (`/etc/cron.d/resolver-geoip`, log `/var/log/resolver-geoip.log`) and runs it once. `GEOIP_URL` in `.env`
takes another source of the same MMDB format, such as MaxMind's GeoLite2 City with an account's licence key. The
resolver notices a new file within a minute, without a restart; without a file requests are logged without a
location. By hand:

```bash
sudo scripts/geoip-update.sh        # 2026-10-20T04:20:01+00:00 OK: …/geoip/dbip-city-lite.mmdb from … (… bytes)
```

**Writing.** Events go into a queue of 10,000 per server process and a background thread writes them in batches
of up to 500, so a scan never waits for the database. When the queue is full or the database does not answer,
events are lost and the resolver writes `Request log: N event(s) lost (…)` in its output, at most once a minute.

**Retention.** Set in the portal (*Requests → Retention*): the installation's days (server administrators, 1 to
3,650) and each organisation's, the same or fewer; until the portal sets them, `RESOLVER_LOG_DAYS` (90). Each event
carries its expiry date, worked out by the resolver from its owner's days; a shortened period is applied by the
worker's hourly housekeeping, which deletes older events (the portal's user may delete events, nothing else). `0` in
`RESOLVER_LOG_DAYS` switches the log off (nothing is captured; the tenant API's calls are not recorded either). The
space the log uses is shown on the same tab. The portal's worker counts each day's events per key
once an hour into the portal's collection `request_daily`, in the days of `PORTAL_TIME_ZONE` (the installer writes
the server's), kept `PORTAL_STATS_DAYS` (800) days. The daily backup keeps `resolver_log` too (`mongodump` cannot leave
a whole database out).

**Who reads it.** The portal's database user may read `resolver_log` and delete its events, never insert or change
one (`portal-db-init`). Each user
sees the events of the records in his reach; a server administrator not limited to prefixes sees the whole
installation, also requests without a key; ownership comes from the company part at query time, so a prefix given
to an organisation takes its history along. The portal's API: `GET /portal/api/requests`, `/requests.csv`,
`/requests/daily`, and `/requests/api` for the tenant API's calls (administrators). The tenant API's calls are
recorded by the portal itself (`api_requests`: key, organisation, method, the route's template, status, time — never
the record or the query string).

**Looking at it on the server** (as the root user of the installation's MongoDB):

```bash
docker compose exec database-service sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin resolver_log --quiet --eval "db.requests.find({}, {_id: 0}).sort({t: -1}).limit(5)"'
```

## Overview

The portal opens on the **Overview** after sign-in ([ADR 0007](../adr/0007-overview-indicators.md)); the editor keeps
the portal's address (`/portal/`, also `/portal/#editor`). Its figures cover the last 7, 30 or 90 days of
`PORTAL_TIME_ZONE`, today included, each against the period of the same length before it, in the scope of the user
(the rules of the request log above): usage (scans by people, automated requests apart, per day, the most scanned
codes, shares by device, form, language and link type), resolution quality (requests answered, codes nobody
registered and codes without the link asked, invalid requests, errors, average time; the slowest day's 95th
percentile for the whole installation), record quality (records and keys by type, no key-level record, serial with
batch or variant, no description, keys nobody scanned, link problems of the last full check), operation (the last
link check, the log's retention; for server administrators the worker, e-mail and the last day counted) and, for
administrators, governance (record changes by kind and by user, sign-ins and refusals, exports, users by role, API
keys active and expiring within 14 days, the tenant API's calls and refusals).

The figures are computed on request: past days from `request_daily`, today from the raw events, the records from the
resolver's summary, governance from the journal. **Quality counts every request; usage counts people.** When the
resolver cannot be read the records group says so and the rest is shown. **Export Excel** (a sheet of indicators with
the previous period, sheets per day, codes and users, lists up to 100) and **Export CSV** (the indicators) are
journalled as `overview-export`. API keys with the scope `stats:read` read usage, quality and records through
`GET /portal/api/v1/stats?days=30`. Nothing is configured: the overview needs the request log (`RESOLVER_LOG_DAYS`
above 0) for its usage and quality figures.

## Organisations' own domains

An organisation's QR codes can carry its own domain instead of the installation's
([ADR 0009](../adr/0009-tenant-domains.md); GS1 Digital Link URI Syntax 1.7, section 4.11): `https://id.acme.example/01/…`
or, with a path stem, `https://id.acme.example/gs1/01/…`.

**In the portal** (user menu → **Domains**, administrators): an organisation's administrators add its domains, a server
administrator the operator's (and sees every domain); at most 10 per organisation. A name is a lower-case host name
(internationalised names in Punycode), never the installation's own, unique in the installation; a stem has one to three
segments, none of 2 to 4 digits. Each domain is proved by a DNS TXT record `_gs1resolver.<domain>` =
`gs1resolver-verify=<token>` (**Verify**); it stays verified afterwards, the worker looking at the record once a day to
show when it was last seen. **Default for the prefixes** makes it the default of the labels of those prefixes (the
longest prefix wins); the label panel's *Domain in the QR code* chooses another for one label. The record's
`digitalLink`, the editor's preview, the label and the tenant API's labels (`domain=`) follow the same rule.
**Test** requests through the domain (public addresses only).

**Points at this server** (`direct`): the domain's DNS points at the server (CNAME or A/AAAA); the resolver recognises
it from the public host the proxy passes (`X-Forwarded-Host`), reading the verified domains from the portal's database
every minute, removes the stem and answers only for the organisation's prefixes (the operator's domains: the keys no
organisation holds); other codes answer 404 like a code nobody registered. Its description file names it as
`resolverRoot`. Certificates are the host's: after verifying a domain run

```bash
sudo scripts/custom-domains.sh list     # each verified direct domain and whether it has a site and a certificate
sudo scripts/custom-domains.sh apply    # a site from the installer's template and a Let's Encrypt certificate for each new one
```

(`CERTBOT_EMAIL` from `.env`; the domain's DNS must already point at the server and port 80 be open). A daily cron line
such as `17 3 * * * root /path/to/scripts/custom-domains.sh apply >> /var/log/resolver-domains.log 2>&1` keeps new
domains served without a visit; sites of domains removed in the portal are listed and deleted by hand.

**My server redirects** (`redirect`): the organisation's own server answers `https://<domain><stem>/<path>?<query>`
with a redirect (301, 302, 307 or 308) to `https://<FQDN>/<path>?<query>`; for nginx
`location ~ ^/gs1(/.*)$ { return 307 https://<FQDN>$1$is_args$args; }`, for Apache
`RedirectMatch 307 ^/gs1/(.*)$ https://<FQDN>/$1`. Nothing is installed on this server.

## The item's page

A record can send its scans to **a page of all its links** instead of one target
([ADR 0011](../adr/0011-item-page.md); backlog items 6.1 and 6.2). The page is the resolver's linkset page for browsers
(`?linkType=linkset`, GS1-Conformant Resolver 2.10), rewritten for phones: the item's description as its title, the
brand of the record's prefix (name, logo, colours; the text colour chosen for contrast), one large button per link with
an icon for its type, the links in the visitor's language first (the others under *Other languages*), the levels
(serial, batch, product) when there are several, the code in human-readable form, the linkset as JSON-LD. It loads
nothing from other sites: no web fonts, and the logo is served by the resolver itself (`/_brand/<prefix>`).

**As the default target.** The editor's *Default target: the item's page* (and `landingPage: true` in the tenant API)
adds to the record a link of type `gs1:defaultLink` to `<the record's Digital Link>?linkType=linkset&view=page` and makes
it the default; a scan is redirected to it (307) like any default, so resolution stays conformant and JSON clients are
unaffected. The editor hides that link and shows the option; spreadsheets carry it as a row of type `gs1:defaultLink`,
read back as the option. As the default link type is shared by the records of a key, so is the option: a batch of a
product using it must use it too, and the key's own record created with a batch gets its own page.

**Views and clicks.** The page reached as a default target (`view=page`) is logged with form `landing`, outcome `page`;
each button goes through `/_click?a=<record>&l=<level>&i=<position>&t=<link type>`, which reads the record again, finds
the link at that place and of that type (otherwise 404 — never an address taken from the request), logs outcome
`click` with the link type and the target's host, and redirects (302). An automated client's views and clicks are
logged as plain `linkset` and `redirect`. The overview counts **page views** and **clicks** apart from scans; the
Requests screen filters both.

**Brands** (user menu → **Item page**, administrators): per GS1 Company Prefix of the organisation (or a longer prefix
inside one), a name, a logo uploaded as PNG, JPEG or WebP (up to 200 KB and 2000 pixels a side; SVG refused, it can
carry scripts) and two colours; a server administrator brands the operator's prefixes and the installation's default
(`*`). The resolver reads them every minute from the portal's `branding` collection and uses the longest prefix.

**Verified by GS1** (item 6.2): for a GTIN or a GLN the page links to Verified by GS1 when
`RESOLVER_VERIFIED_BY_GS1_URL` is set (a template with `{key}` = `gtin` or `gln` and `{value}`; empty, the default:
off) and the brand has not switched it off. The link is on the page only, never in the linkset. Check the service's
current address before setting it:

```bash
grep -q '^RESOLVER_VERIFIED_BY_GS1_URL=' .env || printf 'RESOLVER_VERIFIED_BY_GS1_URL=%s\n' 'https://www.gs1.org/services/verified-by-gs1/results?{key}={value}' >> .env
docker compose up -d web-service
```

## Monitoring and alerts

The job worker checks the installation every `PORTAL_MONITOR_MINUTES` (5; 0 switches it off), one replica at a time
([ADR 0008](../adr/0008-monitoring-and-alerts.md)), and keeps the state of each check in the portal's collection
`alerts`:

| Check | How | Alert |
|---|---|---|
| Resolver | `GET PORTAL_MONITOR_URL` through the proxy (the description file, 200 within 10 s); with `PORTAL_MONITOR_PROBE`, that registered code too (2xx or 3xx, not followed) | after two failed rounds in a row |
| Backup | the record `scripts/resolver-backup.sh` writes after each run (setting `backup.last`: when, OK or the error, the file, its size, the last good run) | the last run failed, or the last good one is older than `PORTAL_MONITOR_BACKUP_HOURS` (26); unknown until the first record |
| Certificate | a TLS connection to `PORTAL_MONITOR_TLS_HOST` (`FQDN`) on port 443, once an hour | expires within `PORTAL_MONITOR_CERT_DAYS` (21) or does not verify; unknown when the host cannot be reached or is `localhost` |
| 404 spikes | requests answered "code not registered" in the last hour, for the installation and for each organisation | at least `PORTAL_ALERT_404_MIN` (20) and `PORTAL_ALERT_404_FACTOR` (3) times the usual hour of the 7 days before |

**Messages** (with e-mail on): one when a check goes into alert, a reminder every 24 hours while it lasts, one when it
is resolved (spikes simply end). Server administrators receive the resolver, backup, certificate and installation's
spikes; an organisation's administrators its own spikes. The category *alerts* is on by default; each user may switch
it off in Options → E-mail. Without e-mail the states are still shown in the overview's *Operation* group (every check
for server administrators; the organisation's spikes for its users).

**The backup's record** is written with `mongosh` inside the database container into the portal's database
(`PORTAL_DB_NAME` from `.env`, `resolver_portal` by default); when it cannot be written the backup still succeeds and
its log says `WARNING: the result was not recorded`. Looking at it on the server:

```bash
docker compose exec database-service sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin resolver_portal --quiet --eval "db.settings.findOne({_id: \"backup.last\"}); db.alerts.find().toArray()"'
```

## Home page

`https://<FQDN>/` shows a home page in the same look and feel as the portal, with a menu to:

| Menu entry | Target |
|---|---|
| Manage links / Cadastro de links | `/portal/` |
| Resolver API / API do Resolver | `/api/docs` (Swagger UI, the page previously shown at `/`) |
| GS1 Digital Link standard | https://ref.gs1.org/standards/digital-link/ |
| GS1 Global | https://www.gs1.org/ |
| Source code (GitHub) | https://github.com/gs1/GS1_DigitalLink_Resolver_CE |

Below the menu: cards for the portal and the resolver API, and GS1 references. The footer names the
operator and carries the community notice (the software is maintained by its community, not by GS1 or any
GS1 Member Organisation; whoever operates the installation is responsible for its use). The box that
showed the shape of a GS1 Digital Link was removed in session 8.

**Way back.** The GS1 logo on the portal and on the resolver's pages, and the portal's user menu ("Home
page"), lead back to `/`.

**Domain independent.** Links to this installation are root-relative (`/portal/`, `/api/docs`,
`/.well-known/gs1resolver`), and the operator's name in the footer comes from `contact.fn` in the
resolver description file, linked to `contact.hasURL` (`RESOLVER_ORG_URL`) when that is an `http(s)`
address, as in the footer of the resolver's pages; any other address leaves the name as plain text. Nothing
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

The editor's label block (QR code, its options, data attributes, link and legend) sits under the form, across
the page: QR code, version information, state and buttons on the left — kept in view while the options are
scrolled — and options, attributes, link and legend on the right, where the three label options fit side by
side and each attribute on one line; on phones it is one column. Until this layout the block was a narrow
panel beside the form, which the options and attributes had outgrown (compared in two mock-ups before the
change). The markup has two groups, `.label-visual` and `.label-controls`.

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
A record is addressed by its key and qualifiers: `key` (the AI, default `01`), `value` and `qualifiers`
(`{"10": "L1"}` in JSON, `/10/L1/21/S1` in a query string). On the resolver it is one entry of the key's
document, `{AI}_{value}`, reached at `/api/{AI}/{value}`.

| On screen | Portal API | Resolver calls |
|---|---|---|
| Sign in / sign out | `POST /portal/api/login`, `POST /portal/api/logout` | — |
| Change password (Options) | `POST /portal/api/password` | — |
| Open record | `GET /portal/api/record?key=…&value=…&qualifiers=…` | `GET /api/{AI}/{value}` (the whole document; the portal picks the entry with the same qualifiers) |
| Save (record not on the resolver yet: a new key, or a new qualifier set of an existing key) | `POST /portal/api/record` | `POST /api/new` (the first target sets `defaultLinktype`; each target carries `fwqs`) |
| Save (existing record) | `POST /portal/api/record` | `PUT /api/{AI}/{value}` with `{qualifiers, links, …}` and, if targets were removed, `DELETE /api/{AI}/{value}` with `{qualifiers, links}` |
| Delete (the only entry of the key) | `DELETE /portal/api/record` | `DELETE /api/{AI}/{value}` |
| Delete (a qualified record, or a key that has qualified records) | `DELETE /portal/api/record` | document `DELETE` + `POST /api/new` with the remaining entries (the original is restored if that fails) |
| Registered records | `GET /portal/api/records` | `GET /api/summary` |
| Export spreadsheet | `POST /portal/api/export` | `GET /api/summary?links=true` |
| Import spreadsheet | `POST /portal/api/import/preview`, `…/apply`, `GET …/status` | preview: `GET /api/summary?links=true`; apply: the save sequence above, record by record |
| QR code label | `GET /portal/api/qrcode?key=…&value=…&qualifiers=…&format=png\|svg&hri=0\|1[&attr=AI:value…]` | generated locally from `{RESOLVER_PUBLIC_URL}/{AI}/{value}[/{qualifier AI}/{value}…][?AI=value…]` (see "QR code label" and "GS1 Digital Link data attributes") |
| Data attributes (while typing) | `POST /portal/api/digital-link` with `{key, value, qualifiers, attributes: [{ai, value}]}` | — (checked by the GS1 Barcode Syntax Engine in the portal; nothing stored) |

Rules applied before calling the API: key values and qualifiers as in
[Primary identification keys](#primary-identification-keys) and [Key qualifiers](#key-qualifiers) (check
digits, GMN check-character pair, GS1 Company Prefix, qualifier formats and combinations; a GTIN of
8/12/13/14 digits is normalised to 14 and a GTIN-13 starting with 2 is refused); descriptions up to 200
characters and titles up to 120 (see [Special characters](#special-characters)); `https://` URLs; media
type inferred from the extension (`.pdf` → `application/pdf`); no duplicate resolver key (link type,
language, context). Targets with a `context` created by other tools are preserved when saving.

On screen: the link type menu shows the code first (`gs1:pip — Product information page`); the first
target is the default link (`gs1:defaultLink`) and "Make default" moves another one to the top; each target
had "Pass the request's query parameters on to this target" (`fwqs`) until item 1.5 removed it; the QR code downloads as
PNG or SVG and the address beneath it is a link.

## QR code label

The image in the preview panel is the exported label itself, so what is shown is what is downloaded.
It follows the symbol and text dimensions of the *QR Codes powered by GS1 design guidelines* (v1.0, May 2024):

- **Size** ([ADR 0010](../adr/0010-label-studio.md)): 80, 90, **100** (default), 120, 150 or 200 % of the target
  X-dimension, that is 0.396 to 0.990 mm per module (the range for GS1 Digital Link QR codes on consumer units). The
  SVG and PDF are sized in millimetres at that X-dimension; the PNG uses 12 pixels per module and carries the DPI
  value that prints at the same size. The text stays 2.2 mm high at every size (never under the 2 mm minimum); print
  the files at 100 % (no scaling).
- **Quiet zone:** 4X on all four sides, always blank.
- **Human readable interpretation** (full by default; or the key only, or none): the element strings below
  the quiet zone, one per line: the key (e.g. `(01)` followed by the GTIN-14, `(414)` followed by the GLN), then each
  qualifier in path order (e.g. `(10)` followed by the batch/lot, `(21)` followed by the serial), then
  each data attribute in the order entered (see below), in
  Liberation Sans (metrically equivalent to Arial). The guidelines require it when the QR code stands alone
  on pack; it may be omitted when the code sits next to the linear barcode that already carries the same
  data, or on a consumer-engagement panel.
- **SVG** and **PDF** are fully vector: modules, bars and HRI glyph outlines (the PDF embeds no font and has one
  page the size of the label, the URI as its title), so they open identically anywhere and are the formats to hand
  to packaging designers. PNG suits documents and quick use. **ZIP** downloads the label as SVG, PNG and PDF with a
  `README.txt` giving the URI, the QR version and level, both X-dimensions, the bar height and the printed size.
- **A linear barcode beside the QR code** (*Linear barcode beside it*, for GTINs of consumer units, indicator 0):
  *EAN-13 / UPC-A / EAN-8, as the GTIN takes* — EAN-8 for a GTIN-8, UPC-A for a GTIN-12, EAN-13 for a GTIN-13 — or
  *UPC-E* for a GTIN-12 that zero-suppresses; for the transition to 2D, when a till must still scan the product.
  It carries the GTIN only. X = 0.330 mm times the same size (0.264 to 0.660 mm, magnification 80 to 200 %), bars
  22.85 mm high at 100 % (EAN-8 18.23 mm), quiet zones EAN-13 11X/7X, UPC-A 9X/9X, UPC-E 9X/7X, EAN-8 7X/7X, guard
  bars 5X longer, human readable digits under the bars (EAN-13's first digit left of them; UPC-A's and UPC-E's outer
  digits smaller and outside). Another key, or an indicator other than 0, answers 422 `label.linearNotPossible`;
  the header `X-Linear-Symbol` names the symbol drawn.
  *Key only* keeps the first line, e.g. `(01)07898357410015`, for codes printed next to other text that
  already shows the batch or date.
- **QR version** (*Automatic* by default, the smallest version that fits; or 1 to 40, each shown with its
  size in modules) and **error correction level** (L 7 %, **M 15 %** by default, Q 25 %, H 30 %). The level is
  exactly the one chosen: the library the portal uses (segno) would otherwise raise it when the version has
  room to spare (the size stays the same), which earlier versions of the portal let it do. The version, size and level used are shown under the
  image and returned in the headers `X-QR-Version`, `X-QR-Modules` and `X-QR-Level`.
- **When the content does not fit** a chosen version at the chosen level, the image is replaced by an
  explanation — "The content does not fit version 2 with correction M" — with what to do: the version
  needed at that level, the highest level at which the chosen version would fit (if any), or shorter
  content (fewer or shorter data attributes). Nothing can be downloaded meanwhile. Content too long even
  for version 40 at that level says so. The API answers 422 with `qr.tooSmall` (`version`, `level`,
  `needed`, `fittingLevel`) or `qr.tooLong`.
- The choices are remembered in the browser (the on/off HRI choice of earlier versions becomes full or
  none). Files are named after the key and qualifiers, e.g. `qrcode_01_09506000134352_10_L1.svg`.

## GS1 Digital Link data attributes

Data attributes (URI Syntax 1.7, §4.10) are GS1 Application Identifiers for informative data — expiry
date (17), net weight (3103), price (3922), ship-to address (4302)… — written as `AI=value` pairs in the
query string: `https://id.example.org/01/09506000134352/10/B42?17=271231&3103=000500`. They are not part of
the identifier (§4.10, Resolver standard §2.12).

**What the portal does.** Ticking *Include data attributes* below the QR code opens an editor of
attributes: each row takes an AI and a value, with the expected format explained in the user's language
(e.g. "6 digits · date YYMMDD"), and ↑ ↓ buttons that set the order of the attributes in the URI and in
the human readable text. The AI is chosen in a combo box (ARIA 1.2 pattern, usable with mouse, touch,
keyboard and screen readers): a click in the field, its arrow button or the Down key opens the whole list,
with the current text selected so that typing replaces it; typing filters by number ("31") or by name
("net weight"); Enter or a click chooses; Escape closes. The list starts with the most used attributes
(dates, net weight, price, count, origin) and then all of them. In Portuguese each has a name followed by
its GS1 data title — "(392n) Preço de item de medida variável (PRICE)" — from the catalogue in
`static/i18n.js` (`ai.<code>`, 216 names, which distinguish pairs the data titles do not, such as (392n)
and (393n), both "PRICE"); in English the data title alone ("(17) USE BY or EXPIRY"). Searching finds either. It leaves out the record's own key and qualifiers (for a GTIN: (01), (22), (10), (21),
(235)). While the user types, `POST /portal/api/digital-link`
checks the attributes and returns the URI; the coloured link gains a green query-string part, and the QR
image, the test and copy buttons and the downloads (`GET /portal/api/qrcode?…&attr=17:271231&attr=3103:000500`)
all use it. While an attribute is wrong the message says why and nothing can be downloaded, so a code is
never produced without the attributes that were asked for.

**Not stored.** Attributes describe the item a code is printed for (this pack expires on…, weighs…), not
the record, so they are not written to the resolver, the history or the audit trail. They apply to the
code drawn at that moment and are cleared when another record is opened or a new one started.

**What the resolver does.** Nothing beyond passing them on: a GS1-Conformant Resolver transmits the whole
query string to the target (Resolver standard §2.12, requirement 19), exactly as it was sent. It does not
judge them; an invalid date reaches the target
unchanged. `dev-tests/resolver/test_resolver.py` checks this.

**Validation: the GS1 Barcode Syntax Engine itself.** About 500 AIs can be data attributes, each with its
own format, check digits, date, time and code-list rules (ISO 3166, ISO 4217…), and the GS1 General
Specifications §4.13 add invalid pairs (e.g. (3102) with (3103)) and mandatory associations (e.g. (17) needs
one of (01), (02), (03), (255), (8006), (8026); (4321) needs an SSCC). Rather than reproduce all of it, as the portal does for
keys and qualifiers, `portal/syntax.py` asks the GS1 Barcode Syntax Engine, the reference implementation
the resolver also uses:

- `portal/tools/build-syntax-engine.sh` downloads the release written in `docker-compose.yml`
  (`x-gs1-syntax-engine`, the one of the `gs1encoder` package the resolver and the data entry API install;
  ADR 0003) from GitHub, builds the native library and copies it with GS1's Python
  binding and the GS1 Barcode Syntax Dictionary of the same release to `/opt/gs1-syntax-engine`. The portal
  image does this in a separate build stage, so the compiler is not in the image; `GS1_SYNTAX_ENGINE_DIR`
  points to the directory. Updating the release is a deliberate change of that one value: build, run the
  tests (a weekly job opens an issue when a newer release exists).
- The engine runs inside the portal process (a few microseconds per check); one instance is shared by the
  portal's threads behind a lock.
- The engine builds the URI (`getDLuri`), so percent-encoding and order follow it; values may use any
  CSET 82 character, e.g. `(99)A(B)/C&D` → `?99=A%28B%29%2FC%26D`.
- The dictionary supplies the list offered in the editor (AIs flagged `?`, which excludes (8200), (03) and
  (8014) as §4.10 requires), their titles and format components, and the qualifiers of each key.

**Which AIs.** The list is the grammar of §4.10: `queryStringParam` names 156 parameters, which resolve to
530 AIs (the 5 newest — (7041), (8040) to (8043) — are in the dictionary of the engine's release 1.4.1 but not
as data attributes, so 525 are offered; a release that makes them data attributes adds them with no code
change, ADR 0003). The grammar deliberately includes every primary key and the batch/lot, so that a code can carry
a second identifier (§4.10 note, §5.9 and §5.11: an SSCC with the CONTENT, count and batch of what it
holds); 368 of them are the decimal variants of measures and amounts, (3100) to (3105) and so on, which the
portal groups into 59 families (below), so the list has 216 entries. It leaves out the AIs that would
go in the path of the record being edited. (The grammar lists `shipToaAdd1Parameter` and `shipToaAdd2Parameter` but defines them as
`shipToAdd1Parameter` and `shipToAdd2Parameter`, (4302) and (4303); a typing error in the standard.)

**Day 00.** GS1 dates marked `yymmd0` — (11), (12), (13), (15), (16), (17), and the date part of (4324) and
(4325) — accept day 00 as "last day of the month". The portal refuses it, as a policy: a person reading the
label, or a system receiving the URI, may not know the convention. The message gives the first and last
day of that month (e.g. 260200 → 260201 or 260228; 29 in a leap year) (`attr.dayZero`).

**Checks and messages.** The engine's refusals that users meet most get messages of their own in both
languages, naming the AIs as chosen ("(392n)", not the "(3920)" it became): a missing associated AI —
"Attribute (392n) also needs one of: (30) VAR. COUNT; (31nn); …", from the General Specifications'
mandatory associations — and an invalid pair — "Attributes (3102) and (310n) cannot be used together". The
portal refuses, with its own message in both languages: an AI that is the key
or one of its qualifiers (it would go in the path and the code would point at another record — for a
batch, serial or variant, open the record with that qualifier), an AI that is not a data attribute, a
repeated AI, an empty value, day 00, a number written wrongly for a decimal family (above), more than 100
attributes. Everything else is the engine's judgement, shown as
"The GS1 Barcode Syntax Engine refused the attributes: …" followed by the engine's own message (English),
e.g. *AI (17): The date contains an illegal month of the year* or *Required AIs for AI (17) are not
satisfied: 01,02,03,255,8006,8026*. As a last guard, the path of the engine's URI must be the record's own.

**Without the engine** (an image built before this feature, or a build without network access to GitHub)
the portal logs a warning, the option is not shown and QR codes work as before.

**Decimal families.** For measures (31nn–36nn) and amounts, prices and discounts (39nn) the fourth digit
of the AI is the number of decimal places: (3102) 012345 is 123.45 kg. `syntax.decimal_families()` groups
them from the dictionary as the General Specifications write them — 59 families such as (310n) NET WEIGHT
(kg), (392n) PRICE, (393n) PRICE with an ISO 4217 currency — and `Engine.resolve_decimal()` turns what is
typed into the right AI and digits:

| Chosen | Typed | In the URI |
|---|---|---|
| (310n) | `123,45` or `123.45` | `3102=012345` (padded to 6 digits) |
| (310n) | `500` | `3100=000500` |
| (392n) | `12,50` | `3922=1250` |
| (393n) | `986 12,50` | `3932=9861250` (currency code first) |
| (3103), a member typed by number | `1,5` | `3103=001500` (its 3 decimal places) |
| (3922), a member typed by number | `1250` | `3922=1250` (digits without a separator keep the GS1 meaning) |

Comma and point are both accepted as the decimal separator, since the portal's users write either; a value
with more than one separator (`1.234,56`) is refused, so there is never a doubt about a thousands separator.
Also refused, each with its own message: more decimal places than the family (or the member) allows, more
digits than the AI holds, anything but digits. Under each converted attribute the editor shows how it went
into the URI ("In the URI: 3102=012345"). Typing a member's number ("3103") in the list finds its family;
typing it and leaving the field keeps that exact member.

**Limits and choices.** No fixed number of attributes: the real limit is what fits in the QR code at the
chosen version and error correction level, and the label says when the content does not fit. A ceiling of
100 attributes per request only protects the server. The editor does not offer date pickers: GS1 users know the AI formats, and the numeric keyboard
opens for date fields on phones. AI titles are GS1's data titles, which are
language-neutral on labels.

## Resolver CE changes

| Before | After | Standard reference |
|---|---|---|
| `/10/<unregistered batch>` → 500 | uses the GTIN's links (walks up the tree) | 2.5.9, 2.5.10, item 16 |
| nothing recorded about resolutions (only gunicorn's access line, with the client's address) | each resolution request recorded in `resolver_log.requests` after it is answered, in the background, without the client's address or User-Agent; answers unchanged ([ADR 0006](../adr/0006-resolver-request-log.md)) | — (operation) |
| batch with a missing linkType → 200 with an error inside | 404 | 2.6.2, items 9 and 18 |
| `/10/123/` (trailing slash) → 400 | treated as `/10/123` | 2.13, item 25 |
| `?linkType=defaultLink` → 300 with an object | redirects to the default target | 2.5.8 |
| only `x` and `gs1:x` | also `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, case-insensitive | 2.5.2, 2.14 |
| linkset keys and JSON-LD context in `https://gs1.org/voc/` | `https://ref.gs1.org/voc/`, the namespace of `gs1:`; stored documents keep `https://gs1.org/voc/` (`web_logic.public_linktype_key()`) | 2.14, item 24 |
| linkset with JSON-LD keys, relative anchor | plain RFC 9264, validates against the linkset schema; JSON-LD only with `Accept: application/ld+json` | 2.10, item 10 |
| JSON-LD context Link header malformed and hidden from CORS | `<…/linkset-context>; rel="http://www.w3.org/ns/json-ld#context"`, exposed | 2.10, item 13 |
| query string always passed on, with a second `?` if the target already had one | passed on exactly as sent (`;` delimiter and keys without a value kept), always — `fwqs: false` is ignored, the option having been removed in Resolver 1.2.0; joined with `&` | 2.12, item 19 |
| without `linkType`, several links of the default type in different languages and no matching language → 300 with a JSON list | the default link, unless the request decides a language variant; those links published as `gs1:defaultLinkMulti` | 2.5.8, 2.6.1, 2.6.3 (examples 5-7) |
| choice among links of one type: `Accept-Language` without q-values, exact tags only (`pt-BR` ≠ `pt`), 400 for links without a media type, 300 body without anchor | media type, then language (q-values, RFC 4647 lookup), then context; 300 answers a valid linkset of that level, or an HTML page | 2.6.3 (examples 8-13), 2.10 |
| request path checked as an element string: qualifiers out of order, data attributes or unknown AIs in the path redirected | the GS1 Barcode Syntax Engine's Digital Link parser checks the path: 400 | 2.4.1; URI Syntax 4.9, 4.10 |
| `%2F` in a value decoded by the proxy and by Werkzeug: 400 | the raw request URI reaches the resolver (`$request_uri`) and each segment is decoded on its own | 2.4.1; URI Syntax 4.2 |
| a single segment that is not a compressed Digital Link → 500 | 400 (HTML page for browsers) | 2.4.1 |
| `/eh…` and `/ex…` (EPC binary strings) read as legacy compression → 500, then 400 | decompressed and resolved as the equivalent GS1 Digital Link on the resolver's own stem: every EPC scheme with a Digital Link (schemes before TDS 2.0 from the TDT 2.2 artefacts, `+` schemes with +AIDC data, `++` schemes with their hostname ignored); key qualifiers from the tag in the path, data attributes in the query string, passed on before the request's own; 400 with the reason when the string does not decode | 2.3, item 5; EPCB 1.0.0, 4.2; URI Syntax 6.1.2 (RE3) |
| HTML linkset page without JSON-LD; JSON with no `Accept` header | JSON-LD embedded; HTML when the request has no `Accept` header | 2.10 |
| description file with the internal `_id` and GS1's terms of use | neither; `termsOfUse` from `RESOLVER_TERMS_URL` | 3 |
| serial-number record and batch record both applying: the one with more qualifiers wins | the serial number's | 2.5.9, rule 4 |
| browsers get raw JSON on errors | HTML page in the gs1.org style (logo, pt-BR/en-GB language menu) with the same HTTP status; a 404 for a linkType lists the available links | 2.6.2 (MAY list other links) |
| `?linkType=linkset` in a browser → JSON | HTML page listing the links per level (the key, then each applicable qualified record: variant, batch/lot, serial, …) | 2.10 |
| — | on the HTML pages only `http`/`https` targets are links; others (`javascript:`, `data:`, stored through the API, which takes any href) are listed without a link, so they cannot run in the resolver's origin | — |

An unknown linkType **still** returns 404: the standard requires it (2.6.2, item 18). Up to GS1 Digital
Link 1.1 the resolver redirected to the default target; that is no longer permitted. Apps and scripts that
ask for JSON keep receiving JSON.

Without these changes the portal still works, but the defects in the table remain.

### EPC binary strings in detail

An NFC tag (often a hybrid UHF/NFC tag) can emit `https://<resolver>/eh<hexadecimal>` or
`https://<resolver>/ex<base 64>`, where the characters after `eh`/`ex` are the tag's EPC in the binary
encoding of the EPC Tag Data Standard. The resolver turns it into the GS1 Digital Link the EPC stands for:

| Request | Resolved as |
|---|---|
| `/eh30164596f40c0e5cbe991a83` (SGTIN-96, EPCB example) | `/01/09528765123457/21/123456789123` |
| `/exMBZFlvQMDly-mRqD` (the same, base 64) | `/01/09528765123457/21/123456789123` |
| `/ehfb342cde795211411234538566cb0afc4` (DSGTIN+, TDS annex E.3) | `/01/79521141123453/21/32a%2Fb?17=220630` |
| SGTIN+ with +AIDC data (10) L1 and (17) 261231 | `/01/…/10/L1/21/…?17=261231` |
| `/ehfd37…d800` (SGTIN++ with the hostname id.example.com) | `/01/79521141123453/21/32a%2Fb` on this resolver |

- **What is supported.** The schemes defined before TDS 2.0 that have a GS1 Digital Link (SGTIN-96/198,
  SSCC-96, SGLN-96/195, GRAI-96/170, GIAI-96/202, GSRN-96, GSRNP-96, GDTI-96/113/174, SGCN-96, ITIP-110/212,
  CPI-96, CPI-var), the twelve `+` schemes of TDS 2.0 and the twelve `++` schemes of TDS 2.3. GID-96,
  USDOD-96 and ADI-var have no GS1 Digital Link: 400.
- **Where the rules come from.** The machine-readable artefacts of EPC Tag Data Translation 2.2, shipped in
  `web_server/src/tdt/` exactly as GS1 publishes them; TDS 2.3 for the methods of section 14.5 and the
  hostname tables, which have no artefact yet.
- **Key qualifiers and data attributes** (owner's decision). A batch, variant or serial number carried in
  +AIDC data is a key qualifier: it goes to the path, in the order of the key, and takes part in the
  walk-up. Everything else (the date of a DSGTIN+, an expiry date, a weight…) is a data attribute: it goes to
  the query string, which the resolver passes on to the target (2.12), in front of whatever query string the
  request itself had. The path and the attributes are checked together by the GS1 Barcode Syntax Engine; a
  combination the engine refuses (for example AI 7258 without 8018 and 7259) answers 400.
- **Hostname of a `++` EPC** (owner's decision). Decoded, so that the data after it can be read, and
  ignored: the resolver answers on its own stem, as EPCB 4.2 (step 3) says. Tags that should resolve
  elsewhere should carry that host in the URI they emit.
- **Not used.** The filter value (no counterpart in a Digital Link). The +AIDC data toggle bit is not
  relied on: whatever follows the EPC is decoded (TDS 14.5.1 makes it non-essential for decoding).
- **Refused (400, with the reason).** Unknown or reserved headers (`00`, `E2`, `FE`…), bits after the data
  that are not zero, values cut short or longer than their AI allows, implausible dates and times, reserved
  encodings, a special +AIDC data header (`A0`…`FF`), an AI given twice. Upper-case `EH`/`EX` and
  upper-case hexadecimal are not EPC binary strings (RE3).

## Operations

After every installation or update, check the resolver **through the proxy** as well as the health check,
which reaches the web server directly (item 1.5 broke every resolution through the proxy while
`/portal/healthz` stayed `ok`):
```bash
curl -s http://127.0.0.1:8080/portal/healthz                                  # {"portal":"ok","resolver":"ok","worker":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/.well-known/gs1resolver    # 200
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:8080/01/<a registered GTIN>   # 307 …
```

`"worker":"unavailable"` means no job worker has reported in the last 30 seconds: the portal works, but
imports and link checks wait in the queue. See `docker compose logs --tail=60 portal-worker`. The worker
finishes the record in hand and hands its job back when it is stopped (`docker compose stop` or an update);
a worker that is killed leaves its job to the next one after two minutes. Jobs and their results are kept for
30 minutes after they end.

Audit trail (who changed what):
```bash
docker compose logs -f portal-service | grep portal.audit
# ... user=maria action=update anchor=/01/07891234567895 lot=L2026A links=3 removed=1
```

### Replicas

`web-service`, `data-entry-service`, `portal-service` and `portal-worker` keep no state of their own (the
resolver's records and the portal's data are in MongoDB), so each can run as several containers. Set the
number in `.env` and apply it:
```bash
sed -i "s/^WEB_SERVICE_REPLICAS=.*/WEB_SERVICE_REPLICAS='2'/" .env   # or edit the file
docker compose up -d                       # adds or removes containers of the changed services only
docker compose ps                          # …-web-service-1, …-web-service-2, …
```
- **The proxy follows by itself.** nginx asks Docker's DNS for every replica's address again every 10
  seconds (`resolve` in `nginx.conf`) and shares the requests among them in turn; a request that meets a
  replica being stopped goes on to another. It no longer needs restarting when a service is recreated, and
  it starts even when a service is still down (that service's paths answer 502 until it is up).
- **Use `.env`, not `--scale`.** `docker compose up -d --scale web-service=3` works, but the next
  `docker compose up -d` (every update) goes back to the numbers in `.env`.
- **Processes and replicas.** Inside each container gunicorn runs `*_PROCESSES` processes (default 2) with
  eight threads each. On one server, more processes and more replicas both use more CPU cores; replicas also
  let one container be recreated while the others answer, and are what spreads a service over several
  servers later (item 7.4).
- **Job workers.** Each `portal-worker` replica runs one job at a time; more replicas run more imports and
  link checks in parallel. Two replicas never take the same job.
- **Names and commands.** Containers are named `<project>-<service>-<n>` (the project is the folder's name
  in lower case); only `database-server` and `frontend-proxy-server` keep fixed names. Use service names in
  commands: `docker compose logs portal-service` shows every replica (each line prefixed with its
  container), `docker compose exec portal-service …` runs in the first replica (`--index 2` for another).
- **Session key.** With several portal replicas on one host the fallback `secret.key` is shared through the
  volume; on several hosts set `PORTAL_SECRET_KEY` (the installer always does).
- **The proxy image** follows nginx's 1.30 branch (`nginx:1.30-alpine`); `docker compose build --pull
  frontend-proxy-service && docker compose up -d` takes its latest security release.

### Load test and scale-out rehearsal

`dev-tests/load/load_test.py` (item 7.4; Python's standard library only, so it runs from a laptop or another server)
sends scans at a steady rate for a while — an open model: a slow server does not slow the arrivals, as with real
scans — and reports the answers, the errors (no answer, or 5xx) and the response times (mean, p50, p95, p99, max), in
total and per kind of request: a phone's scan (`text/html`, the redirect not followed), an app reading the linkset,
the item's page (`--mix scan=90,linkset=5,page=5` by default). Its User-Agent is counted as automated by the request
log, so the scans of the overview stay real. It passes when errors are at most `--max-errors` % (1) and p95 at most
`--max-p95` ms (1000). Run it against staging, or against production only in an agreed window.

A rehearsal, on staging:

1. A file of registered codes (from the portal's spreadsheet export, one GS1 Digital Link path per line), and a
   baseline with one replica of each service:
   ```bash
   python3 dev-tests/load/load_test.py --base https://<staging FQDN> --codes codes.txt --rate 20 --duration 60 --json r1-20.json
   ```
2. Raise the rate (50, 100, 200 requests a second…) until p95 passes 1000 ms or errors appear; watch
   `docker stats` (CPU per container) and the database during each run.
3. Add replicas of the resolver (`WEB_SERVICE_REPLICAS=2`, then 4) and processes (`WEB_SERVICE_PROCESSES`),
   `docker compose up -d`, and repeat: the rate at which p95 passes 1000 ms should rise with them while the CPU allows.
4. Record each run (`--json`), the replica and process counts, the server's size and the rates in the history; the
   agreed target load decides the production sizing.

The first rehearsal on staging (two replicas of each service, 15 October 2026) saturated at about 26 requests a
second, the resolver's containers at 100 % CPU and everything else idle: the official code started a Node.js process
for every check of a request's syntax. The resolver now checks in its own process (`web_server/src/gs1_syntax.py`)
and starts Node.js only when the engine's library is missing from its image, which its log says at start-up
(`GS1 Barcode Syntax Engine not loaded … each check starts Node.js`). To check a running installation:
`docker compose exec web-service python -c "import gs1_syntax; print(gs1_syntax.available())"` answers `True`.

Scans are reads: MongoDB on the same server is rarely the limit before the CPU of the resolver's processes. When it
is, or for availability, a MongoDB replica set (three members on separate machines, `MONGO_URI` and `PORTAL_DB_URI`
listing them with `replicaSet=`) is the next step; the services need no change for it.

To offer more link types, add a row to `LINK_TYPES` in `portal/gs1.py` and its labels to every locale in
`portal/static/i18n.js`, then run `docker compose up -d --build portal-service portal-worker` (the worker
runs imports with the same rules).

## Hardening

- Every data entry operation except `/api/heartbeat` requires the bearer token, including `/api/index`
  and `/api/summary`. In `/api/docs`, click **Authorize** and enter `Bearer <SESSION_TOKEN>`; the value
  stays only in that browser tab (nothing is stored) and is sent with every protected operation.

- Behind a TLS reverse proxy on the same host set `PROXY_BIND_ADDRESS=127.0.0.1` and
  `DATABASE_BIND_ADDRESS=127.0.0.1` in `.env`: plain HTTP (port 8080) and MongoDB (27017) then stay off the
  network. Docker publishes ports past the host firewall (ufw/iptables), so this setting matters.
- With the portal live, restrict `/api` and `/swaggerui` at the edge proxy to the integrations that
  genuinely need them.
- The portal is given no root database credentials: its MongoDB user may read and write the portal's own
  database only (`readWrite` on `PORTAL_DB_NAME`); only the one-shot `portal-db-init` service receives
  `MONGO_URI`.
- For many users, switch on single sign-on per organisation (*Organisation sign-in*, below) and, once it works,
  password sign-in off for that organisation.
- `PORTAL_EXPORT_LIMITS` limits what each role may export (below).

## Daily backup

`scripts/resolver-backup.sh` dumps every MongoDB database (the resolver's records and the portal's users,
record metadata, journal and daily request counts) and the request log `resolver_log`, through the database container so the credentials never appear on the host,
and archives the portal's configuration volume, keeping 14 days in `/var/backups/resolver`. It finds the repository from its own location.

```bash
sudo scripts/resolver-backup.sh                                     # test: prints OK and the sizes (ERROR and status 1 on a failure)
sed "s|REPOSITORY|$PWD|" scripts/resolver-backup.cron | sudo tee /etc/cron.d/resolver-backup >/dev/null
sudo chmod 644 /etc/cron.d/resolver-backup                          # daily at 02:30
```

Restore the database (replaces the current one):
```bash
docker compose exec -T database-service sh -c 'mongorestore -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --drop' < /var/backups/resolver/ARCHIVE.archive.gz
```
Then run `docker compose up -d`: `portal-db-init` runs again and gives the portal's user the password in
`.env`, whatever the restored database held.

Restore the portal configuration (the fallback session key and the `*.migrated` copies; only needed when
`PORTAL_SECRET_KEY` is not set):
```bash
docker compose exec -T portal-service tar -xzf - -C /app/config < /var/backups/resolver/portal-config-ARCHIVE.tar.gz
```
A backup taken before the portal used its database holds the portal's data in that archive (`users.json`,
`records-meta.json`, `journal.jsonl`) and none in the database dump. To restore such a backup, restore both,
remove the portal's database (`docker compose exec database-service sh -c 'mongosh -u
"$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin resolver_portal
--eval "db.dropDatabase()"'`) and run `docker compose up -d --force-recreate portal-db-init portal-service portal-worker`: the
files are imported again at the start.

**Off-server copy.** A backup on the same disk does not survive the loss of the server. Set `BACKUP_COPY_TO` in `.env`
to an rsync destination — a path on another disk or a mounted share, or `user@host:/path` over SSH with a key of
root's that needs no passphrase — and each run copies its archives there too (files of mode 600). A copy that fails
fails the run: `ERROR`, status 1 and an alert from the portal's monitoring, the local archive kept. The destination
keeps what it receives; its own retention is up to it.
```bash
grep -q '^BACKUP_COPY_TO=' .env || printf "BACKUP_COPY_TO='%s'\n" 'backup@vault.example.org:/srv/resolver' >> .env
sudo scripts/resolver-backup.sh                    # … copied to backup@vault.example.org:/srv/resolver … OK
```

**Restore rehearsal.** `scripts/restore-rehearsal.sh` restores an archive (the newest by default, or the one named)
into a throw-away MongoDB container of the installation's own image, with no network and nothing shared with the
running installation, prints each collection's documents next to the live database's, checks that the resolver's
records and the portal's users are in it, and removes the container. Run it after the first backup and then from time
to time (monthly), and after an upgrade of MongoDB:
```bash
sudo scripts/restore-rehearsal.sh
# Collection                                               Restored     Live now
# resolver_ce.gs1resolver                                      1204         1210
# resolver_portal.users                                           9            9
# …
# 2026-10-14T03:10:00+00:00 OK: the archive restores; differences from the live counts are the changes made since it was taken
```

## Secret rotation

`scripts/rotate-secrets.sh` replaces the secrets the installer generated with new random values and recreates the
services with them (about a minute without the resolver: run it at a quiet hour, after a backup). With no argument it
rotates all four; name some to rotate only those:

| Name | Setting | What else changes |
|---|---|---|
| `token` | `SESSION_TOKEN` | Systems that call the data entry API (`/api`) need the new token |
| `session` | `PORTAL_SECRET_KEY` | Every portal user is signed out |
| `portal-db` | `PORTAL_DB_PASSWORD` | Nothing: `portal-db-init` gives the portal's database user the new password on the start |
| `mongo` | `MONGO_INITDB_ROOT_PASSWORD`, `MONGO_URI` | Changed in MongoDB first (the new password given to `mongosh` on standard input); when the database refuses, `.env` keeps the old one and the script ends with status 1 |

No secret is printed or put on a command line. The previous `.env` is kept as `.env.bak-<time>` (mode 600) for going
back; delete it once the installation works with the new values.
```bash
sudo scripts/resolver-backup.sh && sudo scripts/rotate-secrets.sh
curl -s http://127.0.0.1:8080/portal/healthz       # {"portal":"ok","resolver":"ok","worker":"ok"…}
```

## Going to production

A checklist for an installation that will be printed on products (item 7.2):

- [ ] **Domain**: the production name (`FQDN`) is final — it goes into every QR code printed — and its DNS points at
  the server; `www.` or other names redirect to it if wanted. Organisations' own domains: ADR 0009.
- [ ] **HTTPS**: the certificate is valid and renews (`sudo certbot renew --dry-run`); the portal's monitoring warns
  21 days before it expires (`PORTAL_MONITOR_TLS_HOST`).
- [ ] **Clean installation** with `scripts/install.sh` on the production machine: its final checks request the home
  page, the description file, a scan of GS1's example GTIN through the proxy and the portal over HTTPS.
- [ ] **Secrets**: generated by the installer on this machine, never copied from staging; rotated
  (`scripts/rotate-secrets.sh`) if they were ever shared; `.env` mode 600; no `.env.bak-*` left behind.
- [ ] **First user**: its password changed at the first sign-in; one server administrator per person, no shared
  accounts.
- [ ] **E-mail relay** set and tested (`docker compose exec portal-service python mail.py test <address>`): alerts,
  invitations and password recovery depend on it.
- [ ] **Backups**: the daily cron runs (`/var/log/resolver-backup.log`), `BACKUP_COPY_TO` copies off the server, a
  restore rehearsal passed.
- [ ] **Monitoring**: `PORTAL_MONITOR_PROBE` names a registered code; the overview's *Operation* shows every check ok.
- [ ] **Firewall**: only 80 and 443 open to the world; 8080 and 27017 bound to 127.0.0.1 (`PROXY_BIND_ADDRESS`,
  `DATABASE_BIND_ADDRESS`).
- [ ] **Description file**: `RESOLVER_ORG_NAME`, contact and, if any, `RESOLVER_TERMS_URL` are the operator's.
- [ ] **Load**: replicas sized from a load test (`dev-tests/load/`).

## Development tests

See `dev-tests/README.md`.
