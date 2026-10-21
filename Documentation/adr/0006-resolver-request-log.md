# ADR 0006 — The log of resolver requests

| | |
|---|---|
| Status | **Accepted** (14 October 2026). To be implemented in three steps: 1 (this record), 2 (the log on the server: capture in the resolver, daily aggregates and reading in the portal, the tenant API's calls), 3 (the *Requests* screen). **Amended** on 17 October 2026 (section 8, item 9.5) and on 20 October 2026 (section 9, finding F1 of the staging tests) |
| Backlog items | 4.1 — log of resolver requests; 9.5 — browser, approximate location and retention set in the portal; F1 (staging tests of 20 October) — a limit by size |
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
{"t": <date>, "expiresAt": <date>, "m": "GET", "f": "uri" | "compressed" | "epc" | "landing", "epc": "sgtin-96",
 "ai": "01", "v": "07898357410015", "cp": "7898357410015",
 "q": {"10": "L1", "21": null}, "da": ["17", "3103"], "lt": "pip",
 "s": 307, "o": "redirect", "lvl": "/10/L1", "to": "www.example.org", "ms": 12,
 "lang": "pt-br", "dev": "mobile", "ref": "www.example.com", "c": "BR",
 "p": "/wp-login.php"}
```

| Field | Content |
|---|---|
| `t`, `expiresAt` | time of the request (UTC) and of its deletion (`t` + `RESOLVER_LOG_DAYS`, TTL index) |
| `m`, `f`, `epc` | GET or HEAD; `uri`, `compressed`, `epc`, `landing` (the item's page and its clicks, [ADR 0011](0011-item-page.md)); the EPC scheme (`f` = `epc` only) |
| `ai`, `v`, `cp` | the primary key as resolved (a GTIN-13 already as GTIN-14) and its company part: after the indicator digit of a GTIN or ITIP, the extension digit of an SSCC and the filler digit of a GRAI (as `gs1.company_part()` in the portal) |
| `q` | the key qualifiers of the path; `null` for 21 and 235 |
| `da` | AIs of the data attributes of the query string (names made of 2 to 4 digits) |
| `lt` | the link type asked, without the vocabulary's address (`pip`); `linkset` for a linkset; absent for the default |
| `s`, `o` | HTTP status and outcome: `redirect` 307, `choice` 300, `linkset` 200, `unknown` 404 (no record applies), `noLink` 404 (a record applies, no link of that type), `invalid` 400, `error` 5xx, `compressed` 200; `page` 200 and `click` 302 for the item's page reached as a default target and its buttons ([ADR 0011](0011-item-page.md); an automated client's are logged `linkset` and `redirect`); `forwarded` 307 (a prefix rule) and `fallback` 307 (the resolver of last resort) for a request sent to another resolver ([ADR 0018](0018-forwarding.md)) |
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

## 8. Amendment of 17 October 2026 — browser, approximate location, retention set in the portal (item 9.5)

### 8.1 Context

The staging tests asked to keep the visitor's IP address, browser and approximate location, and to set how long the
log is kept from the portal, globally and per organisation. Keeping the address would make every event personal data
(LGPD, GDPR) and goes against decision 2. What the questions need — which browsers open the codes, in which cities they
are scanned — can be **derived when the request arrives**, and the address then forgotten. A neighbourhood or exact
coordinates cannot be derived reliably from an address; a city can, most of the time.

### 8.2 Decision

1. **Browser family** (`br`), worked out from the User-Agent like the device class, from a fixed list: `chrome`,
   `safari`, `firefox`, `edge`, `samsung`, `opera`, `app` (the HTTP stacks of native apps and the browsers inside apps:
   okhttp, Dalvik, CFNetwork, an iOS web view, Facebook, Instagram, WhatsApp, WeChat, Line…) or `other`. Not recorded for
   automated clients or without a User-Agent. The User-Agent itself is still never stored.
2. **Approximate location**: country (`c`, as before), region (`rg`, the first subdivision) and city (`ci`), names in
   English, looked up in a **GeoIP database file** (MMDB, the GeoIP2/GeoLite2 *City* layout) by the resolver at the
   moment of the request. The address comes from the header named by **`RESOLVER_LOG_ADDRESS_HEADER`** (`X-Real-IP` by
   default: the host's nginx sets it to the connection's address, overwriting what the client sent, and the
   installation's proxy passes it on unchanged), or the connection's address without one. It is used for the lookup
   only: never stored, never written in a log line, not even hashed. Private, loopback and reserved addresses have no
   location. A country header (`RESOLVER_LOG_COUNTRY_HEADER`), when set and present, still gives the country.
3. **No coordinates are stored.** The *Requests* screen links a city to Google Maps by its names (city, region,
   country): the map opens on the city, and nothing suggests a precision the address does not have.
4. **The database**: **DB-IP *IP to City Lite*** (Creative Commons Attribution 4.0, free, no account, monthly), at
   **`RESOLVER_GEOIP_DB`** (`/geoip/dbip-city-lite.mmdb` in the resolver's container, the repository's `geoip/` folder
   mounted read only). The resolver opens it at the first request, looks again at most once a minute for a newer file,
   and without one records no location (one line in its output). **`scripts/geoip-update.sh`** downloads the month's
   file (the previous month's while the current one is not out), checks it is an MMDB, and replaces the old one in one
   step; the installer schedules it monthly (`/etc/cron.d/resolver-geoip`) and runs it once. `GEOIP_URL` takes another
   source in the same format (MaxMind GeoLite2 City with an account's licence key, for instance). The licence asks for
   the attribution *IP geolocation by DB-IP*, shown on the screens that show locations and in the documentation.
5. **Retention set in the portal**: a **global** number of days (server administrators; 1 to 3,650; the default is
   `RESOLVER_LOG_DAYS`, which stays the installation's default and its switch: `0` turns the log off) and, **per
   organisation**, the same or fewer days (its administrators or a server administrator; empty: the global). The
   operator's records and the requests without a key follow the global. The resolver reads both from the portal's
   database with its connection, at most once a minute as it reads the domains (ADR 0009), and gives each event the
   expiry of its company part's owner. When a retention is **shortened**, the worker's hourly housekeeping deletes the
   events already older than it (per organisation by its prefixes; the rest by the global); when it is **lengthened**,
   events already stored keep their expiry and only new ones get the longer one — rewriting every stored event was not
   chosen. The tenant API's calls follow their organisation's days. A change is a journal event
   (`requestlog-retention`).
6. **The space the log uses** is shown, not limited: for a server administrator the collection's size on disk, its
   indexes and its number of events; for an organisation its number of events and an estimate (events × the average
   event's size). A limit by size was not chosen: the age of what is deleted is predictable, the size is not.
7. **Aggregates and screens**: the daily aggregates count browsers (`browser`), countries (`country`) and places
   (`place`, the 20 most frequent `country|region|city` of a key and day). The *Requests* screen shows the browser
   beside the device and a *Location* column, filters by browser and country, and a *Retention* tab; the overview's
   usage shows browsers, countries and cities, also in its exports.

### 8.3 Design

An event gains:

```
{"br": "chrome", "c": "BR", "rg": "Sao Paulo", "ci": "Campinas"}
```

| Field | Content |
|---|---|
| `br` | browser family (decision 1); absent for `automated` and `unknown` devices |
| `c` | two-letter country code: the country header when configured and present, otherwise the GeoIP database |
| `rg`, `ci` | region and city in English from the GeoIP database (at most 100 characters each), when it knows them |
| `ll` | the city's position from the GeoIP database, `[latitude, longitude]` rounded to a tenth of a degree, only with a city (section 10) |

- `web_server/src/geoip.py`: `Locator` (the file, opened lazily, reopened when its modification time changes,
  `maxminddb` in memory-mapped mode), `client_address()` (the header's first address, or the connection's) and
  `locate(address)` → `{"c", "rg", "ci"}` or `{}`. `request_log.event()` calls it; the address never leaves the
  function.
- `request_log.Retention`: the global days (`settings`, `_id: "requestLog.days"`) and each organisation's prefixes and
  `logDays` (`tenants`), cached 60 seconds, the last values kept when the database cannot be read; `days_for(cp)` gives
  an event's days (the longest prefix that starts the company part decides, as everywhere).
- Portal: `requestlog.retention()` (the global, the default, each organisation's), `set_global_days()`,
  `set_tenant_days()`, `apply_retention()` (the worker's housekeeping, under the lock `request-retention`) and
  `space(scope)`; routes `GET /portal/api/requests/retention` (any user: what applies to them; administrators see the
  organisations they manage, a server administrator every one and the space) and `PUT /portal/api/requests/retention`
  (`{"days": n}` global, server administrators; `{"tenant": id, "days": n | null}`, the organisation's administrators
  or a server administrator). `/portal/api/config`'s `requestLog.days` is the days that apply to the user's scope.
- Listing and CSV: `browser`, `region`, `city` in each row (CSV columns after `country`); filters `browser` and
  `country`.

### 8.4 Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| The address | used for the lookup, then forgotten | stored (personal data); stored hashed (still pseudonymous data) |
| Precision | country, region, city | coordinates or a neighbourhood (not reliable from an address; would suggest a precision it does not have) |
| The map | Google Maps searched by the city's names | stored coordinates of the city (the database's are those of the network for some sources) |
| GeoIP source | DB-IP City Lite (CC BY 4.0, no account) by default, any MMDB of the same layout | MaxMind GeoLite2 by default (needs an account and a licence key); an online lookup service (sends every visitor's address to a third party) |
| Where it is looked up | in the resolver, at the request | in the portal's worker afterwards (the address would have to be stored until then) |
| Retention | by age, global and per organisation (never longer) | by size (unpredictable; only shown) |
| A longer retention | new events only | rewriting the expiry of every stored event (a long write on a large collection) |

### 8.5 Consequences

- The log answers *which browsers* and *where, roughly* without holding anything about the person: the address is in
  the resolver's memory for the time of one lookup. City, browser and time together are coarse; a privacy notice of the
  operator can say what is derived and how long it is kept.
- A location is wrong when the visitor uses a VPN, a mobile carrier's distant gateway or a relay (iCloud Private
  Relay); the screens say *approximate*.
- The GeoIP file (about 130 MB uncompressed) lives on the server, outside the backup; a missing file costs only the
  location. DB-IP's download site could not be reached from the session that wrote this, so the first monthly
  download is checked on staging.
- An organisation can keep less than the installation, never more; the operator decides the ceiling.

### 8.6 Configuration added

| Variable | Default | |
|---|---|---|
| `RESOLVER_LOG_ADDRESS_HEADER` | `X-Real-IP` | the header with the client's address, set by the proxy in front; empty: the connection's address |
| `RESOLVER_GEOIP_DB` | `/geoip/dbip-city-lite.mmdb` | the GeoIP database file in the resolver's container; empty: no location |
| `GEOIP_URL` | DB-IP City Lite of the month | for `scripts/geoip-update.sh`: another source of an MMDB file, gzip-compressed or not |

## 9. Amendment of 20 October 2026 — a limit by size, and alerts from 80 % of it (finding F1)

### 9.1 Context

In the staging tests of 20 October the owner looked for a field to set the space the request log may take; there was
only the number of days, the space being shown below it (section 8, decision 6). Three options were put: (1) days
only, the line reworded as information; (2) as 1, plus an alert when the server's disk passes a share; (3) a limit by
size that deletes the oldest requests beyond it. **The owner chose option 3, with alerts from 80 % of the limit and
then at every further 5 %.** This section replaces the last sentence of section 8, decision 6.

### 9.2 Decision

1. **The most space the log may use**: one installation-wide value in megabytes (1 MB = 1,048,576 bytes, as the
   screens count), set by server administrators on *Requests → Retention* (`requestLog.maxBytes` in `settings`, in
   bytes); empty: no limit (the default). It stands beside the days: whichever deletes first wins. Organisations have
   no limit of their own: the space is the installation's.
2. **What counts**: the events' collection on disk without the space freed inside it, plus its indexes:
   `storageSize − freeStorageSize + totalIndexSize` from MongoDB's `collStats`. WiredTiger does not shrink a file when
   documents are deleted; it reuses the freed pages for new events, so the freed space is not counted.
3. **Beyond the limit**, the worker's hourly housekeeping (`requestlog.apply_size_limit()`, after the retention by
   days, under the lock `request-size`) deletes the **oldest events** until the log is at **95 %** of the limit: the
   number is estimated from the average event's share of the space, and every event up to the time of the last one to
   go is deleted. A journal event `requestlog-trimmed` (user `-`, `events=N`) records it, and one warning line goes to
   the portal's output. Daily aggregates (`request_daily`) are not touched: the counts of past days stay.
4. **Alerts** (ADR 0008): a check `logspace` of the monitoring, every round. **From 80 %** of the limit it is in alert
   and the server administrators who want alerts receive a message (`alert-log-space`); then **one message at each
   further step of 5 points** reached (85, 90, 95, 100) — no daily reminder; going back down within an alert sends
   nothing; **below 80 %** it is resolved, with a message (`alert-log-space-ok`). The step last told is kept
   (`notifiedLevel`), so a log kept at 95–100 % by the housekeeping does not send a message each hour. Without a limit,
   or when the database does not give the sizes, the check is *unknown*. The overview's *Operation* shows the check
   (*no limit set*, or the share of the limit) and the alert; *Alerts* lists it under its own kind.
5. **Changing the limit** is a journal event `requestlog-space` (`max=N MB` or `max=-`).

### 9.3 Design

- `portal/requestlog.py`: `SETTING_MAX`, `MEGABYTE`, `MAX_MEGABYTES` (10,000,000), `TRIM_TO` (0.95); `used_bytes()`,
  `max_bytes()`, `set_max_megabytes()`, `space_share()`, `apply_size_limit()`; `space()` gives `used` too.
- `portal/monitor.py`: `SPACE_ALERT` (80), `SPACE_STEP` (5), `check_space()`, `_update_space()`; `logspace` in
  `CHECKS`. `portal/notify.py`: the two messages in the category `alerts`.
- Routes: `GET /portal/api/requests/retention` adds `maxBytes` and `maxMegabytes` (the largest value; server
  administrators only, otherwise null); `PUT /portal/api/requests/retention` with `{"maxMegabytes": n | null}`
  (server administrators outside support access; `requests.spaceInvalid` with `{max}` when out of range).

### 9.4 Options considered

| Point | Chosen | Not chosen |
|---|---|---|
| Limit | by size, beside the days (the owner's option 3) | days only (option 1); days and an alert on the server's disk (option 2) |
| What is measured | the collection's used pages and its indexes | the file's size (would never fall after a deletion); the data's uncompressed size (not what the disk holds) |
| Down to | 95 % of the limit | exactly the limit (a deletion every hour for a few events) |
| Alerts | 80 %, then each 5 points, no daily reminder | a reminder every day (noise at a steady 95–100 %) |
| Per organisation | no | a share of the space each (the space is the installation's) |

### 9.5 Consequences

- The age of the oldest request kept is no longer fixed when the limit is reached first: the *Requests* screen still
  says the days, and the alerts say when the limit is near.
- MongoDB's files do not shrink after a deletion; to give the space back to the server's disk, the operator compacts
  the collection by hand (`db.runCommand({compact: "requests"})` in `resolver_log`, during a quiet hour).
- With mongomock (the development tests) the sizes are unknown: the limit is never applied and the check is *unknown*;
  the tests give the statistics themselves.

## 10. Amendment of 20 October 2026 — a map of where requests come from

### 10.1 Context

The owner asked for a world map of the approximate locations on the *Requests* screen, shaded like a heat map, where
regions can be clicked and zoomed, and for the region (state, province) to appear beside the city in the list. The
countries and the names of regions and cities were already recorded (section 8); a map needs a position for each city,
which section 8, decision 3 had chosen not to store.

### 10.2 Decision

1. **The city's position is recorded** (`ll`, `[latitude, longitude]`), taken from the GeoIP database's record of the
   city and **rounded to a tenth of a degree** (about 11 km): the place the database gives for the city, never more
   precise than the city itself. Only when the city is known; dropped with the region and the city when the country
   header disagrees with the database. The client's address is still never stored. This replaces section 8,
   decision 3; requests logged before this change have no position and count on the map by country only.
2. **The map** (`portal/static/requests-map.js`): a box under the list, closed by default and loaded when opened. It
   draws the requests the screen's filters select: each **country shaded** by its number of requests (a logarithmic
   scale from pale to GS1 blue), each **city a circle** sized by its requests. The wheel, a drag and the **+**, **−**
   and **whole world** buttons zoom and move; a **click on a country** zooms to it and lists its regions and cities
   with their counts beside the map. Hovering a country or a city shows its count.
3. **Everything is served by the portal**, after sign-in: d3 7.9.0 (ISC), topojson-client 3.1.0 (ISC), the countries
   of world-atlas 2.0.2 (`countries-50m`, Natural Earth, public domain) and the ISO 3166 numeric codes that join them to
   the log's country codes. No map service is called and no key is needed; the screen credits Natural Earth and DB-IP.
4. **The list shows the region**: *Campinas, Sao Paulo, BR*.
5. **The CSV export** gains `latitude` and `longitude` (empty without a position).

### 10.3 Design

- `web_server/src/geoip.py`: `POINT_DECIMALS` (1), `_point()`; `locate()` adds `ll` with a city.
  `web_server/src/request_log.py`: `ll` dropped with `rg` and `ci` when the country header disagrees.
- `portal/requestlog.py`: `row()` gives `latitude` and `longitude`; `places(args, scope)` counts the filtered requests
  per country and per place (country, region, city), the `MAX_PLACES` (5,000) most frequent places, each with its
  position when one was recorded.
- Route `GET /portal/api/requests/places` (the filters of `GET /portal/api/requests`, the same scope):
  `{"countries": [[code, n]], "places": [{country, region, city, position, requests}], "total", "located"}`.

### 10.4 Options considered

| Point | Chosen | Not chosen |
|---|---|---|
| Position | the city's, from the GeoIP database, rounded to 0.1° | none, placing cities by a gazetteer of names (another data file, ambiguous names); the database's position unrounded (suggests a precision it does not have) |
| Drawing | d3 and topojson served by the portal | a map service with tiles (a key, requests to a third party with the operator's data); a static image (no zoom or click) |
| Countries | Natural Earth 1:50m through world-atlas (750 KB, loaded when the map is opened) | 1:110m (small countries missing); 1:10m (several MB) |
| Loading | when the box is opened | with the screen (the files for everyone who never opens it) |

### 10.5 Consequences

- A city's position is personal data no more than its name: it is the database's point for the city, the same for
  everyone there.
- Requests logged before this change appear in their country's shade, not as circles; the map says so.
- The portal's image carries about 1 MB more of static files.
