"""
The GS1 Barcode Syntax Dictionary as the portal uses it (Documentation/adr/0003-gs1-rules-from-the-dictionary.md).

The dictionary is a text file of GS1 (one line per AI or range of AIs: flags, the format as components with
their linters, attributes such as req=, ex= and dlpkey=, and the title). tools/gen_dictionary.py parses the
dictionary of the engine release written in docker-compose.yml and writes gs1_dictionary.json next to this
module; the portal reads only that file, so it needs neither the engine nor the text file to know the rules.

    {"release": "1.4.1", "dictionary": "2026-01-27",
     "ais": {"01": {"title": "GTIN", "flags": "*?",
                    "components": [{"type": "N", "min": 14, "max": 14, "optional": false,
                                    "linters": ["csum", "gcppos2"]}],
                    "req": [], "ex": [[["255"], ["37"]]], "dlpkey": [["22", "10", "21"], ["235"]]}, …}}

Ranges are expanded (3100-3105 → six AIs). "req" and "ex" keep every instance of the attribute (the dictionary
may repeat one) as a list of alternative groups, a group being AIs that go together ("01+21"). "dlpkey" is absent
for AIs that are not primary keys, [[]] for a key without qualifiers, otherwise the alternative ordered sequences
of qualifiers.
"""
import json
import os
import re

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gs1_dictionary.json")
FLAG_CHARS = set("*!?\"$%&'()+,-./:;<=>@[\\]^_`{|}~")
_COMPONENT = re.compile(r"^(\[)?([NXYZ])(\.\.)?(\d+)\]?(?:,(.*))?$")      # "N6,yymmd0", "[X..17]", "[N3],iso3166"
_RELEASE = re.compile(r"^#\s*Release:\s*(\S+)", re.M)


class DictionaryError(Exception):
    """The dictionary has a line the portal cannot read."""


def expand(ais: str) -> list[str]:
    """AIs of a range ("3100-3105" → 3100, 3101, …), or the AI itself."""
    if "-" not in ais:
        return [ais]
    first, last = ais.split("-")
    return [str(n).zfill(len(first)) for n in range(int(first), int(last) + 1)]


def component(token: str) -> dict:
    """ "N6,yymmd0" → {type N, min 6, max 6, optional False, linters [yymmd0]}; "[X..17]" → optional, 1 to 17."""
    match = _COMPONENT.match(token)
    if not match:
        raise DictionaryError(f"component {token!r} not understood")
    opening, kind, variable, length, linters = match.groups()
    length = int(length)
    return {"type": kind, "min": 1 if variable else length, "max": length, "optional": bool(opening),
            "linters": [x for x in (linters or "").split(",") if x]}


def _groups(value: str) -> list[list[str]]:
    """ "01+21,02,35nn" → [["01", "21"], ["02"], ["35nn"]]"""
    return [group.split("+") for group in value.split(",") if group]


def parse(text: str) -> dict:
    """The dictionary text → {"dictionary": its release date, "ais": {AI: entry}} (see the module's description)."""
    release = _RELEASE.search(text)
    ais: dict[str, dict] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        body, _, title = line.partition("#")
        tokens = body.split()
        codes, rest = tokens[0], tokens[1:]
        flags = rest.pop(0) if rest and set(rest[0]) <= FLAG_CHARS else ""
        entry = {"title": title.strip(), "flags": flags, "components": [], "req": [], "ex": []}
        for token in rest:
            if token == "dlpkey":
                entry["dlpkey"] = [[]]
            elif token.startswith("dlpkey="):
                entry["dlpkey"] = [[q for q in alternative.split(",") if q]
                                   for alternative in token.partition("=")[2].split("|")]
            elif token.startswith("req="):
                entry["req"].append(_groups(token[4:]))
            elif token.startswith("ex="):
                entry["ex"].append(_groups(token[3:]))
            elif "=" in token and not token.startswith("["):
                raise DictionaryError(f"line {number}: attribute {token!r} not understood")
            else:
                try:
                    entry["components"].append(component(token))
                except DictionaryError as exc:
                    raise DictionaryError(f"line {number}: {exc}") from None
        for code in expand(codes):
            ais[code] = json.loads(json.dumps(entry))          # one copy per AI of a range
    return {"dictionary": release.group(1) if release else None, "ais": dict(sorted(ais.items()))}


def dump(data: dict) -> str:
    """The file's text: one AI per line, so that a new release reads as a short diff."""
    lines = ["{", f'  "release": {json.dumps(data["release"])},', f'  "dictionary": {json.dumps(data["dictionary"])},',
             '  "ais": {']
    items = list(data["ais"].items())
    for index, (code, entry) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"    {json.dumps(code)}: {json.dumps(entry, ensure_ascii=False, sort_keys=True)}{comma}")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


_loaded = None


def load(path: str = PATH) -> dict:
    """gs1_dictionary.json (read once)."""
    global _loaded
    if path != PATH:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    if _loaded is None:
        with open(PATH, encoding="utf-8") as fh:
            _loaded = json.load(fh)
    return _loaded


def data_attributes(data: dict) -> dict[str, dict]:
    """The AIs permitted as GS1 Digital Link data attributes (flag "?"): {AI: {ai, title, components}}."""
    return {code: {"ai": code, "title": entry["title"], "components": entry["components"]}
            for code, entry in data["ais"].items() if "?" in entry["flags"]}


def path_ais(data: dict) -> dict[str, set[str]]:
    """For every primary key, the AIs that belong in its path (its qualifiers): {"01": {"22", "10", "21", "235"}}."""
    return {code: {q for alternative in entry["dlpkey"] for q in alternative}
            for code, entry in data["ais"].items() if "dlpkey" in entry}
