"""
The shape of the JSON bodies the portal accepts (Documentation/adr/0040-request-bodies.md, findings F-023 and F-029).

Every write to the portal's API (/portal/api/…, the organisations' API /portal/api/v1/… included) goes through
problem() before its route runs: the body must be one JSON object, and each field named in FIELDS must hold a value of
the kinds listed there, at the top of the body and inside the rows of a list of objects ("links": [{"url": …}]). A
body that is not a JSON object is answered 400 request.jsonInvalid; a field of another kind 422 request.fieldInvalid
with its path ("links.2.url"). So a route never meets a number where it reads a text, a list where it looks a value up
in a set, or an object where it builds a database filter ({"$ne": null} as a user name or a job's token).

null is accepted for every field: the routes read a field with .get(), for which null and absent are the same. A field
that is not in FIELDS is not checked: its route already copes with any value and answers with its own message code,
which the tests expect (the retention's days and sizes, the export limits, the notification choices, "enabled" of
forwarding and strict resolution, the hosts of targets). A new field read
with .get() belongs here unless its route checks the value's kind itself; dev-tests/portal/test_malformed.py sends
every kind to every write route and fails on any answer 500.
"""
from collections.abc import Mapping

TEXT, FLAG, LIST, TEXTS, OBJECTS, NAMES, ALIASES, RECORD, LABELS = (
    "text", "flag", "list", "texts", "objects", "names", "aliases", "record", "labels")

# The kinds each field may hold (a flag is true or false, never 0 or 1). TEXTS: a list of texts; OBJECTS: a list of
# objects whose fields are checked by this same table; NAMES: an object whose values are texts (qualifier values by AI,
# a spreadsheet's column headers); RECORD: an object whose
# fields are checked by this table (the key's own record sent with a qualified one); LABELS: the texts of a spreadsheet
# or an overview in the user's language, checked by LABEL_FIELDS (ALIASES: an object of lists of texts, such as a link type's name and description).
FIELDS: dict[str, tuple[str, ...]] = {
    **{name: (TEXT,) for name in (
        "accent", "action", "ai", "clientId", "clientSecret", "colour", "content", "currentPassword",
        "defaultLinkType", "description", "domain", "email", "filename", "format", "icon", "issuer", "key", "language",
        "linkType", "login", "logo", "mode", "name", "newPassword", "note", "password", "prefix", "reason", "role",
        "scope", "stem", "target", "tenant", "text", "title", "token", "url", "username", "value")},
    **{name: (FLAG,) for name in (
        "all", "createKeyRecords", "disabled", "emailVerifiedOptional", "invite", "landingPage",
        "passwordOff", "ssoForget", "verified")},
    **{name: (TEXTS,) for name in ("defaultFor", "hreflang", "only", "prefixes", "scopes", "urls")},
    "context": (LIST,),
    "domains": (TEXT, TEXTS),
    "links": (OBJECTS,),
    "attributes": (OBJECTS,),
    "labels": (LABELS,),
    "qualifiers": (TEXT, NAMES),
    "keyRecord": (RECORD,),
}
# The parts of "labels" (app.js sheetLabels(), overviewLabels() and the import's): any other part is a text.
LABEL_FIELDS: dict[str, tuple[str, ...]] = {
    **{name: (NAMES,) for name in ("headers", "sheets", "languages", "keys")},
    "linkTypes": (NAMES, ALIASES), "aliases": (ALIASES,), "yes": (TEXT, TEXTS), "no": (TEXT, TEXTS), "yesWords": (TEXTS,), "noWords": (TEXTS,),
}
DEPTH = 3       # objects inside objects: a record's links (2) and the key record's (3); deeper is never sent


def _is(value, kind: str) -> bool:
    if kind == TEXT:
        return isinstance(value, str)
    if kind == FLAG:
        return isinstance(value, bool)
    if kind == LIST:
        return isinstance(value, list)
    if kind == TEXTS:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if kind == OBJECTS:
        return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)
    if kind == NAMES:
        return isinstance(value, Mapping) and all(isinstance(item, str) for item in value.values())
    if kind == ALIASES:
        return isinstance(value, Mapping) and all(_is(item, TEXTS) for item in value.values())
    if kind == LABELS:
        return isinstance(value, Mapping) and all(
            any(_is(item, k) for k in LABEL_FIELDS.get(part, (TEXT,))) for part, item in value.items())
    return isinstance(value, Mapping)       # RECORD


def field_problem(body: Mapping, path: str = "", depth: int = 1) -> str | None:
    """The path of the first field of the object whose value is of a kind its table entry does not allow, or None."""
    for name, value in body.items():
        kinds = FIELDS.get(name)
        if value is None or kinds is None:
            continue
        where = f"{path}{name}"
        if not any(_is(value, kind) for kind in kinds):
            return where
        rows = value if OBJECTS in kinds and isinstance(value, list) else [value] if RECORD in kinds else []
        for position, row in enumerate(rows, start=1):
            if depth >= DEPTH:
                return where
            found = field_problem(row, f"{where}.{position}." if OBJECTS in kinds else f"{where}.", depth + 1)
            if found:
                return found
    return None


def problem(body) -> tuple[str, int, dict] | None:
    """Why a parsed JSON body cannot reach a route — (message code, HTTP status, parameters) — or None."""
    if not isinstance(body, dict):
        return "request.jsonInvalid", 400, {}
    where = field_problem(body)
    return ("request.fieldInvalid", 422, {"field": where}) if where else None
