"""
Failed sign-ins that name no account, counted rather than journalled one by one (Documentation/adr/0031-request-
limits.md, section 2.3; finding F-013).

Anyone on the internet can send a sign-in with a new user name, or open the single sign-on callback without a sign-in
in progress. Journalled one by one, each would add an event kept for months (the "session" category) to the operator's
audit trail: a cheap way to fill the database and to bury the events that matter. Such failures are counted instead,
in the collection "anonymous_failures": one document per kind and hour, with the count and the first addresses seen.
The worker's hourly housekeeping (journal_closed_hours()) then writes one journal event per kind and finished hour,
"login-failed" by "-" in the operator's trail, carrying the count in its "count" field (journal.counts() adds it up)
and the addresses in its detail. Failed sign-ins that name an existing account are still journalled one by one, in its
organisation's trail: the throttle of finding F-005 bounds them per address.

Kinds: "sign-in" (a password sign-in whose user name, or e-mail address, matches no account, or is empty) and "sso"
(the provider's answer reaching the callback when this browser started no sign-in).
"""
import logging
from datetime import timedelta

import journal
import store

log = logging.getLogger("portal.failcount")

COLLECTION = "anonymous_failures"
KINDS = {"sign-in": "failed sign-ins with a user name of no account",
         "sso": "single sign-on answers without a sign-in in progress"}
SAMPLE = 10              # addresses kept per kind and hour
KEEP_DAYS = 7            # a counter stays this long after its hour (the journal keeps the event)


def _counters():
    return store.col(COLLECTION)


def note(kind: str, address: str) -> None:
    """Counts one failure of a kind from an address in the current hour; never raises (the answer does not wait on it)."""
    hour = store.now().replace(minute=0, second=0, microsecond=0)
    ident = f"{kind}|{hour.isoformat()}"
    try:
        _counters().update_one({"_id": ident},
                               {"$inc": {"n": 1},
                                "$setOnInsert": {"kind": kind, "hour": hour, "journaled": False,
                                                 "expiresAt": hour + timedelta(days=KEEP_DAYS, hours=1)}},
                               upsert=True)
        # the first addresses only: a crowd of addresses must not grow the document
        _counters().update_one({"_id": ident, f"addrs.{SAMPLE - 1}": {"$exists": False}},
                               {"$addToSet": {"addrs": str(address)[:64]}})
    except Exception as exc:                              # noqa: BLE001 — counting never changes an answer
        log.warning("Failed sign-in not counted (%s): %s", kind, exc)


def detail_of(doc: dict) -> str:
    """The journal event's detail: what was counted, the hour (UTC) and the first addresses."""
    hour = doc["hour"]
    addrs = doc.get("addrs") or []
    more = " and others" if len(addrs) >= SAMPLE else ""
    return (f'{doc["n"]} {KINDS.get(doc["kind"], doc["kind"])} between {hour:%Y-%m-%d %H:%M} and '
            f'{hour + timedelta(hours=1):%H:%M} UTC, counted (ADR 0031); addresses: {", ".join(addrs)}{more}')


def journal_closed_hours() -> int:
    """Writes one journal event per counter of a finished hour not yet journalled (the worker's housekeeping; safe in
    several workers at once: a counter is claimed before its event is written, and given back when the write fails).
    Returns the events written."""
    current = store.now().replace(minute=0, second=0, microsecond=0)
    written = 0
    while True:
        doc = _counters().find_one_and_update({"hour": {"$lt": current}, "journaled": False},
                                              {"$set": {"journaled": True}}, sort=[("hour", 1)])
        if doc is None:
            return written
        try:
            journal.append("login-failed", "-", detail=detail_of(doc), count=doc["n"])
        except Exception:
            _counters().update_one({"_id": doc["_id"]}, {"$set": {"journaled": False}})
            raise
        written += 1
