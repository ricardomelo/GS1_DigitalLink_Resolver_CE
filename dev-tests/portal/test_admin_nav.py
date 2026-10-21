"""
Administration and navigation (Documentation/adr/0013-administration-and-navigation.md, backlog item 9.2), through the
portal's Flask test client: an organisation's page (its prefixes, users, domains, brands, single sign-on, API keys and
alerts; who may open which: an organisation's administrator their own whatever they ask, a server administrator any
and the operator's, support access the organisation in support, editors not at all); the alert history (written when a
check goes into alert and closed when it leaves, the scope of each administrator, the filters by organisation, kind
and dates, refusals); the overview filtered by organisation for server administrators (the same figures that
organisation's administrators see, the operator's, an unknown one refused, the filter ignored for anyone else),
Operation for server administrators only and its lines that matter to everyone with record quality, the export
filtered too; the account's organisation with its prefixes for the prefix picker; refusals of prefixes naming the
prefix; the texts in both languages; the fourteen confirmations through the portal's own dialog.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_admin_nav.py
"""
import csv
import io
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3402
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ["PORTAL_DB_URI"] = "mongomock://"
os.environ["PORTAL_DB_NAME"] = f"devtest_adminnav_{os.getpid()}"
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "5"
os.environ.pop("PORTAL_MAIL_HOST", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import apikeys  # noqa: E402
import monitor  # noqa: E402
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


def gtin(body):
    return body + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body))) % 10) % 10)


acme = tenants.create("Acme Foods", ["7891234", "7891299"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False, email="ana@acme.example")
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], prefixes=["7891299"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
users.create("oto", "oto-password-long", "editor", must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))
store.col("domains").insert_one({"_id": "id.acme.example", "tenant": acme["id"], "mode": "direct", "stem": "",
                                 "verified": True, "defaultFor": ["7891234"]})
store.col("branding").insert_one({"_id": "7891234", "name": "Acme", "colour": "#002C6C", "accent": "#F26334"})
store.col("sso").insert_one({"_id": acme["id"], "issuer": "https://login.acme.example", "clientId": "c",
                             "clientSecret": "s", "domains": ["acme.example"], "enabled": True, "passwordOff": False})
apikeys.create("ERP", ["records:read"], 30, [], acme["id"], "ana")

# ================================================================== an organisation's page
r = ana.get("/portal/api/organisation")
page = r.get_json() or {}
check("an organisation's administrator opens their organisation's page", r.status_code == 200
      and page.get("id") == acme["id"] and page.get("name") == "Acme Foods"
      and page.get("prefixes") == ["7891234", "7891299"] and page.get("operator") is False, page)
check("…its users with their prefixes", sorted((u["username"], tuple(u["prefixes"])) for u in page.get("users", []))
      == [("ana", ()), ("edu", ("7891299",))], page.get("users"))
check("…no password hash or other secret given", "hash" not in str(page) and "clientSecret" not in str(page)
      and '"s"' not in str(page.get("sso")), page.get("sso"))
check("…its domains, brands, single sign-on and API keys", [d["domain"] for d in page["domains"]] == ["id.acme.example"]
      and [b["prefix"] for b in page["brands"]] == ["7891234"] and page["sso"][0]["issuer"] == "https://login.acme.example"
      and page["sso"][0]["secretSet"] is True and [k["name"] for k in page["apikeys"]] == ["ERP"], page)
check("…its prefixes not changed there by itself", page.get("canEditPrefixes") is False)
r = ana.get(f"/portal/api/organisation?id={beta['id']}")
check("…asking for another organisation still gives its own", r.get_json()["id"] == acme["id"])
check("an editor may not open it", edu.get("/portal/api/organisation").status_code == 403)
r = root.get(f"/portal/api/organisation?id={beta['id']}")
check("a server administrator opens any organisation, prefixes editable", r.status_code == 200
      and r.get_json()["name"] == "Beta Drinks" and r.get_json()["canEditPrefixes"] is True
      and [u["username"] for u in r.get_json()["users"]] == ["bia"], r.get_json())
r = root.get("/portal/api/organisation")
check("…and the operator's (the installation's own users and settings)", r.status_code == 200
      and r.get_json()["operator"] is True and r.get_json()["id"] == "operator"
      and sorted(u["username"] for u in r.get_json()["users"]) == ["oto", "root"]
      and r.get_json()["canEditPrefixes"] is False, r.get_json())
check("…an unknown organisation: 404", root.get("/portal/api/organisation?id=t-nobody").status_code == 404)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 9"}, headers=ORIGIN)
r = root.get(f"/portal/api/organisation?id={beta['id']}")
check("in support access: the organisation in support, read only", r.get_json()["id"] == acme["id"]
      and r.get_json()["readOnly"] is True and r.get_json()["canEditPrefixes"] is False, r.get_json())
root.delete("/portal/api/support", headers=ORIGIN)

# ================================================================== prefixes refused name the prefix
r = root.put(f"/portal/api/tenants/{beta['id']}", json={"prefixes": ["7895555", "78912345"]}, headers=ORIGIN)
check("a prefix overlapping another organisation's: refused, the prefix named (the row marked)",
      code(r) == "tenants.prefixOverlap" and r.get_json()["params"]["prefix"] == "78912345", r.get_json())
r = root.put(f"/portal/api/tenants/{beta['id']}", json={"prefixes": ["7895555", "78a"]}, headers=ORIGIN)
check("…a value that is no prefix: refused, named", code(r) == "users.prefixInvalid"
      and r.get_json()["params"]["prefix"] == "78a", r.get_json())
config = ana.get("/portal/api/config").get_json()
check("the account's organisation comes with its prefixes (the users' prefix picker)",
      config["tenant"]["prefixes"] == ["7891234", "7891299"], config.get("tenant"))

# ================================================================== the alert history
NOW = datetime(2026, 10, 17, 12, 0)
monitor._update("resolver", "alert", {"url": "http://x", "error": "refused"}, NOW, ("alert-resolver-down", None))
monitor._update(f"404:{acme['id']}", "alert", {"count": 40, "usual": 2}, NOW, ("alert-404-spike", None),
                tenant=acme["id"])
monitor._update(f"404:{beta['id']}", "alert", {"count": 25, "usual": 1}, NOW - timedelta(days=3),
                ("alert-404-spike", None), tenant=beta["id"])
history = list(store.col("alert_history").find({}))
check("a check going into alert is recorded once, with its kind, organisation and expiry",
      len(history) == 3 and {h["kind"] for h in history} == {"resolver", "404"}
      and all(h["endedAt"] is None and h["expiresAt"] > h["raisedAt"] for h in history), history)
monitor._update("resolver", "alert", {"url": "http://x"}, NOW + timedelta(minutes=5), ("alert-resolver-down", None))
check("…still in alert: not recorded again", store.col("alert_history").count_documents({"check": "resolver"}) == 1)
monitor._update("resolver", "ok", {"url": "http://x"}, NOW + timedelta(minutes=10), ("alert-resolver-down", None))
done = store.col("alert_history").find_one({"check": "resolver"})
check("…resolved: closed, with when and how", done["endedAt"] == NOW + timedelta(minutes=10) and done["endedAs"] == "ok",
      done)
monitor._update("resolver", "alert", {"url": "http://x"}, NOW + timedelta(hours=1), ("alert-resolver-down", None))
check("…a new alert later: a second entry", store.col("alert_history").count_documents({"check": "resolver"}) == 2)
monitor._update("resolver", "unknown", {}, NOW + timedelta(hours=2), ("alert-resolver-down", None))
check("…left as 'unknown' (could not check): closed as such",
      store.col("alert_history").find_one({"check": "resolver", "endedAs": "unknown"}) is not None)

r = ana.get("/portal/api/alerts")
listed = r.get_json() or {}
check("an organisation's administrator: their organisation's spikes only", r.status_code == 200
      and [(a["kind"], a["tenant"]) for a in listed["alerts"]] == [("404", acme["id"])]
      and listed["tenants"] == [], listed)
check("…asking for another organisation's: still their own", [a["tenant"] for a in
      ana.get(f"/portal/api/alerts?tenant={beta['id']}").get_json()["alerts"]] == [acme["id"]])
check("an editor may not", edu.get("/portal/api/alerts").status_code == 403)
listed = root.get("/portal/api/alerts").get_json()
check("a server administrator: every alert, newest first, organisations named",
      len(listed["alerts"]) == 4 and listed["alerts"][-1]["tenant"] == beta["id"]
      and listed["alerts"][-1]["organisation"] == "Beta Drinks" and len(listed["tenants"]) == 2, listed)
check("…filtered by organisation", [a["tenant"] for a in root.get(f"/portal/api/alerts?tenant={beta['id']}")
                                    .get_json()["alerts"]] == [beta["id"]])
check("…the installation's own checks (\"-\")", {a["kind"] for a in root.get("/portal/api/alerts?tenant=-")
                                                 .get_json()["alerts"]} == {"resolver"})
check("…by kind", {a["kind"] for a in root.get("/portal/api/alerts?kind=404").get_json()["alerts"]} == {"404"})
check("…by dates (from, to inclusive)", [a["tenant"] for a in root.get("/portal/api/alerts?from=2026-10-14&to=2026-10-14")
                                         .get_json()["alerts"]] == [beta["id"]])
check("…an unknown kind or a wrong date refused", code(root.get("/portal/api/alerts?kind=bogus")) == "alerts.kindUnknown"
      and code(root.get("/portal/api/alerts?from=17/10/2026")) == "alerts.dateInvalid")
r = ana.get("/portal/api/organisation")
check("the organisation's page lists its alerts", [a["kind"] for a in r.get_json()["alerts"]] == ["404"], r.get_json())

# ================================================================== the overview, filtered by organisation
G_ACME, G_BETA, G_OPER = gtin("0789123450001"), gtin("0789555500001"), gtin("0950600013435")
for value in (G_ACME, G_BETA, G_OPER):
    mock_data_entry.DB[f"01_{value}"] = {"default": "gs1:pip", "entries": [{"qualifiers": [], "itemDescription": "x",
                                         "links": [{"linktype": "gs1:pip", "href": "https://x.example/", "title": "t",
                                                    "hreflang": ["en"]}], "informative": []}]}
EVENTS = requestlog.events()
now = store.now() - timedelta(minutes=5)
for value, n in ((G_ACME, 3), (G_BETA, 5), (G_OPER, 7)):
    for _ in range(n):
        EVENTS.insert_one({"t": now, "expiresAt": now + timedelta(days=30), "m": "GET", "f": "uri", "s": 307,
                           "o": "redirect", "dev": "mobile", "ai": "01", "v": value, "cp": value[1:], "ms": 10})
whole = root.get("/portal/api/overview?days=7").get_json()
check("a server administrator's overview: the whole installation, with Operation", whole["usage"]["scans"] == 15
      and whole["whole"] is True and whole["scoped"] is False and whole["operation"] is not None
      and "worker" in whole["operation"], {k: whole.get(k) for k in ("whole", "scoped", "operation")})
mine = ana.get("/portal/api/overview?days=7").get_json()
one = root.get(f"/portal/api/overview?days=7&tenant={acme['id']}").get_json()
check("…filtered to an organisation: its figures, as its administrators see them", one["usage"]["scans"] == 3
      and one["whole"] is False and one["scoped"] is True and one["organisation"] == acme["id"]
      and one["usage"]["scans"] == mine["usage"]["scans"] and one["records"]["records"] == mine["records"]["records"], one)
check("…Operation still the installation's", one["operation"] is not None and "worker" in one["operation"])
operator = root.get("/portal/api/overview?days=7&tenant=operator").get_json()
check("…the operator's codes", operator["usage"]["scans"] == 7 and operator["organisation"] is None
      and operator["scoped"] is True, operator["usage"]["scans"])
check("…an unknown organisation refused", code(root.get("/portal/api/overview?days=7&tenant=t-nobody")) == "tenants.unknown")
check("an organisation's administrator: no Operation", mine["operation"] is None, mine.get("operation"))
check("…its lines that matter, with record quality: the last check, the log's days, its alerts",
      "lastCheckAt" in mine["records"] and [a["kind"] for a in mine["records"]["alerts"]] == ["404"]
      and mine["logDays"] > 0, mine["records"].get("alerts"))
check("…the filter ignored for them", ana.get(f"/portal/api/overview?days=7&tenant={beta['id']}").get_json()["usage"]
      ["scans"] == 3)
r = root.post("/portal/api/overview/export", json={"format": "csv", "days": 7, "tenant": beta["id"], "labels": {}},
              headers=ORIGIN)
rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip("﻿")), delimiter=";"))
scans = next((row for row in rows if row[1] == "overview.scans"), None)
check("the export follows the filter", r.status_code == 200 and scans and scans[2] == "5", scans)
check("…the last check and the log's days with records in the export",
      any(row[0] == "overview.group.records" and row[1] == "overview.op.logDays" for row in rows), rows[-6:])

# ================================================================== the page's texts and dialogs
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
script = open(os.path.join(PORTAL, "static", "app.js"), encoding="utf-8").read()
index = open(os.path.join(PORTAL, "static", "index.html"), encoding="utf-8").read()
codes = set(re.findall(r'"((?:org|alerts|prefixes|nav|dialog)\.[A-Za-z0-9.]+)"', script + index))
codes |= set(re.findall(r'data-i18n="((?:org|alerts|prefixes|nav|dialog)\.[A-Za-z0-9.]+)"', index))
codes |= {"menu.organisation", "menu.alerts", "tenants.open", "overview.organisation", "alerts.kind.resolver",
          "alerts.kind.backup", "alerts.kind.certificate", "alerts.kind.404", "alerts.kindUnknown", "alerts.dateInvalid",
          "org.tab.prefixes", "org.tab.users", "org.tab.domains", "org.tab.brands", "org.tab.sso", "org.tab.apikeys",
          "org.tab.alerts"}
codes = {c for c in codes if not c.endswith(".")}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"every new text in both languages ({len(codes)})", len(codes) > 60 and not missing, missing)
code_only = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", script, flags=re.S))
check("no confirmation through the browser's dialog left", "confirm(" not in code_only
      and script.count("await ask(") == 19, script.count("await ask("))   # the fourteen, the organisation's prefixes,
                                                                            # an older GCP length table (item 9.9),
                                                                            # a version of the privacy notice (ADR 0017)
                                                                            # a forwarding rule removed (ADR 0018)
                                                                            # and the original appearance (ADR 0019)
check("the sidebar is built from the user menu's screens (one list)", script.count('".menu-panel a.nav-item"') == 1
      and index.count("nav-item") == 17, index.count("nav-item"))     # with the privacy notice, forwarding and
                                                                        # the appearance

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
