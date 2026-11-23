"""
Target addresses (Documentation/adr/0037-target-addresses.md), through the portal's Flask test client and its
functions: the forms no target may take, for every organisation (a user name or password before the host, an IP
address however it is written, a name that is not a public one), refused with their own message codes in the editor,
the API, imports and forwarding destinations, while public names (internationalised ones, ports, a trailing dot)
pass; and the hosts an organisation's targets may point to: empty by default (any public host), set by its
administrators (their own only) and the server administrators (any, and the operator's scope), cleaned (case, '*.',
Punycode, repeats), refused when a name is not a public host or there are too many, read only in support access,
journalled once per change; with hosts listed, a target is saved only when its host is one of them or a name under
one, in the editor, imports (with the row) and the API, while the record's own page on the installation is never
checked; another organisation's list and the operator's apply only to their own keys.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_targets.py
"""
import base64
import os
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3411
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_targets_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
acme = tenants.create("Acme Pharma", ["7891234"], "root")
beta = tenants.create("Beta Health", ["7895555"], "root")
import app as portal  # noqa: E402
import forwarding  # noqa: E402
import gs1  # noqa: E402
import targets  # noqa: E402
from gs1 import ValidationError  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()

failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def gtin(body: str) -> str:
    """A GTIN-13 with its check digit, as 14 digits."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return "0" + body + str((10 - total % 10) % 10)


ACME_A, ACME_B, BETA_A, OPER_A = gtin("789123400001"), gtin("789123400002"), gtin("789555500001"), gtin("789835741001")


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


def outcome(callable_):
    try:
        return callable_()
    except ValidationError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        return "CRASH " + type(exc).__name__


def save(c, value, *urls, landing=False):
    return c.post("/portal/api/record", headers=ORIGIN, json={
        "key": "01", "value": value, "description": "Item", "landingPage": landing,
        "links": [{"linkType": "gs1:pip" if i == 0 else "gs1:epil", "url": u, "hreflang": ["en"], "title": "t"}
                  for i, u in enumerate(urls)]})


def put_hosts(c, tenant, hosts):
    return c.put("/portal/api/targets/hosts", json={"tenant": tenant, "hosts": hosts}, headers=ORIGIN)


def page(c, tenant=None):
    return c.get("/portal/api/organisation" + (f"?id={tenant}" if tenant else "")).get_json()


users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
users.create("ope", "ope-password-long", "editor", must_change=False)
root, ana, edu, bia, ope = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia", "ope"))

# --------------------------------------------------------------------------- the forms no target may take
REFUSED = [
    ("a user name before the host", "https://user@example.org/x", "link.urlUserInfo"),
    ("a user name and password", "https://user:secret@example.org/x", "link.urlUserInfo"),
    ("a host disguised by user information", "https://example.org@evil.example.net/x", "link.urlUserInfo"),
    ("an empty user information", "https://@example.org/x", "link.urlUserInfo"),
    ("an IPv4 address", "https://192.0.2.10/x", "link.urlAddress"),
    ("a private IPv4 address with a port", "https://10.0.0.5:8443/x", "link.urlAddress"),
    ("the loopback address", "https://127.0.0.1/", "link.urlAddress"),
    ("an IPv6 address", "https://[2001:db8::1]/x", "link.urlAddress"),
    ("the IPv6 loopback", "https://[::1]/", "link.urlAddress"),
    ("an IPv4 address as one number", "https://2130706433/", "link.urlAddress"),
    ("an IPv4 address in hexadecimal", "https://0x7f.1/", "link.urlAddress"),
    ("an IPv4 address in octal", "https://0177.0.0.1/", "link.urlAddress"),
    ("a short IPv4 address", "https://127.1/", "link.urlAddress"),
    ("an IPv4 address in full-width digits", "https://127.0.0.１/", "link.urlAddress"),
    ("an IPv4 address with ideographic full stops", "https://127。0。0。1/", "link.urlAddress"),
    ("localhost", "https://localhost/x", "link.urlHost"),
    ("localhost with a port", "https://localhost:8080/x", "link.urlHost"),
    ("a name without a dot", "https://fileserver/x", "link.urlHost"),
    ("an intranet name", "https://intranet/x", "link.urlHost"),
    ("a name under localhost", "https://app.localhost/x", "link.urlHost"),
    ("a .local name", "https://printer.local/x", "link.urlHost"),
    ("a .internal name", "https://erp.corp.internal/x", "link.urlHost"),
    ("a .lan name", "https://nas.lan/x", "link.urlHost"),
    ("a .home.arpa name", "https://router.home.arpa/x", "link.urlHost"),
    ("a .corp name", "https://wiki.corp/x", "link.urlHost"),
    ("a .test name", "https://site.test/x", "link.urlHost"),
    ("an .onion name", "https://abc.onion/x", "link.urlHost"),
    ("a private name with ideographic full stops", "https://a.b。local/x", "link.urlHost"),
    ("an empty label", "https://shop..example.org/x", "link.urlHost"),
    ("a percent-encoded host", "https://%65xample.org/x", "link.urlHost"),
    ("a port that is not a number", "https://example.org:abc/x", "link.urlInvalid"),
]
for name, url, expected in REFUSED:
    got = outcome(lambda: gs1.normalise_url(url, 3))
    check(f"refused for every organisation: {name} → {expected}", got == expected, got)
try:
    gs1.normalise_url("https://user@example.org/x", 4)
except ValidationError as exc:
    check("…the message carries the target's position and the address", exc.params == {
        "position": 4, "url": "https://user@example.org/x"}, exc.params)
ACCEPTED = ["https://example.org/x", "https://shop.example.co.uk/p?q=1#a", "https://example.org:8443/x",
            "https://example.org./x", "https://bücher.de/x", "https://xn--bcher-kva.de/x", "https://my_site.example.org/",
            "https://1.example.org/x", "https://EXAMPLE.ORG/x", "https://id.acme.example/01/1"]
for url in ACCEPTED:
    check(f"accepted: {url}", outcome(lambda: gs1.normalise_url(url, 1)) == url)

r = save(edu, ACME_A, "https://example.org/ok", "https://10.0.0.5/x")
check("the editor refuses an address literal with its message and the target's position", r.status_code == 422
      and code(r) == "link.urlAddress" and r.get_json()["params"].get("position") == 2, r.get_json())
r = save(edu, ACME_A, "https://admin:pw@example.org/x")
check("…and user information", r.status_code == 422 and code(r) == "link.urlUserInfo", r.get_json())
r = save(edu, ACME_A, "https://localhost/x")
check("…and a name that is not a public one", r.status_code == 422 and code(r) == "link.urlHost", r.get_json())
check("…nothing was written", "01_" + ACME_A not in mock_data_entry.DB)

own = {"id.example.org"}
for name, url, expected in [("an address literal", "https://10.1.2.3/", "link.urlAddress"),
                            ("user information (its own rule before)", "https://u:p@resolver.example.net", "forwarding.urlInvalid"),
                            ("a private name", "https://resolver.internal", "link.urlHost")]:
    try:
        forwarding.check_target(url, own)
        got = "accepted"
    except forwarding.ForwardingError as exc:
        got = exc.code
    check(f"a forwarding destination refuses {name} → {expected}", got == expected, got)
check("…a public resolver is accepted", forwarding.check_target("https://resolver.example.net", own)
      == "https://resolver.example.net")

# --------------------------------------------------------------------------- the list: empty by default
d = page(ana)
check("the organisation's page shows the list: empty by default, editable, at most 50", d["targets"]["hosts"] == []
      and d["targets"]["editable"] is True and d["targets"]["max"] == targets.MAX_HOSTS == 50, d.get("targets"))
r = save(edu, ACME_A, "https://anywhere.example.net/x")
check("with an empty list any public host is saved", r.status_code in (200, 201), r.get_json())

# --------------------------------------------------------------------------- setting it
r = put_hosts(ana, acme["id"], "Example.ORG\n*.cdn.example.net, bücher.de\n.shop.example.com example.org")
kept = (r.get_json() or {}).get("targets", {})
check("an organisation's administrator sets it: cleaned (case, '*.', a leading dot, Punycode, repeats), sorted",
      r.status_code == 200 and code(r) == "targets.saved"
      and kept.get("hosts") == ["cdn.example.net", "example.org", "shop.example.com", "xn--bcher-kva.de"], r.get_json())
doc = store.col("tenants").find_one({"_id": acme["id"]})
check("…stored on the organisation, with who and when", doc.get("targetHosts") == kept.get("hosts")
      and doc.get("targetHostsBy") == "ana" and doc.get("targetHostsUpdated"), doc)
check("…shown on the page with who changed it", page(ana)["targets"]["updatedBy"] == "ana")
r = put_hosts(ana, acme["id"], ["example.org", "shop.example.com", "cdn.example.net", "xn--bcher-kva.de"])
check("…a list of names is accepted too; unchanged, not journalled again", r.status_code == 200
      and len(list(store.col("journal").find({"action": "target-hosts"}))) == 1)
for value, expected in [("https://example.org", "targets.hostInvalid"), ("example.org/path", "targets.hostInvalid"),
                        ("example.org:443", "targets.hostInvalid"), ("10.0.0.5", "targets.hostInvalid"),
                        ("localhost", "targets.hostInvalid"), ("fileserver", "targets.hostInvalid"),
                        ("user@example.org", "targets.hostInvalid"), ({"a": 1}, "targets.invalid"),
                        ([1, 2], "targets.invalid"),
                        (" ".join(f"h{i}.example.org" for i in range(51)), "targets.tooMany")]:
    r = put_hosts(ana, acme["id"], value)
    check(f"refused: {str(value)[:40]!r} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, r.get_json()))
check("…the list kept as it was", store.col("tenants").find_one({"_id": acme["id"]})["targetHosts"] == kept.get("hosts"))
r = put_hosts(ana, beta["id"], ["example.org"])
check("another organisation's list: 404 tenants.unknown", r.status_code == 404 and code(r) == "tenants.unknown"
      and not store.col("tenants").find_one({"_id": beta["id"]}).get("targetHosts"), (r.status_code, code(r)))
r = put_hosts(ana, "operator", ["example.org"])
check("…the operator's: 404 too", r.status_code == 404 and not store.get_setting(targets.SETTING))
r = put_hosts(edu, acme["id"], [])
check("an editor may not change it: 403", r.status_code == 403
      and store.col("tenants").find_one({"_id": acme["id"]})["targetHosts"] == kept.get("hosts"), r.status_code)

# --------------------------------------------------------------------------- saving with a list
r = save(edu, ACME_A, "https://example.org/a", "https://www.shop.example.com/b")
check("a listed host and a name under another are saved", r.status_code in (200, 201), r.get_json())
r = save(edu, ACME_A, "https://cdn.example.net/a", "https://bücher.de/b")
check("…an internationalised name matches its Punycode form", r.status_code in (200, 201), r.get_json())
r = save(edu, ACME_A, "https://example.org/a", "https://evilexample.org/b")
check("a host that only ends with the same letters is refused: link.urlNotAllowed with the host and position",
      r.status_code == 422 and code(r) == "link.urlNotAllowed" and r.get_json()["params"].get("host") == "evilexample.org"
      and r.get_json()["params"].get("position") == 2, r.get_json())
r = save(edu, ACME_A, "https://example.org.evil.net/a")
check("…and one that starts with a listed name", r.status_code == 422 and code(r) == "link.urlNotAllowed", r.get_json())
r = save(edu, ACME_A, "https://shop.example.com.evil.net/a")
check("…and the parent of a listed name is not under it", code(save(edu, ACME_A, "https://example.com/a")) == "link.urlNotAllowed"
      and code(r) == "link.urlNotAllowed")
r = save(edu, ACME_A, "https://example.org/a", landing=True)
check("the record's own page on the installation is saved although its host is not listed", r.status_code in (200, 201)
      and any(gs1.is_landing(link) for link in mock_data_entry.v3("01_" + ACME_A)[0]["links"]), r.get_json())
r = save(edu, ACME_B, "https://example.org/a")
r = edu.post("/portal/api/record", headers=ORIGIN, json={
    "key": "01", "value": ACME_B, "description": "Item", "links": [
        {"linkType": "gs1:pip", "url": "https://example.org/a", "hreflang": ["en"], "title": "t"},
        {"linkType": gs1.LANDING_TYPE, "url": "https://evil.example.net/01/1" + gs1.LANDING_QUERY, "hreflang": ["und"],
         "title": "t"}]})
check("…a page-like address on another host is checked like any target", r.status_code == 422
      and code(r) == "link.urlNotAllowed", r.get_json())
users.create("opa", "opa-password-long", "admin", must_change=False)
r = save(ope, OPER_A, "https://elsewhere.example.net/x")
check("the organisation's list does not apply to the operator's keys", r.status_code in (200, 201), r.get_json())
r = save(client("bia", "bia-password-long"), BETA_A, "https://elsewhere.example.net/x")
check("…nor to another organisation's", r.status_code in (200, 201), r.get_json())

# the API (records:write key of the organisation)
r = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"], "days": 30},
             headers=ORIGIN)
key = (r.get_json() or {}).get("key", "")
api = portal.app.test_client()
r = api.put(f"/portal/api/v1/records/01/{ACME_B}", headers={"Authorization": f"Bearer {key}"}, json={
    "description": "Item", "links": [{"linkType": "gs1:pip", "url": "https://elsewhere.example.net/x", "hreflang": ["en"]}]})
check("the API refuses a host not listed: 422 link.urlNotAllowed", r.status_code == 422 and code(r) == "link.urlNotAllowed",
      (r.status_code, r.get_json()))
r = api.put(f"/portal/api/v1/records/01/{ACME_B}", headers={"Authorization": f"Bearer {key}"}, json={
    "description": "Item", "links": [{"linkType": "gs1:pip", "url": "https://192.0.2.1/x", "hreflang": ["en"]}]})
check("…and an address literal: 422 link.urlAddress", r.status_code == 422 and code(r) == "link.urlAddress",
      (r.status_code, r.get_json()))
r = api.put(f"/portal/api/v1/records/01/{ACME_B}", headers={"Authorization": f"Bearer {key}"}, json={
    "description": "Item", "links": [{"linkType": "gs1:pip", "url": "https://shop.example.com/x", "hreflang": ["en"]}]})
check("…and saves a listed one", r.status_code in (200, 201), (r.status_code, r.get_json()))

# imports: every row reported with its number
table = ("gtin;description;linkType;url\n"
         f"{ACME_A};A;gs1:pip;https://example.org/a\n"
         f"{ACME_B};B;gs1:pip;https://elsewhere.example.net/b\n"
         f"{gtin('789123400003')};C;gs1:pip;https://user@example.org/c\n"
         f"{gtin('789123400004')};D;gs1:pip;https://[::1]/d\n")
preview = edu.post("/portal/api/import/preview", headers=ORIGIN, json={
    "filename": "t.csv", "content": base64.b64encode(table.encode()).decode(), "labels": {}}).get_json()
found = sorted((e["row"], e["code"]) for e in preview.get("errors", []))
check("an import reports each refused row with its number and code",
      found == [(3, "link.urlNotAllowed"), (4, "link.urlUserInfo"), (5, "link.urlAddress")], preview)

# --------------------------------------------------------------------------- the server administrators
r = put_hosts(root, beta["id"], ["example.net"])
check("a server administrator sets any organisation's list", r.status_code == 200
      and store.col("tenants").find_one({"_id": beta["id"]})["targetHosts"] == ["example.net"], r.get_json())
r = put_hosts(root, "operator", "example.com")
check("…and the operator's: the setting targets.hosts", r.status_code == 200
      and store.get_setting(targets.SETTING)["hosts"] == ["example.com"]
      and store.get_setting(targets.SETTING)["updatedBy"] == "root", store.get_setting(targets.SETTING))
check("…shown on the operator's page", page(root)["targets"]["hosts"] == ["example.com"])
r = save(ope, OPER_A, "https://elsewhere.example.net/x")
check("…which applies to the keys no organisation holds", r.status_code == 422 and code(r) == "link.urlNotAllowed",
      r.get_json())
check("…and lets a listed host through", save(ope, OPER_A, "https://www.example.com/x").status_code in (200, 201))
r = put_hosts(root, "nobody", ["example.com"])
check("…an organisation that does not exist: 404", r.status_code == 404 and code(r) == "tenants.unknown")
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 7"}, headers=ORIGIN)
r = put_hosts(root, acme["id"], [])
check("in support access: read only, 403 targets.readOnly", r.status_code == 403 and code(r) == "targets.readOnly"
      and page(root)["targets"]["editable"] is False, (r.status_code, code(r)))
root.delete("/portal/api/support", headers=ORIGIN)
r = put_hosts(ana, acme["id"], "")
check("an empty list accepts any public host again: targets.savedAny", r.status_code == 200
      and code(r) == "targets.savedAny" and save(edu, ACME_A, "https://elsewhere.example.net/x").status_code in (200, 201),
      r.get_json())

# --------------------------------------------------------------------------- the journal and the texts
details = sorted((e.get("tenant") or "-", e.get("detail")) for e in store.col("journal").find({"action": "target-hosts"}))
check("each change journalled once, in the organisation's (or the operator's) trail", details == sorted([
    (acme["id"], "hosts=cdn.example.net,example.org,shop.example.com,xn--bcher-kva.de"), (acme["id"], "hosts=-"),
    (beta["id"], "hosts=example.net"), ("-", "hosts=example.com")]), details)
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
check("the journal's label in both languages", i18n.count('"audit.action.target-hosts"') == 2)
app_js = open(os.path.join(PORTAL, "static", "app.js"), encoding="utf-8").read()
index = open(os.path.join(PORTAL, "static", "index.html"), encoding="utf-8").read()
check("the organisation's page has the tab and its editor", 'data-tab="targets"' in index
      and 'api("PUT", "targets/hosts"' in app_js and "org-target-hosts" in app_js)

print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
sys.exit(1 if failures else 0)
