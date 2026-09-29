"""
Portal governance through the portal's own API (Flask test client) against the in-memory stand-in for the
data entry API: roles, GS1 Company Prefix restrictions, user administration, temporary passwords, the
history of a record and the audit trail.

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_governance.py
"""
import json
import os
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3399
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_USERS_FILE=f"{CONFIG}/users.json", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
sys.path[:0] = [HERE, PORTAL]

# A users file written before roles existed: {"name": "<hash>"}
from werkzeug.security import generate_password_hash  # noqa: E402
with open(f"{CONFIG}/users.json", "w") as fh:
    json.dump({"boss": generate_password_hash("boss-password-long")}, fh)

import mock_data_entry  # noqa: E402
import app as portal  # noqa: E402
import users  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username, password):
    c = portal.app.test_client()
    r = c.post("/portal/api/login", json={"username": username, "password": password})
    return c, r


def record(value, url="https://example.org/x", description="Item", qualifiers=None):
    body = {"key": "01", "value": value, "description": description,
            "links": [{"linkType": "gs1:pip", "url": url, "hreflang": ["en"], "title": "t"}]}
    if qualifiers:
        body["qualifiers"] = qualifiers
    return body


# ------------------------------------------------------------------ migration and administration
check("old users file read: existing user is an administrator", users.get("boss")["role"] == "admin")
admin, r = client("boss", "boss-password-long")
check("administrator signs in", r.status_code == 200 and r.get_json()["mustChange"] is False, r.get_json())

r = admin.post("/portal/api/users", json={"username": "ana", "role": "editor", "prefixes": ["7898357"]})
ana_password = r.get_json().get("password")
check("administrator creates an editor limited to a prefix; temporary password returned once",
      r.status_code == 201 and len(ana_password or "") == 16 and users.get("ana")["mustChange"], r.get_json())
r = admin.post("/portal/api/users", json={"username": "rui", "role": "reader"})
rui_password = r.get_json().get("password")
check("administrator creates a reader", r.status_code == 201)
check("old file converted on write", isinstance(json.load(open(f"{CONFIG}/users.json"))["boss"], dict))
check("duplicate user refused", admin.post("/portal/api/users", json={"username": "ana", "role": "reader"}).get_json()["code"] == "users.exists")
check("invalid prefix refused", admin.post("/portal/api/users", json={"username": "x1x", "role": "reader", "prefixes": ["78A"]})
      .get_json()["code"] == "users.prefixInvalid")
listing = admin.get("/portal/api/users").get_json()["users"]
check("user list without password hashes", {u["username"] for u in listing} == {"boss", "ana", "rui"}
      and not any("hash" in u for u in listing), listing)
check("administrator cannot demote himself", admin.put("/portal/api/users/boss", json={"role": "editor"}).get_json()["code"] == "users.notSelf")
try:
    users.update("boss", role="editor")
    check("last administrator protected", False)
except users.UserError as exc:
    check("last administrator protected", exc.code == "users.lastAdmin", exc.code)

# ------------------------------------------------------------------ temporary password
ana, r = client("ana", ana_password)
check("temporary password: sign-in says a new password is needed", r.get_json()["mustChange"] is True)
check("temporary password: other calls refused", ana.get("/portal/api/records").get_json()["code"] == "password.mustChange")
check("temporary password: configuration still available", ana.get("/portal/api/config").status_code == 200)
r = ana.post("/portal/api/password", json={"currentPassword": ana_password, "newPassword": "ana-own-password"})
check("temporary password replaced", r.status_code == 200 and not users.get("ana")["mustChange"], r.get_json())
rui, _ = client("rui", rui_password)
rui.post("/portal/api/password", json={"currentPassword": rui_password, "newPassword": "rui-own-password"})

# ------------------------------------------------------------------ roles and prefixes
r = ana.post("/portal/api/record", json=record("07898357410015", description="Café"))
check("editor saves a record of her prefix", r.status_code == 201, r.get_json())
r = ana.post("/portal/api/record", json=record("09506000134352"))
check("editor refused outside her prefix", r.status_code == 403 and r.get_json()["code"] == "access.prefix", r.get_json())
admin.post("/portal/api/record", json=record("09506000134352", description="Açaí"))
listed = [x["value"] for x in ana.get("/portal/api/records").get_json()["records"]]
check("record list limited to the prefix", listed == ["07898357410015"], listed)
check("administrator sees everything", len(admin.get("/portal/api/records").get_json()["records"]) == 2)
check("editor cannot read a record outside her prefix",
      ana.get("/portal/api/record?key=01&value=09506000134352").get_json()["code"] == "access.prefix")
check("config tells the browser the role and prefixes",
      ana.get("/portal/api/config").get_json()["role"] == "editor" and ana.get("/portal/api/config").get_json()["prefixes"] == ["7898357"])

r = rui.post("/portal/api/record", json=record("07898357410015"))
check("reader cannot save", r.status_code == 403 and r.get_json()["code"] == "access.role", r.get_json())
check("reader cannot delete", rui.delete("/portal/api/record?key=01&value=07898357410015").get_json()["code"] == "access.role")
check("reader cannot import", rui.post("/portal/api/import/preview", json={}).get_json()["code"] == "access.role")
check("reader consults and exports", rui.get("/portal/api/record?key=01&value=07898357410015").status_code == 200
      and rui.post("/portal/api/export", json={"format": "csv"}).status_code == 200)
check("reader and editor cannot administer", rui.get("/portal/api/users").status_code == 403
      and ana.get("/portal/api/audit").status_code == 403)

import base64  # noqa: E402
sheet = "gtin;description;linkType;url\n07898357410022;Chá;gs1:pip;https://example.org/cha\n09506000134369;Other;gs1:pip;https://example.org/o\n"
preview = ana.post("/portal/api/import/preview", json={"filename": "x.csv", "content": base64.b64encode(sheet.encode()).decode(),
                                                       "labels": {}}).get_json()
check("import preview: rows outside the prefix refused", preview["counts"]["create"] == 1
      and any(e["code"] == "access.prefixRow" and e["row"] == 3 for e in preview["errors"]), preview)

# ------------------------------------------------------------------ history and audit
ana.post("/portal/api/record", json=record("07898357410015", url="https://example.org/v2", description="Café v2"))
versions = ana.get("/portal/api/history?key=01&value=07898357410015").get_json()["versions"]
check("history: newest first, with the content of each version",
      [v["action"] for v in versions] == ["update", "create"] and versions[1]["doc"]["itemDescription"] == "Café"
      and versions[0]["user"] == "ana", versions)
ana.delete("/portal/api/record?key=01&value=07898357410015")
versions = admin.get("/portal/api/history?key=01&value=07898357410015").get_json()["versions"]
check("history keeps a deleted record's last content", versions[0]["action"] == "delete"
      and versions[0]["doc"]["itemDescription"] == "Café v2", versions[:1])
events = admin.get("/portal/api/audit?user=ana").get_json()["events"]
check("audit trail filtered by user, without record contents",
      {e["action"] for e in events} >= {"login", "password-change", "create", "update", "delete"}
      and all("doc" not in e for e in events), [e["action"] for e in events])
csv_text = admin.get("/portal/api/audit.csv?q=user-create").get_data(as_text=True)
check("audit trail as CSV", csv_text.startswith("\ufeffat;user;action") and csv_text.count("user-create") == 2, csv_text[:200])

# ------------------------------------------------------------------ disabling and removing
admin.put("/portal/api/users/rui", json={"disabled": True})
check("disabled user signed out at once", rui.get("/portal/api/records").status_code == 401)
_, r = client("rui", "rui-own-password")
check("disabled user cannot sign in", r.status_code == 401)
r = admin.post("/portal/api/users/ana/reset", json={})
check("password reset: temporary password, other sessions ended", len(r.get_json().get("password") or "") == 16
      and ana.get("/portal/api/records").status_code == 401 and users.get("ana")["mustChange"])
check("user removed", admin.delete("/portal/api/users/rui").status_code == 200 and users.get("rui") is None)
check("administrator cannot remove himself", admin.delete("/portal/api/users/boss").get_json()["code"] == "users.notSelf")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
