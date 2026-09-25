"""
Development test for the Resolver CE web and data entry code of this branch (no Docker, no MongoDB).

Documents are authored with the real data-entry code (data_entry_logic) and resolved with the real
web server code through Flask's test client; MongoDB and the GS1 toolkit are stubbed.

  pip install -r web_server/src/requirements.txt jsonschema
  python dev-tests/resolver/test_resolver.py          # RESOLVER_REPO=<path> to test another checkout
"""
import copy
import glob
import importlib
import json
import os
import sys
import types

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))
SCHEMA = json.load(open(os.path.join(HERE, "linkset-schema.json")))   # https://ref.gs1.org/standards/resolver/linkset-schema

# ---------------------------------------------------------------- stubs and authoring
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


def read_document(anchor):
    key = anchor.replace("/", "_").lstrip("_")
    return {"response_status": 200, "data": copy.deepcopy(DB[key])} if key in DB else {"response_status": 404, "error": "nf"}


web_db.read_document = read_document
sys.modules["web_db"] = web_db
os.environ.setdefault("FQDN", "id.example.org")
os.environ.setdefault("MONGO_URI", "mongodb://unused")
import web_logic  # noqa: E402
web_logic._call_gs1_toolkit = lambda s: True
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def get(path, accept="*/*", language="pt-BR,pt;q=0.9", cookie=None):
    if cookie:
        client.set_cookie("gs1resolver_lang", cookie, domain="localhost")
    else:
        client.delete_cookie("gs1resolver_lang", domain="localhost")
    return client.get("/api" + path, headers={"Accept": accept, "Accept-Language": language})


# ---------------------------------------------------------------- fixtures (the scenario used during development)
G = "/01/07898357410015"
author({"anchor": G, "itemDescription": "Teste 01", "defaultLinktype": "gs1:instructions", "links": [
    {"linktype": "gs1:instructions", "href": "https://www.codigo2d.com.br", "title": "Código 2D", "type": "text/html", "hreflang": ["pt"]},
    {"linktype": "gs1:pip", "href": "https://www.codigo2d.com.br/produto", "title": "Produto", "type": "text/html", "hreflang": ["pt"], "fwqs": False}]})
author({"anchor": G, "qualifiers": [{"10": "123"}], "itemDescription": "Teste Lote", "defaultLinktype": "gs1:instructions", "links": [
    {"linktype": "gs1:instructions", "href": "https://www.example.org", "title": "Lote 123", "type": "text/html", "hreflang": ["pt"]}]})

# ---------------------------------------------------------------- redirection
redirects = [
    (G, "https://www.codigo2d.com.br"),
    (G + "?linkType=gs1:instructions", "https://www.codigo2d.com.br?linkType=gs1%3Ainstructions"),
    (G + "?linkType=instructions", "https://www.codigo2d.com.br?linkType=instructions"),
    (G + "?linkType=https://gs1.org/voc/instructions", "https://www.codigo2d.com.br"),
    (G + "?linkType=https://ref.gs1.org/voc/instructions", "https://www.codigo2d.com.br"),
    (G + "?linkType=defaultLink", "https://www.codigo2d.com.br"),
    (G + "?linkType=defaultlink", "https://www.codigo2d.com.br"),
    (G + "?linkType=pip&x=1", "https://www.codigo2d.com.br/produto"),          # fwqs false: no query string
    (G + "/10/123", "https://www.example.org"),
    (G + "/10/123/", "https://www.example.org"),                                  # trailing slash
    (G + "/10/123?linkType=pip", "https://www.codigo2d.com.br/produto"),       # inherited from the GTIN level
    (G + "/10/111", "https://www.codigo2d.com.br"),                            # unknown batch walks up the tree
    (G + "/10/123/21/ABC", "https://www.example.org"),                           # serial within the batch
]
for path, expected in redirects:
    r = get(path)
    location = r.headers.get("Location", "")
    check(f"307 {path}", r.status_code == 307 and location.startswith(expected), f"{r.status_code} {location}")

for path in [G + "?linkType=gs1:recallStatus", G + "?linkType=gs1:linkset", G + "/10/123?linkType=recallStatus", "/01/07891234567895"]:
    r = get(path)
    check(f"404 {path}", r.status_code == 404, r.status_code)

# ---------------------------------------------------------------- linkset
for path, accept in [(G + "/10/123", "application/linkset+json"), (G + "?linkType=linkset", "*/*"), (G + "/10/111?linkType=linkset", "application/json")]:
    r = get(path, accept)
    body = r.get_json()
    try:
        jsonschema.validate(body, SCHEMA)
        valid = True
    except jsonschema.ValidationError as exc:
        valid = exc.message
    check(f"linkset valid {path}", r.status_code == 200 and valid is True, valid)
    check(f"linkset context header {path}", "json-ld#context" in (r.headers.get("Link") or ""), r.headers.get("Link"))
r = get(G + "/10/123?linkType=linkset", "application/ld+json")
check("JSON-LD on request", r.content_type.startswith("application/ld+json") and "@context" in r.get_json())

# ---------------------------------------------------------------- HTML pages and language
cases = [("pt-BR,pt;q=0.9", None, "pt-BR"), ("pt-BR,pt;q=0.9", "en-GB", "en-GB"), ("en-GB", None, "en-GB"),
         ("en-GB", "pt-BR", "pt-BR"), ("de-DE", "bogus", "en-GB"), ("en;q=0.5,pt;q=0.9", None, "pt-BR")]
for language, cookie, expected in cases:
    r = get(G + "?linkType=gs1:recallStatus", "text/html", language, cookie)
    html = r.get_data(as_text=True)
    check(f"HTML 404 lang={language} cookie={cookie}", r.status_code == 404 and f'<html lang="{expected}"' in html
          and "GS1 Resolver Community Edition" in html and 'id="lang"' in html, r.status_code)
r = get(G + "?linkType=linkset", "text/html")
check("HTML linkset page", r.status_code == 200 and r.content_type.startswith("text/html"))
check("CORS exposes Link", "Link" in (get(G).headers.get("Access-Control-Expose-Headers") or ""))

# ---------------------------------------------------------------- upstream regression expectations (tests/setup_test.py)
for f in glob.glob(os.path.join(REPO, "tests", "test_*.json")):
    data = json.load(open(f))
    for doc in data if isinstance(data, list) else [data]:
        author(doc)
upstream = [
    ("/01/09506000134376", {}, "https://dalgiardino.com/medicinal-compound/pil.html"),
    ("/01/09506000134376/21/HELLOWORLD", {}, "pil.html?serial=HELLOWORLD"),
    ("/01/09506000134376/10/LOT01", {}, "pil.html?lot=LOT01"),
    ("/8004/0950600013430000001", {}, "assets/8004/0950600013430000001.html"),
    ("/8004/095060001343999999", {}, "assets?giai=095060001343999999"),
]
for path, headers, expected in upstream:
    r = client.get("/api" + path, headers=headers)
    check(f"upstream {path}", r.status_code == 307 and expected in r.headers.get("Location", ""), r.headers.get("Location"))
for link_type in ["gs1:hasRetailers", "gs1:pip", "gs1:recipeInfo", "gs1:sustainabilityInfo"]:
    for language in ["en", "es", "vi", "ja"]:
        r = client.get("/api/01/09506000134352?linktype=" + link_type, headers={"Accept-Language": language, "Accept": "*/*"})
        location = r.headers.get("Location", "")
        check(f"upstream {link_type} {language}", r.status_code == 307 and f"test_lt={link_type}" in location
              and f"test_lang={language}" in location, location)

# ---------------------------------------------------------------- resolver description file
for var in ("RESOLVER_ORG_NAME", "RESOLVER_CONTACT_STREET", "RESOLVER_CONTACT_LOCALITY", "RESOLVER_CONTACT_REGION",
            "RESOLVER_CONTACT_POSTCODE", "RESOLVER_CONTACT_COUNTRY", "RESOLVER_CONTACT_TELEPHONE"):
    os.environ.pop(var, None)
r = client.get("/api/.well-known/gs1resolver")
d = r.get_json()
check("description: JSON", r.status_code == 200 and r.content_type.startswith("application/json"), r.content_type)
check("description: resolverRoot from FQDN", d.get("resolverRoot") == "https://id.example.org", d.get("resolverRoot"))
check("description: template contact when no operator is set", d.get("contact") == {"fn": "My Organisation"}, d.get("contact"))
os.environ.update(RESOLVER_ORG_NAME="Example Org", RESOLVER_CONTACT_LOCALITY="São Paulo",
                  RESOLVER_CONTACT_COUNTRY="Brazil", RESOLVER_CONTACT_TELEPHONE="+55 11 0000 0000")
d = client.get("/api/.well-known/gs1resolver").get_json()
check("description: contact from RESOLVER_*",
      d.get("contact") == {"fn": "Example Org", "hasAddress": {"locality": "São Paulo", "country-name": "Brazil"},
                           "hasTelephone": "tel:+55-11-0000-0000"}, d.get("contact"))
check("description: other properties kept", d.get("supportedPrimaryKeys") == ["all"] and "activeLinkTypes" in d)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
