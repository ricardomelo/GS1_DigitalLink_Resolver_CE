"""
Produces the screenshots used by README.md (Documentation/images/*.png) and by the portal user guide in
English (Documentation/images/guide/*.png) and in Brazilian Portuguese (Documentation/images/guide/pt-BR/)
from the real portal and home page, with example data and no network access. The GS1 logo is hidden in the images (it is a GS1
trademark and the images illustrate the software, not an endorsement). Run it again after visual changes.

  pip install -r portal/requirements.txt playwright pillow && playwright install chromium
  python dev-tests/docs/screenshots.py
"""
import json
import os
import sys
import tempfile
import threading

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(REPO, "Documentation", "images")
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8299, 3299
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_USERS_FILE=f"{CONFIG}/users.json", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
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
NO_LOGO = ".brand img { display: none !important; } .brand .product { border-left: 0 !important; padding-left: 0 !important; }"


def pip(href, lang="en", title="Product information"):
    return {"linktype": "gs1:pip", "href": href, "title": title, "hreflang": [lang]}


EXAMPLES = [
    ("/01/09506000134352", [], "Organic açaí 500 g", "gs1:pip",
     [pip("https://brand.example/acai"), {"linktype": "gs1:recipeInfo", "href": "https://brand.example/acai/recipes",
                                          "title": "Recipes", "hreflang": ["en"]}], "maria"),
    ("/01/09506000134352", [{"10": "L2026A"}], "Organic açaí 500 g", "gs1:pip",
     [pip("https://brand.example/acai/L2026A")], "joao"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}, {"21": "S1001"}], "Infusion pump", "gs1:pip",
     [pip("https://medical.example/pump"), {"linktype": "gs1:epil", "href": "https://medical.example/missing/ifu.pdf",
                                            "title": "Instructions for use", "hreflang": ["en"]}], "maria"),
    ("/01/09506000134376", [], "Infusion pump", "gs1:pip", [pip("https://medical.example/pump")], "maria"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}], "Infusion pump — batch B42", "gs1:pip",
     [pip("https://medical.example/pump/B42")], "joao"),
    ("/01/09506000134376", [{"22": "V1"}, {"10": "B42"}, {"21": "S1002"}], "Infusion pump", "gs1:pip",
     [pip("https://medical.example/pump")], None),
    ("/00/095060001343520000", [], "Pallet 1 — São Paulo DC", "gs1:traceability",
     [{"linktype": "gs1:traceability", "href": "https://logistics.example/pallet/1", "title": "Tracking",
       "hreflang": ["en"]}], "joao"),
    ("/414/9506000134376", [{"254": "DOCK-3"}], "Warehouse, dock 3", "gs1:masterData",
     [{"linktype": "gs1:masterData", "href": "https://logistics.example/dock/3", "title": "Dock 3",
       "hreflang": ["en"]}], None),
]
for anchor, qualifiers, description, default, links, user in EXAMPLES:
    doc = {"anchor": anchor, "itemDescription": description, "defaultLinktype": default, "links": links}
    if qualifiers:
        doc["qualifiers"] = qualifiers
    mock_data_entry.upsert(doc)
    if user:
        meta.touch(anchor, "".join(f"/{k}/{v}" for q in qualifiers for k, v in q.items()), user)


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
    scroll_x, scroll_y = page.evaluate("[window.scrollX, window.scrollY]")
    save(page, name, clip={"x": max(box["x"] + scroll_x - pad, 0), "y": max(box["y"] + scroll_y - pad, 0),
                           "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad + extra_height}, full=True)


os.makedirs(OUT, exist_ok=True)
import syntax  # noqa: E402 — tells whether the GS1 Barcode Syntax Engine is available (GS1_SYNTAX_ENGINE_DIR)


def sign_in(browser, locale, viewport=None):
    """A new browser in the locale, signed in as maria."""
    page = browser.new_context(locale=locale, viewport=viewport or {"width": 1280, "height": 1100}).new_page()
    page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
    page.goto(BASE); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(800)
    return page


def open_record(page, value, qualifiers=None):
    """Opens a GTIN record in the editor, with the qualifiers given ({"22": "V1", …}); others cleared."""
    page.select_option("#key-type", "01"); page.fill("#key-value", value)
    for field in page.query_selector_all("#qualifiers .qual-field input"):
        field.fill("")
    for ai, qualifier in (qualifiers or {}).items():
        page.fill(f"#q-{ai}", qualifier)
    page.wait_for_timeout(300)
    page.click("#open"); page.wait_for_timeout(900)


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


def guide_images(locale: str, folder: str, description: str, own_copies: bool) -> None:
    """Every image of the portal user guide in one language (Documentation/portal-user-guide.md and
    Documentation/pt-BR/guia-do-portal.md). With own_copies the images the English guide borrows from the
    README (attributes, record list, import, users) are written too, in this language."""
    os.makedirs(os.path.join(OUT, folder), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1100}).new_page()
        page.on("load", lambda pg: pg.add_style_tag(content=NO_LOGO))
        page.goto(BASE); page.wait_for_timeout(500)
        save(page, f"{folder}/sign-in.png", clip={"x": 0, "y": 0, "width": 1280, "height": 760})
        page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
        page.click("#login-submit"); page.wait_for_timeout(800)
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
        page.keyboard.press("Escape"); page.mouse.click(5, 300); page.wait_for_timeout(200)

        # Other records of the key, then the label block of a serial number
        open_record(page, "09506000134376")
        save_element(page, f"{folder}/other-records.png", "#others")
        open_record(page, "09506000134376", {"22": "V1", "10": "B42", "21": "S1001"})
        save_element(page, f"{folder}/label-panel.png", ".label-panel")
        if own_copies and syntax.ENGINE.available:
            add_attributes(page)
            save_element(page, f"{folder}/attributes.png", ".label-panel", pad=8)

        # Record list: filters and code search (the link check of the README pass is still shown)
        page.goto(BASE + "#records"); page.wait_for_timeout(900)
        if own_copies:
            save(page, f"{folder}/records.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})
        page.select_option("#records-key", "01"); page.select_option("#records-qualifier", "10"); page.wait_for_timeout(200)
        save_element(page, f"{folder}/records-filters.png", "#records-view .sheet")
        page.click("#records-clear")
        page.fill("#records-search", "https://id.example.org/01/09506000134376/22/V1/10/B42/21/S1001?17=271231")
        page.wait_for_timeout(300)
        save_element(page, f"{folder}/records-code-search.png", "#records-view .sheet")
        page.click("#records-clear")
        if own_copies:
            page.click("#records-import"); page.wait_for_timeout(200)
            page.set_input_files("#import-file", import_file()); page.wait_for_timeout(1500)
            save(page, f"{folder}/import.png")
            page.click("#import-cancel")
            page.goto(BASE + "#users"); page.wait_for_timeout(900)
            save(page, f"{folder}/users.png", clip={"x": 0, "y": 0, "width": 1280, "height": 1000})

        # Administration and options
        page.goto(BASE + "#audit"); page.wait_for_timeout(900)
        save(page, f"{folder}/audit.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})
        page.goto(BASE); page.wait_for_timeout(700)
        page.click("#user-button"); page.click("#menu-options"); page.wait_for_timeout(400)
        save_element(page, f"{folder}/password.png", "#options-dialog", pad=4)
        browser.close()


guide_images("en-GB", "guide", "Organic açaí 500 g — batch L2026A", own_copies=False)
guide_images("pt-BR", "guide/pt-BR", "Açaí orgânico 500 g — lote L2026A", own_copies=True)

# Home page
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    page.goto(f"http://127.0.0.1:{HOME_PORT}/"); page.wait_for_timeout(800)
    save(page, "home.png")
    page = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    page.goto(f"http://127.0.0.1:{HOME_PORT}/"); page.wait_for_timeout(800)
    save(page, "guide/pt-BR/home.png")
    browser.close()
