"""
Produces the screenshots used by README.md (Documentation/images/*.png) and by the portal user guide in
English (Documentation/images/guide/*.png) from the real portal and home page, with example data and no network access. The GS1 logo is hidden in the images (it is a GS1
trademark and the images illustrate the software, not an endorsement). Run it again after visual changes.

  pip install -r portal/requirements.txt playwright pillow && playwright install chromium
  python dev-tests/docs/screenshots.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(REPO, "Documentation", "images")
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8299, 3299
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_screenshots_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ["PORTAL_WORKER"] = "embedded"               # imports and link checks run in a thread of the portal
sys.path[:0] = [os.path.join(REPO, "dev-tests", "portal"), os.path.join(REPO, "portal")]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.set_password("maria", "a-long-test-password")
import app as portal  # noqa: E402
import linkcheck  # noqa: E402
import meta  # noqa: E402

linkcheck.check_url = lambda url: {"url": url, "ok": "missing" not in url,
                                   "problem": "linkcheck.httpError" if "missing" in url else None,
                                   "status": 404 if "missing" in url else 200, "finalUrl": url,
                                   "params": {"status": 404} if "missing" in url else {}}

for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"

# The home page's files, served as the proxy serves them (/, /home/…, /.well-known/gs1resolver)
from flask import Flask, Response, send_from_directory  # noqa: E402
HOME_DIR = os.path.join(REPO, "frontend_proxy_server", "home")
HOME_PORT = 8298
home_app = Flask("home")
home_app.add_url_rule("/", "index", lambda: send_from_directory(HOME_DIR, "index.html"))
home_app.add_url_rule("/home/<path:name>", "asset", lambda name: send_from_directory(HOME_DIR, name))
home_app.add_url_rule("/.well-known/gs1resolver", "description", lambda: Response(
    json.dumps({"resolverRoot": "https://id.example.org", "contact": {"fn": "Example Org", "hasURL": "https://www.example.org/"}}), mimetype="application/json"))
threading.Thread(target=make_server("127.0.0.1", HOME_PORT, home_app, threaded=True).serve_forever, daemon=True).start()

# Hides the GS1 logo (header of the portal and of the home page) in every screenshot
NO_LOGO = (".brand img { display: none !important; } .brand .product { border-left: 0 !important; padding-left: 0 !important; }"
           # the sidebar scrolls with the page in the pictures: a fixed one is drawn once, over a full-page capture
           " .sidebar { position: absolute !important; min-height: 100% !important; }")


def pip(href, lang="en", title="Product information"):
    return {"linktype": "gs1:pip", "href": href, "title": title, "hreflang": [lang]}


EXAMPLES = [
    ("/01/09506000134352", [], "Organic açaí 500 g", "gs1:pip",
     [pip("https://brand.example/acai"), {"linktype": "gs1:recipeInfo", "href": "https://brand.example/acai/recipes",
                                          "title": "Recipes", "hreflang": ["en"]}], "maria"),
    ("/01/09506000134352", [{"10": "L2026A"}], "Organic açaí 500 g", "gs1:pip",
     [pip("https://brand.example/acai/L2026A")], "joao"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}, {"21": "S1001"}], "Infusion pump — unit S1001", "gs1:pip",
     [pip("https://medical.example/pump"), {"linktype": "gs1:epil", "href": "https://medical.example/missing/ifu.pdf",
                                            "title": "Instructions for use", "hreflang": ["en"]}], "maria"),
    ("/01/09506000134376", [], "Infusion pump", "gs1:pip", [pip("https://medical.example/pump")], "maria"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}], "Infusion pump — batch B42", "gs1:pip",
     [pip("https://medical.example/pump/B42")], "joao"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}, {"21": "S1002"}], "Infusion pump — unit S1002", "gs1:pip",
     [pip("https://medical.example/pump")], None),
    # a batch of a GTIN without a record of its own: flagged in the record list (section 2.5.9)
    ("/01/09506000134925", [{"10": "C77"}], "Roasted coffee 1 kg — batch C77", "gs1:pip",
     [pip("https://brand.example/coffee/C77")], "joao"),
    ("/00/095060001343520000", [], "Pallet 1 — São Paulo DC", "gs1:traceability",
     [{"linktype": "gs1:traceability", "href": "https://logistics.example/pallet/1", "title": "Tracking",
       "hreflang": ["en"]}], "joao"),
    ("/414/9506000134376", [{"254": "DOCK-3"}], "Warehouse, dock 3", "gs1:masterData",
     [{"linktype": "gs1:masterData", "href": "https://logistics.example/dock/3", "title": "Dock 3",
       "hreflang": ["en"]}], None),
]
for anchor, qualifiers, description, default, links, user in EXAMPLES:
    doc = {"anchor": anchor, "itemDescription": description, "defaultLinktype": default, "links": links}
    # a serial number keeps its variant and batch as information (GS1-Conformant Resolver 2.5.9, rule 2)
    if any("21" in q for q in qualifiers):
        doc["informativeQualifiers"] = [q for q in qualifiers if "21" not in q]
        qualifiers = [q for q in qualifiers if "21" in q]
    if qualifiers:
        doc["qualifiers"] = qualifiers
    mock_data_entry.upsert(doc)
    if user:
        meta.touch(anchor, "".join(f"/{k}/{v}" for q in qualifiers for k, v in q.items()), user)



def confirm_portal(page, wait: int = 400) -> None:
    """Confirms the portal's own dialog (ADR 0013) when an action asked for it."""
    page.wait_for_timeout(200)
    if page.is_visible("#ask-dialog"):
        page.click("#ask-ok")
    page.wait_for_timeout(wait)

def save(page, name, clip=None, full=False):
    page.add_style_tag(content=NO_LOGO)
    page.wait_for_timeout(100)
    path = os.path.join(OUT, name)
    page.screenshot(path=path, clip=clip, full_page=full)
    image = Image.open(path).convert("RGB")
    image = image.quantize(colors=128, method=Image.Quantize.MEDIANCUT)   # small files for the repository
    image.save(path, optimize=True)
    print("wrote", os.path.relpath(path, REPO))


def save_element(page, name, selector, pad=12, extra_height=0):
    """Screenshot of one element of the page (with a margin), wherever it is on the page."""
    page.locator(selector).first.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    box = page.locator(selector).first.bounding_box()
    height = page.evaluate("window.innerHeight")
    if box["y"] - pad >= 0 and box["y"] + box["height"] + pad + extra_height <= height:
        # in view: captured as laid out (a full-page capture lays the page out again, without the sidebar of wide
        # screens, and the element moves)
        save(page, name, clip={"x": max(box["x"] - pad, 0), "y": box["y"] - pad,
                               "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad + extra_height})
        return
    scroll_x, scroll_y = page.evaluate("[window.scrollX, window.scrollY]")
    save(page, name, clip={"x": max(box["x"] + scroll_x - pad, 0), "y": max(box["y"] + scroll_y - pad, 0),
                           "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad + extra_height}, full=True)


os.makedirs(OUT, exist_ok=True)
import syntax  # noqa: E402 — tells whether the GS1 Barcode Syntax Engine is available (GS1_SYNTAX_ENGINE_DIR)
import tenants  # noqa: E402 — organisations for the guide's images


def sign_in(browser, locale, viewport=None):
    """A new browser in the locale, signed in as maria."""
    page = browser.new_context(locale=locale, viewport=viewport or {"width": 1280, "height": 1100}).new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.on("dialog", lambda dialog: dialog.accept())    # "discard unsaved changes?" between pictures
    page.goto(BASE); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(800)
    page.goto(BASE); page.wait_for_timeout(500)          # sign-in opens the overview; the pictures start in the editor
    return page


def open_record(page, value, qualifiers=None):
    """Opens a GTIN record in the editor, with the qualifiers given ({"22": "V1", …}); others cleared."""
    confirm_portal(page, 0)                              # "discard unsaved changes?" between pictures (ADR 0013)
    page.select_option("#key-type", "01"); page.fill("#key-value", value)
    for field in page.query_selector_all("#qualifiers .qual-field input"):
        field.fill("")
    for ai, qualifier in (qualifiers or {}).items():
        page.fill(f"#q-{ai}", qualifier)
    page.wait_for_timeout(300)
    page.click("#open"); confirm_portal(page, 700)


def add_attributes(page):
    """Data attributes (17) expiry and (3103) net weight in the label block."""
    page.check("#opt-attrs"); page.wait_for_timeout(150)
    row = "#attr-rows .attr-row:nth-child(1)"
    page.fill(f"{row} .attr-ai", "17"); page.press(f"{row} .attr-ai", "Tab"); page.fill(f"{row} .attr-value", "271231")
    page.click("#attr-add")
    row = "#attr-rows .attr-row:nth-child(2)"
    page.fill(f"{row} .attr-ai", "3103"); page.press(f"{row} .attr-ai", "Tab"); page.fill(f"{row} .attr-value", "000500")
    page.wait_for_timeout(1500)


def import_file() -> str:
    """A small spreadsheet for the import preview (two new records, one change)."""
    from openpyxl import Workbook  # noqa: PLC0415
    book = Workbook(); sheet = book.active
    sheet.append(["Key (AI)", "Identifier", "Qualifiers", "Description", "Link type", "URL", "Language", "Title",
                  "Default", "Forward query string"])
    sheet.append(["01", "09506000134352", "", "Organic açaí 500 g (new pack)", "gs1:pip", "https://brand.example/acai",
                  "en", "Product information", "yes", "yes"])
    sheet.append(["01", "09506000999999", "(10)L1", "Green tea 250 g", "gs1:pip", "https://brand.example/tea", "en", "", "", ""])
    sheet.append(["414", "9506000134377", "", "Store", "gs1:masterData", "https://store.example", "en", "", "", ""])
    path = os.path.join(CONFIG, "import.xlsx"); book.save(path)
    return path


# README images (English)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = sign_in(browser, "en-GB")

    # Editor: GTIN with variant, batch and serial
    open_record(page, "09506000134376", {"22": "V1", "10": "B42", "21": "S1001"})
    page.click("#check-links"); page.wait_for_timeout(1200)
    save(page, "portal-editor.png", full=True)

    # QR code panel with data attributes (needs the GS1 Barcode Syntax Engine: GS1_SYNTAX_ENGINE_DIR)
    if syntax.ENGINE.available:
        add_attributes(page)
        save_element(page, "portal-attributes.png", ".label-panel", pad=8)
    else:
        print("portal-attributes.png not written: GS1 Barcode Syntax Engine not available (GS1_SYNTAX_ENGINE_DIR)")

    # Record list after a link check
    page.goto(BASE + "#records"); page.wait_for_timeout(800)
    page.click("#records-check"); page.wait_for_timeout(2500)
    save(page, "portal-records.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})

    # Spreadsheet import preview
    page.click("#records-import"); page.wait_for_timeout(200)
    page.set_input_files("#import-file", import_file()); page.wait_for_timeout(1500)
    save(page, "portal-import.png")
    page.click("#import-cancel")
    # User administration
    users.create("ana", "ana-temporary-pw1", "editor", ["9506000"], must_change=False)
    users.create("rui", "rui-temporary-pw1", "reader", ["7891234"])
    page.goto(BASE + "#users"); page.wait_for_timeout(900)
    page.fill("#new-user-name", "joana"); page.select_option("#new-user-role", "editor"); page.fill("#new-user-prefixes", "7895678")
    page.click("#users-create button[type=submit]"); page.wait_for_timeout(800)
    save(page, "portal-users.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1100})
    browser.close()


def guide_images(locale: str, folder: str, description: str) -> None:
    """Every image of the portal user guide (Documentation/portal-user-guide.md). The guide borrows the images of
    the attributes, the record list, the import and the users from the README's."""
    os.makedirs(os.path.join(OUT, folder), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1100}).new_page()
        page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
        page.on("dialog", lambda dialog: dialog.accept())    # "discard unsaved changes?" between pictures
        page.goto(BASE); page.wait_for_timeout(500)
        save(page, f"{folder}/sign-in.png", clip={"x": 0, "y": 0, "width": 1280, "height": 760})
        page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
        page.click("#login-submit"); page.wait_for_timeout(800)
        page.goto(BASE); page.wait_for_timeout(500)      # sign-in opens the overview
        save(page, f"{folder}/editor-start.png", clip={"x": 0, "y": 0, "width": 1280, "height": 820})

        # Steps 1 to 3 and the history of a batch record (saved once more, so it has a version)
        open_record(page, "9506000134352", {"10": "L2026A"})
        page.fill("#description", description); page.click("#save"); page.wait_for_timeout(900)
        save_element(page, f"{folder}/step1-identify.png", "section.step:first-of-type")
        save_element(page, f"{folder}/step3-targets.png", "#editor")
        page.click("#history-toggle"); page.wait_for_timeout(700)
        save_element(page, f"{folder}/history.png", "#history-panel")
        page.click("#user-button"); page.wait_for_timeout(300)
        save(page, f"{folder}/user-menu.png", clip={"x": 900, "y": 0, "width": 380, "height": 420})
        page.keyboard.press("Escape"); page.mouse.click(700, 150); page.wait_for_timeout(200)

        # Other records of the key, then the label block of a serial number
        open_record(page, "09506000134376")
        save_element(page, f"{folder}/other-records.png", "#others")
        open_record(page, "09506000134376", {"22": "V1", "10": "B42", "21": "S1001"})
        save_element(page, f"{folder}/label-panel.png", ".label-panel")
        save_element(page, f"{folder}/step1-serial.png", "section.step:first-of-type")

        # Saving a batch of a GTIN without a record of its own (section 2.5.9), and copying targets
        open_record(page, "09506000134901", {"10": "L1"})
        page.fill("#description", "Green tea 250 g — batch L1")
        page.fill(".link-row .url", "https://brand.example/tea/L1"); page.click("#description")
        page.click("#save"); page.wait_for_timeout(500)
        save_element(page, f"{folder}/key-record-dialog.png", "#keyrecord-dialog", pad=4)
        page.click("#keyrecord-cancel"); page.wait_for_timeout(200)
        page.click("#copy-from"); page.wait_for_timeout(700)
        page.fill("#copy-search", "09506000134352"); page.wait_for_timeout(200)
        page.click("#copy-list li"); page.wait_for_timeout(150)
        save_element(page, f"{folder}/copy-targets.png", "#copy-pop", pad=8)
        page.click("#copy-cancel")

        # Record list: filters and code search (the link check of the README pass is still shown)
        page.goto(BASE + "#records"); page.wait_for_timeout(900)
        page.select_option("#records-key", "01"); page.select_option("#records-qualifier", "10"); page.wait_for_timeout(200)
        save_element(page, f"{folder}/records-filters.png", "#records-view .sheet")
        page.click("#records-clear")
        page.fill("#records-search", "https://id.example.org/01/09506000134376/22/V1/10/B42/21/S1001?17=271231")
        page.wait_for_timeout(300)
        save_element(page, f"{folder}/records-code-search.png", "#records-view .sheet")
        page.click("#records-clear")
        page.click("#records-alert-show"); page.wait_for_timeout(200)
        save_element(page, f"{folder}/records-status.png", "#records-view .sheet")
        page.click("#records-clear")

        # Administration and options
        page.goto(BASE + "#audit"); page.wait_for_timeout(900)
        save(page, f"{folder}/audit.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})
        page.goto(BASE); page.wait_for_timeout(700)
        page.click("#user-button"); page.click("#menu-options"); page.wait_for_timeout(400)
        save_element(page, f"{folder}/password.png", "#options-dialog", pad=4)
        page.click("#options-close")

        # Organisations and support access (last: an organisation takes its records away from maria)
        tenant_images(page, folder, locale)
        mail_images(browser, folder, locale)
        apikey_images(browser, folder, locale)
        domain_images(browser, folder, locale)
        item_page_images(browser, folder, locale)
        sso_images(browser, folder, locale)
        requests_images(browser, folder, locale)
        browser.close()


def tenant_images(page, folder: str, locale: str) -> None:
    """The organisations screen, the support access dialog and its banner (Documentation/adr/0002-tenants.md).
    The organisations are made once, with prefixes no example record uses, plus one tenant administrator."""
    if not tenants.find("Acme Foods"):
        acme = tenants.create("Acme Foods", ["7895555"], "maria")
        tenants.create("Beta Drinks", ["7896666", "7897777"], "maria")
        users.create("ana.acme", "acme-temporary-pw1", "admin", tenant=acme["id"], email="ana@acme.example",
                     must_change=False)
        for value, description in (("07895555000017", "Acme coffee 500 g"), ("07895555000024", "Acme tea 250 g")):
            mock_data_entry.upsert({"anchor": f"/01/{value}", "itemDescription": description, "defaultLinktype": "gs1:pip",
                                    "links": [pip(f"https://acme.example/{value}")]})
    page.goto(BASE + "#tenants"); page.wait_for_timeout(900)
    save(page, f"{folder}/organisations.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1000})
    acme_id = tenants.find("Acme Foods")["id"]
    page.goto(BASE + "#organisation?id=" + acme_id); page.wait_for_timeout(900)              # ADR 0013
    page.click("#org-tab-users"); page.wait_for_timeout(300)
    save(page, f"{folder}/organisation.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})
    page.goto(BASE + "#tenants"); page.wait_for_timeout(900)
    page.click("#tenants-body tr:first-child button.btn-ghost >> nth=2"); page.wait_for_timeout(300)  # Support access
    page.fill("#support-reason", "Ticket 42: wrong target")
    save_element(page, f"{folder}/support-dialog.png", "#support-dialog", pad=4)
    page.click("#support-open"); page.wait_for_timeout(1500)
    save(page, f"{folder}/support-banner.png", clip={"x": 0, "y": 0, "width": 1280, "height": 720})
    page.click("#support-leave"); page.wait_for_timeout(1200)


_relay = None


def mail_images(browser, folder: str, locale: str) -> None:
    """The e-mail screens (Documentation/adr/0004-e-mail.md): recovery on the sign-in page, the page a link opens,
    the invitation on the users screen and Options → E-mail. E-mail is on only while they are made (a relay of the
    development tests' own), so the other images show an installation without it."""
    global _relay
    from fake_smtp import FakeRelay
    import re
    if _relay is None:
        _relay = FakeRelay().start()
    os.environ.update(PORTAL_MAIL_HOST="127.0.0.1", PORTAL_MAIL_PORT=str(_relay.port), PORTAL_MAIL_SECURITY="none",
                      PORTAL_MAIL_FROM="portal@example.org")
    users.update("maria", email="maria@brand.example")
    try:
        ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
        page.goto(BASE + "login"); page.wait_for_timeout(600)
        page.click("#forgot-open"); page.fill("#forgot-login", "maria@brand.example")
        page.click("#forgot-submit"); page.wait_for_timeout(1200)
        save(page, f"{folder}/password-recovery.png", clip={"x": 0, "y": 0, "width": 1280, "height": 760})
        end = time.monotonic() + 8
        while not _relay.messages and time.monotonic() < end:
            time.sleep(0.05)
        text = _relay.messages[-1].get_body(("plain",)).get_content()
        link = re.search(r"http://\S+#reset=[A-Za-z0-9_-]+", text).group(0)
        _relay.clear()
        page.goto(link); page.wait_for_timeout(900)
        save(page, f"{folder}/choose-password.png", clip={"x": 0, "y": 0, "width": 1280, "height": 860})
        ctx.close()

        ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1100})
        page = ctx.new_page()
        page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
        page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
        page.click("#login-submit"); page.wait_for_timeout(1000)
        page.goto(BASE + "#users"); page.wait_for_timeout(900)
        page.fill("#new-user-name", "pedro.lima"); page.fill("#new-user-email", "pedro.lima@brand.example")
        save_element(page, f"{folder}/users-invite.png", "#users-create", pad=10, extra_height=110)
        page.click("#user-button"); page.click("#menu-options"); page.wait_for_timeout(400)
        page.check("#prefs-jobs")
        save_element(page, f"{folder}/options-email.png", "#options-dialog", pad=4)
        ctx.close()
    finally:
        users.update("maria", email="")
        os.environ["PORTAL_MAIL_HOST"] = ""


def apikey_images(browser, folder: str, locale: str) -> None:
    """The API keys screen with a key just created (Documentation/adr/0005-tenant-api.md)."""
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1100})
    page = ctx.new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(1000)
    page.goto(BASE + "#apikeys"); page.wait_for_timeout(900)
    page.fill("#new-apikey-name", "ERP")
    page.check("#apikeys-create input[value='records:write']")
    page.click("#apikeys-create button[type=submit]"); page.wait_for_timeout(1200)
    save(page, f"{folder}/api-keys.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1100})
    for button in page.query_selector_all("#apikeys-body button.btn-danger-ghost"):   # the next run starts clean
        button.click(); confirm_portal(page)
    ctx.close()


def domain_images(browser, folder: str, locale: str) -> None:
    """The Domains screen with one domain verified and one waiting for its DNS record
    (Documentation/adr/0009-tenant-domains.md); DNS is answered by the script itself."""
    import domains
    records = {}
    domains.txt_records = lambda name: records.get(name, [])
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1300})
    page = ctx.new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(1000)
    page.goto(BASE + "#domains"); page.wait_for_timeout(900)
    for name, stem in (("id.brand.example", "/gs1"), ("qr.brand.example", "")):
        page.fill("#new-domain", name); page.fill("#new-domain-stem", stem)
        page.click("#domains-create button[type=submit]"); page.wait_for_timeout(900)
    card = page.locator(".domain-card[data-domain='id.brand.example']")
    records["_gs1resolver.id.brand.example"] = [card.locator("dd.code").nth(1).inner_text()]
    card.locator("button.btn-primary").click(); page.wait_for_timeout(900)
    page.locator(".domain-card[data-domain='id.brand.example'] input.domain-defaults").fill("9506000")
    page.locator(".domain-card[data-domain='id.brand.example'] button[type=submit]").click(); page.wait_for_timeout(900)
    save(page, f"{folder}/domains.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1300})
    for name in ("id.brand.example", "qr.brand.example"):                # the next run starts clean
        page.locator(f".domain-card[data-domain='{name}'] button.btn-danger-ghost").click(); confirm_portal(page)
    ctx.close()


def example_logo() -> str:
    """A made-up brand's logo (a fruit and its name), as a PNG file."""
    from PIL import ImageDraw
    path = os.path.join(CONFIG, "brand-logo.png")
    image = Image.new("RGB", (240, 80), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 72, 72), fill=(74, 29, 92))
    draw.ellipse((24, 24, 56, 56), fill=(123, 176, 58))
    draw.text((86, 32), "AMAZON FRUIT CO.", fill=(74, 29, 92))
    image.save(path)
    return path


def item_page_images(browser, folder: str, locale: str) -> None:
    """The Item page screen with a brand, and the resolver's item page of a record on a phone
    (Documentation/adr/0011-item-page.md); the page is made by the resolver's code in a process of its own."""
    import base64
    import subprocess
    logo = example_logo()
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1200})
    page = ctx.new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(1000)
    page.goto(BASE + "#branding"); page.wait_for_timeout(900)
    page.fill("#brand-prefix", "9506000"); page.fill("#brand-name", "Amazon Fruit Co.")
    page.fill("#brand-colour", "#4a1d5c"); page.fill("#brand-accent", "#7bb03a"); page.set_input_files("#brand-logo", logo)
    page.click("#branding-form button[type=submit]"); page.wait_for_timeout(1000)
    save(page, f"{folder}/item-page.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1150})
    page.locator(".domain-card[data-prefix='9506000'] button.btn-danger-ghost").click()  # the next run starts clean
    confirm_portal(page)
    ctx.close()
    html = subprocess.run([sys.executable, os.path.join(HERE, "item_page_html.py"), logo, locale], check=True,
                          capture_output=True, text=True).stdout
    data = "data:image/png;base64," + base64.b64encode(open(logo, "rb").read()).decode()
    html = re.sub(r'src="/_brand/[^"]*"', f'src="{data}"', html)
    ctx = browser.new_context(locale=locale, viewport={"width": 390, "height": 844}, device_scale_factor=2,
                              is_mobile=True)
    page = ctx.new_page()
    page.set_content(html); page.wait_for_timeout(400)
    save(page, f"{folder}/item-page-phone.png", full=True)
    ctx.close()


def sso_images(browser, folder: str, locale: str) -> None:
    """The Organisation sign-in screen with the operator's configuration (Documentation/adr/0012-single-sign-on.md);
    removed afterwards, so that the sign-in page of the other pictures stays as it was."""
    import sso
    sso.save("operator", {"issuer": "https://login.brand.example/realms/staff", "clientId": "resolver-portal",
                          "clientSecret": "example-secret", "domains": ["brand.example"], "enabled": True}, "maria")
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(1000)
    page.goto(BASE + "#sso"); page.wait_for_timeout(900)
    save(page, f"{folder}/sso.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1000})
    ctx.close()
    sso.remove("operator")


def seed_requests() -> None:
    """A month of resolver requests, as the resolver would log them (Documentation/adr/0006-resolver-request-log.md),
    and their daily counts. Made once; the same for both languages."""
    import math
    import random
    from datetime import datetime, timedelta, timezone
    import requestlog
    events = requestlog.events()
    if events.estimated_document_count():
        return
    rnd = random.Random(42)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    codes = [("09506000134352", "", "brand.example", 6), ("09506000134352", "/10/L2026A", "brand.example", 3),
             ("09506000134376", "/21/*", "medical.example", 2), ("09506000134925", "/10/C77", "coffee.example", 2),
             ("07895555000017", "", "acme.example", 2), ("09506000999982", None, None, 1)]
    agents = ["mobile"] * 14 + ["tablet", "desktop", "desktop", "automated"]
    for day in range(30):
        for i in range(int(18 + 10 * math.sin(day / 3) + rnd.randint(0, 6))):
            value, level, host, _ = rnd.choices(codes, weights=[c[3] for c in codes])[0]
            t = now - timedelta(days=day, minutes=rnd.randint(0, 600 if day == 0 else 1400))
            doc = {"t": t, "expiresAt": t + timedelta(days=90), "m": "GET", "f": "uri", "ai": "01", "v": value,
                   "cp": value[1:], "dev": rnd.choice(agents), "ms": rnd.randint(6, 40),
                   "lang": rnd.choice(["pt-br", "pt-br", "pt-br", "en", "es"])}
            if level is None:
                doc.update(s=404, o="unknown")
            else:
                doc.update(s=307, o="redirect", lvl=level, to="www." + host)
                if level.startswith("/10/"):
                    doc["q"] = {"10": level[4:]}
                elif level == "/21/*":
                    doc["q"] = {"21": None}
            if rnd.random() < .15:
                doc["ref"] = "www.instagram.com"
            if rnd.random() < .05:
                doc.update(f="epc", epc="SGTIN-96")
            events.insert_one(doc)
    events.insert_one({"t": now - timedelta(minutes=3), "expiresAt": now + timedelta(days=90), "m": "GET", "f": "uri",
                       "s": 400, "o": "invalid", "p": "/wp-login.php", "dev": "automated", "ms": 2})
    for day in range(1, 31):
        requestlog.count_day(requestlog.today() - timedelta(days=day))


def requests_images(browser, folder: str, locale: str) -> None:
    """The Requests screen of a server administrator: the last 30 days and the latest requests (ADR 0006); the
    overview of the same month (ADR 0007)."""
    seed_requests()
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1250})
    page = ctx.new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE + "login"); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(1000)
    page.goto(BASE + "#requests"); page.wait_for_timeout(1500)
    save(page, f"{folder}/requests.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1250})
    page.goto(BASE + "#overview"); page.wait_for_timeout(1500)   # the overview (ADR 0007), the same month
    save(page, f"{folder}/overview.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1600})
    ctx.close()


guide_images("en-GB", "guide", "Organic açaí 500 g — batch L2026A")

# Home page
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    page.goto(f"http://127.0.0.1:{HOME_PORT}/"); page.wait_for_timeout(800)
    save(page, "home.png")
    browser.close()
