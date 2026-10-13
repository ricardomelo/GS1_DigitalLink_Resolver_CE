"""
Tenants through the portal's own API (Flask test client) against the in-memory stand-in for the data entry API
(Documentation/adr/0002-tenants.md): organisations that own GS1 Company Prefixes, the operator's records and
users, the server administrator, tenant administrators, e-mail addresses, support access, the audit trail and
record history per tenant, link check results per scope, and the check the job worker makes before each
imported record.

Runs against mongomock unless PORTAL_DB_URI names a real MongoDB (the CI job "database" does that).

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_tenants.py
"""
import base64
import os
import sys
import tempfile
import threading
import time

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3397
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_tenants_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "embedded"               # imports run in a thread of the portal
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)          # server administrator
users.create("opedit", "opedit-password-long", "editor", must_change=False)     # operator editor, every prefix
import app as portal  # noqa: E402
import journal  # noqa: E402
import tenants  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def gtin(body13: str) -> str:
    """A GTIN-14 with its check digit, from the indicator and the next 12 digits."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


def client(username, password):
    c = portal.app.test_client()
    r = c.post("/portal/api/login", json={"username": username, "password": password})
    return c, r


def record(value, url="https://example.org/x", description="Item"):
    return {"key": "01", "value": value, "description": description,
            "links": [{"linkType": "gs1:pip", "url": url, "hreflang": ["en"], "title": "t"}]}


def code(r):
    return (r.get_json() or {}).get("code")


def listed(c):
    r = c.get("/portal/api/records")
    return sorted(x["value"] for x in r.get_json().get("records", [])) if r.status_code == 200 else r.status_code


def events(c, **query):
    r = c.get("/portal/api/audit?" + "&".join(f"{k}={v}" for k, v in query.items()))
    return r.get_json().get("events", []) if r.status_code == 200 else r.status_code


ACME_A = gtin("0789123450001")      # Acme, prefix 7891234, inside 78912345
ACME_B = gtin("0789123410001")      # Acme, prefix 7891234, outside 78912345
ACME_C = gtin("0789567810001")      # Acme, prefix 7895678
BETA = gtin("0789835741001")        # Beta, prefix 7898357
OPER = gtin("0950600013435")        # the operator's (no tenant)
LATER = gtin("0956000010001")       # the operator's, given to a tenant later in the test

root, r = client("root", "root-password-long")
check("server administrator signs in", r.status_code == 200, r.get_json())
opedit, _ = client("opedit", "opedit-password-long")
for value in (ACME_A, ACME_B, ACME_C, BETA, OPER, LATER):
    r = opedit.post("/portal/api/record", json=record(value))
check("before any tenant: an operator editor writes every record (behaviour unchanged)",
      len(mock_data_entry.DB) == 6 and listed(opedit) == sorted([ACME_A, ACME_B, ACME_C, BETA, OPER, LATER]),
      listed(opedit))
cfg = root.get("/portal/api/config").get_json()
check("configuration: the operator's administrator is a server administrator, no tenant, no support access",
      cfg["serverAdmin"] is True and cfg["tenant"] is None and cfg["support"] is None and cfg["accountRole"] == "admin", cfg)
check("only server administrators manage tenants", opedit.get("/portal/api/tenants").status_code == 403
      and code(opedit.post("/portal/api/tenants", json={"name": "X", "prefixes": []})) == "access.serverAdmin")

# ------------------------------------------------------------------ tenants and their prefixes
r = root.post("/portal/api/tenants", json={"name": "  Acme   Foods ", "prefixes": ["7895678", "7891234"]})
acme = (r.get_json() or {}).get("tenant") or {}
check("tenant created: name tidied, prefixes sorted, id t-<12 hex>", r.status_code == 201 and acme.get("name") == "Acme Foods"
      and acme.get("prefixes") == ["7891234", "7895678"] and len(acme.get("id", "")) == 14 and acme["id"].startswith("t-"),
      r.get_json())
check("tenant name unique ignoring case", code(root.post("/portal/api/tenants", json={"name": "acme foods", "prefixes": []}))
      == "tenants.nameExists")
check("tenant name too short refused", code(root.post("/portal/api/tenants", json={"name": "A", "prefixes": []})) == "tenants.nameInvalid")
check("invalid prefix refused", code(root.post("/portal/api/tenants", json={"name": "Bad", "prefixes": ["78A"]})) == "users.prefixInvalid")
r = root.post("/portal/api/tenants", json={"name": "Redundant", "prefixes": ["5601234", "56012345"]})
check("prefix covered by another of the same tenant refused", code(r) == "tenants.prefixRedundant"
      and r.get_json()["params"] == {"prefix": "56012345", "covered": "5601234"}, r.get_json())
for prefix in ("789123", "78912345", "7891234"):
    r = root.post("/portal/api/tenants", json={"name": "Beta", "prefixes": [prefix]})
    check(f"prefix {prefix} overlapping another tenant's refused, naming it", code(r) == "tenants.prefixOverlap"
          and r.get_json()["params"]["tenant"] == "Acme Foods", r.get_json())
r = root.post("/portal/api/tenants", json={"name": "Beta", "prefixes": ["7898357"]})
beta = r.get_json()["tenant"]
check("second tenant with its own prefix", r.status_code == 201)
check("tenant list: users, records per tenant, the operator's records",
      [(t["name"], t["users"], t["records"]) for t in root.get("/portal/api/tenants").get_json()["tenants"]]
      == [("Acme Foods", 0, 3), ("Beta", 0, 1)] and root.get("/portal/api/tenants").get_json()["operatorRecords"] == 2,
      root.get("/portal/api/tenants").get_json())

# ------------------------------------------------------------------ the operator after tenants exist
check("operator users now reach only the records no tenant holds", listed(opedit) == sorted([OPER, LATER])
      and listed(root) == sorted([OPER, LATER]), (listed(opedit), listed(root)))
check("an operator editor cannot open, save, label or check a tenant's record",
      opedit.get(f"/portal/api/record?key=01&value={ACME_A}").status_code == 403
      and opedit.post("/portal/api/record", json=record(ACME_A, url="https://example.org/stolen")).status_code == 403
      and opedit.get(f"/portal/api/qrcode?key=01&value={ACME_A}").status_code == 403
      and opedit.get(f"/portal/api/history?key=01&value={ACME_A}").status_code == 403)
check("the server administrator cannot either (outside support access)",
      root.get(f"/portal/api/record?key=01&value={BETA}").status_code == 403)
r = root.post("/portal/api/users", json={"username": "opread", "role": "reader", "prefixes": ["78912345"]})
check("an operator user cannot be limited to a prefix inside a tenant's", code(r) == "users.prefixOfTenant"
      and r.get_json()["params"]["tenant"] == "Acme Foods", r.get_json())
r = root.post("/portal/api/users", json={"username": "opread", "role": "reader", "prefixes": ["95600001"]})
check("an operator user limited to an operator prefix", r.status_code == 201, r.get_json())
r = root.post("/portal/api/tenants", json={"name": "Gamma", "prefixes": ["9560"]})
check("a prefix holding an operator user's whole range is not given to a tenant", code(r) == "tenants.prefixOperatorUser"
      and r.get_json()["params"]["users"] == "opread", r.get_json())

# ------------------------------------------------------------------ users of tenants
r = root.post("/portal/api/users", json={"username": "ana", "role": "admin", "tenant": acme["id"], "email": " Ana@Acme.Example "})
ana_pw = r.get_json().get("password")
check("server administrator creates a tenant administrator with an e-mail address", r.status_code == 201
      and users.get("ana")["tenant"] == acme["id"] and users.get("ana")["email"] == "ana@acme.example", r.get_json())
check("e-mail unique ignoring case", code(root.post("/portal/api/users", json={"username": "ana2", "role": "reader",
                                                                              "tenant": acme["id"], "email": "ANA@acme.example"}))
      == "users.emailExists")
check("e-mail checked for form", code(root.post("/portal/api/users", json={"username": "ana3", "role": "reader",
                                                                          "email": "ana at acme"})) == "users.emailInvalid")
check("unknown tenant refused", code(root.post("/portal/api/users", json={"username": "x9x", "role": "reader",
                                                                         "tenant": "t-000000000000"})) == "users.tenantUnknown")
r = root.post("/portal/api/users", json={"username": "bia", "role": "editor", "tenant": beta["id"]})
bia_pw = r.get_json().get("password")
check("journal: user-create of a tenant user in the tenant's trail, marked as done by the operator",
      store.col("journal").find_one({"action": "user-create", "detail": {"$regex": "^ana "}}, {"_id": 0, "tenant": 1, "byOperator": 1})
      == {"tenant": acme["id"], "byOperator": True})
check("the e-mail address never reaches the journal", not store.col("journal").find_one({"detail": {"$regex": "acme.example"}}))

ana, r = client("ana", ana_pw)
ana.post("/portal/api/password", json={"currentPassword": ana_pw, "newPassword": "ana-password-long"})
bia, _ = client("bia", bia_pw)
bia.post("/portal/api/password", json={"currentPassword": bia_pw, "newPassword": "bia-password-long"})
cfg = ana.get("/portal/api/config").get_json()
check("configuration of a tenant administrator: the tenant, not a server administrator",
      cfg["tenant"] == {"id": acme["id"], "name": "Acme Foods", "disabled": False} and cfg["serverAdmin"] is False, cfg)
check("a tenant administrator does not manage tenants", ana.get("/portal/api/tenants").status_code == 403
      and ana.post("/portal/api/support", json={"tenant": beta["id"], "reason": "curious"}).status_code == 403)
r = ana.post("/portal/api/users", json={"username": "caio", "role": "editor", "tenant": beta["id"], "prefixes": ["78912345"],
                                        "email": "caio@acme.example"})
caio_pw = r.get_json().get("password")
check("a tenant administrator creates users of his own tenant only (the tenant asked for is ignored)",
      r.status_code == 201 and users.get("caio")["tenant"] == acme["id"], r.get_json())
check("a tenant user's prefixes lie inside the tenant's", code(ana.post("/portal/api/users", json={
      "username": "dora", "role": "reader", "prefixes": ["7898357"]})) == "users.prefixOutsideTenant")
names = [u["username"] for u in ana.get("/portal/api/users").get_json()["users"]]
check("a tenant administrator lists the tenant's users only, without the tenants list",
      names == ["ana", "caio"] and ana.get("/portal/api/users").get_json()["tenants"] == [], names)
everyone = root.get("/portal/api/users").get_json()
check("the server administrator lists every user, with the organisation's name and the tenants",
      [(u["username"], u["tenantName"]) for u in everyone["users"]]
      == [("ana", "Acme Foods"), ("bia", "Beta"), ("caio", "Acme Foods"), ("opedit", ""), ("opread", ""), ("root", "")]
      and [t["name"] for t in everyone["tenants"]] == ["Acme Foods", "Beta"], everyone)
check("a tenant administrator cannot touch another tenant's or the operator's users (unknown to him)",
      all(code(c) == "users.unknown" for c in (ana.put("/portal/api/users/bia", json={"role": "reader"}),
                                               ana.post("/portal/api/users/root/reset", json={}),
                                               ana.delete("/portal/api/users/opedit"))))
r = ana.put("/portal/api/users/caio", json={"email": ""})
check("e-mail removed with an empty value", r.status_code == 200 and users.get("caio")["email"] is None
      and "email" not in store.col("users").find_one({"_id": "caio"}), r.get_json())
check("a tenant administrator cannot demote himself", code(ana.put("/portal/api/users/ana", json={"role": "editor"})) == "users.notSelf")
check("tenant administrators do not count as the last server administrator: root stays",
      code(root.put("/portal/api/users/root", json={"role": "editor"})) == "users.notSelf")
try:
    users.update("root", disabled=True)
    last = None
except users.UserError as exc:
    last = exc.code
check("the last enabled server administrator cannot be disabled while only tenant administrators remain",
      last == "users.lastAdmin")

caio, _ = client("caio", caio_pw)
caio.post("/portal/api/password", json={"currentPassword": caio_pw, "newPassword": "caio-password-long"})

# ------------------------------------------------------------------ records of a tenant
check("a tenant's users reach the tenant's records only; a limited user only his prefixes",
      listed(ana) == sorted([ACME_A, ACME_B, ACME_C]) and listed(bia) == [BETA] and listed(caio) == [ACME_A],
      (listed(ana), listed(bia), listed(caio)))
r = ana.post("/portal/api/record", json=record(ACME_A, url="https://acme.example/a", description="Acme A"))
check("a tenant administrator saves a record of the tenant", r.status_code == 200, r.get_json())
check("another tenant's user cannot open or save it", bia.get(f"/portal/api/record?key=01&value={ACME_A}").status_code == 403
      and bia.post("/portal/api/record", json=record(ACME_A)).status_code == 403)
ev = store.col("journal").find_one({"action": "update", "anchor": f"/01/{ACME_A}", "user": "ana"})
check("journal: the change belongs to the tenant, not marked as the operator's", ev and ev.get("tenant") == acme["id"]
      and "byOperator" not in ev, ev)
rows = {r["value"]: r for r in ana.get("/portal/api/records").get_json()["records"]}
check("record list: who changed a record is shown to the same tenant only (not the operator's earlier change)",
      rows[ACME_A]["updatedBy"] == "ana" and rows[ACME_B]["updatedBy"] is None, rows)
history = ana.get(f"/portal/api/history?key=01&value={ACME_A}").get_json()["versions"]
check("history: only the versions made while the record was the tenant's", [v["user"] for v in history] == ["ana"], history)
check("export of a tenant user: his tenant's records only", b"0789123450001" in ana.post("/portal/api/export", json={"format": "csv"}).data
      and b"0950600013435" not in ana.post("/portal/api/export", json={"format": "csv"}).data
      and b"0789835741001" not in ana.post("/portal/api/export", json={"format": "csv"}).data)


def preview(c, text):
    return c.post("/portal/api/import/preview", json={"filename": "t.csv", "content": base64.b64encode(text.encode()).decode(),
                                                      "labels": {}}).get_json()


def finish(c, token):
    for _ in range(80):
        status = c.get(f"/portal/api/import/status?token={token}").get_json()
        if status.get("state") == "finished":
            return status
        time.sleep(0.1)
    return status


p = preview(bia, f"key;value;description;linkType;url;language\n01;{ACME_C};Taken;gs1:pip;https://x.example/c;en\n")
check("import preview: another tenant's key is an error of its row", p["counts"]["error"] == 1
      and p["errors"][0]["code"] == "access.prefixRow", p)
p = preview(bia, f"key;value;description;linkType;url;language\n01;{BETA};Beta new;gs1:pip;https://beta.example/b;en\n")
check("import preview of the tenant's own key", p["counts"]["update"] == 1, p)
root.put(f"/portal/api/tenants/{beta['id']}", json={"prefixes": []})      # the prefix goes back to the operator
bia.post("/portal/api/import/apply", json={"token": p["token"]})
status = finish(bia, p["token"])
check("the worker checks each record again: a prefix the tenant lost since the preview is not written",
      status["results"][0]["action"] == "failed" and status["results"][0]["code"] == "access.prefix"
      and mock_data_entry.DB[f"01_{BETA}"]["entries"][0]["itemDescription"] == "Item", status)
root.put(f"/portal/api/tenants/{beta['id']}", json={"prefixes": ["7898357"]})

# ------------------------------------------------------------------ prefixes moving between owners
r = root.put(f"/portal/api/tenants/{acme['id']}", json={"prefixes": ["7895678"]})
check("a prefix is not taken from a tenant while one of its users is limited inside it", code(r) == "tenants.prefixInUse"
      and r.get_json()["params"]["users"] == "caio", r.get_json())
opedit.post("/portal/api/record", json=record(LATER, url="https://operator.example/later", description="Operator's"))
r = root.post("/portal/api/tenants", json={"name": "Delta", "prefixes": ["95600001"]})
check("a prefix an operator user is limited to stays refused", code(r) == "tenants.prefixOperatorUser")
root.put("/portal/api/users/opread", json={"prefixes": ["95060001"]})
r = root.post("/portal/api/tenants", json={"name": "Delta", "prefixes": ["9560000"]})
delta = r.get_json()["tenant"]
r = root.post("/portal/api/users", json={"username": "dino", "role": "editor", "tenant": delta["id"]})
dino, _ = client("dino", r.get_json()["password"])
dino.post("/portal/api/password", json={"currentPassword": r.get_json()["password"], "newPassword": "dino-password-long"})
rows = {x["value"]: x for x in dino.get("/portal/api/records").get_json()["records"]}
check("a record moved to a tenant: its new users do not see who changed it under the operator, nor its history",
      list(rows) == [LATER] and rows[LATER]["updatedBy"] is None and rows[LATER]["createdBy"] is None
      and dino.get(f"/portal/api/history?key=01&value={LATER}").get_json()["versions"] == [], rows)
check("its earlier versions stay in the operator's trail",
      any(e["action"] == "update" and e.get("anchor") == f"/01/{LATER}" for e in events(root)))
dino.post("/portal/api/record", json=record(LATER, url="https://delta.example/later", description="Delta's"))
check("record metadata restarted for the new owner", store.col("record_meta").find_one({"_id": LATER})["createdBy"] == "dino"
      and store.col("record_meta").find_one({"_id": LATER})["tenant"] == delta["id"])

# ------------------------------------------------------------------ audit trail per tenant
ana_events = events(ana)
check("a tenant administrator's audit trail: his tenant's events only, including what the operator did to it",
      ana_events and all(e.get("tenant") == acme["id"] for e in ana_events)
      and {"user-create", "update", "login"} <= {e["action"] for e in ana_events}
      and any(e.get("byOperator") and e["user"] == "root" for e in ana_events), ana_events)
check("no other tenant's or the operator's events, nor their user names", not any(e["user"] in ("bia", "dino", "opedit")
                                                                                  for e in ana_events))
root_events = events(root)
check("the server administrator's trail: the operator's events and what operator users did to tenants",
      any(e["action"] == "tenant-create" and e.get("byOperator") for e in root_events)
      and any(e["action"] == "update" and e["user"] == "opedit" for e in root_events)
      and not any(e["user"] in ("ana", "bia", "dino") for e in root_events)
      and any(e.get("tenantName") == "Acme Foods" for e in root_events), root_events)
csv_text = root.get("/portal/api/audit.csv").data.decode("utf-8-sig")
check("audit CSV: organisation and by-operator columns", csv_text.splitlines()[0].endswith(";organisation;by_operator")
      and ";Acme Foods;yes" in csv_text, csv_text[:300])
bad, r = client("ana", "wrong-password-xx")
check("a failed sign-in of a tenant user goes to the tenant's trail",
      store.col("journal").find_one({"action": "login-failed", "user": "ana"})["tenant"] == acme["id"])

# ------------------------------------------------------------------ support access
r = root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "ok"})
check("support access needs a reason of 5 characters or more", code(r) == "support.reason", r.get_json())
r = root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "  Ticket 42:​ wrong   target "})
check("support access opened", r.status_code == 200 and r.get_json()["params"] == {"name": "Acme Foods"}, r.get_json())
cfg = root.get("/portal/api/config").get_json()
check("during support access: reader of the tenant, the account still an administrator",
      cfg["support"]["name"] == "Acme Foods" and cfg["role"] == "reader" and cfg["accountRole"] == "admin", cfg)
check("the server administrator sees the tenant's records, read only",
      listed(root) == sorted([ACME_A, ACME_B, ACME_C])
      and code(root.post("/portal/api/record", json=record(ACME_B))) == "access.role"
      and root.get(f"/portal/api/history?key=01&value={ACME_A}").get_json()["versions"][0]["user"] == "ana")
check("…and the tenant's audit trail", {e["user"] for e in events(root)} >= {"ana", "root"}
      and all(e.get("tenant") == acme["id"] for e in events(root)))
check("…and still manages users", root.get("/portal/api/users").status_code == 200)
opened = store.col("journal").find_one({"action": "support-open"})
check("support access recorded in the tenant's trail, with the reason (invisible characters removed)",
      opened["tenant"] == acme["id"] and opened["byOperator"] is True and opened["detail"] == "Ticket 42: wrong target"
      and any(e["action"] == "support-open" for e in events(ana)), opened)
root.post("/portal/api/support", json={"tenant": delta["id"], "reason": "second ticket"})
check("opening support access to another tenant closes the first",
      store.col("journal").count_documents({"action": "support-close", "tenant": acme["id"]}) == 1
      and listed(root) == [LATER])
r = root.delete("/portal/api/support")
check("support access closed: back to the operator's records", r.status_code == 200 and listed(root) == [OPER]
      and store.col("journal").count_documents({"action": "support-close", "tenant": delta["id"]}) == 1)
root.post("/portal/api/support", json={"tenant": beta["id"], "reason": "third ticket"})
root.post("/portal/api/logout", json={})
check("signing out closes support access in the tenant's trail",
      store.col("journal").find_one({"action": "support-close", "tenant": beta["id"]})["detail"] == "logout")
root, _ = client("root", "root-password-long")

# ------------------------------------------------------------------ disabled and removed tenants
before = bia.get("/portal/api/records").status_code
root.put(f"/portal/api/tenants/{beta['id']}", json={"disabled": True})
check("disabling a tenant ends its users' sessions at the next request",
      before == 200 and bia.get("/portal/api/records").status_code == 401)
bia, r = client("bia", "bia-password-long")
check("a user of a disabled tenant cannot sign in; refusal in the tenant's trail", code(r) == "auth.tenantDisabled"
      and store.col("journal").find_one({"action": "login-refused"})["tenant"] == beta["id"]
      and journal.category("login-refused") == "session", r.get_json())
check("a disabled tenant's records stay out of the operator's reach", listed(root) == [OPER])
root.put(f"/portal/api/tenants/{beta['id']}", json={"disabled": False, "name": "Beta Drinks"})
bia, r = client("bia", "bia-password-long")
check("enabled again: its users sign in; the rename is recorded", r.status_code == 200
      and store.col("journal").find_one({"action": "tenant-update", "detail": {"$regex": "name=Beta Drinks"}}) is not None)
check("a tenant with users cannot be removed", code(root.delete(f"/portal/api/tenants/{beta['id']}")) == "tenants.notEmpty")
root.delete("/portal/api/users/bia")
r = root.delete(f"/portal/api/tenants/{beta['id']}")
check("an empty tenant is removed; its records go back to the operator", r.status_code == 200
      and listed(root) == sorted([OPER, BETA]) and tenants.get(beta["id"]) is None, listed(root))
check("removed tenant: its trail keeps its id; the server administrator sees the removal", any(
      e["action"] == "tenant-remove" and e.get("tenantName") == beta["id"] for e in events(root)))

# ------------------------------------------------------------------ link check results per scope
portal._save_last_full_check(None, {"checkedAt": "2026-10-13T10:00:00Z", "user": "opedit", "urls": 1,
                                    "records": {f"/01/{OPER}|": [{"url": "https://x", "ok": False}]}})
portal._save_last_full_check(acme["id"], {"checkedAt": "2026-10-13T11:00:00Z", "user": "ana", "urls": 2,
                                          "records": {f"/01/{ACME_A}|": [{"url": "https://y", "ok": False}]}})
check("the last check of every record is kept per scope: each sees its own, with its own user's name",
      ana.get("/portal/api/links/last").get_json()["user"] == "ana"
      and list(ana.get("/portal/api/links/last").get_json()["records"]) == [f"/01/{ACME_A}|"]
      and root.get("/portal/api/links/last").get_json()["user"] == "opedit"
      and dino.get("/portal/api/links/last").get_json() == {})

# ------------------------------------------------------------------ ownership rules
ts = [{"id": "a", "prefixes": ["7891234"]}, {"id": "b", "prefixes": ["40"]}]
check("ownership after the indicator, extension or filler digit; other keys from the first digit",
      tenants.owner(f"/01/{ACME_A}", ts) == "a" and tenants.owner("/00/378912340000000018", ts) == "a"
      and tenants.owner("/414/4012345000009", ts) == "b" and tenants.owner(f"/01/{OPER}", ts) is None
      and tenants.owner("/nonsense", ts) is None)
users.set_password("cli", "cli-password-long", role="reader", tenant=acme["id"], email="cli@acme.example")
users.set_password("cli", "cli-password-new!", tenant=delta["id"])
check("command line: a new user created in a tenant; an existing user keeps his", users.get("cli")["tenant"] == acme["id"]
      and users.get("cli")["email"] == "cli@acme.example")
check("tenants.find by name ignoring case, or by id", tenants.find(" ACME foods ")["id"] == acme["id"]
      and tenants.find(delta["id"])["name"] == "Delta" and tenants.find("nobody") is None)

# ------------------------------------------------------------------ messages in both languages
import re  # noqa: E402

STATIC = os.path.join(PORTAL, "static")
catalogue_js = open(os.path.join(STATIC, "i18n.js"), encoding="utf-8").read()
blocks = re.split(r'\n    "(?:pt-BR|en-GB)": \{', catalogue_js)[1:]
pt_keys, en_keys = (set(re.findall(r'^      "([^"]+)":', b, re.M)) for b in blocks[:2])
# the Portuguese names of the GS1 Application Identifiers ("ai.…") exist in pt-BR only: English uses the GS1 Barcode
# Syntax Dictionary's own titles
check("both languages have the same messages", {k for k in pt_keys ^ en_keys if not k.startswith("ai.")} == set(),
      sorted(k for k in pt_keys ^ en_keys if not k.startswith("ai.")))
page_keys = set(re.findall(r'data-i18n="([^"]+)"', open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()))
page_keys |= {k.split(":", 1)[1] for attr in re.findall(r'data-i18n-attr="([^"]+)"',
                                                         open(os.path.join(STATIC, "index.html"), encoding="utf-8").read())
              for k in attr.split(";")}
check("every message of the page is translated", page_keys <= pt_keys, sorted(page_keys - pt_keys))
server_codes = set(re.findall(r'(?:UserError|ValidationError|message)\("((?:tenants|users|support|access|auth)\.[A-Za-z.]+)"',
                              "".join(open(os.path.join(PORTAL, f), encoding="utf-8").read()
                                      for f in ("app.py", "users.py", "tenants.py"))))
check("every message code of the server is translated", server_codes <= pt_keys and len(server_codes) > 25,
      sorted(server_codes - pt_keys))
actions = {"login-refused", "tenant-create", "tenant-update", "tenant-remove", "support-open", "support-close"}
check("every new journal action has a name", {f"audit.action.{a}" for a in actions} <= pt_keys)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
