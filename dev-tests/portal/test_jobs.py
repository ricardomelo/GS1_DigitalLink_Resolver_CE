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
import io
import http.server
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
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


# A workbook of a few KB that unpacks into more than the import's limit (ADR 0032): refused, no job prepared
_bomb = io.BytesIO()
with zipfile.ZipFile(_bomb, "w", zipfile.ZIP_DEFLATED) as _zip:
    _zip.writestr("xl/worksheets/sheet1.xml", b"a" * (33 * 1024 * 1024))
_before = store.col("jobs").count_documents({})
r = web.post("/portal/api/import/preview", json={"filename": "x.xlsx", "content": base64.b64encode(_bomb.getvalue()).decode(),
                                                 "labels": {}})
check("preview of an XLSX that unpacks too far: 422 import.unpackedTooBig, no job prepared",
      r.status_code == 422 and r.get_json().get("code") == "import.unpackedTooBig"
      and store.col("jobs").count_documents({}) == _before, (r.status_code, r.get_json()))

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

# ------------------------------------------------------------------ the account read again before each record (F-024)
# Documentation/adr/0041-queued-import-account.md: a queued import writes only while its account is still the one that
# prepared it, enabled, of an enabled organisation and an editor; its role, organisation and prefixes as they are now.
import tenants  # noqa: E402


def gtin_of(prefix, n):
    body = f"{prefix}{n:05d}"
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return "0" + body + str((10 - total % 10) % 10)


def sheet_of(prefix, first, count):
    return HEADER + "".join(f"01;{gtin_of(prefix, n)};;Item {n};gs1:pip;https://example.org/item/{n};en\n"
                            for n in range(first, first + count))


def signed_in(name, password="a-long-test-password"):
    c = portal.app.test_client()
    r = c.post("/portal/api/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.get_json()
    return c


def applied(c, text):
    p = c.post("/portal/api/import/preview", json={"filename": "x.csv", "labels": {},
                                                   "content": base64.b64encode(text.encode()).decode()}).get_json()
    r = c.post("/portal/api/import/apply", json={"token": p["token"]})
    assert r.status_code == 202, r.get_json()
    return p["token"]


def written(prefix, first, count):
    return [f"01_{gtin_of(prefix, n)}" in mock_data_entry.DB for n in range(first, first + count)]


def refusals():
    return list(store.col("journal").find({"action": "import-refused"}).sort("at", 1))


def refused_as(token, done):
    doc = job(token)
    return doc["state"] == "failed" and doc["error"] == "import.accountChanged" and doc["done"] == done


users.create("edda", "a-long-test-password", "editor", must_change=False)
edda = signed_in("edda")
token = applied(edda, sheet_of("9506001", 1, 3))
doc = job(token)
check("F-024: the job keeps the organisation and creation date of the account that prepared it",
      doc.get("tenant", "absent") is None and doc.get("accountCreated") == users.get("edda")["created"], doc)

users.update("edda", role="reader")
w.run_once()
check("F-024: an editor made a reader after Apply: the import stops before its first record (failed, accountChanged)",
      refused_as(token, 0) and written("9506001", 1, 3) == [False] * 3, job(token))
check("F-024: the refusal is in the journal under the user, in the operator's trail, with the reason and what was left",
      [(e["user"], e.get("tenant"), e["detail"]) for e in refusals()]
      == [("edda", None, "reason=role created=0 updated=0 failed=0 left=3")], refusals())
r = edda.get(f"/portal/api/import/status?token={token}")
check("F-024: as a reader the user no longer reads the import (access.role)", r.status_code == 403, r.get_json())
users.update("edda", role="editor")
status = edda.get(f"/portal/api/import/status?token={token}").get_json()
check("F-024: the status says failed with import.accountChanged and what was done",
      status["state"] == "failed" and status["error"] == "import.accountChanged" and status["done"] == 0, status)

# the role lowered while the import runs: the records written before stay, the next ones are not written
token = applied(edda, sheet_of("9506001", 10, 4))
calls = {"n": 0}


def demoting_store_record(*args):
    calls["n"] += 1
    result = real_store_record(*args)
    if calls["n"] == 2:
        users.update("edda", role="reader")
    return result


portal.store_record = demoting_store_record
w.run_once()
portal.store_record = real_store_record
check("F-024: a reader since the second record: two written and kept, the other two not written",
      refused_as(token, 2) and written("9506001", 10, 4) == [True, True, False, False]
      and [x["action"] for x in job(token)["results"]] == ["created", "created"], job(token))
check("F-024: the journal counts what was written and what was left",
      refusals()[-1]["detail"] == "reason=role created=2 updated=0 failed=0 left=2", refusals()[-1])
users.update("edda", role="editor")

token = applied(edda, sheet_of("9506001", 20, 2))
users.update("edda", disabled=True)
w.run_once()
check("F-024: a disabled account: nothing written", refused_as(token, 0) and written("9506001", 20, 2) == [False] * 2
      and refusals()[-1]["detail"].startswith("reason=disabled "), (job(token), refusals()[-1]))
users.update("edda", disabled=False)

edda = signed_in("edda")
token = applied(edda, sheet_of("9506001", 30, 2))
users.remove("edda")
w.run_once()
check("F-024: a removed account: nothing written (it used to run as an empty account, in the operator's scope)",
      refused_as(token, 0) and written("9506001", 30, 2) == [False] * 2
      and refusals()[-1]["detail"].startswith("reason=removed ") and refusals()[-1]["user"] == "edda",
      (job(token), refusals()[-1]))

users.create("edda", "a-long-test-password", "editor", must_change=False)
edda = signed_in("edda")
token = applied(edda, sheet_of("9506001", 40, 2))
users.remove("edda")
time.sleep(1.1)                                 # creation dates are kept to the second
users.create("edda", "a-long-test-password", "admin", must_change=False)
w.run_once()
check("F-024: an account of the same name made after the preview is another account: nothing written",
      refused_as(token, 0) and written("9506001", 40, 2) == [False] * 2
      and refusals()[-1]["detail"].startswith("reason=replaced "), (job(token), refusals()[-1]))

# an organisation's user
acme = tenants.create("Acme jobs", ["9507001"], "maria")
users.create("tina", "a-long-test-password", "editor", tenant=acme["id"], must_change=False)
tina = signed_in("tina")
token = applied(tina, sheet_of("9507001", 1, 2))
check("F-024: an organisation's import keeps its organisation", job(token).get("tenant") == acme["id"], job(token))
tenants.update(acme["id"], disabled=True)
w.run_once()
check("F-024: the organisation disabled after Apply: nothing written, journalled in the organisation's own trail",
      refused_as(token, 0) and written("9507001", 1, 2) == [False] * 2
      and refusals()[-1]["detail"].startswith("reason=organisation ") and refusals()[-1].get("tenant") == acme["id"],
      (job(token), refusals()[-1]))
tenants.update(acme["id"], disabled=False)
tina = signed_in("tina")
token = applied(tina, sheet_of("9507001", 10, 2))
users.remove("tina")
w.run_once()
check("F-024: an organisation's account removed: nothing written; the refusal stays in the organisation's trail",
      refused_as(token, 0) and written("9507001", 10, 2) == [False] * 2
      and refusals()[-1]["detail"].startswith("reason=removed ") and refusals()[-1].get("tenant") == acme["id"],
      (job(token), refusals()[-1]))

# prefixes read again before each record, not once when the worker took the job
users.create("pia", "a-long-test-password", "editor", prefixes=["9506002", "9506003"], must_change=False)
pia = signed_in("pia")
token = applied(pia, sheet_of("9506002", 1, 4))
calls = {"n": 0}


def narrowing_store_record(*args):
    calls["n"] += 1
    result = real_store_record(*args)
    if calls["n"] == 2:
        users.update("pia", prefixes=["9506003"])
    return result


portal.store_record = narrowing_store_record
w.run_once()
portal.store_record = real_store_record
status = pia.get(f"/portal/api/import/status?token={token}").get_json()
check("F-024: a prefix taken from the user during the import: the next records fail one by one (access.prefix)",
      status["state"] == "finished" and [x["action"] for x in status["results"]] == ["created", "created", "failed", "failed"]
      and {x.get("code") for x in status["results"][2:]} == {"access.prefix"}
      and written("9506002", 1, 4) == [True, True, False, False], status)

# a job queued before the job kept its account's organisation and date still runs
users.update("pia", prefixes=["9506002", "9506003"])
token = applied(pia, sheet_of("9506003", 1, 2))
store.col("jobs").update_one({"_id": token}, {"$unset": {"tenant": "", "accountCreated": ""}})
w.run_once()
check("F-024: a job queued before this change (without the account's organisation and date) still runs",
      job(token)["state"] == "finished" and written("9506003", 1, 2) == [True, True], job(token))
before = len(refusals())
token = applied(pia, sheet_of("9506003", 10, 2))
store.col("jobs").update_one({"_id": token}, {"$unset": {"tenant": "", "accountCreated": ""}})
users.update("pia", role="reader")
w.run_once()
check("F-024: ... and is refused like the others when its account may no longer write",
      refused_as(token, 0) and len(refusals()) == before + 1, job(token))
users.update("pia", role="editor")

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
# ADR 0029: one link check queued or running per organisation
r2 = other.post("/portal/api/links/jobs", json={"urls": [BASE + "/ok/busy"]})
check("a second link check of the same organisation (another user) is refused while one is queued: linkcheck.busy",
      r2.status_code == 422 and r2.get_json().get("code") == "linkcheck.busy"
      and store.col("jobs").count_documents({"type": "linkcheck"}) == 1, (r2.status_code, r2.get_json()))
store.col("jobs").insert_one({"_id": "lc-other", "type": "linkcheck", "user": "x", "state": "running",
                              "tenant": "t-other", "created": store.now()})
check("jobs.active(): a running check counts; another organisation's check does not block this one",
      (jobs.active("linkcheck", tenant="t-other") or {}).get("_id") == "lc-other"
      and (jobs.active("linkcheck", tenant=None) or {}).get("_id") == token
      and jobs.active("linkcheck", tenant="t-third") is None and jobs.active("import", tenant=None) is None)
store.col("jobs").delete_one({"_id": "lc-other"})
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

# the daily budget of addresses per organisation (ADR 0060): a check that does not fit is refused before it is queued
used = linkcheck.used_today(None)
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = str(used + 3)
queued = store.col("jobs").count_documents({"type": "linkcheck"})
r = web.post("/portal/api/links/jobs", json={"urls": [f"{BASE}/ok/b{n}" for n in range(5)]})
check("over the day's budget: a link check refused (linkcheck.budget, with the limit and what is left), not queued",
      r.status_code == 422 and r.get_json().get("code") == "linkcheck.budget"
      and r.get_json().get("params") == {"max": used + 3, "left": 3}
      and store.col("jobs").count_documents({"type": "linkcheck"}) == queued, (r.status_code, r.get_json()))
r = web.post("/portal/api/links/jobs", json={"urls": [f"{BASE}/ok/b{n}" for n in range(3)]})
w.run_once()
check("…what is left can still be checked", r.status_code == 202 and linkcheck.used_today(None) == used + 3,
      (r.status_code, linkcheck.used_today(None)))
r = web.post("/portal/api/links/check", json={"urls": [BASE + "/ok/b9"]})
check("…then a record's own check is refused too", r.status_code == 422 and r.get_json().get("code") == "linkcheck.budget"
      and r.get_json()["params"]["left"] == 0, r.get_json())
os.environ["PORTAL_LINKCHECK_DAILY_LIMIT"] = str(used + 10)
r = web.post("/portal/api/links/check", json={"urls": [BASE + "/ok/b9", BASE + "/ok/b9", BASE + "/missing/b9"]})
check("…a record's own check counts each address once", r.status_code == 200 and linkcheck.used_today(None) == used + 5,
      (r.status_code, linkcheck.used_today(None)))
os.environ.pop("PORTAL_LINKCHECK_DAILY_LIMIT", None)

# ------------------------------------------------------------------ stopping a job (its user's request)
clear()
q = jobs.create("linkcheck", "maria", "queued", 3, scope="list", urls=[])
check("cancel: another user's job, another type or an unknown token: None, nothing changed",
      jobs.cancel(q, "joao", "linkcheck") is None and jobs.cancel(q, "maria", "import") is None
      and jobs.cancel("nope", "maria", "linkcheck") is None and job(q)["state"] == "queued")
doc = jobs.cancel(q, "maria", "linkcheck")
check("cancel: a queued job is cancelled at once, kept 30 minutes",
      doc["state"] == "cancelled" and job(q)["state"] == "cancelled"
      and abs((job(q)["expiresAt"] - job(q)["finishedAt"]).total_seconds() - jobs.FINISHED_SECONDS) < 1, doc)
check("cancel: a cancelled job is never claimed", jobs.claim("w1") is None)
check("status: a cancelled job reports its state", jobs.status(job(q))["state"] == "cancelled")

r = jobs.create("import", "maria", "queued", 3, plan=[], results=[])
jobs.claim("w1")
doc = jobs.cancel(r, "maria", "import")
check("cancel: a running job is marked, still running, and its status says it is stopping",
      doc["state"] == "running" and doc["cancelRequested"] is True and jobs.status(doc).get("cancelling") is True, doc)
rep = jobs.Reporter(r, "w1")
rep.beat()
check("cancel: the heartbeat goes on (the stop is left to the job's own writes)", job(r)["state"] == "running")
try:
    rep.record(1, {"n": 1})
    check("cancel: the next record raises Cancelled", False)
except jobs.Cancelled:
    check("cancel: the next record raises Cancelled, after storing its result",
          job(r)["done"] == 1 and job(r)["results"] == [{"n": 1}])
jobs.cancelled(r, "w1")
doc = job(r)
check("cancelled(): running → cancelled, worker released", doc["state"] == "cancelled" and "worker" not in doc, doc)
check("cancel: a job that ended is left as it was", jobs.cancel(r, "maria", "import")["state"] == "cancelled")

f = jobs.create("linkcheck", "maria", "queued", 1, scope="list", urls=[])
jobs.claim("w1")
jobs.cancel(f, "maria", "linkcheck")
jobs.Reporter(f, "w1").finish(problems=[])
check("cancel: asked as the job finishes, finish() still finishes it", job(f)["state"] == "finished")
check("cancel: a finished job is left finished", jobs.cancel(f, "maria", "linkcheck")["state"] == "finished")

st = jobs.create("linkcheck", "maria", "queued", 1, scope="list", urls=[])
jobs.claim("w1")
jobs.cancel(st, "maria", "linkcheck")
age(st, "heartbeat", jobs.STALE_SECONDS + 1)
jobs.requeue_stale()
check("cancel: a job its user stopped, whose worker went silent, is cancelled, not queued again",
      job(st)["state"] == "cancelled", job(st))
rl = jobs.create("linkcheck", "maria", "queued", 1, scope="list", urls=[])
jobs.claim("w1")
jobs.cancel(rl, "maria", "linkcheck")
jobs.release(rl, "w1")
check("cancel: a stopping worker hands back a job its user stopped as cancelled", job(rl)["state"] == "cancelled", job(rl))
rl2 = jobs.create("linkcheck", "maria", "queued", 1, scope="list", urls=[])
jobs.claim("w1")
jobs.release(rl2, "w1")
check("release: a job nobody stopped goes back to the queue as before", job(rl2)["state"] == "queued", job(rl2))

# the worker loop: stopped after the item in hand, the worker carries on with the next job
clear()
seen.clear()
store.col("jobs").insert_one({"_id": "j-cancel", "type": "import", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 20, "expiresAt": store.now() + timedelta(hours=1)})
wc = worker.Worker({"import": slow}, "external")          # the test's slow runner, as an import
threading.Timer(0.4, lambda: jobs.cancel("j-cancel", "maria", "import")).start()
wc.run_once()
doc = job("j-cancel")
check("worker: a job its user stops ends cancelled, with the items done kept",
      doc["state"] == "cancelled" and 0 < doc["done"] < 20 and len(doc["results"]) == doc["done"]
      and "worker" not in doc, doc)
store.col("jobs").insert_one({"_id": "j-after", "type": "import", "user": "maria", "state": "queued", "created": store.now(),
                              "attempts": 0, "done": 0, "total": 2, "expiresAt": store.now() + timedelta(hours=1)})
wc.run_once()
check("worker: carries on with the next job", job("j-after")["state"] == "finished")

# through the API: an import
clear()
mock_data_entry.DB.clear()
p = preview(sheet(600, 4))
web.post("/portal/api/import/apply", json={"token": p["token"]})
check("import cancel: another user's request is refused (import.expired), the job stays queued",
      other.post("/portal/api/import/cancel", json={"token": p["token"]}).get_json().get("code") == "import.expired"
      and job(p["token"])["state"] == "queued")
check("import cancel: no token, an unknown one: import.expired",
      web.post("/portal/api/import/cancel", json={}).get_json().get("code") == "import.expired"
      and web.post("/portal/api/import/cancel", json={"token": "nope"}).get_json().get("code") == "import.expired")
status = web.post("/portal/api/import/cancel", json={"token": p["token"]}).get_json()
w.run_once()
check("import cancel while queued: cancelled at once, nothing written",
      status["state"] == "cancelled" and status["results"] == [] and job(p["token"])["state"] == "cancelled"
      and not any(f"01_{gtin(n)}" in mock_data_entry.DB for n in range(600, 604)), status)

p = preview(sheet(610, 6))
web.post("/portal/api/import/apply", json={"token": p["token"]})
calls = {"n": 0}


def stopping_store_record(*args):
    calls["n"] += 1
    if calls["n"] == 2:
        answer = web.post("/portal/api/import/cancel", json={"token": p["token"]}).get_json()
        calls["answer"] = answer
    return real_store_record(*args)


portal.store_record = stopping_store_record
w.run_once()
portal.store_record = real_store_record
status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
check("import cancel while running: the answer says it is stopping",
      calls["answer"]["state"] == "running" and calls["answer"]["cancelling"] is True, calls.get("answer"))
check("import cancel while running: stops after the record in hand; the two written are kept and listed",
      status["state"] == "cancelled" and [x["action"] for x in status["results"]] == ["created"] * 2
      and status["total"] == 6 and f"01_{gtin(611)}" in mock_data_entry.DB and f"01_{gtin(612)}" not in mock_data_entry.DB,
      status)
events = list(store.col("journal").find({"action": "import"}).sort("at", -1).limit(1))
check("import cancel: the journal has the counts and the records not imported",
      events[0]["detail"] == "created=2 updated=0 failed=0 cancelled=4", events)

p = preview(sheet(620, 3))
web.post("/portal/api/import/apply", json={"token": p["token"]})
calls = {"n": 0}


def late_store_record(*args):
    calls["n"] += 1
    if calls["n"] == 3:
        web.post("/portal/api/import/cancel", json={"token": p["token"]})
    return real_store_record(*args)


portal.store_record = late_store_record
w.run_once()
portal.store_record = real_store_record
status = web.get(f"/portal/api/import/status?token={p['token']}").get_json()
check("import cancel during the last record: the import simply finishes",
      status["state"] == "finished" and len(status["results"]) == 3, status)

# through the API: a link check
linkcheck.clear_cache()
r = web.post("/portal/api/links/jobs", json={"urls": [f"{BASE}/slow/c{n}" for n in range(200)]})
token = r.get_json()["token"]
check("link cancel: another user's request is refused (linkcheck.expired)",
      other.post(f"/portal/api/links/jobs/{token}/cancel", json={}).get_json().get("code") == "linkcheck.expired")
HITS["count"] = 0
threading.Timer(0.5, lambda: web.post(f"/portal/api/links/jobs/{token}/cancel", json={})).start()
started = time.monotonic()
w.run_once()
took, hits = time.monotonic() - started, HITS["count"]
status = web.get(f"/portal/api/links/jobs/{token}").get_json()
check("link cancel while running: cancelled, no result", status["state"] == "cancelled" and "problems" not in status,
      status)
check("link cancel: seen at the next progress write; the addresses not started are not requested (not all 200)",
      hits < 200 and took < 5, (hits, took))
r = web.post("/portal/api/links/jobs", json={"urls": [BASE + "/ok/q"]})
status = web.post(f"/portal/api/links/jobs/{r.get_json()['token']}/cancel", json={}).get_json()
check("link cancel while queued: cancelled at once", status["state"] == "cancelled", status)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
