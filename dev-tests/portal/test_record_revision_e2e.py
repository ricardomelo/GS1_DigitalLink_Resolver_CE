"""
A record's revision in a real browser (Playwright/Chromium; ADR 0058): two users open the same record in the editor;
the first saves; the second's save is refused with the message in the user's language and a button that opens the
record again (asking before the unsaved changes are discarded), after which the second user sees the first user's
version and can save; a record that did not exist when it was opened and was created meanwhile, and a delete of a
record changed meanwhile, are refused the same way; Portuguese; no script errors.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_record_revision_e2e.py      # SCREENSHOTS=<folder> keeps a picture of each step
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
PORT, DATA_ENTRY_PORT = 8271, 3271
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_revision_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import csp_guard  # noqa: E402,F401  (fails the program on a Content-Security-Policy violation: ADR 0038)
import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402

users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("eva", "eva-password-long", "editor", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def gtin(body):
    return body + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body))) % 10) % 10)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.goto(BASE); page.wait_for_timeout(700)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def open_record(page, value, batch=""):
    page.fill("#key-value", value); page.wait_for_timeout(150)
    if page.is_visible("#q-10"):
        page.fill("#q-10", batch); page.wait_for_timeout(300)
    page.click("#open"); page.wait_for_timeout(700)


def answer(page, accept=True):
    page.wait_for_selector("#ask-dialog", state="visible", timeout=3000)
    page.click("#ask-ok" if accept else "#ask-cancel"); page.wait_for_timeout(700)


def status(page):
    return page.inner_text("#status") if page.is_visible("#status") else ""


A, B = gtin("0789123456001"), gtin("0789123456002")
LINK = {"linktype": "gs1:pip", "href": "https://acme.example.com/p", "title": "P", "hreflang": ["en"]}
mock_data_entry.DB.clear()
mock_data_entry.DB[f"01_{A}"] = {"default": "gs1:pip", "entries": [
    {"qualifiers": [], "itemDescription": "Coffee", "links": [dict(LINK)], "informative": []}]}

with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    edu = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000}).new_page()
    eva = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000}).new_page()
    for page in (edu, eva):
        page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(edu, "edu", "edu-password-long")
    sign_in(eva, "eva", "eva-password-long")

    open_record(edu, A)
    open_record(eva, A)
    eva.fill("#description", "Coffee beans"); eva.click("#save"); eva.wait_for_timeout(900)
    check("the first user's save: done", "is-ok" in (eva.get_attribute("#status", "class") or "")
          and mock_data_entry.DB[f"01_{A}"]["entries"][0]["itemDescription"] == "Coffee beans", status(eva))
    edu.fill("#description", "Ground coffee"); edu.click("#save"); edu.wait_for_timeout(900)
    check("the second user's save, from the record as opened before: refused with the message",
          status(edu) == "Someone else saved or deleted this record after you opened it. Nothing was saved. Open the "
          "record again to see the current version, then make the change again."
          and "is-error" in edu.get_attribute("#status", "class"), status(edu))
    check("…the first user's save kept", mock_data_entry.DB[f"01_{A}"]["entries"][0]["itemDescription"] == "Coffee beans")
    check("…a button to open the record again", edu.is_visible("#reopen")
          and edu.inner_text("#reopen") == "Open the record again", edu.is_visible("#reopen"))
    shot(edu, "revision-refused")
    edu.click("#reopen")
    check("…asks before the unsaved changes are discarded", edu.is_visible("#ask-dialog"))
    answer(edu)
    check("…opened again: the first user's version shown, the message and the button gone",
          edu.input_value("#description") == "Coffee beans" and not edu.is_visible("#reopen")
          and not edu.is_visible("#status"), (edu.input_value("#description"), status(edu)))
    edu.fill("#description", "Coffee beans, roasted"); edu.click("#save"); edu.wait_for_timeout(900)
    check("…then the change saved", "is-ok" in (edu.get_attribute("#status", "class") or "")
          and mock_data_entry.DB[f"01_{A}"]["entries"][0]["itemDescription"] == "Coffee beans, roasted", status(edu))
    edu.fill("#description", "Coffee beans, dark roast"); edu.click("#save"); edu.wait_for_timeout(900)
    check("…and saved again from the same page (the revision of each save kept)", "is-ok" in
          (edu.get_attribute("#status", "class") or "")
          and mock_data_entry.DB[f"01_{A}"]["entries"][0]["itemDescription"] == "Coffee beans, dark roast", status(edu))

    # a record that did not exist when it was opened, created meanwhile
    open_record(edu, A, "L1")
    open_record(eva, A, "L1")
    edu.fill("#description", "Batch L1"); edu.fill(".link-row .url", "https://acme.example.com/l1"); edu.click("#description")
    edu.click("#save"); edu.wait_for_timeout(900)
    eva.fill("#description", "Lote L1"); eva.fill(".link-row .url", "https://acme.example.com/lote"); eva.click("#description")
    eva.click("#save"); eva.wait_for_timeout(900)
    check("a new record created meanwhile by someone else: refused in Portuguese, the first one kept",
          status(eva).startswith("Outra pessoa salvou ou excluiu este cadastro depois que você o abriu.")
          and eva.inner_text("#reopen") == "Abrir o cadastro de novo"
          and [e["itemDescription"] for e in mock_data_entry.DB[f"01_{A}"]["entries"]] == ["Coffee beans, dark roast",
                                                                                         "Batch L1"], status(eva))
    shot(eva, "revision-refused-pt")

    # a delete from a record changed meanwhile
    mock_data_entry.DB[f"01_{B}"] = {"default": "gs1:pip", "entries": [
        {"qualifiers": [], "itemDescription": "Tea", "links": [dict(LINK)], "informative": []}]}
    open_record(edu, B)
    mock_data_entry.DB[f"01_{B}"]["entries"][0]["itemDescription"] = "Green tea"
    edu.click("#delete"); answer(edu)
    check("a delete from a record changed meanwhile: refused, the record kept",
          status(edu).startswith("Someone else saved or deleted this record") and f"01_{B}" in mock_data_entry.DB,
          status(edu))

    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
