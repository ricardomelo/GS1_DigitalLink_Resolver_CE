"""
Spreadsheets for bulk import and export of records (CSV and XLSX).

Layout: one row per link. Rows with the same key, identifier and batch/lot form one record, exactly as
the editor would save it:

    Key | Identifier | Batch/lot | Description | Link type | URL | Language | Title | Default | Forward q.s.

"Key" is the AI of the primary identification key (01, 00, 414, …); empty means 01, so spreadsheets
made before other keys existed, with a "GTIN" column and no "Key" column, still import unchanged.

The module is language-neutral: header labels, sheet names and reference texts come from the
browser (portal/static/i18n.js), which sends them with each request. Headers are recognised by their
canonical key (the first column of COLUMNS) or by any label the browser sends, ignoring case, accents,
spaces and punctuation.
"""
import csv
import io
import re
import unicodedata

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import gs1
from gs1 import ValidationError

# canonical key, column width in the XLSX export
COLUMNS = [("key", 8), ("value", 22), ("lot", 14), ("description", 36), ("linkType", 24), ("url", 48),
           ("language", 10), ("title", 30), ("default", 10), ("forward", 12)]
KEYS = [key for key, _ in COLUMNS]
REQUIRED = {"value", "description", "linkType", "url"}
# Headers accepted for a column besides its key and the labels sent by the browser
BUILT_IN_ALIASES = {"value": ["gtin"], "key": ["ai"]}

MAX_ROWS = 5000
MAX_FILE_BYTES = 700 * 1024

_YES = {"1", "true", "yes", "y", "x", "sim", "s", "verdadeiro", "v"}
_NO = {"", "0", "false", "no", "n", "nao", "falso", "f"}


class SheetError(ValidationError):
    """A problem with the file as a whole (format, header, size)."""


def fold(text) -> str:
    """Lower case, no accents, no spaces or punctuation: "Tipo de link" → "tipodelink"."""
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ------------------------------------------------------------------------------------------ reading
def read_table(filename: str, data: bytes) -> list[list[str]]:
    """Returns the rows of the first sheet (XLSX) or of the CSV file, every cell as text."""
    if len(data) > MAX_FILE_BYTES:
        raise SheetError("import.tooBig", max=MAX_FILE_BYTES // 1024)
    name = (filename or "").lower()
    if name.endswith(".xlsx") or data[:2] == b"PK":
        return _read_xlsx(data)
    if name.endswith((".csv", ".txt")) or not name:
        return _read_csv(data)
    raise SheetError("import.format")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))          # a GTIN typed as a number: 7898357410015.0 → "7898357410015"
    return str(value).strip()


def _read_xlsx(data: bytes) -> list[list[str]]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001  (any unreadable file is reported the same way)
        raise SheetError("import.unreadable") from exc
    sheet = workbook.worksheets[0]
    rows = [[_cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
    workbook.close()
    return rows


def _read_csv(data: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1252"):     # Excel in Brazil saves "CSV" as Windows-1252
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError("import.unreadable")
    first = text.split("\n", 1)[0]
    delimiter = max([";", ",", "\t"], key=first.count)   # ";" is Excel's separator in pt-BR
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


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
    folded = fold(value)
    if folded in _YES or folded in {fold(v) for v in extra_yes}:
        return True
    if folded in _NO or folded in {fold(v) for v in extra_no}:
        return default if folded == "" else False
    return None


def parse_rows(rows: list[list[str]], aliases: dict[str, list[str]], yes=(), no=()):
    """
    Groups the data rows into records. Returns (records, errors):
      records: [{"rows": [row numbers], "gtin": raw, "lot": raw, "description": str,
                 "links": [{"row", "linkType", "url", "hreflang", "title", "default", "forward"}]}]
      errors:  [{"row", "code", "params"}]  for rows that cannot be read at all
    Validation of the resulting records is left to the editor's own rules (app.build_document).
    """
    rows = [r for r in rows]
    while rows and not any(rows[0]):
        rows.pop(0)
    if not rows:
        raise SheetError("import.empty")
    columns = map_header(rows[0], aliases)
    data = rows[1:]
    if sum(1 for r in data if any(r)) > MAX_ROWS:
        raise SheetError("import.tooManyRows", max=MAX_ROWS)

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
        # GTINs are grouped without separators and leading zeros (8, 12, 13 and 14 digits are the same key)
        grouped = re.sub(r"[\s.\-]", "", value_raw).lstrip("0") if ai == "01" else value_raw.strip()
        key = (ai, grouped, cell(row, "lot"))
        if key not in records:
            records[key] = {"rows": [], "key": ai, "value": value_raw, "lot": cell(row, "lot"),
                            "description": "", "descriptions": set(), "links": []}
            order.append(key)
        record = records[key]
        record["rows"].append(number)
        description = cell(row, "description")
        if description:
            record["descriptions"].add(description)
            record["description"] = record["description"] or description

        default = yes_no(cell(row, "default"), False, yes, no)
        forward = yes_no(cell(row, "forward"), True, yes, no)
        if default is None or forward is None:
            errors.append({"row": number, "code": "import.yesNo",
                           "params": {"value": cell(row, "default") if default is None else cell(row, "forward")}})
            default = bool(default)
            forward = True if forward is None else forward
        language = [code.strip() for code in re.split(r"[,;/\s]+", cell(row, "language")) if code.strip()]
        link_type = cell(row, "linkType")
        if link_type and ":" not in link_type:
            link_type = "gs1:" + link_type                     # "pip" → "gs1:pip"
        url = cell(row, "url")
        if url and not re.match(r"^[a-z]+://", url, re.I):
            url = "https://" + url                             # as the editor does
        record["links"].append({"row": number, "linkType": link_type, "url": url, "hreflang": language or ["pt"],
                                "title": cell(row, "title"), "default": default, "forward": forward})
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
    """records: [{"key", "value", "lot", "description", "defaultLinkType", "links": [v3 links]}]"""
    rows = []
    for record in records:
        default = record.get("defaultLinkType")
        links = sorted(record.get("links") or [], key=lambda l: l.get("linktype") != default)
        default_marked = False
        for link in links:
            is_default = link.get("linktype") == default and not default_marked
            default_marked = default_marked or is_default
            rows.append([record["key"], record["value"], record.get("lot") or "", record.get("description") or "",
                         link.get("linktype") or "", link.get("href") or "",
                         ", ".join(link.get("hreflang") or []), link.get("title") or "",
                         "yes" if is_default else "", "no" if link.get("fwqs") is False else "yes"])
    return rows


def _localise_flags(rows, yes_word, no_word):
    for row in rows:
        row[8] = yes_word if row[8] == "yes" else ""
        row[9] = yes_word if row[9] == "yes" else no_word
    return rows


def write_csv(rows: list[list[str]], labels: dict) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow([labels.get("headers", {}).get(key, key) for key in KEYS])
    writer.writerows(_localise_flags(rows, labels.get("yes", "yes"), labels.get("no", "no")))
    return ("\ufeff" + out.getvalue()).encode("utf-8")      # BOM: Excel opens UTF-8 correctly


def write_xlsx(rows: list[list[str]], labels: dict, link_types: list[tuple[str, str, str]],
               languages: list[tuple[str, str]], keys: list[tuple[str, str]] = ()) -> bytes:
    headers = labels.get("headers", {})
    sheets = labels.get("sheets", {})
    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="002C6C")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (sheets.get("links") or "Links")[:31]
    sheet.append([headers.get(key, key) for key in KEYS])
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
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(KEYS))}{max(1, sheet.max_row)}"

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

    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def known_link_types() -> list[str]:
    return [code for code, _, _ in gs1.LINK_TYPES]
