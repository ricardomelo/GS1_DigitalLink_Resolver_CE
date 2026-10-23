"""
The organisations' own domains in the resolver (Documentation/adr/0009-tenant-domains.md): the middleware that
recognises a verified "direct" domain from X-Forwarded-Host (or Host), removes its path stem and limits it to its
organisation's prefixes (the operator's to the keys no organisation holds), the description file's resolverRoot on a
domain, the cache of the domain list and a database that cannot be read; every other host answered as before. No
Docker, no MongoDB: documents are authored with the real data entry code and resolved with the real web server code
through Flask's test client; the portal's domains and tenants are in mongomock.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_domains_resolver.py
"""
import copy
import importlib
import json
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

web_logic._call_gs1_toolkit = lambda s: True
EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
PORTAL = mongomock.MongoClient()["resolver_portal"]
domains.MAP.database = lambda: PORTAL
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


ACME, BETA, OPER = "/01/07891234500014", "/01/07895555000017", "/01/09506000134352"
for anchor, host in ((ACME, "acme"), (BETA, "beta"), (OPER, "operator")):
    author({"anchor": anchor, "itemDescription": host, "defaultLinktype": "gs1:pip", "links": [
        {"linktype": "gs1:pip", "href": f"https://{host}.example.com/product", "title": "P", "type": "text/html",
         "hreflang": ["en"]}]})
author({"anchor": ACME, "qualifiers": [{"10": "A/B"}], "itemDescription": "batch", "defaultLinktype": "gs1:pip",
        "links": [{"linktype": "gs1:pip", "href": "https://acme.example.com/batch", "title": "B", "type": "text/html",
                   "hreflang": ["en"]}]})
PORTAL["tenants"].insert_many([{"_id": "t-acme", "name": "Acme", "prefixes": ["7891234"]},
                               {"_id": "t-beta", "name": "Beta", "prefixes": ["7895555"]}])
PORTAL["domains"].insert_many([
    {"_id": "id.acme.example", "tenant": "t-acme", "mode": "direct", "stem": "/gs1", "verified": True},
    {"_id": "go.acme.example", "tenant": "t-acme", "mode": "direct", "stem": "", "verified": True},
    {"_id": "pending.acme.example", "tenant": "t-acme", "mode": "direct", "stem": "", "verified": False},
    {"_id": "redir.acme.example", "tenant": "t-acme", "mode": "redirect", "stem": "", "verified": True},
    {"_id": "id.operator.example", "mode": "direct", "stem": "/a/b", "verified": True},
])


def ask(path, host=None, header="X-Forwarded-Host", accept="*/*", **extra):
    headers = {"Accept": accept, "User-Agent": "Mozilla/5.0 (iPhone; Mobile)", **extra}
    if host:
        headers[header] = host
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.get("/api" + path, headers=headers)
    request_log.WRITER.flush()
    events = list(EVENTS.find({}, {"_id": 0}))
    return response, (events[0] if len(events) == 1 else None)


def goes_to(response, target):
    return response.status_code == 307 and response.headers.get("Location", "").startswith(target)


# ---------------------------------------------------------------- an organisation's domain with a stem
r, e = ask("/gs1" + ACME, "id.acme.example")
check("the organisation's domain with its stem resolves its code", goes_to(r, "https://acme.example.com/product"),
      (r.status_code, r.headers.get("Location")))
check("…the request log sees the key, as on the installation's name", e and e.get("v") == ACME[4:]
      and e.get("o") == "redirect", e)
r, e = ask("/gs1" + BETA, "id.acme.example")
check("…another organisation's code: 404, as a code nobody registered", r.status_code == 404
      and e and e.get("o") == "unknown", (r.status_code, e))
r, _ = ask("/gs1" + OPER, "id.acme.example")
check("…the operator's code: 404", r.status_code == 404, r.status_code)
r, _ = ask("/gs1" + ACME + "/10/A%2FB", "id.acme.example")
check("…a batch with %2F after the stem (the raw request URI stripped too)", goes_to(r, "https://acme.example.com/batch"),
      (r.status_code, r.headers.get("Location")))
r, _ = ask(ACME, "id.acme.example")
check("…the same code without the stem still resolves (the stem is removed when present)",
      goes_to(r, "https://acme.example.com/product"), r.status_code)
r, _ = ask("/gs1" + BETA + "?linkType=gs1:certificationInfo", "id.acme.example", accept="text/html")
check("…a browser asking for another organisation's code gets the 404 page, without its link types",
      r.status_code == 404 and b"pip" not in r.data, r.status_code)
r, _ = ask("/gs1" + BETA + "?linkType=linkset", "id.acme.example", accept="application/linkset+json")
check("…its linkset is not given either", r.status_code == 404, r.status_code)
r, _ = ask("/.well-known/gs1resolver", "id.acme.example")
body = json.loads(r.data or b"{}")
check("the description file on the domain names the domain and its stem as the resolver root",
      r.status_code == 200 and body.get("resolverRoot") == "https://id.acme.example/gs1", body.get("resolverRoot"))
r, _ = ask("/.well-known/gs1resolver")
check("…on the installation's name, the installation's", json.loads(r.data)["resolverRoot"] == "https://id.example.org")

# ---------------------------------------------------------------- the addresses written about a request
# A GS1 Digital Link URI names the same item on any of the installation's names; the linkset's anchors, its Link
# header and the JSON-LD @id are on the name the request was made on (GS1's test suite compares the anchor with the
# URI it asked for), and so is the description file's root


def anchors(path, host=None, header="X-Forwarded-Host"):
    r, _ = ask(path, host, header=header, accept="application/linkset+json")
    return [item.get("anchor") for item in json.loads(r.data or b"{}").get("linkset", [])], r.headers.get("Link", "")


found, link = anchors("/gs1" + ACME + "/10/A%2FB", "id.acme.example")
check("linkset on an organisation's domain: the anchors carry the domain and its stem",
      found == ["https://id.acme.example/gs1" + ACME + "/10/A%2FB", "https://id.acme.example/gs1" + ACME], found)
check("…and so does the Link header", link.startswith("<https://id.acme.example/gs1" + ACME + "/10/A%2FB?linkType=linkset>"),
      link)
found, link = anchors(BETA, "alias.example.net")
check("linkset on another name of the installation: the anchors are on that name",
      found == ["https://alias.example.net" + BETA], found)
check("…and so is the Link header", link.startswith(f"<https://alias.example.net{BETA}?linkType=linkset>"), link)
r, _ = ask(BETA, "alias.example.net")
check("…the Link header of a redirect too", goes_to(r, "https://beta.example.com/")
      and r.headers.get("Link", "").startswith(f"<https://alias.example.net{BETA}?linkType=linkset>"),
      r.headers.get("Link"))
r, _ = ask(BETA, "alias.example.net", accept="application/ld+json")
body = json.loads(r.data or b"{}")
check("…the JSON-LD linkset's @id and anchors too", body.get("@id") == "https://alias.example.net" + BETA
      and [i.get("anchor") for i in body.get("linkset", [])] == ["https://alias.example.net" + BETA], body.get("@id"))
r, _ = ask("/.well-known/gs1resolver", "alias.example.net")
check("…and the description file's resolver root", json.loads(r.data)["resolverRoot"] == "https://alias.example.net",
      json.loads(r.data).get("resolverRoot"))
check("a port and capitals in the name are left out", anchors(BETA, "Alias.Example.NET:443")[0]
      == ["https://alias.example.net" + BETA])
check("the installation's own name: its anchors", anchors(BETA, "id.example.org")[0] == ["https://id.example.org" + BETA])
check("no X-Forwarded-Host (a request that did not come through the proxy): the installation's name",
      anchors(BETA)[0] == ["https://id.example.org" + BETA]
      and anchors(BETA, "web-service:4000", header="Host")[0] == ["https://id.example.org" + BETA])
for bad in ("bad_host.example", "evil.example/path", "a..b", "-x.example", "x" * 64 + ".example"):
    found, link = anchors(BETA, bad)
    check(f"a host that is not a valid host name ({bad[:20]}): the installation's name",
          found == ["https://id.example.org" + BETA] and link.startswith("<https://id.example.org/"), (found, link))
r, _ = ask("/.well-known/gs1resolver", "bad_host.example")
check("…in the description file too", json.loads(r.data)["resolverRoot"] == "https://id.example.org")

# ---------------------------------------------------------------- without a stem; how the host is read
check("a domain without a stem resolves its codes", goes_to(ask(ACME, "go.acme.example")[0], "https://acme.example.com/"))
check("…and refuses the others", ask(BETA, "go.acme.example")[0].status_code == 404)
check("Host when there is no X-Forwarded-Host", ask(BETA, "go.acme.example", header="Host")[0].status_code == 404)
check("a port and capitals in the host", ask(BETA, "Go.Acme.Example:443")[0].status_code == 404)
check("X-Forwarded-Host with several hosts: the first", ask(BETA, "go.acme.example, proxy.internal")[0].status_code == 404)

# ---------------------------------------------------------------- the operator's domain
check("the operator's domain (a stem of two segments) resolves the operator's codes",
      goes_to(ask("/a/b" + OPER, "id.operator.example")[0], "https://operator.example.com/"))
check("…and refuses every organisation's", ask("/a/b" + ACME, "id.operator.example")[0].status_code == 404
      and ask("/a/b" + BETA, "id.operator.example")[0].status_code == 404)

# ---------------------------------------------------------------- hosts that are not registered domains
check("the installation's name answers every code", goes_to(ask(BETA, "id.example.org")[0], "https://beta.example.com/"))
check("a domain not verified yet: as before", goes_to(ask(BETA, "pending.acme.example")[0], "https://beta.example.com/"))
check("a redirecting domain (its own server redirects here): as before",
      goes_to(ask(BETA, "redir.acme.example")[0], "https://beta.example.com/"))
check("no host header at all: as before", goes_to(ask(BETA)[0], "https://beta.example.com/"))
check("an unknown host with the stem's path: not stripped, 400 or 404", ask("/gs1" + ACME, "other.example")[0].status_code
      in (400, 404))

# ---------------------------------------------------------------- the cache and failures
PORTAL["domains"].update_one({"_id": "go.acme.example"}, {"$set": {"verified": False}})
check("the list is kept for a minute", ask(BETA, "go.acme.example")[0].status_code == 404)
domains.MAP.forget()
check("…and read again after it", goes_to(ask(BETA, "go.acme.example")[0], "https://beta.example.com/"))
PORTAL["domains"].update_one({"_id": "go.acme.example"}, {"$set": {"verified": True}})
domains.MAP.forget()
check("…verified again: limited again", ask(BETA, "go.acme.example")[0].status_code == 404)
domains.MAP.forget()
saved = domains.MAP.database


def broken():
    raise RuntimeError("database down")


domains.MAP.database = broken
check("the portal's database cannot be read: the last list is kept", ask(BETA, "go.acme.example")[0].status_code == 404)
domains.MAP.database = saved
domains.MAP.forget()
check("PORTAL_DB_NAME names the portal's database (resolver_portal by default)", domains.portal_db_name() == "resolver_portal")
os.environ["PORTAL_DB_NAME"] = "other_portal"
check("…or another", domains.portal_db_name() == "other_portal")
del os.environ["PORTAL_DB_NAME"]

# ---------------------------------------------------------------- the proxy passes the public host
conf = open(os.path.join(REPO, "frontend_proxy_server", "nginx.conf"), encoding="utf-8").read()
resolver_block = conf[conf.index("location / {"):conf.index("}", conf.index("location / {"))]
check("the proxy passes the public host to the resolver", "proxy_set_header X-Forwarded-Host $host;" in resolver_block,
      resolver_block)

request_log.WRITER.flush()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
