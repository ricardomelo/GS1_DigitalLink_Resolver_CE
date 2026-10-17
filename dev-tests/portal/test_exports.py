"""
Limits on exports (backlog items 7.1 and 9.8, Documentation/adr/0012-single-sign-on.md, sections 2.7 and 8), through the
portal's Flask test client: the installation's maximum set by server administrators (and only by them, outside support
access), each organisation's limits per role set on its page by its administrators (never above the maximum, never
another organisation's) and the operator's by server administrators; what applies to each role (the lower of its
limit and the maximum; an organisation's administrators the maximum; server administrators none, also during support
access); a role that may not export (0) refused every export — records, requests, the overview — before anything is
read; a limit refused above it with the numbers, its exact value allowed; the tenant API's record listing reaching at
most the API keys' limit (0 refuses it); PORTAL_EXPORT_LIMITS read once into the operator's and every organisation's
limits, then no longer; the page told the limit; refusals and changes in the journal; and every journal action
labelled in both languages on the audit trail.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_exports.py
"""
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3396
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_exports_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)
# The earlier setting: read once at the first start (an editor's limit of 2, malformed entries ignored)
os.environ["PORTAL_EXPORT_LIMITS"] = "reader:0, editor:2, bogus:5, admin:x"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
# On a real MongoDB the database may hold an earlier run's settings: the first start of an installation
for name in ("exports.seeded", "exports.maximum", "exports.operator"):
    store.col("settings").delete_one({"_id": name})
acme = tenants.create("Acme Foods", ["7891234"], "root")            # an organisation of before the upgrade
gamma = tenants.create("Gamma Teas", ["7896666"], "root")           # …one that already has limits of its own
store.col("tenants").update_one({"_id": gamma["id"]}, {"$set": {"exportLimits": {"editor": 7}}})
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import apikeys  # noqa: E402
import exportlimits  # noqa: E402
import requestlog  # noqa: E402

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


# --------------------------------------------------------------------------- PORTAL_EXPORT_LIMITS, read once
check("PORTAL_EXPORT_LIMITS read once: reader and editor kept, malformed entries and the administrators' ignored",
      exportlimits.parse_env("reader:0, editor:2, bogus:5, admin:x, admin:7") == {"reader": 0, "editor": 2},
      exportlimits.parse_env("reader:0, editor:2, bogus:5, admin:x, admin:7"))
check("…they became the operator's limits and those of the organisation that existed",
      exportlimits.limits_of(None) == {"reader": 0, "editor": 2}
      and tenants.get(acme["id"])["exportLimits"] == {"reader": 0, "editor": 2},
      (exportlimits.limits_of(None), tenants.get(acme["id"])["exportLimits"]))
check("…an organisation's own limits are kept", tenants.get(gamma["id"])["exportLimits"] == {"editor": 7},
      tenants.get(gamma["id"])["exportLimits"])
check("…the start is recorded, so it is not read again", bool(store.get_setting(exportlimits.SETTING_SEEDED)))
beta = tenants.create("Beta Drinks", ["7895555"], "root")
os.environ["PORTAL_EXPORT_LIMITS"] = "reader:9"
check("…a later start does not read it again (an organisation created since has no limits)",
      exportlimits.seed_from_env("reader:9") is False and tenants.get(beta["id"])["exportLimits"] == {}
      and exportlimits.limits_of(None) == {"reader": 0, "editor": 2})
check("no maximum by default", exportlimits.maximum() is None)

users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("rui", "rui-password-long", "reader", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
users.create("bob", "bob-password-long", "editor", tenant=beta["id"], must_change=False)
users.create("ope", "ope-password-long", "editor", must_change=False)
root, ana, edu, rui, bia, bob, ope = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "rui", "bia", "bob", "ope"))

# On a real MongoDB the request log's database is shared by every program of a run: start from an empty log
requestlog.events().delete_many({})
for value in (gtin("0789123452001"), gtin("0789123452002"), gtin("0789123452003")):
    ana.post("/portal/api/record", json={"key": "01", "value": value, "description": "x", "links": [
        {"linkType": "gs1:pip", "url": "https://acme.example.com/p", "hreflang": ["en"]}]}, headers=ORIGIN)
for value in (gtin("0950600013401"), gtin("0950600013402"), gtin("0950600013403")):   # the operator's records
    ope.post("/portal/api/record", json={"key": "01", "value": value, "description": "z", "links": [
        {"linkType": "gs1:pip", "url": "https://operator.example.com/p", "hreflang": ["en"]}]}, headers=ORIGIN)
for value in (gtin("0789555552001"), gtin("0789555552002"), gtin("0789555552003")):
    bia.post("/portal/api/record", json={"key": "01", "value": value, "description": "y", "links": [
        {"linkType": "gs1:pip", "url": "https://beta.example.com/p", "hreflang": ["en"]}]}, headers=ORIGIN)


def export(c, kind):
    if kind == "records":
        return c.post("/portal/api/export", json={"format": "csv", "labels": {}}, headers=ORIGIN)
    if kind == "requests":
        return c.get("/portal/api/requests.csv")
    return c.post("/portal/api/overview/export", json={"format": "csv", "days": 7, "labels": {}}, headers=ORIGIN)


# --------------------------------------------------------------------------- the limits seeded apply
for kind in ("records", "requests", "overview"):
    r = export(rui, kind)
    check(f"a reader (limit 0) may not export {kind}: 403 export.notAllowed", r.status_code == 403
          and code(r) == "export.notAllowed" and r.get_json()["params"]["role"] == "reader", (r.status_code, code(r)))
r = export(edu, "records")
check("an editor (limit 2) refused 3 records, with the numbers", r.status_code == 422 and code(r) == "export.tooMany"
      and r.get_json()["params"] == {"max": 2, "rows": 3}, r.get_json())
check("…the overview's figures are not rows: allowed", export(edu, "overview").status_code == 200)
one = f"/01/{gtin('0789123452001')}|"
r = edu.post("/portal/api/export", json={"format": "csv", "labels": {}, "only": [one]}, headers=ORIGIN)
body = r.get_data(as_text=True)
check("…a filtered list's export (\"only\": the records shown) within the limit: only those records",
      r.status_code == 200 and gtin("0789123452001") in body and gtin("0789123452002") not in body, (r.status_code, body[:200]))
check("…requests within the limit: allowed", export(edu, "requests").status_code == 200)
EVENTS = requestlog.events()
now = store.now()
for n in range(3):
    EVENTS.insert_one({"t": now, "expiresAt": now + timedelta(days=1), "m": "GET", "f": "uri", "s": 307, "o": "redirect",
                       "dev": "mobile", "ai": "01", "v": gtin("0789123452001"), "cp": "7891234", "ms": 5})
r = export(edu, "requests")
check("…3 requests above the limit of 2: refused", r.status_code == 422 and code(r) == "export.tooMany"
      and r.get_json()["params"]["rows"] == 3, (r.status_code, r.get_json()))
EVENTS.delete_one({"v": gtin("0789123452001")})
check("…exactly the limit (2 requests): allowed", export(edu, "requests").status_code == 200)
for kind in ("records", "requests", "overview"):
    check(f"an organisation's administrator without a maximum has no limit ({kind})", export(ana, kind).status_code == 200)
check("an organisation created after the upgrade has no limits (Beta's editor exports 3 records)",
      export(bob, "records").status_code == 200)
r = export(ope, "records")
check("the operator's editor has the operator's limit (2): 3 records refused", r.status_code == 422
      and r.get_json()["params"] == {"max": 2, "rows": 3}, (r.status_code, r.get_json()))

# --------------------------------------------------------------------------- the installation's maximum
r = ana.put("/portal/api/exports/maximum", json={"maximum": 5}, headers=ORIGIN)
check("an organisation's administrator may not set the maximum: 403", r.status_code == 403
      and exportlimits.maximum() is None, (r.status_code, code(r)))
for bad in (-1, "abc", 1.5, True, 10_000_001):
    r = root.put("/portal/api/exports/maximum", json={"maximum": bad}, headers=ORIGIN)
    check(f"a maximum of {bad!r} refused: 422 exports.maximumInvalid", r.status_code == 422
          and code(r) == "exports.maximumInvalid" and r.get_json()["params"]["max"] == exportlimits.MAX_ROWS, r.get_json())
r = root.put("/portal/api/exports/maximum", json={"maximum": 2}, headers=ORIGIN)
check("a server administrator sets the maximum (2)", r.status_code == 200 and code(r) == "exports.maximumSaved"
      and r.get_json()["params"] == {"max": 2} and exportlimits.maximum() == 2, r.get_json())
check("…the Organisations screen reads it", root.get("/portal/api/tenants").get_json()["exportMaximum"] == 2)
r = export(ana, "records")
check("…an organisation's administrator now has the maximum: 3 records refused", r.status_code == 422
      and r.get_json()["params"] == {"max": 2, "rows": 3}, r.get_json())
r = export(bob, "records")
check("…an organisation without limits of its own too", r.status_code == 422 and r.get_json()["params"]["max"] == 2)
check("…the overview's figures are still allowed", export(ana, "overview").status_code == 200)
check("…the operator's users are not capped by it (their own limit applies)",
      exportlimits.effective(None, "reader") == 0 and exportlimits.effective(None, "editor") == 2
      and exportlimits.effective(None, "admin") is None)
check("…the server administrator has no limit", export(root, "records").status_code == 200)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 9"}, headers=ORIGIN)
check("…also in support access (a reader there)", export(root, "records").status_code == 200)
r = root.put("/portal/api/exports/maximum", json={"maximum": 9}, headers=ORIGIN)
check("…in support access the maximum cannot be changed: 403 exports.readOnly", r.status_code == 403
      and code(r) == "exports.readOnly" and exportlimits.maximum() == 2, (r.status_code, code(r)))
r = root.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"reader": 1}}, headers=ORIGIN)
check("…nor an organisation's limits", r.status_code == 403 and code(r) == "exports.readOnly")
page = root.get("/portal/api/organisation").get_json()["exports"]
check("…the organisation's page shows them read only", page["editable"] is False and page["maximum"] == 2)
root.delete("/portal/api/support", headers=ORIGIN)

# --------------------------------------------------------------------------- an organisation's own limits
r = root.put("/portal/api/exports/maximum", json={"maximum": 1000}, headers=ORIGIN)
page = ana.get("/portal/api/organisation").get_json()["exports"]
check("the organisation's page: the maximum, the limits set and what applies to each role",
      page == {"maximum": 1000, "limits": {"reader": 0, "editor": 2}, "editable": True,
               "effective": {"reader": 0, "editor": 2, "admin": 1000, "api": 1000}}, page)
r = ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"reader": 1001}}, headers=ORIGIN)
check("a limit above the maximum refused: 422 exports.invalid with the maximum", r.status_code == 422
      and code(r) == "exports.invalid" and r.get_json()["params"] == {"max": 1000}, r.get_json())
for bad in ({"reader": -1}, {"reader": "x"}, {"admin": 5}, {"owner": 1}, ["reader"], {"editor": 2.5}):
    r = ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": bad}, headers=ORIGIN)
    check(f"limits {bad!r} refused: 422", r.status_code == 422 and code(r) == "exports.invalid", (r.status_code, code(r)))
check("…nothing changed by the refusals", tenants.get(acme["id"])["exportLimits"] == {"reader": 0, "editor": 2})
r = ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"reader": 5, "editor": None, "api": "1"}},
            headers=ORIGIN)
check("an organisation's administrator sets its limits (reader 5, editor emptied, API keys 1)", r.status_code == 200
      and code(r) == "exports.saved" and tenants.get(acme["id"])["exportLimits"] == {"reader": 5, "api": 1}
      and r.get_json()["exports"]["effective"] == {"reader": 5, "editor": 1000, "admin": 1000, "api": 1}, r.get_json())
check("…a reader with a limit of 5 now exports 3 records", export(rui, "records").status_code == 200)
check("…an emptied limit follows the maximum (the editor exports 3 records)", export(edu, "records").status_code == 200)
r = ana.put("/portal/api/exports/limits", json={"tenant": beta["id"], "limits": {"reader": 0}}, headers=ORIGIN)
check("…another organisation's limits: 404, unchanged", r.status_code == 404 and tenants.get(beta["id"])["exportLimits"] == {})
r = edu.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"reader": 0}}, headers=ORIGIN)
check("…an editor may not set them: 403", r.status_code == 403)
r = root.put("/portal/api/exports/limits", json={"tenant": beta["id"], "limits": {"editor": 2}}, headers=ORIGIN)
check("a server administrator sets an organisation's limits", r.status_code == 200
      and tenants.get(beta["id"])["exportLimits"] == {"editor": 2} and export(bob, "records").status_code == 422)
r = root.put("/portal/api/exports/limits", json={"tenant": "operator", "limits": {"reader": None, "editor": 5_000_000}},
             headers=ORIGIN)
check("…and the operator's, which no maximum caps", r.status_code == 200
      and exportlimits.limits_of(None) == {"editor": 5_000_000} and export(ope, "records").status_code == 200, r.get_json())
r = root.put("/portal/api/exports/limits", json={"tenant": "t-unknown", "limits": {"reader": 0}}, headers=ORIGIN)
check("…an unknown organisation: 404", r.status_code == 404 and code(r) == "tenants.unknown")
r = bia.put("/portal/api/exports/limits", json={"tenant": "operator", "limits": {"reader": 0}}, headers=ORIGIN)
check("…an organisation's administrator may not set the operator's: 404", r.status_code == 404
      and exportlimits.limits_of(None) == {"editor": 5_000_000})
operator_page = root.get("/portal/api/organisation?id=operator").get_json()["exports"]
check("the operator's page: no maximum, the server administrators without limit", operator_page["maximum"] is None
      and operator_page["effective"]["admin"] is None and operator_page["effective"]["editor"] == 5_000_000, operator_page)
root.put("/portal/api/exports/maximum", json={"maximum": 3}, headers=ORIGIN)
check("a maximum lowered below a limit already set: the maximum applies", exportlimits.effective(
    tenants.get(acme["id"]), "reader") == 3 and tenants.get(acme["id"])["exportLimits"]["reader"] == 5)
r = root.put("/portal/api/exports/maximum", json={"maximum": ""}, headers=ORIGIN)
check("the maximum lifted (empty): exports.maximumCleared, no limit again for administrators",
      r.status_code == 200 and code(r) == "exports.maximumCleared" and exportlimits.maximum() is None
      and exportlimits.effective(tenants.get(acme["id"]), "admin") is None)

# --------------------------------------------------------------------------- the tenant API's record listing
key, _ = apikeys.create("ERP", ["records:read"], 30, [], acme["id"], "ana")


def listing(**params):
    return portal.app.test_client().get("/portal/api/v1/records", query_string=params,
                                        headers={"Authorization": f"Bearer {key}"})


r = listing()
body = r.get_json()
check("the API's listing reaches at most the API keys' limit (1 of 3 records), and says so", r.status_code == 200
      and len(body["records"]) == 1 and body["total"] == 3 and body["exportLimit"] == 1 and body["next"] is None, body)
ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"api": 2}}, headers=ORIGIN)
first = listing(limit=1).get_json()
second = listing(limit=1, after=first["next"]).get_json()
check("…paging stops at the limit (2 records over pages of 1)", len(first["records"]) == 1 and first["next"]
      and len(second["records"]) == 1 and second["next"] is None, (first, second))
ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"api": 0}}, headers=ORIGIN)
r = listing()
check("…an API keys' limit of 0 refuses the listing: 403 export.notAllowed (role api)", r.status_code == 403
      and code(r) == "export.notAllowed" and r.get_json()["params"]["role"] == "api", (r.status_code, r.get_json()))
r = portal.app.test_client().get(f"/portal/api/v1/records/01/{gtin('0789123452001')}",
                                 headers={"Authorization": f"Bearer {key}"})
check("…one record is still read (not an export)", r.status_code == 200, r.status_code)
ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"api": None}}, headers=ORIGIN)
body = listing().get_json()
check("…no limit: every record, exportLimit null", len(body["records"]) == 3 and body["exportLimit"] is None, body)

# --------------------------------------------------------------------------- the page and the journal
ana.put("/portal/api/exports/limits", json={"tenant": acme["id"], "limits": {"reader": 0, "editor": 2}}, headers=ORIGIN)
check("the page is told the limit", rui.get("/portal/api/config").get_json()["exportLimit"] == 0
      and edu.get("/portal/api/config").get_json()["exportLimit"] == 2
      and ana.get("/portal/api/config").get_json()["exportLimit"] is None
      and root.get("/portal/api/config").get_json()["exportLimit"] is None)
refusals = list(store.col("journal").find({"action": "export-refused"}))
check("each refusal is in the journal with the role, the rows and the limit",
      any("role=editor rows=3 limit=2" in (e.get("detail") or "") for e in refusals)
      and any("role=api rows=- limit=0" in (e.get("detail") or "") for e in refusals), [e.get("detail") for e in refusals])
changes = list(store.col("journal").find({"action": "export-limits", "tenant": acme["id"]}))
check("each change of an organisation's limits is in its journal", len(changes) >= 4
      and any(e.get("detail") == "reader=5 editor=- api=1" for e in changes), [e.get("detail") for e in changes])
check("each change of the maximum is in the operator's journal", {e.get("detail") for e in store.col("journal").find(
    {"action": "export-maximum"})} >= {"maximum=2", "maximum=1000", "maximum=-"})

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
actions = set()
for name in os.listdir(PORTAL):
    if name.endswith(".py"):
        actions |= set(re.findall(r'log_event\("([a-z-]+)"', open(os.path.join(PORTAL, name), encoding="utf-8").read()))
missing = sorted(a for a in actions if i18n.count(f'"audit.action.{a}"') != 2)
check(f"every journal action has its label in both languages ({len(actions)})", len(actions) > 20 and not missing,
      missing)
check("the export texts in both languages", all(i18n.count(f'"{c}"') == 2 for c in ("export.notAllowed", "export.tooMany")))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
