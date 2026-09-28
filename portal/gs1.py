"""
GS1 rules used by the portal: GTIN and batch/lot validation, the supported link types
(a subset of the GS1 Web Vocabulary) and construction of the GS1 Digital Link URI.

Validation failures raise ValidationError with a message *code* and parameters rather than
a sentence. The browser turns the code into text in the user's language (see static/i18n.js),
so this module stays language-neutral.
"""
import re
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
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-(?:[A-Za-z]{2}|\d{3}))?(-(?:[A-Za-z0-9]{5,8}|\d[A-Za-z0-9]{3}))*$")


def normalise_language(tag: str) -> str | None:
    """Well-formed BCP 47 tag in canonical case ("pt-br" → "pt-BR"), or None."""
    tag = (tag or "").strip().replace("_", "-")
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

# Conservative subset of GS1 AI encodable character set 82 for batch/lot numbers.
_LOT_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,20}$")


def gtin_check_digit(body: str) -> int:
    """GS1 modulo-10 check digit for the digits preceding it."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def normalise_gtin(raw: str) -> str:
    """Validates a GTIN-8/12/13/14 and returns it as GTIN-14."""
    digits = re.sub(r"[\s.\-]", "", raw or "")
    if not digits:
        raise ValidationError("gtin.required")
    if not digits.isdigit():
        raise ValidationError("gtin.digitsOnly")
    if len(digits) not in (8, 12, 13, 14):
        raise ValidationError("gtin.length", length=len(digits))
    expected = gtin_check_digit(digits[:-1])
    if int(digits[-1]) != expected:
        raise ValidationError("gtin.checkDigit", expected=expected)
    if len(digits) == 13 and digits[0] == "2":
        raise ValidationError("gtin.restricted")   # restricted circulation number (in-store use)
    return digits.zfill(14)


def normalise_lot(raw: str | None) -> str | None:
    lot = (raw or "").strip()
    if not lot:
        return None
    if not _LOT_PATTERN.match(lot):
        raise ValidationError("lot.invalid")
    return lot


def is_editable_lot(value) -> bool:
    """A batch/lot the portal can edit: excludes templates such as "{lotnumber}" and values outside
    the portal's character subset, which other tools may have stored."""
    return isinstance(value, str) and bool(_LOT_PATTERN.match(value))


def qualifiers_for(lot: str | None) -> list[dict[str, str]]:
    return [{"10": lot}] if lot else []


# --------------------------------------------------------------------------- primary identification keys
# GS1 Digital Link URI Syntax 1.7, section 4.3, with the value formats of section 4.5 and the checks of
# the GS1 General Specifications as applied by the GS1 Barcode Syntax Engine (the library the resolver
# uses to validate every request): check digits, GMN check-character pair, GS1 Company Prefix at the
# start of alphanumeric keys, ITIP piece/total, GRAI filler zero.
#
# AI 415 (GLN of the invoicing party) is not offered yet: its Digital Link path requires the key
# qualifier 8020 (payment reference), which comes with the key qualifiers.
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
    if not value.isdigit():
        raise ValidationError("key.digitsOnly")
    if len(value) != length:
        raise ValidationError("key.length", expected=length, length=len(value))


def _check_digit(digits: str) -> None:
    expected = gtin_check_digit(digits[:-1])
    if int(digits[-1]) != expected:
        raise ValidationError("key.checkDigit", expected=expected)


def _alnum(value: str, maximum: int, pattern=_ALNUM, code="key.chars") -> None:
    if len(value) > maximum:
        raise ValidationError("key.tooLong", max=maximum)
    if not pattern.match(value):
        raise ValidationError(code)
    if not value[:4].isdigit() or len(value) < 4:
        raise ValidationError("key.companyPrefix")      # must start with a GS1 Company Prefix


def _numeric_key(length: int):
    def check(value: str) -> str:
        _digits(value, length)
        _check_digit(value)
        return value
    return check


def _itip(value: str) -> str:
    _digits(value, 18)
    _check_digit(value[:14])
    piece, total = int(value[14:16]), int(value[16:18])
    if piece == 0 or total == 0 or piece > total:
        raise ValidationError("key.itipPiece")
    return value


def _gmn(value: str) -> str:
    _alnum(value, 25)
    if len(value) < 3:
        raise ValidationError("key.gmnPair", expected="")
    expected = gmn_check_pair(value[:-2])
    if value[-2:] != expected:
        raise ValidationError("key.gmnPair", expected=expected)
    return value


def _cpid(value: str) -> str:
    _alnum(value, 30, _CPID_CHARS, "key.cpidChars")
    return value


def _gcn(value: str) -> str:
    if not value.isdigit():
        raise ValidationError("key.digitsOnly")
    if not 13 <= len(value) <= 25:
        raise ValidationError("key.lengthRange", min=13, max=25, length=len(value))
    _check_digit(value[:13])
    return value


def _with_serial(prefix_length: int, serial_max: int, filler: str = ""):
    """13 digits with a check digit, then an optional serial (GDTI, GRAI)."""
    def check(value: str) -> str:
        body = value
        if filler:
            if not value.startswith(filler):
                raise ValidationError("key.graiZero")
            body = value[len(filler):]
        base, serial = body[:prefix_length], body[prefix_length:]
        if len(base) < prefix_length or not base.isdigit():
            raise ValidationError("key.baseDigits", length=prefix_length)
        _check_digit(base)
        if len(serial) > serial_max:
            raise ValidationError("key.serialTooLong", max=serial_max)
        if serial and not _ALNUM.match(serial):
            raise ValidationError("key.chars")
        return value
    return check


def _alnum_key(maximum: int):
    def check(value: str) -> str:
        _alnum(value, maximum)
        return value
    return check


def _gtin(value: str) -> str:
    return normalise_gtin(value)


# code: (short name, validator, key qualifiers the portal manages for it)
PRIMARY_KEYS: dict[str, tuple[str, object, tuple[str, ...]]] = {
    "01": ("GTIN", _gtin, ("10",)),
    "8006": ("ITIP", _itip, ()),
    "8013": ("GMN", _gmn, ()),
    "8010": ("CPID", _cpid, ()),
    "414": ("GLN", _numeric_key(13), ()),
    "417": ("Party GLN", _numeric_key(13), ()),
    "8017": ("GSRNP", _numeric_key(18), ()),
    "8018": ("GSRN", _numeric_key(18), ()),
    "255": ("GCN", _gcn, ()),
    "00": ("SSCC", _numeric_key(18), ()),
    "253": ("GDTI", _with_serial(13, 17), ()),
    "401": ("GINC", _alnum_key(30), ()),
    "402": ("GSIN", _numeric_key(17), ()),
    "8003": ("GRAI", _with_serial(13, 16, filler="0"), ()),
    "8004": ("GIAI", _alnum_key(30), ()),
}


def normalise_key(ai: str, raw) -> str:
    """Validates the value of a primary identification key and returns it as it appears in the URI."""
    if ai not in PRIMARY_KEYS:
        raise ValidationError("key.unsupported", key=str(ai))
    value = re.sub(r"\s", "", str(raw or ""))
    if not value:
        raise ValidationError("gtin.required" if ai == "01" else "key.required")
    if ai in ("01", "414", "417", "8017", "8018", "00", "402", "8006", "255"):
        value = value.replace(".", "").replace("-", "")     # separators people type in numbers
    return PRIMARY_KEYS[ai][1](value)


def anchor_for(ai: str, value: str) -> str:
    return f"/{ai}/{value}"


def split_anchor(anchor: str) -> tuple[str, str] | None:
    """("01", "0950…") for a supported primary key, otherwise None."""
    parts = (anchor or "").split("/")
    if len(parts) == 3 and parts[0] == "" and parts[1] in PRIMARY_KEYS and parts[2]:
        return parts[1], parts[2]
    return None


def allows_lot(ai: str) -> bool:
    return "10" in PRIMARY_KEYS.get(ai, ("", None, ()))[2]


def digital_link(base_url: str, anchor: str, lot: str | None) -> str:
    uri = f"{base_url}{anchor}"
    if lot:
        uri += f"/10/{quote(lot, safe='')}"
    return uri


def hri_lines(anchor: str, lot: str | None) -> list[str]:
    """Human readable interpretation of the element strings, one per line: (01)… and (10)…"""
    ai, value = anchor.strip("/").split("/", 1)
    lines = [f"({ai}){value}"]
    if lot:
        lines.append(f"(10){lot}")
    return lines


def normalise_url(raw: str, position: int) -> str:
    url = (raw or "").strip()
    if not url:
        raise ValidationError("link.urlRequired", position=position)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or " " in url:
        raise ValidationError("link.urlInvalid", position=position, url=url)
    return url


def guess_media_type(url: str) -> str:
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
    def normalise(qualifiers):
        return sorted((k, v) for item in (qualifiers or []) for k, v in item.items())
    return normalise(a) == normalise(b)
