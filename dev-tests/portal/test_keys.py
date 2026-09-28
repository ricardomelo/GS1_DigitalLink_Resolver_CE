"""
Primary identification keys (GS1 Digital Link URI Syntax 1.7, section 4.3): the portal's validation of
every key, and — when the GS1 Barcode Syntax Engine is available — agreement with it, since that is the
library the resolver uses to accept or refuse each request.

  pip install -r portal/requirements.txt
  python dev-tests/portal/test_keys.py

To compare with the engine (recommended), install it once and point to it:
  mkdir -p /tmp/se && cd /tmp/se && npm init -y && npm pkg set type=module && npm install gs1encoder
  GS1_SYNTAX_ENGINE=/tmp/se python dev-tests/portal/test_keys.py
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal")))

import gs1  # noqa: E402
from gs1 import ValidationError  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def portal(ai, value):
    try:
        return gs1.normalise_key(ai, value), None
    except ValidationError as exc:
        return None, exc.code


# (AI, value, expected error code or None, engine agrees?) — the last flag is False where the portal is
# deliberately stricter than the standard (character subset).
CASES = [
    ("01", "09506000134352", None, True), ("01", "9506000134352", None, True), ("01", "09506000134353", "gtin.checkDigit", True),
    ("8006", "095060001343520102", None, True), ("8006", "095060001343520302", "key.itipPiece", True),
    ("8006", "095060001343520001", "key.itipPiece", True), ("8006", "095060001343530102", "key.checkDigit", True),
    ("8013", "1987654Ad4X4bL5ttr2310c2K", None, True), ("8013", "1987654Ad4X4bL5ttr2310c2X", "key.gmnPair", True),
    ("8013", "95060001", "key.gmnPair", True), ("8013", "ABC1234", "key.companyPrefix", True),
    ("8010", "9506000ABC-1", None, True), ("8010", "9506000abc", "key.cpidChars", True), ("8010", "ABC-1", "key.companyPrefix", True),
    ("414", "9506000134376", None, True), ("414", "9506000134377", "key.checkDigit", True), ("414", "950600013437", "key.length", True),
    ("417", "9506000134376", None, True),
    ("8017", "950600013437612342", None, True), ("8017", "950600013437612345", "key.checkDigit", True),
    ("8018", "950600013437612342", None, True),
    ("255", "9506000134376", None, True), ("255", "95060001343761234", None, True), ("255", "9506000134377", "key.checkDigit", True),
    ("00", "095060001343520000", None, True), ("00", "095060001343528862", "key.checkDigit", True),
    ("253", "9506000134376", None, True), ("253", "9506000134376ABC", None, True), ("253", "9506000134377ABC", "key.checkDigit", True),
    ("401", "9506000ABC", None, True), ("401", "ABC", "key.companyPrefix", True),
    ("402", "95060001343760123", None, True), ("402", "95060001343760122", "key.checkDigit", True),
    ("8003", "09506000134352ABC", None, True), ("8003", "09506000134352", None, True),
    ("8003", "19506000134352ABC", "key.graiZero", True), ("8003", "0950600013435", "key.baseDigits", True),
    ("8004", "9506000ABC123", None, True), ("8004", "1234", None, True), ("8004", "123ABC", "key.companyPrefix", True),
    # stricter than the standard on purpose: "_" and "+" are in the 82-character set
    ("8004", "9506000AB_C", "key.chars", False), ("401", "9506000A+B", "key.chars", False),
]

for ai, value, expected, _ in CASES:
    _, code = portal(ai, value)
    check(f"({ai}) {value} → {expected or 'valid'}", code == expected, code)

check("every key of section 4.3 except 415 is supported",
      set(gs1.PRIMARY_KEYS) == {"01", "8006", "8013", "8010", "414", "417", "8017", "8018", "255", "00", "253",
                                "401", "402", "8003", "8004"})
check("unsupported key refused", portal("415", "9506000134376")[1] == "key.unsupported")
check("separators removed from numeric keys", portal("00", "0 9506 0001 3435 2000-0")[0] == "095060001343520000")
check("anchor round trip", gs1.split_anchor(gs1.anchor_for("8004", "1234")) == ("8004", "1234")
      and gs1.split_anchor("/415/9506000134376") is None and gs1.split_anchor("/01/x/10/y") is None)
check("lot only for GTIN", gs1.allows_lot("01") and not gs1.allows_lot("00"))
check("Digital Link and HRI for any key",
      gs1.digital_link("https://id.example.org", "/00/095060001343520000", None) == "https://id.example.org/00/095060001343520000"
      and gs1.hri_lines("/8004/1234", None) == ["(8004)1234"] and gs1.hri_lines("/01/09506000134352", "L1")[1] == "(10)L1")

engine = os.environ.get("GS1_SYNTAX_ENGINE")
if engine and shutil.which("node") and os.path.isdir(os.path.join(engine, "node_modules", "gs1encoder")):
    script = """
import {GS1encoder} from "gs1encoder";
const g = new GS1encoder(); await g.init();
const out = {};
for (const s of JSON.parse(process.argv[2])) { try { g.aiDataStr = s; out[s] = null; } catch (e) { out[s] = e.message; } }
g.free(); console.log(JSON.stringify(out));
"""
    path = os.path.join(engine, "_portal_keys.mjs")
    with open(path, "w") as fh:
        fh.write(script)
    strings = [f"({ai}){value}" for ai, value, _, _ in CASES if ai != "01" or len(value) == 14]
    verdicts = json.loads(subprocess.run(["node", path, json.dumps(strings)], cwd=engine,
                                         capture_output=True, text=True, check=True).stdout)
    for ai, value, expected, agrees in CASES:
        key = f"({ai}){value}"
        if key not in verdicts:
            continue
        engine_ok = verdicts[key] is None
        portal_ok = expected is None
        if agrees:
            check(f"engine agrees on ({ai}) {value}", engine_ok == portal_ok, verdicts[key])
        else:
            check(f"portal stricter than the engine on ({ai}) {value}", engine_ok and not portal_ok, verdicts[key])
else:
    print("SKIP comparison with the GS1 Syntax Engine (set GS1_SYNTAX_ENGINE)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
