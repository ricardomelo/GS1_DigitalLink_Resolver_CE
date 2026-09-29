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
the resolver also uses, through its Python binding. The engine and the GS1 Barcode Syntax Dictionary
(names and formats of the AIs, shown in the editor) come from the same pinned release, built by
tools/build-syntax-engine.sh into GS1_SYNTAX_ENGINE_DIR.

Without the engine the portal works as before and simply does not offer data attributes.
"""
import ctypes
import logging
import os
import re
import sys
import threading

import gs1
from gs1 import ValidationError

log = logging.getLogger("portal.syntax")

ENGINE_DIR = os.environ.get("GS1_SYNTAX_ENGINE_DIR", "/opt/gs1-syntax-engine")
MAX_ATTRIBUTES = 10          # a QR code stays readable at the label's X-dimension; see the README

_FLAG_CHARS = set("*!?\"$%&'()+,-./:;<=>@[\\]^_`{|}~")
_COMPONENT = re.compile(r"^(\[)?([NXYZ])(\.\.)?(\d+)\]?(?:,(.*))?$")     # "N6,yymmd0", "[X..17]", "[N3],iso3166"


class Engine:
    """The loaded engine, or the reason it is not available."""

    def __init__(self, directory: str):
        self.directory = directory
        self.available = False
        self.release = None
        self.reason = None
        self.attributes: dict[str, dict] = {}      # AI → {ai, title, components}
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
        with open(os.path.join(self.directory, "gs1-syntax-dictionary.txt"), encoding="utf-8") as fh:
            self.attributes, self.path_ais = parse_dictionary(fh.read())
        try:
            with open(os.path.join(self.directory, "RELEASE"), encoding="utf-8") as fh:
                self.release = fh.read().strip()
        except OSError:
            self.release = None
        self.available = True

    def describe(self) -> dict:
        """What the browser needs to offer data attributes (GET /portal/api/config)."""
        if not self.available:
            return {"available": False}
        return {"available": True, "release": self.release, "max": MAX_ATTRIBUTES,
                "ais": list(self.attributes.values()),
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
        seen = set()
        for ai, value in attributes:
            if ai == key_ai or ai in self.path_ais.get(key_ai, set()):
                # A qualifier of this key (batch, serial…) or the key itself: the engine would write it in
                # the path and the QR code would point at another record. Checked first because it tells
                # the user where the value belongs, also for qualifiers that are never data attributes.
                raise ValidationError("attr.inPath", ai=ai)
            if ai not in self.attributes:
                raise ValidationError("attr.unknown", ai=ai)
            if ai in seen:
                raise ValidationError("attr.duplicate", ai=ai)
            seen.add(ai)
            if not value:
                raise ValidationError("attr.valueRequired", ai=ai)
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
                raise ValidationError("attr.invalid", detail=str(exc), markup=self._encoder.err_markup) from exc
        if uri.split("?", 1)[0] != path_uri:
            # Belt and braces: the identification in the path must stay the record's own.
            raise ValidationError("attr.inPath", ai=next(iter(seen)))
        return uri, [f"({ai}){value}" for ai, value in attributes]


def _escape(value: str) -> str:
    # In the engine's bracketed syntax a literal "(" in a value is written "\("
    return value.replace("(", "\\(")


def parse_dictionary(text: str) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """The AIs permitted as GS1 Digital Link data attributes (flag "?") with their title and format
    components, and for every primary key the AIs that belong in its path (dlpkey qualifiers)."""
    attributes, path_ais = {}, {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        body, _, title = line.partition("#")
        tokens = body.split()
        ais, rest = tokens[0], tokens[1:]
        flags = rest.pop(0) if rest and set(rest[0]) <= _FLAG_CHARS else ""
        components, attrs = [], []
        for token in rest:
            if token.startswith(("req=", "ex=", "dlpkey")) or "=" in token and not token.startswith("["):
                attrs.append(token)
            else:
                components.append(token)
        codes = _expand(ais)
        for token in attrs:
            if token == "dlpkey" or token.startswith("dlpkey="):
                qualifiers = {q for alternative in token.partition("=")[2].split("|") for q in alternative.split(",") if q}
                for code in codes:
                    path_ais.setdefault(code, set()).update(qualifiers)
        if "?" in flags:
            parsed = [_component(c) for c in components]
            for code in codes:
                attributes[code] = {"ai": code, "title": title.strip(), "components": parsed}
    return attributes, path_ais


def _expand(ais: str) -> list[str]:
    if "-" not in ais:
        return [ais]
    first, last = ais.split("-")
    return [str(n).zfill(len(first)) for n in range(int(first), int(last) + 1)]


def _component(token: str) -> dict:
    """ "N6,yymmd0" → {type N, min 6, max 6, linters [yymmd0]}; "[X..17]" → optional, 1..17."""
    match = _COMPONENT.match(token)
    if not match:
        return {"type": "X", "min": 1, "max": 90, "optional": False, "linters": []}
    opening, kind, variable, length, linters = match.groups()
    length = int(length)
    return {"type": kind, "min": 1 if variable else length, "max": length, "optional": bool(opening),
            "linters": [x for x in (linters or "").split(",") if x]}


ENGINE = Engine(ENGINE_DIR)
