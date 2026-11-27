# ADR 0027 — Every write of a key's document is conditional: no lost update

| | |
|---|---|
| Status | **Accepted** (17 November 2026); §4 (*The editor's own copy*) closed by [ADR 0058](0058-record-revision.md) (27 November 2026) for clients that send the record's revision |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); extends [ADR 0023](0023-record-level-delete.md) §2.2 to every write |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): the document as read is the revision checked by the write's filter, the data entry API reads again and applies the change on top of another writer's, and answers 409 when the key keeps changing; no revision field and no per-key lock |

## 1. Context

A key's records (the product's own, its batches, its serial numbers) are one document of the data entry API. Every
operation that changes them (`POST /new`, `PUT`, a `DELETE` of links) read the document, changed it in memory and
replaced it by its `_id` (`data_entry_db.update_document()`, `replace_one({"_id": ...})`). Two writers on one key —
two users of the portal, a spreadsheet import and an editor, the tenant API and the portal, two replicas of the data
entry API — could read the same document; the second write then undid the first, and both were answered as
successful and journalled as such. For the codes of medicines and medical devices a lost update can silently drop a
leaflet, a safety-information or recall-status link that someone has just added (threat model T-D3, G-8). A key that
did not exist was worse: two `POST /new` could both find no document; the second `insert_one` failed with 409, which
the portal reported as a refusal. ADR 0023 made the record-level delete conditional and left the other writes for
later.

## 2. Decision

1. **One write path.** Every operation of `data_entry_logic` that changes a document — `_process_document_upsert()`
   (`POST /new`, a single record or a list), `update_document()` (`PUT`), `delete_links()` (a `DELETE` naming links)
   and `delete_record()` (ADR 0023) — builds the new document with a function given to `_write_document()`, which
   reads the document, lets the function change a copy, and writes:
   - a key without a document with `data_entry_db.create_document()`, which refuses (409) an `_id` another writer
     created in the meantime;
   - any other with `data_entry_db.write_document_if_unchanged(document, expected)`, which replaces it — or deletes it
     when no record is left — only while the stored document is still `expected`, the document read: the filter names
     every field of it (`_id`, `defaultLinktype`, `data`). The document as read is the revision; one atomic operation
     on one document, so it holds across replicas of the data entry API.
2. **A refusal is not an error of the caller.** The change is a delta (links merged, links removed, a record added or
   removed), so on a 409 the operation starts again from a new read and applies itself on top of the other writer's
   change; both are kept. After `WRITE_ATTEMPTS` (3) refusals the answer is 409, with nothing written. Other answers
   decided while changing the document (404, 400) are raised as `_Refused` and returned unchanged.
3. **No unconditional replace is left.** `data_entry_db.update_document()` is removed.
4. **The answers say what happened.** A list sent to `POST /new` stops at the first item not written and answers its
   status, naming it, with `written` listing the items written before it (the official code answered 201 for the whole
   list whatever happened to each item). `POST /new` on an existing key answers the write's own error (the official
   code answered 200 when the update failed).
5. **The portal tells the user.** A 409 of the data entry API for a write (`POST /new`, `PUT`, the record-level delete,
   fixing serial numbers, the explicit default links) becomes `upstream.conflict`, answered with 409 rather than 502
   (`refused_upstream()`): the key's records were being changed by someone else at the same moment, nothing of this
   change was applied, open the record again and repeat it. The text is in the twelve languages; the journal names the
   attempt as failed (`change-failed`, ADR 0026); the tenant API documents the 409 (`portal/openapi.json`, response
   `Conflict`).

## 3. Consequences

- Two writers on one key no longer overwrite each other in the data entry API: each operation is applied whole on the
  document the other left, or not at all with a 409.
- An integrator of the official API sees 409 where a lost update used to happen, and a list to `POST /new` that fails
  part way answers its error instead of 201. Both belong in the pull request offered to the official project.
- Options not taken: a revision field incremented by every write (`$inc`) — it would need every existing document and
  every other tool that writes the collection to keep it, while the document as read gives the same guarantee; a lock
  per key — it needs a lock shared by the replicas and a way to recover a lock its holder never released.

## 4. Residuals

- **The editor's own copy.** The editor and the tenant API send the record as the user wants it, and the portal
  computes the links to remove from the record it reads at the moment of the save. A user who saves a record opened
  minutes before still replaces what another user saved in between on the *same* record (the last save wins, at the
  level of links); both versions are in the journal and the record's history, from which the first can be restored.
  An `If-Match` revision carried by the editor and the tenant API from the read to the save would refuse that save
  instead; it is left for a later step.
  > Closed by [ADR 0058](0058-record-revision.md): the editor and the tenant API's reads give the record's revision
  > (`ETag`), and a save or delete that sends it back as `If-Match` is refused with 412 `record.changed` when the
  > record changed in between; without the header, as before.
- **The portal's save is two calls when links are removed** (`PUT`, then a `DELETE` of links). A conflict on the
  second leaves the first applied: `upstream.partialUpdate` asks the user to save again, as before.

## 5. Checks

`test_data_entry_api` (`PUT`, `POST /new` and a `DELETE` of links racing another writer: read again, both changes
kept; two writers creating one key; a key that keeps changing → 409 with nothing written; a list stopping at the item
not written; a failed write no longer answered 200; the database layer on mongomock: the default link type changed →
409, no unconditional replace left), `test_record_delete` (the editor's save and delete, the tenant API's save and
delete and fixing serial numbers answer 409 `upstream.conflict`, the records unchanged, the attempt journalled as
failed) and `test_mock_parity` (the stand-in against the real API with conditional writes). 8 mutations, all caught.
