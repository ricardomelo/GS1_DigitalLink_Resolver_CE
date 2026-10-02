"""
GS1's own resolver conformance test suite (https://ref.gs1.org/test-suites/resolver/, code at
https://github.com/gs1/GS1DL-resolver-testsuite), run unchanged in Chromium against this branch's resolver.

The suite's JavaScript runs in the browser as on GS1's page; the requests it sends to its PHP helper
(tester.php) are answered here by a Python version of that helper (same methods, headers and result
format), which calls the real web server code over HTTP, mounted under /api as the proxy does
(proxy_pass http://resolver-web/api$request_uri). MongoDB is stubbed; records are authored with the real
data entry code. The schemas and the list of ratified link types the suite downloads are served from local
copies, so the test needs no network once its dependencies are in place.

  git clone https://github.com/gs1/GS1DL-resolver-testsuite /tmp/gs1-testsuite   # tested at 32597c1 (2026-08-07)
  mkdir -p /tmp/ajv && cd /tmp/ajv && npm init -y && npm install ajv-dist@8      # the suite's window.ajv7
  export GS1_RESOLVER_TESTSUITE=/tmp/gs1-testsuite AJV_DIST=/tmp/ajv/node_modules/ajv-dist
  python dev-tests/resolver/test_gs1_suite.py      # GS1_SYNTAX_ENGINE as for test_resolver.py (optional)

Each scenario's result is the suite's own verdict for every test (pass, warn or fail) compared with the
verdict expected here; a warning is expected only where this file says why.
"""
import copy
import http.client
import importlib
import json
import os
import subprocess
import sys
import threading
import types
from urllib.parse import parse_qs, quote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))
SUITE = os.environ.get("GS1_RESOLVER_TESTSUITE")
AJV = os.environ.get("AJV_DIST")
if not (SUITE and AJV and os.path.isdir(SUITE) and os.path.isdir(AJV)):
    print("SKIP: set GS1_RESOLVER_TESTSUITE and AJV_DIST (see the docstring)")
    sys.exit(0)

FQDN = "id.example.org"
ORIGIN = "https://ref.gs1.org/test-suites/resolver/"

# ---------------------------------------------------------------- the resolver (as in test_resolver.py)
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


def read_document(anchor):
    key = anchor.replace("/", "_").lstrip("_")
    return {"response_status": 200, "data": copy.deepcopy(DB[key])} if key in DB else {"response_status": 404, "error": "nf"}


web_db.read_document = read_document
sys.modules["web_db"] = web_db
os.environ["FQDN"] = FQDN
os.environ.setdefault("MONGO_URI", "mongodb://unused")
import web_logic  # noqa: E402

ENGINE = os.environ.get("GS1_SYNTAX_ENGINE")


def engine_check(data):
    script = os.path.join(ENGINE, "_resolver_check.mjs")
    if not os.path.exists(script):
        with open(script, "w") as fh:
            fh.write('import {GS1encoder} from "gs1encoder"; const g = new GS1encoder(); await g.init();'
                     'const a = process.argv[2];'
                     'try { if (a.startsWith("https://")) g.dataStr = a; else { g.aiDataStr = a; g.getDLuri(null); } }'
                     'catch (e) { g.free(); process.exit(1); } g.free();')
    return subprocess.run(["node", script, data], cwd=ENGINE, capture_output=True).returncode == 0


web_logic._call_gs1_toolkit = engine_check if ENGINE else (lambda s: True)
from __init__ import create_app  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

app = create_app()


def behind_proxy(environ, start_response):
    """What the proxy does: the request URI, unchanged, under /api."""
    environ["PATH_INFO"] = "/api" + environ.get("PATH_INFO", "")
    for key in ("RAW_URI", "REQUEST_URI"):
        if environ.get(key):
            environ[key] = "/api" + environ[key]
    return app(environ, start_response)


server = make_server("127.0.0.1", 0, behind_proxy, threaded=True)
PORT = server.server_port
threading.Thread(target=server.serve_forever, daemon=True).start()


LOWER_CASE = False      # header names as HTTP/2 sends them (curl negotiates HTTP/2 when the server offers it)


def call(method, url, headers):
    """One request to the resolver for a URL on FQDN; returns (status, reason, [(name, value)], body)."""
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    conn.request(method, path, headers={"Host": FQDN, **headers})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, r.reason, r.getheaders(), body


# ---------------------------------------------------------------- tester.php, in Python
def tester(query):
    """tester.php of the suite: same commands, request methods and headers, same result objects. curl sends
    'Accept: */*' unless the command sets Accept, and no Accept-Language unless it sets one."""
    params = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
    test, url = params.get("test"), params.get("testVal")
    if not url or not url.startswith("https://"):
        return {"error": "No valid command received"}
    if test == "getHTTPversion":
        return {"test": test, "testVal": url, "result": "HTTP/1.1"}
    headers = {"Origin": ORIGIN, "Accept": "*/*"}
    if test == "getAllHeaders":
        method = "HEAD"
        if "mediaType" in params:
            headers["Accept"] = params["mediaType"]
        if "lang" in params:
            headers["Accept-Language"] = params["lang"]
    elif test == "getLinksetHeaders":
        method = "HEAD"
        headers["Accept"], headers["Accept-Language"] = "application/linkset+json", ""
    elif test == "getCorsHeaders":
        method = "OPTIONS"
        headers["Access-Control-Request-Method"] = "GET,HEAD,OPTIONS"
    elif test == "getLinkset":
        method = "GET"
        headers["Accept"] = "application/linkset+json"
    else:
        return {"error": "Invalid test command"}
    status, reason, response_headers, body = call(method, url, headers)
    # later headers win, as in parseHeadersToArray()
    named = {(name.lower() if LOWER_CASE else name): value for name, value in response_headers}
    named["0"] = f"HTTP/1.1 {status} {reason}"
    if test == "getLinkset":
        result = json.dumps({"uri": url, "httpCode": status, "httpMsg": reason, "headers": named,
                             "responseBody": quote(body.decode("utf-8"), safe="-_.~")})
        return {"test": test, "testVal": url, "result": result}
    return {"test": test, "testVal": url, "result": {"uri": url, "httpCode": status, "httpMsg": reason, **named}}


# ---------------------------------------------------------------- what the suite downloads besides the resolver
description = json.load(open(os.path.join(REPO, "web_server", "src", "public", "gs1resolver.json"), encoding="utf-8"))
# Stand-in for https://ref.gs1.org/voc/data/linktypes: the link types of the description file, plus the two
# that the GS1 Web Vocabulary defines for the default but a description file does not list as active
RATIFIED = {code.split(":", 1)[1]: {"title": v.get("title")} for code, v in description["activeLinkTypes"]["en"].items()}
RATIFIED.update({"defaultLink": {"title": "Default link"}, "defaultLinkMulti": {"title": "Default link (multiple)"}})
LOCAL = {
    "https://ref.gs1.org/standards/resolver/description-file-schema": open(os.path.join(HERE, "description-file-schema.json")).read(),
    "https://gs1.github.io/linkset/gs1-linkset-schema.json": open(os.path.join(HERE, "linkset-schema.json")).read(),
    "https://ref.gs1.org/voc/data/linktypes": json.dumps(RATIFIED),
}
PAGE = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>suite</title>
<script src="/x/ajv7.bundle.js"></script><script src="/x/GS1DigitalLinkToolkit.js"></script>
<script src="/x/GS1DigitalLinkResolverTestSuite.js"></script></head>
<body><img id="rotatingcircle" alt=""><div id="gs1ResolverTests"></div></body></html>"""
FILES = {"ajv7.bundle.js": os.path.join(AJV, "dist", "ajv7.bundle.js"),
         "GS1DigitalLinkToolkit.js": os.path.join(SUITE, "GS1DigitalLinkToolkit.js"),
         "GS1DigitalLinkResolverTestSuite.js": os.path.join(SUITE, "GS1DigitalLinkResolverTestSuite.js")}
CORS = {"Access-Control-Allow-Origin": "*"}


def route(r):
    url = r.request.url
    if url == ORIGIN:
        return r.fulfill(status=200, content_type="text/html", body=PAGE)
    if url.startswith("https://ref.gs1.org/x/"):
        return r.fulfill(status=200, content_type="application/javascript",
                         body=open(FILES[url.rsplit("/", 1)[1]], encoding="utf-8").read())
    if urlsplit(url).path.endswith("/tester.php"):
        return r.fulfill(status=200, headers=CORS, content_type="application/json",
                         body=json.dumps(tester(urlsplit(url).query)))
    if url in LOCAL:
        return r.fulfill(status=200, headers=CORS, content_type="application/json", body=LOCAL[url])
    if urlsplit(url).hostname == FQDN:                  # the browser's own requests (TLS check, description file)
        status, _, headers, body = call(r.request.method, url,
                                        {k: v for k, v in r.request.headers.items() if k.lower() != "host"})
        return r.fulfill(status=status, headers=dict(headers), body=body)
    return r.abort()


# ---------------------------------------------------------------- scenarios
def link(linktype, href, title, lang="pt", media="text/html"):
    return {"linktype": linktype, "href": href, "title": title, "type": media, "hreflang": [lang]}


A, B, GLN = "/01/07898357410015", "/01/07898357410022", "/414/7898357410008"
# A: what a record made in the portal looks like: one link per type, the default among them
author({"anchor": A, "itemDescription": "Suite A", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://example.com/a/pip", "Produto"),
    link("gs1:instructions", "https://example.com/a/instructions", "Instruções"),
    link("gs1:certificationInfo", "https://example.com/a/cert?x=1", "Certificados")]})
# A, batch LOT1: its own default and instructions, the certificate inherited from the GTIN
author({"anchor": A, "qualifiers": [{"10": "LOT1"}], "itemDescription": "Suite A lote", "defaultLinktype": "gs1:pip",
        "links": [link("gs1:pip", "https://example.com/a/lot1", "Lote LOT1"),
                  link("gs1:instructions", "https://example.com/a/lot1/instructions", "Instruções do lote")]})
# A, serial S1 with an informative batch (registration model of section 2.5.9)
author({"anchor": A, "qualifiers": [{"21": "S1"}], "informativeQualifiers": [{"10": "LOT1"}],
        "itemDescription": "Suite A série", "defaultLinktype": "gs1:pip",
        "links": [link("gs1:pip", "https://example.com/a/s1", "Unidade S1")]})
# B: the record proposed for the run on staging (language variants of the default, hence gs1:defaultLinkMulti,
# and of another type), plus two links the request cannot tell apart (300), which the data entry API accepts
# but the portal refuses (same type and language)
author({"anchor": B, "itemDescription": "Suite B", "defaultLinktype": "gs1:pip", "links": [
    link("gs1:pip", "https://example.com/b/pip-pt", "Produto"),
    link("gs1:pip", "https://example.com/b/pip-en", "Product", "en"),
    link("gs1:instructions", "https://example.com/b/instr-pt", "Instruções"),
    link("gs1:instructions", "https://example.com/b/instr-en", "Instructions", "en"),
    link("gs1:relatedVideo", "https://example.com/b/video1", "Vídeo 1"),
    link("gs1:relatedVideo", "https://example.com/b/video2", "Vídeo 2")]})
author({"anchor": B, "qualifiers": [{"10": "LOT1"}], "itemDescription": "Suite B lote", "defaultLinktype": "gs1:pip",
        "links": [link("gs1:pip", "https://example.com/b/lot1", "Lote LOT1"),
                  link("gs1:instructions", "https://example.com/b/lot1/instructions", "Instruções do lote")]})

# a GLN (link types the portal offers): the suite's walk-up check adds an extension (254)
author({"anchor": GLN, "itemDescription": "Suite GLN", "defaultLinktype": "gs1:support", "links": [
    link("gs1:support", "https://example.com/gln/support", "Atendimento"),
    link("gs1:socialMedia", "https://example.com/gln/social", "Redes sociais")]})

BASE = {"isURL", "validDL", "isHttps", "plausibleDL", "basicWalkUp", "tlsOK", "rdFile", "httpVersion", "corsCheck",
        "methodsCheck", "reportWith400", "noErrorWith200", "trailingSlash", "legacyLinkHeaders", "qsPassedOn",
        "ltLinksetNoRedirect", "ltAcceptHeader", "validLinkset", "linksetJsonldCheck", "declaredContentType",
        "defaultLinkExists", "singleDefaulLink", "defaultTarget", "linkTypesDefined", "specificLinkTypeNotFound"}
SCENARIOS = [
    # (name, URI, link-type tests expected besides BASE, {test id: expected verdict other than pass})
    ("GTIN", f"https://{FQDN}{A}", {"loForgs1pip", "loForgs1instructions", "loForgs1certificationInfo"}, {}),
    ("GTIN + batch", f"https://{FQDN}{A}/10/LOT1", {"loForgs1pip", "loForgs1instructions", "loForgs1certificationInfo"}, {}),
    ("GTIN + serial", f"https://{FQDN}{A}/21/S1", {"loForgs1pip", "loForgs1instructions", "loForgs1certificationInfo"}, {}),
    ("GTIN with language variants", f"https://{FQDN}{B}",
     {"loForgs1defaultLinkMulti0", "loForgs1defaultLinkMulti1", "loForgs1pip0", "loForgs1pip1",
      "loForgs1instructions0", "loForgs1instructions1", "loForgs1relatedVideo0"}, {}),
    # The batch's own links outrank the GTIN's. Known divergence (conformance review, erratum E12): the suite
    # treats the GTIN's gs1:defaultLinkMulti as a link type the batch inherits and expects the batch URI with
    # Accept-Language pt or en to go to the GTIN's language variants. This resolver answers with the batch's
    # own default: each identified entity has exactly one default link (Resolver 1.2.1, 2.5.8), the language
    # variants refine that default, and the batch defines its own (2.5.9). The standard does not say which.
    ("GTIN with language variants + batch", f"https://{FQDN}{B}/10/LOT1",
     {"loForgs1pip", "loForgs1instructions", "loForgs1relatedVideo0", "loForgs1defaultLinkMulti0",
      "loForgs1defaultLinkMulti1"}, {"loForgs1defaultLinkMulti0": "fail", "loForgs1defaultLinkMulti1": "fail"}),
    ("GLN", f"https://{FQDN}{GLN}", {"loForgs1support", "loForgs1socialMedia"}, {}),
    ("GTIN, HTTP/2 header names", f"https://{FQDN}{A}", {"loForgs1pip", "loForgs1instructions", "loForgs1certificationInfo"}, {}),
]

# Without the GS1 Barcode Syntax Engine the stub accepts any path, so the suite's invalid URI (the key
# followed by /foo) walks up to the key and is redirected instead of refused
if not ENGINE:
    for scenario in SCENARIOS:
        scenario[3]["reportWith400"] = "fail"

# ---------------------------------------------------------------- run
from playwright.sync_api import sync_playwright  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, uri, link_tests, expected in SCENARIOS:
        LOWER_CASE = "HTTP/2" in name
        page = browser.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        page.route("**/*", route)
        page.goto(ORIGIN)
        page.evaluate("dl => testDL(dl)", uri)
        page.wait_for_selector("#linkToResult", timeout=60000)
        page.wait_for_timeout(1500)                        # the description file and TLS checks are not awaited
        results = page.evaluate("resultsArray.map(r => ({id: r.id, status: r.status, msg: r.msg}))")
        page.close()
        seen = {r["id"]: r for r in results}
        check(f"{name}: every test of the suite ran", BASE | link_tests <= set(seen),
              sorted((BASE | link_tests) - set(seen)))
        check(f"{name}: no unexpected test", set(seen) <= BASE | link_tests, sorted(set(seen) - BASE - link_tests))
        for test_id in sorted(seen):
            r = seen[test_id]
            want = expected.get(test_id, "pass")
            check(f"{name}: {test_id} {want}", r["status"] == want, f"{r['status']}: {r['msg']}")
        if console:
            print("     browser console:", " | ".join(console)[:600])
    browser.close()
server.shutdown()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
