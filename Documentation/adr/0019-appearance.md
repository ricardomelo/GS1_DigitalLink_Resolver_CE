# ADR 0019 — The installation's appearance: title, logo and colours

| | |
|---|---|
| Status | **Accepted** (21 October 2026). Implemented in one delivery |
| Backlog item | The owner's request of 21 October, before the staging tests of session 17 |
| Decided by | the owner of the branch, who gave the requirements; the recommended option on the points they left open (section 4) |

## 1. Context

Every page of an installation says *GS1 Resolver Community Edition* beside the project's logo, in GS1 blue. An
operator — a GS1 Member Organisation, a company, a solution provider — wants its own name, logo and colours on the
installation it runs, as the item's page already lets each brand do for its own codes (ADR 0011). The owner asked
for a function similar to the item's page brands that lets the operator change the logo, the colours and the title,
with a button that restores the original.

## 2. Decision

1. **One appearance for the installation**, set by server administrators (outside support access) on a new screen,
   *Appearance*: a **title** (1 to 60 characters, in place of *GS1 Resolver Community Edition*), a **logo** (PNG, JPEG
   or WebP of at most 200 KB and 2,000 pixels a side, checked as the brands' logos are; SVG is refused because it can
   carry scripts) and three **colours**:
   - the *main colour* — the header's title, the coloured band under it, headings and the side menu (GS1 blue,
     `#002C6C`, by default);
   - the *action colour* — the buttons that act (`#CE3D0D`);
   - the *highlight colour* — the marks of the current menu item, tab and similar (`#F26334`).
   Darker shades for the side menu and the buttons' hover are derived from them.
2. **Readable or refused**: white text must keep a contrast of at least 4.5:1 on the main and the action colours
   (WCAG 2.1, level AA); a lighter colour is refused with the contrast it has.
3. **Restore the original**: one button, after the portal's confirmation, removes the appearance; every page shows
   the original title, logo and colours again. Each change and each restore is a journal event (`appearance-save`,
   `appearance-reset`).
4. **Where it shows**: the portal (signed in, the sign-in page, the privacy notice), the home page, the resolver's
   pages and the item's page (its header; each brand keeps its own colours in the page's content). The title also
   replaces the product's name in the browsers' tab titles. The resolver's description file
   (`/.well-known/gs1resolver`) keeps the software's name.
5. **Served by the portal, for anyone**: `GET /portal/api/appearance` (the title, colours, the logo's address, whether
   it is the original), `GET /portal/appearance.css` (the colours as the pages' own design tokens) and
   `GET /portal/appearance/logo` (the operator's logo, or the project's). The home page, served by the proxy, reads the
   same three. The resolver reads the setting from the portal's database every 30 seconds, as it reads brands and
   forwarding, and embeds the logo in its pages.

## 3. Design

- Portal's database: the setting `appearance` in `settings`: `{"title", "colour", "action", "accent", "logo":
  {"type", "data", "etag", "width", "height"} | null, "updated", "updatedBy"}`; absent: the original.
- `portal/appearance.py`: `current()`, `public()`, `save()`, `reset()`, `css()`, `contrast()`; the logo through
  `branding.read_logo()`.
- Routes: the three public ones above; `PUT /portal/api/appearance` (`{title, colour, action, accent, logo}`: `logo`
  base64 to replace, `""` for the original, absent to keep) and `DELETE /portal/api/appearance`, server administrators.
- Pages: `appearance.css` linked after each page's style sheet; `appearance.js` (portal) and `home.js` set the title
  and the logo; `i18n.js` puts the title in place of the product's name in every text (`I18N.product`).
- Resolver: `web_server/src/web_pages.py` — `Appearance` (the setting, cached), the title, the logo as a `data:` URI and
  the colours in each page's style.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Colours | three (main, action, highlight), the shades derived | every design token (twelve colours, easy to make unreadable); one colour (buttons and marks would stay GS1's) |
| Unreadable colours | refused below 4.5:1 for white text | a warning only |
| Logo formats | PNG, JPEG, WebP, as the brands' | SVG (scripts) |
| Title in the tab titles | replaced everywhere the product's name appears | only the header (the tab would still say GS1's name) |
| Where it is set | the portal, by server administrators | `.env` (a rebuild for each change; the owner asked for a function like the brands') |
| Restore | one button removing the setting | each field back to its default by hand |

## 5. Consequences

- An installation can carry its operator's identity without changing the code; GS1's name and logo appear only where
  the operator keeps them; the original logo is the project's own, not GS1's (backlog item 7.3).
- Pages ask for one more small style sheet (no cache between changes beyond 60 seconds); the home page and the portal
  briefly show the original title before the operator's replaces it.
- The resolver's pages follow a change within 30 seconds.
