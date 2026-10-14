"""
Link management portal for GS1 Resolver CE.

Backend-for-frontend: the browser never sees SESSION_TOKEN or the Resolver CE v3 payload.
It sends a simple JSON document (primary key, key qualifiers, description, link targets) and this service:
  1. validates it against GS1 rules;
  2. reads the current state from the resolver (GET);
  3. chooses the safe sequence of calls (POST /new, PUT, partial DELETE);
  4. writes an audit trail of who changed what.

Responses carry message *codes* (e.g. "save.updated", "gtin.checkDigit") instead of sentences;
the front end renders them in the user's language from static/i18n.js.
"""
import base64
import csv
import io
import json
import logging
import os
import re
import secrets
import time
from datetime import timedelta
from functools import wraps

import requests
from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory, session
from pymongo.errors import PyMongoError

import gs1
import jobs
import journal
import label
import linear
import apikeys
import branding
import domains
import linkcheck
import mail
import meta
import migrate
import monitor
import notify
import overview
import requestlog
import sheet
import store
import syntax
import tenants
import tokens
import users
import worker
from gs1 import ValidationError

# --------------------------------------------------------------------------- configuration
DATA_ENTRY_URL = os.environ.get("DATA_ENTRY_URL", "http://data-entry-service:3000/api").rstrip("/")
SESSION_TOKEN = os.environ.get("SESSION_TOKEN", "")
# Public address of the resolver (used in the Digital Links the portal prints and for the Origin
# check). RESOLVER_PUBLIC_URL if set, otherwise https://FQDN, the resolver root used by the web server.
_FQDN = os.environ.get("FQDN", "").strip()
RESOLVER_PUBLIC_URL = (os.environ.get("RESOLVER_PUBLIC_URL", "").strip()
                       or (f"https://{_FQDN}" if _FQDN else "")).rstrip("/")
PORTAL_ORIGIN = (os.environ.get("PORTAL_ORIGIN", "").strip() or RESOLVER_PUBLIC_URL).rstrip("/")
CONFIG_DIR = os.environ.get("PORTAL_CONFIG_DIR", "/app/config")
# Secure cookies unless explicitly switched off; the default follows the scheme of the portal origin
# so that plain-HTTP development (RESOLVER_PUBLIC_URL=http://localhost:8080) works without extra settings.
COOKIE_SECURE = os.environ.get("PORTAL_COOKIE_SECURE", "").strip().lower() not in ("false", "0", "no") \
    if os.environ.get("PORTAL_COOKIE_SECURE", "").strip() else PORTAL_ORIGIN.startswith("https://")
# A session ends after PORTAL_SESSION_IDLE_MINUTES without use (sliding expiry) and, in any case,
# PORTAL_SESSION_MAX_HOURS after the sign-in. The page warns SESSION_WARNING_SECONDS before either end.
SESSION_IDLE_MINUTES = max(0.1, float(os.environ.get("PORTAL_SESSION_IDLE_MINUTES", "30")))
SESSION_MAX_HOURS = max(SESSION_IDLE_MINUTES / 60, float(os.environ.get("PORTAL_SESSION_MAX_HOURS", "12")))
SESSION_WARNING_SECONDS = min(120.0, SESSION_IDLE_MINUTES * 60 / 4)
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = store.LOGIN_FAILURE_SECONDS   # 15 minutes
# Password recovery requests in the same window (Documentation/adr/0004-e-mail.md, section 3.5): per user name or
# address typed, per browser address; invalid single-use links per browser address.
RECOVERY_PER_LOGIN = 3
RECOVERY_PER_ADDRESS = 10
BAD_LINKS_PER_ADDRESS = 10
RECOVERY_SECONDS = 0.5      # every recovery answer takes at least this long, whether or not an account matched
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "15"))
MAX_LINKS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("portal")
audit = logging.getLogger("portal.audit")

if not SESSION_TOKEN:
    raise RuntimeError("SESSION_TOKEN is not set: the portal would be unable to authenticate with the resolver.")
if not RESOLVER_PUBLIC_URL:
    raise RuntimeError("Set FQDN (or RESOLVER_PUBLIC_URL): the portal needs the resolver's public address.")
if os.environ.get("PORTAL_SESSION_HOURS", "").strip():
    log.warning("PORTAL_SESSION_HOURS is no longer read: use PORTAL_SESSION_IDLE_MINUTES (default 30) and "
                "PORTAL_SESSION_MAX_HOURS (default 12).")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PUBLIC_ASSETS = {"app.css", "i18n.js", "login.js", "password.js", "gs1-logo.png", "favicon.png"}   # needed by the login page
PRIVATE_ASSETS = {"app.js"}


def _secret_key() -> bytes:
    """PORTAL_SECRET_KEY if set (the installer writes one to .env; every replica must share it); otherwise a
    random key created once in the config volume, which serves the portal's processes and replicas on one
    Docker host (they share the volume).

    Several processes start at once (gunicorn's workers, replicas), so the file appears complete or not at
    all: the key is written to a file of this process's own and then linked to the final name, which fails
    for every process but the first. Reading a file another process had created but not yet written would
    sign sessions with an empty key."""
    if os.environ.get("PORTAL_SECRET_KEY"):
        return os.environ["PORTAL_SECRET_KEY"].encode()
    path = os.path.join(CONFIG_DIR, "secret.key")
    if not os.path.exists(path):
        draft = f"{path}.{os.getpid()}.{secrets.token_hex(4)}"
        try:
            fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(secrets.token_hex(32))
            try:
                os.link(draft, path)
            except FileExistsError:
                pass                                   # another process was first: use its key
            finally:
                os.unlink(draft)
        except OSError as exc:
            raise RuntimeError(f"Cannot create {path} ({exc}). "
                               "/app/config must be writable by uid 10001 (the portal-config volume).") from exc
    with open(path, encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise RuntimeError(f"{path} is empty: delete it (a new key is made at the next start) "
                           "or set PORTAL_SECRET_KEY in .env.")
    return key.encode()


app = Flask(__name__, static_folder=None)
app.config.update(
    MAX_CONTENT_LENGTH=1024 * 1024,   # spreadsheet imports arrive as base64 in JSON (sheet.FORMATS: ≤ 700 KB)
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_NAME="gs1resolver_portal",
    SESSION_COOKIE_PATH="/portal",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=SESSION_IDLE_MINUTES),
    SESSION_REFRESH_EACH_REQUEST=True,   # sliding expiry: the cookie's signed time is renewed on every request
)
if not os.environ.get("PORTAL_SECRET_KEY"):
    log.warning("PORTAL_SECRET_KEY is not set: sessions are signed with %s, which works only while every "
                "portal process shares that volume (one Docker host).", os.path.join(CONFIG_DIR, "secret.key"))


def _bootstrap_admin() -> None:
    """Creates the first portal user from PORTAL_ADMIN_USERNAME / PORTAL_ADMIN_PASSWORD, only while
    the user store is empty. Existing users are never changed, so the variables can stay in place."""
    username = os.environ.get("PORTAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("PORTAL_ADMIN_PASSWORD", "")
    if not username or not password or users.load():
        return
    if len(password) < users.MIN_PASSWORD_LENGTH:
        log.warning("PORTAL_ADMIN_PASSWORD is shorter than %d characters: first user not created.",
                    users.MIN_PASSWORD_LENGTH)
        return
    try:
        users.set_password(username, password)
        audit.info("user=%s action=bootstrap", username)
    except users.StoreNotWritable as exc:
        log.warning("Cannot create the first portal user (%s).", exc)


# Start-up: the files of earlier versions move into the database once, the journal's retention follows the
# environment, and the first user is created while there is none.
migrate.run(CONFIG_DIR)
journal.apply_retention()
_bootstrap_admin()


class UpstreamError(Exception):
    """The data entry API failed or refused a call: a message code for the browser, the HTTP status to
    answer with and the upstream detail, which is logged but never shown.
    """
    def __init__(self, code: str, status: int = 502, detail=None, **params):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail
        self.params = params


def message(code: str, status: int = 200, **extra):
    """JSON answer carrying a message code (rendered in the user's language by i18n.js) and extra fields."""
    return jsonify(code=code, **extra), status


# --------------------------------------------------------------------------- authentication
class LoginThrottle:
    """Locks a username (and, separately, a client address) after repeated failures. The failures are
    documents of the "login_failures" collection, so every replica of the portal sees the same count;
    MongoDB deletes them once they are older than the lockout window (TTL index, store.py)."""

    @staticmethod
    def _failures():
        return store.col("login_failures")

    def retry_after(self, *keys: str) -> int:
        """Seconds to wait before another attempt for any of the keys (0 when none is locked)."""
        now = store.now()
        window = now - timedelta(seconds=LOCKOUT_SECONDS)
        waits = []
        for key in keys:
            recent = list(self._failures().find({"key": key, "at": {"$gt": window}}, {"at": 1})
                          .sort("at", 1).limit(MAX_LOGIN_FAILURES))
            if len(recent) >= MAX_LOGIN_FAILURES:
                waits.append(int(LOCKOUT_SECONDS - (now - recent[0]["at"]).total_seconds()) + 1)
        return max(waits, default=0)

    def fail(self, *keys: str) -> None:
        """Records a failed attempt for every key (user name and client address)."""
        now = store.now()
        self._failures().insert_many([{"key": key, "at": now} for key in keys])

    def clear(self, *keys: str) -> None:
        """Forgets the failures of the keys after a successful sign-in."""
        self._failures().delete_many({"key": {"$in": list(keys)}})

    def over(self, key: str, limit: int) -> bool:
        """Whether a key already counts `limit` events in the window (password recovery and links use their own
        keys, "forgot-…" and "link-…", in the same collection)."""
        window = store.now() - timedelta(seconds=LOCKOUT_SECONDS)
        return self._failures().count_documents({"key": key, "at": {"$gt": window}}, limit=limit) >= limit


throttle = LoginThrottle()


def client_address() -> str:
    """Address of the browser as seen through the proxies (X-Forwarded-For), for the sign-in throttle."""
    return request.access_route[0] if request.access_route else (request.remote_addr or "?")


def session_ends_in() -> float:
    """Seconds left before the session reaches PORTAL_SESSION_MAX_HOURS after its sign-in."""
    return session.get("since", time.time()) + SESSION_MAX_HOURS * 3600 - time.time()


def tenant_blocked(account: dict | None) -> bool:
    """Whether the account belongs to a tenant that was disabled or removed (its users cannot sign in, and their
    sessions end at the next request)."""
    if not account or not account.get("tenant"):
        return False
    tenant = tenants.get(account["tenant"])
    return tenant is None or tenant["disabled"]


def current_user() -> str | None:
    """Signed-in user of this session, or None. The session also carries a fingerprint of the account's
    password hash: a password change or reset ends every other session of that user. A session older than
    PORTAL_SESSION_MAX_HOURS ends whatever its use; the idle limit is checked with the cookie's signature.
    """
    username = session.get("user")
    if username and users.fingerprint_matches(username, session.get("fp")) and not tenant_blocked(users.get(username)):
        if "since" not in session:          # sessions opened before the limit existed start counting now
            session["since"] = int(time.time())
        if session_ends_in() > 0:
            return username
        session.clear()
        session["was_logged_in"] = True     # the sign-in page explains that the session has ended
        audit.info("user=%s action=session-limit", username)
        return None
    ended = session.get("was_logged_in")
    session.clear()
    if ended:
        session["was_logged_in"] = True     # keeps the reason for the sign-in page
    return None


# Calls allowed while the account must set a new password (temporary password)
MUST_CHANGE_ALLOWED = ("/portal/api/config", "/portal/api/password", "/portal/api/logout", "/portal/api/session")


def set_scope(username: str, account: dict, support: str | None = None) -> None:
    """The scope of a request (Documentation/adr/0002-tenants.md, section 3.3), from the account:
      g.user, g.account_role, g.account_tenant  the account itself;
      g.server_admin                            an administrator of the operator;
      g.tenants                                 every tenant (read once per request);
      g.tenant                                  whose records the request reaches: the user's tenant, the tenant
                                                of an open support access, or None (the operator);
      g.role, g.prefixes                        the role and the prefixes that apply (reader and the whole tenant
                                                during support access);
      g.support                                 the tenant of an open support access, or None."""
    g.user = username
    g.account_role, g.account_tenant = account.get("role", "reader"), account.get("tenant")
    g.server_admin = users.is_server_admin(account)
    g.tenants = tenants.load()
    g.support = support if g.server_admin and any(t["id"] == support for t in g.tenants) else None
    if g.support:
        g.tenant, g.role, g.prefixes = g.support, "reader", []
    else:
        g.tenant, g.role, g.prefixes = g.account_tenant, g.account_role, account.get("prefixes", [])


def require_login(view):
    """Session login. API calls get 401 with a message code; pages are redirected to the login page.
    Sets the scope of the request (set_scope) from the account, re-read on every request, so role, prefix and
    tenant changes apply at once."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        username = current_user()
        if not username:
            if request.path.startswith("/portal/api/"):
                return message("auth.required", 401)
            return redirect("/portal/login?reason=expired" if session.get("was_logged_in") else "/portal/login")
        account = users.get(username) or {}
        set_scope(username, account, session.get("support"))
        if session.get("support") and not g.support:
            session.pop("support", None)                # the tenant was removed meanwhile
        g.must_change = bool(account.get("mustChange"))
        if g.must_change and request.path.startswith("/portal/api/") and request.path not in MUST_CHANGE_ALLOWED:
            return message("password.mustChange", 403)
        return view(*args, **kwargs)
    return wrapper


def role_required(role: str):
    """Allows the view for this role and the ones above it (reader < editor < admin)."""
    minimum = users.ROLES.index(role)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if users.ROLES.index(g.role) < minimum:
                return message("access.role", 403, params={"role": role})
            return view(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(view):
    """Allows the view to administrators — of a tenant or of the operator (server administrators) — whatever the
    scope of the request: a server administrator in support access still manages users. The view limits what
    each one sees."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.account_role != "admin":
            return message("access.role", 403, params={"role": "admin"})
        return view(*args, **kwargs)
    return wrapper


def server_admin_required(view):
    """Allows the view to server administrators (administrators of the operator) only."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.server_admin:
            return message("access.serverAdmin", 403)
        return view(*args, **kwargs)
    return wrapper


class AccessDenied(Exception):
    """The record belongs to another tenant, or to a GS1 Company Prefix outside the user's."""


def allowed(anchor: str) -> bool:
    """Whether the signed-in user may see (and, with the role, change) this anchor: its owner is the scope of the
    request (the user's tenant, the tenant of a support access, or the operator) and it lies in the user's own
    GS1 Company Prefixes, if any."""
    return (tenants.owner(anchor, getattr(g, "tenants", None) or []) == getattr(g, "tenant", None)
            and gs1.within_prefixes(anchor, getattr(g, "prefixes", None)))


def check_access(anchor: str) -> None:
    """Raises AccessDenied (403) when the anchor is outside the user's GS1 Company Prefixes."""
    if not allowed(anchor):
        raise AccessDenied(anchor)


_SCOPE = object()


def log_event(action: str, tenant=_SCOPE, actor_tenant=_SCOPE, **fields) -> None:
    """Journal entry (history and audit); a failure is logged, never shown to the user.

    tenant: whose audit trail the event belongs to (None: the operator's). By default the owner of the record
    for record events, otherwise the scope of the request. actor_tenant: the tenant of the user who acted (by
    default the account's); when an operator user acts on a tenant the event is marked byOperator."""
    try:
        user = fields.pop("user", None) or getattr(g, "user", None) or "-"
        if tenant is _SCOPE:
            tenant = (tenants.owner(fields["anchor"], getattr(g, "tenants", None) or tenants.load())
                      if fields.get("anchor") else getattr(g, "tenant", None))
        if actor_tenant is _SCOPE:
            actor_tenant = getattr(g, "account_tenant", None)
        if tenant:
            fields["tenant"] = tenant
            if not actor_tenant:
                fields["byOperator"] = True
        journal.append(action, user, **fields)
    except (OSError, PyMongoError) as exc:
        log.warning("Journal not written (%s): %s", action, exc)


@app.before_request
def same_origin_only():
    """Rejects writes coming from another site (CSRF defence while using Basic auth)."""
    if request.method in ("POST", "PUT", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != PORTAL_ORIGIN:
            return message("request.forbiddenOrigin", 403)
        if request.method != "DELETE" and not request.is_json:
            return message("request.jsonRequired", 415)


@app.after_request
def security_headers(resp):
    """Headers added to every answer: no MIME sniffing, no framing, same-origin referrer, no caching."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.errorhandler(ValidationError)
def on_validation_error(err):
    """A rule of the standard or of the portal was broken: 422 with the message code and parameters."""
    return message(err.code, 422, params=err.params)


@app.errorhandler(AccessDenied)
def on_access_denied(err):
    """Identifier outside the user's GS1 Company Prefixes: 403."""
    return message("access.prefix", 403)


@app.errorhandler(users.UserError)
def on_user_error(err):
    """User administration refused (invalid name, last administrator, …): 422."""
    return message(err.code, 422, params=err.params)


@app.errorhandler(UpstreamError)
def on_upstream_error(err):
    """The resolver failed or refused: logged with its detail, answered with a message code only."""
    log.warning("Upstream: %s | %s", err.code, err.detail)
    return message(err.code, err.status, params=err.params)


# --------------------------------------------------------------------------- resolver API client
def resolver(method: str, path: str, payload=None) -> tuple[int, object]:
    """One call to the data entry API with the bearer token: (HTTP status, decoded JSON body).
    Raises UpstreamError when the API cannot be reached or refuses the token.
    """
    headers = {"Authorization": f"Bearer {SESSION_TOKEN}", "Accept": "application/json"}
    try:
        r = requests.request(method, DATA_ENTRY_URL + path, headers=headers,
                             json=payload, timeout=UPSTREAM_TIMEOUT)
    except requests.RequestException as exc:
        raise UpstreamError("upstream.unavailable", 503, str(exc)) from exc
    if r.status_code in (401, 403):
        raise UpstreamError("upstream.unauthorised", 502, r.text[:300])
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return r.status_code, body


def read_entries(anchor: str) -> tuple[list[dict], str | None]:
    """Every v3 entry for the primary key (one per qualifier set) and the shared default link type."""
    status, body = resolver("GET", anchor)
    if status == 404:
        return [], None
    if status != 200 or not isinstance(body, dict):
        raise UpstreamError("upstream.readFailed", 502, body)
    entries = body.get("data") or []
    default = entries[0].get("defaultLinktype") if entries else None
    return entries, default


def find_entry(entries: list[dict], qualifiers: list) -> dict | None:
    """The entry of a document whose qualifier set equals the given one (order does not matter), or None."""
    for entry in entries:
        if gs1.qualifiers_match(entry.get("qualifiers"), qualifiers):
            return entry
    return None


def describe_entry(entry: dict) -> dict:
    """Language-neutral description of an entry: {"kind": "product"} without qualifiers,
    {"kind": "qualified", "qualifiers": [[AI, value], …], "path": "/10/L1"} for a qualifier set the
    portal manages, {"kind": "other", "value": …} for anything else (templates such as {lotnumber},
    AIs or characters the portal does not manage)."""
    pairs = gs1.pairs_from(entry.get("qualifiers"))
    if not pairs:
        return {"kind": "product"}
    key = gs1.split_anchor(entry.get("anchor") or "")
    if key and gs1.is_valid_qualifier_set(key[0], pairs):
        pairs = gs1.normalise_qualifiers(key[0], pairs)
        return {"kind": "qualified", "qualifiers": [list(p) for p in pairs],
                "path": gs1.qualifier_path(pairs, encode=False),
                "informative": [list(p) for p in gs1.pairs_from(entry.get("informativeQualifiers"))]}
    return {"kind": "other", "value": "".join(f"({q}){v}" for q, v in pairs)}


def record_change(anchor: str, pairs: list, doc: dict | None, action: str) -> None:
    """Keeps the "last change" metadata and the record's history; never makes a save fail."""
    qpath = gs1.qualifier_path(pairs, encode=False)
    try:
        if action == "delete":
            meta.remove(anchor, qpath)
        else:
            meta.touch(anchor, qpath, g.user, getattr(g, "tenant", None))
    except (OSError, PyMongoError) as exc:
        log.warning("Record metadata not updated for %s: %s", meta.key(anchor, qpath), exc)
    log_event(action, anchor=anchor, qpath=qpath, doc=doc)


def is_success(status: int, body) -> bool:
    """Whether a data entry answer is a success (the API sometimes answers 200 with an error field)."""
    return status in (200, 201) and not (isinstance(body, dict) and body.get("error"))


# --------------------------------------------------------------------------- form → Resolver CE v3
def request_key(source) -> str:
    """The anchor (/AI/value) named by a request: key + value, or gtin (older clients)."""
    ai = str(source.get("key") or "01")
    value = source.get("value") if source.get("value") is not None else source.get("gtin", "")
    return gs1.anchor_for(ai, gs1.normalise_key(ai, value))


def request_qualifiers(source, anchor: str) -> list[tuple[str, str]]:
    """The qualifiers named by a request: "qualifiers" as {"10": "L1"} (JSON) or "/10/L1/21/S1"
    (query string), plus "lot" from older clients."""
    raw = source.get("qualifiers") or {}
    pairs = list(raw.items()) if isinstance(raw, dict) else gs1.parse_qualifier_text(str(raw))
    if source.get("lot"):
        pairs.append(("10", str(source.get("lot"))))
    return gs1.normalise_qualifiers(gs1.split_anchor(anchor)[0], pairs)


def request_record(source, anchor: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The record named by a request: (its qualifiers, the informative ones). The qualifiers of a GS1 Digital
    Link may include a serial number's variant and batch, which are not part of the record (section 2.5.9)."""
    return gs1.split_informative(gs1.split_anchor(anchor)[0], request_qualifiers(source, anchor))


def request_attributes(source) -> list[tuple[str, str]]:
    """GS1 Digital Link data attributes named by a request: [{"ai": "17", "value": "261231"}] (JSON) or
    repeated attr=17:261231 (query string). Only put in the QR code, never stored."""
    if hasattr(source, "getlist"):
        items = [item.partition(":")[::2] for item in source.getlist("attr")]
    else:
        items = [(str(a.get("ai", "")), str(a.get("value", ""))) for a in source.get("attributes") or []
                 if isinstance(a, dict)]
    return [(gs1.without_invisible(ai).strip("() "), gs1.without_invisible(value).strip()) for ai, value in items]


def link_base(anchor: str, choice: str | None = None) -> str:
    """The address in front of a record's GS1 path: the default domain of its prefix, the installation's, or the
    verified domain chosen (Documentation/adr/0009-tenant-domains.md)."""
    return domains.label_base(anchor, getattr(g, "tenant", None), choice, RESOLVER_PUBLIC_URL)


def digital_link_for(anchor: str, pairs, attributes, domain: str | None = None) -> tuple[str, list[str]]:
    """The record's GS1 Digital Link URI on its domain, with data attributes (validated by the syntax engine) if any."""
    base = link_base(anchor, domain)
    if not attributes:
        return gs1.digital_link(base, anchor, pairs), []
    return syntax.ENGINE.digital_link(base, anchor, pairs, attributes)


def landing_link(anchor: str, pairs) -> dict:
    """The link of a record to its own page (Documentation/adr/0011-item-page.md), on the record's domain."""
    return {"linktype": gs1.LANDING_TYPE, "href": gs1.landing_url(link_base(anchor), anchor, pairs),
            "title": "Item page", "type": "text/html", "hreflang": ["und"]}


def build_document(data: dict) -> tuple[str, str | None, dict]:
    """Validates a record sent by the browser (key, qualifiers, description, targets, default) and builds
    the Resolver CE v3 document: (anchor, qualifier pairs, document). Raises ValidationError on the first problem.
    """
    anchor = request_key(data)
    pairs, informative = request_record(data, anchor)

    description = gs1.clean_text(data.get("description"))
    if not description:
        raise ValidationError("description.required")
    if len(description) > gs1.MAX_DESCRIPTION:
        raise ValidationError("description.tooLong", max=gs1.MAX_DESCRIPTION)

    rows = data.get("links") or []
    if not rows:
        raise ValidationError("links.required")
    if len(rows) > MAX_LINKS:
        raise ValidationError("links.tooMany", max=MAX_LINKS)

    links, seen = [], {}
    for position, row in enumerate(rows, start=1):
        link_type = row.get("linkType")
        if link_type not in gs1.LINK_TYPE_CODES:
            raise ValidationError("link.typeRequired", position=position)
        href = gs1.normalise_url(row.get("url"), position)
        hreflang = [gs1.normalise_language(h) for h in (row.get("hreflang") or []) if isinstance(h, str) and h]
        if not hreflang or not all(hreflang):
            raise ValidationError("link.languageRequired", position=position)
        link = {
            "linktype": link_type,
            "href": href,
            "title": gs1.clean_text(row.get("title"))[:120] or gs1.LINK_TYPE_DEFAULT_TITLES[link_type],
            "type": gs1.guess_media_type(href),
            "hreflang": hreflang,
            # No "fwqs": the resolver always passes the query string on (GS1-Conformant Resolver 1.2.1, section
            # 2.12; the option to switch it off was removed in release 1.2.0, and from the portal on the owner's
            # decision). Saving a record drops "fwqs": false from records made before.
        }
        context = [c for c in (row.get("context") or []) if isinstance(c, str) and c]
        if context:  # preserved when the link was created by another tool
            link["context"] = context
        key = gs1.link_key(link)
        if key in seen:
            raise ValidationError("link.duplicate", first=seen[key], second=position)
        seen[key] = position
        links.append(link)

    # The first link is the default (gs1:defaultLink); its type becomes the key's defaultLinktype.
    default = data.get("defaultLinkType") or links[0]["linktype"]
    if data.get("landingPage"):
        # The item's page as the default target (Documentation/adr/0011-item-page.md): a gs1:defaultLink to the
        # resolver's page of these links, on the record's domain
        links.append(landing_link(anchor, pairs))
        default = gs1.LANDING_TYPE
    if default not in {l["linktype"] for l in links}:
        raise ValidationError("default.required")

    doc = {"anchor": anchor, "itemDescription": description,
           "defaultLinktype": default, "links": links}
    if pairs:
        doc["qualifiers"] = gs1.qualifier_list(pairs)
    rule = gs1.INFORMATIVE_QUALIFIERS.get(gs1.split_anchor(anchor)[0])
    if rule and rule[0] in {q for q, _ in pairs}:
        # A serial-number record always sends the field, so that clearing the batch or variant reaches the
        # resolver (an absent field keeps the stored value on PUT).
        doc["informativeQualifiers"] = gs1.qualifier_list(informative)
    return anchor, pairs, doc


# --------------------------------------------------------------------------- pages and assets
@app.get("/portal")
def portal_root():
    """/portal → /portal/ (relative addresses of the page depend on the trailing slash)."""
    return redirect("/portal/", 301)


@app.get("/portal/")
@require_login
def index():
    """The portal page (sign-in required)."""
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/portal/login")
def login_page():
    """The sign-in page; a user already signed in goes straight to the portal."""
    if current_user():
        return redirect("/portal/")
    return send_from_directory(STATIC_DIR, "login.html")


@app.get("/portal/<name>")
def assets(name):
    """Static files: those used by the sign-in page for anyone (PUBLIC_ASSETS), the others only after sign-in."""
    if name in PUBLIC_ASSETS:
        return send_from_directory(STATIC_DIR, name, max_age=3600 if name.endswith(".png") else 0)
    if name in PRIVATE_ASSETS and current_user():
        return send_from_directory(STATIC_DIR, name)
    return Response(status=404)


def shown_username(typed: str) -> str:
    """A user name typed at a failed sign-in, as written to the log and the audit trail: anyone can type
    it, so line breaks and other unprintable characters (which could forge log lines) become "?" and it
    is cut at the longest valid user name."""
    if not typed:
        return "-"
    text = "".join(c if c.isprintable() else "?" for c in typed)
    return text if len(text) <= 64 else text[:64] + "…"


@app.post("/portal/api/login")
def login():
    """Signs a user in: throttled per user name and per address, audited, and the session is bound to the
    account's password fingerprint.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    keys = (f"user:{username.lower()}", f"addr:{client_address()}")
    wait = throttle.retry_after(*keys)
    if wait:
        return message("auth.locked", 429, params={"minutes": -(-wait // 60)})
    account = users.get(username) if username else None
    tenant = (account or {}).get("tenant")
    if not username or not users.verify(username, password):
        throttle.fail(*keys)
        typed = shown_username(username)
        audit.info("user=%s action=login-failed addr=%s", typed, client_address())
        log_event("login-failed", user=typed, detail=client_address(), tenant=tenant, actor_tenant=tenant)
        if account and throttle.retry_after(keys[0]):   # this failure locked the account: tell its owner, once
            notify.send(username, "account-locked", when=notify.now_text(), minutes=LOCKOUT_SECONDS // 60)
        time.sleep(0.5)
        return message("auth.invalid", 401)
    if tenant_blocked(account):
        audit.info("user=%s action=login-refused addr=%s", username, client_address())
        log_event("login-refused", user=username, detail=client_address(), tenant=tenant, actor_tenant=tenant)
        return message("auth.tenantDisabled", 403)
    throttle.clear(*keys)
    session.clear()
    session.permanent = True
    session.update(user=username, fp=users.fingerprint(username), was_logged_in=True, since=int(time.time()))
    audit.info("user=%s action=login addr=%s", username, client_address())
    users.touch_login(username)
    users.note_language(username, data.get("language"))     # the language of his messages, until he chooses one
    log_event("login", user=username, detail=client_address(), tenant=tenant, actor_tenant=tenant)
    return message("auth.welcome", 200, user=username, mustChange=bool((users.get(username) or {}).get("mustChange")))


@app.post("/portal/api/logout")
def logout():
    """Ends the session and records it in the audit trail."""
    username, support = session.get("user"), session.get("support")
    session.clear()
    if username:
        tenant = (users.get(username) or {}).get("tenant")
        if support:
            log_event("support-close", user=username, tenant=support, actor_tenant=None, detail="logout")
        audit.info("user=%s action=logout", username)
        log_event("logout", user=username, tenant=tenant, actor_tenant=tenant)
    return message("auth.loggedOut")


@app.post("/portal/api/password")
@require_login
def change_password():
    """Changes the signed-in user's password (current password required, minimum length); ends the other
    sessions of the account and clears the must-change flag.
    """
    data = request.get_json(silent=True) or {}
    current = str(data.get("currentPassword", ""))
    new = str(data.get("newPassword", ""))
    keys = (f"user:{g.user.lower()}",)
    if throttle.retry_after(*keys):
        return message("auth.locked", 429, params={"minutes": LOCKOUT_SECONDS // 60})
    if not users.verify(g.user, current):
        throttle.fail(*keys)
        raise ValidationError("password.currentWrong")
    if len(new) < users.MIN_PASSWORD_LENGTH:
        raise ValidationError("password.tooShort", min=users.MIN_PASSWORD_LENGTH)
    if new == current:
        raise ValidationError("password.sameAsCurrent")
    try:
        users.set_password(g.user, new, must_change=False)
    except users.StoreNotWritable as exc:
        log.error("Password change failed: %s", exc)
        return message("password.storeReadOnly", 500)
    session["fp"] = users.fingerprint(g.user)   # keeps this session; every other session is signed out
    audit.info("user=%s action=password-change", g.user)
    log_event("password-change", tenant=g.account_tenant)
    notify.send(g.user, "password-changed", when=notify.now_text())
    return message("password.changed")


# --------------------------------------------------------------------------- e-mail: recovery and links
@app.get("/portal/api/login/options")
def login_options():
    """What the sign-in page offers besides the password: recovery by e-mail when mail is on."""
    return jsonify(passwordRecovery=mail.enabled())


def _link_params(purpose: str, token: str) -> dict:
    """The link and its validity, as the messages show them."""
    hours = tokens.validity_hours(purpose)
    return {"link": tokens.link(token, purpose, notify.link_base()),
            "hours": f"{hours:g}", "minutes": f"{round(hours * 60)}"}


def send_link(username: str, purpose: str, template: str, language: str | None = None) -> bool:
    """Issues a single-use link and queues the message that carries it; the link is withdrawn when no message
    could be queued."""
    token = tokens.issue(username, purpose)
    if notify.send(username, template, language=language, **_link_params(purpose, token)):
        return True
    tokens.purge(username, purpose)
    return False


@app.post("/portal/api/password/forgot")
def forgot_password():
    """Password recovery (Documentation/adr/0004-e-mail.md, decision 6): sends a recovery link when the user name
    or address typed belongs to an account that may sign in and has an address. The answer, and the time it
    takes, are the same whether or not an account matched."""
    if not mail.enabled():
        return message("password.recoveryOff", 404)
    data = request.get_json(silent=True) or {}
    typed = str(data.get("login", "")).strip()[:users.EMAIL_MAX]
    if not typed:
        raise ValidationError("password.recoveryMissing")
    started = time.monotonic()
    keys = (f"forgot-user:{typed.lower()}", f"forgot-addr:{client_address()}")
    if throttle.over(keys[0], RECOVERY_PER_LOGIN) or throttle.over(keys[1], RECOVERY_PER_ADDRESS):
        return message("password.recoveryLimit", 429, params={"minutes": LOCKOUT_SECONDS // 60})
    throttle.fail(*keys)
    username = users.find_login(typed)
    account = users.get(username) if username else None
    if account and account.get("email") and notify.reachable(account):
        language = account.get("language") or data.get("language")
        if send_link(username, "reset", "password-recovery", language=language):
            tenant = account.get("tenant")
            audit.info("user=%s action=password-recovery addr=%s", username, client_address())
            log_event("password-recovery", user=username, detail=client_address(), tenant=tenant, actor_tenant=tenant)
    time.sleep(max(0.0, RECOVERY_SECONDS - (time.monotonic() - started)))
    return message("password.recoverySent")


def _bad_link(key: str):
    throttle.fail(key)
    return message("password.linkInvalid", 410)


@app.post("/portal/api/password/link/check")
def check_password_link():
    """Whether a single-use link is still valid, and for whom: the page shows the user name before the user types
    a password. Nothing is used up."""
    key = f"link-addr:{client_address()}"
    if throttle.over(key, BAD_LINKS_PER_ADDRESS):
        return message("password.linkLimit", 429, params={"minutes": LOCKOUT_SECONDS // 60})
    found = tokens.peek((request.get_json(silent=True) or {}).get("token"))
    if not found or not notify.reachable(users.get(found["user"])):
        return _bad_link(key)
    return jsonify(user=found["user"], purpose=found["purpose"], min=users.MIN_PASSWORD_LENGTH)


@app.post("/portal/api/password/link")
def set_password_by_link():
    """Sets the password through an invitation or recovery link: the link is used up, every session and every other
    link of the account end, and a recovery is followed by a security message."""
    key = f"link-addr:{client_address()}"
    if throttle.over(key, BAD_LINKS_PER_ADDRESS):
        return message("password.linkLimit", 429, params={"minutes": LOCKOUT_SECONDS // 60})
    data = request.get_json(silent=True) or {}
    token, new = data.get("token"), str(data.get("newPassword", ""))
    if not tokens.peek(token):
        return _bad_link(key)
    if len(new) < users.MIN_PASSWORD_LENGTH:
        raise ValidationError("password.tooShort", min=users.MIN_PASSWORD_LENGTH)
    used = tokens.consume(token)                        # atomically: a link works once
    account = users.get(used["user"]) if used else None
    if not used or not notify.reachable(account):
        return _bad_link(key)
    username, purpose, tenant = used["user"], used["purpose"], account.get("tenant")
    try:
        users.set_password(username, new, must_change=False)
    except users.StoreNotWritable as exc:
        log.error("Password through a link not set: %s", exc)
        return message("password.storeReadOnly", 500)
    tokens.purge(username)
    throttle.clear(f"user:{username.lower()}")          # a locked account is open again
    users.note_language(username, data.get("language"))
    action = "invite-accepted" if purpose == "invite" else "password-reset"
    audit.info("user=%s action=%s addr=%s", username, action, client_address())
    log_event(action, user=username, detail=client_address(), tenant=tenant, actor_tenant=tenant)
    if purpose == "reset":
        notify.send(username, "password-changed", when=notify.now_text())
    session.clear()
    return message("password.set", 200, purpose=purpose, user=username)


@app.get("/portal/healthz")
def healthz():
    """Health check for Compose and monitoring: the portal is up, whether the resolver answers, whether a job
    worker is running (jobs.WORKER_ALIVE_SECONDS) and whether e-mail is configured."""
    try:
        status, _ = resolver("GET", "/heartbeat")
    except UpstreamError:
        status = 0
    try:
        workers = jobs.workers_alive()
    except PyMongoError:
        workers = 0
    return jsonify(portal="ok", resolver="ok" if status == 200 else "unavailable",
                   worker="ok" if workers else "unavailable", mail="on" if mail.enabled() else "off"), 200


# --------------------------------------------------------------------------- portal API
@app.get("/portal/api/config")
@require_login
def config():
    """Everything the page needs at start-up: user, role, prefixes, resolver address, link types, primary keys
    with their qualifiers and allowed qualifier shapes, languages, import limits and the data attributes on offer.
    """
    return jsonify(
        user=g.user, role=g.role, prefixes=g.prefixes, mustChange=g.must_change,
        accountRole=g.account_role, serverAdmin=g.server_admin,
        tenant=tenant_summary(g.account_tenant), support=tenant_summary(g.support),
        resolver=RESOLVER_PUBLIC_URL,
        linkTypes=[{"code": code, "group": group} for code, group, _ in gs1.LINK_TYPES],
        keys=[{"code": ai, "name": name, "qualifiers": gs1.key_qualifiers(ai),
               "shapes": [[{"ai": q, "required": req} for q, req in shape] for shape in gs1.KEY_SHAPES.get(ai, [[]])],
               # section 2.5.9: a serial number's variant and batch are informative; a key-level record is possible
               "informative": ({"serial": gs1.INFORMATIVE_QUALIFIERS[ai][0], "ais": list(gs1.INFORMATIVE_QUALIFIERS[ai][1])}
                               if ai in gs1.INFORMATIVE_QUALIFIERS else None),
               "keyLevel": gs1.has_key_level(ai)}
              for ai, (name, _) in gs1.PRIMARY_KEYS.items()],
        rules=gs1.browser_rules(),
        languages=gs1.LANGUAGES,
        importLimits=sheet.limits(),
        dataAttributes=syntax.ENGINE.describe(),
        session=session_info(),
        mail={"enabled": mail.enabled()},
        requestLog={"days": requestlog.log_days(), "whole": log_sees_everything()},
        domains={"installation": RESOLVER_PUBLIC_URL,
                 "verified": [{"domain": d["_id"], "url": domains.base_url(d), "defaultFor": d.get("defaultFor") or []}
                              for d in domains.verified(g.tenant)]},
        preferences=preferences_of(users.get(g.user) or {}),
    )


def preferences_of(account: dict) -> dict:
    """The user's own e-mail choices (Options → E-mail): his address (set by the administrators), the language of
    his messages and each optional category, on or off."""
    chosen = account.get("notify") or {}
    return {"email": account.get("email"), "language": account.get("language"),
            "languageChosen": bool(account.get("languageChosen")),
            "notify": {name: bool(chosen.get(name, notify.CATEGORIES[name][1])) for name in notify.OPTIONAL}}


@app.get("/portal/api/preferences")
@require_login
def get_preferences():
    """The signed-in user's e-mail preferences."""
    return jsonify(preferences_of(users.get(g.user) or {}))


@app.put("/portal/api/preferences")
@require_login
def save_preferences():
    """Saves the language of the user's messages and the optional categories he wants."""
    data = request.get_json(silent=True) or {}
    choices = data.get("notify")
    if choices is not None:
        if not isinstance(choices, dict) or any(name not in notify.OPTIONAL for name in choices):
            raise users.UserError("preferences.categoryUnknown")
    account = users.set_preferences(g.user, language=data.get("language"), notify=choices)
    shown = preferences_of(account)
    log_event("preferences", tenant=g.account_tenant,
              detail=f'language={shown["language"]} ' + " ".join(f"{k}={'on' if v else 'off'}"
                                                                for k, v in shown["notify"].items()))
    return message("preferences.saved", 200, preferences=shown)


def tenant_summary(tenant_id: str | None) -> dict | None:
    """{"id", "name", "disabled"} of a tenant of this request, or None."""
    tenant = next((t for t in getattr(g, "tenants", None) or [] if t["id"] == tenant_id), None) if tenant_id else None
    return {"id": tenant["id"], "name": tenant["name"], "disabled": tenant["disabled"]} if tenant else None


def session_info() -> dict:
    """The session limits the page counts down from: idle limit, warning time, time left before the
    absolute limit and that limit in hours (seconds are relative, so the browser's clock does not matter)."""
    return {"idleSeconds": round(SESSION_IDLE_MINUTES * 60), "warningSeconds": round(SESSION_WARNING_SECONDS),
            "endsIn": max(0, round(session_ends_in())), "maxHours": SESSION_MAX_HOURS}


@app.get("/portal/api/session")
@require_login
def keep_alive():
    """Renews the session after the user has worked in the page without calling the server (typing, reading)
    or chose to stay signed in when warned; answers the same limits as the configuration."""
    return jsonify(session_info())


@app.get("/portal/api/record")
@require_login
def get_record():
    """One record (key + qualifier set) for the editor: description, targets with the default first, the
    Digital Link and the other records of the same key (for the list under Open record).
    """
    anchor = request_key(request.args)
    check_access(anchor)
    pairs, informative = request_record(request.args, anchor)
    entries, default = read_entries(anchor)
    target = find_entry(entries, gs1.qualifier_list(pairs))
    stored = gs1.pairs_from(target.get("informativeQualifiers")) if target else []
    known = meta.load()
    others = []
    for entry in entries:
        if entry is target:
            continue
        # What the editor's "other records of this key" list shows: qualifiers, description, number of
        # targets and the last change made through the portal
        other = describe_entry(entry)
        info = meta.visible(known.get(meta.key(anchor, other.get("path", ""))), g.tenant) if other["kind"] != "other" else {}
        other.update(description=entry.get("itemDescription") or "", links=len(entry.get("links") or []),
                     updatedAt=info.get("updatedAt"), updatedBy=info.get("updatedBy"))
        others.append(other)
    ai, value = gs1.split_anchor(anchor)

    result = {
        "key": ai, "value": value, "anchor": anchor, "qualifiers": [list(p) for p in pairs],
        # the serial number's variant and batch typed now, and those kept with the record
        "informative": [list(p) for p in informative], "storedInformative": [list(p) for p in stored],
        "digitalLink": gs1.digital_link(link_base(anchor), anchor, gs1.join_informative(pairs, informative or stored)),
        "exists": target is not None,
        # section 2.5.9: whether the key has a record of its own (the editor offers one when saving)
        "hasKeyRecord": any(not e.get("qualifiers") for e in entries),
        "otherEntries": others,
        # With other entries on the same key the default link type is shared and cannot change here.
        "sharedDefaultLinkType": default if others else None,
        "defaultLinkType": default,
        "description": "", "links": [], "landingPage": False,
    }
    if target:
        result["description"] = target.get("itemDescription", "")
        result["landingPage"] = any(gs1.is_landing(l) for l in target.get("links", []))
        result["links"] = [{
            "linkType": l.get("linktype"), "url": l.get("href"), "title": l.get("title") or "",
            "hreflang": l.get("hreflang") or ["pt"], "context": l.get("context") or [],
        } for l in target.get("links", []) if not gs1.is_landing(l)]
        result["links"].sort(key=lambda l: l["linkType"] != default)   # default link first
    return jsonify(result)


@app.post("/portal/api/record")
@require_login
@role_required("editor")
def save_record():
    """Creates or replaces a record from the editor (editor role, within the user's prefixes)."""
    data = request.get_json(silent=True) or {}
    anchor, pairs, doc = build_document(data)
    check_access(anchor)
    uri = gs1.digital_link(link_base(anchor), anchor,
                           gs1.join_informative(pairs, gs1.pairs_from(doc.get("informativeQualifiers"))))
    key_doc = key_record_document(anchor, pairs, doc, data.get("keyRecord"))
    if key_doc:
        store_record(anchor, [], key_doc)        # first, so the qualified record is never without a default above it
    created = store_record(anchor, pairs, doc)
    code = ("save.createdWithKey" if key_doc else "save.created") if created else ("save.updatedWithKey" if key_doc else "save.updated")
    return message(code, 201 if created else 200, digitalLink=uri, created=created, keyRecordCreated=bool(key_doc))


def key_record_document(anchor: str, pairs: list, doc: dict, request_data) -> dict | None:
    """The key-level record asked for when saving a qualified record of a key that has none (GS1-Conformant
    Resolver 1.2.1, section 2.5.9: a default link at the entry level or higher). request_data:
    {"mode": "copy", "description"} copies the targets being saved; {"mode": "target", "description", "url"}
    gives one target of the key's default link type, in the language of the record's default target.
    None when nothing was asked for, or the key already has its record."""
    if not isinstance(request_data, dict) or not pairs or not gs1.has_key_level(gs1.split_anchor(anchor)[0]):
        return None
    entries, _ = read_entries(anchor)
    if any(not e.get("qualifiers") for e in entries):
        return None
    ai, value = gs1.split_anchor(anchor)
    default = doc["links"][0]
    # With the item's page as default target, the key's record gets its own page (the same option), not a copy of
    # the qualified record's page link
    landing = doc["defaultLinktype"] == gs1.LANDING_TYPE
    if request_data.get("mode") == "target":
        rows = [{"linkType": default["linktype"] if landing else doc["defaultLinktype"], "url": request_data.get("url"),
                 "hreflang": default["hreflang"], "title": ""}]
    else:
        rows = [{"linkType": l["linktype"], "url": l["href"], "hreflang": l["hreflang"], "title": l["title"],
                 "context": l.get("context", [])} for l in doc["links"] if not gs1.is_landing(l)]
    _, _, key_doc = build_document({"key": ai, "value": value, "description": request_data.get("description") or doc["itemDescription"],
                                    "defaultLinkType": rows[0]["linkType"] if landing else doc["defaultLinktype"],
                                    "landingPage": landing, "links": rows})
    return key_doc


def store_record(anchor: str, pairs: list, doc: dict) -> bool:
    """Creates or replaces one record (primary key + qualifier set) with the safe call sequence.
    Returns True when the record was created. Used by the editor and by spreadsheet imports."""
    qualifiers = doc.get("qualifiers", [])

    entries, current_default = read_entries(anchor)
    target = find_entry(entries, qualifiers)
    others = [e for e in entries if e is not target]

    if others and doc["defaultLinktype"] != current_default:
        raise ValidationError("default.sharedMismatch", linkType=current_default,
                              entries=[describe_entry(e) for e in others])

    # Case 1: new key, or new batch/lot on an existing GTIN → POST /new (upsert appends the entry)
    if target is None:
        status, body = resolver("POST", "/new", doc)
        if not is_success(status, body):
            raise UpstreamError("upstream.createRejected", 502, body)
        audit.info("user=%s action=create anchor=%s%s links=%d",
                   g.user, anchor, gs1.qualifier_path(pairs), len(doc["links"]))
        record_change(anchor, pairs, doc, "create")
        return True

    # Case 2: existing entry → PUT (merge on linktype+hreflang+context), then a partial DELETE of the
    # links the user removed. In this order the product is never left without a target.
    status, body = resolver("PUT", anchor, doc)
    if not is_success(status, body):
        raise UpstreamError("upstream.updateRejected", 502, body)

    new_keys = {gs1.link_key(l) for l in doc["links"]}
    removed = [{"linktype": l["linktype"], "hreflang": l.get("hreflang") or [],
                "context": l.get("context") or []}
               for l in target.get("links", []) if gs1.link_key(l) not in new_keys]
    if removed:
        status, body = resolver("DELETE", anchor, {"qualifiers": qualifiers, "links": removed})
        if not is_success(status, body):
            raise UpstreamError("upstream.partialUpdate", 502, body, count=len(removed))

    audit.info("user=%s action=update anchor=%s%s links=%d removed=%d",
               g.user, anchor, gs1.qualifier_path(pairs), len(doc["links"]), len(removed))
    record_change(anchor, pairs, doc, "update")
    return False


@app.delete("/portal/api/record")
@require_login
@role_required("editor")
def delete_record():
    """Deletes one record. The API deletes whole documents only, so the other records of the key are
    written back, and the original is restored if that fails.
    """
    anchor = request_key(request.args)
    check_access(anchor)
    pairs, _ = request_record(request.args, anchor)
    remove_record(anchor, pairs)
    return message("delete.done")


def remove_record(anchor: str, pairs: list) -> None:
    """Deletes one record of a key, keeping the others (the editor and the tenant API). ValidationError
    record.notFound when the key has no record with those qualifiers."""
    entries, _ = read_entries(anchor)
    target = find_entry(entries, gs1.qualifier_list(pairs))
    if target is None:
        raise ValidationError("record.notFound")
    others = [e for e in entries if e is not target]

    status, body = resolver("DELETE", anchor)
    if not is_success(status, body):
        raise UpstreamError("upstream.deleteFailed", 502, body)
    if others:
        # The API cannot remove a whole qualifier entry: recreate the document with the remaining
        # entries and restore the original if that fails.
        status, body = resolver("POST", "/new", others)
        if not is_success(status, body):
            resolver("POST", "/new", entries)
            raise UpstreamError("upstream.deleteRestored", 502, body)

    audit.info("user=%s action=delete anchor=%s%s", g.user, anchor, gs1.qualifier_path(pairs))
    record_change(anchor, pairs, target, "delete")


@app.get("/portal/api/records")
@require_login
def list_records():
    """Every record on the resolver (one per primary key + qualifier set), with the portal's metadata.
    Searching and filtering happen in the browser; the list is small enough to send whole."""
    return jsonify({"records": visible_records()})


def visible_records() -> list[dict]:
    """The records of the record list: every record on the resolver the user may see, with the portal's metadata
    (also the overview's record quality, Documentation/adr/0007-overview-indicators.md)."""
    status, body = resolver("GET", "/summary")
    if status == 404:
        lines = []
    elif status != 200 or not isinstance(body, dict):
        raise UpstreamError("upstream.readFailed", 502, body)
    else:
        lines = body.get("data") or []
    known = meta.load()
    records = []
    # GS1-Conformant Resolver 1.2.1, section 2.5.9: keys that have a record of their own (no qualifiers)
    with_key_record = {line.get("anchor") for line in lines if not line.get("qualifiers")}
    for line in lines:
        anchor = line.get("anchor") or ""
        key = gs1.split_anchor(anchor)
        if not key or not allowed(anchor):
            continue                      # keys the portal does not manage, or outside the user's prefixes
        entry = describe_entry(line)
        qpath = entry.get("path", "")
        info = meta.visible(known.get(meta.key(anchor, qpath)), g.tenant) if entry["kind"] != "other" else {}
        records.append({
            "key": key[0], "value": key[1], "anchor": anchor, "kind": entry["kind"],
            "qualifiers": entry.get("qualifiers", []), "qpath": qpath,
            "informative": entry.get("informative", []),
            "other": entry.get("value") if entry["kind"] == "other" else None,
            "description": line.get("itemDescription") or "",
            "defaultLinkType": line.get("defaultLinktype"),
            "links": line.get("linkCount", 0),
            "updatedAt": info.get("updatedAt"), "updatedBy": info.get("updatedBy"),
            "createdAt": info.get("createdAt"), "createdBy": info.get("createdBy"),
            # qualified record of a key without a record of its own: other codes of that key answer 404
            "noKeyRecord": bool(entry["kind"] != "product" and gs1.has_key_level(key[0]) and anchor not in with_key_record),
            # a serial number registered together with its batch or variant (made before rule 2 was applied)
            "breaksRules": entry["kind"] == "qualified" and bool(gs1.split_informative(
                key[0], [tuple(p) for p in entry.get("qualifiers", [])])[1]),
        })
    return records


# --------------------------------------------------------------------------- spreadsheets
def summary_with_links() -> list[dict]:
    """Every record on the resolver with its targets (GET /summary?links=true), keys the portal manages only."""
    status, body = resolver("GET", "/summary?links=true")
    if status == 404:
        return []
    if status != 200 or not isinstance(body, dict):
        raise UpstreamError("upstream.readFailed", 502, body)
    return [line for line in body.get("data") or [] if gs1.split_anchor(line.get("anchor") or "")]


@app.post("/portal/api/export")
@require_login
def export_records():
    """Every record the portal can edit, one row per link, as XLSX or CSV. The browser sends the
    header labels and reference texts in the user's language."""
    data = request.get_json(silent=True) or {}
    labels = data.get("labels") or {}
    records = []
    for line in summary_with_links():
        entry = describe_entry(line)
        if entry["kind"] == "other" or not allowed(line["anchor"]):
            continue
        ai, value = gs1.split_anchor(line["anchor"])
        # the spreadsheet writes the qualifiers of the record's GS1 Digital Link, informative ones included
        records.append({"key": ai, "value": value,
                        "qualifiers": gs1.join_informative(entry.get("qualifiers", []), entry.get("informative", [])),
                        "description": line.get("itemDescription") or "",
                        "defaultLinkType": line.get("defaultLinktype"), "links": line.get("links") or []})
    rows = sheet.export_rows(records)
    stamp = time.strftime("%Y%m%d-%H%M")
    audit.info("user=%s action=export format=%s records=%d rows=%d", g.user, data.get("format"), len(records), len(rows))
    log_event("export", detail=f'{data.get("format")} records={len(records)}')
    if data.get("format") == "csv":
        body, mime, ext = sheet.write_csv(rows, labels), "text/csv; charset=utf-8", "csv"
    else:
        names = labels.get("linkTypes") or {}
        link_types = [(code, *(names.get(code) or [title, ""])[:2]) for code, _, title in gs1.LINK_TYPES]
        languages = [(code, (labels.get("languages") or {}).get(code, code)) for code in gs1.LANGUAGES]
        key_names = labels.get("keys") or {}
        keys = [(ai, key_names.get(ai, name)) for ai, (name, _) in gs1.PRIMARY_KEYS.items()]
        body = sheet.write_xlsx(rows, labels, link_types, languages, keys)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return Response(body, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="resolver-links-{stamp}.{ext}"'})


def _row_of(record: dict, position) -> int:
    """Spreadsheet row of a record's target at a 1-based position (for error messages); first row otherwise."""
    try:
        return record["links"][int(position) - 1]["row"]
    except (KeyError, IndexError, TypeError, ValueError):
        return record["rows"][0]


def _same_record(target: dict, doc: dict) -> bool:
    """Whether an imported record equals the one on the resolver (description, default and targets), so the
    preview can show it as unchanged.
    """
    def links(items):
        return sorted((l.get("linktype"), l.get("href"), l.get("title") or "", tuple(sorted(l.get("hreflang") or [])),
                       tuple(sorted(l.get("context") or []))) for l in items)
    return ((target.get("itemDescription") or "") == doc["itemDescription"]
            and target.get("defaultLinktype") == doc["defaultLinktype"]
            and gs1.pairs_from(target.get("informativeQualifiers")) == gs1.pairs_from(doc.get("informativeQualifiers"))
            and links(target.get("links") or []) == links(doc["links"]))


@app.post("/portal/api/import/preview")
@require_login
@role_required("editor")
def import_preview():
    """Reads a spreadsheet, validates every record with the editor's rules and compares it with the
    resolver. Nothing is written; the valid records are kept for /import/apply as a prepared job (jobs.py)."""
    data = request.get_json(silent=True) or {}
    try:
        content = base64.b64decode(data.get("content") or "", validate=True)
    except ValueError as exc:
        raise ValidationError("import.unreadable") from exc
    labels = data.get("labels") or {}
    rows = sheet.read_table(data.get("filename") or "", content)
    parsed, errors = sheet.parse_rows(rows, labels.get("aliases") or {}, labels.get("yes") or [], labels.get("no") or [])

    existing: dict[str, list[dict]] = {}
    for line in summary_with_links():
        existing.setdefault(line["anchor"], []).append(line)

    report, plan, file_defaults, to_check = [], [], {}, []
    rows_with_errors = {e["row"] for e in errors}
    for record in parsed:
        item = {"rows": record["rows"], "key": record["key"] or "01", "value": record["value"],
                "qualifiers": [list(p) for p in record["qualifiers"]],
                "description": record["description"], "links": len(record["links"])}
        if rows_with_errors.intersection(record["rows"]):
            item["action"] = "error"
            report.append(item)
            continue
        # A row of type gs1:defaultLink is the item's page of an exported record (ADR 0011): read back as the option
        landing = any(l["linkType"] == gs1.LANDING_TYPE for l in record["links"])
        record["links"] = [l for l in record["links"] if l["linkType"] != gs1.LANDING_TYPE]
        defaults = [l for l in record["links"] if l["default"]]
        if len(defaults) > 1:
            errors.append({"row": defaults[1]["row"], "code": "import.defaultMany",
                           "params": {"rows": ", ".join(str(l["row"]) for l in defaults)}})
            item["action"] = "error"
            report.append(item)
            continue
        # Row by row first, so that every wrong row is reported at once (the editor's rules below
        # stop at the first problem of a record).
        row_errors = []
        for q, v in record["qualifiers"]:
            if v.startswith("{") and v.endswith("}"):
                # a template such as {lotnumber}, created by other tools
                row_errors.append({"row": record["rows"][0], "code": "import.lotNotEditable", "params": {"value": v}})
        for link in record["links"]:
            if link["linkType"] not in gs1.LINK_TYPE_CODES:
                row_errors.append({"row": link["row"], "code": "link.typeRequired", "params": {"value": link["linkType"]}})
            try:
                gs1.normalise_url(link["url"], 0)
            except ValidationError as exc:
                row_errors.append({"row": link["row"], "code": exc.code, "params": {"url": link["url"]}})
            wrong = [tag for tag in link["hreflang"] if not gs1.normalise_language(tag)]
            if wrong:
                row_errors.append({"row": link["row"], "code": "link.languageRequired",
                                   "params": {"value": ", ".join(wrong)}})
        if row_errors:
            errors.extend(row_errors)
            item["action"] = "error"
            report.append(item)
            continue
        ordered = defaults + [l for l in record["links"] if not l["default"]]
        try:
            anchor, pairs, doc = build_document({
                "key": record["key"] or "01", "value": record["value"], "qualifiers": dict(record["qualifiers"]),
                "description": record["description"],
                "defaultLinkType": ordered[0]["linkType"] if ordered else None, "landingPage": landing,
                "links": [{"linkType": l["linkType"], "url": l["url"], "hreflang": l["hreflang"],
                           "title": l["title"]} for l in ordered]})
        except ValidationError as exc:
            params = dict(exc.params)
            row = _row_of({"links": ordered, "rows": record["rows"]}, params.get("position"))
            for name in ("first", "second"):
                if name in params:
                    params[name] = _row_of({"links": ordered, "rows": record["rows"]}, params[name])
            errors.append({"row": row, "code": exc.code, "params": params})
            item["action"] = "error"
            report.append(item)
            continue

        informative = gs1.pairs_from(doc.get("informativeQualifiers"))
        item.update(key=gs1.split_anchor(anchor)[0], value=gs1.split_anchor(anchor)[1],
                    qualifiers=[list(p) for p in pairs], informative=[list(p) for p in informative])
        if not allowed(anchor):
            errors.append({"row": record["rows"][0], "code": "access.prefixRow", "params": {"value": item["value"]}})
            item["action"] = "error"
            report.append(item)
            continue
        entries = existing.get(anchor, [])
        target = find_entry(entries, doc.get("qualifiers", []))
        others = [e for e in entries if e is not target]
        first = file_defaults.setdefault(anchor, (doc["defaultLinktype"], record["rows"][0]))
        if first[0] != doc["defaultLinktype"]:
            errors.append({"row": record["rows"][0], "code": "import.defaultConflict",
                           "params": {"linkType": first[0], "row": first[1]}})
            item["action"] = "error"
        elif others and others[0].get("defaultLinktype") != doc["defaultLinktype"]:
            errors.append({"row": record["rows"][0], "code": "default.sharedMismatch",
                           "params": {"linkType": others[0].get("defaultLinktype"),
                                      "entries": [describe_entry(e) for e in others]}})
            item["action"] = "error"
        elif target is None:
            item["action"] = "create"
        elif _same_record(target, doc):
            item["action"] = "unchanged"
        else:
            item["action"] = "update"
        if item["action"] == "update" and gs1.pairs_from(target.get("informativeQualifiers")) != informative:
            # a serial number whose batch or variant changes: shown in the preview
            item["informativeBefore"] = [list(p) for p in gs1.pairs_from(target.get("informativeQualifiers"))]
        if item["action"] in ("create", "update"):
            # less qualified records first, so a new key is created with its unqualified record
            plan.append({"anchor": anchor, "pairs": pairs, "doc": doc, "rows": record["rows"]})
            to_check.extend({"row": link["row"], "url": link["url"]} for link in record["links"])
        report.append(item)

    plan.sort(key=lambda p: (p["anchor"], len(p["pairs"])))
    # Section 2.5.9: keys that would be left with qualified records only. The preview lists them; on applying,
    # the user may create each key's own record with the targets of its first qualified record in the file.
    in_file = {p["anchor"] for p in plan if not p["pairs"]}
    key_records = {}
    for item in plan:
        anchor = item["anchor"]
        if (item["pairs"] and anchor not in in_file and anchor not in key_records and gs1.has_key_level(gs1.split_anchor(anchor)[0])
                and not any(not e.get("qualifiers") for e in existing.get(anchor, []))):
            doc = {k: v for k, v in item["doc"].items() if k not in ("qualifiers", "informativeQualifiers")}
            if doc["defaultLinktype"] == gs1.LANDING_TYPE:     # the key's own page, not the qualified record's
                doc["links"] = [l for l in doc["links"] if not gs1.is_landing(l)] + [landing_link(anchor, [])]
            key_records[anchor] = {"anchor": anchor, "pairs": [], "doc": doc, "rows": item["rows"]}
    for item in report:
        anchor = gs1.anchor_for(item["key"], item["value"]) if item.get("action") in ("create", "update") else None
        if anchor in key_records:
            item["noKeyRecord"] = True
    token = jobs.create("import", g.user, "prepared", len(plan), plan=_storable_plan(plan),
                        keyRecords=_storable_plan(key_records.values()), results=[])
    counts = {action: sum(1 for i in report if i["action"] == action)
              for action in ("create", "update", "unchanged", "error")}
    errors.sort(key=lambda e: e["row"])
    return jsonify({"token": token, "records": report, "errors": errors, "counts": counts, "links": to_check,
                    "keysWithoutRecord": [{"key": gs1.split_anchor(k["anchor"])[0], "value": gs1.split_anchor(k["anchor"])[1],
                                           "rows": k["rows"], "description": k["doc"]["itemDescription"]}
                                          for k in key_records.values()]})


def _storable_plan(plan) -> list[dict]:
    """An import plan as stored in its job: qualifier pairs as lists (BSON has no tuples)."""
    return [{**item, "pairs": [list(p) for p in item["pairs"]]} for item in plan]


def run_import_job(job: dict, reporter: "jobs.Reporter") -> None:
    """Worker: writes the records of a confirmed import one by one with the editor's call sequence, from the
    first one not yet done (a job interrupted by a worker that stopped continues where it was; writing a
    record again is safe: the data entry API ends in the same state). Logs the import when done.
    """
    user = job["user"]
    plan = job["plan"]
    results = list(job.get("results") or [])[:job.get("done", 0)]
    with app.test_request_context():
        set_scope(user, users.get(user) or {})          # store_record logs and records who changed it
        for index in range(len(results), len(plan)):
            reporter.check_stop()                       # between records: a stopping worker hands the job back
            item = plan[index]
            pairs = [tuple(p) for p in item["pairs"]]
            ai, value = gs1.split_anchor(item["anchor"])
            result = {"key": ai, "value": value, "qualifiers": [list(p) for p in pairs], "rows": item["rows"],
                      "description": item["doc"]["itemDescription"]}
            try:
                # checked again here: a prefix may have changed hands, or the user lost it, since the preview
                if not allowed(item["anchor"]):
                    raise ValidationError("access.prefix")
                result["action"] = "created" if store_record(item["anchor"], pairs, item["doc"]) else "updated"
            except (ValidationError, UpstreamError) as exc:
                result.update(action="failed", code=exc.code, params=exc.params)
            reporter.record(index + 1, result)
            results.append(result)
        counts = {a: sum(1 for r in results if r["action"] == a) for a in ("created", "updated", "failed")}
        audit.info("user=%s action=import created=%d updated=%d failed=%d", user,
                   counts["created"], counts["updated"], counts["failed"])
        log_event("import", detail="created={created} updated={updated} failed={failed}".format(**counts))
    reporter.finish()
    notify.send(user, "import-finished", **counts)     # when the user switched "My background jobs" on


@app.post("/portal/api/import/apply")
@require_login
@role_required("editor")
def import_apply():
    """Queues a previewed import (by its token) for the worker; the browser then polls /import/status."""
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    job = jobs.get(token, g.user, "import")
    if not job:
        raise ValidationError("import.expired")
    if job["state"] != "prepared":
        raise ValidationError("import.alreadyApplied")
    plan = job["plan"]
    if data.get("createKeyRecords") and job.get("keyRecords"):
        # the keys' own records go first (section 2.5.9: a default link above every qualified record)
        plan = job["keyRecords"] + plan
    queued = jobs.queue_prepared(token, g.user, plan=plan, total=len(plan))
    if not queued:                                      # applied (or expired) by another request meanwhile
        raise ValidationError("import.alreadyApplied" if jobs.get(token, g.user, "import") else "import.expired")
    worker.wake()
    return jsonify({"token": token, "total": queued["total"]}), 202


@app.get("/portal/api/import/status")
@require_login
@role_required("editor")
def import_status():
    """Progress of an import and, when finished, the result of every record. "stalled" tells a job waiting in
    the queue with no worker running."""
    job = jobs.get(request.args.get("token", ""), g.user, "import")
    if not job or job["state"] == "prepared":
        raise ValidationError("import.expired")
    return jsonify({**jobs.status(job), "results": job.get("results", []) if job["state"] == "finished" else []})


# --------------------------------------------------------------------------- link checker
def _full_check_setting(tenant: str | None) -> str:
    """The setting that keeps the last "check every record" of a scope: one per tenant, one for the operator."""
    return f"lastFullCheck:{tenant}" if tenant else "lastFullCheck"


def _last_full_check(tenant: str | None) -> dict:
    """Result of the latest "check every record" of a scope, shown in the record list."""
    value = store.get_setting(_full_check_setting(tenant)) or {}
    # stored as pairs: record keys contain "/" and "." and are not used as field names
    return {**value, "records": dict(value.get("records") or [])} if value else {}


def _save_last_full_check(tenant: str | None, value: dict) -> None:
    """Keeps the result of a "check every record" of a scope for every replica."""
    store.set_setting(_full_check_setting(tenant), {**value, "records": [[k, v] for k, v in value["records"].items()]})


MAX_CHECK_URLS = 5000


@app.post("/portal/api/links/check")
@require_login
@role_required("editor")
def check_links():
    """Checks the few targets of one record (editor); answers when all are done."""
    urls = [u for u in (request.get_json(silent=True) or {}).get("urls") or [] if isinstance(u, str)][:MAX_LINKS]
    results = linkcheck.check_many(urls)
    return jsonify({"results": [results[u] for u in dict.fromkeys(urls) if u in results]})


def run_link_job(job: dict, reporter: "jobs.Reporter") -> None:
    """Worker: checks every address of a link check once and maps problems back to records (scope "all")
    or to the addresses sent (editor and import preview). An interrupted check starts again from the first
    address; the checker's cache (CACHE_SECONDS) answers the ones already checked.
    """
    urls = {item["url"]: item["records"] for item in job["urls"]}
    last = [0.0]

    def progress(done, total):
        reporter.check_stop()
        now = time.monotonic()
        if done == total or now - last[0] >= 1:          # at most one write a second
            reporter.progress(done, total)
            last[0] = now

    results = linkcheck.check_many(list(urls), progress)
    problems = {u: r for u, r in results.items() if not r["ok"]}
    fields = {"problems": list(problems.values())}
    if job["scope"] == "all":
        by_record = {}
        for url, result in problems.items():
            for key in urls[url]:
                by_record.setdefault(key, []).append(result)
        # record keys contain "/" and ".", so they are values, not field names
        fields["records"] = [{"record": key, "problems": found} for key, found in by_record.items()]
        _save_last_full_check(job.get("tenant"), {"checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "records": by_record, "urls": len(results), "user": job["user"]})
        audit.info("user=%s action=linkcheck urls=%d problems=%d", job["user"], len(results), len(problems))
    reporter.finish(**fields)
    if job["scope"] == "all":                         # only the check of every record, which can take long
        notify.send(job["user"], "linkcheck-finished", urls=len(results), problems=len(problems))


@app.post("/portal/api/links/jobs")
@require_login
@role_required("editor")
def start_link_job():
    """Queues a check of many targets for the worker: every record's ("scope": "all") or a list of URLs
    (spreadsheet import preview). Poll /links/jobs/<token>."""
    data = request.get_json(silent=True) or {}
    if data.get("scope") == "all":
        urls: dict[str, list[str]] = {}
        for line in summary_with_links():
            entry = describe_entry(line)
            if entry["kind"] == "other" or not allowed(line["anchor"]):
                continue
            key = f'{line["anchor"]}|{entry.get("path", "")}'
            for link in line.get("links") or []:
                if not gs1.is_landing(link):          # the item's page is the resolver's own (ADR 0011)
                    urls.setdefault(link.get("href"), []).append(key)
        scope = "all"
    else:
        urls = {u: [] for u in data.get("urls") or [] if isinstance(u, str) and u}
        scope = "list"
    if len(urls) > MAX_CHECK_URLS:
        raise ValidationError("linkcheck.tooMany", max=MAX_CHECK_URLS)
    # addresses contain "." and are values, not field names
    token = jobs.create("linkcheck", g.user, "queued", len(urls), scope=scope, tenant=g.tenant,
                        urls=[{"url": url, "records": keys} for url, keys in urls.items()])
    worker.wake()
    return jsonify({"token": token, "total": len(urls)}), 202


@app.get("/portal/api/links/jobs/<token>")
@require_login
@role_required("editor")
def link_job_status(token):
    """Progress of a link check and, when finished, its problems."""
    job = jobs.get(token, g.user, "linkcheck")
    if not job:
        raise ValidationError("linkcheck.expired")
    out = jobs.status(job)
    if job["state"] == "finished":
        out["problems"] = job.get("problems", [])
        if job["scope"] == "all":
            out.update(_last_full_check(job.get("tenant")))
            out["records"] = {item["record"]: item["problems"] for item in job.get("records") or []}
    return jsonify(out)


@app.get("/portal/api/links/last")
@require_login
def last_link_check():
    """Result of the last check of every record, limited to the records the user may see."""
    last = _last_full_check(g.tenant)
    if not last:
        return jsonify({})
    records = {k: v for k, v in last.get("records", {}).items() if allowed(k.split("|")[0])}
    return jsonify({**last, "records": records})


# --------------------------------------------------------------------------- governance
def temporary_password() -> str:
    """16 characters, easy to type from a message: no look-alike characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def tenant_name(tenant_id: str | None) -> str:
    """The name of a tenant of this request ("" for the operator, the id for a tenant removed since)."""
    if not tenant_id:
        return ""
    return next((t["name"] for t in getattr(g, "tenants", None) or [] if t["id"] == tenant_id), tenant_id)


def managed_account(username: str) -> dict:
    """The account an administrator acts upon: any account for a server administrator, the accounts of his own
    tenant for a tenant administrator (any other answers "unknown user", so that names do not leak)."""
    account = users.get(username)
    if not account or (not g.server_admin and account.get("tenant") != g.account_tenant):
        raise users.UserError("users.unknown", user=username)
    return account


@app.get("/portal/api/users")
@require_login
@admin_required
def list_users():
    """The users an administrator manages, without password hashes: every user for a server administrator (with
    the tenants, for the organisation column and selector), the tenant's users for a tenant administrator."""
    accounts = sorted(users.load().items())
    if not g.server_admin:
        accounts = [(n, a) for n, a in accounts if a.get("tenant") == g.account_tenant]
    return jsonify({"users": [{**users.public(name, account), "tenantName": tenant_name(account.get("tenant"))}
                              for name, account in accounts],
                    "roles": list(users.ROLES),
                    "tenants": [{"id": t["id"], "name": t["name"], "prefixes": t["prefixes"]} for t in g.tenants]
                               if g.server_admin else []})


@app.post("/portal/api/users")
@require_login
@admin_required
def create_user():
    """Creates a user (administrators): with mail on, an address and "invite", the user gets an invitation by
    e-mail and chooses his own password; otherwise a temporary password, shown once in the answer. A server
    administrator chooses the tenant (none: the operator); a tenant administrator creates users of his tenant."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    tenant = (str(data.get("tenant") or "").strip() or None) if g.server_admin else g.account_tenant
    role, prefixes = str(data.get("role", "")), data.get("prefixes") or []
    detail = f'{username} role={data.get("role")} prefixes={",".join(prefixes)}'
    language = data.get("language") or (users.get(g.user) or {}).get("language")   # the inviter's, until the user signs in
    if data.get("invite") and mail.enabled() and str(data.get("email") or "").strip():
        users.create(username, None, role, prefixes, tenant=tenant, email=data.get("email"), language=language)
        if send_link(username, "invite", "invite", language=language):
            audit.info("user=%s action=user-create target=%s role=%s tenant=%s invited", g.user, username, role,
                       tenant or "-")
            log_event("user-create", tenant=tenant, detail=detail + " invited")
            return message("users.invited", 201, params={"user": username})
        password = temporary_password()                 # the invitation could not be queued: as before
        users.set_password(username, password, must_change=True)
    else:
        password = temporary_password()
        users.create(username, password, role, prefixes, tenant=tenant, email=data.get("email"), language=language)
    audit.info("user=%s action=user-create target=%s role=%s tenant=%s", g.user, username, data.get("role"), tenant or "-")
    log_event("user-create", tenant=tenant, detail=detail)
    return message("users.created", 201, params={"user": username}, password=password)


@app.put("/portal/api/users/<username>")
@require_login
@admin_required
def update_user(username):
    """Changes the role, prefixes, e-mail or status of a user; administrators cannot disable or demote themselves."""
    data = request.get_json(silent=True) or {}
    target = managed_account(username)
    if username == g.user and (data.get("disabled") or data.get("role") not in (None, "admin")):
        raise users.UserError("users.notSelf")          # an administrator cannot lock himself out
    account = users.update(username, role=data.get("role"), prefixes=data.get("prefixes"),
                           disabled=data.get("disabled"), email=data.get("email"))
    audit.info("user=%s action=user-update target=%s", g.user, username)
    log_event("user-update", tenant=target.get("tenant"),
              detail=f'{username} role={account["role"]} disabled={account["disabled"]} '
                     f'prefixes={",".join(account["prefixes"])}'
                     + (" email-changed" if account["email"] != target.get("email") else ""))
    if account["email"] != target.get("email"):        # security: to the old address and to the new one
        when = notify.now_text()
        if target.get("email"):
            notify.send(username, "email-changed-old", to=target["email"], when=when)
        if account["email"]:
            notify.send(username, "email-changed-new", when=when)
    return message("users.updated", 200, params={"user": username})


@app.post("/portal/api/users/<username>/reset")
@require_login
@admin_required
def reset_user(username):
    """Resets a user's password (administrators). With mail on and an address: the password stops working at once
    (every session ends) and a link to choose a new one goes by e-mail (an invited user gets a new invitation).
    Otherwise a new temporary password, shown once, and the user's sessions end."""
    target = managed_account(username)
    if mail.enabled() and target.get("email") and notify.reachable(target) and username != g.user:
        invited = bool(target.get("invited"))
        if not invited:
            users.clear_password(username)
        if send_link(username, "invite" if invited else "reset", "invite" if invited else "password-reset-admin",
                     language=target.get("language")):
            audit.info("user=%s action=user-reset target=%s by=link", g.user, username)
            log_event("user-reset", tenant=target.get("tenant"), detail=f"{username} link")
            return message("users.resetSent", 200, params={"user": username})
    password = temporary_password()
    users.set_password(username, password, must_change=True)
    audit.info("user=%s action=user-reset target=%s", g.user, username)
    log_event("user-reset", tenant=target.get("tenant"), detail=username)
    return message("users.reset", 200, params={"user": username}, password=password)


@app.delete("/portal/api/users/<username>")
@require_login
@admin_required
def remove_user(username):
    """Removes a user; the user's changes stay in the journal (administrators)."""
    if username == g.user:
        raise users.UserError("users.notSelf")
    target = managed_account(username)
    users.remove(username)
    tokens.purge(username)                              # his links stop working; queued messages are skipped
    audit.info("user=%s action=user-remove target=%s", g.user, username)
    log_event("user-remove", tenant=target.get("tenant"), detail=username)
    return message("users.removed", 200, params={"user": username})


# --------------------------------------------------------------------------- API keys (administrators)
def scope_label(tenant_id: str | None, language: str | None = None) -> str:
    """How a message names the scope of a key: the organisation's name, or the operator's records."""
    if tenant_id:
        return tenant_name(tenant_id) or tenant_id
    return "os cadastros do operador" if (language or "").startswith("pt") else "the operator's records"


@app.get("/portal/api/keys")
@require_login
@admin_required
def list_api_keys():
    """The API keys of the administrator's own scope (his organisation, or the operator's for a server
    administrator, also during support access), newest first, without their hashes."""
    return jsonify({"keys": [apikeys.public(d) for d in apikeys.load(g.account_tenant)],
                    "scopes": list(apikeys.SCOPES), "maxDays": apikeys.max_days(),
                    "defaultDays": apikeys.DEFAULT_DAYS, "ratePerMinute": apikeys.rate_per_minute()})


@app.post("/portal/api/keys")
@require_login
@admin_required
def create_api_key():
    """Creates an API key for the administrator's own scope; the full key is in the answer, once
    (Documentation/adr/0005-tenant-api.md)."""
    data = request.get_json(silent=True) or {}
    key, doc = apikeys.create(data.get("name"), data.get("scopes"), data.get("days"), data.get("prefixes"),
                              g.account_tenant, g.user)
    audit.info("user=%s action=api-key-create key=%s tenant=%s", g.user, doc["_id"], g.account_tenant or "-")
    log_event("api-key-create", tenant=g.account_tenant,
              detail=f'{doc["_id"]} {doc["name"]} scopes={",".join(doc["scopes"])} prefixes={",".join(doc["prefixes"])} '
                     f'expires={store.iso(doc["expiresAt"])[:10]}')
    language = (users.get(g.user) or {}).get("language")
    notify.send(g.user, "api-key-created", name=doc["name"], id=doc["_id"], scope=scope_label(g.account_tenant, language),
                scopes=", ".join(doc["scopes"]), when=notify.now_text(),
                expires=store.iso(doc["expiresAt"]).replace("T", " ")[:16])
    return message("apikeys.created", 201, params={"name": doc["name"]}, key=key, item=apikeys.public(doc))


@app.delete("/portal/api/keys/<key_id>")
@require_login
@admin_required
def revoke_api_key(key_id):
    """Revokes an API key of the administrator's own scope; it stops working at once."""
    doc = apikeys.revoke(key_id, g.account_tenant, g.user)
    audit.info("user=%s action=api-key-revoke key=%s", g.user, doc["_id"])
    log_event("api-key-revoke", tenant=g.account_tenant, detail=f'{doc["_id"]} {doc["name"]}')
    return message("apikeys.revoked", 200, params={"name": doc["name"]})


def notify_expiring_keys() -> int:
    """Housekeeping of the worker (hourly): tells each creator of a key that expires within a week, once."""
    told = 0
    for doc in apikeys.expiring():
        creator = users.get(doc.get("createdBy") or "")
        if not creator:
            continue
        with app.test_request_context():
            g.tenants = tenants.load()
            sent = notify.send(doc["createdBy"], "api-key-expiring", name=doc["name"], id=doc["_id"],
                               scope=scope_label(doc.get("tenant"), creator.get("language")),
                               expires=store.iso(doc["expiresAt"]).replace("T", " ")[:16])
        told += int(sent)
    return told


# --------------------------------------------------------------------------- tenants (server administrators)
def record_owners() -> dict | None:
    """How many records each tenant holds ({tenant id or None: count}), from the resolver's summary; None when
    the resolver cannot be read (the tenants screen still works)."""
    try:
        status, body = resolver("GET", "/summary")
    except UpstreamError:
        return None
    if status == 404:
        return {}
    if status != 200 or not isinstance(body, dict):
        return None
    counts: dict = {}
    for line in body.get("data") or []:
        anchor = line.get("anchor") or ""
        if gs1.split_anchor(anchor):
            owner = tenants.owner(anchor, g.tenants)
            counts[owner] = counts.get(owner, 0) + 1
    return counts


@app.get("/portal/api/tenants")
@require_login
@server_admin_required
def list_tenants():
    """Every tenant with its number of users and records, and the records no tenant holds (the operator's)."""
    members: dict = {}
    for account in users.load().values():
        if account.get("tenant"):
            members[account["tenant"]] = members.get(account["tenant"], 0) + 1
    owners = record_owners()
    return jsonify({"tenants": [{**t, "users": members.get(t["id"], 0),
                                 "records": None if owners is None else owners.get(t["id"], 0)} for t in g.tenants],
                    "operatorRecords": None if owners is None else owners.get(None, 0),
                    "support": g.support})


@app.post("/portal/api/tenants")
@require_login
@server_admin_required
def create_tenant():
    """Creates a tenant with its GS1 Company Prefixes (server administrators)."""
    data = request.get_json(silent=True) or {}
    tenant = tenants.create(data.get("name"), data.get("prefixes") or [], g.user)
    audit.info("user=%s action=tenant-create tenant=%s prefixes=%s", g.user, tenant["id"], ",".join(tenant["prefixes"]))
    log_event("tenant-create", tenant=tenant["id"], detail=f'{tenant["name"]} prefixes={",".join(tenant["prefixes"])}')
    return message("tenants.created", 201, params={"name": tenant["name"]}, tenant=tenant)


@app.put("/portal/api/tenants/<tenant_id>")
@require_login
@server_admin_required
def update_tenant(tenant_id):
    """Renames a tenant, changes its prefixes, disables or enables it (server administrators)."""
    data = request.get_json(silent=True) or {}
    before, after = tenants.update(tenant_id, name=data.get("name"), prefixes=data.get("prefixes"),
                                   disabled=data.get("disabled"))
    changes = [f"{field}={','.join(after[field]) if field == 'prefixes' else after[field]}"
               for field in ("name", "prefixes", "disabled") if before[field] != after[field]]
    audit.info("user=%s action=tenant-update tenant=%s %s", g.user, tenant_id, " ".join(changes))
    log_event("tenant-update", tenant=tenant_id, detail=" ".join(changes) or None)
    return message("tenants.updated", 200, params={"name": after["name"]})


@app.delete("/portal/api/tenants/<tenant_id>")
@require_login
@server_admin_required
def remove_tenant(tenant_id):
    """Removes a tenant without users; its prefixes and records go back to the operator (server administrators)."""
    tenant = tenants.remove(tenant_id)
    if session.get("support") == tenant_id:
        session.pop("support", None)
    audit.info("user=%s action=tenant-remove tenant=%s", g.user, tenant_id)
    log_event("tenant-remove", tenant=tenant_id, detail=f'{tenant["name"]} prefixes={",".join(tenant["prefixes"])}')
    return message("tenants.removed", 200, params={"name": tenant["name"]})


SUPPORT_REASON = (5, 200)


@app.post("/portal/api/support")
@require_login
@server_admin_required
def open_support():
    """Opens read-only support access to one tenant, with a reason recorded in the tenant's audit trail
    (Documentation/adr/0002-tenants.md, section 3.4). Opening another closes the first."""
    data = request.get_json(silent=True) or {}
    tenant = next((t for t in g.tenants if t["id"] == data.get("tenant")), None)
    if not tenant:
        raise users.UserError("tenants.unknown")
    reason = " ".join(gs1.without_invisible(str(data.get("reason") or "")).split())
    if not (SUPPORT_REASON[0] <= len(reason) <= SUPPORT_REASON[1]) or not reason.isprintable():
        raise ValidationError("support.reason", min=SUPPORT_REASON[0], max=SUPPORT_REASON[1])
    if g.support and g.support != tenant["id"]:
        log_event("support-close", tenant=g.support, detail=f'switched to {tenant["name"]}')
    session["support"] = tenant["id"]
    audit.info("user=%s action=support-open tenant=%s", g.user, tenant["id"])
    log_event("support-open", tenant=tenant["id"], detail=reason)
    return message("support.opened", 200, params={"name": tenant["name"]})


@app.delete("/portal/api/support")
@require_login
@server_admin_required
def close_support():
    """Closes support access (nothing to do when none is open)."""
    if g.support:
        audit.info("user=%s action=support-close tenant=%s", g.user, g.support)
        log_event("support-close", tenant=g.support)
    session.pop("support", None)
    return message("support.closed")


@app.get("/portal/api/history")
@require_login
def record_history():
    """The latest versions of one record made while it belonged to the scope of the request, with their content,
    for the editor's History panel."""
    anchor = request_key(request.args)
    check_access(anchor)
    pairs, _ = request_record(request.args, anchor)
    versions = journal.for_record(anchor, gs1.qualifier_path(pairs, encode=False), tenant=g.tenant)
    return jsonify({"versions": versions})


def _audit_events():
    """Journal events matching the audit filters of the request, in the audit trail of the request's scope
    (a tenant's; during support access the tenant's; for a server administrator the operator's and what operator
    users did to tenants), limited to the user's own prefixes."""
    args = request.args
    scope = journal.scope_query(g.tenant, operator_view=g.server_admin and not g.support)
    events = journal.search(user=args.get("user") or None, since=args.get("from") or None,
                            until=args.get("to") or None, text=args.get("q") or None,
                            allowed=lambda anchor: gs1.within_prefixes(anchor, g.prefixes), scope=scope,
                            limit=min(int(args.get("limit", 500) or 500), 5000))
    for event in events:
        if event.get("tenant"):
            event["tenantName"] = tenant_name(event["tenant"])
    return events


@app.get("/portal/api/audit")
@require_login
@admin_required
def audit_trail():
    """The audit trail as JSON, newest first (administrators)."""
    return jsonify({"events": _audit_events()})


@app.get("/portal/api/audit.csv")
@require_login
@admin_required
def audit_csv():
    """The audit trail as CSV for Excel (UTF-8 with BOM, ';', cells protected against formulas)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["at", "user", "action", "anchor", "qualifiers", "detail", "organisation", "by_operator"])
    for event in _audit_events():                  # user names of failed sign-ins are typed by anyone
        writer.writerow([sheet.protect(event.get(k, "")) for k in ("at", "user", "action", "anchor", "qpath", "detail",
                                                                   "tenantName")]
                        + ["yes" if event.get("byOperator") else ""])
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(("\ufeff" + out.getvalue()).encode("utf-8"), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="portal-audit-{stamp}.csv"'})


# --------------------------------------------------------------------------- request log (ADR 0006)
REQUEST_CSV_COLUMNS = ["at", "method", "form", "epc", "key", "value", "qualifiers", "attributes", "linkType", "status",
                       "outcome", "level", "target", "ms", "language", "device", "referrer", "country", "path"]


@app.errorhandler(requestlog.FilterError)
def on_filter_error(err):
    """A filter of the request log cannot be read: 422 with the message code."""
    return message(err.code, 422, params=err.params)


def request_log_scope() -> tuple[dict, bool]:
    """The events the request reaches (Documentation/adr/0006-resolver-request-log.md, decision 7) and whether it is
    the whole installation (a server administrator outside support access)."""
    whole = log_sees_everything()
    return requestlog.scope_filter(g.tenants, g.tenant, g.prefixes, whole), whole


def log_sees_everything() -> bool:
    """A server administrator outside support access and not limited to prefixes sees the whole installation's
    requests and API calls."""
    return bool(g.server_admin and not g.support and not g.prefixes)


def _log_unavailable(exc: Exception):
    log.warning("Request log not read: %s", exc)
    return message("requests.unavailable", 503)


@app.get("/portal/api/requests")
@require_login
def list_requests():
    """The newest resolver requests in the scope of the request, with the filters of the Requests screen."""
    scope, whole = request_log_scope()
    try:
        found = requestlog.list_events(request.args, scope, organisations=g.tenants if whole else None)
    except PyMongoError as exc:
        return _log_unavailable(exc)
    return jsonify(**found, days=requestlog.log_days(), whole=whole)


@app.get("/portal/api/requests.csv")
@require_login
def requests_csv():
    """The resolver requests matching the filters as CSV for Excel (UTF-8 with BOM, ';', cells protected against
    formulas), at most requestlog.MAX_EXPORT rows. A journal event: the export of the log."""
    scope, whole = request_log_scope()
    try:
        found = requestlog.list_events(request.args, scope, limit=requestlog.MAX_EXPORT,
                                       organisations=g.tenants if whole else None)
    except PyMongoError as exc:
        return _log_unavailable(exc)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    columns = REQUEST_CSV_COLUMNS + (["organisation"] if whole else [])
    writer.writerow(columns)
    for event in found["events"]:                   # paths of invalid requests and referrers are typed by anyone
        writer.writerow([sheet.protect(" ".join(event[c]) if isinstance(event.get(c), list) else
                                       ("" if event.get(c) is None else event[c])) for c in columns])
    log_event("requests-export", detail=f'rows={len(found["events"])}')
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(("\ufeff" + out.getvalue()).encode("utf-8"), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="resolver-requests-{stamp}.csv"'})


@app.get("/portal/api/requests/daily")
@require_login
def requests_per_day():
    """Requests per day in the scope of the request (30 days by default, at most 400), oldest first."""
    scope, whole = request_log_scope()
    try:
        days = int(request.args.get("days") or 30)
    except ValueError:
        return message("requests.badFilter", 422, params={"name": "days"})
    try:
        return jsonify(days=requestlog.per_day(scope, whole, days), timeZone=str(requestlog.zone()))
    except PyMongoError as exc:
        return _log_unavailable(exc)


@app.get("/portal/api/requests/api")
@require_login
@admin_required
def tenant_api_calls():
    """The tenant API's calls (Documentation/adr/0006-resolver-request-log.md, decision 8): an organisation's for its
    administrators (during support access, that organisation's), every organisation's for a server administrator."""
    whole = log_sees_everything()
    names = apikeys.names(g.tenant, every=whole)
    try:
        return jsonify(**requestlog.list_api_calls(request.args, g.tenant, whole, names, g.tenants), whole=whole)
    except PyMongoError as exc:
        return _log_unavailable(exc)


# --------------------------------------------------------------------------- domains (ADR 0009)
def _installation_host() -> str:
    return (RESOLVER_PUBLIC_URL.split("://", 1)[-1].split("/", 1)[0].split(":")[0]).lower()


def domain_scope() -> tuple[str | None, bool]:
    """Whose domains the request manages (the account's own scope, as API keys; during support access the
    organisation's, read only) and whether it sees every domain (a server administrator outside support access)."""
    if g.support:
        return g.support, False
    return g.account_tenant, bool(g.server_admin)


def _sample_anchor(tenant: str | None) -> str | None:
    """A record of the scope, for checking a redirecting domain."""
    try:
        for record in visible_records():
            if record.get("kind") != "other":
                return record["anchor"]
    except UpstreamError:
        pass
    return None


@app.get("/portal/api/domains")
@require_login
@admin_required
def list_domains():
    """The domains of the administrator's scope (a server administrator: every domain, with its organisation)."""
    tenant, every = domain_scope()
    names = {t["id"]: t["name"] for t in g.tenants}
    docs = domains.load(tenant, every=every)
    return jsonify(domains=[domains.public(d, names if every else None) for d in docs], every=every,
                   readOnly=bool(g.support), installation=_installation_host(), max=domains.MAX_PER_SCOPE,
                   txtName=domains.TXT_NAME, prefixes=(tenants.get(tenant) or {}).get("prefixes", [])
                   if tenant else [], modes=list(domains.MODES))


class ReadOnlySupport(Exception):
    """A change asked during support access, which is read only."""


@app.errorhandler(ReadOnlySupport)
def on_read_only_support(err):
    return message("domains.readOnly", 403)


def _domain_write_scope() -> str | None:
    """The scope a change of domains applies to: the account's own (never during support access)."""
    if g.support:
        raise ReadOnlySupport()
    return g.account_tenant


@app.post("/portal/api/domains")
@require_login
@admin_required
def create_domain():
    data = request.get_json(silent=True) or {}
    tenant = _domain_write_scope()
    doc = domains.create(data.get("domain"), data.get("mode"), data.get("stem"), tenant, g.user, _installation_host())
    log_event("domain-create", tenant=tenant, detail=f'{doc["_id"]} mode={doc["mode"]} stem={doc["stem"] or "-"}')
    return message("domains.created", 201, params={"domain": doc["_id"]}, item=domains.public(doc))


@app.put("/portal/api/domains/<name>")
@require_login
@admin_required
def update_domain(name):
    data = request.get_json(silent=True) or {}
    tenant = _domain_write_scope()
    before, after = domains.update(name, tenant, mode=data.get("mode"), stem=data.get("stem"),
                                   default_prefixes=data.get("defaultFor"))
    log_event("domain-update", tenant=tenant,
              detail=f'{after["_id"]} mode={after.get("mode")} stem={after.get("stem") or "-"} '
                     f'default={",".join(after.get("defaultFor") or []) or "-"}')
    return message("domains.saved", 200, params={"domain": after["_id"]}, item=domains.public(after))


@app.post("/portal/api/domains/<name>/verify")
@require_login
@admin_required
def verify_domain(name):
    tenant = _domain_write_scope()
    was = domains.get(name, tenant).get("verified")
    doc = domains.verify(name, tenant)
    if not was:
        log_event("domain-verify", tenant=tenant, detail=doc["_id"])
    return message("domains.verified", 200, params={"domain": doc["_id"]}, item=domains.public(doc))


@app.post("/portal/api/domains/<name>/check")
@require_login
@admin_required
def check_domain(name):
    tenant = _domain_write_scope()
    doc = domains.check(name, tenant, RESOLVER_PUBLIC_URL, _sample_anchor(tenant))
    result = doc["check"]
    return message("domains.checkOk" if result["ok"] else result["problem"], 200,
                   params={"domain": doc["_id"], "detail": result.get("detail") or "", "url": result["url"]},
                   item=domains.public(doc))


@app.delete("/portal/api/domains/<name>")
@require_login
@admin_required
def remove_domain(name):
    tenant = _domain_write_scope()
    doc = domains.remove(name, tenant)
    log_event("domain-remove", tenant=tenant, detail=doc["_id"])
    return message("domains.removed", 200, params={"domain": doc["_id"]})


# --------------------------------------------------------------------------- the item's page (ADR 0011)
def branding_scope() -> tuple[str | None, bool]:
    """Whose brands the request manages (the account's own scope; during support access read only) and whether it is
    a server administrator outside support access (the operator's prefixes and the installation's default)."""
    if g.support:
        return g.support, False
    return g.account_tenant, bool(g.server_admin)


@app.get("/portal/api/branding")
@require_login
@admin_required
def list_branding():
    tenant, server = branding_scope()
    held = (tenants.get(tenant) or {}).get("prefixes", []) if tenant else []
    return jsonify(brands=[branding.public(d) for d in branding.load(tenant)], readOnly=bool(g.support),
                   prefixes=held, installationDefault=server, maxLogoKB=branding.MAX_LOGO_BYTES // 1024,
                   verifiedOn=bool((os.environ.get("RESOLVER_VERIFIED_BY_GS1_URL", "") or "").strip()))


@app.put("/portal/api/branding/<prefix>")
@require_login
@admin_required
def save_branding(prefix):
    if g.support:
        raise ReadOnlySupport()
    tenant, server = branding_scope()
    doc = branding.save(prefix, request.get_json(silent=True) or {}, tenant, server, g.user)
    log_event("branding-save", tenant=tenant, detail=f'{doc["_id"]} name={doc.get("name") or "-"} '
              f'logo={"yes" if doc.get("logo") else "no"} verified={doc.get("verified")}')
    return message("branding.saved", 200, params={"prefix": doc["_id"]}, item=branding.public(doc))


@app.get("/portal/api/branding/<prefix>/logo")
@require_login
@admin_required
def branding_logo(prefix):
    """The logo of one of the scope's brands, for the screen's preview."""
    found = branding.logo(prefix, branding_scope()[0])
    if not found:
        return message("branding.unknown", 404)
    response = Response(bytes(found["data"]), mimetype=found["type"])
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.delete("/portal/api/branding/<prefix>")
@require_login
@admin_required
def remove_branding(prefix):
    if g.support:
        raise ReadOnlySupport()
    tenant, server = branding_scope()
    doc = branding.remove(prefix, tenant, server)
    log_event("branding-remove", tenant=tenant, detail=doc["_id"])
    return message("branding.removed", 200, params={"prefix": doc["_id"]})


# --------------------------------------------------------------------------- overview (ADR 0007)
@app.errorhandler(overview.PeriodError)
def on_period_error(err):
    """A period that is not 7, 30 or 90 days: 422."""
    return message("overview.badPeriod", 422, params={"periods": list(overview.PERIODS)})


def overview_records() -> list[dict] | None:
    """The records of the scope for the overview, or None when the resolver cannot be read."""
    try:
        return visible_records()
    except UpstreamError as exc:
        log.warning("Overview without records: %s", exc)
        return None


def overview_last_check() -> dict:
    """The last check of every link of the scope, limited to the records the user may see."""
    last = _last_full_check(g.tenant)
    if not last:
        return {}
    return {**last, "records": {k: v for k, v in last.get("records", {}).items() if allowed(k.split("|")[0])}}


def overview_operation(last_check: dict) -> dict:
    """The operation group: the last check of every link; for server administrators also the worker, e-mail and the
    request log's counts."""
    out = {"lastCheck": last_check.get("checkedAt"), "logDays": requestlog.log_days()}
    alerts = monitor.states(g.tenant, g.server_admin and not g.support)
    out["alerts"] = alerts["active"]
    if g.server_admin and not g.support:
        out["checks"] = alerts["checks"]
    if g.server_admin:
        try:
            out["worker"] = jobs.workers_alive()
        except PyMongoError:
            out["worker"] = 0
        out["mail"] = "on" if mail.enabled() else "off"
        out["countedUntil"] = store.get_setting(requestlog.SETTING_FINAL)
    return out


def overview_data(days, top: int = overview.TOP_SCREEN) -> dict:
    """Every indicator of the overview in the scope of the request."""
    per = overview.period(days)
    scope, whole = request_log_scope()
    last_check = overview_last_check()
    governance_of = None
    if g.account_role == "admin":
        audit_scope = journal.scope_query(g.tenant, operator_view=g.server_admin and not g.support)

        def governance_of(p, n):
            return overview.governance(audit_scope, lambda anchor: gs1.within_prefixes(anchor, g.prefixes), p,
                                       g.tenant, whole, n)
    return overview.build(per, scope, whole, overview_records(), last_check, overview_operation(last_check),
                          governance_of, top)


@app.get("/portal/api/overview")
@require_login
def get_overview():
    """The overview's indicators for the last 7, 30 or 90 days (Documentation/adr/0007-overview-indicators.md)."""
    try:
        return jsonify(overview_data(request.args.get("days")))
    except PyMongoError as exc:
        return _log_unavailable(exc)


@app.post("/portal/api/overview/export")
@require_login
def export_overview():
    """The overview's figures as XLSX (one sheet per list) or CSV (one row per figure); the browser sends the labels
    in the user's language. A journal event: overview-export."""
    data = request.get_json(silent=True) or {}
    labels = data.get("labels") if isinstance(data.get("labels"), dict) else {}
    labels = {str(k): str(v) for k, v in labels.items()}
    try:
        found = overview_data(data.get("days"), overview.TOP_EXPORT)
    except PyMongoError as exc:
        return _log_unavailable(exc)
    stamp = time.strftime("%Y%m%d-%H%M")
    log_event("overview-export", detail=f'{data.get("format")} days={found["period"]["days"]}')
    if data.get("format") == "csv":
        body, mime, ext = overview.write_csv(found, labels), "text/csv; charset=utf-8", "csv"
    else:
        body = overview.write_xlsx(found, labels)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return Response(body, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="portal-overview-{stamp}.{ext}"'})


# Human readable interpretation below the QR code: every element string, only the key's, or none.
# "1" and "0" are the values of earlier versions of the portal.
HRI_MODES = {"full": "full", "1": "full", "key": "key", "none": "none", "0": "none"}


def qr_version(raw) -> int | None:
    """QR version 1-40, or None ("auto" or absent): the smallest that fits."""
    if raw in (None, "", "auto"):
        return None
    if not (str(raw).isascii() and str(raw).isdigit() and 1 <= int(raw) <= 40):
        raise ValidationError("qr.version")
    return int(raw)


def qr_error_level(raw) -> str:
    """The QR error correction level of a request (L, M, Q or H; default M), or ValidationError."""
    level = str(raw or "m").lower()
    if level not in label.ERROR_LEVELS:
        raise ValidationError("qr.level")
    return level


@app.post("/portal/api/digital-link")
@require_login
def digital_link_preview():
    """The GS1 Digital Link URI the QR code will carry, with data attributes validated by the GS1 Barcode
    Syntax Engine; the editor calls it while the user types. Nothing is stored."""
    data = request.get_json(silent=True) or {}
    anchor = request_key(data)
    check_access(anchor)
    pairs = request_qualifiers(data, anchor)
    uri, attribute_lines = digital_link_for(anchor, pairs, request_attributes(data), data.get("domain"))
    return jsonify(uri=uri, hri=gs1.hri_lines(anchor, pairs) + attribute_lines)


@app.get("/portal/api/qrcode")
@require_login
def qrcode():
    """QR code label. format=png|svg downloads it; without format it is the inline SVG preview.
    hri=0 omits the human readable interpretation."""
    anchor = request_key(request.args)
    check_access(anchor)
    return label_response(anchor, request.args)


def label_size(raw) -> int:
    """The label's size, a percentage of the target X-dimensions (Documentation/adr/0010-label-studio.md)."""
    try:
        size = int(str(raw or "100").rstrip("%"))
    except ValueError:
        size = 0
    if size not in label.SIZES:
        raise ValidationError("label.sizeInvalid", sizes=", ".join(map(str, label.SIZES)))
    return size


def label_linear(anchor: str, pairs, raw) -> tuple[str, str] | None:
    """The EAN/UPC symbol beside the QR code: none (default), auto (the one the GTIN takes) or upce."""
    choice = str(raw or "none").strip().lower()
    if choice in ("none", "0", ""):
        return None
    if choice not in ("auto", "upce"):
        raise ValidationError("label.linearInvalid")
    ai, value = gs1.split_anchor(anchor)
    try:
        if ai != "01":
            raise linear.NotPossible(ai)
        return linear.symbol_for(value, choice)
    except linear.NotPossible:
        raise ValidationError("label.linearNotPossible", choice=choice) from None


def zip_name(filename: str) -> str:
    """The name of the files inside a label's zip: no folders, nothing a file system refuses."""
    return re.sub(r"[^A-Za-z0-9_.-]", "-", filename)


def label_response(anchor: str, args) -> Response:
    """The label of a key (whose access was checked) from the request's options: the portal's and the tenant
    API's (qualifiers, attr, hri, version, ecl, size, linear, domain, format=svg|png|pdf|zip)."""
    pairs = request_qualifiers(args, anchor)
    uri, attribute_lines = digital_link_for(anchor, pairs, request_attributes(args), args.get("domain"))
    lines = gs1.hri_lines(anchor, pairs) + attribute_lines
    hri = HRI_MODES.get(args.get("hri", "full"))
    if hri is None:
        raise ValidationError("qr.hri")
    options = label.LabelOptions(
        uri=uri,
        hri_lines=tuple(lines[:1] if hri == "key" else lines),
        show_hri=hri != "none",
        version=qr_version(args.get("version")),
        error=qr_error_level(args.get("ecl")),
        size=label_size(args.get("size")),
        linear=label_linear(anchor, pairs, args.get("linear")),
    )
    try:
        qr = label.symbol(options)
    except label.DoesNotFit as exc:
        raise ValidationError("qr.tooLong" if exc.params["needed"] is None else "qr.tooSmall", **exc.params) from None
    # The version and level actually used, shown under the preview
    qr_headers = {"X-QR-Version": str(qr.version), "X-QR-Level": qr.error.upper(), "X-QR-Modules": str(len(qr.matrix))}
    if options.linear:
        qr_headers["X-Linear-Symbol"] = f"{linear.NAMES[options.linear[0]]} {options.linear[1]}"
    ai, value = gs1.split_anchor(anchor)
    suffix = "".join(f"_{q}_{v}" for q, v in pairs)
    filename = f"qrcode_{ai}_{value}{suffix}"
    download_format = args.get("format")
    if download_format == "png":
        return Response(label.render_png(options), mimetype="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.png"', **qr_headers})
    if download_format == "pdf":
        return Response(label.render_pdf(options), mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"', **qr_headers})
    if download_format == "zip":
        return Response(label.render_zip(options, zip_name(filename)), mimetype="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.zip"', **qr_headers})
    headers = {"Content-Disposition": f'attachment; filename="{filename}.svg"'} if download_format == "svg" else {}
    return Response(label.render_svg(options), mimetype="image/svg+xml", headers={**headers, **qr_headers})


# --------------------------------------------------------------------------- background jobs
# What the worker runs for each type of job (worker.py). With PORTAL_WORKER=embedded a worker thread runs
# them inside this process; otherwise the portal-worker service does.
JOB_RUNNERS = {"import": run_import_job, "linkcheck": run_link_job, "mail": notify.run_mail_job}
# What the worker runs about once an hour, outside any job (worker.HOUSEKEEPING_SECONDS)
HOUSEKEEPING = [notify_expiring_keys, requestlog.aggregate, domains.recheck_all]
# What the worker runs every PORTAL_MONITOR_MINUTES (Documentation/adr/0008-monitoring-and-alerts.md)
MONITORING = [monitor.run]
MONITOR_SECONDS = monitor.minutes() * 60
EMBEDDED_WORKER = (worker.start_embedded(JOB_RUNNERS, HOUSEKEEPING, MONITORING, MONITOR_SECONDS)
                   if worker.mode() == "embedded" and not worker.IN_WORKER_PROCESS else None)

# The tenant API (/portal/api/v1, Documentation/adr/0005-tenant-api.md) adds its routes to this application; it is
# imported last because it uses the functions above.
import api_v1  # noqa: E402,F401
