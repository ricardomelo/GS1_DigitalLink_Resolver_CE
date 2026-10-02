"""
Development test for web_server/src/epc_binary.py: EPC binary strings ('eh' / 'ex' compression strings of
GS1 Digital Link URI: Compression Technical Standard for EPC binary strings 1.0.0) decoded to GS1 Digital Link.

  pip install jsonschema
  python dev-tests/resolver/test_epc_binary.py

Optional: EPC_TDS=<directory where 'npm install epc-tds' was run> compares random EPCs of the classic schemes
with that independent library (MIT, https://github.com/sergiss/epc-tds).
"""
import json
import os
import subprocess
import sys

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("RESOLVER_REPO", os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "web_server", "src"))
import epc_binary  # noqa: E402
from epc_binary import EpcDecodeError, decompress  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def decoded(segment):
    d = decompress(segment)
    return d.path() + ("?" + d.query() if d.query() else "")


def refused(segment):
    try:
        decompress(segment)
        return None
    except EpcDecodeError as e:
        return str(e)


# ---------------------------------------------------------------- a small encoder, for the cases of TDS 2.0 / 2.3
def b(value, width):
    return format(value, f"0{width}b")


def nibbles(digits):
    return "".join(b(int(d, 16), 4) for d in digits)


B64 = epc_binary.BASE64_URL


def alnum(value, li_bits):
    """TDS 14.5.6 with the method of the decision tree: numeric, base 64, else 7-bit ASCII."""
    if value.isdigit():
        return "000" + b(len(value), li_bits) + b(int(value), (10 ** len(value) - 1).bit_length())
    if all(c in B64 for c in value):
        return "011" + b(len(value), li_bits) + "".join(b(B64.index(c), 6) for c in value)
    return "100" + b(len(value), li_bits) + "".join(b(ord(c), 7) for c in value)


def date(yymmdd):
    return b(int(yymmdd[:2]), 7) + b(int(yymmdd[2:4]), 4) + b(int(yymmdd[4:]), 5)


def aidc(ai, value_bits):
    return nibbles(ai) + value_bits


def sgtin_plus(gtin, serial, toggle="1", header="11110111", tail=""):
    return header + toggle + "011" + nibbles(gtin) + alnum(serial, 5) + tail


def eh(bits):
    bits += "0" * (-len(bits) % 16)                     # padded to a 16-bit word, as in Gen2 EPC memory
    return "eh" + "".join(format(int(bits[i:i + 4], 2), "x") for i in range(0, len(bits), 4))


def ex(bits):
    bits += "0" * (-len(bits) % 6)
    return "ex" + "".join(B64[int(bits[i:i + 6], 2)] for i in range(0, len(bits), 6))


def urn40(text):
    table = epc_binary._URN_CODE_40
    out = ""
    for i in range(0, len(text), 3):
        group = [table.index(c) for c in text[i:i + 3]] + [0, 0]
        out += b(1600 * group[0] + 40 * group[1] + group[2] + 1, 16)
    return out


# ---------------------------------------------------------------- the artefacts
TDT = os.path.join(REPO, "web_server", "src", "tdt")
schema = json.load(open(os.path.join(TDT, "TDT-JSON-Schema.json")))
manifest = json.load(open(os.path.join(TDT, "manifest.json")))
invalid = []
for entry in manifest["definitionFiles"]:
    try:
        jsonschema.validate(json.load(open(os.path.join(TDT, entry["file"]))), schema)
    except jsonschema.ValidationError as e:
        invalid.append(f'{entry["file"]}: {e.message}')
check(f"the {len(manifest['definitionFiles'])} TDT definition files of the manifest are valid against TDT-JSON-Schema.json",
      not invalid, invalid)
table_b = json.load(open(os.path.join(TDT, "TDT_TableB.json")))["rows"]
check("integer bits (ceiling(L*log2 10)) agree with column b of Table B",
      all(epc_binary._int_bits(int(r["a"])) == int(r["b"]) for r in table_b), table_b[:3])

# ---------------------------------------------------------------- EPCB 1.0.0, section 4.2: the two worked examples
for segment in ("eh30164596f40c0e5cbe991a83", "exMBZFlvQMDly-mRqD"):
    d = decompress(segment)
    check(f"EPCB worked example {segment}",
          d.scheme == "SGTIN-96" and d.uri("https://example.com/") == "https://example.com/01/09528765123457/21/123456789123",
          (d.scheme, d.uri("https://example.com/")))

# ---------------------------------------------------------------- TDS 2.3 annex E.3: every scheme with a GS1 Digital Link
E3 = [
    ("SGTIN-96", "3066C4409047E140075BCD15", "/01/09506000134352/21/123456789"),
    ("SGTIN-198", "3666C4409047E159B2C2BF100000000000000000000000000000", "/01/09506000134352/21/32a%2Fb"),
    ("SGTIN+", "F73795211411234538566CB0AFC4", "/01/79521141123453/21/32a%2Fb"),
    ("DSGTIN+", "FB342CDE795211411234538566CB0AFC4", "/01/79521141123453/21/32a%2Fb?17=220630"),
    ("SGTIN++", "FD3795211411234538566CB0AFC525065F1876F0D996D800", "/01/79521141123453/21/32a%2Fb"),
    ("DSGTIN++", "FC342CDE795211411234538566CB0AFC525065F1876F0D996D80", "/01/79521141123453/21/32a%2Fb?17=220630"),
    ("SSCC-96", "311BA1B300CE0A6A83000000", "/00/095201234567891235"),
    ("SSCC+", "F90095201234567891235", "/00/095201234567891235"),
    ("SGLN-96", "3276451FD46072000000162E", "/414/9521141123454/254/5678"),
    ("SGLN-195", "3976451FD46072CD9615F8800000000000000000000000000000", "/414/9521141123454/254/32a%2Fb"),
    ("SGLN+", "F2395211411234548566CB0AFC4", "/414/9521141123454/254/32a%2Fb"),
    ("SGLN++", "E9395211411234548566CB0AFC525065F1876F0D996D8000", "/414/9521141123454/254/32a%2Fb"),
    ("GRAI-96", "3376451FD40C0E400000162E", "/8003/095211411234545678"),
    ("GRAI-170", "3776451FD40C0E59B2C2BF1000000000000000000000", "/8003/0952114112345432a%2Fb"),
    ("GRAI+", "F13095211411234548566CB0AFC4", "/8003/0952114112345432a%2Fb"),
    ("GRAI++", "EB3095211411234548566CB0AFC525065F1876F0D996D800", "/8003/0952114112345432a%2Fb"),
    ("GIAI-96", "3476451FD40000000000162E", "/8004/95211415678"),
    ("GIAI-202", "3876451FD59B2C2BF10000000000000000000000000000000000", "/8004/952114132a%2Fb"),
    ("GIAI+", "FA3952114132E83C2BF10", "/8004/952114132a%2Fb"),
    ("GIAI++", "EE3952114132E83C2BF1494197C61DBC3665B600", "/8004/952114132a%2Fb"),
    ("GSRN-96", "2D76451FD4499602D2000000", "/8018/952114112345678906"),
    ("GSRN+", "F43952114112345678906", "/8018/952114112345678906"),
    ("GSRN++", "E7395211411234567890692832F8C3B786CCB6C0", "/8018/952114112345678906"),
    ("GSRNP-96", "2E76451FD4499602D2000000", "/8017/952114112345678906"),
    ("GSRNP+", "F53952114112345678906", "/8017/952114112345678906"),
    ("GSRNP++", "E8395211411234567890692832F8C3B786CCB6C0", "/8017/952114112345678906"),
    ("GDTI-96", "2C76451FD46072000000162E", "/253/95211411234545678"),
    ("GDTI-174", "3E76451FD7039B061438997367D0C18B266D1AB66EE0", "/253/9521141987650ABCDefgh012345678"),
    ("GDTI+", "F6395211411234540458B8", "/253/95211411234545678"),
    ("GDTI++", "EA395211411234540458BA4A0CBE30EDE1B32DB0", "/253/95211411234545678"),
    ("CPI-96", "3C76451FD400C0E680003039", "/8010/952114198765/8011/12345"),
    ("CPI-var", "3D76451FD75411DEF6B4CC00000003039000", "/8010/95211415PQ7%2FZ43/8011/12345"),
    ("CPI+", "F0395211415E87A145BAFB4D19A8C0E4", "/8010/95211415PQ7%2FZ43/8011/12345"),
    ("CPI++", "E6395211415E87A145BAFB4D19A8C0E64A0CBE30EDE1B32DB000", "/8010/95211415PQ7%2FZ43/8011/12345"),
    ("SGCN-96", "3F76451FD612640000019907", "/255/952114167890904711"),
    ("SGCN+", "F839521141678909509338", "/255/952114167890904711"),
    ("SGCN++", "EC3952114167890950933C94197C61DBC3665B60", "/255/952114167890904711"),
    ("ITIP-110", "4076451FD40C0E40820000000F54", "/8006/095211411234540102/21/981"),
    ("ITIP-212", "4176451FD40C0E4082DBDD8B36600000000000000000000000000000", "/8006/095211411234540102/21/mw133"),
    ("ITIP+", "F3309521141123454010266AE27FDF35", "/8006/095211411234540102/21/rif981"),
]
for scheme, hexadecimal, expected in E3:
    try:
        d = decompress("eh" + hexadecimal.lower())
        result = (d.scheme, d.path() + ("?" + d.query() if d.query() else ""))
    except EpcDecodeError as e:
        result = ("error", str(e))
    check(f"TDS annex E.3 {scheme}", result == (scheme, expected), result)
    if scheme.endswith("++"):
        check(f"…its hostname is decoded (and not used): {scheme}", d.hostname == "id.example.com", d.hostname)

# Erratum candidate E9: the SSCC++ and ITIP++ examples of annex E.3 carry the '+' headers F9 and F3; with
# the '++' headers of Table 14-1 (EF, ED) the same bits decode to the URIs the annex shows.
for scheme, printed, header, expected in [
        ("SSCC++", "F9009520123456789123592832F8C3B786CCB6C0", "ef", "/00/095201234567891235"),
        ("ITIP++", "F3309521141123454010266AE27FDF3592832F8C3B786CCB6C00", "ed", "/8006/095211411234540102/21/rif981")]:
    check(f"TDS annex E.3 {scheme} as printed (header {printed[:2]}) is refused", refused("eh" + printed.lower()) is not None)
    d = decompress("eh" + header + printed[2:].lower())
    check(f"TDS annex E.3 {scheme} with header {header.upper()}", (d.scheme, d.path(), d.hostname) == (scheme, expected, "id.example.com"),
          (d.scheme, d.path(), d.hostname))

# The same bits as 'ex' (6 bits per character)
for scheme, hexadecimal, expected in E3:
    bits = "".join(format(int(c, 16), "04b") for c in hexadecimal)
    segment = ex(bits)
    check(f"'ex' form of {scheme}", decoded(segment) == expected, decoded(segment))

# Schemes without a GS1 Digital Link equivalent
for scheme, hexadecimal in [("GID-96", "3500E86F8000A9E000000586"), ("USDOD-96", "2F320434147455900000162E"),
                            ("ADI-var", "3B0E0CF5E76C9047759AD00373DC7602E7200")]:
    message = refused("eh" + hexadecimal.lower())
    check(f"{scheme} refused: no GS1 Digital Link equivalent", message and "no GS1 Digital Link equivalent" in message, message)

# ---------------------------------------------------------------- +AIDC data after the EPC (TDS 15.3)
G = "09506000134352"
cases = [
    ("batch is a key qualifier (path), expiry date a data attribute (query)",
     sgtin_plus(G, "S1", tail=aidc("10", alnum("ABC123", 5)) + aidc("17", date("261231"))),
     f"/01/{G}/10/ABC123/21/S1?17=261231"),
    ("variant and batch in the path in the order 22, 10, 21",
     sgtin_plus(G, "S1", tail=aidc("10", alnum("L1", 5)) + aidc("22", alnum("V1", 5))),
     f"/01/{G}/22/V1/10/L1/21/S1"),
    ("a 7-bit batch with '/' is percent-encoded",
     sgtin_plus(G, "S1", tail=aidc("10", alnum("A/B", 5))), f"/01/{G}/10/A%2FB/21/S1"),
    ("numeric batch (integer encoding, leading zeros kept)",
     sgtin_plus(G, "S1", tail=aidc("10", alnum("00123", 5))), f"/01/{G}/10/00123/21/S1"),
    ("date and time of production (8008), variable precision YYMMDDhhmm",
     sgtin_plus(G, "S1", tail=aidc("8008", "01" + date("260115") + b(14, 5) + b(30, 6))),
     f"/01/{G}/21/S1?8008=2601151430"),
    ("harvest date range (7007)",
     sgtin_plus(G, "S1", tail=aidc("7007", "1" + date("260101") + date("260131"))),
     f"/01/{G}/21/S1?7007=260101260131"),
    ("net weight (3103), fixed-bit-length numeric",
     sgtin_plus(G, "S1", tail=aidc("3103", b(1250, 20))), f"/01/{G}/21/S1?3103=001250"),
    ("maximum temperature (4330) with its optional minus sign",
     sgtin_plus(G, "S1", tail=aidc("4330", b(1850, 20) + "1")), f"/01/{G}/21/S1?4330=001850-"),
    ("country of origin (422 is numeric) and of processing (4307 is alpha-2)",
     sgtin_plus(G, "S1", tail=aidc("4307", b(B64.index("B"), 6) + b(B64.index("R"), 6))), f"/01/{G}/21/S1?4307=BR"),
    ("an SSCC (header 00000000) after the EPC",
     sgtin_plus(G, "S1", tail=aidc("00", nibbles("095060001343520001"))), f"/01/{G}/21/S1?00=095060001343520001"),
    ("a toggle bit of 0 does not hide +AIDC data",
     sgtin_plus(G, "S1", toggle="0", tail=aidc("17", date("261231"))), f"/01/{G}/21/S1?17=261231"),
    ("DSGTIN+ with a best-before date and a batch",
     "11111011" + "1" + "011" + "0010" + date("270101") + nibbles(G) + alnum("S1", 5) + aidc("10", alnum("L9", 5)),
     f"/01/{G}/10/L9/21/S1?15=270101"),
    ("GIAI+ with an alphanumeric remainder after the delimiter",
     "11111010" + "0" + "000" + nibbles("9506000") + "1110" + alnum("A-1", 5), "/8004/9506000A-1"),
]
for name, bits, expected in cases:
    for form in (eh, ex):
        try:
            result = decoded(form(bits))
        except EpcDecodeError as e:
            result = f"error: {e}"
        check(f"+AIDC {name} ({form.__name__})", result == expected, result)

# ---------------------------------------------------------------- '++' hostnames (TDS 14.5.16)
for name, host_bits, expected in [
        ("URN Code 40", "0" + b(14, 6) + urn40("ID.EXAMPLE.ORG"), "id.example.org"),
        ("7-bit ASCII without optimisation", "1" + b(7, 6) + "".join(b(ord(c), 7) for c in "a-b.c_d"), "a-b.c_d"),
        ("'qr.', '.com.br' (Table B3) and '.br' (Table B1)",
         "1" + b(1 + 4 + 2, 6) + b(0b0011110, 7) + "".join(b(ord(c), 7) for c in "loja") + "0000010" + b(6, 7), "qr.loja.com.br"),
        ("'www.' and '.de' (Table B1)", "1" + b(1 + 3 + 2, 6) + b(0b0011111, 7) + "".join(b(ord(c), 7) for c in "abc")
         + "0000000" + b(0b0110111, 7), "www.abc.de"),
        ("'.tech' (Table B4)", "1" + b(1 + 2, 6) + b(ord("x"), 7) + "0000011" + "0000000", "x.tech")]:
    bits = "11111101" + "0" + "011" + nibbles(G) + alnum("S1", 5) + host_bits
    d = decompress(eh(bits))
    check(f"SGTIN++ hostname, {name}", (d.hostname, d.path()) == (expected, f"/01/{G}/21/S1"), (d.hostname, d.path()))
d = decompress(eh("11111101" + "1" + "011" + nibbles(G) + alnum("S1", 5) + "0" + b(3, 6) + urn40("A.B")
                  + aidc("17", date("261231"))))
check("SGTIN++ with +AIDC data after the hostname", (d.hostname, d.query()) == ("a.b", "17=261231"), (d.hostname, d.query()))

# ---------------------------------------------------------------- strings that do not decode
for segment, why in [
        ("eh", "no EPC binary string"), ("ex", "no EPC binary string"), ("eh3", "shorter than a header"),
        ("eh00" + "0" * 22, "header 00 (unprogrammed tag)"), ("ehe2" + "0" * 22, "header E2 (reserved, TID)"),
        ("ehfe" + "0" * 22, "header FE (reserved)"), ("eh3016", "SGTIN-96 cut short"),
        ("eh30164596f40c0e5cbe991a830001", "data after the end of an SGTIN-96"),
        (eh("00110000" + "011" + "111" + "0" * 86), "GCP partition value 7 (reserved)"),
        (eh(sgtin_plus(G, "S1", tail=nibbles("A0") + "1" * 8)), "+AIDC data header A0 (special/reserved)"),
        (eh(sgtin_plus(G, "S1", tail=aidc("14", "0" * 16))), "no AI begins with 14"),
        (eh(sgtin_plus(G, "S1", tail=aidc("21", alnum("S2", 5)))), "the serial number repeated in the +AIDC data"),
        (eh(sgtin_plus(G, "S1", tail=aidc("17", b(26, 7) + b(2, 4) + b(30, 5)))), "30 February"),
        (eh(sgtin_plus(G, "S1", tail=aidc("10", "110" + b(2, 5) + "0" * 12))), "encoding indicator 6 (reserved)"),
        (eh(sgtin_plus(G, "S1", tail=aidc("10", "011" + b(20, 5) + alnum("ABCDEF", 5)[8:]))), "a batch shorter than its length indicator"),
        (eh("11111011" + "0" + "011" + "0111" + date("270101") + nibbles(G) + alnum("S1", 5)), "date type 0111 (reserved)"),
        (eh("11110111" + "0" + "011" + nibbles("0950600013435A") + alnum("S1", 5)), "a GTIN nibble above 9"),
        ("ex" + "A" * 16, "header 00 in base 64"),
        ("ehZZ", "upper case is not RE3"), ("EH30164596f40c0e5cbe991a83", "upper-case prefix"), ("ex+/", "not base 64 URL")]:
    message = refused(segment)
    check(f"refused: {why} ({segment[:24]}{'…' if len(segment) > 24 else ''})", message is not None, message)

# ---------------------------------------------------------------- RE3 (URI Syntax 1.7, 6.1.2)
for segment, expected in [("eh30", True), ("exMB", True), ("eh", True), ("eh3G", False), ("EH30", False),
                          ("ex=", False), ("01", False), ("exMB-_", True)]:
    check(f"RE3 {'matches' if expected else 'does not match'} {segment}",
          bool(epc_binary.COMPRESSED_EPC.fullmatch(segment)) == expected)

# ---------------------------------------------------------------- independent oracle (optional)
ORACLE = r"""
const tds = require("epc-tds");
let seed = 20261002;
const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return Math.floor(seed / 65536) % k; };
const digits = (k) => Array.from({length: k}, () => rnd(10)).join("");
const SET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz";
const text = (k) => Array.from({length: k}, () => SET82[rnd(SET82.length)]).join("");
const enc = (v) => encodeURIComponent(v).replace(/[!'()*]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase());
const out = [];
for (let i = 0; i < 100; i++) {
  const p = rnd(7);
  let e = new tds.Sgtin96().setFilter(rnd(8)).setPartition(p).setGtin(digits(13) + "0").setSerial(rnd(2 ** 30));
  out.push(["SGTIN-96", e.toHexString(), `/01/${e.getGtin()}/21/${e.getSerial()}`]);
  e = new tds.Sgtin198().setFilter(rnd(8)).setPartition(p).setGtin(digits(13) + "0").setSerial(text(1 + rnd(20)));
  out.push(["SGTIN-198", e.toHexString(), `/01/${e.getGtin()}/21/${enc(e.getSerial())}`]);
  e = new tds.Sscc96().setFilter(rnd(8)).setPartition(p).setSscc(digits(17) + "0");
  out.push(["SSCC-96", e.toHexString(), `/00/${e.getSscc()}`]);
  e = new tds.Sgln96().setFilter(rnd(8)).setPartition(p).setGln(digits(12) + "0").setExtension(rnd(2 ** 30));
  out.push(["SGLN-96", e.toHexString(), `/414/${e.getGln()}` + (e.getExtension() == "0" ? "" : `/254/${e.getExtension()}`)]);
  e = new tds.Grai96().setFilter(rnd(8)).setPartition(p).setGrai("0" + digits(12) + "0" + (1 + rnd(9)) + digits(5));
  out.push(["GRAI-96", e.toHexString(), `/8003/0${e.getGrai()}`]);     // epc-tds leaves out the filler zero of (8003)
  e = new tds.Giai96().setFilter(rnd(8)).setPartition(p).setGiai(digits(12) + String(1 + rnd(9)) + digits(4));
  out.push(["GIAI-96", e.toHexString(), `/8004/${e.getGiai()}`]);
  e = new tds.Gsrn96().setFilter(rnd(8)).setPartition(p).setGsrn(digits(17) + "0");
  out.push(["GSRN-96", e.toHexString(), `/8018/${e.getGsrn()}`]);
  e = new tds.Gdti96().setFilter(rnd(8)).setPartition(p).setGdti(digits(12) + "0" + (1 + rnd(9)) + digits(5));
  out.push(["GDTI-96", e.toHexString(), `/253/${e.getGdti()}`]);
}
console.log(JSON.stringify(out));
"""
EPC_TDS = os.environ.get("EPC_TDS")
if EPC_TDS:
    rows = json.loads(subprocess.run(["node", "-e", ORACLE], cwd=EPC_TDS, capture_output=True, text=True, check=True).stdout)
    wrong = []
    for scheme, hexadecimal, expected in rows:
        try:
            d = decompress("eh" + hexadecimal.lower())
            if (d.scheme, d.path()) != (scheme, expected):
                wrong.append((scheme, hexadecimal, expected, d.path()))
        except EpcDecodeError as e:
            wrong.append((scheme, hexadecimal, expected, str(e)))
    check(f"{len(rows)} random EPCs of 8 classic schemes agree with epc-tds", not wrong, wrong[:3])
else:
    print("SKIP comparison with epc-tds (set EPC_TDS to a directory where 'npm install epc-tds' was run)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
