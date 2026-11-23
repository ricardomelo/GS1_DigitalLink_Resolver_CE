# ADR 0036 — User names and e-mail addresses across organisations

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-T3, gap G-30 of the [threat model](../threat-model.md); finding F-019 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): e-mail addresses unique per organisation instead of per installation; user names kept as the installation's sign-in names, with the refusals an organisation's administrator meets counted (5 in 15 minutes) and those naming another organisation's account journalled in the operator's trail. Sign-in names qualified by organisation were not taken |
| Amends | [ADR 0002](0002-tenants.md) (one user collection, unique names and addresses) and [ADR 0004](0004-e-mail.md) decision 6 (recovery by address finds one account) |

## 1. Context

Every account of the installation is a document of the `users` collection keyed by its user name, the name typed at
sign-in. Its e-mail address was unique in the installation. An organisation's administrator who creates a user, or
changes a user's address, could therefore learn from the refusal that a name (`users.exists`) or an address
(`users.emailExists`) belonged to someone in another organisation, one guess at a time and without limit. Both are
personal data (asset A10 of the threat model); the address also says that a person works with the installation's
other customers.

The screens themselves were already scoped: an organisation's administrator lists only its own users, and acting on
another organisation's user answers "unknown user" (`managed_account()`).

## 2. Decision

### 2.1 Addresses unique per organisation

- `users._check_email()` refuses an address only when another account **of the same organisation** has it (the
  operator's users are one scope, `tenant` absent). The same address may be given once in each organisation: a
  refusal now tells an administrator only about the organisation's own users, which the administrator can list anyway.
- Password recovery by address (`users.find_logins()`, which replaces `find_login()`) finds every account with the
  address; `forgot_password()` sends a link to each that may sign in, all to the same mailbox (the address's owner
  controls them all). The answer and its time stay the same whether or not anything matched.
- Single sign-on (`sso.finish()`) looks for the account with the token's address **in the configuration's
  organisation**, so another organisation's account with the same address neither blocks nor takes the sign-in.
- No migration: addresses stored before are already unique in the installation.

### 2.2 User names: counted and journalled refusals

User names stay unique in the installation: they are what people type at sign-in, and qualifying them by organisation
would change every sign-in, every link and every integration's account. Instead (`app.name_refusals_counted()`):

- each `users.exists` refusal an **organisation's administrator** meets when creating a user is counted under
  `name-taken:<administrator>` in `login_failures` (the sign-in throttle's collection, kept 15 minutes);
- with 5 refusals in the window (`NAME_REFUSALS`) no user is created, whatever the name, until the oldest leaves it:
  `users.nameLimit` (429, the wait in minutes). Names can no longer be tried in bulk, and because every create is
  refused once the limit is reached, the limit tells nothing either;
- a refusal for a name held **outside** the administrator's organisation is journalled as `user-create-refused` in the
  **operator's** audit trail (who tried, the name, from which organisation), so that a server administrator sees a
  probe; refusals for the organisation's own names are not journalled;
- server administrators, who see every user, are neither counted nor journalled.

### 2.3 Single sign-on's "no provider"

`/portal/api/sso/start` still answers `sso.noProvider` for an e-mail domain without single sign-on: the portal must
either send the browser to a provider or not. It tells whether a **domain** uses single sign-on here, not whether a
person has an account, and it is limited per address at the proxy ([ADR 0031](0031-request-limits.md)).

### 2.4 Alternatives not taken

- *Sign-in names qualified by organisation* (`name@organisation`): removes the name oracle entirely, but changes every
  account's sign-in, the invitation and recovery links and API integrations; out of proportion for a finding of low
  severity, and still possible later.
- *A neutral refusal text only*: any refusal of a taken name tells the same thing, whatever its words.
- *Unique addresses kept, refusal hidden*: an address could then not be saved without telling the administrator why.

## 3. Consequences

- Finding F-019 fixed for addresses; for user names the oracle remains, limited to 5 guesses per administrator every
  15 minutes and visible to the operator.
- One person may now have accounts in several organisations with one address (a consultant, a shared mailbox), which
  previously needed an address per account.
- Residuals: a name can still be tested slowly (about 480 a day per administrator, each one journalled when it is
  another organisation's); `sso.noProvider` tells which e-mail domains use single sign-on; the limit is a constant,
  not a setting; the server administrator creating a tenant's first administrator is not counted (it sees every user).
- Tests: `test_tenants.py` (addresses per organisation, the operator's scope, recovery's accounts, the limit, the
  journal, the window, server administrators), `test_mail.py` (a recovery link to each account of an address),
  `test_sso.py` (the configuration's organisation's account signs in).
