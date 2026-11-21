# ADR 0035 — Domain claims that expire, and proofs that lapse

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-T2, T-A6 and hazard H-12, gap G-20 of the [threat model](../threat-model.md); findings F-018 and F-006 (its residual) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): unverified domains become claims that several organisations may hold and that expire after 7 days, the first proved wins; the TXT record of every verified domain and of every DNS proof of single sign-on is looked at again daily, and missing for 7 days the domain or proof has *lapsed*: still served, no longer offered for new labels, its administrators told, and another organisation that proves it takes it over |
| Amends | [ADR 0009](0009-tenant-domains.md) §§ 2–3 (one document per name, never un-verified) and [ADR 0025](0025-sso-domain-proof-and-subject.md) § 2.1 (proofs that never expire) |

## 1. Context

A domain of an organisation's QR codes ([ADR 0009](0009-tenant-domains.md)) is a document keyed by its name in the
`domains` collection. It was unique in the installation from the moment it was added, before any proof: an
administrator of one organisation could add another organisation's domain and never verify it, and the rightful
organisation was refused (`domains.exists`) for as long as the entry stayed. In the other direction, a verified domain
stayed verified for ever: the daily look at its TXT record only recorded when the record was last seen. A domain whose
registration lapsed, or that changed hands, stayed the default domain of its prefixes on new labels and nobody was told.

Single sign-on's domain proofs ([ADR 0025](0025-sso-domain-proof-and-subject.md)) had the second half of the same
weakness: a proof by DNS never expired, and kept any other configuration from proving the domain.

## 2. Decision

### 2.1 Claims

- Adding a domain makes a **claim**: a document under the key `"<name> <tenant>"` (`"<name> -"` for the operator;
  `domains.pending_id()`), with the field `name` and `expiresAt` = the time it was made + 7 days (`domains.PENDING`).
  A TTL index on `expiresAt` (`store.INDEXES["domains"]`) deletes it; until MongoDB's monitor does (about once a
  minute) the portal ignores a claim whose time is up (`_live()`).
- Several organisations (and the operator) may claim the same name; each scope only once, and not a name another scope
  has verified and that has not lapsed (`domains.exists`). A claim counts towards the 10 domains of its scope.
- **The first claim proved becomes the domain**: `verify()` writes it under the key `"<name>"` (what the resolver,
  `scripts/custom-domains.sh` and `domain_hosts` already read), without `expiresAt`, and deletes the other claims of the
  name. The card of a claim shows when it will be deleted.
- At the first start of this version (`domains.upgrade()`, idempotent) every document gets its `name`; an unverified one
  becomes a claim deleted 7 days after the upgrade.

### 2.2 Lapsed domains

- The worker's hourly housekeeping (`app.recheck_domains()`) looks at each verified domain's TXT record once a day
  (`domains.recheck_all()`, as before). Found, the domain is seen now. Missing for 7 days (`domains.LAPSE`) since it was
  last seen (or verified), the domain **lapses** (`lapsedAt`):
  - the resolver keeps serving it (labels already printed keep working while the name still points here);
  - it is no longer the default domain of its prefixes nor a domain to choose for new labels (`usable()`,
    `default_for()`, `label_base()`, the label panel's list): labels carry the installation's address instead;
  - the event `domain-lapsed` (by `-`) goes into the scope's audit trail and the message `alert-domain-lapsed`
    (category *alerts*) to the scope's administrators (server administrators for the operator's domains), once;
  - a claim of another scope may be made, and when proved it **takes the domain over**: the lapsed domain and the
    host's report of it are deleted and `domain-released` goes into the first scope's trail.
- Seen again, by the daily look or by *Verify* on its card, the domain is no longer lapsed (*Verify* journals
  `domain-verify` again).

### 2.3 Single sign-on

- A DNS proof records `seenAt`. `sso.recheck_proofs()` (in the same housekeeping) looks at each DNS proof's record
  (`gs1resolver-sso=<token>`) once a day; missing for 7 days the proof lapses (`lapsedAt`), with the same journal event
  (`sso <domain> …`) and message.
- A lapsed proof **still signs people in**: ending it would lock out the organisation's users, who may have no
  password. It no longer keeps another configuration from listing and proving the domain (`proved_elsewhere()`); that
  proof, by DNS or by a server administrator's approval (still refused while accounts of another organisation use the
  domain), removes the lapsed one (`domain-released` in its trail). *Verify* with the record back makes a fresh proof.
- Approvals and proofs of the upgrade have no record to look at and do not lapse.

### 2.4 Alternatives not taken

- *Un-verify a lapsed domain*: the resolver would stop answering on it at once, breaking printed labels after a DNS
  outage of a few days; lapsing keeps them working and only stops new labels from carrying the domain.
- *Only expire unverified entries, keeping one per name*: a claimant could add the name again as soon as it expired.
- *Lapse after a shorter time*: a week rides out a DNS provider's outage or a mistaken edit noticed late.

## 3. Consequences

- Finding F-018 fixed; F-006's residual (proofs never expire) fixed for DNS proofs.
- Residuals: approvals and upgrade proofs never lapse; a lapsed domain is still served (by design); no "record found
  again" message (the card shows it); `LAPSE` and `PENDING` are constants, not settings; the claims of a name are not
  shown to the other claimants (each sees its own).
- Tests: `test_domains.py` (claims, expiry, lapse, take-over, upgrade), `test_sso.py` (proofs looked at again, lapse,
  take-over), `test_store_mongodb.py` (the TTL index deletes a claim, keeps a verified domain); 32 mutations, all
  caught.
