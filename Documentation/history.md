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

**The first load test on staging** (15 October, the owner running the staging test plan): at 100 requests a second
through HTTPS the resolver answered 26.6 a second, p50 6.2 s, 29 % without an answer; `docker stats` under load showed
both resolver containers at 90–100 % CPU and their process count rising from 27 to about 110, the database at 2 %
and the proxy at 1 %. The cause was in the official code: a Node.js process started for every syntax check of a
request path (about 46 ms each here). The resolver now asks the engine's C library in its own process (`653ffc6`,
the owner's choice among three options; about 2 µs a check), built into its image with the portal's script at the
same release, Node.js kept as the fallback; `test_resolver.py` checks that both answer alike, and GS1's suite runs
through the new check.

**The staging tests of 15 and 16 October** confirmed the update to `0244bb8` (backup, settings, installer re-run,
monitoring alerts after correcting the plan: an alert needs two failed rounds five minutes apart) and produced
twenty-three notes from the owner. Two were bugs, both hidden by test doubles that did more than the real components:
the editor lost *Default target: the item's page* on reopening a record, because the official data entry API keeps a
`gs1:defaultLink` only as the document's `defaultLink` and leaves it out of what it returns, which the portal's
stand-in API did not; and a brand stayed with its old owner after its prefix moved to an organisation, because brands
recorded their owner when saved instead of deriving it from the prefixes. The rest became items 9.1 to 9.7 of the
README's backlog (item's page per record, administration and navigation, DataMatrix and label options, every link
type and language, browser and city in the request log without the IP address, domains without the terminal, nine
more interface languages), on the recommended options.

## Session 15 — the staging feedback, items 9.1 to 9.7

The owner, away from the server until 20 October, asked for packages P1 to P7 (items 9.1 to 9.7) in order, each a
complete delivery, every question on the recommended option (the triage of 16 October, section 4).

**Item 9.1, the item's page per record** (`cb67cf5`; ADR 0011 amended). Bug B1 was reproduced first, at its source: a new
test program, `test_mock_parity.py`, makes the portal's calls on its stand-in and on the real data entry API and
compares the records; before the fix it failed eleven times (the API dropping links of type `gs1:defaultLink`, and a
partial `DELETE` on such a record answering 400). The fix is in the API, which now returns the record's own
`gs1:defaultLink` links. Of the two models the triage left open, the ADR chose explicit default links per record — the
official model's own link type for a record's default — over the page as the address of a link of the key's shared
default type, which would have told applications asking for that type that the resolver's page was the brand's. The
records saved with the earlier, shared option were already in the new form, so nothing was migrated. B2 (a brand kept
by its old owner after its prefix moved) was fixed by deriving the owner at query time; the same pattern was looked for
in domains and single sign-on, which belong to the organisation itself, and found only in a domain's default prefixes.
The item's page now shows each link type once in the visitor's best language and uses the brand's logo as favicon.
2,621 checks in 39 programs without a browser; 24 mutations, all caught.

**Item 9.2, administration and navigation** (`a3b3cea`; ADR 0013). A sidebar built from the user menu rather than a
second list; an organisation's page that reads the modules the screens already use, with links to them, rather than
moving twelve screens into it; prefixes as rows and a prefix picker; the portal's own dialog for the fourteen
`confirm()` calls; the overview filtered by organisation for server administrators, with *Operation* theirs only; an
alert history from now on (earlier alerts were never recorded). The phone-width review became a test that opens every
screen at 390 pixels and measures the page's width. The e2e programs that confirmed through the browser's dialog now
click the portal's, and the guide's screenshots, which clicked near the left edge to close the user menu, clicked the
new sidebar instead: they now click in the hero band. 2,663 checks without a browser, 648 in Chromium; 24 mutations, all
caught.

**Item 9.3, labels** (`7f9892e`; ADR 0010 amended). libzint was chosen over a Data Matrix encoder written here, and every
symbol is read back in the tests by an independent decoder (zxing-cpp). The GS1 General Specifications could not be
fetched: the environment's network policy refuses gs1.org and the GS1 Member Organisations' sites, so the healthcare
and direct part marking ranges come from excerpts found by searching, and are left for the owner to check against the
current release; general distribution was left out for want of a source. Regenerating the guide's images showed that
since item 9.2 the element pictures were cut: a full-page capture lays the page out again without the sidebar, so an
element in view is now captured as it stands. 22 mutations, all caught.

**Item 9.4, every link type and language** (`1e40f8c`). The link types are generated from the vocabulary's JSON-LD
rather than typed in: gs1.org is refused here, so the tests read version 1.16 from the vocabulary's GitHub repository at
a pinned commit, as the GS1 rules are read from the dictionary. The deprecated types and the resolver's own
`gs1:defaultLink` and `gs1:defaultLinkMulti` are left out. The English titles the portal gave before were kept rather
than replaced by the vocabulary's, so that records saved with them still read as the portal's own. The language field
became a search over a list rather than a longer menu, the names given by the browser so that they follow the
interface's language. 15 mutations, all caught.

**Item 9.5, browser, location and retention** (`b768463`; ADR 0006 amended). The address is looked up where it arrives,
in the resolver, and never leaves the function: looking it up later in the worker would have meant storing it until
then. City names, not coordinates, are kept, and the map is searched by name, so the screen suggests no more precision
than the address gives. DB-IP's free database was chosen over MaxMind's, which needs an account; its download site is
refused by the session's network policy, so the tests write their own MMDB file and the first real download is part of
the staging checks. Retention needed the portal to delete events, which its database user could not: rather than a
second writer, a role with the single right to delete events of the log. 27 mutations, all caught, two of them after the tests were strengthened (the database role
is checked on CI only).

**Item 9.6, domains without the terminal** (`0bfe208`; ADR 0009 amended). The portal was kept away from the host: a web
application able to write nginx sites and run Certbot would be root to whoever took it over, so the operator's script
runs on a schedule instead and reports what it did into the portal's database, which the card reads. Running it every 5
minutes made Let's Encrypt's limits matter — a domain whose DNS is not ready would fail twelve times an hour — hence the
growing waits. The script's JavaScript for mongosh now travels as an environment variable of the container rather than
inside a quoted command line. 16 mutations, all caught.

**Item 9.7, interface languages** (`3d66bdd`; ADR 0014). About 1,900 texts were translated into nine languages by nine
Claude agents working in parallel from the English, with the Portuguese as a reference and one glossary of GS1 terms;
a script checked each file (same keys, same placeholders, nothing empty) before it was merged. The session's usage
limit stopped the agents twice; each resumed from the files it had written. The portal loads a language only when it
is used, so pages do not carry eleven catalogues. Arabic needed the styles rewritten with logical properties; a browser
test now checks that the content stays beside the sidebar, which a first version missed. The names of the GS1
Application Identifiers were left in GS1's English for the new languages: official names come from each Member
Organisation. 13 mutations: 12 caught, one equivalent.

**Four items added by the owner** on 17 October became 9.8 to 9.11 of the backlog, numbered in the order recommended
rather than the order given: export limits set in the portal (small, and on screens that exist); the GS1 Company
Prefix's length from GS1's table, which the EPC of keys other than the GTIN needs for its partition; an EPC for every
key the Tag Data Standard encodes; and the project's documentation last, since it describes everything before it. The
table the owner attached (`GCPPrefixFormatList` of 17 September 2026, 212,486 prefixes) says it has been restricted since
December 2025; the repository is public, so the table stays out of it and the server administrator uploads it, the
tests using a small table of their own in the same format.

## Session 16 — the owner's additions, items 9.8 to 9.11

The owner, away from the server until 20 October, asked for items 9.8 to 9.11 in that order, each a complete delivery,
every question on the recommended option of the handover (section 8a), mock-ups delivered without waiting, and a section
of the staging test plan for each.

**Item 9.8, export limits in the portal** (`f0c1d4f`; ADR 0012 amended). The limits moved from `.env` to the portal:
an installation maximum on *Organisations* and each organisation's limits per role on a new *Exports* tab of its page.
The maximum caps an organisation's administrators too — otherwise it would not hold "for every company", as asked —
while server administrators keep no limit. The tenant API had no notion of an export; its record listing is the
closest, so it is truncated at the limit set for API keys rather than refused (an organisation's systems page through
everything), and refused at 0. `PORTAL_EXPORT_LIMITS` is read once, so an upgrade keeps the limits in force. The
mock-up showed, by chance, that the *New organisation* form's prefixes label had used the label studio's card class
since item 9.2: fixed in passing. 18 mutations: 17 caught, one equivalent (a redundant check on fractions, removed).
2,989 checks in 43 programs without a browser, 736 in 14 Chromium programs.

**Item 9.9, the GCP length table** (`5dd6bfe`; ADR 0015). GS1's list is restricted since December 2025 and the fork is
public, so the server administrator uploads it and the tests use a small table in its format; the owner's copy of the
list of 17 September 2026 was used once, outside the repository, to check the parser and the timings (212,486 entries,
0.9 s to parse, 0.25 s to store, a lookup in about 10 µs). Its 9.2 MB do not pass the 1 MB the proxies and the portal
accept, and raising that on the host's nginx would mean editing every server's site: the page compresses the file
instead (0.7 MB), and a command in the container loads larger ones. The upload is the portal's only route that takes a
body other than JSON; its types (`application/gzip`, `application/xml`) are ones a form of another site cannot send, so
the rule that guards against cross-site requests still holds, and a test proves the form types are refused. The real
list showed that the staging installation's prefix `7898357` is part of a 9-digit company prefix in GS1's list, which
the new warning beside an organisation's prefixes now says. 22 mutations, all caught (three after the tests were
strengthened). 3,068 checks in 44 programs without a browser, 756 in 15 Chromium programs.

**Item 9.10, an EPC for every key** (`6c7c755`; ADR 0010 amended). Rather than a table per scheme typed from the
standard, the encoder reads the same Tag Data Translation artefacts as the resolver's decoder and runs them the other
way, so that one engine covers the eleven keys and a test can decode every result back. That round trip found a defect
in the resolver: with a 12-digit company prefix, the empty reference of an SGLN, GRAI, GDTI or SGCN was decoded as "0",
giving a key one digit too long — and the independent library the tests had compared with for months, `epc-tds`, had
the same defect, so the comparison agreed on the wrong answer. Those cases are now checked against the standard. The
comparison with `epc-tds` was widened to the other schemes through their tag URIs, which showed three of its limits
(serials cut at `.` or `:`, escapes not undone, leading zeros of an SGCN serial dropped); the cases are left out with
the reason, and the TDT artefact's rule is followed. The TDS 2.0 "+" schemes were left for later: no tag URI, less
support in readers. 18 mutations, all caught. 3,112 checks in 44 programs without a browser, 763 in 15 Chromium programs.

**Item 9.11, the documentation** (`6b8737e`; ADR 0016). The tests' check names were already the most complete and
current description of the software, so the inventory is drawn from them rather than written: the pytest layer keeps
each program's `PASS` lines and a script groups them by area, with a section that gathers every search and filter from
every screen, the search by EPC included. Each of the 197 features now cites the checks that prove it, and a new test
fails when one cites none or cites words no check holds. Mapping them showed three features with no check at all — the
order of data attributes, an import that never deletes, a CSV cell above 128 KB — which gained one each, and two counts
of the developer guide that had drifted before this session. The checks of the documents themselves read the inventory,
so their own count is left out of the comparison (it would depend on itself). The operator's guide gained a table of
contents and the label studio's Data Matrix and EPC sections it lacked; the user guide a table of every search and filter
and one of every administration task; `features.md` lost a section that had collected the item's page, labels, domains
and monitoring under "Request log"; the tenant API got a reference page generated from its OpenAPI description. 12
mutations, all caught. 3,129 checks in 45 programs without a browser, 765 in 15 Chromium programs; the inventory holds
4,061 with the CI-only program's.

## Session 17 — the staging tests of 20 October and the owner's notes

The staging tests of 20 October passed (every box of P1–P7 and 9.8–9.11) and left two findings; the owner decided both,
answered the checks of the handover and added notes from the tests. Each became a delivery, the recommended option
taken where the owner was away.

**Finding F1, a limit by size for the request log** (`2425487`; ADR 0006 §9). The owner chose the third option put to
them: a most space on disk beside the days, with alerts from 80 % of it and at every further 5 %. The obvious measure,
the collection's size on disk, never falls: MongoDB reuses the pages of deleted documents but does not shrink its
files, so a limit on it would keep deleting once reached. What counts is the used pages (`storageSize −
freeStorageSize`) plus the indexes. The housekeeping trims down to 95 % rather than to the limit itself, and the alerts
remember the step last told instead of reminding every day, so a log held at its limit by the housekeeping stays quiet.
16 mutations, all caught (two after the tests were strengthened: a threshold of 75 % and the limit shown to an
organisation's administrator went unnoticed at first). **Finding F2** (`5421bd3`): considered validated by the owner;
the procedure used on staging went into the operator's guide.

**Upgrading the official resolver** (`0c76bf0`). The official project and the fork share the database image, the
database and the document format, so an installation needs no conversion, only the right folder: Docker Compose names
the volume after it, and a fresh clone elsewhere would start with an empty database. The script therefore upgrades in
place, after a backup, keeping the official branch for the way back. The installer already kept an existing database's
default password with a warning; the script writes the credentials into `.env` before it runs. Because `git switch`
may replace the running script, its body is one block that bash reads before running it. 11 mutations, all caught.
3,181 checks in 45 programs without a browser, 769 in 15 Chromium programs; the inventory holds 4,117.

**Turkish, the menus' order, every target language** (`984f2ce`; ADR 0014 §7). The 1,703 messages of the portal, the
22 e-mails, the resolver's pages and the home page were written in Turkish with a short glossary added to the
translation guide; the owner decided that no native review will be arranged and that corrections come from the
community. The menus now list the Latin alphabet's languages first: the rule is written three times (portal, home page,
resolver), so each place has its own check. The target languages' field used the browser's `datalist`, which shows only
the entries that match the field's current value — with `pt` in it, Portuguese alone — so the list looked short; it
was replaced by the portal's own list, scrolled, counted, filtered by the part after the last comma. Building it showed
that a list placed with fixed coordinates under a field near the bottom of the window ends up off-screen or behind the
page; it now lives inside the field's box and opens upwards when there is no room below. 12 mutations, all caught.

**A map of where requests come from** (`a287a64`; ADR 0006 §10). The log had the names of countries, regions and cities but,
by the decision of 17 October, no coordinates; placing cities by their names would have needed a gazetteer and guesses
between namesakes, while the GeoIP database already gives each city a point. That point is now kept, rounded to a
tenth of a degree, so it says no more than the city's name. The map is d3 over Natural Earth's countries, served by the
portal and loaded only when the box is opened; a click on a country zooms to it and lists its regions and cities, and
the map follows the list's filters. Adding the map's texts replaced, unnoticed at first, an existing message of the
same name (the Google Maps link's title): the location check of the end-to-end test caught it. 12 mutations, all
caught.

**The X-dimension, checked** (`6350211`; ADR 0010 §7.6). The owner sent section 5.12 of the General Specifications,
release 26.0, with the decision tree and its thirteen tables. Retail and direct part marking matched what had been
built from secondary sources in session 15; *healthcare* did not — its range was table 11's, the GSRN's, and the
healthcare tables are three, with ranges up to 1.52 mm. Rather than correct one line, each table a label of the portal
can follow became an environment, and the key now decides which are offered, as the tree's first questions do. The
page received the environments as a JSON object, whose keys Flask sorts: the "first is the default" rule picked
*distribution* for a GTIN until each environment carried its rank. One of 11 mutations (table 8 given table 2's
values) went unnoticed while the checks compared only the sizes; they now compare the ranges. The PDF stays out of the
repository.

**The logo and the layout** (`3a17b40`). The owner asked for a logo in the same blue that recalls a resolver, possibly
with a QR code: the mark is a QR code whose lower-right corner, the one without a finder pattern, holds a node
branching into three links. It replaced the GS1 logo in every header, which the screenshots of the guides had been
hiding until now; they show the new one. The sign-in page looked pushed to the right because the room for the
sidebar was kept on every page, the sign-in page included; it is now kept only on the page that has the sidebar, and
the sign-in form lines up under the title. The content may now take 96rem of a wide monitor, and the list of requests
lets long words wrap, so its nine columns fit a 1,280-pixel screen with the side menu (the follow-up noted in the
previous handover). 13 mutations: 11 caught (one after the resolver's check decoded the embedded logo instead of
trusting its type), one equivalent at the tested width (the *New organisation* grid replaced by the former flex row),
and one showed a rule to be unnecessary (narrower cells), which was removed.

**The privacy notice** (`37b14e8`; ADR 0017). The owner asked for a footer link on every page to a notice the operator
writes in the portal, open without signing in, with its changes kept as versions, and for a first text placing the use
of the software on whoever operates the instance, not on GS1 nor on its contributors, "as is". The handover had proposed
only a setting with an external address; the owner's version keeps the notice in the installation itself. Each
publication is a new document whose number is its `_id`, so two administrators publishing at once cannot overwrite
each other: the second is refused. The text is plain, with three marks, rendered with `textContent` only — a notice
cannot carry a script to every visitor; the end-to-end test proved it only after a paragraph of markup with no address
in it was added (one of 21 mutations escaped until then). The default notice was written in the twelve languages; the
operator adapts it before production.

**The owner's other answers** (documents only). Whether the GeoIP database's licence allows any use, commercial
included: DB-IP's *IP to City Lite* is under Creative Commons Attribution 4.0, which allows commercial use with the
attribution the screens already show; the question widened into an inventory of every component, data source and
service with its licence (`Documentation/third-party.md`), which found nothing that restricts commercial use — MongoDB's
SSPL constrains offering MongoDB itself as a service, not running an application on it — and recorded what an operator
must do, trademarks included. The load test of 15 October was written up with what it did not measure and the tests
recommended before production. The native review of the nine draft languages will not be arranged (the files are in
the repository for contributions); single sign-on was not tested on staging (contributions welcome); there is no e-mail
relay for now; the Verified by GS1 address stays as it is; production readiness (7.2) waits for the owner; the
Portuguese AI names (7.3) stay open; the errata material (8.1) was prepared for the owner to send.

**Forwarding** (`8673873`; ADR 0018). Before the staging round, the owner asked for a default destination for the keys
the resolver does not know — GS1's global resolver unless the operator says otherwise — and for destinations by
prefix, both switched on and off in the portal, with indicators in the overview. The resolver reads them from the
portal's database as it already reads domains and brands, so a change needs no restart. Two choices were the
recommended ones, the owner being away: the resolver of last resort stays off after installation, because switching
it on changes the answer to every unknown key (and GS1's test suite expects a 404); and a prefix rule wins over the
resolver's own records, as the owner described it — "any key with the prefix is simply sent on". The per-rule counts
come from the counts per key matched against the current rules, which spares the request log a field. Looking at the
screen showed that the side menu cut *Organisation management* (from the previous delivery): long names now wrap,
with a check. 33 mutations, all caught.

**The installation's appearance** (`fbb44ff`; ADR 0019). The owner asked for a function like the item's page brands
that lets the operator change the logo, the colours and the title *GS1 Resolver Community Edition*, with a button that
restores the original. One setting in the portal's database holds them; the portal and the home page apply it through
a small public style sheet that redefines the pages' own design tokens, and the resolver reads it as it reads brands
and forwarding. The points the owner left open took the recommended option, the owner being away: three colours
rather than every token (twelve colours would be easy to make unreadable), colours refused when white text falls
below WCAG's 4.5:1 rather than a mere warning, the title replacing the product's name in every text (the tab titles
too) and the description file keeping the software's name. Replacing the name in the texts had to happen before their
placeholders were filled, or the screen's own hint, which names the original title, would have named the new one; a
mutation showed it. 28 mutations: 27 caught (one only after it was aimed at the cache's check inside the lock, the outer one being a shortcut); the last showed the logo's own `nosniff` header to be redundant — every answer of the portal carries it — and it was removed.

Right after, the owner asked not to forget the page's HTML title and the favicon (`d23f518`). The title had been
replaced only by the pages' scripts, so the portal first showed the original, and the favicon stayed the project's. The
portal now serves its three pages with the title, logo and icon in their HTML (the home page, plain files behind the
proxy, still sets them from its script), and an icon of its own was added rather than the logo scaled down, because a
logo is usually wide and unreadable at 16 pixels. 14 more mutations, all caught; one of them was caught at first for
the wrong reason — it broke the script's syntax — and was rewritten until a check caught it for the right one.

## Session 18 — the staging tests of 21 October

The staging round of session 17's deliveries, run by the owner on the head `5251e13`, with each finding fixed as it
came.

**The space limit's Save reloaded the page** (`4797247`). Typing 0 in *Most space on disk* and saving reloaded the
page instead of refusing the value, and nothing happened after it. The space form's handler had been registered inside
the days form's handler, so it existed only once the days had been saved in the same page. The end-to-end test saved
the days first and never met that page; its space checks now start on a freshly loaded page and check that the
refusal leaves the page in place (the old code fails it).

**The linear barcode's own size** (`83b06a3`; ADR 0010 §7.7). Testing the label environments, the owner asked whether
the percentage applied to the linear barcode too — it did, each symbol at its own target — and then whether the two
sizes should be separate. The tables give each symbol its own range, and one size for both had locked the 2D symbol at
100 % beside an EAN-13 in tables 2 and 8. The EAN/UPC now takes a size of its own, by default the 2D symbol's or the
nearest its range allows; the API without the new parameter draws what it drew before. Writing the zip's README showed
that it called the percentage of the target a "magnification", which is measured against 0.330 mm and differs outside
retail: it now gives both. 16 mutations, all caught.

**New organisation's button** (`890c383`). On a wide screen the prefixes' column took the spare width and pushed
*Create organisation* to the far right. The existing check ran at 1,280 pixels, where there is little spare width, and
passed with the old layout; the new one runs at 1,920.

**A wrong check digit in the test plan.** The forwarding check used `09521234000019`, whose check digit is 3: the
resolver rightly refused it before forwarding. The plan was corrected and its other codes verified.

**Item 7.3 dropped** by the owner: the review of the Portuguese AI names will not be arranged.

**Automated requests and requests without a key counted, not listed** (`e05420a`; ADR 0006 §11). The owner found the
log flooded and proposed not recording invalid and automated requests at all. Two things in the code argued for less:
the daily counts are built from the events, so recording nothing would have changed the overview's figures; and an
invalid GS1 code read by a phone is a misprinted label, worth keeping. A count on staging decided it: of 89,500 events
in seven days, 92.6 % came from automated clients — most of them with a valid key — and 3.1 % had no key; about 125
were people. The owner chose to count those without storing them. The resolver writes one count per quarter of an hour
and per group of the aggregates (a quarter of an hour, because every time zone is a whole number of them from UTC),
and the portal reads counts wherever it reads events to count them. The events of before go once their day is counted,
rather than being converted into counts: a crash between the two halves of a conversion would count some twice. The
first test run showed that the writer's own tests feed it bare dictionaries with no key — now counted — and that the
counts' indexes must not be made with the events' (a stand-in collection has no database); a check of today's figures
was written so that it does not depend on the hour. 20 mutations, all caught.

## Session 19 — two follow-ups

While the owner ran the rest of the staging round, two of the small follow-ups were built, on the owner's request and
on the recommended options.

**Stopping a running import or link check** (`2bdae36`; ADR 0001 §3.3.1). Step 3 of item 2.3 had left the cancel button
for later. A job is stopped only where its own writes happen — after a record of an import, at a link check's progress
write — so an import never stops half way through a record, and the heartbeat, which runs in a thread of its own,
never stops one. Two cases were found while writing the tests: a stop asked as the last record is written must let the
import finish rather than call it stopped, and a worker that is shut down or dies with a job marked to stop must
cancel it rather than hand it back to the queue. The browser's request to stop sends an empty JSON body: the portal
refuses any write without one (the same-origin rule), which the first test run showed. A first time limit for the
stopped link check was too tight, because the stop is seen only at the next progress write, once a second; the test
now uses enough addresses to tell a stopped check from a finished one. 17 mutations, all caught.

**An alert when GS1's GCP length table is old** (`83b266d`; ADR 0008 §3.1). The age is counted from the date GS1
gave the list, not from the upload, so an old file uploaded today is still reported; the reminder is weekly, since
an old list makes some results less accurate and nothing stops. The end-to-end test's lists are dated, so the limit
it runs with is computed from today: the list of 17 September stays recent and the one of 1 March old whatever the day
the test runs. 12 mutations, all caught.

**Werkzeug 3.1.9** (`949ab50`). The owner asked to take the official project's pull request #129, a Dependabot bump of
the resolver's Werkzeug from 3.1.7. The data entry API pinned the same version, and the CI and the session hook install
both services' requirements in one pip command, which cannot satisfy two pins of one package: both moved. The whole
battery passed with it.

## Session 20 — the official project's pull request #128

With no new findings from staging, the owner took the recommended follow-up: compare the official project's open pull
request #128 with the fork. Of its three fixes, two were already in the fork — the resolver adds a query string to an
address that has one with `&` (`_append_query()`), and the rewritten `read_document()` answers a pair on every path.
The third, `POST /new` duplicating the links of a record that exists, was still there (`5d04806`). Taken as proposed,
it passed the first two new checks and failed the third: in MongoDB a record's `linkset` holds one object keyed by link
type URIs, not links, so `_find_matching_link()` found every object equal and `update()` replaced the type's links — a
link in another language removed the English one. The fix goes through the v3 format, as `PUT` does. The portal's
stand-in for the API appended too, and `test_mock_parity.py` had left the case out because the portal "never does
it"; it does, when two people create the same record at once and on the restore after a failed rewrite, so the
stand-in merges now and the parity program covers it. 6 mutations, the pull request's own fix among them, all caught.

Found on the way and left for the owner: `PUT` with qualifiers that no record of the key has answers 200 and writes
the links into the key's first record (official code; the portal only puts records that exist).

## Session 21 — a record the key does not have

The owner finished the staging sections of sessions 19 and 20 with nothing found, and the follow-up recommended at the
end of session 20 was taken: `PUT` with qualifiers that no record of the key has (`8dbe297`). The same fallback to the
document's first record was in `delete_links()`, so a `DELETE` of links for such a record removed the first record's
links of the same type and languages; both answer 404 now. One existing check, *PUT refuses informative qualifiers
on a batch record*, sent a batch the key did not have and passed only because the fallback checked the key's own
record; it now names a batch that exists. The first parity check of the `DELETE` asked to remove a link the first
record did not have, so the official code answered 404 as well and its mutation went uncaught; it now names one the
first record has. 8 mutations, all caught.

## Session 22 — a list of a key's records

Nothing new on staging or in the plan's threads, and nothing new in the official repository (`master` still the
fork's base; no pull request after #129). Looking for other places where the data entry API quietly wrote less than
it was sent, after session 21's fallback to the first record, found one: `_process_document_upsert()` returned after
the first entry of a document that existed, so `POST /new` with a list of several records of a registered key stored
only the first and answered 201; a new key kept a record listed twice as two entries (`9e0c266`). It came with the
official change that made a list use the upsert instead of deleting and creating the document (official commit
`aae5ebc`, for issue #121). The portal's stand-in wrote every record, so the parity program now compares lists too. 5 mutations,
all caught. The container's Chromium had moved to build 1243 while the pinned Playwright looks for 1194, so the
browser programs could not start until a folder of links gave 1243 the old names (for the session only; the hook is
unchanged).

The owner ran the sections of sessions 21 and 22 on staging the same day. The first version of the session 22 script
answered 500: the body reached the server as JSON it could not read (most likely a character changed when copying
from the browser), and the official handlers turn that into 500. The plan's script now writes the bodies to files and
checks them before sending; it passed. The same handlers, read again, showed that a `DELETE` whose body was a list
deleted the whole document, and that `POST /new` of a record without a link of its default link type answered a
status made of two dictionary keys; both answer 400 now, with a body that is not JSON (`dc3e97e`). 8 mutations, all
caught. Last, the session start hook took over the session's Chromium workaround (`c4c5192`): it reads the builds
the pinned Playwright wants and links the image's newer ones under their names; the e2e group passed with its
variables alone.

## Session 23 — browser tests that wait for the sign-in

Nothing new on staging, in the plan's threads or in the official repository. The check that failed once in session
22's battery, *wrong password message*, paused a fixed 900 ms after the click; with the sign-in slowed by 1.5 s the
old code failed it and three other checks, and the portal program stopped after its seventh. The six sign-ins of the
portal and mail programs now wait for what they expect, up to 10 s, and a timeout fails only the check that follows
(`76fa572`); the other programs' `sign_in()` helpers already waited for the overview's address. Both mutations
behaved as intended: the slow sign-in passes, a changed wrong-password text fails that one check.

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

- Comparing with an independent library proves agreement, not correctness: the EPC decoder and `epc-tds` agreed for
  months on a key one digit too long. Check the cases a library is likely to get wrong against the standard itself.
- An encoder written as the inverse of a decoder, from the same machine-readable definitions, can be tested by the
  round trip on every case; that round trip is what found the decoder's defect.
- A list of features is only as good as the proof behind it: tying each feature to named checks found three features
  nobody had tested.

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
- Hold a test double to the real component with a test that runs both: a stand-in corrected by hand drifts again, a
  comparison fails as soon as it does (item 9.1, bug B1).
- A test that uses a dated fixture against a limit counted from today changes its answer with the calendar: compute
  the limit from today in the test, so the fixture stays on the same side of it.
- A mutation that makes the code loop for ever is caught (the test cannot pass) but can stop a mutation loop that
  waits on it: give each run its own time limit and treat a timeout as caught.
- A fix from elsewhere is a proposal: test it against the data as stored before taking it. The official pull request
  #128 reused a helper written for the v3 format on MongoDB's linkset objects, and only a check with a second
  language showed it.

## Open items

- Security notice to the official maintainers about the public `GET /api/index` (drafted).
- Rotation of the development secrets of the staging installation, with `scripts/rotate-secrets.sh` (item 7.2).
- A fresh installation with `scripts/install.sh` on a clean machine (only the re-run path is proven).
- The off-server backup copy's destination and a restore rehearsal on the servers (`BACKUP_COPY_TO`,
  `scripts/restore-rehearsal.sh`, item 7.2); the load test's rehearsal on staging (item 7.4).
- The items delivered in session 14 (4.2 to 7.4 and the "later" list) are still to be confirmed on staging.
- Items 2.4, 2.5, 3.1, 3.2 and 4.1 were confirmed on staging and in CI on 14 October (session 13); a real e-mail
  relay for staging and production is still to be set up.
- The resolver's own `/heartbeat` answers 500 (official code: a Flask-RESTX resource returns a `jsonify` response
  inside a tuple); the portal's health check uses the data entry API's, so nothing depends on it. A candidate for a
  small fix and an issue upstream.

Next steps: the open backlog, in the agreed order, is in the README ([Open backlog](../README.md#open-backlog)).
