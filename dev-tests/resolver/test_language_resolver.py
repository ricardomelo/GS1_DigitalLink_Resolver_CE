"""
Language and market for safety-critical link types in the resolver (Documentation/adr/0028-language-fallback.md): the
standard's choice by language and context kept (GS1-Conformant Resolver 1.2.1, section 2.6.3), the header
Resolution-Fallback on a 307 or 300 whose links do not serve the language or the context asked; links that declare no
language or no context serve every one; for the five safety-critical types (asked, or the key's default link type on
a plain scan) a browser receives the page of a choice (300) with every link of the type and a notice in the visitor's
language, an app the redirect with the header; other link types, matched requests, '*' and the linkset unchanged. No
Docker, no MongoDB: documents are authored with the real data entry code and resolved with the real web server code
through Flask's test client.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_language_resolver.py
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



G = "/01/09506000134369"          # a medicine: leaflets in English and French only
NEUTRAL = "/01/09506000134376"    # a leaflet that declares no language
DEF = "/01/09506000134383"        # a key whose default link type is the leaflet


def link(linktype, href, lang=None, context=None, kind="text/html"):
    out = {"linktype": linktype, "href": href, "title": linktype, "type": kind}
    if lang:
        out["hreflang"] = [lang]
    if context:
        out["context"] = [context]
    return out


author({"anchor": G, "itemDescription": "Amoxicillin", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://pharma.example.com/product", "en"),
    link("gs1:epil", "https://pharma.example.com/leaflet-en", "en", "GB"),
    link("gs1:epil", "https://pharma.example.com/leaflet-fr", "fr", "FR"),
    link("gs1:recallStatus", "https://pharma.example.com/recall-en", "en"),
    link("gs1:smpc", "https://pharma.example.com/smpc", "en", "GB"),
    link("gs1:smpc", "https://pharma.example.com/smpc-neutral"),
    link("gs1:certificationInfo", "https://pharma.example.com/cert-en", "en")]})
author({"anchor": NEUTRAL, "itemDescription": "Neutral", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://neutral.example.com/product"),
    link("gs1:epil", "https://neutral.example.com/leaflet")]})
author({"anchor": DEF, "itemDescription": "Leaflet first", "defaultLinktype": "gs1:epil", "links": [
    link("gs1:epil", "https://def.example.com/leaflet-en", "en"),
    link("gs1:pip", "https://def.example.com/product", "en")]})


def ask(path, accept="*/*", language=None, **headers):
    """One request: an app (Accept: */*) unless accept says otherwise."""
    if language is not None:
        headers["Accept-Language"] = language
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.get("/api" + path, headers={"Accept": accept, "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone "
                          "OS 18_0 like Mac OS X) Mobile/15E148", **headers})
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else {})


def where(r):
    """(status, the target without the query string passed on, Resolution-Fallback)."""
    location = r.headers.get("Location")
    return r.status_code, location.split("?")[0] if location else None, r.headers.get("Resolution-Fallback")


EPIL, HTML = "?linkType=gs1:epil", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"

# ---------------------------------------------------------------- apps: the standard's answer, with the header
r, _ = ask(G + EPIL, language="pt-BR")
check("an app asking a leaflet in pt-BR, only English and French registered: no best match (300), header language",
      where(r) == (300, None, "language"), where(r))
r, _ = ask(G + "?linkType=gs1:recallStatus", language="pt-BR")
check("…one link in English: the redirect, with Resolution-Fallback: language",
      where(r) == (307, "https://pharma.example.com/recall-en", "language"), where(r))
check("…the header readable by a web app on another origin",
      "Resolution-Fallback" in r.headers.get("Access-Control-Expose-Headers", ""), r.headers)
r, _ = ask(G + EPIL, language="fr-CA, pt;q=0.5")
check("a language served (fr-CA → fr): the French leaflet, no header",
      where(r) == (307, "https://pharma.example.com/leaflet-fr", None), where(r))
r, _ = ask(G + EPIL, language="pt-BR, en;q=0.3")
check("…English accepted with a lower weight: served, no header",
      where(r) == (307, "https://pharma.example.com/leaflet-en", None), where(r))
r, _ = ask(G + EPIL, language="pt-BR, *;q=0.1")
check("…'*' accepts any language: no header", where(r)[2] is None, where(r))
r, _ = ask(G + EPIL)
check("…no Accept-Language at all: no header", where(r)[2] is None, where(r))
r, _ = ask(G + "?linkType=gs1:smpc", language="pt-BR")
check("a link that declares no language serves every one: chosen, no header",
      where(r) == (307, "https://pharma.example.com/smpc-neutral", None), where(r))
r, _ = ask(NEUTRAL + EPIL, language="pt-BR")
check("…a key whose only leaflet declares no language: redirect, no header",
      where(r) == (307, "https://neutral.example.com/leaflet", None), where(r))
r, _ = ask(G + EPIL + "&context=BR", language="fr")
check("a context nobody declared: the French leaflet (marked FR), header context",
      where(r) == (307, "https://pharma.example.com/leaflet-fr", "context"), where(r))
r, _ = ask(G + EPIL + "&context=FR", language="fr")
check("…the context served: no header", where(r) == (307, "https://pharma.example.com/leaflet-fr", None), where(r))
r, _ = ask(G + EPIL + "&context=BR", language="pt-BR")
check("…neither served: header 'language, context'", where(r)[2] == "language, context", where(r))
r, _ = ask(G + "?linkType=gs1:certificationInfo&context=BR", language="pt-BR")
check("…a link that declares no context serves every context: header language only", where(r)[2] == "language",
      where(r))
r, _ = ask(G, language="pt-BR")
check("a plain scan: the default link (pip, English), header language",
      where(r) == (307, "https://pharma.example.com/product", "language"), where(r))
r, _ = ask(G + "?linkType=linkset", language="pt-BR")
check("the linkset: unchanged, no header", r.status_code == 200 and "Resolution-Fallback" not in r.headers,
      (r.status_code, r.headers))

# ---------------------------------------------------------------- browsers: a choice for safety-critical types
r, e = ask(G + "?linkType=gs1:recallStatus", accept=HTML, language="pt-BR")
page = r.get_data(as_text=True)
check("a browser asking the recall status in pt-BR, English only: the page of a choice (300), not a redirect",
      r.status_code == 300 and "text/html" in r.content_type and not r.headers.get("Location"),
      (r.status_code, r.headers))
check("…with the header", r.headers.get("Resolution-Fallback") == "language", r.headers)
check("…the English link offered", "https://pharma.example.com/recall-en" in page, page[:400])
check("…the notice in the visitor's language, naming the type",
      "level-notice" in page and "Não há “Situação de recolhimento (recall)” no seu idioma" in page, page[:2000])
check("…the request log: outcome choice", e.get("o") == "choice" and e.get("s") == 300, e)
r, _ = ask(G + EPIL, accept=HTML, language="pt-BR")
page = r.get_data(as_text=True)
check("…the leaflet: every leaflet of the level offered (English and French)",
      r.status_code == 300 and "leaflet-en" in page and "leaflet-fr" in page, r.status_code)
r, _ = ask(G + EPIL + "&context=BR", accept=HTML, language="en-GB")
page = r.get_data(as_text=True)
check("…a market not served: the choice, the notice naming the market", r.status_code == 300
      and "No “" in page and "marked for your market (BR)" in page, page[:2000])
r, _ = ask(G + EPIL, accept=HTML, language="fr")
check("…a language served: the redirect, as before",
      where(r) == (307, "https://pharma.example.com/leaflet-fr", None), where(r))
r, _ = ask(G + "?linkType=gs1:certificationInfo", accept=HTML, language="pt-BR")
check("…another link type: the redirect, with the header",
      where(r) == (307, "https://pharma.example.com/cert-en", "language"), where(r))
r, _ = ask(G, accept=HTML, language="pt-BR")
check("…a plain scan whose default link type is not safety-critical: the redirect",
      where(r) == (307, "https://pharma.example.com/product", "language"), where(r))
r, _ = ask(DEF, accept=HTML, language="pt-BR")
page = r.get_data(as_text=True)
check("…a plain scan whose default link type is the leaflet: the choice with the leaflet",
      r.status_code == 300 and "https://def.example.com/leaflet-en" in page
      and "https://def.example.com/product" not in page, (r.status_code, page[:600]))
r, _ = ask(DEF, language="pt-BR")
check("…the same scan by an app: the redirect with the header",
      where(r) == (307, "https://def.example.com/leaflet-en", "language"), where(r))
r, _ = ask(NEUTRAL + EPIL, accept=HTML, language="pt-BR")
check("…a leaflet that declares no language: the redirect", where(r)[:2] == (307, "https://neutral.example.com/leaflet"),
      where(r))
r, _ = ask(G + "?linkType=gs1:recallStatus", accept=HTML, language="ar")
check("…the notice in Arabic for an Arabic browser", "لا يوجد “حالة الاستدعاء” بلغتك" in r.get_data(as_text=True),
      r.status_code)

# ---------------------------------------------------------------- the functions
check("unserved(): neutral links serve everything",
      web_logic.unserved([{"href": "x"}], ["pt-br"], "BR") == [], web_logic.unserved([{"href": "x"}], ["pt-br"], "BR"))
check("…a link marked only 'und' is neutral",
      web_logic.unserved([{"href": "x", "hreflang": ["und"]}], ["pt-br"], None) == [])
check("…a context given as text, not a list, is compared whole (no substring match)",
      web_logic.unserved([{"href": "x", "context": "BRA"}], [], "BR") == ["context"])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
