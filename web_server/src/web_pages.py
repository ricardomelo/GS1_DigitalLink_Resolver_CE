"""
HTML pages served by the resolver to people using a browser (Accept: text/html).

- render_linkset: a readable list of links (?linkType=linkset in a browser), as recommended by
  section 2.10 of the GS1-Conformant Resolver Standard.
- render_error: a friendly page for 400/404/500. The HTTP status code is NOT changed (a 404 stays
  a 404); on a 404 for a missing linkType the available links are listed (section 2.6.2, "MAY include
  information about other links that are available").

The look follows gs1.org. The page language is taken from the "gs1resolver_lang" cookie (set by the
language menu on these pages and by the link management portal) or, failing that, from the
Accept-Language header: one of the twelve languages of page_texts.json (Documentation/adr/0014-interface-languages.md),
English otherwise; Arabic is written right to left.
Clients asking for JSON keep receiving JSON; nothing here alters machine responses.
"""
import base64
import logging
import os
import json
import secrets
import threading
import time
import unicodedata
from urllib.parse import unquote, urlparse

from flask import g, render_template_string, request

import settings_age

PRODUCT_NAME = os.getenv('RESOLVER_PRODUCT_NAME', 'GS1 Digital Link Resolver Suite')       # ADR 0024
# A stored title equal to a former default is not the operator's choice (portal/appearance.py, FORMER_TITLES).
FORMER_TITLES = ('GS1 Resolver Community Edition',)
# Operator shown in the footer (see .env.example), beside the link to the installation's privacy notice (ADR 0017).
ORG_NAME = os.getenv('RESOLVER_ORG_NAME', '').strip()
ORG_URL = os.getenv('RESOLVER_ORG_URL', '').strip()
LOCALE_COOKIE = 'gs1resolver_lang'
# The texts of the pages, the item's page (landing.py) and the link types' names in every language, each language
# with its own name (Documentation/adr/0014-interface-languages.md)
with open(os.path.join(os.path.dirname(__file__), 'page_texts.json'), encoding='utf-8') as _fh:
    PAGE_TEXTS = json.load(_fh)
SUPPORTED_LOCALES = {tag: texts['name'] for tag, texts in PAGE_TEXTS.items()}


def _menu_key(item):
    """The language menu's order, as the portal's: names in the Latin alphabet first, alphabetically (accents
    ignored), then the others by their script."""
    name = item[1]
    latin = 'LATIN' in unicodedata.name(name[0], '')
    folded = ''.join(c for c in unicodedata.normalize('NFD', name) if not unicodedata.combining(c)).lower()
    return (0, folded) if latin else (1, ord(name[0]), name)


SUPPORTED_LOCALES = dict(sorted(SUPPORTED_LOCALES.items(), key=_menu_key))
DEFAULT_LOCALE = 'en-GB'
RIGHT_TO_LEFT = {'ar'}

# The project's logo (backlog item 7.3), embedded in each page so nothing more is requested
_LOGO_PATH = os.path.join(os.path.dirname(__file__), 'logo.svg')
try:
    with open(_LOGO_PATH, 'rb') as _fh:
        LOGO_DATA_URI = 'data:image/svg+xml;base64,' + base64.b64encode(_fh.read()).decode('ascii')
except OSError:
    LOGO_DATA_URI = ''


class Appearance:
    """The installation's appearance set in the portal (Documentation/adr/0019-appearance.md): the setting "appearance"
    of the portal's database, read again after CACHE_SECONDS (the last kept on failure, for RESOLVER_SETTINGS_MAX_AGE_S
    at most: then the original until it is read again; finding F-033, ADR 0053); {} for the original."""
    CACHE_SECONDS = 30

    def __init__(self, database=None):
        self.database = database        # a function giving the portal's database (pymongo), set by create_app
        self._doc: dict = {}
        self._loaded = 0.0
        self._lock = threading.Lock()
        self.age = settings_age.Age('Appearance', 'the pages are shown with the original appearance')

    def current(self) -> dict:
        self.refresh()
        return {} if self.database is None or self.age.stale() else self._doc

    def refresh(self) -> None:
        """Reads the appearance again when CACHE_SECONDS have passed; a failure keeps the last one (settings_age)."""
        if self.database is None:
            return
        now = time.monotonic()
        if now - self._loaded >= self.CACHE_SECONDS:
            with self._lock:
                if now - self._loaded >= self.CACHE_SECONDS:
                    try:
                        self._doc = (self.database()['settings'].find_one({'_id': 'appearance'}) or {}).get('value') or {}
                        self.age.read(now)
                    except Exception as exc:          # noqa: BLE001 — the pages keep the last appearance
                        logging.getLogger(__name__).warning('Appearance not read (%s); the last one is kept.', exc)
                        self.age.failed(now)
                    self._loaded = now

    def forget(self) -> None:
        self._loaded = 0.0


APPEARANCE = Appearance()


def _hex(value) -> str | None:
    text = str(value or '')
    return text if len(text) == 7 and text.startswith('#') and all(c in '0123456789abcdefABCDEF' for c in text[1:]) \
        else None


def appearance() -> tuple[str, str, str]:
    """(title, logo address, extra style) of the installation's pages: the operator's, else the original."""
    doc = APPEARANCE.current()
    title = str(doc.get('title') or '').strip()
    title = PRODUCT_NAME if not title or title in FORMER_TITLES else title
    logo = doc.get('logo') or {}
    address = (f"data:{logo.get('type', 'image/png')};base64," + base64.b64encode(bytes(logo['data'])).decode('ascii')
               if logo.get('data') else LOGO_DATA_URI)
    colour, action, accent = (_hex(doc.get(k)) for k in ('colour', 'action', 'accent'))
    style = ''
    if colour or action or accent:
        style = ':root{' + (f'--blue:{colour};' if colour else '') + (f'--orange:{accent};' if accent else '') \
            + (f'--action:{action};' if action else '') + '}'
    return title, address, style


def icon() -> dict | None:
    """The icon of the browsers' tabs the operator set ({"type", "data", …}), or None for the original."""
    found = APPEARANCE.current().get('icon') or {}
    return found if found.get('data') else None


def icon_address() -> str | None:
    """The operator's icon as a data: URI for a page's <link rel="icon">, or None (the browser asks /favicon.ico)."""
    found = icon()
    return f"data:{found.get('type', 'image/png')};base64," + base64.b64encode(bytes(found['data'])).decode('ascii') \
        if found else None


# First matching language prefix in Accept-Language wins.
LOCALE_MATCHERS = [('pt', 'pt-BR'), ('en', 'en-GB'), ('es', 'es'), ('fr', 'fr'), ('de', 'de'), ('it', 'it'),
                   ('tr', 'tr'), ('zh', 'zh-Hans'), ('ja', 'ja'), ('ko', 'ko'), ('hi', 'hi'), ('ar', 'ar')]
LOCALE_MATCHERS = [(prefix, tag) for prefix, tag in LOCALE_MATCHERS if tag in SUPPORTED_LOCALES]

TEXT = {tag: texts['pages'] for tag, texts in PAGE_TEXTS.items()}
LINK_TYPE_LABELS = {tag: texts['linkLabels'] for tag, texts in PAGE_TEXTS.items()}

# The browser's rules for the resolver's answers (Documentation/adr/0038-browser-hardening.md, finding F-021). A page's
# own <style> and <script> elements carry a nonce drawn for each answer; nothing else may run or style it, and nothing
# is loaded from other sites but the fonts of the pages that use them. Every other answer (redirects, JSON, linksets)
# may load nothing at all.
PAGE_POLICY = ("default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'{fonts_css}; {fonts}"
               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
OTHER_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
# The Swagger UI of the library (flask-restx) writes its start-up script and style in the page, with the address of
# the description in it: allowed inline, but it loads and calls nothing outside this origin and nothing frames it
SWAGGER_POLICY = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                  "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                  "frame-ancestors 'none'")
FONT_CSS = 'https://fonts.googleapis.com'
FONT_FILES = 'https://fonts.gstatic.com'


def content_security_policy() -> str:
    """The Content-Security-Policy of the answer being made: the page's own (its nonce, and the fonts' sites when the
    page loads fonts) when _page() made one, the Swagger UI's for the library's documentation page, else the policy
    that allows nothing."""
    if request.endpoint == 'api.doc':
        return SWAGGER_POLICY
    page = g.get('csp_page')
    if not page:
        return OTHER_POLICY
    nonce, fonts = page
    return PAGE_POLICY.format(nonce=nonce, fonts_css=f' {FONT_CSS}' if fonts else '',
                              fonts=f'font-src {FONT_FILES}; ' if fonts else '')


def _with_nonce(html: str, fonts: bool) -> str:
    """The page's own <style> and <script> elements with this answer's nonce. Only the templates write these elements:
    every value is escaped, so a '<style>' or '<script>' in a record's text reaches the page as text, not as markup
    (the JSON-LD block is <script type=...>, data the browser does not run)."""
    nonce = secrets.token_urlsafe(18)
    g.csp_page = (nonce, fonts)
    return html.replace('<style>', f'<style nonce="{nonce}">').replace('<script>', f'<script nonce="{nonce}">')


_BASE = """<!doctype html>
<html lang="{{ locale }}" dir="{{ direction }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{ title }} | {{ product }}</title>
{% if icon %}<link rel="icon" href="{{ icon }}">{% endif %}
{% if fonts %}<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600&display=swap" rel="stylesheet">{% endif %}
<style>
:root{--blue:#002C6C;--orange:#F26334;--action:#CE3D0D;--link:#00799E;--ink:#121212;--text:#262626;--muted:#555F6D;
--line:#CDD5DF;--page:#F0F5FA;--sans:"Montserrat","Gotham SSm A","Gotham SSm B",Verdana,sans-serif}
{{ appearance_style }}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--text);font:400 1rem/1.5 var(--sans)}
a{color:var(--link)}
header{background:#fff;box-shadow:0 2px 3px rgba(0,44,108,.2);position:relative}
.bar{max-width:60rem;margin:0 auto;padding:.6rem clamp(1rem,4vw,2rem);min-height:4.5rem;display:flex;align-items:center;gap:1rem}
.brand{display:flex;align-items:center;gap:1rem;color:var(--blue);text-decoration:none;min-width:0}
.brand img{height:2.75rem;width:auto;display:block}
.brand span{font-weight:500;padding-inline-start:1rem;border-inline-start:1px solid var(--line);line-height:1.25}
.lang{margin-inline-start:auto;display:flex;align-items:center;gap:.35rem;color:var(--blue)}
.lang select{font:500 .875rem var(--sans);color:var(--blue);border:1px solid transparent;background:transparent;padding:.35rem .4rem;cursor:pointer}
.lang select:hover{border-color:var(--line)}
.hero{background:var(--blue);color:#fff;padding:2.25rem 0 5rem}
.hero div{max-width:60rem;margin:0 auto;padding:0 clamp(1rem,4vw,2rem)}
.hero h1{font-weight:400;font-size:clamp(1.6rem,3.4vw,2.25rem);line-height:1.15;margin:0}
main{max-width:60rem;margin:-3rem auto 0;padding:0 clamp(1rem,4vw,2rem) 2rem;position:relative}
.card{background:#fff;border-radius:4px;padding:clamp(1.25rem,4vw,2rem);
box-shadow:0 1px 2px rgba(0,44,108,.08),0 8px 24px -12px rgba(0,44,108,.25)}
p{margin:.5rem 0}.muted{color:var(--muted);font-size:.875rem}
.code{font-family:ui-monospace,Consolas,monospace;background:var(--page);border-radius:4px;padding:.2rem .45rem;word-break:break-all;display:inline-block}
h2{font-size:.8125rem;font-weight:600;margin:1.75rem 0 .5rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
ul{list-style:none;padding:0;margin:0}
li a,li .unlinked{display:block;padding:.85rem 1rem;margin:.5rem 0;border:1px solid var(--line);border-inline-start:4px solid var(--blue);
border-radius:4px;text-decoration:none;color:var(--ink);background:#FAFCFE}
li .unlinked{border-inline-start-color:var(--line)}
li a:hover{background:var(--page);border-inline-start-color:var(--action)}li strong{display:block;color:var(--blue);font-weight:600}
li small{color:var(--muted)}
footer{max-width:60rem;margin:0 auto;padding:0 clamp(1rem,4vw,2rem) 2rem;font-size:.8125rem;color:var(--muted)}
[dir=rtl] .code{direction:ltr;unicode-bidi:isolate}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:560px){.brand span{font-size:.8125rem;padding-inline-start:.75rem}.brand img{height:2.25rem}.lang svg{display:none}}
</style></head><body>
<header><div class="bar">
  <a class="brand" href="/" title="{{ home_label }}">{% if logo %}<img src="{{ logo }}" alt="" width="44" height="44">{% endif %}<span>{{ product }}</span></a>
  <label class="lang"><span class="vh">{{ language_label }}</span>
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm6.9 6h-3a15.7 15.7 0 0 0-1.4-3.6A8 8 0 0 1 18.9 8ZM12 4c.8 1.2 1.5 2.5 1.9 4h-3.8c.4-1.5 1.1-2.8 1.9-4ZM4.3 14a8.2 8.2 0 0 1 0-4h3.4a16.5 16.5 0 0 0 0 4H4.3Zm.8 2h3c.3 1.3.8 2.5 1.4 3.6A8 8 0 0 1 5.1 16ZM8.1 8h-3a8 8 0 0 1 4.4-3.6C8.9 5.5 8.4 6.7 8.1 8ZM12 20c-.8-1.2-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.8-1.9 4Zm2.3-6H9.7a14.7 14.7 0 0 1 0-4h4.6a14.7 14.7 0 0 1 0 4Zm.3 5.6c.6-1.1 1.1-2.3 1.4-3.6h3a8 8 0 0 1-4.4 3.6Zm1.7-5.6a16.5 16.5 0 0 0 0-4h3.4a8.2 8.2 0 0 1 0 4h-3.4Z"/></svg>
    <select id="lang">{% for code, name in locales.items() %}<option value="{{ code }}"{% if code == locale %} selected{% endif %}>{{ name }}</option>{% endfor %}</select>
  </label>
</div></header>
<section class="hero"><div><h1>{{ title }}</h1></div></section>
<main><div class="card">{{ body|safe }}</div></main>
<footer>{% if org %}{{ footer }} {% if org_url %}<a href="{{ org_url }}">{{ org }}</a>{% else %}{{ org }}{% endif %}. {% endif %}<a href="/portal/privacy">{{ privacy_label }}</a></footer>
<script>
/* Language menu: remembers the choice in a cookie (shared with the portal) and re-renders the page.
   A cookie rather than a query parameter keeps the Digital Link URI untouched. */
document.getElementById('lang').addEventListener('change', function (e) {
  document.cookie = '{{ cookie }}=' + encodeURIComponent(e.target.value) + '; path=/; max-age=31536000; SameSite=Lax' +
    (location.protocol === 'https:' ? '; Secure' : '');
  location.reload();
});
</script>
</body></html>"""

_LINKS = """
{% for level in levels %}
  <h2>{{ level.label }}</h2>
  {% if level.description %}<p>{{ level.description }}</p>{% endif %}
  <ul>{% for l in level.links %}
    <li>{% if l.href %}<a href="{{ l.href }}" rel="noopener">{% else %}<span class="unlinked">{% endif %}<strong>{{ l.title }}</strong>
      <small>{{ l.label }}{% if l.lang %} · {{ l.lang }}{% endif %}</small>{% if l.href %}</a>{% else %}</span>{% endif %}</li>
  {% endfor %}</ul>
{% endfor %}
"""


def negotiate_locale(accept_language: str, cookie: str | None = None) -> str:
    """Page locale: a supported value in the language cookie wins; otherwise the Accept-Language
    header (q-values honoured) is matched by language prefix; otherwise the default."""
    if cookie in SUPPORTED_LOCALES:
        return cookie
    ranked = []
    for position, part in enumerate((accept_language or '').split(',')):
        pieces = part.strip().split(';')
        tag = pieces[0].strip().lower()
        quality = 1.0
        for piece in pieces[1:]:
            if piece.strip().startswith('q='):
                try:
                    quality = float(piece.strip()[2:])
                except ValueError:
                    quality = 0.0
        if tag:
            ranked.append((-quality, position, tag))
    for _, _, tag in sorted(ranked):
        for prefix, locale in LOCALE_MATCHERS:
            if tag == prefix or tag.startswith(prefix + '-'):
                return locale
    return DEFAULT_LOCALE


def _request_locale() -> str:
    """Language of the page: the language cookie, else the browser's Accept-Language, else English."""
    return negotiate_locale(request.headers.get('Accept-Language', ''), request.cookies.get(LOCALE_COOKIE))


def _t(locale: str, key: str, **params) -> str:
    """A text of the page in the language, with its parameters."""
    return TEXT[locale][key].format(**params)


def _label(locale: str, term: str) -> str:
    """Name of a GS1 link type in the language (the term itself when unknown)."""
    return LINK_TYPE_LABELS[locale].get(term, term)


def _level_label(locale: str, anchor: str) -> str:
    """Name of a level of the linkset (serial, batch, variant, product or the key) from its anchor."""
    # /AI/value followed by the key qualifiers, e.g. /01/…/10/L1/21/S1 or /414/…/254/1. Linkset anchors
    # are absolute URIs (https://id.example.org/01/…), so only the path is read.
    parts = urlparse(anchor).path.strip('/').split('/')
    ai = parts[0] if parts else ''
    # values are percent-encoded in paths and anchors (a batch may hold '/'): shown as they are printed
    pairs = {k: unquote(v) for k, v in zip(parts[2::2], parts[3::2])}
    if '21' in pairs:
        return _t(locale, 'level.serial', value=pairs['21'])
    if '10' in pairs:
        return _t(locale, 'level.lot', value=pairs['10'])
    if '22' in pairs:
        return _t(locale, 'level.variant', value=pairs['22'])
    if pairs:
        return ' '.join(f'({k}) {v}' for k, v in pairs.items())
    return _t(locale, 'level.product') if ai == '01' else f'({ai}) {parts[1] if len(parts) > 1 else ""}'


def _web_address(href) -> str | None:
    """The target as a clickable address, or None when it is not http(s). The data entry API stores any
    href it is given, and a javascript: or data: address would run in the resolver's own origin when
    clicked; such targets are listed without a link. Redirects are unaffected (browsers refuse them)."""
    href = str(href or '').strip()
    return href if urlparse(href).scheme.lower() in ('http', 'https') else None


_GS1_KEY_PREFIXES = ('https://ref.gs1.org/voc/', 'https://gs1.org/voc/')


def _levels(locale: str, linkset: list[dict]) -> list[dict]:
    """The links of each level of a linkset, grouped for the HTML page (default link marked)."""
    levels = []
    for item in linkset:
        links, seen = [], set()
        for key, value in item.items():
            # published keys use https://ref.gs1.org/voc/ (section 2.14); https://gs1.org/voc/ is still read
            if not key.startswith(_GS1_KEY_PREFIXES) or key.endswith('/defaultLink') or key.endswith('/defaultLinkMulti'):
                continue
            term = key.rsplit('/', 1)[-1]
            for link in value:
                identity = (term, link.get('href'), tuple(link.get('hreflang') or []))
                if identity in seen:
                    continue
                seen.add(identity)
                links.append({
                    'href': _web_address(link.get('href')), 'title': link.get('title') or term,
                    'label': f"{_label(locale, term)} (gs1:{term})",
                    'lang': ', '.join(link.get('hreflang') or []),
                })
        if links:
            levels.append({'label': _level_label(locale, item.get('anchor', '')),
                           'description': item.get('itemDescription') or item.get('description'),
                           'links': links})
    return levels


def _hri(identifiers: str, qualifier_path: str | None) -> str:
    """The identification in human readable form: (01) 0950… (10) L1."""
    parts = [unquote(p) for p in (identifiers + (qualifier_path or '')).strip('/').split('/')]
    return '  '.join(f'({parts[i]}) {parts[i + 1]}' for i in range(0, len(parts) - 1, 2))


def _page(locale: str, title: str, body: str, fonts: bool = True, icon: str | None = None) -> str:
    """A whole HTML page: header, language menu, body and the operator footer from the configuration. Without fonts,
    nothing is loaded from other sites (the item's page, which every scan of some codes reaches: ADR 0011); icon: the
    page's own favicon (the brand's logo on the item's page), else the installation's icon."""
    product, logo, style = appearance()           # the installation's title, logo and colours (ADR 0019)
    icon = icon or icon_address()
    html = render_template_string(_BASE, locale=locale, title=title, product=product, logo=logo, fonts=fonts, icon=icon,
                                  appearance_style=style,
                                  org=ORG_NAME, org_url=ORG_URL, footer=_t(locale, 'footer'),
                                  privacy_label=_t(locale, 'privacy'),
                                  language_label=_t(locale, 'language'), home_label=_t(locale, 'home'),
                                  locales=SUPPORTED_LOCALES, direction='rtl' if locale in RIGHT_TO_LEFT else 'ltr',
                                  cookie=LOCALE_COOKIE, body=body)
    return _with_nonce(html, fonts)


# The notice of a page whose links come from a less specific level than the request named (ADR 0022, section 2.3)
_NOTICE = """<style>
.level-notice{display:flex;gap:.7rem;align-items:flex-start;background:#FFF4E0;border:1px solid #F0D09A;
border-inline-start:4px solid #E08A00;border-radius:.6rem;padding:.8rem 1rem;margin:0 0 1rem;color:#4A3000;line-height:1.45}
.level-notice strong{display:block;margin-bottom:.15rem}
.level-notice svg{flex:none;width:1.4rem;height:1.4rem;fill:#B36B00;margin-top:.1rem}
</style>
<div class="level-notice" role="note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>
<div><strong>{{ notice.title }}</strong>{{ notice.text }}</div></div>
"""


def level_notice(locale: str, walked: tuple[str, str] | None) -> dict | None:
    """The notice's texts for walked = (the request's path, the path of the level that answered), or None when the
    request was answered by its own level: which level has no record of its own, and whose links are shown."""
    if not walked:
        return None
    asked, answered = walked
    return {'title': _t(locale, 'notice.title', level=_level_label(locale, asked)),
            'text': _t(locale, 'notice.text', level=_level_label(locale, answered))}


def notice_html(locale: str, walked: tuple[str, str] | None) -> str:
    """The notice as HTML (escaped by the template), or nothing."""
    notice = level_notice(locale, walked)
    return render_template_string(_NOTICE, notice=notice) if notice else ''


def fallback_notices(locale: str, linkset: list[dict], fallback: list[str] | None, context: str | None) -> str:
    """The notices of a choice whose links do not serve the language or the context (market) the request named
    (ADR 0028), as HTML: one for each, naming the link type offered."""
    if not fallback:
        return ''
    terms = [public.rsplit('/', 1)[-1] for item in linkset for public in item if public.startswith('http')]
    label = _label(locale, terms[0]) if terms else ''
    html = ''
    for what in ('language', 'context'):
        if what in fallback:
            notice = {'title': _t(locale, f'fallback.{what}.title', label=label, context=context or ''),
                      'text': _t(locale, f'fallback.{what}.text')}
            html += render_template_string(_NOTICE, notice=notice)
    return html


def render_linkset(identifiers: str, qualifier_path: str | None, linkset: list[dict],
                   json_ld: dict | None = None, choice: bool = False,
                   walked: tuple[str, str] | None = None, fallback: list[str] | None = None,
                   context: str | None = None) -> str:
    """HTML page listing every link of a linkset, for people who open ?linkType=linkset in a browser, or the
    links among which the resolver could not choose (choice: 300 Multiple Choices). With json_ld the linkset
    is embedded as JSON-LD too (GS1-Conformant Resolver 1.2.1, section 2.10). walked: the request's path and the
    level that answered, when the links come from a less specific level (the notice of ADR 0022, section 2.3).
    fallback: the preferences of the request ('language', 'context') that the links offered do not serve, with the
    context asked (the notices of ADR 0028)."""
    locale = _request_locale()
    title = _t(locale, 'choice.title' if choice else 'linkset.title')
    body = render_template_string("{% if text %}<p>{{ text }}</p>{% endif %}<p class='code'>{{ hri }}</p>"
                                  "{{ notice|safe }}" + _LINKS,
                                  text=_t(locale, 'choice.text') if choice else '',
                                  hri=_hri(identifiers, qualifier_path), levels=_levels(locale, linkset),
                                  notice=fallback_notices(locale, linkset, fallback, context)
                                  + notice_html(locale, walked))
    if json_ld is not None:
        # '<' escaped so that no value can close the script element
        data = json.dumps(json_ld, ensure_ascii=False).replace('<', '\\u003c')
        body += f'<script type="application/ld+json">{data}</script>'
    return _page(locale, title, body)


def render_error(status: int, identifiers: str, qualifier_path: str | None, linktype: str | None,
                 available: list[dict] | None, walked: tuple[str, str] | None = None) -> str:
    """HTML page for 400 (not a valid Digital Link) and 404 (unknown identifier, or a link type the
    identifier does not have, with the types it has). walked: a link withheld by the strict mode (ADR 0022, section
    2.4), as (the request's path, the level that holds it): the page names the level asked and shows the notice of
    section 2.3 above the links that are available.
    """
    locale = _request_locale()
    notice = ''
    if status == 400:
        title, text = _t(locale, 'error.400.title'), _t(locale, 'error.400.text')
    elif status == 404 and linktype and walked:
        term = linktype.split(':')[-1].rsplit('/', 1)[-1]
        title = _t(locale, 'error.404withheld.title')
        text = _t(locale, 'error.404withheld.text', label=_label(locale, term), level=_level_label(locale, walked[0]))
        notice = notice_html(locale, walked) if available else ''
    elif status == 404 and linktype and available:
        term = linktype.split(':')[-1].rsplit('/', 1)[-1]
        title = _t(locale, 'error.404type.title')
        text = _t(locale, 'error.404type.text', label=_label(locale, term))
    elif status == 404:
        title, text = _t(locale, 'error.404.title'), _t(locale, 'error.404.text')
    else:
        title, text = _t(locale, 'error.other.title'), _t(locale, 'error.other.text')

    body = render_template_string(
        "<p>{{ text }}</p><p class='code'>{{ hri }}</p>"
        "<p class='muted'>{{ status_text }}</p>{{ notice|safe }}" + (_LINKS if available else ''),
        text=text, hri=_hri(identifiers, qualifier_path), notice=notice,
        status_text=_t(locale, 'status', status=status), levels=_levels(locale, available or []))
    return _page(locale, title, body)
