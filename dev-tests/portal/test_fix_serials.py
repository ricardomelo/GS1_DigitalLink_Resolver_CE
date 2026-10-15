"""
Serial-number records registered with their batch or variant before rule 2 of GS1-Conformant Resolver 1.2.1, section
2.5.9 (the backlog's "a way to fix records registered before rule 2"), through the portal's Flask test client and the
stand-in data entry API: such records are flagged; fixing one registers it again as the serial number alone with the
batch and variant as informative qualifiers, links, description and the key's other records unchanged, in the journal;
a serial number that already has its own record is left and reported; "fix them all" stays in the user's reach; and a
key whose document holds a record the API would refuse is never deleted to be written back (the guard every
deletion now has, through POST /api/validate).

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_fix_serials.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

from PIL import Image
from werkzeug.serving import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
CONFIG = tempfile.mkdtemp()
DATA_ENTRY_PORT = 3401
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL=f"http://127.0.0.1:{DATA_ENTRY_PORT}/api", SESSION_TOKEN="tok",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")   # a real MongoDB when PORTAL_DB_URI is set
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_fixserials_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"
os.environ.pop("RESOLVER_VERIFIED_BY_GS1_URL", None)

import mock_data_entry  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
users.create("root", "root-password-long", "admin", must_change=False)
import app as portal  # noqa: E402
import api_v1  # noqa: E402,F401
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


def image(kind="PNG", size=(60, 30), colour=(10, 120, 200)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind)
    return out.getvalue()


def data_uri(data, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


acme = tenants.create("Acme Foods", ["7891234"], "root")
beta = tenants.create("Beta Drinks", ["7895555"], "root")
users.create("ana", "ana-password-long", "admin", tenant=acme["id"], must_change=False)
users.create("edu", "edu-password-long", "editor", tenant=acme["id"], must_change=False)
users.create("bia", "bia-password-long", "admin", tenant=beta["id"], must_change=False)
root, ana, edu, bia = (client(u, f"{u}-password-long") for u in ("root", "ana", "edu", "bia"))



users.create("rui", "rui-password-long", "reader", tenant=acme["id"], must_change=False)
rui = client("rui", "rui-password-long")
A, B, C = gtin("0789123453001"), gtin("0789123453002"), gtin("0789555500001")
LINK = [{"linktype": "gs1:pip", "href": "https://acme.example.com/p", "title": "P", "hreflang": ["en"]}]


def put_raw(value, entries):
    """A key's document as other tools (or the portal before rule 2) left it: written straight into the stand-in."""
    mock_data_entry.DB[f"01_{value}"] = {"default": "gs1:pip", "entries": [
        {"qualifiers": q, "itemDescription": d, "links": [dict(l) for l in LINK], "informative": []} for q, d in entries]}


def entries_of(value):
    doc = mock_data_entry.DB.get(f"01_{value}")
    return [] if not doc else [(e["qualifiers"], e.get("informative") or [], e["itemDescription"]) for e in doc["entries"]]


put_raw(A, [([], "Coffee"), ([{"10": "L1"}, {"21": "S1"}], "Unit S1"), ([{"22": "V1"}, {"10": "L1"}, {"21": "S2"}], "Unit S2"),
            ([{"10": "L2"}], "Batch L2")])
put_raw(B, [([], "Tea"), ([{"10": "L9"}, {"21": "S9"}], "Unit S9"), ([{"21": "S9"}], "Unit S9 alone"),
            ([{"10": "L9"}, {"21": "S8"}], "Unit S8")])
D = gtin("0789123453003")
put_raw(D, [([], "Juice"), ([{"10": "L5"}, {"21": "S5"}], "Unit S5"), ([{"21": "S5"}], "Unit S5")])   # a true duplicate
put_raw(C, [([], "Beta"), ([{"10": "X"}, {"21": "Z"}], "Beta unit")])
records = ana.get("/portal/api/records").get_json()["records"]
flagged = sorted((r["value"], r["qpath"]) for r in records if r.get("breaksRules"))
check("flagged: the organisation's serial numbers registered with a batch or variant",
      flagged == sorted([(A, "/10/L1/21/S1"), (A, "/22/V1/10/L1/21/S2"), (B, "/10/L9/21/S9"), (B, "/10/L9/21/S8"),
                         (D, "/10/L5/21/S5")]), flagged)

r = rui.post("/portal/api/records/fix-serials", json={"all": True}, headers=ORIGIN)
check("a reader may not fix", r.status_code == 403)
r = edu.post("/portal/api/records/fix-serials", json={"key": "01", "value": A, "qualifiers": "/10/L1/21/S1"}, headers=ORIGIN)
check("a key's records fixed together (its document is written back whole)", code(r) == "rules.fixed"
      and r.get_json()["params"]["fixed"] == 2, r.get_json())
after = entries_of(A)
check("…registered again as the serial number alone, the batch as information, description and links kept",
      ([{"21": "S1"}], [{"10": "L1"}], "Unit S1") in after
      and mock_data_entry.DB[f"01_{A}"]["entries"][1]["links"][0]["href"] == "https://acme.example.com/p", after)
check("…the variant and batch both kept as information, in path order",
      ([{"21": "S2"}], [{"22": "V1"}, {"10": "L1"}], "Unit S2") in after, after)
check("…the key's other records unchanged", ([], [], "Coffee") in after and ([{"10": "L2"}], [], "Batch L2") in after
      and len(after) == 4, after)
journal = [(e["action"], e.get("qpath")) for e in store.col("journal").find({"anchor": f"/01/{A}"})]
check("…the journal: the old record deleted, the new one created", ("delete", "/10/L1/21/S1") in journal
      and ("create", "/21/S1") in journal, journal)

r = edu.post("/portal/api/records/fix-serials", json={"all": True}, headers=ORIGIN)
data = r.get_json()
check("fix them all: a true duplicate of the serial number's own record removed; a key whose serial number has its "
      "own record with other targets left whole and reported", code(r) == "rules.fixedSome"
      and data["params"]["fixed"] == 1 and data["conflicts"] == [f"/01/{B}/10/L9/21/S9"], data)
check("…the duplicate gone, the serial number's own record kept", entries_of(D) == [([], [], "Juice"),
      ([{"21": "S5"}], [], "Unit S5")], entries_of(D))
check("…the key with a conflict unchanged (its other rule-2 record too)", len(entries_of(B)) == 4
      and ([{"10": "L9"}, {"21": "S8"}], [], "Unit S8") in entries_of(B), entries_of(B))
check("…another organisation's records untouched", ([{"10": "X"}, {"21": "Z"}], [], "Beta unit") in entries_of(C))
check("…in the journal", store.col("journal").count_documents({"action": "fix-serials"}) == 2)
r = bia.post("/portal/api/records/fix-serials", json={"all": True}, headers=ORIGIN)
check("another organisation's administrator fixes its own", r.get_json()["params"]["fixed"] == 1
      and ([{"21": "Z"}], [{"10": "X"}], "Beta unit") in entries_of(C), r.get_json())

# ================================================================== the guard of every rewrite
r = edu.delete(f"/portal/api/record?key=01&value={B}&qualifiers=/21/S9", headers=ORIGIN)
check("deleting a record of a key whose document holds one the API would refuse: refused, nothing deleted",
      r.status_code == 422 and code(r) == "record.rewriteRefused" and "rule 2" in r.get_json()["params"]["detail"]
      and len(entries_of(B)) == 4, (r.status_code, r.get_json(), entries_of(B)))
r = edu.delete(f"/portal/api/record?key=01&value={A}&qualifiers=/10/L2", headers=ORIGIN)
check("an ordinary deletion still works", r.status_code == 200 and len(entries_of(A)) == 3)

i18n = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
codes = {"rules.fixed", "rules.fixedSome", "rules.fixedNone", "record.rewriteRefused", "records.rules.alert",
         "records.rules.fix", "records.rules.fixAll", "records.rules.confirmAll", "audit.action.fix-serials"}
missing = sorted(c for c in codes if i18n.count(f'"{c}"') != 2)
check("the texts in both languages", not missing, missing)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
