"""
The tenant API and its keys (Documentation/adr/0005-tenant-api.md) through the portal's Flask test client, against
the in-memory stand-in for the data entry API: keys created, listed and revoked by administrators in their own scope;
the key's format and storage; authentication, scopes, prefixes, organisations and the operator; records listed,
read, written and deleted and labels made through /portal/api/v1, with the portal's rules and journal; revoked,
expired and disabled keys; the request limit; the e-mail notices of a new key and of a key about to expire (the
worker's housekeeping); the OpenAPI description checked against the routes and the answers; the messages of both
languages.

Runs against mongomock unless PORTAL_DB_URI names a real MongoDB (the CI job "database" does that).

  pip install -r portal/requirements.txt mongomock jsonschema
  python dev-tests/portal/test_api.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import timedelta

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3396
sys.path[:0] = [HERE, PORTAL]

from fake_smtp import FakeRelay  # noqa: E402

relay = FakeRelay().start()
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", RESOLVER_ORG_NAME="Example Operator",
                  PORTAL_MAIL_HOST="127.0.0.1", PORTAL_MAIL_PORT=str(relay.port), PORTAL_MAIL_SECURITY="none",
                  PORTAL_MAIL_FROM="portal@example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_api_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "embedded"

import jsonschema  # noqa: E402
import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False, email="root@example.org")
import app as portal  # noqa: E402
import apikeys  # noqa: E402
import journal  # noqa: E402
import tenants  # noqa: E402
import worker  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}
V1 = "/portal/api/v1"


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def gtin(body13: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


def api(method, path, key=None, **kw):
    headers = dict(kw.pop("headers", {}))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return getattr(portal.app.test_client(), method)(V1 + path, headers=headers, **kw)


def body(description="Item", url="https://example.org/x", extra=()):
    return {"description": description,
            "links": [{"linkType": "gs1:pip", "url": url, "title": "Info", "hreflang": ["en"]}, *extra]}


def wait_messages(count, timeout=6.0):
    end = time.monotonic() + timeout
    while len(relay.messages) < count and time.monotonic() < end:
        time.sleep(0.05)
    return list(relay.messages)


ACME_A = gtin("0789123450001")      # Acme, prefix 7891234, inside 78912345
ACME_B = gtin("0789123410001")      # Acme, prefix 7891234, outside 78912345
OPER = gtin("0950600013435")        # the operator's

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False, email="ana@acme.example")
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
root, ana, edu = client("root", "root-password-long"), client("ana", "ana-password-long"), client("edu", "edu-password-long")

# ================================================================== keys in the portal
check("an editor cannot list or create keys", edu.get("/portal/api/keys").status_code == 403
      and code(edu.post("/portal/api/keys", json={"name": "x", "scopes": ["records:read"]}, headers=ORIGIN)) == "access.role")
r = ana.post("/portal/api/keys", json={"name": "  ERP   integration ", "scopes": ["records:write", "records:read", "labels:read"],
                                       "days": 30}, headers=ORIGIN)
data = r.get_json() or {}
ana_key, ana_item = data.get("key", ""), data.get("item", {})
check("a tenant administrator creates a key: 201, the full key once", r.status_code == 201 and code(r) == "apikeys.created"
      and re.fullmatch(r"rk_[0-9a-f]{12}\.[A-Za-z0-9_-]{43}", ana_key) is not None, data)
check("the key's item: tidy name, sorted scopes, 30 days, no hash", ana_item.get("name") == "ERP integration"
      and ana_item.get("scopes") == ["labels:read", "records:read", "records:write"] and "hash" not in ana_item
      and ana_item.get("state") == "active" and ana_item.get("createdBy") == "ana", ana_item)
stored = store.col("api_keys").find_one({"_id": ana_item.get("id")})
secret = ana_key.split(".", 1)[1] if "." in ana_key else "?"
check("only the secret's SHA-256 is stored, under the organisation", stored and stored["hash"] != secret
      and len(stored["hash"]) == 64 and secret not in json.dumps(stored, default=str) and stored.get("tenant") == acme["id"])
check("expiry: 30 days from now", abs((stored["expiresAt"] - stored["created"]) - timedelta(days=30)) < timedelta(seconds=2))
listed = ana.get("/portal/api/keys").get_json()
check("list: the organisation's keys, the scopes, the limits", [k["id"] for k in listed["keys"]] == [ana_item["id"]]
      and listed["scopes"] == list(apikeys.SCOPES) and listed["maxDays"] == 365 and listed["defaultDays"] == 90
      and listed["ratePerMinute"] == 120 and "key" not in json.dumps(listed["keys"]).replace('"keys"', ""), listed)
for payload, expected in [({"name": "ab", "scopes": ["records:read"]}, "apikeys.nameInvalid"),
                          ({"name": "No scope", "scopes": []}, "apikeys.scopesInvalid"),
                          ({"name": "Bad scope", "scopes": ["admin"]}, "apikeys.scopesInvalid"),
                          ({"name": "Zero", "scopes": ["records:read"], "days": 0}, "apikeys.daysInvalid"),
                          ({"name": "Too long", "scopes": ["records:read"], "days": 366}, "apikeys.daysInvalid"),
                          ({"name": "erp INTEGRATION", "scopes": ["records:read"]}, "apikeys.nameExists"),
                          ({"name": "Outside", "scopes": ["records:read"], "prefixes": ["7895555"]}, "users.prefixOutsideTenant")]:
    check(f"refused: {expected} ({payload['name']})", code(ana.post("/portal/api/keys", json=payload, headers=ORIGIN)) == expected)
os.environ["PORTAL_API_KEY_MAX_DAYS"] = "180"
check("the longest validity follows PORTAL_API_KEY_MAX_DAYS", code(ana.post("/portal/api/keys", json={
    "name": "Half year", "scopes": ["records:read"], "days": 181}, headers=ORIGIN)) == "apikeys.daysInvalid")
del os.environ["PORTAL_API_KEY_MAX_DAYS"]
r = ana.post("/portal/api/keys", json={"name": "Reader", "scopes": ["records:read"]}, headers=ORIGIN)
read_key, read_id = r.get_json()["key"], r.get_json()["item"]["id"]
check("default validity: 90 days", r.get_json()["item"]["expiresAt"][:10]
      == store.iso(store.now() + timedelta(days=90))[:10])
narrow_key = ana.post("/portal/api/keys", json={"name": "Narrow", "scopes": ["records:read", "records:write"],
                                                "prefixes": ["78912345"]}, headers=ORIGIN).get_json()["key"]
r = root.post("/portal/api/keys", json={"name": "Operator sync", "scopes": ["records:read", "records:write"]}, headers=ORIGIN)
oper_key, oper_id = r.get_json()["key"], r.get_json()["item"]["id"]
check("a server administrator creates keys for the operator", r.status_code == 201
      and "tenant" not in store.col("api_keys").find_one({"_id": oper_id}))
check("each administrator lists only his own scope's keys",
      [k["name"] for k in root.get("/portal/api/keys").get_json()["keys"]] == ["Operator sync"]
      and {k["name"] for k in ana.get("/portal/api/keys").get_json()["keys"]} == {"ERP integration", "Reader", "Narrow"})
check("an operator key may not be limited to an organisation's prefix", code(root.post("/portal/api/keys", json={
    "name": "Into Acme", "scopes": ["records:read"], "prefixes": ["7891234"]}, headers=ORIGIN)) == "users.prefixOfTenant")
check("nobody revokes another scope's key", code(root.delete(f"/portal/api/keys/{ana_item['id']}", headers=ORIGIN)) == "apikeys.unknown"
      and code(ana.delete(f"/portal/api/keys/{oper_id}", headers=ORIGIN)) == "apikeys.unknown")
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7: keys"}, headers=ORIGIN)
check("during support access the server administrator still sees the operator's keys only",
      [k["name"] for k in root.get("/portal/api/keys").get_json()["keys"]] == ["Operator sync"])
root.delete("/portal/api/support", headers=ORIGIN)
events = ana.get("/portal/api/audit").get_json()["events"]
check("journal: api-key-create in the organisation's trail, by its administrator",
      sum(1 for e in events if e["action"] == "api-key-create") == 3
      and all(not e.get("byOperator") for e in events if e["action"] == "api-key-create")
      and ana_item["id"] in next(e["detail"] for e in events if e["action"] == "api-key-create" and "ERP" in e["detail"]))
check("…and the operator's key in the operator's trail", any(e["action"] == "api-key-create" and oper_id in e["detail"]
                                                            for e in root.get("/portal/api/audit").get_json()["events"]))
messages = wait_messages(4)
created_mail = [m for m in messages if m["Subject"] in ("A new API key was created", "Uma nova chave de API foi criada")]
check("the creator is told by e-mail of each key (ana's three, root's one)",
      sorted(m["To"] for m in created_mail) == ["ana@acme.example"] * 3 + ["root@example.org"], [m["To"] for m in messages])
text = next(m for m in created_mail if "ERP integration" in m.get_body(("plain",)).get_content()).get_body(("plain",)).get_content()
check("…naming the key, its id, the organisation and the scopes, never the secret",
      ana_item["id"] in text and "Acme Foods" in text and "records:write" in text and secret not in text)

beta = tenants.create("Beta", ["7898357"], "root")
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
bia = client("bia", "bia-password-long")
answers = [bia.post("/portal/api/keys", json={"name": f"Key {n:02d}", "scopes": ["records:read"]}, headers=ORIGIN).status_code
           for n in range(apikeys.MAX_ACTIVE_KEYS)]
r = bia.post("/portal/api/keys", json={"name": "One too many", "scopes": ["records:read"]}, headers=ORIGIN)
check("at most 20 active keys per organisation", answers == [201] * 20 and code(r) == "apikeys.tooMany")
bia.delete(f"/portal/api/keys/{bia.get('/portal/api/keys').get_json()['keys'][0]['id']}", headers=ORIGIN)
check("…a revoked key frees a place", bia.post("/portal/api/keys", json={"name": "One too many", "scopes": ["records:read"]},
                                               headers=ORIGIN).status_code == 201)

# ================================================================== authentication
r = api("get", "/")
check("no key: 401 api.keyMissing with a Bearer challenge", r.status_code == 401 and code(r) == "api.keyMissing"
      and r.headers.get("WWW-Authenticate", "").startswith("Bearer"))
for bad in ("rk_nothing", "Basic abc", ana_key[:-1] + ("A" if ana_key[-1] != "A" else "B"), "rk_000000000000." + "x" * 43):
    r = api("get", "/", headers={"Authorization": bad if bad.startswith("Basic") else f"Bearer {bad}"})
    check(f"a wrong key is refused ({bad[:14]}…)", r.status_code == 401 and code(r) in ("api.keyInvalid", "api.keyMissing"))
r = api("get", "/", ana_key)
who = r.get_json() or {}
check("who am I: the key, its organisation, the limit", r.status_code == 200 and who["key"]["id"] == ana_item["id"]
      and who["organisation"] == "Acme Foods" and who["rateLimit"]["perMinute"] == 120, who)
check("GET /portal/api/v1 (no slash) goes to the same place", api("get", "", ana_key).status_code in (301, 308))
r = api("get", "/openapi.json")
spec = r.get_json() or {}
check("the OpenAPI description is public, with this installation as its server", r.status_code == 200
      and spec.get("openapi") == "3.1.0" and spec["servers"] == [{"url": "https://id.example.org/portal/api/v1"}])
check("the session API is not reachable with a key", portal.app.test_client().get(
    "/portal/api/records", headers={"Authorization": f"Bearer {ana_key}"}).status_code == 401)
check("a portal session does not reach the key API", ana.get(V1 + "/").status_code == 401)

# ================================================================== records through the API
r = api("put", f"/records/01/{ACME_A}", ana_key, json=body("Coffee 500 g"))
check("PUT a new record: 201 save.created with its Digital Link", r.status_code == 201 and code(r) == "save.created"
      and r.get_json()["created"] is True and r.get_json()["digitalLink"] == f"https://id.example.org/01/{ACME_A}", r.get_json())
check("…stored by the data entry API", mock_data_entry.DB.get(f"01_{ACME_A}", {}).get("entries", [{}])[0].get(
    "itemDescription") == "Coffee 500 g")
r = api("put", f"/records/01/{ACME_A}", ana_key, json=body("Coffee 500 g", extra=[
    {"linkType": "gs1:recipeInfo", "url": "https://example.org/r", "hreflang": ["pt"]}]))
check("PUT again: 200 save.updated", r.status_code == 200 and code(r) == "save.updated" and r.get_json()["created"] is False)
r = api("put", f"/records/01/{ACME_A}?qualifiers=/10/L1", ana_key, json=body("Coffee batch L1"))
check("PUT a qualified record", r.status_code == 201 and r.get_json()["digitalLink"].endswith("/10/L1"))
check("a GTIN-13 is stored as GTIN-14", api("put", f"/records/01/{ACME_B[1:]}", ana_key, json=body("Tea")).status_code == 201
      and f"01_{ACME_B}" in mock_data_entry.DB)
r = api("put", f"/records/01/{ACME_A[:-1]}0" if ACME_A[-1] != "0" else f"/records/01/{ACME_A[:-1]}1", ana_key, json=body())
check("GS1 rules apply: a wrong check digit, 422", r.status_code == 422 and code(r) == "gtin.checkDigit", r.get_json())
check("no links: 422 links.required", code(api("put", f"/records/01/{ACME_A}", ana_key, json={"description": "x"})) == "links.required")
check("no description: 422 description.required",
      code(api("put", f"/records/01/{ACME_A}", ana_key, json={"links": body()["links"]})) == "description.required")
check("a body that is not JSON: 415", api("put", f"/records/01/{ACME_A}", ana_key, data="x",
                                         content_type="text/plain").status_code == 415)
r = api("put", f"/records/01/{OPER}", ana_key, json=body("Not ours"))
check("another owner's record: 403 access.prefix, nothing written", r.status_code == 403 and code(r) == "access.prefix"
      and f"01_{OPER}" not in mock_data_entry.DB)
r = api("put", f"/records/01/{ACME_A}", ana_key, json=body(), headers={"Origin": "https://evil.example"})
check("a browser request from another site is refused (no CORS)", r.status_code == 403 and code(r) == "request.forbiddenOrigin")
change = journal.search(user=f"api:{ana_item['id']}")
check("journal: the changes are record events of the organisation, user api:<key id>",
      {e["action"] for e in change} == {"create", "update"} and all(e.get("tenant") == acme["id"] for e in change)
      and not any(e.get("byOperator") for e in change), [(e["action"], e.get("tenant")) for e in change])
r = api("get", f"/records/01/{ACME_A}", ana_key)
rec = r.get_json() or {}
check("GET a record: description, links with the default first, its Digital Link", r.status_code == 200
      and rec["description"] == "Coffee 500 g" and [l["linkType"] for l in rec["links"]] == ["gs1:pip", "gs1:recipeInfo"]
      and rec["defaultLinkType"] == "gs1:pip" and rec["qualifiers"] == "" and rec["digitalLink"].endswith(ACME_A), rec)
r = api("get", f"/records/01/{ACME_A}?qualifiers=/10/L9", ana_key)
check("GET unknown qualifiers: 404 record.notFound", r.status_code == 404 and code(r) == "record.notFound")
r = api("get", "/records", ana_key)
page = r.get_json() or {}
check("list: the organisation's records only, sorted", r.status_code == 200 and page["total"] == 3
      and [x["value"] for x in page["records"]] == sorted([ACME_A, ACME_A, ACME_B])
      and page["next"] is None and {x["qualifiers"] for x in page["records"]} == {"", "/10/L1"}, page)
first = api("get", "/records?limit=2", ana_key).get_json()
second = api("get", f"/records?limit=2&after={first['next']}", ana_key).get_json()
check("list in pages: limit and after", len(first["records"]) == 2 and first["next"] == first["records"][-1]["id"]
      and len(second["records"]) == 1 and second["next"] is None)
check("list: limit out of range is 422 api.limit", code(api("get", "/records?limit=0", ana_key)) == "api.limit"
      and code(api("get", "/records?limit=1001", ana_key)) == "api.limit")
check("list: filter by key", api("get", "/records?key=00", ana_key).get_json()["total"] == 0)
r = api("get", f"/labels/01/{ACME_A}?qualifiers=/10/L1", ana_key)
check("label: SVG with the QR headers", r.status_code == 200 and r.mimetype == "image/svg+xml"
      and r.headers.get("X-QR-Version") and b"<svg" in r.data[:300])
r = api("get", f"/labels/01/{ACME_A}?format=png&attr=17:261231", ana_key)
check("label: PNG download with a data attribute", r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n"
      and "attachment" in r.headers.get("Content-Disposition", ""))
r = api("delete", f"/records/01/{ACME_A}?qualifiers=/10/L1", ana_key)
check("DELETE a record: 200, the key's own record stays", r.status_code == 200 and code(r) == "delete.done"
      and api("get", f"/records/01/{ACME_A}", ana_key).status_code == 200)
check("DELETE it again: 404", api("delete", f"/records/01/{ACME_A}?qualifiers=/10/L1", ana_key).status_code == 404)

# ================================================================== scopes, prefixes, the operator
r = api("put", f"/records/01/{ACME_A}", read_key, json=body())
check("a read-only key cannot write: 403 api.scope", r.status_code == 403 and code(r) == "api.scope"
      and r.get_json()["params"] == {"scope": "records:write"})
check("…nor make labels without labels:read", code(api("get", f"/labels/01/{ACME_A}", read_key)) == "api.scope")
check("…but reads", api("get", f"/records/01/{ACME_A}", read_key).status_code == 200)
check("a key limited to 78912345 reaches its records, not the rest of the organisation",
      api("get", f"/records/01/{ACME_A}", narrow_key).status_code == 200
      and code(api("get", f"/records/01/{ACME_B}", narrow_key)) == "access.prefix"
      and api("get", "/records", narrow_key).get_json()["total"] == 1)
r = api("put", f"/records/01/{OPER}", oper_key, json=body("Operator item"))
check("an operator key writes the operator's records", r.status_code == 201)
check("…and not the organisation's", code(api("get", f"/records/01/{ACME_A}", oper_key)) == "access.prefix"
      and api("get", "/records", oper_key).get_json()["total"] == 1)
check("the operator key's change is in the operator's trail", any(
    e["action"] == "create" and not e.get("tenant") for e in journal.search(user=f"api:{oper_id}")))

# ================================================================== revoked, expired, disabled
r = ana.delete(f"/portal/api/keys/{read_id}", headers=ORIGIN)
check("revoke: 200, the key stops at once", r.status_code == 200 and code(r) == "apikeys.revoked"
      and code(api("get", "/", read_key)) == "api.keyInvalid")
item = next(k for k in ana.get("/portal/api/keys").get_json()["keys"] if k["id"] == read_id)
check("…listed as revoked, by whom", item["state"] == "revoked" and item["revokedBy"] == "ana" and item["revoked"])
check("revoking twice: apikeys.alreadyRevoked", code(ana.delete(f"/portal/api/keys/{read_id}", headers=ORIGIN)) == "apikeys.alreadyRevoked")
check("journal: api-key-revoke", any(e["action"] == "api-key-revoke" and read_id in e["detail"]
                                     for e in ana.get("/portal/api/audit").get_json()["events"]))
narrow_id = narrow_key[3:15]
store.col("api_keys").update_one({"_id": narrow_id}, {"$set": {"expiresAt": store.now() - timedelta(seconds=1)}})
check("an expired key is refused and listed as expired", code(api("get", "/", narrow_key)) == "api.keyInvalid"
      and next(k for k in ana.get("/portal/api/keys").get_json()["keys"] if k["id"] == narrow_id)["state"] == "expired")
tenants.update(acme["id"], disabled=True)
check("a key of a disabled organisation is refused", code(api("get", "/", ana_key)) == "api.keyInvalid")
tenants.update(acme["id"], disabled=False)
check("…and works again when it is enabled", api("get", "/", ana_key).status_code == 200)

# ================================================================== the request limit
check("the first request of a minute records the last use", store.col("api_keys").find_one({"_id": ana_item["id"]}).get("lastUsed"))
while int(time.time()) % 60 > 50:          # the five requests below must fall in one minute
    time.sleep(0.5)
os.environ["PORTAL_API_RATE_PER_MINUTE"] = "5"
store.col("api_rate").delete_many({})
answers = [api("get", "/", ana_key) for _ in range(6)]
check("the sixth request of a minute: 429 api.rateLimit with Retry-After",
      [a.status_code for a in answers] == [200] * 5 + [429] and code(answers[-1]) == "api.rateLimit"
      and 1 <= int(answers[-1].headers.get("Retry-After", "0")) <= 60, [a.status_code for a in answers])
check("…another key has its own count", api("get", "/", oper_key).status_code == 200)
check("…counted in the database for every replica", store.col("api_rate").count_documents({}) == 2)
del os.environ["PORTAL_API_RATE_PER_MINUTE"]

# ================================================================== keys about to expire (worker housekeeping)
relay.clear()
soon = ana.post("/portal/api/keys", json={"name": "Short", "scopes": ["records:read"], "days": 3}, headers=ORIGIN).get_json()
wait_messages(1)
relay.clear()
told = portal.notify_expiring_keys()
messages = wait_messages(1)
check("a key expiring within a week: its creator is told once", told == 1 and len(messages) == 1
      and messages[0]["Subject"] in ("An API key expires soon", "Uma chave de API expira em breve")
      and soon["item"]["id"] in messages[0].get_body(("plain",)).get_content(), [m["Subject"] for m in messages])
check("…and not again", portal.notify_expiring_keys() == 0)
ran, failing = [], []
w = worker.Worker({}, "embedded", housekeeping=[lambda: failing.append(1) or 1 / 0, lambda: ran.append(1)])
w.housekeep(force=True)
w.housekeep()
check("the worker runs its housekeeping, a failing task does not stop the others, at most once an hour",
      ran == [1] and failing == [1])
check("the portal's worker has the expiry check", portal.notify_expiring_keys in portal.HOUSEKEEPING
      and portal.EMBEDDED_WORKER.housekeeping == portal.HOUSEKEEPING)

# ================================================================== the description against the code
routes = {}
for rule in portal.app.url_map.iter_rules():
    if rule.rule.startswith(V1):
        path = re.sub(r"<(?:path:)?(\w+)>", r"{\1}", rule.rule[len(V1):]) or "/"
        routes.setdefault(path, set()).update(m.lower() for m in rule.methods - {"HEAD", "OPTIONS"})
documented = {p: {m for m in ops if m in ("get", "put", "post", "delete")} for p, ops in spec["paths"].items()}
check("every route of /portal/api/v1 is described, and every description is a route", routes == documented,
      (routes, documented))
check("every operation has an operationId and its error answers", all(
    op.get("operationId") and (p == "/openapi.json" or "401" in op["responses"])
    for p, ops in spec["paths"].items() for m, op in ops.items() if m in ("get", "put", "delete")))


def valid(instance, name):
    schema = {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
    try:
        jsonschema.Draft202012Validator(schema).validate(instance)
        return True
    except jsonschema.ValidationError as exc:
        print("   ", exc.message)
        return False


check("answers match the description: who am I", valid(api("get", "/", ana_key).get_json(), "WhoAmI"))
check("…a record", valid(api("get", f"/records/01/{ACME_A}", ana_key).get_json(), "Record"))
check("…a list", valid(api("get", "/records?limit=2", ana_key).get_json(), "RecordList"))
check("…a save", valid(api("put", f"/records/01/{ACME_A}", ana_key, json=body("Coffee 500 g")).get_json(), "Saved"))
check("…an error", valid(api("get", "/").get_json(), "Error") and valid(api("get", "/records?limit=0", ana_key).get_json(), "Error"))
check("the request body schema accepts what the API accepts", valid(body(), "RecordInput"))

# ================================================================== messages in both languages
catalogue = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
blocks = re.split(r'\n    "(?:pt-BR|en-GB)": \{', catalogue)[1:]
pt_keys, en_keys = (set(re.findall(r'^      "([^"]+)":', b, re.M)) for b in blocks[:2])
sources = "".join(open(os.path.join(PORTAL, f), encoding="utf-8").read() for f in ("api_v1.py", "apikeys.py", "app.py"))
codes = set(re.findall(r'(?:UserError|ValidationError|message|_refuse)\("((?:api|apikeys)\.[A-Za-z.]+)"', sources))
check("every message code of the API and its keys is translated in both languages",
      codes <= pt_keys & en_keys and len(codes) >= 14, sorted(codes - (pt_keys & en_keys)))
duplicates = {name: sorted({k for k in re.findall(r'^      "([^"]+)":', b, re.M)
                             if re.findall(rf'^      "{re.escape(k)}":', b, re.M).__len__() > 1})
              for name, b in zip(("pt-BR", "en-GB"), blocks[:2])}
check("no message key is written twice in a language (the second would replace the first)",
      duplicates == {"pt-BR": [], "en-GB": []}, duplicates)
check("the journal actions have names", {"audit.action.api-key-create", "audit.action.api-key-revoke"} <= pt_keys & en_keys)
check("the documented codes exist", all(c in pt_keys for c in ("api.keyMissing", "api.keyInvalid", "api.scope",
                                                                "api.rateLimit", "access.prefix", "record.notFound")))

relay.stop()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
