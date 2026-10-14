"""
The organisations' own domains in the portal (Documentation/adr/0009-tenant-domains.md), through the portal's Flask
test client: who manages which domains (an organisation's administrators, the operator's by server administrators,
every domain listed for them, support access read only, nobody else); the rules of a name, a stem, a mode, uniqueness
and the limit; the proof by a DNS TXT record (looked up through a replaced domains.txt_records) and the daily look
again; default prefixes; the domain a label, the Digital Link preview, a record and the tenant API carry; the check
through the domain (domains.probe replaced); the journal; the texts in both languages.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_domains.py
"""
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

import requests
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3393
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_domains_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import apikeys  # noqa: E402
import app as portal  # noqa: E402
import domains  # noqa: E402
import tenants  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


acme = tenants.create("Acme Foods", ["7891234", "7891235"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))
ACME = "07891234500014"
ACME2 = "0789123500001" + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1)
                                             for i, d in enumerate(reversed("0789123500001"))) % 10) % 10)
ana.post("/portal/api/record", json={"key": "01", "value": ACME, "description": "Acme", "links": [
    {"linkType": "gs1:pip", "url": "https://acme.example.com/p", "hreflang": ["en"], "title": "t"}]}, headers=ORIGIN)

TXT = {}
domains.txt_records = lambda name: list(TXT.get(name, []))

# ================================================================== who manages which domains
r = ana.post("/portal/api/domains", json={"domain": "ID.Acme.Example.", "stem": "gs1/", "mode": "direct"}, headers=ORIGIN)
check("an organisation's administrator adds a domain (name tidied, stem with its slash)", r.status_code == 201
      and r.get_json()["item"]["domain"] == "id.acme.example" and r.get_json()["item"]["stem"] == "/gs1"
      and not r.get_json()["item"]["verified"], r.get_json())
item = r.get_json()["item"]
check("…with the TXT record to add", item["txtName"] == "_gs1resolver.id.acme.example"
      and re.fullmatch(r"gs1resolver-verify=[0-9a-f]{32}", item["txtValue"]), item)
check("an editor may not", edu.post("/portal/api/domains", json={"domain": "x.acme.example"}, headers=ORIGIN).status_code == 403
      and edu.get("/portal/api/domains").status_code == 403)
check("another organisation does not see it", bia.get("/portal/api/domains").get_json()["domains"] == [])
r = root.post("/portal/api/domains", json={"domain": "go.operator.example", "mode": "redirect"}, headers=ORIGIN)
check("a server administrator adds the operator's", r.status_code == 201, r.get_json())
listed = root.get("/portal/api/domains").get_json()
check("…and sees every domain with its organisation", listed["every"] and
      {d["domain"]: d.get("organisation") for d in listed["domains"]} == {"id.acme.example": "Acme Foods",
                                                                          "go.operator.example": None}, listed)
check("…but cannot change an organisation's", code(root.put("/portal/api/domains/id.acme.example",
      json={"stem": ""}, headers=ORIGIN)) == "domains.unknown")
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 3"}, headers=ORIGIN)
listed = root.get("/portal/api/domains").get_json()
check("support access: the organisation's domains, read only", [d["domain"] for d in listed["domains"]]
      == ["id.acme.example"] and listed["readOnly"] and not listed["every"], listed)
r = root.post("/portal/api/domains", json={"domain": "z.acme.example"}, headers=ORIGIN)
check("…a change refused (403 domains.readOnly)", r.status_code == 403 and code(r) == "domains.readOnly", r.status_code)
root.delete("/portal/api/support", headers=ORIGIN)

# ================================================================== rules
for payload, expected in [({"domain": "localhost"}, "domains.nameInvalid"),
                          ({"domain": "192.168.0.1"}, "domains.nameInvalid"),
                          ({"domain": "acme"}, "domains.nameInvalid"),
                          ({"domain": "-x.acme.example"}, "domains.nameInvalid"),
                          ({"domain": "a b.example"}, "domains.nameInvalid"),
                          ({"domain": "id.example.org"}, "domains.installationName"),
                          ({"domain": "https://id.acme.example/gs1"}, "domains.exists"),
                          ({"domain": "y.acme.example", "stem": "/01"}, "domains.stemInvalid"),
                          ({"domain": "y.acme.example", "stem": "/a/b/c/d"}, "domains.stemInvalid"),
                          ({"domain": "y.acme.example", "stem": "/a b"}, "domains.stemInvalid"),
                          ({"domain": "y.acme.example", "mode": "proxy"}, "domains.modeInvalid")]:
    r = ana.post("/portal/api/domains", json=payload, headers=ORIGIN)
    check(f"refused: {payload} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
r = bia.post("/portal/api/domains", json={"domain": "id.acme.example"}, headers=ORIGIN)
check("a name is unique in the installation (another organisation cannot claim it)", code(r) == "domains.exists")
r = ana.post("/portal/api/domains", json={"domain": "açaí.acme.example"}, headers=ORIGIN)
check("an internationalised name is kept in Punycode", r.status_code == 201
      and r.get_json()["item"]["domain"] == "açaí.acme.example".encode("idna").decode(), r.get_json())
for n in range(8):
    ana.post("/portal/api/domains", json={"domain": f"d{n}.acme.example"}, headers=ORIGIN)
r = ana.post("/portal/api/domains", json={"domain": "eleven.acme.example"}, headers=ORIGIN)
check("at most 10 per organisation", code(r) == "domains.tooMany" and r.get_json()["params"]["max"] == 10, code(r))
for n in range(8):
    ana.delete(f"/portal/api/domains/d{n}.acme.example", headers=ORIGIN)

# ================================================================== proof by DNS
r = ana.post("/portal/api/domains/id.acme.example/verify", json={}, headers=ORIGIN)
check("verify without the TXT record: refused, with the record to add", code(r) == "domains.txtMissing"
      and r.get_json()["params"]["value"] == item["txtValue"], r.get_json())
TXT["_gs1resolver.id.acme.example"] = ["v=spf1 -all", item["txtValue"]]
r = ana.post("/portal/api/domains/id.acme.example/verify", json={}, headers=ORIGIN)
check("with it: verified", code(r) == "domains.verified" and r.get_json()["item"]["verified"]
      and r.get_json()["item"]["seenAt"], r.get_json())
TXT.clear()
r = ana.post("/portal/api/domains/id.acme.example/verify", json={}, headers=ORIGIN)
check("the record removed later: still verified (printed codes keep working)", r.status_code == 200
      and r.get_json()["item"]["verified"], r.get_json())
doc = store.col("domains").find_one({"_id": "id.acme.example"})
store.col("domains").update_one({"_id": "id.acme.example"}, {"$set": {"seenAt": doc["seenAt"] - timedelta(days=2)}})
check("the daily look again records nothing when the record is gone", domains.recheck_all() == 0
      and store.col("domains").find_one({"_id": "id.acme.example"})["verified"])
TXT["_gs1resolver.id.acme.example"] = [item["txtValue"]]
check("…and when it was last seen when it is there", domains.recheck_all() == 1
      and store.col("domains").find_one({"_id": "id.acme.example"})["seenAt"] > doc["seenAt"])
check("…once a day", domains.recheck_all() == 0)
check("the look again is part of the worker's housekeeping", domains.recheck_all in portal.HOUSEKEEPING)

# ================================================================== defaults and labels
r = ana.put("/portal/api/domains/id.acme.example", json={"defaultFor": ["7895555"]}, headers=ORIGIN)
check("a default prefix must be the organisation's", code(r) == "domains.prefixOutside")
r = ana.put("/portal/api/domains/id.acme.example", json={"defaultFor": ["7891234"]}, headers=ORIGIN)
check("default for one of its prefixes", r.status_code == 200 and r.get_json()["item"]["defaultFor"] == ["7891234"])
ana.post("/portal/api/domains", json={"domain": "two.acme.example"}, headers=ORIGIN)
r = ana.put("/portal/api/domains/two.acme.example", json={"defaultFor": ["7891234"]}, headers=ORIGIN)
check("a prefix is the default of one domain at most", code(r) == "domains.prefixTaken"
      and r.get_json()["params"]["domain"] == "id.acme.example", r.get_json())
r = root.put("/portal/api/domains/go.operator.example", json={"defaultFor": ["7891234"]}, headers=ORIGIN)
check("the operator's default prefixes cannot be an organisation's", code(r) == "domains.prefixOutside")
cfg = ana.get("/portal/api/config").get_json()["domains"]
check("the configuration gives the label panel the verified domains only", cfg == {
    "installation": "https://id.example.org",
    "verified": [{"domain": "id.acme.example", "url": "https://id.acme.example/gs1", "defaultFor": ["7891234"]}]}, cfg)


def preview(c, value, **extra):
    r = c.post("/portal/api/digital-link", json={"key": "01", "value": value, **extra}, headers=ORIGIN)
    return r.get_json().get("uri") if r.status_code == 200 else (r.status_code, code(r))


check("the Digital Link of a record of a default prefix carries the domain and its stem",
      preview(ana, ACME) == f"https://id.acme.example/gs1/01/{ACME}", preview(ana, ACME))
check("…of another prefix, the installation's", preview(ana, ACME2) == f"https://id.example.org/01/{ACME2}")
check("…the installation's when chosen", preview(ana, ACME, domain="installation") == f"https://id.example.org/01/{ACME}")
check("…a verified domain chosen for any prefix of the organisation",
      preview(ana, ACME2, domain="id.acme.example") == f"https://id.acme.example/gs1/01/{ACME2}")
check("…a domain not verified: 422 domains.unusable", preview(ana, ACME, domain="two.acme.example")
      == (422, "domains.unusable"))
check("…another organisation's domain: 422", preview(bia, "07895555000017", domain="id.acme.example")
      == (422, "domains.unusable"))
check("…data attributes after the domain's path too", str(preview(ana, ACME, attributes=[]))
      .startswith("https://id.acme.example/gs1/"))
record = ana.get(f"/portal/api/record?key=01&value={ACME}").get_json()
check("the record's Digital Link uses its default domain", record["digitalLink"] == f"https://id.acme.example/gs1/01/{ACME}",
      record.get("digitalLink"))
r = ana.get(f"/portal/api/qrcode?key=01&value={ACME}&domain=id.acme.example")
check("the label with a domain", r.status_code == 200 and r.mimetype == "image/svg+xml")
r = ana.get(f"/portal/api/qrcode?key=01&value={ACME}&domain=nope.example")
check("…a domain the scope does not have: 422", r.status_code == 422 and code(r) == "domains.unusable")
long_qr = ana.get(f"/portal/api/qrcode?key=01&value={ACME}&version=1&domain=id.acme.example")
check("…the longer address is what the QR code holds (version 1 is too small for it)", long_qr.status_code == 422
      and code(long_qr) == "qr.tooSmall", code(long_qr))
key, _ = apikeys.create("Labels", ["labels:read", "records:read"], 30, [], acme["id"], "ana")
api = portal.app.test_client()
auth = {"Authorization": f"Bearer {key}"}
r = api.get(f"/portal/api/v1/records/01/{ACME}", headers=auth)
check("tenant API: the record's Digital Link on its default domain", r.get_json()["digitalLink"]
      == f"https://id.acme.example/gs1/01/{ACME}", r.get_json())
check("…labels take domain=", api.get(f"/portal/api/v1/labels/01/{ACME}?domain=installation", headers=auth).status_code == 200
      and api.get(f"/portal/api/v1/labels/01/{ACME}?domain=nope.example", headers=auth).status_code == 422)

# ================================================================== the check through the domain


class Answer:
    def __init__(self, status, headers=None, body=None):
        self.status_code, self.headers, self._body = status, headers or {}, body

    def json(self):
        return self._body


ANSWERS = {}


def probe(url):
    found = ANSWERS.get(url)
    if isinstance(found, Exception):
        raise found
    return found or Answer(404)


domains.probe = probe
ANSWERS["https://id.acme.example/.well-known/gs1resolver"] = Answer(200, {"Content-Type": "application/json"},
                                                                     {"resolverRoot": "https://id.acme.example/gs1"})
r = ana.post("/portal/api/domains/id.acme.example/check", json={}, headers=ORIGIN)
check("check of a direct domain: the description file answers", code(r) == "domains.checkOk"
      and r.get_json()["item"]["check"]["ok"], r.get_json())
ANSWERS["https://id.acme.example/.well-known/gs1resolver"] = Answer(200, {"Content-Type": "text/html"}, None)
r = ana.post("/portal/api/domains/id.acme.example/check", json={}, headers=ORIGIN)
check("…a page that is not this resolver's", code(r) == "domains.checkNotResolver", code(r))
ANSWERS["https://id.acme.example/.well-known/gs1resolver"] = requests.ConnectionError("refused")
r = ana.post("/portal/api/domains/id.acme.example/check", json={}, headers=ORIGIN)
check("…no answer", code(r) == "domains.checkUnreachable" and r.get_json()["params"]["detail"] == "ConnectionError")
ANSWERS["https://id.acme.example/.well-known/gs1resolver"] = PermissionError("private")
r = ana.post("/portal/api/domains/id.acme.example/check", json={}, headers=ORIGIN)
check("…a private address is not requested", code(r) == "domains.checkPrivate")
ana.put("/portal/api/domains/two.acme.example", json={"mode": "redirect", "stem": "/id"}, headers=ORIGIN)
expected = f"https://id.example.org/01/{ACME}?linkType=all"
ANSWERS[f"https://two.acme.example/id/01/{ACME}?linkType=all"] = Answer(308, {"Location": expected})
r = ana.post("/portal/api/domains/two.acme.example/check", json={}, headers=ORIGIN)
check("check of a redirecting domain: a code of the organisation redirected with its path and query",
      code(r) == "domains.checkOk", r.get_json())
ANSWERS[f"https://two.acme.example/id/01/{ACME}?linkType=all"] = Answer(302, {"Location": "https://id.example.org/"})
r = ana.post("/portal/api/domains/two.acme.example/check", json={}, headers=ORIGIN)
check("…a redirect that loses the path", code(r) == "domains.checkRedirect" and "302" in r.get_json()["params"]["detail"])
kept = {d["domain"]: d for d in ana.get("/portal/api/domains").get_json()["domains"]}["two.acme.example"]["check"]
check("…the last check is kept", kept and kept["problem"] == "domains.checkRedirect", kept)
saved_probe = domains.probe
del domains.probe
import importlib  # noqa: E402
fresh = importlib.reload(domains)
try:
    fresh.probe("https://127.0.0.1/x")
    refused = False
except PermissionError:
    refused = True
check("the real probe refuses a private address (the link checker's guard)", refused)
domains.probe, domains.txt_records = probe, (lambda name: list(TXT.get(name, [])))

# ================================================================== removal and the journal
r = ana.delete("/portal/api/domains/two.acme.example", headers=ORIGIN)
check("removed", code(r) == "domains.removed" and store.col("domains").count_documents({"_id": "two.acme.example"}) == 0)
actions = {e["action"] for e in store.col("journal").find({"tenant": acme["id"]})}
check("the journal: added, verified, changed, removed", {"domain-create", "domain-verify", "domain-update",
                                                         "domain-remove"} <= actions, actions)

# ================================================================== texts
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(domains\.[A-Za-z.]+)"', open(os.path.join(PORTAL, "domains.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read()))
codes |= {"menu.domains", "label.domain", "label.domainDefault", "domains.mode.direct", "domains.mode.redirect"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"every domains text in both languages ({len(codes)})", not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
