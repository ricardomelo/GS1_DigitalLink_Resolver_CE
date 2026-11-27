"""
A record's revision (ADR 0058): the first 20 hexadecimal digits of the SHA-256 of what the record holds, as GET
/api/{AI}/{value} gives it (one v3 entry per record) - its qualifiers, item description, links and informative
qualifiers, in canonical JSON; the key's default link type and the anchor left out. The data entry API has the same
function (data_entry_server/src/revision.py); dev-tests/portal/test_record_revision.py holds the two equal. Nothing is
stored.
"""
import hashlib
import json
from typing import Any

FIELDS = (('qualifiers', list), ('itemDescription', str), ('links', list), ('informativeQualifiers', list))


def of(entry: dict[str, Any] | None) -> str | None:
    """The revision of one v3 entry; None for no entry (a record that does not exist)."""
    if entry is None:
        return None
    content = {name: entry.get(name) or empty() for name, empty in FIELDS}
    text = json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]


def tags(header: str | None) -> list[str] | None:
    """The entity tags of an If-Match or If-None-Match header: ['*'], a list of revisions (W/ and quotes optional), or
    None when the header is absent or empty."""
    if header is None or not header.strip():
        return None
    out = []
    for part in header.split(','):
        part = part.strip()
        if part.startswith('W/'):
            part = part[2:]
        part = part.strip().strip('"')
        if part:
            out.append(part)
    return out or None


def problem(entry: dict[str, Any] | None, if_match: list[str] | None, if_none_match: list[str] | None) -> bool:
    """Whether the preconditions fail for the record as it is now (entry None: it does not exist)."""
    current = of(entry)
    if if_match is not None:
        if current is None:
            return True
        if '*' not in if_match and current not in if_match:
            return True
    if if_none_match is not None and current is not None:
        if '*' in if_none_match or current in if_none_match:
            return True
    return False
