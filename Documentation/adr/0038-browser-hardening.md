# ADR 0038 — The browser's rules: a Content-Security-Policy everywhere, HTTPS only, one origin kept

| | |
|---|---|
| Status | **Accepted** (21 November 2026); §2.5 amended by [ADR 0057](0057-portal-own-host-name.md) (27 November 2026): the portal on a host name of its own when the operator sets one |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-B1, T-B3, T-R5 and T-I6, gap G-16 of the [threat model](../threat-model.md); finding F-021 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): a policy for every answer of the portal, the resolver and the data entry API; Strict-Transport-Security from the installation's proxy; the single origin kept. The portal on a host name of its own, a route for violation reports and HSTS for the names under the installation's were not taken |

## 1. Context

The home page has had a strict Content-Security-Policy since release 1.1.0, set by the proxy. Nothing else had one:

- **the portal** sent `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` and `no-store`, but no policy:
  an injection flaw in any of its screens would run with the signed-in user's session;
- **the resolver's pages** (a linkset or a choice in a browser, the error pages, the item's page of ADR 0011) sent no
  header at all: no policy, nothing against framing, MIME type guessed. They show values written by organisations
  (titles, descriptions, the brand's name);
- **the Swagger UIs** of the data entry API (`/api/docs`, closed by default since ADR 0021) and of the web server (not
  reachable through the proxy) are pages of a third-party library;
- **no HSTS**: the host's proxy redirects HTTP to HTTPS, but a browser that types the name, or follows an `http://`
  link, makes its first request in clear every time;
- **one origin for everything**: the portal, the resolver's pages and the Swagger UI share the installation's name, so
  a script running in any of them may call the portal's API with the user's cookie.

The assessment found no injection flaw: this is the missing second line.

## 2. Decision

### 2.1 The portal

Every answer (`app.security_headers()`) carries:

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;
  font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; object-src 'none';
  base-uri 'none'; form-action 'self'; frame-ancestors 'none'
Cross-Origin-Opener-Policy: same-origin
```

with the headers it already had. The portal's pages hold no inline script, style element, style attribute or event
handler attribute, and its scripts write no such attribute into markup and evaluate no text (checked by
`test_appearance.py` on the files themselves): they change styles through the DOM (`element.style`), which a policy
does not govern. `data:` is the preview of a logo chosen for upload, `blob:` the label's QR code; fonts come from Google
Fonts, as on the home page. `Cross-Origin-Opener-Policy` gives the portal's window a browsing context group of its own:
a page that opened it, or that it opens, cannot reach it.

### 2.2 The resolver's pages

`web_pages._page()` draws a nonce for each answer (`secrets.token_urlsafe(18)`, 24 characters) and writes it into the
page's own `<style>` and `<script>` elements; the web server's `add_headers()` sends:

```
default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>' https://fonts.googleapis.com;
  font-src https://fonts.gstatic.com; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

- Only the templates write those elements: every value is escaped, so `<style>` or `<script>` typed into a record or
  into the installation's title reaches the page as text and gets no nonce. The JSON-LD block
  (`<script type="application/ld+json">`) is data the browser does not run and needs none.
- **The item's page loads nothing from other sites** (ADR 0011): its policy names no font site at all.
- `img-src 'self' data:`: the installation's logo and icon are data URIs, a brand's logo is `/_brand/…` on the
  resolver.
- **Every other answer** of the resolver (redirects, JSON, linksets, the description file, images) carries
  `default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`: a document opened from one of them
  may load and run nothing.
- All answers carry `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin` (what
  browsers do by default, now stated): the address of a scanned item, with its serial number, never goes to the site a
  link leads to, only the resolver's origin.

### 2.3 The Swagger UIs

flask-restx writes the Swagger UI's start-up script and a style element into the page, with the address of the
description in it (the host of the request), so they can carry neither a fixed hash nor a nonce. The page
(`api.doc`) of the data entry API, and of the web server, gets:

```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

It loads and calls nothing outside the origin, and nothing frames it. Every other answer of the data entry API gets the
policy that allows nothing, and `nosniff`. The Swagger UI the library ships (5.x) ignores configuration in the address
(`queryConfigEnabled` off).

### 2.4 HTTPS only: Strict-Transport-Security

The installation's proxy (`frontend_proxy_server/nginx.conf`) adds `Strict-Transport-Security: max-age=31536000` to
every answer to a request that reached the host's proxy over HTTPS, which says so in `X-Forwarded-Proto` (the
installer's templates and the server blocks Certbot writes, for the installation's name and the organisations'
domains alike). Over plain HTTP, no header (nginx sends none with an empty value; browsers ignore one received over
HTTP anyway, so a client writing `X-Forwarded-Proto` itself changes nothing). The locations with `add_header` of their
own (the home page, its files, the two 429 answers) repeat it, since nginx does not inherit the server's then.

One year, without `includeSubDomains` (other names under the installation's are not ours to decide) and without
`preload` (a list that is slow to leave): an operator who wants either adds it to the host's proxy.

### 2.5 One origin, kept

> Amended by [ADR 0057](0057-portal-own-host-name.md): one origin stays the default; an operator who sets
> `PORTAL_ORIGIN` to a name of its own gets the portal on that name only, and the costs below fall only on them.

The portal stays at `/portal/` on the installation's name. A name of its own (`portal.<name>`) would isolate it from
the resolver's pages and the Swagger UI, but needs a second name and certificate for every installation, changes the
address of every bookmark, of the single sign-on callbacks registered with the providers and of the tenant API, and
gives the organisations' domains (ADR 0009, F-027) a question of their own. What makes one origin acceptable now:

- no page on it runs a script it did not load from a file of its own, except the Swagger UI (§2.3), closed to every
  address the operator did not list (ADR 0021);
- the resolver's pages may run only their language menu, by nonce; their values are escaped;
- the portal's cookie is `HttpOnly`, `SameSite=Lax`, path `/portal`, ended on the server at sign-out (ADR 0034).

### 2.6 Tests

- `test_appearance.py`: the policy and the other headers on the portal's pages, files, API and its 404; nothing in the
  pages or their scripts that the policy would refuse.
- Every portal browser program imports `dev-tests/portal/csp_guard.py`, which watches each page's console and fails
  the program on any message about the policy: the whole e2e group runs under it.
- `test_landing.py`: the nonce on every inline element of the item's page, a linkset page and the error pages, a new
  one for each answer, an element typed in a value left as text, the item's page without fonts, the other answers'
  policy; the pages opened in Chromium (style applied, the language menu's script runs, nothing refused).
- `test_data_entry_api.py`: the Swagger UI's policy and the others; the Swagger UI opened in Chromium starts and reads
  the description with nothing refused.
- `test_home.py` (the real nginx): Strict-Transport-Security on every location over HTTPS, the 429s included; none over
  HTTP.

### 2.7 Alternatives not taken

- **The portal on a host name of its own** (§2.5): the isolation is real, the cost falls on every operator at the next
  update. Recorded as a residual.
- **A route for violation reports** (`report-to`): an anonymous write route on every answer, which the request limits
  of ADR 0031 would have to cover, for messages that browser extensions also cause. The browser tests catch violations
  before a release.
- **Hashes instead of a nonce** on the resolver's pages: their style holds the installation's colours and the item's
  page the brand's, so the hash would change with the data; a nonce is simpler for pages rendered on each request.
- **HSTS from Certbot** (`--hsts`) or in the installer's templates only: it would miss the operators who run their own
  TLS front, and Certbot adds it only to names it installs. The proxy covers every front that sends
  `X-Forwarded-Proto`.

## 3. Consequences

- Nothing changes for users: the pages already met the policies (the browser tests prove it). A browser extension that
  injects scripts or styles into the portal may be refused by the policy.
- Operators: no setting. After the update, a browser that once received the header over HTTPS uses only HTTPS for the
  installation's name, and for an organisation's domain, for a year; a name that must go back to HTTP needs the header
  first sent with `max-age=0` from the host's proxy.

### 3.1 Residuals

1. **One origin**: a script flaw in any page of the installation's name would still reach the portal's API with the
   user's cookie; the Swagger UI allows inline script (§2.3). Closed for installations that give the portal a name of
   its own ([ADR 0057](0057-portal-own-host-name.md)); the default stays one origin.
2. **No reports**: a policy refusal in production is seen only in the browser's console.
3. **HSTS depends on `X-Forwarded-Proto`** from the host's proxy; one year, fixed, without `includeSubDomains` or
   `preload`.
4. **Google Fonts** is a third party allowed to serve style sheets to the portal and to the resolver's pages other than
   the item's page (no script).
5. The policies are constants in the code (`portal/app.py`, `web_server/src/web_pages.py`,
   `data_entry_server/src/__init__.py`) and the proxy's configuration.
