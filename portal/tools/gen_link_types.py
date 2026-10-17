#!/usr/bin/env python3
"""
Writes portal/gs1_link_types.json from the GS1 Web Vocabulary (backlog item 9.4): every link type — every property
declared a sub-property of gs1:linkType — whose status is stable, with its English title and description, except
gs1:defaultLink and gs1:defaultLinkMulti, which the resolver uses for a record's default and are not offered as targets.
The portal then offers them all (gs1.py), grouped by what they are for and ordered by the key type.

  python portal/tools/gen_link_types.py [vocabulary .jsonld] [--out FILE] [--check]

The vocabulary is the JSON-LD file the GS1 Web Vocabulary publishes (https://ref.gs1.org/voc/, also in the GitHub
repository gs1/WebVoc as vX.Y/gs1Voc.jsonld); default $GS1_WEB_VOCABULARY. --check writes nothing and exits with
status 1 when the file in the repository differs from what the vocabulary gives (the development tests use it).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "gs1_link_types.json")
NOT_OFFERED = {"gs1:defaultLink", "gs1:defaultLinkMulti"}


def _ids(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [v.get("@id") if isinstance(v, dict) else v for v in values if v]


def _english(value) -> str:
    values = value if isinstance(value, list) else [value]
    for v in values:
        if isinstance(v, dict) and v.get("@language", "en") == "en":
            return " ".join(str(v.get("@value", "")).split())
        if isinstance(v, str):
            return " ".join(v.split())
    return ""


def generate(vocabulary: dict) -> str:
    """The text of gs1_link_types.json for a parsed vocabulary."""
    graph = vocabulary.get("@graph") or []
    ontology = next((n for n in graph if "owl:Ontology" in _ids(n.get("@type"))), {})
    version = str(ontology.get("owl:versionInfo") or ontology.get("schema:version") or "")
    types = []
    for node in graph:
        code = node.get("@id")
        if "gs1:linkType" not in _ids(node.get("rdfs:subPropertyOf")) or code in NOT_OFFERED:
            continue
        if node.get("sw:term_status", "stable") != "stable":
            continue
        types.append({"code": code, "title": _english(node.get("rdfs:label")),
                      "description": _english(node.get("rdfs:comment"))})
    types.sort(key=lambda t: t["code"].lower())
    data = {"source": "GS1 Web Vocabulary", "version": version, "linkTypes": types}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("vocabulary", nargs="?", default=os.environ.get("GS1_WEB_VOCABULARY", ""))
    parser.add_argument("--out", default=PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.vocabulary:
        parser.error("give the vocabulary's .jsonld or set GS1_WEB_VOCABULARY")
    with open(args.vocabulary, encoding="utf-8-sig") as fh:
        text = generate(json.load(fh))
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                same = fh.read() == text
        except OSError:
            same = False
        print(f"{args.out} is {'up to date' if same else 'NOT up to date'} with {args.vocabulary}")
        return 0 if same else 1
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
