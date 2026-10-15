"""
Reading a scanned code for the record list's search (the backlog's code search from raw scanner data and RFID),
through the portal's Flask test client: raw scan data with a symbology identifier (DataMatrix ]d2 with the group
separator, QR ]Q1 with a GS1 Digital Link, GS1-128 ]C1), an element string without brackets (^ or the group separator
for FNC1, digits only), refusals with the GS1 Barcode Syntax Engine's reason; RFID EPCs (hexadecimal from a reader,
eh…, ex…) read through a stand-in resolver (the anchor of its linkset), an EPC without a record, one that does not
decode, a resolver that does not answer; sign-in required; the texts in both languages.

  pip install -r portal/requirements.txt mongomock (and the engine, GS1_SYNTAX_ENGINE_DIR, as for test_keys.py)
  python dev-tests/portal/test_scan_search.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3399
RESOLVER_PORT = 3400
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_scan_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)
os.environ["PORTAL_MONITOR_URL"] = f"http://127.0.0.1:{RESOLVER_PORT}/.well-known/gs1resolver"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import gs1  # noqa: E402
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


def image(kind="PNG", size=(60, 30), colour=(10, 120, 200)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind)
    return out.getvalue()


def data_uri(data, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))



from flask import Flask, jsonify  # noqa: E402

resolver = Flask("stand-in-resolver")
ASKED = []


@resolver.get("/<path:segment>")
def epc(segment):
    from flask import request
    ASKED.append((segment, request.args.get("linkType"), request.headers.get("Accept")))
    if segment.lower().startswith(("eh3074", "exmhq")):
        return jsonify(linkset=[{"anchor": "https://id.example.org/01/09506000134352/21/1001", "itemDescription": "x"}])
    if segment.lower().startswith("eh3000"):
        return jsonify(error="not found"), 404
    return jsonify(error="Not a decodable EPC binary string"), 400


threading.Thread(target=make_server("127.0.0.1", RESOLVER_PORT, resolver, threaded=True).serve_forever, daemon=True).start()
GS = "\x1d"


def read(text, who=None):
    return (who or ana).post("/portal/api/code/read", json={"text": text}, headers=ORIGIN)


if portal.syntax.ENGINE.available:
    for name, text, expected in (
            ("DataMatrix scan data (]d2, the group separator)", f"]d2010950600013435210L2026A{GS}21SER1",
             "(01)09506000134352(10)L2026A(21)SER1"),
            ("QR scan data with a GS1 Digital Link (]Q1)", "]Q1https://id.gs1.org/01/09506000134352/10/L1",
             "(01)09506000134352(10)L1"),
            ("GS1-128 scan data (]C1) of an SSCC", "]C100095060001343520000", "(00)095060001343520000"),
            ("an element string with ^ for FNC1", "0109506000134352^10LOT1^21S2", "(01)09506000134352(10)LOT1(21)S2"),
            ("an element string with the group separator", f"0109506000134352{GS}10LOT1", "(01)09506000134352(10)LOT1"),
            ("digits only", "0109506000134352", "(01)09506000134352")):
        r = read(text)
        check(f"read: {name}", r.status_code == 200 and r.get_json() == {"bracketed": expected, "source": "scan"},
              r.get_json())
    r = read("]d201095060001343531")
    check("refused: a wrong check digit, with the engine's reason", r.status_code == 422 and code(r) == "code.unreadable"
          and "check digit" in r.get_json()["params"]["detail"], r.get_json())
    r = read("garbage text")
    check("refused: text that is no code", r.status_code == 422 and code(r) == "code.unreadable")
else:
    r = read("]d2010950600013435210L1")
    check("without the engine: reading is unavailable", r.status_code == 422 and code(r) == "code.engineUnavailable")
    print("SKIP the engine's readings (set GS1_SYNTAX_ENGINE_DIR)")

for name, text, segment in (("an RFID reader's hexadecimal", "3074257BF7194E4000001A85", "eh3074257bf7194e4000001a85"),
                            ("eh… (a compressed GS1 Digital Link)", "eh3074257bf7194e4000001a85", "eh3074257bf7194e4000001a85"),
                            ("ex… (base 64)", "exMHQlexcZTkAAABqF", "exMHQlexcZTkAAABqF")):
    ASKED.clear()
    r = read(text)
    check(f"EPC read through the resolver: {name}", r.status_code == 200
          and r.get_json() == {"bracketed": "(01)09506000134352(21)1001", "source": "epc"}
          and ASKED == [(segment, "linkset", "application/linkset+json")], (r.get_json(), ASKED))
r = read("3000000000000000000000AA")
check("an EPC without a record: said so", r.status_code == 422 and code(r) == "code.epcNoRecord", code(r))
r = read("eh99aa00000000000000000000")
check("an EPC that does not decode: said so", r.status_code == 422 and code(r) == "code.epcInvalid", code(r))
os.environ["PORTAL_MONITOR_URL"] = "http://127.0.0.1:9/.well-known/gs1resolver"
r = read("3074257BF7194E4000001A85")
check("the resolver not answering: 502 code.epcUnavailable", r.status_code == 502 and code(r) == "code.epcUnavailable")
r = portal.app.test_client().post("/portal/api/code/read", json={"text": "0109506000134352"}, headers=ORIGIN)
check("signed in only", r.status_code == 401)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = {"code.unreadable", "code.engineUnavailable", "code.epcInvalid", "code.epcNoRecord", "code.epcUnavailable",
         "records.codeRead", "records.codeReadEpc", "records.codeReading"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check("the texts in both languages", not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
