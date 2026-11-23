# ADR 0040 — The shape of a request's body, checked before its route

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D8 and control G-27 of the [threat model](../threat-model.md); findings F-023 and F-029 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): one check of every JSON body before any route of the portal's API runs — one JSON object, and the kinds of the fields a route would otherwise misread — with its own two message codes. Validating each route's body by hand, a schema per route and a catch-all that turns exceptions into 400 were not taken |

## 1. Context

The portal's routes read their bodies with `request.get_json(silent=True) or {}` and then `data.get("field")`, trusting
that the body is an object and that each field holds the kind of value the browser sends. A client that sends anything
else made the route fail half-way and answer 500: an array or a text as the body (`'list' object has no attribute
'get'`), a number where a list of prefixes goes (`can only join an iterable`), a list where a link type is looked up in a
set (`unhashable type`), a number where an import's base64 content goes, a row of `links` that is a text, a document
nested 50,000 levels deep (`RecursionError`, which Flask's `silent=True` does not catch). A sweep of every write route
with every kind of value, before this change, found 36 of the 60 routes answering 500 to at least one body, the
organisations' API (`PUT /portal/api/v1/records/…`) among them. Nothing was written in those cases — the failures came
before any write — but each one filled the log with a stack trace, counted as a server error in monitoring, and hid the
cause from the client, which was told nothing about what it had sent wrong (finding F-023).

The same trust let an object reach code that builds database filters: `{"token": {"$ne": null}}` for an import's
token, `{"username": {"$ne": null}}` at sign-in, `{"tenant": {"$ne": null}}` for a support request. The routes reviewed
fix the user and the job's type in the same filter or compare the value afterwards, so no case was found that read or
changed what it should not (finding F-029, *Info*), but the safety came from each route's care, not from a rule.

## 2. Decision

### 2.1 One check before every route

`same_origin_only()` (`portal/app.py`), which already runs before every request and refuses writes of another origin
or without JSON, now also parses the body of every `POST`, `PUT` and `DELETE` sent as JSON and passes it to
`bodies.problem()` (`portal/bodies.py`) before the route runs:

- A body that is not JSON, nested past what the parser follows, or not one JSON object (an array, a text, a number,
  `true`, `null`) is answered **400 `request.jsonInvalid`**.
- A field named in `bodies.FIELDS` whose value is of none of the kinds listed there is answered **422
  `request.fieldInvalid`** with `params.field`, the field's path (`urls`, `links.2.url`, `keyRecord.description`).
- An empty body still reaches the route, which reads it as `{}` and answers with its own codes (`gtin.required`,
  `request.jsonRequired` in the organisations' API), as before.

### 2.2 The table of fields

`bodies.FIELDS` names a field once for every route, because the portal uses each name for one kind of value
everywhere: texts (user names, tokens, tenant ids, link types, target addresses, descriptions, colours…), flags (true or
false, never 0 or 1), lists of texts (prefixes, scopes, languages, addresses to check), lists of objects whose fields are
checked by the same table (a record's `links`, a Digital Link's `attributes`), objects whose values are texts
(qualifiers by AI), the key's own record sent with a qualified one (`keyRecord`, checked by the same table) and the
texts of a spreadsheet or an overview in the user's language (`labels`, checked part by part by `LABEL_FIELDS`: column
headers and sheet names as objects of texts, aliases as objects of lists of texts, link types either way, the words for
yes and no as a text or a list, any other part a text).
Two fields take two kinds, as the browser and the tests send them: `domains` (a text or a list) and `qualifiers` (a path
or an object). Objects inside objects stop at three levels (a record's links, the key record's links); deeper is never
sent and is refused with the field's path.

`null` is accepted for every field, because the routes read fields with `.get()`, for which `null` and absent are the
same. A field the table does not name is not checked: its route already copes with every value and answers with its own
message code, which the users and the tests rely on — the retention's days and sizes, the export limits, the
notification choices, the `enabled` of forwarding and strict resolution, the hosts of targets. A field that a new
route reads without checking its kind belongs in the table; the development test below finds the one that was
forgotten.

### 2.3 Alternatives not taken

- **Each route checks its own body.** The 36 routes would each need their own checks, and the next route written would
  start without them; the class of fault stays open.
- **A JSON Schema per route** (as `openapi.json` describes the organisations' API). Exact, but a second description of
  some 60 routes to keep in step with the code, for a portal whose browser is its only other client.
- **A catch-all that answers 400 for `TypeError` and `AttributeError`.** It would turn genuine faults of the code into
  the client's fault and hide them from the tests.
- **Refusing fields nobody reads** (`additionalProperties: false`). Clients of the organisations' API that send back a
  record they read, with its `digitalLink` and other read-only fields, would start failing for no gain.

## 3. Consequences

- No write route of the portal's API answers 500 to a malformed body: a client is told what it sent wrong (two new
  message codes, in every language of the interface) and the log no longer fills with stack traces for it.
- No route receives an object where it reads a text, so no query operator can reach a database filter from a field of
  the table (F-029 closed as a class, not route by route).
- The organisations' API answers a body that is not an object with 400 `request.jsonInvalid` instead of 422
  `request.jsonRequired` (still given for an empty body); a field of another kind, such as a row of `links` that is not
  an object, is now 422 `request.fieldInvalid` where the route used to drop it silently. `openapi.json` describes both.
- A value of the right kind can still be refused by its route, with that route's own code, as before.
- The sweep that proves this found one more fault of the same family, with a value of the right kind: a control
  character in the labels of an XLSX export made the spreadsheet library refuse the whole workbook (500). The texts of
  an XLSX export (labels, rows, reference sheets) and of the overview's are now written without the control characters
  the format forbids (`sheet.xlsx_text()`).

Residuals, recorded in the private register: the resolver's web server and the official data entry API (code that came
from the official project) were not swept; fields outside the table rely on their routes' own checks, proved only by the
development test; query strings and path parameters are not part of this check (they are always texts).

## 4. Delivery

`portal/bodies.py` (`FIELDS`, `LABEL_FIELDS`, `field_problem()`, `problem()`), `portal/app.py` (`same_origin_only()`),
`portal/sheet.py` (`xlsx_text()`, used by `write_xlsx()` and `overview._label()`), the message codes
`request.jsonInvalid` and `request.fieldInvalid` in `i18n.js` and every `locales/<tag>.json`, `portal/openapi.json`
(400 *Malformed*, the 422 description) and `Documentation/api-reference.md`. Tests: `dev-tests/portal/test_malformed.py`
— every write route of the application's own table of routes, as a server administrator, an organisation's
administrator, nobody and the organisations' API key: bodies that are not an object (400), each field of the table of
every other kind (422 naming it, inside rows and the key record too), a valid body per route with every place replaced
by every kind of value and the fields left to the routes all at once (never 500), query operators where values go
(F-029), an XLSX export whose labels carry control characters, and that valid bodies, `null` and empty bodies still
pass; 15 mutations, all caught.
