#!/usr/bin/env python3
"""
Portal session limits and the community notice: the session ends after PORTAL_SESSION_IDLE_MINUTES without use and, whatever the
use, PORTAL_SESSION_MAX_HOURS after the sign-in; the page warns before either end, renews the session
while the user works in it, follows other tabs, and goes to the sign-in page at the end.

The limits are shortened (15 seconds without use, warning 4 seconds before) so the test takes about two
minutes. The server rules are checked with Flask's test client, the page in Chromium (Playwright) against
the in-memory stand-in for the data entry API.

  pip install -r portal/requirements.txt playwright && playwright install chromium
  python dev-tests/portal/test_session.py
"""
import os
import sys
import tempfile
import threading
import time

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
PORT, DATA_ENTRY_PORT = 8198, 3198
IDLE = 15                       # seconds without use
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_DB_NAME=f"devtest_session_{os.getpid()}",
                  PORTAL_ORIGIN=f"http://127.0.0.1:{PORT}", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_SESSION_IDLE_MINUTES=str(IDLE / 60))
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.set_password("tester", "a-long-test-password")
users.create("newcomer", "a-temporary-password", "reader")      # must change the password at sign-in
import app as portal  # noqa: E402

for application, port in [(mock_data_entry.app, DATA_ENTRY_PORT), (portal.app, PORT)]:
    threading.Thread(target=make_server("127.0.0.1", port, application, threaded=True).serve_forever, daemon=True).start()

BASE = f"http://127.0.0.1:{PORT}/portal/"
ORIGIN = {"Origin": f"http://127.0.0.1:{PORT}"}
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def signed_in_client(username="tester", password="a-long-test-password"):
    client = portal.app.test_client()
    client.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return client


# ---------------------------------------------------------------- server rules (test client)
client = signed_in_client()
info = client.get("/portal/api/config").get_json().get("session", {})
check("configuration carries the session limits", info.get("idleSeconds") == IDLE and info.get("warningSeconds") == 4
      and info.get("maxHours") == 12 and 12 * 3600 - 5 <= info.get("endsIn", 0) <= 12 * 3600, info)
check("keep-alive answers the same limits", client.get("/portal/api/session").get_json().get("idleSeconds") == IDLE)

with client.session_transaction("/portal/api/config") as s:                      # signed in longer ago than the absolute limit
    s["since"] = int(time.time()) - 12 * 3600 - 1
answer = client.get("/portal/api/config")
check("absolute limit: a call after 12 hours is refused", answer.status_code == 401
      and answer.get_json().get("code") == "auth.required", answer.status_code)
page = client.get("/portal/")
check("absolute limit: the page goes to the sign-in page with the reason",
      page.status_code == 302 and page.headers["Location"].endswith("login?reason=expired"), page.headers.get("Location"))

client = signed_in_client()
with client.session_transaction("/portal/api/config") as s:                      # session opened before the limit existed
    s.pop("since")
check("a session without a sign-in time keeps working (counted from now)",
      client.get("/portal/api/config").status_code == 200)
with client.session_transaction("/portal/api/config") as s:
    since = s.get("since", 0)
check("… and gets a sign-in time", abs(since - time.time()) < 5, since)

newcomer = signed_in_client("newcomer", "a-temporary-password")
check("keep-alive allowed while a new password is due", newcomer.get("/portal/api/session").status_code == 200)
check("other calls still refused while a new password is due", newcomer.get("/portal/api/records").status_code == 403)

idle = signed_in_client()
renewed = signed_in_client()
time.sleep(IDLE * 0.6)
check("keep-alive within the idle limit", renewed.get("/portal/api/session").status_code == 200)
time.sleep(IDLE * 0.6)
check("idle limit counts from the last call: renewed session still open",
      renewed.get("/portal/api/config").status_code == 200)
check("idle limit: a session without calls for longer is refused", idle.get("/portal/api/config").status_code == 401)


# ---------------------------------------------------------------- the client's address (finding F-004)
# The installation's proxy sets X-Forwarded-For to the one client address it resolved through its trusted proxies
# (frontend_proxy_server/nginx.conf); what a client wrote before it reaches the portal only when nginx is bypassed or
# misconfigured, and must never be the address the throttle counts or the audit trail records.
import store  # noqa: E402
from datetime import timedelta  # noqa: E402

portal.FAILURE_PAUSE = 0                                 # the half second after each wrong password, not tested here
anonymous = portal.app.test_client()
for n in range(portal.MAX_ADDRESS_FAILURES):            # a first address rotated at every attempt, as a forger would
    anonymous.post("/portal/api/login", json={"username": f"nobody{n}", "password": "wrong"},
                   headers={**ORIGIN, "X-Forwarded-For": f"10.9.8.{n}, 198.51.100.7"})
answer = anonymous.post("/portal/api/login", json={"username": "tester", "password": "a-long-test-password"},
                        headers={**ORIGIN, "X-Forwarded-For": "10.9.8.250, 198.51.100.7"})
check("throttle per address: a forged first X-Forwarded-For address rotated at every attempt does not escape it",
      answer.status_code == 429 and answer.get_json().get("code") == "auth.locked", answer.status_code)
for n in range(portal.MAX_ADDRESS_FAILURES):            # failures from 198.51.100.8 naming a victim's address first
    anonymous.post("/portal/api/login", json={"username": f"nobody{n}", "password": "wrong"},
                   headers={**ORIGIN, "X-Forwarded-For": "203.0.113.20, 198.51.100.8"})
answer = portal.app.test_client().post("/portal/api/login", json={"username": "tester", "password": "a-long-test-password"},
                                       headers={**ORIGIN, "X-Forwarded-For": "203.0.113.20"})
check("…and failures cannot be charged to another address by writing it first", answer.status_code == 200,
      answer.status_code)
store.col("login_failures").delete_many({})
anonymous.post("/portal/api/login", json={"username": "nobody-traced", "password": "wrong"},
               headers={**ORIGIN, "X-Forwarded-For": "10.9.8.7, 203.0.113.21"})
traced = store.col("journal").find_one({"action": "login-failed", "user": "nobody-traced"}) or {}
check("the audit trail records the address the proxy set, not the one the client wrote",
      traced.get("detail") == "203.0.113.21", traced.get("detail"))
store.col("login_failures").delete_many({})


# ---------------------------------------------------------------- no lock by user name alone (finding F-005)
# Wrong passwords for a user name delay that user name from that address only, more after each failure; an address
# is limited whatever the user names it tries; the owner signs in from elsewhere.
def sign_in_from(address, password, username="tester"):
    return portal.app.test_client().post("/portal/api/login", json={"username": username, "password": password},
                                         headers={**ORIGIN, "X-Forwarded-For": address})


answers = [sign_in_from("198.51.100.30", "wrong") for _ in range(portal.MAX_LOGIN_FAILURES + 3)]
check("five and more wrong passwords from one address: 401, then a wait from that address",
      [a.status_code for a in answers[:portal.FREE_FAILURES]] == [401] * portal.FREE_FAILURES
      and all(a.status_code == 429 for a in answers[portal.FREE_FAILURES:]), [a.status_code for a in answers])
for _ in range(portal.FREE_FAILURES):                    # a second guessing address: the user name counts six failures
    sign_in_from("198.51.100.31", "wrong")
check("the account's owner still signs in from another address (six failures of the user name from two addresses)",
      portal.throttle.count("user:tester") >= portal.MAX_LOGIN_FAILURES
      and sign_in_from("203.0.113.31", "a-long-test-password").status_code == 200)
waiting = sign_in_from("198.51.100.30", "a-long-test-password")
body = waiting.get_json() or {}
check("from the guessing address even the right password waits: 429 auth.wait with seconds and Retry-After",
      waiting.status_code == 429 and body.get("code") == "auth.wait"
      and 0 < body.get("params", {}).get("seconds", 0) <= portal.FIRST_DELAY_SECONDS
      and waiting.headers.get("Retry-After") == str(body["params"]["seconds"]), (waiting.status_code, body))
check("the wait is not a failure: the address's own count did not grow while it waited",
      portal.throttle.count("user-addr:tester|198.51.100.30") == portal.FREE_FAILURES)
store.col("login_failures").update_many({"key": "user-addr:tester|198.51.100.30"},
                                        {"$set": {"at": store.now() - timedelta(seconds=portal.FIRST_DELAY_SECONDS + 1)}})
check("once the wait has passed, the right password signs in from that address too",
      sign_in_from("198.51.100.30", "a-long-test-password").status_code == 200)
check("…and a sign-in forgets the user name's failures from that address",
      portal.throttle.count("user-addr:tester|198.51.100.30") == 0)
for n in range(portal.MAX_ADDRESS_FAILURES - 1):         # one address trying many user names (password spraying)
    sign_in_from("198.51.100.40", "wrong", username=f"sprayed{n}")
check("one address may try many user names up to its limit", sign_in_from("198.51.100.40", "a-long-test-password").status_code == 200)
sign_in_from("198.51.100.40", "wrong", username="sprayed-last")
answer = sign_in_from("198.51.100.40", "a-long-test-password")
check("then the address waits 15 minutes whatever the user name (auth.locked in minutes)",
      answer.status_code == 429 and (answer.get_json() or {}).get("code") == "auth.locked"
      and (answer.get_json() or {}).get("params", {}).get("minutes") == 15, answer.get_json())
check("a sign-in of one's own does not reset the address's count",
      portal.throttle.count("addr:198.51.100.40") == portal.MAX_ADDRESS_FAILURES)
signed_in = portal.app.test_client()
signed_in.post("/portal/api/login", json={"username": "tester", "password": "a-long-test-password"},
               headers={**ORIGIN, "X-Forwarded-For": "203.0.113.32"})
for n in range(portal.MAX_LOGIN_FAILURES):              # after the owner signed in: wrong passwords from elsewhere
    sign_in_from(f"198.51.100.5{n}", "wrong")
changed = signed_in.post("/portal/api/password", json={"currentPassword": "wrong", "newPassword": "another-long-password"},
                         headers={**ORIGIN, "X-Forwarded-For": "203.0.113.32"})
check("others' wrong sign-in passwords do not lock the owner's password change",
      changed.status_code != 429 and (changed.get_json() or {}).get("code") == "password.currentWrong",
      (changed.status_code, changed.get_json()))
store.col("login_failures").delete_many({})


# ---------------------------------------------------------------- the page (Chromium)
def sign_in(page):
    page.goto(BASE)
    page.fill("#username", "tester")
    page.fill("#password", "a-long-test-password")
    page.click("#login-submit")
    page.wait_for_url("**/portal/#overview")                  # sign-in opens the overview (ADR 0007)
    page.goto(BASE)
    page.wait_for_function("document.body.dataset.role")


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: (print(f"FAIL page error: {e}"), failures.append(f"page error: {e}")))

    page.goto(BASE + "login")
    notice = "not by GS1 or any GS1 Member Organisation. Whoever operates this installation is responsible"
    check("sign-in page: community notice in the footer", notice in page.inner_text("#notice"), page.inner_text("#notice"))
    sign_in(page)
    check("portal: community notice in the footer", notice in page.inner_text("#notice") and page.is_visible("#notice"))
    check("no warning right after the sign-in", not page.is_visible("#session-dialog"))
    page.wait_for_selector("#session-dialog[open]", timeout=(IDLE + 2) * 1000)
    text = page.inner_text("#session-text")
    check("idle warning shown before the end, with a countdown",
          "because it has not been used" in text and "0:0" in text, text)
    check("idle warning offers to stay signed in and to sign out",
          page.is_visible("#session-continue") and page.is_visible("#session-signout")
          and not page.is_visible("#session-close") and page.inner_text("#session-continue") == "Stay signed in")
    page.click("#session-continue")
    page.wait_for_timeout(500)
    check("staying signed in closes the warning", not page.is_visible("#session-dialog"))
    page.wait_for_timeout(5000)                               # past the first idle limit
    status = page.evaluate("fetch('api/config').then(r => r.status)")
    check("… and renews the session on the server", status == 200, status)

    # Work in the page without server calls: key presses renew the session quietly.
    start = time.time()
    shown = False
    while time.time() - start < IDLE + 6:
        page.keyboard.press("Shift")                            # a key press with no server call
        shown = shown or page.is_visible("#session-dialog")
        page.wait_for_timeout(1500)
    check("key presses count as use: no warning while working", not shown)
    check("… and the page is still signed in", "/portal/" in page.url and "login" not in page.url, page.url)

    # Other tabs: calls made in one tab keep the other one open.
    other = ctx.new_page()
    other.goto(BASE)
    other.wait_for_function("document.body.dataset.role")
    start = time.time()
    shown = False
    while time.time() - start < IDLE + 4:
        other.evaluate("fetch('api/session')")               # not through api(): renews the server only
        other.evaluate("localStorage.setItem('gs1resolver.portal.lastContact', String(Date.now()))")
        shown = shown or page.is_visible("#session-dialog")
        page.wait_for_timeout(2000)
    check("a call in another tab keeps this tab open", not shown and "login" not in page.url, page.url)
    other.close()

    # Without use the page goes to the sign-in page, which explains why.
    page.wait_for_url("**/login?reason=expired", timeout=(IDLE + 4) * 1000)
    check("idle end: the page goes to the sign-in page", "reason=expired" in page.url, page.url)
    check("… which says the session has ended", "session has ended" in page.inner_text("#login-status"),
          page.inner_text("#login-status"))

    # Absolute limit: a warning that cannot be extended, then the sign-in page.
    portal.SESSION_MAX_HOURS = 12 / 3600                       # 12 seconds after the sign-in
    sign_in(page)
    start = time.time()
    while not page.is_visible("#session-dialog") and time.time() - start < 15:
        page.keyboard.press("Shift")
        page.wait_for_timeout(500)
    text = page.inner_text("#session-text") if page.is_visible("#session-dialog") else ""
    check("absolute limit: warning before the end", "limit of" in text and "sign in again" in text, text)
    check("… without the option to stay signed in", not page.is_visible("#session-continue")
          and page.is_visible("#session-close"))
    page.click("#session-close")
    page.wait_for_timeout(500)
    check("… which can be closed", not page.is_visible("#session-dialog"))
    page.wait_for_url("**/login?reason=expired", timeout=10000)
    check("absolute end: the page goes to the sign-in page", "reason=expired" in page.url, page.url)
    portal.SESSION_MAX_HOURS = 12

    # Portuguese wording.
    pt = browser.new_context(locale="pt-BR").new_page()
    sign_in(pt)
    pt.wait_for_selector("#session-dialog[open]", timeout=(IDLE + 2) * 1000)
    check("Portuguese notice in the footer", "não pela GS1 nem por qualquer Organização-Membro GS1" in pt.inner_text("#notice"))
    check("Portuguese warning", "Por falta de uso" in pt.inner_text("#session-text")
          and pt.inner_text("#session-continue") == "Continuar conectado", pt.inner_text("#session-text"))
    pt.click("#session-signout")
    pt.wait_for_url("**/login?reason=signedOut", timeout=5000)
    check("signing out from the warning", "reason=signedOut" in pt.url, pt.url)
    browser.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
