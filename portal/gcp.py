"""
GS1's GCP length table (Documentation/adr/0015-gcp-length-table.md; backlog item 9.9): how many digits the GS1 Company
Prefix of a key has, from GS1's list of prefixes (GCPPrefixFormatList, an XML file the server administrator uploads;
the list is GS1's and restricted, so it is never in the repository).

    <GCPPrefixFormatList date="2026-09-17T11:04:36.316Z">
      <entry prefix="7896" gcpLength="8" />
      …

The list is checked, compacted ("prefix length" lines, gzip) and stored as one document of the "gcp_table" collection
(_id "current"), replaced in one step. Each process loads it when first needed and looks for a newer one at most once a
minute. A key's GS1 Company Prefix has the length of the longest entry its company part starts with; a length of 0
means the range is not a GS1 Company Prefix.

  python gcp.py load FILE|- [--force]     checks and stores a list (- reads standard input)
  python gcp.py info                      the list in use
"""
import bisect
import gzip
import hashlib
import io
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone

from bson.binary import Binary

import gs1
import store

ROOT = "GCPPrefixFormatList"
LENGTHS = {0, 6, 7, 8, 9, 10, 11, 12}
MAX_PREFIX = 12
MAX_XML_BYTES = 64 * 1024 * 1024          # once decompressed: today's list is 9.2 MB
RECHECK_SECONDS = 60
DOC_ID = "current"


class GcpError(ValueError):
    """A list refused; code is a message code of the portal."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


class Table:
    """A list in memory: its date, its prefixes in order and the length of each."""

    def __init__(self, date: str, entries: dict[str, int]):
        self.date = date
        self.prefixes = sorted(entries)
        self.lengths = bytes(entries[p] for p in self.prefixes)

    def __len__(self) -> int:
        return len(self.prefixes)

    def length_for(self, digits: str) -> int | None:
        """The length of the longest prefix the digits start with, or None when no entry matches."""
        for size in range(min(MAX_PREFIX, len(digits)), 0, -1):
            head = digits[:size]
            i = bisect.bisect_left(self.prefixes, head)
            if i < len(self.prefixes) and self.prefixes[i] == head:
                return self.lengths[i]
        return None

    def counts(self) -> dict[str, int]:
        """How many entries have each length ({"7": 31031, …})."""
        found: dict[str, int] = {}
        for n in self.lengths:
            found[str(n)] = found.get(str(n), 0) + 1
        return found

    def compact(self) -> bytes:
        return gzip.compress("".join(f"{p} {n}\n" for p, n in zip(self.prefixes, self.lengths)).encode("ascii"), 6)


def _decompressed(data: bytes) -> bytes:
    """The XML of an upload: gzip (as the page sends it) or plain, at most MAX_XML_BYTES."""
    if data[:2] == b"\x1f\x8b":
        out, inflater = bytearray(), zlib.decompressobj(31)
        try:
            chunk = inflater.decompress(data, MAX_XML_BYTES + 1)
            out += chunk
            while inflater.unconsumed_tail and len(out) <= MAX_XML_BYTES:
                out += inflater.decompress(inflater.unconsumed_tail, MAX_XML_BYTES + 1 - len(out))
        except zlib.error:
            raise GcpError("gcp.notXml")
        data = bytes(out)
    if len(data) > MAX_XML_BYTES:
        raise GcpError("gcp.tooLarge", max=MAX_XML_BYTES // (1024 * 1024))
    return data


def _date(text: str | None) -> str:
    """The list's date as ISO 8601 in UTC with a Z (to the second)."""
    try:
        moment = datetime.fromisoformat((text or "").strip().replace("Z", "+00:00"))
    except ValueError:
        raise GcpError("gcp.date")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(data: bytes) -> Table:
    """Checks a GCPPrefixFormatList (gzip or plain XML) and returns it, or raises GcpError naming the first problem."""
    data = _decompressed(data)
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if not head.startswith(b"<"):
        raise GcpError("gcp.notXml")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise GcpError("gcp.doctype")
    entries: dict[str, int] = {}
    date = None
    depth = 0
    try:
        for event, element in ET.iterparse(io.BytesIO(data), events=("start", "end")):
            if event == "start":
                depth += 1
                if depth == 1:
                    if element.tag != ROOT:
                        raise GcpError("gcp.root", root=element.tag[:60])
                    date = _date(element.get("date"))
                elif depth == 2 and element.tag != "entry":
                    raise GcpError("gcp.element", element=element.tag[:60])
                elif depth > 2:
                    raise GcpError("gcp.element", element=element.tag[:60])
                continue
            depth -= 1
            if element.tag != "entry" or depth != 1:
                continue
            prefix, length = (element.get("prefix") or "").strip(), (element.get("gcpLength") or "").strip()
            if not (prefix.isascii() and prefix.isdigit() and 1 <= len(prefix) <= MAX_PREFIX) \
                    or not (length.isascii() and length.isdigit() and int(length) in LENGTHS):
                raise GcpError("gcp.entry", prefix=prefix[:20], length=length[:20], number=len(entries) + 1)
            if prefix in entries:
                raise GcpError("gcp.duplicate", prefix=prefix)
            entries[prefix] = int(length)
            element.clear()
    except ET.ParseError as exc:
        raise GcpError("gcp.notXml", detail=str(exc)[:120])
    if not entries:
        raise GcpError("gcp.empty")
    return Table(date, entries)


# ------------------------------------------------------------------------------------------- the list in use
def _col():
    return store.col("gcp_table")


def info() -> dict | None:
    """The list in use: {date, count, lengths, uploadedBy, uploadedAt, sha256}, or None."""
    doc = _col().find_one({"_id": DOC_ID}, {"data": 0})
    if not doc:
        return None
    at = doc.get("uploadedAt")
    return {"date": doc.get("date"), "count": doc.get("count", 0), "lengths": doc.get("lengths") or {},
            "uploadedBy": doc.get("uploadedBy"), "sha256": doc.get("sha256"),
            "uploadedAt": at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(at, datetime) else at}


def save(table: Table, user: str, force: bool = False) -> dict:
    """Stores a checked list in place of the one in use, in one step. A list older than the one in use is refused
    (gcp.older) unless forced. Returns the new info()."""
    now = info()
    if now and not force and table.date < (now.get("date") or ""):
        raise GcpError("gcp.older", date=table.date, current=now["date"])
    data = table.compact()
    _col().replace_one({"_id": DOC_ID}, {
        "_id": DOC_ID, "date": table.date, "count": len(table), "lengths": table.counts(),
        "sha256": hashlib.sha256(data).hexdigest(), "uploadedBy": user, "uploadedAt": store.now(),
        "data": Binary(data)}, upsert=True)
    forget()
    return info()


_cache = {"table": None, "sha": None, "checked": 0.0}
_lock = threading.Lock()


def forget() -> None:
    """Drops this process's copy (the next lookup reads the stored list again)."""
    with _lock:
        _cache.update(table=None, sha=None, checked=0.0)


def current() -> Table | None:
    """The list in use in this process: read when first needed, again when the stored one changed (looked at most once
    every RECHECK_SECONDS). None without a list."""
    with _lock:
        if time.monotonic() - _cache["checked"] < RECHECK_SECONDS and _cache["checked"]:
            return _cache["table"]
        head = _col().find_one({"_id": DOC_ID}, {"sha256": 1})
        _cache["checked"] = time.monotonic()
        if not head:
            _cache.update(table=None, sha=None)
            return None
        if head.get("sha256") != _cache["sha"]:
            doc = _col().find_one({"_id": DOC_ID})
            entries = {}
            for line in gzip.decompress(bytes(doc["data"])).decode("ascii").splitlines():
                prefix, _, length = line.partition(" ")
                entries[prefix] = int(length)
            _cache.update(table=Table(doc["date"], entries), sha=doc.get("sha256"))
        return _cache["table"]


def lookup(anchor: str) -> dict | None:
    """A key's GS1 Company Prefix by the list in use: {prefix, length, date} (length 0: not a GS1 Company Prefix;
    prefix None then), {length: None, date} when the list has no entry for it, or None without a list."""
    table = current()
    if table is None:
        return None
    part = re.match(r"[0-9]*", gs1.company_part(anchor)).group()    # a GIAI's or GRAI's serial may follow
    length = table.length_for(part) if part else None
    return {"prefix": part[:length] if length and len(part) >= length else None, "length": length, "date": table.date}


def check_prefix(prefix: str) -> dict | None:
    """An organisation's prefix against the list: status ok (it is a GS1 Company Prefix of its length), longer (a part
    of a company prefix of `length` digits), shorter (it spans company prefixes of `length` digits), notGcp (a range
    that is not a GS1 Company Prefix), unknown (no entry); None without a list."""
    table = current()
    if table is None:
        return None
    length = table.length_for(prefix)
    if length is None:
        status = "unknown"
    elif length == 0:
        status = "notGcp"
    elif length == len(prefix):
        status = "ok"
    else:
        status = "longer" if length < len(prefix) else "shorter"
    return {"prefix": prefix, "status": status, "length": length}


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "load":
        source = sys.stdin.buffer.read() if argv[1] == "-" else open(argv[1], "rb").read()
        started = time.perf_counter()
        try:
            table = parse(source)
            stored = save(table, "command line", force="--force" in argv[2:])
        except GcpError as exc:
            print(f"Refused: {exc.code} {exc.params}", file=sys.stderr)
            return 1
        print(f"Loaded GS1's list of {stored['date']}: {stored['count']} prefixes "
              f"({time.perf_counter() - started:.1f} s).")
        return 0
    if argv[:1] == ["info"]:
        found = info()
        print("No list loaded." if not found else
              f"GS1's list of {found['date']}: {found['count']} prefixes, uploaded by {found['uploadedBy']} "
              f"on {found['uploadedAt']}.")
        return 0
    print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
