"""
The item's page in the resolver (Documentation/adr/0011-item-page.md, backlog items 6.1 and 6.2): a record whose
default link is its own page (gs1:defaultLink to ?linkType=linkset&view=page) is redirected there; the page shows the
brand of the longest prefix (name, logo served by the resolver, colours), one button per link with an icon, the
visitor's language first, the levels, Verified by GS1 when the installation and the brand allow it; page views and
clicks are logged as follow-ups (automated clients' as plain answers); /_click finds the link in the record again and
never redirects to an address taken from the request. No Docker, no MongoDB: documents are authored with the real
data entry code and resolved with the real web server code through Flask's test client; the portal's branding,
tenants and domains are in mongomock.

  pip install -r web_server/src/requirements.txt mongomock pillow
  python dev-tests/resolver/test_landing.py
"""
import copy
import importlib
import io
import os
import re
import sys
import types
from urllib.parse import parse_qs, urlparse

import mongomock
from PIL import Image

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
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)
import web_logic  # noqa: E402
import request_log  # noqa: E402
import domains  # noqa: E402
import landing  # noqa: E402

web_logic._call_gs1_toolkit = lambda s: True
EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
PORTAL = mongomock.MongoClient()["resolver_portal"]
domains.MAP.database = lambda: PORTAL
landing.BRANDS.database = lambda: PORTAL
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def png(colour=(200, 30, 30), size=(40, 20)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


ACME = "/01/07891234500014"              # prefix 7891234 (an organisation), 789123450 has a brand of its own
ACME2 = "/01/07891234600011"             # prefix 7891234 only
OPER = "/01/09506000134352"              # no organisation: the installation's brand
GLN = "/414/7891234000006"
SSCC = "/00/078912340000000017"
PAGE = "?linkType=linkset&view=page"


def page_link(anchor, qualifiers=""):
    return {"linktype": "gs1:defaultLink", "href": f"https://id.example.org{anchor}{qualifiers}{PAGE}",
            "title": "Item page", "type": "text/html", "hreflang": ["und"]}


def links(host):
    return [
        {"linktype": "gs1:pip", "href": f"https://{host}/en", "title": "Product page", "type": "text/html",
         "hreflang": ["en"]},
        {"linktype": "gs1:pip", "href": f"https://{host}/pt", "title": "Página do produto", "type": "text/html",
         "hreflang": ["pt"]},
        {"linktype": "gs1:recipeInfo", "href": f"https://{host}/recipes", "title": "Recipes", "type": "text/html",
         "hreflang": ["en"]},
    ]


author({"anchor": ACME, "itemDescription": "Acme coffee", "defaultLinktype": "gs1:defaultLink",
        "links": links("acme.example.com") + [page_link(ACME)]})
author({"anchor": ACME, "qualifiers": [{"10": "LOT1"}], "itemDescription": "Acme coffee, lot 1",
        "defaultLinktype": "gs1:defaultLink",
        "links": [{"linktype": "gs1:recallStatus", "href": "https://acme.example.com/recall", "title": "Recall",
                   "type": "text/html", "hreflang": ["en"]}, page_link(ACME, "/10/LOT1")]})
author({"anchor": ACME2, "itemDescription": "Acme tea", "defaultLinktype": "gs1:defaultLink",
        "links": links("acme.example.com") + [page_link(ACME2)]})
author({"anchor": OPER, "itemDescription": "Operator item", "defaultLinktype": "gs1:pip",
        "links": links("oper.example.com")[:1]})
author({"anchor": GLN, "itemDescription": "Acme plant", "defaultLinktype": "gs1:pip",
        "links": links("acme.example.com")[:1]})
author({"anchor": SSCC, "itemDescription": "Pallet", "defaultLinktype": "gs1:pip",
        "links": links("acme.example.com")[:1]})
PORTAL["tenants"].insert_one({"_id": "t-acme", "name": "Acme", "prefixes": ["7891234"]})
PORTAL["domains"].insert_many([
    {"_id": "id.acme.example", "tenant": "t-acme", "mode": "direct", "stem": "/gs1", "verified": True},
    {"_id": "id.operator.example", "mode": "direct", "stem": "", "verified": True},
])
LOGO = png()
PORTAL["branding"].insert_many([
    {"_id": "7891234", "tenant": "t-acme", "name": "Acme <b>Foods</b>", "colour": "#FFE66D", "accent": "#123456",
     "verified": True, "logo": {"type": "image/png", "data": LOGO, "etag": "abc123", "width": 40, "height": 20}},
    {"_id": "789123450", "tenant": "t-acme", "name": "Acme Coffee", "colour": "#3B1F0E", "accent": "#C8A27A",
     "verified": False},
    {"_id": "*", "name": "The Operator", "colour": "#002C6C", "accent": "#F26334", "verified": True},
    {"_id": "78912", "name": "Shorter prefix, read last", "colour": "#000000", "accent": "#FFFFFF"},
])

MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"


def ask(path, host=None, accept="text/html", ua=MOBILE, language="en-GB"):
    headers = {"Accept": accept, "User-Agent": ua, "Accept-Language": language}
    if host:
        headers["X-Forwarded-Host"] = host
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.get("/api" + path, headers=headers)
    request_log.WRITER.flush()
    events = list(EVENTS.find({}, {"_id": 0}))
    return response, (events[0] if len(events) == 1 else None)


def clicks(html):
    return [m.replace("&amp;", "&") for m in re.findall(r'href="([^"]*_click\?[^"]*)"', html)]


# ---------------------------------------------------------------- the scan: a conformant redirect to the page
r, e = ask(ACME, accept="*/*")
check("a scan of a record whose default is its page: 307 to the page",
      r.status_code == 307 and r.headers.get("Location", "").endswith(ACME + PAGE), (r.status_code, r.headers))
check("…logged as a scan (outcome redirect, form uri)", e and e["o"] == "redirect" and e["f"] == "uri", e)
r, e = ask(ACME + "/10/LOT1", accept="*/*")
check("…a batch: to the batch's page", r.status_code == 307
      and r.headers.get("Location", "").endswith(ACME + "/10/LOT1" + PAGE), r.headers.get("Location"))
r, _ = ask(ACME, accept="application/json")
check("…a JSON client gets the linkset as before (the page is a link like any other)", r.status_code == 200
      and "linkset" in (r.get_json(silent=True) or {}), r.status_code)
r, _ = ask(ACME + "?linkType=linkset", accept="application/linkset+json")
body = r.get_json(silent=True) or {}
anchor_item = (body.get("linkset") or [{}])[0]
check("the linkset carries the page as gs1:defaultLink and every link",
      any(k.endswith("/defaultLink") for k in anchor_item) and any(k.endswith("/recipeInfo") for k in anchor_item),
      list(anchor_item))
check("…and never a Verified by GS1 link", "verified" not in r.get_data(as_text=True).lower())

# ---------------------------------------------------------------- the page
r, e = ask(ACME + PAGE)
html = r.get_data(as_text=True)
check("the page: 200 HTML", r.status_code == 200 and r.mimetype == "text/html", r.status_code)
check("…logged as a follow-up: form landing, outcome page", e and e["f"] == "landing" and e["o"] == "page", e)
check("…titled by the item's description", "<title>Acme coffee" in html or ">Acme coffee<" in html, html[:400])
check("…the brand of the longest prefix (789123450: Acme Coffee, its colour)",
      "Acme Coffee" in html and "#3B1F0E" in html and "Acme &lt;b&gt;" not in html)
check("…white text on a dark colour", "color:#ffffff" in html)
check("…no logo for a brand without one", "/_brand/" not in html)
check("…a button per link, through /_click", len(clicks(html)) == 3, clicks(html))
check("…an icon per type (recipes: the food icon)", landing._I["food"] in html and landing._I["info"] in html)
check("…the visitor's language first, the others folded", "Other languages (1)" in html
      and html.index("Product page") < html.index("Other languages") < html.index("Página do produto"))
check("…the code in human readable form", "(01) 07891234500014" in html, re.findall(r"item-code.{0,80}", html))
check("…the linkset as JSON-LD", 'application/ld+json' in html)
check("…nothing loaded from other sites (no external src, no web fonts)", not re.search(r'src="https?://', html)
      and "fonts.googleapis" not in html and not re.search(r'<link[^>]+href="https?://', html))
check("…Verified by GS1 off without the installation's address", 'class="item-verified"' not in html)
r, _ = ask(ACME + PAGE, language="pt-BR")
html_pt = r.get_data(as_text=True)
check("in Portuguese: the Portuguese link first", html_pt.index("Página do produto") < html_pt.index("Outros idiomas")
      < html_pt.index(">Product page") if ">Product page" in html_pt else False)

r, e = ask(ACME + "?linkType=linkset")
check("?linkType=linkset in a browser without view=page: the same page, logged as linkset",
      r.status_code == 200 and "_click?" in r.get_data(as_text=True) and e and e["o"] == "linkset" and e["f"] == "uri", e)
r, e = ask(ACME + PAGE, ua="curl/8.5.0")
check("an automated client's page view: a plain linkset answer (counted apart as automated)",
      e and e["o"] == "linkset" and e["dev"] == "automated", e)

r, _ = ask(ACME2 + PAGE)
html2 = r.get_data(as_text=True)
check("a code of the shorter prefix: its brand, name escaped", "Acme &lt;b&gt;Foods&lt;/b&gt;" in html2
      and "<b>Foods" not in html2)
check("…dark text on a light colour", "color:#121212" in html2)
check("…its logo, served by the resolver with the logo's version", '/_brand/7891234?v=abc123' in html2)

r, _ = ask(ACME + "/10/LOT1" + PAGE)
html3 = r.get_data(as_text=True)
check("a batch's page: its level and the product's", html3.count("<h2>") == 2 and "Recall" in html3
      and "Product page" in html3)
check("…the alert icon for the recall status", landing._I["alert"] in html3)

r, _ = ask(OPER + "?linkType=linkset")
check("a code no organisation holds: the installation's brand", "The Operator" in r.get_data(as_text=True))
r, _ = ask(OPER + "?linkType=linkset", language="pt-BR")
html5 = r.get_data(as_text=True)
check("no link in the visitor's language: every link shown, none folded", "Outros idiomas" not in html5
      and len(clicks(html5)) == 1, clicks(html5))

# ---------------------------------------------------------------- clicks
r, _ = ask(ACME + PAGE)
targets = {parse_qs(urlparse(u).query)["t"][0]: u for u in clicks(r.get_data(as_text=True))}
r, e = ask(targets["recipeInfo"][len(""):], accept="text/html")
check("a click: 302 to the link's target", r.status_code == 302
      and r.headers["Location"] == "https://acme.example.com/recipes", (r.status_code, r.headers.get("Location")))
check("…not cached", r.headers.get("Cache-Control") == "no-store")
check("…logged: form landing, outcome click, the link type, the target's host, the key",
      e and e["o"] == "click" and e["f"] == "landing" and e.get("lt") == "recipeInfo"
      and e.get("to") == "acme.example.com" and e.get("v") == "07891234500014", e)
r, e = ask(targets["recipeInfo"], ua="python-requests/2.32")
check("…an automated client's click: redirected, logged as a plain redirect", r.status_code == 302
      and e and e["o"] == "redirect", e)

query = parse_qs(urlparse(targets["recipeInfo"]).query)


def click(**changes):
    q = {k: v[0] for k, v in query.items()}
    q.update(changes)
    q = {k: v for k, v in q.items() if v is not None}
    from urllib.parse import urlencode
    return ask("/_click?" + urlencode(q))


for name, change in (("another type than the link's", {"t": "pip"}),
                     ("a position past the links", {"i": "9"}), ("a negative level", {"l": "-1"}),
                     ("a level that is not a number", {"l": "x"}), ("no record path", {"a": None}),
                     ("a record path of odd length", {"a": "/01/07891234500014/10"}),
                     ("a code with no record", {"a": "/01/07891234999995"})):
    r, e = click(**change)
    check(f"/_click refuses {name}: 404, nothing logged as a click", r.status_code == 404
          and not (e and e.get("o") == "click"), (r.status_code, e))
r, _ = click(url="https://evil.example/", href="https://evil.example/")
check("/_click never takes a target from the request (extra url parameters ignored)",
      r.headers.get("Location") == "https://acme.example.com/recipes", r.headers.get("Location"))

# ---------------------------------------------------------------- on an organisation's domain with a stem
r, _ = ask("/gs1" + ACME + PAGE, host="id.acme.example")
html4 = r.get_data(as_text=True)
check("on the organisation's domain: the page's addresses keep the stem",
      clicks(html4) and all(u.startswith("/gs1/_click?") for u in clicks(html4)), clicks(html4)[:1])
r, e = ask(clicks(html4)[0], host="id.acme.example")
check("…its clicks resolve there", r.status_code == 302, r.status_code)
r, _ = ask("/gs1/_brand/7891234?v=abc123", host="id.acme.example")
check("…and its logo", r.status_code == 200)
r, _ = ask("/_click?" + urlparse(targets["recipeInfo"]).query, host="id.operator.example")
check("…another domain's click for the organisation's code: 404", r.status_code == 404, r.status_code)

# ---------------------------------------------------------------- logos
r, _ = ask("/_brand/7891234?v=abc123", accept="*/*")
check("the logo: the bytes uploaded, its type, cached a day, not sniffed", r.status_code == 200
      and r.data == LOGO and r.mimetype == "image/png" and "max-age=86400" in r.headers.get("Cache-Control", "")
      and r.headers.get("X-Content-Type-Options") == "nosniff", (r.status_code, r.headers))
for prefix in ("789123450", "000", "*"):
    r, _ = ask(f"/_brand/{prefix}", accept="*/*")
    check(f"no logo for {prefix!r}: 404", r.status_code == 404, r.status_code)

# ---------------------------------------------------------------- Verified by GS1 (item 6.2)
os.environ["RESOLVER_VERIFIED_BY_GS1_URL"] = "https://verified.example/search?{key}={value}"
r, _ = ask(ACME2 + PAGE)
check("Verified by GS1 on: a GTIN's page links to it with gtin=<value>",
      'href="https://verified.example/search?gtin=07891234600011"' in r.get_data(as_text=True))
r, _ = ask(ACME + PAGE)
check("…not for a brand that switched it off (789123450)", 'class="item-verified"' not in r.get_data(as_text=True))
r, _ = ask(GLN + "?linkType=linkset")
check("…a GLN: gln=<value>", "search?gln=7891234000006" in r.get_data(as_text=True))
r, _ = ask(SSCC + "?linkType=linkset")
check("…not for other keys (an SSCC)", r.status_code == 200 and 'class="item-verified"' not in r.get_data(as_text=True),
      r.status_code)
r, _ = ask(ACME2 + "?linkType=linkset", accept="application/linkset+json")
check("…never in the linkset", "verified.example" not in r.get_data(as_text=True))
check("verified_url() quotes the value", landing.verified_url("/01/a b", None).endswith("gtin=a%20b"))
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL")

# ---------------------------------------------------------------- the branding cache
PORTAL["branding"].update_one({"_id": "7891234"}, {"$set": {"name": "Renamed"}})
r, _ = ask(ACME2 + PAGE)
check("branding is cached (a change shows after the cache time)", "Renamed" not in r.get_data(as_text=True))
landing.BRANDS.forget()
r, _ = ask(ACME2 + PAGE)
check("…and read again after it", "Renamed" in r.get_data(as_text=True))


def broken():
    raise RuntimeError("database down")


landing.BRANDS.database = broken
landing.BRANDS.forget()
r, _ = ask(ACME2 + PAGE)
check("a branding read that fails: the page still answers, with the last branding", r.status_code == 200
      and "Renamed" in r.get_data(as_text=True))
landing.BRANDS.database = lambda: PORTAL

print(f"\n{'FAILED' if failures else 'ALL PASSED'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
