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
    of a serial-number record: stored, returned, listed in /summary, changed and cleared by PUT.

  pip install -r data_entry_server/src/requirements.txt
  python dev-tests/resolver/test_data_entry_api.py
"""
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
db.create_document = lambda doc: (STORE.__setitem__(doc["_id"], copy.deepcopy(doc)), {"response_status": 201})[1]
db.update_document = lambda doc: (STORE.__setitem__(doc["_id"], copy.deepcopy(doc)), {"response_status": 200})[1]
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
r = client.put("/api/01/09506000134352", json={"qualifiers": [{"10": "B1"}], "informativeQualifiers": [{"22": "V1"}]}, headers=AUTH)
check("PUT refuses informative qualifiers on a batch record → 400", r.status_code == 400, r.get_data(as_text=True))
r = post(entry(qualifiers=[{"21": "S1"}], informativeQualifiers=[{"10": "B9"}]))
data = client.get("/api/01/09506000134352", headers=AUTH).get_json()["data"]
check("POST /new on an existing serial record updates its informative qualifiers", any(
    e.get("qualifiers") == [{"21": "S1"}] and e.get("informativeQualifiers") == [{"10": "B9"}] for e in data), data)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
