# ADR 0056 — Records outside the rules: a report for the operator

| | |
|---|---|
| Status | **Accepted** (27 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the *GS1 data* control and threats T-D1/T-D2 of the [threat model](../threat-model.md); residuals of findings U-004 ([ADR 0049](0049-data-entry-anchors.md) §4) and U-003 ([ADR 0048](0048-data-entry-target-rule.md) §4), code from the official project |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — one report, read on request by a server administrator on the *Organisations* screen, of every anchor and target the resolver holds that the data entry API now refuses; the counts and the first rows on the screen, every row in CSV or Excel. Not taken: rewriting or deleting such records (the anchor's intended key, or the right target, cannot be guessed, and they are still resolved); a monitoring check with e-mail alerts and daily reminders (the state of old records does not change by itself; an alert that can only be silenced by editing records is noise); counting them on the *Overview* (it would read every record with its links each time the page opens); showing an organisation its own (the records were written through the operator's API, and an anchor of another shape has no organisation) |
| Amends | nothing; closes the first residual of ADR 0048 §4 and of ADR 0049 §4 |

## 1. Context

The data entry API checks what is sent to it: anchors of one shape since ADR 0049 (finding U-004), targets under the
portal's rule since ADR 0048 (finding U-003). Neither changed what was stored before:

- **Anchors.** The official API stored an anchor of any shape under a document id with every `/` turned into `_`.
  Since ADR 0049 an id splits at its first `_`, so a document written as `/01/09506000134352/10/LOT` now reads as
  `/01/09506000134352_10_LOT`, and one written under an AI that is not a primary key (`/17/261231`) as itself. The
  portal hides the second kind and lists the first under a value its rules refuse; neither was reported anywhere but
  the API's `/summary`.
- **Targets.** A target stored before ADR 0048 (or before ADR 0037 in the portal) may be `http:`, `javascript:`,
  `data:` or an address inside a network. The resolver still sends people there; the item's page lists non-web
  targets without a link.

The operator had no way to find either without reading the database.

## 2. Decision

1. **Where**: a section *Records outside the rules* on the *Organisations* screen (server administrators), under
   GS1's GCP length table, with a button *Check the records*. Nothing is read until it is pressed.
2. **What is read**: `GET /summary?links=true` of the data entry API, the whole installation, through
   `POST /portal/api/legacy-records` (server administrators; refused during support access, since the report is the
   whole installation's). It changes nothing.
3. **What is reported** (`portal/legacy.py`), one row per problem:

   | Problem | Meaning | Rows |
   |---|---|---|
   | `anchorShape` | the anchor is not `/AI/value` with a primary key the portal knows | one per anchor |
   | `keyValue` | `/AI/value`, but the portal's rules for that key refuse the value (`gs1.normalise_key()`: a qualifier left in the value, a `_`, a wrong check digit, a GTIN-13 stored as typed) | one per anchor |
   | `targetNotHttps` | a target that is not an `https:` address | one per target |
   | `targetHost` | an `https:` target whose host is an address, a name that is not a public one, or carries a user name | one per target |
   | `targetForm` | any other target the rule refuses: spaces around or inside, control characters, a port that is not a number, no host | one per target |

   The target rule is the data entry API's (`data_entry_server/src/target_rule.py`, the portal's `normalise_url()`
   without its trimming); a test compares the two address by address. The record's own page (`gs1:defaultLink` to its
   GS1 Digital Link with `?linkType=linkset&view=page`) is the portal's and is not checked. Each row names the
   organisation that holds the anchor's prefix (none for the operator's records and for anchors of another shape),
   the record's qualifiers, the link type and the target.
4. **The screen** shows the counts (a warning when there are any, *No record outside the rules* otherwise) and the
   first 20 rows (`legacy.SCREEN_ROWS`); *Export Excel* and *Export CSV* give every row, with the column names and
   problems in the user's language (the browser sends the labels), cells protected against formulas and against
   characters a workbook cannot hold. A file is the journal event **`legacy-export`** (`csv|xlsx anchors=N
   targets=M`, the operator's trail); a look on the screen is not.
5. **Correcting** stays with the operator: through the data entry API (`PUT`, or `DELETE /api/{AI}/{value}`), or in
   the portal when it lists the record (its rules then apply to what is saved).

## 3. Consequences

- The operator can see, at any time, how much of the installation predates today's rules and who holds it, and hand
  each organisation its rows.
- The check reads every record with its links: on a large installation it takes as long as an export of every record.
- The export limit of the operator's role applies to the files, as to every export.

## 4. Residuals

- The per-organisation host lists ([ADR 0037](0037-target-addresses.md) §2.2) are not applied: a target outside an
  organisation's own list but within the general rule is not reported.
- A public name that resolves to a private address is not detected (DNS rebinding), as in the rule itself.
- Qualifiers of other shapes are not reported here: the portal already lists such records as *other* entries.

## 5. Delivery

`portal/legacy.py` (new: `anchor_problem()`, `target_problem()`, `rows()`, `counts()`, `write_csv()`,
`write_xlsx()`); `portal/app.py` (`POST /portal/api/legacy-records`, `legacy_records()`); the section on the
*Organisations* screen (`portal/static/index.html`, `app.js`, `app.css`); its texts, the message `legacy.format` and
`audit.action.legacy-export` in the twelve languages (`portal/static/i18n.js`, `portal/static/locales/`).
Tests: `test_legacy.py` 55 (each problem, value by value; the report's target rule against the data entry API's on 44
addresses; the counts, the order, one row per anchor, qualifiers, link type, target and organisation; the record's page
left out; nothing written; access: organisation administrators, the operator's readers, no session, support access;
the format; CSV and Excel with the browser's labels, formula protection, a control character, the journal event; the
first 20 rows on the screen and every row in the files; an empty, a clean and an unreachable resolver) and
`test_legacy_e2e.py` 11 (the section, the counts as a warning, the rows in the user's language, both downloads in the
journal, a clean resolver, Portuguese, no script errors); 18 mutations, all caught.
