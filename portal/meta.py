"""
Record metadata kept by the portal: who created and who last changed each record, and when.

The resolver stores only the links, so the "record_meta" collection of the portal's database (store.py)
lets the record list show and filter by "last change". Records created or changed outside the portal simply
have no metadata.

"tenant" is the tenant the record belonged to at its last change through the portal (none for the operator):
the record list shows who changed a record only to users of that same tenant (Documentation/adr/0002-tenants.md,
section 3.6).

Key (the document's _id): see key(): "<GTIN-14>" and "<GTIN-14>/10/<lot>" for GTINs, "<AI>/<value>" for the
other keys. A failure here never stops a save: the caller logs it and carries on.
"""
from datetime import datetime, timezone

import store

FIELDS = ("createdAt", "createdBy", "updatedAt", "updatedBy", "tenant")


def key(anchor: str, qpath: str = "") -> str:
    """"09506000134352" for /01/… (the format used before other keys existed), "414/9506000134376"
    for the other primary keys; the qualifier path appended ("/10/L1/21/S1") for qualified records,
    so a batch keeps its earlier key "<GTIN-14>/10/<lot>"."""
    base = anchor[4:] if anchor.startswith("/01/") else anchor.lstrip("/")
    return base + (qpath or "")


def _meta():
    return store.col("record_meta")


def load() -> dict[str, dict]:
    """Every record's metadata ({record key: {createdAt, createdBy, updatedAt, updatedBy, tenant?}}); empty if none."""
    return {doc["_id"]: {k: doc[k] for k in FIELDS if k in doc} for doc in _meta().find()}


def _now() -> str:
    """Current UTC time, ISO 8601 with a Z, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def touch(anchor: str, qpath: str, user: str, tenant: str | None = None) -> None:
    """Records a creation or a change by `user` of `tenant` (None: the operator) now. A record that changes
    hands starts its metadata again, so its new owner never sees who changed it before."""
    now = _now()
    _meta().delete_one({"_id": key(anchor, qpath), "tenant": {"$ne": tenant}})
    update = {"$set": {"updatedAt": now, "updatedBy": user},
              "$setOnInsert": {"createdAt": now, "createdBy": user}}
    if tenant:
        update["$setOnInsert"]["tenant"] = tenant
    _meta().update_one({"_id": key(anchor, qpath)}, update, upsert=True)


def visible(info: dict | None, tenant: str | None) -> dict:
    """The metadata of a record as the users of `tenant` may see it: empty unless the last change through the
    portal was made by that same tenant (or, for the operator, by the operator)."""
    return info if info and info.get("tenant") == tenant else {}


def remove(anchor: str, qpath: str) -> None:
    """Forgets the metadata of a deleted record."""
    _meta().delete_one({"_id": key(anchor, qpath)})
