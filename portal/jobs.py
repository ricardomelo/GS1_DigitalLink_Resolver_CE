"""
Background jobs of the portal: spreadsheet imports and link checks, kept as documents of the "jobs"
collection of the portal's database and run by a worker (worker.py), so that no job depends on the memory of
the web process that accepted it (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.3).

States:
  prepared   an import preview waiting for *Apply* (expires PREPARED_SECONDS after the preview)
  queued     waiting for a worker (a link check starts here; an import gets here on *Apply*)
  running    claimed by one worker, which renews "heartbeat" every HEARTBEAT_SECONDS
  finished   done; the result stays for FINISHED_SECONDS
  failed     stopped by an unexpected error, or interrupted more than MAX_ATTEMPTS times

A running job whose heartbeat is older than STALE_SECONDS belongs to a worker that died: it goes back to
"queued" and the next worker continues it from "done". Every write a worker makes is conditional on the job
still being its own, so a worker that was only slow, not dead, finds out (JobLost) and lets go.

Workers announce themselves in the "workers" collection ({_id: name, seen, mode, job}); the health check and
the browser use it to tell "waiting in the queue" from "no worker is running".

Document of a job:
  {_id: token, type: "import" | "linkcheck", user, state, created, queuedAt, startedAt, finishedAt,
   heartbeat, worker, attempts, done, total, expiresAt, error, ...the fields of its type}
  import:    plan, keyRecords, results (one per record written, in plan order: len(results) == done)
  linkcheck: scope ("all" | "list"), urls ([{url, records: [record keys]}]), problems,
             records ([{record, problems}], scope "all")
"""
import logging
import os
import socket
import uuid
from datetime import timedelta

from pymongo import ReturnDocument

import store

log = logging.getLogger("portal.jobs")

PREPARED_SECONDS = 30 * 60           # an import preview waits this long for *Apply*
FINISHED_SECONDS = 30 * 60           # a finished or failed job stays readable this long
UNFINISHED_SECONDS = 24 * 60 * 60    # safety net: a job that never finishes is dropped after a day
HEARTBEAT_SECONDS = 10               # a working worker renews its job's heartbeat at least this often
STALE_SECONDS = 120                  # a running job silent for longer goes back to the queue
MAX_ATTEMPTS = 3                     # claims of one job before it is marked failed (a job that kills workers)
WORKER_ALIVE_SECONDS = 30            # a worker seen within this time counts as running
STALLED_SECONDS = 15                 # a job queued this long with no worker running is shown as stalled

TYPES = ("import", "linkcheck")
STATES = ("prepared", "queued", "running", "finished", "failed")


class JobLost(Exception):
    """The job is no longer this worker's: it was given back to the queue (or expired) while it worked."""


class Interrupted(Exception):
    """The worker is stopping; the job goes back to the queue and continues elsewhere."""


def _col():
    return store.col("jobs")


def _later(seconds: float):
    return store.now() + timedelta(seconds=seconds)


# --------------------------------------------------------------------------- web process side
def create(job_type: str, user: str, state: str, total: int, **fields) -> str:
    """A new job; returns its token. state is "prepared" (an import preview) or "queued"."""
    assert job_type in TYPES and state in ("prepared", "queued")
    token = uuid.uuid4().hex
    now = store.now()
    doc = {"_id": token, "type": job_type, "user": user, "state": state, "created": now, "attempts": 0,
           "done": 0, "total": total,
           "expiresAt": now + timedelta(seconds=PREPARED_SECONDS if state == "prepared" else UNFINISHED_SECONDS),
           **fields}
    if state == "queued":
        doc["queuedAt"] = now
    _col().insert_one(doc)
    return token


def get(token: str, user: str, job_type: str) -> dict | None:
    """The user's job of that type, or None (unknown, someone else's or expired: MongoDB removes expired
    documents only about once a minute, so the date is checked here too)."""
    if not isinstance(token, str) or not token:
        return None
    return _col().find_one({"_id": token, "user": user, "type": job_type, "expiresAt": {"$gt": store.now()}})


def queue_prepared(token: str, user: str, **changes) -> dict | None:
    """prepared → queued, once: None when the job is not (or no longer) a prepared job of this user."""
    now = store.now()
    return _col().find_one_and_update(
        {"_id": token, "user": user, "state": "prepared", "expiresAt": {"$gt": now}},
        {"$set": {"state": "queued", "queuedAt": now, "expiresAt": now + timedelta(seconds=UNFINISHED_SECONDS),
                  **changes}},
        return_document=ReturnDocument.AFTER)


def workers_alive() -> int:
    """How many workers were seen within WORKER_ALIVE_SECONDS."""
    since = store.now() - timedelta(seconds=WORKER_ALIVE_SECONDS)
    return store.col("workers").count_documents({"seen": {"$gt": since}})


def status(job: dict) -> dict:
    """The part of a job every status call returns: state, progress and whether it is stuck in the queue
    because no worker is running."""
    out = {"state": job["state"], "done": job.get("done", 0), "total": job.get("total", 0)}
    if job["state"] == "queued":
        waited = (store.now() - job.get("queuedAt", job["created"])).total_seconds()
        out["stalled"] = waited > STALLED_SECONDS and workers_alive() == 0
    if job["state"] == "failed":
        out["error"] = job.get("error") or "job.failed"
    return out


# --------------------------------------------------------------------------- worker side
def worker_name(mode: str) -> str:
    """host:pid, plus the mode; the host is the container's name or id in Docker."""
    return f"{socket.gethostname()}:{os.getpid()}:{mode}"


def announce(name: str, mode: str, job: str | None = None) -> None:
    """Records that the worker is alive (and which job it is working on)."""
    store.col("workers").update_one({"_id": name}, {"$set": {"seen": store.now(), "mode": mode, "job": job}},
                                    upsert=True)


def withdraw(name: str) -> None:
    """Removes the worker's announcement (clean stop)."""
    store.col("workers").delete_one({"_id": name})


def requeue_stale() -> int:
    """Gives running jobs whose worker went silent back to the queue (or fails them after MAX_ATTEMPTS).
    Returns how many jobs were given back."""
    stale = store.now() - timedelta(seconds=STALE_SECONDS)
    jobs = _col()
    failed = jobs.update_many({"state": "running", "heartbeat": {"$lt": stale}, "attempts": {"$gte": MAX_ATTEMPTS}},
                              {"$set": {"state": "failed", "error": "job.interrupted", "finishedAt": store.now(),
                                        "expiresAt": _later(FINISHED_SECONDS)},
                               "$unset": {"worker": ""}})
    if failed.modified_count:
        log.warning("%d job(s) failed after %d interrupted attempts.", failed.modified_count, MAX_ATTEMPTS)
    back = jobs.update_many({"state": "running", "heartbeat": {"$lt": stale}},
                            {"$set": {"state": "queued", "queuedAt": store.now()}, "$unset": {"worker": ""}})
    if back.modified_count:
        log.warning("%d job(s) went back to the queue: their worker stopped answering.", back.modified_count)
    return back.modified_count


def claim(name: str) -> dict | None:
    """Takes the oldest queued job for this worker (atomically: two workers never take the same job)."""
    now = store.now()
    return _col().find_one_and_update(
        {"state": "queued"},
        {"$set": {"state": "running", "worker": name, "heartbeat": now, "startedAt": now},
         "$inc": {"attempts": 1}},
        sort=[("created", 1)], return_document=ReturnDocument.AFTER)


class Reporter:
    """What a running job may write, always on the condition that the job is still this worker's."""

    def __init__(self, token: str, worker: str, stopping=lambda: False):
        self.token, self.worker, self.stopping = token, worker, stopping

    def _update(self, change: dict) -> None:
        change.setdefault("$set", {})["heartbeat"] = store.now()
        if not _col().update_one({"_id": self.token, "worker": self.worker, "state": "running"}, change).matched_count:
            raise JobLost(self.token)

    def beat(self) -> None:
        """Renews the heartbeat."""
        self._update({})

    def progress(self, done: int, total: int | None = None) -> None:
        """Progress of a job whose items are not stored one by one (a link check)."""
        self._update({"$set": {"done": done, **({"total": total} if total is not None else {})}})

    def record(self, done: int, result: dict) -> None:
        """One more item done, with its result (an import: the result of one record)."""
        self._update({"$set": {"done": done}, "$push": {"results": result}})

    def check_stop(self) -> None:
        """Raises Interrupted when the worker has been asked to stop."""
        if self.stopping():
            raise Interrupted(self.token)

    def finish(self, **fields) -> None:
        """running → finished, with the job's result fields."""
        now = store.now()
        self._update({"$set": {"state": "finished", "finishedAt": now, "expiresAt": now + timedelta(seconds=FINISHED_SECONDS),
                               **fields}, "$unset": {"worker": ""}})


def release(token: str, worker: str) -> None:
    """running → queued at once (the worker is stopping): the next worker continues from "done"."""
    _col().update_one({"_id": token, "worker": worker, "state": "running"},
                      {"$set": {"state": "queued", "queuedAt": store.now()}, "$unset": {"worker": ""}})


def fail(token: str, worker: str, code: str = "job.failed") -> None:
    """running → failed (an unexpected error, logged by the worker)."""
    now = store.now()
    _col().update_one({"_id": token, "worker": worker, "state": "running"},
                      {"$set": {"state": "failed", "error": code, "finishedAt": now,
                                "expiresAt": now + timedelta(seconds=FINISHED_SECONDS)},
                       "$unset": {"worker": ""}})
