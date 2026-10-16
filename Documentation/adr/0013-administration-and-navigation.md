# ADR 0013 — Administration and navigation: a sidebar, an organisation's page, the portal's own dialogs, alert history

| | |
|---|---|
| Status | **Accepted** (17 October 2026). Implemented in one delivery |
| Backlog item | 9.2 — administration and navigation (staging feedback of 16 October) |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

The staging tests of 15 and 16 October found the portal hard to find one's way in once it had grown to twelve
screens: every screen is reached through the user menu (a drop-down behind an icon), an organisation's settings are
spread over seven screens, prefixes are typed as one comma-separated text, a user's prefixes are typed too (and a
typing error is refused only on saving), and confirmations use the browser's own `confirm()` boxes, which look like
another site's and cannot be styled or translated beyond their text. Server administrators asked to see the overview of
one organisation at a time; organisations' administrators were shown installation facts (*Operation*) that are not
theirs to act on. Alerts (ADR 0008) are kept as the current state of each check only: once resolved, nothing tells
what happened.

## 2. Decision

1. **A collapsible left sidebar** on screens at least 1,100 pixels wide, with the same entries as the user menu,
   built from it in the page (one list of screens, one rule of who sees which). It folds to its icons (remembered in
   the browser). The user menu stays as it is on every width; on narrower screens it is the only menu. The current
   screen is marked (`aria-current`) in both. **Every screen at phone width** (390 pixels): no screen makes the page
   wider than the phone; wide tables scroll inside their own box. A test opens each screen at that width.
2. **An organisation's page** (`#organisation`), in one place: its prefixes (changed there by server administrators),
   its users with their prefixes, its domains, its item page brands, its single sign-on, its API keys and its alerts,
   each in a tab with a link to the screen that changes it. An organisation's administrators reach their own from the
   menu (*My organisation*); server administrators open any from *Organisations* (the name is a link) and the
   operator's too. It reads the same modules as the screens; nothing is stored apart.
3. **Prefixes as rows.** Creating an organisation and its page take one prefix per row, with *Add GCP* and a remove
   button on each; each row is checked as it is typed (4 to 12 digits), and the server's refusals (overlap with
   another organisation, redundancy, users still limited to a prefix) mark the row they name.
4. **Users' prefixes picked from the organisation's own** in a searchable list with checkboxes; a longer prefix inside
   one of them can still be added from the search box. The operator's users (no organisation) keep the text field.
5. **The portal's own dialogs** (`ask()`, `tell()`) in the style of the inactivity warning, for the fourteen
   `confirm()` calls: translated buttons, the danger shown in red, keyboard and screen readers as for any `<dialog>`.
6. **The overview filtered by organisation** for server administrators (the whole installation, the operator's
   records, or one organisation: the same figures that organisation's administrators see); *Operation* (worker,
   e-mail, monitoring checks, the log's counting) shown to server administrators only. Its two lines that matter to an
   organisation — the last check of every link and how long requests are kept — move to *Record quality*, and an
   organisation's active alerts are shown there too.
7. **Alert history**: from now on each alert raised is recorded in a new collection `alert_history` (raised, ended,
   the check, the organisation, the detail), and an *Alerts* screen lists them with filters by organisation, kind and
   date. Alerts raised before this version are not in it (there is no record of them).

## 3. Design

- `index.html`: `#sidebar` (filled by `buildSidebar()` from `.menu-item.nav-item` of the user menu), the toggle,
  `#organisation-view`, `#alerts-view`, `#ask-dialog`; `app.css`: the grid at 1,100 px and above, the folded state,
  phone fixes.
- `GET /portal/api/organisation[?id=<tenant id>|operator]` (administrators): `{tenant, prefixes, users, domains, brands,
  sso, apikeys, alerts}`; an organisation's administrator always gets their own; a server administrator any (support
  access: the one in support).
- `GET /portal/api/alerts?tenant=&kind=&from=&to=` (administrators): the history in the scope (an organisation's
  administrators: their organisation's spikes of 404; server administrators: every alert, or one organisation's).
- `monitor._update()` writes `alert_history` when a check goes into alert and closes it when it leaves (`endedAs`:
  `ok`, or `unknown` when the check could not run); kept `monitor.HISTORY_DAYS` (400) by a TTL index on `expiresAt`.
- `GET /portal/api/overview?tenant=<id>|operator` and the export: for a server administrator outside support access,
  the scope of that organisation or the operator (`scoped_view()`); *Operation* computed for the whole installation
  first, sent to server administrators only.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Navigation | a sidebar built from the user menu | a second hand-written menu (two lists to keep in step) |
| An organisation's settings | one page reading the existing modules, links to the screens that change them | moving every screen into the page (twelve screens rewritten, the organisations' own administrators' screens duplicated) |
| Confirmations | the portal's dialog | the browser's `confirm()` (unstyled, says it comes from the site's address) |
| Alert history | a collection written from now on | rebuilding the past from e-mails (not kept) |
| Overview per organisation | a filter on the same screen | support access for each look (read-only, journalled, slower) |

## 5. Consequences

- New collection `alert_history`; no change to `alerts`.
- The tests that confirmed with the browser's dialogs click the portal's.
- Organisations' administrators no longer see the worker, e-mail and monitoring facts.

## 6. Delivery

This record; the sidebar and the phone fixes; the organisation's page; prefix rows; the prefix picker; the dialogs;
the overview's filter; the alert history and its screen; tests `portal/test_admin_nav.py` and
`portal/test_admin_nav_e2e.py` (Chromium), mutation-checked; the documentation.
