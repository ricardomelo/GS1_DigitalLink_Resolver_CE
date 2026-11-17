"""
The portal's database layer against a real MongoDB, as installations run it: the user made by db_init.py
(the portal-db-init service) and what it may do, the journal moved to a database of its own where that user may only
read and insert (ADR 0026 section 2.5.2), test_store.py and test_jobs.py run again as that user,
worker.py as real processes sharing the queue (test_worker_processes.py), the users db_init.py makes for the resolver
and the data entry API and what each may do (ADR 0030), and MongoDB's TTL monitor deleting expired documents.
mongomock cannot show any of this.

Needs PORTAL_TEST_MONGO_URI: a MongoDB 7 connection with the right to create users (root). The continuous
integration starts a mongo:7 service container for it (.github/workflows/dev-tests.yml, job "database").
Everything made here (a database and a user named devtest_*) is removed at the end.

  PORTAL_TEST_MONGO_URI='mongodb://root:pw@localhost:27017/?authSource=admin' python dev-tests/portal/test_store_mongodb.py
"""
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.errors import OperationFailure

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
ROOT_URI = os.environ.get("PORTAL_TEST_MONGO_URI", "").strip()
if not ROOT_URI:
    print("SKIP: PORTAL_TEST_MONGO_URI is not set (a real MongoDB is needed)")
    sys.exit(0)
HOST = os.environ.get("PORTAL_TEST_MONGO_HOST", "localhost:27017")
NAME = f"devtest_portal_{os.getpid()}"
JOURNAL_DB = f"{NAME}_journal"
USER = f"devtest_user_{os.getpid()}"
RESOLVER_USER = f"devtest_resolver_{os.getpid()}"       # the services' users (ADR 0030), in the admin database
ENTRY_USER = f"devtest_entry_{os.getpid()}"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def db_init(**env):
    """Runs portal/db_init.py as the portal-db-init service does."""
    base = {k: v for k, v in os.environ.items() if not k.startswith(("PORTAL_DB_", "MONGO_"))}
    base.update(MONGO_URI=ROOT_URI, PORTAL_DB_NAME=NAME, PORTAL_DB_USERNAME=USER, PORTAL_DB_INIT_TIMEOUT_MS="10000")
    base.update(env)
    return subprocess.run([sys.executable, "db_init.py"], cwd=PORTAL, env=base, capture_output=True, text=True)


def user_uri(password: str) -> str:
    return f"mongodb://{quote_plus(USER)}:{quote_plus(password)}@{HOST}/{NAME}?authSource={NAME}"


def service_uri(user: str, password: str) -> str:
    return f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{HOST}/?authSource=admin"


def refused(label: str, attempt) -> None:
    try:
        attempt()
        check(label, False)
    except OperationFailure as exc:
        check(label, exc.code == 13, exc.code)


def can_sign_in(password: str) -> bool:
    try:
        with MongoClient(user_uri(password), serverSelectionTimeoutMS=5000) as client:
            client[NAME].command("ping")
            client[NAME]["probe"].find_one()
        return True
    except OperationFailure:
        return False


root = MongoClient(ROOT_URI, serverSelectionTimeoutMS=20000)
try:
    first, second = secrets.token_hex(12), secrets.token_hex(12)

    # an installation of an earlier version: the journal in the portal's database (written by the root user here)
    sys.path[:0] = [PORTAL]
    import journal as journal_module  # noqa: E402  (its sealing functions; no connection is made by them)
    seal_key = os.environ.get("PORTAL_JOURNAL_KEY", "").encode() or None
    old_sealed = journal_module._seal({"_id": "old-sealed", "at": datetime(2026, 9, 1), "user": "u", "action": "login",
                                       "category": "session"}, "operator/session", 1, "", seal_key)
    root[NAME]["journal"].insert_many([old_sealed, {"_id": "old-unsealed", "at": datetime(2026, 9, 2), "user": "u",
                                                    "action": "logout", "category": "session"}])
    root[NAME]["journal_heads"].insert_one({"_id": "operator/session", "seq": 1, "hash": old_sealed["hash"]})

    # ---------------------------------------------------------------- the user made by db_init.py
    run = db_init(PORTAL_DB_PASSWORD=first)
    check("db_init: user created, exit status 0", run.returncode == 0 and "created" in run.stdout, run.stderr[-300:])
    check("db_init: the password is never printed", first not in run.stdout + run.stderr)
    roles = root[NAME].command("usersInfo", USER)["users"][0]["roles"]
    check("db_init: readWrite on the portal's database, read on the request log and deleting its events, nothing else",
          sorted(roles, key=lambda r: (r["db"], r["role"])) == sorted(
              [{"role": "readWrite", "db": NAME}, {"role": "read", "db": "resolver_log"},
               {"role": "requestLogPrune", "db": "resolver_log"}, {"role": "journalAppend", "db": JOURNAL_DB}],
              key=lambda r: (r["db"], r["role"])), roles)
    append = root[JOURNAL_DB].command("rolesInfo", "journalAppend", showPrivileges=True)["roles"]
    check("db_init: the journal's role reads and inserts events, and moves heads forward, nothing else",
          append and sorted((p["resource"]["collection"], sorted(p["actions"])) for p in append[0]["privileges"])
          == [("journal", ["find", "insert", "listIndexes"]), ("journal_heads", ["find", "insert", "listIndexes", "update"])]
          and all(p["resource"]["db"] == JOURNAL_DB for p in append[0]["privileges"]), append)
    moved = {d["_id"]: d for d in root[JOURNAL_DB]["journal"].find()}
    check("db_init: the journal of an earlier version moved to its own database, the old collections dropped",
          set(moved) == {"old-sealed", "old-unsealed"} and "journal" not in root[NAME].list_collection_names()
          and "journal_heads" not in root[NAME].list_collection_names()
          and root[JOURNAL_DB]["journal_moved"].find_one({"_id": "moved"})["events"] == 2, (moved, run.stdout))
    check("db_init: a sealed event keeps its seal; the unsealed one is sealed after it, marked so",
          moved["old-sealed"]["hash"] == old_sealed["hash"] and moved["old-unsealed"].get("seq") == 2
          and moved["old-unsealed"].get("sealed") == "upgrade"
          and root[JOURNAL_DB]["journal_heads"].find_one({"_id": "operator/session"})["seq"] == 2, moved)
    indexes = list(root[JOURNAL_DB]["journal"].list_indexes())
    check("db_init: the journal's indexes made in its database (the unique (chain, seq) and the TTL on expiresAt only)",
          any(i.get("unique") and list(i["key"]) == ["chain", "seq"] for i in indexes)
          and [list(i["key"]) for i in indexes if "expireAfterSeconds" in i] == [["expiresAt"]], indexes)
    prune = root["resolver_log"].command("rolesInfo", "requestLogPrune", showPrivileges=True)["roles"]
    check("db_init: the role deletes events of resolver_log.requests only",
          prune and [(p["resource"], sorted(p["actions"])) for p in prune[0]["privileges"]]
          == [({"db": "resolver_log", "collection": "requests"}, ["remove"])], prune)
    # the request log (ADR 0006): written by the resolver (root here), read by the portal
    root["resolver_log"]["requests"].insert_one({"_id": "probe-event", "t": datetime(2026, 10, 14), "cp": "7898357410015",
                                                 "o": "redirect", "dev": "mobile", "ms": 5})

    with MongoClient(user_uri(first), serverSelectionTimeoutMS=5000) as client:
        own = client[NAME]["probe"]
        own.insert_one({"_id": 1})
        check("portal user: reads and writes its own database", own.find_one({"_id": 1}) == {"_id": 1})
        own.create_index("x", expireAfterSeconds=60)
        check("portal user: may make indexes (TTL included)", any(i.get("expireAfterSeconds") == 60 for i in own.list_indexes()))
        for other in ("resolver_ce", "admin"):
            try:
                client[other]["anything"].find_one()
                check(f"portal user: cannot read the {other} database", False)
            except OperationFailure as exc:
                check(f"portal user: cannot read the {other} database", exc.code == 13, exc.code)
        log = client["resolver_log"]["requests"]
        check("portal user: reads the request log",
              log.find_one({"_id": "probe-event"}, {"_id": 1}) == {"_id": "probe-event"})
        check("portal user: the request log's queries work (anchored regex, $not, $group)",
              log.count_documents({"cp": {"$regex": "^(?:7898357)"}}) >= 1
              and log.count_documents({"_id": "probe-event", "cp": {"$exists": True, "$not": re.compile("^(?:789111)")}}) == 1
              and any(g["n"] >= 1 for g in log.aggregate([{"$match": {"_id": "probe-event"}},
                                                           {"$group": {"_id": {"o": "$o", "ai": "$ai"}, "n": {"$sum": 1},
                                                                       "ms": {"$max": "$ms"}}}])))
        try:
            log.insert_one({"_id": "forged"})
            check("portal user: cannot write the request log", False)
        except OperationFailure as exc:
            check("portal user: cannot write the request log", exc.code == 13, exc.code)
        try:
            log.update_one({"_id": "probe-event"}, {"$set": {"o": "forged"}})
            check("portal user: cannot change an event of the request log", False)
        except OperationFailure as exc:
            check("portal user: cannot change an event of the request log", exc.code == 13, exc.code)
        root["resolver_log"]["requests"].insert_one({"_id": "old-event", "t": datetime(2026, 1, 1), "cp": "7898357"})
        check("portal user: deletes old events of the request log (the retention set in the portal)",
              log.delete_many({"t": {"$lt": datetime(2026, 2, 1)}}).deleted_count == 1
              and log.find_one({"_id": "probe-event"}) is not None)
        counts = root["resolver_log"]["request_counts"]
        for ms in (3, 9):       # the resolver's upsert, twice (web_server/src/request_log.py; ADR 0006, section 11)
            counts.update_one({"_id": "probe-count"}, {"$inc": {"n": 1, "ms": ms}, "$max": {"msMax": ms},
                                                       "$setOnInsert": {"b": datetime(2026, 10, 14), "o": "redirect",
                                                                        "dev": "automated", "cp": "7898357410015"}},
                              upsert=True)
        grouped = list(client["resolver_log"]["request_counts"].aggregate([
            {"$match": {"_id": "probe-count"}},
            {"$group": {"_id": {"o": "$o", "dev": "$dev"}, "n": {"$sum": "$n"}, "ms": {"$sum": "$ms"},
                        "max": {"$max": "$msMax"}}}]))
        check("request counts: the resolver's upsert adds up; the portal user reads and groups them",
              [(g["n"], g["ms"], g["max"]) for g in grouped] == [(2, 12, 9)], grouped)
        root["resolver_log"]["requests"].insert_one({"_id": "bot-event", "t": datetime(2026, 1, 2), "dev": "automated"})
        check("portal user: deletes the automated events and those without a key of counted days",
              log.delete_many({"$and": [{"t": {"$lt": datetime(2026, 2, 1)}},
                                        {"$or": [{"dev": "automated"}, {"ai": {"$exists": False}}]}]}).deleted_count == 1)
        counts.delete_one({"_id": "probe-count"})
        try:
            client["resolver_log"]["other"].delete_many({})
            check("portal user: deletes nothing else in resolver_log", False)
        except OperationFailure as exc:
            check("portal user: deletes nothing else in resolver_log", exc.code == 13, exc.code)
        try:
            client["resolver_ce"]["resolver"].insert_one({"_id": "x"})
            check("portal user: cannot write the resolver's records", False)
        except OperationFailure as exc:
            check("portal user: cannot write the resolver's records", exc.code == 13, exc.code)
        try:
            client[NAME].command("createUser", "intruder", pwd="intruder-password", roles=["root"])
            check("portal user: cannot create users", False)
        except OperationFailure as exc:
            check("portal user: cannot create users", exc.code == 13, exc.code)
        events, heads = client[JOURNAL_DB]["journal"], client[JOURNAL_DB]["journal_heads"]
        events.insert_one({"_id": "probe", "at": datetime(2026, 10, 14), "user": "u", "action": "login",
                           "category": "session"})
        check("portal user: inserts and reads journal events", events.find_one({"_id": "probe"})["action"] == "login"
              and events.count_documents({"category": "session"}) >= 1)
        heads.update_one({"_id": "probe/session", "seq": {"$lt": 1}}, {"$set": {"seq": 1, "hash": "h"}}, upsert=True)
        check("portal user: moves a chain's head forward", heads.find_one({"_id": "probe/session"})["seq"] == 1)
        refusals = {
            "change an event": lambda: events.update_one({"_id": "probe"}, {"$set": {"user": "forged"}}),
            "replace an event": lambda: events.replace_one({"_id": "probe"}, {"at": datetime(2026, 1, 1)}),
            "delete an event": lambda: events.delete_one({"_id": "probe"}),
            "drop the journal": lambda: events.drop(),
            "make an index (a TTL could delete every event)": lambda: events.create_index("at", expireAfterSeconds=1),
            "change the collection (collMod)": lambda: client[JOURNAL_DB].command("collMod", "journal"),
            "delete a head": lambda: heads.delete_one({"_id": "probe/session"}),
            "write the move's marker": lambda: client[JOURNAL_DB]["journal_moved"].insert_one({"_id": "x"}),
        }
        for what, attempt in refusals.items():
            try:
                attempt()
                check(f"portal user: cannot {what} in the journal's database", False)
            except OperationFailure as exc:
                check(f"portal user: cannot {what} in the journal's database", exc.code == 13, exc.code)
        check("… the event is unchanged", events.find_one({"_id": "probe"})["user"] == "u")
        root[JOURNAL_DB]["journal"].delete_one({"_id": "probe"})
        root[JOURNAL_DB]["journal_heads"].delete_one({"_id": "probe/session"})

    root[NAME]["journal"].insert_one({"_id": "late", "at": datetime(2026, 9, 3), "user": "u", "action": "login",
                                      "category": "session"})          # an old replica writing after the move
    run = db_init(PORTAL_DB_PASSWORD=second)
    check("db_init again with a new password: user brought up to date",
          run.returncode == 0 and "up to date" in run.stdout, run.stderr[-300:])
    check("db_init: a journal that reappears in the portal's database is reported and left, neither moved nor sealed",
          "WARNING" in run.stdout and f"{NAME}.journal reappeared" in run.stdout
          and root[NAME]["journal"].count_documents({}) == 1 and not root[JOURNAL_DB]["journal"].find_one({"_id": "late"}),
          run.stdout)
    root[NAME].drop_collection("journal")
    for collection in ("journal", "journal_heads"):     # test_store.py below starts from an empty journal
        root[JOURNAL_DB][collection].delete_many({})
    check("… the old password no longer works, the new one does", not can_sign_in(first) and can_sign_in(second))
    # MongoDB keeps roles as a set: usersInfo may list them in another order after updateUser
    # (two roles share the database resolver_log: ordered by database and role, never by database alone)
    check("… roles unchanged", sorted(root[NAME].command("usersInfo", USER)["users"][0]["roles"],
                                      key=lambda r: (r["db"], r["role"])) == sorted(roles, key=lambda r: (r["db"], r["role"])))
    check("db_init refuses the official database", db_init(PORTAL_DB_PASSWORD=second, PORTAL_DB_NAME="resolver_ce").returncode == 1)
    check("db_init refuses the request log's database", db_init(PORTAL_DB_PASSWORD=second, PORTAL_DB_NAME="resolver_log").returncode == 1)
    check("db_init refuses an empty password", db_init(PORTAL_DB_PASSWORD="").returncode == 1)
    check("db_init without MONGO_URI fails", db_init(PORTAL_DB_PASSWORD=second, MONGO_URI="").returncode == 1)

    # ---------------------------------------------------------------- the services' users (ADR 0030)
    resolver_pw, entry_pw = secrets.token_hex(12), secrets.token_hex(12)
    services = dict(RESOLVER_DB_USERNAME=RESOLVER_USER, RESOLVER_DB_PASSWORD=resolver_pw,
                    DATA_ENTRY_DB_USERNAME=ENTRY_USER, DATA_ENTRY_DB_PASSWORD=entry_pw)
    run = db_init(PORTAL_DB_PASSWORD=second, **services)
    check("db_init: the resolver's and the data entry API's users created, exit status 0",
          run.returncode == 0 and f"user {RESOLVER_USER} of the resolver service created" in run.stdout
          and f"user {ENTRY_USER} of the data entry service created" in run.stdout, (run.stdout[-400:], run.stderr[-300:]))
    check("db_init: their passwords never printed", resolver_pw not in run.stdout + run.stderr
          and entry_pw not in run.stdout + run.stderr)
    for user, role in ((RESOLVER_USER, "resolverService"), (ENTRY_USER, "dataEntryService")):
        info = root["admin"].command("usersInfo", user)["users"]
        check(f"db_init: {role}'s user in the admin database with that role only",
              info and info[0]["roles"] == [{"role": role, "db": "admin"}], info)
    root["resolver_ce"]["gs1resolver"].insert_one({"_id": "devtest-probe", "data": []})
    root[NAME]["settings"].insert_one({"_id": "devtest-probe", "value": 1})
    root[NAME]["users"].insert_one({"_id": "devtest-probe", "hash": "x"})
    with MongoClient(service_uri(RESOLVER_USER, resolver_pw), serverSelectionTimeoutMS=5000) as client:
        check("resolver user: reads the records", client["resolver_ce"]["gs1resolver"].find_one({"_id": "devtest-probe"}))
        for collection in ("tenants", "domains", "branding", "forwarding_rules"):   # refused: OperationFailure
            list(client[NAME][collection].find({}, {"_id": 1}).limit(1))
        check("resolver user: reads the portal's settings, tenants, domains, branding and forwarding rules",
              client[NAME]["settings"].find_one({"_id": "devtest-probe"}) is not None)
        log = client["resolver_log"]["requests"]
        log.create_index([("t", -1)])
        log.create_index([("expiresAt", 1)], expireAfterSeconds=0)
        log.insert_many([{"_id": "devtest-resolver-event", "t": datetime(2026, 10, 15)}], ordered=False)
        client["resolver_log"]["request_counts"].create_index([("b", -1)])
        client["resolver_log"]["request_counts"].update_one(
            {"_id": "devtest-count"}, {"$inc": {"n": 1}, "$max": {"msMax": 3}, "$setOnInsert": {"o": "redirect"}},
            upsert=True)
        check("resolver user: writes the request log as the resolver does (indexes, insert_many, the counts' upsert)",
              root["resolver_log"]["requests"].find_one({"_id": "devtest-resolver-event"}) is not None
              and root["resolver_log"]["request_counts"].find_one({"_id": "devtest-count"})["n"] == 1)
        refused("resolver user: cannot read the portal's users", lambda: client[NAME]["users"].find_one())
        refused("resolver user: cannot read the portal's sessions", lambda: client[NAME]["sessions"].find_one())
        refused("resolver user: cannot read the journal", lambda: client[JOURNAL_DB]["journal"].find_one())
        refused("resolver user: cannot write the records",
                lambda: client["resolver_ce"]["gs1resolver"].insert_one({"_id": "devtest-forged"}))
        refused("resolver user: cannot change the portal's settings",
                lambda: client[NAME]["settings"].update_one({"_id": "devtest-probe"}, {"$set": {"value": 2}}))
        refused("resolver user: cannot delete events of the request log",
                lambda: log.delete_many({"_id": "devtest-resolver-event"}))
        refused("resolver user: cannot create users",
                lambda: client["admin"].command("createUser", "intruder", pwd="intruder-password", roles=["root"]))
    with MongoClient(service_uri(ENTRY_USER, entry_pw), serverSelectionTimeoutMS=5000) as client:
        records = client["resolver_ce"]["gs1resolver"]
        records.insert_one({"_id": "devtest-entry", "data": []})
        records.update_one({"_id": "devtest-entry"}, {"$set": {"data": [1]}})
        found = records.find_one({"_id": "devtest-entry"})
        records.delete_one({"_id": "devtest-entry"})
        check("data entry user: reads, inserts, changes and deletes records",
              found == {"_id": "devtest-entry", "data": [1]} and root["resolver_ce"]["gs1resolver"].find_one(
                  {"_id": "devtest-entry"}) is None, found)
        refused("data entry user: cannot read the portal's database", lambda: client[NAME]["settings"].find_one())
        refused("data entry user: cannot write the request log",
                lambda: client["resolver_log"]["requests"].insert_one({"_id": "devtest-forged"}))
        refused("data entry user: cannot create users",
                lambda: client["admin"].command("createUser", "intruder", pwd="intruder-password", roles=["root"]))
    newer = secrets.token_hex(12)
    run = db_init(PORTAL_DB_PASSWORD=second, **{**services, "RESOLVER_DB_PASSWORD": newer})

    def service_signs_in(password: str) -> bool:
        try:
            with MongoClient(service_uri(RESOLVER_USER, password), serverSelectionTimeoutMS=5000) as client:
                client["resolver_ce"]["gs1resolver"].find_one()
            return True
        except OperationFailure:
            return False
    check("db_init again: the resolver's user takes the new password of .env, the old one no longer works",
          run.returncode == 0 and "brought up to date" in run.stdout and service_signs_in(newer)
          and not service_signs_in(resolver_pw), run.stdout[-300:])
    check("db_init: MongoDB's root user refused as a service's user, nothing changed",
          db_init(PORTAL_DB_PASSWORD=second, RESOLVER_DB_USERNAME=re.sub(r"^mongodb://([^:]+):.*$", r"\1", ROOT_URI),
                  RESOLVER_DB_PASSWORD="x" * 12).returncode == 1 and service_signs_in(newer))

    # ---------------------------------------------------------------- programs run again as the portal's user
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTAL_DB_")}
    env.update(PORTAL_DB_URI=user_uri(second), PORTAL_DB_NAME=NAME, DEV_TESTS_DB_ADMIN_URI=ROOT_URI)
    for program, minimum in (("test_store.py", 50), ("test_jobs.py", 60), ("test_worker_processes.py", 10)):
        run = subprocess.run([sys.executable, os.path.join(HERE, program)], env=env, capture_output=True, text=True,
                             timeout=900)
        lines = run.stdout.splitlines()
        for line in lines:
            if line.startswith(("PASS ", "FAIL ")):
                print(line[:5] + "real MongoDB: " + line[5:])
        passed = sum(line.startswith("PASS ") for line in lines)
        check(f"{program} passes on a real MongoDB as the portal's user",
              run.returncode == 0 and passed > minimum, (passed, run.stderr[-800:]))

    # ---------------------------------------------------------------- MongoDB's TTL monitor
    sys.path[:0] = [PORTAL]
    os.environ.update(PORTAL_DB_URI=user_uri(second), PORTAL_DB_NAME=NAME)
    import store  # noqa: E402
    store.reset()                         # imported earlier through journal.py, before PORTAL_DB_NAME was set

    now = store.now()
    store.col("login_failures").insert_one({"_id": "ttl-probe", "key": "user:ttl", "at": now - timedelta(minutes=20)})
    store.col("journal").insert_one({"_id": "ttl-probe", "at": now, "user": "x", "action": "login",
                                     "category": "session", "expiresAt": now - timedelta(minutes=1)})
    store.col("linkcheck_cache").insert_one({"_id": "ttl-probe", "result": {}, "expiresAt": now - timedelta(minutes=1)})
    store.col("jobs").insert_one({"_id": "ttl-probe", "type": "linkcheck", "state": "finished", "created": now,
                                  "expiresAt": now - timedelta(minutes=1)})
    store.col("workers").insert_one({"_id": "ttl-probe", "seen": now - timedelta(seconds=store.WORKER_RECORD_SECONDS + 60)})
    store.col("journal").insert_one({"_id": "ttl-keep", "at": now, "user": "x", "action": "create", "category": "record"})
    deadline = time.monotonic() + 150                     # the monitor runs every 60 seconds
    probed = ("login_failures", "journal", "linkcheck_cache", "jobs", "workers")
    left = len(probed)
    while time.monotonic() < deadline:
        left = sum(store.col(c).count_documents({"_id": "ttl-probe"}) for c in probed)
        if not left:
            break
        time.sleep(5)
    check("TTL: expired sign-in failures, journal events, cached results, jobs and old worker announcements are "
          "deleted by MongoDB", left == 0, left)
    check("TTL: an event without expiresAt is kept", store.col("journal").count_documents({"_id": "ttl-keep"}) == 1)
finally:
    try:
        root[NAME].command("dropUser", USER)
    except OperationFailure:
        pass
    root.drop_database(NAME)
    root[JOURNAL_DB].command("dropAllRolesFromDatabase")
    root.drop_database(JOURNAL_DB)
    root["resolver_log"]["requests"].delete_many({"_id": {"$in": ["probe-event", "devtest-resolver-event"]}})
    root["resolver_log"]["request_counts"].delete_one({"_id": "devtest-count"})
    root["resolver_ce"]["gs1resolver"].delete_many({"_id": {"$regex": "^devtest-"}})
    for service_user in (RESOLVER_USER, ENTRY_USER):
        try:
            root["admin"].command("dropUser", service_user)
        except OperationFailure:
            pass
    for service_role in ("resolverService", "dataEntryService"):
        try:
            root["admin"].command("dropRole", service_role)
        except OperationFailure:
            pass

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
