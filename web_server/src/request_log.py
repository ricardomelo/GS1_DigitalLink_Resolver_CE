"""
The log of resolver requests (Documentation/adr/0006-resolver-request-log.md).

Each resolution request (a GS1 Digital Link URI, a compressed one, an EPC binary string, a ?compress request) becomes
one event in the collection "requests" of the database "resolver_log": what was asked, what the resolver answered and
how long it took — never anything about the person who scanned (no client address in any form, no User-Agent, no
full referrer, no values of unit qualifiers or data attributes).

The routes of web_namespace note what they know in flask.g.resolution (note()); the after_request hook of the
application (record()) adds the status, the target's host, the time taken and the few headers kept, and puts the
event in a bounded queue in memory. A background thread of each server process writes the queue in batches, so the
answer never waits for the database; a full queue or a failing database drops events, counts them and says so in the
resolver's output at most once a minute.

Settings, read at every request (so a test can change them):
  RESOLVER_LOG_DAYS             days an event is kept (its expiresAt, a TTL index); 0 switches the log off; default 90
  RESOLVER_LOG_COUNTRY_HEADER   a header with a two-letter country code set by a proxy in front (default: none)
"""
import atexit
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from flask import Response, g, request

log = logging.getLogger(__name__)

DB_NAME = "resolver_log"
COLLECTION = "requests"
DEFAULT_DAYS = 90
QUEUE_SIZE = 10_000            # events waiting in one process
BATCH_SIZE = 500               # events written at once
FLUSH_SECONDS = 1.0            # the longest an event waits in the queue when the resolver is quiet
WARN_SECONDS = 60              # at most one warning a minute about lost events
UNIT_QUALIFIERS = {"21", "235"}        # they name a single unit: only the AI is kept
COMPANY_AFTER_FIRST_DIGIT = {"01", "8006", "00", "8003"}   # indicator, extension or filler digit before the prefix
MAX_VALUE = 100
MAX_PATH = 200

_AI = re.compile(r"\d{2,4}")
_LANGUAGE = re.compile(r"[a-z]{1,8}(-[a-z0-9]{1,8}){0,2}")
_COUNTRY = re.compile(r"[A-Za-z]{2}")
# Crawlers, link previews, monitors, command-line tools and HTTP libraries. Checked before the device patterns: many
# crawlers claim to be a phone. Native scanner apps (okhttp, Dalvik, CFNetwork) are phones, not automation.
_AUTOMATED = re.compile(
    r"bot\b|bot/|crawl|spider|slurp|facebookexternalhit|embedly|preview|monitor|uptime|pingdom|lighthouse|headless"
    r"|curl/|wget/|python|java/|go-http-client|libwww|httpclient|httpie|axios|node-fetch|undici|postman|insomnia"
    r"|apache-httpclient|scrapy|validator|checker", re.IGNORECASE)
_TABLET = re.compile(r"ipad|tablet|kindle|silk/|playbook|android(?!.*mobile)", re.IGNORECASE)
_NATIVE_APP = re.compile(r"dalvik|okhttp|cfnetwork", re.IGNORECASE)   # HTTP stacks of Android and iOS apps
_MOBILE = re.compile(r"mobi|iphone|ipod|android|windows phone|blackberry|opera mini", re.IGNORECASE)
_DESKTOP = re.compile(r"windows nt|macintosh|mac os x|x11|cros|linux", re.IGNORECASE)


def days() -> int:
    """RESOLVER_LOG_DAYS: days an event is kept; 0 (or a negative number) switches the log off."""
    raw = os.environ.get("RESOLVER_LOG_DAYS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_DAYS
    except ValueError:
        return DEFAULT_DAYS


def enabled() -> bool:
    return days() > 0


# ----------------------------------------------------------------------------------------------- what is kept
def device_class(user_agent: str | None) -> str:
    """mobile, tablet, desktop, automated or unknown (none, or not recognised); the User-Agent itself is not kept."""
    ua = (user_agent or "").strip()
    if not ua:
        return "unknown"
    if _AUTOMATED.search(ua):
        return "automated"
    if _NATIVE_APP.search(ua):
        return "mobile"
    if _TABLET.search(ua):
        return "tablet"
    if _MOBILE.search(ua):
        return "mobile"
    if _DESKTOP.search(ua):
        return "desktop"
    return "unknown"


def language(ranges: list[str]) -> str | None:
    """The most preferred language range, lower case ('pt-br'); None for '*' or nothing usable."""
    for tag in ranges or []:
        tag = tag.strip().lower()
        if tag in ("*", "und"):           # "und": the resolver's own value when Accept-Language is absent
            return None
        return tag if _LANGUAGE.fullmatch(tag) else None
    return None


def host_of(url: str | None) -> str | None:
    """The host of an address, lower case, or None."""
    if not url:
        return None
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    return host[:MAX_VALUE] if host else None


def company_part(ai: str, value: str) -> str | None:
    """Where the GS1 Company Prefix starts in a key's value (as gs1.company_part() in the portal); None for anything
    that is not a primary key's number."""
    if not _AI.fullmatch(ai or "") or not value:
        return None
    return value[1:] if ai in COMPANY_AFTER_FIRST_DIGIT else value


def qualifiers(pairs: list[tuple[str, str]]) -> dict[str, str | None]:
    """Key qualifiers as {AI: value}, the value of a serial number or TPX left out (None)."""
    kept: dict[str, str | None] = {}
    for ai, value in pairs:
        if _AI.fullmatch(str(ai)):
            kept[str(ai)] = None if ai in UNIT_QUALIFIERS else str(value)[:MAX_VALUE]
    return kept


def pairs_of_path(path: str | None) -> list[tuple[str, str]]:
    """'/10/L1/21/ABC' (values percent-encoded) → [('10', 'L1'), ('21', 'ABC')]."""
    parts = [p for p in (path or "").strip("/").split("/") if p != ""]
    return [(parts[i], unquote(parts[i + 1])) for i in range(0, len(parts) - 1, 2)]


def masked_level(path: str | None) -> str:
    """A record level ('/10/L1/21/ABC', values percent-encoded) as stored: values decoded, those of unit qualifiers
    replaced by '*'."""
    return "".join(f"/{ai}/{'*' if ai in UNIT_QUALIFIERS else value[:MAX_VALUE]}" for ai, value in pairs_of_path(path))


def attribute_ais(query_string: str) -> list[str]:
    """The AIs of the data attributes in a query string ('17=261231&3103=000500' → ['17', '3103']); values are not
    kept, nor parameters that are not AIs (linkType, context)."""
    found = []
    for part in re.split(r"[&;]", query_string or ""):
        name = unquote(part.split("=", 1)[0]).strip()
        if _AI.fullmatch(name) and name not in found:
            found.append(name)
    return found


# ----------------------------------------------------------------------------------------------- the routes' side
def note(**fields: Any) -> None:
    """Called by the resolution routes: marks the request as one to record and keeps what the route knows (form, ai,
    value, qualifiers, linkType, level, outcome, epc, path). Fields given as None are ignored."""
    current = g.get("resolution")
    if current is None:
        current = g.resolution = {}
    current.update({k: v for k, v in fields.items() if v is not None})


def start() -> None:
    """before_request: the time the request arrived."""
    g.request_started = time.perf_counter()


def record(response: Response) -> Response:
    """after_request: queues the event of a resolution request (one that called note()). Never raises."""
    try:
        noted = g.get("resolution")
        if noted is None or request.method not in ("GET", "HEAD") or not enabled():
            return response
        WRITER.put(event(noted, response))
    except Exception as exc:          # the log must never change an answer
        log.warning("Request not logged: %s", exc)
    return response


def event(noted: dict[str, Any], response: Response) -> dict[str, Any]:
    """The stored event, from what the route noted, the answer and the request's headers."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = response.status_code
    started = g.get("request_started")
    doc: dict[str, Any] = {"t": now, "expiresAt": now + timedelta(days=days()), "m": request.method,
                           "f": noted.get("form", "uri"), "s": status}
    if noted.get("epc"):
        doc["epc"] = str(noted["epc"])[:40]
    ai, value = noted.get("ai"), noted.get("value")
    if ai and value is not None:
        doc["ai"], doc["v"] = str(ai)[:10], str(value)[:MAX_VALUE]
        cp = company_part(doc["ai"], doc["v"])
        if cp:
            doc["cp"] = cp
    elif noted.get("path"):
        doc["p"] = str(noted["path"])[:MAX_PATH]
    q = qualifiers(noted.get("qualifiers") or [])
    if q:
        doc["q"] = q
    attributes = attribute_ais(noted.get("query", ""))
    if attributes:
        doc["da"] = attributes
    if noted.get("linkType"):
        doc["lt"] = str(noted["linkType"])[:MAX_VALUE]
    doc["o"] = outcome(status, noted)
    if doc["o"] in ("redirect", "choice") and "level" in noted:
        doc["lvl"] = masked_level(noted["level"])
    if status in (301, 302, 303, 307, 308):
        target = host_of(response.headers.get("Location"))
        if target:
            doc["to"] = target
    if started is not None:
        doc["ms"] = max(0, round((time.perf_counter() - started) * 1000))
    lang = language(noted.get("languages") or [])
    if lang:
        doc["lang"] = lang
    doc["dev"] = device_class(request.headers.get("User-Agent"))
    referrer = host_of(request.headers.get("Referer"))
    if referrer:
        doc["ref"] = referrer
    header = os.environ.get("RESOLVER_LOG_COUNTRY_HEADER", "").strip()
    if header:
        country = (request.headers.get(header) or "").strip()
        if _COUNTRY.fullmatch(country):
            doc["c"] = country.upper()
    return doc


def outcome(status: int, noted: dict[str, Any]) -> str:
    """redirect, choice, linkset, compressed, unknown, noLink, invalid or error."""
    if noted.get("compress"):
        return "compressed" if status < 400 else "invalid"
    if status == 307:
        return "redirect"
    if status == 300:
        return "choice"
    if status < 300:
        return "linkset"
    if status == 404:
        return "noLink" if noted.get("outcome") == "noLink" else "unknown"
    if status < 500:
        return "invalid"
    return "error"


# ----------------------------------------------------------------------------------------------- the writer
class Writer:
    """A bounded queue and a background thread that writes it in batches, one per server process (started at the
    first event, again after a fork)."""

    def __init__(self, collection: Callable[[], Any] | None = None, size: int = QUEUE_SIZE):
        self.collection = collection          # a function returning the collection (set by create_app or a test)
        self.size = size
        self.dropped = 0                      # events lost since the last warning
        self.lost_total = 0                   # events lost in this process
        self.written = 0
        self._warned = 0.0
        self._pid = None
        self._queue: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._indexed = False
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        if self._pid == os.getpid() and self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._pid == os.getpid() and self._thread is not None and self._thread.is_alive():
                return
            self._pid = os.getpid()
            self._queue = queue.Queue(maxsize=self.size)
            self._thread = threading.Thread(target=self._run, name="request-log", daemon=True)
            self._thread.start()

    def put(self, doc: dict[str, Any]) -> bool:
        """Queues an event without waiting; False (the event lost and counted) when the queue is full."""
        self._ensure_thread()
        try:
            self._queue.put_nowait(doc)
            return True
        except queue.Full:
            self._lost(1, "the queue is full")
            return False

    def _lost(self, count: int, reason: str) -> None:
        self.dropped += count
        self.lost_total += count
        now = time.monotonic()
        if now - self._warned >= WARN_SECONDS:
            log.warning("Request log: %d event(s) lost (%s).", self.dropped, reason)
            self._warned, self.dropped = now, 0

    def _target(self):
        target = self.collection() if self.collection else None
        if target is None:
            raise RuntimeError("no database")
        if not self._indexed:
            target.create_index([("t", -1)])
            target.create_index([("cp", 1), ("t", -1)])
            target.create_index([("ai", 1), ("v", 1), ("t", -1)])
            target.create_index([("expiresAt", 1)], expireAfterSeconds=0)
            self._indexed = True
        return target

    def _write(self, batch: list[dict[str, Any]]) -> None:
        for attempt in (1, 2):
            try:
                self._target().insert_many(batch, ordered=False)
                self.written += len(batch)
                return
            except Exception as exc:
                if attempt == 2:
                    self._lost(len(batch), f"{type(exc).__name__}: {exc}")
                else:
                    time.sleep(0.2)

    def _run(self) -> None:
        q = self._queue
        while True:
            try:
                first = q.get(timeout=FLUSH_SECONDS)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(q.get_nowait())
                except queue.Empty:
                    break
            self._write(batch)
            for _ in batch:
                q.task_done()

    def flush(self, timeout: float = 5.0) -> bool:
        """Waits until every queued event is written or lost (tests; a normal stop). True when the queue emptied."""
        if self._queue is None or self._pid != os.getpid():
            return True
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return not self._queue.unfinished_tasks


WRITER = Writer()
atexit.register(lambda: WRITER.flush(3.0))
