# ADR 0034 — Portal sessions kept on the server, so that they can be ended

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-A3 and gap G-14 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): a session record per sign-in in the portal's database, named by a random id in the signed cookie; ended at sign-out, by a password change or reset, by disabling or removing the account and by disabling its organisation; sessions opened before the change end once; no new screen |

## 1. Context

The portal's session was a cookie signed by Flask (`gs1resolver_portal`, `HttpOnly`, `Secure`, `SameSite=Lax`, path
`/portal`) holding the user name, a fingerprint of the account's password hash and the time of the sign-in. Nothing
about it was kept on the server. Signing out cleared the cookie in that browser only: a copy of the cookie (taken
from a shared computer, a browser profile, a proxy log or a stolen backup of the profile) kept working until the
idle limit (30 minutes without use, renewed at every call, so as long as the copy was used) or the absolute limit
(12 hours), or until the account's password changed. Disabling an account ended its sessions only while it stayed
disabled: enabling it again made the fingerprint match again, and a copied cookie still inside its limits came back
to life; the same held for an organisation disabled and enabled again.

## 2. Decision

### 2.1 A record per session

At each sign-in (password or single sign-on, `app.open_session()`) the portal makes a random session id of 256 bits
(`secrets.token_urlsafe(32)`) and puts it in the signed cookie under `sid`. The new collection `sessions` of the
portal's database (`portal/sessions.py`) keeps one document per open session under the id's SHA-256:

```json
{"_id": "<sha256 hex>", "user": "maria", "via": "password", "created": "<date>", "seen": "<date>", "expiresAt": "<date>"}
```

Only the digest is stored, as for the single-use links (`tokens.py`): a copy of the database gives no cookie (which
would need the portal's signing key anyway).

### 2.2 Checked at every request

`current_user()` signs a request in only when, as before, the cookie is validly signed and within the idle limit
(Flask), the fingerprint matches, the organisation is not disabled and the absolute limit has not passed, **and** the
cookie's id names a record of the same user whose `expiresAt` has not passed (`sessions.valid()`). A cookie without
an id, with an unknown id, or with the id of another user's record is not signed in; the page goes to the sign-in page
with the reason (*the session has ended*).

### 2.3 Ended on the server

| Event | Sessions ended | Where |
|---|---|---|
| Sign-out | this one | `app.logout()` → `sessions.end()` |
| Own password change | every other one; this browser gets a new id | `users.set_password()` → `sessions.end_user()`; `app.change_password()` opens a new record |
| Password set through a link (invitation, recovery), administrator's reset (temporary password or link) | all | `users.set_password()`, `users.clear_password()` |
| Account disabled | all, and they stay ended when it is enabled again | `users.update()` |
| Account removed | all | `users.remove()` |
| Organisation disabled | all of its users', and they stay ended when it is enabled again | `tenants.update()` → `sessions.end_users()` |

The calls are in `users.py` and `tenants.py`, not in the routes, so the command-line tool (`create_user.py`) ends the
sessions as well.

### 2.4 Expiry and writes

`expiresAt` is the idle limit after the record's last renewal plus the renewal interval, capped at the absolute
limit after the sign-in. A TTL index on `expiresAt` (`store.INDEXES["sessions"]`) lets MongoDB remove ended
sessions; the date is also compared in the query, since the TTL monitor runs about once a minute. The record is
renewed at most once per renewal interval (`sessions.renewal_seconds()`: a minute, or a quarter of the idle limit
when that is shorter), so a page in use writes at most once a minute, not at every call. The interval is added to the
record's end so that the record never ends before the cookie's own idle limit: the exact idle limit stays the
cookie's, and the page's warning and countdown are unchanged.

### 2.5 Sessions opened before the change

A cookie signed before this change has no id, and is not signed in: everyone signs in again once after the update.
Keeping such cookies until their limits would have left exactly the sessions that cannot be ended.

### 2.6 What is not done

- No list of one's open sessions and no *sign out everywhere* button (G-14): a password change already ends every
  other session; a screen of sessions is a later item.
- No shorter limits for administrators (G-14).
- The fingerprint stays in the cookie: it is redundant with the records for the events above, and costs nothing.
- If the portal's database cannot be read, nobody is signed in; this was already so (the account is read at every
  request).

## 3. Consequences

- A copied cookie stops working when its owner signs out, changes the password, or when an administrator resets the
  password or disables the account or its organisation, and stays dead afterwards.
- One more collection; a write per sign-in and at most one per session per minute of use.
- Everyone signs in once more after the update (the release notes say so).
- Tests: `dev-tests/portal/test_session.py`, section *server-side session records*; `test_store_mongodb.py` runs the
  portal's tests on a real MongoDB in CI.
