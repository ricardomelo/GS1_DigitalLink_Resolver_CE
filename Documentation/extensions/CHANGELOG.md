# Changelog

## Unreleased (branch gs1br/develop)

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

Installed on the GS1 Brasil staging resolver and reported working by the operator.

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
- `gs1resolver.json` with real resolver root, GS1 Brasil contact, JSON-LD context location.
- Daily MongoDB backup script and cron entry.
