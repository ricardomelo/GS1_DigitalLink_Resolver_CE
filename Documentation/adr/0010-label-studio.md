# ADR 0010 — The label studio: size, PDF, a linear barcode beside the QR code, every format in one zip

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery. **Amended** on 17 October 2026 (section 7, item 9.3; section 8, item 9.10) |
| Backlog items | 5.2 — X-dimension choice and PDF export; 5.3 — QR code with EAN-13/UPC-A (and EAN-8/UPC-E); 5.4 — every label format in one zip; 9.3 — Data Matrix, HRI as text, sizes by scanning environment; 9.10 — an EPC for every key that has one |
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
- The values of three table rows are an open item for the owner (7.2, item 3); closed by section 7.6.

### 7.5 Delivery

`label.py` (`SYMBOLS`, `ENVIRONMENTS`, `sizes_for()`, `check_environment()`, `data_matrix()`, the HRI as text), the
label options in `app.py`, `/config`, the tenant API's description, the label panel (`#opt-symbol`, `#opt-env`,
`#opt-hritext`), tests `portal/test_datamatrix.py` (new) and `portal/test_datamatrix_e2e.py` (new, Chromium), 22
mutations, all caught.

### 7.6 Amendment of 21 October 2026 — checked against the General Specifications, release 26.0

**Context.** The owner sent section 5.12 of the GS1 General Specifications, release 26.0 (ratified January 2026): the
scanner functional bands (figure 5-67), the symbology operational environment decision tree (figure 5-68), its summary
(table 5-42) and the thirteen symbol specification tables with their addenda for 2D symbols (5.12.3.1 to 5.12.3.13).

**What the check found.**

- *Retail point of sale* matches table 1 and its addendum 2 (tables 5-44 and 5-46): 2D 0.396 / 0.495 / 0.990 mm,
  EAN/UPC 0.264 / 0.330 / 0.660 mm.
- *Direct part marking* matches table 7 (5-53): 0.254 / 0.300 / 0.615 mm. The table names the GS1 QR Code beside the
  GS1 DataMatrix, so the QR code is now offered there too.
- *Healthcare* was wrong: 0.254 / 0.380 / **0.495** mm are table 11's (GSRN). The healthcare tables are three: table 6
  (non-retail, not in general distribution: GS1 DataMatrix 0.254 / 0.380 / **0.990**, EAN/UPC from 0.170), table 10
  (retail pharmacy, not in general distribution: 0.396 / 0.495 / 0.990) and table 8 (pharmacy and general
  distribution: 0.750 / 0.750 / 1.520, EAN/UPC 0.495 / 0.660 / 0.660). One environment could not stand for all three.

**Decision.**

1. **One environment per table of the decision tree** that a label of the portal can follow (`label.ENVIRONMENTS`,
   each with its `table`): trade items — `retail` (1), `retail-gd` (3), `distribution` (2), `pharmacy` (10),
   `pharmacy-gd` (8), `healthcare` (6, the same name, now table 6's values), `other` (4); other keys — `logistics`
   (5, SSCC), `assets` (9, GDTI, GRAI, GIAI, GLN), `gsrn` (11); and `dpm` (7) for every key.
2. **By key** (figure 5-68, questions 1 and 4): `label.environments_for(ai)` gives a key its own tables or, for every
   key without one, the trade items'; direct part marking for all. The first is the default when a label is asked
   without `env` (an SSCC now gets table 5 by default, not retail); an environment of other keys is refused
   (`label.environmentNotForKey`, naming the key's); the page offers only the key's environments.
3. **Symbols**: where a table names the GS1 DataMatrix, both Data Matrix symbols take its range (tables 1 and 3 give
   the Data Matrix with the URI the same range as the GS1 DataMatrix); the QR code with the URI only where a table names
   a QR Code — so not in tables 6, 8 and 10.
4. **Not offered**: table 12 (tobacco, EU Regulation 2018/574: grade 3.5 and the GS1 DotCode) and table 13 (long
   distance: no target, a quality aperture of 80 % of the X chosen). Neither fits a size given as a percentage of a
   target; both stay in this section for whoever needs them. GS1-128 and GS1 DataBar, named by several tables, are not
   drawn by the portal; table 5's and table 9's ranges for them are not used.

| Environment | Table | 2D symbols | 2D X (mm): min / target / max | EAN/UPC X (mm) | Keys | Sizes (with EAN/UPC) |
|---|---|---|---|---|---|---|
| `retail` | 1 + add. 2 | QR, DM, GS1 DM | 0.396 / 0.495 / 0.990 | 0.264 / 0.330 / 0.660 | trade items | 80–200 % (80–200 %) |
| `retail-gd` | 3 + add. 1 | QR, DM, GS1 DM | 0.743 / 0.990 / 0.990 | 0.495 / 0.660 / 0.660 | trade items | 80–100 % (80–100 %) |
| `distribution` | 2 | QR, DM, GS1 DM | 0.743 / 0.743 / 1.50 | 0.495 / 0.660 / 0.660 | trade items | 100–200 % (100 %) |
| `pharmacy` | 10 | DM, GS1 DM | 0.396 / 0.495 / 0.990 | 0.264 / 0.330 / 0.660 | trade items | 80–200 % (80–200 %) |
| `pharmacy-gd` | 8 | DM, GS1 DM | 0.750 / 0.750 / 1.520 | 0.495 / 0.660 / 0.660 | trade items | 100–200 % (100 %) |
| `healthcare` | 6 | DM, GS1 DM | 0.254 / 0.380 / 0.990 | 0.170 / 0.330 / 0.660 | trade items | 80–200 % (80–200 %) |
| `other` | 4 | QR, DM, GS1 DM | 0.375 / 0.495 / 0.990 | 0.264 / 0.330 / 0.660 | trade items | 80–200 % (80–200 %) |
| `logistics` | 5 | QR, DM, GS1 DM | 0.743 / 0.743 / 1.50 | — | SSCC | 100–200 % |
| `assets` | 9 | QR, DM, GS1 DM | 0.375 / 0.375 / 0.743 | — | GDTI, GRAI, GIAI, GLN | 100–150 % |
| `gsrn` | 11 | QR, DM, GS1 DM | 0.254 / 0.380 / 0.495 | — | GSRN | 80–120 % |
| `dpm` | 7 | QR, DM, GS1 DM | 0.254 / 0.300 / 0.615 | — | any | 90–200 % |

*Trade items*: every key except those with a table of their own (SSCC, GDTI, GRAI, GIAI, GLN, GSRN). In table 3 the
EAN/UPC's maximum equals its target, so the sizes stop at 100 %.

**Consequences.** A label of the `healthcare` environment keeps its target (0.380 mm) and gains sizes up to 200 %. A
label of an SSCC, GDTI, GRAI, GIAI, GLN or GSRN asked without `env` is drawn at its own table's target (an SSCC's QR
code at 0.743 mm instead of 0.495); asked with `env=retail` it is refused. The General Specifications are updated every
year: a new release is checked against this table, one line of `label.ENVIRONMENTS` per row. The PDF is GS1's and is
not kept in the repository.

## 8. Amendment of 17 October 2026 — an EPC for every key that has one (item 9.10)

### 8.1 Context

The label studio's *RFID and NFC (EPC)* block encoded one scheme, the SGTIN of a GTIN with a serial number. The owner
asked for the EPC of every key the EPC Tag Data Standard (TDS) encodes, once the record holds what it needs — a GLN
and its extension, an SSCC, a GRAI, a GIAI… The resolver already decodes every scheme, from the machine-readable EPC
Tag Data Translation (TDT) artefacts it carries (`web_server/src/tdt`, item 1.6), and item 9.9 gave the portal the
company prefix's length that every scheme's partition needs.

### 8.2 Decision

1. **Every key with a scheme defined before TDS 2.0**, in the order tried — the 96-bit scheme for numeric values
   without leading zeros, then the longer one that takes characters:

   | Key | Schemes | What the record needs first |
   |---|---|---|
   | GTIN (01) | SGTIN-96, SGTIN-198 | a serial number (21) |
   | SSCC (00) | SSCC-96 | — |
   | GLN (414) | SGLN-96, SGLN-195 | — (without an extension (254), the extension 0, as TDS 6.3.3 says) |
   | GRAI (8003) | GRAI-96, GRAI-170 | its serial component (after the 14 digits) |
   | GIAI (8004) | GIAI-96, GIAI-202 | — |
   | GSRN (8018), GSRNP (8017) | GSRN-96, GSRNP-96 | — |
   | GDTI (253) | GDTI-96, GDTI-174 | its serial component (after the 13 digits) |
   | GCN (255) | SGCN-96 | its serial component (after the 13 digits) |
   | CPID (8010) | CPI-96, CPI-var | its serial (8011) |
   | ITIP (8006) | ITIP-110, ITIP-212 | a serial number (21) |

   GDTI-113 (deprecated by TDS 2.0) and the keys without a scheme (GINC, GSIN, party GLN, GMN…) have no EPC; the block
   is not offered for them, nor before the record holds what it needs.
2. **Driven by the TDT artefacts**, not by tables written here: the record's GS1 Digital Link path is matched by the
   scheme's GS1_DIGITAL_LINK level for the company prefix's length, its EXTRACT rules give the fields, and the BINARY,
   TAG_ENCODING and PURE_IDENTITY levels write them out — the inverse of what the resolver's decoder does. The portal's
   image is built from `portal/` alone, so it carries `portal/epc_schemes.json`, the four levels of the 19 schemes,
   generated from the resolver's artefacts by `portal/tools/gen_epc_schemes.py` and checked against them by the tests.
   Two rules the artefacts do not spell out are applied: a number without a fixed width (a 96-bit scheme's serial) is
   written without leading zeros, so "012" goes to the longer scheme; and every URI written must match the artefact's
   own pattern for it.
3. **The TDS 2.0 "+" schemes** (SGTIN+, SGLN+…) are not offered in this delivery: they need no partition but have no
   tag URI or pure identity URI, readers and middleware support them less, and their encoding (TDS 14.5's methods, the
   +AIDC data) is a different engine. The resolver keeps decoding them. They can be added beside the classic schemes
   later, as an option of the block.
4. **The filter**: the named values of TDS Table 10-2 for trade items (GTIN, ITIP; 1, point of sale, by default); for
   the other keys 0 (*all others*) by default and the other values as numbers.
5. **The partition** as item 9.9 decided: the person's choice, then GS1's GCP length table, then the organisation's
   prefixes. The record list's search by EPC already reads any scheme through the resolver.
6. **A defect of the resolver's decoder** found by the round trip: with a 12-digit company prefix the location, asset
   type, document type or coupon reference has no digit (TDT `length` 0, one or four bits 0); the decoder wrote it as
   "0", giving a GLN, GRAI, GDTI or GCN one digit too long. It now writes nothing. The independent library the tests
   compare with (`epc-tds`) has the same defect, which is why the comparison had passed; those cases are now checked
   against the standard instead.

### 8.3 Design

- `portal/epc.py`: `KEY_SCHEMES`, `MINIMUM`, `missing()`, `path_of()`, `encode(ai, value, qualifiers, prefix_length,
  filter)` → `Epc` (`scheme`, `filter`, `bits`, `hex`, `base64`, `tag_uri`, `pure_identity`); `sgtin()` kept for the
  GTIN; `prefix_length_of()` for any key's company part. Errors: `epc.unsupported`, `epc.needsQualifier`
  (`qualifier`), `epc.needsSerial` (`serialAfter`), `epc.notEncodable`, `epc.prefixLength`, `epc.filterInvalid`.
- `GET /portal/api/epc` takes any key; `GET /config` gives `epc` (each key's minimum) for the page.
- `web_server/src/epc_binary.py`: a field of `length` 0 decodes to the empty string.

### 8.4 Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Encoder | from the TDT artefacts (one engine, the resolver's own definitions, checked by decoding) | a hand-written table per scheme (eleven tables to keep right by hand) |
| The artefacts in the portal | a generated copy of the four levels used, checked | the portal reading the resolver's folder (another image; the build context is `portal/`) |
| TDS 2.0 "+" schemes | not now, decided here | offered beside the classic ones (no tag URI; less support in readers; another engine) |
| A GLN without extension | SGLN with the extension 0 (TDS) | no EPC until an extension is typed |

### 8.5 Consequences

- `portal/epc_schemes.json` (about 550 KB) must be generated again when the resolver's artefacts change; a test fails
  until it is.
- An SGCN's serial keeps its leading zeros, as the TDT artefact's rule says (`epc-tds` drops them).

### 8.6 Delivery

This amendment; `portal/epc.py`, `portal/epc_schemes.json`, `portal/tools/gen_epc_schemes.py`, the route and the block;
the decoder's fix; `test_epc.py` (every key and partition decoded back, `epc-tds` for eight scheme families, the API and
the record search by each new EPC), `test_epc_binary.py` (12-digit company prefixes) and `test_domains_e2e.py` (the
block for a GLN, an SSCC and a GRAI in Chromium), mutation-checked; texts in the eleven languages; the documentation.
