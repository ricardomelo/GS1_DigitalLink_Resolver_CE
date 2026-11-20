"""
Unit tests for portal/sheet.py (spreadsheet import/export), without a browser or a resolver.

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_sheet.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal")))

from openpyxl import load_workbook  # noqa: E402

import sheet  # noqa: E402
from gs1 import ValidationError  # noqa: E402

failures = []
PT = {"key": ["Chave (AI)", "Key (AI)"], "value": ["Identificador", "Identifier"], "lot": ["Lote", "Batch/lot"], "description": ["Descrição", "Description"],
      "linkType": ["Tipo de link", "Link type"], "url": ["URL"], "language": ["Idioma", "Language"],
      "title": ["Título", "Title"], "default": ["Principal", "Default"],
      "forward": ["Repassar parâmetros", "Forward query string"]}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def error_code(callable_):
    try:
        callable_()
    except ValidationError as exc:
        return exc.code
    return None


# Brazilian Excel: ";" separator, Windows-1252, Portuguese headers without the optional columns' order
csv_pt = ("Descrição;GTIN;Lote;Tipo de link;URL;Idioma;Principal;Repassar parâmetros\r\n"
          "Café torrado;7898357410015;;gs1:pip;www.exemplo.com.br/cafe;pt;sim;sim\r\n"
          "Café torrado;7898357410015;;instructions;https://exemplo.com.br/manual.pdf;pt, en;;não\r\n"
          ";;;;;;;\r\n"
          "Café torrado;7898357410015;L1;gs1:pip;https://exemplo.com.br/l1;pt;;\r\n").encode("cp1252")
rows = sheet.read_table("links.csv", csv_pt)
records, errors = sheet.parse_rows(rows, PT)
check("CSV cp1252 with ';' and Portuguese headers", len(records) == 2 and not errors, (records, errors))
product = records[0]
check("rows of the same GTIN and lot form one record", product["rows"] == [2, 3] and records[1]["rows"] == [5])
check("scheme added to bare addresses", product["links"][0]["url"] == "https://www.exemplo.com.br/cafe")
check("'gs1:' added to bare link types", product["links"][1]["linkType"] == "gs1:instructions")
check("several languages in one cell", product["links"][1]["hreflang"] == ["pt", "en"])
check("sim/não and empty defaults; the old forward column is read but ignored",
      product["links"][0]["default"] and not product["links"][1]["default"]
      and all("forward" not in link for r in records for link in r["links"]))

check("canonical keys accepted without aliases", error_code(lambda: sheet.parse_rows(sheet.read_table("a.csv", b"gtin,description,linkType,url\n1,a,b,c\n"), {})) is None)
rows = sheet.read_table("x.csv", "GTIN;Descrição;Tipo de link;URL\r\n7,89836E+12;Café;gs1:pip;https://x.org\r\n".encode())
_, errors = sheet.parse_rows(rows, PT)
check("GTIN in scientific notation reported", errors and errors[0]["code"] == "import.gtinScientific", errors)
rows = sheet.read_table("x.csv", "GTIN;Descrição;Tipo de link;URL;Principal\r\n7898357410015;A;gs1:pip;https://x.org;talvez\r\n".encode())
_, errors = sheet.parse_rows(rows, PT)
check("unknown yes/no value reported", errors and errors[0]["code"] == "import.yesNo", errors)
rows = sheet.read_table("x.csv", "GTIN;Descrição;Tipo de link;URL\r\n7898357410015;A;gs1:pip;https://x.org\r\n0007898357410015;B;gs1:pip;https://y.org\r\n".encode())
records, errors = sheet.parse_rows(rows, PT)
check("leading zeros do not split a record; different descriptions reported",
      len(records) == 1 and errors and errors[0]["code"] == "import.descriptionConflict", (records, errors))
check("missing required columns", error_code(lambda: sheet.parse_rows([["GTIN", "URL"]], PT)) == "import.missingColumns")
check("empty file", error_code(lambda: sheet.parse_rows([[""], []], PT)) == "import.empty")
check("file too big", error_code(lambda: sheet.read_table("a.csv", b"x" * (sheet.MAX_FILE_BYTES + 1))) == "import.tooBig")
check("unknown format", error_code(lambda: sheet.read_table("a.pdf", b"%PDF")) == "import.format")
check("CSV cell above the csv module's field limit reported, not a crash",
      error_code(lambda: sheet.read_table("a.csv", b"a;b\r\n" + b"x" * 200_000)) == "import.unreadable")
check("broken XLSX", error_code(lambda: sheet.read_table("a.xlsx", b"PK\x03\x04broken")) == "import.unreadable")

# Limits per format (sheet.FORMATS), as sent to the browser
limits = {l["format"]: l for l in sheet.limits()}
check("limits listed for every accepted format", set(limits) == {"xlsx", "csv"}
      and limits["csv"]["extensions"] == [".csv", ".txt"] and all(l["maxRows"] > 0 and l["maxKB"] > 0 for l in limits.values()),
      limits)
check("formats detected by name and content", [sheet.detect_format(n, d) for n, d in
      [("a.xlsx", b""), ("a.bin", b"PK\x03\x04"), ("a.CSV", b"x"), ("a.txt", b"x"), ("", b"x")]] == ["xlsx", "xlsx", "csv", "csv", "csv"])


def exc_of(callable_):
    try:
        callable_()
    except ValidationError as exc:
        return exc
    return None


for fmt, name in (("csv", "a.csv"), ("xlsx", "a.xlsx")):
    kb = limits[fmt]["maxKB"]
    prefix = b"PK" if fmt == "xlsx" else b""
    exc = exc_of(lambda: sheet.read_table(name, prefix + b"x" * (kb * 1024 - len(prefix))))
    check(f"{fmt}: file at the size limit is read (not refused for size)", exc is None or exc.code != "import.tooBig", exc and exc.code)
    exc = exc_of(lambda: sheet.read_table(name, prefix + b"x" * (kb * 1024 + 1)))
    check(f"{fmt}: file above {kb} KB refused with the format's limit", exc and exc.code == "import.tooBig"
          and exc.params == {"max": kb, "format": fmt}, exc and (exc.code, exc.params))
    header = ["GTIN", "Descrição", "Tipo de link", "URL"]
    body = [["7898357410015", "A", "gs1:pip", "https://x.org"]]
    at_limit = sheet.Table([header] + body * limits[fmt]["maxRows"], fmt)
    check(f"{fmt}: {limits[fmt]['maxRows']} data rows accepted", error_code(lambda: sheet.parse_rows(at_limit, PT)) is None)
    over = sheet.Table([header] + body * (limits[fmt]["maxRows"] + 1), fmt)
    exc = exc_of(lambda: sheet.parse_rows(over, PT))
    check(f"{fmt}: one row more refused with the format's limit", exc and exc.code == "import.tooManyRows"
          and exc.params == {"max": limits[fmt]["maxRows"], "format": fmt}, exc and (exc.code, exc.params))
check("read_table reports the format of the rows", sheet.read_table("x.csv", b"a;b\r\n").format == "csv")

# Export → XLSX → import round trip
records = [{"key": "01", "value": "07898357410015", "qualifiers": [], "description": "Café torrado", "defaultLinkType": "gs1:pip",
            "links": [{"linktype": "gs1:instructions", "href": "https://x.org/m.pdf", "hreflang": ["pt", "en"], "fwqs": False},
                      {"linktype": "gs1:pip", "href": "https://x.org/cafe", "hreflang": ["pt"], "title": "Café"}]}]
labels = {"headers": {"key": "Chave (AI)", "value": "Identificador", "qualifiers": "Qualificadores", "lot": "Lote", "description": "Descrição", "linkType": "Tipo de link", "url": "URL",
                      "language": "Idioma", "title": "Título", "default": "Principal", "forward": "Repassar parâmetros"},
          "yes": "sim", "no": "não", "sheets": {"links": "Links", "linkTypes": "Tipos de link", "languages": "Idiomas"}}
rows = sheet.export_rows(records)
check("export: default link first and marked", rows[0][4] == "gs1:pip" and rows[0][8] == "yes" and rows[1][8] == "")
data = sheet.write_xlsx([list(r) for r in rows], labels, [("gs1:pip", "Página do produto", "…")], [("pt", "português")])
book = load_workbook(io.BytesIO(data))
links = book["Links"]
check("XLSX: localised headers and sheets", [c.value for c in links[1]][:4] == ["Chave (AI)", "Identificador", "Qualificadores", "Descrição"]
      and book.sheetnames == ["Links", "Tipos de link", "Idiomas"], book.sheetnames)
check("XLSX: key and identifier stored as text with leading zeros", links["A2"].value == "01" and links["B2"].value == "07898357410015"
      and links["B2"].number_format == "@")
back, errors = sheet.parse_rows(sheet.read_table("x.xlsx", data), PT)
check("XLSX round trip", not errors and len(back) == 1 and back[0]["links"][0]["default"]
      and back[0]["links"][1]["hreflang"] == ["pt", "en"], (back, errors))
check("export: no forward column (the query string is always passed on)", len(rows[0]) == 9
      and "Repassar parâmetros" not in [c.value for c in links[1]], [c.value for c in links[1]])
csv_bytes = sheet.write_csv([list(r) for r in rows], labels)
check("CSV export: BOM, ';' and localised yes", csv_bytes.startswith(b"\xef\xbb\xbf") and b";sim\r\n" in csv_bytes)
back, errors = sheet.parse_rows(sheet.read_table("x.csv", csv_bytes), PT, ["sim"], ["não"])
check("CSV round trip", not errors and back[0]["links"][0]["default"] and len(back[0]["links"]) == 2, (back, errors))

# Language tags and lots stored by other tools
import gs1  # noqa: E402
check("BCP 47 tags accepted in canonical case",
      [gs1.normalise_language(t) for t in ["pt", "pt-br", "en_US", "vi", "und", "zh-hant-tw", "es-419"]]
      == ["pt", "pt-BR", "en-US", "vi", "und", "zh-Hant-TW", "es-419"])
check("malformed tags refused", not any(gs1.normalise_language(t) for t in ["", "portuguese", "p", "en-", "en-US-x"]))
rows = sheet.read_table("x.csv", "GTIN;Descrição;Tipo de link;URL;Idioma\r\n7898357410015;A;gs1:pip;https://x.org;en-US, vi\r\n".encode())
records, _ = sheet.parse_rows(rows, PT)
check("language case kept from the file", records[0]["links"][0]["hreflang"] == ["en-US", "vi"], records[0]["links"][0])
check("template and unusual lots are not valid qualifiers",
      gs1.is_valid_qualifier_set("01", [("10", "L2026A")]) and not gs1.is_valid_qualifier_set("01", [("10", "{lotnumber}")])
      and not gs1.is_valid_qualifier_set("01", [("10", "A/B")]))
rows = sheet.read_table("x.csv", "GTIN;Qualificadores;Lote;Descrição;Tipo de link;URL\r\n7898357410015;(21)S1;L1;Café;gs1:pip;https://x.org\r\n7898357410015;/10/L1/21/S1;;Café;gs1:pip;https://y.org\r\n".encode())
records, errors = sheet.parse_rows(rows, {**PT, "qualifiers": ["Qualificadores"]})
check("qualifiers column (element strings or path) and the old lot column form one record",
      not errors and len(records) == 1 and records[0]["qualifiers"] == [("10", "L1"), ("21", "S1")], (records, errors))
rows = sheet.read_table("x.csv", "GTIN;Qualificadores;Descrição;Tipo de link;URL\r\n7898357410015;10/L1/21;Café;gs1:pip;https://x.org\r\n".encode())
_, errors = sheet.parse_rows(rows, {**PT, "qualifiers": ["Qualificadores"]})
check("malformed qualifiers reported", errors and errors[0]["code"] == "qualifier.format", errors)

# Other primary keys and spreadsheets made before them
rows = sheet.read_table("x.csv", "Chave (AI);Identificador;Descrição;Tipo de link;URL\r\n(00);095060001343520000;Palete;gs1:pip;https://x.org\r\n414;9506000134376;Loja;gs1:pip;https://y.org\r\n;7898357410015;Café;gs1:pip;https://z.org\r\n".encode())
records, errors = sheet.parse_rows(rows, PT)
check("key column: AI with or without brackets, empty means GTIN",
      [(r["key"], r["value"]) for r in records] == [("00", "095060001343520000"), ("414", "9506000134376"), ("01", "7898357410015")], records)
rows = sheet.read_table("x.csv", "GTIN;Descrição;Tipo de link;URL\r\n7898357410015;Café;gs1:pip;https://z.org\r\n".encode())
records, errors = sheet.parse_rows(rows, PT)
check("old spreadsheets with a GTIN column still import", not errors and records[0]["key"] == "01"
      and records[0]["value"] == "7898357410015", (records, errors))
rows = sheet.read_table("x.csv", "Chave (AI);Identificador;Descrição;Tipo de link;URL\r\n8004;9506000A;A;gs1:pip;https://x.org\r\n8004;9506000a;B;gs1:pip;https://y.org\r\n".encode())
records, _ = sheet.parse_rows(rows, PT)
check("alphanumeric keys are not merged by case or zeros", len(records) == 2)
big = ("gtin;description;linkType;url\n07898357410015;" + "x" * (140 * 1024) + ";gs1:pip;https://x.org\n").encode()
check("a CSV cell above 128 KB is reported (import.unreadable), not a server error",
      error_code(lambda: sheet.read_table("big.csv", big)) == "import.unreadable")

# What a file may hold once read (ADR 0032, finding F-014): the size limit bounds the file, not its content
import zipfile  # noqa: E402
from openpyxl import Workbook  # noqa: E402

SHEET_HEAD = b'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'


def xlsx_with(sheet_rows: bytes, compression=zipfile.ZIP_DEFLATED) -> bytes:
    """A workbook made by openpyxl whose first sheet's rows are replaced by the XML given."""
    workbook = Workbook()
    workbook.active.append(["x"])
    plain = io.BytesIO()
    workbook.save(plain)
    source, out = zipfile.ZipFile(io.BytesIO(plain.getvalue())), io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as target:
        for info in source.infolist():
            part = source.read(info)
            if info.filename == "xl/worksheets/sheet1.xml":
                part = SHEET_HEAD + sheet_rows + b"</sheetData></worksheet>"
            target.writestr(info.filename, part)
    return out.getvalue()


def inline(ref: str, text: str) -> bytes:
    return b'<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref.encode(), text.encode())


HEADER_CELLS = b"".join(inline(f"{c}1", t) for c, t in zip("ABCD", ["value", "description", "linkType", "url"]))
ROW = b"".join(inline(f"{c}%d", t) for c, t in zip("ABCD", ["7898357410015", "A", "gs1:pip", "https://x.org"]))

# A row a million rows down: the blank rows before it are one shared list, not a million rows of cells
far = sheet.read_table("far.xlsx", xlsx_with(b'<row r="1">' + HEADER_CELLS + b'</row><row r="1000000">'
                                             + (ROW % ((1000000,) * 4)) + b"</row>"))
check("XLSX: a row far down is read with its row number; the blank rows before it share one list",
      len(far) == 1000000 and far[-1][0] == "7898357410015" and len({id(r) for r in far[1:-1]}) == 1
      and not far[1], (len(far), len({id(r) for r in far[1:-1]})))
_calls, _cell_text = [], sheet._cell_text
sheet._cell_text = lambda value: (_calls.append(1), _cell_text(value))[1]
try:
    sheet.read_table("far.xlsx", xlsx_with(b'<row r="1">' + HEADER_CELLS + b'</row><row r="200000">'
                                           + (ROW % ((200000,) * 4)) + b"</row>"))
finally:
    sheet._cell_text = _cell_text
check("XLSX: the cells of blank rows are not converted one by one (only the two rows with values)",
      len(_calls) == 2 * sheet.MAX_COLUMNS, len(_calls))
records, _ = sheet.parse_rows(far, {})
check("XLSX: the far row keeps its spreadsheet row number", records and records[0]["rows"] == [1000000],
      records and records[0]["rows"])
beyond = sheet.read_table("beyond.xlsx", xlsx_with(b'<row r="1">' + HEADER_CELLS + b'</row><row r="50000000">'
                                                    + (ROW % ((50000000,) * 4)) + b"</row>"))
check("XLSX: rows past Excel's last row are not read", len(beyond) == 1, len(beyond))
check("XLSX: blank rows at the end are dropped", len(sheet.read_table("tail.xlsx", xlsx_with(
    b'<row r="1">' + HEADER_CELLS + b'</row><row r="900000"><c r="A900000"/></row>'))) == 1)

# A cell in the last column (XFD): only the first MAX_COLUMNS cells of a row are read
wide = sheet.read_table("wide.xlsx", xlsx_with(b'<row r="1">' + HEADER_CELLS + inline("XFD1", "far") + b"</row>"))
check(f"XLSX: a cell in column XFD does not make rows of 16 384 cells (at most {sheet.MAX_COLUMNS})",
      len(wide) == 1 and len(wide[0]) == sheet.MAX_COLUMNS and "far" not in wide[0], len(wide[0]) if wide else wide)
csv_wide = sheet.read_table("wide.csv", b"value;description;linkType;url" + b";" * 300000 + b"tail\r\n")
check(f"CSV: a row of 300 000 cells is read as its first {sheet.MAX_COLUMNS}",
      len(csv_wide[0]) == sheet.MAX_COLUMNS and "tail" not in csv_wide[0], len(csv_wide[0]))
check("CSV: blank rows share one list; trailing blank rows dropped",
      [len(r) for r in sheet.read_table("b.csv", b"a;b\r\n\r\n\r\nc;d\r\n" + b"\r\n" * 50000)] == [2, 0, 0, 2])

# Reading stops at the row limit, before the rest of the file is read
for fmt, name in (("csv", "rows.csv"), ("xlsx", "rows.xlsx")):
    max_rows = sheet.FORMATS[fmt][1]
    if fmt == "csv":
        data = b"value;description;linkType;url\r\n" + b"7898357410015;A;gs1:pip;https://x.org\r\n" * (max_rows + 1)
    else:
        data = xlsx_with(b'<row r="1">' + HEADER_CELLS + b"</row>" + b"".join(
            b'<row r="%d">' % r + (ROW % ((r,) * 4)) + b"</row>" for r in range(2, max_rows + 3)))
    exc = exc_of(lambda: sheet.read_table(name, data))
    check(f"{fmt}: read_table refuses one data row past the limit itself", exc and exc.code == "import.tooManyRows"
          and exc.params == {"max": max_rows, "format": fmt}, exc and (exc.code, exc.params))


def endless():
    """An iterator that fails if anything reads past the row limit's first extra row."""
    yield ["value", "description", "linkType", "url"]
    for _ in range(sheet.MAX_ROWS):
        yield ["7898357410015", "A", "gs1:pip", "https://x.org"]
    yield ["7898357410015", "A", "gs1:pip", "https://x.org"]
    raise AssertionError("read past the row limit")


exc = exc_of(lambda: sheet._take(endless(), sheet.MAX_ROWS, "csv"))
check("reading stops at the first row past the limit (nothing after it is read)",
      exc and exc.code == "import.tooManyRows", exc)
check("leading blank rows and the header are not counted as data rows",
      len(sheet._take(iter([[""], [], ["h"]] + [["d"]] * 3), 3, "csv")) == 6)

# Unpacked size: measured by unpacking, refused before openpyxl opens the workbook
big = xlsx_with(b'<row r="1">' + inline("A1", "a" * (sheet.MAX_UNPACKED_MB * 1024 * 1024 + 1)) + b"</row>")
exc = exc_of(lambda: sheet.read_table("big.xlsx", big))
check(f"XLSX: a few KB that unpack into more than {sheet.MAX_UNPACKED_MB} MB refused (import.unpackedTooBig)",
      len(big) < 200 * 1024 and exc and exc.code == "import.unpackedTooBig" and exc.params == {"max": sheet.MAX_UNPACKED_MB},
      (len(big), exc and (exc.code, exc.params)))
under = xlsx_with(b'<row r="1">' + HEADER_CELLS + b'</row><row r="2">' + inline("A2", "a" * (8 * 1024 * 1024)) + b"</row>")
check("XLSX: a file that unpacks into 8 MB is read", exc_of(lambda: sheet.read_table("under.xlsx", under)) is None)
check("XLSX: parts compressed otherwise than Excel's (bzip2) refused as unreadable",
      error_code(lambda: sheet.read_table("bz.xlsx", xlsx_with(b"", zipfile.ZIP_BZIP2))) == "import.unreadable")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
