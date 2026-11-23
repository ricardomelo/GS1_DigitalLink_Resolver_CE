"""
Journal of what happens in the portal: sign-ins, user administration and every record change, with the
full content of each version of a record so that it can be restored.

One document per event in the "journal" collection of the journal's database (store.py: "<PORTAL_DB_NAME>_journal",
where the portal's user may read and insert only; ADR 0026 section 2.5.2), included in the
daily backup with the rest of the database. Queries use indexes on the date, the record and the user.

Event: {"at", "user", "action", "category", "tenant"?, "byOperator"?, "anchor"?, "qpath"?, "doc"?, "detail"?,
        "expiresAt"?}
  record actions: create, update, delete (doc = the record after the change, or before a deletion),
  import (detail = counts); others: import-refused (a queued import stopped because its account may no longer write,
  ADR 0041), login, login-failed, login-refused, logout, password-change, user-create,
  user-update, user-reset, user-remove, user-create-refused (an organisation's administrator tried a user name
  held by another organisation; in the operator's trail, ADR 0036), export, tenant-create, tenant-update, tenant-remove, support-open,
  support-close, and with e-mail (Documentation/adr/0004-e-mail.md) password-recovery (a recovery link was
  sent), password-reset (a password chosen through a recovery or reset link), invite-accepted, preferences and
  mail-failed (a message the relay refused; never the address); with the tenant API
  (Documentation/adr/0005-tenant-api.md) api-key-create and api-key-revoke. Changes made through the API are record
  events whose user is "api:<key id>". requests-export: the log of resolver requests exported as CSV
  (Documentation/adr/0006-resolver-request-log.md); requestlog-retention: how long it is kept, changed (section 8).

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

Integrity (Documentation/adr/0026-journal-integrity.md): every event is sealed in a hash chain, one per audit trail and
retention category ("<tenant id or operator>/<category>", chain_of()), so retention only ever removes a chain's
beginning. Seal fields: chain, seq (1, 2, … in the chain), prev (the previous event's hash, "" for the first), hash
(SHA-256 of the canonical JSON of every field but _id, expiresAt, hash and mac), mac (HMAC-SHA-256 of hash with
PORTAL_JOURNAL_KEY, absent without a key) and kid (key_id() of the key). A unique index on (chain, seq) numbers events
safely across replicas; "journal_heads" keeps each chain's last seq and hash outside the retention. Events written
before this version are sealed by seal_unsealed(), marked sealed "upgrade": by portal-db-init when it moves them to the
journal's database (root user), and at the portal's start-up where its user may still update the journal (an
external MongoDB without portal-db-init); expiresAt follows a retention change the same way (apply_retention()).
verify() walks a chain;
checkpoint() (the worker's housekeeping) verifies every chain, writes the heads to the log and stores the result in
settings "journalVerified" ({at, chains, broken: [{chain, kind, seq}]}), which an administrator's verification brings
up to date (record_verification()) and the monitor's check "journal" reads (alert by e-mail, ADR 0026 section 2.5). A record change is
journalled before the data entry API is called (app.journal_first()); a failed one adds change-failed with ref
{chain, seq} of the attempt.
"""
import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timedelta

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

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
KEY_VARIABLE = "PORTAL_JOURNAL_KEY"
UNHASHED = ("_id", "expiresAt", "hash", "mac")      # every other stored field is sealed
APPEND_TRIES = 50                                    # writers racing for the same chain retry this often
FAILED_ACTION = "change-failed"
VERIFIED_SETTING = "journalVerified"                 # the last verification's result, read by monitor.check_journal()
_append_lock = threading.Lock()     # threads of one process take turns; processes race on the unique index


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


def append(action: str, user: str, **fields) -> dict:
    """Adds one event to the journal, sealed in its chain; returns {"chain", "seq"} (the ref of change-failed)."""
    doc = _insert_sealed(event_document(store.now(), user, action, **fields))
    return {"chain": doc["chain"], "seq": doc["seq"]}


# ------------------------------------------------------------------ integrity (ADR 0026)
def key() -> bytes | None:
    """The journal key (PORTAL_JOURNAL_KEY), None when it is not set."""
    text = os.environ.get(KEY_VARIABLE, "")
    return text.encode() if text.strip() else None


def key_id(secret: bytes | None) -> str:
    """The identifier of a key stored with each seal: the first 8 hexadecimal digits of its SHA-256 ("" without a key)."""
    return hashlib.sha256(secret).hexdigest()[:8] if secret else ""


def chain_of(doc: dict) -> str:
    """The chain of an event: its audit trail (tenant id, or operator) and its retention category."""
    return f'{doc.get("tenant") or "operator"}/{doc.get("category") or category(doc.get("action", ""))}'


def _canonical(value):
    """JSON for what json cannot write: dates to the millisecond with a Z (as MongoDB stores them)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"
    return str(value)


def content_hash(doc: dict) -> str:
    """SHA-256 of an event's sealed content: every field but _id, expiresAt, hash and mac, keys sorted."""
    content = {k: v for k, v in doc.items() if k not in UNHASHED}
    text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_canonical)
    return hashlib.sha256(text.encode()).hexdigest()


def mac_of(digest: str, secret: bytes) -> str:
    return hmac.new(secret, digest.encode(), hashlib.sha256).hexdigest()


def _heads():
    return store.col("journal_heads")


def _head(chain: str) -> tuple[int, str]:
    """(seq, hash) of a chain's newest event: the newer of the journal's last event and journal_heads."""
    last = _journal().find_one({"chain": chain, "seq": {"$exists": True}}, {"seq": 1, "hash": 1},
                               sort=[("seq", DESCENDING)])
    head = _heads().find_one({"_id": chain}) or {}
    if last and last["seq"] >= head.get("seq", 0):
        return last["seq"], last["hash"]
    return head.get("seq", 0), head.get("hash", "")


def _seal(doc: dict, chain: str, seq: int, prev: str, secret: bytes | None) -> dict:
    for field in ("hash", "mac"):
        doc.pop(field, None)
    doc.update(chain=chain, seq=seq, prev=prev, kid=key_id(secret))
    doc["hash"] = content_hash(doc)
    if secret:
        doc["mac"] = mac_of(doc["hash"], secret)
    return doc


def _move_head(chain: str, seq: int, digest: str) -> None:
    """journal_heads follows a chain forward, never back (another writer may already be further)."""
    try:
        _heads().update_one({"_id": chain, "seq": {"$lt": seq}}, {"$set": {"seq": seq, "hash": digest,
                                                                           "at": store.now()}}, upsert=True)
    except DuplicateKeyError:
        pass                                          # the head is already at or past seq


def _insert_sealed(doc: dict, existing_id=None) -> dict:
    """Seals an event as the next of its chain and stores it (inserted, or the stored unsealed event existing_id
    updated); a writer that loses the race for a sequence number reads the head again."""
    with _append_lock:
        return _insert_sealed_locked(doc, existing_id)


def _insert_sealed_locked(doc: dict, existing_id) -> dict:
    chain, secret = chain_of(doc), key()
    for _ in range(APPEND_TRIES):
        seq, prev = _head(chain)
        sealed = _seal(doc, chain, seq + 1, prev, secret)
        try:
            if existing_id is None:
                _journal().insert_one(sealed)
            else:
                fields = {k: sealed[k] for k in ("chain", "seq", "prev", "kid", "hash", "mac", "sealed") if k in sealed}
                _journal().update_one({"_id": existing_id}, {"$set": fields})
        except DuplicateKeyError:
            continue
        _move_head(chain, sealed["seq"], sealed["hash"])
        return sealed
    raise store.LockTimeout(f"journal chain {chain}")


def append_upgraded(doc: dict) -> int:
    """Seals and inserts an event of an earlier version (migrate.py's journal.jsonl), marked sealed "upgrade", as the
    next of its chain; an event whose _id is already stored is left alone. Returns 1 when inserted, else 0."""
    if _journal().find_one({"_id": doc["_id"]}, {"_id": 1}):
        return 0
    doc["sealed"] = "upgrade"
    _insert_sealed(doc)
    return 1


def seal_unsealed(ids=None) -> int:
    """Seals the events stored without a seal (written before ADR 0026, or by an older replica during an upgrade),
    in the order they were written, marked sealed "upgrade"; under a lock so that replicas starting together do it
    once. ids limits it to those events: portal-db-init seals only the events it moved itself, never one that
    someone inserted unsealed in the journal's database (that one stays unsealed and the verification reports it).
    Returns how many were sealed."""
    journal = _journal()
    unsealed = {"seq": {"$exists": False}}
    if ids is not None:
        unsealed["_id"] = {"$in": list(ids)}
    if not journal.find_one(unsealed, {"_id": 1}):
        return 0
    count = 0
    with store.lock("journal-seal", hold_seconds=3600, wait_seconds=3600):
        for doc in journal.find(unsealed).sort([("at", ASCENDING), ("_id", ASCENDING)]):
            doc["sealed"] = "upgrade"
            _insert_sealed(doc, existing_id=doc["_id"])
            count += 1
            if count % 10000 == 0:
                log.info("Journal: %d events sealed so far.", count)
    if count:
        log.info("Journal: %d event(s) written before ADR 0026 sealed in their chains.", count)
    return count


def receipt_text(chain: str, seq: int, digest: str) -> str:
    """A chain's head as the administrator keeps it: <chain>:<seq>:<hash>."""
    return f"{chain}:{seq}:{digest}"


def parse_receipt(text: str) -> tuple[str, int, str] | None:
    """(chain, seq, hash) of a receipt, None when it is not one."""
    parts = (text or "").strip().rsplit(":", 2)
    if len(parts) != 3 or not parts[1].isdigit() or len(parts[2]) != 64 \
            or any(c not in "0123456789abcdef" for c in parts[2]):
        return None
    return parts[0], int(parts[1]), parts[2]


def chains(tenant: str | None = None, everything: bool = False) -> list[str]:
    """The chains of one audit trail (a tenant's, or the operator's with tenant None), or every chain (everything):
    those with a head or an event, sorted."""
    found = set(_heads().distinct("_id")) | set(_journal().distinct("chain"))
    found.discard(None)
    if not everything:
        trail = (tenant or "operator") + "/"
        found = {c for c in found if c.startswith(trail)}
    return sorted(found)


def verify(chain: str, receipt: tuple[str, int, str] | None = None) -> dict:
    """Walks one chain by sequence number: {"chain", "events", "first", "last", "head", "keyed", "otherKey" (events
    sealed without the current key or with another one: their links are checked, not their mac), "ok", "problem"?:
    {"kind", "seq"}, "receipt"?: true | false}. Problems, the first found: hash (an event changed), mac (a seal of the
    current key that does not match), prev (a broken link), gap (an event missing), start (a
    chain kept for ever that does not start at 1), truncated (shorter than journal_heads), unsealed (events not yet
    sealed in this trail), receipt (a kept head not in the chain)."""
    secret = key()
    kid = key_id(secret)
    cat = chain.rsplit("/", 1)[-1]
    result = {"chain": chain, "events": 0, "first": None, "last": None, "head": None, "keyed": bool(secret),
              "otherKey": 0, "ok": True}
    problem = None
    previous = None
    receipt_seen = None
    for doc in _journal().find({"chain": chain}).sort("seq", ASCENDING):
        seq = doc.get("seq")
        result["events"] += 1
        if result["first"] is None:
            result["first"] = seq
            if seq != 1 and not retention_days().get(cat):
                problem = problem or {"kind": "start", "seq": seq}
        if problem is None:
            if content_hash(doc) != doc.get("hash"):
                problem = {"kind": "hash", "seq": seq}
            elif previous is not None and seq != previous["seq"] + 1:
                problem = {"kind": "gap", "seq": previous["seq"] + 1}
            elif previous is not None and doc.get("prev") != previous["hash"]:
                problem = {"kind": "prev", "seq": seq}
            elif secret and doc.get("kid") == kid and not hmac.compare_digest(
                    doc.get("mac", ""), mac_of(doc["hash"], secret)):
                problem = {"kind": "mac", "seq": seq}
        if doc.get("kid") != kid:
            result["otherKey"] += 1
        if receipt and receipt[0] == chain and seq == receipt[1]:
            receipt_seen = doc.get("hash") == receipt[2]
        previous = {"seq": seq, "hash": doc.get("hash")}
    if previous:
        result["last"] = previous["seq"]
        result["head"] = receipt_text(chain, previous["seq"], previous["hash"])
    stored = _heads().find_one({"_id": chain}) or {}
    if problem is None and stored.get("seq", 0) > (result["last"] or 0):
        problem = {"kind": "truncated", "seq": stored["seq"]}
    if problem is None:
        tenant = None if chain.startswith("operator/") else chain.split("/", 1)[0]
        unsealed = _journal().count_documents({"seq": {"$exists": False}, "tenant": tenant, "category": cat})
        if unsealed:
            problem = {"kind": "unsealed", "seq": None, "count": unsealed}
    if receipt and receipt[0] == chain:
        result["receipt"] = bool(receipt_seen)
        if not receipt_seen and problem is None:
            problem = {"kind": "receipt", "seq": receipt[1]}
    if problem:
        result["ok"] = False
        result["problem"] = problem
    return result


def checkpoint() -> list[dict]:
    """The worker's daily check (app.HOUSEKEEPING runs it about once an hour; it acts once a day): verifies every
    chain and writes each head to the portal's log, which leaves the database; a broken chain is logged as an error."""
    today = _day(store.now())
    if store.get_setting("journalCheckpoint") == store.iso(today):
        return []
    results = [verify(chain) for chain in chains(everything=True)]
    for result in results:
        if result["ok"]:
            log.info("Journal head %s (%d events).", result["head"], result["events"])
        else:
            log.error("Journal chain %s broken: %s at %s (head %s).", result["chain"], result["problem"]["kind"],
                      result["problem"].get("seq"), result["head"])
    store.set_setting(VERIFIED_SETTING, {"at": store.now(), "chains": len(results),
                                         "broken": [_broken(r) for r in results if not r["ok"]]})
    store.set_setting("journalCheckpoint", store.iso(today))
    return results


def _broken(result: dict) -> dict:
    return {"chain": result["chain"], "kind": result["problem"]["kind"], "seq": result["problem"].get("seq")}


def record_verification(results: list[dict]) -> None:
    """An administrator's verification (GET /portal/api/audit/verify) brings the stored result up to date for the
    chains it walked, so that the monitor's alert (ADR 0026, section 2.5) does not wait for the next day: a broken
    chain is added, a chain found whole again is taken out. A receipt that is not in its chain is shown to the
    administrator who typed it and is not stored (anyone can type a wrong one)."""
    stored = store.get_setting(VERIFIED_SETTING) or {}
    walked = {r["chain"] for r in results}
    broken = [b for b in stored.get("broken") or [] if b.get("chain") not in walked]
    broken += [_broken(r) for r in results if not r["ok"] and r["problem"]["kind"] != "receipt"]
    if broken == (stored.get("broken") or []):
        return
    store.set_setting(VERIFIED_SETTING, {**stored, "at": stored.get("at") or store.now(), "broken": broken})


def last_verification() -> dict | None:
    """The stored result of the last verification: {"at", "chains", "broken": [{"chain", "kind", "seq"}]}, None
    before the first."""
    found = store.get_setting(VERIFIED_SETTING)
    return found if isinstance(found, dict) else None


def _output(doc: dict, with_doc: bool = True) -> dict:
    """An event as the API returns it (the format of the former journal.jsonl lines)."""
    event = {k: doc[k] for k in OUTPUT_FIELDS if k in doc and (with_doc or k != "doc")}
    event["at"] = store.iso(doc.get("at"))
    return event


def for_record(anchor: str, qpath: str, tenant: str | None = None, limit: int = 20) -> list[dict]:
    """The latest versions of one record made while it belonged to `tenant` (None: the operator), newest first,
    leaving out attempts that a change-failed event names (ADR 0026, section 2.1)."""
    query = {"anchor": anchor, "action": {"$in": list(RECORD_ACTIONS)},
             "qpath": qpath if qpath else {"$in": ["", None]}, "tenant": tenant}
    failed = {(e["ref"].get("chain"), e["ref"].get("seq"))
              for e in _journal().find({"anchor": anchor, "action": FAILED_ACTION, "tenant": tenant}, {"ref": 1})
              if isinstance(e.get("ref"), dict)}
    versions = []
    for doc in _journal().find(query).sort([("at", DESCENDING), ("_id", DESCENDING)]):
        if (doc.get("chain"), doc.get("seq")) in failed:
            continue
        versions.append(_output(doc))
        if len(versions) >= limit:
            break
    return versions


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


def counts(scope: dict, start: datetime, end: datetime, allowed=None) -> tuple[dict[str, int], dict[str, int]]:
    """Events of one audit trail (scope_query()) made in [start, end): ({action: count}, {user: record changes}),
    leaving out record events that allowed(anchor) refuses (the overview, Documentation/adr/0007-overview-indicators.md).
    """
    query = {**(scope or {}), "at": {"$gte": start, "$lt": end}}
    actions: dict[str, int] = {}
    by_user: dict[str, int] = {}
    for event in _journal().find(query, {"action": 1, "user": 1, "anchor": 1, "count": 1}):
        if allowed and event.get("anchor") and not allowed(event["anchor"]):
            continue
        action = event.get("action", "")
        # an event standing for several (failed sign-ins naming no account, counted an hour at a time: ADR 0031)
        actions[action] = actions.get(action, 0) + max(1, int(event.get("count") or 1))
        if action in CATEGORIES["record"]:
            user = event.get("user", "-")
            by_user[user] = by_user.get(user, 0) + 1
    return actions, by_user


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
