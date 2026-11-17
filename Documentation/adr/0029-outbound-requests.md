# ADR 0029 — Requests to addresses users choose: resolved once, connected to the address checked; limits on the link checker

| | |
|---|---|
| Status | **Accepted** (17 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-S1 and T-S2 and control G-17 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): connect to the address checked, HTTPS only for the link checker, one link check per organisation and a limit per host |

## 1. Context

The portal sends HTTP requests to addresses its users choose: the **link checker** (the targets of a record, of an
import preview, or of every record of an organisation — up to 5 000 addresses in one job), **single sign-on**
(the provider's discovery document, its keys and the token exchange, at addresses an organisation's administrator
types) and the **check of a QR code domain** (a request through the domain an organisation adds).

Each of them refused a host whose addresses were not all global (private, loopback, link-local and so on), so that
the portal could not be used to reach the server's own network (the Docker network, the cloud metadata service).
But the check resolved the name, and the HTTP library then resolved it **again** to connect. A name whose DNS answer
changes between the two (DNS rebinding: a public address with a very short life, then `127.0.0.1` or a container's
address) passed the check and was then contacted at the internal address, and the link checker reports the status
and the final address back. The single sign-on check also accepted a name that did not resolve at the time it was
saved.

Two smaller points: the link checker contacted plain `http://` addresses (the portal refuses them as targets, but
records written through the official API may hold them), and any editor could make the server send thousands of
requests to third parties at once — several checks of every record in parallel, eight requests at a time, all to one
host if the records point there.

## 2. Decision

### 2.1 One function for every request to an address a user chose

`portal/outbound.py`, `request(method, url, allow_private=False, **kwargs)`:

1. The address must be `http` or `https`, with a host, a valid port and **no user information** (`BadAddress`).
2. The name is **resolved once**. Every address it resolves to must be global: `ipaddress`'s `is_global`, and for
   an IPv6 address that carries an IPv4 one (IPv4-mapped `::ffff:…`, 6to4 `2002:…`, the NAT64 prefix
   `64:ff9b::/96`) the IPv4 address must be global too. One address that is not is enough to refuse
   (`PrivateAddress`); a name without an address is `Unresolvable`.
3. The connection is made to **one of the addresses checked**, never to the name resolved again: a `requests`
   adapter replaces the host of the connection pool by the address and keeps the **name for TLS** — the name sent in
   SNI and the name the certificate is checked against — and the `Host` header is the name (with its port). A site
   behind a shared address answers as usual and a certificate is verified exactly as before.
4. When an address does not connect (an IPv6 address without a route, for instance), the next checked one is tried,
   **three at most**.
5. **Redirects are never followed** there; a caller that follows them calls `request()` again for each hop.
6. **No proxy from the environment** is used: a proxy would resolve the name itself.

`allow_private` lifts the check of step 2 (not the connection to the address resolved): the link checker's
development setting (`PORTAL_LINKCHECK_ALLOW_PRIVATE=1`) and single sign-on's (`PORTAL_SSO_ALLOW_INSECURE`).

The link checker (`linkcheck._request()`), single sign-on (`sso._send()`: discovery, keys, token exchange) and the
domain check (`domains.probe()`) use it. `outbound.public_host()` replaces `linkcheck._public_host()` for the check
made when a provider's address is saved.

### 2.2 The link checker contacts HTTPS addresses only

An `http://` address is reported as **`linkcheck.insecureAddress`** (*the address does not use HTTPS and was not
checked*) without a request, at the first address and at every redirect hop (a hop from HTTPS to HTTP was already
reported as `linkcheck.insecureRedirect`). The development setting lifts this too (the tests' server is plain HTTP).

### 2.3 Limits on the link checker

- **One link check queued or running per organisation** (`jobs.active()`): a second one, by any user of the same
  organisation (or the operator's scope), is refused with **`linkcheck.busy`** (422) — *another link check of your
  organisation is already under way; wait for it to finish or stop it*. The check of one record's few links
  (`POST /links/check`) is not a job and is not limited this way.
- **At most two requests to one host at once** (`linkcheck.PER_HOST`), whatever the size of the job; the addresses
  are taken one host after another, so that one host's queue does not hold up the others.
- Results are taken as they finish, and a check that stops (its user's request, the worker stopping) leaves the
  addresses not yet started unrequested.

The existing limits stay: 5 000 addresses per job, editors only, each address's result cached for ten minutes.

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Rebinding | resolve once and connect to the address checked, with the name kept for TLS | a second check after connecting (the socket's peer address: the request has already been sent); a global replacement of `socket.getaddrinfo` (changes every connection of the process, the database's included); an egress proxy that enforces the rule (an extra service for every installation) |
| How to connect to the address | a `requests` adapter whose pool connects to the address, with `server_hostname`/`assert_hostname` the name | the address in the URL and the name in `Host` (breaks SNI and the certificate's check for HTTPS) |
| Plain HTTP in the link checker | reported, not contacted | contacted as before (an unencrypted request for a target the portal itself refuses) |
| Limits | one check per organisation, two requests per host at once | a daily budget of addresses per organisation (a new setting, for no named need); a global queue (one organisation's check would delay every other's) |
| Proxies | not used | honoured (a proxy resolves the name, so the address could not be checked) |

## 4. Consequences

- A name whose answer changes cannot lead the link checker, single sign-on or the domain check into the server's own
  network: the address checked is the address contacted.
- Records whose targets start with `http://` (written through the official API) show a problem in the link check
  instead of being requested.
- An organisation runs one link check at a time; a second user sees `linkcheck.busy` until the first one finishes or
  is stopped. A sudden check of every record cannot flood one site with more than two requests at once.
- An installation that reaches the Internet only through a proxy (`HTTPS_PROXY`) can no longer check links, discover
  a provider or check a domain from the portal; none is configured by the installer or the composition, and such an
  installation would need an egress rule for the portal instead.
- The monitoring probe (`monitor.py`) and the e-mail relay connect by name as before: their addresses are the
  operator's own settings, not a user's.

## 5. Delivery

In one step (17 November 2026): `portal/outbound.py` (new); `linkcheck.py` (`_request()`, `_check()`, `check_many()`,
`PER_HOST`), `sso.py` (`_send()`, `check_url()`), `domains.py` (`probe()`), `jobs.active()`, `app.py`
(`start_link_job()`); two texts in `i18n.js` and `locales/`. Checks in `dev-tests/portal/test_outbound.py` (new),
`dev-tests/portal/test_linkcheck.py` and `dev-tests/portal/test_jobs.py`.
