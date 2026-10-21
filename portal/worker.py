"""
The portal's job worker: claims the jobs of the "jobs" collection one at a time and runs them with the
portal's own functions (app.JOB_RUNNERS), so that imports, link checks and e-mail messages do not depend on the
web process that accepted them (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.3; jobs.py has the
states).

PORTAL_WORKER chooses where it runs:
  external   (default) the portal-worker service runs "python worker.py"; the web process only creates jobs
             and reads their state
  embedded   a thread inside the portal process itself, for development, tests and a minimal installation
             without the portal-worker service

The loop: give the jobs of silent workers back to the queue, claim the oldest queued job, run it while a
thread renews its heartbeat, look again after a second when there is nothing to do. On SIGTERM (docker stop)
the worker finishes the record it is writing, gives the job back to the queue and stops; the next worker
continues from there. About once an hour, between jobs, it also runs the portal's housekeeping (app.HOUSEKEEPING:
the notices of API keys about to expire, the daily counts of resolver requests), and every PORTAL_MONITOR_MINUTES the
monitoring (app.MONITORING, Documentation/adr/0008-monitoring-and-alerts.md); each task is safe to run in several
workers at once.
"""
import logging
import os
import signal
import threading
import time

from pymongo.errors import PyMongoError

import jobs

log = logging.getLogger("portal.worker")

IDLE_SECONDS = 1             # look for work this often when there is none
ERROR_SECONDS = 5            # wait this long after a database error
ANNOUNCE_SECONDS = 10        # renew the worker's announcement this often
HOUSEKEEPING_SECONDS = 3600  # run the housekeeping tasks this often (the first time at start)

# Set by main() before it imports app, so that app does not also start an embedded worker in this process.
IN_WORKER_PROCESS = False

# Set by wake(): a job was just queued in this process, so an embedded worker need not wait for its next look.
_WAKE = threading.Event()


def wake() -> None:
    """Tells the workers of this process that a job was queued (the portal calls it; external workers in
    other containers find the job at their next look, within IDLE_SECONDS)."""
    _WAKE.set()


def mode() -> str:
    """PORTAL_WORKER: "external" (default) or "embedded"."""
    value = os.environ.get("PORTAL_WORKER", "").strip().lower() or "external"
    if value not in ("external", "embedded"):
        log.warning("PORTAL_WORKER=%r is not external or embedded; using external.", value)
        value = "external"
    return value


class Worker:
    """One worker: a loop that claims and runs jobs until stop() is called."""

    def __init__(self, runners: dict, worker_mode: str, housekeeping=(), monitoring=(), monitor_seconds: float = 0):
        self.runners = runners
        self.housekeeping = list(housekeeping)
        self._housekept = None
        self.monitoring = list(monitoring)
        self.monitor_seconds = monitor_seconds          # 0: no monitoring
        self._monitored = None
        self.mode = worker_mode
        self.name = jobs.worker_name(worker_mode)
        self._stop = threading.Event()
        self._announced = None

    def stop(self) -> None:
        """Asks the worker to stop after the item it is working on."""
        self._stop.set()
        _WAKE.set()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def _announce(self, job: str | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if force or self._announced is None or now - self._announced >= ANNOUNCE_SECONDS:
            jobs.announce(self.name, self.mode, job)
            self._announced = now

    def housekeep(self, force: bool = False) -> None:
        """Runs the housekeeping tasks when HOUSEKEEPING_SECONDS have passed (or at once with force), and the
        monitoring tasks every monitor_seconds; a failing task is logged and the others still run."""
        now = time.monotonic()
        if self.monitor_seconds and self.monitoring and (
                force or self._monitored is None or now - self._monitored >= self.monitor_seconds):
            self._monitored = now
            self._run_tasks(self.monitoring)
        if not force and self._housekept is not None and now - self._housekept < HOUSEKEEPING_SECONDS:
            return
        self._housekept = now
        self._run_tasks(self.housekeeping)

    @staticmethod
    def _run_tasks(tasks) -> None:
        for task in tasks:
            try:
                done = task()
                if done:
                    log.info("Housekeeping %s: %s.", getattr(task, "__name__", task), done)
            except Exception:                               # noqa: BLE001 — one task never stops the worker
                log.exception("Housekeeping %s failed.", getattr(task, "__name__", task))

    def run_once(self) -> bool:
        """Runs at most one job; returns whether there was one."""
        jobs.requeue_stale()
        job = jobs.claim(self.name)
        if job is None:
            return False
        self._run(job)
        return True

    def _run(self, job: dict) -> None:
        token = job["_id"]
        reporter = jobs.Reporter(token, self.name, self.stopping)
        runner = self.runners.get(job.get("type"))
        finished = threading.Event()

        def heartbeat():
            # A record written to the data entry API or a slow site can take longer than the heartbeat
            # interval, so the heartbeat has a thread of its own.
            while not finished.wait(jobs.HEARTBEAT_SECONDS):
                try:
                    reporter.beat()
                    self._announce(token, force=True)
                except jobs.JobLost:
                    return
                except PyMongoError as exc:
                    log.warning("Heartbeat of job %s not written: %s", token, exc)

        threading.Thread(target=heartbeat, name="job-heartbeat", daemon=True).start()
        self._announce(token, force=True)
        log.info("Job %s (%s of %s) started, attempt %d, from item %d of %d.", token, job.get("type"),
                 job.get("user"), job.get("attempts", 1), job.get("done", 0), job.get("total", 0))
        try:
            if runner is None:
                raise RuntimeError(f"no runner for jobs of type {job.get('type')!r}")
            runner(job, reporter)
            log.info("Job %s finished.", token)
        except jobs.Interrupted:
            jobs.release(token, self.name)
            log.info("Job %s handed back to the queue: the worker is stopping.", token)
        except jobs.Deferred:
            log.info("Job %s went back to the queue, to be tried again later.", token)
        except jobs.Cancelled:
            jobs.cancelled(token, self.name)
            log.info("Job %s stopped at its user's request.", token)
        except jobs.JobLost:
            log.warning("Job %s was given to another worker while this one worked on it; left to it.", token)
        except Exception:                                   # noqa: BLE001 — any error ends this job only
            log.exception("Job %s failed.", token)
            try:
                jobs.fail(token, self.name)
            except PyMongoError:
                pass
        finally:
            finished.set()
            try:
                self._announce(None, force=True)
            except PyMongoError:
                pass

    def loop(self) -> None:
        """Claims and runs jobs until stop()."""
        log.info("Worker %s started (PORTAL_WORKER=%s).", self.name, self.mode)
        while not self.stopping():
            try:
                self._announce()
                self.housekeep()
                if not self.run_once():
                    _WAKE.wait(IDLE_SECONDS)
                    _WAKE.clear()
            except PyMongoError as exc:
                log.warning("Portal database unavailable (%s); trying again in %d s.", exc, ERROR_SECONDS)
                self._stop.wait(ERROR_SECONDS)
        try:
            jobs.withdraw(self.name)
        except PyMongoError:
            pass
        log.info("Worker %s stopped.", self.name)


def start_embedded(runners: dict, housekeeping=(), monitoring=(), monitor_seconds: float = 0) -> Worker:
    """Starts a worker thread inside the calling process (PORTAL_WORKER=embedded)."""
    worker = Worker(runners, "embedded", housekeeping, monitoring, monitor_seconds)
    threading.Thread(target=worker.loop, name="portal-worker", daemon=True).start()
    return worker


def main() -> None:
    """The portal-worker service."""
    global IN_WORKER_PROCESS
    IN_WORKER_PROCESS = True
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import app                                      # the portal's start-up and its job runners

    worker = Worker(app.JOB_RUNNERS, "external", app.HOUSEKEEPING, app.MONITORING, app.MONITOR_SECONDS)

    def on_signal(signum, _frame):
        log.info("Signal %d received: stopping after the current item.", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    worker.loop()


if __name__ == "__main__":
    # Run as the importable module "worker", not as "__main__", so that app sees IN_WORKER_PROCESS.
    import worker as _worker
    _worker.main()
