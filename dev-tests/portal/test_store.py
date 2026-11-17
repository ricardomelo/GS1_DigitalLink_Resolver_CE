"""
The portal's database layer (Documentation/adr/0001-portal-state-in-mongodb.md): connection settings,
indexes, the shared lock, users, record metadata, the journal with its retention, the sign-in throttle and
the one-off migration of the files of earlier versions.

Runs against mongomock (no server needed) unless PORTAL_DB_URI names a real MongoDB; test_store_mongodb.py
runs it that way, as the portal's own least-privilege user, in the continuous integration, with
DEV_TESTS_DB_ADMIN_URI naming the root user: that user changes and deletes journal events (the tampering checks)
and runs the retention and the sealing, which the portal's user may not (ADR 0026 section 2.5.2).

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
os.environ.update(SESSION_TOKEN="tok", FQDN="id.example.org", PORTAL_CONFIG_DIR=CONFIG, PORTAL_JOURNAL_KEY="journal-key-1",
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
ADMIN_URI = os.environ.get("DEV_TESTS_DB_ADMIN_URI", "").strip()
_admin_client = None


def admin_col(name):
    """A collection as the root user sees it (the portal's own view without DEV_TESTS_DB_ADMIN_URI)."""
    global _admin_client
    if not ADMIN_URI:
        return store.col(name)
    if _admin_client is None:
        from pymongo import MongoClient
        _admin_client = MongoClient(ADMIN_URI, serverSelectionTimeoutMS=20000)
    database = store.journal_db_name() if name in store.JOURNAL_COLLECTIONS else store.DB_NAME
    return _admin_client[database][name]


def as_admin(step, *args, **kwargs):
    """Runs a journal step that updates events (retention, sealing) connected as the root user, as portal-db-init
    does, then connects as the portal's user again."""
    if not ADMIN_URI:
        return step(*args, **kwargs)
    saved = os.environ["PORTAL_DB_URI"]
    os.environ["PORTAL_DB_URI"] = ADMIN_URI
    store.reset()
    try:
        return step(*args, **kwargs)
    finally:
        os.environ["PORTAL_DB_URI"] = saved
        store.reset()
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
as_admin(journal.apply_retention)
os.environ["PORTAL_JOURNAL_RECORD_DAYS"] = "30"
changed = as_admin(journal.apply_retention)
create = store.col("journal").find_one({"action": "create", "user": "ana"})
check("retention of records set to 30 days: existing record events updated, others untouched",
      changed == {"record": 4} and create["expiresAt"] == day + timedelta(days=31),
      changed)
check("unchanged retention: nothing to do", as_admin(journal.apply_retention) == {})
os.environ["PORTAL_JOURNAL_RECORD_DAYS"] = "0"
as_admin(journal.apply_retention)
check("retention back to 0: record events kept for ever again",
      store.col("journal").count_documents({"category": "record", "expiresAt": {"$exists": True}}) == 0)
os.environ["PORTAL_JOURNAL_SESSION_DAYS"] = "many"
check("an unreadable value falls back to the default", journal.retention_days()["session"] == 180)
os.environ.pop("PORTAL_JOURNAL_SESSION_DAYS")
os.environ.pop("PORTAL_JOURNAL_RECORD_DAYS")

# ------------------------------------------------------------------ journal integrity (ADR 0026)
from pymongo.errors import DuplicateKeyError  # noqa: E402

J = admin_col("journal")                 # the root user's view: changes and deletions are tampering here
J.delete_many({})
admin_col("journal_heads").delete_many({})
check("chains: unique index on (chain, seq) for sealed events only",
      any(i.get("unique") and list(i["key"]) == ["chain", "seq"] for i in J.list_indexes()))
refs = [journal.append("create", "ana", anchor="/01/09506000134352", qpath="", doc={"v": 1, "at": "x"}),
        journal.append("login", "ana", detail="10.0.0.1"),
        journal.append("update", "bia", anchor="/01/09506000134352", qpath="", doc={"v": 2.5, "list": [1, "a"]}),
        journal.append("user-create", "ana", detail="carla", tenant="t-1"),
        journal.append("update", "bia", tenant="t-1", anchor="/01/09506000134352", qpath="/10/L1", doc={"v": None})]
check("append returns the event's chain and sequence number, one chain per trail and category",
      refs == [{"chain": "operator/record", "seq": 1}, {"chain": "operator/session", "seq": 1},
               {"chain": "operator/record", "seq": 2}, {"chain": "t-1/admin", "seq": 1}, {"chain": "t-1/record", "seq": 1}],
      refs)
first, second = J.find_one({"chain": "operator/record", "seq": 1}), J.find_one({"chain": "operator/record", "seq": 2})
check("seal: prev empty for the first event, the previous hash after", first["prev"] == "" and second["prev"] == first["hash"])
check("seal: hash is the SHA-256 of the stored content (read back from the database)",
      all(journal.content_hash(d) == d["hash"] for d in J.find()), [d["seq"] for d in J.find()])
check("seal: mac with the journal key, kid its identifier",
      second["mac"] == journal.mac_of(second["hash"], b"journal-key-1") and second["kid"] == journal.key_id(b"journal-key-1")
      and len(second["kid"]) == 8)
check("chains of a trail; every chain", journal.chains("t-1") == ["t-1/admin", "t-1/record"]
      and journal.chains() == ["operator/record", "operator/session"] and len(journal.chains(everything=True)) == 4)
good = journal.verify("operator/record")
check("verify: an untouched chain is ok, with its head as a receipt",
      good["ok"] and good["events"] == 2 and good["first"] == 1 and good["last"] == 2 and good["keyed"]
      and good["head"] == f'operator/record:2:{second["hash"]}' and good["otherKey"] == 0, good)


def problem(chain, receipt=None):
    found = journal.verify(chain, receipt)
    return (found.get("problem") or {}).get("kind"), (found.get("problem") or {}).get("seq")


J.update_one({"_id": first["_id"]}, {"$set": {"doc.v": 9}})
check("verify: a changed event → hash at its sequence number", problem("operator/record") == ("hash", 1),
      problem("operator/record"))
forged = {**first, "doc": {**first["doc"], "v": 9}}
J.update_one({"_id": first["_id"]}, {"$set": {"hash": journal.content_hash(forged)}})
check("verify: a changed event whose hash was recomputed without the key → mac at its sequence number",
      problem("operator/record") == ("mac", 1), problem("operator/record"))
os.environ["PORTAL_JOURNAL_KEY"] = ""
check("…without a key to check: its link breaks (prev of the next event)", problem("operator/record") == ("prev", 2),
      problem("operator/record"))
J.update_one({"_id": second["_id"]}, {"$set": {"prev": journal.content_hash(forged)}})
check("…and with the next link rewritten too → the next event's hash", problem("operator/record") == ("hash", 2))
os.environ["PORTAL_JOURNAL_KEY"] = "journal-key-1"
J.replace_one({"_id": first["_id"]}, first)
J.replace_one({"_id": second["_id"]}, second)
J.update_one({"_id": second["_id"]}, {"$set": {"mac": "0" * 64}})
check("verify: a seal not made with the key → mac", problem("operator/record") == ("mac", 2))
J.replace_one({"_id": second["_id"]}, second)
check("verify: restored → ok", journal.verify("operator/record")["ok"])

for n in range(3, 6):
    journal.append("update", "bia", anchor="/01/09506000134352", qpath="", doc={"v": n})
middle = J.find_one({"chain": "operator/record", "seq": 3})
J.delete_one({"_id": middle["_id"]})
check("verify: an event deleted in the middle → gap", problem("operator/record") == ("gap", 3), problem("operator/record"))
J.insert_one(middle)
newest = J.find_one({"chain": "operator/record", "seq": 5})
J.delete_one({"_id": newest["_id"]})
check("verify: the newest event deleted → truncated (journal_heads remembers seq 5)",
      problem("operator/record") == ("truncated", 5), problem("operator/record"))
check("append after a deleted tail continues from journal_heads (the gap stays visible)",
      journal.append("update", "bia", anchor="/01/09506000134352", qpath="", doc={"v": 6})["seq"] == 6
      and problem("operator/record") == ("gap", 5))
J.insert_one(newest)
check("verify: tail restored → ok", journal.verify("operator/record")["ok"])
try:
    J.insert_one({**newest, "_id": "copy"})
    check("a second event with the same sequence number is refused by the index", False)
except DuplicateKeyError:
    check("a second event with the same sequence number is refused by the index", True)
J.delete_many({"chain": "operator/record", "seq": {"$lte": 2}})
check("verify: a chain kept for ever must start at 1 → start", problem("operator/record") == ("start", 3))
first_login = J.find_one({"chain": "operator/session"})
journal.append("login", "ana", detail="10.0.0.2")
J.delete_one({"_id": first_login["_id"]})
check("verify: a category with retention may lose its beginning", journal.verify("operator/session")["ok"],
      journal.verify("operator/session"))
J.insert_many([first, second])

head = journal.verify("operator/record")["head"]
receipt = journal.parse_receipt(head)
check("receipt: parsed (chain, seq, hash); text that is not one → None",
      receipt == ("operator/record", 6, head.rsplit(":", 1)[1]) and journal.parse_receipt("operator/record:6:abc") is None
      and journal.parse_receipt("x") is None and journal.parse_receipt("a:b:" + "0" * 64) is None
      and journal.parse_receipt("operator/record:6:" + "g" * 64) is None)
check("receipt: a kept head still in the chain", journal.verify("operator/record", receipt).get("receipt") is True)
check("receipt: a head that is not in the chain → receipt",
      problem("operator/record", ("operator/record", 6, "f" * 64)) == ("receipt", 6)
      and journal.verify("operator/record", ("operator/record", 6, "f" * 64))["receipt"] is False)

errors = []
def racer():
    try:
        for _ in range(15):
            journal.append("user-update", "ana", detail="race", tenant="t-race")
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
threads = [threading.Thread(target=racer) for _ in range(6)]
[t.start() for t in threads]
[t.join() for t in threads]
seqs = sorted(d["seq"] for d in J.find({"chain": "t-race/admin"}))
check("writers racing on one chain: every event numbered once, no gap, chain ok",
      not errors and seqs == list(range(1, 91)) and journal.verify("t-race/admin")["ok"], (errors, seqs[-3:]))

J.insert_many([{"at": store.parse_iso("2026-01-02T00:00:00Z"), "user": "old", "action": "user-remove", "category": "admin",
                "tenant": "t-old", "detail": "second"},
               {"at": store.parse_iso("2026-01-01T00:00:00Z"), "user": "old", "action": "user-create", "category": "admin",
                "tenant": "t-old", "detail": "first"}])
check("verify: events of a trail not yet sealed → unsealed", problem("t-old/admin") in (("unsealed", None), (None, None))
      and journal.verify("operator/admin")["ok"])
check("events written before ADR 0026 sealed once, in the order they were written, marked so",
      as_admin(journal.seal_unsealed) == 2 and [d["detail"] for d in J.find({"chain": "t-old/admin"}).sort("seq", 1)] == ["first", "second"]
      and all(d["sealed"] == "upgrade" for d in J.find({"chain": "t-old/admin"})) and as_admin(journal.seal_unsealed) == 0
      and journal.verify("t-old/admin")["ok"])
J.insert_one({"at": store.now(), "user": "old", "action": "user-create", "category": "admin", "tenant": "t-old"})
check("verify: an unsealed event in a sealed trail → unsealed", problem("t-old/admin") == ("unsealed", None))
as_admin(journal.seal_unsealed)

os.environ["PORTAL_JOURNAL_KEY"] = "journal-key-2"
journal.append("user-update", "ana", detail="new key", tenant="t-old")
rotated = journal.verify("t-old/admin")
check("another key: the chain stays ok, its earlier events counted as sealed with another key",
      rotated["ok"] and rotated["otherKey"] == 3, rotated)
os.environ["PORTAL_JOURNAL_KEY"] = ""
journal.append("user-update", "ana", detail="no key", tenant="t-old")
unkeyed = J.find_one({"chain": "t-old/admin", "detail": "no key"})
check("without a key: sealed without mac, kid empty, verification says not keyed",
      "mac" not in unkeyed and unkeyed["kid"] == "" and journal.verify("t-old/admin")["keyed"] is False
      and journal.verify("t-old/admin")["ok"])
os.environ["PORTAL_JOURNAL_KEY"] = "journal-key-1"

store.set_setting("journalCheckpoint", None)
with_log = logging.getLogger("portal.journal")
seen = []
handler = logging.Handler()
handler.emit = lambda record: seen.append((record.levelname, record.getMessage()))
with_log.addHandler(handler)
with_log.setLevel(logging.INFO)
results = journal.checkpoint()
check("daily checkpoint: every chain verified, each head written to the log",
      len(results) == len(journal.chains(everything=True))
      and any(level == "INFO" and f"Journal head {head}" in text for level, text in seen), seen[:3])
check("daily checkpoint: once a day", journal.checkpoint() == [])
store.set_setting("journalCheckpoint", None)
J.update_one({"chain": "t-race/admin", "seq": 7}, {"$set": {"detail": "edited"}})
seen.clear()
journal.checkpoint()
check("daily checkpoint: a broken chain logged as an error",
      any(level == "ERROR" and "t-race/admin broken: hash at 7" in text for level, text in seen), seen)
with_log.removeHandler(handler)

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
check("throttle: a limit of its own (the address's 20)", throttle.retry_after(keys[1], limit=20) == 0
      and [throttle.fail(keys[1]) for _ in range(20)] and 890 <= throttle.retry_after(keys[1], limit=20) <= 901)

# progressive delay per user name and address (finding F-005)
pair = f"user-addr:{uuid.uuid4().hex}|192.0.2.9"


def failures_ago(key, *seconds):
    store.col("login_failures").insert_many([{"key": key, "at": store.now() - timedelta(seconds=s)} for s in seconds])


failures_ago(pair, 1, 1)
check("delay: two failures of a user name from one address cost nothing", throttle.delay(pair) == 0)
failures_ago(pair, 1)
check("delay: the third waits 15 seconds from the last failure", 13 <= throttle.delay(pair) <= 15, throttle.delay(pair))
failures_ago(pair, 1)
check("delay: the fourth 30 seconds", 28 <= throttle.delay(pair) <= 30, throttle.delay(pair))
failures_ago(pair, 1)
check("delay: the fifth 60 seconds (doubling)", 58 <= throttle.delay(pair) <= 60, throttle.delay(pair))
failures_ago(pair, *[1] * 10)
check("delay: never more than 15 minutes", 898 <= throttle.delay(pair) <= 900, throttle.delay(pair))
later = f"user-addr:{uuid.uuid4().hex}|192.0.2.9"
failures_ago(later, 40, 40, 40)
check("delay: counted from the last failure (15 seconds already passed)", throttle.delay(later) == 0)
recent = f"user-addr:{uuid.uuid4().hex}|192.0.2.9"
failures_ago(recent, 300, 300, 1)
check("delay: counted from the newest failure, not the oldest", 13 <= throttle.delay(recent) <= 15, throttle.delay(recent))
check("delay: another address of the same user name waits nothing",
      throttle.delay(pair.replace("192.0.2.9", "192.0.2.10")) == 0)
victim = uuid.uuid4().hex
failures_ago(f"user-addr:{victim}|192.0.2.1", 1, 1, 1)
failures_ago(f"user-addr:{victim}|192.0.2.2", 1, 1, 1)
failures_ago(f"user:{victim}", 1)
failures_ago(f"user-addr:{victim}x|192.0.2.1", 1, 1, 1)
throttle.clear_user(victim)
check("clear_user: every address of the user name forgotten, and its count",
      throttle.count(f"user-addr:{victim}|192.0.2.1") == throttle.count(f"user-addr:{victim}|192.0.2.2")
      == throttle.count(f"user:{victim}") == 0)
check("clear_user: a longer user name that starts with it is not touched", throttle.count(f"user-addr:{victim}x|192.0.2.1") == 3)

# ------------------------------------------------------------------ migration of the files of earlier versions
from werkzeug.security import generate_password_hash  # noqa: E402

def empty_database():
    """Starts a part of the test from an empty database (the portal's user may only use its own database)."""
    for name in ("users", "record_meta", "journal", "journal_heads", "settings", "login_failures"):
        admin_col(name).delete_many({})


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
check("migration: old events sealed in their chains as they are inserted, marked so (the portal's user may not "
      "update the journal afterwards)",
      all(d.get("seq") and d.get("sealed") == "upgrade" for d in store.col("journal").find())
      and all(journal.verify(c)["ok"] for c in journal.chains(everything=True)),
      [(d["_id"], d.get("seq"), d.get("sealed")) for d in store.col("journal").find()])
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

# ------------------------------------------------------------------ the journal's own database (ADR 0026, 2.5.2)
check("the journal and its heads live in <PORTAL_DB_NAME>_journal, everything else in the portal's database",
      store.col("journal").database.name == store.col("journal_heads").database.name == store.DB_NAME + "_journal"
      and store.col("users").database.name == store.DB_NAME and store.journal_db_name() == store.DB_NAME + "_journal")
if not REAL:                       # against a real MongoDB with its roles: test_store_mongodb.py
    import contextlib  # noqa: E402
    import io  # noqa: E402

    import db_init  # noqa: E402

    empty_database()
    client, name = store.db().client, store.DB_NAME
    old_journal, old_heads = client[name]["journal"], client[name]["journal_heads"]
    target = client[name + "_journal"]
    target.drop_collection(db_init.MARKER)

    def event(n, **fields):
        return {"_id": f"old-{n}", "at": store.parse_iso(f"2026-09-0{n}T10:00:00Z"), "user": "u", "action": "login",
                "category": "session", **fields}

    check("db_init: the journal's role may read and insert events, and move heads forward, in that database only",
          db_init.journal_privileges("x_journal") == [
              {"resource": {"db": "x_journal", "collection": "journal"}, "actions": ["find", "insert", "listIndexes"]},
              {"resource": {"db": "x_journal", "collection": "journal_heads"},
               "actions": ["find", "insert", "listIndexes", "update"]}])
    old_journal.insert_one(event(1))
    saved_copy, db_init._copy = db_init._copy, lambda target_collection, docs: []      # a copy that loses events
    try:
        db_init.move_journal(client, name)
        check("db_init: nothing is dropped when an event is missing after the copy", False)
    except RuntimeError as exc:
        check("db_init: nothing is dropped when an event is missing after the copy",
              old_journal.count_documents({}) == 1 and not target[db_init.MARKER].find_one({"_id": "moved"}), exc)
    finally:
        db_init._copy = saved_copy
    old_journal.delete_many({})
    secret = journal.key()
    first = journal._seal(event(1), "operator/session", 1, "", secret)
    second = journal._seal(event(2), "operator/session", 2, first["hash"], secret)
    old_journal.insert_many([first, second, event(3), journal._seal(event(4), "t-x/session", 1, "", secret)])
    old_heads.insert_many([{"_id": "operator/session", "seq": 2, "hash": second["hash"]},
                           {"_id": "t-x/session", "seq": 1, "hash": "h"}])
    # a newer replica already wrote seq 1 of t-x/session in the journal's database: the old one collides
    target["journal"].insert_one(journal._seal(event(5), "t-x/session", 1, "", secret))
    target["journal_heads"].insert_one({"_id": "t-x/session", "seq": 1, "hash": "newer"})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        moved_ids = db_init.move_journal(client, name)
    check("db_init: the journal moves to its own database once, the old collections dropped, the move marked",
          target["journal"].count_documents({}) == 5 and "journal" not in client[name].list_collection_names()
          and "journal_heads" not in client[name].list_collection_names()
          and target[db_init.MARKER].find_one({"_id": "moved"})["events"] == 4, out.getvalue())
    check("db_init: sealed events keep their seal; unsealed ones and a (chain, seq) collision go in unsealed",
          sorted(moved_ids) == ["old-3", "old-4"] and target["journal"].find_one({"_id": "old-1"})["hash"] == first["hash"]
          and "seq" not in target["journal"].find_one({"_id": "old-4"}), moved_ids)
    check("db_init: a chain's head already further on in the journal's database is kept",
          target["journal_heads"].find_one({"_id": "t-x/session"})["hash"] == "newer"
          and target["journal_heads"].find_one({"_id": "operator/session"})["seq"] == 2)
    target["journal"].insert_one(event(6))               # inserted unsealed by someone else, not moved
    with contextlib.redirect_stdout(out):
        db_init.journal_upkeep(store, journal, moved_ids)
    check("db_init: only the events it moved are sealed; an event inserted unsealed by anyone else is left and warned",
          all(target["journal"].find_one({"_id": i}).get("sealed") == "upgrade" for i in moved_ids)
          and "seq" not in target["journal"].find_one({"_id": "old-6"})
          and "1 event(s) of the journal are not sealed" in out.getvalue()
          and journal.verify("t-x/session")["ok"] and journal.verify("operator/session")["problem"]["kind"] == "unsealed",
          out.getvalue())
    old_journal.insert_one(event(7))                     # an old replica writing after the move
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        again = db_init.move_journal(client, name)
    check("db_init: a journal that reappears in the portal's database after the move is reported, neither moved "
          "nor sealed", again == [] and old_journal.count_documents({}) == 1 and "WARNING" in out.getvalue()
          and f"{name}.journal reappeared" in out.getvalue() and not target["journal"].find_one({"_id": "old-7"}),
          out.getvalue())
    client[name].drop_collection("journal")
    empty_database()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
