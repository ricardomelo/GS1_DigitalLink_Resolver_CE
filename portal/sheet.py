"""
Spreadsheets for bulk import and export of records (CSV and XLSX).

Layout: one row per link. Rows with the same key, identifier and batch/lot form one record, exactly as
the editor would save it:

    Key | Identifier | Qualifiers | Description | Link type | URL | Language | Title | Default | Forward q.s.

"Key" is the AI of the primary identification key (01, 00, 414, …); empty means 01. "Qualifiers" holds
the key qualifiers as element strings, "(22)V1(10)L1(21)S1", or as a path, "/10/L1". Spreadsheets
made before, with a "GTIN" and a "Batch/lot" column, still import unchanged.

The module is language-neutral: header labels, sheet names and reference texts come from the
browser (portal/static/i18n.js), which sends them with each request. Headers are recognised by their
canonical key (the first column of COLUMNS) or by any label the browser sends, ignoring case, accents,
spaces and punctuation.
"""
import csv
import io
import re
import unicodedata
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import gs1
from gs1 import ValidationError

# canonical key, column width in the XLSX export
COLUMNS = [("key", 8), ("value", 22), ("qualifiers", 24), ("description", 36), ("linkType", 24), ("url", 48),
           ("language", 10), ("title", 30), ("default", 10)]
EXPORTED = [key for key, _ in COLUMNS]
# Accepted on import (older spreadsheets), not exported: "lot", and "forward", ignored since the query string
# is always passed on (GS1-Conformant Resolver 1.2.1, section 2.12)
KEYS = EXPORTED + ["lot", "forward"]
REQUIRED = {"value", "description", "linkType", "url"}
# Headers accepted for a column besides its key and the labels sent by the browser
BUILT_IN_ALIASES = {"value": ["gtin"], "key": ["ai"]}

# Import limits per accepted format. The file travels base64-encoded in a JSON request, and both the
# portal (MAX_CONTENT_LENGTH) and the proxy (client_max_body_size) accept 1 MB per request, so no file
# may exceed about 700 KB whatever its format. An XLSX file is compressed: 5 000 rows usually take
# 150-300 KB, so its row limit is reached first. A CSV file is plain text: long URLs and descriptions
# can reach 700 KB before 5 000 rows. The limits are shown in the import dialog (GET /portal/api/config)
# and in the README; change them here only.
FORMATS = {
    # format: (file name extensions, maximum data rows, maximum size in KB)
    "xlsx": ((".xlsx",), 5000, 700),
    "csv": ((".csv", ".txt"), 5000, 700),
}
MAX_ROWS = max(rows for _, rows, _ in FORMATS.values())
MAX_FILE_BYTES = max(kb for _, _, kb in FORMATS.values()) * 1024
# Limits on what a file may hold once read (ADR 0032). The size limit above bounds the file, not its content: an
# XLSX file is a ZIP archive, and a few kilobytes can unpack into gigabytes or name a cell a million rows down or
# 16 384 columns across. Reading stops at the row limit; only the first MAX_COLUMNS columns of each row are read
# (the layout has ten; further columns are ignored); an XLSX file whose parts unpack into more than
# MAX_UNPACKED_MB is refused before it is opened (an honest file at the size limit unpacks into a few megabytes).
MAX_COLUMNS = 64
MAX_UNPACKED_MB = 32
XLSX_LAST_ROW = 1_048_576

# Spreadsheet programs run a cell that starts with one of these as a formula when they open a CSV file
# ("CSV injection"): a description such as =HYPERLINK(…) would become a live link or worse. Exported CSV
# cells that start with one of them get a leading apostrophe, which Excel and LibreOffice take as "text"
# and do not show; imports remove it again. XLSX cells are written as text and need no apostrophe.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

_YES = {"1", "true", "yes", "y", "x", "sim", "s", "verdadeiro", "v"}
_NO = {"", "0", "false", "no", "n", "nao", "falso", "f"}


class SheetError(ValidationError):
    """A problem with the file as a whole (format, header, size)."""


class Table(list):
    """The rows of a spreadsheet, every cell as text, and the format they were read from."""

    def __init__(self, rows, file_format: str | None = None):
        super().__init__(rows)
        self.format = file_format


def limits() -> list[dict]:
    """The import limits of every accepted format, as sent to the browser."""
    return [{"format": name, "extensions": list(extensions), "maxRows": rows, "maxKB": kb}
            for name, (extensions, rows, kb) in FORMATS.items()]


def detect_format(filename: str, data: bytes) -> str:
    """"xlsx" or "csv" from the file's content and name; SheetError for anything else."""
    name = (filename or "").lower()
    if data[:2] == b"PK" or name.endswith(FORMATS["xlsx"][0]):
        return "xlsx"
    if name.endswith(FORMATS["csv"][0]) or not name:
        return "csv"
    raise SheetError("import.format")


def protect(value) -> str:
    """A CSV cell that spreadsheet programs will not run as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def xlsx_text(value):
    """A value an XLSX cell can hold: the control characters the format forbids (U+0000 to U+001F except tab and line
    breaks) removed from texts, in nested labels too; openpyxl refuses the whole workbook otherwise (ADR 0040)."""
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    if isinstance(value, dict):
        return {key: xlsx_text(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [xlsx_text(item) for item in value]
    return value


def unprotect(text: str) -> str:
    """Undoes protect() on import."""
    return text[1:] if text.startswith("'") and text[1:].startswith(FORMULA_START) else text


def fold(text) -> str:
    """Lower case, no accents, no spaces or punctuation: "Tipo de link" → "tipodelink"."""
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ------------------------------------------------------------------------------------------ reading
def read_table(filename: str, data: bytes) -> Table:
    """Returns the rows of the first sheet (XLSX) or of the CSV file, every cell as text, at most MAX_COLUMNS
    cells a row. Stops reading, with import.tooManyRows, at the first data row past the format's row limit."""
    file_format = detect_format(filename, data)
    _, max_rows, max_kb = FORMATS[file_format]
    if len(data) > max_kb * 1024:
        raise SheetError("import.tooBig", max=max_kb, format=file_format)
    if file_format == "xlsx":
        _check_unpacked(data)
        return Table(_take(_read_xlsx(data), max_rows, file_format), file_format)
    return Table(_take(_read_csv(data), max_rows, file_format), file_format)


_BLANK: list = []      # every blank row is this one list: blank rows cost a reference each, not a row of cells


def _take(rows, max_rows: int, file_format: str) -> list[list[str]]:
    """The rows of an iterator up to the header and max_rows data rows (non-blank rows after the first non-blank
    one); import.tooManyRows as soon as one more data row is read, before the rest of the file is."""
    taken, filled = [], 0
    for row in rows:
        if not any(row):
            taken.append(_BLANK)
            continue
        filled += 1
        if filled > max_rows + 1:                  # the header and max_rows data rows
            raise SheetError("import.tooManyRows", max=max_rows, format=file_format)
        taken.append(row)
    while taken and taken[-1] is _BLANK:          # blank rows at the end carry nothing
        taken.pop()
    return taken


def _cell_text(value) -> str:
    """Text of a spreadsheet cell: numbers typed as numbers lose the ".0", formula protection removed."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))          # a GTIN typed as a number: 7898357410015.0 → "7898357410015"
    return unprotect(str(value).strip())


def _check_unpacked(data: bytes) -> None:
    """Refuses an XLSX file whose parts unpack into more than MAX_UNPACKED_MB, measured by unpacking them (the
    sizes a ZIP archive declares can be false), and one whose parts use another compression than Excel's."""
    budget = MAX_UNPACKED_MB * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise SheetError("import.unreadable")
                with archive.open(info) as part:
                    while chunk := part.read(1024 * 1024):
                        budget -= len(chunk)
                        if budget < 0:
                            raise SheetError("import.unpackedTooBig", max=MAX_UNPACKED_MB)
    except SheetError:
        raise
    except Exception as exc:  # noqa: BLE001  (any unreadable archive is reported the same way)
        raise SheetError("import.unreadable") from exc


def _read_xlsx(data: bytes):
    """Rows of the first sheet of an Excel workbook, as text, one at a time (the first MAX_COLUMNS cells)."""
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001  (any unreadable file is reported the same way)
        raise SheetError("import.unreadable") from exc
    try:
        # Excel's last row bounds the blank rows a file can make the reader produce by naming a row far down
        for row in workbook.worksheets[0].iter_rows(max_row=XLSX_LAST_ROW, max_col=MAX_COLUMNS, values_only=True):
            yield _BLANK if row.count(None) == len(row) else [_cell_text(v) for v in row]
    except SheetError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SheetError("import.unreadable") from exc
    finally:
        workbook.close()


def _read_csv(data: bytes):
    """Rows of a CSV or text file, one at a time (the first MAX_COLUMNS cells): encoding (UTF-16, UTF-8,
    Windows-1252) and separator detected."""
    # UTF-16 with its byte order mark is Excel's "Unicode text" (.txt, tab-separated); UTF-8 with or
    # without BOM is "CSV UTF-8"; Excel in Brazil saves plain "CSV" as Windows-1252.
    encodings = ("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError("import.unreadable")
    first = text.split("\n", 1)[0]
    delimiter = max([";", ",", "\t"], key=first.count)   # ";" is Excel's separator in pt-BR
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            yield [unprotect(cell.strip()) for cell in row[:MAX_COLUMNS]]
    except csv.Error as exc:           # e.g. a cell above the csv module's 128 KB field limit
        raise SheetError("import.unreadable") from exc


def map_header(header: list[str], aliases: dict[str, list[str]]) -> dict[str, int]:
    """Column index of each known key, recognising the canonical key or any alias."""
    names = {key: {fold(key)} | {fold(a) for a in aliases.get(key, []) + BUILT_IN_ALIASES.get(key, [])}
             for key in KEYS}
    columns = {}
    for index, cell in enumerate(header):
        folded = fold(cell)
        for key in KEYS:
            if folded and folded in names[key] and key not in columns:
                columns[key] = index
    missing = [key for key in KEYS if key in REQUIRED and key not in columns]
    if missing:
        raise SheetError("import.missingColumns", columns=missing)
    return columns


def yes_no(value: str, default: bool, extra_yes=(), extra_no=()) -> bool | None:
    """True, False, the default for an empty cell, or None when the word is not a yes or a no."""
    folded = fold(value)
    if folded in _YES or folded in {fold(v) for v in extra_yes}:
        return True
    if folded in _NO or folded in {fold(v) for v in extra_no}:
        return default if folded == "" else False
    return None


def parse_rows(rows: list[list[str]], aliases: dict[str, list[str]], yes=(), no=()):
    """
    The row limit is the one of the format the rows were read from (read_table), MAX_ROWS otherwise.

    Groups the data rows into records. Returns (records, errors):
      records: [{"rows": [row numbers], "gtin": raw, "lot": raw, "description": str,
                 "links": [{"row", "linkType", "url", "hreflang", "title", "default"}]}]
      errors:  [{"row", "code", "params"}]  for rows that cannot be read at all
    Validation of the resulting records is left to the editor's own rules (app.build_document).
    """
    file_format = getattr(rows, "format", None)
    max_rows = FORMATS[file_format][1] if file_format in FORMATS else MAX_ROWS
    rows = [r for r in rows]
    while rows and not any(rows[0]):
        rows.pop(0)
    if not rows:
        raise SheetError("import.empty")
    columns = map_header(rows[0], aliases)
    data = rows[1:]
    if sum(1 for r in data if any(r)) > max_rows:
        raise SheetError("import.tooManyRows", max=max_rows, format=file_format or "")

    def cell(row, key):
        index = columns.get(key)
        return row[index].strip() if index is not None and index < len(row) and row[index] else ""

    records, order, errors = {}, [], []
    for number, row in enumerate(data, start=2):
        if not any(c.strip() for c in row):
            continue
        value_raw = cell(row, "value")
        ai = re.sub(r"[()\s]", "", cell(row, "key")) or "01"          # "(01)" or " 01 " → "01"
        if re.fullmatch(r"\d+([.,]\d+)?[eE]\+?\d+", value_raw):
            errors.append({"row": number, "code": "import.gtinScientific", "params": {"value": value_raw}})
            continue
        try:
            qualifiers = gs1.parse_qualifier_text(cell(row, "qualifiers"))
        except ValidationError as exc:
            errors.append({"row": number, "code": exc.code, "params": {"value": cell(row, "qualifiers")}})
            continue
        if cell(row, "lot"):
            qualifiers.append(("10", cell(row, "lot")))
        qualifiers = sorted(qualifiers, key=lambda kv: gs1.QUALIFIER_ORDER.index(kv[0])
                            if kv[0] in gs1.QUALIFIER_ORDER else 99)
        # GTINs are grouped without separators and leading zeros (8, 12, 13 and 14 digits are the same key)
        clean = gs1.without_invisible(value_raw)
        grouped = re.sub(r"[\s.\-]", "", clean).lstrip("0") if ai == "01" else re.sub(r"\s", "", clean)
        key = (ai, grouped, tuple(qualifiers))
        if key not in records:
            records[key] = {"rows": [], "key": ai, "value": value_raw, "qualifiers": qualifiers,
                            "description": "", "descriptions": set(), "links": []}
            order.append(key)
        record = records[key]
        record["rows"].append(number)
        description = cell(row, "description")
        if description:
            record["descriptions"].add(description)
            record["description"] = record["description"] or description

        default = yes_no(cell(row, "default"), False, yes, no)
        if default is None:
            errors.append({"row": number, "code": "import.yesNo", "params": {"value": cell(row, "default")}})
            default = False
        language = [code.strip() for code in re.split(r"[,;/\s]+", cell(row, "language")) if code.strip()]
        link_type = cell(row, "linkType")
        if link_type and ":" not in link_type:
            link_type = "gs1:" + link_type                     # "pip" → "gs1:pip"
        url = cell(row, "url")
        if url and not re.match(r"^[a-z]+://", url, re.I):
            url = "https://" + url                             # as the editor does
        record["links"].append({"row": number, "linkType": link_type, "url": url, "hreflang": language or ["pt"],
                                "title": cell(row, "title"), "default": default})
    result = []
    for key in order:
        record = records.pop(key)
        if len(record.pop("descriptions")) > 1:
            errors.append({"row": record["rows"][0], "code": "import.descriptionConflict",
                           "params": {"rows": ", ".join(map(str, record["rows"]))}})
        result.append(record)
    return result, errors


# ------------------------------------------------------------------------------------------ writing
def export_rows(records: list[dict]) -> list[list[str]]:
    """records: [{"key", "value", "qualifiers": [[AI, value]], "description", "defaultLinkType", "links"}]"""
    rows = []
    for record in records:
        default = record.get("defaultLinkType")
        links = sorted(record.get("links") or [], key=lambda l: l.get("linktype") != default)
        default_marked = False
        for link in links:
            is_default = link.get("linktype") == default and not default_marked
            default_marked = default_marked or is_default
            qualifiers = "".join(f"({q}){v}" for q, v in record.get("qualifiers") or [])
            rows.append([record["key"], record["value"], qualifiers, record.get("description") or "",
                         link.get("linktype") or "", link.get("href") or "",
                         ", ".join(link.get("hreflang") or []), link.get("title") or "",
                         "yes" if is_default else ""])
    return rows


def _localise_flags(rows, yes_word, no_word):
    """The Default column in the user's language (yes word)."""
    for row in rows:
        row[8] = yes_word if row[8] == "yes" else ""
    return rows


def write_csv(rows: list[list[str]], labels: dict) -> bytes:
    """Export as CSV for Excel: UTF-8 with BOM, ';' separator, cells protected against formulas."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow([protect(labels.get("headers", {}).get(key, key)) for key in EXPORTED])
    writer.writerows([[protect(cell) for cell in row]
                      for row in _localise_flags(rows, labels.get("yes", "yes"), labels.get("no", "no"))])
    return ("\ufeff" + out.getvalue()).encode("utf-8")      # BOM: Excel opens UTF-8 correctly


def write_xlsx(rows: list[list[str]], labels: dict, link_types: list[tuple[str, str, str]],
               languages: list[tuple[str, str]], keys: list[tuple[str, str]] = ()) -> bytes:
    """Export as XLSX: the links sheet plus reference sheets of link types, keys and languages."""
    labels, rows, link_types, languages, keys = (xlsx_text(labels), xlsx_text(rows), xlsx_text(list(link_types)),
                                                 xlsx_text(list(languages)), xlsx_text(list(keys)))
    headers = labels.get("headers", {})
    sheets = labels.get("sheets", {})
    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="002C6C")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (sheets.get("links") or "Links")[:31]
    sheet.append([headers.get(key, key) for key in EXPORTED])
    for row in _localise_flags(rows, labels.get("yes", "yes"), labels.get("no", "no")):
        sheet.append(row)
    for index, (_, width) in enumerate(COLUMNS, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = width
        head = sheet[f"{letter}1"]
        head.font, head.fill, head.alignment = bold, fill, Alignment(vertical="center")
    for letter in ("A", "B", "C"):                           # key, identifier and lot as text:
        for cell in sheet[letter][1:]:                       # Excel keeps the leading zeros
            cell.number_format = "@"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(EXPORTED))}{max(1, sheet.max_row)}"

    reference = workbook.create_sheet((sheets.get("linkTypes") or "Link types")[:31])
    reference.append([labels.get("codeHeader", "Code"), labels.get("nameHeader", "Name"),
                      labels.get("descriptionHeader", "Description")])
    for row in link_types:
        reference.append(list(row))
    for letter, width in (("A", 28), ("B", 34), ("C", 80)):
        reference.column_dimensions[letter].width = width
        reference[f"{letter}1"].font, reference[f"{letter}1"].fill = bold, fill

    if keys:
        key_sheet = workbook.create_sheet((sheets.get("keys") or "Keys")[:31])
        key_sheet.append([labels.get("codeHeader", "Code"), labels.get("nameHeader", "Name")])
        for row in keys:
            key_sheet.append(list(row))
        for letter, width in (("A", 10), ("B", 60)):
            key_sheet.column_dimensions[letter].width = width
            key_sheet[f"{letter}1"].font, key_sheet[f"{letter}1"].fill = bold, fill
        for cell in key_sheet["A"][1:]:
            cell.number_format = "@"

    codes = workbook.create_sheet((sheets.get("languages") or "Languages")[:31])
    codes.append([labels.get("codeHeader", "Code"), labels.get("nameHeader", "Name")])
    for row in languages:
        codes.append(list(row))
    if labels.get("languagesNote"):
        codes.append([])
        codes.append([labels["languagesNote"]])
    for letter, width in (("A", 10), ("B", 30)):
        codes.column_dimensions[letter].width = width
        codes[f"{letter}1"].font, codes[f"{letter}1"].fill = bold, fill

    for worksheet in workbook.worksheets:                # every text as text, never as a formula
        for line in worksheet.iter_rows():
            for cell in line:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def known_link_types() -> list[str]:
    """Codes of the link types the portal offers (gs1:pip, …)."""
    return [code for code, _, _ in gs1.LINK_TYPES]
