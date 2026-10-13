"""
The portal's job worker as real processes ("python worker.py", as the portal-worker service runs it) sharing
one MongoDB: several workers share a queue without taking a job twice; "docker stop" (SIGTERM) hands the job
in hand back to the queue at once and another worker finishes it; a worker that is killed (SIGKILL) leaves
its job running until its heartbeat is old, then another worker continues it.

Needs a real MongoDB in PORTAL_DB_URI (processes cannot share mongomock's memory): test_store_mongodb.py runs
it as the portal's own user in the continuous integration and relays its lines.

  PORTAL_DB_URI=mongodb://... PORTAL_DB_NAME=... python dev-tests/portal/test_worker_processes.py
"""
import http.server
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
if os.environ.get("PORTAL_DB_URI", "mongomock://").startswith("mongomock://"):
    print("FAIL a real MongoDB is needed in PORTAL_DB_URI (run through test_store_mongodb.py)")
    sys.exit(1)
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_workers_{os.getpid()}")
os.environ.update(SESSION_TOKEN="tok", FQDN="id.example.org", PORTAL_CONFIG_DIR=tempfile.mkdtemp(),
                  PORTAL_LINKCHECK_ALLOW_PRIVATE="1", DATA_ENTRY_URL="http://127.0.0.1:9/api")
os.environ.pop("PORTAL_WORKER", None)
sys.path[:0] = [PORTAL]

import jobs  # noqa: E402
import store  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


class Slow(http.server.BaseHTTPRequestHandler):
    """Every address answers 200 after 0.2 seconds, so that a job lasts long enough to be interrupted."""

    def _answer(self):
        time.sleep(0.2)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._answer()

    def do_GET(self):
        self._answer()

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
LOGS = tempfile.mkdtemp()


def start_worker(label):
    log = open(os.path.join(LOGS, f"worker-{label}.log"), "w+")
    proc = subprocess.Popen([sys.executable, "worker.py"], cwd=PORTAL, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PORTAL_WORKER": "external"})
    proc.log = log
    return proc


def log_of(proc):
    proc.log.flush()
    proc.log.seek(0)
    return proc.log.read()


def queue(n, tag):
    urls = [{"url": f"{BASE}/{tag}/{i}", "records": []} for i in range(n)]
    return jobs.create("linkcheck", "maria", "queued", n, scope="list", urls=urls)


def wait(condition, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def job(token):
    return store.col("jobs").find_one({"_id": token})


store.col("jobs").delete_many({})
store.col("workers").delete_many({})
workers = [start_worker("a"), start_worker("b")]
try:
    check("two worker processes start and announce themselves",
          wait(lambda: jobs.workers_alive() == 2, 60), list(store.col("workers").find()))

    # ---------------------------------------------------------------- a shared queue
    tokens = [queue(8, f"share{n}") for n in range(6)]
    finished = wait(lambda: store.col("jobs").count_documents({"_id": {"$in": tokens}, "state": "finished"}) == 6, 90)
    docs = [job(t) for t in tokens]
    check("six queued jobs all finish", finished, [(d["state"], d["done"]) for d in docs])
    check("each job was taken once (two workers never take the same job)", all(d["attempts"] == 1 for d in docs),
          [d["attempts"] for d in docs])
    started = [log_of(w).count("started, attempt") for w in workers]
    check("both workers took jobs from the shared queue", all(started) and sum(started) == 6, started)

    # ---------------------------------------------------------------- SIGTERM: hand back at once
    token = queue(60, "term")
    check("a long job is claimed", wait(lambda: (job(token) or {}).get("state") == "running", 30), job(token))
    owner_name = job(token)["worker"]
    owner = next(w for w in workers if f":{w.pid}:" in owner_name)
    other = next(w for w in workers if w is not owner)
    wait(lambda: job(token)["done"] >= 8, 30)
    owner.send_signal(signal.SIGTERM)
    try:
        code = owner.wait(20)
    except subprocess.TimeoutExpired:
        code = None
    check("SIGTERM: the worker stops within seconds, exit status 0", code == 0, (code, log_of(owner)[-600:]))
    check("SIGTERM: it said it handed the job back", "handed back to the queue" in log_of(owner), log_of(owner)[-600:])
    check("SIGTERM: its announcement is withdrawn", store.col("workers").count_documents({"_id": owner_name}) == 0)
    check("SIGTERM: the other worker finishes the job",
          wait(lambda: job(token)["state"] == "finished", 60) and job(token)["attempts"] == 2 and job(token)["done"] == 60,
          job(token))

    # ---------------------------------------------------------------- SIGKILL: continued after the heartbeat
    token = queue(60, "kill")
    check("SIGKILL: the remaining worker claims the next job",
          wait(lambda: (job(token) or {}).get("state") == "running", 30), job(token))
    wait(lambda: job(token)["done"] >= 8, 30)
    other.kill()
    other.wait(10)
    time.sleep(1)
    doc = job(token)
    check("SIGKILL: the job stays running, with its progress", doc["state"] == "running" and doc["done"] >= 8, doc)
    # instead of waiting two minutes, the heartbeat is made old
    store.col("jobs").update_one({"_id": token},
                                 {"$set": {"heartbeat": store.now() - timedelta(seconds=jobs.STALE_SECONDS + 1)}})
    third = start_worker("c")
    workers.append(third)
    check("SIGKILL: a new worker gives the silent job back to the queue and finishes it",
          wait(lambda: job(token)["state"] == "finished", 90) and job(token)["attempts"] == 2, job(token))
    check("SIGKILL: the new worker logged the job going back to the queue",
          "went back to the queue" in log_of(third), log_of(third)[-600:])
finally:
    for w in workers:
        if w.poll() is None:
            w.terminate()
            try:
                w.wait(20)
            except subprocess.TimeoutExpired:
                w.kill()
    store.col("jobs").delete_many({})
    store.col("workers").delete_many({})

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
