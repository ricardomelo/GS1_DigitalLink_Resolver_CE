"""
Link checker: does each target address answer, and does it stay on HTTPS?

For every URL: a HEAD request (GET when the server refuses HEAD), following up to MAX_REDIRECTS
redirects one by one so that a hop from https:// to http:// can be reported. Results are cached for
CACHE_SECONDS in the "linkcheck_cache" collection of the portal's database (shared by every replica, emptied
by MongoDB through a TTL index) so that checking the same addresses again does not hammer the sites.

Only HTTPS addresses on public addresses are contacted (Documentation/adr/0029-outbound-requests.md): an http://
address is reported without a request; a host name resolving to a private, loopback, link-local or other non-global
address (the Docker network, the cloud metadata service, …) is refused, at every hop, and the request is made to the
address checked, not to the name resolved again (outbound.request()), so that the portal cannot be used to probe the
server's own network. At most PER_HOST requests to one host run at once. PORTAL_LINKCHECK_ALLOW_PRIVATE=1 lifts the
address and HTTPS rules for development tests only.

A daily budget per organisation (Documentation/adr/0060-link-check-budget.md): reserve() counts the addresses each
check asks for against the organisation's day (the installation's time zone) in the "linkcheck_budget" collection, at
most PORTAL_LINKCHECK_DAILY_LIMIT (default DAILY_LIMIT; 0 for none), atomically, so that an editor cannot make the
server send an unbounded number of requests to third parties.

Result: {"url", "ok", "problem" (message code or None), "status", "finalUrl", "params"}
  problem codes: linkcheck.httpError {status}, linkcheck.blocked {status}, linkcheck.unreachable,
  linkcheck.insecureRedirect {location}, linkcheck.insecureAddress, linkcheck.tooManyRedirects,
  linkcheck.privateAddress, linkcheck.invalid
"""
import os
import threading
from collections import defaultdict
from itertools import zip_longest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import logging

import requests
from pymongo.errors import DuplicateKeyError, PyMongoError

import outbound
import requestlog
import store

log = logging.getLogger(__name__)

TIMEOUT = float(os.environ.get("PORTAL_LINKCHECK_TIMEOUT", "8"))
MAX_REDIRECTS = 5
CACHE_SECONDS = 600
WORKERS = 8
PER_HOST = 2               # requests to one host at once, whatever the number of its addresses in a check
ALLOW_PRIVATE = os.environ.get("PORTAL_LINKCHECK_ALLOW_PRIVATE") == "1"
USER_AGENT = "GS1-Resolver-CE-LinkChecker/1.0"
DAILY_LIMIT = 20000        # addresses an organisation may have checked a day (ADR 0060): four checks of every record
BUDGET = "linkcheck_budget"



def is_downgrade(from_url: str, to_url: str) -> bool:
    """Whether a redirect goes from HTTPS to plain HTTP."""
    return urlparse(from_url).scheme == "https" and urlparse(to_url).scheme == "http"


def _request(url: str) -> requests.Response:
    """One request without following redirects, to a checked address of the name: HEAD, or GET without reading the
    body when HEAD is refused."""
    headers = {"User-Agent": USER_AGENT}
    response = outbound.request("HEAD", url, ALLOW_PRIVATE, timeout=TIMEOUT, headers=headers)
    if response.status_code in (400, 403, 405, 501):     # many servers refuse or mishandle HEAD
        response.close()
        response = outbound.request("GET", url, ALLOW_PRIVATE, timeout=TIMEOUT, headers=headers, stream=True)
    response.close()                                    # the body is never read
    return response


def check_url(url: str) -> dict:
    """Result of checking one address, cached for CACHE_SECONDS (a database failure only skips the cache)."""
    cache = store.col("linkcheck_cache")
    try:
        cached = cache.find_one({"_id": url, "expiresAt": {"$gt": store.now()}})
    except PyMongoError:
        cached = None
    if cached:
        return cached["result"]
    result = _check(url)
    try:
        cache.replace_one({"_id": url}, {"result": result, "expiresAt": store.now() + timedelta(seconds=CACHE_SECONDS)},
                          upsert=True)
    except PyMongoError:
        pass
    return result


class OverBudget(Exception):
    """The addresses asked for do not fit in what is left of the organisation's day (ADR 0060)."""

    def __init__(self, limit: int, left: int):
        super().__init__(f"{left} of {limit} addresses left today")
        self.limit, self.left = limit, left


def daily_limit() -> int:
    """PORTAL_LINKCHECK_DAILY_LIMIT, the addresses an organisation may have checked a day; 0 for no limit; DAILY_LIMIT
    when it is not set or not a whole number."""
    try:
        value = int(os.environ.get("PORTAL_LINKCHECK_DAILY_LIMIT", "").strip() or DAILY_LIMIT)
    except ValueError:
        log.warning("PORTAL_LINKCHECK_DAILY_LIMIT is not a whole number; %d addresses a day apply", DAILY_LIMIT)
        value = DAILY_LIMIT
    return max(0, value)


def _budget_id(tenant: str | None, day) -> str:
    return f"{tenant or '-'}|{day.isoformat()}"


def used_today(tenant: str | None) -> int:
    """The addresses the organisation (None: the operator) has had checked today."""
    doc = store.col(BUDGET).find_one({"_id": _budget_id(tenant, requestlog.today())}) or {}
    return int(doc.get("n", 0))


def reserve(tenant: str | None, count: int) -> None:
    """Counts count addresses against the organisation's day (None: the operator's), or raises OverBudget and counts
    nothing. One conditional update: two checks started at once cannot both pass the limit. Addresses are counted
    when asked for, cached or not, and are not given back when a check is stopped. When the database cannot be read
    the check goes ahead (logged): it cannot be queued without the database anyway."""
    limit = daily_limit()
    if not limit or count <= 0:
        return
    day = requestlog.today()
    key = _budget_id(tenant, day)
    collection = store.col(BUDGET)
    try:
        if count > limit:
            raise DuplicateKeyError("more than a day's budget")
        collection.update_one({"_id": key, "n": {"$lte": limit - count}},
                              {"$inc": {"n": count},
                               "$setOnInsert": {"tenant": tenant, "day": day.isoformat(),
                                                "expiresAt": store.now() + timedelta(days=2)}},
                              upsert=True)
    except DuplicateKeyError:
        # the day's document exists and does not leave room for count addresses
        try:
            used = int((collection.find_one({"_id": key}) or {}).get("n", 0))
        except PyMongoError:
            used = limit
        raise OverBudget(limit, max(0, limit - used)) from None
    except PyMongoError as exc:
        log.warning("Link check budget not counted (%s); the check goes ahead", exc)


def clear_cache() -> None:
    """Forgets every cached result (development tests)."""
    store.col("linkcheck_cache").delete_many({})


def _result(url, problem=None, http_status=None, final=None, **params) -> dict:
    """The result of a check: ok, problem code, HTTP status, final address and message parameters."""
    return {"url": url, "ok": problem is None, "problem": problem, "status": http_status,
            "finalUrl": final or url, "params": params}


def _check(url: str) -> dict:
    """Follows the redirects of an address by hand, refusing http:// and private addresses at every step (SSRF guard)
    and HTTPS → HTTP downgrades; reports errors, blocked checks and unreachable sites.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        try:
            scheme = outbound.target(current)[0]
        except outbound.BadAddress:
            return _result(url, "linkcheck.invalid", final=current)
        if scheme != "https" and not ALLOW_PRIVATE:
            return _result(url, "linkcheck.insecureAddress", final=current)
        try:
            response = _request(current)
        except outbound.Unresolvable:
            return _result(url, "linkcheck.unreachable", final=current)
        except outbound.PrivateAddress:
            return _result(url, "linkcheck.privateAddress", final=current)
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


def _host(url: str) -> str:
    """The host of an address, for the limit of requests to one host at once ("" when there is none)."""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def check_many(urls: list[str], progress=None) -> dict[str, dict]:
    """Checks distinct URLs in parallel, at most PER_HOST at once to one host; progress(done, total) is called after
    each one (an exception it raises stops the check: the addresses not started are not requested)."""
    distinct = list(dict.fromkeys(u for u in urls if u))
    by_host = defaultdict(list)
    for url in distinct:
        by_host[_host(url)].append(url)
    gates = {host: threading.BoundedSemaphore(PER_HOST) for host in by_host}
    # one host after another (round robin), so that the threads waiting at one host's gate do not hold up the others
    order = [url for group in zip_longest(*by_host.values()) for url in group if url]

    def one(url):
        with gates[_host(url)]:
            return check_url(url)

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(one, url): url for url in order}
        try:
            for future in as_completed(futures):              # as they finish: the gates change the order
                results[futures[future]] = future.result()
                if progress:
                    progress(len(results), len(distinct))
        finally:
            for future in futures:                            # stopped (an exception): the ones not started
                future.cancel()
    return {url: results[url] for url in distinct}
