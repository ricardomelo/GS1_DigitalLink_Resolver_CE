"""
Server-side session records of the portal (Documentation/adr/0034-session-records.md, finding F-016).

The signed session cookie carries a random session id (256 bits) under "sid"; the "sessions" collection of the
portal's database keeps one document per open session, under the id's SHA-256 (a copy of the database gives no
usable cookie):

    {"_id": "<sha256 hex>", "user": "maria", "via": "password" | "sso", "created": <date>, "seen": <date>,
     "expiresAt": <date>}

A request is signed in only while its cookie is validly signed (Flask, the idle limit) and names a record of the
same user that has not expired. Ending a record ends the session for every copy of the cookie: signing out ends
this one; a password change ends the others (this browser gets a new id); a password set or cleared, an account
disabled or removed and an organisation disabled end them all (users.py, tenants.py).

expiresAt is the idle limit after the last renewal plus the renewal interval (so the record never ends before the
cookie's own idle limit), capped at the absolute limit after the sign-in; MongoDB removes a document once it has
passed (TTL index, store.py) and the date is also checked here. A record is renewed at most once per renewal
interval (a minute, or a quarter of the idle limit when shorter), not at every request.
"""
import hashlib
import secrets
from datetime import timedelta

import store

COOKIE_KEY = "sid"
VIAS = ("password", "sso")


def _col():
    return store.col("sessions")


def digest(sid) -> str:
    """The key under which a session id is stored."""
    return hashlib.sha256(str(sid or "").encode("utf-8")).hexdigest()


def renewal_seconds(idle_seconds: float) -> float:
    """How often a record's end is moved forward while the session is used."""
    return min(60.0, idle_seconds / 4)


def _end(created, seen, idle_seconds: float, max_seconds: float):
    return min(seen + timedelta(seconds=idle_seconds + renewal_seconds(idle_seconds)),
               created + timedelta(seconds=max_seconds))


def open_record(user: str, via: str, idle_seconds: float, max_seconds: float) -> str:
    """A new session of the user; returns its id, for the cookie (only its digest is stored)."""
    assert via in VIAS
    sid = secrets.token_urlsafe(32)
    now = store.now()
    _col().insert_one({"_id": digest(sid), "user": user, "via": via, "created": now, "seen": now,
                       "expiresAt": _end(now, now, idle_seconds, max_seconds)})
    return sid


def valid(sid, user: str, idle_seconds: float, max_seconds: float) -> bool:
    """Whether the session id names an open session of the user; renews its end when due."""
    if not isinstance(sid, str) or not 20 <= len(sid) <= 100 or not user:
        return False
    now = store.now()
    record = _col().find_one({"_id": digest(sid), "user": user, "expiresAt": {"$gt": now}})
    if not record:
        return False
    if now - record["seen"] >= timedelta(seconds=renewal_seconds(idle_seconds)):
        _col().update_one({"_id": record["_id"], "user": user},
                          {"$set": {"seen": now, "expiresAt": _end(record["created"], now, idle_seconds, max_seconds)}})
    return True


def end(sid) -> None:
    """Ends one session (signing out)."""
    if isinstance(sid, str) and sid:
        _col().delete_one({"_id": digest(sid)})


def end_user(user: str, keep=None) -> int:
    """Ends every session of the user (but the one named by keep); returns how many."""
    query = {"user": user, **({"_id": {"$ne": digest(keep)}} if keep else {})}
    return _col().delete_many(query).deleted_count


def end_users(names) -> int:
    """Ends every session of these users (an organisation disabled); returns how many."""
    names = list(names)
    return _col().delete_many({"user": {"$in": names}}).deleted_count if names else 0
