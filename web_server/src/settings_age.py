"""The age of the portal's settings the resolver keeps in its caches (finding F-033;
Documentation/adr/0053-settings-age.md).

Six caches read the portal's database at most every 30 to 300 seconds: the domains (domains.MAP), forwarding
(forwarding.FORWARDING), the strict mode (resolution.STRICT), the brands of the item's page (landing.BRANDS), the
appearance (web_pages.APPEARANCE) and the request log's retention (request_log.RETENTION). When a read fails each keeps
the values it read last. Age bounds that: each cache notes when it last read the database; once its reads have failed
for longer than RESOLVER_SETTINGS_MAX_AGE_S since then, its values are stale.

  - A cache whose values are safer absent stops using them: forwarding (no prefix rule, no resolver of last resort:
    the resolver answers from its own records), the brands (the item's page without an organisation's brand and its
    verified site) and the appearance (the original pages).
  - A cache whose absence would loosen a restriction keeps them: the domains (without them an organisation's domain
    would answer for every key), the strict mode (without it a withheld link would be given) and the retention.

Either way the resolver's log has an error line when a cache becomes stale and an information line when it reads the
database again, the heartbeat says "settings": "stale" (web_namespace.Heartbeat), and the portal's monitor raises the
alert "settings" from it (portal/monitor.py).
"""
import logging
import os
import time

logger = logging.getLogger(__name__)

SETTING = 'RESOLVER_SETTINGS_MAX_AGE_S'
DEFAULT_S = 900
MIN_S, MAX_S = 60, 86400


def setting_s() -> int | None:
    """RESOLVER_SETTINGS_MAX_AGE_S as a whole number of seconds within the limits; None when unset or invalid."""
    raw = os.environ.get(SETTING, '').strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if MIN_S <= value <= MAX_S else None


def invalid() -> bool:
    """True when RESOLVER_SETTINGS_MAX_AGE_S is set but not usable (DEFAULT_S is used; create_app warns)."""
    return bool(os.environ.get(SETTING, '').strip()) and setting_s() is None


def limit() -> int:
    """The longest time, in seconds, a cache may go on with values it could not read again."""
    return setting_s() or DEFAULT_S


class Age:
    """When a cache last read the portal's database, and whether its values are stale: its reads have failed since
    then, for longer than limit(). The start of the process counts as a read (the values are then the defaults)."""

    def __init__(self, name: str, after: str):
        self.name = name                # the cache, as the log names it
        self.after = after              # what the resolver does with its values once they are stale
        self.read_at = time.monotonic()
        self.failing = False
        self._told = False

    def read(self, now: float) -> None:
        """A read of the database succeeded at now."""
        if self._told:
            logger.info('%s read again from the portal\'s database; its settings are applied.', self.name)
        self.read_at, self.failing, self._told = now, False, False

    def failed(self, now: float) -> None:
        """A read of the database failed at now."""
        self.failing = True
        self.stale(now)

    def stale(self, now: float | None = None) -> bool:
        """True while the values are older than limit() and could not be read again; logs once when they become so."""
        now = time.monotonic() if now is None else now
        old = self.failing and now - self.read_at > limit()
        if old and not self._told:
            self._told = True
            logger.error('%s not read from the portal\'s database for %d s (RESOLVER_SETTINGS_MAX_AGE_S %d): %s until '
                         'it is read again.', self.name, now - self.read_at, limit(), self.after)
        return old


def state(caches) -> str:
    """"stale" when one of the caches (objects with refresh() and age) holds stale values, else "current"; each is
    refreshed first, which reads the database only when its period has passed."""
    stale = False
    for cache in caches:
        cache.refresh()
        stale = cache.age.stale() or stale
    return 'stale' if stale else 'current'
