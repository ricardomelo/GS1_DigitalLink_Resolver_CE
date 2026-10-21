"""
The installation's appearance in a real browser (Playwright/Chromium; Documentation/adr/0019-appearance.md): the
Appearance screen of a server administrator (the original at first, the preview following the form, a light colour
refused with its contrast, the title, a logo, the tab icon and the colours saved), the portal's own header, colours, tab
title and favicon changed at once, the page served with them on reload, the sign-in page and the privacy notice showing them too, "Restore the original" after the portal's
confirmation, no screen for an organisation's administrator, Portuguese and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_appearance_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
"""
import io
import os
import sys
import tempfile
import threading

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8249, 3249
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_appearance_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("RESOLVER_LOG_DAYS", None)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
LOGO = os.path.join(CONFIG, "acme-logo.png")
Image.new("RGB", (132, 44), (26, 61, 43)).save(LOGO, "PNG")
ICON = os.path.join(CONFIG, "acme-icon.png")
Image.new("RGB", (64, 64), (232, 177, 0)).save(ICON, "PNG")
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
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
    page.wait_for_timeout(700)


def token(page, name):
    return page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")


def background(page, selector):
    return page.evaluate(f"getComputedStyle(document.querySelector('{selector}')).backgroundColor")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    sign_in(page, "root", "root-password-long")
    check("a server administrator has the screen in the menu, after the item's page",
          page.evaluate("[...document.querySelectorAll('.menu-panel a.nav-item')].map(a => a.id)"
                        ".indexOf('menu-appearance') - "
                        "[...document.querySelectorAll('.menu-panel a.nav-item')].map(a => a.id).indexOf('menu-branding')")
          == 1)
    page.goto(BASE + "#appearance"); page.wait_for_timeout(800)
    check("the screen: its title and the original", page.is_visible("#appearance-view")
          and page.inner_text("#hero-title") == "The installation's appearance"
          and page.inner_text("#appearance-state") == "Original appearance."
          and page.is_hidden("#appearance-reset"), page.inner_text("#appearance-state"))
    check("…the hint names the original title", "“GS1 Resolver Community Edition”"
          in page.inner_text("#appearance-view"), page.inner_text("#appearance-view")[:300])
    check("…the form holds the original colours, the title empty with the original as placeholder",
          [page.input_value(f"#appearance-{f}") for f in ("colour", "action", "accent")]
          == ["#002c6c", "#ce3d0d", "#f26334"] and page.input_value("#appearance-name") == ""
          and page.get_attribute("#appearance-name", "placeholder") == "GS1 Resolver Community Edition"
          and page.is_hidden("#appearance-logo-original"))
    check("…the preview: the original title and logo", page.inner_text("#appearance-preview-title")
          == "GS1 Resolver Community Edition" and page.get_attribute("#appearance-preview-logo", "src") == "logo.svg")
    shot(page, "1-original")

    page.fill("#appearance-name", "Acme Resolver")
    page.fill("#appearance-colour", "#1a3d2b")
    page.fill("#appearance-action", "#8a1538")
    page.fill("#appearance-accent", "#e8b100")
    page.set_input_files("#appearance-logo", LOGO); page.wait_for_timeout(400)
    page.set_input_files("#appearance-icon", ICON); page.wait_for_timeout(400)
    check("the preview's browser tab: the icon chosen and the title",
          page.get_attribute("#appearance-preview-icon", "src").startswith("data:image/png;base64,")
          and page.inner_text("#appearance-preview-tab-title") == "Acme Resolver")
    check("the preview follows the form: title, logo, band, button and tab mark",
          page.inner_text("#appearance-preview-title") == "Acme Resolver"
          and page.get_attribute("#appearance-preview-logo", "src").startswith("data:image/png;base64,")
          and background(page, ".appearance-preview-band") == "rgb(26, 61, 43)"
          and background(page, ".appearance-preview-button") == "rgb(138, 21, 56)"
          and page.evaluate("getComputedStyle(document.querySelector('.appearance-preview-tab')).borderBottomColor")
          == "rgb(232, 177, 0)", background(page, ".appearance-preview-band"))
    check("…nothing saved yet", store.get_setting("appearance") is None
          and page.inner_text(".site-header .product") == "GS1 Resolver Community Edition")
    shot(page, "2-preview")

    page.fill("#appearance-action", "#ffd700")
    page.click("#appearance-save"); page.wait_for_timeout(700)
    check("a light action colour refused, with its contrast", "hard to read on the action colour (1.4:1; at least 4.5:1)"
          in page.inner_text("#appearance-status") and store.get_setting("appearance") is None,
          page.inner_text("#appearance-status"))
    page.fill("#appearance-action", "#8a1538")
    page.click("#appearance-save"); page.wait_for_timeout(1200)
    check("saved", "Appearance saved" in page.inner_text("#appearance-status")
          and (store.get_setting("appearance") or {}).get("title") == "Acme Resolver",
          page.inner_text("#appearance-status"))
    check("…the header at once: the title and the logo", page.inner_text(".site-header .product") == "Acme Resolver"
          and "appearance/logo?v=" in page.get_attribute(".site-header .brand img", "src"),
          page.get_attribute(".site-header .brand img", "src"))
    check("…the colours at once (the pages' own tokens)", token(page, "--gs1-blue") == "#1A3D2B"
          and token(page, "--action") == "#8A1538" and token(page, "--gs1-orange") == "#E8B100"
          and background(page, ".hero") == "rgb(26, 61, 43)", (token(page, "--gs1-blue"), background(page, ".hero")))
    check("…the tab's title carries the new title", page.title().endswith("Acme Resolver")
          and "GS1 Resolver Community Edition" not in page.title(), page.title())
    check("…and the tab's icon (favicon)", page.locator("link[rel='icon']").count() == 1
          and "appearance/icon?v=" in page.get_attribute("link[rel='icon']", "href"),
          page.get_attribute("link[rel='icon']", "href"))
    raw = page.evaluate("(async () => (await fetch(location.pathname)).text())()")
    check("…the page itself now comes with them (no original before the script runs)",
          "<title>Acme Resolver</title>" in raw and '<span class="product">Acme Resolver</span>' in raw
          and 'href="appearance/icon?v=' in raw and 'src="appearance/logo?v=' in raw, raw[:400])
    page.route("**/api/appearance", lambda route: route.abort())     # the page alone, without appearance.js's answer
    page.reload(); page.wait_for_timeout(1000)
    check("…reloaded: the header, the tab title and the icon stay the operator's, from the page itself",
          page.inner_text(".site-header .product") == "Acme Resolver" and page.title().endswith("Acme Resolver")
          and "appearance/icon?v=" in page.get_attribute("link[rel='icon']", "href"), page.title())
    page.unroute("**/api/appearance")
    page.reload(); page.wait_for_timeout(1000)
    check("…the screen says who changed it, and offers the original back",
          page.inner_text("#appearance-state").startswith("Changed on") and "root" in page.inner_text("#appearance-state")
          and page.is_visible("#appearance-reset") and page.is_visible("#appearance-logo-original"),
          page.inner_text("#appearance-state"))
    check("…the hint still names the original title (not replaced by the new one)", "“GS1 Resolver Community Edition”"
          in page.inner_text("#appearance-view"), page.inner_text("#appearance-view")[:300])
    shot(page, "3-saved")

    other = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    other.goto(BASE + "login"); other.wait_for_timeout(900)
    check("the sign-in page shows it too: title, logo, colours, icon", other.inner_text(".site-header .product") == "Acme Resolver"
          and "appearance/icon?v=" in other.get_attribute("link[rel='icon']", "href") and "Acme Resolver" in other.title()
          and "appearance/logo?v=" in other.get_attribute(".site-header .brand img", "src")
          and token(other, "--action") == "#8A1538", other.inner_text(".site-header .product"))
    logo = other.evaluate("(async () => { const r = await fetch(document.querySelector('.site-header .brand img').src);"
                          " return [r.status, r.headers.get('content-type')]; })()")
    check("…its logo is the operator's", logo == [200, "image/png"], logo)
    other.goto(BASE + "privacy"); other.wait_for_timeout(900)
    check("…and the privacy notice", other.inner_text(".site-header .product") == "Acme Resolver"
          and token(other, "--gs1-blue") == "#1A3D2B", other.inner_text(".site-header .product"))
    other.close()

    page.click("#appearance-reset"); page.wait_for_timeout(300)
    check("restore: the portal's confirmation first", page.is_visible("#ask-dialog")
          and "Restore the original title, logo and colours" in page.inner_text("#ask-text"))
    page.click("#ask-cancel"); page.wait_for_timeout(300)
    check("…cancelled: nothing changes", (store.get_setting("appearance") or {}).get("title") == "Acme Resolver")
    page.click("#appearance-reset"); page.wait_for_timeout(300)
    page.click("#ask-ok"); page.wait_for_timeout(1200)
    check("…confirmed: the original back everywhere on the page",
          "Original appearance restored" in page.inner_text("#appearance-status")
          and store.get_setting("appearance") is None
          and page.inner_text(".site-header .product") == "GS1 Resolver Community Edition"
          and page.get_attribute(".site-header .brand img", "src") == "logo.svg"
          and page.get_attribute("link[rel='icon']", "href") == "favicon.png"
          and token(page, "--gs1-blue").upper() == "#002C6C" and "GS1 Resolver Community Edition" in page.title()
          and page.inner_text("#appearance-state") == "Original appearance." and page.is_hidden("#appearance-reset"),
          (page.inner_text("#appearance-status"), page.inner_text(".site-header .product"), token(page, "--gs1-blue")))
    shot(page, "4-restored")

    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(500)
    check("Portuguese", page.inner_text("#hero-title") == "Aparência da instalação"
          and page.inner_text("#appearance-reset") == "Voltar ao original"
          and "“GS1 Resolver Community Edition”" in page.inner_text("#appearance-view"), page.inner_text("#hero-title"))
    page.select_option("#locale", "en-GB"); page.wait_for_timeout(300)

    ana = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    sign_in(ana, "ana", "ana-password-long")
    check("an organisation's administrator: no screen in the menu", ana.query_selector("#menu-appearance") is None
          or not ana.is_visible("#menu-appearance"))
    ana.goto(BASE + "#appearance"); ana.wait_for_timeout(700)
    check("…nor by its address", ana.is_hidden("#appearance-view"))
    ana.close()

    phone = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 800}, is_mobile=True).new_page()
    sign_in(phone, "root", "root-password-long")
    phone.goto(BASE + "#appearance"); phone.wait_for_timeout(800)
    width = phone.evaluate("document.documentElement.scrollWidth")
    check("a phone's width: no sideways scrolling", width <= 390, width)
    shot(phone, "5-phone")
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
