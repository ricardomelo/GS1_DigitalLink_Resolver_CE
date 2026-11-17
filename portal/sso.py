"""
Single sign-on per organisation with OpenID Connect (Documentation/adr/0012-single-sign-on.md, backlog item 7.1).

One configuration per organisation and one for the operator, in the collection "sso":

    {"_id": "t-…" | "operator", "issuer": "https://login.example.com/tenant/v2.0", "clientId": "…",
     "clientSecret": "…" (never sent to a browser), "domains": ["acme.example"], "enabled": true, "passwordOff": false,
     "emailVerifiedOptional": false, "token": "<32 hex>",
     "proofs": [{"domain": "acme.example", "how": "dns" | "admin" | "upgrade", "at", "by"}],
     "updated", "updatedBy", "lastLogin", "lastError": {"at", "code", "detail"}}

A listed domain signs people in only once proved (Documentation/adr/0025-sso-domain-proof-and-subject.md): a DNS TXT
record "_gs1resolver.<domain>" holding "gs1resolver-sso=<token>", or a server administrator's approval; a domain is
proved in one configuration at most.

start() turns an e-mail address into the provider's authorization address (the code flow with PKCE, state and nonce
kept in the signed session cookie); finish() exchanges the code, verifies the ID token with the provider's keys and
finds the portal account with that e-mail in that organisation, bound at its first sign-in to the token's issuer and
subject. Accounts are never created here.
"""
import base64
import hashlib
import os
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse

import jwt
import requests

import domains as domain_proof
import linkcheck
import outbound
import store
import users
from users import UserError

OPERATOR = "operator"
ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
CACHE_SECONDS = 3600          # discovery documents and keys
FLOW_SECONDS = 600            # from the sign-in page to the provider's answer
TIMEOUT = 10
MAX_DOMAINS = 20
LEEWAY = 60                   # seconds of clock difference accepted on exp/iat
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
DISCOVERY = "/.well-known/openid-configuration"
TXT_PREFIX = "gs1resolver-sso="     # at domain_proof.TXT_NAME + "." + domain, beside the QR code domains' record
PROOF_WAYS = ("dns", "admin", "upgrade")


class SsoError(Exception):
    """A sign-in that cannot go on; code is a message code for the sign-in page."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def insecure_allowed() -> bool:
    return os.environ.get("PORTAL_SSO_ALLOW_INSECURE", "").strip().lower() in ("1", "true", "yes")


def _col():
    return store.col("sso")


def scope_id(tenant: str | None) -> str:
    return tenant or OPERATOR


def tenant_of(scope: str) -> str | None:
    return None if scope == OPERATOR else scope


# ----------------------------------------------------------------------------------------------- configurations
def public(doc: dict) -> dict:
    """What the screen shows: everything but the secret (only whether there is one); each domain with its proof and the
    TXT record that proves it."""
    error = doc.get("lastError") or None
    proofs = {p["domain"]: p for p in doc.get("proofs") or []}
    token = doc.get("token") or ""
    return {"scope": doc["_id"], "issuer": doc.get("issuer") or "", "clientId": doc.get("clientId") or "",
            "secretSet": bool(doc.get("clientSecret")), "domains": doc.get("domains") or [],
            "domainStates": [{"domain": d, "proof": proofs[d]["how"] if d in proofs else None,
                              "provedAt": store.iso(proofs[d].get("at")) if d in proofs else None,
                              "provedBy": proofs[d].get("by") if d in proofs else None,
                              "txtName": f"{domain_proof.TXT_NAME}.{d}", "txtValue": TXT_PREFIX + token if token else ""}
                             for d in doc.get("domains") or []],
            "enabled": bool(doc.get("enabled")), "passwordOff": bool(doc.get("passwordOff")),
            "emailVerifiedOptional": bool(doc.get("emailVerifiedOptional")),
            "updated": store.iso(doc.get("updated")), "updatedBy": doc.get("updatedBy"),
            "lastLogin": store.iso(doc.get("lastLogin")),
            "lastError": {"at": store.iso(error.get("at")), "code": error.get("code"), "detail": error.get("detail")}
            if error else None}


def load(scope: str | None, every: bool = False) -> list[dict]:
    query = {} if every else {"_id": scope}
    return sorted(_col().find(query), key=lambda d: (d["_id"] != OPERATOR, d["_id"]))


def get(scope: str) -> dict | None:
    return _col().find_one({"_id": scope})


def check_url(url: str, code: str = "sso.issuerInvalid") -> str:
    """An address of the provider: https on a public address (http and private addresses with
    PORTAL_SSO_ALLOW_INSECURE). Raises UserError(code)."""
    text = str(url or "").strip()
    parts = urlparse(text)
    insecure = insecure_allowed()
    if parts.scheme not in (("https", "http") if insecure else ("https",)) or not parts.hostname \
            or parts.username or parts.password or parts.fragment or len(text) > 500:
        raise UserError(code)
    if not insecure and outbound.public_host(parts.hostname) is False:
        raise UserError("sso.issuerPrivate")
    return text


def _send(method: str, url: str, **kwargs):
    """One request to the provider (ADR 0029): connected to an address of the name checked once, never to the name
    resolved again; no redirects. A private address raises SsoError(sso.issuerPrivate), a name without an address
    requests.ConnectionError."""
    try:
        return outbound.request(method, url, insecure_allowed(), timeout=TIMEOUT, **kwargs)
    except outbound.PrivateAddress:
        raise SsoError("sso.issuerPrivate", url)
    except outbound.OutboundError as exc:
        raise requests.ConnectionError(type(exc).__name__)


def clean_domains(values, scope: str) -> list[str]:
    raw = values if isinstance(values, list) else re.split(r"[\s,;]+", str(values or ""))
    domains = []
    for value in raw:
        domain = str(value or "").strip().lower().lstrip("@").rstrip(".")
        if not domain:
            continue
        try:
            domain = domain.encode("idna").decode("ascii")
        except UnicodeError:
            raise UserError("sso.domainInvalid", domain=str(value)[:80])
        if not DOMAIN.match(domain):
            raise UserError("sso.domainInvalid", domain=domain[:80])
        if domain not in domains:
            domains.append(domain)
    if len(domains) > MAX_DOMAINS:
        raise UserError("sso.domainsTooMany", max=MAX_DOMAINS)
    for domain in domains:
        if proved_elsewhere(domain, scope):
            raise UserError("sso.domainTaken", domain=domain)
    return domains


def proved(doc: dict | None) -> list[str]:
    """The listed domains of a configuration that are proved (only these sign people in)."""
    if not doc:
        return []
    listed = doc.get("domains") or []
    return [p["domain"] for p in doc.get("proofs") or [] if p.get("domain") in listed]


def proved_elsewhere(domain: str, scope: str) -> bool:
    """Whether another configuration has proved the domain."""
    return any(domain in proved(other)
               for other in _col().find({"_id": {"$ne": scope}, "proofs.domain": domain}))


def _proof_target(scope: str, domain) -> tuple[dict, str]:
    doc = get(scope)
    domain = str(domain or "").strip().lower().rstrip(".")
    if not doc:
        raise UserError("sso.unknown")
    if domain not in (doc.get("domains") or []):
        raise UserError("sso.domainNotListed", domain=domain[:80])
    if proved_elsewhere(domain, scope):
        raise UserError("sso.domainTaken", domain=domain)
    return doc, domain


def _add_proof(doc: dict, domain: str, how: str, by: str) -> dict:
    proofs = [p for p in doc.get("proofs") or [] if p.get("domain") != domain]
    proofs.append({"domain": domain, "how": how, "at": store.now(), "by": by})
    _col().update_one({"_id": doc["_id"]}, {"$set": {"proofs": proofs}})
    forget()
    return get(doc["_id"])


def verify_domain(scope: str, domain, by: str) -> dict:
    """Looks up the domain's TXT record; found, the domain is proved by DNS. Raises UserError("sso.txtMissing")."""
    with users.locked():
        doc, domain = _proof_target(scope, domain)
        name, value = f"{domain_proof.TXT_NAME}.{domain}", TXT_PREFIX + doc["token"]
        if value not in domain_proof.txt_records(name):
            raise UserError("sso.txtMissing", name=name, value=value)
        return _add_proof(doc, domain, "dns", by)


def accounts_elsewhere(domain: str, scope: str) -> int:
    """How many accounts outside the configuration's organisation (or the operator) have an address at the domain."""
    tenant = tenant_of(scope)
    pattern = "@" + re.escape(domain) + "$"
    return sum(1 for a in users._users().find({"email": {"$regex": pattern}}, {"tenant": 1})
               if (a.get("tenant") or None) != tenant)


def approve_domain(scope: str, domain, by: str) -> dict:
    """A server administrator's approval of a domain without a DNS record; refused when accounts of another
    organisation (or of the operator) use the domain."""
    with users.locked():
        doc, domain = _proof_target(scope, domain)
        if accounts_elsewhere(domain, scope):
            raise UserError("sso.domainUsed", domain=domain)
        return _add_proof(doc, domain, "admin", by)


def upgrade() -> int:
    """Configurations saved before domains needed a proof (ADR 0025 §2.1.7): their listed domains are recorded as
    proved at the upgrade, so that sign-in goes on working. Idempotent; returns the configurations changed."""
    changed = 0
    for doc in _col().find({"proofs": {"$exists": False}}):
        now = store.now()
        change = {"proofs": [{"domain": d, "how": "upgrade", "at": now, "by": None} for d in doc.get("domains") or []]}
        if not doc.get("token"):
            change["token"] = secrets.token_hex(16)
        _col().update_one({"_id": doc["_id"], "proofs": {"$exists": False}}, {"$set": change})
        changed += 1
    if changed:
        forget()
    return changed


def save(scope: str, data: dict, by: str) -> dict:
    """Creates or changes a configuration; "clientSecret" replaces the secret when given (not empty), keeps it
    otherwise. Switched on, it needs an issuer, a client ID, a secret and a domain."""
    with users.locked():
        doc = get(scope) or {"_id": scope}
        issuer = str(data.get("issuer", doc.get("issuer", "")) or "").strip().rstrip("/")
        client_id = str(data.get("clientId", doc.get("clientId", "")) or "").strip()
        secret = data.get("clientSecret")
        domains = clean_domains(data.get("domains", doc.get("domains", [])), scope)
        enabled = bool(data.get("enabled", doc.get("enabled", False)))
        password_off = bool(data.get("passwordOff", doc.get("passwordOff", False)))
        unverified_ok = bool(data.get("emailVerifiedOptional", doc.get("emailVerifiedOptional", False)))
        if issuer:
            issuer = check_url(issuer).rstrip("/")
        if len(client_id) > 200 or (client_id and not client_id.isprintable()):
            raise UserError("sso.clientIdInvalid")
        change = {"issuer": issuer, "clientId": client_id, "domains": domains, "enabled": enabled,
                  "passwordOff": enabled and password_off, "emailVerifiedOptional": unverified_ok,
                  "proofs": [p for p in doc.get("proofs") or [] if p.get("domain") in domains],
                  "token": doc.get("token") or secrets.token_hex(16), "updated": store.now(), "updatedBy": by}
        if isinstance(secret, str) and secret.strip():
            if len(secret) > 500 or not secret.isprintable():
                raise UserError("sso.secretInvalid")
            change["clientSecret"] = secret.strip()
        if enabled:
            missing = [name for name, value in (("issuer", issuer), ("clientId", client_id),
                                                ("clientSecret", change.get("clientSecret") or doc.get("clientSecret")),
                                                ("domains", domains)) if not value]
            if missing:
                raise UserError("sso.incomplete", fields=", ".join(missing))
        _col().update_one({"_id": scope}, {"$set": change}, upsert=True)
    forget()
    return get(scope)


def remove(scope: str) -> dict | None:
    doc = get(scope)
    if doc:
        _col().delete_one({"_id": scope})
        forget()
    return doc


def for_email(email: str) -> dict | None:
    """The configuration switched on that proved the domain of an e-mail address."""
    domain = str(email or "").strip().lower().rpartition("@")[2]
    if not domain:
        return None
    return next((doc for doc in _col().find({"domains": domain, "enabled": True}) if domain in proved(doc)), None)


def password_off_for(account: dict | None) -> bool:
    """Whether password sign-in is off for the account: its organisation's configuration says so and has proved the
    domain of the account's e-mail (never for a server administrator)."""
    if not account or not account.get("tenant"):          # the operator's users, server administrators among them
        return False
    doc = _col().find_one({"_id": account["tenant"]}, {"enabled": 1, "passwordOff": 1, "domains": 1, "proofs": 1})
    domain = str(account.get("email") or "").rpartition("@")[2]
    return bool(doc and doc.get("enabled") and doc.get("passwordOff") and domain and domain in proved(doc))


def any_enabled() -> bool:
    return _col().count_documents({"enabled": True}, limit=1) > 0


def note(scope: str, ok: bool, code: str | None = None, detail: str | None = None) -> None:
    """The last sign-in through a configuration, or its last failure (shown on the screen)."""
    change = {"lastLogin": store.now()} if ok else {"lastError": {"at": store.now(), "code": code,
                                                                   "detail": (detail or "")[:200]}}
    _col().update_one({"_id": scope}, {"$set": change})


# ----------------------------------------------------------------------------------------------- the provider
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def forget() -> None:
    with _lock:
        _cache.clear()


def _get_json(url: str) -> dict:
    """A JSON document of the provider (no redirects followed; the address checked first)."""
    try:
        check_url(url, "sso.discoveryFailed")
    except UserError as exc:
        raise SsoError(exc.code, url)
    answer = _send("GET", url, headers={"Accept": "application/json", "User-Agent": linkcheck.USER_AGENT})
    if answer.status_code != 200:
        raise SsoError("sso.discoveryFailed", f"{url}: HTTP {answer.status_code}")
    try:
        return answer.json()
    except ValueError:
        raise SsoError("sso.discoveryFailed", f"{url}: not JSON")


def _cached(key: str, fetch, refresh: bool = False):
    with _lock:
        hit = _cache.get(key)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def discovery(issuer: str) -> dict:
    """The provider's discovery document, checked: its issuer is the one configured, its endpoints are acceptable
    addresses."""
    def fetch():
        try:
            meta = _get_json(issuer.rstrip("/") + DISCOVERY)
        except requests.RequestException as exc:
            raise SsoError("sso.discoveryFailed", type(exc).__name__)
        if str(meta.get("issuer", "")).rstrip("/") != issuer.rstrip("/"):
            raise SsoError("sso.discoveryFailed", f"issuer {meta.get('issuer')!r} is not {issuer!r}")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            try:
                check_url(meta.get(name), "sso.discoveryFailed")
            except UserError:
                raise SsoError("sso.discoveryFailed", f"{name}: {meta.get(name)!r}")
        return meta
    return _cached("discovery " + issuer, fetch)


def _keys(uri: str, refresh: bool = False) -> list:
    def fetch():
        try:
            data = _get_json(uri)
        except requests.RequestException as exc:
            raise SsoError("sso.discoveryFailed", type(exc).__name__)
        keys = []
        for item in data.get("keys") or []:
            if item.get("use", "sig") != "sig":
                continue
            try:
                keys.append(jwt.PyJWK(item))
            except (jwt.PyJWKError, jwt.InvalidKeyError, TypeError, ValueError):
                continue                                  # a key of a kind not used here
        return keys
    return _cached("keys " + uri, fetch, refresh)


def _signing_key(meta: dict, header: dict):
    kid = header.get("kid")
    for refresh in (False, True):                         # a key the provider has just added: read the keys again once
        keys = _keys(meta["jwks_uri"], refresh)
        found = [k for k in keys if (kid is None and len(keys) == 1) or k.key_id == kid]
        if found:
            return found[0]
    raise SsoError("sso.tokenInvalid", f"no key {kid!r}")


def verify(token: str, doc: dict, meta: dict, nonce: str) -> dict:
    """The claims of an ID token whose signature, issuer, audience, times and nonce are right."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise SsoError("sso.tokenInvalid", type(exc).__name__)
    if header.get("alg") not in ALGORITHMS:
        raise SsoError("sso.tokenInvalid", f"algorithm {header.get('alg')!r}")
    key = _signing_key(meta, header)
    try:
        claims = jwt.decode(token, key.key, algorithms=[header["alg"]], audience=doc["clientId"],
                            issuer=meta["issuer"], leeway=LEEWAY,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as exc:
        raise SsoError("sso.tokenInvalid", f"{type(exc).__name__}: {exc}")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("sso.tokenInvalid", "nonce")
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != doc["clientId"]:
        raise SsoError("sso.tokenInvalid", "azp")
    return claims


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start(email: str, redirect_uri: str, session) -> str:
    """The provider's authorization address for the person with this e-mail; the flow's values go into the
    session (a signed cookie that comes back with the provider's redirect)."""
    email = str(email or "").strip().lower()
    if "@" not in email or len(email) > users.EMAIL_MAX:
        raise SsoError("sso.emailInvalid")
    doc = for_email(email)
    if not doc:
        raise SsoError("sso.noProvider")
    meta = discovery(doc["issuer"])
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    session["sso"] = {"state": state, "nonce": nonce, "verifier": verifier, "scope": doc["_id"], "at": time.time()}
    params = {"response_type": "code", "client_id": doc["clientId"], "redirect_uri": redirect_uri,
              "scope": "openid email profile", "state": state, "nonce": nonce, "login_hint": email,
              "code_challenge": _b64(hashlib.sha256(verifier.encode("ascii")).digest()),
              "code_challenge_method": "S256"}
    endpoint = meta["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)


def finish(args, redirect_uri: str, session) -> tuple[str, dict, dict]:
    """(user name, configuration, {"sub", "bound"}) of the provider's answer to start(); raises SsoError with what went
    wrong. The account is bound to the token's issuer and subject at its first sign-in (ADR 0025 §2.2)."""
    flow = session.pop("sso", None)
    if not flow or not secrets.compare_digest(str(args.get("state", "")), flow.get("state", "")) \
            or time.time() - flow.get("at", 0) > FLOW_SECONDS:
        raise SsoError("sso.expired")
    doc = get(flow["scope"])
    if not doc or not doc.get("enabled"):
        raise SsoError("sso.noProvider")
    if args.get("error"):
        raise SsoError("sso.providerRefused", str(args.get("error"))[:80])
    code = str(args.get("code") or "")
    if not code:
        raise SsoError("sso.expired")
    meta = discovery(doc["issuer"])
    try:
        check_url(meta["token_endpoint"], "sso.discoveryFailed")
        answer = _send("POST", meta["token_endpoint"],
                       headers={"Accept": "application/json", "User-Agent": linkcheck.USER_AGENT},
                       data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                             "client_id": doc["clientId"], "client_secret": doc.get("clientSecret", ""),
                             "code_verifier": flow["verifier"]})
    except UserError as exc:
        raise SsoError(exc.code, meta.get("token_endpoint", ""))
    except requests.RequestException as exc:
        raise SsoError("sso.tokenFailed", type(exc).__name__)
    if answer.status_code != 200:
        raise SsoError("sso.tokenFailed", f"HTTP {answer.status_code}")
    try:
        id_token = answer.json().get("id_token")
    except ValueError:
        id_token = None
    if not id_token:
        raise SsoError("sso.tokenFailed", "no id_token")
    claims = verify(id_token, doc, meta, flow["nonce"])
    email = str(claims.get("email") or "").strip().lower()
    verified = claims.get("email_verified")
    if isinstance(verified, str):                         # some providers send "true"
        verified = verified.strip().lower() == "true"
    if not email or not (verified is True or (verified is None and doc.get("emailVerifiedOptional"))):
        raise SsoError("sso.noEmail", email)
    if email.rpartition("@")[2] not in proved(doc):
        raise SsoError("sso.domainMismatch", email)
    found = users._users().find_one({"email": email})
    if not found or found.get("tenant") != tenant_of(doc["_id"]):
        raise SsoError("sso.noAccount", email)
    if found.get("disabled"):
        raise SsoError("sso.accountDisabled", email)
    issuer, subject = str(claims["iss"]), str(claims["sub"])
    bound = users.bind_sso(found["_id"], issuer, subject)
    if bound == "mismatch":
        raise SsoError("sso.subjectMismatch", f"{email} subject {subject}"[:200])
    if bound == "taken":
        raise SsoError("sso.subjectTaken", f"{email} subject {subject}"[:200])
    return found["_id"], doc, {"sub": subject, "bound": bound == "bound"}


def test(scope: str) -> dict:
    """Reads the configuration's discovery document and keys again: {"ok", "detail", "keys"}."""
    doc = get(scope)
    if not doc or not doc.get("issuer"):
        raise UserError("sso.incomplete", fields="issuer")
    forget()
    try:
        meta = discovery(doc["issuer"])
        keys = _keys(meta["jwks_uri"])
    except SsoError as exc:
        return {"ok": False, "code": exc.code, "detail": exc.detail}
    return {"ok": bool(keys), "code": "sso.testOk" if keys else "sso.testNoKeys", "detail": "",
            "keys": len(keys), "authorizationEndpoint": meta["authorization_endpoint"]}
