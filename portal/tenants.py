"""
Tenants: organisations that own GS1 Company Prefixes (Documentation/adr/0002-tenants.md). One document per
tenant in the "tenants" collection of the portal's database (store.py):

    {"_id": "t-3f9a1c0b2e7d", "name": "Acme Foods", "prefixes": ["7891234"], "disabled": false,
     "created": "…", "createdBy": "admin"}

A record belongs to the tenant whose prefix starts the company part of its key (gs1.company_part); ownership is
derived, never stored. Whatever no tenant holds belongs to the operator, whose users are the users without a
tenant and whose administrators are the server administrators.

Rules (checked under the users lock, because they cross the users and tenants collections):
  - a prefix belongs to one tenant at most: no prefix of a tenant may start, or be started by, a prefix of
    another tenant; within one tenant a prefix covered by another is redundant and refused;
  - a prefix may not be given to a tenant while an operator user is limited to a prefix inside it, nor taken
    from a tenant while one of its users is limited to a prefix inside it;
  - a tenant with users cannot be removed.
"""
import re
import secrets
from datetime import datetime, timezone

import gs1
import store
import users
from users import UserError

NAME_MAX = 80
FIELDS = ("name", "prefixes", "disabled", "created", "createdBy")


def _now() -> str:
    """Current UTC time, ISO 8601 with a Z, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tenants():
    return store.col("tenants")


def _tenant(doc: dict) -> dict:
    """A tenant as the rest of the portal sees it: {"id", "name", "prefixes", "disabled", "created", "createdBy",
    "logDays", "exportLimits"} (logDays: how long its requests are kept, None for the installation's; requestlog.py;
    exportLimits: its own limits on exports per role, exportlimits.py)."""
    return {"id": doc["_id"], "name": doc.get("name", ""), "prefixes": list(doc.get("prefixes") or []),
            "disabled": bool(doc.get("disabled")), "created": doc.get("created"), "createdBy": doc.get("createdBy"),
            "logDays": doc.get("logDays"), "exportLimits": dict(doc.get("exportLimits") or {})}


def load() -> list[dict]:
    """Every tenant, by name."""
    return sorted((_tenant(doc) for doc in _tenants().find()), key=lambda t: t["name"].casefold())


def get(tenant_id) -> dict | None:
    """One tenant, or None."""
    if not tenant_id:
        return None
    doc = _tenants().find_one({"_id": str(tenant_id)})
    return _tenant(doc) if doc else None


def find(name_or_id: str) -> dict | None:
    """A tenant by id or by name (ignoring case and surrounding spaces), or None (command line)."""
    wanted = clean_name(name_or_id, check=False).casefold()
    return get(name_or_id) or next((t for t in load() if t["name"].casefold() == wanted), None)


def owner(anchor: str, tenants: list[dict]) -> str | None:
    """Id of the tenant that holds the anchor's GS1 Company Prefix, or None (the operator). Prefixes of different
    tenants never overlap, so at most one tenant matches."""
    part = gs1.company_part(anchor)
    if not part:
        return None
    for tenant in tenants:
        if any(part.startswith(p) for p in tenant["prefixes"]):
            return tenant["id"]
    return None


def overlap(a: str, b: str) -> bool:
    """Whether two prefixes overlap: one starts with the other."""
    return a.startswith(b) or b.startswith(a)


def clean_name(value, check: bool = True) -> str:
    """A tenant name as stored: invisible characters removed, spaces collapsed; 2 to NAME_MAX printable characters."""
    name = re.sub(r"\s+", " ", gs1.without_invisible(str(value or ""))).strip()
    if check and not (2 <= len(name) <= NAME_MAX and name.isprintable()):
        raise UserError("tenants.nameInvalid", max=NAME_MAX)
    return name


def _check_prefixes(tenant_id: str | None, prefixes: list[str], previous: list[str]) -> None:
    """Refuses prefixes that are redundant within the tenant, overlap another tenant's, would leave an operator
    user without records (prefixes given) or a user of the tenant limited to a prefix the tenant no longer has
    (prefixes taken)."""
    for i, a in enumerate(prefixes):
        for b in prefixes[i + 1:]:
            if overlap(a, b):
                raise UserError("tenants.prefixRedundant", prefix=max(a, b, key=len), covered=min(a, b, key=len))
    for doc in _tenants().find({"_id": {"$ne": tenant_id}}):
        for theirs in doc.get("prefixes") or []:
            for mine in prefixes:
                if overlap(mine, theirs):
                    raise UserError("tenants.prefixOverlap", prefix=mine, other=theirs, tenant=doc.get("name", ""))
    added = [p for p in prefixes if p not in previous]
    if added:
        held = sorted(doc["_id"] for doc in users._users().find({"tenant": None})
                      if any(up.startswith(p) for up in doc.get("prefixes") or [] for p in added))
        if held:
            raise UserError("tenants.prefixOperatorUser", users=", ".join(held))
    removed = [p for p in previous if p not in prefixes]
    if removed and tenant_id:
        stranded = sorted(doc["_id"] for doc in users._users().find({"tenant": tenant_id})
                          if any(not any(up.startswith(p) for p in prefixes) for up in doc.get("prefixes") or []))
        if stranded:
            raise UserError("tenants.prefixInUse", users=", ".join(stranded))


def _name_taken(name: str, tenant_id: str | None) -> bool:
    wanted = name.casefold()
    return any(doc.get("name", "").casefold() == wanted for doc in _tenants().find({"_id": {"$ne": tenant_id}}))


def create(name: str, prefixes, by: str) -> dict:
    """Creates a tenant; returns it."""
    name = clean_name(name)
    prefixes = users.clean_prefixes(prefixes)
    with users.locked():
        if _name_taken(name, None):
            raise UserError("tenants.nameExists", name=name)
        _check_prefixes(None, prefixes, [])
        doc = {"_id": "t-" + secrets.token_hex(6), "name": name, "prefixes": prefixes, "disabled": False,
               "created": _now(), "createdBy": by}
        _tenants().insert_one(doc)
    return _tenant(doc)


def update(tenant_id: str, name=None, prefixes=None, disabled=None) -> tuple[dict, dict]:
    """Renames a tenant, changes its prefixes or its state; returns (before, after)."""
    with users.locked():
        before = get(tenant_id)
        if not before:
            raise UserError("tenants.unknown")
        after = dict(before)
        if name is not None:
            after["name"] = clean_name(name)
            if _name_taken(after["name"], tenant_id):
                raise UserError("tenants.nameExists", name=after["name"])
        if prefixes is not None:
            after["prefixes"] = users.clean_prefixes(prefixes)
            _check_prefixes(tenant_id, after["prefixes"], before["prefixes"])
        if disabled is not None:
            after["disabled"] = bool(disabled)
        _tenants().update_one({"_id": tenant_id}, {"$set": {k: after[k] for k in ("name", "prefixes", "disabled")}})
    return before, after


def remove(tenant_id: str) -> dict:
    """Removes a tenant without users; its prefixes go back to the operator. Returns the tenant removed."""
    with users.locked():
        tenant = get(tenant_id)
        if not tenant:
            raise UserError("tenants.unknown")
        count = users._users().count_documents({"tenant": tenant_id})
        if count:
            raise UserError("tenants.notEmpty", count=count)
        _tenants().delete_one({"_id": tenant_id})
    return tenant
