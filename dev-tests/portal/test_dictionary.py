"""
The GS1 rules from the GS1 Barcode Syntax Dictionary (Documentation/adr/0003-gs1-rules-from-the-dictionary.md):
portal/gs1_dictionary.json is what the dictionary of the engine release in docker-compose.yml gives; the
portal's keys, qualifiers and formats are built from it, with the portal's deliberate exceptions; a format the
portal cannot check stops the build instead of being accepted; the comparison the weekly update check puts in
its issue.

  GS1_SYNTAX_ENGINE_DIR=<engine build> python dev-tests/portal/test_dictionary.py
"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
sys.path[:0] = [PORTAL, os.path.join(HERE, "..")]

import gs1  # noqa: E402
import gs1dict  # noqa: E402
from engine_release import engine_release  # noqa: E402

sys.path.insert(0, os.path.join(PORTAL, "tools"))
import dictionary_diff  # noqa: E402
import gen_dictionary  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def raises(callable_):
    """The message of the DictionaryError raised, or None."""
    try:
        callable_()
    except gs1dict.DictionaryError as exc:
        return str(exc)
    return None


DATA = gs1dict.load()
AIS = DATA["ais"]

# ------------------------------------------------------------------ the file and the release
check(f"gs1_dictionary.json made from the release of docker-compose.yml ({engine_release()})",
      DATA["release"] == engine_release() == gs1.DICTIONARY_RELEASE, DATA["release"])
engine_dir = os.environ.get("GS1_SYNTAX_ENGINE_DIR", "")
if os.path.isfile(os.path.join(engine_dir, "gs1-syntax-dictionary.txt")):
    with open(os.path.join(gs1dict.PATH), encoding="utf-8") as fh:
        committed = fh.read()
    check("gs1_dictionary.json is exactly what the engine's dictionary gives (tools/gen_dictionary.py)",
          gen_dictionary.generate(engine_dir) == committed)
    run = subprocess.run([sys.executable, os.path.join(PORTAL, "tools", "gen_dictionary.py"), engine_dir, "--check"],
                         capture_output=True, text=True)
    check("gen_dictionary.py --check: up to date, status 0", run.returncode == 0 and "up to date" in run.stdout, run.stdout)
else:
    print("SKIP gs1_dictionary.json against the engine's dictionary (set GS1_SYNTAX_ENGINE_DIR)")
check("the file's dictionary date is the one in its header", DATA["dictionary"] == "2026-01-27", DATA["dictionary"])
check("ranges expanded; every AI with title, flags and components",
      all(f"310{n}" in AIS for n in range(6)) and all({"title", "flags", "components", "req", "ex"} <= set(e) for e in AIS.values()),
      len(AIS))
check("one line per AI, in order (a new release reads as a short diff)",
      gs1dict.dump(DATA) == open(gs1dict.PATH, encoding="utf-8").read() and list(AIS) == sorted(AIS))

# ------------------------------------------------------------------ the parser
sample = """# Release: 2099-01-01
01         *?  N14,csum,gcppos2                  ex=255,37 dlpkey=22,10,21|235                    # GTIN
10          ?  X..20                             req=01,02 req=8006+21                           # BATCH/LOT
3100-3102  *?  N6                                req=01,02                                        # NET WEIGHT (kg)
"""
parsed = gs1dict.parse(sample)
check("parser: release date, flags, components, alternatives of dlpkey, groups of req and ex, repeated req",
      parsed["dictionary"] == "2099-01-01" and parsed["ais"]["01"]["dlpkey"] == [["22", "10", "21"], ["235"]]
      and parsed["ais"]["01"]["ex"] == [[["255"], ["37"]]] and parsed["ais"]["10"]["req"] == [[["01"], ["02"]], [["8006", "21"]]]
      and parsed["ais"]["10"]["flags"] == "?" and list(parsed["ais"]) == ["01", "10", "3100", "3101", "3102"], parsed)
check("parser: an attribute it does not know is an error, with the line number",
      "line 2" in (raises(lambda: gs1dict.parse("01 N14 dlpkey # GTIN\n10 X..20 newattr=1 # LOT")) or ""))
check("parser: a component it does not know is an error", raises(lambda: gs1dict.parse("01 Q14 # GTIN")) is not None)

# ------------------------------------------------------------------ the portal's rules built from it
keys = [k for k, e in AIS.items() if "dlpkey" in e]
check("every primary key of the dictionary is a key of the portal, in the order of URI Syntax 4.3",
      sorted(gs1.PRIMARY_KEYS) == sorted(keys) and len(keys) == 16
      and list(gs1.PRIMARY_KEYS)[:4] == ["01", "8006", "8013", "8010"], list(gs1.PRIMARY_KEYS))
check("key qualifiers in the dictionary's order",
      gs1.QUALIFIER_ORDER == ["22", "10", "21", "235", "8011", "254", "7040", "8020", "8019"], gs1.QUALIFIER_ORDER)
check("exception: ITIP without (22) (erratum E2), though the dictionary lists it",
      "22" in AIS["8006"]["dlpkey"][0] and gs1.key_qualifiers("8006") == ["10", "21"], gs1.key_qualifiers("8006"))
check("req of the key: 415 needs 8020", gs1.KEY_SHAPES["415"] == [[("8020", True)]], gs1.KEY_SHAPES["415"])
check("an alternative sequence is told apart by its first qualifier (01: 235; 414: 7040)",
      gs1.KEY_SHAPES["01"][1] == [("235", True)] and gs1.KEY_SHAPES["414"] == [[("254", False)], [("7040", True)]],
      (gs1.KEY_SHAPES["01"], gs1.KEY_SHAPES["414"]))
check("formats from the components: lengths of the dictionary, the portal's character sets",
      gs1.QUALIFIER_FORMATS["235"][1].match("A" * 28) and not gs1.QUALIFIER_FORMATS["235"][1].match("A" * 29)
      and not gs1.QUALIFIER_FORMATS["10"][1].match("L 1") and gs1.QUALIFIER_FORMATS["10"][1].match("L_1.2-x")
      and gs1.QUALIFIER_FORMATS["8011"][1].match("9" * 12) and not gs1.QUALIFIER_FORMATS["8011"][1].match("012")
      and gs1.QUALIFIER_FORMATS["7040"][1].match("1A..") is None and gs1.QUALIFIER_FORMATS["7040"][1].match("1A.-"))
check("titles of the dictionary", gs1.QUALIFIER_FORMATS["10"][0] == "BATCH/LOT" and AIS["414"]["title"] == "LOC No.")

lengthened = copy.deepcopy(DATA)
lengthened["ais"]["10"]["components"][0]["max"] = 30
lengthened["ais"]["414"]["components"][0]["max"] = lengthened["ais"]["414"]["components"][0]["min"] = 14
primary, shapes, order, formats = gs1._build(lengthened)
check("a longer batch in a new dictionary changes the portal's rules with no code",
      bool(formats["10"][1].match("B" * 30)) and not gs1.QUALIFIER_FORMATS["10"][1].match("B" * 30))
gln14 = "1234567890123" + str(gs1.gtin_check_digit("1234567890123"))
try:
    primary["414"][1](gln14)
    longer_gln = True
except gs1.ValidationError as exc:
    longer_gln = exc
check("…and a longer GLN: the validator takes the new length", longer_gln is True, longer_gln)

added = copy.deepcopy(DATA)
added["ais"]["9999"] = {"title": "NEW KEY", "flags": "?", "components": [{"type": "N", "min": 13, "max": 13,
                        "optional": False, "linters": ["csum", "gcppos1"]}], "req": [], "ex": [], "dlpkey": [["10"]]}
primary, shapes, order, formats = gs1._build(added)
check("a new key of a known format is built with no code, under its dictionary title, last",
      list(primary)[-1] == "9999" and primary["9999"][0] == "NEW KEY" and shapes["9999"] == [[("10", False)]])

unknown = copy.deepcopy(DATA)
unknown["ais"]["414"]["components"][0]["linters"].append("newlinter")
check("a key with a linter the portal does not check stops the build, naming it",
      "newlinter" in (raises(lambda: gs1._build(unknown)) or ""), raises(lambda: gs1._build(unknown)))
unknown = copy.deepcopy(DATA)
unknown["ais"]["10"]["components"][0]["linters"].append("newlinter")
check("a qualifier with a linter the portal does not check stops the build",
      "qualifier 10" in (raises(lambda: gs1._build(unknown)) or ""))
odd = copy.deepcopy(DATA)
odd["ais"]["8004"]["components"].append({"type": "N", "min": 2, "max": 2, "optional": False, "linters": []})
check("a key of an unknown shape stops the build", "key 8004" in (raises(lambda: gs1._build(odd)) or ""))

rules = gs1.browser_rules()
check("the browser's rules come from the same tables: every key's check, every qualifier's pattern and length",
      set(rules["keys"]) == set(gs1.PRIMARY_KEYS) and rules["order"] == gs1.QUALIFIER_ORDER
      and rules["keys"]["414"] == {"kind": "numeric", "length": 13} and rules["keys"]["8003"]["filler"] == "0"
      and rules["qualifiers"]["235"]["max"] == 28 and rules["qualifiers"]["7040"]["max"] == 4
      and all(rules["qualifiers"][q]["pattern"] == gs1.QUALIFIER_FORMATS[q][1].pattern for q in gs1.QUALIFIER_ORDER)
      and rules["release"] == DATA["release"], rules["keys"])
check("digits-only keys drop the separators people type (from the checks, not a list)",
      gs1.normalise_key("414", "506.0000.00000.9") == "5060000000009" and gs1.normalise_key("8004", "1234-A") == "1234-A")

# ------------------------------------------------------------------ AIs of the dictionary the portal names
check("(7041) and (8040)-(8043) are in the dictionary, none of them a data attribute, key or qualifier",
      all(c in AIS and "?" not in AIS[c]["flags"] and "dlpkey" not in AIS[c] and c not in gs1.QUALIFIER_ORDER
          for c in ("7041", "8040", "8041", "8042", "8043")) and AIS["8040"]["title"] == "IMEI")

# ------------------------------------------------------------------ the comparison of the weekly update check
newer = copy.deepcopy(DATA)
newer.update(release="9.9.9", dictionary="2099-01-01")
newer["ais"]["8040"]["flags"] = "?"
newer["ais"]["7777"] = {"title": "SOMETHING NEW", "flags": "?", "components": [{"type": "X", "min": 1, "max": 20,
                        "optional": False, "linters": []}], "req": [[["01"]]], "ex": []}
del newer["ais"]["8043"]
newer["ais"]["10"]["components"][0]["max"] = 30
diff = dictionary_diff.compare(DATA, newer)
check("comparison: AIs added, removed and changed; data attributes gained",
      diff["added"] == ["7777"] and diff["removed"] == ["8043"] and ("10", ["components"]) in diff["changed"]
      and diff["attributes_gained"] == ["7777", "8040"], diff)
text = dictionary_diff.markdown(DATA, newer)
check("comparison as Markdown for the issue: releases, the format change, the portal's rules built",
      "engine 9.9.9" in text and "(10) BATCH/LOT: format `X..20` → `X..30`" in text
      and "built from the new dictionary" in text, text)
broken = copy.deepcopy(newer)
broken["ais"]["01"]["components"][0]["linters"].append("newlinter")
check("comparison: says when the portal cannot build its rules from the new dictionary",
      "cannot be built" in dictionary_diff.markdown(DATA, broken) and "newlinter" in dictionary_diff.markdown(DATA, broken))
check("comparison of a dictionary with itself", "No AI changed." in dictionary_diff.markdown(DATA, DATA))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
