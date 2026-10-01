"""
GS1 rules used by the portal: validation of every primary identification key of GS1 Digital Link URI
Syntax 1.7 (section 4.3, PRIMARY_KEYS) and of their key qualifiers (sections 4.4, 4.6 and 4.9, KEY_SHAPES),
the GS1 Company Prefix of an identifier (governance), clean-up of free text and target addresses, the
supported link types (a subset of the GS1 Web Vocabulary), languages, and construction of the GS1 Digital
Link URI. The rules mirror the GS1 Barcode Syntax Engine; dev-tests/portal/test_keys.py compares them.

Validation failures raise ValidationError with a message *code* and parameters rather than
a sentence. The browser turns the code into text in the user's language (see static/i18n.js),
so this module stays language-neutral.
"""
import re
import unicodedata
from urllib.parse import quote, urlparse


class ValidationError(Exception):
    """User input error. `code` is a key in the front-end message catalogue."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


# ---------------------------------------------------------------------------
# Supported link types: (CURIE, catalogue group, default title).
# The default title is the GS1 Web Vocabulary title and is stored in the resolver only when
# the user leaves the title blank. Display labels and help text live in static/i18n.js.
# To offer another link type, add a row here and its labels to every locale in i18n.js.
# ---------------------------------------------------------------------------
LINK_TYPES = [
    ("gs1:pip", "common", "Product information page"),
    ("gs1:instructions", "common", "Instructions"),
    ("gs1:support", "common", "Support"),
    ("gs1:certificationInfo", "common", "Certification information"),
    ("gs1:safetyInfo", "common", "Safety information"),
    ("gs1:epil", "health", "Electronic patient information leaflet"),
    ("gs1:smpc", "health", "Summary of product characteristics"),
    ("gs1:recallStatus", "health", "Recall status"),
    ("gs1:quickStartGuide", "aftersales", "Quick start guide"),
    ("gs1:tutorial", "aftersales", "Tutorial"),
    ("gs1:relatedVideo", "aftersales", "Related video"),
    ("gs1:serviceInfo", "aftersales", "Service information"),
    ("gs1:whatsInTheBox", "aftersales", "What's in the box"),
    ("gs1:faqs", "aftersales", "Frequently asked questions"),
    ("gs1:registerProduct", "aftersales", "Register product"),
    ("gs1:purchaseSuppliesOrAccessories", "aftersales", "Purchase supplies or accessories"),
    ("gs1:promotion", "consumer", "Promotion"),
    ("gs1:hasRetailers", "consumer", "Where to buy"),
    ("gs1:review", "consumer", "Reviews"),
    ("gs1:leaveReview", "consumer", "Leave a review"),
    ("gs1:socialMedia", "consumer", "Social media"),
    ("gs1:sustainabilityInfo", "consumer", "Sustainability and recycling"),
    ("gs1:nutritionalInfo", "food", "Nutritional information"),
    ("gs1:ingredientsInfo", "food", "Ingredients information"),
    ("gs1:allergenInfo", "food", "Allergen information"),
    ("gs1:recipeInfo", "food", "Recipes"),
    ("gs1:masterData", "b2b", "Master data"),
    ("gs1:traceability", "b2b", "Traceability information"),
    ("gs1:epcis", "b2b", "EPCIS repository"),
]
LINK_TYPE_CODES = {code for code, _, _ in LINK_TYPES}
LINK_TYPE_DEFAULT_TITLES = {code: title for code, _, title in LINK_TYPES}

# BCP 47 language tags offered in the editor's menu (names are rendered by the browser). Any other
# well-formed tag (pt-BR, en-US, vi, …) is accepted too: records created with other tools use them.
LANGUAGES = ["pt", "en", "es", "fr", "de", "it", "zh", "ja"]
LANGUAGE_CODES = set(LANGUAGES)
# language [-script] [-region] [-variants], or "und" (undetermined)
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-(?:[A-Za-z]{2}|\d{3}))?(-(?:[A-Za-z0-9]{5,8}|\d[A-Za-z0-9]{3}))*$",
                           re.ASCII)


def normalise_language(tag: str) -> str | None:
    """Well-formed BCP 47 tag in canonical case ("pt-br" → "pt-BR"), or None."""
    tag = without_invisible(tag).strip().replace("_", "-")
    if not _LANGUAGE_TAG.match(tag):
        return None
    parts = tag.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            out.append(part.title())          # script: Latn
        elif len(part) == 2 and part.isalpha():
            out.append(part.upper())          # region: BR
        else:
            out.append(part.lower())
    return "-".join(out)

MAX_DESCRIPTION = 200

_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf", ".json": "application/json", ".jsonld": "application/ld+json",
    ".xml": "application/xml", ".mp4": "video/mp4", ".webm": "video/webm",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
}

# --------------------------------------------------------------------------- special characters
# Identifiers are ASCII: GS1 keys and qualifiers only use digits, letters and a few symbols. Python's
# str.isdigit() and the regular expression \d also accept other scripts' digits (full-width "７",
# Arabic-Indic "٧", superscript "²"), which would be stored as they are or fail int(); every check below
# is therefore ASCII-only. Invisible characters that come with text copied from web pages, PDFs and
# spreadsheets (zero-width space, word joiner, byte order mark, soft hyphen, direction marks) are removed
# from identifiers before they are checked. Free text (descriptions, titles) keeps any character but is
# stored in Unicode normal form C, with control characters and line breaks turned into spaces.
_INVISIBLE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def without_invisible(text) -> str:
    """Text without invisible characters (zero-width space, joiners, BOM, soft hyphen, direction marks)."""
    return _INVISIBLE.sub("", str(text or ""))


def ascii_digits(value: str) -> bool:
    """Whether the value has ASCII digits only (str.isdigit alone also accepts other scripts' digits)."""
    return value.isascii() and value.isdigit()


def clean_text(text) -> str:
    """Free text as stored: NFC, control characters and line breaks as single spaces, trimmed."""
    text = _CONTROL.sub(" ", unicodedata.normalize("NFC", str(text or "")))
    return re.sub(r" {2,}", " ", text).strip()


def gtin_check_digit(body: str) -> int:
    """GS1 modulo-10 check digit for the digits preceding it."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def normalise_gtin(raw: str) -> str:
    """Validates a GTIN-8/12/13/14 and returns it as GTIN-14."""
    digits = re.sub(r"[\s.\-]", "", without_invisible(raw))
    if not digits:
        raise ValidationError("gtin.required")
    if not ascii_digits(digits):
        raise ValidationError("gtin.digitsOnly")
    if len(digits) not in (8, 12, 13, 14):
        raise ValidationError("gtin.length", length=len(digits))
    expected = gtin_check_digit(digits[:-1])
    if int(digits[-1]) != expected:
        raise ValidationError("gtin.checkDigit", expected=expected)
    if len(digits) == 13 and digits[0] == "2":
        raise ValidationError("gtin.restricted")   # restricted circulation number (in-store use)
    return digits.zfill(14)




# --------------------------------------------------------------------------- primary identification keys
# GS1 Digital Link URI Syntax 1.7, section 4.3, with the value formats of section 4.5 and the checks of
# the GS1 General Specifications as applied by the GS1 Barcode Syntax Engine (the library the resolver
# uses to validate every request): check digits, GMN check-character pair, GS1 Company Prefix at the
# start of alphanumeric keys, ITIP piece/total, GRAI filler zero.
#
# Key qualifiers (section 4.4) and the paths of section 4.9 are described by KEY_SHAPES below.
#
# Alphanumeric values use a conservative subset of the 82-character set: letters, digits, full stop and
# hyphen. "_" is excluded because the data entry service turns "/" into "_" in document ids, and the
# other symbols would need percent-encoding in the URI.

_CSET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
_CSET32 = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
_ALNUM = re.compile(r"^[A-Za-z0-9.\-]+$")
_CPID_CHARS = re.compile(r"^[0-9A-Z\-]+$")


def gmn_check_pair(body: str) -> str:
    """GS1 check-character pair for a Global Model Number (GS1 General Specifications 7.9.6)."""
    total = sum(_CSET82.index(c) * _PRIMES[len(body) - 1 - i] for i, c in enumerate(body)) % 1021
    return _CSET32[total >> 5] + _CSET32[total & 31]


def _digits(value: str, length: int) -> None:
    """Raises ValidationError unless the value has exactly `length` ASCII digits."""
    if not ascii_digits(value):
        raise ValidationError("key.digitsOnly")
    if len(value) != length:
        raise ValidationError("key.length", expected=length, length=len(value))


def _check_digit(digits: str) -> None:
    """Raises ValidationError unless the last digit is the GS1 mod-10 check digit of the others."""
    expected = gtin_check_digit(digits[:-1])
    if int(digits[-1]) != expected:
        raise ValidationError("key.checkDigit", expected=expected)


def _alnum(value: str, maximum: int, pattern=_ALNUM, code="key.chars") -> None:
    """Common rules of alphanumeric keys: maximum length, allowed characters, GS1 Company Prefix first."""
    if len(value) > maximum:
        raise ValidationError("key.tooLong", max=maximum)
    if not pattern.match(value):
        raise ValidationError(code)
    if not ascii_digits(value[:4]) or len(value) < 4:
        raise ValidationError("key.companyPrefix")      # must start with a GS1 Company Prefix


def _numeric_key(length: int):
    """Validator of a fixed-length numeric key with a check digit (GLN, GSRN, SSCC, GSIN)."""
    def check(value: str) -> str:
        _digits(value, length)
        _check_digit(value)
        return value
    return check


def _itip(value: str) -> str:
    """ITIP (8006): GTIN-14 with its check digit, then piece and total, piece from 1 to total."""
    _digits(value, 18)
    _check_digit(value[:14])
    piece, total = int(value[14:16]), int(value[16:18])
    if piece == 0 or total == 0 or piece > total:
        raise ValidationError("key.itipPiece")
    return value


def _gmn(value: str) -> str:
    """GMN (8013): alphanumeric with the check-character pair of the GS1 General Specifications."""
    _alnum(value, 25)
    if len(value) < 3:
        raise ValidationError("key.gmnPair", expected="")
    expected = gmn_check_pair(value[:-2])
    if value[-2:] != expected:
        raise ValidationError("key.gmnPair", expected=expected)
    return value


def _cpid(value: str) -> str:
    """CPID (8010): digits, capital letters and '-' after a GS1 Company Prefix (the portal leaves out the
    '#' and '/' of character set 39)."""
    _alnum(value, 30, _CPID_CHARS, "key.cpidChars")
    return value


def _gcn(value: str) -> str:
    """GCN (255): GCN-13 with its check digit and an optional serial, 13 to 25 digits."""
    if not ascii_digits(value):
        raise ValidationError("key.digitsOnly")
    if not 13 <= len(value) <= 25:
        raise ValidationError("key.lengthRange", min=13, max=25, length=len(value))
    _check_digit(value[:13])
    return value


def _with_serial(prefix_length: int, serial_max: int, filler: str = ""):
    """13 digits with a check digit, then an optional serial (GDTI, GRAI)."""
    def check(value: str) -> str:
        """Checks a key made of a numeric base with check digit and an optional serial."""
        body = value
        if filler:
            if not value.startswith(filler):
                raise ValidationError("key.graiZero")
            body = value[len(filler):]
        base, serial = body[:prefix_length], body[prefix_length:]
        if len(base) < prefix_length or not ascii_digits(base):
            raise ValidationError("key.baseDigits", length=prefix_length)
        _check_digit(base)
        if len(serial) > serial_max:
            raise ValidationError("key.serialTooLong", max=serial_max)
        if serial and not _ALNUM.match(serial):
            raise ValidationError("key.chars")
        return value
    return check


def _alnum_key(maximum: int):
    """Validator of an alphanumeric key of up to `maximum` characters (GINC, GIAI)."""
    def check(value: str) -> str:
        _alnum(value, maximum)
        return value
    return check


def _gtin(value: str) -> str:
    """GTIN (01): any GTIN length, returned as 14 digits."""
    return normalise_gtin(value)


# code: (short name, validator)
PRIMARY_KEYS: dict[str, tuple[str, object]] = {
    "01": ("GTIN", _gtin),
    "8006": ("ITIP", _itip),
    "8013": ("GMN", _gmn),
    "8010": ("CPID", _cpid),
    "414": ("GLN", _numeric_key(13)),
    "415": ("Pay-to GLN", _numeric_key(13)),
    "417": ("Party GLN", _numeric_key(13)),
    "8017": ("GSRNP", _numeric_key(18)),
    "8018": ("GSRN", _numeric_key(18)),
    "255": ("GCN", _gcn),
    "00": ("SSCC", _numeric_key(18)),
    "253": ("GDTI", _with_serial(13, 17)),
    "401": ("GINC", _alnum_key(30)),
    "402": ("GSIN", _numeric_key(17)),
    "8003": ("GRAI", _with_serial(13, 16, filler="0")),
    "8004": ("GIAI", _alnum_key(30)),
}

# --------------------------------------------------------------------------- key qualifiers
# Section 4.4 (which AIs), 4.6 (formats) and 4.9 (path order). Each key has one or more "shapes": the
# qualifiers allowed together, in path order, and whether each is required. A record uses exactly one
# shape. Compound paths of 4.9 are shapes with a required qualifier: UPUI = 01 + 235, EOID = 417 + 7040,
# FID = 414 + 7040, MID = 8004 + 7040; 415 always needs 8020.
#
# ITIP (8006) is offered with 10 and 21 only: the grammar of 4.9 also allows 22, but the GS1 Barcode
# Syntax Engine the resolver uses refuses 22 without 01 (GS1 General Specifications association rule),
# so such a record could never be resolved.
KEY_SHAPES: dict[str, list[list[tuple[str, bool]]]] = {
    "01": [[("22", False), ("10", False), ("21", False)], [("235", True)]],
    "8006": [[("10", False), ("21", False)]],
    "8010": [[("8011", False)]],
    "414": [[("254", False)], [("7040", True)]],
    "415": [[("8020", True)]],
    "417": [[], [("7040", True)]],
    "8017": [[("8019", False)]],
    "8018": [[("8019", False)]],
    "8004": [[], [("7040", True)]],
}
QUALIFIER_ORDER = ["22", "10", "21", "235", "8011", "254", "7040", "8020", "8019"]

_QCHARS = r"[A-Za-z0-9._\-]"
QUALIFIER_FORMATS: dict[str, tuple[str, re.Pattern]] = {
    # AI: (name, pattern) — alphanumerics limited to letters, digits, ".", "_" and "-"
    "22": ("CPV", re.compile(rf"^{_QCHARS}{{1,20}}$")),
    "10": ("LOT", re.compile(rf"^{_QCHARS}{{1,20}}$")),
    "21": ("SER", re.compile(rf"^{_QCHARS}{{1,20}}$")),
    "235": ("TPX", re.compile(rf"^{_QCHARS}{{1,28}}$")),
    "8011": ("CPID SERIAL", re.compile(r"^[1-9]\d{0,11}$", re.ASCII)),          # no leading zero
    "254": ("GLN EXTENSION", re.compile(rf"^{_QCHARS}{{1,20}}$")),
    "7040": ("UIC EXT", re.compile(r"^\d[A-Za-z0-9._\-]{2}[A-Za-z0-9_\-]$", re.ASCII)),   # last: importer index
    "8020": ("REF NO", re.compile(rf"^{_QCHARS}{{1,25}}$")),
    "8019": ("SRIN", re.compile(r"^\d{1,10}$", re.ASCII)),
}


def key_qualifiers(ai: str) -> list[str]:
    """Every qualifier AI the key accepts, in path order."""
    seen = {q for shape in KEY_SHAPES.get(ai, [[]]) for q, _ in shape}
    return [q for q in QUALIFIER_ORDER if q in seen]


def normalise_qualifiers(ai: str, raw) -> list[tuple[str, str]]:
    """Validates the qualifiers of a record ({"10": "L1", …} or [("10", "L1"), …]) and returns them as
    (AI, value) pairs in path order. Empty values are ignored."""
    items = raw.items() if isinstance(raw, dict) else (raw or [])
    given: dict[str, str] = {}
    for q, value in items:
        q, value = without_invisible(q).strip("() "), without_invisible(value).strip()
        if not value:
            continue
        if q not in QUALIFIER_FORMATS or q not in key_qualifiers(ai):
            raise ValidationError("qualifier.notAllowed", ai=q, key=ai)
        if not QUALIFIER_FORMATS[q][1].match(value):
            raise ValidationError("qualifier.invalid", ai=q)
        given[q] = value
    shapes = KEY_SHAPES.get(ai, [[]])
    for shape in shapes:
        allowed = {q for q, _ in shape}
        required = {q for q, needed in shape if needed}
        if set(given) <= allowed and required <= set(given):
            return [(q, given[q]) for q, _ in shape if q in given]
    missing = [q for shape in shapes for q, needed in shape if needed and set(given) <= {x for x, _ in shape}]
    if missing:
        raise ValidationError("qualifier.required", ai=missing[0], key=ai)
    raise ValidationError("qualifier.combination", key=ai, given=" + ".join(sorted(given, key=QUALIFIER_ORDER.index)))


# GS1-Conformant Resolver 1.2.1, section 2.5.9, rule 2: with a serial number (AI 21) the variant (AI 22) and the
# batch (AI 10) of a GTIN or ITIP are not part of the registration. The portal keeps them with the serial-number
# record as information ("informativeQualifiers"): stored, searchable and printed in the QR code, never used by
# the resolver to choose a record.
INFORMATIVE_QUALIFIERS: dict[str, tuple[str, tuple[str, ...]]] = {"01": ("21", ("22", "10")), "8006": ("21", ("22", "10"))}


def split_informative(ai: str, pairs: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Splits the qualifiers of a GS1 Digital Link (path order) into the record's qualifiers and the informative
    ones: (registration pairs, informative pairs). Only a serial number of a GTIN or ITIP has informative ones."""
    rule = INFORMATIVE_QUALIFIERS.get(ai)
    if not rule or rule[0] not in {q for q, _ in pairs}:
        return list(pairs), []
    return [(q, v) for q, v in pairs if q not in rule[1]], [(q, v) for q, v in pairs if q in rule[1]]


def join_informative(pairs, informative) -> list[tuple[str, str]]:
    """The qualifiers of the record's GS1 Digital Link: its own and the informative ones, in path order."""
    joined = list(pairs) + list(informative or [])
    return sorted(joined, key=lambda kv: QUALIFIER_ORDER.index(kv[0]) if kv[0] in QUALIFIER_ORDER else 99)


def has_key_level(ai: str) -> bool:
    """Whether the key can have a record of its own, without qualifiers (not AI 415, which needs AI 8020).
    GS1-Conformant Resolver 1.2.1, section 2.5.9, asks for a default link at that level or higher."""
    return any(all(not needed for _, needed in shape) for shape in KEY_SHAPES.get(ai, [[]]))


def is_valid_qualifier_set(ai: str, pairs) -> bool:
    """Whether the qualifier pairs are valid for the key (format, combination, order)."""
    try:
        normalise_qualifiers(ai, pairs)
        return True
    except ValidationError:
        return False


def qualifier_list(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """The data entry format: [{"10": "L1"}, {"21": "S1"}]."""
    return [{q: v} for q, v in pairs]


def qualifier_path(pairs: list[tuple[str, str]], encode: bool = True) -> str:
    """"/10/L1/21/S1" (values percent-encoded for URIs unless encode=False)."""
    return "".join(f"/{q}/{quote(v, safe='') if encode else v}" for q, v in pairs)


def parse_qualifier_text(text: str) -> list[tuple[str, str]]:
    """Qualifiers written as element strings "(10)L1(21)S1" or as a path "/10/L1/21/S1"."""
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("("):
        pairs = re.findall(r"\((\d{2,4})\)([^()]*)", text)
        if "".join(f"({q}){v}" for q, v in pairs) != text.replace(" ", "") and not pairs:
            raise ValidationError("qualifier.format")
        return [(q, v.strip()) for q, v in pairs]
    parts = [p for p in text.strip("/").split("/")]
    if len(parts) % 2:
        raise ValidationError("qualifier.format")
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]


def pairs_from(qualifiers) -> list[tuple[str, str]]:
    """(AI, value) pairs from the data entry format, in path order (unknown AIs last)."""
    pairs = [(k, v) for item in qualifiers or [] for k, v in item.items()]
    return sorted(pairs, key=lambda kv: QUALIFIER_ORDER.index(kv[0]) if kv[0] in QUALIFIER_ORDER else 99)


def normalise_key(ai: str, raw) -> str:
    """Validates the value of a primary identification key and returns it as it appears in the URI."""
    if ai not in PRIMARY_KEYS:
        raise ValidationError("key.unsupported", key=str(ai))
    value = re.sub(r"\s", "", without_invisible(raw))
    if not value:
        raise ValidationError("gtin.required" if ai == "01" else "key.required")
    if ai in ("01", "414", "417", "8017", "8018", "00", "402", "8006", "255"):
        value = value.replace(".", "").replace("-", "")     # separators people type in numbers
    return PRIMARY_KEYS[ai][1](value)


def anchor_for(ai: str, value: str) -> str:
    """The resolver's anchor of a key: /AI/value."""
    return f"/{ai}/{value}"


def split_anchor(anchor: str) -> tuple[str, str] | None:
    """("01", "0950…") for a supported primary key, otherwise None."""
    parts = (anchor or "").split("/")
    if len(parts) == 3 and parts[0] == "" and parts[1] in PRIMARY_KEYS and parts[2]:
        return parts[1], parts[2]
    return None


def company_part(anchor: str) -> str:
    """The part of a key value where the GS1 Company Prefix starts: after the indicator digit of a
    GTIN-14 or ITIP, the extension digit of an SSCC and the filler zero of a GRAI."""
    key = split_anchor(anchor)
    if not key:
        return ""
    ai, value = key
    return value[1:] if ai in ("01", "8006", "00", "8003") else value


def within_prefixes(anchor: str, prefixes) -> bool:
    """True when no prefixes are set or the key belongs to one of them."""
    if not prefixes:
        return True
    part = company_part(anchor)
    return any(part.startswith(p) for p in prefixes)


def digital_link(base_url: str, anchor: str, pairs: list[tuple[str, str]] = ()) -> str:
    """The GS1 Digital Link URI of a record: resolver address, anchor and qualifier path."""
    return f"{base_url}{anchor}{qualifier_path(list(pairs))}"


def hri_lines(anchor: str, pairs: list[tuple[str, str]] = ()) -> list[str]:
    """Human readable interpretation of the element strings, one per line: (01)…, (10)…, (21)…"""
    ai, value = anchor.strip("/").split("/", 1)
    return [f"({ai}){value}"] + [f"({q}){v}" for q, v in pairs]


def element_string(anchor: str, pairs: list[tuple[str, str]] = ()) -> str:
    """The record as GS1 element strings in bracketed AI syntax: (01)…(10)…"""
    return "".join(hri_lines(anchor, pairs))


def normalise_url(raw: str, position: int) -> str:
    """A target address as stored: trimmed, HTTPS only, without spaces, control or invisible characters;
    raises ValidationError with the target's position otherwise.
    """
    url = (raw or "").strip()
    if not url:
        raise ValidationError("link.urlRequired", position=position)
    # Spaces, line breaks, tabs, invisible characters and backslashes are never part of an address that
    # was copied correctly; a line break would even make the resolver fail when it sends the redirect.
    # Other non-ASCII characters (accented paths, internationalised domain names) are kept: the resolver
    # sends them percent-encoded and in Punycode.
    if any(c.isspace() or c == "\\" or unicodedata.category(c) in ("Cc", "Cf") for c in url):
        raise ValidationError("link.urlChars", position=position, url=url.encode("unicode_escape").decode("ascii"))
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or " " in url:
        raise ValidationError("link.urlInvalid", position=position, url=url)
    return url


def guess_media_type(url: str) -> str:
    """The media type stored with a target, from the extension of its path (PDF, images, video…)."""
    path = urlparse(url).path.lower()
    for extension, media_type in _MIME_BY_EXTENSION.items():
        if path.endswith(extension):
            return media_type
    return "text/html"


def link_key(link: dict) -> tuple:
    """Uniqueness key used by Resolver CE: (linktype, hreflang, context)."""
    return (
        link.get("linktype", ""),
        tuple(sorted(link.get("hreflang") or [])),
        tuple(sorted(link.get("context") or [])),
    )


def qualifiers_match(a: list | None, b: list | None) -> bool:
    """Whether two Resolver CE qualifier lists ([{AI: value}, …]) name the same set, in any order."""
    def normalise(qualifiers):
        return sorted((k, v) for item in (qualifiers or []) for k, v in item.items())
    return normalise(a) == normalise(b)
