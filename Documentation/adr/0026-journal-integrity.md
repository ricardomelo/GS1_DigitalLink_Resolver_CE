# ADR 0026 — The journal: written before a record changes, sealed in hash chains, verified

| | |
|---|---|
| Status | **Accepted** (16 November 2026); step 2 in progress: the alert delivered on 16 November 2026 (§2.5.1), insert-only access to follow |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); amends [ADR 0001](0001-portal-state-in-mongodb.md) §3.5 and the journal of [ADR 0002](0002-tenants.md) §3.5 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): a record change is journalled before the data entry API is called and refused when it cannot be; every event is sealed in a hash chain per audit trail and retention category, with a key kept outside the database; administrators verify the chains and can keep a chain's head as a receipt |

## 1. Context

The journal (`portal/journal.py`) is the portal's audit trail and the source of a record's history: who changed which
link, when, and the record's full content at each version. For the codes of medicines and medical devices it is the
evidence the ALCOA+ principles ask for: attributable, complete, enduring. Finding F-008 of the security assessment
showed three gaps.

1. **Best effort.** `log_event()` wrote the event after the change and only logged a warning when it could not: a
   record changed in the data entry API (another service, another database) while the portal's database refused the
   event left no trace at all. The changes `store_record()` makes to a key's other records when it turns them to
   explicit default links (ADR 0011, amendment) were never journalled.
2. **No tamper evidence.** Anyone holding the portal's database user, MongoDB's root user (which the resolver and the
   data entry service hold, F-012) or a backup could change or delete events, and nothing would show it.
3. **Nothing outside the database** recorded what the journal held, so a whole rewrite was undetectable.

Changes made through the official data entry API leave no event; [ADR 0021](0021-data-entry-api-closed.md) closed
that API to the internet, and its own journal remains a step of item 10.1. A reason for each change and a second
signature (electronic signatures in the sense of regulated systems) are not part of this decision (§5).

## 2. Decision

### 2.1 A record change is journalled first

1. **The event is written before the data entry API is called**, for every record change: the editor, the tenant API,
   spreadsheet imports, *Fix serial numbers*, and now the records `store_record()` turns to explicit default links
   (one `update` event each). It is written immediately before the call that changes the key, after every check the
   portal makes itself, so a refused save (a rule of the standard, a prefix) writes nothing.
2. **When the event cannot be written, nothing changes**: the answer is 503 with the message `journal.unavailable`
   (twelve languages), and the data entry API is not called.
3. **When the change then fails** (the API refuses it, cannot be reached, or a partial update stops half way), a
   second event `change-failed` names the attempt (`ref`: its chain and sequence number) and the message code. The
   record's history leaves out failed attempts; the audit trail shows both.
4. **What remains.** If the portal stops between the event and the API's answer, the attempt stays without an outcome
   and the history may show a version that never became current; the record itself is always read from the data
   entry API. If the database fails between the change and the second event, the attempt is shown as made. Both are
   logged.
5. **Other events** (sign-ins, administration, settings) keep being written after their change: that change is a
   write to the same database, so the journal fails with it rather than alone. A failure is now logged as an error.

### 2.2 Every event is sealed in a hash chain

1. **One chain per audit trail and retention category**: `<tenant id or "operator">/<session|record|admin>`. The
   retention of a category (ADR 0001 §3.5) deletes its oldest events first, so a chain only ever loses its beginning;
   a chain for the whole trail would lose events in the middle.
2. **Each event carries** `chain`, `seq` (1, 2, … within the chain), `prev` (the previous event's `hash`, empty for the
   first), `hash` (SHA-256 of the event's canonical JSON: every stored field except `_id`, `expiresAt`, `hash` and
   `mac`, keys sorted, dates to the millisecond as MongoDB stores them), `mac` (HMAC-SHA-256 of `hash` with the
   journal key) and `kid` (the key's identifier: the first 8 hexadecimal digits of the SHA-256 of the key).
3. **Numbering is safe across replicas**: a unique index on `(chain, seq)`; a writer that loses the race reads the head
   again and retries. `journal_heads` keeps each chain's last sequence number and hash outside the retention, so a
   chain whose events have all expired continues its numbering, and deleting the newest events is seen.
4. **Events written before this version are sealed at the first start** of the new version, in the order they were
   written, marked `sealed: "upgrade"`: the chain proves that they have not changed since the upgrade, not since they
   were written. Events an older replica writes during a rolling upgrade are sealed at the next start.

### 2.3 The journal key

`PORTAL_JOURNAL_KEY` in `.env`, shared by every replica and the worker, never stored in the database. The installer
writes one (also when it upgrades an installation without it); `scripts/rotate-secrets.sh journal` replaces it, and
events sealed with the former key then keep their links checked but their `mac` is reported as made with another key.
Without a key the portal starts, seals the chains without `mac`, warns at start-up, and the verification says the
journal is not keyed: anyone able to write to the database could then rewrite a whole chain consistently.

### 2.4 Verification

1. **`journal.verify()`** walks a chain by sequence number and reports the first problem: an event changed (`hash`), a
   seal not made with the key (`mac`), a broken link (`prev`), a missing event (`gap`), a chain that starts after 1 in
   a category kept for ever (`start`), a chain shorter than its head (`truncated`), events not yet sealed, and a head
   kept by the administrator that is not in the chain (`receipt`).
2. **`GET /portal/api/audit/verify`** (administrators): the chains of the request's audit trail (an organisation's
   three; for a server administrator outside support access, every chain), each with its events, first and last
   sequence numbers, result and head (`<chain>:<seq>:<hash>`). `?receipt=<chain>:<seq>:<hash>` checks a head kept
   earlier.
3. **The Audit screen** gains *Verify integrity*: one line per chain with its result and its head, which the
   administrator can copy and keep outside the server as a receipt, and a field to check a receipt.
4. **Every day** the worker's housekeeping verifies every chain and writes each head to the portal's log, which leaves
   the database (container logs, a log collector); a broken chain is logged as an error.

### 2.5 Later steps of this decision

1. **An alert** (ADR 0008) when the daily verification finds a broken chain, by e-mail to the server administrators.
   *Delivered (session 40, the owner away, recommended options):* `checkpoint()` stores its result in the setting
   `journalVerified`; an administrator's verification brings it up to date for the chains it walked (a broken chain
   added, a whole one taken out; a wrong receipt is shown to whoever typed it and never stored); the monitor's check
   `journal` reads it every round (an alert while a chain is broken, reminded daily, resolved with a message when every
   chain is whole again) and the overview shows it with the other checks. Messages `alert-journal` and
   `alert-journal-ok` in the category `alerts` (ADR 0008 §3.1 says why not `security`).
2. **Insert-only access**: the journal moves to a database of its own on which the portal's MongoDB user may find and
   insert only; retention changes and sealing at the upgrade run in `portal-db-init` with the root user.

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Order of a record change | event first, refused without it, `change-failed` after a failure | event after the change, change undone when it cannot be written (a second call that can fail too); a transaction (two services, two databases; MongoDB without a replica set) |
| Other events | after their change, error logged | journal first everywhere (some sixty places; the change and its event fail together anyway) |
| Chain | per audit trail and retention category | one chain for the installation (an organisation could not verify its own trail; retention would cut it in the middle); per event Merkle tree (more than the threat needs) |
| Seal | SHA-256 links plus HMAC with a key outside the database | links only (anyone with the database rewrites a chain consistently); a signature with a private key (the portal holds it anyway; more to manage) |
| Anchor outside the database | heads in the daily log and as receipts kept by administrators | a public ledger or timestamping service (an outside dependency and a network call per day); e-mailed heads (later, with the alert) |
| Events already stored | sealed at the upgrade, marked so | left unsealed (no evidence for them at all) |

## 4. Consequences

- A record change needs the portal's database as well as the data entry API: with MongoDB unavailable to the portal,
  editors are refused instead of changing records without trace. Resolution does not depend on it.
- Each event costs one more read (the chain's head) and an index; journals of an existing installation are sealed once
  at the upgrade, which takes longer the bigger the journal (logged).
- Stored data: journal events gain fields, `journal_heads` is new; nothing is removed, backups restore as before, and a
  restored backup verifies as it was when made (its heads are older than the log's).
- A single event can no longer be removed or changed without the verification reporting it.
- Operators keep `PORTAL_JOURNAL_KEY` with the other secrets of `.env`; the backup of the database does not include it.

## 5. Not decided here

A reason for each change and a second signature for selected changes are features of regulated record-keeping
(electronic signatures), not of tamper evidence; they would change every screen that saves, and wait for a request.
The data entry service's own journal is a step of item 10.1 ([ADR 0021](0021-data-entry-api-closed.md) §4).

## 6. Delivery

Step 1: this record; `portal/journal.py` (chains, sealing, verification), `portal/app.py` (record changes journalled
first, `change-failed`, the verification route, the daily housekeeping), the Audit screen, `.env.example`, the
installer and `rotate-secrets.sh`; texts in the twelve languages; checks in `test_store.py` (also against a real
MongoDB in the continuous integration), `test_record_delete.py` and a new `test_journal.py`, mutation-checked; ADR
0001's note, the developer guide, the threat model, the changelog, features and the portal guide. Step 2 (§2.5), the
alert: `journal.py` (`journalVerified`, `record_verification()`, `last_verification()`), `monitor.py`
(`check_journal()`), `app.py` (the verification route updates the stored result), the overview and the alert history,
two messages and five screen texts in the twelve languages, 15 checks in `test_monitor.py` (7 mutations, all caught).
