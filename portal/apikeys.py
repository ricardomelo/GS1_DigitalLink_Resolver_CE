"""
API keys of the tenant API (Documentation/adr/0005-tenant-api.md): keys that let an organisation's own systems use
/portal/api/v1 within its records, created and revoked by its administrators.

One document per key in the "api_keys" collection of the portal's database:

    {"_id": "3f9a1c0b2e7d", "hash": "<sha256 hex of the secret>", "name": "ERP integration",
     "tenant": "t-…" (absent for the operator), "scopes": ["records:read"], "prefixes": [],
     "created": <date>, "createdBy": "maria", "expiresAt": <date>, "lastUsed": <date>,
     "revoked": <date>, "revokedBy": "ana", "expiryNotice": <date>}

The key handed out once is "rk_<id>.<secret>": 12 hexadecimal digits that name it, and a 256-bit random secret of
which only the SHA-256 is kept. Revoked and expired keys stay in the collection for the audit trail.

Requests are limited per key and minute ("api_rate" collection, {_id: "<id>:<minute>", n, at}, TTL), the same
counter for every replica of the portal.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import store
import users

SCOPES = ("records:read", "records:write", "labels:read", "stats:read")
MAX_ACTIVE_KEYS = 20
NAME_LENGTH = (3, 60)
DEFAULT_DAYS = 90
KEY_FORMAT = re.compile(r"^rk_([0-9a-f]{12})\.([A-Za-z0-9_-]{43})$")
EXPIRY_NOTICE_DAYS = 7
RATE_WINDOW_SECONDS = 60


def _col():
    return store.col("api_keys")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def max_days() -> int:
    """PORTAL_API_KEY_MAX_DAYS: the longest validity an administrator may choose (default 365)."""
    text = (os.environ.get("PORTAL_API_KEY_MAX_DAYS", "") or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else 365


def rate_per_minute() -> int:
    """PORTAL_API_RATE_PER_MINUTE: requests per key and minute (default 120)."""
    text = (os.environ.get("PORTAL_API_RATE_PER_MINUTE", "") or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else 120


def _scope_query(tenant: str | None) -> dict:
    return {"tenant": tenant} if tenant else {"tenant": None}


def state(doc: dict, now: datetime | None = None) -> str:
    """active, expired or revoked."""
    now = now or store.now()
    if doc.get("revoked"):
        return "revoked"
    return "expired" if doc["expiresAt"] <= now else "active"


def public(doc: dict) -> dict:
    """What the API keys screen shows (never the hash)."""
    return {"id": doc["_id"], "name": doc["name"], "scopes": doc["scopes"], "prefixes": doc.get("prefixes") or [],
            "created": store.iso(doc.get("created")), "createdBy": doc.get("createdBy"),
            "expiresAt": store.iso(doc["expiresAt"]), "lastUsed": store.iso(doc.get("lastUsed")),
            "revoked": store.iso(doc.get("revoked")), "revokedBy": doc.get("revokedBy"), "state": state(doc)}


def load(tenant: str | None) -> list[dict]:
    """The keys of a scope (an organisation, or the operator), newest first."""
    return list(_col().find(_scope_query(tenant)).sort("created", -1))


def names(tenant: str | None, every: bool = False) -> dict[str, str]:
    """Key id → name, for a scope or (every) for the whole installation: the request log's list of API calls."""
    return {doc["_id"]: doc.get("name", "") for doc in _col().find({} if every else _scope_query(tenant), {"name": 1})}


def clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not (NAME_LENGTH[0] <= len(name) <= NAME_LENGTH[1]) or not name.isprintable():
        raise users.UserError("apikeys.nameInvalid", min=NAME_LENGTH[0], max=NAME_LENGTH[1])
    return name


def clean_scopes(values) -> list[str]:
    scopes = sorted({str(v) for v in values or []})
    if not scopes or any(s not in SCOPES for s in scopes):
        raise users.UserError("apikeys.scopesInvalid")
    return scopes


def clean_days(value) -> int:
    try:
        days = int(value if value not in (None, "") else DEFAULT_DAYS)
    except (TypeError, ValueError):
        days = 0
    if not 1 <= days <= max_days():
        raise users.UserError("apikeys.daysInvalid", max=max_days())
    return days


def create(name, scopes, days, prefixes, tenant: str | None, created_by: str) -> tuple[str, dict]:
    """A new key for a scope; returns (the full key, shown once, and its document)."""
    name, scopes, days = clean_name(name), clean_scopes(scopes), clean_days(days)
    prefixes = users.clean_prefixes(prefixes or [])
    now = store.now()
    with users.locked():
        users._check_scope(tenant, prefixes)
        active = [d for d in load(tenant) if state(d, now) == "active"]
        if len(active) >= MAX_ACTIVE_KEYS:
            raise users.UserError("apikeys.tooMany", max=MAX_ACTIVE_KEYS)
        if any(d["name"].lower() == name.lower() for d in active):
            raise users.UserError("apikeys.nameExists")
        key_id, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
        doc = {"_id": key_id, "hash": _hash(secret), "name": name, "scopes": scopes, "prefixes": prefixes,
               "created": now, "createdBy": created_by, "expiresAt": now + timedelta(days=days)}
        if tenant:
            doc["tenant"] = tenant
        _col().insert_one(doc)
    return f"rk_{key_id}.{secret}", doc


def revoke(key_id: str, tenant: str | None, by: str) -> dict:
    """Revokes a key of the scope (an unknown key, or another scope's, answers apikeys.unknown)."""
    doc = _col().find_one({"_id": str(key_id or ""), **_scope_query(tenant)})
    if not doc:
        raise users.UserError("apikeys.unknown")
    if doc.get("revoked"):
        raise users.UserError("apikeys.alreadyRevoked")
    _col().update_one({"_id": doc["_id"]}, {"$set": {"revoked": store.now(), "revokedBy": by}})
    return {**doc, "revoked": store.now(), "revokedBy": by}


def authenticate(text: str | None) -> dict | None:
    """The key document an "rk_<id>.<secret>" names, when the secret matches (constant-time) and the key is neither
    revoked nor expired; otherwise None. Whether the key's organisation may act is the caller's check."""
    match = KEY_FORMAT.match(str(text or ""))
    if not match:
        return None
    doc = _col().find_one({"_id": match.group(1)})
    if not doc or not hmac.compare_digest(doc["hash"], _hash(match.group(2))):
        return None
    return doc if state(doc) == "active" else None


def count_request(key_id: str) -> tuple[bool, int]:
    """Counts one request of a key in the current minute: (allowed, seconds to wait when not). The first request of
    a minute also records the key's last use."""
    now = datetime.now(timezone.utc)
    minute = int(now.timestamp()) // RATE_WINDOW_SECONDS
    from pymongo import ReturnDocument
    doc = store.col("api_rate").find_one_and_update(
        {"_id": f"{key_id}:{minute}"}, {"$inc": {"n": 1}, "$setOnInsert": {"at": store.now()}},
        upsert=True, return_document=ReturnDocument.AFTER)
    if doc["n"] == 1:
        _col().update_one({"_id": key_id}, {"$set": {"lastUsed": store.now()}})
    if doc["n"] > rate_per_minute():
        return False, RATE_WINDOW_SECONDS - int(now.timestamp()) % RATE_WINDOW_SECONDS
    return True, 0


def expiring(now: datetime | None = None) -> list[dict]:
    """Takes, atomically one by one, the active keys that expire within EXPIRY_NOTICE_DAYS and whose creator was not
    told yet (several workers may run the check at once: each key is taken by one)."""
    now = now or store.now()
    taken = []
    while True:
        doc = _col().find_one_and_update(
            {"revoked": None, "expiryNotice": None, "expiresAt": {"$gt": now, "$lte": now + timedelta(days=EXPIRY_NOTICE_DAYS)}},
            {"$set": {"expiryNotice": now}})
        if not doc:
            return taken
        taken.append(doc)
