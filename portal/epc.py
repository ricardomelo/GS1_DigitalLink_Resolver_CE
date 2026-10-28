"""
The EPC of a record for RFID and NFC tags (the backlog's "EPC/NFC label option", item 9.10;
Documentation/adr/0010-label-studio.md, section 8): every key the EPC Tag Data Standard encodes in a scheme defined
before TDS 2.0 — SGTIN, SSCC, SGLN, GRAI, GIAI, GSRN, GSRNP, GDTI, SGCN, CPI, ITIP — as its binary string (hexadecimal
and base 64), tag URI and pure identity URI, and as the compressed GS1 Digital Link URI an NFC tag emits (GS1 Digital
Link URI: Compression Technical Standard for EPC binary strings 1.0.0: https://<stem>/eh<hexadecimal> or
/ex<base 64>), which the resolver decompresses (item 1.6, web_server/src/epc_binary.py).

The encoding follows the EPC Tag Data Translation artefacts (epc_schemes.json, generated from the resolver's copy by
tools/gen_epc_schemes.py): the record's GS1 Digital Link path is matched by the scheme's GS1_DIGITAL_LINK level for the
company prefix's length, the level's EXTRACT rules give the EPC's fields, and the BINARY, TAG_ENCODING and
PURE_IDENTITY levels write them out (TDT 3.x). For each key the schemes are tried in order — the 96-bit one first, then
the longer one that takes alphanumeric values — and the first whose rules accept the values is used.

The partition of the GS1 Company Prefix needs its length, which the key does not say: the caller gives it (the
person's choice, GS1's GCP length table, the organisation's prefix).
"""
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import unquote

SCHEMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "epc_schemes.json")
# The schemes of each primary key, in the order they are tried (GDTI-113 left out: TDS 2.0 deprecates it)
KEY_SCHEMES = {
    "01": ("SGTIN-96", "SGTIN-198"), "00": ("SSCC-96",), "414": ("SGLN-96", "SGLN-195"),
    "8003": ("GRAI-96", "GRAI-170"), "8004": ("GIAI-96", "GIAI-202"), "8018": ("GSRN-96",), "8017": ("GSRNP-96",),
    "253": ("GDTI-96", "GDTI-174"), "255": ("SGCN-96",), "8010": ("CPI-96", "CPI-var"), "8006": ("ITIP-110", "ITIP-212"),
}
# What a record needs before its key has an EPC: a key qualifier, or a serial component after the key's fixed digits
# (GRAI: 14 digits, GDTI and GCN: 13); a GLN without extension is encoded with the extension 0 (TDS 6.3.3).
MINIMUM = {"01": {"qualifier": "21"}, "8006": {"qualifier": "21"}, "8010": {"qualifier": "8011"},
           "8003": {"serialAfter": 14}, "253": {"serialAfter": 13}, "255": {"serialAfter": 13}}
# Key qualifiers that are part of an EPC (the others — a batch, a variant — are not)
EPC_QUALIFIERS = ("21", "254", "8011")
PARTITION_LENGTHS = range(6, 13)
SERIAL_96_LIMIT = 2 ** 38
# GS1 AI encodable character set 82
CSET_82 = set('!"%&\'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz')
BASE64_URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# TDS section 7 (Table I.3.1-1): characters escaped in the strings of an EPC URI ('#' only occurs in a CPI)
_URN_ESCAPES = {'"': "%22", "#": "%23", "%": "%25", "&": "%26", "/": "%2F", "<": "%3C", ">": "%3E", "?": "%3F"}
# Characters a GS1 Digital Link path keeps as they are in the TDT artefacts' patterns; the others are %-escaped
_URL_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\"._-")


class EpcError(ValueError):
    """The record cannot be written as an EPC; code is a message code of the portal."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


@dataclass
class Epc:
    scheme: str                 # lower case, as in the tag URI: sgtin-96, sscc-96, …
    filter: int
    bits: str
    tag_uri: str
    pure_identity: str

    @property
    def hex(self) -> str:
        """The tag's EPC bank as an RFID encoder writes it: the bits padded with zeros to a whole 16-bit word (TDS
        2.3: the PC bits' length counts words), so an SGTIN-198 is 52 digits; 96-bit schemes are unchanged."""
        return _hex(self.bits, 16)

    @property
    def link_hex(self) -> str:
        """The hexadecimal of the compressed link (/eh…): the bits padded only to a whole digit (EPCB 4.2.1)."""
        return _hex(self.bits, 4)

    @property
    def base64(self) -> str:
        bits = self.bits + "0" * (-len(self.bits) % 6)
        return "".join(BASE64_URL[int(bits[i:i + 6], 2)] for i in range(0, len(bits), 6))


Sgtin = Epc                     # the name of item 1.x's single scheme


def _hex(bits: str, multiple: int) -> str:
    bits += "0" * (-len(bits) % multiple)
    return format(int(bits, 2), f"0{len(bits) // 4}x")


# ------------------------------------------------------------------------------------------------- TDT artefacts
@lru_cache(maxsize=1)
def schemes() -> dict[str, dict]:
    """The TDT definitions the encoder reads, by scheme name."""
    with open(SCHEMES_FILE, encoding="utf-8") as fh:
        return {s["name"]: s for s in json.load(fh)["schemes"]}


def _option(level: dict, key: str) -> dict | None:
    return next((o for o in level["options"] if o["optionKey"] == key), None)


def _tokens(grammar: str) -> list[tuple[bool, str]]:
    """(is_literal, text) for each token of a TDT grammar ('literal' or field name)."""
    return [(token.startswith("'"), token[1:-1] if token.startswith("'") else token)
            for token in re.findall(r"'[^']*'|\S+", grammar)]


def _checksum(digits: str) -> str:
    return str((10 - sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits))) % 10) % 10)


def urn_escape(text: str) -> str:
    return "".join(_URN_ESCAPES.get(c, c) for c in text)


def url_escape(text: str) -> str:
    return "".join(c if c in _URL_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in text)


def _call(function: str, values: dict[str, str]) -> str:
    """The functions of the artefacts' rules (TDT Table 3-3)."""
    name, raw = re.fullmatch(r"(\w+)\((.*)\)", function.strip()).groups()

    def arg(token: str) -> str:
        token = token.strip()
        if token in values:
            return values[token]
        if token.startswith("'") and token.endswith("'"):
            return token[1:-1]
        if token.isdigit():
            return token
        raise EpcError("epc.notEncodable")
    args = [arg(a) for a in raw.split(",")]
    if name == "SUBSTR":
        start = int(args[1])
        return args[0][start:start + int(args[2])] if len(args) > 2 else args[0][start:]
    if name == "CONCAT":
        return "".join(args)
    if name == "GS1CHECKSUM":
        return _checksum(args[0])
    if name == "URLENCODE":
        return url_escape(args[0])
    if name == "URLDECODE":
        return unquote(args[0])
    if name == "URNENCODE":
        return urn_escape(args[0])
    if name == "URNDECODE":
        return unquote(args[0])
    raise EpcError("epc.notEncodable")


def _run(level: dict, kind: str, values: dict[str, str]) -> None:
    for rule in sorted((r for r in level["rules"] if r["type"] == kind), key=lambda r: int(r["seq"])):
        values[rule["newFieldName"]] = _call(rule["function"], values)


def _characters(text: str, compaction: str) -> str | None:
    """A string compacted at 6 or 7 bits per character (TDT 3.13), or None when a character does not fit."""
    if compaction == "7-bit":
        return "".join(format(ord(c), "07b") for c in text) if all(c in CSET_82 for c in text) else None
    if compaction == "6-bit":                     # TDS 14.3.6: the characters 0x20 to 0x5F, written as their low 6 bits
        if not all(0x20 <= ord(c) <= 0x5F for c in text):
            return None
        return "".join(format(ord(c) & 0x3F, "06b") for c in text)
    return None


def _binary(option: dict, values: dict[str, str]) -> str | None:
    """The BINARY grammar filled in, or None when a value does not fit its field."""
    fields = {f["name"]: f for f in option["fields"]}
    bits = ""
    for literal, token in _tokens(option["grammar"]):
        if literal:
            bits += token
            continue
        spec, value = fields[token], values.get(token, "")
        length = int(spec["bitLength"]) if spec.get("bitLength") else None
        if spec.get("compaction"):
            part = _characters(value, spec["compaction"])
            if part is None or not value or (length is not None and len(part) > length):
                return None
            bits += part.ljust(length, "0") if length else part
            continue
        if value and not value.isdigit():
            return None
        # a number without a fixed width (a serial of a 96-bit scheme) is written without leading zeros (TDS 14.3.2):
        # "012" goes to the longer scheme, which keeps it as characters
        if value and not spec.get("length") and value != str(int(value)):
            return None
        number = int(value or "0")
        if not int(spec.get("decimalMinimum", 0)) <= number <= int(spec.get("decimalMaximum", 2 ** length - 1)) \
                or number >= 2 ** length:
            return None
        bits += format(number, f"0{length}b")
    return bits if re.match(option["pattern"], bits) else None


def _text(level: dict, key: str, values: dict[str, str]) -> str | None:
    """A TAG_ENCODING or PURE_IDENTITY URI: the level's FORMAT rules, then its grammar, numbers padded as its fields say;
    None unless the level's own pattern accepts it."""
    option = _option(level, key)
    values = dict(values)
    _run(level, "FORMAT", values)
    fields = {f["name"]: f for f in option["fields"]}
    out = ""
    for literal, token in _tokens(option["grammar"]):
        if literal:
            out += token
            continue
        value, spec = values.get(token, ""), fields.get(token, {})
        if spec.get("padChar") and spec.get("length") and int(spec["length"]):
            value = value.rjust(int(spec["length"]), spec["padChar"]) if spec.get("padDir") == "LEFT" else value
        out += value
    return out if re.match(option["pattern"], out) else None


def path_of(ai: str, value: str, qualifiers: dict[str, str]) -> str:
    """The GS1 Digital Link path the artefacts read: the key and the qualifiers that are part of an EPC."""
    path = f"/{ai}/{url_escape(value)}"
    for q in EPC_QUALIFIERS:
        if qualifiers.get(q):
            path += f"/{q}/{url_escape(qualifiers[q])}"
    if ai == "414" and not qualifiers.get("254"):
        path += "/254/0"                          # a GLN without extension: the extension 0 (TDS 6.3.3)
    return path


def missing(ai: str, value: str, qualifiers: dict[str, str]) -> dict | None:
    """What the record lacks before its key has an EPC ({"qualifier": "21"} or {"serialAfter": 14}), or None."""
    rule = MINIMUM.get(ai) or {}
    if rule.get("qualifier") and not qualifiers.get(rule["qualifier"]):
        return {"qualifier": rule["qualifier"]}
    if rule.get("serialAfter") and len(value) <= rule["serialAfter"]:
        return {"serialAfter": rule["serialAfter"]}
    return None


def encode(ai: str, value: str, qualifiers: dict[str, str], prefix_length: int, filter_value: int = 1) -> Epc:
    """The EPC of a key (and its EPC qualifiers) with a company prefix of prefix_length digits."""
    if ai not in KEY_SCHEMES:
        raise EpcError("epc.unsupported", key=ai)
    if prefix_length not in PARTITION_LENGTHS:
        raise EpcError("epc.prefixLength")
    if not isinstance(filter_value, int) or not 0 <= filter_value <= 7:
        raise EpcError("epc.filterInvalid")
    need = missing(ai, value, qualifiers)
    if need:
        raise EpcError("epc.needsQualifier" if "qualifier" in need else "epc.needsSerial", **need)
    path = path_of(ai, value, qualifiers)
    key = str(prefix_length)
    for name in KEY_SCHEMES[ai]:
        scheme = schemes()[name]
        levels = scheme["levels"]
        link = levels["GS1_DIGITAL_LINK"]
        option = _option(link, key)
        match = re.match(option["pattern"], path) if option else None
        if not match:
            continue
        values = {"gs1companyprefixlength": key, "filter": str(filter_value), "tagLength": str(scheme["tagLength"] or "")}
        for spec in option["fields"]:
            values[spec["name"]] = match.group(int(spec["seq"])) or ""
        try:
            _run(link, "EXTRACT", values)
            binary = levels["BINARY"]
            _run(binary, "FORMAT", values)
            bits = _binary(_option(binary, key), values)
            if bits is None:
                continue
            tag_uri = _text(levels["TAG_ENCODING"], key, values)
            pure = _text(levels["PURE_IDENTITY"], key, values)
            if not (tag_uri and pure):
                continue
        except (EpcError, ValueError, KeyError, IndexError):
            continue
        return Epc(name.lower(), filter_value, bits, tag_uri, pure)
    raise EpcError("epc.notEncodable", key=ai)


def sgtin(gtin14: str, serial: str, prefix_length: int, filter_value: int = 1) -> Epc:
    """The SGTIN of a GTIN-14 and a serial number (AI 21) with a company prefix of prefix_length digits."""
    if len(gtin14) != 14 or not gtin14.isdigit():
        raise EpcError("epc.gtin")
    if prefix_length not in PARTITION_LENGTHS:
        raise EpcError("epc.prefixLength")
    if not 0 <= filter_value <= 7:
        raise EpcError("epc.filterInvalid")
    if not serial or len(serial) > 20 or any(c not in CSET_82 for c in serial):
        raise EpcError("epc.serial")
    return encode("01", gtin14, {"21": serial}, prefix_length, filter_value)


def prefix_length_for(gtin14: str, prefixes) -> int | None:
    """The length of the longest of the given GS1 Company Prefixes (6 to 12 digits) the GTIN's company part starts
    with, or None."""
    return prefix_length_of(gtin14[1:], prefixes)


def prefix_length_of(company_part: str, prefixes) -> int | None:
    """The length of the longest of the given GS1 Company Prefixes (6 to 12 digits) a key's company part starts with."""
    lengths = [len(p) for p in prefixes or [] if 6 <= len(p) <= 12 and company_part.startswith(p)]
    return max(lengths) if lengths else None
