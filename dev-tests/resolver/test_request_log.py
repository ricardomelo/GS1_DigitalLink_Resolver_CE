"""
Development test of the log of resolver requests (Documentation/adr/0006-resolver-request-log.md): what the resolver
records for each kind of request, what it never records, that answers do not change and that writing never holds a
request up; the browser family, the approximate location from a GeoIP database (written here with mmdb-writer, the
client's address never kept) and the retention the portal sets, per organisation (ADR 0006, section 8). No Docker, no
MongoDB: documents are authored with the real data entry code, resolved with the real web server code through Flask's
test client, and events are written to mongomock.

  pip install -r web_server/src/requirements.txt mongomock mmdb-writer
  python dev-tests/resolver/test_request_log.py
"""
import copy
import importlib
import json
from datetime import datetime, timedelta
import os
import sys
import threading
import time
import types

import logging
import tempfile

import mongomock
from mmdb_writer import MMDBWriter
from netaddr import IPSet

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
os.environ.pop("RESOLVER_LOG_ADDRESS_HEADER", None)
os.environ["RESOLVER_GEOIP_DB"] = ""          # no location until the GeoIP section
import web_logic  # noqa: E402
import request_log  # noqa: E402
import geoip  # noqa: E402
import gs1_syntax  # noqa: E402

SYNTAX_CHECK = web_logic._call_gs1_toolkit
web_logic._call_gs1_toolkit = lambda s: True
web_logic.uncompress_gs1_digital_link = lambda link: (
    {"SUCCESS": True, "identifiers": [{"01": "07898357410015"}], "qualifiers": [{"10": "123"}]} if link == "AbCdEf"
    else {"SUCCESS": False, "error": "not compressed"})
web_logic.compress_gs1_digital_link = lambda link: {"SUCCESS": True, "COMPRESSED": "https://id.example.org/AbCdEf"}

MONGO = mongomock.MongoClient()
EVENTS = MONGO["resolver_log"]["requests"]
COUNTS = MONGO["resolver_log"]["request_counts"]      # automated requests and requests without a key (section 11)
COUNTED = []                                           # the counts of the last ask()
PORTAL_DB = MONGO["resolver_portal"]
request_log.WRITER.collection = lambda: EVENTS
request_log.RETENTION.database = lambda: PORTAL_DB
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
    COUNTS.delete_many({})
    sent = {"Accept": accept, "User-Agent": agent, "X-Forwarded-For": "203.0.113.9", **headers}
    if language is not None:
        sent["Accept-Language"] = language
    response = client.open("/api" + path, method=method, headers=sent)
    request_log.WRITER.flush()
    found = list(EVENTS.find({}, {"_id": 0}))
    COUNTED[:] = list(COUNTS.find({}, {"_id": 0}))
    return response, (found[0] if len(found) == 1 else (None if not found else found))


def counted():
    """The one count of the last ask(), or None."""
    return COUNTED[0] if len(COUNTED) == 1 else None


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
check("the browser family", e.get("br") == "app", e)       # an iPhone User-Agent without "Safari/": an app's web view
check("only the documented fields", set(e) <= {"t", "expiresAt", "m", "f", "epc", "ai", "v", "cp", "q", "da", "lt", "s",
                                                "o", "lvl", "to", "ms", "lang", "dev", "br", "ref", "c", "rg", "ci",
                                                "ll", "p"}, sorted(e))
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
c = counted()
check("a probe from a crawler: 400 'invalid', counted, not stored (section 11); no path, no key in the count",
      r.status_code == 400 and e is None and c and c.get("o") == "invalid" and c.get("dev") == "automated"
      and c.get("n") == 1 and "p" not in c and "ai" not in c and c.get("f") == "uri", (e, COUNTED))
r, e = ask("/wp-login.php")
c = counted()
check("…from a phone's browser too: no key, counted with its device and browser", e is None and c
      and c.get("dev") == "mobile" and c.get("br") == "app" and c.get("o") == "invalid", (e, COUNTED))
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
# The syntax check as a resolver makes it (the GS1 Barcode Syntax Engine; without it here, a check that refuses
# everything, as the engine refuses these three paths): the stub above would let a probe reach the database
web_logic._call_gs1_toolkit = SYNTAX_CHECK if gs1_syntax.available() else (lambda s: False)
r, e = ask("/wp-admin/setup-config.php", agent=DESKTOP)
c = counted()
check("a probe of two segments from a browser (400, as the syntax check answers it): its first segment is no "
      "primary key, counted, not stored; no key in the count", r.status_code == 400 and e is None and c
      and "ai" not in c and "v" not in c and "cp" not in c and c.get("o") == "invalid" and c.get("dev") == "desktop",
      (r.status_code, e, COUNTED))
r, e = ask("/2024/01/shell.php", agent=DESKTOP)
c = counted()
check("…a number that is no primary key (a year) neither: counted, no key, no company part", e is None and c
      and "ai" not in c and "cp" not in c, (e, COUNTED))
r, e = ask("/01/wp-login.php", agent=DESKTOP)
check("…but a primary key with a value that is not one is a GS1 code read wrong: stored, with its key",
      r.status_code == 400 and e and e.get("ai") == "01" and e.get("v") == "wp-login.php" and e.get("o") == "invalid",
      (r.status_code, e))
web_logic._call_gs1_toolkit = lambda s: True
check("the resolver's primary keys are those of GS1's dictionary (the portal's)",
      request_log.KEY_AIS == set(json.load(open(os.path.join(REPO, "portal", "gs1_dictionary.json")))["ais"].keys()
                                 & {code for code, entry in json.load(open(os.path.join(REPO, "portal",
                                    "gs1_dictionary.json")))["ais"].items() if "dlpkey" in entry}),
      sorted(request_log.KEY_AIS))
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
c = counted()
check("an EPC binary string that does not decode: 'invalid', form 'epc', counted (no key)", r.status_code == 400
      and e is None and c and c.get("o") == "invalid" and c.get("f") == "epc", (e, COUNTED))
r, e = ask(G, method="HEAD")
check("HEAD is recorded with its method", r.status_code == 307 and e and e.get("m") == "HEAD", e)
r, e = ask(G, language=None)
check("no Accept-Language: no language", e and "lang" not in e, e)
r, e = ask(G, language="*")
check("Accept-Language '*': no language", e and "lang" not in e, e)
r, e = ask(G, agent="")
check("no User-Agent: device 'unknown', no browser", e and e.get("dev") == "unknown" and "br" not in e, e)
r, e = ask(G, agent="curl/8.5.0")
c = counted()
check("an automated client with a key: counted, not stored; its key, outcome, no browser", e is None and c
      and (c.get("ai"), c.get("v"), c.get("cp"), c.get("o"), c.get("dev")) == ("01", "07898357410015", "7898357410015",
                                                                                "redirect", "automated")
      and "br" not in c and c.get("n") == 1, (e, COUNTED))
check("…its quarter of an hour, UTC", c and c["b"].minute % 15 == 0 and c["b"].second == 0
      and c["b"].microsecond == 0 and timedelta(0) <= datetime.utcnow() - c["b"] < timedelta(minutes=16), c)
request_log.WRITER.flush()
COUNTS.delete_many({})
for query in ("", "", "", "?linkType=gs1:instructions"):
    client.get("/api" + G + query, headers={"User-Agent": "curl/8.5.0", "Accept-Language": "pt-BR"})
request_log.WRITER.flush()
found = sorted(COUNTS.find({}), key=lambda d: -d["n"])
check("…requests of the same group add up in one count (n, times summed, the longest kept); another link type, "
      "another count", [d["n"] for d in found] == [3, 1] and all(0 <= d["msMax"] <= d["ms"] for d in found)
      and found[1].get("lt") == "instructions" and EVENTS.count_documents({}) == 0, found)
counts_indexes = COUNTS.index_information()
check("…indexes of the counts: quarter, company part, expiry (TTL)",
      any(v.get("expireAfterSeconds") == 0 and v["key"] == [("expiresAt", 1)] for v in counts_indexes.values())
      and any(v["key"] == [("cp", 1), ("b", -1)] for v in counts_indexes.values())
      and any(v["key"] == [("b", -1)] for v in counts_indexes.values()), counts_indexes)

# ---------------------------------------------------------------- not recorded
for path in ["/heartbeat", "/favicon.ico", "/robots.txt", "/.well-known/gs1resolver"]:
    r, e = ask(path)
    check(f"{path} is not recorded", e is None, (r.status_code, e))
    if path == "/heartbeat":
        check("/heartbeat answers 200 with its message (the official code answered 500)", r.status_code == 200
              and (r.get_json(silent=True) or {}).get("response_message") == "Server is running!",
              (r.status_code, r.data[:200]))
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

# ---------------------------------------------------------------- browser families
for agent, expected in [
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36", "chrome"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1", "chrome"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", "safari"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", "safari"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "firefox"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/131.0 Mobile/15E148 Safari/605.1.15", "firefox"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0", "edge"),
    ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36 OPR/84.0", "opera"),
    ("Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0 Mobile Safari/537.36", "samsung"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0 Mobile Safari/537.36", "app"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 350.0", "app"),
    ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/480.0;]", "app"),
    ("okhttp/4.12.0", "app"), ("Scanner/3 CFNetwork/1490 Darwin/23.2.0", "app"),
    ("Mozilla/5.0 (Windows NT 10.0) Gecko Trident/7.0; rv:11.0", "other")]:
    check(f"browser family of {agent[:60]!r}…: {expected}", request_log.browser_family(agent) == expected,
          request_log.browser_family(agent))

# ---------------------------------------------------------------- approximate location (GeoIP)
WORK = tempfile.mkdtemp(prefix="geoip-test-")


def write_geoip(path, networks):
    """An MMDB in the GeoIP2 City layout, as DB-IP's City Lite."""
    writer = MMDBWriter(ip_version=6, database_type="DBIP-City-Lite", languages=["en"],
                        description={"en": "dev-tests"}, ipv4_compatible=True)
    for network, country, region, city in networks:
        record = {"country": {"iso_code": country, "names": {"en": country}},
                  "location": {"latitude": -22.9, "longitude": -47.06}}
        if region:
            record["subdivisions"] = [{"names": {"en": region}}]
        if city:
            record["city"] = {"names": {"en": city, "pt-BR": city + " (pt)"}}
        writer.insert_network(IPSet([network]), record)
    writer.to_db_file(path)


DBFILE = os.path.join(WORK, "dbip-city-lite.mmdb")
write_geoip(DBFILE, [("191.0.0.0/16", "BR", "Sao Paulo", "Campinas"), ("2804:1::/32", "BR", "Parana", "Curitiba"),
                     ("81.2.69.0/24", "GB", "England", "London"), ("41.0.0.0/16", "ZA", None, None),
                     # private networks in the file too: such an address is never looked up
                     ("10.0.0.0/8", "XX", "Private", "Nowhere"), ("192.168.0.0/16", "XX", "Private", "Nowhere")])
os.environ["RESOLVER_GEOIP_DB"] = DBFILE
geoip.CHECK_SECONDS = 0
messages = []


class Keep(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())


logging.getLogger().addHandler(Keep())
logging.getLogger().setLevel(logging.INFO)
r, e = ask(G, **{"X-Real-IP": "191.0.5.77"})
check("the location of the address in X-Real-IP: country, region and city", e and (e.get("c"), e.get("rg"), e.get("ci"))
      == ("BR", "Sao Paulo", "Campinas"), e)
check("…the names in English", e and e.get("ci") == "Campinas", e)
check("…the city's position, to a tenth of a degree (about 11 km), for the map", e and e.get("ll") == [-22.9, -47.1], e)
check("…never the address, nor the database's exact coordinates (only the rounded city position)", e
      and "191.0" not in json.dumps(e, default=str) and "47.06" not in json.dumps(e, default=str)
      and not {"lat", "lon", "ip"} & set(e), e)
check("…the answer is the same", r.status_code == 307 and r.headers["Location"] == "https://www.example.org/product",
      r.headers.get("Location"))
r, e = ask(G, **{"X-Real-IP": "2804:1:abcd::7"})
check("an IPv6 address", e and (e.get("c"), e.get("rg"), e.get("ci")) == ("BR", "Parana", "Curitiba"), e)
r, e = ask(G, **{"X-Real-IP": "41.0.3.3"})
check("a network the database knows only by country: no region, city or position", e and e.get("c") == "ZA"
      and "rg" not in e and "ci" not in e and "ll" not in e, e)
for address in ("10.1.2.3", "127.0.0.1", "192.168.0.9", "fd00::1", "203.0.113.9", "not-an-address", "8.8.8.8"):
    r, e = ask(G, **{"X-Real-IP": address})
    check(f"no location for {address!r} (private, reserved, malformed or not in the database)", e and "c" not in e
          and "ci" not in e and r.status_code == 307, e)
r, e = ask(G, **{"X-Real-IP": "81.2.69.160:51000"})
check("an address with its port", e and e.get("ci") == "London", e)
r, e = ask(G, **{"X-Real-IP": "::ffff:81.2.69.1"})
check("an IPv4-mapped IPv6 address", e and e.get("ci") == "London", e)
r, e = ask(G, **{"X-Forwarded-For": "81.2.69.1, 191.0.5.77"})
check("X-Forwarded-For is not read by default (anyone can write it)", e and "ci" not in e, e)
os.environ["RESOLVER_LOG_ADDRESS_HEADER"] = "X-Forwarded-For"
r, e = ask(G, **{"X-Forwarded-For": "81.2.69.1, 191.0.5.77"})
check("RESOLVER_LOG_ADDRESS_HEADER names another header: its first address", e and e.get("ci") == "London", e)
os.environ["RESOLVER_LOG_ADDRESS_HEADER"] = ""
request_log.WRITER.flush()
EVENTS.delete_many({})
client.get("/api" + G, headers={"User-Agent": IPHONE, "X-Real-IP": "81.2.69.1"}, environ_base={"REMOTE_ADDR": "191.0.9.9"})
request_log.WRITER.flush()
e = EVENTS.find_one({}) or {}
check("an empty RESOLVER_LOG_ADDRESS_HEADER: the connection's address", e.get("ci") == "Campinas", e)
del os.environ["RESOLVER_LOG_ADDRESS_HEADER"]
os.environ["RESOLVER_LOG_COUNTRY_HEADER"] = "CF-IPCountry"
r, e = ask(G, **{"X-Real-IP": "191.0.5.77", "CF-IPCountry": "BR"})
check("a country header that agrees keeps the region and city", e and (e.get("c"), e.get("ci")) == ("BR", "Campinas"), e)
r, e = ask(G, **{"X-Real-IP": "191.0.5.77", "CF-IPCountry": "PT"})
check("a country header that disagrees wins, without the database's region, city and position", e and e.get("c") == "PT"
      and "rg" not in e and "ci" not in e and "ll" not in e, e)
del os.environ["RESOLVER_LOG_COUNTRY_HEADER"]
time.sleep(0.05)
write_geoip(DBFILE + ".new", [("191.0.0.0/16", "BR", "Sao Paulo", "Sao Paulo")])
os.replace(DBFILE + ".new", DBFILE)
os.utime(DBFILE, (time.time() + 5, time.time() + 5))
r, e = ask(G, **{"X-Real-IP": "191.0.5.77"})
check("a newer file replacing the database is read without a restart", e and e.get("ci") == "Sao Paulo", e)
with open(DBFILE, "wb") as fh:
    fh.write(b"not a database")
os.utime(DBFILE, (time.time() + 10, time.time() + 10))
r, e = ask(G, **{"X-Real-IP": "191.0.5.77"})
check("a broken file: no location, the same answer", e and "c" not in e and r.status_code == 307, e)
os.environ["RESOLVER_GEOIP_DB"] = os.path.join(WORK, "missing.mmdb")
r, e = ask(G, **{"X-Real-IP": "191.0.5.77"})
check("no file: no location, the same answer", e and "c" not in e and r.status_code == 307, e)
check("the client's address is never written in the resolver's output",
      messages and not any("191.0" in m or "81.2.69" in m or "2804:1" in m for m in messages),
      [m for m in messages if "191.0" in m or "81.2" in m])
check("…which says when there is no database", any("No GeoIP database" in m for m in messages), messages[-5:])
os.environ["RESOLVER_GEOIP_DB"] = ""

# ---------------------------------------------------------------- retention set in the portal
def kept_days(e):
    if not e and counted():            # a request counted, not stored: its count's expiry
        e = {"expiresAt": counted()["expiresAt"], "t": counted()["b"]}
    return round((e["expiresAt"] - e["t"]).total_seconds() / 86400) if e else None


PORTAL_DB["settings"].insert_one({"_id": "requestLog.days", "value": 200})
PORTAL_DB["tenants"].insert_many([
    {"_id": "t-acme", "name": "Acme", "prefixes": ["789835"], "logDays": 30},
    {"_id": "t-wide", "name": "Wide", "prefixes": ["952114"], "logDays": 900},
    {"_id": "t-none", "name": "None", "prefixes": ["9506"]}])
request_log.RETENTION.forget()
r, e = ask(G)
check("an organisation's events are kept its days (the prefix that starts the company part)", kept_days(e) == 30, e)
r, e = ask("/01/79521141123453")
check("…never longer than the installation's", kept_days(e) == 200, e)
r, e = ask("/01/09506000000000")
check("an organisation without its own days: the installation's (the portal's setting)", kept_days(e) == 200, e)
r, e = ask("/wp-login.php")
check("a request without a key: the installation's", kept_days(e) == 200, e)
PORTAL_DB["tenants"].insert_one({"_id": "t-longer", "name": "Longer", "prefixes": ["78983574"], "logDays": 7})
request_log.RETENTION.forget()
r, e = ask(G)
check("the longest prefix decides", kept_days(e) == 7, e)
PORTAL_DB["settings"].update_one({"_id": "requestLog.days"}, {"$set": {"value": 45}})
r, e = ask("/01/09506000000000")
check("a change is read after a minute at most, not at every request", kept_days(e) == 200, e)
request_log.RETENTION.forget()
r, e = ask("/01/09506000000000")
check("…then followed", kept_days(e) == 45, e)
PORTAL_DB["settings"].update_one({"_id": "requestLog.days"}, {"$set": {"value": "many"}})
request_log.RETENTION.forget()
r, e = ask("/01/09506000000000")
check("a setting that is not a number of days: RESOLVER_LOG_DAYS", kept_days(e) == 90, e)
PORTAL_DB["settings"].update_one({"_id": "requestLog.days"}, {"$set": {"value": 60}})
request_log.RETENTION.forget()
saved_database = request_log.RETENTION.database
request_log.RETENTION.database = lambda: (_ for _ in ()).throw(RuntimeError("portal database down"))
r, e = ask(G)
check("the portal's database unreadable: the last values kept, the same answer", kept_days(e) == 7
      and r.status_code == 307, e)
request_log.RETENTION.database = saved_database
request_log.RETENTION.forget()
os.environ["RESOLVER_LOG_DAYS"] = "0"
r, e = ask(G)
check("RESOLVER_LOG_DAYS=0 still switches the log off whatever the portal sets", e is None, e)
del os.environ["RESOLVER_LOG_DAYS"]
PORTAL_DB["settings"].delete_many({})
PORTAL_DB["tenants"].delete_many({})
request_log.RETENTION.forget()

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
    request_log.WRITER.put({"t": 1, "ai": "01", "dev": "mobile"})      # stored events (section 11)
request_log.WRITER.flush(10)
check("events are written in batches of at most 500", sum(counting.batches) == 1200 and max(counting.batches) <= 500
      and len(counting.batches) >= 3, counting.batches)
request_log.WRITER = saved

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
