"""
Export limits set in the portal (Documentation/adr/0012-single-sign-on.md, section 8; backlog item 9.8): the most rows
one export may hold — the record spreadsheet, the requests' CSV, the tenant API's record listing — per role.

  - The installation's maximum ("exports.maximum" in the settings collection), set by the server administrators, caps
    every export of every organisation (its administrators' included); None (the default) is no limit.
  - Each organisation's own limits per role ("exportLimits" on its tenant document: {"reader": n, "editor": n,
    "api": n}), set by its administrators, never above the maximum; a role without one has the maximum.
  - The operator's users and API keys have their own limits ("exports.operator"), which no maximum caps; server
    administrators have no limit, also during support access.

0 means no export at all (the overview's export, figures rather than rows, is refused only then). PORTAL_EXPORT_LIMITS,
the earlier setting in .env, is read once (seed_from_env()): its reader and editor limits become the starting limits of
the operator and of every organisation, and the variable is then no longer read.
"""
import logging

import store
import users

log = logging.getLogger("portal.exports")

ROLES = ("reader", "editor", "api")       # the roles an organisation limits; its administrators have the maximum
MAX_ROWS = 10_000_000
SETTING_MAXIMUM = "exports.maximum"
SETTING_OPERATOR = "exports.operator"
SETTING_SEEDED = "exports.seeded"


class LimitError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _number(value, highest: int, code: str) -> int | None:
    """A limit typed on the page: None for empty, else a whole number from 0 to highest."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise LimitError(code, max=highest)
    text = str(value).strip()                     # a fraction ("2.5", "3.0") is not digits
    if not text.isdigit() or not 0 <= int(text) <= highest:
        raise LimitError(code, max=highest)
    return int(text)


def _clean(limits) -> dict[str, int]:
    """Only the known roles with a whole number of rows (what the database may hold from an earlier version)."""
    return {role: n for role, n in (limits or {}).items()
            if role in ROLES and isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= MAX_ROWS}


def maximum() -> int | None:
    """The installation's maximum rows per export in any organisation, or None (no limit)."""
    value = store.get_setting(SETTING_MAXIMUM)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_ROWS else None


def set_maximum(value) -> int | None:
    """Sets the installation's maximum (0 to MAX_ROWS, or None to lift it); returns it."""
    n = _number(value, MAX_ROWS, "exports.maximumInvalid")
    store.set_setting(SETTING_MAXIMUM, n)
    return n


def limits_of(tenant: dict | None) -> dict[str, int]:
    """An organisation's own limits (a tenant as tenants.load() gives it), or the operator's for None."""
    if tenant is None:
        return _clean(store.get_setting(SETTING_OPERATOR))
    return _clean(tenant.get("exportLimits"))


def set_limits(tenant_id: str | None, values: dict) -> dict[str, int]:
    """Sets an organisation's limits ({role: n or None}; a role left out keeps its limit), never above the maximum, or
    the operator's (tenant_id None). Returns the limits now kept."""
    if not isinstance(values, dict) or any(role not in ROLES for role in values):
        raise LimitError("exports.invalid", max=MAX_ROWS)
    highest = MAX_ROWS if tenant_id is None else (maximum() if maximum() is not None else MAX_ROWS)
    current = limits_of(None) if tenant_id is None else _clean(
        (store.col("tenants").find_one({"_id": tenant_id}) or {}).get("exportLimits"))
    for role, value in values.items():
        n = _number(value, highest, "exports.invalid")
        if n is None:
            current.pop(role, None)
        else:
            current[role] = n
    if tenant_id is None:
        store.set_setting(SETTING_OPERATOR, current)
    else:
        store.col("tenants").update_one({"_id": tenant_id}, {"$set": {"exportLimits": current}})
    return current


def effective(tenant: dict | None, role: str) -> int | None:
    """The most rows one export of this role may hold in this scope (None: no limit). An organisation's role has the
    lower of its own limit and the maximum (its administrators: the maximum); the operator's roles their own limit,
    its administrators (the server administrators) none."""
    own = None if role == "admin" else limits_of(tenant).get(role)
    if tenant is None:
        return own
    cap = maximum()
    found = [n for n in (own, cap) if n is not None]
    return min(found) if found else None


def describe(tenant: dict | None) -> dict:
    """The limits of a scope for the organisation's page: the maximum, the limits set and what applies to each role."""
    return {"maximum": None if tenant is None else maximum(), "limits": limits_of(tenant),
            "effective": {role: effective(tenant, role) for role in ("reader", "editor", "admin", "api")}}


def parse_env(text: str) -> dict[str, int]:
    """PORTAL_EXPORT_LIMITS ("reader:0,editor:20000"): the reader and editor limits it names; anything else ignored
    with a warning (administrators were never limited by it)."""
    limits = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        role, _, number = part.strip().partition(":")
        role, number = role.strip(), number.strip()
        if role not in users.ROLES or not number.isdigit():
            log.warning("PORTAL_EXPORT_LIMITS: %r ignored (role:number, the role one of %s)", part, ", ".join(users.ROLES))
            continue
        if role in ROLES:
            limits[role] = min(int(number), MAX_ROWS)
    return limits


def seed_from_env(text: str) -> bool:
    """Once per installation: the limits of PORTAL_EXPORT_LIMITS become those of the operator and of every
    organisation that has none of its own. Later starts only warn that the variable is no longer read. Returns
    whether it seeded now."""
    if store.get_setting(SETTING_SEEDED):
        if (text or "").strip():
            log.warning("PORTAL_EXPORT_LIMITS is no longer read: export limits are set in the portal "
                        "(the organisation's page, Exports). Remove it from .env.")
        return False
    limits = parse_env(text)
    if limits:
        store.set_setting(SETTING_OPERATOR, {**limits_of(None), **limits})
        store.col("tenants").update_many({"exportLimits": {"$exists": False}}, {"$set": {"exportLimits": limits}})
        log.info("PORTAL_EXPORT_LIMITS %s copied to the portal's export limits (read once).", limits)
    store.set_setting(SETTING_SEEDED, {"at": store.now(), "limits": limits})
    return bool(limits)
