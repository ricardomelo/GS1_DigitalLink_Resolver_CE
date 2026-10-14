"""
GS1 Digital Link data attributes (GS1 Digital Link URI Syntax 1.7, section 4.10), validated by the GS1
Barcode Syntax Engine.

Data attributes are GS1 Application Identifiers for informative data (expiry date, net weight, price…)
written in the query string of a GS1 Digital Link URI: https://id.example.org/01/…/10/L1?17=261231.
They are not part of the identifier, so they are never stored on the resolver; the portal only puts
them in the QR code it draws. The resolver passes the query string on to the target (fwqs).

About 200 AIs, each with its own format, check digits, date and code-list rules, and the association
rules of the GS1 General Specifications (section 4.13: invalid pairs, mandatory associations) apply.
Rather than reproduce them, the portal asks the GS1 Barcode Syntax Engine, the reference implementation
the resolver also uses, through its Python binding, built by tools/build-syntax-engine.sh into
GS1_SYNTAX_ENGINE_DIR. The AIs on offer, their titles and formats, and the AIs that belong in each key's path come
from gs1_dictionary.json (gs1dict.py), generated from the dictionary of the same release (the one written in
docker-compose.yml; ADR 0003); a different engine release is logged.

Without the engine the portal works as before and simply does not offer data attributes.
"""
import calendar
import ctypes
import logging
import os
import re
import sys
import threading

import engine_messages
import gs1
import gs1dict
from gs1 import ValidationError

log = logging.getLogger("portal.syntax")

ENGINE_DIR = os.environ.get("GS1_SYNTAX_ENGINE_DIR", "/opt/gs1-syntax-engine")
# The real limit is what fits in a QR code at the chosen version and error correction level (the label says
# so when the content does not fit); this ceiling only guards the server against absurd requests.
MAX_ATTRIBUTES = 100
_DECIMAL_SEPARATORS = re.compile(r"[.,]")



class Engine:
    """The loaded engine, or the reason it is not available."""

    def __init__(self, directory: str):
        self.directory = directory
        self.available = False
        self.release = None
        self.reason = None
        self.attributes: dict[str, dict] = {}      # AI → {ai, title, components}
        self.families: dict[str, dict] = {}        # "310n" → {ai, title, components, members, decimals, family}
        self.path_ais: dict[str, set[str]] = {}    # primary key AI → AIs that go in its path
        self._lock = threading.Lock()
        self._encoder = None
        self._errors: tuple = ()
        try:
            self._load()
        except Exception as exc:  # noqa: BLE001 — any failure only disables the feature
            self.reason = f"{type(exc).__name__}: {exc}"
            log.warning("GS1 Barcode Syntax Engine not available (%s): data attributes are disabled", self.reason)

    def _load(self) -> None:
        library = ctypes.CDLL(os.path.join(self.directory, "libgs1encoders.so"))
        if self.directory not in sys.path:
            sys.path.insert(0, self.directory)
        # The binding loads "libgs1encoders.so" by name when it is imported, which would need the
        # directory in LD_LIBRARY_PATH; it is handed the library loaded from this directory instead.
        load_library = ctypes.cdll.LoadLibrary
        ctypes.cdll.LoadLibrary = lambda name: library if name == "libgs1encoders.so" else load_library(name)
        try:
            import gs1encoders  # noqa: PLC0415
        finally:
            ctypes.cdll.LoadLibrary = load_library

        self._encoder = gs1encoders.GS1Encoder()
        self._errors = (gs1encoders.GS1EncoderParameterException, gs1encoders.GS1EncoderDigitalLinkException,
                        gs1encoders.GS1EncoderGeneralException)
        dictionary = gs1dict.load()
        self.attributes, self.path_ais = gs1dict.data_attributes(dictionary), gs1dict.path_ais(dictionary)
        self.families = decimal_families(self.attributes)
        try:
            with open(os.path.join(self.directory, "RELEASE"), encoding="utf-8") as fh:
                self.release = fh.read().strip()
        except OSError:
            self.release = None
        if self.release != dictionary["release"]:
            log.warning("GS1 Barcode Syntax Engine %s, but gs1_dictionary.json is of %s: build the engine of the "
                        "release in docker-compose.yml", self.release, dictionary["release"])
        self.available = True

    def describe(self) -> dict:
        """What the browser needs to offer data attributes (GET /portal/api/config)."""
        if not self.available:
            return {"available": False}
        members = {code for family in self.families.values() for code in family["members"]}
        offered = [a for a in self.attributes.values() if a["ai"] not in members] + list(self.families.values())
        offered.sort(key=lambda a: (a["ai"][:2], a["ai"]))
        return {"available": True, "release": self.release, "max": MAX_ATTRIBUTES,
                "ais": offered,
                "inPath": {key: sorted(ais) for key, ais in self.path_ais.items()}}

    def digital_link(self, stem: str, anchor: str, pairs: list[tuple[str, str]],
                     attributes: list[tuple[str, str]]) -> tuple[str, list[str]]:
        """The GS1 Digital Link URI of a record with data attributes in the query string, and the HRI
        lines of the attributes. Raises ValidationError with a code the portal translates; problems
        only the engine can judge (formats, check digits, dates, associations) come as attr.invalid
        with the engine's own message in "detail"."""
        if not self.available:
            raise ValidationError("attr.unavailable")
        key_ai, _ = gs1.split_anchor(anchor)
        if len(attributes) > MAX_ATTRIBUTES:
            raise ValidationError("attr.tooMany", max=MAX_ATTRIBUTES)
        # Checks on the attributes as the user chose them ("392n", "17"), then decimal conversion, so that
        # every message names what the user sees
        seen = set()
        for ai, value in attributes:
            if ai == key_ai or ai in self.path_ais.get(key_ai, set()):
                # A qualifier of this key (batch, serial…) or the key itself: the engine would write it in
                # the path and the QR code would point at another record. Checked first because it tells
                # the user where the value belongs, also for qualifiers that are never data attributes.
                raise ValidationError("attr.inPath", ai=ai)
            if ai not in self.attributes and ai not in self.families:
                raise ValidationError("attr.unknown", ai=ai)
            if ai in seen:
                raise ValidationError("attr.duplicate", ai=ai)
            seen.add(ai)
            if not value:
                raise ValidationError("attr.valueRequired", ai=ai)
        chosen = {}                                   # AI in the URI → AI as chosen (3920 → 392n)
        resolved = []
        for ai, value in attributes:
            code, digits = self.resolve_decimal(ai, value)
            if code in chosen:                        # 310n twice, both with the same decimals
                raise ValidationError("attr.duplicate", ai=ai)
            chosen[code] = ai
            _refuse_day_zero(code, digits, self.attributes[code]["components"])
            resolved.append((code, digits))
        attributes = resolved
        path_uri = gs1.digital_link(stem, anchor, pairs)
        if not attributes:
            return path_uri, []
        element_string = gs1.element_string(anchor, pairs) + "".join(
            f"({ai}){_escape(value)}" for ai, value in attributes)
        with self._lock:
            try:
                self._encoder.ai_data_str = element_string
                uri = self._encoder.get_dl_uri(stem)
            except self._errors as exc:
                raise _engine_error(str(exc), self._encoder.err_markup, chosen) from exc
        if uri.split("?", 1)[0] != path_uri:
            # Belt and braces: the identification in the path must stay the record's own.
            raise ValidationError("attr.inPath", ai=next(iter(seen)))
        return uri, [f"({ai}){value}" for ai, value in attributes]

    def resolve_decimal(self, ai: str, value: str) -> tuple[str, str]:
        """AIs whose last digit is the number of decimal places (310n net weight, 392n price…) as people
        write numbers: "310n" with "123,45" becomes (3102) 012345; a member such as "3922" with "12,5"
        becomes (3922) 1250. Comma or point is the decimal separator (a single one, no thousands
        separator); digits without a separator keep the GS1 meaning. Anything else is left unchanged."""
        family_code = ai if ai in self.families else (ai[:3] + "n" if ai[:3] + "n" in self.families else None)
        if not family_code or not value:
            return ai, value
        family = self.families[family_code]
        fixed = None if ai == family_code else int(ai[3])            # decimals of a member chosen directly
        prefix_length = sum(c["max"] for c in family["components"][:-1])   # e.g. the ISO 4217 code of 393n
        compact = value.replace(" ", "")
        prefix, number = compact[:prefix_length], compact[prefix_length:]
        separators = _DECIMAL_SEPARATORS.findall(number)
        if len(separators) > 1:
            raise ValidationError("attr.decimalSeparator", ai=ai)
        if not separators:
            if fixed is not None:
                return ai, value                                     # GS1 digits as typed
            whole, fraction = number, ""
        else:
            whole, fraction = _DECIMAL_SEPARATORS.split(number)
        if not (whole + fraction).isascii() or not (whole + fraction).isdigit() \
                or (prefix_length and not (prefix.isascii() and prefix.isdigit())):
            raise ValidationError("attr.notNumber", ai=ai)
        decimals = len(fraction) if fixed is None else fixed
        if len(fraction) > decimals or decimals > family["decimals"]:
            raise ValidationError("attr.decimals", ai=ai, max=family["decimals"] if fixed is None else fixed)
        digits = (whole.lstrip("0") + fraction.ljust(decimals, "0")).lstrip("0") or "0"
        last = family["components"][-1]
        if len(digits) > last["max"]:
            raise ValidationError("attr.tooManyDigits", ai=ai, max=last["max"])
        if last["min"] == last["max"]:
            digits = digits.rjust(last["max"], "0")
        return f"{family_code[:3]}{decimals}", prefix + digits


_REQUIRES = re.compile(r"^Required AIs for AI \((\d+)\) are not satisfied: ([0-9n,]+)$")
_PAIR = re.compile(r"^It is invalid to pair AI \((\d+)\) with AI \((\d+)\)$")
_NOT_ATTRIBUTE = re.compile(r"^AI \((\d+)\) is not a valid DL URI data attribute$")


def _engine_error(message: str, markup: str, chosen: dict[str, str]) -> ValidationError:
    """The engine's refusal. The association rules of the General Specifications, which users meet most
    (a price needs a quantity or measure; two weights of different precision cannot go together), get
    messages of their own in the user's language, naming the AIs as the user chose them ("392n", not
    "3920"). Other refusals (a check digit, a date, a code list) are attr.invalid with the engine's English text
    in "detail" and, when it is one of the engine's messages, its code and parameters in "message"
    (engine_messages.py), which the browser shows in the user's language instead."""
    shown = lambda ai: chosen.get(ai, ai)                      # noqa: E731
    if match := _REQUIRES.match(message):
        # "31nn" in the engine's list stands for the families 310n-316n; the portal writes "31nn" as well
        return ValidationError("attr.requires", ai=shown(match.group(1)), list=match.group(2).split(","))
    if match := _PAIR.match(message):
        return ValidationError("attr.pair", ai=shown(match.group(1)), other=shown(match.group(2)))
    if match := _NOT_ATTRIBUTE.match(message):
        return ValidationError("attr.unknown", ai=shown(match.group(1)))
    recognised = engine_messages.recognise(message)
    if recognised is None:
        return ValidationError("attr.invalid", detail=message, markup=markup)
    return ValidationError("attr.invalid", detail=message, markup=markup, message=recognised)


def _refuse_day_zero(ai: str, value: str, components: list[dict]) -> None:
    """GS1 allows day 00 in some dates (yymmd0: 17, 15, 11…) to mean "end of the month". The portal
    refuses it, as a policy: a reader of the label, or a system receiving the Digital Link, may not know
    the convention; an explicit first or last day of the month says the same without ambiguity."""
    offset = 0
    for component in components:
        if component["min"] != component["max"]:
            return                               # offsets after a variable-length part are unknown
        date = value[offset:offset + 6]
        if "yymmd0" in component["linters"] and len(date) == 6 and date.isascii() and date.isdigit() \
                and date.endswith("00") and 1 <= int(date[2:4]) <= 12:
            year, month = 2000 + int(date[:2]), int(date[2:4])       # the century does not change leap years here
            last = calendar.monthrange(year, month)[1]
            raise ValidationError("attr.dayZero", ai=ai, first=date[:4] + "01", last=f"{date[:4]}{last:02d}")
        offset += component["max"]


def _escape(value: str) -> str:
    """Escapes '(' in a value for the engine's bracketed element string syntax."""
    # In the engine's bracketed syntax a literal "(" in a value is written "\("
    return value.replace("(", "\\(")


def parse_dictionary(text: str) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """The AIs permitted as GS1 Digital Link data attributes (flag "?") with their title and format
    components, and for every primary key the AIs that belong in its path (dlpkey qualifiers), from the text of a
    GS1 Barcode Syntax Dictionary (the portal itself reads gs1_dictionary.json)."""
    data = gs1dict.parse(text)
    return gs1dict.data_attributes(data), gs1dict.path_ais(data)


def decimal_families(attributes: dict[str, dict]) -> dict[str, dict]:
    """AIs whose fourth digit gives the number of decimal places — measures 31nn-36nn, amounts and prices
    39nn — grouped as the GS1 General Specifications write them: 310n NET WEIGHT (kg) for 3100-3105."""
    families = {}
    for code, attribute in attributes.items():
        if len(code) == 4 and code[:2] in {"31", "32", "33", "34", "35", "36", "39"}:
            family = families.setdefault(code[:3] + "n", {"ai": code[:3] + "n", "title": attribute["title"],
                                                          "components": attribute["components"], "members": [],
                                                          "decimals": 0, "family": True})
            family["members"].append(code)
            family["decimals"] = max(family["decimals"], int(code[3]))
    return families


ENGINE = Engine(ENGINE_DIR)
