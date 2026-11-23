# ADR 0043 — Access logs without the client's address or the query string

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-I4 of the [threat model](../threat-model.md) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken. Not taken: turning every access log off (an operator loses the status and timing of each request); a truncated address (still personal data when joined with the time, and of no use against one client); keeping the full lines and only stating a retention (the privacy notice says the address is not kept) |

## 1. Context

The request log ([ADR 0006](0006-resolver-request-log.md)) was designed so that a scan leaves no personal data: never
the client's address, the User-Agent, the full referrer, the values of serial numbers or of data attributes. The
default privacy notice ([ADR 0017](0017-privacy-notice.md)) says so: "The address itself is not kept, nor the
browser's full identification".

Three other logs kept exactly that, for every request:

- **The installation's proxy** (`frontend_proxy_server/nginx.conf`), nginx's `main` format: the client's address
  (the real one since ADR 0030's `real_ip`), the whole request line with the path and the query string (serial
  numbers, data attribute values, the portal's query parameters), the referrer, the User-Agent and the
  `X-Forwarded-For` header. Its request limits' refusals (ADR 0031) wrote the address and the request line again to
  the error log.
- **gunicorn** in the resolver, the data entry API and the portal (`--access-logfile -`): the request line, the
  referrer and the User-Agent (the address there is the proxy's).
- **The host's nginx** (the sites `scripts/install.sh` and `custom-domains.sh` write): its default `combined` format,
  with the client's address, in `/var/log/nginx/access.log`.

The containers' output went to Docker's `json-file` driver, which keeps it, without a size limit, until the
container is removed.

## 2. Decision

1. **The proxy's access log is minimal by default.** `PROXY_ACCESS_LOG` (`.env`; `api-access.sh` writes
   `/etc/nginx/access-log.conf` when the container starts) chooses it:
   - `minimal` (the default, and the file baked into the image): the time, the method, the **area** of the path, the
     status, the size and the time taken. The area is the path's first segment when it is a word (lower-case letters
     and hyphens, with an optional extension: `/portal`, `/favicon.ico`), `.well-known` or an application identifier
     of 2 to 4 digits (`/01`, `/8004`); anything else — a compressed link, an encoded name — is `/...`; `/` alone is
     `/`. It is read from the path as the client sent it (`$request_uri`, up to the first `/` or `?`), never past it.
     Nothing else: no address, no User-Agent, no referrer, no query string, no identifier's value.
   - `full`: the former line, the time taken added. Personal data: for a diagnosis, for as long as it lasts; the
     privacy notice must then say so.
   - `off`: no line at all.
   - another value: `minimal`, with a warning when the proxy starts.

   In `minimal` and `off`, the request limits' refusals are written at `info` (below the error log's `warn`), so the
   error log does not name the client either; the access log shows them as status 429. In `full` they are written at
   `warn`, as before.
2. **No access log in gunicorn.** The three images start gunicorn without `--access-logfile`: the proxy writes one line
   for each request they receive. Errors are still written.
3. **No access log in the host's sites.** The installer's templates (`nginx-site-http.conf`, used by
   `custom-domains.sh` too, and `nginx-site-https.conf`) say `access_log off;` in each server. When the installer keeps
   a Let's Encrypt site with a server that has no `access_log off;`, it warns, with a `sed` command that adds one to
   each server.
4. **A bounded output.** Every service of `docker-compose.yml` uses the `json-file` driver with `max-size`
   `LOG_MAX_SIZE` (10m by default) and `max-file` `LOG_MAX_FILES` (5): at most 50 MB of output per container, the
   oldest dropped first.

## 3. Consequences

- The privacy notice's statement holds for the logs too, in the default configuration: no log of an installation
  keeps a scanner's address, User-Agent or the values of a request.
- An operator still sees each request's status and time per area (errors, 429, slow answers), and turns `full` on
  (`PROXY_ACCESS_LOG=full`, `docker compose up -d frontend-proxy-service`) to follow one client; the request log and
  the portal's audit trail keep what each is for.
- An integrator or tool that parsed the proxy's former lines reads the new format, or sets `full`.
- Residuals: nginx's error lines (an upstream that does not answer, a malformed request) still name the client and
  the request, and nginx has no setting to leave them out; sites written by Certbot or by hand before this change
  keep their access log until the operator applies the command the installer prints (the organisations' domain sites
  too, until `custom-domains.sh` writes them again); the output is bounded by size, not by age, so a quiet
  installation keeps lines longer; the portal's own warnings and the audit trail keep the address where ADR 0006 and
  the threat model already say so (sign-in, the audit trail).
