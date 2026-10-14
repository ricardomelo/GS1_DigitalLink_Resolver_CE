"""
Writes the resolver's item page of an example record (Documentation/adr/0011-item-page.md) to standard output, made by
the real web server code through Flask's test client, for dev-tests/docs/screenshots.py (which runs it in a process of
its own: the resolver's modules and the portal's share names). The brand's logo is given as a file.

  python dev-tests/docs/item_page_html.py <logo.png> <locale>
"""
import copy
import importlib
import os
import sys
import types

import mongomock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LOGO, LOCALE = sys.argv[1], sys.argv[2]

fake_mongo = types.ModuleType("mongo_db_init")
fake_mongo.mongo = None
fake_mongo.init_mongo = lambda app: None
sys.modules["mongo_db_init"] = fake_mongo
sys.path.insert(0, os.path.join(REPO, "data_entry_server", "src"))
sys.modules["data_entry_db"] = types.ModuleType("data_entry_db")
data_entry = importlib.import_module("data_entry_logic")
DB = {}


def author(doc):
    document = data_entry._author_db_linkset_document(doc)["data"]
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
os.environ.update(FQDN="id.example.org", MONGO_URI="mongodb://unused", RESOLVER_LOG_DAYS="0",
                  RESOLVER_VERIFIED_BY_GS1_URL="https://verified.example/?{key}={value}")
import web_logic  # noqa: E402
import domains  # noqa: E402
import landing  # noqa: E402

web_logic._call_gs1_toolkit = lambda s: True
PORTAL = mongomock.MongoClient()["resolver_portal"]
domains.MAP.database = lambda: PORTAL
landing.BRANDS.database = lambda: PORTAL
from __init__ import create_app  # noqa: E402

ANCHOR = "/01/09506000134352"
PAGE = "?linkType=linkset&view=page"


def link(kind, href, title, lang="en"):
    return {"linktype": kind, "href": href, "title": title, "type": "text/html", "hreflang": [lang]}


author({"anchor": ANCHOR, "itemDescription": "Organic açaí 500 g", "defaultLinktype": "gs1:defaultLink", "links": [
    link("gs1:pip", "https://brand.example/acai", "Product information"),
    link("gs1:pip", "https://brand.example/pt/acai", "Informações do produto", "pt"),
    link("gs1:recipeInfo", "https://brand.example/acai/recipes", "Recipes"),
    link("gs1:nutritionalInfo", "https://brand.example/acai/nutrition", "Nutrition facts"),
    link("gs1:sustainabilityInfo", "https://brand.example/acai/recycling", "How to recycle the pack"),
    link("gs1:hasRetailers", "https://brand.example/acai/shops", "Where to buy"),
    link("gs1:defaultLink", f"https://id.example.org{ANCHOR}{PAGE}", "Item page", "und")]})
PORTAL["branding"].insert_one({"_id": "9506000", "name": "Amazon Fruit Co.", "colour": "#4A1D5C", "accent": "#7BB03A",
                               "verified": True, "logo": {"type": "image/png", "data": open(LOGO, "rb").read(),
                                                          "etag": "example"}})
language = "pt-BR,pt;q=0.9" if LOCALE.startswith("pt") else "en-GB,en;q=0.9"
answer = create_app().test_client().get("/api" + ANCHOR + PAGE, headers={
    "Accept": "text/html", "Accept-Language": language, "User-Agent": "Mozilla/5.0 (iPhone; Mobile)"})
sys.stdout.write(answer.get_data(as_text=True))
