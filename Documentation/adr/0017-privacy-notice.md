# ADR 0017 — The installation's privacy notice

| | |
|---|---|
| Status | **Accepted** (20 October 2026). Implemented in one delivery |
| Backlog item | The owner's check of the handover of 20 October ("privacy notice"), decided that day |
| Decided by | the owner of the branch, who gave the requirements; the recommended option on the points they left open (section 4) |

## 1. Context

The resolver records each scan (ADR 0006: the code, the outcome, the device class, the browser family, an approximate
location; never the address) and the portal keeps its users' accounts and an audit trail. Whoever operates an
installation owes the people concerned a notice of what is recorded and why (LGPD, GDPR and similar laws), but the
installation had nowhere to publish one. The owner asked for:

1. a link in the footer of every page;
2. a page in the portal where the operator writes the text shown by that link;
3. the link reachable without signing in;
4. the changes of the notice kept as versions;
5. a first text saying that the use of this free software is the sole responsibility of whoever operates the instance,
   that neither GS1 nor anyone who contributed to it is responsible, and that the software is provided "as is".

## 2. Decision

1. **Versions, never changed**: each publication is a new numbered version in the portal's collection
   `privacy_notice` (`{_id: n, text, note, at, by}`); none is edited or deleted. The newest is in force; the page
   lists every version with its date and note, and shows any of them (`/portal/privacy?version=n`).
2. **Who writes it**: server administrators, outside support access, on *Privacy notice* (sidebar). A journal event
   `privacy-publish` (`version=n`) records each publication.
3. **The default notice**: until a version is published, the page shows the default text of the catalogues
   (`privacy.default`) in the reader's language — what the resolver and the portal record, how long, and the
   responsibility clause the owner asked for. The editor starts from it, in the administrator's language.
4. **Plain text**: paragraphs separated by a blank line, `# ` for a heading, `- ` for an item of a list, addresses made
   links; `{operator}` and `{days}` are replaced by the operator's name (`RESOLVER_ORG_NAME`) and the days requests are
   kept. No HTML is accepted, so a notice cannot carry a script.
5. **Public**: `GET /portal/privacy` (the page, for anyone) and `GET /portal/api/privacy` (its JSON: the version in
   force or the one asked for, the history, the operator's name and the days); `PUT /portal/api/privacy`
   (`{text, note}`, server administrators) publishes.
6. **The links**: the footers of the portal (signed in and on the sign-in page), the home page, the resolver's pages
   and the item's page link to `/portal/privacy`, labelled *Privacy notice* in the reader's language.

## 3. Design

- `portal/privacy.py`: `current()`, `version(n)`, `history()`, `publish(text, note, user)` (`PrivacyError`:
  `privacy.textRequired`, `privacy.textTooLong`, `privacy.textInvalid`, `privacy.noteTooLong`, `privacy.conflict`).
- `portal/static/privacy.html` and `privacy.js`: the public page, with the portal's language menu (`i18n.js`); the
  renderer turns the plain text into elements (`textContent`, never `innerHTML`).
- The administrators' screen in `index.html`/`app.js` (`#privacy`): the text, a note, a preview with the same
  renderer, *Publish*, the versions.
- Texts: `privacy.*` in every catalogue; `footer.privacy` in the home page's; `privacy` in `page_texts.json`.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the text lives | the portal's database, by version | a file on the server (no history, the terminal needed); an external address only (the owner asked for a page in the portal) |
| Format | plain text with three marks | HTML (a script could be published to every visitor); Markdown in full (more to learn, more to sanitise) |
| Languages of the operator's text | one text, written in the languages the operator chooses | one text per interface language (twelve texts to keep in step) |
| Before a version exists | the default text in the reader's language | an empty page |
| Who publishes | server administrators | organisations' administrators too (the notice is the installation's) |

## 5. Consequences

- A notice is in place from the first start; the operator should still adapt it (contact, legal basis, the law that
  applies to them).
- Old versions stay readable, which is what a change of policy needs.
- The default text is a draft in the ten languages other than Portuguese and English, like the other texts (ADR 0014).
