"""
Unit test for portal/linkcheck.py against a local HTTP server (no Internet needed).

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_linkcheck.py
"""
import http.server
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["PORTAL_LINKCHECK_ALLOW_PRIVATE"] = "1"      # the test server is on 127.0.0.1
os.environ["PORTAL_LINKCHECK_TIMEOUT"] = "2"
sys.path.insert(0, os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal")))

import linkcheck  # noqa: E402

failures = []
HITS = {"count": 0}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


class Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self, head: bool):
        HITS["count"] += 1
        path = self.path
        if path == "/head405" and head:
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

linkcheck.ALLOW_PRIVATE = False
linkcheck._cache.clear()
for url in (BASE + "/ok", "http://169.254.169.254/latest/meta-data/", "http://localhost/", "http://10.0.0.1/"):
    r = linkcheck.check_url(url)
    check(f"internal address refused: {url}", r["problem"] == "linkcheck.privateAddress", r)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
