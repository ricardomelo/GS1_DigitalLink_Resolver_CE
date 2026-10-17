#!/usr/bin/env python3
"""
Writes Documentation/api-reference.md from portal/openapi.json (backlog item 9.11, Documentation/adr/0016-documentation-
and-feature-inventory.md): the tenant API's operations, their parameters, request bodies and answers, and its schemas,
as a manual for the people who connect an organisation's systems. The OpenAPI description stays the source; this page
is its readable form.

  python portal/tools/gen_api_reference.py [--out FILE] [--check]

--check writes nothing and exits with status 1 when the page differs from what openapi.json gives (the development
tests use it).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(REPO, "portal", "openapi.json")
PATH = os.path.join(REPO, "Documentation", "api-reference.md")
METHODS = ("get", "put", "post", "delete")


def _ref(spec: dict, node: dict) -> dict:
    """The object a $ref points to (one level), or the node itself."""
    if isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return target
    return node


def _name(node: dict) -> str:
    return node["$ref"].rsplit("/", 1)[-1] if isinstance(node, dict) and "$ref" in node else ""


def _cell(text) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _type(schema: dict) -> str:
    """A schema's type in a few words: a referenced schema's name, an array of it, or its JSON type."""
    if not schema:
        return ""
    if "$ref" in schema:
        name = _name(schema)
        return f"[{name}](#schema-{name.lower()})"
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = " or ".join(kind)
    if kind == "array":
        return "array of " + _type(schema.get("items") or {})
    extra = []
    if "enum" in schema:
        extra.append("one of " + ", ".join(f"`{v}`" for v in schema["enum"]))
    if "pattern" in schema:
        extra.append(f"pattern `{schema['pattern']}`")
    if "minimum" in schema or "maximum" in schema:
        extra.append(f"{schema.get('minimum', '…')} to {schema.get('maximum', '…')}")
    if "default" in schema:
        extra.append(f"default {schema['default']}")
    return (kind or "object") + (" (" + "; ".join(extra) + ")" if extra else "")


def generate(spec: dict) -> str:
    info = spec["info"]
    out = [f"# {info['title']} — reference", "",
           f"Version {info['version']}. {info.get('summary', '')}", "",
           "This page is generated from `portal/openapi.json` by `portal/tools/gen_api_reference.py` (do not edit it by "
           "hand); every installation serves the same description at `/portal/api/v1/openapi.json`. How to create keys "
           "and use them is in the operator's guide (`Documentation/extensions/README.md`, *Tenant API*) and the user "
           "guide (*API keys*).", "",
           "## How it works", "", info.get("description", ""), ""]
    out += ["## Operations", "", "| Method | Path | What it does |", "|---|---|---|"]
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method in item:
                op = item[method]
                out.append(f"| `{method.upper()}` | [`{path}`](#operation-{op['operationId'].lower()}) | "
                           f"{_cell(op.get('summary'))} |")
    out.append("")
    for path, item in spec["paths"].items():
        shared = item.get("parameters", [])
        for method in METHODS:
            if method not in item:
                continue
            op = item[method]
            out += [f"### Operation: {op['operationId']}", "", f"`{method.upper()} /portal/api/v1{path}` — {op.get('summary', '')}", ""]
            if op.get("description"):
                out += [op["description"], ""]
            params = [_ref(spec, p) for p in shared + op.get("parameters", [])]
            if params:
                out += ["| Parameter | In | Required | Type | Meaning |", "|---|---|---|---|---|"]
                for p in params:
                    out.append(f"| `{p['name']}` | {p['in']} | {'yes' if p.get('required') else 'no'} | "
                               f"{_cell(_type(p.get('schema') or {}))} | {_cell(p.get('description'))} |")
                out.append("")
            body = op.get("requestBody")
            if body:
                schema = (body.get("content", {}).get("application/json") or {}).get("schema") or {}
                out += [f"Request body ({'required' if body.get('required') else 'optional'}): {_type(schema)}.", ""]
            out += ["| Status | Answer |", "|---|---|"]
            for status, answer in op.get("responses", {}).items():
                resolved = _ref(spec, answer)
                schema = ((resolved.get("content") or {}).get("application/json") or {}).get("schema") or {}
                kind = _type(schema)
                out.append(f"| {status} | {_cell(resolved.get('description'))}{' — ' + _cell(kind) if kind else ''} |")
            out.append("")
    out += ["## Schemas", ""]
    for name, schema in spec["components"]["schemas"].items():
        out += [f"### Schema: {name}", ""]
        if schema.get("description"):
            out += [schema["description"], ""]
        required = set(schema.get("required") or [])
        props = schema.get("properties") or {}
        if props:
            out += ["| Field | Required | Type | Meaning |", "|---|---|---|---|"]
            for field, sub in props.items():
                out.append(f"| `{field}` | {'yes' if field in required else 'no'} | {_cell(_type(sub))} | "
                           f"{_cell(sub.get('description'))} |")
            out.append("")
        elif schema.get("type"):
            out += [f"Type: {_type(schema)}.", ""]
    out += ["## Authentication", ""]
    for name, scheme in spec["components"].get("securitySchemes", {}).items():
        out += [f"- `{name}`: {scheme.get('type')} {scheme.get('scheme', '')} — {_cell(scheme.get('description'))}"]
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--out", default=PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = generate(json.load(open(SPEC, encoding="utf-8")))
    if args.check:
        current = open(args.out, encoding="utf-8").read() if os.path.exists(args.out) else ""
        if current != text:
            print(f"{args.out} is not what {SPEC} gives: run portal/tools/gen_api_reference.py", file=sys.stderr)
            return 1
        print(f"{args.out} matches {SPEC}")
        return 0
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{args.out} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
