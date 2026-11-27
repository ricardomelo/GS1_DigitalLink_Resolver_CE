"""
Records outside the rules in a real browser (Playwright/Chromium; ADR 0056): on the organisations' list a server
administrator checks the records — the counts, the first rows with the problem in the user's language, the downloads
of the whole report (CSV and Excel) — a clean resolver said so, Portuguese, and no script errors.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_legacy_e2e.py          # SCREENSHOTS=<folder> keeps a picture of each step
"""
import csv
import io
import os
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8197, 3194
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_legacy_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("PORTAL_EXPORT_LIMITS", None)
sys.path[:0] = [HERE, PORTAL]

import csp_guard  # noqa: E402,F401  (fails the program on a Content-Security-Policy violation: ADR 0038)
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
    page.wait_for_timeout(700)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def link(href):
    return {"linktype": "gs1:pip", "href": href, "title": "T", "hreflang": ["en"]}


A = gtin("0789123450001")
mock_data_entry.DB.clear()
mock_data_entry.DB[f"01_{A}"] = {"default": "gs1:pip", "entries": [
    {"qualifiers": [], "itemDescription": "D", "links": [link("http://acme.example.com/p")], "informative": []}]}
mock_data_entry.DB[f"01_{A}_10_LOT"] = {"default": "gs1:pip", "entries": [
    {"qualifiers": [], "itemDescription": "D", "links": [link("https://acme.example.com/lot")], "informative": []}]}
mock_data_entry.DB["99_X"] = {"default": "gs1:pip", "entries": [
    {"qualifiers": [], "itemDescription": "D", "links": [link("https://10.0.0.5/p")], "informative": []}]}

with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    context = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "root", "root-password-long")

    page.goto(BASE + "#tenants"); page.wait_for_timeout(900)
    check("the organisations' list: the section and its button, nothing read yet", page.is_visible("#legacy-check")
          and page.is_hidden("#legacy-table") and page.is_hidden("#legacy-xlsx") and page.is_hidden("#legacy-status"))
    page.click("#legacy-check"); page.wait_for_timeout(1200)
    status = page.inner_text("#legacy-status")
    check("checked: the counts, as a warning", status == "4 found: 2 identifier(s) and 2 target(s) outside the rules."
          and "is-warn" in page.get_attribute("#legacy-status", "class"), status)
    rows = page.locator("#legacy-body tr")
    first = [c.strip() for c in rows.nth(0).locator("td").all_inner_texts()]
    check("…the rows, the problem in the user's language", rows.count() == 4 and first[:2]
          == ["Key value the rules refuse", f"/01/{A}_10_LOT"] and first[3] == "Acme Foods", first)
    check("…the target rows", "Target that is not HTTPS" in page.inner_text("#legacy-body")
          and "Target inside a network or by address" in page.inner_text("#legacy-body"))
    check("…the downloads offered, no 'first rows' line under 20 rows", page.is_visible("#legacy-xlsx")
          and page.is_visible("#legacy-csv") and page.is_hidden("#legacy-more"))
    shot(page, "legacy-found")
    with page.expect_download() as info:
        page.click("#legacy-csv")
    data = open(info.value.path(), encoding="utf-8-sig").read()
    table = list(csv.reader(io.StringIO(data), delimiter=";"))
    check("CSV: every row, the header and the problems in the user's language",
          info.value.suggested_filename.startswith("records-outside-the-rules-") and len(table) == 5
          and table[0][1] == "Identifier" and table[1][0] == "Key value the rules refuse", table[:2])
    with page.expect_download() as info:
        page.click("#legacy-xlsx")
    check("Excel: a workbook", info.value.suggested_filename.endswith(".xlsx")
          and open(info.value.path(), "rb").read(2) == b"PK")
    check("…both in the journal", store.col("journal").count_documents({"action": "legacy-export"}) == 2)

    mock_data_entry.DB.pop(f"01_{A}_10_LOT"); mock_data_entry.DB.pop("99_X")
    mock_data_entry.DB[f"01_{A}"]["entries"][0]["links"] = [link("https://acme.example.com/p")]
    page.click("#legacy-check"); page.wait_for_timeout(1200)
    check("a clean resolver: said so, no table, no downloads", page.inner_text("#legacy-status")
          == "No record outside the rules." and page.is_hidden("#legacy-table") and page.is_hidden("#legacy-csv"),
          page.inner_text("#legacy-status"))

    pt = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    pt.on("pageerror", lambda e: errors.append(str(e)))
    mock_data_entry.DB["17_261231"] = {"default": "gs1:pip", "entries": [
        {"qualifiers": [], "itemDescription": "D", "links": [link("javascript:alert(1)")], "informative": []}]}
    sign_in(pt, "root", "root-password-long")
    pt.goto(BASE + "#tenants"); pt.wait_for_timeout(900)
    pt.click("#legacy-check"); pt.wait_for_timeout(1200)
    check("Portuguese: the counts and the problems", pt.inner_text("#legacy-status")
          == "2 encontrado(s): 1 identificador(es) e 1 destino(s) fora das regras."
          and "Identificador que não é uma chave GS1" in pt.inner_text("#legacy-body"), pt.inner_text("#legacy-status"))
    shot(pt, "legacy-found-pt")

    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
