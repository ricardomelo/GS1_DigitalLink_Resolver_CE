# History of the Expansion Pack

How the GS1 Digital Link Resolver CE — Expansion Pack grew from the official GS1 Resolver CE v3, session
by session, with the decisions taken on the way and why. The day-by-day list of changes is in
[extensions/CHANGELOG.md](extensions/CHANGELOG.md); what each feature does today is in
[features.md](features.md).

The work was done in four working sessions between 22 September and 1 October 2026, against a staging
installation of the resolver run by the maintainer. Every increment was tested on that installation before
the next one started.

## Timeline

| Session | Dates (2026) | Delivery | Result |
|---|---|---|---|
| 0 — starting point | March | official commit `bf885fd` | GS1 Resolver CE v3, data entry by JSON API only |
| 1 — portal 1.0.0 | until 23 Sep | zip package with a patch for the official code | portal for GTINs and batches, conformance fixes, labels, backup |
| 2 — the fork | 25–29 Sep | 21 commits, `d51e398` → `7e7a62a` | fork with git history, installer, every key and qualifier, spreadsheets, link checker, governance |
| 3 — Expansion Pack | 29–30 Sep | 22 commits, `d4e5584` → `cf5ce10` | special characters, data attributes, QR options, new editor layout, other records of a key |
| 4 — search and documentation | 30 Sep – 1 Oct | `f4f3071` and the documentation commits | filters by key type and qualifier, code search, user guide, feature list, this history, developer guide, docstrings |

At the end of session 4 the fork changes or adds 70 files of the official project (about 16,000 lines
added) and is covered by 739 checks in the development tests, plus the installer test.

## Session 0 — the official project

GS1 Resolver Community Edition v3 (official commit `bf885fdf4888f0395229478bf6b50342c1f761a8`, March 2026):
a Python resolver (`web_server`), a data entry API (`data_entry_server`), MongoDB and an nginx front end,
run with Docker Compose. Records are entered by sending Resolver CE v3 JSON documents with a bearer token,
which needs technical knowledge, and running the GS1 conformance test suite against an installation
showed several defects (see session 1).

## Session 1 — a portal for non-technical users (version 1.0.0)

**Goal.** Let people who are not developers register where a product's QR code leads, and fix the
conformance defects found in the resolver.

**Architecture chosen.** A new service, `portal-service` (Flask behind gunicorn), serves the pages *and*
talks to the data entry API on the server side. The API token never reaches the browser, and the portal
chooses the safe sequence of API calls — the API appends on `POST /new`, merges on `PUT` and deletes whole
documents on `DELETE`, so a naive form would duplicate or lose targets. This "back end for the front end"
has remained the core of the design.

**Delivered** as a zip package (portal, `gs1br-resolver.patch` for the official code, Compose override,
description file, backup script, tests, `SHA256SUMS`), installed on the staging server and reported working
on 23 September as checkpoint 1.0.0:

- three-step form: GTIN with check-digit feedback and an optional batch/lot, description, targets with
  link type, language, default target and per-target query-string forwarding (`fwqs`);
- QR code labels (PNG, SVG in millimetres) following the *QR Codes powered by GS1* dimensions, with an
  optional branding mark (later removed);
- Brazilian Portuguese and British English, switched live, with message codes translated in the browser
  and the choice shared with the resolver's pages through a cookie;
- sign-in with session cookie, lockout after five failures, password change ending other sessions;
- resolver fixes: walk-up from an unknown batch to the GTIN, trailing slash, every `linkType` form,
  404 for a missing link type, RFC 9264 linkset valid against GS1's schema, JSON-LD context header,
  `fwqs`, HTML pages for browsers;
- a description file with the real resolver root, ports 8080 and 27017 bound to 127.0.0.1, daily MongoDB
  backup;
- development tests: 53 resolver checks and 16 portal checks in a real browser.

**Learnt during installation.** `FQDN` must hold a bare domain (a value with `https://` produced
`https://https://…` in linksets); Docker publishes ports past the host firewall, so ports must be bound to
127.0.0.1 behind a TLS proxy; restoring files for a patch must come from `HEAD` and not from the git index,
which held an already-patched copy.

**Left open.** Rotation of development secrets, a recorded run of the conformance suite, an off-server
backup copy, and a list of improvements: record list, spreadsheets, link checker, serial numbers and
variants, roles and prefixes, history and audit.

## Session 2 — the fork and the big features

**From patch to fork.** Carrying a patch over an untouched upstream checkout was fragile. The work moved
to a fork of the official repository on GitHub (branch `gs1br/develop`, made the default branch) — the
maintainer's first GitHub project. Every increment is delivered as a git bundle that the maintainer pulls
on a workstation and pushes, and the server follows with `git pull && docker compose up -d --build`. The
1.0.0 contents were rewritten as seven topic commits so that each can later be offered upstream on its own.

| Commit | Change | Why |
|---|---|---|
| `d51e398` | `.env.example` with development defaults + optional `.env` for real values; bind-address variables | keep the official variable names, commit only safe defaults |
| `766a652` | resolver conformance fixes and HTML pages; description file from the configuration | from 1.0.0, now as a reviewable commit |
| `126f507` | the portal (first user from `PORTAL_ADMIN_*`, named configuration volume) | from 1.0.0 |
| `ec1f1d7` | home page at `/` | the root of a resolver should explain itself to a person |
| `ba0c293` | backup of the database and the portal volume | users and metadata live outside MongoDB |
| `0733a3f`, `539bab0` | development tests; extensions documentation and changelog | |
| `e11f630` | `scripts/install.sh` for Ubuntu 22.04/24.04 | a third party should install it without this history |
| `5f8c7d7` | Compose restarts the proxy when a service is recreated | nginx resolves upstream names only at start-up |
| `a49f24d` | navigation back to the home page | |
| `db56b22` | record list with search; `GET /api/summary` | one call for every record instead of one per identifier |
| `1941e75` | token on `/api/index`; `BearerAuth` in Swagger | the official `/api/index` listed every identifier publicly (a notice for the official maintainers was drafted) |
| `429dce7`, `7339e3c` | spreadsheet import/export with preview; any BCP 47 language, lot templates, every wrong row at once | bulk work; testing with records made by other tools exposed assumptions |
| `0da20ee` | link checker with SSRF guard | broken targets are the commonest fault of a resolver |
| `e181ccc` | every primary key of URI Syntax 1.7 §4.3 | the portal was GTIN-only |
| `67d40bb` | every key qualifier (§4.4, 4.6, 4.9); AI 415 + 8020 | completes the identification side of the standard |
| `f14d8c4`, `85346a3` | README for the fork with screenshots; official README kept apart | |
| `71b15f2` | governance: roles, GS1 Company Prefixes per user, users screen, record history, audit trail | needed before anyone outside the operator uses the portal |
| `7e7a62a` | GS1 branding removed from labels; AI 415 name; qualifier 235 labelled TPX | labels must not imply endorsement |

**Decisions of this session.** Validation mirrors the GS1 Barcode Syntax Engine and the tests compare the
two; alphanumeric values are limited to letters, digits, `.`, `-` (and `_` in qualifiers); ITIP is offered
without qualifier 22, which the engine refuses; the GS1 Company Prefix of an identifier is read after the
indicator digit (GTIN-14, ITIP), the extension digit (SSCC) or the filler zero (GRAI); users created before
roles are administrators; one gunicorn worker with threads, because sign-in lockout and background jobs
live in memory.

## Session 3 — "Expansion Pack": hardening and data attributes

The fork got its public name, *GS1 Digital Link Resolver CE — Expansion Pack*, and the README stopped
naming an organisation or a maintainer: third-party installations must not be associated with any GS1
organisation. The operator shown on each installation comes only from its `.env`.

| Commit | Change | Why |
|---|---|---|
| `d4e5584`, `e99fc21` | README title; credits without the maintainer | neutrality of the published project |
| `9d12f9d` | import limits per format shown in the dialog; a huge CSV cell no longer causes an error 500 | users must know the limits before uploading |
| `1b58bfd` | special characters: ASCII digits only, invisible characters removed, NFC text, safe addresses, formula protection in exports, UTF-16 import, safe logging | text copied from documents and spreadsheets carries invisible and look-alike characters |
| `3f1ff37` | installer passwords with special characters | |
| `b33def6`, `92bfb5d` | level names on the HTML linkset page; only `http(s)` targets are links | clarity; the API accepts any `href`, so `javascript:` must never become a link |
| `13dbf05` | extensions documentation rewritten for every key and qualifier | |
| `289822d` → `764e360` | operator footer removed, then restored | the operator's name was already configurable, so it could stay |
| `cc72145` | operator's name linked to `RESOLVER_ORG_URL` (`contact.hasURL`) | |
| `4b42c6f` | **data attributes** (§4.10) in QR codes, validated by the GS1 Barcode Syntax Engine 1.4.1 (C library + Python binding built in a Docker stage) | GS1's own engine instead of re-implementing hundreds of AI rules; attributes are never stored |
| `1525f82` | QR version and error correction, HRI modes, attribute combo box, show-password button | artwork needs a fixed size; the native list failed on phones |
| `1746f19` | label block under the form at every width | chosen between two mock-ups (B) |
| `e71384d` | decimal families (310n, 392n…), no limit of 10 attributes | people type `1,5 kg`, not `3103=001500` |
| `08570e4`, `cf5ce10` | other records of the same key under *Open record*; 216 Portuguese AI names; localised association errors | a GTIN with dozens of batches needs a list; names in the user's language |

Each feature with a visible layout was first shown as mock-up images produced from the real portal and
approved before implementation. Screenshots in the README are regenerated by a script, with the GS1 logo
hidden.

## Session 4 — search by key type and qualifier; documentation

| Commit | Change |
|---|---|
| `f4f3071` | record list filters by primary key type and key qualifier, with counts; a pasted GS1 Digital Link or bracketed element string finds the exact record and the related ones |
| `d11c369` | "one other record" in the singular under *Open record* |
| `52a1087` | docstrings for every function written for the fork; map of `app.js` |
| documentation | [portal user guide](portal-user-guide.md) with screenshots, [features](features.md), this history, [developer guide](developer-guide.md), documentation index, README |

"Key attributes" in the request was read as the key qualifiers of the standard: data attributes are never
stored, so they cannot be filtered.

## How the main areas evolved

| Area | 1.0.0 (session 1) | Now |
|---|---|---|
| Identification | GTIN + optional batch | 16 primary keys and 9 qualifiers, with the combinations of the standard |
| Labels | PNG/SVG, HRI on/off, optional branding | HRI full/key/none, QR version and correction, data attributes, no branding |
| Finding records | open one GTIN at a time | record list, text search, filters by key type, qualifier, author and link problems, code search, other records of a key |
| Bulk work | none | XLSX/CSV export and two-step import |
| Quality of targets | none | link checker in the editor, for every record and on import |
| Accounts | users from the command line, all equal | roles, prefixes, users screen, temporary passwords, history, audit trail |
| Installation | manual, with a patch | git fork, layered configuration, Ubuntu installer, backup |
| Tests | 69 checks | 739 checks in 11 test programs, plus the installer test |
| Documentation | README of the package, handover | README, user guide, features, history, developer guide, extensions documentation, changelog |

## Decisions that stay unless deliberately revisited

1. Official variable names and behaviour are kept; deliberate changes are documented in the changelog.
2. No instance values in the code: domain from `FQDN`, operator from `RESOLVER_ORG_*` / `RESOLVER_CONTACT_*`.
3. The portal is the back end between the browser and the API; the token never reaches the browser.
4. Validation mirrors the GS1 Barcode Syntax Engine; deliberate limits are documented.
5. Resolver: an unknown `linkType` is a 404 (required by the standard); walk-up serial → batch → variant →
   key; query strings are passed on unchanged and never judged.
6. Roles reader < editor < admin are checked on every call; GS1 Company Prefixes limit every screen.
7. Portal files (`users.json`, `secret.key`, `records-meta.json`, `journal.jsonl`) live in the
   configuration volume and are in the daily backup.
8. Labels: X = 0.495 mm, 2.2 mm text, 4X quiet zone; error correction exactly as chosen; no GS1 branding.
9. Data attributes go only into the QR code and are validated by GS1's engine.
10. One gunicorn worker with threads.

## Lessons learnt

- Test with data created by other tools; official example records exposed assumptions.
- nginx resolves upstream names at start-up: the proxy must restart when a service is recreated.
- `docker compose restart` keeps the old environment; use `up -d` after editing `.env`.
- The syntax engine refuses some combinations the URI grammar allows (22 on ITIP): check with the engine.
- The GS1 §4.10 grammar has a typing error (`shipToaAdd…` for (4302)/(4303)).
- Check claims against the code before documenting them.
- Show layouts as images before building them.

## Open items

- Security notice to the official maintainers about the public `GET /api/index` (drafted).
- Rotation of the development secrets of the staging installation (an installer option is a candidate).
- A fresh installation with `scripts/install.sh` on a clean machine (only the re-run path is proven).
- A recorded run of the GS1 conformance test suite against the staging resolver.
- An off-server backup copy and a restore rehearsal.
- Review of the 216 Portuguese AI names; decision on the GS1 logo on the home page and resolver pages.

Candidate next steps: reading raw scanner data (FNC1/GS) in the code search through the syntax engine,
exporting only the filtered records, copying targets between records, label size choice and PDF export,
single sign-on, journal rotation, health monitoring, CI with the development tests, and small pull
requests to the official project.
