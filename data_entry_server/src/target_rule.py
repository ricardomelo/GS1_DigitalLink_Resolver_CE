"""
The target address rule of the data entry API (Documentation/adr/0048-data-entry-target-rule.md): the rule the portal
applies to every target it saves (portal/gs1.py, normalise_url() and target_host_problem(); ADR 0037), here for the
targets that reach the data entry API from any other client. A target is an https address with a public host name:
no spaces, control or invisible characters or backslashes; no user name or password before the host; no IP address
however written; no name that only a network's own resolvers answer (localhost, .local, .internal, .home.arpa…).

The portal's module is not imported: the data entry API is an image of its own. dev-tests/resolver/test_data_entry_api.py
compares the two rules on the same addresses, so that they cannot drift apart.
"""
import re
import unicodedata
from urllib.parse import urlparse, urlsplit

# The same names as portal/gs1.py's PRIVATE_TOP_NAMES (ADR 0037, section 2.1).
PRIVATE_TOP_NAMES = frozenset(("localhost", "local", "localdomain", "internal", "intranet", "lan", "home", "corp",
                               "test", "onion", "alt", "arpa"))
# A host whose last label is a number is an IPv4 address to a browser, however it is written (WHATWG URL Standard,
# "ends in a number").
_NUMERIC_LABEL = re.compile(r"(?:0x[0-9a-f]*|[0-9]+)")
_HOST_LABEL = re.compile(r"[a-z0-9_-]+")

# What the API answers for each problem; the codes are the portal's message codes without "link.".
REASONS = {
    "urlRequired": "a link needs a target address (href)",
    "urlChars": "a target address cannot hold spaces, line breaks, control or invisible characters or backslashes",
    "urlInvalid": "a target address must be an https address with a host name and, if any, a numeric port",
    "urlUserInfo": "a target address cannot name a user or password before its host",
    "urlAddress": "a target address must name its host, not an IP address",
    "urlHost": "a target address must name a public host (no localhost, .local, .internal, .home.arpa or name "
               "without a dot)",
}


def _host_problem(host: str) -> str | None:
    """portal/gs1.py's host_problem(): urlAddress, urlHost or None for the host as urlsplit() gives it."""
    host = unicodedata.normalize("NFKC", host or "").lower()
    host = host.replace("。", ".").replace("．", ".").replace("｡", ".")
    if ":" in host:
        return "urlAddress"
    host = host[:-1] if host.endswith(".") else host
    labels = host.split(".")
    if not host or not all(labels):
        return "urlHost"
    if _NUMERIC_LABEL.fullmatch(labels[-1]):
        return "urlAddress"
    if any(not _HOST_LABEL.fullmatch(label) and not all(ord(c) > 127 or _HOST_LABEL.fullmatch(c) for c in label)
           for label in labels):
        return "urlHost"
    if len(labels) < 2 or labels[-1] in PRIVATE_TOP_NAMES:
        return "urlHost"
    return None


def target_problem(href) -> str | None:
    """Why href cannot be a target, as a code of REASONS (the portal's normalise_url() refuses the same addresses with
    the same codes), or None. The address is checked as sent: the portal stores it trimmed, so a target with spaces
    around it is refused here rather than changed."""
    if not isinstance(href, str) or not href.strip():
        return "urlRequired"
    if any(c.isspace() or c == "\\" or unicodedata.category(c) in ("Cc", "Cf") for c in href):
        return "urlChars"
    parsed = urlparse(href)
    if parsed.scheme != "https" or not parsed.netloc:
        return "urlInvalid"
    if "@" in parsed.netloc:
        return "urlUserInfo"
    try:
        parts = urlsplit(href)
        parts.port                                      # raises ValueError for a port that is not a number
    except ValueError:
        return "urlInvalid"
    return _host_problem(parts.hostname or "")


def document_hrefs(document: dict | None) -> set[str]:
    """Every target of a key's document as stored (data[].linkset[]: lists of links, and the defaultLink objects)."""
    hrefs = set()
    for entry in (document or {}).get("data") or []:
        for linkset in entry.get("linkset") or []:
            for value in linkset.values() if isinstance(linkset, dict) else []:
                for link in value if isinstance(value, list) else [value]:
                    if isinstance(link, dict) and isinstance(link.get("href"), str):
                        hrefs.add(link["href"])
    return hrefs


def hrefs_problem(hrefs, stored: set[str] = frozenset()) -> str | None:
    """The first of the targets sent (an entry's links, or a v2 entry's responses, in order) that breaks the rule, as
    the API's message, or None. A target already stored in the key's document (stored) is accepted as it is: records
    saved before this rule keep working, and a rewrite of them (the portal's explicit default links, its serial-number
    fix) is not refused for a target it did not choose."""
    for position, href in enumerate(hrefs, start=1):
        if isinstance(href, str) and href in stored:
            continue
        code = target_problem(href)
        if code:
            shown = href[:200] if isinstance(href, str) else href
            return f"link {position} ({shown!r}): {REASONS[code]}"
    return None
