#!/usr/bin/env python3
"""
Load test of a GS1 Resolver CE installation (backlog item 7.4): scans at a steady rate for a while, as phones would
make them, and reports throughput, answers and response times. Python's standard library only, so it runs from any
machine with Python 3.10+.

  python dev-tests/load/load_test.py --base https://id.example.org --codes codes.txt --rate 100 --duration 120
  python dev-tests/load/load_test.py --base http://127.0.0.1:8080 --rate 20 --duration 30 --json result.json

--codes: a file with one GS1 Digital Link path per line (/01/09506000134352, /01/…/10/LOT1 …); without it, GS1's
example GTIN. Each request is one of the mix below, chosen at random with the weights given by --mix
(default scan=90,linkset=5,page=5):
  scan     GET <path>                       Accept: text/html, a phone's browser; the redirect is not followed
  linkset  GET <path>?linkType=linkset      Accept: application/linkset+json, an app reading every link
  page     GET <path>?linkType=linkset      Accept: text/html, the item's page (ADR 0011)
The requests are spread evenly over each second (an open model: a slow server does not slow the arrivals, as with
real scans) and run by --workers threads (default: enough for the rate at 2 s per answer). The User-Agent says what
it is, so the request log counts these requests as automated and keeps them out of the scans.

Exit status 0 when the error rate (no answer, or a 5xx) is at most --max-errors (default 1 %) and the 95th percentile
at most --max-p95 milliseconds (default 1000); 1 otherwise. Run it against staging, or against production only in
an agreed window: it is real load.
"""
import argparse
import http.client
import json
import queue
import random
import ssl
import statistics
import sys
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

USER_AGENT = "gs1-resolver-load-test/1.0 (python; load test bot)"
EXAMPLE = "/01/09506000134352"
KINDS = {"scan": ("", "text/html"), "linkset": ("?linkType=linkset", "application/linkset+json"),
         "page": ("?linkType=linkset", "text/html")}


def parse_mix(text: str) -> dict[str, int]:
    mix = {}
    for part in text.split(","):
        name, _, weight = part.partition("=")
        name = name.strip()
        if name not in KINDS or not weight.strip().isdigit():
            raise argparse.ArgumentTypeError(f"--mix: {part!r} is not one of {', '.join(KINDS)} with a whole weight")
        mix[name] = int(weight)
    if not any(mix.values()):
        raise argparse.ArgumentTypeError("--mix: every weight is zero")
    return mix


def percentile(values: list[float], p: float) -> float | None:
    """The p-th percentile (0–100) by the nearest-rank method; None without values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))          # ceil(n·p/100), at least 1
    return ordered[int(rank) - 1]


class Client:
    """One keep-alive connection per thread to the installation."""

    def __init__(self, base: str, timeout: float, insecure: bool):
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"--base must be an http or https address, not {base!r}")
        self.https, self.host, self.port = parts.scheme == "https", parts.hostname, parts.port
        self.prefix = parts.path.rstrip("/")
        self.timeout = timeout
        self.context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
        self.connection = None

    def _connect(self):
        if self.https:
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self.context)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def get(self, path: str, accept: str) -> tuple[int | None, float, str | None]:
        """(status or None, milliseconds, error)"""
        started = time.perf_counter()
        for attempt in (1, 2):                 # a keep-alive connection the server closed is opened again once
            try:
                if self.connection is None:
                    self.connection = self._connect()
                self.connection.request("GET", self.prefix + path, headers={
                    "Accept": accept, "User-Agent": USER_AGENT, "Accept-Language": "pt-BR,en;q=0.8"})
                response = self.connection.getresponse()
                response.read()
                if response.getheader("Connection", "").lower() == "close":
                    self.connection.close()
                    self.connection = None
                return response.status, (time.perf_counter() - started) * 1000, None
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError) as exc:
                self.connection = None
                if attempt == 2:
                    return None, (time.perf_counter() - started) * 1000, type(exc).__name__
            except (OSError, http.client.HTTPException) as exc:
                self.connection = None
                return None, (time.perf_counter() - started) * 1000, type(exc).__name__
        return None, 0.0, "unreachable"


def run(base: str, paths: list[str], rate: float, duration: float, mix: dict[str, int], workers: int,
        timeout: float = 10.0, insecure: bool = False, seed: int | None = None) -> dict:
    """Sends rate requests a second for duration seconds; gives the summary (see report())."""
    chooser = random.Random(seed)
    kinds = [k for k, w in mix.items() for _ in range(w)]
    jobs: queue.Queue = queue.Queue()
    results: list[tuple[str, int | None, float, str | None, float]] = []
    lock = threading.Lock()
    Client(base, timeout, insecure)          # refuses a bad address before any thread starts

    def worker():
        client = Client(base, timeout, insecure)
        while True:
            job = jobs.get()
            if job is None:
                return
            kind, path, due = job
            status, ms, error = client.get(path + KINDS[kind][0], KINDS[kind][1])
            with lock:
                results.append((kind, status, ms, error, time.perf_counter() - due))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    total = int(rate * duration)
    started = time.perf_counter()
    for i in range(total):
        due = started + i / rate
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        jobs.put((chooser.choice(kinds), chooser.choice(paths), due))
    for _ in threads:
        jobs.put(None)
    for t in threads:
        t.join(timeout + 30)
    elapsed = time.perf_counter() - started
    return report(results, elapsed, rate, duration)


def report(results, elapsed: float, rate: float, duration: float) -> dict:
    times = [ms for _, status, ms, error, _ in results if status is not None]
    statuses = Counter(str(status) if status is not None else f"no answer ({error})" for _, status, _, error, _ in results)
    errors = sum(1 for _, status, _, _, _ in results if status is None or status >= 500)
    late = [wait for *_, wait in results]
    by_kind = {}
    for kind in sorted({r[0] for r in results}):
        kind_times = [ms for k, status, ms, _, _ in results if k == kind and status is not None]
        by_kind[kind] = {"requests": sum(1 for r in results if r[0] == kind),
                         "p50": percentile(kind_times, 50), "p95": percentile(kind_times, 95)}
    return {"asked": {"rate": rate, "duration": duration}, "requests": len(results),
            "throughput": round(len(results) / elapsed, 1) if elapsed else None,
            "statuses": dict(sorted(statuses.items())), "errors": errors,
            "errorRate": round(errors / len(results) * 100, 2) if results else None,
            "ms": {"mean": round(statistics.fmean(times), 1) if times else None, "p50": percentile(times, 50),
                   "p95": percentile(times, 95), "p99": percentile(times, 99), "max": max(times) if times else None},
            "queueingMaxMs": round(max(late) * 1000, 1) if late else None, "byKind": by_kind}


def printable(summary: dict) -> str:
    ms = summary["ms"]
    fmt = lambda v: "-" if v is None else f"{v:.0f}"
    lines = [f"Requests      {summary['requests']} in {summary['asked']['duration']:.0f} s "
             f"(asked {summary['asked']['rate']:g}/s, got {summary['throughput']}/s)",
             "Answers       " + ", ".join(f"{k}: {v}" for k, v in summary["statuses"].items()),
             f"Errors        {summary['errors']} ({summary['errorRate']} %: no answer or 5xx)",
             f"Time (ms)     mean {fmt(ms['mean'])}  p50 {fmt(ms['p50'])}  p95 {fmt(ms['p95'])}  "
             f"p99 {fmt(ms['p99'])}  max {fmt(ms['max'])}"]
    for kind, figures in summary["byKind"].items():
        lines.append(f"  {kind:<10}  {figures['requests']} requests, p50 {fmt(figures['p50'])} ms, "
                     f"p95 {fmt(figures['p95'])} ms")
    lines.append(f"Longest wait for a free worker  {fmt(summary['queueingMaxMs'])} ms "
                 "(large: raise --workers, the figures above then understate)")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True, help="the installation, e.g. https://id.example.org")
    parser.add_argument("--codes", help="file of GS1 Digital Link paths, one per line")
    parser.add_argument("--rate", type=float, default=20, help="requests per second (default 20)")
    parser.add_argument("--duration", type=float, default=30, help="seconds (default 30)")
    parser.add_argument("--mix", type=parse_mix, default=parse_mix("scan=90,linkset=5,page=5"))
    parser.add_argument("--workers", type=int, help="threads (default: rate × 2, at least 4, at most 400)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds per request (default 10)")
    parser.add_argument("--insecure", action="store_true", help="accept a certificate that does not verify")
    parser.add_argument("--max-errors", type=float, default=1.0, help="largest error rate in %% that passes")
    parser.add_argument("--max-p95", type=float, default=1000.0, help="largest p95 in ms that passes")
    parser.add_argument("--json", help="also write the summary to this file")
    parser.add_argument("--seed", type=int, help="the random choices' seed (repeatable runs)")
    args = parser.parse_args(argv)
    if args.rate <= 0 or args.duration <= 0:
        parser.error("--rate and --duration must be positive")
    paths = [EXAMPLE]
    if args.codes:
        with open(args.codes, encoding="utf-8") as handle:
            paths = [line.strip() for line in handle if line.strip().startswith("/")]
        if not paths:
            parser.error(f"{args.codes}: no line starting with /")
    workers = args.workers or min(400, max(4, int(args.rate * 2)))
    try:
        summary = run(args.base, paths, args.rate, args.duration, args.mix, workers, args.timeout, args.insecure,
                      args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    summary["base"], summary["codes"], summary["workers"] = args.base, len(paths), workers
    print(printable(summary))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
    passed = (summary["errorRate"] is not None and summary["errorRate"] <= args.max_errors
              and summary["ms"]["p95"] is not None and summary["ms"]["p95"] <= args.max_p95)
    print("PASSED" if passed else f"NOT PASSED (errors ≤ {args.max_errors} %, p95 ≤ {args.max_p95:g} ms)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
