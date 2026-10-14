"""
The GS1 Barcode Syntax Engine's messages in the user's language (Documentation/adr/0003-gs1-rules-from-the-dictionary.md):
portal/engine_messages.json is what the sources of the engine release in docker-compose.yml give; every message
and every linter's message of that release has a translation in both languages of static/i18n.js, with the same
parameters, the English one being the engine's own text; an engine message is recognised as its code and
parameters (a linter's message inside it too); the comparison the weekly update check puts in its issue.

  GS1_SYNTAX_ENGINE_DIR=<engine build> python dev-tests/portal/test_engine_messages.py
"""
import copy
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
sys.path[:0] = [PORTAL, os.path.join(HERE, "..")]

import engine_messages  # noqa: E402
import syntax  # noqa: E402
from engine_release import engine_release  # noqa: E402
from gs1 import ValidationError  # noqa: E402

sys.path.insert(0, os.path.join(PORTAL, "tools"))
import gen_engine_messages  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


DATA = engine_messages.load()
MESSAGES = engine_messages.Messages()
PLACEHOLDER = re.compile(r"\{(\w+)\}")

# ------------------------------------------------------------------ the table and the release
check(f"engine_messages.json made from the release of docker-compose.yml ({engine_release()})",
      DATA["release"] == engine_release(), DATA["release"])
engine_dir = os.environ.get("GS1_SYNTAX_ENGINE_DIR", "")
if os.path.isfile(os.path.join(engine_dir, "source", "tr_EN.h")):
    with open(engine_messages.PATH, encoding="utf-8") as fh:
        committed = fh.read()
    check("engine_messages.json is exactly what the engine's sources give (tools/gen_engine_messages.py)",
          gen_engine_messages.generate(engine_dir) == committed)
    run = subprocess.run([sys.executable, os.path.join(PORTAL, "tools", "gen_engine_messages.py"), engine_dir, "--check"],
                         capture_output=True, text=True)
    check("gen_engine_messages.py --check: up to date, status 0", run.returncode == 0 and "up to date" in run.stdout,
          run.stdout + run.stderr)
else:
    print("SKIP engine_messages.json against the engine's sources (set GS1_SYNTAX_ENGINE_DIR to a build of "
          "portal/tools/build-syntax-engine.sh)")
codes = [m["code"] for m in DATA["messages"]]
lint_codes = [lint["code"] for lint in DATA["linters"]]
check("every message and linter's message of the release, once each (94 and 117 in 1.4.1)",
      len(codes) == len(set(codes)) and len(lint_codes) == len(set(lint_codes))
      and (DATA["release"] != "1.4.1" or (len(codes), len(lint_codes)) == (94, 117)), (len(codes), len(lint_codes)))
check("the number of parameters of each template counts its printf conversions ('%%' is none)",
      all(m["params"] == len(PLACEHOLDER.findall(engine_messages.catalogue_text(m["template"]))) for m in DATA["messages"])
      and engine_messages.catalogue_text("%.*s: %s 100%% %u%c") == "{p1}: {p2} 100% {p3}{p4}")

# ------------------------------------------------------------------ the parsers of the generator
templates = gen_engine_messages.parse_templates('#define TR_EN_A "AI (%.*s) is \\"%s\\""\n#define TR_EN_B "100%%"\n')
check("templates: name, unescaped text, parameters", templates == [
    {"code": "A", "template": 'AI (%.*s) is "%s"', "params": 2}, {"code": "B", "template": "100%%", "params": 0}], templates)
linters = gen_engine_messages.parse_linters(
    'const char *gs1_lint_err_str[] = {\n\t"",\n\t"First.",\n\t"",\n\t"Third.",\n};\n',
    "typedef enum {\n\tGS1_LINTER_OK = 0,\n\tGS1_LINTER_FIRST,\n\tGS1_LINTER_UNUSED,\n\tGS1_LINTER_THIRD,\n"
    "\t__GS1_LINTER_NUM_ERRS\n} gs1_lint_err_t;")
check("linters: codes paired with the strings in order, OK and empty slots left out",
      linters == [{"code": "FIRST", "text": "First."}, {"code": "THIRD", "text": "Third."}], linters)

# ------------------------------------------------------------------ both languages of every message
catalogue_js = open(os.path.join(PORTAL, "static", "i18n.js"), encoding="utf-8").read()
blocks = re.split(r'\n    "(pt-BR|en-GB)": \{', catalogue_js)[1:]
catalogue = {}
for locale, block in zip(blocks[0::2], blocks[1::2]):
    catalogue[locale] = {key: json.loads(value) for key, value in
                         re.findall(r'^      "(engine\.[^"]+)": ("(?:[^"\\]|\\.)*"),?$', block, re.M)}
expected = {"engine." + m["code"]: engine_messages.catalogue_text(m["template"]) for m in DATA["messages"]}
expected.update({"engine.lint." + lint["code"]: lint["text"] for lint in DATA["linters"]})
pt, en = catalogue.get("pt-BR", {}), catalogue.get("en-GB", {})
check("every engine message has its English text: the engine's own, parameters as {p1}, {p2}…",
      en == expected, sorted(set(en) ^ set(expected)) or [k for k in en if en[k] != expected.get(k)])
check("every engine message has its Portuguese text, and no other engine.* key exists",
      set(pt) == set(expected), sorted(set(pt) ^ set(expected)))
check("…with the same parameters as the English text",
      all(sorted(PLACEHOLDER.findall(pt.get(k, ""))) == sorted(PLACEHOLDER.findall(v)) for k, v in expected.items()),
      [k for k, v in expected.items() if sorted(PLACEHOLDER.findall(pt.get(k, ""))) != sorted(PLACEHOLDER.findall(v))])
same = sorted(k for k in expected if pt.get(k) == expected[k])
check("…and translated (only 'AI ({p1}): {p2}' reads the same in both)", same == ["engine.AI_LINTER_ERROR"], same)

# ------------------------------------------------------------------ recognising the engine's messages
for text, result in [
        ("AI (17): The date contains an illegal month of the year.",
         {"code": "engine.AI_LINTER_ERROR", "params": {"p1": "17", "p2": {"code": "engine.lint.ILLEGAL_MONTH", "params": {}}}}),
        ("AI (17) value is too short", {"code": "engine.AI_VALUE_IS_TOO_SHORT", "params": {"p1": "17"}}),
        ("Required AIs for AI (17) are not satisfied: 01,02",
         {"code": "engine.REQUIRED_AIS_NOT_SATISFIED", "params": {"p1": "17", "p2": "01,02"}}),
        ("No known AI is a prefix of: 9999...", {"code": "engine.NO_AI_FOR_PREFIX", "params": {"p1": "9999"}}),
        ("Syntax Dictionary line 12: AI must be numeric",
         {"code": "engine.SYNTAX_DICTIONARY_LINE_ERROR", "params": {"p1": "12", "p2": {"code": "engine.AI_MUST_BE_NUMERIC", "params": {}}}}),
        ("Something the engine never says", None)]:
    check(f"recognised: {text}", MESSAGES.recognise(text) == result, MESSAGES.recognise(text))


def sample(template):
    """The template with a value for each parameter, as the engine would write it."""
    return engine_messages.SPEC.sub(lambda m: "%" if m.group(0) == "%%" else "7" if m.group(0)[-1] in "ud"
                                    else "Z" if m.group(0) == "%c" else "ab", template)


mistaken = [m["code"] for m in DATA["messages"] if (MESSAGES.recognise(sample(m["template"])) or {}).get("code") != "engine." + m["code"]]
check("every template is recognised as itself (no template hides another)", mistaken == [], mistaken)
mistaken = [lint["code"] for lint in DATA["linters"] if MESSAGES.recognise(lint["text"]) != {"code": "engine.lint." + lint["code"], "params": {}}]
check("every linter's message is recognised as itself", mistaken == [], mistaken)
check("without the table, nothing is recognised and the engine's text is shown",
      engine_messages.Messages({"release": "x", "messages": [], "linters": []}).recognise("AI (17) value is too short") is None)

# ------------------------------------------------------------------ the portal's refusal carries the message
ENGINE = syntax.ENGINE
if ENGINE.available:
    def refusal(attributes):
        try:
            ENGINE.digital_link("https://id.example.org", "/01/09506000134352", [], attributes)
        except ValidationError as exc:
            return exc.code, exc.params
        return None

    code, params = refusal([("17", "261399")]) or (None, {})
    check("an illegal month: attr.invalid with the English detail and the recognised message",
          code == "attr.invalid" and "illegal month" in params.get("detail", "")
          and params.get("message") == {"code": "engine.AI_LINTER_ERROR",
                                        "params": {"p1": "17", "p2": {"code": "engine.lint.ILLEGAL_MONTH", "params": {}}}},
          (code, params))
    code, params = refusal([("422", "999")]) or (None, {})
    check("a country code: engine.lint.NOT_ISO3166 inside the message",
          code == "attr.invalid" and params.get("message", {}).get("params", {}).get("p2") == {"code": "engine.lint.NOT_ISO3166", "params": {}},
          (code, params))
    code, params = refusal([("392n", "111")]) or (None, {})
    check("association rules keep their own messages (attr.requires), naming the AI as chosen",
          code == "attr.requires" and params.get("ai") == "392n", (code, params))
else:
    print(f"SKIP the portal's refusals ({ENGINE.reason})")

# ------------------------------------------------------------------ the comparison of the weekly update check
newer = copy.deepcopy(DATA)
newer["release"] = "9.9.9"
newer["messages"].append({"code": "NEW_THING", "template": "AI (%.*s) is new", "params": 1})
newer["linters"] = [dict(lint, text="Changed.") if lint["code"] == "ILLEGAL_MONTH" else lint
                    for lint in newer["linters"] if lint["code"] != "IBAN_TOO_LONG"]
diff = gen_engine_messages.compare(DATA, newer)
check("comparison: messages added, changed and removed",
      diff["added"] == ["engine.NEW_THING"] and diff["changed"] == ["engine.lint.ILLEGAL_MONTH"]
      and diff["removed"] == ["engine.lint.IBAN_TOO_LONG"], {k: diff[k] for k in ("added", "changed", "removed")})
text = gen_engine_messages.summary(DATA, newer)
check("comparison as Markdown: the releases and every message that needs a translation",
      "1.4.1 → 9.9.9" in text and "`engine.NEW_THING`: AI (%.*s) is new" in text
      and "`engine.lint.ILLEGAL_MONTH` (changed): Changed." in text and "`engine.lint.IBAN_TOO_LONG`" in text, text)
check("comparison of a table with itself", "No engine message changed" in gen_engine_messages.summary(DATA, DATA))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
