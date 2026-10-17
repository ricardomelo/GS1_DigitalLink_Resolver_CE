"""
Renders the QR code label exported by the portal, following the symbol and text dimensions of the
"QR Codes powered by GS1 design guidelines" (version 1.0, May 2024):

- X-dimension: the SVG is sized in millimetres at the target X-dimension (0.495 mm) times the size chosen
  (Documentation/adr/0010-label-studio.md: 80 to 200 %, X from 0.396 to 0.990 mm).
- Quiet zone: 4X on all four sides, always kept blank.
- Human readable interpretation (HRI): the element strings below the quiet zone, e.g.
  "(01)09506000164960" and, for a batch, "(10)ABC123" on a second line.
- Text height: at least 2 mm is required; TEXT_HEIGHT_MM gives a small margin above that at
  100 % size. Printing smaller than 100 % would take the text below the minimum.

- A linear barcode beside the QR code (EAN-13, UPC-A, EAN-8, UPC-E; linear.py) for the transition to 2D, at 0.330 mm
  times the same size, with its quiet zones, guard bars and human readable digits.

Item 9.3 (ADR 0010, section 7): the 2D symbol may also be a Data Matrix carrying the GS1 Digital Link URI or a GS1 DataMatrix
carrying the element string (FNC1 first, libzint through zint-bindings); the X-dimensions come from the scanning
environment chosen (ENVIRONMENTS: the ranges of the GS1 General Specifications' symbol specification tables), the size
a percentage of its target, refused outside its range; the HRI of the SVG may be real text instead of outlines.

Every format is built from the same geometry, expressed in units of the 2D symbol's module: SVG is fully vector (modules,
bars and HRI glyph outlines, so no fonts are needed to open it); PDF the same, written here without a library; PNG is
rasterised at a whole number of pixels per module and carries a DPI value that reproduces the size when printed.
"""
import io
import os
import re
import zipfile
import zlib
from dataclasses import dataclass
from functools import lru_cache

import segno
import zint
from fontTools.pens.basePen import BasePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

import linear

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
HRI_FONT = os.path.join(ASSETS, "fonts", "LiberationSans-Regular.ttf")

TARGET_X_MM = 0.495          # target X-dimension for GS1 Digital Link on consumer units
LINEAR_X_MM = 0.330          # EAN/UPC X-dimension at 100 % magnification
SIZES = (80, 90, 100, 120, 150, 200)   # magnifications offered: X 0.396 to 0.990 mm (QR), 0.264 to 0.660 mm (EAN/UPC)
LINEAR_GAP = 4.0             # between the QR code's quiet zone and the linear symbol's, in QR modules
TEXT_HEIGHT_MM = 2.2         # guideline minimum is 2 mm for the HRI
QUIET_ZONE = 4               # in X
TEXT_GAP = 1.0               # clearance between text and the quiet zone, in X
MARGIN = 2.0                 # white border around the whole label, in X
LINE_SPACING = 1.6           # HRI baseline-to-baseline distance, as a multiple of the text height
PNG_PIXELS_PER_MODULE = 12   # ≈ 616 dpi at the target X-dimension; 8 pixels per EAN/UPC module


ERROR_LEVELS = ("l", "m", "q", "h")          # QR error correction: about 7 %, 15 %, 25 %, 30 % recoverable

# The 2D symbols (ADR 0010, section 7 of item 9.3): QR code and Data Matrix with the GS1 Digital Link URI, GS1 DataMatrix
# with the element string (FNC1 in first position, the GS1 system's own Data Matrix).
SYMBOLS = ("qr", "dm", "gs1dm")
SYMBOL_NAMES = {"qr": "GS1 Digital Link QR code", "dm": "Data Matrix with a GS1 Digital Link URI",
                "gs1dm": "GS1 DataMatrix"}
# Scanning environments: the X-dimension (min, target, max) in mm of the 2D symbol and of EAN/UPC, from the GS1 General
# Specifications' symbol specification tables (section 5.12.3), and the 2D symbols each takes. Sources and the values
# still to be checked against the current release: ADR 0010, section 7.
ENVIRONMENTS = {
    # Table 1 and its addendum for 2D symbols: trade items scanned at general retail point of sale
    "retail": {"2d": (0.396, 0.495, 0.990), "linear": (0.264, 0.330, 0.660), "symbols": SYMBOLS},
    # Regulated healthcare trade items: GS1 DataMatrix (and the Digital Link URI in a Data Matrix); EAN/UPC as retail
    "healthcare": {"2d": (0.254, 0.380, 0.495), "linear": (0.264, 0.330, 0.660), "symbols": ("gs1dm", "dm")},
    # Direct part marking: Data Matrix only, no linear symbol
    "dpm": {"2d": (0.254, 0.300, 0.615), "linear": None, "symbols": ("gs1dm", "dm")},
}
OCR_B = "OCR-B, 'OCR B', 'OCR-B 10 BT', monospace"         # the font of EAN/UPC digits, when the HRI is text
HRI_FONT_FAMILY = "'Liberation Sans', Arial, Helvetica, sans-serif"


@dataclass(frozen=True)
class LabelOptions:
    """What to draw: the URI, the lines of human readable text, whether to show them, the QR version
    (None: the smallest that fits), the error correction level, the size (a percentage of the target X-dimensions)
    and an EAN/UPC symbol beside the QR code ((kind, digits) from linear.symbol_for(), or None).
    """
    uri: str
    hri_lines: tuple[str, ...]
    show_hri: bool
    version: int | None = None                  # QR version 1-40; None chooses the smallest that fits
    error: str = "m"                            # error correction level, exactly as chosen
    size: int = 100                             # percentage of the target X-dimensions, one of SIZES
    linear: tuple[str, str] | None = None       # ("ean13" | "upca" | "upce" | "ean8", digits)
    symbol: str = "qr"                          # one of SYMBOLS
    element_string: str = ""                    # the element string with brackets, for "gs1dm"
    environment: str = "retail"                 # one of ENVIRONMENTS
    hri_text: bool = False                      # the SVG's HRI as text (needs the fonts) instead of outlines

    @property
    def x_mm(self) -> float:
        """The 2D symbol's X-dimension in millimetres: the environment's target times the size."""
        return ENVIRONMENTS[self.environment]["2d"][1] * self.size / 100

    @property
    def linear_x_mm(self) -> float:
        """The EAN/UPC X-dimension in millimetres."""
        ranges = ENVIRONMENTS[self.environment]["linear"]
        return (ranges[1] if ranges else LINEAR_X_MM) * self.size / 100


class OutOfRange(ValueError):
    """A size, symbol or linear symbol the scanning environment does not allow: code and parameters for the message."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def sizes_for(environment: str, with_linear: bool = False) -> list[int]:
    """The sizes (percentages of the environment's targets) whose X-dimensions stay within its ranges."""
    env = ENVIRONMENTS[environment]
    ranges = [env["2d"]] + ([env["linear"]] if with_linear and env["linear"] else [])
    return [s for s in SIZES if all(low - 1e-9 <= target * s / 100 <= high + 1e-9 for low, target, high in ranges)]


def check_environment(options: "LabelOptions") -> None:
    """Refuses what the scanning environment does not allow (OutOfRange)."""
    env = ENVIRONMENTS.get(options.environment)
    if env is None:
        raise OutOfRange("label.environmentInvalid")
    if options.symbol not in env["symbols"]:
        raise OutOfRange("label.symbolNotForEnvironment")
    if options.linear and not env["linear"]:
        raise OutOfRange("label.linearNotForEnvironment")
    if options.size not in sizes_for(options.environment, bool(options.linear)):
        low, _, high = env["2d"]
        raise OutOfRange("label.sizeOutOfRange", min=f"{low:.3f}", max=f"{high:.3f}",
                         sizes=", ".join(map(str, sizes_for(options.environment, bool(options.linear)))))


class DoesNotFit(ValueError):
    """The URI does not fit the chosen QR version at the chosen error correction level."""

    def __init__(self, version: int | None, error: str, needed: int | None, fitting_level: str | None):
        super().__init__(f"{version}-{error}")
        # needed: smallest version that fits at this level (None: not even version 40)
        # fitting_level: highest level at which the chosen version fits (None: none does)
        self.params = {"version": version, "level": error.upper(), "needed": needed,
                       "fittingLevel": fitting_level.upper() if fitting_level else None}


@dataclass(frozen=True)
class DataMatrix:
    """A Data Matrix made by libzint: its modules (rows of booleans) and size."""
    matrix: tuple[tuple[bool, ...], ...]
    rows: int
    columns: int
    gs1: bool


class DataMatrixError(ValueError):
    """libzint refused the data (too long for the largest symbol, or an element string it does not accept)."""


def data_matrix(data: str, gs1_mode: bool) -> DataMatrix:
    """A square ECC 200 Data Matrix: GS1 mode for an element string with brackets ("(01)…(10)…": FNC1 first and
    between variable-length fields), plain data for a URI."""
    sym = zint.Symbol()
    sym.symbology = zint.Symbology.DATAMATRIX
    sym.input_mode = (zint.InputMode.GS1 | zint.InputMode.GS1PARENS) if gs1_mode else zint.InputMode.DATA
    sym.option_3 = zint.DataMatrixOptions.SQUARE
    try:
        sym.encode(data)
    except Exception as exc:                       # zint raises RuntimeError with its message
        raise DataMatrixError(str(exc)[:200]) from None
    if sym.errtxt and sym.errtxt.startswith("Error"):
        raise DataMatrixError(sym.errtxt[:200])
    rows, columns = sym.rows, sym.width
    raw, stride = bytes(sym.encoded_data), sym.encoded_data.shape[1]   # rows of bytes, the first module in bit 0
    matrix = tuple(tuple(bool(raw[r * stride + c // 8] >> (c % 8) & 1) for c in range(columns)) for r in range(rows))
    return DataMatrix(matrix, rows, columns, gs1_mode)


def symbol(options: LabelOptions):
    """The 2D symbol for the label. QR: the level is never raised automatically (segno's boost_error), so
    the code is exactly what the user chose; Micro QR is never used. Data Matrix: square, ECC 200."""
    if options.symbol == "gs1dm":
        return data_matrix(options.element_string, True)
    if options.symbol == "dm":
        return data_matrix(options.uri, False)
    try:
        return segno.make(options.uri, error=options.error, version=options.version, micro=False, boost_error=False)
    except segno.DataOverflowError:
        needed = _smallest_version(options.uri, options.error)
        fitting = None
        if options.version:
            fitting = next((level for level in reversed(ERROR_LEVELS)
                            if _fits(options.uri, level, options.version)), None)
        raise DoesNotFit(options.version, options.error, needed, fitting) from None


def _fits(uri: str, error: str, version: int) -> bool:
    """Whether the URI fits the QR version at the error correction level, exactly as chosen."""
    try:
        segno.make(uri, error=error, version=version, micro=False, boost_error=False)
        return True
    except segno.DataOverflowError:
        return False


def _smallest_version(uri: str, error: str) -> int | None:
    """The smallest QR version holding the URI at that level, or None when not even version 40 does."""
    try:
        return segno.make(uri, error=error, micro=False, boost_error=False).version
    except segno.DataOverflowError:
        return None


# --------------------------------------------------------------------------- assets
@lru_cache(maxsize=1)
def _font() -> TTFont:
    """The HRI font (Liberation Sans), loaded once."""
    return TTFont(HRI_FONT)


def _font_metrics() -> tuple[int, int, int]:
    """Units per em, cap height and descent of the HRI font, to size the text in millimetres."""
    font = _font()
    return font["head"].unitsPerEm, font["OS/2"].sCapHeight, -font["hhea"].descent


def _text_width(text: str, em: float) -> float:
    """Advance width of `text` at an em size given in X units."""
    font = _font()
    units_per_em = font["head"].unitsPerEm
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    return sum(hmtx[cmap[ord(ch)]][0] for ch in text) * em / units_per_em


# --------------------------------------------------------------------------- geometry
@dataclass
class _Layout:
    """Geometry of a label in units of the QR module: dark rectangles (modules and bars) and text lines."""
    width: float
    height: float
    rects: list[tuple[float, float, float, float]]       # x, y, width, height
    texts: list[tuple]                                   # text, x (left), baseline, em[, "linear" for EAN/UPC digits]
    x_mm: float                                          # millimetres per unit


def _qr_rects(matrix, x0: float, y0: float) -> list[tuple[float, float, float, float]]:
    """The dark modules, one rectangle per horizontal run."""
    rects = []
    for row_index, row in enumerate(matrix):
        col, size = 0, len(row)
        while col < size:
            if row[col]:
                start = col
                while col < size and row[col]:
                    col += 1
                rects.append((x0 + start, y0 + row_index, col - start, 1))
            else:
                col += 1
    return rects


def _layout(options: LabelOptions) -> _Layout:
    """Places the symbol, its quiet zone and the HRI lines (text never below 2 mm), then the linear symbol, if any,
    to the right with its own quiet zones, tops aligned."""
    if options.size not in SIZES:
        raise ValueError(f"size {options.size} is not one of {SIZES}")
    check_environment(options)
    qr = symbol(options)
    matrix = [list(row) for row in qr.matrix]
    modules = len(matrix[0]) if matrix else 0
    box = modules + 2 * QUIET_ZONE

    units_per_em, cap_height, descent = _font_metrics()
    text_height = TEXT_HEIGHT_MM / options.x_mm
    em = text_height * units_per_em / cap_height
    lines = list(options.hri_lines) if options.show_hri else []
    widths = [_text_width(line, em) for line in lines]
    content_width = max([box] + widths)

    box_x = MARGIN + (content_width - box) / 2
    box_y = MARGIN
    rects = _qr_rects(matrix, box_x + QUIET_ZONE, box_y + QUIET_ZONE)
    texts = []
    y = box_y + len(matrix) + 2 * QUIET_ZONE
    for index, (line, line_width) in enumerate(zip(lines, widths)):
        baseline = y + TEXT_GAP + text_height + index * text_height * LINE_SPACING
        texts.append((line, MARGIN + (content_width - line_width) / 2, baseline, em))
    if texts:
        y = texts[-1][2] + descent * em / units_per_em
    width, height = MARGIN + content_width, y

    if options.linear:
        width, height = _place_linear(options, rects, texts, width, box_y, height)
    return _Layout(width + MARGIN, height + MARGIN, rects, texts, options.x_mm)


def _place_linear(options: LabelOptions, rects, texts, left: float, top: float, bottom: float) -> tuple[float, float]:
    """Adds the EAN/UPC symbol to the right of `left`; returns the new right edge and bottom."""
    code = linear.encode(*options.linear)
    unit = options.linear_x_mm / options.x_mm           # one linear module in 2D modules (the same size applies)
    quiet_left, quiet_right = code.quiet
    x0 = left + LINEAR_GAP + quiet_left * unit
    bar_bottom = top + code.bar_height * unit
    guard_bottom = bar_bottom + linear.GUARD_EXTENSION * unit
    index = 0
    while index < len(code.modules):
        if code.modules[index] == "1":
            start = index
            while index < len(code.modules) and code.modules[index] == "1" and \
                    (index in code.extended) == (start in code.extended):
                index += 1
            low = guard_bottom if start in code.extended else bar_bottom
            rects.append((x0 + start * unit, top, (index - start) * unit, low - top))
        else:
            index += 1
    units_per_em, cap_height, descent = _font_metrics()
    lowest = guard_bottom
    for text, centre, relative in code.digits:
        height = linear.DIGIT_HEIGHT * unit * relative
        em = height * units_per_em / cap_height
        baseline = bar_bottom + 0.6 * unit + height
        texts.append((text, x0 + centre * unit - _text_width(text, em) / 2, baseline, em, "linear"))
        lowest = max(lowest, baseline + descent * em / units_per_em)
    right = x0 + (len(code.modules) + quiet_right) * unit
    return right, max(bottom, lowest)


# --------------------------------------------------------------------------- SVG
def _rects_path(layout: _Layout) -> str:
    return "".join(f"M{x:g},{y:g}h{w:g}v{h:g}h{-w:g}z" for x, y, w, h in
                   ((round(x, 4), round(y, 4), round(w, 4), round(h, 4)) for x, y, w, h in layout.rects))


def _hri_path(text: str, x: float, baseline: float, em: float) -> str:
    """SVG path of a line of text drawn with the font's glyph outlines (no font needed to view it)."""
    pen = SVGPathPen(_font().getGlyphSet(), ntos=lambda v: f"{v:.3f}".rstrip("0").rstrip("."))
    _draw_text(pen, text, x, baseline, em)
    return pen.getCommands()


def _draw_text(pen, text: str, x: float, baseline: float, em: float) -> None:
    font = _font()
    glyph_set = font.getGlyphSet()
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    scale = em / font["head"].unitsPerEm
    cursor = x
    for ch in text:
        name = cmap[ord(ch)]
        glyph_set[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, baseline)))
        cursor += hmtx[name][0] * scale


def render_svg(options: LabelOptions) -> bytes:
    """The label as SVG sized in millimetres, text as outlines."""
    layout = _layout(options)
    w_mm, h_mm = layout.width * layout.x_mm, layout.height * layout.x_mm
    linear_note = (f", {linear.NAMES[options.linear[0]]} {options.linear[1]} at X = "
                   f"{options.linear_x_mm:.3f} mm" if options.linear else "")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_mm:.3f}mm" height="{h_mm:.3f}mm" '
        f'viewBox="0 0 {layout.width:.4f} {layout.height:.4f}">',
        f"<title>{_xml(options.element_string if options.symbol == 'gs1dm' else options.uri)}</title>",
        f'<desc>{SYMBOL_NAMES[options.symbol]} at {options.size} % of the target size of the scanning environment '
        f'{options.environment} (X = {layout.x_mm:.3f} mm), quiet zone {QUIET_ZONE}X{linear_note}.</desc>',
        f'<rect width="{layout.width:.4f}" height="{layout.height:.4f}" fill="#fff"/>',
        f'<path fill="#000" shape-rendering="crispEdges" d="{_rects_path(layout)}"/>',
    ]
    for text, x, baseline, em, *kind in layout.texts:
        if options.hri_text:                 # real text: editable, needs the fonts where it is printed (OCR-B for EAN/UPC)
            family = OCR_B if kind else HRI_FONT_FAMILY
            parts.append(f'<text x="{x:.4f}" y="{baseline:.4f}" font-family="{family}" font-size="{em:.4f}" '
                         f'fill="#000">{_xml(text)}</text>')
        else:
            parts.append(f'<path fill="#000" aria-label="{_xml(text)}" d="{_hri_path(text, x, baseline, em)}"/>')
    parts.append("</svg>")
    return "\n".join(parts).encode("utf-8")


def _xml(value: str) -> str:
    """Escapes text for XML attributes and elements."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --------------------------------------------------------------------------- PNG
def render_png(options: LabelOptions) -> bytes:
    """The label as PNG at PNG_PIXELS_PER_MODULE pixels per QR module, its DPI giving the size when printed."""
    layout = _layout(options)
    px = PNG_PIXELS_PER_MODULE

    def p(value: float) -> int:
        return round(value * px)

    image = Image.new("RGB", (p(layout.width), p(layout.height)), "white")
    draw = ImageDraw.Draw(image)
    for x, y, w, h in layout.rects:
        draw.rectangle([p(x), p(y), p(x + w) - 1, p(y + h) - 1], fill="black")
    for text, x, baseline, em, *_ in layout.texts:
        font = ImageFont.truetype(HRI_FONT, size=max(1, round(em * px)))
        draw.text((p(x), p(baseline)), text, fill="black", font=font, anchor="ls")

    dpi = px / layout.x_mm * 25.4
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi), optimize=True)
    return buffer.getvalue()


# --------------------------------------------------------------------------- PDF
class _PdfPen(BasePen):
    """Glyph outlines as PDF path operators; quadratic curves become cubic ones (BasePen)."""

    def __init__(self, glyph_set, to_pdf):
        super().__init__(glyph_set)
        self.to_pdf, self.ops = to_pdf, []

    def _point(self, pt) -> str:
        x, y = self.to_pdf(*pt)
        return f"{x:.3f} {y:.3f}"

    def _moveTo(self, pt):
        self.ops.append(f"{self._point(pt)} m")

    def _lineTo(self, pt):
        self.ops.append(f"{self._point(pt)} l")

    def _curveToOne(self, pt1, pt2, pt3):
        self.ops.append(f"{self._point(pt1)} {self._point(pt2)} {self._point(pt3)} c")

    def _closePath(self):
        self.ops.append("h")


def _pdf_text(value: str) -> str:
    """A PDF literal string."""
    return "(" + value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def render_pdf(options: LabelOptions) -> bytes:
    """The label as a one-page PDF the size of the label: vector modules, bars and glyph outlines, no fonts."""
    layout = _layout(options)
    scale = layout.x_mm * 72 / 25.4                       # points per unit
    page_w, page_h = layout.width * scale, layout.height * scale

    def to_pdf(x: float, y: float) -> tuple[float, float]:
        return x * scale, page_h - y * scale

    ops = ["1 g", f"0 0 {page_w:.3f} {page_h:.3f} re f", "0 g"]
    for x, y, w, h in layout.rects:
        px, py = to_pdf(x, y + h)
        ops.append(f"{px:.3f} {py:.3f} {w * scale:.3f} {h * scale:.3f} re")
    ops.append("f")
    for text, x, baseline, em, *_ in layout.texts:
        pen = _PdfPen(_font().getGlyphSet(), to_pdf)
        _draw_text(pen, text, x, baseline, em)
        ops.extend(pen.ops)
        ops.append("f")
    content = zlib.compress("\n".join(ops).encode("ascii"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.3f} {page_h:.3f}] /Contents 4 0 R "
        f"/Resources << >> >>".encode("ascii"),
        f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode("ascii") + content + b"\nendstream",
        f"<< /Title {_pdf_text(options.element_string if options.symbol == 'gs1dm' else options.uri)} "
        f"/Producer (GS1 Resolver CE portal) >>".encode("latin-1", "replace"),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n".encode("ascii"))
    return out.getvalue()


# --------------------------------------------------------------------------- every format
def render_zip(options: LabelOptions, name: str) -> bytes:
    """The label as SVG, PNG and PDF, and a README.txt with the URI, the options and the sizes (backlog item 5.4)."""
    layout = _layout(options)
    w_mm, h_mm = layout.width * layout.x_mm, layout.height * layout.x_mm
    code = symbol(options)
    target = ENVIRONMENTS[options.environment]["2d"][1]
    if options.symbol == "qr":
        lines = [f"GS1 Digital Link: {options.uri}",
                 f"QR code: version {code.version}, error correction {code.error.upper()}, {len(code.matrix)} x "
                 f"{len(code.matrix)} modules,"]
    else:
        lines = [f"GS1 element string: {options.element_string}" if options.symbol == "gs1dm"
                 else f"GS1 Digital Link: {options.uri}",
                 f"{SYMBOL_NAMES[options.symbol]}: ECC 200, {code.rows} x {code.columns} modules,"]
    lines[-1] += (f" X = {layout.x_mm:.3f} mm ({options.size} % of the target {target:.3f} mm of the scanning environment "
                  f"{options.environment}), quiet zone {QUIET_ZONE}X")
    if options.linear:
        kind, digits = options.linear
        lines.append(f"{linear.NAMES[kind]}: {digits}, X = {options.linear_x_mm:.3f} mm "
                     f"({options.size} % magnification), bar height {linear.BAR_HEIGHT[kind] * options.linear_x_mm:.2f} mm")
    lines += [f"Human readable text: {' '.join(options.hri_lines) if options.show_hri else 'none'}",
              f"Label size: {w_mm:.1f} x {h_mm:.1f} mm; print at 100 % (no scaling) to keep these dimensions.",
              "Files: SVG and PDF are vector (for artwork); PNG is for screens and documents (its DPI gives the size)."]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}.svg", render_svg(options))
        archive.writestr(f"{name}.png", render_png(options))
        archive.writestr(f"{name}.pdf", render_pdf(options))
        archive.writestr("README.txt", "\r\n".join(lines) + "\r\n")
    return out.getvalue()
