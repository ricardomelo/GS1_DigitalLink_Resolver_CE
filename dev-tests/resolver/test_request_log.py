"""
Development test of the log of resolver requests (Documentation/adr/0006-resolver-request-log.md): what the resolver
records for each kind of request, what it never records, that answers do not change and that writing never holds a
request up. No Docker, no MongoDB: documents are authored with the real data entry code, resolved with the real web
server code through Flask's test client, and events are written to mongomock.

  pip install -r web_server/src/requirements.txt mongomock
  python dev-tests/resolver/test_request_log.py
"""
import copy
import importlib
import json
import os
import sys
import threading
import time
import types

import mongomock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))

# ---------------------------------------------------------------- stubs and authoring (as test_resolver.py)
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
    document = result["data"]
    if document["_id"] in DB:
        DB[document["_id"]]["data"].extend(document["data"])
    else:
        DB[document["_id"]] = document


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
os.environ.pop("RESOLVER_LOG_DAYS", None)
os.environ.pop("RESOLVER_LOG_COUNTRY_HEADER", None)
import web_logic  # noqa: E402
import request_log  # noqa: E402

web_logic._call_gs1_toolkit = lambda s: True
web_logic.uncompress_gs1_digital_link = lambda link: (
    {"SUCCESS": True, "identifiers": [{"01": "07898357410015"}], "qualifiers": [{"10": "123"}]} if link == "AbCdEf"
    else {"SUCCESS": False, "error": "not compressed"})
web_logic.compress_gs1_digital_link = lambda link: {"SUCCESS": True, "COMPRESSED": "https://id.example.org/AbCdEf"}

EVENTS = mongomock.MongoClient()["resolver_log"]["requests"]
request_log.WRITER.collection = lambda: EVENTS
from __init__ import create_app  # noqa: E402

client = create_app().test_client()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"


def ask(path, method="GET", accept="*/*", language="pt-BR,pt;q=0.9", agent=IPHONE, **headers):
    """One request; returns (response, the event it produced or None)."""
    request_log.WRITER.flush()
    EVENTS.delete_many({})
    sent = {"Accept": accept, "User-Agent": agent, "X-Forwarded-For": "203.0.113.9", **headers}
    if language is not None:
        sent["Accept-Language"] = language
    response = client.open("/api" + path, method=method, headers=sent)
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else (None if not found else found))


G = "/01/07898357410015"
author({"anchor": G, "itemDescription": "Product", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://www.example.org/product", "title": "Product", "type": "text/html", "hreflang": ["pt"]},
    {"linktype": "gs1:instructions", "href": "https://www.example.org/manual/pt", "title": "Manual", "type": "text/html", "hreflang": ["pt"]},
    {"linktype": "gs1:instructions", "href": "https://www.example.org/manual/en", "title": "Manual", "type": "text/html", "hreflang": ["en"]}]})
author({"anchor": G, "qualifiers": [{"10": "123"}], "itemDescription": "Batch", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://batch.example.org/123", "title": "Batch", "type": "text/html", "hreflang": ["pt"]}]})
author({"anchor": G, "qualifiers": [{"21": "SERIAL777"}], "itemDescription": "Unit", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://unit.example.org/one", "title": "Unit", "type": "text/html", "hreflang": ["pt"]}]})
author({"anchor": "/01/79521141123453", "itemDescription": "EPC", "defaultLinktype": "gs1:pip", "links": [
    {"linktype": "gs1:pip", "href": "https://epc.example.org/", "title": "EPC", "type": "text/html"}]})

# ---------------------------------------------------------------- a redirect, field by field
r, e = ask(G + "?17=261231&3103=000500&linkType=gs1:pip", Referer="https://www.example.com/page?secret=1")
check("a redirect is answered as before", r.status_code == 307
      and r.headers["Location"] == "https://www.example.org/product?17=261231&3103=000500&linkType=gs1:pip",
      (r.status_code, r.headers.get("Location")))
check("one event per request", isinstance(e, dict), e)
e = e if isinstance(e, dict) else {}
check("method, form, key and company part", (e.get("m"), e.get("f"), e.get("ai"), e.get("v"), e.get("cp"))
      == ("GET", "uri", "01", "07898357410015", "7898357410015"), e)
check("status and outcome", (e.get("s"), e.get("o")) == (307, "redirect"), e)
check("the level that answered: the key's", e.get("lvl") == "", e)
check("the link type asked, without the vocabulary's prefix", e.get("lt") == "pip", e)
check("the data attributes' AIs, in order", e.get("da") == ["17", "3103"], e)
check("the target's host only", e.get("to") == "www.example.org", e)
check("the language, lower case", e.get("lang") == "pt-br", e)
check("the device class", e.get("dev") == "mobile", e)
check("the referrer's host only", e.get("ref") == "www.example.com", e)
check("the time taken, in whole milliseconds", isinstance(e.get("ms"), int) and e["ms"] >= 0, e)
check("time and expiry: 90 days by default", isinstance(e.get("t"), object) and e.get("expiresAt") is not None
      and abs((e["expiresAt"] - e["t"]).total_seconds() - 90 * 86400) < 1, e)
text = json.dumps(e, default=str)
check("never the client's address", "203.0.113" not in text, text)
check("never the User-Agent", "iPhone" not in text and "Mozilla" not in text, text)
check("never the full referrer", "secret" not in text and "/page" not in text, text)
check("never the values of data attributes", "261231" not in text and "000500" not in text, text)
check("only the documented fields", set(e) <= {"t", "expiresAt", "m", "f", "epc", "ai", "v", "cp", "q", "da", "lt", "s",
                                                "o", "lvl", "to", "ms", "lang", "dev", "ref", "c", "p"}, sorted(e))
check("no country without RESOLVER_LOG_COUNTRY_HEADER", "c" not in e, e)

# ---------------------------------------------------------------- levels and unit qualifiers
r, e = ask(G + "/10/123")
check("a batch: qualifier value kept, the batch level answered",
      r.status_code == 307 and e and e.get("q") == {"10": "123"} and e.get("lvl") == "/10/123", e)
r, e = ask(G + "/10/123/21/SERIAL777")
check("a serial number: its AI kept, never its value (most specific level: the serial's)",
      r.status_code == 307 and e and e.get("q") == {"10": "123", "21": None} and e.get("lvl") == "/21/*", e)
check("…the serial value appears nowhere in the event", "SERIAL777" not in json.dumps(e, default=str), e)
r, e = ask(G + "/10/999/21/OTHER")
check("an unknown batch walks up to the key's level", r.status_code == 307 and e and e.get("lvl") == "", e)
r, e = ask(G + "/235/TPX42")
check("a TPX: only its AI", e and e.get("q") == {"235": None} and "TPX42" not in json.dumps(e, default=str), e)

# ---------------------------------------------------------------- other outcomes
r, e = ask("/01/09506000000000")
body = r.get_json(force=True) or {}
check("an unregistered code: 404 'unknown'", r.status_code == 404 and e and e.get("o") == "unknown" and e.get("s") == 404, e)
check("…the 404 answer is unchanged (no private keys)", set(body) == {"response_status", "error"}, body)
r, e = ask(G + "?linkType=gs1:recallStatus")
body = r.get_json(force=True) or {}
check("a link type the record does not have: 404 'noLink'", r.status_code == 404 and e and e.get("o") == "noLink"
      and e.get("lt") == "recallStatus", e)
check("…the 404 answer is unchanged", set(body) == {"response_status", "error"}, body)
r, e = ask(G + "?linkType=gs1:instructions", language="de")
check("several links, none decided: 300 'choice' at the key's level", r.status_code == 300 and e and e.get("o") == "choice"
      and e.get("lvl") == "" and e.get("lang") == "de", e)
check("…the 300 answer carries no private key", "_level" not in r.get_data(as_text=True), r.get_data(as_text=True)[:200])
r, e = ask(G, accept="application/linkset+json")
check("a linkset: 200 'linkset', link type 'linkset'", r.status_code == 200 and e and e.get("o") == "linkset"
      and e.get("lt") == "linkset" and "lvl" not in e and "to" not in e, e)
r, e = ask(G + "?linkType=all")
check("linkType=all is a linkset too", e and e.get("lt") == "linkset", e)
r, e = ask(G + "/21/S1/10/L1")
check("a request the syntax check refuses: 400 'invalid', key kept, no path",
      r.status_code in (400, 307) and e and (e.get("o") == "invalid") == (r.status_code == 400) and "p" not in e, (r.status_code, e))
r, e = ask("/wp-login.php", agent="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
check("a probe: 400 'invalid', its path kept (no key), automated",
      r.status_code == 400 and e and e.get("o") == "invalid" and e.get("p") == "/wp-login.php" and "ai" not in e
      and e.get("dev") == "automated", e)
r, e = ask("/AbCdEf?17=261231")
check("a compressed GS1 Digital Link: form 'compressed', key and qualifiers as decompressed, no path",
      r.status_code == 307 and e and e.get("f") == "compressed" and e.get("ai") == "01" and e.get("q") == {"10": "123"}
      and e.get("lvl") == "/10/123" and e.get("da") == ["17"] and "p" not in e, e)
r, e = ask(G + "?compress=true")
check("?compress: 'compressed'", r.status_code == 200 and e and e.get("o") == "compressed", e)
AIDC = "/ehf7b07898357410015624b510031ec5cd67c0"      # SGTIN+ with +AIDC (10)123 and (17)261231
r, e = ask(AIDC)
check("an EPC binary string: form 'epc' with its scheme, batch and serial's AI from the tag, the expiry date's AI only",
      r.status_code == 307 and e and e.get("f") == "epc" and e.get("epc") == "SGTIN+" and e.get("ai") == "01"
      and e.get("q") == {"10": "123", "21": None} and e.get("da") == ["17"] and "261231" not in json.dumps(e, default=str), e)
r, e = ask("/eh00000000000000000000000000")
check("an EPC binary string that does not decode: 'invalid', form 'epc'", r.status_code == 400 and e
      and e.get("o") == "invalid" and e.get("f") == "epc", e)
r, e = ask(G, method="HEAD")
check("HEAD is recorded with its method", r.status_code == 307 and e and e.get("m") == "HEAD", e)
r, e = ask(G, language=None)
check("no Accept-Language: no language", e and "lang" not in e, e)
r, e = ask(G, language="*")
check("Accept-Language '*': no language", e and "lang" not in e, e)
r, e = ask(G, agent="")
check("no User-Agent: device 'unknown'", e and e.get("dev") == "unknown", e)

# ---------------------------------------------------------------- not recorded
for path in ["/heartbeat", "/favicon.ico", "/robots.txt", "/.well-known/gs1resolver"]:
    r, e = ask(path)
    check(f"{path} is not recorded", e is None, (r.status_code, e))   # (/heartbeat answers 500 here, as before)
r, e = ask(G, method="OPTIONS")
check("OPTIONS is not recorded", e is None, e)

# ---------------------------------------------------------------- settings
os.environ["RESOLVER_LOG_COUNTRY_HEADER"] = "CF-IPCountry"
r, e = ask(G, **{"CF-IPCountry": "br"})
check("country from the configured header, upper case", e and e.get("c") == "BR", e)
r, e = ask(G, **{"CF-IPCountry": "Brazil"})
check("…only a two-letter code", e and "c" not in e, e)
del os.environ["RESOLVER_LOG_COUNTRY_HEADER"]
os.environ["RESOLVER_LOG_DAYS"] = "30"
r, e = ask(G)
check("RESOLVER_LOG_DAYS sets the expiry", e and abs((e["expiresAt"] - e["t"]).total_seconds() - 30 * 86400) < 1, e)
os.environ["RESOLVER_LOG_DAYS"] = "0"
written = request_log.WRITER.written
r, e = ask(G)
check("RESOLVER_LOG_DAYS=0 switches the log off (nothing written); the answer is the same",
      e is None and request_log.WRITER.written == written and r.status_code == 307
      and r.headers["Location"] == "https://www.example.org/product", (r.status_code, e, request_log.WRITER.written - written))
del os.environ["RESOLVER_LOG_DAYS"]
indexes = EVENTS.index_information()
check("indexes: time, company part, key, expiry (TTL)",
      any(v.get("expireAfterSeconds") == 0 and v["key"] == [("expiresAt", 1)] for v in indexes.values())
      and any(v["key"] == [("cp", 1), ("t", -1)] for v in indexes.values())
      and any(v["key"] == [("ai", 1), ("v", 1), ("t", -1)] for v in indexes.values()), indexes)

# ---------------------------------------------------------------- device classes
for agent, expected in [
    ("curl/8.5.0", "automated"), ("python-requests/2.32", "automated"), ("Wget/1.21", "automated"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36 (compatible; Googlebot/2.1)", "automated"),
    ("facebookexternalhit/1.1", "automated"), ("WhatsApp/2.23 A", "unknown"),
    ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)", "tablet"),
    ("Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 Safari/537.36", "tablet"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36", "mobile"),
    ("okhttp/4.12.0", "mobile"), ("Dalvik/2.1.0 (Linux; U; Android 12)", "mobile"),
    ("Scanner/3 CFNetwork/1490 Darwin/23.2.0", "mobile"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36", "desktop"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15", "desktop"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "desktop"), ("", "unknown")]:
    check(f"device class of {agent[:50]!r}: {expected}", request_log.device_class(agent) == expected,
          request_log.device_class(agent))

# ---------------------------------------------------------------- writing never holds a request up
class Blocking:
    """A collection whose writes wait until released."""
    def __init__(self):
        self.release, self.batches = threading.Event(), []

    def create_index(self, *a, **k):
        pass

    def insert_many(self, docs, ordered=True):
        self.release.wait(10)
        self.batches.append(len(docs))


saved = request_log.WRITER
blocking = Blocking()
request_log.WRITER = request_log.Writer(collection=lambda: blocking, size=5)
started = time.perf_counter()
answers = [client.get("/api" + G, headers={"User-Agent": IPHONE}).status_code for _ in range(30)]
elapsed = time.perf_counter() - started
check("30 requests answered while the database does not answer", answers == [307] * 30, answers)
check("…without waiting for it (under 3 s)", elapsed < 3, elapsed)
check("…events beyond the queue are lost and counted", request_log.WRITER.lost_total >= 20, request_log.WRITER.lost_total)
blocking.release.set()
request_log.WRITER.flush()


class Failing:
    def create_index(self, *a, **k):
        pass

    def insert_many(self, docs, ordered=True):
        raise RuntimeError("database down")


request_log.WRITER = request_log.Writer(collection=lambda: Failing())
r = client.get("/api" + G)
request_log.WRITER.flush()
check("a failing database: the answer is the same, the events lost and counted",
      r.status_code == 307 and request_log.WRITER.lost_total == 1, (r.status_code, request_log.WRITER.lost_total))


class Counting(Blocking):
    def __init__(self):
        super().__init__()
        self.release.set()


counting = Counting()
request_log.WRITER = request_log.Writer(collection=lambda: counting)
for _ in range(1200):
    request_log.WRITER.put({"t": 1})
request_log.WRITER.flush(10)
check("events are written in batches of at most 500", sum(counting.batches) == 1200 and max(counting.batches) <= 500
      and len(counting.batches) >= 3, counting.batches)
request_log.WRITER = saved

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
