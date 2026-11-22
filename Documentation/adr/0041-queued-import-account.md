# ADR 0041 — A queued import writes only while its account may

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-T5 and the worker jobs (I1) of the [threat model](../threat-model.md); finding F-024 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): the worker reads the account again before each record of an import, as a request would, and stops the import when the account may no longer write. Cancelling queued imports from each place that changes an account, and keeping the role the account had on *Apply*, were not taken |

## 1. Context

A spreadsheet import is previewed and applied by an editor in the browser; its records are then written by the
worker (`portal/worker.py`, `run_import_job()` in `portal/app.py`), in the background, possibly minutes later and
after a restart of the worker ([ADR 0001](0001-portal-state-in-mongodb.md), section 3.3). Every request of the portal
reads the account again (`require_login()`, `set_scope()`), so a role, prefix or organisation change applies at once —
but the worker set the scope once, when it took the job, from `users.get(user) or {}`, and checked only each record's
prefix and owner against that scope:

- an editor made a reader, an account disabled, or an organisation disabled after *Apply* still had every record of
  the import written in their name;
- a removed account became an empty one: no organisation, no prefixes — the scope of the operator with every prefix —
  so an operator user's queued import wrote everything, and an organisation user's import failed record by record
  instead of stopping;
- a change made while the import ran (a prefix taken from the user, the role lowered) did not apply until the job ended.

Nothing let a user do more than they could when they applied the import; the gap was that a decision of an
administrator (remove, disable, demote) did not stop work already queued (finding F-024, *Low*).

## 2. Decision

### 2.1 The account read again before each record

Before each record the worker reads the account and sets the scope from it, as `require_login()` does for a request:
role, organisation and prefixes as they are now. The import stops — job **failed** with **`import.accountChanged`**,
the records written before kept — when (`import_refusal()`):

| Reason | When |
|---|---|
| `removed` | the account no longer exists |
| `replaced` | an account of that name exists, but it is not the one that prepared the import: another creation date, or another organisation |
| `disabled` | the account is disabled |
| `organisation` | its organisation is disabled or was removed (`tenant_blocked()`, as at sign-in) |
| `role` | its role is below editor |

A prefix taken from the user or the organisation while the import runs keeps failing the records it covers one by one
(`access.prefix`), as before, but from the next record on instead of from the next import.

### 2.2 What the job keeps

The preview stores in the job the organisation (`tenant`) and the creation date (`accountCreated`) of the account that
prepared it, to tell a removed and re-created account of the same name (`replaced`). Jobs queued before this change have
neither and are compared on the rest.

### 2.3 Journal and status

A refusal is journalled once as **`import-refused`** under the import's user, in the audit trail of the organisation
the import was for (the job's `tenant`, whatever the account is now), with the reason and the counts:
`reason=role created=2 updated=0 failed=0 left=2`; the portal's audit log has the same line. The browser, when it can
still poll, shows the message with the number of records written (`params.done`). A refusal sends no e-mail: the
account may be gone; the administrator who acted sees the event in the audit trail.

## 3. Alternatives not taken

- **Cancel queued imports where an account changes** (`users.update()`, `users.remove()`, `tenants.update()`): many
  places, each to be kept in step, and a race with a job already running; the worker's check covers every cause at
  the point of writing.
- **Keep the role the account had on *Apply*** (a snapshot in the job): that is the behaviour being fixed.
- **Check only when the worker takes the job**: a change made during a long import would wait for its end.

## 4. Consequences

- A queued import does nothing an administrator has since forbidden; the account is read three more times per record
  (account, organisation, organisations' list), small beside the record's own calls to the data entry API.
- Residuals: an administrator ending a user's sessions or resetting a password does not stop a queued import (the
  account may still write); an account removed and made again in the same second with the same organisation is taken
  for the same account (creation dates are kept to the second); no message tells the user by e-mail that an import
  stopped; link checks and messages (the other jobs) do not write records and are not checked.
