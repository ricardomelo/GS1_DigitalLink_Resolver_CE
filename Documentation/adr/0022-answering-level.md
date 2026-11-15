# ADR 0022 — The level that answered a request, and a strict mode for safety-critical link types

| | |
|---|---|
| Status | **Accepted** (14 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); hazard H-1 and control G-7 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch, who chose the recommended option on each point (13 and 14 November): keep the standard's walk-up, state the level that answered, warn in the portal, and an optional strict mode per organisation |

## 1. Context

A GS1 Digital Link URI can carry key qualifiers: a batch (AI 10), a serial number (21), a variant (22) and others. A
record may be registered for the key alone (the product) or for the key with some of its qualifiers (one batch, one
unit). GS1-Conformant Resolver 1.2.1, sections 2.5.9 and 2.5.10, makes the resolver *walk up*: when the most specific
record has no link of the type asked, the next less specific one answers, down to the product. The resolver does this
(`web_server/src/web_logic.py`, `read_document()`), and the request log keeps which level answered (ADR 0006), but the
answer itself does not say so.

For most link types that is what an organisation wants: one product page for every batch. For a few it is a hazard
(H-1 of the threat model, observed): a request for `gs1:recallStatus` of a batch that has no record of its own — a
batch nobody registered, a batch value typed in another letter case at registration, a serial number scanned without
its batch — receives the product-level link, which may say "not recalled", while a recall is registered for another
batch. Nothing tells the person, the app that scanned the code, or the organisation that the answer came from the
product and not from the batch. The same holds for batch-specific leaflets (`gs1:epil`).

The standard is not wrong: it cannot know which batches exist. This record keeps its behaviour and makes the level
visible and, where an organisation wants it, binding.

## 2. Decision

### 2.1 Safety-critical link types

Five link types of the GS1 Web vocabulary are treated as **safety-critical**: `gs1:recallStatus`, `gs1:safetyInfo`,
`gs1:epil` (electronic patient information leaflet), `gs1:smpc` (summary of product characteristics) and `gs1:eifu`
(electronic instructions for use) — the list of control G-6 of the threat model. The list is fixed in the code (one
constant shared by the resolver and the portal) and changes only with this record.

### 2.2 The level that answered, in every answer that redirects or offers a choice

A 307 (redirect) or 300 (choice among links) answer carries two response headers:

- **`Resolution-Anchor`**: the GS1 Digital Link URI of the record whose links answered, on the name the request was
  made on — the same form as the anchors of the linkset (`https://id.example.org/01/09506000134369`).
- **`Resolution-Match`**: `exact` when that record names every key qualifier of the request, or names the request's
  serial number (a unit's record covers its batch and variant: Resolver 1.2.1, section 2.5.9, rule 2); `walk-up`
  otherwise.

Both are listed in `Access-Control-Expose-Headers`, so a web app on another origin can read them. They are not part of
the GS1 standards and do not change any answer the standard defines: an app that ignores them sees no difference. The
linkset (`linkType=linkset`) already names the level of each group of links in its anchor; it is unchanged.

### 2.3 A visible notice on the resolver's pages

When the links a page shows come from a less specific level than the request named — the item's page
(`linkType=linkset` in a browser, ADR 0011), the page of a choice (300) and the error page of the strict mode (2.4) —
the page says so above the links, in the visitor's language (the twelve of ADR 0014): which qualifier of the request
has no record of its own, and that the links shown belong to the product, or to the level that answered, and may not
apply to it. This holds in every organisation, with or without the strict mode. A redirect has no page and carries the
headers only.

### 2.4 The strict mode

An organisation may switch on the **strict mode for safety-critical link types**; the server administrator sets it
for the keys no organisation holds (the operator's scope). It is off by default, so nothing changes for an
installation that does not choose it.

With the strict mode on, a request that **asks for a safety-critical link type** (`linkType=`) and **names a batch or
a serial number** (AI 10, 21 or 235) is answered only by a record that names that batch or that serial number. A
request with batch and serial may still be answered by the batch's record; a batch or a serial alone is never answered
by the product's record. When no such record holds a link of the type asked, the resolver answers:

- **404** to an app, with `Resolution-Match: withheld`, so that an app can tell "nothing registered for this batch"
  (withheld) from "nothing registered at all" (no header);
- in a browser, the error page of a missing link type (section 2.6.2 of the standard: the links that *are* available)
  with the notice of 2.3: the product-level links stay reachable, but nobody receives them as if they were the batch's.

A request without a link type (a plain scan: the default link), with `linkType=linkset` or `all`, or for any other link
type is not affected. The request log records the outcome as **`withheld`** (404), a value added to those of ADR 0006,
so that the Requests screen and the overview can show it.

The organisation's administrators and the server administrator switch it on in the portal, on the organisation's page;
the setting is journalled like the organisation's other settings. The resolver reads it from the portal's database
with its own connection, at most once a minute, like the domains, brands and forwarding rules (ADR 0009, 0011, 0018),
and keeps the last value when the database cannot be read. The organisation that owns a key is found as everywhere
else: the longest of its GS1 Company Prefixes that starts the key.

### 2.5 Warnings in the portal

The portal warns, without refusing the save, where the hazard is made:

1. **A level that would be walked up.** In the editor of a batch or serial record that lacks a safety-critical link
   type held by a less specific record of the same key: requests for that batch receive the product's link of that
   type (or, with the strict mode, a 404). In the editor of a product-level record holding a safety-critical type while
   the key has batch or serial records: batches without a record of their own receive this link.
2. **A batch value close to an existing one.** When a batch or serial value is saved for a key that already has a
   record for a value equal to it but for letter case, spaces, hyphens, dots or slashes, or the letters O and I for
   the digits 0 and 1: GS1 values are case-sensitive and exact, so a code printed with one does not find the other.

The tenant API returns the same warnings with the saved record (`warnings`), and the spreadsheet import shows them in
its preview. The screens are drawn as mock-ups and approved before they are built.

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Walk-up | kept, as the standard defines it, and made visible | never walk up for safety-critical types (a deviation from the standard for every organisation); warnings in the portal only (the scan stays silent) |
| Strict mode's answer | 404 with `Resolution-Match: withheld`; the browser's page lists the available links with the notice | 300 with the product's links (an app may take the first link and show "not recalled" anyway); 307 with the header only (a person sees nothing) |
| Strict mode's rule | the walk-up stops at the batch or serial named in the request | no walk-up at all (a recall registered per batch would not answer a request with batch and serial) |
| Safety-critical types | the five of G-6, fixed | recall and safety information only (batch-specific leaflets stay silent); chosen per organisation (a larger screen and more cases, for no named need) |
| Notice on pages | always, every organisation | for safety-critical types only; none (the header reaches apps only) |
| Header names | `Resolution-Anchor` and `Resolution-Match`, without a vendor or `X-` prefix (RFC 6648) | a parameter of the `Link` header (the linkset's anchor is the request's URI, which GS1's test suite checks); a field in the body of a redirect (no body is read by browsers or most apps) |

## 4. Consequences

- An app can show "this answer is for the product, not for batch LOTB" without a second request, and the item's page
  tells a person the same. Nothing changes for an app that ignores the headers, and GS1's test suite is unaffected
  (the headers are extra; the strict mode is off by default).
- With the strict mode on, a batch nobody registered answers 404 for the five types, by design: an organisation that
  turns it on must register a record (or at least the link) for every batch it wants answered, or accept the page that
  lists the product's links. The portal's warnings say which batches are affected.
- The walk-up remains the default, as the standard requires; the hazard is reduced, not removed, for organisations
  that do not turn the strict mode on.
- Not in this record: an indicator and an alert for walk-ups on `recallStatus` (proposed for H-1), and a plain scan of
  a record that holds a recall (H-2, the default link). Both can follow from the request log's level and outcome.

## 5. Delivery

In four steps, each with its checks and documents:

1. The headers of 2.2 (`web_server/src/web_logic.py`, `web_namespace.py`, `__init__.py`); checks in
   `dev-tests/resolver/test_resolver.py`.
2. The notice of 2.3 on the item's page and the page of a choice (`landing.py`, `web_pages.py`, `page_texts.json`).
3. The strict mode of 2.4: the setting (portal, journal), the resolver's cache and answer, the outcome
   `withheld` in the request log, on the Requests screen and in the overview's quality figures. The tenant API
   (ADR 0005) manages records, not an organisation's settings, so the setting is changed on the organisation's page
   only (its *Resolution* tab; the operator's page for the keys no organisation holds).
4. The warnings of 2.5 in the editor, the tenant API and the import preview.

Steps 1 and 2 were delivered on 14 and 15 November 2026, step 3 on 15 November 2026, step 4 on 15 November 2026:
`portal/safety.py` computes the warnings of 2.5 for the editor (`POST /portal/api/record/warnings` while the record is
edited, and with the saved record), the tenant API (`warnings` in the answer of a saved record) and the import's
preview (per record, on the key's records as they will be after the import); a near duplicate compares batch, serial
and TPX values (AI 10, 21, 235). The organisation's *Resolution* tab also counts the batch and serial records that
lack a safety-critical type a broader record holds.
