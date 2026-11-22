# ADR 0051 — A failure of the records' database answered 503, never as an unknown code

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the hazards *Unknown codes go to another resolver* (H-14) and *Resolution is unavailable* (H-17) of the [threat model](../threat-model.md); finding F-031 (seen while fixing U-006, [ADR 0050](0050-error-answers.md)) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken — when the records' database cannot be read, the resolver answers 503 with `Retry-After` and the page that asks to try again, never the answer for a code nobody registered and never the resolver of last resort; the request log counts an error. Not taken: an outcome of its own in the request log (`unavailable`: a new value in the portal's filters, overview and twelve languages, while `error` already says that the resolver failed, and the toolkit's 503 of [ADR 0047](0047-toolkit-processes.md) counts as `error` too); sending the request to the resolver of last resort during an outage (it would answer registered codes with whatever another resolver holds); a cached copy of recent answers served during an outage (a recall withdrawn just before the outage could be served again; a separate item if wanted) |
| Amends | the official resolver (`web_server/src/web_logic.py`), deliberately, and the fork's [ADR 0018](0018-forwarding.md) (the resolver of last resort); recorded in the CHANGELOG |

## 1. Context

`web_db.read_document()` answers 200 with the key's document, 404 when there is none, and 500 when MongoDB could not
be read (`PyMongoError`: the database stopped, unreachable, its credentials refused). The official
`_validate_and_fetch_document()` looked only for 200: anything else went on as a missing document — for GIAIs, GRAIs
and SSCCs a search for a shorter stored prefix, whose binary search also read a 500 as "not there" — and ended in 404
*No document found for anchor*, with the request log's outcome `unknown`. During an outage of the records' database:

- a person scanning a medicine or a device read *No information registered for this product* (`error.404`), which
  says the product's owner registered nothing, instead of *try again*;
- an app could not tell an outage from an unknown code: both were 404 with the same body;
- the request log counted every scan of the outage as an unknown code, in the portal's *Requests* and overview;
- with the resolver of last resort switched on ([ADR 0018](0018-forwarding.md)), every scan of a registered code was
  sent to another resolver (`https://id.gs1.org` by default), which answers with whatever it holds for the key, and
  counted as `fallback`;
- a button of an item's page (`/_click`) answered 404 *Not a link of this item*.

## 2. Decision

1. **An outage is not a missing document.** `web_logic._read()` wraps `web_db.read_document()`: a 5xx raises
   `RecordsUnavailable`; every read of the resolution (the key's document, the binary search and the scan for a
   serialised key's stored prefix) goes through it. `_validate_and_fetch_document()` answers it with 503 and
   `RECORDS_UNAVAILABLE` (*The resolver cannot read its records at the moment: try again later*). `web_db` has already
   logged the exception with its traceback ([ADR 0050](0050-error-answers.md)).
2. **The answer.** `web_namespace._process_response()` adds `Retry-After: 30` (`RECORDS_RETRY_AFTER`) to a 503; a browser
   receives the resolver's page *The request could not be completed — Please try again in a moment* (`error.other`,
   already in the twelve languages and used for the toolkit's 503), an app the JSON body with the fixed text. The status
   is the same for a redirect, a linkset, a HEAD request, a compressed link and an EPC binary string.
3. **Never the resolver of last resort.** Only a 404 with the outcome `unknown` goes there, as before; the resolver
   cannot know a code is unknown when it cannot read its records. Prefix rules still forward: they come from the
   portal's settings, read before the records and kept in the cache when that database fails (ADR 0018).
4. **The item's page.** `/_click` answers 503 with `Retry-After` (`_records_unavailable()`), not 404.
5. **The request log** counts the 503 as `error` (`request_log.outcome()`), as the toolkit's 503.
6. **Unchanged.** An invalid code is still 400: the syntax is checked before the database. A 500 that is not the
   database's (a failure while choosing the link) is still 500 with its fixed text.

## 3. Consequences

- During an outage, people are asked to try again and apps receive a status that says so (503 with `Retry-After`), the
  standard way to say the service is unavailable for a while; nothing changes when the database answers.
- An operator who switched the resolver of last resort on no longer sends registered codes elsewhere during an outage;
  the overview's errors rise instead of its unknown codes and fallbacks, which tells the operator what happened.
- No new text in the user interface: the page and its texts already existed in every language; the JSON text is in
  English, as the resolver's other messages.
- The 30 seconds of `Retry-After` match PyMongo's default server selection timeout: a request made during the outage
  has already waited that long for the database before its answer.

## 4. Residuals

- Each request during an outage still waits for PyMongo's server selection timeout (30 s by default) before its 503,
  holding one of the server's threads for that time; a shorter timeout for the resolver's connection would answer
  sooner, at the risk of 503s on a slow but working database.
- The resolver's caches of domains, forwarding rules, brands and the strict mode keep their last values while the
  portal's database is unreachable (threat model T-R6, H-15), as before.
- The data entry API already answered a database failure with 500 (and stops a write when the read before it fails,
  F-009); it is not changed.

## 5. Delivery

`web_server/src/web_logic.py` (`RECORDS_UNAVAILABLE`, `RECORDS_RETRY_AFTER`, `RecordsUnavailable`, `_read()`;
`_process_serialised_identifier()`, `_validate_and_fetch_document()`); `web_server/src/web_namespace.py`
(`_process_response()`, `_records_unavailable()`, `_page_linkset()`, `/_click`). Tests: `test_resolver.py` (the
records' database down: 503 with `Retry-After` and the fixed text, the page that asks to try again and not *no
information registered*, a linkset, HEAD, a serialised key without a search, the database failing during the binary
search and during the scan, an item page's button, an invalid code still 400, the same answers again once the database
is back); `test_forwarding_resolver.py` (the resolver of last resort on: a registered code, an unknown one and a
compressed link answered 503 and not sent, outcome `error`; a prefix rule still forwards; an unknown code sent again
once the database is back).
