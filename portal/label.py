"""
Renders the QR code label exported by the portal, following "QR Codes powered by GS1 design
guidelines" (GS1 branding pilot, version 1.0, May 2024, draft V6):

- X-dimension: the SVG is sized in millimetres at the 100 % target X-dimension (0.495 mm).
- Quiet zone: 4X on all four sides, always kept blank.
- Human readable interpretation (HRI): the element strings below the quiet zone, e.g.
  "(01)09506000164960" and, for a batch, "(10)ABC123" on a second line.
- Optional "GS1®" branding: the supplied artwork (Verdana-based wordmark, outlined), above the
  top-left corner of the symbol and outside the quiet zone, never bold or italic.
- Text height: at least 2 mm is required; TEXT_HEIGHT_MM gives a small margin above that at
  100 % size. Printing smaller than 100 % would take the text below the minimum.

Both formats are built from the same geometry, expressed in units of X (one module):
SVG is fully vector (QR modules, wordmark paths and HRI glyph outlines, so no fonts are needed
to open it); PNG is rasterised at a whole number of pixels per module and carries a DPI value
that reproduces the target size when printed.
"""
import io
import os
import re
from dataclasses import dataclass
from functools import lru_cache

import segno
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
WORDMARK_SVG = os.path.join(ASSETS, "gs1-wordmark.svg")
WORDMARK_PNG = os.path.join(ASSETS, "gs1-wordmark.png")
HRI_FONT = os.path.join(ASSETS, "fonts", "LiberationSans-Regular.ttf")

TARGET_X_MM = 0.495          # target X-dimension for GS1 Digital Link on consumer units
TEXT_HEIGHT_MM = 2.2         # guideline minimum is 2 mm for both "GS1®" and the HRI
QUIET_ZONE = 4               # in X
TEXT_GAP = 1.0               # clearance between text and the quiet zone, in X
MARGIN = 2.0                 # white border around the whole label, in X
LINE_SPACING = 1.6           # HRI baseline-to-baseline distance, as a multiple of the text height
PNG_PIXELS_PER_MODULE = 12   # ≈ 616 dpi at the target X-dimension

TEXT_HEIGHT = TEXT_HEIGHT_MM / TARGET_X_MM   # in X

# Ink box of the supplied GS1® artwork in its SVG viewBox units (measured once from the file):
# the viewBox has padding around the letters, so placement uses the ink box instead.
WORDMARK_INK_LEFT, WORDMARK_INK_TOP, WORDMARK_INK_BOTTOM = 11.6, 11.5, 129.6
WORDMARK_CAP_HEIGHT = 113.9          # height of the "1", i.e. the flat cap height of the wordmark
# Total ink height (with the round overshoot of G, S and ®) relative to the cap height.
WORDMARK_INK_OVER_CAP = (WORDMARK_INK_BOTTOM - WORDMARK_INK_TOP) / WORDMARK_CAP_HEIGHT


@dataclass(frozen=True)
class LabelOptions:
    uri: str
    hri_lines: tuple[str, ...]
    branded: bool
    show_hri: bool


# --------------------------------------------------------------------------- assets
@lru_cache(maxsize=1)
def _wordmark_svg() -> tuple[float, float, list[str]]:
    """(width, height, path data) of the supplied GS1® artwork."""
    with open(WORDMARK_SVG, encoding="utf-8") as fh:
        source = fh.read()
    _, _, width, height = (float(v) for v in re.search(r'viewBox="([^"]+)"', source).group(1).split())
    paths = re.findall(r'<path[^>]*\sd="([^"]+)"', source)
    return width, height, paths


@lru_cache(maxsize=1)
def _font() -> TTFont:
    return TTFont(HRI_FONT)


def _font_metrics() -> tuple[int, int, int]:
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
    matrix: list
    modules: int
    width: float
    height: float
    symbol_x: float
    symbol_y: float
    wordmark: tuple[float, float, float] | None      # ink box: x (left), y (top), height
    hri: list[tuple[str, float, float]]              # text, x (left), baseline
    em: float


def _layout(options: LabelOptions) -> _Layout:
    qr = segno.make(options.uri, error="m")
    matrix = [list(row) for row in qr.matrix]
    modules = len(matrix)
    box = modules + 2 * QUIET_ZONE

    units_per_em, cap_height, descent = _font_metrics()
    em = TEXT_HEIGHT * units_per_em / cap_height
    lines = list(options.hri_lines) if options.show_hri else []
    widths = [_text_width(line, em) for line in lines]
    content_width = max([box] + widths)
    width = content_width + 2 * MARGIN

    y = MARGIN
    wordmark = None
    box_x = MARGIN + (content_width - box) / 2
    if options.branded:
        # "GS1®" sits above the top-left corner of the symbol, left-aligned with it and outside
        # the quiet zone; its cap height equals the text height.
        ink_height = TEXT_HEIGHT * WORDMARK_INK_OVER_CAP
        wordmark = (box_x + QUIET_ZONE, y, ink_height)
        y += ink_height + TEXT_GAP
    box_y = y
    y = box_y + box

    hri = []
    for index, (line, line_width) in enumerate(zip(lines, widths)):
        baseline = y + TEXT_GAP + TEXT_HEIGHT + index * TEXT_HEIGHT * LINE_SPACING
        hri.append((line, MARGIN + (content_width - line_width) / 2, baseline))
    if hri:
        y = hri[-1][2] + descent * em / units_per_em
    height = y + MARGIN

    return _Layout(matrix, modules, width, height, box_x + QUIET_ZONE, box_y + QUIET_ZONE,
                   wordmark, hri, em)


# --------------------------------------------------------------------------- SVG
def _qr_path(layout: _Layout) -> str:
    parts = []
    for row_index, row in enumerate(layout.matrix):
        col = 0
        while col < layout.modules:
            if row[col]:
                start = col
                while col < layout.modules and row[col]:
                    col += 1
                x = layout.symbol_x + start
                y = layout.symbol_y + row_index
                parts.append(f"M{x:g},{y:g}h{col - start}v1h-{col - start}z")
            else:
                col += 1
    return "".join(parts)


def _hri_path(text: str, x: float, baseline: float, em: float) -> str:
    font = _font()
    glyph_set = font.getGlyphSet()
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    scale = em / font["head"].unitsPerEm
    pen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.3f}".rstrip("0").rstrip("."))
    cursor = x
    for ch in text:
        name = cmap[ord(ch)]
        glyph_set[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, baseline)))
        cursor += hmtx[name][0] * scale
    return pen.getCommands()


def render_svg(options: LabelOptions) -> bytes:
    layout = _layout(options)
    w_mm, h_mm = layout.width * TARGET_X_MM, layout.height * TARGET_X_MM
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_mm:.3f}mm" height="{h_mm:.3f}mm" '
        f'viewBox="0 0 {layout.width:.4f} {layout.height:.4f}">',
        f"<title>{_xml(options.uri)}</title>",
        f'<desc>GS1 Digital Link QR code at 100 % target size (X = {TARGET_X_MM} mm), '
        f'quiet zone {QUIET_ZONE}X{", GS1® branding" if options.branded else ""}.</desc>',
        f'<rect width="{layout.width:.4f}" height="{layout.height:.4f}" fill="#fff"/>',
        f'<path fill="#000" shape-rendering="crispEdges" d="{_qr_path(layout)}"/>',
    ]
    if layout.wordmark:
        x, y, ink_height = layout.wordmark
        _, _, paths = _wordmark_svg()
        scale = ink_height / (WORDMARK_INK_BOTTOM - WORDMARK_INK_TOP)
        parts.append(f'<g fill="#000" transform="translate({x - WORDMARK_INK_LEFT * scale:.4f},'
                     f'{y - WORDMARK_INK_TOP * scale:.4f}) scale({scale:.6f})">')
        parts.extend(f'<path d="{d}"/>' for d in paths)
        parts.append("</g>")
    for text, x, baseline in layout.hri:
        parts.append(f'<path fill="#000" aria-label="{_xml(text)}" d="{_hri_path(text, x, baseline, layout.em)}"/>')
    parts.append("</svg>")
    return "\n".join(parts).encode("utf-8")


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --------------------------------------------------------------------------- PNG
def render_png(options: LabelOptions) -> bytes:
    layout = _layout(options)
    px = PNG_PIXELS_PER_MODULE

    def p(value: float) -> int:
        return round(value * px)

    image = Image.new("RGB", (p(layout.width), p(layout.height)), "white")
    draw = ImageDraw.Draw(image)
    for row_index, row in enumerate(layout.matrix):
        for col, dark in enumerate(row):
            if dark:
                x, y = p(layout.symbol_x + col), p(layout.symbol_y + row_index)
                draw.rectangle([x, y, x + px - 1, y + px - 1], fill="black")

    if layout.wordmark:
        x, y, ink_height = layout.wordmark
        artwork = Image.open(WORDMARK_PNG).convert("RGBA")
        artwork = artwork.crop(artwork.getchannel("A").getbbox())   # the PNG artwork is trimmed to its ink
        target_h = p(ink_height)
        target_w = round(artwork.width * target_h / artwork.height)
        artwork = artwork.resize((target_w, target_h), Image.LANCZOS)
        image.paste(artwork, (p(x), p(y)), artwork)

    if layout.hri:
        font = ImageFont.truetype(HRI_FONT, size=max(1, round(layout.em * px)))
        for text, x, baseline in layout.hri:
            draw.text((p(x), p(baseline)), text, fill="black", font=font, anchor="ls")

    dpi = px / TARGET_X_MM * 25.4
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi), optimize=True)
    return buffer.getvalue()
