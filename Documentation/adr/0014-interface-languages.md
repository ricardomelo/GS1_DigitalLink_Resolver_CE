# ADR 0014 — Interface languages: nine more, one catalogue per language, right to left for Arabic

| | |
|---|---|
| Status | **Accepted** (17 October 2026). Implemented in one delivery |
| Backlog item | 9.7 — interface languages (staging feedback of 16 October) |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

Every text people read — the portal, its e-mails, the resolver's own pages (errors, the linkset, the choice among
links), the item's page and the home page — exists in Brazilian Portuguese and British English. The staging tests
asked for Spanish, French, German, Korean, Mandarin (Simplified Chinese), Italian, Hindi, Arabic and Japanese, each
named in its own language in the menus, and for every later delivery to end with its texts in every language.

What there is to translate: the portal's catalogue (`portal/static/i18n.js`: 1,625 messages and the names and
explanations of 57 link types, about 110 KB in English), 18 e-mail messages and their signature
(`portal/mailtexts.py`), about 20 texts of the resolver's pages and 31 link type names (`web_server/src/web_pages.py`),
6 texts of the item's page (`web_server/src/landing.py`) and about 30 of the home page
(`frontend_proxy_server/home/home.js`).

## 2. Decision

1. **Eleven languages**, tagged without a region where the text does not depend on one: `pt-BR`, `en-GB` (as before),
   `es`, `fr`, `de`, `it`, `zh-Hans` (Simplified Chinese), `ja`, `ko`, `hi`, `ar`. A browser asking for `es-MX`,
   `fr-CA`, `de-AT`, `zh-CN`, `zh-TW`, `ar-EG`… gets the language; the menus name each language in that language
   (Español, Français, Deutsch, Italiano, 中文（简体）, 日本語, 한국어, हिन्दी, العربية).
2. **The portal loads a language only when it is used.** Portuguese and English stay in `i18n.js` (English is the
   fallback of every message); each other language is a file `portal/static/locales/<tag>.json` with the same keys,
   fetched when it is detected or chosen, so a page does not carry eleven catalogues (about 110 KB each). The page
   waits for it before its first render (`I18N.ready`); changing language fetches it first (`I18N.setLocale()` returns
   a promise).
3. **Arabic is right to left**: `<html dir="rtl">` in the portal, the resolver's pages, the item's page and the home
   page. Layouts that depend on a side (the sidebar, menus, paddings, arrows) use CSS logical properties or a
   `[dir=rtl]` rule; codes, GS1 element strings, addresses and numbers stay left to right inside the text
   (`dir="ltr"`, `unicode-bidi: isolate`).
4. **What stays as it is**: the names of the GS1 Application Identifiers stay GS1's English data titles in the new
   languages (Portuguese keeps its own: official translations come from each GS1 Member Organisation); link type codes
   (`gs1:pip`), GS1 terms that are names (*GS1 Digital Link*, *GS1 Company Prefix* is translated where GS1 has a usual
   name, otherwise kept), product names and addresses. The GS1 Barcode Syntax Engine's messages are translated.
5. **Every text in every language, checked**: a new text needs all eleven languages; `CLAUDE.md` says so and
   `dev-tests/portal/test_i18n.py` refuses a message missing, empty or with different `{placeholders}` in any language
   of the portal, the e-mails, the resolver's pages, the item's page and the home page.
6. **The translations are drafted by Claude** from the English (and checked against the Portuguese) with a glossary
   of the GS1 terms, and are to be reviewed by a native speaker of each language before production; until then they
   are marked as drafts in the extensions README.
7. **Numbers and dates** follow the language through `Intl` (Arabic and Hindi may show their own digits where the
   browser's locale data says so); the e-mails use the language chosen in *Options*, now any of the eleven.
8. **Spreadsheet headers** are accepted in Portuguese, English and the user's language (the catalogues loaded); a
   spreadsheet exported in another language is imported by a user of that language.

## 3. Design

- `i18n.js`: `SUPPORTED` lists the eleven tags; `ENDONYMS` names them for the menus before their catalogue is
  loaded; `LOCALE_MATCHERS` maps a browser's tag to one (`zh*` → `zh-Hans`); `load(tag)` fetches
  `locales/<tag>.json` once; `lookup()` falls back to English; `apply()` sets `lang` and `dir`; `every(key)` reads
  the catalogues loaded.
- `portal/tools/i18n_catalogue.py`: reads the catalogues of `i18n.js` (its object literal), writes or checks the
  English source of the translations, and checks a language file (same keys, same placeholders, nothing empty).
- `mailtexts.LANGUAGES` lists the eleven; `language()` maps a preference to one.
- The resolver's texts (pages and item's page) for every language in `web_server/src/page_texts.json`; link type names
  for every link type of the GS1 Web Vocabulary the portal offers; `negotiate_locale()` matches the eleven.
- The home page's catalogue in `frontend_proxy_server/home/home.js`, as before, with the eleven languages.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the portal's languages live | Portuguese and English in `i18n.js`, the others one file each, loaded on demand | all eleven in `i18n.js` (about 1.2 MB for every page); a build step (none exists) |
| Right to left | `dir` on the page, logical CSS properties where a side matters | a separate style sheet for Arabic |
| AI names | GS1's English data titles (Portuguese keeps its own) | machine translations of 221 standard names (they would differ from each Member Organisation's) |
| Translations | drafted by Claude, native review before production | waiting for professional translations |
| Chinese | Simplified (`zh-Hans`) for every `zh` | Simplified and Traditional |

## 5. Consequences

- The portal, its e-mails and every public page speak eleven languages; a visitor's phone language picks the page.
- Each delivery now costs its texts in eleven languages; the test makes a forgotten one fail.
- Drafted translations can read stiffly or choose a wrong term; until a native review they should be described as
  drafts to users of those languages.
- A page in a language other than Portuguese or English makes one more request (its catalogue), cached by the browser.

## 6. Delivery

This record; `i18n.js`, the catalogues of the nine languages, the right-to-left rules of `app.css`; `mailtexts.py`;
`web_pages.py`, `landing.py` and `page_texts.json`; the home page; `test_i18n.py` and `test_languages_e2e.py`; the
`CLAUDE.md` rule; the translation guide (`Documentation/translation-glossary.md`); the documentation.
