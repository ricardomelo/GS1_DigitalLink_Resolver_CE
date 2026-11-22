# ADR 0046 — A forwarding rule told to the organisations whose codes it sends elsewhere

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); hazard H-13 and gap G-21 of the [threat model](../threat-model.md); finding F-028 |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken. Not taken: an approval by the organisation before a rule covering its prefixes takes effect (forwarding is the operator's decision, often for a move the organisation is not part of, and a rule that waits cannot answer an emergency); refusing rules that overlap an organisation's prefixes (the case ADR 0018 was made for); a message for every change, a note included (noise that teaches administrators to ignore the message); the *security* category, always sent (it is for the account's own credentials; the change is in the organisation's trail whatever its administrators chose) |
| Amends | [ADR 0018](0018-forwarding.md) §2.4 (who is told of a rule) |

## 1. Context

A forwarding rule ([ADR 0018](0018-forwarding.md)) sends every code of a prefix to another address **before** this
resolver's records: the records of an organisation whose prefixes the rule overlaps are no longer what a scan finds —
for a medicine, the leaflet the organisation keeps up to date is bypassed. The *Forwarding* screen names the
organisations concerned to the server administrator who saves the rule, and the change is a journal event — in the
operator's trail only (`tenant=None`). The organisation itself was never told: its administrators could see that their
codes were *forwarded* in the overview's figures, after the fact, and nowhere else. A mistyped prefix, a rule left on
after a move, or an operator acting against an organisation would go unnoticed by the people responsible for the
information.

## 2. Decision

1. **A change that changes where an organisation's codes go** is told to it. A rule *sends codes* while it is on, to
   its destination with its mode; a change does so when that differs before and after: a rule created on, switched
   on or off, removed while on, or given another destination or mode while on
   (`forwarding.changes_destination()`). A note changed, or a rule that stays off, tells nobody.
2. **The organisations concerned** are those with a prefix the rule's prefix overlaps (one starts with the other,
   `forwarding.covered()`): a rule shorter than an organisation's prefix takes all its codes, a longer one some.
3. For each of them:
   - **its own audit trail** receives the same event as the operator's (`forwarding-rule-create`, `-update`,
     `-remove`, with the rule's prefix, destination and state), by the server administrator, marked *by the operator*;
   - **its administrators** receive a message, in the *alerts* category (on by default; Options → E-mail):
     `forwarding-on` — its codes of the prefix now go to the destination, with the organisation's prefixes covered and
     the time, the records themselves unchanged, whom to ask; `forwarding-off` — the rule no longer sends them there,
     so, unless another rule covers them, they are answered again from the records, to be checked.
4. The *Forwarding* screen says so to the server administrator, beside the rules.

## 3. Consequences

- An organisation learns of a rule over its prefixes when it takes effect and when it ends, and can ask the operator;
  the event in its trail proves when and by whom, whether or not its administrators read the message.
- Messages follow `notify.send()`: none without mail configured, none to disabled accounts or organisations, none to an
  administrator who switched alerts off.
- The operator's trail keeps its event as before; an organisation's trail now holds events by the operator about the
  installation's forwarding.

## 4. Residuals

- An organisation given a prefix that an enabled rule already covers (its prefixes changed by a server administrator)
  is not told; the screen names it beside the rule.
- The message for one rule does not say whether another rule (shorter or longer) also covers the codes; the longest
  prefix wins.
- No confirmation with the number of records concerned before saving (H-13's second suggestion); support access is
  still not told to the organisation (the other half of G-21).

## 5. Delivery

`portal/forwarding.py` (`covered()`, `destination()`, `changes_destination()`; `overlaps()` built on `covered()`);
`portal/app.py` (`tell_forwarded()`, called by the three rule routes after the operator's event); `portal/notify.py`
(`forwarding-on`, `forwarding-off` in *alerts*); the two messages in the twelve languages (`portal/mailtexts.py`,
`portal/mail_languages.json`); `forwarding.rulesHint` in the twelve languages (`portal/static/i18n.js`,
`portal/static/locales/`).
Tests: `test_forwarding.py` (the organisation's administrator told, with the prefix, the destination, its prefixes
covered and the time, editors and other organisations not; the event in its own trail, by the operator, and seen in
its *Audit trail*; nothing for a note or a rule that stays off; told again for another destination or mode, at
switching off and at removal while on; rules shorter and longer than the organisation's prefix; two organisations each
told; no organisation, nobody told; both messages in every language; their category); 16 mutations, all caught.
