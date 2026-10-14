"""
The log of resolver requests as the portal reads it (Documentation/adr/0006-resolver-request-log.md), through the
portal's Flask test client: who sees which events (organisations, the operator, a user's own prefixes, server
administrators, support access), the filters, pages and the CSV export, the daily aggregates the worker makes (time
zone, finished days, replacement, the lock, retention), the requests per day, and the log of the tenant API's calls.
Events are written straight into resolver_log.requests, as the resolver would.

Runs against mongomock unless PORTAL_DB_URI names a real MongoDB (the portal's user may only read resolver_log there,
so this program is not run on a real database).

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_requestlog.py
"""
import csv
import io
import json
import os
import re
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3397
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_TIME_ZONE="America/Sao_Paulo")
os.environ["PORTAL_DB_URI"] = "mongomock://"
os.environ["PORTAL_DB_NAME"] = f"devtest_requestlog_{os.getpid()}"
os.environ["PORTAL_WORKER"] = "embedded"
for name in ("RESOLVER_LOG_DAYS", "PORTAL_STATS_DAYS", "PORTAL_MAIL_HOST"):
    os.environ.pop(name, None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import journal  # noqa: E402
import requestlog  # noqa: E402
import tenants  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


EVENTS = requestlog.events()
UTC = timezone.utc
NOW = datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def event(cp=None, ai="01", v=None, t=None, o="redirect", dev="mobile", **extra):
    doc = {"t": t or NOW - timedelta(minutes=5), "m": "GET", "f": "uri", "s": 307, "o": o, "dev": dev, "ms": 10}
    if cp:
        doc.update(ai=ai, v=v or ("0" + cp), cp=cp)
    doc["expiresAt"] = doc["t"] + timedelta(days=90)
    doc.update(extra)
    return EVENTS.insert_one(doc).inserted_id


acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("leo", "leo-password-long", "reader", tenant=acme["id"], prefixes=["78912345"], must_change=False)
users.create("oto", "oto-password-long", "editor", must_change=False)
users.create("opa", "opa-password-long", "admin", prefixes=["9506"], must_change=False)   # an operator admin, limited
root = client("root", "root-password-long")
ana, leo, oto = client("ana", "ana-password-long"), client("leo", "leo-password-long"), client("oto", "oto-password-long")

ACME_IN = "7891234500017"          # inside leo's 78912345
ACME_OUT = "7891234100015"         # Acme, outside 78912345
OPER = "9506000134352"             # the operator's
OTHER = "7790001000014"            # the operator's too (no organisation holds 779)
ids = {
    "acme_in": event(ACME_IN, lang="pt-br", lt="pip"),
    "acme_out": event(ACME_OUT, o="unknown", s=404),
    "oper": event(OPER, o="noLink", s=404),
    "other": event(OTHER, dev="desktop"),
    "probe": event(None, o="invalid", s=400, p="=HYPERLINK(\"http://x\")"),
    "bot": event(OPER, dev="automated"),
}


def seen(c, query=""):
    r = c.get("/portal/api/requests" + query)
    return r, {e["id"] for e in (r.get_json() or {}).get("events", [])}


def ids_of(*names):
    return {str(ids[n]) for n in names}


# ================================================================== who sees what
r, got = seen(root)
check("a server administrator sees the whole installation (automated requests hidden by default)",
      got == ids_of("acme_in", "acme_out", "oper", "other", "probe"), got)
rows = {e["id"]: e for e in r.get_json()["events"]}
check("…with the organisation of each event", rows[str(ids["acme_in"])]["organisation"] == "Acme Foods"
      and rows[str(ids["oper"])]["organisation"] is None and r.get_json()["whole"] is True, rows[str(ids["acme_in"])])
_, got = seen(root, "?automated=1")
check("automated=1 shows automated requests too", str(ids["bot"]) in got, got)
r, got = seen(ana)
check("an organisation's administrator sees its events only", got == ids_of("acme_in", "acme_out"), got)
check("…without an organisation column", "organisation" not in r.get_json()["events"][0] and r.get_json()["whole"] is False,
      r.get_json()["events"][0])
_, got = seen(leo)
check("a user limited to a prefix sees that prefix's events only", got == ids_of("acme_in"), got)
_, got = seen(oto)
check("an operator user sees the operator's events (no organisation's, none without a key)", got == ids_of("oper", "other"), got)
opa = client("opa", "opa-password-long")
_, got = seen(opa)
check("a server administrator limited to a prefix sees the operator's events of that prefix only", got == ids_of("oper"), got)
check("support access: a server administrator sees the organisation's events only",
      root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN).status_code == 200
      and seen(root)[1] == ids_of("acme_in", "acme_out"), seen(root)[1])
root.delete("/portal/api/support", headers=ORIGIN)
row = rows[str(ids["acme_in"])]
check("an event's row: anchor, outcome, device, language, link type, time", row["anchor"] == "/01/0" + ACME_IN
      and row["outcome"] == "redirect" and row["device"] == "mobile" and row["language"] == "pt-br"
      and row["linkType"] == "pip" and row["ms"] == 10 and row["at"].endswith("Z"), row)

# a prefix moved to another organisation takes its history along
users.remove("opa")                                  # limited to 9506: a prefix cannot be given while he holds it
beta = tenants.create("Beta Ltd", ["9506"], "root")
_, got = seen(oto)
check("a prefix given to an organisation: its events leave the operator's view", got == ids_of("other"), got)
users.create("bea", "bea-password-long", "reader", tenant=beta["id"], must_change=False)
_, got = seen(client("bea", "bea-password-long"))
check("…and appear in the organisation's", got == ids_of("oper"), got)
users.remove("bea")
tenants.remove(beta["id"])
_, got = seen(oto)
check("…and come back when the organisation is removed", got == ids_of("oper", "other"), got)

# ================================================================== filters and pages
_, got = seen(root, "?outcome=notFound")
check("outcome=notFound: unknown codes and missing link types", got == ids_of("acme_out", "oper"), got)
_, got = seen(root, "?outcome=unknown")
check("outcome=unknown", got == ids_of("acme_out"), got)
_, got = seen(root, "?device=desktop")
check("device=desktop", got == ids_of("other"), got)
_, got = seen(root, "?device=automated")
check("device=automated shows them without automated=1", got == ids_of("bot"), got)
_, got = seen(root, "?code=" + ACME_IN)
check("code: a GTIN-13 (the company part)", got == ids_of("acme_in"), got)
_, got = seen(root, "?code=0" + ACME_IN)
check("code: the GTIN-14", got == ids_of("acme_in"), got)
_, got = seen(root, "?code=7891234")
check("code: a GS1 Company Prefix", got == ids_of("acme_in", "acme_out"), got)
_, got = seen(root, "?code=/01/0" + OPER)
check("code: an anchor", got == ids_of("oper"), got)
_, got = seen(root, "?code=.%2A")
check("code: regular-expression characters are taken literally", got == set(), got)
for query, expected in [("?outcome=everything", "requests.badFilter"), ("?device=fridge", "requests.badFilter"),
                        ("?from=yesterday", "requests.badDate"), ("?limit=x", "requests.badFilter"),
                        ("?before=nonsense", "requests.badFilter")]:
    r = root.get("/portal/api/requests" + query)
    check(f"refused: {query} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, r.get_json()))

# periods in the installation's time zone (America/Sao_Paulo, UTC-3)
day = date(2026, 3, 10)
early = event(OTHER, t=datetime(2026, 3, 11, 2, 30))         # 23:30 on the 10th in São Paulo
late = event(OTHER, t=datetime(2026, 3, 11, 3, 30))          # 00:30 on the 11th
_, got = seen(root, "?from=2026-03-10&to=2026-03-10")
check("from/to are days of PORTAL_TIME_ZONE: 02:30 UTC on the 11th belongs to the 10th", got == {str(early)}, got)
_, got = seen(root, "?from=2026-03-11&to=2026-03-11")
check("…and 03:30 UTC to the 11th", got == {str(late)}, got)

bulk = [event(OTHER, t=datetime(2026, 2, 1, 12, 0, 0) + timedelta(seconds=i // 2)) for i in range(7)]  # same seconds
pages, cursor, guard = [], "", 0
while guard < 10:
    r = root.get("/portal/api/requests?from=2026-02-01&to=2026-02-01&limit=3" + (f"&before={cursor}" if cursor else ""))
    data = r.get_json()
    pages.append([e["id"] for e in data["events"]])
    cursor = data["next"]
    guard += 1
    if not cursor:
        break
flat = [i for p in pages for i in p]
check("pages of 3: every event once, newest first, ties on the second kept apart",
      [len(p) for p in pages] == [3, 3, 1] and sorted(flat) == sorted(str(i) for i in bulk) and len(set(flat)) == 7
      and flat == [str(i) for i in sorted(bulk, key=lambda x: (EVENTS.find_one({"_id": x})["t"], x), reverse=True)], pages)

# ================================================================== CSV export
r = root.get("/portal/api/requests.csv")
text = r.get_data().decode("utf-8")
check("CSV: UTF-8 with BOM, ';', a header", r.status_code == 200 and text.startswith("﻿at;method;form")
      and r.mimetype == "text/csv", text[:80])
table = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
probe_row = next((row for row in table if row and "HYPERLINK" in ";".join(row)), [])
check("CSV: a probe's path cannot become a formula in Excel", any(c.startswith("'=HYPERLINK") for c in probe_row), probe_row)
check("CSV: a server administrator's export names the organisation", table[0][-1] == "organisation"
      and any(row[-1] == "Acme Foods" for row in table[1:]), table[0])
check("CSV: the export is a journal event", any(e["action"] == "requests-export" and e["user"] == "root"
                                               for e in journal.search(limit=20)), journal.search(limit=3))
r = ana.get("/portal/api/requests.csv")
table = list(csv.reader(io.StringIO(r.get_data().decode("utf-8").lstrip("﻿")), delimiter=";"))
check("CSV of an organisation: its events only, no organisation column", len(table) == 3 and table[0][-1] == "path", table)

# ================================================================== aggregates
for collection in (EVENTS, requestlog.daily()):
    collection.delete_many({})
store.col("settings").delete_one({"_id": requestlog.SETTING_FINAL})
D1 = date(2026, 10, 1)
def at(day, hour, minute=0):            # a time of the installation's day, as stored (UTC)
    return datetime(day.year, day.month, day.day, hour, minute) + timedelta(hours=3)


for i in range(10):
    event(ACME_IN, t=at(D1, 9, i), ms=i + 1, lang="pt-br" if i < 7 else "en", lt="pip" if i == 0 else None)
event(ACME_IN, t=at(D1, 23, 50), o="unknown", s=404, dev="automated", ms=100)
event(OTHER, t=at(D1, 12), ms=50, f="compressed")
event(None, t=at(D1, 13), o="invalid", s=400, ms=1)
event(OTHER, t=at(D1 + timedelta(days=1), 0, 10), ms=5)          # the next day
counted = requestlog.aggregate(now=datetime.combine(D1 + timedelta(days=2), datetime.min.time(), UTC) + timedelta(hours=6))
check("the first run counts from the oldest event's day to today", counted == 3, counted)
doc = requestlog.daily().find_one({"_id": f"{D1.isoformat()}|01|0{ACME_IN}"}) or {}
check("a key's day: totals, automated, outcomes, devices, forms",
      doc.get("total") == 11 and doc.get("automated") == 1 and doc.get("outcome") == {"redirect": 10, "unknown": 1}
      and doc.get("device") == {"mobile": 10, "automated": 1} and doc.get("form") == {"uri": 11}
      and doc.get("cp") == ACME_IN, doc)
check("…languages and link types as lists, most frequent first", doc.get("language") == [["pt-br", 7], ["en", 3]]
      and doc.get("linkType") == [["pip", 1]], doc.get("language"))
check("…the time taken: sum and maximum", doc.get("ms") == 55 + 100 and doc.get("msMax") == 100, doc)
check("…the 23:50 event (02:50 UTC the next day) counted on its own day", doc.get("total") == 11, doc.get("total"))
whole = requestlog.daily().find_one({"_id": f"{D1.isoformat()}|*"}) or {}
check("the installation's day: every event, also those without a key, and the number of keys",
      whole.get("total") == 13 and whole.get("keys") == 2 and whole.get("outcome", {}).get("invalid") == 1
      and whole.get("form") == {"uri": 12, "compressed": 1} and "ai" not in whole, whole)
check("…percentiles of the time taken (nearest rank)", (whole.get("p50"), whole.get("p95"), whole.get("p99")) == (6, 100, 100),
      (whole.get("p50"), whole.get("p95"), whole.get("p99")))
check("…expiry: the day's end plus PORTAL_STATS_DAYS (800)",
      whole.get("expiresAt") == datetime(2026, 10, 2) + timedelta(days=800), whole.get("expiresAt"))
check("no document for an event without a key", requestlog.daily().count_documents({"day": D1.isoformat()}) == 3,
      list(requestlog.daily().find({"day": D1.isoformat()}, {"_id": 1})))
final = store.get_setting(requestlog.SETTING_FINAL)
check("finished days are recorded (06:00 local: yesterday is finished)", final == (D1 + timedelta(days=1)).isoformat(), final)

EVENTS.delete_many({"cp": OTHER, "t": {"$lt": at(D1 + timedelta(days=1), 0)}})
event(ACME_OUT, t=at(D1 + timedelta(days=2), 8))
counted = requestlog.aggregate(now=datetime.combine(D1 + timedelta(days=2), datetime.min.time(), UTC) + timedelta(hours=7))
check("a later run counts only the days not finished (today)", counted == 1, counted)
check("…a finished day is not counted again", requestlog.daily().find_one({"_id": f"{D1.isoformat()}|*"})["total"] == 13)
requestlog.count_day(D1)
check("counting a day again replaces it: keys no longer seen are removed",
      requestlog.daily().find_one({"_id": f"{D1.isoformat()}|01|0{OTHER}"}) is None
      and requestlog.daily().find_one({"_id": f"{D1.isoformat()}|*"})["total"] == 12, list(requestlog.daily().find({"day": D1.isoformat()}, {"_id": 1})))
store.set_setting(requestlog.SETTING_FINAL, None)
store.col("settings").delete_one({"_id": requestlog.SETTING_FINAL})
counted = requestlog.aggregate(now=datetime.combine(D1 + timedelta(days=3), datetime.min.time(), UTC) + timedelta(hours=3, minutes=5))
check("just after midnight, yesterday is not yet finished", store.get_setting(requestlog.SETTING_FINAL)
      == (D1 + timedelta(days=1)).isoformat(), store.get_setting(requestlog.SETTING_FINAL))
with store.lock("request-stats"):
    check("another replica holding the lock: the run is skipped", requestlog.aggregate() == 0)
os.environ["RESOLVER_LOG_DAYS"] = "0"
check("RESOLVER_LOG_DAYS=0: nothing is counted", requestlog.aggregate() == 0)
del os.environ["RESOLVER_LOG_DAYS"]
check("the worker's housekeeping runs the aggregates", requestlog.aggregate in portal.HOUSEKEEPING)
os.environ["PORTAL_TIME_ZONE"] = "Mars/Olympus"
check("an unknown time zone: UTC", str(requestlog.zone()) == "UTC")
os.environ["PORTAL_TIME_ZONE"] = "America/Sao_Paulo"

# ================================================================== requests per day
EVENTS.delete_many({})
requestlog.daily().delete_many({})
store.col("settings").delete_one({"_id": requestlog.SETTING_FINAL})
today = requestlog.today()
yesterday = today - timedelta(days=1)
start, _ = requestlog.day_bounds(yesterday)
for minutes, cp in [(60, ACME_IN), (61, ACME_IN), (62, OTHER)]:
    event(cp, t=start + timedelta(minutes=minutes))
event(ACME_IN, t=NOW - timedelta(seconds=30), o="unknown", s=404)
event(OTHER, t=NOW - timedelta(seconds=20), dev="automated")
requestlog.count_day(yesterday)
r = root.get("/portal/api/requests/daily?days=7")
days = (r.get_json() or {}).get("days", [])
check("per day: the last 7 days, oldest first, today included", [d["day"] for d in days]
      == [(today - timedelta(days=6 - i)).isoformat() for i in range(7)] and r.get_json()["timeZone"] == "America/Sao_Paulo",
      [d["day"] for d in days])
check("…yesterday from the aggregates, today from the raw events", days[-2]["total"] == 3 and days[-1]["total"] == 2
      and days[-1]["automated"] == 1 and days[-1]["outcome"].get("unknown") == 1, days[-2:])
days = ana.get("/portal/api/requests/daily?days=2").get_json()["days"]
check("…an organisation's days count its keys only", [d["total"] for d in days] == [2, 1], days)
days = oto.get("/portal/api/requests/daily?days=2").get_json()["days"]
check("…the operator's too", [d["total"] for d in days] == [1, 1], days)
check("days=x refused", code(root.get("/portal/api/requests/daily?days=x")) == "requests.badFilter")

# ================================================================== the tenant API's calls
r = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:read"], "days": 30}, headers=ORIGIN)
key = (r.get_json() or {}).get("key", "")
key_id = key[3:15]
auth = {"Authorization": f"Bearer {key}"}
api_client = portal.app.test_client()
api_client.get("/portal/api/v1/", headers=auth)
api_client.get(f"/portal/api/v1/records/01/0{ACME_IN}?qualifiers=/10/SECRETBATCH", headers=auth)
api_client.get("/portal/api/v1/records")                                     # no key
calls = list(store.col("api_requests").find({}, {"_id": 0}).sort("t", 1))
check("each call is recorded", len(calls) == 3, calls)
check("…with the key and its organisation", calls[0].get("key") == key_id and calls[0].get("tenant") == acme["id"]
      and calls[0].get("op") == "/portal/api/v1/" and calls[0].get("s") == 200 and calls[0].get("m") == "GET", calls[0])
check("…the route's template, never the record or the query string",
      calls[1].get("op") == "/portal/api/v1/records/<key>/<path:value>" and ACME_IN not in json.dumps(calls, default=str)
      and "SECRETBATCH" not in json.dumps(calls, default=str), calls[1])
check("…a call without a key: no key, its status", "key" not in calls[2] and calls[2].get("s") == 401, calls[2])
check("…the key's secret appears nowhere", key[16:] not in json.dumps(calls, default=str))
r = ana.get("/portal/api/requests/api")
listed = (r.get_json() or {}).get("calls", [])
check("an organisation's administrator sees its calls with the key's name", [c["keyName"] for c in listed] == ["ERP", "ERP"]
      and listed[0]["operation"] == "/portal/api/v1/records/<key>/<path:value>", listed)
check("a user who is not an administrator cannot", leo.get("/portal/api/requests/api").status_code == 403)
listed = root.get("/portal/api/requests/api").get_json()["calls"]
check("a server administrator sees every call, with the organisation", len(listed) == 3
      and {c["organisation"] for c in listed} == {"Acme Foods", None}, listed)
listed = root.get(f"/portal/api/requests/api?key={key_id}&limit=1").get_json()
check("filter by key, pages", len(listed["calls"]) == 1 and listed["next"], listed)
os.environ["RESOLVER_LOG_DAYS"] = "0"
api_client.get("/portal/api/v1/", headers=auth)
check("RESOLVER_LOG_DAYS=0: calls are not recorded", store.col("api_requests").count_documents({}) == 3)
del os.environ["RESOLVER_LOG_DAYS"]

# ================================================================== configuration and failures
cfg = ana.get("/portal/api/config").get_json()
check("configuration: the log's retention and the scope", cfg.get("requestLog") == {"days": 90, "whole": False}, cfg.get("requestLog"))
check("…a server administrator's view is the whole installation", root.get("/portal/api/config").get_json()["requestLog"]["whole"])
saved = requestlog.events


class Down:
    def find(self, *a, **k):
        from pymongo.errors import OperationFailure
        raise OperationFailure("not authorized on resolver_log", 13)
    aggregate = find


requestlog.events = lambda: Down()
r = root.get("/portal/api/requests")
check("the log cannot be read: 503 requests.unavailable", r.status_code == 503 and code(r) == "requests.unavailable", r.status_code)
requestlog.events = saved

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
for message_code in ("requests.badDate", "requests.badFilter", "requests.unavailable"):
    check(f"{message_code} in both languages", i18n.count(f'"{message_code}"') == 2, i18n.count(f'"{message_code}"'))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
