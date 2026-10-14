"""
Default link titles in the link's language (GS1-Conformant Resolver 2.5.3, conformance review F21, backlog item 7.3),
through the portal's Flask test client: a link saved without a title gets its type's title in Portuguese when the link
is in Portuguese (pt, pt-BR, pt-PT) and in English otherwise; a title somebody typed is kept as typed; a title the
portal gave, in either language, is shown empty in the editor so that it follows a change of language; spreadsheets
and the tenant API give titles the same way; every link type has a Portuguese title.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_titles.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3395
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_titles_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import gs1  # noqa: E402
import tenants  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


def gtin(body):
    return body + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body))) % 10) % 10)


def image(kind="PNG", size=(60, 30), colour=(10, 120, 200)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind)
    return out.getvalue()


def data_uri(data, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))


G1, G2 = gtin("0789123451001"), gtin("0789123451002")


def save(value, links, **extra):
    return ana.post("/portal/api/record", json={"key": "01", "value": value, "description": "Coffee", "links": links,
                                                **extra}, headers=ORIGIN)


def stored(value):
    entries, _ = portal.read_entries(f"/01/{value}")
    return {(l["linktype"], l["hreflang"][0]): l["title"] for l in portal.find_entry(entries, [])["links"]}


r = save(G1, [{"linkType": "gs1:pip", "url": "https://acme.example.com/pt", "hreflang": ["pt"], "title": ""},
              {"linkType": "gs1:pip", "url": "https://acme.example.com/en", "hreflang": ["en"], "title": ""},
              {"linkType": "gs1:recipeInfo", "url": "https://acme.example.com/r", "hreflang": ["pt-BR"]},
              {"linkType": "gs1:instructions", "url": "https://acme.example.com/es", "hreflang": ["es"]},
              {"linkType": "gs1:support", "url": "https://acme.example.com/s", "hreflang": ["pt"],
               "title": "Fale conosco"}])
titles = stored(G1)
check("saved: a link in Portuguese without a title gets the Portuguese title", r.status_code == 201
      and titles[("gs1:pip", "pt")] == "Página do produto" and titles[("gs1:recipeInfo", "pt-BR")] == "Receitas", titles)
check("…in English, the English one", titles[("gs1:pip", "en")] == "Product information page", titles)
check("…English for a language without titles (Spanish)",
      titles[("gs1:instructions", "es")] == gs1.LINK_TYPE_DEFAULT_TITLES["gs1:instructions"], titles)
check("…a typed title kept", titles[("gs1:support", "pt")] == "Fale conosco")
opened = ana.get(f"/portal/api/record?key=01&value={G1}").get_json()
shown = {(l["linkType"], l["hreflang"][0]): l["title"] for l in opened["links"]}
check("the editor shows the portal's titles empty, typed ones as typed", shown[("gs1:pip", "pt")] == ""
      and shown[("gs1:pip", "en")] == "" and shown[("gs1:recipeInfo", "pt-BR")] == ""
      and shown[("gs1:support", "pt")] == "Fale conosco", shown)
links = opened["links"]
for link in links:
    if link["linkType"] == "gs1:recipeInfo":
        link["hreflang"] = ["en"]
save(G1, links)
check("a link moved to English gets the English title on the next save",
      stored(G1)[("gs1:recipeInfo", "en")] == gs1.LINK_TYPE_DEFAULT_TITLES["gs1:recipeInfo"], stored(G1))
G3 = gtin("0789123451003")
save(G3, [{"linkType": "gs1:pip", "url": "https://acme.example.com/pt", "hreflang": ["pt"],
           "title": "Product information page"}])                  # as records saved before F21 hold it
again = ana.get(f"/portal/api/record?key=01&value={G3}").get_json()["links"]
save(G3, again)
check("…an old record's English default on a Portuguese link becomes Portuguese when saved again",
      again[0]["title"] == "" and stored(G3)[("gs1:pip", "pt")] == "Página do produto", (again, stored(G3)))

key = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"]},
               headers=ORIGIN).get_json()["key"]
r = portal.app.test_client().put(f"/portal/api/v1/records/01/{G2}", headers={"Authorization": f"Bearer {key}"},
                                 json={"description": "Tea", "links": [{"linkType": "gs1:nutritionalInfo",
                                       "url": "https://acme.example.com/n", "hreflang": ["pt-PT"]}]})
check("the tenant API: the same rule (pt-PT → Portuguese)", r.status_code == 201
      and stored(G2)[("gs1:nutritionalInfo", "pt-PT")] == "Informação nutricional", stored(G2))
check("every link type has a Portuguese title", set(gs1.LINK_TYPE_TITLES_PT) == gs1.LINK_TYPE_CODES
      and all(gs1.LINK_TYPE_TITLES_PT.values()))
check("default_title(): the language's base, any case", gs1.default_title("gs1:pip", ["PT-br"]) == "Página do produto"
      and gs1.default_title("gs1:pip", []) == gs1.LINK_TYPE_DEFAULT_TITLES["gs1:pip"]
      and gs1.default_title("gs1:pip", ["und"]) == gs1.LINK_TYPE_DEFAULT_TITLES["gs1:pip"])
check("is_default_title(): only the portal's own, never an empty title", gs1.is_default_title("gs1:pip", "Página do produto")
      and not gs1.is_default_title("gs1:pip", "Página") and not gs1.is_default_title("gs1:pip", ""))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
