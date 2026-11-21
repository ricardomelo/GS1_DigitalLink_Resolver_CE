"""
The organisations' own domains in the QR code (Documentation/adr/0009-tenant-domains.md; GS1 Digital Link URI Syntax
1.7, section 4.11). One document per domain in the "domains" collection of the portal's database:

    {"_id": "id.acme.example", "name": "id.acme.example", "tenant": "t-…" (absent for the operator),
     "mode": "direct" | "redirect", "stem": "" | "/gs1", "defaultFor": ["7891234"], "token": "<32 hex>",
     "verified": bool, "verifiedAt", "seenAt", "lapsedAt", "expiresAt" (unverified only),
     "check": {"at", "ok", "problem", "detail"}, "created", "createdBy"}

A domain is proved by a DNS TXT record "_gs1resolver.<domain>" holding "gs1resolver-verify=<token>"
(Documentation/adr/0035-domain-claims-and-lapsed-proofs.md). Until then it is a claim: several organisations may
claim the same name, each under the _id "<name> <tenant or ->" (pending_id()), and the claim is deleted by its TTL
PENDING after it was made. The first claim proved becomes the domain, under the _id "<name>", and the other claims of
the name go. The daily housekeeping looks again at every verified domain's record (recheck_all()); missing for LAPSE,
the domain is lapsed: still served, but no longer offered for labels, its administrators are told, and another
organisation's claim that proves the name takes it over. Seen again, it is no longer lapsed. The resolver
(web_server/src/domains.py) reads the verified "direct" domains and answers on them for their organisation's prefixes
only; labels carry the default domain of the record's prefix, or the one chosen.

Rules: a lower-case host name with at least two labels, not an address, not the installation's own name, not
"localhost"; verified in one scope at most, claimed once per scope; at most MAX_PER_SCOPE per organisation (and for
the operator), claims included; a stem of one
to three segments of letters, digits, "-", ".", "_", "~", none of them 2 to 4 digits (it would read as an AI); a
default prefix is one of the organisation's prefixes (for the operator, any prefix no organisation holds) and is the
default of one domain at most.

What the host did for a verified "direct" domain (ADR 0009, section 7) is reported by scripts/custom-domains.sh, which
the installer runs every 5 minutes, into the collection "domain_hosts" (one document per domain: "state" served or
failed, "checkedAt", "attempts", "nextAttemptAt", "error" nginx or certificate, "certificateUntil") and the setting
"domains.hostRun" ({"at", "ok"}); the portal only reads them (certificate(), host_run()).
"""
import re
import secrets
from datetime import timedelta

import requests

import gs1
import linkcheck
import outbound
import store
import tenants
import users
from users import UserError

MAX_PER_SCOPE = 10
TXT_NAME = "_gs1resolver"
TXT_PREFIX = "gs1resolver-verify="
MODES = ("direct", "redirect")
LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
STEM_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,40}$")
RECHECK = timedelta(days=1)
PENDING = timedelta(days=7)                # an unverified claim is deleted this long after it was made
LAPSE = timedelta(days=7)                  # a verified domain whose record is missing this long is lapsed
REDIRECTS = (301, 302, 307, 308)
TIMEOUT = 10
HOST_RUN_LATE = timedelta(minutes=15)      # the server's task runs every 5 minutes; three missed runs: a warning


def _col():
    return store.col("domains")


# ----------------------------------------------------------------------------------------------- names
def clean_name(value, installation: str = "") -> str:
    """A domain as stored: lower case, Punycode, no scheme, path, port or final dot."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text).split("/")[0].split("?")[0].rstrip(".")
    if ":" in text:
        text = text.split(":")[0]
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError:
        raise UserError("domains.nameInvalid")
    labels = text.split(".")
    if (len(text) > 253 or len(labels) < 2 or not all(LABEL.match(label) for label in labels)
            or labels[-1].isdigit() or text == "localhost"):
        raise UserError("domains.nameInvalid")
    if installation and text == installation.lower():
        raise UserError("domains.installationName")
    return text


def clean_stem(value) -> str:
    """"" or "/seg[/seg[/seg]]"."""
    text = str(value or "").strip().strip("/")
    if not text:
        return ""
    segments = text.split("/")
    if len(segments) > 3 or not all(STEM_SEGMENT.match(s) and not re.fullmatch(r"\d{2,4}", s) for s in segments):
        raise UserError("domains.stemInvalid")
    return "/" + "/".join(segments)


def clean_mode(value) -> str:
    mode = str(value or "direct").strip().lower()
    if mode not in MODES:
        raise UserError("domains.modeInvalid")
    return mode


def name_of(doc: dict) -> str:
    """A domain's name (documents written before ADR 0035 have it in _id only)."""
    return doc.get("name") or doc["_id"]


def pending_id(name: str, tenant: str | None) -> str:
    """The _id of an unverified claim: the name and the scope, apart by a space (never in a host name)."""
    return f"{name} {tenant or '-'}"


def usable(doc: dict) -> bool:
    """Whether a domain may be put on new labels: verified and not lapsed."""
    return bool(doc.get("verified")) and not doc.get("lapsedAt")


def base_url(doc: dict) -> str:
    """The address a label carries for a domain: https://<domain><stem>."""
    return f"https://{name_of(doc)}{doc.get('stem') or ''}"


# ----------------------------------------------------------------------------------------------- reading
def certificate(doc: dict, host: dict | None) -> dict | None:
    """The certificate's state on the host for the card: None for a domain that needs none here (not verified, or
    redirected by the organisation's own server); otherwise {"state": "pending" | "served" | "failed", "checkedAt",
    "until", "nextAttemptAt", "error", "attempts"} — pending until the server's task has reported."""
    if not doc.get("verified") or doc.get("mode", "direct") != "direct":
        return None
    host = host or {}
    state = host.get("state") if host.get("state") in ("served", "failed") else "pending"
    return {"state": state, "checkedAt": store.iso(host.get("checkedAt")), "until": store.iso(host.get("certificateUntil")),
            "nextAttemptAt": store.iso(host.get("nextAttemptAt")), "error": host.get("error"),
            "attempts": host.get("attempts") or 0}


def host_states(names) -> dict:
    """The host's reports of these domains, by name."""
    names = list(names)
    return {d["_id"]: d for d in store.col("domain_hosts").find({"_id": {"$in": names}})} if names else {}


def with_hosts(docs: list[dict]) -> list[tuple[dict, dict | None]]:
    """Each domain with the host's report of it."""
    hosts = host_states(d["_id"] for d in docs)
    return [(d, hosts.get(d["_id"])) for d in docs]


def host_run(now=None) -> dict:
    """The last run of the server's task: {"at", "ok", "late"} (late: none for HOST_RUN_LATE, or never)."""
    value = store.get_setting("domains.hostRun") or {}
    at = value.get("at") if isinstance(value, dict) else None
    at = store.parse_iso(at) if isinstance(at, str) else at
    late = at is None or (now or store.now()) - at > HOST_RUN_LATE
    return {"at": store.iso(at), "ok": bool(value.get("ok")) if isinstance(value, dict) else False, "late": late}


def public(doc: dict, tenant_names: dict | None = None, host: dict | None = None) -> dict:
    """What the Domains screen shows (the token too: the administrator writes it in DNS); host: the server's report of
    the domain (domain_hosts), for the certificate's state."""
    name = name_of(doc)
    out = {"domain": name, "mode": doc.get("mode", "direct"), "stem": doc.get("stem") or "",
           "defaultFor": list(doc.get("defaultFor") or []), "verified": bool(doc.get("verified")),
           "verifiedAt": store.iso(doc.get("verifiedAt")), "seenAt": store.iso(doc.get("seenAt")),
           "lapsedAt": store.iso(doc.get("lapsedAt")),
           "expiresAt": store.iso(doc.get("expiresAt")) if not doc.get("verified") else None,
           "txtName": f"{TXT_NAME}.{name}", "txtValue": TXT_PREFIX + doc.get("token", ""),
           "check": {**(doc.get("check") or {}), "at": store.iso((doc.get("check") or {}).get("at"))}
           if doc.get("check") else None,
           "created": store.iso(doc.get("created")), "createdBy": doc.get("createdBy"),
           "url": base_url(doc), "certificate": certificate(doc, host)}
    if tenant_names is not None:
        out["organisation"] = tenant_names.get(doc.get("tenant")) if doc.get("tenant") else None
    return out


def _scope(tenant: str | None) -> dict:
    return {"tenant": tenant} if tenant else {"tenant": None}


def _live(docs) -> list[dict]:
    """Leaves out claims whose time is up (the TTL index deletes them within a minute or so)."""
    now = store.now()
    return [d for d in docs if d.get("verified") or not d.get("expiresAt") or d["expiresAt"] > now]


def load(tenant: str | None, every: bool = False) -> list[dict]:
    """The domains and claims of a scope (an organisation, or the operator), or every one."""
    return sorted(_live(_col().find({} if every else _scope(tenant))), key=lambda d: (name_of(d), d["_id"]))


def get(name: str, tenant: str | None) -> dict:
    """A domain or claim of the scope by its name."""
    name = str(name or "").strip().lower()
    doc = next(iter(_live(_col().find({"_id": {"$in": [name, pending_id(name, tenant)]}, **_scope(tenant)}))), None)
    if not doc:
        raise UserError("domains.unknown")
    return doc


def verified(tenant: str | None) -> list[dict]:
    """The domains of a scope that new labels may carry (verified, not lapsed)."""
    return [d for d in load(tenant) if usable(d)]


def still_held(doc: dict, prefix: str, tenant_list: list[dict]) -> bool:
    """Whether a domain's organisation (the operator without one) still holds a prefix it is the default for: a prefix
    moved to another organisation leaves a stale entry, ignored (prefixes are owned at query time, ADR 0002)."""
    if doc.get("tenant"):
        held = next((t.get("prefixes") or [] for t in tenant_list if t["id"] == doc["tenant"]), [])
        return any(prefix.startswith(h) for h in held)
    return not any(tenants.overlap(prefix, p) for t in tenant_list for p in t.get("prefixes") or [])


def default_for(anchor: str, tenant: str | None) -> dict | None:
    """The verified domain whose default prefixes cover the record's company part (the longest prefix wins)."""
    part = gs1.company_part(anchor)
    best, length = None, -1
    tenant_list = tenants.load()
    for doc in verified(tenant):
        for prefix in doc.get("defaultFor") or []:
            if part.startswith(prefix) and len(prefix) > length and still_held(doc, prefix, tenant_list):
                best, length = doc, len(prefix)
    return best


def label_base(anchor: str, tenant: str | None, choice: str | None, installation_url: str) -> str:
    """The address in front of a record's GS1 path: choice "" / "default" (the default domain of its prefix, else the
    installation), "installation", or a verified domain of the scope (otherwise domains.unusable)."""
    choice = str(choice or "").strip().lower()
    if choice in ("", "default"):
        doc = default_for(anchor, tenant)
        return base_url(doc) if doc else installation_url
    if choice == "installation":
        return installation_url
    doc = _col().find_one({"_id": choice, **_scope(tenant), "verified": True})
    if not doc or not usable(doc):
        raise gs1.ValidationError("domains.unusable", domain=choice[:100])
    return base_url(doc)


# ----------------------------------------------------------------------------------------------- changing
def _check_defaults(prefixes, tenant: str | None, own: str | None) -> list[str]:
    cleaned = users.clean_prefixes(prefixes or [])
    tenant_list = tenants.load()
    if tenant:
        held = next((t.get("prefixes") or [] for t in tenant_list if t["id"] == tenant), [])
        if any(not any(p.startswith(h) for h in held) for p in cleaned):
            raise UserError("domains.prefixOutside")
    else:
        taken = [p for t in tenant_list for p in t.get("prefixes") or []]
        if any(tenants.overlap(p, t) for p in cleaned for t in taken):
            raise UserError("domains.prefixOutside")
    for doc in _col().find({"defaultFor": {"$in": cleaned}, "_id": {"$ne": own}}):
        if any(still_held(doc, p, tenant_list) for p in cleaned if p in (doc.get("defaultFor") or [])):
            raise UserError("domains.prefixTaken", domain=name_of(doc))
    return cleaned


def _taken(name: str, tenant: str | None) -> bool:
    """Whether the name is verified in another scope and not lapsed there (a lapsed one can be taken over)."""
    doc = _col().find_one({"_id": name})
    return bool(doc) and (doc.get("tenant") or None) != tenant and not doc.get("lapsedAt")


def create(name, mode, stem, tenant: str | None, by: str, installation: str) -> dict:
    """A claim of a name for the scope: refused when the scope has it already or another scope has verified it (and
    it has not lapsed); a claim of another scope does not stand in the way (ADR 0035)."""
    name, mode, stem = clean_name(name, installation), clean_mode(mode), clean_stem(stem)
    with users.locked():
        mine = _live(_col().find({"_id": {"$in": [name, pending_id(name, tenant)]}, **_scope(tenant)}))
        if mine or _taken(name, tenant):
            raise UserError("domains.exists")
        if len(load(tenant)) >= MAX_PER_SCOPE:
            raise UserError("domains.tooMany", max=MAX_PER_SCOPE)
        now = store.now()
        _col().delete_many({"_id": pending_id(name, tenant)})          # a claim whose time is up, not yet deleted
        doc = {"_id": pending_id(name, tenant), "name": name, "mode": mode, "stem": stem, "defaultFor": [],
               "token": secrets.token_hex(16), "verified": False, "created": now, "createdBy": by,
               "expiresAt": now + PENDING}
        if tenant:
            doc["tenant"] = tenant
        _col().insert_one(doc)
    return doc


def update(name, tenant: str | None, mode=None, stem=None, default_prefixes=None) -> tuple[dict, dict]:
    """Changes a domain of the scope; returns (before, after)."""
    with users.locked():
        doc = get(name, tenant)
        change = {}
        if mode is not None:
            change["mode"] = clean_mode(mode)
        if stem is not None:
            change["stem"] = clean_stem(stem)
        if default_prefixes is not None:
            change["defaultFor"] = _check_defaults(default_prefixes, tenant, doc["_id"])
        if change:
            _col().update_one({"_id": doc["_id"]}, {"$set": change})
        return doc, {**doc, **change}


def remove(name, tenant: str | None) -> dict:
    """Removes a domain; the host's report of it goes too, so the domain starts over if it is added again (its site on
    the host stays until removed by hand: custom-domains.sh list)."""
    doc = get(name, tenant)
    _col().delete_one({"_id": doc["_id"]})
    if doc.get("verified") or not _col().find_one({"_id": name_of(doc)}):    # never another scope's domain's report
        store.col("domain_hosts").delete_one({"_id": name_of(doc)})
    return doc


# ----------------------------------------------------------------------------------------------- proof and checks
def txt_records(host: str) -> list[str]:
    """The TXT strings of a name (empty when there are none or the lookup fails). Replaced by the tests."""
    import dns.exception
    import dns.resolver
    try:
        answer = dns.resolver.resolve(host, "TXT", lifetime=TIMEOUT)
    except (dns.exception.DNSException, OSError):
        return []
    return ["".join(part.decode("utf-8", "replace") for part in record.strings) for record in answer]


def verify(name, tenant: str | None) -> tuple[dict, dict | None]:
    """Looks up the TXT record. A claim found becomes the domain (refused with domains.exists while another scope's
    domain of that name has not lapsed; a lapsed one is removed: the second value, for the journal) and the other
    claims of the name go; a domain found is seen now and no longer lapsed. Returns (the domain after the look, the
    lapsed domain of another scope it replaced or None)."""
    doc = get(name, tenant)
    name = name_of(doc)
    found = TXT_PREFIX + doc["token"] in txt_records(f"{TXT_NAME}.{name}")
    if not found:
        if not doc.get("verified"):
            raise UserError("domains.txtMissing", name=f"{TXT_NAME}.{name}", value=TXT_PREFIX + doc["token"])
        return doc, None
    now = store.now()
    if doc.get("verified"):
        _col().update_one({"_id": doc["_id"]}, {"$set": {"seenAt": now}, "$unset": {"lapsedAt": ""}})
        doc = {**doc, "seenAt": now}
        doc.pop("lapsedAt", None)
        return doc, None
    with users.locked():
        replaced = _col().find_one({"_id": name})
        if replaced and (not replaced.get("lapsedAt") or (replaced.get("tenant") or None) == tenant):
            raise UserError("domains.exists")
        if replaced:
            _col().delete_one({"_id": name, "lapsedAt": {"$exists": True}})
            store.col("domain_hosts").delete_one({"_id": name})
        new = {k: v for k, v in doc.items() if k not in ("_id", "expiresAt", "check")}
        new.update(_id=name, name=name, verified=True, verifiedAt=now, seenAt=now)
        _col().insert_one(new)
        _col().delete_many({"name": name, "verified": False})
    return new, replaced


def recheck_all(now=None) -> list[dict]:
    """Daily housekeeping: looks again at the TXT record of every verified domain not seen for a day. Found, it is
    seen now and no longer lapsed; missing for LAPSE since it was last seen (or verified), it is lapsed. Returns the
    domains that lapsed in this run (the caller journals them and tells their administrators)."""
    now = now or store.now()
    lapsed = []
    for doc in _col().find({"verified": True}):
        if doc.get("seenAt") and now - doc["seenAt"] < RECHECK:
            continue
        if TXT_PREFIX + doc["token"] in txt_records(f"{TXT_NAME}.{name_of(doc)}"):
            _col().update_one({"_id": doc["_id"]}, {"$set": {"seenAt": now}, "$unset": {"lapsedAt": ""}})
        elif not doc.get("lapsedAt") and now - (doc.get("seenAt") or doc.get("verifiedAt") or now) >= LAPSE:
            _col().update_one({"_id": doc["_id"], "lapsedAt": {"$exists": False}}, {"$set": {"lapsedAt": now}})
            lapsed.append({**doc, "lapsedAt": now})
    return lapsed


def upgrade(now=None) -> int:
    """Domains written before ADR 0035: each gets its name, and an unverified one becomes a claim under pending_id()
    deleted PENDING after the upgrade. Idempotent; returns the documents changed."""
    now = now or store.now()
    changed = 0
    for doc in _col().find({"name": {"$exists": False}}):
        if doc.get("verified"):
            _col().update_one({"_id": doc["_id"]}, {"$set": {"name": doc["_id"]}})
        else:
            claim = {**doc, "_id": pending_id(doc["_id"], doc.get("tenant")), "name": doc["_id"],
                     "expiresAt": now + PENDING}
            if not _col().find_one({"_id": claim["_id"]}):
                _col().insert_one(claim)
            _col().delete_one({"_id": doc["_id"], "verified": {"$ne": True}})
        changed += 1
    return changed


def probe(url: str) -> requests.Response:
    """One request through a domain without following redirects, connected to a checked public address of the name
    (outbound.request(), ADR 0029); PermissionError for a private address. Replaced by the tests."""
    try:
        return outbound.request("GET", url, timeout=TIMEOUT, headers={"User-Agent": linkcheck.USER_AGENT})
    except outbound.PrivateAddress:
        raise PermissionError("private address")
    except outbound.OutboundError as exc:
        raise requests.ConnectionError(type(exc).__name__)


def check(name, tenant: str | None, installation_url: str, sample_anchor: str | None) -> dict:
    """Requests through the domain: direct mode, the description file at its root; redirect mode, a code of the organisation
    (sample_anchor, or a made-up GTIN of its first prefix), whose Location must be the installation's same path."""
    doc = get(name, tenant)
    base = base_url(doc)
    if doc.get("mode") == "redirect":
        path = (sample_anchor or "/01/00000000000000") + "?linkType=all"
        url, expected = base + path, installation_url.rstrip("/") + path
    else:
        url, expected = f"https://{name_of(doc)}/.well-known/gs1resolver", None      # at the root, never under the stem
    result = {"at": store.now(), "url": url, "ok": False, "problem": None, "detail": None}
    try:
        answer = probe(url)
    except PermissionError:
        result["problem"] = "domains.checkPrivate"
    except requests.RequestException as exc:
        result.update(problem="domains.checkUnreachable", detail=type(exc).__name__)
    else:
        if expected is None:
            body = answer.json() if answer.headers.get("Content-Type", "").startswith("application/json") else None
            if answer.status_code == 200 and isinstance(body, dict) and body.get("resolverRoot"):
                result["ok"] = True
            else:
                result.update(problem="domains.checkNotResolver", detail=str(answer.status_code))
        else:
            location = answer.headers.get("Location", "")
            if answer.status_code in REDIRECTS and location == expected:
                result["ok"] = True
            else:
                result.update(problem="domains.checkRedirect", detail=f"{answer.status_code} {location}"[:200])
    _col().update_one({"_id": doc["_id"]}, {"$set": {"check": result}})
    return {**doc, "check": result}
