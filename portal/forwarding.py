"""
Forwarding (Documentation/adr/0018-forwarding.md): the requests the resolver sends to another one, as the server
administrators set them in the portal.

  - The resolver of last resort: the setting "forwarding.fallback", {"enabled", "url"}; a key the resolver does not
    know goes there with its path and query string, when enabled. https://id.gs1.org until another address is set.
  - Prefix rules: the collection "forwarding_rules", {_id: prefix, target, mode, enabled, note, created, createdBy,
    updated, updatedBy}; every key of an enabled rule's prefix goes to its destination, the path kept ("path") or not
    ("fixed"), before the resolver's own records; the longest prefix wins.

The resolver reads both (web_server/src/forwarding.py). group() gives the overview's figures (ADR 0007).
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import store

SETTING_FALLBACK = "forwarding.fallback"
DEFAULT_FALLBACK = "https://id.gs1.org"
COLLECTION = "forwarding_rules"
MODES = ("path", "fixed")
MAX_URL = 500
MAX_NOTE = 200
PREFIX = re.compile(r"\d{3,12}")
COMPANY_AFTER_FIRST_DIGIT = {"01", "8006", "00", "8003"}   # as the request log's company part (requestlog)


class ForwardingError(ValueError):
    """A setting or rule refused: the message code and its parameters."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _col():
    return store.col(COLLECTION)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def company_part(ai: str, value: str) -> str:
    return value[1:] if ai in COMPANY_AFTER_FIRST_DIGIT else value


# ----------------------------------------------------------------------------------------------- destinations
def check_target(value, own_hosts: set[str]) -> str:
    """An https address, at most MAX_URL characters, that is not this installation (own_hosts: its own host and its
    organisations' verified domains, lower case): the address, trimmed."""
    url = str(value or "").strip()
    if not url:
        raise ForwardingError("forwarding.urlRequired")
    if len(url) > MAX_URL:
        raise ForwardingError("forwarding.urlTooLong", max=MAX_URL)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise ForwardingError("forwarding.urlInvalid") from None
    if parts.scheme != "https" or not host or any(c.isspace() for c in url) or parts.username or parts.password:
        raise ForwardingError("forwarding.urlInvalid")
    if host in own_hosts:
        raise ForwardingError("forwarding.urlSelf", host=host)
    return url


# ----------------------------------------------------------------------------------------------- the last resort
def fallback() -> dict:
    """{"enabled", "url", "default", "updated", "updatedBy"}: off, with GS1's address, until a server administrator
    sets it."""
    value = store.get_setting(SETTING_FALLBACK) or {}
    return {"enabled": bool(value.get("enabled")), "url": value.get("url") or DEFAULT_FALLBACK,
            "default": DEFAULT_FALLBACK, "updated": value.get("updated"), "updatedBy": value.get("updatedBy")}


def set_fallback(enabled, url, user: str, own_hosts: set[str]) -> dict:
    """Switches the resolver of last resort on or off, with its address (empty: GS1's)."""
    if not isinstance(enabled, bool):
        raise ForwardingError("forwarding.enabledInvalid")
    address = check_target(url, own_hosts) if str(url or "").strip() else DEFAULT_FALLBACK
    store.set_setting(SETTING_FALLBACK, {"enabled": enabled, "url": address, "updated": store.iso(_now()),
                                         "updatedBy": user})
    return fallback()


# ----------------------------------------------------------------------------------------------- prefix rules
def _public(doc: dict) -> dict:
    return {"prefix": doc["_id"], "target": doc.get("target", ""), "mode": doc.get("mode") or "path",
            "enabled": bool(doc.get("enabled")), "note": doc.get("note") or "",
            "created": store.iso(doc.get("created")), "createdBy": doc.get("createdBy"),
            "updated": store.iso(doc.get("updated")), "updatedBy": doc.get("updatedBy")}


def rules() -> list[dict]:
    """Every rule, by prefix."""
    return [_public(doc) for doc in _col().find({}).sort("_id", 1)]


def rule(prefix: str) -> dict:
    doc = _col().find_one({"_id": str(prefix or "")})
    if not doc:
        raise ForwardingError("forwarding.unknownRule", prefix=str(prefix or "")[:20])
    return _public(doc)


def _clean(data: dict, own_hosts: set[str]) -> dict:
    mode = str(data.get("mode") or "path")
    if mode not in MODES:
        raise ForwardingError("forwarding.modeInvalid")
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ForwardingError("forwarding.enabledInvalid")
    note = " ".join(str(data.get("note") or "").split())
    if len(note) > MAX_NOTE:
        raise ForwardingError("forwarding.noteTooLong", max=MAX_NOTE)
    return {"target": check_target(data.get("target"), own_hosts), "mode": mode, "enabled": enabled, "note": note}


def save_rule(prefix, data: dict, user: str, own_hosts: set[str], new: bool) -> tuple[dict, dict | None]:
    """Creates (new) or changes a rule; (the rule, the one before or None)."""
    prefix = str(prefix or "").strip()
    if not PREFIX.fullmatch(prefix):
        raise ForwardingError("forwarding.prefixInvalid")
    fields = _clean(data, own_hosts)
    before = _col().find_one({"_id": prefix})
    if new and before:
        raise ForwardingError("forwarding.prefixExists", prefix=prefix)
    if not new and not before:
        raise ForwardingError("forwarding.unknownRule", prefix=prefix)
    now = _now()
    if new:
        _col().insert_one({"_id": prefix, **fields, "created": now, "createdBy": user, "updated": now,
                           "updatedBy": user})
    else:
        _col().update_one({"_id": prefix}, {"$set": {**fields, "updated": now, "updatedBy": user}})
    return rule(prefix), (_public(before) if before else None)


def remove_rule(prefix) -> dict:
    found = rule(prefix)
    _col().delete_one({"_id": found["prefix"]})
    return found


def overlaps(prefix: str, tenant_list: list[dict]) -> list[str]:
    """The organisations whose prefixes overlap a rule's: their codes of that prefix are answered elsewhere."""
    return sorted(t["name"] for t in tenant_list
                  if any(p.startswith(prefix) or prefix.startswith(p) for p in t.get("prefixes") or []))


def rule_of(ai: str, value: str, every: list[dict]) -> str | None:
    """The prefix of the rule that matches a key now (the longest), or None."""
    part = company_part(ai, value)
    found = [r["prefix"] for r in every if part.startswith(r["prefix"])]
    return max(found, key=len) if found else None


# ----------------------------------------------------------------------------------------------- the overview
def group(keys: dict, total: dict, before: dict, top: int) -> dict:
    """The overview's Forwarding group for server administrators (ADR 0018, decision 7): keys, total and before as
    requestlog.collect() gives them for the period and the previous one."""
    every = rules()
    per_rule = {r["prefix"]: 0 for r in every}
    sent = []
    for (ai, value), entry in keys.items():
        n = entry["outcome"].get("forwarded", 0)
        if n:
            found = rule_of(ai, value, every)
            if found:
                per_rule[found] += n
        k = entry["outcome"].get("fallback", 0)
        if k:
            sent.append({"key": ai, "value": value, "anchor": f"/{ai}/{value}", "requests": k})
    sent.sort(key=lambda c: (-c["requests"], c["anchor"]))
    return {
        "fallback": {**{k: v for k, v in fallback().items() if k in ("enabled", "url")},
                     "requests": total["outcome"].get("fallback", 0),
                     "previous": before["outcome"].get("fallback", 0), "topCodes": sent[:top]},
        "rules": {"active": sum(1 for r in every if r["enabled"]), "total": len(every),
                  "requests": total["outcome"].get("forwarded", 0),
                  "previous": before["outcome"].get("forwarded", 0),
                  "byRule": [{"prefix": r["prefix"], "target": r["target"], "enabled": r["enabled"],
                              "requests": per_rule[r["prefix"]]} for r in every]},
    }
