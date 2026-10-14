"""
Per-role limits on exports (backlog item 7.1, PORTAL_EXPORT_LIMITS), through the portal's Flask test client: a role
that may not export (0) is refused every export — records, requests, the overview — before anything is read; a role
with a number may export up to that many rows (records, requests) and is refused above it, with the numbers; roles
not named, administrators and server administrators (also during support access) have no limit; malformed entries are
ignored; the page is told the limit; each refusal is in the journal; and every action of the journal has its label in
both languages on the audit trail.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_exports.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from PIL import Image
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
os.environ["PORTAL_EXPORT_LIMITS"] = "reader:0, editor:2, bogus:5, admin:x"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import requestlog  # noqa: E402
import gs1  # noqa: E402
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


def image(kind="PNG", size=(60, 30), colour=(10, 120, 200)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind)
    return out.getvalue()


def data_uri(data, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))



users.create("rui", "rui-password-long", "reader", tenant=acme["id"], must_change=False)
rui = client("rui", "rui-password-long")
check("malformed entries ignored, the others read", portal.EXPORT_LIMITS == {"reader": 0, "editor": 2},
      portal.EXPORT_LIMITS)
for value in (gtin("0789123452001"), gtin("0789123452002"), gtin("0789123452003")):
    ana.post("/portal/api/record", json={"key": "01", "value": value, "description": "x", "links": [
        {"linkType": "gs1:pip", "url": "https://acme.example.com/p", "hreflang": ["en"]}]}, headers=ORIGIN)


def export(c, kind):
    if kind == "records":
        return c.post("/portal/api/export", json={"format": "csv", "labels": {}}, headers=ORIGIN)
    if kind == "requests":
        return c.get("/portal/api/requests.csv")
    return c.post("/portal/api/overview/export", json={"format": "csv", "days": 7, "labels": {}}, headers=ORIGIN)


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
    check(f"an administrator has no limit ({kind})", export(ana, kind).status_code == 200)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 9"}, headers=ORIGIN)
check("a server administrator in support access (a reader there) has no limit", export(root, "records").status_code == 200)
root.delete("/portal/api/support", headers=ORIGIN)
check("the page is told the limit", rui.get("/portal/api/config").get_json()["exportLimit"] == 0
      and edu.get("/portal/api/config").get_json()["exportLimit"] == 2
      and ana.get("/portal/api/config").get_json()["exportLimit"] is None)
refusals = list(store.col("journal").find({"action": "export-refused"}))
check("each refusal is in the journal with the role, the rows and the limit", len(refusals) == 5
      and any("role=editor rows=3 limit=2" in (e.get("detail") or "") for e in refusals), [e.get("detail") for e in refusals])

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
