"""
The item's page (Documentation/adr/0011-item-page.md): the page of an item's links the resolver shows to a person
who opens ?linkType=linkset in a browser — or who scans a code whose default link is that page (the portal's option
"Default target: the item's page", a gs1:defaultLink to <the record>?linkType=linkset&view=page).

  render_page()  the page: the brand of the record's prefix (logo, colours, name), the item's description, one button
                 per link type with an icon, each in the visitor's best language (the type's other translations under
                 "Other languages"), the brand's logo as favicon, the levels (serial, batch,
                 product), the code in human readable form, Verified by GS1 (item 6.2) when switched on;
  click()        /_click?a=<path>&l=<level>&i=<link>&t=<type>: the link looked up again in the record (never an
                 address taken from the request), logged as a click, redirected to (302);
  logo()         /_brand/<prefix>: the logo uploaded in the portal, served by the resolver (nothing is loaded from
                 the brand's own server).

The branding is the portal's collection "branding" of PORTAL_DB_NAME, read with the resolver's own connection at
most every CACHE_SECONDS; the longest prefix of the record's company part wins, then the installation's ("*").
"""
import hashlib
import logging
import os
import threading
import time
from urllib.parse import quote, urlencode, urlparse

from flask import Response, make_response, render_template_string, request

import domains
import request_log
import web_pages

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
VERIFIED_KEYS = {'01': 'gtin', '414': 'gln'}
DEFAULT_COLOUR, DEFAULT_ACCENT = '#002C6C', '#F26334'

TEXT = {
    'pt-BR': {'links': 'Informações sobre este item', 'other': 'Outros idiomas', 'none': 'Nenhum link disponível.',
              'verified': 'Conferir este código no Verified by GS1', 'verifiedNote': 'Quem licenciou este código, na base da GS1.',
              'code': 'Código'},
    'en-GB': {'links': 'About this item', 'other': 'Other languages', 'none': 'No link available.',
              'verified': 'Check this code in Verified by GS1', 'verifiedNote': 'Who licensed this code, in GS1\'s registry.',
              'code': 'Code'},
}

# Icons (24 × 24 outlines) per group of link types; any other type gets LINK
_I = {
    'info': 'M11 7h2v2h-2V7Zm0 4h2v6h-2v-6Zm1-9a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Z',
    'book': 'M18 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2ZM6 4h5v8l-2.5-1.5L6 12V4Z',
    'chat': 'M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2Zm0 14H5.2L4 17.2V4h16v12Z',
    'badge': 'M12 1 3 5v6c0 5.6 3.8 10.7 9 12 5.2-1.3 9-6.4 9-12V5l-9-4Zm-2 16-4-4 1.4-1.4 2.6 2.6 6.6-6.6L18 9l-8 8Z',
    'alert': 'M1 21h22L12 2 1 21Zm12-3h-2v-2h2v2Zm0-4h-2v-4h2v4Z',
    'play': 'M8 5v14l11-7L8 5Z',
    'tool': 'm22.7 19-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4Z',
    'box': 'M21 16.5c0 .4-.2.7-.5.9l-7.9 4.4c-.2.1-.4.2-.6.2s-.4-.1-.6-.2l-7.9-4.4c-.3-.2-.5-.5-.5-.9v-9c0-.4.2-.7.5-.9l7.9-4.4c.2-.1.4-.2.6-.2s.4.1.6.2l7.9 4.4c.3.2.5.5.5.9v9ZM12 4.2 6 7.5l6 3.3 6-3.3-6-3.3Z',
    'help': 'M11 18h2v-2h-2v2Zm1-16a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm0-14a4 4 0 0 0-4 4h2a2 2 0 1 1 4 0c0 2-3 1.8-3 5h2c0-2.3 3-2.5 3-5a4 4 0 0 0-4-4Z',
    'cart': 'M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM1 2v2h2l3.6 7.6L5.2 14c-.1.3-.2.6-.2 1a2 2 0 0 0 2 2h12v-2H7.4a.2.2 0 0 1-.2-.2v-.1l.9-1.7h7.4c.8 0 1.4-.4 1.7-1l3.6-6.5A1 1 0 0 0 20 4H5.2l-.9-2H1Zm16 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
    'star': 'M12 17.3 18.2 21l-1.6-7L22 9.2l-7.2-.6L12 2 9.2 8.6 2 9.2 7.5 14l-1.7 7L12 17.3Z',
    'leaf': 'M17 8C8 10 5.9 16.2 3.8 21.3l1.9.7.9-2.3c.5.2 1 .3 1.4.3C19 20 22 3 22 3c-1 2-8 2.3-13 3.3S2 11.5 2 13.5 3.8 17.3 3.8 17.3C7 8 17 8 17 8Z',
    'food': 'M8.1 13.3 10.9 10.5 3.9 3.5a4 4 0 0 0 0 5.7l4.2 4.1Zm6.8-1.8c1.5.7 3.7.2 5.3-1.4 1.9-1.9 2.3-4.7.8-6.2-1.5-1.5-4.3-1.1-6.2.8-1.6 1.6-2.1 3.8-1.4 5.3L3.6 19.8 5 21.2l6.9-6.9 6.9 6.9 1.4-1.4-6.9-6.9 1.6-1.4Z',
    'data': 'M12 3C7 3 3 4.8 3 7v10c0 2.2 4 4 9 4s9-1.8 9-4V7c0-2.2-4-4-9-4Zm0 2c4.4 0 7 1.4 7 2s-2.6 2-7 2-7-1.4-7-2 2.6-2 7-2Zm7 12c0 .6-2.6 2-7 2s-7-1.4-7-2v-2.3c1.6.8 4.2 1.3 7 1.3s5.4-.5 7-1.3V17Zm0-5c0 .6-2.6 2-7 2s-7-1.4-7-2V9.7c1.6.8 4.2 1.3 7 1.3s5.4-.5 7-1.3V12Z',
    'share': 'M18 16c-.8 0-1.5.3-2 .8l-7.1-4.2c.1-.2.1-.4.1-.6s0-.4-.1-.6L16 7.2c.5.5 1.2.8 2 .8a3 3 0 1 0-3-3c0 .2 0 .4.1.6L8 9.8A3 3 0 1 0 8 14.2l7.1 4.2-.1.6a3 3 0 1 0 3-3Z',
    'link': 'M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12ZM8 13h8v-2H8v2Zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10Z',
    'check': 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2Z',
}
ICONS = {
    'pip': 'info', 'instructions': 'book', 'quickStartGuide': 'book', 'epil': 'book', 'smpc': 'book',
    'support': 'chat', 'faqs': 'help', 'certificationInfo': 'badge', 'safetyInfo': 'alert', 'recallStatus': 'alert',
    'allergenInfo': 'alert', 'tutorial': 'play', 'relatedVideo': 'play', 'serviceInfo': 'tool',
    'whatsInTheBox': 'box', 'registerProduct': 'check', 'purchaseSuppliesOrAccessories': 'cart',
    'hasRetailers': 'cart', 'promotion': 'cart', 'review': 'star', 'leaveReview': 'star', 'socialMedia': 'share',
    'sustainabilityInfo': 'leaf', 'nutritionalInfo': 'food', 'ingredientsInfo': 'food', 'recipeInfo': 'food',
    'masterData': 'data', 'traceability': 'data', 'epcis': 'data',
}


# ----------------------------------------------------------------------------------------------- branding
class BrandMap:
    """The portal's branding: {prefix or "*": doc}, read again after CACHE_SECONDS (the last kept on failure)."""

    def __init__(self, database=None):
        self.database = database
        self._map: dict[str, dict] = {}
        self._loaded = 0.0
        self._lock = threading.Lock()

    def _all(self) -> dict[str, dict]:
        if self.database is None:
            return {}
        now = time.monotonic()
        if now - self._loaded >= CACHE_SECONDS:
            with self._lock:
                if now - self._loaded >= CACHE_SECONDS:
                    try:
                        self._map = {doc['_id']: doc for doc in self.database()['branding'].find({})}
                    except Exception as exc:          # noqa: BLE001 — the page is shown without a brand
                        logger.warning('Branding not read (%s); the last one is kept.', exc)
                    self._loaded = now
        return self._map

    def for_part(self, part: str | None) -> dict | None:
        """The branding of the longest prefix of a company part, else the installation's ("*")."""
        found = self._all()
        best = None
        for prefix, doc in found.items():
            if prefix != '*' and part and part.startswith(prefix) and (best is None or len(prefix) > len(best['_id'])):
                best = doc
        return best or found.get('*')

    def get(self, prefix: str) -> dict | None:
        return self._all().get(prefix)

    def forget(self) -> None:
        self._loaded = 0.0


BRANDS = BrandMap()


def _text_colour(colour: str) -> str:
    """Black or white, whichever reads better on the colour (WCAG relative luminance)."""
    try:
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (ValueError, IndexError):
        return '#ffffff'
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return '#121212' if luminance > 0.179 else '#ffffff'


def _colour(value, default: str) -> str:
    text = str(value or '')
    return text if len(text) == 7 and text.startswith('#') and all(c in '0123456789abcdefABCDEF' for c in text[1:]) \
        else default


# ----------------------------------------------------------------------------------------------- links
def page_levels(linkset: list[dict]) -> list[dict]:
    """The links of each level of a linkset, in the order the page shows them and /_click finds them:
    [{"anchor": path, "description", "links": [{"term", "href", "title", "hreflang"}]}]."""
    levels = []
    for item in linkset:
        links, seen = [], set()
        for key, value in item.items():
            if not key.startswith(web_pages._GS1_KEY_PREFIXES) or key.endswith(('/defaultLink', '/defaultLinkMulti')):
                continue
            term = key.rsplit('/', 1)[-1]
            for link in value:
                identity = (term, link.get('href'), tuple(link.get('hreflang') or []))
                if identity in seen:
                    continue
                seen.add(identity)
                links.append({'term': term, 'href': web_pages._web_address(link.get('href')),
                              'title': link.get('title') or term, 'hreflang': list(link.get('hreflang') or [])})
        if links:
            levels.append({'anchor': urlparse(item.get('anchor', '')).path,
                           'description': item.get('itemDescription') or item.get('description'), 'links': links})
    return levels


def _preferences(locale: str) -> list[str]:
    """The visitor's languages, best first: the page's, then the others of the browser's Accept-Language (q-values
    honoured), as primary subtags."""
    ranked = []
    for position, part in enumerate(request.headers.get('Accept-Language', '').split(',')):
        pieces = part.strip().split(';')
        quality = 1.0
        for piece in pieces[1:]:
            if piece.strip().startswith('q='):
                try:
                    quality = float(piece.strip()[2:])
                except ValueError:
                    quality = 0.0
        tag = pieces[0].strip().lower().split('-')[0]
        if tag and tag != '*' and quality > 0:
            ranked.append((-quality, position, tag))
    found = [locale.split('-')[0].lower()]
    for _, _, tag in sorted(ranked):
        if tag not in found:
            found.append(tag)
    return found


def _rank(link: dict, preferences: list[str]) -> int:
    """How well a link's language suits the visitor: the position of its language among the visitor's (0: the
    page's own), then a link in no language in particular, then any other."""
    tags = [t.lower().split('-')[0] for t in link['hreflang']]
    for position, language in enumerate(preferences):
        if language in tags:
            return position
    return len(preferences) if not tags or 'und' in tags else len(preferences) + 1


def group_links(links: list[dict], preferences: list[str]) -> tuple[list[tuple[int, dict, bool]], list[tuple[int, dict]]]:
    """Each link type once (item 9.1): for each type, in the order the record gives them, its links in the best
    language the visitor reads (or, when it has none of those, in its first language) — (position, link, whether its
    language is shown: not the page's own); the type's other translations apart, for "Other languages"."""
    by_type: dict[str, list[tuple[int, dict]]] = {}
    for position, link in enumerate(links):
        by_type.setdefault(link['term'], []).append((position, link))
    shown, others = [], []
    neutral = len(preferences)
    for items in by_type.values():
        best = min(_rank(link, preferences) for _, link in items)
        if best > neutral:                                # no language the visitor reads: the type's first one
            first = tuple(items[0][1]['hreflang'])
            chosen = [(p, l) for p, l in items if tuple(l['hreflang']) == first]
        else:
            chosen = [(p, l) for p, l in items if _rank(l, preferences) == best]
        shown += [(p, l, best not in (0, neutral)) for p, l in chosen]
        others += [(p, l) for p, l in items if (p, l) not in chosen]
    return shown, others


def verified_url(identifiers: str, brand: dict | None) -> str | None:
    """The Verified by GS1 address of the key (item 6.2), or None: the installation's template set, a GTIN or GLN, and
    the brand not having switched it off."""
    template = (os.getenv('RESOLVER_VERIFIED_BY_GS1_URL', '') or '').strip()
    parts = identifiers.strip('/').split('/')
    if not template or len(parts) < 2 or parts[0] not in VERIFIED_KEYS or (brand and brand.get('verified') is False):
        return None
    return template.replace('{key}', VERIFIED_KEYS[parts[0]]).replace('{value}', quote(parts[1], safe=''))


# ----------------------------------------------------------------------------------------------- the page
_PAGE = """
<style>
.item-brand{display:flex;align-items:center;gap:.9rem;margin:0 0 1rem}
.item-brand img{max-height:3.5rem;max-width:10rem;width:auto;height:auto;display:block}
.item-brand strong{font-size:1.05rem;color:{{ colour }}}
.item-code{font-family:ui-monospace,Consolas,monospace;font-size:.8125rem;color:var(--muted);margin:.25rem 0 1rem;word-break:break-all}
.item-links{display:grid;gap:.6rem;margin:.5rem 0 1rem}
.item-links a,.item-links span.off{display:flex;align-items:center;gap:.9rem;min-height:3.5rem;padding:.75rem 1rem;border-radius:.6rem;
text-decoration:none;background:{{ colour }};color:{{ ink }};font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.12)}
.item-links span.off{background:var(--page);color:var(--muted)}
.item-links a:focus-visible{outline:3px solid {{ accent }};outline-offset:2px}
.item-links svg{flex:none;width:1.6rem;height:1.6rem;fill:currentColor}
.item-links small{display:block;font-weight:400;opacity:.85;font-size:.8125rem}
.item-links a:hover{filter:brightness(1.08)}
details.item-other{margin:1rem 0}details.item-other summary{cursor:pointer;color:var(--link);font-weight:500}
.item-verified{display:flex;gap:.75rem;align-items:center;border:1px solid var(--line);border-radius:.6rem;padding:.75rem 1rem;
margin-top:1.25rem;text-decoration:none;color:var(--ink)}
.item-verified svg{flex:none;width:1.5rem;height:1.5rem;fill:#1B7A45}
.item-verified small{display:block;color:var(--muted)}
.hero{background:{{ colour }};color:{{ ink }}}
</style>
{% if brand_name or logo %}<div class="item-brand">{% if logo %}<img src="{{ logo }}" alt="{{ brand_name or '' }}">{% endif %}
{% if brand_name %}<strong>{{ brand_name }}</strong>{% endif %}</div>{% endif %}
<p class="item-code">{{ code_label }}: {{ hri }}</p>
{% for level in levels %}
  {% if levels|length > 1 %}<h2>{{ level.label }}</h2>{% endif %}
  {% if level.description and loop.index > 1 %}<p>{{ level.description }}</p>{% endif %}
  <div class="item-links">{% for l in level.mine %}{{ button(l) }}{% endfor %}</div>
  {% if level.others %}<details class="item-other"><summary>{{ other_label }} ({{ level.others|length }})</summary>
  <div class="item-links">{% for l in level.others %}{{ button(l) }}{% endfor %}</div></details>{% endif %}
{% else %}<p class="muted">{{ none_label }}</p>{% endfor %}
{% if verified %}<a class="item-verified" href="{{ verified }}" rel="noopener"><svg viewBox="0 0 24 24" aria-hidden="true">
<path d="{{ check_icon }}"/></svg><span>{{ verified_label }}<small>{{ verified_note }}</small></span></a>{% endif %}
"""

_BUTTON = """{% macro button(l) %}{% if l.click %}<a href="{{ l.click }}" rel="noopener">{% else %}<span class="off">{% endif %}
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{{ l.icon }}"/></svg><span>{{ l.title }}<small>{{ l.label }}{% if l.lang %} · {{ l.lang }}{% endif %}</small></span>
{% if l.click %}</a>{% else %}</span>{% endif %}{% endmacro %}"""


def render_page(identifiers: str, qualifier_path: str | None, linkset: list[dict], json_ld: dict | None) -> str:
    """The item's page for a linkset (ADR 0011)."""
    locale = web_pages._request_locale()
    path = identifiers + (qualifier_path or '')
    # On an organisation's domain with a path stem, the page's own addresses keep the stem (its server may pass on
    # nothing else)
    stem = (request.environ.get(domains.ENV_KEY) or {}).get('stem') or ''
    parts = identifiers.strip('/').split('/')
    brand = BRANDS.for_part(request_log.company_part(parts[0], parts[1]) if len(parts) > 1 else None)
    colour = _colour((brand or {}).get('colour'), DEFAULT_COLOUR)
    accent = _colour((brand or {}).get('accent'), DEFAULT_ACCENT)
    preferences = _preferences(locale)

    def button(index, position, link, show_language=True):
        return {'title': link['title'], 'label': web_pages._label(locale, link['term']),
                'lang': ', '.join(link['hreflang']) if show_language else '', 'icon': _I[ICONS.get(link['term'], 'link')],
                'click': (stem + '/_click?' + urlencode({'a': path, 'l': index, 'i': position, 't': link['term']}))
                if link['href'] else None}

    levels = []
    for index, level in enumerate(page_levels(linkset)):
        shown, others = group_links(level['links'], preferences)
        levels.append({'label': web_pages._level_label(locale, level['anchor']), 'description': level['description'],
                       'mine': [button(index, p, l, marked) for p, l, marked in shown],
                       'others': [button(index, p, l) for p, l in others]})
    title = next((lv['description'] for lv in page_levels(linkset) if lv['description']), None) \
        or web_pages._t(locale, 'linkset.title')
    logo = f"{stem}/_brand/{quote(brand['_id'], safe='')}?v={brand.get('logo', {}).get('etag', '')}" \
        if brand and brand.get('logo') else None
    body = render_template_string(
        _BUTTON + _PAGE, levels=levels, hri=web_pages._hri(identifiers, qualifier_path), colour=colour, accent=accent,
        ink=_text_colour(colour), brand_name=(brand or {}).get('name'), logo=logo, code_label=TEXT[locale]['code'],
        other_label=TEXT[locale]['other'], none_label=TEXT[locale]['none'], verified=verified_url(identifiers, brand),
        verified_label=TEXT[locale]['verified'], verified_note=TEXT[locale]['verifiedNote'], check_icon=_I['check'])
    if json_ld is not None:
        data = web_pages.json.dumps(json_ld, ensure_ascii=False).replace('<', '\\u003c')
        body += f'<script type="application/ld+json">{data}</script>'
    return web_pages._page(locale, title, body, fonts=False, icon=logo)


# ----------------------------------------------------------------------------------------------- clicks and logos
def click(resolve_linkset) -> Response | tuple:
    """/_click: the link at (level l, position i) of the record's page, of type t, logged as a click and redirected
    to. resolve_linkset(identifiers, qualifier_path) gives the record's linkset (or None)."""
    args = request.args
    path = args.get('a', '')
    parts = [p for p in path.split('/') if p]
    if len(parts) < 2 or len(parts) % 2:
        return {'error': 'Not a link of this item'}, 404
    identifiers, qualifier_path = f'/{parts[0]}/{parts[1]}', ''.join(f'/{p}' for p in parts[2:]) or None
    try:
        level, position = int(args.get('l', '')), int(args.get('i', ''))
    except ValueError:
        return {'error': 'Not a link of this item'}, 404
    if not domains.allows(request.environ, parts[0], parts[1]):
        return {'error': 'Not a link of this item'}, 404
    linkset = resolve_linkset(identifiers, qualifier_path)
    levels = page_levels(linkset or [])
    if not (0 <= level < len(levels) and 0 <= position < len(levels[level]['links'])):
        return {'error': 'Not a link of this item'}, 404
    link = levels[level]['links'][position]
    if link['term'] != args.get('t') or not link['href']:
        return {'error': 'Not a link of this item'}, 404
    request_log.note(form='landing', ai=parts[0], value=parts[1],
                     qualifiers=list(zip(parts[2::2], parts[3::2])), linkType=link['term'], outcome='click')
    response = Response(status=302)
    response.headers['Location'] = link['href']
    response.headers['Cache-Control'] = 'no-store'
    return response


def logo(prefix: str) -> Response | tuple:
    """/_brand/<prefix>: the uploaded logo, cached a day (its address changes with it)."""
    brand = BRANDS.get(prefix)
    data = (brand or {}).get('logo') or {}
    if not data.get('data'):
        return {'error': 'No logo'}, 404
    response = make_response(bytes(data['data']))
    response.headers['Content-Type'] = data.get('type', 'image/png')
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['ETag'] = data.get('etag') or hashlib.sha256(bytes(data['data'])).hexdigest()[:16]
    return response
