"""
Records outside the rules: a report, for server administrators, of what the resolver holds that the rules of today
would refuse (Documentation/adr/0056-records-outside-the-rules.md).

The data entry API checks the anchors (ADR 0049, finding U-004) and the targets (ADR 0048, finding U-003) of what is
sent to it from then on; neither decision changed what was stored before. Documents written under other anchor
shapes (/01/…/10/LOT as an anchor, an AI that is not a primary key) and targets the portal's rule refuses (http:,
javascript:, an address inside a network) stay where they are, are resolved as before and, for the anchors, are not
all in the portal's record list. This report lists them, read from the data entry API's summary with links; it
changes nothing.

Each row is one of:

  anchorShape     the anchor is not /AI/value with a primary key the portal knows (one row per anchor)
  keyValue        /AI/value, but the value is not one the portal's rules for that key accept (one row per anchor)
  targetNotHttps  a target that is not an https address (http:, javascript:, data:, mailto: …)
  targetHost      an https target whose host is an address, a name that is not a public one, or has a user name
  targetForm      any other target the rule refuses: empty, spaces or control characters, a port that is not a number

The record's own page (gs1:defaultLink to its GS1 Digital Link with ?linkType=linkset&view=page) is the portal's
and is not checked. Per-organisation host lists (ADR 0037) are not applied: the rule is the one the data entry API
applies to everyone (data_entry_server/src/target_rule.py).
"""
import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

import gs1
import sheet
import tenants as tenants_mod
from gs1 import ValidationError

ANCHOR_PROBLEMS = ("anchorShape", "keyValue")
TARGET_PROBLEMS = ("targetNotHttps", "targetHost", "targetForm")
PROBLEMS = ANCHOR_PROBLEMS + TARGET_PROBLEMS
SCREEN_ROWS = 20                     # rows the screen shows; the files hold every row
COLUMNS = ("problem", "anchor", "qualifiers", "organisation", "linkType", "target")
_HOST_CODES = ("link.urlUserInfo", "link.urlAddress", "link.urlHost")


def anchor_problem(anchor) -> str | None:
    """anchorShape, keyValue or None for the anchor of a summary line."""
    key = gs1.split_anchor(anchor if isinstance(anchor, str) else "")
    if not key:
        return "anchorShape"
    ai, value = key
    try:
        return None if gs1.normalise_key(ai, value) == value else "keyValue"
    except ValidationError:
        return "keyValue"


def target_problem(href) -> str | None:
    """targetNotHttps, targetHost, targetForm or None for a stored target (the portal's rule, gs1.normalise_url())."""
    text = href if isinstance(href, str) else ""
    if not text.strip().lower().startswith("https:"):
        return "targetNotHttps"
    if text != text.strip():
        return "targetForm"                 # the data entry API checks a target as sent; the portal trims it
    try:
        gs1.normalise_url(text, 1)
    except ValidationError as exc:
        return "targetHost" if exc.code in _HOST_CODES else "targetForm"
    return None


def _qualifiers(line: dict) -> str:
    """The qualifiers of a summary line as element strings: (10)L1(21)S1."""
    out = []
    for item in line.get("qualifiers") or []:
        if isinstance(item, dict):
            out += [f"({k}){v}" for k, v in item.items()]
    return "".join(out)


def rows(lines: list[dict], tenant_list: list[dict]) -> list[dict]:
    """The report's rows for the summary lines (GET /summary?links=true), anchors first, then targets, each in the
    summary's order. organisation: the name of the organisation whose prefix holds the anchor ("" for the operator's
    or an anchor without one)."""
    names = {t["id"]: t.get("name") or t["id"] for t in tenant_list}
    anchors, targets, seen = [], [], set()
    for line in lines:
        if not isinstance(line, dict):
            continue
        anchor = line.get("anchor") if isinstance(line.get("anchor"), str) else ""
        problem = anchor_problem(anchor)
        owner = "" if problem == "anchorShape" else names.get(tenants_mod.owner(anchor, tenant_list), "")
        if problem and anchor not in seen:
            seen.add(anchor)
            anchors.append({"problem": problem, "anchor": anchor, "qualifiers": "", "organisation": owner,
                            "linkType": "", "target": ""})
        for link in line.get("links") or []:
            if not isinstance(link, dict) or gs1.is_landing(link):
                continue
            found = target_problem(link.get("href"))
            if found:
                targets.append({"problem": found, "anchor": anchor, "qualifiers": _qualifiers(line),
                                "organisation": owner, "linkType": str(link.get("linktype") or ""),
                                "target": str(link.get("href") or "")})
    return anchors + targets


def counts(found: list[dict]) -> dict:
    """{"total", "anchors", "targets", "byProblem": {problem: n}} of the report's rows."""
    by = {p: 0 for p in PROBLEMS}
    for row in found:
        by[row["problem"]] += 1
    return {"total": len(found), "anchors": sum(by[p] for p in ANCHOR_PROBLEMS),
            "targets": sum(by[p] for p in TARGET_PROBLEMS), "byProblem": by}


def _label(labels: dict, code: str) -> str:
    return sheet.xlsx_text(labels.get(code) or code)


def table(found: list[dict], labels: dict) -> tuple[list[str], list[list]]:
    """(header, rows) in the user's language: labels has legacy.col.<column> and legacy.problem.<problem>."""
    header = [_label(labels, "legacy.col." + c) for c in COLUMNS]
    body = [[_label(labels, "legacy.problem." + r["problem"])] + [r[c] for c in COLUMNS[1:]] for r in found]
    return header, body


def write_csv(found: list[dict], labels: dict) -> bytes:
    """UTF-8 with BOM, ';', cells protected against formulas (as the portal's other CSV files)."""
    header, body = table(found, labels)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    for row in body:
        writer.writerow([sheet.protect(c) for c in row])
    return ("﻿" + out.getvalue()).encode("utf-8")


def write_xlsx(found: list[dict], labels: dict) -> bytes:
    """One sheet, the header in bold and frozen."""
    header, body = table(found, labels)
    book = Workbook()
    ws = book.active
    ws.title = (_label(labels, "legacy.sheet") or "Records")[:31].translate({ord(c): " " for c in "[]:*?/\\"})
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in body:
        ws.append([sheet.protect(sheet.xlsx_text(str(c))) for c in row])
    for i, name in enumerate(header, start=1):
        width = max([len(str(name)), 8] + [len(str(r[i - 1])) for r in body])
        ws.column_dimensions[get_column_letter(i)].width = min(80, width + 2)
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
