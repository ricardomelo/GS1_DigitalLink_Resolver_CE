"""
Development test for the data entry API's token protection (no Docker, no MongoDB).

Builds the real data entry application with the database layer replaced by an in-memory stub and
checks, through Flask's test client:
  * every data entry operation except /heartbeat refuses requests without a token (401) or with a
    wrong token (403), including /index and /summary;
  * the Swagger description declares the BearerAuth scheme on every protected operation, so the
    "Authorize" button of /api/docs sends the token with them.

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

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
