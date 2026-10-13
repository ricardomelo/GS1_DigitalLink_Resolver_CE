"""
Background jobs (portal/jobs.py, portal/worker.py; Documentation/adr/0001-portal-state-in-mongodb.md,
section 3.3): the states of a job, claiming, heartbeat, a worker that dies or stops, the worker's
announcement and the health check, and spreadsheet imports and link checks through the portal's API with a
worker driven by the test (PORTAL_WORKER=external, so the portal starts no worker of its own).

Runs against mongomock unless PORTAL_DB_URI names a real MongoDB (test_store_mongodb.py does that, and also
runs worker.py as real processes).

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_jobs.py
"""
import base64
import http.server
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3397
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_LINKCHECK_ALLOW_PRIVATE="1")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")      # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_jobs_{os.getpid()}")
os.environ.pop("PORTAL_WORKER", None)                       # external: the test drives the worker itself
sys.path[:0] = [HERE, PORTAL]
logging.basicConfig(level=logging.WARNING)

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.set_password("maria", "a-long-test-password")
import app as portal  # noqa: E402
import jobs  # noqa: E402
import linkcheck  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def job(token):
    return store.col("jobs").find_one({"_id": token})


def age(token, field, seconds):
    """Moves a date of a job into the past (instead of waiting)."""
    store.col("jobs").update_one({"_id": token}, {"$set": {field: store.now() - timedelta(seconds=seconds)}})


def clear():
    store.col("jobs").delete_many({})
    store.col("workers").delete_many({})


class Crash(BaseException):
    """A worker dying half way (not an Exception: the worker's own error handling does not see it)."""


# ------------------------------------------------------------------ states, claim, expiry
clear()
check("worker mode: external by default", worker.mode() == "external" and portal.EMBEDDED_WORKER is None)
for value, expected in (("embedded", "embedded"), (" Embedded ", "embedded"), ("threads", "external")):
    os.environ["PORTAL_WORKER"] = value
    check(f"worker mode: PORTAL_WORKER={value!r} → {expected}", worker.mode() == expected)
os.environ.pop("PORTAL_WORKER")

prepared = jobs.create("import", "maria", "prepared", 2, plan=[], keyRecords=[], results=[])
doc = job(prepared)
check("prepared job: state, no queue time, expires 30 minutes after the preview",
      doc["state"] == "prepared" and "queuedAt" not in doc
      and abs((doc["expiresAt"] - doc["created"]).total_seconds() - jobs.PREPARED_SECONDS) < 1, doc)
check("prepared job: found by its user and type only",
      jobs.get(prepared, "maria", "import") and not jobs.get(prepared, "joao", "import")
      and not jobs.get(prepared, "maria", "linkcheck") and not jobs.get("", "maria", "import"))
check("prepared job: never claimed", jobs.claim("w1") is None)
age(prepared, "expiresAt", 1)
check("expired job: not found (its date is checked; MongoDB's TTL monitor runs only once a minute)",
      jobs.get(prepared, "maria", "import") is None)
check("expired job: cannot be queued", jobs.queue_prepared(prepared, "maria") is None)

prepared = jobs.create("import", "maria", "prepared", 0, plan=[], results=[])
check("queue_prepared: another user's job is refused", jobs.queue_prepared(prepared, "joao") is None)
queued = jobs.queue_prepared(prepared, "maria", total=5)
check("queue_prepared: prepared → queued, with the changes, expiry a day later",
      queued and queued["state"] == "queued" and queued["total"] == 5 and queued["queuedAt"]
      and (queued["expiresAt"] - queued["queuedAt"]).total_seconds() > 23 * 3600, queued)
check("queue_prepared: only once", jobs.queue_prepared(prepared, "maria") is None)

clear()
first = jobs.create("linkcheck", "maria", "queued", 0, scope="list", urls=[])
time.sleep(0.01)
second = jobs.create("linkcheck", "maria", "queued", 0, scope="list", urls=[])
a, b, c = jobs.claim("w1"), jobs.claim("w2"), jobs.claim("w3")
check("claim: the oldest queued job first", a and a["_id"] == first, a)
check("claim: two workers never take the same job; nothing left for a third",
      b and b["_id"] == second and c is None, (b, c))
check("claim: running, worker, heartbeat, first attempt",
      a["state"] == "running" and a["worker"] == "w1" and a["heartbeat"] and a["attempts"] == 1, a)

reporter = jobs.Reporter(first, "w1")
reporter.record(1, {"n": 1})
reporter.record(2, {"n": 2})
check("reporter: results stored in order, done counts them", job(first)["results"] == [{"n": 1}, {"n": 2}]
      and job(first)["done"] == 2)
try:
    jobs.Reporter(first, "w2").beat()
    check("reporter: another worker's write is refused", False)
except jobs.JobLost:
    check("reporter: another worker's write is refused", True)
reporter.finish(problems=[])
doc = job(first)
check("finish: finished, worker released, expires 30 minutes later",
      doc["state"] == "finished" and "worker" not in doc and doc["problems"] == []
      and abs((doc["expiresAt"] - doc["finishedAt"]).total_seconds() - jobs.FINISHED_SECONDS) < 1, doc)
try:
    reporter.beat()
    check("reporter: a finished job takes no more writes", False)
except jobs.JobLost:
    check("reporter: a finished job takes no more writes", True)

# ------------------------------------------------------------------ silent workers
age(second, "heartbeat", jobs.STALE_SECONDS - 30)
check("requeue: a worker silent for less than two minutes keeps its job",
      jobs.requeue_stale() == 0 and job(second)["state"] == "running")
age(second, "heartbeat", jobs.STALE_SECONDS + 1)
check("requeue: a worker silent for two minutes loses its job back to the queue",
      jobs.requeue_stale() == 1 and job(second)["state"] == "queued" and "worker" not in job(second), job(second))
try:
    jobs.Reporter(second, "w2").beat()
    check("requeue: the slow worker finds out (JobLost)", False)
except jobs.JobLost:
    check("requeue: the slow worker finds out (JobLost)", True)
for attempt in (2, 3):
    jobs.claim("w9")
    age(second, "heartbeat", jobs.STALE_SECONDS + 1)
    jobs.requeue_stale()
doc = job(second)
check(f"requeue: after {jobs.MAX_ATTEMPTS} interrupted attempts the job fails (a job that kills workers)",
      doc["state"] == "failed" and doc["error"] == "job.interrupted" and doc["attempts"] == 3, doc)
check("status: a failed job reports its error", jobs.status(doc)["error"] == "job.interrupted")

# ------------------------------------------------------------------ the worker's announcement and stalled jobs
clear()
check("no worker announced: none alive", jobs.workers_alive() == 0)
waiting = jobs.create("linkcheck", "maria", "queued", 3, scope="list", urls=[])
check("status: a job just queued is not stalled", jobs.status(job(waiting)) == {"state": "queued", "done": 0, "total": 3,
                                                                              "stalled": False})
age(waiting, "queuedAt", jobs.STALLED_SECONDS + 1)
check("status: queued for long with no worker → stalled", jobs.status(job(waiting))["stalled"] is True)
jobs.announce("w1", "external")
check("status: queued for long while a worker runs (busy elsewhere) → not stalled",
      jobs.status(job(waiting))["stalled"] is False and jobs.workers_alive() == 1)
store.col("workers").update_one({"_id": "w1"}, {"$set": {"seen": store.now() - timedelta(seconds=jobs.WORKER_ALIVE_SECONDS + 1)}})
check("a worker not seen for 30 seconds no longer counts", jobs.workers_alive() == 0)
jobs.announce("w1", "external")
jobs.withdraw("w1")
check("withdraw: a worker that stops removes its announcement", jobs.workers_alive() == 0)
check("workers collection: TTL index forgets old announcements",
      any(i.get("expireAfterSeconds") == store.WORKER_RECORD_SECONDS for i in store.col("workers").list_indexes()))
check("jobs collection: TTL index on expiresAt and an index on state and creation",
      any(i.get("expireAfterSeconds") == 0 and "expiresAt" in i["key"] for i in store.col("jobs").list_indexes())
      and any(list(i["key"]) == ["state", "created"] for i in store.col("jobs").list_indexes()))

web = portal.app.test_client()
health = web.get("/portal/healthz").get_json()
check("healthz: worker unavailable when no worker is running", health.get("worker") == "unavailable", health)
jobs.announce("w1", "external")
health = web.get("/portal/healthz").get_json()
check("healthz: worker ok when one announced itself", health.get("worker") == "ok" and health["portal"] == "ok", health)
jobs.withdraw("w1")

# ------------------------------------------------------------------ the worker loop with test runners
clear()
seen = []


def slow(job_doc, rep):
    for n in range(job_doc["done"], job_doc["total"]):
        rep.check_stop()
        time.sleep(0.15)
        rep.record(n + 1, {"n": n})
        seen.append(n)
    rep.finish()


def boom(job_doc, rep):
    raise ValueError("unexpected")


w = worker.Worker({"slow": slow, "boom": boom}, "external")
check("run_once: nothing to do", w.run_once() is False)
store.col("jobs").insert_one({"_id": "j-boom", "type": "boom", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 1, "expiresAt": store.now() + timedelta(hours=1)})
w.run_once()
check("an unexpected error fails that job only (job.failed), the worker carries on",
      job("j-boom")["state"] == "failed" and job("j-boom")["error"] == "job.failed")
store.col("jobs").insert_one({"_id": "j-odd", "type": "unknown", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 1, "expiresAt": store.now() + timedelta(hours=1)})
w.run_once()
check("a job of an unknown type fails", job("j-odd")["state"] == "failed")

jobs.HEARTBEAT_SECONDS, saved_heartbeat = 0.2, jobs.HEARTBEAT_SECONDS
store.col("jobs").insert_one({"_id": "j-slow", "type": "slow", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 6, "expiresAt": store.now() + timedelta(hours=1)})
w.run_once()
doc = job("j-slow")
check("a job runs to the end; heartbeat renewed while it works",
      doc["state"] == "finished" and doc["done"] == 6 and doc["heartbeat"] > doc["startedAt"], doc)

# stop while working: the item in hand is finished, the job goes back to the queue and continues elsewhere
seen.clear()
store.col("jobs").insert_one({"_id": "j-stop", "type": "slow", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 8, "expiresAt": store.now() + timedelta(hours=1)})
w2 = worker.Worker({"slow": slow}, "external")
loop = threading.Thread(target=w2.loop)
loop.start()
deadline = time.monotonic() + 10
while time.monotonic() < deadline and not seen:
    time.sleep(0.02)
w2.stop()
loop.join(10)
doc = job("j-stop")
check("stop: the loop ends after the item in hand", not loop.is_alive())
check("stop: the job goes back to the queue at once, with what was done kept",
      doc["state"] == "queued" and "worker" not in doc and 0 < doc["done"] < 8 and len(doc["results"]) == doc["done"], doc)
check("stop: the stopping worker withdrew its announcement", store.col("workers").count_documents({"_id": w2.name}) == 0)
done_before = doc["done"]
w.run_once()
doc = job("j-stop")
check("stop: another worker continues from there, each item done once",
      doc["state"] == "finished" and [r["n"] for r in doc["results"]] == list(range(8))
      and seen == list(range(8)) and doc["attempts"] == 2, (doc, seen, done_before))

# a job taken away while working: the worker lets go, without failing it
def stolen(job_doc, rep):
    store.col("jobs").update_one({"_id": job_doc["_id"]}, {"$set": {"state": "queued"}, "$unset": {"worker": ""}})
    rep.record(1, {})


w3 = worker.Worker({"stolen": stolen}, "external")
store.col("jobs").insert_one({"_id": "j-stolen", "type": "stolen", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 1, "expiresAt": store.now() + timedelta(hours=1)})
w3.run_once()
check("JobLost: the worker leaves the job to the queue instead of failing it", job("j-stolen")["state"] == "queued")
jobs.HEARTBEAT_SECONDS = saved_heartbeat

# embedded worker: a thread in the calling process
clear()
embedded = worker.start_embedded({"slow": slow})
store.col("jobs").insert_one({"_id": "j-emb", "type": "slow", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 2, "expiresAt": store.now() + timedelta(hours=1)})
deadline = time.monotonic() + 10
while time.monotonic() < deadline and job("j-emb")["state"] != "finished":
    time.sleep(0.05)
check("embedded worker: picks the job up within a second or two and announces itself as embedded",
      job("j-emb")["state"] == "finished" and store.col("workers").find_one({"_id": embedded.name})["mode"] == "embedded")
embedded.stop()
time.sleep(1.5)
check("embedded worker: stops on request", store.col("workers").count_documents({}) == 0)

# PORTAL_WORKER=embedded starts a worker in the portal, except inside the worker process itself
probe = ("import sys; sys.path[:0]=[{p!r}]; import users; import worker; worker.IN_WORKER_PROCESS={inside}; "
         "import app; print('started' if app.EMBEDDED_WORKER else 'none')")
env = {**os.environ, "PORTAL_WORKER": "embedded"}     # same database: the portal's user may use no other
outside = subprocess.run([sys.executable, "-c", probe.format(p=PORTAL, inside=False)], env=env, capture_output=True,
                         text=True, timeout=60)
inside = subprocess.run([sys.executable, "-c", probe.format(p=PORTAL, inside=True)], env=env, capture_output=True,
                        text=True, timeout=60)
check("PORTAL_WORKER=embedded: the portal starts its own worker thread", outside.stdout.strip() == "started",
      outside.stderr[-300:])
check("PORTAL_WORKER=embedded: but not a second one inside worker.py", inside.stdout.strip() == "none", inside.stderr[-300:])

# ------------------------------------------------------------------ imports through the API
clear()
web.post("/portal/api/login", json={"username": "maria", "password": "a-long-test-password"})
HEADER = "key;value;qualifiers;description;linkType;url;language\n"


def preview(text):
    return web.post("/portal/api/import/preview", json={"filename": "x.csv", "content": base64.b64encode(text.encode()).decode(),
                                                        "labels": {}}).get_json()


def sheet(first, count):
    return HEADER + "".join(f"01;{gtin(n)};;Item {n};gs1:pip;https://example.org/item/{n};en\n"
                            for n in range(first, first + count))


def gtin(n):
    body = f"9506000{n:05d}"
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return "0" + body + str((10 - total % 10) % 10)


p = preview(sheet(100, 5))
token = p["token"]
check("preview: the import becomes a prepared job of its user with the plan",
      job(token)["state"] == "prepared" and job(token)["type"] == "import" and len(job(token)["plan"]) == 5)
r = web.get(f"/portal/api/import/status?token={token}")
check("status of a preview not applied yet: expired (the browser only asks after Apply)",
      r.get_json().get("code") == "import.expired", r.get_json())
r = web.post("/portal/api/import/apply", json={"token": token})
check("apply: 202 with the total; the job waits in the queue", r.status_code == 202 and r.get_json()["total"] == 5
      and job(token)["state"] == "queued", r.get_json())
r = web.post("/portal/api/import/apply", json={"token": token})
check("apply again: refused (import.alreadyApplied)", r.get_json().get("code") == "import.alreadyApplied", r.get_json())
r = web.post("/portal/api/import/apply", json={"token": "nope"})
check("apply of an unknown token: import.expired", r.get_json().get("code") == "import.expired")
status = web.get(f"/portal/api/import/status?token={token}").get_json()
check("status while queued: state, progress, not stalled yet",
      status == {"state": "queued", "done": 0, "total": 5, "stalled": False, "results": []}, status)
age(token, "queuedAt", jobs.STALLED_SECONDS + 1)
check("status while queued with no worker for long: stalled",
      web.get(f"/portal/api/import/status?token={token}").get_json()["stalled"] is True)
w = worker.Worker(portal.JOB_RUNNERS, "external")
w.run_once()
status = web.get(f"/portal/api/import/status?token={token}").get_json()
check("the worker writes the records; status finished with every result",
      status["state"] == "finished" and [x["action"] for x in status["results"]] == ["created"] * 5
      and all(f"01_{gtin(n)}" in mock_data_entry.DB for n in range(100, 105)), status)
events = list(store.col("journal").find({"action": "import"}))
check("the import is in the journal under its user, with the counts",
      len(events) == 1 and events[0]["user"] == "maria" and events[0]["detail"] == "created=5 updated=0 failed=0", events)
other = portal.app.test_client()
users.set_password("joao", "another-long-password")
other.post("/portal/api/login", json={"username": "joao", "password": "another-long-password"})
check("another user cannot read the job", other.get(f"/portal/api/import/status?token={token}").get_json().get("code")
      == "import.expired")

# a worker dying in the middle: the next one continues from the first record not done
real_store_record = portal.store_record
calls = {"n": 0}


def dying_store_record(*args):
    calls["n"] += 1
    if calls["n"] == 4:
        raise Crash()
    return real_store_record(*args)


p = preview(sheet(200, 8))
web.post("/portal/api/import/apply", json={"token": p["token"]})
portal.store_record = dying_store_record
try:
    worker.Worker(portal.JOB_RUNNERS, "external").run_once()
    check("crash: the test's crash reached the test", False)
except Crash:
    pass
portal.store_record = real_store_record
doc = job(p["token"])
check("crash: the job is left running with the three records done", doc["state"] == "running" and doc["done"] == 3, doc)
age(p["token"], "heartbeat", jobs.STALE_SECONDS + 1)
w.run_once()
status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
check("crash: two minutes later another worker takes the job back and finishes it, every record created once",
      status["state"] == "finished" and [x["action"] for x in status["results"]] == ["created"] * 8
      and [x["value"] for x in status["results"]] == [gtin(n) for n in range(200, 208)], status)

# dying after writing a record but before noting it: that record is written again, safely
p = preview(sheet(300, 4))
web.post("/portal/api/import/apply", json={"token": p["token"]})
real_record = jobs.Reporter.record


def dying_record(self, done, result):
    if done == 2:
        raise Crash()
    return real_record(self, done, result)


jobs.Reporter.record = dying_record
try:
    w.run_once()
except Crash:
    pass
jobs.Reporter.record = real_record
age(p["token"], "heartbeat", jobs.STALE_SECONDS + 1)
w.run_once()
status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
entries = mock_data_entry.v3(f"01_{gtin(301)}")
check("crash after a write: the record is written again (updated) and stays one record with its link",
      status["state"] == "finished" and [x["action"] for x in status["results"]] == ["created", "updated", "created", "created"]
      and len(entries) == 1 and [l["href"] for l in entries[0]["links"]] == ["https://example.org/item/301"],
      (status, entries))

# a failed job: the browser gets the error, with what was done so far
p = preview(sheet(400, 3))
web.post("/portal/api/import/apply", json={"token": p["token"]})
portal.store_record = lambda *a: (_ for _ in ()).throw(RuntimeError("unexpected"))
w.run_once()
portal.store_record = real_store_record
status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
check("an unexpected error: status failed with job.failed", status["state"] == "failed" and status["error"] == "job.failed",
      status)

# ------------------------------------------------------------------ link checks through the API
HITS = {"count": 0}


class Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self):
        HITS["count"] += 1
        if self.path.startswith("/slow"):
            time.sleep(0.3)
        self.send_response(404 if self.path.startswith("/missing") else 200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._answer()

    def do_GET(self):
        self._answer()

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
clear()
linkcheck.clear_cache()
mock_data_entry.DB.clear()
for value, path in ((gtin(500), "/ok/1"), (gtin(501), "/missing/1")):
    web.post("/portal/api/record", json={"key": "01", "value": value, "description": "Item",
                                         "links": [{"linkType": "gs1:pip", "url": "https://example.org" + path,
                                                    "hreflang": ["en"], "title": "t"}]})
    # the portal accepts HTTPS targets only; the test server speaks plain HTTP on 127.0.0.1
    mock_data_entry.DB[f"01_{value}"]["entries"][0]["links"][0]["href"] = BASE + path
r = web.post("/portal/api/links/jobs", json={"scope": "all"})
token = r.get_json()["token"]
doc = job(token)
check("check every record: a queued linkcheck job, each address with its records",
      r.status_code == 202 and doc["state"] == "queued" and doc["scope"] == "all"
      and sorted((u["url"], u["records"][0]) for u in doc["urls"])
      == [(BASE + "/missing/1", f"/01/{gtin(501)}|"), (BASE + "/ok/1", f"/01/{gtin(500)}|")], doc)
status = web.get(f"/portal/api/links/jobs/{token}").get_json()
check("link job status while queued", status["state"] == "queued" and status["total"] == 2, status)
w.run_once()
status = web.get(f"/portal/api/links/jobs/{token}").get_json()
check("check every record: finished, the problem mapped to its record",
      status["state"] == "finished" and [x["url"] for x in status["problems"]] == [BASE + "/missing/1"]
      and list(status["records"]) == [f"/01/{gtin(501)}|"] and status["checkedAt"] and status["urls"] == 2, status)
last = web.get("/portal/api/links/last").get_json()
check("the last full check is kept for the record list", list(last["records"]) == [f"/01/{gtin(501)}|"], last)
check("another user cannot read the link job",
      other.get(f"/portal/api/links/jobs/{token}").get_json().get("code") == "linkcheck.expired")

r = web.post("/portal/api/links/jobs", json={"urls": [BASE + "/ok/2", BASE + "/missing/2", BASE + "/ok/2", ""]})
w.run_once()
status = web.get(f"/portal/api/links/jobs/{r.get_json()['token']}").get_json()
check("a list of addresses (import preview): each checked once, problems only",
      status["state"] == "finished" and status["total"] == 2 and [x["url"] for x in status["problems"]] == [BASE + "/missing/2"]
      and "records" not in status, status)

# a worker stopping in the middle of a long check: addresses not started yet are not requested
linkcheck.clear_cache()
r = web.post("/portal/api/links/jobs", json={"urls": [f"{BASE}/slow/{n}" for n in range(40)]})
token = r.get_json()["token"]
stopper = worker.Worker(portal.JOB_RUNNERS, "external")
HITS["count"] = 0
threading.Timer(0.5, stopper.stop).start()
started = time.monotonic()
stopper.run_once()
took, hits = time.monotonic() - started, HITS["count"]
doc = job(token)
check("stop during a link check: the job goes back to the queue", doc["state"] == "queued", doc)
check("stop during a link check: pending addresses are cancelled (not all 40 requested, done in seconds)",
      hits < 40 and took < 5, (hits, took))
w.run_once()
status = web.get(f"/portal/api/links/jobs/{token}").get_json()
check("the next worker checks the whole list again (the cache answers what was done) and finishes",
      status["state"] == "finished" and status["done"] == 40 and status["problems"] == [], status)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
