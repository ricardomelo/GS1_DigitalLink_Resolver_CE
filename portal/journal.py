"""
Journal of what happens in the portal: sign-ins, user administration and every record change, with the
full content of each version of a record so that it can be restored.

One document per event in the "journal" collection of the portal's database (store.py), included in the
daily backup with the rest of the database. Queries use indexes on the date, the record and the user.

Event: {"at", "user", "action", "category", "tenant"?, "byOperator"?, "anchor"?, "qpath"?, "doc"?, "detail"?,
        "expiresAt"?}
  record actions: create, update, delete (doc = the record after the change, or before a deletion),
  import (detail = counts); others: login, login-failed, login-refused, logout, password-change, user-create,
  user-update, user-reset, user-remove, export, tenant-create, tenant-update, tenant-remove, support-open,
  support-close, and with e-mail (Documentation/adr/0004-e-mail.md) password-recovery (a recovery link was
  sent), password-reset (a password chosen through a recovery or reset link), invite-accepted, preferences and
  mail-failed (a message the relay refused; never the address); with the tenant API
  (Documentation/adr/0005-tenant-api.md) api-key-create and api-key-revoke. Changes made through the API are record
  events whose user is "api:<key id>".

"tenant" is the tenant whose audit trail the event belongs to (Documentation/adr/0002-tenants.md, section 3.5);
none for the operator, which is also what events written before tenants existed are. "byOperator" marks what an
operator user (a server administrator) did to a tenant, so that the operator's trail shows it too.

Retention by age, per category (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.5):
  PORTAL_JOURNAL_SESSION_DAYS  login, login-failed, login-refused, logout,       default 180
                               password-recovery
  PORTAL_JOURNAL_RECORD_DAYS   create, update, delete, import                    default 0 (kept for ever)
  PORTAL_JOURNAL_ADMIN_DAYS    password-change, user-*, export and anything else  default 0 (kept for ever)
An event is kept for the days of its category counted from the end of the day (UTC) it was made: expiresAt
is that midnight plus the days (none when 0), and MongoDB's TTL monitor deletes it after that. Whole days keep
the rule simple and let apply_retention() bring older events in line, one day at a time, when a value
changes.
"""
import logging
import os
from datetime import datetime, timedelta

from pymongo import ASCENDING, DESCENDING

import store

log = logging.getLogger("portal.journal")

RECORD_ACTIONS = ("create", "update", "delete")
CATEGORIES = {
    "session": ("login", "login-failed", "login-refused", "logout", "password-recovery"),
    "record": ("create", "update", "delete", "import"),
}
RETENTION_VARIABLES = {"session": ("PORTAL_JOURNAL_SESSION_DAYS", 180),
                       "record": ("PORTAL_JOURNAL_RECORD_DAYS", 0),
                       "admin": ("PORTAL_JOURNAL_ADMIN_DAYS", 0)}
OUTPUT_FIELDS = ("at", "user", "action", "tenant", "byOperator", "anchor", "qpath", "doc", "detail")


def category(action: str) -> str:
    """session, record or admin (the retention category of an action)."""
    for name, actions in CATEGORIES.items():
        if action in actions:
            return name
    return "admin"


def retention_days() -> dict[str, int]:
    """Days each category is kept ({"session": 180, "record": 0, "admin": 0}; 0 = for ever), from the environment."""
    days = {}
    for name, (variable, default) in RETENTION_VARIABLES.items():
        text = os.environ.get(variable, "").strip()
        try:
            days[name] = max(0, int(text)) if text else default
        except ValueError:
            log.warning("%s=%r is not a number of days: using %d.", variable, text, default)
            days[name] = default
    return days


def _day(at) -> datetime:
    """Midnight (UTC) at the start of the day of `at`."""
    return datetime(at.year, at.month, at.day)


def expires_at(at, cat: str, days: dict[str, int] | None = None):
    """When an event of that category, made at `at`, expires: the end of its day plus the category's days
    (None: kept for ever)."""
    keep = (days or retention_days())[cat]
    return _day(at) + timedelta(days=keep + 1) if keep else None


def _journal():
    return store.col("journal")


def event_document(at, user: str, action: str, days: dict[str, int] | None = None, **fields) -> dict:
    """The stored form of an event (also used by the migration of journal.jsonl)."""
    cat = category(action)
    doc = {"at": at, "user": user, "action": action, "category": cat,
           **{k: v for k, v in fields.items() if v is not None}}
    expiry = expires_at(at, cat, days)
    if expiry is not None:
        doc["expiresAt"] = expiry
    return doc


def append(action: str, user: str, **fields) -> None:
    """Adds one event to the journal."""
    _journal().insert_one(event_document(store.now(), user, action, **fields))


def _output(doc: dict, with_doc: bool = True) -> dict:
    """An event as the API returns it (the format of the former journal.jsonl lines)."""
    event = {k: doc[k] for k in OUTPUT_FIELDS if k in doc and (with_doc or k != "doc")}
    event["at"] = store.iso(doc.get("at"))
    return event


def for_record(anchor: str, qpath: str, tenant: str | None = None, limit: int = 20) -> list[dict]:
    """The latest versions of one record made while it belonged to `tenant` (None: the operator), newest first."""
    query = {"anchor": anchor, "action": {"$in": list(RECORD_ACTIONS)},
             "qpath": qpath if qpath else {"$in": ["", None]}, "tenant": tenant}
    cursor = _journal().find(query).sort([("at", DESCENDING), ("_id", DESCENDING)]).limit(limit)
    return [_output(doc) for doc in cursor]


def scope_query(tenant: str | None, operator_view: bool = False) -> dict:
    """The events of one audit trail: a tenant's ({"tenant": id}); the operator's (no tenant) and, for the
    server administrator (operator_view), what operator users did to tenants."""
    if tenant:
        return {"tenant": tenant}
    if operator_view:
        return {"$or": [{"tenant": None}, {"byOperator": True}]}
    return {"tenant": None}


def search(user: str | None = None, since: str | None = None, until: str | None = None,
           text: str | None = None, allowed=None, limit: int = 500, scope: dict | None = None) -> list[dict]:
    """Events newest first, without record contents. since/until are ISO dates (inclusive);
    text matches the anchor, qualifiers, action or detail; allowed(anchor) filters records by permission;
    scope (scope_query()) limits the events to one audit trail."""
    query: dict = dict(scope or {})
    if user:
        query["user"] = user
    bounds = {}
    start = store.parse_iso(f"{since}T00:00:00") if since else None
    end = store.parse_iso(f"{until}T00:00:00") if until else None
    if start:
        bounds["$gte"] = start
    if end:
        bounds["$lt"] = end + timedelta(days=1)
    if bounds:
        query["at"] = bounds
    needle = (text or "").lower()
    found = []
    cursor = _journal().find(query, {"doc": 0}).sort([("at", DESCENDING), ("_id", DESCENDING)])
    for event in cursor:
        if needle and needle not in " ".join(str(event.get(k, "")) for k in ("anchor", "qpath", "action", "detail")).lower():
            continue
        if allowed and event.get("anchor") and not allowed(event["anchor"]):
            continue
        found.append(_output(event, with_doc=False))
        if len(found) >= limit:
            break
    return found


def apply_retention() -> dict[str, int]:
    """Recalculates expiresAt of the events of every category whose retention changed since the last start
    (the values in use are kept in settings "journalRetention"), one day at a time, under a lock so that
    replicas starting together do it once. Returns the number of events updated per category."""
    days = retention_days()
    changed = {}
    if store.get_setting("journalRetention") == days:
        return changed
    journal = _journal()
    with store.lock("retention", hold_seconds=1800, wait_seconds=1800):
        previous = store.get_setting("journalRetention") or {}
        for cat, keep in days.items():
            if previous.get(cat) == keep:
                continue
            if not keep:
                count = journal.update_many({"category": cat}, {"$unset": {"expiresAt": ""}}).modified_count
            else:
                count = 0
                first = journal.find_one({"category": cat}, {"at": 1}, sort=[("at", ASCENDING)])
                last = journal.find_one({"category": cat}, {"at": 1}, sort=[("at", DESCENDING)])
                day = _day(first["at"]) if first else None
                while day is not None and day <= last["at"]:
                    following = day + timedelta(days=1)
                    count += journal.update_many({"category": cat, "at": {"$gte": day, "$lt": following}},
                                                 {"$set": {"expiresAt": day + timedelta(days=keep + 1)}}).modified_count
                    day = following
            changed[cat] = count
            if previous:
                log.info("Journal retention of %s events is now %s; %d event(s) updated.",
                         cat, f"{keep} days" if keep else "for ever", count)
        store.set_setting("journalRetention", days)
    return changed
