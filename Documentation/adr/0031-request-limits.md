# ADR 0031 — Request limits per address at the proxy; anonymous events counted, not stored one by one

| | |
|---|---|
| Status | **Accepted** (20 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-R3, T-A1, T-A5 and T-A7 and control G-3 of the [threat model](../threat-model.md); hazard H-17 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): limits per client address in the installation's own proxy, with defaults generous enough for a shared office address, each setting in `.env`; the calls and sign-ins that anyone can send counted instead of stored one by one |

## 1. Context

Nothing limited how many requests one address could send. The installation's proxy passed every request on; the
portal limited failed sign-ins per user name and address (finding F-005) and the tenant API's calls per key (120 a
minute), but nothing before authentication. Two kinds of anonymous request also wrote to the database, each time:

- a failed sign-in wrote a journal event, kept 180 days by default, **whatever the user name** — a new name each time
  passes the delay per user name and address, and the limit of 20 failures per address only slows one address down;
- a single sign-on answer reaching the callback without a sign-in in progress wrote one too;
- every call under `/portal/api/v1` wrote a document into `api_requests`, kept as long as the request log, **with or
  without a valid key**.

Automated requests could therefore take the resolver's time away from people scanning a code (the availability of
resolution is asset A4 of the threat model) and fill the database and the operator's audit trail with noise that
buries the events that matter.

## 2. Decision

### 2.1 Limits per client address in the installation's proxy

`frontend_proxy_server/nginx.conf` limits requests with nginx's `limit_req` and `limit_conn`, keyed on the client's
address as found through the trusted proxies of [ADR 0021](0021-data-entry-api-closed.md) §3 (`real_ip` runs before the
limits, so the host's nginx and a listed load balancer are never mistaken for the client). An IPv6 address counts with
every address of its `/64` network, the usual allocation of one subscriber, so changing the interface part of the
address does not step around the limits. `api-access.sh`, which already writes the proxy's address files when the
container starts, writes the zones and the limit of each group of paths from these settings of `.env`:

| Setting | Applies to | Default | Burst |
|---|---|---|---|
| `PROXY_LIMIT_RESOLVE` | resolution (every path the resolver answers) and the home page | 50 requests a second | 100 |
| `PROXY_LIMIT_PORTAL` | the portal: its pages and files, its API and the tenant API (`/portal/`) | 30 requests a second | 90 |
| `PROXY_LIMIT_SIGNIN` | sign-in, password recovery and its links, the start and the callback of single sign-on | 60 requests a minute | 30 |
| `PROXY_LIMIT_CONNECTIONS` | connections open at once, whatever the path | 100 | — |
| `PROXY_LIMIT_EXEMPT` | addresses or networks counted by none of them (the operator's monitoring, an integrator resolving in bulk) | none | — |

`0` turns a limit off; a value that is not a whole number keeps the default with a warning, and an exempt entry that
is not an address is left out with a warning, so a typing error never stops the proxy. A burst is served at once
(`nodelay`), the requests beyond it answered **429 Too Many Requests** with `Retry-After: 1` by nginx itself, before
any service is reached: plain text for resolution, `{"code": "proxy.tooMany"}` for the portal, whose pages show the
message in the user's language. Each refusal is a warning in nginx's error log.

The official data entry API (`/api`, `/swaggerui`) has no rate: only the addresses the operator listed in
`DATA_ENTRY_API_ALLOW` reach it, and their bulk loads must not be cut short. Its connections count.

The defaults are meant for an address shared by many people (an office, a mobile operator's NAT): a phone sends one
request per scan; the portal's pages load about twenty files at once, within the burst. The sign-in rate stays above
the portal's own limit of 20 failures per address in 15 minutes, which still applies behind it.

### 2.2 Tenant API calls without a valid key: one document a minute

`requestlog.record_api_call()` stores a call made with a valid key as before (one document, with the key and its
organisation). A call without one — no `Authorization` header, an unknown, expired or revoked key, or a key of a
disabled organisation — adds one to the document of its minute, method, operation and status (`b`, the bucket, unique
among the collection's documents that have one; `n`, the calls; `ms`, their total time), so calls in bulk cost one
document a minute per kind of answer, not one each. The list of calls shows such a row with its count ("no valid key
— 312 calls in this minute") and the average time; the overview's governance tiles add the counts up
(`requestlog.api_call_count()`). They stay where they were: in the operator's scope and a server administrator's.

### 2.3 Failed sign-ins that name no account: counted, journalled an hour at a time

A failed password sign-in whose user name (or e-mail address) matches no account, or is empty, and a single sign-on
answer reaching the callback when this browser started no sign-in, are counted in the collection
`anonymous_failures` (`portal/failcount.py`): one document per kind and hour, with the count and the first ten
addresses, deleted seven days after its hour. The worker's hourly housekeeping writes **one journal event per kind
and finished hour** — `login-failed` by `-` in the operator's trail, its detail giving the count, the hour (UTC) and
the addresses, its `count` field the number of failures, which the overview adds up — so the trail keeps the fact and
its size in a bounded number of events (at most 48 a day). A counter is claimed before its event is written and given
back when the write fails, so several workers never write it twice.

A failed sign-in that names an existing account is still journalled at once, in its organisation's trail, with the
address: the account's owner and administrators must see attempts on it, and the throttle of finding F-005 bounds them
per address. So is a failed single sign-on that this browser started, which names the configuration.

## 3. Options considered

| Question | Chosen | Not chosen |
|---|---|---|
| Where to limit | the installation's own proxy, which every installation has and which knows the client's address | the host's nginx (absent with an external load balancer or `TLS_MODE=external`); the services themselves (each request would already have cost a process its time) |
| Key | the client's address, an IPv6 address's `/64` | the address alone (an IPv6 client has 2^64 of them); a cookie or token (anyone can drop it) |
| Defaults | generous, on by default, each one a setting | off by default (most installations would never turn them on); strict (would refuse an office signing in at nine) |
| A path's cost | one rate per group of paths | a rate per path, or by cost (one-segment paths start a process: an item of the official project's code, kept for the code review) |
| Anonymous calls | counted per minute in the same collection, shown in the same list | not recorded at all (the operator would not see an attack); a sample (counts would be wrong) |
| Failed sign-ins of no account | counted per hour, then one journal event | one event each (the weakness); one event per address and hour (an attacker with many addresses still writes many) |

## 4. Consequences

- One address can no longer take a large share of the resolver's or the portal's time, nor try more than 60
  sign-ins or recovery requests a minute; anonymous requests no longer grow the database or the audit trail one
  document at a time.
- An address over a limit gets 429 for a moment. An integrator who resolves in bulk from known servers, or the
  operator's monitoring, should be listed in `PROXY_LIMIT_EXEMPT`; an office behind one address with a very busy portal
  may need a higher `PROXY_LIMIT_PORTAL`. The 429 of the proxy carries no organisation-specific text.
- An attacker with many addresses (a botnet, a large IPv6 allocation beyond a `/64`) still gets each address's share;
  the limits bound one address, not the whole internet. The sign-in throttle's own short-lived documents
  (`login_failures`, 15 minutes) are still written per failure.
- The journal shows failed sign-ins naming no account up to two hours late (the hour must end, then the housekeeping
  run, hourly); the individual user names typed are no longer kept (they were attacker-chosen text), only the count
  and the first addresses. The access log of nginx and the portal's audit log line still name each attempt.
- The resolver's own request log (one event per resolution, [ADR 0006](0006-resolver-request-log.md)) is unchanged:
  it already counts automated requests and requests without a key instead of storing them (section 11 there) and has a
  size limit (section 9); the proxy's limit now bounds what one address adds to it.
- The host's nginx written by the installer has no limit of its own: it passes everything to the installation's
  proxy, which applies these.

## 5. Delivery

In one step (20 November 2026): `frontend_proxy_server/nginx.conf`, `api-access.sh` and `Dockerfile`;
`docker-compose.yml`; `.env.example`; `portal/requestlog.py` (`record_api_call()`, `api_call_count()`, the list's
count); `portal/overview.py`; `portal/failcount.py` (new); `portal/app.py` (`login()`, `sso_callback()`,
`HOUSEKEEPING`); `portal/journal.py` (`counts()`); `portal/store.py` (indexes); `portal/static/app.js`; the texts
`requests.noKeyCount` and `proxy.tooMany` in every language. Checks in `dev-tests/home/test_home.py` (the real
`nginx.conf` with the limits), `dev-tests/portal/test_requestlog.py`, `dev-tests/portal/test_session.py` and
`dev-tests/portal/test_sso.py`.
