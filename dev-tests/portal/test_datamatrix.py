"""
Data Matrix on labels and the scanning environments (Documentation/adr/0010-label-studio.md, section 7; backlog item
9.3): a GS1 DataMatrix (the element string, FNC1 first and after a variable-length field: read back by an independent
decoder, zxing-cpp, as symbology ]d2 with the same element string) and a Data Matrix carrying the GS1 Digital Link URI
(]d1, the URI), square, in PNG, SVG, PDF and the zip; the element string holding the record's qualifiers and its data
attributes whatever the human readable text; the scanning environments (their X-dimensions, their symbols, the sizes
that stay within their ranges, with an EAN/UPC beside too, a linear symbol refused where none is used); the HRI as text
in the SVG (OCR-B for EAN/UPC digits) or as outlines (the default); the headers, the file names, refusals, the tenant API,
the configuration the page reads, and the texts in both languages.

  pip install -r portal/requirements.txt mongomock zxing-cpp
  python dev-tests/portal/test_datamatrix.py
"""
import io
import os
import re
import sys
import tempfile
import threading
import zipfile
import zlib

import zxingcpp
from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3403
sys.path[:0] = [HERE, PORTAL]
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_datamatrix_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import apikeys  # noqa: E402
import app as portal  # noqa: E402
import label  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}
GTIN = "09506000134352"


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def read(png: bytes) -> list:
    """Every symbol zxing-cpp finds in a PNG: (format, symbology identifier, text)."""
    image = Image.open(io.BytesIO(png)).convert("L")
    return [(str(r.format), r.symbology_identifier, r.text) for r in zxingcpp.read_barcodes(image)]


def options(**extra):
    base = dict(uri=f"https://id.example.org/01/{GTIN}/10/ABC123/21/XYZ", hri_lines=(f"(01){GTIN}", "(10)ABC123", "(21)XYZ"),
                show_hri=True, element_string=f"(01){GTIN}(10)ABC123(21)XYZ")
    base.update(extra)
    return label.LabelOptions(**base)


# ================================================================== the symbols
found = read(label.render_png(options(symbol="gs1dm")))
check("GS1 DataMatrix: read back as ]d2 with the element string (FNC1 first, a separator after the batch)",
      ("Data Matrix", "]d2", f"(01){GTIN}(10)ABC123(21)XYZ") in found, found)
code = label.symbol(options(symbol="gs1dm"))
check("…square ECC 200", code.rows == code.columns and code.gs1, (code.rows, code.columns))
short = label.symbol(options(symbol="gs1dm", element_string=f"(01){GTIN}(10)ABC123"))
check("…square even where a rectangle would be smaller (12 x 26)", short.rows == short.columns == 18, (short.rows, short.columns))
found = read(label.render_png(options(symbol="dm")))
check("Data Matrix with the GS1 Digital Link URI: ]d1 and the URI, no FNC1",
      ("Data Matrix", "]d1", f"https://id.example.org/01/{GTIN}/10/ABC123/21/XYZ") in found, found)
found = read(label.render_png(options()))
check("the QR code is unchanged by default", any(f[0] == "QR Code" and f[1] == "]Q1" for f in found), found)
try:
    label.data_matrix("A" * 3200, False)
    refused = False
except label.DataMatrixError:
    refused = True
check("data too long for the largest Data Matrix: refused", refused)

svg = label.render_svg(options(symbol="gs1dm")).decode()
check("SVG: titled with the element string, the symbol named, the X-dimension given",
      f"<title>(01){GTIN}(10)ABC123(21)XYZ</title>" in svg and "GS1 DataMatrix at 100 %" in svg
      and "X = 0.495 mm" in svg, svg[:500])
width_mm = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
check("…the label at least as wide as the symbol and its quiet zones at 0.495 mm",
      width_mm >= (code.columns + 2 * label.QUIET_ZONE) * 0.495 - 0.01, width_mm)
pdf = label.render_pdf(options(symbol="gs1dm"))
check("PDF: titled with the element string", f"/Title (\\(01\\){GTIN}\\(10\\)ABC123\\(21\\)XYZ)".encode() in pdf, pdf[-300:])
archive = zipfile.ZipFile(io.BytesIO(label.render_zip(options(symbol="gs1dm"), "x")))
readme = archive.read("README.txt").decode()
check("zip: every format, the README naming the symbol, its modules and the element string",
      sorted(archive.namelist()) == ["README.txt", "x.pdf", "x.png", "x.svg"] and "GS1 DataMatrix: ECC 200" in readme
      and f"GS1 element string: (01){GTIN}(10)ABC123(21)XYZ" in readme
      and f"{code.rows} x {code.columns} modules" in readme, readme)

# ================================================================== scanning environments
check("retail: every size, the 2D X 0.396–0.990 mm, EAN/UPC 0.264–0.660 mm",
      label.sizes_for("retail") == list(label.SIZES) and label.sizes_for("retail", True) == list(label.SIZES)
      and label.ENVIRONMENTS["retail"]["2d"] == (0.396, 0.495, 0.990))
check("healthcare, non-retail (table 6): Data Matrix at 0.254–0.990 mm (target 0.380), EAN/UPC from 0.170 mm: every size",
      label.sizes_for("healthcare") == list(label.SIZES) and label.sizes_for("healthcare", True) == list(label.SIZES)
      and label.ENVIRONMENTS["healthcare"]["2d"] == (0.254, 0.380, 0.990)
      and label.ENVIRONMENTS["healthcare"]["linear"] == (0.170, 0.330, 0.660)
      and label.ENVIRONMENTS["healthcare"]["symbols"] == ("gs1dm", "dm"))
check("direct part marking (table 7): 0.254–0.615 mm (target 0.300), from 90 %, no linear symbol, the QR code too",
      label.sizes_for("dpm") == [90, 100, 120, 150, 200] and label.ENVIRONMENTS["dpm"]["linear"] is None
      and "qr" in label.ENVIRONMENTS["dpm"]["symbols"])
# The tables of the GS1 General Specifications, release 26.0, section 5.12.3: the sizes each range allows
for name, table, x, linear_x, sizes, with_linear in (
        ("retail-gd", 3, (0.743, 0.990, 0.990), (0.495, 0.660, 0.660), [80, 90, 100], [80, 90, 100]),
        ("distribution", 2, (0.743, 0.743, 1.50), (0.495, 0.660, 0.660), [100, 120, 150, 200], [100]),
        ("pharmacy", 10, (0.396, 0.495, 0.990), (0.264, 0.330, 0.660), list(label.SIZES), list(label.SIZES)),
        ("pharmacy-gd", 8, (0.750, 0.750, 1.520), (0.495, 0.660, 0.660), [100, 120, 150, 200], [100]),
        ("other", 4, (0.375, 0.495, 0.990), (0.264, 0.330, 0.660), list(label.SIZES), list(label.SIZES)),
        ("logistics", 5, (0.743, 0.743, 1.50), None, [100, 120, 150, 200], []),
        ("assets", 9, (0.375, 0.375, 0.743), None, [100, 120, 150], []),
        ("gsrn", 11, (0.254, 0.380, 0.495), None, [80, 90, 100, 120], [])):
    env = label.ENVIRONMENTS[name]
    check(f"{name} (table {table}): 2D {x[0]}–{x[2]} mm (target {x[1]}), sizes {sizes}, with an EAN/UPC {with_linear or 'none'}",
          env["table"] == table and env["2d"] == x and env["linear"] == linear_x and label.sizes_for(name) == sizes
          and (label.sizes_for(name, True) if env["linear"] else []) == with_linear,
          (env, label.sizes_for(name), label.sizes_for(name, True)))
check("a QR code only where the tables name one: not in the healthcare tables (6, 8, 10)",
      [n for n, e in label.ENVIRONMENTS.items() if "qr" not in e["symbols"]] == ["pharmacy", "pharmacy-gd", "healthcare"])
check("the environments of a key, its default first (figure 5-68): a GTIN the trade items' tables and DPM",
      label.environments_for("01") == ["retail", "retail-gd", "distribution", "pharmacy", "pharmacy-gd", "healthcare",
                                       "other", "dpm"] and label.environments_for("8006") == label.environments_for("01"))
check("…an SSCC table 5, GDTI, GRAI, GIAI and GLN table 9, a GSRN table 11, each with DPM",
      label.environments_for("00") == ["logistics", "dpm"] and label.environments_for("8004") == ["assets", "dpm"]
      and label.environments_for("414") == ["assets", "dpm"] and label.environments_for("8018") == ["gsrn", "dpm"])
svg = label.render_svg(options(symbol="gs1dm", environment="healthcare", size=120,
                               linear=("ean13", "9506000134352"))).decode()
check("healthcare at 120 %: X 0.456 mm, the EAN-13 at 0.396 mm", "X = 0.456 mm" in svg
      and "EAN-13 9506000134352 at X = 0.396 mm" in svg, re.search(r"<desc>.*</desc>", svg).group(0))
# An environment whose EAN/UPC range is narrower than its 2D range: the linear symbol limits the sizes too
label.ENVIRONMENTS["narrow"] = {"2d": (0.3, 0.5, 1.0), "linear": (0.5, 0.5, 0.66), "symbols": label.SYMBOLS}
check("the sizes with an EAN/UPC beside keep both within their ranges", label.sizes_for("narrow") == [80, 90, 100, 120, 150, 200]
      and label.sizes_for("narrow", True) == [100, 120], label.sizes_for("narrow", True))
svg = label.render_svg(options(environment="narrow", linear=("ean13", "9506000134352"))).decode()
check("…the EAN/UPC drawn at the environment's own target (0.500 mm)", "EAN-13 9506000134352 at X = 0.500 mm" in svg
      and "(X = 0.500 mm)" in svg, re.search(r"<desc>.*</desc>", svg).group(0))
del label.ENVIRONMENTS["narrow"]
for name, extra, code_expected in (
        ("a QR code in healthcare", dict(environment="healthcare"), "label.symbolNotForEnvironment"),
        ("120 % in retail and general distribution (1.188 mm)", dict(symbol="gs1dm", environment="retail-gd", size=120),
         "label.sizeOutOfRange"),
        ("80 % in direct part marking (0.240 mm)", dict(symbol="dm", environment="dpm", size=80), "label.sizeOutOfRange"),
        ("an EAN-13 in direct part marking", dict(symbol="dm", environment="dpm", linear=("ean13", "9506000134352")),
         "label.linearNotForEnvironment")):
    try:
        label.render_svg(options(**extra))
        got = None
    except label.OutOfRange as exc:
        got = exc.code
    check(f"refused: {name} → {code_expected}", got == code_expected, got)

# ================================================================== HRI as text in the SVG
text_svg = label.render_svg(options(linear=("ean13", "9506000134352"), hri_text=True)).decode()
outline_svg = label.render_svg(options(linear=("ean13", "9506000134352"))).decode()
check("HRI as text: <text> elements, the element strings in Liberation Sans, the EAN/UPC digits in OCR-B",
      f">(01){GTIN}</text>" in text_svg and "font-family=\"'Liberation Sans'" in text_svg
      and text_svg.count("font-family=\"OCR-B") == 13, text_svg[-800:])
check("…outlines by default (no <text>, no font needed)", "<text" not in outline_svg
      and f'aria-label="(01){GTIN}"' in outline_svg)
check("…the symbol's modules the same either way", re.search(r'shape-rendering="crispEdges" d="([^"]+)"', text_svg).group(1)
      == re.search(r'shape-rendering="crispEdges" d="([^"]+)"', outline_svg).group(1))

# ================================================================== through the portal and the tenant API
root = portal.app.test_client()
root.post("/portal/api/login", json={"username": "root", "password": "root-password-long"}, headers=ORIGIN)


def get(query, client=root, headers=None):
    return client.get("/portal/api/qrcode?" + query, headers=headers or {})


r = get(f"key=01&value={GTIN}&qualifiers=/10/L1&attr=17:261231&symbol=gs1dm&hri=key&format=png")
found = read(r.data)
check("portal: a GS1 DataMatrix of the record with its batch and a data attribute, whatever the HRI",
      r.status_code == 200 and ("Data Matrix", "]d2", f"(01){GTIN}(17)261231(10)L1") in found
      or ("Data Matrix", "]d2", f"(01){GTIN}(10)L1(17)261231") in found, (r.status_code, found))
check("…its headers: the symbol, its modules, the X-dimension", r.headers.get("X-Symbol") == "gs1dm"
      and re.fullmatch(r"\d+x\d+", r.headers.get("X-DM-Modules", "")) and r.headers.get("X-Dimension") == "0.495"
      and "X-QR-Version" not in r.headers, dict(r.headers))
check("…a file name saying what it is", 'filename="gs1datamatrix_01_' in r.headers.get("Content-Disposition", ""))
r = get(f"key=01&value={GTIN}&symbol=dm&env=healthcare&size=120&format=png")
found = read(r.data)
check("…a Data Matrix with the URI in healthcare at 120 %", r.status_code == 200
      and ("Data Matrix", "]d1", f"https://id.example.org/01/{GTIN}") in found
      and r.headers.get("X-Dimension") == "0.456", (found, dict(r.headers)))
r = get(f"key=01&value={GTIN}&hritext=text")
check("…HRI as text in the SVG", r.status_code == 200 and b"<text " in r.data)
for query, expected in (("symbol=pdf417", "label.symbolInvalid"), ("env=moon", "label.environmentInvalid"),
                        ("hritext=bold", "label.hriTextInvalid"), ("env=healthcare", "label.symbolNotForEnvironment"),
                        ("symbol=gs1dm&env=retail-gd&size=150", "label.sizeOutOfRange"),
                        ("env=logistics", "label.environmentNotForKey"),
                        ("symbol=dm&env=dpm&linear=auto", "label.linearNotForEnvironment")):
    r = get(f"key=01&value={GTIN}&{query}")
    check(f"refused: {query} → {expected}", r.status_code == 422 and r.get_json()["code"] == expected, r.get_json())
r = get(f"key=01&value={GTIN}&symbol=gs1dm&env=retail-gd&size=150")
check("…the sizes of the environment offered in the refusal", r.get_json()["params"]["sizes"] == "80, 90, 100"
      and r.get_json()["params"]["max"] == "0.990", r.get_json())
r = get(f"key=01&value={GTIN}&env=moon")
check("…an unknown environment answered with the names", "pharmacy-gd" in r.get_json()["params"]["names"], r.get_json())
r = get(f"key=01&value={GTIN}&env=logistics")
check("…an environment of other keys answered with the key's", r.get_json()["params"]["names"]
      == "retail, retail-gd, distribution, pharmacy, pharmacy-gd, healthcare, other, dpm", r.get_json())
r = get("key=00&value=095060001234567893&format=png")
check("an SSCC without an environment: table 5, the QR code at 0.743 mm", r.status_code == 200
      and r.headers.get("X-Dimension") == "0.743", (r.status_code, dict(r.headers)))
r = get("key=414&value=9506000134352&symbol=gs1dm&size=150&format=png")
check("a GLN: table 9, a GS1 DataMatrix at 150 % (0.562 mm)", r.status_code == 200
      and r.headers.get("X-Dimension") == "0.562", (r.status_code, dict(r.headers)))
cfg = root.get("/portal/api/config").get_json()["labelEnvironments"]
check("the configuration gives the page every environment with its table, keys, symbols, ranges and sizes",
      sorted(cfg, key=lambda n: cfg[n]["rank"]) == list(label.ENVIRONMENTS) and cfg["pharmacy-gd"]["sizesWithLinear"] == [100]
      and cfg["logistics"]["keys"] == ["00"] and cfg["retail"]["keys"] is None and cfg["dpm"]["anyKey"] is True
      and cfg["gsrn"]["table"] == 11
      and cfg["dpm"]["linearX"] is None and cfg["dpm"]["sizesWithLinear"] == [] and cfg["retail"]["x"] == [0.396, 0.495, 0.99],
      cfg)
key, _ = apikeys.create("Labels", ["labels:read"], 30, [], None, "root")
api = portal.app.test_client()
r = api.get(f"/portal/api/v1/labels/01/{GTIN}?symbol=gs1dm&format=png", headers={"Authorization": f"Bearer {key}"})
check("tenant API: the same options", r.status_code == 200 and ("Data Matrix", "]d2", f"(01){GTIN}")
      in read(r.data), r.status_code)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
keys = ["label.symbol", "label.symbol.qr", "label.symbol.dm", "label.symbol.gs1dm", "label.env", "label.env.retail",
        "label.env.healthcare", "label.env.dpm", "label.env.retail-gd", "label.env.distribution", "label.env.pharmacy",
        "label.env.pharmacy-gd", "label.env.other", "label.env.logistics", "label.env.assets", "label.env.gsrn",
        "label.envHint", "label.environmentNotForKey", "label.hriText", "label.hriText.outline", "label.hriText.text",
        "preview.dmInfo", "label.symbolInvalid", "label.environmentInvalid", "label.hriTextInvalid",
        "label.symbolNotForEnvironment", "label.linearNotForEnvironment", "label.sizeOutOfRange", "label.dataMatrixRefused"]
missing = [k for k in keys if i18n.count(f'"{k}"') != 2]
check("texts in both languages", not missing, missing)
openapi = open(os.path.join(PORTAL, "openapi.json"), encoding="utf-8").read()
check("the tenant API's description lists the new options", all(f'"name": "{n}"' in openapi for n in ("symbol", "env", "hritext")))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
