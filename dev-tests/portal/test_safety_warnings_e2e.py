"""
The portal's warnings on safety-critical link types in a real browser (Playwright/Chromium; Documentation/adr/0022-
answering-level.md, section 2.5): the editor's box under the targets when a batch lacks the product's safety-critical
links (with the types named and what the strict mode would do), the box under the qualifiers for a batch value close to
an existing one, the product's box listing its batches, the box gone once the batch has its own links, the import's
preview marking the row and counting it, the count on the organisation's Resolution tab, in English and Portuguese.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_safety_warnings_e2e.py          # SCREENSHOTS=<folder> keeps a picture of each step
"""
import os
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8263, 3263
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_safety_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import csp_guard  # noqa: E402,F401  (fails the program on a Content-Security-Policy violation: ADR 0038)
import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import sheet  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Pharma", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
G = "07891234000170"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {str(detail)[:600]}"))
    if not condition:
        failures.append(name)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.wait_for_timeout(500)


def link(kind):
    return {"linkType": kind, "url": f"https://farma.example/{kind.split(':')[1]}", "title": "", "hreflang": ["en"]}


def seed(page, qualifiers, *types):
    r = page.request.post(BASE + "api/record", headers=ORIGIN, data={
        "key": "01", "value": G, "qualifiers": qualifiers, "description": "Amoxicillin", "defaultLinkType": "gs1:pip",
        "links": [link("gs1:pip"), *(link(t) for t in types)]})
    assert r.status in (200, 201), r.text()


def open_record(page, batch):
    page.goto(BASE); page.wait_for_timeout(500)
    page.fill("#key-value", G); page.fill("#q-10", batch); page.wait_for_timeout(200)
    page.click("#open"); page.wait_for_timeout(1000)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    sign_in(page, "ana", "ana-password-long")
    seed(page, {}, "gs1:recallStatus", "gs1:epil")
    seed(page, {"10": "LOTA"}, "gs1:recallStatus", "gs1:epil")
    seed(page, {"10": "LOTC"})

    # ------------------------------------------------------------ a batch without the product's safety links
    open_record(page, "LOTC")
    box = page.inner_text("#safety-warnings") if page.is_visible("#safety-warnings") else ""
    check("a batch lacking the product's safety-critical links: the box under the targets, both types named",
          "This record lacks safety-critical links" in box and "Batch LOTC" in box and "the GTIN itself" in box
          and "Recall status" in box and "leaflet" in box.lower(), box)
    check("…what the strict mode would do (off)", "would receive “not available for this batch”" in box, box)
    check("…no near-duplicate box", not page.is_visible("#dup-warnings"))
    shot(page, "editor-batch-walks-up")
    page.click("#add"); page.wait_for_timeout(200)
    row = page.locator("#links .link-row").last
    row.locator(".link-type").select_option("gs1:recallStatus")
    row.locator(".url").fill("https://farma.example/lotc/recall"); page.wait_for_timeout(900)
    box = page.inner_text("#safety-warnings") if page.is_visible("#safety-warnings") else ""
    check("…a recall link added in the form: only the leaflet left, before saving",
          "leaflet" in box.lower() and "Recall status" not in box, box)

    # ------------------------------------------------------------ a value close to an existing batch
    page.fill("#q-10", "lota"); page.wait_for_timeout(900)
    dup = page.inner_text("#dup-warnings") if page.is_visible("#dup-warnings") else ""
    check("a batch typed \"lota\": the box under the qualifiers names LOTA, before the record is opened",
          "Batch LOTA already exists for this key" in dup and "“lota”" in dup, dup)
    shot(page, "editor-near-duplicate")

    # ------------------------------------------------------------ the product
    open_record(page, "")
    box = page.inner_text("#safety-warnings") if page.is_visible("#safety-warnings") else ""
    check("the product: batches without a record of their own receive its links, both batches listed",
          "Batches without a record of their own receive these links" in box and "Batch LOTA" in box
          and "Batch LOTC" in box and "strict mode: off" in box, box)
    shot(page, "editor-product-level")

    # ------------------------------------------------------------ the batch with its own links
    seed(page, {"10": "LOTC"}, "gs1:recallStatus", "gs1:epil")
    open_record(page, "LOTC")
    check("the batch with its own links: no box", not page.is_visible("#safety-warnings")
          and not page.is_visible("#dup-warnings"))

    # ------------------------------------------------------------ the import's preview
    path = os.path.join(CONFIG, "links.csv")
    open(path, "wb").write(sheet.write_csv([["01", G, "/10/LOTD", "Amoxicillin LOTD", "gs1:pip",
                                             "https://farma.example/d", "en", "", "yes"]], {}))
    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    page.click("#records-import"); page.wait_for_timeout(200)
    page.set_input_files("#import-file", path); page.wait_for_timeout(1200)
    body = page.inner_text("#import-body")
    check("the import's preview: the row marked with what LOTD lacks", "⚠" in body and "Recall status" in body, body)
    check("…the warnings counted above the table", page.is_visible("#import-safety")
          and "1 record has a warning" in page.inner_text("#import-safety"), page.inner_text("#import-safety"))
    shot(page, "import-preview-warning")

    # ------------------------------------------------------------ the Resolution tab, in Portuguese
    pt = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    sign_in(pt, "ana", "ana-password-long")
    seed(pt, {"10": "LOTE"})
    pt.goto(BASE + "#organisation"); pt.wait_for_timeout(800)
    pt.click("#org-tab-resolution"); pt.wait_for_timeout(400)
    lack = pt.inner_text("#org-resolution-lacking") if pt.is_visible("#org-resolution-lacking") else ""
    check("the Resolution tab (Portuguese): one batch lacks safety-critical links, named with its types",
          "1 cadastro de lote ou série não tem um link crítico" in lack and "Lote LOTE" in lack
          and f"(01) {G}" in lack, lack)
    shot(pt, "organisation-resolution-lacking-pt")
    open_record(pt, "LOTE")
    box = pt.inner_text("#safety-warnings") if pt.is_visible("#safety-warnings") else ""
    check("…the editor's box in Portuguese", "Este cadastro não tem todos os links críticos" in box
          and "o próprio GTIN (todas as unidades)" in box, box)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
