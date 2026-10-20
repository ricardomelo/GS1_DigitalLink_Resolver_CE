# Documentation

The software is maintained by its community, not by GS1 or any GS1 Member Organisation; whoever operates
an installation is responsible for its use (see the notice at the top of the [README](../README.md)).

The documents are grouped by who reads them. Every feature is listed in [features.md](features.md), each with the
development tests' checks that prove it; the whole list of checks is the [inventory of features](test-inventory.md)
([ADR 0016](adr/0016-documentation-and-feature-inventory.md)).

## People who register records

| Document | What it holds |
|---|---|
| [Portal user guide](portal-user-guide.md) | every task in the portal, step by step, with screenshots: signing in and languages, the editor, keys and qualifiers, targets and the item's page, labels (QR code, Data Matrix, EAN/UPC, PDF, ZIP) and EPCs for RFID and NFC, data attributes, the record list with every search and filter (by text, key type, qualifier, author, link problems, a scanner's or an RFID reader's code), spreadsheets, link checks, requests to the resolver, the overview, messages and what to do |
| [Features](features.md) | every feature, what it does, the commit that brought it and the checks that prove it |

## Organisations' administrators

| Document | What it holds |
|---|---|
| [Portal user guide](portal-user-guide.md), section 14 | users and their prefixes, the organisation's page (prefixes, users, domains, item page brands, single sign-on, API keys, exports, alerts), the audit trail, request log retention, domains, single sign-on, API keys |

## Server administrators and operators

| Document | What it holds |
|---|---|
| [Operator's guide](extensions/README.md) | installation, configuration, every setting, organisations and server administrators, e-mail, the request log and GeoIP, domains and certificates, monitoring, export limits, GS1's GCP length table, backup and restore, replicas and the load test, hardening, going to production |
| [Portal user guide](portal-user-guide.md), section 14 | the screens only server administrators see (organisations, the export maximum, the GCP length table, support access, alerts of the installation) |
| [Changelog](extensions/CHANGELOG.md) | every change on the branch, with the commit |
| [Conformance review](conformance-review.md) | clause-by-clause review against GS1 Digital Link URI Syntax 1.7 and GS1-Conformant Resolver 1.2.1: findings, evidence, candidate errata |

## Integrators

| Document | What it holds |
|---|---|
| [Tenant API reference](api-reference.md) | every operation, parameter, answer and schema of `/portal/api/v1`, generated from the OpenAPI description the API serves |
| [README](../README.md), *Tenant API* and *API reference* | how to call the API and the official data entry API |

## Developers and maintainers

| Document | What it holds |
|---|---|
| [Developer guide](developer-guide.md) | services, source files, request flows, the portal's API, its data, the tests with their counts, how to extend |
| [Development tests](../dev-tests/README.md) | every test program, how to set up and run them |
| [Inventory of features](test-inventory.md) | every check of every test program, grouped by area |
| [History](history.md) | how the project evolved session by session, decisions, lessons, open items |
| [Translation guide](translation-glossary.md) | the rules and glossary for the texts of the twelve interface languages, and how to contribute corrections |
| [Official README](upstream-README.md) | the README of the official GS1 Resolver CE, kept for reference |

## Architecture decision records

| Record | Decision |
|---|---|
| [ADR 0001](adr/0001-portal-state-in-mongodb.md) | the portal's state in MongoDB, background jobs in a worker, more than one replica |
| [ADR 0002](adr/0002-tenants.md) | organisations that own GS1 Company Prefixes, the server administrator, support access, an audit trail per organisation |
| [ADR 0003](adr/0003-gs1-rules-from-the-dictionary.md) | one source for the GS1 rules (the GS1 Barcode Syntax Dictionary), one engine release, engine messages translated, a weekly update check |
| [ADR 0004](adr/0004-e-mail.md) | outgoing mail through an authenticated relay, invitations, password recovery by single-use link, notifications with per-user preferences |
| [ADR 0005](adr/0005-tenant-api.md) | the portal's versioned API for organisations' systems, API keys (scopes, prefixes, expiry, hash only), a request limit per key, an OpenAPI description |
| [ADR 0006](adr/0006-resolver-request-log.md) | the resolver's log of requests without personal data, daily aggregates, attribution at query time; browser, approximate location and retention set in the portal |
| [ADR 0007](adr/0007-overview-indicators.md) | the overview after sign-in: usage, resolution quality, records, operation and governance per scope; exports; `/stats` |
| [ADR 0008](adr/0008-monitoring-and-alerts.md) | monitoring the resolver, the backup, the certificate and spikes of 404, alerts by e-mail |
| [ADR 0009](adr/0009-tenant-domains.md) | an organisation's own domain in the QR code, proved by DNS, served with its certificate without the terminal |
| [ADR 0010](adr/0010-label-studio.md) | the label studio: sizes, PDF, EAN/UPC beside the QR code, every format in a zip; Data Matrix and scanning environments; an EPC for every key |
| [ADR 0011](adr/0011-item-page.md) | the item's page as a record's default target, brands per prefix, Verified by GS1 |
| [ADR 0012](adr/0012-single-sign-on.md) | single sign-on per organisation with OpenID Connect; limits on exports, set in the portal within an installation maximum |
| [ADR 0013](adr/0013-administration-and-navigation.md) | a sidebar, an organisation's page, prefixes as rows, the portal's own dialogs, the overview by organisation, the alert history |
| [ADR 0014](adr/0014-interface-languages.md) | the interface languages (twelve since Turkish was added), Arabic right to left, every text in every language checked, the menus' order |
| [ADR 0015](adr/0015-gcp-length-table.md) | the GS1 Company Prefix's length from GS1's GCP length table, uploaded by the server administrator |
| [ADR 0016](adr/0016-documentation-and-feature-inventory.md) | the documents by reader, the feature inventory drawn from the tests' checks, the API reference generated |

The documentation is written in British English only; readers of other languages can use the translation built into
their browser. The software itself — the portal, its e-mails, the resolver's pages, the item's page and the home page —
speaks twelve languages ([ADR 0014](adr/0014-interface-languages.md)).

Images: `images/` (README) and `images/guide/` (user guide), regenerated by `dev-tests/docs/screenshots.py`.
