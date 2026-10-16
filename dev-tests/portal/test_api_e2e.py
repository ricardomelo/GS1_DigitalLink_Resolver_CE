"""
The API keys screen in a real browser (Playwright/Chromium) and the key it makes used against the running portal
(Documentation/adr/0005-tenant-api.md): an organisation's administrator creates a key, sees it once with an example,
a system uses it through /portal/api/v1, the list shows the last use, the key is revoked on screen and refused;
an editor has no such screen; both languages and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock requests && playwright install chromium
  python dev-tests/portal/test_api_e2e.py
"""
import os
import re
import sys
import tempfile
import threading

import requests
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8196, 3195
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_api_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL=f"http://127.0.0.1:{PORT}")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("root", "root-password-long", "admin", must_change=False)
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def gtin(body13: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)       # sign-in opens the overview (ADR 0007)
    page.goto(BASE)
    page.wait_for_timeout(500)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    ctx = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "ana", "ana-password-long")
    page.click("#user-button")
    check("an organisation's administrator has API keys in the menu", page.is_visible("#menu-apikeys")
          and page.inner_text("#menu-apikeys").strip() == "Chaves de API")
    page.click("#menu-apikeys"); page.wait_for_timeout(700)
    check("choosing a menu item closes the menu, though the pointer is still over it", not page.is_visible("#menu-logout"))
    check("the screen says whose records the keys reach, no key yet", page.is_visible("#apikeys-view")
          and "Acme Foods" in page.inner_text("#apikeys-scope") and page.is_visible("#apikeys-empty"))
    check("validity choices up to the longest allowed, 90 days chosen",
          page.eval_on_selector_all("#new-apikey-days option", "o => o.map(x => x.value)") == ["30", "90", "180", "365"]
          and page.input_value("#new-apikey-days") == "90")
    page.fill("#new-apikey-name", "Integração ERP")
    page.check("#apikeys-create input[value='records:write']")
    page.click("#apikeys-create button[type=submit]"); page.wait_for_timeout(900)
    key = page.inner_text("#apikey-value").strip()
    check("the key is shown once, with an example request", re.fullmatch(r"rk_[0-9a-f]{12}\.[A-Za-z0-9_-]{43}", key) is not None
          and "Chave Integração ERP criada." in page.inner_text("#apikeys-status")
          and key in page.inner_text("#apikey-example") and "/portal/api/v1/" in page.inner_text("#apikey-example"),
          (page.inner_text("#apikeys-status"), page.inner_text("#apikey-example")))
    row = page.inner_text("#apikeys-body tr:first-child")
    check("the list shows it: name, id, scopes, creator, active, never used", "Integração ERP" in row and key[3:15] in row
          and "ler, gravar" in row and "ana" in row and "Ativa" in row, row)
    check("the description of the API is linked", page.get_attribute("#apikeys-openapi", "href") == "api/v1/openapi.json")

    # a system uses the key
    value = gtin("0789123450001")
    headers = {"Authorization": f"Bearer {key}"}
    r = requests.put(f"{BASE}api/v1/records/01/{value}", headers=headers, timeout=10,
                     json={"description": "Café 500 g", "links": [{"linkType": "gs1:pip", "url": "https://acme.example/cafe",
                                                                    "hreflang": ["pt"]}]})
    check("the key writes a record through the API", r.status_code == 201 and r.json()["created"] is True, r.text)
    r = requests.get(f"{BASE}api/v1/records", headers=headers, timeout=10)
    check("…and lists it", r.status_code == 200 and r.json()["total"] == 1)
    page.goto(BASE + "#records"); page.wait_for_timeout(900)
    check("the record is in the portal, changed by api:<id>", "Café 500 g" in page.inner_text("#records-body")
          and f"api:{key[3:15]}" in page.inner_text("#records-body"), page.inner_text("#records-body")[:300])
    page.goto(BASE + "#apikeys"); page.wait_for_timeout(800)
    check("leaving the screen removes the key from the page", page.inner_text("#apikey-value") == ""
          and key not in page.content())
    check("the new key is not shown again; the list has its last use",
          not page.is_visible("#apikey-new") and "—" not in page.inner_text("#apikeys-body tr:first-child td:nth-child(6)"),
          (page.is_visible("#apikey-new"), page.inner_text("#apikeys-body tr:first-child")))

    asked = []
    page.click("#apikeys-body tr:first-child button.btn-danger-ghost"); page.wait_for_timeout(300)
    if page.is_visible("#ask-dialog"):                  # the portal's own confirmation (ADR 0013)
        asked.append(page.inner_text("#ask-text")); page.click("#ask-ok")
    page.wait_for_timeout(900)
    check("revoke: asked first, then the state says who", asked and "Integração ERP" in asked[0]
          and "Revogada por ana" in page.inner_text("#apikeys-body tr:first-child")
          and page.locator("#apikeys-body tr:first-child button").count() == 0, page.inner_text("#apikeys-body"))
    r = requests.get(f"{BASE}api/v1/", headers=headers, timeout=10)
    check("the revoked key is refused at once", r.status_code == 401 and r.json()["code"] == "api.keyInvalid")
    page.goto(BASE + "#audit"); page.wait_for_timeout(900)
    audit = page.inner_text("#audit-body")
    check("the audit trail shows the key created and revoked", "Chave de API criada" in audit and "Chave de API revogada" in audit)

    page.select_option("#locale", "en-GB"); page.goto(BASE + "#apikeys"); page.wait_for_timeout(800)
    check("in English", page.inner_text("#apikeys-view h2") == "New API key" and "Revoked by ana" in page.inner_text("#apikeys-body"))
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(300)
    check("phone width: no sideways scroll", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    ctx.close()

    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, "root", "root-password-long")
    page.goto(BASE + "#apikeys"); page.wait_for_timeout(800)
    check("a server administrator's keys are the operator's", "operator's records" in page.inner_text("#apikeys-scope")
          and page.is_visible("#apikeys-empty"))
    ctx.close()

    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    sign_in(page, "edu", "edu-password-long")
    page.click("#user-button")
    check("an editor has no API keys", not page.is_visible("#menu-apikeys"))
    page.goto(BASE + "#apikeys"); page.wait_for_timeout(600)
    check("…and the address shows the editor", not page.is_visible("#apikeys-view") and page.is_visible("#editor-view"))
    check("no error in the pages", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
