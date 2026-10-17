#!/usr/bin/env python3
"""
Writes portal/epc_schemes.json from the EPC Tag Data Translation artefacts the resolver decodes with
(web_server/src/tdt; backlog item 9.10, Documentation/adr/0010-label-studio.md, section 8): for every EPC scheme defined
before TDS 2.0 that has a GS1 Digital Link equivalent, the four levels the portal's encoder (portal/epc.py) reads —
GS1_DIGITAL_LINK (the record's key and qualifiers), BINARY, TAG_ENCODING and PURE_IDENTITY — with their options, fields
and rules, nothing else. The portal's image is built from portal/ alone, so it carries this copy; the resolver keeps the
complete artefacts.

  python portal/tools/gen_epc_schemes.py [TDT folder] [--out FILE] [--check]

--check writes nothing and exits with status 1 when the file in the repository differs from what the artefacts give
(the development tests use it).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PATH = os.path.join(os.path.dirname(HERE), "epc_schemes.json")
TDT = os.path.join(REPO, "web_server", "src", "tdt")
LEVELS = ("GS1_DIGITAL_LINK", "BINARY", "TAG_ENCODING", "PURE_IDENTITY")
FIELD_KEYS = ("seq", "name", "bitLength", "bitPadDir", "compaction", "characterSet", "decimalMinimum",
              "decimalMaximum", "length", "padChar", "padDir")


def _options(level: dict) -> list[dict]:
    options = level["option"]
    return options if isinstance(options, list) else [options]


def generate(folder: str) -> str:
    """The text of epc_schemes.json for a folder of TDT artefacts."""
    manifest = json.load(open(os.path.join(folder, "manifest.json"), encoding="utf-8"))
    schemes = []
    for entry in manifest["definitionFiles"]:
        if "+" in entry["scheme"]:
            continue                                    # TDS 2.0 '+' schemes: no tag URI, no partition (ADR 0010 §8)
        scheme = json.load(open(os.path.join(folder, entry["file"]), encoding="utf-8"))["tdt:epcTagDataTranslation"]["scheme"]
        levels = {level["type"]: level for level in scheme["level"]}
        if not all(name in levels for name in LEVELS):
            continue                                    # no GS1 Digital Link equivalent (GID-96, USDOD-96, ADI-var)
        out = {"name": scheme["name"], "optionKey": scheme.get("optionKey"), "tagLength": scheme.get("tagLength"),
               "levels": {}}
        for name in LEVELS:
            level = levels[name]
            out["levels"][name] = {
                "prefixMatch": level.get("prefixMatch"),
                "keyQualifiers": level.get("gs1DigitalLinkKeyQualifiers"),
                "rules": [{k: r[k] for k in ("type", "seq", "newFieldName", "function")} for r in level.get("rule", [])],
                "options": [{"optionKey": o["optionKey"], "pattern": o["pattern"], "grammar": o["grammar"],
                             "fields": [{k: f[k] for k in FIELD_KEYS if k in f} for f in o.get("field", [])]}
                            for o in _options(level)],
            }
        schemes.append(out)
    schemes.sort(key=lambda s: s["name"])
    return json.dumps({"source": "EPC Tag Data Translation artefacts, " + manifest.get("date", ""),
                       "schemes": schemes}, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("folder", nargs="?", default=TDT)
    parser.add_argument("--out", default=PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = generate(args.folder)
    if args.check:
        current = open(args.out, encoding="utf-8").read() if os.path.exists(args.out) else ""
        if current != text:
            print(f"{args.out} is not what {args.folder} gives: run portal/tools/gen_epc_schemes.py", file=sys.stderr)
            return 1
        print(f"{args.out} matches {args.folder}")
        return 0
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{args.out}: {len(json.loads(text)['schemes'])} schemes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
