"""One time budget for all the database reads of a request (finding F-032; Documentation/adr/0052-database-time-budget.md).

The resolver reads MongoDB up to six times in one request: the caches of the domains, forwarding, the strict mode, the
request log's retention, the brands and the appearance when their period has passed, then the record (web_db). Without
a bound each read waited for PyMongo's server selection timeout (30 s) while the database was unreachable, one after
the other: one scan held a server thread for three minutes before its 503. Budget wraps the application, so that every
read of a request shares RESOLVER_DB_TIMEOUT_MS (pymongo.timeout()): once it is spent, a read that finds no server
fails at once, the caches keep their last values, web_db answers 500 and the resolver 503 with Retry-After
(Documentation/adr/0051-records-unavailable.md). The request log's writer and other background threads are outside it.
"""
import os

import pymongo

SETTING = 'RESOLVER_DB_TIMEOUT_MS'
DEFAULT_MS = 5000
MIN_MS, MAX_MS = 500, 60000


def setting_ms() -> int | None:
    """RESOLVER_DB_TIMEOUT_MS as a whole number of milliseconds within the limits; None when unset or invalid."""
    raw = os.environ.get(SETTING, '').strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if MIN_MS <= value <= MAX_MS else None


def invalid() -> bool:
    """True when RESOLVER_DB_TIMEOUT_MS is set but not usable (DEFAULT_MS is used; create_app warns)."""
    return bool(os.environ.get(SETTING, '').strip()) and setting_ms() is None


def seconds() -> float:
    """The time a request may spend reading MongoDB, in seconds: the setting, or DEFAULT_MS."""
    return (setting_ms() or DEFAULT_MS) / 1000


class Budget:
    """WSGI middleware: every database read made while the application handles a request shares one time budget."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        with pymongo.timeout(seconds()):
            return self.app(environ, start_response)
