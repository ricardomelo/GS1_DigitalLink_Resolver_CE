"""
Every link type and every language of the targets (backlog item 9.4): portal/gs1_link_types.json is exactly what the
GS1 Web Vocabulary gives (tools/gen_link_types.py: its stable link types, without the resolver's own gs1:defaultLink
and gs1:defaultLinkMulti, without the deprecated ones); each is in a group of the editor's menu, named in both
languages with a Portuguese default title; the groups' order by key type; the titles the portal gave before still
read as its own; the configuration the page reads; a record with a new link type and its default title in its
language; every ISO 639-1 language and regional tags offered, any well-formed tag accepted, a malformed one refused;
a spreadsheet with a new link type; the texts in both languages.

  pip install -r portal/requirements.txt mongomock
  GS1_WEB_VOCABULARY=<gs1/WebVoc checkout>/v1.16/gs1Voc.jsonld python dev-tests/portal/test_link_types.py
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3404
sys.path[:0] = [HERE, PORTAL]
os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_linktypes_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"

import mock_data_entry  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import gs1  # noqa: E402
import sheet  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}
VOCABULARY = os.environ.get("GS1_WEB_VOCABULARY", "")


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


# ================================================================== the file and the vocabulary
if VOCABULARY and os.path.exists(VOCABULARY):
    run = subprocess.run([sys.executable, os.path.join(PORTAL, "tools", "gen_link_types.py"), VOCABULARY, "--check"],
                         capture_output=True, text=True)
    check("gs1_link_types.json is exactly what the GS1 Web Vocabulary gives (tools/gen_link_types.py --check)",
          run.returncode == 0, run.stdout + run.stderr)
    sys.path.insert(0, os.path.join(PORTAL, "tools"))
    import gen_link_types  # noqa: E402
    with open(VOCABULARY, encoding="utf-8-sig") as fh:
        vocabulary = json.load(fh)
    every = [n for n in vocabulary["@graph"] if "gs1:linkType" in gen_link_types._ids(n.get("rdfs:subPropertyOf"))]
    deprecated = {n["@id"] for n in every if n.get("sw:term_status") != "stable"}
    check("…every stable link type of the vocabulary, none deprecated, not the resolver's own default ones",
          {t["code"] for t in gs1.VOCABULARY_LINK_TYPES["linkTypes"]}
          == {n["@id"] for n in every} - deprecated - {"gs1:defaultLink", "gs1:defaultLinkMulti"}
          and "gs1:productSustainabilityInfo" in deprecated, deprecated)
else:
    print("SKIP the link types against the GS1 Web Vocabulary (set GS1_WEB_VOCABULARY)")
data = gs1.VOCABULARY_LINK_TYPES
check(f"version {data['version']} of the vocabulary: {len(data['linkTypes'])} link types, each with a title and a "
      f"description", data["version"] and len(data["linkTypes"]) >= 57
      and all(t["title"] and t["description"] for t in data["linkTypes"]), data["version"])
codes = [code for code, _, _ in gs1.LINK_TYPES]
check("every one offered, once", sorted(codes) == sorted(t["code"] for t in data["linkTypes"]) and len(set(codes)) == len(codes))
check("…each in a group of the menu (a new one fails here until it has one)",
      all(group in gs1.LINK_TYPE_GROUPS for _, group, _ in gs1.LINK_TYPES)
      and sorted(c for g in gs1.LINK_TYPE_GROUPS.values() for c in g) == sorted(codes),
      [c for c, g, _ in gs1.LINK_TYPES if g not in gs1.LINK_TYPE_GROUPS])
check("…every group in every key type's order, once", all(sorted(order) == sorted(gs1.LINK_TYPE_GROUPS)
                                                            for order in gs1.LINK_GROUP_ORDER.values()))
check("…the order by key type: products the most used first, places for a GLN, logistics for an SSCC, services for a GSRN",
      gs1.link_group_order("01")[0] == "common" and gs1.link_group_order("414")[0] == "places"
      and gs1.link_group_order("00")[0] == "b2b" and gs1.link_group_order("8018")[0] == "organisation"
      and gs1.link_group_order("7240") == gs1.LINK_GROUP_ORDER["*"])
check("…a Portuguese default title for each", set(gs1.LINK_TYPE_TITLES_PT) == set(codes),
      set(codes) - set(gs1.LINK_TYPE_TITLES_PT))
check("the titles the portal gave before still read as its own, and the vocabulary's too",
      gs1.is_default_title("gs1:pip", "Product information page") and gs1.is_default_title("gs1:pip", "Product Information Page")
      and gs1.is_default_title("gs1:hasRetailers", "Where to buy") and gs1.is_default_title("gs1:dpp", "Digital Product Passport")
      and gs1.LINK_TYPE_DEFAULT_TITLES["gs1:registerProduct"] == "Register product")

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
named = [c for c in codes if len(re.findall(rf'"{re.escape(c)}": \["[^"]+", "[^"]+"\]', i18n)) != 2]
check("every link type named and explained in both languages", not named, named)
groups = [g for g in gs1.LINK_TYPE_GROUPS if i18n.count(f'"group.{g}"') != 2]
check("…every group named in both languages", not groups, groups)
check("…and the refusal of a language typed", i18n.count('"link.languageInvalid"') == 2)

# ================================================================== the configuration and the editor
root = portal.app.test_client()
root.post("/portal/api/login", json={"username": "root", "password": "root-password-long"}, headers=ORIGIN)
cfg = root.get("/portal/api/config").get_json()
check("the page gets every link type with its group", len(cfg["linkTypes"]) == len(codes)
      and {"code": "gs1:dpp", "group": "common"} in cfg["linkTypes"], len(cfg["linkTypes"]))
check("…the groups' order for every key type", set(cfg["linkTypeOrder"]) == {"*", *gs1.PRIMARY_KEYS}
      and cfg["linkTypeOrder"]["414"][0] == "places", cfg["linkTypeOrder"].get("414"))
check("…every ISO 639-1 language and the common regional tags", set(gs1.ISO_639_1) <= set(cfg["languages"])
      and len(gs1.ISO_639_1) == 183 and {"pt-BR", "en-GB", "zh-Hans", "es-419"} <= set(cfg["languages"])
      and cfg["languages"][:2] == ["pt", "en"], len(cfg["languages"]))
check("…each a well-formed tag", all(gs1.normalise_language(tag) for tag in cfg["languages"]))

GTIN = "09506000134352"
r = root.post("/portal/api/record", json={"key": "01", "value": GTIN, "description": "Lamp", "links": [
    {"linkType": "gs1:dpp", "url": "https://brand.example/dpp", "hreflang": ["en"]},
    {"linkType": "gs1:eifu", "url": "https://brand.example/eifu-pt", "hreflang": ["pt-BR"]},
    {"linkType": "gs1:relatedImage", "url": "https://brand.example/img", "hreflang": ["yo"]}]}, headers=ORIGIN)
links = {l["linktype"]: l for l in mock_data_entry.DB.get(f"01_{GTIN}", {}).get("entries", [{}])[0].get("links", [])}
check("a record with link types new to the portal saved", r.status_code == 201 and set(links) == {"gs1:dpp", "gs1:eifu",
                                                                                                  "gs1:relatedImage"}, r.get_json())
check("…their default titles in the link's language (English, Portuguese for pt-BR)",
      links["gs1:dpp"]["title"] == "Digital Product Passport" and links["gs1:eifu"]["title"] == "Instruções de uso eletrônicas (eIFU)",
      {k: v["title"] for k, v in links.items()})
check("…any well-formed language, not only those of the old menu", links["gs1:relatedImage"]["hreflang"] == ["yo"]
      and links["gs1:eifu"]["hreflang"] == ["pt-BR"])
opened = root.get(f"/portal/api/record?key=01&value={GTIN}").get_json()
check("…read back with the titles empty (the portal's own)", all(l["title"] == "" for l in opened["links"]), opened["links"])
r = root.post("/portal/api/record", json={"key": "01", "value": GTIN, "description": "Lamp", "links": [
    {"linkType": "gs1:dpp", "url": "https://brand.example/dpp", "hreflang": ["portuguese"]}]}, headers=ORIGIN)
check("a malformed language refused", r.status_code == 422 and r.get_json()["code"] == "link.languageRequired", r.get_json())
r = root.post("/portal/api/record", json={"key": "01", "value": GTIN, "description": "Lamp", "links": [
    {"linkType": "gs1:productSustainabilityInfo", "url": "https://brand.example/s", "hreflang": ["en"]}]}, headers=ORIGIN)
check("a deprecated link type refused", r.status_code == 422 and r.get_json()["code"] == "link.typeRequired", r.get_json())

rows = [["01", "09506000134369", "", "Desk", "gs1:locationInfo", "https://brand.example/where", "fr-CA", "", "yes"]]
content = sheet.write_csv(rows, {})
result = root.post("/portal/api/import/preview", json={"filename": "x.csv", "content": base64.b64encode(content).decode(),
                                                       "labels": {}}, headers=ORIGIN).get_json()
check("a spreadsheet with a new link type and a regional language", result["counts"]["create"] == 1
      and not result["errors"], result)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
