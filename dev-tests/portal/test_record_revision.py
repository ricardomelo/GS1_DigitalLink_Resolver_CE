"""
A record's revision from the read to the save (ADR 0058, the first residual of finding F-009), through the portal's
Flask test client and the stand-in data entry API: the editor's read (GET /portal/api/record) and the tenant API's
read give the record's revision (`revision`, ETag); a save or a delete that sends it back as If-Match is made only
while the record is still the one read, and refused with 412 record.changed (nothing written, nothing journalled as
done) when someone else saved or deleted it in between; If-None-Match: * creates only; the headers are checked by the
portal on its own read first and passed to the data entry API with the record's first write (the DELETE of links
that follows a PUT holds to the revision the PUT answered); a save without the headers behaves as before.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_record_revision.py
"""
import importlib.util
import os
import sys
import tempfile
import threading

from flask import jsonify, request
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
REPO = os.path.join(HERE, "..", "..")
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3433
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_recordrevision_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import revision  # noqa: E402
import tenants  # noqa: E402

CALLS = []          # (method, path, body, If-Match, If-None-Match) of every call the portal makes to the data entry API
BEFORE = {}         # {"write": f()} → run once just before the next write reaches the stand-in (another user's save)


@mock_data_entry.app.before_request
def watch():
    body = request.get_json(silent=True)
    CALLS.append((request.method, request.path, body, request.headers.get("If-Match"),
                  request.headers.get("If-None-Match")))
    if request.method != "GET" and not request.path.endswith("/validate") and BEFORE.get("write"):
        BEFORE.pop("write")()
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
users.create("eva", "eva-password-long", "editor", tenant=acme["id"], must_change=False)
ana, edu, eva = (client(n, f"{n}-password-long") for n in ("ana", "edu", "eva"))
A, B, C, D, E = (gtin(f"078912345500{i}") for i in range(1, 6))
LINK = {"linktype": "gs1:pip", "href": "https://acme.example.com/p", "title": "P", "hreflang": ["en"]}


def put_raw(value, entries):
    mock_data_entry.DB[f"01_{value}"] = {"default": "gs1:pip", "entries": [
        {"qualifiers": q, "itemDescription": d, "links": [dict(l) for l in links], "informative": []}
        for q, d, links in entries]}


def entries_of(value):
    doc = mock_data_entry.DB.get(f"01_{value}")
    return [] if not doc else [(e["qualifiers"], e["itemDescription"], sorted(l["href"] for l in e["links"]))
                               for e in doc["entries"]]


def writes():
    return [c for c in CALLS if c[0] != "GET" and not c[1].endswith("/validate")]


def done_events(value):
    """The record events of a key that took effect (an attempt named by a change-failed event left out, ADR 0026)."""
    found = list(store.col("journal").find({"anchor": f"/01/{value}"}))
    failed = {(e["ref"]["chain"], e["ref"]["seq"]) for e in found if e["action"] == "change-failed"}
    return sorted((e["action"], e.get("qpath") or "") for e in found
                  if e["action"] != "change-failed" and (e.get("chain"), e.get("seq")) not in failed)


def failed_events(value):
    return len(list(store.col("journal").find({"anchor": f"/01/{value}", "action": "change-failed"})))


def save_body(value, description, hrefs, qualifiers=""):
    return {"key": "01", "value": value, "qualifiers": qualifiers, "description": description,
            "links": [{"linkType": t, "url": h, "hreflang": ["en"], "title": "P"}
                      for t, h in zip(("gs1:pip", "gs1:epil", "gs1:faqs"), hrefs)]}


def if_match(value):
    return {**ORIGIN, "If-Match": f'"{value}"'}


# ================================================================== the two functions and the stand-in agree
spec = importlib.util.spec_from_file_location("data_entry_revision",
                                              os.path.join(REPO, "data_entry_server", "src", "revision.py"))
data_entry_revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data_entry_revision)
SAMPLES = [None, {"anchor": "/01/1", "itemDescription": "Coffee", "defaultLinktype": "gs1:pip", "links": [LINK]},
           {"anchor": "/01/1", "itemDescription": "Café ☕", "defaultLinktype": "gs1:pip", "links": [LINK],
            "qualifiers": [{"10": "L1"}], "informativeQualifiers": [{"22": "V"}]},
           {"itemDescription": "", "links": []}]
check("the portal's revision.py and the data entry API's give the same revision for every record",
      [revision.of(e) for e in SAMPLES] == [data_entry_revision.of(e) for e in SAMPLES], SAMPLES)
check("…and the stand-in data entry API too", [revision.of(e) for e in SAMPLES] == [mock_data_entry.rev(e) for e in SAMPLES])
with open(os.path.join(PORTAL, "revision.py"), encoding="utf-8") as fh:
    portal_code = fh.read().split('"""', 2)[2]
with open(os.path.join(REPO, "data_entry_server", "src", "revision.py"), encoding="utf-8") as fh:
    data_entry_code = fh.read().split('"""', 2)[2]
check("…the two files are the same code (only their first comment differs)", portal_code == data_entry_code)

# ================================================================== the editor
put_raw(A, [([], "Coffee", [LINK]), ([{"10": "L1"}], "Batch L1", [LINK])])
r = edu.get(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L1")
first = r.get_json().get("revision")
check("the editor's read gives the record's revision in the body and as its ETag",
      r.status_code == 200 and first and r.headers.get("ETag") == f'"{first}"'
      and first == mock_data_entry.rev(mock_data_entry.entry_of(f"01_{A}", [{"10": "L1"}])), (r.headers, first))
r = edu.get(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L9")
check("…a record that does not exist: revision null, no ETag", r.status_code == 200
      and r.get_json().get("revision") is None and "ETag" not in r.headers, (r.get_json().get("revision"), r.headers))
r = edu.get(f"/portal/api/record?key=01&value={A}")
check("…each record of a key has its own revision", r.get_json().get("revision") not in (None, first))

# Eva opens the batch and saves it; Edu, who opened it before, saves his own change
r = eva.post("/portal/api/record", json=save_body(A, "Batch L1", ["https://acme.example.com/p", "https://acme.example.com/eva"],
                                                   "/10/L1"), headers=if_match(first))
second = (r.get_json() or {}).get("revision")
check("a save with If-Match of the record as read: 200, written, the new revision answered (body and ETag)",
      r.status_code == 200 and second and second != first and r.headers.get("ETag") == f'"{second}"'
      and entries_of(A)[1][2] == ["https://acme.example.com/eva", "https://acme.example.com/p"], (r.get_json(), r.headers))
check("…the If-Match passed on to the data entry API with the write",
      [c[3] for c in writes()][-1:] == [f'"{first}"'], writes()[-2:])
CALLS.clear()
events = done_events(A)
r = edu.post("/portal/api/record", json=save_body(A, "Batch one", ["https://acme.example.com/edu"], "/10/L1"),
             headers=if_match(first))
check("a save from a record opened before someone else's save: 412 record.changed", r.status_code == 412
      and code(r) == "record.changed", (r.status_code, r.get_json()))
check("…nothing written (Eva's links kept, the description unchanged), no write sent to the data entry API",
      entries_of(A)[1] == ([{"10": "L1"}], "Batch L1", ["https://acme.example.com/eva", "https://acme.example.com/p"])
      and not writes(), (entries_of(A), writes()))
check("…nothing journalled", done_events(A) == events and failed_events(A) == 0, done_events(A))

# the save that removes links: PUT then DELETE, the DELETE holding to the revision the PUT answered
CALLS.clear()
r = edu.post("/portal/api/record", json=save_body(A, "Batch L1", ["https://acme.example.com/edu"], "/10/L1"),
             headers=if_match(second))
third = (r.get_json() or {}).get("revision")
methods = [(c[0], c[3]) for c in writes()]
check("a save that removes links with If-Match: 200, the PUT carries the revision read, the DELETE the one the PUT "
      "answered", r.status_code == 200 and len(methods) == 2 and methods[0] == ("PUT", f'"{second}"')
      and methods[1][0] == "DELETE" and methods[1][1] not in (None, f'"{second}"'), (r.get_json(), methods))
check("…the record as saved, its final revision answered", entries_of(A)[1][2] == ["https://acme.example.com/edu"]
      and third == mock_data_entry.rev(mock_data_entry.entry_of(f"01_{A}", [{"10": "L1"}])), (entries_of(A), third))

# someone saves between the portal's own check and its write: the data entry API refuses (412), journalled as failed
BEFORE["write"] = lambda: mock_data_entry.DB[f"01_{A}"]["entries"][1].update(itemDescription="Theirs")
r = edu.post("/portal/api/record", json=save_body(A, "Mine", ["https://acme.example.com/edu"], "/10/L1"),
             headers=if_match(third))
check("someone else saves between the portal's check and its write: the data entry API's 412 → 412 record.changed",
      r.status_code == 412 and code(r) == "record.changed", (r.status_code, r.get_json()))
check("…their change kept, the attempt journalled as failed", entries_of(A)[1][1] == "Theirs" and failed_events(A) == 1,
      (entries_of(A), failed_events(A)))

# a new record: If-None-Match: * creates only
r = edu.post("/portal/api/record", json=save_body(A, "Batch L2", ["https://acme.example.com/l2"], "/10/L2"),
             headers={**ORIGIN, "If-None-Match": "*"})
check("a new record saved with If-None-Match: *: 201, its revision answered", r.status_code == 201
      and (r.get_json() or {}).get("revision") == mock_data_entry.rev(mock_data_entry.entry_of(f"01_{A}", [{"10": "L2"}])),
      (r.status_code, r.get_json()))
CALLS.clear()
r = eva.post("/portal/api/record", json=save_body(A, "Eva's L2", ["https://acme.example.com/eva2"], "/10/L2"),
             headers={**ORIGIN, "If-None-Match": "*"})
check("…a second user who opened it while it did not exist: 412 record.changed, the first user's record kept",
      r.status_code == 412 and code(r) == "record.changed" and not writes()
      and entries_of(A)[2] == ([{"10": "L2"}], "Batch L2", ["https://acme.example.com/l2"]), (r.get_json(), entries_of(A)))

CALLS.clear()
BEFORE["write"] = lambda: mock_data_entry.DB[f"01_{A}"]["entries"].append(
    {"qualifiers": [{"10": "L3"}], "itemDescription": "Theirs L3", "links": [dict(LINK)], "informative": []})
r = edu.post("/portal/api/record", json=save_body(A, "Mine L3", ["https://acme.example.com/l3"], "/10/L3"),
             headers={**ORIGIN, "If-None-Match": "*"})
check("…a new record someone creates between the portal's check and its write: If-None-Match passed on with POST /new, "
      "412 record.changed, theirs kept", r.status_code == 412 and code(r) == "record.changed"
      and [(c[0], c[4]) for c in writes()] == [("POST", "*")] and entries_of(A)[3][1] == "Theirs L3",
      (r.status_code, writes(), entries_of(A)))

# the key's own record created with the save is not written when the save is out of date
put_raw(B, [([{"10": "K1"}], "Batch K1", [LINK])])
stale = edu.get(f"/portal/api/record?key=01&value={B}&qualifiers=/10/K1").get_json()["revision"]
mock_data_entry.DB[f"01_{B}"]["entries"][0]["itemDescription"] = "Changed"
CALLS.clear()
r = edu.post("/portal/api/record", json={**save_body(B, "Batch K1", ["https://acme.example.com/k"], "/10/K1"),
                                         "keyRecord": {"mode": "copy", "description": "Key"}}, headers=if_match(stale))
check("a save out of date that would also create the key's own record: 412, the key's record not written",
      r.status_code == 412 and not writes() and len(entries_of(B)) == 1, (r.get_json(), entries_of(B), writes()))

# the delete
put_raw(C, [([], "Juice", [LINK]), ([{"10": "J1"}], "Batch J1", [LINK])])
read = edu.get(f"/portal/api/record?key=01&value={C}&qualifiers=/10/J1").get_json()["revision"]
mock_data_entry.DB[f"01_{C}"]["entries"][1]["links"].append(dict(LINK, linktype="gs1:epil", href="https://acme.example.com/l"))
CALLS.clear()
r = edu.delete(f"/portal/api/record?key=01&value={C}&qualifiers=/10/J1", headers=if_match(read))
check("a delete from a record opened before someone else's save: 412 record.changed, the record kept",
      r.status_code == 412 and code(r) == "record.changed" and len(entries_of(C)) == 2 and not writes(),
      (r.get_json(), entries_of(C)))
read = edu.get(f"/portal/api/record?key=01&value={C}&qualifiers=/10/J1").get_json()["revision"]
r = edu.delete(f"/portal/api/record?key=01&value={C}&qualifiers=/10/J1", headers=if_match(read))
check("…with the revision as read: deleted, the If-Match passed on to the data entry API", r.status_code == 200
      and len(entries_of(C)) == 1 and writes()[-1][0] == "DELETE" and writes()[-1][3] == f'"{read}"',
      (r.get_json(), writes()[-1:]))
r = eva.delete(f"/portal/api/record?key=01&value={C}&qualifiers=/10/J1", headers=if_match(read))
check("…a second user deleting the record already deleted: 412 record.changed (not 404)", r.status_code == 412
      and code(r) == "record.changed", (r.status_code, r.get_json()))

# without the headers: as before
put_raw(D, [([], "Milk", [LINK])])
old = edu.get(f"/portal/api/record?key=01&value={D}").get_json()["revision"]
mock_data_entry.DB[f"01_{D}"]["entries"][0]["itemDescription"] = "Changed"
CALLS.clear()
r = edu.post("/portal/api/record", json=save_body(D, "Milk", ["https://acme.example.com/m"]), headers=ORIGIN)
check("a save without the headers: written as before (the last save wins), no header sent to the data entry API",
      r.status_code == 200 and entries_of(D)[0][1] == "Milk" and all(c[3] is None and c[4] is None for c in writes()),
      (r.get_json(), writes()))
r = edu.post("/portal/api/record", json=save_body(D, "Milk", ["https://acme.example.com/m"]),
             headers={**ORIGIN, "If-Match": "*"})
check("a save with If-Match: * on an existing record: 200", r.status_code == 200, r.status_code)
r = edu.post("/portal/api/record", json=save_body(D, "Milk", ["https://acme.example.com/m"]),
             headers={**ORIGIN, "If-Match": f'W/"{old}", "{revision.of(portal.find_entry(portal.read_entries("/01/" + D)[0], []))}"'})
check("a save with a list of revisions naming the current one (and W/): 200", r.status_code == 200, r.status_code)

# ================================================================== the tenant API
r = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"], "days": 30},
             headers=ORIGIN)
KEY = {"Authorization": f"Bearer {(r.get_json() or {}).get('key', '')}"}
api = portal.app.test_client()
put_raw(E, [([], "Water", [LINK])])
r = api.get(f"/portal/api/v1/records/01/{E}", headers=KEY)
etag = r.headers.get("ETag")
check("the tenant API's read gives the record's revision as its ETag", r.status_code == 200 and etag
      == f'"{mock_data_entry.rev(mock_data_entry.entry_of(f"01_{E}", []))}"', (r.status_code, r.headers))
BODY = {"description": "Water", "links": [{"linkType": "gs1:pip", "url": "https://acme.example.com/w", "hreflang": ["en"]}]}
r = api.put(f"/portal/api/v1/records/01/{E}", json=BODY, headers={**KEY, "If-Match": etag})
new_etag = r.headers.get("ETag")
check("the tenant API's save with If-Match of the read: 200, the new revision as its ETag", r.status_code == 200
      and new_etag and new_etag != etag and new_etag == f'"{mock_data_entry.rev(mock_data_entry.entry_of(f"01_{E}", []))}"',
      (r.status_code, r.get_json(), r.headers))
CALLS.clear()
r = api.put(f"/portal/api/v1/records/01/{E}", json={**BODY, "description": "Old"}, headers={**KEY, "If-Match": etag})
check("…with the ETag of an earlier read: 412 record.changed, nothing written", r.status_code == 412
      and code(r) == "record.changed" and entries_of(E)[0][1] == "Water" and not writes(), (r.status_code, r.get_json()))
r = api.put(f"/portal/api/v1/records/01/{E}?qualifiers=/10/W1", json=BODY, headers={**KEY, "If-None-Match": "*"})
check("…If-None-Match: * for a record that does not exist: 201 with its ETag", r.status_code == 201
      and r.headers.get("ETag"), (r.status_code, r.headers))
r = api.put(f"/portal/api/v1/records/01/{E}?qualifiers=/10/W1", json=BODY, headers={**KEY, "If-None-Match": "*"})
check("…If-None-Match: * again, the record now exists: 412", r.status_code == 412 and code(r) == "record.changed",
      r.status_code)
r = api.delete(f"/portal/api/v1/records/01/{E}", headers={**KEY, "If-Match": etag})
check("the tenant API's delete with the ETag of an earlier read: 412, the record kept", r.status_code == 412
      and len(entries_of(E)) == 2, (r.status_code, entries_of(E)))
r = api.delete(f"/portal/api/v1/records/01/{E}", headers={**KEY, "If-Match": new_etag})
check("…with the ETag of the record as read: deleted", r.status_code == 200 and len(entries_of(E)) == 1, r.status_code)
r = api.put(f"/portal/api/v1/records/01/{E}?qualifiers=/10/W1", json=BODY, headers=KEY)
check("the tenant API's save without the headers: as before", r.status_code == 200, r.status_code)

# the description of the tenant API
spec = portal.app.test_client().get("/portal/api/v1/openapi.json").get_json()
record_path = spec["paths"]["/records/{key}/{value}"]
check("the tenant API's description: ETag on the read and the save, If-Match/If-None-Match, 412 record.changed",
      "ETag" in record_path["get"]["responses"]["200"].get("headers", {})
      and "ETag" in record_path["put"]["responses"]["200"].get("headers", {})
      and {p["$ref"] for p in record_path["put"]["parameters"]} >= {"#/components/parameters/IfMatch",
                                                                   "#/components/parameters/IfNoneMatch"}
      and record_path["put"]["responses"].get("412") and record_path["delete"]["responses"].get("412")
      and "record.changed" in spec["components"]["responses"]["Changed"]["description"], record_path["put"]["responses"])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
