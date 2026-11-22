# ADR 0054 — An organisation given a prefix that a forwarding rule already covers is told

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); hazard H-13 and gap G-21 of the [threat model](../threat-model.md); finding F-028 (a residual of [ADR 0046](0046-forwarding-tells-organisations.md)) |
| Decided by | the owner's standing instruction for the assessment's residuals, the owner away: the recommended option taken — when a server administrator creates an organisation or changes its prefixes, each rule switched on that covers a prefix it did not have before is an event in its own trail and an alert to its administrators, as for a rule that starts to cover it. Not taken: refusing a prefix that a rule covers (an organisation joining while its codes are still forwarded during a move is the usual case); a confirmation step on the *Organisations* screen before saving (the server administrator already sees on the *Forwarding* screen which organisations each rule covers; the point is to tell the organisation); telling it again when prefixes it already had are saved again, or when prefixes are taken away (where its codes go does not change for the prefixes it keeps) |
| Amends | [ADR 0046](0046-forwarding-tells-organisations.md) §2.1 (a change of an organisation's prefixes, too) |

## 1. Context

[ADR 0046](0046-forwarding-tells-organisations.md) tells an organisation when a forwarding rule starts or stops sending
its codes elsewhere — when the **rule** changes. Where an organisation's codes go also changes when its **prefixes**
change: a server administrator who gives it a prefix that a rule switched on already covers takes that prefix's codes
away from its records from the first save, and the organisation's trail held only `tenant-update` (or
`tenant-create`) with the new prefixes. Its administrators could edit records for the new prefix that no scan would
ever reach, and not know why.

## 2. Decision

1. **When**: a server administrator creates an organisation (`POST /portal/api/tenants`) or changes its prefixes
   (`PUT /portal/api/tenants/{id}`). For each rule **switched on** whose prefix overlaps (`forwarding.covered()`, one
   starts with the other) a prefix the organisation **has now and did not have before**
   (`forwarding.newly_covered(previous, tenant)`).
2. **What**, for each such rule (`app.tell_covered(tenant, previous)`, after the operator's own event):
   - the event **`forwarding-covered`** in the organisation's own audit trail, by the server administrator, marked *by
     the operator*, with the rule's prefix, its destination and the prefixes given that it covers
     (`prefix=… target=… prefixes=…`);
   - the message **`forwarding-covered`** to the organisation's administrators, in the *alerts* category (on by
     default; Options → E-mail): the prefixes it was given, the rule's prefix and destination, the time, that what it
     saves for those codes is not what a scan finds while the rule is on, and whom to ask.
3. **Not told**: the same prefixes saved again, another field changed, prefixes taken away, a prefix that only a rule
   switched off covers, a prefix no rule covers. An organisation created with such a prefix has no administrator yet:
   the event is in its trail, which its first administrator sees.
4. Two rules over the same prefix (a shorter and a longer one) are two events and two messages, one per rule, as in
   ADR 0046.

## 3. Consequences

- An organisation learns that some of its codes are answered elsewhere both when a rule changes (ADR 0046) and when
  its own prefixes change; the event in its trail proves when and by whom.
- Messages follow `notify.send()`: none without mail configured, none to disabled accounts or organisations, none to an
  administrator who switched alerts off.
- The hint on the *Forwarding* screen already says that each change that sends an organisation's codes elsewhere is in
  its trail and told to its administrators: unchanged.

## 4. Residuals

- As in ADR 0046 §4, less its first item: the message does not say whether another rule also covers the codes; no
  confirmation with the number of records before saving; an administrator with alerts off, or an installation without
  e-mail, learns it from the trail only; support access is still not told to the organisation.

## 5. Delivery

`portal/forwarding.py` (`newly_covered()`); `portal/app.py` (`tell_covered()`, called by `create_tenant()` and, when
the prefixes changed, `update_tenant()`); `portal/notify.py` (`forwarding-covered` in *alerts*); the message in the
twelve languages (`portal/mailtexts.py`, `portal/mail_languages.json`); `audit.action.forwarding-covered` in the twelve
languages (`portal/static/i18n.js`, `portal/static/locales/`).
Tests: `test_forwarding.py` 75 → 90 (the administrator told with the rule's prefix, destination, the prefixes given
and the time; the event in its own trail, by the operator, beside `tenant-update`, seen in its *Audit trail*; nobody
else; nothing for the same prefixes saved again, a prefix no rule covers, prefixes taken away, a rule switched off;
prefixes shorter and longer than the rule's; two prefixes, one message; two rules, two messages; an organisation
created with such a prefix; the message in every language; its category); 11 mutations, all caught.
