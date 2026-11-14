# ADR 0020 — A security assessment for a healthcare information chain

| | |
|---|---|
| Status | **Accepted** (13 November 2026). Phase 0, the threat model, delivered with this record on 14 November; the later phases are items 10.1 to 10.5 of the open backlog |
| Backlog item | The owner's request of 13 November 2026: a deep security assessment, with a view to validating the system for medicines and medical devices |
| Decided by | the owner of the branch, who chose the recommended option (the threat model first); the recommended option on the points of section 4 |

## 1. Context

The resolver is meant to answer the codes on **medicines and medical devices**: a scan of a pack or a device leads to
its patient information leaflet, the manufacturer's information, a safety notice or a recall notice. A wrong answer
there is not a broken link but a patient reading the wrong leaflet, or not learning of a recall. The owner wants the
system validated, in future, as part of a healthcare information chain, and asked for a deep assessment of its
security: against attacks from the internet (by people and by automated, AI-driven tools that probe at scale), one user
or organisation against another, wrong data registered, wrong routing decisions and other sensitive failures.

The software has grown in 26 sessions to a resolver, a data entry API, a portal with organisations, single sign-on,
API keys, custom domains, forwarding, an item's page and a worker. Many controls exist — each written with the feature
it protects — but nothing yet describes the system as an attacker or a hazard analyst sees it, and no review has looked
at all of it with security as the only question.

The fork is public. A document that names a weakness before it is fixed hands it to an attacker; the security notice
to the official maintainers about the public `GET /api/index` (29 October 2026) was sent privately for that reason.

## 2. Decision

1. **An assessment in phases**, each a step of the open backlog:
   - **Phase 0 — threat model** (this delivery): [`Documentation/threat-model.md`](../threat-model.md) describes the
     services and their trust boundaries, the assets ranked by their effect on patient safety, the actors, every entry
     point, the threats and the controls that answer them with the code that implements each, the patient-safety
     hazards that are not attacks, the gaps phrased as controls, and the plan of phase 1.
   - **Phase 1 — review of the code by area**: tenant isolation and authorisation on every route; authentication,
     sessions, single sign-on, recovery and API keys; the resolver's routing decision, parsing, custom domains and
     caching; data entry and the integrity of records; output to browsers; requests the server makes (link checker,
     forwarding, DNS, OpenID Connect discovery); the infrastructure; the supply chain.
   - **Phase 2 — adversarial verification**: a second, independent pass tries to refute each finding; an
     authorisation matrix (every route × role × organisation) and fuzzing of the resolver's path parser become
     permanent development tests.
   - **Phase 3 — fixes**, each with its test, one topic per commit, as every other change.
   - **Phase 4 — dynamic tests on the staging installation**, run by the owner with the steps given (the sessions cannot
     reach the servers), and an **independent penetration test** before production, which the owner decides with item
     7.2.
2. **The lens**: STRIDE for the threats; for the hazards, the approach of ISO 14971 (cause, consequence, mitigation);
   impact rated first by its consequence to a patient, then to the operator. OWASP ASVS, IEC 81001-5-1, GAMP 5, the
   ALCOA+ principles of data integrity and the LGPD are references for what a validation will ask; the documents claim
   compliance with none of them.
3. **Public model, private findings**: the threat model is public and names gaps as missing or partial *controls*.
   Concrete weaknesses — where, how, a reproduction — go into a **private findings register** kept outside the
   repository, in the owner's folder with the handover, until they are fixed. A fix's commit and the changelog then say
   what was wrong at the level an operator needs. A weakness in code that came from the official project is reported
   to its maintainers privately first. *Changed by the owner on 14 November 2026:* such weaknesses are fixed in the fork
   and published with their fix, like the fork's own, without a private notice first; the notice about `GET /api/index`
   of 29 October had no answer, and fixing quickly matters more than waiting. Weaknesses not yet fixed stay out of the
   public documents, wherever the code came from.
4. **Every finding is proved by a development test** that fails on the code before the fix and passes after it (the
   project's mutation rule); the test stays in the suite as a security regression test.
5. **Controls that change the product** — a second factor, approval by a second person for safety-critical link types,
   allowed target domains per organisation and similar — are not decided here: each becomes an item with its own ADR
   when the owner chooses it from the threat model's gaps.

## 3. Design

- `Documentation/threat-model.md`: the model (sections 1–11), kept in step by the delivery that changes a route, a
  role, a service, a stored collection, an external party or a control, as the developer guide is (`CLAUDE.md`,
  *Keep the documents in step*). Where a gap is a live weakness, the model says *private register* and no more.
- The private findings register: one entry per finding (identifier, area, place in the code, description, severity
  with the patient-safety reasoning, confidence, the test that proves it, the fix, its state).
- A test plan with checkboxes for the owner's checks on staging, as for the earlier deliveries.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Order | the threat model first, then the review by area | a broad review of the code first, documented afterwards (faster, but nothing to measure completeness against and less of what a validation asks for); automated scanners and an external penetration test only (cheaper, far narrower) |
| Where findings live | a private register until fixed | issues or documents in the public repository (discloses live weaknesses) |
| Official code (14 November) | fixed and published, as the fork's own (the owner's choice) | a private notice to GS1 first, the fix held until they answer (the recommendation; an earlier notice had no answer) |
| Proof of a finding | a development test that fails before the fix | a description only (findings that cannot be reproduced are kept as *suspected*) |
| Product controls | one item and ADR each, chosen by the owner | decided together here (too large for one record, and each changes how organisations work) |

## 5. Consequences

- The threat model is one more document to keep in step; a change of an entry point or a control that leaves it
  behind makes it misleading.
- Findings are fixed before they are described in public; the changelog describes them afterwards.
- The review cannot replace an independent penetration test, which a validation will ask for; it reduces what that
  test finds and what it costs.

## 6. Delivery

Phase 0 (14 November 2026): the code and the documents read by an AI reviewer, its claims checked against the code,
the most serious by running it (the portal and the resolver in process, with the real GS1 Barcode Syntax Engine);
`Documentation/threat-model.md`; the private register with 29 findings in the fork's code and 6 in code that came
from the official project; the open questions of the model's section 11 put to the owner. No change to the software.
