"""The service's own MongoDB connection (Documentation/adr/0030-least-privilege-services.md).

The resolver and the data entry API no longer hold MongoDB's root credentials: each connects as its own user, which
portal-db-init creates, or brings up to date, at every "docker compose up" with the least privileges the service needs
(portal/db_init.py). The connection is read from settings with the service's prefix:

  <PREFIX>_DB_URI        a complete MongoDB URI (an external server, for example); when set, the values below are not read
  <PREFIX>_DB_USERNAME   the service's user (created in MongoDB's admin database)
  <PREFIX>_DB_PASSWORD   its password (refused at start-up outside development while it is .env.example's)
  <PREFIX>_DB_HOST       host:port, default database-service:27017

The prefix is RESOLVER for the resolver (web-service) and DATA_ENTRY for the data entry API. With neither a URI nor a
password, MONGO_URI is used, as before this change, with a warning: docker-compose.yml gives these services an empty
MONGO_URI, so that fallback serves a service started by hand only.

The same file is copied into web_server/src and data_entry_server/src (each image holds only its own folder);
dev-tests/install/test_deploy.py checks that the copies are identical.
"""
import logging
import os
from urllib.parse import quote_plus

DEFAULT_HOST = "database-service:27017"
AUTH_DB = "admin"


def uri(prefix: str, log: logging.Logger | None = None) -> str:
    """The connection URI of the service whose settings start with `prefix`; RuntimeError when there is none."""
    explicit = os.environ.get(f"{prefix}_DB_URI", "").strip()
    if explicit:
        return explicit
    password = os.environ.get(f"{prefix}_DB_PASSWORD", "")
    user = os.environ.get(f"{prefix}_DB_USERNAME", "").strip()
    if password and user:
        host = os.environ.get(f"{prefix}_DB_HOST", "").strip() or DEFAULT_HOST
        return f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}/?authSource={AUTH_DB}"
    legacy = os.environ.get("MONGO_URI", "").strip()
    if legacy:
        if log is not None:
            log.warning("%s_DB_USERNAME and %s_DB_PASSWORD are not set: connecting with MONGO_URI, MongoDB's root user "
                        "(Documentation/adr/0030-least-privilege-services.md).", prefix, prefix)
        return legacy
    raise RuntimeError(f"Neither {prefix}_DB_URI nor {prefix}_DB_USERNAME and {prefix}_DB_PASSWORD are set")


def host_of(connection: str) -> str:
    """The part of a URI after the credentials, for the log (never the password)."""
    return connection.split('@')[-1] if '@' in connection else connection
