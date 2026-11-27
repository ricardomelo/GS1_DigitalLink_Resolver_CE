# ADR 0049 — Anchors of one shape, one document id per anchor, in the data entry API

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the *GS1 data* control of the [threat model](../threat-model.md); finding U-004 (code from the official project) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken — every anchor sent to the data entry API is `/AI/value` with a GS1 primary key, and a document id splits at its first `_`, so stored documents keep their ids. Not taken: a new id format (every document of every installation rewritten, the resolver reading two formats during the upgrade); escaping `_` in values (the same rewrite, for values the portal does not even allow); deleting or rewriting the documents written before under other anchor shapes (they are listed instead, readable and removable); letting the portal accept `_` in key values (a change of its forms and hints in twelve languages, not needed to close the finding — a later backlog item if asked for) |
| Amends | the official data entry API (`data_entry_server/src/data_entry_logic.py`, `data_entry_db.py`, `data_entry_namespace.py`) and the resolver's database layer (`web_server/src/web_db.py`), deliberately; recorded in the CHANGELOG |

## 1. Context

The official data entry API turned an anchor into a document id by replacing **every** `/` with `_`
(`/01/09506000134352` → `01_09506000134352`) and read an id back by replacing **every** `_` with `/`. Three faults
followed:

- **A value with `_` came back under another anchor.** GS1 values of character set 82 (GIAI, GRAI's serial, GDTI,
  GINC, GMN…) may hold `_`: `/8004/9506000AB_12` was stored as `8004_9506000AB_12` and listed, read and answered as
  `/8004/9506000AB/12`.
- **Two anchors, one document.** `/8004/A/B` and `/8004/A_B` had the same id; so had `GET /api/8004_A/B` and
  `GET /api/8004/A_B`, and the resolver read the document of `/8004/A_B` for a request for `/8004/A%2FB`.
- **Anchors of any other shape skipped the checks.** `registration_problem()` and `value_problem()` returned at once
  for an anchor without exactly two slashes, so `/01/09506000134352/10/ABC`, `/99/X` or `/gtin/1` were stored without
  any rule, under ids nobody else reads. The portal never sends `_` in a key value (`portal/gs1.py`
  `PORTAL_EXCEPTIONS["key_chars"]`) and hides what it cannot parse, so such documents existed without appearing in any
  list.

## 2. Decision

1. **One anchor shape.** `anchor_problem()` refuses, with 400, every anchor sent to `POST /new` (a v3 entry's
   `anchor`; a v2 entry's `identificationKeyType` and `identificationKey`), `PUT` (the anchor of the record changed)
   and `POST /validate` that is not `/AI/value`: exactly two slashes, an AI among the sixteen GS1 Digital Link primary
   keys (`KEY_AIS`: 00, 01, 253, 255, 401, 402, 414, 415, 417, 8003, 8004, 8006, 8010, 8013, 8017, 8018 — the portal's
   `PRIMARY_KEYS`, compared by the tests), and a value of printable ASCII characters other than `/` and space (GS1
   values are ASCII). Qualifiers go in `qualifiers`. The registration and value checks therefore run for every entry.
   A list is refused whole, naming the item.
2. **One document id per anchor.** The AI is digits only, so the first `_` of an id ends it: `/8004/A_B` ↔
   `8004_A_B` (`convert_path_to_document_id()`, `document_id_to_anchor()`, `data_entry_db._reformat_id_for_db()` and
   `_reformat_id_for_external_use()`, `read_index()`, `_convert_mongo_linkset_to_v3()`). Every id the official code
   wrote for a `/AI/value` anchor whose value had no `_` is unchanged: **no stored document is rewritten**.
3. **Paths.** `GET`, `PUT` and `DELETE /api/{AI}/{value}` answer 400 when the AI part holds `_` (`/api/8004_A/B` named
   the document of `/8004/A_B`); `GET /api/{AI}/{value}/{more…}` answers 400 (it read the document a malformed anchor
   had written).
4. **The resolver.** `web_db._reformat_id()` turns only the slash right after the AI's digits into `_`; an id is
   returned unchanged. A value with a `/` (a `%2F` in the request) gives an id no document has, never another
   anchor's document.
5. **Documents written before.** A document written by the official code from an anchor of another shape keeps its
   id and is read, listed (`/summary`, `/index`) and removed under the anchor its id now gives (`01_X_10_Y` →
   `/01/X_10_Y`); a `PUT` of it passes only if that anchor passes the rule. The portal still hides it (it is not a key
   value the portal accepts).

## 3. Consequences

- An integration that sent anchors carrying qualifiers (`/01/…/10/LOT`), other AIs, or values with spaces or
  characters outside ASCII is answered 400 after the upgrade: the release notes say so. Such records could not be
  resolved: the resolver checks a request's syntax and reads the id of its `/AI/value` only.
- A key value with `_` sent through the API is now stored, listed and resolved under its own anchor.
- The portal sees no change: it only sends `/AI/value` anchors of its sixteen keys, without `_` in key values.
- No new text in the user interface: the API's messages are in English, as its other refusals.

## 4. Residuals

- Documents written before under other anchor shapes are not changed; the operator removes them with
  `DELETE /api/{AI}/{value}`. Since [ADR 0056](0056-records-outside-the-rules.md) they are reported in the portal
  (*Records outside the rules*, *Organisations* screen).
- The portal still refuses `_` in key values (`PORTAL_EXCEPTIONS["key_chars"]`): its reason is gone, its forms and
  hints are unchanged.
- The list of primary keys exists twice (portal, from the dictionary; data entry API, written out); the comparison
  test keeps them equal, and a new dictionary release with a new key fails it.

## 5. Delivery

`data_entry_server/src/data_entry_logic.py` (`KEY_AIS`, `_ANCHOR`, `entry_anchor()`, `anchor_problem()` called by
`registration_problem()`; `convert_path_to_document_id()`, `document_id_to_anchor()`; `read_index()`,
`_convert_mongo_linkset_to_v3()`, `_stored_hrefs()`); `data_entry_db.py` (`_reformat_id_for_db()`,
`_reformat_id_for_external_use()`); `data_entry_namespace.py` (`_document_id()`, `ANCHOR_PATH_ERROR`; the route with
more segments); the Swagger description of `anchor`; `web_server/src/web_db.py` (`_reformat_id()`);
`useful_external_python_scripts/convert_data_entry_between_v3_and_linkset_db_format.py` (the first `_` only); the
portal's stand-in `dev-tests/portal/mock_data_entry.py`.
Tests: `test_data_entry_api.py` (12 malformed anchors refused by `POST /new`, nothing stored; no anchor; a v2 key
with a slash refused and a valid one accepted; a list refused whole; `POST /validate`; the primary keys the portal's;
a value with `_` stored under one id, read, listed in `/summary` and `/index` and changed under its own anchor; `GET`,
`PUT` and `DELETE` of a path whose AI part has `_` and `GET` of a path with more segments refused, the document
untouched; ids and anchors one to one; documents of other shapes listed under the anchor their id gives, a `PUT`
refused, a `DELETE` accepted; the database layer on mongomock), `test_mock_parity.py` (three malformed anchors and a
path with `_` answered 400 by both), `test_resolver.py` (a value with `_` resolved to its record, `%2F` not reading
it, the resolver's mapping). 15 mutations, all caught.
