"""
The About page in a real browser (Playwright/Chromium; Documentation/adr/0024-name-and-about.md): the sign-in page's
footer link, the page without signing in (the version with its commit linked, the operator, the documents at the
running commit, the components in their four groups, the trademarks), in Portuguese and in Arabic (right to left), the
user menu's and the sidebar's item for a user of an organisation (before Options), and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_about_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
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
PORT, DATA_ENTRY_PORT = 8247, 3247
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_about_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0",
                  RESOLVER_ORG_NAME="Example Operator")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import csp_guard  # noqa: E402,F401  (fails the program on a Content-Security-Policy violation: ADR 0038)
import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import about  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("eva", "eva-password-long", "editor", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/portal/"
FACTS = about.facts()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    visitor = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    visitor.on("pageerror", lambda e: errors.append(str(e)))

    visitor.goto(BASE + "login"); visitor.wait_for_timeout(600)
    link = visitor.locator(".site-footer a[href='about']")
    check("the sign-in page: a footer link Sobre beside the privacy notice", link.inner_text().strip() == "Sobre")
    link.click(); visitor.wait_for_timeout(900)
    check("…which opens without signing in, in the reader's language",
          visitor.url == BASE + "about" and visitor.inner_text("h1").strip().startswith("Sobre")
          and "GS1 Digital Link Resolver Suite" in visitor.inner_text("h1"), visitor.inner_text("h1"))
    check("…operated by the operator", visitor.inner_text("#about-operator").strip() == "Operado por Example Operator")
    commit = visitor.locator("#about-version a")
    check("…the version, with the commit linked to the repository",
          commit.inner_text().strip() == FACTS["commit"][:7]
          and commit.get_attribute("href") == f'{FACTS["repository"]}/commit/{FACTS["commit"]}'
          and "Commit" in visitor.inner_text("#about-version"), visitor.inner_text("#about-version"))
    docs = visitor.locator("#about-docs a")
    hrefs = [docs.nth(i).get_attribute("href") for i in range(docs.count())]
    check("…five documents linked at the running commit",
          len(hrefs) == 5 and all(h.startswith(f'{FACTS["repository"]}/blob/{FACTS["commit"]}/') for h in hrefs)
          and "Guia do usuário do portal" in visitor.inner_text("#about-docs"), hrefs)
    check("…the licence at that commit", visitor.get_attribute("#about-licence", "href")
          == f'{FACTS["repository"]}/blob/{FACTS["commit"]}/LICENSE')
    groups = visitor.locator(".about-group h3")
    check("…the components in their four groups, each with its licence",
          [groups.nth(i).inner_text() for i in range(groups.count())]
          == ["Padrões e ferramentas GS1", "Plataforma", "Bibliotecas", "Dados e fontes"]
          and visitor.locator(".about-group li").count() == len(FACTS["components"])
          and visitor.locator(".about-group li .about-licence").count() == len(FACTS["components"]))
    check("…the trademarks and the operator's responsibility",
          "marcas da GS1 AISBL" in visitor.inner_text(".about-sheet")
          and "Quem opera esta instalação é responsável" in visitor.inner_text(".about-sheet"))
    shot(visitor, "about-pt-BR")
    visitor.select_option("#locale", "ar"); visitor.wait_for_timeout(500)
    check("…in Arabic, right to left, when the reader chooses it",
          visitor.get_attribute("html", "dir") == "rtl" and visitor.inner_text("h1").startswith("حول")
          and "المكتبات" in visitor.inner_text(".about-components"), visitor.inner_text("h1"))
    shot(visitor, "about-ar")

    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "login")
    page.fill("#username", "eva"); page.fill("#password", "eva-password-long"); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000); page.wait_for_timeout(700)
    item = page.locator(".sidebar-item[href='/portal/about']")
    check("an editor of an organisation: About in the sidebar", item.count() == 1 and item.inner_text().strip() == "About")
    page.click("#user-menu"); page.wait_for_timeout(200)
    labels = page.locator("#user-menu-panel .menu-item").all_inner_texts()
    labels = [x.strip() for x in labels]
    check("…and in the user menu, just before Options", "About" in labels and "Options" in labels
          and labels.index("Options") == labels.index("About") + 1, labels)
    page.click("#menu-about"); page.wait_for_timeout(900)
    check("…which opens the page", page.url == BASE + "about" and page.inner_text("h1").startswith("About"))

    phone = browser.new_context(locale="en-GB", viewport={"width": 375, "height": 800}).new_page()
    phone.on("pageerror", lambda e: errors.append(str(e)))
    phone.goto(BASE + "about"); phone.wait_for_timeout(800)
    width = phone.evaluate("document.documentElement.scrollWidth")
    check("a phone's width: no sideways scrolling", width <= 375, width)
    shot(phone, "about-phone")
    check("no script error on any page", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
