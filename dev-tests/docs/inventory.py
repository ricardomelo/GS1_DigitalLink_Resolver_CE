#!/usr/bin/env python3
"""
The inventory of the software's features, drawn from the development tests' checks (backlog item 9.11,
Documentation/adr/0016-documentation-and-feature-inventory.md): every program prints one "PASS <check>" line per check,
a sentence that says what is true; this collects them, grouped by area and program, into
Documentation/test-inventory.md (to read) and Documentation/test-inventory.json (for dev-tests/docs/test_docs.py).

  DEV_TESTS_STRICT=1 DEV_TESTS_INVENTORY=/tmp/inventory python3 -m pytest dev-tests -m "not database"
  python3 dev-tests/docs/inventory.py build /tmp/inventory

The program on a real MongoDB (store_mongodb) runs on the CI only: it is listed with the count the developer guide gives.
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
MARKDOWN = os.path.join(REPO, "Documentation", "test-inventory.md")
JSON = os.path.join(REPO, "Documentation", "test-inventory.json")

# The areas in the order of the user guide, and the programs of each (one area per program)
AREAS = [
    ("Resolution: the resolver, its pages and its log", ["resolver", "gs1_suite", "epc_binary", "data_entry_api",
                                                         "mock_parity", "request_log", "domains_resolver",
                                                         "forwarding_resolver", "landing", "load"]),
    ("Records: keys, qualifiers, links and the editor", ["keys", "registration", "data_attributes", "special_chars",
                                                         "dictionary", "engine_messages", "link_types", "governance",
                                                         "fix_serials", "portal_e2e", "portal_e2e_without_engine",
                                                         "link_types_e2e"]),
    ("Searching and filtering records", ["scan_search"]),
    ("Labels, RFID and NFC", ["label", "datamatrix", "datamatrix_e2e", "epc_label", "gcp", "gcp_e2e"]),
    ("Spreadsheets, link checks and background work", ["sheet", "linkcheck", "jobs"]),
    ("The item's page", ["item_page", "item_page_e2e", "titles"]),
    ("Requests and the overview", ["requestlog", "requests_e2e", "overview", "overview_e2e"]),
    ("Administration: organisations, users, exports, sign-in, API, domains, alerts, e-mail, privacy, forwarding",
     ["tenants", "admin_nav", "admin_nav_e2e", "exports", "sso", "sso_e2e", "session", "api", "api_e2e", "domains",
      "domains_e2e", "monitor", "mail", "mail_e2e", "privacy", "privacy_e2e", "forwarding", "forwarding_e2e"]),
    ("Interface and languages", ["portal_config", "i18n", "languages_e2e"]),
    ("The documents", ["docs"]),
    ("Data store, installation and operation", ["store", "store_mongodb", "home", "install", "deploy"]),
]
CI_ONLY = {"store_mongodb"}
# Checks gathered from every area under one heading, as the owner asked for "every search and filter, the search by EPC
# included": a check is listed there when its name matches
SEARCHES = re.compile(r"\b(search|searched|searching|filters?(?! ?[0-7]\b| value|=|Invalid)|filtered|finds?|"
                      r"look(?:s|ed)? up|read as)\b", re.IGNORECASE)


def area_of(program: str) -> str:
    return next((name for name, programs in AREAS if program in programs), "Other")


def _anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).replace(" ", "-")


def _ci_count(program: str) -> int:
    """The count of a CI-only program, from the developer guide's table (section 13)."""
    guide = open(os.path.join(REPO, "Documentation", "developer-guide.md"), encoding="utf-8").read()
    found = re.search(rf"\| `portal/test_{program}\.py` \| (\d+) \|", guide)
    return int(found.group(1)) if found else 0


def build(folder: str) -> dict:
    programs = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".txt"):
            lines = open(os.path.join(folder, name), encoding="utf-8").read().splitlines()
            programs[name[:-4]] = [line[5:].strip() for line in lines if line.startswith("PASS ")]
    for name in CI_ONLY:
        programs.setdefault(name, [])
    data = {"generated": date.today().isoformat(),
            "programs": {name: {"area": area_of(name), "checks": checks,
                                "count": len(checks) if checks or name not in CI_ONLY else _ci_count(name),
                                "ciOnly": name in CI_ONLY}
                         for name, checks in programs.items()}}
    with open(JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    with open(MARKDOWN, "w", encoding="utf-8") as fh:
        fh.write(markdown(data))
    return data


def markdown(data: dict) -> str:
    programs = data["programs"]
    total = sum(p["count"] for p in programs.values())
    out = ["# Inventory of features from the development tests", "",
           f"Every check of every development test program on {data['generated']}: {total:,} checks in "
           f"{len(programs)} programs. Each line is the sentence a program prints when the check passes; together they "
           "say what the software does, every search and filter included, and that it works. Each feature of "
           "[features.md](features.md) names the checks that prove it. Generated by `dev-tests/docs/inventory.py` "
           "from a complete run ([ADR 0016](adr/0016-documentation-and-feature-inventory.md)); do not edit by hand.",
           "", "| Area | Programs | Checks |", "|---|---|---:|"]
    for area, names in AREAS:
        present = [n for n in names if n in programs]
        if present:
            out.append(f"| [{area}](#{_anchor(area)}) | " + ", ".join(f"`{n}`" for n in present) + f" | "
                       f"{sum(programs[n]['count'] for n in present):,} |")
    searching = dict(AREAS)["Searching and filtering records"]          # every check of the search's own programs
    found = [(n, c) for n, p in programs.items() for c in p["checks"] if n in searching or SEARCHES.search(c)]
    out.append(f"| [Every search and filter](#every-search-and-filter), from every area | — | {len(found):,} |")
    out.append("")
    out += ["## Every search and filter", "",
            "The checks of every program about searching, filtering and finding — the record list's text search and "
            "filters, a code or a scanner's data, an RFID reader's EPC, the requests', audit trail's and alerts' filters, "
            "the API's — gathered from the areas below (they are listed there too).", ""]
    for name in [n for _, names in AREAS for n in names if n in programs]:
        mine = [c for n, c in found if n == name]
        if mine:
            out.append(f"<details><summary><code>{name}</code> — {len(mine)} checks</summary>")
            out.append("")
            out += ["- " + c.replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|") for c in mine]
            out += ["", "</details>", ""]
    for area, names in AREAS:
        present = [n for n in names if n in programs]
        if not present:
            continue
        out += [f"## {area}", ""]
        for name in present:
            p = programs[name]
            out.append(f"<details><summary><code>{name}</code> — {p['count']} checks</summary>")
            out.append("")
            if p["ciOnly"] and not p["checks"]:
                out.append("Runs on the CI only (a real MongoDB); see `dev-tests/README.md`.")
            for check in p["checks"]:
                out.append("- " + check.replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|"))
            out += ["", "</details>", ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "build":
        data = build(argv[1])
        print(f"{MARKDOWN}: {sum(p['count'] for p in data['programs'].values())} checks in {len(data['programs'])} programs")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
