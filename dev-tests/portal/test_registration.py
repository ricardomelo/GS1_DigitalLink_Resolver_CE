"""
The registration model of GS1-Conformant Resolver 1.2.1, section 2.5.9, through the portal's own API (Flask
test client) against the in-memory stand-in for the data entry API:

  * rule 2: a serial number of a GTIN is registered with its serial only; the variant and batch typed with it
    are kept as informative qualifiers, returned when the record is opened, listed, searched, exported and
    imported again; a later import that changes them is shown as an update with the batch it had before;
  * records made before the rule (serial number with batch) are flagged in the record list;
  * "a default link at the entry level or higher": the record list flags qualified records of keys without a
    record of their own; saving such a record can create the key's record, copying the targets or with
    another target; a spreadsheet import lists those keys and creates their records when asked.

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_registration.py
"""
import base64
import csv
import io
import os
import sys
import tempfile
import threading
import time

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3398
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_USERS_FILE=f"{CONFIG}/users.json", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.set_password("maria", "a-long-test-password")
import app as portal  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


web = portal.app.test_client()
web.post("/portal/api/login", json={"username": "maria", "password": "a-long-test-password"})
G = "09506000134352"


def record(value=G, qualifiers=None, url="https://example.org/x", description="Item", **extra):
    body = {"key": "01", "value": value, "description": description,
            "links": [{"linkType": "gs1:pip", "url": url, "hreflang": ["en"], "title": "t"}], **extra}
    if qualifiers:
        body["qualifiers"] = qualifiers
    return body


def stored(value=G):
    return mock_data_entry.v3(f"01_{value}") if f"01_{value}" in mock_data_entry.DB else []


def listed():
    return web.get("/portal/api/records").get_json()["records"]


# ------------------------------------------------------------------ rule 2: serial numbers
web.post("/portal/api/record", json=record(description="Product"))
r = web.post("/portal/api/record", json=record(qualifiers={"22": "V1", "10": "B42", "21": "S1"}, description="Unit S1"))
entry = [e for e in stored() if e.get("qualifiers") == [{"21": "S1"}]]
check("serial number saved with its serial only; variant and batch informative",
      r.status_code == 201 and entry and entry[0].get("informativeQualifiers") == [{"22": "V1"}, {"10": "B42"}], (r.get_json(), stored()))
check("the saved record's Digital Link keeps every qualifier",
      r.get_json().get("digitalLink") == f"https://id.example.org/01/{G}/22/V1/10/B42/21/S1", r.get_json())
check("no record was made for the batch", not [e for e in stored() if e.get("qualifiers") == [{"10": "B42"}]], stored())

got = web.get(f"/portal/api/record?key=01&value={G}&qualifiers=/21/S1").get_json()
check("opening the serial without its batch finds the record and its informative qualifiers",
      got["exists"] and got["qualifiers"] == [["21", "S1"]] and got["storedInformative"] == [["22", "V1"], ["10", "B42"]]
      and got["digitalLink"].endswith("/22/V1/10/B42/21/S1"), got)
got = web.get(f"/portal/api/record?key=01&value={G}&qualifiers=/10/OTHER/21/S1").get_json()
check("opening it with another batch finds the same record", got["exists"] and got["informative"] == [["10", "OTHER"]], got)

web.post("/portal/api/record", json=record(qualifiers={"10": "B43", "21": "S1"}, description="Unit S1"))
entry = [e for e in stored() if e.get("qualifiers") == [{"21": "S1"}]]
check("saving another batch replaces the informative qualifiers (the variant goes)",
      entry and entry[0].get("informativeQualifiers") == [{"10": "B43"}], entry)
web.post("/portal/api/record", json=record(qualifiers={"21": "S1"}, description="Unit S1"))
entry = [e for e in stored() if e.get("qualifiers") == [{"21": "S1"}]]
check("saving without batch or variant clears them", entry and not entry[0].get("informativeQualifiers"), entry)
web.post("/portal/api/record", json=record(qualifiers={"22": "V1", "10": "B42", "21": "S1"}, description="Unit S1"))

versions = web.get(f"/portal/api/history?key=01&value={G}&qualifiers=/10/B42/21/S1").get_json()["versions"]
check("history of the serial number, whatever batch is typed", len(versions) == 4, versions)

rows = {r["qpath"]: r for r in listed() if r["value"] == G}
check("record list: the serial number with its informative qualifiers",
      rows.get("/21/S1", {}).get("informative") == [["22", "V1"], ["10", "B42"]], rows)

# export and import again
body = web.post("/portal/api/export", json={"format": "csv", "labels": {}}).get_data(as_text=True)
lines = list(csv.reader(io.StringIO(body.lstrip("\ufeff")), delimiter=";"))
check("export writes the serial number's qualifiers with the informative ones, in path order",
      any("(22)V1(10)B42(21)S1" in line for line in lines), lines)


def preview(text, name="x.csv"):
    return web.post("/portal/api/import/preview", json={"filename": name, "content": base64.b64encode(text.encode()).decode(),
                                                        "labels": {}}).get_json()


again = preview(body.lstrip("\ufeff"))
check("importing the export again changes nothing", again["counts"]["update"] == 0 and again["counts"]["create"] == 0
      and again["counts"]["error"] == 0, again)
changed = preview("key;value;qualifiers;description;linkType;url;language\n"
                  f"01;{G};(10)B99(21)S1;Unit S1;gs1:pip;https://example.org/x;en\n")
item = changed["records"][0]
check("an import that changes a serial number's batch is an update showing the batch it had",
      item["action"] == "update" and item["qualifiers"] == [["21", "S1"]] and item["informative"] == [["10", "B99"]]
      and item["informativeBefore"] == [["22", "V1"], ["10", "B42"]], changed)

# records made before rule 2
mock_data_entry.DB[f"01_{G}"]["entries"].append({"qualifiers": [{"10": "OLD"}, {"21": "S9"}], "itemDescription": "Old",
                                                 "links": [{"linktype": "gs1:pip", "href": "https://example.org/o",
                                                            "title": "t", "hreflang": ["en"]}], "informative": []})
rows = {r["qpath"]: r for r in listed() if r["value"] == G}
check("record list flags a serial number registered with its batch (made before rule 2)",
      rows.get("/10/OLD/21/S9", {}).get("breaksRules") is True and not rows["/21/S1"].get("breaksRules"), rows)
mock_data_entry.DB[f"01_{G}"]["entries"].pop()

# ------------------------------------------------------------------ a default link at the key level (1.3)
T = "09506000134901"
r = web.post("/portal/api/record", json=record(T, {"10": "L1"}, url="https://example.org/tea/L1", description="Tea L1"))
rows = [r for r in listed() if r["value"] == T]
check("record list flags a batch of a GTIN without a record of its own", rows and rows[0]["noKeyRecord"] is True, rows)
check("record list does not flag records of a key that has its own record",
      not any(r.get("noKeyRecord") for r in listed() if r["value"] == G))
got = web.get(f"/portal/api/record?key=01&value={T}&qualifiers=/10/L2").get_json()
check("the editor is told the key has no record of its own", got["hasKeyRecord"] is False, got)

r = web.post("/portal/api/record", json=record(T, {"10": "L2"}, url="https://example.org/tea/L2", description="Tea L2",
                                               keyRecord={"mode": "copy", "description": "Tea"}))
key_entry = [e for e in stored(T) if not e.get("qualifiers")]
check("saving with mode copy creates the key's record with the same targets first",
      r.get_json()["code"] == "save.createdWithKey" and key_entry and key_entry[0]["itemDescription"] == "Tea"
      and key_entry[0]["links"][0]["href"] == "https://example.org/tea/L2", (r.get_json(), stored(T)))
check("…and the batch record", any(e.get("qualifiers") == [{"10": "L2"}] for e in stored(T)))
check("no record flagged any more for that key", not any(r.get("noKeyRecord") for r in listed() if r["value"] == T))
r = web.post("/portal/api/record", json=record(T, {"10": "L3"}, keyRecord={"mode": "copy"}))
check("asking again when the key already has its record changes nothing",
      r.get_json()["code"] == "save.created" and len([e for e in stored(T) if not e.get("qualifiers")]) == 1, r.get_json())

C = "09506000134925"
r = web.post("/portal/api/record", json=record(C, {"21": "C1"}, url="https://example.org/coffee/C1", description="Coffee C1",
                                               keyRecord={"mode": "target", "url": "https://example.org/coffee",
                                                          "description": "Coffee"}))
key_entry = [e for e in stored(C) if not e.get("qualifiers")]
check("saving with mode target creates the key's record with that target, the default link type and language",
      key_entry and [(l["linktype"], l["href"], l["hreflang"]) for l in key_entry[0]["links"]]
      == [("gs1:pip", "https://example.org/coffee", ["en"])], stored(C))
r = web.post("/portal/api/record", json=record("09506000134932", {"10": "X"}, keyRecord={"mode": "target", "url": "not a url"}))
check("an invalid target for the key's record stops the save", r.status_code >= 400
      and "09506000134932" not in str(list(mock_data_entry.DB)), r.get_json())

# import: keys without a record of their own
sheet = ("key;value;qualifiers;description;linkType;url;language\n"
         "01;09506000134949;(10)A1;Juice A1;gs1:pip;https://example.org/juice/A1;en\n"
         "01;09506000134949;(10)A2;Juice A2;gs1:pip;https://example.org/juice/A2;en\n"
         "01;09506000134956;;Water;gs1:pip;https://example.org/water;en\n"
         "01;09506000134956;(10)W1;Water W1;gs1:pip;https://example.org/water/W1;en\n")
p = preview(sheet)
check("import preview lists the keys left without a record of their own, once",
      [(k["value"], k["rows"]) for k in p["keysWithoutRecord"]] == [("09506000134949", [2])]
      and sum(1 for i in p["records"] if i.get("noKeyRecord")) == 2, p)
r = web.post("/portal/api/import/apply", json={"token": p["token"], "createKeyRecords": True})
check("applying with createKeyRecords adds the keys' records to the plan", r.get_json()["total"] == 5, r.get_json())
for _ in range(50):
    status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
    if status["state"] == "finished":
        break
    time.sleep(0.1)
key_entry = [e for e in stored("09506000134949") if not e.get("qualifiers")]
check("the key's record is created with the targets of its first qualified record in the file",
      key_entry and key_entry[0]["links"][0]["href"] == "https://example.org/juice/A1"
      and status["results"][0]["qualifiers"] == [], (stored("09506000134949"), status))
p = preview(sheet.replace("09506000134949", "09506000134963"))
web.post("/portal/api/import/apply", json={"token": p["token"]})
for _ in range(50):
    if web.get(f"/portal/api/import/status?token={p['token']}").get_json()["state"] == "finished":
        break
    time.sleep(0.1)
check("without createKeyRecords the import writes only its own rows",
      not [e for e in stored("09506000134963") if not e.get("qualifiers")] and len(stored("09506000134963")) == 2,
      stored("09506000134963"))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
