# Features

Every feature of the GS1 Digital Link Resolver CE — Expansion Pack, grouped by component, with what it
does and the commit that introduced it (on branch `gs1br/develop`, oldest first in
[history.md](history.md)). Features of the official GS1 Resolver CE v3 that the fork keeps unchanged are
listed at the end for completeness.

How to use the portal: [portal user guide](portal-user-guide.md). How each feature is built:
[developer guide](developer-guide.md). Design decisions and details:
[extensions documentation](extensions/README.md).

*Versão em português: [funcionalidades](pt-BR/funcionalidades.md).*

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
- [Portal: robustness and security](#portal-robustness-and-security)
- [Portal: languages and look](#portal-languages-and-look)
- [Home page and navigation](#home-page-and-navigation)
- [Configuration, installation and operation](#configuration-installation-and-operation)
- [Development tests and documentation](#development-tests-and-documentation)
- [Kept from the official project](#kept-from-the-official-project)

## Resolver (public resolution)

| Feature | What it does | Since |
|---|---|---|
| Walk-up | A level without a record falls back to the next level: serial → batch → variant → key, instead of an error 500 | `766a652` |
| Serial before batch | When a serial-number record and a batch or variant record both apply, the serial number's answers (GS1-Conformant Resolver 2.5.9, rule 4: 01+21 before 01+22+10) | `61babe1` |
| 404 for a missing link type | A record without the requested `linkType` answers 404, as GS1-Conformant Resolver 2.6.2 requires (was 200 with an error inside) | `766a652` |
| Trailing slash | `/10/123/` is treated as `/10/123` (was 400) | `766a652` |
| `linkType` forms | Accepts `x`, `gs1:x`, `https://gs1.org/voc/x`, `https://ref.gs1.org/voc/x`, case-insensitive; `defaultLink` redirects to the default target | `766a652` |
| Conformant linkset | `?linkType=linkset` / `Accept: application/linkset+json` returns plain RFC 9264, valid against GS1's linkset schema; JSON-LD only on request; correct JSON-LD context `Link` header exposed to CORS | `766a652` |
| `gs1:` namespace | Link types in linksets and in the JSON-LD context written in `https://ref.gs1.org/voc/` (Resolver 2.14); stored documents unchanged | `bc573c4` |
| GS1's test suite | Passes every test of GS1's resolver test suite on staging; the suite also runs in the development tests | `cc95d77` |
| Query string forwarding | The scan's query string (data attributes included) is passed on exactly as sent — `;` delimiter and keys without a value kept — always (`"fwqs": false` in older records ignored, Resolver 2.12); joined with `&` when the target already has a query | `766a652`, `4f81234` |
| Default response | Without `linkType`, the default link, unless the request decides a language variant (Resolver 2.6.3, examples 5-7; was 300 for two languages without a match); several links of the default type published as `gs1:defaultLinkMulti` | `4f81234` |
| Choosing among links of one type | Media type, then language (q-values, `pt-BR` → `pt`), then context (examples 8-13); 300 answers a valid linkset of that level, or an HTML page | `4f81234` |
| Request paths checked by the engine | The GS1 Barcode Syntax Engine's Digital Link parser checks the path: qualifiers out of order, data attributes or unknown AIs in the path → 400 | `4f81234` |
| Values with `/` | `%2F` in a value stays in it: the proxy passes the raw request URI and the resolver decodes each segment on its own | `4f81234` |
| EPC binary strings | `/eh…` and `/ex…` (an EPC read from an NFC or hybrid UHF/NFC tag) are decompressed and resolved as the equivalent GS1 Digital Link: every EPC scheme with a Digital Link, the `+` schemes with their +AIDC data and the `++` schemes (their hostname ignored); key qualifiers from the tag go to the path, data attributes to the query string passed on to the target; 400 when the string does not decode (Resolver 2.3, EPCB 1.0.0) | `51a0da8`, `895c4b1` |
| HTML pages for browsers | Errors (400, 404, link type not available — listing the available links) and the linkset as gs1.org-style pages in pt-BR / en-GB, same HTTP status, language menu | `766a652` |
| Level names on the linkset page | Each level named by its anchor: the key, variant, batch/lot, serial, GLN extension… | `b33def6` |
| Safe links on HTML pages | Only `http(s)` targets are links; `javascript:`, `data:` and others are listed without a link | `92bfb5d` |
| Configurable description file | `/.well-known/gs1resolver` takes `resolverRoot` and `contact` (name, address, telephone, `hasURL`) from `.env`, and `termsOfUse` from `RESOLVER_TERMS_URL`; validated against a schema in the tests | `766a652`, `764e360`, `cc72145`, `4f81234` |
| Operator footer | "GS1 Digital Link service operated by …" from `RESOLVER_ORG_NAME`, per installation | `766a652`, `764e360` |

## Data entry API

| Feature | What it does | Since |
|---|---|---|
| `GET /api/summary[?links=true]` | One line per record (anchor, qualifiers, description, default link type, number of links, optionally the links): the portal reads every record in one call | `db56b22` |
| Token on `/api/index` | The official public `GET /api/index` (every identifier on the resolver) now requires the bearer token | `1941e75` |
| `BearerAuth` in Swagger | Every protected operation declares the bearer scheme, so **Authorize** in `/api/docs` works | `1941e75` |
| Registration rules | `POST /new` and `PUT` refuse qualifiers the key does not take, 415 without 8020, 235 with other qualifiers and 22 or 10 with 21 (GS1-Conformant Resolver 2.5.9, rules 1 and 2); a list is refused whole, naming the item | `61babe1` |
| `informativeQualifiers` | A serial-number record of a GTIN or ITIP keeps the unit's variant and batch as information: stored, returned by `GET` and `/summary`, replaced by `PUT`; never used to choose a record, never in the public linkset | `61babe1` |

## Portal: access and accounts

| Feature | What it does | Since |
|---|---|---|
| Sign-in page | Username and password, session cookie (HttpOnly, SameSite, Secure over HTTPS), sliding expiry (`PORTAL_SESSION_HOURS`, default 8) | `126f507` |
| Throttling | 5 failures → 15 minutes wait, per user name and per address | `126f507` |
| Password change | Options dialog; current password required; at least 12 characters; other sessions signed out | `126f507` |
| Session fingerprint | A password change or reset ends every other session of the account | `126f507` |
| Show-password button | An eye in every password field (sign-in, password change) | `1525f82` |
| First user from `.env` | `PORTAL_ADMIN_USERNAME` / `PORTAL_ADMIN_PASSWORD` create the first administrator while there are no users | `126f507` |
| Command-line users | `create_user.py`: create, set password, role, prefixes, remove | `126f507`, `71b15f2` |

## Portal: editor

| Feature | What it does | Since |
|---|---|---|
| Three-step form | Identify → describe → targets, with live validation and the label alongside | `126f507` |
| Open record | Reads the record from the resolver; tells whether it exists and which other records the key has; locks steps 2 and 3 when the identifier changes afterwards | `126f507` |
| Targets | Link type (29 GS1 link types with explanations), language, URL, title, default target, up to 20 per record (the per-target query-string option was removed in `db8e342`) | `126f507` |
| Shared default type | Explains and enforces that every record of a key shares the default link type | `126f507` |
| Safe API sequence | POST appends, PUT merges, partial DELETE removes only the targets the user removed; deleting one record keeps the others of the key (restored on failure) | `126f507` |
| Other records of the key | List under *Open record*: what each applies to, description, links, last change; search, qualifier filter, five rows in view, *Open* with unsaved-changes confirmation | `08570e4` |
| Informative batch and variant | With a serial number, the variant and batch fields of a GTIN or ITIP are marked *informative*: kept with the serial-number record, printed in the QR code, but not part of the registration (GS1-Conformant Resolver 2.5.9, rule 2); opening a serial number without them fills in the stored ones; a different typed value is pointed out | `83d1ba0` |
| "This record applies to" | A card under the qualifiers says, in plain words, what the record applies to and where codes without a record of their own go | `83d1ba0` |
| Record of the key when saving | Saving a batch, serial or extension of a key without a record of its own offers to create that record with the same targets (recommended), with another target, or not (GS1-Conformant Resolver 2.5.9) | `3a49ca9` |
| Copy targets from… | Search any record and add its targets to the form or replace them | `3a49ca9` |
| Confirmation on *Open record* | Asks before discarding unsaved changes, also after the key or qualifiers changed | `3a49ca9` |
| Singular wording | "This identifier has one other record" | `d11c369` |
| Read-only mode | Readers see every field disabled and a note | `71b15f2` |

## Portal: identification keys and qualifiers

| Feature | What it does | Since |
|---|---|---|
| Every primary key of URI Syntax 1.7 §4.3 | GTIN, ITIP, GMN, CPID, GLN (414, 415, 417), GSRN (8017, 8018), GCN, SSCC, GDTI, GINC, GSIN, GRAI, GIAI, each with its own label, hint and checks (check digit, GMN check-character pair, ITIP piece/total, GRAI filler zero…) | `e181ccc` |
| Every key qualifier of §4.4/4.6/4.9 | 22, 10, 21, 235 (TPX), 8011, 254, 7040, 8020, 8019, with the combinations and order the standard allows and the required ones (8020 for 415) | `67d40bb` |
| Mirrors the Syntax Engine | Validation in Python and JavaScript compared with the GS1 Barcode Syntax Engine by the tests | `e181ccc`, `67d40bb` |
| GTIN convenience | 8, 12, 13 or 14 digits typed, stored as GTIN-14; restricted-circulation GTIN-13 (prefix 2) refused | `126f507` |

## Portal: QR code labels

| Feature | What it does | Since |
|---|---|---|
| Live preview | QR code, coloured Digital Link and legend while typing; *Published* / *Not yet registered* | `126f507` |
| PNG and SVG | SVG in millimetres at X = 0.495 mm, 4X quiet zone, HRI 2.2 mm as outlines (no font needed); PNG for screens | `126f507` |
| No GS1 branding | Labels carry no GS1 artwork | `7e7a62a` |
| HRI modes | Full (each element on its own line), key only, none | `1525f82` |
| QR version | Automatic (smallest that fits) or 1–40 | `1525f82` |
| Error correction | L, M (default), Q, H, applied exactly as chosen | `1525f82` |
| "Does not fit" panel | Explains the needed version or the fitting level instead of a broken image (422 `qr.tooSmall` / `qr.tooLong`) | `1525f82` |
| Label block layout | Under the form at every width: code and buttons on the left, options on the right; one column on phones | `1746f19` |
| Try now, Copy link address | Opens or copies the Digital Link | `126f507` |

## Portal: data attributes

| Feature | What it does | Since |
|---|---|---|
| Attributes in the QR code | Expiry, weight, price… (URI Syntax §4.10) added to the code drawn now; never stored; cleared when another record opens | `4b42c6f` |
| GS1 Barcode Syntax Engine | Validation by GS1's own C library 1.4.1 and Python binding (built in a Docker stage); the option is hidden when the engine is absent | `4b42c6f` |
| Combo box | Pick from *Most used* / *All attributes* or type a number or name; works on phones | `1525f82` |
| Order | Up/down buttons | `1525f82` |
| Day 00 refused | With the first/last day of the month suggested | `1525f82` |
| Decimal families | (310n), (392n)… accept `123,45` or `123.45` and encode `3102=012345`; the URI line shows the decimals used | `e71384d` |
| No limit of 10 | A ceiling of 100 per request; the QR code is the real limit | `e71384d` |
| Localised messages | Association errors (`requires`, `pair`) in both languages | `08570e4` |
| Portuguese AI names | 216 names, e.g. "(17) Data de validade (USE BY or EXPIRY)", in the field and in the list; searching the list keeps the chosen attribute | `08570e4`, `cf5ce10` |

## Portal: record list

| Feature | What it does | Since |
|---|---|---|
| Registered records | Every record the user may see, most recently changed first, with identifier, scope, links and last change | `db56b22` |
| Text search | Identifier (with or without leading zeros), key name, description, qualifier; accents and case ignored | `db56b22` |
| Filter by author | *Changed by* | `db56b22` |
| Filter by key type | *Identifier type*, with counts | `f4f3071` |
| Filter by qualifier | *Qualifier*: any qualifier, none, or sets made elsewhere; follows the key type | `f4f3071` |
| Code search | A pasted GS1 Digital Link or bracketed element string shows the exact record (marked), the more general and the more specific ones; ignored AIs named | `f4f3071` |
| Clear search and filters | One button | `f4f3071` |
| Records made elsewhere | Listed (templates such as `{lotnumber}`), not opened | `db56b22`, `7339e3c` |
| Informative qualifiers in lists | Filters, text search and code search find a serial number by its informative batch or variant; the scope shows them | `83d1ba0` |
| Status filter and alert | *Status*: records of keys without a record of their own (with an alert and *Show only these*) and serial numbers registered with their batch before rule 2; a badge on each | `3a49ca9` |

## Portal: spreadsheets

| Feature | What it does | Since |
|---|---|---|
| Export | XLSX (with Link types, Keys and Languages sheets) or CSV, one row per target, headers in the user's language | `429dce7` |
| Two-step import | Preview with New / Changed / Unchanged / With errors and every wrong row explained, then apply in the background with progress | `429dce7`, `7339e3c` |
| Never deletes | Records not in the file stay | `429dce7` |
| Any BCP 47 language | `pt-BR`, `en-US`, `vi`, `und`… accepted and kept | `7339e3c` |
| Limits per format | XLSX and CSV/TXT: 5,000 rows and 700 KB, shown in the dialog | `9d12f9d` |
| Excel-friendly | Windows-1252, UTF-8 and UTF-16 ("Unicode text") files; separator detected; scientific notation detected; formula protection on export | `429dce7`, `1b58bfd` |
| Informative qualifiers in spreadsheets | `(10)B42(21)S1` is exported for a serial number with an informative batch and imported back the same way; a change of batch is shown in the preview | `83d1ba0` |
| Keys without a record of their own | The preview lists them and, ticked by default, creates each key's record with the targets of its first row | `3a49ca9` |

## Portal: link checker

| Feature | What it does | Since |
|---|---|---|
| Check targets (editor) | After each save and on demand; result under each target | `0da20ee` |
| Check links (every record) | Background job; summary kept; badge per record; *Only with problems* | `0da20ee` |
| Import preview check | Optional, does not stop the import | `0da20ee` |
| SSRF guard | Only public addresses are contacted, at every redirect | `0da20ee` |
| Clear reasons | HTTP errors, blocked checks (401/403/429), unreachable, HTTPS downgrade, too many redirects, private address, invalid | `0da20ee` |

## Portal: governance

| Feature | What it does | Since |
|---|---|---|
| Roles | Reader < editor < administrator, checked on every call | `71b15f2` |
| GS1 Company Prefixes per user | Users see and change only their prefixes' identifiers (after the indicator digit of GTIN-14/ITIP, the extension digit of SSCC, the filler zero of GRAI) | `71b15f2` |
| Users screen | Create with a temporary password shown once, change role and prefixes, reset, disable, remove; at least one active administrator | `71b15f2` |
| Record history | Every version saved through the portal, with restore | `71b15f2` |
| Audit trail | Sign-ins, changes, imports, exports, administration; filters; CSV | `71b15f2` |
| Journal | `journal.jsonl` in the configuration volume, included in the backup | `71b15f2` |

## Portal: robustness and security

| Feature | What it does | Since |
|---|---|---|
| Back end between browser and API | The API token never reaches the browser | `126f507` |
| Same-origin writes | Writes need a JSON body and the portal's own origin | `126f507` |
| Security headers | `nosniff`, `DENY` framing, same-origin referrer, `no-store` | `126f507` |
| Special characters | ASCII digits only in identifiers; invisible characters removed; NFC text without control characters; addresses with spaces or line breaks refused; typed user names logged safely | `1b58bfd` |
| Formula protection | CSV/XLSX exports and the audit CSV cannot run formulas in Excel | `1b58bfd` |
| Large cells | A CSV cell above 128 KB is reported, not a server error | `9d12f9d` |

## Portal: languages and look

| Feature | What it does | Since |
|---|---|---|
| pt-BR and en-GB | Every text in both languages, switched live; browser language detected; choice shared with the resolver's pages and the home page | `126f507` |
| Message codes | The server answers with codes; the browser translates | `126f507` |
| gs1.org-like style | Montserrat, GS1 blue and orange; responsive down to phones | `126f507` |
| No organisation names | Operator details only from `.env` | `7e7a62a`, `764e360` |

## Home page and navigation

| Feature | What it does | Since |
|---|---|---|
| Home page at `/` | What the resolver is, how to use it, links to the portal and API docs; operator from the description file | `ec1f1d7` |
| Operator link | The operator's name links to `RESOLVER_ORG_URL` | `cc72145` |
| Navigation | Logo → home page; *Home page* in the portal's user menu | `a49f24d` |

## Configuration, installation and operation

| Feature | What it does | Since |
|---|---|---|
| Layered configuration | `.env.example` (committed defaults) + optional `.env` (installation values) for every service | `d51e398` |
| Bind addresses | `PROXY_BIND_ADDRESS`, `DATABASE_BIND_ADDRESS` keep ports 8080 and 27017 off the network behind a TLS proxy | `d51e398` |
| Ubuntu installer | `scripts/install.sh`: checks, questions, Docker, nginx + Certbot or an existing certificate or an external proxy, `.env` with generated secrets, start-up, backup cron; safe to re-run; `--non-interactive` | `e11f630` |
| Installer hardening | Passwords with special characters; refuses a single quote in the first user's password | `3f1ff37` |
| Proxy restart | Compose restarts the proxy when a service behind it is recreated | `5f8c7d7` |
| Daily backup | MongoDB dump + portal configuration volume, 14 days kept, cron at 02:30 | `ba0c293` |
| Health check | `/portal/healthz` | `126f507` |

## Development tests and documentation

| Feature | What it does | Since |
|---|---|---|
| Development tests | Resolver, GS1's resolver test suite run in Chromium against the resolver code, EPC binary decoder (checked against TDS annex E.3 and the `epc-tds` library), data entry, keys, governance, spreadsheets, special characters, data attributes, link checker, portal end to end in Chromium (desktop and phone), home page through nginx, installer through shims | `0733a3f` and later |
| Screenshots | `dev-tests/docs/screenshots.py` regenerates the README and user guide images | `f14d8c4`, session 4 |
| Documentation | README, user guide, features, history, developer guide, extensions documentation, changelog | `539bab0` and later |

## Kept from the official project

Resolution of GS1 Digital Link URIs with content negotiation (language, media type, context), the data
entry API (create, read, update, delete; v2 documents converted to v3), validation of every request by
the GS1 Barcode Syntax Engine (Node), the MongoDB database, the nginx front end and the official tests in
`tests/`.
