"""
The log of resolver requests, as the portal reads it (Documentation/adr/0006-resolver-request-log.md).

The resolver writes one event per resolution request into the collection "requests" of the database "resolver_log"
(web_server/src/request_log.py); the portal's database user may only read it (db_init.py). This module:

  - turns the scope of a request (app.set_scope(): an organisation, the user's own prefixes, the operator, or the whole
    installation for a server administrator) into a filter on the events' company part ("cp"): ownership is derived at
    query time, so a prefix moved between organisations takes its history along;
  - lists events (newest first, in pages) and turns them into rows for the screen and the CSV export;
  - counts each day's events per primary key into the portal's collection "request_daily" (aggregate(), run by the
    worker's hourly housekeeping), in the installation's time zone, kept PORTAL_STATS_DAYS;
  - records the tenant API's calls (record_api_call(), collection "api_requests") and lists them.

Settings:
  RESOLVER_LOG_DAYS    days raw events and API calls are kept (the resolver reads it too); 0: the log is off (90)
  PORTAL_TIME_ZONE     the time zone of the aggregates' days, an IANA name (UTC)
  PORTAL_STATS_DAYS    days the daily aggregates are kept (800)
"""
import logging
import math
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING

import store

log = logging.getLogger("portal.requestlog")

LOG_DB = "resolver_log"
EVENTS = "requests"
DAILY = "request_daily"
API_CALLS = "api_requests"
OUTCOMES = ("redirect", "choice", "linkset", "unknown", "noLink", "invalid", "error", "compressed")
DEVICES = ("mobile", "tablet", "desktop", "automated", "unknown")
FORMS = ("uri", "compressed", "epc")
MAX_PAGE = 500
DEFAULT_PAGE = 200
MAX_EXPORT = 50_000
FINAL_AFTER = timedelta(minutes=10)        # a day is counted for the last time this long after it ended
TOP = 20                                   # languages and link types kept per key and day
SETTING_FINAL = "requestStats.finalUntil"


# ----------------------------------------------------------------------------------------------- settings
def _int_env(name: str, default: int) -> int:
    text = os.environ.get(name, "").strip()
    try:
        return max(0, int(text)) if text else default
    except ValueError:
        log.warning("%s=%r is not a number of days: using %d.", name, text, default)
        return default


def log_days() -> int:
    """RESOLVER_LOG_DAYS (0: the log is off)."""
    return _int_env("RESOLVER_LOG_DAYS", 90)


def stats_days() -> int:
    """PORTAL_STATS_DAYS: how long daily aggregates are kept (0 is taken as 1)."""
    return max(1, _int_env("PORTAL_STATS_DAYS", 800))


def zone() -> ZoneInfo:
    """PORTAL_TIME_ZONE, or UTC when it is empty or unknown."""
    name = os.environ.get("PORTAL_TIME_ZONE", "").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("PORTAL_TIME_ZONE=%r is not a known time zone: using UTC.", name)
        return ZoneInfo("UTC")


def utc_naive(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The UTC interval [start, end) of a day of the installation's time zone (naive, as stored dates)."""
    tz = zone()
    start = datetime.combine(day, time(0), tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tz)
    return utc_naive(start), utc_naive(end)


def local_day(moment: datetime) -> date:
    """The installation's day of a stored (naive UTC) date."""
    return moment.replace(tzinfo=timezone.utc).astimezone(zone()).date()


def today() -> date:
    return datetime.now(zone()).date()


def parse_day(text) -> date | None:
    try:
        return date.fromisoformat(str(text).strip()[:10]) if text else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- collections
def events():
    """The resolver's events (read only for the portal's user)."""
    return store.db().client[LOG_DB][EVENTS]


def daily():
    return store.col(DAILY)


def api_calls():
    return store.col(API_CALLS)


# ----------------------------------------------------------------------------------------------- scope
def _prefix_pattern(prefixes) -> str:
    return "^(?:" + "|".join(re.escape(p) for p in prefixes) + ")"


def _prefix_regex(prefixes) -> re.Pattern:
    return re.compile(_prefix_pattern(prefixes))


def scope_filter(tenant_list: list[dict], tenant_id: str | None, prefixes, whole: bool) -> dict:
    """The events (or aggregates) a scope reaches, as a filter on "cp":
      whole        a server administrator outside support access: everything (also events without a key);
      tenant_id    the organisation's prefixes;
      None         the operator: keys that no organisation's prefix starts;
    narrowed in both last cases to the user's own prefixes, if any."""
    if whole:
        return {}
    parts = []
    if tenant_id:
        tenant = next((t for t in tenant_list if t["id"] == tenant_id), None)
        held = (tenant or {}).get("prefixes") or []
        parts.append({"cp": {"$regex": _prefix_pattern(held)}} if held else {"cp": {"$in": []}})
    else:
        taken = [p for t in tenant_list for p in t.get("prefixes") or []]
        parts.append({"cp": {"$exists": True, "$not": _prefix_regex(taken)}} if taken else {"cp": {"$exists": True}})
    if prefixes:
        parts.append({"cp": {"$regex": _prefix_pattern(prefixes)}})
    return parts[0] if len(parts) == 1 else {"$and": parts}


def owner_of(cp: str | None, tenant_list: list[dict]) -> str | None:
    """Id of the organisation whose prefix starts a company part, or None (the operator)."""
    if not cp:
        return None
    for tenant in tenant_list:
        if any(cp.startswith(p) for p in tenant.get("prefixes") or []):
            return tenant["id"]
    return None


# ----------------------------------------------------------------------------------------------- listing events
class FilterError(ValueError):
    """A filter of the request cannot be read: the message code and parameters."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _interval(args) -> dict:
    """{"t": {"$gte": …, "$lt": …}} for from/to (days of the installation, both included)."""
    t = {}
    first, last = args.get("from"), args.get("to")
    if first:
        day = parse_day(first)
        if not day:
            raise FilterError("requests.badDate", value=str(first)[:20])
        t["$gte"] = day_bounds(day)[0]
    if last:
        day = parse_day(last)
        if not day:
            raise FilterError("requests.badDate", value=str(last)[:20])
        t["$lt"] = day_bounds(day)[1]
    return {"t": t} if t else {}


def _code_filter(text: str) -> dict:
    """A code typed by the user: an anchor ("/01/0789…"), a key value or the start of one, a GS1 Company Prefix or a
    GTIN-13 (matched against the company part)."""
    text = (text or "").strip()
    if not text:
        return {}
    parts = [p for p in text.split("/") if p]
    if text.startswith("/") and len(parts) >= 2:
        return {"ai": parts[0], "v": parts[1]}
    value = re.sub(r"[\s()]", "", text)[:100]
    pattern = "^" + re.escape(value)
    return {"$or": [{"v": {"$regex": pattern}}, {"cp": {"$regex": pattern}}]}


def event_query(args, scope: dict) -> dict:
    """The query of a listing: scope, period, code, outcome, device class; automated requests are left out unless
    asked for (automated=1, or device=automated)."""
    parts = [scope] if scope else []
    parts.append(_interval(args))
    parts.append(_code_filter(args.get("code", "")))
    outcome = (args.get("outcome") or "").strip()
    if outcome:
        if outcome == "notFound":
            parts.append({"o": {"$in": ["unknown", "noLink"]}})
        elif outcome in OUTCOMES:
            parts.append({"o": outcome})
        else:
            raise FilterError("requests.badFilter", name="outcome")
    device = (args.get("device") or "").strip()
    if device:
        if device not in DEVICES:
            raise FilterError("requests.badFilter", name="device")
        parts.append({"dev": device})
    elif str(args.get("automated", "")).strip() not in ("1", "true", "yes"):
        parts.append({"dev": {"$ne": "automated"}})
    parts = [p for p in parts if p]
    return {} if not parts else parts[0] if len(parts) == 1 else {"$and": parts}


def _after(cursor_text: str | None) -> dict:
    """The page after a cursor "<ISO time>|<event id>" (newest first)."""
    if not cursor_text:
        return {}
    at_text, _, ident = str(cursor_text).partition("|")
    at = store.parse_iso(at_text)
    try:
        oid = ObjectId(ident)
    except (InvalidId, TypeError):
        oid = None
    if at is None or oid is None:
        raise FilterError("requests.badFilter", name="before")
    return {"$or": [{"t": {"$lt": at}}, {"t": at, "_id": {"$lt": oid}}]}


def _iso_ms(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


def qualifier_path(q: dict | None) -> str:
    """{"10": "L1", "21": None} → "/10/L1/21/*"."""
    return "".join(f"/{ai}/{'*' if value is None else value}" for ai, value in (q or {}).items())


def row(doc: dict, tenant_names: dict | None = None, tenant_list: list[dict] | None = None) -> dict:
    """An event as the API answers it."""
    out = {
        "id": str(doc.get("_id", "")), "at": _iso_ms(doc["t"]) if isinstance(doc.get("t"), datetime) else None,
        "method": doc.get("m"), "form": doc.get("f"), "epc": doc.get("epc"),
        "key": doc.get("ai"), "value": doc.get("v"),
        "anchor": f"/{doc['ai']}/{doc['v']}" if doc.get("ai") and doc.get("v") is not None else None,
        "qualifiers": qualifier_path(doc.get("q")), "attributes": doc.get("da") or [],
        "linkType": doc.get("lt"), "status": doc.get("s"), "outcome": doc.get("o"), "level": doc.get("lvl"),
        "target": doc.get("to"), "ms": doc.get("ms"), "language": doc.get("lang"), "device": doc.get("dev"),
        "referrer": doc.get("ref"), "country": doc.get("c"), "path": doc.get("p"),
    }
    if tenant_names is not None:
        owner = owner_of(doc.get("cp"), tenant_list or [])
        out["organisation"] = tenant_names.get(owner) if owner else None
    return out


def list_events(args, scope: dict, limit: int | None = None, organisations: list[dict] | None = None) -> dict:
    """{"events": [...], "next": cursor or None}: the newest events matching the request's filters in the scope.
    organisations: every tenant, to name each event's organisation (a server administrator's view)."""
    try:
        size = int(args.get("limit") or DEFAULT_PAGE) if limit is None else limit
    except (TypeError, ValueError):
        raise FilterError("requests.badFilter", name="limit")
    size = max(1, min(size, MAX_PAGE if limit is None else MAX_EXPORT))
    query = event_query(args, scope)
    after = _after(args.get("before"))
    if after:
        query = {"$and": [query, after]} if query else after
    docs = list(events().find(query).sort([("t", DESCENDING), ("_id", DESCENDING)]).limit(size + 1))
    names = {t["id"]: t["name"] for t in organisations} if organisations is not None else None
    rows = [row(doc, names, organisations) for doc in docs[:size]]
    following = None
    if len(docs) > size:
        last = docs[size - 1]
        following = f"{_iso_ms(last['t'])}|{last['_id']}"
    return {"events": rows, "next": following}


# ----------------------------------------------------------------------------------------------- per day
def per_day(scope: dict, whole: bool, days: int = 30) -> list[dict]:
    """Requests per day of the installation's time zone for the last `days` days (today included), oldest first:
    {"day", "total", "automated", "outcome": {...}}. Past days come from the aggregates; today from the raw events
    (the aggregates may be up to an hour behind)."""
    days = max(1, min(int(days), 400))
    last = today()
    first = last - timedelta(days=days - 1)
    found: dict[str, dict] = {}
    if whole:
        query = {"day": {"$gte": first.isoformat(), "$lt": last.isoformat()}, "ai": {"$exists": False}}
    else:
        query = {"$and": [scope, {"day": {"$gte": first.isoformat(), "$lt": last.isoformat()}},
                          {"ai": {"$exists": True}}]}
    for doc in daily().find(query, {"day": 1, "total": 1, "automated": 1, "outcome": 1}):
        entry = found.setdefault(doc["day"], {"total": 0, "automated": 0, "outcome": {}})
        entry["total"] += doc.get("total", 0)
        entry["automated"] += doc.get("automated", 0)
        for name, n in (doc.get("outcome") or {}).items():
            entry["outcome"][name] = entry["outcome"].get(name, 0) + n
    start, end = day_bounds(last)
    match = {"t": {"$gte": start, "$lt": end}}
    raw_query = {"$and": [scope, match]} if scope else match
    entry = {"total": 0, "automated": 0, "outcome": {}}
    for group in events().aggregate([{"$match": raw_query},
                                     {"$group": {"_id": {"o": "$o", "dev": "$dev"}, "n": {"$sum": 1}}}]):
        n = group["n"]
        entry["total"] += n
        if group["_id"].get("dev") == "automated":
            entry["automated"] += n
        name = group["_id"].get("o") or "unknown"
        entry["outcome"][name] = entry["outcome"].get(name, 0) + n
    found[last.isoformat()] = entry
    out = []
    for i in range(days):
        day = (first + timedelta(days=i)).isoformat()
        out.append({"day": day, **found.get(day, {"total": 0, "automated": 0, "outcome": {}})})
    return out


# ----------------------------------------------------------------------------------------------- aggregates
def _bump(counter: dict, name, n: int) -> None:
    if name is None:
        name = "-"
    counter[name] = counter.get(name, 0) + n


def _top(counter: dict) -> list[list]:
    return [[name, n] for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:TOP]]


def _empty() -> dict:
    return {"total": 0, "automated": 0, "outcome": {}, "device": {}, "form": {}, "language": {}, "linkType": {},
            "ms": 0, "msMax": 0}


def _percentile(match: dict, count: int, percent: int):
    """The time taken at a percentile among `count` events with a time (nearest rank)."""
    if not count:
        return None
    rank = max(1, math.ceil(percent / 100 * count))
    found = list(events().find({**match, "ms": {"$exists": True}}, {"ms": 1}).sort("ms", 1).skip(rank - 1).limit(1))
    return found[0]["ms"] if found else None


def count_day(day: date, run: str | None = None) -> int:
    """Counts one day's events into request_daily: a document per primary key and one for the whole installation.
    Replaces that day's documents (those not produced again are removed). Returns the number of keys."""
    run = run or uuid.uuid4().hex
    start, end = day_bounds(day)
    match = {"t": {"$gte": start, "$lt": end}}
    groups = events().aggregate([
        {"$match": match},
        {"$group": {"_id": {"ai": "$ai", "v": "$v", "cp": "$cp", "o": "$o", "dev": "$dev", "f": "$f",
                            "lang": "$lang", "lt": "$lt"},
                    "n": {"$sum": 1}, "ms": {"$sum": "$ms"}, "max": {"$max": "$ms"}}}])
    keys: dict[tuple, dict] = {}
    whole = _empty()
    for group in groups:
        g, n = group["_id"], group["n"]
        targets = [whole]
        if g.get("cp"):
            entry = keys.get((g.get("ai"), g.get("v")))
            if entry is None:
                entry = keys[(g.get("ai"), g.get("v"))] = {**_empty(), "cp": g["cp"]}
            targets.append(entry)
        for t in targets:
            t["total"] += n
            if g.get("dev") == "automated":
                t["automated"] += n
            _bump(t["outcome"], g.get("o"), n)
            _bump(t["device"], g.get("dev"), n)
            _bump(t["form"], g.get("f"), n)
            if g.get("lang"):
                _bump(t["language"], g["lang"], n)
            if g.get("lt"):
                _bump(t["linkType"], g["lt"], n)
            t["ms"] += group.get("ms") or 0
            t["msMax"] = max(t["msMax"], group.get("max") or 0)
    expires = utc_naive(datetime.combine(day + timedelta(days=1), time(0), timezone.utc)) + timedelta(days=stats_days())
    key = day.isoformat()
    target = daily()
    for (ai, value), entry in keys.items():
        target.replace_one({"_id": f"{key}|{ai}|{value}"},
                           {"day": key, "ai": ai, "v": value, **entry, "language": _top(entry["language"]),
                            "linkType": _top(entry["linkType"]), "run": run, "expiresAt": expires}, upsert=True)
    timed = events().count_documents({**match, "ms": {"$exists": True}})
    target.replace_one({"_id": f"{key}|*"},
                       {"day": key, **whole, "language": _top(whole["language"]), "linkType": _top(whole["linkType"]),
                        "keys": len(keys), "p50": _percentile(match, timed, 50), "p95": _percentile(match, timed, 95),
                        "p99": _percentile(match, timed, 99), "run": run, "expiresAt": expires}, upsert=True)
    target.delete_many({"day": key, "run": {"$ne": run}})
    return len(keys)


def aggregate(now: datetime | None = None) -> int:
    """The worker's hourly housekeeping: counts every day from the one after the last finished day counted up to today
    (the first time, from the oldest raw event), then records which days are finished. One replica at a time (a lock);
    another one finding it taken skips the run. Returns the number of days counted."""
    if not log_days():
        return 0
    try:
        with store.lock("request-stats", hold_seconds=1800, wait_seconds=0):
            return _aggregate(now)
    except store.LockTimeout:
        return 0


def _aggregate(now: datetime | None) -> int:
    tz = zone()
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    current = moment.date()
    final = parse_day(store.get_setting(SETTING_FINAL))
    if final:
        first = final + timedelta(days=1)
    else:
        oldest = next(iter(events().find({}, {"t": 1}).sort("t", 1).limit(1)), None)
        first = local_day(oldest["t"]) if oldest else current
    first = max(first, current - timedelta(days=log_days()))
    counted = 0
    day = first
    while day <= current:
        count_day(day)
        counted += 1
        day += timedelta(days=1)
    finished = current - timedelta(days=1)
    if moment - datetime.combine(current, time(0), tz) < FINAL_AFTER:
        finished -= timedelta(days=1)        # yesterday's last events may still be on their way
    if not final or finished > final:
        store.set_setting(SETTING_FINAL, finished.isoformat())
    return counted


# ----------------------------------------------------------------------------------------------- tenant API calls
def record_api_call(key: dict | None, method: str, operation: str | None, status: int, ms: int) -> None:
    """One call of /portal/api/v1 (ADR 0006, decision 8): never the record, the query string or the key's secret."""
    days = log_days()
    if not days:
        return
    now = store.now()
    doc = {"t": now, "expiresAt": now + timedelta(days=days), "m": method, "op": (operation or "")[:120],
           "s": status, "ms": ms}
    if key:
        doc["key"] = key.get("_id")
        if key.get("tenant"):
            doc["tenant"] = key["tenant"]
    api_calls().insert_one(doc)


def list_api_calls(args, tenant_id: str | None, whole: bool, keys: dict, organisations: list[dict]) -> dict:
    """The tenant API's calls of a scope, newest first: an organisation's (or the operator's keys' for its
    administrators), or every one for a server administrator. keys: id → name of the keys known in the scope."""
    parts = [] if whole else [{"tenant": tenant_id} if tenant_id else {"tenant": {"$exists": False}}]
    interval = _interval(args)
    if interval:
        parts.append(interval)
    key = (args.get("key") or "").strip()
    if key:
        parts.append({"key": key})
    try:
        size = max(1, min(int(args.get("limit") or DEFAULT_PAGE), MAX_PAGE))
    except (TypeError, ValueError):
        raise FilterError("requests.badFilter", name="limit")
    after = _after(args.get("before"))
    if after:
        parts.append(after)
    query = {} if not parts else parts[0] if len(parts) == 1 else {"$and": parts}
    docs = list(api_calls().find(query).sort([("t", DESCENDING), ("_id", DESCENDING)]).limit(size + 1))
    names = {t["id"]: t["name"] for t in organisations}
    rows = [{"id": str(d["_id"]), "at": _iso_ms(d["t"]), "key": d.get("key"), "keyName": keys.get(d.get("key")),
             "organisation": names.get(d.get("tenant")) if d.get("tenant") else None,
             "method": d.get("m"), "operation": d.get("op"), "status": d.get("s"), "ms": d.get("ms")}
            for d in docs[:size]]
    following = f"{_iso_ms(docs[size - 1]['t'])}|{docs[size - 1]['_id']}" if len(docs) > size else None
    return {"calls": rows, "next": following}
