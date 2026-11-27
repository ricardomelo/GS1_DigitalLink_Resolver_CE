"""
Records outside the rules (ADR 0056; residuals of findings U-004 and U-003), through the portal's Flask test client
and the stand-in data entry API: documents written before the data entry API checked anchors (other anchor shapes, an
AI that is not a primary key, a value the portal's rules refuse) and targets the target rule refuses (http:,
javascript:, addresses inside a network) are listed for server administrators only — the counts and the first rows on
the screen, every row in CSV and XLSX with the browser's labels, a journal event for a file — the record's own page is
not checked, the organisation that holds the prefix is named, nothing is written, and the report's rule for targets is
the data entry API's.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_legacy.py
"""
import copy
import csv
import io
import os
import sys
import tempfile
import threading

from openpyxl import load_workbook
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(REPO, "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3417
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_legacy_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import legacy  # noqa: E402
import tenants  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
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


# ---- The rules, one value at a time ----
A, B = gtin("0789123450001"), gtin("0789555500001")
ANCHORS = [
    ("a GTIN-14 with its check digit", f"/01/{A}", None),
    ("a GIAI the portal accepts", "/8004/7891234AB12", None),
    ("a qualifier left in the anchor by the official API (/01/…/10/LOT, its id read back now)", f"/01/{A}_10_LOT",
     "keyValue"),
    ("a value with '_' (the portal's forms refuse it)", "/8004/7891234AB_12", "keyValue"),
    ("a wrong check digit", f"/01/{A[:-1]}{(int(A[-1]) + 1) % 10}", "keyValue"),
    ("a GTIN-13 stored as typed (the URI carries 14 digits)", f"/01/{A[1:]}", "keyValue"),
    ("an AI that is not a primary key", "/17/261231", "anchorShape"),
    ("an unknown AI", "/99/X", "anchorShape"),
    ("one segment", "/foo", "anchorShape"),
    ("three segments", f"/01/{A}/10", "anchorShape"),
    ("empty", "", "anchorShape"),
    ("not a text", None, "anchorShape"),
]
for name, anchor, expected in ANCHORS:
    got = legacy.anchor_problem(anchor)
    check(f"anchor: {name} → {expected}", got == expected, got)

TARGETS = [
    ("https to a public name", "https://acme.example.com/p", None),
    ("HTTPS in capitals", "HTTPS://acme.example.com/p", None),
    ("http", "http://acme.example.com/p", "targetNotHttps"),
    ("javascript:", "javascript:alert(1)", "targetNotHttps"),
    ("data:", "data:text/html,x", "targetNotHttps"),
    ("mailto:", "mailto:a@example.com", "targetNotHttps"),
    ("empty", "", "targetNotHttps"),
    ("not a text", None, "targetNotHttps"),
    ("an IPv4 address", "https://127.0.0.1/", "targetHost"),
    ("an IPv6 address", "https://[::1]/", "targetHost"),
    ("a private name", "https://printer.local/", "targetHost"),
    ("one label", "https://intranet/", "targetHost"),
    ("a user name before the host", "https://user@acme.example.com/", "targetHost"),
    ("a port that is not a number", "https://acme.example.com:x/", "targetForm"),
    ("a space inside", "https://acme.example.com/a b", "targetForm"),
    ("a space around (the API checks a target as sent)", " https://acme.example.com/p", "targetForm"),
    ("https without a host", "https:///p", "targetForm"),
]
for name, href, expected in TARGETS:
    got = legacy.target_problem(href)
    check(f"target: {name} → {expected}", got == expected, got)

# The data entry API's rule (data_entry_server/src/target_rule.py), address by address: what it accepts is not in the
# report, what it refuses is, and an address, a private name or a user name is targetHost
sys.path.append(os.path.join(REPO, "data_entry_server", "src"))
import target_rule  # noqa: E402
SAMPLE = [h for _, h, _ in TARGETS if isinstance(h, str)] + [
    "ftp://example.com/p", "https://:@example.com/p", "https://example.com:8443/", "https://127.1/", "https://0x7f.1/",
    "https://2130706433/", "https://[fe80::1]/", "https://localhost./", "https://x.internal/", "https://x.lan/",
    "https://router.home.arpa/", "https://x.corp/", "https://x.test/", "https://x.onion/", "https://a..b.com/",
    "https://%31%32%37.0.0.1/", "https://ex_ample.com/", "https://exämple.com/", "https://１２７.0.0.1/",
    "https://127。0。0。1/", "https://example.invalid/", "https://example.com/​", "https://example.com\\@x.com/",
    "https://example.com/p\tq", "https://example.com/{gtin}", "https://xn--exmple-cua.com/", "https://example.com./p",
    "https://example.com/p "]
HOST_CODES = {"urlUserInfo", "urlAddress", "urlHost"}
differ = [(h, legacy.target_problem(h), target_rule.target_problem(h)) for h in SAMPLE
          if (legacy.target_problem(h) is None) != (target_rule.target_problem(h) is None)
          or (legacy.target_problem(h) == "targetHost") != (target_rule.target_problem(h) in HOST_CODES)]
check(f"target: the report refuses the {len(SAMPLE)} sample addresses as the data entry API does (targetHost for an "
      "address, a private name or a user name)", not differ, differ)

# ---- The report over the resolver's documents ----
acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("rui", "rui-password-long", "reader", must_change=False)
root, ana, rui = client("root", "root-password-long"), client("ana", "ana-password-long"), client("rui", "rui-password-long")


def link(href, linktype="gs1:pip"):
    return {"linktype": linktype, "href": href, "title": "T", "hreflang": ["en"]}


def put(doc_id, entries, default="gs1:pip"):
    mock_data_entry.DB[doc_id] = {"default": default, "entries": [
        {"qualifiers": q, "itemDescription": "D", "links": links, "informative": []} for q, links in entries]}


mock_data_entry.DB.clear()
PAGE = f"http://localhost:8080/01/{A}?linkType=linkset&view=page"           # the portal's page: never checked
put(f"01_{A}", [([], [link("https://acme.example.com/p"), link(PAGE, "gs1:defaultLink")]),
                ([{"10": "L1"}], [link("http://acme.example.com/l1"), link("=HYPERLINK(1)", "gs1:epil")])])
put(f"01_{A}_10_LOT", [([], [link("https://acme.example.com/lot")]),
                       ([{"21": "S"}], [link("https://acme.example.com/s")])])  # one anchor row for its two entries
put("17_261231", [([], [link("javascript:alert(1)")])])
put(f"01_{B}", [([], [link("https://10.0.0.5/p")])])
before = copy.deepcopy(mock_data_entry.DB)
r = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN)
data = r.get_json() or {}
check("report: a server administrator gets the counts (200, JSON by default)",
      r.status_code == 200 and (data.get("total"), data.get("anchors"), data.get("targets")) == (6, 2, 4), data)
check("report: …by problem", data.get("byProblem") == {"anchorShape": 1, "keyValue": 1, "targetNotHttps": 3,
                                                        "targetHost": 1, "targetForm": 0}, data.get("byProblem"))
rows = data.get("rows") or []
check("report: …anchors first, one row per anchor, then the targets in the summary's order",
      [(x["problem"], x["anchor"]) for x in rows] == [
          ("keyValue", f"/01/{A}_10_LOT"), ("anchorShape", "/17/261231"),
          ("targetNotHttps", f"/01/{A}"), ("targetNotHttps", f"/01/{A}"), ("targetHost", f"/01/{B}"),
          ("targetNotHttps", "/17/261231")], [(x["problem"], x["anchor"]) for x in rows])
check("report: …a target row names the record's qualifiers, link type and target",
      {"qualifiers": "(10)L1", "linkType": "gs1:pip", "target": "http://acme.example.com/l1"}.items()
      <= rows[2].items(), rows[2])
check("report: …the organisation that holds the prefix is named, the operator's records and anchors of other shapes "
      "name none", (rows[0]["organisation"], rows[2]["organisation"], rows[4]["organisation"], rows[1]["organisation"])
      == ("Acme Foods", "Acme Foods", "", ""), [x["organisation"] for x in rows])
check("report: …the record's own page is not checked (an http address of the portal's)",
      not any(x["target"] == PAGE for x in rows))
check("report: …nothing written to the resolver", mock_data_entry.DB == before)
check("report: …and no journal event for a look", not list(store.col("journal").find({"action": "legacy-export"})))

r = ana.post("/portal/api/legacy-records", json={}, headers=ORIGIN)
check("access: an organisation's administrator is refused (403 access.serverAdmin)",
      r.status_code == 403 and code(r) == "access.serverAdmin", r.status_code)
r = rui.post("/portal/api/legacy-records", json={}, headers=ORIGIN)
check("access: the operator's reader is refused", r.status_code == 403 and code(r) == "access.serverAdmin", r.status_code)
check("access: without a session 401", portal.app.test_client().post("/portal/api/legacy-records", json={},
                                                                     headers=ORIGIN).status_code == 401)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN)
r = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN)
check("access: not during support access (the report is the whole installation's)", r.status_code == 403, r.status_code)
root.delete("/portal/api/support", headers=ORIGIN)
r = root.post("/portal/api/legacy-records", json={"format": "pdf"}, headers=ORIGIN)
check("format: another format is refused (422 legacy.format)", r.status_code == 422 and code(r) == "legacy.format",
      r.status_code)

LABELS = {"legacy.sheet": "Outside the rules", "legacy.col.problem": "Problem", "legacy.col.anchor": "Identifier",
          "legacy.col.qualifiers": "Qualifiers", "legacy.col.organisation": "Organisation",
          "legacy.col.linkType": "Link type", "legacy.col.target": "Target",
          "legacy.problem.anchorShape": "Not a GS1 key", "legacy.problem.keyValue": "Key value refused",
          "legacy.problem.targetNotHttps": "Not HTTPS", "legacy.problem.targetHost": "Inside a network",
          "legacy.problem.targetForm": "Badly written"}
r = root.post("/portal/api/legacy-records", json={"format": "csv", "labels": LABELS}, headers=ORIGIN)
text = r.get_data().decode("utf-8")
table = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
check("csv: a file (UTF-8 with BOM, ';') with the browser's labels",
      r.status_code == 200 and text.startswith("﻿") and table[0] == ["Problem", "Identifier", "Qualifiers",
                                                                         "Organisation", "Link type", "Target"]
      and "records-outside-the-rules-" in r.headers.get("Content-Disposition", ""), table[:1])
check("csv: …every row, the problem in the user's language", len(table) == 7 and table[1][0] == "Key value refused"
      and table[3][0] == "Not HTTPS", table)
check("csv: …a target that a spreadsheet would run as a formula is protected",
      any(row[-1] == "'=HYPERLINK(1)" for row in table), [row[-1] for row in table])
event = store.col("journal").find_one({"action": "legacy-export"})
check("csv: …a journal event legacy-export with the format and the counts",
      bool(event) and event.get("detail") == "csv anchors=2 targets=4", event)
r = root.post("/portal/api/legacy-records", json={"format": "xlsx", "labels": LABELS}, headers=ORIGIN)
book = load_workbook(io.BytesIO(r.get_data()))
sheet = book.active
values = [[c.value for c in row] for row in sheet.iter_rows()]
check("xlsx: one sheet named by the browser, the header and every row",
      r.status_code == 200 and sheet.title == "Outside the rules" and len(values) == 7 and values[0][1] == "Identifier",
      (sheet.title, len(values)))
check("xlsx: …the header in bold and frozen", sheet["A1"].font.bold and sheet.freeze_panes == "A2")

# A control character an XLSX cell cannot hold does not break the file
put("8004_7891234X", [([], [link("http://acme.example.com/\x01x")])])
r = root.post("/portal/api/legacy-records", json={"format": "xlsx", "labels": LABELS}, headers=ORIGIN)
check("xlsx: a target with a control character still gives a file", r.status_code == 200
      and load_workbook(io.BytesIO(r.get_data())).active.max_row == 8, r.status_code)

# Many rows: the screen gets the first SCREEN_ROWS, the files every row
for n in range(30):
    put(f"99_X{n}", [([], [link("https://acme.example.com/x")])])
data = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN).get_json()
check(f"screen: the first {legacy.SCREEN_ROWS} rows, the total of every row",
      len(data["rows"]) == legacy.SCREEN_ROWS and data["total"] == 37, (len(data["rows"]), data["total"]))
r = root.post("/portal/api/legacy-records", json={"format": "csv", "labels": LABELS}, headers=ORIGIN)
check("screen: …the file holds them all", len(r.get_data().decode("utf-8").strip().splitlines()) == 38)

# An empty resolver, a clean one, and one that cannot be read
mock_data_entry.DB.clear()
data = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN).get_json()
check("empty resolver: nothing outside the rules", data.get("total") == 0 and data.get("rows") == [], data)
put(f"01_{A}", [([], [link("https://acme.example.com/p")])])
data = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN).get_json()
check("records within the rules: nothing reported", data.get("total") == 0, data)
saved = portal.DATA_ENTRY_URL
portal.DATA_ENTRY_URL = "http://127.0.0.1:9/api"
r = root.post("/portal/api/legacy-records", json={}, headers=ORIGIN)
portal.DATA_ENTRY_URL = saved
check("resolver unreachable: an error answer, no report", r.status_code >= 500, r.status_code)

print(f"\n{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
