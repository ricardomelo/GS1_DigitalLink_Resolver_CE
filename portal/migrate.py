"""
One-off move of the files earlier versions of the portal kept in its configuration volume into the portal's
database (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.6). Run by app.py at start-up, before
any request is served:

  users.json         → users          (accounts written before roles existed become administrators)
  records-meta.json  → record_meta
  journal.jsonl      → journal        (dates, categories and the retention of journal.py)

A file is imported only into an empty collection, then renamed "<name>.migrated" and left in the volume as a
copy. Every document gets a fixed _id (user name, record key, "jsonl-<line>"), so a start that stops half
way through imports the rest at the next start without duplicates: the setting "migration" marks a file
"started" until it is done. One process at a time (store.lock "migration"), so replicas starting together
do not import twice. secret.key is not moved: it stays the fallback session key (app._secret_key).
"""
import json
import logging
import os

from pymongo.errors import BulkWriteError

import journal
import store
import users

log = logging.getLogger("portal.migrate")
BATCH = 1000


def _sources(config_dir: str) -> list[tuple[str, str, str]]:
    """(name, file, collection) of each file to move; PORTAL_*_FILE as earlier versions read them."""
    def path(variable, name):
        return os.environ.get(variable, "").strip() or os.path.join(config_dir, name)
    return [("users", path("PORTAL_USERS_FILE", "users.json"), "users"),
            ("meta", path("PORTAL_META_FILE", "records-meta.json"), "record_meta"),
            ("journal", path("PORTAL_JOURNAL_FILE", "journal.jsonl"), "journal")]


def _insert(collection, docs: list[dict]) -> int:
    """Inserts documents, skipping those already there (same _id); returns how many were added."""
    if not docs:
        return 0
    try:
        return len(collection.insert_many(docs, ordered=False).inserted_ids)
    except BulkWriteError as exc:
        errors = exc.details.get("writeErrors", [])
        if any(err.get("code") != 11000 for err in errors):
            raise
        return exc.details.get("nInserted", len(docs) - len(errors))


def _users(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [{"_id": name, **{k: v for k, v in users._account(value).items()}} for name, value in data.items()]


def _meta(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return []
    return [{"_id": key, **{k: v for k, v in value.items() if k in ("createdAt", "createdBy", "updatedAt", "updatedBy")}}
            for key, value in data.items() if isinstance(value, dict)]


def _journal(path: str, collection) -> tuple[int, int]:
    """Imports journal.jsonl in batches; returns (events added, lines that could not be read)."""
    days = journal.retention_days()
    added, damaged, batch = 0, 0, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                at = store.parse_iso(event.pop("at"))
                user, action = event.pop("user", "-"), event.pop("action")
            except (ValueError, KeyError, TypeError, AttributeError):
                damaged += 1
                continue
            if at is None:
                damaged += 1
                continue
            doc = journal.event_document(at, user, action, days, **event)
            doc["_id"] = f"jsonl-{number:09d}"
            batch.append(doc)
            if len(batch) >= BATCH:
                added += _insert(collection, batch)
                batch = []
    added += _insert(collection, batch)
    return added, damaged


def run(config_dir: str) -> dict:
    """Moves every file that is still there and whose collection is empty (or whose import was interrupted).
    Returns {name: number of documents added} for the files moved in this call."""
    moved = {}
    sources = [s for s in _sources(config_dir) if os.path.isfile(s[1])]
    if not sources:
        return moved
    with store.lock("migration", hold_seconds=1800, wait_seconds=1800):
        state = store.get_setting("migration") or {}
        for name, path, collection_name in sources:
            if not os.path.isfile(path):                    # moved by another replica while this one waited
                continue
            collection = store.col(collection_name)
            started = state.get(name) == "started"
            if isinstance(state.get(name), dict):
                log.info("%s was already imported on %s; the file was left in place.", path, state[name].get("at"))
                continue
            if not started and collection.estimated_document_count():
                log.warning("%s not imported: the %s collection already holds data.", path, collection_name)
                continue
            state[name] = "started"
            store.set_setting("migration", state)
            damaged = 0
            if name == "users":
                count = _insert(collection, _users(path))
            elif name == "meta":
                count = _insert(collection, _meta(path))
            else:
                count, damaged = _journal(path, collection)
            state[name] = {"at": store.iso(store.now()), "file": os.path.basename(path), "added": count,
                           "damaged": damaged}
            store.set_setting("migration", state)
            moved[name] = count
            try:
                os.replace(path, path + ".migrated")
            except OSError as exc:
                log.warning("%s imported but not renamed (%s); it will not be read again.", path, exc)
            log.info("Moved %d document(s) from %s to the %s collection%s.", count, os.path.basename(path),
                     collection_name, f" ({damaged} damaged line(s) skipped)" if damaged else "")
    return moved
