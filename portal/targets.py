"""
The hosts an organisation's targets may point to (Documentation/adr/0037-target-addresses.md, section 2.2): the field
"targetHosts" of an organisation (collection "tenants") and the setting "targets.hosts" for the keys no organisation
holds. Set by the organisation's administrators and the server administrators; empty (the default) allows any public
host, as before. With hosts listed, a record is saved only when each target's host is one of them or a name under one
(shop.example.com under example.com). The item's page (gs1:defaultLink to the resolver's own page) is never checked.

The forms no target may take (user information, address literals, names that are not public) are refused for every
organisation by gs1.target_host_problem(); this list narrows what remains.
"""
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

import gs1
import store

SETTING = "targets.hosts"
TENANT_FIELD = "targetHosts"
MAX_HOSTS = 50
MAX_HOST = 253


class TargetsError(ValueError):
    """A list refused: the message code and its parameters."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def ascii_host(host: str) -> str:
    """A host name in the form the browser sends (UTS #46 folded, lower case, Punycode for each label outside ASCII,
    without the root's dot), so that bücher.de and xn--bcher-kva.de compare equal."""
    host = unicodedata.normalize("NFKC", host or "").lower()
    host = host.replace("。", ".").replace("．", ".").replace("｡", ".").rstrip(".")
    labels = []
    for label in host.split("."):
        if label.isascii():
            labels.append(label)
            continue
        try:
            labels.append("xn--" + label.encode("punycode").decode("ascii"))
        except UnicodeError:
            labels.append(label)
    return ".".join(labels)


def clean(value) -> list[str]:
    """The list as stored: from a list of names or a text with one per line (commas and spaces also separate them);
    each a public host name (a leading '*.' or dot dropped, the same rule as a target's host), in its ASCII form,
    without repeats, sorted. Raises TargetsError (targets.invalid, targets.hostInvalid {host}, targets.tooMany {max})."""
    if value is None:
        return []
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = [part for item in value for part in item.replace(",", " ").split()]
    else:
        raise TargetsError("targets.invalid")
    kept = set()
    for item in items:
        name = item.strip()
        bare = name[2:] if name.startswith("*.") else name.lstrip(".")
        if not bare or len(bare) > MAX_HOST or gs1.host_problem(bare):    # no scheme, path, port, @ or address
            raise TargetsError("targets.hostInvalid", host=name[:MAX_HOST])
        kept.add(ascii_host(bare))
    if len(kept) > MAX_HOSTS:
        raise TargetsError("targets.tooMany", max=MAX_HOSTS)
    return sorted(kept)


def hosts(tenant_id: str | None, tenant: dict | None = None) -> dict:
    """{"hosts", "updated", "updatedBy", "max"}: an organisation's list (tenant: its document as tenants.load() gives
    it, to spare a read), or the operator's for None."""
    if tenant_id is None:
        value = store.get_setting(SETTING) or {}
        listed, updated, by = value.get("hosts"), value.get("updated"), value.get("updatedBy")
    else:
        doc = tenant if tenant is not None else (store.col("tenants").find_one({"_id": tenant_id}) or {})
        listed = doc.get(TENANT_FIELD)
        updated, by = doc.get(TENANT_FIELD + "Updated"), doc.get(TENANT_FIELD + "By")
    return {"hosts": list(listed or []), "updated": store.iso(updated) if updated else None, "updatedBy": by,
            "max": MAX_HOSTS}


def set_hosts(tenant_id: str | None, value, user: str) -> tuple[dict, bool]:
    """Replaces an organisation's list (or the operator's, None); (the list now, whether it changed)."""
    listed = clean(value)
    before = hosts(tenant_id)["hosts"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if tenant_id is None:
        store.set_setting(SETTING, {"hosts": listed, "updated": store.iso(now), "updatedBy": user})
    else:
        store.col("tenants").update_one({"_id": tenant_id}, {"$set": {TENANT_FIELD: listed,
                                                                      TENANT_FIELD + "Updated": now,
                                                                      TENANT_FIELD + "By": user}})
    return hosts(tenant_id), before != listed


def allowed(url: str, listed: list[str]) -> bool:
    """Whether a target's host is one of the listed names or under one; any host when the list is empty."""
    if not listed:
        return True
    host = ascii_host(urlsplit(url).hostname or "")
    return any(host == name or host.endswith("." + name) for name in listed)


def check(url: str, listed: list[str], position: int) -> None:
    """Raises gs1.ValidationError link.urlNotAllowed {position, url, host} when the host is not on the list."""
    if not allowed(url, listed):
        raise gs1.ValidationError("link.urlNotAllowed", position=position, url=url,
                                  host=urlsplit(url).hostname or "")
