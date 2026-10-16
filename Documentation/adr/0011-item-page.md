# ADR 0011 — The item's page: the resolver's landing page, branded per prefix, with Verified by GS1

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery. **Amended** on 17 October 2026 (section 8, item 9.1): the page per record, explicit default links |
| Backlog items | 6.1 — page of the item's links; 6.2 — Verified by GS1 on the landing page; 9.1 — the item's page per record |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

A scan goes to one target, the default link; the other links of the record (instructions, recipes, recall status,
where to buy…) are reachable only by apps that ask for a link type, or by the resolver's plain linkset page
(`?linkType=linkset` in a browser, GS1-Conformant Resolver 2.10). Brands without a page of their own ask for **a page of
the item's links as the default target**: made by the resolver, **mobile first**, an **icon per link type**, their
**logo and colours per prefix**, in the visitor's **language**, with **clicks logged** (item 4.1 asked for it). Item 6.2
adds a link to **Verified by GS1**, where anyone can check who licensed the key — shown on the page only, never added to
the linkset (`gs1:verificationService` names a GS1 Lightweight Messaging service, not a web page), switched on or off
per installation and per organisation.

Constraints: the resolver must stay conformant — a request without a link type is answered with a redirect to the
default link; the default link type is shared by every record of a key (the data entry API's v3 model, the portal's
`default.sharedMismatch`); nothing about the people who scan is stored (ADR 0006); no third-party content may be
loaded by the page (a logo fetched from the brand's server would tell it who scans).

## 2. Decision

1. **The item's page is the resolver's linkset page**, rewritten: the item's description as its title, the brand's
   logo and colours, one large button per link with an icon for its type, the links in the visitor's language first
   (the others under *Other languages*), the levels (serial, batch, product) when there are several, the code in human
   readable form, the language menu and the operator's footer as before. *Amended (section 8): each link type once.* It answers `?linkType=linkset` in a browser,
   as the standard asks; JSON clients are unaffected.
2. **As the default target**: the editor's *Default target: the item's page* adds to the record a link of type
   `gs1:defaultLink` to `<the record's address>?linkType=linkset&view=page` and makes it the default; a scan is
   redirected (307) to it, so resolution stays conformant. The editor hides that link and shows the option instead; the
   tenant API takes and gives `landingPage: true`; spreadsheets carry it as a row of type `gs1:defaultLink` read back
   as the option. The default link type being shared by a key's records, the option is the same for all of them (the
   editor says so, as for any shared default). *Replaced by section 8: each record chooses.*
3. **Views and clicks are logged as follow-ups, not scans**: the page's own request (`view=page`) is an event of form
   `landing`, outcome `page`; each button goes through `/_click?…`, which looks the link up again in the record (never
   an address taken from the request: no open redirect), logs an event of outcome `click` with its link type and the
   target's host, and redirects (302). The overview counts them apart from scans; the Requests screen shows them. An
   automated client's page views and clicks are logged as plain answers (`linkset`, `redirect`): they are already
   counted apart as automated, and scans stay exact (people's requests less the follow-ups).
4. **Branding per prefix** in the portal (*Item page*, organisation administrators; server administrators for the
   operator and an installation default): a brand name, a logo **uploaded** (PNG, JPEG or WebP up to 200 KB; SVG
   refused — it can carry scripts) and two colours (`#rrggbb`); the text colour on them is chosen for contrast. The
   resolver reads the branding of the longest prefix of the record's company part (60-second cache, as domains) and
   serves the logo itself (`/_brand/<prefix>`, cached a day).
5. **Verified by GS1** (6.2): on the page, for a GTIN (01) or a GLN (414), a link *Check this code in Verified by GS1*,
   when the installation switches it on (`RESOLVER_VERIFIED_BY_GS1_URL`, a template with `{key}` and `{value}`; empty:
   off) and the organisation's branding has not switched it off (on by default). Never in the linkset.

## 3. Design

- `web_server/src/landing.py`: the branding cache (portal collection `branding`), `render_page()` (template, icons,
  language order, the Verified by GS1 link), `click()` (the route `/_click?a=<record path>&l=<level>&i=<position>&t=<link
  type>`: the position in the page's own order, checked against the type) and `logo()` (`/_brand/<prefix>`). On an
  organisation's domain with a path stem, the page's addresses carry the stem (its server may forward nothing else).
- `request_log`: form `landing`, outcomes `page` and `click`.
- `portal/branding.py`: rules, upload, the screen's calls (`GET/PUT/DELETE /portal/api/branding[/<prefix>]`, the
  preview `GET /portal/api/branding/<prefix>/logo`); `app.py`: the editor's option (`landingPage`) in
  `build_document()` (`landing_link()`), `get_record()`, the key's own record, imports and the tenant API; the check of
  every record's links leaves the pages out; `overview.py`: `pageViews` and `clicks`, scans without them.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| How the page becomes the default | a `gs1:defaultLink` link to the page, redirected as any default | the resolver answering browsers with the page instead of the redirect (not conformant: the default must be a redirect) |
| Logo | uploaded, served by the resolver | an address on the brand's server (leaks every scan to it; can change or vanish) |
| Click logging | a redirect route that finds the link in the record | JavaScript beacons (blocked, no-JS phones); links with the target in the query (open redirect) |
| Page views | a marked follow-up (`view=page`), not a scan | counted as scans (each scan would count twice) |
| Verified by GS1 | an installation's URL template, off until set | a fixed address (the service's address is not under this project's control and could not be confirmed when this was written) |

## 5. Consequences

- A record using the option has one more link (`gs1:defaultLink`) in its linkset, pointing at its page.
- The resolver reads the portal's `branding` collection; the page loads nothing from other sites.
- The installation sets `RESOLVER_VERIFIED_BY_GS1_URL` to enable 6.2, after checking the service's current address.

## 6. Configuration added

| Variable | Default | |
|---|---|---|
| `RESOLVER_VERIFIED_BY_GS1_URL` | empty (off) | e.g. `https://www.gs1.org/services/verified-by-gs1/results?{key}={value}` with `{key}` = `gtin` or `gln` |

## 7. Delivery

This record; the page, the click and logo routes, the log's new form and outcomes; branding in the portal (the *Item
page* screen); the editor's option, imports, exports and the tenant API; the overview's page views and clicks; tests
`resolver/test_landing.py`, `portal/test_item_page.py` and `portal/test_item_page_e2e.py` (Chromium), 41 mutations all
caught; the documentation.

## 8. Amendment of 17 October 2026 — the item's page per record (item 9.1)

### 8.1 Context

The staging tests of 15 and 16 October found two faults and asked for a change of model.

- **Bug B1.** *Default target: the item's page* came back unticked when a saved record was reopened, and saving then
  failed. The data entry API stores a link of type `gs1:defaultLink` in the linkset's `https://gs1.org/voc/defaultLink`
  member, where it otherwise keeps the derived default (one object, `href` and `title`), and its conversion back to the
  v3 format skipped that member whatever it held: `GET /api/<ai>/<value>` never returned the page link, and the portal
  saw no page. The portal's test stand-in (`dev-tests/portal/mock_data_entry.py`) kept the link, so no test failed. The
  same omission made the API refuse to remove a link from such a record (`DELETE` with links: 400 *Missing key
  'defaultLink'*), and would have made deleting one record of such a key fail to write the others back.
- **Bug B2.** After a prefix moved from the operator to an organisation, that organisation's *Item page* screen showed
  no brand: a brand recorded its owner when saved, while everywhere else ownership is derived from the prefixes when it
  is read (ADR 0002).
- **The model.** The option was shared by every record of a key (section 2.2), because the key's default link type is
  shared. The owner asked for each record to choose: a scan of the GTIN alone, or of a batch without a record, reaches
  the product's page, while a registered batch goes where its own record says.

### 8.2 Decision

1. **Explicit default links.** The official model's own way of giving each record its default target is used: when a
   record of a key uses its page, the key's shared default link type is `gs1:defaultLink`, and every record of the key
   has links of that type of its own — its page, or **copies of its default targets** (its links of the type of its
   first target, every language, the same address, title and context). The resolver needed no change: it already
   redirects to the first `gs1:defaultLink` of the level that answers, and chooses among several by language
   (`gs1:defaultLinkMulti`, section 2.5.8). A key whose records do not use the page keeps the shared default link type
   as before; nothing changes for it.
2. **The portal writes and hides them.** `gs1.record_view()` turns a record's stored links into what the editor, the
   tenant API and exports show: the targets with the default ones first, whether the page is the default target, and
   the record's own default link type. A copy is hidden; a `gs1:defaultLink` to an address no other link of the record
   has (written by another tool) is shown as a target of that type and kept. On saving, `store_record()` adds the copies
   to a record of a key that has explicit default links, and, when a record takes its page in a key that has none yet,
   first turns the key's other records to explicit default links (`turn_to_explicit_defaults()`), each keeping its own
   target — after asking `POST /api/validate`, so that nothing is changed when one of them would be refused.
3. **No conversion of stored data.** Records saved with the shared option (section 2.2) are already in this form: every
   record of such a key has its own page link. Nothing is migrated.
4. **B1 fixed at its source, the stand-in held to the real API.** The data entry API returns a record's links of type
   `gs1:defaultLink` when the member holds a list (the record's own links), and still skips the derived default (one
   object). A new test program, `resolver/test_mock_parity.py`, makes the same calls, in the order the portal makes
   them, on the stand-in and on the real data entry API, and compares what each returns: a stand-in that does more than
   the real component now fails a test.
5. **B2 fixed: brands owned through their prefix.** `branding.owner()` gives the organisation whose prefixes cover a
   brand's prefix, at query time; the `tenant` field earlier versions wrote is ignored and removed on the next save. The
   same pattern was looked for elsewhere: a domain and a single sign-on configuration belong to their organisation
   itself (a name it proved it holds, a configuration it made), but the prefixes a domain is the default for are now
   read against what its organisation holds (`domains.still_held()`): a moved prefix's stale entry no longer blocks the
   new owner, and is ignored for labels.
6. **The editor.** A new record of a key starts with the choice of the key's own record. Above the targets, the key's
   other records are listed by their choice (*Using the item's page: …* / *Going to their own default target: …*).
   Ticking the page in a key whose default type is shared says that the other records keep their own targets on
   saving; the old refusal (`default.sharedMismatch`) stays for keys without the page.
7. **The page: each link type once.** For each link type, in the record's order, the page shows its links in the best
   language the visitor reads — the page's language, then the browser's other languages in order of preference, then a
   link in no language in particular, otherwise the type's first language — and marks the language when it is not the
   page's own. The type's other translations go under *Other languages*: nothing is hidden.
8. **The brand's logo as favicon** of the page (`<link rel="icon">` to `/_brand/<prefix>`, the resolver's own address).

### 8.3 Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where a record's own default lives | links of type `gs1:defaultLink` per record (the official model's link type for it; the API fixed to return them) | the page as the address of the first link of the key's shared default type (a `gs1:pip` that is the resolver's own page: misleading for applications asking for that type, and a second link of the type for the real one) |
| Keys without the page | unchanged (shared default type) | explicit default links for every key (one more link per record everywhere, for no gain) |
| Data written by the earlier option | used as it is | a migration (nothing to convert) |
| The stand-in | compared with the real API by a test | corrected by hand to drop the link (the next difference would hide again) |

### 8.4 Consequences

- A record of a key with explicit default links has one more link per language of its default target in its linkset.
  Exports and the editor do not show it; the link check leaves it out (its address is the target's).
- Turning a key costs one `PUT` per record of the key, once.
- `GET /api/<ai>/<value>` of the data entry API now returns links of type `gs1:defaultLink` (a change to the official
  component, recorded in the changelog).

### 8.5 Delivery

The data entry API's conversion; `gs1.record_view()`, `gs1.explicit_default_links()`, `store_record()`,
`turn_to_explicit_defaults()`, `get_record()` (`explicitDefaults`, `keyRecordLanding`, each other record's
`landingPage`), imports and exports, the tenant API; `branding.owner()`, `domains.still_held()`; the editor
(`renderLandingUse()`, `refreshDefault()`); the page (`group_links()`, the favicon). Tests: `resolver/test_mock_parity.py`
(new, 29 checks), `resolver/test_landing.py` (68), `portal/test_item_page.py` (89), `portal/test_item_page_e2e.py`
(29); 24 mutations, all caught.
