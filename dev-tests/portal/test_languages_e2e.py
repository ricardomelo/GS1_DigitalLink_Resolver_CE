"""
The interface languages in a real browser (Playwright/Chromium; Documentation/adr/0014-interface-languages.md): the
sign-in page in the browser's language (Spanish) before anyone signs in, its catalogue fetched on demand; the portal
in Japanese, the menu naming every language in itself, a change of language kept after a reload; Arabic right to left
(the sidebar on the right, the codes still left to right, no page wider than the screen on a computer or a phone); and
every screen in every language without a message key left showing (a missing text) or a script error.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_languages_e2e.py
"""
import json
import os
import re
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8203, 3199
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_languages_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL, os.path.join(PORTAL, "tools")]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import app as portal  # noqa: E402
import i18n_catalogue  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
LANGUAGES = ["pt-BR", "en-GB", "es", "fr", "de", "it", "tr", "zh-Hans", "ja", "ko", "hi", "ar"]
SCREENS = ["#overview", "#editor", "#records", "#requests", "#users", "#tenants", "#apikeys", "#audit", "#domains",
           "#branding", "#sso", "#organisation", "#alerts"]
KEYS = [k for k in i18n_catalogue.english() if k != "linkTypes" and "." in k]
KEY_PATTERN = re.compile(r"(?<![\w./:@-])(" + "|".join(re.escape(k) for k in sorted(KEYS, key=len, reverse=True))
                         + r")(?![\w/-])")
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {str(detail)[:500]}"))
    if not condition:
        failures.append(name)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"))


def sign_in(page):
    page.fill("#username", "root"); page.fill("#password", "root-password-long"); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=8000)
    page.wait_for_timeout(800)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []

    # ------------------------------------------------------------ the sign-in page in the browser's language
    ctx = browser.new_context(locale="es-ES", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    fetched = []
    page.on("request", lambda r: fetched.append(r.url) if "/locales/" in r.url else None)
    page.goto(BASE + "login"); page.wait_for_timeout(1200)
    spanish = i18n_catalogue.load("es")
    check("a Spanish browser: the sign-in page in Spanish before anyone signs in",
          page.get_attribute("html", "lang") == "es" and spanish["login.submit"] in page.inner_text("#login-submit"),
          (page.get_attribute("html", "lang"), page.inner_text("#login-submit")))
    check("…its catalogue fetched on demand, once", [u for u in fetched if u.endswith("/locales/es.json")] == [BASE + "locales/es.json"],
          fetched)
    sign_in(page)
    check("…and the portal after signing in", page.get_attribute("html", "lang") == "es"
          and spanish["overview.title"] in page.inner_text("#hero-title"), page.inner_text("#hero-title"))
    ctx.close()

    # ------------------------------------------------------------ Japanese, the menu, a change kept
    ctx = browser.new_context(locale="ja-JP", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login"); page.wait_for_timeout(1000)
    sign_in(page)
    japanese = i18n_catalogue.load("ja")
    check("a Japanese browser: the portal in Japanese", page.get_attribute("html", "lang") == "ja"
          and japanese["overview.title"] in page.inner_text("#hero-title"), page.inner_text("#hero-title"))
    menu = page.eval_on_selector_all("#locale option", "os => os.map(o => [o.value, o.textContent])")
    check("the language menu: every language, each named in itself, the Latin alphabet's first, alphabetically",
          menu == [[t, n] for t, n in [("de", "Deutsch"), ("en-GB", "English (UK)"), ("es", "Español"),
                                       ("fr", "Français"), ("it", "Italiano"), ("pt-BR", "Português (Brasil)"),
                                       ("tr", "Türkçe"), ("ar", "العربية"), ("hi", "हिन्दी"),
                                       ("zh-Hans", "中文（简体）"), ("ja", "日本語"), ("ko", "한국어")]], menu)
    page.select_option("#locale", "de"); page.wait_for_timeout(1200)
    german = i18n_catalogue.load("de")
    check("German chosen: the page changes at once", page.get_attribute("html", "lang") == "de"
          and german["overview.title"] in page.inner_text("#hero-title"), page.inner_text("#hero-title"))
    page.reload(); page.wait_for_timeout(1500)
    check("…and is kept after a reload", page.get_attribute("html", "lang") == "de", page.get_attribute("html", "lang"))
    ctx.close()

    # ------------------------------------------------------------ Arabic, right to left
    ctx = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login"); page.wait_for_timeout(1000)
    check("an Arabic browser: the sign-in page right to left", page.get_attribute("html", "dir") == "rtl"
          and page.get_attribute("html", "lang") == "ar")
    sign_in(page)
    box = page.locator(".sidebar").bounding_box()
    check("…the portal right to left, the sidebar on the right", page.get_attribute("html", "dir") == "rtl"
          and box and box["x"] > 640, box)
    content = page.locator("main:not([hidden]) .sheet").first.bounding_box()
    check("…the page's content beside it, not under it", content and box
          and content["x"] + content["width"] <= box["x"] + 1, (content, box))
    page.goto(BASE + "#editor"); page.wait_for_timeout(800)
    page.fill("#key-value", "09506000134352"); page.wait_for_timeout(300)
    check("…a code typed still reads left to right", page.eval_on_selector("#key-value", "e => getComputedStyle(e).direction")
          == "ltr")
    width = page.evaluate("() => document.documentElement.scrollWidth")
    check("…no page wider than the screen", width <= 1280, width)
    shot(page, "arabic-editor")
    page.goto(BASE + "#overview"); page.wait_for_timeout(1200)
    shot(page, "arabic-overview")
    ctx.close()
    phone = browser.new_context(locale="ar", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = phone.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login"); page.wait_for_timeout(1000)
    sign_in(page)
    wide = {}
    for screen in ("#overview", "#editor", "#records", "#requests", "#users"):
        page.goto(BASE + screen); page.wait_for_timeout(700)
        w = page.evaluate("() => document.documentElement.scrollWidth")
        if w > 392:
            wide[screen] = w
    check("Arabic on a phone: no screen wider than the phone", not wide, wide)
    phone.close()

    # ------------------------------------------------------------ every screen in every language
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login"); page.wait_for_timeout(800)
    sign_in(page)
    for tag in LANGUAGES:
        page.select_option("#locale", tag); page.wait_for_timeout(900)
        shown, wide = {}, {}
        for screen in SCREENS:
            page.goto(BASE + screen); page.wait_for_timeout(500)
            keys = sorted(set(KEY_PATTERN.findall(page.inner_text("body"))))
            if keys:
                shown[screen] = keys[:6]
            width = page.evaluate("() => document.documentElement.scrollWidth")
            if width > 1280:
                wide[screen] = width
        check(f"{tag}: every screen without a message key showing", not shown and page.get_attribute("html", "lang") == tag,
              shown)
        check(f"{tag}: …none wider than the screen (longer words)", not wide, wide)
    ctx.close()
    check("no script errors", not errors, errors[:5])
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
