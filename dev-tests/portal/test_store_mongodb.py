"""
The portal's database layer against a real MongoDB, as installations run it: the user made by db_init.py
(the portal-db-init service) and what it may do, test_store.py run again as that user, and MongoDB's TTL
monitor deleting expired documents. mongomock cannot show any of this.

Needs PORTAL_TEST_MONGO_URI: a MongoDB 7 connection with the right to create users (root). The continuous
integration starts a mongo:7 service container for it (.github/workflows/dev-tests.yml, job "database").
Everything made here (a database and a user named devtest_*) is removed at the end.

  PORTAL_TEST_MONGO_URI='mongodb://root:pw@localhost:27017/?authSource=admin' python dev-tests/portal/test_store_mongodb.py
"""
import os
import secrets
import subprocess
import sys
import time
from datetime import timedelta
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
    check("db_init: readWrite on the portal's database, nothing else", roles == [{"role": "readWrite", "db": NAME}], roles)

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
    check("… roles unchanged", root[NAME].command("usersInfo", USER)["users"][0]["roles"] == roles)
    check("db_init refuses the official database", db_init(PORTAL_DB_PASSWORD=second, PORTAL_DB_NAME="resolver_ce").returncode == 1)
    check("db_init refuses an empty password", db_init(PORTAL_DB_PASSWORD="").returncode == 1)
    check("db_init without MONGO_URI fails", db_init(PORTAL_DB_PASSWORD=second, MONGO_URI="").returncode == 1)

    # ---------------------------------------------------------------- test_store.py as the portal's user
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTAL_DB_")}
    env.update(PORTAL_DB_URI=user_uri(second), PORTAL_DB_NAME=NAME)
    store_run = subprocess.run([sys.executable, os.path.join(HERE, "test_store.py")], env=env,
                               capture_output=True, text=True, timeout=600)
    lines = store_run.stdout.splitlines()
    for line in lines:
        if line.startswith(("PASS ", "FAIL ")):
            print(line[:5] + "real MongoDB: " + line[5:])
    passed = sum(line.startswith("PASS ") for line in lines)
    check("test_store.py passes on a real MongoDB as the portal's user",
          store_run.returncode == 0 and passed > 50, store_run.stderr[-800:])

    # ---------------------------------------------------------------- MongoDB's TTL monitor
    sys.path[:0] = [PORTAL]
    os.environ.update(PORTAL_DB_URI=user_uri(second), PORTAL_DB_NAME=NAME)
    import store  # noqa: E402

    now = store.now()
    store.col("login_failures").insert_one({"_id": "ttl-probe", "key": "user:ttl", "at": now - timedelta(minutes=20)})
    store.col("journal").insert_one({"_id": "ttl-probe", "at": now, "user": "x", "action": "login",
                                     "category": "session", "expiresAt": now - timedelta(minutes=1)})
    store.col("linkcheck_cache").insert_one({"_id": "ttl-probe", "result": {}, "expiresAt": now - timedelta(minutes=1)})
    store.col("journal").insert_one({"_id": "ttl-keep", "at": now, "user": "x", "action": "create", "category": "record"})
    deadline = time.monotonic() + 150                     # the monitor runs every 60 seconds
    left = 3
    while time.monotonic() < deadline:
        left = sum(store.col(c).count_documents({"_id": "ttl-probe"}) for c in ("login_failures", "journal", "linkcheck_cache"))
        if not left:
            break
        time.sleep(5)
    check("TTL: expired sign-in failures, journal events and cached results are deleted by MongoDB", left == 0, left)
    check("TTL: an event without expiresAt is kept", store.col("journal").count_documents({"_id": "ttl-keep"}) == 1)
finally:
    try:
        root[NAME].command("dropUser", USER)
    except OperationFailure:
        pass
    root.drop_database(NAME)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
