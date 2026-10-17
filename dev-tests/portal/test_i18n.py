"""
Every text in every language (Documentation/adr/0014-interface-languages.md): the same eleven languages everywhere
(the portal, its e-mails, the resolver's pages, the item's page, the home page), each named in its own language, Arabic
right to left; every message of the portal, of the e-mails, of the pages and of the home page present in every
language, not empty, with the same {placeholders} as the English; every link type named in every language on the
portal and on the resolver's pages; the portal serving each catalogue; the resolver choosing the language from the
browser's; a page in Japanese and one in Arabic.

  pip install -r portal/requirements.txt -r web_server/src/requirements.txt mongomock
  python dev-tests/portal/test_i18n.py
"""
import json
import os
import re
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(REPO, "portal"))
WEB = os.path.join(REPO, "web_server", "src")
sys.path[:0] = [HERE, PORTAL, os.path.join(PORTAL, "tools")]
os.environ.update(DATA_ENTRY_URL="http://127.0.0.1:9/api", SESSION_TOKEN="tok", PORTAL_CONFIG_DIR=tempfile.mkdtemp(),
                  PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", PORTAL_MONITOR_MINUTES="0", PORTAL_WORKER="external")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_i18n_{os.getpid()}")

import i18n_catalogue  # noqa: E402
import gs1  # noqa: E402
import mailtexts  # noqa: E402
import users  # noqa: E402

failures = []
LANGUAGES = ["pt-BR", "en-GB", "es", "fr", "de", "it", "zh-Hans", "ja", "ko", "hi", "ar"]
ENDONYMS = {"pt-BR": "Português (Brasil)", "en-GB": "English (UK)", "es": "Español", "fr": "Français", "de": "Deutsch",
            "it": "Italiano", "zh-Hans": "中文（简体）", "ja": "日本語", "ko": "한국어", "hi": "हिन्दी", "ar": "العربية"}
OTHERS = [tag for tag in LANGUAGES if tag not in ("pt-BR", "en-GB")]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {str(detail)[:600]}"))
    if not condition:
        failures.append(name)


def names(text):
    return sorted(set(PLACEHOLDER.findall(text)))


def js_list(text, name):
    found = re.search(rf"const {name} = \[([^\]]*)\]", text)
    return re.findall(r'"([^"]+)"', found.group(1)) if found else []


def js_catalogue(path):
    text = open(path, encoding="utf-8").read()
    start = text.index("const CATALOGUE = {") + len("const CATALOGUE = ")
    end = text.index("\n  };\n", start) + len("\n  }")
    body = "\n".join(line for line in text[start:end].splitlines() if not line.strip().startswith("//"))
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", body))


# ================================================================== the same languages everywhere
i18n_js = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
home_js_path = os.path.join(REPO, "frontend_proxy_server", "home", "home.js")
home_js = open(home_js_path, encoding="utf-8").read()
with open(os.path.join(WEB, "page_texts.json"), encoding="utf-8") as fh:
    page_texts = json.load(fh)
check("the portal offers the eleven languages", js_list(i18n_js, "SUPPORTED") == LANGUAGES, js_list(i18n_js, "SUPPORTED"))
check("…the home page the same", js_list(home_js, "SUPPORTED") == LANGUAGES, js_list(home_js, "SUPPORTED"))
check("…the e-mails and the users' preference the same", sorted(mailtexts.LANGUAGES) == sorted(LANGUAGES)
      and sorted(users.LANGUAGES) == sorted(LANGUAGES), (mailtexts.LANGUAGES, users.LANGUAGES))
check("…the resolver's pages the same, in the same order", list(page_texts) == LANGUAGES, list(page_texts))
check("a catalogue file for each language the portal loads on demand", i18n_catalogue.languages() == sorted(OTHERS),
      i18n_catalogue.languages())
check("Arabic right to left in the portal, the resolver's pages and the home page",
      'RIGHT_TO_LEFT = new Set(["ar"])' in i18n_js and 'RIGHT_TO_LEFT = ["ar"]' in home_js
      and "RIGHT_TO_LEFT = {'ar'}" in open(os.path.join(WEB, "web_pages.py"), encoding="utf-8").read())

# ================================================================== the portal
def catalogue(tag):
    """A language's catalogue file ({} when missing: every check of it then fails)."""
    try:
        return i18n_catalogue.load(tag)
    except FileNotFoundError:
        return {}


builtin = i18n_catalogue.builtin()
english = builtin["en-GB"]
for tag in OTHERS:
    found = i18n_catalogue.problems(english, catalogue(tag))
    check(f"portal, {tag}: every message, none empty, the same placeholders, every link type named and explained",
          not found, found[:12])
broken = json.loads(json.dumps(catalogue("es")))
del broken["menu.users"]
broken["records.count"] = broken["records.count"].replace("{shown}", "{count}")
broken["users.save"] = " "
broken["linkTypes"]["gs1:pip"] = ["Página", ""]
broken["extra.key"] = "x"
found = i18n_catalogue.problems(english, broken)
check("the check of a catalogue finds a missing message, other placeholders, an empty text, a link type without its "
      "explanation and an unknown message", {"missing: menu.users", "empty: users.save",
                                            "link type without a name and an explanation: gs1:pip", "unknown: extra.key"}
      <= set(found) and any(f.startswith("placeholders of records.count") for f in found), found)
portuguese = {k: v for k, v in builtin["pt-BR"].items() if not k.startswith("ai.")}
check("portal, pt-BR: the same (the names of the AIs are Portuguese's own)",
      not i18n_catalogue.problems(english, portuguese), i18n_catalogue.problems(english, portuguese)[:12])
names_found = {tag: (catalogue(tag) if tag in OTHERS else builtin[tag]).get("locale.name") for tag in LANGUAGES}
check("each language named in itself", names_found == ENDONYMS, names_found)
endonyms_js = dict(re.findall(r'"([A-Za-z-]+)": "([^"]+)"', i18n_js[i18n_js.index("const ENDONYMS"):
                                                                    i18n_js.index("const RIGHT_TO_LEFT")]))
check("…also in the portal's menu before a catalogue is loaded", endonyms_js == ENDONYMS, endonyms_js)
check("every link type the portal offers in every language", all(
    set((catalogue(tag) if tag in OTHERS else builtin[tag]).get("linkTypes", {})) == {c for c, _, _ in gs1.LINK_TYPES}
    for tag in LANGUAGES))
same = {tag: sum(1 for k, v in catalogue(tag).items()
                 if isinstance(v, str) and v == english.get(k) and len(v) > 30) for tag in OTHERS}
check("the catalogues are translations (few long texts left as the English)", all(n < 40 for n in same.values()), same)

import app as portal  # noqa: E402
client = portal.app.test_client()
answers = {tag: client.get(f"/portal/locales/{tag}.json") for tag in OTHERS}
check("the portal serves each catalogue to anyone (the sign-in page needs it)",
      all(r.status_code == 200 and r.mimetype == "application/json" and r.get_json()["locale.name"] == ENDONYMS[t]
          for t, r in answers.items()), {t: r.status_code for t, r in answers.items()})
check("…and nothing else from that folder", client.get("/portal/locales/pt-BR.json").status_code == 404
      and client.get("/portal/locales/xx.json").status_code == 404
      and client.get("/portal/locales/..%2Fapp.js").status_code == 404)

# ================================================================== the e-mails
for tag in LANGUAGES:
    wrong = []
    for name, texts in mailtexts.TEXTS.items():
        subject, body = texts.get(tag, ("", ""))
        english_subject, english_body = texts["en-GB"]
        if not subject.strip() or not body.strip() or names(subject) != names(english_subject) \
                or names(body) != names(english_body):
            wrong.append(name)
    if names(mailtexts.SIGNATURE.get(tag, "")) != names(mailtexts.SIGNATURE["en-GB"]):
        wrong.append("signature")
    check(f"e-mails, {tag}: every message with its subject, the same placeholders, the signature", not wrong, wrong)
subject, text, html_text = mailtexts.compose("invite", "ja", operator="Org", user="ana", hours=72,
                                             link="https://id.example.org/portal/login#invite=x", portal="https://p")
check("an invitation in Japanese", "ana" in text and "72" in text and subject != mailtexts.TEXTS["invite"]["en-GB"][0]
      and "https://id.example.org/portal/login#invite=x" in html_text, subject)
check("a preference of another region reads as the language", mailtexts.language("zh-CN") == "zh-Hans"
      and mailtexts.language("es-MX") == "es" and mailtexts.language("ar-EG") == "ar" and mailtexts.language("xx") == "en-GB")

# ================================================================== the resolver's pages and the item's page
link_terms = {code.split(":", 1)[1] for code, _, _ in gs1.LINK_TYPES} | {"defaultLink", "defaultLinkMulti"}
for tag in LANGUAGES:
    texts = page_texts.get(tag, {"name": "", "pages": {}, "landing": {}, "linkLabels": {}})
    wrong = [f"{part}/{k}" for part in ("pages", "landing") for k, v in page_texts["en-GB"][part].items()
             if not str(texts[part].get(k, "")).strip() or names(texts[part].get(k, "")) != names(v)]
    wrong += [f"{part}/{k}" for part in ("pages", "landing") for k in texts[part] if k not in page_texts["en-GB"][part]]
    missing = sorted(link_terms - set(texts["linkLabels"]))
    check(f"resolver's pages, {tag}: every text, the same placeholders, every link type named",
          not wrong and not missing and texts["name"] == ENDONYMS[tag], (wrong, missing))

for name in ("mongo_db_init", "web_db"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["mongo_db_init"].mongo = None
sys.modules["web_db"].read_document = lambda anchor: {"response_status": 404}
os.environ.setdefault("FQDN", "id.example.org")
sys.path.insert(0, WEB)
import web_pages  # noqa: E402
for header, expected in [("es-MX,es;q=0.9", "es"), ("zh-TW", "zh-Hans"), ("ar-EG", "ar"), ("de;q=0.5,fr", "fr"),
                         ("ko-KR", "ko"), ("hi", "hi"), ("ja-JP", "ja"), ("it-CH", "it"), ("nl", "en-GB")]:
    check(f"the resolver's page for Accept-Language {header!r}: {expected}",
          web_pages.negotiate_locale(header) == expected, web_pages.negotiate_locale(header))
check("…the language cookie wins", web_pages.negotiate_locale("ja", "ar") == "ar")
from flask import Flask  # noqa: E402
flask_app = Flask(__name__)
with flask_app.test_request_context("/01/09506000134352", headers={"Accept-Language": "ja"}):
    page = web_pages.render_error(404, "/01/09506000134352", None, None, None)
check("a page in Japanese", 'lang="ja"' in page and 'dir="ltr"' in page and page_texts["ja"]["pages"]["error.404.title"]
      in page and "日本語" in page, page[:300])
with flask_app.test_request_context("/01/09506000134352", headers={"Accept-Language": "ar"}):
    page = web_pages.render_error(404, "/01/09506000134352", None, None, None)
check("…in Arabic, right to left, with the menu of every language", 'lang="ar"' in page and 'dir="rtl"' in page
      and all(f">{n}<" in page for n in ENDONYMS.values()), page[:300])

# ================================================================== the home page
home = js_catalogue(home_js_path)
for tag in LANGUAGES:
    texts = home.get(tag, {})
    wrong = [k for k, v in home["en-GB"].items() if not str(texts.get(k, "")).strip() or names(texts.get(k, "")) != names(v)]
    wrong += [k for k in texts if k not in home["en-GB"]]
    check(f"home page, {tag}: every text", not wrong and texts.get("locale.name") == ENDONYMS[tag], wrong)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
