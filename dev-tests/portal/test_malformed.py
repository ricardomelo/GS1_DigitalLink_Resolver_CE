"""
Malformed request bodies (Documentation/adr/0040-request-bodies.md, findings F-023 and F-029), through the portal's
Flask test client: every write route of the portal's API (/portal/api/…, the organisations' API included), found in the
application's own table of routes, answers a body that is not one JSON object (an array, a text, a number, null, a
broken or deeply nested document) with 400 request.jsonInvalid, and a field of bodies.FIELDS holding a value of another
kind (a number for a text, an object for a user name or a job's token, a list of numbers for a list of prefixes, a
row that is not an object) with 422 request.fieldInvalid naming the field's path, before the route runs; seeded with a
valid body for each route, every field and every field of its rows replaced by values of every kind never makes a
route answer 500, nor do the fields the table leaves to their routes; null and unknown fields still reach the routes,
and valid bodies are still saved.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_malformed.py
"""
import copy
import json
import logging
import os
import re
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3412
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_malformed_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402,F401
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Pharma", ["7891234"], "root")
gamma = tenants.create("Gamma Labs", ["7895555"], "root")
import app as portal  # noqa: E402
import apikeys  # noqa: E402
import bodies  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
for logger in ("portal", "werkzeug"):            # the routes' own warnings while every value is tried
    logging.getLogger(logger).setLevel(logging.CRITICAL)

failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("zed", "zed-password-long", "editor", tenant=gamma["id"], must_change=False)
API_KEY, _ = apikeys.create("Malformed bodies", ["records:read", "records:write"], 30, ["7891234"], acme["id"], "ana")


def client(username=None):
    c = portal.app.test_client()
    if username:
        c.post("/portal/api/login", json={"username": username, "password": f"{username}-password-long"},
               headers=ORIGIN)
    return c


def send(c, method, path, raw=None, body=None, key=False):
    headers = dict(ORIGIN, **({"Authorization": f"Bearer {API_KEY}"} if key else {}))
    data = raw if raw is not None else json.dumps(body)
    return c.open(path, method=method, data=data, headers=headers, content_type="application/json")


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


# --------------------------------------------------------------------------- every write route, from the app itself
PLACES = {"username": "zed", "tenant_id": gamma["id"], "scope": gamma["id"], "prefix": "7895555", "name": "id.gamma.example",
          "key_id": "k-unknown", "token": "unknown-token", "key": "01", "value": "07891234000019"}
ROUTES = []
for rule in portal.app.url_map.iter_rules():
    if not rule.rule.startswith("/portal/api/"):
        continue
    for method in sorted(rule.methods & {"POST", "PUT", "DELETE"}):
        path = re.sub(r"<(?:[a-z]+:)?([a-z_]+)>", lambda m: PLACES[m.group(1)], rule.rule)
        ROUTES.append((method, rule.rule, path))
ROUTES.sort()
check("the table of routes gives the portal's write routes (more than 50, the organisations' API among them)",
      len(ROUTES) > 50 and any("/api/v1/" in r for _, r, _ in ROUTES), len(ROUTES))

# Valid bodies, one per route that reads one, as the browser or a client sends them (captured from the other programs)
T = acme["id"]
SEEDS = {
    ("POST", "/portal/api/code/read"): {"text": "]Q1https://id.gs1.org/01/09506000134352/10/L1"},
    ("POST", "/portal/api/digital-link"): {"attributes": [{"ai": "(17)", "value": "261231"}, {"ai": "3103", "value": "000500"}],
                                            "key": "01", "qualifiers": {"10": "L1"}, "value": "09506000134352"},
    ("POST", "/portal/api/domains"): {"domain": "ID.Acme.Example.", "mode": "direct", "stem": "gs1/"},
    ("POST", "/portal/api/export"): {"format": "xlsx", "only": ["/01/07891234520012|"], "labels": {
        "headers": {"key": "Key", "value": "Value"}, "aliases": {"key": ["Key", "Chave"]}, "linkTypes": {"gs1:pip": ["Product", "A page about the product"]},
        "languages": {"pt": "Portuguese"}, "keys": {"01": "GTIN"}, "yes": "yes", "no": "no", "yesWords": ["yes", "sim"],
        "noWords": ["no", "não"], "sheets": {"links": "Links", "keys": "Keys"}, "codeHeader": "Code", "languagesNote": "Note"}},
    ("POST", "/portal/api/forwarding/rules"): {"note": "Moved", "prefix": "9521234", "target": "https://other.example.net"},
    ("POST", "/portal/api/import/apply"): {"createKeyRecords": True, "token": "f04d2c07ff2b449a993e342b35b7e89a"},
    ("POST", "/portal/api/import/cancel"): {"token": "7ae7cd133d604ec2be03493d9fc0a668"},
    ("POST", "/portal/api/import/preview"): {"content": "a2V5LHZhbHVlCg==", "filename": "links.csv",
                                             "labels": {"aliases": {"key": ["Key", "Chave"]}, "yes": ["yes"], "no": ["no"]}},
    ("POST", "/portal/api/keys"): {"days": 30, "name": "ERP integration", "scopes": ["records:write", "records:read"],
                                   "prefixes": ["7891234"], "tenant": T},
    ("POST", "/portal/api/links/check"): {"urls": ["https://example.org/a", "https://example.org/b"]},
    ("POST", "/portal/api/links/jobs"): {"urls": ["https://example.org/a"], "scope": "all"},
    ("POST", "/portal/api/login"): {"language": "pt-BR", "password": "nobody-password-long", "username": "nobody"},
    ("POST", "/portal/api/overview/export"): {"days": 7, "format": "xlsx", "labels": {"overview.on": "on"}, "tenant": T},
    ("POST", "/portal/api/password"): {"currentPassword": "not-the-password", "newPassword": "another-password-long"},
    ("POST", "/portal/api/password/forgot"): {"language": "pt-BR", "login": "nobody@example.org"},
    ("POST", "/portal/api/password/link"): {"language": "en-GB", "newPassword": "another-password-long",
                                            "token": "OIViP7uqNoSTJ1oz37FAsFUTN7HxNeZCY2JnzmEQD3k"},
    ("POST", "/portal/api/password/link/check"): {"token": "OIViP7uqNoSTJ1oz37FAsFUTN7HxNeZCY2JnzmEQD3k"},
    ("POST", "/portal/api/record"): {
        "description": "Coffee", "key": "01", "value": "07891234000019", "qualifiers": {"10": "L1"}, "landingPage": False,
        "defaultLinkType": "gs1:pip", "keyRecord": {"description": "Coffee", "mode": "copy"},
        "links": [{"context": [], "hreflang": ["pt"], "linkType": "gs1:pip", "title": "", "url": "https://acme.example.com/pt"},
                  {"hreflang": ["en"], "linkType": "gs1:epil", "title": "Leaflet", "url": "https://acme.example.com/en"}]},
    ("POST", "/portal/api/record/warnings"): {
        "defaultLinkType": "gs1:pip", "description": "Amoxicillin", "key": "01", "value": "07891234000019",
        "links": [{"hreflang": ["pt"], "linkType": "gs1:pip", "title": "", "url": "https://farma.example/pip"}]},
    ("POST", "/portal/api/records/fix-serials"): {"key": "01", "qualifiers": "/10/L1/21/S1", "value": "07891234000019",
                                                   "all": False},
    ("POST", "/portal/api/sso/start"): {"email": "nobody@acme.example", "language": "en-GB"},
    ("POST", "/portal/api/sso/<scope>/approve"): {"domain": "beta.example"},
    ("POST", "/portal/api/sso/<scope>/verify"): {"domain": "acme.example"},
    ("POST", "/portal/api/support"): {"reason": "Ticket 42: wrong target", "tenant": T},
    ("POST", "/portal/api/tenants"): {"name": "Delta Foods", "prefixes": ["7895678"]},
    ("POST", "/portal/api/users"): {"email": "caio@acme.example", "prefixes": ["78912345"], "role": "editor", "tenant": T,
                                    "username": "caio", "invite": False},
    ("PUT", "/portal/api/appearance"): {"accent": "#e8b100", "action": "#8a1538", "colour": "#1a3d2b", "logo": "",
                                        "icon": "", "title": "Acme Resolver"},
    ("PUT", "/portal/api/branding/<prefix>"): {"name": "Gamma", "colour": "#1a3d2b", "logo": "", "verified": False},
    ("PUT", "/portal/api/domains/<name>"): {"mode": "redirect", "stem": "/id", "defaultFor": ["7895555"]},
    ("PUT", "/portal/api/exports/limits"): {"limits": {"api": "1", "editor": None, "reader": 5}, "tenant": T},
    ("PUT", "/portal/api/exports/maximum"): {"maximum": 1000},
    ("PUT", "/portal/api/forwarding/fallback"): {"enabled": False, "url": "https://resolver.example.net/gs1"},
    ("PUT", "/portal/api/forwarding/rules/<prefix>"): {"enabled": False, "mode": "fixed", "target": "https://other.example.net"},
    ("PUT", "/portal/api/preferences"): {"language": "en-GB", "notify": {"jobs": True}},
    ("PUT", "/portal/api/privacy"): {"note": "First version", "text": "# Privacy\n\nOperated by {operator}."},
    ("PUT", "/portal/api/requests/retention"): {"days": 30, "maxMegabytes": 500, "tenant": T},
    ("PUT", "/portal/api/resolution/strict"): {"enabled": False, "tenant": T},
    ("PUT", "/portal/api/sso/<scope>"): {"clientId": "portal-client", "clientSecret": "s3cret-value", "domains": ["gamma.example"],
                                         "enabled": False, "issuer": "https://login.gamma.example", "passwordOff": False,
                                         "emailVerifiedOptional": False},
    ("PUT", "/portal/api/targets/hosts"): {"hosts": ["example.org", "cdn.example.net"], "tenant": T},
    ("PUT", "/portal/api/tenants/<tenant_id>"): {"disabled": False, "name": "Gamma Labs", "prefixes": ["7895555"]},
    ("PUT", "/portal/api/users/<username>"): {"email": "zed@gamma.example", "role": "editor", "disabled": False,
                                              "ssoForget": False, "prefixes": []},
    ("PUT", "/portal/api/v1/records/<key>/<path:value>"): {
        "description": "Coffee 500 g", "defaultLinkType": "gs1:pip", "landingPage": False,
        "links": [{"hreflang": ["en"], "linkType": "gs1:pip", "title": "Info", "url": "https://example.org/x"}]},
}
check("every seed names a write route of the table", all(k in {(m, r) for m, r, _ in ROUTES} for k in SEEDS),
      [k for k in SEEDS if k not in {(m, r) for m, r, _ in ROUTES}])


def who(rule):
    """The clients a route is tried with: the organisations' API with its key, the others as a server administrator,
    an organisation's administrator and nobody signed in."""
    return [("key", None)] if "/api/v1/" in rule else [("root", "root"), ("ana", "ana"), ("anonymous", None)]


# --------------------------------------------------------------------------- 1. bodies that are not one JSON object
NOT_OBJECTS = ["[1]", "[{}]", '"text"', "5", "null", "true", "{", '{"key": "01",}', "[" * 50_000 + "]" * 50_000,
               '{"a": ' * 50_000 + "1" + "}" * 50_000]
for method, rule, path in ROUTES:
    for name, user in who(rule):
        c = client(user)
        wrong = [raw[:12] for raw in NOT_OBJECTS
                 if (lambda r: (r.status_code, code(r)) != (400, "request.jsonInvalid"))(
                     send(c, method, path, raw=raw, key=name == "key"))]
        check(f"not an object, 400 request.jsonInvalid: {method} {rule} ({name})", not wrong, wrong)

# --------------------------------------------------------------------------- 2. a field of the table of another kind
WRONG = {bodies.TEXT: [5, ["x"], {"$ne": None}, True], bodies.FLAG: ["true", 1, [True]],
         bodies.LIST: ["x", 5, {}], bodies.TEXTS: [["x", 5], "x", [{"$ne": None}], 5],
         bodies.OBJECTS: [[1], ["x"], {"url": "x"}, "x"], bodies.NAMES: [{"a": 1}, {"a": ["x"]}, ["x"], "x"],
         bodies.LABELS: [["x"], "x", {"headers": "x"}, {"aliases": {"key": "x"}}, {"yes": 5}, {"anything": ["x"]}],
         bodies.RECORD: [[1], "x", 5]}


def wrong_values(kinds):
    """Values of none of the kinds a field allows."""
    return [v for kind in kinds for v in WRONG[kind] if not any(bodies._is(v, k) for k in kinds)]


for method, rule, path in ROUTES:
    name, user = who(rule)[0]
    c = client(user)
    missed = []
    for field, kinds in sorted(bodies.FIELDS.items()):
        for value in wrong_values(kinds):
            r = send(c, method, path, body={field: value}, key=name == "key")
            if (r.status_code, code(r), (r.get_json() or {}).get("params")) != (422, "request.fieldInvalid", {"field": field}):
                missed.append(f"{field}={json.dumps(value)} → {r.status_code} {code(r)}")
    check(f"each field of the table of another kind, 422 request.fieldInvalid naming it: {method} {rule}", not missed,
          missed[:5])

root = client("root")
NESTED = [
    ({"links": [{"url": "https://example.org/a"}, {"url": 5}]}, "links.2.url"),
    ({"links": [{"hreflang": ["en", 5]}]}, "links.1.hreflang"),
    ({"links": [{"linkType": ["gs1:pip"]}]}, "links.1.linkType"),
    ({"links": [{"context": "x"}]}, "links.1.context"),
    ({"attributes": [{"ai": "10", "value": {"a": 1}}]}, "attributes.1.value"),
    ({"keyRecord": {"description": ["x"]}}, "keyRecord.description"),
    ({"keyRecord": {"links": [{"url": True}]}}, "keyRecord.links.1.url"),
    ({"keyRecord": {"links": [{"links": [{"url": "x"}]}]}}, "keyRecord.links.1.links"),
    ({"links": [{"links": [{"links": [{}]}]}]}, "links.1.links.1.links"),
    ({"qualifiers": {"10": 5}}, "qualifiers"),
    ({"labels": {"export.key": None}}, "labels"),
    ({"labels": {"headers": {"key": ["Key"]}}}, "labels"),
]
for body, where in NESTED:
    r = send(root, "POST", "/portal/api/record", body=body)
    check(f"a field inside rows or the key's record of another kind names its path: {where}",
          (r.status_code, code(r), (r.get_json() or {}).get("params")) == (422, "request.fieldInvalid", {"field": where}),
          f"{r.status_code} {r.get_json()}")

# --------------------------------------------------------------------------- 3. every value of every kind, never 500
VALUES = [5, -1, 10 ** 20, 1.5, True, False, None, "", "x", " ", "\u0000", "é" * 300, [], [1], ["x", 5], [None], [[]],
          [{}], {}, {"a": 1}, {"$ne": None}, {"$gt": ""}]


def paths(o, pre=()):
    """Every place of a body: the fields, the rows of its lists and their fields."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield pre + (k,)
            yield from paths(v, pre + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield pre + (i,)
            yield from paths(v, pre + (i,))


def replaced(o, where, value):
    o = copy.deepcopy(o)
    target = o
    for step in where[:-1]:
        target = target[step]
    target[where[-1]] = value
    return o


paths_of = {method_rule: list(paths(seed)) for method_rule, seed in SEEDS.items()}
for method, rule, path in ROUTES:
    seed = SEEDS.get((method, rule))
    if seed is None:
        continue
    for name, user in who(rule)[:2]:
        c = client(user)
        r = send(c, method, path, body=seed, key=name == "key")
        crashed = [] if r.status_code < 500 else ["the seed itself"]
        for where in paths_of[(method, rule)]:
            for value in VALUES:
                r = send(c, method, path, body=replaced(seed, where, value), key=name == "key")
                if r.status_code >= 500:
                    crashed.append(f"{'.'.join(map(str, where))}={json.dumps(value)[:20]}")
        check(f"every place of a valid body with every kind of value, never 500: {method} {rule} ({name})",
              not crashed, crashed[:5])

# The fields the table leaves to their routes (any name the portal's code reads with .get()), all at once, every kind
names = set()
for file in os.listdir(PORTAL):
    if file.endswith(".py") and file != "bodies.py":
        names |= set(re.findall(r'\.get\("([A-Za-z_][A-Za-z0-9_]*)"', open(os.path.join(PORTAL, file), encoding="utf-8").read()))
free = sorted(names - set(bodies.FIELDS))
check("the portal's code reads fields the table leaves to their routes (more than 100 names)", len(free) > 100, len(free))
for method, rule, path in ROUTES:
    name, user = who(rule)[0]
    c = client(user)
    crashed = []
    for value in (5, True, ["x", 5], {"$ne": None}, "x", -1):
        body = dict(SEEDS.get((method, rule), {}), **{n: value for n in free})
        r = send(c, method, path, body=body, key=name == "key")
        if r.status_code >= 500:
            crashed.append(json.dumps(value))
    check(f"the fields left to the routes with every kind of value, never 500: {method} {rule}", not crashed, crashed)

# --------------------------------------------------------------------------- 4. what still passes
check("null is accepted for every field of the table (the routes read it as absent)",
      bodies.problem({f: None for f in bodies.FIELDS}) is None)
check("a field the table does not name is not checked", bodies.problem({"maxMegabytes": {"a": [1]}, "whatever": 5}) is None)
check("a flag is not a number, a number is not a flag, a text is neither",
      bodies.problem({"landingPage": 1}) == ("request.fieldInvalid", 422, {"field": "landingPage"})
      and bodies.problem({"invite": "true"}) == ("request.fieldInvalid", 422, {"field": "invite"})
      and bodies.problem({"days": True, "maximum": "x"}) is None)
check("the kinds a field allows are all accepted (domains as text or list, qualifiers as path or object)",
      all(bodies.problem(b) is None for b in (
          {"domains": "a.example b.example"}, {"domains": ["a.example"]}, {"qualifiers": "/10/L1"},
          {"qualifiers": {"10": "L1"}}, {"labels": {}}, {"links": []}, {"context": [1, None]},
          {"labels": {"aliases": {"key": ["Key"]}, "yes": ["yes", "sim"], "no": "no", "overview.on": "on"}})))
check("an array, a text, a number or null as the body is refused by bodies.problem",
      all(bodies.problem(b) == ("request.jsonInvalid", 400, {}) for b in ([], [{}], "x", 5, None, True)))

send(client("root"), "PUT", "/portal/api/targets/hosts", body={"tenant": T, "hosts": []})   # as the seeds left it
ana = client("ana")
r = send(ana, "POST", "/portal/api/record", body=SEEDS[("POST", "/portal/api/record")] | {"keyRecord": None, "qualifiers": None})
check("a valid record is still saved (the seeds made it: 200 save.updated), with null for fields the route reads as "
      "absent", (r.status_code, code(r)) == (200, "save.updated"),
      f"{r.status_code} {r.get_json()}")
r = ana.post("/portal/api/record", data="", headers=ORIGIN, content_type="application/json")
check("an empty body still reaches the route, which reads it as {} (gtin.required)",
      (r.status_code, code(r)) == (422, "gtin.required"), f"{r.status_code} {r.get_json()}")
r = send(client(), "PUT", "/portal/api/v1/records/01/07891234000026", body=SEEDS[("PUT", "/portal/api/v1/records/<key>/<path:value>")],
         key=True)
check("the organisations' API still creates a record from a valid body (201)", r.status_code == 201,
      f"{r.status_code} {r.get_json()}")
r = send(client(), "PUT", "/portal/api/v1/records/01/07891234000026", raw="", key=True)
check("the organisations' API still answers an empty body with request.jsonRequired (422)",
      (r.status_code, code(r)) == (422, "request.jsonRequired"), f"{r.status_code} {r.get_json()}")

r = send(ana, "POST", "/portal/api/export", body={"format": "xlsx", "labels": {
    "headers": {"key": "Ke\u0000y"}, "sheets": {"links": "Li\u0001nks"}, "codeHeader": "Co\u001fde"}})
try:
    import io
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(r.data)) if r.status_code == 200 else None
except Exception as exc:  # noqa: BLE001
    book = exc
check("an XLSX export whose labels carry control characters is written without them (the format forbids them)",
      book is not None and not isinstance(book, Exception) and book.worksheets[0].title == "Links"
      and book.worksheets[0]["A1"].value == "Key" and book.worksheets[1]["A1"].value == "Code",
      f"{r.status_code} {book!r}")

# --------------------------------------------------------------------------- 5. operators instead of values (F-029)
for method, path, body, field in (
        ("POST", "/portal/api/import/apply", {"token": {"$ne": None}}, "token"),
        ("POST", "/portal/api/import/cancel", {"token": {"$gt": ""}}, "token"),
        ("POST", "/portal/api/password/link", {"token": {"$ne": None}, "newPassword": "another-password-long"}, "token"),
        ("POST", "/portal/api/login", {"username": {"$ne": None}, "password": "x"}, "username"),
        ("POST", "/portal/api/password/forgot", {"login": {"$regex": ".*"}}, "login"),
        ("POST", "/portal/api/support", {"tenant": {"$ne": None}, "reason": "Ticket 42"}, "tenant")):
    r = send(client("root"), method, path, body=body)
    check(f"a query operator where a value goes never reaches a database filter: {path} {field}",
          (r.status_code, code(r), (r.get_json() or {}).get("params")) == (422, "request.fieldInvalid", {"field": field}),
          f"{r.status_code} {r.get_json()}")

print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
sys.exit(1 if failures else 0)
