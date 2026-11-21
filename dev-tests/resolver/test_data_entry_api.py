"""
Development test for the data entry API (no Docker, no MongoDB): token protection and registration rules.

Builds the real data entry application with the database layer replaced by an in-memory stub and
checks, through Flask's test client:
  * every data entry operation except /heartbeat refuses requests without a token (401) or with a
    wrong token (403), including /index and /summary;
  * the Swagger description declares the BearerAuth scheme on every protected operation, so the
    "Authorize" button of /api/docs sends the token with them;
  * the registration rules of GS1-Conformant Resolver 1.2.1, section 2.5.9 (qualifiers allowed for each
    key, AI 235 alone, no AI 22 or AI 10 with AI 21) on POST /new and PUT, and the informative qualifiers
    of a serial-number record: stored, returned, listed in /summary, changed and cleared by PUT;
  * POST /new on a record that exists merges its links as PUT does, and a list writes every record of a key (a
    record sent twice merged); PUT and a DELETE of links with qualifiers no record of the key has answer 404 and
    change nothing;
  * a DELETE with {"removeRecord": true, "qualifiers": [...]} removes one record and keeps the key's others in one
    conditional write of the document (ADR 0023), read again when another writer changed it; the database layer's
    conditional write on mongomock;
  * the browser's rules (ADR 0038): the Swagger UI's policy (this origin only, never framed) and the policy of every
    other answer (nothing at all); the Swagger UI opened in Chromium starts and the policy refuses nothing;
  * a body that is not JSON (or, for PUT and DELETE, not an object) and a record without a link of its default link
    type answer 400 and change nothing.

  pip install -r data_entry_server/src/requirements.txt
  python dev-tests/resolver/test_data_entry_api.py
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))
TOKEN = "test-token"
os.environ.update(SESSION_TOKEN=TOKEN, MONGO_URI="mongodb://unused")

fake_mongo = types.ModuleType("mongo_db_init")
fake_mongo.mongo = None
fake_mongo.init_mongo = lambda app: None
sys.modules["mongo_db_init"] = fake_mongo

db = types.ModuleType("data_entry_db")
db.read_index = lambda: {"response_status": 200, "data": ["01_09506000134352"]}
db.read_all_documents = lambda: {"response_status": 200, "data": []}
db.read_document = lambda document_id: {"response_status": 404, "error": "not found"}
sys.modules["data_entry_db"] = db

sys.path.insert(0, os.path.join(REPO, "data_entry_server", "src"))
from __init__ import create_app  # noqa: E402  (the data entry package's own factory)

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


PROTECTED = [("get", "/api/index"), ("get", "/api/summary"), ("get", "/api/01/09506000134352"),
             ("get", "/api/01/09506000134352/10/ABC"), ("put", "/api/01/09506000134352"),
             ("delete", "/api/01/09506000134352"), ("post", "/api/new")]

for method, path in PROTECTED:
    r = getattr(client, method)(path, json={})
    check(f"{method.upper()} {path} without token → 401", r.status_code == 401, r.status_code)
    r = getattr(client, method)(path, json={}, headers={"Authorization": "Bearer wrong"})
    check(f"{method.upper()} {path} with a wrong token → 403", r.status_code == 403, r.status_code)

r = client.get("/api/index", headers={"Authorization": f"Bearer {TOKEN}"})
check("GET /api/index with the token → 200 and the list", r.status_code == 200
      and r.get_json().get("data") == ["/01/09506000134352"], r.get_data(as_text=True))
r = client.get("/api/summary", headers={"Authorization": f"Bearer {TOKEN}"})
check("GET /api/summary with the token → 200", r.status_code == 200, r.status_code)
r = client.get("/api/heartbeat")
check("GET /api/heartbeat stays public", r.status_code == 200, r.status_code)

spec = client.get("/api/swagger.json").get_json()
paths = spec.get("paths", {})
check("Swagger: BearerAuth scheme defined", "BearerAuth" in (spec.get("securityDefinitions") or {}))
for method, path in PROTECTED:
    swagger_path = path.replace("/api", "", 1)
    swagger_path = swagger_path.replace("/01/09506000134352/10/ABC", "/{anchor_ai_code}/{anchor_ai}/{extra_segments}")
    swagger_path = swagger_path.replace("/01/09506000134352", "/{anchor_ai_code}/{anchor_ai}")
    operation = (paths.get(swagger_path) or {}).get(method) or {}
    check(f"Swagger: {method.upper()} {swagger_path} declares BearerAuth",
          {"BearerAuth": []} in (operation.get("security") or []), operation.get("security"))


# ---------------------------------------------------------------- registration rules and informative qualifiers
import copy  # noqa: E402
import data_entry_logic  # noqa: E402

STORE = {}
db.read_document = lambda document_id: ({"response_status": 200, "data": copy.deepcopy(STORE[document_id])}
                                        if document_id in STORE else {"response_status": 404, "error": "not found"})
db.create_document = lambda doc: ({"response_status": 409, "error": "exists"} if doc["_id"] in STORE else
                                  (STORE.__setitem__(doc["_id"], copy.deepcopy(doc)), {"response_status": 201})[1])


def stored_write(doc, expected):
    """data_entry_db.write_document_if_unchanged() on STORE: written only while the stored document is the one read."""
    if STORE.get(doc["_id"]) != expected:
        return {"response_status": 409, "error": "changed"}
    if doc["data"]:
        STORE[doc["_id"]] = copy.deepcopy(doc)
    else:
        STORE.pop(doc["_id"])
    return {"response_status": 200}


db.write_document_if_unchanged = stored_write
db.read_all_documents = lambda: {"response_status": 200, "data": copy.deepcopy(list(STORE.values()))}
data_entry_logic.data_entry_db = db
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PIP = [{"linktype": "gs1:pip", "href": "https://example.com/p", "title": "Product", "hreflang": ["en"]}]


def post(doc):
    return client.post("/api/new", json=doc, headers=AUTH)


def entry(anchor="/01/09506000134352", **extra):
    return {"anchor": anchor, "itemDescription": "x", "defaultLinktype": "gs1:pip", "links": PIP, **extra}


REFUSED = [
    ("GTIN with batch and serial (rule 2)", entry(qualifiers=[{"10": "B1"}, {"21": "S1"}])),
    ("GTIN with variant and serial (rule 2)", entry(qualifiers=[{"22": "V1"}, {"21": "S1"}])),
    ("ITIP with batch and serial (rule 2)", entry("/8006/095060001343520102", qualifiers=[{"10": "B1"}, {"21": "S1"}])),
    ("TPX with a batch (rule 1)", entry(qualifiers=[{"235": "T1"}, {"10": "B1"}])),
    ("a qualifier the key does not take", entry(qualifiers=[{"17": "261231"}])),
    ("a qualifier on SSCC", entry("/00/095060001343520000", qualifiers=[{"21": "S1"}])),
    ("AI 415 without AI 8020", entry("/415/9506000134376")),
    ("the same AI twice", entry(qualifiers=[{"10": "B1"}, {"10": "B2"}])),
    ("informative qualifiers without a serial", entry(qualifiers=[{"10": "B1"}], informativeQualifiers=[{"22": "V1"}])),
    ("informative serial", entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"21": "S2"}])),
    ("informative qualifiers on a GLN", entry("/414/9506000134376", qualifiers=[{"254": "D1"}], informativeQualifiers=[{"10": "B1"}])),
    ("qualifiers that are not one-entry objects", entry(qualifiers=[{"10": "B1", "21": "S1"}])),
]
for name, doc in REFUSED:
    r = post(doc)
    check(f"POST /new refuses {name} → 400", r.status_code == 400 and r.get_json().get("error"), r.get_data(as_text=True))
r = post([entry(qualifiers=[{"10": "B1"}]), entry(qualifiers=[{"10": "B1"}, {"21": "S1"}])])
check("POST /new with a list refuses the whole list when one item breaks a rule, naming it",
      r.status_code == 400 and "Item 2" in r.get_json().get("error", "") and not STORE, r.get_data(as_text=True))

ACCEPTED = [
    ("GTIN", entry()), ("GTIN with variant and batch", entry(qualifiers=[{"22": "V1"}, {"10": "B1"}])),
    ("GTIN with a template batch", entry(qualifiers=[{"10": "{lotnumber}"}])),
    ("GTIN with TPX", entry(qualifiers=[{"235": "T1"}])),
    ("AI 415 with AI 8020", entry("/415/9506000134376", qualifiers=[{"8020": "R1"}])),
    ("GLN with extension", entry("/414/9506000134376", qualifiers=[{"254": "D1"}])),
    ("serial with informative variant and batch",
     entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"22": "V1"}, {"10": "B1"}])),
]
for name, doc in ACCEPTED:
    r = post(doc)
    check(f"POST /new accepts {name}", r.status_code in (200, 201), r.get_data(as_text=True))

r = client.get("/api/01/09506000134352", headers=AUTH)
serial = [e for e in r.get_json().get("data", []) if e.get("qualifiers") == [{"21": "S1"}]]
check("GET returns the informative qualifiers of the serial record",
      serial and serial[0].get("informativeQualifiers") == [{"22": "V1"}, {"10": "B1"}], r.get_json())
others = [e for e in r.get_json().get("data", []) if "informativeQualifiers" in e and e.get("qualifiers") != [{"21": "S1"}]]
check("GET: no other record carries informative qualifiers", not others, others)
lines = client.get("/api/summary", headers=AUTH).get_json().get("data", [])
check("/summary lists the informative qualifiers",
      any(l.get("qualifiers") == [{"21": "S1"}] and l.get("informativeQualifiers") == [{"22": "V1"}, {"10": "B1"}] for l in lines), lines)

r = client.put("/api/01/09506000134352", json={"qualifiers": [{"21": "S1"}], "informativeQualifiers": [{"10": "B2"}]}, headers=AUTH)
data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
check("PUT replaces the informative qualifiers", r.status_code == 200 and any(
    e.get("qualifiers") == [{"21": "S1"}] and e.get("informativeQualifiers") == [{"10": "B2"}] for e in data), data)
r = client.put("/api/01/09506000134352", json={"qualifiers": [{"21": "S1"}], "itemDescription": "y"}, headers=AUTH)
data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
check("PUT without the field keeps the informative qualifiers", any(
    e.get("qualifiers") == [{"21": "S1"}] and e.get("informativeQualifiers") == [{"10": "B2"}] for e in data), data)
r = client.put("/api/01/09506000134352", json={"qualifiers": [{"21": "S1"}], "informativeQualifiers": []}, headers=AUTH)
data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
check("PUT with an empty list clears them", any(
    e.get("qualifiers") == [{"21": "S1"}] and "informativeQualifiers" not in e for e in data), data)
r = client.put("/api/01/09506000134352", json={"qualifiers": [{"22": "V1"}, {"10": "B1"}], "informativeQualifiers": [{"22": "V2"}]},
               headers=AUTH)
check("PUT refuses informative qualifiers on a batch record → 400", r.status_code == 400, r.get_data(as_text=True))
r = post(entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"10": "B9"}]))
data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
check("POST /new on an existing serial record updates its informative qualifiers", any(
    e.get("qualifiers") == [{"21": "S1"}] and e.get("informativeQualifiers") == [{"10": "B9"}] for e in data), data)


def batch_links():
    data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
    return next((e.get("links") for e in data if e.get("qualifiers") == [{"10": "B1"}]), None)


# The merge of POST /new on an existing record is PUT's, on (linktype, hreflang, context) (official pull request #128)
post(entry(qualifiers=[{"10": "B1"}]))
r = post(entry(qualifiers=[{"10": "B1"}]))
links = batch_links()
stored = [e for e in STORE["01_09506000134352"]["data"] if e["qualifiers"] == [{"10": "B1"}]]
check("POST /new of the same record again does not duplicate its links",
      r.status_code in (200, 201) and links is not None and len(links) == 1 and len(stored[0]["linkset"]) == 1,
      (links, stored))
post(entry(qualifiers=[{"10": "B1"}], links=[{**PIP[0], "href": "https://example.com/p2"}]))
links = batch_links()
check("POST /new on an existing record: a link of the same type, languages and context replaced in place",
      links is not None and [l.get("href") for l in links] == ["https://example.com/p2"], links)
post(entry(qualifiers=[{"10": "B1"}], links=[{**PIP[0], "hreflang": ["pt"], "href": "https://example.com/pt"}]))
links = batch_links()
check("POST /new on an existing record: a link in other languages added",
      links is not None and sorted(l.get("href") for l in links) == ["https://example.com/p2", "https://example.com/pt"], links)

# A list sent to POST /new writes every record of a key, the document once: the official code stopped at the first
# record when the document existed, and a new document kept a record sent twice as two entries
stored = [e["qualifiers"] for e in STORE["01_09506000134352"]["data"]]
r = post([entry(qualifiers=[{"10": "L1"}]), entry(qualifiers=[{"10": "L2"}])])
after = [e["qualifiers"] for e in STORE["01_09506000134352"]["data"]]
check("POST /new with a list on a key that exists stores every record, keeping the others",
      r.status_code == 201 and after == stored + [[{"10": "L1"}], [{"10": "L2"}]], (r.status_code, after))
PT = [{**PIP[0], "hreflang": ["pt"], "href": "https://example.com/pt"}]
r = post([entry("/01/09506000134369"), entry("/01/09506000134369", links=PT)])
data = STORE.get("01_09506000134369", {}).get("data", [])
links = client.get("/api/01/09506000134369", headers=AUTH).get_json().get("data", [{}])[0].get("links", [])
check("POST /new with a list naming a record twice, new key: one record, its links merged",
      r.status_code == 201 and len(data) == 1 and sorted(l.get("href") for l in links)
      == ["https://example.com/p", "https://example.com/pt"], (data, links))
r = post([entry("/01/09506000134369", links=[{**PIP[0], "href": "https://example.com/p2"}]),
          entry("/01/09506000134369", qualifiers=[{"10": "L1"}])])
data = client.get("/api/01/09506000134369", headers=AUTH).get_json().get("data", [])
own = next((e.get("links") for e in data if not e.get("qualifiers")), [])
check("POST /new with a list on a key that exists: its record merged, a new record added",
      r.status_code == 201 and len(data) == 2 and sorted(l.get("href") for l in own)
      == ["https://example.com/p2", "https://example.com/pt"] and any(e.get("qualifiers") == [{"10": "L1"}] for e in data),
      data)

# PUT and a DELETE of links name one record by its qualifiers: none of the key's records with them is a 404, not a
# change to the key's first record
before = copy.deepcopy(STORE)
r = client.put("/api/01/09506000134352", json={"qualifiers": [{"10": "B404"}], "links": PIP}, headers=AUTH)
check("PUT with qualifiers no record of the key has → 404 naming the record, nothing changed",
      r.status_code == 404 and "/10/B404" in r.get_json().get("error", "") and STORE == before, r.get_data(as_text=True))
r = client.delete("/api/01/09506000134352", json={"qualifiers": [{"10": "B404"}],
                                                   "links": [{"linktype": "gs1:pip", "hreflang": ["en"], "context": []}]},
                  headers=AUTH)
check("DELETE of links with qualifiers no record of the key has → 404, nothing removed",
      r.status_code == 404 and STORE == before, r.get_data(as_text=True))
post(entry("/01/09521234000013", qualifiers=[{"10": "B1"}]))
before = copy.deepcopy(STORE)
r = client.put("/api/01/09521234000013", json={"itemDescription": "z", "links": PIP}, headers=AUTH)
check("PUT without qualifiers on a key with only a batch record → 404, the batch unchanged",
      r.status_code == 404 and STORE == before, r.get_data(as_text=True))
r = client.delete("/api/01/09521234000013", json={"links": [{"linktype": "gs1:pip", "hreflang": ["en"], "context": []}]},
                  headers=AUTH)
check("DELETE of links without qualifiers on that key → 404, the batch keeps its link",
      r.status_code == 404 and STORE == before, r.get_data(as_text=True))

# ---------------------------------------------------------------- error answers: 400 for a body that cannot be used
# The official handlers read the body inside their catch-all (a body that was not JSON answered 500), POST /new of a
# record without a link of its default link type answered a status made of two dictionary keys, and a DELETE whose
# body was a list deleted the whole document
db.delete_document = lambda document_id: (STORE.pop(document_id, None), {"response_status": 200})[1]
JSON = {**AUTH, "Content-Type": "application/json"}
before = copy.deepcopy(STORE)
r = client.post("/api/new", data="{,}", headers=JSON)
check("POST /new with a body that is not JSON → 400 saying so", r.status_code == 400
      and "not valid JSON" in (r.get_json() or {}).get("error", ""), (r.status_code, r.get_data(as_text=True)))
r = post(entry("/01/09506000134376", links=[]))
check("POST /new of a record without a link of its default link type → 400 naming the type, nothing stored",
      r.status_code == 400 and "gs1:pip" in (r.get_json() or {}).get("error", "") and STORE == before,
      (r.status, r.get_data(as_text=True)))
r = post([entry("/01/09506000134376"), entry("/01/09506000134376", qualifiers=[{"10": "B1"}], links=[])])
check("POST /new with a list, one record without a link of its default link type → 400, nothing stored",
      r.status_code == 400 and STORE == before, (r.status, r.get_data(as_text=True)))
r = client.post("/api/new", data='"text"', headers=JSON)
check("POST /new with a body that is neither an object nor a list → 400", r.status_code == 400 and STORE == before,
      (r.status, r.get_data(as_text=True)))
r = client.put("/api/01/09506000134352", data="{,}", headers=JSON)
r2 = client.put("/api/01/09506000134352", data="[]", headers=JSON)
check("PUT with a body that is not JSON, or not an object → 400, nothing changed",
      r.status_code == r2.status_code == 400 and STORE == before, (r.status_code, r2.status_code))
r = client.delete("/api/01/09506000134352", data="{,}", headers=JSON)
check("DELETE with a body that is not JSON → 400, the document kept", r.status_code == 400 and STORE == before,
      (r.status_code, r.get_data(as_text=True)))
r = client.delete("/api/01/09506000134352", data='[{"linktype": "gs1:pip"}]', headers=JSON)
check("DELETE with a body that is not an object → 400, the document kept (the official code deleted it)",
      r.status_code == 400 and STORE == before, (r.status_code, r.get_data(as_text=True)))
# a body that names no link is not a request to delete everything (the official code deleted the whole document)
for body in ({}, {"qualifiers": [{"10": "B1"}]}, {"links": []}, {"links": "gs1:pip"}, {"links": ["gs1:pip"]}):
    r = client.delete("/api/01/09506000134352", json=body, headers=AUTH)
    check(f"DELETE with a body that names no link ({json.dumps(body)[:30]}) → 400, the document kept",
          r.status_code == 400 and "links" in (r.get_json() or {}).get("error", "") and STORE == before,
          (r.status_code, r.get_data(as_text=True)))
r = client.post("/api/validate", data="{,}", headers=JSON)
check("POST /validate with a body that is not JSON → 400 saying so", r.status_code == 400
      and "not valid JSON" in (r.get_json() or {}).get("error", ""), (r.status_code, r.get_data(as_text=True)))

# ---------------------------------------------------------------- POST /validate: what POST /new would refuse, nothing stored
before = copy.deepcopy(STORE)
r = client.post("/api/validate", json=[entry(qualifiers=[{"10": "B1"}]), entry(qualifiers=[{"10": "B1"}, {"21": "S1"}])],
                headers=AUTH)
problems = (r.get_json() or {}).get("problems")
check("POST /validate names the item POST /new would refuse and why", r.status_code == 200 and len(problems) == 1
      and problems[0]["item"] == 2 and "rule 2" in problems[0]["error"], r.get_json())
check("…and stores nothing", STORE == before)
r = client.post("/api/validate", json=entry(), headers=AUTH)
check("…one entry, valid: no problem", r.status_code == 200 and r.get_json()["problems"] == [], r.get_json())
check("…needs the token", client.post("/api/validate", json=entry()).status_code == 401)

# ---------------------------------------------------------------- one record removed, the key's others kept (ADR 0023)
# The official API deleted whole documents only, so its callers deleted the key and wrote the other records back: a
# window in which every code of the key answered 404, for good when the second call failed. DELETE with
# {"removeRecord": true, "qualifiers": [...]} removes one record in one write of the document, provided the document is
# still the one read (write_document_if_unchanged); a document changed in between is read again.
WRITES = []


def write_if_unchanged(doc, expected):
    WRITES.append(doc["_id"])
    return stored_write(doc, expected)


db.write_document_if_unchanged = write_if_unchanged
WHOLE = []
db.delete_document = lambda document_id: (WHOLE.append(document_id), STORE.pop(document_id, None),
                                          {"response_status": 200})[2]
STORE.clear()
post([entry(), entry(qualifiers=[{"10": "R1"}]), entry(qualifiers=[{"10": "R2"}]),
      entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"10": "R1"}])])
KEY = "01_09506000134352"
quals = lambda: [e["qualifiers"] for e in STORE[KEY]["data"]]
r = client.delete("/api/01/09506000134352", json={"removeRecord": True, "qualifiers": [{"10": "R1"}]}, headers=AUTH)
check("DELETE with removeRecord removes the batch's record → 200, removed 1, 3 remaining", r.status_code == 200
      and r.get_json().get("removed") == 1 and r.get_json().get("remaining") == 3, r.get_data(as_text=True))
check("…in one conditional write of the document, never a whole delete", WRITES == [KEY] and not WHOLE, (WRITES, WHOLE))
check("…the key's other records kept, the serial number's informative batch too",
      quals() == [[], [{"10": "R2"}], [{"21": "S1"}]]
      and STORE[KEY]["data"][2].get("informativeQualifiers") == [{"10": "R1"}], STORE[KEY]["data"])
r = client.delete("/api/01/09506000134352", json={"removeRecord": True, "qualifiers": [{"10": "R9"}]}, headers=AUTH)
check("…a record the key does not have → 404 naming it, nothing changed", r.status_code == 404
      and "/10/R9" in r.get_json().get("error", "") and len(quals()) == 3, r.get_data(as_text=True))
r = client.delete("/api/01/09506000134999", json={"removeRecord": True, "qualifiers": []}, headers=AUTH)
check("…a key without a document → 404", r.status_code == 404, r.status_code)
r = client.delete("/api/01/09506000134352", json={"removeRecord": True}, headers=AUTH)
check("…no qualifiers: the key's own record removed, its batch and serial kept", r.status_code == 200
      and quals() == [[{"10": "R2"}], [{"21": "S1"}]], quals())
for body in ({"removeRecord": False, "qualifiers": [{"10": "R2"}]}, {"removeRecord": "yes", "qualifiers": [{"10": "R2"}]},
             {"removeRecord": True, "qualifiers": [{"10": "R2"}], "links": PIP},
             {"removeRecord": True, "qualifiers": {"10": "R2"}}, {"removeRecord": True, "qualifiers": [{"10": 2}]},
             {"removeRecord": True, "qualifiers": [{"10": "R2", "21": "S1"}]}):
    r = client.delete("/api/01/09506000134352", json=body, headers=AUTH)
    check(f"…a malformed record delete ({json.dumps(body)[:48]}) → 400, nothing removed", r.status_code == 400
          and "removeRecord" in r.get_json().get("error", "") and len(quals()) == 2, (r.status_code, quals()))
# another writer changes the document between the read and the write: read again, its change kept
real_read, raced = db.read_document, []


def racing_read(document_id):
    answer = real_read(document_id)
    if not raced:
        raced.append(1)
        STORE[KEY]["data"].append(copy.deepcopy(STORE[KEY]["data"][0]) | {"qualifiers": [{"10": "R3"}]})
    return answer


db.read_document = racing_read
WRITES.clear()
r = client.delete("/api/01/09506000134352", json={"removeRecord": True, "qualifiers": [{"10": "R2"}]}, headers=AUTH)
db.read_document = real_read
check("…a document changed by another writer in between: read again, removed, the other writer's record kept",
      r.status_code == 200 and len(WRITES) == 2 and quals() == [[{"21": "S1"}], [{"10": "R3"}]], (WRITES, quals()))
db.write_document_if_unchanged = lambda doc, expected: {"response_status": 409, "error": "changed"}
r = client.delete("/api/01/09506000134352", json={"removeRecord": True, "qualifiers": [{"10": "R3"}]}, headers=AUTH)
check("…a document that keeps changing → 409 after three attempts, nothing removed", r.status_code == 409
      and len(quals()) == 2, (r.status_code, quals()))
db.write_document_if_unchanged = write_if_unchanged
for q in ([{"21": "S1"}], [{"10": "R3"}]):
    r = client.delete("/api/01/09506000134352", json={"removeRecord": True, "qualifiers": q}, headers=AUTH)
check("…the last record removed: the document goes with it", r.status_code == 200 and KEY not in STORE
      and not WHOLE, (r.status_code, STORE.get(KEY)))

# ---------------------------------------------------------------- every write conditional: no lost update (F-009, ADR 0027)
# The official code read a key's document, changed it in memory and replaced it by its _id: of two writers that read
# the same document the second undid the first, and both were answered 200. Every write now goes through
# write_document_if_unchanged() (or create_document(), which refuses an _id created in the meantime); a refusal reads
# the document again and applies the change on top of the other writer's.
LEAFLET = [{"linktype": "gs1:epil", "href": "https://example.com/leaflet", "title": "Leaflet", "hreflang": ["en"]}]
SAFETY = [{"linktype": "gs1:safetyInfo", "href": "https://example.com/safety", "title": "Safety", "hreflang": ["en"]}]


def racing(other_writer, times=1):
    """read_document that lets another writer change the store right after the first `times` reads."""
    seen = []

    def read(document_id):
        answer = real_read(document_id)
        if len(seen) < times:
            seen.append(1)
            other_writer()
        return answer
    return read


def linktypes(key, qualifiers):
    for item in data_entry_logic._convert_mongo_linkset_to_v3(STORE[key]) if key in STORE else []:
        if data_entry_logic._do_qualifiers_match(item.get("qualifiers") or [], qualifiers):
            return sorted(l["linktype"] for l in item.get("links") or [])
    return None


def other_put(qualifiers, links):
    """Another writer's PUT, straight through the logic (as a second replica of the API would do it)."""
    return lambda: data_entry_logic.update_document(KEY, {"qualifiers": qualifiers, "links": links})


STORE.clear()
post([entry(), entry(qualifiers=[{"10": "L1"}])])
WRITES.clear()
db.read_document = racing(other_put([{"10": "L1"}], LEAFLET))
r = client.put("/api/01/09506000134352", json={"qualifiers": [], "links": SAFETY}, headers=AUTH)
db.read_document = real_read
check("PUT racing another writer's PUT on another record of the key → 200, read again and written on top",
      r.status_code == 200 and WRITES.count(KEY) == 3, (r.status_code, WRITES))
check("…the other writer's link kept (the official code lost it), this one written too",
      linktypes(KEY, [{"10": "L1"}]) == ["gs1:epil", "gs1:pip"] and linktypes(KEY, []) == ["gs1:pip", "gs1:safetyInfo"],
      STORE[KEY]["data"])

db.read_document = racing(other_put([], LEAFLET))
r = post(entry(qualifiers=[{"10": "L2"}]))
db.read_document = real_read
check("POST /new adding a record while another writer changes the key → 200, both changes kept",
      r.status_code == 200 and linktypes(KEY, [{"10": "L2"}]) == ["gs1:pip"]
      and "gs1:epil" in linktypes(KEY, []), (r.status_code, STORE[KEY]["data"]))

db.read_document = racing(other_put([{"10": "L2"}], LEAFLET))
r = client.delete("/api/01/09506000134352", json={"qualifiers": [], "links": SAFETY}, headers=AUTH)
db.read_document = real_read
check("DELETE of links racing another writer → 200, the links removed and the other writer's link kept",
      r.status_code == 200 and "gs1:safetyInfo" not in linktypes(KEY, [])
      and linktypes(KEY, [{"10": "L2"}]) == ["gs1:epil", "gs1:pip"], (r.status_code, STORE[KEY]["data"]))

NEW_KEY = "01_09521234000013"
db.read_document = racing(lambda: data_entry_logic.create_document(entry("/01/09521234000013", qualifiers=[{"10": "X1"}])))
r = post(entry("/01/09521234000013", qualifiers=[{"10": "X2"}]))
db.read_document = real_read
check("POST /new creating a key another writer creates at the same moment → read again, both records kept",
      r.status_code == 200 and [e["qualifiers"] for e in STORE[NEW_KEY]["data"]] == [[{"10": "X1"}], [{"10": "X2"}]],
      (r.status_code, STORE.get(NEW_KEY)))

before = copy.deepcopy(STORE)
db.write_document_if_unchanged = lambda doc, expected: {"response_status": 409, "error": "changed"}
answers = [client.put("/api/01/09506000134352", json={"qualifiers": [], "links": SAFETY}, headers=AUTH),
           post(entry(qualifiers=[{"10": "L3"}])),
           client.delete("/api/01/09506000134352", json={"qualifiers": [{"10": "L2"}], "links": LEAFLET}, headers=AUTH)]
db.write_document_if_unchanged = write_if_unchanged
check("a key that keeps changing → 409 for PUT, POST /new and DELETE of links, nothing written",
      [a.status_code for a in answers] == [409, 409, 409] and STORE == before,
      [(a.status_code, a.get_data(as_text=True)[:80]) for a in answers])
db.write_document_if_unchanged = lambda doc, expected: {"response_status": 409, "error": "changed"}
r = post([entry("/01/09521234000020"), entry(qualifiers=[{"10": "L4"}])])
db.write_document_if_unchanged = write_if_unchanged
check("…a list sent to POST /new stops at the item not written: 409 naming it, the written ones listed",
      r.status_code == 409 and "09506000134352" in r.get_json().get("error", "")
      and len(r.get_json().get("written", [])) == 1 and "01_09521234000020" in STORE, r.get_data(as_text=True)[:300])
db.write_document_if_unchanged = lambda doc, expected: {"response_status": 500, "error": "Database error: down"}
r = post(entry(qualifiers=[{"10": "L5"}]))
db.write_document_if_unchanged = write_if_unchanged
check("…a failed write of an existing key → its error status (the official code answered 200)", r.status_code == 500,
      (r.status_code, r.get_data(as_text=True)[:120]))

# the database layer itself (data_entry_db.write_document_if_unchanged) on mongomock: one conditional operation
import importlib.util  # noqa: E402
try:
    import mongomock  # noqa: E402
except ImportError:
    mongomock = None
if mongomock:
    spec = importlib.util.spec_from_file_location("real_data_entry_db",
                                                  os.path.join(REPO, "data_entry_server", "src", "data_entry_db.py"))
    real_db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_db)
    coll = mongomock.MongoClient()["resolver_ce"]["gs1resolver"]
    real_db._resolver_collection = coll
    one, two = {"qualifiers": [], "linkset": {"a": 1}}, {"qualifiers": [{"10": "B"}], "linkset": {"a": 2}}
    coll.insert_one({"_id": "01_1", "defaultLinktype": "gs1:pip", "data": [one, two]})
    read = lambda: coll.find_one({"_id": "01_1"})
    stale = real_db.write_document_if_unchanged({"_id": "01_1", "defaultLinktype": "gs1:pip", "data": [one]},
                                                {"_id": "01_1", "defaultLinktype": "gs1:pip", "data": [two]})
    check("database layer: records no longer the ones read → 409, the document untouched",
          stale["response_status"] == 409 and read()["data"] == [one, two], stale)
    stale = real_db.write_document_if_unchanged({"_id": "01_1", "defaultLinktype": "gs1:pip", "data": [one]},
                                                {**read(), "defaultLinktype": "gs1:epil"})
    check("database layer: the key's default link type no longer the one read → 409, the document untouched",
          stale["response_status"] == 409 and read()["data"] == [one, two], stale)
    done = real_db.write_document_if_unchanged({"_id": "01_1", "defaultLinktype": "gs1:pip", "data": [one]}, read())
    check("database layer: the document still the one read → replaced without the record", done["response_status"] == 200
          and read()["data"] == [one], done)
    check("database layer: no unconditional replace left (update_document gone)", not hasattr(real_db, "update_document"))
    done = real_db.write_document_if_unchanged({"_id": "01_1", "defaultLinktype": "gs1:pip", "data": []}, read())
    check("database layer: no record left → the document deleted", done["response_status"] == 200
          and read() is None, done)
    gone = real_db.write_document_if_unchanged({"_id": "01_1", "data": []}, {"_id": "01_1", "data": [one]})
    check("database layer: a document already gone → 409", gone["response_status"] == 409, gone)
else:
    print("SKIP the database layer on mongomock (pip install mongomock)")

# ---------------------------------------------------------------- values checked by the GS1 Barcode Syntax Engine (F11)
ENGINE = os.environ.get("GS1_SYNTAX_ENGINE")
if ENGINE:
    import shutil  # noqa: E402
    # the image's own toolkit script, beside the engine of the tests (its import "gs1encoder" resolves there)
    script = os.path.join(ENGINE, "_data_entry_check.mjs")
    shutil.copyfile(os.path.join(REPO, "data_entry_server", "src", "gs1-digitallink-toolkit", "callGS1encoder.js"), script)
    data_entry_logic.TOOLKIT = script
    STORE.clear()
    for name, doc, good in [
            ("a GTIN with a wrong check digit", entry("/01/09506000134353"), False),
            ("a GTIN of 13 digits", entry("/01/9506000134352"), False),
            ("a batch longer than 20 characters", entry(qualifiers=[{"10": "B" * 21}]), False),
            ("a serial with a character outside the set (é)", entry(qualifiers=[{"21": "Sé1"}]), False),
            ("an informative batch too long", entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"10": "B" * 21}]), False),
            ("an SSCC with a wrong check digit", entry("/00/095060001343520001"), False),
            ("a valid GTIN with variant and batch", entry(qualifiers=[{"22": "V1"}, {"10": "B1"}]), True),
            ("a batch with brackets and other characters of the set", entry(qualifiers=[{"10": "A(1)-B/2+%"}]), True),
            ("a template batch (left out of the check)", entry(qualifiers=[{"10": "{lotnumber}"}]), True),
            ("a valid SSCC", entry("/00/095060001343520000"), True),
            ("a valid GLN with extension", entry("/414/9506000134376", qualifiers=[{"254": "D1"}]), True)]:
        r = post(doc)
        if good:
            check(f"engine: POST /new accepts {name}", r.status_code in (200, 201), r.get_data(as_text=True))
        else:
            error = (r.get_json(silent=True) or {}).get("error", "")
            check(f"engine: POST /new refuses {name} → 400, saying so", r.status_code == 400 and "not valid GS1 data" in error,
                  (r.status_code, error))
    r = post([entry(qualifiers=[{"10": "B2"}]), entry("/01/09506000134353")])
    check("engine: a list with one invalid item refused whole, naming it", r.status_code == 400
          and "Item 2" in r.get_json().get("error", ""), r.get_data(as_text=True))
    r = client.put("/api/01/09506000134352", json={"qualifiers": [{"22": "V1"}, {"10": "B1"}],
                                                    "informativeQualifiers": []}, headers=AUTH)
    check("engine: PUT of a valid record accepted", r.status_code == 200, r.get_data(as_text=True))
    post(entry(qualifiers=[{"21": "S7"}]))
    r = client.put("/api/01/09506000134352", json={"qualifiers": [{"21": "S7"}],
                                                    "informativeQualifiers": [{"10": "B" * 21}]}, headers=AUTH)
    check("engine: PUT refuses an invalid value (an informative batch too long) → 400", r.status_code == 400
          and "not valid GS1 data" in r.get_json().get("error", ""), r.get_data(as_text=True))
    data_entry_logic.TOOLKIT = os.path.join(ENGINE, "missing-script.mjs")
    r = post(entry("/01/09506000134353"))
    check("without the engine (no script): values not checked, as before", r.status_code in (200, 201), r.status_code)
else:
    print("SKIP values checked by the GS1 Barcode Syntax Engine (set GS1_SYNTAX_ENGINE)")

# ---- The browser's rules (ADR 0038, finding F-021) ----
r = client.get("/api/docs")
csp = r.headers.get("Content-Security-Policy", "")
check("CSP: the Swagger UI calls and loads nothing outside this origin, and nothing frames it",
      "default-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
      and "object-src 'none'" in csp and "base-uri 'none'" in csp and "https:" not in csp, csp)
check("…no type guessed", r.headers.get("X-Content-Type-Options") == "nosniff", dict(r.headers))
for path, headers in [("/api/index", AUTH), ("/api/swagger.json", {}), ("/api/heartbeat", {})]:
    r = client.get(path, headers=headers)
    check(f"CSP: GET {path} may load nothing", r.headers.get("Content-Security-Policy") ==
          "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
          and r.headers.get("X-Content-Type-Options") == "nosniff", (r.status_code, r.headers.get("Content-Security-Policy")))
try:
    import threading
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, client.application, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        refused = []
        page.on("console", lambda m: refused.append(m.text) if "Content Security Policy" in m.text else None)
        page.goto(f"http://127.0.0.1:{server.server_port}/api/docs")
        page.wait_for_selector(".swagger-ui .info .title", timeout=15000)
        check("Chromium: the Swagger UI starts under its policy and reads the description",
              "GS1 Resolver Community Edition API" in page.inner_text(".swagger-ui .info .title")
              and page.locator(".opblock-tag").count() > 0, page.inner_text(".swagger-ui .info"))
        check("Chromium: the policy refused nothing on the Swagger UI", not refused, refused[:3])
        browser.close()
    server.shutdown()
except Exception as exc:  # noqa: BLE001  (a browser that cannot start is a failure, not a skip)
    check("Chromium: the Swagger UI under its policy", False, repr(exc))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
