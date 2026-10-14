"""
The load test script (dev-tests/load/load_test.py, backlog item 7.4) against a local stand-in server: the rate and the
mix of requests asked, keep-alive connections, the summary (answers, errors, percentiles), the pass/fail thresholds,
the codes file, refusals, and its User-Agent counted as automated by the resolver's request log.

  python dev-tests/load/test_load.py
"""
import json
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [HERE]
import load_test  # noqa: E402

failures = []
SEEN: list[tuple[str, str, str]] = []
CONNECTIONS: set = set()


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Accept", ""), self.headers.get("User-Agent", "")))
        CONNECTIONS.add(self.client_address)
        if "/broken" in self.path:
            status, body = 500, b"error"
        elif self.path.startswith("/slow"):
            time.sleep(0.25)
            status, body = 307, b""
        elif "linkType=linkset" in self.path:
            status, body = 200, b'{"linkset": []}'
        else:
            time.sleep(0.01)
            status, body = 307, b""
        self.send_response(status)
        if status == 307:
            self.send_header("Location", "https://brand.example/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"

# ------------------------------------------------------------------ percentiles
check("nearest-rank percentiles", load_test.percentile(list(range(1, 101)), 95) == 95
      and load_test.percentile([5], 99) == 5 and load_test.percentile([], 50) is None
      and load_test.percentile([1, 2, 3, 4], 50) == 2 and load_test.percentile(list(range(1, 11)), 95) == 10)

# ------------------------------------------------------------------ a steady run
started = time.perf_counter()
summary = load_test.run(BASE, ["/01/09506000134352", "/01/09506000134376/10/B42"], rate=50, duration=2,
                        mix={"scan": 8, "linkset": 1, "page": 1}, workers=8, seed=7)
elapsed = time.perf_counter() - started
check("the rate and duration asked: 100 requests in about 2 s", summary["requests"] == 100 and 1.9 <= elapsed < 4,
      (summary["requests"], elapsed))
kinds = Counter(kind for kind in summary["byKind"] for _ in range(summary["byKind"][kind]["requests"]))
check("the mix asked (scan 80 %, linkset and page 10 % each, ±10)", 70 <= kinds["scan"] <= 90
      and 3 <= kinds["linkset"] <= 20 and 3 <= kinds["page"] <= 20, dict(kinds))
check("answers counted by status", summary["statuses"].get("307", 0) == kinds["scan"]
      and summary["statuses"].get("200", 0) == kinds["linkset"] + kinds["page"], summary["statuses"])
check("no errors, times measured", summary["errors"] == 0 and summary["errorRate"] == 0
      and summary["ms"]["p50"] is not None and summary["ms"]["p50"] >= 10 and summary["ms"]["max"] >= summary["ms"]["p95"],
      summary["ms"])
scans = [s for s in SEEN if "linkType" not in s[0]]
linksets = [s for s in SEEN if "linkType=linkset" in s[0]]
check("scans as a phone's browser asks (text/html), linksets as JSON, the page as HTML",
      all(a == "text/html" for _, a, _ in scans) and {a for _, a, _ in linksets} == {"application/linkset+json", "text/html"})
check("both codes requested, the path kept with its qualifiers", {p.split("?")[0] for p, _, _ in SEEN}
      == {"/01/09506000134352", "/01/09506000134376/10/B42"})
check("keep-alive: one connection per worker, not per request", len(CONNECTIONS) <= 8, len(CONNECTIONS))
SEEN.clear()

# ------------------------------------------------------------------ errors and thresholds
codes = os.path.join(tempfile.mkdtemp(), "codes.txt")
with open(codes, "w") as handle:
    handle.write("# comment\n/broken/01/1\n/01/09506000134352\n\n")
out = os.path.join(tempfile.mkdtemp(), "result.json")
status = load_test.main(["--base", BASE, "--codes", codes, "--rate", "40", "--duration", "1", "--mix", "scan=1",
                         "--json", out, "--seed", "3"])
data = json.load(open(out))
check("server errors counted, the run not passed (status 1)", status == 1 and data["errors"] > 0
      and data["statuses"].get("500") == data["errors"] and data["codes"] == 2, (status, data["statuses"]))
status = load_test.main(["--base", BASE, "--rate", "10", "--duration", "1", "--max-p95", "1000"])
check("a clean run passes (status 0)", status == 0)
status = load_test.main(["--base", BASE + "/slow", "--rate", "10", "--duration", "1", "--max-p95", "100"])
check("a slow p95 does not pass, the base's path kept as a prefix", status == 1
      and any(p.startswith("/slow/01/") for p, _, _ in SEEN), SEEN[-1:])
summary = load_test.run("http://127.0.0.1:9", ["/01/1"], rate=5, duration=1, mix={"scan": 1}, workers=2, timeout=2)
check("no server: every request an error without an answer", summary["errors"] == 5
      and all(k.startswith("no answer") for k in summary["statuses"]), summary["statuses"])

for args, name in ((["--base", "ftp://x"], "an address that is not http(s)"),
                   (["--base", BASE, "--mix", "scan=1,bogus=2"], "an unknown kind of request"),
                   (["--base", BASE, "--rate", "0"], "a rate of zero")):
    try:
        load_test.main(args)
        refused = False
    except SystemExit as exc:
        refused = exc.code == 2
    check(f"refused: {name}", refused)

# ------------------------------------------------------------------ counted as automated by the resolver
sys.path.insert(0, os.path.join(REPO, "web_server", "src"))
try:
    import request_log  # noqa: E402
    check("the resolver's request log counts its User-Agent as automated (kept out of the scans)",
          request_log.device_class(load_test.USER_AGENT) == "automated")
except ImportError as exc:
    check("the resolver's request log can be imported", False, exc)

server.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
