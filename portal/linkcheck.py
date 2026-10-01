"""
Link checker: does each target address answer, and does it stay on HTTPS?

For every URL: a HEAD request (GET when the server refuses HEAD), following up to MAX_REDIRECTS
redirects one by one so that a hop from https:// to http:// can be reported. Results are cached for
CACHE_SECONDS so that checking the same addresses again does not hammer the sites.

Only public addresses are contacted. Host names resolving to private, loopback, link-local or other
non-global addresses (the Docker network, the cloud metadata service, …) are refused, at every hop, so
that the portal cannot be used to probe the server's own network. PORTAL_LINKCHECK_ALLOW_PRIVATE=1
lifts this for development tests only.

Result: {"url", "ok", "problem" (message code or None), "status", "finalUrl", "params"}
  problem codes: linkcheck.httpError {status}, linkcheck.blocked {status}, linkcheck.unreachable,
  linkcheck.insecureRedirect {location}, linkcheck.tooManyRedirects, linkcheck.privateAddress,
  linkcheck.invalid
"""
import ipaddress
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

TIMEOUT = float(os.environ.get("PORTAL_LINKCHECK_TIMEOUT", "8"))
MAX_REDIRECTS = 5
CACHE_SECONDS = 600
WORKERS = 8
ALLOW_PRIVATE = os.environ.get("PORTAL_LINKCHECK_ALLOW_PRIVATE") == "1"
USER_AGENT = "GS1-Resolver-CE-LinkChecker/1.0"

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _public_host(host: str) -> bool | None:
    """True if every address of the host is global; False if one is not; None if it does not resolve."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return None
    if ALLOW_PRIVATE:
        return True
    return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)


def is_downgrade(from_url: str, to_url: str) -> bool:
    """Whether a redirect goes from HTTPS to plain HTTP."""
    return urlparse(from_url).scheme == "https" and urlparse(to_url).scheme == "http"


def _request(session: requests.Session, url: str) -> requests.Response:
    """One request without following redirects: HEAD, or GET without reading the body when HEAD is refused."""
    response = session.head(url, allow_redirects=False, timeout=TIMEOUT)
    if response.status_code in (400, 403, 405, 501):     # many servers refuse or mishandle HEAD
        response.close()
        response = session.get(url, allow_redirects=False, timeout=TIMEOUT, stream=True)
    response.close()                                    # the body is never read
    return response


def check_url(url: str) -> dict:
    """Result of checking one address, cached for CACHE_SECONDS."""
    now = time.time()
    with _cache_lock:
        cached = _cache.get(url)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    result = _check(url)
    with _cache_lock:
        _cache[url] = (now, result)
    return result


def _result(url, problem=None, http_status=None, final=None, **params) -> dict:
    """The result of a check: ok, problem code, HTTP status, final address and message parameters."""
    return {"url": url, "ok": problem is None, "problem": problem, "status": http_status,
            "finalUrl": final or url, "params": params}


def _check(url: str) -> dict:
    """Follows the redirects of an address by hand, refusing private addresses at every step (SSRF guard)
    and HTTPS → HTTP downgrades; reports errors, blocked checks and unreachable sites.
    """
    current = url
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return _result(url, "linkcheck.invalid", final=current)
            public = _public_host(parsed.hostname)
            if public is None:
                return _result(url, "linkcheck.unreachable", final=current)
            if not public:
                return _result(url, "linkcheck.privateAddress", final=current)
            try:
                response = _request(session, current)
            except requests.RequestException:
                return _result(url, "linkcheck.unreachable", final=current)
            status = response.status_code
            if 300 <= status < 400 and response.headers.get("Location"):
                target = urljoin(current, response.headers["Location"])
                if is_downgrade(current, target):
                    return _result(url, "linkcheck.insecureRedirect", status, target, location=target)
                current = target
                continue
            if status < 400:
                return _result(url, http_status=status, final=current)
            if status in (401, 403, 429):
                # The site answers but refuses automated checks: the page may well be fine for people.
                return _result(url, "linkcheck.blocked", status, current, status=status)
            return _result(url, "linkcheck.httpError", status, current, status=status)
    return _result(url, "linkcheck.tooManyRedirects", final=current)


def check_many(urls: list[str], progress=None) -> dict[str, dict]:
    """Checks distinct URLs in parallel; progress(done, total) is called after each one."""
    distinct = list(dict.fromkeys(u for u in urls if u))
    results, done = {}, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for url, result in zip(distinct, pool.map(check_url, distinct)):
            results[url] = result
            done += 1
            if progress:
                progress(done, len(distinct))
    return results
