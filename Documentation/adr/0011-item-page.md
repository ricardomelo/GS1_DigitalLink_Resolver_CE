# ADR 0011 — The item's page: the resolver's landing page, branded per prefix, with Verified by GS1

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog items | 6.1 — page of the item's links; 6.2 — Verified by GS1 on the landing page |
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
   readable form, the language menu and the operator's footer as before. It answers `?linkType=linkset` in a browser,
   as the standard asks; JSON clients are unaffected.
2. **As the default target**: the editor's *Default target: the item's page* adds to the record a link of type
   `gs1:defaultLink` to `<the record's address>?linkType=linkset&view=page` and makes it the default; a scan is
   redirected (307) to it, so resolution stays conformant. The editor hides that link and shows the option instead; the
   tenant API takes and gives `landingPage: true`; spreadsheets carry it as a row of type `gs1:defaultLink` read back
   as the option. The default link type being shared by a key's records, the option is the same for all of them (the
   editor says so, as for any shared default).
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
