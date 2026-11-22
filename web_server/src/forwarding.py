"""
Forwarding (Documentation/adr/0018-forwarding.md): the requests this resolver sends to another one.

  - Prefix rules: every request for a key whose GS1 Company Prefix starts with a rule's prefix goes to the rule's
    destination, whatever this resolver holds for it (the longest prefix wins). A rule either keeps the request's
    path (another resolver answers it: destination + /01/…/10/… + ?query) or always sends to its address.
  - The resolver of last resort: a request for a key this resolver does not know (outcome "unknown": no record, or a
    key outside the scope of the organisation's own domain) goes to another resolver, https://id.gs1.org by default,
    with its path and query string, instead of a 404.

The server administrators set both in the portal (collection "forwarding_rules" and the setting "forwarding.fallback"
of the portal's database, PORTAL_DB_NAME); the resolver reads them with its root connection at most every
CACHE_SECONDS, and keeps the last ones read when the database does not answer, for RESOLVER_SETTINGS_MAX_AGE_S at
most: after that neither the rules nor the resolver of last resort are applied until the database is read again
(finding F-033, Documentation/adr/0053-settings-age.md).
"""
import logging
import threading
import time

import request_log
import settings_age

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
DEFAULT_FALLBACK = 'https://id.gs1.org'
SETTING_FALLBACK = 'forwarding.fallback'
RULES = 'forwarding_rules'


def join(base: str, path: str, query: str) -> str:
    """The destination of a request that keeps its path: base without its trailing slash, the GS1 Digital Link path,
    the query string."""
    return base.rstrip('/') + path + (('?' + query) if query else '')


class Forwarding:
    """The rules and the resolver of last resort as the portal set them: {"rules": [(prefix, target, mode)], longest
    prefix first, "fallback": url or None}."""

    def __init__(self, database=None):
        self.database = database        # a function giving the portal's database (pymongo), set by create_app
        self._rules: list[tuple[str, str, str]] = []
        self._fallback: str | None = None
        self._loaded = 0.0
        self._lock = threading.Lock()
        self.age = settings_age.Age('Forwarding', 'its prefix rules and the resolver of last resort are not applied')

    def _load(self) -> None:
        db = self.database()
        rules = [(str(doc['_id']), str(doc.get('target') or ''), doc.get('mode') or 'path')
                 for doc in db[RULES].find({'enabled': True}, {'target': 1, 'mode': 1})]
        setting = (db['settings'].find_one({'_id': SETTING_FALLBACK}) or {}).get('value') or {}
        self._rules = sorted([r for r in rules if r[0] and r[1]], key=lambda r: -len(r[0]))
        self._fallback = (setting.get('url') or DEFAULT_FALLBACK) if setting.get('enabled') else None

    def refresh(self) -> None:
        """Reads the settings again when CACHE_SECONDS have passed; a failure keeps the last ones (settings_age)."""
        if self.database is None:
            return
        now = time.monotonic()
        if now - self._loaded >= CACHE_SECONDS:
            with self._lock:
                if now - self._loaded >= CACHE_SECONDS:
                    try:
                        self._load()
                        self.age.read(now)
                    except Exception as exc:          # noqa: BLE001 — the resolver keeps answering
                        logger.warning('Forwarding not read (%s); the last settings are kept.', exc)
                        self.age.failed(now)
                    self._loaded = now

    def rule_for(self, ai: str, value: str) -> tuple[str, str, str] | None:
        """(prefix, target, mode) of the rule for a key, or None (also while the settings are stale)."""
        self.refresh()
        part = request_log.company_part(ai, value)
        if not part or self.age.stale():
            return None
        return next((rule for rule in self._rules if part.startswith(rule[0])), None)

    def fallback(self) -> str | None:
        """The resolver of last resort, or None when it is switched off or the settings are stale."""
        self.refresh()
        return None if self.age.stale() else self._fallback

    def forget(self) -> None:
        """Reads the settings again at the next request (tests)."""
        self._loaded = 0.0


FORWARDING = Forwarding()
