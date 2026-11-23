"""
Deleting one record without rewriting the key (ADR 0023), through the portal's Flask test client and the stand-in data
entry API: the editor's delete, the tenant API's delete and "fix serial numbers" remove a record with one call, the data
entry API's record-level delete (DELETE with {"removeRecord": true, "qualifiers": [...]}), and never delete the key's
whole document. Before it the portal deleted the document and wrote the other records back, so every code of the key
answered 404 between the two calls, and for good when the second one failed. The checks watch the calls the portal
makes, make the data entry API fail at each step and look at what the key still holds; a key holding a record the API
would now refuse no longer blocks a deletion.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_record_delete.py
"""
import os
import sys
import tempfile
import threading

from flask import jsonify, request
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3405
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_recorddelete_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import tenants  # noqa: E402

CALLS = []          # (method, path, body) of every call the portal makes to the data entry API
FAIL = {}           # {"rule": f(method, body), "status": 409} → the next matching call answers 500 (or that status)


@mock_data_entry.app.before_request
def watch():
    body = request.get_json(silent=True)
    CALLS.append((request.method, request.path, body))
    if request.path.endswith("/validate") and FAIL.pop("refuse", None):
        return jsonify(response_status=200, problems=[{"item": 1, "error": "a rule of a newer API"}])
    rule = FAIL.get("rule")
    if rule and rule(request.method, body):
        FAIL.pop("rule")
        status = FAIL.pop("status", 500)
        return jsonify(response_status=status, error="injected failure"), status
    return None


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


acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
ana, edu = client("ana", "ana-password-long"), client("edu", "edu-password-long")
A, B, C, D, E = (gtin(f"078912345400{i}") for i in range(1, 6))
LINK = [{"linktype": "gs1:pip", "href": "https://acme.example.com/p", "title": "P", "hreflang": ["en"]}]


def put_raw(value, entries):
    mock_data_entry.DB[f"01_{value}"] = {"default": "gs1:pip", "entries": [
        {"qualifiers": q, "itemDescription": d, "links": [dict(l) for l in LINK], "informative": []} for q, d in entries]}


def entries_of(value):
    doc = mock_data_entry.DB.get(f"01_{value}")
    return [] if not doc else [(e["qualifiers"], e.get("informative") or [], e["itemDescription"]) for e in doc["entries"]]


def writes():
    """The calls that changed something (not GET, not POST /validate)."""
    return [(m, p, b) for m, p, b in CALLS if m != "GET" and not p.endswith("/validate")]


def whole_deletes():
    return [c for c in writes() if c[0] == "DELETE" and not (c[2] or {}).get("removeRecord")]


def journal(value):
    """The record events of a key that took effect: an attempt that a change-failed event names is left out (ADR 0026)."""
    found = list(store.col("journal").find({"anchor": f"/01/{value}"}))
    failed = {(e["ref"]["chain"], e["ref"]["seq"]) for e in found if e["action"] == "change-failed"}
    return sorted((e["action"], e.get("qpath") or "") for e in found
                  if e["action"] != "change-failed" and (e.get("chain"), e.get("seq")) not in failed)


# ================================================================== the editor's delete
put_raw(A, [([], "Coffee"), ([{"10": "L1"}], "Batch L1"), ([{"10": "L2"}], "Batch L2")])
CALLS.clear()
r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L1", headers=ORIGIN)
check("the editor deletes a batch record: 200 delete.done", r.status_code == 200 and code(r) == "delete.done", r.get_json())
check("…with one call to the data entry API, the record-level delete with the batch's qualifiers",
      writes() == [("DELETE", f"/api/01/{A}", {"removeRecord": True, "qualifiers": [{"10": "L1"}]})], writes())
check("…the key's document never deleted (no window in which its other records answer 404)", not whole_deletes(), writes())
check("…the key's other records kept as they were", entries_of(A) == [([], [], "Coffee"), ([{"10": "L2"}], [], "Batch L2")],
      entries_of(A))
check("…in the journal, with the record as it was", ("delete", "/10/L2") not in journal(A)
      and store.col("journal").find_one({"anchor": f"/01/{A}", "action": "delete", "qpath": "/10/L1"}) is not None,
      journal(A))

CALLS.clear()
FAIL["rule"] = lambda method, body: method == "DELETE"
r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L2", headers=ORIGIN)
check("the data entry API fails the delete: 502 upstream.deleteFailed", r.status_code == 502
      and code(r) == "upstream.deleteFailed", (r.status_code, r.get_json()))
check("…every record of the key still there (the failure cannot leave the key empty)",
      entries_of(A) == [([], [], "Coffee"), ([{"10": "L2"}], [], "Batch L2")], entries_of(A))
check("…nothing journalled as deleted", ("delete", "/10/L2") not in journal(A), journal(A))
check("…the attempt journalled first, then change-failed naming it (ADR 0026)", store.col("journal").find_one(
      {"anchor": f"/01/{A}", "action": "change-failed", "detail": "delete upstream.deleteFailed"}) is not None)

r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L9", headers=ORIGIN)
check("a batch the key has no record of: 404 record.notFound, nothing written", code(r) == "record.notFound"
      and len(entries_of(A)) == 2, (r.status_code, r.get_json()))

CALLS.clear()
r = edu.delete(f"/portal/api/record?key=01&value={A}", headers=ORIGIN)
check("the key's own record deleted while a batch has one: the batch kept", r.status_code == 200
      and entries_of(A) == [([{"10": "L2"}], [], "Batch L2")] and not whole_deletes(), (entries_of(A), writes()))
r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L2", headers=ORIGIN)
check("the last record deleted: the key's document goes with it", r.status_code == 200
      and f"01_{A}" not in mock_data_entry.DB, mock_data_entry.DB.get(f"01_{A}"))

# A record the data entry API would now refuse (made before rule 2, or by another tool) no longer blocks a deletion:
# nothing is written back, so nothing is checked
put_raw(B, [([], "Tea"), ([{"10": "L9"}, {"21": "S9"}], "Unit S9"), ([{"10": "L5"}], "Batch L5")])
r = edu.delete(f"/portal/api/record?key=01&value={B}&qualifiers=/10/L5", headers=ORIGIN)
check("a key holding a record the API would refuse: the batch deleted, that record untouched", r.status_code == 200
      and entries_of(B) == [([], [], "Tea"), ([{"10": "L9"}, {"21": "S9"}], [], "Unit S9")], (r.get_json(), entries_of(B)))

# ================================================================== the tenant API's delete
r = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"], "days": 30},
             headers=ORIGIN)
KEY = (r.get_json() or {}).get("key", "")
put_raw(C, [([], "Juice"), ([{"10": "J1"}], "Batch J1")])
CALLS.clear()
r = portal.app.test_client().delete(f"/portal/api/v1/records/01/{C}?qualifiers=/10/J1",
                                    headers={"Authorization": f"Bearer {KEY}"})
check("the tenant API deletes a batch: 200, one record-level delete, the product's record kept", r.status_code == 200
      and entries_of(C) == [([], [], "Juice")] and not whole_deletes() and len(writes()) == 1, (r.get_json(), writes()))
FAIL["rule"] = lambda method, body: method == "DELETE"
r = portal.app.test_client().delete(f"/portal/api/v1/records/01/{C}", headers={"Authorization": f"Bearer {KEY}"})
check("…a failed delete through the tenant API: 502, the record kept", r.status_code == 502
      and entries_of(C) == [([], [], "Juice")], (r.status_code, r.get_json()))

# ================================================================== fixing serial numbers (rule 2)
put_raw(D, [([], "Milk"), ([{"10": "M1"}, {"21": "S1"}], "Unit S1"), ([{"22": "V1"}, {"21": "S2"}], "Unit S2")])
CALLS.clear()
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": D}, headers=ORIGIN)
check("fixing two serial numbers: both fixed", code(r) == "rules.fixed" and r.get_json()["params"]["fixed"] == 2, r.get_json())
check("…the serial number written alone first, then the old record removed, one record at a time",
      [(m, (b or {}).get("qualifiers")) for m, _, b in writes()]
      == [("POST", [{"21": "S1"}]), ("DELETE", [{"10": "M1"}, {"21": "S1"}]),
          ("POST", [{"21": "S2"}]), ("DELETE", [{"22": "V1"}, {"21": "S2"}])], writes())
check("…the key's document never deleted", not whole_deletes(), writes())
check("…the records as the rule wants them, the product's kept", entries_of(D) == [
    ([], [], "Milk"), ([{"21": "S1"}], [{"10": "M1"}], "Unit S1"), ([{"21": "S2"}], [{"22": "V1"}], "Unit S2")],
    entries_of(D))

put_raw(E, [([], "Water"), ([{"10": "W1"}, {"21": "S7"}], "Unit S7")])
FAIL["rule"] = lambda method, body: method == "DELETE" and (body or {}).get("removeRecord")
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": E}, headers=ORIGIN)
check("the old record's removal fails: 502, the serial number answers by both records (never by none)",
      r.status_code == 502 and entries_of(E) == [([], [], "Water"), ([{"10": "W1"}, {"21": "S7"}], [], "Unit S7"),
                                                 ([{"21": "S7"}], [{"10": "W1"}], "Unit S7")], (r.get_json(), entries_of(E)))
check("…what was done is in the journal (the new record created)", ("create", "/21/S7") in journal(E)
      and ("delete", "/10/W1/21/S7") not in journal(E), journal(E))
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": E}, headers=ORIGIN)
check("…a second run finishes it: the old record, now a repeat, removed", code(r) == "rules.fixed"
      and entries_of(E) == [([], [], "Water"), ([{"21": "S7"}], [{"10": "W1"}], "Unit S7")], (r.get_json(), entries_of(E)))

put_raw(E, [([], "Water"), ([{"10": "W2"}, {"21": "S8"}], "Unit S8")])
FAIL["rule"] = lambda method, body: method == "POST" and isinstance(body, dict)   # POST /new, not /validate
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": E}, headers=ORIGIN)
check("writing the serial number alone fails: 502, the old record kept, nothing else written",
      r.status_code == 502 and entries_of(E) == [([], [], "Water"), ([{"10": "W2"}, {"21": "S8"}], [], "Unit S8")],
      (r.get_json(), entries_of(E)))

put_raw(E, [([], "Water"), ([{"10": "W3"}, {"21": "S9"}], "Unit S9")])
FAIL["refuse"] = True
CALLS.clear()
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": E}, headers=ORIGIN)
check("a fixed record the data entry API would refuse: reported (record.rewriteRefused), nothing written",
      [x["code"] for x in r.get_json().get("refused", [])] == ["record.rewriteRefused"] and not writes()
      and entries_of(E) == [([], [], "Water"), ([{"10": "W3"}, {"21": "S9"}], [], "Unit S9")], (r.get_json(), writes()))

# ================================================================== a key changing under other writers (F-009, ADR 0027)
# The data entry API answers 409 when the key's document kept changing under other writers while it tried to write it
# (nothing written). The portal answers 409 upstream.conflict (not 502 as for a refusal), and the journal names the
# attempt as failed: the user opens the record again and repeats the change.
SAVE = {"key": "01", "value": A, "description": "Coffee", "links": [
    {"linkType": "gs1:pip", "url": "https://acme.example.com/new", "hreflang": ["en"], "title": "P"}]}
attempts = [
    ("the editor's save of a new record", "POST", lambda: edu.post("/portal/api/record", json={**SAVE, "qualifiers": "/10/N1"},
                                                                  headers=ORIGIN)),
    ("the editor's save of an existing record", "PUT", lambda: edu.post("/portal/api/record", json=SAVE, headers=ORIGIN)),
    ("the editor's delete", "DELETE", lambda: edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L1",
                                                         headers=ORIGIN)),
    ("the tenant API's save", "PUT", lambda: portal.app.test_client().put(
        f"/portal/api/v1/records/01/{A}", headers={"Authorization": f"Bearer {KEY}"},
        json={"description": "Coffee", "links": SAVE["links"]})),
    ("the tenant API's delete", "DELETE", lambda: portal.app.test_client().delete(
        f"/portal/api/v1/records/01/{A}?qualifiers=/10/L1", headers={"Authorization": f"Bearer {KEY}"})),
]
for name, method, attempt in attempts:
    put_raw(A, [([], "Coffee"), ([{"10": "L1"}], "Batch L1")])
    before, events = entries_of(A), journal(A)
    FAIL["rule"], FAIL["status"] = (lambda m: lambda method, body: method == m and isinstance(body, dict)
                                    and not (body.get("links") and not body.get("anchor")))(method), 409
    r = attempt()
    FAIL.pop("rule", None), FAIL.pop("status", None)
    check(f"{name}, the key changing under other writers: 409 upstream.conflict", r.status_code == 409
          and code(r) == "upstream.conflict", (r.status_code, r.get_json()))
    check(f"…the key's records as they were, the attempt journalled as failed", entries_of(A) == before
          and journal(A) == events, (entries_of(A), journal(A)))
put_raw(D, [([], "Milk"), ([{"10": "M9"}, {"21": "S5"}], "Unit S5")])
FAIL["rule"], FAIL["status"] = (lambda method, body: method == "POST" and isinstance(body, dict)), 409
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": D}, headers=ORIGIN)
FAIL.pop("rule", None), FAIL.pop("status", None)
check("fixing serial numbers while the key changes under other writers: 409 upstream.conflict, the old record kept",
      r.status_code == 409 and code(r) == "upstream.conflict"
      and entries_of(D) == [([], [], "Milk"), ([{"10": "M9"}, {"21": "S5"}], [], "Unit S5")], (r.get_json(), entries_of(D)))

# ================================================================== the data entry API's own answers (the stand-in)
mock = mock_data_entry.app.test_client()
AUTH = {"Authorization": "Bearer tok"}
put_raw(A, [([], "Coffee"), ([{"10": "L1"}], "Batch L1")])
for body in ({"removeRecord": False, "qualifiers": []}, {"removeRecord": True, "qualifiers": [{"10": "L1"}], "links": [LINK[0]]},
             {"removeRecord": True, "qualifiers": {"10": "L1"}}, {"removeRecord": True, "qualifiers": [{"10": 5}]}):
    r = mock.delete(f"/api/01/{A}", json=body, headers=AUTH)
    check(f"the stand-in refuses a malformed record delete ({str(body)[:50]}): 400, nothing removed",
          r.status_code == 400 and len(entries_of(A)) == 2, (r.status_code, entries_of(A)))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
