"""
The EPC of a serialised GTIN for RFID and NFC tags (portal/epc.py; the backlog's EPC/NFC label option): SGTIN-96 and
SGTIN-198 encoded as the EPC Tag Data Standard says — its own example, every partition, the limits of SGTIN-96 —,
decoded back by the resolver's own decoder (web_server/src/epc_binary.py) from eh… and ex…, and compared with an
independent library (epc-tds, when EPC_TDS is set); and GET /portal/api/epc: the company prefix's length from the
organisation's prefixes or chosen, the filter, the label's domain, refusals, access, both languages.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_epc.py          # EPC_TDS=<folder of 'npm install epc-tds'> for the comparison
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
DATA_ENTRY_PORT = 3402
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_epc_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import epc  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
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



spec = importlib.util.spec_from_file_location("epc_binary", os.path.join(HERE, "..", "..", "web_server", "src", "epc_binary.py"))
epc_binary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(epc_binary)

# ================================================================== the encoder
e = epc.sgtin("80614141123458", "6789", 7, 3)
check("the Tag Data Standard's example: SGTIN-96 3074257BF7194E4000001A85", e.hex == "3074257bf7194e4000001a85"
      and e.tag_uri == "urn:epc:tag:sgtin-96:3.0614141.812345.6789"
      and e.pure_identity == "urn:epc:id:sgtin:0614141.812345.6789", (e.hex, e.tag_uri))
wrong = []
for length in range(6, 13):
    for serial in ("1001", "274877906943", "274877906944", "0", "012", "ABC-12/x?", "x" * 20):
        e = epc.sgtin("09506000134352", serial, length, 1)
        for segment in ("eh" + e.hex, "ex" + e.base64):
            decoded = epc_binary.decompress(segment)
            from urllib.parse import quote
            if decoded.path() != "/01/09506000134352/21/" + quote(serial, safe="") or decoded.scheme.lower() != e.scheme:
                wrong.append((length, serial, segment, decoded.scheme, decoded.path()))
check("every partition and kind of serial number decoded back by the resolver (eh… and ex…)", not wrong, wrong[:3])
check("SGTIN-96 for a numeric serial below 2^38 without leading zeros, SGTIN-198 otherwise",
      [epc.sgtin("09506000134352", s, 7).scheme for s in ("1001", "0", "274877906943", "274877906944", "012", "A1")]
      == ["sgtin-96", "sgtin-96", "sgtin-96", "sgtin-198", "sgtin-198", "sgtin-198"])
check("the URIs escape the serial number's reserved characters", epc.sgtin("09506000134352", "a/b?c%", 7).tag_uri
      .endswith(".a%2Fb%3Fc%25"))
for args, code_expected in ((("0950600013435", "1", 7), "epc.gtin"), (("09506000134352", "1", 5), "epc.prefixLength"),
                            (("09506000134352", "é", 7), "epc.serial"), (("09506000134352", "x" * 21, 7), "epc.serial"),
                            (("09506000134352", "1", 7, 8), "epc.filterInvalid")):
    try:
        epc.sgtin(*args)
        refused = None
    except epc.EpcError as exc:
        refused = exc.code
    check(f"refused: {args} → {code_expected}", refused == code_expected, refused)
check("the company prefix's length from prefixes: the longest the GTIN starts with",
      epc.prefix_length_for("07891234500014", ["789", "7891234", "78912345", "7895"]) == 8
      and epc.prefix_length_for("07891234500014", ["7895555"]) is None)

ORACLE = r"""
const tds = require("epc-tds");
let seed = 20261015;
const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return Math.floor(seed / 65536) % k; };
const digits = (k) => Array.from({length: k}, () => rnd(10)).join("");
const SET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz";
const text = (k) => Array.from({length: k}, () => SET82[rnd(SET82.length)]).join("");
const out = [];
for (let i = 0; i < 100; i++) {
  const p = rnd(7), f = rnd(8), gtin = digits(13) + "0";
  let e = new tds.Sgtin96().setFilter(f).setPartition(p).setGtin(gtin).setSerial(1 + rnd(2 ** 30));
  out.push([e.getGtin(), String(e.getSerial()), 12 - p, f, e.toHexString()]);
  e = new tds.Sgtin198().setFilter(f).setPartition(p).setGtin(gtin).setSerial("A" + text(rnd(20)));
  out.push([e.getGtin(), e.getSerial(), 12 - p, f, e.toHexString()]);
}
console.log(JSON.stringify(out));
"""
EPC_TDS = os.environ.get("EPC_TDS")
if EPC_TDS:
    rows = json.loads(subprocess.run(["node", "-e", ORACLE], cwd=EPC_TDS, capture_output=True, text=True, check=True).stdout)
    differ = []
    for gtin14, serial, length, filter_value, theirs in rows:
        mine = epc.sgtin(gtin14, serial, length, filter_value).hex
        width = max(len(mine), len(theirs))
        if mine.ljust(width, "0") != theirs.lower().ljust(width, "0"):
            differ.append((gtin14, serial, length, mine, theirs))
    check(f"{len(rows)} random SGTIN-96 and SGTIN-198 the same as epc-tds encodes them", not differ, differ[:2])
else:
    print("SKIP comparison with epc-tds (set EPC_TDS)")

# ================================================================== GET /portal/api/epc
G = gtin("0789123450007")
r = ana.get(f"/portal/api/epc?key=01&value={G}&qualifiers=/21/1001")
data = r.get_json() or {}
check("the organisation's code: its prefix's length, filter 1, the EPC and the URIs", r.status_code == 200
      and data["prefixLength"] == 7 and data["prefixFrom"] == "prefixes" and data["scheme"] == "sgtin-96"
      and data["tagUri"] == f"urn:epc:tag:sgtin-96:1.7891234.{G[0]}{G[8:13]}.1001", data)
check("…the compressed links on the installation's address, decoded back to the record",
      data["compressedHex"] == f"https://id.example.org/eh{data['hex']}"
      and epc_binary.decompress(data["compressedBase64"].rsplit("/", 1)[1]).path() == f"/01/{G}/21/1001", data)
r = ana.get(f"/portal/api/epc?key=01&value={G}&qualifiers=/10/L1/21/S1&prefixLength=8&filter=0")
data = r.get_json() or {}
check("a chosen length and filter; a batch with the serial (informative) does not change the EPC",
      data.get("prefixLength") == 8 and data.get("prefixFrom") == "chosen" and data.get("scheme") == "sgtin-198"
      and data["tagUri"].startswith("urn:epc:tag:sgtin-198:0.78912345."), data)
OPER = gtin("0950600013436")
r = root.get(f"/portal/api/epc?key=01&value={OPER}&qualifiers=/21/7")
check("a code of no organisation: the length must be chosen", r.status_code == 422 and code(r) == "epc.prefixLength")
check("…and then it is", root.get(f"/portal/api/epc?key=01&value={OPER}&qualifiers=/21/7&prefixLength=7").status_code == 200)
for query, expected in ((f"key=01&value={G}", "epc.notSerialised"), (f"key=01&value={G}&qualifiers=/10/L1", "epc.notSerialised"),
                        (f"key=01&value={G}&qualifiers=/21/1&filter=x", "epc.filterInvalid"),
                        (f"key=414&value={gtin('789123400000')}", "epc.notSerialised")):
    r = ana.get("/portal/api/epc?" + query)
    check(f"refused: {query} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
r = bia.get(f"/portal/api/epc?key=01&value={G}&qualifiers=/21/1")
check("another organisation's code: refused", r.status_code == 403, r.status_code)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(epc\.[A-Za-z.0-9]+)"', open(os.path.join(PORTAL, "epc.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read() + open(os.path.join(PORTAL, "static", "app.js")).read()))
codes = {c for c in codes if not c.endswith(".")} | {f"epc.filter.{n}" for n in range(8)} | {"epc.title", "epc.intro"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"the texts in both languages ({len(codes)})", len(codes) > 20 and not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
