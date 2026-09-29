"""
Journal of what happens in the portal: sign-ins, user administration and every record change, with the
full content of each version of a record so that it can be restored.

One JSON object per line in journal.jsonl, next to users.json in the portal's configuration volume
(included in the daily backup). Appends are serialised with an advisory lock; reads scan the file,
newest first, which is comfortable for hundreds of thousands of events.

Event: {"at", "user", "action", "anchor"?, "qpath"?, "doc"?, "detail"?}
  record actions: create, update, delete (doc = the record after the change, or before a deletion),
  import (detail = counts); others: login, login-failed, logout, password-change, user-create,
  user-update, user-reset, user-remove, export.
"""
import fcntl
import json
import os
from collections import deque
from datetime import datetime, timezone

JOURNAL_FILE = os.environ.get("PORTAL_JOURNAL_FILE",
                              os.path.join(os.environ.get("PORTAL_CONFIG_DIR", "/app/config"), "journal.jsonl"))
RECORD_ACTIONS = ("create", "update", "delete")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append(action: str, user: str, **fields) -> None:
    event = {"at": _now(), "user": user, "action": action, **{k: v for k, v in fields.items() if v is not None}}
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(JOURNAL_FILE, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(line)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    try:
        os.chmod(JOURNAL_FILE, 0o600)
    except OSError:
        pass


def _events():
    try:
        with open(JOURNAL_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except FileNotFoundError:
        return


def for_record(anchor: str, qpath: str, limit: int = 20) -> list[dict]:
    """The latest versions of one record, newest first."""
    found = deque(maxlen=limit)
    for event in _events():
        if event.get("anchor") == anchor and event.get("qpath", "") == qpath and event.get("action") in RECORD_ACTIONS:
            found.append(event)
    return list(reversed(found))


def search(user: str | None = None, since: str | None = None, until: str | None = None,
           text: str | None = None, allowed=None, limit: int = 500) -> list[dict]:
    """Events newest first, without record contents. since/until are ISO dates (inclusive);
    text matches the anchor, qualifiers or action; allowed(anchor) filters records by permission."""
    found = deque(maxlen=limit)
    needle = (text or "").lower()
    for event in _events():
        day = event.get("at", "")[:10]
        if user and event.get("user") != user:
            continue
        if since and day < since:
            continue
        if until and day > until:
            continue
        if needle and needle not in " ".join(str(event.get(k, "")) for k in ("anchor", "qpath", "action", "detail")).lower():
            continue
        if allowed and event.get("anchor") and not allowed(event["anchor"]):
            continue
        found.append({k: v for k, v in event.items() if k != "doc"})
    return list(reversed(found))
