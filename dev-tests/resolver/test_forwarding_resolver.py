"""
Forwarding in the resolver (Documentation/adr/0018-forwarding.md): the resolver of last resort (a key this resolver
does not know sent to https://id.gs1.org, or the operator's address, with its path and query string; switched off by
default; never a known key, a missing link type or an invalid request) and the prefix rules (every key of a prefix
sent to its destination before this resolver's records, the path kept or a fixed address, the longest prefix first,
GTIN-13, SSCC and GLN, disabled rules ignored, an organisation's own domain limited to its keys), the request log's
outcomes, the settings read again after the cache and kept when the database fails. No Docker, no MongoDB: documents
are authored with the real data entry code and resolved with the real web server code through Flask's test client;
the portal's settings are in mongomock.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_forwarding_resolver.py
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

web_logic._call_gs1_toolkit = lambda s: "X" not in s        # an X stands for an invalid check digit
web_logic.uncompress_gs1_digital_link = lambda link: (
    {"SUCCESS": True, "identifiers": [{"01": "09506000134376"}], "qualifiers": [{"10": "B/1"}]} if link == "UnKnOwN"
    else {"SUCCESS": False, "error": "not compressed"})
EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
PORTAL = mongomock.MongoClient()["resolver_portal"]
domains.MAP.database = lambda: PORTAL
forwarding.FORWARDING.database = lambda: PORTAL
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


KNOWN, BETA = "/01/07891234500014", "/01/07895555000017"
for anchor, host in ((KNOWN, "acme"), (BETA, "beta")):
    author({"anchor": anchor, "itemDescription": host, "defaultLinktype": "gs1:pip", "links": [
        {"linktype": "gs1:pip", "href": f"https://{host}.example.com/product", "title": "P", "type": "text/html",
         "hreflang": ["en"]}]})
UNKNOWN = "/01/09506000134376"


def settings(fallback=None, rules=()):
    """The portal's forwarding settings: fallback {"enabled", "url"} or None; rules (prefix, target, mode, enabled)."""
    PORTAL["settings"].delete_many({"_id": forwarding.SETTING_FALLBACK})
    if fallback is not None:
        PORTAL["settings"].insert_one({"_id": forwarding.SETTING_FALLBACK, "value": fallback})
    PORTAL[forwarding.RULES].delete_many({})
    for prefix, target, mode, enabled in rules:
        PORTAL[forwarding.RULES].insert_one({"_id": prefix, "target": target, "mode": mode, "enabled": enabled})
    forwarding.FORWARDING.forget()
    domains.MAP.forget()


def ask(path, method="GET", accept="text/html", **headers):
    """One request; returns (response, the event it produced)."""
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.open("/api" + path, method=method, headers={"Accept": accept, "User-Agent": "Mozilla/5.0 "
                           "(iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148", **headers})
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else {})


# ---------------------------------------------------------------- the resolver of last resort
settings()
r, e = ask(UNKNOWN)
check("nothing set: a key nobody registered is a 404, as before", r.status_code == 404 and e.get("o") == "unknown",
      (r.status_code, e))
settings(fallback={"enabled": False, "url": "https://other.example.net"})
check("…the resolver of last resort switched off: 404", ask(UNKNOWN)[0].status_code == 404)
settings(fallback={"enabled": True})
r, e = ask(UNKNOWN + "/10/ABC?linkType=gs1:pip&17=261231")
check("switched on without an address: to https://id.gs1.org, the path and the query string kept",
      r.status_code == 307 and r.headers["Location"]
      == "https://id.gs1.org/01/09506000134376/10/ABC?linkType=gs1:pip&17=261231", (r.status_code, dict(r.headers)))
check("…the request log: outcome fallback, the destination's host", (e.get("o"), e.get("s"), e.get("to"))
      == ("fallback", 307, "id.gs1.org"), e)
settings(fallback={"enabled": True, "url": "https://resolver.example.net/gs1/"})
r, _ = ask("/01/9506000134376/10/A%2FB")
check("the operator's address, its trailing slash not doubled; a GTIN-13 as GTIN-14, a '/' in a value kept encoded",
      r.status_code == 307 and r.headers["Location"] == "https://resolver.example.net/gs1/01/09506000134376/10/A%2FB",
      r.headers.get("Location"))
r, e = ask(KNOWN)
check("a known key is answered here", r.status_code == 307 and r.headers["Location"] == "https://acme.example.com/product"
      and e.get("o") == "redirect", (r.headers.get("Location"), e))
r, e = ask(KNOWN + "?linkType=gs1:recipeInfo")
check("…and a link type it lacks stays a 404 (not a key nobody knows)", r.status_code == 404 and e.get("o") == "noLink",
      (r.status_code, e))
r, _ = ask("/01/0950600013437X")
check("an invalid request stays a 400", r.status_code == 400, r.status_code)
r, e = ask("/UnKnOwN")
check("a compressed link of an unknown key: sent uncompressed", r.status_code == 307
      and r.headers["Location"] == "https://resolver.example.net/gs1/01/09506000134376/10/B%2F1"
      and e.get("o") == "fallback" and e.get("f") == "compressed", (r.headers.get("Location"), e))
r, _ = ask(UNKNOWN, accept="application/linkset+json")
check("a linkset asked for an unknown key: sent too", r.status_code == 307, r.status_code)
r, _ = ask(UNKNOWN, method="HEAD")
check("HEAD: sent too", r.status_code == 307 and r.headers["Location"].endswith(UNKNOWN), dict(r.headers))

# ---------------------------------------------------------------- prefix rules
settings(rules=[("7895555", "https://beta-resolver.example.net", "path", True)])
r, e = ask(BETA + "/10/L1?linkType=gs1:pip")
check("a prefix rule: every key of the prefix sent, even one registered here, its path and query kept",
      r.status_code == 307 and r.headers["Location"] == "https://beta-resolver.example.net/01/07895555000017/10/L1"
      "?linkType=gs1:pip" and (e.get("o"), e.get("to")) == ("forwarded", "beta-resolver.example.net"),
      (r.headers.get("Location"), e))
r, _ = ask("/01/7895555000017")
check("…a GTIN-13 of the prefix", r.status_code == 307 and r.headers["Location"].startswith("https://beta-resolver"))
r, _ = ask(KNOWN)
check("…other prefixes answered here", r.headers.get("Location") == "https://acme.example.com/product")
r, _ = ask("/01/0789555500001X")
check("…an invalid request of the prefix stays a 400", r.status_code == 400, r.status_code)
settings(rules=[("789", "https://brazil.example.net", "path", True),
                ("7895555", "https://beta.example.com/scan", "fixed", True),
                ("7891234", "https://never.example.net", "path", False)])
r, _ = ask(BETA + "?linkType=gs1:pip")
check("the longest prefix wins; a fixed address: always that address", r.headers.get("Location")
      == "https://beta.example.com/scan", r.headers.get("Location"))
r, _ = ask("/01/07899999000015")
check("…the shorter one for the other keys", r.headers.get("Location") == "https://brazil.example.net/01/07899999000015",
      r.headers.get("Location"))
r, _ = ask(KNOWN)
check("…a disabled rule ignored: the shorter prefix applies", r.headers.get("Location")
      == "https://brazil.example.net/01/07891234500014", r.headers.get("Location"))
settings(rules=[("9521234", "https://sscc.example.net", "path", True)])
r, e = ask("/00/395212345678901236")
check("an SSCC: its prefix after the extension digit", r.status_code == 307
      and r.headers["Location"] == "https://sscc.example.net/00/395212345678901236", (r.status_code, e))
r, _ = ask("/414/9521234000013")
check("a GLN: its prefix from the first digit", r.headers.get("Location") == "https://sscc.example.net/414/9521234000013",
      r.headers.get("Location"))

# Both: a rule first, the resolver of last resort for the rest
settings(fallback={"enabled": True}, rules=[("7895555", "https://beta-resolver.example.net", "path", True)])
check("both on: a rule's prefix by the rule, a known key here, an unknown one to the last resort",
      ask(BETA)[0].headers.get("Location", "").startswith("https://beta-resolver")
      and ask(KNOWN)[0].headers.get("Location") == "https://acme.example.com/product"
      and ask(UNKNOWN)[0].headers.get("Location") == "https://id.gs1.org" + UNKNOWN)

# An organisation's own domain (ADR 0009) answers for its keys only: another prefix is unknown there
PORTAL["tenants"].insert_one({"_id": "t1", "prefixes": ["7891234"]})
PORTAL["domains"].insert_one({"_id": "id.acme.example", "verified": True, "mode": "direct", "tenant": "t1", "stem": ""})
settings(rules=[("7895555", "https://beta-resolver.example.net", "path", True)])
r, _ = ask(BETA, **{"X-Forwarded-Host": "id.acme.example"})
check("on an organisation's own domain, another organisation's prefix is not forwarded by its rule", r.status_code == 404,
      (r.status_code, r.headers.get("Location")))
PORTAL["tenants"].delete_many({})
PORTAL["domains"].delete_many({})

# ---------------------------------------------------------------- the settings, read again
settings(fallback={"enabled": True})
ask(UNKNOWN)                                                  # read once
PORTAL["settings"].update_one({"_id": forwarding.SETTING_FALLBACK}, {"$set": {"value": {"enabled": False}}})
check("a change is seen after the cache (within CACHE_SECONDS)", ask(UNKNOWN)[0].status_code == 307)
forwarding.FORWARDING.forget()
check("…and then applied", ask(UNKNOWN)[0].status_code == 404)
settings(fallback={"enabled": True})
ask(UNKNOWN)


def broken():
    raise RuntimeError("database down")


forwarding.FORWARDING.database = broken
forwarding.FORWARDING.forget()
check("a database that does not answer: the last settings kept", ask(UNKNOWN)[0].status_code == 307)
forwarding.FORWARDING.database = lambda: PORTAL
check("the default address is GS1's global resolver", forwarding.DEFAULT_FALLBACK == "https://id.gs1.org"
      and forwarding.CACHE_SECONDS <= 60)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
