"""
Administration and navigation in a real browser (Playwright/Chromium; Documentation/adr/0013-administration-and-
navigation.md, item 9.2): the sidebar of wide screens (built from the user menu, the current screen marked, folded and
remembered, absent on a phone), every screen at phone width without the page growing sideways, an organisation's page
(its tabs, prefixes as rows with a row checked as it is typed and the row a refusal names marked, saved through the
portal's own dialog), the organisation list's prefix rows, users' prefixes picked from the organisation's own (a
longer one added from the search box), the portal's own confirmation (cancel keeps, confirm acts, Escape cancels),
the alert history and its filters, the overview filtered by organisation with Operation for server administrators
only, the export limits (backlog item 9.8: the installation's maximum on the organisations' list, an organisation's
limits per role on its page's Exports tab), Portuguese.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_admin_nav_e2e.py             # SCREENSHOTS=<folder> keeps a picture of each step
"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8198, 3195
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_adminnav_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import monitor  # noqa: E402
import app as portal  # noqa: E402
import exportlimits  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234", "7891299"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
NOW = datetime(2026, 10, 17, 12, 0)
monitor._update(f"404:{acme['id']}", "alert", {"count": 40, "usual": 2}, NOW, ("alert-404-spike", None), tenant=acme["id"])
monitor._update("backup", "alert", {"reason": "late"}, NOW - timedelta(days=2), ("alert-backup-failed", None))
monitor._update("backup", "ok", {}, NOW - timedelta(days=1), ("alert-backup-failed", None))

BASE = f"http://127.0.0.1:{PORT}/portal/"
VIEWS = ["overview", "editor", "records", "requests", "users", "tenants", "domains", "branding", "sso", "apikeys",
         "audit", "organisation", "alerts"]
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.wait_for_timeout(700)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def overflow(page):
    """How many pixels the page is wider than the window (0: nothing to scroll sideways)."""
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    natives = []
    page.on("dialog", lambda d: (natives.append(d.message), d.accept()))

    # ------------------------------------------------------------ the layout fixes of 20 October and the project's logo
    page.goto(BASE + "login"); page.wait_for_timeout(500)
    left = page.evaluate("""() => [getComputedStyle(document.body).paddingInlineStart,
        document.getElementById('login-form').getBoundingClientRect().left,
        document.querySelector('.hero-inner h1').getBoundingClientRect().left]""")
    check("the sign-in page: no room kept for a sidebar it does not have, the form under the title", left[0] == "0px"
          and abs(left[1] - left[2]) < 1, left)
    check("…the project's logo in the header, not GS1's", page.get_attribute(".site-header img", "src") == "logo.svg"
          and page.evaluate("() => document.querySelector('.site-header img').naturalWidth") > 0)
    sign_in(page, "root", "root-password-long")
    check("the portal: the sidebar's room kept", page.evaluate("() => getComputedStyle(document.body).paddingInlineStart")
          == "240px")
    check("…the menu says Organisation management", page.inner_text(".sidebar-item[href='#organisation']").strip()
          == "Organisation management", page.inner_text(".sidebar-item[href='#organisation']"))
    wide = browser.new_context(locale="en-GB", viewport={"width": 1920, "height": 900}).new_page()
    sign_in(wide, "root", "root-password-long")
    wide.goto(BASE + "#records"); wide.wait_for_timeout(600)
    width = wide.evaluate("() => document.getElementById('records-view').getBoundingClientRect().width")
    check("a wide screen: the content up to 96rem (1,536 px), wider than before (76rem)", 1216 < width <= 1536, width)
    wide.close()

    # ------------------------------------------------------------ the sidebar
    check("wide screen: the sidebar, with the user menu's screens", page.is_visible("#sidebar")
          and page.locator(".sidebar-item").count() == page.locator(".menu-panel a.nav-item").count() == 14)
    check("…the current screen marked", page.get_attribute(".sidebar-item[href='#overview']", "aria-current") == "page"
          and page.get_attribute(".sidebar-item[href='#records']", "aria-current") is None)
    page.click(".sidebar-item[href='#records']"); page.wait_for_timeout(500)
    check("…a click opens the screen and marks it", page.is_visible("#records-view")
          and page.get_attribute(".sidebar-item[href='#records']", "aria-current") == "page")
    shot(page, "sidebar")
    page.click("#sidebar-toggle"); page.wait_for_timeout(300)
    width = page.evaluate("() => document.getElementById('sidebar').getBoundingClientRect().width")
    check("…folded to its icons", 50 < width < 80 and page.get_attribute("#sidebar-toggle", "aria-expanded") == "false",
          width)
    page.reload(); page.wait_for_timeout(800)
    check("…remembered in this browser", "sidebar-folded" in (page.get_attribute("body", "class") or ""))
    page.click("#sidebar-toggle"); page.wait_for_timeout(300)
    check("…unfolded again", page.evaluate("() => document.getElementById('sidebar').getBoundingClientRect().width") > 200)

    # ------------------------------------------------------------ the organisations' list and the organisation's page
    page.goto(BASE + "#tenants"); page.wait_for_timeout(700)
    rows = page.locator("#new-tenant-prefixes .prefix-row")
    check("new organisation: prefixes as rows, one to start with", rows.count() == 1)
    boxes = {name: page.locator(selector).first.bounding_box() for name, selector in (
        ("name", "#new-tenant-name"), ("prefix", "#new-tenant-prefixes .prefix-row input"),
        ("add", "#new-tenant-prefixes .prefix-add"), ("create", "#tenants-create > .btn"))}
    check("…the name level with the first prefix, Add GCP beside the prefixes, the button level with the fields",
          abs(boxes["name"]["y"] - boxes["prefix"]["y"]) < 2
          and boxes["add"]["x"] > boxes["prefix"]["x"] + boxes["prefix"]["width"]
          and abs(boxes["add"]["y"] + boxes["add"]["height"] / 2 - boxes["prefix"]["y"] - boxes["prefix"]["height"] / 2) < 4
          and boxes["create"]["x"] > boxes["add"]["x"] + boxes["add"]["width"]
          and abs(boxes["create"]["y"] + boxes["create"]["height"] / 2 - boxes["name"]["y"] - boxes["name"]["height"] / 2) < 6,
          boxes)
    page.fill("#new-tenant-name", "Gamma Teas")
    rows.nth(0).locator("input").fill("78a")
    check("…a row checked as it is typed", "4 to 12 digits" in rows.nth(0).inner_text()
          and rows.nth(0).get_attribute("class").find("is-invalid") >= 0)
    rows.nth(0).locator("input").fill("7896666")
    page.click("#new-tenant-prefixes .prefix-add"); page.wait_for_timeout(100)
    rows.nth(1).locator("input").fill("7897777")
    page.click("#new-tenant-prefixes .prefix-add"); page.wait_for_timeout(100)
    rows.nth(2).locator("input").fill("7898888")
    rows.nth(2).locator(".prefix-remove").click()
    check("…Add GCP and a remove button on each row", rows.count() == 2)
    page.click("#tenants-create button[type=submit]"); page.wait_for_timeout(500)
    check("…confirmed in the portal's own dialog, not the browser's", page.is_visible("#ask-dialog") and not natives
          and "Gamma Teas" in page.inner_text("#ask-text"), page.inner_text("#ask-text") if page.is_visible("#ask-dialog") else natives)
    shot(page, "ask-dialog")
    page.click("#ask-cancel"); page.wait_for_timeout(300)
    check("…cancelled: nothing created", not page.is_visible("#ask-dialog")
          and not any(t["name"] == "Gamma Teas" for t in tenants.load()))
    page.click("#tenants-create button[type=submit]"); page.wait_for_timeout(400)
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    check("…Escape cancels too", not any(t["name"] == "Gamma Teas" for t in tenants.load()))
    page.click("#tenants-create button[type=submit]"); page.wait_for_timeout(400)
    page.click("#ask-ok"); page.wait_for_timeout(800)
    gamma = next((t for t in tenants.load() if t["name"] == "Gamma Teas"), None)
    check("…confirmed: created with both prefixes", gamma and gamma["prefixes"] == ["7896666", "7897777"], gamma)
    page.locator("#tenants-body tr").nth(1).locator("button", has_text="Open").click()   # by name: Acme, Beta, Gamma
    page.wait_for_timeout(900)
    check("an organisation opened from the list: its page", page.is_visible("#organisation-view")
          and page.inner_text("#org-name") == "Beta Drinks" and page.url.endswith("#organisation?id=" + beta["id"]))
    check("…its tabs, prefixes first", page.locator("#org-tabs [role=tab]").count() == 8
          and page.get_attribute("#org-tab-prefixes", "aria-selected") == "true")
    org_rows = page.locator("#org-panel .prefix-row")
    page.click("#org-panel .prefix-add"); org_rows.nth(1).locator("input").fill("78912345")
    page.click("#org-save-prefixes"); page.wait_for_timeout(300)
    page.click("#ask-ok"); page.wait_for_timeout(800)
    check("…a prefix of another organisation refused, its row marked",
          "is-invalid" in (org_rows.nth(1).get_attribute("class") or "") and "Acme Foods" in page.inner_text("#org-status"),
          page.inner_text("#org-status"))
    org_rows.nth(1).locator("input").fill("7895556")
    page.click("#org-save-prefixes"); page.wait_for_timeout(300); page.click("#ask-ok"); page.wait_for_timeout(800)
    check("…a good one saved", tenants.get(beta["id"])["prefixes"] == ["7895555", "7895556"], tenants.get(beta["id"]))
    page.click("#org-tab-users"); page.wait_for_timeout(200)
    check("…its users", "bia" not in page.inner_text("#org-panel") and "No users" in page.inner_text("#org-panel"))
    page.click("#org-tab-brands"); page.wait_for_timeout(200)
    check("…another organisation's brands changed through support access", page.locator(
        "#org-panel button", has_text="support access").count() == 1)
    page.focus("#org-tab-brands"); page.keyboard.press("ArrowRight"); page.wait_for_timeout(200)
    check("…the arrow keys move between tabs", page.get_attribute("#org-tab-sso", "aria-selected") == "true")
    shot(page, "organisation")

    page.goto(BASE + "#organisation"); page.wait_for_timeout(900)
    page.click("#org-tab-users"); page.wait_for_timeout(200)
    check("the server administrator's own page: the operator's, without a prefixes tab",
          page.inner_text("#org-name") == "Operator (the installation)" and not page.is_visible("#org-tab-prefixes")
          and "root" in page.inner_text("#org-panel"), page.inner_text("#org-name"))

    # ------------------------------------------------------------ the users' prefix picker
    page.goto(BASE + "#users"); page.wait_for_timeout(800)
    page.select_option("#new-user-tenant", acme["id"]); page.wait_for_timeout(200)
    check("a user of an organisation: prefixes picked from its own", page.locator("#new-user-prefixes summary").count() == 1)
    page.click("#new-user-prefixes summary")
    check("…its prefixes listed", page.locator("#new-user-prefixes .picker-list input").count() == 2)
    page.fill("#new-user-prefixes input[type=search]", "78912990")
    check("…a longer prefix inside one can be added", page.is_visible("#new-user-prefixes .picker-add"))
    page.click("#new-user-prefixes .picker-add")
    page.fill("#new-user-name", "picker")
    page.click("#users-create button[type=submit]"); page.wait_for_timeout(800)
    check("…saved with it", (users.get("picker") or {}).get("prefixes") == ["78912990"], users.get("picker"))
    page.select_option("#new-user-tenant", ""); page.wait_for_timeout(200)
    check("…an operator's user: typed as before", page.locator("input#new-user-prefixes").count() == 1)
    shot(page, "users-picker")

    # ------------------------------------------------------------ alerts and the overview
    page.goto(BASE + "#alerts"); page.wait_for_timeout(900)
    check("the alert history: every alert, the ended one dated", page.locator("#alerts-body tr").count() == 2
          and "Spike of unregistered codes" in page.inner_text("#alerts-body") and "Ongoing" in page.inner_text("#alerts-body"))
    page.select_option("#alerts-tenant", acme["id"]); page.click("#alerts-filters button[type=submit]")
    page.wait_for_timeout(600)
    check("…filtered by organisation", page.locator("#alerts-body tr").count() == 1
          and "Acme Foods" in page.inner_text("#alerts-body"))
    shot(page, "alerts")
    page.goto(BASE + "#overview"); page.wait_for_timeout(900)
    check("the overview: an organisation filter and Operation for the server administrator",
          page.is_visible("#overview-tenant") and page.is_visible("#overview-operation-group"))
    page.select_option("#overview-tenant", acme["id"]); page.wait_for_timeout(900)
    check("…filtered: the scope named", "Acme Foods" in page.inner_text("#overview-scope"), page.inner_text("#overview-scope"))
    check("…the last check and the log's days with record quality", "Requests kept" in page.inner_text("#overview-records-facts")
          or "kept" in page.inner_text("#overview-records-facts").lower(), page.inner_text("#overview-records-facts"))

    # ------------------------------------------------------------ an organisation's administrator
    ana = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    ana.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(ana, "ana", "ana-password-long")
    check("an organisation's administrator: no organisation filter, no Operation",
          not ana.is_visible("#overview-tenant") and not ana.is_visible("#overview-operation-group"))
    ana.click(".sidebar-item[href='#organisation']"); ana.wait_for_timeout(900)
    check("…their organisation's page from the menu, in Portuguese", ana.inner_text("#org-name") == "Acme Foods"
          and "Prefixos" in ana.inner_text("#org-tabs") and ana.locator("#org-save-prefixes").count() == 0)

    # ------------------------------------------------------------ export limits (item 9.8)
    page.goto(BASE + "#tenants"); page.wait_for_timeout(700)
    check("the organisations' list: the installation's export maximum, empty (no limit)",
          page.is_visible("#export-maximum") and page.input_value("#export-maximum") == "")
    page.fill("#export-maximum", "20000"); page.click("#export-maximum-save"); page.wait_for_timeout(500)
    check("…saved", exportlimits.maximum() == 20000 and "20,000" in page.inner_text("#tenants-status"),
          page.inner_text("#tenants-status"))
    page.reload(); page.wait_for_timeout(900)
    check("…and shown when the list is opened again", page.input_value("#export-maximum") == "20000")
    page.fill("#export-maximum", "-3"); page.click("#export-maximum-save"); page.wait_for_timeout(300)
    check("…a negative maximum refused in the page", exportlimits.maximum() == 20000
          and "whole number" in page.inner_text("#tenants-status"), page.inner_text("#tenants-status"))
    page.goto(BASE + "#organisation?id=" + acme["id"]); page.wait_for_timeout(800)
    page.click("#org-tab-exports"); page.wait_for_timeout(300)
    check("the server administrator on an organisation's Exports tab: the maximum and a field per role",
          "20,000" in page.inner_text("#org-exports-maximum") and page.locator("#org-panel .org-export-limit").count() == 3
          and "up to 20,000 rows (the maximum)" in page.inner_text("#org-export-applies-admin"))
    shot(page, "organisation-exports")
    ana.reload(); ana.wait_for_timeout(1200)
    ana.click("#org-tab-exports"); ana.wait_for_timeout(400)
    check("an organisation's administrator: the Exports tab in Portuguese, the maximum told",
          "Exportações" in ana.inner_text("#org-tabs") and "20.000" in ana.inner_text("#org-exports-maximum"),
          ana.inner_text("#org-panel"))
    ana.fill("#org-export-reader", "0"); ana.fill("#org-export-editor", "5000"); ana.fill("#org-export-api", "")
    ana.click("#org-save-exports"); ana.wait_for_timeout(600)
    check("…limits saved and what applies shown", tenants.get(acme["id"])["exportLimits"] == {"reader": 0, "editor": 5000}
          and "nenhuma exportação" in ana.inner_text("#org-export-applies-reader")
          and "até 5.000 linhas" in ana.inner_text("#org-export-applies-editor")
          and "salvos" in ana.inner_text("#org-status"), (tenants.get(acme["id"]), ana.inner_text("#org-panel")))
    ana.fill("#org-export-editor", "20001"); ana.click("#org-save-exports"); ana.wait_for_timeout(400)
    check("…a limit above the maximum refused in the page", tenants.get(acme["id"])["exportLimits"]["editor"] == 5000
          and "20.000" in ana.inner_text("#org-status"), ana.inner_text("#org-status"))
    shot(ana, "organisation-exports-pt")

    # ------------------------------------------------------------ phone width
    phone = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 800}, is_mobile=True,
                                has_touch=True).new_page()
    phone.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(phone, "root", "root-password-long")
    check("a phone: no sidebar, the user menu", not phone.is_visible("#sidebar") and phone.is_visible("#user-button"))
    wide = {}
    for view in VIEWS:
        phone.goto(BASE + "#" + view); phone.wait_for_timeout(700)
        extra = overflow(phone)
        if extra > 1:
            wide[view] = extra
    check(f"every screen at 390 pixels: nothing wider than the phone ({len(VIEWS)} screens)", not wide, wide)
    phone.goto(BASE + "#organisation?id=" + acme["id"]); phone.wait_for_timeout(800)
    shot(phone, "organisation-phone")

    check("no script errors", not errors, errors)
    check("the browser's own dialogs never used", not natives, natives)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
