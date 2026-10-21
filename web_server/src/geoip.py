"""
The approximate location of a request for the log of resolver requests (Documentation/adr/0006-resolver-request-log.md,
section 8): country, region and city — and, with a city, the city's position to a tenth of a degree, for the map of
requests (section 10) — looked up in a GeoIP database file at the moment of the request. The client's
address is used for the lookup only — it is never returned, stored or written in a log line.

The file is an MMDB in the GeoIP2/GeoLite2 City layout: DB-IP's "IP to City Lite" by default (Creative Commons
Attribution 4.0; scripts/geoip-update.sh downloads it monthly). It is opened at the first lookup and opened again when
a newer file replaces it (looked for at most every CHECK_SECONDS); without a file nothing is located.

Settings, read at every request (so a test can change them):
  RESOLVER_GEOIP_DB            the database file; empty: no location (default /geoip/dbip-city-lite.mmdb)
  RESOLVER_LOG_ADDRESS_HEADER  the header with the client's address, set by the proxy in front (default X-Real-IP);
                               empty: the connection's address
"""
import ipaddress
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

DEFAULT_PATH = '/geoip/dbip-city-lite.mmdb'
DEFAULT_HEADER = 'X-Real-IP'
CHECK_SECONDS = 60
MAX_NAME = 100
POINT_DECIMALS = 1                            # a tenth of a degree, about 11 km: a city, never a street


def database_path() -> str:
    raw = os.environ.get('RESOLVER_GEOIP_DB')
    return DEFAULT_PATH if raw is None else raw.strip()


def client_address(headers, remote_addr: str | None) -> str | None:
    """The client's address: the first one in the header the proxy sets, or the connection's. Not checked here."""
    name = os.environ.get('RESOLVER_LOG_ADDRESS_HEADER')
    name = DEFAULT_HEADER if name is None else name.strip()
    if name:
        value = (headers.get(name) or '').split(',')[0].strip()
        if value:
            return value
    return remote_addr


def _public(address: str | None) -> str | None:
    """The address in canonical form when it is a public one; None for anything else (private, loopback, reserved,
    malformed). "[2001:db8::1]:443" and "198.51.100.7:51000" are read without their port."""
    text = (address or '').strip()
    if text.startswith('[') and ']' in text:
        text = text[1:text.index(']')]
    elif text.count(':') == 1:
        text = text.split(':')[0]
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip) if ip.is_global else None


def _point(location) -> list[float] | None:
    """[latitude, longitude] of a GeoIP record's location, rounded to POINT_DECIMALS; None when absent or invalid."""
    try:
        lat, lon = float(location['latitude']), float(location['longitude'])
    except (TypeError, KeyError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return [round(lat, POINT_DECIMALS), round(lon, POINT_DECIMALS)]


def _english(node) -> str | None:
    names = (node or {}).get('names') or {}
    name = names.get('en') or next(iter(names.values()), None)
    name = ' '.join(str(name).split())[:MAX_NAME] if name else ''
    return name or None


class Locator:
    """The GeoIP database of one server process, opened lazily and again when the file changes."""

    def __init__(self):
        self._reader = None
        self._opened = None             # (path, modification time) of the file open
        self._checked = 0.0
        self._missing_said = None       # the path a warning was written for
        self._lock = threading.Lock()

    def _current(self):
        path = database_path()
        if not path:
            return None
        now = time.monotonic()
        if self._reader is not None and self._opened[0] == path and now - self._checked < CHECK_SECONDS:
            return self._reader
        with self._lock:
            self._checked = now
            try:
                stamp = os.stat(path).st_mtime
            except OSError:
                if self._missing_said != path:
                    log.info('No GeoIP database at %s: requests are logged without a location.', path)
                    self._missing_said = path
                self._close()
                return None
            if self._reader is not None and self._opened == (path, stamp):
                return self._reader
            try:
                import maxminddb
                reader = maxminddb.open_database(path, maxminddb.MODE_MMAP)
            except Exception as exc:          # noqa: BLE001 — a broken file costs only the location
                if self._missing_said != (path, stamp):
                    log.warning('GeoIP database %s not read (%s): requests are logged without a location.',
                                path, type(exc).__name__)
                    self._missing_said = (path, stamp)
                self._close()
                return None
            self._close()
            self._reader, self._opened, self._missing_said = reader, (path, stamp), None
            log.info('GeoIP database %s (%s, built %s).', path, reader.metadata().database_type,
                     time.strftime('%Y-%m-%d', time.gmtime(reader.metadata().build_epoch)))
            return reader

    def _close(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:                 # noqa: BLE001
                pass
        self._reader, self._opened = None, None

    def locate(self, address: str | None) -> dict:
        """{"c": "BR", "rg": "Sao Paulo", "ci": "Campinas", "ll": [-22.9, -47.1]} with what the database knows of a
        public address (ll only with a city); {} for anything else. Never raises."""
        ip = _public(address)
        if ip is None:
            return {}
        try:
            reader = self._current()
            found = reader.get(ip) if reader is not None else None
        except Exception:                     # noqa: BLE001 — the address is not put in the message
            log.warning('GeoIP lookup failed.')
            return {}
        if not isinstance(found, dict):
            return {}
        out = {}
        country = str((found.get('country') or {}).get('iso_code') or '').upper()
        if len(country) == 2 and country.isalpha():
            out['c'] = country
        subdivisions = found.get('subdivisions') or []
        region = _english(subdivisions[0]) if subdivisions and isinstance(subdivisions[0], dict) else None
        if region:
            out['rg'] = region
        city = _english(found.get('city'))
        if city:
            out['ci'] = city
            point = _point(found.get('location'))
            if point:
                out['ll'] = point
        return out


LOCATOR = Locator()
