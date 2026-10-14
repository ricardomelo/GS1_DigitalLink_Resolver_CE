# ADR 0006 — The log of resolver requests

| | |
|---|---|
| Status | **Accepted** (14 October 2026). To be implemented in three steps: 1 (this record), 2 (the log on the server: capture in the resolver, daily aggregates and reading in the portal, the tenant API's calls), 3 (the *Requests* screen) |
| Backlog item | 4.1 — log of resolver requests |
| Decided by | the owner of the branch, who asked for the recommended option on every point of section 4 |

## 1. Context

The resolver answers every scan of a GS1 Digital Link, but nothing records what it answered. Nobody can say how
often a product's QR code is read, which codes are scanned but not registered (404), which links are served, how
long answers take or whether a printed label carries an error. The backlog's next items need exactly that: the
indicators of the home page (4.2), alerts on spikes of 404 (4.3), the weekly summary (4.4) and the landing page's
clicks (6.1). ADR 0005 also left the reads of the tenant API unrecorded, for this item.

The access log of the resolver's server processes (gunicorn's, on standard output) has a line per request, but only
in the container's output, with the client's address in clear, without the outcome of the resolution, and lost when
the container is recreated.

Constraints:

- **Resolution must not slow down or fail** because of the log: it is the one path every printed code depends on.
- **Privacy by design** (LGPD, GDPR): a scan is made by a person, often on a phone; the log must answer questions
  about products, not about people.
- The resolver runs in several replicas and processes (ADR 0001); MongoDB is the only shared store.
- Ownership of records is derived from GS1 Company Prefixes and can change (ADR 0002): history must follow it.
- The resolver is the official component; its own behaviour (answers, headers, bodies) must not change.

## 2. Decision

1. **The resolver records each resolution request itself**, at the end of the request, from what the resolution
   knows: GS1 Digital Link URIs, compressed ones, EPC binary strings (`/eh…`, `/ex…`) and `?compress` requests.
   Not recorded: `/heartbeat`, `/favicon.ico`, `/robots.txt`, `/.well-known/gs1resolver`, the home page, the portal,
   the data entry API.
2. **What an event holds**: the time; the method; the form of the request (uncompressed, compressed, EPC binary and
   its scheme); the primary key (AI and value) and the part where its GS1 Company Prefix starts; the key qualifiers
   (AI and value — **only the AI for a serial number (21) or a TPX (235)**, which name one unit); the AIs of the data
   attributes in the query string (**never their values**); the link type asked; the outcome (redirect, choice among
   links, linkset, unknown code, no link of that type, invalid request, error, compressed link) with the HTTP status;
   the level of the record that answered; the host of the target; the time taken; the preferred language; a
   **device class** (mobile, tablet, desktop, automated, unknown) worked out from the User-Agent; the **host** of the
   referrer; optionally the country, when a proxy in front of the installation sends it in a header.
   **Never stored**: the client's address in any form (not even hashed), the User-Agent, the full referrer, cookies,
   values of data attributes and of unit qualifiers, any other header.
3. **Asynchronous writing**: each server process puts events in a bounded queue in memory (10,000 events); a
   background thread inserts them in batches (up to 500, at least once a second). A full queue or an unavailable
   database drops events, counts them and writes a warning at most once a minute; the answer to the scan never waits
   for the database. On a normal stop the thread writes what it holds.
4. **Storage**: a database of its own, **`resolver_log`**, collection `requests`, written by the resolver with the
   connection it already has; each event carries its expiry date (TTL), **`RESOLVER_LOG_DAYS`, 90 days by
   default**; `0` switches the log off. The portal's database user is given **read** access to `resolver_log`
   (`portal-db-init`), never write. The daily backup was to leave `resolver_log` out; it keeps it (section 3.4:
   `mongodump` cannot leave a whole database out).
5. **Daily aggregates** in the portal's database (`request_daily`): the worker's hourly housekeeping (ADR 0005)
   counts each day's events per primary key — totals, outcomes, device classes, forms, languages, link types,
   automated requests, time taken — plus one document per day for the whole installation with the 50th, 95th and
   99th percentiles of the time taken. Days are those of **`PORTAL_TIME_ZONE`** (UTC by default; the installer writes
   the server's time zone). A day is counted again until it is over; aggregates are kept **`PORTAL_STATS_DAYS`,
   800 days by default** (a month can be compared with the same month of the year before).
6. **Attribution at query time**: events and aggregates keep the key, never the organisation. A tenant's events are
   those whose company part starts with one of its GS1 Company Prefixes; the operator's are the rest. A prefix moved
   from one organisation to another takes its history with it.
7. **Who sees what**: every user sees the events of the records in his reach (his organisation, his own prefixes,
   any role); during support access, the organisation's. **Server administrators see the whole installation**
   (every organisation, and requests without a key, such as invalid ones), with the organisation of each event —
   the operator runs the resolver and must see what reaches it, and the log holds nothing about the people who scan.
   Exporting the log is a journal event (`requests-export`).
8. **The tenant API's calls** (ADR 0005) are recorded by the portal in its own collection `api_requests`: time, key
   id, organisation, method, operation (the route's template, never the record or the query string), status, time
   taken; same retention, `RESOLVER_LOG_DAYS`. Administrators see their organisation's; server administrators,
   every organisation's.
9. **A *Requests* screen** (step 3): the requests of the last 30 days as daily bars, the latest requests with filters
   (period, code, outcome, device class, automated requests hidden by default), a CSV export, and for administrators
   a second tab with the tenant API's calls. The indicators themselves are item 4.2.

## 3. Design

### 3.1 An event (`resolver_log.requests`, `web_server/src/request_log.py`)

```
{"t": <date>, "expiresAt": <date>, "m": "GET", "f": "uri" | "compressed" | "epc", "epc": "sgtin-96",
 "ai": "01", "v": "07898357410015", "cp": "7898357410015",
 "q": {"10": "L1", "21": null}, "da": ["17", "3103"], "lt": "pip",
 "s": 307, "o": "redirect", "lvl": "/10/L1", "to": "www.example.org", "ms": 12,
 "lang": "pt-br", "dev": "mobile", "ref": "www.example.com", "c": "BR",
 "p": "/wp-login.php"}
```

| Field | Content |
|---|---|
| `t`, `expiresAt` | time of the request (UTC) and of its deletion (`t` + `RESOLVER_LOG_DAYS`, TTL index) |
| `m`, `f`, `epc` | GET or HEAD; `uri`, `compressed`, `epc`; the EPC scheme (`f` = `epc` only) |
| `ai`, `v`, `cp` | the primary key as resolved (a GTIN-13 already as GTIN-14) and its company part: after the indicator digit of a GTIN or ITIP, the extension digit of an SSCC and the filler digit of a GRAI (as `gs1.company_part()` in the portal) |
| `q` | the key qualifiers of the path; `null` for 21 and 235 |
| `da` | AIs of the data attributes of the query string (names made of 2 to 4 digits) |
| `lt` | the link type asked, without the vocabulary's address (`pip`); `linkset` for a linkset; absent for the default |
| `s`, `o` | HTTP status and outcome: `redirect` 307, `choice` 300, `linkset` 200, `unknown` 404 (no record applies), `noLink` 404 (a record applies, no link of that type), `invalid` 400, `error` 5xx, `compressed` 200 |
| `lvl` | the level that answered (`""` for the key, `/10/L1` for a batch; unit values as `*`); redirect and choice only |
| `to` | host of the target (redirect only) |
| `ms` | milliseconds from the request's arrival in the resolver to its answer |
| `lang` | the first language range of Accept-Language, lower case (`pt-br`), absent for `*` or none |
| `dev` | `mobile`, `tablet`, `desktop`, `automated` (crawlers, link previews, monitors, command-line tools and libraries), `unknown` (no User-Agent) |
| `ref` | host of the Referer, when there is one |
| `c` | two-letter country code from the header named by `RESOLVER_LOG_COUNTRY_HEADER` (empty by default: no country) |
| `p` | the first 200 characters of the path, only for an invalid request in which no key could be read (to recognise probes) |

The resolver's routes fill the fields they know in `flask.g`; an `after_request` hook adds status, target, time and
headers, and queues the event. `web_logic.read_document()` returns the level and the reason of a 404 in private keys
(`_level`, `_outcome`) that `web_namespace` removes before answering, so no answer changes.

Indexes, made by the resolver at its first write: `t`; `cp` + `t`; `ai` + `v` + `t`; `expiresAt` (TTL).

### 3.2 Daily aggregates (`request_daily`, `portal/requestlog.py`)

```
{"_id": "2026-10-14|01|07898357410015", "day": "2026-10-14", "ai": "01", "v": "07898357410015", "cp": "…",
 "total": 41, "automated": 3, "outcome": {"redirect": 37, "unknown": 0, …}, "device": {"mobile": 30, …},
 "form": {"uri": 40, "compressed": 1}, "language": [["pt-br", 33], ["en", 5]], "linkType": [["pip", 2]],
 "ms": 492, "msMax": 61, "expiresAt": <date>}
{"_id": "2026-10-14|*", "day": "2026-10-14", "total": 1290, …, "p50": 9, "p95": 31, "p99": 80}
```

One aggregation per day (`$match` on the day's UTC interval, one `$group` by key, outcome, device, form, language and
link type), folded in Python. Lists rather than sub-documents where names come from requests (link types may contain
dots). Under a lock (`store.lock("request-stats")`); a replica that finds it taken skips the run. The setting
`requestStats.finalUntil` records the last day counted after it ended; each run counts again from the next day to
today. Documents of a day that are no longer produced are removed.

### 3.3 Reading in the portal

| Call | Who | Answer |
|---|---|---|
| `GET /portal/api/requests?from=&to=&code=&outcome=&device=&automated=&before=&limit=` | any user | the newest events in the scope, at most `limit` (1–500, 200); `next` for the following page |
| `GET /portal/api/requests.csv` (same filters) | any user | up to 50,000 events as CSV (UTF-8 with BOM, `;`, cells protected); journal `requests-export` |
| `GET /portal/api/requests/daily?days=30` | any user | requests per day in the scope, from the aggregates, with today's from the raw events |
| `GET /portal/api/requests/api?from=&to=&key=&before=&limit=` | administrators | the tenant API's calls in the scope |

The scope is a filter on `cp`: an organisation's prefixes (anchored, from `g.tenants`), the user's own prefixes, or
for the operator's users "none of the organisations' prefixes"; none for a server administrator outside support
access. `/portal/api/config` gains `requestLog: {"days": …}` (0: the log is off).

### 3.4 As implemented (step 2)

- A server administrator **limited to GS1 Company Prefixes** does not see the whole installation: like any operator
  user, he sees the operator's events within his prefixes (`app.log_sees_everything()`: a server administrator outside
  support access and without prefixes).
- Device class: `unknown` also for a User-Agent that matches nothing; the HTTP stacks of native apps (okhttp, Dalvik,
  CFNetwork) count as `mobile`, checked before the tablet pattern (an Android app's User-Agent has no "Mobile").
- The aggregates are written one document at a time (`replace_one` with a run stamp), not in one bulk write; a day
  with tens of thousands of keys takes correspondingly longer (item 7.4 measures it).
- The tenant API's calls keep the route's template as Flask names it (`/portal/api/v1/records/<key>/<path:value>`), and
  the key also when a call was refused after the key was recognised (request limit, scope).
- The installer does not ask for the time zone; it writes the server's (`timedatectl`, `/etc/timezone` or the
  `/etc/localtime` link), keeps an existing value and refuses one that is not an IANA name. The portal's image gains
  `tzdata`, so the names work whatever the base image holds.
- **The backup keeps `resolver_log`** (found on staging, 14 October): `--nsExclude`, used to leave it out, is an option
  of `mongorestore` only, and `mongodump` refused to run, so the dump failed. `mongodump` can leave collections out
  only within one chosen database, never a whole database, and several dumps would change the restore procedure. The
  raw events are small at the installation's traffic and expire anyway. `resolver-backup.sh` now says `ERROR`, removes
  the partial file and exits with status 1 when the dump fails; `test_deploy.py` checks its `mongodump` options and
  both outcomes with a stand-in `docker`.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where requests are captured | in the resolver, after resolution (knows the outcome, the level, the link type) | nginx's access log shipped to MongoDB (another service; nginx knows neither outcome nor level and sees the client's address); the portal (does not see scans) |
| What identifies the client | nothing | the address in clear (personal data, retention rules); a daily salted hash of address and User-Agent (still pseudonymous data, little use before 4.2 asks for it) |
| Unit qualifiers and data attributes | AIs only | their values (a serial number scanned at a time and place can single out a buyer) |
| Writing | a bounded queue and batches per process; events dropped when it is full | one insert per request (adds the database's time to every scan); a separate collector service (another moving part) |
| Where events live | a database of their own, `resolver_log`, readable by the portal | the resolver's `resolver_ce` (the portal would need read access to records the API already gives it); the portal's database (the resolver would need the portal's credentials) |
| Retention | expiry date per event, 90 days; aggregates 800 days | a capped collection (size, not age, decides); a time-series collection (not in the test stand-ins, harder to query by key) |
| Aggregates | daily per key, by the worker, in the installation's time zone | hourly (more documents, little use before 4.2); in the resolver (each replica would compete); none (every indicator reads raw events) |
| Attribution | at query time, from the company part | stored per event (wrong after a prefix moves) |
| Server administrators | the whole installation | the operator's records only (404 for unknown codes and probes would be seen by nobody) |
| Tenant API calls | recorded by the portal, route template only | not recorded (ADR 0005 promised it); in the resolver's log (another component's requests) |
| Delivery | three steps: record, server, screen | one step |

## 5. Consequences

- The installation can tell how its codes are used and where resolution fails, without recording anything about the
  people who scan: no address, no User-Agent, no serial number, no data attribute value. A privacy notice of the
  operator can say so.
- Under heavy load or with the database down, a few events can be lost; resolution is never affected. Lost events
  are counted in the resolver's output.
- Raw events grow with traffic: about 300 bytes each, plus indexes; at a million scans a day and 90 days, some
  30 GB. `RESOLVER_LOG_DAYS` is the lever; aggregates stay small (one document per key and day).
- The backup holds `resolver_log` too (section 3.4), so it grows with the raw events; `RESOLVER_LOG_DAYS` limits both.
- A portal reaching an external database through `PORTAL_DB_URI` reads the log only if that server also holds
  `resolver_log`.
- Requests made by the installation's own checks (the test plan's `curl`, GS1's test suite) are logged too, as
  `automated`.

## 6. Configuration added

| Variable | Default | |
|---|---|---|
| `RESOLVER_LOG_DAYS` | 90 | days raw events (and the tenant API's calls) are kept; 0 switches the log off |
| `RESOLVER_LOG_COUNTRY_HEADER` | empty | a header with a two-letter country code set by a proxy in front of the installation (e.g. `CF-IPCountry`) |
| `PORTAL_TIME_ZONE` | UTC | the time zone of the aggregates' days (IANA name, e.g. `America/Sao_Paulo`); the installer writes the server's |
| `PORTAL_STATS_DAYS` | 800 | days the daily aggregates are kept |

## 7. Delivery

1. This record (both languages).
2. On the server: `web_server/src/request_log.py` and the hooks in the resolver; the read role in `db_init.py`;
   `portal/requestlog.py` (scope, reading, aggregates in the worker's housekeeping), the tenant API's calls, the
   portal's endpoints; the installer's time zone; development tests.
3. The *Requests* screen, the end-to-end test, images, the user and developer guides.
