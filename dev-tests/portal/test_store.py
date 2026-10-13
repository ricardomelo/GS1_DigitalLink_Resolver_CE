"""
The portal's database layer (Documentation/adr/0001-portal-state-in-mongodb.md): connection settings,
indexes, the shared lock, users, record metadata, the journal with its retention, the sign-in throttle and
the one-off migration of the files of earlier versions.

Runs against mongomock (no server needed) unless PORTAL_DB_URI names a real MongoDB; test_store_mongodb.py
runs it that way, as the portal's own least-privilege user, in the continuous integration.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_store.py
"""
import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_store_{os.getpid()}")
os.environ.update(SESSION_TOKEN="tok", FQDN="id.example.org", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false")
for variable in ("PORTAL_JOURNAL_SESSION_DAYS", "PORTAL_JOURNAL_RECORD_DAYS", "PORTAL_JOURNAL_ADMIN_DAYS"):
    os.environ.pop(variable, None)
sys.path[:0] = [PORTAL]
logging.basicConfig(level=logging.WARNING)

import journal  # noqa: E402
import meta  # noqa: E402
import migrate  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402

REAL = not os.environ["PORTAL_DB_URI"].startswith("mongomock://")
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def with_env(**values):
    """Runs store.uri() with some variables changed, then puts them back."""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return store.uri()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------ connection settings
built = with_env(PORTAL_DB_URI=None, PORTAL_DB_HOST="db.internal:27018", PORTAL_DB_USERNAME="portal user",
                 PORTAL_DB_PASSWORD="p@ss:w/rd%")
check("URI built from the parts, user and password percent-encoded, own database as authentication source",
      built == f"mongodb://portal+user:p%40ss%3Aw%2Frd%25@db.internal:27018/{store.DB_NAME}?authSource={store.DB_NAME}",
      built)
check("defaults: host database-service:27017, user resolver_portal",
      with_env(PORTAL_DB_URI=None, PORTAL_DB_HOST=None, PORTAL_DB_USERNAME=None, PORTAL_DB_PASSWORD="x")
      .startswith("mongodb://resolver_portal:x@database-service:27017/"))
try:
    with_env(PORTAL_DB_URI=None, PORTAL_DB_PASSWORD="")
    check("no password → refuses to connect", False)
except RuntimeError as exc:
    check("no password → refuses to connect, naming the variable", "PORTAL_DB_PASSWORD" in str(exc), exc)
check("PORTAL_DB_URI wins over the parts", with_env(PORTAL_DB_URI="mongodb://h/x", PORTAL_DB_PASSWORD="y") == "mongodb://h/x")

# ------------------------------------------------------------------ indexes
def ttl(collection, field):
    for index in store.col(collection).list_indexes():
        if list(index["key"].keys()) == [field]:
            return index.get("expireAfterSeconds")
    return None


check("journal: TTL index on expiresAt (expire at that date)", ttl("journal", "expiresAt") == 0)
check("login_failures: TTL index on at, 15 minutes", ttl("login_failures", "at") == 900)
check("linkcheck_cache: TTL index on expiresAt", ttl("linkcheck_cache", "expiresAt") == 0)
names = {tuple(i["key"].keys()) for i in store.col("journal").list_indexes()}
check("journal: indexes for the record history and the audit filters",
      {("anchor", "qpath", "at"), ("user", "at"), ("at",), ("category",)} <= names, names)

# ------------------------------------------------------------------ dates and settings
stamp = store.now()
check("dates in UTC, naive, to the millisecond", stamp.tzinfo is None and stamp.microsecond % 1000 == 0)
check("ISO output to the second with Z", store.iso(stamp.replace(microsecond=123000)).endswith("Z")
      and "." not in store.iso(stamp), store.iso(stamp))
check("ISO input: Z, offset and plain date", store.parse_iso("2026-10-13T12:00:00Z").hour == 12
      and store.parse_iso("2026-10-13T09:00:00-03:00").hour == 12 and store.parse_iso("nonsense") is None)
store.set_setting("probe", {"a": [1, 2]})
check("settings: a value is stored and read back", store.get_setting("probe") == {"a": [1, 2]}
      and store.get_setting("absent", "d") == "d")

# ------------------------------------------------------------------ the shared lock
with store.lock("probe"):
    try:
        with store.lock("probe", wait_seconds=0.2):
            pass
        check("lock: a second holder waits and gives up", False)
    except store.LockTimeout:
        check("lock: a second holder waits and gives up", True)
with store.lock("probe", wait_seconds=0.2):
    check("lock: released at the end of the block", True)
store.col("settings").insert_one({"_id": "lock:stale", "owner": "dead", "since": store.now() - timedelta(minutes=5)})
started = time.monotonic()
with store.lock("stale", hold_seconds=60, wait_seconds=2):
    check("lock: a lock left by a process that died is broken", time.monotonic() - started < 1.5)

# ------------------------------------------------------------------ users
users.create("ana", "ana-password-long", "admin", prefixes=["7898357"], must_change=False)
check("create, read back: role, prefixes, created", users.get("ana")["role"] == "admin"
      and users.get("ana")["prefixes"] == ["7898357"] and users.get("ana")["created"].endswith("Z"))
check("password verified; wrong one refused", users.verify("ana", "ana-password-long")
      and not users.verify("ana", "wrong-password-xx") and not users.verify("nobody", "x"))
try:
    users.create("ana", "another-password", "reader")
    check("duplicate user refused", False)
except users.UserError as exc:
    check("duplicate user refused", exc.code == "users.exists")
try:
    users.update("ana", role="editor")
    check("the last enabled administrator keeps that status", False)
except users.UserError as exc:
    check("the last enabled administrator keeps that status", exc.code == "users.lastAdmin")
check("refused change not saved", users.get("ana")["role"] == "admin")
users.set_password("bia", "bia-password-long", role="admin")
fp = users.fingerprint("bia")
users.set_password("bia", "bia-password-new!", must_change=True)
check("new password: fingerprint changes (other sessions end), must change", users.fingerprint("bia") != fp
      and users.get("bia")["mustChange"] and users.get("bia")["role"] == "admin")
users.touch_login("bia")
check("last sign-in recorded", (users.get("bia")["lastLogin"] or "").endswith("Z"))
check("load: every account, no internal fields", set(users.load()) == {"ana", "bia"}
      and "_id" not in users.load()["ana"])

# two administrators remove each other at the same moment: one must be refused
outcome = []
barrier = threading.Barrier(2)


def remove(name):
    barrier.wait()
    try:
        users.remove(name)
        outcome.append("removed")
    except users.UserError as exc:
        outcome.append(exc.code)


threads = [threading.Thread(target=remove, args=(n,)) for n in ("ana", "bia")]
[t.start() for t in threads]
[t.join() for t in threads]
check("two administrators removing each other at once: one is refused, one administrator is left",
      sorted(outcome) == ["removed", "users.lastAdmin"] and len(users.load()) == 1, (outcome, list(users.load())))
users.create("carla", "carla-password-1", "editor")
done = threading.Event()
waiter = threading.Thread(target=lambda: (users.update("carla", role="reader"), done.set()))
with store.lock("users"):                                  # another replica is changing users
    waiter.start()
    time.sleep(0.4)
    check("a change of users waits for the lock held by another process", not done.is_set())
waiter.join(5)
check("… and is made once the lock is released", done.is_set() and users.get("carla")["role"] == "reader")
users.remove("carla")
check("remove", users.get("carla") is None)

# ------------------------------------------------------------------ record metadata
meta.touch("/01/09506000134352", "", "ana")
time.sleep(1.1)
meta.touch("/01/09506000134352", "", "bia")
meta.touch("/414/9506000134376", "/254/1", "ana")
known = meta.load()
first = known.get("09506000134352", {})
check("metadata: creation kept, last change updated", first.get("createdBy") == "ana" and first.get("updatedBy") == "bia"
      and first["createdAt"] < first["updatedAt"], first)
check("metadata: keys as before (GTIN-14; AI/value + qualifier path)", "414/9506000134376/254/1" in known, known)
meta.remove("/01/09506000134352", "")
check("metadata: removed with the record", "09506000134352" not in meta.load())

# ------------------------------------------------------------------ journal
journal.append("login", "ana", detail="10.0.0.1")
journal.append("create", "ana", anchor="/01/09506000134352", qpath="", doc={"v": 1, "https://gs1.org/voc/pip": "dots in a key"})
journal.append("update", "bia", anchor="/01/09506000134352", qpath="", doc={"v": 2})
journal.append("update", "bia", anchor="/01/09506000134352", qpath="/10/L1", doc={"v": "lot"})
journal.append("user-create", "ana", detail="carla")
login = store.col("journal").find_one({"action": "login"})
create = store.col("journal").find_one({"action": "create"})
check("categories: session, record, admin", login["category"] == "session" and create["category"] == "record"
      and store.col("journal").find_one({"action": "user-create"})["category"] == "admin")
day = login["at"].replace(hour=0, minute=0, second=0, microsecond=0)
check("retention defaults: sign-ins 180 days after the end of their day, records kept", "expiresAt" not in create
      and login["expiresAt"] == day + timedelta(days=181), login)
versions = journal.for_record("/01/09506000134352", "")
check("history of a record: newest first, only that record, with contents",
      [v["doc"]["v"] for v in versions] == [2, 1] and versions[1]["doc"]["https://gs1.org/voc/pip"] == "dots in a key",
      versions)
check("history: same format as journal.jsonl (ISO date, no internal fields)",
      versions[0]["at"].endswith("Z") and set(versions[0]) <= {"at", "user", "action", "anchor", "qpath", "doc", "detail"},
      versions[0])
store.col("journal").insert_one({"at": store.now(), "user": "old", "action": "create", "category": "record",
                                 "anchor": "/01/09506000134352", "doc": {"v": 0}})
check("history: an event without qpath belongs to the record itself",
      len(journal.for_record("/01/09506000134352", "")) == 3 and len(journal.for_record("/01/09506000134352", "", limit=1)) == 1)
events = journal.search()
check("audit: newest first, never the record contents", events[0]["action"] == "create" and all("doc" not in e for e in events),
      events[:2])
check("audit filters: user, text, permission", {e["user"] for e in journal.search(user="bia")} == {"bia"}
      and [e["action"] for e in journal.search(text="10.0.0")] == ["login"]
      and all(not e.get("anchor") for e in journal.search(allowed=lambda anchor: False)))
today = store.now().date().isoformat()
yesterday = (store.now() - timedelta(days=1)).date().isoformat()
check("audit filters: dates inclusive", len(journal.search(since=today, until=today)) == len(events)
      and journal.search(until=yesterday) == [] and len(journal.search(limit=2)) == 2)

# retention changes are applied to existing events
store.set_setting("journalRetention", None)
journal.apply_retention()
os.environ["PORTAL_JOURNAL_RECORD_DAYS"] = "30"
changed = journal.apply_retention()
create = store.col("journal").find_one({"action": "create", "user": "ana"})
check("retention of records set to 30 days: existing record events updated, others untouched",
      changed == {"record": 4} and create["expiresAt"] == day + timedelta(days=31),
      changed)
check("unchanged retention: nothing to do", journal.apply_retention() == {})
os.environ["PORTAL_JOURNAL_RECORD_DAYS"] = "0"
journal.apply_retention()
check("retention back to 0: record events kept for ever again",
      store.col("journal").count_documents({"category": "record", "expiresAt": {"$exists": True}}) == 0)
os.environ["PORTAL_JOURNAL_SESSION_DAYS"] = "many"
check("an unreadable value falls back to the default", journal.retention_days()["session"] == 180)
os.environ.pop("PORTAL_JOURNAL_SESSION_DAYS")
os.environ.pop("PORTAL_JOURNAL_RECORD_DAYS")

# ------------------------------------------------------------------ sign-in throttle (app.LoginThrottle)
import app  # noqa: E402

throttle = app.LoginThrottle()
keys = (f"user:{uuid.uuid4().hex}", f"addr:{uuid.uuid4().hex}")
for _ in range(4):
    throttle.fail(*keys)
check("throttle: four failures do not lock", throttle.retry_after(*keys) == 0)
throttle.fail(*keys)
wait = throttle.retry_after(keys[0])
check("throttle: the fifth locks for about 15 minutes", 890 <= wait <= 901, wait)
check("throttle: another user name is not locked", throttle.retry_after("user:someone-else") == 0)
other = app.LoginThrottle()
check("throttle: shared by every instance (replica)", other.retry_after(keys[1]) > 0)
throttle.clear(*keys)
check("throttle: a successful sign-in clears both keys", throttle.retry_after(*keys) == 0)
old = store.now() - timedelta(minutes=16)
store.col("login_failures").insert_many([{"key": "user:old", "at": old} for _ in range(5)])
check("throttle: failures older than 15 minutes do not count", throttle.retry_after("user:old") == 0)

# ------------------------------------------------------------------ migration of the files of earlier versions
from werkzeug.security import generate_password_hash  # noqa: E402

def empty_database():
    """Starts a part of the test from an empty database (the portal's user may only use its own database)."""
    for name in ("users", "record_meta", "journal", "settings", "login_failures"):
        store.col(name).delete_many({})


empty_database()
folder = tempfile.mkdtemp()
with open(f"{folder}/users.json", "w") as fh:
    json.dump({"boss": generate_password_hash("boss-password-long"),
               "rui": {"hash": generate_password_hash("rui-password-long"), "role": "reader", "prefixes": ["789"],
                       "disabled": False, "mustChange": True, "created": "2026-09-25T10:00:00Z", "lastLogin": None}}, fh)
with open(f"{folder}/records-meta.json", "w") as fh:
    json.dump({"09506000134352": {"createdAt": "2026-09-25T10:00:00Z", "createdBy": "boss",
                                  "updatedAt": "2026-09-26T10:00:00Z", "updatedBy": "rui"}}, fh)
lines = [{"at": "2026-09-25T10:00:00Z", "user": "boss", "action": "login", "detail": "10.0.0.2"},
         {"at": "2026-09-25T10:01:00Z", "user": "boss", "action": "create", "anchor": "/01/09506000134352",
          "qpath": "", "doc": {"v": "first"}},
         "{damaged line",
         {"at": "2026-09-26T10:00:00Z", "user": "rui", "action": "update", "anchor": "/01/09506000134352",
          "qpath": "", "doc": {"v": "second"}},
         {"at": "not a date", "user": "x", "action": "login"}]
with open(f"{folder}/journal.jsonl", "w") as fh:
    for line in lines:
        fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    fh.write("\n")
moved = migrate.run(folder)
check("migration: users, metadata and journal moved", moved == {"users": 2, "meta": 1, "journal": 3}, moved)
check("migration: files renamed *.migrated and kept", sorted(os.listdir(folder)) ==
      ["journal.jsonl.migrated", "records-meta.json.migrated", "users.json.migrated"], os.listdir(folder))
check("migration: an account from before roles is an administrator; others as they were",
      users.get("boss")["role"] == "admin" and users.verify("boss", "boss-password-long")
      and users.get("rui")["prefixes"] == ["789"] and users.get("rui")["mustChange"])
check("migration: record metadata as before", meta.load()["09506000134352"]["updatedBy"] == "rui")
history = journal.for_record("/01/09506000134352", "")
check("migration: journal events with their dates, history newest first",
      [h["doc"]["v"] for h in history] == ["second", "first"] and history[0]["at"] == "2026-09-26T10:00:00Z", history)
check("migration: damaged lines skipped and counted",
      store.get_setting("migration")["journal"]["damaged"] == 2, store.get_setting("migration"))
migrated_login = store.col("journal").find_one({"action": "login"})
check("migration: categories and retention applied to old events", migrated_login["category"] == "session"
      and migrated_login["expiresAt"] == store.parse_iso("2026-09-26T00:00:00Z") + timedelta(days=180))
check("migration: a second start finds nothing to do", migrate.run(folder) == {})

# a file that comes back (an old volume restored) does not overwrite the database
with open(f"{folder}/users.json", "w") as fh:
    json.dump({"intruder": generate_password_hash("intruder-password")}, fh)
store.set_setting("migration", {})
check("migration: a users.json next to a database that holds users is not imported",
      migrate.run(folder) == {} and users.get("intruder") is None and os.path.exists(f"{folder}/users.json"))

# an import interrupted half way finishes at the next start, without duplicates
empty_database()
folder = tempfile.mkdtemp()
with open(f"{folder}/journal.jsonl", "w") as fh:
    for n in range(1, 2501):
        fh.write(json.dumps({"at": "2026-09-25T10:00:00Z", "user": "u", "action": "update",
                             "anchor": f"/01/{n:014d}", "qpath": "", "doc": {"n": n}}) + "\n")
store.set_setting("migration", {"journal": "started"})
first_lines = [json.loads(line) for line in open(f"{folder}/journal.jsonl")][:1000]
store.col("journal").insert_many([{**journal.event_document(store.parse_iso(e["at"]), e["user"], e["action"],
                                                            anchor=e["anchor"], qpath="", doc=e["doc"]),
                                   "_id": f"jsonl-{n:09d}"} for n, e in enumerate(first_lines, 1)])
moved = migrate.run(folder)
check("migration: an interrupted import is completed without duplicates",
      moved == {"journal": 1500} and store.col("journal").count_documents({}) == 2500, moved)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
