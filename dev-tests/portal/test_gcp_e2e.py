"""
GS1's GCP length table in a real browser (Playwright/Chromium; backlog item 9.9, Documentation/adr/0015-gcp-length-
table.md), with a small table of its own in GS1's format: the panel on the organisations' list (no list, then one
uploaded — compressed by the page — with its date, count and who), a refused file with the entry named, an older list
asked about in the portal's own dialog (cancel keeps, confirm replaces), the warnings beside an organisation's prefixes
on the list and on its page, the company prefix under the key in the editor (a prefix, a range that is not one), the
EPC's partition said to come from the list, Portuguese, and no script errors.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_gcp_e2e.py             # SCREENSHOTS=<folder> keeps a picture of each step
"""
import os
import sys
import tempfile
import threading
from datetime import date, datetime, timezone

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8196, 3193
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_gcp_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("PORTAL_EXPORT_LIMITS", None)
# The age the monitoring reports (ADR 0008), set from today so that the test's list of 17 September 2026 is never old
# and its list of 1 March 2026 always is, whatever the day the test runs
LIST_AGE = (datetime.now(timezone.utc).date() - date(2026, 9, 17)).days
os.environ["PORTAL_MONITOR_GCP_DAYS"] = str(LIST_AGE + 30)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import gcp  # noqa: E402

store.col("gcp_table").delete_many({})
users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Foods", ["7898357", "7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
sent = []                                   # what the page sent: its type and size


@portal.app.before_request
def _seen():
    from flask import request
    if request.path == "/portal/api/gcp" and request.method == "POST":
        sent.append((request.mimetype, request.content_length or 0))


for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()
gcp.RECHECK_SECONDS = 0                     # the server's processes see a new list at once in the test

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def table(entries, date):
    body = "".join(f'  <entry prefix="{p}" gcpLength="{n}" />\n' for p, n in entries)
    return (f'﻿<!--A test list in GS1\'s format.-->\n<GCPPrefixFormatList date="{date}">\n{body}'
            f'</GCPPrefixFormatList>\n').encode("utf-8")


ENTRIES = [("20", 0), ("7890", 7), ("7891", 7), ("7896", 8), ("78983", 9), ("7898357", 12)]
FILES = {}
for name, data in [("list.xml", table(ENTRIES, "2026-09-17T11:04:36.316Z")),
                   ("older.xml", table(ENTRIES[:3], "2026-03-01T00:00:00Z")),
                   ("bad.xml", table([("7890", 7), ("789", 5)], "2026-10-01T00:00:00Z"))]:
    FILES[name] = os.path.join(CONFIG, name)
    open(FILES[name], "wb").write(data)


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)
    page.wait_for_timeout(700)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def upload(page, name):
    page.set_input_files("#gcp-file", FILES[name])
    page.click("#gcp-upload"); page.wait_for_timeout(1500)


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    page = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    natives = []
    page.on("dialog", lambda d: (natives.append(d.message), d.accept()))
    sign_in(page, "root", "root-password-long")

    page.goto(BASE + "#tenants"); page.wait_for_timeout(900)
    check("the organisations' list: the GCP length table panel, no list yet", page.is_visible("#gcp-form")
          and "No list uploaded" in page.inner_text("#gcp-current"), page.inner_text("#gcp-current"))
    check("…no warnings beside the prefixes without a list", page.locator("#tenants-body .gcp-warnings").count() == 0)
    page.click("#gcp-upload"); page.wait_for_timeout(300)
    check("…no file chosen: said so", "Choose the file" in page.inner_text("#gcp-status"))
    upload(page, "bad.xml")
    check("a refused file: the entry named, nothing stored", "Entry 2 is invalid (prefix 789, length 5)"
          in page.inner_text("#gcp-status") and gcp.info() is None, page.inner_text("#gcp-status"))
    upload(page, "list.xml")
    info = gcp.info()
    check("GS1's list uploaded, compressed by the page", sent and sent[-1][0] == "application/gzip"
          and 0 < sent[-1][1] < os.path.getsize(FILES["list.xml"]), sent)
    check("…stored with its date and count", info and info["count"] == 6
          and info["date"] == "2026-09-17T11:04:36Z" and info["uploadedBy"] == "root", info)
    check("…the status and the list in use say so", "GS1's list of 17/09/2026 loaded: 6 prefixes" in
          page.inner_text("#gcp-status") and "GS1's list of 17/09/2026: 6 prefixes, uploaded by root"
          in page.inner_text("#gcp-current"), (page.inner_text("#gcp-status"), page.inner_text("#gcp-current")))
    warnings = page.inner_text("#tenants-body .gcp-warnings")
    check("…the organisation's prefix that disagrees warned beside it (7898357: shorter than 12 digits)",
          "7898357: shorter than the GS1 Company Prefixes it covers (12 digits" in warnings
          and page.locator("#tenants-body .gcp-warnings .is-warn").count() == 1, warnings)
    shot(page, "gcp-tenants")
    upload(page, "older.xml")
    check("an older list: asked in the portal's dialog", page.is_visible("#ask-dialog")
          and "older list of 01/03/2026" in page.inner_text("#ask-text") and not natives, page.inner_text("#ask-text")
          if page.is_visible("#ask-dialog") else natives)
    page.click("#ask-cancel"); page.wait_for_timeout(500)
    check("…cancelled: the list in use kept", gcp.info()["count"] == 6
          and "older than the one in use" in page.inner_text("#gcp-status"), page.inner_text("#gcp-status"))
    upload(page, "older.xml")
    page.click("#ask-ok"); page.wait_for_timeout(1500)
    check("…confirmed: replaced", gcp.info()["count"] == 3 and "01/03/2026" in page.inner_text("#gcp-current"))
    old_days = (datetime.now(timezone.utc).date() - date(2026, 3, 1)).days
    check("a list as old as the monitoring reports: its age said beside it",
          page.is_visible("#gcp-age") and page.inner_text("#gcp-age") == f"This list is {old_days:,} days old (reported "
          f"from {LIST_AGE + 30:,}): upload GS1's latest list.", page.inner_text("#gcp-age"))
    upload(page, "list.xml")
    check("…a recent one: nothing said", not page.is_visible("#gcp-age"))

    page.goto(BASE + "#organisation?id=" + acme["id"]); page.wait_for_timeout(900)
    check("the organisation's page: the warning under its prefixes", "7898357: shorter"
          in page.inner_text("#org-gcp-warnings"), page.inner_text("#org-panel"))

    page.goto(BASE); page.wait_for_timeout(900)
    page.fill("#key-value", "07898357410015"); page.wait_for_timeout(900)
    check("the editor: the key's GS1 Company Prefix under the key, with the list's date",
          page.inner_text("#gcp-hint") == "GS1 Company Prefix: 789835741001 (12 digits, GS1's list of 17/09/2026).",
          page.inner_text("#gcp-hint"))
    page.fill("#key-value", "02000000000008"); page.wait_for_timeout(900)
    check("…a range that is not a GS1 Company Prefix said so", "is not a GS1 Company Prefix"
          in page.inner_text("#gcp-hint") and "is-warn" in page.get_attribute("#gcp-hint", "class"))
    page.fill("#key-value", "0789"); page.wait_for_timeout(700)
    check("…nothing while the key is incomplete", page.is_hidden("#gcp-hint"))
    page.fill("#key-value", "07896123456786"); page.fill("#q-21", "1001"); page.wait_for_timeout(900)   # the operator's
    page.click("#epc summary"); page.wait_for_timeout(1200)
    check("the EPC's partition from GS1's list (8 digits), said so", "urn:epc:tag:sgtin-96:1.78961234.05678.1001"
          in page.inner_text("#epc-out") and "from GS1's list of 17/09/2026" in page.inner_text("#epc-msg"),
          (page.inner_text("#epc-out"), page.inner_text("#epc-msg")))
    shot(page, "gcp-editor")

    pt = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900}).new_page()
    pt.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(pt, "ana", "ana-password-long")
    pt.goto(BASE + "#organisation"); pt.wait_for_timeout(900)
    check("an organisation's administrator in Portuguese: the warning on its page", "7898357: mais curto"
          in pt.inner_text("#org-gcp-warnings") and "17/09/2026" in pt.inner_text("#org-gcp-warnings"),
          pt.inner_text("#org-panel"))
    pt.goto(BASE); pt.wait_for_timeout(900)
    pt.fill("#key-value", "07898357410015"); pt.wait_for_timeout(900)
    check("…and the editor's line", pt.inner_text("#gcp-hint").startswith("Prefixo de empresa GS1: 789835741001 (12"),
          pt.inner_text("#gcp-hint"))
    shot(pt, "gcp-editor-pt")

    check("no script errors", not errors, errors)
    check("the browser's own dialogs never used", not natives, natives)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
