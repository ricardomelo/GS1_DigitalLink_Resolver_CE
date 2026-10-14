"""
Single-use links of the portal: invitations and password recovery (Documentation/adr/0004-e-mail.md, section 3.3).

A link carries a random token (256 bits) in its fragment: <portal>/portal/login#invite=<token> or #reset=<token>.
Only the token's SHA-256 is stored, in the "tokens" collection of the portal's database:

    {"_id": "<sha256 hex>", "purpose": "invite" | "reset", "user": "maria", "created": <date>, "expiresAt": <date>}

MongoDB removes a document once expiresAt has passed (TTL index, store.py); the date is also checked here, since
its monitor runs only about once a minute. A new link replaces the user's earlier link of the same purpose;
consume() takes the document atomically, so a link works once even when two requests race.
"""
import hashlib
import os
import secrets
from datetime import timedelta

import store

PURPOSES = ("invite", "reset")
DEFAULT_HOURS = {"invite": 72.0, "reset": 1.0}
SETTINGS = {"invite": ("PORTAL_INVITE_HOURS", 1.0), "reset": ("PORTAL_RESET_MINUTES", 1 / 60)}


def _col():
    return store.col("tokens")


def _hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def validity_hours(purpose: str) -> float:
    """How long a link of that purpose is valid, in hours: PORTAL_INVITE_HOURS (default 72) or
    PORTAL_RESET_MINUTES (default 60), at least one minute."""
    variable, factor = SETTINGS[purpose]
    text = (os.environ.get(variable, "") or "").strip()
    try:
        value = float(text) * factor if text else DEFAULT_HOURS[purpose]
    except ValueError:
        value = DEFAULT_HOURS[purpose]
    return max(value, 1 / 60)


def issue(user: str, purpose: str) -> str:
    """A new token for the user (the earlier one of that purpose stops working); only its hash is stored."""
    assert purpose in PURPOSES
    token = secrets.token_urlsafe(32)
    now = store.now()
    _col().delete_many({"user": user, "purpose": purpose})
    _col().insert_one({"_id": _hash(token), "purpose": purpose, "user": user, "created": now,
                       "expiresAt": now + timedelta(hours=validity_hours(purpose))})
    return token


def peek(token: str) -> dict | None:
    """{"user", "purpose", "expiresAt"} of a valid token, without using it; None when unknown or expired."""
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        return None
    return _col().find_one({"_id": _hash(token), "expiresAt": {"$gt": store.now()}},
                           {"_id": 0, "user": 1, "purpose": 1, "expiresAt": 1})


def consume(token: str) -> dict | None:
    """Takes a valid token (it works once): its document, or None when unknown, expired or already used."""
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        return None
    return _col().find_one_and_delete({"_id": _hash(token), "expiresAt": {"$gt": store.now()}})


def purge(user: str, purpose: str | None = None) -> int:
    """Removes the user's links (of one purpose, or all); returns how many."""
    query = {"user": user, **({"purpose": purpose} if purpose else {})}
    return _col().delete_many(query).deleted_count


def link(token: str, purpose: str, base: str) -> str:
    """The address a message carries: the sign-in page with the token in the fragment."""
    return f"{base.rstrip('/')}/portal/login#{purpose}={token}"
