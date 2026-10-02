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
docker compose exec portal-service python create_user.py maria --remove   # remove
```

The user store (`users.json`, password hashes) and the session key (`secret.key`) live in the named
volume `resolver-portal-config`, which the image initialises with the right owner.

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
| admin | everything, user administration, audit trail |
| editor | create, change, delete records; import; link checks |
| reader | consult, list, export, labels |

- `users.json` holds, per user: password hash, role, GS1 Company Prefixes, disabled, must-change flag,
  creation and last sign-in. Files from before roles (`{"name": "<hash>"}`) are read as administrators and
  converted on the next write.
- GS1 Company Prefixes (4-12 digits) limit a user to identifiers whose company part starts with one of
  them (`gs1.company_part`: after the indicator digit of GTIN-14 and ITIP, the extension digit of SSCC and
  the filler zero of GRAI). Records, lists, exports, imports, labels, history and link checks are filtered
  or refused (`access.prefix`).
- Temporary passwords (16 characters without look-alikes) are shown once; the account can only call
  `/config`, `/password` and `/logout` until it sets its own password.
- A password reset, disabling or removal ends the user's open sessions (session fingerprint).
- `journal.jsonl` (portal configuration volume, mode 600) records every event: `login`, `login-failed`,
  `logout`, `password-change`, `create`, `update`, `delete` (with the record's content), `import`,
  `export`, `user-create`, `user-update`, `user-reset`, `user-remove`. The editor's History panel shows
  the last 20 versions of a record; the audit trail shows events without record contents.

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
portal's own `records-meta.json` in the `resolver-portal-config` volume, which records who created and
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
made each change, and writes one audit line (`action=import created=… updated=… failed=…`).

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
  and offers *Only with problems*. The latest result is kept until the portal restarts and is shown
  again when the list opens; opening a marked record checks its targets in the editor.
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
  (`gs1resolver_portal`: HttpOnly, Secure, SameSite=Lax, path `/portal`) valid for 8 hours after the last
  use; afterwards the user is sent back to the sign-in page with a "session ended" message.
- Every password field (sign-in, password change) has an eye button that shows or hides what is typed
  (`static/password.js`, `aria-pressed`, labelled in the user's language). The field is hidden again when
  its form is submitted, so password managers still see a password field. The script is one of the few
  files served without a session (`PUBLIC_ASSETS`), because the sign-in page needs it.
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

**Way back.** The GS1 logo on the portal and on the resolver's pages, and the portal's user menu ("Home
page"), lead back to `/`.

**Domain independent.** Links to this installation are root-relative (`/portal/`, `/api/docs`,
`/.well-known/gs1resolver`), the resolver root shown in the example link is read from the address bar,
and the operator's name in the footer comes from `contact.fn` in the resolver description file, linked to
`contact.hasURL` (`RESOLVER_ORG_URL`) when that is an `http(s)` address, as in the footer of the resolver's
pages; any other address leaves the name as plain text. Nothing
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

- **Size:** the SVG is sized in millimetres at the 100 % target X-dimension, 0.495 mm per module. The PNG
  uses 12 pixels per module and carries a DPI value (≈ 616) that prints at the same size. Do not print
  below 100 %: the text is 2.2 mm high at that size and must not fall under the 2 mm minimum.
- **Quiet zone:** 4X on all four sides, always blank.
- **Human readable interpretation** (full by default; or the key only, or none): the element strings below
  the quiet zone, one per line: the key (e.g. `(01)` followed by the GTIN-14, `(414)` followed by the GLN), then each
  qualifier in path order (e.g. `(10)` followed by the batch/lot, `(21)` followed by the serial), then
  each data attribute in the order entered (see below), in
  Liberation Sans (metrically equivalent to Arial). The guidelines require it when the QR code stands alone
  on pack; it may be omitted when the code sits next to the linear barcode that already carries the same
  data, or on a consumer-engagement panel.
- **SVG** is fully vector: QR modules and HRI glyph outlines, so it opens identically anywhere
  and is the format to hand to packaging designers. PNG suits documents and quick use.
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

- `portal/tools/build-syntax-engine.sh` downloads a pinned release (1.4.1, the one of the `gs1encoder`
  package the resolver installs) from GitHub, builds the native library and copies it with GS1's Python
  binding and the GS1 Barcode Syntax Dictionary of the same release to `/opt/gs1-syntax-engine`. The portal
  image does this in a separate build stage, so the compiler is not in the image; `GS1_SYNTAX_ENGINE_DIR`
  points to the directory. Updating the release is a deliberate change: build, run the tests, update the
  script.
- The engine runs inside the portal process (a few microseconds per check); one instance is shared by the
  portal's threads behind a lock.
- The engine builds the URI (`getDLuri`), so percent-encoding and order follow it; values may use any
  CSET 82 character, e.g. `(99)A(B)/C&D` → `?99=A%28B%29%2FC%26D`.
- The dictionary supplies the list offered in the editor (AIs flagged `?`, which excludes (8200), (03) and
  (8014) as §4.10 requires), their titles and format components, and the qualifiers of each key.

**Which AIs.** The list is the grammar of §4.10: `queryStringParam` names 156 parameters, which resolve to
530 AIs (the 5 newest — (7041), (8040) to (8043) — are not yet known to the engine's release 1.4.1, so 525
are offered). The grammar deliberately includes every primary key and the batch/lot, so that a code can carry
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
| batch with a missing linkType → 200 with an error inside | 404 | 2.6.2, items 9 and 18 |
| `/10/123/` (trailing slash) → 400 | treated as `/10/123` | 2.13, item 25 |
| `?linkType=defaultLink` → 300 with an object | redirects to the default target | 2.5.8 |
| only `x` and `gs1:x` | also `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, case-insensitive | 2.5.2, 2.14 |
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

Audit trail (who changed what):
```bash
docker compose logs -f portal-service | grep portal.audit
# ... user=maria action=update anchor=/01/07891234567895 lot=L2026A links=3 removed=1
```

To offer more link types, add a row to `LINK_TYPES` in `portal/gs1.py` and its labels to every locale in
`portal/static/i18n.js`, then run `docker compose up -d --build portal-service`.

## Hardening

- Every data entry operation except `/api/heartbeat` requires the bearer token, including `/api/index`
  and `/api/summary`. In `/api/docs`, click **Authorize** and enter `Bearer <SESSION_TOKEN>`; the value
  stays only in that browser tab (nothing is stored) and is sent with every protected operation.

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
