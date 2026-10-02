# Conformance review

*Versão em português: [Revisão de conformidade](pt-BR/revisao-de-conformidade.md).*

A clause-by-clause review of this branch against the two GS1 standards it implements:

- **GS1 Digital Link Standard: URI Syntax**, release 1.7.0 (ratified, August 2026) — "URI Syntax" below;
- **GS1-Conformant Resolver Standard**, release 1.2.1 (ratified, August 2026) — "Resolver standard" below.

Reviewed code: branch `gs1br/develop` at `115a054` (1 October 2026). Review only: nothing in the code was
changed. Each gap found becomes a backlog item (section 7), so that the fixes start from evidence.

## 1. Summary

The resolver answers the core of the Resolver standard correctly: HTTP methods, CORS, redirection to a
requested link type, 404 for unknown entities and missing link types, the linkset (JSON, JSON-LD, HTML)
gathered from every level of the hierarchy without HTTP redirects, the resolver description file and
tolerance of trailing slashes. The portal builds conformant GS1 Digital Link URIs for its labels.

The review found **five gaps with a SHALL** that matter in practice:

| Finding | Clause | In one sentence |
|---|---|---|
| [F9](#f9) | Resolver 2.6.1, 2.5.8 | Without `linkType`, a record with two links of its default type in different languages answers **300** instead of redirecting to the default link when the request's language matches neither, or names no language at all. |
| [F1](#f1) | Resolver 2.5.9 | A qualified record (batch, serial…) can exist without a record for its key, so other batches and serials of that key answer 404. |
| [F2](#f2) | Resolver 2.5.9, rule 2 | Serial records may also carry a batch or a variant, which the standard forbids. |
| [F6](#f6) | Resolver 2.3 | EPC binary strings (`/eh…`, `/ex…`) are not decompressed; they answer 500. |
| [F10](#f10) | Resolver 2.4.1; URI Syntax 4.9, 4.10 | Request paths with qualifiers out of order or with data attributes in the path are redirected instead of refused with 400. |

and a number of smaller ones (sections 3 to 5). It also found **seven candidate errata** in the standards
and their published schemas (section 6), one of which (ITIP with a Consumer Product Variant) is a real
conflict between the URI Syntax and the GS1 General Specifications.

Counts (clause tables of sections 4 and 5; one row per normative statement or tightly related group):

| Status | Resolver standard | URI Syntax |
|---|---|---|
| Conforms | 32 | 10 |
| Partly | 11 | 2 |
| Does not conform | 5 | 0 |
| Not applicable / optional feature not implemented | 3 | 4 |
| To verify | 1 | 1 |

### Since the review

The review describes the branch at `115a054`. Findings fixed since, with the commits:

| Finding | Status | Commits |
|---|---|---|
| [F1](#f1) | Fixed (item 1.3): saving a qualified record of a key without a record of its own offers to create it; the record list and the import flag such keys | `83d1ba0`, `3a49ca9` |
| [F2](#f2) | Fixed (item 1.2): with AI 21, AI 22 and AI 10 are informative, not part of the registration; the data entry API refuses them as qualifiers | `61babe1`, `83d1ba0` |
| [F4](#f4) | Revised and fixed: when a serial-number record and a batch or variant record both apply, the resolver now redirects with the serial number's (see F4) | `61babe1` |
| F11 | Partly fixed (item 1.2): the data entry API checks which qualifiers each key takes and the rules of 2.5.9; values are still checked by the portal only | `61babe1` |
| F7 | Fixed (item 1.5): no `_id`; `termsOfUse` from `RESOLVER_TERMS_URL`; `validatesAIcombinations` now true (F10). `"all"` keys still promise EPC binary (F6) | `4f81234` |
| F9 | Fixed (item 1.5): without `linkType` the default link unless the request decides a variant; `gs1:defaultLinkMulti` published; the first default-type link is the default | `4f81234` |
| F10 | Fixed (item 1.5): request paths checked by the engine's Digital Link parser | `4f81234` |
| F12 | Fixed (item 1.5): raw request URI through the proxy and the resolver | `4f81234` |
| F13 | Fixed (item 1.5): query string passed on exactly as sent | `4f81234` |
| F14 | Fixed (item 1.5, owner's decision): the per-target option removed; `fwqs: false` ignored | `4f81234`, `db8e342` |
| F15 | Fixed (item 1.5): 400 instead of 500 | `4f81234` |
| F16 | Fixed (item 1.5): 300 as a valid linkset, or an HTML page | `4f81234` |
| F17 | Fixed (item 1.5): JSON-LD in the HTML page; HTML without an `Accept` header | `4f81234` |
| F18 | Fixed (item 1.5): links without a media type handled | `4f81234` |
| F19 | Fixed (item 1.5): q-values and RFC 4647 lookup | `4f81234` |

Still open: F6 (EPC binary, item 1.6), F20 and F23 (errata E2 and E4), F21 (item 7.3), F22 (item 1.4).

## 2. Method

1. Every normative statement of both standards was listed — SHALL, SHALL NOT, SHOULD, SHOULD NOT,
   RECOMMENDED, and MAY where it constrains — with its clause, including the conformance statement of the
   Resolver standard (section 5 of that standard), the ABNF of the URI Syntax and the normative schemas the
   Resolver standard points to (linkset schema, resolver description file schema).
2. Each statement was checked against the code (file and function) and, where behaviour mattered, by a
   request: the real resolver code through Flask's test client with the real GS1 Barcode Syntax Engine
   1.4.1 (the harness of `dev-tests/resolver/test_resolver.py`), and the proxy's `proxy_pass` rule on a
   local nginx. Section 8 lists the requests so that they can be repeated, also against an installation.
3. Each statement received a **side** and a **status**:

| Side | Meaning |
|---|---|
| Query | the resolver answering a GS1 Digital Link (`web_server/`, proxy) |
| Registration | what can be registered: portal (`portal/`) and data entry API (`data_entry_server/`) |
| Description | the resolver description file (`/.well-known/gs1resolver`) |
| Labels | the GS1 Digital Link URIs the portal puts in QR codes |
| Deployment | the installation (TLS, proxy) |

| Status | Meaning |
|---|---|
| Conforms | the behaviour meets the statement |
| Partly | met in the common case, not in every case, or met by the portal but not by the API |
| Does not conform | the behaviour contradicts the statement |
| N/A | the statement does not apply, or describes an optional feature not implemented |
| To verify | needs evidence not available in this review (GS1's conformance test suite, item 1.4) |

The existing development tests (`dev-tests/`) were run before the review; all 128 resolver checks pass.

## 3. Findings

Findings F1 to F8 were known before the review and are confirmed or rejected here; F9 onwards are new.

### <a id="f1"></a>F1 — No default link above a qualified record (Resolver 2.5.9) — does not conform

> For any entry point, that is, for any GS1 Digital Link URI, no matter how granular, there SHALL be a
> default link available either at the entry level or at a higher level.

The portal accepts a batch or serial record for a key that has no key-level record. Then the key itself
and every other batch or serial of it answer 404: with only `/01/09506000134369/10/L1` registered,
`/01/09506000134369` and `/01/09506000134369/10/L2` both answer 404. This is what GS1's test "Resolver does
not handle unknown value for a valid key qualifier" detects. The statement is about data, so the fix is on
the registration side. Side: registration. **Action: item 1.3.** *Fixed in `83d1ba0` and `3a49ca9`.*

### <a id="f2"></a>F2 — Serial records with a batch or a variant (Resolver 2.5.9, rule 2) — does not conform

> If a link is associated with AI 01 (GTIN) or AI 8006 (ITIP) plus AI 21 (serial), then AI 22 (CPV) or AI 10
> (batch/lot number) SHALL NOT be defined for that association.

`KEY_SHAPES` in `portal/gs1.py` gives GTIN the shape `22, 10, 21` with every qualifier optional, so
01+10+21 and 01+22+10+21 can be registered (ITIP likewise with 10+21). The data entry API accepts any
qualifiers (F11). Rule 1 (01+235 alone) is already enforced by the shape `235`. Side: registration.
**Action: item 1.2.** The staging installation held no serial record with a batch or a variant (checked on
1 October 2026), so 1.2 needs no migration tool: it refuses the combination on every input (form,
spreadsheet import, API) and lists any such record already stored, for installations whose data predates
the rule. *Fixed in `61babe1` and `83d1ba0`, with the owner's design: the batch and variant of a serial
number are kept with its record as information (`informativeQualifiers`), so they can still be searched,
filtered, exported and printed.*

### F3 — The default link carries a title and nothing else (Resolver 2.5.8) — conforms

`_author_db_linkset_document()` in `data_entry_server/src/data_entry_logic.py` stores
`https://gs1.org/voc/defaultLink` as `{"href", "title"}` only; `_public_link()` and
`format_linkset_for_external_use()` in `web_server/src/web_logic.py` publish it unchanged. The portal never
sends an empty title: a blank title becomes the vocabulary title of the link type (`build_document()` in
`portal/app.py`). Which link becomes the default is a separate problem: see F9.

### <a id="f4"></a>F4 — The query linkset is the union of the matching registrations (Resolver 2.5.9, rule 4) — conforms; redirect choice corrected

`read_document()` gathers every entry whose qualifiers are all present in the request
(`_entry_applies()`), most specific first, and the linkset merges them, each level with its own anchor. That
set contains the six sets of rule 4 and, in addition, entries such as 01+10+21 — which rule 2 forbids
registering. Once F2 is fixed, the two sets are the same. The match is literal: an entry 01+22+10 is not
returned for a request without the CPV, as the standard says. **Action: item 1.2 adds a test with all six
sets.**

*Correction found while implementing item 1.2:* the linkset was right, but the redirect was not. The most
specific entry was the one with the most qualifiers, so with records 01+10 and 01+21 a request
`/10/B42/21/S1` (both apply, one qualifier each) could be redirected with the batch's link. Rule 4 lists
01+21 first, and a serial number names one unit. Since `61babe1` a record with AI 21 or AI 235 outranks any
batch or variant record (test "informative qualifiers: … → u-serial" in `test_resolver.py`).

### F5 — Walking up the tree without HTTP redirects (Resolver 2.5.9) — conforms

The levels are resolved inside one request; there is no redirect to a less granular URI.

### <a id="f6"></a>F6 — EPC binary strings are not decompressed (Resolver 2.3) — does not conform

> A GS1-Conformant resolver SHALL decompress EPC binary strings [EPCB].

Single-segment paths go to `uncompress_gs1_digital_link()`, which calls `GS1DigitalLinkToolkit.js`. The
toolkit implements only the legacy compression algorithm of GS1 Digital Link 1.1 (optional since Resolver
1.2.0) and nothing of the EPC binary standard: `/eh…` and `/ex…` strings are read as legacy-compressed
data and refused ("No optimisation defined for hex code…"). The refusal then produces **500** (see F15).
Side: query. **Action: new item 1.6.**

### F7 — Resolver description file (Resolver 3) — partly

The file is served at `/.well-known/gs1resolver`, validates against the official schema (test
"description: validates against the official description file schema"), takes the root and the operator
from the environment and declares the JSON-LD context. But:

- `"supportedPrimaryKeys": ["all"]` promises every qualifier of every key (2.1, 2.5.9), which is not true
  for EPC binary (F6) or ITIP with a CPV (F20);
- `"validatesAIcombinations": true` (a property of the legacy file) is not true while F10 stands;
- the internal `"_id"` field is published;
- `"termsOfUse"` points to a GS1 page for every installation, while operator details otherwise come from
  each installation's `.env`.

Side: description. **Action: item 1.5** (remove `_id`, make `termsOfUse` configurable or drop it, keep
`validatesAIcombinations` true only once F10 is fixed); the `"all"` claim becomes true with 1.6.

### F8 — URIs on the portal's labels (URI Syntax 4) — conforms

`gs1.digital_link()` and `syntax.digital_link()` build the label URI from validated values: GTIN as 14
digits, qualifiers in path order (`KEY_SHAPES`), values percent-encoded (`quote(v, safe='')`), data
attributes placed in the query string by the GS1 Barcode Syntax Engine, no trailing slash, and the
operator's stem (`RESOLVER_PUBLIC_URL`). Once 1.2 restricts what a record may register, the URI in the QR
code and the registration become different things; 1.2 keeps the first free (any valid URI).

### <a id="f9"></a>F9 — The default response is not always the default link (Resolver 2.6.1, 2.5.8) — does not conform

> Resolvers SHALL redirect to the default link unless there is information in the request that can be used
> to determine a better response.

Without `linkType`, `_handle_link_type()` does not use the stored `gs1:defaultLink`: it takes every link of
the key's `defaultLinktype` and matches their languages against `Accept-Language`. When nothing matches and
there are two or more such links, the fallback of `_get_appropriate_linktype_docs_list()` returns all of
them and the resolver answers **300** with a JSON list — also to a browser. Example: `gs1:pip` in English and
in French, request without `Accept-Language` or with `de` → 300; the standard's examples 5 and 7 expect a
redirect to the default. Portal records always carry a language, so any record with two languages for its
default type is affected.

Two related defects:

- the stored `defaultLink` is the **last** link of the default type (the loop in
  `_author_db_linkset_document()` overwrites it), while the portal tells the user that the first link is the
  default;
- choosing among the default type's links by language is the `gs1:defaultLinkMulti` behaviour, and 2.5.8
  says that if this feature is supported "the link types for these links SHALL include
  gs1:defaultLinkMulti". Such links are typed so only when a single link lists two languages, and then
  under the key `defaultLinkMulti` (not a URI), which `format_linkset_for_external_use()` drops.

Side: query and registration. **Action: item 1.5** — no `linkType`: best language match among explicit
`gs1:defaultLinkMulti` links, otherwise 307 to `gs1:defaultLink`; the default link is the first link of the
default type; `defaultLinkMulti` stored under its URI and published.

### <a id="f10"></a>F10 — Request paths are not validated as GS1 Digital Link URIs (Resolver 2.4, 2.4.1; URI Syntax 4.9, 4.10) — partly

`_test_gs1_digital_link_syntax()` turns the path into an element string and asks the engine to accept it.
An element string has no path order and allows data attributes, so these requests are redirected (307) to
the key's default instead of being refused:

| Request path | Problem | Answer |
|---|---|---|
| `/01/{gtin}/21/S1/10/L1` | qualifiers out of order (4.9) | 307 |
| `/01/{gtin}/17/261231` | data attribute in the path (4.10: attributes SHALL be in the query string) | 307 |
| `/01/{gtin}/99/ABC` | an AI that is not a qualifier of the key | 307 |

The same engine, given the URI itself (`dataStr`, its GS1 Digital Link parser), refuses all three ("The AIs
in the path are not a valid key-qualifier sequence for the key"), and also checks tests 4 and 5 of 2.4
(primary key, qualifiers valid for the key). It accepts `%2F` in a value and refuses a trailing slash, so the
slash must be removed first (2.13). Side: query. **Action: item 1.5.**

### F11 — The data entry API registers without validating the identifier (Resolver 2.4) — partly

> it SHOULD be impossible to register a link against an invalid GS1 identifier or set of identifiers.

The portal validates every key and qualifier (`gs1.py`, compared with the engine by `test_keys.py`). The
data entry API — official code — validates nothing: `_test_gs1_digital_link_syntax()` exists in
`data_entry_logic.py` but is never called, and `_validate_data()` is an empty hook. The API needs the
token, which only the portal holds, so the risk is limited to direct API users. Side: registration.
**Action: item 1.2** (the API applies the same rules as the portal, including the registration sets of
2.5.9). *Partly fixed in `61babe1`: structure and the rules of 2.5.9; values are not checked by the API, so
that templates such as `{lotnumber}` keep working.*

### F12 — `%2F` in a value breaks resolution (Resolver 2.4.1) — partly

`/` belongs to the 82-character set and is written `%2F` in a URI (4.2). The proxy's
`proxy_pass http://web-service:4000/api/;` passes the *decoded* path on (checked on nginx 1.24: `/10/A%2FB`
arrives as `/10/A/B`), and Werkzeug decodes `PATH_INFO` as well. The request then has an odd number of
segments and answers 400 although the URI is valid. The portal does not let `/` into registered values, so
only walking up from such a batch or serial is affected. Side: query, deployment. **Action: item 1.5**
(pass the raw request URI through the proxy and read it in the web server).

### F13 — The query string is rebuilt, not passed on (Resolver 2.12) — partly

`_extract_query_strings()` decodes the query string and encodes it again with `urlencode()`. The `;`
delimiter that the URI Syntax allows (`queryStringDelim`, 4.11) is not understood: `?17=261231;3103=000189`
reaches the target as `?17=261231%3B3103%3D000189`; a key without a value (`?flag`) becomes `?flag=`. Side:
query. **Action: item 1.5** (append the raw query string).

### F14 — Turning off query-string forwarding per link (Resolver 2.12) — does not conform when used; option to be removed

> When redirecting, by default, a resolver SHALL transmit the entirety of the query string in the request
> URI to the target destination.

and, in the change log of release 1.2.0: "The option to omit incoming query string parameters when
redirecting to a target URL has been removed." The portal offers *Pass the request's query parameters on to
this target* per link (stored as `"fwqs": false`, honoured in `_process_response()`), and the import and
export columns carry it. Forwarding is the default, so only records where a user unticked the box are
affected. The attribute `fwqs` is still part of GS1's official linkset schema, which is why erratum E3 is
proposed. Side: registration, query. **Action: item 1.5**, as decided by the maintainer on 1 October 2026: the option
leaves the link editor and the spreadsheet import and export, and the resolver ignores `fwqs: false` in
records that already carry it, so that every redirect forwards the query string.

### F15 — Unrecognised single-segment paths answer 500 (Resolver 2.4.1) — partly

When the toolkit refuses a single-segment path (`/foo`, an EPC binary string), it exits with an error and
`uncompress_gs1_digital_link()` returns a dictionary without `SUCCESS`; `_handle_request()` in
`web_namespace.py` then raises `KeyError` and answers 500. A request that is not a valid GS1 Digital Link URI
should get 400 (2.4.1). It is not a 200, so statement 9 of the conformance statement is met. Side: query.
**Action: item 1.5** (with 1.6 for EPC binary).

### F16 — The 300 Multiple Choices body is not a linkset (Resolver 2.6.3, 2.10) — partly

The status is right, but the body is `{"linkset": [ …links… ]}`: the links without an anchor and without
their link type, which is not a valid RFC 9264 linkset, and JSON also when a browser asked for HTML. Side:
query. **Action: item 1.5** (a real linkset of the candidate links, and the HTML page for browsers).

### F17 — HTML linkset without embedded JSON-LD; JSON when no media type is asked for (Resolver 2.10) — partly

2.10 says that for `text/html` "or unspecified" the resolver SHOULD return an HTML page and SHOULD embed the
linkset in it as JSON-LD. The HTML page (`web_pages.render_linkset()`) has no JSON-LD; a request without an
`Accept` header gets JSON (deliberate since `766a652`, so that tools such as `curl` keep receiving JSON).
Side: query. **Action: item 1.5** (embed the JSON-LD; keep JSON for requests without `Accept` and document
the choice).

### F18 — A link without a media type can cause a 400 (Resolver 2.4.1) — partly

`_match_media_type()` evaluates `'und' in linktype_doc['type']`; for a link created through the API without
a `type` the value is `None` and the `TypeError` becomes 400 for a valid request (e.g. `linkType` set and
`Accept-Language` matching none of the links). The portal always stores a media type
(`gs1.guess_media_type()`), so only API-created links are affected. Side: query. **Action: item 1.5.**

### F19 — Languages are matched literally (Resolver 2.6.3) — partly

`Accept-Language: pt-BR` does not match a link in `pt` unless the browser also sends `pt`; the q-values are
discarded rather than used for ordering. 2.6.3 asks for a best-effort closest match. Side: query.
**Action: item 1.5**, with F9 (BCP 47 lookup: `pt-BR` → `pt`).

### <a id="f20"></a>F20 — ITIP with a Consumer Product Variant (URI Syntax 4.9; Resolver 2.5.10) — conflict between standards

`itip-path` in 4.9 allows `/8006/{itip}/22/{cpv}`, and 2.5.10 of the Resolver standard lists CPV among the
qualifiers of ITIP. The GS1 Barcode Syntax Engine, following the Syntax Dictionary, refuses it: "Required AIs
for AI (22) are not satisfied: 01". The resolver therefore answers 400, and the portal does not offer 22 for
ITIP (decision of `67d40bb`). The behaviour follows the GS1 General Specifications; the standards disagree
with each other. **Action: erratum E2** (item 8.1); no code change.

### F21 — Default titles are in English (Resolver 2.5.3) — partly

A blank title becomes the vocabulary title in English (`LINK_TYPE_DEFAULT_TITLES`), whatever the language of
the link; 2.5.3 says the title SHOULD be in the language of the target. Side: registration. **Action: item
7.3** (default titles in the link's language when the portal knows them).

### F22 — `gs1:` namespace written as `https://gs1.org/voc/` (Resolver 2.14) — to verify

2.14 defines `gs1:` as `https://ref.gs1.org/voc/`; the linksets use `https://gs1.org/voc/…` keys (official
code), while the description file declares `https://ref.gs1.org/voc/`. Both addresses lead to the
vocabulary, and the official schema accepts either. Whether GS1's test suite or clients compare the strings
is unknown. **Action: item 1.4** (check with the test suite); if needed, item 1.5.

### F23 — Language tags that the linkset schema refuses (Resolver 2.5.4, 2.10) — partly

Since `7339e3c` the portal accepts any BCP 47 tag, as 2.5.4 requires. The official linkset schema, which the
linkset SHALL validate against, only accepts `ll` or `ll-CC`
(`(^\w{2}$)|(^\w{2}-\w{2}$)`): a link in `es-419`, `zh-Hant` or `fil` makes the linkset invalid. Side:
query, registration. **Action: erratum E4**; meanwhile, item 1.5 decides whether the portal warns about such
tags.

## 4. GS1-Conformant Resolver 1.2.1, clause by clause

Numbers in the first column refer to the conformance statement (section 5 of the standard) where the
statement appears there.

| Clause | Statement (summary) | Side | Status | Evidence | Action |
|---|---|---|---|---|---|
| 2.1, 2.5.9; §5.1 | For each supported key, every key qualifier SHALL be supported | Query | Partly | every key and qualified path resolves (`test_resolver.py`, "resolves …" with the real engine); ITIP+CPV refused | F20 |
| 2.2; §5.2 | HTTP 1.1 GET, HEAD and OPTIONS | Query | Conforms | `web_namespace.py`; HEAD answers 307 with no body; OPTIONS answers `Allow: GET, HEAD, OPTIONS` | — |
| 2.2; §5.3 | HTTP over TLS | Deployment | Conforms | the installer configures host nginx with Certbot or a certificate (`scripts/install.sh`, `TLS_MODE`); the Compose stack listens on 127.0.0.1 | — |
| 2.2; §5.4 | CORS | Query | Conforms | `flask_cors.CORS(app)` and `add_headers()`; preflight answered; `Link` and `Location` exposed (test "CORS exposes Link") | — |
| 2.2 (3b) | Redirect to the default unless the query says otherwise | Query | Does not conform | see F9 | 1.5 |
| 2.2 (3c), 2.9 | `linkType=linkset` or `Accept: application/linkset+json` → no redirect, linkset | Query | Conforms | `_get_request_parameters()`; tests "linkset …" | — |
| 2.3; §5.5 | Decompress EPC binary strings | Query | Does not conform | F6 | 1.6 |
| 2.3 | MAY implement legacy decompression | Query | Conforms | `uncompress_gs1_digital_link()` (official toolkit) | — |
| 2.3; §5.10 | Linkset anchors use the decompressed URI | Query | Conforms | `DocOperationsNonGS1DigitalLinkRequest` resolves the decompressed identifiers | — |
| 2.3; §5.6 | Redirect the uncompressed URI to another resolver | Query | N/A | no redirection to other resolvers | — |
| 2.4 | SHOULD be impossible to register a link against an invalid identifier | Registration | Partly | portal: `gs1.normalise_key()`, `normalise_qualifiers()`, `test_keys.py`; API: no validation | F11 → 1.2 |
| 2.4, tests 1–3 | Basic validation (structure, AI lengths, character sets, check digits, duplicates) | Query | Partly | element string checked by the engine (`_test_gs1_digital_link_syntax()`; tests "wrong SSCC check digit…"); path structure not checked | F10 |
| 2.4, tests 4–5 | MAY check primary key and qualifiers valid for the key | Query | Not implemented | — | F10 (comes with the fix) |
| 2.4.1; §5.7 | SHALL answer 400 when the request fails the tests | Query | Partly | 400 for check digits and refused combinations; 307 for F10 paths; 400 for valid paths with `%2F` (F12); 500 for single segments (F15) | 1.5 |
| 2.4.1; §5.8 | Valid URI, nothing known → simple 404 | Query | Conforms | unknown GTIN → 404 | — |
| 2.4.1; §5.9 | No 200 for an error condition | Query | Conforms | HTML error pages keep the status (`render_error()`); errors are 4xx/5xx | — |
| 2.5.1 | The target URL SHALL be provided | Registration | Conforms | `gs1.normalise_url()`; API model requires `href` | — |
| 2.5.1 | Templates MAY be supported; SHOULD NOT use the query string | Query | Conforms | official `{0}`/`{1}` and qualifier templates use path values only | — |
| 2.5.2 | Links SHALL have a link type, SHOULD from the GS1 vocabulary | Registration | Conforms | `gs1.LINK_TYPES` (GS1 vocabulary only) | — |
| 2.5.3; §5.11 | A title SHALL be provided | Registration | Conforms | blank title → vocabulary title (`build_document()`); linkset schema requires `title` | — |
| 2.5.3 | Title SHOULD be in the target's language | Registration | Partly | default titles in English | F21 → 7.3 |
| 2.5.4 | Language tags SHALL follow BCP 47, as an array | Registration, query | Partly | `gs1.normalise_language()`; arrays in the linkset; schema refuses valid tags | F23 |
| 2.5.5; §5.11 | Media types SHALL be IANA media types | Registration | Conforms | `gs1.guess_media_type()` (IANA types by extension) | — |
| 2.5.6 | Context values SHOULD be declared in the description file | Description | Conforms | `supportedContextValuesExternal` (ISO 3166) | — |
| 2.5.8; §5.14 | Exactly one default link per entity, title only | Registration | Conforms | F3 | — |
| 2.5.8 | `gs1:defaultLinkMulti` links SHALL be typed so if the feature is supported | Query, registration | Does not conform | F9 | 1.5 |
| 2.5.8; §5.12 | Default links SHALL also carry a descriptive link type | Registration | Conforms | the default's `href` is also listed under its link type | — |
| 2.5.9; §5.16 | A default link at the entry level or higher for any URI | Registration | Does not conform | F1 | 1.3 |
| 2.5.9; §5.22 | Supported primary keys SHALL be declared in the description file | Description | Conforms | `"supportedPrimaryKeys": ["all"]` (but see F7) | — |
| 2.5.9 | SHOULD NOT redirect to walk up the tree | Query | Conforms | F5 | — |
| 2.5.9 rule 1 | 01+235: no further AIs | Registration | Conforms | shape `235` in `KEY_SHAPES`; engine refuses UPUI with a batch (test) | — |
| 2.5.9 rule 2; §5.23 | 01/8006 + 21: no 22 or 10 | Registration | Does not conform | F2 | 1.2 |
| 2.5.9 rule 3 | Without 235 or 21: 22 and/or 10 allowed | Registration | Conforms | `KEY_SHAPES` | — |
| 2.5.9 rule 4 | The query linkset SHALL be the union of six sets | Query | Conforms | F4 | test in 1.2 |
| 2.6.2; §5.17 | Requested link type available → redirect | Query | Conforms | tests "redirection …", including inherited levels | — |
| 2.6.2; §5.18 | Requested link type missing → 404 (MAY list the links) | Query | Conforms | 404 with the available links on the HTML page (test "HTML 404 page …") | — |
| 2.6.3; §5.20 | SHOULD use `Accept-Language`, MAY use `Accept` and `context` | Query | Partly | `_get_appropriate_linktype_docs_list()`; literal language match | F19 |
| 2.6.3 (7) | Undecidable choice → 300 with the links | Query | Partly | status right, body not a linkset | F16 |
| 2.8 | Pattern-based redirection MAY; `gs1:handledBy` SHALL be the rel if exposed | Query | N/A | not implemented | — |
| 2.10 | `application/linkset+json` → RFC 9264 JSON; SHALL validate against the linkset schema | Query | Conforms | tests validate every linkset with the official schema (except F23 tags) | — |
| 2.10 | Same answer RECOMMENDED for `application/json` | Query | Conforms | `_process_response()` | — |
| 2.10; §5.13 | Link header to the JSON-LD context SHOULD; context file SHOULD be declared | Query, description | Conforms | `JSON_LD_CONTEXT` in every linkset response; `jsonLdContextLocation` | — |
| 2.10 | `application/ld+json` SHOULD embed the context | Query | Conforms | test "JSON-LD on request" | — |
| 2.10 | HTML SHOULD be returned for `text/html` or no media type, with JSON-LD embedded | Query | Partly | HTML page without JSON-LD; JSON without `Accept` | F17 |
| 2.11 | Default link type `linkset`: MAY, SHOULD be declared | Description | Conforms | not supported; `linkTypeDefaultCanBeLinkset: false` | — |
| 2.12; §5.19 | SHALL pass the entire query string on when redirecting | Query | Partly | passed on by default, but rebuilt (F13) and can be switched off per link (F14) | 1.5 |
| 2.13; §5.25 | SHOULD tolerate a trailing slash | Query | Conforms | `strict_slashes = False`; test "trailing slash" | — |
| 2.14; §5.24 | SHALL recognise `gs1:` link types; other namespaces SHOULD be declared | Query | Conforms | `normalise_linktype()` accepts `gs1:`, `https://gs1.org/voc/` and `https://ref.gs1.org/voc/` | F22 |
| 2.14; §5.24 | Link types from elsewhere SHALL NOT duplicate GS1's | Registration | Conforms | GS1 vocabulary only | — |
| 3; §5.21 | Description file at `/.well-known/gs1resolver`, validating against the schema | Description | Conforms | test "description: validates …" | — |
| 3 | Content of the description file | Description | Partly | F7 | 1.5, 1.6 |
| 2.14 | Namespace URI of `gs1:` | Query, description | To verify | F22 | 1.4 |

## 5. GS1 Digital Link URI Syntax 1.7, clause by clause

This standard constrains the URIs the portal writes on labels (side *labels*) and defines what the resolver
must accept (side *query*).

| Clause | Statement (summary) | Side | Status | Evidence | Action |
|---|---|---|---|---|---|
| 2 | Applications SHALL NOT assume that a GS1 Digital Link URI points to a resolver | Registration | Conforms | the portal's code search parses URIs of any domain without contacting them | — |
| 4.1 | GTIN-8/12/13 SHALL be written as 14 digits | Labels | Conforms | `gs1.normalise_gtin()` | — |
| 4.1 | Only existing infrastructure SHOULD keep accepting legacy forms | Query | Conforms | the resolver pads a 13-digit GTIN (official behaviour); harmless | — |
| 4.2 | Reserved characters percent-encoded | Labels | Conforms | `quote(v, safe='')`; registered values limited to letters, digits, `.`, `-`, `_` | — |
| 4.3–4.6 | Primary keys, qualifiers and their formats | Registration | Conforms | `PRIMARY_KEYS`, `QUALIFIER_FORMATS`, compared with the engine (`test_keys.py`); deliberately narrower character set (decision 4) | — |
| 4.7–4.9 | Path order and permitted paths (incl. UPUI, EOID, FID, MID; 415 needs 8020) | Labels | Conforms | `KEY_SHAPES`, `QUALIFIER_ORDER` | — |
| 4.9 | Path order | Query | Partly | not checked on requests | F10 |
| 4.9 | `itip-path` with CPV | Query | To verify | refused by the engine | F20, E2 |
| 4.10 | Data attributes SHALL be in the query string | Labels | Conforms | engine's `get_dl_uri()`; the path must stay the record's own (`syntax.digital_link()`) | — |
| 4.10 | Data attributes SHALL be in the query string | Query | Partly | `/01/{gtin}/17/…` accepted | F10 |
| 4.10 | A second identifier SHALL be a data attribute | Labels | Conforms | the attribute list is the Syntax Dictionary's (keys included), minus the record's own key and qualifiers | — |
| 4.10.1 | Extension keys SHALL NOT be all-numeric; `linkType` and `context` reserved | Labels, query | Conforms | the portal writes no extension keys; the resolver uses the two keywords as defined | — |
| 4.11 | `customURIstem` with optional path segments | Labels | Conforms | `RESOLVER_PUBLIC_URL` | — |
| 4.11 | `customURIstem` with optional path segments | Query | N/A | the resolver serves at the domain root; a stem matters for item 5.1 | 5.1 |
| 4.12 | Canonical URI rules (HTTPS, `id.gs1.org`, sorted AI keys, no trailing slash) | Labels | N/A | the portal never presents a URI as canonical | — |
| 6.1 | A scanner SHALL pass on only plausible GS1 Digital Link URIs | — | N/A | no scanning software in the project | — |
| 6.2 | HRI follows the GS1 General Specifications | Labels | N/A | to check when labels with EAN/UPC are designed | 5.3 |

## 6. Candidate errata and Work Requests

For item 8.1. Each was checked against the text of the standards in this review.

| # | Document | Problem | Proposal |
|---|---|---|---|
| E1 | URI Syntax 1.7, 4.10 | The list of query parameters names `shipToaAdd1Parameter` and `shipToaAdd2Parameter`; the rules are defined as `shipToAdd1Parameter` and `shipToAdd2Parameter` (AIs 4302, 4303). | Correct the names in the list. |
| E2 | URI Syntax 1.7, 4.9; Resolver 1.2.1, 2.5.10 | `itip-path` allows `/22/` after an ITIP and 2.5.10 lists CPV among ITIP's qualifiers, but the GS1 Syntax Dictionary makes AI 22 require AI 01, so the GS1 Barcode Syntax Engine refuses `(8006)…(22)…`. | Either drop `[cpv-comp]` from `itip-path` (and CPV from 2.5.10 for ITIP), or allow 8006 in the requirement of AI 22. |
| E3 | Resolver 1.2.1, 2.12 and change log 7.2; linkset schema | The option to stop forwarding the query string was removed in 1.2.0, yet the normative linkset schema still defines `fwqs`. | Remove `fwqs` from the schema or state its meaning (e.g. informative only). |
| E4 | Linkset schema; Resolver 2.5.4 | `hreflang` must match `(^\w{2}$)|(^\w{2}-\w{2}$)`, refusing valid BCP 47 tags (`es-419`, `zh-Hant`, `fil`, `sr-Latn-RS`); the `anchor` and `href` patterns use the range `A-z`, which also admits `[`, `\`, `]`, `^`, `_` and `` ` ``. | Accept BCP 47 tags (e.g. RFC 5646 pattern or a looser one); use `A-Za-z`. |
| E5 | Resolver 1.2.1, section 3, example | The example description file is not valid JSON: an extra `},` before `jsonLdContextLocation`, its URL not quoted, and `hasTelepone` for `hasTelephone`. | Correct the example. |
| E6 | Resolver 1.2.1, section 5 and 2.7 | Items 7 and 9 of the conformance statement refer to "section 0"; example 3 writes `gs1:smp` for `gs1:smpc` and still uses the deprecated `all`. | Editorial corrections. |
| E7 | Resolver 1.2.1, 2.5.9 | The SHALL on a default link "at the entry level or higher" binds the data, but the standard gives no guidance to the registration side (refuse, warn or create the higher-level record). | Informative guidance for registration tools (what 1.3 implements). |

The namespace question (F22) is not listed: it becomes an erratum only if the test suite shows a problem.

## 7. Effect on the backlog

| Item | Change |
|---|---|
| 1.2 Registration model of 2.5.9 | Also: the data entry API validates keys and qualifiers with the same rules as the portal (F11); a test with the six sets of rule 4 (F4); no migration tool (see F2). Fixes F2. |
| 1.3 Default link at a higher level | Unchanged; fixes F1. |
| **1.5 Resolution fixes (new, M)** | F9 default response and `defaultLinkMulti`; F10 path validated by the engine's GS1 Digital Link parser; F12 raw request URI through the proxy and the web server; F13 raw query string; F14 removal of the per-link option; F15 400 instead of 500; F16 300 as a linkset (and HTML); F17 JSON-LD in the HTML page; F18 links without media type; F19 BCP 47 lookup; F7 description file tidy-up; F23 decision. Depends on 1.2 (the same records and tests). |
| **1.6 EPC binary decompression (new, M–L)** | F6 and the remaining part of F7. Implementation to be chosen when the item starts (GS1 Digital Link URI: Compression Technical Standard for EPC binary strings 1.0.0, Tag Data Standard / Tag Data Translation); the 500 for unrecognised segments is fixed in 1.5. |
| 1.4 GS1 conformance test suite | Runs after 1.5 and 1.6, so that the record reflects the corrected resolver; also settles F22. |
| 7.3 Polish | F21 (default titles in the link's language). |
| 8.1 Work Requests / errata | E1–E7 (section 6). |

Proposed order of phase 1: 1.2 → 1.3 → 1.5 → 1.6 → 1.4.

## 8. Reproducing the checks

**In a development sandbox** (see [`dev-tests/README.md`](../dev-tests/README.md)): the harness at the top
of `dev-tests/resolver/test_resolver.py` authors documents with the real data entry code and resolves them
with the real web server; with `GS1_SYNTAX_ENGINE` set, the resolver's syntax check is the real engine. The
cases of this review are the requests in the findings above, with a record holding `gs1:pip` in two
languages for F9.

**The engine as a GS1 Digital Link parser** (F10, F20), with the npm package `gs1encoder` 1.4.1:

```js
import {GS1encoder} from "gs1encoder";
const g = new GS1encoder(); await g.init();
g.dataStr = "https://example.org/01/09506000134352/21/S1/10/L1";   // throws: not a valid key-qualifier sequence
```

**The proxy** (F12): any nginx with `location / { proxy_pass http://127.0.0.1:4000/api/; }` in front of a
server that prints the path it receives shows `/10/A%2FB` arriving as `/10/A/B`.

**Against an installation**, replacing the values of `R` (the resolver's address) and `G` (a registered
GTIN, 14 digits, without braces). The expected answers of the F10 lines assume a GTIN whose own request
redirects; for a GTIN affected by F9 they also give 300, which still shows that the path was not refused.
Each line prints the status and the `Location` header.

```bash
R=https://resolver.example; G=09506000134352
show() { curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "$@"; }
show -H 'Accept-Language: de' "$R/01/$G"            # F9:  300 today; 307 to the default link expected
show "$R/01/$G/17/261231"                            # F10: 307 today; 400 expected
show "$R/01/$G/21/S1/10/L1"                          # F10: 307 today; 400 expected
show "$R/01/$G/10/A%2FB"                             # F12: 400 today; 307 expected (walks up to the GTIN)
show "$R/01/$G?17=261231;3103=000189"                # F13: Location ends in %3B3103%3D000189 today
show "$R/eh3074257bf7194e4000001a85"                 # F6, F15: 500 today
```

Results on the staging installation (1 October 2026), with a GTIN whose default link type has links in
more than one language:

| Line | Answer | Reading |
|---|---|---|
| F9, `Accept-Language: de` | 300 | F9 confirmed |
| F10, `/17/261231` | 300 | not refused: the path walked up to the GTIN and met F9 — F10 confirmed |
| F10, `/21/S1/10/L1` | 300 | the same — F10 confirmed |
| F12, `/10/A%2FB` | 400 | F12 confirmed through the host's nginx and the proxy |
| F13, `?17=…;3103=…` | 300 | F9 again; without a redirect the forwarded query string cannot be seen (F13 rests on the sandbox check) |
| F6, F15, `/eh…` | 500 | F6 and F15 confirmed |

The F10 and F13 lines also answered 300 without any `Accept-Language` header, which is the standard's
example 5 (no language information → the default link) failing in the same way as example 7.
