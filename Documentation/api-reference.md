# Link management portal — tenant API — reference

Version 1.0.0. Records, labels and statistics of one organisation of a GS1 Digital Link resolver, for its own systems.

This page is generated from `portal/openapi.json` by `portal/tools/gen_api_reference.py` (do not edit it by hand); every installation serves the same description at `/portal/api/v1/openapi.json`. How to create keys and use them is in the operator's guide (`Documentation/extensions/README.md`, *Tenant API*) and the user guide (*API keys*).

## How it works

Authenticate every call (except this description) with an API key created by an administrator in the portal (API keys): `Authorization: Bearer rk_<id>.<secret>`. A key belongs to an organisation (or to the operator) and reaches only its records, within the key's GS1 Company Prefixes when it has some; it has scopes, an expiry and a limit of requests per minute. Answers are JSON; errors carry a message `code` and its `params` (the portal's message codes). Records are addressed by primary key and value (`/records/01/09506000134352`) and, for a qualified record, its key qualifiers as a path in `qualifiers` (`?qualifiers=/10/L1`). The API follows the portal's rules: the GS1 rules of keys, qualifiers and formats, the registration model of GS1-Conformant Resolver 2.5.9, the default link type shared by every record of a key (`default.sharedMismatch`). It is meant for servers: it sends no CORS headers.

## Operations

| Method | Path | What it does |
|---|---|---|
| `GET` | [`/`](#operation-whoami) | The key itself, its organisation and its request limit |
| `GET` | [`/stats`](#operation-getstats) | Usage, resolution quality and record quality of the key's reach |
| `GET` | [`/openapi.json`](#operation-openapi) | This description |
| `GET` | [`/records`](#operation-listrecords) | The records within the key's reach, a page at a time |
| `GET` | [`/records/{key}/{value}`](#operation-getrecord) | One record |
| `PUT` | [`/records/{key}/{value}`](#operation-putrecord) | Creates or replaces one record |
| `DELETE` | [`/records/{key}/{value}`](#operation-deleterecord) | Deletes one record, keeping the key's others |
| `GET` | [`/labels/{key}/{value}`](#operation-getlabel) | The record's label: a QR code, a Data Matrix or a GS1 DataMatrix |

### Operation: whoami

`GET /portal/api/v1/` — The key itself, its organisation and its request limit

| Status | Answer |
|---|---|
| 200 | The key — [WhoAmI](#schema-whoami) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |

### Operation: getStats

`GET /portal/api/v1/stats` — Usage, resolution quality and record quality of the key's reach

Scope `stats:read`. The figures of the portal's overview for the last 7, 30 or 90 days in the installation's time zone (today included), each compared with the period just before: scans by people and automated requests, per day, the most scanned codes, shares by device class, form, language and link type; the requests answered, scanned codes nobody registered (404 unknown) and codes without a link of the type asked (404 noLink); the records, their quality and the keys nobody scanned. Nothing in it identifies the people who scan.

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `days` | query | no | integer (one of `7`, `30`, `90`; default 30) | The period |

| Status | Answer |
|---|---|
| 200 | The statistics — [Stats](#schema-stats) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 422 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |

### Operation: openapi

`GET /portal/api/v1/openapi.json` — This description

| Status | Answer |
|---|---|
| 200 | OpenAPI 3.1 document |

### Operation: listRecords

`GET /portal/api/v1/records` — The records within the key's reach, a page at a time

Scope `records:read`. Sorted by `id`; pass the `next` of an answer as `after` to get the next page. The listing reaches at most the export limit the organisation set for its API keys (`exportLimit`): the first that many records; 403 `export.notAllowed` when that limit is 0.

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `key` | query | no | string (pattern `^[0-9]{2,4}$`) | Only the records of this primary key (an Application Identifier, e.g. 01) |
| `limit` | query | no | integer (1 to 1000; default 100) | Records per page |
| `after` | query | no | string | The `next` of the previous page |

| Status | Answer |
|---|---|
| 200 | A page of records — [RecordList](#schema-recordlist) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 422 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |

### Operation: getRecord

`GET /portal/api/v1/records/{key}/{value}` — One record

Scope `records:read`.

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `key` | path | yes | string (pattern `^[0-9]{2,4}$`) | The primary key's Application Identifier (01, 00, 414, 8004…) |
| `value` | path | yes | string | The key's value (a GTIN of 8, 12, 13 or 14 digits is stored as GTIN-14); percent-encode / and other reserved characters |
| `qualifiers` | query | no | string | The record's key qualifiers as a path (/22/V1/10/L1/21/S1); absent: the key's own record |

| Status | Answer |
|---|---|
| 200 | The record — [Record](#schema-record) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 404 | No record with those qualifiers (record.notFound) — [Error](#schema-error) |
| 422 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |

### Operation: putRecord

`PUT /portal/api/v1/records/{key}/{value}` — Creates or replaces one record

Scope `records:write`. The first link is the record's default link unless `defaultLinkType` names another of its types. Links are matched on link type, languages and context: links the record had and the body lacks are removed.

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `key` | path | yes | string (pattern `^[0-9]{2,4}$`) | The primary key's Application Identifier (01, 00, 414, 8004…) |
| `value` | path | yes | string | The key's value (a GTIN of 8, 12, 13 or 14 digits is stored as GTIN-14); percent-encode / and other reserved characters |
| `qualifiers` | query | no | string | The record's key qualifiers as a path (/22/V1/10/L1/21/S1); absent: the key's own record |

Request body (required): [RecordInput](#schema-recordinput).

| Status | Answer |
|---|---|
| 200 | Replaced — [Saved](#schema-saved) |
| 201 | Created — [Saved](#schema-saved) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 415 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 422 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |
| 502 | The resolver's data entry API failed or refused the change (upstream.*) — [Error](#schema-error) |

### Operation: deleteRecord

`DELETE /portal/api/v1/records/{key}/{value}` — Deletes one record, keeping the key's others

Scope `records:write`.

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `key` | path | yes | string (pattern `^[0-9]{2,4}$`) | The primary key's Application Identifier (01, 00, 414, 8004…) |
| `value` | path | yes | string | The key's value (a GTIN of 8, 12, 13 or 14 digits is stored as GTIN-14); percent-encode / and other reserved characters |
| `qualifiers` | query | no | string | The record's key qualifiers as a path (/22/V1/10/L1/21/S1); absent: the key's own record |

| Status | Answer |
|---|---|
| 200 | Deleted — [Message](#schema-message) |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 404 | No record with those qualifiers (record.notFound) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |
| 502 | The resolver's data entry API failed or refused the change (upstream.*) — [Error](#schema-error) |

### Operation: getLabel

`GET /portal/api/v1/labels/{key}/{value}` — The record's label: a QR code, a Data Matrix or a GS1 DataMatrix

Scope `labels:read`. X-Symbol names the 2D symbol and X-Dimension its X-dimension in mm; for a QR code X-QR-Version, X-QR-Level and X-QR-Modules, for a Data Matrix X-DM-Modules (rows x columns).

| Parameter | In | Required | Type | Meaning |
|---|---|---|---|---|
| `key` | path | yes | string (pattern `^[0-9]{2,4}$`) | The primary key's Application Identifier (01, 00, 414, 8004…) |
| `value` | path | yes | string | The key's value (a GTIN of 8, 12, 13 or 14 digits is stored as GTIN-14); percent-encode / and other reserved characters |
| `qualifiers` | query | no | string | The record's key qualifiers as a path (/22/V1/10/L1/21/S1); absent: the key's own record |
| `format` | query | no | string (one of `svg`, `png`, `pdf`, `zip`) | svg (default), png or pdf, as a download; zip: the three and a README.txt |
| `symbol` | query | no | string (one of `qr`, `dm`, `gs1dm`; default qr) | The 2D symbol: qr (GS1 Digital Link QR code), dm (Data Matrix with the GS1 Digital Link URI) or gs1dm (GS1 DataMatrix with the element string: the key, its qualifiers and the data attributes) |
| `env` | query | no | string (one of `retail`, `healthcare`, `dpm`; default retail) | The scanning environment, which sets the X-dimension ranges (GS1 General Specifications, symbol specification tables) and the symbols it takes: retail (point of sale: every symbol, 2D 0.396-0.990 mm, EAN/UPC 0.264-0.660 mm), healthcare (Data Matrix only, 0.254-0.495 mm) or dpm (direct part marking: Data Matrix only, 0.254-0.615 mm, no EAN/UPC) |
| `hritext` | query | no | string (one of `outline`, `text`; default outline) | The SVG's human readable text: outline (glyph outlines, no font needed) or text (editable text, needing the fonts where it is printed: OCR-B for EAN/UPC digits) |
| `size` | query | no | integer (one of `80`, `90`, `100`, `120`, `150`, `200`; default 100) | Percentage of the scanning environment's target X-dimensions (retail: the 2D symbol's 0.495 mm, an EAN/UPC's 0.330 mm); refused (label.sizeOutOfRange) outside its ranges |
| `linear` | query | no | string (one of `none`, `auto`, `upce`; default none) | An EAN/UPC symbol beside the QR code, for GTINs of consumer units: auto (EAN-13, UPC-A or EAN-8 as the GTIN takes) or upce |
| `domain` | query | no | string (default default) | The domain in the QR code: default (that of the record's prefix, else the installation's), installation, or a verified domain of the organisation |
| `hri` | query | no | string (one of `full`, `key`, `none`; default full) | Human readable text under the symbol |
| `version` | query | no | string (default auto) | QR version, or auto |
| `ecl` | query | no | string (one of `l`, `m`, `q`, `h`; default m) | Error correction level |
| `attr` | query | no | array of string | A GS1 Digital Link data attribute in the QR code, AI:value (repeatable; checked by the GS1 Barcode Syntax Engine) |

| Status | Answer |
|---|---|
| 200 | The label |
| 401 | No key (api.keyMissing), or a key that is unknown, expired, revoked or of a disabled organisation (api.keyInvalid) — [Error](#schema-error) |
| 403 | The key lacks the scope (api.scope), or the record is outside its reach (access.prefix) — [Error](#schema-error) |
| 422 | A rule of GS1 or of the portal refused the request (for example gtin.checkDigit, description.required, links.required, link.typeRequired, default.sharedMismatch, request.jsonRequired, api.limit) — [Error](#schema-error) |
| 429 | Too many requests in this minute for the key (api.rateLimit); Retry-After gives the seconds to wait — [Error](#schema-error) |

## Schemas

### Schema: Error

| Field | Required | Type | Meaning |
|---|---|---|---|
| `code` | yes | string | A message code of the portal |
| `params` | no | object |  |

### Schema: Message

| Field | Required | Type | Meaning |
|---|---|---|---|
| `code` | yes | string |  |
| `params` | no | object |  |

### Schema: Link

| Field | Required | Type | Meaning |
|---|---|---|---|
| `linkType` | yes | string (pattern `^gs1:[A-Za-z]+$`) | A GS1 link type, e.g. gs1:pip |
| `url` | yes | string | An http or https address |
| `title` | no | string |  |
| `hreflang` | yes | array of string | Languages of the target (pt, en, pt-BR…) |

### Schema: RecordInput

| Field | Required | Type | Meaning |
|---|---|---|---|
| `description` | yes | string | What the item is (shown in the resolver's pages and the portal) |
| `links` | yes | array of [Link](#schema-link) |  |
| `defaultLinkType` | no | string | The link type of the default link (default: the first link's) |
| `landingPage` | no | boolean | The item's page as the record's default target: a gs1:defaultLink to the resolver's page of the record's links (Documentation/adr/0011-item-page.md). Each record of a key chooses for itself: the key's other records keep their own default targets (explicit default links, written by the portal) |

### Schema: Record

| Field | Required | Type | Meaning |
|---|---|---|---|
| `key` | yes | string |  |
| `value` | yes | string |  |
| `qualifiers` | yes | string | The record's key qualifiers as a path, empty for the key's own record |
| `informative` | no | string | The variant and batch kept with a serial number (GS1-Conformant Resolver 2.5.9) |
| `description` | yes | string |  |
| `defaultLinkType` | yes | string or null | The type of the record's own default target; gs1:defaultLink when it is the item's page |
| `links` | yes | array of [Link](#schema-link) |  |
| `landingPage` | no | boolean | Whether the item's page is the default target (its link is not listed in links) |
| `digitalLink` | yes | string | The record's GS1 Digital Link URI |

### Schema: RecordSummary

| Field | Required | Type | Meaning |
|---|---|---|---|
| `id` | yes | string | Sort key of the list (anchor\|qualifiers) |
| `key` | yes | string |  |
| `value` | yes | string |  |
| `qualifiers` | yes | string |  |
| `informative` | no | string |  |
| `description` | yes | string |  |
| `defaultLinkType` | no | string or null |  |
| `links` | yes | integer | Number of links |

### Schema: RecordList

| Field | Required | Type | Meaning |
|---|---|---|---|
| `records` | yes | array of [RecordSummary](#schema-recordsummary) |  |
| `next` | yes | string or null | The `after` of the next page; null on the last page |
| `total` | yes | integer | Records within the key's reach (and the key filter), also those beyond the export limit |
| `exportLimit` | no | integer or null | The most records the listing reaches (the organisation's export limit for API keys); null: no limit |

### Schema: Saved

| Field | Required | Type | Meaning |
|---|---|---|---|
| `code` | yes | string (one of `save.created`, `save.updated`) |  |
| `created` | yes | boolean |  |
| `digitalLink` | yes | string |  |

### Schema: Stats

| Field | Required | Type | Meaning |
|---|---|---|---|
| `period` | yes | object |  |
| `usage` | yes | object |  |
| `quality` | yes | object |  |
| `records` | yes | object |  |

### Schema: WhoAmI

| Field | Required | Type | Meaning |
|---|---|---|---|
| `key` | yes | object |  |
| `organisation` | yes | string or null | Null for the operator's keys |
| `rateLimit` | yes | object |  |
| `resolver` | no | string |  |

## Authentication

- `apiKey`: http bearer — An API key from the portal (API keys); shown once when it is created.
