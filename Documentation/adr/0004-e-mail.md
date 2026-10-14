# ADR 0004 — E-mail: an authenticated relay, invitations, password recovery and notifications

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in three steps: 1 (this record), 2 (sending, single-use links, notifications and their settings on the server; section 3.8), 3 (screens; section 3.9) |
| Backlog item | 3.1 — e-mail |
| Decided by | the owner of the branch, who asked for the recommended option on every point of section 4 while he was away |
| Portuguese | [ADR 0004 em português](../pt-BR/adr/0004-e-mail.md) |

## 1. Context

The portal cannot send a message today. Everything that would normally travel by e-mail goes through an
administrator by hand:

- a new user gets a **temporary password** that the administrator reads on the screen and passes on (a chat
  message, a phone call), and that the user must change at the first sign-in;
- a user who forgot his password asks an administrator, who makes another temporary password;
- nobody is told when his password or his e-mail address changed, nor when his account was locked by failed
  sign-ins — the usual signs that someone else is trying the account;
- a long import or a check of every link finishes while the user may have left the page.

Item 2.4 gave every user an optional, unique e-mail address (ADR 0002, decision 8), set by the administrators
and not used yet. Items 4.3 (monitoring and alerts) and 4.4 (weekly summary per tenant) will send messages too
and need a way to do it, a place for each user's choices and texts in both languages.

Constraints of the installations:

- Cloud providers block outgoing connections to port 25 (Azure does; the staging server runs there). Mail has to
  go through a **relay** that accepts authenticated submissions on port 587 (STARTTLS) or 465 (TLS): the
  organisation's own (Microsoft 365, Google Workspace, an Exchange or Postfix server) or a sending service
  (Amazon SES, SendGrid, Mailgun and others all offer such an SMTP interface).
- The portal runs in several replicas and processes, and its background jobs run in the `portal-worker` service
  (ADR 0001). A relay can be slow or unavailable for a while; a sign-in page must not wait for it.
- An installation without a relay must keep working exactly as today.

## 2. Decision

1. **SMTP submission to a relay the operator chooses**, with authentication, on port 587 with STARTTLS (the
   default) or 465 with TLS. The relay's certificate is always verified. A relay without encryption is accepted
   only without credentials (a test server on the installation's own network). No vendor's HTTP API.
2. **Settings in `.env`** (`PORTAL_MAIL_*`, section 6), like every other setting; the relay's password is a
   secret like the others (never shown, never in the journal). **Without `PORTAL_MAIL_HOST` mail is off** and
   the portal behaves exactly as before: temporary passwords, no recovery link, no notification. The installer
   asks for the relay as an optional step.
3. **Messages are jobs of the worker** (a third job type, `mail`, in the `jobs` collection of ADR 0001): the
   request that causes a message only queues it. The worker sends it, tries again after a temporary failure
   (after 1, 5, 15, 60 and 120 minutes) and gives up on a permanent refusal or after the last try, writing
   `mail-failed` in the journal. The text of a message is removed from its job once it is sent or has failed.
4. **Single-use links** for invitations and password recovery: 256 random bits, kept only as a SHA-256 hash in a
   new `tokens` collection that expires them (TTL index); valid for **72 hours** (invitation) or **60 minutes**
   (recovery); a new link replaces the previous one of the same kind; used once (taken atomically). **The token
   travels in the fragment of the link** (`…/portal/login#reset=…`), which browsers never send to a server, so
   it does not reach access logs, proxies or the `Referer` of a page; the sign-in page reads it and posts it.
5. **Invitations.** With mail on, a user created **with an e-mail address** gets an invitation instead of a
   temporary password (a box on the form, ticked by default, lets the administrator still choose the temporary
   password). The invited account has no password until the user chooses one through the link. *Reset password*
   sends a link to a user who has an address; without an address (or with mail off) it makes a temporary
   password, as today.
6. **Password recovery.** *Forgot your password?* on the sign-in page, shown only when mail is on. The user types
   his user name or e-mail address; **the answer is the same whether or not an account matched**, so the page
   does not reveal which names or addresses exist. Requests are limited per name and per address of the browser.
   Nothing is sent to an account without an address, disabled, or of a disabled organisation. Choosing a
   password through a link ends every open session of the account and removes its other links.
7. **A notification framework** (`portal/notify.py`): each message belongs to a **category**. *Security*
   messages are always sent — the password was changed, the e-mail address was changed (to the old and to the
   new address), the account was locked after repeated failed sign-ins (once per lock). *My background jobs*
   (an import or a link check I started has finished) is optional and **off by default**. Each user keeps his
   choices and **the language of his messages** (pt-BR or en-GB; taken from the page at each sign-in until he
   chooses one in *Options*). Items 4.3 and 4.4 add their own categories.
8. **Texts in both languages, in the code** (`portal/mailtexts.py`): a subject and a plain text per message and
   language, with an HTML alternative made from the same text; signed with the operator's name
   (`RESOLVER_ORG_NAME`); no GS1 branding. A test checks that both languages have the same messages with the
   same placeholders.
9. **Tests without a real relay.** The development tests run a small SMTP relay of their own (STARTTLS with a
   throwaway certificate, authentication, refusals on demand). For trying the whole flow on a staging
   installation before a real relay is configured, `docker-compose.yml` gains a **`mailpit` service in the
   `mail-test` profile** (not started unless asked), which accepts every message and shows it through its API on
   `127.0.0.1:8025`.
10. **Privacy by design.** The journal names the user, never his address. A message says only what the user
    needs; recovery messages do not say whether other accounts exist. The relay sees addresses and texts, which
    the operator accepts by choosing it.

## 3. Design

### 3.1 Sending (`portal/mail.py`)

`enabled()` is true when `PORTAL_MAIL_HOST` and `PORTAL_MAIL_FROM` are set and the settings are consistent
(a username without a password, or credentials with `PORTAL_MAIL_SECURITY=none`, switch mail off with an error
in the log). `send(message)` opens one connection per message:

| `PORTAL_MAIL_SECURITY` | Connection |
|---|---|
| `starttls` (default, port 587) | plain connection, `STARTTLS` required (a relay that does not offer it is refused), then `AUTH` |
| `tls` (port 465) | TLS from the first byte, then `AUTH` |
| `none` | no encryption, no authentication (a test relay such as Mailpit) |

The TLS context is the system's, plus `PORTAL_MAIL_CA_FILE` when given (a company relay signed by a private
authority). Errors are sorted into **temporary** (no connection, a timeout, a 4xx answer) and **permanent**
(5xx: refused sender, unknown recipient, authentication failed).

`python mail.py test <address>` (run in the `portal-service` container) sends a test message at once, without
the worker, and prints the relay's answer: the operator's check after configuring the relay.

### 3.2 The `mail` job

```
{"_id": "<token>", "type": "mail", "user": "<recipient's user name>", "state": "queued",
 "to": "maria@example.org", "subject": "…", "text": "…", "html": "…", "template": "password-reset",
 "tries": 0, "notBefore": <date>, "lastError": "…", "created": …, "expiresAt": …}
```

The message is composed when it is queued (the language and the link are known then). `jobs.claim()` takes a
queued job only when its `notBefore` has passed; `jobs.defer()` puts a job back in the queue with a later
`notBefore` (a temporary failure). Once sent, the job is finished and loses `text` and `html`; a failed job loses
them too and the journal gets `mail-failed` (template and the relay's answer, never the address). Mail jobs do not
appear in the browser: nobody waits for them.

### 3.3 Single-use links (`portal/tokens.py`)

```
{"_id": "<sha256 of the token>", "purpose": "invite" | "reset", "user": "maria",
 "created": <date>, "expiresAt": <date>}
```

- `issue(user, purpose)` removes the user's earlier links of that purpose and returns a new random token
  (`secrets.token_urlsafe(32)`); only its hash is stored.
- `peek(token)` (is it valid, for whom, for what) lets the page show the user name before he types a password.
- `consume(token)` takes the document atomically (`find_one_and_delete` on hash and date): a link works once.
- `purge(user)` removes every link of a user (password set, user removed).
- The link is `<PORTAL_ORIGIN>/portal/login#invite=<token>` or `#reset=<token>`.

### 3.4 Accounts

`users` documents gain:

- `invited`: the date of the invitation, while the account has no password of its own (the `hash` is empty, so
  no password can sign in); removed when the user chooses one.
- `language`: `pt-BR` or `en-GB`; `languageChosen`: true once the user chose it in *Options* (until then each
  sign-in takes the page's language).
- `notify`: the optional categories the user switched on (`{"jobs": true}`).

### 3.5 Flows

| Flow | What happens |
|---|---|
| Invitation | administrator creates the user with an address and *Send an invitation* ticked → account with `invited`, no password → `invite` link by e-mail → the user opens it, sees his user name, chooses a password → signed out of nothing (he had no session), sent to the sign-in page with a message → journal `invite-accepted` |
| Reset by an administrator | *Reset password* on a user with an address → every session of the user ends (the old password stops working at once) → `reset` link by e-mail → as above, journal `user-reset` (with `detail` "link") and later `password-reset` |
| Recovery by the user | *Forgot your password?* → user name or address → same answer for every input → when an account matches and may sign in, `reset` link by e-mail and journal `password-recovery` → as above |
| Password chosen through a link | `POST /portal/api/password/link` with the token and the new password (minimum length as today) → password set, `mustChange` and `invited` cleared, every session and every other link of the user ended → security message "your password was changed" |
| Address changed by an administrator | security message to the old address (it may no longer be the user's) and to the new one |
| Account locked | the fifth failed sign-in for a user name that exists sends one security message (one per lock) |
| Job finished | when the user switched *My background jobs* on: an import (counts) or a link check (problems found) finished |

The time a request takes does not depend on whether an account matched (the same delay as a failed sign-in).
Requests for recovery count in the sign-in throttle collection under their own keys: 3 per user name and 10 per
browser address in 15 minutes.

### 3.6 Screens

- **Sign-in page**: *Forgot your password?* (when mail is on) opens a small form; a link from a message opens
  *Choose your password* (user name shown, new password twice).
- **Users**: *Send an invitation by e-mail* on the new-user form (when mail is on and an address is typed); the
  state column says *Invited*; *Reset password* says before acting whether a link or a temporary password will
  follow.
- **Options**: a section *E-mail* with the user's address (set by the administrators), the language of the
  messages and the optional categories; security messages are listed as always sent.

### 3.7 API added or changed

| Call | Who | |
|---|---|---|
| `GET /portal/api/login/options` | anyone | `{"passwordRecovery": bool}` for the sign-in page |
| `POST /portal/api/password/forgot` | anyone | `{"login"}` → always `password.recoverySent` |
| `POST /portal/api/password/link/check` | anyone | `{"token"}` → `{"user", "purpose"}` or `password.linkInvalid` |
| `POST /portal/api/password/link` | anyone | `{"token", "newPassword"}` → `password.set` |
| `GET` / `PUT /portal/api/preferences` | signed in | language and optional categories |
| `POST /portal/api/users` | administrators | gains `invite` (bool); answers without a password when an invitation was sent |
| `POST /portal/api/users/<name>/reset` | administrators | sends a link when possible (`users.resetSent`), else a temporary password as today |
| `GET /portal/api/config` | signed in | gains `mail` (`{"enabled": bool}`) and the user's `email`, `language`, `notify` |
| `GET /portal/healthz` | anyone | gains `"mail": "off"` or `"on"` |

### 3.8 As implemented in step 2

As designed, with these details settled by the implementation:

- `mail.send()` opens one connection per message and names itself in `EHLO` with `FQDN`. An answer refusing
  the recipient after the message counts like any 4xx or 5xx answer.
- When a link was issued but its message could not be queued, the link is withdrawn (`app.send_link()`); for a
  new user the administrator then gets a temporary password, as without mail.
- An administrator's reset goes by link only for an enabled account with an address and never for the
  administrator's own account; a disabled account still gets a temporary password.
- `users.create()` without a password and without an address is refused (`users.emailRequired`).
- `mail-failed` is written in the recipient's audit trail (his tenant's, or the operator's); choosing the
  preferences writes `preferences`.
- The health check adds `"mail": "on" | "off"`.
- The installer asks for the relay after the first portal user: host (empty: no e-mail; `off` switches it
  off), `starttls` or `tls`, port, user name, password (hidden; Enter keeps the one in `.env`) and sender. A test
  relay with `none`, set by hand, is kept on a re-run. Writing the test of this step found an older defect of
  the installer — settings at the end of a line of its list of managed keys were written twice, the old value
  last — fixed in its own commit (`f3d127d`).
- The `mailpit` image is pinned (`axllent/mailpit:v1.31.5`). The development sandbox cannot reach Docker Hub,
  so it is first started on the staging server.
- Every protection is mutation-checked by `test_mail.py` (16 mutations, all caught): the recovery answer
  telling unknown accounts apart, or answering faster for them; a raw token stored; a link usable twice; a
  disabled account receiving; the message text kept after sending; `notBefore` ignored; an administrator's
  reset keeping the old password; other links surviving a password set by link; credentials sent without
  STARTTLS; a lock notice on every failure; the address in the journal; optional categories ignored; the old
  address not told; no recovery limit; a disabled account's link accepted.

### 3.9 As implemented in step 3

- The sign-in page (`login.html`, `login.js`) holds three forms: sign-in, recovery and the one a link opens. The
  token is taken from the fragment and removed from the address bar before the first request; a link pasted into
  an open sign-in page changes only the fragment and is caught by `hashchange`. A link opened while someone is
  signed in in the same browser reaches the portal page (the sign-in page redirects there, keeping the fragment):
  the page signs that session out and goes back.
- The users screen gains *Send an invitation by e-mail* (ticked by default), the state *Invited — waiting for the
  password* and *Send the invitation again*; the question before a reset says whether a link or a temporary
  password follows. Options gains the *E-mail* section. Everything new is shown only when `/config` says
  e-mail is on (`body[data-mail]`), so an installation without a relay looks as before.
- The owner was away: instead of mock-ups first, images of the finished screens are in both user guides
  (`password-recovery.png`, `choose-password.png`, `users-invite.png`, `options-email.png`) for his review.
- `test_mail_e2e.py` (37 checks) drives the screens in Chromium against the relay of the tests; removing the
  token from the address bar is mutation-checked.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Transport | SMTP submission to a relay, 587 STARTTLS or 465 TLS | a provider's HTTP API (one vendor, one more secret format); a mail server in a container (port 25 blocked, messages marked as spam) |
| When messages are sent | jobs of the worker, with retries | in the request (a slow relay blocks the page, a failure loses the message); a separate outbox collection (a second claim mechanism next to the jobs') |
| Links | random token, only its hash stored, in the fragment of the link | a signed token without storage (cannot be used once only nor revoked); the token in the query string (written to access logs, sent as `Referer`) |
| Validity | 72 hours for invitations, 60 minutes for recovery, settable | one value for both; a day for recovery (a longer window for a stolen mailbox) |
| New users | invitation by default when there is an address, temporary password still possible | invitation only (no way to help a user whose mailbox fails); temporary password only (item 3.1 would change nothing for new users) |
| Recovery | user name or e-mail, same answer for all | user name only (users forget it more than their address); an answer that says "no such account" (reveals who has an account) |
| Notifications | security always, background jobs optional (off) | every category optional (a user could silence the warning that someone changed his password); everything on (noise) |
| Language of messages | the user's, from the page until chosen | the installation's (a Portuguese user of an English installation); both languages in every message (long) |
| Texts | in the code, both languages, checked by a test | files an operator edits (texts drift from the code, two languages out of step) |
| Trying it on staging | Mailpit in a compose profile | only a real relay (cannot be tested before the organisation gives one); a fake relay in the portal (code that production carries for nothing) |
| Delivery | three steps: record, server, screens | one step; four (sending, links, notifications, screens) |

## 5. Consequences

- Without a relay nothing changes. With one, new users and forgotten passwords stop going through the
  administrators' hands, and users hear of changes to their account.
- The portal's messages are only as reliable as the relay: an organisation must give the installation a sender
  address its domain allows (SPF, DKIM) or the messages may land in spam. The operator's guide lists what to ask
  the organisation's mail administrators.
- An invitation or recovery link is a credential while it is valid: whoever reads the mailbox can choose the
  password. The validity is short, the link works once, and the user is told afterwards that his password
  changed.
- The worker now also sends mail: an installation that stops the `portal-worker` service (with
  `PORTAL_WORKER=external`) queues messages until it comes back (the health check already shows a missing
  worker).
- A disabled account or organisation gets no message; removing a user removes his links and his queued
  messages are sent no more (the job checks the account first).

## 6. Configuration added

| Variable | Default | |
|---|---|---|
| `PORTAL_MAIL_HOST` | empty (mail off) | the relay's host name |
| `PORTAL_MAIL_PORT` | 587 (465 with `tls`, 25 with `none`) | |
| `PORTAL_MAIL_SECURITY` | `starttls` | `starttls`, `tls` or `none` |
| `PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD` | empty | the relay's credentials (required with `starttls` or `tls` unless the relay accepts the server by address) |
| `PORTAL_MAIL_FROM` | empty | the sender, `Name <address>` or an address; required |
| `PORTAL_MAIL_REPLY_TO` | empty | optional answer address (a help desk) |
| `PORTAL_MAIL_CA_FILE` | empty | an extra certificate authority for the relay (PEM) |
| `PORTAL_MAIL_TIMEOUT` | 20 | seconds for each step of the conversation with the relay |
| `PORTAL_INVITE_HOURS` | 72 | validity of an invitation link |
| `PORTAL_RESET_MINUTES` | 60 | validity of a recovery link |

## 7. Delivery

1. This record (both languages).
2. On the server: `portal/mail.py`, `portal/mailtexts.py`, `portal/tokens.py`, `portal/notify.py`; the `mail`
   job and `notBefore` in `jobs.py`; the accounts' new fields in `users.py`; the calls of section 3.7 in
   `app.py`; the `tokens` collection; the installer's optional relay step; the `mailpit` service in the
   `mail-test` profile; a new development test program `test_mail.py` with its own SMTP relay.
3. Screens (images of the finished screens for review, as in item 2.4, since the owner is away): the sign-in
   page, the users screen and *Options*; the end-to-end tests; the user and developer guides.
