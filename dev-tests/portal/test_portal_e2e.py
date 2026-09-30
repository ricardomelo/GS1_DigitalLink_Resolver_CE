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
import syntax  # noqa: E402,F401 — portal.syntax.ENGINE tells whether data attributes are offered


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
    page.on("pageerror", lambda e: (print(f"FAIL page error: {e}"), failures.append(f"page error: {e}")))

    page.goto(BASE)
    check("unauthenticated → sign-in page", page.url.endswith("/portal/login"), page.url)
    page.fill("#username", "tester"); page.fill("#password", "wrong"); page.click("#login-submit"); page.wait_for_timeout(900)
    check("wrong password message", "Incorrect" in page.inner_text("#login-status"))
    page.fill("#password", "a-long-test-password")
    reveal = page.locator("#password + .reveal")
    check("sign-in: eye button to show the password", reveal.count() == 1
          and reveal.get_attribute("aria-label") == "Show password" and reveal.get_attribute("aria-pressed") == "false")
    reveal.click()
    check("password shown as text", page.get_attribute("#password", "type") == "text"
          and reveal.get_attribute("aria-pressed") == "true" and reveal.get_attribute("aria-label") == "Hide password")
    reveal.click()
    check("password hidden again", page.get_attribute("#password", "type") == "password")
    reveal.click()
    page.click("#login-submit"); page.wait_for_timeout(800)
    check("signed in", page.url.endswith("/portal/"), page.url)

    page.fill("#key-value", "7898357410016"); page.wait_for_timeout(100)
    check("check digit feedback", "should be 5" in page.inner_text("#key-msg"), page.inner_text("#key-msg"))
    page.fill("#key-value", "\u200b7898357410015\ufeff"); page.wait_for_timeout(100)
    check("GTIN pasted with invisible characters accepted", "should be" not in page.inner_text("#key-msg")
          and "digits" not in page.inner_text("#key-msg"), page.inner_text("#key-msg"))
    page.fill("#key-value", "７８９８３５７４１００１５"); page.wait_for_timeout(100)
    check("GTIN in full-width digits refused", "digits" in page.inner_text("#key-msg"), page.inner_text("#key-msg"))
    page.fill("#key-value", "7898357410015"); page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(500)
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

    page.fill("#q-10", "L2026A"); page.wait_for_timeout(700)
    check("no GS1 branding option", page.query_selector("#opt-brand") is None)
    for fmt in ["png", "svg"]:
        response = ctx.request.get(f"http://127.0.0.1:{PORT}" + page.get_attribute(f"#download-{fmt}", "href"))
        check(f"{fmt} download", response.status == 200
              and "qrcode_01_07898357410015_10_L2026A." in (response.headers.get("content-disposition") or ""),
              response.headers.get("content-disposition"))
        if fmt == "png":
            image = cv2.imdecode(np.frombuffer(response.body(), np.uint8), 1)
            decoded = cv2.QRCodeDetector().detectAndDecode(image)[0]
            check("PNG decodes", decoded.endswith("/01/07898357410015/10/L2026A"), decoded)
        else:
            check("SVG sized in mm, without branding artwork", b'mm"' in response.body() and b"<g fill" not in response.body())

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
    check("serial-number records are listed and editable",
          page.query_selector("#records-body tr:has-text('Serial SER1') a") is not None)
    page.click("#records-body a:has-text('Test 01')"); page.wait_for_timeout(700)
    check("opening from the list loads the record in the editor",
          page.is_visible("#editor-view") and page.input_value("#key-value") == "07898357410015"
          and page.input_value("#description") == "Test 01", page.input_value("#key-value"))
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
    check("export: English headers and reference sheets", header[:4] == ["Key (AI)", "Identifier", "Qualifiers", "Description"]
          and book.sheetnames == ["Links", "Link types", "Keys", "Languages"], (header, book.sheetnames))
    check("export: one row per link of the editable records", len(exported) == 6
          and any(r[2] == "(21)SER1" for r in exported)
          and all(r[0] == "01" and r[1] in ("07898357410015", "09506000134352", "09506000134369") for r in exported), exported)
    check("export: languages outside the menu kept", {"en-US", "vi"} <= {r[6] for r in exported}, exported)
    with page.expect_download() as info:
        page.click("#records-export-csv")
    check("export: CSV file", info.value.suggested_filename.endswith(".csv"))

    for row in links_sheet.iter_rows(min_row=2):
        if row[1].value == "07898357410015":
            row[3].value = "Test 01 (updated)"                      # update: new description
    links_sheet.append(["01", "07898357410022", "", "Imported product", "gs1:pip", "www.example.org/new", "pt, en", "", "yes", "yes"])
    links_sheet.append(["01", "07898357410022", "(10)L9", "Imported product", "gs1:pip", "https://example.org/l9", "pt", "", "", ""])
    links_sheet.append(["01", "07898357410039", "", "Broken", "gs1:pip", "ftp://example.org", "pt", "", "", ""])
    links_sheet.append(["01", "07898357410039", "", "Broken", "gs1:pip", "https://example.org/b", "portuguese", "", "", ""])
    links_sheet.append(["01", "09506000134352", "(10){lotnumber}", "Açaí orgânico", "gs1:pip", "https://example.org/t", "pt", "", "", ""])
    edited = os.path.join(CONFIG, "edited.xlsx")
    book.save(edited)

    page.click("#records-import"); page.wait_for_timeout(200)
    limits_text = page.inner_text("#import-limits")
    check("import dialog shows the limits of every format", "Excel (.xlsx): up to 5,000 data rows and 700 KB" in limits_text
          and "CSV or text (.csv, .txt): up to 5,000 data rows and 700 KB" in limits_text, limits_text)
    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(200)
    limits_text = page.inner_text("#import-limits")
    check("limits follow the language", "Excel (.xlsx): até 5.000 linhas de dados e 700 KB" in limits_text, limits_text)
    page.select_option("#locale", "en-GB"); page.wait_for_timeout(200)
    check("file picker offers .txt", ".txt" in page.get_attribute("#import-file", "accept"))
    big = os.path.join(CONFIG, "big.csv")
    with open(big, "wb") as fh:
        fh.write(b"x" * (700 * 1024 + 1))
    page.set_input_files("#import-file", big); page.wait_for_timeout(400)
    check("CSV above its size limit refused in the browser", "larger than 700 KB, the limit for its format"
          in page.inner_text("#import-status"), page.inner_text("#import-status"))
    page.set_input_files("#import-file", edited); page.wait_for_timeout(1200)
    summary = page.inner_text("#import-summary")
    check("import preview counts", summary == "New: 2 · Changed: 1 · Unchanged: 3 · With errors: 2", summary)
    errors_text = page.inner_text("#import-errors")
    check("import preview explains every wrong row at once", "Row 10:" in errors_text and "ftp://example.org" in errors_text
          and "Row 11:" in errors_text and "portuguese" in errors_text
          and "Row 12: the batch/lot “{lotnumber}” cannot be managed" in errors_text, errors_text)
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

    # Other primary identification keys (GS1 Digital Link URI Syntax 4.3)
    page.goto(BASE); page.wait_for_timeout(700)
    options = [o.inner_text() for o in page.query_selector_all("#key-type option")]
    check("every key of section 4.3 offered, each with its name", len(options) == 16
          and "Invoicing party (GLN) (415)" in options and not any(o.startswith("key.") for o in options), options)
    page.select_option("#key-type", "414"); page.wait_for_timeout(100)
    check("GLN: its own label and qualifiers (254, 7040)", page.inner_text("#key-label") == "GLN number"
          and [el.get_attribute("data-ai") for el in page.query_selector_all("#qualifiers .qual-field")] == ["254", "7040"])
    page.fill("#key-value", "9506000134377"); page.wait_for_timeout(100)
    check("GLN check digit feedback", "should be 6" in page.inner_text("#key-msg"), page.inner_text("#key-msg"))
    page.select_option("#key-type", "8013"); page.fill("#key-value", "1987654Ad4X4bL5ttr2310c2X"); page.wait_for_timeout(100)
    check("GMN check-character pair feedback", "should be 2K" in page.inner_text("#key-msg"), page.inner_text("#key-msg"))
    page.select_option("#key-type", "00"); page.fill("#key-value", "0 9506 0001 3435 2000 0"); page.wait_for_timeout(300)
    check("SSCC accepted, preview uses /00/", page.inner_text("#key-msg") == "Valid identifier."
          and "/00/095060001343520000" in page.inner_text("#dl"), (page.inner_text("#key-msg"), page.inner_text("#dl")))
    page.click("#open"); page.wait_for_timeout(600)
    page.fill("#description", "Pallet 1")
    page.fill(".link-row .url", "https://example.org/pallet"); page.click("#description")
    page.click("#save"); page.wait_for_timeout(800)
    check("SSCC record created", "Record created" in page.inner_text("#status") and "00_095060001343520000" in mock_data_entry.DB,
          page.inner_text("#status"))
    response = ctx.request.get(f"http://127.0.0.1:{PORT}" + page.get_attribute("#download-png", "href"))
    decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(response.body(), np.uint8), 1))[0]
    check("SSCC QR code", decoded.endswith("/00/095060001343520000"), decoded)
    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    row = page.query_selector("#records-body tr:has-text('095060001343520000')")
    check("SSCC in the record list", row is not None and "(00) 095060001343520000" in row.inner_text()
          and "The whole SSCC" in row.inner_text(), row.inner_text() if row else None)
    row.query_selector("a").click(); page.wait_for_timeout(800)
    check("SSCC opens in the editor", page.input_value("#key-type") == "00"
          and page.input_value("#description") == "Pallet 1")

    # Other records of the same key: list under "Open record", five rows in view, search, filter, open
    MANY = "07898357410015"
    many = [({"22": f"V{n}"}, f"Café 500 g variante V{n}") for n in (1, 2, 3)]
    many += [({"10": f"L2026-{n:02d}"}, f"Café 500 g lote {n}") for n in range(1, 13)]
    many += [({"10": "L2026-09", "21": f"S{n:04d}"}, "Café 500 g unidade serializada") for n in range(1, 7)]
    link = [{"linktype": "gs1:pip", "href": "https://example.org/cafe", "title": "Café", "hreflang": ["pt"]}]
    mock_data_entry.upsert({"anchor": f"/01/{MANY}", "itemDescription": "Café 500 g", "defaultLinktype": "gs1:pip", "links": link})
    for quals, description in many:
        mock_data_entry.upsert({"anchor": f"/01/{MANY}", "qualifiers": [{k: v} for k, v in quals.items()],
                                "itemDescription": description, "defaultLinktype": "gs1:pip", "links": link})
    page.select_option("#key-type", "01"); page.wait_for_timeout(100)
    page.fill("#key-value", MANY)
    for field in page.query_selector_all("#qualifiers .qual-field input"):
        field.fill("")
    page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(900)
    check("other records listed under Open record", page.is_visible("#others")
          and page.inner_text("#others-title") == "Other records of this GTIN (21)"
          and "21 other records" in page.inner_text("#open-msg"), page.inner_text("#others-title"))
    scroll = page.locator("#others-scroll")
    in_view = page.evaluate("""() => { const s = document.querySelector('#others-scroll').getBoundingClientRect();
        return [...document.querySelectorAll('#others-body tr')].filter(r => { const b = r.getBoundingClientRect();
        return b.top >= s.top - 1 && b.bottom <= s.bottom + 1; }).length; }""")
    check("exactly five rows in view, the list scrolls", in_view == 5
          and page.evaluate("document.querySelector('#others-scroll').scrollHeight > document.querySelector('#others-scroll').clientHeight"),
          in_view)
    check("footer says how many are shown", page.inner_text("#others-foot") == "Showing 21 of 21 · scroll the list to see more")
    filters = page.eval_on_selector_all("#others-filter option", "o => o.map(x => x.value)")
    check("filter offers the qualifiers present", filters == ["", "22", "10", "21"], filters)
    page.select_option("#others-filter", "21"); page.wait_for_timeout(150)
    check("filter by serial number", len(page.query_selector_all("#others-body tr")) == 6
          and page.inner_text("#others-foot") == "Showing 6 of 21 · scroll the list to see more")
    page.select_option("#others-filter", "10"); page.fill("#others-search", "l2026-0"); page.wait_for_timeout(150)
    check("filter and search together", len(page.query_selector_all("#others-body tr")) == 15,
          len(page.query_selector_all("#others-body tr")))
    page.fill("#others-search", "variante"); page.select_option("#others-filter", ""); page.wait_for_timeout(150)
    rows = page.query_selector_all("#others-body tr")
    check("search by description", len(rows) == 3 and page.inner_text("#others-foot") == "Showing 3 of 21", len(rows))
    # unsaved change: cancelling the confirmation keeps the record, accepting opens the other one
    page.fill("#description", "Café 500 g (edited)")
    page.once("dialog", lambda d: d.dismiss())
    page.click("#others-body tr:nth-child(2) .others-open"); page.wait_for_timeout(600)
    check("unsaved changes: cancelling keeps the record being edited",
          page.input_value("#description") == "Café 500 g (edited)" and page.input_value("#q-22") == "")
    messages = []
    page.once("dialog", lambda d: (messages.append(d.message), d.accept()))
    page.click("#others-body tr:nth-child(2) .others-open"); page.wait_for_timeout(900)
    check("accepting opens the chosen record", page.input_value("#q-22") == "V2"
          and page.input_value("#description") == "Café 500 g variante V2"
          and "unsaved changes" in (messages[0] if messages else ""), (page.input_value("#q-22"), messages))
    check("the list now shows the product among the others", "Every unit" in page.inner_text("#others-body")
          and page.inner_text("#others-title") == "Other records of this GTIN (21)")
    opened = []

    def record_dialog(dialog):
        opened.append(dialog.message)
        dialog.accept()
    page.on("dialog", record_dialog)
    page.fill("#others-search", "lote 3"); page.wait_for_timeout(150)
    page.click("#others-body tr:first-child .others-open"); page.wait_for_timeout(900)
    check("no confirmation without changes", not opened and page.input_value("#q-10") == "L2026-03"
          and page.input_value("#q-22") == "", opened)
    page.remove_listener("dialog", record_dialog)

    # The label block sits under the form at every width, QR code and options side by side
    for width in (1024, 1360, 1920):
        page.set_viewport_size({"width": width, "height": 900}); page.wait_for_timeout(200)
        form_box, panel_box = page.locator("#editor").bounding_box(), page.locator(".label-panel").bounding_box()
        visual, controls = page.locator(".label-visual").bounding_box(), page.locator(".label-controls").bounding_box()
        check(f"{width} px: label under the form, QR code left, options right",
              panel_box["y"] > form_box["y"] + form_box["height"] - 1 and controls["x"] > visual["x"] + visual["width"] - 1
              and abs(controls["y"] - visual["y"]) < 2, (form_box, panel_box, visual, controls))
    page.set_viewport_size({"width": 1360, "height": 1000}); page.wait_for_timeout(200)

    # Key qualifiers (URI Syntax 4.4, 4.6, 4.9)
    page.goto(BASE); page.wait_for_timeout(700)
    check("GTIN qualifiers in path order", [el.get_attribute("data-ai") for el in page.query_selector_all("#qualifiers .qual-field")]
          == ["22", "10", "21", "235"])
    check("235 labelled TPX", "Third-party serialised extension — TPX (235)" in page.inner_text("#qualifiers"))
    page.fill("#key-value", "09506000134352")
    page.fill("#q-21", "S1"); page.fill("#q-10", "L1"); page.fill("#q-22", "V1"); page.wait_for_timeout(300)
    check("preview path follows 4.9 order", "/01/09506000134352/22/V1/10/L1/21/S1" in page.inner_text("#dl"), page.inner_text("#dl"))
    page.fill("#q-235", "TPX1"); page.wait_for_timeout(100)
    check("UPUI (235) cannot be combined with 22/10/21", "does not allow this combination" in page.inner_text("#qual-msg")
          and page.is_disabled("#open"), page.inner_text("#qual-msg"))
    page.fill("#q-235", ""); page.wait_for_timeout(100)
    page.click("#open"); page.wait_for_timeout(600)
    page.fill("#description", "Variant batch serial")
    page.fill(".link-row .url", "https://example.org/serial"); page.click("#description")
    page.click("#save"); page.wait_for_timeout(800)
    stored = [e for e in mock_data_entry.v3("01_09506000134352") if e.get("qualifiers") and len(e["qualifiers"]) == 3]
    check("qualified record stored with its qualifiers in order", stored and stored[0]["qualifiers"] == [{"22": "V1"}, {"10": "L1"}, {"21": "S1"}],
          stored)
    response = ctx.request.get(f"http://127.0.0.1:{PORT}" + page.get_attribute("#download-png", "href"))
    decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(response.body(), np.uint8), 1))[0]
    check("QR code with every qualifier", decoded.endswith("/01/09506000134352/22/V1/10/L1/21/S1"), decoded)

    # GS1 Digital Link data attributes (URI Syntax 4.10): only in the QR code, checked by the syntax engine
    if not portal.syntax.ENGINE.available:
        check("data attributes not offered without the syntax engine", page.is_hidden("#opt-attrs-choice"))
    else:
        check("data attributes offered, editor closed", page.is_visible("#opt-attrs-choice") and page.is_hidden("#attrs"))
        page.check("#opt-attrs"); page.wait_for_timeout(150)
        check("ticking opens the editor with one row", page.is_visible("#attrs")
              and len(page.query_selector_all("#attr-rows .attr-row")) == 1)
        first = "#attr-rows .attr-row:nth-child(1)"
        page.fill(f"{first} .attr-ai", "17"); page.press(f"{first} .attr-ai", "Tab"); page.wait_for_timeout(100)
        check("AI completed with its GS1 data title", page.input_value(f"{first} .attr-ai") == "(17) USE BY or EXPIRY",
              page.input_value(f"{first} .attr-ai"))
        check("format hint from the syntax dictionary", "6 digits · date YYMMDD" in page.inner_text(f"{first} .attr-hint"),
              page.inner_text(f"{first} .attr-hint"))
        page.fill(f"{first} .attr-value", "261399"); page.wait_for_timeout(900)
        check("invalid date refused by the engine", "illegal month" in page.inner_text("#attr-msg"), page.inner_text("#attr-msg"))
        check("nothing downloadable while attributes are wrong", page.get_attribute("#download-png", "href") is None
              and page.is_disabled("#copy") and "Correct the attributes" in page.inner_text("#qr"))
        page.fill(f"{first} .attr-value", "261231"); page.wait_for_timeout(900)
        check("valid attribute accepted", "1 attribute(s) checked" in page.inner_text("#attr-msg"), page.inner_text("#attr-msg"))
        check("preview shows the query string", page.inner_text("#dl").endswith("/21/S1?17=261231")
              and page.is_visible("#legend-attr"), page.inner_text("#dl"))
        check("test link carries the attribute", page.get_attribute("#test", "href").endswith("/21/S1?17=261231"))
        response = ctx.request.get(f"http://127.0.0.1:{PORT}" + page.get_attribute("#download-png", "href"))
        decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(response.body(), np.uint8), 1))[0]
        check("QR code with a data attribute", decoded == "https://id.example.org/01/09506000134352/22/V1/10/L1/21/S1?17=261231",
              decoded)
        page.click("#attr-add"); page.wait_for_timeout(100)
        second = "#attr-rows .attr-row:nth-child(2)"
        page.fill(f"{second} .attr-ai", "10"); page.press(f"{second} .attr-ai", "Tab")
        page.fill(f"{second} .attr-value", "L9"); page.wait_for_timeout(900)
        check("batch/lot refused as attribute of a GTIN (would change the record)",
              "(10) is part of the identification" in page.inner_text("#attr-msg"), page.inner_text("#attr-msg"))
        page.fill(f"{second} .attr-ai", "3103"); page.press(f"{second} .attr-ai", "Tab")
        page.fill(f"{second} .attr-value", "000500"); page.wait_for_timeout(900)
        check("second attribute accepted", page.inner_text("#dl").endswith("?17=261231&3103=000500"), page.inner_text("#dl"))
        page.select_option("#locale", "pt-BR"); page.wait_for_timeout(200)
        check("format hints follow the language", "data AAMMDD" in page.inner_text(f"{first} .attr-hint"),
              page.inner_text(f"{first} .attr-hint"))
        check("names in Portuguese with the GS1 data title", page.input_value(f"{first} .attr-ai")
              == "(17) Data de validade (USE BY or EXPIRY)", page.input_value(f"{first} .attr-ai"))
        page.click(f"{first} .combo-toggle"); page.wait_for_timeout(150)
        option_17 = page.inner_text(f"{first} .combo-option[data-ai='17']")
        check("list shows the same names as the field", option_17 == "(17) Data de validade (USE BY or EXPIRY)", option_17)
        page.keyboard.type("validade"); page.wait_for_timeout(150)
        texts = page.locator(f"{first} .combo-list .combo-option").all_inner_texts()
        check("search by Portuguese name", "(17) Data de validade (USE BY or EXPIRY)" in texts
              and all("validade" in t.lower() for t in texts), texts)
        page.keyboard.press("Escape"); page.wait_for_timeout(100)
        check("Escape restores the chosen attribute", page.input_value(f"{first} .attr-ai")
              == "(17) Data de validade (USE BY or EXPIRY)", page.input_value(f"{first} .attr-ai"))
        page.click(f"{first} .attr-ai"); page.keyboard.type("peso"); page.wait_for_timeout(150)
        page.click("#attr-msg"); page.wait_for_timeout(200)
        check("leaving after a search by name keeps the chosen attribute", page.input_value(f"{first} .attr-ai")
              == "(17) Data de validade (USE BY or EXPIRY)" and "?" not in page.inner_text("#attr-msg"),
              (page.input_value(f"{first} .attr-ai"), page.inner_text("#attr-msg")))
        page.click(f"{second} .combo-toggle"); page.wait_for_timeout(150)
        page.click(f"{second} .combo-option[data-ai='392n']"); page.fill(f"{second} .attr-value", ""); page.wait_for_timeout(900)
        check("family without a value: asks for the value", "Informe o valor do atributo (392n)" in page.inner_text("#attr-msg"),
              page.inner_text("#attr-msg"))
        page.fill(f"{second} .attr-value", "111"); page.wait_for_timeout(900)
        check("association rule in Portuguese, with names", page.inner_text("#attr-msg").startswith(
              "O atributo (392n) exige também um destes: (30) Quantidade variável (VAR. COUNT); (31nn)"), page.inner_text("#attr-msg"))
        page.click(f"{second} .combo-toggle"); page.wait_for_timeout(150)
        page.click(f"{second} .combo-option[data-ai='310n']"); page.wait_for_timeout(100)
        page.fill(f"{second} .attr-value", "000500"); page.wait_for_timeout(900)
        page.select_option("#locale", "en-GB"); page.wait_for_timeout(200)
        page.click(f"{second} .attr-remove"); page.wait_for_timeout(900)
        check("removing a row updates the link", page.inner_text("#dl").endswith("?17=261231"), page.inner_text("#dl"))
        # combo box: the list reopens with one click, filters by name, keyboard choice; key's own AIs not offered
        page.click(f"{first} .attr-ai"); page.wait_for_timeout(150)
        listbox = page.locator(f"{first} .combo-list")
        check("clicking a chosen AI opens the whole list, text selected", listbox.is_visible()
              and "most used" in listbox.inner_text().lower() and "all attributes" in listbox.inner_text().lower()
              and page.evaluate("document.activeElement.selectionEnd - document.activeElement.selectionStart") > 5,
              (listbox.is_visible(), listbox.inner_text()[:80] if listbox.is_visible() else "",
               page.evaluate("[document.activeElement.className, document.activeElement.selectionStart, document.activeElement.selectionEnd]")))
        codes = page.eval_on_selector_all(f"{first} .combo-option", "els => els.map(e => e.dataset.ai)")
        check("list offers attributes only, not the GTIN's key or qualifiers", "17" in codes and "310n" in codes
              and not {"01", "10", "21", "22", "235", "3103"} & set(codes) and "8200" not in codes, len(codes))
        page.keyboard.type("3103"); page.wait_for_timeout(150)
        check("typing a member's number finds its family", listbox.locator(".combo-option").all_inner_texts()
              == ["(310n) NET WEIGHT (kg)"], listbox.locator(".combo-option").all_inner_texts())
        page.keyboard.press("Control+a"); page.keyboard.type("net weight"); page.wait_for_timeout(150)
        check("typing filters by name", listbox.locator(".combo-option").first.inner_text() == "(310n) NET WEIGHT (kg)"
              and all("NET WEIGHT" in t for t in listbox.locator(".combo-option").all_inner_texts()))
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); page.wait_for_timeout(200)
        check("keyboard choice (the first match is active after typing)",
              page.input_value(f"{first} .attr-ai") == "(320n) NET WEIGHT (lb)" and listbox.is_hidden(),
              page.input_value(f"{first} .attr-ai"))
        page.fill(f"{first} .attr-value", "123,45"); page.wait_for_timeout(900)
        check("decimal family: comma typed, right AI and digits in the link", page.inner_text("#dl").endswith("?3202=012345")
              and page.inner_text(f"{first} .attr-resolved") == "→ In the URI: 3202=012345 (2 decimal places)"
              and page.get_attribute(f"{first} .attr-value", "inputmode") == "decimal", page.inner_text("#dl"))
        page.fill(f"{first} .attr-value", "261231")
        page.click(f"{first} .combo-toggle"); page.wait_for_timeout(150)
        page.click(f"{first} .combo-option[data-ai='17']"); page.wait_for_timeout(900)
        check("arrow button, then a click on an option", page.input_value(f"{first} .attr-ai") == "(17) USE BY or EXPIRY"
              and page.inner_text("#dl").endswith("?17=261231"), page.inner_text("#dl"))
        # order of the attributes: up/down buttons
        page.click("#attr-add"); page.wait_for_timeout(100)
        page.fill(f"{second} .attr-ai", "3103"); page.press(f"{second} .attr-ai", "Tab")
        page.fill(f"{second} .attr-value", "000500"); page.wait_for_timeout(900)
        check("first row cannot move up, last cannot move down", page.is_disabled(f"{first} .attr-up")
              and page.is_disabled(f"{second} .attr-down") and page.is_enabled(f"{first} .attr-down"))
        page.click(f"{second} .attr-up"); page.wait_for_timeout(900)
        check("moving a row changes the order in the link", page.inner_text("#dl").endswith("?3103=000500&17=261231"),
              page.inner_text("#dl"))
        # day 00 refused, with the first and last day of the month suggested
        page.fill(f"{second} .attr-value", "260200"); page.wait_for_timeout(900)
        check("day 00 refused with first and last day", "(17): day 00" in page.inner_text("#attr-msg")
              and "(260201)" in page.inner_text("#attr-msg") and "(260228)" in page.inner_text("#attr-msg"), page.inner_text("#attr-msg"))
        page.fill(f"{second} .attr-value", "261231"); page.wait_for_timeout(900)
        # QR options: defaults, version and level used, forced version too small
        check("QR options default to full HRI, automatic version, level M",
              (page.input_value("#opt-hri"), page.input_value("#opt-version"), page.input_value("#opt-ecl")) == ("full", "auto", "m"))
        check("version and level used shown under the code", page.inner_text("#qr-info").startswith("Version ")
              and page.inner_text("#qr-info").endswith("correction M"), page.inner_text("#qr-info"))
        page.select_option("#opt-version", "2"); page.wait_for_timeout(900)
        check("forced version too small: explanation instead of the image", page.locator("#qr .qr-error").is_visible()
              and "does not fit version 2 with correction M" in page.inner_text("#qr")
              and "or higher" in page.inner_text("#qr") and page.locator("#qr img").count() == 0, page.inner_text("#qr"))
        check("nothing to download while the code does not fit", page.get_attribute("#download-png", "href") is None
              and page.inner_text("#qr-info") == "")
        page.select_option("#opt-version", "auto"); page.select_option("#opt-ecl", "h"); page.wait_for_timeout(900)
        check("level H used", page.inner_text("#qr-info").endswith("correction H") and page.locator("#qr img").count() == 1,
              page.inner_text("#qr-info"))
        check("download carries version and level choices", "ecl=h" in page.get_attribute("#download-png", "href")
              and "version=auto" in page.get_attribute("#download-png", "href"))
        page.select_option("#opt-ecl", "m"); page.wait_for_timeout(300)
        page.click("#open"); page.wait_for_timeout(800)
        check("attributes cleared when a record is opened", not page.is_checked("#opt-attrs") and page.is_hidden("#attrs")
              and "?" not in page.inner_text("#dl"), page.inner_text("#dl"))

        # Phone (touch, 390 px): the list opens with a tap on the arrow and an option is chosen with a tap
        phone_ctx = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        phone = phone_ctx.new_page()
        phone.on("pageerror", lambda e: (print(f"FAIL phone page error: {e}"), failures.append(f"phone page error: {e}")))
        phone.goto(BASE); phone.fill("#username", "tester"); phone.fill("#password", "a-long-test-password")
        phone.tap("#password + .reveal")
        check("phone: password shown with a tap", phone.get_attribute("#password", "type") == "text")
        phone.tap("#login-submit"); phone.wait_for_timeout(900)
        phone.fill("#key-value", "09506000134352"); phone.wait_for_timeout(300)
        phone.tap("#opt-attrs"); phone.wait_for_timeout(200)
        phone.tap("#attr-rows .attr-row .combo-toggle"); phone.wait_for_timeout(200)
        check("phone: list opened by a tap", phone.locator("#attr-rows .combo-list").is_visible())
        phone.locator("#attr-rows .combo-option[data-ai='15']").first.tap(); phone.wait_for_timeout(200)
        check("phone: option chosen by a tap", phone.input_value("#attr-rows .attr-ai") == "(15) BEST BEFORE or BEST BY"
              and phone.locator("#attr-rows .combo-list").is_hidden(), phone.input_value("#attr-rows .attr-ai"))
        check("phone: numeric keyboard for a date", phone.get_attribute("#attr-rows .attr-value", "inputmode") == "numeric")
        phone.fill("#attr-rows .attr-value", "270131"); phone.wait_for_timeout(900)
        check("phone: link with the attribute", phone.inner_text("#dl").endswith("?15=270131"), phone.inner_text("#dl"))
        width = phone.evaluate("document.documentElement.scrollWidth")
        check("phone: no horizontal scrolling", width <= 390, width)
        visual, controls = phone.locator(".label-visual").bounding_box(), phone.locator(".label-controls").bounding_box()
        check("phone: label in one column, options under the QR code", controls["y"] > visual["y"] + visual["height"] - 1,
              (visual, controls))
        phone_ctx.close()

    page.select_option("#key-type", "415"); page.fill("#key-value", "9506000134376"); page.wait_for_timeout(200)
    check("415 requires 8020", "requires the qualifier (8020)" in page.inner_text("#qual-msg") and page.is_disabled("#open")
          and "required" in page.inner_text("#qualifiers"), page.inner_text("#qual-msg"))
    page.fill("#q-8020", "INV-2026-1"); page.wait_for_timeout(200)
    check("415 + 8020 accepted", page.is_enabled("#open") and "/415/9506000134376/8020/INV-2026-1" in page.inner_text("#dl"))
    page.select_option("#key-type", "8010"); page.fill("#key-value", "9506000ABC-1"); page.fill("#q-8011", "0123"); page.wait_for_timeout(200)
    check("CPID serial without leading zero", "(8011) is not in an accepted format" in page.inner_text("#qual-msg"), page.inner_text("#qual-msg"))

    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    row = page.query_selector("#records-body tr:has-text('Variant batch serial')")
    check("qualified record in the list", row is not None and "Variant V1 · Batch L1 · Serial S1" in row.inner_text(),
          row.inner_text() if row else None)
    row.query_selector("a").click(); page.wait_for_timeout(800)
    check("qualified record opens with its qualifiers", page.input_value("#q-22") == "V1" and page.input_value("#q-10") == "L1"
          and page.input_value("#q-21") == "S1" and page.input_value("#description") == "Variant batch serial")

    # Governance: history of a record, user administration, reader, temporary password, audit trail
    page.goto(BASE); page.wait_for_timeout(700)
    page.select_option("#key-type", "00"); page.fill("#key-value", "095060001343520000"); page.wait_for_timeout(200)
    page.click("#open"); page.wait_for_timeout(700)
    page.fill("#description", "Pallet 1 (second version)"); page.click("#save"); page.wait_for_timeout(800)
    page.click("#history-toggle"); page.wait_for_timeout(700)
    items = page.query_selector_all("#history-list li")
    check("history panel lists the versions", len(items) == 2 and "Record changed" in items[0].inner_text()
          and "Record created" in items[1].inner_text(), [i.inner_text() for i in items])
    items[1].query_selector("button").click(); page.wait_for_timeout(300)
    check("restore brings the earlier version into the form", page.input_value("#description") == "Pallet 1"
          and "Check it and click Save links" in page.inner_text("#status"), page.inner_text("#status"))

    page.click("#user-button"); page.click("#menu-users"); page.wait_for_timeout(700)
    check("administrator: users view", page.is_visible("#users-view") and "tester" in page.inner_text("#users-body"))
    page.fill("#new-user-name", "reader1"); page.select_option("#new-user-role", "reader")
    page.fill("#new-user-prefixes", "9506000"); page.click("#users-create button[type=submit]"); page.wait_for_timeout(700)
    temp = page.inner_text("#temp-password-value")
    check("new user: temporary password shown once", len(temp) == 16 and "reader1" in page.inner_text("#users-body"), temp)

    reader_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    reader = reader_ctx.new_page()
    reader.goto(BASE); reader.fill("#username", "reader1"); reader.fill("#password", temp)
    reader.click("#login-submit"); reader.wait_for_timeout(1000)
    check("temporary password: the new-password dialog opens", reader.is_visible("#options-dialog")
          and reader.is_visible("#must-change-note"))
    reader.fill("#current-password", temp); reader.fill("#new-password", "reader1-own-password")
    reader.fill("#confirm-password", "reader1-own-password"); reader.click("#password-save"); reader.wait_for_timeout(700)
    reader.click("#password-cancel"); reader.wait_for_timeout(200)
    reader.select_option("#key-type", "00"); reader.fill("#key-value", "095060001343520000"); reader.wait_for_timeout(200)
    reader.click("#open"); reader.wait_for_timeout(800)
    check("reader: record opens read-only", reader.input_value("#description") == "Pallet 1 (second version)"
          and reader.is_disabled("#description") and not reader.is_visible("#save") and reader.is_visible("#read-only-note"))
    check("reader: no administration menu", not reader.is_visible("#menu-users"))
    reader.goto(BASE + "#records"); reader.wait_for_timeout(800)
    rows = reader.inner_text("#records-body")
    check("reader: only records of the prefix 9506000", "095060001343520000" in rows and "07898357410015" not in rows, rows)
    reader_ctx.close()

    page.click("#user-button"); page.click("#menu-audit"); page.wait_for_timeout(900)
    audit_text = page.inner_text("#audit-body")
    check("audit trail view", "User created" in audit_text and "reader1" in audit_text and "Password changed" in audit_text,
          audit_text[:300])

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
