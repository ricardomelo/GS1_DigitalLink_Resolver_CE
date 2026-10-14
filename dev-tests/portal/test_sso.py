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
single sign-on; the texts in both languages.

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
      and store.col("sso").find_one({"_id": acme["id"]})["clientSecret"] == provider.client_secret)
check("…and nothing lists it", provider.client_secret not in ana.get("/portal/api/sso").get_data(as_text=True))
ana.put(f"/portal/api/sso/{acme['id']}", json={"clientSecret": "", "clientId": provider.client_id}, headers=ORIGIN)
check("an empty secret field (as the screen sends it) keeps the secret",
      store.col("sso").find_one({"_id": acme["id"]})["clientSecret"] == provider.client_secret)
r = bia.put(f"/portal/api/sso/{acme['id']}", json=CONFIG, headers=ORIGIN)
check("another organisation's administrator may not touch it", r.status_code == 403 and code(r) == "sso.scopeOutside")
r = bia.put(f"/portal/api/sso/{beta['id']}", json={**CONFIG, "domains": ["beta.example", "acme.example"]}, headers=ORIGIN)
check("a domain belongs to one configuration", code(r) == "sso.domainTaken" and r.get_json()["params"]["domain"]
      == "acme.example", r.get_json())
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
refused("a disabled account", "accountDisabled", email="off@acme.example")
refused("a domain without single sign-on (at the start)", "noProvider", email="x@nowhere.example")
refused("not an e-mail address (at the start)", "emailInvalid", email="nobody")
last = store.col("sso").find_one({"_id": acme["id"]}).get("lastError") or {}
check("the configuration's last failure noted for its administrators", last.get("code") == "sso.accountDisabled"
      and "off@acme.example" in last.get("detail", ""), last)
failed = store.col("journal").find_one({"action": "login-failed", "detail": {"$regex": "sso.noAccount"}})
check("refusals are in the organisation's journal", failed and failed.get("tenant") == acme["id"], failed)

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
check("the journal: configurations saved and removed", actions == {"sso-save", "sso-remove"}, actions)

# ================================================================== texts
i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = set(re.findall(r'"(sso\.[A-Za-z]+)"', open(os.path.join(PORTAL, "sso.py")).read()
                       + open(os.path.join(PORTAL, "app.py")).read()))
codes |= {f"sso.{c}" for c in ("expired", "providerRefused", "tokenFailed", "tokenInvalid", "noEmail", "domainMismatch",
                               "noAccount", "accountDisabled", "tenantDisabled", "noProvider", "discoveryFailed")}
codes |= {"auth.ssoRequired"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check(f"every single sign-on text in both languages ({len(codes)})", len(codes) > 25 and not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
