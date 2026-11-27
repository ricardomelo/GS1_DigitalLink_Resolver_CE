# Security and resilience assessment

Every finding of the assessment is fixed and released in **3.2.0** (23 November 2026): 33 in the code this project
added (F-001 to F-033) and 6 in code that came from the official GS1 Resolver CE (U-001 to U-006). This page says what
was assessed, how, what was fixed and with what proof. It is kept in step by each fix
([ADR 0055](adr/0055-public-assessment-record.md)).

## 1. Why, and what it covers

The resolver is meant to answer the codes on **medicines and medical devices**: a scan leads to a leaflet, product
information, a safety notice or a recall. A wrong, missing, stale or attacker-chosen answer there reaches a patient or
a professional. The assessment ([ADR 0020](adr/0020-security-assessment.md)) therefore judged each finding first by its
consequence for a person scanning a code, then for the operator and the organisations that register links.

It covers the software of this repository as `scripts/install.sh` installs it: the front-end proxy, the resolver, the
official data entry API, the portal and its worker, the database and its initialisation, the installer, the backups,
the host's web server and certificates, the continuous integration and the supply chain. Its lens is STRIDE for
attacks and the approach of ISO 14971 (cause, consequence, mitigation) for hazards that are not attacks; OWASP ASVS,
IEC 81001-5-1, GAMP 5, ALCOA+ and the LGPD are references for what a validation will ask, not claims of compliance.
Threats included the internet at large (people and automated tools that probe at scale), one organisation against
another, a user beyond their role, wrong data registered, wrong routing, and the failure of a part of the system.

## 2. Method

| Step | What it is |
|---|---|
| Threat model | [threat-model.md](threat-model.md): the services and their trust boundaries, the assets ranked by their effect on patient safety, the actors, every entry point, the threats with the controls that answer them (each with the code that implements it), the hazards, the gaps. Kept in step with every change of a route, role, service, stored collection, external party or control |
| Review by area | tenant isolation and authorisation, authentication and sessions, single sign-on, the resolver's routing and parsing, data entry and the integrity of records, output to browsers, requests the server makes, infrastructure, supply chain; the official project's code with the same questions |
| Confidence | each finding marked *run* (confirmed by running the code), *read* (confirmed by reading it and looking for a control elsewhere) or *suspected*; the most serious were run again independently |
| A private register | each weakness — where, how, its consequence — kept outside the repository until fixed; never described in a public document before its fix |
| One fix per delivery | one finding (or one residual) at a time, with its own ADR where it changes a decision, its code and technical documents in one commit, the changelog and the user documents in the next |
| Proof | a development test that fails on the code before the fix and passes after it; it stays in the suite as a regression test. Each new check is proved able to fail by mutating the code it guards (mutation checks); the files are restored and compared by checksum |
| Continuous integration | every push runs the development tests in six jobs (portal, resolver and data entry API with GS1's conformance suite, the portal in a real browser, the home page and proxy on the real nginx, the installer and deployment, and the portal on a real MongoDB); a second workflow looks for known vulnerabilities in lock files and images and attaches an SBOM to each release. The suite holds 7,234 checks in 87 programs ([test-inventory.md](test-inventory.md)) |
| Staging | each delivery comes with a test plan of steps and expected results that the operator runs on a staging installation |

**What it is not.** It is a review by the maintainers with an AI reviewer, not an independent penetration test; a
validation for healthcare will ask for one, before production ([ADR 0020](adr/0020-security-assessment.md), phase 4).
It reduces what such a test should find; it does not replace it.

## 3. Findings fixed

*Severity* is the finding's before its fix. *Completed in* is the commit that completed the fix on the development
branch; the ADR says what was decided and why, and the [changelog](extensions/CHANGELOG.md) what changed for operators.

| ID | What is stronger now | Area | Severity | ADR | Completed in | Release |
|---|---|---|---|---|---|---|
| F-001 | The official data entry API closed to the internet by default; example secrets refused outside development | Architecture | High | [0021](adr/0021-data-entry-api-closed.md) | `8405225` | 3.2.0 |
| F-002 | Deleting one record without rewriting its key | Integrity | High | [0023](adr/0023-record-level-delete.md) | `f5642c5` | 3.2.0 |
| F-003 | The level that answered a scan reported; a strict mode and warnings for safety-critical links | Routing | High | [0022](adr/0022-answering-level.md) | `9114e49` | 3.2.0 |
| F-004 | The client's address taken from trusted proxies only | Authentication | Medium | [0021](adr/0021-data-entry-api-closed.md) | `4d96de1` | 3.2.0 |
| F-005 | Failed sign-ins slowed per user name and address instead of locking accounts | Authentication | Medium | — | `5527110` | 3.2.0 |
| F-006 | Single sign-on domains proved by DNS before they route anyone | Authentication | Medium | [0025](adr/0025-sso-domain-proof-and-subject.md) | `1699d51` | 3.2.0 |
| F-007 | Single sign-on: a verified e-mail and the provider's subject required | Authentication | Medium | [0025](adr/0025-sso-domain-proof-and-subject.md) | `1699d51` | 3.2.0 |
| F-008 | The journal written before each change, sealed in chains, verified daily, insert-only in its own database | Audit | Medium | [0026](adr/0026-journal-integrity.md) | `e51f0c1` | 3.2.0 |
| F-009 | No lost update when two people change one key; a save over a change not seen refused; a save applied whole or not at all | Integrity | Medium | [0027](adr/0027-conditional-writes.md), [0058](adr/0058-record-revision.md), [0059](adr/0059-save-in-one-write.md) | `875db4b`, `b7e282c`, `4e38aa4` | 3.2.0; revision and one write: unreleased |
| F-010 | A leaflet in another language or for another market no longer given silently | Routing | Medium | [0028](adr/0028-language-fallback.md) | `9f28dab` | 3.2.0 |
| F-011 | Requests to addresses users choose contact the address that was checked | Outbound requests | Medium | [0029](adr/0029-outbound-requests.md) | `0d23833` | 3.2.0 |
| F-012 | Each service with its own database user and least privilege, none as root | Infrastructure | Medium | [0030](adr/0030-least-privilege-services.md) | `3e92870` | 3.2.0 |
| F-013 | Request limits per address; anonymous requests counted, not stored one by one | Availability | Medium | [0031](adr/0031-request-limits.md) | `c89c362` | 3.2.0 |
| F-014 | Spreadsheet imports read one row at a time, within limits | Availability | Medium | [0032](adr/0032-spreadsheet-reading-limits.md) | `a5255c4` | 3.2.0 |
| F-015 | The supply chain pinned by content, scanned for known vulnerabilities, with an SBOM per release | Supply chain | Medium | [0033](adr/0033-supply-chain.md) | `30f5879` | 3.2.0 |
| F-016 | Signing out ends the session everywhere | Sessions | Low | [0034](adr/0034-session-records.md) | `9424d30` | 3.2.0 |
| F-017 | The test of the operator's single sign-on reserved to server administrators | Authorisation | Low | — | `8b6d643` | 3.2.0 |
| F-018 | Domain claims that expire, proofs that lapse | Domains | Low | [0035](adr/0035-domain-claims-and-lapsed-proofs.md) | `5405e90` | 3.2.0 |
| F-019 | User names and e-mail addresses of other organisations not disclosed | Privacy | Low | [0036](adr/0036-names-and-addresses-across-organisations.md) | `0f432e2` | 3.2.0 |
| F-020 | Target addresses: HTTPS, public host names, an optional list per organisation | Data entry | Low | [0037](adr/0037-target-addresses.md) | `806ff42` | 3.2.0 |
| F-021 | Content-Security-Policy on every page, HTTPS only; the portal on a host name of its own, when the operator sets one | Browser | Low | [0038](adr/0038-browser-hardening.md), [0057](adr/0057-portal-own-host-name.md) | `7447750`, `6933371` | 3.2.0; own host name: unreleased |
| F-022 | Only the installation's own host names in the resolver's answers | Resolver | Low | [0039](adr/0039-known-public-names.md) | `e8e7a23` | 3.2.0 |
| F-023 | Malformed request bodies refused before the route | Robustness | Low | [0040](adr/0040-request-bodies.md) | `eda6315` | 3.2.0 |
| F-024 | A queued import stops when its account may no longer write | Authorisation | Low | [0041](adr/0041-queued-import-account.md) | `4bb4928` | 3.2.0 |
| F-025 | Access logs without the client's address or the query string | Privacy | Low | [0043](adr/0043-access-logs.md) | `909b826` | 3.2.0 |
| F-026 | Encrypted backups; single sign-on secrets sealed in the database | Secrets | Low | [0044](adr/0044-encrypted-backups-and-sealed-secrets.md) | `513b9a5` | 3.2.0 |
| F-027 | Only the resolver on an organisation's own domain | Domains | Low | [0045](adr/0045-organisation-domains-resolver-only.md) | `f6054b0` | 3.2.0 |
| F-028 | Organisations told when forwarding sends their codes elsewhere, including for a prefix they are given | Routing | Low | [0046](adr/0046-forwarding-tells-organisations.md), [0054](adr/0054-forwarding-tells-new-prefixes.md) | `3941d91` | 3.2.0 |
| F-029 | The types of a request body's fields checked | Robustness | Info | [0040](adr/0040-request-bodies.md) | `eda6315` | 3.2.0 |
| F-030 | The host's web server installed and kept up to date by the installer | Infrastructure | — | [0042](adr/0042-host-nginx.md) | `7c3bea5` | 3.2.0 |
| F-031 | A failure of the records' database answered "try again", never "not registered" | Resolver | Low | [0051](adr/0051-records-unavailable.md) | `98c083b` | 3.2.0 |
| F-032 | One time budget for a request's database reads | Availability | Low | [0052](adr/0052-database-time-budget.md) | `990b469` | 3.2.0 |
| F-033 | Settings the resolver cannot read again expire, with an alert | Resolver | Low | [0053](adr/0053-settings-age.md) | `5df16ce` | 3.2.0 |
| U-001 | Template values can no longer change a redirect's target | Official resolver | Medium | — | `8c06f72` | 3.2.0 |
| U-002 | Compressed links decompressed within limits | Official resolver | Medium | [0047](adr/0047-toolkit-processes.md) | `642839d` | 3.2.0 |
| U-003 | Targets sent to the data entry API follow the portal's rule; targets stored before reported to the operator | Official data entry API | Medium | [0048](adr/0048-data-entry-target-rule.md), [0056](adr/0056-records-outside-the-rules.md) | `af12fac` | 3.2.0; report: unreleased |
| U-004 | Anchors of one shape and one document id per anchor; anchors stored before under other shapes reported to the operator | Official data entry API | Low | [0049](adr/0049-data-entry-anchors.md), [0056](adr/0056-records-outside-the-rules.md) | `af12fac` | 3.2.0; report: unreleased |
| U-005 | No lost update in the data entry API's writes | Official data entry API | Medium | [0027](adr/0027-conditional-writes.md) | `875db4b` | 3.2.0 |
| U-006 | Error answers without the exception's text; images without a root user or an editor | Official images | Low | [0030](adr/0030-least-privilege-services.md), [0050](adr/0050-error-answers.md) | `6653986` | 3.2.0 |

## 4. Resilience and performance

A resolver for healthcare must keep answering correctly when parts of the system are slow, overloaded or down — and
say so honestly when it cannot.

| Concern | What the system does now |
|---|---|
| Load from one address | per-address limits at the proxy and in the portal; anonymous requests counted rather than written one by one (F-013, [ADR 0031](adr/0031-request-limits.md)) |
| Heavy requests | spreadsheets read row by row within limits (F-014); compressed links checked by pattern first, then decompressed by at most two Node.js processes at a time per server process, each with a time limit, recent answers kept (U-002); the syntax of every link checked in process |
| The records' database fails | the scan is answered 503 with *Retry-After* and a page that asks to try again — never "not registered", never sent to the resolver of last resort (F-031) |
| The database is slow or unreachable | one time budget for all of a request's reads (5 seconds by default), so a scan is answered within seconds and server threads are not held (F-032) |
| The portal's settings cannot be read | after 15 minutes the resolver stops applying forwarding, brands and appearance (whose absence is the safer answer), keeps domains and the strict mode, and the portal alerts the server administrators (F-033) |
| Monitoring | the portal checks the resolver, backups, certificates, the journal's chains and the resolver's settings, and alerts by e-mail ([ADR 0008](adr/0008-monitoring-and-alerts.md)) |
| Throughput | one load test on staging (15 October 2026) found the resolver CPU-bound at about 26 requests a second, because the official code started a process for every syntax check; the check now runs in process. The test has not been repeated since; more exhaustive tests before production are listed in the [operator's guide](extensions/README.md#load-test-and-scale-out-rehearsal) |

## 5. Hardening in progress

Every finding is fixed. Each fix records smaller improvements that remain possible; they are worked on one at a time
and described here only as categories, until each is done:

- authentication, sessions and credentials;
- the separation of the portal from the resolver;
- reports for the operator on records stored in earlier versions;
- notifications to organisations;
- logs, alerts and observability;
- caching;
- the build and the supply chain.

## 6. For operators

- **Install the latest release** (`master`, tag `vX.Y.Z`): security fixes are released soon after they land on the
  development branch, and each changelog entry says what to do when updating.
- **Keep the host's nginx and Certbot up to date**: run the installer again after a security release of nginx, or
  rely on Ubuntu's unattended upgrades ([ADR 0042](adr/0042-host-nginx.md)).
- Follow the operator's guide's *Hardening* and production checklist; keep `DATA_ENTRY_API_ALLOW` empty unless an
  integration needs the official data entry API.
- **Report a vulnerability privately**, as [SECURITY.md](../SECURITY.md) says.

## 7. How this record is kept

A row is added in the delivery that fixes a finding, once the fix is on the development branch; its release is filled
in when a release carries it. Nothing here describes a weakness that is not yet fixed
([ADR 0055](adr/0055-public-assessment-record.md)).
