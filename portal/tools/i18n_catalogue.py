#!/usr/bin/env python3
"""
The portal's message catalogues (Documentation/adr/0014-interface-languages.md): Portuguese and English live in
portal/static/i18n.js, every other language in portal/static/locales/<tag>.json with the same keys.

  python portal/tools/i18n_catalogue.py export [--out FILE]   the English catalogue as JSON (the translations' source)
  python portal/tools/i18n_catalogue.py check [TAG …]         every language file against English (all by default)

A language file must have exactly English's messages (the names of the GS1 Application Identifiers, "ai.*", are
Portuguese's only and stay out), none empty, each with the same {placeholders}, and a name and an explanation for
every link type. check exits with status 1 and lists the problems otherwise; the development tests run it.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "static")
I18N_JS = os.path.join(STATIC, "i18n.js")
LOCALES = os.path.join(STATIC, "locales")
SOURCE = "en-GB"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def builtin(path: str = I18N_JS) -> dict:
    """The catalogues written in i18n.js ({"pt-BR": {...}, "en-GB": {...}}): its object literal read as JSON once its
    comment lines and trailing commas are left out."""
    text = open(path, encoding="utf-8").read()
    start = text.index("const CATALOGUE = {") + len("const CATALOGUE = ")
    end = text.index("\n  };\n", start) + len("\n  }")
    body = "\n".join(line for line in text[start:end].splitlines() if not line.strip().startswith("//"))
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", body))


def english() -> dict:
    return builtin()[SOURCE]


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER.findall(text)))


def problems(source: dict, other: dict) -> list[str]:
    """What keeps a language file from matching the English catalogue."""
    found = []
    for key in source:
        if key not in other:
            found.append(f"missing: {key}")
    for key in other:
        if key not in source:
            found.append(f"unknown: {key}")
    for key, value in source.items():
        if key not in other:
            continue
        if key == "linkTypes":
            theirs = other[key] if isinstance(other[key], dict) else {}
            for code in value:
                pair = theirs.get(code)
                if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) and p.strip() for p in pair)):
                    found.append(f"link type without a name and an explanation: {code}")
            found += [f"unknown link type: {code}" for code in theirs if code not in value]
            continue
        text = other[key]
        if not isinstance(text, str) or not text.strip():
            found.append(f"empty: {key}")
        elif placeholders(text) != placeholders(value):
            found.append(f"placeholders of {key}: {placeholders(text)} instead of {placeholders(value)}")
    return found


def languages() -> list[str]:
    return sorted(name[:-5] for name in os.listdir(LOCALES) if name.endswith(".json")) if os.path.isdir(LOCALES) else []


def load(tag: str) -> dict:
    with open(os.path.join(LOCALES, f"{tag}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    out = sub.add_parser("export")
    out.add_argument("--out")
    chk = sub.add_parser("check")
    chk.add_argument("tags", nargs="*")
    args = parser.parse_args()
    if args.command == "export":
        text = json.dumps(english(), ensure_ascii=False, indent=1) + "\n"
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        else:
            sys.stdout.write(text)
        return 0
    source, failed = english(), False
    for tag in args.tags or languages():
        found = problems(source, load(tag))
        print(f"{tag}: {'complete' if not found else f'{len(found)} problem(s)'}")
        for line in found[:50]:
            print("  " + line)
        failed |= bool(found)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
