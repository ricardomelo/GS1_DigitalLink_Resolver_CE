"""
Decompression of EPC binary strings carried in GS1 Digital Link URIs.

GS1 Digital Link URI: Compression Technical Standard for EPC binary strings (EPCB) 1.0.0 lets an NFC tag
(typically a hybrid UHF/NFC tag) emit https://<stem>/eh<hex> or https://<stem>/ex<base 64>, where the
characters after 'eh' or 'ex' are the EPC binary string of the EPC Tag Data Standard (TDS), beginning with
the EPC header. A GS1-Conformant resolver SHALL decompress them (GS1-Conformant Resolver 1.2.1, section 2.3
and conformance statement item 5). This module turns the compression string into the equivalent GS1 Digital
Link path and query string; the web server resolves that like any other request.

How each kind of EPC scheme is decoded:

- schemes defined before TDS 2.0 (SGTIN-96, SSCC-96, ..., CPI-var): entirely from the machine-readable
  artefacts of the EPC Tag Data Translation standard (TDT 2.2, in ./tdt): the BINARY level gives the fields
  and their rules, the GS1_DIGITAL_LINK level gives the rules and the grammar of the URI;
- '+' schemes of TDS 2.0 (SGTIN+, DSGTIN+, ...): header, +AIDC data toggle, filter and prioritised date from
  the artefacts; the values of the AIs named by 'encodedAI' with TDT Table F and the methods of TDS section
  14.5; then the +AIDC data that may follow the EPC (TDS section 15.3, tables K, F and B);
- '++' schemes of TDS 2.3 (SGTIN++, ...), for which no artefact exists yet: as the matching '+' scheme
  followed by the custom hostname of TDS section 14.5.16. The hostname is decoded (so that what follows it
  can be read) but not used: the resolver keeps the stem of the request, as EPCB section 4.2 says.

The result is the GS1 Digital Link of URI Syntax 1.7: the primary key, its key qualifiers in the order the
artefact gives (gs1DigitalLinkKeyQualifiers) in the path, every other AI as a data attribute in the query
string. The filter value has no counterpart there and is dropped.
"""
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote, unquote

TDT_DIR = os.environ.get('TDT_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tdt')

# RE3 of GS1 Digital Link URI Syntax 1.7, section 6.1.2: the last path segment of a URI carrying an EPC
# binary string (EPCB 4.2.1 'eh', lower-case hexadecimal; 4.2.2 'ex', RFC 4648 section 5 base 64)
COMPRESSED_EPC = re.compile(r'eh[0-9a-f]*|ex[A-Za-z0-9_-]*')

BASE64_URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'   # EPCB 4.1, TDS Table 14-7

# TDS Table 14-1: the '++' headers and the '+' scheme each one extends with a hostname (TDS 14.6)
PLUS_PLUS = {
    '11100110': 'CPI', '11100111': 'GSRN', '11101000': 'GSRNP', '11101001': 'SGLN', '11101010': 'GDTI',
    '11101011': 'GRAI', '11101100': 'SGCN', '11101101': 'ITIP', '11101110': 'GIAI', '11101111': 'SSCC',
    '11111100': 'DSGTIN', '11111101': 'SGTIN',
}

# Characters of the GS1 AI encodable character set 82, plus '#' of character set 39 (TDS Table 14-9)
_CSET_82 = set('!"%&\'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz')
_ASCII_7 = _CSET_82 | {'#'}

# TDS Table 14-8
_URN_CODE_40 = '\0ABCDEFGHIJKLMNOPQRSTUVWXYZ-.:0123456789'

# TDS Tables 14-11 to 14-15: optimisation sequences of the 7-bit hostname encoding (14.5.16)
_HOST_TABLE_A = {0b0011110: 'qr.', 0b0011111: 'www.', 0b0100000: 'id.', 0b1011011: '.com', 0b1011100: '.org',
                 0b1011101: '.net', 0b1011110: '.int', 0b1100000: '.edu', 0b1111011: '.gov', 0b1111100: '.mil',
                 0b1111101: '.biz', 0b1111110: '.eco', 0b1111111: '.med'}
_HOST_TABLES_B = {
    0: ('.ac .ad .ae .af .ag .ai .al .am .ao .aq .ar .as .at .au .aw .ax .az .ba .bb .bd .be .bf .bg .bh .bi .bj '
        '.bm .bn .bo .bq .br .bs .bt .bw .by .bz .ca .cc .cd .cf .cg .ch .ci .ck .cl .cm .cn .co .cr .cu .cv .cw '
        '.cx .cy .cz .de .dj .dk .dm .do .dz .ec .ee .eg .eh .er .es .et .eu .fi .fj .fk .fm .fo .fr .ga .gd .ge '
        '.gf .gg .gh .gi .gl .gm .gn .gp .gq .gr .gs .gt .gu .gw .gy .hk .hm .hn .hr .ht .hu .id .ie .il .im .in '
        '.io .iq .ir .is .it .je .jm .jo .jp .ke .kg .kh .ki .km .kn .kp .kr .kw .ky .kz .la .lb .lc .li').split(),
    1: ('.lk .lr .ls .lt .lu .lv .ly .ma .mc .md .me .mg .mh .mk .ml .mm .mn .mo .mp .mq .mr .ms .mt .mu .mv .mw '
        '.mx .my .mz .na .nc .ne .nf .ng .ni .nl .no .np .nr .nu .nz .om .pa .pe .pf .pg .ph .pk .pl .pm .pn .pr '
        '.ps .pt .pw .py .qa .re .ro .rs .ru .rw .sa .sb .sc .sd .se .sg .sh .si .sk .sl .sm .sn .sr .ss .st .su '
        '.sv .sx .sy .sz .tc .td .tf .tg .th .tj .tk .tl .tm .tn .to .tr .tt .tv .tw .tz .ua .ug .us .uy .uz .va '
        '.vc .ve .vg .vi .vn .vu .wf .ws .ye .yt .za .zm .zw').split(),
    # Table 14-14 prints the prefix of .org.cn and .net.cn as 0000000; they are rows 29 and 30 of this table
    2: ('.com.au .net.au .org.au .co.at .com.bd .co.bd .com.br .net.br .co.nz .com.ng .com.pk .co.in .com.in '
        '.co.il .co.jp .co.za .co.kr .com.es .com.lk .co.th .co.tt .com.tt .com.tr .biz.tr .com.ua .co.uk .co.zm '
        '.com.zm .com.cn .org.cn .net.cn .gov.cn').split(),
    3: ['.tech'],
}

# TDS 14.5.3: date type indicator of DSGTIN+ / DSGTIN++
_DATE_TYPES = {'0000': '11', '0001': '13', '0010': '15', '0011': '16', '0100': '17', '0101': '7006', '0110': '7007'}


class EpcDecodeError(ValueError):
    """The compression string does not hold an EPC binary string that translates to a GS1 Digital Link."""


@dataclass
class DecodedEpc:
    """An EPC binary string translated to the data of a GS1 Digital Link URI."""
    scheme: str                                  # e.g. 'SGTIN-96', 'DSGTIN+', 'SGTIN++'
    primary_key: str                             # AI of the primary key
    key_qualifiers: list[str]                    # AIs that are key qualifiers of it, in path order
    elements: list[tuple[str, str]]              # every AI and value, as decoded
    filter_value: int | None = None
    hostname: str | None = None                  # '++' schemes only; not used for resolution
    aidc_toggle: bool | None = None              # '+' and '++' schemes only
    bit_length: int = 0
    notes: list[str] = field(default_factory=list)

    def path(self) -> str:
        """'/AI/value' of the primary key followed by its key qualifiers in order; values percent-encoded."""
        values = dict(self.elements)
        parts = [self.primary_key] + [ai for ai in self.key_qualifiers if ai in values]
        return ''.join(f'/{ai}/{quote(values[ai], safe="")}' for ai in parts)

    def query(self) -> str:
        """The data attributes ('AI=value' pairs, values percent-encoded), in the order they were decoded."""
        in_path = {self.primary_key, *self.key_qualifiers}
        return '&'.join(f'{ai}={quote(value, safe="")}' for ai, value in self.elements if ai not in in_path)

    def uri(self, stem: str) -> str:
        """The fully uncompressed GS1 Digital Link URI on the given stem (EPCB 4.2, step 3)."""
        query = self.query()
        return stem.rstrip('/') + self.path() + ('?' + query if query else '')


# ---------------------------------------------------------------------------------------------------- bits
class _Bits:
    """A cursor over a string of '0' and '1'."""

    def __init__(self, bits: str, position: int = 0) -> None:
        self.bits = bits
        self.position = position

    @property
    def remaining(self) -> int:
        return len(self.bits) - self.position

    def peek(self, count: int) -> str:
        return self.bits[self.position:self.position + count]

    def read(self, count: int) -> str:
        if count > self.remaining:
            raise EpcDecodeError('the EPC binary string ends before the value it announces')
        chunk = self.bits[self.position:self.position + count]
        self.position += count
        return chunk

    def read_int(self, count: int) -> int:
        return int(self.read(count), 2) if count else 0

    def rest(self) -> str:
        return self.bits[self.position:]


def compression_bits(segment: str) -> str:
    """EPCB 4.2.1 / 4.2.2, step 2: the characters after 'eh' (4 bits each) or 'ex' (6 bits each) as bits."""
    if not COMPRESSED_EPC.fullmatch(segment):
        raise EpcDecodeError('not an EPC compression string (eh + lower-case hexadecimal or ex + base 64)')
    body = segment[2:]
    if not body:
        raise EpcDecodeError('no EPC binary string after the prefix')
    if segment.startswith('eh'):
        return ''.join(format(int(c, 16), '04b') for c in body)
    return ''.join(format(BASE64_URL.index(c), '06b') for c in body)


def _check_zero(bits: str, what: str) -> None:
    if '1' in bits:
        raise EpcDecodeError(f'unexpected data {what}')


# ---------------------------------------------------------------------------------------------------- TDT artefacts
@lru_cache(maxsize=1)
def _artefacts() -> tuple[dict[str, dict], dict[str, dict]]:
    """The TDT definition files by BINARY prefixMatch (8-bit EPC header) and the tables by letter."""
    with open(os.path.join(TDT_DIR, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    schemes = {}
    for entry in manifest['definitionFiles']:
        with open(os.path.join(TDT_DIR, entry['file']), encoding='utf-8') as fh:
            scheme = json.load(fh)['tdt:epcTagDataTranslation']['scheme']
        schemes[_level(scheme, 'BINARY')['prefixMatch']] = scheme
    tables = {}
    for entry in manifest['tables']:
        with open(os.path.join(TDT_DIR, entry['file']), encoding='utf-8') as fh:
            tables[entry['table']] = json.load(fh)
    return schemes, tables


@lru_cache(maxsize=1)
def _table_f() -> dict[str, dict[str, str]]:
    return {row['a']: row for row in _artefacts()[1]['F']['rows']}


@lru_cache(maxsize=1)
def _table_k() -> dict[str, dict[str, str]]:
    return {row['a']: row for row in _artefacts()[1]['K']['rows']}


def _level(scheme: dict, level_type: str) -> dict | None:
    return next((level for level in scheme['level'] if level['type'] == level_type), None)


def _options(level: dict | None) -> list[dict]:
    if level is None:
        return []
    options = level['option']
    return options if isinstance(options, list) else [options]


def _option(level: dict | None, option_key: str) -> dict | None:
    return next((o for o in _options(level) if o['optionKey'] == option_key), None)


def _grammar_tokens(grammar: str) -> list[tuple[bool, str]]:
    """(is_literal, text) for each token of a TDT grammar ('literal' or field name)."""
    return [(token.startswith("'"), token[1:-1] if token.startswith("'") else token)
            for token in re.findall(r"'[^']*'|\S+", grammar)]


def _field_ais(ai_json_option: dict) -> dict[str, str]:
    """Field name -> AI, read from a GS1_AI_JSON grammar such as '{"01":"' gtin '","21":"' serial '"}'."""
    result, current = {}, None
    for literal, text in _grammar_tokens(ai_json_option['grammar']):
        if literal:
            found = re.findall(r'"(\d+)":"', text)
            if found:
                current = found[-1]
        elif current:
            result[text] = current
    return result


def _dl_shape(scheme: dict) -> tuple[str, list[str]]:
    """Primary key AI and its key qualifiers (in path order) from the GS1_DIGITAL_LINK level."""
    level = _level(scheme, 'GS1_DIGITAL_LINK')
    if level is None:
        raise EpcDecodeError(f'{scheme["name"]} has no GS1 Digital Link equivalent')
    sequence = _options(level)[0].get('aiSequence') or []
    if not sequence:
        raise EpcDecodeError(f'the TDT definition of {scheme["name"]} gives no AI sequence')
    return sequence[0], list(level.get('gs1DigitalLinkKeyQualifiers') or [])


# ---------------------------------------------------------------------------------------------------- schemes before TDS 2.0
def _gs1_checksum(digits: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


def _call_rule(function: str, values: dict[str, str]) -> str:
    """The TDT functions used by the rules of the artefacts (TDT Table 3-3). The URL/URN encodings only need
    to be each other's inverse here: the URI built from the grammar is parsed and its values decoded again."""
    match = re.fullmatch(r'(\w+)\((.*)\)', function.strip())
    if not match:
        raise EpcDecodeError(f'unsupported TDT rule {function}')
    name, raw_args = match.group(1), [a.strip() for a in match.group(2).split(',')]

    def arg(token: str) -> str:
        if token in values:
            return values[token]
        if token.startswith("'") and token.endswith("'"):
            return token[1:-1]
        if token.isdigit():
            return token
        raise EpcDecodeError(f'TDT rule {function} refers to an unknown field {token}')

    args = [arg(a) for a in raw_args]
    if name == 'SUBSTR':
        start = int(args[1])
        return args[0][start:start + int(args[2])] if len(args) > 2 else args[0][start:]
    if name == 'CONCAT':
        return ''.join(args)
    if name == 'GS1CHECKSUM':
        return _gs1_checksum(args[0])
    if name in ('URLENCODE', 'URNENCODE'):
        return quote(args[0], safe='')
    if name in ('URLDECODE', 'URNDECODE'):
        return unquote(args[0])
    raise EpcDecodeError(f'unsupported TDT function {name}')


def _decode_characters(bits: str, compaction: str, pad_right: bool) -> str:
    """TDT 3.13: a character string compacted at 5, 6, 7 or 8 bits per character (ISO/IEC 15962)."""
    width = {'5-bit': 5, '6-bit': 6, '7-bit': 7, '8-bit': 8}.get(compaction)
    if width is None:
        raise EpcDecodeError(f'unsupported compaction {compaction}')
    codes = [int(bits[i:i + width], 2) for i in range(0, len(bits) - len(bits) % width, width)]
    if pad_right:
        while codes and codes[-1] == 0:
            codes.pop()
        _check_zero(bits[len(codes) * width:], 'in the padding of a character field')
    if width == 5:
        text = ''.join(chr(c | 0x40) for c in codes)
    elif width == 6:
        text = ''.join(chr(c | 0x40) if c < 0x20 else chr(c) for c in codes)
    else:
        text = ''.join(chr(c) for c in codes)
    if any(ord(c) < 0x20 or ord(c) > 0x7e for c in text):
        raise EpcDecodeError('a character field holds characters outside the permitted set')
    return text


def _pad(value: str, spec: dict | None) -> str:
    if spec and spec.get('padChar') and spec.get('length'):
        length = int(spec['length'])
        if len(value) < length:
            value = value.rjust(length, spec['padChar']) if spec.get('padDir') == 'LEFT' else value.ljust(length, spec['padChar'])
    return value


def _run_rules(level: dict, rule_type: str, values: dict[str, str]) -> None:
    for rule in sorted((r for r in level.get('rule', []) if r['type'] == rule_type), key=lambda r: int(r['seq'])):
        values[rule['newFieldName']] = _call_rule(rule['function'], values)


def _decode_tdt_scheme(scheme: dict, bits: str) -> DecodedEpc:
    """
    BINARY -> GS1_DIGITAL_LINK with the TDT definition file of a scheme defined before TDS 2.0 (TDT 3.10):
    match an option of the BINARY level, decode and pad its fields, run the EXTRACT rules of the BINARY level
    and the FORMAT rules of the GS1_DIGITAL_LINK level, then fill in that level's grammar.
    """
    name = scheme['name']
    digital_link = _level(scheme, 'GS1_DIGITAL_LINK')
    if digital_link is None:
        raise EpcDecodeError(f'{name} has no GS1 Digital Link equivalent')
    tag_length = int(scheme['tagLength']) if scheme.get('tagLength') else None
    if tag_length and len(bits) < tag_length:
        raise EpcDecodeError(f'{name} needs {tag_length} bits; the string holds {len(bits)}')

    binary = _level(scheme, 'BINARY')
    for option in _options(binary):
        match = re.match(option['pattern'], bits)
        if match:
            break
    else:
        raise EpcDecodeError(f'the bits after the {name} header match none of its partitions')
    _check_zero(bits[match.end():], f'after the end of the {name} EPC')

    target = _option(digital_link, option['optionKey'])
    if target is None:
        raise EpcDecodeError(f'the TDT definition of {name} has no GS1 Digital Link option {option["optionKey"]}')
    tag_encoding = _option(_level(scheme, 'TAG_ENCODING'), option['optionKey'])
    target_fields = {f['name']: f for f in target.get('field', [])}
    tag_fields = {f['name']: f for f in (tag_encoding or {}).get('field', [])}

    values: dict[str, str] = {}
    filter_value = None
    for spec in sorted(option['field'], key=lambda f: int(f['seq'])):
        raw = match.group(int(spec['seq']))
        if spec.get('compaction'):
            value = _decode_characters(raw, spec['compaction'], spec.get('bitPadDir') == 'RIGHT')
        else:
            number = int(raw, 2) if raw else 0
            if 'decimalMaximum' in spec and not int(spec.get('decimalMinimum', 0)) <= number <= int(spec['decimalMaximum']):
                raise EpcDecodeError(f'{spec["name"]} of {name} is out of range')
            value = str(number)
        # TDT Figure 3-6: pad as the output level (or, failing that, the tag-encoding level) defines the field
        value = _pad(value, target_fields.get(spec['name']) or tag_fields.get(spec['name']))
        if spec['name'] == 'filter':
            filter_value = int(value)
        values[spec['name']] = value

    if scheme.get('optionKey'):
        values[scheme['optionKey']] = option['optionKey']
    _run_rules(binary, 'EXTRACT', values)
    _run_rules(digital_link, 'FORMAT', values)

    uri = ''
    for literal, token in _grammar_tokens(target['grammar']):
        if literal:
            uri += token
        elif token == 'uriStem':
            continue
        elif token in values:
            uri += values[token]
        else:
            raise EpcDecodeError(f'the TDT grammar of {name} refers to an unknown field {token}')
    path, _, query = uri.partition('?')
    segments = path.strip('/').split('/')
    if len(segments) % 2:
        raise EpcDecodeError(f'the TDT grammar of {name} gave an odd number of path segments')
    elements = [(segments[i], unquote(segments[i + 1])) for i in range(0, len(segments), 2)]
    elements += [(ai, unquote(value)) for ai, _, value in (pair.partition('=') for pair in query.split('&') if pair)]
    primary, qualifiers = _dl_shape(scheme)
    return DecodedEpc(name, primary, qualifiers, elements, filter_value=filter_value, bit_length=len(bits))


# ---------------------------------------------------------------------------------------------------- TDS 14.5 methods
def _int_bits(length: int) -> int:
    """Bits of a numeric string of that many digits as an integer: ceiling(L * log2(10)) (TDS Table B)."""
    return (10 ** length - 1).bit_length() if length > 0 else 0


_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _date6(reader: _Bits) -> str:
    """YYMMDD in 16 bits (TDS 14.5.8.2); DD may be 00 (General Specifications 7.12)."""
    yy, mm, dd = reader.read_int(7), reader.read_int(4), reader.read_int(5)
    if yy > 99 or not 1 <= mm <= 12 or dd > _DAYS[mm - 1]:
        raise EpcDecodeError('implausible date')
    return f'{yy:02d}{mm:02d}{dd:02d}'


def _time(reader: _Bits, parts: int) -> str:
    """hh (5 bits), then mm and ss (6 bits each) as asked (TDS 14.5.9.2, 14.5.11.2)."""
    hh = reader.read_int(5)
    rest = [reader.read_int(6) for _ in range(parts - 1)]
    if hh > 24 or any(v > 59 for v in rest) or (hh == 24 and any(rest)):
        raise EpcDecodeError('implausible time')
    return ''.join(f'{v:02d}' for v in [hh, *rest])


def _hex_digits(reader: _Bits, count: int, alphabet: str) -> str:
    return ''.join(alphabet[reader.read_int(4)] for _ in range(count))


def _urn_code_40(reader: _Bits, length: int) -> str:
    """TDS 14.5.6.5.2: 16 bits for each group of 3 characters."""
    text = ''
    for _ in range(-(-length // 3)):
        r = reader.read_int(16)
        if r == 0 or r > 64000:
            raise EpcDecodeError('invalid URN Code 40 value')
        i3 = (r - 1) % 40
        i2 = ((r - 1 - i3) // 40) % 40
        i1 = (r - 1 - i3 - 40 * i2) // 1600
        text += ''.join(_URN_CODE_40[i] for i in (i1, i2, i3) if i)
    if len(text) != length:
        raise EpcDecodeError('URN Code 40 value of the wrong length')
    return text


def _variable_alphanumeric(reader: _Bits, length_bits: int, maximum: int) -> str:
    """TDS 14.5.6: a 3-bit encoding indicator (Table E), a length indicator, then the characters."""
    indicator = reader.read_int(3)
    length = reader.read_int(length_bits) if maximum > 1 else 1
    if length > maximum:
        raise EpcDecodeError('value longer than its AI allows')
    if indicator == 0:                                                     # 14.5.6.1 numeric string
        value = str(reader.read_int(_int_bits(length))).zfill(length)
        if len(value) > length:
            raise EpcDecodeError('numeric value longer than its length indicator')
        return value
    if indicator == 1:                                                     # 14.5.6.2
        return _hex_digits(reader, length, '0123456789ABCDEF')
    if indicator == 2:                                                     # 14.5.6.3
        return _hex_digits(reader, length, '0123456789abcdef')
    if indicator == 3:                                                     # 14.5.6.4
        return ''.join(BASE64_URL[reader.read_int(6)] for _ in range(length))
    if indicator == 4:                                                     # 14.5.6.6
        value = ''.join(chr(reader.read_int(7)) for _ in range(length))
        if any(c not in _ASCII_7 for c in value):
            raise EpcDecodeError('7-bit value with a character outside the GS1 character sets')
        return value
    if indicator == 5:                                                     # 14.5.6.5
        return _urn_code_40(reader, length)
    raise EpcDecodeError(f'encoding indicator {indicator} is reserved')


def _component(reader: _Bits, row: dict[str, str], columns: str) -> str:
    """One component of an AI value, by its Table F format. columns: the 7 Table F letters of the component
    (format, section, fixed characters, fixed bits, encoding indicator bits, length indicator bits, maximum)."""
    fmt, _, chars, bits, _, li_bits, maximum = (row.get(c, '') for c in columns)
    if fmt == 'Fixed-length numeric':                                      # 14.5.4
        value = _hex_digits(reader, int(chars), '0123456789ABCDEF')
        if not value.isdigit():
            raise EpcDecodeError('fixed-length numeric value with a non-digit nibble')
        return value
    if fmt == 'Fixed-Bit-Length Numeric String':                           # 14.5.2
        value = str(reader.read_int(int(bits)))
        if len(value) > int(chars):
            raise EpcDecodeError('numeric value too large for its AI')
        return value.zfill(int(chars))
    if fmt == 'Variable-length alphanumeric':                              # 14.5.6
        return _variable_alphanumeric(reader, int(li_bits), int(maximum))
    if fmt == 'Variable-length numeric string without encoding indicator':  # 14.5.13
        length = reader.read_int(int(li_bits))
        if length > int(maximum):
            raise EpcDecodeError('value longer than its AI allows')
        value = str(reader.read_int(_int_bits(length))).zfill(length)
        if len(value) > length:
            raise EpcDecodeError('numeric value longer than its length indicator')
        return value
    if fmt == 'Delimited/terminated numeric':                              # 14.5.5
        value = ''
        while True:
            nibble = reader.read_int(4)
            if nibble <= 9:
                value += str(nibble)
            elif nibble == 0b1111:
                return value
            elif nibble == 0b1110:
                return value + _variable_alphanumeric(reader, int(li_bits), int(maximum))
            else:
                raise EpcDecodeError('invalid nibble in a delimited/terminated numeric value')
    if fmt == '6-digit date YYMMDD':                                       # 14.5.8
        return _date6(reader)
    if fmt == '10-digit date+time YYMMDDhhmm':                             # 14.5.9
        return _date6(reader) + _time(reader, 2)
    if fmt == 'Variable-format date / date range':                         # 14.5.10
        single = reader.read(1) == '0'
        return _date6(reader) if single else _date6(reader) + _date6(reader)
    if fmt == 'Variable-precision date+time':                              # 14.5.11
        precision = reader.read(2)
        date = _date6(reader)
        return date if precision == '11' else date + _time(reader, {'00': 1, '01': 2, '10': 3}[precision])
    if fmt == 'Country code (ISO 3166-1 alpha-2)':                         # 14.5.12
        codes = [reader.read_int(6), reader.read_int(6)]
        if any(c > 25 for c in codes):
            raise EpcDecodeError('invalid country code')
        return ''.join(BASE64_URL[c] for c in codes)
    if fmt == 'Single data bit':                                           # 14.5.7
        return reader.read(1)
    if fmt == 'Optional minus sign in 1 bit':                              # 14.5.14
        return '-' if reader.read(1) == '1' else ''
    if fmt == 'Sequence indicator':                                        # 14.5.15
        n, m = reader.read_int(4), reader.read_int(4)
        if not (1 <= n <= 9 and 1 <= m <= 9):
            raise EpcDecodeError('invalid sequence indicator')
        return f'{n}/{m}'
    raise EpcDecodeError(f'unsupported Table F format {fmt!r}')


def _ai_value(ai: str, reader: _Bits) -> str:
    """The value of a GS1 Application Identifier encoded as Table F says (TDS 15.3)."""
    row = _table_f().get(ai)
    if row is None:
        raise EpcDecodeError(f'AI ({ai}) cannot be encoded in an EPC (not in Table F)')
    value = _component(reader, row, 'bcdefgh')
    if row.get('i'):
        value += _component(reader, row, 'ijklmno')
    return value


def _aidc_data(reader: _Bits) -> list[tuple[str, str]]:
    """TDS 15.3: '+AIDC data' after the EPC, until fewer than 8 bits remain or only padding is left."""
    elements = []
    while reader.remaining >= 8:
        header = reader.peek(8)
        if header == '00000000' and reader.remaining < 8 + 72:
            break                                    # padding (it cannot be an SSCC)
        reader.read(8)
        first, second = int(header[:4], 2), int(header[4:], 2)
        if first > 9 or second > 9:
            raise EpcDecodeError(f'+AIDC data header {int(header, 2):02X} is not supported')
        key = _table_k().get(f'{first}{second}')
        if key is None:
            raise EpcDecodeError(f'no GS1 Application Identifier begins with {first}{second}')
        extra = _hex_digits(reader, int(key['c']) // 4, '0123456789ABCDEF')
        if extra and not extra.isdigit():
            raise EpcDecodeError('invalid digit in a +AIDC data header')
        ai = f'{first}{second}{extra}'
        elements.append((ai, _ai_value(ai, reader)))
    _check_zero(reader.rest(), 'after the end of the +AIDC data')
    return elements


def _hostname(reader: _Bits) -> str:
    """TDS 14.5.16.2: a custom hostname, URN Code 40 or 7-bit ASCII with optimisation sequences."""
    indicator = reader.read(1)
    length = reader.read_int(6)
    if length == 0:
        raise EpcDecodeError('empty hostname')
    if indicator == '0':
        return _urn_code_40(reader, length).lower()
    host, units = '', length
    while units > 0:
        code = reader.read_int(7)
        if code <= 0b0000011:                        # 14-bit sequence, Tables 14-12 to 14-15
            index = reader.read_int(7)
            table = _HOST_TABLES_B[code]
            if index >= len(table):
                raise EpcDecodeError('reserved hostname optimisation sequence')
            host += table[index]
            units -= 2
        elif code in _HOST_TABLE_A:
            host += _HOST_TABLE_A[code]
            units -= 1
        elif chr(code) in _ASCII_7:
            host += chr(code)
            units -= 1
        else:
            raise EpcDecodeError('reserved hostname character')
    if units < 0:
        raise EpcDecodeError('hostname longer than its length indicator')
    return host


def _decode_plus_scheme(scheme: dict, bits: str, with_hostname: bool) -> DecodedEpc:
    """A '+' scheme of TDS 2.0 (or a '++' scheme of TDS 2.3, read as its '+' scheme plus a hostname)."""
    binary = _level(scheme, 'BINARY')
    work = binary['prefixMatch'] + bits[8:]          # a '++' header in place of the '+' one
    for option in _options(binary):
        match = re.match(option['pattern'], work)
        if match:
            break
    else:
        raise EpcDecodeError(f'the bits after the {scheme["name"]} header match none of its options')

    field_ais = _field_ais(_option(_level(scheme, 'GS1_AI_JSON'), option['optionKey']) or {'grammar': ''})
    elements: list[tuple[str, str]] = []
    toggle = filter_value = None
    for spec in sorted(option['field'], key=lambda f: int(f['seq'])):
        raw = match.group(int(spec['seq']))
        if spec['name'] == 'dataToggle':
            toggle = raw == '1'
        elif spec['name'] == 'filter':
            filter_value = int(raw, 2)
        elif spec.get('encoding') == 'dateYYMMDD':  # DSGTIN+ prioritised date (TDS 14.5.3)
            ai = field_ais.get(spec['name']) or _DATE_TYPES.get(work[12:16])
            if ai is None:
                raise EpcDecodeError('unknown date type indicator')
            elements.append((ai, _date6(_Bits(raw))))

    reader = _Bits(work, match.end())
    for encoded in sorted(option.get('encodedAI', []), key=lambda e: int(e['seq'])):
        elements.append((encoded['ai'], _ai_value(encoded['ai'], reader)))
    hostname = _hostname(reader) if with_hostname else None
    elements.extend(_aidc_data(reader))

    seen = set()
    for ai, _ in elements:
        if ai in seen:
            raise EpcDecodeError(f'AI ({ai}) appears twice')
        seen.add(ai)
    name = scheme['name'] + ('+' if with_hostname else '')
    primary, qualifiers = _dl_shape(scheme)
    return DecodedEpc(name, primary, qualifiers, elements, filter_value=filter_value, hostname=hostname,
                      aidc_toggle=toggle, bit_length=len(bits))


# ---------------------------------------------------------------------------------------------------- entry points
def decode_binary(bits: str) -> DecodedEpc:
    """An EPC binary string (beginning with the 8-bit EPC header of TDS Table 14-1) as a DecodedEpc."""
    if len(bits) < 8:
        raise EpcDecodeError('shorter than an EPC header')
    header = bits[:8]
    schemes = _artefacts()[0]
    if header in PLUS_PLUS:
        plus = next(s for s in schemes.values() if s['name'] == PLUS_PLUS[header] + '+')
        return _decode_plus_scheme(plus, bits, with_hostname=True)
    scheme = schemes.get(header)
    if scheme is None:
        raise EpcDecodeError(f'EPC header {int(header, 2):02X} is not assigned to an EPC scheme with a TDT definition')
    if scheme['name'].endswith('+'):
        return _decode_plus_scheme(scheme, bits, with_hostname=False)
    return _decode_tdt_scheme(scheme, bits)


def decompress(segment: str) -> DecodedEpc:
    """EPCB 4.2: the last path segment of a compressed GS1 Digital Link URI ('eh…' or 'ex…') decoded."""
    return decode_binary(compression_bits(segment))
