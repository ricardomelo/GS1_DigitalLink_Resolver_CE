"""
Forwarding in a real browser (Playwright/Chromium; Documentation/adr/0018-forwarding.md): the Forwarding screen of a
server administrator (the resolver of last resort switched on with GS1's address, an address refused; prefix rules
added, one over an organisation's prefix with the warning, edited, switched off from the list, removed after the
portal's confirmation), the overview's Forwarding group and quality tiles, the Requests screen's new outcomes, no
screen nor group for an organisation's administrator, Portuguese and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_forwarding_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8247, 3247
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_forwarding_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("RESOLVER_LOG_DAYS", None)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import forwarding  # noqa: E402
import requestlog  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
NOW = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=3)
for value, outcome, n, to in (("09521234000019", "forwarded", 3, "other.example.net"),
                              ("09506000134376", "fallback", 5, "id.gs1.org"),
                              ("07891234500014", "fallback", 2, "id.gs1.org")):
    for _ in range(n):
        requestlog.events().insert_one({"t": NOW, "m": "GET", "f": "uri", "s": 307, "o": outcome, "dev": "mobile",
                                        "ms": 10, "ai": "01", "v": value, "cp": value[1:], "to": to,
                                        "expiresAt": NOW + timedelta(days=90)})
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


def status(page):
    return page.inner_text("#forwarding-status")


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "root", "root-password-long")

    # ------------------------------------------------------------ the screen
    check("a server administrator: Forwarding in the menu", page.inner_text(".sidebar-item[href='#forwarding']").strip()
          == "Forwarding")
    page.click(".sidebar-item[href='#forwarding']"); page.wait_for_timeout(900)
    check("…the screen: the resolver of last resort off, GS1's address offered",
          page.is_visible("#forwarding-view") and not page.is_checked("#fallback-enabled")
          and page.get_attribute("#fallback-url", "placeholder") == "https://id.gs1.org"
          and "Off:" in page.inner_text("#fallback-state") and page.is_visible("#forwarding-empty"),
          page.inner_text("#fallback-state"))
    page.check("#fallback-enabled"); page.click("#fallback-save"); page.wait_for_timeout(700)
    check("…switched on: GS1's global resolver", "Resolver of last resort on: https://id.gs1.org." in status(page)
          and "On: codes not registered here go to https://id.gs1.org." in page.inner_text("#fallback-state")
          and forwarding.fallback()["enabled"] is True, status(page))
    page.fill("#fallback-url", "http://resolver.example.net"); page.click("#fallback-save"); page.wait_for_timeout(700)
    check("…an http address refused, with the reason", "complete https:// address" in status(page)
          and forwarding.fallback()["url"] == "https://id.gs1.org", status(page))
    page.fill("#fallback-url", "")

    page.fill("#rule-prefix", "9521234"); page.fill("#rule-target", "https://other.example.net")
    page.fill("#rule-note", "Moved"); page.click("#rule-save"); page.wait_for_timeout(700)
    rows = page.locator("#forwarding-rules tr")
    check("a rule added: listed with its destination, the path kept, on", rows.count() == 1
          and "9521234" in rows.nth(0).inner_text() and "https://other.example.net" in rows.nth(0).inner_text()
          and "kept" in rows.nth(0).inner_text() and rows.nth(0).locator("input[type=checkbox]").is_checked()
          and "Rule for prefix 9521234 saved." in status(page), (rows.count(), status(page)))
    check("…the form emptied", page.input_value("#rule-prefix") == "" and page.input_value("#rule-target") == "")
    page.fill("#rule-prefix", "789"); page.fill("#rule-target", "https://brazil.example.net/scan")
    page.select_option("#rule-mode", "fixed"); page.click("#rule-save"); page.wait_for_timeout(700)
    check("a rule over an organisation's prefix: saved with a warning naming it", "Codes of Acme Foods" in status(page)
          and "is-warn" in (page.get_attribute("#forwarding-status", "class") or "")
          and "Acme Foods" in page.inner_text("#forwarding-rules tr:first-child td.is-warn")
          and "fixed address" in page.inner_text("#forwarding-rules tr:first-child"), status(page))
    shot(page, "forwarding")
    page.locator("#forwarding-rules tr:first-child button", has_text="Edit").click(); page.wait_for_timeout(300)
    check("…edit: the form filled, the prefix fixed", page.input_value("#rule-prefix") == "789"
          and page.get_attribute("#rule-prefix", "readonly") is not None
          and page.input_value("#rule-mode") == "fixed" and page.is_visible("#rule-cancel"))
    page.fill("#rule-target", "https://brazil.example.net/qr"); page.click("#rule-save"); page.wait_for_timeout(700)
    check("…saved", forwarding.rule("789")["target"] == "https://brazil.example.net/qr"
          and page.input_value("#rule-prefix") == "" and not page.is_visible("#rule-cancel"))
    page.locator("#forwarding-rules tr:first-child input[type=checkbox]").uncheck(); page.wait_for_timeout(700)
    check("…switched off from the list", forwarding.rule("789")["enabled"] is False
          and "is-off" in (page.get_attribute("#forwarding-rules tr:first-child", "class") or ""))
    page.locator("#forwarding-rules tr:first-child button", has_text="Remove").click(); page.wait_for_timeout(300)
    check("…removing asks first, in the portal's own dialog", page.is_visible("#ask-dialog")
          and "prefix 789" in page.inner_text("#ask-text"))
    page.click("#ask-cancel"); page.wait_for_timeout(300)
    check("…cancelled: kept", len(forwarding.rules()) == 2)
    page.locator("#forwarding-rules tr:first-child button", has_text="Remove").click(); page.wait_for_timeout(300)
    page.click("#ask-ok"); page.wait_for_timeout(700)
    check("…confirmed: removed", [r["prefix"] for r in forwarding.rules()] == ["9521234"]
          and page.locator("#forwarding-rules tr").count() == 1)

    # ------------------------------------------------------------ the overview and the Requests screen
    page.goto(BASE + "#overview"); page.wait_for_timeout(1500)
    tiles = page.inner_text("#overview-forwarding-tiles")
    check("the overview: the Forwarding group with the last resort, its requests, the rules and theirs",
          page.is_visible("#overview-forwarding-group") and "Resolver of last resort" in tiles and "on" in tiles
          and "1 of 1" in tiles and "7" in tiles and "3" in tiles, tiles)
    check("…the codes most sent to the last resort", page.inner_text("#overview-fallback-body tr:first-child")
          .split("\t")[0].strip() == "/01/09506000134376", page.inner_text("#overview-fallback-body"))
    check("…the requests by rule", "9521234" in page.inner_text("#overview-byrule-body")
          and "https://other.example.net" in page.inner_text("#overview-byrule-body"))
    check("…quality: forwarded and sent to the last resort apart", "Forwarded by prefix rules"
          in page.inner_text("#overview-quality-tiles") and "Sent to the resolver of last resort"
          in page.inner_text("#overview-quality-tiles"))
    shot(page, "forwarding-overview")
    page.click("#overview-forwarding-group a[href='#forwarding']"); page.wait_for_timeout(700)
    check("…a link to the screen", page.is_visible("#forwarding-view"))
    page.goto(BASE + "#requests"); page.wait_for_timeout(1200)
    options = page.eval_on_selector_all("#requests-outcome option", "os => os.map(o => o.value)")
    check("Requests: the two outcomes in the filter", "forwarded" in options and "fallback" in options, options)
    page.select_option("#requests-outcome", "forwarded"); page.click("#requests-filters button[type=submit]")
    page.wait_for_timeout(900)
    body = page.inner_text("#requests-body")
    check("…filtered, the outcome named in each row", body.count("Forwarded by prefix") == 3, body[:300])

    # ------------------------------------------------------------ others
    ana = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000}).new_page()
    sign_in(ana, "ana", "ana-password-long")
    check("an organisation's administrator: no Forwarding screen, no group in the overview",
          ana.locator(".sidebar-item[href='#forwarding']").count() == 0 or not ana.is_visible(".sidebar-item[href='#forwarding']"))
    check("…its overview without the group", not ana.is_visible("#overview-forwarding-group"))
    ana.goto(BASE + "#forwarding"); ana.wait_for_timeout(700)
    check("…nor by its address", not ana.is_visible("#forwarding-view"))
    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(500)
    check("in Portuguese", page.inner_text(".sidebar-item[href='#forwarding']").strip() == "Encaminhamento")
    phone = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 800}, is_mobile=True).new_page()
    sign_in(phone, "root", "root-password-long")
    phone.goto(BASE + "#forwarding"); phone.wait_for_timeout(900)
    check("a phone: the screen within the width", phone.evaluate("() => document.documentElement.scrollWidth") <= 392)
    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
