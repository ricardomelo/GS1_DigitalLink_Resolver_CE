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
ENGINE = os.environ.get("GS1_SYNTAX_ENGINE")        # optional: the real GS1 Barcode Syntax Engine


def engine_check(ai_data_string):
    """What the resolver's toolkit call does in production: accept or refuse the element string."""
    script = os.path.join(ENGINE, "_resolver_check.mjs")
    if not os.path.exists(script):
        with open(script, "w") as fh:
            fh.write('import {GS1encoder} from "gs1encoder"; const g = new GS1encoder(); await g.init();'
                     'try { g.aiDataStr = process.argv[2]; g.getDLuri(null); } catch (e) { g.free(); process.exit(1); } g.free();')
    import subprocess
    return subprocess.run(["node", script, ai_data_string], cwd=ENGINE, capture_output=True).returncode == 0
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
html = r.get_data(as_text=True)
check("HTML linkset page: levels named from the absolute anchors", "<h2>Produto (todas as unidades)</h2>" in html
      and "id.example.org" not in html.split("<h2>", 1)[1].split("</h2>", 1)[0], html[html.find("<h2>"):][:200])
r = get(G + "/10/123?linkType=linkset", "text/html")
check("HTML linkset page: batch level named", "<h2>Lote 123</h2>" in r.get_data(as_text=True))
# Targets that are not web addresses (stored through the API, which takes any href) are listed, not linked
UNSAFE = "/01/07890000000772"
author({"anchor": UNSAFE, "itemDescription": "Unsafe targets", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://example.org/ok", "title": "Web page", "type": "text/html", "hreflang": ["en"]},
    {"linktype": "gs1:epil", "href": "javascript:alert(document.cookie)", "title": "Script", "type": "text/html", "hreflang": ["en"]},
    {"linktype": "gs1:smpc", "href": " JavaScript:alert(1)", "title": "Script 2", "type": "text/html", "hreflang": ["en"]},
    {"linktype": "gs1:faqs", "href": "data:text/html,<script>alert(1)</script>", "title": "Data", "type": "text/html", "hreflang": ["en"]}]})
unsafe_html = get(UNSAFE + "?linkType=linkset", "text/html").get_data(as_text=True)
check("HTML linkset page: https target linked", 'href="https://example.org/ok"' in unsafe_html)
check("HTML linkset page: javascript: and data: targets listed without a link",
      "javascript:" not in unsafe_html.lower().split("<script>")[0] and "data:text/html" not in unsafe_html
      and unsafe_html.count('class="unlinked"') == 3 and "Script 2" in unsafe_html, unsafe_html[unsafe_html.find("<h2>"):][:900])
unsafe_404 = get(UNSAFE + "?linkType=gs1:recallStatus", "text/html").get_data(as_text=True)
check("HTML 404 page lists the same targets without links", 'class="unlinked"' in unsafe_404 and "javascript:alert" not in unsafe_404)
check("HTML pages: logo links to the home page", '<a class="brand" href="/" title="Página inicial do Resolver">' in html)
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

# ---------------------------------------------------------------- data entry summary
data_entry.data_entry_db.read_all_documents = lambda: {"response_status": 200, "data": [copy.deepcopy(d) for d in DB.values()]}
summary = data_entry.read_summary()
lines = summary.get("data") or []
batch_line = [l for l in lines if l.get("qualifiers")]
check("summary: one line per entry", summary.get("response_status") == 200 and len(lines) == sum(len(d["data"]) for d in DB.values()), summary)
check("summary: fields", all({"anchor", "itemDescription", "defaultLinktype", "linkCount"} <= set(l) for l in lines), lines[:1])
check("summary: batch entry keeps its qualifiers", bool(batch_line) and batch_line[0]["qualifiers"] == [{"10": "123"}], batch_line[:1])
check("summary: sorted by anchor", [l["anchor"] for l in lines] == sorted(l["anchor"] for l in lines))
with_links = data_entry.read_summary(True).get("data") or []
check("summary with links: every link included", all(len(l.get("links") or []) == l["linkCount"] for l in with_links)
      and "links" not in lines[0], with_links[:1])

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

# ---------------------------------------------------------------- every primary key (URI Syntax 1.7, section 4.3)
KEY_EXAMPLES = {"01": "09506000999999", "8006": "095060001343520102", "8013": "1987654Ad4X4bL5ttr2310c2K",
                "8010": "9506000ABC-1", "414": "9506000134376", "417": "9506000134376", "8017": "950600013437612342",
                "8018": "950600013437612342", "255": "95060001343761234", "00": "095060001343520000",
                "253": "9506000134376ABC", "401": "9506000ABC", "402": "95060001343760123",
                "8003": "09506000134352ABC", "8004": "9506000ABC123"}
if ENGINE:
    web_logic._call_gs1_toolkit = engine_check
for ai, value in KEY_EXAMPLES.items():
    anchor = f"/{ai}/{value}"
    author({"anchor": anchor, "itemDescription": f"Key {ai}", "defaultLinktype": "gs1:pip", "links": [
        {"linktype": "gs1:pip", "href": f"https://example.org/key/{ai}", "title": "t", "type": "text/html", "hreflang": ["en"]}]})
    r = get(anchor)
    check(f"resolves {anchor}" + (" (real syntax engine)" if ENGINE else ""),
          r.status_code == 307 and r.headers.get("Location") == f"https://example.org/key/{ai}", (r.status_code, r.headers.get("Location")))
    r = get(anchor + "?linkType=linkset", "application/linkset+json")
    check(f"linkset for {anchor}", r.status_code == 200 and anchor in r.get_data(as_text=True), r.status_code)
# ---------------------------------------------------------------- key qualifiers (sections 4.4 and 4.9)
def link(href):
    return [{"linktype": "gs1:pip", "href": href, "title": "t", "type": "text/html", "hreflang": ["en"]}]


Q = "/01/09506000999982"       # a GTIN with a record per level: product, variant, variant + batch
author({"anchor": Q, "itemDescription": "Cascade", "defaultLinktype": "gs1:pip", "links": link("https://example.org/product")})
author({"anchor": Q, "qualifiers": [{"22": "V1"}], "itemDescription": "Cascade", "defaultLinktype": "gs1:pip",
        "links": link("https://example.org/variant")})
author({"anchor": Q, "qualifiers": [{"22": "V1"}, {"10": "L1"}], "itemDescription": "Cascade", "defaultLinktype": "gs1:pip",
        "links": link("https://example.org/variant-batch")})
for path, target in [(Q + "/22/V1/10/L1/21/S1", "variant-batch"), (Q + "/22/V1/10/L2", "variant"),
                     (Q + "/22/V2/10/L1", "product"), (Q + "/22/V1", "variant"), (Q + "/10/L1", "product")]:
    r = get(path)
    check(f"walk-up {path} → {target}", r.status_code == 307 and r.headers.get("Location") == f"https://example.org/{target}",
          (r.status_code, r.headers.get("Location")))
QUALIFIED = [("/415/9506000134376", [{"8020": "INV-1"}]), ("/414/9506000134376", [{"254": "EXT1"}]),
             ("/417/9506000134376", [{"7040": "1ABC"}]), ("/8004/9506000ABC123", [{"7040": "1ABC"}]),
             ("/8018/950600013437612342", [{"8019": "123"}]), ("/8010/9506000ABC-1", [{"8011": "123"}]),
             ("/01/09506000999999", [{"235": "TPX123"}])]
for anchor, qualifiers in QUALIFIED:
    author({"anchor": anchor, "qualifiers": qualifiers, "itemDescription": "q", "defaultLinktype": "gs1:pip",
            "links": link("https://example.org/q" + anchor.replace("/", "-"))})
    path = anchor + "".join(f"/{k}/{v}" for q in qualifiers for k, v in q.items())
    r = get(path)
    check(f"resolves {path}" + (" (real syntax engine)" if ENGINE else ""),
          r.status_code == 307 and r.headers.get("Location") == "https://example.org/q" + anchor.replace("/", "-"),
          (r.status_code, r.headers.get("Location")))

if ENGINE:
    r = get("/00/095060001343520001")
    check("wrong SSCC check digit refused by the syntax engine", r.status_code == 400, r.status_code)
    r = get("/415/9506000134376")
    check("415 without its required 8020 refused by the syntax engine", r.status_code == 400, r.status_code)
    r = get("/01/09506000999999/235/TPX123/10/L1")
    check("UPUI combined with a batch refused by the syntax engine", r.status_code == 400, r.status_code)
else:
    print("SKIP real syntax engine checks (set GS1_SYNTAX_ENGINE, see dev-tests/portal/test_keys.py)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
