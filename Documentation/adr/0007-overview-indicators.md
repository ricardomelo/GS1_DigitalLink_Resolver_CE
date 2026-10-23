# ADR 0007 — The overview: indicators after sign-in

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog item | 4.2 — home page after sign-in with indicators |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

Item 4.1 (ADR 0006) made the resolver record each request and the worker count each day per key. The portal shows
those requests one by one (the *Requests* screen) and as bars per day, but nobody gets a picture of the whole: how
much the codes of an organisation are read, which scanned codes are not registered, how many records lack a
key-level record or have broken links, whether the worker and the daily counts run, who changed what. The backlog
asks for a **home page after sign-in with indicators**, each organisation seeing only its own prefixes and keys (the
server administrator the whole installation): usage, resolution quality (404 for unknown codes first), record
quality, operation and governance, with an export to Excel and CSV.

Constraints:

- The scope rules of ADR 0002 and ADR 0006 apply unchanged: an organisation, the operator, a user's own prefixes,
  support access, and the whole installation for a server administrator outside support access.
- Nothing new is stored about people: the indicators are made from what the log already keeps (ADR 0006).
- The figures must be cheap to compute at today's sizes and must not need a new service.
- No external chart library (the portal ships no third-party front-end code).

## 2. Decision

1. **A new view, *Overview*** (`#overview`, *Visão geral*), **opened after sign-in**. The editor stays at the portal's
   address without a fragment, so bookmarks and links keep working; the overview is the first item of the menu and
   links to the editor, the record list and the Requests screen.
2. **Period**: the last 7, 30 (default) or 90 days, today included, in the installation's time zone; every count is
   compared with the period of the same length just before it.
3. **Five groups of indicators**, every one limited to the scope of the request:
   - **Usage** — scans by people (automated requests counted apart), per day, the most scanned codes, shares by
     device class, language, form of the request (URI, compressed, EPC) and link type asked; since 23 October 2026
     the map of where the period's requests come from, under the most scanned codes
     ([ADR 0006 §13](0006-resolver-request-log.md));
   - **Resolution quality** — the share of requests answered, **scanned codes that are not registered (404
     `unknown`) first**, each with a link that opens it in the editor, codes without a link of the type asked (404
     `noLink`), invalid requests, errors, the average time of an answer (and, for the whole installation, the
     slowest day's 95th percentile);
   - **Record quality** — records, keys and their types, qualified records whose key has no key-level record
     (GS1-Conformant Resolver 2.5.9), serial numbers registered with their batch or variant, records without a
     description, keys with records that nobody scanned in the period, records with problems in the last link check;
   - **Operation** — the last check of every link, and for server administrators the worker, e-mail, the request
     log's retention and the last day counted by the worker;
   - **Governance** (administrators, as the audit trail) — record changes by kind and by user, sign-ins and refused
     sign-ins, users by role, API keys active and expiring within 14 days, the tenant API's calls and refusals.
4. **Computed on request, not cached**: past days from the daily aggregates (`request_daily`), today from the raw
   events, records from the resolver's summary, governance from the journal, users and API keys.
5. **Export** of the figures on screen to **Excel** (one sheet per group) and **CSV** (one row per figure), a journal
   event `overview-export`.
6. **The tenant API gains `GET /portal/api/v1/stats`** with a new scope `stats:read`: usage, resolution quality and
   record quality of the key's reach (governance and operation stay in the portal).
7. **Charts without libraries**: bars made of HTML elements, as on the Requests screen, each with a text
   alternative; every list is a table.

## 3. Design

### 3.1 Calls

| Call | Who | Answer |
|---|---|---|
| `GET /portal/api/overview?days=30` | any user | every indicator of the scope (section 3.2) |
| `POST /portal/api/overview/export` `{format: xlsx\|csv, days, labels}` | any user | the same figures as a file, labelled with the texts the browser sends in the user's language (as the record export); journal `overview-export` |
| `GET /portal/api/v1/stats?days=30` | API key with `stats:read` | `usage`, `quality`, `records` of the key's reach |

`days` is 7, 30 or 90; another value is refused with `overview.badPeriod` (422).

### 3.2 The answer (`portal/overview.py`)

```
{"period": {"days", "from", "to", "previousFrom", "previousTo", "timeZone"},
 "whole": bool, "logDays": n,
 "usage":   {"scans", "automated", "previous": {"scans", "automated"}, "perDay": [{"day", "scans", "automated",
             "notFound"}], "topCodes": [{"key", "value", "anchor", "scans", "notFound"}], "device": {…},
             "language": [[name, n]], "form": {…}, "linkType": [[name, n]]},
 "quality": {"requests", "answered", "unknown", "noLink", "invalid", "error", "previous": {…}, "avgMs", "p95Max",
             "unknownCodes": [{"key", "value", "anchor", "requests", "registered"}], "noLinkCodes": […]},
 "records": {"records", "keys", "byKey": {ai: n}, "noKeyRecord", "breaksRules", "noDescription", "notScanned",
             "notScannedSample": [anchor], "linkProblems", "lastCheck": {"at", "records", "urls"} | null,
             "available": bool},
 "operation": {"lastCheck", "worker", "mail", "logDays", "countedUntil"},          (worker… server admins only)
 "governance": {"changes": {action: n}, "byUser": [[user, n]], "signIns", "signInsRefused", "users": {role: n},
                "apiKeys": {"active", "expiring"}, "apiCalls": {"calls", "refused"}} | null (not administrators)}
```

- **Usage and quality** come from `requestlog.collect()`: the aggregates of the period's past days (per key for an
  organisation, the operator or a user's prefixes; the installation's documents `|*` for the whole installation, so
  that requests without a key count too) and today's raw events grouped the same way. Outcomes in the aggregates
  count every request, automated ones included (the aggregates do not split outcomes by device class): the quality
  figures therefore count every request, the usage figures only people's. Since ADR 0006 §14 people's figures and
  the quality figures count requests with a GS1 primary key only, also for the whole installation (its documents per
  key); its automated requests and answer times stay every request's, and its requests without a GS1 code are a
  figure of their own (`usage.noKey`).
- **Top lists** keep 10 entries on screen and 100 in the export.
- **Records** are those the record list shows (`app.visible_records()`, shared with `GET /portal/api/records`);
  when the resolver cannot be read, `available` is false and the other groups are still answered.
- **Not scanned**: keys with at least one record in the scope and no request in the period, automated or not.

### 3.3 The screen

A period selector (7/30/90 days) and two export buttons; five sections of tiles (figure, the previous period's and
the change), the bars per day, and tables. Each code in *Unknown codes* opens the editor on it
(`#open=/01/…`); a qualified code opens its key. The governance section is shown to administrators only; the
operation section's server-wide lines to server administrators.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the indicators live | a new view opened after sign-in; the editor keeps its address | the editor replaced at `/portal/` (breaks bookmarks and every guide); a separate page outside the portal (another sign-in path) |
| Periods | 7, 30, 90 days with the previous period | free dates (slow on raw events, little use on a home page); calendar months (the log keeps 90 days) |
| Computation | on request from aggregates + today's raw events | a cache refreshed by the worker (stale figures, one more collection); raw events only (slow beyond a few days) |
| Outcomes of automated requests | counted in quality (the aggregates do not split them) | a new split in the aggregates (every finished day would have to be counted again) |
| Export | XLSX one sheet per group and CSV one row per figure | PDF (a renderer in the image); the screen only |
| Tenant API | `/v1/stats` with a new scope `stats:read` | no API (organisations would scrape the portal); every group (governance is the administrators' audit) |
| Charts | HTML bars and tables | an SVG chart library (third-party code in the portal); canvas (not accessible) |

## 5. Consequences

- The portal opens on the overview after sign-in; the user guide's first sections change.
- The figures are as fresh as the raw events for today and the worker's hourly count for earlier days.
- At today's sizes (thousands of keys) the overview reads at most days × keys aggregate documents; item 7.4
  measures it with a large data set, and a cache can follow if needed.
- An API key needs the new scope `stats:read` to read the statistics; existing keys are unchanged.

## 6. Configuration added

None.

## 7. Delivery

One delivery: this record; `portal/overview.py`, `requestlog.collect()`, the endpoints, the tenant API's `/stats`
and the scope; the *Overview* view and its texts in both languages; `test_overview.py` and `test_overview_e2e.py`;
the user guide, the developer guide, the features, the CHANGELOG and the README.
