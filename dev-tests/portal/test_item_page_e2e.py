"""
The item's page in a real browser (Playwright/Chromium; Documentation/adr/0011-item-page.md): the editor's option
"Default target: the item's page" (ticked, saved, read back, the first row no longer marked as the default, the shared
default explained for a batch), the Item page screen of an organisation's administrator (a brand with an uploaded
logo, its preview in the brand's colours, edited, its logo removed, the brand removed), an editor without the screen,
the Requests screen's new outcomes, Portuguese and a phone's width.

  pip install -r portal/requirements.txt playwright mongomock pillow && playwright install chromium
  python dev-tests/portal/test_item_page_e2e.py             # SCREENSHOTS=<folder> keeps a picture of each step
"""
import io
import os
import sys
import tempfile
import threading

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8196, 3193
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_itempage_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
ACME = "07891234500014"
LOGO = os.path.join(CONFIG, "logo.png")
out = io.BytesIO()
Image.new("RGB", (120, 40), (230, 40, 40)).save(out, "PNG")
open(LOGO, "wb").write(out.getvalue())
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


def links_of(value, qualifiers=()):
    entries, default = portal.read_entries(f"/01/{value}")
    entry = portal.find_entry(entries, [{q: v} for q, v in qualifiers])
    return default, (entry or {}).get("links", [])


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    sign_in(page, "ana", "ana-password-long")

    # The editor's option
    page.goto(BASE); page.wait_for_timeout(700)
    page.fill("#key-value", ACME); page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(700)
    check("the editor offers the item's page, unticked for a new record", page.is_visible("#landing-page")
          and not page.is_checked("#landing-page")
          and "Default target: the item's page" in page.inner_text(".landing-choice"), page.inner_text(".landing-choice"))
    page.fill("#description", "Acme coffee"); page.fill(".link-row .url", "https://acme.example.com/p")
    page.click("#description")
    page.click("#add"); page.wait_for_timeout(200)
    rows = page.query_selector_all(".link-row")
    rows[1].query_selector(".link-type").select_option("gs1:recipeInfo")
    rows[1].query_selector(".url").fill("https://acme.example.com/recipes")
    check("…the first row marked as the default while unticked", page.is_visible(".link-row:first-child .row-badge"))
    page.check("#landing-page"); page.wait_for_timeout(200)
    check("ticked: no row is marked as the default", page.is_hidden(".link-row:first-child .row-badge")
          and page.is_hidden(".link-row .make-default"))
    shot(page, "item-page-option")
    page.click("#save"); page.wait_for_timeout(900)
    default, links = links_of(ACME)
    check("saved: the record's default is its page", default == "gs1:defaultLink" and any(
        l["href"] == f"https://id.example.org/01/{ACME}?linkType=linkset&view=page" for l in links),
        (default, [l["href"] for l in links]))
    page.goto(BASE + "#records"); page.wait_for_timeout(700)
    page.goto(BASE); page.wait_for_timeout(700)
    page.fill("#key-value", ACME); page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(900)
    check("opened again: ticked, the page link hidden", page.is_checked("#landing-page")
          and page.locator(".link-row").count() == 2, page.locator(".link-row").count())

    # A batch of the same GTIN: the shared default
    opened = page.evaluate("""async () => (await (await fetch('api/record?key=01&value=%s&qualifiers=/10/L1',
                                  {credentials: 'same-origin'})).json())""" % ACME)
    check("a batch of that GTIN: the page is the shared default", opened.get("sharedDefaultLinkType") == "gs1:defaultLink",
          opened)
    page.fill("#q-10", "L1"); page.wait_for_timeout(200); page.click("#open"); page.wait_for_timeout(900)
    check("…opened in the editor: ticked, the shared default said", page.is_checked("#landing-page")
          and "use the item's page" in page.inner_text("#default-msg").lower()
          or "item's page is the default target shared" in page.inner_text("#default-msg"),
          page.inner_text("#default-msg"))
    page.uncheck("#landing-page"); page.wait_for_timeout(200)
    check("…unticked: the mismatch shown as an error", "Tick the option above" in page.inner_text("#default-msg")
          and "is-error" in (page.get_attribute("#default-msg", "class") or ""), page.inner_text("#default-msg"))
    shot(page, "item-page-shared")
    page.check("#landing-page")

    # The Item page screen
    page.click("#user-button")
    check("administrators have Item page in the menu", page.is_visible("#menu-branding"))
    page.click("#menu-branding"); page.wait_for_timeout(900)
    check("the screen opens with its title, no brand yet", page.is_visible("#branding-view")
          and page.inner_text("#hero-title").strip() == "The item's page" and page.is_visible("#branding-empty"))
    check("…Verified by GS1 said to be switched off here", page.is_visible("#branding-verified-off"))
    check("…the organisation's prefixes offered", page.eval_on_selector_all("#brand-prefixes option",
                                                                            "os => os.map(o => o.value)") == ["7891234"])
    page.fill("#brand-prefix", "7891234"); page.fill("#brand-name", "Acme Foods")
    page.fill("#brand-colour", "#3b1f0e"); page.fill("#brand-accent", "#c8a27a")
    page.set_input_files("#brand-logo", LOGO)
    page.click("#branding-form button[type=submit]"); page.wait_for_timeout(1000)
    card = page.locator(".domain-card[data-prefix='7891234']")
    check("a brand saved, with its logo", card.count() == 1 and "Brand of prefix 7891234 saved" in
          page.inner_text("#branding-status") and card.locator("img").count() == 1, page.inner_text("#branding-status"))
    natural = card.locator("img").evaluate("img => img.complete && img.naturalWidth")
    check("…the logo's preview loads from the portal", natural == 120, natural)
    preview = card.locator(".brand-preview")
    check("…the preview in the brand's colours, light text on the dark colour",
          preview.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(59, 31, 14)"
          and preview.evaluate("e => getComputedStyle(e).color") == "rgb(255, 255, 255)",
          preview.evaluate("e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]"))
    check("…its size", "120×40 pixels" in card.inner_text(), card.inner_text())
    shot(page, "item-page-brand")
    card.locator("button", has_text="Edit").click(); page.wait_for_timeout(200)
    check("edit: the form filled with the brand", page.input_value("#brand-name") == "Acme Foods"
          and page.input_value("#brand-colour") == "#3b1f0e")
    page.uncheck("#brand-verified"); page.click("#branding-form button[type=submit]"); page.wait_for_timeout(900)
    card = page.locator(".domain-card[data-prefix='7891234']")
    check("…Verified by GS1 switched off for the brand, the logo kept", "Without Verified by GS1" in card.inner_text()
          and card.locator("img").count() == 1, card.inner_text())
    card.locator("button", has_text="Remove logo").click(); page.wait_for_timeout(900)
    card = page.locator(".domain-card[data-prefix='7891234']")
    check("the logo removed", card.locator("img").count() == 0 and store.col("branding").find_one({"_id": "7891234"})
          .get("logo") is None)
    page.fill("#brand-prefix", "7895555"); page.fill("#brand-name", "Not ours")
    page.click("#branding-form button[type=submit]"); page.wait_for_timeout(800)
    check("another organisation's prefix: refused, said why", "does not belong to this organisation"
          in page.inner_text("#branding-status"), page.inner_text("#branding-status"))

    page.select_option("#locale", "pt-BR"); page.wait_for_timeout(400)
    check("in Portuguese", "Página do item" in page.inner_text("#hero-title") and "Sem Verified by GS1"
          in page.inner_text("#branding-list"), page.inner_text("#hero-title"))
    page.goto(BASE); page.wait_for_timeout(700)
    check("…the editor's option too", "Destino principal: a página do item" in page.inner_text(".landing-choice"))
    page.select_option("#locale", "en-GB"); page.wait_for_timeout(300)
    page.goto(BASE + "#branding"); page.wait_for_timeout(900)
    page.locator(".domain-card[data-prefix='7891234'] button", has_text="Remove brand").click()
    page.wait_for_timeout(900)
    check("the brand removed (after a confirmation)", page.locator(".domain-card").count() == 0
          and page.is_visible("#branding-empty"))

    # The Requests screen
    page.goto(BASE + "#requests"); page.wait_for_timeout(900)
    outcomes = page.eval_on_selector_all("#requests-outcome option", "os => os.map(o => o.textContent)") \
        if page.locator("#requests-outcome").count() else []
    check("the Requests screen filters page views and clicks", "Item page" in outcomes
          and "Click on the item page" in outcomes, outcomes)

    # An editor: no screen
    editor_ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    editor = editor_ctx.new_page()
    editor.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(editor, "edu", "edu-password-long")
    editor.goto(BASE + "#branding"); editor.wait_for_timeout(900)
    editor.click("#user-button")
    check("an editor has no Item page screen", not editor.is_visible("#menu-branding")
          and editor.is_hidden("#branding-view"))
    editor_ctx.close()

    # A phone
    phone_ctx = browser.new_context(locale="en-GB", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    phone = phone_ctx.new_page()
    phone.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(phone, "ana", "ana-password-long")
    phone.goto(BASE + "#branding"); phone.wait_for_timeout(900)
    phone.fill("#brand-prefix", "7891234"); phone.fill("#brand-name", "Acme")
    phone.tap("#branding-form button[type=submit]"); phone.wait_for_timeout(900)
    width = phone.evaluate("document.documentElement.scrollWidth")
    check("a phone: no sideways scrolling", width <= 390, width)
    shot(phone, "item-page-phone")
    phone_ctx.close()

    check("no errors in the page", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
