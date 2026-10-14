"""
Creates, or brings up to date, the portal's own MongoDB user: readWrite on the portal's database, read on the
resolver's request log (resolver_log, Documentation/adr/0006-resolver-request-log.md) and nothing else
(Documentation/adr/0001-portal-state-in-mongodb.md, section 3.1).

Run by the one-shot Compose service portal-db-init before the portal starts, on every "docker compose up",
so a new installation, an existing one and a restored one all end with the user and the password of .env.
MongoDB's own /docker-entrypoint-initdb.d scripts run only on an empty volume and cannot serve the last two.

Reads MONGO_URI (the root connection the official services use), PORTAL_DB_NAME, PORTAL_DB_USERNAME and
PORTAL_DB_PASSWORD. Prints what it did, never a password. Exit status 0 on success.

  docker compose run --rm portal-db-init          # by hand, e.g. after changing PORTAL_DB_PASSWORD
"""
import os
import sys

from pymongo import MongoClient
from pymongo.errors import PyMongoError

LOG_DB = "resolver_log"                                   # written by the resolver, read by the portal
RESERVED = {"admin", "local", "config", "resolver_ce", LOG_DB}     # never the portal's own database


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
    roles = [{"role": "readWrite", "db": name}, {"role": "read", "db": LOG_DB}]
    timeout = int(os.environ.get("PORTAL_DB_INIT_TIMEOUT_MS", "60000"))   # the database may still be starting
    try:
        with MongoClient(root_uri, serverSelectionTimeoutMS=timeout, appname="portal-db-init") as client:
            database = client[name]
            exists = database.command("usersInfo", username)["users"]
            if exists:
                database.command("updateUser", username, pwd=password, roles=roles)
                print(f"portal-db-init: user {username} of database {name} brought up to date.")
            else:
                database.command("createUser", username, pwd=password, roles=roles)
                print(f"portal-db-init: user {username} created for database {name}.")
    except PyMongoError as exc:
        print(f"portal-db-init: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
