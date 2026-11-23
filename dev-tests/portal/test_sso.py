"""
Single sign-on per organisation with OpenID Connect (Documentation/adr/0012-single-sign-on.md, backlog item 7.1),
through the portal's Flask test client and a stand-in provider (fake_oidc.py): who configures which organisation's
sign-on (its administrators, a server administrator every one, support access read only), the rules of a
configuration (complete when on, the secret write-only, domains unique, https and public addresses unless allowed),
the provider's test; the sign-in itself (the authorization request with PKCE, state, nonce and the e-mail as hint;
the token request with the client's secret and the verifier; the session, the journal) and every refusal (a state
that does not match or is old or used twice, the provider refusing, its token endpoint failing, an ID token with a
wrong nonce, audience, issuer, expiry, key or algorithm, no verified e-mail, an e-mail of another domain, no account
or another organisation's, a disabled account or organisation); a new key of the provider; password sign-in off for
the organisation (not for server administrators, nor password recovery); the temporary password not asked after
single sign-on; the client secret sealed in the database with the data key (ADR 0044): in place of the text, opened
only in its own configuration, sealed at the start when stored in clear, earlier keys, a lost key; the texts in both
languages.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_sso.py
"""
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3397
IDP_PORT = 3398
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_sso_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)
os.environ["PORTAL_SSO_ALLOW_INSECURE"] = "1"      # the stand-in provider is on http://127.0.0.1

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
import fake_oidc  # noqa: E402
import sso  # noqa: E402
import requests as http  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402
import gs1  # noqa: E402
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


def gtin(body):
    return body + str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body))) % 10) % 10)


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))



users.update("ana", email="ana@acme.example")
users.update("edu", email="edu@acme.example")
users.update("bia", email="bia@beta.example")
users.create("rui", "rui-password-long", "reader", tenant=beta["id"], email="rui@acme.example", must_change=False)
users.create("off", "off-password-long", "reader", tenant=acme["id"], email="off@acme.example", must_change=False)
users.update("off", disabled=True)
users.create("new", "temporary-password", "reader", tenant=acme["id"], email="new@acme.example", must_change=True)
users.update("root", email="root@operator.example")
provider = fake_oidc.FakeProvider(IDP_PORT)
CALLBACK = "https://id.example.org/portal/sso/callback"
CONFIG = {"issuer": provider.issuer, "clientId": provider.client_id, "clientSecret": provider.client_secret,
          "domains": "Acme.Example, @acme.example", "enabled": True}

# ================================================================== configurations
r = ana.get("/portal/api/sso")
data = r.get_json() or {}
check("an organisation's administrator: its configuration (none yet), the address to register", r.status_code == 200
      and data["configs"] == [] and data["scope"] == acme["id"] and data["callback"] == CALLBACK and not data["every"],
      data)
check("an editor may not", edu.get("/portal/api/sso").status_code == 403
      and edu.put(f"/portal/api/sso/{acme['id']}", json=CONFIG, headers=ORIGIN).status_code == 403)
r = ana.put(f"/portal/api/sso/{acme['id']}", json={**CONFIG, "clientSecret": ""}, headers=ORIGIN)
check("switched on without a secret: refused, naming what is missing", code(r) == "sso.incomplete"
      and "clientSecret" in r.get_json()["params"]["fields"], r.get_json())
r = ana.put(f"/portal/api/sso/{acme['id']}", json=CONFIG, headers=ORIGIN)
item = (r.get_json() or {}).get("item") or {}
check("saved: domains tidied (case, @, repeats), the secret never given back", code(r) == "sso.saved"
      and item.get("domains") == ["acme.example"] and item.get("secretSet") is True and "clientSecret" not in item
      and provider.client_secret not in r.get_data(as_text=True), r.get_json())
r = ana.put(f"/portal/api/sso/{acme['id']}", json={"clientId": provider.client_id}, headers=ORIGIN)
check("a change without a secret keeps it", r.get_json()["item"]["secretSet"]
      and sso.client_secret(store.col("sso").find_one({"_id": acme["id"]})) == provider.client_secret)
check("…and nothing lists it", provider.client_secret not in ana.get("/portal/api/sso").get_data(as_text=True))
ana.put(f"/portal/api/sso/{acme['id']}", json={"clientSecret": "", "clientId": provider.client_id}, headers=ORIGIN)
check("an empty secret field (as the screen sends it) keeps the secret",
      sso.client_secret(store.col("sso").find_one({"_id": acme["id"]})) == provider.client_secret)
r = bia.put(f"/portal/api/sso/{acme['id']}", json=CONFIG, headers=ORIGIN)
check("another organisation's administrator may not touch it", r.status_code == 403 and code(r) == "sso.scopeOutside")

# ------------------------------------------------------------------ e-mail domains proved (ADR 0025)
TXT = {}                                           # the stand-in DNS: name -> TXT strings
portal.domains.txt_records = lambda name: TXT.get(name, [])
states = {s["domain"]: s for s in item["domainStates"]}
token = store.col("sso").find_one({"_id": acme["id"]})["token"]
check("a listed domain waits for its proof; the screen shows the TXT record to publish",
      states["acme.example"]["proof"] is None and states["acme.example"]["txtName"] == "_gs1resolver.acme.example"
      and states["acme.example"]["txtValue"] == f"gs1resolver-sso={token}" and len(token) == 32, states)
r = portal.app.test_client().post("/portal/api/sso/start", json={"email": "edu@acme.example"}, headers=ORIGIN)
check("…and signs nobody in until then", code(r) == "sso.noProvider", r.get_json())
r = bia.put(f"/portal/api/sso/{beta['id']}", json={**CONFIG, "domains": ["beta.example", "acme.example"]}, headers=ORIGIN)
check("another organisation may list a domain nobody has proved", code(r) == "sso.saved", r.get_json())
r = ana.post(f"/portal/api/sso/{acme['id']}/verify", json={"domain": "acme.example"}, headers=ORIGIN)
check("verify without the record: refused, naming the record", r.status_code == 422 and code(r) == "sso.txtMissing"
      and r.get_json()["params"] == {"name": "_gs1resolver.acme.example", "value": f"gs1resolver-sso={token}"},
      r.get_json())
r = ana.post(f"/portal/api/sso/{acme['id']}/approve", json={"domain": "acme.example"}, headers=ORIGIN)
check("an organisation's administrator cannot approve a domain", r.status_code == 403, r.get_json())
r = root.post(f"/portal/api/sso/{acme['id']}/approve", json={"domain": "acme.example"}, headers=ORIGIN)
check("a server administrator's approval: refused while another organisation's account uses the domain (rui, Beta)",
      code(r) == "sso.domainUsed" and r.get_json()["params"]["domain"] == "acme.example", r.get_json())
TXT["_gs1resolver.acme.example"] = ["v=other", f"gs1resolver-verify=abc", f"gs1resolver-sso={token}"]
r = ana.post(f"/portal/api/sso/{acme['id']}/verify", json={"domain": "Acme.Example"}, headers=ORIGIN)
proof = (store.col("sso").find_one({"_id": acme["id"]}).get("proofs") or [{}])[0]
check("the record published: proved by DNS (beside other records at the name), by whom", code(r) == "sso.domainProved"
      and r.get_json()["item"]["domainStates"][0]["proof"] == "dns" and proof.get("domain") == "acme.example"
      and proof.get("by") == "ana" and proof.get("how") == "dns", (r.get_json(), proof))
TXT["_gs1resolver.acme.example"].append(
    "gs1resolver-sso=" + store.col("sso").find_one({"_id": beta["id"]})["token"])
r = bia.post(f"/portal/api/sso/{beta['id']}/verify", json={"domain": "acme.example"}, headers=ORIGIN)
r2 = root.post(f"/portal/api/sso/{beta['id']}/approve", json={"domain": "acme.example"}, headers=ORIGIN)
r3 = bia.put(f"/portal/api/sso/{beta['id']}", json={"clientId": provider.client_id}, headers=ORIGIN)
check("a domain is proved in one configuration: another's verify, approval and save refused", code(r) == "sso.domainTaken"
      and code(r2) == "sso.domainTaken" and code(r3) == "sso.domainTaken", (code(r), code(r2), code(r3)))
r = bia.post(f"/portal/api/sso/{beta['id']}/verify", json={"domain": "gamma.example"}, headers=ORIGIN)
check("…and a domain the configuration does not list", code(r) == "sso.domainNotListed", r.get_json())
bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta.example"]}, headers=ORIGIN)
r = root.post(f"/portal/api/sso/{beta['id']}/approve", json={"domain": "beta.example"}, headers=ORIGIN)
check("a server administrator approves a domain nobody else uses", code(r) == "sso.domainApproved"
      and r.get_json()["item"]["domainStates"][0]["proof"] == "admin"
      and r.get_json()["item"]["domainStates"][0]["provedBy"] == "root", r.get_json())
bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta.example", "beta2.example"]}, headers=ORIGIN)
r = bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta2.example"]}, headers=ORIGIN)
r2 = bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta.example", "beta2.example"]}, headers=ORIGIN)
check("a domain removed from the list loses its proof; listed again, it waits again",
      [s["proof"] for s in r.get_json()["item"]["domainStates"]] == [None]
      and [s["proof"] for s in r2.get_json()["item"]["domainStates"]] == [None, None], r2.get_json())
domain_events = [e["detail"] for e in store.col("journal").find({"action": "sso-domain"})]
check("the journal: each proof and approval", domain_events == ["acme.example proved by DNS", "beta.example approved"],
      domain_events)

# ------------------------------------------------------------------ DNS proofs looked at again; lapsed (ADR 0035)
def acme_proof():
    return next(p for p in store.col("sso").find_one({"_id": acme["id"]})["proofs"] if p["domain"] == "acme.example")


def set_proof(**fields):
    doc = store.col("sso").find_one({"_id": acme["id"]})
    proofs = [{**p, **fields} if p["domain"] == "acme.example" else p for p in doc["proofs"]]
    store.col("sso").update_one({"_id": acme["id"]}, {"$set": {"proofs": proofs}})


check("a DNS proof records when its record was seen", acme_proof().get("seenAt") == acme_proof()["at"], acme_proof())
saved_txt = dict(TXT)
TXT.clear()
set_proof(seenAt=store.now() - timedelta(days=2))
check("the daily look: the record missing for 2 days, nothing lapses", portal.sso.recheck_proofs() == []
      and "lapsedAt" not in acme_proof())
TXT.update(saved_txt)
portal.sso.recheck_proofs()
check("…the record there: seen now", store.now() - acme_proof()["seenAt"] < timedelta(minutes=1), acme_proof())
set_proof(seenAt=store.now() - timedelta(hours=1))
portal.sso.recheck_proofs()
check("…looked at once a day", timedelta(minutes=59) < store.now() - acme_proof()["seenAt"] < timedelta(minutes=61))
TXT.clear()
set_proof(seenAt=store.now() - timedelta(days=7, hours=1))
store.col("sso").update_one({"_id": acme["id"]}, {"$push": {"proofs":
    {"domain": "old.acme.example", "how": "admin", "at": store.now() - timedelta(days=30), "by": "root"}}})
mails = []
real_send = portal.notify.send
portal.notify.send = lambda user, template, **params: mails.append((user, template, params)) or True
lapsed_count = portal.recheck_domains()
portal.notify.send = real_send
check("missing for 7 days: the proof has lapsed", lapsed_count == 1 and acme_proof().get("lapsedAt"), acme_proof())
check("…an approval has no record to look at and never lapses", [p for p in store.col("sso").find_one(
      {"_id": acme["id"]})["proofs"] if p["domain"] == "old.acme.example" and "lapsedAt" not in p])
store.col("sso").update_one({"_id": acme["id"]}, {"$pull": {"proofs": {"domain": "old.acme.example"}}})
event = store.col("journal").find_one({"action": "domain-lapsed"})
check("…journalled in the organisation's trail ('sso <domain>')", event and event.get("tenant") == acme["id"]
      and event["detail"].startswith("sso acme.example record missing since ") and event["user"] == "-", event)
check("…its administrators told", [(u, t, p["domain"], p["record"]) for u, t, p in mails]
      == [("ana", "alert-domain-lapsed", "acme.example", "_gs1resolver.acme.example")], mails)
check("…once", portal.recheck_domains() == 0)
state = portal.sso.public(store.col("sso").find_one({"_id": acme["id"]}))["domainStates"][0]
check("…the screen shows it, with when the record was last seen", state["lapsedAt"] and state["seenAt"]
      and state["proof"] == "dns", state)
check("…and it still signs people in (nobody locked out)", (portal.sso.for_email("edu@acme.example") or {}).get("_id")
      == acme["id"])
r = bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta.example", "acme.example"]}, headers=ORIGIN)
check("another configuration may list a domain whose proof lapsed", code(r) == "sso.saved", r.get_json())
r = root.post(f"/portal/api/sso/{beta['id']}/approve", json={"domain": "acme.example"}, headers=ORIGIN)
check("…an approval is still refused while another organisation's account uses it", code(r) == "sso.domainUsed")
TXT.update(saved_txt)
r = bia.post(f"/portal/api/sso/{beta['id']}/verify", json={"domain": "acme.example"}, headers=ORIGIN)
check("…and proving it takes it over: the lapsed proof goes", code(r) == "sso.domainProved"
      and "acme.example" not in [p["domain"] for p in store.col("sso").find_one({"_id": acme["id"]})["proofs"]]
      and "acme.example" in portal.sso.proved(store.col("sso").find_one({"_id": beta["id"]})), r.get_json())
event = store.col("journal").find_one({"action": "domain-released"})
check("…journalled in the first organisation's trail", event and event.get("tenant") == acme["id"]
      and event["detail"] == "sso acme.example proved elsewhere", event)
bia.put(f"/portal/api/sso/{beta['id']}", json={"domains": ["beta.example"]}, headers=ORIGIN)
r = ana.post(f"/portal/api/sso/{acme['id']}/verify", json={"domain": "acme.example"}, headers=ORIGIN)
check("a lapsed proof proved again is a fresh proof", code(r) == "sso.domainProved" and "lapsedAt" not in acme_proof())
set_proof(lapsedAt=store.now(), seenAt=store.now() - timedelta(days=9))
portal.sso.recheck_proofs()
check("…and a lapsed proof whose record the daily look finds again is no longer lapsed", "lapsedAt" not in acme_proof()
      and store.now() - acme_proof()["seenAt"] < timedelta(minutes=1), acme_proof())
bia.delete(f"/portal/api/sso/{beta['id']}", headers=ORIGIN)
for payload, expected in (({"domains": "not a domain"}, "sso.domainInvalid"), ({"domains": "localhost"}, "sso.domainInvalid"),
                          ({"issuer": "ftp://x.example"}, "sso.issuerInvalid"),
                          ({"issuer": "https://user:pw@x.example"}, "sso.issuerInvalid"),
                          ({"clientId": "a\nb"}, "sso.clientIdInvalid"),
                          ({"domains": [f"d{n}.example" for n in range(21)]}, "sso.domainsTooMany")):
    r = bia.put(f"/portal/api/sso/{beta['id']}", json=payload, headers=ORIGIN)
    check(f"refused: {payload} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, code(r)))
os.environ["PORTAL_SSO_ALLOW_INSECURE"] = ""
r = bia.put(f"/portal/api/sso/{beta['id']}", json={"issuer": "http://login.beta.example"}, headers=ORIGIN)
r2 = bia.put(f"/portal/api/sso/{beta['id']}", json={"issuer": "https://127.0.0.1:8443"}, headers=ORIGIN)
check("without PORTAL_SSO_ALLOW_INSECURE: http and private addresses refused", code(r) == "sso.issuerInvalid"
      and code(r2) == "sso.issuerPrivate", (code(r), code(r2)))
os.environ["PORTAL_SSO_ALLOW_INSECURE"] = "1"
listed = root.get("/portal/api/sso").get_json()
check("a server administrator lists every configuration with its organisation", listed["every"]
      and [(c["scope"], c["organisation"]) for c in listed["configs"]] == [(acme["id"], "Acme Foods")]
      and {o["name"] for o in listed["organisations"]} == {"Acme Foods", "Beta Drinks"}, listed)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 11"}, headers=ORIGIN)
listed = root.get("/portal/api/sso").get_json()
r = root.put(f"/portal/api/sso/{acme['id']}", json={"enabled": False}, headers=ORIGIN)
check("support access: the organisation's configuration, read only", listed["readOnly"] and not listed["every"]
      and [c["scope"] for c in listed["configs"]] == [acme["id"]] and r.status_code == 403, (listed, r.status_code))
root.delete("/portal/api/support", headers=ORIGIN)
root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 12"}, headers=ORIGIN)
r = root.post(f"/portal/api/sso/{acme['id']}/test", json={}, headers=ORIGIN)
check("support access may run the organisation's provider test", code(r) == "sso.testOk", r.get_json())
root.delete("/portal/api/support", headers=ORIGIN)
root.put("/portal/api/sso/operator", json={"issuer": provider.issuer, "clientId": "op", "clientSecret": "x",
                                          "domains": ["operator.example"]}, headers=ORIGIN)
r = ana.post("/portal/api/sso/operator/test", json={}, headers=ORIGIN)
r2 = root.post("/portal/api/sso/operator/test", json={}, headers=ORIGIN)
check("an organisation's administrator may not run the operator's provider test; a server administrator may",
      r.status_code == 403 and code(r) == "sso.scopeOutside" and code(r2) == "sso.testOk", (code(r), code(r2)))
root.delete("/portal/api/sso/operator", headers=ORIGIN)
r = ana.post(f"/portal/api/sso/{acme['id']}/test", json={}, headers=ORIGIN)
check("the provider's test: discovery and keys read", code(r) == "sso.testOk" and r.get_json()["result"]["keys"] == 1,
      r.get_json())
provider.NEXT["discovery_issuer"] = "http://elsewhere.example"
r = ana.post(f"/portal/api/sso/{acme['id']}/test", json={}, headers=ORIGIN)
check("…a discovery document naming another issuer fails the test", code(r) == "sso.discoveryFailed"
      and "elsewhere" in r.get_json()["result"]["detail"], r.get_json())
provider.reset()
sso.forget()
check("the sign-in page is told single sign-on is offered",
      portal.app.test_client().get("/portal/api/login/options").get_json()["sso"] is True)

# ================================================================== signing in
LAST = []


def sign_in(email, browser=None, tamper=None):
    """The whole round: the page's start, the provider, the callback. (response of the callback, browser)"""
    browser = browser or portal.app.test_client()
    r = browser.post("/portal/api/sso/start", json={"email": email, "language": "en-GB"}, headers=ORIGIN)
    if r.status_code != 200:
        return r, browser
    answer = http.get(r.get_json()["url"], allow_redirects=False, timeout=5)
    target = urlparse(answer.headers["Location"])
    query = target.query if not tamper else tamper(target.query)
    LAST[:] = [target.path + "?" + query]
    return browser.get(target.path + "?" + query), browser


def landed(r):
    return r.headers.get("Location", "")


provider.NEXT["email"] = "edu@acme.example"
r, browser = sign_in("EDU@acme.example")
asked = next(q for q in reversed(provider.requests) if q["endpoint"] == "authorize")
check("the authorization request: code flow, PKCE S256, state, nonce, the callback, the e-mail as hint",
      asked["response_type"] == "code" and asked["code_challenge_method"] == "S256" and len(asked["code_challenge"]) == 43
      and len(asked["state"]) >= 32 and len(asked["nonce"]) >= 32 and asked["redirect_uri"] == CALLBACK
      and asked["login_hint"] == "edu@acme.example" and "openid" in asked["scope"].split()
      and asked["client_id"] == provider.client_id, asked)
token_call = next(q for q in reversed(provider.requests) if q["endpoint"] == "token")
check("the token request: the client's secret and the PKCE verifier (checked by the provider)",
      token_call["client_secret"] == provider.client_secret and len(token_call["code_verifier"]) >= 43)
check("signed in: on to the overview", r.status_code == 302 and landed(r).endswith("/portal/#overview"), landed(r))
me = browser.get("/portal/api/config").get_json() or {}
check("…the session is the account's, with its role and organisation", me.get("user") == "edu"
      and me.get("role") == "editor" and me.get("tenant", {}).get("id") == acme["id"], me)
event = store.col("journal").find_one({"action": "login", "user": "edu"}, sort=[("at", -1)])
check("…the journal says single sign-on and the provider", event and "single sign-on 127.0.0.1" in event.get("detail", ""),
      event)
check("…the configuration's last sign-in noted", store.col("sso").find_one({"_id": acme["id"]}).get("lastLogin"))
r2 = browser.get(LAST[0])
check("the same answer used twice: refused (the flow is spent)", landed(r2).endswith("/portal/login?sso=expired"),
      landed(r2))


def refused(name, expected, email="edu@acme.example", setup=None, tamper=None, start_email=None):
    provider.reset()
    provider.NEXT["email"] = email
    if setup:
        setup()
    r, _ = sign_in(start_email or email, tamper=tamper)
    if r.status_code == 302:
        ok = landed(r).endswith(f"/portal/login?sso={expected}")
    else:
        ok = code(r) == f"sso.{expected}"
    check(f"refused: {name} → {expected}", ok, landed(r) or (r.status_code, r.get_json()))


refused("another state", "expired", tamper=lambda q: re.sub(r"state=[^&]+", "state=forged", q))
refused("the provider refusing", "providerRefused", setup=lambda: provider.NEXT.update(error="access_denied"))
refused("the token endpoint failing", "tokenFailed", setup=lambda: provider.NEXT.update(token_status=500))
refused("no ID token", "tokenFailed", setup=lambda: provider.NEXT.update(no_id_token=True))
refused("another nonce", "tokenInvalid", setup=lambda: provider.NEXT.update(nonce="forged"))
refused("another audience", "tokenInvalid", setup=lambda: provider.NEXT.update(aud="someone-else"))
refused("another issuer", "tokenInvalid", setup=lambda: provider.NEXT.update(iss="http://evil.example"))
refused("an expired token", "tokenInvalid", setup=lambda: provider.NEXT.update(exp=-3600))
refused("a token signed by an unknown key", "tokenInvalid",
        setup=lambda: provider.NEXT.update(key=fake_oidc._new_key("key-1")))
refused("a token signed with a shared secret (HS256)", "tokenInvalid", setup=lambda: provider.NEXT.update(alg="HS256"))
refused("an e-mail the provider has not verified", "noEmail", setup=lambda: provider.NEXT.update(email_verified=False))
refused("no e-mail", "noEmail", email=None, start_email="edu@acme.example")
refused("an e-mail of another domain", "domainMismatch", email="bia@beta.example", start_email="edu@acme.example")
refused("no account with that e-mail", "noAccount", email="nobody@acme.example")
refused("the e-mail of another organisation's account", "noAccount", email="rui@acme.example")
# ADR 0036 (finding F-019): an address may be used once per organisation; the configuration's organisation's account
# signs in even when another organisation's account has the same address (rui, Beta, was made first)
users.create("rui2", "rui2-password-long", "reader", tenant=acme["id"], email="rui@acme.example", must_change=False)
provider.reset()
provider.NEXT["email"] = "rui@acme.example"
r, browser = sign_in("rui@acme.example")
me = browser.get("/portal/api/config").get_json() or {}
check("the same address in two organisations: the configuration's organisation's account signs in (rui2, Acme)",
      landed(r).endswith("/portal/#overview") and me.get("user") == "rui2", (landed(r), me.get("user")))
users.remove("rui2")
refused("a disabled account", "accountDisabled", email="off@acme.example")
refused("a domain without single sign-on (at the start)", "noProvider", email="x@nowhere.example")
refused("not an e-mail address (at the start)", "emailInvalid", email="nobody")
last = store.col("sso").find_one({"_id": acme["id"]}).get("lastError") or {}
check("the configuration's last failure noted for its administrators", last.get("code") == "sso.accountDisabled"
      and "off@acme.example" in last.get("detail", ""), last)
failed = store.col("journal").find_one({"action": "login-failed", "detail": {"$regex": "sso.noAccount"}})
check("refusals are in the organisation's journal", failed and failed.get("tenant") == acme["id"], failed)
# ADR 0031 §2.3: the provider's answer reaching the callback when this browser started no sign-in is counted
import failcount  # noqa: E402
failcount._counters().delete_many({})
_before = store.col("journal").count_documents({"action": "login-failed"})
for _ in range(3):
    _r = portal.app.test_client().get("/portal/sso/callback?code=forged&state=forged",
                                      headers={"X-Forwarded-For": "203.0.113.77"})
_counter = failcount._counters().find_one({"kind": "sso"}) or {}
check("a callback without a sign-in in progress: refused, counted, no journal event each",
      _r.status_code == 302 and "/portal/login?sso=" in _r.headers.get("Location", "")
      and store.col("journal").count_documents({"action": "login-failed"}) == _before
      and _counter.get("n") == 3 and _counter.get("addrs") == ["203.0.113.77"], _counter)
check("…its hour's journal event names single sign-on",
      "3 single sign-on answers without a sign-in in progress" in failcount.detail_of(_counter), failcount.detail_of(_counter))
failcount._counters().delete_many({})

# ------------------------------------------------------------------ a verified e-mail, the subject (ADR 0025)
ana.put(f"/portal/api/sso/{acme['id']}", json={"domains": ["acme.example", "acme2.example"]}, headers=ORIGIN)
users.create("zoe", "zoe-password-long", "reader", tenant=acme["id"], email="zoe@acme2.example", must_change=False)
refused("the provider's e-mail at a listed domain not yet proved", "domainMismatch", email="zoe@acme2.example",
        start_email="edu@acme.example")
ana.put(f"/portal/api/sso/{acme['id']}", json={"domains": ["acme.example"]}, headers=ORIGIN)
refused("no email_verified claim", "noEmail", setup=lambda: provider.NEXT.update(email_verified=None))
ana.put(f"/portal/api/sso/{acme['id']}", json={"emailVerifiedOptional": True}, headers=ORIGIN)
refused("email_verified false, even when the provider is said not to send it", "noEmail",
        setup=lambda: provider.NEXT.update(email_verified=False))
provider.reset()
provider.NEXT.update(email="edu@acme.example", email_verified=None)
r, _ = sign_in("edu@acme.example")
check("…a missing claim accepted when the configuration says its provider never sends it",
      landed(r).endswith("/portal/#overview"), landed(r))
ana.put(f"/portal/api/sso/{acme['id']}", json={"emailVerifiedOptional": False}, headers=ORIGIN)
provider.reset()
provider.NEXT.update(email="edu@acme.example", email_verified="true")
r, _ = sign_in("edu@acme.example")
check("…the claim as the string \"true\" accepted", landed(r).endswith("/portal/#overview"), landed(r))
bound = users.get("edu")["sso"] or {}
first = store.col("journal").find_one({"action": "login", "user": "edu", "detail": {"$regex": " bound$"}})
check("the first sign-in bound the account to the provider's issuer and subject, in the journal",
      bound.get("iss") == provider.issuer and bound.get("sub") == "sub-edu@acme.example" and first
      and "subject sub-edu@acme.example bound" in first["detail"], (bound, first))
listed = {u["username"]: u for u in ana.get("/portal/api/users").get_json()["users"]}
check("…shown to the organisation's administrators", listed["edu"]["sso"]["subject"] == "sub-edu@acme.example"
      and listed["edu"]["sso"]["issuer"] == provider.issuer and listed["ana"]["sso"] is None, listed["edu"])
refused("another subject for the same e-mail (a mail attribute set by someone else)", "subjectMismatch",
        setup=lambda: provider.NEXT.update(sub="someone-else"))
failed = store.col("journal").find_one({"action": "login-failed", "detail": {"$regex": "subjectMismatch"}},
                                       sort=[("at", -1)])
check("…in the journal with the subject presented and the account's e-mail", failed and failed.get("user")
      == "edu@acme.example" and "subject someone-else" in failed.get("detail", ""), failed)
refused("a subject bound to another account", "subjectTaken", email="new@acme.example",
        setup=lambda: provider.NEXT.update(sub="sub-edu@acme.example"))
r = ana.put("/portal/api/users/edu", json={"ssoForget": True}, headers=ORIGIN)
forgot = store.col("journal").find_one({"action": "user-update", "detail": {"$regex": "sso-forgotten"}})
check("an administrator forgets the binding, in the journal", r.status_code == 200 and users.get("edu")["sso"] is None
      and forgot and forgot.get("detail", "").startswith("edu "), (r.get_json(), forgot))
provider.reset()
provider.NEXT.update(email="edu@acme.example", sub="recreated-account")
r, _ = sign_in("edu@acme.example")
check("…then the new subject signs in and is bound", landed(r).endswith("/portal/#overview")
      and users.get("edu")["sso"]["sub"] == "recreated-account", landed(r))
users.update("edu", role="editor")
check("other changes of the account keep the binding", (users.get("edu")["sso"] or {}).get("sub") == "recreated-account")
users.update("edu", email="edu2@acme.example")
users.update("edu", email="edu@acme.example")
check("a new e-mail address drops it", users.get("edu")["sso"] is None)
users.bind_sso("edu", provider.issuer, "sub-edu@acme.example")
check("bind_sso: the same subject passes, another issuer rebinds", users.bind_sso("edu", provider.issuer,
      "sub-edu@acme.example") == "same" and users.bind_sso("edu", "https://new.example", "x") == "bound"
      and users.get("edu")["sso"]["iss"] == "https://new.example")
users.update("edu", sso_forget=True)

provider.reset()
provider.NEXT["email"] = "edu@acme.example"
browser = portal.app.test_client()
start = browser.post("/portal/api/sso/start", json={"email": "edu@acme.example"}, headers=ORIGIN).get_json()
with browser.session_transaction("/portal/api/config") as flask_session:
    flask_session["sso"] = {**flask_session["sso"], "at": flask_session["sso"]["at"] - sso.FLOW_SECONDS - 1}
reply = http.get(start["url"], allow_redirects=False, timeout=5)
r = browser.get(urlparse(reply.headers["Location"]).path + "?" + urlparse(reply.headers["Location"]).query)
check("a flow begun more than 10 minutes ago: refused (expired)", landed(r).endswith("/portal/login?sso=expired"),
      landed(r))

provider.reset()
provider.rotate()
provider.NEXT["email"] = "edu@acme.example"
r, _ = sign_in("edu@acme.example")
check("the provider's new key: read once more, signed in", landed(r).endswith("/portal/#overview"), landed(r))

provider.NEXT["email"] = "new@acme.example"
r, browser = sign_in("new@acme.example")
me = browser.get("/portal/api/config").get_json()
check("a temporary password is not asked for after single sign-on", landed(r).endswith("#overview")
      and me["mustChange"] is False and browser.get("/portal/api/records").status_code == 200, me.get("mustChange"))
store.col("tenants").update_one({"_id": acme["id"]}, {"$set": {"disabled": True}})
provider.NEXT["email"] = "edu@acme.example"
r, _ = sign_in("edu@acme.example")
check("a disabled organisation: refused", landed(r).endswith("/portal/login?sso=tenantDisabled"), landed(r))
store.col("tenants").update_one({"_id": acme["id"]}, {"$set": {"disabled": False}})

# ================================================================== password sign-in off
ana.put(f"/portal/api/sso/{acme['id']}", json={"passwordOff": True}, headers=ORIGIN)
fresh = portal.app.test_client()
r = fresh.post("/portal/api/login", json={"username": "edu", "password": "edu-password-long"}, headers=ORIGIN)
check("password sign-in off: the right password refused with auth.ssoRequired", r.status_code == 403
      and code(r) == "auth.ssoRequired", (r.status_code, code(r)))
r = fresh.post("/portal/api/login", json={"username": "edu", "password": "wrong-password"}, headers=ORIGIN)
check("…a wrong password still the usual answer", r.status_code == 401 and code(r) == "auth.invalid")
users.create("ext", "ext-password-long", "reader", tenant=acme["id"], email="ext@elsewhere.example", must_change=False)
r = fresh.post("/portal/api/login", json={"username": "ext", "password": "ext-password-long"}, headers=ORIGIN)
check("…not for an account whose e-mail domain the configuration has not proved", r.status_code == 200, code(r))
sent = []
saved = portal.mail.enabled, portal.notify.reachable, portal.send_link, portal.RECOVERY_SECONDS
portal.mail.enabled, portal.notify.reachable = (lambda: True), (lambda account: True)
portal.send_link = lambda username, *args, **kwargs: sent.append(username) or True
portal.RECOVERY_SECONDS = 0
for login in ("edu@acme.example", "bia@beta.example"):
    fresh.post("/portal/api/password/forgot", json={"login": login}, headers=ORIGIN)
portal.mail.enabled, portal.notify.reachable, portal.send_link, portal.RECOVERY_SECONDS = saved
check("…password recovery sends nothing for them (another organisation's people still get it)", sent == ["bia"], sent)
r = fresh.post("/portal/api/login", json={"username": "root", "password": "root-password-long"}, headers=ORIGIN)
check("…never for a server administrator", r.status_code == 200)
r = root.put(f"/portal/api/sso/{acme['id']}", json={"passwordOff": False}, headers=ORIGIN)
r2 = portal.app.test_client().post("/portal/api/login", json={"username": "edu", "password": "edu-password-long"},
                                   headers=ORIGIN)
check("a server administrator switches it off for the organisation: passwords work again", code(r) == "sso.saved"
      and r2.status_code == 200, (code(r), r2.status_code))
r = root.put("/portal/api/sso/operator", json={"issuer": provider.issuer, "clientId": "op", "clientSecret": "x",
                                               "domains": ["operator.example"], "enabled": True, "passwordOff": True},
             headers=ORIGIN)
check("the operator's own configuration (server administrators)", code(r) == "sso.saved"
      and not sso.password_off_for(users.get("root")))
r = ana.delete("/portal/api/sso/operator", headers=ORIGIN)
check("…which an organisation's administrator may not remove", r.status_code == 403)
r = root.delete("/portal/api/sso/operator", headers=ORIGIN)
check("removed", code(r) == "sso.removed" and sso.get("operator") is None)
actions = {e["action"] for e in store.col("journal").find({"action": {"$regex": "^sso-"}})}
check("the journal: configurations saved and removed, domains proved", actions == {"sso-save", "sso-remove", "sso-domain"},
      actions)

# ================================================================== the client secret sealed (ADR 0044)
import sealed  # noqa: E402

stored = store.col("sso").find_one({"_id": acme["id"]})["clientSecret"]
everything = repr(list(store.col("sso").find()))
check("the client secret is stored sealed (AES-GCM, a key id), never in clear in the collection",
      isinstance(stored, dict) and stored.get("sealed") == 1 and len(stored.get("kid", "")) == 16
      and provider.client_secret not in everything and len(stored.get("nonce", "")) == 16, stored)
check("…and opens with the data key to the secret given", sso.client_secret(sso.get(acme["id"])) == provider.client_secret)
check("…only in its own configuration (the place is its associated data)",
      sso.client_secret({"_id": beta["id"], "clientSecret": stored}) is None)
changed = dict(stored, data=stored["data"][:-4] + ("AAAA" if not stored["data"].endswith("AAAA") else "BBBB"))
check("…and not once changed", sso.client_secret({"_id": acme["id"], "clientSecret": changed}) is None)
check("the data key without PORTAL_DATA_KEY: a key file of the configuration volume, mode 600",
      os.path.exists(os.path.join(os.environ["PORTAL_CONFIG_DIR"], "data.key"))
      and oct(os.stat(os.path.join(os.environ["PORTAL_CONFIG_DIR"], "data.key")).st_mode & 0o777) == "0o600"
      and sealed.key_id(sealed.keys()[0]) == stored["kid"])


def sso_round(email="edu@acme.example"):
    provider.reset()
    provider.NEXT["email"] = email
    before = len(provider.requests)
    r, _ = sign_in(email)
    tokens = [q for q in provider.requests[before:] if q["endpoint"] == "token"]
    return landed(r), tokens


# a secret stored in clear by an earlier version: sealed at the start, once
store.col("sso").update_one({"_id": acme["id"]}, {"$set": {"clientSecret": provider.client_secret}})
check("a secret stored in clear before still signs people in", sso_round()[0].endswith("/portal/#overview"))
first, second = sso.seal_stored(), sso.seal_stored()
stored = store.col("sso").find_one({"_id": acme["id"]})["clientSecret"]
check("at the start, a secret stored in clear is sealed in place, once", first == 1 and second == 0
      and sealed.is_sealed(stored) and sso.client_secret(sso.get(acme["id"])) == provider.client_secret, (first, second))
app_source = open(os.path.join(PORTAL, "app.py"), encoding="utf-8").read()
check("…which the portal does when it starts", re.search(r"^if sso\.seal_stored\(\):", app_source, re.M) is not None)
where, tokens = sso_round()
check("…and the sign-in sends the secret opened, as before", where.endswith("/portal/#overview")
      and tokens and tokens[-1]["client_secret"] == provider.client_secret, where)

# PORTAL_DATA_KEY set later: the key file's values still open and are sealed again with it
os.environ["PORTAL_DATA_KEY"] = "a" * 64
kid_before = stored["kid"]
check("PORTAL_DATA_KEY set: a value of the key file still opens", sso.client_secret(sso.get(acme["id"])) == provider.client_secret)
resealed = sso.seal_stored()
stored = store.col("sso").find_one({"_id": acme["id"]})["clientSecret"]
check("…and is sealed again with PORTAL_DATA_KEY at the start", resealed == 1 and stored["kid"] != kid_before
      and stored["kid"] == sealed.key_id(sealed.keys()[0]) and sso.seal_stored() == 0, (resealed, stored["kid"]))

# rotation (scripts/rotate-secrets.sh data): the former key as PORTAL_DATA_KEY_PREVIOUS
os.environ["PORTAL_DATA_KEY_PREVIOUS"], os.environ["PORTAL_DATA_KEY"] = "a" * 64, "b" * 64
check("rotated: the former key, as PORTAL_DATA_KEY_PREVIOUS, still opens", sso.client_secret(sso.get(acme["id"]))
      == provider.client_secret and sso.seal_stored() == 1
      and store.col("sso").find_one({"_id": acme["id"]})["clientSecret"]["kid"] == sealed.key_id(sealed.keys()[0]))

# the key lost: never sent, the screen asks for it again
os.environ["PORTAL_DATA_KEY"] = "c" * 64
os.environ.pop("PORTAL_DATA_KEY_PREVIOUS")
item = next(c for c in ana.get("/portal/api/sso").get_json()["configs"] if c["scope"] == acme["id"])
check("a secret no known key opens: the screen says unreadable (still set)", item["secretUnreadable"] is True
      and item["secretSet"] is True and sso.seal_stored() == 0, item)
where, tokens = sso_round()
doc = sso.get(acme["id"])
check("…the sign-in stops before the token request, and the configuration's last error says why",
      where.endswith("/portal/login?sso=secretUnreadable") and not tokens
      and (doc.get("lastError") or {}).get("code") == "sso.secretUnreadable", (where, len(tokens), doc.get("lastError")))
r = ana.put(f"/portal/api/sso/{acme['id']}", json={"clientSecret": provider.client_secret}, headers=ORIGIN)
check("…until an administrator enters it again", code(r) == "sso.saved" and r.get_json()["item"]["secretUnreadable"] is False
      and sso_round()[0].endswith("/portal/#overview"), r.get_json())
os.environ.pop("PORTAL_DATA_KEY")
ana.put(f"/portal/api/sso/{acme['id']}", json={"clientSecret": provider.client_secret}, headers=ORIGIN)

# ================================================================== configurations from before ADR 0025
store.col("sso").insert_one({"_id": beta["id"], "issuer": provider.issuer, "clientId": "c", "clientSecret": "s",
                             "domains": ["beta.example"], "enabled": True})
changed = sso.upgrade()
doc = sso.get(beta["id"])
check("at the start, an earlier configuration's domains are recorded as proved at the upgrade, with a token",
      changed == 1 and [(p["domain"], p["how"]) for p in doc["proofs"]] == [("beta.example", "upgrade")]
      and len(doc.get("token", "")) == 32 and sso.for_email("bia@beta.example")["_id"] == beta["id"], doc)
check("…once only", sso.upgrade() == 0 and sso.get(beta["id"])["token"] == doc["token"])
sso.remove(beta["id"])

# ================================================================== texts
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(sso\.[A-Za-z]+)"', open(os.path.join(PORTAL, "sso.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read()))
codes |= {f"sso.{c}" for c in ("expired", "providerRefused", "tokenFailed", "tokenInvalid", "noEmail", "domainMismatch",
                               "noAccount", "accountDisabled", "tenantDisabled", "noProvider", "discoveryFailed")}
codes |= {"auth.ssoRequired", "sso.secretUnreadableBadge"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"every single sign-on text in both languages ({len(codes)})", len(codes) > 25 and not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
