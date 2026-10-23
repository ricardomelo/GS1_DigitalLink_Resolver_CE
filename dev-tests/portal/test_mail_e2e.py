"""
The portal's e-mail screens in a real browser (Playwright/Chromium), against the in-memory stand-in for the data
entry API and the SMTP relay of fake_smtp.py (Documentation/adr/0004-e-mail.md): the sign-in page's password
recovery and the page that a link of an invitation or recovery message opens, the invitation and the reset by link
on the users screen, the e-mail section of Options, both languages, a phone's width, and the same screens with
e-mail off.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_mail_e2e.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8197, 3197
sys.path[:0] = [HERE, PORTAL]

from fake_smtp import FakeRelay  # noqa: E402

relay = FakeRelay(starttls=True, credentials=("portal", "relay-secret")).start()
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_mail_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL=f"http://127.0.0.1:{PORT}", RESOLVER_ORG_NAME="Example Operator",
                  PORTAL_MAIL_HOST="127.0.0.1", PORTAL_MAIL_PORT=str(relay.port), PORTAL_MAIL_USERNAME="portal",
                  PORTAL_MAIL_PASSWORD="relay-secret", PORTAL_MAIL_FROM="Link portal <noreply@example.org>",
                  PORTAL_MAIL_CA_FILE=relay.ca_file, PORTAL_MAIL_TIMEOUT="5")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ["PORTAL_WORKER"] = "embedded"               # messages are sent by a thread of the portal

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False, email="root@example.org")
import app as portal  # noqa: E402

for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def wait_messages(count, timeout=8.0):
    end = time.monotonic() + timeout
    while len(relay.messages) < count and time.monotonic() < end:
        time.sleep(0.05)
    return list(relay.messages)


def link_of(msg):
    found = re.search(r"http://127\.0\.0\.1:\d+/portal/login#(?:invite|reset)=[A-Za-z0-9_-]+",
                      msg.get_body(("plain",)).get_content())
    return found.group(0) if found else None


def until(wait):
    """Runs a Playwright wait for a condition (instead of a fixed pause); False when it times out, so that the check
    after it reports the failure instead of the program stopping."""
    try:
        wait()
        return True
    except PlaywrightTimeoutError:
        return False


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)       # sign-in opens the overview (ADR 0007)
    page.goto(BASE)
    page.wait_for_timeout(600)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []

    def new_page(locale, width=1280, height=900):
        ctx = browser.new_context(locale=locale, viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        return ctx, page

    # ------------------------------------------------------------------ the sign-in page with e-mail on
    ctx_root, root = new_page("en-GB")
    root.goto(BASE + "login"); root.wait_for_timeout(500)
    check("sign-in page: recovery offered", root.is_visible("#forgot-open")
          and root.inner_text("#forgot-open") == "Forgotten your password?"
          and root.inner_text("#login-help") == "No access? Contact the resolver administrator.")

    # ------------------------------------------------------------------ an invitation
    sign_in(root, "root", "root-password-long")
    root.goto(BASE + "#users"); root.wait_for_timeout(800)
    check("users: the invitation box, ticked, and its hint", root.is_visible("#new-user-invite")
          and root.is_checked("#new-user-invite") and "receives a link" in root.inner_text("#users-view"))
    root.fill("#new-user-name", "maria"); root.select_option("#new-user-role", "editor")
    root.fill("#new-user-email", "maria@example.org")
    root.click("#users-create button[type=submit]"); root.wait_for_timeout(900)
    check("invited: the status says so, no temporary password shown",
          "The invitation was sent by e-mail" in root.inner_text("#users-status") and not root.is_visible("#temp-password"),
          root.inner_text("#users-status"))
    row = root.locator("#users-body tr", has_text="maria")
    check("users list: invited state, send the invitation again", "Invited — waiting for the password" in row.inner_text()
          and row.locator("button", has_text="Send the invitation again").count() == 1, row.inner_text())
    messages = wait_messages(1)
    invite = link_of(messages[0]) if messages else None
    check("the invitation reached the relay with a link", invite is not None and messages[0]["To"] == "maria@example.org")

    ctx_maria, maria = new_page("pt-BR", 390, 844)              # a phone, in Portuguese
    maria.goto(invite); maria.wait_for_timeout(900)
    check("the link opens the page to choose a password, with the user name",
          maria.is_visible("#link-form") and not maria.is_visible("#login-form")
          and maria.inner_text("#link-title") == "Bem-vindo: escolha a sua senha" and maria.inner_text("#link-user") == "maria",
          maria.inner_text("#link-form"))
    check("the token leaves the address bar at once", "#" not in maria.url and "invite" not in maria.url, maria.url)
    check("phone width: no sideways scroll", maria.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    check("the new password fields have the show/hide button", maria.locator("#link-form .reveal").count() == 2)
    maria.fill("#link-password", "curta"); maria.fill("#link-confirm", "curta"); maria.click("#link-submit")
    maria.wait_for_timeout(300)
    check("a short password is refused in the page", "pelo menos 12" in maria.inner_text("#link-status"))
    maria.fill("#link-password", "maria-password-long"); maria.fill("#link-confirm", "maria-password-other")
    maria.click("#link-submit"); maria.wait_for_timeout(300)
    check("two different entries are refused", "não conferem" in maria.inner_text("#link-status"))
    maria.fill("#link-confirm", "maria-password-long"); maria.click("#link-submit"); maria.wait_for_timeout(900)
    check("password chosen: back to the sign-in page, the user name filled in",
          maria.is_visible("#login-form") and "Senha definida" in maria.inner_text("#login-status")
          and maria.input_value("#username") == "maria", maria.inner_text("#login-status"))
    maria.fill("#password", "maria-password-long"); maria.click("#login-submit")
    until(lambda: maria.wait_for_url(BASE + "#overview", timeout=10000))
    check("the invited user signs in (the overview opens)", maria.url == BASE + "#overview", maria.url)

    ctx_again, again = new_page("pt-BR")
    again.goto(invite); again.wait_for_timeout(800)
    check("the same link a second time: no longer valid, no password fields",
          "não vale mais" in again.inner_text("#link-status") and not again.is_visible("#link-fields"),
          again.inner_text("#link-form"))
    again.click("#link-back"); again.wait_for_timeout(200)
    check("back to the sign-in form", again.is_visible("#login-form") and not again.is_visible("#link-form"))

    # ------------------------------------------------------------------ password recovery in Portuguese
    relay.clear()
    again.click("#forgot-open"); again.wait_for_timeout(200)
    check("recovery form in Portuguese", again.is_visible("#forgot-form") and again.inner_text("#forgot-form h2")
          == "Recuperar a senha")
    again.click("#forgot-submit"); again.wait_for_timeout(300)
    check("recovery: an empty entry is pointed out", "Informe o seu usuário" in again.inner_text("#forgot-status"))
    again.fill("#forgot-login", "MARIA@example.org"); again.click("#forgot-submit"); again.wait_for_timeout(1200)
    check("recovery: the same answer for everyone", "Se houver uma conta" in again.inner_text("#forgot-status"),
          again.inner_text("#forgot-status"))
    again.fill("#forgot-login", "nobody-here"); again.click("#forgot-submit"); again.wait_for_timeout(1200)
    check("recovery for an unknown name: the same answer", "Se houver uma conta" in again.inner_text("#forgot-status"))
    messages = wait_messages(1)
    check("one recovery message, in the user's language (Portuguese, from her pages)", len(wait_messages(2, 1.0)) == 1
          and messages[0]["Subject"] == "Escolha uma nova senha", [m["Subject"] for m in messages])
    reset_link = link_of(messages[0])

    # a link opened while someone else is signed in, in this browser
    root.goto(reset_link); root.wait_for_timeout(1500)
    check("a reset link opened while signed in: the session ends, the link page opens",
          root.url.endswith("/portal/login") and root.is_visible("#link-form") and root.inner_text("#link-user") == "maria",
          root.url)
    root.goto(BASE); root.wait_for_timeout(500)
    check("…and the earlier session is over", root.url.endswith("/portal/login"), root.url)
    again.goto(reset_link); again.wait_for_timeout(800)
    check("recovery link: 'Choose a new password'", again.inner_text("#link-title") == "Escolha uma nova senha"
          and again.inner_text("#link-user") == "maria")
    again.fill("#link-password", "maria-new-password"); again.fill("#link-confirm", "maria-new-password")
    again.click("#link-submit"); again.wait_for_timeout(900)
    check("recovery done", "Senha definida" in again.inner_text("#login-status"))
    maria.goto(BASE); maria.wait_for_timeout(600)
    check("maria's open session ended with the new password, the sign-in page says why",
      "/portal/login?reason=expired" in maria.url and "terminou" in maria.inner_text("#login-status"), maria.url)

    # ------------------------------------------------------------------ Options → E-mail
    sign_in(maria, "maria", "maria-new-password")
    maria.click("#user-button"); maria.click("#menu-options"); maria.wait_for_timeout(300)
    check("options: the e-mail section, the address, the page's language, job notices off",
          maria.is_visible("#prefs-form") and "maria@example.org" in maria.inner_text("#prefs-address")
          and maria.input_value("#prefs-language") == "pt-BR" and not maria.is_checked("#prefs-jobs")
          and maria.is_disabled("#prefs-form input[type=checkbox][disabled]"), maria.inner_text("#prefs-form"))
    maria.select_option("#prefs-language", "en-GB"); maria.check("#prefs-jobs"); maria.click("#prefs-save")
    maria.wait_for_timeout(600)
    check("preferences saved", "Preferências de e-mail salvas" in maria.inner_text("#prefs-status"))
    maria.click("#options-close"); maria.reload(); maria.wait_for_timeout(800)
    maria.click("#user-button"); maria.click("#menu-options"); maria.wait_for_timeout(300)
    check("…and kept", maria.input_value("#prefs-language") == "en-GB" and maria.is_checked("#prefs-jobs"))
    maria.click("#options-close")

    # ------------------------------------------------------------------ a reset by an administrator
    relay.clear()
    sign_in(root, "root", "root-password-long")
    root.goto(BASE + "#users"); root.wait_for_timeout(800)
    asked = []
    root.locator("#users-body tr", has_text="maria").locator("button", has_text="Reset password").click()
    root.wait_for_timeout(300)
    if root.is_visible("#ask-dialog"):                  # the portal's own confirmation (ADR 0013)
        asked.append(root.inner_text("#ask-text")); root.click("#ask-ok")
    root.wait_for_timeout(900)
    check("reset of a user with an address: the question says a link goes by e-mail",
          asked and "link" in asked[0] and "stops working at once" in asked[0], asked)
    check("…the status says the link was sent, no temporary password",
          "was sent by e-mail" in root.inner_text("#users-status") and not root.is_visible("#temp-password"),
          root.inner_text("#users-status"))
    messages = wait_messages(1)
    check("…the message in maria's chosen language", messages and messages[0]["Subject"] == "Your password was reset")

    # ------------------------------------------------------------------ texts of the sign-in page
    catalogue = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
    blocks = re.split(r'\n    "(?:pt-BR|en-GB)": \{', catalogue)[1:]
    pt_keys, en_keys = (set(re.findall(r'^      "([^"]+)":', b, re.M)) for b in blocks[:2])
    html = open(os.path.join(PORTAL, "static", "login.html"), encoding="utf-8").read()
    script = open(os.path.join(PORTAL, "static", "login.js"), encoding="utf-8").read()
    keys = set(re.findall(r'data-i18n="([^"]+)"', html)) | set(re.findall(r'"((?:login|password)\.[A-Za-z]+)"', script))
    check("every text of the sign-in page is translated in both languages", keys <= pt_keys & en_keys,
          sorted(keys - (pt_keys & en_keys)))

    # ------------------------------------------------------------------ e-mail off
    os.environ["PORTAL_MAIL_HOST"] = ""
    ctx_off, off = new_page("en-GB")
    off.goto(BASE + "login"); off.wait_for_timeout(600)
    check("e-mail off: no recovery on the sign-in page, the usual help", not off.is_visible("#forgot-open")
          and off.inner_text("#login-help") == "No access, or forgotten your password? Contact the resolver administrator.")
    sign_in(off, "root", "root-password-long")
    off.goto(BASE + "#users"); off.wait_for_timeout(800)
    check("e-mail off: no invitation box", not off.is_visible("#new-user-invite"))
    off.fill("#new-user-name", "joao"); off.fill("#new-user-email", "joao@example.org")
    off.click("#users-create button[type=submit]"); off.wait_for_timeout(900)
    check("e-mail off: a temporary password, as before", off.is_visible("#temp-password")
          and len(off.inner_text("#temp-password-value")) == 16)
    off.click("#user-button"); off.click("#menu-options"); off.wait_for_timeout(300)
    check("e-mail off: no e-mail section in Options", not off.is_visible("#prefs-form") and off.is_visible("#password-form"))

    check("no error in the pages", not errors, errors)
    browser.close()

relay.stop()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
