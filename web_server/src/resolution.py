"""
The strict mode for safety-critical link types (Documentation/adr/0022-answering-level.md, section 2.4).

With the strict mode on for the organisation that owns a key, a request that asks for a safety-critical link type and
names a batch or a serial number is answered only by a record that names that batch or serial number: the walk-up of
GS1-Conformant Resolver 1.2.1 (sections 2.5.9 and 2.5.10) stops there, and a link held only by a less specific level is
withheld (404 with Resolution-Match: withheld; web_logic.read_document(), web_namespace).

The portal keeps the setting in its own database (PORTAL_DB_NAME): the field "strictSafety" of an organisation
(collection "tenants") and the setting "resolution.strict" for the keys no organisation holds (the operator's scope).
The resolver reads both with its root connection at most every CACHE_SECONDS and keeps the last ones read when the
database does not answer. The organisation that owns a key is the one with the longest GS1 Company Prefix that starts
it, as everywhere else.
"""
import logging
import threading
import time

import request_log

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
SETTING_STRICT = 'resolution.strict'
TENANT_FIELD = 'strictSafety'

# The five safety-critical link types of the GS1 Web vocabulary (ADR 0022, section 2.1; control G-6 of the threat
# model). The portal holds the same list (portal/resolution.py); a development test keeps the two equal.
SAFETY_CRITICAL = ('recallStatus', 'safetyInfo', 'epil', 'smpc', 'eifu')

# The key qualifiers a strict answer must name: a batch, a serial number, a third-party controlled serial (TPX)
STRICT_QUALIFIERS = ('10', '21', '235')


class StrictMode:
    """{"prefixes": [(prefix, strict)], longest first, "operator": strict}, as the portal set them."""

    def __init__(self, database=None):
        self.database = database        # a function giving the portal's database (pymongo), set by create_app
        self._prefixes: list[tuple[str, bool]] = []
        self._operator = False
        self._loaded = 0.0
        self._lock = threading.Lock()

    def _load(self) -> None:
        db = self.database()
        prefixes = [(str(p), bool(doc.get(TENANT_FIELD)))
                    for doc in db['tenants'].find({}, {'prefixes': 1, TENANT_FIELD: 1})
                    for p in (doc.get('prefixes') or []) if p]
        setting = (db['settings'].find_one({'_id': SETTING_STRICT}) or {}).get('value') or {}
        self._prefixes = sorted(prefixes, key=lambda item: -len(item[0]))
        self._operator = bool(setting.get('enabled'))

    def _fresh(self) -> None:
        if self.database is None:
            return
        now = time.monotonic()
        if now - self._loaded >= CACHE_SECONDS:
            with self._lock:
                if now - self._loaded >= CACHE_SECONDS:
                    try:
                        self._load()
                    except Exception as exc:          # noqa: BLE001 — the resolver keeps answering
                        logger.warning('Strict mode not read (%s); the last settings are kept.', exc)
                    self._loaded = now

    def on_for(self, ai: str, value: str) -> bool:
        """Whether the strict mode is on for the organisation that owns this key (the operator's for a key no
        organisation holds)."""
        self._fresh()
        part = request_log.company_part(ai, value)
        if not part:
            return False
        owner = next((strict for prefix, strict in self._prefixes if part.startswith(prefix)), None)
        return self._operator if owner is None else owner

    def forget(self) -> None:
        """Reads the settings again at the next request (tests)."""
        self._loaded = 0.0


STRICT = StrictMode()


def applies(linktype: str | None, path_qualifiers: list[dict[str, str]]) -> bool:
    """Whether a request falls under the strict mode: it asks for a safety-critical link type (the bare term,
    web_logic.normalise_linktype()) and names a batch or a serial number."""
    return bool(linktype in SAFETY_CRITICAL and any(k in STRICT_QUALIFIERS for q in path_qualifiers for k in q))


def may_answer(path_qualifiers: list[dict[str, str]], doc_qualifiers: list[dict[str, str]]) -> bool:
    """Under the strict mode, whether a record that applies to the request may answer it: it names the request's
    batch or serial number (a record applies only when its values equal the request's, web_logic._entry_applies())."""
    asked = {k for q in path_qualifiers for k in q} & set(STRICT_QUALIFIERS)
    return bool(asked & {k for q in doc_qualifiers for k in q})
