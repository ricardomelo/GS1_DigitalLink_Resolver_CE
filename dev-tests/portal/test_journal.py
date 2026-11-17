"""
The journal's integrity in the portal (Documentation/adr/0026-journal-integrity.md), through the Flask test client and
the stand-in data entry API: a record change is journalled before the data entry API is called and refused (503
journal.unavailable, nothing changed) when its event cannot be written; a change the API then refuses adds
change-failed naming the attempt, which the record's history leaves out; the records the portal turns to explicit
default links are journalled; events written before the upgrade are sealed at start-up; administrators verify the
chains of their audit trail and check a receipt; the worker's housekeeping runs the daily checkpoint. The chains
themselves (sealing, every kind of tampering, racing writers, keys) are checked in test_store.py, also against a real
MongoDB.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_journal.py
"""
import os
import sys
import tempfile
import threading

from flask import g, request
from pymongo.errors import PyMongoError
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3406
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_JOURNAL_KEY="journal-test-key")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_journal_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
# An event as an earlier version wrote it, without a seal: the portal seals it when it starts
store.col("journal").insert_one({"at": store.parse_iso("2026-01-05T10:00:00Z"), "user": "old", "action": "user-create",
                                 "category": "admin", "detail": "before the upgrade"})
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import journal  # noqa: E402
import tenants  # noqa: E402

ORDER = []          # ("journal", action) and ("api", method) in the order they happen
FAIL = {}


@mock_data_entry.app.before_request
def watch():
    if request.method != "GET" and not request.path.endswith("/validate"):
        ORDER.append(("api", request.method))
    rule = FAIL.get("rule")
    if rule and rule(request.method, request.get_json(silent=True)):
        FAIL.pop("rule")
        return {"response_status": 500, "error": "injected failure"}, 500
    return None


real_append = journal.append


def watched_append(action, user, **fields):
    if FAIL.get("journal"):
        raise PyMongoError("injected: the portal's database refuses the write")
    ORDER.append(("journal", action))
    return real_append(action, user, **fields)


journal.append = watched_append
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


def record(value, qualifiers=None, url="https://acme.example.com/p"):
    return {"key": "01", "value": value, "qualifiers": qualifiers or {}, "description": "Coffee",
            "defaultLinkType": "gs1:pip", "links": [{"linkType": "gs1:pip", "url": url, "title": "", "hreflang": ["en"]}]}


def events(value, action=None):
    query = {"anchor": f"/01/{value}"}
    if action:
        query["action"] = action
    return list(store.col("journal").find(query).sort([("chain", 1), ("seq", 1)]))


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bob", "bob-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bob = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bob"))
A, B, C = (gtin(f"078912345500{i}") for i in range(1, 4))

# ================================================================== sealed at start-up
old = store.col("journal").find_one({"detail": "before the upgrade"})
check("an event written before the upgrade is sealed when the portal starts, marked so",
      old.get("sealed") == "upgrade" and old.get("chain") == "operator/admin" and old.get("seq") == 1
      and journal.content_hash(old) == old["hash"], old)
check("start-up housekeeping includes the daily checkpoint of the chains", journal.checkpoint in portal.HOUSEKEEPING)

# ================================================================== journalled first
ORDER.clear()
r = edu.post("/portal/api/record", json=record(A), headers=ORIGIN)
check("a record created: 201", r.status_code == 201, r.get_json())
check("…its event written before the data entry API is called", ORDER[:2] == [("journal", "create"), ("api", "POST")], ORDER)
created = events(A, "create")
check("…sealed in the organisation's record chain, with the record's content",
      len(created) == 1 and created[0]["chain"] == f'{acme["id"]}/record' and created[0]["doc"]["itemDescription"] == "Coffee",
      created)

ORDER.clear()
r = edu.post("/portal/api/record", json=record(A, url="https://acme.example.com/q"), headers=ORIGIN)
check("a record updated: event first, then the API", r.status_code == 200
      and ORDER[:2] == [("journal", "update"), ("api", "PUT")], (r.status_code, ORDER))

FAIL["journal"] = True
ORDER.clear()
r = edu.post("/portal/api/record", json=record(B), headers=ORIGIN)
check("the journal cannot be written: 503 journal.unavailable", r.status_code == 503 and code(r) == "journal.unavailable",
      (r.status_code, r.get_json()))
check("…the data entry API never called, the record not created",
      ("api", "POST") not in ORDER and f"01_{B}" not in mock_data_entry.DB, ORDER)
r = edu.post("/portal/api/record", json=record(A, url="https://acme.example.com/never"), headers=ORIGIN)
check("…an update refused the same way, the record unchanged", r.status_code == 503
      and "never" not in str(mock_data_entry.DB.get(f"01_{A}")), mock_data_entry.DB.get(f"01_{A}"))
r = edu.delete(f"/portal/api/record?key=01&value={A}", headers=ORIGIN)
check("…a delete refused the same way, the record kept", r.status_code == 503 and f"01_{A}" in mock_data_entry.DB)
key = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"], "days": 30},
               headers=ORIGIN).get_json()
FAIL["journal"] = True
r = portal.app.test_client().put(f"/portal/api/v1/records/01/{B}", headers={"Authorization": f'Bearer {key["key"]}'},
                                 json={"description": "Tea", "links": [{"linkType": "gs1:pip", "url": "https://acme.example.com/t",
                                                                      "hreflang": ["en"]}]})
check("…the tenant API refused the same way (503 journal.unavailable), nothing created",
      r.status_code == 503 and code(r) == "journal.unavailable" and f"01_{B}" not in mock_data_entry.DB,
      (r.status_code, r.get_json()))
FAIL.pop("journal")

# ================================================================== a change the API refuses
FAIL["rule"] = lambda method, body: method == "POST"
r = edu.post("/portal/api/record", json=record(A, {"10": "L1"}), headers=ORIGIN)
check("the data entry API refuses a create: 502", r.status_code == 502, (r.status_code, r.get_json()))
attempt = events(A, "create")[-1]
failed = events(A, journal.FAILED_ACTION)
check("…change-failed names the attempt (chain and sequence number) and the message code",
      len(failed) == 1 and failed[0]["ref"] == {"chain": attempt["chain"], "seq": attempt["seq"]}
      and failed[0]["detail"] == "create upstream.createRejected" and failed[0]["qpath"] == "/10/L1", failed)
history = edu.get(f"/portal/api/history?key=01&value={A}&qualifiers=/10/L1").get_json()["versions"]
check("…the record's history leaves the failed attempt out", history == [], history)
r = edu.post("/portal/api/record", json=record(A, {"10": "L1"}), headers=ORIGIN)
history = edu.get(f"/portal/api/history?key=01&value={A}&qualifiers=/10/L1").get_json()["versions"]
check("…a second, successful attempt is the history's only version", r.status_code == 201 and len(history) == 1, history)
audit = ana.get("/portal/api/audit").get_json()["events"]
check("…the audit trail shows the attempt and its failure", sum(e["action"] == journal.FAILED_ACTION for e in audit) == 1
      and sum(e["action"] == "create" and e.get("qpath") == "/10/L1" for e in audit) == 2)

FAIL["rule"] = lambda method, body: method == "DELETE" and "links" in (body or {})
r = edu.post("/portal/api/record", json={**record(A, {"10": "L1"}), "links": [
    {"linkType": "gs1:pip", "url": "https://acme.example.com/p", "title": "", "hreflang": ["pt"]}]}, headers=ORIGIN)
check("an update stopped half way (the links' removal refused): 502 and change-failed upstream.partialUpdate",
      r.status_code == 502 and events(A, journal.FAILED_ACTION)[-1]["detail"] == "update upstream.partialUpdate",
      (r.status_code, [e["detail"] for e in events(A, journal.FAILED_ACTION)]))

FAIL["rule"] = lambda method, body: method == "DELETE"
r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L1", headers=ORIGIN)
check("a delete the API refuses: change-failed upstream.deleteFailed",
      r.status_code == 502 and events(A, journal.FAILED_ACTION)[-1]["detail"] == "delete upstream.deleteFailed")

# ================================================================== records turned to explicit default links
mock_data_entry.DB[f"01_{C}"] = {"default": "gs1:pip", "entries": [
    {"qualifiers": q, "itemDescription": d, "links": [{"linktype": "gs1:pip", "href": "https://acme.example.com/p",
                                                       "title": "P", "hreflang": ["en"]}], "informative": []}
    for q, d in (([], "Milk"), ([{"10": "M1"}], "Batch M1"))]}
entries, _ = portal.read_entries(f"/01/{C}")
with portal.app.test_request_context():
    g.user, g.tenant, g.tenants = "edu", acme["id"], tenants.load()
    portal.turn_to_explicit_defaults(f"/01/{C}", entries, "gs1:pip")
turned = events(C, "update")
check("records turned to explicit default links are journalled, one update each with its new content",
      sorted(e["qpath"] or "" for e in turned) == ["", "/10/M1"]
      and all(e["doc"]["defaultLinktype"] == portal.gs1.LANDING_TYPE for e in turned), [e.get("qpath") for e in turned])

# ================================================================== verification
r = edu.get("/portal/api/audit/verify")
check("verification: administrators only (an editor: 403)", r.status_code == 403, r.status_code)
mine = ana.get("/portal/api/audit/verify").get_json()
names = [c["chain"] for c in mine["chains"]]
check("an organisation's administrator verifies the chains of its own trail, all ok, keyed",
      names and all(n.startswith(acme["id"] + "/") for n in names) and all(c["ok"] for c in mine["chains"])
      and mine["keyed"] is True and mine["chains"][0]["tenantName"] == "Acme Foods", mine)
everything = root.get("/portal/api/audit/verify").get_json()
check("a server administrator verifies every chain (the operator's and each organisation's)",
      {"operator/admin", f'{acme["id"]}/record'} <= {c["chain"] for c in everything["chains"]}, everything)
record_chain = next(c for c in mine["chains"] if c["chain"].endswith("/record"))
r = ana.get("/portal/api/audit/verify", query_string={"receipt": record_chain["head"]})
check("a receipt kept earlier: found in the chain", r.status_code == 200
      and next(c for c in r.get_json()["chains"] if c["chain"] == record_chain["chain"])["receipt"] is True, r.get_json())
bob_head = next(c for c in everything["chains"] if c["chain"].startswith("operator/"))["head"]
r = ana.get("/portal/api/audit/verify", query_string={"receipt": bob_head})
check("a receipt of a chain outside the trail: 422 journal.badReceipt", r.status_code == 422
      and code(r) == "journal.badReceipt", (r.status_code, r.get_json()))
r = ana.get("/portal/api/audit/verify", query_string={"receipt": "not a receipt"})
check("text that is not a receipt: 422 journal.badReceipt", r.status_code == 422 and code(r) == "journal.badReceipt")
target = events(A, "create")[0]
store.col("journal").update_one({"_id": target["_id"]}, {"$set": {"user": "someone else"}})
broken = next(c for c in ana.get("/portal/api/audit/verify").get_json()["chains"] if c["chain"] == target["chain"])
check("an event changed in the database: its chain reported broken at that event",
      broken["ok"] is False and broken["problem"] == {"kind": "hash", "seq": target["seq"]}, broken)
other = bob.get("/portal/api/audit/verify").get_json()
check("…another organisation's verification does not see it", all(c["ok"] for c in other["chains"])
      and all(c["chain"].startswith(beta["id"] + "/") for c in other["chains"]), other)

# start-up where the portal's user may only insert into the journal (ADR 0026 section 2.5.2)
from pymongo.errors import OperationFailure  # noqa: E402

calls, saved_steps = [], (journal.apply_retention, journal.seal_unsealed)


def refused(code_number):
    def step():
        calls.append(code_number)
        raise OperationFailure("not authorized", code=code_number)
    step.__name__ = "refused"
    return step


journal.apply_retention, journal.seal_unsealed = refused(13), refused(13)
try:
    portal._journal_upkeep()
    check("start-up: retention and sealing refused to the portal's user (code 13) are left to portal-db-init, "
          "and both are tried", calls == [13, 13])
    journal.apply_retention = refused(2)
    try:
        portal._journal_upkeep()
        check("start-up: any other database error is not hidden", False)
    except OperationFailure:
        check("start-up: any other database error is not hidden", True)
finally:
    journal.apply_retention, journal.seal_unsealed = saved_steps

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
