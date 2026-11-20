# ADR 0032 — Spreadsheet imports: limits on what a file holds, read one row at a time

| | |
|---|---|
| Status | **Accepted** (20 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D6 and hazard H-17 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): reading stops at the row limit, only the first columns of a row are read, an XLSX file is measured unpacked before it is opened; the preview stays in the request |

## 1. Context

An editor imports links from a spreadsheet (`POST /portal/api/import/preview`, `portal/sheet.py`). The import had a
limit on the file's size (700 KB, `sheet.FORMATS`) and on its data rows (5 000), but the row limit was applied
after the whole first sheet had been read into memory, every row padded to the widest one. An XLSX file is a ZIP
archive of XML parts, and its size says little about its content:

- a cell a million rows down made the reader produce a million rows (a file of 4 KB);
- a cell in the last column (`XFD`, column 16 384) padded every row to 16 384 cells: 8 000 such rows, a file of
  69 KB, took 5 seconds and 1.1 GB of memory, and a file at the size limit would have taken ten times as much;
- a part of a few kilobytes could unpack into gigabytes before openpyxl had read a cell (deflate reaches about
  1 000 to 1, and openpyxl reads the whole shared-strings part when it opens a workbook).

Any editor of any organisation could therefore exhaust the portal's memory with one request. A CSV file was bounded
by its size (700 KB of text), but a row of 700 000 separators still became a row of 700 000 cells.

## 2. Decision

`sheet.read_table()` reads the rows one at a time and keeps only what the import can use:

1. **Row limit while reading.** The rows come from a generator (`_read_xlsx()`, `_read_csv()`); `_take()` counts
   the non-blank rows and raises `import.tooManyRows` at the first one past the header and the format's row limit,
   before anything after it is read. `parse_rows()` keeps its own check for rows given directly.
2. **Blank rows cost a reference.** Every blank row is the same empty list (`_BLANK`), so the row numbers of the
   spreadsheet stay right for error messages without a row of cells per blank row; blank rows at the end are
   dropped. In an XLSX file no row after Excel's last row (1 048 576, `XLSX_LAST_ROW`) is read.
3. **Columns.** Only the first `MAX_COLUMNS` (64) cells of a row are read, in both formats. The layout has ten
   columns; a column further right is ignored, as if it were not there.
4. **Unpacked size.** Before openpyxl opens an XLSX file, `_check_unpacked()` unpacks every part of the archive and
   counts the bytes, stopping as soon as they pass `MAX_UNPACKED_MB` (32 MB): `import.unpackedTooBig` (a new message,
   in every language). The sizes an archive declares are not trusted. Parts compressed with anything other than
   Excel's methods (stored or deflate) are refused as `import.unreadable`, since bzip2 and LZMA can unpack a small
   chunk into far more than the reader asked for. An honest file at the size limit unpacks into 4 to 15 MB (measured
   with 5 000 rows of ten to twenty columns of distinct URLs).

With these limits the worst file at the size limit is read in about a third of a second and some 60 MB of memory.

## 3. Options considered

| Question | Chosen | Not chosen |
|---|---|---|
| Where the row limit applies | while reading, at the first row past it | after reading (the weakness); a limit on all rows, blank ones included (a sheet with formatted empty rows would be refused) |
| Wide rows | read the first 64 cells, ignore the rest | refuse the file (a sheet with a far column of notes would fail for no reason); the sheet's declared dimension (a file can declare anything) |
| Unpacked content | measured by unpacking, 32 MB | the sizes the archive declares (trusted only by `zipfile`'s own reading, which stops at them; measuring costs at most 32 MB of inflation, a tenth of a second); no limit (the weakness) |
| The preview in the worker | no: the preview stays in the request, now bounded | an asynchronous preview job (the browser would poll for the report, a larger change for a cost that the limits above already bound; the portal's request limits per address, [ADR 0031](0031-request-limits.md), bound how often one address can send it) |

## 4. Consequences

- One import request can no longer take more than a fraction of a second and some tens of megabytes to read; the
  rest of the preview (the editor's rules for at most 5 000 rows) is unchanged.
- An XLSX file that unpacks into more than 32 MB is refused with a message that says so; columns past the 64th are
  ignored. Neither is reached by a spreadsheet of the import's layout.
- The preview still runs in the web process: a burst of imports by several editors at once still takes several
  workers' time, each bounded as above.

## 5. Delivery

In one step (20 November 2026): `portal/sheet.py` (`read_table()`, `_take()`, `_check_unpacked()`, `_read_xlsx()`,
`_read_csv()`, `MAX_COLUMNS`, `MAX_UNPACKED_MB`, `XLSX_LAST_ROW`); the text `import.unpackedTooBig` in every
language. Checks in `dev-tests/portal/test_sheet.py` and `dev-tests/portal/test_jobs.py` (the preview through the API).
