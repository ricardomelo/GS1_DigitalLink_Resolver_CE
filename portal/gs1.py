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

# BCP 47 language tags offered for link targets (names are rendered by the browser).
LANGUAGES = ["pt", "en", "es", "fr", "de", "it", "zh", "ja"]
LANGUAGE_CODES = set(LANGUAGES)

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


def qualifiers_for(lot: str | None) -> list[dict[str, str]]:
    return [{"10": lot}] if lot else []


def digital_link(base_url: str, gtin14: str, lot: str | None) -> str:
    uri = f"{base_url}/01/{gtin14}"
    if lot:
        uri += f"/10/{quote(lot, safe='')}"
    return uri


def hri_lines(gtin14: str, lot: str | None) -> list[str]:
    """Human readable interpretation of the element strings, one per line: (01)… and (10)…"""
    lines = [f"(01){gtin14}"]
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
