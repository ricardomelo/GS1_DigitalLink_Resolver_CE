# Third-party software, data and licences

What the GS1 Digital Link Resolver CE — Expansion Pack is made of besides its own code, under which licence, and what
that means for anyone who installs and runs it, commercially or not. This is a summary for orientation, not legal
advice: the licences themselves decide, and an operator with doubts asks its own lawyer.

## In short

- **The software is free and open source under the Apache License 2.0** (the official GS1 Resolver CE's licence, kept
  by this fork). Anyone — a person, a company, a GS1 Member Organisation — may download, install, run, change and
  redistribute it, **for profit or not**, without paying anyone and without asking.
- **Every component it installs or ships is under a permissive licence** (Apache 2.0, MIT, BSD, ISC, SIL OFL, PSF) or,
  for MongoDB, under the SSPL, which restricts only offering *MongoDB itself* as a service — not running an application
  on it. Nothing in them forbids commercial use.
- **What an operator must do**: keep the licence and copyright notices when redistributing (Apache 2.0, section 4);
  show the attribution of the GeoIP database (*IP geolocation by DB-IP*, CC BY 4.0) — the portal does it on the
  screens that show locations; obtain GS1's GCP length table under GS1's own terms; and respect **trademarks**: the
  licences give no right to the GS1 name or logo (Apache 2.0, section 6): the pages show the project's own logo, and an
  operator does not suggest that GS1 endorses its service.
- **No warranty, no liability**: the software is provided "as is" (Apache 2.0, sections 7 and 8). Whoever runs an
  installation is responsible for it — its operation, its data, its privacy notice and the law of its country. Neither
  GS1 nor anyone who contributed to the software answers for it.

## The project's own code

| Part | Licence | Notes |
|---|---|---|
| GS1 Resolver CE v3 (the official project: resolver, data entry API, proxy, installer) | Apache 2.0, © GS1 AISBL | `LICENSE` at the root |
| The Expansion Pack (portal, resolver changes, scripts, tests, documents) | Apache 2.0, as a derivative work | changes recorded in `Documentation/extensions/CHANGELOG.md` (Apache 2.0, section 4 b) |
| Interface translations (`portal/static/i18n.js`, `portal/static/locales/*.json`, `portal/mail_languages.json`, `web_server/src/page_texts.json`, `frontend_proxy_server/home/home.js`) | Apache 2.0 | drafts other than pt-BR and en-GB; corrections by native speakers are welcome as pull requests (`Documentation/translation-glossary.md`) |

## Components installed or shipped with it

| Component | Used for | Licence |
|---|---|---|
| GS1 Barcode Syntax Engine (`gs1-syntax-engine`, built in the images) | parsing and checking GS1 element strings and Digital Link URIs; its Syntax Dictionary gives `portal/gs1_dictionary.json` | Apache 2.0, © GS1 AISBL |
| GS1 Digital Link toolkit (`GS1DigitalLinkToolkit.js`, from the official project) | the resolver's compression and decompression | Apache 2.0, © GS1 AISBL |
| EPC Tag Data Translation artefacts (`web_server/src/tdt`, from the official project) | decoding and encoding EPCs | Apache 2.0 with the official project; the standard itself is GS1's |
| GS1 Web Vocabulary (link types, read from `github.com/gs1/WebVoc` into `portal/gs1_link_types.json`) | the link types and their names | Apache 2.0, © GS1 AISBL |
| Python 3.12 (`python:3.12-slim-bookworm` images, Debian) | the portal, the resolver, the data entry API | PSF; Debian's packages under their own free licences |
| Node.js 24 (in the resolver's image) | running the Digital Link toolkit | MIT |
| MongoDB Community Server 7 (`mongo:7-jammy`) | the database | Server Side Public License v1 — see below |
| nginx (`nginx:1.30-alpine`, and the host's) | the proxy | BSD-2-Clause |
| Certbot and Let's Encrypt (on the host, optional) | certificates | Certbot: Apache 2.0; Let's Encrypt: its Subscriber Agreement |
| Flask, Werkzeug, flask-restx, Flask-Cors, Flask-PyMongo, python-dotenv | web applications | BSD (3- or 2-clause), Flask-Cors MIT |
| gunicorn | application server | MIT |
| pymongo, requests, bcrypt, maxminddb, tzdata | database, HTTP, passwords, GeoIP file, time zones | Apache 2.0 |
| segno | QR codes | BSD-3-Clause |
| zint-bindings and libzint | Data Matrix and GS1 DataMatrix | Apache 2.0 (bindings), BSD-3-Clause (libzint) |
| fonttools, openpyxl, PyJWT | fonts in SVG labels, spreadsheets, single sign-on tokens | MIT |
| Pillow | images (logos, PNG labels) | MIT-CMU (HPND) |
| cryptography | single sign-on | Apache 2.0 or BSD-3-Clause |
| dnspython | the DNS proof of organisations' domains | ISC |
| Liberation Sans (`portal/assets/fonts`) | the text of labels | SIL Open Font License 1.1 (`OFL.txt`); embedding in labels allowed |
| d3 7.9.0, topojson-client 3.1.0 and world-atlas 2.0.2 (`portal/static/d3.min.js`, `topojson-client.min.js`, `world-countries.json`) | the map of requests | ISC; the map data are Natural Earth's (public domain) |

**MongoDB and the SSPL.** The SSPL's extra condition (its section 13) applies to whoever offers *the functionality of
MongoDB* to third parties as a service (a hosted database). Running the resolver and its portal on MongoDB — even as a
paid service to other companies — uses MongoDB as the application's database, which the SSPL does not restrict. An
operator unsure of its own case can read MongoDB's licensing FAQ, or run another MongoDB edition it holds a licence
for.

## Data and services from outside

| What | Where it comes from | Terms | Commercial use |
|---|---|---|---|
| GeoIP database (approximate location of requests) | **DB-IP** *IP to City Lite*, downloaded monthly by `scripts/geoip-update.sh` from db-ip.com | Creative Commons Attribution 4.0 International | allowed, **with the attribution** *IP geolocation by DB-IP* (linked to db-ip.com), which the *Requests* screen and the documentation show. `GEOIP_URL` may name another source (MaxMind GeoLite2 needs an account and has its own licence) |
| GS1's GCP length table (`GCPPrefixFormatList.xml`) | GS1, or the operator's GS1 Member Organisation | GS1's terms; protected since December 2025 | the operator obtains it and uploads it in the portal; never in this repository |
| Google Maps | links from the *Requests* screen (a search by a city's name) | Google's terms, for the person who follows the link | nothing is embedded and no key is used; no data is sent until someone clicks |
| GS1 standards (Digital Link, General Specifications, Tag Data Standard, Conformant Resolver) | gs1.org | published by GS1 for anyone to implement; GS1's IP Policy and disclaimers | implementing them needs no licence from GS1; GS1 gives no warranty about third parties' patents |
| The map of countries | Natural Earth, through world-atlas | public domain | allowed |

## Trademarks

*GS1*, the GS1 logo and *GS1 Digital Link* are trademarks of GS1 AISBL. The Apache License grants no right to them
(section 6). Since 20 October 2026 the headers of the portal, the home page and the resolver's pages show the
project's own logo (`logo.svg`; `Documentation/images/logo`, Apache 2.0 like the code) instead of the GS1 logo the
official project shipped (`gs1-logo.png`, still in the repository, no longer shown). An operator authorised by GS1 may
show GS1's logo where GS1's brand rules allow; any operator names its service in its own words (for instance "a
resolver for GS1 Digital Link", never "GS1's resolver") and does not suggest that GS1 endorses it.

## Development tools (not installed with the software)

The tests use Playwright and Chromium (Apache 2.0 / BSD), mongomock (ISC), pytest (MIT), AJV (MIT), epc-tds (MIT) and
GS1's resolver test suite; they run on developers' machines and in the CI, not on an installation.

## When this list changes

A new dependency (a line in a `requirements.txt`, an image, a library file under `portal/static`, a data source) adds a
row here in the same delivery, with its licence; a licence that restricts use or needs an attribution is said in
*In short*.
