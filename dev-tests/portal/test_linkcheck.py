"""
Unit test for portal/linkcheck.py against a local HTTP server (no Internet needed).

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_linkcheck.py
"""
import http.server
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["PORTAL_LINKCHECK_ALLOW_PRIVATE"] = "1"      # the test server is on 127.0.0.1
os.environ["PORTAL_LINKCHECK_TIMEOUT"] = "2"
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # the cache is in the portal's database
os.environ["PORTAL_DB_NAME"] = f"devtest_linkcheck_{os.getpid()}"
sys.path.insert(0, os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal")))

import linkcheck  # noqa: E402

failures = []
HITS = {"count": 0}
BUSY = {"now": 0, "most": 0}
LOCK = threading.Lock()


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


class Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self, head: bool):
        HITS["count"] += 1
        path = self.path
        if path.startswith("/slow"):                   # how many requests to this host at once
            with LOCK:
                BUSY["now"] += 1
                BUSY["most"] = max(BUSY["most"], BUSY["now"])
            time.sleep(0.2)
            with LOCK:
                BUSY["now"] -= 1
            self.send_response(200)
        elif path == "/head405" and head:
            self.send_response(405)
        elif path in ("/ok", "/head405", "/counted"):
            self.send_response(200)
        elif path == "/missing":
            self.send_response(404)
        elif path == "/forbidden":
            self.send_response(403)
        elif path == "/broken":
            self.send_response(500)
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
        elif path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", path + "x")
        else:
            self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._answer(True)

    def do_GET(self):
        self._answer(False)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"

r = linkcheck.check_url(BASE + "/ok")
check("200 → ok", r["ok"] and r["status"] == 200 and r["problem"] is None, r)
r = linkcheck.check_url(BASE + "/missing")
check("404 → httpError", r["problem"] == "linkcheck.httpError" and r["params"] == {"status": 404}, r)
r = linkcheck.check_url(BASE + "/broken")
check("500 → httpError", r["problem"] == "linkcheck.httpError" and r["status"] == 500, r)
r = linkcheck.check_url(BASE + "/forbidden")
check("403 → blocked (site refuses robots), not an error", r["problem"] == "linkcheck.blocked", r)
r = linkcheck.check_url(BASE + "/head405")
check("HEAD refused → GET used", r["ok"], r)
r = linkcheck.check_url(BASE + "/redirect")
check("redirect followed to the final page", r["ok"] and r["finalUrl"].endswith("/ok"), r)
r = linkcheck.check_url(BASE + "/loop")
check("endless redirects stopped", r["problem"] == "linkcheck.tooManyRedirects", r)
r = linkcheck.check_url("http://127.0.0.1:9/unused")
check("closed port → unreachable", r["problem"] == "linkcheck.unreachable", r)
r = linkcheck.check_url("https://no-such-host.invalid/x")
check("unknown domain → unreachable", r["problem"] == "linkcheck.unreachable", r)
check("https → http hop is a downgrade", linkcheck.is_downgrade("https://a.org/x", "http://a.org/y")
      and not linkcheck.is_downgrade("https://a.org/x", "https://b.org/y")
      and not linkcheck.is_downgrade("http://a.org/x", "http://b.org/y"))

before = HITS["count"]
linkcheck.check_url(BASE + "/counted")
linkcheck.check_url(BASE + "/counted")
check("results cached: the site is contacted once", HITS["count"] - before == 1, HITS["count"] - before)

seen = []
results = linkcheck.check_many([BASE + "/ok", BASE + "/missing", BASE + "/ok"], lambda d, t: seen.append((d, t)))
check("check_many: distinct URLs, progress reported", len(results) == 2 and seen[-1] == (2, 2), (results.keys(), seen))

# ADR 0029: at most PER_HOST requests to one host at once, other hosts not held up; stopping leaves the rest unrequested
linkcheck.clear_cache()
BUSY["most"] = 0
started = time.monotonic()
results = linkcheck.check_many([BASE + f"/slow/{n}" for n in range(8)])
check(f"check_many: at most {linkcheck.PER_HOST} requests to one host at once (8 addresses, 8 threads)",
      linkcheck.PER_HOST == 2 and BUSY["most"] == 2 and all(r["ok"] for r in results.values()), (BUSY, results))
OTHER = BASE.replace("127.0.0.1", "localhost")          # the same server under another host name
linkcheck.clear_cache()
BUSY["most"] = 0
results = linkcheck.check_many([BASE + f"/slow/a{n}" for n in range(4)] + [OTHER + f"/slow/b{n}" for n in range(4)])
check("check_many: two hosts are checked side by side (up to 2 each)", BUSY["most"] == 4 and len(results) == 8, BUSY)
linkcheck.clear_cache()
HITS["count"] = 0


class Stop(Exception):
    pass


def stop_at_third(done, total):
    if done == 3:
        raise Stop()


try:
    linkcheck.check_many([BASE + f"/slow/s{n}" for n in range(30)], stop_at_third)
    stopped = False
except Stop:
    stopped = True
check("check_many: an exception in progress stops the check; addresses not started are not requested",
      stopped and HITS["count"] < 30, HITS)
linkcheck.clear_cache()
r = linkcheck.check_many([BASE + "/ok", BASE + "/missing"])
check("check_many: results keyed by address in the order given", list(r) == [BASE + "/ok", BASE + "/missing"], list(r))

linkcheck.ALLOW_PRIVATE = False
linkcheck.clear_cache()
HITS["count"] = 0
for url in ("https://127.0.0.1/ok", "https://169.254.169.254/latest/meta-data/", "https://localhost/",
            "https://10.0.0.1/", "https://[::1]/", "https://[::ffff:127.0.0.1]/", "https://[::ffff:10.0.0.1]/",
            "https://100.64.0.1/", "https://0.0.0.0/"):
    r = linkcheck.check_url(url)
    check(f"internal address refused: {url}", r["problem"] == "linkcheck.privateAddress", r)
for url in (BASE + "/ok", "http://example.org/"):
    r = linkcheck.check_url(url)
    check(f"http:// address reported without a request (insecureAddress): {url}",
          r["problem"] == "linkcheck.insecureAddress" and r["status"] is None, r)
r = linkcheck.check_url("https://user:secret@example.org/")
check("an address with user information is invalid, not requested", r["problem"] == "linkcheck.invalid", r)
check("nothing reached the local server without ALLOW_PRIVATE", HITS["count"] == 0, HITS)

# DNS rebinding: the name's first answer is public, the next ones the local server. The check must connect to the
# address it checked (here a public one, refused below as there is no network), never to the name resolved again.
real_getaddrinfo, real_connect = socket.getaddrinfo, None
answers = {"n": 0}


def rebinding(host, *args, **kwargs):
    if host == "rebind.test":
        answers["n"] += 1
        address = "93.184.216.34" if answers["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, args[0] if args else 0))]
    return real_getaddrinfo(host, *args, **kwargs)


import urllib3.util.connection as u3c  # noqa: E402
real_connect = u3c.create_connection
dialled = []


def connect(address, *args, **kwargs):
    dialled.append(address[0])
    if address[0] == "93.184.216.34":                # the public address: no network here, refused at once
        raise ConnectionRefusedError("no network in the test")
    return real_connect(address, *args, **kwargs)


socket.getaddrinfo, u3c.create_connection = rebinding, connect
try:
    linkcheck.clear_cache()
    HITS["count"] = 0
    port = BASE.rsplit(":", 1)[1]
    r = linkcheck.check_url(f"https://rebind.test:{port}/ok")
finally:
    socket.getaddrinfo, u3c.create_connection = real_getaddrinfo, real_connect
check("rebinding: the request goes to the address checked (unreachable), never to the local server",
      r["problem"] == "linkcheck.unreachable" and HITS["count"] == 0 and set(dialled) == {"93.184.216.34"},
      (r, HITS, dialled))

# ------------------------------------------------------------------ the daily budget per organisation (ADR 0060)
from datetime import date, timedelta as _td  # noqa: E402

import requestlog  # noqa: E402
import store  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

os.environ.pop("PORTAL_LINKCHECK_DAILY_LIMIT", None)
check("the daily limit: 20,000 addresses by default", linkcheck.daily_limit() == 20000, linkcheck.daily_limit())
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = "many"
check("…a value that is not a whole number: the default", linkcheck.daily_limit() == 20000, linkcheck.daily_limit())
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = "10"
linkcheck.reserve("t-a", 6)
check("a check within the day's budget is counted", linkcheck.used_today("t-a") == 6, linkcheck.used_today("t-a"))


def refused(tenant, count):
    try:
        linkcheck.reserve(tenant, count)
    except linkcheck.OverBudget as exc:
        return exc.limit, exc.left
    return None


check("…one that does not fit is refused with what is left, and nothing counted",
      refused("t-a", 5) == (10, 4) and linkcheck.used_today("t-a") == 6, (refused("t-a", 5), linkcheck.used_today("t-a")))
linkcheck.reserve("t-a", 4)
check("…exactly what is left fits; then nothing more", linkcheck.used_today("t-a") == 10 and refused("t-a", 1) == (10, 0))
check("…another organisation and the operator have days of their own",
      refused("t-b", 10) is None and refused(None, 3) is None and linkcheck.used_today("t-b") == 10
      and linkcheck.used_today(None) == 3)
check("…more than a whole day's budget at once: refused without counting",
      refused("t-c", 11) == (10, 10) and linkcheck.used_today("t-c") == 0)
doc = store.col("linkcheck_budget").find_one({"_id": f"t-a|{requestlog.today().isoformat()}"})
check("…one document per organisation and day of the installation, removed two days later (TTL)",
      doc and doc["tenant"] == "t-a" and doc["day"] == requestlog.today().isoformat()
      and _td(days=1) < doc["expiresAt"] - store.now() <= _td(days=2), doc)
real_today = requestlog.today
requestlog.today = lambda: real_today() + _td(days=1)
try:
    check("…the next day starts again", refused("t-a", 10) is None and linkcheck.used_today("t-a") == 10)
finally:
    requestlog.today = real_today
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = "0"
check("…0: no limit, nothing counted", refused("t-a", 1000) is None and linkcheck.used_today("t-a") == 10)
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = "10"


class Down:
    def update_one(self, *args, **kwargs):
        raise PyMongoError("down")


real_col = store.col
store.col = lambda name: Down() if name == "linkcheck_budget" else real_col(name)
try:
    check("…the database cannot be written: the check goes ahead", refused("t-d", 5) is None)
finally:
    store.col = real_col
os.environ.pop("PORTAL_LINKCHECK_DAILY_LIMIT", None)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
