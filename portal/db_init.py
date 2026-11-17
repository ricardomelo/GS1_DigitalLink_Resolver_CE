"""
Creates, or brings up to date, the portal's own MongoDB user: readWrite on the portal's database, read on the
resolver's request log (resolver_log, Documentation/adr/0006-resolver-request-log.md) and the right to delete its events
(the role PRUNE_ROLE: the retention set in the portal, section 8 of the ADR), read and insert in the journal's database
"<PORTAL_DB_NAME>_journal" (the role JOURNAL_ROLE: journal_heads may also move forward; no event can be changed or
deleted, no index made), and nothing else (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.1;
Documentation/adr/0026-journal-integrity.md, section 2.5.2).

The journal's upkeep that needs more than inserting runs here, with the root user: the one-time move of the journal
from the portal's database into its own (move_journal(); the marker document journal_moved {_id: "moved"} in the
journal's database says it is done, and a journal collection that reappears in the portal's database afterwards is
reported, never moved), the indexes of both databases (store.db()), a change of retention (journal.apply_retention())
and the sealing of the events it moved without a seal (journal.seal_unsealed(ids)).

Run by the one-shot Compose service portal-db-init before the portal starts, on every "docker compose up",
so a new installation, an existing one and a restored one all end with the user and the password of .env.
MongoDB's own /docker-entrypoint-initdb.d scripts run only on an empty volume and cannot serve the last two.

Reads MONGO_URI (the root connection the official services use), PORTAL_DB_NAME, PORTAL_DB_USERNAME and
PORTAL_DB_PASSWORD. Prints what it did, never a password. Exit status 0 on success.

  docker compose run --rm portal-db-init          # by hand, e.g. after changing PORTAL_DB_PASSWORD
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from pymongo.errors import BulkWriteError, PyMongoError

LOG_DB = "resolver_log"                                   # written by the resolver, read by the portal
PRUNE_ROLE = "requestLogPrune"                            # deletes events of resolver_log.requests, nothing else
PRUNE_PRIVILEGES = [{"resource": {"db": LOG_DB, "collection": "requests"}, "actions": ["remove"]}]
RESERVED = {"admin", "local", "config", "resolver_ce", LOG_DB}     # never the portal's own database
JOURNAL_ROLE = "journalAppend"                            # defined in the journal's database
JOURNAL_COLLECTIONS = ("journal", "journal_heads")        # as store.JOURNAL_COLLECTIONS
MARKER = "journal_moved"                                  # {_id: "moved", at, events}: the move is done
SEAL_FIELDS = ("chain", "seq", "prev", "hash", "mac", "kid", "sealed")


def journal_privileges(journal_db: str) -> list[dict]:
    """Events: read and insert only. Heads: also updated, since each moves forward with its chain."""
    return [{"resource": {"db": journal_db, "collection": "journal"}, "actions": ["find", "insert", "listIndexes"]},
            {"resource": {"db": journal_db, "collection": "journal_heads"},
             "actions": ["find", "insert", "listIndexes", "update"]}]


def ensure_role(database, role: str, privileges: list[dict]) -> None:
    if database.command("rolesInfo", role)["roles"]:
        database.command("updateRole", role, privileges=privileges, roles=[])
    else:
        database.command("createRole", role, privileges=privileges, roles=[])


def _copy(target, docs: list[dict]) -> list:
    """Inserts docs into target; an event already there (same _id) is skipped, one whose (chain, seq) is taken by
    another event goes in without its seal (the verification reports it). Returns the _ids inserted unsealed."""
    if not docs:
        return []
    unsealed = [d["_id"] for d in docs if "seq" not in d]
    try:
        target.insert_many(docs, ordered=False)
        return unsealed
    except BulkWriteError as exc:
        errors = exc.details.get("writeErrors", [])
        if any(err.get("code") != 11000 for err in errors):
            raise
    for err in errors:
        doc = docs[err["index"]]
        if target.find_one({"_id": doc["_id"]}, {"_id": 1}):
            continue                                       # moved by an earlier, interrupted run
        stripped = {k: v for k, v in doc.items() if k not in SEAL_FIELDS}
        target.insert_one(stripped)
        unsealed.append(doc["_id"])
    return unsealed


def _missing(source, target) -> int:
    """How many documents of source are not in target, leaving out events that expire within the hour (MongoDB's TTL
    monitor may delete them from the copy at any moment)."""
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    lasting = {"$or": [{"expiresAt": {"$exists": False}}, {"expiresAt": {"$gt": soon}}]}
    missing, batch = 0, []
    for doc in list(source.find(lasting, {"_id": 1})) + [None]:
        if doc is not None:
            batch.append(doc["_id"])
        if batch and (doc is None or len(batch) >= 1000):
            missing += len(batch) - target.count_documents({"_id": {"$in": batch}})
            batch = []
    return missing


def _copy_heads(target, docs: list[dict]) -> list:
    """Heads: a chain's head already in the journal's database stays when it is further on."""
    heads = target["journal_heads"]
    for doc in docs:
        if heads.find_one({"_id": doc["_id"]}, {"_id": 1}) is None:
            heads.insert_one(doc)
        else:
            heads.update_one({"_id": doc["_id"], "seq": {"$lt": doc.get("seq", 0)}},
                             {"$set": {k: v for k, v in doc.items() if k != "_id"}})
    return []


def move_journal(client, name: str) -> list:
    """Moves journal and journal_heads from the portal's database into the journal's, once (the indexes of the
    journal's database already made). Returns the _ids of the events moved without a seal, for the caller to seal;
    prints what it did. Nothing is dropped unless every document is found in the journal's database."""
    source, target = client[name], client[f"{name}_journal"]
    present = [c for c in JOURNAL_COLLECTIONS if c in source.list_collection_names()]
    if target[MARKER].find_one({"_id": "moved"}):
        for collection in present:
            print(f"portal-db-init: WARNING: {name}.{collection} reappeared after the journal moved to {name}_journal "
                  f"({source[collection].estimated_document_count()} document(s)); it is left where it is, neither "
                  f"moved nor sealed (Documentation/adr/0026-journal-integrity.md, section 2.5.2).")
        return []
    unsealed, moved = [], 0
    for collection in present:
        copy = (lambda docs: _copy(target["journal"], docs)) if collection == "journal" else \
               (lambda docs: _copy_heads(target, docs))
        batch = []
        for doc in source[collection].find():
            batch.append(doc)
            if len(batch) >= 1000:
                unsealed += copy(batch)
                batch = []
        unsealed += copy(batch)
        missing = _missing(source[collection], target[collection])
        if missing:
            raise RuntimeError(f"{missing} document(s) of {name}.{collection} not found in {name}_journal after the "
                               f"copy; nothing was dropped")
        if collection == "journal":
            moved = source[collection].estimated_document_count()
    for collection in present:
        source[collection].drop()
    target[MARKER].insert_one({"_id": "moved", "at": datetime.now(timezone.utc), "events": moved})
    if present:
        print(f"portal-db-init: journal moved to {name}_journal ({moved} event(s)).")
    return unsealed


def connect_store(root_uri: str):
    """store.py and journal.py connected with the root user: store.db() makes the indexes of both databases."""
    os.environ["PORTAL_DB_URI"] = root_uri
    import journal                                         # reads the environment when called
    import store
    store.reset()
    store.db()
    return store, journal


def journal_upkeep(store, journal, ids: list) -> None:
    """Retention and the sealing of the events moved without a seal; a warning for any other unsealed event."""
    changed = journal.apply_retention()
    if sum(changed.values()):
        print(f"portal-db-init: journal retention applied ({sum(changed.values())} event(s) updated).")
    sealed = journal.seal_unsealed(ids=ids) if ids else 0
    if sealed:
        print(f"portal-db-init: {sealed} event(s) sealed in their chains.")
    left = store.col("journal").count_documents({"seq": {"$exists": False}})
    if left:
        print(f"portal-db-init: WARNING: {left} event(s) of the journal are not sealed and were not moved here; "
              f"the verification reports them (Documentation/adr/0026-journal-integrity.md).")


def main() -> int:
    root_uri = os.environ.get("MONGO_URI", "").strip()
    name = os.environ.get("PORTAL_DB_NAME", "").strip() or "resolver_portal"
    username = os.environ.get("PORTAL_DB_USERNAME", "").strip() or "resolver_portal"
    password = os.environ.get("PORTAL_DB_PASSWORD", "")
    if not root_uri:
        print("portal-db-init: MONGO_URI is not set.", file=sys.stderr)
        return 1
    if not password:
        print("portal-db-init: PORTAL_DB_PASSWORD is not set.", file=sys.stderr)
        return 1
    if name in RESERVED:
        print(f"portal-db-init: PORTAL_DB_NAME may not be {name!r}.", file=sys.stderr)
        return 1
    journal_db = f"{name}_journal"
    roles = [{"role": "readWrite", "db": name}, {"role": "read", "db": LOG_DB}, {"role": PRUNE_ROLE, "db": LOG_DB},
             {"role": JOURNAL_ROLE, "db": journal_db}]
    timeout = int(os.environ.get("PORTAL_DB_INIT_TIMEOUT_MS", "60000"))   # the database may still be starting
    try:
        with MongoClient(root_uri, serverSelectionTimeoutMS=timeout, appname="portal-db-init") as client:
            ensure_role(client[LOG_DB], PRUNE_ROLE, PRUNE_PRIVILEGES)
            ensure_role(client[journal_db], JOURNAL_ROLE, journal_privileges(journal_db))
            store, journal = connect_store(root_uri)
            unsealed = move_journal(client, name)
            database = client[name]
            exists = database.command("usersInfo", username)["users"]
            if exists:
                database.command("updateUser", username, pwd=password, roles=roles)
                print(f"portal-db-init: user {username} of database {name} brought up to date.")
            else:
                database.command("createUser", username, pwd=password, roles=roles)
                print(f"portal-db-init: user {username} created for database {name}.")
        journal_upkeep(store, journal, unsealed)
    except (PyMongoError, RuntimeError) as exc:
        print(f"portal-db-init: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
