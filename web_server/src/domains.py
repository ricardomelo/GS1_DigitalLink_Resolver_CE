"""
The organisations' own domains (Documentation/adr/0009-tenant-domains.md; GS1 Digital Link URI Syntax 1.7, section
4.11): a WSGI middleware in front of the resolver that recognises a request made on a registered domain.

The portal keeps the domains in its own database (collection "domains" of PORTAL_DB_NAME, "resolver_portal" by
default); the resolver reads the verified ones whose mode is "direct" with its root connection, at most every
CACHE_SECONDS. For a request on such a domain (the public host comes from X-Forwarded-Host, which the proxy sets, or
Host):

  - the domain's path stem ("/gs1") is removed from the path (PATH_INFO and the raw request URI), so that
    https://id.acme.example/gs1/01/… resolves as /01/…;
  - the domain's limits are kept in the WSGI environment (ENV_KEY): an organisation's domain answers only for its
    prefixes, the operator's for the keys no organisation holds; web_namespace refuses the others with 404, as a code
    nobody registered (allows()).

A host that is not a registered domain (the installation's own name above all) is served exactly as before.

public_name() gives the name a request was made on, for the addresses the resolver writes about it (the linkset's
anchors, the Link header, the description file's root): a GS1 Digital Link URI names the same item on any of the
installation's names, and a client compares the anchors with the URI it asked for (GS1's conformance test suite
requires the anchor to be that URI).
"""
import logging
import os
import re
import threading
import time

import request_log

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
ENV_KEY = 'gs1resolver.domain'
MOUNT = '/api'                      # the blueprint's prefix: the proxy sends /api<request URI>
_HOST_NAME = re.compile(r'^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$')


def portal_db_name() -> str:
    return (os.getenv('PORTAL_DB_NAME', '') or '').strip() or 'resolver_portal'


class DomainMap:
    """The verified direct domains: {host: {"stem", "prefixes" (None for the operator), "excluded"}}, read again
    after CACHE_SECONDS; when the database cannot be read the last map is kept."""

    def __init__(self, database=None):
        self.database = database        # a function giving the portal's database (pymongo), set by create_app
        self._map: dict[str, dict] = {}
        self._loaded = 0.0
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict]:
        db = self.database()
        tenants = {doc['_id']: list(doc.get('prefixes') or []) for doc in db['tenants'].find({}, {'prefixes': 1})}
        every = [p for prefixes in tenants.values() for p in prefixes]
        found = {}
        for doc in db['domains'].find({'verified': True, 'mode': 'direct'}, {'stem': 1, 'tenant': 1}):
            tenant = doc.get('tenant')
            found[doc['_id']] = {'stem': doc.get('stem') or '',
                                 'prefixes': tenants.get(tenant, []) if tenant else None,
                                 'excluded': [] if tenant else every}
        return found

    def lookup(self, host: str) -> dict | None:
        if not host or self.database is None:
            return None
        now = time.monotonic()
        if now - self._loaded >= CACHE_SECONDS:
            with self._lock:
                if now - self._loaded >= CACHE_SECONDS:
                    try:
                        self._map = self._load()
                    except Exception as exc:          # noqa: BLE001 — the resolver keeps answering
                        logger.warning('Domains not read (%s); the last list is kept.', exc)
                    self._loaded = now
        return self._map.get(host)

    def forget(self) -> None:
        """Reads the domains again at the next request (tests)."""
        self._loaded = 0.0


MAP = DomainMap()


def request_host(environ: dict) -> str:
    """The public host of a request, lower case, without port."""
    raw = environ.get('HTTP_X_FORWARDED_HOST') or environ.get('HTTP_HOST') or ''
    host = raw.split(',')[0].strip().lower()
    if host.startswith('['):                          # an IPv6 literal is never a registered domain
        return ''
    return host.split(':')[0]


def public_name(environ: dict) -> str | None:
    """The public name the request was made on, as the start of its URI without the scheme: an organisation's domain
    with its stem ("id.acme.example/gs1"), or the host the proxy names in X-Forwarded-Host when it is a valid host
    name (another name of the installation). None without X-Forwarded-Host (a request that did not come through the
    proxy): the caller then uses the installation's FQDN."""
    entry = environ.get(ENV_KEY)
    if entry:
        return entry['host'] + entry['stem']
    if not environ.get('HTTP_X_FORWARDED_HOST'):
        return None
    host = request_host(environ)
    return host if _HOST_NAME.match(host) else None


def _without_stem(path: str, stem: str) -> str | None:
    """The path with MOUNT + stem replaced by MOUNT, or None when it does not start with them."""
    prefix = MOUNT + stem
    if path == prefix or path == prefix + '/':
        return MOUNT + '/'
    if path.startswith(prefix + '/'):
        return MOUNT + path[len(prefix):]
    return None


class Middleware:
    """WSGI middleware: recognises a registered domain, removes its stem, records its limits."""

    def __init__(self, app, domain_map: DomainMap = MAP):
        self.app = app
        self.map = domain_map

    def __call__(self, environ, start_response):
        host = request_host(environ)
        entry = self.map.lookup(host)
        if entry:
            environ[ENV_KEY] = {**entry, 'host': host}
            stem = entry['stem']
            if stem:
                path = _without_stem(environ.get('PATH_INFO', ''), stem)
                if path is not None:
                    environ['PATH_INFO'] = path
                    for name in ('RAW_URI', 'REQUEST_URI'):
                        raw = environ.get(name)
                        if raw:
                            raw_path, sep, query = raw.partition('?')
                            stripped = _without_stem(raw_path, stem)
                            if stripped is not None:
                                environ[name] = stripped + sep + query
        return self.app(environ, start_response)


def allows(environ: dict, ai: str, value: str) -> bool:
    """Whether the domain of the request may answer for this key (always outside a registered domain)."""
    entry = environ.get(ENV_KEY)
    if not entry:
        return True
    part = request_log.company_part(ai, value)
    if part is None:
        return False
    if entry['prefixes'] is not None:
        return any(part.startswith(p) for p in entry['prefixes'])
    return not any(part.startswith(p) for p in entry['excluded'])
