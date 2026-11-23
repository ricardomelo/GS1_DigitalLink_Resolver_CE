"""
The strict mode for safety-critical link types in the resolver (Documentation/adr/0022-answering-level.md, section
2.4): off by default (the standard's walk-up); on for an organisation (its prefixes, the longest first) or for the
operator's scope (keys no organisation holds); a request for one of the five types with a batch or serial number is
answered only by a record naming that batch or serial number, else 404 with Resolution-Match: withheld, the request
log's outcome "withheld", and in a browser the error page with the links available and the notice; the batch's record,
other link types, the default link, the linkset and requests without a batch or serial unchanged; the setting read
again after the cache and kept when the database fails. No Docker, no MongoDB: documents are authored with the real
data entry code and resolved with the real web server code through Flask's test client; the portal's settings are in
mongomock.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_strict_resolver.py
"""
import copy
import importlib
import os
import sys
import types

import mongomock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))

# ---------------------------------------------------------------- stubs and authoring (as test_resolver.py)
fake_mongo = types.ModuleType("mongo_db_init")
fake_mongo.mongo = None
fake_mongo.init_mongo = lambda app: None
sys.modules["mongo_db_init"] = fake_mongo
sys.path.insert(0, os.path.join(REPO, "data_entry_server", "src"))
sys.modules["data_entry_db"] = types.ModuleType("data_entry_db")
data_entry = importlib.import_module("data_entry_logic")
DB = {}


def author(doc):
    result = data_entry._author_db_linkset_document(doc)
    assert result["response_status"] == 200, result
    document = result["data"]
    if document["_id"] in DB:
        DB[document["_id"]]["data"].extend(document["data"])
    else:
        DB[document["_id"]] = document


sys.path.pop(0)
sys.modules.pop("data_entry_logic")
sys.path.insert(0, os.path.join(REPO, "web_server", "src"))
web_db = types.ModuleType("web_db")
web_db.read_document = lambda anchor: (
    {"response_status": 200, "data": copy.deepcopy(DB[anchor.replace("/", "_").lstrip("_")])}
    if anchor.replace("/", "_").lstrip("_") in DB else {"response_status": 404, "error": "nf"})
sys.modules["web_db"] = web_db
os.environ["FQDN"] = "id.example.org"
os.environ["MONGO_URI"] = "mongodb://unused"
os.environ.pop("PORTAL_DB_NAME", None)
import web_logic  # noqa: E402
import request_log  # noqa: E402
import domains  # noqa: E402
import forwarding  # noqa: E402
import resolution  # noqa: E402

web_logic._call_gs1_toolkit = lambda s: "X" not in s        # an X stands for an invalid check digit
web_logic.uncompress_gs1_digital_link = lambda link: (
    {"SUCCESS": True, "identifiers": [{"01": "09506000134376"}], "qualifiers": [{"10": "B/1"}]} if link == "UnKnOwN"
    else {"SUCCESS": False, "error": "not compressed"})
EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
PORTAL = mongomock.MongoClient()["resolver_portal"]
domains.MAP.database = lambda: PORTAL
forwarding.FORWARDING.database = lambda: PORTAL
resolution.STRICT.database = lambda: PORTAL
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)



G = "/01/09506000134369"          # an organisation's key (prefix 950600)
OP = "/01/07891234500014"         # a key no organisation holds (the operator's)


def link(linktype, href):
    return {"linktype": linktype, "href": href, "title": linktype, "type": "text/html", "hreflang": ["pt"]}


author({"anchor": G, "itemDescription": "Amoxicillin", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://pharma.example.com/product"), link("gs1:recallStatus", "https://pharma.example.com/no-recall"),
    link("gs1:epil", "https://pharma.example.com/leaflet"), link("gs1:safetyInfo", "https://pharma.example.com/safety"),
    link("gs1:smpc", "https://pharma.example.com/smpc"), link("gs1:eifu", "https://pharma.example.com/eifu"),
    link("gs1:certificationInfo", "https://pharma.example.com/cert")]})
author({"anchor": G, "qualifiers": [{"10": "LOTA"}], "itemDescription": "Batch A", "defaultLinktype": "gs1:recallStatus",
        "links": [link("gs1:recallStatus", "https://pharma.example.com/recall-lota")]})
author({"anchor": G, "qualifiers": [{"22": "V1"}], "itemDescription": "Variant", "defaultLinktype": "gs1:smpc",
        "links": [link("gs1:smpc", "https://pharma.example.com/smpc-v1")]})
author({"anchor": G, "qualifiers": [{"21": "S9"}], "itemDescription": "Unit", "defaultLinktype": "gs1:eifu",
        "links": [link("gs1:eifu", "https://pharma.example.com/eifu-s9")]})
G2 = "/01/09506001000016"         # prefix 9506001: another organisation
author({"anchor": G2, "itemDescription": "Other", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://other.example.com/product"), link("gs1:recallStatus", "https://other.example.com/r")]})
author({"anchor": OP, "itemDescription": "Operator", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://op.example.com/product"), link("gs1:recallStatus", "https://op.example.com/no-recall")]})


def settings(tenant=None, operator=None):
    """The strict mode: tenant True/False/None (the field absent) for the organisation holding 950600, operator
    {"enabled": …} or None."""
    PORTAL["tenants"].delete_many({})
    PORTAL["settings"].delete_many({"_id": resolution.SETTING_STRICT})
    doc = {"_id": "pharma", "prefixes": ["950600"]}
    if tenant is not None:
        doc[resolution.TENANT_FIELD] = tenant
    PORTAL["tenants"].insert_one(doc)
    PORTAL["tenants"].insert_one({"_id": "other", "prefixes": ["9506001"], resolution.TENANT_FIELD: not tenant})
    if operator is not None:
        PORTAL["settings"].insert_one({"_id": resolution.SETTING_STRICT, "value": operator})
    resolution.STRICT.forget()
    domains.MAP.forget()


def ask(path, method="GET", accept="*/*", **headers):
    """One request; returns (response, the event it produced)."""
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.open("/api" + path, method=method, headers={"Accept": accept, "User-Agent": "Mozilla/5.0 "
                           "(iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148", **headers})
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else {})


def where(r):
    """(status, the target without the query string passed on, Resolution-Match)."""
    location = r.headers.get("Location")
    return r.status_code, location.split("?")[0] if location else None, r.headers.get("Resolution-Match")


RECALL = "?linkType=gs1:recallStatus"

# ---------------------------------------------------------------- off: the standard's walk-up
settings()
r, e = ask(G + "/10/LOTB" + RECALL)
check("off by default: a batch without a record receives the product's recall link (walk-up)",
      where(r) == (307, "https://pharma.example.com/no-recall", "walk-up") and e.get("o") == "redirect", (where(r), e))
settings(tenant=False, operator={"enabled": False})
check("…switched off explicitly: the same", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 307)

# ---------------------------------------------------------------- on for the organisation
settings(tenant=True)
r, e = ask(G + "/10/LOTB" + RECALL)
check("on: a batch without its own recall link is withheld: 404, Resolution-Match: withheld, no Location",
      where(r) == (404, None, "withheld") and r.headers.get("Resolution-Anchor") is None, (where(r), dict(r.headers)))
check("…the request log: outcome withheld, the level that holds the link", (e.get("o"), e.get("s")) == ("withheld", 404),
      e)
check("…the JSON body says why", "error" in (r.get_json(silent=True) or {}), r.data[:200])
r, _ = ask(G + "/10/LOTA" + RECALL)
check("…the batch's own record answers, exact", where(r) == (307, "https://pharma.example.com/recall-lota", "exact"),
      where(r))
r, _ = ask(G + "/10/LOTA/21/S1" + RECALL)
check("…a serial within a batch: the batch's record may answer", where(r)[:2] == (307, "https://pharma.example.com/recall-lota"),
      where(r))
r, _ = ask(G + "/21/S1" + RECALL)
check("…a serial alone is never answered by the product", where(r) == (404, None, "withheld"), where(r))
r, _ = ask(G + "/21/S9?linkType=gs1:eifu")
check("…the unit's own record answers its serial", where(r)[:2] == (307, "https://pharma.example.com/eifu-s9"), where(r))
r, _ = ask(G + "/10/lota" + RECALL)
check("…a batch value differing in case is another batch: withheld", where(r)[0] == 404, where(r))
for term in ("safetyInfo", "epil", "smpc", "eifu"):
    r, _ = ask(G + "/10/LOTB?linkType=gs1:" + term)
    check(f"…{term} is safety-critical: withheld", where(r) == (404, None, "withheld"), where(r))
r, _ = ask(G + "/10/LOTB?linkType=https://gs1.org/voc/recallStatus")
check("…the link type in its URI form too", where(r)[0] == 404, where(r))
r, _ = ask(G + "/22/V1/10/LOTB?linkType=gs1:smpc")
check("…a variant's record does not name the batch: withheld", where(r) == (404, None, "withheld"), where(r))
r, _ = ask(G + "/10/LOTB?linkType=gs1:certificationInfo")
check("…another link type walks up as before", where(r) == (307, "https://pharma.example.com/cert", "walk-up"), where(r))
r, _ = ask(G + "/10/LOTB")
check("…the default link (a plain scan) walks up as before", where(r)[:2] == (307, "https://pharma.example.com/product"),
      where(r))
r, _ = ask(G + RECALL)
check("…the product itself, without batch or serial, answers", where(r) == (307, "https://pharma.example.com/no-recall",
      "exact"), where(r))
r, _ = ask(G + "/10/LOTB?linkType=linkset", accept="application/linkset+json")
check("…the linkset is unchanged (each level with its own anchor)", r.status_code == 200
      and "recallStatus" in r.get_data(as_text=True), r.status_code)
r, _ = ask(G + "/10/LOTB?linkType=gs1:recipeInfo")
check("…a type nobody registered stays a plain 404, without the header", where(r) == (404, None, None), where(r))
r, _ = ask(G + "/10/LOTB" + RECALL, method="HEAD")
check("…HEAD: 404 withheld too", where(r) == (404, None, "withheld"), where(r))
r, _ = ask(OP + "/10/Q1" + RECALL)
check("…the operator's keys are not affected by an organisation's setting", where(r)[0] == 307, where(r))
r, _ = ask(G2 + "/10/Q1" + RECALL)
check("…the longest prefix decides: 9506001 belongs to another organisation, switched off", where(r)[0] == 307,
      where(r))

# ---------------------------------------------------------------- the browser's page
r, e = ask(G + "/10/LOTB" + RECALL, accept="text/html", **{"Accept-Language": "en-GB"})
page = r.get_data(as_text=True)
check("a browser: 404 page with the header", where(r) == (404, None, "withheld") and "text/html" in r.content_type,
      where(r))
check("…its own title, naming the batch and the type asked", "Information not available for this batch or item" in page
      and "Batch/lot LOTB" in page and "Recall" in page, page[:600])
check("…the notice: the links shown belong to the product", "level-notice" in page and "Product (every unit)" in page,
      page[:600])
check("…the product's links stay reachable", "https://pharma.example.com/no-recall" in page
      and "https://pharma.example.com/leaflet" in page)
r, _ = ask(G + "/10/LOTB" + RECALL, accept="text/html", **{"Accept-Language": "pt-BR"})
check("…in the visitor's language", "Informação não disponível para este lote ou item" in r.get_data(as_text=True))
r, _ = ask(G + "/10/LOTB?linkType=gs1:recipeInfo", accept="text/html", **{"Accept-Language": "en-GB"})
page = r.get_data(as_text=True)
check("…a type nobody registered keeps the page of a missing type, without the notice",
      r.status_code == 404 and "level-notice" not in page and "This product has no" in page, page[:600])

# ---------------------------------------------------------------- the operator's scope
settings(tenant=False, operator={"enabled": True})
check("the operator's scope: its keys withheld", where(ask(OP + "/10/Q1" + RECALL)[0]) == (404, None, "withheld"))
check("…an organisation switched off is not affected", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 307)
settings(tenant=None, operator={"enabled": True})
check("…an organisation that never set it stays off", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 307)

# ---------------------------------------------------------------- the settings, read again
settings(tenant=True)
ask(G + "/10/LOTB" + RECALL)                                  # read once
PORTAL["tenants"].update_one({"_id": "pharma"}, {"$set": {resolution.TENANT_FIELD: False}})
check("a change is seen after the cache (within CACHE_SECONDS)", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 404)
resolution.STRICT.forget()
check("…and then applied", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 307)
settings(tenant=True)
ask(G + "/10/LOTB" + RECALL)


def broken():
    raise RuntimeError("database down")


resolution.STRICT.database = broken
resolution.STRICT.forget()
check("a database that does not answer: the last settings kept", where(ask(G + "/10/LOTB" + RECALL)[0])[0] == 404)
resolution.STRICT.database = lambda: PORTAL
check("the five safety-critical types of ADR 0022, read at most every minute",
      resolution.SAFETY_CRITICAL == ("recallStatus", "safetyInfo", "epil", "smpc", "eifu")
      and resolution.CACHE_SECONDS <= 60)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
