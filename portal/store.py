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

Collections: users, tenants (tenants.py), record_meta, login_failures, linkcheck_cache, settings, jobs
and workers (jobs.py), sessions (sessions.py: open sessions of the portal, ADR 0034), tokens (tokens.py: invitation
and recovery links), api_keys and api_rate (apikeys.py: the tenant
API's keys and request counters), request_daily and api_requests (requestlog.py: daily counts of the resolver's
requests and the tenant API's calls). The journal, journal and journal_heads (journal.py, ADR 0026), lives in a
database of its own, "<PORTAL_DB_NAME>_journal" (journal_db_name()), where the portal's user may read and insert
events but neither change nor delete them (db_init.py's role journalAppend, ADR 0026 section 2.5.2); col() routes
those two names there, so callers need not know. The resolver's own log, resolver_log.requests, is another database that the
portal's user may only read (db_init.py, Documentation/adr/0006-resolver-request-log.md). The indexes are made at
the first use in each process (createIndex is allowed to the readWrite role; in the journal's database only
portal-db-init may make them, so a refusal there is expected and ignored). Dates are stored as BSON dates
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
from pymongo.errors import DuplicateKeyError, OperationFailure

log = logging.getLogger("portal.store")

DB_NAME = os.environ.get("PORTAL_DB_NAME", "").strip() or "resolver_portal"
JOURNAL_COLLECTIONS = ("journal", "journal_heads")   # in journal_db_name(), insert-only for the portal (ADR 0026)
UNAUTHORIZED = 13                                     # MongoDB's error code for an action the user may not take
LOGIN_FAILURE_SECONDS = 15 * 60          # how long a failed sign-in counts (app.LOCKOUT_SECONDS)
WORKER_RECORD_SECONDS = 10 * 60          # a worker not seen for this long is forgotten (jobs.announce)

# Collection → indexes (key list, options). TTL indexes: MongoDB deletes a document once the date in the
# field is older than expireAfterSeconds (its monitor runs about once a minute).
INDEXES = {
    "journal": [
        ([("at", DESCENDING)], {}),
        ([("anchor", ASCENDING), ("qpath", ASCENDING), ("at", DESCENDING)], {}),
        ([("user", ASCENDING), ("at", DESCENDING)], {}),
        ([("tenant", ASCENDING), ("at", DESCENDING)], {}),
        ([("category", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
        # The hash chains of ADR 0026: one event per sequence number of a chain (unsealed events are left out)
        ([("chain", ASCENDING), ("seq", ASCENDING)], {"unique": True,
                                                      "partialFilterExpression": {"seq": {"$exists": True}}}),
    ],
    "login_failures": [
        ([("key", ASCENDING), ("at", ASCENDING)], {}),
        ([("at", ASCENDING)], {"expireAfterSeconds": LOGIN_FAILURE_SECONDS}),
    ],
    # failed sign-ins naming no account, counted per hour (failcount.py, ADR 0031)
    "anonymous_failures": [
        ([("journaled", ASCENDING), ("hour", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
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
    # open sessions of the portal (sessions.py, ADR 0034)
    "sessions": [
        ([("user", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    # the QR codes' domains and the claims of them (domains.py, ADR 0035): a claim not verified is deleted at expiresAt
    "domains": [
        ([("name", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "tokens": [
        ([("user", ASCENDING), ("purpose", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "api_keys": [
        ([("tenant", ASCENDING), ("created", DESCENDING)], {}),
        ([("expiresAt", ASCENDING)], {}),
    ],
    "api_rate": [
        ([("at", ASCENDING)], {"expireAfterSeconds": 120}),
    ],
    "request_daily": [
        ([("day", ASCENDING)], {}),
        ([("cp", ASCENDING), ("day", ASCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "alert_history": [
        ([("raisedAt", DESCENDING)], {}),
        ([("tenant", ASCENDING), ("raisedAt", DESCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
    "api_requests": [
        ([("t", DESCENDING)], {}),
        # the minute's document of the calls without a valid key (requestlog.record_api_call(), ADR 0031)
        ([("b", ASCENDING)], {"unique": True, "partialFilterExpression": {"b": {"$exists": True}}}),
        ([("tenant", ASCENDING), ("t", DESCENDING)], {}),
        ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ],
}

_client = None
_db = None
_journal_db = None
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


def journal_db_name() -> str:
    """The journal's database: the portal's database name followed by "_journal" (no setting of its own)."""
    return f"{DB_NAME}_journal"


def _make_indexes(collection, indexes) -> None:
    for keys, options in indexes:
        collection.create_index(keys, **options)


def db():
    """The portal's database (one client per process, created and indexed at the first call)."""
    global _client, _db, _journal_db
    if _db is None:
        with _init_lock:
            if _db is None:
                client = _connect()
                database, journal_database = client[DB_NAME], client[journal_db_name()]
                for name, indexes in INDEXES.items():
                    if name not in JOURNAL_COLLECTIONS:
                        _make_indexes(database[name], indexes)
                        continue
                    try:
                        _make_indexes(journal_database[name], indexes)
                    except OperationFailure as exc:
                        # The portal's user may not make indexes in the journal's database (a TTL index could
                        # delete every event): portal-db-init made them with the root user.
                        if exc.code != UNAUTHORIZED:
                            raise
                _client, _db, _journal_db = client, database, journal_database
    return _db


def col(name: str):
    """One collection of the portal's database; journal and journal_heads come from the journal's database."""
    database = db()
    return _journal_db[name] if name in JOURNAL_COLLECTIONS else database[name]


def reset() -> None:
    """Forgets the client (tests: a new PORTAL_DB_NAME takes effect at the next call)."""
    global _client, _db, _journal_db, DB_NAME
    with _init_lock:
        _client = _db = _journal_db = None
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
