"""
Monitoring and alerts by e-mail (Documentation/adr/0008-monitoring-and-alerts.md): the settings; the resolver checked
through a stand-in proxy (two failed rounds before an alert, a reminder a day, a message when it answers again, the
probe of a registered code); the backup's record (unknown, late, failed, good again); the certificate (expiring,
invalid, unreachable, once an hour); the request log's space against its limit (80 %, then every 5); the age of GS1's
GCP length table (unknown without one, an alert from 90 days, reminded weekly, resolved by a newer list); spikes of 404 per scope against the usual hourly number; who receives what (server
administrators, an organisation's administrators, the category switched off, disabled accounts); the lock and the
switch; the worker's schedule; the overview's alerts per scope; the messages in both languages.

Messages are queued as "mail" jobs (an external worker would send them; none runs here), so the test reads them from
the jobs collection.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_monitor.py
"""
import os
import ssl
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT, PROXY_PORT = 3395, 3394
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_TIME_ZONE="UTC",
                  PORTAL_MAIL_HOST="relay.invalid", PORTAL_MAIL_SECURITY="none", PORTAL_MAIL_FROM="portal@example.org",
                  PORTAL_MONITOR_URL=f"http://127.0.0.1:{PROXY_PORT}/.well-known/gs1resolver",
                  PORTAL_MONITOR_TLS_HOST="", RESOLVER_ORG_NAME="Example Operator")
os.environ["PORTAL_DB_URI"] = "mongomock://"
os.environ["PORTAL_DB_NAME"] = f"devtest_monitor_{os.getpid()}"
os.environ["PORTAL_WORKER"] = "external"            # messages stay queued: nothing sends them here
for name in ("RESOLVER_LOG_DAYS", "PORTAL_MONITOR_MINUTES", "PORTAL_MONITOR_PROBE", "PORTAL_ALERT_404_MIN",
             "PORTAL_ALERT_404_FACTOR", "PORTAL_MONITOR_BACKUP_HOURS", "PORTAL_MONITOR_CERT_DAYS", "PORTAL_MONITOR_GCP_DAYS",
             "FQDN"):
    os.environ.pop(name, None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False, email="root@example.org")
import app as portal  # noqa: E402
import gcp  # noqa: E402
import mailtexts  # noqa: E402
import monitor  # noqa: E402
import notify  # noqa: E402
import requestlog  # noqa: E402
import tenants  # noqa: E402
import worker  # noqa: E402

failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


# A stand-in proxy whose answers the test chooses
proxy = Flask("proxy")
ANSWER = {"/.well-known/gs1resolver": 200, "/01/09506000134352": 307}


@proxy.route("/<path:path>")
def answer(path):
    return "", ANSWER.get("/" + path, 404), ({"Location": "https://example.org/"} if ANSWER.get("/" + path) == 307 else {})


for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (proxy, PROXY_PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
time.sleep(0.3)

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False, email="ana@acme.example")
users.create("edu", "edu-password-long", "reader", tenant=acme["id"], must_change=False, email="edu@acme.example")
users.create("oto", "oto-password-long", "editor", must_change=False, email="oto@example.org")
users.create("sam", "sam-password-long", "admin", must_change=False, email="sam@example.org")
users.create("dis", "dis-password-long", "admin", must_change=False, email="dis@example.org")
users.update("dis", disabled=True)
users.set_preferences("sam", notify={"alerts": False})
MAIL = store.col("jobs")
ALERTS = store.col("alerts")
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def sent(template=None):
    """[(user, template)] of the messages queued so far, oldest first."""
    query = {"type": "mail", **({"template": template} if template else {})}
    return [(j["user"], j["template"]) for j in MAIL.find(query).sort("created", 1)]


def clear():
    MAIL.delete_many({"type": "mail"})


def state(doc_id):
    return (ALERTS.find_one({"_id": doc_id}) or {}).get("state")


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


# ================================================================== settings
check("defaults: every 5 minutes, the description file through the proxy, 26 hours, 21 days, 90 days, 20 and 3 times",
      (monitor.minutes(), monitor.backup_hours(), monitor.cert_days(), monitor.gcp_days(), monitor.spike_min(),
       monitor.spike_factor()) == (5, 26, 21, 90, 20, 3) and monitor.DEFAULT_URL == "http://frontend-proxy-service/.well-known/gs1resolver")
os.environ["PORTAL_MONITOR_MINUTES"] = "soon"
check("a setting that is not a number: the default", monitor.minutes() == 5)
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
check("PORTAL_MONITOR_MINUTES=0: monitoring off, run() does nothing", monitor.run() == {} and ALERTS.count_documents({}) == 0)
del os.environ["PORTAL_MONITOR_MINUTES"]
os.environ["FQDN"] = "id.example.org"
del os.environ["PORTAL_MONITOR_TLS_HOST"]
check("the certificate's host: FQDN by default", monitor.tls_host() == "id.example.org")
os.environ["FQDN"] = "localhost"
check("…none for localhost (development)", monitor.tls_host() == "")
os.environ["PORTAL_MONITOR_TLS_HOST"] = "https://Resolver.Example.org/x"
check("…PORTAL_MONITOR_TLS_HOST, its host only", monitor.tls_host() == "resolver.example.org")
os.environ["PORTAL_MONITOR_TLS_HOST"] = ""
check("recipients of the installation's alerts: enabled server administrators",
      monitor.recipients() == ["root", "sam"], monitor.recipients())
check("…of an organisation's: its administrators", monitor.recipients(acme["id"]) == ["ana"], monitor.recipients(acme["id"]))

# ================================================================== the resolver through the proxy
clear()
found = monitor._run(NOW)
check("the resolver answers: ok, no message", state("resolver") == "ok" and not sent(), (state("resolver"), sent()))
check("…the backup not recorded yet: unknown; the certificate not checked: unknown",
      state("backup") == "unknown" and state("certificate") == "unknown")
ANSWER["/.well-known/gs1resolver"] = 503
monitor._run(NOW + timedelta(minutes=5))
check("one failed round: still ok, no message (a restart is not an outage)",
      state("resolver") == "ok" and ALERTS.find_one({"_id": "resolver"})["failures"] == 1 and not sent())
monitor._run(NOW + timedelta(minutes=10))
check("two failed rounds: alert to the server administrators who want alerts",
      state("resolver") == "alert" and sent() == [("root", "alert-resolver-down")], sent())
job = MAIL.find_one({"template": "alert-resolver-down"})
check("…the message names the address and the problem", "/.well-known/gs1resolver" in job["text"] and "503" in job["text"]
      and "Example Operator" in job["text"] and job["to"] == "root@example.org", job["text"][:300])
monitor._run(NOW + timedelta(minutes=15))
check("…no new message while it lasts", len(sent()) == 1, sent())
monitor._run(NOW + timedelta(hours=24, minutes=11))
check("…a reminder after 24 hours", sent() == [("root", "alert-resolver-down")] * 2, sent())
ANSWER["/.well-known/gs1resolver"] = 200
monitor._run(NOW + timedelta(hours=24, minutes=16))
check("answering again: resolved, a message", state("resolver") == "ok" and sent()[-1] == ("root", "alert-resolver-up"),
      sent())
os.environ["PORTAL_MONITOR_PROBE"] = "/01/09506000134352"
check("the probe of a registered code: a redirect counts as an answer", monitor.check_resolver()[0])
ANSWER["/01/09506000134352"] = 404
ok, detail = monitor.check_resolver()
check("…a 404 for it is a failure", not ok and detail.get("status") == 404 and detail["url"].endswith("/01/09506000134352"),
      detail)
del os.environ["PORTAL_MONITOR_PROBE"]
os.environ["PORTAL_MONITOR_URL"] = "http://127.0.0.1:9/.well-known/gs1resolver"
ok, detail = monitor.check_resolver()
check("a proxy that does not answer: a failure with the error's name", not ok and detail.get("error"), detail)
os.environ["PORTAL_MONITOR_URL"] = f"http://127.0.0.1:{PROXY_PORT}/.well-known/gs1resolver"

# ================================================================== the backup's record
clear()
T = NOW + timedelta(days=2)
store.set_setting("backup.last", {"at": T - timedelta(hours=3), "ok": True, "file": "/var/backups/r.gz", "size": "4.0M",
                                  "error": None, "lastOk": T - timedelta(hours=3)})
monitor._run(T)
check("a good backup 3 hours ago: ok", state("backup") == "ok" and not sent(), (state("backup"), sent()))
store.set_setting("backup.last", {"at": T - timedelta(hours=30), "ok": True, "lastOk": T - timedelta(hours=30)})
monitor._run(T + timedelta(minutes=5))
check("the last good backup older than 26 hours: alert (late)", state("backup") == "alert"
      and ALERTS.find_one({"_id": "backup"})["detail"]["reason"] == "late" and ("root", "alert-backup-failed") in sent(),
      sent())
store.set_setting("backup.last", {"at": T, "ok": False, "error": "the database dump failed",
                                  "lastOk": T - timedelta(hours=30)})
monitor._run(T + timedelta(minutes=10))
check("…then a failed run: still the same alert, no second message",
      state("backup") == "alert" and ALERTS.find_one({"_id": "backup"})["detail"]["reason"] == "failed"
      and sent().count(("root", "alert-backup-failed")) == 1, sent())
store.set_setting("backup.last", {"at": T + timedelta(minutes=12), "ok": True, "file": "/var/backups/r2.gz",
                                  "size": "4.1M", "lastOk": T + timedelta(minutes=12)})
monitor._run(T + timedelta(minutes=15))
check("a good backup again: resolved, a message", state("backup") == "ok" and sent()[-1] == ("root", "alert-backup-ok"),
      sent())
clear()
store.set_setting("backup.last", {"at": T + timedelta(minutes=20), "ok": False, "error": "the database dump failed"})
monitor._run(T + timedelta(minutes=25))
job = MAIL.find_one({"template": "alert-backup-failed"})
check("a failed run is an alert at once, the error in the message", state("backup") == "alert" and job
      and "the database dump failed" in job["text"], job and job["text"][:300])

# ================================================================== the certificate
clear()
os.environ["PORTAL_MONITOR_TLS_HOST"] = "id.example.org"
C = T + timedelta(days=1)
monitor.tls_expiry = lambda host, port=443: C + timedelta(days=60)
ALERTS.update_one({"_id": "certificate"}, {"$set": {"checkedAt": C - timedelta(hours=2)}})
monitor._run(C)
check("a certificate valid for 60 days: ok", state("certificate") == "ok"
      and ALERTS.find_one({"_id": "certificate"})["detail"]["days"] == 60, ALERTS.find_one({"_id": "certificate"}))
monitor.tls_expiry = lambda host, port=443: C + timedelta(days=10)
monitor._run(C + timedelta(minutes=5))
check("…checked once an hour (no new check after 5 minutes)", state("certificate") == "ok")
monitor._run(C + timedelta(hours=1, minutes=1))
check("expiring within 21 days: alert", state("certificate") == "alert"
      and ("root", "alert-certificate") in sent(), sent())
job = MAIL.find_one({"template": "alert-certificate"})
check("…the message names the host and the days left", "id.example.org" in job["subject"]
      and ("10 days" in job["text"] or "9 days" in job["text"]), job["text"][:300])


def invalid(host, port=443):
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_message = "certificate has expired"
    raise error


monitor.tls_expiry = invalid
monitor._run(C + timedelta(hours=2, minutes=2))
check("a certificate that does not verify: alert (invalid)", state("certificate") == "alert"
      and ALERTS.find_one({"_id": "certificate"})["detail"]["reason"] == "invalid", ALERTS.find_one({"_id": "certificate"}))


def unreachable(host, port=443):
    raise OSError("no route to host")


monitor.tls_expiry = unreachable
before = len(sent())
monitor._run(C + timedelta(hours=3, minutes=3))
check("the host cannot be reached: unknown, and no 'resolved' message", state("certificate") == "unknown"
      and len(sent()) == before, sent())
monitor.tls_expiry = lambda host, port=443: C + timedelta(days=80)
monitor._run(C + timedelta(hours=4, minutes=4))
check("valid again: ok", state("certificate") == "ok")

# ================================================================== spikes of 404
clear()
EVENTS = requestlog.events()
S = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def unknown(value, n, minutes_ago=10):
    EVENTS.insert_many([{"t": S - timedelta(minutes=minutes_ago), "ai": "01", "v": value, "cp": value[1:], "o": "unknown",
                         "s": 404, "dev": "mobile", "expiresAt": S + timedelta(days=90)} for _ in range(n)])


unknown("07891234500014", 15)
unknown("07891234500021", 10)
unknown("09506000999982", 5, minutes_ago=90)            # more than an hour ago: not counted
found = monitor.spikes(S, tenants.load())
check("404 in the last hour per scope: the installation and the organisation",
      found["*"]["count"] == 25 and found[acme["id"]]["count"] == 25 and found["*"]["usual"] == 0, found)
check("…the most requested codes first", found[acme["id"]]["codes"][0] == ["/01/07891234500014", 15], found[acme["id"]]["codes"])
check("…25 with nothing usual: a spike (at least 20)", found["*"]["spike"] and found[acme["id"]]["spike"])
monitor._run(S)
check("a spike: a message to the server administrators and to the organisation's administrators",
      sorted(sent("alert-404-spike")) == [("ana", "alert-404-spike"), ("root", "alert-404-spike")], sent())
job = MAIL.find_one({"template": "alert-404-spike", "user": "ana"})
check("…with the codes and the numbers", "/01/07891234500014  (15)" in job["text"] and "25" in job["text"], job["text"][:400])
check("…not to readers, nor to administrators who switched alerts off", ("edu", "alert-404-spike") not in sent()
      and ("sam", "alert-404-spike") not in sent())
for day in range(1, 8):
    key = (requestlog.today() - timedelta(days=day)).isoformat()
    requestlog.daily().insert_one({"_id": f"{key}|*", "day": key, "total": 400, "outcome": {"unknown": 240}})
    requestlog.daily().insert_one({"_id": f"{key}|01|07891234500014", "day": key, "ai": "01", "v": "07891234500014",
                                   "cp": "7891234500014", "total": 400, "outcome": {"unknown": 240}})
found = monitor.spikes(S, tenants.load())
check("a usual hour of 10: 25 is not 3 times as many, no spike", found["*"]["usual"] == 10 and not found["*"]["spike"]
      and found[acme["id"]]["usual"] == 10 and not found[acme["id"]]["spike"], found)
before = len(sent())
monitor._run(S + timedelta(minutes=5))
check("the spike ends: ok, no message", state("404:*") == "ok" and state(f"404:{acme['id']}") == "ok"
      and len(sent()) == before, sent())
os.environ["PORTAL_ALERT_404_FACTOR"] = "2"
check("PORTAL_ALERT_404_FACTOR=2: 25 is more than twice 10", monitor.spikes(S, tenants.load())["*"]["spike"])
os.environ["PORTAL_ALERT_404_MIN"] = "30"
check("PORTAL_ALERT_404_MIN=30: 25 is too few", not monitor.spikes(S, tenants.load())["*"]["spike"])
del os.environ["PORTAL_ALERT_404_FACTOR"], os.environ["PORTAL_ALERT_404_MIN"]

# ================================================================== the request log's space (ADR 0006, section 9)
clear()
monitor._run(S)
check("the log's space without a limit: not checked, no message", state("logspace") == "unknown"
      and ALERTS.find_one({"_id": "logspace"})["detail"] == {"reason": "noLimit"} and not sent("alert-log-space"),
      ALERTS.find_one({"_id": "logspace"}))
store.set_setting(requestlog.SETTING_MAX, 1000 * requestlog.MEGABYTE)
monitor._run(S)
check("…a limit, but the database does not give the sizes (mongomock): not checked",
      state("logspace") == "unknown" and ALERTS.find_one({"_id": "logspace"})["detail"]["reason"] == "notMeasured")
STATS = {}
ROUND = [0]
saved_stats = requestlog._collstats
requestlog._collstats = lambda: dict(STATS)


def at_share(percent):
    """The log's statistics for that share of its 1000 MB, then one round of the checks."""
    STATS.update(storageSize=int(percent * 10 * requestlog.MEGABYTE), freeStorageSize=0, totalIndexSize=0, count=1000)
    ROUND[0] += 1
    return monitor._run(S + timedelta(seconds=ROUND[0]))["logspace"]


steps = [(50, None), (79, None), (81, "alert"), (83, None), (86, "step"), (99, "step"), (101, "step"), (120, None), (96, None)]
got = [(p, at_share(p)) for p, _ in steps]
check("the space: an alert at 80 %, a message at each step of 5 (85, 95, 100), none within a step or after the trim",
      got == steps, got)
check("…to the server administrators who want alerts", sent("alert-log-space") == [("root", "alert-log-space")] * 4,
      sent("alert-log-space"))
job = MAIL.find_one({"template": "alert-log-space"}, sort=[("created", 1)])
check("…the message names the share, the space used and the limit", job and "81 %" in job["subject"]
      and "810 MB" in job["text"] and "1,000 MB" in job["text"], job and (job["subject"], job["text"][:300]))
doc = ALERTS.find_one({"_id": "logspace"})
check("…the check keeps the step reached and the detail", doc["state"] == "alert" and doc["notifiedLevel"] == 100
      and doc["detail"]["level"] == 95 and doc["detail"]["percent"] == 96.0, doc)
check("…free space inside the file does not count", requestlog.used_bytes({"storageSize": 900, "freeStorageSize": 300,
                                                                            "totalIndexSize": 50}) == 650)
check("below 80 %: resolved, a message", at_share(70) == "resolved" and state("logspace") == "ok"
      and sent()[-1] == ("root", "alert-log-space-ok"), sent()[-2:])
hist = list(store.col(monitor.HISTORY).find({"check": "logspace"}))
check("…one alert in the history, raised and ended", len(hist) == 1 and hist[0]["endedAt"] and hist[0]["kind"] == "logspace",
      hist)
check("…a new rise starts from 80 % again, a second alert in the history", at_share(84) == "alert"
      and store.col(monitor.HISTORY).count_documents({"check": "logspace"}) == 2)
at_share(10)
requestlog._collstats = saved_stats
store.col("settings").delete_one({"_id": requestlog.SETTING_MAX})
clear()

# ================================================================== the age of GS1's GCP length table (ADR 0008, 0015)
def gcp_list(days_old, now=S):
    """Stores a small list GS1 dated that many days before now (forced: it may be older than the one in use)."""
    date = (now - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    gcp.save(gcp.parse(f'<GCPPrefixFormatList date="{date}"><entry prefix="789" gcpLength="7"/>'
                       f'</GCPPrefixFormatList>'.encode()), "root", force=True)


def gcp_round(days_after=0):
    return monitor._run(S + timedelta(days=days_after, seconds=1))["gcptable"]


clear()
store.col("gcp_table").delete_many({})
gcp_round()
check("the GCP table: without a list, not checked and no message (the table is optional)",
      state("gcptable") == "unknown" and ALERTS.find_one({"_id": "gcptable"})["detail"] == {"reason": "none"}
      and not sent("alert-gcp-table"), ALERTS.find_one({"_id": "gcptable"}))
gcp_list(30)
check("…a list GS1 dated 30 days ago: ok, with its date and age", gcp_round() is None and state("gcptable") == "ok"
      and ALERTS.find_one({"_id": "gcptable"})["detail"]["days"] == 30
      and ALERTS.find_one({"_id": "gcptable"})["detail"]["max"] == 90, ALERTS.find_one({"_id": "gcptable"}))
gcp_list(89)
check("…89 days: still ok", gcp_round() is None and state("gcptable") == "ok")
gcp_list(90)
check("…90 days: an alert, a message to the server administrators who want alerts",
      gcp_round() == "alert" and state("gcptable") == "alert" and sent("alert-gcp-table") == [("root", "alert-gcp-table")],
      sent())
job = MAIL.find_one({"template": "alert-gcp-table"})
check("…the message gives the list's date, its age and the limit",
      job and "90 days old" in job["subject"] and (S - timedelta(days=90)).strftime("%Y-%m-%d") in job["text"]
      and "from 90 days" in job["text"], job and (job["subject"], job["text"][:400]))
check("…no reminder the next day", gcp_round(1) is None and len(sent("alert-gcp-table")) == 1)
check("…a reminder a week later", gcp_round(7) == "reminder" and len(sent("alert-gcp-table")) == 2, sent())
os.environ["PORTAL_MONITOR_GCP_DAYS"] = "120"
check("PORTAL_MONITOR_GCP_DAYS=120: the same list is ok again, resolved with a message",
      gcp_round(8) == "resolved" and sent()[-1] == ("root", "alert-gcp-table-ok"), sent()[-2:])
os.environ["PORTAL_MONITOR_GCP_DAYS"] = "0"
gcp_round(8)
check("PORTAL_MONITOR_GCP_DAYS=0: not checked", state("gcptable") == "unknown"
      and ALERTS.find_one({"_id": "gcptable"})["detail"] == {"reason": "notChecked"})
del os.environ["PORTAL_MONITOR_GCP_DAYS"]
gcp_list(100)
gcp_round(9)
gcp_list(5, S + timedelta(days=9))
check("a newer list uploaded: resolved, a message naming it", gcp_round(9) == "resolved"
      and sent()[-1] == ("root", "alert-gcp-table-ok"), sent()[-2:])
hist = list(store.col(monitor.HISTORY).find({"check": "gcptable"}))
check("…each alert in the history, raised and ended", len(hist) == 2 and all(h["endedAt"] for h in hist)
      and hist[0]["kind"] == "gcptable", hist)
gcp_list(100, NOW)
root = client("root", "root-password-long")
answer = root.get("/portal/api/gcp").get_json()
check("GET /gcp: the list and its age against the limit", answer["table"]["count"] == 1
      and answer["age"] == {"date": answer["table"]["date"], "days": 100, "maxDays": 90, "old": True}, answer)
gcp_list(10, NOW)
check("…a recent list is not old", root.get("/portal/api/gcp").get_json()["age"]["old"] is False)
store.col("gcp_table").delete_many({})
check("…no list: no age", root.get("/portal/api/gcp").get_json() == {"table": None, "age": None})
gcp.forget()
monitor._run(S + timedelta(days=10))
clear()

# ================================================================== the overview shows the alerts
ANSWER["/.well-known/gs1resolver"] = 503
monitor._run(S + timedelta(minutes=10)); monitor._run(S + timedelta(minutes=15))
EVENTS.delete_many({}); requestlog.daily().delete_many({})
unknown("07891234500014", 30)
monitor._run(S + timedelta(minutes=20))
root = client("root", "root-password-long")
op = root.get("/portal/api/overview").get_json()["operation"]
check("overview of a server administrator: every active alert and the state of each check",
      sorted(a["kind"] for a in op["alerts"]) == ["404", "404", "backup", "resolver"]
      and set(op["checks"]) == {"resolver", "backup", "certificate", "logspace", "gcptable"},
      op.get("alerts"))
# Operation is the server administrators' only (ADR 0013); everyone else's alerts come with record quality
ana = client("ana", "ana-password-long")
data = ana.get("/portal/api/overview").get_json()
check("…an organisation's administrator: its own spike only, no checks (no Operation)",
      [a["id"] for a in data["records"]["alerts"]] == [f"404:{acme['id']}"] and data["operation"] is None, data["records"])
oto = client("oto", "oto-password-long")
data = oto.get("/portal/api/overview").get_json()
check("…an operator user: no installation alerts", data["records"]["alerts"] == [] and data["operation"] is None,
      data["records"])
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 1"}, headers=ORIGIN)
data = root.get("/portal/api/overview").get_json()
check("…support access: the organisation's alerts", [a["id"] for a in data["records"]["alerts"]] == [f"404:{acme['id']}"]
      and data["operation"] is None, data["records"]["alerts"])
root.delete("/portal/api/support", headers=ORIGIN)
ANSWER["/.well-known/gs1resolver"] = 200

# ================================================================== lock, schedule, preferences, messages
with store.lock("monitor", hold_seconds=60, wait_seconds=0):
    marker = ALERTS.find_one({"_id": "resolver"})["checkedAt"]
    check("another replica holds the lock: run() skips the round", monitor.run() == {}
          and ALERTS.find_one({"_id": "resolver"})["checkedAt"] == marker)
calls = []
w = worker.Worker({}, "embedded", housekeeping=[lambda: calls.append("house")], monitoring=[lambda: calls.append("mon")],
                  monitor_seconds=300)
w.housekeep()
w.housekeep()
check("the worker: monitoring and housekeeping at start, not again at once", calls == ["mon", "house"], calls)
w._monitored -= 301
w.housekeep()
check("…monitoring again after its interval, housekeeping not before its hour", calls == ["mon", "house", "mon"], calls)
w0 = worker.Worker({}, "embedded", monitoring=[lambda: calls.append("never")], monitor_seconds=0)
w0.housekeep()
check("…no monitoring with an interval of 0", "never" not in calls)
check("the worker service and the embedded worker get the monitoring", portal.MONITORING == [monitor.run]
      and portal.MONITOR_SECONDS == 300)
check("the category alerts: optional and on by default", notify.CATEGORIES["alerts"] == (True, True)
      and all(notify.TEMPLATES[t] == "alerts" for t in mailtexts.TEXTS if t.startswith("alert-")))
prefs = client("sam", "sam-password-long").get("/portal/api/preferences").get_json()
check("…a user's choice is kept", prefs["notify"] == {"jobs": False, "alerts": False}, prefs)
users.set_preferences("ana", language="pt-BR")
clear()
ALERTS.update_one({"_id": f"404:{acme['id']}"}, {"$set": {"notifiedAt": S - timedelta(hours=25)}})
monitor._run(S + timedelta(minutes=30))
job = MAIL.find_one({"template": "alert-404-spike", "user": "ana"})
check("…messages in the recipient's language", job and "códigos sem cadastro" in job["subject"], job and job["subject"])
templates = [t for t in mailtexts.TEXTS if t.startswith("alert-")]
check("eleven alert messages", len(templates) == 11, templates)
for template in templates:
    en, pt = mailtexts.TEXTS[template]["en-GB"], mailtexts.TEXTS[template]["pt-BR"]
    same = mailtexts.placeholders(en[0] + en[1]) == mailtexts.placeholders(pt[0] + pt[1])
    check(f"{template}: both languages with the same placeholders", same)
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
keys = ["prefs.alerts", "overview.op.alerts", "overview.op.noAlerts", "overview.alertSince", "overview.check.resolver",
        "overview.check.backup", "overview.check.certificate", "overview.check.backupAt", "overview.check.certExpires",
        "overview.state.ok", "overview.state.alert", "overview.state.unknown"] + \
       [f"overview.alert.{k}" for k in ("resolver", "backup", "certificate", "404", "logspace", "gcptable")] + \
       ["overview.check.logspace", "overview.check.spaceUse", "overview.check.noLimit", "alerts.kind.logspace",
        "overview.check.gcptable", "overview.check.gcpAge", "overview.check.gcpNone", "alerts.kind.gcptable", "gcp.old"]
missing = [k for k in keys if i18n.count(f'"{k}"') != 2]
check("the screen's texts in both languages", not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
