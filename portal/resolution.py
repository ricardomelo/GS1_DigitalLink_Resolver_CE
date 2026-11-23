"""
The strict mode for safety-critical link types (Documentation/adr/0022-answering-level.md, section 2.4), as the portal
keeps it: the field "strictSafety" of an organisation (collection "tenants"), set by its administrators and the server
administrators, and the setting "resolution.strict" ({"enabled", "updated", "updatedBy"}) for the keys no organisation
holds, set by the server administrators. Off by default. The resolver reads both (web_server/src/resolution.py).

With the strict mode on, a request for one of SAFETY_CRITICAL that names a batch or serial number is answered only by a
record naming that batch or serial number; otherwise the resolver answers 404 (Resolution-Match: withheld) and the
request log records the outcome "withheld".
"""
from datetime import datetime, timezone

import store

SETTING_STRICT = "resolution.strict"
TENANT_FIELD = "strictSafety"

# The five safety-critical link types of the GS1 Web vocabulary (ADR 0022, section 2.1); the resolver holds the same
# list (web_server/src/resolution.py) and a development test keeps the two equal.
SAFETY_CRITICAL = ("recallStatus", "safetyInfo", "epil", "smpc", "eifu")


class ResolutionError(ValueError):
    """A setting refused: the message code and its parameters."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def strict(tenant_id: str | None) -> dict:
    """{"strict", "types", "updated", "updatedBy"}: an organisation's strict mode, or the operator's for None."""
    if tenant_id is None:
        value = store.get_setting(SETTING_STRICT) or {}
        on, updated, by = bool(value.get("enabled")), value.get("updated"), value.get("updatedBy")
    else:
        doc = store.col("tenants").find_one({"_id": tenant_id}) or {}
        on, updated, by = bool(doc.get(TENANT_FIELD)), doc.get(TENANT_FIELD + "Updated"), doc.get(TENANT_FIELD + "By")
    return {"strict": on, "types": list(SAFETY_CRITICAL), "updated": store.iso(updated) if updated else None,
            "updatedBy": by}


def set_strict(tenant_id: str | None, enabled, user: str) -> tuple[dict, bool]:
    """Switches the strict mode of an organisation (or of the operator's scope, None) on or off; (the setting now,
    whether it changed)."""
    if not isinstance(enabled, bool):
        raise ResolutionError("resolution.invalid")
    before = strict(tenant_id)["strict"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if tenant_id is None:
        store.set_setting(SETTING_STRICT, {"enabled": enabled, "updated": store.iso(now), "updatedBy": user})
    else:
        store.col("tenants").update_one({"_id": tenant_id}, {"$set": {TENANT_FIELD: enabled,
                                                                      TENANT_FIELD + "Updated": now,
                                                                      TENANT_FIELD + "By": user}})
    return strict(tenant_id), before != enabled
