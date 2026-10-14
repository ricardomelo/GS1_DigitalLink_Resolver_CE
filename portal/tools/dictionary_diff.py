#!/usr/bin/env python3
"""
What changes between two generated dictionaries (portal/gs1_dictionary.json of two engine releases), as Markdown
for the issue the weekly update check opens (.github/workflows/engine-update.yml, ADR 0003).

  python portal/tools/dictionary_diff.py OLD.json NEW.json

Lists AIs added and removed; AIs whose format, flags, associations or title changed; data attributes gained or
lost (flag "?"); primary keys and their qualifiers; and whether the portal can still build its rules from the new
file (a format it cannot check is named).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _fmt(entry: dict) -> str:
    """A component list written as the dictionary writes it: "N13,csum,gcppos1 [X..17]"."""
    parts = []
    for c in entry["components"]:
        size = f"{c['type']}{c['max']}" if c["min"] == c["max"] else f"{c['type']}..{c['max']}"
        text = ",".join([size, *c["linters"]])
        parts.append(f"[{text}]" if c["optional"] else text)
    return " ".join(parts)


def _groups(instances) -> str:
    return " ".join(",".join("+".join(group) for group in instance) for instance in instances) or "—"


def compare(old: dict, new: dict) -> dict:
    """The differences, as data: {added, removed, changed, attributes_gained, attributes_lost, keys}."""
    a, b = old["ais"], new["ais"]
    changed = []
    for code in sorted(set(a) & set(b)):
        fields = [name for name in ("title", "flags", "components", "req", "ex", "dlpkey") if a[code].get(name) != b[code].get(name)]
        if fields:
            changed.append((code, fields))
    attr = lambda d, c: "?" in d[c]["flags"]                                     # noqa: E731
    return {
        "added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)), "changed": changed,
        "attributes_gained": sorted(c for c in b if attr(b, c) and (c not in a or not attr(a, c))),
        "attributes_lost": sorted(c for c in a if attr(a, c) and (c not in b or not attr(b, c))),
        "keys": sorted(c for c in set(a) | set(b) if a.get(c, {}).get("dlpkey") != b.get(c, {}).get("dlpkey")),
    }


def portal_check(new: dict) -> str | None:
    """None when the portal can build its rules from the new dictionary, otherwise why not."""
    import gs1                                              # noqa: PLC0415 — the portal's rule builder
    import gs1dict                                          # noqa: PLC0415
    try:
        gs1._build(new)
    except gs1dict.DictionaryError as exc:
        return str(exc)
    return None


def markdown(old: dict, new: dict) -> str:
    """The summary for the issue."""
    diff = compare(old, new)
    a, b = old["ais"], new["ais"]
    title = lambda d, c: d[c]["title"]                                             # noqa: E731
    out = [f"Dictionary {old.get('dictionary')} (engine {old.get('release')}) → "
           f"{new.get('dictionary')} (engine {new.get('release')}).", ""]
    if not any(diff.values()):
        out.append("No AI changed.")
    if diff["added"]:
        out += ["**AIs added**", ""] + [f"- ({c}) {title(b, c)} — `{_fmt(b[c])}`, req {_groups(b[c]['req'])}"
                                        f"{', data attribute' if '?' in b[c]['flags'] else ''}" for c in diff["added"]] + [""]
    if diff["removed"]:
        out += ["**AIs removed**", ""] + [f"- ({c}) {title(a, c)}" for c in diff["removed"]] + [""]
    if diff["changed"]:
        out += ["**AIs changed**", ""]
        for code, fields in diff["changed"]:
            details = []
            if "components" in fields:
                details.append(f"format `{_fmt(a[code])}` → `{_fmt(b[code])}`")
            if "flags" in fields:
                details.append(f"flags `{a[code]['flags'] or '—'}` → `{b[code]['flags'] or '—'}`")
            if "req" in fields:
                details.append(f"req {_groups(a[code]['req'])} → {_groups(b[code]['req'])}")
            if "ex" in fields:
                details.append(f"ex {_groups(a[code]['ex'])} → {_groups(b[code]['ex'])}")
            if "title" in fields:
                details.append(f"title “{a[code]['title']}” → “{b[code]['title']}”")
            if "dlpkey" in fields:
                details.append(f"dlpkey {a[code].get('dlpkey')} → {b[code].get('dlpkey')}")
            out.append(f"- ({code}) {title(b, code)}: " + "; ".join(details))
        out.append("")
    if diff["attributes_gained"] or diff["attributes_lost"]:
        out += ["**GS1 Digital Link data attributes**", "",
                f"- now offered: {', '.join(diff['attributes_gained']) or '—'}",
                f"- no longer offered: {', '.join(diff['attributes_lost']) or '—'}", ""]
    if diff["keys"]:
        out += ["**Primary keys or their qualifiers changed**: " + ", ".join(diff["keys"]), ""]
    problem = portal_check(new)
    out += ["**The portal's rules**: " + ("built from the new dictionary." if problem is None
                                          else f"cannot be built — {problem}. Code is needed before updating."), ""]
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        old = json.load(fh)
    with open(sys.argv[2], encoding="utf-8") as fh:
        new = json.load(fh)
    print(markdown(old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
