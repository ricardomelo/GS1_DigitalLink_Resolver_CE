"""
The portal's warnings on safety-critical link types (Documentation/adr/0022-answering-level.md, section 2.5), through
the portal's Flask test client and the in-memory data entry API: a batch or serial record lacking a safety-critical
type a less specific record holds (warning.walkUp, with the level that answers and whether the strict mode withholds
it), a product-level record holding them while the key has batch or serial records (warning.productLevel), a batch or
serial value equal to another of the key's but for case, spaces, - . / or O/0 and I/1 (warning.nearDuplicate); the
same list before saving (POST /portal/api/record/warnings, nothing written), with the saved record (the editor and
the tenant API's "warnings", documented in openapi.json), in the import's preview (per record, and counted), and the
count on the organisation's Resolution tab; a warning never refuses a save; the folding rules of safety.fold().

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_safety_warnings.py
"""
import base64
import json
import os
import sys
import tempfile
import threading

from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3431
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_safety_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
import tenants  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
store.col("settings").delete_one({"_id": "resolution.strict"})
acme = tenants.create("Acme Pharma", ["7891234"], "root")
import app as portal  # noqa: E402
import safety  # noqa: E402
import sheet  # noqa: E402

threading.Thread(target=make_server("127.0.0.1", DATA_ENTRY_PORT, mock_data_entry.app, threaded=True).serve_forever,
                 daemon=True).start()
failures = []
ORIGIN = {"Origin": "https://id.example.org"}


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {str(detail)[:600]}"))
    if not condition:
        failures.append(name)


def gtin(body13: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body13)))
    return body13 + str((10 - total % 10) % 10)


def client(username, password):
    c = portal.app.test_client()
    c.post("/portal/api/login", json={"username": username, "password": password}, headers=ORIGIN)
    return c


def link(kind, url=None):
    return {"linkType": kind, "url": url or f"https://farma.example/{kind.split(':')[1]}", "title": "", "hreflang": ["pt"]}


def record(value, qualifiers=None, *types, description="Amoxicillin"):
    return {"key": "01", "value": value, "qualifiers": qualifiers or {}, "description": description,
            "defaultLinkType": "gs1:pip", "links": [link("gs1:pip"), *(link(t) for t in types)]}


def codes(warnings):
    return [w["code"] for w in warnings]


def find(warnings, code):
    return next((w["params"] for w in warnings if w["code"] == code), None)


users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("rui", "rui-password-long", "reader", tenant=acme["id"], must_change=False)
ana, edu, rui = (client(u, f"{u}-password-long") for u in ("ana", "edu", "rui"))
G = gtin("0789123400017")
G2 = gtin("0789123400024")


def save(body, who=None):
    return (who or edu).post("/portal/api/record", json=body, headers=ORIGIN)


def preview_warnings(body, who=None):
    return (who or edu).post("/portal/api/record/warnings", json=body, headers=ORIGIN)


# --------------------------------------------------------------------------- folding
check("fold: case, spaces, - . / removed, O and I read as 0 and 1",
      safety.fold("lot a-1.0/i") == safety.fold("L0TA 1.01") == "L0TA101", safety.fold("lot a-1.0/i"))
check("…different values stay different", safety.fold("LOTA") != safety.fold("LOTB"))
check("the safety-critical types are the strict mode's five", safety.SAFETY_TYPES == tuple(
      "gs1:" + c for c in ("recallStatus", "safetyInfo", "epil", "smpc", "eifu")))

# --------------------------------------------------------------------------- the product holds them; a batch does not
r = save(record(G, None, "gs1:recallStatus", "gs1:epil", "gs1:safetyInfo"))
check("the product with three safety-critical types, no batch yet: saved, no warning",
      r.status_code == 201 and r.get_json().get("warnings") == [], r.get_json())
r = save(record(G, {"10": "LOTA"}, "gs1:recallStatus"))
w = r.get_json().get("warnings")
check("a batch with recallStatus only: saved (201) all the same", r.status_code == 201, r.get_json())
p = find(w, "warning.walkUp")
check("…warning.walkUp: lacks the leaflet and safety information, answered by the key's own record",
      codes(w) == ["warning.walkUp"] and p["types"] == ["gs1:safetyInfo", "gs1:epil"] and p["level"] == []
      and p["strict"] is False, w)
r = save(record(G, None, "gs1:recallStatus", "gs1:epil", "gs1:safetyInfo"))
p = find(r.get_json().get("warnings"), "warning.productLevel")
check("the product saved again: warning.productLevel with its three types and the batch",
      p and p["types"] == ["gs1:recallStatus", "gs1:safetyInfo", "gs1:epil"] and p["count"] == 1
      and p["values"] == [[["10", "LOTA"]]] and p["strict"] is False, r.get_json())
r = save(record(G, None))
check("…a product without safety-critical types: no warning even with batches", r.get_json().get("warnings") == [],
      r.get_json())
r = save(record(G, None, "gs1:recallStatus", "gs1:epil", "gs1:safetyInfo"))

# --------------------------------------------------------------------------- before saving
before = json.dumps(mock_data_entry.DB, sort_keys=True, default=str)
r = preview_warnings(record(G, {"10": "LOTB"}))
w = r.get_json().get("warnings")
check("POST record/warnings for a new batch without safety links: the three types, from the key's own record",
      r.status_code == 200 and find(w, "warning.walkUp")["types"] == ["gs1:recallStatus", "gs1:safetyInfo", "gs1:epil"], w)
check("…nothing written", json.dumps(mock_data_entry.DB, sort_keys=True, default=str) == before)
w = preview_warnings(record(G, {"10": "LOTB"}, "gs1:recallStatus", "gs1:epil", "gs1:safetyInfo")).get_json()["warnings"]
check("…with its own three links: no warning", w == [], w)
w = preview_warnings(record(G, {"10": "lota"})).get_json()["warnings"]
p = find(w, "warning.nearDuplicate")
check("a batch typed \"lota\" beside LOTA: warning.nearDuplicate naming both", p == {"ai": "10", "value": "lota",
                                                                                   "existing": "LOTA"}, w)
for typed in ("L0TA", "LOT-A", "LOT.A", "lot-a"):     # spaces and slashes: refused by the editor before
    w = preview_warnings(record(G, {"10": typed})).get_json()["warnings"]
    check(f"…\"{typed}\" too", (find(w, "warning.nearDuplicate") or {}).get("existing") == "LOTA", w)
w = preview_warnings(record(G, {"10": "LOTA"})).get_json()["warnings"]
check("…the same value (the record itself): no near duplicate", "warning.nearDuplicate" not in codes(w), w)
w = preview_warnings(record(G, {"10": "LOTX"})).get_json()["warnings"]
check("…a different value: none", "warning.nearDuplicate" not in codes(w), w)
w = preview_warnings(record(G2, {"10": "lota"})).get_json()["warnings"]
check("…a close value of another key: none (and that key has no broader record: no walk-up)", w == [], w)
w = preview_warnings({"key": "01", "value": "123", "qualifiers": {"10": "x"}}).get_json()
check("an invalid key: no warnings, not an error", w == {"warnings": []}, w)
OPER = gtin("0950600013435")
r = save(record(OPER, None, "gs1:recallStatus"), client("root", "root-password-long"))
w = preview_warnings(record(OPER, {"10": "LOTA"})).get_json()
check("a key outside the user's organisation, with a recall on its product: no warnings (nothing is told about it)",
      r.status_code == 201 and w == {"warnings": []}, (r.status_code, w))
r = preview_warnings(record(G, {"10": "LOTB"}), rui)
check("a reader may not ask (403)", r.status_code == 403, r.status_code)

# --------------------------------------------------------------------------- a serial with its batch
save(record(G, {"10": "LOTB"}, "gs1:epil"))
w = preview_warnings(record(G, {"21": "S1", "10": "LOTB"})).get_json()["warnings"]
levels = [(x["params"]["level"], x["params"]["types"]) for x in w if x["code"] == "warning.walkUp"]
check("a serial with batch LOTB: the leaflet from the batch's record, recall and safety from the key's own",
      levels == [([["10", "LOTB"]], ["gs1:epil"]), ([], ["gs1:recallStatus", "gs1:safetyInfo"])], w)

# --------------------------------------------------------------------------- the strict mode
ana.put("/portal/api/resolution/strict", json={"tenant": acme["id"], "enabled": True}, headers=ORIGIN)
w = preview_warnings(record(G, {"21": "S1", "10": "LOTB"})).get_json()["warnings"]
strict = [(x["params"]["level"], x["params"]["strict"]) for x in w if x["code"] == "warning.walkUp"]
check("strict mode on: the key's own record's links withheld, the batch's not (it names the request's batch)",
      strict == [([["10", "LOTB"]], False), ([], True)], w)
w = preview_warnings(record(G, {"22": "V1"})).get_json()["warnings"]
check("…a variant record (no batch or serial): not withheld", [x["params"]["strict"] for x in w] == [False], w)
r = save(record(G, None, "gs1:recallStatus", "gs1:epil", "gs1:safetyInfo"))
check("…the product's warning says the strict mode is on",
      (find(r.get_json()["warnings"], "warning.productLevel") or {}).get("strict") is True, r.get_json())

# --------------------------------------------------------------------------- the tenant API
key = ana.post("/portal/api/keys", json={"name": "ERP", "scopes": ["records:write", "records:read"], "days": 30},
               headers=ORIGIN).get_json()["key"]
r = portal.app.test_client().put(f"/portal/api/v1/records/01/{G}?qualifiers=/10/lotA", headers={
    "Authorization": f"Bearer {key}"}, json={"description": "Amoxicillin", "links": [link("gs1:pip")]})
w = (r.get_json() or {}).get("warnings")
check("the tenant API: 201 with \"warnings\" (walk-up withheld, near duplicate of LOTA)",
      r.status_code == 201 and codes(w) == ["warning.walkUp", "warning.nearDuplicate"]
      and find(w, "warning.walkUp")["strict"] is True, (r.status_code, r.get_json()))
spec = json.load(open(os.path.join(PORTAL, "openapi.json"), encoding="utf-8"))
saved = spec["components"]["schemas"].get("Saved", {})
check("…documented in openapi.json (Saved.warnings, Warning)", "warnings" in saved.get("properties", {})
      and "Warning" in spec["components"]["schemas"], saved)

# --------------------------------------------------------------------------- the organisation's Resolution tab
d = ana.get("/portal/api/organisation").get_json()["resolution"]["lacking"]
values = sorted(x["qualifiers"][0][1] for x in d["records"])
check("the Resolution tab counts the batch records lacking a type of a broader record (LOTA, LOTB, lotA)",
      d["count"] == 3 and values == ["LOTA", "LOTB", "lotA"], d)
check("…with the types each lacks", next(x for x in d["records"] if x["qualifiers"] == [["10", "LOTA"]])["types"]
      == ["gs1:safetyInfo", "gs1:epil"], d)
check("…the operator's scope counts none of the organisation's",
      client("root", "root-password-long").get("/portal/api/organisation").get_json()["resolution"]["lacking"]["count"] == 0)

# --------------------------------------------------------------------------- the import's preview
rows = [["01", G, "/10/LOTC", "Amoxicillin LOTC", "gs1:pip", "https://farma.example/c", "pt", "", "yes"],
        ["01", G, "/10/L0TA", "Amoxicillin L0TA", "gs1:pip", "https://farma.example/o", "pt", "", "yes"],
        ["01", G, "/10/LOTD", "Amoxicillin LOTD", "gs1:pip", "https://farma.example/d", "pt", "", "yes"],
        ["01", G, "/10/LOTD", "Amoxicillin LOTD", "gs1:recallStatus", "https://farma.example/r", "pt", "", "no"],
        ["01", G, "/10/LOTD", "Amoxicillin LOTD", "gs1:epil", "https://farma.example/e", "pt", "", "no"],
        ["01", G, "/10/LOTD", "Amoxicillin LOTD", "gs1:safetyInfo", "https://farma.example/s", "pt", "", "no"]]
r = edu.post("/portal/api/import/preview", json={"filename": "links.csv", "labels": {},
             "content": base64.b64encode(sheet.write_csv(rows, {})).decode()}, headers=ORIGIN).get_json()
by_value = {item["qualifiers"][0][1]: item for item in r.get("records", [])}
check("the import's preview: LOTC (no safety links) warned of the walk-up, withheld",
      (find(by_value.get("LOTC", {}).get("warnings", []), "warning.walkUp") or {}).get("strict") is True, r)
check("…L0TA warned of the near duplicate LOTA", (find(by_value.get("L0TA", {}).get("warnings", []),
                                                       "warning.nearDuplicate") or {}).get("existing") == "LOTA", r)
check("…LOTD, with its own three links: no warning", "warnings" not in by_value.get("LOTD", {"warnings": 1}), r)
check("…counted (2) and still to be created (warnings do not refuse)", r.get("warningCount") == 2
      and r.get("counts", {}).get("create") == 3 and not r.get("errors"), r.get("counts"))

# --------------------------------------------------------------------------- languages (ADR 0028)
def lang_link(kind, *tags, url=None):
    return {"linkType": kind, "url": url or f"https://farma.example/{kind.split(':')[1]}-{'-'.join(tags) or 'x'}",
            "title": "", "hreflang": list(tags)}


def lang_record(*links):
    return {"key": "01", "value": G2, "qualifiers": {}, "description": "Ibuprofen", "defaultLinkType": "gs1:pip",
            "links": list(links)}


w = preview_warnings(lang_record(lang_link("gs1:pip", "pt"), lang_link("gs1:pip", "en"),
                                 lang_link("gs1:epil", "en"))).get_json()["warnings"]
check("a leaflet in English only, the product page in Portuguese and English: warning.languageGap, missing pt",
      codes(w) == ["warning.languageGap"] and find(w, "warning.languageGap")["gaps"] == [
          {"type": "gs1:epil", "missing": ["pt"]}], w)
w = preview_warnings(lang_record(lang_link("gs1:pip", "pt-BR"), lang_link("gs1:epil", "pt"),
                                 lang_link("gs1:recallStatus", "pt-br"))).get_json()["warnings"]
check("…compared as the resolver does: pt serves pt-BR, case ignored: no warning", w == [], w)
w = preview_warnings(lang_record(lang_link("gs1:pip", "pt-BR"), lang_link("gs1:epil", "pt-PT"))).get_json()["warnings"]
check("…pt-PT does not serve a request for pt-BR (the resolver would fall back): missing pt-BR",
      (find(w, "warning.languageGap") or {}).get("gaps") == [{"type": "gs1:epil", "missing": ["pt-BR"]}], w)
check("serves() is the resolver's lookup: pt-BR by pt, pt by pt-BR, not pt-BR by pt-PT nor en by en-x… for fr",
      safety.serves(["pt"], "pt-BR") and safety.serves(["pt-BR"], "pt") and not safety.serves(["pt-PT"], "pt-BR")
      and not safety.serves(["en"], "fr"))
w = preview_warnings(lang_record(lang_link("gs1:pip", "pt"), lang_link("gs1:epil"),
                                 lang_link("gs1:smpc", "und"), lang_link("gs1:smpc", "en"))).get_json()["warnings"]
p = find(w, "warning.noLanguage")
check("a leaflet without a language, a summary marked 'und': warning.noLanguage for both, in the five types' order",
      p and p["types"] == ["gs1:epil", "gs1:smpc"], w)
check("…a type with a link that declares no language is not also reported as missing a language",
      find(w, "warning.languageGap") is None, w)
w = preview_warnings(lang_record(lang_link("gs1:pip"), lang_link("gs1:certificationInfo", "fr"),
                                 lang_link("gs1:epil", "pt"))).get_json()["warnings"]
check("…other link types without a language, or in other languages, warn of nothing about themselves; the leaflet "
      "lacks French", codes(w) == ["warning.languageGap"]
      and find(w, "warning.languageGap")["gaps"] == [{"type": "gs1:epil", "missing": ["fr"]}], w)
check("language_warnings() reads the stored form too (linktype, hreflang)",
      safety.language_warnings([{"linktype": "gs1:eifu", "href": "x"}]) == [
          {"code": "warning.noLanguage", "params": {"types": ["gs1:eifu"]}}])
r = portal.app.test_client().put(f"/portal/api/v1/records/01/{G2}", headers={"Authorization": f"Bearer {key}"},
                                 json={"description": "Ibuprofen", "links": [
                                     {"linkType": "gs1:pip", "url": "https://farma.example/i", "hreflang": ["pt"]},
                                     {"linkType": "gs1:epil", "url": "https://farma.example/l", "hreflang": ["und"]}]})
check("the tenant API: a leaflet marked 'und' (undetermined) saved with warning.noLanguage",
      r.status_code in (200, 201) and "warning.noLanguage" in codes((r.get_json() or {}).get("warnings") or []),
      (r.status_code, r.get_json()))
check("…both codes in openapi.json", {"warning.noLanguage", "warning.languageGap"} <= set(
      spec["components"]["schemas"]["Warning"]["properties"]["code"]["enum"]))
rows = [["01", G2, "/10/LANG1", "Ibuprofen LANG1", "gs1:pip", "https://farma.example/p1", "pt", "", "yes"],
        ["01", G2, "/10/LANG1", "Ibuprofen LANG1", "gs1:epil", "https://farma.example/e1", "und", "", "no"]]
r = edu.post("/portal/api/import/preview", json={"filename": "links.csv", "labels": {},
             "content": base64.b64encode(sheet.write_csv(rows, {})).decode()}, headers=ORIGIN).get_json()
item = next((i for i in r.get("records", []) if i["qualifiers"] == [["10", "LANG1"]]), {})
check("the import's preview: a leaflet row in 'und' warned (warning.noLanguage)",
      "warning.noLanguage" in codes(item.get("warnings", [])), r)
script = open(os.path.join(PORTAL, "static", "app.js"), encoding="utf-8").read()
check("the editor draws both and the import's preview has a line for each",
      script.count('w.code === "warning.noLanguage"') == 2 and script.count('w.code === "warning.languageGap"') == 2)

# --------------------------------------------------------------------------- the texts
catalogue = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
for name in ("warning.walkUp.title", "warning.walkUp.text", "warning.walkUp.strict", "warning.productLevel.text",
             "warning.nearDuplicate.text", "import.warningsMany", "resolution.lackingMany", "warning.noLanguage.title",
             "warning.noLanguage.text", "warning.noLanguage.short", "warning.languageGap.title",
             "warning.languageGap.text", "warning.languageGap.item"):
    check(f"the text {name} in Portuguese and English", catalogue.count(f'"{name}":') == 2)
page = open(os.path.join(PORTAL, "static", "index.html"), encoding="utf-8").read()
check("the editor's boxes: under the qualifiers and under the targets, read aloud when they change",
      'id="dup-warnings"' in page and 'id="safety-warnings"' in page and page.count('class="safety-warn"') == 2
      and 'id="import-safety"' in page)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
