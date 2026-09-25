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

    page.hover("#user-button"); page.wait_for_timeout(200)
    check("user menu on hover", page.is_visible("#menu-logout"))
    page.click("#user-button"); page.click("#menu-options")
    page.fill("#current-password", "a-long-test-password"); page.fill("#new-password", "another-long-password")
    page.fill("#confirm-password", "another-long-password"); page.click("#password-save"); page.wait_for_timeout(600)
    check("password changed", "Password changed" in page.inner_text("#password-status"))
    page.click("#options-close"); page.hover("#user-button"); page.click("#menu-logout"); page.wait_for_timeout(500)
    check("signed out", "reason=signedOut" in page.url, page.url)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
