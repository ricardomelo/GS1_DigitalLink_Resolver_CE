"""The example secrets of .env.example refused outside development (Documentation/adr/0021-data-entry-api-closed.md, §2.7).

.env.example is public and holds working credentials so that "docker compose up -d" runs on a development machine
without a .env. On any other installation those values are known to everyone: a service that finds the example data
entry token or the example password of its own database user (the portal's, the resolver's or the data entry API's:
Documentation/adr/0030-least-privilege-services.md) while FQDN names a real host refuses to start, saying which setting
to change, instead of serving with it. The installer replaces them whenever it finds them.

MongoDB's root password is only warned about: the installer keeps it for a database created with it (it cannot change
it without the database), so refusing it would stop an upgraded installation; scripts/rotate-secrets.sh mongo changes it.
Since ADR 0030 only portal-db-init holds it; since ADR 0062 it records what it found, and the portal's monitoring
alerts the server administrators while it stays. The first portal user is never created with the example
PORTAL_ADMIN_PASSWORD (ADR 0062).

Development: FQDN empty, localhost, 127.0.0.1, ::1 or a name under .localhost.

The same file is copied into web_server/src, data_entry_server/src and portal (each image holds only its own folder);
dev-tests/install/test_deploy.py checks that the copies are identical.
"""
import logging
import os
from urllib.parse import urlsplit

# A setting whose whole value is an example; a connection string whose password is
EXAMPLE_VALUES = {"SESSION_TOKEN": "secret", "PORTAL_DB_PASSWORD": "resolver_portal",
                  "RESOLVER_DB_PASSWORD": "resolver_web", "DATA_ENTRY_DB_PASSWORD": "resolver_data_entry",
                  "PORTAL_ADMIN_PASSWORD": "change-me-please"}
EXAMPLE_URI_PASSWORDS = {"MONGO_URI": "gs1resolver"}
DEVELOPMENT_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def development() -> bool:
    """Whether FQDN names a development machine rather than an installation others reach."""
    host = os.environ.get("FQDN", "").strip().lower().rstrip(".")
    return host in DEVELOPMENT_HOSTS or host.endswith(".localhost")


def in_use(names: list[str]) -> list[str]:
    """The settings among `names` that still hold the example value of .env.example."""
    found = []
    for name in names:
        value = os.environ.get(name, "").strip()
        if name in EXAMPLE_VALUES and value == EXAMPLE_VALUES[name]:
            found.append(name)
        elif name in EXAMPLE_URI_PASSWORDS and value:
            try:
                password = urlsplit(value).password
            except ValueError:
                password = None
            if password == EXAMPLE_URI_PASSWORDS[name]:
                found.append(name)
    return found


def warn(names: list[str], log: logging.Logger) -> None:
    """Logs a warning when one of `names` holds its example value outside development."""
    if development():
        return
    for name in in_use(names):
        log.warning("%s holds the example password of .env.example, known to everyone, while FQDN is %s: change it "
                    "with scripts/rotate-secrets.sh mongo (Documentation/adr/0021-data-entry-api-closed.md).",
                    name, os.environ.get("FQDN", "").strip())


def refuse(names: list[str]) -> None:
    """Stops the service (RuntimeError) when one of `names` holds its example value outside development."""
    if development():
        return
    found = in_use(names)
    if found:
        raise RuntimeError(
            f"Refusing to start: {', '.join(found)} still {'has' if len(found) == 1 else 'have'} the example value of "
            f".env.example, known to everyone, while FQDN is {os.environ.get('FQDN', '').strip()}. Set new values in "
            ".env (scripts/rotate-secrets.sh does it; Documentation/adr/0021-data-entry-api-closed.md) and start again.")
