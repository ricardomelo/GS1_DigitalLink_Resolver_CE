"""
Every link type and language of the targets in a real browser (Playwright/Chromium; item 9.4): the link type menu in
groups ordered by the key type (the most used first for a GTIN, places for a GLN) and changed when the key type
changes, a row's type kept; the language field searched in a list of every language the browser names, a name typed
read as its code, several languages, a malformed one pointed out and the save refused until it is fixed; Portuguese.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_link_types_e2e.py
"""
import os
import sys
import unicodedata
import tempfile
import threading

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8201, 3198
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_linktypes_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import app as portal  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
GTIN = "09506000134352"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)




def groups(page, row=0):
    return page.eval_on_selector_all(f"#links .link-row >> nth={row}", "rows => [...rows[0].querySelectorAll('.link-type optgroup')].map(g => g.label)")


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login")
    page.fill("#username", "root"); page.fill("#password", "root-password-long"); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.goto(BASE); page.wait_for_timeout(800)
    page.fill("#key-value", GTIN); page.wait_for_timeout(300); page.click("#open"); page.wait_for_timeout(900)
    found = groups(page)
    check("a GTIN: the link types in eight groups, the most used first", len(found) == 8 and found[0] == "Most used"
          and "Places" in found, found)
    check("…every link type of the vocabulary", page.locator("#links .link-row .link-type option").count() >= 57)
    page.select_option("#links .link-row .link-type", "gs1:dpp"); page.wait_for_timeout(200)
    check("…a new one chosen, its help shown", "passport" in page.inner_text("#links .link-row .row-help").lower(),
          page.inner_text("#links .link-row .row-help"))
    page.select_option("#key-type", "414"); page.wait_for_timeout(500)
    found = groups(page)
    check("a GLN: places first, the row's type kept", found[0] == "Places"
          and page.input_value("#links .link-row .link-type") == "gs1:dpp", found)
    page.select_option("#key-type", "01"); page.wait_for_timeout(300)
    page.fill("#key-value", GTIN); page.wait_for_timeout(300); page.click("#open"); page.wait_for_timeout(400)
    if page.is_visible("#ask-dialog"):                  # the type chosen above is an unsaved change
        page.click("#ask-ok")
    page.wait_for_timeout(700)
    field = page.locator("#links .link-row .language").first
    field.fill(""); field.press("Escape"); page.click("#links .link-row .combo-toggle"); page.wait_for_timeout(300)
    names = page.eval_on_selector_all("#language-picker-list li", "lis => lis.map(li => li.firstChild.textContent)")
    check("the languages: the row's button opens a list of every language the browser names, scrolled",
          page.is_visible("#language-picker") and len(names) >= 200 and "German" in names
          and page.eval_on_selector("#language-picker-list", "ul => ul.scrollHeight > ul.clientHeight")
          and "type to filter" in page.inner_text("#language-picker-head"), (len(names), page.inner_text("#language-picker-head")))
    folded = [unicodedata.normalize("NFD", n).encode("ascii", "ignore").decode().lower() for n in names]
    check("…in alphabetical order, accents aside (every name here is in the Latin alphabet)",
          folded == sorted(folded), [(a, b) for a, b in zip(names, names[1:])
                                     if unicodedata.normalize("NFD", a).encode("ascii", "ignore").decode().lower()
                                     > unicodedata.normalize("NFD", b).encode("ascii", "ignore").decode().lower()][:5])
    field.type("germ"); page.wait_for_timeout(200)
    shown = page.eval_on_selector_all("#language-picker-list li", "lis => lis.map(li => li.dataset.code)")
    check("…filtered by what is typed, with the count", "de" in shown and len(shown) < 10
          and f"{len(shown)} of " in page.inner_text("#language-picker-head"), (shown, page.inner_text("#language-picker-head")))
    page.click("#language-picker-list li[data-code='de']"); page.wait_for_timeout(200)
    check("…a click writes its code", field.input_value() == "de" and not page.is_visible("#language-picker")
          and page.eval_on_selector("#links .link-row", "li => li.dataset.hreflang") == '["de"]', field.input_value())
    field.fill("de, fren"); page.wait_for_timeout(150); field.press("ArrowDown"); field.press("Enter"); page.wait_for_timeout(200)
    check("…the keyboard chooses the language after the last comma", field.input_value() == "de, fr"
          and page.eval_on_selector("#links .link-row", "li => li.dataset.hreflang") == '["de","fr"]', field.input_value())
    field.press("ArrowDown"); page.wait_for_timeout(100); field.press("Escape"); page.wait_for_timeout(100)
    check("…Escape closes it", not page.is_visible("#language-picker"))
    field.fill("xyzzy"); page.wait_for_timeout(150)
    check("…nothing found: a code can still be typed", "pt-BR" in page.inner_text("#language-picker-head"),
          page.inner_text("#language-picker-head"))
    field.fill("German"); field.dispatch_event("change"); page.wait_for_timeout(200)
    check("…a name typed read as its code", field.input_value() == "de"
          and page.eval_on_selector("#links .link-row", "li => li.dataset.hreflang") == '["de"]', field.input_value())
    field.fill("pt-BR, en"); field.dispatch_event("change"); page.wait_for_timeout(200)
    check("…several languages", page.eval_on_selector("#links .link-row", "li => li.dataset.hreflang") == '["pt-BR","en"]')
    field.fill("portuguese!"); field.dispatch_event("change"); page.wait_for_timeout(200)
    check("…a malformed one pointed out", field.get_attribute("aria-invalid") == "true")
    page.select_option("#links .link-row .link-type", "gs1:dpp")
    page.fill("#description", "Lamp"); page.fill("#links .link-row .url", "https://brand.example/dpp")
    page.click("#save"); page.wait_for_timeout(600)
    check("…and the save refused until it is fixed", "not a language code" in page.inner_text("#status")
          and f"01_{GTIN}" not in mock_data_entry.DB, page.inner_text("#status"))
    field.fill("fr-CA"); field.dispatch_event("change"); page.click("#save"); page.wait_for_timeout(900)
    saved = mock_data_entry.DB.get(f"01_{GTIN}", {}).get("entries", [{}])[0].get("links", [])
    check("…fixed: saved with the new link type and the regional language",
          [(l["linktype"], l["hreflang"]) for l in saved] == [("gs1:dpp", ["fr-CA"])], saved)
    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(500)
    field.fill(""); field.press("Escape"); page.click("#links .link-row .combo-toggle"); page.wait_for_timeout(300)
    check("in Portuguese: the groups and the languages' names", "Mais usados" in groups(page)
          and page.inner_text("#language-picker-list li[data-code='de']").startswith("Alemão")
          and "digite para filtrar" in page.inner_text("#language-picker-head"), groups(page))
    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
