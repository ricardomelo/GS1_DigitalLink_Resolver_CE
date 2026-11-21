#!/usr/bin/env python3
"""
Reads the reports of pip-audit (the four Python lock files) and npm audit (the two npm lock files) written by the
supply-chain workflow (.github/workflows/supply-chain.yml; Documentation/adr/0033-supply-chain.md, section 2.2) and
fails on a known vulnerability that has a correction available and is not accepted in accepted.yaml.

    audit.py --accepted .github/supply-chain/accepted.yaml REPORT.json...

A report's kind is told from its content (pip-audit: "dependencies"; npm audit: "auditReportVersion"). An accepted
entry matches the advisory's identifier or any of its aliases (CVE, GHSA, PYSEC) and counts only until its
expired_at date. Every vulnerability found is listed, with or without a correction, and the list also goes to the
run's summary (GITHUB_STEP_SUMMARY) when there is one.

Exit status: 0 nothing to correct; 1 a vulnerability to correct; 2 a report missing or unreadable (a failed scan
is never taken for a clean one).
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

import yaml


def accepted_ids(path: str, today: datetime.date) -> dict[str, str]:
    """Identifier → statement of every entry still valid today."""
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = {}
    for entry in doc.get("vulnerabilities") or []:
        expires = entry.get("expired_at")
        if isinstance(expires, str):
            expires = datetime.date.fromisoformat(expires)
        if isinstance(expires, datetime.datetime):
            expires = expires.date()
        if isinstance(expires, datetime.date) and expires >= today:
            out[str(entry["id"]).upper()] = str(entry.get("statement", ""))
    return out


def findings_pip(report: dict, source: str) -> list[dict]:
    out = []
    for dep in report.get("dependencies") or []:
        for vuln in dep.get("vulns") or []:
            out.append({"source": source, "package": dep.get("name", "?"), "version": dep.get("version", "?"),
                        "ids": [vuln.get("id", "?")] + list(vuln.get("aliases") or []),
                        "fix": ", ".join(vuln.get("fix_versions") or []),
                        "fixable": bool(vuln.get("fix_versions"))})
    return out


def findings_npm(report: dict, source: str) -> list[dict]:
    out = []
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        advisories = [v for v in vuln.get("via") or [] if isinstance(v, dict)]
        ids = [m.group(0) for v in advisories for m in [re.search(r"GHSA(-[0-9a-z]{4}){3}", str(v.get("url", "")))] if m]
        ids += [str(v["source"]) for v in advisories if not v.get("url") and "source" in v]
        fixable = bool(vuln.get("fixAvailable"))
        out.append({"source": source, "package": name, "version": vuln.get("range", "?"),
                    "ids": ids or [f"via {', '.join(map(str, vuln.get('via') or []))}"],
                    "fix": "npm audit fix" if fixable else "", "fixable": fixable})
    return out


def read_report(path: str) -> list[dict]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(report, dict) and isinstance(report.get("dependencies"), list):
        return findings_pip(report, path)
    if isinstance(report, dict) and "auditReportVersion" in report and isinstance(report.get("vulnerabilities"), dict):
        return findings_npm(report, path)
    raise ValueError("neither a pip-audit nor an npm audit report")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--accepted", required=True)
    parser.add_argument("--today", help="YYYY-MM-DD (for the tests)")
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args(argv)
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    accepted = accepted_ids(args.accepted, today)
    findings, broken = [], []
    for path in args.reports:
        try:
            findings += read_report(path)
        except (OSError, ValueError) as exc:     # json.JSONDecodeError is a ValueError
            broken.append(f"{path}: {exc}")
    lines = ["| Lock file | Package | Version | Advisory | Correction | Verdict |", "|---|---|---|---|---|---|"]
    failing = 0
    for f in findings:
        hit = next((i for i in f["ids"] if i.upper() in accepted), None)
        if hit:
            verdict = f"accepted ({accepted[hit.upper()]})"
        elif f["fixable"]:
            verdict, failing = "**to correct**", failing + 1
        else:
            verdict = "no correction yet"
        lines.append(f"| {f['source']} | {f['package']} | {f['version']} | {', '.join(f['ids'])} | {f['fix'] or '-'} "
                     f"| {verdict} |")
    summary = [f"### Known vulnerabilities of the lock files: {len(findings)} found, {failing} to correct", ""]
    summary += lines if findings else ["None."]
    summary += [""] + [f"- unreadable report: {b}" for b in broken]
    print("\n".join(summary))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write("\n".join(summary) + "\n")
    return 2 if broken else (1 if failing else 0)


if __name__ == "__main__":
    sys.exit(main())
