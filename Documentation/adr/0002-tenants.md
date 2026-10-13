# ADR 0002 — Tenants: organisations that own GS1 Company Prefixes

| | |
|---|---|
| Status | **Accepted** (13 October 2026). Implemented in three steps: 1 (this record), 2 (data model, server checks and audit; section 3.9), 3 (screens; section 3.10) |
| Backlog item | 2.4 — tenants |
| Decided by | the owner of the branch, who asked for the recommended option on every point of section 4 |
| Portuguese | [ADR 0002 em português](../pt-BR/adr/0002-organizacoes.md) |

## 1. Context

The portal knows **users**, each with a **role** (reader < editor < admin) and an optional list of **GS1
Company Prefixes** (`portal/users.py`). A user with prefixes sees and changes only the records whose key
belongs to one of them (`gs1.within_prefixes()`, called through `allowed()` / `check_access()` in
`portal/app.py`); a user without prefixes sees every record. Every administrator manages every user and
reads the whole audit trail.

That is enough for one organisation running its own resolver. It is not enough for an installation that
serves several organisations (a GS1 Member Organisation serving its members, a service provider serving
brands):

- an administrator of one organisation could create users for another, or give a user every prefix;
- the audit trail, the record history and the "last change" columns show every organisation's users;
- nothing says which organisation a prefix belongs to, so two organisations could be given the same prefix;
- the result of the last "check every record" is one value for the whole installation, with the name of the
  user who ran it.

The records themselves live in the official resolver's database (`resolver_ce`), written by the data entry API
with one master token. The official code knows nothing of organisations and must stay unchanged.

Items 3.1 (e-mail), 3.2 (tenant API and keys), 4.2 (indicators per tenant), 5.1 (the tenant's own domain) and
7.1 (single sign-on per tenant) all need the notion of a tenant.

## 2. Decision

1. **A tenant is an organisation that owns GS1 Company Prefixes.** The user interface calls it an
   *organisation* (pt-BR *organização*); the code and these documents say *tenant*. Tenants are documents of a
   new `tenants` collection in the portal's database (ADR 0001). **A prefix belongs to one tenant at most**, and
   prefixes of different tenants may not overlap (`789835741` and `7898357410` cannot belong to two tenants).
2. **A record belongs to the tenant whose prefix starts its key** (after the indicator, extension or filler
   digit, as today). Ownership is **derived, never stored** in the official database: assigning a prefix to a
   tenant moves its records with it, and the official data stays as it is.
3. **The operator is the owner of everything no tenant holds.** Users without a tenant — every user of an
   installation today — are **the operator's users**: they keep today's rights over the records no tenant
   holds, and nothing else. **The operator's administrators are the server administrators.** An installation
   that never creates a tenant works exactly as before; updating an installation changes nothing until the
   first tenant is created. No user, record or journal event is migrated.
4. **Each user belongs to one tenant or to the operator**, fixed when the user is created. Inside a tenant the
   roles are today's: reader, editor and **tenant administrator** (`admin`). A tenant user's prefixes, when
   given, must lie inside the tenant's.
5. **The server administrator** (an operator `admin`) creates, renames, disables and removes tenants, assigns
   their prefixes and manages the users of every tenant (to create a tenant's first administrator, or to help
   one who is locked out). **He does not see a tenant's records, history or audit trail**, except through
   **support access**: read only, opened for one tenant at a time with a reason, closed when he leaves it or
   signs out, and **recorded in that tenant's audit trail** with the reason.
6. **Every call checks the tenant on the server.** The scope of a request is the user's tenant, the tenant of
   an open support access, or the operator; `allowed()` admits an identifier only when its owner is that scope
   (and, inside it, when it lies in the user's own prefixes). Imports check again when the worker writes each
   record, because a prefix may have changed hands since the preview.
7. **An audit trail per tenant.** Every journal event carries the tenant it concerns (`tenant`, none for the
   operator). Record events belong to the owner of the record at the time; sign-ins to the user's tenant; user
   administration to the tenant of the user acted upon. When the server administrator acts on a tenant (its
   users, its prefixes, a support access), the event belongs to the tenant **and** is marked as done by the
   operator (`byOperator`), so both trails show it. A tenant administrator sees the trail of his tenant only;
   the server administrator sees the operator's trail and every action of the operator's users, and a tenant's
   whole trail only during support access.
8. **One e-mail address per user**, optional for now, checked for form, unique in the installation (ignoring
   case), set by the administrators. It is not used before item 3.1 (e-mail), never written to the journal,
   and removed with the user.
9. **Privacy by design.** Data minimisation: an organisation's name and prefixes, a user's name, role, prefixes
   and e-mail, nothing else. A tenant's users never see the operator's or other tenants' user names (history,
   "last change" columns, the result of the last full link check). The server administrator's access to a
   tenant's data is visible to the tenant.

## 3. Design

### 3.1 The `tenants` collection

```
{"_id": "t-3f9a1c0b2e7d", "name": "Acme Foods", "prefixes": ["7891234", "7895678"],
 "disabled": false, "created": "2026-10-13T21:00:00Z", "createdBy": "admin"}
```

- `_id`: `t-` and 12 random hexadecimal digits; never changes (the name may).
- `name`: 2 to 80 printable characters, unique ignoring case and surrounding spaces.
- `prefixes`: 4 to 12 ASCII digits each (as for users today), sorted, unique; **none may be a prefix of
  another tenant's** (or equal to it), and none may be a prefix of another of the same tenant (redundant).
- `disabled`: the tenant's users cannot sign in and their open sessions end; its records still resolve (the
  resolver knows nothing of tenants) and stay out of the operator's reach.

Writes run under the lock of the users (`store.lock("users")`), because the rules cross both collections:

| Change | Refused when |
|---|---|
| a prefix given to a tenant | it overlaps a prefix of another tenant; an **operator user** is limited to a prefix inside it (he would lose every record he can reach) |
| a prefix taken from a tenant | a **user of that tenant** is limited to a prefix inside it |
| a tenant removed | it still has users (remove or move their work first); its prefixes go back to the operator |

### 3.2 Users

The `users` documents gain two fields: `tenant` (a tenant `_id`, or absent for the operator) and `email`
(optional). The roles stay `reader`, `editor`, `admin`.

- **Who manages whom.** A tenant administrator lists, creates, changes, resets and removes the users of his
  tenant only, and only with tenant roles. The server administrator manages every user; when he creates one he
  chooses the tenant (or the operator).
- **Last administrator.** At least one enabled **operator** administrator must remain (as today for any
  administrator). A tenant may be left without an administrator: the server administrator can create one.
- **Prefixes of a tenant user** lie inside the tenant's (each starts with one of them); empty means the whole
  tenant. A tenant without prefixes reaches no record.
- **Sign-in.** A user of a disabled or removed tenant cannot sign in (`auth.tenantDisabled`); an open session
  ends at its next request.
- `create_user.py` gains `--tenant` (name or id) and `--email`; without `--tenant` the user is the operator's,
  as today.

### 3.3 The scope of a request

`require_login` sets, from the account (read on every request, as today):

| | `g.tenant` (scope) | `g.role` | `g.prefixes` |
|---|---|---|---|
| tenant user | his tenant | his role | his prefixes (empty: the tenant's) |
| operator user | none | his role | his prefixes (empty: everything the operator holds) |
| server administrator in support access | the tenant | `reader` | none (the whole tenant) |

`allowed(anchor)`: the owner of the anchor (the tenant whose prefix starts its company part, or none) equals
`g.tenant`, and the anchor lies in `g.prefixes` when there are any. Every place that reaches records already
goes through `allowed()` or `check_access()`: the record and its history, the record list, exports, imports
(preview and, now, each write of the worker), link checks, QR codes and Digital Link previews.

The tenants are read once per request (a small collection). Ownership is the longest prefix that matches —
which, with overlaps refused, is the only one.

### 3.4 Support access

`POST /portal/api/support {"tenant", "reason"}` (server administrators; reason 5 to 200 characters) stores the
tenant in the session and records `support-open` with the reason in the tenant's trail; `DELETE
/portal/api/support` closes it (`support-close`); signing out closes it as well. While it is open the page
shows a banner with the tenant's name and a button to leave, the server administrator acts as a reader of that
tenant (record list, records, history, export, QR codes, the tenant's audit trail), and cannot change records.
Opening support access to another tenant closes the first.

### 3.5 Journal

Events gain `tenant` (absent for the operator) and `byOperator` (true when an operator user acted on a tenant).
A new index `(tenant, at)` serves the filters. Events written before this change carry no tenant: they were the
operator's, which is what they become. `journal.for_record()` (the History panel) returns only the versions
made while the record belonged to the scope of the request, so a record that moves to a tenant keeps its
earlier versions in the operator's trail.

New actions: `tenant-create`, `tenant-update`, `tenant-remove` (operator trail, and the tenant's), `support-open`,
`support-close` (tenant's trail, `byOperator`), `login-refused` (a user of a disabled tenant). All belong to the
admin retention category except `login-refused`, which joins the session category.

### 3.6 Record metadata and link checks

`record_meta` stores the tenant that made the change; the record list shows "created/changed by" only when it
matches the scope of the request. The result of the last "check every record" is kept per scope (setting
`lastFullCheck:<tenant>` or `lastFullCheck` for the operator).

### 3.7 Screens

- **Organisations** (`#tenants`, server administrators): a form to create one (name, prefixes), a table with
  name, prefixes, users, records, state and actions (save, disable/enable, support access, remove), and the
  number of records that belong to no organisation.
- **Users**: an *Organisation* column and filter and, when creating a user, an organisation selector (server
  administrator only); an *E-mail* column for both administrators.
- **Header**: the organisation's name under the user name in the account menu; a banner during support access.
- **Audit trail**: unchanged for tenant administrators (their trail only); the server administrator's shows an
  *Organisation* column.

Mock-ups of these screens are delivered with step 3 before it reaches staging.

### 3.8 API added or changed

| Method and path | Who | What |
|---|---|---|
| `GET /portal/api/tenants` | server administrator | tenants with users and records counts; records that belong to none |
| `POST /portal/api/tenants` | server administrator | create (`name`, `prefixes`) |
| `PUT /portal/api/tenants/<id>` | server administrator | rename, change prefixes, disable or enable |
| `DELETE /portal/api/tenants/<id>` | server administrator | remove a tenant without users |
| `POST`, `DELETE /portal/api/support` | server administrator | open and close support access |
| `GET /portal/api/users` and the user calls | both administrators | scoped as in 3.2; `tenant` and `email` fields |
| `GET /portal/api/config` | everyone | adds `tenant` (`{id, name}` or none), `serverAdmin`, `support` |

### 3.9 As implemented in step 2

Step 2 follows sections 3.1 to 3.6 and 3.8; details settled while writing it:
- `set_scope()` in `portal/app.py` puts the scope of section 3.3 on Flask's `g`; the worker calls it for the
  user of an import. User administration and the audit trail check the role of the **account**
  (`admin_required`), so a server administrator in support access still manages users; tenants and support
  access need a server administrator (`server_admin_required`, `access.serverAdmin`).
- A record that changes hands starts its metadata again (`meta.touch()` deletes it when the stored tenant differs),
  so the new owner never sees who changed it before.
- The support reason has invisible characters removed and spaces collapsed before its length is checked.
- An operator user may not be limited to a prefix inside a tenant's (`users.prefixOfTenant`): he would reach no
  record. A user of an unknown tenant is refused (`users.tenantUnknown`).
- A tenant user's failed sign-in goes to the tenant's trail (the typed name exists); other failures to the
  operator's.
- The audit CSV gains two columns at the end, `organisation` and `by_operator`, so programs reading the first six
  keep working.

### 3.10 As implemented in step 3

The screens follow section 3.7. Creating an organisation, changing its prefixes, disabling and removing it ask
for confirmation; *Remove* is disabled while the organisation has users. Support access opens from the
organisation's row in a dialog that asks for the reason and starts the page again in the organisation's scope;
*End support access* in the banner returns to the organisations. The users list of a server administrator has an
organisation filter; in the audit trail, events done by the operator to an organisation carry the tag
*operator* in both administrators' views. The owner was away when step 3 was built: the images of the screens
(the user guide's) were delivered for review before the update reaches staging, instead of mock-ups before the
work.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Tenant model | `tenants` collection; one tenant per user | users in several tenants (a tenant switcher in every screen; harder to reason about) |
| Server administrator | the operator's `admin`; no new role | a new role above `admin`, or a flag on any account (a member of a tenant who also sees every tenant) |
| Server administrator and tenant data | support access, read only, with a reason, in the tenant's trail | full access (no privacy); no access at all (no way to help a tenant) |
| Prefix overlaps | refused | allowed, longest match wins (a tenant could take part of another's range unnoticed) |
| Existing installations | nothing migrated: today's users become the operator's | one tenant made from the operator's name holding the prefixes in use (records of users without prefixes would have no tenant; guessing prefix lengths from records is not possible without the GCP length table); one tenant per distinct set of prefixes |
| Ownership of records | derived from the prefix | a `tenant` field kept by the portal (records made by other tools would have none) |
| Audit per tenant | a `tenant` field on events, `byOperator` for the operator's actions | separate journals per tenant (retention and backups multiplied) |
| E-mail | optional, unique, administrators set it | required now (blocks today's users); a self-service field (needs item 3.1 to confirm it) |
| Delivery | three steps: record, server, screens | one step; five steps (data, API, audit, privacy, screens) |

## 5. Consequences

- An installation that does not create tenants behaves exactly as before.
- **Creating a tenant takes its records away from the operator's users**, the server administrators included:
  they reach them again only through support access. This is the point of the change; the screens say so before
  the prefix is saved.
- The server administrator cannot change a tenant's records. A tenant that needs help with its records gives
  one of its users the rights, or the server administrator creates a user in the tenant (recorded in its trail).
- The data entry API still has one master token: anyone with it bypasses tenants. Tenant API keys come with
  item 3.2.
- The resolver answers for every record, of every tenant: tenants are a matter of administration, not of
  resolution (item 5.1 brings the tenant's own domain).

## 6. Configuration added

None. Tenants are data, managed in the portal.

## 7. Delivery

1. This record (both languages).
2. Data model, server checks and audit: `portal/tenants.py`, changes to `users.py`, `journal.py`, `meta.py`,
   `app.py` and `create_user.py`; a new development test program `test_tenants.py`.
3. Screens (mock-ups first), the end-to-end tests, the user and developer guides.
