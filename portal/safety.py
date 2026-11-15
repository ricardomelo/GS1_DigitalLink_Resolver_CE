"""
The portal's warnings on safety-critical link types (Documentation/adr/0022-answering-level.md, section 2.5): given a
record about to be saved and the other records of its key, what a request for that record would receive from a less
specific level, and which batch or serial values are close to an existing one. A warning never refuses a save; the
editor, the tenant API (answer "warnings") and the spreadsheet import's preview show the same list.

Each warning is {"code", "params"}, its text in every language under the same code (portal/static/i18n.js, locales/):

- "warning.walkUp": a qualified record lacks safety-critical types that a less specific record of the key holds:
  {"types": ["gs1:recallStatus", …], "level": the qualifiers of the level that answers ([["10", "L1"]]; [] for the
  key's own record), "strict": whether the strict mode
  withholds them (404) instead of answering with that level's links};
- "warning.productLevel": a record of the key alone holds safety-critical types while the key has batch or serial
  records: {"types", "count" (batch or serial records), "values": the qualifiers of the first five, "strict"};
- "warning.nearDuplicate": a batch or serial value equal to another of the key's but for letter case, spaces,
  hyphens, dots, slashes, or O and I for 0 and 1: {"ai", "value", "existing"}.
"""
from resolution import SAFETY_CRITICAL

import gs1

# The qualifiers whose records the strict mode requires (a batch, a serial number, a TPX), and the values compared for
# near duplicates: the same three
STRICT_QUALIFIERS = ("10", "21", "235")
SAFETY_TYPES = tuple("gs1:" + code for code in SAFETY_CRITICAL)
_FOLD = str.maketrans({"O": "0", "I": "1", " ": None, "-": None, ".": None, "/": None})
_UNITS = ("21", "235")
_SHOWN = 5


def fold(value: str) -> str:
    """A batch or serial value as compared for near duplicates: upper case, without spaces, hyphens, dots and slashes,
    the letters O and I read as the digits 0 and 1."""
    return str(value).upper().translate(_FOLD)


def safety_types(links) -> list[str]:
    """The safety-critical link types among links ({"linktype"} as stored, or {"linkType"} as the editor sends them),
    in the order of SAFETY_TYPES."""
    held = {link.get("linktype") or link.get("linkType") for link in links or [] if isinstance(link, dict)}
    return [t for t in SAFETY_TYPES if t in held]


def _template(pairs) -> bool:
    return any(str(v).startswith("{") for _, v in pairs)


def _specificity(pairs) -> tuple[bool, int]:
    """The resolver's order of the levels that apply to a request (web_logic.read_document): a unit's record first."""
    return any(q in _UNITS for q, _ in pairs), len(pairs)


def check(pairs, informative, links, entries, strict: bool) -> list[dict]:
    """The warnings for a record of a key: its qualifiers and informative ones (lists of (AI, value)), the links it
    will hold, the key's records as the data entry API returns them (the record itself among them or not) and whether
    the strict mode is on for the key's organisation."""
    pairs, informative = [tuple(p) for p in pairs], [tuple(p) for p in informative or []]
    own = set(pairs)
    others = [(gs1.pairs_from(e.get("qualifiers")), e) for e in entries or []]
    others = [(p, e) for p, e in others if set(p) != own and not _template(p)]
    warnings = []
    held = set(safety_types(links))
    requested = own | set(informative)

    if pairs:
        # Section 2.5.9: a request for this record walks up to the records whose qualifiers it carries
        broader = sorted(((p, e) for p, e in others if set(p) <= requested),
                         key=lambda item: _specificity(item[0]), reverse=True)
        answered, by_level = set(held), []
        for p, entry in broader:
            missing = [t for t in safety_types(entry.get("links")) if t not in answered]
            if missing:
                answered.update(missing)
                # withheld when the level names none of the request's batch or serial numbers
                withheld = strict and any(q in STRICT_QUALIFIERS for q, _ in requested) and \
                    not any(q in STRICT_QUALIFIERS for q, _ in p)
                by_level.append({"code": "warning.walkUp",
                                 "params": {"types": missing, "level": [list(q) for q in p],
                                            "strict": bool(withheld)}})
        warnings.extend(by_level)
    elif held:
        qualified = [p for p, _ in others if any(q in STRICT_QUALIFIERS for q, _ in p)]
        if qualified:
            warnings.append({"code": "warning.productLevel",
                             "params": {"types": sorted(held, key=SAFETY_TYPES.index), "count": len(qualified),
                                        "values": [[list(q) for q in p] for p in qualified[:_SHOWN]],
                                        "strict": bool(strict)}})

    seen = set()
    for ai, value in pairs + informative:
        if ai not in STRICT_QUALIFIERS or str(value).startswith("{"):
            continue
        for p, entry in others:
            for q, v in p + gs1.pairs_from(entry.get("informativeQualifiers")):
                if q == ai and v != value and fold(v) == fold(value) and (ai, v) not in seen:
                    seen.add((ai, v))
                    warnings.append({"code": "warning.nearDuplicate",
                                     "params": {"ai": ai, "value": value, "existing": v}})
    return warnings


def lacking(lines) -> list[dict]:
    """The batch and serial records, among the record summaries of one scope (GET /summary?links=true), that lack a
    safety-critical type a less specific record of their key holds: [{"anchor", "qualifiers", "types"}]
    (the count on the organisation's Resolution tab)."""
    by_key: dict[str, list[dict]] = {}
    for line in lines:
        by_key.setdefault(line.get("anchor") or "", []).append(line)
    found = []
    for anchor, entries in sorted(by_key.items()):
        for entry in entries:
            pairs = gs1.pairs_from(entry.get("qualifiers"))
            informative = gs1.pairs_from(entry.get("informativeQualifiers"))
            if not any(q in STRICT_QUALIFIERS for q, _ in pairs) or _template(pairs):
                continue
            types = [t for w in check(pairs, informative, entry.get("links"), entries, False)
                     if w["code"] == "warning.walkUp" for t in w["params"]["types"]]
            if types:
                found.append({"anchor": anchor, "qualifiers": [list(p) for p in pairs], "types": types})
    return found
