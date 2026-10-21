"""
The label panel's symbols and scanning environments in a real browser (Playwright/Chromium; Documentation/adr/
0010-label-studio.md, section 7; item 9.3): the 2D symbol and the scanning environment offered, the symbols and sizes
each environment takes (the others disabled), the QR options shown for a QR code only, the linear symbol hidden where
none is used, the preview's line naming the Data Matrix, its modules and X-dimension, the downloads carrying the
choices, the HRI as text, the choices remembered, Portuguese.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_datamatrix_e2e.py
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
PORT, DATA_ENTRY_PORT = 8199, 3196
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_datamatrix_e2e_{os.getpid()}",
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


def enabled(page, select):
    return page.eval_on_selector_all(f"{select} option", "os => os.filter(o => !o.disabled).map(o => o.value)")


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login")
    page.fill("#username", "root"); page.fill("#password", "root-password-long"); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.goto(BASE); page.wait_for_timeout(800)
    page.fill("#key-value", GTIN); page.wait_for_timeout(900)
    check("the label offers the 2D symbol and the scanning environment, a QR code at retail by default",
          page.input_value("#opt-symbol") == "qr" and page.input_value("#opt-env") == "retail"
          and enabled(page, "#opt-symbol") == ["qr", "dm", "gs1dm"] and page.is_visible("#opt-version-field"))
    check("…retail: every size", enabled(page, "#opt-size") == ["80", "90", "100", "120", "150", "200"])
    check("for a GTIN, the trade items' environments and direct part marking, not those of other keys",
          enabled(page, "#opt-env") == ["retail", "retail-gd", "distribution", "pharmacy", "pharmacy-gd", "healthcare",
                                        "other", "dpm"] and page.is_visible("#opt-env-hint"), enabled(page, "#opt-env"))
    page.select_option("#opt-env", "retail-gd"); page.wait_for_timeout(900)
    check("retail and general distribution (table 3): 80 to 100 %, the target 0.990 mm",
          enabled(page, "#opt-size") == ["80", "90", "100"] and "0.990" in page.inner_text("#opt-size option[value='100']"))
    page.select_option("#opt-env", "healthcare"); page.wait_for_timeout(900)
    check("healthcare: Data Matrix only (the QR code disabled), GS1 DataMatrix chosen",
          enabled(page, "#opt-symbol") == ["dm", "gs1dm"] and page.input_value("#opt-symbol") == "gs1dm")
    check("…the QR options hidden", not page.is_visible("#opt-version-field") and not page.is_visible("#opt-ecl-field"))
    check("…sizes within 0.254–0.990 mm (table 6), labelled with the X-dimension",
          enabled(page, "#opt-size") == ["80", "90", "100", "120", "150", "200"]
          and "0.380" in page.inner_text("#opt-size option[value='100']"), page.inner_text("#opt-size"))
    check("…the preview names the symbol, its modules and the X-dimension", "GS1 DataMatrix" in page.inner_text("#qr-info")
          and "0.380 mm" in page.inner_text("#qr-info"), page.inner_text("#qr-info"))
    href = page.get_attribute("#download-svg", "href") or ""
    check("…the downloads carry the choices", "symbol=gs1dm" in href and "env=healthcare" in href, href)
    page.select_option("#opt-env", "dpm"); page.wait_for_timeout(900)
    check("direct part marking: no linear symbol, sizes from 90 %", not page.is_visible("#opt-linear-field")
          and enabled(page, "#opt-size") == ["90", "100", "120", "150", "200"])
    page.select_option("#opt-hritext", "text"); page.wait_for_timeout(700)
    check("the HRI as text in the SVG", "hritext=text" in (page.get_attribute("#download-svg", "href") or ""))
    page.reload(); page.wait_for_timeout(900)
    page.fill("#key-value", GTIN); page.wait_for_timeout(900)
    check("the choices remembered", page.input_value("#opt-env") == "dpm" and page.input_value("#opt-symbol") == "gs1dm"
          and page.input_value("#opt-hritext") == "text")
    page.select_option("#opt-env", "retail"); page.select_option("#opt-symbol", "qr"); page.wait_for_timeout(900)
    check("back at retail with a QR code: the QR options again", page.is_visible("#opt-version-field")
          and "Version" in page.inner_text("#qr-info"), page.inner_text("#qr-info"))
    page.select_option("#key-type", "00"); page.fill("#key-value", "095060001234567893"); page.wait_for_timeout(900)
    check("an SSCC: logistic units (table 5) and direct part marking only, table 5 chosen",
          enabled(page, "#opt-env") == ["logistics", "dpm"] and page.input_value("#opt-env") == "logistics"
          and "0.743" in page.inner_text("#opt-size option[value='100']"),
          (page.input_value("#opt-env"), page.inner_text("#opt-size option[value='100']")))
    page.select_option("#key-type", "01"); page.fill("#key-value", GTIN); page.wait_for_timeout(900)
    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(400)
    check("in Portuguese", "Ambiente de leitura" in page.inner_text(".label-options")
          and "Ponto de venda no varejo" in page.inner_text("#opt-env"))
    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
