"""
The organisations' own domains in the QR code (Documentation/adr/0009-tenant-domains.md; GS1 Digital Link URI Syntax
1.7, section 4.11). One document per domain in the "domains" collection of the portal's database:

    {"_id": "id.acme.example", "tenant": "t-…" (absent for the operator), "mode": "direct" | "redirect",
     "stem": "" | "/gs1", "defaultFor": ["7891234"], "token": "<32 hex>", "verified": bool, "verifiedAt", "seenAt",
     "check": {"at", "ok", "problem", "detail"}, "created", "createdBy"}

A domain is proved by a DNS TXT record "_gs1resolver.<domain>" holding "gs1resolver-verify=<token>"; once verified it
stays so (the daily housekeeping looks again and records when the record was last seen). The resolver
(web_server/src/domains.py) reads the verified "direct" domains and answers on them for their organisation's prefixes
only; labels carry the default domain of the record's prefix, or the one chosen.

Rules: a lower-case host name with at least two labels, not an address, not the installation's own name, not
"localhost"; unique in the installation; at most MAX_PER_SCOPE per organisation (and for the operator); a stem of one
to three segments of letters, digits, "-", ".", "_", "~", none of them 2 to 4 digits (it would read as an AI); a
default prefix is one of the organisation's prefixes (for the operator, any prefix no organisation holds) and is the
default of one domain at most.
"""
import re
import secrets
from datetime import timedelta

import requests

import gs1
import linkcheck
import store
import tenants
import users
from users import UserError

MAX_PER_SCOPE = 10
TXT_NAME = "_gs1resolver"
TXT_PREFIX = "gs1resolver-verify="
MODES = ("direct", "redirect")
LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
STEM_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,40}$")
RECHECK = timedelta(days=1)
REDIRECTS = (301, 302, 307, 308)
TIMEOUT = 10


def _col():
    return store.col("domains")


# ----------------------------------------------------------------------------------------------- names
def clean_name(value, installation: str = "") -> str:
    """A domain as stored: lower case, Punycode, no scheme, path, port or final dot."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text).split("/")[0].split("?")[0].rstrip(".")
    if ":" in text:
        text = text.split(":")[0]
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError:
        raise UserError("domains.nameInvalid")
    labels = text.split(".")
    if (len(text) > 253 or len(labels) < 2 or not all(LABEL.match(label) for label in labels)
            or labels[-1].isdigit() or text == "localhost"):
        raise UserError("domains.nameInvalid")
    if installation and text == installation.lower():
        raise UserError("domains.installationName")
    return text


def clean_stem(value) -> str:
    """"" or "/seg[/seg[/seg]]"."""
    text = str(value or "").strip().strip("/")
    if not text:
        return ""
    segments = text.split("/")
    if len(segments) > 3 or not all(STEM_SEGMENT.match(s) and not re.fullmatch(r"\d{2,4}", s) for s in segments):
        raise UserError("domains.stemInvalid")
    return "/" + "/".join(segments)


def clean_mode(value) -> str:
    mode = str(value or "direct").strip().lower()
    if mode not in MODES:
        raise UserError("domains.modeInvalid")
    return mode


def base_url(doc: dict) -> str:
    """The address a label carries for a domain: https://<domain><stem>."""
    return f"https://{doc['_id']}{doc.get('stem') or ''}"


# ----------------------------------------------------------------------------------------------- reading
def public(doc: dict, tenant_names: dict | None = None) -> dict:
    """What the Domains screen shows (the token too: the administrator writes it in DNS)."""
    out = {"domain": doc["_id"], "mode": doc.get("mode", "direct"), "stem": doc.get("stem") or "",
           "defaultFor": list(doc.get("defaultFor") or []), "verified": bool(doc.get("verified")),
           "verifiedAt": store.iso(doc.get("verifiedAt")), "seenAt": store.iso(doc.get("seenAt")),
           "txtName": f"{TXT_NAME}.{doc['_id']}", "txtValue": TXT_PREFIX + doc.get("token", ""),
           "check": {**(doc.get("check") or {}), "at": store.iso((doc.get("check") or {}).get("at"))}
           if doc.get("check") else None,
           "created": store.iso(doc.get("created")), "createdBy": doc.get("createdBy"),
           "url": base_url(doc)}
    if tenant_names is not None:
        out["organisation"] = tenant_names.get(doc.get("tenant")) if doc.get("tenant") else None
    return out


def _scope(tenant: str | None) -> dict:
    return {"tenant": tenant} if tenant else {"tenant": None}


def load(tenant: str | None, every: bool = False) -> list[dict]:
    """The domains of a scope (an organisation, or the operator), or every domain."""
    return list(_col().find({} if every else _scope(tenant)).sort("_id", 1))


def get(name: str, tenant: str | None, every: bool = False) -> dict:
    doc = _col().find_one({"_id": str(name or "").lower(), **({} if every else _scope(tenant))})
    if not doc:
        raise UserError("domains.unknown")
    return doc


def verified(tenant: str | None) -> list[dict]:
    """The verified domains of a scope, for labels."""
    return [d for d in load(tenant) if d.get("verified")]


def still_held(doc: dict, prefix: str, tenant_list: list[dict]) -> bool:
    """Whether a domain's organisation (the operator without one) still holds a prefix it is the default for: a prefix
    moved to another organisation leaves a stale entry, ignored (prefixes are owned at query time, ADR 0002)."""
    if doc.get("tenant"):
        held = next((t.get("prefixes") or [] for t in tenant_list if t["id"] == doc["tenant"]), [])
        return any(prefix.startswith(h) for h in held)
    return not any(tenants.overlap(prefix, p) for t in tenant_list for p in t.get("prefixes") or [])


def default_for(anchor: str, tenant: str | None) -> dict | None:
    """The verified domain whose default prefixes cover the record's company part (the longest prefix wins)."""
    part = gs1.company_part(anchor)
    best, length = None, -1
    tenant_list = tenants.load()
    for doc in verified(tenant):
        for prefix in doc.get("defaultFor") or []:
            if part.startswith(prefix) and len(prefix) > length and still_held(doc, prefix, tenant_list):
                best, length = doc, len(prefix)
    return best


def label_base(anchor: str, tenant: str | None, choice: str | None, installation_url: str) -> str:
    """The address in front of a record's GS1 path: choice "" / "default" (the default domain of its prefix, else the
    installation), "installation", or a verified domain of the scope (otherwise domains.unusable)."""
    choice = str(choice or "").strip().lower()
    if choice in ("", "default"):
        doc = default_for(anchor, tenant)
        return base_url(doc) if doc else installation_url
    if choice == "installation":
        return installation_url
    doc = _col().find_one({"_id": choice, **_scope(tenant), "verified": True})
    if not doc:
        raise gs1.ValidationError("domains.unusable", domain=choice[:100])
    return base_url(doc)


# ----------------------------------------------------------------------------------------------- changing
def _check_defaults(prefixes, tenant: str | None, own: str | None) -> list[str]:
    cleaned = users.clean_prefixes(prefixes or [])
    tenant_list = tenants.load()
    if tenant:
        held = next((t.get("prefixes") or [] for t in tenant_list if t["id"] == tenant), [])
        if any(not any(p.startswith(h) for h in held) for p in cleaned):
            raise UserError("domains.prefixOutside")
    else:
        taken = [p for t in tenant_list for p in t.get("prefixes") or []]
        if any(tenants.overlap(p, t) for p in cleaned for t in taken):
            raise UserError("domains.prefixOutside")
    for doc in _col().find({"defaultFor": {"$in": cleaned}, "_id": {"$ne": own}}):
        if any(still_held(doc, p, tenant_list) for p in cleaned if p in (doc.get("defaultFor") or [])):
            raise UserError("domains.prefixTaken", domain=doc["_id"])
    return cleaned


def create(name, mode, stem, tenant: str | None, by: str, installation: str) -> dict:
    name, mode, stem = clean_name(name, installation), clean_mode(mode), clean_stem(stem)
    with users.locked():
        if _col().find_one({"_id": name}):
            raise UserError("domains.exists")
        if _col().count_documents(_scope(tenant)) >= MAX_PER_SCOPE:
            raise UserError("domains.tooMany", max=MAX_PER_SCOPE)
        doc = {"_id": name, "mode": mode, "stem": stem, "defaultFor": [], "token": secrets.token_hex(16),
               "verified": False, "created": store.now(), "createdBy": by}
        if tenant:
            doc["tenant"] = tenant
        _col().insert_one(doc)
    return doc


def update(name, tenant: str | None, mode=None, stem=None, default_prefixes=None) -> tuple[dict, dict]:
    """Changes a domain of the scope; returns (before, after)."""
    with users.locked():
        doc = get(name, tenant)
        change = {}
        if mode is not None:
            change["mode"] = clean_mode(mode)
        if stem is not None:
            change["stem"] = clean_stem(stem)
        if default_prefixes is not None:
            change["defaultFor"] = _check_defaults(default_prefixes, tenant, doc["_id"])
        if change:
            _col().update_one({"_id": doc["_id"]}, {"$set": change})
        return doc, {**doc, **change}


def remove(name, tenant: str | None) -> dict:
    doc = get(name, tenant)
    _col().delete_one({"_id": doc["_id"]})
    return doc


# ----------------------------------------------------------------------------------------------- proof and checks
def txt_records(host: str) -> list[str]:
    """The TXT strings of a name (empty when there are none or the lookup fails). Replaced by the tests."""
    import dns.exception
    import dns.resolver
    try:
        answer = dns.resolver.resolve(host, "TXT", lifetime=TIMEOUT)
    except (dns.exception.DNSException, OSError):
        return []
    return ["".join(part.decode("utf-8", "replace") for part in record.strings) for record in answer]


def verify(name, tenant: str | None) -> dict:
    """Looks up the TXT record; a domain found is verified (and stays so). Returns the domain after the look."""
    doc = get(name, tenant)
    found = TXT_PREFIX + doc["token"] in txt_records(f"{TXT_NAME}.{doc['_id']}")
    now = store.now()
    change = {"seenAt": now} if found else {}
    if found and not doc.get("verified"):
        change.update(verified=True, verifiedAt=now)
    if change:
        _col().update_one({"_id": doc["_id"]}, {"$set": change})
    if not found and not doc.get("verified"):
        raise UserError("domains.txtMissing", name=f"{TXT_NAME}.{doc['_id']}", value=TXT_PREFIX + doc["token"])
    return {**doc, **change}


def recheck_all(now=None) -> int:
    """Daily housekeeping: looks again at the TXT record of every verified domain not seen for a day, recording when
    it was last seen (never un-verifying). Returns the number found."""
    now = now or store.now()
    found = 0
    for doc in _col().find({"verified": True}):
        if doc.get("seenAt") and now - doc["seenAt"] < RECHECK:
            continue
        if TXT_PREFIX + doc["token"] in txt_records(f"{TXT_NAME}.{doc['_id']}"):
            _col().update_one({"_id": doc["_id"]}, {"$set": {"seenAt": now}})
            found += 1
    return found


def probe(url: str) -> requests.Response:
    """One request through a domain without following redirects (public addresses only). Replaced by the tests."""
    host = requests.utils.urlparse(url).hostname or ""
    if linkcheck._public_host(host) is False:
        raise PermissionError("private address")
    return requests.get(url, allow_redirects=False, timeout=TIMEOUT,
                        headers={"User-Agent": linkcheck.USER_AGENT})


def check(name, tenant: str | None, installation_url: str, sample_anchor: str | None) -> dict:
    """Requests through the domain: direct mode, the description file at its root; redirect mode, a code of the organisation
    (sample_anchor, or a made-up GTIN of its first prefix), whose Location must be the installation's same path."""
    doc = get(name, tenant)
    base = base_url(doc)
    if doc.get("mode") == "redirect":
        path = (sample_anchor or "/01/00000000000000") + "?linkType=all"
        url, expected = base + path, installation_url.rstrip("/") + path
    else:
        url, expected = f"https://{doc['_id']}/.well-known/gs1resolver", None      # at the root, never under the stem
    result = {"at": store.now(), "url": url, "ok": False, "problem": None, "detail": None}
    try:
        answer = probe(url)
    except PermissionError:
        result["problem"] = "domains.checkPrivate"
    except requests.RequestException as exc:
        result.update(problem="domains.checkUnreachable", detail=type(exc).__name__)
    else:
        if expected is None:
            body = answer.json() if answer.headers.get("Content-Type", "").startswith("application/json") else None
            if answer.status_code == 200 and isinstance(body, dict) and body.get("resolverRoot"):
                result["ok"] = True
            else:
                result.update(problem="domains.checkNotResolver", detail=str(answer.status_code))
        else:
            location = answer.headers.get("Location", "")
            if answer.status_code in REDIRECTS and location == expected:
                result["ok"] = True
            else:
                result.update(problem="domains.checkRedirect", detail=f"{answer.status_code} {location}"[:200])
    _col().update_one({"_id": doc["_id"]}, {"$set": {"check": result}})
    return {**doc, "check": result}
