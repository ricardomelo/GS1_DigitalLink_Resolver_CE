# ADR 0058 — A record's revision, from the read to the save: no save over a change not seen

| | |
|---|---|
| Status | **Accepted** (27 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D3 and gap G-8 of the [threat model](../threat-model.md); the first residual of finding F-009 ([ADR 0027](0027-conditional-writes.md) §4) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — a revision of each record (a hash of what the record holds), given as an `ETag` by the editor's and the tenant API's read, sent back as an optional `If-Match` (or `If-None-Match: *` for a record that did not exist) on the save and the delete, and checked by the data entry API inside its conditional write; a save without the header behaves as before. Not taken: the header required (every organisation's integration and spreadsheet import would break at the update); a revision number stored in the document (every document written before, and every other tool that writes the collection, would have to keep it — ADR 0027 §3); the check in the portal only (a writer between the portal's read and its write would still be overwritten) |
| Amends | [ADR 0027](0027-conditional-writes.md) §4 (*The editor's own copy*): closed for clients that send the header |

## 1. Context

ADR 0027 made every write of a key's document conditional on the document as read **by the data entry API**, a few
milliseconds before it writes. The editor and the tenant API work on a longer span: a user opens a record, changes it
for some minutes and saves; the portal then sends the record as the user wants it, and computes the links to remove
from the record as it reads it at the moment of the save. A second user who saved the same record in between is
overwritten without being seen: the first user's save replaces the description, and the links the second user added
are removed because the first user's copy does not have them. Both saves are journalled as successful, and the record's
history keeps the lost version, but nobody is told. For the codes of medicines and medical devices, the link lost can be
the leaflet or the recall notice that the second user had just added.

## 2. Decision

### 2.1 The revision

A record's revision is the first 20 hexadecimal digits of the SHA-256 of what the record holds, as the data entry API
gives it (`GET /api/{AI}/{value}`, one entry per record): its qualifiers, item description, links and informative
qualifiers, in canonical JSON (keys sorted, no spaces, UTF-8; a field missing taken as empty). The key's default link
type and the anchor are left out: the portal changes them for the key's other records in the same save (explicit
default links, ADR 0011; the key's own record, section 2.5.9), and they are not this record's content. The same function
is in the data entry API (`data_entry_server/src/revision.py`) and the portal (`portal/revision.py`), and a check holds
them equal. Nothing is stored: a record written by any tool, before or after this change, has a revision.

### 2.2 The data entry API

`PUT /api/{AI}/{value}`, a `DELETE` naming links or a record (`removeRecord`, ADR 0023) and `POST /new` read two
optional headers:

| Header | Meaning | Refused with 412 when |
|---|---|---|
| `If-Match: "<revision>"` (one or more, comma-separated; `W/` and the quotes are optional) | the record named by the body is still the one read | the record has another revision, or no longer exists |
| `If-Match: *` | the record exists | it does not |
| `If-None-Match: *` | the record does not exist yet (a creation only) | a record with those qualifiers exists (for `POST /new`, any record the body names) |

The check runs inside the function that builds the new document (`_write_document()`, ADR 0027), on the document
just read, and the write is conditional on that same document: a writer between the check and the write makes the write
fail, the operation reads again and checks again. The check and the write are therefore one atomic step, across replicas.
A 412 writes nothing (`{"error": "Record changed since it was read", "revision": <the current one, or null>}`). A
successful write answers the record's new revision (`revision` in the body; `null` when the record was removed).

### 2.3 The portal

- **Read.** `GET /portal/api/record` (the editor) answers the record's revision as `revision` in the body and as an
  `ETag` header (none when the record does not exist); `GET /portal/api/v1/records/{key}/{value}` (the tenant API)
  answers the `ETag` header.
- **Save and delete.** `POST /portal/api/record`, `DELETE /portal/api/record`, `PUT` and `DELETE
  /portal/api/v1/records/{key}/{value}` take the same optional headers. The portal checks them on its own read first
  (no journal entry and no call for a save already out of date), then passes them to the data entry API with the first
  write of the record. When a save removes links (`PUT`, then a `DELETE` of links), the `DELETE` carries the revision the
  `PUT` answered, so a writer between the two calls is not overwritten either (it fails the second call, as before
  `upstream.partialUpdate`). A successful save answers the record's new revision (`revision` and `ETag`).
- **Refusal.** 412 with the message `record.changed` (twelve languages): someone else saved or deleted this record after
  it was opened; nothing was saved; open it again to see that version, then make the change again. The tenant API's
  description (`portal/openapi.json`) documents the headers, the `ETag` and the 412.
- **The editor** keeps the revision of the record it opened and sends it with the save and the delete (`If-None-Match:
  *` for a record that did not exist when it was opened), keeps the revision each save answers, and on a 412 shows the
  message with a button that opens the record again (asking first, as always, before unsaved changes are discarded).

### 2.4 What does not change

A save or delete without the headers works as before (the last save wins at the level of links, ADR 0027 §4): the
spreadsheet import, the fixing of serial numbers, the explicit default links of the key's other records and every
existing integration of the tenant API. The official data entry API keeps its answers for requests without the headers.

## 3. Consequences

- Two users of the editor on one record: the second save is refused with a message instead of silently replacing the
  first; the user sees the other version before changing it again.
- An integration of the tenant API can do the same by sending back the `ETag` it read.
- Options not taken: the header required (`428 Precondition Required`) — every organisation's integration and the
  import would break at the update, for a protection a client can take when it needs it; a stored revision number — it
  would need every document written before, and the official tools, to keep it; the check in the portal only — the
  data entry API is the one place where the check and the write can be one step.

## 4. Residuals

- **Optional.** A client that sends no header (the import, an integration that does not) keeps the last save wins.
- **Two calls.** A save that removes links is still two calls; a writer between them now fails the second, which leaves
  the first applied (`upstream.partialUpdate`, ADR 0027 §4, the second residual of F-009).
- **The key's default link type** is not part of the revision: a change of it by another record's save is not refused
  here (the portal refuses a save whose default link type differs from the key's, `default.sharedMismatch`).

## 5. Delivery

`data_entry_server/src/revision.py` (new), `data_entry_logic.py` (`precondition()`, the check in each write's
function, `revision` in the answers), `data_entry_namespace.py` (the headers read); `portal/revision.py` (new),
`portal/app.py` (`get_record()`, `save_record()`, `delete_record()`, `store_record()`, `remove_record()`,
`delete_one_record()`), `portal/api_v1.py` (`ETag`, the headers), `portal/openapi.json` and
`Documentation/api-reference.md`; `portal/static/app.js` (the editor) and the texts `record.changed` and
`record.reopen` in twelve languages; `dev-tests/portal/mock_data_entry.py` (the same headers).

## 6. Checks

`test_record_revision` (new: the three functions equal; the editor's read, save and delete and the tenant API's with
and without the headers; a save out of date refused before any call or journal entry; a writer between the portal's
check and its write refused by the data entry API; the `DELETE` of links holding to the `PUT`'s revision; the key's own
record not written by a save out of date; the description of the tenant API), `test_record_revision_e2e` (new: the
editor in Chromium, two users on one record, the message and the button, Portuguese, the delete),
`test_data_entry_api` (the headers on every write of the data entry API, 412 with nothing written, the revision
answered, another writer between the read and the write) and `test_mock_parity` (the stand-in against the real API).
16 mutations, all caught.
