# ADR 0005 — The tenant API and API keys

| | |
|---|---|
| Status | **Accepted** (14 October 2026). To be implemented in three steps: 1 (this record), 2 (keys, the API and its description on the server), 3 (the API keys screen) |
| Backlog item | 3.2 — tenant API and API keys |
| Decided by | the owner of the branch, who asked for the recommended option on every point of section 4 |
| Portuguese | [ADR 0005 em português](../pt-BR/adr/0005-api-das-organizacoes.md) |

## 1. Context

Records are written by people in the portal, or by spreadsheet imports. An organisation that keeps its products in
its own system (an ERP, a PIM, an e-commerce platform) has to export a spreadsheet and import it by hand whenever
something changes. The only programmable interface is the official data entry API, which has **one master token**
for the whole installation: whoever holds it reaches every record of every organisation, bypassing roles, GS1
Company Prefixes and tenants (ADR 0002, section 5). It cannot be handed to an organisation.

What an organisation's system needs is a small, stable API that does what a portal user does — read, write and
delete records, make labels — limited exactly as a portal user is limited, with credentials the organisation can
create, see used, and revoke itself.

Constraints:

- The portal already holds every rule (ADR 0002 `set_scope()` / `allowed()`; ADR 0003 the GS1 rules; the safe
  call sequence of `store_record()`); a second implementation would drift.
- The portal runs in several replicas: a request limit must be shared by all of them (ADR 0001).
- Keys are credentials; the portal already keeps single-use links as hashes only (ADR 0004).
- Items 4.2 (indicators) and 5.1 (custom domains) will add operations; the API must grow without breaking clients.

## 2. Decision

1. **A versioned API of the portal at `/portal/api/v1/`**, served by the portal itself (no new service, no proxy
   change), JSON in and out, the same message codes as the portal's own API. A later incompatible change gets
   `/v2/`; additions (new operations, new fields) stay in `v1`.
2. **Operations of v1**: who am I (`GET /portal/api/v1`), list records (paged), read one record, create or replace
   one record (`PUT`, idempotent), delete one record, make a label (SVG or PNG); and the description of the API,
   **`GET /portal/api/v1/openapi.json`** (OpenAPI 3.1), public. Records are addressed as the portal addresses them:
   `/records/{key}/{value}` plus `?qualifiers=/10/L1`.
3. **API keys belong to an organisation** (or to the operator), not to a person. **Administrators create them**: a
   tenant administrator for his organisation, a server administrator for the operator's records (never for an
   organisation: that would bypass ADR 0002's support-access rule). A key has a name, **scopes** (`records:read`,
   `records:write`, `labels:read`), optionally GS1 Company Prefixes inside the organisation's, an **expiry**
   (required, 1–365 days, 90 by default), and records who created it, when it was last used and who revoked it.
   At most 20 active keys per organisation.
4. **The key is shown once**: `rk_<id>.<secret>` — 12 hexadecimal digits that identify it (shown in lists and in
   the audit trail) and a 256-bit random secret. **Only the secret's SHA-256 is stored** (as ADR 0004's links);
   the comparison is constant-time. A lost key is revoked and replaced, never recovered.
5. **A key works as a user of its organisation would**: each call is given the scope of a request
   (`set_scope()`): the key's organisation, the role its scopes imply (`records:write` → editor, otherwise reader),
   its prefixes. `allowed()` and every rule of the portal apply unchanged. A key of a disabled or removed
   organisation, an expired or revoked key, is refused (401).
6. **A request limit per key**, shared by every replica: a counter per key and minute in the portal's database
   (TTL), **120 requests per minute** by default (`PORTAL_API_RATE_PER_MINUTE`); above it, 429 with
   `Retry-After`.
7. **Audit**: creating and revoking a key are journal events of the organisation (`api-key-create`,
   `api-key-revoke`); every change a key makes is a record event like any other, its user `api:<key id>`. Reads
   are not journalled (item 4.1 logs requests); the key keeps its last use (at most one write a minute).
8. **E-mail** (ADR 0004): the administrator who created a key is told when it is created and seven days before it
   expires (security category, always sent); the worker checks expiries once an hour.
9. **Server to server**: the API is meant for systems, not browsers. It sends no CORS headers; a browser request
   from another site is refused by the portal's existing Origin check.

## 3. Design

### 3.1 The `api_keys` collection (`portal/apikeys.py`)

```
{"_id": "3f9a1c0b2e7d", "hash": "<sha256 hex of the secret>", "name": "ERP integration",
 "tenant": "t-…" (absent for the operator), "scopes": ["records:read", "records:write"], "prefixes": [],
 "created": <date>, "createdBy": "maria", "expiresAt": <date>, "lastUsed": <date>,
 "revoked": <date>, "revokedBy": "ana", "expiryNotice": <date>}
```

`create()` checks the name (3–60 printable characters, unique among the organisation's active keys), the scopes, the
days (1 to `PORTAL_API_KEY_MAX_DAYS`, default 365) and the prefixes (as `users._check_scope()`), under the `users`
lock; returns the full key once. `authenticate(text)` parses `rk_<id>.<secret>`, finds the document by id and
compares hashes; `revoke()` marks it. Revoked and expired keys stay listed (greyed) for the audit trail; they are
never deleted by the portal.

### 3.2 The request limit (`api_rate` collection)

`{"_id": "<key id>:<minute>", "n": 17, "at": <date>}` — `find_one_and_update` with `$inc` and `upsert`, a TTL of two
minutes on `at`. The first request of a minute also writes `lastUsed`.

### 3.3 The API (`portal/api_v1.py`)

| Call | Scope | Answer |
|---|---|---|
| `GET /portal/api/v1` | any | the key (id, name, scopes, prefixes, expiry), its organisation, the limit |
| `GET /portal/api/v1/openapi.json` | none | the description of the API |
| `GET /portal/api/v1/records?key=&limit=&after=` | `records:read` | records in the key's reach, sorted, at most `limit` (1–1000, 100); `next` is the `after` of the next page |
| `GET /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:read` | description, links (default first), default link type, Digital Link; 404 `record.notFound` |
| `PUT /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | `{description, links: [{linkType, url, title, hreflang}]}` → 201 created / 200 replaced, with the Digital Link |
| `DELETE /portal/api/v1/records/{key}/{value}?qualifiers=` | `records:write` | 200 `delete.done`; 404 `record.notFound` |
| `GET /portal/api/v1/labels/{key}/{value}?qualifiers=&format=svg\|png&hri=&version=&ecl=&attr=` | `labels:read` | the label, as the portal's |

Errors: `{"code", "params"}` as the portal's (`api.keyMissing`, `api.keyInvalid`, `api.scope`, `api.rateLimit`,
`access.prefix`, `record.notFound`, the GS1 and validation codes). The handlers call the functions the portal's own
endpoints use (`build_document()`, `store_record()`, the delete sequence, the label), so the rules are the same.

### 3.4 Keys in the portal

`GET /portal/api/keys`, `POST /portal/api/keys` `{name, scopes, days, prefixes}` → `{key, item}`,
`DELETE /portal/api/keys/<id>` (revoke), for administrators, always in the scope of their own account (a server
administrator in support access still manages the operator's keys). A screen **API keys** lists them and shows a
new key once, with a copy button and an example request.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the API lives | the portal, `/portal/api/v1/` | a new service (a second copy of every rule); the official data entry API with per-tenant tokens (changes official code, the rules are in the portal) |
| Versioning | `v1` in the path; additions without a new version | a header (`Accept-Version`; easy to forget, harder to try with curl); no version |
| Who owns a key | the organisation, created by its administrators | each user's personal tokens (a key would stop working when its person leaves) |
| Server administrators | keys for the operator's records only | keys for any organisation (bypasses support access) |
| Key format | `rk_<id>.<secret>`, SHA-256 of the secret stored | a stored secret (a database copy leaks every key); a slow hash such as bcrypt (unneeded for a 256-bit random secret, and costly on every call); signed tokens (cannot be revoked one by one) |
| Expiry | required, 90 days by default, 365 at most | optional (forgotten keys live for ever) |
| Scopes | `records:read`, `records:write`, `labels:read` | one all-powerful key; per-operation scopes (too fine for three resources) |
| Request limit | per key per minute in MongoDB, 120 | in each process's memory (wrong with replicas); in nginx (cannot tell keys apart without reading them) |
| Audit | writes as record events, key creation and revocation as admin events; last use on the key | every request journalled (item 4.1 does that, with retention) |
| Description | a hand-written OpenAPI 3.1 file, checked against the routes by a test | generated from the code (a library and decorators for six operations) |
| Delivery | three steps: record, server, screen | one step; four (keys, API, description, screen) |

## 5. Consequences

- An organisation can connect its own systems without the master token, limited to its prefixes, and can see and
  revoke what it created. The master token stays the operator's, for the portal and the installation's tools.
- A key is a credential: whoever holds it writes the organisation's records within its scopes until it expires or
  is revoked. Keys are shown once, expire, are limited per minute, and their creation is told by e-mail.
- The API answers in the portal's message codes, not in sentences; the OpenAPI document lists them.
- Writing through the API follows the same rules as the portal, including the shared default link type of a key
  (`default.sharedMismatch`), so a client must handle those answers.

## 6. Configuration added

| Variable | Default | |
|---|---|---|
| `PORTAL_API_RATE_PER_MINUTE` | 120 | requests per key and minute |
| `PORTAL_API_KEY_MAX_DAYS` | 365 | the longest validity an administrator may choose |

## 7. Delivery

1. This record (both languages).
2. On the server: `portal/apikeys.py`, `portal/api_v1.py`, `portal/openapi.json`; the key endpoints in `app.py`; the
   worker's hourly expiry check; messages in `mailtexts.py`; a new development test program `test_api.py`.
3. The API keys screen (images for review, as the owner is away), the end-to-end test, the user and developer
   guides, the README's API reference.
