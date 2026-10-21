"""
The installation's privacy notice (Documentation/adr/0017-privacy-notice.md): the default notice while none is
published (every language, with the operator's name and the days requests are kept, on the operator's responsibility
and "as is"), the page and its script for anyone signed in or not, versions published by server administrators only
(not an organisation's administrator, not during support access), every refusal (empty, too long, control characters,
a note too long, two administrators at once), versions never changed — the older ones readable by number, the list
newest first —, the journal, and the texts of every language.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_privacy.py
"""
import json
import os
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3417
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", RESOLVER_ORG_NAME="Example Operator",
                  RESOLVER_LOG_DAYS="90")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_privacy_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import privacy  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
store.col(privacy.COLLECTION).delete_many({})        # a real MongoDB may hold an earlier run's versions
failures = []
ORIGIN = {"Origin": "https://id.example.org"}
LANGS = ("pt-BR", "en-GB", "es", "fr", "de", "it", "tr", "zh-Hans", "ja", "ko", "hi", "ar")


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def client(username=None, password=None):
    c = portal.app.test_client()
    if username:
        c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def code(r):
    return (r.get_json(silent=True) or {}).get("code")


acme = tenants.create("Acme Foods", ["7891234"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
anyone, root, ana = client(), client("root", "root-password-long"), client("ana", "ana-password-long")

# ------------------------------------------------------------------ for anyone, before a version is published
r = anyone.get("/portal/api/privacy")
data = r.get_json() or {}
check("anyone, signed in or not: no version yet, the operator's name and the days requests are kept",
      r.status_code == 200 and data.get("notice") is None and data.get("versions") == [] and data.get("current") is None
      and data.get("operator") == "Example Operator" and data.get("days") == 90, data)
r = anyone.get("/portal/privacy")
html = r.get_data(as_text=True)
check("…the page itself, with the footer's notice and its own script", r.status_code == 200
      and '<script src="privacy.js"></script>' in html and 'data-page="privacy"' in html, r.status_code)
check("…its script, style and the project's logo without signing in", all(
      anyone.get("/portal/" + name).status_code == 200 for name in ("privacy.js", "app.css", "i18n.js", "logo.svg")))
check("…but not the portal's own script", anyone.get("/portal/app.js").status_code == 404)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
start = i18n.index("const CATALOGUE = {")
catalogues = {}
for tag in ("pt-BR", "en-GB"):
    block = i18n[i18n.index(f'    "{tag}": {{', start):]
    block = block[:block.index("\n    }")]
    catalogues[tag] = block
defaults = {}
for tag in LANGS:
    if tag in ("pt-BR", "en-GB"):
        line = next(l for l in catalogues[tag].split("\n") if l.startswith('      "privacy.default":'))
        defaults[tag] = json.loads(line.split(":", 1)[1].strip().rstrip(","))
    else:
        defaults[tag] = json.load(open(os.path.join(PORTAL, "static", "locales", tag + ".json"),
                                       encoding="utf-8"))["privacy.default"]
check("the default notice in every language, with the operator's name and the days requests are kept",
      all("{operator}" in t and "{days}" in t and t.startswith("# ") for t in defaults.values()),
      [tag for tag, t in defaults.items() if "{operator}" not in t or "{days}" not in t])
en = defaults["en-GB"]
check("…on the operator's sole responsibility, not GS1's nor the contributors', the software \"as is\"",
      "sole responsibility of whoever operates this instance" in en and "Neither GS1" in en
      and "anyone who contributed" in en and '"as is"' in en and "Apache License 2.0" in en, en[-700:])
check("…and in Portuguese", "estrita responsabilidade de quem opera esta instância" in defaults["pt-BR"]
      and "Nem a GS1" in defaults["pt-BR"] and '"no estado em que se encontra" ("as is")' in defaults["pt-BR"],
      defaults["pt-BR"][-600:])
check("…what is recorded: no address, an approximate location, the days", "address itself is not kept" in en
      and "approximate location" in en and "kept {days} days" in en)

# ------------------------------------------------------------------ publishing
r = anyone.put("/portal/api/privacy", json={"text": "x"}, headers=ORIGIN)
check("publishing: not without signing in", r.status_code == 401, r.status_code)
r = ana.put("/portal/api/privacy", json={"text": "x"}, headers=ORIGIN)
check("…not by an organisation's administrator (server administrators only)", r.status_code == 403, (r.status_code, code(r)))
for name, body, expected in (
        ("an empty text", {"text": "  \n "}, "privacy.textRequired"),
        ("no text", {}, "privacy.textRequired"),
        ("a text too long", {"text": "a" * (privacy.MAX_TEXT + 1)}, "privacy.textTooLong"),
        ("control characters", {"text": "Notice\x07"}, "privacy.textInvalid"),
        ("a note too long", {"text": "Notice", "note": "n" * (privacy.MAX_NOTE + 1)}, "privacy.noteTooLong")):
    r = root.put("/portal/api/privacy", json=body, headers=ORIGIN)
    check(f"…refused: {name} → {expected}", r.status_code == 422 and code(r) == expected, (r.status_code, r.get_json()))
check("…the limit named", root.put("/portal/api/privacy", json={"text": "a" * (privacy.MAX_TEXT + 1)},
                                   headers=ORIGIN).get_json()["params"] == {"max": privacy.MAX_TEXT})
check("…nothing stored by a refusal", store.col(privacy.COLLECTION).count_documents({}) == 0)
FIRST = "# Privacy\r\n\r\nOperated by {operator}.\r\n\r\n- one\n- two\n\nTab\tkept."
r = root.put("/portal/api/privacy", json={"text": FIRST, "note": "  First   version "}, headers=ORIGIN)
found = r.get_json() or {}
check("a server administrator publishes version 1: line breaks made \\n, tabs kept, the note's spaces tidied",
      r.status_code == 200 and code(r) == "privacy.published" and found.get("params") == {"version": 1}
      and found["notice"]["text"] == FIRST.replace("\r\n", "\n") and found["notice"]["note"] == "First version"
      and found["notice"]["by"] == "root", found)
entry = store.col("journal").find_one({"action": "privacy-publish"}) or {}
check("…in the journal, with the version", entry.get("user") == "root" and entry.get("detail") == "version=1", entry)
data = anyone.get("/portal/api/privacy").get_json()
check("…shown to anyone as the notice in force", data["notice"]["version"] == 1 and data["current"] == 1
      and data["notice"]["text"].startswith("# Privacy") and len(data["versions"]) == 1, data)
r = root.put("/portal/api/privacy", json={"text": "# Privacy\n\nSecond.", "note": "Contact added"}, headers=ORIGIN)
data = anyone.get("/portal/api/privacy").get_json()
check("version 2: in force, the list newest first and without the texts", data["current"] == 2
      and data["notice"]["text"] == "# Privacy\n\nSecond." and [v["version"] for v in data["versions"]] == [2, 1]
      and all("text" not in v for v in data["versions"]) and data["versions"][0]["note"] == "Contact added", data)
old = anyone.get("/portal/api/privacy?version=1").get_json()
check("…version 1 still readable as published, by its number", old["notice"]["version"] == 1
      and old["notice"]["text"] == FIRST.replace("\r\n", "\n") and old["current"] == 2, old)
for asked in ("9", "abc", "0"):
    r = anyone.get("/portal/api/privacy?version=" + asked)
    check(f"…an unknown version ({asked}): 404 privacy.unknown", r.status_code == 404 and code(r) == "privacy.unknown",
          (r.status_code, r.get_json()))
check("…no way to change or delete a version", root.delete("/portal/api/privacy", headers=ORIGIN).status_code == 405
      and root.post("/portal/api/privacy", json={"text": "x"}, headers=ORIGIN).status_code == 405)

# Two administrators at once: the second finds its number taken
original = privacy._col


class Stale:
    """The collection as one administrator saw it before another published: the last version is still 2."""

    def __init__(self, col):
        self.col = col

    def find_one(self, *args, **kwargs):
        return self.col.find_one({"_id": 2})

    def __getattr__(self, name):
        return getattr(self.col, name)


store.col(privacy.COLLECTION).insert_one({"_id": 3, "text": "Third", "note": "", "at": None, "by": "other"})
privacy._col = lambda: Stale(original())
r = root.put("/portal/api/privacy", json={"text": "Mine"}, headers=ORIGIN)
privacy._col = original
check("two administrators at once: the second refused (privacy.conflict), the first's version kept",
      r.status_code == 422 and code(r) == "privacy.conflict"
      and store.col(privacy.COLLECTION).find_one({"_id": 3})["text"] == "Third", (r.status_code, r.get_json()))

# Support access: read only
r = root.post("/portal/api/support", json={"tenant": acme["id"], "reason": "Ticket 9"}, headers=ORIGIN)
r = root.put("/portal/api/privacy", json={"text": "During support"}, headers=ORIGIN)
check("support access: no publishing (403 privacy.readOnly)", r.status_code == 403 and code(r) == "privacy.readOnly",
      (r.status_code, r.get_json()))
root.delete("/portal/api/support", headers=ORIGIN)

# ------------------------------------------------------------------ texts
keys = ["menu.privacy", "footer.privacy", "audit.action.privacy-publish", "privacy.title", "privacy.lede",
        "privacy.text", "privacy.textHint", "privacy.note", "privacy.preview", "privacy.publish",
        "privacy.confirmPublish", "privacy.published", "privacy.versions", "privacy.view", "privacy.defaultInUse",
        "privacy.versionOf", "privacy.defaultLabel", "privacy.older", "privacy.inForce", "privacy.history",
        "privacy.textRequired", "privacy.textTooLong", "privacy.textInvalid", "privacy.noteTooLong",
        "privacy.conflict", "privacy.unknown", "privacy.readOnly", "privacy.default"]
missing = [(tag, k) for tag in ("pt-BR", "en-GB") for k in keys if f'      "{k}":' not in catalogues[tag]]
for tag in LANGS[2:]:
    texts = json.load(open(os.path.join(PORTAL, "static", "locales", tag + ".json"), encoding="utf-8"))
    missing += [(tag, k) for k in keys if not texts.get(k)]
check(f"every text of the notice in the twelve languages ({len(keys)} keys)", not missing, missing[:10])
pages = json.load(open(os.path.join(PORTAL, "..", "web_server", "src", "page_texts.json"), encoding="utf-8"))
check("…the footer's link on the resolver's pages too", all(pages[tag]["pages"].get("privacy") for tag in LANGS)
      and pages["pt-BR"]["pages"]["privacy"] == "Aviso de privacidade")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
