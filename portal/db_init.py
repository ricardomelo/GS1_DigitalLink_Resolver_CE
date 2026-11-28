"""
Creates, or brings up to date, the portal's own MongoDB user: readWrite on the portal's database, read on the
resolver's request log (resolver_log, Documentation/adr/0006-resolver-request-log.md) and the right to delete its events
(the role PRUNE_ROLE: the retention set in the portal, section 8 of the ADR), read and insert in the journal's database
"<PORTAL_DB_NAME>_journal" (the role JOURNAL_ROLE: journal_heads may also move forward; no event can be changed or
deleted, no index made), and nothing else (Documentation/adr/0001-portal-state-in-mongodb.md, section 3.1;
Documentation/adr/0026-journal-integrity.md, section 2.5.2).

It also creates, or brings up to date, the users of the two official services, so that neither holds MongoDB's root
credentials (Documentation/adr/0030-least-privilege-services.md), both in the admin database with a role of their own
defined there (a role outside admin may hold privileges on its own database only):
  - the resolver (RESOLVER_DB_USERNAME, role RESOLVER_ROLE): reads the records (resolver_ce.gs1resolver) and the five
    collections of the portal's database it serves from (tenants, domains, settings, branding, forwarding_rules), writes
    the request log
    (resolver_log.requests and request_counts: insert, update, indexes), and nothing else — not the portal's users,
    sessions, keys or journal;
  - the data entry API (DATA_ENTRY_DB_USERNAME, role DATA_ENTRY_ROLE): reads and writes the records, nothing else.

The journal's upkeep that needs more than inserting runs here, with the root user: the one-time move of the journal
from the portal's database into its own (move_journal(); the marker document journal_moved {_id: "moved"} in the
journal's database says it is done, and a journal collection that reappears in the portal's database afterwards is
reported, never moved), the indexes of both databases (store.db()), a change of retention (journal.apply_retention())
and the sealing of the events it moved without a seal (journal.seal_unsealed(ids)).

Run by the one-shot Compose service portal-db-init before the portal starts, on every "docker compose up",
so a new installation, an existing one and a restored one all end with the user and the password of .env.
MongoDB's own /docker-entrypoint-initdb.d scripts run only on an empty volume and cannot serve the last two.

Reads MONGO_URI (the root connection; since ADR 0030 this service alone receives it), PORTAL_DB_NAME,
PORTAL_DB_USERNAME, PORTAL_DB_PASSWORD, RESOLVER_DB_USERNAME, RESOLVER_DB_PASSWORD, DATA_ENTRY_DB_USERNAME and
DATA_ENTRY_DB_PASSWORD (a service whose password is empty is left as it is, with a warning). Prints what it did, never a password. Exit status 0 on success.

  docker compose run --rm portal-db-init          # by hand, e.g. after changing PORTAL_DB_PASSWORD
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit

import example_secrets
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
RECORDS_DB, RECORDS = "resolver_ce", "gs1resolver"       # the official services' records
RESOLVER_ROLE = "resolverService"                        # defined in admin (privileges on several databases)
DATA_ENTRY_ROLE = "dataEntryService"
RESOLVER_PORTAL_COLLECTIONS = ("tenants", "domains", "settings", "branding", "forwarding_rules")   # read there
LOG_COLLECTIONS = ("requests", "request_counts")         # the resolver's request log (ADR 0006)
SERVICES = (("RESOLVER", "resolver_web", RESOLVER_ROLE), ("DATA_ENTRY", "resolver_data_entry", DATA_ENTRY_ROLE))


def resolver_privileges(portal_db: str) -> list[dict]:
    """The resolver: find on the records and on the portal's collections it serves from; the request log written."""
    return ([{"resource": {"db": RECORDS_DB, "collection": RECORDS}, "actions": ["find"]}]
            + [{"resource": {"db": portal_db, "collection": c}, "actions": ["find"]} for c in RESOLVER_PORTAL_COLLECTIONS]
            + [{"resource": {"db": LOG_DB, "collection": c}, "actions": ["createIndex", "insert", "update"]}
               for c in LOG_COLLECTIONS])


def data_entry_privileges() -> list[dict]:
    """The data entry API: the records read and written, nothing else."""
    return [{"resource": {"db": RECORDS_DB, "collection": RECORDS},
             "actions": ["find", "insert", "remove", "update"]}]


def ensure_user(database, username: str, password: str, roles: list[dict]) -> str:
    """Creates the user, or sets its password and roles; returns 'created' or 'brought up to date'."""
    if database.command("usersInfo", username)["users"]:
        database.command("updateUser", username, pwd=password, roles=roles)
        return "brought up to date"
    database.command("createUser", username, pwd=password, roles=roles)
    return "created"


def service_users(client, portal_db: str) -> None:
    """The users of the resolver and of the data entry API (ADR 0030), in the admin database."""
    admin = client["admin"]
    ensure_role(admin, RESOLVER_ROLE, resolver_privileges(portal_db))
    ensure_role(admin, DATA_ENTRY_ROLE, data_entry_privileges())
    for prefix, default, role in SERVICES:
        username = os.environ.get(f"{prefix}_DB_USERNAME", "").strip() or default
        password = os.environ.get(f"{prefix}_DB_PASSWORD", "")
        if not password:
            print(f"portal-db-init: WARNING: {prefix}_DB_PASSWORD is not set; the user {username} was not created or "
                  f"changed (Documentation/adr/0030-least-privilege-services.md).")
            continue
        if username == root_username():
            raise RuntimeError(f"{prefix}_DB_USERNAME may not be MongoDB's root user")
        done = ensure_user(admin, username, password, [{"role": role, "db": "admin"}])
        print(f"portal-db-init: user {username} of the {prefix.lower().replace('_', ' ')} service {done}.")


def root_username() -> str:
    """The root user's name, from MONGO_INITDB_ROOT_USERNAME or the root connection string."""
    name = os.environ.get("MONGO_INITDB_ROOT_USERNAME", "").strip()
    if name:
        return name
    try:
        return unquote(urlsplit(os.environ.get("MONGO_URI", "")).username or "")
    except ValueError:
        return ""


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


EXAMPLES_SETTING = "security.examples"


def record_examples(database, names: list[str]) -> None:
    """Keeps in the portal's settings which of the secrets only this service sees still hold the example of
    .env.example ({_id: EXAMPLES_SETTING, value: {names, at}}; none in development): the portal's monitoring alerts the
    server administrators while one does (Documentation/adr/0062-example-secrets-watched.md). Never the value."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    database["settings"].update_one({"_id": EXAMPLES_SETTING},
                                    {"$set": {"value": {"names": list(names), "at": now}, "updatedAt": now}}, upsert=True)


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
    examples = [] if example_secrets.development() else example_secrets.in_use(["MONGO_URI"])
    if examples:
        print("portal-db-init: WARNING: MONGO_URI holds the example root password of .env.example, known to everyone; "
              "change it with scripts/rotate-secrets.sh mongo (Documentation/adr/0030-least-privilege-services.md).")
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
            service_users(client, name)
            store, journal = connect_store(root_uri)
            unsealed = move_journal(client, name)
            database = client[name]
            record_examples(database, examples)
            if ensure_user(database, username, password, roles) == "created":
                print(f"portal-db-init: user {username} created for database {name}.")
            else:
                print(f"portal-db-init: user {username} of database {name} brought up to date.")
        journal_upkeep(store, journal, unsealed)
    except (PyMongoError, RuntimeError) as exc:
        print(f"portal-db-init: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
