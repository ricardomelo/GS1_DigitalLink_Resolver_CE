"""
Produces the screenshots used by README.md (Documentation/images/*.png) from the real portal and home
page, with example data and no network access. Run it again after visual changes.

  pip install -r portal/requirements.txt playwright pillow && playwright install chromium
  python dev-tests/docs/screenshots.py            # needs nginx on the PATH for the home page
"""
import os
import shutil
import subprocess
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
    path = os.path.join(OUT, name)
    page.screenshot(path=path, clip=clip, full_page=full)
    image = Image.open(path).convert("RGB")
    image = image.quantize(colors=128, method=Image.Quantize.MEDIANCUT)   # small files for the repository
    image.save(path, optimize=True)
    print("wrote", os.path.relpath(path, REPO))


os.makedirs(OUT, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.goto(BASE); page.fill("#username", "maria"); page.fill("#password", "a-long-test-password")
    page.click("#login-submit"); page.wait_for_timeout(800)

    # Editor: GTIN with variant, batch and serial
    page.fill("#key-value", "09506000134376")
    page.fill("#q-22", "V1"); page.fill("#q-10", "B42"); page.fill("#q-21", "S1001"); page.wait_for_timeout(300)
    page.click("#open"); page.wait_for_timeout(900)
    page.click("#check-links"); page.wait_for_timeout(1200)
    save(page, "portal-editor.png", full=True)

    # Record list after a link check
    page.goto(BASE + "#records"); page.wait_for_timeout(800)
    page.click("#records-check"); page.wait_for_timeout(2500)
    save(page, "portal-records.png", clip={"x": 0, "y": 0, "width": 1280, "height": 900})

    # Spreadsheet import preview
    from openpyxl import Workbook
    book = Workbook(); sheet = book.active
    sheet.append(["Key (AI)", "Identifier", "Qualifiers", "Description", "Link type", "URL", "Language", "Title",
                  "Default", "Forward query string"])
    sheet.append(["01", "09506000134352", "", "Organic açaí 500 g (new pack)", "gs1:pip", "https://brand.example/acai",
                  "en", "Product information", "yes", "yes"])
    sheet.append(["01", "09506000999999", "(10)L1", "Green tea 250 g", "gs1:pip", "https://brand.example/tea", "en", "", "", ""])
    sheet.append(["414", "9506000134377", "", "Store", "gs1:masterData", "https://store.example", "en", "", "", ""])
    upload = os.path.join(CONFIG, "import.xlsx"); book.save(upload)
    page.click("#records-import"); page.wait_for_timeout(200)
    page.set_input_files("#import-file", upload); page.wait_for_timeout(1500)
    save(page, "portal-import.png")
    browser.close()

# Home page, through the real nginx configuration (as in dev-tests/home/test_home.py)
if shutil.which("nginx"):
    shots = tempfile.mkdtemp()
    env = dict(os.environ, HOME_TEST_SCREENSHOTS=shots)
    subprocess.run([sys.executable, os.path.join(REPO, "dev-tests", "home", "test_home.py")], env=env,
                   capture_output=True, check=False)
    source = os.path.join(shots, "home-desktop-en.png")
    if os.path.exists(source):
        image = Image.open(source).convert("RGB")
        image = image.crop((0, 0, image.width, min(image.height, 900)))
        image.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(os.path.join(OUT, "home.png"), optimize=True)
        print("wrote Documentation/images/home.png")
