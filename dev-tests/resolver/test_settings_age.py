"""
The age of the portal's settings in the resolver's caches (finding F-033, Documentation/adr/0053-settings-age.md):
RESOLVER_SETTINGS_MAX_AGE_S and its limits; once a cache's reads of the portal's database have failed for longer than
that since its last good read, forwarding applies neither its prefix rules nor the resolver of last resort, the item's
page shows no brand and the pages the original appearance, while the domains, the strict mode and the request log's
retention keep their last values; one error line in the resolver's log when a cache becomes stale and one information
line when it is read again; the heartbeat's "settings" ("current" or "stale"). No Docker, no MongoDB: documents are
authored with the real data entry code and resolved with the real web server code through Flask's test client; the
portal's settings are in mongomock; the caches' clock is moved forward instead of waiting.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_settings_age.py
"""
import copy
import importlib
import logging
import os
import sys
import time
import types

import mongomock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))

# ---------------------------------------------------------------- stubs and authoring (as test_forwarding_resolver.py)
fake_mongo = types.ModuleType("mongo_db_init")
fake_mongo.mongo = None
fake_mongo.init_mongo = lambda app: None
sys.modules["mongo_db_init"] = fake_mongo
sys.path.insert(0, os.path.join(REPO, "data_entry_server", "src"))
sys.modules["data_entry_db"] = types.ModuleType("data_entry_db")
data_entry = importlib.import_module("data_entry_logic")
DB = {}


def author(doc):
    result = data_entry._author_db_linkset_document(doc)
    assert result["response_status"] == 200, result
    DB[result["data"]["_id"]] = result["data"]


sys.path.pop(0)
sys.modules.pop("data_entry_logic")
sys.path.insert(0, os.path.join(REPO, "web_server", "src"))
web_db = types.ModuleType("web_db")
web_db.read_document = lambda anchor: (
    {"response_status": 200, "data": copy.deepcopy(DB[anchor.replace("/", "_").lstrip("_")])}
    if anchor.replace("/", "_").lstrip("_") in DB else {"response_status": 404, "error": "nf"})
sys.modules["web_db"] = web_db
os.environ["FQDN"] = "id.example.org"
os.environ["MONGO_URI"] = "mongodb://unused"
os.environ.pop("PORTAL_DB_NAME", None)
os.environ.pop("RESOLVER_SETTINGS_MAX_AGE_S", None)
import web_logic  # noqa: E402
import request_log  # noqa: E402
import domains  # noqa: E402
import forwarding  # noqa: E402
import landing  # noqa: E402
import resolution  # noqa: E402
import settings_age  # noqa: E402
import web_pages  # noqa: E402


class Clock:
    """The caches' clock: time.monotonic() moved forward by the test, every other function of time unchanged."""
    now = 1_000_000.0

    def monotonic(self):
        return Clock.now

    def __getattr__(self, name):
        return getattr(time, name)


for module in (settings_age, domains, forwarding, landing, resolution, web_pages, request_log):
    module.time = Clock()


class Lines(logging.Handler):
    """The resolver's log lines, kept for the checks."""
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, record.name, record.getMessage()))


LOG = Lines()
logging.getLogger().addHandler(LOG)
logging.getLogger().setLevel(logging.INFO)

web_logic._call_gs1_toolkit = lambda s: "X" not in s
EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
PORTAL = mongomock.MongoClient()["resolver_portal"]
UP = {"ok": True}


def portal():
    """The portal's database, or the failure of an unreachable one."""
    if not UP["ok"]:
        raise RuntimeError("database down")
    return PORTAL


failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


# ---------------------------------------------------------------- the setting
saved = os.environ.pop(settings_age.SETTING, None)
check("RESOLVER_SETTINGS_MAX_AGE_S unset: 900 s (15 minutes), not invalid",
      settings_age.limit() == 900 and not settings_age.invalid(), settings_age.limit())
found = {}
for value in ("60", "86400", " 600 ", "59", "86401", "abc", "1.5", "-900", ""):
    os.environ[settings_age.SETTING] = value
    found[value] = (settings_age.limit(), settings_age.invalid())
check("…a whole number of seconds from 60 to 86400 is used; outside them or not a number 900 s, and it is invalid",
      found == {"60": (60, False), "86400": (86400, False), " 600 ": (600, False), "59": (900, True),
                "86401": (900, True), "abc": (900, True), "1.5": (900, True), "-900": (900, True), "": (900, False)},
      found)
os.environ.pop(settings_age.SETTING, None)

from __init__ import create_app  # noqa: E402

LOG.lines.clear()
os.environ[settings_age.SETTING] = "5"
create_app()
check("create_app warns about an invalid RESOLVER_SETTINGS_MAX_AGE_S and says the limit used",
      any(lvl == "WARNING" and "RESOLVER_SETTINGS_MAX_AGE_S must be a whole number of seconds from 60 to 86400: 900"
          in msg for lvl, _, msg in LOG.lines)
      and any("settings are used for 900 s at most" in msg for _, _, msg in LOG.lines), LOG.lines)
os.environ.pop(settings_age.SETTING, None)
if saved is not None:
    os.environ[settings_age.SETTING] = saved
LIMIT = settings_age.limit()

client = create_app().test_client()
domains.MAP.database = portal                   # the two caches a request reads here; the others unset
forwarding.FORWARDING.database = portal
for cache in (landing.BRANDS, resolution.STRICT, web_pages.APPEARANCE, request_log.RETENTION):
    cache.database = None

KNOWN = "/01/07891234500014"            # registered here; its company prefix 7891234 has a rule below
UNKNOWN = "/01/09506000134376"          # registered nowhere
author({"anchor": KNOWN, "itemDescription": "acme", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://acme.example.com/product", "title": "P", "type": "text/html",
     "hreflang": ["en"]}]})
PORTAL[forwarding.RULES].insert_one({"_id": "7891234", "target": "https://other.example.net", "mode": "path",
                                     "enabled": True})
PORTAL["settings"].insert_one({"_id": forwarding.SETTING_FALLBACK, "value": {"enabled": True}})


def ask(path):
    """One request; returns (response, the request log's event)."""
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    response = client.get("/api" + path, headers={"Accept": "text/html", "User-Agent":
                         "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148"})
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else {})


def later(seconds):
    """Moves the clock forward and lets every cache read again at its next use."""
    Clock.now += seconds


def heartbeat():
    return client.get("/api/heartbeat").get_json() or {}


# ---------------------------------------------------------------- forwarding: dropped once stale
r, e = ask(KNOWN)
check("forwarding read: a rule's prefix goes to its destination", r.status_code == 307
      and r.headers["Location"].startswith("https://other.example.net/01/07891234500014"), r.headers.get("Location"))
check("…and a key nobody registered to the resolver of last resort", ask(UNKNOWN)[0].headers.get("Location", "")
      .startswith("https://id.gs1.org/"))
check("the heartbeat: settings current, its message unchanged", heartbeat() == {
    "response_message": "Server is running!", "settings": "current"}, heartbeat())
UP["ok"] = False
LOG.lines.clear()
later(forwarding.CACHE_SECONDS)
check("the database down, within the limit: the rule still applied", ask(KNOWN)[0].headers.get("Location", "")
      .startswith("https://other.example.net/"))
check("…and the resolver of last resort still used", ask(UNKNOWN)[0].status_code == 307)
check("…the heartbeat still current", heartbeat().get("settings") == "current", heartbeat())
check("…no error line yet, a warning per failed read", not any(lvl == "ERROR" for lvl, _, _ in LOG.lines)
      and any(lvl == "WARNING" and "Forwarding not read" in msg for lvl, _, msg in LOG.lines), LOG.lines)
later(LIMIT - forwarding.CACHE_SECONDS + 1)
r, e = ask(KNOWN)
check("past the limit: the rule no longer applied, the key answered by this resolver's record",
      r.status_code == 307 and r.headers["Location"] == "https://acme.example.com/product"
      and e.get("o") == "redirect", (r.status_code, r.headers.get("Location"), e))
r, e = ask(UNKNOWN)
check("…and a key nobody registered is a 404, not sent to the resolver of last resort",
      r.status_code == 404 and e.get("o") == "unknown" and "Location" not in r.headers, (r.status_code, e))
errors = [msg for lvl, name, msg in LOG.lines if lvl == "ERROR" and msg.startswith("Forwarding")]
check("…one error line, naming the cache, its age, the limit and what is no longer applied",
      len(errors) == 1 and errors[0].startswith("Forwarding not read from the portal's database for ")
      and f"(RESOLVER_SETTINGS_MAX_AGE_S {LIMIT})" in errors[0]
      and "its prefix rules and the resolver of last resort are not applied until it is read again" in errors[0],
      errors)
later(forwarding.CACHE_SECONDS)
ask(KNOWN)
ask(UNKNOWN)
check("…not repeated at the next failed reads", len([1 for lvl, _, m in LOG.lines if lvl == "ERROR"
                                                    and m.startswith("Forwarding")]) == 1, LOG.lines)
check("the heartbeat: settings stale", heartbeat() == {"response_message": "Server is running!", "settings": "stale"},
      heartbeat())
check("…and the HEAD of the heartbeat still 200 without a body", (lambda h: h.status_code == 200 and not h.data)(
      client.head("/api/heartbeat")))
UP["ok"] = True
LOG.lines.clear()
later(forwarding.CACHE_SECONDS)
check("the database back: the rule applied again at the next read", ask(KNOWN)[0].headers.get("Location", "")
      .startswith("https://other.example.net/"))
check("…the resolver of last resort too", ask(UNKNOWN)[0].status_code == 307)
check("…one information line says so", [msg for lvl, _, msg in LOG.lines if lvl == "INFO"
                                        and msg.startswith("Forwarding read again")]
      == ["Forwarding read again from the portal's database; its settings are applied."], LOG.lines)
check("…the heartbeat current again", heartbeat().get("settings") == "current", heartbeat())
later(LIMIT * 2)
check("…and a good read ends the failure: no use for longer than the limit afterwards is not stale",
      not forwarding.FORWARDING.age.stale())

# ---------------------------------------------------------------- the age counts from the last good read
idle = forwarding.Forwarding(portal)
idle.rule_for("01", "07891234500014")
later(LIMIT * 3)
check("a cache not used for longer than the limit, its database answering: not stale (only failed reads count)",
      not idle.age.stale() and idle.rule_for("01", "07891234500014") is not None)
later(LIMIT * 3)
UP["ok"] = False
check("…but its first failed read after more than the limit: stale at once (its values are that old)",
      idle.rule_for("01", "07891234500014") is None and idle.fallback() is None and idle.age.stale())
UP["ok"] = True
fresh = forwarding.Forwarding(portal)
UP["ok"] = False
fresh.rule_for("01", "07891234500014")
later(LIMIT + 1)
fresh.forget()
check("the start of the process counts as a read: never read and failing past the limit, stale",
      fresh.age.stale() and fresh.rule_for("01", "07891234500014") is None)
UP["ok"] = True

# ---------------------------------------------------------------- brands and appearance: dropped once stale
brands = landing.BrandMap(portal)
PORTAL["branding"].insert_one({"_id": "7891234", "website": "https://acme.example.com", "colour": "#123456"})
check("a brand read", (brands.for_part("78912345") or {}).get("_id") == "7891234")
UP["ok"] = False
later(landing.CACHE_SECONDS)
check("…the database down, within the limit: the brand kept", (brands.for_part("78912345") or {}).get("_id")
      == "7891234" and brands.get("7891234") is not None)
later(LIMIT)
check("…past the limit: no brand (the item's page without it and its verified site)",
      brands.for_part("78912345") is None and brands.get("7891234") is None)
UP["ok"] = True
later(landing.CACHE_SECONDS)
check("…back with the database", (brands.for_part("78912345") or {}).get("_id") == "7891234")
appearance = web_pages.Appearance(portal)
PORTAL["settings"].insert_one({"_id": "appearance", "value": {"title": "Acme resolver"}})
check("the appearance read", appearance.current().get("title") == "Acme resolver")
UP["ok"] = False
later(web_pages.Appearance.CACHE_SECONDS)
check("…the database down, within the limit: kept", appearance.current().get("title") == "Acme resolver")
later(LIMIT)
check("…past the limit: the original appearance", appearance.current() == {})
UP["ok"] = True
later(web_pages.Appearance.CACHE_SECONDS)
check("…back with the database", appearance.current().get("title") == "Acme resolver")

# ---------------------------------------------------------------- domains, strict mode, retention: kept once stale
PORTAL["tenants"].insert_one({"_id": "acme", "prefixes": ["7891234"], "strictSafety": True, "logDays": 30})
PORTAL["domains"].insert_one({"_id": "id.acme.example", "verified": True, "mode": "direct", "stem": "",
                              "tenant": "acme"})
domain_map = domains.DomainMap(portal)
strict = resolution.StrictMode(portal)
retention = request_log.Retention(portal)
before = (domain_map.lookup("id.acme.example"), strict.on_for("01", "07891234500014"), retention.days_for("7891234"))
UP["ok"] = False
LOG.lines.clear()
later(max(domains.CACHE_SECONDS, resolution.CACHE_SECONDS, request_log.RETENTION_SECONDS) + LIMIT)
after = (domain_map.lookup("id.acme.example"), strict.on_for("01", "07891234500014"), retention.days_for("7891234"))
check("read: the organisation's domain limited to its prefix, its strict mode on, 30 days of retention",
      before == ({"stem": "", "prefixes": ["7891234"], "excluded": []}, True, 30), before)
check("…past the limit: the domain's limits kept (without them it would answer for every key), the strict mode kept "
      "(without it a withheld link would be given), the retention kept", after == before, after)
check("…each of the three stale, with its own error line saying what is kept",
      domain_map.age.stale() and strict.age.stale() and retention.age.stale()
      and sorted(msg.split(" not read")[0] + " / " + msg.split(": ", 1)[1] for lvl, _, msg in LOG.lines
                 if lvl == "ERROR") == [
          "Domains / the last domains read are kept until it is read again.",
          "Request log retention / the last retention read is kept until it is read again.",
          "Strict mode / the last strict mode read is kept until it is read again."],
      [m for lvl, _, m in LOG.lines if lvl == "ERROR"])
UP["ok"] = True

# ---------------------------------------------------------------- the heartbeat covers the six caches
check("the heartbeat reports the six caches of the portal's settings", {type(c).__name__ for c in
      __import__("web_namespace").SETTINGS_CACHES} == {"DomainMap", "Forwarding", "StrictMode", "BrandMap",
                                                         "Appearance", "Retention"})
web_pages.APPEARANCE.database = portal
heartbeat()
UP["ok"] = False
later(LIMIT + web_pages.Appearance.CACHE_SECONDS)
check("…a stale appearance alone makes it stale (the heartbeat reads each cache whose period has passed)",
      heartbeat().get("settings") == "stale" and web_pages.APPEARANCE.age.stale(), heartbeat())
UP["ok"] = True
later(max(web_pages.Appearance.CACHE_SECONDS, domains.CACHE_SECONDS, request_log.RETENTION_SECONDS))
check("…current once every cache is read again", heartbeat().get("settings") == "current", heartbeat())
web_pages.APPEARANCE.database = None

request_log.WRITER.flush()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
