# ADR 0059 — A save that removes links, in one write

| | |
|---|---|
| Status | **Accepted** (27 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D3 of the [threat model](../threat-model.md); the second residual of finding F-009 ([ADR 0027](0027-conditional-writes.md) §4, [ADR 0058](0058-record-revision.md) §4) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — an optional `removeLinks` list on the data entry API's `PUT`, the links it names removed in the same conditional write as the links sent are merged. Not taken: a `PUT` that replaces the record's links with those sent (it would also remove a link another writer added between the portal's read and its write, which the merge keeps today, ADR 0027 §2); a transaction across the two calls (MongoDB transactions need a replica set, which the installation does not have, and the data entry API would still answer the two calls separately) |
| Amends | [ADR 0027](0027-conditional-writes.md) §4 (*The portal's save is two calls*) and [ADR 0058](0058-record-revision.md) §2.3 and §4 (*Two calls*): closed |

## 1. Context

The data entry API merges the links a `PUT` sends into the record (by link type, language and context) and never
removes one; a link is removed by a `DELETE` naming it. So the portal saved a record whose user had removed links in
two calls: the `PUT` with the record as the user wants it, then a `DELETE` of the links no longer there. When the second
call failed (the data entry API unreachable for a moment, another writer in between with `If-Match`, ADR 0058), the
first was already applied: the new targets saved, the old ones still there, and the user told to save again
(`upstream.partialUpdate`). For the codes of medicines and medical devices, the target left in place can be the
withdrawn leaflet the user meant to replace.

## 2. Decision

### 2.1 The data entry API

`PUT /api/{AI}/{value}` takes an optional `removeLinks`: a list of links, each named by its `linktype` (a string) and,
when it has them, its `hreflang` and `context` (lists of strings), matched as a `DELETE` of links matches them. The
links sent in `links` are merged first, then the links named are removed, in the same change of the document and the
same conditional write (`_write_document()`, ADR 0027): on a conflict the whole operation is applied again on top of
the other writer's change, and with `If-Match` the check covers both (ADR 0058).

- A link named that the record does not hold is ignored (the end state is the one asked for); the answer counts those
  removed (`removedLinks`). A `PUT` without `removeLinks` answers as before, without the count.
- Refused with 400, nothing written: `removeLinks` that is not such a list; a link both sent in `links` and named in
  `removeLinks`; a record that would keep no link.

### 2.2 The portal

`store_record()` (the editor, the tenant API and the spreadsheet import) sends one `PUT` for an existing record, with
`removeLinks` naming the links the user removed (the record's links as the portal read it, less those it sends). It no
longer sends a `DELETE` of links. Refused, the save leaves the record as it was (`upstream.updateRejected`,
`upstream.conflict` or `record.changed`, as for any write). An answer without `removedLinks` to a `PUT` that named
links comes from a data entry API without this change, which ignored them: the portal does not take it for done and
answers `upstream.partialUpdate` (the new targets saved, the old ones not removed).

## 3. Consequences

- A save is applied whole or not at all; `upstream.partialUpdate` no longer happens with the installation's own data
  entry API.
- Only the links the user removed are named: a link another writer added between the portal's read and its write is
  kept, as the merge kept it before (without `If-Match`); with `If-Match` that writer's save refuses this one.
- The official data entry API ignores `removeLinks`; a portal in front of it answers `upstream.partialUpdate` for a save
  that removes links (it would need the `DELETE` again: not supported, the portal ships with its data entry API).
- The data entry API's `DELETE` of links is unchanged for other clients.

## 4. Delivery

`data_entry_server/src/data_entry_logic.py` (`remove_links_problem()`, the removal in `update_document()`,
`removedLinks`), `data_entry_namespace.py` (the `PUT`'s description); `portal/app.py` (`store_record()`);
`dev-tests/portal/mock_data_entry.py` (the same field).

## 5. Checks

`test_data_entry_api` (the links named removed in the same write, `removedLinks`, a link already gone, the 400s, with
`If-Match` and racing another writer), `test_mock_parity` (the stand-in against the real API), `test_record_revision`
(one `PUT` naming the links removed, with and without `If-Match`; refused, the record unchanged and no `DELETE` sent;
another writer's link kept; a data entry API that does not count them: `upstream.partialUpdate`; the tenant API) and
`test_journal` (a save that removes links refused: `change-failed` `upstream.updateRejected`). 9 mutations, all caught.
