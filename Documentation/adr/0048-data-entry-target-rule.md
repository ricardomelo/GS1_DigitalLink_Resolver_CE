# ADR 0048 — The data entry API applies the portal's target rule

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D2 and gap G-12 of the [threat model](../threat-model.md); finding U-003 (code from the official project) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken — the rule of [ADR 0037](0037-target-addresses.md) §2.1 for every target the data entry API is sent, a target the key's document already holds accepted as it is. Not taken: a setting that lets an operator switch the rule off or allow `http:` (no installation has asked for one; the portal has no such switch either); refusing targets already stored (a rewrite of an old record by the portal would then fail for a target it did not choose, and the records would stay in the database anyway); the per-organisation host lists of ADR 0037 §2.2 (the data entry API does not know organisations); a check that the target answers (a request from the server for every write) |
| Amends | the official data entry API (`data_entry_server/src/data_entry_logic.py`, whose `_validate_data()` is a stub that returns every document unchanged), deliberately; recorded in the CHANGELOG |

## 1. Context

The official data entry API stores whatever `href` it is sent: `javascript:` and `data:` addresses, `http:`, an IP
address or a name inside the operator's network. The resolver then redirects a person who scans the code to it. The
portal checks every target it saves (ADR 0037: HTTPS only, no user information, no address literal, no private name),
but any other client of the API — an integration, a script, the API's own Swagger page — went past that rule.
The API has been closed to every address `DATA_ENTRY_API_ALLOW` does not list since [ADR 0021](0021-data-entry-api-closed.md)
(finding F-001), and the resolver's pages list a target that is not a web address without a link; neither stops a
redirect to such a target, which is what a scan does.

## 2. Decision

1. **The same rule as the portal's.** `data_entry_server/src/target_rule.py` holds a copy of the portal's
   `normalise_url()` / `target_host_problem()` / `host_problem()` (the data entry API is an image of its own and does
   not import the portal): a target is an `https:` address with a host; no spaces, line breaks, control or invisible
   characters or backslashes; no user name or password before the host; no IP address however a browser reads one
   (IPv6, a last label that is a number in decimal, octal or hexadecimal, full-width digits); no name without a dot,
   with an empty label, with characters other than letters, digits, `-` and `_` in ASCII, or ending in one of the
   private top-level names (`localhost`, `local`, `localdomain`, `internal`, `intranet`, `lan`, `home`, `corp`,
   `test`, `onion`, `alt`, `arpa`); a port, if any, a number. A target with spaces around it is refused, not trimmed.
2. **Where.** `POST /new` (a single entry, a list — the whole list is checked before anything is written — and the
   legacy v2 format's `targetUrl`), `PUT` (the links it sends) and `POST /validate` answer **400** naming the link and
   the reason, e.g. `link 2 ('http://example.com/p'): a target address must be an https address with a host name and,
   if any, a numeric port`; nothing is written. Deletions are not checked.
3. **A target the key already holds is accepted as it is.** A target found anywhere in the key's stored document is
   not checked again: records saved before this rule keep working, and the portal's rewrites of them (explicit default
   links copied from a record's own targets; the serial-number fix, which writes a record again with its targets) are
   not refused for a target the person did not choose. A new target, even on the same key, follows the rule.
4. The portal's and the API's rules are compared address by address in `dev-tests/resolver/test_data_entry_api.py`
   (47 addresses, the same codes, the same private names), so that they cannot drift apart.

## 3. Consequences

- An integration that sent `http:` targets, or targets on an internal name, is answered 400 after the upgrade: the
  release notes say so. Its existing records are not changed and keep resolving.
- The portal sees no change: it already refuses the same targets, with its own messages in twelve languages, before
  it calls the API. Its `POST /validate` calls before a rewrite now also report a new target outside the rule.
- No new text in the user interface: the API's messages are in English, as its other refusals.

## 4. Residuals

- Targets stored before the rule are not reported or changed (as in ADR 0037 §4 for the portal).
- Between the check of `POST /new` and its write, another writer may remove the target that made one acceptable; the
  write then stores a target that was in the document a moment before (no new target reaches the database this way).
- The per-organisation host lists (ADR 0037 §2.2) apply in the portal only.
- A public name may still resolve to a private address (DNS rebinding, the person's own network), as in the portal.
- The rule exists twice (portal and data entry API); the comparison test keeps them equal.

## 5. Delivery

`data_entry_server/src/target_rule.py` (new: `target_problem()`, `hrefs_problem()`, `document_hrefs()`, `REASONS`,
`PRIVATE_TOP_NAMES`); `data_entry_server/src/data_entry_logic.py` (`_sent_hrefs()`, `_stored_hrefs()`,
`target_problem()`, called by `create_document()`, `update_document()` and `validate_documents()`); the Swagger
description of `href` and of `POST /validate`.
Tests: `test_data_entry_api.py` (18 targets refused by `POST /new` naming the link and the reason, nothing stored; a
list refused whole for one target; a v2 `targetUrl`; four accepted forms; `PUT` refusing a new target, the document
unchanged; a target the key holds accepted by `PUT`, by `POST /new` of another record and by `POST /validate`, not on
another key and not a new `http:` target on the same key; the 47 addresses compared with the portal's rule, the same
private names, spaces around a target refused). 14 mutations, all caught.
