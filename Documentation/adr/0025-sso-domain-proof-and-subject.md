# ADR 0025 — Single sign-on: e-mail domains proved, a verified e-mail required, the account bound to the provider's subject

| | |
|---|---|
| Status | **Accepted** (16 November 2026). DNS proofs looked at again daily and lapsed after 7 days missing: [ADR 0035](0035-domain-claims-and-lapsed-proofs.md) (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); amends [ADR 0012](0012-single-sign-on.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): a DNS record or a server administrator's approval proves an e-mail domain; `email_verified` is required unless the configuration says its provider never sends it; the account is bound to the provider's issuer and subject at its first sign-in |

## 1. Context

ADR 0012 lets an organisation's administrators list the e-mail domains whose people sign in through their identity
provider. Two weaknesses followed from it.

1. **A domain was claimed by typing it.** The first configuration to list a domain held it: another organisation's
   domain, or a public mailbox domain, could be listed by any organisation's administrator. The rightful
   organisation was then refused (`sso.domainTaken`), and anyone typing an address of that domain on the sign-in page
   was sent to the claimant's provider with the address as a hint. The sign-in itself failed (the account must belong
   to the configuration's organisation), so this denied single sign-on rather than giving an account away.
2. **The account was matched by the `email` claim alone.** Only an explicit `email_verified: false` was refused, and
   the provider's subject (`sub`) was never recorded. Where a member of the provider's directory can set an
   unverified mail attribute, they could present the portal administrator's address and sign in as that account; an
   administrator of the provider could sign in as any account of the organisation, and the journal would name the
   victim.

## 2. Decision

### 2.1 E-mail domains are proved

1. **A listed domain signs nobody in until it is proved.** Proof is either:
   - a **DNS TXT record** at `_gs1resolver.<domain>` holding `gs1resolver-sso=<token>`, the token being the
     configuration's own (shown on the screen, like the domains of ADR 0009, whose record lives at the same name with
     another prefix, so one name can hold both); the screen's *Verify* looks it up; or
   - a **server administrator's approval** (outside support access), for an organisation that cannot publish a record
     and for the operator's own configuration.
   The organisation's administrators can verify but not approve.
2. **A domain is proved in one configuration at most.** Saving refuses a domain proved by another configuration
   (`sso.domainTaken`); a domain only listed elsewhere, not proved, blocks nobody and routes nobody. Verifying or
   approving refuses a domain proved elsewhere in the meantime.
3. **Approval is refused** for a domain that accounts of another organisation, or of the operator, use in their
   e-mail addresses (`sso.domainUsed`): a server administrator approving by hand should not hand those people's
   domain to someone else. A DNS proof is not refused for that reason: whoever controls the domain's DNS controls its
   mail.
4. **Removing a domain from the list removes its proof.** A proof stays otherwise (as for ADR 0009's domains; its
   expiry is finding F-018's and applies to both).
5. **Sign-in uses proved domains only**: the e-mail typed on the sign-in page chooses the switched-on configuration
   that proved its domain, and the provider's answer must carry an address of a proved domain of that configuration.
6. **Password sign-in off** (ADR 0012 §2.4) applies only to accounts whose e-mail domain is proved in their
   organisation's configuration: switching it on before a domain is proved cannot lock anyone out.
7. **Configurations saved before this version** keep working: at the first start their listed domains are recorded
   as proved *at the upgrade*, which the screen shows with the record to publish, so that an administrator can
   replace it with a DNS proof or remove the domain. The changelog asks operators to look at them.

### 2.2 A verified e-mail, and the provider's subject

8. **`email_verified` must be `true`.** A configuration may say that its provider never sends the claim (Microsoft
   Entra ID, for one, does not by default): then a missing claim is accepted; `false` is always refused.
9. **The first sign-in through single sign-on binds the account** to the token's issuer and subject (`iss`, `sub`).
   Later sign-ins must present the same subject for that issuer (`sso.subjectMismatch` otherwise), and a subject bound
   to one account cannot sign in to another (`sso.subjectTaken`). A binding to another issuer is replaced at the next
   sign-in: the configuration's issuer changed, which the journal already records (`sso-save`).
10. **The binding goes** when an administrator who manages the account forgets it on the *Users* screen (a person's
    account at the provider was recreated; journal `user-update … sso-forgotten`), and when the account's e-mail
    address changes.
11. **The journal** names the subject: `login` records `single sign-on <provider's host> subject <sub>` (and
    `bound` at the first), and a refused subject is recorded in `login-failed`.

## 3. Design

- `portal/sso.py`: the configuration gains `token` (32 hex, made at the first save), `proofs` (`[{"domain", "how":
  "dns" | "admin" | "upgrade", "at", "by"}]`) and `emailVerifiedOptional`; `proved(doc)`, `verify_domain(scope,
  domain)` (DNS through `domains.txt_records()`), `approve_domain(scope, domain, by)`, `upgrade()` (called at
  start-up, idempotent: a configuration without `proofs` gets one `upgrade` proof per listed domain);
  `clean_domains()` checks only proved domains elsewhere; `save()` keeps the proofs of the domains still listed;
  `for_email()`, `password_off_for()` and `finish()` read proved domains; `finish()` checks `email_verified` and the
  subject (`bind()`), and returns the subject and whether it was bound.
- `portal/users.py`: the account's optional field `sso` (`{"iss", "sub", "at"}`), `bind_sso()`, `update(...,
  sso_forget=)`; a changed e-mail drops it; `public()` shows it to administrators.
- `portal/app.py`: `POST /portal/api/sso/<scope>/verify` and `/approve` `{domain}`; `PUT /portal/api/users/<name>`
  accepts `ssoForget`; the callback writes the subject into the journal.
- The *Single sign-on* screen lists each domain with its state (proved by DNS, approved, at the upgrade, waiting for
  the record), the record's name and value, *Verify* and, for server administrators, *Approve* — the Domains screen's
  card (ADR 0009) — and the option *The provider does not send email_verified*. The *Users* screen shows a bound
  identity and *Forget*.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Proof of a domain | DNS TXT record, or a server administrator's approval | approval only (every organisation waits for the operator); DNS only (no way for an organisation without DNS access, nor for the operator's own staff on a public mailbox domain) |
| A domain listed by two configurations | allowed, proved in one only | first to list it holds it (the weakness itself) |
| Accounts of another organisation at the domain | refuse an approval | refuse a DNS proof too (an organisation could block the rightful one by creating an account with that domain) |
| Configurations already in use | their domains accepted at the upgrade, shown as such | unproved at once (organisations with password sign-in off locked out by an upgrade) |
| A provider that never sends `email_verified` | an option per configuration | refuse it (Entra ID unusable); accept a missing claim everywhere (the weakness itself) |
| The subject | bound at the first sign-in, forgotten by an administrator | stored by the administrator in advance (nobody knows a provider's subject); not bound (the weakness itself) |

## 5. Consequences

- An organisation publishes one TXT record per domain, or asks a server administrator to approve it.
- Configurations with Entra ID must tick the new option, or their users are refused with `sso.noEmail`.
- A person whose account at the provider is recreated is refused until an administrator forgets the binding.
- Stored data: the `sso` collection's documents and the user accounts gain fields; nothing is removed, and backups
  restore as before.

## 6. Delivery

This record; `portal/sso.py`, `portal/users.py`, the routes, the two screens; texts in the twelve languages; checks in
`test_sso.py` and `test_sso_e2e.py`, mutation-checked; ADR 0012's note, the developer guide, the threat model, the
changelog, features and the portal guide.
