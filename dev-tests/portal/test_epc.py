"""
The EPC of a record for RFID and NFC tags (portal/epc.py; the backlog's EPC/NFC label option and item 9.10, ADR 0010
section 8): SGTIN-96 and SGTIN-198 encoded as the EPC Tag Data Standard says — its own example, every partition, the
limits of SGTIN-96 —, and every other key the standard encodes (SSCC, SGLN, GRAI, GIAI, GSRN, GSRNP, GDTI, SGCN, CPI,
ITIP) for every partition, numeric and alphanumeric, each decoded back by the resolver's own decoder
(web_server/src/epc_binary.py) from eh… and ex…, and compared with an independent library (epc-tds, when EPC_TDS is set);
the definitions file against the TDT artefacts; what a record needs first; and GET /portal/api/epc: the company prefix's
length from the organisation's prefixes or chosen, the filter (1 for trade items, 0 otherwise), the label's domain,
refusals, access, a search of the record list by each new EPC read through a resolver, both languages.

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

# ================================================================== every key with an EPC (item 9.10)
from urllib.parse import quote  # noqa: E402
run = subprocess.run([sys.executable, os.path.join(PORTAL, "tools", "gen_epc_schemes.py"), "--check"],
                     capture_output=True, text=True)
check("the definitions file is what the resolver's TDT artefacts give (gen_epc_schemes.py --check)",
      run.returncode == 0, run.stderr[-300:])
check("…every scheme the encoder tries is in it", all(name in epc.schemes() for names in epc.KEY_SCHEMES.values()
                                                       for name in names))


gsrn = gtin                                       # 17 digits and the check digit, as for a GTIN


# (key, value as typed after the company prefix's place, the record's EPC qualifiers, the scheme expected)
PREFIX12 = "950600013435"                         # a 12-digit run: the first L digits are the company prefix
KEYS = [
    ("00", lambda: gtin("3" + PREFIX12 + "0001"), {}, "sscc-96"),
    ("414", lambda: gtin(PREFIX12), {}, "sgln-96"),
    ("414", lambda: gtin(PREFIX12), {"254": "1234"}, "sgln-96"),
    ("414", lambda: gtin(PREFIX12), {"254": "DOCK-3/B"}, "sgln-195"),
    ("8003", lambda: "0" + gtin(PREFIX12) + "1234", {}, "grai-96"),
    ("8003", lambda: "0" + gtin(PREFIX12) + "A-1", {}, "grai-170"),
    ("8004", lambda: PREFIX12 + "99", {}, "giai-96"),
    ("8004", lambda: PREFIX12 + "ASSET-9", {}, "giai-202"),
    ("8018", lambda: gsrn(PREFIX12 + "00007"), {}, "gsrn-96"),
    ("8017", lambda: gsrn(PREFIX12 + "00007"), {}, "gsrnp-96"),
    ("253", lambda: gtin(PREFIX12) + "77", {}, "gdti-96"),
    ("253", lambda: gtin(PREFIX12) + "X-7", {}, "gdti-174"),
    ("255", lambda: gtin(PREFIX12) + "0042", {}, "sgcn-96"),
    ("8010", lambda: PREFIX12 + "123", {"8011": "5"}, "cpi-96"),
    ("8010", lambda: PREFIX12 + "AB-1/2#", {"8011": "5"}, "cpi-var"),
    ("8006", lambda: gtin("1" + PREFIX12) + "0102", {"21": "77"}, "itip-110"),
    ("8006", lambda: gtin("1" + PREFIX12) + "0102", {"21": "x/7"}, "itip-212"),
]
wrong, seen = [], set()
for ai, make, qualifiers, scheme in KEYS:
    value = make()
    expected = epc.path_of(ai, value, qualifiers)
    for length in range(6, 13):
        try:
            e = epc.encode(ai, value, qualifiers, length, 1)
        except epc.EpcError as exc:
            wrong.append((ai, value, length, exc.code))
            continue
        seen.add(e.scheme)
        for segment in ("eh" + e.hex, "ex" + e.base64):
            decoded = epc_binary.decompress(segment)
            # a numeric reference that starts with 0 at this partition goes to the longer scheme (TDS 14.3.2)
            family = [n.lower() for n in epc.KEY_SCHEMES[ai]]
            if decoded.scheme.lower() != e.scheme or e.scheme not in family or decoded.path() != expected \
                    or family.index(e.scheme) < family.index(scheme):
                wrong.append((ai, value, length, segment[:2], e.scheme, decoded.scheme, decoded.path(), expected))
check(f"every key with an EPC, every partition, numeric and alphanumeric: decoded back by the resolver "
      f"({len(seen)} schemes besides the SGTIN's)", not wrong and len(seen) == 16, (wrong[:3], sorted(seen)))
check("…the 96-bit scheme for numeric values without leading zeros, the longer one otherwise",
      [epc.encode("8004", v, {}, 7).scheme for v in ("950600099", "9506000099", "9506000A9")]
      == ["giai-96", "giai-202", "giai-202"]
      and [epc.encode("414", gtin(PREFIX12), {"254": v}, 7).scheme for v in ("7", "07", "A")]
      == ["sgln-96", "sgln-195", "sgln-195"])
e = epc.encode("414", gtin(PREFIX12), {}, 7, 0)
check("a GLN without extension: SGLN with the extension 0 (TDS 6.3.3)", e.tag_uri == "urn:epc:tag:sgln-96:0.9506000.13435.0"
      and epc_binary.decompress("eh" + e.hex).path() == f"/414/{gtin(PREFIX12)}/254/0", e.tag_uri)
e = epc.encode("8010", PREFIX12 + "AB-1/2#", {"8011": "5"}, 7, 0)
check("a CPI's '/' and '#' escaped in its URIs (%2F, %23)", e.tag_uri == "urn:epc:tag:cpi-var:0.9506000.13435AB-1%2F2%23.5"
      and e.pure_identity == "urn:epc:id:cpi:9506000.13435AB-1%2F2%23.5", (e.tag_uri, e.pure_identity))
e = epc.encode("255", gtin(PREFIX12) + "0042", {}, 7, 0)
check("an SGCN's serial keeps its leading zeros (TDT: '1' prepended)", e.tag_uri.endswith(".0042")
      and epc_binary.decompress("eh" + e.hex).path().endswith("0042"), e.tag_uri)
REFUSED = [(("8004", "9506000ASSET-9" + "X" * 20, {}, 7), "epc.notEncodable"),
           (("414", gtin(PREFIX12), {"254": "é"}, 7), "epc.notEncodable"),
           (("8003", "0" + gtin(PREFIX12), {}, 7), "epc.needsSerial"),
           (("8006", gtin("1" + PREFIX12) + "0102", {}, 7), "epc.needsQualifier"),
           (("401", "950600012345", {}, 7), "epc.unsupported"),
           (("00", gtin("3" + PREFIX12 + "0001"), {}, 13), "epc.prefixLength"),
           (("00", gtin("3" + PREFIX12 + "0001"), {}, 7, 8), "epc.filterInvalid")]
for args, expected in REFUSED:
    try:
        epc.encode(*args)
        got = None
    except epc.EpcError as exc:
        got = exc.code
    check(f"refused: {args[0]} {args[1][:20]} {args[2]} → {expected}", got == expected, got)
check("what a record needs first", epc.missing("01", "x", {}) == {"qualifier": "21"}
      and epc.missing("8003", "0" + gtin(PREFIX12), {}) == {"serialAfter": 14}
      and epc.missing("8003", "0" + gtin(PREFIX12) + "1", {}) is None and epc.missing("00", "x", {}) is None)

# Compared with epc-tds: the hexadecimal it writes for each tag URI of ours (it has no GSRNP, CPI-var or ITIP; and it
# drops an SGCN serial's leading zeros, which the TDT artefact keeps, so those are left out of the comparison)
TAG_ORACLE = r"""
const tds = require("epc-tds");
const rows = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(rows.map(u => { try { return tds.fromTagURI(u).toHexString(); } catch (e) { return "ERR " + e; } })));
"""
if EPC_TDS:
    import random
    rnd = random.Random(20261017)
    # epc-tds reads a URI's fields up to the next '.' or ':', so a serial with either is cut there; it does not undo a
    # URI's escapes; and it does not read the empty field of a 12-digit company prefix ("…885..serial"): none of these
    # is left to it (the resolver's decoder checks them all above)
    SET82 = "!'()*+,-0123456789;=ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
    cases = []
    for _ in range(40):
        digits = "".join(rnd.choice("0123456789") for _ in range(12))
        number = str(rnd.randint(1, 2 ** 30))
        text = rnd.choice("ABC") + "".join(rnd.choice(SET82) for _ in range(rnd.randint(0, 10)))
        cases += [("00", gtin("3" + digits + "0001"), {}), ("414", gtin(digits), {"254": number}),
                  ("414", gtin(digits), {"254": text}), ("8003", "0" + gtin(digits) + number, {}),
                  ("8003", "0" + gtin(digits) + text[:16], {}), ("8004", digits + number, {}),
                  ("8004", digits + text, {}), ("8018", gtin(digits + "00007"), {}), ("253", gtin(digits) + number, {}),
                  ("253", gtin(digits) + text[:17], {}), ("255", gtin(digits) + number[:12], {}),
                  ("8010", digits + str(rnd.randint(1, 999)), {"8011": number})]
    mine = []
    for ai, value, qualifiers in cases:
        length = rnd.randint(6, 11)
        try:
            e = epc.encode(ai, value, qualifiers, length, rnd.randint(0, 7))
        except epc.EpcError:
            continue
        if e.scheme not in ("cpi-var", "gsrnp-96"):
            mine.append(e)
    theirs = json.loads(subprocess.run(["node", "-e", TAG_ORACLE], cwd=EPC_TDS, input=json.dumps([e.tag_uri for e in mine]),
                                       capture_output=True, text=True, check=True).stdout)
    differ = [(e.tag_uri, e.hex, t) for e, t in zip(mine, theirs)
              if e.hex.rstrip("0") != str(t).lower().rstrip("0")]
    check(f"{len(mine)} random EPCs of SSCC, SGLN, GRAI, GIAI, GSRN, GDTI, SGCN and CPI the same as epc-tds writes "
          f"from their tag URIs ({len({e.scheme for e in mine})} schemes)", len(mine) > 400 and not differ, differ[:2])
else:
    print("SKIP comparison of the other schemes with epc-tds (set EPC_TDS)")

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
for query, expected in ((f"key=01&value={G}", "epc.needsQualifier"), (f"key=01&value={G}&qualifiers=/10/L1", "epc.needsQualifier"),
                        (f"key=01&value={G}&qualifiers=/21/1&filter=x", "epc.filterInvalid"),
                        (f"key=8003&value=0{gtin('789123400000')}", "epc.needsSerial"),
                        (f"key=8010&value=7891234AB", "epc.needsQualifier"),
                        (f"key=417&value={gtin('789123400000')}", "epc.unsupported")):
    r = ana.get("/portal/api/epc?" + query)
    check(f"refused: {query} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
r = bia.get(f"/portal/api/epc?key=01&value={G}&qualifiers=/21/1")
check("another organisation's code: refused", r.status_code == 403, r.status_code)

# Every key with an EPC through the API, and the record list's search by that EPC: read through a resolver (here a
# stand-in that decodes with the resolver's own decoder, as the real one does) back to the record's element string
from flask import Flask, jsonify  # noqa: E402
from werkzeug.serving import make_server as _make_server  # noqa: E402
stand_in = Flask("stand-in-resolver")


@stand_in.get("/<path:segment>")
def _decode(segment):
    try:
        found = epc_binary.decompress(segment)
    except epc_binary.EpcDecodeError:
        return jsonify(error="Not a decodable EPC binary string"), 400
    return jsonify(linkset=[{"anchor": "https://id.example.org" + found.path()}])


threading.Thread(target=_make_server("127.0.0.1", 3403, stand_in, threaded=True).serve_forever, daemon=True).start()
os.environ["PORTAL_MONITOR_URL"] = "http://127.0.0.1:3403/.well-known/gs1resolver"
API_KEYS = [("414", gtin("789123400001"), "", "sgln-96", "(414){v}(254)0"),
            ("414", gtin("789123400001"), "/254/DOCK-3", "sgln-195", "(414){v}(254)DOCK-3"),
            ("00", gtin("37891234000000001"), "", "sscc-96", "(00){v}"),
            ("8003", "0" + gtin("789123400001") + "55", "", "grai-96", "(8003){v}"),
            ("8004", "7891234ASSET1", "", "giai-202", "(8004){v}"),
            ("8018", gtin("78912340000000007"), "", "gsrn-96", "(8018){v}"),
            ("8017", gtin("78912340000000007"), "", "gsrnp-96", "(8017){v}"),
            ("253", gtin("789123400001") + "9", "", "gdti-96", "(253){v}"),
            ("255", gtin("789123400001") + "12", "", "sgcn-96", "(255){v}"),
            ("8010", "7891234PART-1", "/8011/9", "cpi-var", "(8010){v}(8011)9"),
            ("8006", gtin("1789123400001") + "0102", "/21/7", "itip-110", "(8006){v}(21)7")]
for ai, value, qualifiers, scheme, bracketed in API_KEYS:
    r = ana.get("/portal/api/epc", query_string={"key": ai, "value": value, "qualifiers": qualifiers})
    data = r.get_json() or {}
    filter_expected = 1 if ai in ("01", "8006") else 0
    check(f"API: {scheme} of a {ai} with the organisation's prefix (filter {filter_expected} by default)",
          r.status_code == 200 and data.get("scheme") == scheme and data.get("prefixLength") == 7
          and data.get("tagUri", "").startswith(f"urn:epc:tag:{scheme}:{filter_expected}.7891234")
          and data.get("compressedHex") == f"https://id.example.org/eh{data.get('hex')}", data)
    found = ana.post("/portal/api/code/read", json={"text": data.get("hex", "").upper()}, headers=ORIGIN).get_json() or {}
    check(f"…the record list's search by that EPC finds the {ai}", found.get("bracketed") == bracketed.format(v=value)
          and found.get("source") == "epc", found)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(epc\.[A-Za-z.0-9]+)"', open(os.path.join(PORTAL, "epc.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read() + open(os.path.join(PORTAL, "static", "app.js")).read()))
codes = {c for c in codes if not c.endswith(".")} | {f"epc.filter.{n}" for n in range(8)} | {"epc.title", "epc.intro"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"the texts in both languages ({len(codes)})", len(codes) > 20 and not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
