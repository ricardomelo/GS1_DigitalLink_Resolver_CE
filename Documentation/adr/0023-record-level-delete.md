# ADR 0023 — A record-level delete in the data entry API

| | |
|---|---|
| Status | **Accepted** (15 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): the data entry API gains a record-level delete, the portal uses it, rather than journalling the key's pre-image and reconciling it later |

## 1. Context

A key's records (the product's own, its batches, its serial numbers) are one document of the data entry API. The
official API deletes whole documents only (`DELETE /api/{ai}/{value}` without a body), or some links of one record (a
body naming `links`). To delete one record — the editor's *Delete*, the tenant API's `DELETE /records/…`, and *Fix
serial numbers*, which registers a record again under other qualifiers — the portal deleted the key's document and
posted the other records back (`rewrite_document()`): it checked them first with `POST /api/validate` and posted the
original back when the write was refused.

That left two failures that no check could prevent. Between the two calls every code of the key answered 404, or went
to the resolver of last resort: the product's leaflet, safety information and recall status included. And when the
portal, the network or the data entry service failed after the delete, nothing restored the key: its records stayed
gone until someone noticed, and the journal's versions had to be restored by hand. For a resolver meant for medicines
and medical devices this is a hazard (threat model T-D4, H-11). A side effect: a key holding a record the API now
refuses (made before a rule, or by another tool) could not lose any record, since the others could not be written back.

## 2. Decision

1. **The data entry API removes one record in one write.** `DELETE /api/{ai}/{value}` with the body
   `{"removeRecord": true, "qualifiers": [{"10": "L1"}]}` removes the record with those qualifiers (in any order; none,
   or `[]`, for the key's own record) and keeps the document's other records untouched. The document is replaced
   without the record, or deleted when it was the last one. 200 with `removed` and `remaining`; 404 when the document
   or the record does not exist; 400 for `removeRecord` other than `true`, `links` in the same body, or qualifiers that
   are not a list of one-AI objects with string values. A body without `removeRecord` keeps its meaning (links, or a
   400); no body still deletes the whole document, as in the official API.
2. **The write is conditional.** `data_entry_db.write_document_if_unchanged()` replaces (or deletes) the document only
   while its records are still the ones read (the filter names `_id` and `data`), so a change made by another writer
   between the read and the write is not lost: the operation reads the document again, up to three times, then answers
   409 with nothing removed. This closes the lost update for this operation only; the general one (F-009, U-005) is
   for later. *Note (17 November 2026, [ADR 0027](0027-conditional-writes.md)):* every write of a key's document now
   goes this way (`_write_document()`); the filter names every field of the document read, not only `data`, and
   `RECORD_DELETE_ATTEMPTS` became `WRITE_ATTEMPTS`.
3. **The portal uses it everywhere it removed a record.** `remove_record()` (the editor and the tenant API) makes one
   call; nothing is written back, so nothing is checked first, and a key holding a record the API would refuse no
   longer blocks a deletion. *Fix serial numbers* writes each record as the serial number alone (`POST /new`), then
   removes the old one: the serial number answers at every step, with one record or the other. The new records are
   checked with `POST /api/validate` first, and nothing is written when one would be refused (`record.rewriteRefused`,
   as before). When a step fails, what was done is journalled and the answer is 502; a second run finishes the key,
   since an old record then repeats the new one and is removed as a duplicate. `rewrite_document()` is gone, with the
   message `upstream.deleteRestored`.
4. **The portal's stand-in for the API** (`dev-tests/portal/mock_data_entry.py`) does the same, and
   `test_mock_parity.py` compares the two.

## 3. Consequences

- No window and no failure mode in which deleting one record leaves the key without its others; a failed delete leaves
  every record in place (`upstream.deleteFailed`).
- The official API gains an operation. An integrator who sends no `removeRecord` sees no change. It belongs in the
  pull request offered to the official project with the other data entry fixes.
- The portal now needs a data entry API of the same release; both are always built and deployed together by
  `docker compose`, so no fallback to the two calls is kept (it would bring the window back).
- Option not taken: journalling the key's whole document before the rewrite and reconciling it at start-up. It would
  have kept the window, and repair would have depended on the portal starting again.

## 4. Checks

`test_record_delete` (portal: the calls the portal makes, the API failing at each step, the tenant API, fixing serial
numbers), `test_data_entry_api` (the operation, its refusals, a document changed in between, the database layer on
mongomock) and `test_mock_parity` (the stand-in against the real API).
