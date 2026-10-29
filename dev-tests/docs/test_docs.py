"""
The documents kept in step with the software (backlog item 9.11, Documentation/adr/0016-documentation-and-feature-
inventory.md): every feature of Documentation/features.md cites at least one check, each reference names a program of
the inventory and words found in one of its checks (Documentation/test-inventory.json, generated from a run of the
tests by dev-tests/docs/inventory.py); every test program is in the inventory, the developer guide (section 13, with the
inventory's count) and dev-tests/README.md; the API reference is what portal/openapi.json gives; the documentation index
names every manual and record; and every relative link of the documents leads to a file that exists.

  python dev-tests/docs/test_docs.py
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DOCS = os.path.join(REPO, "Documentation")
sys.path.insert(0, os.path.join(REPO, "dev-tests"))

import test_programs  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def read(*parts):
    return open(os.path.join(REPO, *parts), encoding="utf-8").read()


inventory = json.loads(read("Documentation", "test-inventory.json"))["programs"]
programs = {p.name: p for p in test_programs.PROGRAMS} | {"docs": None}

# ------------------------------------------------------------------------------------------------ features and checks
REFERENCE = re.compile(r"`([a-z0-9_]+)`(?::\s*([^·|]+))?")
rows, header = [], None
for line in read("Documentation", "features.md").splitlines():
    if not line.startswith("|"):
        header = None
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if cells[0] == "Feature":
        header = cells
        continue
    if header and not set(line.replace("|", "").strip()) <= set("-: "):
        rows.append(dict(zip(header, cells)))
check(f"features.md: every table has a Checks column ({len(rows)} features)",
      len(rows) > 150 and all("Checks" in r for r in rows), [r.get("Feature") for r in rows if "Checks" not in r][:5])
without = [r["Feature"] for r in rows if not REFERENCE.search(r.get("Checks", ""))]
check("…every feature cites at least one check", not without, without[:10])
unknown, unmatched, references = [], [], 0
for r in rows:
    for program, words in REFERENCE.findall(r.get("Checks", "")):
        references += 1
        if program not in inventory:
            unknown.append((r["Feature"], program))
            continue
        words = words.strip().lower()
        if words and not any(words in c.lower() for c in inventory[program]["checks"]) \
                and not inventory[program].get("ciOnly"):
            unmatched.append((r["Feature"], program, words))
check(f"…each reference names a program of the inventory ({references} references)", not unknown, unknown[:10])
check("…and words found in one of its checks", not unmatched, unmatched[:10])

# ------------------------------------------------------------------------------------------------ the inventory
missing = sorted(set(programs) - set(inventory))
check(f"every test program is in the inventory ({len(programs)})", not missing, missing)
extra = sorted(set(inventory) - set(programs))
check("…and the inventory holds no program that no longer exists", not extra, extra)
markdown = read("Documentation", "test-inventory.md")
check("…its page lists every program with its count", all(f"<code>{n}</code> — {p['count']} checks" in markdown
                                                          for n, p in inventory.items()))
searches = markdown.split("## Every search and filter", 1)[-1].split("\n## ", 1)[0]
check("…and gathers every search and filter, the search by EPC included", "<code>scan_search</code>" in searches
      and "<code>portal_e2e</code>" in searches and "search by that EPC" in searches, searches[:300])

# ------------------------------------------------------------------------------------------------ developer guide, tests README
guide, readme = read("Documentation", "developer-guide.md"), read("dev-tests", "README.md")
counts = {}
for name, program in programs.items():
    path = program.path if program else "docs/test_docs.py"
    found = re.search(rf"\| `{re.escape(path)}` \| (\d+) \|", guide)
    counts[name] = (path, int(found.group(1)) if found else None)
no_row = sorted(n for n, (_, c) in counts.items() if c is None)
check("developer guide, section 13: a row for every program", not no_row, no_row)
# a file that two programs run (the portal without the engine) is counted by its first program; this program's own
# count is left out (it would depend on itself)
first = {}
for name, (path, _) in counts.items():
    first.setdefault(path, name)
wrong = sorted((n, c, inventory[n]["count"]) for n, (path, c) in counts.items()
               if c is not None and first[path] == n and n in inventory and not inventory[n].get("ciOnly")
               and n != "docs" and c != inventory[n]["count"])
check("…with the inventory's count", not wrong, wrong)
no_line = sorted(n for n, (path, _) in counts.items() if f"`{path}`" not in readme)
check("dev-tests/README.md: a line for every program", not no_line, no_line)

# ------------------------------------------------------------------------------------------------ API reference
run = subprocess.run([sys.executable, os.path.join(REPO, "portal", "tools", "gen_api_reference.py"), "--check"],
                     capture_output=True, text=True)
check("the API reference is what portal/openapi.json gives (gen_api_reference.py --check)", run.returncode == 0,
      run.stderr[-300:])

# ------------------------------------------------------------------------------------------------ the index
index = read("Documentation", "README.md")
manuals = ["portal-user-guide.md", "extensions/README.md", "developer-guide.md", "api-reference.md", "features.md",
           "test-inventory.md", "conformance-review.md", "translation-glossary.md",
           "extensions/CHANGELOG.md"]
absent = [m for m in manuals if f"]({m})" not in index]
check("the documentation index names every manual", not absent, absent)
adrs = sorted(f for f in os.listdir(os.path.join(DOCS, "adr")) if f.endswith(".md"))
absent = [a for a in adrs if f"](adr/{a})" not in index]
check(f"…and every decision record ({len(adrs)})", not absent, absent)

# ------------------------------------------------------------------------------------------------ links
LINK = re.compile(r"\]\(([^)\s]+)\)")
broken = []
files = [os.path.join(REPO, "README.md"), os.path.join(REPO, "dev-tests", "README.md")]
for folder, _, names in os.walk(DOCS):
    files += [os.path.join(folder, n) for n in names if n.endswith(".md")]
for path in files:
    text = re.sub(r"```.*?```", "", open(path, encoding="utf-8").read(), flags=re.S)
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        local = target.split("#", 1)[0]
        if local and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), local))):
            broken.append((os.path.relpath(path, REPO), target))
check(f"every relative link of the documents leads to a file ({len(files)} documents)", not broken, broken[:10])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
