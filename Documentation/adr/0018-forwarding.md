# ADR 0018 — Forwarding: by prefix, and to a resolver of last resort

| | |
|---|---|
| Status | **Accepted** (21 October 2026). Implemented in one delivery |
| Backlog item | The owner's request of 21 October, before the staging tests of session 17 |
| Decided by | the owner of the branch, who gave the requirements; the recommended option on the points they left open (section 4) |

## 1. Context

A resolver answers for the keys registered in it. Two cases were answered with a 404 that a person scanning a code
does not deserve:

1. **A key this resolver does not know** — no record for it, typically a product of a brand that uses another
   resolver. GS1's global resolver, `https://id.gs1.org`, knows how to send such a request on (or to tell what it
   knows of the key); a resolver may hand it the request instead of answering 404.
2. **A prefix that another resolver answers** — a company, a GS1 Member Organisation or a country prefix whose codes
   are served elsewhere, for instance while moving from one installation to another, or because the codes were
   printed with this resolver's domain.

The owner asked for:

1. a default destination for keys the server does not know, `https://id.gs1.org` by default, which the operator can
   change;
2. destinations by prefix: a request for **any** key of a prefix (the example: 9521234) is simply sent to the
   destination the operator set;
3. both switched on and off by the operator in the portal;
4. indicators of both in the operator's overview.

## 2. Decision

1. **Forwarding by prefix** (*prefix rules*): a rule is a prefix of 3 to 12 digits (a GS1 prefix of three digits, a
   GS1 Company Prefix, or a longer range), a destination (an `https` address) and a mode:
   - *keep the path* (default): the destination, then the request's GS1 Digital Link path and query string —
     `https://other-resolver.example/01/09521234000019/10/L1?linkType=gs1:pip`; another resolver answers it;
   - *always this address*: the destination as it is, for a site that is not a resolver.

   A request for a key whose GS1 Company Prefix (the value without the indicator, extension or filler digit for GTIN,
   ITIP, SSCC and GRAI — the company part the request log already uses) starts with an enabled rule's prefix is
   answered **307** to the rule's destination, **before this resolver's own records** (the rule says that the prefix
   is answered elsewhere); the longest prefix wins. A request that is not a valid GS1 Digital Link URI is still a 400.
   On an organisation's own domain (ADR 0009) only that organisation's keys are considered, as before.
2. **The resolver of last resort** (*fallback*): when switched on, a request whose answer would be a 404 for a key
   this resolver does not know (outcome `unknown`: no record; on an organisation's domain, a key outside its
   prefixes) is answered **307** to the destination with the request's path and query string — compressed links and
   EPC binary strings uncompressed. The destination is `https://id.gs1.org` until the operator sets another. A key
   that has records but lacks the link type asked stays a 404 (`noLink`), as does an invalid request (400).
3. **Order**: a prefix rule, then this resolver's records, then the resolver of last resort.
4. **In the portal**, server administrators (outside support access) manage both on a new screen, *Forwarding*: the
   resolver of last resort (on or off, its address) and the rules (add, edit, switch on and off, remove), each change
   a journal event (`forwarding-fallback`, `forwarding-rule-create`, `-update`, `-remove`). A rule whose prefix
   overlaps an organisation's prefixes is allowed, with the organisations named beside it: their codes of that
   prefix are no longer answered here.
5. **Destinations are checked**: `https` only, at most 500 characters, never this installation's own address
   (`RESOLVER_PUBLIC_URL`) nor one of its organisations' verified domains — a request sent back here would go round
   in circles.
6. **The request log** records the two new outcomes, `forwarded` (a prefix rule) and `fallback` (the resolver of last
   resort), with the destination's host as for any redirect; the *Requests* screen filters and shows them.
7. **The overview** (ADR 0007): the quality group counts both for every scope (a code of an organisation sent on by
   a rule is visible to it); server administrators see a *Forwarding* group: whether the resolver of last resort is on
   and where to, the requests sent to it in the period (and the previous one) with the codes most sent, the rules
   active, the requests sent by rules, and each rule's requests. The exports carry the same figures.

## 3. Design

- Portal's database: setting `forwarding.fallback` (`{"enabled", "url"}` in `settings`), collection
  `forwarding_rules` (`{_id: prefix, target, mode, enabled, note, created, createdBy, updated, updatedBy}`).
- `portal/forwarding.py`: `fallback()`, `set_fallback()`, `rules()`, `save_rule()`, `remove_rule()`, `overlaps()`,
  `check_target()`, `group()` (the overview's figures); `ForwardingError` with the message code.
- Routes (server administrators): `GET /portal/api/forwarding`; `PUT /portal/api/forwarding/fallback`;
  `POST /portal/api/forwarding/rules`; `PUT` and `DELETE /portal/api/forwarding/rules/<prefix>`.
- Resolver: `web_server/src/forwarding.py` (`Forwarding`: the enabled rules, longest prefix first, and the fallback,
  read from the portal's database at most every 30 seconds, the last ones kept when the database does not answer);
  `web_namespace._process_response()` applies them; `request_log.outcome()` keeps `forwarded` and `fallback`.
- Per-rule figures come from the request log's counts per key (`requestlog.collect()`) matched against the current
  rules: a rule changed during the period counts under its present prefix.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| The resolver of last resort at installation | **off**, its address filled in with `https://id.gs1.org` | on (every existing installation's 404s would change at the update, and GS1's resolver test suite expects 404 for an unknown key) |
| A prefix rule and this resolver's records | the rule first ("the prefix is answered elsewhere", as the owner described) | records first, the rule only for unknown keys (a rule would then be a second fallback) |
| The destination of a rule | the path kept by default; a fixed address as an option | always the path (a brand's site is not a resolver); always fixed (another resolver needs the code) |
| Shortest prefix | 3 digits (a GS1 prefix) | 4 (would leave out forwarding a country's codes) |
| Where the settings live | the portal's database, read by the resolver with a cache, as the domains and brands | `.env` (the owner asked for the interface; a restart for each change) |
| Per-rule counts | from the counts per key and the current rules | a new field in every event (a field of the log for an operator's view) |

## 5. Consequences

- With the resolver of last resort on, a code nobody registered here is no longer a 404: the overview's *codes
  nobody registered* becomes *sent to the resolver of last resort*; the 404 alerts (ADR 0008) count fewer requests.
- A rule takes a prefix's codes away from this resolver at once (within 30 seconds), its records included; the screen
  names the organisations concerned before saving.
- GS1's resolver test suite runs with forwarding off (the default).
- Nothing changes until the operator switches either on.
