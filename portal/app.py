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
import secrets
import threading
import time
import uuid
from datetime import timedelta
from functools import wraps

import requests
from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory, session

import gs1
import journal
import label
import linkcheck
import meta
import sheet
import users
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
SESSION_HOURS = float(os.environ.get("PORTAL_SESSION_HOURS", "8"))
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "15"))
MAX_LINKS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("portal")
audit = logging.getLogger("portal.audit")

if not SESSION_TOKEN:
    raise RuntimeError("SESSION_TOKEN is not set: the portal would be unable to authenticate with the resolver.")
if not RESOLVER_PUBLIC_URL:
    raise RuntimeError("Set FQDN (or RESOLVER_PUBLIC_URL): the portal needs the resolver's public address.")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PUBLIC_ASSETS = {"app.css", "i18n.js", "login.js", "gs1-logo.png", "favicon.png"}   # needed by the login page
PRIVATE_ASSETS = {"app.js"}


def _secret_key() -> bytes:
    """PORTAL_SECRET_KEY if set; otherwise a random key created once in the config volume."""
    if os.environ.get("PORTAL_SECRET_KEY"):
        return os.environ["PORTAL_SECRET_KEY"].encode()
    path = os.path.join(CONFIG_DIR, "secret.key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    except OSError as exc:
        raise RuntimeError(f"Cannot create {path} ({exc}). "
                           "/app/config must be writable by uid 10001 (the portal-config volume).") from exc
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip().encode()


app = Flask(__name__, static_folder=None)
app.config.update(
    MAX_CONTENT_LENGTH=1024 * 1024,   # spreadsheet imports arrive as base64 in JSON (sheet.FORMATS: ≤ 700 KB)
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_NAME="gs1resolver_portal",
    SESSION_COOKIE_PATH="/portal",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    SESSION_REFRESH_EACH_REQUEST=True,   # sliding expiry: the session lasts SESSION_HOURS after the last use
)
if not users.is_writable():
    log.warning("The users file is read-only for the portal: password changes will fail. "
                "Check that /app/config is writable by uid 10001 (the portal-config volume).")


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


_bootstrap_admin()


class UpstreamError(Exception):
    def __init__(self, code: str, status: int = 502, detail=None, **params):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail
        self.params = params


def message(code: str, status: int = 200, **extra):
    return jsonify(code=code, **extra), status


# --------------------------------------------------------------------------- authentication
class LoginThrottle:
    """Locks a username (and, separately, a client address) after repeated failures.
    Kept in memory: the portal runs a single gunicorn worker (with threads) for this reason."""

    def __init__(self):
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self._failures.get(key, []) if now - t < LOCKOUT_SECONDS]

    def retry_after(self, *keys: str) -> int:
        now = time.time()
        with self._lock:
            waits = []
            for key in keys:
                recent = self._recent(key, now)
                self._failures[key] = recent
                if len(recent) >= MAX_LOGIN_FAILURES:
                    waits.append(int(LOCKOUT_SECONDS - (now - recent[0])) + 1)
            return max(waits, default=0)

    def fail(self, *keys: str) -> None:
        now = time.time()
        with self._lock:
            for key in keys:
                self._failures[key] = self._recent(key, now) + [now]

    def clear(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


throttle = LoginThrottle()


def client_address() -> str:
    return request.access_route[0] if request.access_route else (request.remote_addr or "?")


def current_user() -> str | None:
    username = session.get("user")
    if username and users.fingerprint_matches(username, session.get("fp")):
        return username
    session.clear()
    return None


# Calls allowed while the account must set a new password (temporary password)
MUST_CHANGE_ALLOWED = ("/portal/api/config", "/portal/api/password", "/portal/api/logout")


def require_login(view):
    """Session login. API calls get 401 with a message code; pages are redirected to the login page.
    Sets g.user, g.role and g.prefixes from the account, re-read on every request, so role and prefix
    changes apply at once."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        username = current_user()
        if not username:
            if request.path.startswith("/portal/api/"):
                return message("auth.required", 401)
            return redirect("/portal/login?reason=expired" if session.get("was_logged_in") else "/portal/login")
        account = users.get(username) or {}
        g.user, g.role, g.prefixes = username, account.get("role", "reader"), account.get("prefixes", [])
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


class AccessDenied(Exception):
    """The record belongs to a GS1 Company Prefix outside the user's."""


def allowed(anchor: str) -> bool:
    return gs1.within_prefixes(anchor, getattr(g, "prefixes", None))


def check_access(anchor: str) -> None:
    if not allowed(anchor):
        raise AccessDenied(anchor)


def log_event(action: str, **fields) -> None:
    """Journal entry (history and audit); a failure is logged, never shown to the user."""
    try:
        user = fields.pop("user", None) or getattr(g, "user", None) or "-"
        journal.append(action, user, **fields)
    except OSError as exc:
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
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.errorhandler(ValidationError)
def on_validation_error(err):
    return message(err.code, 422, params=err.params)


@app.errorhandler(AccessDenied)
def on_access_denied(err):
    return message("access.prefix", 403)


@app.errorhandler(users.UserError)
def on_user_error(err):
    return message(err.code, 422, params=err.params)


@app.errorhandler(UpstreamError)
def on_upstream_error(err):
    log.warning("Upstream: %s | %s", err.code, err.detail)
    return message(err.code, err.status, params=err.params)


# --------------------------------------------------------------------------- resolver API client
def resolver(method: str, path: str, payload=None) -> tuple[int, object]:
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
                "path": gs1.qualifier_path(pairs, encode=False)}
    return {"kind": "other", "value": "".join(f"({q}){v}" for q, v in pairs)}


def record_change(anchor: str, pairs: list, doc: dict | None, action: str) -> None:
    """Keeps the "last change" metadata and the record's history; never makes a save fail."""
    qpath = gs1.qualifier_path(pairs, encode=False)
    try:
        if action == "delete":
            meta.remove(anchor, qpath)
        else:
            meta.touch(anchor, qpath, g.user)
    except OSError as exc:
        log.warning("Record metadata not updated for %s: %s", meta.key(anchor, qpath), exc)
    log_event(action, anchor=anchor, qpath=qpath, doc=doc)


def is_success(status: int, body) -> bool:
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


def build_document(data: dict) -> tuple[str, str | None, dict]:
    anchor = request_key(data)
    pairs = request_qualifiers(data, anchor)

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
            # fwqs = "forward query strings", an attribute of the official GS1 linkset schema.
            # True is the default behaviour required by section 2.12 of the resolver standard.
            "fwqs": row.get("forwardQueryString", True) is not False,
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
    if default not in {l["linktype"] for l in links}:
        raise ValidationError("default.required")

    doc = {"anchor": anchor, "itemDescription": description,
           "defaultLinktype": default, "links": links}
    if pairs:
        doc["qualifiers"] = gs1.qualifier_list(pairs)
    return anchor, pairs, doc


# --------------------------------------------------------------------------- pages and assets
@app.get("/portal")
def portal_root():
    return redirect("/portal/", 301)


@app.get("/portal/")
@require_login
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/portal/login")
def login_page():
    if current_user():
        return redirect("/portal/")
    return send_from_directory(STATIC_DIR, "login.html")


@app.get("/portal/<name>")
def assets(name):
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
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    keys = (f"user:{username.lower()}", f"addr:{client_address()}")
    wait = throttle.retry_after(*keys)
    if wait:
        return message("auth.locked", 429, params={"minutes": -(-wait // 60)})
    if not username or not users.verify(username, password):
        throttle.fail(*keys)
        typed = shown_username(username)
        audit.info("user=%s action=login-failed addr=%s", typed, client_address())
        log_event("login-failed", user=typed, detail=client_address())
        time.sleep(0.5)
        return message("auth.invalid", 401)
    throttle.clear(*keys)
    session.clear()
    session.permanent = True
    session.update(user=username, fp=users.fingerprint(username), was_logged_in=True)
    audit.info("user=%s action=login addr=%s", username, client_address())
    users.touch_login(username)
    log_event("login", user=username, detail=client_address())
    return message("auth.welcome", 200, user=username, mustChange=bool((users.get(username) or {}).get("mustChange")))


@app.post("/portal/api/logout")
def logout():
    username = session.get("user")
    session.clear()
    if username:
        audit.info("user=%s action=logout", username)
        log_event("logout", user=username)
    return message("auth.loggedOut")


@app.post("/portal/api/password")
@require_login
def change_password():
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
    log_event("password-change")
    return message("password.changed")


@app.get("/portal/healthz")
def healthz():
    try:
        status, _ = resolver("GET", "/heartbeat")
    except UpstreamError:
        status = 0
    return jsonify(portal="ok", resolver="ok" if status == 200 else "unavailable"), 200


# --------------------------------------------------------------------------- portal API
@app.get("/portal/api/config")
@require_login
def config():
    return jsonify(
        user=g.user, role=g.role, prefixes=g.prefixes, mustChange=g.must_change,
        resolver=RESOLVER_PUBLIC_URL,
        linkTypes=[{"code": code, "group": group} for code, group, _ in gs1.LINK_TYPES],
        keys=[{"code": ai, "name": name, "qualifiers": gs1.key_qualifiers(ai),
               "shapes": [[{"ai": q, "required": req} for q, req in shape] for shape in gs1.KEY_SHAPES.get(ai, [[]])]}
              for ai, (name, _) in gs1.PRIMARY_KEYS.items()],
        languages=gs1.LANGUAGES,
        importLimits=sheet.limits(),
    )


@app.get("/portal/api/record")
@require_login
def get_record():
    anchor = request_key(request.args)
    check_access(anchor)
    pairs = request_qualifiers(request.args, anchor)
    entries, default = read_entries(anchor)
    target = find_entry(entries, gs1.qualifier_list(pairs))
    others = [describe_entry(e) for e in entries if e is not target]
    ai, value = gs1.split_anchor(anchor)

    result = {
        "key": ai, "value": value, "anchor": anchor, "qualifiers": [list(p) for p in pairs],
        "digitalLink": gs1.digital_link(RESOLVER_PUBLIC_URL, anchor, pairs),
        "exists": target is not None,
        "otherEntries": others,
        # With other entries on the same key the default link type is shared and cannot change here.
        "sharedDefaultLinkType": default if others else None,
        "defaultLinkType": default,
        "description": "", "links": [],
    }
    if target:
        result["description"] = target.get("itemDescription", "")
        result["links"] = [{
            "linkType": l.get("linktype"), "url": l.get("href"), "title": l.get("title") or "",
            "hreflang": l.get("hreflang") or ["pt"], "context": l.get("context") or [],
            "forwardQueryString": l.get("fwqs", True) is not False,
        } for l in target.get("links", [])]
        result["links"].sort(key=lambda l: l["linkType"] != default)   # default link first
    return jsonify(result)


@app.post("/portal/api/record")
@require_login
@role_required("editor")
def save_record():
    anchor, pairs, doc = build_document(request.get_json(silent=True) or {})
    check_access(anchor)
    uri = gs1.digital_link(RESOLVER_PUBLIC_URL, anchor, pairs)
    created = store_record(anchor, pairs, doc)
    return message("save.created" if created else "save.updated", 201 if created else 200,
                   digitalLink=uri, created=created)


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
    anchor = request_key(request.args)
    check_access(anchor)
    pairs = request_qualifiers(request.args, anchor)
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
    return message("delete.done")


@app.get("/portal/api/records")
@require_login
def list_records():
    """Every record on the resolver (one per primary key + qualifier set), with the portal's metadata.
    Searching and filtering happen in the browser; the list is small enough to send whole."""
    status, body = resolver("GET", "/summary")
    if status == 404:
        lines = []
    elif status != 200 or not isinstance(body, dict):
        raise UpstreamError("upstream.readFailed", 502, body)
    else:
        lines = body.get("data") or []
    known = meta.load()
    records = []
    for line in lines:
        anchor = line.get("anchor") or ""
        key = gs1.split_anchor(anchor)
        if not key or not allowed(anchor):
            continue                      # keys the portal does not manage, or outside the user's prefixes
        entry = describe_entry(line)
        qpath = entry.get("path", "")
        info = known.get(meta.key(anchor, qpath), {}) if entry["kind"] != "other" else {}
        records.append({
            "key": key[0], "value": key[1], "anchor": anchor, "kind": entry["kind"],
            "qualifiers": entry.get("qualifiers", []), "qpath": qpath,
            "other": entry.get("value") if entry["kind"] == "other" else None,
            "description": line.get("itemDescription") or "",
            "defaultLinkType": line.get("defaultLinktype"),
            "links": line.get("linkCount", 0),
            "updatedAt": info.get("updatedAt"), "updatedBy": info.get("updatedBy"),
            "createdAt": info.get("createdAt"), "createdBy": info.get("createdBy"),
        })
    return jsonify({"records": records})


# --------------------------------------------------------------------------- spreadsheets
def summary_with_links() -> list[dict]:
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
        records.append({"key": ai, "value": value, "qualifiers": entry.get("qualifiers", []),
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


IMPORTS: dict[str, dict] = {}          # token → prepared import (single worker: memory is shared)
IMPORTS_LOCK = threading.Lock()
IMPORT_TTL = 30 * 60


def _forget_old_imports() -> None:
    now = time.time()
    with IMPORTS_LOCK:
        for token in [t for t, job in IMPORTS.items() if now - job["created"] > IMPORT_TTL]:
            IMPORTS.pop(token, None)


def _row_of(record: dict, position) -> int:
    try:
        return record["links"][int(position) - 1]["row"]
    except (KeyError, IndexError, TypeError, ValueError):
        return record["rows"][0]


def _same_record(target: dict, doc: dict) -> bool:
    def links(items):
        return sorted((l.get("linktype"), l.get("href"), l.get("title") or "", tuple(sorted(l.get("hreflang") or [])),
                       l.get("fwqs", True) is not False, tuple(sorted(l.get("context") or []))) for l in items)
    return ((target.get("itemDescription") or "") == doc["itemDescription"]
            and target.get("defaultLinktype") == doc["defaultLinktype"]
            and links(target.get("links") or []) == links(doc["links"]))


@app.post("/portal/api/import/preview")
@require_login
@role_required("editor")
def import_preview():
    """Reads a spreadsheet, validates every record with the editor's rules and compares it with the
    resolver. Nothing is written; the valid records are kept for /import/apply under a token."""
    _forget_old_imports()
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
                "defaultLinkType": ordered[0]["linkType"] if ordered else None,
                "links": [{"linkType": l["linkType"], "url": l["url"], "hreflang": l["hreflang"],
                           "title": l["title"], "forwardQueryString": l["forward"]} for l in ordered]})
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

        item.update(key=gs1.split_anchor(anchor)[0], value=gs1.split_anchor(anchor)[1],
                    qualifiers=[list(p) for p in pairs])
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
        if item["action"] in ("create", "update"):
            # less qualified records first, so a new key is created with its unqualified record
            plan.append({"anchor": anchor, "pairs": pairs, "doc": doc, "rows": record["rows"]})
            to_check.extend({"row": link["row"], "url": link["url"]} for link in record["links"])
        report.append(item)

    plan.sort(key=lambda p: (p["anchor"], len(p["pairs"])))
    token = uuid.uuid4().hex
    with IMPORTS_LOCK:
        IMPORTS[token] = {"user": g.user, "created": time.time(), "plan": plan, "state": "ready",
                          "done": 0, "total": len(plan), "results": []}
    counts = {action: sum(1 for i in report if i["action"] == action)
              for action in ("create", "update", "unchanged", "error")}
    errors.sort(key=lambda e: e["row"])
    return jsonify({"token": token, "records": report, "errors": errors, "counts": counts, "links": to_check})


def _run_import(token: str, user: str) -> None:
    job = IMPORTS[token]
    with app.test_request_context():
        g.user = user                                   # store_record logs and records who changed it
        g.prefixes = (users.get(user) or {}).get("prefixes", [])
        created = updated = failed = 0
        for item in job["plan"]:
            ai, value = gs1.split_anchor(item["anchor"])
            result = {"key": ai, "value": value, "qualifiers": [list(p) for p in item["pairs"]], "rows": item["rows"],
                      "description": item["doc"]["itemDescription"]}
            try:
                result["action"] = "created" if store_record(item["anchor"], item["pairs"], item["doc"]) else "updated"
                created += result["action"] == "created"
                updated += result["action"] == "updated"
            except (ValidationError, UpstreamError) as exc:
                result.update(action="failed", code=exc.code, params=exc.params)
                failed += 1
            job["results"].append(result)
            job["done"] += 1
        audit.info("user=%s action=import created=%d updated=%d failed=%d", user, created, updated, failed)
        log_event("import", detail=f"created={created} updated={updated} failed={failed}")
    job["state"] = "finished"
    job["created"] = time.time()                       # keep the result for IMPORT_TTL from now


@app.post("/portal/api/import/apply")
@require_login
@role_required("editor")
def import_apply():
    token = (request.get_json(silent=True) or {}).get("token", "")
    with IMPORTS_LOCK:
        job = IMPORTS.get(token)
        if not job or job["user"] != g.user:
            raise ValidationError("import.expired")
        if job["state"] != "ready":
            raise ValidationError("import.alreadyApplied")
        job["state"] = "running"
    threading.Thread(target=_run_import, args=(token, g.user), daemon=True).start()
    return jsonify({"token": token, "total": job["total"]}), 202


@app.get("/portal/api/import/status")
@require_login
@role_required("editor")
def import_status():
    job = IMPORTS.get(request.args.get("token", ""))
    if not job or job["user"] != g.user:
        raise ValidationError("import.expired")
    return jsonify({"state": job["state"], "done": job["done"], "total": job["total"],
                    "results": job["results"] if job["state"] == "finished" else []})


# --------------------------------------------------------------------------- link checker
LINK_JOBS: dict[str, dict] = {}
LINK_JOBS_LOCK = threading.Lock()
LAST_FULL_CHECK: dict = {}             # result of the latest "check every record", shown in the list
MAX_CHECK_URLS = 5000


@app.post("/portal/api/links/check")
@require_login
@role_required("editor")
def check_links():
    """Checks the few targets of one record (editor); answers when all are done."""
    urls = [u for u in (request.get_json(silent=True) or {}).get("urls") or [] if isinstance(u, str)][:MAX_LINKS]
    results = linkcheck.check_many(urls)
    return jsonify({"results": [results[u] for u in dict.fromkeys(urls) if u in results]})


def _run_link_job(token: str) -> None:
    job = LINK_JOBS[token]

    def progress(done, total):
        job["done"], job["total"] = done, total

    results = linkcheck.check_many(list(job["urls"]), progress)
    problems = {u: r for u, r in results.items() if not r["ok"]}
    if job["scope"] == "all":
        by_record = {}
        for url, result in problems.items():
            for key in job["urls"][url]:
                by_record.setdefault(key, []).append(result)
        job["records"] = by_record
        LAST_FULL_CHECK.clear()
        LAST_FULL_CHECK.update(checkedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               records=by_record, urls=len(results), user=job["user"])
        audit.info("user=%s action=linkcheck urls=%d problems=%d", job["user"], len(results), len(problems))
    job["problems"] = list(problems.values())
    job["state"] = "finished"
    job["created"] = time.time()


@app.post("/portal/api/links/jobs")
@require_login
@role_required("editor")
def start_link_job():
    """Checks many targets in the background: every record's ("scope": "all") or a list of URLs
    (spreadsheet import preview). Poll /links/jobs/<token>."""
    data = request.get_json(silent=True) or {}
    now = time.time()
    with LINK_JOBS_LOCK:
        for old in [t for t, j in LINK_JOBS.items() if now - j["created"] > IMPORT_TTL]:
            LINK_JOBS.pop(old, None)
    if data.get("scope") == "all":
        urls: dict[str, list[str]] = {}
        for line in summary_with_links():
            entry = describe_entry(line)
            if entry["kind"] == "other" or not allowed(line["anchor"]):
                continue
            key = f'{line["anchor"]}|{entry.get("path", "")}'
            for link in line.get("links") or []:
                urls.setdefault(link.get("href"), []).append(key)
        scope = "all"
    else:
        urls = {u: [] for u in data.get("urls") or [] if isinstance(u, str) and u}
        scope = "list"
    if len(urls) > MAX_CHECK_URLS:
        raise ValidationError("linkcheck.tooMany", max=MAX_CHECK_URLS)
    token = uuid.uuid4().hex
    with LINK_JOBS_LOCK:
        LINK_JOBS[token] = {"user": g.user, "created": now, "state": "running", "scope": scope,
                            "urls": urls, "done": 0, "total": len(urls)}
    threading.Thread(target=_run_link_job, args=(token,), daemon=True).start()
    return jsonify({"token": token, "total": len(urls)}), 202


@app.get("/portal/api/links/jobs/<token>")
@require_login
@role_required("editor")
def link_job_status(token):
    job = LINK_JOBS.get(token)
    if not job or job["user"] != g.user:
        raise ValidationError("linkcheck.expired")
    out = {"state": job["state"], "done": job["done"], "total": job["total"]}
    if job["state"] == "finished":
        out["problems"] = job["problems"]
        if job["scope"] == "all":
            out.update(LAST_FULL_CHECK)
            out["records"] = job.get("records", {})
    return jsonify(out)


@app.get("/portal/api/links/last")
@require_login
def last_link_check():
    if not LAST_FULL_CHECK:
        return jsonify({})
    records = {k: v for k, v in LAST_FULL_CHECK.get("records", {}).items() if allowed(k.split("|")[0])}
    return jsonify({**LAST_FULL_CHECK, "records": records})


# --------------------------------------------------------------------------- governance
def temporary_password() -> str:
    """16 characters, easy to type from a message: no look-alike characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


@app.get("/portal/api/users")
@require_login
@role_required("admin")
def list_users():
    return jsonify({"users": [users.public(name, account) for name, account in sorted(users.load().items())],
                    "roles": list(users.ROLES)})


@app.post("/portal/api/users")
@require_login
@role_required("admin")
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = temporary_password()
    users.create(username, password, str(data.get("role", "")), data.get("prefixes") or [])
    audit.info("user=%s action=user-create target=%s role=%s", g.user, username, data.get("role"))
    log_event("user-create", detail=f'{username} role={data.get("role")} prefixes={",".join(data.get("prefixes") or [])}')
    return message("users.created", 201, params={"user": username}, password=password)


@app.put("/portal/api/users/<username>")
@require_login
@role_required("admin")
def update_user(username):
    data = request.get_json(silent=True) or {}
    if username == g.user and (data.get("disabled") or data.get("role") not in (None, "admin")):
        raise users.UserError("users.notSelf")          # an administrator cannot lock himself out
    account = users.update(username, role=data.get("role"), prefixes=data.get("prefixes"),
                           disabled=data.get("disabled"))
    audit.info("user=%s action=user-update target=%s", g.user, username)
    log_event("user-update", detail=f'{username} role={account["role"]} disabled={account["disabled"]} '
                                    f'prefixes={",".join(account["prefixes"])}')
    return message("users.updated", 200, params={"user": username})


@app.post("/portal/api/users/<username>/reset")
@require_login
@role_required("admin")
def reset_user(username):
    if not users.get(username):
        raise users.UserError("users.unknown", user=username)
    password = temporary_password()
    users.set_password(username, password, must_change=True)
    audit.info("user=%s action=user-reset target=%s", g.user, username)
    log_event("user-reset", detail=username)
    return message("users.reset", 200, params={"user": username}, password=password)


@app.delete("/portal/api/users/<username>")
@require_login
@role_required("admin")
def remove_user(username):
    if username == g.user:
        raise users.UserError("users.notSelf")
    users.remove(username)
    audit.info("user=%s action=user-remove target=%s", g.user, username)
    log_event("user-remove", detail=username)
    return message("users.removed", 200, params={"user": username})


@app.get("/portal/api/history")
@require_login
def record_history():
    """The latest versions of one record, with their content, for the editor's History panel."""
    anchor = request_key(request.args)
    check_access(anchor)
    pairs = request_qualifiers(request.args, anchor)
    versions = journal.for_record(anchor, gs1.qualifier_path(pairs, encode=False))
    return jsonify({"versions": versions})


def _audit_events():
    args = request.args
    return journal.search(user=args.get("user") or None, since=args.get("from") or None,
                          until=args.get("to") or None, text=args.get("q") or None,
                          allowed=allowed, limit=min(int(args.get("limit", 500) or 500), 5000))


@app.get("/portal/api/audit")
@require_login
@role_required("admin")
def audit_trail():
    return jsonify({"events": _audit_events()})


@app.get("/portal/api/audit.csv")
@require_login
@role_required("admin")
def audit_csv():
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["at", "user", "action", "anchor", "qualifiers", "detail"])
    for event in _audit_events():                  # user names of failed sign-ins are typed by anyone
        writer.writerow([sheet.protect(event.get(k, "")) for k in ("at", "user", "action", "anchor", "qpath", "detail")])
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(("\ufeff" + out.getvalue()).encode("utf-8"), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="portal-audit-{stamp}.csv"'})


@app.get("/portal/api/qrcode")
@require_login
def qrcode():
    """QR code label. format=png|svg downloads it; without format it is the inline SVG preview.
    hri=0 omits the human readable interpretation."""
    anchor = request_key(request.args)
    check_access(anchor)
    pairs = request_qualifiers(request.args, anchor)
    options = label.LabelOptions(
        uri=gs1.digital_link(RESOLVER_PUBLIC_URL, anchor, pairs),
        hri_lines=tuple(gs1.hri_lines(anchor, pairs)),
        show_hri=request.args.get("hri", "1") != "0",
    )
    ai, value = gs1.split_anchor(anchor)
    suffix = "".join(f"_{q}_{v}" for q, v in pairs)
    filename = f"qrcode_{ai}_{value}{suffix}"
    download_format = request.args.get("format")
    if download_format == "png":
        return Response(label.render_png(options), mimetype="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.png"'})
    headers = {"Content-Disposition": f'attachment; filename="{filename}.svg"'} if download_format == "svg" else {}
    return Response(label.render_svg(options), mimetype="image/svg+xml", headers=headers)
