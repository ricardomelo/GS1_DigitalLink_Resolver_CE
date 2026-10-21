# Features

Every feature of the GS1 Digital Link Resolver CE — Expansion Pack, grouped by component, with what it
does, the commit that introduced it (on branch `gs1br/develop`, oldest first in
[history.md](history.md)) and the development tests' checks that prove it: `program` names a test program, and the
words after it are found in the names of its checks, listed in the [inventory of features](test-inventory.md)
([ADR 0016](adr/0016-documentation-and-feature-inventory.md); `dev-tests/docs/test_docs.py` fails when a feature cites
no check). Features of the official GS1 Resolver CE v3 that the fork keeps unchanged are
listed at the end for completeness.

How to use the portal: [portal user guide](portal-user-guide.md). How each feature is built:
[developer guide](developer-guide.md). Design decisions and details:
[extensions documentation](extensions/README.md).

## Contents

- [Resolver (public resolution)](#resolver-public-resolution)
- [Data entry API](#data-entry-api)
- [Portal: access and accounts](#portal-access-and-accounts)
- [Portal: editor](#portal-editor)
- [Portal: identification keys and qualifiers](#portal-identification-keys-and-qualifiers)
- [Portal: QR code labels](#portal-qr-code-labels)
- [Portal: data attributes](#portal-data-attributes)
- [Portal: record list](#portal-record-list)
- [Portal: spreadsheets](#portal-spreadsheets)
- [Portal: link checker](#portal-link-checker)
- [Portal: governance](#portal-governance)
- [Tenant API](#tenant-api)
- [Request log and overview](#request-log-and-overview)
- [The item's page](#the-items-page)
- [Organisations' own domains](#organisations-own-domains)
- [Monitoring and alerts](#monitoring-and-alerts)
- [Portal: robustness and security](#portal-robustness-and-security)
- [Portal: languages and look](#portal-languages-and-look)
- [Home page and navigation](#home-page-and-navigation)
- [Configuration, installation and operation](#configuration-installation-and-operation)
- [Development tests and documentation](#development-tests-and-documentation)
- [Kept from the official project](#kept-from-the-official-project)

## Resolver (public resolution)

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Walk-up | A level without a record falls back to the next level: serial → batch → variant → key, instead of an error 500 | `766a652` | `resolver`: walk-up · `request_log`: walks up |
| Serial before batch | When a serial-number record and a batch or variant record both apply, the serial number's answers (GS1-Conformant Resolver 2.5.9, rule 4: 01+21 before 01+22+10) | `61babe1` | `resolver`: rule 4 |
| 404 for a missing link type | A record without the requested `linkType` answers 404, as GS1-Conformant Resolver 2.6.2 requires (was 200 with an error inside) | `766a652` | `resolver`: 404 /01/07898357410015?linkType=gs1:recallStatus · `request_log`: noLink |
| Trailing slash | `/10/123/` is treated as `/10/123` (was 400) | `766a652` | `gs1_suite`: trailingSlash pass |
| `linkType` forms | Accepts `x`, `gs1:x`, `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, case-insensitive; `defaultLink` redirects to the default target | `766a652` | `resolver`: linkType=instructions · `resolver`: linkType=https://gs1.org/voc/instructions |
| Conformant linkset | `?linkType=linkset` / `Accept: application/linkset+json` returns plain RFC 9264, valid against GS1's linkset schema; JSON-LD only on request; correct JSON-LD context `Link` header exposed to CORS | `766a652` | `resolver`: linkset valid · `resolver`: linkset context header |
| `gs1:` namespace | Link types in linksets and in the JSON-LD context written in `https://ref.gs1.org/voc/` (Resolver 2.14); stored documents unchanged | `bc573c4` | `resolver`: gs1 is https://ref.gs1.org/voc/ |
| GS1's test suite | Passes every test of GS1's resolver test suite on staging; the suite also runs in the development tests | `cc95d77` | `gs1_suite`: every test of the suite ran |
| Query string forwarding | The scan's query string (data attributes included) is passed on exactly as sent — `;` delimiter and keys without a value kept — always (`"fwqs": false` in older records ignored, Resolver 2.12); joined with `&` when the target already has a query | `766a652`, `4f81234` | `resolver`: query string is passed on |
| Default response | Without `linkType`, the default link, unless the request decides a language variant (Resolver 2.6.3, examples 5-7; was 300 for two languages without a match); several links of the default type published as `gs1:defaultLinkMulti` | `4f81234` | `resolver`: linkType=defaultLink |
| Choosing among links of one type | Media type, then language (q-values, `pt-BR` → `pt`), then context (examples 8-13); 300 answers a valid linkset of that level, or an HTML page | `4f81234` | `resolver`: choosing a link |
| Request paths checked by the engine | The GS1 Barcode Syntax Engine's Digital Link parser checks the path: qualifiers out of order, data attributes or unknown AIs in the path → 400 | `4f81234` | `resolver`: real syntax engine |
| Syntax check in the resolver's process | The engine's C library answers each check in a few microseconds (`gs1_syntax.py`: per-thread contexts, the last 20,000 answers kept), instead of a Node.js process per request (tens of ms of CPU); Node.js only when the library is missing | `653ffc6` | `resolver`: in the resolver's process |
| Values with `/` | `%2F` in a value stays in it: the proxy passes the raw request URI and the resolver decodes each segment on its own | `4f81234` | `resolver`: (%2F) finds its record · `domains_resolver`: %2F |
| EPC binary strings | `/eh…` and `/ex…` (an EPC read from an NFC or hybrid UHF/NFC tag) are decompressed and resolved as the equivalent GS1 Digital Link: every EPC scheme with a Digital Link, the `+` schemes with their +AIDC data and the `++` schemes (their hostname ignored); key qualifiers from the tag go to the path, data attributes to the query string passed on to the target; 400 when the string does not decode (Resolver 2.3, EPCB 1.0.0) | `51a0da8`, `895c4b1` | `epc_binary`: EPCB worked example · `epc_binary`: TDS annex E.3 · `resolver`: EPC binary string |
| HTML pages for browsers | Errors (400, 404, link type not available — listing the available links) and the linkset as gs1.org-style pages in pt-BR / en-GB, same HTTP status, language menu | `766a652` | `resolver`: HTML 404 |
| Level names on the linkset page | Each level named by its anchor: the key, variant, batch/lot, serial, GLN extension… | `b33def6` | `landing`: its level and the product's |
| Safe links on HTML pages | Only `http(s)` targets are links; `javascript:`, `data:` and others are listed without a link | `92bfb5d` | `resolver`: javascript: and data: targets listed without a link |
| Configurable description file | `/.well-known/gs1resolver` takes `resolverRoot` and `contact` (name, address, telephone, `hasURL`) from `.env`, and `termsOfUse` from `RESOLVER_TERMS_URL`; validated against a schema in the tests | `766a652`, `764e360`, `cc72145`, `4f81234` | `resolver`: description file |
| Operator footer | "GS1 Digital Link service operated by …" from `RESOLVER_ORG_NAME`, per installation | `766a652`, `764e360` | `resolver`: footer names the configured operator |

## Data entry API

| Feature | What it does | Since | Checks |
|---|---|---|---|
| `GET /api/summary[?links=true]` | One line per record (anchor, qualifiers, description, default link type, number of links, optionally the links): the portal reads every record in one call | `db56b22` | `mock_parity`: GET /summary with links · `data_entry_api`: summary |
| Token on `/api/index` | The official public `GET /api/index` (every identifier on the resolver) now requires the bearer token | `1941e75` | `data_entry_api`: GET /api/index without token |
| `BearerAuth` in Swagger | Every protected operation declares the bearer scheme, so **Authorize** in `/api/docs` works | `1941e75` | `data_entry_api`: BearerAuth |
| Registration rules | `POST /new` and `PUT` refuse qualifiers the key does not take, 415 without 8020, 235 with other qualifiers and 22 or 10 with 21 (GS1-Conformant Resolver 2.5.9, rules 1 and 2); a list is refused whole, naming the item | `61babe1` | `data_entry_api`: rule 2 |
| `informativeQualifiers` | A serial-number record of a GTIN or ITIP keeps the unit's variant and batch as information: stored, returned by `GET` and `/summary`, replaced by `PUT`; never used to choose a record, never in the public linkset | `61babe1` | `data_entry_api`: informative |
| Values checked | The GS1 Barcode Syntax Engine checks the values of every registration (templates left out) | `a1131bb` | `data_entry_api`: engine: |
| `POST /api/validate` | What `POST /new` would refuse, nothing stored; the portal asks it before rewriting a key's document | `8dbc85d` | `data_entry_api`: POST /validate |
| `gs1:defaultLink` links returned | A record's own links of type `gs1:defaultLink` (the item's page, explicit default links) are returned by `GET` and `/summary` and kept by `PUT` and `DELETE`; the official code dropped them | `cb67cf5` | `mock_parity`: returns a link of type gs1:defaultLink |

## Portal: access and accounts

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Sign-in page | Username and password, session cookie (HttpOnly, SameSite, Secure over HTTPS) | `126f507` | `portal_e2e`: sign-in · `mail`: sign-in page |
| Session limits | The session ends after 30 minutes without use and 12 hours after the sign-in (`PORTAL_SESSION_IDLE_MINUTES`, `PORTAL_SESSION_MAX_HOURS`); a dialog counts down the last two minutes and offers *Stay signed in*; typing, clicks and scrolling count as use; tabs share the session | `1a1ca59` | `session`: idle limit · `portal_config`: session defaults |
| Throttling | 5 failures → 15 minutes wait, per user name and per address | `126f507` | `store`: login_failures |
| Password change | Options dialog; current password required; at least 12 characters; other sessions signed out | `126f507` | `store`: new password · `governance`: temporary password |
| Session fingerprint | A password change or reset ends every other session of the account | `126f507` | `store`: fingerprint changes |
| Show-password button | An eye in every password field (sign-in, password change) | `1525f82` | `portal_e2e`: eye button to show the password |
| First user from `.env` | `PORTAL_ADMIN_USERNAME` / `PORTAL_ADMIN_PASSWORD` create the first administrator while there are no users | `126f507` | `portal_config`: first user created |
| Command-line users | `create_user.py`: create, set password, role, prefixes, remove | `126f507`, `71b15f2` | `tenants`: command line |
| Password recovery by e-mail | *Forgotten your password?* on the sign-in page (installations with e-mail): a single-use link (60 minutes) to the account's address, by user name or address; the same answer for every entry; limits per entry and per browser address ([ADR 0004](adr/0004-e-mail.md)) | `03c924b`, `fbe86f0` | `mail`: recovery · `mail_e2e`: recovery |
| Invitations | A user created with an address chooses their own password through a link (72 hours) instead of a temporary password; *Send the invitation again*; a reset by an administrator sends a link | `03c924b`, `fbe86f0` | `mail`: invitation · `mail_e2e`: invitation |
| Security notices | A message when the password or the e-mail address changes (to the old and the new address) and when the account is locked | `03c924b` | `mail`: security message |
| E-mail preferences | Options → E-mail: the language of the messages and the notices of finished imports and full link checks | `03c924b`, `fbe86f0` | `mail`: preferences |

## Portal: editor

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Three-step form | Identify → describe → targets, with live validation and the label alongside | `126f507` | `portal_e2e`: record created · `portal_e2e`: default link type = first target |
| Open record | Reads the record from the resolver; tells whether it exists and which other records the key has; locks steps 2 and 3 when the identifier changes afterwards | `126f507` | `portal_e2e`: opening from the list loads the record in the editor |
| Targets | Link type (29 GS1 link types with explanations), language, URL, title, default target, up to 20 per record (the per-target query-string option was removed in `db8e342`) | `126f507` | `portal_e2e`: another target needs an address · `portal_e2e`: default link type = first target |
| Every link type and language | Every stable link type of the GS1 Web Vocabulary (57 in 1.16, generated by `portal/tools/gen_link_types.py` and checked against the vocabulary), grouped and ordered by the key type; a target's language chosen from a list of every ISO 639-1 language and the usual regional tags, named in the user's language, the Latin alphabet's first, scrolled and filtered by what is typed (since `984f2ce`) | `1e40f8c` | `link_types` · `link_types_e2e` · `link_types_e2e`: filtered by what is typed |
| Shared default type | Explains and enforces that every record of a key shares the default link type | `126f507` | `registration`: default · `item_page`: its default type shared |
| Safe API sequence | POST appends, PUT merges, partial DELETE removes only the targets the user removed; deleting one record keeps the others of the key (restored on failure) | `126f507` | `fix_serials`: deleting a record of a key |
| Other records of the key | List under *Open record*: what each applies to, description, links, last change; search, qualifier filter, five rows in view, *Open* with unsaved-changes confirmation | `08570e4` | `portal_e2e`: other records |
| Informative batch and variant | With a serial number, the variant and batch fields of a GTIN or ITIP are marked *informative*: kept with the serial-number record, printed in the QR code, but not part of the registration (GS1-Conformant Resolver 2.5.9, rule 2); opening a serial number without them fills in the stored ones; a different typed value is pointed out | `83d1ba0` | `registration`: informative · `data_entry_api`: informative variant and batch |
| "This record applies to" | A card under the qualifiers says, in plain words, what the record applies to and where codes without a record of their own go | `83d1ba0` | `portal_e2e`: scope: |
| Record of the key when saving | Saving a batch, serial or extension of a key without a record of its own offers to create that record with the same targets (recommended), with another target, or not (GS1-Conformant Resolver 2.5.9) | `3a49ca9` | `registration`: saving with mode copy · `registration`: saving with mode target |
| Copy targets from… | Search any record and add its targets to the form or replace them | `3a49ca9` | `portal_e2e`: copy targets |
| Confirmation on *Open record* | Asks before discarding unsaved changes, also after the key or qualifiers changed | `3a49ca9` | `portal_e2e`: Open record asks before discarding |
| Singular wording | "This identifier has one other record" | `d11c369` | `portal_e2e`: other records listed under Open record |
| Read-only mode | Readers see every field disabled and a note | `71b15f2` | `portal_e2e`: reader: record opens read-only · `governance`: reader cannot save |
| Default titles in the link's language | A link without a title gets its type's title in Portuguese or English, as the link's language (GS1-Conformant Resolver 2.5.3) | `266dcf3` | `titles` · `link_types`: default titles in the link's language |

## Portal: identification keys and qualifiers

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Every primary key of URI Syntax 1.7 §4.3 | GTIN, ITIP, GMN, CPID, GLN (414, 415, 417), GSRN (8017, 8018), GCN, SSCC, GDTI, GINC, GSIN, GRAI, GIAI, each with its own label, hint and checks (check digit, GMN check-character pair, ITIP piece/total, GRAI filler zero…) | `e181ccc` | `keys` · `dictionary`: every primary key of the dictionary |
| Every key qualifier of §4.4/4.6/4.9 | 22, 10, 21, 235 (TPX), 8011, 254, 7040, 8020, 8019, with the combinations and order the standard allows and the required ones (8020 for 415) | `67d40bb` | `keys`: qualifier |
| Mirrors the Syntax Engine | Validation in Python and JavaScript compared with the GS1 Barcode Syntax Engine by the tests | `e181ccc`, `67d40bb` | `keys` · `dictionary` |
| Rules from the GS1 Barcode Syntax Dictionary | Keys, qualifiers, their order, lengths and formats, in the server and in the browser, built from the dictionary of the pinned engine release (`portal/gs1_dictionary.json`, generated) with the portal's few deliberate exceptions; a format the portal cannot check stops the build instead of being accepted ([ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md)) | `6f6ce19` | `dictionary` · `engine_messages` |
| GTIN convenience | 8, 12, 13 or 14 digits typed, stored as GTIN-14; restricted-circulation GTIN-13 (prefix 2) refused | `126f507` | `api`: a GTIN-13 is stored as GTIN-14 |

## Portal: QR code labels

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Live preview | QR code, coloured Digital Link and legend while typing; *Published* / *Not yet registered* | `126f507` | `portal_e2e`: SSCC accepted, preview uses /00/ |
| PNG and SVG | SVG in millimetres at X = 0.495 mm, 4X quiet zone, HRI 2.2 mm as outlines (no font needed); PNG for screens | `126f507` | `label`: SVG · `label`: PNG |
| No GS1 branding | Labels carry no GS1 artwork | `7e7a62a` | `portal_e2e`: no GS1 branding option · `portal_e2e`: without branding artwork |
| HRI modes | Full (each element on its own line), key only, none | `1525f82` | `data_attributes`: HRI |
| QR version | Automatic (smallest that fits) or 1–40 | `1525f82` | `data_attributes`: version |
| Error correction | L, M (default), Q, H, applied exactly as chosen | `1525f82` | `data_attributes`: level H |
| "Does not fit" panel | Explains the needed version or the fitting level instead of a broken image (422 `qr.tooSmall` / `qr.tooLong`) | `1525f82` | `data_attributes`: version too small |
| Label block layout | Under the form at every width: code and buttons on the left, options on the right; one column on phones | `1746f19` | `portal_e2e`: label |
| Try now, Copy link address | Opens or copies the Digital Link | `126f507` | `portal_e2e`: copy |
| RFID and NFC | For a serial number: its EPC (SGTIN-96 or SGTIN-198) in hexadecimal and as a tag URI, and the compressed link (`eh…`, `ex…`) for NFC tags; the company prefix's length from the organisation, the filter chosen | `e1b6917` | `epc_label`: the Tag Data Standard's example · `domains_e2e`: RFID/NFC |
| An EPC for every key | The same for every key the EPC Tag Data Standard encodes — SSCC, SGLN (the extension 0 without one), GRAI, GIAI, GSRN, GSRNP, GDTI, SGCN, CPI, ITIP — once the record holds what it needs, from the TDT artefacts; the record search finds each by its EPC ([ADR 0010](adr/0010-label-studio.md) §8) | `6c7c755` | `epc_label`: every key with an EPC · `epc_label`: search by that EPC · `domains_e2e`: GLN |
| Data Matrix and scanning environments | GS1 DataMatrix (element string) or Data Matrix (GS1 Digital Link URI) instead of the QR code; the module size by scanning environment (retail, healthcare, direct part marking) within the General Specifications' ranges; the SVG's HRI as editable text, an option ([ADR 0010 §7](adr/0010-label-studio.md)) | `7f9892e` | `datamatrix` · `datamatrix_e2e` |
| Label studio | Sizes 80–200 %, a vector PDF, an EAN-13/UPC-A/EAN-8/UPC-E beside the QR code for the transition to 2D, every format in one ZIP ([ADR 0010](adr/0010-label-studio.md)) | `d60421f` | `label` |

## Portal: data attributes

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Attributes in the QR code | Expiry, weight, price… (URI Syntax §4.10) added to the code drawn now; never stored; cleared when another record opens | `4b42c6f` | `data_attributes` |
| GS1 Barcode Syntax Engine | Validation by GS1's own C library and Python binding (built in a Docker stage), at the release every service uses; the option is hidden when the engine is absent | `4b42c6f`, `8e3d9c7` | `data_attributes`: engine |
| Combo box | Pick from *Most used* / *All attributes* or type a number or name; works on phones | `1525f82` | `portal_e2e`: attribute |
| Order | Up/down buttons | `1525f82` | `portal_e2e`: an attribute moved up |
| Day 00 refused | With the first/last day of the month suggested | `1525f82` | `data_attributes`: day 00 |
| Decimal families | (310n), (392n)… accept `123,45` or `123.45` and encode `3102=012345`; the URI line shows the decimals used | `e71384d` | `data_attributes`: decimal value |
| No limit of 10 | A ceiling of 100 per request; the QR code is the real limit | `e71384d` | `data_attributes`: technical ceiling |
| Localised messages | Association errors (`requires`, `pair`) in both languages; every other message of the engine (formats, check digits, dates, code lists: 94 messages and 117 linters' messages) too | `08570e4`, `e7c5a6d` | `engine_messages` |
| Portuguese AI names | 221 names (with (7041) and (8040)–(8043) since `e7c5a6d`), e.g. "(17) Data de validade (USE BY or EXPIRY)", in the field and in the list; searching the list keeps the chosen attribute | `08570e4`, `cf5ce10` | `dictionary`: named in Portuguese · `i18n`: the names of the AIs are Portuguese's own |

## Portal: record list

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Registered records | Every record the user may see, most recently changed first, with identifier, scope, links and last change | `db56b22` | `portal_e2e`: record list |
| Text search | Identifier (with or without leading zeros), key name, description, qualifier; accents and case ignored | `db56b22` | `portal_e2e`: search |
| Filter by author | *Changed by* | `db56b22` | `portal_e2e`: author |
| Filter by key type | *Identifier type*, with counts | `f4f3071` | `portal_e2e`: key type |
| Filter by qualifier | *Qualifier*: any qualifier, none, or sets made elsewhere; follows the key type | `f4f3071` | `portal_e2e`: qualifier |
| Code search | A pasted GS1 Digital Link or bracketed element string shows the exact record (marked), the more general and the more specific ones; ignored AIs named | `f4f3071` | `portal_e2e`: code |
| Clear search and filters | One button | `f4f3071` | `portal_e2e`: clear |
| Records made elsewhere | Listed (templates such as `{lotnumber}`), not opened | `db56b22`, `7339e3c` | `portal_e2e`: no history |
| Informative qualifiers in lists | Filters, text search and code search find a serial number by its informative batch or variant; the scope shows them | `83d1ba0` | `registration`: record list · `data_entry_api`: /summary lists the informative qualifiers |
| Status filter and alert | *Status*: records of keys without a record of their own (with an alert and *Show only these*) and serial numbers registered with their batch before rule 2; a badge on each | `3a49ca9` | `registration`: record list flags |
| Scanners and RFID readers in the search | Raw scan data (`]d2`, `]Q3`, `]C1`…, the group separator, AIs without brackets) read by the GS1 Barcode Syntax Engine; RFID EPCs (hexadecimal, `eh…`, `ex…`) read by the resolver; the line under the filters says how | `576b48a` | `scan_search`: read · `scan_search`: EPC read through the resolver |
| Filters in the address | The list's filters and search text kept in the address, for bookmarks and colleagues | `3df0c50` | `portal_e2e`: address |
| Fix serial numbers registered with their batch | Registered again as the serial number alone with the batch and variant as information (rule 2 of §2.5.9), one identifier or all at once | `8dbc85d` | `fix_serials` |

## Portal: spreadsheets

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Export | XLSX (with Link types, Keys and Languages sheets) or CSV, one row per target, headers in the user's language | `429dce7` | `sheet`: export · `exports` |
| Two-step import | Preview with New / Changed / Unchanged / With errors and every wrong row explained, then apply in the background with progress; run by the job worker, so it survives a restart of the portal and continues after a restart of the worker; *In the queue…* while it waits | `429dce7`, `7339e3c`, `a072e9d` | `portal_e2e`: import preview counts · `jobs`: preview: the import becomes a prepared job |
| Never deletes | Records not in the file stay | `429dce7` | `registration`: an import never deletes |
| Any BCP 47 language | `pt-BR`, `en-US`, `vi`, `und`… accepted and kept | `7339e3c` | `sheet`: BCP 47 |
| Limits per format | XLSX and CSV/TXT: 5,000 rows and 700 KB, shown in the dialog | `9d12f9d` | `sheet`: 700 KB |
| Excel-friendly | Windows-1252, UTF-8 and UTF-16 ("Unicode text") files; separator detected; scientific notation detected; formula protection on export | `429dce7`, `1b58bfd` | `special_chars`: Excel · `special_chars`: no cell starts with |
| Informative qualifiers in spreadsheets | `(10)B42(21)S1` is exported for a serial number with an informative batch and imported back the same way; a change of batch is shown in the preview | `83d1ba0` | `registration`: export · `registration`: import |
| Keys without a record of their own | The preview lists them and, ticked by default, creates each key's record with the targets of its first row | `3a49ca9` | `registration`: import |
| Export of the filtered records | With filters on, the exports hold only the records the list shows | `3df0c50` | `exports`: a filtered list's export |

## Portal: link checker

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Check targets (editor) | After each save and on demand; result under each target | `0da20ee` | `linkcheck` · `portal_e2e`: opening a record with problems checks its targets |
| Check links (every record) | Background job, run by the job worker; summary kept; badge per record; *Only with problems* | `0da20ee`, `a072e9d` | `portal_e2e`: check every record · `jobs`: link check |
| Import preview check | Optional, does not stop the import | `0da20ee` | `linkcheck` |
| SSRF guard | Only public addresses are contacted, at every redirect | `0da20ee` | `linkcheck`: internal address refused |
| Clear reasons | HTTP errors, blocked checks (401/403/429), unreachable, HTTPS downgrade, too many redirects, private address, invalid | `0da20ee` | `linkcheck` |

## Portal: governance

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Roles | Reader < editor < administrator, checked on every call | `71b15f2` | `governance`: reader · `governance`: editor |
| GS1 Company Prefixes per user | Users see and change only their prefixes' identifiers (after the indicator digit of GTIN-14/ITIP, the extension digit of SSCC, the filler zero of GRAI) | `71b15f2` | `governance`: prefix |
| Users screen | Create with a temporary password shown once, change role and prefixes, reset, disable, remove; at least one active administrator | `71b15f2` | `governance` · `portal_e2e`: users |
| Record history | Every version saved through the portal, with restore | `71b15f2` | `governance`: history |
| Audit trail | Sign-ins, changes, imports, exports, administration; filters; CSV | `71b15f2` | `governance`: audit · `store`: audit |
| Organisations (tenants) | An organisation owns GS1 Company Prefixes (one organisation per prefix, no overlaps); its records and users are its own; the operator owns whatever belongs to no organisation, and an installation without organisations works as before ([ADR 0002](adr/0002-tenants.md)) | `1590b7e`, `675b6ca` | `tenants` |
| Server administrator | The operator's administrators manage organisations and every user; an organisation's administrator only its users | `1590b7e`, `675b6ca` | `tenants`: server administrator |
| Support access | Read-only access of a server administrator to one organisation, with a reason recorded in its audit trail; a banner while it is open | `1590b7e`, `675b6ca` | `tenants`: support access |
| Audit trail per organisation | Each organisation sees its own trail; what the operator did to it is tagged; history and "changed by" per organisation | `1590b7e`, `675b6ca` | `tenants`: audit |
| E-mail per user | Optional, unique; where invitations, recovery links and notices go | `1590b7e`, `675b6ca`, `03c924b` | `tenants`: e-mail |
| API keys | Administrators create keys for their organisation's systems (the operator's records for a server administrator): scopes, optional prefixes, validity; shown once, stored as a hash, revocable; last use; e-mail when created and before expiry ([ADR 0005](adr/0005-tenant-api.md)) | `bb0b496`, `c469f29` | `api`: key · `api_e2e` |
| Journal | One event per document in the portal's database, included in the backup; kept by age per category (sign-ins 180 days, record changes and administration for ever by default; `PORTAL_JOURNAL_*_DAYS`) | `71b15f2`, `d783f3d` | `store`: journal |
| Single sign-on | Each organisation's OpenID Connect provider (Entra ID, Google, Okta, Keycloak…) for its users' sign-in, chosen by the e-mail's domain; accounts matched by e-mail, never created; password sign-in off per organisation, never for server administrators ([ADR 0012](adr/0012-single-sign-on.md)) | `732b5c0` | `sso` · `sso_e2e` |
| Export limits per role | The most rows one export of a role may hold, or none; refusals journalled, buttons hidden | `732b5c0` | `exports`: a reader (limit 0) may not export |
| GS1's GCP length table | Uploaded by server administrators (checked, swapped in at once, older lists confirmed); the GS1 Company Prefix of a key under it in the editor, the EPC's partition, warnings on organisations' prefixes ([ADR 0015](adr/0015-gcp-length-table.md)) | `5dd6bfe` | `gcp` · `gcp_e2e` |
| Export limits in the portal | An installation maximum set by server administrators; each organisation's limits for readers, editors and API keys on its page (*Exports*), within it; the tenant API's listing truncated at the keys' limit; `PORTAL_EXPORT_LIMITS` read once ([ADR 0012](adr/0012-single-sign-on.md) §8) | `f0c1d4f` | `exports`: maximum · `admin_nav_e2e`: export |
| Sidebar and phone width | The screens of the user menu in a foldable left sidebar on wide screens; every screen fits a phone ([ADR 0013](adr/0013-administration-and-navigation.md)) | `a3b3cea` | `admin_nav_e2e`: sidebar · `admin_nav_e2e`: 390 pixels |
| An organisation's page | Prefixes, users, domains, brands, single sign-on, API keys and alerts of an organisation in one place | `a3b3cea` | `admin_nav`: organisation's page · `admin_nav_e2e`: organisation's page |
| Prefixes as rows, picked | Organisations' prefixes one per row (*Add GCP*, remove, checked as typed, a refused row marked); users' prefixes picked from the organisation's own | `a3b3cea` | `admin_nav_e2e`: prefixes as rows · `admin_nav_e2e`: picked |
| The portal's own dialogs | Confirmations in the portal's style instead of the browser's | `a3b3cea` | `admin_nav_e2e`: the portal's own dialog |
| Overview by organisation | Server administrators choose an organisation (or the operator) on the overview; *Operation* is theirs only | `a3b3cea` | `admin_nav`: a server administrator's overview · `admin_nav_e2e`: the overview |

## Tenant API

| Feature | What it does | Since | Checks |
|---|---|---|---|
| `/portal/api/v1` | Records listed in pages, read, created or replaced, deleted; labels (SVG, PNG); who am I — for an organisation's own systems, with an API key, under every rule of the portal ([ADR 0005](adr/0005-tenant-api.md)) | `bb0b496` | `api` · `api_e2e` |
| OpenAPI description | `GET /portal/api/v1/openapi.json`, OpenAPI 3.1, public, checked against the routes by the tests | `bb0b496` | `api`: OpenAPI |
| Request limit | 120 requests per key and minute by default (`PORTAL_API_RATE_PER_MINUTE`), shared by every replica; 429 with `Retry-After` | `bb0b496` | `api`: limit |

## Request log and overview

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Log of resolver requests | Each scan the resolver answers is recorded: code and qualifiers, outcome (redirected, code not registered, no link of that type, choice, linkset, invalid), the level that answered, the target's host, the time taken, language, device class, referrer's host; never the client's address, the User-Agent, serial numbers or data attribute values; written in the background, never slowing a scan; kept `RESOLVER_LOG_DAYS` (90) ([ADR 0006](adr/0006-resolver-request-log.md)) | `d633fcb` | `request_log` |
| Daily counts | Requests per key and day, with outcomes, devices, languages, link types and times, counted hourly by the worker in the installation's time zone, kept 800 days | `d633fcb` | `requestlog`: per day |
| Map of requests | A world map of the requests the filters select on the Requests screen: countries shaded by their requests, cities as circles at the GeoIP database's point rounded to 0.1°, zoom, a click on a country listing its regions and cities; the region beside the city in the list, the position in the CSV ([ADR 0006 §10](adr/0006-resolver-request-log.md)) | `a287a64` | `request_log`: city's position · `requestlog`: the map · `requests_e2e`: map |
| Browser, location, retention | The browser family and the approximate location (country, region, city from a GeoIP database updated monthly; the address forgotten) of each request, on the Requests screen with a Google Maps link, filters and in the overview; how long requests are kept set in the portal for the installation and per organisation, with the space used ([ADR 0006 §8](adr/0006-resolver-request-log.md)) | `b768463` | `request_log`: browser · `requestlog`: retention · `requests_e2e`: browser |
| Space limit of the request log | The most space the log may use on disk, set by server administrators in megabytes; beyond it the hourly housekeeping deletes the oldest requests down to 95 %; alerts from 80 % of it and at each further 5 % ([ADR 0006 §9](adr/0006-resolver-request-log.md)) | `2425487` | `requestlog`: space limit · `requestlog`: beyond it: the oldest deleted · `monitor`: the space: an alert at 80 % · `requests_e2e`: the most space on disk |
| Requests screen | Every user: the last 30 days as bars, the latest requests of the codes in his reach with filters and a CSV export; the server administrator sees the whole installation with the organisation of each request | `7b8967a` | `requests_e2e` |
| Tenant API calls | Each call of `/portal/api/v1` recorded (key, organisation, operation, status, time) and listed for administrators | `d633fcb`, `7b8967a` | `requestlog`: API · `requests_e2e`: API |
| Overview after sign-in | Indicators of the user's scope for 7, 30 or 90 days against the period before: usage, resolution quality with the scanned codes nobody registered first, record quality, operation and governance; Excel and CSV exports ([ADR 0007](adr/0007-overview-indicators.md)) | `16ceb9f` | `overview` · `overview_e2e` |
| Statistics through the tenant API | `GET /portal/api/v1/stats` with the scope `stats:read`: the overview's usage, quality and records for an organisation's own systems | `16ceb9f` | `overview`: tenant API: /stats |

## The item's page

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Item page | A page of all the links of an item as the default target of its code, made by the resolver for phones: the brand of the prefix (logo uploaded in the portal, colours), an icon per link type, the visitor's language first, nothing loaded from other sites; views and clicks counted apart from scans ([ADR 0011](adr/0011-item-page.md)) | `3d59bc2` | `landing` · `item_page` |
| Item page per record | Each record chooses its page or its own target as default (explicit `gs1:defaultLink` links per record when a key uses the page); the editor shows the key's other records' choices; each link type once on the page, in the visitor's best language; the brand's logo as favicon; brands owned through their prefix ([ADR 0011 §8](adr/0011-item-page.md)) | `cb67cf5` | `item_page`: record · `mock_parity`: gs1:defaultLink |
| Verified by GS1 | On the item's page, a link that looks a GTIN or GLN up in Verified by GS1, on when the installation sets its address and the brand allows it; never in the linkset | `3d59bc2` | `landing`: Verified by GS1 |

## Organisations' own domains

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Organisation's own domain | QR codes on the organisation's domain with an optional path stem, proved by DNS, default per prefix or chosen on the label; the resolver answers on it for that organisation only; certificates by a host script ([ADR 0009](adr/0009-tenant-domains.md)) | `0a6e42a` | `domains` · `domains_resolver` · `domains_e2e` |
| Domains without the terminal | A domain verified in the portal gets its nginx site and Let's Encrypt certificate within about 5 minutes (the operator's script, scheduled by the installer); its card shows the certificate pending, served until a date, or failed with the next attempt ([ADR 0009 §7](adr/0009-tenant-domains.md)) | `0bfe208` | `domains`: host · `install`: domains |

## Monitoring and alerts

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Monitoring and alerts | The worker checks the resolver through the proxy, the daily backup, the certificate and spikes of codes nobody registered every 5 minutes, and e-mails the administrators when something goes wrong and when it is right again; states in the overview ([ADR 0008](adr/0008-monitoring-and-alerts.md)) | `57a5420` | `monitor` |
| Alert history | Each alert raised and ended, kept 400 days, listed on the *Alerts* screen by organisation, kind and date ([ADR 0013](adr/0013-administration-and-navigation.md)) | `a3b3cea` | `admin_nav`: a check going into alert is recorded once · `admin_nav_e2e`: alert history |

## Portal: robustness and security

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Back end between browser and API | The API token never reaches the browser | `126f507` | `portal_config` |
| Same-origin writes | Writes need a JSON body and the portal's own origin | `126f507` | `gcp`: another site's page |
| Security headers | `nosniff`, `DENY` framing, same-origin referrer, `no-store` | `126f507` | `home`: Content Security Policy |
| Special characters | ASCII digits only in identifiers; invisible characters removed; NFC text without control characters; addresses with spaces or line breaks refused; typed user names logged safely | `1b58bfd` | `special_chars` |
| Formula protection | CSV/XLSX exports and the audit CSV cannot run formulas in Excel | `1b58bfd` | `special_chars`: no cell is a formula · `requestlog`: formula |
| Large cells | A CSV cell above 128 KB is reported, not a server error | `9d12f9d` | `sheet`: a CSV cell above 128 KB |
| Portal data in its own database | Users, record metadata, journal, sign-in failures and the link checker's cache in the database `resolver_portal` of the installation's MongoDB, reached with a user that may use that database only; the resolver's database untouched | `d783f3d` | `store` |
| Sign-in lockout for the whole installation | Five failures lock a user name or an address for 15 minutes in every portal replica and across restarts | `d783f3d` | `store`: login_failures |
| Last administrator kept | Changes of users are serialised by a lock shared by every process: the last enabled administrator cannot be removed or demoted, even by two administrators at once | `71b15f2`, `d783f3d` | `governance`: last administrator protected |
| Background jobs in a worker | Imports and checks of many links are jobs in the portal's database, run one at a time by the `portal-worker` service; a stopped worker hands its job back at once, a dead one's job goes back to the queue after two minutes; an import continues where it was; a job interrupted three times fails, keeping what was done | `a072e9d` | `jobs` |
| Job worker not running | The browser warns when a job has waited 15 seconds with no worker running, and says when a job failed | `a072e9d` | `jobs`: worker |
| Replicas | The resolver, the data entry API, the portal and the job worker can each run as several containers (`*_REPLICAS` in `.env`); the proxy finds them through Docker's DNS every 10 seconds and shares the requests, skipping a replica that is stopping | `20f3304` | `home`: replica · `deploy`: replicas |
| Fallback session key | Without `PORTAL_SECRET_KEY`, every portal process and replica on one host reads one complete `secret.key`, also when they start at the same moment | `126f507`, `20f3304` | `deploy`: secret.key |

## Portal: languages and look

| Feature | What it does | Since | Checks |
|---|---|---|---|
| pt-BR and en-GB | Every text in both languages, switched live; browser language detected; choice shared with the resolver's pages and the home page | `126f507` | `i18n`: pt-BR · `i18n`: en-GB |
| Twelve interface languages | Portuguese, English, Spanish, French, German, Italian, Turkish (since `984f2ce`), Simplified Chinese, Japanese, Korean, Hindi and Arabic (right to left) in the portal, e-mails, resolver pages, item's page and home page; catalogues loaded on demand; every text checked in every language ([ADR 0014](adr/0014-interface-languages.md)) | `3d66bdd` | `i18n` · `languages_e2e` |
| Language menus in order | The interface languages listed with the names written in the Latin alphabet first, alphabetically, then the others by script, in the portal, the home page and the resolver's pages ([ADR 0014 §7](adr/0014-interface-languages.md)) | `984f2ce` | `languages_e2e`: the Latin alphabet's first · `i18n`: the Latin alphabet's names first · `home`: the Latin alphabet's first |
| Message codes | The server answers with codes; the browser translates | `126f507` | `i18n`: placeholders |
| gs1.org-like style | Montserrat, GS1 blue and orange; responsive down to phones | `126f507` | `portal_e2e`: logo and menu link to the resolver home page |
| No organisation names | Operator details only from `.env` | `7e7a62a`, `764e360` | `install`: organisation |

## Home page and navigation

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Home page at `/` | What the resolver is, how to use it, links to the portal and API docs; operator from the description file (the GS1 Digital Link syntax box was removed in `1a1ca59`) | `ec1f1d7` | `home` |
| Community notice | Footer of the home page, the sign-in page and the portal, and the README: maintained by the community, not by GS1 or any GS1 Member Organisation; the operator is responsible for the use | `1a1ca59` | `home`: community software |
| Operator link | The operator's name links to `RESOLVER_ORG_URL` | `cc72145` | `home`: operator |
| Navigation | Logo → home page; *Home page* in the portal's user menu | `a49f24d` | `home`: language menu |

## Configuration, installation and operation

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Layered configuration | `.env.example` (committed defaults) + optional `.env` (installation values) for every service | `d51e398` | `deploy`: .env |
| Bind addresses | `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` keep ports 8080 and 27017 off the network behind a TLS proxy | `d51e398` | `install`: ports bound to 127.0.0.1 · `install`: database stays on 127.0.0.1 |
| Ubuntu installer | `scripts/install.sh`: checks, questions, Docker, nginx + Certbot or an existing certificate or an external proxy, `.env` with generated secrets, start-up, backup cron; safe to re-run; `--non-interactive` | `e11f630` | `install` |
| Installer hardening | Passwords with special characters; refuses a single quote in the first user's password | `3f1ff37` | `install`: .env mode 600 |
| Proxy follows the services | nginx 1.30 asks Docker's DNS for every service's replicas every 10 seconds: recreated, added or removed containers need no proxy restart, and the proxy starts while a service is down (until `20f3304`: Compose restarted the proxy when a service behind it was recreated) | `5f8c7d7`, `20f3304` | `home`: replica |
| Servers | gunicorn in the resolver, the data entry API and the portal, with `*_PROCESSES` processes per container (default 2) | `20f3304` | `deploy`: gunicorn |
| Replicas in the installer | The installer writes the replica counts to `.env` (1 of each unless the environment or the existing `.env` says otherwise) | `20f3304` | `install`: replicas |
| Daily backup | MongoDB dump (the portal's database included) + portal configuration volume, 14 days kept, cron at 02:30 | `ba0c293`, `d783f3d` | `deploy`: backup: a good dump writes the archive · `install`: backup cron |
| Portal database user | The one-shot service `portal-db-init` creates the portal's MongoDB user, or brings its password up to date, at every start | `d783f3d` | `store_mongodb` |
| Move from the files of earlier versions | At its first start the portal imports `users.json`, `records-meta.json` and `journal.jsonl` into its database and keeps them as `*.migrated`; an interrupted import finishes at the next start | `d783f3d` | `store`: migration |
| Installer secrets for the portal | `PORTAL_DB_PASSWORD` and `PORTAL_SECRET_KEY` generated and kept on re-runs | `d783f3d` | `install`: portal database password |
| Health check | `/portal/healthz`, with the job worker (`worker`: `ok` or `unavailable`) and e-mail (`mail`: `on` or `off`); the installer warns when the worker does not report | `126f507`, `a072e9d`, `03c924b` | `deploy`: healthz |
| E-mail relay | Messages through an authenticated SMTP relay (587 STARTTLS or 465 TLS, certificate verified), sent and retried by the worker; settings in `.env`, asked by the installer; `python mail.py test <address>`; a Mailpit service (profile `mail-test`) for trying it | `03c924b` | `mail`: relay · `install`: e-mail relay |
| One engine release | The GS1 Barcode Syntax Engine release is written once, in `docker-compose.yml` (`x-gs1-syntax-engine`), and used by the resolver, the data entry API, the portal, CI and the tests | `8e3d9c7` | `deploy`: engine release |
| Off-server backup copy | Each daily backup copied to `BACKUP_COPY_TO` (rsync); a failed copy fails the run and alerts | `449edef` | `deploy`: backup copy |
| Restore rehearsal | `scripts/restore-rehearsal.sh`: an archive restored into a throw-away container, its counts next to the live database's | `449edef` | `deploy`: rehearsal |
| Upgrade from the official resolver | `scripts/upgrade-from-official.sh`: an installation of the official GS1 Resolver CE v3 upgraded in its own folder — checks, a backup, the official containers stopped with the volume kept, this branch checked out beside the official one, the credentials and token kept, the installer, the records compared | `0c76bf0` | `deploy`: upgrade |
| Secret rotation | `scripts/rotate-secrets.sh`: new API token, session key and database passwords, MongoDB's changed in the database first, nothing printed | `449edef` | `deploy`: rotation |
| Installer's final checks | The home page, the description file, a scan of GS1's example GTIN through the proxy and the portal over the public address | `449edef` | `install`: a scan through the proxy checked at the end |
| Load test | `dev-tests/load/load_test.py`: a steady rate of scans, linksets and item pages with response-time percentiles and pass/fail thresholds | `37c5664` | `load` |
| `portal-worker` service | The portal's image running the job worker; `PORTAL_WORKER=embedded` runs it as a thread of the portal for a set-up without the service | `a072e9d` | `deploy`: worker · `jobs`: worker |

## Development tests and documentation

| Feature | What it does | Since | Checks |
|---|---|---|---|
| Development tests | Resolver, GS1's resolver test suite run in Chromium against the resolver code, EPC binary decoder (checked against TDS annex E.3 and the `epc-tds` library), data entry, keys, governance, spreadsheets, special characters, data attributes, link checker, background jobs (also as worker processes on a real MongoDB), portal end to end in Chromium (desktop and phone), home page and replicas through nginx, installer through shims, deployment (Compose, gunicorn) | `0733a3f` and later | `docs`: every test program is in the inventory |
| Development tests through pytest | `pytest dev-tests` runs every program, by group (`-m resolver`, `portal`, `e2e`, `home`, `install`, `database`), with each program's check count; strict mode for CI | `d68a883`, `d783f3d` | `docs`: every test program is in the inventory |
| Continuous integration | GitHub Actions runs the tests in six parallel jobs on every push and pull request to `gs1br/develop`, one of them on a real MongoDB 7 (service container), the proxy test on nginx 1.30; pinned versions, cached engines and browser; status badge in the README | `d68a883`, `d783f3d`, `20f3304` | `deploy`: engine release |
| Weekly engine update check | A scheduled GitHub Actions job opens an issue when a newer GS1 Barcode Syntax Engine is released: what changes in the dictionary, the messages that need a translation, the portal's test results with it | `6f6ce19`, `e7c5a6d` | `deploy`: engine |
| Screenshots | `dev-tests/docs/screenshots.py` regenerates the README and user guide images | `f14d8c4`, session 4 | `docs`: every relative link |
| Documentation | README, user guide, features, history, developer guide, extensions documentation, changelog | `539bab0` and later | `docs` |
| Feature inventory and documents in step | Every check of every test program listed by area ([test-inventory.md](test-inventory.md)); each feature here cites its checks; the developer guide's counts, the documentation index, the API reference and every relative link checked by a test ([ADR 0016](adr/0016-documentation-and-feature-inventory.md)) | `6b8737e` | `docs`: every feature cites at least one check · `docs`: with the inventory's count · `docs`: every relative link |
| Tenant API reference | [api-reference.md](api-reference.md), every operation, parameter, answer and schema of `/portal/api/v1`, generated from `portal/openapi.json` | `6b8737e` | `docs`: the API reference is what portal/openapi.json gives |

## Kept from the official project

Resolution of GS1 Digital Link URIs with content negotiation (language, media type, context), the data
entry API (create, read, update, delete; v2 documents converted to v3), validation of every request by
the GS1 Barcode Syntax Engine (Node), the MongoDB database, the nginx front end and the official tests in
`tests/`.
