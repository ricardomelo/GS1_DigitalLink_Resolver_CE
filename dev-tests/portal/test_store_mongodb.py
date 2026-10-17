"""
The portal's database layer against a real MongoDB, as installations run it: the user made by db_init.py
(the portal-db-init service) and what it may do, test_store.py and test_jobs.py run again as that user,
worker.py as real processes sharing the queue (test_worker_processes.py), and MongoDB's TTL monitor deleting
expired documents. mongomock cannot show any of this.

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
USER = f"devtest_user_{os.getpid()}"
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

    # ---------------------------------------------------------------- the user made by db_init.py
    run = db_init(PORTAL_DB_PASSWORD=first)
    check("db_init: user created, exit status 0", run.returncode == 0 and "created" in run.stdout, run.stderr[-300:])
    check("db_init: the password is never printed", first not in run.stdout + run.stderr)
    roles = root[NAME].command("usersInfo", USER)["users"][0]["roles"]
    check("db_init: readWrite on the portal's database, read on the request log and deleting its events, nothing else",
          sorted(roles, key=lambda r: (r["db"], r["role"])) == sorted(
              [{"role": "readWrite", "db": NAME}, {"role": "read", "db": "resolver_log"},
               {"role": "requestLogPrune", "db": "resolver_log"}], key=lambda r: (r["db"], r["role"])), roles)
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

    run = db_init(PORTAL_DB_PASSWORD=second)
    check("db_init again with a new password: user brought up to date",
          run.returncode == 0 and "up to date" in run.stdout, run.stderr[-300:])
    check("… the old password no longer works, the new one does", not can_sign_in(first) and can_sign_in(second))
    # MongoDB keeps roles as a set: usersInfo may list them in another order after updateUser
    check("… roles unchanged", sorted(root[NAME].command("usersInfo", USER)["users"][0]["roles"], key=lambda r: r["db"])
          == sorted(roles, key=lambda r: r["db"]))
    check("db_init refuses the official database", db_init(PORTAL_DB_PASSWORD=second, PORTAL_DB_NAME="resolver_ce").returncode == 1)
    check("db_init refuses the request log's database", db_init(PORTAL_DB_PASSWORD=second, PORTAL_DB_NAME="resolver_log").returncode == 1)
    check("db_init refuses an empty password", db_init(PORTAL_DB_PASSWORD="").returncode == 1)
    check("db_init without MONGO_URI fails", db_init(PORTAL_DB_PASSWORD=second, MONGO_URI="").returncode == 1)

    # ---------------------------------------------------------------- programs run again as the portal's user
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTAL_DB_")}
    env.update(PORTAL_DB_URI=user_uri(second), PORTAL_DB_NAME=NAME)
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
    root["resolver_log"]["requests"].delete_one({"_id": "probe-event"})

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
