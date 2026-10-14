# ADR 0012 — Single sign-on per organisation (OpenID Connect) and per-role limits on exports

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog item | 7.1 — single sign-on for the portal, per tenant; per-role limits on exports |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

Organisations with many users want them to sign in to the portal with the account they already have — Microsoft
Entra ID, Google Workspace, Okta, Keycloak — so that leaving the company also ends access to the portal, and their own
rules (two factors, password policy) apply. Each organisation has its own identity provider; the operator may have
one too. The portal's accounts, roles, prefixes and organisations (ADR 0002) stay as they are: single sign-on changes
how a person proves who they are, not what they may do.

Operators also asked to limit what each role may take away: a reader exporting every record or every request may not
be what an organisation wants.

## 2. Decision

1. **OpenID Connect**, the authorization code flow with PKCE (S256), `state` and `nonce`, and a client secret sent in
   the token request (`client_secret_post`). Every provider above speaks it; nothing else (SAML, LDAP) is offered.
2. **One configuration per organisation** (and one for the operator), set on a new *Single sign-on* screen by the
   organisation's administrators — a server administrator sees and may change every one, so that an organisation
   locked out by its provider can be let in again: the provider's **issuer** (its discovery document at
   `<issuer>/.well-known/openid-configuration`), the **client ID** and **secret** the provider gave (the secret is
   write-only: never shown again, kept in the portal's database like its other credentials), the **e-mail domains**
   whose people it signs in (each domain belongs to one configuration in the installation), on or off, and
   **password sign-in off** for the organisation's users once it works. The screen shows the address to register at
   the provider (`<PORTAL_ORIGIN>/portal/sso/callback`) and a *Test* that reads the discovery document.
3. **Who signs in**: the sign-in page's *Sign in with your organisation's account* asks for the e-mail address; its
   domain chooses the configuration; the provider's answer must carry that `email` (not `email_verified: false`),
   and an account **with that e-mail must already exist** in that organisation (or the operator), not disabled.
   Nobody is created by signing in: administrators still create or invite users and choose their role and prefixes.
4. **Password sign-in off** applies to the organisation's users, never to server administrators (who must be able to
   reach the portal when a provider fails); their passwords stay and work again when the option is switched off.
   Password recovery says nothing different for them (no enumeration) and sends nothing.
5. **The session** is the portal's usual one (idle and total limits, the password fingerprint). The journal records
   `login` with `sso` and the provider's host, and `login-failed` with the reason (no account, disabled, a token that
   does not verify…).
6. **The provider's addresses** must be `https` on public addresses (the link checker's guard against requests to the
   internal network); `PORTAL_SSO_ALLOW_INSECURE=1` lifts both, for tests and for a provider on the operator's own
   network. ID tokens are verified with the provider's keys (JWKS, RS256/ES256/PS256), issuer, audience, expiry and
   nonce; discovery documents and keys are kept an hour, the keys read again once for an unknown key ID.
7. **Exports per role** (`PORTAL_EXPORT_LIMITS`, e.g. `reader:0,editor:20000`): the most rows one export of a role may
   hold — records (spreadsheet), requests (CSV) — and 0 for no export at all (the overview's export, figures rather
   than rows, is refused only then). Roles not named and administrators have no limit. A refusal says the numbers and
   is in the journal (`export-refused`); the page hides the export buttons of a role that may not export.

## 3. Design

- `portal/sso.py`: the configurations (collection `sso`, `_id` the tenant or `operator`), their rules, the discovery
  and JWKS caches, `start()` (the provider's authorization address, the flow's values kept in the signed session
  cookie, which is `SameSite=Lax` and so comes back with the provider's redirect) and `finish()` (code for tokens, ID
  token verified, the account found). PyJWT with its crypto extra verifies the tokens.
- `app.py`: `POST /portal/api/sso/start` `{email}` → `{url}`; `GET /portal/sso/callback` → the portal or the sign-in
  page with `?sso=<message code>`; `GET/PUT/DELETE /portal/api/sso[/<scope>]`, `POST /portal/api/sso/<scope>/test`;
  password sign-in refused with `auth.ssoRequired` (after the password is checked); `login/options` says whether any
  configuration is on.
- `login.html`/`login.js`: the second form; `index.html`/`app.js`: the *Single sign-on* view.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Protocol | OpenID Connect, code flow with PKCE | SAML (heavier, XML signatures); a proxy in front (`oauth2-proxy`: one provider for the whole installation, not one per organisation) |
| Accounts | must exist, matched by e-mail within the organisation | created at the first sign-in with a default role (anyone at the domain becomes a user; roles and prefixes still need an administrator) |
| Choosing the provider | the e-mail's domain | a button per organisation on the sign-in page (lists the installation's customers to anyone) |
| Client secret | in the portal's database, write-only on the screen | encrypted with `PORTAL_SECRET_KEY` (rotating that key would silently break every configuration) |
| Password sign-in when SSO is on | allowed until the organisation switches it off; never off for server administrators | off at once (a wrong configuration locks everybody out) |
| Export limits | per role, per installation (`.env`) | per organisation on a screen (more to build; no request for it yet) |

## 5. Consequences

- A new dependency: `pyjwt[crypto]` (PyJWT and `cryptography`).
- Organisations register the portal at their provider (the callback address) and give its administrators the issuer,
  client ID and secret.
- Users of an organisation with password sign-in off cannot sign in when its provider is down: a server administrator
  switches the option off.

## 6. Configuration added

| Variable | Default | |
|---|---|---|
| `PORTAL_SSO_ALLOW_INSECURE` | empty (off) | `1`: providers on `http` or on private addresses accepted (tests; a provider on the operator's network) |
| `PORTAL_EXPORT_LIMITS` | empty (no limits) | `role:rows` pairs, e.g. `reader:0,editor:20000` |

## 7. Delivery

This record; `portal/sso.py`, the routes, the sign-in form and the *Single sign-on* screen; export limits; tests with
a stand-in OpenID provider (`test_sso.py`, `test_sso_e2e.py`), `test_exports.py`; the documentation.
