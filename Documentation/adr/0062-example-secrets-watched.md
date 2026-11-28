# ADR 0062 — Example secrets watched: the first user never created with one, an alert while the root password is one

| | |
|---|---|
| Status | **Accepted** (28 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-I1 of the [threat model](../threat-model.md); the third residual of finding F-012 ([ADR 0030](0030-least-privilege-services.md)); follows [ADR 0021](0021-data-entry-api-closed.md) §2.7 (example secrets refused outside development) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — the first portal user is not created with the example `PORTAL_ADMIN_PASSWORD` outside development, and the portal's monitoring alerts the server administrators while MongoDB's root password, or the first user's password, is still the example. Not taken: refusing to start with the example root password (an installation upgraded from a database created with it would stop, and the installer cannot change it without the database: ADR 0021 §2.7); a check of every user's password against known examples (only the first user's was ever given in a public file) |
| Amends | [ADR 0030](0030-least-privilege-services.md) (its residual *MongoDB's example root password and PORTAL_ADMIN_PASSWORD's example only warned about / applied once*) |

## 1. Context

`.env.example` is public and holds working credentials, so that `docker compose up -d` runs on a development machine
without a `.env`. Since ADR 0021 and ADR 0030 every service refuses the example secrets it uses while `FQDN` names a
real host, except two: MongoDB's root password, of which `portal-db-init` only printed a warning in its log, and
`PORTAL_ADMIN_PASSWORD` (`change-me-please`), with which the portal created its first user when the store was empty.
A warning in a one-shot service's log is read by nobody, and a first user with a public password is an open door.

## 2. Decision

1. **The first user.** `app._bootstrap_admin()` does not create the first user from `PORTAL_ADMIN_PASSWORD` when it is
   the example and `FQDN` is not a development name; it logs a warning saying to set a password of the operator's own.
   `example_secrets.EXAMPLE_VALUES` gains `PORTAL_ADMIN_PASSWORD` (the three copies stay identical). The installer
   already writes a generated password.
2. **What `portal-db-init` found.** At every start it records in the portal's settings
   `security.examples = {names, at}`: the settings it alone sees that hold the example (today `MONGO_URI`'s root
   password), none in development. Never a value.
3. **An alert.** `monitor.check_secrets()` reads that setting and, once an hour, checks the first user
   (`PORTAL_ADMIN_USERNAME`) against the example password by its hash (`users.verify()`): an **alert** while any name
   is found, **ok** otherwise or in development, **unknown** before `portal-db-init` of this version has run. The
   messages `alert-secrets` and `alert-secrets-ok` (category *alerts*, twelve languages) name the settings and how to
   change them (`scripts/rotate-secrets.sh mongo`; the user's own password in *Options*), reminded every
   `SECRETS_REMIND_DAYS` (7) days. The Overview's *Operation* shows the check (*Example passwords*), and *Alerts* lists
   it.

## 3. Consequences

- A new installation never has a first user with a public password; a manual start that forgets
  `PORTAL_ADMIN_PASSWORD` has no user until one is set (`create_user.py` also creates one).
- An installation that still uses MongoDB's example root password, or whose first user never changed the example,
  is told by e-mail and on the Overview until it changes them.
- The monitoring verifies one password hash an hour.

## 4. Checks

`test_portal_config` (the example refused on a real host, accepted in development), `test_monitor` (development ok;
unknown before a record; MongoDB's example recorded: an alert and a message naming the setting, never a password;
once an hour; the first user's example password; resolved with a message; the check listed; the screen's texts) and
`test_least_privilege` (`portal-db-init` records the names only, clears them, at every start). 6 mutations, all caught.
