"""
The portal's stand-in for the data entry API (dev-tests/portal/mock_data_entry.py) against the real one: the same
calls, in the order the portal makes them, must give the same records back. Both staging bugs of 15 October hid
behind stand-ins that did more than the real component (Documentation/history.md, session 14); this program keeps
the data entry stand-in honest. It covers what the portal relies on: POST /new (a new key, a new record of a key, a
record that exists, a list of a key's records),
PUT (links merged by type, language and context; the shared default link type;
informative qualifiers; 404 for a record the key does not have), DELETE of some links (404 likewise), GET and GET /summary with links — with and without links of type
gs1:defaultLink (Documentation/adr/0011-item-page.md, amendment of 17 October 2026).

No Docker, no MongoDB: the real data entry application with its database layer replaced by a dictionary, as in
test_data_entry_api.py; the stand-in through its own Flask test client.

  pip install -r data_entry_server/src/requirements.txt
  python dev-tests/resolver/test_mock_parity.py
"""
import copy
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))
TOKEN = "tok"
os.environ.update(SESSION_TOKEN=TOKEN, MONGO_URI="mongodb://unused")

fake_mongo = types.ModuleType("mongo_db_init")
fake_mongo.mongo = None
fake_mongo.init_mongo = lambda app: None
sys.modules["mongo_db_init"] = fake_mongo

STORE = {}
db = types.ModuleType("data_entry_db")
db.read_document = lambda document_id: ({"response_status": 200, "data": copy.deepcopy(STORE[document_id])}
                                        if document_id in STORE else {"response_status": 404, "error": "not found"})
db.create_document = lambda doc: (STORE.__setitem__(doc["_id"], copy.deepcopy(doc)), {"response_status": 201})[1]
db.update_document = lambda doc: (STORE.__setitem__(doc["_id"], copy.deepcopy(doc)), {"response_status": 200})[1]
db.read_all_documents = lambda: {"response_status": 200, "data": copy.deepcopy(list(STORE.values()))}
db.read_index = lambda: {"response_status": 200, "data": list(STORE)}
db.delete_document = lambda document_id: (STORE.pop(document_id, None), {"response_status": 200})[1]
sys.modules["data_entry_db"] = db

sys.path.insert(0, os.path.join(REPO, "data_entry_server", "src"))
from __init__ import create_app  # noqa: E402  (the data entry package's own factory)

sys.path.insert(0, os.path.join(REPO, "dev-tests", "portal"))
import mock_data_entry  # noqa: E402

REAL = create_app().test_client()
MOCK = mock_data_entry.app.test_client()
AUTH = {"Authorization": f"Bearer {TOKEN}"}
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def normal_link(link: dict) -> tuple:
    return (link.get("linktype"), link.get("href"), link.get("title"), tuple(link.get("hreflang") or []),
            tuple(link.get("context") or []))


def normal(body) -> list:
    """A GET answer as a comparable value: entries by qualifiers, links as a sorted list (order is not part of the
    contract the portal relies on: it sorts the default first itself)."""
    out = []
    for entry in (body or {}).get("data") or []:
        out.append({"anchor": entry.get("anchor"), "qualifiers": entry.get("qualifiers") or [],
                    "informative": entry.get("informativeQualifiers") or [],
                    "description": entry.get("itemDescription"), "default": entry.get("defaultLinktype"),
                    "links": sorted(normal_link(l) for l in entry.get("links") or [])})
    return sorted(out, key=lambda e: json.dumps(e["qualifiers"]))


def both(method: str, path: str, payload=None):
    """The same call on both: (real answer, stand-in answer)."""
    kwargs = {"headers": AUTH}
    if payload is not None:
        kwargs["json"] = payload
    return getattr(REAL, method)("/api" + path, **kwargs), getattr(MOCK, method)("/api" + path, **kwargs)


def same(name: str, path: str = "/01/09506000134352"):
    real, mock = both("get", path)
    check(f"{name}: GET {path} gives the same records", (real.status_code, normal(real.get_json()))
          == (mock.status_code, normal(mock.get_json())),
          f"real {real.status_code} {normal(real.get_json())}\n      stand-in {mock.status_code} {normal(mock.get_json())}")


def succeeded(name: str, answers) -> None:
    real, mock = answers
    check(f"{name}: both accept", real.status_code in (200, 201) and mock.status_code in (200, 201),
          f"real {real.status_code} {real.get_data(as_text=True)[:200]} / stand-in {mock.status_code}")


PAGE = "https://id.example.com/01/09506000134352?linkType=linkset&view=page"


def link(linktype, href, lang="en", title="T", **extra):
    return {"linktype": linktype, "href": href, "title": title, "type": "text/html", "hreflang": [lang], **extra}


def record(links, default, qualifiers=None, **extra):
    doc = {"anchor": "/01/09506000134352", "itemDescription": "Item", "defaultLinktype": default, "links": links}
    if qualifiers:
        doc["qualifiers"] = qualifiers
    doc.update(extra)
    return doc


# ---------------------------------------------------------------- a key without the item's page
succeeded("new key", both("post", "/new", record([link("gs1:pip", "https://a.example/p")], "gs1:pip")))
same("new key")
# POST /new on a record that exists merges its links as PUT does (official pull request #128); the portal does it
# when two people create the same record at once, and when it restores a key's records after a failed rewrite
succeeded("the same record again by POST", both("post", "/new", record([link("gs1:pip", "https://a.example/p")], "gs1:pip")))
same("the same record again")
succeeded("POST on a record that exists", both("post", "/new", record(
    [link("gs1:pip", "https://a.example/p1"), link("gs1:pip", "https://a.example/pt", lang="pt")], "gs1:pip")))
same("POST on a record that exists")
succeeded("a second link added by PUT", both("put", "/01/09506000134352", record([link("gs1:faqs", "https://a.example/f")], "gs1:pip")))
same("added link")
succeeded("a batch record", both("post", "/new", record([link("gs1:pip", "https://a.example/b")], "gs1:pip",
                                                         [{"10": "B1"}])))
same("batch record")
succeeded("PUT merges a changed address", both("put", "/01/09506000134352",
                                                record([link("gs1:pip", "https://a.example/p2")], "gs1:pip")))
same("merged address")
succeeded("PUT on the batch adds a language", both("put", "/01/09506000134352",
                                                    record([link("gs1:pip", "https://a.example/b-pt", "pt")], "gs1:pip",
                                                           [{"10": "B1"}])))
same("added language")
succeeded("DELETE of one link", both("delete", "/01/09506000134352",
                                     {"links": [{"linktype": "gs1:faqs", "hreflang": ["en"], "context": []}]}))
same("deleted link")

# ---------------------------------------------------------------- the item's page and explicit default links
# The key switches to gs1:defaultLink: the batch first gets its own default link (a copy of its target), then the
# product record gets its page, as the portal does (portal/app.py, store_record)
succeeded("the batch switched to an explicit default link", both("put", "/01/09506000134352", record(
    [link("gs1:pip", "https://a.example/b"), link("gs1:defaultLink", "https://a.example/b")], "gs1:defaultLink",
    [{"10": "B1"}])))
same("explicit default link")
succeeded("the product's page as its default link", both("put", "/01/09506000134352", record(
    [link("gs1:pip", "https://a.example/p2"), link("gs1:defaultLink", PAGE, "und", "Item page")], "gs1:defaultLink")))
same("page as default link")
real, _ = both("get", "/01/09506000134352")
links = [l for e in real.get_json().get("data") or [] if not e.get("qualifiers") for l in e.get("links") or []]
check("the real API returns a link of type gs1:defaultLink (bug B1: it dropped it)",
      any(l["linktype"] == "gs1:defaultLink" and l["href"] == PAGE for l in links), links)
succeeded("PUT of the page again changes nothing else", both("put", "/01/09506000134352", record(
    [link("gs1:pip", "https://a.example/p2"), link("gs1:defaultLink", PAGE, "und", "Item page")], "gs1:defaultLink")))
same("page saved twice")
succeeded("a serial number with its page, by POST", both("post", "/new", record(
    [link("gs1:pip", "https://a.example/s"), link("gs1:defaultLink", PAGE.replace("?", "/21/S1?"), "und")],
    "gs1:defaultLink", [{"21": "S1"}], informativeQualifiers=[{"10": "B1"}])))
same("serial with page")
succeeded("DELETE of the batch's other language keeps its default link", both("delete", "/01/09506000134352", {
    "qualifiers": [{"10": "B1"}], "links": [{"linktype": "gs1:pip", "hreflang": ["pt"], "context": []}]}))
same("batch after delete")
succeeded("default links in two languages", both("put", "/01/09506000134352", record(
    [link("gs1:pip", "https://a.example/b-es", "es"), link("gs1:defaultLink", "https://a.example/b-es", "es")],
    "gs1:defaultLink", [{"10": "B1"}])))
same("default links in two languages")

# PUT and a DELETE of links with qualifiers no record of the key has: 404 on both, nothing changed (the link is one
# the key's first record has, where the official code removed it)
real, mock = both("put", "/01/09506000134352", record([link("gs1:pip", "https://a.example/x")], "gs1:defaultLink",
                                                      [{"10": "B404"}]))
check("PUT of a record that does not exist: both answer 404", real.status_code == mock.status_code == 404,
      (real.status_code, mock.status_code))
same("after the PUT of a record that does not exist")
real, mock = both("delete", "/01/09506000134352", {"qualifiers": [{"10": "B404"}],
                                                   "links": [{"linktype": "gs1:pip", "hreflang": ["en"], "context": []}]})
check("DELETE of links of a record that does not exist: both answer 404", real.status_code == mock.status_code == 404,
      (real.status_code, mock.status_code))
same("after the DELETE of links of a record that does not exist")

# A list sent to POST /new writes every record of a key (the portal restores a key's records with one): the real API
# stopped at the first record when the document existed, and kept a record sent twice as two entries
OTHER = "/01/09506000134369"
succeeded("a list naming a record twice, new key", both("post", "/new", [
    {**record([link("gs1:pip", "https://b.example/p")], "gs1:pip"), "anchor": OTHER},
    {**record([link("gs1:pip", "https://b.example/pt", lang="pt")], "gs1:pip"), "anchor": OTHER}]))
same("a list naming a record twice", OTHER)
succeeded("a list on a key that exists", both("post", "/new", [
    {**record([link("gs1:pip", "https://b.example/p2")], "gs1:pip"), "anchor": OTHER},
    {**record([link("gs1:pip", "https://b.example/l1")], "gs1:pip", [{"10": "L1"}]), "anchor": OTHER},
    {**record([link("gs1:pip", "https://b.example/l2")], "gs1:pip", [{"10": "L2"}]), "anchor": OTHER}]))
same("a list on a key that exists", OTHER)

# A DELETE whose body names no link deletes nothing: both answer 400 (the official code deleted the whole document)
for body in ({"qualifiers": [{"10": "B1"}]}, {"links": []}):
    real, mock = both("delete", "/01/09506000134352", body)
    check(f"DELETE with a body that names no link ({json.dumps(body)[:24]}): both answer 400",
          real.status_code == mock.status_code == 400, (real.status_code, mock.status_code))
same("after a DELETE whose body names no link")

real, mock = both("get", "/summary?links=true")
check("GET /summary with links gives the same lines", normal(real.get_json()) == normal(mock.get_json()),
      f"real {normal(real.get_json())}\n      stand-in {normal(mock.get_json())}")

real, mock = both("delete", "/01/09506000134352")
check("DELETE of the whole key: both accept", real.status_code == mock.status_code == 200,
      (real.status_code, mock.status_code))
real, mock = both("get", "/01/09506000134352")
check("after the DELETE both answer 404", real.status_code == mock.status_code == 404, (real.status_code, mock.status_code))

print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
