"""
The EPC of a serialised GTIN for RFID and NFC tags (the backlog's "EPC/NFC label option"): the SGTIN of a record
with a GTIN and a serial number, as the EPC Tag Data Standard encodes it (SGTIN-96 for a numeric serial number below
2^38 without leading zeros, SGTIN-198 otherwise), and as the compressed GS1 Digital Link URI an NFC tag emits
(GS1 Digital Link URI: Compression Technical Standard for EPC binary strings 1.0.0: https://<stem>/eh<hexadecimal>
or /ex<base 64>), which the resolver decompresses (item 1.6, web_server/src/epc_binary.py).

The partition of the GS1 Company Prefix and the item reference needs the length of the company prefix, which the
GTIN does not say: the caller gives it (the organisation's prefix, or the person's choice).
"""
from dataclasses import dataclass

# TDS Table 14-2 (SGTIN partition table): company prefix digits → (partition value, prefix bits, item reference bits)
PARTITIONS = {12: (0, 40, 4), 11: (1, 37, 7), 10: (2, 34, 10), 9: (3, 30, 14), 8: (4, 27, 17), 7: (5, 24, 20),
              6: (6, 20, 24)}
HEADERS = {"sgtin-96": "00110000", "sgtin-198": "00110110"}
SERIAL_96_LIMIT = 2 ** 38
# GS1 AI encodable character set 82 (the serial number's characters; SGTIN-198 writes each in 7 bits)
CSET_82 = set('!"%&\'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz')
BASE64_URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# TDS section 7: characters escaped in the serial number of an EPC URI
_URI_ESCAPES = {'"': "%22", "%": "%25", "&": "%26", "/": "%2F", "<": "%3C", ">": "%3E", "?": "%3F"}


class EpcError(ValueError):
    """The record cannot be written as an SGTIN; code is a message code of the portal."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


@dataclass
class Sgtin:
    scheme: str
    filter: int
    company_prefix: str
    item_reference: str
    serial: str
    bits: str

    @property
    def hex(self) -> str:
        bits = self.bits + "0" * (-len(self.bits) % 4)
        return format(int(bits, 2), f"0{len(bits) // 4}x")

    @property
    def base64(self) -> str:
        bits = self.bits + "0" * (-len(self.bits) % 6)
        return "".join(BASE64_URL[int(bits[i:i + 6], 2)] for i in range(0, len(bits), 6))

    @property
    def tag_uri(self) -> str:
        return f"urn:epc:tag:{self.scheme}:{self.filter}.{self.company_prefix}.{self.item_reference}.{_uri(self.serial)}"

    @property
    def pure_identity(self) -> str:
        return f"urn:epc:id:sgtin:{self.company_prefix}.{self.item_reference}.{_uri(self.serial)}"


def _uri(serial: str) -> str:
    return "".join(_URI_ESCAPES.get(c, c) for c in serial)


def sgtin(gtin14: str, serial: str, prefix_length: int, filter_value: int = 1) -> Sgtin:
    """The SGTIN of a GTIN-14 and a serial number (AI 21) with a company prefix of prefix_length digits."""
    if len(gtin14) != 14 or not gtin14.isdigit():
        raise EpcError("epc.gtin")
    if prefix_length not in PARTITIONS:
        raise EpcError("epc.prefixLength")
    if not 0 <= filter_value <= 7:
        raise EpcError("epc.filterInvalid")
    if not serial or len(serial) > 20 or any(c not in CSET_82 for c in serial):
        raise EpcError("epc.serial")
    partition, prefix_bits, item_bits = PARTITIONS[prefix_length]
    company_prefix = gtin14[1:1 + prefix_length]
    item_reference = gtin14[0] + gtin14[1 + prefix_length:13]      # the indicator digit, then the item reference
    numeric = serial.isdigit() and (serial == "0" or not serial.startswith("0")) and int(serial) < SERIAL_96_LIMIT
    scheme = "sgtin-96" if numeric else "sgtin-198"
    if numeric:
        serial_bits = format(int(serial), "038b")
    else:
        serial_bits = "".join(format(ord(c), "07b") for c in serial).ljust(140, "0")
    bits = (HEADERS[scheme] + format(filter_value, "03b") + format(partition, "03b")
            + format(int(company_prefix), f"0{prefix_bits}b") + format(int(item_reference), f"0{item_bits}b")
            + serial_bits)
    return Sgtin(scheme, filter_value, company_prefix, item_reference, serial, bits)


def prefix_length_for(gtin14: str, prefixes) -> int | None:
    """The length of the longest of the given GS1 Company Prefixes (6 to 12 digits) the GTIN's company part starts
    with, or None."""
    part = gtin14[1:]
    lengths = [len(p) for p in prefixes or [] if 6 <= len(p) <= 12 and part.startswith(p)]
    return max(lengths) if lengths else None
