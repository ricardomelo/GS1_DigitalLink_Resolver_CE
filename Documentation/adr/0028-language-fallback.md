# ADR 0028 — A language or market the links do not serve, made visible; a choice for safety-critical types

| | |
|---|---|
| Status | **Accepted** (17 November 2026); §6 (27 November 2026): the request log records the preference not served |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); hazard H-6 and control G-19 of the [threat model](../threat-model.md); follows [ADR 0022](0022-answering-level.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): keep the standard's choice, state the preference not served in a header, offer a choice to a person for the five safety-critical types, warn in the portal |

## 1. Context

A link can declare the languages it is written in (`hreflang`) and the contexts it applies to (`context`, a value the
organisation chooses — a country or market, for instance). A request states its languages in `Accept-Language` and
may name a context (`?context=`). GS1-Conformant Resolver 1.2.1, section 2.6.3, orders the choice among the links of
one type — media type, then language, then context — and the resolver follows it (`web_server/src/web_logic.py`,
`choose_links()`): the links in a language the request names win; failing that, the links that declare no language;
failing that, all of them.

When no link serves the request's languages, or none is marked for the context asked, the resolver still answers with
a link — a redirect to the only one, or a choice among several — and nothing says that it is in another language or
for another market. For most link types that is what everybody wants: a product page in English is better than none.
For a patient leaflet, a summary of product characteristics, instructions for use, safety information or a recall
notice it is a hazard (H-6 of the threat model, observed): a request in Portuguese for the leaflet of a product that
has only an English one is sent straight to the English leaflet; a request for the market `BR` receives the leaflet
marked for `GB`. A person may not understand it, or may follow information that is not valid in their country, and
neither the person nor the app that scanned the code is told.

## 2. Decision

### 2.1 What counts as "not served"

The links an answer gives **do not serve the language** when the request named languages (`Accept-Language`, without
`*` and other than the `und` the resolver assumes when the header is absent), every link given declares at least one
language, and none of them matches any range of the request (the RFC 4647 lookup the resolver already uses: a request for
`pt-BR` is served by a link in `pt-BR` or in `pt`, not by one in `pt-PT`; a request for `pt` by any `pt-…`; an English
link serves a request that accepts `en` at any weight). They **do not serve the context** when the request named one and every link given declares contexts,
none of them the one asked.

A link that declares **no language** (or only `und`), or **no context**, serves every language, or every context: the
organisation said nothing to the contrary, and the resolver cannot know better. The portal warns about such links on
safety-critical types (2.4), so that the organisation can say.

The resolver's choice among links is not changed: the same link is chosen as before.

### 2.2 `Resolution-Fallback` in every answer that redirects or offers a choice

A 307 or 300 answer whose links do not serve the request carries the response header **`Resolution-Fallback`**, with
`language`, `context` or `language, context`. It is listed in `Access-Control-Expose-Headers` beside
`Resolution-Anchor` and `Resolution-Match` (ADR 0022, section 2.2). Like them it is not part of the GS1 standards, an
app that ignores it sees no difference, and it applies to every link type and every organisation. For a plain scan
(no link type) it describes the default link, with the languages and contexts of the link of the key's default link
type it was taken from.

### 2.3 A choice for a person, for the five safety-critical types

The safety-critical link types are the five of ADR 0022, section 2.1 (`gs1:recallStatus`, `gs1:safetyInfo`,
`gs1:epil`, `gs1:smpc`, `gs1:eifu`). When a **browser** (the resolver's test for a page: an explicit `text/html`, or
no `Accept` at all) asks for one of them — or makes a plain scan of a key whose default link type is one of them — and
the link chosen does not serve its language or context, the resolver answers with the **page of a choice (300)**
instead of the redirect: every link of that type at the level that answered, each with its language, and above them a
notice in the visitor's language (the twelve of ADR 0014): *No "Patient information leaflet" in your language* —
open one you can read, or ask the manufacturer or a healthcare professional for one in your language; or *No "…"
marked for your market (BR)* — information for another country may not apply where you are. One tap opens the link.

An **app** (`Accept: */*` or a JSON type) receives the standard's answer — the redirect, or the choice it would have
received — with the header of 2.2. Every page of a choice (300) shows the notice when its links do not serve the
request, whatever the link type.

### 2.4 Warnings in the portal

The portal warns, without refusing the save, in the editor, the tenant API's answer (`warnings`) and the import's
preview, beside the warnings of ADR 0022, section 2.5:

1. **`warning.noLanguage`** — links of safety-critical types that declare no language. The portal requires a language
   on every link, so in practice these are links marked `und` (undetermined); records written through the official
   data entry API may lack one altogether. The resolver gives them to a request in any language without saying so.
2. **`warning.languageGap`** — safety-critical types (every link with a language) that do not serve a language other
   links of the same record have, by the resolver's rule of 2.1 (`pt` serves `pt-BR`; `pt-PT` does not): a request in that language receives the
   type in another language, now with the header and, in a browser, the choice. The record's own languages stand for
   the organisation's: the portal keeps no list of an organisation's languages or markets.

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| The standard's choice | kept, made visible | prefer a link without a context when none matches the context asked (a change of which link answers, for no request that needs it) |
| Header | one header, `Resolution-Fallback`, naming what was not served, for every link type | one header per preference (`Resolution-Language`, `Resolution-Context`); safety-critical types only (the others lose a free signal) |
| A person, safety-critical types | the page of a choice (300) with the notice; one tap to the link | the redirect with the header only (a person sees nothing); 404 (a leaflet in another language is better than none); a setting per organisation (no named need: the cost is one tap) |
| An app | the standard's answer with the header | 300 to apps too (an app that follows the first link gains nothing, and an app that expects a redirect breaks); 404 |
| Links without a language or context | serve everyone, and the portal warns on safety-critical types | treated as not serving (every request in any language would be flagged for links that may be multilingual or pictorial) |
| Portal | warnings on safety-critical links without a language and on languages a record has for other types but not for these | a list of languages and markets per organisation (a new setting, for a warning the record's own languages already give); a refusal |

## 4. Consequences

- An app can tell "this leaflet is not in the language asked" without a second request; a person scanning with a
  browser sees which languages exist and chooses, instead of landing on a document they may not understand.
- A browser whose languages are not served now needs one more tap to reach a safety-critical link. A browser that
  sends `Accept-Language: pt-BR,pt;q=0.9,en;q=0.8` accepts English and is not affected by an English leaflet.
- GS1's conformance test suite is unaffected: it sends `Accept: */*` (an app), and the header is extra.
- The request log records the outcome as before (`choice` for the page, `redirect` for an app); since §6 it also
  records the preference not served. A list of an organisation's languages and markets for the portal's warnings can
  follow if needed.

## 5. Delivery

In one step (17 November 2026): `web_logic.unserved()`, `_described()`, `_handle_link_type(offer_choice=…)` and
`read_document(offer_choice=…)`; `web_namespace` (the header, `offer_choice` for a browser), `__init__` (the exposed
header), `web_pages.fallback_notices()` and four texts in `page_texts.json`; `portal/safety.language_warnings()`, the
editor (`app.js`), `openapi.json` and six texts in `i18n.js` and `locales/`. Checks in
`dev-tests/resolver/test_language_resolver.py` (new), `dev-tests/resolver/test_resolver.py` and
`dev-tests/portal/test_safety_warnings.py`.

## 6. The preference not served in the request log (27 November 2026)

Residual (3) of finding F-010: the request log had no field for these answers, so an organisation could not see how
often its leaflets were given in a language or for a market that was not asked for. The owner was away; the
recommended option was taken.

- **The event.** A 307 or 300 that carries `Resolution-Fallback` stores the same values in the event's `ns` (a list,
  `language`, `context` or both, in that order); no other answer has the field
  ([ADR 0006](0006-resolver-request-log.md) §3.1). `web_namespace._process_response()` passes them with
  `request_log.note(unserved=…)` where it sets the header, so the field and the header cannot disagree;
  `request_log.event()` keeps it for the outcomes `redirect` and `choice` only. Nothing about the person is added: the
  first language asked was already in `lang`.
- **The portal.** The Requests screen's *Outcome* filter has *Language or market not served* (`outcome=notServed`,
  the events with `ns`), and a row shows *not served: language, market* beside its outcome; the API's row has
  `notServed` (a list) and the CSV a column `notServed` after `level` (values separated by spaces). Twelve languages.
- **Not taken.** A count of these answers in the daily aggregates and the Overview (the filter and the CSV answer
  the question for a period; a count per key can follow if organisations ask for it); the counts of automated
  requests (ADR 0006 §11) do not keep the field: they are not people scanning.
- **Residual.** Events recorded before this change have no `ns`: the filter finds none of them.

Checks: `dev-tests/resolver/test_request_log.py` (the field on a redirect and a choice, for an app and a browser,
language, market and both, and its absence when the preference is served, without `Accept-Language`, for links that
declare none, for a linkset and a 404), `dev-tests/portal/test_requestlog.py` (the row, the filter within the
account's scope, the CSV column) and `dev-tests/portal/test_requests_e2e.py` (the filter and the mark on the screen).
