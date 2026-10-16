"""
The tenant API, version 1 (Documentation/adr/0005-tenant-api.md): /portal/api/v1, for an organisation's own systems,
authenticated by an API key (apikeys.py) in "Authorization: Bearer rk_<id>.<secret>".

Each call is given the scope of a request from its key (app.set_scope(): the key's organisation, the role its scopes
imply, its prefixes) and goes through the same functions as the portal's own endpoints (build_document(),
store_record(), remove_record(), label_response()), so every rule of the portal applies. Answers are JSON with the
portal's message codes; the description is portal/openapi.json, served at /portal/api/v1/openapi.json.

Imported at the end of app.py (it uses app's functions), so it adds its routes to the portal's Flask application.
"""
import copy
import json
import logging
import os
import time
from functools import wraps

from flask import Response, g, jsonify, request

import apikeys
import app as portal
import gs1
import overview
import requestlog
from gs1 import ValidationError

log = logging.getLogger("portal.api")

PREFIX = "/portal/api/v1"
SPEC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")
MAX_PAGE = 1000
DEFAULT_PAGE = 100


def _refuse(code: str, status: int, headers: dict | None = None, **params):
    response, status = portal.message(code, status, params=params)
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response, status


def require_key(scope: str | None = None):
    """Authenticates the request by its API key, counts it against the key's limit, checks the scope and gives the
    request the key's scope. 401 api.keyMissing / api.keyInvalid (unknown, revoked, expired, or of a disabled
    organisation), 429 api.rateLimit with Retry-After, 403 api.scope."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            challenge = {"WWW-Authenticate": 'Bearer realm="tenant-api"'}
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return _refuse("api.keyMissing", 401, challenge)
            key = apikeys.authenticate(header[len("Bearer "):].strip())
            if not key or portal.tenant_blocked({"tenant": key.get("tenant")}):
                return _refuse("api.keyInvalid", 401, challenge)
            g.api_key_seen = key                          # for the log of calls, even when refused below
            allowed, wait = apikeys.count_request(key["_id"])
            if not allowed:
                return _refuse("api.rateLimit", 429, {"Retry-After": str(wait)}, seconds=wait)
            if scope and scope not in key["scopes"]:
                return _refuse("api.scope", 403, scope=scope)
            role = "editor" if "records:write" in key["scopes"] else "reader"
            portal.set_scope(f"api:{key['_id']}", {"role": role, "prefixes": key.get("prefixes") or [],
                                                    "tenant": key.get("tenant")})
            g.api_key = key
            return view(*args, **kwargs)
        return wrapper
    return decorator


@portal.app.before_request
def _call_started():
    """The time a call of this API arrived (its log, Documentation/adr/0006-resolver-request-log.md, decision 8)."""
    if request.path == PREFIX or request.path.startswith(PREFIX + "/"):
        g.api_call_started = time.perf_counter()


@portal.app.after_request
def _call_logged(response):
    """Records the call: key, method, the route's template (never the record or the query string), status, time."""
    started = g.get("api_call_started")
    if started is not None and request.method in ("GET", "PUT", "DELETE", "POST", "HEAD"):
        try:
            requestlog.record_api_call(g.get("api_key_seen"), request.method,
                                       request.url_rule.rule if request.url_rule else None, response.status_code,
                                       max(0, round((time.perf_counter() - started) * 1000)))
        except Exception as exc:                          # the log never changes an answer
            log.warning("Tenant API call not logged: %s", exc)
    return response


def _anchor(key: str, value: str) -> str:
    """The anchor a path names (/records/{key}/{value}), checked against the key's reach (403 access.prefix)."""
    anchor = portal.request_key({"key": key, "value": value})
    portal.check_access(anchor)
    return anchor


def _summary() -> list[dict]:
    status, body = portal.resolver("GET", "/summary")
    if status == 404:
        return []
    if status != 200 or not isinstance(body, dict):
        raise portal.UpstreamError("upstream.readFailed", 502, body)
    return body.get("data") or []


@portal.app.get(PREFIX + "/")
@require_key()
def v1_whoami():
    """The key itself, its organisation and its request limit."""
    key = g.api_key
    tenant = portal.tenant_summary(key.get("tenant"))
    return jsonify({"key": {"id": key["_id"], "name": key["name"], "scopes": key["scopes"],
                            "prefixes": key.get("prefixes") or [], "expiresAt": portal.store.iso(key["expiresAt"])},
                    "organisation": tenant["name"] if tenant else None,
                    "rateLimit": {"perMinute": apikeys.rate_per_minute()}, "resolver": portal.RESOLVER_PUBLIC_URL})


@portal.app.get(PREFIX + "/openapi.json")
def v1_openapi():
    """The OpenAPI 3.1 description of this API (public), with the installation's address as its server."""
    with open(SPEC_FILE, encoding="utf-8") as fh:
        spec = json.load(fh)
    spec = copy.deepcopy(spec)
    spec["servers"] = [{"url": portal.PORTAL_ORIGIN + PREFIX}]
    return Response(json.dumps(spec, ensure_ascii=False, indent=1), mimetype="application/json")


@portal.app.get(PREFIX + "/records")
@require_key("records:read")
def v1_list_records():
    """The records within the key's reach, sorted by key and qualifiers, a page at a time (limit, after); filter by
    primary key with key=01."""
    try:
        limit = int(request.args.get("limit") or DEFAULT_PAGE)
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_PAGE:
        raise ValidationError("api.limit", max=MAX_PAGE)
    only, after = request.args.get("key") or None, request.args.get("after") or ""
    records = []
    for line in _summary():
        anchor = line.get("anchor") or ""
        key = gs1.split_anchor(anchor)
        if not key or (only and key[0] != only) or not portal.allowed(anchor):
            continue
        entry = portal.describe_entry(line)
        if entry["kind"] == "other":
            continue
        qpath = entry.get("path", "")
        records.append({"key": key[0], "value": key[1], "qualifiers": qpath,
                        "informative": gs1.qualifier_path([tuple(p) for p in entry.get("informative") or []], encode=False),
                        "description": line.get("itemDescription") or "",
                        "defaultLinkType": line.get("defaultLinktype"), "links": line.get("linkCount", 0),
                        "id": f"{anchor}|{qpath}"})
    records.sort(key=lambda r: r["id"])
    page = [r for r in records if r["id"] > after][:limit]
    more = len([r for r in records if r["id"] > after]) > limit
    return jsonify({"records": page, "next": page[-1]["id"] if more else None, "total": len(records)})


def _link_out(link: dict) -> dict:
    return {"linkType": link.get("linktype"), "url": link.get("href"), "title": link.get("title") or "",
            "hreflang": link.get("hreflang") or []}


@portal.app.get(PREFIX + "/records/<key>/<path:value>")
@require_key("records:read")
def v1_get_record(key, value):
    """One record: description, links (the default first), the default link type and its Digital Link."""
    anchor = _anchor(key, value)
    pairs, informative = portal.request_record(request.args, anchor)
    entries, default = portal.read_entries(anchor)
    target = portal.find_entry(entries, gs1.qualifier_list(pairs))
    if target is None:
        return _refuse("record.notFound", 404)
    stored = gs1.pairs_from(target.get("informativeQualifiers"))
    ai, val = gs1.split_anchor(anchor)
    shown, landing, own_default = gs1.record_view(target.get("links") or [], default)
    links = [_link_out(l) for l in shown]
    return jsonify({"key": ai, "value": val, "qualifiers": gs1.qualifier_path(pairs, encode=False),
                    "informative": gs1.qualifier_path(stored, encode=False),
                    "description": target.get("itemDescription") or "", "defaultLinkType": own_default, "links": links,
                    "landingPage": landing,
                    "digitalLink": gs1.digital_link(portal.link_base(anchor), anchor,
                                                    gs1.join_informative(pairs, informative or stored))})


@portal.app.put(PREFIX + "/records/<key>/<path:value>")
@require_key("records:write")
def v1_put_record(key, value):
    """Creates (201) or replaces (200) one record with the description and links of the body."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("request.jsonRequired")
    data = {"key": key, "value": value, "qualifiers": request.args.get("qualifiers", ""),
            "description": body.get("description"), "links": body.get("links") if isinstance(body.get("links"), list) else [],
            "defaultLinkType": body.get("defaultLinkType"), "landingPage": bool(body.get("landingPage"))}
    data["links"] = [row for row in data["links"] if isinstance(row, dict)]
    anchor, pairs, doc = portal.build_document(data)
    portal.check_access(anchor)
    created = portal.store_record(anchor, pairs, doc)
    uri = gs1.digital_link(portal.link_base(anchor), anchor,
                           gs1.join_informative(pairs, gs1.pairs_from(doc.get("informativeQualifiers"))))
    return portal.message("save.created" if created else "save.updated", 201 if created else 200,
                          created=created, digitalLink=uri)


@portal.app.delete(PREFIX + "/records/<key>/<path:value>")
@require_key("records:write")
def v1_delete_record(key, value):
    """Deletes one record, keeping the key's others."""
    anchor = _anchor(key, value)
    pairs, _ = portal.request_record(request.args, anchor)
    try:
        portal.remove_record(anchor, pairs)
    except ValidationError as exc:
        if exc.code == "record.notFound":
            return _refuse("record.notFound", 404)
        raise
    return portal.message("delete.done")


@portal.app.get(PREFIX + "/labels/<key>/<path:value>")
@require_key("labels:read")
def v1_get_label(key, value):
    """The record's label, as the portal makes it (format=svg|png, hri, version, ecl, attr=AI:value, domain)."""
    anchor = _anchor(key, value)
    return portal.label_response(anchor, request.args)


@portal.app.get(PREFIX + "/stats")
@require_key("stats:read")
def v1_stats():
    """Usage, resolution quality and record quality of the key's reach for the last 7, 30 or 90 days
    (Documentation/adr/0007-overview-indicators.md); the portal's overview without operation and governance."""
    per = overview.period(request.args.get("days"))
    scope, _ = portal.request_log_scope()
    data = overview.build(per, scope, False, portal.overview_records(), portal.overview_last_check(), {})
    return jsonify({name: data[name] for name in ("period", "usage", "quality", "records")})
