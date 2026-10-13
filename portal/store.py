"""
The portal's own database: a MongoDB database of its own (PORTAL_DB_NAME, default "resolver_portal") in the
installation's MongoDB, reached with a user that may read and write that database only
(Documentation/adr/0001-portal-state-in-mongodb.md). The official resolver's database is never touched; the
portal still changes records only through the data entry API.

Connection, from the environment:
  PORTAL_DB_URI                       a complete MongoDB URI (an external server, for example); when set, the
                                      parts below are not read. "mongomock://" uses an in-memory stand-in
                                      (development tests only: mongomock is not in the image)
  PORTAL_DB_HOST                      host:port, default database-service:27017
  PORTAL_DB_USERNAME, _PASSWORD       the portal's own user, created by db_init.py (the portal-db-init service)
  PORTAL_DB_NAME                      the database, also the user's authentication database

Collections: users, record_meta, journal, login_failures, linkcheck_cache, settings, jobs and workers
(jobs.py). The indexes are made at
the first use in each process (createIndex is allowed to the readWrite role). Dates are stored as BSON dates
in UTC and come back as naive datetimes in UTC (pymongo's default).
"""
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import quote_plus

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

log = logging.getLogger("portal.store")

DB_NAME = os.environ.get("PORTAL_DB_NAME", "").strip() or "resolver_portal"
LOGIN_FAILURE_SECONDS = 15 * 60          # how long a failed sign-in counts (app.LOCKOUT_SECONDS)
WORKER_RECORD_SECONDS = 10 * 60          # a worker not seen for this long is forgotten (jobs.announce)

# Collection → indexes (key list, options). TTL indexes: MongoDB deletes a document once the date in the
# field is older than expireAfterSeconds (its monitor runs about once a minute).
INDEXES = {
    "journal": [
        ([("at", DESCENDING)], {}),
        ([("anchor", ASCENDING), ("qpath", ASCENDING), ("at", DESCENDING)], {}),
        ([("user", ASCENDING), ("at", DESCENDING)], {}),
        ([("category", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "login_failures": [
        ([("key", ASCENDING), ("at", ASCENDING)], {}),
        ([("at", ASCENDING)], {"expireAfterSeconds": LOGIN_FAILURE_SECONDS}),
    ],
    "linkcheck_cache": [
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "jobs": [
        ([("state", ASCENDING), ("created", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "workers": [
        ([("seen", ASCENDING)], {"expireAfterSeconds": WORKER_RECORD_SECONDS}),
    ],
}

_client = None
_db = None
_init_lock = threading.Lock()


class LockTimeout(Exception):
    """A lock document stayed taken longer than the caller was willing to wait."""


def uri() -> str:
    """The connection URI: PORTAL_DB_URI, or one built from PORTAL_DB_HOST / _USERNAME / _PASSWORD / _NAME."""
    explicit = os.environ.get("PORTAL_DB_URI", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("PORTAL_DB_HOST", "").strip() or "database-service:27017"
    user = os.environ.get("PORTAL_DB_USERNAME", "").strip() or "resolver_portal"
    password = os.environ.get("PORTAL_DB_PASSWORD", "")
    if not password:
        raise RuntimeError("PORTAL_DB_PASSWORD is not set: the portal cannot reach its database "
                           "(see .env.example and Documentation/adr/0001-portal-state-in-mongodb.md).")
    return f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}/{quote_plus(DB_NAME)}?authSource={quote_plus(DB_NAME)}"


def _connect():
    """A client for uri(): pymongo, or mongomock for "mongomock://"."""
    target = uri()
    if target.startswith("mongomock://"):
        import mongomock                                       # development tests only
        return mongomock.MongoClient()
    from pymongo import MongoClient
    return MongoClient(target, serverSelectionTimeoutMS=int(os.environ.get("PORTAL_DB_TIMEOUT_MS", "30000")),
                       appname="resolver-portal")


def db():
    """The portal's database (one client per process, created and indexed at the first call)."""
    global _client, _db
    if _db is None:
        with _init_lock:
            if _db is None:
                client = _connect()
                database = client[DB_NAME]
                for name, indexes in INDEXES.items():
                    for keys, options in indexes:
                        database[name].create_index(keys, **options)
                _client, _db = client, database
    return _db


def col(name: str):
    """One collection of the portal's database."""
    return db()[name]


def reset() -> None:
    """Forgets the client (tests: a new PORTAL_DB_NAME takes effect at the next call)."""
    global _client, _db, DB_NAME
    with _init_lock:
        _client = _db = None
        DB_NAME = os.environ.get("PORTAL_DB_NAME", "").strip() or "resolver_portal"


def now() -> datetime:
    """Current time in UTC, naive (as pymongo returns stored dates), to the millisecond (BSON's precision)."""
    t = datetime.now(timezone.utc).replace(tzinfo=None)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def iso(value) -> str | None:
    """A stored date as ISO 8601 with a Z, to the second (the format of the API and of the old files)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


def parse_iso(text) -> datetime | None:
    """"2026-10-13T12:00:00Z" (or a date) → naive UTC datetime; None when it cannot be read."""
    if isinstance(text, datetime):
        return text.astimezone(timezone.utc).replace(tzinfo=None) if text.tzinfo else text
    try:
        value = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def get_setting(name: str, default=None):
    """A value kept in the settings collection (document {_id: name, value: …})."""
    doc = col("settings").find_one({"_id": name})
    return doc.get("value", default) if doc else default


def set_setting(name: str, value) -> None:
    """Stores a value in the settings collection."""
    col("settings").update_one({"_id": name}, {"$set": {"value": value, "updatedAt": now()}}, upsert=True)


@contextmanager
def lock(name: str, hold_seconds: float = 60, wait_seconds: float = 30):
    """Exclusive lock shared by every process of the installation: a document {_id: "lock:<name>"} in
    settings. A lock older than hold_seconds is taken to belong to a process that died and is broken.
    Raises LockTimeout after wait_seconds."""
    settings = col("settings")
    key, owner = f"lock:{name}", uuid.uuid4().hex
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            settings.insert_one({"_id": key, "owner": owner, "since": now()})
            break
        except DuplicateKeyError:
            stale = datetime.fromtimestamp(time.time() - hold_seconds, timezone.utc).replace(tzinfo=None)
            if settings.delete_one({"_id": key, "since": {"$lt": stale}}).deleted_count:
                log.warning("Broke the lock %s, held for more than %s seconds.", name, hold_seconds)
                continue
            if time.monotonic() > deadline:
                raise LockTimeout(name)
            time.sleep(0.05)
    try:
        yield
    finally:
        settings.delete_one({"_id": key, "owner": owner})
