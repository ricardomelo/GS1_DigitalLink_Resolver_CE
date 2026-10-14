#!/usr/bin/env python3
"""
Writes portal/engine_messages.json, the table of the GS1 Barcode Syntax Engine's English messages, from the
sources of an engine build (Documentation/adr/0003-gs1-rules-from-the-dictionary.md):

  python portal/tools/gen_engine_messages.py [engine directory] [--out FILE] [--check]

The engine directory is what tools/build-syntax-engine.sh makes; its source/ folder holds tr_EN.h (the engine's
message templates, printf style) and gs1syntaxdictionary.c / .h (the linters' messages, in the order of their
error codes). The portal recognises an engine message by these templates (engine_messages.py) and shows it in the
user's language: the keys engine.<CODE> and engine.lint.<CODE> of static/i18n.js. --check exits with status 1 when
the committed file differs. --summary OLD writes, in Markdown, which messages differ from those of the table OLD
(the ones that need a translation), for the issue of the weekly update check.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from engine_messages import PATH as OUT, SPEC as _SPEC  # noqa: E402

_DEFINE = re.compile(r'^#define\s+TR_EN_(\w+)\s+"((?:[^"\\]|\\.)*)"\s*$', re.M)


def _unescape(text: str) -> str:
    return bytes(text, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")


def parse_templates(tr_en: str) -> list[dict]:
    """[{"code", "template", "params"}] from tr_EN.h; params is the number of printf parameters."""
    out = []
    for code, text in _DEFINE.findall(tr_en):
        template = _unescape(text)
        out.append({"code": code, "template": template,
                    "params": sum(1 for spec in _SPEC.findall(template) if spec != "%%")})
    return out


def parse_linters(source_c: str, header: str) -> list[dict]:
    """[{"code", "text"}] of the linters' messages: the names of the gs1_lint_err_t values paired with the strings
    of gs1_lint_err_str, in order; unused (empty) slots are left out."""
    enum = re.search(r"typedef enum\s*\{(.*?)\}\s*gs1_lint_err_t;", header, re.S).group(1)
    names = re.findall(r"^\s*GS1_LINTER_(\w+)", enum, re.M)
    body = re.search(r"gs1_lint_err_str\[\]\s*=\s*\{(.*?)\n\};", source_c, re.S).group(1)
    texts = [_unescape(t) for t in re.findall(r'^\s*"((?:[^"\\]|\\.)*)"', body, re.M)]
    names = [n for n in names if not n.startswith("_")]
    if len(names) < len(texts):
        raise SystemExit(f"{len(texts)} linter messages but {len(names)} error codes")
    return [{"code": name, "text": text} for name, text in zip(names, texts) if text and name != "OK"]


def generate(engine_dir: str) -> str:
    """The text of engine_messages.json for the engine build in engine_dir."""
    source = os.path.join(engine_dir, "source")
    read = lambda name: open(os.path.join(source, name), encoding="utf-8").read()      # noqa: E731
    with open(os.path.join(engine_dir, "RELEASE"), encoding="utf-8") as fh:
        release = fh.read().strip()
    data = {"release": release, "messages": parse_templates(read("tr_EN.h")),
            "linters": parse_linters(read("gs1syntaxdictionary.c"), read("gs1syntaxdictionary.h"))}
    lines = ["{", f'  "release": {json.dumps(release)},']
    for name in ("messages", "linters"):
        items = data[name]
        lines.append(f'  "{name}": [')
        lines += [f"    {json.dumps(item, ensure_ascii=False)}{',' if i < len(items) - 1 else ''}" for i, item in enumerate(items)]
        lines.append("  ]," if name == "messages" else "  ]")
    lines += ["}", ""]
    return "\n".join(lines)


def compare(old: dict, new: dict) -> dict:
    """{"added", "removed", "changed"}: codes ("engine.X", "engine.lint.Y") whose English text is new, gone or
    different in the table new; added and changed ones need a translation in static/i18n.js."""
    def texts(data: dict) -> dict:
        out = {"engine." + m["code"]: m["template"] for m in data["messages"]}
        out.update({"engine.lint." + lint["code"]: lint["text"] for lint in data["linters"]})
        return out
    before, after = texts(old), texts(new)
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
            "changed": sorted(c for c in set(before) & set(after) if before[c] != after[c]), "texts": after}


def summary(old: dict, new: dict) -> str:
    """The comparison in Markdown, for the weekly update check's issue."""
    diff = compare(old, new)
    lines = [f"### Engine messages ({old['release']} → {new['release']})", ""]
    if not (diff["added"] or diff["removed"] or diff["changed"]):
        return "\n".join(lines + ["No engine message changed: every message keeps its translation.", ""])
    if diff["added"] or diff["changed"]:
        lines += ["Messages that need a translation in `portal/static/i18n.js` (both languages; the English one is "
                  "the engine's text):", ""]
        lines += [f"- `{code}`{' (changed)' if code in diff['changed'] else ''}: {diff['texts'][code]}"
                  for code in diff["added"] + diff["changed"]]
        lines.append("")
    if diff["removed"]:
        lines += ["Messages no longer in the engine (their translations can go): "
                  + ", ".join(f"`{code}`" for code in diff["removed"]), ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("engine_dir", nargs="?", default=os.environ.get("GS1_SYNTAX_ENGINE_DIR", ""))
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--summary", metavar="OLD", help="compare with the table OLD, in Markdown")
    args = parser.parse_args()
    if not args.engine_dir:
        parser.error("give the engine directory or set GS1_SYNTAX_ENGINE_DIR")
    text = generate(args.engine_dir)
    if args.summary:
        with open(args.summary, encoding="utf-8") as fh:
            print(summary(json.load(fh), json.loads(text)))
        return 0
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                same = fh.read() == text
        except OSError:
            same = False
        print(f"{args.out} is {'up to date' if same else 'NOT up to date'} with {args.engine_dir}")
        return 0 if same else 1
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
