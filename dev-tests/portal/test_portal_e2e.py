"""
End-to-end test of the portal in a real browser (Playwright/Chromium) against an in-memory
stand-in for the data-entry API. No Docker needed.

  pip install -r portal/requirements.txt playwright opencv-python-headless && playwright install chromium
  python dev-tests/portal/test_portal_e2e.py
"""
import json
import os
import sys
import tempfile
import threading

import cv2
from openpyxl import load_workbook
import numpy as np
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8199, 3199
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_USERS_FILE=f"{CONFIG}/users.json", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.set_password("tester", "a-long-test-password")
import app as portal  # noqa: E402
import linkcheck  # noqa: E402


def fake_check(url):
    """Stand-in for the network: addresses containing "missing" answer 404, the others 200."""
    bad = "missing" in url
    return {"url": url, "ok": not bad, "problem": "linkcheck.httpError" if bad else None,
            "status": 404 if bad else 200, "finalUrl": url, "params": {"status": 404} if bad else {}}


linkcheck.check_url = fake_check

for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1360, "height": 1000})
    page = ctx.new_page()
    page.on("pageerror", lambda e: failures.append(f"page error: {e}"))

    page.goto(BASE)
    check("unauthenticated → sign-in page", page.url.endswith("/portal/login"), page.url)
    page.fill("#username", "tester"); page.fill("#password", "wrong"); page.click("#login-submit"); page.wait_for_timeout(900)
    check("wrong password message", "Incorrect" in page.inner_text("#login-status"))
    page.fill("#password", "a-long-test-password"); page.click("#login-submit"); page.wait_for_timeout(800)
    check("signed in", page.url.endswith("/portal/"), page.url)

    page.fill("#gtin", "7898357410016"); page.wait_for_timeout(100)
    check("check digit feedback", "should be 5" in page.inner_text("#gtin-msg"), page.inner_text("#gtin-msg"))
    page.fill("#gtin", "7898357410015"); page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(500)
    page.fill("#description", "Test 01")
    page.fill(".link-row .url", "www.codigo2d.com.br"); page.click("#description")
    page.click("#add"); rows = page.query_selector_all(".link-row")
    rows[1].query_selector(".link-type").select_option("gs1:instructions")
    rows[1].query_selector(".url").fill("https://www.codigo2d.com.br/manual.pdf")
    rows[1].query_selector(".forward").uncheck()
    rows[1].query_selector(".make-default").click()
    page.click("#save"); page.wait_for_timeout(600)
    check("record created", "Record created" in page.inner_text("#status"), page.inner_text("#status"))
    stored = json.dumps(mock_data_entry.DB)
    check("default link type = first target", '"default": "gs1:instructions"' in stored)
    check("fwqs false stored", '"fwqs": false' in stored)

    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(200)
    check("live language switch", "Cadastro criado" in page.inner_text("#status"), page.inner_text("#status"))
    page.select_option("#locale", "en-GB")
    check("English wording", page.inner_text("#test") == "Try now" and page.inner_text("#copy") == "Copy link address")

    page.check('input[value="lot"]'); page.fill("#lot", "L2026A"); page.check("#opt-brand"); page.wait_for_timeout(700)
    for fmt in ["png", "svg"]:
        response = ctx.request.get(f"http://127.0.0.1:{PORT}" + page.get_attribute(f"#download-{fmt}", "href"))
        check(f"{fmt} download", response.status == 200 and "_gs1." in (response.headers.get("content-disposition") or ""))
        if fmt == "png":
            image = cv2.imdecode(np.frombuffer(response.body(), np.uint8), 1)
            decoded = cv2.QRCodeDetector().detectAndDecode(image)[0]
            check("PNG decodes", decoded.endswith("/01/07898357410015/10/L2026A"), decoded)
        else:
            check("SVG sized in mm with branding", b'mm"' in response.body() and b"<g fill" in response.body())

    # Record list: one record made in the portal (with history) and two made elsewhere
    other = {"anchor": "/01/09506000134352", "itemDescription": "Açaí orgânico", "defaultLinktype": "gs1:pip",
             "links": [{"linktype": "gs1:pip", "href": "https://example.org/acai", "title": "Açaí", "hreflang": ["pt"]}]}
    mock_data_entry.upsert(other)
    mock_data_entry.upsert({**other, "qualifiers": [{"21": "SER1"}]})
    page.click("#user-button"); page.click("#menu-records"); page.wait_for_timeout(700)
    rows = page.query_selector_all("#records-body tr")
    check("record list shown from the user menu", page.is_visible("#records-view") and not page.is_visible("#editor-view"))
    check("record list: every entry", len(rows) == 3, len(rows))
    check("record list: portal change first, with user", "Test 01" in rows[0].inner_text() and "tester" in rows[0].inner_text(),
          rows[0].inner_text())
    check("record list: no history for records made elsewhere", "no history" in rows[1].inner_text(), rows[1].inner_text())
    page.fill("#records-search", "acai"); page.wait_for_timeout(100)
    check("search ignores accents and case", len(page.query_selector_all("#records-body tr")) == 2)
    page.fill("#records-search", "9506000134352 ser1"); page.wait_for_timeout(100)
    check("search by GTIN without leading zero and qualifier", len(page.query_selector_all("#records-body tr")) == 1)
    page.fill("#records-search", "zzz"); page.wait_for_timeout(100)
    check("no match message", page.inner_text("#records-empty") == "No record matches the search.")
    page.fill("#records-search", ""); page.select_option("#records-user", "tester"); page.wait_for_timeout(100)
    check("filter by user", len(page.query_selector_all("#records-body tr")) == 1)
    page.select_option("#records-user", "")
    check("records with other qualifiers are not editable here",
          page.query_selector("#records-body tr:has-text('SER1') a") is None)
    page.click("#records-body a:has-text('Test 01')"); page.wait_for_timeout(700)
    check("opening from the list loads the record in the editor",
          page.is_visible("#editor-view") and page.input_value("#gtin") == "07898357410015"
          and page.input_value("#description") == "Test 01", page.input_value("#gtin"))
    page.go_back(); page.wait_for_timeout(500)
    page.go_forward(); page.wait_for_timeout(300)
    check("browser history moves between list and editor", page.is_visible("#editor-view"))

    # Spreadsheet export → edit → import. Records made by other tools: a template lot (not editable,
    # not exported) and languages outside the editor's menu (exported and re-imported unchanged).
    mock_data_entry.upsert({**other, "qualifiers": [{"10": "{lotnumber}"}]})
    mock_data_entry.upsert({"anchor": "/01/09506000134369", "itemDescription": "Risotto", "defaultLinktype": "gs1:pip",
                            "links": [{"linktype": "gs1:pip", "href": "https://example.org/r", "title": "R", "hreflang": ["en-US"]},
                                      {"linktype": "gs1:pip", "href": "https://example.org/r/vi", "title": "R", "hreflang": ["vi"]}]})
    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    check("template lot listed as another kind of record",
          "{lotnumber}" in page.inner_text("#records-body") and page.query_selector("#records-body tr:has-text('{lotnumber}') a") is None)
    with page.expect_download() as info:
        page.click("#records-export-xlsx")
    downloaded = os.path.join(CONFIG, info.value.suggested_filename)
    info.value.save_as(downloaded)
    check("export: XLSX file name", downloaded.endswith(".xlsx"), downloaded)
    book = load_workbook(downloaded)
    links_sheet = book.worksheets[0]
    header = [c.value for c in links_sheet[1]]
    exported = [[c.value for c in row] for row in links_sheet.iter_rows(min_row=2)]
    check("export: English headers and reference sheets", header[:4] == ["GTIN", "Batch/lot", "Description", "Link type"]
          and book.sheetnames == ["Links", "Link types", "Languages"], (header, book.sheetnames))
    check("export: one row per link of the editable records", len(exported) == 5
          and all(r[0] in ("07898357410015", "09506000134352", "09506000134369") for r in exported), exported)
    check("export: languages outside the menu kept", {"en-US", "vi"} <= {r[5] for r in exported}, exported)
    with page.expect_download() as info:
        page.click("#records-export-csv")
    check("export: CSV file", info.value.suggested_filename.endswith(".csv"))

    for row in links_sheet.iter_rows(min_row=2):
        if row[0].value == "07898357410015":
            row[2].value = "Test 01 (updated)"                      # update: new description
    links_sheet.append(["07898357410022", "", "Imported product", "gs1:pip", "www.example.org/new", "pt, en", "", "yes", "yes"])
    links_sheet.append(["07898357410022", "L9", "Imported product", "gs1:pip", "https://example.org/l9", "pt", "", "", ""])
    links_sheet.append(["07898357410039", "", "Broken", "gs1:pip", "ftp://example.org", "pt", "", "", ""])
    links_sheet.append(["07898357410039", "", "Broken", "gs1:pip", "https://example.org/b", "portuguese", "", "", ""])
    links_sheet.append(["09506000134352", "{lotnumber}", "Açaí orgânico", "gs1:pip", "https://example.org/t", "pt", "", "", ""])
    edited = os.path.join(CONFIG, "edited.xlsx")
    book.save(edited)

    page.click("#records-import"); page.wait_for_timeout(200)
    page.set_input_files("#import-file", edited); page.wait_for_timeout(1200)
    summary = page.inner_text("#import-summary")
    check("import preview counts", summary == "New: 2 · Changed: 1 · Unchanged: 2 · With errors: 2", summary)
    errors_text = page.inner_text("#import-errors")
    check("import preview explains every wrong row at once", "Row 9:" in errors_text and "ftp://example.org" in errors_text
          and "Row 10:" in errors_text and "portuguese" in errors_text
          and "Row 11: the batch/lot “{lotnumber}” cannot be managed" in errors_text, errors_text)
    check("nothing written before confirming", "07898357410022" not in json.dumps(list(mock_data_entry.DB)))
    check("apply button counts valid changes", page.inner_text("#import-apply") == "Import records (3)")
    page.click("#import-apply"); page.wait_for_timeout(2500)
    check("import finished", "Import finished. Created: 2 · Updated: 1 · Failed: 0" in page.inner_text("#import-status"),
          page.inner_text("#import-status"))
    page.click("#import-cancel"); page.wait_for_timeout(800)
    listed = page.inner_text("#records-body")
    check("imported records listed with their author", "Imported product" in listed and "Test 01 (updated)" in listed
          and listed.count("tester") >= 3, listed)
    stored = mock_data_entry.v3("01_07898357410022")
    check("import stored product and batch with the default first", len(stored) == 2
          and stored[0]["defaultLinktype"] == "gs1:pip" and stored[0]["links"][0]["href"] == "https://www.example.org/new"
          and stored[0]["links"][0]["hreflang"] == ["pt", "en"], stored)

    # Link checker: editor, every record, import preview
    mock_data_entry.upsert({"anchor": "/01/09506000134369", "itemDescription": "Risotto", "defaultLinktype": "gs1:pip",
                            "links": [{"linktype": "gs1:pip", "href": "https://example.org/missing",
                                       "title": "Manual", "hreflang": ["en"]}]})
    page.click("#records-check"); page.wait_for_timeout(2500)
    check("check every record: summary line", "Records with problems: 1" in page.inner_text("#records-check-msg"),
          page.inner_text("#records-check-msg"))
    risotto = page.query_selector("#records-body tr:has-text('Risotto')")
    check("check every record: warning on the record", risotto and risotto.query_selector(".link-warn") is not None
          and "example.org/missing" in risotto.query_selector(".link-warn").get_attribute("title"))
    page.check("#records-problems"); page.wait_for_timeout(100)
    check("filter: only records with problems", len(page.query_selector_all("#records-body tr")) == 1)
    page.click("#records-body a:has-text('Risotto')"); page.wait_for_timeout(1500)
    notes = [el.inner_text() for el in page.query_selector_all("#links .row-check") if el.is_visible()]
    check("opening a record with problems checks its targets", any("error 404" in n for n in notes)
          and "Targets with problems: 1" in page.inner_text("#links-check-msg"), (notes, page.inner_text("#links-check-msg")))
    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    check("last check shown again after reloading", "Records with problems: 1" in page.inner_text("#records-check-msg"))

    page.click("#records-import"); page.wait_for_timeout(200)
    page.check("#import-checklinks")
    extra = os.path.join(CONFIG, "check.csv")
    with open(extra, "w", encoding="utf-8") as fh:
        fh.write("gtin;description;linkType;url\n07898357410039;New;gs1:pip;https://example.org/missing-page\n")
    page.set_input_files("#import-file", extra); page.wait_for_timeout(2500)
    check("import preview: optional address check", "Row 2: https://example.org/missing-page" in page.inner_text("#import-warnings")
          and page.is_enabled("#import-apply"), page.inner_text("#import-warnings"))
    page.click("#import-cancel")

    page.hover("#user-button"); page.wait_for_timeout(200)
    check("user menu on hover", page.is_visible("#menu-logout"))
    check("logo and menu link to the resolver home page",
          page.get_attribute("a.brand", "href") == "/" and page.get_attribute("#menu-home", "href") == "/"
          and page.inner_text("#menu-home").strip() in ("Home page", "Página inicial"), page.inner_text("#menu-home"))
    page.click("#user-button"); page.click("#menu-options")
    page.fill("#current-password", "a-long-test-password"); page.fill("#new-password", "another-long-password")
    page.fill("#confirm-password", "another-long-password"); page.click("#password-save"); page.wait_for_timeout(600)
    check("password changed", "Password changed" in page.inner_text("#password-status"))
    page.click("#options-close"); page.hover("#user-button"); page.click("#menu-logout"); page.wait_for_timeout(500)
    check("signed out", "reason=signedOut" in page.url, page.url)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
