"""
The installation's privacy notice (Documentation/adr/0017-privacy-notice.md): a text the server administrators write
in the portal, published as numbered versions that are never changed or deleted, shown to anyone — signed in or not —
at /portal/privacy and linked from the footer of every page of the installation.

Each version is one document of the portal's collection "privacy_notice":

    {_id: <version number, 1, 2…>, text, note, at, by}

The newest version is the notice in force. Until one is published, the page shows the default notice of the
catalogues (privacy.default, in the reader's language). The text is plain: blank lines separate paragraphs, a line
starting with "# " is a heading and "- " an item of a list, addresses become links; {operator} and {days} are replaced
by the operator's name and the days requests are kept, when the page shows it.
"""
from datetime import datetime, timezone

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

import store

COLLECTION = "privacy_notice"
MAX_TEXT = 50_000
MAX_NOTE = 200


class PrivacyError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _col():
    return store.col(COLLECTION)


def _public(doc: dict, with_text: bool = True) -> dict:
    out = {"version": doc["_id"], "at": store.iso(doc.get("at")), "by": doc.get("by"), "note": doc.get("note") or ""}
    if with_text:
        out["text"] = doc.get("text", "")
    return out


def current() -> dict | None:
    """The version in force, or None (the default notice applies)."""
    doc = _col().find_one({}, sort=[("_id", DESCENDING)])
    return _public(doc) if doc else None


def version(number) -> dict | None:
    """One version, or None when there is no such version."""
    try:
        number = int(str(number).strip())
    except (TypeError, ValueError):
        return None
    doc = _col().find_one({"_id": number})
    return _public(doc) if doc else None


def history() -> list[dict]:
    """Every version, newest first, without its text."""
    return [_public(doc, with_text=False) for doc in _col().find({}).sort("_id", DESCENDING)]


def publish(text, note, user: str) -> dict:
    """A new version (the previous ones stay as they were). The text is required (1 to MAX_TEXT characters, line
    breaks kept, other control characters refused); the note says what changed (up to MAX_NOTE characters)."""
    text = "" if text is None else str(text).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise PrivacyError("privacy.textRequired")
    if len(text) > MAX_TEXT:
        raise PrivacyError("privacy.textTooLong", max=MAX_TEXT)
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise PrivacyError("privacy.textInvalid")
    note = " ".join(str(note or "").split())
    if len(note) > MAX_NOTE:
        raise PrivacyError("privacy.noteTooLong", max=MAX_NOTE)
    last = _col().find_one({}, sort=[("_id", DESCENDING)])
    number = (last["_id"] if last else 0) + 1
    doc = {"_id": number, "text": text, "note": note, "at": datetime.now(timezone.utc).replace(tzinfo=None),
           "by": user}
    try:
        _col().insert_one(doc)
    except DuplicateKeyError:              # another administrator published the same number a moment before
        raise PrivacyError("privacy.conflict")
    return _public(doc)
