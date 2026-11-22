# ADR 0052 — One time budget for the database reads of a resolver request

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the hazard *Resolution is unavailable* (H-17) of the [threat model](../threat-model.md); finding F-032 (a residual of F-031, [ADR 0051](0051-records-unavailable.md), measured) |
| Decided by | the owner's standing instruction for the assessment's residuals, the owner away: the recommended option taken — every database read of a resolver request shares one time budget (`RESOLVER_DB_TIMEOUT_MS`, 5 seconds by default), and the 503 of an outage carries a `Retry-After` of that budget. Not taken: only a shorter server selection timeout on the resolver's connection (the residual's first idea: each of a request's six reads would still wait for it in turn, 30 seconds for the first request of each cache period with 5 seconds each); a circuit breaker that answers at once while PyMongo knows the database is down (one more state to get right, and answers would stay 503 for up to one heartbeat, 10 seconds, after the database is back); the same budget for the data entry API (nobody scanning waits on it; a separate residual) |
| Amends | [ADR 0051](0051-records-unavailable.md) (`Retry-After` follows the budget instead of 30 seconds); the official resolver's connection (`web_server/src/__init__.py`), deliberately; recorded in the CHANGELOG |

## 1. Context

The resolver's PyMongo client had no bound of its own: each read waits for PyMongo's server selection timeout, 30
seconds by default, when MongoDB cannot be reached. One request reads the database up to six times in turn: the caches
of the organisations' domains (`domains.py`, in the middleware), forwarding (`forwarding.py`), the strict mode
(`resolution.py`), the request log's retention (`request_log.py`), the brands of the item's page (`landing.py`) and the
appearance (`web_pages.py`) when their period has passed, then the record itself (`web_db.py`). Run with the real
client and nothing listening on the database's address, one read took 30 seconds and one `GET /01/…` 180 seconds
before its 503: the domains, forwarding, the record, the appearance twice (its 30-second period ran out while the
request waited) and the retention. F-031 had counted one wait of 30 seconds.

During an outage the first request after each cache period therefore held a server thread for up to three minutes and
every other request for at least 30 seconds. The resolver has 2 processes of 8 threads by default: 16 such requests
fill it, and other scans, including those a prefix rule would forward without reading a record, queue at the proxy and
time out instead of receiving the *try again* of ADR 0051.

## 2. Decision

1. **One budget per request.** `db_budget.Budget` wraps the whole application, outside the domains' middleware: every
   database read made while the resolver handles a request runs inside `pymongo.timeout()` with the same budget.
   Once it is spent, a read that finds no server fails at once (`ServerSelectionTimeoutError`, a `PyMongoError`): the
   caches keep their last values, as before, and `web_db.read_document()` answers 500, which the resolver answers
   503 (ADR 0051). The budget also bounds a read on a connection that stops answering.
2. **The setting.** `RESOLVER_DB_TIMEOUT_MS`, in milliseconds, from 500 to 60,000; 5,000 when unset. Any other value
   is not used: the resolver warns at start and uses 5,000. The resolver's log says the budget at start. `.env.example`
   documents it, commented out.
3. **Retry-After.** The 503 of an outage carries the budget in whole seconds, rounded up
   (`web_logic.records_retry_after()`): 5 by default, the time the request has already waited.
4. **Unchanged.** A working database answers well within 5 seconds: a request reads a few small documents by their
   identifier. The request log's writer and other background threads are outside the budget: they keep PyMongo's
   defaults, the writer its queue of fixed size and its three attempts.

## 3. Consequences

- During an outage every scan is answered within the budget (5 seconds by default) with 503 and the page that asks to
  try again; a forwarded prefix answers at once once the caches have kept their last values; the resolver's threads
  are no longer held for minutes.
- An operator whose database is slow but working can raise the budget; a value too small for the installation turns
  slow reads into 503s, which the overview counts as errors.
- No new text in the user interface and no new request log value.

## 4. Residuals

- A request that waits for a cache's lock while another request loads it can take up to twice the budget.
- The data entry API keeps PyMongo's 30-second server selection timeout; the portal has its own
  (`PORTAL_DB_TIMEOUT_MS`).
- ADR 0051's other residuals are unchanged: the caches keep their last values while the portal's database is
  unreachable (T-R6, H-15), and during a whole outage the request log loses the outage's events.

## 5. Delivery

`web_server/src/db_budget.py` (new: `SETTING`, `DEFAULT_MS`, `MIN_MS`, `MAX_MS`, `setting_ms()`, `invalid()`,
`seconds()`, `Budget`); `web_server/src/__init__.py` (the warning and the log line at start, `Budget` around the
application); `web_server/src/web_logic.py` (`records_retry_after()` instead of `RECORDS_RETRY_AFTER`);
`web_server/src/web_namespace.py` (`_process_response()`, `_records_unavailable()`); `.env.example`. Tests:
`test_resolver.py` (5 seconds by default; the setting in milliseconds and `Retry-After` rounded up; values out of range
or not whole numbers refused; the budget around the whole application; with the real PyMongo client and nothing
listening, a 0.5-second budget: 503 in JSON and as the page within the budget, the next request too, the budget in the
log; an invalid setting warned about and 5 seconds used).
