# Changelog

## Unreleased (branch gs1br/develop)

### The staging tests of 21 October (session 18)
- **Fixed: the request log's space limit could not be saved on a fresh page**: on *Requests → Retention*, *Save*
  beside *Most space on disk (MB)* reloaded the page unless the days had been saved first in the same page, and each
  save of the days added another copy of its handler. Commit `4797247`.

### The staging tests of 20 October and the owner's notes (session 17)
- **A limit on the space the request log may use** (finding F1; [ADR 0006, section 9](../adr/0006-resolver-request-log.md)):
  server administrators set the most space on disk on *Requests → Retention* (megabytes; empty: no limit). Beyond it,
  the hourly housekeeping deletes the oldest requests down to 95 % of the limit (journal event `requestlog-trimmed`);
  the monitoring's new check *Request log space* is an alert from 80 % of the limit, with a message at each further
  5 % (85, 90, 95, 100) and one when it falls below 80 % again; the overview's *Operation* shows the share. What
  counts is the collection's used pages and its indexes. Commit `2425487`.
- **Testing a failed certificate without a second domain** (finding F2): the operator's guide gives the procedure used
  on staging. Commit `5421bd3`.
- **Upgrading an installation of the official GS1 Resolver CE v3** in place: `scripts/upgrade-from-official.sh` checks
  it, backs up the database, stops the official containers (the volume kept), checks out this branch beside the
  official one, keeps the database's credentials and the data entry token, runs the installer and compares the
  records before and after; `--check` only checks. Commit `0c76bf0`.
- **Turkish** as a twelfth language of the portal, its e-mails, the resolver's pages, the item's page and the home page
  (a draft, as the other languages but Portuguese and English; [ADR 0014, section 7](../adr/0014-interface-languages.md)).
  Commit `984f2ce`.
- **Language menus with the Latin alphabet first**: Deutsch, English, Español, Français, Italiano, Português, Türkçe,
  then العربية, हिन्दी, 中文, 日本語, 한국어 — in the portal, on the home page and on the resolver's pages. Commit `984f2ce`.
- **Every language of a target listed**: the *Language* field of a target opens a list of the 200-odd languages the
  browser names, scrolled, with a count and *type to filter*, in the same order, filtered by what is typed. Commit
  `984f2ce`.
- **A map of where requests come from** on the *Requests* screen ([ADR 0006, section 10](../adr/0006-resolver-request-log.md)):
  a world map of the requests the filters select, each country shaded by its requests, each city a circle; zoom with
  the wheel, a drag or buttons; a click on a country zooms to it and lists its regions and cities. The resolver now
  records the city's position from the GeoIP database, rounded to a tenth of a degree (`ll`); the CSV gains `latitude`
  and `longitude`; the list shows the region beside the city. d3, topojson-client and Natural Earth's countries are
  served by the portal (no map service). New route `GET /portal/api/requests/places`. Commit `a287a64`.
- **The label's scanning environments checked against the GS1 General Specifications, release 26.0**
  ([ADR 0010, section 7.6](../adr/0010-label-studio.md)): one environment per symbol specification table of the
  decision tree — retail point of sale (1), retail and general distribution (3), general distribution only (2),
  retail pharmacy (10), healthcare and general distribution (8), non-retail healthcare (6), other trade items (4),
  logistic units (5), GDTI/GRAI/GIAI/GLN (9), GSRN (11) and direct part marking (7). *Healthcare* now follows table 6
  (Data Matrix up to 0.990 mm, EAN/UPC from 0.170 mm; it had table 11's 0.495 mm); direct part marking also takes the
  QR code. Only a key's environments are offered, its usual one first: **an SSCC, GDTI, GRAI, GIAI, GLN or GSRN label
  asked without `env` follows its own table** (an SSCC's QR code at 0.743 mm), and `env=retail` for them is refused
  (`label.environmentNotForKey`). Commit `6350211`.
- **The project's own logo** (backlog item 7.3): a QR code whose corner branches into links, in GS1 blue, in the
  headers of the portal, the sign-in page, the home page and the resolver's pages, instead of the GS1 logo the official
  project shipped (`gs1-logo.png` stays in the repository, unused). Its files, with a wordmark, are in
  `Documentation/images/logo` (Apache 2.0). Commit `3a17b40`.
- **Layout** (the owner's notes of 20 October): the sign-in page no longer keeps the sidebar's room (it looked pushed
  to the right); the screens use up to 1,536 pixels of a wide monitor instead of 1,216; the list of requests fits a
  1,280-pixel screen with the side menu, without scrolling sideways; *New organisation* puts the name level with the
  first prefix and *Add GCP* beside the prefixes; the side menu says *Organisation management*. Commit `3a17b40`.
- **The installation's privacy notice** ([ADR 0017](../adr/0017-privacy-notice.md)): a *Privacy notice* link in the
  footer of every page (portal, sign-in page, home page, resolver's pages, item's page) opens `/portal/privacy`, for
  anyone, signed in or not. Server administrators write the notice in the portal (*Privacy notice*: plain text with
  headings, lists and links, a preview); each publication is a new numbered version, never changed, the earlier ones
  readable from the page. Until one is published the page shows a default notice in the reader's language: what is
  recorded, the days requests are kept, and that the installation is the sole responsibility of whoever operates it,
  neither GS1 nor the software's contributors answering for it, the software provided "as is". New collection
  `privacy_notice`; routes `GET /portal/privacy`, `GET` and `PUT /portal/api/privacy`. Commit `37b14e8`.
- **Forwarding to other resolvers** ([ADR 0018](../adr/0018-forwarding.md)), set by server administrators on the
  portal's new *Forwarding* screen: a **resolver of last resort** (off after installation; `https://id.gs1.org` unless
  another address is set) answers 307 with the request's path and query string for a key this resolver does not know,
  instead of 404; **prefix rules** (3 to 12 digits) send every key of a prefix to a destination — another resolver,
  the path kept, or a fixed address — before this resolver's own records, the longest prefix first. Both switch on and
  off in the portal and reach the resolver within 30 seconds. The request log records the outcomes *forwarded* and
  *fallback*; the overview counts both and gives server administrators a *Forwarding* group (the last resort, its
  requests and codes, the rules and the requests of each), in the exports too. The side menu's long names wrap.
  Commit `8673873`.
- **The installation's appearance** ([ADR 0019](../adr/0019-appearance.md)), set by server administrators on the
  portal's new *Appearance* screen: a **title** in place of *GS1 Resolver Community Edition* (in the headers and the
  browsers' tab titles), a **logo** (PNG, JPEG or WebP, up to 200 KB) and three **colours** — main, action and highlight
  — with a live preview; a colour on which white text would be hard to read (below 4.5:1) is refused. The portal (its
  sign-in page and privacy notice too) and the home page show it at once, the resolver's pages and the item's page
  within 30 seconds; **Restore the original** brings back the original title, logo and colours. Each change is in the
  journal (`appearance-save`, `appearance-reset`). The resolver's description file keeps the software's name.
  Commit `fbb44ff`.
- **The appearance's tab icon and the title in the pages themselves** ([ADR 0019, section 6](../adr/0019-appearance.md)):
  an **icon for the browsers' tabs** (favicon), set apart from the logo, with *Use the original icon*, shown on every
  page — the portal, the home page, the resolver's pages (the item's page keeps its brand's logo) and the resolver's
  `/favicon.ico`; the preview shows the browser's tab with the icon and the title. The portal now serves its pages with
  the title, the logo and the icon already in their HTML, so the original no longer shows before the scripts run.
  Commit `d23f518`.
- **Third-party software, data and licences** (`Documentation/third-party.md`): every component, data source and
  service with its licence; what an operator must do (the notices, the DB-IP attribution, GS1's terms for the GCP
  table, trademarks); why nothing restricts commercial use (MongoDB's SSPL included). The README's licence section
  points to it and names DB-IP.
- **The load test written up** (item 7.4, operator's guide): what the rehearsal of 15 October measured and what it did
  not, and the more exhaustive tests recommended before production.
- **The backlog after the owner's decisions of 20 October**: 7.2 later; 7.3 the logo done, the Portuguese AI names left
  open; 7.4 more exhaustive load tests before production; 8.1 the material to send prepared, the owner sends it.

### Owner's additions of 17 October: the project's documentation (backlog item 9.11)
- **An inventory of every feature drawn from the development tests** ([ADR 0016](../adr/0016-documentation-and-feature-inventory.md)):
  `Documentation/test-inventory.md` lists every check of every test program by area (4,061 checks in 61 programs),
  with a section gathering every search and filter; `features.md` cites, for each feature, the checks that prove it;
  `dev-tests/docs/test_docs.py` keeps both, the developer guide's counts, the index and the links in step. The pytest
  layer keeps each program's `PASS` lines with `DEV_TESTS_INVENTORY`. Commit `6b8737e`.
- **The documents by reader**: `Documentation/README.md` as the index (people who register records, organisations'
  administrators, operators, integrators, developers), the tenant API reference (`api-reference.md`, generated from
  `portal/openapi.json` by `portal/tools/gen_api_reference.py`), the user guide's tables of every search and filter and
  of every administration task, the operator's guide with a table of contents and its missing Data Matrix and EPC
  sections. Commit `6b8737e`.
- Checks added where a feature had none: the order of data attributes, an import that never deletes, a CSV cell above
  128 KB. Commit `6b8737e`.

### Owner's additions of 17 October: an EPC for every key that has one (backlog item 9.10)
- **The label studio's RFID and NFC block for every key the EPC Tag Data Standard encodes** — SSCC, GLN (with or
  without its extension), GRAI, GIAI, GSRN, GSRNP, GDTI, GCN, CPID and ITIP besides the GTIN — as soon as the record
  holds what the EPC needs ([ADR 0010, section 8](../adr/0010-label-studio.md)): the EPC in hexadecimal, its tag URI and
  the links for NFC; the 96-bit scheme for numeric values, the longer one otherwise; filter 0 by default for keys that
  are not trade items. The encoder follows the EPC Tag Data Translation artefacts the resolver decodes with
  (`portal/epc_schemes.json`, generated by `portal/tools/gen_epc_schemes.py`). Commit `6c7c755`.
- **Resolver fix**: an EPC of an SGLN, GRAI, GDTI or SGCN with a 12-digit company prefix was decoded into a key one
  digit too long (the empty reference written as "0"); it now gives the right key. Commit `6c7c755`.

### Owner's additions of 17 October: the GS1 Company Prefix's length from GS1's table (backlog item 9.9)
- **GS1's GCP length table uploaded in the portal** ([ADR 0015](../adr/0015-gcp-length-table.md)): server
  administrators upload `GCPPrefixFormatList.xml` on *Organisations* (and each later version); the page compresses it,
  the portal checks it (root, date, every entry; a refusal names the problem) and swaps it in at once; an older list is
  asked about first. The table is GS1's and restricted, so it is not in the repository and is never downloaded
  automatically; `python gcp.py load` in the portal's container loads it too. New collection `gcp_table`.
  Commit `5dd6bfe`.
- **Uses**: the EPC's partition (the person's choice, then the table, then the organisation's prefixes), the GS1 Company
  Prefix shown under the key in the editor, and a warning beside an organisation's prefix that disagrees with GS1's
  list (on its page and on the organisations' list). A range the list marks as not a GS1 Company Prefix is said so, and
  has no EPC unless a length is chosen. Commit `5dd6bfe`.

### Owner's additions of 17 October: export limits in the portal (backlog item 9.8)
- **Export limits are set in the portal** instead of `.env`
  ([ADR 0012, section 8](../adr/0012-single-sign-on.md#8-amendment-of-17-october-2026--export-limits-set-in-the-portal-item-98)):
  server administrators set the most rows one export may hold in every organisation (*Organisations*, empty by
  default: no limit), and each organisation's administrators set limits for readers, editors and API keys on the
  organisation's page (new *Exports* tab), never above that maximum. An organisation's administrators are now capped
  by the maximum; server administrators have no limit. Changes are journalled (`export-limits`, `export-maximum`).
  Commit `f0c1d4f`.
- **The tenant API's record listing** reaches at most the organisation's limit for API keys (the first that many
  records, `exportLimit` in the answer; `total` still counts all) and is refused when that limit is 0. Commit `f0c1d4f`.
- **`PORTAL_EXPORT_LIMITS` is obsolete**: read once at the first start of this version as the starting limits of the
  operator and of every existing organisation, then ignored with a warning; remove it from `.env` afterwards.
  Commit `f0c1d4f`.
- The *New organisation* form's prefixes label used the label studio's card style by mistake (item 9.2): it is a plain
  label again. Commit `f0c1d4f`.

### Staging feedback of 16 October: interface languages (backlog item 9.7)
- **Nine more languages**: Español, Français, Deutsch, Italiano, 中文（简体）, 日本語, 한국어, हिन्दी and العربية (right to
  left), besides Português (Brasil) and English (UK), in the portal, its e-mails, the resolver's pages, the item's page
  and the home page; each named in itself in the menus; the browser's language picks one, the choice is shared as
  before ([ADR 0014](../adr/0014-interface-languages.md)). The translations were drafted by Claude and are to be
  reviewed by native speakers before production ([translation guide](../translation-glossary.md)). Commit `3d66bdd`.
- The portal loads a language's catalogue only when it is used (`portal/static/locales/<tag>.json`); Arabic pages are
  laid out right to left (the styles now use logical properties); every text in every language is checked by
  `dev-tests/portal/test_i18n.py`, and `CLAUDE.md` asks every delivery to end with its texts in every language.
  Commit `3d66bdd`.

### Staging feedback of 16 October: domains without the terminal (backlog item 9.6)
- **A domain verified in the portal is served within about 5 minutes, certificate included**: the installer schedules
  `scripts/custom-domains.sh apply --quiet` every 5 minutes as root when it set up Let's Encrypt
  (`/etc/cron.d/resolver-domains`); the portal itself still never touches the host
  ([ADR 0009, section 7](../adr/0009-tenant-domains.md#7-amendment-of-17-october-2026--domains-without-the-terminal-item-96)).
  Commit `0bfe208`.
- **The domain's card shows the certificate's state**: *pending*, *served over HTTPS* until a date, or *failed* with the
  reason and the next attempt; the script reports each domain into the portal's database (`domain_hosts`) and each run
  (`domains.hostRun`), which server administrators see above the list, with a warning when it has not run for 15
  minutes. After a failed certificate the next attempt waits longer each time (5 minutes doubling up to 6 hours), below
  Let's Encrypt's limits; a run holds a lock. Commit `0bfe208`.

### Staging feedback of 16 October: the request log's browser, location and retention (backlog item 9.5)
- **The browser and the approximate location of each scan** — country, region and city — are worked out when the
  request arrives and kept; the visitor's address is used for the lookup and forgotten, never stored
  ([ADR 0006, section 8](../adr/0006-resolver-request-log.md#8-amendment-of-17-october-2026--browser-approximate-location-retention-set-in-the-portal-item-95)).
  The *Requests* screen shows them, filters by browser and country, and opens a city in Google Maps; the overview and its
  exports count browsers, countries and cities. The location comes from DB-IP's free *IP to City Lite* database
  (Creative Commons Attribution 4.0, credited on the screen), downloaded monthly by the new `scripts/geoip-update.sh`,
  which the installer schedules and runs once; `GEOIP_URL` takes another source of the same format. New settings
  `RESOLVER_LOG_ADDRESS_HEADER`, `RESOLVER_GEOIP_DB`, `GEOIP_URL`; the resolver mounts the repository's `geoip/` folder
  read only; a new dependency of the resolver's image, `maxminddb`. Commit `b768463`.
- **How long requests are kept is set in the portal** (*Requests → Retention*): the installation's days by server
  administrators, each organisation's the same or fewer by its administrators; the space the log uses is shown.
  `RESOLVER_LOG_DAYS` becomes the default until then (and still switches the log off). A shortened period is applied
  within the hour by the worker, for which the portal's database user may now delete events of the log (a new role,
  `requestLogPrune`, made by `portal-db-init`). Commit `b768463`.

### Staging feedback of 16 October: every link type and language (backlog item 9.4)
- **Every link type of the GS1 Web Vocabulary** in the editor (57 in version 1.16, against 29 before), each named and
  explained in both languages, in groups ordered by the key type (places first for a GLN, business to business for an
  SSCC, the organisation for a GSRN…); the menu follows a change of key type. `portal/gs1_link_types.json` is written by
  `portal/tools/gen_link_types.py` from the vocabulary and the development tests check it. Commit `1e40f8c`.
- **Every language for a target**: a searched list of every ISO 639-1 language and the usual regional tags, named in the
  user's language; several separated by commas; a malformed one is pointed out before saving. Commit `1e40f8c`.

### Staging feedback of 16 October: labels (backlog item 9.3)
- **GS1 DataMatrix** (the record's element string with FNC1) and **Data Matrix with the GS1 Digital Link URI** on the
  label, besides the QR code, in every format and the zip; made with libzint (`zint-bindings`, a new dependency of the
  portal's image) ([ADR 0010, section 7](../adr/0010-label-studio.md#7-amendment-of-17-october-2026--data-matrix-hri-as-text-sizes-by-scanning-environment-item-93)). Commit `7f9892e`.
- **Scanning environment** on the label (retail point of sale, healthcare, direct part marking): the module size range
  of the GS1 General Specifications, the symbols each takes, the sizes within the range. Commit `7f9892e`.
- **The SVG's human readable text as text**, an option (outlines remain the default). Commit `7f9892e`.
- The tenant API's label takes `symbol`, `env` and `hritext`. Commit `7f9892e`.

### Staging feedback of 16 October: administration and navigation (backlog item 9.2)
- **Architecture decision record** [ADR 0013](../adr/0013-administration-and-navigation.md).
- **A left sidebar** on wide screens with every screen of the user menu, foldable to its icons; the current screen
  marked; every screen fits a phone's width. Commit `a3b3cea`.
- **An organisation's page**: its prefixes, users, domains, item page brands, single sign-on, API keys and alerts in
  one place (*Organisation* in the menu; *Open* on the organisations' list). Commit `a3b3cea`.
- **Prefixes one per row** with *Add GCP* and a remove button, checked as typed; **users' prefixes picked** from their
  organisation's own. Commit `a3b3cea`.
- **The portal's own confirmation dialog** instead of the browser's. Commit `a3b3cea`.
- **The overview by organisation** for server administrators; *Operation* for them only, its lines that matter to
  everyone under *Record quality*. Commit `a3b3cea`.
- **Alert history**: each alert raised and ended is kept (collection `alert_history`, 400 days) and listed on a new
  *Alerts* screen with filters. Commit `a3b3cea`.

### Staging feedback of 16 October: the item's page per record (backlog item 9.1)
- **Each record chooses its default target** — its item's page, or its own first target: the product can open its page
  while a batch or serial number goes to its own target. A scan of the GTIN alone, or of a batch without a record,
  follows the product's record. A key whose records use the page has **explicit default links**: its default link type
  is `gs1:defaultLink` and every record has its own (its page, or copies of its default targets), written and hidden by
  the portal; taking the page turns the key's other records, each keeping its target (checked with `POST
  /api/validate` first). Keys without the page are unchanged; stored records need no conversion
  ([ADR 0011, amendment](../adr/0011-item-page.md#8-amendment-of-17-october-2026--the-items-page-per-record-item-91)).
  Commit `cb67cf5`.
- **The editor shows how the key's other records use the page**, above the targets; a new batch starts with the
  product's choice. Commit `cb67cf5`.
- **Fixed (B1): the option was lost when a record was reopened**, and saving it then failed: the data entry API left
  links of type `gs1:defaultLink` out of what it returns. It now returns them (a change to the official data entry
  API), which also lets a link be removed from such a record. A new test compares the portal's stand-in with the real
  API. Commit `cb67cf5`.
- **Fixed (B2): a brand stayed with its old owner** when its prefix moved to an organisation; brands now belong to
  whoever holds their prefix, and an organisation's domains are the default only for prefixes it still holds.
  Commit `cb67cf5`.
- **The item's page shows each link type once**, in the visitor's best language, the language marked when it is not
  the page's; the other translations under *Other languages*. **The brand's logo is the page's favicon.** Commit `cb67cf5`.

### The resolver's syntax check in its own process (load test of item 7.4)
- **The resolver checks each request path with the GS1 Barcode Syntax Engine in its own process**
  (`web_server/src/gs1_syntax.py`), the engine's C library at the compose file's release built into its image; the
  official code started a Node.js process per request, which made the resolver CPU-bound at about 26 resolutions a
  second on staging. The answers are the same; Node.js is kept as the fallback when the library is missing.
  Commit `653ffc6`.

### The backlog's "later" list
- **Exports follow the filters**: with filters on, the record list's exports hold only the records it shows; the
  filters and the search text are kept in the address (`#records?key=01&qualifier=10…`). Commit `3df0c50`.
- **Data entry API checks values** with the GS1 Barcode Syntax Engine of its image (check digits, lengths, character
  sets, associations), templates such as `{lotnumber}` left out; conformance review F11 fixed. Commit `a1131bb`.
- **The record search reads scanners and RFID readers**: raw scan data with a symbology identifier (`]d2`, `]Q3`,
  `]C1`…), element strings without brackets, EPCs in hexadecimal or `eh…`/`ex…`. Commit `576b48a`.
- **Serial numbers registered with their batch or variant** (before rule 2 of §2.5.9) fixed from the record list.
  Commit `8dbc85d`.
- **`POST /api/validate`** in the data entry API, and the portal asking it before rewriting a key's document, so that
  a deletion never removes what could not be written back. Commit `8dbc85d`.
- **RFID and NFC on the label**: the EPC of a serial number (SGTIN-96 or SGTIN-198) and its compressed link for NFC
  tags. Commit `e1b6917`.
- Development tests: failed checks become annotations of the GitHub job (`bd6e0d9`); `test_exports.py` empties the
  shared request log on a real MongoDB (`45fe9d7`); `test_store_mongodb.py` compares the portal user's roles as a set
  (`0855a82`).

### Single sign-on per organisation and per-role limits on exports (backlog item 7.1)
- **Architecture decision record** [ADR 0012](../adr/0012-single-sign-on.md).
- **Organisation sign-in** (user menu, administrators): each organisation's OpenID Connect provider — issuer, client
  ID, a write-only secret, e-mail domains — tested from the screen; a server administrator sees every one and sets the
  operator's. Collection `sso`; journal `sso-save`, `sso-remove`. Commit `732b5c0`.
- **Sign in with your organisation's account** on the sign-in page: the e-mail's domain chooses the provider; the code
  flow with PKCE, state and nonce; the ID token verified with the provider's keys; the account with that e-mail in that
  organisation signed in, nobody created; refusals explained on the sign-in page and journalled. Commit `732b5c0`.
- **Password sign-in off** per organisation (never for server administrators); password recovery then sends nothing
  to those users. Commit `732b5c0`.
- **`PORTAL_EXPORT_LIMITS`**: the most rows one export of a role may hold (records, requests), 0 for none; the page
  hides the export buttons of a role that may not export. Commit `732b5c0`.
- The audit trail names every journal action (the domains', the overview export and the item page's brands showed
  their codes). Commit `732b5c0`.
- New dependency `pyjwt[crypto]`. Commit `732b5c0`.

### Default link titles in the link's language (backlog item 7.3, conformance review F21)
- A link saved without a title gets its type's title in Portuguese when the link is in Portuguese, in English
  otherwise (was: English always); the editor shows a title the portal gave as empty, so that it follows a change of
  language. Commit `266dcf3`.

### Load test script (backlog item 7.4)
- `dev-tests/load/load_test.py`: scans at a steady rate with a mix of phones' scans, apps' linksets and item pages;
  answers, errors and response times with pass/fail thresholds; the procedure of a scale-out rehearsal in the
  extensions documentation. Commit `37c5664`.

### Production readiness (backlog item 7.2)
- **Off-server copy** of each daily backup to `BACKUP_COPY_TO` (rsync); a failed copy fails the run and is recorded for
  the monitoring. Commit `449edef`.
- **`scripts/restore-rehearsal.sh`**: restores an archive into a throw-away container of the database's image and
  compares the counts with the live database. Commit `449edef`.
- **`scripts/rotate-secrets.sh`**: new values for the API token, the portal's session key, the portal's database
  password and MongoDB's root password (changed in the database first), never printed. Commit `449edef`.
- **Installer**: the final checks also request a scan through the proxy and the portal over the public address.
  Commit `449edef`.
- A production checklist in the extensions documentation. Commit `449edef`.

### The item's page and Verified by GS1 (backlog items 6.1 and 6.2)
- **Architecture decision record** [ADR 0011](../adr/0011-item-page.md).
- **The item's page** (resolver; deliberate change to the official linkset page for browsers): the item's description
  as title, the brand of the record's prefix, a large button per link with an icon for its type, the visitor's language
  first, the levels, JSON-LD as before; no web fonts or other external content on it. Commit `3d59bc2`.
- **Default target: the item's page** in the editor, `landingPage` in the tenant API and the portal API, a row of type
  `gs1:defaultLink` in spreadsheets: a `gs1:defaultLink` to `?linkType=linkset&view=page`, redirected to like any
  default; shared by the records of a key like the default type; the key's own record gets its own page. Commit `3d59bc2`.
- **Clicks** through `/_click` (the link found again in the record: no open redirect) and **page views** in the request
  log (form `landing`, outcomes `page` and `click`; an automated client's logged as plain answers); the overview counts
  them apart from scans (`pageViews`, `clicks`, also in `/v1/stats`); the Requests screen filters them. Commit `3d59bc2`.
- **Item page** screen (administrators): brands per GS1 Company Prefix with an uploaded logo (PNG, JPEG, WebP up to
  200 KB; SVG refused) and two colours; the operator's and the installation's default (`*`) for server administrators;
  collection `branding`, read by the resolver every minute; logos served at `/_brand/<prefix>`; journal
  `branding-save`, `branding-remove`. Commit `3d59bc2`.
- **Verified by GS1** on the page for GTINs and GLNs when `RESOLVER_VERIFIED_BY_GS1_URL` is set (empty by default) and
  the brand has not switched it off; never in the linkset. Commit `3d59bc2`.
- The check of every record's links leaves the items' pages out. Commit `3d59bc2`.

### The label studio (backlog items 5.2, 5.3 and 5.4)
- **Architecture decision record** [ADR 0010](../adr/0010-label-studio.md).
- **Size** of the label: 80, 90, 100, 120, 150 or 200 % of the target X-dimension (QR code 0.396 to 0.990 mm), the
  human readable text staying 2.2 mm. Commit `d60421f`.
- **PDF** download: one vector page the size of the label, no font embedded, the URI as its title. Commit `d60421f`.
- **EAN-13, UPC-A, EAN-8 or UPC-E beside the QR code** for GTINs of consumer units (the transition to 2D), at 0.330 mm
  times the same size, with quiet zones, bar heights, guard bars and digits as the General Specifications place them;
  header `X-Linear-Symbol`. Commit `d60421f`.
- **Download all (ZIP)**: SVG, PNG and PDF with a `README.txt` of the sizes. Commit `d60421f`.
- The default label (100 %, no linear symbol) is exactly as before. Commit `d60421f`.

### The organisation's own domain in the QR code (backlog item 5.1)
- **Architecture decision record** [ADR 0009](../adr/0009-tenant-domains.md).
- **Domains** (user menu, administrators): an organisation's own domains, with an optional path stem, proved by a DNS
  TXT record `_gs1resolver.<domain>`, kept verified, looked at again daily; default per GS1 Company Prefix; *Test*
  through the domain; at most 10 per organisation; journal `domain-create`, `domain-verify`, `domain-update`,
  `domain-remove`. Commit `0a6e42a`.
- **Labels**: *Domain in the QR code* (default of the prefix, the installation's, a verified domain); the preview, the
  record's `digitalLink`, the tenant API's records and labels (`domain=`) follow it. Commit `0a6e42a`.
- **Resolver** (deliberate change to the official component, only for registered domains): a middleware recognises a
  verified direct domain from `X-Forwarded-Host` (which the proxy now passes), removes its stem, answers only for its
  organisation's prefixes (404 for others) and names it as `resolverRoot`; every other host is served as before.
  Commit `0a6e42a`.
- **`scripts/custom-domains.sh`** `list` / `apply`: nginx sites and Let's Encrypt certificates for verified direct
  domains on the host. Commit `0a6e42a`.
- The portal's requirements name `dnspython` (already installed with `pymongo`). Commit `0a6e42a`.

### Monitoring and alerts by e-mail (backlog item 4.3)
- **Architecture decision record** [ADR 0008](../adr/0008-monitoring-and-alerts.md) (committed with the docs of
  item 4.2, `b06ff53`, before its code).
- **Monitoring by the job worker** every `PORTAL_MONITOR_MINUTES` (5), one replica at a time: the resolver through the
  proxy (`PORTAL_MONITOR_URL`, an optional `PORTAL_MONITOR_PROBE`; an alert after two failed rounds), the daily
  backup's record (failed, or no good run for `PORTAL_MONITOR_BACKUP_HOURS`, 26), the certificate of `FQDN`
  (`PORTAL_MONITOR_TLS_HOST`; expiring within `PORTAL_MONITOR_CERT_DAYS`, 21, or invalid), and spikes of "code not
  registered" per scope (`PORTAL_ALERT_404_MIN`, 20, and `PORTAL_ALERT_404_FACTOR`, 3, times the usual hour). States in
  the collection `alerts`. Commit `57a5420`.
- **Alerts by e-mail** in the new category *alerts* (optional, on by default; Options → E-mail for administrators):
  seven messages in both languages — resolver down and up, backup failed and good again, certificate expiring and
  valid again, spike of 404 with the codes scanned most; a reminder every 24 hours while an alert lasts. Server
  administrators receive the installation's, an organisation's administrators its spikes. Commit `57a5420`.
- **The overview** lists the active alerts of the scope and, for server administrators, the state of each check.
  Commit `57a5420`.
- **The daily backup records its result** in the portal's database (`backup.last`, with `mongosh` inside the database
  container); a record that cannot be written is a warning in its log, never a failed backup. Commit `57a5420`.
- **Fix**: e-mail preferences kept only the categories switched on, so a category on by default could not be switched
  off; both values are kept now. Commit `57a5420`.

### Overview after sign-in (backlog item 4.2)
- **Architecture decision record** [ADR 0007](../adr/0007-overview-indicators.md): a new view opened after sign-in,
  five groups of indicators per scope for 7, 30 or 90 days against the period before, computed on request, exports,
  `/v1/stats`.
- **The overview** (`#overview`, *Visão geral*): usage (scans by people, automated requests apart, per day, the most
  scanned codes, shares by device, form, language and link type), resolution quality (requests answered, **scanned
  codes nobody registered** with *Register* opening the editor, codes without the link asked, invalid requests,
  errors, average time; the slowest day's 95th percentile for the whole installation), record quality (records and
  keys by type, no key-level record, serial with batch or variant, no description, keys nobody scanned, link
  problems), operation and, for administrators, governance (record changes by kind and user, sign-ins and refusals,
  exports, users by role, API keys active and expiring, the tenant API's calls). **Sign-in now opens the overview**;
  the editor keeps the portal's address and gains *Link editor* in the menu. Commit `16ceb9f`.
- **Exports** of the overview to Excel (a sheet of indicators with the previous period, sheets per day, codes and
  users) and CSV, journalled as `overview-export`. Commit `16ceb9f`.
- **Tenant API**: `GET /portal/api/v1/stats?days=` (usage, quality, records of the key's reach) with the new scope
  `stats:read` (*Read statistics*). Existing keys are unchanged. Commit `16ceb9f`.

### Development in Claude Code cloud sessions
- `CLAUDE.md`: the repository's conventions (language, commits, documents kept in step, tests) for Claude Code.
- `.claude/hooks/session-start.sh`, registered in `.claude/settings.json`: a cloud session installs the development
  tests' pieces at the versions pinned in `.github/actions/dev-tests-setup/action.yml` into `~/.cache/dev-tests` and
  exports the variables the programs read. The portal's GS1 Barcode Syntax Engine is built from a git clone of the
  release, because the session's proxy refuses the release tarball; nginx 1.30 is built from source. Commits are
  now pushed from the session itself, without bundles. **The software is unchanged.** Commit `b9bd4ed`.

### Documentation in English only
- The Brazilian Portuguese documentation is removed: `Documentation/pt-BR/` (overview, user guide, features, history,
  developer guide, conformance review, ADRs 0001–0006) and the Portuguese screenshots
  (`Documentation/images/guide/pt-BR/`). Readers of other languages can use their browser's translation. The links to
  them are gone from the README, the documentation index, the English documents and the ADRs;
  `dev-tests/docs/screenshots.py` makes the English images only. **The software is unchanged**: the portal, the
  resolver's pages, the home page and the e-mail messages stay in Brazilian Portuguese and British English.

### Backlog
- Item 4.4, a weekly summary by e-mail per organisation, removed from the open backlog in the README (both
  languages) at the owner's request, 14 October. No other item depended on it.

### Log of resolver requests (backlog item 4.1)
- **Architecture decision record** [ADR 0006](../adr/0006-resolver-request-log.md) (English and Portuguese): the
  resolver records each resolution request itself, asynchronously and without personal data; raw events with an
  expiry in a database of their own, daily aggregates per key by the worker, ownership derived at query time.
  Commit `e519771`.
- **The resolver's log** (step 2): each request for a GS1 Digital Link URI, a compressed one, an EPC binary string or
  `?compress` becomes one event in `resolver_log.requests` — key and company part, qualifiers (only the AI of a serial
  number or TPX), the AIs of data attributes (never their values), link type asked, outcome (`unknown` code and
  `noLink` told apart) with the level that answered, target host, time taken, language, device class, referrer host,
  optional country. Never the client's address, the User-Agent or the full referrer. A queue and a writer thread per
  process: a scan never waits for the database; lost events are counted. **Deliberate change to the official
  resolver**: two hooks and private keys in `web_logic`'s results, removed before answering, so answers are unchanged.
  `RESOLVER_LOG_DAYS` (90; 0 switches it off), `RESOLVER_LOG_COUNTRY_HEADER`. Commit `d633fcb`.
- **The log in the portal**: the portal's database user may read `resolver_log` (never write it); `/portal/api/requests`,
  `requests.csv` (journalled as `requests-export`), `requests/daily`; each user sees the requests of the records in his
  reach, a server administrator the whole installation. The worker counts each day per key into `request_daily`
  (`PORTAL_TIME_ZONE`, which the installer writes from the server; `PORTAL_STATS_DAYS`, 800). The tenant API's calls
  are recorded in `api_requests` (key, organisation, route template, status, time) and listed for administrators
  (`/portal/api/requests/api`). The portal's image gains `tzdata`. Commit `d633fcb`.
- **Fix: the daily backup** (found on staging, 14 October): `d633fcb` left `resolver_log` out with `--nsExclude`, which
  `mongodump` does not have, so the backup failed without a message of its own and left a partial file. The backup
  now keeps every database, the log included; a failed dump says `ERROR`, removes the partial file and exits with
  status 1; `test_deploy.py` checks the dump's options and runs the script with a stand-in `docker` (62). Commit
  `c1b3f78`.
- **Requests screen** (step 3, every user): the last 30 days as bars, the latest requests with filters, pages and a CSV
  export, the tenant API's calls for administrators; user guides (new section 16) in both languages. Commit `7b8967a`.
- **Tests**: `test_request_log.py` (73 checks), `test_requestlog.py` (74), `test_requests_e2e.py` (28); 26 mutations,
  all caught; the installer test checks the time zone (87), the deployment test the backup (62); `test_store_mongodb.py` checks the read-only role on the
  log. Commits `d633fcb`, `7b8967a`.

### Tenant API and API keys (backlog item 3.2)
- **Architecture decision record** [ADR 0005](../adr/0005-tenant-api.md) (English and Portuguese): a versioned API
  of the portal for organisations' own systems, keys owned by organisations and created by their administrators,
  a request limit per key, an OpenAPI description. Commit `326566d`.
- **The tenant API** (step 2), `/portal/api/v1`: who am I, records listed in pages, read, created or replaced
  (`PUT`), deleted; labels in SVG or PNG; `GET /portal/api/v1/openapi.json` (OpenAPI 3.1, public). Every call gets
  the scope of its key (organisation, role from the scopes, prefixes) and goes through the same functions as the
  portal's endpoints, so every rule applies; changes are journalled with the user `api:<key id>`. No CORS: the
  portal's Origin check refuses browser requests from other sites. Commit `bb0b496`.
- **API keys**: `rk_<id>.<secret>`, shown once, only the secret's SHA-256 stored (`api_keys` collection); scopes
  `records:read`, `records:write`, `labels:read`; optional prefixes inside the organisation's; a required validity
  (90 days by default, `PORTAL_API_KEY_MAX_DAYS` at most); 20 active keys per organisation; revocation;
  `api-key-create` / `api-key-revoke` in the organisation's trail. A server administrator's keys reach the
  operator's records only. Commits `bb0b496`, `c469f29`.
- **Request limit**: `PORTAL_API_RATE_PER_MINUTE` (120) per key and minute, counted in MongoDB for every replica
  (`api_rate`, TTL); 429 with `Retry-After`. The first request of a minute records the key's last use. Commit `bb0b496`.
- **E-mail**: the creator of a key is told when it is created and a week before it expires; the worker runs an
  hourly housekeeping (`app.HOUSEKEEPING`, `Worker.housekeep()`) for the second. Commit `bb0b496`.
- **API keys screen** (step 3, administrators): create (name, scopes, validity, prefixes), the key and an example
  shown once and removed from the page when the screen is left, the list with last use and state, revoke; user
  guides in both languages. **Fix:** choosing an item of the user menu with the mouse now closes the menu; it used to
  stay open while the pointer was over it, covering the chosen page (found when the menu grew by one item).
  Commit `c469f29`.
- **Tests**: `test_api.py` (92 checks, 16 protections mutation-checked, the OpenAPI document against the routes
  and the answers, no message key written twice in a language) and `test_api_e2e.py` (21). Commits `bb0b496`, `c469f29`.
- **Authorship**: on the owner's decision of 14 October, the commits of items 2.4, 2.5 and 3.1 (not yet pushed)
  were rewritten with Claude as author and the owner as co-author; their hashes changed and every document
  citing them was updated in the same rewrite.

### E-mail (backlog item 3.1)
- **Architecture decision record** [ADR 0004](../adr/0004-e-mail.md) (English and Portuguese): outgoing mail through
  an authenticated SMTP relay, messages as jobs of the worker, single-use links for invitations and password
  recovery, a notification framework with per-user preferences. Commit `a0ccc6a`.
- **Outgoing e-mail** (step 2), off unless `PORTAL_MAIL_HOST` is set: `portal/mail.py` sends through the relay with
  STARTTLS on 587 (default) or TLS on 465, the certificate always verified and no credential ever sent without
  encryption; `python mail.py test <address>` checks the settings. Settings `PORTAL_MAIL_*`, `PORTAL_INVITE_HOURS`,
  `PORTAL_RESET_MINUTES` in `.env.example`; the installer asks for the relay (optional). Commit `03c924b`.
- **Invitations**: a user created with an address gets a link (72 hours) to choose a password instead of a
  temporary one shown to the administrator; a reset by an administrator sends a link (60 minutes) and the old
  password stops working at once. Without an address, or with e-mail off, temporary passwords as before.
  Commits `03c924b`, `fbe86f0`.
- **Password recovery** on the sign-in page (*Forgotten your password?*): by user name or address, the same answer
  and timing for every entry, limits per entry and per browser address. Links carry a random token in the
  fragment of the address (never in a server log), stored only as a hash, valid once; choosing a password through
  one ends every session and link of the account. Commits `03c924b`, `fbe86f0`.
- **Notifications** in the user's language: security notices always (password changed, e-mail address changed —
  to the old and the new address —, account locked); finished imports and full link checks when the user asks
  (Options → E-mail). Messages are jobs of the worker (`type: "mail"`), retried after 1, 5, 15, 60 and 120 minutes,
  `mail-failed` in the audit trail without the address; the text leaves the job once sent. Jobs gain `notBefore`;
  a `tokens` collection; users gain `invited`, `language`, `languageChosen`, `notify`; journal actions
  `password-recovery`, `password-reset`, `invite-accepted`, `preferences`, `mail-failed`; `"mail"` in
  `/portal/healthz`. Commit `03c924b`.
- **Mailpit for trying it** (`docker compose --profile mail-test up -d mailpit`): a test relay that keeps every
  message, on `127.0.0.1:8025` only; never started by default. Commit `03c924b`.
- **Fix: the installer wrote some settings twice in `.env`** on a re-run (`FQDN`, `RESOLVER_CONTACT_REGION`,
  `PORTAL_ADMIN_USERNAME`, `TLS_MODE`, `DATA_ENTRY_SERVICE_REPLICAS`: the names at the end of a line of its list
  of managed keys), the old value last, so a value changed through the installer did not take effect. Found while
  writing the relay's test. Commit `f3d127d`.
- **Tests**: `test_mail.py` (138 checks, against an SMTP relay of the tests' own, `fake_smtp.py`; 16 protections
  mutation-checked) and `test_mail_e2e.py` (37, the screens in Chromium); the installer test covers the relay and
  duplicate keys (84). Commits `f3d127d`, `03c924b`, `fbe86f0`.

### One source for the GS1 rules (backlog item 2.5)
- **Architecture decision record** [ADR 0003](../adr/0003-gs1-rules-from-the-dictionary.md) (English and
  Portuguese): the portal's GS1 rules generated from the GS1 Barcode Syntax Dictionary of one pinned engine
  release; that release used by every service; every engine message translated; a weekly job proposing updates.
  Commit `8d50280`.
- **One GS1 Barcode Syntax Engine release** (step 2), written once in `docker-compose.yml`
  (`x-gs1-syntax-engine`, `1.4.1`) and passed to the five services that check GS1 data as the build argument
  `GS1_SYNTAX_ENGINE_RELEASE`. **Deliberate change to the official images**: `web_server/Dockerfile` and
  `data_entry_server/Dockerfile` installed whatever `gs1encoder` release was newest at build time; they now install
  the pinned one and refuse to build without it (build them through Docker Compose). The portal's build script
  and the CI set-up action read the same value. Commit `8e3d9c7`.
- **Rules from the dictionary** (step 3): `portal/gs1_dictionary.json`, generated from the pinned release's
  dictionary (`portal/tools/gen_dictionary.py`, `portal/gs1dict.py`); `gs1.py` builds the keys, qualifiers, their
  order, lengths and formats from it, with the portal's few deliberate exceptions (ITIP without (22), the
  character sets of values in a URI); a format the portal cannot check stops the build. The browser receives the
  same rules (`rules` in `/config`) instead of repeating them; a Pay-to GLN (415) now has a live check. The
  portal image copies every `*.json` of `portal/`. Same records accepted as before. Commit `6f6ce19`.
- **Weekly update check** `.github/workflows/engine-update.yml` (Mondays, and on demand): when a newer engine
  release exists it builds it in the runner's copy, regenerates the dictionary and the message table, runs the
  portal's tests and opens one issue per release with the differences, the messages that need a translation and
  the test results; it never pushes. Permissions `contents: read`, `issues: write`. Commits `6f6ce19`, `e7c5a6d`.
- **The engine's messages in the user's language** (step 4): the 94 messages and 117 linters' messages of 1.4.1
  are translated (`engine.*` in `i18n.js`; the English text is the engine's own), recognised from a table
  generated from the engine's sources (`portal/engine_messages.json`, `portal/tools/gen_engine_messages.py`,
  `portal/engine_messages.py`); `attr.invalid` keeps its English `detail` and adds `message`. The build script
  also copies the engine's message sources. AIs (7041) and (8040)–(8043) named in Portuguese. Commit `e7c5a6d`.
- **Tests**: `test_dictionary.py` (30 checks) and `test_engine_messages.py` (26), both mutation-checked;
  `test_deploy.py` checks the one release everywhere (59); `test_keys.py` checks the engine it compares with
  (138); the portal in Chromium reads an engine message in Portuguese (211 checks, 166 without the engine).
  Commits `8e3d9c7`, `6f6ce19`, `e7c5a6d`.

### Tenants (backlog item 2.4)
- **Fix: `tenants.py` in the portal image.** `portal/Dockerfile` copied the portal's modules by name and left
  out `tenants.py`, so the portal of `1590b7e` would not have started in a container. The image now copies every
  module at the top of `portal/`, and `test_deploy.py` starts the portal from the files the image would hold.
  Found before the update reached staging. Commit `7c10048`.
- **Architecture decision record** [ADR 0002](../adr/0002-tenants.md) (English and Portuguese): organisations
  (tenants) that own GS1 Company Prefixes; the operator owns whatever no tenant holds; the operator's
  administrators are the server administrators; read-only support access with a reason; an audit trail per
  tenant; an e-mail address per user. Documentation only (step 1 of 3). Commit `4bb39cd`.
- **Tenants on the server** (step 2 of 3): a `tenants` collection; a record belongs to the tenant whose prefix
  starts its key, worked out on every request (nothing changes in the resolver's database); overlapping
  prefixes between tenants, redundant prefixes within one and changes that would strand a user refused.
  **Every call is limited to the scope of the request** (the user's tenant, an open support access, or the
  operator), including the import worker before each record. **An installation without tenants behaves as
  before**: existing users become the operator's, nothing is migrated. Commit `1590b7e`.
- **Users per tenant**: a user belongs to one tenant (fixed at creation) or to the operator; a tenant
  administrator manages his tenant's users only, inside its prefixes; an operator user cannot be limited to a
  tenant's prefix; only server administrators count for the last-administrator rule. Optional, unique
  **e-mail address** per user (not used before item 3.1, never in the journal). `create_user.py --tenant
  --email`. Commit `1590b7e`.
- **New API** `/portal/api/tenants` (GET, POST, PUT, DELETE) and `/portal/api/support` (POST, DELETE), server
  administrators only; `/config` adds `accountRole`, `serverAdmin`, `tenant`, `support`; `/users` adds `tenant`,
  `tenantName`, `email`. Commit `1590b7e`.
- **Audit trail per tenant**: journal events carry `tenant` and `byOperator`; new actions `tenant-create`,
  `tenant-update`, `tenant-remove`, `support-open`, `support-close`, `login-refused` (a user of a disabled
  tenant). The History panel, the "changed by" columns and the last full link check are kept per scope. The
  audit CSV adds `organisation` and `by_operator` at the end. Commit `1590b7e`.
- **Screens** (step 3 of 3): **Organisations** (server administrators), support access with a banner, the
  organisation column, selector and filter and an e-mail column in **Users**, the organisation in the account
  menu, the organisation column and *operator* tag in the **Audit trail**. Commit `675b6ca`.
- **Messages**: `access.prefix` and `access.prefixRow` now say the identifier is outside the user's reach
  (organisation or prefixes); `users.lastAdmin` speaks of server administrators. Commit `675b6ca`.
- **Tests**: `test_tenants.py` (82 checks, every protection mutation-checked; also the translations of both
  languages); the portal in Chromium with organisations and support access (208 checks, 164 without the
  engine). Commits `1590b7e`, `675b6ca`.

### Architecture for scale (backlog item 2.3)
- **Architecture decision record** [ADR 0001](../adr/0001-portal-state-in-mongodb.md) (English and
  Portuguese): the portal's users, record metadata, journal, sign-in failures, jobs and caches move to a
  database of its own in the existing MongoDB, reached with a least-privilege user created by a one-shot
  `portal-db-init` service; imports and link checks run in a `portal-worker` container; the session key in
  `.env`; journal retention by age per category; automatic migration of the files at start-up; replicas in
  step 4. Documentation only (step 1 of 4). Commit `076f19a`.
- **The portal's data in MongoDB** (step 2 of 4): users, record metadata, the journal, sign-in failures, the
  link checker's cache and the last full link check move from the configuration volume and the worker's
  memory to the database `PORTAL_DB_NAME` (default `resolver_portal`) of the installation's MongoDB
  (`portal/store.py`). The public functions of `users.py`, `meta.py` and `journal.py` and every API answer
  are unchanged. Commit `d783f3d`.
- **Portal database user**: the one-shot Compose service `portal-db-init` (`portal/db_init.py`, the portal's
  image) creates the user `PORTAL_DB_USERNAME` with `readWrite` on the portal's database only, or brings its
  password and roles up to date, at every start; `portal-service` starts after it. The portal still gets no
  root `MONGO_URI`. New settings `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD`,
  `PORTAL_DB_HOST`, `PORTAL_DB_URI`. Commit `d783f3d`.
- **Migration**: at the first start the portal imports `users.json`, `records-meta.json` and `journal.jsonl`
  into empty collections, renames them `*.migrated` and logs the counts; an interrupted import finishes at
  the next start without duplicates. Commit `d783f3d`.
- **Sign-in lockout** shared by every replica and kept across restarts (`login_failures`, TTL 15 minutes).
  **Changes of users** run under a lock shared by every process, so the last enabled administrator cannot
  be removed by two administrators at once. Commit `d783f3d`.
- **Journal retention** by age per category, from the end of the event's day: `PORTAL_JOURNAL_SESSION_DAYS`
  (180), `PORTAL_JOURNAL_RECORD_DAYS` (0, for ever), `PORTAL_JOURNAL_ADMIN_DAYS` (0); a changed value is
  applied to older events at the next start. Commit `d783f3d`.
- **Session key**: the installer writes `PORTAL_SECRET_KEY` (and `PORTAL_DB_PASSWORD`) to `.env` and keeps
  them on re-runs; without it the portal logs a warning and uses `secret.key` in the volume, enough for a
  single replica. Commit `d783f3d`.
- **Tests**: the portal programs run on `mongomock` (`PORTAL_DB_URI=mongomock://`) or on a real MongoDB
  when `PORTAL_DB_URI` is set; `test_store.py` (58 checks); `test_store_mongodb.py` (the user's privileges,
  `test_store.py` as that user, the TTL monitor); a sixth CI job, informative at first, with a `mongo:7`
  service container; the installer test checks the new secrets (57 checks). Commit `d783f3d`.
- **Background jobs in a worker** (step 3 of 4): spreadsheet imports and checks of many links are documents
  of a `jobs` collection, run by a new Compose service, `portal-worker` (the portal's image, `python
  worker.py`), instead of threads of the portal: a restart of the portal no longer loses them, and nothing in
  the portal depends on the memory of one process. The web process only creates jobs and reads their state;
  the browser API keeps its calls and answers, with a `failed` state, `stalled` and `error` added.
  Commit `a072e9d`.
- **Interrupted jobs**: a worker stopped by `docker compose stop` or an update finishes the record in hand and
  hands its job back to the queue at once; a job of a worker that died goes back to the queue after two
  minutes without a heartbeat. An import continues from the first record not written; a link check starts
  again, the checker's cache answering what was done; after three interrupted attempts the job fails
  (`job.interrupted`), keeping what was written. Commit `a072e9d`.
- **Is the job worker running?** Workers announce themselves (`workers` collection); the browser says *In the
  queue…* while a job waits, warns when it has waited 15 seconds with no worker running, and says when a job
  failed; `GET /portal/healthz` adds `"worker": "ok" | "unavailable"`; the installer waits for the worker to
  report and warns when it does not. Commit `a072e9d`.
- **`PORTAL_WORKER`**: `external` (default, the `portal-worker` service) or `embedded` (a worker thread inside
  the portal, for development tests and a set-up without that service). Commit `a072e9d`.
- **Tests**: `test_jobs.py` (70 checks: queue, claims, ownership of writes, silent workers, the worker loop,
  imports and link checks through the API); `test_worker_processes.py` (13 checks: worker processes sharing a
  queue, SIGTERM and SIGKILL, on a real MongoDB, relayed by `test_store_mongodb.py`, now 161 checks); the
  portal in Chromium with the worker stopped and a failing job (190 checks, 146 without the engine); the
  installer with a worker that does not start (61 checks). Commit `a072e9d`.
- **Replicas** (step 4 of 4): `web-service`, `data-entry-service`, `portal-service` and `portal-worker` run as
  `WEB_SERVICE_REPLICAS`, `DATA_ENTRY_SERVICE_REPLICAS`, `PORTAL_SERVICE_REPLICAS` and `PORTAL_WORKER_REPLICAS`
  containers (`.env`, default 1; Compose's `deploy.replicas`). **Deliberate change to official code**: the
  fixed `container_name` of `web-service`, `data-entry-service` and `portal-service` is removed (Compose cannot
  replicate a service with one; containers are now `<project>-<service>-<n>`); the database and the proxy
  keep theirs. Commit `20f3304`.
- **gunicorn in the resolver and the data entry API** (**deliberate change to the official images**): both
  leave Flask's built-in server for gunicorn 26.2 (`__init__:create_app()`, so `main.py`'s SIGTERM handler
  does not replace gunicorn's; `python -m main` still starts the built-in server for development), with
  `WEB_CONCURRENCY` processes of eight threads (default 2, from `WEB_SERVICE_PROCESSES` and
  `DATA_ENTRY_SERVICE_PROCESSES`), requests finishing within Docker's stop period, request lines in the log.
  The portal moves from one gunicorn process to `WEB_CONCURRENCY` (`PORTAL_SERVICE_PROCESSES`, default 2).
  Commit `20f3304`.
- **The proxy follows replicas by itself**: each service is an upstream block with `resolve` in a shared zone,
  and nginx asks Docker's DNS again every 10 seconds; requests are shared among the replicas, a replica that
  refuses the connection is skipped, nginx starts while a service is down, and it is no longer restarted when
  a service is recreated (the `depends_on … restart: true` lines are removed). **Deliberate change to the
  official image**: `nginx:1.25.1-alpine` → `nginx:1.30-alpine` (`resolve` needs 1.27.3 or later; the 1.30
  stable branch also carries the security releases since 2023). The raw request URI to the resolver is
  unchanged. Commit `20f3304`.
- **Fix: the portal's fallback session key under concurrent starts.** Without `PORTAL_SECRET_KEY`, two
  processes starting at once could read `secret.key` before it was written and sign sessions with an empty
  key; the key is now written under another name and linked into place, and an empty file stops the portal
  with a message. Commit `20f3304`.
- **Installer**: writes the four replica counts to `.env` (not asked: 1, the environment or the existing
  `.env`; 1 to 20, anything else refused) and shows them in the summary. Commit `20f3304`.
- **CI**: the jobs *Portal in Chromium* and *Installer and deployment* are required (no longer
  `continue-on-error`); the proxy test runs on nginx 1.30.5 from nginx.org. Commit `20f3304`.
- **Tests**: `test_home.py` with a stub DNS server and replica upstreams on `127.0.0.x` (68 checks: start
  without a service's address, two replicas sharing requests, scale up and down without a restart, no failed
  request while replicas stop); `test_install.sh` with the replica counts (68); a new `test_deploy.py` (51:
  `docker compose config`, the proxy configuration, each image's gunicorn command started locally, the
  session key under concurrent starts). Commit `20f3304`.

### Continuous integration (backlog item 2.2)
- **Development tests through pytest**: `dev-tests/test_programs.py` runs each of the fifteen programs and the
  installer test as one pytest test (a subprocess; exit status and `PASS`/`FAIL`/`SKIP` lines); the
  programs are unchanged and still run by hand. Markers `resolver`, `portal`, `e2e`, `home`, `install`;
  each program's check count at the end and in the GitHub Actions run summary. **Strict mode**
  (`DEV_TESTS_STRICT=1`): a missing variable, path or command, or a `SKIP` line, fails. Commit `d68a883`.
- **GitHub Actions workflow** `.github/workflows/dev-tests.yml`: five jobs in parallel on every push and pull
  request to `gs1br/develop` (not for documentation-only changes), in strict mode; the portal in Chromium
  and the installer are informative at first. The composite action `.github/actions/dev-tests-setup` pins
  Python 3.12, Node.js 24, `gs1encoder` 1.4.1, `epc-tds` 1.4.1, `ajv-dist` 8.17.1, GS1's resolver test suite
  at `32597c1` and Docker Compose v2.29.7, and caches the engines, npm packages and Chromium. The empty
  `.github/workflows/main.yml` is removed. Status badge in the README (both languages). Commit `d68a883`.

### Quick wins (backlog item 2.1)
- **Portal session limits** (owner's decision of 13 October): the session ends after 30 minutes without
  use (`PORTAL_SESSION_IDLE_MINUTES`) and 12 hours after the sign-in whatever the use
  (`PORTAL_SESSION_MAX_HOURS`). The idle limit is the cookie's signed time, renewed by every request; the
  absolute limit is the sign-in time kept in the session (`since`; older sessions count from their next
  request). The page mirrors both (`SessionClock` in `app.js`): key presses, clicks, scrolling and touches
  count as use and renew the session quietly through the new `GET /portal/api/session`; tabs share the
  last call through `localStorage`; two minutes before the end a dialog counts down and offers *Stay signed
  in* (idle) or explains that a new sign-in is needed (absolute). `GET /portal/api/config` carries
  `session`. **`PORTAL_SESSION_HOURS` (8-hour sliding limit) is no longer read**; the portal logs a warning
  when it is set. A page request that finds the session over now shows the "session ended" reason too.
  Commit `1a1ca59`.
- **Home page**: the box showing the shape of a GS1 Digital Link is removed; one column. Commit `1a1ca59`.
- **Community notice** in the README (both languages), the documentation index and the footers of the home
  page, the sign-in page and the portal: the software and the official project are maintained by their
  communities, not by GS1 or any GS1 Member Organisation; whoever operates an installation is responsible
  for its use. Commit `1a1ca59`.
- Tests: new `dev-tests/portal/test_session.py` (30 checks); `test_portal_config.py` 13; `test_home.py` 55.
- Backlog reordered in the README (both languages) from the owner's notes of 13 October. Commit `bc1c86b`.

### GS1's resolver test suite (backlog item 1.4)
- **Staging passes every test** of GS1's own suite (https://ref.gs1.org/test-suites/resolver/, Resolver
  1.2.1): 31 of 31 on a GTIN whose default link has a Portuguese and an English version, 2 October 2026,
  before and after `bc573c4`.
- **New development test** `dev-tests/resolver/test_gs1_suite.py` (215 checks): the suite's JavaScript,
  unchanged, in Chromium against the resolver code, with a Python version of its PHP helper; seven
  scenarios. One known divergence, under a batch (erratum E12 below). Commit `cc95d77`.
- **Link types published in `https://ref.gs1.org/voc/`** (finding F22, owner's decision; **deliberate
  change to official code**): linksets (200 and 300, JSON and JSON-LD) and the JSON-LD context write the
  `gs1:` namespace as Resolver 1.2.1, section 2.14 defines it, and as the description file already
  declared it; the official code wrote `https://gs1.org/voc/`. Stored documents and the data entry API keep
  `https://gs1.org/voc/` keys; `?linkType=` still accepts every form. `test_resolver.py` 194 checks. Commit
  `bc573c4`.
- Candidate erratum E12 (conformance review, section 6): the standard does not say whether
  `gs1:defaultLinkMulti` links of a higher level apply under a level that has its own default link.

### Fixed: every resolution through the proxy answered 500 (since item 1.5)
The `upstream` block added in item 1.5 was named `resolver_web`; nginx sends the upstream's name as the
`Host` header, and Werkzeug 3.1 refuses a host name with an underscore before any resolver code runs, so
every `/…` request through the proxy answered 500 (`/portal/healthz` does not go through it and stayed
`ok`). The upstream is now `resolver-web`. `test_home.py` checks that every upstream receives a Host header
Werkzeug accepts (54 checks). Commit `b9a7631`.

### EPC binary strings: `/eh…` and `/ex…` (backlog item 1.6)
Conformance review finding F6 and the rest of F7. GS1-Conformant Resolver 1.2.1, section 2.3; GS1 Digital
Link URI: Compression Technical Standard for EPC binary strings (EPCB) 1.0.0.

- **Decompression**: a request whose only path segment is `eh` + lower-case hexadecimal or `ex` + base 64
  URL (RE3 of URI Syntax 1.7, 6.1.2) is decoded as an EPC binary string and resolved as the equivalent fully
  uncompressed GS1 Digital Link URI on the resolver's own stem; the linkset is that URI's (it was 500 before
  item 1.5, then 400).
- **Every EPC scheme with a GS1 Digital Link**: the schemes before TDS 2.0 (SGTIN-96, SGTIN-198, SSCC-96,
  SGLN-96/195, GRAI-96/170, GIAI-96/202, GSRN-96, GSRNP-96, GDTI-96/113/174, SGCN-96, ITIP-110/212, CPI-96,
  CPI-var) entirely from the artefacts of EPC Tag Data Translation 2.2, now shipped in
  `web_server/src/tdt/`; the twelve `+` schemes of TDS 2.0 with Table F and the methods of TDS 14.5,
  including the **+AIDC data** that may follow the EPC (TDS 15.3); the twelve `++` schemes of TDS 2.3 (no
  TDT artefacts yet) as their `+` scheme followed by a custom hostname (TDS 14.5.16).
- **Owner's decisions**: key qualifiers carried by the tag (a batch, variant or serial in +AIDC data) go to
  the path in the order of the key; data attributes (the date of a DSGTIN+, other +AIDC data) go to the
  query string and are passed on to the target before the request's own query string (2.12); the hostname
  inside a `++` EPC is decoded but **ignored** — the resolver keeps its own stem (EPCB 4.2, step 3).
- **Checks**: data attributes are checked with the path by the GS1 Barcode Syntax Engine's Digital Link
  parser (mandatory associations, plausible dates…). A string that matches RE3 but does not decode answers
  **400** with the reason: unknown or reserved header, scheme without a Digital Link (GID-96, USDOD-96,
  ADI-var), data after the end, value cut short, reserved encoding, repeated AI. The filter value has no
  counterpart in a Digital Link and is dropped; the +AIDC data toggle bit is not relied on (TDS 14.5.1).
- **Description file**: `"supportedPrimaryKeys": ["all"]` is now true for EPC binary strings as well.
- Tests: `dev-tests/resolver/test_epc_binary.py` (163 checks: the EPCB worked examples, every vector of TDS
  2.3 annex E.3 in both forms, +AIDC data and hostnames, refusals, 800 random EPCs compared with the
  independent library `epc-tds` when `EPC_TDS` is set); `test_resolver.py` 189 checks.
- Candidate errata found (conformance review, section 6): E8 in EPCB 4.2.2; E9 in TDS 2.3 annex E.3
  (headers of SSCC++ and ITIP++, hostname of SGTIN++ and DSGTIN++); E10 in TDS 2.3 Table 14-14 and 14-15;
  E11 in the TDT 2.2 artefact of CPI-var.

### Resolution fixes of the conformance review (backlog item 1.5)
Conformance review findings F7, F9, F10, F12-F19. Deliberate changes to official code are marked.

- **Default response** (Resolver 2.6.1, 2.6.3 steps 3-4): without `linkType`, the default link, unless
  the request decides a language variant; a record with its default target in two languages answered 300
  with a JSON list when the browser's language matched neither, or sent none (examples 5 and 7). Several
  links of the key's default type are published and used as `gs1:defaultLinkMulti` (2.5.8). The data entry
  API keeps the *first* link of the default type as `gs1:defaultLink` (official code kept the last).
- **Choosing a link** (official code replaced): `choose_links()` — media type, then language, then context,
  as 2.6.3 suggests (examples 8-13) — replaces the `_match_*()` helpers, which ignored q-values, matched
  language tags literally (`pt-BR` did not find `pt`) and failed with a 400 on links without a media type.
  The 300 Multiple Choices answers a valid linkset of the links of that level (with its anchor), or an HTML
  page for browsers.
- **Request paths** (2.4.1; URI Syntax 4.9, 4.10): checked by the GS1 Barcode Syntax Engine's own Digital
  Link parser (`callGS1encoder.js` accepts a URI): qualifiers out of order, data attributes or unknown AIs
  in the path and qualifiers without a value answer 400 instead of being redirected.
- **Values with `/`** (URI Syntax 4.2): the proxy passes the raw request URI (`$request_uri`, with an
  `upstream` block) and the resolver reads the raw URI, so `%2F` stays inside its value (was 400).
- **Query string** (2.12): passed on exactly as sent (the `;` delimiter became `%3B`, a key without a
  value gained `=`), and always: the per-target option is gone from the portal and the spreadsheets (owner's
  decision; release 1.2.0 of the standard removed it), `"fwqs": false` in older records is ignored and no
  longer published. Spreadsheets with the old Forward column are still read; the column is ignored.
- **Errors**: a single path segment that is not a compressed Digital Link answers 400 (was 500).
- **HTML** (2.10): the linkset page embeds the linkset as JSON-LD; a request without an `Accept` header
  gets HTML.
- **Description file** (3): no internal `_id`; `termsOfUse` only from the new optional `RESOLVER_TERMS_URL`
  (it pointed to a GS1 page for every installation).
- Tests: `test_resolver.py` 170 checks, including examples 5 to 13 of the standard and the real engine's
  400s; `test_home.py` checks `%2F` and `;` through nginx; `test_sheet.py` and the e2e test follow the
  removal of the option.

### Registration model of GS1-Conformant Resolver 2.5.9 (backlog items 1.2 and 1.3)
Conformance review findings F1, F2, F4 and F11; design chosen by the owner from mock-ups (approach C).

- **Serial numbers and their batch (rule 2).** With a serial number (AI 21), the variant (22) and batch
  (10) of a GTIN or ITIP are no longer part of the registration: the record is the serial number's, and the
  variant and batch are kept with it as `informativeQualifiers` — stored in the resolver's document,
  returned by the data entry API, searchable, filterable, exported and printed in the QR code, but never
  used by the resolver to choose a record and never in the public linkset. The editor keeps the fields
  where they were, marks them *informative* when a serial number is typed and says in plain words what the
  record applies to (*This record applies to*). Opening a serial number without its batch fills in the
  stored one; a different batch typed is pointed out and replaces it on saving. Spreadsheets keep writing
  `(22)V1(10)B42(21)S1`; an import that changes a serial number's batch shows the previous one.
- **Data entry API (deliberate change to official code).** `POST /new` and `PUT` refuse qualifiers a key
  does not take (URI Syntax 1.7, 4.9), AI 415 without AI 8020, AI 235 with other qualifiers (rule 1) and
  AI 22 or AI 10 with AI 21 (rule 2), with a 400 naming the problem (and the item, for a list). Values are
  not checked, so templates such as `{lotnumber}` keep working. New optional field `informativeQualifiers`
  in the Swagger model.
- **Resolver.** When a serial-number record and a batch or variant record both apply, the serial number's
  answers (rule 4 lists 01+21 before 01+22+10); before, the record with more qualifiers won, so a batch
  record could answer a request for a registered serial number.
- **A default link above every record.** Saving a batch, serial number or extension of a key that has no
  record of its own (except AI 415, which cannot exist without AI 8020) asks whether to create that record
  too: with the same targets (recommended, preselected), with another target, or not. The record list has
  a *Status* filter (no record of the key; serial numbers registered with their batch before rule 2), an
  alert with *Show only these* and a badge on each record concerned. The import preview lists the keys it
  would leave without a record of their own and, ticked by default, creates them with the targets of each
  key's first row.
- **Editor.** *Copy targets from…* adds the targets of any record to the form or replaces them; *Open
  record* asks before discarding unsaved changes, also after the key or qualifiers were changed.
- Records that break rule 2 and were made before it are only flagged, not changed: on staging there were
  none (checked on 1 October 2026).
- Tests: `dev-tests/portal/test_registration.py` (new); `test_data_entry_api.py`, `test_resolver.py` and
  the portal end-to-end test extended; the mock data entry API keeps informative qualifiers and enforces
  rule 2.

### Conformance review
- `Documentation/conformance-review.md` and `Documentation/pt-BR/revisao-de-conformidade.md`: clause-by-clause
  review of the branch against GS1 Digital Link URI Syntax 1.7 and GS1-Conformant Resolver 1.2.1, with the
  findings, the evidence behind each, the backlog items that address them and candidate errata. No code change.

### Home page and record list: texts cover every GS1 key
- The portal card of the home page and the lede of *Registered records* no longer speak of GTINs and
  batches only: the portal registers every primary key and key qualifier.

### Documentation in Brazilian Portuguese
- `Documentation/pt-BR/`: overview with installation, configuration and operation (`README.md`), portal
  user guide (`guia-do-portal.md`), features (`funcionalidades.md`), history (`historico.md`) and
  developer guide (`guia-do-desenvolvedor.md`), with screenshots of the portal and the home page in
  Portuguese (`Documentation/images/guide/pt-BR/`). The English documents and the README link to them.
- `dev-tests/docs/screenshots.py` produces the user guide images in both languages from one function.
- The guides now say that the targets are checked after each save, as the editor does.

### Documentation
- New documents: a portal user guide with screenshots (`Documentation/portal-user-guide.md`), the list of
  every feature with the commit that introduced it (`features.md`), the history of the project across its
  working sessions (`history.md`), a developer guide to the source code, the portal API and data files
  (`developer-guide.md`), and an index (`Documentation/README.md`). The README links to all of them.
- Docstrings for every function written for the fork and a map of `app.js`'s sections; no behaviour change.
- `dev-tests/docs/screenshots.py` also produces the user guide's images (`Documentation/images/guide/`);
  the example data gained the product and batch records of the infusion pump, so the README screenshots of
  the editor, the attributes panel and the record list show the list of other records.

### Portal: one other record in the singular
- "This identifier has one other record, listed below." instead of "1 other records".

### Portal: record list filters by key type and key qualifier; code search
- Two filters on *Registered records*: primary key type (GTIN, SSCC, GLN…) and key qualifier (variant,
  batch/lot, serial…, "None" for the whole key, "Others" for qualifier sets made elsewhere). They list only
  what the records contain, with counts, follow the language and keep the choice when the list reloads; the
  qualifier filter follows the key type. A button clears the search and every filter.
- A GS1 Digital Link URI or an element string with brackets in the search box finds the exact record of
  that code (marked "Exact"), the more general records that apply to it and the more specific ones, and
  says which AIs it ignored (data attributes are never stored). GTIN-8/12/13 are completed to 14 digits.
- "No record matches the search and filters." replaces "No record matches the search.".
- Everything happens in the browser on the list already sent by `GET /portal/api/records`; no API change.
- Tests: filters, counts, language, clearing, Digital Link and element string searches.

### Portal: attribute list fixes
- The list of data attributes showed the GS1 data titles only, in any language; it now shows the same
  names as the field once chosen: "(17) Data de validade (USE BY or EXPIRY)" in Portuguese.
- Searching the list by name ("validade") no longer drops the attribute already chosen: leaving the field
  (Escape or a click elsewhere) without picking another brings it back. A number typed still chooses, and
  emptying the field clears the choice.

### Portal: other records of the same key; data attribute fixes; names in Portuguese
- Under *Open record*, a list of the other records of the key (product, batches, serials, variants): what
  each applies to, description, links, last change; search, filter by key qualifier, five rows in view with
  scrolling, and *Open*, which asks for confirmation when the record being edited has unsaved changes.
  `GET /portal/api/record` returns description, links and last change in `otherEntries`.
- Fix: a decimal family chosen without a value (e.g. (392n)) was refused as "not a data attribute"; it now
  asks for the value.
- The engine's association refusals get messages of their own in both languages, naming the AIs as chosen:
  "(392n) also needs one of: (30) …; (31nn) …" (a price needs a quantity or measure), and invalid pairs.
- The line showing how a converted attribute went into the URI says how many decimal places were used,
  and stands out from the format hint.
- Data attributes named in Portuguese, with the GS1 data title in brackets: "(392n) Preço de item de medida
  variável (PRICE)" (216 names); English keeps the data titles.
- Tests: the list of other records (five rows, search, filter, confirmation), the fixes and the names.

### Portal: decimal families of data attributes, no limit of 10 attributes
- Measures and amounts whose fourth digit is the number of decimal places are offered as families — (310n)
  NET WEIGHT (kg), (392n) PRICE, 59 in all — and take the number as people write it, with a comma or a point:
  `123,45` becomes `3102=012345`. A member typed by number keeps its decimals (`3103` with `1,5` →
  `3103=001500`), and digits without a separator keep the GS1 meaning. New messages for two separators, too
  many decimals, too many digits, not a number. The editor shows how each converted attribute went into the
  URI. The list of attributes goes from 525 to 216 entries.
- No limit of 10 attributes: with the QR version and level configurable, the label itself says when the
  content does not fit. A ceiling of 100 per request remains, against misuse.
- New wording of the note in the attributes editor.

### Portal: label block under the form
- The label block (QR code, options, data attributes, link) sits under the form at every width, with the
  code and its buttons on the left, kept in view, and the options on the right; one column on phones. The
  side panel had become too narrow for the options and attributes (mock-ups A and B compared). The full HRI
  option is labelled "Full (every element)".
- Tests: layout at 1024, 1360 and 1920 px and on a phone.

### Portal: label options, attribute editor, show password
- Sign-in and password change: an eye button shows or hides the password being typed.
- QR code label options: human readable text in full, for the key only, or none (was on/off); QR version
  (*Automatic*, the default, or 1 to 40) and error correction level (L, **M** by default, Q, H). **Change:**
  the level is now exactly the one chosen; before, the QR library raised M to Q or H when the version had
  room to spare, so some labels drawn with the defaults now have the same size but a lower level than before. The version, size and level used are shown
  under the image (headers `X-QR-Version`, `X-QR-Modules`, `X-QR-Level`).
- When the content does not fit a chosen version, an explanation (version needed, level that would fit,
  shorter content) replaces the image and nothing can be downloaded (`qr.tooSmall`, `qr.tooLong`).
- Data attributes: a combo box replaces the browser's suggestion list, which could not be reopened without
  erasing the text and did not work on phones; most used attributes first; the record's own key and
  qualifiers left out; ↑ ↓ to order the attributes; day 00 in dates refused, with the first and last day of
  the month suggested (`attr.dayZero`); larger, darker helper text.
- Documentation: which AIs the grammar of §4.10 allows (530, 525 known to the engine) and why the list
  includes primary keys.
- Tests: label options, forced versions and day 00 in `test_data_attributes.py` (59 checks); password
  button, combo box (mouse, keyboard and touch on a 390 px phone), order, day 00, QR options and layout at
  1024 and 1360 px in the portal end-to-end test, which now prints JavaScript errors of the page.

### Portal: GS1 Digital Link data attributes
- QR codes can carry data attributes (URI Syntax 1.7, §4.10) — expiry date, net weight, price and every
  other AI the standard allows — in the query string of the Digital Link. *Include data attributes*
  below the QR code opens an editor of up to 10 attributes (AI by number or name with its GS1 data title,
  value with its format explained); the link preview, QR image, test and copy buttons and downloads use
  them once they are valid. They are not stored and are cleared when another record is opened.
- Validation by the GS1 Barcode Syntax Engine itself (formats, check digits, dates, code lists, invalid
  pairs and mandatory associations of the General Specifications §4.13), release 1.4.1 as used by the
  resolver: `portal/tools/build-syntax-engine.sh` builds its native library, GS1's Python binding and the
  Syntax Dictionary in a separate stage of the portal image (`GS1_SYNTAX_ENGINE_DIR`); `portal/syntax.py`
  runs it in the portal process. Without the engine the option is not offered.
- A qualifier of the record's key (e.g. batch/lot of a GTIN) is refused as an attribute: it would go in the
  path and the code would point at another record.
- API: `POST /portal/api/digital-link`; `GET /portal/api/qrcode` accepts `attr=AI:value`; `GET
  /portal/api/config` lists the attributes (`dataAttributes`). The label's HRI adds one line per attribute.
- Tests: `dev-tests/portal/test_data_attributes.py` (42 checks); data attribute steps in the portal
  end-to-end test; the resolver passes attributes on unchanged (`dev-tests/resolver/test_resolver.py`).
  Documentation: section "GS1 Digital Link data attributes"; README screenshot `portal-attributes.png`.

### Home page: operator linked
- The operator's name in the home page footer links to the operator's website, as on the resolver's
  pages. The home page reads it from the resolver description file, which now publishes
  `RESOLVER_ORG_URL` as `contact.hasURL` (a vCard property; the file still validates against the
  official schema). Only `http`/`https` addresses become links; the link is marked as external like the
  other external links of the page.
- Tests: link, plain text without `hasURL` and with `javascript:` or `ftp:` addresses in
  `dev-tests/home/test_home.py`; `hasURL` in `dev-tests/resolver/test_resolver.py`.

### Resolver: description file schema, credits
- The resolver description file is tested against a copy of the official schema
  (`dev-tests/resolver/description-file-schema.json`, version 1.2.0), and the footer of the resolver's
  pages against the operator configured in `RESOLVER_ORG_NAME` (no organisation is named in the code).
- README: "Extensions in this fork" line removed from the credits; the link checker's "soft 404" example
  no longer names an organisation.

### Documentation: every key and qualifier
- `Documentation/extensions/README.md` no longer describes the portal as GTIN-only: the API behaviours
  the portal works around, the record list (search by key name and qualifier value, link problems filter,
  which records are not opened), the spreadsheet layout (Key, Identifier and Qualifiers columns, with an
  example checked through the import preview), what each action does on the API (`/api/{AI}/{value}`,
  records, export and import), the QR code HRI (one line per element string) and the linkset page levels.

### Resolver: linkset page
- The HTML linkset page named every level "(domain) 01" instead of "Product (every unit)", "Batch/lot …":
  linkset anchors are absolute URIs and the level name read the whole URI as a path. Test added in
  `dev-tests/resolver/test_resolver.py`.
- Only `http` and `https` targets are links on the HTML linkset and 404 pages; a `javascript:` or
  `data:` href stored through the data entry API (which accepts any href) is listed without a link, so it
  cannot run in the resolver's origin when clicked. Tests added in `dev-tests/resolver/test_resolver.py`.

### Installer: passwords with special characters
- A first-user password with a single quote is refused (it ended the single-quoted value in `.env`); any
  other character, `$`, `\`, `"` and spaces included, is kept literally. Passwords typed interactively
  keep leading and trailing spaces (`IFS= read`).
- Tests: single-quoted password refused interactively and non-interactively in `test_install.sh`.

### Portal: special characters
- Keys, qualifiers, language tags and user prefixes accept ASCII digits only: full-width, Arabic-Indic and
  other scripts' digits were accepted and stored, and a superscript `²` in a numeric key failed with an
  internal error (HTTP 500).
- Invisible characters from copied text (zero-width space and joiners, word joiner, BOM, soft hyphen,
  direction marks) are removed from keys and qualifiers, in the editor and on the server.
- Descriptions and titles stored in Unicode normal form C, with line breaks, tabs and control characters
  as one space.
- Target addresses with spaces, line breaks, tabs, invisible characters or a backslash are refused with
  their own message (`link.urlChars`); a line break made the resolver answer 500 for that link type.
- XLSX exports write every text as text: a description starting with `=` was written as a formula and
  came back empty on import. CSV exports (records and audit trail) prefix cells starting with `=`, `+`,
  `-`, `@`, tab or carriage return with an apostrophe; imports remove it.
- CSV and text imports read UTF-16 with BOM (Excel's "Unicode text").
- User names typed at failed sign-ins: unprintable characters written as `?` and cut at 64 characters in
  the log and the audit trail.
- Documentation: section "Special characters" in `Documentation/extensions/README.md`.
- Tests: `dev-tests/portal/test_special_chars.py` (57 checks); invisible and full-width digits in the
  portal end-to-end test.

### Portal: import limits per format
- Limits per accepted format in `sheet.FORMATS` (`xlsx`: `.xlsx`; `csv`: `.csv`, `.txt`): 5 000 data rows
  and 700 KB each, sent to the browser in `GET /portal/api/config` (`importLimits`), listed in the import
  dialog in the user's language and checked by the browser for the file's format before sending. Error
  messages name the limit of the format. The file picker also offers `.txt`, which the server already read.
- A CSV cell above 128 KB (the `csv` module's field limit) is reported as an unreadable file instead of
  failing with an internal error.
- README: title "GS1 Digital Link Resolver CE — Expansion Pack"; table of import limits with measured
  sizes (5 000 rows: 200–290 KB in XLSX, 900–1 800 KB in CSV).
- Tests: limits per format in `test_sheet.py`; limits in the dialog (both languages) and a refused file
  in the portal end-to-end test.

### Portal: adjustments
- GS1® branding of the QR code label removed (option, artwork files and `brand` parameter); labels keep
  the dimensions of the *QR Codes powered by GS1* guidelines and the optional HRI. Label files are named
  after the key and qualifiers.
- Identifier type menu: name of AI 415 ("Invoicing party (GLN)") and its hints; qualifier 235 labelled
  TPX (its GS1 data title), UPUI remaining the name of the GTIN + 235 path.
- README screenshots without the GS1 logo; README wording of the portal's purpose.

### Portal: governance
- Roles administrator, editor and reader, checked on every call; interface adapted to the role (readers
  see records read-only).
- GS1 Company Prefixes per user: records, lists, exports, imports, labels, history and link checks limited
  to the user's prefixes.
- User administration screen: create users with a temporary password (changed at the first sign-in),
  change role and prefixes, reset passwords, disable, enable, remove; last administrator and self-lockout
  protected. `create_user.py` accepts `--role` and `--prefixes`.
- History of every record with the content of each version and *Restore this version*.
- Audit trail (`journal.jsonl`) with filters by user, period and identifier, and CSV export.
- Existing users (file without roles) become administrators.
- Tests: `dev-tests/portal/test_governance.py` (35 checks); history, user administration, reader,
  temporary password and audit trail in the portal end-to-end test.

### Documentation
- New top-level README for the fork: the original project, what the fork adds, architecture (Mermaid),
  the portal with screenshots, GS1 Digital Link coverage, API reference (resolver, data entry, portal),
  system requirements, installation with the Ubuntu script and by hand, configuration, operation,
  tests, repository layout, licence and credits. The official README is kept unchanged in
  `Documentation/upstream-README.md`; screenshots in `Documentation/images/` come from
  `dev-tests/docs/screenshots.py`.

### Portal: key qualifiers (URI Syntax 1.7, sections 4.4, 4.6, 4.9)
- Every key qualifier: 22, 10, 21 (GTIN; 10 and 21 for ITIP), 235 (UPUI), 8011 (CPID), 254 and 7040
  (GLN 414: FID), 8020 (required for 415, now supported), 7040 (417: EOID; 8004: MID), 8019 (GSRN).
  `gs1.KEY_SHAPES` describes which qualifiers go together, in path order, and which are required;
  formats of section 4.6. ITIP is offered without 22: the GS1 Syntax Engine refuses 22 without 01.
- Editor: one field per qualifier of the chosen key (optional/required, format note), live checks of
  formats and combinations; preview, QR code and HRI with every qualifier.
- Records carry a qualifier set instead of a batch: API `qualifiers` ({"10": "L1"} or "/10/L1/21/S1";
  `lot` still accepted); record metadata keys unchanged for batches; list, search, link checker and
  deletion work with any qualifier set.
- Spreadsheets: *Qualifiers* column ("(22)V1(10)L1(21)S1" or "/10/L1"); the older *Batch/lot* column
  still imports.
- Resolver: canonical qualifier order includes 8011, 8020 and 8019; HTML pages label records of any key.
- Tests: qualifier cases compared with the GS1 Syntax Engine (`test_keys.py`); walk-up through
  variant + batch and resolution of qualified records of every key (`test_resolver.py`); qualifiers in
  the portal end-to-end test (order, UPUI exclusion, 415 + 8020, CPID serial format) and the spreadsheet
  test.

### Portal: every primary identification key (URI Syntax 1.7, section 4.3)
- Editor, record list, spreadsheets, labels and link checker work with GTIN, ITIP, GMN, CPID, GLN (414,
  417), GSRN (8017, 8018), GCN, SSCC, GDTI, GINC, GSIN, GRAI and GIAI; step 1 has an identifier type
  selector with the label, hint, keyboard and live checks of each key. AI 415 waits for its required
  key qualifier 8020.
- `portal/gs1.py`: registry of primary keys with the Syntax Engine's rules (check digits, GMN
  check-character pair, GS1 Company Prefix, ITIP piece/total, GRAI filler zero); records addressed by
  anchor (`/AI/value`); API accepts `key` + `value` (and `gtin` from older clients).
- Record metadata keys unchanged for GTINs (`<GTIN-14>`, `<GTIN-14>/10/<lot>`); `<AI>/<value>` for the
  others.
- Spreadsheets: *Key (AI)* and *Identifier* columns plus a *Keys* reference sheet; older files with a
  *GTIN* column import unchanged.
- Wording made key-neutral where it is shown for every key (description, previews, messages).
- Tests: `dev-tests/portal/test_keys.py` (every key, compared with the GS1 Barcode Syntax Engine when
  `GS1_SYNTAX_ENGINE` is set); the resolver test authors and resolves one record per key (with the real
  engine when available); SSCC and GLN in the portal end-to-end test; key columns in the spreadsheet test.

### Portal: link checker
- Editor: targets checked after each save and on demand (*Check targets*); a note under each target.
- Record list: *Check links* checks every target in the background with progress, marks records with
  problems, filter *Only with problems*; the latest result is shown when the list opens.
- Import preview: optional check of the addresses of the records to be written (warnings only).
- `portal/linkcheck.py`: HEAD (GET fallback), redirects followed one by one to detect HTTPS → HTTP,
  401/403/429 reported as "blocked", 8 s timeout, 10-minute cache, 8 parallel checks; private, loopback,
  link-local and other non-global addresses refused at every hop (no probing of the internal network).
- Tests: `dev-tests/portal/test_linkcheck.py` (local HTTP server); editor, list and import checks in the
  portal end-to-end test (network replaced by a stand-in).

### Fixes from the first real import (records created by other tools)
- Link languages: any well-formed BCP 47 tag is accepted and normalised (`en-us` → `en-US`), in the
  editor and in imports; before, only the eight languages of the editor's menu were, so records created
  through the API (e.g. `vi`, `en-US`, `en-GB`) could be exported but neither re-imported nor saved.
- Batch/lot values the portal cannot manage (templates such as `{lotnumber}`, characters outside its
  subset) make a record "other": listed, not opened, not exported; an import that contains one explains
  it instead of reporting an invalid lot.
- The import preview reports every wrong row of a record (link type, URL, language) at once, instead of
  the first problem only.

### Portal: spreadsheet import and export
- Export of every editable record as XLSX (links sheet with the headers in the user's language, GTIN as
  text, plus link type and language reference sheets) or CSV (`;`, UTF-8 with BOM).
- Import of XLSX or CSV in two steps: a preview that validates every record with the editor's rules and
  classifies it as new, changed, unchanged or with errors (row numbers and reasons), then, after
  confirmation, a background import with progress. Records not in the file are never deleted.
- Data entry API: `GET /api/summary?links=true` includes each record's links (one request for exports
  and previews).
- `portal/sheet.py` (openpyxl); portal request limit 1 MB (proxy `client_max_body_size 1m` on `/portal/`).
- Tests: `dev-tests/portal/test_sheet.py` (parsing, Excel quirks, round trips); export → edit → import in
  the portal end-to-end test.

### Data entry API: consistent token protection
- `GET /api/index` now requires the bearer token like every other data entry operation (401 without
  it, 403 with a wrong one). It was public and listed every registered identifier, so anyone could
  enumerate the catalogue. Clients that call it must send `Authorization: Bearer <SESSION_TOKEN>`.
- The Swagger description declares the `BearerAuth` scheme on every protected operation. Before, only
  `POST /new` did, so the "Authorize" button of `/api/docs` sent the token with that operation alone
  and "Try it out" on GET/PUT/DELETE returned 401. `/api/heartbeat` stays public.
- `dev-tests/resolver/test_data_entry_api.py`: token checks on every operation and the Swagger
  declarations (fails on the official code on exactly these points).

### Portal: record list
- New view "Registered records" (`/portal/#records`, from the user menu or the link under the title):
  every product and batch on the resolver with description, GTIN, scope, number of links and last
  change (date and user); search by GTIN (with or without leading zeros), description or batch,
  ignoring case and accents; filter by who changed it; most recent first; opens a record in the editor;
  cards on narrow screens; browser back/forward move between list and editor.
- Data entry API: new `GET /api/summary` (bearer token) returning one line per record, so the list
  needs one request instead of one per GTIN.
- Portal metadata `records-meta.json` (in the portal's configuration volume, included in the daily
  backup): who created and last changed each record through the portal, and when. Records created or
  changed elsewhere show "no history".

### Navigation
- The GS1 logo on the portal (sign-in and main page) and on the resolver's HTML pages now links to the
  home page `/`, with a translated tooltip; the portal's user menu has a "Home page" item. Links are
  root-relative, so they work on any domain.

### Fixes found on the first real run of the installer
- The front-end proxy answered 502 after Compose recreated the services behind it (nginx resolves
  `web-service`, `data-entry-service` and `portal-service` once, at start-up, and the recreated
  containers came back with new addresses). `docker-compose.yml` now declares those dependencies with
  `restart: true`, so Compose restarts the proxy whenever it updates one of them; the installer also
  restarts the proxy once if the health check still fails after 30 s. The same problem affects the
  official repository whenever `web-service` or `data-entry-service` is recreated alone.
- The installer's `.env.bak-<date>` now keeps the owner of `.env` (it was root-only).

### Installer
- `scripts/install.sh`: interactive (or `--non-interactive`) installation and update on Ubuntu Server
  22.04 / 24.04 — Docker Engine + Compose from Docker's repository, generated secrets in `.env` (600),
  host nginx with Let's Encrypt, an existing certificate or an external proxy, health wait, first portal
  user with its password removed from `.env` afterwards, daily backup cron, final checks. Idempotent:
  secrets, users, data and a certified nginx site are kept on re-runs; unmanaged `.env` settings are
  carried over.
- `scripts/templates/`: host nginx site templates (HTTP for Certbot, HTTPS with own certificate).
- `dev-tests/install/test_install.sh`: 50 checks in eight scenarios with stand-ins for system commands,
  real `docker compose config` and real `nginx -t`.


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

Installed on the staging resolver and reported working by the operator.

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
- `gs1resolver.json` with the real resolver root, the operator's contact, JSON-LD context location.
- Daily MongoDB backup script and cron entry.
