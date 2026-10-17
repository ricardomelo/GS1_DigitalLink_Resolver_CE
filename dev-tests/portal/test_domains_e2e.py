"""
The organisations' own domains in a real browser (Playwright/Chromium; Documentation/adr/0009-tenant-domains.md): the
Domains screen of an organisation's administrator (adding a domain, the TXT record to add, verifying it, default
prefixes, a check), the label panel's *Domain in the QR code* (the default of the prefix, the installation's, a
domain chosen; the address under the code and the downloads following it), an editor without the screen, Portuguese
and a phone's width. DNS lookups and the check's request are replaced inside the portal (domains.txt_records,
domains.probe).

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_domains_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
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
PORT, DATA_ENTRY_PORT = 8195, 3192
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_domains_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import domains  # noqa: E402
import store  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

acme = tenants.create("Acme Foods", ["7891234", "7891235"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("root", "root-password-long", "admin", must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

TXT = {}
domains.txt_records = lambda name: list(TXT.get(name, []))


class Answer:
    status_code, headers = 200, {"Content-Type": "application/json"}

    @staticmethod
    def json():
        return {"resolverRoot": "https://id.acme.example/gs1"}


domains.probe = lambda url: Answer()
BASE = f"http://127.0.0.1:{PORT}/portal/"
ACME = "07891234500014"
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
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    sign_in(page, "ana", "ana-password-long")

    page.click("#user-button")
    check("administrators have Domains in the menu", page.is_visible("#menu-domains"))
    page.click("#menu-domains"); page.wait_for_timeout(900)
    check("the screen opens with its title, no domain yet", page.is_visible("#domains-view")
          and page.inner_text("#hero-title").strip() == "Domains in the QR codes" and page.is_visible("#domains-empty"))
    page.fill("#new-domain", "id.acme.example"); page.fill("#new-domain-stem", "/gs1")
    page.click("#domains-create button[type=submit]"); page.wait_for_timeout(900)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("a domain added: the TXT record to add", card.count() == 1 and "_gs1resolver.id.acme.example" in card.inner_text()
          and "gs1resolver-verify=" in card.inner_text() and "Waiting for DNS" in card.inner_text(), card.inner_text()[:300])
    shot(page, "domains-pending")
    card.locator("button", has_text="Verify").click(); page.wait_for_timeout(800)
    check("verify before the record exists: what to add, said again", "was not found yet" in page.inner_text("#domains-status"),
          page.inner_text("#domains-status"))
    token = card.locator("dd.code").nth(1).inner_text()
    TXT["_gs1resolver.id.acme.example"] = [token]
    card.locator("button", has_text="Verify").click(); page.wait_for_timeout(1000)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("with the record: verified", "Verified" in card.inner_text() and "verified" in page.inner_text("#domains-status"),
          card.inner_text()[:300])
    card.locator("input.domain-defaults").fill("7891234")
    card.locator("button[type=submit]").click(); page.wait_for_timeout(900)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("default prefixes saved", "Default of the QR codes of the prefixes: 7891234" in card.inner_text(), card.inner_text())
    card.locator("button", has_text="Test").click(); page.wait_for_timeout(900)
    check("a check through the domain", "reaches the resolver" in page.inner_text("#domains-status"),
          page.inner_text("#domains-status"))
    # the certificate on the host, as the server's task reports it (ADR 0009, section 7)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("verified: certificate pending, within 5 minutes", card.locator(".domain-cert.is-pending").count() == 1
          and "within 5 minutes" in card.inner_text(), card.inner_text()[:400])
    check("…the server's task is not an organisation's business", page.is_hidden("#domains-host-run"))
    store.col("domain_hosts").insert_one({"_id": "id.acme.example", "state": "failed", "attempts": 1, "error": "certificate",
                                          "nextAttemptAt": store.now() + timedelta(minutes=5), "checkedAt": store.now()})
    page.reload(); page.wait_for_timeout(1000)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("…failed: the reason and the next attempt", card.locator(".domain-cert.is-failed").count() == 1
          and "Let's Encrypt did not validate the domain" in card.inner_text() and "next attempt at" in card.inner_text(),
          card.inner_text()[:400])
    store.col("domain_hosts").update_one({"_id": "id.acme.example"}, {"$set": {
        "state": "served", "attempts": 0, "error": None, "nextAttemptAt": None,
        "certificateUntil": datetime(2027, 1, 15, 12, 0)}})
    page.reload(); page.wait_for_timeout(1000)
    card = page.locator(".domain-card[data-domain='id.acme.example']")
    check("…served, with the certificate's end", card.locator(".domain-cert.is-served").count() == 1
          and "Served over HTTPS" in card.inner_text() and "valid until 15/01/2027" in card.inner_text(),
          card.inner_text()[:400])
    shot(page, "domains-verified")

    # The label panel
    page.goto(BASE); page.wait_for_timeout(900)
    check("the label offers the domain", page.is_visible("#opt-domain")
          and page.eval_on_selector_all("#opt-domain option", "os => os.map(o => o.textContent)")
          == ["Default of the prefix", "id.example.org", "id.acme.example/gs1"],
          page.eval_on_selector_all("#opt-domain option", "os => os.map(o => o.textContent)"))
    page.fill("#key-value", ACME); page.wait_for_timeout(900)
    check("the default domain of the prefix in the address under the code", page.get_attribute("#dl", "href")
          == f"https://id.acme.example/gs1/01/{ACME}", page.get_attribute("#dl", "href"))
    check("…and in the downloads", "domain=" not in (page.get_attribute("#download-svg", "href") or "x")
          and page.get_attribute("#download-svg", "href"))
    page.select_option("#opt-domain", "installation"); page.wait_for_timeout(900)
    check("the installation's address chosen", page.get_attribute("#dl", "href") == f"https://id.example.org/01/{ACME}"
          and "domain=installation" in page.get_attribute("#download-svg", "href"), page.get_attribute("#dl", "href"))
    page.fill("#key-value", "07891235000018"); page.select_option("#opt-domain", ""); page.wait_for_timeout(900)
    check("another prefix by default: the installation's", (page.get_attribute("#dl", "href") or "")
          .startswith("https://id.example.org/01/"), page.get_attribute("#dl", "href"))
    page.select_option("#opt-domain", "id.acme.example"); page.wait_for_timeout(900)
    check("…or the domain chosen", (page.get_attribute("#dl", "href") or "").startswith("https://id.acme.example/gs1/01/"))
    shot(page, "label-domain")

    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(400)
    check("in Portuguese", page.inner_text(".opt-domain span").strip() == "Domínio no QR code")
    page.goto(BASE + "#domains"); page.wait_for_timeout(900)
    check("…the screen too", "Domínios" in page.inner_text("#hero-title") and "Verificado" in page.inner_text("#domains-list"))
    page.select_option("#locale", "en-GB"); page.wait_for_timeout(300)

    page.locator(".domain-card[data-domain='id.acme.example'] button", has_text="Remove").click(); page.wait_for_timeout(300)
    page.click("#ask-ok"); page.wait_for_timeout(900)                     # the portal's own confirmation (ADR 0013)
    check("removed (after a confirmation)", page.locator(".domain-card").count() == 0 and page.is_visible("#domains-empty"))
    page.goto(BASE); page.wait_for_timeout(900)
    check("…the label no longer offers it", page.is_hidden("#opt-domain-field"))

    # The label studio (Documentation/adr/0010-label-studio.md): size, a linear barcode, PDF and ZIP
    page.fill("#key-value", ACME); page.wait_for_timeout(900)
    sizes = page.eval_on_selector_all("#opt-size option", "os => os.map(o => o.textContent)")
    check("label studio: the sizes with their X-dimensions", sizes[0] == "80 % (X 0.396 mm)"
          and sizes[2] == "100 % (X 0.495 mm, recommended)" and sizes[-1] == "200 % (X 0.990 mm)", sizes)
    check("…a linear barcode offered for a GTIN of a consumer unit", page.is_visible("#opt-linear"))
    page.select_option("#opt-size", "150"); page.select_option("#opt-linear", "auto"); page.wait_for_timeout(1200)
    href = page.get_attribute("#download-pdf", "href") or ""
    check("…the downloads carry the options, PDF and ZIP among them", "size=150" in href and "linear=auto" in href
          and href.endswith("format=pdf") and (page.get_attribute("#download-zip", "href") or "").endswith("format=zip"), href)
    check("…the preview drawn with the EAN-13 beside the QR code", page.locator("#qr img").count() == 1
          and "has-error" not in (page.get_attribute("#qr", "class") or ""))
    page.select_option("#key-type", "00"); page.wait_for_timeout(300)
    check("…no linear barcode for an SSCC", page.is_hidden("#opt-linear-field"))
    page.select_option("#key-type", "01"); page.select_option("#opt-size", "100"); page.select_option("#opt-linear", "none")
    page.wait_for_timeout(300)
    # RFID and NFC: the SGTIN of a serial number (portal/epc.py)
    check("RFID/NFC: not offered without a serial number", page.is_hidden("#epc"))
    page.fill("#key-value", ACME); page.fill("#q-21", "1001"); page.wait_for_timeout(900)
    page.click("#epc summary"); page.wait_for_timeout(1200)
    out = page.inner_text("#epc-out")
    check("…with one: the SGTIN-96, the organisation's prefix length, the link for NFC",
          "SGTIN-96" in out and "urn:epc:tag:sgtin-96:1.7891234." in out and "/eh30" in out
          and "7 digits" in page.inner_text("#epc-msg"), (out, page.inner_text("#epc-msg")))
    page.select_option("#epc-filter", "3"); page.wait_for_timeout(1000)
    check("…another filter changes the EPC", "urn:epc:tag:sgtin-96:3.7891234." in page.inner_text("#epc-out"))
    page.fill("#q-21", ""); page.wait_for_timeout(300)
    # Every key with an EPC (item 9.10): a GLN alone (the extension 0), its extension, an SSCC; filter 0 by default
    page.select_option("#key-type", "414"); page.fill("#key-value", "7891234500014"); page.wait_for_timeout(900)
    check("RFID/NFC for a GLN without extension: offered", page.is_visible("#epc"))
    if not page.evaluate("document.getElementById('epc').open"):
        page.click("#epc summary")
    page.wait_for_timeout(1200)
    out = page.inner_text("#epc-out")
    filters = page.eval_on_selector_all("#epc-filter option", "os => os.map(o => o.textContent)")
    check("…its SGLN-96 with the extension 0, filter 0 (all others) by default, the link for NFC",
          "SGLN-96" in out and "urn:epc:tag:sgln-96:0.7891234.50001.0" in out and "/eh32" in out
          and page.input_value("#epc-filter") == "0" and filters[0] == "0 — All others" and filters[1] == "1", (out, filters))
    page.fill("#q-254", "DOCK-3"); page.wait_for_timeout(1200)
    if SHOTS:                                     # the label studio's EPC block, as it stands
        page.locator("#epc").scroll_into_view_if_needed()
        page.locator(".label").screenshot(path=os.path.join(SHOTS, "epc-gln.png"))
    check("…with an alphanumeric extension: SGLN-195", "urn:epc:tag:sgln-195:0.7891234.50001.DOCK-3"
          in page.inner_text("#epc-out"), page.inner_text("#epc-out"))
    page.fill("#q-254", ""); page.select_option("#key-type", "00"); page.fill("#key-value", "378912340000000010")
    page.wait_for_timeout(1200)
    check("…an SSCC: SSCC-96", "urn:epc:tag:sscc-96:0.7891234." in page.inner_text("#epc-out"), page.inner_text("#epc-out"))
    page.select_option("#key-type", "8003"); page.fill("#key-value", "07891234500014"); page.wait_for_timeout(700)
    check("…a GRAI without its serial component: not offered yet", page.is_hidden("#epc"))
    page.fill("#key-value", "0789123450001477"); page.wait_for_timeout(1200)
    check("…with it: GRAI-96", page.is_visible("#epc") and "urn:epc:tag:grai-96:0.7891234.50001.77"
          in page.inner_text("#epc-out"), page.inner_text("#epc-out"))
    page.select_option("#key-type", "417"); page.wait_for_timeout(300)
    check("…a key without an EPC scheme (a party's GLN): not offered", page.is_hidden("#epc"))
    page.select_option("#key-type", "01"); page.wait_for_timeout(300)

    # A server administrator: when the server's task last ran
    admin_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    admin = admin_ctx.new_page()
    admin.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(admin, "root", "root-password-long")
    admin.goto(BASE + "#domains"); admin.wait_for_timeout(1000)
    check("a server administrator: the server's task never ran, said with what to do", admin.is_visible("#domains-host-run")
          and "has not run yet" in admin.inner_text("#domains-host-run")
          and "is-error" in (admin.get_attribute("#domains-host-run", "class") or ""), admin.inner_text("#domains-host-run"))
    store.set_setting("domains.hostRun", {"at": store.now() - timedelta(minutes=3), "ok": True})
    admin.reload(); admin.wait_for_timeout(1000)
    check("…ran 3 minutes ago: when, and that it runs every 5 minutes", "last ran at" in admin.inner_text("#domains-host-run")
          and "is-error" not in (admin.get_attribute("#domains-host-run", "class") or ""), admin.inner_text("#domains-host-run"))
    admin_ctx.close()

    # An editor: no screen
    editor_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    editor = editor_ctx.new_page()
    editor.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(editor, "edu", "edu-password-long")
    editor.goto(BASE + "#domains"); editor.wait_for_timeout(900)
    editor.click("#user-button")
    check("an editor has no Domains screen", not editor.is_visible("#menu-domains") and editor.is_hidden("#domains-view"))
    editor_ctx.close()

    # A phone
    phone_ctx = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    phone = phone_ctx.new_page()
    phone.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(phone, "ana", "ana-password-long")
    phone.goto(BASE + "#domains"); phone.wait_for_timeout(900)
    phone.fill("#new-domain", "m.acme.example"); phone.tap("#domains-create button[type=submit]"); phone.wait_for_timeout(900)
    width = phone.evaluate("document.documentElement.scrollWidth")
    check("a phone: no sideways scrolling", width <= 390, width)
    shot(phone, "domains-phone")
    phone_ctx.close()

    check("no errors in the page", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
