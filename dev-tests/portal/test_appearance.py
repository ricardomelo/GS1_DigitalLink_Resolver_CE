"""
The installation's appearance in the portal (Documentation/adr/0019-appearance.md): the original until set; the title,
the three colours and the logo saved and read back; every refusal (the title's length, a colour that is not #RRGGBB,
white text hard to read on the main or the action colour, a logo that is not PNG, JPEG or WebP); the logo kept, replaced
and back to the project's; "Restore the original"; who may change it (server administrators outside support access);
the journal; what anyone may read (the appearance, its style sheet, the logo); and the setting as the resolver's own
reader (web_server/src/web_pages.py) sees it.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_appearance.py
"""
import base64
import importlib.util
import io
import os
import sys
import tempfile
import threading

from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3421
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ["PORTAL_DB_URI"] = "mongomock://"
os.environ["PORTAL_DB_NAME"] = f"devtest_appearance_{os.getpid()}"
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
for name in ("RESOLVER_LOG_DAYS", "PORTAL_MAIL_HOST"):
    os.environ.pop(name, None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import appearance  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username=None, password=None):
    c = portal.app.test_client()
    if username:
        c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


def image(kind="PNG", size=(120, 44), colour=(200, 30, 60)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind)
    return out.getvalue()


def data_uri(data, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
root, ana, anyone = client("root", "root-password-long"), client("ana", "ana-password-long"), client()

# The resolver's own reader of the same setting (web_server/src/web_pages.py), on the portal's database
RESOLVER_SRC = os.path.join(HERE, "..", "..", "web_server", "src")
spec = importlib.util.spec_from_file_location("resolver_web_pages", os.path.join(RESOLVER_SRC, "web_pages.py"))
web_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_pages)
web_pages.APPEARANCE.database = lambda: store.db()


def resolver():
    web_pages.APPEARANCE.forget()
    return web_pages.appearance()


ORIGINAL = {"title": "GS1 Resolver Community Edition", "colour": "#002C6C", "action": "#CE3D0D", "accent": "#F26334"}

# ================================================================== the original
data = anyone.get("/portal/api/appearance").get_json()
check("nothing set: the original, for anyone (no sign-in)", data["original"] is True and data["customLogo"] is False
      and {k: data[k] for k in ORIGINAL} == ORIGINAL and data["defaults"] == ORIGINAL and data["logo"] == "logo.svg"
      and data["updated"] is None, data)
r = anyone.get("/portal/appearance.css")
check("…the style sheet changes nothing", r.status_code == 200 and r.mimetype == "text/css"
      and ":root" not in r.get_data(as_text=True) and "max-age=60" in r.headers.get("Cache-Control", ""),
      (r.status_code, r.get_data(as_text=True)))
r = anyone.get("/portal/appearance/logo")
check("…the logo address gives the project's logo", r.status_code == 200 and r.mimetype == "image/svg+xml",
      (r.status_code, r.mimetype))
title, logo, style = resolver()
check("…the resolver's pages: the original title, logo and colours", title == ORIGINAL["title"]
      and logo == web_pages.LOGO_DATA_URI and style == "", (title, logo[:40], style))
check("the original colours keep white text readable (they pass their own rule)",
      appearance.contrast(ORIGINAL["colour"]) >= appearance.MIN_CONTRAST
      and appearance.contrast(ORIGINAL["action"]) >= appearance.MIN_CONTRAST,
      (appearance.contrast(ORIGINAL["colour"]), appearance.contrast(ORIGINAL["action"])))
check("the contrast is WCAG's: black 21:1, white 1:1, GS1 orange about 3:1",
      round(appearance.contrast("#000000"), 1) == 21.0 and round(appearance.contrast("#FFFFFF"), 1) == 1.0
      and 2.9 <= appearance.contrast("#F26334") <= 3.2, appearance.contrast("#F26334"))

# ================================================================== saved and read back
LOGO = image()
r = root.put("/portal/api/appearance", json={"title": "  Acme   Resolver ", "colour": "#1a3d2b", "action": "#8a1538",
                                             "accent": "#e8b100", "logo": data_uri(LOGO)}, headers=ORIGIN)
found = (r.get_json() or {}).get("appearance") or {}
check("saved: title (spaces folded), colours (upper case), logo", r.status_code == 200 and code(r) == "appearance.saved"
      and found.get("title") == "Acme Resolver" and found.get("colour") == "#1A3D2B" and found.get("action") == "#8A1538"
      and found.get("accent") == "#E8B100" and found.get("customLogo") is True and found.get("original") is False
      and found.get("updatedBy") == "root" and found.get("updated"), r.get_json())
stored = store.get_setting("appearance") or {}
check("…in the setting \"appearance\" of the portal's database", stored.get("title") == "Acme Resolver"
      and bytes(stored["logo"]["data"]) == LOGO and stored["logo"]["type"] == "image/png"
      and stored["logo"]["width"] == 120 and stored["logo"]["height"] == 44, {k: v for k, v in stored.items() if k != "logo"})
check("…the logo's address carries its version", found.get("logo") == f"appearance/logo?v={stored['logo']['etag']}",
      found.get("logo"))
r = anyone.get("/portal/api/appearance")
check("…anyone reads it", r.get_json()["title"] == "Acme Resolver" and r.get_json()["customLogo"] is True, r.get_json())
css = anyone.get("/portal/appearance.css").get_data(as_text=True)
check("…the style sheet sets the pages' tokens, with the darker shades",
      "--gs1-blue: #1A3D2B;" in css and "--gs1-orange: #E8B100;" in css and "--action: #8A1538;" in css
      and f"--gs1-blue-dark: {appearance.darker('#1A3D2B', .33)};" in css
      and f"--action-dark: {appearance.darker('#8A1538', .18)};" in css, css)
check("…darker: mixed with black", appearance.darker("#FF8040", .5) == "#804020" and appearance.darker("#123456", 0)
      == "#123456", appearance.darker("#FF8040", .5))
r = anyone.get("/portal/appearance/logo?v=1")
check("…the logo address gives the operator's logo (cached a day, never sniffed)", r.status_code == 200
      and r.data == LOGO and r.mimetype == "image/png" and "max-age=86400" in r.headers.get("Cache-Control", "")
      and r.headers.get("X-Content-Type-Options") == "nosniff", (r.status_code, r.mimetype, dict(r.headers)))
title, logo, style = resolver()
check("…the resolver's pages: the title, the logo embedded, the colours",
      title == "Acme Resolver" and logo == data_uri(LOGO)
      and style == ":root{--blue:#1A3D2B;--orange:#E8B100;--action:#8A1538;}", (title, logo[:40], style))
entry = store.col("journal").find_one({"action": "appearance-save"}) or {}
check("…in the journal", entry.get("user") == "root" and entry.get("tenant") is None and entry.get("detail")
      == "title=Acme Resolver colour=#1A3D2B action=#8A1538 accent=#E8B100 logo=yes", entry)

r = root.put("/portal/api/appearance", json={"title": "Acme Links"}, headers=ORIGIN)
found = r.get_json()["appearance"]
check("only the title sent: the colours and the logo kept", found["title"] == "Acme Links"
      and found["colour"] == "#1A3D2B" and found["customLogo"] is True
      and bytes(store.get_setting("appearance")["logo"]["data"]) == LOGO, found)
LOGO2 = image("WEBP", (80, 80), (0, 90, 40))
r = root.put("/portal/api/appearance", json={"logo": base64.b64encode(LOGO2).decode()}, headers=ORIGIN)
check("another logo (WebP, bare base64)", r.status_code == 200 and anyone.get("/portal/appearance/logo").data == LOGO2
      and anyone.get("/portal/appearance/logo").mimetype == "image/webp" and resolver()[1] == data_uri(LOGO2, "image/webp"),
      r.get_json())
r = root.put("/portal/api/appearance", json={"logo": ""}, headers=ORIGIN)
found = r.get_json()["appearance"]
check("\"\": back to the project's logo, the rest kept", found["customLogo"] is False and found["logo"] == "logo.svg"
      and found["title"] == "Acme Links" and anyone.get("/portal/appearance/logo").mimetype == "image/svg+xml"
      and resolver()[1] == web_pages.LOGO_DATA_URI, found)
check("…journal: logo=no", (list(store.col("journal").find({"action": "appearance-save"}).sort("at", -1))[:1] or [{}])[0]
      .get("detail", "").endswith("logo=no"))
r = root.put("/portal/api/appearance", json={"title": ""}, headers=ORIGIN)
check("an empty title: the original title (the colours kept)", r.get_json()["appearance"]["title"] == ORIGINAL["title"]
      and r.get_json()["appearance"]["colour"] == "#1A3D2B", r.get_json())

# ================================================================== refusals
before = store.get_setting("appearance")
for name, body, expected in (
        ("a title of 61 characters", {"title": "A" * 61}, "appearance.titleInvalid"),
        ("a title with a control character", {"title": "Acme\u0007"}, "appearance.titleInvalid"),
        ("a colour by name", {"colour": "navy"}, "appearance.colourInvalid"),
        ("a short colour", {"action": "#abc"}, "appearance.colourInvalid"),
        ("a highlight colour with alpha", {"accent": "#F26334FF"}, "appearance.colourInvalid"),
        ("a light main colour", {"colour": "#F26334"}, "appearance.colourContrast"),
        ("a light action colour", {"action": "#FFD700"}, "appearance.actionContrast"),
        ("a logo that is not an image", {"logo": base64.b64encode(b"<svg onload=alert(1)/>").decode()},
         "branding.logoInvalid"),
        ("a logo that is not base64", {"logo": "not base64!"}, "branding.logoInvalid"),
        ("a GIF logo", {"logo": base64.b64encode(image("GIF")).decode()}, "branding.logoInvalid"),
        ("a logo over 200 KB", {"logo": base64.b64encode(b"\x89PNG" + b"0" * (200 * 1024 + 1)).decode()},
         "branding.logoTooLarge")):
    r = root.put("/portal/api/appearance", json=body, headers=ORIGIN)
    check(f"refused: {name} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, r.get_json()))
check("…nothing changed by the refusals", store.get_setting("appearance") == before)
r = root.put("/portal/api/appearance", json={"colour": "#F26334"}, headers=ORIGIN)
check("the contrast refusal says how much and the minimum", (r.get_json() or {}).get("params") == {"ratio": "3.2",
                                                                                                    "min": "4.5"},
      r.get_json())
check("a colour of the action just readable (4.5:1) is accepted",
      root.put("/portal/api/appearance", json={"action": "#757575"}, headers=ORIGIN).status_code == 200
      and appearance.contrast("#757575") >= 4.5, appearance.contrast("#757575"))

# ================================================================== who may
check("not without signing in", anyone.put("/portal/api/appearance", json={"title": "X"}, headers=ORIGIN).status_code
      == 401 and anyone.delete("/portal/api/appearance", headers=ORIGIN).status_code == 401)
r = ana.put("/portal/api/appearance", json={"title": "Ana's"}, headers=ORIGIN)
check("not an organisation's administrator (server administrators only)", r.status_code == 403
      and code(r) == "access.serverAdmin" and ana.delete("/portal/api/appearance", headers=ORIGIN).status_code == 403,
      (r.status_code, r.get_json()))
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 9"}, headers=ORIGIN)
r = root.put("/portal/api/appearance", json={"title": "Support"}, headers=ORIGIN)
check("support access: read only (403 appearance.readOnly)", r.status_code == 403 and code(r) == "appearance.readOnly"
      and code(root.delete("/portal/api/appearance", headers=ORIGIN)) == "appearance.readOnly", (r.status_code, r.get_json()))
root.delete("/portal/api/support", headers=ORIGIN)
check("…nothing changed", store.get_setting("appearance")["title"] == ORIGINAL["title"])

# ================================================================== restore the original
r = root.delete("/portal/api/appearance", headers=ORIGIN)
found = (r.get_json() or {}).get("appearance") or {}
check("restored: the original everywhere", r.status_code == 200 and code(r) == "appearance.restored"
      and found.get("original") is True and {k: found.get(k) for k in ORIGINAL} == ORIGINAL, r.get_json())
check("…the setting removed", store.get_setting("appearance") is None
      and store.col("settings").find_one({"_id": "appearance"}) is None)
check("…anyone sees the original again", anyone.get("/portal/api/appearance").get_json()["original"] is True
      and ":root" not in anyone.get("/portal/appearance.css").get_data(as_text=True)
      and anyone.get("/portal/appearance/logo").mimetype == "image/svg+xml")
check("…the resolver's pages too", resolver() == (ORIGINAL["title"], web_pages.LOGO_DATA_URI, ""))
entry = store.col("journal").find_one({"action": "appearance-reset"}) or {}
check("…in the journal", entry.get("user") == "root" and entry.get("tenant") is None, entry)
check("restoring the original twice is harmless", root.delete("/portal/api/appearance", headers=ORIGIN).status_code == 200)

# ================================================================== the resolver's reader
store.set_setting("appearance", {"title": "Direct", "colour": "red", "action": "#123456"})
title, logo, style = resolver()
check("the resolver's reader ignores what is not a colour", title == "Direct" and style == ":root{--action:#123456;}",
      style)
web_pages.APPEARANCE.forget()
web_pages.APPEARANCE.current()
store.set_setting("appearance", {"title": "Later"})
check("…and reads the setting again only after 30 seconds", web_pages.appearance()[0] == "Direct"
      and web_pages.Appearance.CACHE_SECONDS == 30)
broken = web_pages.Appearance(lambda: (_ for _ in ()).throw(RuntimeError("down")))
check("…a database that fails: the original", broken.current() == {})
store.col("settings").delete_one({"_id": "appearance"})

# ================================================================== the pages
for page in ("index.html", "login.html", "privacy.html"):
    text = open(os.path.join(PORTAL, "static", page), encoding="utf-8").read()
    check(f"{page}: appearance.css after app.css, appearance.js after i18n.js",
          text.index('href="appearance.css"') > text.index('href="app.css"')
          and text.index('src="appearance.js"') > text.index('src="i18n.js"'), page)
check("appearance.js is served before sign-in", anyone.get("/portal/appearance.js").status_code == 200)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
