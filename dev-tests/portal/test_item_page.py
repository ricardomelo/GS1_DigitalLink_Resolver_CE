"""
The item's page in the portal (Documentation/adr/0011-item-page.md, backlog items 6.1 and 6.2), through the portal's
Flask test client: the brands per prefix (who brands which prefixes, the rules of a logo, a name and the colours,
support access read only, the logo's preview, the journal); the editor's option "Default target: the item's page"
(the gs1:defaultLink link it adds, the record read back without it, a shared default, the key's own record, unticking
it); spreadsheets (exported as a row, read back as the option); the tenant API; the link check of every record
leaving the page out; the overview counting page views and clicks apart from scans; the texts in both languages.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_item_page.py
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
DATA_ENTRY_PORT = 3394
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_itempage_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import branding  # noqa: E402
import gs1  # noqa: E402
import requestlog  # noqa: E402
import sheet  # noqa: E402
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

# ================================================================== brands: who brands which prefixes
r = ana.get("/portal/api/branding")
listed = r.get_json() or {}
check("an organisation's administrator lists its brands (none yet), its prefixes, the logo limit",
      r.status_code == 200 and listed.get("brands") == [] and listed.get("prefixes") == ["7891234"]
      and listed.get("maxLogoKB") == 200 and listed.get("installationDefault") is False
      and listed.get("verifiedOn") is False, listed)
check("an editor may not", edu.get("/portal/api/branding").status_code == 403
      and edu.put("/portal/api/branding/7891234", json={"name": "x"}, headers=ORIGIN).status_code == 403)
LOGO = image()
r = ana.put("/portal/api/branding/7891234", json={"name": "  Acme   Foods ", "colour": "#aa0000", "accent": "#00aa00",
                                                   "logo": data_uri(LOGO)}, headers=ORIGIN)
item = (r.get_json() or {}).get("item") or {}
check("…brands its prefix: name tidied, colours upper case, the logo described (never its bytes)",
      r.status_code == 200 and code(r) == "branding.saved" and item.get("name") == "Acme Foods"
      and item.get("colour") == "#AA0000" and item.get("accent") == "#00AA00" and item.get("verified") is True
      and item["logo"]["type"] == "image/png" and item["logo"]["width"] == 60 and item["logo"]["bytes"] == len(LOGO)
      and "data" not in item["logo"], r.get_json())
stored = store.col("branding").find_one({"_id": "7891234"})
check("…stored for the resolver: the bytes, the type, a version, the organisation",
      stored and bytes(stored["logo"]["data"]) == LOGO and stored["tenant"] == acme["id"]
      and re.fullmatch(r"[0-9a-f]{16}", stored["logo"]["etag"]), stored and {k: v for k, v in stored.items() if k != "logo"})
r = ana.put("/portal/api/branding/789123450", json={"name": "Acme Coffee", "verified": False}, headers=ORIGIN)
check("…and a longer prefix inside its own, without Verified by GS1", code(r) == "branding.saved"
      and r.get_json()["item"]["verified"] is False and r.get_json()["item"]["colour"] == branding.DEFAULTS["colour"])
for prefix, who, expected in (("7895555", ana, "branding.prefixOutside"), ("789", ana, "branding.prefixInvalid"),
                              ("*", ana, "branding.prefixOutside"), ("7891234", bia, "branding.prefixOutside"),
                              ("78912", ana, "branding.prefixOutside"), ("78a1234", ana, "branding.prefixInvalid"),
                              ("7891234", root, "branding.prefixOutside"), ("9506000", bia, "branding.prefixOutside")):
    r = who.put(f"/portal/api/branding/{prefix}", json={"name": "x"}, headers=ORIGIN)
    check(f"refused: {prefix!r} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
r = root.put("/portal/api/branding/78912345", json={"name": "x"}, headers=ORIGIN)
check("a server administrator may not brand a prefix inside an organisation's", code(r) == "branding.prefixOutside"
      and store.col("branding").count_documents({"_id": "78912345"}) == 0, code(r))
try:
    branding.save("*", {"name": "x"}, None, False, "someone")
    refused = False
except branding.UserError as exc:
    refused = exc.code == "branding.prefixOutside"
check("…and only a server administrator brands the installation's default", refused)
r = root.put("/portal/api/branding/9506000", json={"name": "Operator item"}, headers=ORIGIN)
check("a server administrator brands the operator's prefixes", code(r) == "branding.saved", r.get_json())
r = root.put("/portal/api/branding/*", json={"name": "The Resolver", "colour": "#002C6C"}, headers=ORIGIN)
check("…and the installation's default", code(r) == "branding.saved", r.get_json())
listed = root.get("/portal/api/branding").get_json()
check("…and lists the operator's and the default (the default first), not the organisations'",
      [b["prefix"] for b in listed["brands"]] == ["*", "9506000"] and listed["installationDefault"], listed)
check("another organisation does not see Acme's", bia.get("/portal/api/branding").get_json()["brands"] == [])
check("an organisation lists its own", [b["prefix"] for b in ana.get("/portal/api/branding").get_json()["brands"]]
      == ["7891234", "789123450"])

# ================================================================== the rules of a brand
for name, payload, expected in (
        ("SVG (it can carry scripts)", {"logo": data_uri(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml")},
         "branding.logoInvalid"),
        ("a GIF", {"logo": data_uri(image("GIF"), "image/gif")}, "branding.logoInvalid"),
        ("text that is not base64", {"logo": "data:image/png;base64,***"}, "branding.logoInvalid"),
        ("bytes that are no image", {"logo": data_uri(b"\x89PNG not really")}, "branding.logoInvalid"),
        ("a logo over 200 KB", {"logo": data_uri(os.urandom(201 * 1024))}, "branding.logoTooLarge"),
        ("a logo over 2000 pixels", {"logo": data_uri(image("PNG", (2001, 10)))}, "branding.logoTooLarge"),
        ("a colour that is not #rrggbb", {"colour": "red"}, "branding.colourInvalid"),
        ("an accent of 3 digits", {"accent": "#abc"}, "branding.colourInvalid"),
        ("a name over 60 characters", {"name": "x" * 61}, "branding.nameInvalid"),
        ("a name with a control character", {"name": "Acme\u0007"}, "branding.nameInvalid")):
    r = ana.put("/portal/api/branding/7891234", json=payload, headers=ORIGIN)
    check(f"refused: {name} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
r = ana.put("/portal/api/branding/7891234", json={"logo": data_uri(image("JPEG"), "image/jpeg")}, headers=ORIGIN)
check("a JPEG is accepted (and the bare base64 too)", r.get_json()["item"]["logo"]["type"] == "image/jpeg"
      and code(ana.put("/portal/api/branding/7891234", json={"logo": base64.b64encode(image("WEBP")).decode()},
                       headers=ORIGIN)) == "branding.saved")
r = ana.put("/portal/api/branding/7891234", json={"name": "Acme Foods"}, headers=ORIGIN)
check("a change without a logo keeps the logo, the colours and the flag", r.get_json()["item"]["logo"]["type"]
      == "image/webp" and r.get_json()["item"]["colour"] == "#AA0000", r.get_json())
r = ana.put("/portal/api/branding/7891234", json={"logo": data_uri(LOGO)}, headers=ORIGIN)
etag = store.col("branding").find_one({"_id": "7891234"})["logo"]["etag"]
check("…a new logo, a new version", r.get_json()["item"]["logo"]["url"] == f"api/branding/7891234/logo?v={etag}")
preview = ana.get("/portal/api/branding/7891234/logo")
check("the screen's preview of the logo: the bytes, not sniffed", preview.status_code == 200 and preview.data == LOGO
      and preview.mimetype == "image/png" and preview.headers.get("X-Content-Type-Options") == "nosniff")
check("…not another organisation's", bia.get("/portal/api/branding/7891234/logo").status_code == 404
      and root.get("/portal/api/branding/7891234/logo").status_code == 404)

# ================================================================== support access, removal, the journal
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN)
listed = root.get("/portal/api/branding").get_json()
check("support access: the organisation's brands, read only", listed["readOnly"]
      and [b["prefix"] for b in listed["brands"]] == ["7891234", "789123450"] and not listed["installationDefault"],
      listed)
r = root.put("/portal/api/branding/7891234", json={"name": "x"}, headers=ORIGIN)
check("…a change refused (403)", r.status_code == 403
      and root.delete("/portal/api/branding/7891234", headers=ORIGIN).status_code == 403)
root.delete("/portal/api/support", headers=ORIGIN)
r = ana.put("/portal/api/branding/789123450", json={"logo": data_uri(LOGO)}, headers=ORIGIN)
r = ana.put("/portal/api/branding/789123450", json={"logo": ""}, headers=ORIGIN)
check("the logo removed (\"logo\": \"\"), the brand kept", code(r) == "branding.saved"
      and r.get_json()["item"]["logo"] is None and store.col("branding").find_one({"_id": "789123450"})["name"]
      == "Acme Coffee")
check("removing another organisation's brand: unknown", code(bia.delete("/portal/api/branding/7895555",
                                                                           headers=ORIGIN)) == "branding.unknown")
r = ana.delete("/portal/api/branding/789123450", headers=ORIGIN)
check("a brand removed", code(r) == "branding.removed"
      and store.col("branding").count_documents({"_id": "789123450"}) == 0)
actions = [e["action"] for e in store.col("journal").find({"tenant": acme["id"]})]
check("the journal: saved and removed", "branding-save" in actions and "branding-remove" in actions, actions)
os.environ["RESOLVER_VERIFIED_BY_GS1_URL"] = "https://verified.example/?{key}={value}"
check("the screen knows when Verified by GS1 is switched on", ana.get("/portal/api/branding").get_json()["verifiedOn"])
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL")

# ================================================================== the editor's option
G1, G2, G3 = gtin("0789123450001"), gtin("0789123450002"), gtin("0789123450003")
LINKS = [{"linkType": "gs1:pip", "url": "https://acme.example.com/p", "hreflang": ["en"], "title": "Product"},
         {"linkType": "gs1:recipeInfo", "url": "https://acme.example.com/r", "hreflang": ["en"], "title": "Recipes"}]


def save(c, value, landing=True, qualifiers=None, links=LINKS, **extra):
    body = {"key": "01", "value": value, "description": "Coffee", "links": links, "landingPage": landing, **extra}
    if qualifiers:
        body["qualifiers"] = qualifiers
    return c.post("/portal/api/record", json=body, headers=ORIGIN)


def stored_entry(value, qualifiers=()):
    entries, default = portal.read_entries(f"/01/{value}")
    return portal.find_entry(entries, gs1.qualifier_list(list(qualifiers))), default


r = save(edu, G1)
entry, default = stored_entry(G1)
page = [l for l in (entry or {}).get("links", []) if l["linktype"] == "gs1:defaultLink"]
check("saved with the option: the record's default is gs1:defaultLink", r.status_code == 201 and default
      == "gs1:defaultLink", (r.status_code, r.get_json(), default))
check("…to the record's page on its domain", len(page) == 1 and page[0]["href"]
      == f"https://id.example.org/01/{G1}?linkType=linkset&view=page" and page[0]["type"] == "text/html", page)
check("…the other links kept", {l["linktype"] for l in entry["links"]} == {"gs1:pip", "gs1:recipeInfo",
                                                                            "gs1:defaultLink"})
opened = edu.get(f"/portal/api/record?key=01&value={G1}").get_json()
check("read back: the option ticked, the page link hidden, the links in order",
      opened["landingPage"] is True and [l["linkType"] for l in opened["links"]] == ["gs1:pip", "gs1:recipeInfo"],
      opened)
r = save(edu, G1, qualifiers={"10": "L1"}, landing=False)
check("a batch without the option, the product's default being the page: refused (shared default)",
      code(r) == "default.sharedMismatch" and r.get_json()["params"]["linkType"] == "gs1:defaultLink", r.get_json())
r = save(edu, G1, qualifiers={"10": "L1"})
entry, _ = stored_entry(G1, [("10", "L1")])
check("…with it: saved, with the batch's own page", code(r) == "save.created" and any(
    l["href"] == f"https://id.example.org/01/{G1}/10/L1?linkType=linkset&view=page" for l in entry["links"]),
    r.get_json())
opened = edu.get(f"/portal/api/record?key=01&value={G2}").get_json()
check("a key without records: the option is not shared", opened["landingPage"] is False
      and opened["sharedDefaultLinkType"] is None, opened)
r = save(edu, G2, qualifiers={"10": "B1"}, keyRecord={"mode": "copy", "description": ""})
key_entry, key_default = stored_entry(G2)
check("a batch with the option and the key's own record copied: the key's record gets its own page",
      code(r) == "save.createdWithKey" and key_default == "gs1:defaultLink"
      and [l["href"] for l in key_entry["links"] if l["linktype"] == "gs1:defaultLink"]
      == [f"https://id.example.org/01/{G2}?linkType=linkset&view=page"], (code(r), key_entry))
r = save(edu, G3, qualifiers={"10": "C1"}, keyRecord={"mode": "target", "url": "https://acme.example.com/k",
                                                      "description": ""})
key_entry, key_default = stored_entry(G3)
check("…or with one target: that target and the key's page", code(r) == "save.createdWithKey"
      and key_default == "gs1:defaultLink" and {l["linktype"] for l in key_entry["links"]}
      == {"gs1:pip", "gs1:defaultLink"}, key_entry)
G4 = gtin("0789123450004")
save(edu, G4)
r = save(edu, G4, landing=False)
entry, default = stored_entry(G4)
check("unticked (no other record): the page link removed, the first link the default again",
      code(r) == "save.updated" and default == "gs1:pip"
      and not any(l["linktype"] == "gs1:defaultLink" for l in entry["links"]), (code(r), default, entry))
r = edu.post("/portal/api/record", json={"key": "01", "value": G4, "description": "x", "links": [
    {"linkType": "gs1:defaultLink", "url": "https://elsewhere.example/", "hreflang": ["en"]}]}, headers=ORIGIN)
check("gs1:defaultLink is not a type to type in", code(r) == "link.typeRequired", r.get_json())

check("a gs1:defaultLink elsewhere (a record made by another tool) is not the item's page",
      not gs1.is_landing({"linktype": "gs1:defaultLink", "href": "https://acme.example.com/home"})
      and gs1.is_landing({"linktype": "gs1:defaultLink", "href": gs1.landing_url("https://x", "/01/1")}))

# ================================================================== spreadsheets
records = [{"key": "01", "value": G1, "qualifiers": [], "description": "Coffee", "defaultLinkType": "gs1:defaultLink",
            "links": stored_entry(G1)[0]["links"]}]
rows = sheet.export_rows(records)
check("exported: the page as a row of type gs1:defaultLink, marked default, first",
      rows[0][4] == "gs1:defaultLink" and rows[0][8] == "yes" and rows[0][5].endswith("?linkType=linkset&view=page")
      and len(rows) == 3, rows)
csv_text = sheet.write_csv(rows, {})


def preview(content, name="links.csv"):
    return edu.post("/portal/api/import/preview", json={"filename": name, "content": base64.b64encode(content).decode(),
                                                         "labels": {}}, headers=ORIGIN).get_json()


result = preview(csv_text)
check("read back: the same record, unchanged (the row is the option)", result.get("counts", {}).get("unchanged") == 1
      and not result.get("errors"), result)
no_page = sheet.write_csv([r for r in rows if r[4] != "gs1:defaultLink"], {})
result = preview(no_page)
check("…without that row: the option unticked, refused here as the batch shares the page",
      result.get("counts", {}).get("error") == 1 and [e["code"] for e in result["errors"]] == ["default.sharedMismatch"]
      and result["errors"][0]["params"]["linkType"] == "gs1:defaultLink", result)

# ================================================================== the tenant API
r = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"]}, headers=ORIGIN)
key = r.get_json()["key"]
auth = {"Authorization": f"Bearer {key}"}
G5 = gtin("0789123450005")
api = portal.app.test_client()
r = api.put(f"/portal/api/v1/records/01/{G5}", json={"description": "Tea", "links": LINKS[:1], "landingPage": True},
            headers=auth)
check("the tenant API takes landingPage", r.status_code == 201, (r.status_code, r.get_json()))
got = api.get(f"/portal/api/v1/records/01/{G5}", headers=auth).get_json()
check("…and gives it, the page link hidden", got.get("landingPage") is True and got.get("defaultLinkType")
      == "gs1:defaultLink" and [l["linkType"] for l in got["links"]] == ["gs1:pip"], got)

# ================================================================== the link check of every record
r = edu.post("/portal/api/links/jobs", json={"scope": "all"}, headers=ORIGIN)
job = store.col("jobs").find_one({"_id": r.get_json()["token"]}) if r.status_code == 202 else None
urls = [u["url"] for u in (job or {}).get("urls", [])]
check("the check of every record leaves the pages out (the resolver's own)", job and urls
      and not any(u.endswith("view=page") for u in urls) and "https://acme.example.com/p" in urls, urls)

# ================================================================== the overview: page views and clicks apart
EVENTS = requestlog.events()
EVENTS.delete_many({})
now = store.now() - timedelta(minutes=5)


def event(o, dev="mobile", f="uri", n=1):
    for _ in range(n):
        EVENTS.insert_one({"t": now, "expiresAt": now + timedelta(days=30), "m": "GET", "f": f, "s": 200, "o": o,
                           "dev": dev, "ai": "01", "v": G1, "cp": "7891234", "ms": 10})


event("redirect", n=5)
event("page", f="landing", n=4)
event("click", f="landing", n=3)
event("redirect", dev="automated", n=2)
event("linkset", dev="automated", f="landing")
data = ana.get("/portal/api/overview?days=7").get_json()
u, q = data["usage"], data["quality"]
check("the overview: scans without the page's views and clicks", u["scans"] == 5, u["scans"])
check("…page views and clicks counted apart", u["pageViews"] == 4 and u["clicks"] == 3
      and u["previous"]["pageViews"] == 0, {k: u[k] for k in ("pageViews", "clicks", "previous")})
check("…the item's page is no way of scanning (left out of the forms)", "landing" not in u["form"], u["form"])
check("…resolution quality counts requests, not follow-ups", q["requests"] == 8, q["requests"])
r = ana.get("/portal/api/requests?outcome=click")
check("the Requests screen filters clicks", r.status_code == 200
      and {e["outcome"] for e in r.get_json().get("events", [])} == {"click"}, r.get_json())
check("…and refuses an outcome it does not know", ana.get("/portal/api/requests?outcome=bogus").status_code == 422)

# ================================================================== texts
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(branding\.[A-Za-z]+)"', open(os.path.join(PORTAL, "branding.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read()))
index = open(os.path.join(PORTAL, "static", "index.html"), encoding="utf-8").read()
script = open(os.path.join(PORTAL, "static", "app.js"), encoding="utf-8").read()
codes |= set(re.findall(r'data-i18n="((?:branding|landing)\.[A-Za-z]+)"', index))
codes |= set(re.findall(r'"((?:branding|landing)\.[A-Za-z]+)"', script))
codes |= {"menu.branding", "branding.title", "branding.lede", "requests.outcome.page", "requests.outcome.click",
          "requests.form.landing", "overview.pageViews", "overview.clicks"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"every text of the item's page in both languages ({len(codes)})", len(codes) > 40 and not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
