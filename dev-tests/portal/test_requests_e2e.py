"""
The Requests screen in a real browser (Playwright/Chromium), the log of resolver requests as the portal shows it
(Documentation/adr/0006-resolver-request-log.md): the menu item for every user, the last 30 days as bars, the latest
requests with filters, pages and the CSV export, each user seeing his own scope (an organisation's user, a server
administrator with the organisation column, support access), the tab of the tenant API's calls for administrators
only, the log switched off, both languages and a phone's width. Events are written straight into
resolver_log.requests, as the resolver would.

  pip install -r portal/requirements.txt playwright mongomock && playwright install chromium
  python dev-tests/portal/test_requests_e2e.py               # SCREENSHOTS=<folder> keeps a picture of each step
"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8197, 3198
SHOTS = os.environ.get("SCREENSHOTS")
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_requests_e2e_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL=f"http://127.0.0.1:{PORT}", PORTAL_TIME_ZONE="America/Sao_Paulo")
os.environ["PORTAL_DB_URI"] = "mongomock://"          # events are written into resolver_log, which the portal only reads
os.environ["PORTAL_WORKER"] = "embedded"
os.environ.pop("RESOLVER_LOG_DAYS", None)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
import app as portal  # noqa: E402
import requestlog  # noqa: E402

acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("root", "root-password-long", "admin", must_change=False)
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "reader", tenant=acme["id"], must_change=False)
for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
failures = []
EVENTS = requestlog.events()
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
ACME = "07891234500017"
OPER = "09506000134352"


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def event(value=None, minutes=5, o="redirect", s=307, dev="mobile", **extra):
    t = NOW - timedelta(minutes=minutes)
    doc = {"t": t, "expiresAt": t + timedelta(days=90), "m": "GET", "f": "uri", "s": s, "o": o, "dev": dev, "ms": 12}
    if value:
        doc.update(ai="01", v=value, cp=value[1:])
    doc.update(extra)
    EVENTS.insert_one(doc)


# today: Acme's scans, the operator's, a probe and a crawler; earlier days for the bars
event(ACME, 2, lang="pt-br", lvl="", to="www.acme.example", ref="www.instagram.com", br="chrome", c="BR",
      rg="Sao Paulo", ci="Campinas", ll=[-22.9, -47.1])
# two more places for the map (ADR 0006, section 10), an hour earlier
event(OPER, 60, br="firefox", c="PT", rg="Lisbon", ci="Lisbon", ll=[38.7, -9.1])
event(OPER, 61, br="firefox", c="DE", rg="Berlin", ci="Berlin", ll=[52.5, 13.4])
event(ACME, 3, o="unknown", s=404, lang="en", q={"10": "L7", "21": None})
event(ACME, 4, f="epc", epc="SGTIN+", lvl="/10/L7", to="batch.acme.example", da=["17"], q={"10": "L7", "21": None})
event(OPER, 5, dev="desktop", lt="pip", lvl="", to="www.example.org")
event(None, 6, o="invalid", s=400, p="/wp-login.php", dev="automated")
event(OPER, 7, dev="automated")
for i in range(1, 12):
    for j in range(i % 4 + 1):
        event(ACME if j % 2 else OPER, minutes=60 * 24 * i + j, o="unknown" if j == 2 else "redirect")
for day in range(1, 12):
    requestlog.count_day(requestlog.today() - timedelta(days=day))
for i in range(205):                                       # enough for a second page
    event(OPER, minutes=8 + i / 60, dev="tablet")


def sign_in(page, user, password):
    page.goto(BASE + "login")
    page.fill("#username", user); page.fill("#password", password); page.click("#login-submit")
    page.wait_for_url(BASE + "#overview", timeout=5000)       # sign-in opens the overview (ADR 0007)
    page.goto(BASE)
    page.wait_for_timeout(500)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def rows(page, body="#requests-body"):
    return page.eval_on_selector_all(body + " tr", "rs => rs.map(r => r.innerText)")


with sync_playwright() as p:
    browser = p.chromium.launch()
    errors = []
    ctx = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000}, accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ------------------------------------------------------------ a server administrator: the whole installation
    sign_in(page, "root", "root-password-long")
    page.click("#user-button")
    check("every user has Requests in the menu", page.inner_text("#menu-requests").strip() == "Acessos")
    page.click("#menu-requests"); page.wait_for_timeout(1200)
    check("choosing it closes the menu, though the pointer is still over it", not page.is_visible("#menu-logout"))
    check("the screen opens with its title", page.is_visible("#requests-view")
          and page.inner_text("#hero-title").strip() == "Acessos ao Resolver", page.inner_text("#hero-title"))
    bars = page.eval_on_selector_all("#requests-chart .requests-bar", "bs => bs.length")
    check("30 daily bars", bars == 30, bars)
    summary = page.inner_text("#requests-summary")
    check("the summary counts requests, those not found and automated ones apart", "não encontradas" in summary
          and "automatizadas" in summary, summary)
    first_day = requestlog.day_bounds(requestlog.today() - timedelta(days=29))[0]
    people = EVENTS.count_documents({"t": {"$gte": first_day}, "dev": {"$ne": "automated"}})
    machines = EVENTS.count_documents({"t": {"$gte": first_day}, "dev": "automated"})
    numbers = [int(n) for n in __import__("re").findall(r"\d+", summary.replace(".", ""))]
    check("…people's requests in the bars, automated ones only in the summary",
          numbers[:1] == [people] and numbers[-1:] == [machines], (numbers, people, machines))
    heights = page.eval_on_selector_all("#requests-chart .requests-bar .bar-ok",
                                        "bs => bs.map(b => parseFloat(b.style.height) || 0)")
    check("past days drawn from the aggregates, today from the raw events", heights[-1] > 0
          and sum(1 for h in heights[:-1] if h > 0) >= 10, heights)
    listed = rows(page)
    check("the newest requests first, 200 to a page, automated ones hidden", len(listed) == 200
          and "/01/" + ACME in listed[0] and not any("wp-login" in r for r in listed), (len(listed), listed[:2]))
    check("an event's row: outcome, answer, device, referrer, language",
          "Redirecionada" in listed[0] and "www.acme.example" in listed[0] and "Celular" in listed[0]
          and "www.instagram.com" in listed[0] and "pt-br" in listed[0], listed[0])
    check("…its browser and approximate location (ADR 0006, section 8)", "Chrome" in listed[0]
          and "Campinas, Sao Paulo, BR" in listed[0], listed[0])
    link = page.eval_on_selector("#requests-body tr:first-child td.requests-place a",
                                 "a => [a.href, a.target, a.rel, a.title]")
    check("…the city opens Google Maps searched by its names, in a new tab",
          link[0] == "https://www.google.com/maps/search/?api=1&query=Campinas%2C%20Sao%20Paulo%2C%20BR"
          and link[1] == "_blank" and "noopener" in link[2] and "Campinas, Sao Paulo, BR" in link[3], link)
    check("…the location's source credited (DB-IP, CC BY)", page.is_visible("#requests-geo")
          and page.get_attribute("#requests-geo a", "href") == "https://db-ip.com", page.inner_text("#requests-geo"))
    check("a server administrator sees the organisation of each request", page.is_visible("#requests-body tr .requests-org-col")
          and "Acme Foods" in listed[0], listed[0])
    check("an EPC binary string shows its scheme and the level that answered",
          any("SGTIN+" in r and "nível /10/L7" in r for r in listed), [r for r in listed if "SGTIN" in r])
    check("a serial number appears only as its AI", any("/21/*" in r for r in listed))
    check("more requests: a button", page.is_visible("#requests-more"))

    # The map of requests (ADR 0006, section 10): closed until asked for, then countries shaded and cities drawn
    check("the map: closed at first, nothing loaded", not page.is_visible("#requests-map svg")
          and not page.evaluate("Boolean(window.d3)"))
    page.click("#requests-map-box summary")
    page.wait_for_selector("#requests-map svg path.map-country", timeout=10000)
    shades = page.eval_on_selector_all("#requests-map path.map-country", "ps => Object.fromEntries(ps.filter(p => "
                                       "p.dataset.code).map(p => [p.dataset.code, p.getAttribute('fill')]))")
    check("…the world's countries, those with requests shaded", len(shades) > 150 and shades["BR"] != shades["FR"]
          and shades["PT"] != shades["FR"] and shades["FR"].upper() == "#E6EBF1", {k: shades.get(k) for k in ("BR", "PT", "FR")})
    check("…a circle for each city the resolver placed", page.locator("#requests-map circle.map-city").count() == 3)
    check("…a summary of the requests located", "3 de" in page.inner_text("#requests-map .map-side")
          and "3 países" in page.inner_text("#requests-map .map-side"), page.inner_text("#requests-map .map-side"))
    check("…credits the map and the GeoIP database", "Natural Earth" in page.inner_text("#requests-map-box")
          and page.get_attribute("#requests-map-box a", "href") == "https://db-ip.com")
    page.dispatch_event('#requests-map path[data-code="BR"]', "click"); page.wait_for_timeout(900)
    side = page.inner_text("#requests-map .map-side")
    check("…a click on a country zooms to it and lists its regions and cities", "Brasil" in side and "Sao Paulo" in side
          and "Campinas" in side and "is-focus" in page.get_attribute('#requests-map path[data-code="BR"]', "class")
          and "scale" in (page.get_attribute("#requests-map svg > g", "transform") or ""), side)
    page.click("#requests-map .map-tools button:nth-child(3)"); page.wait_for_timeout(600)
    check("…the whole world again", "Campinas" not in page.inner_text("#requests-map .map-side"))
    shot(page, "requests-map")
    shot(page, "requests-admin")
    page.click("#requests-more"); page.wait_for_timeout(800)
    check("…which adds the next page", len(rows(page)) > 200 and not page.is_visible("#requests-more"), len(rows(page)))

    page.select_option("#requests-browser", "chrome"); page.click("#requests-filters button[type=submit]")
    page.wait_for_timeout(800)
    listed = rows(page)
    check("filter: a browser", len(listed) == 1 and "Chrome" in listed[0], listed[:3])
    page.select_option("#requests-browser", ""); page.fill("#requests-country", "br")
    page.click("#requests-filters button[type=submit]"); page.wait_for_timeout(800)
    listed = rows(page)
    check("filter: a country, typed in either case", len(listed) == 1 and "Campinas" in listed[0], listed[:3])
    page.wait_for_timeout(500)
    check("…the map follows the filters", page.locator("#requests-map circle.map-city").count() == 1
          and "1 de 1 " in page.inner_text("#requests-map .map-side"), page.inner_text("#requests-map .map-side"))
    page.fill("#requests-country", "")
    page.select_option("#requests-outcome", "notFound"); page.click("#requests-filters button[type=submit]")
    page.wait_for_timeout(800)
    listed = rows(page)
    check("filter: not found (404)", listed and all("Código não cadastrado" in r or "Sem link" in r for r in listed), listed[:3])
    page.select_option("#requests-outcome", ""); page.fill("#requests-code", ACME[1:])
    page.click("#requests-filters button[type=submit]"); page.wait_for_timeout(800)
    listed = rows(page)
    check("filter: a GTIN-13", listed and all(ACME in r for r in listed), listed[:3])
    page.fill("#requests-code", ""); page.check("#requests-automated")
    page.click("#requests-filters button[type=submit]"); page.wait_for_timeout(800)
    check("automated requests on request, also a probe without a key", any("/wp-login.php" in r and "Requisição inválida" in r
                                                                            for r in rows(page)))
    with page.expect_download() as download:
        page.click("#requests-csv")
    path = download.value.path()
    text = open(path, encoding="utf-8-sig").read()
    check("CSV export with the filters, the organisation column", download.value.suggested_filename.startswith("resolver-requests-")
          and "wp-login.php" in text and text.splitlines()[0].endswith(";organisation"), text[:120])
    page.uncheck("#requests-automated")

    page.click("#requests-tab-api"); page.wait_for_timeout(600)
    check("administrators have the tenant API's tab (no call yet)", page.is_visible("#requests-api")
          and page.is_visible("#requests-api-empty"))

    # how long requests are kept (ADR 0006, section 8)
    page.click("#requests-tab-retention"); page.wait_for_timeout(800)
    check("a Retention tab: the installation's days, the default, the space", page.is_visible("#requests-retention")
          and page.input_value("#retention-global-days") == "90" and "RESOLVER_LOG_DAYS" in page.inner_text("#retention-default")
          and page.is_visible("#retention-space") and "requisições" in page.inner_text("#retention-space"),
          page.inner_text("#requests-retention")[:300])
    org_rows = rows(page, "#retention-orgs-body")
    check("…every organisation with its requests kept", len(org_rows) == 1 and "Acme Foods" in org_rows[0], org_rows)
    page.fill("#retention-global-days", "5000"); page.click("#retention-global-save"); page.wait_for_timeout(600)
    check("…too many days refused with the limit", "3.650" in page.inner_text("#retention-status")
          and requestlog.global_days() == 90, page.inner_text("#retention-status"))
    page.fill("#retention-global-days", "120"); page.click("#retention-global-save"); page.wait_for_timeout(800)
    check("…the installation's days saved", "120" in page.inner_text("#retention-status") and requestlog.global_days() == 120
          and page.input_value("#retention-global-days") == "120", page.inner_text("#retention-status"))
    page.fill(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] input", "30")
    page.click(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] button"); page.wait_for_timeout(800)
    check("…an organisation's fewer days saved", tenants.get(acme["id"])["logDays"] == 30
          and page.input_value(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] input") == "30",
          page.inner_text("#retention-status"))
    check("…the most space on disk: empty (no limit), with what it does", page.is_visible("#retention-max-mb")
          and page.input_value("#retention-max-mb") == "" and "80 %" in page.inner_text("#retention-max-hint")
          and not page.is_visible("#retention-max-share"), page.inner_text("#requests-retention")[:400])
    page.fill("#retention-max-mb", "0"); page.click("#retention-max-save"); page.wait_for_timeout(600)
    check("…0 MB refused", "megabytes" in page.inner_text("#retention-status") and requestlog.max_bytes() is None,
          page.inner_text("#retention-status"))
    page.fill("#retention-max-mb", "2048"); page.click("#retention-max-save"); page.wait_for_timeout(800)
    check("…2048 MB saved and shown as 2 GB", "2 GB" in page.inner_text("#retention-status")
          and requestlog.max_bytes() == 2048 * 1048576 and page.input_value("#retention-max-mb") == "2048",
          page.inner_text("#retention-status"))
    page.fill("#retention-max-mb", ""); page.click("#retention-max-save"); page.wait_for_timeout(800)
    check("…emptied: no limit", requestlog.max_bytes() is None and page.input_value("#retention-max-mb") == "",
          page.inner_text("#retention-status"))
    page.fill("#retention-max-mb", "2048"); page.click("#retention-max-save"); page.wait_for_timeout(800)
    shot(page, "requests-retention")
    page.click("#requests-tab-resolver")

    # support access: the organisation's requests only
    status = page.evaluate("""async () => (await fetch('api/support', {method: 'POST', headers: {'Content-Type':
        'application/json'}, body: JSON.stringify({tenant: '%s', reason: 'Ticket 9'})})).status""" % acme["id"])
    page.goto(BASE + "#requests"); page.reload(); page.wait_for_timeout(1500)   # as the Organisations screen does
    listed = rows(page)
    check("support access: the organisation's requests only, no organisation column", status == 200
          and listed and all(ACME in r for r in listed) and not page.is_visible("#requests-body tr .requests-org-col"),
          (status, [r for r in listed if ACME not in r][:3]))
    page.evaluate("async () => { await fetch('api/support', {method: 'DELETE'}); }")
    page.reload(); page.wait_for_timeout(800)

    # ------------------------------------------------------------ English
    page.select_option("#locale", "en-GB"); page.goto(BASE + "#requests"); page.wait_for_timeout(1200)
    check("English: title, filters and outcomes", page.inner_text("#hero-title").strip() == "Resolver requests"
          and "Redirected" in rows(page)[0] and page.inner_text("label[for=requests-outcome]").strip() == "Outcome",
          page.inner_text("#hero-title"))
    shot(page, "requests-admin-en")
    ctx.close()

    # ------------------------------------------------------------ an organisation's reader and administrator
    ctx = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "edu", "edu-password-long")
    page.goto(BASE + "#requests"); page.wait_for_timeout(1200)
    listed = rows(page)
    check("a reader of an organisation sees its requests only", len(listed) >= 3 and all(ACME in r for r in listed),
          listed[:3])
    check("…without the organisation column or the API tab", not page.is_visible("#requests-body tr .requests-org-col")
          and not page.is_visible("#requests-tab-api"))
    ctx.close()

    ctx = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    sign_in(page, "ana", "ana-password-long")
    key = page.evaluate("""async () => (await (await fetch('api/keys', {method: 'POST', headers: {'Content-Type':
        'application/json'}, body: JSON.stringify({name: 'ERP', scopes: ['records:read'], days: 30})})).json()).key""")
    page.evaluate("async k => { await fetch('api/v1/', {headers: {Authorization: 'Bearer ' + k}}); }", key)
    page.goto(BASE + "#requests"); page.wait_for_timeout(1000)
    page.click("#requests-tab-api"); page.wait_for_timeout(800)
    listed = rows(page, "#requests-api-body")
    check("an organisation's administrator sees its key's calls", len(listed) == 1 and "ERP" in listed[0]
          and "/portal/api/v1/" in listed[0] and "200" in listed[0], listed)
    check("…never the key's secret", key.split(".")[1] not in page.content())
    shot(page, "requests-api")
    page.click("#requests-tab-retention"); page.wait_for_timeout(800)
    check("…its Retention tab: the installation's days read only, its organisation's editable",
          page.is_disabled("#retention-global-days") and not page.is_visible("#retention-global-save")
          and page.input_value(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] input") == "30"
          and not page.is_visible("#retention-space") and not page.is_visible("#retention-max"),
          page.inner_text("#requests-retention")[:300])
    page.fill(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] input", "200")
    page.click(f"#retention-orgs-body tr[data-tenant='{acme['id']}'] button"); page.wait_for_timeout(600)
    check("…never longer than the installation's", "120" in page.inner_text("#retention-status")
          and tenants.get(acme["id"])["logDays"] == 30, page.inner_text("#retention-status"))
    ctx.close()

    # ------------------------------------------------------------ a phone; the log switched off
    phone = browser.new_context(locale="pt-BR", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = phone.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, "root", "root-password-long")
    page.goto(BASE + "#requests"); page.wait_for_timeout(1200)
    width = page.evaluate("() => document.documentElement.scrollWidth")
    check("a phone: no sideways scrolling, rows as cards with labels", width <= 392
          and page.eval_on_selector("#requests-body td", "td => getComputedStyle(td, '::before').content").startswith('"'),
          width)
    shot(page, "requests-phone")
    page.click("#requests-tab-retention"); page.wait_for_timeout(800)
    width = page.evaluate("() => document.documentElement.scrollWidth")
    check("…the Retention tab too", width <= 392 and page.is_visible("#retention-orgs-body tr"), width)
    os.environ["RESOLVER_LOG_DAYS"] = "0"
    page.reload(); page.wait_for_timeout(1200)
    check("the log switched off: a notice", page.is_visible("#requests-off"))
    del os.environ["RESOLVER_LOG_DAYS"]
    phone.close()
    check("no script errors", not errors, errors)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
