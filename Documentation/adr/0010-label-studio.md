# ADR 0010 — The label studio: size, PDF, a linear barcode beside the QR code, every format in one zip

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery. **Amended** on 17 October 2026 (section 7, item 9.3) |
| Backlog items | 5.2 — X-dimension choice and PDF export; 5.3 — QR code with EAN-13/UPC-A (and EAN-8/UPC-E); 5.4 — every label format in one zip; 9.3 — Data Matrix, HRI as text, sizes by scanning environment |
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

## 7. Amendment of 17 October 2026 — Data Matrix, HRI as text, sizes by scanning environment (item 9.3)

### 7.1 Context

The staging tests asked for the label to carry a **GS1 DataMatrix** (the element string, with FNC1: what healthcare
and industry scan) and a **Data Matrix carrying the GS1 Digital Link URI**, besides the QR code and the EAN/UPC; for
the SVG's human readable text to be **real text** that artwork tools can edit; and for the module size to follow the
**application** (point of sale, healthcare, direct part marking…) as the GS1 General Specifications' symbol
specification tables set it, rather than a bare percentage.

### 7.2 Decision

1. **The 2D symbol is chosen**: QR code (default, unchanged), Data Matrix with the GS1 Digital Link URI (plain data,
   symbology identifier `]d1`), or GS1 DataMatrix with the element string (FNC1 in first position and after each
   variable-length field, `]d2`). One 2D symbol per label, as GS1 recommends; the EAN/UPC can still stand beside it.
   The GS1 DataMatrix holds every element of the record and the data attributes, whatever the human readable text
   shows. Every format (SVG, PNG, PDF) and the zip carry the symbol chosen; its file names say which
   (`qrcode_…`, `datamatrix_…`, `gs1datamatrix_…`).
2. **The encoder is libzint** (Apache-2.0 Python binding `zint-bindings`, wheels for the image's Python), in GS1 mode
   for the element string; square symbols only (ECC 200). Writing a Data Matrix encoder here was not chosen: libzint
   is maintained, implements GS1 mode (FNC1, the AI checks) and is widely used. The tests read every symbol back with
   an independent decoder (zxing-cpp): the symbology identifier and the data must come out as put in.
3. **Scanning environments** (`label.ENVIRONMENTS`): each gives the X-dimension range (minimum, target, maximum) of
   the 2D symbol and of EAN/UPC, and the 2D symbols it takes. The size stays a percentage, now of the environment's
   target, and only the sizes that keep every symbol on the label within its range are offered (refused otherwise,
   `label.sizeOutOfRange` naming the range and the sizes). The screen grows by one field.

   | Environment | 2D symbols | 2D X (mm): min / target / max | EAN/UPC X (mm) | Sizes |
   |---|---|---|---|---|
   | Retail point of sale (default) | QR, Data Matrix, GS1 DataMatrix | 0.396 / 0.495 / 0.990 | 0.264 / 0.330 / 0.660 | 80–200 % |
   | Healthcare (regulated items) | GS1 DataMatrix, Data Matrix | 0.254 / 0.380 / 0.495 | 0.264 / 0.330 / 0.660 | 80–120 % |
   | Direct part marking | GS1 DataMatrix, Data Matrix | 0.254 / 0.300 / 0.615 | none | 90–200 % |

   **Sources, and what is still to be checked.** The retail values are those of section 2 (the QR Codes powered by GS1
   guidelines; GS1 UK's and GS1 Canada's guides) and of the addendum to symbol specification table 1 for 2D symbols at
   the point of sale (GS1's *2D barcodes at retail point-of-sale* guideline, whose worked examples use 0.495 mm). The
   healthcare and direct part marking rows come from excerpts of the General Specifications and GS1 change
   notifications found while this was written (GS1's own site could not be reached from the session); the published
   tables have changed between releases. **The owner checks the three rows against the current General
   Specifications (section 5.12.3) before production**; a row is one line of `label.ENVIRONMENTS`. *General
   distribution* was left out: no source for its Data Matrix range could be confirmed.
4. **The HRI as text in the SVG** (`hritext=text`), an option: `<text>` elements in Liberation Sans (Arial, Helvetica)
   for the element strings and OCR-B for EAN/UPC digits, editable, but needing those fonts where the artwork is
   printed. **Outlines stay the default**: they look the same everywhere. PNG and PDF always draw outlines.
5. Through the tenant API the same options (`symbol`, `env`, `hritext`); the page reads the environments from
   `/config` (`labelEnvironments`).

### 7.3 Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Encoder | libzint (`zint-bindings`) | a Data Matrix encoder written here; `pylibdmtx` (no GS1 mode, a system library) |
| Several 2D symbols on one label | no: one, chosen | QR and Data Matrix side by side (GS1 advises one 2D symbol a package) |
| Module size | a percentage of the environment's target, limited to its range | free millimetres (easy to leave the range) |
| SVG text | an option, outlines by default | text by default (depends on the printer's fonts) |

### 7.4 Consequences

- The portal's image installs `zint-bindings`; the tests also need `zxing-cpp` (development only).
- A label of the healthcare and direct part marking environments cannot be a QR code.
- The values of three table rows are an open item for the owner (7.2, item 3).

### 7.5 Delivery

`label.py` (`SYMBOLS`, `ENVIRONMENTS`, `sizes_for()`, `check_environment()`, `data_matrix()`, the HRI as text), the
label options in `app.py`, `/config`, the tenant API's description, the label panel (`#opt-symbol`, `#opt-env`,
`#opt-hritext`), tests `portal/test_datamatrix.py` (new) and `portal/test_datamatrix_e2e.py` (new, Chromium), 22
mutations, all caught.
