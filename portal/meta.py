"""
Record metadata kept by the portal: who created and who last changed each record, and when.

The resolver stores only the links, so the "record_meta" collection of the portal's database (store.py)
lets the record list show and filter by "last change". Records created or changed outside the portal simply
have no metadata.

Key (the document's _id): see key(): "<GTIN-14>" and "<GTIN-14>/10/<lot>" for GTINs, "<AI>/<value>" for the
other keys. A failure here never stops a save: the caller logs it and carries on.
"""
from datetime import datetime, timezone

import store

FIELDS = ("createdAt", "createdBy", "updatedAt", "updatedBy")


def key(anchor: str, qpath: str = "") -> str:
    """"09506000134352" for /01/… (the format used before other keys existed), "414/9506000134376"
    for the other primary keys; the qualifier path appended ("/10/L1/21/S1") for qualified records,
    so a batch keeps its earlier key "<GTIN-14>/10/<lot>"."""
    base = anchor[4:] if anchor.startswith("/01/") else anchor.lstrip("/")
    return base + (qpath or "")


def _meta():
    return store.col("record_meta")


def load() -> dict[str, dict]:
    """Every record's metadata ({record key: {createdAt, createdBy, updatedAt, updatedBy}}); empty if none."""
    return {doc["_id"]: {k: doc[k] for k in FIELDS if k in doc} for doc in _meta().find()}


def _now() -> str:
    """Current UTC time, ISO 8601 with a Z, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def touch(anchor: str, qpath: str, user: str) -> None:
    """Records a creation or a change by `user` now."""
    now = _now()
    _meta().update_one({"_id": key(anchor, qpath)},
                       {"$set": {"updatedAt": now, "updatedBy": user},
                        "$setOnInsert": {"createdAt": now, "createdBy": user}}, upsert=True)


def remove(anchor: str, qpath: str) -> None:
    """Forgets the metadata of a deleted record."""
    _meta().delete_one({"_id": key(anchor, qpath)})
