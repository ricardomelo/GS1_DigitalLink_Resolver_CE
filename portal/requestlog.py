"""
The log of resolver requests, as the portal reads it (Documentation/adr/0006-resolver-request-log.md).

The resolver writes one event per resolution request into the collection "requests" of the database "resolver_log"
(web_server/src/request_log.py); the portal's database user may only read it (db_init.py). This module:

  - turns the scope of a request (app.set_scope(): an organisation, the user's own prefixes, the operator, or the whole
    installation for a server administrator) into a filter on the events' company part ("cp"): ownership is derived at
    query time, so a prefix moved between organisations takes its history along;
  - lists events (newest first, in pages) and turns them into rows for the screen and the CSV export;
  - counts each day's events per primary key into the portal's collection "request_daily" (aggregate(), run by the
    worker's hourly housekeeping), in the installation's time zone, kept PORTAL_STATS_DAYS, together with the counts
    the resolver keeps instead of events for automated requests and requests without a key ("request_counts", ADR
    0006, section 11); the housekeeping deletes such events recorded before that change once their day is counted
    (fold_noise());
  - records the tenant API's calls (record_api_call(), collection "api_requests") and lists them;
  - keeps the retention set in the portal (ADR 0006, section 8): the installation's days (server administrators) and
    each organisation's, never longer; the resolver reads both to date each event's expiry, and the worker's
    housekeeping deletes what a shortened retention no longer keeps (apply_retention()); the space the log uses, and
    the most it may use (ADR 0006, section 9): beyond it, the housekeeping deletes the oldest events (apply_size_limit())
    and the monitoring warns from 80 % of it (monitor.py).

Settings:
  RESOLVER_LOG_DAYS    the default days raw events and API calls are kept until the portal sets them (the resolver
                       reads it too); 0: the log is off (90)
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

import gs1
import store

log = logging.getLogger("portal.requestlog")

LOG_DB = "resolver_log"
EVENTS = "requests"
COUNTS = "request_counts"                 # automated requests and requests without a key, counted (section 11)
DAILY = "request_daily"
API_CALLS = "api_requests"
# page and click: the item's page and its buttons, people following a scan (Documentation/adr/0011-item-page.md)
OUTCOMES = ("redirect", "choice", "linkset", "unknown", "noLink", "invalid", "error", "compressed", "page", "click",
            "forwarded", "fallback")           # sent to another resolver (ADR 0018)
DEVICES = ("mobile", "tablet", "desktop", "automated", "unknown")
BROWSERS = ("chrome", "safari", "firefox", "edge", "samsung", "opera", "app", "other")
FORMS = ("uri", "compressed", "epc", "landing")
MAX_PAGE = 500
DEFAULT_PAGE = 200
MAX_EXPORT = 50_000
FINAL_AFTER = timedelta(minutes=10)        # a day is counted for the last time this long after it ended
TOP = 20                                   # languages and link types kept per key and day
SETTING_FINAL = "requestStats.finalUntil"
# The events left out since section 11 deleted up to this time. Was "requestLog.foldedUntil" until probes recorded with
# a key that is none (see NOISE) became noise: a new name, so every counted day is looked at once more
SETTING_FOLDED = "requestLog.noiseFoldedUntil"
KEYS = sorted(gs1.PRIMARY_KEYS)             # an event's "ai" must be one of them: the resolver's KEY_AIS
KEY_SET = frozenset(KEYS)
# Events now counted, not stored: automated clients' and those naming no GS1 primary key (no "ai", or a probe's first
# segment such as "wp-admin", which resolvers before 23 October 2026 recorded as one)
NOISE = {"$or": [{"dev": "automated"}, {"ai": {"$nin": KEYS}}]}
SETTING_DAYS = "requestLog.days"            # the installation's retention (the resolver reads it: request_log.py)
MAX_DAYS = 3650
SETTING_MAX = "requestLog.maxBytes"         # the most space the log may use on disk (ADR 0006, section 9)
MEGABYTE = 1 << 20                          # as the screens count it (1,024 × 1,024 bytes)
MAX_MEGABYTES = 10_000_000                  # about 10 TB
TRIM_TO = 0.95                              # a log beyond its limit is cut down to this share of it


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


def global_days() -> int:
    """The installation's retention: the portal's setting, or RESOLVER_LOG_DAYS until one is set; 0 when the log is
    off."""
    if not log_days():
        return 0
    value = store.get_setting(SETTING_DAYS)
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_DAYS else log_days()


def tenant_days(tenant: dict | None, whole: int | None = None) -> int:
    """The days an organisation's events are kept: its own, never longer than the installation's (0: the log is off)."""
    whole = global_days() if whole is None else whole
    own = (tenant or {}).get("logDays")
    return min(own, whole) if isinstance(own, int) and own >= 1 and whole else whole


def days_for(tenant_id: str | None, tenant_list: list[dict]) -> int:
    """The retention that applies to a scope: an organisation's, or the installation's for the operator."""
    tenant = next((t for t in tenant_list if t["id"] == tenant_id), None) if tenant_id else None
    return tenant_days(tenant)


class RetentionError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _days_value(value, maximum: int):
    if isinstance(value, bool):
        raise RetentionError("requests.retentionInvalid", max=maximum)
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise RetentionError("requests.retentionInvalid", max=maximum)
    if not 1 <= n <= maximum:
        raise RetentionError("requests.retentionInvalid", max=maximum)
    return n


def set_global_days(value) -> int:
    """Sets the installation's retention (1 to MAX_DAYS days); returns it."""
    if not log_days():
        raise RetentionError("requests.retentionOff")
    n = _days_value(value, MAX_DAYS)
    store.set_setting(SETTING_DAYS, n)
    return n


def set_tenant_days(tenant_id: str, value) -> int | None:
    """Sets an organisation's retention (1 to the installation's days), or None to follow the installation's."""
    if not log_days():
        raise RetentionError("requests.retentionOff")
    if value is None or str(value).strip() == "":
        store.col("tenants").update_one({"_id": tenant_id}, {"$unset": {"logDays": ""}})
        return None
    n = _days_value(value, global_days())
    store.col("tenants").update_one({"_id": tenant_id}, {"$set": {"logDays": n}})
    return n


def apply_retention(now: datetime | None = None, tenant_list: list[dict] | None = None) -> int:
    """The worker's hourly housekeeping: deletes the events (and tenant API calls) older than the retention that applies
    to them — an organisation's by its prefixes, the rest by the installation's. Events carry their expiry, so this
    matters only after a retention was shortened. One replica at a time; returns the number of events deleted."""
    if not log_days():
        return 0
    try:
        with store.lock("request-retention", hold_seconds=1800, wait_seconds=0):
            return _apply_retention(now, tenant_list)
    except store.LockTimeout:
        return 0


def _apply_retention(now: datetime | None, tenant_list: list[dict] | None) -> int:
    import tenants as tenants_module
    moment = utc_naive(now or datetime.now(timezone.utc))
    tenant_list = tenants_module.load() if tenant_list is None else tenant_list
    whole = global_days()
    deleted = events().delete_many({"t": {"$lt": moment - timedelta(days=whole)}}).deleted_count
    api_calls().delete_many({"t": {"$lt": moment - timedelta(days=whole)}})
    for tenant in tenant_list:
        days = tenant_days(tenant, whole)
        if days < whole:
            cutoff = moment - timedelta(days=days)
            if tenant.get("prefixes"):
                deleted += events().delete_many({"cp": {"$regex": _prefix_pattern(tenant["prefixes"])},
                                                 "t": {"$lt": cutoff}}).deleted_count
            api_calls().delete_many({"tenant": tenant["id"], "t": {"$lt": cutoff}})
    if deleted:
        log.info("Request log: %d event(s) older than their retention deleted.", deleted)
    return deleted


def _collstats() -> dict:
    """The database's statistics of the events' collection, or {} when it does not give them."""
    try:
        return store.db().client[LOG_DB].command("collstats", EVENTS)
    except Exception:          # noqa: BLE001 — no such command (mongomock), no collection yet, no right
        return {}


def space(scope: dict | None = None) -> dict:
    """The space the log uses: the whole collection (size on disk, indexes, events, and "used": what counts against the
    limit) when scope is None; otherwise the scope's events and an estimate of their size (events × the average event).
    Sizes are None when the database does not say (mongomock)."""
    stats = _collstats()
    average = stats.get("avgObjSize")
    if scope is None:
        count = stats.get("count")
        if count is None:
            count = events().estimated_document_count()
        return {"events": count, "bytes": stats.get("storageSize"), "indexBytes": stats.get("totalIndexSize"),
                "dataBytes": stats.get("size"), "used": used_bytes(stats)}
    count = events().count_documents(scope)
    return {"events": count, "bytes": round(count * average) if average else None}


def used_bytes(stats: dict | None = None) -> int | None:
    """What counts against the limit: the collection's file without the space freed inside it (which MongoDB reuses
    for new events; the file itself does not shrink), plus its indexes. None when the database does not say."""
    stats = _collstats() if stats is None else stats
    storage, indexes = stats.get("storageSize"), stats.get("totalIndexSize")
    if storage is None:
        return None
    return max(0, int(storage) - int(stats.get("freeStorageSize") or 0)) + int(indexes or 0)


def max_bytes() -> int | None:
    """The most space the log may use (bytes), or None: no limit."""
    value = store.get_setting(SETTING_MAX)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def set_max_megabytes(value) -> int | None:
    """Sets the most space the log may use, in megabytes (1 to MAX_MEGABYTES), or None (empty) for no limit; returns
    it in bytes."""
    if value is None or str(value).strip() == "":
        store.col("settings").delete_one({"_id": SETTING_MAX})
        return None
    if isinstance(value, bool):
        raise RetentionError("requests.spaceInvalid", max=MAX_MEGABYTES)
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise RetentionError("requests.spaceInvalid", max=MAX_MEGABYTES)
    if not 1 <= n <= MAX_MEGABYTES:
        raise RetentionError("requests.spaceInvalid", max=MAX_MEGABYTES)
    store.set_setting(SETTING_MAX, n * MEGABYTE)
    return n * MEGABYTE


def space_share(stats: dict | None = None) -> dict | None:
    """{"used", "max", "share"} (share: used ÷ max) when a limit is set and the database gives the sizes; else None."""
    limit = max_bytes()
    if not limit:
        return None
    used = used_bytes(stats)
    return None if used is None else {"used": used, "max": limit, "share": used / limit}


def apply_size_limit(stats: dict | None = None) -> int:
    """The worker's hourly housekeeping: a log beyond its limit loses its oldest events, down to TRIM_TO of the limit
    (the number estimated from the average event's share of the space). One replica at a time; returns the number of
    events deleted."""
    if not log_days():
        return 0
    try:
        with store.lock("request-size", hold_seconds=1800, wait_seconds=0):
            return _apply_size_limit(stats)
    except store.LockTimeout:
        return 0


def _apply_size_limit(stats: dict | None) -> int:
    stats = _collstats() if stats is None else stats
    measured = space_share(stats)
    if not measured or measured["used"] <= measured["max"]:
        return 0
    count = stats.get("count") or events().estimated_document_count()
    if not count:
        return 0
    per_event = measured["used"] / count
    excess = math.ceil((measured["used"] - measured["max"] * TRIM_TO) / per_event)
    excess = min(count, max(1, excess))
    last = list(events().find({}, {"t": 1}).sort("t", 1).skip(excess - 1).limit(1))
    if not last:
        return 0
    deleted = events().delete_many({"t": {"$lte": last[0]["t"]}}).deleted_count
    if deleted:
        log.warning("Request log beyond its limit (%d of %d bytes): the %d oldest event(s) deleted.",
                    measured["used"], measured["max"], deleted)
        try:
            import journal
            journal.append("requestlog-trimmed", "-", detail=f"events={deleted}")
        except Exception as exc:   # noqa: BLE001 — the journal never stops the housekeeping
            log.warning("Journal event not written: %s", exc)
    return deleted


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
def counts():
    return store.db().client[LOG_DB][COUNTS]


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
    asked for (automated=1, or device=automated). Only events of a GS1 primary key: those of probes recorded before
    23 October 2026 wait in the collection until fold_noise() deletes them."""
    parts = [scope] if scope else []
    parts.append({"ai": {"$in": KEYS}})
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
    browser = (args.get("browser") or "").strip()
    if browser:
        if browser not in BROWSERS:
            raise FilterError("requests.badFilter", name="browser")
        parts.append({"br": browser})
    country = (args.get("country") or "").strip().upper()
    if country:
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise FilterError("requests.badFilter", name="country")
        parts.append({"c": country})
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
        "referrer": doc.get("ref"), "country": doc.get("c"), "browser": doc.get("br"), "region": doc.get("rg"),
        "city": doc.get("ci"), "path": doc.get("p"),
        "latitude": (doc.get("ll") or [None, None])[0], "longitude": (doc.get("ll") or [None, None])[1],
    }
    if tenant_names is not None:
        owner = owner_of(doc.get("cp"), tenant_list or [])
        out["organisation"] = tenant_names.get(owner) if owner else None
    return out


MAX_PLACES = 5000


def places(args, scope: dict) -> dict:
    """The map of requests (ADR 0006, section 10): the requests a listing's filters select, counted per country and per
    place (country, region, city) with the place's position when the resolver recorded one (the city's, to a tenth of
    a degree); the MAX_PLACES most frequent places. {"countries": [[code, n]], "places": [{country, region, city,
    position, requests}], "total", "located"} — requests without a country are in total only."""
    match = event_query(args, scope)
    countries, total, located = [], 0, 0
    for group in events().aggregate([{"$match": match}, {"$group": {"_id": "$c", "n": {"$sum": 1}}}]):
        total += group["n"]
        if group["_id"]:
            located += group["n"]
            countries.append([group["_id"], group["n"]])
    countries.sort(key=lambda c: (-c[1], c[0]))
    found = events().aggregate([
        {"$match": {"$and": [match, {"c": {"$exists": True}}]} if match else {"c": {"$exists": True}}},
        {"$group": {"_id": {"c": "$c", "rg": "$rg", "ci": "$ci"}, "n": {"$sum": 1}, "ll": {"$max": "$ll"}}},
        {"$sort": {"n": -1}}, {"$limit": MAX_PLACES}])
    out = [{"country": g["_id"].get("c"), "region": g["_id"].get("rg"), "city": g["_id"].get("ci"),
            "position": g.get("ll") if isinstance(g.get("ll"), list) and len(g["ll"]) == 2 else None,
            "requests": g["n"]} for g in found]
    out.sort(key=lambda p: (-p["requests"], p["country"] or "", p["region"] or "", p["city"] or ""))
    return {"countries": countries, "places": out, "total": total, "located": located}


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
    count_query = {"$and": [scope, _quarters(start, end)]} if scope else _quarters(start, end)
    for group in [*events().aggregate([{"$match": raw_query},
                                       {"$group": {"_id": {"o": "$o", "dev": "$dev"}, "n": {"$sum": 1}}}]),
                  *counts().aggregate([{"$match": count_query},
                                       {"$group": {"_id": {"o": "$o", "dev": "$dev"}, "n": {"$sum": "$n"}}}])]:
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
            "browser": {}, "country": {}, "place": {}, "ms": 0, "msMax": 0}


def place_of(group: dict) -> str | None:
    """"BR|Sao Paulo|Campinas" for a group with a city (region may be empty), None otherwise."""
    if not group.get("ci"):
        return None
    return f'{group.get("c") or ""}|{group.get("rg") or ""}|{group["ci"]}'


def _group_doc(g: dict, n: int, ms: int, longest: int) -> dict:
    """A group of raw events (count_day, collect) as an aggregate document."""
    place = place_of(g)
    return {"total": n, "automated": n if g.get("dev") == "automated" else 0, "ms": ms or 0, "msMax": longest or 0,
            "outcome": {g.get("o") or "-": n}, "device": {g.get("dev") or "-": n}, "form": {g.get("f") or "-": n},
            "language": {g["lang"]: n} if g.get("lang") else {}, "linkType": {g["lt"]: n} if g.get("lt") else {},
            "browser": {g["br"]: n} if g.get("br") else {}, "country": {g["c"]: n} if g.get("c") else {},
            "place": {place: n} if place else {}}


GROUP_ID = {"ai": "$ai", "v": "$v", "cp": "$cp", "o": "$o", "dev": "$dev", "f": "$f", "lang": "$lang", "lt": "$lt",
            "br": "$br", "c": "$c", "rg": "$rg", "ci": "$ci"}


def _quarters(start: datetime, end: datetime) -> dict:
    """The counts of an interval of UTC times whose ends are whole quarters of an hour (a day in any time zone)."""
    return {"b": {"$gte": start, "$lt": end}}


def _count_groups(match: dict) -> list[dict]:
    """The counts matching `match`, grouped as GROUP_ID groups the events: [{"_id", "n", "ms", "max"}]."""
    return list(counts().aggregate([
        {"$match": match},
        {"$group": {"_id": GROUP_ID, "n": {"$sum": "$n"}, "ms": {"$sum": "$ms"}, "max": {"$max": "$msMax"}}}]))


def _percentile(match: dict, count: int, percent: int):
    """The time taken at a percentile among `count` events with a time (nearest rank)."""
    if not count:
        return None
    rank = max(1, math.ceil(percent / 100 * count))
    found = list(events().find({**match, "ms": {"$exists": True}}, {"ms": 1}).sort("ms", 1).skip(rank - 1).limit(1))
    return found[0]["ms"] if found else None


def count_day(day: date, run: str | None = None) -> int:
    """Counts one day's events, and the day's counts of requests not stored (section 11), into request_daily: a
    document per primary key and one for the whole installation. Replaces that day's documents (those not produced
    again are removed). The times' percentiles are the stored events'. Returns the number of keys."""
    run = run or uuid.uuid4().hex
    start, end = day_bounds(day)
    match = {"t": {"$gte": start, "$lt": end}}
    groups = [*events().aggregate([
        {"$match": match},
        {"$group": {"_id": GROUP_ID, "n": {"$sum": 1}, "ms": {"$sum": "$ms"}, "max": {"$max": "$ms"}}}]),
        *_count_groups(_quarters(start, end))]
    keys: dict[tuple, dict] = {}
    whole = _empty()
    for group in groups:
        g, n = group["_id"], group["n"]
        doc = _group_doc(g, n, group.get("ms"), group.get("max"))
        _add(whole, doc)
        if g.get("cp"):
            entry = keys.get((g.get("ai"), g.get("v")))
            if entry is None:
                entry = keys[(g.get("ai"), g.get("v"))] = {**_empty(), "cp": g["cp"]}
            _add(entry, doc)
    expires = utc_naive(datetime.combine(day + timedelta(days=1), time(0), timezone.utc)) + timedelta(days=stats_days())
    key = day.isoformat()
    target = daily()
    for (ai, value), entry in keys.items():
        target.replace_one({"_id": f"{key}|{ai}|{value}"},
                           {"day": key, "ai": ai, "v": value, **entry, "language": _top(entry["language"]),
                            "linkType": _top(entry["linkType"]), "place": _top(entry["place"]), "run": run,
                            "expiresAt": expires}, upsert=True)
    timed = events().count_documents({**match, "ms": {"$exists": True}})
    target.replace_one({"_id": f"{key}|*"},
                       {"day": key, **whole, "language": _top(whole["language"]), "linkType": _top(whole["linkType"]),
                        "place": _top(whole["place"]),
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
        oldest = [doc[field] for collection, field in ((events(), "t"), (counts(), "b"))
                  for doc in collection.find({}, {field: 1}).sort(field, 1).limit(1)]
        first = local_day(min(oldest)) if oldest else current
    first = max(first, current - timedelta(days=global_days()))
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


def fold_noise(now: datetime | None = None) -> int:
    """The worker's hourly housekeeping (ADR 0006, section 11): deletes the events the resolver now counts instead of
    storing (automated clients', and those without a key) that were recorded before that change, once their day is
    counted into the aggregates (up to requestStats.finalUntil), so their numbers stay. Also removes those a resolver
    of an earlier version writes during an update. One replica at a time; returns the number deleted."""
    if not log_days():
        return 0
    try:
        with store.lock("request-fold", hold_seconds=1800, wait_seconds=0):
            return _fold_noise()
    except store.LockTimeout:
        return 0


def _fold_noise() -> int:
    final = parse_day(store.get_setting(SETTING_FINAL))
    if not final:
        return 0
    until = day_bounds(final)[1]
    since = store.get_setting(SETTING_FOLDED)
    span = {"$lt": until}
    if isinstance(since, datetime):
        if since >= until:
            return 0
        span["$gte"] = since
    deleted = events().delete_many({"$and": [{"t": span}, NOISE]}).deleted_count
    store.set_setting(SETTING_FOLDED, until)
    if deleted:
        log.info("Request log: %d automated event(s) or event(s) without a key of counted days deleted.", deleted)
        try:
            import journal
            journal.append("requestlog-folded", "-", detail=f"events={deleted}")
        except Exception as exc:   # noqa: BLE001 — the journal never stops the housekeeping
            log.warning("Journal event not written: %s", exc)
    return deleted


# ----------------------------------------------------------------------------------------------- periods (ADR 0007)
def _add(target: dict, doc: dict) -> None:
    """Adds an aggregate document (or a group of raw events in the same shape) to a running entry."""
    target["total"] += doc.get("total", 0)
    target["automated"] += doc.get("automated", 0)
    target["ms"] += doc.get("ms") or 0
    target["msMax"] = max(target["msMax"], doc.get("msMax") or 0)
    for name in ("outcome", "device", "form", "browser", "country"):
        for value, n in (doc.get(name) or {}).items():
            _bump(target[name], value, n)
    for name in ("language", "linkType", "place"):
        found = doc.get(name) or []
        for value, n in (found.items() if isinstance(found, dict) else found):
            _bump(target[name], value, n)


def collect(scope: dict, whole: bool, first: date, last: date, keys: bool = True) -> dict:
    """The requests of the days [first, last] of the installation's time zone in a scope (ADR 0007, section 3.2):
    {"total": entry, "days": {day: entry}, "keyed": {"total": entry, "days": {day: entry}}, "keys": {(ai, value): entry
    with "cp"}, "p95": [daily p95 values]}, an entry being {"total", "automated", "outcome", "device", "form",
    "language", "linkType", "browser", "country", "place", "ms", "msMax"} with dictionaries of counts. Finished days
    come from the aggregates, today from the raw events. For the whole installation "total" and "days" come from the
    installation's documents (requests without a key included); otherwise from the documents per key of the scope.
    "keyed" holds the requests with a GS1 primary key only (ADR 0006, section 14), the same as "total" for anything
    but the whole installation. keys=False leaves "keys" empty."""
    current = today()
    total, days, per_key, p95 = _empty(), {}, {}, []
    keyed_total, keyed_days = (total, days) if not whole else (_empty(), {})
    past_last = min(last, current - timedelta(days=1))
    if first <= past_last:
        span = {"day": {"$gte": first.isoformat(), "$lte": past_last.isoformat()}}
        if whole:
            for doc in daily().find({**span, "ai": {"$exists": False}}):
                _add(total, doc)
                _add(days.setdefault(doc["day"], _empty()), doc)
                if doc.get("p95") is not None:
                    p95.append(doc["p95"])
        # documents per key: of a primary key only (a probe's "key" of before 23 October 2026 left out: section 12)
        query = {"$and": [scope, span, {"ai": {"$in": KEYS}}]} if scope else {**span, "ai": {"$in": KEYS}}
        for doc in daily().find(query):
            _add(keyed_total, doc)
            _add(keyed_days.setdefault(doc["day"], _empty()), doc)
            if keys:
                entry = per_key.setdefault((doc.get("ai"), doc.get("v")), {**_empty(), "cp": doc.get("cp")})
                _add(entry, doc)
    if first <= current <= last:
        start, end = day_bounds(current)
        match = {"t": {"$gte": start, "$lt": end}}
        query = {"$and": [scope, match]} if scope else match
        count_query = {"$and": [scope, _quarters(start, end)]} if scope else _quarters(start, end)
        groups = [*events().aggregate([
            {"$match": query},
            {"$group": {"_id": GROUP_ID, "n": {"$sum": 1}, "ms": {"$sum": "$ms"}, "max": {"$max": "$ms"}}}]),
            *_count_groups(count_query)]
        today_entry = days.setdefault(current.isoformat(), _empty())
        keyed_today = keyed_days.setdefault(current.isoformat(), _empty()) if whole else today_entry
        for group in groups:
            g, n = group["_id"], group["n"]
            doc = _group_doc(g, n, group.get("ms"), group.get("max"))
            with_key = g.get("ai") in KEY_SET
            if whole or with_key:
                _add(total, doc)
                _add(today_entry, doc)
            if whole and with_key:
                _add(keyed_total, doc)
                _add(keyed_today, doc)
            if keys and with_key and g.get("cp"):
                entry = per_key.setdefault((g.get("ai"), g.get("v")), {**_empty(), "cp": g.get("cp")})
                _add(entry, doc)
    return {"total": total, "days": days, "keyed": {"total": keyed_total, "days": keyed_days}, "keys": per_key,
            "p95": p95}


# ----------------------------------------------------------------------------------------------- tenant API calls
def _tenant_list() -> list[dict]:
    import tenants as tenants_module
    return tenants_module.load()


def record_api_call(key: dict | None, method: str, operation: str | None, status: int, ms: int) -> None:
    """One call of /portal/api/v1 (ADR 0006, decision 8): never the record, the query string or the key's secret."""
    if not log_days():
        return
    days = days_for(key.get("tenant") if key else None, _tenant_list())
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
