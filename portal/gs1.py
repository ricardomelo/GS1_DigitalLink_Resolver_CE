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
import json
import os
import re
import unicodedata
from urllib.parse import quote, urlparse

import gs1dict


class ValidationError(Exception):
    """User input error. `code` is a key in the front-end message catalogue."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


# ---------------------------------------------------------------------------
# Link types (backlog item 9.4): every link type of the GS1 Web Vocabulary, from gs1_link_types.json, which
# tools/gen_link_types.py writes from the vocabulary (the development tests check it is what the vocabulary gives).
# Each is put in a group of the editor's menu here (a new link type of the vocabulary fails the tests until it has
# one), and the menu shows the groups in the order that suits the key type (LINK_GROUP_ORDER). The default title is
# stored only when the user leaves the title blank; display labels and help text live in static/i18n.js.
# ---------------------------------------------------------------------------
LINK_TYPES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gs1_link_types.json")
with open(LINK_TYPES_PATH, encoding="utf-8") as _fh:
    VOCABULARY_LINK_TYPES = json.load(_fh)
LINK_TYPE_GROUPS = {
    "common": ["gs1:pip", "gs1:instructions", "gs1:support", "gs1:certificationInfo", "gs1:safetyInfo", "gs1:dpp"],
    "health": ["gs1:epil", "gs1:smpc", "gs1:recallStatus", "gs1:eifu", "gs1:brandHomepagePatient",
               "gs1:brandHomepageClinical"],
    "aftersales": ["gs1:quickStartGuide", "gs1:tutorial", "gs1:relatedVideo", "gs1:serviceInfo", "gs1:whatsInTheBox",
                   "gs1:faqs", "gs1:registerProduct", "gs1:purchaseSuppliesOrAccessories",
                   "gs1:consumerHandlingStorageInfo", "gs1:appDownload", "gs1:userAgreement", "gs1:reportFound"],
    "consumer": ["gs1:promotion", "gs1:hasRetailers", "gs1:review", "gs1:leaveReview", "gs1:socialMedia",
                 "gs1:sustainabilityInfo", "gs1:loyaltyProgram", "gs1:subscribe", "gs1:smartLabel", "gs1:relatedImage",
                 "gs1:activityIdeas", "gs1:backgroundInfo", "gs1:paymentLink"],
    "food": ["gs1:nutritionalInfo", "gs1:ingredientsInfo", "gs1:allergenInfo", "gs1:recipeInfo"],
    "b2b": ["gs1:masterData", "gs1:traceability", "gs1:epcis", "gs1:logisticsInfo", "gs1:registryEntry",
            "gs1:verificationService", "gs1:jws", "gs1:handledBy", "gs1:statisticInfo"],
    "places": ["gs1:locationInfo", "gs1:openingHoursInfo", "gs1:menuInfo", "gs1:eventsInfo", "gs1:scheduleTime"],
    "organisation": ["gs1:homepage", "gs1:careersInfo"],
}
# The groups in the order that suits each key type (the others: LINK_GROUP_ORDER["*"]); every type stays available.
_PRODUCTS = ["common", "food", "health", "consumer", "aftersales", "b2b", "places", "organisation"]
_LOCATIONS = ["places", "organisation", "common", "consumer", "b2b", "aftersales", "health", "food"]
_LOGISTICS = ["b2b", "common", "aftersales", "places", "organisation", "consumer", "health", "food"]
_SERVICES = ["organisation", "places", "health", "common", "consumer", "aftersales", "b2b", "food"]
LINK_GROUP_ORDER = {
    "*": _PRODUCTS, "01": _PRODUCTS, "8006": _PRODUCTS, "8013": _PRODUCTS, "8010": _PRODUCTS,
    "414": _LOCATIONS, "417": _LOCATIONS,
    "00": _LOGISTICS, "8003": _LOGISTICS, "8004": _LOGISTICS, "401": _LOGISTICS, "402": _LOGISTICS, "253": _LOGISTICS,
    "8017": _SERVICES, "8018": _SERVICES,
    "255": ["consumer", "common", "organisation", "places", "aftersales", "food", "health", "b2b"],
}
# English default titles the portal gave before item 9.4 (kept, so that records saved with them still read as titles
# the portal gave); the vocabulary's own title for the others.
_TITLES_BEFORE = {
    "gs1:pip": "Product information page", "gs1:certificationInfo": "Certification information",
    "gs1:epil": "Electronic patient information leaflet", "gs1:smpc": "Summary of product characteristics",
    "gs1:faqs": "Frequently asked questions", "gs1:registerProduct": "Register product",
    "gs1:hasRetailers": "Where to buy", "gs1:nutritionalInfo": "Nutritional information", "gs1:recipeInfo": "Recipes",
    "gs1:masterData": "Master data", "gs1:epcis": "EPCIS repository", "gs1:whatsInTheBox": "What's in the box",
}
_GROUP_OF = {code: group for group, codes in LINK_TYPE_GROUPS.items() for code in codes}
LINK_TYPES = [(t["code"], _GROUP_OF.get(t["code"], "other"), _TITLES_BEFORE.get(t["code"], t["title"]))
              for t in VOCABULARY_LINK_TYPES["linkTypes"]]
LINK_TYPES.sort(key=lambda t: (list(LINK_TYPE_GROUPS).index(t[1]) if t[1] in LINK_TYPE_GROUPS else 99,
                               LINK_TYPE_GROUPS.get(t[1], []).index(t[0]) if t[0] in LINK_TYPE_GROUPS.get(t[1], []) else 0))
VOCABULARY_TITLES = {t["code"]: t["title"] for t in VOCABULARY_LINK_TYPES["linkTypes"]}


def link_group_order(ai: str) -> list[str]:
    """The groups of the link type menu in the order that suits a key type."""
    return LINK_GROUP_ORDER.get(ai, LINK_GROUP_ORDER["*"])


LINK_TYPE_CODES = {code for code, _, _ in LINK_TYPES}
LINK_TYPE_DEFAULT_TITLES = {code: title for code, _, title in LINK_TYPES}
# Titles in Portuguese, the portal's other language (the editor's names, portal/static/i18n.js): a link left without a
# title gets the one in its own language (GS1-Conformant Resolver 2.5.3, conformance review F21); English otherwise.
LINK_TYPE_TITLES_PT = {
    "gs1:pip": "Página do produto",
    "gs1:instructions": "Instruções de uso",
    "gs1:support": "Atendimento (SAC)",
    "gs1:certificationInfo": "Certificados e conformidade",
    "gs1:safetyInfo": "Informações de segurança",
    "gs1:epil": "Bula eletrônica (paciente)",
    "gs1:smpc": "Informações ao profissional de saúde",
    "gs1:recallStatus": "Situação de recolhimento (recall)",
    "gs1:quickStartGuide": "Guia rápido",
    "gs1:tutorial": "Tutoriais",
    "gs1:relatedVideo": "Vídeo do produto",
    "gs1:serviceInfo": "Manutenção e assistência técnica",
    "gs1:whatsInTheBox": "Conteúdo da embalagem",
    "gs1:faqs": "Perguntas frequentes",
    "gs1:registerProduct": "Registrar produto ou garantia",
    "gs1:purchaseSuppliesOrAccessories": "Comprar acessórios e refis",
    "gs1:promotion": "Promoção",
    "gs1:hasRetailers": "Onde comprar",
    "gs1:review": "Avaliações",
    "gs1:leaveReview": "Deixar uma avaliação",
    "gs1:socialMedia": "Redes sociais",
    "gs1:sustainabilityInfo": "Sustentabilidade e reciclagem",
    "gs1:nutritionalInfo": "Informação nutricional",
    "gs1:ingredientsInfo": "Ingredientes",
    "gs1:allergenInfo": "Alergênicos",
    "gs1:recipeInfo": "Receitas",
    "gs1:masterData": "Dados cadastrais (B2B)",
    "gs1:traceability": "Rastreabilidade",
    "gs1:epcis": "Repositório EPCIS",
    "gs1:dpp": "Passaporte digital do produto",
    "gs1:eifu": "Instruções de uso eletrônicas (eIFU)",
    "gs1:brandHomepagePatient": "Informações da marca para pacientes",
    "gs1:brandHomepageClinical": "Informações da marca para profissionais",
    "gs1:consumerHandlingStorageInfo": "Conservação e manuseio",
    "gs1:appDownload": "Baixar o aplicativo",
    "gs1:userAgreement": "Termo ou contrato para assinar",
    "gs1:reportFound": "Comunicar item encontrado",
    "gs1:loyaltyProgram": "Programa de fidelidade",
    "gs1:subscribe": "Assinar",
    "gs1:smartLabel": "SmartLabel",
    "gs1:relatedImage": "Imagem relacionada",
    "gs1:activityIdeas": "Ideias de atividades",
    "gs1:backgroundInfo": "Bastidores e história",
    "gs1:paymentLink": "Fazer um pagamento",
    "gs1:logisticsInfo": "Informações logísticas",
    "gs1:registryEntry": "Registro em cadastro oficial",
    "gs1:verificationService": "Serviço de verificação",
    "gs1:jws": "Assinatura JSON Web (JWS)",
    "gs1:handledBy": "Atendido por outro resolver",
    "gs1:statisticInfo": "Estatísticas",
    "gs1:locationInfo": "Localização e como chegar",
    "gs1:openingHoursInfo": "Horário de funcionamento",
    "gs1:menuInfo": "Cardápio e serviços",
    "gs1:eventsInfo": "Eventos",
    "gs1:scheduleTime": "Agendamento e reservas",
    "gs1:homepage": "Página da organização",
    "gs1:careersInfo": "Trabalhe conosco",
}


def default_title(link_type: str, hreflang=()) -> str:
    """The title a link of this type gets when none is given: in the link's language when the portal knows it
    (Portuguese), else in English."""
    language = str((list(hreflang) or [""])[0]).split("-")[0].lower()
    if language == "pt" and link_type in LINK_TYPE_TITLES_PT:
        return LINK_TYPE_TITLES_PT[link_type]
    return LINK_TYPE_DEFAULT_TITLES.get(link_type, link_type)


def is_default_title(link_type: str, title: str) -> bool:
    """Whether a stored title is one the portal gave (in any language it knows), not one somebody typed."""
    return title in (LINK_TYPE_DEFAULT_TITLES.get(link_type), LINK_TYPE_TITLES_PT.get(link_type),
                     VOCABULARY_TITLES.get(link_type))
# The item's page as a record's default target (Documentation/adr/0011-item-page.md): a gs1:defaultLink to the
# resolver's own page of the record's links; set by the editor's option, never typed as a link of its own.
LANDING_TYPE = "gs1:defaultLink"
LANDING_QUERY = "?linkType=linkset&view=page"


def landing_url(base_url: str, anchor: str, pairs: list[tuple[str, str]] = ()) -> str:
    """The address of a record's page: its GS1 Digital Link with ?linkType=linkset&view=page."""
    return f"{base_url}{anchor}{qualifier_path(list(pairs))}{LANDING_QUERY}"


def is_landing(link: dict) -> bool:
    """Whether a stored link is the record's page (gs1:defaultLink to an address ending with LANDING_QUERY)."""
    return link.get("linktype") == LANDING_TYPE and str(link.get("href") or "").endswith(LANDING_QUERY)


# Explicit default links (ADR 0011, amendment of 17 October 2026): when a record of a key uses its page, the key's
# shared default link type is gs1:defaultLink and every record of the key has links of that type of its own — its
# page, or copies of its default targets (its links of the type of its first target, every language). The portal
# writes them and hides them; the editor shows the targets with the default first, and the option.
def explicit_default_links(links: list[dict], link_type: str) -> list[dict]:
    """Copies, as gs1:defaultLink, of the links of one type (the record's default targets)."""
    copies = []
    for link in links:
        if link.get("linktype") == link_type:
            copy = {k: v for k, v in link.items() if k in ("href", "title", "type", "hreflang", "context")}
            copies.append({"linktype": LANDING_TYPE, **copy})
    return copies


def record_view(links: list[dict], key_default: str | None) -> tuple[list[dict], bool, str | None]:
    """A record's stored links as the portal shows them: (its targets, the default ones first; whether its default
    target is its page; its own default link type). A link of type gs1:defaultLink is hidden when it is the page or a
    copy of another link of the record; one that copies nothing (written by another tool) is shown as a target."""
    explicit = [l for l in links if l.get("linktype") == LANDING_TYPE]
    others = [l for l in links if l.get("linktype") != LANDING_TYPE]
    landing = any(is_landing(l) for l in explicit)
    hrefs = {l.get("href") for l in others}
    pointers = [l.get("href") for l in explicit if not is_landing(l) and l.get("href") in hrefs]
    orphans = [l for l in explicit if not is_landing(l) and l.get("href") not in hrefs]
    targets = orphans + others
    if key_default != LANDING_TYPE:
        default = key_default
        first = lambda l: l.get("linktype") == default                  # noqa: E731
    elif landing or orphans or not pointers:
        default = LANDING_TYPE if landing or orphans else (others[0].get("linktype") if others else None)
        first = lambda l: l in orphans or (not landing and not orphans and l.get("linktype") == default)  # noqa: E731
    else:
        default = next(l.get("linktype") for l in others if l.get("href") == pointers[0])
        first = lambda l: l.get("linktype") == default and l.get("href") in pointers  # noqa: E731
    return sorted(targets, key=lambda l: not first(l)), landing, default


# The languages of a target offered in the editor (backlog item 9.4): every ISO 639-1 language, then the regional tags
# most asked for; the browser writes their names (Intl.DisplayNames) and the list is searched as it is typed. Any other
# well-formed BCP 47 tag (normalise_language) is accepted too: records created with other tools use them.
ISO_639_1 = (
    "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en "
    "eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv "
    "ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne "
    "ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st "
    "su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu").split()
REGIONAL_TAGS = ["pt-BR", "pt-PT", "en-GB", "en-US", "en-CA", "en-AU", "es-ES", "es-MX", "es-AR", "es-419", "fr-FR",
                 "fr-CA", "fr-BE", "fr-CH", "de-DE", "de-AT", "de-CH", "it-IT", "it-CH", "nl-NL", "nl-BE", "zh-Hans",
                 "zh-Hant", "zh-CN", "zh-TW", "zh-HK", "sr-Latn", "sr-Cyrl", "ar-SA", "ar-EG", "ar-AE", "hi-IN", "ja-JP",
                 "ko-KR"]
# The first ones: the portal's own languages, then those most used for product information
LANGUAGES = ["pt", "en", "es", "fr", "de", "it", "zh", "ja"]
LANGUAGES += [code for code in ISO_639_1 if code not in LANGUAGES] + REGIONAL_TAGS
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
# GS1 Digital Link URI Syntax 1.7, section 4.3, with the value formats of section 4.5 and the checks of the GS1
# General Specifications as the GS1 Barcode Syntax Engine applies them (the library the resolver uses to validate
# every request): check digits, GMN check-character pair, GS1 Company Prefix at the start of alphanumeric keys,
# ITIP piece/total, GRAI filler zero.
#
# The keys, their formats, their qualifiers and the order of the path come from the GS1 Barcode Syntax Dictionary
# of the engine release written in docker-compose.yml (gs1_dictionary.json, ADR 0003): the primary keys are the
# AIs with "dlpkey"; each key's validator is chosen from the shape of its components and their linters, with the
# lengths of the dictionary. What the portal deliberately does differently is in PORTAL_EXCEPTIONS below. A key or
# qualifier whose format the portal cannot check makes this module fail at import (gs1dict.DictionaryError), so a
# new dictionary release that brings one is caught by the tests instead of being accepted unchecked.

_CSET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
_CSET32 = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]

# What the portal does differently from the dictionary, on purpose. Each entry says why.
PORTAL_EXCEPTIONS = {
    # Alphanumeric values of keys (CSET 82 in the dictionary): letters, digits, full stop and hyphen. "_" is
    # excluded because the data entry service turns "/" into "_" in document ids; the other symbols would need
    # percent-encoding in the URI.
    "key_chars": r"A-Za-z0-9.\-",
    # Alphanumeric values of key qualifiers (CSET 82): letters, digits, ".", "_" and "-".
    "qualifier_chars": r"A-Za-z0-9._\-",
    # CPID (8010, CSET 39 in the dictionary): digits, capital letters and "-"; the portal leaves out "#" and "/".
    "cset39_chars": r"0-9A-Z\-",
    # ITIP (8006) is offered with 10 and 21 only: the dictionary also lists 22, but the GS1 Barcode Syntax Engine
    # refuses 22 without 01 (an association rule of the GS1 General Specifications), so such a record could never
    # be resolved (conformance review, erratum E2).
    "qualifiers_left_out": {"8006": {"22"}},
    # GTIN (01): GTIN-8, GTIN-12 and GTIN-13 are accepted as typed and stored as GTIN-14 (a convenience of the
    # portal's forms; the URI always carries 14 digits).
    "short_gtin": {"01"},
    # Short names of the keys and the order of the menu, as GS1 Digital Link URI Syntax 1.7 section 4.3 lists them
    # (the dictionary's titles are the element strings' data titles: "LOC No.", "PAY TO"). A key the dictionary
    # adds later comes last, under its dictionary title.
    "key_names": {"01": "GTIN", "8006": "ITIP", "8013": "GMN", "8010": "CPID", "414": "GLN", "415": "Pay-to GLN",
                  "417": "Party GLN", "8017": "GSRNP", "8018": "GSRN", "255": "GCN", "00": "SSCC", "253": "GDTI",
                  "401": "GINC", "402": "GSIN", "8003": "GRAI", "8004": "GIAI"},
}
_ALNUM = re.compile(rf"^[{PORTAL_EXCEPTIONS['key_chars']}]+$")
_CPID_CHARS = re.compile(rf"^[{PORTAL_EXCEPTIONS['cset39_chars']}]+$")
# Linters the portal checks itself (the engine has about 40; these are the ones keys and qualifiers use).
KNOWN_LINTERS = {"csum", "csumalpha", "gcppos1", "gcppos2", "zero", "pieceoftotal", "nozeroprefix", "importeridx"}


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
        raise ValidationError("key.companyPrefix")      # must start with a GS1 Company Prefix (linter gcppos1)


def _numeric_key(length: int):
    """Validator of a fixed-length numeric key with a check digit (GLN, GSRN, SSCC, GSIN)."""
    def check(value: str) -> str:
        _digits(value, length)
        _check_digit(value)
        return value
    return check


def _itip(base: int, extra: int):
    """ITIP (8006): GTIN-14 with its check digit, then piece and total, piece from 1 to total."""
    def check(value: str) -> str:
        _digits(value, base + extra)
        _check_digit(value[:base])
        half = extra // 2
        piece, total = int(value[base:base + half]), int(value[base + half:])
        if piece == 0 or total == 0 or piece > total:
            raise ValidationError("key.itipPiece")
        return value
    return check


def _gmn(maximum: int):
    """GMN (8013): alphanumeric with the check-character pair of the GS1 General Specifications."""
    def check(value: str) -> str:
        _alnum(value, maximum)
        if len(value) < 3:
            raise ValidationError("key.gmnPair", expected="")
        expected = gmn_check_pair(value[:-2])
        if value[-2:] != expected:
            raise ValidationError("key.gmnPair", expected=expected)
        return value
    return check


def _cpid(maximum: int):
    """CPID (8010): character set 39 after a GS1 Company Prefix (see PORTAL_EXCEPTIONS)."""
    def check(value: str) -> str:
        _alnum(value, maximum, _CPID_CHARS, "key.cpidChars")
        return value
    return check


def _digits_with_serial(base: int, minimum: int, maximum: int):
    """GCN (255): a numeric base with its check digit and an optional numeric serial, minimum to maximum digits."""
    def check(value: str) -> str:
        if not ascii_digits(value):
            raise ValidationError("key.digitsOnly")
        if not minimum <= len(value) <= maximum:
            raise ValidationError("key.lengthRange", min=minimum, max=maximum, length=len(value))
        _check_digit(value[:base])
        return value
    return check


def _with_serial(prefix_length: int, serial_max: int, filler: str = ""):
    """A numeric base with a check digit, then an optional alphanumeric serial (GDTI; GRAI after its filler)."""
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


def _shape(components: list[dict]) -> list[tuple]:
    """A key's components as (type, min, max, optional, linters) for matching."""
    return [(c["type"], c["min"], c["max"], c["optional"], frozenset(c["linters"])) for c in components]


def _spec(check, **spec):
    """A validator with the description the browser repeats the check from (GET /portal/api/config)."""
    check.spec = spec
    return check


def key_validator(ai: str, components: list[dict]):
    """The validator of a primary key, chosen from the shape of its components in the dictionary, with
    `.spec`, the same check described for the browser ({"kind": "numeric", "length": 13}, …).
    Raises gs1dict.DictionaryError for a shape the portal cannot check."""
    shape = _shape(components)
    unknown = {linter for *_, linters in shape for linter in linters} - KNOWN_LINTERS
    if unknown:
        raise gs1dict.DictionaryError(f"key {ai}: linters {sorted(unknown)} not checked by the portal")
    kinds = [(t, opt) for t, _, _, opt, _ in shape]
    if ai in PORTAL_EXCEPTIONS["short_gtin"] and kinds == [("N", False)]:
        return _spec(_gtin, kind="gtin")
    if kinds == [("N", False)] and shape[0][1] == shape[0][2] and "csum" in shape[0][4]:
        return _spec(_numeric_key(shape[0][2]), kind="numeric", length=shape[0][2])     # GLN, SSCC, GSRN, GSIN
    if kinds == [("N", False), ("N", False)] and "csum" in shape[0][4] and "pieceoftotal" in shape[1][4]:
        return _spec(_itip(shape[0][2], shape[1][2]), kind="itip", base=shape[0][2], extra=shape[1][2])
    if kinds == [("N", False), ("N", True)] and "csum" in shape[0][4]:
        base, maximum = shape[0][2], shape[0][2] + shape[1][2]                             # GCN
        return _spec(_digits_with_serial(base, base, maximum), kind="digitsSerial", base=base, min=base, max=maximum)
    if kinds == [("N", False), ("X", True)] and "csum" in shape[0][4]:
        return _spec(_with_serial(shape[0][2], shape[1][2]), kind="withSerial", base=shape[0][2],
                     serialMax=shape[1][2], filler="")                            # GDTI
    if kinds == [("N", False), ("N", False), ("X", True)] and "zero" in shape[0][4] and shape[0][2] == 1 \
            and "csum" in shape[1][4]:
        return _spec(_with_serial(shape[1][2], shape[2][2], filler="0"), kind="withSerial", base=shape[1][2],
                     serialMax=shape[2][2], filler="0")                           # GRAI
    if kinds == [("X", False)] and "gcppos1" in shape[0][4]:
        if "csumalpha" in shape[0][4]:
            return _spec(_gmn(shape[0][2]), kind="gmn", max=shape[0][2])  # GMN
        return _spec(_alnum_key(shape[0][2]), kind="alnum", max=shape[0][2])  # GINC, GIAI
    if kinds == [("Y", False)] and "gcppos1" in shape[0][4]:
        return _spec(_cpid(shape[0][2]), kind="cpid", max=shape[0][2])  # CPID
    raise gs1dict.DictionaryError(f"key {ai}: format {components} not checked by the portal")


def qualifier_pattern(ai: str, components: list[dict]) -> re.Pattern:
    """The pattern of a key qualifier's value, from its components in the dictionary (see PORTAL_EXCEPTIONS).
    Raises gs1dict.DictionaryError for a format the portal cannot check."""
    parts = []
    for c in components:
        linters = set(c["linters"]) - {"nozeroprefix", "importeridx"}
        if linters:
            raise gs1dict.DictionaryError(f"qualifier {ai}: linters {sorted(linters)} not checked by the portal")
        if c["type"] == "N":
            first = "[1-9]" if "nozeroprefix" in c["linters"] else None
            if first:
                parts.append(f"{first}\\d{{{max(c['min'] - 1, 0)},{c['max'] - 1}}}")
            else:
                parts.append(f"\\d{{{c['min']},{c['max']}}}")
        elif c["type"] == "X":
            chars = r"A-Za-z0-9_\-" if "importeridx" in c["linters"] else PORTAL_EXCEPTIONS["qualifier_chars"]
            parts.append(f"[{chars}]{{{c['min']},{c['max']}}}")
        else:
            raise gs1dict.DictionaryError(f"qualifier {ai}: type {c['type']} not checked by the portal")
        if c["optional"]:
            parts[-1] = f"(?:{parts[-1]})?"
    return re.compile("^" + "".join(parts) + "$", re.ASCII)


def _build(data: dict):
    """PRIMARY_KEYS, KEY_SHAPES, QUALIFIER_ORDER and QUALIFIER_FORMATS from the dictionary."""
    ais = data["ais"]
    names = PORTAL_EXCEPTIONS["key_names"]
    keys = [ai for ai in names if "dlpkey" in ais.get(ai, {})] + sorted(
        ai for ai, entry in ais.items() if "dlpkey" in entry and ai not in names)
    primary = {ai: (names.get(ai, ais[ai]["title"]), key_validator(ai, ais[ai]["components"])) for ai in keys}
    shapes, order = {}, []
    for ai in keys:
        left_out = PORTAL_EXCEPTIONS["qualifiers_left_out"].get(ai, set())
        required = {q for instance in ais[ai]["req"] for group in instance for q in group if len(instance) == 1}
        alternatives = [[q for q in seq if q not in left_out] for seq in ais[ai]["dlpkey"]]
        result = []
        for index, sequence in enumerate(alternatives):
            # the first sequence may be empty (the key alone); a later one is told apart by its first qualifier
            shape = [(q, q in required or (index > 0 and position == 0)) for position, q in enumerate(sequence)]
            result.append(shape)
            order.extend(q for q in sequence if q not in order)
        if result != [[]]:
            shapes[ai] = result
    formats = {q: (ais[q]["title"], qualifier_pattern(q, ais[q]["components"])) for q in order}
    return primary, shapes, order, formats


PRIMARY_KEYS, KEY_SHAPES, QUALIFIER_ORDER, QUALIFIER_FORMATS = _build(gs1dict.load())
NUMERIC_KINDS = {"gtin", "numeric", "itip", "digitsSerial"}      # keys of digits only: "." and "-" are dropped


def browser_rules() -> dict:
    """The rules the browser repeats for live feedback (GET /portal/api/config), from the same tables: each key's
    check, each qualifier's pattern and maximum length, the qualifier order and the portal's character sets."""
    return {"keys": {ai: dict(validator.spec) for ai, (_, validator) in PRIMARY_KEYS.items()},
            "qualifiers": {q: {"pattern": pattern.pattern, "max": sum(c["max"] for c in gs1dict.load()["ais"][q]["components"])}
                           for q, (_, pattern) in QUALIFIER_FORMATS.items()},
            "order": list(QUALIFIER_ORDER),
            "keyChars": PORTAL_EXCEPTIONS["key_chars"], "cset39Chars": PORTAL_EXCEPTIONS["cset39_chars"],
            "release": DICTIONARY_RELEASE}
DICTIONARY_RELEASE = gs1dict.load()["release"]


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
    if PRIMARY_KEYS[ai][1].spec["kind"] in NUMERIC_KINDS:
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
