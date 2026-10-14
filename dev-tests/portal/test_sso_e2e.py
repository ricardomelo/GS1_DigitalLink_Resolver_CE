"""
Single sign-on in a real browser (Playwright/Chromium; Documentation/adr/0012-single-sign-on.md) with a stand-in OpenID
provider (fake_oidc.py): an organisation's administrator configures it on the *Organisation sign-in* screen (the
return address shown, the secret write-only, the provider tested, switched on); the sign-in page offers it; a person
signs in through the provider and lands on the overview; refusals come back to the sign-in page with their reason;
password sign-in switched off; an editor without the screen; the export buttons hidden from a role that may not export
(PORTAL_EXPORT_LIMITS); Portuguese and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_sso_e2e.py                  # SCREENSHOTS=<folder> keeps a picture of each step
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
PORT, DATA_ENTRY_PORT, IDP_PORT = 8197, 3194, 3195
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_sso_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0",
                  PORTAL_SSO_ALLOW_INSECURE="1", PORTAL_EXPORT_LIMITS="reader:0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import fake_oidc  # noqa: E402
import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False, email="ana@acme.example")
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False, email="edu@acme.example")
users.create("rui", "rui-password-long", "reader", tenant=acme["id"], must_change=False, email="rui@acme.example")
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
provider = fake_oidc.FakeProvider(IDP_PORT)
BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.wait_for_timeout(600)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1100})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())

    page.goto(BASE + "login"); page.wait_for_timeout(500)
    check("no organisation sign-in offered before one is on", page.is_hidden("#sso-open"))
    sign_in(page, "ana", "ana-password-long")
    page.click("#user-button")
    check("administrators have Organisation sign-in in the menu", page.is_visible("#menu-sso"))
    page.click("#menu-sso"); page.wait_for_timeout(900)
    check("the screen: the return address to register", page.inner_text("#sso-callback")
          == f"http://127.0.0.1:{PORT}/portal/sso/callback", page.inner_text("#sso-callback"))
    card = page.locator(f".domain-card[data-scope='{acme['id']}']")
    check("…an empty form for the organisation", card.count() == 1)
    card.locator(".sso-issuer").fill(provider.issuer)
    card.locator(".sso-client-id").fill(provider.client_id)
    card.locator(".sso-secret").fill(provider.client_secret)
    card.locator(".sso-domains").fill("acme.example")
    card.locator(".sso-enabled").check()
    card.locator("button", has_text="Save").click(); page.wait_for_timeout(900)
    card = page.locator(f".domain-card[data-scope='{acme['id']}']")
    check("saved and on, the secret stored and not shown", "Configuration saved" in page.inner_text("#sso-status")
          and "secret stored" in card.inner_text() and card.locator(".sso-secret").input_value() == ""
          and card.locator(".sso-secret").get_attribute("placeholder") == "Stored — leave empty to keep it",
          page.inner_text("#sso-status"))
    card.locator("button", has_text="Test the provider").click(); page.wait_for_timeout(900)
    check("the provider tested from the screen", "discovery document and keys read" in page.inner_text("#sso-status"),
          page.inner_text("#sso-status"))
    shot(page, "sso-screen")
    page.click("#user-button"); page.click("#menu-logout"); page.wait_for_timeout(800)

    # Signing in through the provider
    check("the sign-in page offers the organisation's account", page.is_visible("#sso-open"))
    page.click("#sso-open")
    page.fill("#sso-email", "edu@acme.example")
    provider.NEXT["email"] = "edu@acme.example"
    shot(page, "sso-login")
    page.click("#sso-submit")
    page.wait_for_url(BASE + "#overview", timeout=8000); page.wait_for_timeout(800)
    me = page.evaluate("async () => (await (await fetch('api/config', {credentials: 'same-origin'})).json()).user")
    check("through the provider and back: on the overview, signed in as the account",
          page.is_visible("#overview-view") and me == "edu", (page.url, me))
    page.click("#user-button"); page.click("#menu-logout"); page.wait_for_timeout(800)

    provider.reset()
    provider.NEXT["email"] = "nobody@acme.example"
    page.click("#sso-open"); page.fill("#sso-email", "nobody@acme.example"); page.click("#sso-submit")
    page.wait_for_url("**/portal/login?sso=noAccount", timeout=8000); page.wait_for_timeout(500)
    check("no account with that e-mail: back on the sign-in page, said why", "no portal user with your e-mail"
          in page.inner_text("#login-status"), page.inner_text("#login-status"))
    page.click("#sso-open"); page.fill("#sso-email", "someone@elsewhere.example"); page.click("#sso-submit")
    page.wait_for_timeout(800)
    check("a domain without it: said at once, on the form", "no organisation sign-in for that e-mail"
          in page.inner_text("#sso-status"), page.inner_text("#sso-status"))

    # Password sign-in off
    portal.sso.save(acme["id"], {"passwordOff": True}, "test")
    page.goto(BASE + "login"); page.wait_for_timeout(400)
    page.fill("#username", "edu"); page.fill("#password", "edu-password-long"); page.click("#login-submit")
    page.wait_for_timeout(800)
    check("password sign-in off: the page sends the person to the organisation's account",
          "use “Sign in with your organisation's account”" in page.inner_text("#login-status"),
          page.inner_text("#login-status"))
    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(300)
    check("in Portuguese", page.inner_text("#sso-open").strip() == "Entrar com a conta da organização")
    page.select_option("#locale", "en-GB")
    portal.sso.save(acme["id"], {"passwordOff": False}, "test")

    # An editor has no screen; a reader no export buttons (PORTAL_EXPORT_LIMITS="reader:0")
    editor_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    editor = editor_ctx.new_page()
    editor.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(editor, "edu", "edu-password-long")
    editor.goto(BASE + "#sso"); editor.wait_for_timeout(900)
    editor.click("#user-button")
    check("an editor has no Organisation sign-in screen", not editor.is_visible("#menu-sso")
          and editor.is_hidden("#sso-view"))
    editor.goto(BASE + "#records"); editor.wait_for_timeout(900)
    check("…and may export (no limit for editors)", editor.is_visible("#records-export-csv"))
    editor_ctx.close()
    reader_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    reader = reader_ctx.new_page()
    sign_in(reader, "rui", "rui-password-long")
    reader.goto(BASE + "#records"); reader.wait_for_timeout(900)
    hidden = [reader.is_hidden(sel) for sel in ("#records-export-csv", "#records-export-xlsx")]
    reader.goto(BASE + "#overview"); reader.wait_for_timeout(900)
    hidden += [reader.is_hidden(sel) for sel in ("#overview-xlsx", "#overview-csv")]
    reader.goto(BASE + "#requests"); reader.wait_for_timeout(900)
    hidden.append(reader.is_hidden("#requests-csv"))
    check("a role that may not export sees no export button", all(hidden), hidden)
    reader_ctx.close()

    # A phone
    phone_ctx = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    phone = phone_ctx.new_page()
    phone.goto(BASE + "login"); phone.wait_for_timeout(600)
    phone.tap("#sso-open"); phone.wait_for_timeout(300)
    width = phone.evaluate("document.documentElement.scrollWidth")
    check("a phone: the sign-in forms without sideways scrolling", width <= 390, width)
    phone_ctx.close()

    check("no errors in the page", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
