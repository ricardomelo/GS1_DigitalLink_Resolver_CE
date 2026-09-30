"""
GS1 Digital Link data attributes (URI Syntax 1.7, section 4.10) in the portal: the syntax engine and
dictionary (portal/syntax.py), the API (GET /portal/api/config, POST /portal/api/digital-link,
GET /portal/api/qrcode with attr=AI:value) and the portal without the engine.

Needs the GS1 Barcode Syntax Engine built by the portal's own script:

  bash portal/tools/build-syntax-engine.sh /tmp/gs1se
  GS1_SYNTAX_ENGINE_DIR=/tmp/gs1se python dev-tests/portal/test_data_attributes.py
"""
import os
import sys
import tempfile
import threading

import cv2
import numpy as np
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3396
STEM = "https://id.example.org"
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_USERS_FILE=f"{CONFIG}/users.json", PORTAL_CONFIG_DIR=CONFIG,
                  PORTAL_ORIGIN="http://localhost", PORTAL_COOKIE_SECURE="false", RESOLVER_PUBLIC_URL=STEM)
sys.path[:0] = [HERE, PORTAL]

import mock_data_entry  # noqa: E402
import app as portal  # noqa: E402
import gs1  # noqa: E402
import syntax  # noqa: E402
import users  # noqa: E402
from gs1 import ValidationError  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def outcome(callable_):
    try:
        return callable_()
    except ValidationError as exc:
        return exc.code, exc.params


E = syntax.ENGINE
if not E.available:
    print(f"FAIL GS1 Barcode Syntax Engine not available in {syntax.ENGINE_DIR}: {E.reason}\n"
          "     build it with: bash portal/tools/build-syntax-engine.sh /tmp/gs1se, then set GS1_SYNTAX_ENGINE_DIR")
    sys.exit(1)

GTIN = "/01/09506000134352"
SSCC_BODY = "09506000134352000"
SSCC = "/00/" + SSCC_BODY + str(gs1.gtin_check_digit(SSCC_BODY))
GLN = "/414/9506000134376"

# ------------------------------------------------------------------ engine and dictionary
check("engine release pinned to 1.4.1", E.release == "1.4.1", E.release)
check("dictionary: several hundred data attribute AIs, ranges expanded",
      len(E.attributes) > 500 and all(f"310{n}" in E.attributes for n in range(6)), len(E.attributes))
check("dictionary: (8200), (03) and (8014) are not data attributes (URI Syntax 4.10)",
      not {"8200", "03", "8014"} & set(E.attributes))
check("dictionary: GS1 data titles", E.attributes["17"]["title"] == "USE BY or EXPIRY"
      and E.attributes["3103"]["title"] == "NET WEIGHT (kg)")
check("dictionary: components with length and linters", E.attributes["7003"]["components"] ==
      [{"type": "N", "min": 6, "max": 6, "optional": False, "linters": ["yymmdd"]},
       {"type": "N", "min": 4, "max": 4, "optional": False, "linters": ["hhmi"]}])
check("dictionary: qualifiers of each key (they go in the path)", E.path_ais["01"] == {"22", "10", "21", "235"}
      and {"254", "7040"} <= E.path_ais["414"] and not E.path_ais.get("00"), E.path_ais.get("01"))
attributes, path_ais = syntax.parse_dictionary(
    "# comment\n"
    "01  *?  N14,csum,gcppos2  ex=255 dlpkey=22,10,21|235  # GTIN\n"
    "422  ?  N3,iso3166  req=01,02  # ORIGIN\n"
    "7007 ?  N6,yymmdd [N6],yymmdd  req=01,02  # HARVEST DATE\n"
    "8200    X..70  req=01  # PRODUCT URL\n"
    "91-92  ?  X..90  # INTERNAL\n")
check("parser: flags, optional components, ranges, alternatives",
      set(attributes) == {"01", "422", "7007", "91", "92"}
      and attributes["7007"]["components"][1] == {"type": "N", "min": 6, "max": 6, "optional": True, "linters": ["yymmdd"]}
      and path_ais["01"] == {"22", "10", "21", "235"}, (attributes, path_ais))

# ------------------------------------------------------------------ building the GS1 Digital Link URI
check("no attributes: the record's own URI", E.digital_link(STEM, GTIN, [("10", "L1")], [])
      == (STEM + GTIN + "/10/L1", []))
check("attributes in the query string, HRI lines per attribute",
      E.digital_link(STEM, GTIN, [("10", "L1")], [("17", "261231"), ("3103", "000500")])
      == (STEM + GTIN + "/10/L1?17=261231&3103=000500", ["(17)261231", "(3103)000500"]))
check("SSCC with content, count and batch/lot as attributes (URI Syntax 5.9)",
      E.digital_link(STEM, SSCC, [], [("02", "09506000134352"), ("37", "12"), ("10", "L1")])[0]
      == STEM + SSCC + "?02=09506000134352&37=12&10=L1")
check("SSCC with a dangerous goods flag", E.digital_link(STEM, SSCC, [], [("4321", "1")])[0] == STEM + SSCC + "?4321=1")
check("reserved characters percent-encoded, brackets escaped for the engine",
      E.digital_link(STEM, GTIN, [], [("99", "A(B)/C&D")])[0] == STEM + GTIN + "?99=A%28B%29%2FC%26D")
cases = [
    ("unknown AI", GTIN, [("9999", "1")], ("attr.unknown", {"ai": "9999"})),
    ("AI not permitted as data attribute", GTIN, [("8200", "https://x")], ("attr.unknown", {"ai": "8200"})),
    ("batch/lot of a GTIN is a qualifier", GTIN, [("10", "L9")], ("attr.inPath", {"ai": "10"})),
    ("the key itself", GTIN, [("01", "09506000134352")], ("attr.inPath", {"ai": "01"})),
    ("GLN extension of a GLN is a qualifier", GLN, [("254", "1")], ("attr.inPath", {"ai": "254"})),
    ("serial of a GTIN is a qualifier, not an attribute", GTIN, [("21", "S1")], ("attr.inPath", {"ai": "21"})),
    ("repeated attribute", GTIN, [("17", "261231"), ("17", "261231")], ("attr.duplicate", {"ai": "17"})),
    ("empty value", GTIN, [("17", "")], ("attr.valueRequired", {"ai": "17"})),
    ("day 00 of a date (portal policy)", GTIN, [("17", "260200")], ("attr.dayZero", {"ai": "17", "first": "260201", "last": "260228"})),
    ("day 00 in a leap-year February", GTIN, [("15", "240200")], ("attr.dayZero", {"ai": "15", "first": "240201", "last": "240229"})),
    ("day 00 in a date and time (4324)", SSCC, [("4324", "2612002359")], ("attr.dayZero", {"ai": "4324", "first": "261201", "last": "261231"})),
    ("more than the maximum", GTIN, [(f"9{n}", "X") for n in range(1, 10)] + [("17", "261231"), ("3103", "000500")],
     ("attr.tooMany", {"max": syntax.MAX_ATTRIBUTES})),
]
for name, anchor, attrs, expected in cases:
    result = outcome(lambda: E.digital_link(STEM, anchor, [], attrs))
    check(f"refused: {name}", result == expected, result)
for name, anchor, attrs, text, markup in [
        ("illegal month", GTIN, [("17", "261399")], "illegal month", "(17)26|13|99"),
        ("date required association (17 with a GLN)", GLN, [("17", "261231")], "Required AIs for AI (17)", ""),
        ("invalid pair (3102 with 3103)", GTIN, [("3102", "001000"), ("3103", "000500")], "invalid to pair", ""),
        ("character outside CSET 82", GTIN, [("99", "A B")], "non-CSET 82", "(99)A| |B"),
        ("wrong length", GTIN, [("3103", "500")], "", "")]:
    result = outcome(lambda: E.digital_link(STEM, anchor, [], attrs))
    check(f"engine refuses: {name}", isinstance(result, tuple) and result[0] == "attr.invalid"
          and text in result[1]["detail"] and (not markup or result[1]["markup"] == markup), result)

results, errors = [], []


def hammer():
    try:
        for n in range(200):
            day = f"{n % 28 + 1:02d}"
            results.append(E.digital_link(STEM, GTIN, [], [("17", f"2612{day}")])[0].endswith(f"?17=2612{day}"))
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)


threads = [threading.Thread(target=hammer) for _ in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
check("one engine shared by the portal's threads", not errors and len(results) == 1600 and all(results), errors[:1])

# ------------------------------------------------------------------ through the portal's API
users.create("root", "root-password-long", "admin", must_change=False)
users.create("brand", "brand-password-long", "editor", prefixes=["9506000"], must_change=False)
users.create("other", "other-password-long", "editor", prefixes=["7891234"], must_change=False)


def client(name, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": name, "password": password})
    return c


root, other = client("root", "root-password-long"), client("other", "other-password-long")
config = root.get("/portal/api/config").get_json()["dataAttributes"]
check("config: data attributes offered with names, formats, limit and path AIs",
      config["available"] and config["release"] == "1.4.1" and config["max"] == syntax.MAX_ATTRIBUTES
      and {"ai": "17", "title": "USE BY or EXPIRY", "components": E.attributes["17"]["components"]} in config["ais"]
      and config["inPath"]["01"] == ["10", "21", "22", "235"], {k: v for k, v in config.items() if k != "ais"})

body = {"key": "01", "value": "09506000134352", "qualifiers": {"10": "L1"}}
r = root.post("/portal/api/digital-link", json=body)
check("digital-link without attributes", r.status_code == 200 and r.get_json() ==
      {"uri": STEM + GTIN + "/10/L1", "hri": ["(01)09506000134352", "(10)L1"]}, r.get_json())
r = root.post("/portal/api/digital-link", json={**body, "attributes": [{"ai": "(17)", "value": " 261231\u200b"},
                                                                       {"ai": "3103", "value": "000500"}]})
check("digital-link with attributes (brackets, spaces and invisible characters removed)",
      r.status_code == 200 and r.get_json() == {"uri": STEM + GTIN + "/10/L1?17=261231&3103=000500",
                                                 "hri": ["(01)09506000134352", "(10)L1", "(17)261231", "(3103)000500"]},
      r.get_json())
r = root.post("/portal/api/digital-link", json={**body, "attributes": [{"ai": "17", "value": "261399"}]})
check("digital-link: engine's refusal as 422 with its detail", r.status_code == 422 and r.get_json()["code"] == "attr.invalid"
      and "illegal month" in r.get_json()["params"]["detail"], r.get_json())
r = root.post("/portal/api/digital-link", json={**body, "attributes": [{"ai": "10", "value": "L2"}]})
check("digital-link: qualifier as attribute refused", r.status_code == 422 and r.get_json()["code"] == "attr.inPath")
r = other.post("/portal/api/digital-link", json={**body, "attributes": [{"ai": "17", "value": "261231"}]})
check("digital-link: GS1 Company Prefix of the user checked", r.status_code == 403, r.status_code)
check("digital-link: sign-in required", portal.app.test_client().post("/portal/api/digital-link", json=body).status_code == 401)

query = "key=01&value=09506000134352&qualifiers=/10/L1"
png = root.get(f"/portal/api/qrcode?{query}&attr=17:261231&attr=3103:000500&format=png")
decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(png.get_data(), np.uint8), 1))[0]
check("QR code (PNG) carries the attributes", png.status_code == 200 and decoded == STEM + GTIN + "/10/L1?17=261231&3103=000500",
      decoded)


def svg_height(response):
    import re  # noqa: PLC0415
    return float(re.search(rb'height="([\d.]+)mm"', response.get_data()).group(1))


plain, with_attrs = root.get(f"/portal/api/qrcode?{query}"), root.get(f"/portal/api/qrcode?{query}&attr=17:261231")
check("label grows by the attribute's HRI line", svg_height(with_attrs) > svg_height(plain), (svg_height(plain), svg_height(with_attrs)))
without_hri = root.get(f"/portal/api/qrcode?{query}&attr=17:261231&hri=0")
check("hri=0 still possible with attributes", without_hri.status_code == 200 and svg_height(without_hri) < svg_height(plain))
r = root.get(f"/portal/api/qrcode?{query}&attr=17:261399")
check("QR code refused for invalid attributes", r.status_code == 422 and r.get_json()["code"] == "attr.invalid")
r = root.get(f"/portal/api/qrcode?{query}&attr=17")
check("attr without a value", r.status_code == 422 and r.get_json() == {"code": "attr.valueRequired", "params": {"ai": "17"}},
      r.get_json())

# ------------------------------------------------------------------ label options: HRI, QR version, error correction
def headers(response):
    return response.headers.get("X-QR-Version"), response.headers.get("X-QR-Level"), response.headers.get("X-QR-Modules")


attr_query = f"{query}&attr=17:261231&attr=3103:000500"
full, key_only, none = (root.get(f"/portal/api/qrcode?{attr_query}&hri={mode}") for mode in ("full", "key", "none"))
check("HRI: full > key only > none", svg_height(full) > svg_height(key_only) > svg_height(none),
      [svg_height(r) for r in (full, key_only, none)])
check("HRI: 1 and 0 of earlier versions still mean full and none",
      svg_height(root.get(f"/portal/api/qrcode?{attr_query}&hri=1")) == svg_height(full)
      and svg_height(root.get(f"/portal/api/qrcode?{attr_query}&hri=0")) == svg_height(none))
r = root.get(f"/portal/api/qrcode?{attr_query}")
check("defaults: automatic version, level M exactly (not raised)", headers(r) == ("5", "M", "37"), headers(r))
r = root.get(f"/portal/api/qrcode?{attr_query}&ecl=h&version=auto")
check("level H: larger automatic version", r.headers.get("X-QR-Level") == "H" and int(r.headers.get("X-QR-Version")) > 5, headers(r))
r = root.get(f"/portal/api/qrcode?{attr_query}&version=10&ecl=l")
check("forced version and level used as chosen", headers(r) == ("10", "L", "57"), headers(r))
png = root.get(f"/portal/api/qrcode?{attr_query}&version=10&ecl=q&format=png")
decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(png.get_data(), np.uint8), 1))[0]
check("forced version still decodes", decoded.endswith("?17=261231&3103=000500") and png.headers.get("X-QR-Version") == "10", decoded)
r = root.get(f"/portal/api/qrcode?{attr_query}&version=2")
check("version too small: 422 with the version needed", r.status_code == 422 and r.get_json() ==
      {"code": "qr.tooSmall", "params": {"version": 2, "level": "M", "needed": 5, "fittingLevel": None}}, r.get_json())
r = root.get(f"/portal/api/qrcode?{attr_query}&version=5&ecl=h")
check("version too small at H but fits at a lower level: that level suggested", r.status_code == 422
      and r.get_json()["params"] == {"version": 5, "level": "H", "needed": 8, "fittingLevel": "M"}, r.get_json())
# "&" is percent-encoded in the URI (%26): nine values of 90 of them exceed version 40 at level H
long_attrs = "".join(f"&attr=9{n}:" + "%26" * 90 for n in range(1, 10))
r = root.get(f"/portal/api/qrcode?{query}{long_attrs}&ecl=h")
check("content too long even for version 40", r.status_code == 422 and r.get_json()["code"] == "qr.tooLong"
      and r.get_json()["params"]["level"] == "H", r.get_json())
for bad, code in [("version=0", "qr.version"), ("version=41", "qr.version"), ("version=x", "qr.version"),
                  ("ecl=z", "qr.level"), ("hri=some", "qr.hri")]:
    r = root.get(f"/portal/api/qrcode?{query}&{bad}")
    check(f"invalid option {bad} refused", r.status_code == 422 and r.get_json()["code"] == code, r.get_json())

# ------------------------------------------------------------------ without the engine
portal.syntax.ENGINE = syntax.Engine("/nonexistent")
check("without the engine: not offered", root.get("/portal/api/config").get_json()["dataAttributes"] == {"available": False})
r = root.post("/portal/api/digital-link", json={**body, "attributes": [{"ai": "17", "value": "261231"}]})
check("without the engine: attributes refused with their own message", r.status_code == 422
      and r.get_json()["code"] == "attr.unavailable", r.get_json())
check("without the engine: QR codes without attributes as before",
      root.get(f"/portal/api/qrcode?{query}").status_code == 200
      and root.post("/portal/api/digital-link", json=body).status_code == 200)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
