"""
EAN/UPC symbols for the label beside the QR code (Documentation/adr/0010-label-studio.md, backlog item 5.3): EAN-13,
UPC-A, EAN-8 and UPC-E (number system 0), as the GS1 General Specifications (section 5.2) encode them.

symbol_for(gtin14, choice) chooses the symbol a GTIN takes (or refuses); encode() gives its modules ("1" a dark
module), which modules are guard bars (extended below the others), its quiet zones and where its human readable digits
go, all in modules of the linear symbol (X = 0.330 mm at 100 %).
"""
from dataclasses import dataclass

L_CODES = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
G_CODES = ("0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111")
R_CODES = ("1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100")
# EAN-13: the parity of the six left characters, chosen by the first digit (which has no bars of its own)
EAN13_PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")
# UPC-E, number system 0: the parity of the six characters, chosen by the check digit (G = even, L = odd)
UPCE_PARITY = ("GGGLLL", "GGLGLL", "GGLLGL", "GGLLLG", "GLGGLL", "GLLGGL", "GLLLGG", "GLGLGL", "GLGLLG", "GLLGLG")
START, CENTRE, END_UPCE = "101", "01010", "010101"

BAR_HEIGHT = {"ean13": 69.24, "upca": 69.24, "upce": 69.24, "ean8": 55.24}   # in X: 22.85 mm and 18.23 mm at 100 %
QUIET = {"ean13": (11, 7), "upca": (9, 9), "upce": (9, 7), "ean8": (7, 7)}  # left, right, in X
GUARD_EXTENSION = 5.0         # guard bars reach this far below the others, in X
DIGIT_HEIGHT = 8.33           # height of the human readable digits, in X (about 2.75 mm at 100 %)
SMALL_DIGIT = 0.75            # UPC-A's and UPC-E's outer digits are smaller
NAMES = {"ean13": "EAN-13", "upca": "UPC-A", "upce": "UPC-E", "ean8": "EAN-8"}


class NotPossible(ValueError):
    """The record's key cannot be carried by an EAN/UPC symbol (or not by the one asked)."""


def check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def upce_from_upca(upca: str) -> str | None:
    """The six UPC-E digits of a UPC-A (12 digits, number system 0), or None when it does not zero-suppress."""
    if len(upca) != 12 or upca[0] != "0":
        return None
    m, p = upca[1:6], upca[6:11]
    if m[2:] in ("000", "100", "200") and p[:2] == "00":
        return m[:2] + p[2:] + m[2]
    if m[3:] == "00" and p[:3] == "000":
        return m[:3] + p[3:] + "3"
    if m[4] == "0" and p[:4] == "0000":
        return m[:4] + p[4] + "4"
    if m[4] != "0" and p[:4] == "0000" and p[4] in "56789":
        return m + p[4]
    return None


def symbol_for(gtin14: str, choice: str) -> tuple[str, str]:
    """(symbol, digits) for a GTIN-14 value: "auto" chooses by the GTIN's length — EAN-8 for a GTIN-8 (six leading
    zeros), UPC-A for a GTIN-12 (two), EAN-13 for a GTIN-13 (one) —, "upce" asks for UPC-E (a GTIN-12 that
    zero-suppresses). Raises NotPossible for anything else (an indicator other than 0, a value that is not 14 digits)."""
    if len(gtin14) != 14 or not gtin14.isdigit() or gtin14[0] != "0":
        raise NotPossible(gtin14)
    if choice == "upce":
        if gtin14[:2] != "00" or gtin14[:6] == "000000":
            raise NotPossible(gtin14)
        digits = upce_from_upca(gtin14[2:])
        if digits is None:
            raise NotPossible(gtin14)
        return "upce", "0" + digits + gtin14[-1]
    if choice != "auto":
        raise NotPossible(choice)
    if gtin14[:6] == "000000":
        return "ean8", gtin14[6:]
    if gtin14[:2] == "00":
        return "upca", gtin14[2:]
    return "ean13", gtin14[1:]


@dataclass
class Encoded:
    """A linear symbol: modules ("1" dark), which modules belong to extended bars, quiet zones, bar height, and the
    human readable digits as (text, centre x in modules from the first module, relative size)."""
    kind: str
    modules: str
    extended: set
    quiet: tuple[int, int]
    bar_height: float
    digits: list[tuple[str, float, float]]


def _characters(text: str, codes) -> str:
    return "".join(codes[int(d)] for d in text)


def encode(kind: str, digits: str) -> Encoded:
    """The modules and human readable digits of an EAN-13 (13 digits), UPC-A (12), EAN-8 (8) or UPC-E (8: number
    system, six digits, check digit). The check digit is verified."""
    if kind == "upce":
        if len(digits) != 8 or digits[0] != "0":
            raise NotPossible(digits)
        upca = "0" + _upca_body(digits[1:7])
        if check_digit(upca) != digits[7]:
            raise NotPossible(digits)
    elif check_digit(digits[:-1]) != digits[-1]:
        raise NotPossible(digits)
    if kind == "ean13":
        parity = EAN13_PARITY[int(digits[0])]
        left = "".join((L_CODES if p == "L" else G_CODES)[int(d)] for p, d in zip(parity, digits[1:7]))
        modules = START + left + CENTRE + _characters(digits[7:], R_CODES) + START
        extended = _guards(len(modules), 6, 6)
        texts = [(digits[0], -QUIET["ean13"][0] / 2 - 1, 1.0)] + _under(digits[1:7], 3) + _under(digits[7:], 3 + 42 + 5)
    elif kind == "upca":
        modules = START + _characters(digits[:6], L_CODES) + CENTRE + _characters(digits[6:], R_CODES) + START
        extended = _guards(len(modules), 6, 6) | set(range(3, 10)) | set(range(85, 92))   # first and last characters
        texts = ([(digits[0], -QUIET["upca"][0] / 2, SMALL_DIGIT)] + _under(digits[1:6], 10)
                 + _under(digits[6:11], 3 + 42 + 5) + [(digits[11], len(modules) + QUIET["upca"][1] / 2, SMALL_DIGIT)])
    elif kind == "ean8":
        modules = START + _characters(digits[:4], L_CODES) + CENTRE + _characters(digits[4:], R_CODES) + START
        extended = _guards(len(modules), 4, 4)
        texts = _under(digits[:4], 3) + _under(digits[4:], 3 + 28 + 5)
    elif kind == "upce":
        parity = UPCE_PARITY[int(digits[7])]
        body = "".join((L_CODES if p == "L" else G_CODES)[int(d)] for p, d in zip(parity, digits[1:7]))
        modules = START + body + END_UPCE
        extended = set(range(0, 3)) | set(range(len(modules) - 6, len(modules)))
        texts = ([(digits[0], -QUIET["upce"][0] / 2, SMALL_DIGIT)] + _under(digits[1:7], 3)
                 + [(digits[7], len(modules) + QUIET["upce"][1] / 2, SMALL_DIGIT)])
    else:
        raise NotPossible(kind)
    return Encoded(kind, modules, extended, QUIET[kind], BAR_HEIGHT[kind], texts)


def _guards(length: int, left_chars: int, right_chars: int) -> set:
    centre = 3 + 7 * left_chars
    return set(range(0, 3)) | set(range(centre, centre + 5)) | set(range(length - 3, length))


def _under(text: str, first: int) -> list[tuple[str, float, float]]:
    """Digits centred under their 7-module characters, the first starting at module `first`."""
    return [(d, first + 7 * i + 3.5, 1.0) for i, d in enumerate(text)]


def _upca_body(e: str) -> str:
    """The UPC-A digits (manufacturer and product, 10) a UPC-E's six digits stand for."""
    last = e[5]
    if last in "012":
        return e[:2] + last + "00" + "00" + e[2:5]
    if last == "3":
        return e[:3] + "00" + "000" + e[3:5]
    if last == "4":
        return e[:4] + "0" + "0000" + e[4]
    return e[:5] + "0000" + last
