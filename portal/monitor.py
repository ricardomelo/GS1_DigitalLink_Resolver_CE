"""
Monitoring and alerts by e-mail (Documentation/adr/0008-monitoring-and-alerts.md).

The job worker calls run() every PORTAL_MONITOR_MINUTES (app.MONITORING, worker.py); one replica at a time does the
checks (the "monitor" lock, not waited for). Each check keeps a document in the portal's collection "alerts":

    {_id: "resolver" | "backup" | "certificate" | "logspace" | "404:*" | "404:<tenant id>",
     state: "ok" | "alert" | "unknown", since, checkedAt, failures, detail, notifiedAt, notifiedLevel, tenant}

Each alert raised is also recorded in "alert_history" (Documentation/adr/0013-administration-and-navigation.md):

    {_id, check: "resolver" | … | "404:<scope>", kind, tenant, raisedAt, endedAt (None while it lasts), endedAs
     ("ok" | "unknown"), detail, expiresAt}

kept HISTORY_DAYS after it was raised. A change of state decides the messages (category "alerts" of notify.py): one when a check goes into alert, a
reminder every REMIND_HOURS while it lasts, one when it is resolved (not for spikes of 404, which simply end). The
request log's space (Documentation/adr/0006-resolver-request-log.md, section 9) is an alert from SPACE_ALERT % of its
limit, with a message at each step of SPACE_STEP points it reaches (80, 85, 90, 95, 100) instead of daily reminders.
Server administrators receive the installation's alerts; an organisation's administrators its spikes of 404.

Settings (section 3.4 of the ADR):
  PORTAL_MONITOR_MINUTES       how often the worker checks; 0: monitoring off                       (5)
  PORTAL_MONITOR_URL           the resolver through the proxy   (http://frontend-proxy-service/.well-known/gs1resolver)
  PORTAL_MONITOR_PROBE         a GS1 Digital Link path of a registered code, checked through the proxy too (empty)
  PORTAL_MONITOR_BACKUP_HOURS  the longest time without a good backup                               (26)
  PORTAL_MONITOR_TLS_HOST      the host whose certificate is checked (empty or localhost: not)      (FQDN)
  PORTAL_MONITOR_CERT_DAYS     an alert when the certificate expires within this many days          (21)
  PORTAL_ALERT_404_MIN         the fewest 404 "unknown" in an hour that make a spike                (20)
  PORTAL_ALERT_404_FACTOR      how many times the usual hourly number a spike is                     (3)
"""
import logging
import os
import socket
import ssl
from datetime import datetime, timedelta, timezone

import requests
from pymongo.errors import PyMongoError

import notify
import requestlog
import store
import tenants
import users

log = logging.getLogger("portal.monitor")

COLLECTION = "alerts"
BACKUP_SETTING = "backup.last"
REMIND_HOURS = 24
FAILURES_BEFORE_ALERT = 2
TIMEOUT_SECONDS = 10
CERT_EVERY = timedelta(hours=1)
SPIKE_WINDOW = timedelta(hours=1)
BASELINE_DAYS = 7
TOP_CODES = 5
DEFAULT_URL = "http://frontend-proxy-service/.well-known/gs1resolver"
SPACE_ALERT = 80
SPACE_STEP = 5
CHECKS = ("resolver", "backup", "certificate", "logspace")
HISTORY = "alert_history"
HISTORY_DAYS = 400
KINDS = CHECKS + ("404",)


# ----------------------------------------------------------------------------------------------- settings
def _number(name: str, default, kind=int):
    text = (os.environ.get(name, "") or "").strip()
    try:
        value = kind(text) if text else default
        return value if value >= 0 else default
    except ValueError:
        log.warning("%s=%r is not a number: using %s.", name, text, default)
        return default


def minutes() -> float:
    """PORTAL_MONITOR_MINUTES (0: monitoring off)."""
    return _number("PORTAL_MONITOR_MINUTES", 5, float)


def monitor_url() -> str:
    return (os.environ.get("PORTAL_MONITOR_URL", "") or "").strip() or DEFAULT_URL


def probe_path() -> str:
    path = (os.environ.get("PORTAL_MONITOR_PROBE", "") or "").strip()
    return path if path.startswith("/") else ""


def backup_hours() -> float:
    return _number("PORTAL_MONITOR_BACKUP_HOURS", 26, float) or 26


def tls_host() -> str:
    """The host whose certificate is checked: PORTAL_MONITOR_TLS_HOST, else FQDN; "" when it is local."""
    raw = os.environ.get("PORTAL_MONITOR_TLS_HOST")
    host = (raw if raw is not None else os.environ.get("FQDN", "")).strip().lower()
    host = host.split("://")[-1].split("/")[0]
    return "" if host in ("", "localhost", "127.0.0.1", "::1") else host


def cert_days() -> int:
    return _number("PORTAL_MONITOR_CERT_DAYS", 21)


def spike_min() -> int:
    return max(1, _number("PORTAL_ALERT_404_MIN", 20))


def spike_factor() -> float:
    return _number("PORTAL_ALERT_404_FACTOR", 3, float)


def _col():
    return store.col(COLLECTION)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------------------------------- the checks
def check_resolver() -> tuple[bool, dict]:
    """(answered, detail): the description file through the proxy answers 200, and the probe, when set, a 2xx or
    3xx (redirects are not followed: the target's own server is not the installation's)."""
    url = monitor_url()
    targets = [(url, lambda s: s == 200)]
    probe = probe_path()
    if probe:
        base = url.split("://", 1)[0] + "://" + url.split("://", 1)[-1].split("/", 1)[0]
        targets.append((base + probe, lambda s: 200 <= s < 400))
    for target, good in targets:
        try:
            answer = requests.get(target, timeout=TIMEOUT_SECONDS, allow_redirects=False)
        except requests.RequestException as exc:
            return False, {"url": target, "error": type(exc).__name__}
        if not good(answer.status_code):
            return False, {"url": target, "status": answer.status_code}
    return True, {"url": url, "probe": probe or None}


def check_backup(now: datetime) -> tuple[str, dict]:
    """("ok" | "alert" | "unknown", detail) from the backup script's record (setting backup.last)."""
    last = store.get_setting(BACKUP_SETTING)
    if not isinstance(last, dict) or not last.get("at"):
        return "unknown", {}
    at = last["at"] if isinstance(last["at"], datetime) else store.parse_iso(str(last["at"]))
    good = last.get("lastOk") or (last["at"] if last.get("ok") else None)
    good = good if isinstance(good, datetime) or good is None else store.parse_iso(str(good))
    detail = {"at": store.iso(at), "ok": bool(last.get("ok")), "file": last.get("file"), "size": last.get("size"),
              "error": last.get("error"), "lastOk": store.iso(good) if good else None}
    if not last.get("ok"):
        return "alert", {**detail, "reason": "failed"}
    if at is None or now - at > timedelta(hours=backup_hours()):
        return "alert", {**detail, "reason": "late", "hours": backup_hours()}
    return "ok", detail


def tls_expiry(host: str, port: int = 443) -> datetime:
    """When the certificate the host presents expires (raises ssl.SSLError or OSError when it cannot be checked;
    ssl.SSLCertVerificationError when it does not verify, an expired one included)."""
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc).replace(tzinfo=None)


def check_certificate(now: datetime) -> tuple[str, dict]:
    host = tls_host()
    if not host:
        return "unknown", {"reason": "notChecked"}
    try:
        expires = tls_expiry(host)
    except ssl.SSLCertVerificationError as exc:
        return "alert", {"host": host, "reason": "invalid", "error": (exc.verify_message or str(exc))[:200]}
    except (OSError, ssl.SSLError) as exc:
        return "unknown", {"host": host, "reason": "unreachable", "error": type(exc).__name__}
    days = (expires - now).total_seconds() / 86400
    detail = {"host": host, "expires": store.iso(expires), "days": max(0, int(days))}
    return ("alert" if days < cert_days() else "ok"), detail


def check_space() -> tuple[str, dict]:
    """The request log's space against its limit: ("alert", …) from SPACE_ALERT %, "ok" below, "unknown" without a
    limit or when the database does not give the sizes. detail: used, max (bytes), percent, level (the step reached:
    80, 85 … 100)."""
    limit = requestlog.max_bytes()
    if not limit:
        return "unknown", {"reason": "noLimit"}
    measured = requestlog.space_share()
    if measured is None:
        return "unknown", {"reason": "notMeasured", "max": limit}
    percent = measured["share"] * 100
    level = min(100, int(percent // SPACE_STEP) * SPACE_STEP)
    detail = {"used": measured["used"], "max": limit, "percent": round(percent, 1), "level": level}
    return ("alert" if percent >= SPACE_ALERT else "ok"), detail


def _megabytes(n) -> str:
    return f"{n / requestlog.MEGABYTE:,.0f} MB" if isinstance(n, (int, float)) else ""


def _update_space(now: datetime) -> str | None:
    """Stores the space check's state: a message when it goes into alert and at each higher step, one when it falls
    back below SPACE_ALERT. Returns "alert", "step", "resolved" or None."""
    state, detail = check_space()
    previous = _col().find_one({"_id": "logspace"}) or {}
    was = previous.get("state")
    doc = {"state": state, "checkedAt": now, "detail": detail}
    params = {"percent": int(detail["percent"]) if "percent" in detail else "", "used": _megabytes(detail.get("used")),
              "max": _megabytes(detail.get("max"))}
    sent = None
    if state == "alert":
        doc["since"] = previous.get("since") if was == "alert" else now
        notified = (previous.get("notifiedLevel") or 0) if was == "alert" else 0
        if detail["level"] > notified:
            _tell("alert-log-space", since=_text(doc["since"]), **params)
            sent = "step" if notified else "alert"
            notified = detail["level"]
        doc["notifiedLevel"] = notified
    else:
        doc["since"] = previous.get("since") if was == state else now
        if was == "alert" and state == "ok":
            doc["resolvedAt"] = now
            _tell("alert-log-space-ok", since=_text(previous.get("since")), **params)
            sent = "resolved"
        doc["notifiedLevel"] = None
    _col().update_one({"_id": "logspace"}, {"$set": doc}, upsert=True)
    _remember("logspace", was, state, now, detail, None)
    return sent


def spikes(now: datetime, tenant_list: list[dict]) -> dict[str, dict]:
    """The 404 "unknown" of the last hour per scope ("*" the installation, or a tenant id) with the usual hourly
    number of the BASELINE_DAYS days before: {scope: {"count", "usual", "codes": [[anchor, n]], "spike"}}."""
    start = now - SPIKE_WINDOW
    found: dict[str, dict] = {"*": {"count": 0, "codes": {}}}
    for t in tenant_list:
        found[t["id"]] = {"count": 0, "codes": {}}
    quarter = start.replace(minute=start.minute - start.minute % 15, second=0, microsecond=0)
    groups = [*requestlog.events().aggregate([
        {"$match": {"t": {"$gte": start, "$lt": now}, "o": "unknown"}},
        {"$group": {"_id": {"ai": "$ai", "v": "$v", "cp": "$cp"}, "n": {"$sum": 1}}}]),
        # and the counts of automated requests (ADR 0006, section 11), by whole quarters of an hour
        *requestlog.counts().aggregate([
            {"$match": {"b": {"$gte": quarter, "$lt": now}, "o": "unknown"}},
            {"$group": {"_id": {"ai": "$ai", "v": "$v", "cp": "$cp"}, "n": {"$sum": "$n"}}}])]
    for group in groups:
        g, n = group["_id"], group["n"]
        anchor = f"/{g['ai']}/{g['v']}" if g.get("ai") else "?"
        scopes = ["*"]
        owner = requestlog.owner_of(g.get("cp"), tenant_list)
        if owner:
            scopes.append(owner)
        for scope in scopes:
            found[scope]["count"] += n
            found[scope]["codes"][anchor] = found[scope]["codes"].get(anchor, 0) + n
    today = requestlog.today()
    first = (today - timedelta(days=BASELINE_DAYS)).isoformat()
    last = (today - timedelta(days=1)).isoformat()
    span = {"day": {"$gte": first, "$lte": last}}
    hours = BASELINE_DAYS * 24
    out = {}
    for scope, entry in found.items():
        if scope == "*":
            query = {**span, "ai": {"$exists": False}}
        else:
            tenant_scope = requestlog.scope_filter(tenant_list, scope, [], False)
            query = {"$and": [tenant_scope, span, {"ai": {"$exists": True}}]}
        past = sum((doc.get("outcome") or {}).get("unknown", 0)
                   for doc in requestlog.daily().find(query, {"outcome": 1}))
        usual = past / hours
        count = entry["count"]
        codes = sorted(entry["codes"].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_CODES]
        out[scope] = {"count": count, "usual": round(usual, 1), "codes": [list(c) for c in codes],
                      "spike": count >= spike_min() and count >= spike_factor() * usual}
    return out


# ----------------------------------------------------------------------------------------------- recipients
def recipients(tenant: str | None = None) -> list[str]:
    """Server administrators (tenant None) or the administrators of an organisation."""
    out = []
    for name, account in users.load().items():
        if account.get("role") != "admin" or account.get("disabled"):
            continue
        if tenant is None and users.is_server_admin(account):
            out.append(name)
        elif tenant is not None and account.get("tenant") == tenant:
            out.append(name)
    return sorted(out)


def _tell(template: str, tenant: str | None = None, **params) -> int:
    sent = 0
    for name in recipients(tenant):
        sent += bool(notify.send(name, template, **params))
    return sent


# ----------------------------------------------------------------------------------------------- state
def _update(doc_id: str, state: str, detail: dict, now: datetime, templates: tuple, tenant: str | None = None,
            params: dict | None = None, **extra) -> str | None:
    """Stores a check's new state and sends what the change calls for: templates = (alert, resolved or None).
    Returns the message sent ("alert", "reminder", "resolved") or None."""
    previous = _col().find_one({"_id": doc_id}) or {}
    was = previous.get("state")
    doc = {"state": state, "checkedAt": now, "detail": detail, **extra}
    if tenant:
        doc["tenant"] = tenant
    sent = None
    if state == "alert":
        doc["since"] = previous.get("since") if was == "alert" else now
        notified = previous.get("notifiedAt") if was == "alert" else None
        if notified is None or now - notified >= timedelta(hours=REMIND_HOURS):
            sent = "reminder" if notified is not None else "alert"
            _tell(templates[0], tenant, since=_text(doc["since"]), **(params or {}))
            doc["notifiedAt"] = now
        else:
            doc["notifiedAt"] = notified
    else:
        doc["since"] = previous.get("since") if was == state else now
        if was == "alert" and state == "ok":            # "unknown" (could not check) resolves nothing
            doc["resolvedAt"] = now
            if templates[1]:
                _tell(templates[1], tenant, since=_text(previous.get("since")), **(params or {}))
                sent = "resolved"
        doc["notifiedAt"] = None
    _col().update_one({"_id": doc_id}, {"$set": doc}, upsert=True)
    _remember(doc_id, was, state, now, detail, tenant)
    return sent


def _kind(doc_id: str) -> str:
    return "404" if doc_id.startswith("404:") else doc_id


def _remember(doc_id: str, was: str | None, state: str, now: datetime, detail: dict, tenant: str | None) -> None:
    """The alert history: a raised alert recorded, an ended one closed; a failure never stops the checks."""
    try:
        history = store.col(HISTORY)
        if state == "alert" and was != "alert":
            history.insert_one({"_id": f"{doc_id}@{now.strftime('%Y%m%dT%H%M%S')}", "check": doc_id,
                                "kind": _kind(doc_id), "tenant": tenant, "raisedAt": now, "endedAt": None,
                                "detail": detail, "expiresAt": now + timedelta(days=HISTORY_DAYS)})
        elif was == "alert" and state != "alert":
            history.update_many({"check": doc_id, "endedAt": None}, {"$set": {"endedAt": now, "endedAs": state}})
    except PyMongoError as exc:
        log.warning("Alert history not written (%s): %s", doc_id, exc)


def _text(moment) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC") if isinstance(moment, datetime) else ""


def run(now: datetime | None = None) -> dict:
    """One round of checks (the worker's monitoring task); one replica at a time. Returns the messages sent, per
    check ({"resolver": "alert"}), empty when nothing changed."""
    if not minutes():
        return {}
    try:
        with store.lock("monitor", hold_seconds=600, wait_seconds=0):
            return {name: sent for name, sent in _run(now or _now()).items() if sent}
    except store.LockTimeout:
        return {}


def _run(now: datetime) -> dict:
    found = {}
    # resolver: two failed rounds in a row
    answered, detail = check_resolver()
    previous = _col().find_one({"_id": "resolver"}) or {}
    failures = 0 if answered else int(previous.get("failures") or 0) + 1
    if answered:
        state = "ok"
    elif failures >= FAILURES_BEFORE_ALERT:
        state = "alert"
    else:
        state = previous.get("state") or "ok"             # a first failure: no change yet
    found["resolver"] = _update("resolver", state, detail, now, ("alert-resolver-down", "alert-resolver-up"),
                                params={"url": detail.get("url"), "problem": detail.get("error") or detail.get("status") or ""},
                                failures=failures)
    # backup
    state, detail = check_backup(now)
    found["backup"] = _update("backup", state, detail, now, ("alert-backup-failed", "alert-backup-ok"),
                              params={"at": detail.get("at") or "", "lastOk": detail.get("lastOk") or "-",
                                      "error": detail.get("error") or detail.get("reason") or ""})
    # certificate, once an hour
    cert = _col().find_one({"_id": "certificate"}) or {}
    if not cert.get("checkedAt") or now - cert["checkedAt"] >= CERT_EVERY:
        state, detail = check_certificate(now)
        found["certificate"] = _update("certificate", state, detail, now, ("alert-certificate", "alert-certificate-ok"),
                                       params={"host": detail.get("host") or "", "expires": detail.get("expires") or "",
                                               "days": detail.get("days", 0),
                                               "error": detail.get("error") or ""})
    # the request log's space against its limit
    found["logspace"] = _update_space(now)
    # spikes of 404 per scope
    tenant_list = tenants.load()
    for scope, entry in spikes(now, tenant_list).items():
        doc_id = f"404:{scope}"
        tenant = None if scope == "*" else scope
        codes = "\n".join(f"  {anchor}  ({n})" for anchor, n in entry["codes"]) or "-"
        found[doc_id] = _update(doc_id, "alert" if entry["spike"] else "ok", entry, now, ("alert-404-spike", None),
                                tenant=tenant, params={"count": entry["count"], "usual": entry["usual"],
                                                       "codes": codes})
    return found


# ----------------------------------------------------------------------------------------------- reading
def states(tenant: str | None, server_admin: bool) -> dict:
    """What the overview shows: {"checks": {name: {state, since, detail}} (server administrators),
    "active": [{id, kind, since, detail}] (the scope's alerts)}."""
    try:
        docs = list(_col().find({}))
    except PyMongoError:
        return {"checks": {}, "active": []}
    out = {"checks": {}, "active": []}
    for doc in docs:
        kind = "404" if doc["_id"].startswith("404:") else doc["_id"]
        mine = server_admin if (kind != "404" or doc["_id"] == "404:*") else (
            server_admin or doc.get("tenant") == tenant)
        if not mine:
            continue
        entry = {"id": doc["_id"], "kind": kind, "state": doc.get("state"), "since": store.iso(doc.get("since")),
                 "checkedAt": store.iso(doc.get("checkedAt")), "detail": _public(doc.get("detail") or {})}
        if kind in CHECKS:
            out["checks"][kind] = entry
        if doc.get("state") == "alert":
            out["active"].append(entry)
    out["active"].sort(key=lambda e: e["since"] or "")
    return out


def history(tenant: str | None, server_admin: bool, only_tenant: str | None = None, kind: str | None = None,
            since: datetime | None = None, until: datetime | None = None, limit: int = 500) -> list[dict]:
    """The alerts raised, newest first: a server administrator's every alert (or one organisation's: only_tenant, "-"
    for the installation's own); an organisation's administrator their organisation's spikes of 404."""
    query: dict = {}
    if not server_admin:
        query["tenant"] = tenant or "-none-"
    elif only_tenant:
        query["tenant"] = None if only_tenant == "-" else only_tenant
    if kind:
        query["kind"] = kind
    if since or until:
        query["raisedAt"] = {**({"$gte": since} if since else {}), **({"$lt": until} if until else {})}
    out = []
    for doc in store.col(HISTORY).find(query).sort("raisedAt", -1).limit(limit):
        out.append({"id": doc["_id"], "check": doc["check"], "kind": doc["kind"], "tenant": doc.get("tenant"),
                    "raisedAt": store.iso(doc.get("raisedAt")), "endedAt": store.iso(doc.get("endedAt")),
                    "endedAs": doc.get("endedAs"), "detail": _public(doc.get("detail") or {})})
    return out


def _public(detail: dict) -> dict:
    return {k: (store.iso(v) if isinstance(v, datetime) else v) for k, v in detail.items()}
