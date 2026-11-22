# Documentation

The software is maintained by its community, not by GS1 or any GS1 Member Organisation; whoever operates
an installation is responsible for its use (see the notice at the top of the [README](../README.md)).

The documents are grouped by who reads them. Every feature is listed in [features.md](features.md), each with the
development tests' checks that prove it; the whole list of checks is the [inventory of features](test-inventory.md)
([ADR 0016](adr/0016-documentation-and-feature-inventory.md)).

## People who register records

| Document | What it holds |
|---|---|
| [Portal user guide](portal-user-guide.md) | every task in the portal, step by step, with screenshots: signing in and languages, the editor, keys and qualifiers, targets and the item's page, labels (QR code, Data Matrix, EAN/UPC, PDF, ZIP) and EPCs for RFID and NFC, data attributes, the record list with every search and filter (by text, key type, qualifier, author, link problems, a scanner's or an RFID reader's code), spreadsheets, link checks, requests to the resolver, the overview, messages and what to do |
| [Features](features.md) | every feature, what it does, the commit that brought it and the checks that prove it |

## Organisations' administrators

| Document | What it holds |
|---|---|
| [Portal user guide](portal-user-guide.md), section 14 | users and their prefixes, the organisation's page (prefixes, users, domains, item page brands, single sign-on, API keys, exports, alerts), the audit trail, request log retention, domains, single sign-on, API keys |

## Server administrators and operators

| Document | What it holds |
|---|---|
| [Operator's guide](extensions/README.md) | installation, configuration, every setting, organisations and server administrators, e-mail, the request log and GeoIP, domains and certificates, monitoring, export limits, GS1's GCP length table, backup and restore, replicas and the load test, hardening, going to production |
| [Portal user guide](portal-user-guide.md), section 14 | the screens only server administrators see (organisations, the export maximum, the GCP length table, support access, alerts of the installation) |
| [Changelog](extensions/CHANGELOG.md) | every change on the branch, with the commit |
| [Conformance review](conformance-review.md) | clause-by-clause review against GS1 Digital Link URI Syntax 1.7 and GS1-Conformant Resolver 1.2.1: findings, evidence, candidate errata |
| [Third-party software, data and licences](third-party.md) | what the software is made of besides its own code (components, data such as the DB-IP GeoIP database, services), each licence, what an operator must do, and why nothing restricts commercial use |

## Integrators

| Document | What it holds |
|---|---|
| [Tenant API reference](api-reference.md) | every operation, parameter, answer and schema of `/portal/api/v1`, generated from the OpenAPI description the API serves |
| [README](../README.md), *Tenant API* and *API reference* | how to call the API and the official data entry API |

## Developers and maintainers

| Document | What it holds |
|---|---|
| [Developer guide](developer-guide.md) | services, source files, request flows, the portal's API, its data, the tests with their counts, how to extend |
| [Development tests](../dev-tests/README.md) | every test program, how to set up and run them |
| [Inventory of features](test-inventory.md) | every check of every test program, grouped by area |
| [Threat model](threat-model.md) | the services and their trust boundaries, the assets ranked by their effect on patient safety, actors, entry points, threats with the controls that answer them, hazards that are not attacks, gaps and the plan of the security review |
| [History](history.md) | how the project evolved session by session, decisions, lessons, open items |
| [Translation guide](translation-glossary.md) | the rules and glossary for the texts of the twelve interface languages, and how to contribute corrections |
| [Official README](upstream-README.md) | the README of the official GS1 Resolver CE, kept for reference |

## Architecture decision records

| Record | Decision |
|---|---|
| [ADR 0001](adr/0001-portal-state-in-mongodb.md) | the portal's state in MongoDB, background jobs in a worker, more than one replica |
| [ADR 0002](adr/0002-tenants.md) | organisations that own GS1 Company Prefixes, the server administrator, support access, an audit trail per organisation |
| [ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md) | one source for the GS1 rules (the GS1 Barcode Syntax Dictionary), one engine release, engine messages translated, a weekly update check |
| [ADR 0004](adr/0004-e-mail.md) | outgoing mail through an authenticated relay, invitations, password recovery by single-use link, notifications with per-user preferences |
| [ADR 0005](adr/0005-tenant-api.md) | the portal's versioned API for organisations' systems, API keys (scopes, prefixes, expiry, hash only), a request limit per key, an OpenAPI description |
| [ADR 0006](adr/0006-resolver-request-log.md) | the resolver's log of requests without personal data, daily aggregates, attribution at query time; browser, approximate location and retention set in the portal |
| [ADR 0007](adr/0007-overview-indicators.md) | the overview after sign-in: usage, resolution quality, records, operation and governance per scope; exports; `/stats` |
| [ADR 0008](adr/0008-monitoring-and-alerts.md) | monitoring the resolver, the backup, the certificate and spikes of 404, alerts by e-mail |
| [ADR 0009](adr/0009-tenant-domains.md) | an organisation's own domain in the QR code, proved by DNS, served with its certificate without the terminal |
| [ADR 0010](adr/0010-label-studio.md) | the label studio: sizes, PDF, EAN/UPC beside the QR code, every format in a zip; Data Matrix and scanning environments; an EPC for every key |
| [ADR 0011](adr/0011-item-page.md) | the item's page as a record's default target, brands per prefix, Verified by GS1 |
| [ADR 0012](adr/0012-single-sign-on.md) | single sign-on per organisation with OpenID Connect; limits on exports, set in the portal within an installation maximum |
| [ADR 0013](adr/0013-administration-and-navigation.md) | a sidebar, an organisation's page, prefixes as rows, the portal's own dialogs, the overview by organisation, the alert history |
| [ADR 0014](adr/0014-interface-languages.md) | the interface languages (twelve since Turkish was added), Arabic right to left, every text in every language checked, the menus' order |
| [ADR 0015](adr/0015-gcp-length-table.md) | the GS1 Company Prefix's length from GS1's GCP length table, uploaded by the server administrator |
| [ADR 0016](adr/0016-documentation-and-feature-inventory.md) | the documents by reader, the feature inventory drawn from the tests' checks, the API reference generated |
| [ADR 0018](adr/0018-forwarding.md) | forwarding: every code of a prefix sent to another resolver, and the codes this resolver does not know sent to a resolver of last resort (`https://id.gs1.org` by default), both switched on in the portal, with the overview's figures |
| [ADR 0019](adr/0019-appearance.md) | the installation's appearance: the title in place of *GS1 Resolver Community Edition*, the logo and three colours, set by server administrators in the portal for every page (portal, home page, resolver's pages), with a button that restores the original |
| [ADR 0017](adr/0017-privacy-notice.md) | the installation's privacy notice: written in the portal by server administrators, kept as versions, linked from every footer, a default text on the operator's responsibility |
| [ADR 0020](adr/0020-security-assessment.md) | a security assessment for a healthcare information chain: a threat model first, then a review of the code by area; findings kept in a private register until fixed, each proved by a development test |
| [ADR 0021](adr/0021-data-entry-api-closed.md) | the official data entry API (`/api`, `/swaggerui`) closed at the proxy by default, opened to the addresses of `DATA_ENTRY_API_ALLOW`; the client read from `X-Forwarded-For` of trusted proxies only; organisations' systems on the tenant API |
| [ADR 0022](adr/0022-answering-level.md) | the level that answered: `Resolution-Anchor` and `Resolution-Match` on every redirect and choice, a notice on the resolver's pages when the links come from a less specific level, an optional strict mode per organisation for five safety-critical link types (a batch or serial without its own record answers 404), warnings in the portal |
| [ADR 0023](adr/0023-record-level-delete.md) | a record-level delete in the data entry API (`DELETE` with `removeRecord`): one record removed in one conditional write of the key's document, used by the portal wherever it removed a record, so a key is never left without its other records |
| [ADR 0024](adr/0024-name-and-about.md) | the name *GS1 Digital Link Resolver Suite* in place of *Expansion Pack*, and a public About page (`/portal/about`: version and commit written at the image's build, repository, licence, manuals, origin, third-party components with their licences, trademarks) linked from the portal's menu, its sign-in page and the home page |
| [ADR 0025](adr/0025-sso-domain-proof-and-subject.md) | single sign-on hardened (findings F-006, F-007): an e-mail domain signs people in only once proved by a DNS TXT record or a server administrator's approval, one configuration per domain; `email_verified` required unless the configuration says its provider never sends it; the account bound to the provider's issuer and subject at its first sign-in, forgotten by an administrator |
| [ADR 0026](adr/0026-journal-integrity.md) | the journal's integrity (finding F-008): a record change journalled before the data entry API is called and refused when it cannot be, a failed one followed by `change-failed`; every event sealed in a hash chain per audit trail and retention category with an HMAC whose key (`PORTAL_JOURNAL_KEY`) stays outside the database; administrators verify the chains and keep heads as receipts, the worker verifies daily and logs the heads |
| [ADR 0027](adr/0027-conditional-writes.md) | no lost update on a key's document (finding F-009): every write of the data entry API conditional on the document as read (`write_document_if_unchanged()`, `create_document()`), read again and applied on top of another writer's change, 409 after three attempts; the portal answers 409 `upstream.conflict` |
| [ADR 0028](adr/0028-language-fallback.md) | a language or market the links do not serve (finding F-010): the header `Resolution-Fallback` on a 307 or 300, the page of a choice with a notice for a browser asking a safety-critical type, the portal's warnings `warning.noLanguage` and `warning.languageGap` |
| [ADR 0029](adr/0029-outbound-requests.md) | requests to addresses users choose (finding F-011): the name resolved once and the address checked contacted, with the name kept for TLS; HTTPS only for the link checker; one link check per organisation and two requests per host at once |
| [ADR 0030](adr/0030-least-privilege-services.md) | the official services without MongoDB's root user (finding F-012): a database user per service with the least privileges it needs, made by `portal-db-init`, the only holder of the root connection; images that do not run as root; MongoDB and the proxy on the host's loopback address by default; the example passwords of the new users refused on a real domain |
| [ADR 0031](adr/0031-request-limits.md) | request limits per client address at the installation's proxy (finding F-013): resolution, the portal and sign-in, connections, each a setting with exempt addresses, an IPv6 address counted with its `/64`, 429 with `Retry-After`; tenant API calls without a valid key counted per minute and failed sign-ins naming no account counted per hour, one journal event an hour |
| [ADR 0032](adr/0032-spreadsheet-reading-limits.md) | spreadsheet imports read one row at a time (finding F-014): reading stops at the row limit, the first 64 columns of a row, blank rows kept as one shared list, an XLSX file measured unpacked (32 MB) before it is opened; the preview stays in the request |
| [ADR 0033](adr/0033-supply-chain.md) | the supply chain (finding F-015): Python lock files with hashes resolved together for the tests and the images, Node.js from the official image and `gs1encoder` from `package-lock.json`, images by digest, actions by commit, Dependabot's weekly proposals, `SECURITY.md`; scanning and an SBOM in step 2 |
| [ADR 0034](adr/0034-session-records.md) | portal sessions kept on the server (finding F-016): a random id in the signed cookie names a record in the `sessions` collection, ended at sign-out, by a password change or reset and by disabling or removing the account or disabling its organisation, so a copied cookie stops working too |
| [ADR 0035](adr/0035-domain-claims-and-lapsed-proofs.md) | domain claims that expire and proofs that lapse (finding F-018, F-006's residual): several organisations may claim a QR code domain, the first proved keeps it, claims go after 7 days; a domain or single sign-on DNS proof whose record is missing for 7 days lapses — no longer offered for new labels, administrators told, taken over by another organisation that proves it |
| [ADR 0036](adr/0036-names-and-addresses-across-organisations.md) | user names and e-mail addresses across organisations (finding F-019): an address unique per organisation, so a refusal never says that a person has an account elsewhere, recovery by address sends a link to each account and single sign-on looks only in the configuration's organisation; an organisation's administrator who meets 5 taken user names in 15 minutes waits, and a name of another organisation is journalled for the operator |
| [ADR 0037](adr/0037-target-addresses.md) | target addresses (finding F-020): user information before the host, IP addresses however they are written and names that only exist inside a network (localhost, names without a dot, `.local`, `.internal`…) refused for every organisation, in the editor, imports, the API and forwarding destinations; an optional list of hosts per organisation (and for the operator's keys) that each target must be or be under |
| [ADR 0038](adr/0038-browser-hardening.md) | the browser's rules (finding F-021): a Content-Security-Policy on every answer of the portal (its own script files and style sheets only), the resolver's pages (their own elements by a nonce drawn for each answer; the item's page loads nothing from other sites), the Swagger UI and the other answers (nothing at all); no framing, no type guessed; Strict-Transport-Security for a year from the installation's proxy over HTTPS; the single origin kept |
| [ADR 0039](adr/0039-known-public-names.md) | the installation's known names only (finding F-022): the resolver writes the name a request was made on (linkset anchors, `Link` and `Resolution-Anchor` headers, the description file) only when it is `FQDN`, one listed in the new setting `FQDN_ALIASES` or a verified domain, `FQDN` otherwise; the proxies' own redirects without the client's `Host`; amends ADR 0009 §8 |
| [ADR 0040](adr/0040-request-bodies.md) | the shape of a request's body (findings F-023 and F-029): every JSON body of a write to the portal's API is one object whose fields hold the kinds `bodies.FIELDS` lists, checked before the route runs — 400 `request.jsonInvalid`, 422 `request.fieldInvalid` naming the field — so that no malformed body answers 500 and no query operator reaches a database filter |
| [ADR 0041](adr/0041-queued-import-account.md) | a queued import writes only while its account may (finding F-024): the worker reads the account before each record and sets the scope from it as a request does; an account removed, re-created, disabled, of a disabled organisation or no longer an editor stops the import (`import.accountChanged`), the records written before kept, journalled as `import-refused` in the organisation's trail |
| [ADR 0042](adr/0042-host-nginx.md) | the host's nginx kept up to date, over HTTP/1.1 (nginx's security release of 18 November 2026): the installer installs or updates it on every run and warns when its package predates the fixes; the HTTPS site it writes no longer serves HTTP/2; the tests run nginx 1.30.7, the proxy image's version |
| [ADR 0043](adr/0043-access-logs.md) | access logs without the client's address or the query string (finding F-025): the proxy's log minimal by default (`PROXY_ACCESS_LOG`: minimal, full or off), no access log in gunicorn or the host's sites, every container's output bounded by `LOG_MAX_SIZE` and `LOG_MAX_FILES` |
| [ADR 0044](adr/0044-encrypted-backups-and-sealed-secrets.md) | encrypted backups and sealed secrets (finding F-026): every archive encrypted with age to the backup key (`BACKUP_KEY_FILE`, `BACKUP_RECIPIENTS`), the restore rehearsal decrypting; the single sign-on client secrets sealed in the database with AES-256-GCM under `PORTAL_DATA_KEY` |
| [ADR 0045](adr/0045-organisation-domains-resolver-only.md) | only the resolver on an organisation's own domain (finding F-027): the host's sites of organisations' domains include a rule that redirects the portal's addresses to the installation's name and refuses the data entry API (404), sites written before changed at the next run of `custom-domains.sh`; stems the installation's proxy would give to something else refused |
| [ADR 0046](adr/0046-forwarding-tells-organisations.md) | a forwarding rule told to the organisations whose codes it sends elsewhere (finding F-028): a change that sends an organisation's codes elsewhere, or stops doing so, is an event in its own trail and an alert to its administrators (`forwarding-on`, `forwarding-off`); a note, or a rule that stays off, tells nobody |
| [ADR 0047](adr/0047-toolkit-processes.md) | the GS1 Digital Link Toolkit's Node.js processes bounded (finding U-002, official code): a one-segment path starts Node.js only when it can be a compressed GS1 Digital Link, at most two processes at once in each server process, killed after 3 s, 503 with `Retry-After` when none is free; recent answers kept |
| [ADR 0048](adr/0048-data-entry-target-rule.md) | the data entry API applies the portal's target rule (finding U-003, official code): every target sent to `POST /new`, `PUT` and `POST /validate` is an `https:` address with a public host name — no user information, IP address or private name — or 400 naming the link; a target the key already holds is accepted as it is |
| [ADR 0049](adr/0049-data-entry-anchors.md) | anchors of one shape and one document id per anchor in the data entry API (finding U-004, official code): every anchor is `/AI/value` with a GS1 primary key and a printable-ASCII value, or 400; an id splits at its first `_`, so a value's own `_` is kept and stored documents keep their ids; the resolver reads ids the same way |
| [ADR 0050](adr/0050-error-answers.md) | error answers without the exception's text and no editor in the images (finding U-006, official code): every error answer of the resolver and the data entry API carries a fixed text, the exception and its traceback go to the service's log; the two images no longer install `nano` |
| [ADR 0051](adr/0051-records-unavailable.md) | a failure of the records' database answered 503 with `Retry-After` and the page that asks to try again (finding F-031): never the answer for a code nobody registered, never the resolver of last resort; the request log counts an error |
| [ADR 0052](adr/0052-database-time-budget.md) | one time budget for the database reads of a resolver request (finding F-032): `RESOLVER_DB_TIMEOUT_MS`, 5 seconds by default; during an outage of MongoDB each scan is answered 503 within it instead of after up to six waits of 30 seconds, with a `Retry-After` of the budget |
| [ADR 0053](adr/0053-settings-age.md) | a limit on the age of the portal's settings in the resolver (finding F-033): after `RESOLVER_SETTINGS_MAX_AGE_S` (15 minutes) without reading them, forwarding, brands and appearance stop, domains, strict mode and retention are kept; an error in the log, `settings` in the heartbeat and the portal's alert *Resolver's settings* |
| [ADR 0054](adr/0054-forwarding-tells-new-prefixes.md) | an organisation given a prefix that a forwarding rule already covers is told (a residual of finding F-028): when a server administrator creates an organisation or changes its prefixes, each rule switched on that covers a prefix it did not have before is an event in its own trail and an alert to its administrators (`forwarding-covered`) |

The documentation is written in British English only; readers of other languages can use the translation built into
their browser. The software itself — the portal, its e-mails, the resolver's pages, the item's page and the home page —
speaks twelve languages ([ADR 0014](adr/0014-interface-languages.md)).

Images: `images/` (README) and `images/guide/` (user guide), regenerated by `dev-tests/docs/screenshots.py`.
