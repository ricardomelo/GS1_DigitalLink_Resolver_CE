"""
E-mail of the portal (Documentation/adr/0004-e-mail.md) against a small SMTP relay of the test's own (fake_smtp.py):
sending through STARTTLS and TLS relays with authentication, the sorting of the relay's errors, the operator's test
command, the texts in both languages, single-use links, the "mail" job with its retries, and every flow through the
portal's API — invitations, password recovery, resets by an administrator, security notices, the user's preferences
and the notices of finished background jobs — with the privacy rules (same answer for every recovery request, no
address in the journal, the message text removed from its job once sent).

Runs against mongomock unless PORTAL_DB_URI names a real MongoDB (the CI job "database" does that).

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_mail.py
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3398
sys.path[:0] = [HERE, PORTAL]

from fake_smtp import FakeRelay  # noqa: E402

relay = FakeRelay(starttls=True, credentials=("portal@example.org", "relay-secret")).start()
MAIL_ENV = {"PORTAL_MAIL_HOST": "127.0.0.1", "PORTAL_MAIL_PORT": str(relay.port), "PORTAL_MAIL_SECURITY": "starttls",
            "PORTAL_MAIL_USERNAME": "portal@example.org", "PORTAL_MAIL_PASSWORD": "relay-secret",
            "PORTAL_MAIL_FROM": "Link portal <noreply@example.org>", "PORTAL_MAIL_CA_FILE": relay.ca_file,
            "PORTAL_MAIL_TIMEOUT": "5"}
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", RESOLVER_ORG_NAME="Example Operator", **MAIL_ENV)
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_mail_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "embedded"               # messages are sent by a thread of the portal

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False, email="root@example.org")
import app as portal  # noqa: E402
import jobs  # noqa: E402
import journal  # noqa: E402
import linkcheck  # noqa: E402
import mail  # noqa: E402
import mailtexts  # noqa: E402
import notify  # noqa: E402
import tenants  # noqa: E402
import tokens  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}
_address = [0]


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def addr():
    """A new browser address for each recovery request (the per-address limit is checked on its own)."""
    _address[0] += 1
    return {**ORIGIN, "X-Forwarded-For": f"10.1.{_address[0] // 250}.{_address[0] % 250 + 1}"}


def client(username=None, password=None, language=None):
    c = portal.app.test_client()
    r = None
    if username:
        r = c.post("/portal/api/login", json={"username": username, "password": password,
                                              **({"language": language} if language else {})}, headers=addr())
    return c, r


def code(r):
    return (r.get_json() or {}).get("code")


def wait_messages(count, timeout=8.0):
    """The relay's messages once there are at least `count` (or what arrived before the timeout)."""
    end = time.monotonic() + timeout
    while len(relay.messages) < count and time.monotonic() < end:
        time.sleep(0.05)
    time.sleep(0.15)                                  # a message more than expected would arrive now
    return list(relay.messages)


def text_of(msg):
    return msg.get_body(("plain",)).get_content()


def link_in(msg):
    found = re.search(r"https://id\.example\.org/portal/login#(invite|reset)=([A-Za-z0-9_-]+)", text_of(msg))
    return (found.group(1), found.group(2)) if found else (None, None)


def queued_mail():
    return list(store.col("jobs").find({"type": "mail"}))


def settle():
    """Waits until no mail job is queued or running (the embedded worker sends one at a time)."""
    end = time.monotonic() + 8
    while store.col("jobs").count_documents({"type": "mail", "state": {"$in": ["queued", "running"]},
                                             "notBefore": None}) and time.monotonic() < end:
        time.sleep(0.05)


def gtin(body13: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


# ================================================================== 1. sending (mail.py)
saved = {k: os.environ.get(k) for k in MAIL_ENV}


def mail_env(**changes):
    for key, value in {**MAIL_ENV, **changes}.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


mail_env(PORTAL_MAIL_HOST="")
check("mail off without PORTAL_MAIL_HOST", mail.enabled() is False)
mail_env(PORTAL_MAIL_FROM="")
check("a relay without a sender is refused", not mail.enabled()
      and any("PORTAL_MAIL_FROM" in p for p in mail.problems()))
mail_env(PORTAL_MAIL_PASSWORD="")
check("a user name without a password is refused", not mail.enabled()
      and any("without PORTAL_MAIL_PASSWORD" in p for p in mail.problems()))
mail_env(PORTAL_MAIL_SECURITY="none")
check("credentials without encryption are refused", not mail.enabled()
      and any("in clear" in p for p in mail.problems()))
mail_env(PORTAL_MAIL_SECURITY="ssl")
check("an unknown security mode is refused", not mail.enabled())
mail_env(PORTAL_MAIL_PORT="", PORTAL_MAIL_SECURITY="tls")
check("default ports: 465 for tls", mail.settings()["port"] == 465)
mail_env(PORTAL_MAIL_PORT="", PORTAL_MAIL_SECURITY="", PORTAL_MAIL_USERNAME="", PORTAL_MAIL_PASSWORD="")
check("default security starttls on 587", mail.settings()["security"] == "starttls" and mail.settings()["port"] == 587)
mail_env()
check("the test settings are usable", mail.enabled() and mail.problems() == [], mail.problems())

relay.clear()
answer = mail.send(mail.message("ana@example.org", "Assunto — teste", "Olá,\n\nlinha\n\nhttps://x.example/a?b=1&c=2",
                                mailtexts.compose("test", "pt-BR", when="hoje", operator="Op", portal="https://p/")[2]))
msg = relay.messages[0] if relay.messages else None
check("STARTTLS, then authentication, then the message", answer == "accepted"
      and relay.commands[:4] == ["EHLO", "STARTTLS", "EHLO", "AUTH"] and relay.envelopes[0][2] is True, relay.commands)
check("envelope: the sender's address and the recipient", relay.envelopes[0][0].lower().startswith("from:<noreply@example.org>")
      and [r.lower() for r in relay.envelopes[0][1]] == ["to:<ana@example.org>"], relay.envelopes)
check("headers: From, To, Subject (UTF-8), Date, Message-ID of the sender's domain, Auto-Submitted",
      msg["From"] == "Link portal <noreply@example.org>" and msg["To"] == "ana@example.org"
      and msg["Subject"] == "Assunto — teste" and msg["Date"] and msg["Message-ID"].endswith("@example.org>")
      and msg["Auto-Submitted"] == "auto-generated", dict(msg.items()) if msg else None)
check("a plain text with an HTML alternative", msg.get_body(("plain",)) is not None
      and msg.get_body(("html",)) is not None)
mail_env(PORTAL_MAIL_REPLY_TO="help@example.org")
relay.clear()
mail.send(mail.message("ana@example.org", "s", "t"))
check("Reply-To when configured", relay.messages[0]["Reply-To"] == "help@example.org")
mail_env()

relay.reply["RCPT"] = (450, "4.2.0 Mailbox busy")
try:
    mail.send(mail.message("ana@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("a 4xx answer is a temporary failure", outcome is not None and outcome.temporary and "450" in str(outcome), outcome)
relay.reply["RCPT"] = (550, "5.1.1 No such user")
try:
    mail.send(mail.message("nobody@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("a 5xx answer is a permanent failure", outcome is not None and not outcome.temporary and "550" in str(outcome))
relay.clear()
mail_env(PORTAL_MAIL_PASSWORD="wrong-secret")
try:
    mail.send(mail.message("ana@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("wrong relay credentials: permanent, nothing sent", outcome is not None and not outcome.temporary
      and "535" in str(outcome) and not relay.messages)
mail_env(PORTAL_MAIL_CA_FILE="")
try:
    mail.send(mail.message("ana@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("a certificate nobody vouches for is refused (permanent)", outcome is not None and not outcome.temporary
      and "certificate" in str(outcome), outcome)
plain = FakeRelay().start()
mail_env(PORTAL_MAIL_PORT=str(plain.port))
try:
    mail.send(mail.message("ana@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("a relay without STARTTLS is refused when starttls is set (credentials never in clear)",
      outcome is not None and not outcome.temporary and "STARTTLS" in str(outcome) and "AUTH" not in plain.commands)
mail_env(PORTAL_MAIL_PORT=str(plain.port), PORTAL_MAIL_SECURITY="none", PORTAL_MAIL_USERNAME="", PORTAL_MAIL_PASSWORD="")
check("security none: a plain relay without credentials (test relays)", mail.send(mail.message("a@example.org", "s", "t"))
      == "accepted" and plain.envelopes[0][2] is False and "AUTH" not in plain.commands)
tls_relay = FakeRelay(implicit_tls=True, credentials=("u", "p")).start()
mail_env(PORTAL_MAIL_PORT=str(tls_relay.port), PORTAL_MAIL_SECURITY="tls", PORTAL_MAIL_USERNAME="u",
         PORTAL_MAIL_PASSWORD="p", PORTAL_MAIL_CA_FILE=tls_relay.ca_file)
check("security tls: TLS from the first byte (port 465 relays)", mail.send(mail.message("a@example.org", "s", "t"))
      == "accepted" and tls_relay.envelopes[0][2] is True and "STARTTLS" not in tls_relay.commands)
closed = FakeRelay()
closed_port = closed.port
closed.stop()
mail_env(PORTAL_MAIL_PORT=str(closed_port))
try:
    mail.send(mail.message("a@example.org", "s", "t"))
    outcome = None
except mail.MailError as exc:
    outcome = exc
check("no connection: a temporary failure", outcome is not None and outcome.temporary, outcome)
mail_env()

relay.clear()
cli = subprocess.run([sys.executable, os.path.join(PORTAL, "mail.py"), "test", "ops@example.org"],
                     capture_output=True, text=True, env={**os.environ, "LANG": "pt_BR.UTF-8"}, timeout=30)
check("python mail.py test <address>: sent at once, the outcome printed",
      cli.returncode == 0 and "Sent" in cli.stdout and relay.messages
      and relay.messages[-1]["Subject"] == mailtexts.TEXTS["test"]["pt-BR"][0], cli.stdout + cli.stderr)
cli = subprocess.run([sys.executable, os.path.join(PORTAL, "mail.py"), "test", "ops@example.org"],
                     capture_output=True, text=True, env={**os.environ, "PORTAL_MAIL_HOST": ""}, timeout=30)
check("the test command says when e-mail is off", cli.returncode == 1 and "off" in cli.stderr, cli.stderr)
cli = subprocess.run([sys.executable, os.path.join(PORTAL, "mail.py"), "test", "ops@example.org"],
                     capture_output=True, text=True, env={**os.environ, "PORTAL_MAIL_PASSWORD": "bad-one"}, timeout=30)
check("the test command shows the relay's refusal", cli.returncode == 1 and "535" in cli.stderr
      and "bad-one" not in cli.stdout + cli.stderr, cli.stderr)

# ================================================================== 2. texts (mailtexts.py)
names = set(mailtexts.TEXTS)
check("every message has both languages", all(set(v) == set(mailtexts.LANGUAGES) for v in mailtexts.TEXTS.values()))
check("both languages use the same placeholders", all(
    mailtexts.placeholders(v["en-GB"][0] + v["en-GB"][1]) == mailtexts.placeholders(v["pt-BR"][0] + v["pt-BR"][1])
    for v in mailtexts.TEXTS.values()))
check("the signatures use the same placeholders", mailtexts.placeholders(mailtexts.SIGNATURE["en-GB"])
      == mailtexts.placeholders(mailtexts.SIGNATURE["pt-BR"]) == {"operator", "portal"})
check("every notification has its texts and every text (but the test) a category", set(notify.TEMPLATES) == names - {"test"},
      set(notify.TEMPLATES) ^ (names - {"test"}))
check("every category is known", set(notify.TEMPLATES.values()) <= set(notify.CATEGORIES))
check("languages: exact, by base language, else English", (mailtexts.language("pt-BR"), mailtexts.language("pt"),
      mailtexts.language("pt-PT"), mailtexts.language("en-US"), mailtexts.language("de"), mailtexts.language(None))
      == ("pt-BR", "pt-BR", "pt-BR", "en-GB", "en-GB", "en-GB"))
subject, text, html = mailtexts.compose("invite", "pt-BR", user="maria<x>", operator="Op & Co", hours="72",
                                        link="https://id.example.org/portal/login#invite=abc", portal="https://p/portal/")
check("compose: placeholders and signature filled", "maria<x>" in text and "72 horas" in text and "Op & Co" in text
      and text.rstrip().endswith("Por favor, não responda.") and "{" not in text)
check("HTML: escaped, links clickable", "maria&lt;x&gt;" in html and "Op &amp; Co" in html
      and '<a href="https://id.example.org/portal/login#invite=abc">' in html and "<x>" not in html)
check("an unknown placeholder stays visible instead of failing",
      "{when}" in mailtexts.compose("password-changed", "en-GB", user="u", operator="o", portal="p")[1])
check("no GS1 branding in the messages", not any("GS1 Brasil" in t or "GS1 Global" in t for v in mailtexts.TEXTS.values()
                                                 for lang in v.values() for t in lang))

# ================================================================== 3. single-use links (tokens.py)
token = tokens.issue("someone", "reset")
stored = store.col("tokens").find_one({"user": "someone"})
check("a link's token: 43 URL-safe characters (256 bits)", re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is not None, token)
check("only the token's hash is stored", stored["_id"] != token and token not in str(stored) and len(stored["_id"]) == 64)
check("validity: 60 minutes for recovery", abs((stored["expiresAt"] - stored["created"]) - timedelta(minutes=60))
      < timedelta(seconds=2))
check("peek: valid, for whom, for what — without using it", tokens.peek(token)["user"] == "someone"
      and tokens.peek(token)["purpose"] == "reset" and tokens.peek(token) is not None)
second = tokens.issue("someone", "reset")
check("a new link replaces the earlier one", tokens.peek(token) is None and tokens.peek(second) is not None)
invite = tokens.issue("someone", "invite")
check("links of another purpose stay", tokens.peek(second) is not None and tokens.peek(invite)["purpose"] == "invite")
check("consume works once", tokens.consume(second)["user"] == "someone" and tokens.consume(second) is None
      and tokens.peek(second) is None)
store.col("tokens").update_one({"user": "someone", "purpose": "invite"}, {"$set": {"expiresAt": store.now() - timedelta(seconds=1)}})
check("an expired link is refused before MongoDB removes it", tokens.peek(invite) is None and tokens.consume(invite) is None)
check("rubbish tokens are refused", tokens.peek("") is None and tokens.peek(None) is None and tokens.peek({"$gt": ""}) is None
      and tokens.consume("x" * 500) is None)
os.environ.update(PORTAL_INVITE_HOURS="24", PORTAL_RESET_MINUTES="15")
check("validity from the environment", tokens.validity_hours("invite") == 24 and tokens.validity_hours("reset") == 0.25)
os.environ.update(PORTAL_INVITE_HOURS="many", PORTAL_RESET_MINUTES="0")
check("validity: a wrong value falls back, a zero becomes one minute", tokens.validity_hours("invite") == 72
      and abs(tokens.validity_hours("reset") - 1 / 60) < 1e-9)
del os.environ["PORTAL_INVITE_HOURS"], os.environ["PORTAL_RESET_MINUTES"]
tokens.issue("someone", "invite")
check("purge removes every link of a user", tokens.purge("someone") >= 1 and not store.col("tokens").find_one({"user": "someone"}))

# ================================================================== 4. jobs with notBefore
portal.EMBEDDED_WORKER.stop()                          # the worker of this process waits while the queue is checked
time.sleep(1.2)
later = jobs.create("mail", "someone", "queued", 1, to="x@example.org", subject="s", text="t", template="test", tries=0)
store.col("jobs").update_one({"_id": later}, {"$set": {"notBefore": store.now() + timedelta(minutes=5)}})
check("a job is not taken before its notBefore", jobs.claim("w1") is None)
store.col("jobs").update_one({"_id": later}, {"$set": {"notBefore": store.now() - timedelta(seconds=1)}})
claimed = jobs.claim("w1")
check("…and is taken after it", claimed is not None and claimed["_id"] == later)
reporter = jobs.Reporter(later, "w1")
try:
    reporter.defer(60, tries=1, lastError="450 busy")
    deferred = False
except jobs.Deferred:
    deferred = True
doc = store.col("jobs").find_one({"_id": later})
check("defer: back in the queue for later, Deferred raised", deferred and doc["state"] == "queued"
      and doc["notBefore"] > store.now() + timedelta(seconds=50) and "worker" not in doc and doc["lastError"] == "450 busy")
store.col("jobs").delete_one({"_id": later})
portal.EMBEDDED_WORKER = portal.worker.start_embedded(portal.JOB_RUNNERS)

# ================================================================== 5. the portal: configuration
relay.clear()
root, r = client("root", "root-password-long", language="pt-BR")
check("server administrator signs in", r.status_code == 200, r.get_json())
cfg = root.get("/portal/api/config").get_json()
check("configuration: mail on, the user's preferences", cfg["mail"] == {"enabled": True}
      and cfg["preferences"] == {"email": "root@example.org", "language": "pt-BR", "languageChosen": False,
                                 "notify": {"jobs": False}}, cfg.get("preferences"))
check("sign-in page: recovery offered", portal.app.test_client().get("/portal/api/login/options").get_json()
      == {"passwordRecovery": True})
check("health check: mail on", portal.app.test_client().get("/portal/healthz").get_json()["mail"] == "on")
mail_env(PORTAL_MAIL_HOST="")
check("mail off: no recovery, health check says off", portal.app.test_client().get("/portal/api/login/options").get_json()
      == {"passwordRecovery": False} and portal.app.test_client().get("/portal/healthz").get_json()["mail"] == "off")
r = portal.app.test_client().post("/portal/api/password/forgot", json={"login": "root"}, headers=addr())
check("mail off: recovery refused", r.status_code == 404 and code(r) == "password.recoveryOff")
r = root.post("/portal/api/users", json={"username": "nomail", "role": "editor", "email": "nomail@example.org",
                                         "invite": True}, headers=ORIGIN)
check("mail off: a new user gets a temporary password even when an invitation was asked",
      r.status_code == 201 and code(r) == "users.created" and len(r.get_json()["password"]) == 16)
r = root.post("/portal/api/users/nomail/reset", json={}, headers=ORIGIN)
check("mail off: reset gives a temporary password", code(r) == "users.reset" and "password" in r.get_json())
mail_env()
time.sleep(0.3)
check("mail off: nothing queued, nothing sent", not queued_mail() and not relay.messages)

# ================================================================== 6. invitations
r = root.post("/portal/api/users", json={"username": "maria", "role": "editor", "email": "Maria@Example.org",
                                         "invite": True, "language": "pt-BR"}, headers=ORIGIN)
check("invitation: created without a password shown", r.status_code == 201 and code(r) == "users.invited"
      and "password" not in r.get_json(), r.get_json())
maria = users.get("maria")
check("invitation: the account has no password and is marked invited", maria["hash"] == "" and maria["invited"]
      and maria["mustChange"] is False and maria["language"] == "pt-BR")
messages = wait_messages(1)
invite_msg = messages[0] if messages else None
check("invitation: one message, to the user's address", len(messages) == 1 and invite_msg["To"] == "maria@example.org",
      [m["To"] for m in messages])
check("invitation: in the inviter's language, with the user name, the validity and the operator",
      invite_msg["Subject"] == mailtexts.TEXTS["invite"]["pt-BR"][0] and "Nome de usuário: maria" in text_of(invite_msg)
      and "72 horas" in text_of(invite_msg) and "Example Operator" in text_of(invite_msg), text_of(invite_msg)[:400])
purpose, invite_token = link_in(invite_msg)
check("invitation: the link carries the token in its fragment", purpose == "invite" and invite_token)
check("invitation: the token is not in the database", invite_token not in str(list(store.col("tokens").find()))
      and invite_token not in str(list(store.col("jobs").find())))
check("invitation: no password signs in", client("maria", "")[1].status_code == 401
      and client("maria", "anything-long-enough")[1].status_code == 401)
check("users list: invited state", next(u for u in root.get("/portal/api/users").get_json()["users"]
                                        if u["username"] == "maria")["invited"])
anon = portal.app.test_client()
r = anon.post("/portal/api/password/link/check", json={"token": invite_token}, headers=addr())
check("link check: user name and purpose, nothing used up", r.status_code == 200 and r.get_json()
      == {"user": "maria", "purpose": "invite", "min": 12} and tokens.peek(invite_token))
r = anon.post("/portal/api/password/link", json={"token": invite_token, "newPassword": "short"}, headers=addr())
check("a short password is refused and the link still works", r.status_code == 422
      and code(r) == "password.tooShort" and tokens.peek(invite_token))
r = anon.post("/portal/api/password/link", json={"token": invite_token, "newPassword": "maria-password-long",
                                                  "language": "en-GB"}, headers=addr())
check("invitation accepted: password set", r.status_code == 200 and code(r) == "password.set"
      and r.get_json()["purpose"] == "invite")
maria = users.get("maria")
check("…invited and must-change cleared, language kept until the user chooses",
      not maria["invited"] and maria["hash"] and maria["language"] == "en-GB")
r = anon.post("/portal/api/password/link", json={"token": invite_token, "newPassword": "another-password-long"},
              headers=addr())
check("the link works once", r.status_code == 410 and code(r) == "password.linkInvalid")
check("the invited user signs in", client("maria", "maria-password-long")[1].status_code == 200)
check("no security notice for a first password", len(wait_messages(2, 1.0)) == 1)
check("journal: invite-accepted", any(e["action"] == "invite-accepted" for e in journal.search(user="maria")))
r = root.post("/portal/api/users", json={"username": "joao", "role": "reader", "invite": True}, headers=ORIGIN)
check("an invitation without an address gives a temporary password", code(r) == "users.created" and r.get_json().get("password"))

# ================================================================== 7. password recovery
relay.clear()
started = time.monotonic()
r = anon.post("/portal/api/password/forgot", json={"login": "nobody-at-all"}, headers=addr())
unknown_time = time.monotonic() - started
check("recovery for an unknown name: the usual answer", r.status_code == 200 and code(r) == "password.recoverySent")
started = time.monotonic()
r = anon.post("/portal/api/password/forgot", json={"login": "MARIA@example.org", "language": "pt-BR"}, headers=addr())
known_time = time.monotonic() - started
check("recovery by address (case ignored): the same answer", r.status_code == 200 and code(r) == "password.recoverySent")
check("the answer takes as long either way (at least 0.5 s)", unknown_time >= 0.5 and known_time >= 0.5
      and abs(unknown_time - known_time) < 0.3, (unknown_time, known_time))
messages = wait_messages(1)
check("recovery: one message, in the user's own language (not the page's)", len(messages) == 1
      and messages[0]["Subject"] == mailtexts.TEXTS["password-recovery"]["en-GB"][0] and "60 minutes" in text_of(messages[0]))
purpose, reset_token = link_in(messages[0])
check("recovery: a reset link", purpose == "reset" and reset_token)
check("recovery does not change the password until the link is used",
      client("maria", "maria-password-long")[1].status_code == 200)
check("journal: password-recovery, with the user's name, not the address",
      any(e["action"] == "password-recovery" for e in journal.search(user="maria")))
r = anon.post("/portal/api/password/forgot", json={"login": "maria"}, headers=addr())
messages = wait_messages(2)
_, newer_token = link_in(messages[-1])
check("recovery by user name; a new request replaces the earlier link", len(messages) == 2 and tokens.peek(reset_token) is None
      and tokens.peek(newer_token))
r = anon.post("/portal/api/password/forgot", json={"login": "Maria"}, headers=addr())
check("recovery: user name case is forgiven", len(wait_messages(3)) == 3)
anon.post("/portal/api/password/forgot", json={"login": "maria"}, headers=addr())
r = anon.post("/portal/api/password/forgot", json={"login": "maria"}, headers=addr())
check("recovery: three requests per name in 15 minutes", r.status_code == 429 and code(r) == "password.recoveryLimit"
      and len(wait_messages(5, 0.8)) == 4)
_, reset_token = link_in(relay.messages[-1])
r = anon.post("/portal/api/password/forgot", json={"login": "unknown@example.org"}, headers=ORIGIN)
for _ in range(9):
    anon.post("/portal/api/password/forgot", json={"login": f"x{_}@example.org"}, headers=ORIGIN)
r = anon.post("/portal/api/password/forgot", json={"login": "another@example.org"}, headers=ORIGIN)
check("recovery: ten requests per browser address", r.status_code == 429)
check("recovery: an empty entry is a mistake to correct", code(anon.post("/portal/api/password/forgot", json={"login": " "},
                                                                         headers=addr())) == "password.recoveryMissing")

stray_invite = tokens.issue("maria", "invite")             # another link of the account, e.g. an old invitation
other_session, _ = client("maria", "maria-password-long")
check("an open session of the user before the reset", other_session.get("/portal/api/config").status_code == 200)
r = anon.post("/portal/api/password/link", json={"token": reset_token, "newPassword": "maria-new-password"}, headers=addr())
check("recovery link: password set", code(r) == "password.set" and r.get_json()["purpose"] == "reset")
check("…the old password no longer works, the new one does", client("maria", "maria-password-long")[1].status_code == 401
      and client("maria", "maria-new-password")[1].status_code == 200)
check("…every open session ended", other_session.get("/portal/api/config").status_code == 401)
check("…and every other link of the account stopped working", tokens.peek(stray_invite) is None)
messages = wait_messages(5)
check("…a security message: the password was changed", messages[-1]["Subject"] == mailtexts.TEXTS["password-changed"]["en-GB"][0]
      and messages[-1]["To"] == "maria@example.org")
check("journal: password-reset", any(e["action"] == "password-reset" for e in journal.search(user="maria")))

# who gets nothing
users.create("noaddr", "noaddr-password-long", "reader", must_change=False)
users.create("gone", "gone-password-long", "reader", must_change=False, email="gone@example.org")
users.update("gone", disabled=True)
relay.clear()
for login in ("noaddr", "gone", "gone@example.org"):
    r = anon.post("/portal/api/password/forgot", json={"login": login}, headers=addr())
    check(f"recovery for {login}: the usual answer", code(r) == "password.recoverySent")
check("nothing sent to an account without an address or disabled", not wait_messages(1, 1.0))
acme = tenants.create("Acme", ["7891234"], "root")
users.create("ana", "ana-password-long", "editor", tenant=acme["id"], must_change=False, email="ana@acme.example")
tenants.update(acme["id"], disabled=True)
r = anon.post("/portal/api/password/forgot", json={"login": "ana"}, headers=addr())
check("nothing sent to a user of a disabled organisation", code(r) == "password.recoverySent" and not wait_messages(1, 1.0))
tenants.update(acme["id"], disabled=False)

# invalid links
r = anon.post("/portal/api/password/link/check", json={"token": "A" * 43}, headers=addr())
check("an unknown link: invalid (410)", r.status_code == 410 and code(r) == "password.linkInvalid")
token = tokens.issue("gone", "reset")
check("a link of a disabled account is refused", code(anon.post("/portal/api/password/link/check", json={"token": token},
                                                                headers=addr())) == "password.linkInvalid")
r = anon.post("/portal/api/password/link", json={"token": token, "newPassword": "taken-over-password"}, headers=addr())
check("…and cannot set its password", r.status_code == 410 and code(r) == "password.linkInvalid"
      and not users.verify("gone", "taken-over-password") and users.get("gone")["disabled"])
bad = {**ORIGIN, "X-Forwarded-For": "10.9.9.9"}
for _ in range(10):
    anon.post("/portal/api/password/link/check", json={"token": "B" * 43}, headers=bad)
r = anon.post("/portal/api/password/link/check", json={"token": "C" * 43}, headers=bad)
check("ten invalid links per browser address, then a pause", r.status_code == 429 and code(r) == "password.linkLimit")

# ================================================================== 8. an administrator's reset
relay.clear()
maria_session, _ = client("maria", "maria-new-password")
r = root.post("/portal/api/users/maria/reset", json={}, headers=ORIGIN)
check("reset of a user with an address: a link by e-mail, no password shown", code(r) == "users.resetSent"
      and "password" not in r.get_json())
check("…the password stops working at once, the user's sessions end", client("maria", "maria-new-password")[1].status_code == 401
      and maria_session.get("/portal/api/config").status_code == 401)
messages = wait_messages(1)
purpose, token = link_in(messages[0]) if messages else (None, None)
check("…the message says an administrator reset it", messages and messages[0]["Subject"]
      == mailtexts.TEXTS["password-reset-admin"]["en-GB"][0] and purpose == "reset")
anon.post("/portal/api/password/link", json={"token": token, "newPassword": "maria-third-password"}, headers=addr())
check("…and the link sets a new password", client("maria", "maria-third-password")[1].status_code == 200)
check("journal: user-reset by link", any(e["action"] == "user-reset" and e.get("detail") == "maria link"
                                          for e in journal.search(user="root")))
root.post("/portal/api/users", json={"username": "lia", "role": "reader", "email": "lia@example.org", "invite": True},
          headers=ORIGIN)
time.sleep(0.5)
_, first_invite = link_in(wait_messages(3)[-1])
r = root.post("/portal/api/users/lia/reset", json={}, headers=ORIGIN)
messages = wait_messages(4)
purpose, second_invite = link_in(messages[-1])
check("reset of an invited user: a new invitation, the first link no longer works", code(r) == "users.resetSent"
      and purpose == "invite" and tokens.peek(first_invite) is None and tokens.peek(second_invite))
r = root.post("/portal/api/users/noaddr/reset", json={}, headers=ORIGIN)
check("reset of a user without an address: a temporary password, as before", code(r) == "users.reset"
      and r.get_json().get("password"))

# ================================================================== 9. security notices
relay.clear()
r = root.put("/portal/api/users/maria", json={"email": "maria.new@example.org"}, headers=ORIGIN)
messages = wait_messages(2)
check("address changed: one message to the old address, one to the new", code(r) == "users.updated"
      and sorted(m["To"] for m in messages) == ["maria.new@example.org", "maria@example.org"]
      and {m["Subject"] for m in messages} == {mailtexts.TEXTS["email-changed-old"]["en-GB"][0],
                                               mailtexts.TEXTS["email-changed-new"]["en-GB"][0]})
check("the old address is not told the new one", "maria.new" not in text_of(next(m for m in messages if m["To"] == "maria@example.org")))
relay.clear()
root.put("/portal/api/users/maria", json={"role": "editor", "email": "maria.new@example.org"}, headers=ORIGIN)
check("no message when the address does not change", not wait_messages(1, 0.8))
maria_session, _ = client("maria", "maria-third-password")
r = maria_session.post("/portal/api/password", json={"currentPassword": "maria-third-password",
                                                     "newPassword": "maria-fourth-password"}, headers=ORIGIN)
messages = wait_messages(1)
check("own password changed: a security message", code(r) == "password.changed" and messages
      and messages[0]["Subject"] == mailtexts.TEXTS["password-changed"]["en-GB"][0])
relay.clear()
lock_addr = {**ORIGIN, "X-Forwarded-For": "10.7.7.7"}
for _ in range(5):
    portal.app.test_client().post("/portal/api/login", json={"username": "maria", "password": "wrong"}, headers=lock_addr)
r = portal.app.test_client().post("/portal/api/login", json={"username": "maria", "password": "wrong"}, headers=lock_addr)
messages = wait_messages(1)
check("five wrong passwords lock the account and tell its owner once", r.status_code == 429 and len(wait_messages(2, 0.8)) == 1
      and messages[0]["Subject"] == mailtexts.TEXTS["account-locked"]["en-GB"][0] and "15" in text_of(messages[0]))
relay.clear()
for _ in range(5):
    portal.app.test_client().post("/portal/api/login", json={"username": "nobody", "password": "x"},
                                  headers={**ORIGIN, "X-Forwarded-For": "10.6.6.6"})
check("no message for a name without an account", not wait_messages(1, 0.8))
r = anon.post("/portal/api/password/forgot", json={"login": "maria.new@example.org"}, headers=addr())
_, token = link_in(wait_messages(1)[-1])
anon.post("/portal/api/password/link", json={"token": token, "newPassword": "maria-fifth-password"}, headers=addr())
check("a recovery opens a locked account", client("maria", "maria-fifth-password")[1].status_code == 200)

# ================================================================== 10. preferences
maria_session, _ = client("maria", "maria-fifth-password", language="pt-BR")
prefs = maria_session.get("/portal/api/preferences").get_json()
check("preferences: the address, the page's language until chosen, jobs off by default",
      prefs == {"email": "maria.new@example.org", "language": "pt-BR", "languageChosen": False, "notify": {"jobs": False}}, prefs)
r = maria_session.put("/portal/api/preferences", json={"language": "en-GB", "notify": {"jobs": True}}, headers=ORIGIN)
check("preferences saved", code(r) == "preferences.saved" and r.get_json()["preferences"]["notify"] == {"jobs": True}
      and r.get_json()["preferences"]["languageChosen"] is True)
client("maria", "maria-fifth-password", language="pt-BR")
check("a chosen language is not changed by the page", users.get("maria")["language"] == "en-GB")
check("an unknown category is refused", code(maria_session.put("/portal/api/preferences", json={"notify": {"security": False}},
                                                                headers=ORIGIN)) == "preferences.categoryUnknown")
check("an unknown language is refused", code(maria_session.put("/portal/api/preferences", json={"language": "fr-FR"},
                                                                headers=ORIGIN)) == "preferences.languageInvalid")
check("journal: preferences, without the address", any(e["action"] == "preferences" and "@" not in (e.get("detail") or "")
                                                        for e in journal.search(user="maria")))

# ================================================================== 11. notices of background jobs
relay.clear()
record = gtin("0950600013436")
csv_text = f"key;value;description;linkType;url;language\n01;{record};Imported;gs1:pip;https://x.example/a;en\n"
import base64  # noqa: E402
p = maria_session.post("/portal/api/import/preview", json={"filename": "t.csv", "labels": {},
                                                           "content": base64.b64encode(csv_text.encode()).decode()},
                       headers=ORIGIN).get_json()
maria_session.post("/portal/api/import/apply", json={"token": p.get("token")}, headers=ORIGIN)
messages = wait_messages(1)
check("import finished: a message with the counts (the user chose it)", messages
      and messages[0]["Subject"] == mailtexts.TEXTS["import-finished"]["en-GB"][0]
      and "Records created: 1" in text_of(messages[0]), [m["Subject"] for m in messages])
real_check = linkcheck.check_many
linkcheck.check_many = lambda urls, progress=None: {u: {"url": u, "ok": False, "status": 404, "code": "linkcheck.status"}
                                                    for u in urls}
relay.clear()
r = maria_session.post("/portal/api/links/jobs", json={"scope": "all"}, headers=ORIGIN)
messages = wait_messages(1)
check("check of every record finished: a message with the numbers", r.status_code == 202 and messages
      and messages[0]["Subject"] == mailtexts.TEXTS["linkcheck-finished"]["en-GB"][0] and "1 with a problem" in text_of(messages[0]),
      [text_of(m)[:200] for m in messages])
relay.clear()
maria_session.post("/portal/api/links/jobs", json={"urls": ["https://x.example/a"]}, headers=ORIGIN)
check("a check of a few addresses sends nothing", not wait_messages(1, 1.0))
linkcheck.check_many = real_check
maria_session.put("/portal/api/preferences", json={"notify": {"jobs": False}}, headers=ORIGIN)
p = maria_session.post("/portal/api/import/preview", json={"filename": "t.csv", "labels": {},
                                                           "content": base64.b64encode(csv_text.encode()).decode()},
                       headers=ORIGIN).get_json()
maria_session.post("/portal/api/import/apply", json={"token": p.get("token")}, headers=ORIGIN)
check("with the choice off, nothing", not wait_messages(1, 1.5))

# ================================================================== 12. the mail job: retries, failures, privacy
settle()
sent = [j for j in queued_mail() if j["state"] == "finished" and j.get("sent")]
check("a sent message leaves its job without its text", sent and all("text" not in j and "html" not in j for j in sent))
relay.clear()
relay.reply["RCPT"] = (451, "4.3.0 Try later")
r = anon.post("/portal/api/password/forgot", json={"login": "maria.new@example.org"}, headers=addr())
time.sleep(1.5)
job = store.col("jobs").find_one({"type": "mail", "template": "password-recovery", "state": "queued", "tries": 1})
check("a temporary refusal: back in the queue for a minute, with the relay's answer", job is not None
      and job["notBefore"] > store.now() + timedelta(seconds=40) and "451" in job["lastError"] and "text" in job,
      job and {k: job[k] for k in ("state", "tries", "lastError")})
relay.reply.clear()
store.col("jobs").update_one({"_id": job["_id"]}, {"$set": {"notBefore": store.now()}})
portal.worker.wake()
messages = wait_messages(1)
check("…and sent at the next try", messages and messages[0]["Subject"] == mailtexts.TEXTS["password-recovery"]["en-GB"][0]
      and store.col("jobs").find_one({"_id": job["_id"]})["tries"] == 2)
relay.clear()
relay.reply["RCPT"] = (550, "5.1.1 Mailbox unknown")
root.put("/portal/api/users/maria", json={"email": "maria.gone@example.org"}, headers=ORIGIN)
time.sleep(1.5)
failed = list(store.col("jobs").find({"type": "mail", "state": "failed"}))
check("a permanent refusal: the job fails at once, its text removed", len(failed) == 2
      and all("text" not in j and "html" not in j and j["error"] == "mail.failed" for j in failed), failed)
events = [e for e in journal.search(user="maria") if e["action"] == "mail-failed"]
check("journal: mail-failed with the template and the relay's answer, not the address",
      len(events) == 2 and all("550" in e["detail"] and "@" not in e["detail"] for e in events), events)
relay.reply.clear()
job_id = jobs.create("mail", "maria", "queued", 1, to="x@example.org", subject="s", text="t", template="test", tries=5)
store.col("jobs").update_one({"_id": job_id}, {"$set": {"notBefore": store.now() + timedelta(hours=1)}})
relay.reply["RCPT"] = (421, "4.7.0 Later")
store.col("jobs").update_one({"_id": job_id}, {"$set": {"notBefore": store.now()}})
portal.worker.wake()
time.sleep(1.5)
check("after the last try, a temporary refusal fails the message", store.col("jobs").find_one({"_id": job_id})["state"] == "failed")
relay.reply.clear()
relay.clear()
users.update("maria", disabled=True)
job_id = jobs.create("mail", "maria", "queued", 1, to="maria.gone@example.org", subject="s", text="t", template="test", tries=0)
portal.worker.wake()
time.sleep(1.2)
check("a message for an account disabled meanwhile is skipped", not relay.messages
      and store.col("jobs").find_one({"_id": job_id}).get("skipped") is True)
users.update("maria", disabled=False)
root.delete("/portal/api/users/lia", headers=ORIGIN)
check("removing a user removes his links", tokens.peek(second_invite) is None and not store.col("tokens").find_one({"user": "lia"}))
everything = str(list(store.col("journal").find()))
check("the journal holds no e-mail address", not re.search(r"[A-Za-z0-9._-]+@(?:example\.org|acme\.example)", everything),
      re.findall(r"[A-Za-z0-9._-]+@(?:example\.org|acme\.example)", everything)[:5])

# ================================================================== 13. messages in both languages
catalogue = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
blocks = re.split(r'\n    "(?:pt-BR|en-GB)": \{', catalogue)[1:]
pt_keys, en_keys = (set(re.findall(r'^      "([^"]+)":', b, re.M)) for b in blocks[:2])
codes = set(re.findall(r'(?:UserError|ValidationError|message)\("((?:password|preferences|users)\.[A-Za-z.]+)"',
                       open(os.path.join(PORTAL, "app.py"), encoding="utf-8").read()
                       + open(os.path.join(PORTAL, "users.py"), encoding="utf-8").read()))
check("every message code of e-mail is translated in both languages", codes <= pt_keys and codes <= en_keys
      and {"password.recoverySent", "password.linkInvalid", "users.invited", "preferences.saved"} <= codes,
      sorted(codes - (pt_keys & en_keys)))
actions = {"password-recovery", "password-reset", "invite-accepted", "preferences", "mail-failed"}
check("every new journal action has a name", {f"audit.action.{a}" for a in actions} <= pt_keys & en_keys)

relay.stop()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
