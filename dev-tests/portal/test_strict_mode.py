"""
The strict mode for safety-critical link types in the portal (Documentation/adr/0022-answering-level.md, section 2.4),
through the portal's Flask test client: off by default; shown on the organisation's page with the five types; switched
on and off by the organisation's administrators (their own only: another organisation's is 404) and by the server
administrators (any organisation, and the operator's scope for the keys no organisation holds); refused to editors and
readers, in support access (403) and with a value that is not true or false (422); stored where the resolver reads it
(the tenant's "strictSafety", the setting "resolution.strict"); each change journalled once, with its label in both
languages; the list of types equal to the resolver's; the request log's outcome "withheld" accepted by the Requests
filter (alone and in "not found") and counted apart by the overview.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_strict_mode.py
"""
import ast
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
REPO = os.path.join(PORTAL, "..")
CONFIG = tempfile.mkdtemp()
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL="http://127.0.0.1:3397/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_strict_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
store.col("settings").delete_one({"_id": "resolution.strict"})
acme = tenants.create("Acme Pharma", ["7891234"], "root")
beta = tenants.create("Beta Health", ["7895555"], "root")
import app as portal  # noqa: E402
import requestlog  # noqa: E402
import resolution  # noqa: E402

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


def put(c, tenant, enabled):
    return c.put("/portal/api/resolution/strict", json={"tenant": tenant, "enabled": enabled}, headers=ORIGIN)


def page(c, tenant=None):
    return c.get("/portal/api/organisation" + (f"?id={tenant}" if tenant else "")).get_json()


users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))

# --------------------------------------------------------------------------- the organisation's page
d = page(ana)
check("off by default, on the organisation's page with the five safety-critical types",
      d["resolution"]["strict"] is False and d["resolution"]["types"] == ["recallStatus", "safetyInfo", "epil", "smpc",
                                                                          "eifu"] and d["resolution"]["editable"], d.get("resolution"))
check("…the operator's scope off by default too", page(root)["resolution"]["strict"] is False)

# --------------------------------------------------------------------------- an organisation's administrators
r = put(ana, acme["id"], True)
check("an organisation's administrator switches it on: resolution.strictOn", r.status_code == 200
      and code(r) == "resolution.strictOn" and r.get_json()["resolution"]["strict"] is True, (r.status_code, r.get_json()))
doc = store.col("tenants").find_one({"_id": acme["id"]})
check("…stored where the resolver reads it: the tenant's strictSafety, with who and when",
      doc.get(resolution.TENANT_FIELD) is True and doc.get("strictSafetyBy") == "ana"
      and isinstance(doc.get("strictSafetyUpdated"), datetime), doc)
d = page(ana)["resolution"]
check("…shown on the page, with who changed it", d["strict"] is True and d["updatedBy"] == "ana" and d["updated"], d)
check("…another organisation is not affected", not store.col("tenants").find_one({"_id": beta["id"]}).get("strictSafety"))
r = put(ana, beta["id"], True)
check("…another organisation's: 404 tenants.unknown, nothing changed", r.status_code == 404 and code(r) == "tenants.unknown"
      and not store.col("tenants").find_one({"_id": beta["id"]}).get("strictSafety"), (r.status_code, code(r)))
r = put(ana, "operator", True)
check("…the operator's scope: 404 too", r.status_code == 404 and not store.get_setting("resolution.strict"),
      (r.status_code, code(r)))
r = put(edu, acme["id"], False)
check("an editor may not change it: 403", r.status_code == 403
      and store.col("tenants").find_one({"_id": acme["id"]}).get("strictSafety") is True, r.status_code)
for value in ("yes", 1, None):
    r = put(ana, acme["id"], value)
    check(f"a value that is not true or false ({value!r}): 422 resolution.invalid", r.status_code == 422
          and code(r) == "resolution.invalid", (r.status_code, code(r)))
r = put(ana, acme["id"], False)
check("switched off again: resolution.strictOff", r.status_code == 200 and code(r) == "resolution.strictOff"
      and store.col("tenants").find_one({"_id": acme["id"]}).get("strictSafety") is False, r.get_json())

# --------------------------------------------------------------------------- the server administrators
r = put(root, beta["id"], True)
check("a server administrator switches it on for any organisation", r.status_code == 200
      and store.col("tenants").find_one({"_id": beta["id"]}).get("strictSafety") is True, r.get_json())
r = put(root, "operator", True)
check("…and for the operator's scope: the setting resolution.strict", r.status_code == 200
      and (store.get_setting("resolution.strict") or {}).get("enabled") is True
      and (store.get_setting("resolution.strict") or {}).get("updatedBy") == "root", store.get_setting("resolution.strict"))
check("…shown on the operator's page", page(root)["resolution"]["strict"] is True)
check("…an organisation's page shows its own", page(root, acme["id"])["resolution"]["strict"] is False)
r = put(root, "nobody", True)
check("…an organisation that does not exist: 404", r.status_code == 404 and code(r) == "tenants.unknown")
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN)
r = put(root, acme["id"], True)
check("in support access: read only, 403 resolution.readOnly", r.status_code == 403 and code(r) == "resolution.readOnly"
      and page(root)["resolution"]["editable"] is False, (r.status_code, code(r)))
root.delete("/portal/api/support", headers=ORIGIN)

# --------------------------------------------------------------------------- the journal
put(root, beta["id"], True)                                   # unchanged: not journalled again
entries = list(store.col("journal").find({"action": "resolution-strict"}))
details = sorted((e.get("tenant") or "-", e.get("detail")) for e in entries)
check("each change journalled once, in the organisation's (or the operator's) trail",
      details == sorted([(acme["id"], "strict=on"), (acme["id"], "strict=off"), (beta["id"], "strict=on"),
                         ("-", "strict=on")]), details)
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
check("the journal action and the messages in both languages", all(i18n.count(f'"{c}"') == 2 for c in (
    "audit.action.resolution-strict", "resolution.strictOn", "resolution.strictOff", "resolution.invalid",
    "resolution.readOnly", "requests.outcome.withheld", "overview.q.withheld", "org.tab.resolution")))

# --------------------------------------------------------------------------- the resolver's list
source = open(os.path.join(REPO, "web_server", "src", "resolution.py"), encoding="utf-8").read()
resolver_types = ast.literal_eval(re.search(r"^SAFETY_CRITICAL = (\(.*?\))", source, re.M).group(1))
check("the portal's list of safety-critical types is the resolver's", resolver_types == resolution.SAFETY_CRITICAL,
      (resolver_types, resolution.SAFETY_CRITICAL))
check("…and the stored names are the resolver's", re.search(r"^SETTING_STRICT = '(.+)'", source, re.M).group(1)
      == resolution.SETTING_STRICT and re.search(r"^TENANT_FIELD = '(.+)'", source, re.M).group(1)
      == resolution.TENANT_FIELD)

# --------------------------------------------------------------------------- the request log's outcome
check("the request log knows the outcome withheld", "withheld" in requestlog.OUTCOMES)
requestlog.events().delete_many({})
now = datetime.now(timezone.utc).replace(tzinfo=None)
for o in ("withheld", "noLink", "redirect"):
    requestlog.events().insert_one({"t": now, "ai": "01", "v": "07891234000019", "cp": "7891234000019", "o": o,
                                    "s": 404 if o != "redirect" else 307, "dev": "mobile", "m": "GET", "f": "uri",
                                    "expiresAt": datetime(2099, 1, 1)})
r = root.get("/portal/api/requests?outcome=withheld")
body = r.get_json() or {}
check("the Requests screen filters by withheld", r.status_code == 200 and [e.get("outcome") for e in body.get("events", [])]
      == ["withheld"], (r.status_code, body))
r = root.get("/portal/api/requests?outcome=notFound")
check("…and counts it among the requests not found (404)", sorted(e.get("outcome") for e in (r.get_json() or {}).get(
    "events", [])) == ["noLink", "withheld"], r.get_json())

r = root.get("/portal/api/overview")
q = (r.get_json() or {}).get("quality") or {}
check("the overview counts the requests withheld apart from those without a link", r.status_code == 200
      and q.get("withheld") == 1 and q.get("noLink") == 1 and q.get("previous", {}).get("withheld") == 0, q)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
