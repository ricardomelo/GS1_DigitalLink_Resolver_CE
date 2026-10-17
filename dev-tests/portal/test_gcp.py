"""
GS1's GCP length table (backlog item 9.9, Documentation/adr/0015-gcp-length-table.md), with a small table of its own in
GS1's format (GS1's list is restricted and never in the repository): the parser (plain, with a byte order mark and a
comment, or gzip as the page sends it; every refusal — not XML, a DOCTYPE, the root, the date, another element, an
entry's prefix or length, a prefix twice, an empty list, a list too large once decompressed), the longest matching
prefix and length 0, the list stored in one step (a refused list leaves the one in use; an older list refused unless
confirmed), each process reading a newer list, the company prefix of each kind of key, an organisation's prefix
against the list, the routes (who may upload, support access, the journal, the configuration, the lookup), the
warnings on the organisation's page and the organisations' list, the EPC's partition from the list (the person's
choice first, length 0 refused, the organisation's prefixes without an entry), and the command line.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_gcp.py
"""
import contextlib
import gzip
import io
import os
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3397
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_gcp_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("PORTAL_EXPORT_LIMITS", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import gcp  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
store.col("gcp_table").delete_many({})       # a real MongoDB may hold an earlier run's list
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


def gtin(body):
    return body + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body))) % 10) % 10)


def table(entries, date="2026-09-17T11:04:36.316Z", root="GCPPrefixFormatList", head="﻿<!--A test list in GS1's "
          "format, made for these tests.-->\n"):
    body = "".join(f'  <entry prefix="{p}" gcpLength="{n}" />\n' for p, n in entries)
    return (f'{head}<{root} date="{date}">\n{body}</{root}>\n').encode("utf-8")


ENTRIES = [("20", 0), ("7890", 7), ("7891", 7), ("7895", 7), ("7896", 8), ("78983", 9), ("7898357", 12),
           ("950600", 7), ("9506001", 12), ("978", 0)]
LIST = table(ENTRIES)


def refused(data, expected):
    try:
        gcp.parse(data)
    except gcp.GcpError as exc:
        return exc.code == expected, (exc.code, exc.params)
    return False, "accepted"


# --------------------------------------------------------------------------- the parser
t = gcp.parse(LIST)
check("a list with a byte order mark and a comment is read: its date (UTC, to the second) and entries",
      t.date == "2026-09-17T11:04:36Z" and len(t) == 10, (t.date, len(t)))
check("…gzip, as the page sends it, gives the same list", gcp.parse(gzip.compress(LIST)).prefixes == t.prefixes)
check("…a date with another offset in UTC", gcp.parse(table(ENTRIES, date="2026-09-17T08:00:00-03:00")).date
      == "2026-09-17T11:00:00Z")
check("the longest matching prefix wins (7898357… → 12, 78983… → 9, 7896… → 8)",
      (t.length_for("789835741001"), t.length_for("789830000000"), t.length_for("789612345678")) == (12, 9, 8))
check("…length 0: not a GS1 Company Prefix (20…, 978…)", t.length_for("200000000000") == 0 and t.length_for("9781") == 0)
check("…no entry: None", t.length_for("123456789012") is None and t.length_for("") is None)
check("…the counts per length", t.counts() == {"0": 2, "7": 4, "8": 1, "9": 1, "12": 2}, t.counts())
CASES = [
    (b"hello", "gcp.notXml"),
    (b"\x1f\x8bnot really gzip", "gcp.notXml"),
    (b"<GCPPrefixFormatList date='2026-09-17T11:04:36Z'><entry prefix='789' gcpLength='7'>", "gcp.notXml"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><GCPPrefixFormatList date="2026-09-17T11:04:36Z">'
     b'<entry prefix="789" gcpLength="7"/></GCPPrefixFormatList>', "gcp.doctype"),
    (table(ENTRIES, root="PrefixList"), "gcp.root"),
    (table(ENTRIES, date="17/09/2026"), "gcp.date"),
    (table(ENTRIES, date=""), "gcp.date"),
    (LIST.replace(b'<entry prefix="20"', b'<item prefix="20"'), "gcp.element"),
    (LIST.replace(b'<entry prefix="20" gcpLength="0" />', b'<entry prefix="20" gcpLength="0"><x/></entry>'), "gcp.element"),
    (table([("78a9", 7)]), "gcp.entry"),
    (table([("7891234567890", 12)]), "gcp.entry"),
    (table([("", 7)]), "gcp.entry"),
    (table([("789", 5)]), "gcp.entry"),
    (table([("789", 13)]), "gcp.entry"),
    (table([("789", "x")]), "gcp.entry"),
    (table([("٧٨٩", 7)]), "gcp.entry"),
    (table([("789", 7), ("789", 8)]), "gcp.duplicate"),
    (table([]), "gcp.empty"),
]
for data, expected in CASES:
    ok, detail = refused(data, expected)
    check(f"refused with {expected}: {data[:70]!r}", ok, detail)
ok, detail = refused(table([("789", 5)]), "gcp.entry")
try:
    gcp.parse(table([("7890", 7), ("789", 5)]))
except gcp.GcpError as exc:
    check("…the refusal names the entry (its prefix, length and number)",
          exc.params == {"prefix": "789", "length": "5", "number": 2}, exc.params)
limit = gcp.MAX_XML_BYTES
gcp.MAX_XML_BYTES = 2000
ok, detail = refused(gzip.compress(table([(f"78{n:04d}", 7) for n in range(200)])), "gcp.tooLarge")
check("a list larger than the limit once decompressed refused (a small gzip of a large file)", ok, detail)
ok, detail = refused(table([(f"78{n:04d}", 7) for n in range(200)]), "gcp.tooLarge")
check("…and plain", ok, detail)
gcp.MAX_XML_BYTES = limit

# --------------------------------------------------------------------------- stored and read
check("no list at first: no info, no lookup", gcp.info() is None and gcp.lookup("/01/07898357410015") is None
      and gcp.check_prefix("7891234") is None)
saved = gcp.save(t, "root")
check("a list stored: date, count, counts, who and when", saved["date"] == "2026-09-17T11:04:36Z" and saved["count"] == 10
      and saved["lengths"]["7"] == 4 and saved["uploadedBy"] == "root" and saved["uploadedAt"].endswith("Z"), saved)
check("…as one document, compacted", store.col("gcp_table").count_documents({}) == 1
      and len(bytes(store.col("gcp_table").find_one()["data"])) < len(LIST))
older = gcp.parse(table(ENTRIES[:3], date="2026-08-01T00:00:00Z"))
try:
    gcp.save(older, "root")
    check("an older list refused unless confirmed", False, "stored")
except gcp.GcpError as exc:
    check("an older list refused unless confirmed (gcp.older, both dates)", exc.code == "gcp.older"
          and exc.params == {"date": "2026-08-01T00:00:00Z", "current": "2026-09-17T11:04:36Z"}, exc.params)
check("…the list in use unchanged", gcp.info()["count"] == 10)
check("…confirmed: stored", gcp.save(older, "root", force=True)["count"] == 3 and len(gcp.current()) == 3)
gcp.save(t, "root")
gcp.RECHECK_SECONDS = 3600
before = gcp.current()
store.col("gcp_table").update_one({"_id": "current"}, {"$set": {"sha256": "x"}})   # another process stored a list
check("each process keeps its copy between checks", gcp.current() is before)
gcp.RECHECK_SECONDS = 0
check("…and reads the stored list again once it changed", gcp.current() is not before and len(gcp.current()) == 10)
gcp.RECHECK_SECONDS = 60

LOOKUPS = [
    ("/01/07898357410015", "789835741001", 12),    # GTIN-13 as GTIN-14: after the indicator digit
    (f"/01/1{gtin('789612345678')}", "78961234", 8),
    (f"/414/{gtin('789123456789')}", "7891234", 7),
    (f"/00/3{gtin('7891234567890123')}", "7891234", 7),
    (f"/8003/0{gtin('789123456789')}AB12", "7891234", 7),
    ("/8004/7891234ASSET-9", "7891234", 7),
]
for anchor, prefix, length in LOOKUPS:
    found = gcp.lookup(anchor)
    check(f"the company prefix of {anchor}: {prefix} ({length} digits)", found and found["prefix"] == prefix
          and found["length"] == length and found["date"] == "2026-09-17T11:04:36Z", found)
found = gcp.lookup(f"/01/0{gtin('200000000001')}")
check("…a range that is not a GS1 Company Prefix: length 0, no prefix", found == {"prefix": None, "length": 0,
                                                                                  "date": "2026-09-17T11:04:36Z"}, found)
found = gcp.lookup(f"/01/0{gtin('123456789012')}")
check("…no entry: length None", found["length"] is None and found["prefix"] is None, found)
STATUSES = [("7891234", "ok", 7), ("78983", "shorter", 9), ("78912345678", "longer", 7), ("2000", "notGcp", 0),
            ("1234567", "unknown", None)]
for prefix, status, length in STATUSES:
    check(f"an organisation's prefix {prefix} against the list: {status}", gcp.check_prefix(prefix) ==
          {"prefix": prefix, "status": status, "length": length}, gcp.check_prefix(prefix))

# --------------------------------------------------------------------------- the routes
store.col("gcp_table").delete_many({})
gcp.forget()
acme = tenants.create("Acme Foods", ["7898357", "7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
root, ana, edu = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu"))


def upload(c, data, confirm=False, kind=None):
    kind = kind or ("application/gzip" if data[:2] == b"\x1f\x8b" else "application/xml")
    return c.post("/portal/api/gcp" + ("?confirm=1" if confirm else ""), data=data, headers={**ORIGIN, "Content-Type": kind})


check("the page knows there is no list", edu.get("/portal/api/config").get_json()["gcpTable"] is None)
r = root.get("/portal/api/gcp")
check("a server administrator reads the list in use (none)", r.status_code == 200 and r.get_json()["table"] is None,
      r.get_json())
check("…an organisation's administrator may not", ana.get("/portal/api/gcp").status_code == 403)
r = upload(root, LIST, kind="text/plain")
check("…a type a form of another site could send: 415, nothing stored", r.status_code == 415 and gcp.info() is None)
r = root.post("/portal/api/gcp", data=gzip.compress(LIST), headers={"Origin": "https://evil.example",
                                                                    "Content-Type": "application/gzip"})
check("…another site's page: 403", r.status_code == 403 and gcp.info() is None)
r = upload(ana, gzip.compress(LIST))
check("…nor upload one: 403, nothing stored", r.status_code == 403 and gcp.info() is None)
r = upload(root, gzip.compress(table([("789", 5)])))
check("a refused list: 422 with the problem, nothing stored", r.status_code == 422 and code(r) == "gcp.entry"
      and gcp.info() is None, r.get_json())
r = upload(root, gzip.compress(LIST))
check("the server administrator uploads GS1's list (gzip): 200 gcp.loaded with its date and count",
      r.status_code == 200 and code(r) == "gcp.loaded" and r.get_json()["params"] == {
          "date": "2026-09-17T11:04:36Z", "count": 10} and r.get_json()["table"]["uploadedBy"] == "root", r.get_json())
r = upload(root, LIST)
check("…plain XML too", r.status_code == 200 and code(r) == "gcp.loaded")
check("…in the journal with its date and count", any(e.get("detail") == "date=2026-09-17T11:04:36Z count=10"
      for e in store.col("journal").find({"action": "gcp-upload"})))
check("…the page is told", edu.get("/portal/api/config").get_json()["gcpTable"] == {
    "date": "2026-09-17T11:04:36Z", "count": 10})
r = upload(root, table(ENTRIES[:2], date="2026-01-01T00:00:00Z"))
check("an older list: 409 gcp.older with both dates, nothing changed", r.status_code == 409 and code(r) == "gcp.older"
      and r.get_json()["params"]["current"] == "2026-09-17T11:04:36Z" and gcp.info()["count"] == 10, r.get_json())
r = upload(root, table(ENTRIES[:2], date="2026-01-01T00:00:00Z"), confirm=True)
check("…confirmed: stored", r.status_code == 200 and gcp.info()["count"] == 2)
upload(root, LIST)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN)
r = upload(root, LIST)
check("support access: no upload (403 gcp.readOnly)", r.status_code == 403 and code(r) == "gcp.readOnly")
root.delete("/portal/api/support", headers=ORIGIN)
r = edu.get("/portal/api/gcp/lookup", query_string={"key": "01", "value": "07898357410015"})
check("any user looks up a key's company prefix", r.status_code == 200 and r.get_json() == {
    "prefix": "789835741001", "length": 12, "date": "2026-09-17T11:04:36Z"}, r.get_json())
r = edu.get("/portal/api/gcp/lookup", query_string={"key": "01", "value": "0789"})
check("…an invalid key refused: 422", r.status_code == 422, r.status_code)
page = ana.get("/portal/api/organisation").get_json()
check("the organisation's page: each prefix against the list (7898357 shorter than GS1's 12 digits there)",
      sorted(page["prefixChecks"], key=lambda c: c["prefix"]) == [{"prefix": "7891234", "status": "ok", "length": 7},
      {"prefix": "7898357", "status": "shorter", "length": 12}], page.get("prefixChecks"))
listed = next(x for x in root.get("/portal/api/tenants").get_json()["tenants"] if x["id"] == acme["id"])
check("…and the organisations' list", {c["prefix"]: c["status"] for c in listed["prefixChecks"]} == {
    "7898357": "shorter", "7891234": "ok"}, listed.get("prefixChecks"))
r = edu.get("/portal/api/organisation")
check("…(the page is an administrators' one)", r.status_code == 403)

# --------------------------------------------------------------------------- the EPC's partition
SERIAL = "/21/1001"


def sgtin(c, value, **params):
    return c.get("/portal/api/epc", query_string={"key": "01", "value": value, "qualifiers": SERIAL, **params})


r = sgtin(edu, "07898357410015")
body = r.get_json()
check("the EPC's partition from the list (12 digits for 7898357…), said so", r.status_code == 200
      and body["prefixLength"] == 12 and body["prefixFrom"] == "table" and body["tableDate"] == "2026-09-17T11:04:36Z"
      and body["tagUri"].startswith("urn:epc:tag:sgtin-96:1.789835741001.0."), body)
r = sgtin(edu, "07898357410015", prefixLength="7")
check("…the person's choice first", r.get_json()["prefixLength"] == 7 and r.get_json()["prefixFrom"] == "chosen")
store.col("gcp_table").delete_many({})
gcp.forget()
r = sgtin(edu, "07898357410015")
check("…without a list: the organisation's prefixes, as before", r.get_json()["prefixLength"] == 7
      and r.get_json()["prefixFrom"] == "prefixes", r.get_json())
upload(root, LIST)
gcp.forget()
r = sgtin(root, "0" + gtin("200000000001"))                     # the operator's
check("…a range the list says is not a GS1 Company Prefix: 422 epc.notGcp with the list's date", r.status_code == 422
      and code(r) == "epc.notGcp" and r.get_json()["params"] == {"date": "2026-09-17T11:04:36Z"}, r.get_json())
r = sgtin(root, "0" + gtin("200000000001"), prefixLength="7")
check("…unless the person chooses a length", r.status_code == 200 and r.get_json()["prefixFrom"] == "chosen")
other = gtin("789123400001")
check("…a key the list knows: its length (7)", sgtin(edu, "0" + other).get_json()["prefixFrom"] == "table")

# --------------------------------------------------------------------------- the command line
def command(*args, stdin=b""):
    """gcp.py's command line, in this process (the database of the tests is in memory)."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = gcp._main(list(args))
    finally:
        sys.stdin = saved
    return status, out.getvalue(), err.getvalue()


path = os.path.join(CONFIG, "list.xml")
open(path, "wb").write(table(ENTRIES, date="2026-10-01T00:00:00Z"))
status, out, err = command("load", path)
check("the command line loads a list", status == 0 and "2026-10-01T00:00:00Z: 10 prefixes" in out, (status, out, err))
status, out, err = command("load", "-", stdin=table([("1", 5)]))
check("…refuses a bad one from standard input", status == 1 and "gcp.entry" in err, (status, err))
status, out, err = command("load", "-", stdin=table(ENTRIES[:1], date="2026-01-01T00:00:00Z"))
check("…an older one only with --force", status == 1 and "gcp.older" in err
      and command("load", "-", "--force", stdin=table(ENTRIES[:1], date="2026-01-01T00:00:00Z"))[0] == 0)
status, out, err = command("info")
check("…and says which list is in use", status == 0 and "2026-01-01T00:00:00Z: 1 prefixes" in out
      and "command line" in out, out)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
check("every message of the list in both languages", all(i18n.count(f'"gcp.{c}"') == 2 for c in (
    "notXml", "doctype", "root", "date", "element", "entry", "duplicate", "empty", "tooLarge", "older", "loaded",
    "readOnly")))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
