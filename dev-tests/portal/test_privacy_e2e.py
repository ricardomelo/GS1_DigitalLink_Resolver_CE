"""
The privacy notice in a real browser (Playwright/Chromium; Documentation/adr/0017-privacy-notice.md): the footer's
link on the sign-in page and in the portal, the public page without signing in (the default notice in the reader's
language with the operator's name and the days, the language menu), the server administrators' screen (the text
starting from the default, the preview with the page's own renderer, publishing after the portal's confirmation, the
versions), the public page with the version in force, an earlier version marked as such, markup in a notice shown as
text, no screen for an organisation's administrator, and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_privacy_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
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
PORT, DATA_ENTRY_PORT = 8243, 3243
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_privacy_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0",
                  RESOLVER_ORG_NAME="Example Operator", RESOLVER_LOG_DAYS="90")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import privacy  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
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


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    visitor = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    visitor.on("pageerror", lambda e: errors.append(str(e)))

    # ------------------------------------------------------------ for anyone, before a version is published
    visitor.goto(BASE + "login"); visitor.wait_for_timeout(600)
    link = visitor.locator(".site-footer a[href='privacy']")
    check("the sign-in page: a footer link to the privacy notice", link.inner_text().strip() == "Aviso de privacidade")
    link.click(); visitor.wait_for_timeout(900)
    body = visitor.inner_text("#privacy-body")
    check("…which opens without signing in: the default notice in the reader's language",
          visitor.url == BASE + "privacy" and visitor.inner_text("h1").strip() == "Aviso de privacidade"
          and "Este resolver GS1 Digital Link é operado por Example Operator" in body, body[:300])
    check("…with the days requests are kept and the operator's responsibility, \"as is\"", "90 dias" in body
          and "estrita responsabilidade de quem opera esta instância" in body and "Nem a GS1" in body, body[-500:])
    check("…headings as headings, said to be the default notice, no list of versions yet",
          visitor.locator("#privacy-body h3").count() >= 4
          and "Aviso padrão" in visitor.inner_text("#privacy-version")
          and not visitor.is_visible("#privacy-history-box"))
    visitor.select_option("#locale", "en-GB"); visitor.wait_for_timeout(500)
    check("…in English when the reader chooses it", "This GS1 Digital Link resolver is operated by Example Operator"
          in visitor.inner_text("#privacy-body") and "Default notice" in visitor.inner_text("#privacy-version"))
    shot(visitor, "privacy-default")

    # ------------------------------------------------------------ the server administrators' screen
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "root", "root-password-long")
    check("the portal's footer: the privacy link", page.get_attribute(".site-footer a[data-i18n='footer.privacy']", "href")
          == "privacy")
    check("a server administrator: Privacy notice in the menu", page.locator(".sidebar-item[href='#privacy']").count() == 1)
    page.click(".sidebar-item[href='#privacy']"); page.wait_for_timeout(900)
    text = page.input_value("#privacy-text")
    check("…the screen: no version yet, the text starting from the default notice",
          page.is_visible("#privacy-view") and "No version published yet" in page.inner_text("#privacy-state")
          and text.startswith("# Privacy notice") and "{operator}" in text, text[:200])
    check("…the hint names the words replaced", "{operator} and {days}" in page.inner_text("#privacy-text-hint"))
    page.fill("#privacy-text", "# Our notice\n\nRun by {operator}, requests kept {days} days.\n\n- first\n- second\n\n"
                               "<img src=x onerror=\"window.hacked=1\"> https://example.org/contact.\n\n"
                               "<img src=y onerror=\"window.hacked=2\">")
    page.click("#privacy-preview-button"); page.wait_for_timeout(300)
    preview = page.locator("#privacy-preview")
    check("…the preview: heading, the words replaced, a list, the address a link, markup shown as text",
          preview.locator("h2").inner_text() == "Our notice"
          and "Run by Example Operator, requests kept 90 days." in preview.inner_text()
          and preview.locator("li").count() == 2 and preview.locator("img").count() == 0
          and "<img src=x" in preview.inner_text()
          and preview.locator("a").get_attribute("href") == "https://example.org/contact", preview.inner_html())
    page.fill("#privacy-note", "First version")
    page.click("#privacy-publish"); page.wait_for_timeout(300)
    check("…publishing asks first, in the portal's own dialog", page.is_visible("#ask-dialog")
          and "Publish version 1?" in page.inner_text("#ask-text"))
    page.click("#ask-cancel"); page.wait_for_timeout(300)
    check("…cancelled: nothing published", privacy.current() is None)
    page.click("#privacy-publish"); page.wait_for_timeout(300); page.click("#ask-ok"); page.wait_for_timeout(900)
    check("…confirmed: version 1 published and listed", "Version 1 published." in page.inner_text("#privacy-admin-status")
          and page.locator("#privacy-versions tr").count() == 1 and "First version" in page.inner_text("#privacy-versions")
          and (privacy.current() or {}).get("version") == 1)
    check("…the state says the version in force", "Version 1 of" in page.inner_text("#privacy-state"))
    shot(page, "privacy-admin")
    page.fill("#privacy-text", "# Our notice\n\nSecond version, by {operator}.")
    page.fill("#privacy-note", "Shorter")
    page.click("#privacy-publish"); page.wait_for_timeout(300); page.click("#ask-ok"); page.wait_for_timeout(900)
    check("…version 2 on top of the list", page.locator("#privacy-versions tr").count() == 2
          and page.inner_text("#privacy-versions tr:first-child td:first-child").strip() == "2")

    # ------------------------------------------------------------ the public page with versions
    visitor.goto(BASE + "privacy"); visitor.wait_for_timeout(900)
    check("the public page: the version in force, its number and date", "Second version, by Example Operator."
          in visitor.inner_text("#privacy-body") and "Version 2 of" in visitor.inner_text("#privacy-version")
          and not visitor.is_visible("#privacy-older"))
    check("…the versions listed, the one shown marked", visitor.locator("#privacy-history li").count() == 2
          and visitor.get_attribute("#privacy-history li:first-child a", "aria-current") == "page")
    visitor.click("#privacy-history li:nth-child(2) a"); visitor.wait_for_timeout(900)
    check("…an earlier version: its text, said to be earlier, a link to the one in force",
          "Run by Example Operator" in visitor.inner_text("#privacy-body") and visitor.is_visible("#privacy-older")
          and visitor.url.endswith("privacy?version=1"))
    check("…markup in a notice never run", visitor.locator("#privacy-body img").count() == 0
          and not visitor.evaluate("() => window.hacked"))
    shot(visitor, "privacy-version")
    visitor.goto(BASE + "privacy?version=7"); visitor.wait_for_timeout(700)
    check("…an unknown version said so", visitor.is_visible("#privacy-status")
          and "no such version" in visitor.inner_text("#privacy-status"))

    # ------------------------------------------------------------ an organisation's administrator, a phone
    other = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    sign_in(other, "ana", "ana-password-long")
    check("an organisation's administrator: no privacy screen in the menu",
          not other.is_visible(".sidebar-item[href='#privacy']"))
    other.goto(BASE + "#privacy"); other.wait_for_timeout(700)
    check("…nor by its address", not other.is_visible("#privacy-view"))
    phone = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 800}, is_mobile=True).new_page()
    phone.goto(BASE + "privacy"); phone.wait_for_timeout(800)
    check("a phone: the notice within the width", phone.evaluate("() => document.documentElement.scrollWidth") <= 392)
    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
