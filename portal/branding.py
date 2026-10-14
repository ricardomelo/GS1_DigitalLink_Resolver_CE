"""
The brands of the item's page (Documentation/adr/0011-item-page.md): per GS1 Company Prefix, the name, logo and
colours the resolver shows on the page of an item's links, and whether it offers Verified by GS1. One document per
prefix in the "branding" collection of the portal's database (the resolver reads it, web_server/src/landing.py):

    {"_id": "7891234" | "*", "tenant": "t-…" (absent for the operator), "name": "Acme", "colour": "#002C6C",
     "accent": "#F26334", "verified": true, "logo": {"type": "image/png", "data": <bytes>, "etag": "…",
     "width", "height"}, "updated", "updatedBy"}

Rules: an organisation's administrators brand prefixes inside its own (one of them or a longer one); server
administrators the operator's (prefixes no organisation holds) and the installation's default "*". A logo is a PNG,
JPEG or WebP of at most MAX_LOGO_BYTES that Pillow can open (SVG is refused: it can carry scripts), at most
MAX_LOGO_PIXELS on each side.
"""
import base64
import binascii
import hashlib
import io
import re

from PIL import Image, UnidentifiedImageError

import store
import tenants
import users
from users import UserError

MAX_LOGO_BYTES = 200 * 1024
MAX_LOGO_PIXELS = 2000
TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
NAME_MAX = 60
DEFAULTS = {"colour": "#002C6C", "accent": "#F26334"}


def _col():
    return store.col("branding")


def public(doc: dict) -> dict:
    """What the screen shows (the logo's size and its address for the screen's preview, never the bytes; the resolver
    serves the same logo at /_brand/<prefix>)."""
    logo = doc.get("logo") or {}
    return {"prefix": doc["_id"], "name": doc.get("name") or "", "colour": doc.get("colour") or DEFAULTS["colour"],
            "accent": doc.get("accent") or DEFAULTS["accent"], "verified": doc.get("verified", True) is not False,
            "logo": {"type": logo.get("type"), "bytes": len(logo.get("data") or b""), "width": logo.get("width"),
                     "height": logo.get("height"), "url": f"api/branding/{doc['_id']}/logo?v={logo.get('etag')}"} if logo else None,
            "updated": store.iso(doc.get("updated")), "updatedBy": doc.get("updatedBy")}


def load(tenant: str | None, every: bool = False) -> list[dict]:
    query = {} if every else ({"tenant": tenant} if tenant else {"tenant": None})
    return sorted(_col().find(query), key=lambda d: (d["_id"] != "*", d["_id"]))


def _check_prefix(prefix: str, tenant: str | None, server_admin: bool) -> str:
    prefix = str(prefix or "").strip()
    if prefix == "*":
        if tenant or not server_admin:
            raise UserError("branding.prefixOutside")
        return prefix
    if not re.fullmatch(r"\d{4,12}", prefix):
        raise UserError("branding.prefixInvalid")
    tenant_list = tenants.load()
    if tenant:
        held = next((t.get("prefixes") or [] for t in tenant_list if t["id"] == tenant), [])
        if not any(prefix.startswith(h) for h in held):
            raise UserError("branding.prefixOutside")
    elif any(tenants.overlap(prefix, p) for t in tenant_list for p in t.get("prefixes") or []):
        raise UserError("branding.prefixOutside")
    return prefix


def read_logo(text) -> dict:
    """A logo sent as base64 (a data: URI or the bare data): checked and described."""
    raw = str(text or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise UserError("branding.logoInvalid")
    if not data or len(data) > MAX_LOGO_BYTES:
        raise UserError("branding.logoTooLarge", max=MAX_LOGO_BYTES // 1024)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            kind, (width, height) = image.format, image.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UserError("branding.logoInvalid")
    if kind not in TYPES:
        raise UserError("branding.logoInvalid")
    if width > MAX_LOGO_PIXELS or height > MAX_LOGO_PIXELS:
        raise UserError("branding.logoTooLarge", max=MAX_LOGO_BYTES // 1024)
    return {"type": TYPES[kind], "data": data, "etag": hashlib.sha256(data).hexdigest()[:16],
            "width": width, "height": height}


def save(prefix, data: dict, tenant: str | None, server_admin: bool, by: str) -> dict:
    """Creates or changes the brand of a prefix; "logo": base64 to replace it, "" to remove it, absent to keep it."""
    prefix = _check_prefix(prefix, tenant, server_admin)
    with users.locked():
        doc = _col().find_one({"_id": prefix}) or {"_id": prefix}
        if doc.get("tenant", None) != (tenant or None) and "name" in doc:
            raise UserError("branding.prefixOutside")
        name = " ".join(str(data.get("name", doc.get("name", "")) or "").split())
        if len(name) > NAME_MAX or not name.isprintable():
            raise UserError("branding.nameInvalid", max=NAME_MAX)
        change = {"name": name, "updated": store.now(), "updatedBy": by,
                  "verified": bool(data.get("verified", doc.get("verified", True)))}
        for field in ("colour", "accent"):
            value = data.get(field, doc.get(field) or DEFAULTS[field])
            if not COLOUR.match(str(value or "")):
                raise UserError("branding.colourInvalid")
            change[field] = str(value).upper()
        if "logo" in data:
            change["logo"] = read_logo(data["logo"]) if data["logo"] else None
        if tenant:
            change["tenant"] = tenant
        _col().update_one({"_id": prefix}, {"$set": change}, upsert=True)
        return _col().find_one({"_id": prefix})


def logo(prefix, tenant: str | None) -> dict | None:
    """The stored logo of a brand of the scope (None when there is none, or the brand is someone else's)."""
    doc = _col().find_one({"_id": str(prefix)})
    if not doc or doc.get("tenant", None) != (tenant or None):
        return None
    return doc.get("logo") or None


def remove(prefix, tenant: str | None, server_admin: bool) -> dict:
    prefix = _check_prefix(prefix, tenant, server_admin)
    doc = _col().find_one({"_id": prefix, "tenant": tenant} if tenant else {"_id": prefix, "tenant": None})
    if not doc:
        raise UserError("branding.unknown")
    _col().delete_one({"_id": prefix})
    return doc
