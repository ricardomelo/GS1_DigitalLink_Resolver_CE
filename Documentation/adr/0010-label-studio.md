# ADR 0010 — The label studio: size, PDF, a linear barcode beside the QR code, every format in one zip

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog items | 5.2 — X-dimension choice and PDF export; 5.3 — QR code with EAN-13/UPC-A (and EAN-8/UPC-E); 5.4 — every label format in one zip |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

The portal draws one label: a QR code at the target X-dimension of the *QR Codes powered by GS1* design guidelines
(0.495 mm), its human readable text, as SVG or PNG. Artwork needs more: another **size** within what the guidelines
allow; a **PDF** that prepress software opens without conversion; during the **transition to 2D** ("Sunrise 2027"),
the familiar **EAN-13 or UPC-A** (or EAN-8, UPC-E) beside the QR code so that every till still scans the product; and
**every format at once** for the designer.

The figures used (GS1 General Specifications and the national organisations' guides): QR code with GS1 Digital Link
on consumer units, X from **0.396 mm to 0.990 mm**, target **0.495 mm**, quiet zone 4X; EAN/UPC, X **0.330 mm at
100 %**, magnification **80 % to 200 %**, bar height **22.85 mm** (69.24X) for EAN-13 and UPC-A/E, **18.23 mm**
(55.24X) for EAN-8, quiet zones EAN-13 11X/7X, UPC-A 9X/9X, UPC-E 9X/7X, EAN-8 7X/7X; human readable digits under
the bars, all of them, legible (OCR-B recommended, about 2.75 mm at 100 %).

## 2. Decision

1. **Size as a magnification of the targets**: 80, 90, 100, 120, 150 or 200 % (`size=`). The QR code's X is
   0.495 mm × size (0.396 to 0.990 mm), the linear symbol's 0.330 mm × size (0.264 to 0.660 mm) — both within their
   ranges at every choice. The human readable text of the QR code never goes below 2 mm, whatever the size.
2. **PDF** (`format=pdf`): one page the size of the label, fully vector (modules and bars as filled rectangles, text as
   glyph outlines, no font embedded), the GS1 Digital Link URI as the document's title. Written by the portal itself:
   no new dependency.
3. **A linear barcode beside the QR code** (`linear=`): `none` (default), `auto` — the symbol the GTIN takes: EAN-8
   for a GTIN-8, UPC-A for a GTIN-12, EAN-13 for a GTIN-13 — or `upce` for a GTIN-12 that zero-suppresses. Only for
   GTINs (01) of consumer units (indicator 0); otherwise 422 `label.linearNotPossible`. The linear symbol carries the
   GTIN only; batches, serials and data attributes stay in the QR code. Placed to the right of the QR code, tops
   aligned, with both quiet zones kept. Human readable digits as the General Specifications place them: EAN-13's first
   digit left of the bars, UPC-A's and UPC-E's number system and check digits smaller and outside, guard bars (and
   UPC-A's first and last characters) extended.
4. **Every format in one zip** (`format=zip`): the label as SVG, PNG and PDF, and a `README.txt` with the URI, the
   options, the X-dimensions and the printed size.
5. The same options in the editor's label block, the portal's `GET /qrcode` and the tenant API's labels.

## 3. Design

`label.LabelOptions` gains `size` (a percentage) and `linear` (`ean13`, `upca`, `upce`, `ean8` with its digits). The
layout is a list of rectangles and text lines in units of the QR module; SVG, PNG (12 pixels per QR module: 8 per
linear module at every size) and PDF are drawn from it. `linear.py` encodes EAN-13, UPC-A, EAN-8 and UPC-E (with the
zero suppression rules of UPC-E, number system 0) and places their digits.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Size | presets as magnifications, one choice for both symbols | a free X in mm (easy to leave the range, two values to keep consistent) |
| PDF | written by the portal (vector, a few hundred lines) | a PDF library (another dependency in the image); converting the SVG with a tool (another program) |
| Linear symbol | EAN/UPC per the GTIN's length, UPC-E on request | GS1-128 or ITF-14 (not for retail point of sale); GS1 DataBar (not the transition's pair) |
| Placement | to the right of the QR code | below (taller labels); two separate files (the pairing is the point) |
| Zip | the three formats of the label as chosen and a text file | every combination of options (large, confusing) |

## 5. Consequences

- The label's options grow by two; their defaults (100 %, no linear symbol) draw exactly what earlier versions drew.
- A linear symbol is offered only where a till can use it.

## 6. Delivery

This record; `portal/label.py`, `portal/linear.py`, the options in the editor and in the APIs, the PDF and the zip;
`test_label.py`, browser checks in `test_portal_e2e.py`; the documentation.
