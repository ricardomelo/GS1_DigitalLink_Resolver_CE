# ADR 0050 — Error answers without the exception's text; no editor in the images

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the *Information disclosure* and *Hardening* controls of the [threat model](../threat-model.md); finding U-006 (code and images from the official project) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken — every error answer of the resolver and the data entry API carries a fixed text, the exception and its traceback go to the service's log, and the two images install no editor. Not taken: a debug switch that puts the exception back into answers (an operator reads the log, which has more: the traceback); an error identifier in the answer to find the log line (useful, but a new field in every error answer; the request log already ties a request to its time); a global error handler in place of each `except` (the official code's statuses differ per operation — 400, 404, 409, 500 — and the answers keep them) |
| Amends | the official resolver (`web_server/src/web_logic.py`, `web_db.py`) and data entry API (`data_entry_server/src/data_entry_db.py`, `data_entry_logic.py`, `data_entry_namespace.py`) and their Dockerfiles, deliberately; recorded in the CHANGELOG |

## 1. Context

Finding U-006 listed what the official images and defaults gave away. Earlier findings had fixed most of it: every
service runs as a user of its own (F-012, [ADR 0030](0030-least-privilege-services.md)); Node.js comes from the
official Node.js image by digest, not from a piped script (F-015, [ADR 0033](0033-supply-chain.md)); the proxy and
MongoDB are published on the host's loopback address unless `.env` says otherwise (F-012); the toolkit's error text
left the resolver's 400 with U-002 ([ADR 0047](0047-toolkit-processes.md)). Two things were left:

- **The exception's text in error answers.** The data entry API answered `"Database error: " + str(e)`,
  `"Duplicate key error: " + str(e)`, `"Invalid ID format: " + str(e)` and `"Internal Server Error - " + str(e)`
  (`data_entry_db.py`, `data_entry_logic.py`), `"Error creating document:" + str(e)` (`data_entry_namespace.py`), and
  `"Invalid data format: " + str(data)`, which repeated the body. The resolver answered `"Unexpected error occurred.
  Details: " + str(e)` and the like (`web_logic.py`, `web_db.py`). PyMongo's messages name the database's host and
  port, the index and the key; other exceptions name files, functions and values of the code.
- **An editor in the images.** The resolver's and the data entry API's images installed `nano` from Debian's
  repository, as the official images did: a tool for whoever gets a shell in a container, and one more package to
  keep up to date.

## 2. Decision

1. **Fixed texts.** Every error answer built from an exception now carries a fixed text that says where to look:
   `Database error: see the data entry service's log`, `Internal server error: see the data entry service's log`
   (`data_entry_db.DATABASE_ERROR`, `INTERNAL_ERROR`, `data_entry_logic.INTERNAL_ERROR`), `Invalid document id`,
   `Error creating document: see the data entry service's log`; `Database error: see the resolver's log` and
   `Internal server error: see the resolver's log` (`web_logic.INTERNAL_ERROR`); `Invalid identifiers or qualifier
   path` and `The record's template variables could not be replaced` for the resolver's 400s. The statuses are the
   official ones. A duplicate key (a document written by another request between the check and the insert) answers
   409 naming the document, as the check before it does. A body that is neither an object nor a list answers
   `Invalid data format: the body is a JSON object or a list of objects`, without repeating the body.
2. **The detail in the log.** Each of these places logs the exception with its traceback (`exc_info=True`), at
   `ERROR` for failures and `WARNING` for refusals. `docker compose logs resolver-service` (or
   `dataentry-service`) shows it.
3. **The code's own refusals keep their text.** An answer made from an exception that the service's own code raises
   with a text written for the caller — `_qualifier_ais()`'s `ValueError`, a change's `_Refused`, the name of a
   missing field, `EpcDecodeError` — is marked `# own message`; an exception passed to a function that only logs it
   (`_unavailable()`, the engine's reason in `gs1_syntax.check()`) is marked `# log only`. The tests read every
   `except … as e` block of both services and refuse any other `return` or `abort()` whose value uses the exception.
4. **No editor.** The two Dockerfiles no longer install `nano`; their final stage installs no package from Debian's
   repository. `docker compose cp` copies a file into or out of a container; `docker compose exec` still opens a shell.

## 3. Consequences

- An integration that parsed the exception's text out of an error answer finds a fixed text; the status is the
  same. No integration should have relied on it: the texts were PyMongo's and Python's, not an interface.
- An operator who read the cause of a 500 in the answer reads it in the service's log, with the traceback.
- No new text in the user interface: the API's and the resolver's JSON messages are in English, as their other
  refusals; the resolver's HTML pages for 400 and 500 were already generic.
- The images are slightly smaller and have one package fewer to scan and update.

## 4. Residuals

- The services' logs hold the exceptions' texts, as before: they are read by the operator only (the log files and
  `docker compose logs` on the host).
- A new `except` that answers from the exception fails the tests only when it sits in `web_server/src` or
  `data_entry_server/src` and binds the exception to a name; the portal has its own error handling (its message codes,
  ADR 0006) and is not covered by this rule.

## 5. Delivery

`data_entry_server/src/data_entry_db.py` (`DATABASE_ERROR`, `INTERNAL_ERROR`, `INVALID_ID`; every operation);
`data_entry_logic.py` (`INTERNAL_ERROR`; `_author_linkset_document()`, the insert, `_author_mongo_linkset_list()`,
`create_document()`, `update_document()`, `delete_links()`, `delete_record()`); `data_entry_namespace.py` (`POST /new`,
`PUT`); `web_server/src/web_logic.py` (`INTERNAL_ERROR`; `_validate_and_fetch_document()`,
`_replace_linkset_template_variables()`, `handle_link_type()`, `_answer_link_type()`, `read_document()`), `web_db.py`,
`web_namespace.py` and `gs1_syntax.py` (markers); `web_server/Dockerfile`, `data_entry_server/Dockerfile`.
Tests: `test_data_entry_api.py` (no answer built from an exception in `data_entry_server/src`; `POST /new`, `PUT`, a
`DELETE` of links and of a record on a failure: 500 with a fixed text, the exception and its traceback in the log for
each; a failing write; the route's own `abort()`; a body neither an object nor a list; the database layer on a
failing database — six operations, an invalid id, a duplicate key); `test_resolver.py` (no answer built from an
exception in `web_server/src`; `web_db` on a failing database; a failure while choosing the link; both in the log
with the traceback); `test_least_privilege.py` (the final stage of the resolver's, the data entry API's and the
portal's images installs no package from Debian's repository). 16 mutations, all caught.
