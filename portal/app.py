"""
Link management portal for GS1 Resolver CE.

Backend-for-frontend: the browser never sees SESSION_TOKEN or the Resolver CE v3 payload.
It sends a simple JSON document (GTIN, batch/lot, description, link targets) and this service:
  1. validates it against GS1 rules;
  2. reads the current state from the resolver (GET);
  3. chooses the safe sequence of calls (POST /new, PUT, partial DELETE);
  4. writes an audit trail of who changed what.

Responses carry message *codes* (e.g. "save.updated", "gtin.checkDigit") instead of sentences;
the front end renders them in the user's language from static/i18n.js.
"""
import json
import logging
import os
import secrets
import threading
import time
from datetime import timedelta
from functools import wraps

import requests
from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory, session

import gs1
import label
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
    MAX_CONTENT_LENGTH=256 * 1024,
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


def require_login(view):
    """Session login. API calls get 401 with a message code; pages are redirected to the login page."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        username = current_user()
        if not username:
            if request.path.startswith("/portal/api/"):
                return message("auth.required", 401)
            return redirect("/portal/login?reason=expired" if session.get("was_logged_in") else "/portal/login")
        g.user = username
        return view(*args, **kwargs)
    return wrapper


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


def read_entries(gtin14: str) -> tuple[list[dict], str | None]:
    """Every v3 entry for the GTIN (one per qualifier set) and the shared default link type."""
    status, body = resolver("GET", f"/01/{gtin14}")
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
    """Language-neutral description of an entry, e.g. {"kind": "lot", "value": "L1"}."""
    q = {k: v for item in entry.get("qualifiers") or [] for k, v in item.items()}
    if "10" in q:
        return {"kind": "lot", "value": q["10"]}
    return {"kind": "product"} if not q else {"kind": "other", "value": json.dumps(q)}


def is_success(status: int, body) -> bool:
    return status in (200, 201) and not (isinstance(body, dict) and body.get("error"))


# --------------------------------------------------------------------------- form → Resolver CE v3
def build_document(data: dict) -> tuple[str, str | None, dict]:
    gtin14 = gs1.normalise_gtin(str(data.get("gtin", "")))
    lot = gs1.normalise_lot(data.get("lot"))

    description = (data.get("description") or "").strip()
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
        hreflang = [h for h in (row.get("hreflang") or []) if isinstance(h, str) and h]
        if not hreflang or any(h not in gs1.LANGUAGE_CODES and h != "und" for h in hreflang):
            raise ValidationError("link.languageRequired", position=position)
        link = {
            "linktype": link_type,
            "href": href,
            "title": (row.get("title") or "").strip()[:120] or gs1.LINK_TYPE_DEFAULT_TITLES[link_type],
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

    # The first link is the default (gs1:defaultLink); its type becomes the GTIN's defaultLinktype.
    default = data.get("defaultLinkType") or links[0]["linktype"]
    if default not in {l["linktype"] for l in links}:
        raise ValidationError("default.required")

    doc = {"anchor": f"/01/{gtin14}", "itemDescription": description,
           "defaultLinktype": default, "links": links}
    if lot:
        doc["qualifiers"] = gs1.qualifiers_for(lot)
    return gtin14, lot, doc


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
        audit.info("user=%s action=login-failed addr=%s", username or "-", client_address())
        time.sleep(0.5)
        return message("auth.invalid", 401)
    throttle.clear(*keys)
    session.clear()
    session.permanent = True
    session.update(user=username, fp=users.fingerprint(username), was_logged_in=True)
    audit.info("user=%s action=login addr=%s", username, client_address())
    return message("auth.welcome", 200, user=username)


@app.post("/portal/api/logout")
def logout():
    username = session.get("user")
    session.clear()
    if username:
        audit.info("user=%s action=logout", username)
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
        users.set_password(g.user, new)
    except users.StoreNotWritable as exc:
        log.error("Password change failed: %s", exc)
        return message("password.storeReadOnly", 500)
    session["fp"] = users.fingerprint(g.user)   # keeps this session; every other session is signed out
    audit.info("user=%s action=password-change", g.user)
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
        user=g.user,
        resolver=RESOLVER_PUBLIC_URL,
        linkTypes=[{"code": code, "group": group} for code, group, _ in gs1.LINK_TYPES],
        languages=gs1.LANGUAGES,
    )


@app.get("/portal/api/record")
@require_login
def get_record():
    gtin14 = gs1.normalise_gtin(request.args.get("gtin", ""))
    lot = gs1.normalise_lot(request.args.get("lot"))
    entries, default = read_entries(gtin14)
    target = find_entry(entries, gs1.qualifiers_for(lot))
    others = [describe_entry(e) for e in entries if e is not target]

    result = {
        "gtin": gtin14, "lot": lot,
        "digitalLink": gs1.digital_link(RESOLVER_PUBLIC_URL, gtin14, lot),
        "exists": target is not None,
        "otherEntries": others,
        # With other entries on the same GTIN the default link type is shared and cannot change here.
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
def save_record():
    gtin14, lot, doc = build_document(request.get_json(silent=True) or {})
    qualifiers = doc.get("qualifiers", [])
    uri = gs1.digital_link(RESOLVER_PUBLIC_URL, gtin14, lot)

    entries, current_default = read_entries(gtin14)
    target = find_entry(entries, qualifiers)
    others = [e for e in entries if e is not target]

    if others and doc["defaultLinktype"] != current_default:
        raise ValidationError("default.sharedMismatch", linkType=current_default,
                              entries=[describe_entry(e) for e in others])

    # Case 1: new GTIN, or new batch/lot on an existing GTIN → POST /new (upsert appends the entry)
    if target is None:
        status, body = resolver("POST", "/new", doc)
        if not is_success(status, body):
            raise UpstreamError("upstream.createRejected", 502, body)
        audit.info("user=%s action=create anchor=/01/%s lot=%s links=%d",
                   g.user, gtin14, lot or "-", len(doc["links"]))
        return message("save.created", 201, digitalLink=uri, created=True)

    # Case 2: existing entry → PUT (merge on linktype+hreflang+context), then a partial DELETE of the
    # links the user removed. In this order the product is never left without a target.
    status, body = resolver("PUT", f"/01/{gtin14}", doc)
    if not is_success(status, body):
        raise UpstreamError("upstream.updateRejected", 502, body)

    new_keys = {gs1.link_key(l) for l in doc["links"]}
    removed = [{"linktype": l["linktype"], "hreflang": l.get("hreflang") or [],
                "context": l.get("context") or []}
               for l in target.get("links", []) if gs1.link_key(l) not in new_keys]
    if removed:
        status, body = resolver("DELETE", f"/01/{gtin14}", {"qualifiers": qualifiers, "links": removed})
        if not is_success(status, body):
            raise UpstreamError("upstream.partialUpdate", 502, body, count=len(removed))

    audit.info("user=%s action=update anchor=/01/%s lot=%s links=%d removed=%d",
               g.user, gtin14, lot or "-", len(doc["links"]), len(removed))
    return message("save.updated", 200, digitalLink=uri, created=False)


@app.delete("/portal/api/record")
@require_login
def delete_record():
    gtin14 = gs1.normalise_gtin(request.args.get("gtin", ""))
    lot = gs1.normalise_lot(request.args.get("lot"))
    entries, _ = read_entries(gtin14)
    target = find_entry(entries, gs1.qualifiers_for(lot))
    if target is None:
        raise ValidationError("record.notFound")
    others = [e for e in entries if e is not target]

    status, body = resolver("DELETE", f"/01/{gtin14}")
    if not is_success(status, body):
        raise UpstreamError("upstream.deleteFailed", 502, body)
    if others:
        # The API cannot remove a whole qualifier entry: recreate the document with the remaining
        # entries and restore the original if that fails.
        status, body = resolver("POST", "/new", others)
        if not is_success(status, body):
            resolver("POST", "/new", entries)
            raise UpstreamError("upstream.deleteRestored", 502, body)

    audit.info("user=%s action=delete anchor=/01/%s lot=%s", g.user, gtin14, lot or "-")
    return message("delete.done")


@app.get("/portal/api/qrcode")
@require_login
def qrcode():
    """QR code label. format=png|svg downloads it; without format it is the inline SVG preview.
    hri=0 omits the human readable interpretation; brand=1 adds the GS1® branding (pilot)."""
    gtin14 = gs1.normalise_gtin(request.args.get("gtin", ""))
    lot = gs1.normalise_lot(request.args.get("lot"))
    options = label.LabelOptions(
        uri=gs1.digital_link(RESOLVER_PUBLIC_URL, gtin14, lot),
        hri_lines=tuple(gs1.hri_lines(gtin14, lot)),
        branded=request.args.get("brand") == "1",
        show_hri=request.args.get("hri", "1") != "0",
    )
    filename = f"qrcode_{gtin14}{'_' + lot if lot else ''}{'_gs1' if options.branded else ''}"
    download_format = request.args.get("format")
    if download_format == "png":
        return Response(label.render_png(options), mimetype="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.png"'})
    headers = {"Content-Disposition": f'attachment; filename="{filename}.svg"'} if download_format == "svg" else {}
    return Response(label.render_svg(options), mimetype="image/svg+xml", headers=headers)
