# ADR 0021 — The official data entry API closed to the internet by default

| | |
|---|---|
| Status | **Accepted** (14 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)) |
| Decided by | the owner of the branch, who chose the recommended option: closed at the proxy by default, opened only to listed addresses, organisations' systems on the tenant API |

## 1. Context

The proxy published the official data entry API (`/api`, with its Swagger UI at `/api/docs` and `/swaggerui`) to
everyone, as the official project does. Its only control is `SESSION_TOKEN`: one static value shared by the portal and
any integration, with no owner, scope, expiry or limit, that creates, changes and deletes the records of every
organisation outside the portal's rules — prefixes, the target address rule, the journal and the notifications. The
operator's guide advised restricting `/api` at the edge once the portal was live, but nothing did it, and the home page
linked to its documentation.

Since then the portal has gained everything an integration needs without that token: the tenant API
(`/portal/api/v1`, [ADR 0005](0005-tenant-api.md)), with keys per organisation, scopes, expiry, a rate limit and the
journal. No system that uses `/api` from outside the server was named by the owner. For a resolver meant for the codes
of medicines and medical devices ([ADR 0020](0020-security-assessment.md)), the credential that can change every
leaflet and recall notice at once should not be one guess or one leak away from the internet.

## 2. Decision

1. **`/api` and `/swaggerui` are closed at the front-end proxy by default.** nginx answers 403 to every address that
   `DATA_ENTRY_API_ALLOW` does not list, before the request reaches the data entry service. The portal and its worker
   are not affected: they call `data-entry-service:3000` inside Docker's network, not through the proxy.
2. **`DATA_ENTRY_API_ALLOW`** in `.env` (read by Compose) opens both to addresses or networks (CIDR), separated by
   spaces or commas; `all` opens them to everyone, as before — a deliberate choice that the installer's summary shows.
3. **The client's address.** Behind the host's nginx every request reaches the proxy from the address of the container's
   gateway, so the allowlist must look at the client the host's nginx names. nginx's `geo` module does it (`proxy`):
   the last address of `X-Forwarded-For` — the one the trusted proxy appended — counts, and only when the request comes
   from a trusted proxy. The gateway is trusted when `PROXY_BIND_ADDRESS` is a loopback address (only processes on the
   server reach the port then); with any other bind address it is not, because clients may arrive from it (Docker's
   own proxy for IPv6, for example). `PROXY_TRUSTED_PROXIES` lists other proxies in front (an external load balancer,
   `TLS_MODE=external`).
4. **The file is written when the container starts** (`frontend_proxy_server/api-access.sh`, run by the nginx image's
   entrypoint from `/docker-entrypoint.d`). An entry that is not an address or a network is left out with a warning in
   the container's log and opens nothing; nginx still starts, so a typing error in the list never takes resolution
   down. The image carries an empty file, so the API stays closed if the script never runs.
5. **The home page no longer links to the data entry API's documentation** (its menu entry and its card, in the twelve
   languages): it is closed for the public. Integrators use the tenant API, described by
   `/portal/api/v1/openapi.json` and the [API reference](../api-reference.md).
6. **Deviation from the official project**, recorded in the changelog: there, `/api` is public.
7. **The example secrets of `.env.example` are refused outside development.** `.env.example` is public and holds
   working values so that a development machine runs without a `.env`. When `FQDN` names a real host (not empty,
   `localhost`, `127.0.0.1`, `::1` or a name under `.localhost`), the data entry API refuses to start with the example
   `SESSION_TOKEN`, and the portal with that token or its example `PORTAL_DB_PASSWORD` (when it builds its connection
   from it); the message names the setting and `scripts/rotate-secrets.sh`, never a value. The installer replaces both
   whenever it finds them, so no installation it made is stopped. MongoDB's example root password in `MONGO_URI` is
   only **warned about**, by the data entry API and the resolver: the installer keeps it for a database created with
   it (it cannot change it without the database), and refusing it would stop an upgraded installation and every scan
   with it; `scripts/rotate-secrets.sh mongo` changes it. One module, `example_secrets.py`, is copied into each of the
   three images (each holds only its own folder); a check keeps the copies identical.

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Default | closed, opened by a list | left open and documented (the token stays one leak away from every record); removed from the proxy entirely (no way left for an integration that cannot move at once) |
| Where | the front-end proxy, in every installation | the host's nginx only (absent with `TLS_MODE=external`, and edited by hand) |
| Client address | `geo` with trusted proxies, last address of `X-Forwarded-For` | `real_ip` (the same rule, but a module nginx builds may lack; `geo` is always built); the connection's address only (the gateway's, for everyone behind the host's nginx) |
| A wrong entry | left out with a warning, nginx starts | the proxy refuses to start (an allowlist typo would stop every scan) |
| Home page | links removed | kept (a 403 for the public) |
| Example secrets | refused (token, the portal's password), warned about (MongoDB's root password) | refused all (an installation upgraded from the official project with its database's example password would stop); a warning only (a public token keeps working) |

## 4. Consequences

- An integration that calls `/api` from outside the server stops working after the upgrade until its address is listed
  in `DATA_ENTRY_API_ALLOW` or it moves to the tenant API. The changelog says so.
- The token keeps its other weaknesses (one value, no owner, no journal); closing the door narrows who can try it, and
  its public example value no longer works outside development. The journal of the data entry service and its
  removal in favour of the tenant API remain steps of item 10.1.
- An installation started by hand with `.env.example`'s token and a real `FQDN` stops at the upgrade, with a message
  that says which setting to change; MongoDB's example password stays possible until rotated (item 7.2).
- The fix of the client's address for the portal's own limits ([threat model](../threat-model.md), section 9) is a
  separate step; this record trusts the same proxies the portal will.

## 5. Delivery

`frontend_proxy_server/api-access.sh`, `nginx.conf` (the `geo` block and a check in `/api` and `/swaggerui`), the
proxy's `Dockerfile`, the three settings passed by `docker-compose.yml` (no secret reaches the proxy), `.env.example`,
the installer's summary, the home page; checks in `dev-tests/home/test_home.py` against the real configuration in
nginx 1.30 (closed by default, an allowed address and network, a trusted proxy, the gateway behind a loopback bind
address and not otherwise, a forged first address, wrong entries, `all`). `example_secrets.py` in `portal/`,
`web_server/src/` and `data_entry_server/src/`, called as each service starts; checks in
`dev-tests/install/test_deploy.py` that start each service with and without the example values, on a real host name
and on `localhost`.
