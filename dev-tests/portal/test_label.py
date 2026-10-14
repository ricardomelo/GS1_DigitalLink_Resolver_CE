"""
The label studio (Documentation/adr/0010-label-studio.md): sizes of the QR code (and the 2 mm minimum of its text),
EAN-13, UPC-A, EAN-8 and UPC-E beside it (the symbol a GTIN takes, UPC-E's zero suppression, the module patterns
against reference patterns read back by an independent decoder, the decoded symbols in the PNG, quiet zones, bar
heights, human readable digits), the PDF (structure, size, every rectangle, the URI as its title), the zip of every
format, the defaults drawing exactly what the previous version drew, and the options through the portal and the
tenant API.

  pip install -r portal/requirements.txt mongomock opencv-python-headless
  python dev-tests/portal/test_label.py
"""
import hashlib
import io
import os
import re
import sys
import tempfile
import threading
import zipfile
import zlib

import cv2
import numpy as np
from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3391
sys.path[:0] = [HERE, PORTAL]
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_label_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import apikeys  # noqa: E402
import app as portal  # noqa: E402
import label  # noqa: E402
import linear  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def options(gtin="07891234500014", **extra):
    return label.LabelOptions(uri=f"https://id.example.org/01/{gtin}", hri_lines=(f"(01){gtin}",), show_hri=True, **extra)


def decode_png(png: bytes) -> tuple[str, set]:
    """(the QR code's text, the EAN/UPC texts OpenCV reads at a few scales)."""
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    qr = cv2.QRCodeDetector().detectAndDecode(img)[0]
    found = set()
    detector = cv2.barcode.BarcodeDetector()
    for scale in (0.25, 0.2, 0.33):
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        small = cv2.copyMakeBorder(small, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        text = detector.detectAndDecode(small)[0]
        if text:
            found.add(text)
    return qr, found


# ================================================================== linear symbols
check("check digits", linear.check_digit("789123450001") == "4" and linear.check_digit("61414112345") == "2")
for gtin, choice, expected in [("07891234500014", "auto", ("ean13", "7891234500014")),
                               ("00614141123452", "auto", ("upca", "614141123452")),
                               ("00000096385074", "auto", ("ean8", "96385074")),
                               ("00042100005264", "upce", ("upce", "04252614")),
                               ("00012345000058", "upce", ("upce", "01234558"))]:
    check(f"symbol for {gtin} ({choice}): {expected[0]}", linear.symbol_for(gtin, choice) == expected,
          linear.symbol_for(gtin, choice))
for gtin, choice in [("17891234500011", "auto"), ("0789123450001X", "auto"), ("0789123450001", "auto"),
                     ("07891234500014", "upce"), ("00614141123452", "upce"), ("00000096385074", "upce"),
                     ("07891234500014", "ean13")]:
    try:
        linear.symbol_for(gtin, choice)
        refused = False
    except linear.NotPossible:
        refused = True
    check(f"refused: {gtin} as {choice}", refused)
check("UPC-E's four zero suppression rules", [linear.upce_from_upca(v) for v in
      ("012000003455", "012300000645", "012340000065", "012345000059", "012345600001", "012300100009")]
      == ["123450", "123643", "123464", "123455", None, None])
# Reference patterns, read back by an independent decoder (zxing-cpp) when they were written
REFERENCE = {
    ("ean13", "7891234500014"): "10101101110010111001100100110110111101001110101010100111011100101110010111001011001101011100101",
    ("upca", "614141123452"): "10101011110011001010001100110010100011001100101010110011011011001000010101110010011101101100101",
    ("ean8", "96385074"): "1010001011010111101111010110111010101001110111001010001001011100101",
    ("upce", "04252614"): "101001110100100110111001001101101011110011001010101",
}
for (kind, digits), modules in REFERENCE.items():
    code = linear.encode(kind, digits)
    check(f"{linear.NAMES[kind]} {digits}: the reference pattern", code.modules == modules, code.modules)
check("lengths: 95, 95, 67 and 51 modules", [len(linear.encode(k, d).modules) for k, d in REFERENCE] == [95, 95, 67, 51])
UPCE_REFERENCE = {          # one per check digit (its parity), read back by zxing-cpp when they were written
    "01002850": "101011001101001110100111001001101101110110001010101",
    "01000771": "101011001101001110001101010011101110110111011010101",
    "01010572": "101011001101001110011001000110101110010111011010101",
    "01004953": "101011001101001110001101010001100010110111001010101",
    "01000764": "101011001100011010100111010011101110110101111010101",
    "01000795": "101011001100011010001101010011100100010001011010101",
    "01007756": "101011001100011010001101011101100100010111001010101",
    "01000757": "101011001100011010100111000110100100010110001010101",
    "01000788": "101011001100011010100111000110101110110001001010101",
    "01009859": "101011001100011010001101001011101101110111001010101",
}
for digits, modules in UPCE_REFERENCE.items():
    check(f"UPC-E {digits}: the reference pattern (check digit {digits[-1]})", linear.encode("upce", digits).modules == modules)
for first in range(10):
    body = f"{first}78912345000"
    digits = body + linear.check_digit(body)
    png = label.render_png(label.LabelOptions(uri="https://x.example/", hri_lines=(), show_hri=False,
                                              linear=("ean13", digits)))
    read = decode_png(png)[1]          # a leading 0 is a UPC-A: read as its 12 digits
    check(f"EAN-13 with the first digit {first} (its parity) read back", digits in read or (first == 0 and digits[1:] in read),
          (digits, read))
ean13 = linear.encode("ean13", "7891234500014")
check("EAN-13: guard bars extended, its first digit outside the bars, 13 digits",
      len(ean13.extended) == 11 and ean13.digits[0][1] < 0 and "".join(d for d, _, _ in ean13.digits) == "7891234500014")
upca = linear.encode("upca", "614141123452")
check("UPC-A: guards and the first and last characters extended, the outer digits smaller and outside",
      len(upca.extended) == 25 and upca.digits[0][2] < 1 and upca.digits[-1][1] > 95 and upca.digits[-1][2] < 1)
try:
    linear.encode("ean13", "7891234500015")
    wrong = False
except linear.NotPossible:
    wrong = True
check("a wrong check digit is refused", wrong)

# ================================================================== sizes and the defaults
# The previous version of label.py (commit 16ceb9f) drew these, for the same options: the default must not change
BEFORE_SIZE_MM = ("32.565", "27.188")                     # the SVG with two lines of text
BEFORE_PIXELS = "7ba1f5a6bad2aaa399d03f45bc675337b3c46630989e21909597337c0a1315b0"   # the PNG without text, 492 x 492
new_svg = label.render_svg(label.LabelOptions(uri="https://id.example.org/01/07891234500014",
                                              hri_lines=("(01)07891234500014", "(10)L1"), show_hri=True)).decode()
check("the default label is the size the previous version drew", re.search(
    r'width="([\d.]+)mm" height="([\d.]+)mm"', new_svg).groups() == BEFORE_SIZE_MM, new_svg[:200])
plain_png = Image.open(io.BytesIO(label.render_png(label.LabelOptions(uri="https://id.example.org/01/07891234500014",
                                                                     hri_lines=(), show_hri=False))))
check("…and the same symbol, pixel for pixel", plain_png.size == (492, 492)
      and hashlib.sha256(plain_png.convert("1").tobytes()).hexdigest() == BEFORE_PIXELS)
sizes = {}
for pct in label.SIZES:
    svg = label.render_svg(options(size=pct)).decode()
    sizes[pct] = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
    check(f"size {pct} %: X = {0.495 * pct / 100:.3f} mm in the description", f"X = {0.495 * pct / 100:.3f} mm" in svg)
layout_80 = label._layout(options(size=80))
upm, cap, _ = label._font_metrics()
check("at 80 % the text stays at least 2 mm high", layout_80.texts[0][3] * cap / upm * layout_80.x_mm >= 2.0,
      layout_80.texts[0][3] * cap / upm * layout_80.x_mm)
def symbol_mm(pct):
    lay = label._layout(options(size=pct))
    modules = [r for r in lay.rects if r[3] == 1]
    return (max(x + w for x, _, w, _ in modules) - min(x for x, *_ in modules)) * lay.x_mm


check("the QR code's symbol grows with the size (200 % twice 100 %), the text staying 2.2 mm",
      abs(symbol_mm(200) - 2 * symbol_mm(100)) < 0.01 and abs(symbol_mm(80) - 0.8 * symbol_mm(100)) < 0.01
      and sizes[200] > sizes[100] > sizes[80], (symbol_mm(80), symbol_mm(100), symbol_mm(200), sizes))
png = label.render_png(options(size=150))
dpi = re.search(rb"pHYs(.{4})", png)
check("the PNG's DPI gives the size when printed", dpi and abs(int.from_bytes(dpi.group(1), "big") * 0.0254
                                                              - 12 / (0.495 * 1.5) * 25.4) < 1)
try:
    label._layout(options(size=75))
    refused = False
except ValueError:
    refused = True
check("a size that is not offered is refused", refused)

# ================================================================== the QR code with a linear symbol
for gtin, choice in [("07891234500014", "auto"), ("00614141123452", "auto"), ("00000096385074", "auto"),
                     ("00042100005264", "upce")]:
    kind, digits = linear.symbol_for(gtin, choice)
    for pct in (80, 100, 200):
        opts = options(gtin, size=pct, linear=(kind, digits))
        png = label.render_png(opts)
        qr, read = decode_png(png)
        expected = {"ean13": digits, "upca": digits, "ean8": digits}.get(kind)
        good = qr == opts.uri and (expected is None or expected in read or "0" + digits in read)
        check(f"{linear.NAMES[kind]} beside the QR code at {pct} %: both read back", good, (qr, read))
lay = label._layout(options(size=100, linear=("ean13", "7891234500014")))
unit = 0.330 / 0.495
bars = [r for r in lay.rects if r[3] > 40]
right_bar = max(x + w for x, _, w, _ in bars)
left_bar = min(x for x, _, _, _ in bars)
qr_right = max(x + w for x, y, w, h in lay.rects if h == 1)
check("EAN-13 at 100 %: bars 22.85 mm high, guard bars 5X longer",
      abs(min(h for *_, h in bars) * lay.x_mm - 22.85) < 0.01 and abs((max(h for *_, h in bars) - min(h for *_, h in bars))
                                                                     / unit - 5) < 0.01)
check("…its right quiet zone (7X) inside the label", (lay.width - label.MARGIN - right_bar) / unit >= 7 - 1e-6,
      (lay.width - label.MARGIN - right_bar) / unit)
check("…its left quiet zone (11X) clear of the QR code's", (left_bar - qr_right - label.QUIET_ZONE) / unit >= 11,
      (left_bar - qr_right - label.QUIET_ZONE) / unit)
check("…its human readable digits under the bars", sum(1 for t in lay.texts if len(t[0]) == 1) == 13)
plain = label._layout(options(size=100))
check("…the label wider by the gap, both quiet zones (11X, 7X) and 95 modules",
      abs(lay.width - plain.width - (label.LINEAR_GAP + (11 + 95 + 7) * unit)) < 1e-6, lay.width - plain.width)
big = label._layout(options(size=200, linear=("ean13", "7891234500014")))
check("…at 200 %: X = 0.660 mm, bars 45.70 mm high", abs(min(h for *_, h in big.rects if h > 40) * big.x_mm - 45.70) < 0.02,
      min(h for *_, h in big.rects if h > 40) * big.x_mm)

# ================================================================== PDF and zip
opts = options(size=120, linear=("upca", "614141123452"))
pdf = label.render_pdf(opts)
check("PDF: a version 1.4 file ending with its trailer", pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"))
xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", pdf)]
check("…its cross-reference table points at each object", pdf[xref:xref + 4] == b"xref" and all(
    pdf[o:o + len(f"{i} 0 obj")] == f"{i} 0 obj".encode() for i, o in enumerate(offsets, start=1)), offsets)
lay = label._layout(opts)
box = [float(v) for v in re.search(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", pdf).groups()]
check("…one page the size of the label", abs(box[0] - lay.width * lay.x_mm * 72 / 25.4) < 0.01
      and abs(box[1] - lay.height * lay.x_mm * 72 / 25.4) < 0.01, box)
stream = re.search(rb"stream\n(.*)\nendstream", pdf, re.S).group(1)
content = zlib.decompress(stream).decode()
check("…every module and bar a filled rectangle, the text as outlines (no font)",
      content.count(" re") == len(lay.rects) + 1 and " c\n" in content and "/Font" not in pdf.decode("latin-1"),
      (content.count(" re"), len(lay.rects)))
check("…the URI as its title", f"/Title ({opts.uri})".encode() in pdf)
archive = zipfile.ZipFile(io.BytesIO(label.render_zip(opts, "qrcode_01_00614141123452")))
names = sorted(archive.namelist())
check("zip: SVG, PNG, PDF and README.txt", names == ["README.txt", "qrcode_01_00614141123452.pdf",
                                                    "qrcode_01_00614141123452.png", "qrcode_01_00614141123452.svg"], names)
readme = archive.read("README.txt").decode()
check("…the README gives the URI, both X-dimensions, the bar height and the size", opts.uri in readme
      and "X = 0.594 mm" in readme and "UPC-A: 614141123452, X = 0.396 mm" in readme and "bar height 27.42 mm" in readme
      and "print at 100 %" in readme, readme)
check("…the same files as the single downloads", archive.read("qrcode_01_00614141123452.svg") == label.render_svg(opts))

# ================================================================== through the portal and the tenant API
root = portal.app.test_client()
root.post("/portal/api/login", json={"username": "root", "password": "root-password-long"}, headers=ORIGIN)
OPER = "09506000134352"


def get(c, query, headers=None):
    return c.get("/portal/api/qrcode?" + query, headers=headers or {})


r = get(root, f"key=01&value={OPER}&size=200")
check("portal: size=200", r.status_code == 200 and b"X = 0.990 mm" in r.data)
r = get(root, f"key=01&value={OPER}&linear=auto")
check("…linear=auto on a GTIN-13: EAN-13, named in a header", r.status_code == 200
      and r.headers.get("X-Linear-Symbol") == "EAN-13 9506000134352", r.headers.get("X-Linear-Symbol"))
r = get(root, "key=00&value=095060001343520000&linear=auto")
check("…on an SSCC: 422 label.linearNotPossible", r.status_code == 422
      and r.get_json()["code"] == "label.linearNotPossible", r.get_json())
r = get(root, "key=8003&value=09506000134352&linear=auto")
check("…on a GRAI of 14 digits (a key other than the GTIN): refused", r.get_json().get("code") == "label.linearNotPossible")
check("…the names inside a zip: no folders, nothing a file system refuses", portal.zip_name("qrcode_01_x_21_A/B*C:D")
      == "qrcode_01_x_21_A-B-C-D")
r = get(root, f"key=01&value={OPER}&linear=upce")
check("…UPC-E for a GTIN-13: refused", r.get_json()["code"] == "label.linearNotPossible")
r = get(root, f"key=01&value={OPER}&linear=code128")
check("…an unknown linear choice: 422 label.linearInvalid", r.get_json()["code"] == "label.linearInvalid")
r = get(root, f"key=01&value={OPER}&size=75")
check("…size=75: 422 label.sizeInvalid with the sizes offered", r.status_code == 422
      and r.get_json()["code"] == "label.sizeInvalid" and "200" in r.get_json()["params"]["sizes"])
r = get(root, f"key=01&value={OPER}&format=pdf")
check("…format=pdf as a download", r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
      and f'filename="qrcode_01_{OPER}.pdf"' in r.headers["Content-Disposition"])
r = get(root, f"key=01&value={OPER}&qualifiers=/21/A-B.C&format=zip")
inner = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
check("…format=zip, the names inside made of safe characters (a serial included)", r.mimetype == "application/zip"
      and all(re.fullmatch(r"[A-Za-z0-9_.-]+", n) for n in inner) and len(inner) == 4, inner)
key, _ = apikeys.create("Labels", ["labels:read"], 30, [], None, "root")
api = portal.app.test_client()
r = api.get(f"/portal/api/v1/labels/01/{OPER}?linear=auto&size=80&format=pdf", headers={"Authorization": f"Bearer {key}"})
check("tenant API: the same options", r.status_code == 200 and r.mimetype == "application/pdf"
      and r.headers.get("X-Linear-Symbol") == "EAN-13 9506000134352")

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
keys = ["label.size", "label.size.option", "label.size.target", "label.linear", "label.linear.none", "label.linear.auto",
        "label.linear.upce", "label.sizeInvalid", "label.linearNotPossible", "label.linearInvalid", "preview.pdf",
        "preview.zip"]
missing = [k for k in keys if i18n.count(f'"{k}"') != 2]
check("texts in both languages", not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
