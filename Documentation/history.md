# History of the Expansion Pack

How the GS1 Digital Link Resolver CE — Expansion Pack grew from the official GS1 Resolver CE v3, session
by session, with the decisions taken on the way and why. The day-by-day list of changes is in
[extensions/CHANGELOG.md](extensions/CHANGELOG.md); what each feature does today is in
[features.md](features.md).

The work was done in six working sessions between 22 September and 2 October 2026, against a staging
installation of the resolver run by the maintainer. Every increment was tested on that installation before
the next one started.

## Timeline

| Session | Dates (2026) | Delivery | Result |
|---|---|---|---|
| 0 — starting point | March | official commit `bf885fd` | GS1 Resolver CE v3, data entry by JSON API only |
| 1 — portal 1.0.0 | until 23 Sep | zip package with a patch for the official code | portal for GTINs and batches, conformance fixes, labels, backup |
| 2 — the fork | 25–29 Sep | 21 commits, `d51e398` → `7e7a62a` | fork with git history, installer, every key and qualifier, spreadsheets, link checker, governance |
| 3 — Expansion Pack | 29–30 Sep | 22 commits, `d4e5584` → `cf5ce10` | special characters, data attributes, QR options, new editor layout, other records of a key |
| 4 — search and documentation | 30 Sep – 1 Oct | `f4f3071` and the documentation commits | filters by key type and qualifier, code search, user guide, feature list, this history, developer guide, docstrings, Portuguese version |
| 5 — conformance review and 2.5.9 | 1 Oct | `324d85b` → `db8e342` and the documentation commits | clause-by-clause conformance review, registration model of Resolver 2.5.9 (informative batch and variant of a serial number), a default link above every record, resolution fixes (item 1.5) |
| 6 — EPC binary strings | 2 Oct | `51a0da8` → `4b9a7be` and the documentation commits | `/eh…` and `/ex…` decompressed for every EPC scheme with a GS1 Digital Link (item 1.6), from the TDT 2.2 artefacts and TDS 2.3; the proxy's upstream name fixed (every resolution through nginx had been a 500 since 1.5); four more candidate errata; confirmed on staging |
| 7 — GS1's resolver test suite | 2 Oct | `bc573c4` → `386a8c3` | GS1's own suite passes on staging (31 of 31), link types published in `https://ref.gs1.org/voc/` (F22), erratum E12, open backlog in the README |
| 8 — backlog, quick wins, CI | 13 Oct | `bc1c86b`, `1a1ca59`, `d68a883` and the documentation commits | backlog reordered around tenants, e-mail, API keys and custom domains; 30-minute idle session with a warning and a 12-hour limit; syntax box removed from the home page; community notice; development tests through pytest and on GitHub Actions |
| 9 — architecture for scale | 13 Oct | ADR 0001, then three code deliveries (`d783f3d`, `a072e9d`, `20f3304`) and the documentation commits | item 2.3: the portal's state in MongoDB, background jobs in a worker service, replicas of every stateless service behind a proxy that finds them by itself; gunicorn in every web service; nginx 1.30 |
| 10 — tenants | 13 Oct | ADR 0002, then two code deliveries (`1590b7e`, `675b6ca`), the documentation commit and a fix (`7c10048`) | item 2.4: organisations that own GS1 Company Prefixes, the server administrator, support access, an audit trail per organisation, an e-mail address per user |
| 11 — one source for the GS1 rules | 13 Oct | ADR 0003, then three code deliveries (`8e3d9c7`, `6f6ce19`, `e7c5a6d`) and the documentation commit | item 2.5: one engine release for every service, keys, qualifiers and formats from the GS1 Barcode Syntax Dictionary, the engine's messages translated, a weekly update check |
| 12 — e-mail and the tenant API | 14 Oct | ADRs 0004 and 0005, an installer fix (`f3d127d`), four code deliveries (`03c924b`, `fbe86f0`, `bb0b496`, `c469f29`) and two documentation commits | item 3.1: mail through an authenticated relay, invitations, password recovery by single-use link, security notices and notices of finished jobs with per-user preferences; item 3.2: a versioned API for organisations' systems with API keys |
| 13 — the request log | 14 Oct | ADR 0006, two code deliveries (`d633fcb`, `7b8967a`) and the documentation commit | item 4.1: every resolution request recorded by the resolver without personal data, daily counts per key, a Requests screen, the tenant API's calls recorded |

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
1.0.0 contents were rewritten as seven topic commits so that each can be reviewed on its own.

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
| documentation | [portal user guide](portal-user-guide.md) with screenshots, [features](features.md), this history, [developer guide](developer-guide.md), documentation index, README; then all of it in Brazilian Portuguese, with screenshots in Portuguese (removed on 14 October) |

"Key attributes" in the request was read as the key qualifiers of the standard: data attributes are never
stored, so they cannot be filtered.

## Session 5 — conformance review and the registration model of 2.5.9

| Commit | Change |
|---|---|
| `324d85b`, `b2bda36` | [conformance review](conformance-review.md) of the branch against URI Syntax 1.7 and Resolver 1.2.1: 23 findings, 7 candidate errata, staging results; backlog items 1.5 (resolution fixes) and 1.6 (EPC binary) proposed |
| `61babe1` | data entry API refuses registrations against 2.5.9 and keeps `informativeQualifiers`; the resolver prefers a serial-number record to a batch record |
| `83d1ba0` | portal: the batch and variant of a serial number are informative (approach C of the mock-ups), *This record applies to*; server side of the key's own record |
| `3a49ca9` | portal: dialog offering the key's own record when saving, *Status* filter and alert, import of keys without a record, *Copy targets from…*, confirmation on *Open record* |
| `4f81234` | resolver and proxy (item 1.5): default response and `gs1:defaultLinkMulti`, choice of a link (examples 5-13), request paths checked by the engine's Digital Link parser, `%2F` in values, raw query string, 400 instead of 500, 300 as a linkset, JSON-LD in HTML, description file |
| `db8e342` | portal (item 1.5): the per-target query-string option removed; `RESOLVER_TERMS_URL` |

Decisions of the owner: the per-link option to stop forwarding the query string is to be removed (item
1.5, F14); a serial number's batch and variant stay in the database as information, not only in the QR
code, so that they can be searched, filtered and exported; the key's own record is offered, with the same
targets preselected.

## Session 6 — EPC binary strings

| Commit | Change |
|---|---|
| `51a0da8` | `epc_binary.py`: EPC binary strings decoded to GS1 Digital Link — schemes before TDS 2.0 entirely from the TDT 2.2 artefacts (now in `web_server/src/tdt/`), `+` schemes with Table F and their +AIDC data, `++` schemes with their hostname; `test_epc_binary.py` checks every vector of TDS 2.3 annex E.3 and 800 random EPCs against the `epc-tds` library |
| `b9a7631` | proxy: the upstream `resolver_web` of item 1.5 renamed `resolver-web` — Werkzeug refused the underscore in the Host header, so every resolution through nginx was a 500 on staging since 1.5; `test_home.py` now checks the Host header |
| `895c4b1` | resolver: `/eh…` and `/ex…` resolved as the decompressed GS1 Digital Link (F6, rest of F7); data attributes checked by the engine and passed on; 400 when a string does not decode |

Decisions of the owner: the decoder covers every scheme at once (classic, `+` with +AIDC data, `++`); key
qualifiers carried by a tag go to the path and data attributes to the query string passed on to the target;
the hostname inside a `++` EPC is ignored and the resolver keeps its own stem. The implementation reads the
TDT artefacts (no scheme-specific code for the classic schemes) rather than using the `epc-tds` library,
which knows only part of the classic schemes and none of TDS 2.0; `epc-tds` serves as an independent check
in the tests.

Staging (2 October, through the proxy): a registered GTIN `/01/…` → 307; the same GTIN as SGTIN-96 in
`eh` and `ex` form → 307 to the same target; an SGTIN+ with +AIDC batch 123 and expiry date → 307 to the
batch record's target with `?17=261231`; a GID-96 → 400 with its reason. The first attempt answered 500
everywhere: that is how the upstream-name defect of item 1.5 came to light.

Candidate errata found by decoding: E8 (EPCB 4.2.2), E9 (TDS 2.3 annex E.3: SSCC++ and ITIP++ headers,
SGTIN++ and DSGTIN++ hostnames, an EPC URI), E10 (TDS 2.3 Tables 14-14 and 14-15), E11 (TDT artefact of
CPI-var) — section 6 of the conformance review.

## Session 7 — GS1's resolver test suite (item 1.4)

| Commit | Change |
|---|---|
| `bc573c4` | resolver: linksets and the JSON-LD context write `gs1:` link types in `https://ref.gs1.org/voc/` (Resolver 2.14, F22); stored documents unchanged |
| `cc95d77` | `test_gs1_suite.py`: GS1's resolver test suite, its JavaScript unchanged, in Chromium against the resolver code, with a Python version of its PHP helper; seven scenarios |

The suite's code was read and run in the sandbox before the owner ran it on staging. Staging (2 October,
`ef96276`, a GTIN with a default link in Portuguese and English and instructions in both): **31 of 31
tests pass**. In the sandbox one divergence remains, which staging does not exercise: under a batch with its
own default link, the suite expects the GTIN's language variants of the default (erratum E12; the resolver
keeps the batch's default). After `bc573c4` was installed: 31 of 31 again, link types in
`https://ref.gs1.org/voc/`, and the F9-F13 checks of the conformance review all as expected (307 to the
default link, 400, 400, 307 walking up with `%2F`, query string passed on as sent). The GTIN of the usual
deployment check answered 404 at the same time: its record had been deleted on staging, and a valid GTIN
without a record is a 404 (2.4.1). The open backlog is now listed in the README.

Decisions of the owner: link types are published in `https://ref.gs1.org/voc/` (option B of F22); the
behaviour under E12 is kept and becomes an erratum and an issue for the suite.

## Session 8 — backlog reordered, quick wins (item 2.1), continuous integration (item 2.2)

| Commit | Change |
|---|---|
| `bc1c86b` | README backlog rewritten from the owner's notes of 13 October: quick wins, architecture for scale with the portal's data in MongoDB, tenants with server and tenant administrators, e-mail, a tenant API with API keys, analytics per tenant with export, the tenant's own domain in the QR code, Verified by GS1 on the landing page, a load test |
| `1a1ca59` | portal: session ends after 30 minutes without use and 12 hours after the sign-in, warning two minutes before, renewal while the user works, shared between tabs; home page without the GS1 Digital Link syntax box; community notice in the README, the documentation and the footers; `test_session.py` |
| `d68a883` | continuous integration (item 2.2): `dev-tests/test_programs.py` runs every test program through pytest, by group, with a strict mode; workflow `.github/workflows/dev-tests.yml` with five parallel jobs and a set-up action that pins every version; the empty `main.yml` removed; status badge |

After a pause from 2 to 13 October the fork, the official project and GS1's suite had not changed. The
owner's notes were assessed one by one: all were kept, some merged with existing items. The order puts the
portal's data store and tenants before the API, e-mail and analytics, because all three need to know whose
data they handle. Two notes were narrowed: the Verified by GS1 link goes on the landing page only, since the
link type `gs1:verificationService` denotes a GS1 Lightweight Messaging service, not a web page; and a
tenant's own domain answers only for that tenant's prefixes, after a DNS proof that the domain is theirs.

Decisions of the owner: the notice names no organisation ("not by GS1 or any GS1 Member Organisation");
the session ends after 30 minutes without use, with a warning two minutes before and a 12-hour limit per
sign-in, both configurable.

Building the portal's syntax engine in the sandbox: the release archive could not be downloaded there, so
the same tag was cloned with git and built with the script's steps (the script itself is unchanged).

Continuous integration (item 2.2). The owner's decisions: a thin pytest layer over the existing programs
(not a rewrite of their checks); five jobs in parallel; every job required except the portal in Chromium and
the installer, which start as informative; a status badge in the README. Before the workflow was written the
baseline was run again (`a6be2ad`: 194 and 215 checks, then every program), and the layer was proved able to
fail: a deliberate change to the link checker made two checks fail and the layer reported them. The setup
steps were also run with Python 3.12, a clean cache folder and the pinned npm versions, as on a runner: every
program passed. The installer test, which needs root, was run as an ordinary user with password-less sudo.
The run logs of GitHub Actions need a sign-in, so the first results come from the owner.
The first run (Development tests #1, on `c7ca3aa`) was green in every job in 5 minutes 42 seconds, without a
cache, and every program reported the same check counts as in the sandbox.

## Session 9 — architecture for scale and the portal's data in MongoDB (item 2.3)

The fork, the official project and GS1's suite were unchanged since session 8; the baseline passed (1,143
checks in 14 programs, as in CI). Reading the portal confirmed where its state lives and found more of it in
memory than expected (import previews, the latest full link check, the link checker's cache). It also showed
that the official resolver and data entry services run Flask's built-in server and that every Compose
service has a fixed container name, which Compose cannot scale; both are left to step 4.

The owner decided the eight points of the item, all on the recommended options: a database of the portal's
own with a least-privilege user; background jobs in a MongoDB collection run by a worker container; sign-in
failures and caches in collections with TTL indexes; the session key in `.env`; journal retention by age
per category; automatic migration at start-up; `mongomock` in the test programs plus a CI job against a
real MongoDB; four deliveries. They are recorded in
[ADR 0001](adr/0001-portal-state-in-mongodb.md) (step 1).

| Commit | Change |
|---|---|
| `f9c38a2` | docs: the "How the main areas evolved" heading restored in both histories (lost in a session 8 documentation commit) |
| `076f19a` | ADR 0001 in English and Portuguese (step 1) |
| `d783f3d` | step 2: `store.py`, users, record metadata, journal with retention, sign-in failures and caches in MongoDB; `migrate.py`; `db_init.py` and the `portal-db-init` service; the installer generates `PORTAL_DB_PASSWORD` and `PORTAL_SECRET_KEY`; `test_store.py`, `test_store_mongodb.py` and the CI job on a real MongoDB |
| `d7644b1` | docs: step 2 in the changelog, features and histories |
| `a072e9d` | step 3: `jobs.py` and `worker.py`; imports and link checks as jobs; the `portal-worker` service and `PORTAL_WORKER`; queue, "not running" and failure messages in the browser; `worker` in the health check and in the installer's checks; `test_jobs.py`, `test_worker_processes.py`, e2e and installer scenarios |
| `f1e4577` | docs: step 3 in the changelog, features and histories |
| `20f3304` | step 4: replicas (`deploy.replicas` from `.env`, no fixed `container_name` on the replicable services); gunicorn in the resolver and the data entry API, `WEB_CONCURRENCY` processes everywhere; nginx 1.30 with `resolve` in every upstream; the portal's fallback session key safe under concurrent starts; replica counts in the installer; e2e and installer jobs required; `test_deploy.py`, replicas in `test_home.py` and `test_install.sh` |
| `c426dfd` | docs: step 4 in the changelog, features and histories |
| `3298da7` | dev-tests: every nginx temporary folder in the proxy test's work folder (the first CI run on nginx.org's nginx) |

Step 2. Three details changed while it was built, and ADR 0001 was brought in line: the portal's user is
made by a Python script in the portal's image (`db_init.py`), so that CI can run the same script against a
real MongoDB; the rule that keeps the last administrator runs under a lock document shared by every process,
because a standalone MongoDB has no multi-document transactions; and journal retention counts whole days
from the end of an event's day, which lets a changed value be applied one day at a time (mongomock cannot
compute dates in an update). The development sandbox cannot download MongoDB, so the programs run on
mongomock there and on a real `mongo:7` service container in CI; the CI job starts as informative. A
deliberate mutation (no lock around the changes of users) first passed the concurrent-removal check, since
mongomock rarely interleaves the two threads; a deterministic check (a change waits while another process
holds the lock) was added and catches it. Step 2 was confirmed on staging (2 users, 3 record metadata entries
and 55 journal events migrated) and the CI job on a real MongoDB passed its 76 checks at its first run.

Step 3. The owner settled the four open points on the recommended options: `PORTAL_WORKER=external`
(the `portal-worker` service, always in Compose) or `embedded` (a thread of the portal, for the tests and a
set-up without the service); an interrupted import continues from the first record not written; one worker
until step 4; no cancel button for now. The implementation added, and ADR 0001 now records: a limit of
three attempts per job, so a job that kills its worker cannot loop; writes conditional on the job still
being the worker's (`JobLost`); an immediate hand-back on SIGTERM; worker announcements, so the browser can
say that no worker is running instead of waiting in silence, and the health check and the installer can
report it; a link check that starts again rather than continuing (its cache answers what was done). The
programs that run imports use the embedded worker; `test_jobs.py` drives workers directly, and
`test_worker_processes.py` starts `worker.py` as processes sharing a queue, which needs a real MongoDB: it runs
in the CI job "database". In the sandbox it was also run against FerretDB (a MongoDB-compatible server on
SQLite, downloaded from GitHub) with TTL indexes switched off: it passed, and a deliberate mutation (claiming
running jobs too) failed three of its checks. Step 3 was confirmed on staging: the worker announced itself,
the health check reported it, *Check links* and an import of the exported spreadsheet finished, a check
waited with the "not running" warning while the worker was stopped and completed once it was started again;
the CI run of `f1e4577` was green in all six jobs (161 checks on the real MongoDB).

Step 4. The owner chose, all as recommended: nginx 1.30 finding replicas by itself; gunicorn in every web
service; replica counts in `.env`, one of each by default; the e2e and installer jobs required now, the
real-MongoDB job informative a little longer. Only the three replicable services that had a fixed container
name lost it; the database and the proxy, which cannot be replicated, keep their official names. Reading the
configuration showed that the plan of the ADR (nginx looking the names up at start-up, restarted by Compose
when a service is recreated) would serve replicas that existed when the proxy started but never one added
later, and that `--scale` is forgotten at the next update; hence `resolve` in the upstream blocks, which
needs nginx 1.27.3 or later and moved the proxy image from 1.25.1 to the 1.30 stable branch, and the counts
in `.env`, which the installer now writes. Running several gunicorn processes exposed a race in the portal's
fallback `secret.key` (a process could read the file another had created but not yet written, and sign
sessions with an empty key): the key is now written under another name and linked into place. Concurrent
starts of six processes did not reproduce the race; a deterministic check (eight threads asking while
writing the key is slow) fails on the earlier code and passes now. The proxy test runs the real
configuration on nginx 1.30 (built from source in the sandbox, from nginx.org in CI) with a small DNS server
of its own that answers the service names with replicas on `127.0.0.x`, and `test_deploy.py` starts each
image's gunicorn command. A rehearsal in the sandbox put two gunicorn replicas of the resolver and of the
data entry API behind that proxy: requests were shared evenly; the records themselves could not be stored,
because FerretDB refuses keys containing a dot, which the official records use.

Step 4 was confirmed on staging: after a backup and the four replica counts set to 2 in `.env`, `docker
compose up -d --build` replaced the containers with fixed names by two of each service
(`gs1_digitallink_resolver_ce-web-service-1`, `-2`, …) beside the single `database-server` and
`frontend-proxy-server`; the health check, both resolutions through the proxy and the two worker
announcements were as expected; twelve resolutions were shared six and six between the two `web-service`
replicas; in the browser, signing in, moving between screens across replicas, saving a product and a batch,
export, import and redirection all worked; GS1's resolver test suite passed again against the resolver now
running under gunicorn. The first CI run of `c426dfd` was green except the proxy test, which stopped before
its first check: nginx from nginx.org's package keeps its temporary folders in `/var/cache/nginx`, which the
runner's user cannot create; the test now keeps every temporary folder in its work folder (`3298da7`).

## Session 10 — tenants (item 2.4)

The owner started the session and left it to run while away, asking for the recommended option on every
question. The fork was at `fd8f67c` and the baseline passed (1,350 checks outside the browser and 366 in
it, as in CI). Reading the portal showed that one function, `allowed()`, already stood between every route
and the records: limiting it to the tenant of the request would limit everything at once.

The nine points of the item were settled on the recommended options and recorded in
[ADR 0002](adr/0002-tenants.md) (step 1): a `tenants` collection with one tenant per user; the operator's
administrators as server administrators, with no new role; read-only support access with a reason, recorded in
the tenant's trail; overlapping prefixes refused; nothing migrated (today's users become the operator's, who owns
whatever no tenant holds); ownership derived from the prefix; a `tenant` field on journal events; an optional,
unique e-mail address; three deliveries. The operator as owner of the unassigned prefixes is what lets an
installation update without any change: until the first tenant exists, every rule gives today's answer.

| Commit | Change |
|---|---|
| `4bb39cd` | docs: ADR 0002 in both languages (step 1) |
| `1590b7e` | step 2: `portal/tenants.py`; users with tenant and e-mail; `set_scope()` and `allowed()` by owner; the worker's check before each imported record; journal, history, record metadata and the last full link check per scope; tenants and support API; `create_user.py --tenant --email`; `test_tenants.py` |
| `675b6ca` | step 3: Organisations screen, support access and its banner, organisation and e-mail in Users, organisation in the account menu and the audit trail; translations; e2e; user guides and images |

Every protection of step 2 was mutation-checked: twelve changes to the code (ownership left out of `allowed()`,
another tenant's users manageable, overlaps accepted, the worker's check removed, the operator's view of the
audit trail widened, metadata shown to every scope, disabled tenants still signing in, support access able to
write, tenant administrators counted as the last server administrator, a tenant user's prefixes unchecked, the
History panel and the journal query without the tenant) each make `test_tenants.py` fail. The new queries also
ran on FerretDB, as far as its known gaps allow. Mock-ups could not be shown before the screens were built, as the
owner usually asks: the images of the finished screens (those of the user guide) were delivered for review before
the update reaches staging. Not yet confirmed on staging nor in CI.

Before the update was delivered, the deployment test of session 11 found that `portal/Dockerfile` copied the
portal's modules by name and left out `tenants.py`: the portal of `1590b7e` would not have started in a container.
The image now copies every module, and `test_deploy.py` starts the portal from the files the image would hold
(`7c10048`).

## Session 11 — one source for the GS1 rules (item 2.5)

Still with the owner away, and with item 2.4 not yet pushed, the owner asked to go on with the next item on top of
it, to be delivered together. The portal's GS1 rules were written three times (Python, JavaScript, and the
tests' comparison with the engine), the resolver and the data entry API installed whatever engine release was
newest at build time, and the engine's refusals reached the Portuguese interface in English.

The four questions of the item were settled on the recommended options and recorded in
[ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md): the rules generated from the dictionary into a committed
file checked by a test, so the portal also works without the engine; one release in `docker-compose.yml`; every
message of the pinned release translated, with a test; a weekly job that opens an issue rather than a pull request.

| Commit | Change |
|---|---|
| `8d50280` | docs: ADR 0003 in both languages (step 1) |
| `7c10048` | deploy: every portal module in the image (the fix of item 2.4 above) |
| `8e3d9c7` | step 2: `x-gs1-syntax-engine` in `docker-compose.yml`, a build argument for the five services, the pinned `gs1encoder` in the official images, the build script and CI reading the same value; `test_deploy.py`, `test_keys.py` check it |
| `6f6ce19` | step 3: `gs1_dictionary.json` and its generator, `gs1dict.py`, `gs1.py` built from it, the browser's rules from `/config`, the comparison for the weekly issue, the weekly workflow; `test_dictionary.py` |
| `e7c5a6d` | step 4: the engine's message table and recogniser, the 211 messages in both languages, Portuguese names for (7041) and (8040)–(8043); `test_engine_messages.py` |

The tables built from the dictionary were compared with the hand-written ones before replacing them: the only
differences were the way two keys' shapes are written (417 and 8004, which accept the same records) and the
qualifiers' internal names. The comparison for the weekly issue was tried on the real dictionaries of 1.1.0 and
1.4.1 (it shows (7041) and (8040)–(8043) added and, the other way round, that the portal could not build its rules
from the older dictionary). Every new test was mutation-checked (three changes for the release, five for the
dictionary, eight for the messages). The GitHub API could not be reached from the sandbox, so the weekly
workflow's first real run will be on GitHub. Not yet confirmed on staging nor in CI.

## Session 12 — e-mail (item 3.1) and the tenant API (item 3.2)

The owner still could not reach the workstation or the server to apply the cumulative bundle of items 2.4 and 2.5,
and asked to go on with the next item and deliver everything in one bundle from `fd8f67c`, taking the recommended
option on every question. He sent the bundle of sessions 10 and 11 into the chat; the baseline on top of it
matched the end of session 11 exactly (1,904 checks).

Every question of [ADR 0004](adr/0004-e-mail.md) was settled on the recommended option: SMTP submission to a relay
the operator chooses (587 STARTTLS or 465 TLS, port 25 being blocked on Azure), settings in `.env` and mail off
without them; messages as jobs of the existing worker with retries; single-use links stored as hashes, with the
token in the fragment of the address; invitations by default when there is an address; recovery with the same
answer for everyone; security notices always and job notices on request, in the user's language; texts in the
code; Mailpit in a compose profile for trying it; three deliveries.

| Commit | Change |
|---|---|
| `a0ccc6a` | docs: ADR 0004 in both languages (step 1) |
| `f3d127d` | install: no setting written twice in `.env` on a re-run (an older defect found by the relay's test) |
| `03c924b` | step 2: `mail.py`, `mailtexts.py`, `tokens.py`, `notify.py`; the `mail` job and `notBefore`; recovery, links, invitations, resets by link, notices and preferences in `app.py`; the installer's relay step; Mailpit; `test_mail.py` with an SMTP relay of its own |
| `fbe86f0` | step 3: the sign-in page's recovery and link forms, the invitation on the users screen, Options → E-mail, the user guides' images; `test_mail_e2e.py` |

Writing the installer's test for the relay showed that a re-run wrote `FQDN`, `TLS_MODE`, a replica count and two
more settings twice in `.env`, the old value last, so a change made through the installer did not take effect: the
check of the managed keys looked for the name followed by a space, and the names at the end of a line of the list
are followed by a line break. Fixed in its own commit with a check that no key appears twice. The browser test of
the link page found that a link pasted into an open sign-in page changes only the fragment and does not load the
page again; the page now listens for it. All 16 protections of the server and the removal of the token from the
address bar were mutation-checked; one mutation (a disabled account's link accepted) escaped at first and got its
check. Mailpit's image cannot be pulled in the sandbox, so its first run is on staging. Not yet confirmed on
staging nor in CI.

**Item 3.2, the same night.** With item 3.1 delivered, the owner asked to go on with the next item, and decided
that the commits not yet pushed should name Claude as author with himself as co-author (until then he was the
author and Claude the co-author). The fifteen commits from `fd8f67c` were rewritten in order: each commit's
documents had the hashes of the earlier rewritten commits replaced, which worked because no commit cites a later
one (checked first); the result differed from the old tree only in those hashes (94 lines). From then on commits
are made that way.

Every question of [ADR 0005](adr/0005-tenant-api.md) was settled on the recommended option: the API served by the
portal at `/portal/api/v1`, so every rule applies unchanged; keys owned by organisations and created by their
administrators (a server administrator only for the operator's records); `rk_<id>.<secret>` shown once, only the
SHA-256 stored; scopes, optional prefixes, a required validity; a request limit per key in MongoDB; key creation
and revocation journalled, changes as record events of `api:<id>`; e-mail when a key is created and before it
expires; a hand-written OpenAPI 3.1 description checked by a test.

| Commit | Change |
|---|---|
| `326566d` | docs: ADR 0005 in both languages (step 1) |
| `bb0b496` | step 2: `apikeys.py`, `api_v1.py`, `openapi.json`; key endpoints, `remove_record()` and `label_response()` shared with the API, the expiry notice and the worker's hourly housekeeping; `test_api.py` |
| `c469f29` | step 3: the API keys screen and its images, the menu fix, the user guides; `test_api_e2e.py` |

All sixteen protections of the server were mutation-checked; one mutation (the expiry notice taken again) made
`expiring()` loop for ever, which the test cannot pass, but it stopped the mutation script with a timeout. The
browser test found two defects before delivery: one message key written twice in the catalogue (the column heading
"Created" replaced the message "Key … created"), now refused by a test, and a new key left in the page after
leaving the screen, now removed. Not yet confirmed on staging nor in CI.

## Session 13 — the log of resolver requests (item 4.1)

The owner still could not reach the workstation or the server, and asked to go on with the handover and deliver one
bundle with everything since `fd8f67c`, taking the recommended option on every question. He sent the bundle of
session 12 into the chat; the baseline on top of it matched the end of session 12 (1,743 checks without a browser,
465 in Chromium).

Every question of [ADR 0006](adr/0006-resolver-request-log.md) was settled on the recommended option: the resolver
records each request itself, after answering, from what the resolution knows; nothing that identifies the client
(no address, not even hashed; no User-Agent, only a device class; only the referrer's host; only the AIs of serial
numbers and data attributes); a bounded queue and a writer thread per process; a database of its own,
`resolver_log`, readable by the portal's user, with an expiry per event (90 days); daily aggregates per key by the
worker in the installation's time zone (800 days); ownership derived from the company part at query time; server
administrators see the whole installation; the tenant API's calls recorded by the portal; three deliveries.

| Commit | Change |
|---|---|
| `e519771` | docs: ADR 0006 in both languages (step 1) |
| `d633fcb` | step 2: `web_server/src/request_log.py` and the resolver's hooks; the read role in `db_init.py`; `portal/requestlog.py` (scope, listing, aggregates in the housekeeping, API calls); the portal's endpoints; the backup without `resolver_log`; the installer's time zone; `test_request_log.py`, `test_requestlog.py` |
| `7b8967a` | step 3: the Requests screen and its image, the user guides' section 16; `test_requests_e2e.py` |

The resolver's answers had to stay exactly as they were, while the log needs two facts only the resolution knows:
the level of the record that answered and why a 404 happened. `web_logic` returns them in private keys of its
results, which `web_namespace` removes before answering; the tests compare the 404 and 300 answers with the official
shape. mongomock deletes documents whose TTL date has passed when they are read, so a log switched off by an expiry
of zero days looked empty either way: the mutation "switch ignored" escaped until the test also counted what the
writer wrote. Another escaped mutation showed a test that searched for an escaped pattern, which matches the same
nothing with or without escaping. The browser test found the new menu item left out of the list of items that close
the menu. 26 mutations, all caught.

**Tests on staging, 14 October.** The owner applied the bundle on the workstation and on staging and followed a test
plan covering everything since `fd8f67c` (sessions 10 to 13). CI was green in every job. Two findings were not in the
code: `.env` held three settings twice from before the installer fix of session 12 (`f3d127d` stops new duplicates
but does not remove old ones), removed by hand; and the weekly engine check failed because a fork on GitHub has
Issues switched off by default (Settings → Features → Issues), after which it ran green. Organisations, the GS1
rules, e-mail, the tenant API and the Requests screen worked as described. The daily backup failed: `d633fcb` left
`resolver_log` out with `--nsExclude`, an option of `mongorestore` that `mongodump` does not have, and the script
stopped without a message of its own, leaving a partial file. `c1b3f78` puts the log back in the backup (it is small
and bounded by its expiry), reports `ERROR`, removes the partial file, and `test_deploy.py` now runs the script with a
stand-in `docker` and checks the dump's options (62 checks).

**Backlog, 14 October.** The owner removed item 4.4, a weekly summary by e-mail per organisation, from the open
backlog. No item depended on it, so nothing else moved; item 4.3, monitoring and alerts by e-mail, stays.

**Documentation in English only, 14 October.** The owner dropped the Brazilian Portuguese documentation
(`Documentation/pt-BR/`, the six ADRs in Portuguese and the Portuguese screenshots of the user guide): keeping every
document in two languages doubled the work of each delivery, and readers of other languages can use the translation
built into their browser. The portal, the resolver's pages, the home page and the e-mail messages keep Brazilian
Portuguese and British English, as before. The commits and sessions above that mention the Portuguese documents
describe them as they were.

## Session 14 — Claude Code cloud sessions

From 14 October the work moves from a chat project, whose sandbox could not push and delivered bundles for the
owner to apply and push, to Claude Code cloud sessions, which clone the fork and push to `gs1br/develop` themselves.
The owner's handover still opens each session. `CLAUDE.md` now holds the conventions that can be public (language,
commits, documents kept in step, tests), and a session start hook prepares the test environment the CI way; the
whole battery passed in the session before the push. The engine's release tarball is refused by the session's
proxy, so the hook builds the portal's engine from a git clone of the same release (`b9bd4ed`; 1,896 checks without a
browser and 493 in Chromium in the session).

**Item 4.2, the overview** (the owner away, every question on the recommended option; [ADR 0007](adr/0007-overview-indicators.md)).
A new view opened after sign-in, with the editor kept at the portal's address so that bookmarks and the guides stay
right; 7, 30 or 90 days against the period before; usage, resolution quality (the scanned codes nobody registered
first, each one click from the editor), record quality, operation and, for administrators, governance; computed on
request from the daily aggregates and today's raw events; Excel and CSV exports; `/v1/stats` for organisations'
systems with a new scope. Commit `16ceb9f`: `portal/overview.py`, `requestlog.collect()`, `journal.counts()`,
`app.visible_records()` shared with the record list, the view, both languages, `test_overview.py` (66) and
`test_overview_e2e.py` (27). The test of the aggregates first passed for the wrong reason: the embedded worker's
housekeeping at start-up had already marked the past days as finished before the test wrote its events, so the test
now clears that mark; three mutations escaped at first (a compressed link's answer, requests without a key in a code
list, an administrator limited to prefixes seeing others' changes) and the program gained a check for each, 18 of 18
caught. Sign-in landing on the overview changed five browser programs, which now open the editor themselves.

**Item 4.3, monitoring and alerts** ([ADR 0008](adr/0008-monitoring-and-alerts.md), recommended options; the record
went out with the docs commit of 4.2 by mistake, before its code). The worker checks every 5 minutes, one replica at a
time: the resolver through the proxy (two failed rounds), the backup's record, which the backup script now writes in
the portal's database, the certificate once an hour, and spikes of 404 per scope against the usual hour. Messages on a
change only, a daily reminder, a resolved message; category *alerts* on by default. Commit `57a5420`: `portal/monitor.py`,
the worker's second schedule, seven messages, `test_monitor.py` (62, 18 mutations caught), `test_deploy.py` (66: the
backup's record with the stand-in `docker`, and its mongosh script checked by `node --check`). Writing the test found
a defect older than the feature: preferences stored only the categories switched on, which worked for the jobs
category (off by default) but would have made alerts impossible to switch off. The backup test found that the error
text "mongodump failed" matched the stand-in's own pattern for the dump: the record now says "the database dump
failed". The CI job on a real MongoDB failed on `b9bd4ed` (a commit without code) and on `16ceb9f`; its logs cannot be
downloaded from the session (the log storage host is outside the network policy), so the job was run again to tell a
flaky run from a defect. It failed again on that run, and then passed on every run from the docs commit of item 4.3
onwards without a change to the code it tests: a cause outside the branch (an unpinned package or the `mongo:7`
image) that went away. The failed runs' log is still worth a look when the owner can download it.

**Item 5.1, the organisation's own domain** ([ADR 0009](adr/0009-tenant-domains.md), recommended options). Domains in
the portal proved by a DNS TXT record and never un-verified by a DNS hiccup; a default per prefix or a choice on the
label; the resolver recognising a verified direct domain from `X-Forwarded-Host`, removing its stem and refusing other
organisations' keys; the redirect mode left to the organisation's server and checked by the portal; certificates by
`scripts/custom-domains.sh` with the installer's template. Commit `0a6e42a`: `portal/domains.py`,
`web_server/src/domains.py`, the Domains view, the label's option, `test_domains.py` (59), `test_domains_resolver.py`
(29), `test_domains_e2e.py` (20), the host script in `test_deploy.py` (73). 25 mutations, all caught. The tests found
that the check of a direct domain asked for the description file under the stem, where it never is.

**Items 5.2 to 5.4, the label studio** ([ADR 0010](adr/0010-label-studio.md), one record for the three, recommended
options). Sizes as magnifications of both targets, a PDF written by the portal (no new dependency), EAN/UPC beside the
QR code for GTINs of consumer units, every format in a zip. Commit `d60421f`: `portal/linear.py`, the layout of
`portal/label.py` as rectangles and text lines drawn alike in SVG, PNG and PDF, the options in the editor and the
APIs, `test_label.py` (92). The symbols were checked with an independent decoder, zxing-cpp, which the session could
install but the CI does not have: the test keeps the module patterns it read back (UPC-E for every check digit) and
reads EAN-13 (every first digit), UPC-A and EAN-8 with OpenCV, which the CI has. Seven of the first mutations
escaped — parity tables, a zero-suppression rule, the left quiet zone, the linear X at other sizes, keys other than
the GTIN, names inside the zip — and the test gained a check for each: 18 of 18. The X-dimension figures (QR 0.396 to
0.990 mm, EAN/UPC 0.330 mm at 80 to 200 %, 22.85 mm bars) were checked against GS1 UK's and GS1 Canada's guides; a
draft of the General Specifications seen on the way lists other QR figures (0.375/0.625 mm), to be confirmed against
the ratified release.

**Items 6.1 and 6.2, the item's page** ([ADR 0011](adr/0011-item-page.md), one record for both, recommended options).
The resolver's linkset page for browsers became the item's page and a record's default target through a
`gs1:defaultLink` to `?linkType=linkset&view=page`, so a scan is still a conformant redirect and nothing changes for
apps; brands per prefix with logos uploaded to the portal and served by the resolver; clicks through a route that finds
the link again in the record; Verified by GS1 from an installation's URL template, off by default because the
service's address could not be confirmed from the session. Commit `3d59bc2`: `web_server/src/landing.py`,
`portal/branding.py`, the editor's option, the Item page view, the overview's page views and clicks,
`test_landing.py` (58), `test_item_page.py` (67), `test_item_page_e2e.py` (27); 41 mutations, all caught after seven
of the first escaped and the tests gained a check each (the longest prefix, the fallback when no link is in the
visitor's language, a key without Verified by GS1 answering 500, the branding cache, a server administrator's prefix
inside an organisation's, the installation's default for others, a `gs1:defaultLink` that is not the page). Writing it
found three things on the way: an automated client's views and clicks would have made the overview's scans wrong
(they are now logged as plain answers); the key's own record created with a batch would have copied the batch's page
(it gets its own); and the resolver's pages load Google's web fonts, which on a page every scan reaches would tell a
third party about each scan — the item's page now loads none (the other resolver pages are unchanged).

**Item 7.2, production readiness**, the parts that are code (the owner away; recommended options). The backup copies
each run off the server when `BACKUP_COPY_TO` names an rsync destination, and a copy that fails fails the run so that
the monitoring says so; `scripts/restore-rehearsal.sh` restores an archive into a throw-away container of the
database's own image, without network, and sets its counts next to the live ones; `scripts/rotate-secrets.sh` gives
the installer's secrets new values, MongoDB's root password changed in the database first and handed to `mongosh` on
standard input; the installer's final check now tries a scan of GS1's example GTIN through the whole chain and the
portal over the public address; a production checklist. Commit `449edef`: `test_deploy.py` 97, `test_install.sh` 91,
13 mutations caught. What remains of the item happens on the servers: a clean installation, the copy's destination,
a rehearsal, the staging secrets rotated.

**Item 7.4, load test**: the script (`dev-tests/load/load_test.py`, standard library only, an open model of arrivals,
a mix of scans, linksets and item pages, percentiles and thresholds; its User-Agent counted as automated) and the
procedure of the rehearsal; the rehearsal itself needs the staging server. Commit `37c5664`: `test_load.py` (17) against
a stand-in server; a mutation of the percentile's rounding escaped at first and the test gained a check.

**Item 7.3, default titles in the link's language** (finding F21): Portuguese for links in Portuguese, English
otherwise, a typed title kept, the portal's own titles shown empty so that they follow a change of language. Commit
`266dcf3`: `test_titles.py` (11). The rest of 7.3 (the Portuguese AI names, the logo) waits for the owner's review.

**Item 7.1, single sign-on and export limits** ([ADR 0012](adr/0012-single-sign-on.md), recommended options).
OpenID Connect per organisation, the provider chosen by the e-mail's domain, the account matched by e-mail and never
created, password sign-in off per organisation but never for server administrators (so that a provider that is down
locks nobody out for good), the client secret write-only in the portal's database rather than encrypted with the
session key (whose rotation would have broken every configuration silently); and `PORTAL_EXPORT_LIMITS` per role.
Commit `732b5c0`: `portal/sso.py`, the Organisation sign-in screen, the sign-in page's second form, `test_sso.py` (62) with
a stand-in provider, `test_sso_e2e.py` (17), `test_exports.py` (17). On the way: a throttle first put on the start of
single sign-on would have stopped an office signing in at nine behind one address, and was dropped (nothing secret is
checked there); an empty secret field, as the screen sends it, would have wiped the stored secret (a test caught it
through a mutation and the code keeps it); and the audit trail showed raw codes for eight journal actions of this and
earlier items, now named in both languages and guarded by a test.

**The CI job on a real MongoDB, again.** It failed on one run and its log could not be read from the session; the test
runner now turns each failed program's `FAIL` lines into an annotation of the job (`bd6e0d9`), which the API returns.
The next failure named `test_exports.py`: on a real MongoDB the request log's database is shared by every program of a
run, and another program's events were counted (`45fe9d7`). The one after named `test_store_mongodb.py`'s check that
`db_init` keeps the portal user's roles: it compared two lists in order, while MongoDB keeps roles as a set and may list
them in another order after `updateUser` — likely the cause of the two earlier, unexplained failures (`0855a82`).

**The backlog's "later" list**, all of it (recommended options). Exports follow the record list's filters, which stay in
the address (`3df0c50`). The data entry API checks the values of a registration with the engine of its image
(`a1131bb`, F11; about 50 ms a registration, so a 5,000-record import takes about four minutes more). The record search
reads raw scanner data with the portal's engine and RFID EPCs through the resolver, which already decodes them
(`576b48a`). Serial numbers registered with their batch can be fixed from the list (`8dbc85d`); writing it found that
deleting one record of a key rewrites the key's whole document, and that a sibling the API now refuses (an old rule-2
record, or — since `a1131bb` — a value the engine rejects) would have made both the rewrite and its restore fail, losing
the key's records: the data entry API now answers `POST /validate` and the portal asks it before any rewrite. The label
offers the EPC of a serial number for RFID and NFC tags (`e1b6917`), its encoder checked against the Tag Data
Standard's example, the resolver's decoder and the independent `epc-tds`.

## How the main areas evolved

| Area | 1.0.0 (session 1) | Now |
|---|---|---|
| Identification | GTIN + optional batch | 16 primary keys and 9 qualifiers, with the combinations of the standard |
| Labels | PNG/SVG, HRI on/off, optional branding | HRI full/key/none, QR version and correction, data attributes, no branding |
| Finding records | open one GTIN at a time | record list, text search, filters by key type, qualifier, author and link problems, code search, other records of a key |
| Bulk work | none | XLSX/CSV export and two-step import |
| Usage | nothing recorded | every resolution request logged without personal data, daily counts per key, a Requests screen per scope |
| Integration | the official data entry API and its single master token | a versioned API for each organisation's systems, with API keys (scopes, prefixes, expiry, a request limit) and an OpenAPI description |
| Quality of targets | none | link checker in the editor, for every record and on import |
| Accounts | users from the command line, all equal | roles, prefixes, organisations (tenants) with their own users and audit trail, a server administrator with support access, users screen, temporary passwords or invitations by e-mail, password recovery by e-mail, security notices, history, audit trail, in the portal's own database |
| Installation | manual, with a patch | git fork, layered configuration, Ubuntu installer, backup |
| Resolution | GTIN and batch, compressed links of Digital Link 1.1 | every key and qualifier, the rules of Resolver 1.2.1, EPC binary strings from NFC tags (`/eh…`, `/ex…`) |
| Tests | 69 checks | 2,133 checks in 28 test programs (one of them GS1's own test suite), plus the installer test (87); run through pytest and on GitHub Actions, the portal and its job workers also on a real MongoDB |
| Deployment | one container per service, Flask's built-in server, the proxy restarted by hand | any number of replicas of the four stateless services (set in `.env`), gunicorn in every web service, a proxy that follows replicas through Docker's DNS |
| Documentation | README of the package, handover | README, user guide, features, history, developer guide (in English; also in Portuguese until 14 October), extensions documentation, changelog |

## Decisions that stay unless deliberately revisited

1. Official variable names and behaviour are kept; deliberate changes are documented in the changelog.
2. No instance values in the code: domain from `FQDN`, operator from `RESOLVER_ORG_*` / `RESOLVER_CONTACT_*`.
3. The portal is the back end between the browser and the API; the token never reaches the browser.
4. Validation mirrors the GS1 Barcode Syntax Engine; deliberate limits are documented. Since session 11 the
   keys, qualifiers and formats are built from the dictionary of the one engine release written in
   `docker-compose.yml`, which every service uses ([ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md)).
5. Resolver: an unknown `linkType` is a 404 (required by the standard); walk-up serial → batch → variant →
   key; query strings are passed on unchanged and never judged.
6. Roles reader < editor < admin are checked on every call; GS1 Company Prefixes limit every screen. A
   record belongs to the tenant whose prefix starts its key, or to the operator; every call is limited to the
   tenant of the request; the server administrator reaches a tenant's data only through recorded, read-only
   support access ([ADR 0002](adr/0002-tenants.md)).
7. The portal's data (users, record metadata, journal, sign-in failures, caches) lives in a database of
   its own in the installation's MongoDB, reached with a user limited to it, and is in the daily backup;
   the session key comes from `.env` ([ADR 0001](adr/0001-portal-state-in-mongodb.md); until session 9,
   files in the configuration volume).
8. Labels: X = 0.495 mm, 2.2 mm text, 4X quiet zone; error correction exactly as chosen; no GS1 branding.
9. Data attributes go only into the QR code and are validated by GS1's engine.
10. Imports and link checks are jobs in the portal's database, run by the `portal-worker` service; nothing in
    the portal depends on the memory of one process. The resolver, the data entry API, the portal and the
    worker run as `*_REPLICAS` containers set in `.env`, the web services under gunicorn with several
    processes; the proxy finds the replicas through Docker's DNS; the database and the proxy run once
    (ADR 0001, step 4).
11. Registration follows Resolver 2.5.9: with a serial number, the batch and variant are informative
    qualifiers of the record; every qualified record should have its key's own record above it.
12. EPC binary strings are decoded from GS1's TDT artefacts, shipped unchanged; key qualifiers from the tag
    go to the path, data attributes to the query string; a `++` hostname is ignored.
13. Linksets write `gs1:` link types in `https://ref.gs1.org/voc/` (Resolver 2.14); stored documents keep
    the official `https://gs1.org/voc/` keys.
14. E-mail goes through a relay the operator chooses, as jobs of the worker; without a relay nothing changes.
    Single-use links are stored as hashes and carried in the fragment of the address; password recovery answers
    the same for everyone; security notices cannot be switched off ([ADR 0004](adr/0004-e-mail.md)).
15. Organisations' systems use the portal's own versioned API (`/portal/api/v1`) with keys their administrators
    create; a key acts as a user of its organisation would, under every rule of the portal; only the hash of a key
    is kept ([ADR 0005](adr/0005-tenant-api.md)).
16. The resolver records each request it answers, in the background and without anything that identifies the person
    who scanned; raw events expire, daily counts per key last; whose events they are is decided at query time from the
    key ([ADR 0006](adr/0006-resolver-request-log.md)).
17. The documentation is written in British English only; the software's own texts (portal, resolver pages, home
    page, e-mail) stay in Brazilian Portuguese and British English.
18. Development happens in Claude Code cloud sessions that push to `gs1br/develop` directly; `CLAUDE.md` holds the
    conventions and a session start hook prepares the tests as the CI does.
19. The portal opens on the overview after sign-in; its figures are computed on request from what the request log
    and the journal keep, in the scope of the user ([ADR 0007](adr/0007-overview-indicators.md)).
20. The worker monitors the installation and e-mails the administrators on a change of state, never on every round
    ([ADR 0008](adr/0008-monitoring-and-alerts.md)).
21. An organisation's domain answers only for its own keys; a verified domain stays verified
    ([ADR 0009](adr/0009-tenant-domains.md)).
22. Labels keep their default exactly; sizes are magnifications of both targets; the PDF is written by the portal
    ([ADR 0010](adr/0010-label-studio.md)).

## Lessons learnt

- Test with data created by other tools; official example records exposed assumptions.
- nginx resolves upstream names at start-up: the proxy must restart when a service is recreated. Since
  session 9 it asks Docker's DNS again every 10 seconds (`resolve`, nginx 1.27.3 or later), which also finds
  replicas added after it started; a restart would not have.
- `docker compose restart` keeps the old environment; use `up -d` after editing `.env`.
- The syntax engine refuses some combinations the URI grammar allows (22 on ITIP): check with the engine.
- The GS1 §4.10 grammar has a typing error (`shipToaAdd…` for (4302)/(4303)).
- Check claims against the code before documenting them.
- Show layouts as images before building them.
- Read the standard's ranking rules as well as its sets: rule 4 of 2.5.9 also orders the records (a serial
  number before a batch), which the walk-up had not followed.
- A test double hides what the real component checks: the proxy test's mock upstream accepted any Host
  header, so the `resolver_web` upstream of item 1.5 (refused by Werkzeug) passed every test and broke
  every resolution on staging. Check resolutions through the proxy after each installation, not only
  `/portal/healthz`.
- Machine-readable artefacts and worked examples have errors too (a field name in a TDT draft, headers in
  annex E.3): decode every published vector and compare with an independent implementation.
- Read the processing model, not only the data: the SGCN-96 artefact needs the EXTRACT rules of its BINARY
  level, which a reading of the output level alone missed.
- Run a conformance suite in the sandbox before running it for real: its unchanged code against the real
  resolver code predicted the staging result and found the one divergence before the owner's run.
- A test suite encodes its authors' reading of the standard: check each failure against the text before
  changing the code (E12).
- When the real database cannot run where the tests are written, a compatible stand-in can still exercise
  what mongomock cannot (separate processes sharing one database), but its own gaps must be told apart from
  defects: FerretDB 1.24 has no TTL indexes and refuses nested arrays and keys containing a dot, which
  MongoDB accepts.
- A worker must say that it is alive: without announcements, a job queued with no worker running waits in
  silence, and nothing tells the user or the installer why.
- A file that other processes may read at the same moment must appear complete: write it under another name
  and link or rename it into place. To test such a race, make the slow part slower in the test rather than
  hoping concurrent starts will meet.
- Check a plan against the way it will be operated: restarting the proxy when a service is recreated works
  for one container per service, not for a container added beside the others.
- A tool from another packager behaves differently in small ways: Ubuntu's and nginx.org's nginx keep their
  temporary folders in different places. Reproduce the CI runner's conditions (the package's paths, a user who
  is not root) before blaming the code.
- Before adding a dimension to access control, find the one place every route already passes through
  (`allowed()`): changing it there limits every route at once, and the existing tests show nothing else moved.
- A new owner for everything unassigned (the operator) lets a model arrive without a migration: until the first
  tenant exists, every rule gives the old answer.
- A list of files kept by hand in a Dockerfile drifts from the code: a new module was missing from the image
  while every test passed, because the tests ran the source tree. Test what the image will hold.
- Before generating a table that replaces a hand-written one, compare the two: the differences are either the
  generator's mistakes or the old table's, and both need a decision.
- A test of a new feature reads what the old code writes: checking the installer's `.env` for the relay found
  settings written twice, the old value last, a defect older than the feature. Check the output, not only the
  values that were meant to change.
- A link that differs from the open page only after `#` does not load the page again: code that reads the
  fragment at load time must also listen for `hashchange`. The same holds for what a view leaves behind: a key shown
  once stayed in the page when the view changed, until leaving the view removed it.
- A message catalogue kept by hand can hold one key twice, and the second silently wins: a test now refuses it.
- A test double can do more than the real thing in a way that hides a defect: mongomock removes expired documents
  when they are read, so an expiry of zero days looked like a log switched off. Check the side effect itself (what
  was written), not only what a query returns.
- A mutation that makes the code loop for ever is caught (the test cannot pass) but can stop a mutation loop that
  waits on it: give each run its own time limit and treat a timeout as caught.

## Open items

- Security notice to the official maintainers about the public `GET /api/index` (drafted).
- Rotation of the development secrets of the staging installation, with `scripts/rotate-secrets.sh` (item 7.2).
- A fresh installation with `scripts/install.sh` on a clean machine (only the re-run path is proven).
- The off-server backup copy's destination and a restore rehearsal on the servers (`BACKUP_COPY_TO`,
  `scripts/restore-rehearsal.sh`, item 7.2); the load test's rehearsal on staging (item 7.4).
- The items delivered in session 14 (4.2 to 7.4 and the "later" list) are still to be confirmed on staging.
- Review of the 221 Portuguese AI names and of the Portuguese engine messages; decision on the GS1 logo on the
  home page and resolver pages.
- Items 2.4, 2.5, 3.1, 3.2 and 4.1 were confirmed on staging and in CI on 14 October (session 13); a real e-mail
  relay for staging and production is still to be set up.
- The resolver's own `/heartbeat` answers 500 (official code: a Flask-RESTX resource returns a `jsonify` response
  inside a tuple); the portal's health check uses the data entry API's, so nothing depends on it. A candidate for a
  small fix and an issue upstream.

Next steps: the open backlog, in the agreed order, is in the README ([Open backlog](../README.md#open-backlog)).
