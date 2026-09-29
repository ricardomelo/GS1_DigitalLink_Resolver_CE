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
(`/portal/#records`): every record on the resolver (any primary key and qualifiers), most recently changed first, with
description, GTIN, scope (every unit or batch), number of links and the last change made through the
portal (date and user).

- Search by GTIN (leading zeros optional), description or batch; several words narrow the result;
  case and accents are ignored. Filter by the user who made the last change.
- Selecting a record opens it in the editor; the browser's back button returns to the list.
- Records with qualifiers the portal does not edit (serial numbers, variants), created by other
  tools, are listed but not opened.

Data comes from the data entry API's `GET /api/summary` (one request for all records) and from the
portal's own `records-meta.json` in the `resolver-portal-config` volume, which records who created and
last changed each record through the portal. Changes made through the API directly show "no history".
The whole list is sent to the browser, which is comfortable up to a few thousand records.

## Spreadsheet import and export

In **Registered records**, *Export spreadsheet (Excel)* and *Export CSV* download every record the
portal can edit, and *Import spreadsheet* reads one back.

**Layout** — one row per target (link); rows with the same GTIN and batch/lot form one record:

| GTIN | Batch/lot | Description | Link type | URL | Language | Title | Default | Forward query string |
|---|---|---|---|---|---|---|---|---|
| 07898357410015 | | Coffee 500 g | gs1:pip | https://… | pt, en | | yes | yes |
| 07898357410015 | | Coffee 500 g | gs1:instructions | https://…/manual.pdf | pt | Manual | | no |

- Headers are written in the user's language and recognised in any of the portal's languages (or as the
  keys `gtin`, `lot`, `description`, `linkType`, `url`, `language`, `title`, `default`, `forward`).
  Only GTIN, Description, Link type and URL are required.
- The XLSX file has two more sheets listing the link type codes and the language codes. GTINs are
  written as text, so Excel keeps the leading zeros. The CSV uses `;` and UTF-8 with BOM, as Excel
  expects in Brazil; imports also accept `,` and Windows-1252.
- Link types may omit `gs1:`; addresses without `https://` get it, as in the editor; several languages
  go in one cell separated by commas; *Default* marks the target that opens first (the first row if
  none is marked); *Forward query string* is yes unless it says no.
- Languages: any well-formed BCP 47 tag (`pt`, `pt-BR`, `en-US`, `vi`, `und`, …), written in canonical
  case. The editor's menu offers the common ones and keeps any other tag a record already has.
- Records created by other tools with qualifiers the portal does not manage (serial numbers, lot
  templates such as `{lotnumber}`) are listed but neither exported nor imported.

**Import** is in two steps. The portal first checks the whole file with the editor's own rules and shows,
record by record, what will be **new**, **changed**, **unchanged** or **with errors** (with the file's row
number and the reason, e.g. a GTIN that Excel turned into scientific notation). Nothing is written until
*Import records* is confirmed; records with errors are skipped. Each record in the file replaces the
record on the resolver entirely, as a save in the editor does; records that are not in the file are not
touched (import never deletes). The import runs in the background with a progress counter, records who
made each change, and writes one audit line (`action=import created=… updated=… failed=…`).

Limits: 700 KB per file and 5 000 rows (split larger files). The default link type is shared by all the
records of a GTIN, so an import cannot change it while the GTIN has other records.

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
not exist (the site of GS1 Brasil does, for example). The checker relies on the status the site sends,
so such addresses pass as valid; open them with *Try now* after registering. Guessing from the page
content would raise false alarms on legitimate pages.

Only public addresses are contacted: host names that resolve to private, loopback, link-local or other
non-global addresses (the Docker network, the cloud metadata service) are refused at every redirect, so
the checker cannot be used to probe the server's own network.

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

**Way back.** The GS1 logo on the portal and on the resolver's pages, and the portal's user menu ("Home
page"), lead back to `/`.

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
| QR code label | `GET /portal/api/qrcode?format=png\|svg&hri=0\|1` | generated locally from `{RESOLVER_PUBLIC_URL}/01/{gtin14}[/10/{lot}]` (see "QR code label") |

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
It follows the symbol and text dimensions of the *QR Codes powered by GS1 design guidelines* (v1.0, May 2024):

- **Size:** the SVG is sized in millimetres at the 100 % target X-dimension, 0.495 mm per module. The PNG
  uses 12 pixels per module and carries a DPI value (≈ 616) that prints at the same size. Do not print
  below 100 %: the text is 2.2 mm high at that size and must not fall under the 2 mm minimum.
- **Quiet zone:** 4X on all four sides, always blank.
- **Human readable interpretation** (checkbox, on by default): the element strings below the quiet zone,
  `(01)` followed by the GTIN-14 and, for a batch, `(10)` followed by the batch/lot on a second line, in
  Liberation Sans (metrically equivalent to Arial). The guidelines require it when the QR code stands alone
  on pack; it may be omitted when the code sits next to the linear barcode that already carries the GTIN,
  or on a consumer-engagement panel.
- **SVG** is fully vector: QR modules and HRI glyph outlines, so it opens identically anywhere
  and is the format to hand to packaging designers. PNG suits documents and quick use.
- The choice is remembered in the browser. Files are named after the key and qualifiers, e.g.
  `qrcode_01_09506000134352_10_L1.svg`.

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
