"""
HTML pages served by the resolver to people using a browser (Accept: text/html).

- render_linkset: a readable list of links (?linkType=linkset in a browser), as recommended by
  section 2.10 of the GS1-Conformant Resolver Standard.
- render_error: a friendly page for 400/404/500. The HTTP status code is NOT changed (a 404 stays
  a 404); on a 404 for a missing linkType the available links are listed (section 2.6.2, "MAY include
  information about other links that are available").

The look follows gs1.org. The page language is taken from the "gs1resolver_lang" cookie (set by the
language menu on these pages and by the link management portal) or, failing that, from the
Accept-Language header: Brazilian Portuguese or British English.
Clients asking for JSON keep receiving JSON; nothing here alters machine responses.
"""
import base64
import os

from flask import render_template_string, request

PRODUCT_NAME = os.getenv('RESOLVER_PRODUCT_NAME', 'GS1 Resolver Community Edition')
# Operator shown in the footer (see .env.example); the footer is omitted when no name is set.
ORG_NAME = os.getenv('RESOLVER_ORG_NAME', '').strip()
ORG_URL = os.getenv('RESOLVER_ORG_URL', '').strip()
LOCALE_COOKIE = 'gs1resolver_lang'
SUPPORTED_LOCALES = {'pt-BR': 'Português (Brasil)', 'en-GB': 'English (UK)'}
DEFAULT_LOCALE = 'en-GB'

_LOGO_PATH = os.path.join(os.path.dirname(__file__), 'gs1-logo.png')
try:
    with open(_LOGO_PATH, 'rb') as _fh:
        LOGO_DATA_URI = 'data:image/png;base64,' + base64.b64encode(_fh.read()).decode('ascii')
except OSError:
    LOGO_DATA_URI = ''
# First matching language prefix in Accept-Language wins.
LOCALE_MATCHERS = [('pt', 'pt-BR'), ('en', 'en-GB')]

TEXT = {
    'pt-BR': {
        'linkset.title': 'Informações disponíveis',
        'level.serial': 'Unidade (série {value})', 'level.lot': 'Lote {value}',
        'level.variant': 'Variante {value}', 'level.product': 'Produto (todas as unidades)',
        'error.400.title': 'Código inválido',
        'error.400.text': 'Este endereço não corresponde a um GS1 Digital Link válido. Confira os números e tente escanear de novo.',
        'error.404type.title': 'Informação não disponível',
        'error.404type.text': 'Este produto não tem “{label}” cadastrado. Veja abaixo o que o fabricante disponibilizou.',
        'error.404.title': 'Produto sem informações cadastradas',
        'error.404.text': 'O responsável por este código ainda não cadastrou páginas para ele no Resolver. Se você é o dono da marca, fale com o operador deste Resolver para publicar os links do seu produto.',
        'error.other.title': 'Não foi possível concluir a consulta',
        'error.other.text': 'Tente novamente em alguns instantes.',
        'status': 'Código da resposta: {status}',
        'footer': 'Serviço GS1 Digital Link operado por',
        'language': 'Idioma',
    },
    'en-GB': {
        'linkset.title': 'Available information',
        'level.serial': 'Item (serial {value})', 'level.lot': 'Batch/lot {value}',
        'level.variant': 'Variant {value}', 'level.product': 'Product (every unit)',
        'error.400.title': 'Invalid code',
        'error.400.text': 'This address is not a valid GS1 Digital Link. Check the numbers and try scanning again.',
        'error.404type.title': 'Information not available',
        'error.404type.text': 'This product has no “{label}” registered. See below what the manufacturer has made available.',
        'error.404.title': 'No information registered for this product',
        'error.404.text': 'The owner of this code has not yet registered any pages for it on the resolver. If you own the brand, contact the operator of this resolver to publish your product links.',
        'error.other.title': 'The request could not be completed',
        'error.other.text': 'Please try again in a moment.',
        'status': 'Response code: {status}',
        'footer': 'GS1 Digital Link service operated by',
        'language': 'Language',
    },
}

LINK_TYPE_LABELS = {
    'pt-BR': {
        'defaultLink': 'Destino principal', 'defaultLinkMulti': 'Destino principal (por idioma)',
        'pip': 'Página do produto', 'instructions': 'Instruções de uso', 'support': 'Atendimento (SAC)',
        'certificationInfo': 'Certificados e conformidade', 'safetyInfo': 'Informações de segurança',
        'epil': 'Bula eletrônica (paciente)', 'smpc': 'Informações ao profissional de saúde',
        'recallStatus': 'Situação de recolhimento (recall)', 'quickStartGuide': 'Guia rápido',
        'tutorial': 'Tutoriais', 'relatedVideo': 'Vídeo do produto', 'serviceInfo': 'Manutenção e assistência',
        'whatsInTheBox': 'Conteúdo da embalagem', 'faqs': 'Perguntas frequentes',
        'registerProduct': 'Registrar produto ou garantia', 'purchaseSuppliesOrAccessories': 'Acessórios e refis',
        'promotion': 'Promoção', 'hasRetailers': 'Onde comprar', 'review': 'Avaliações',
        'leaveReview': 'Deixar uma avaliação', 'socialMedia': 'Redes sociais',
        'sustainabilityInfo': 'Sustentabilidade e reciclagem', 'nutritionalInfo': 'Informação nutricional',
        'ingredientsInfo': 'Ingredientes', 'allergenInfo': 'Alergênicos', 'recipeInfo': 'Receitas',
        'masterData': 'Dados cadastrais (B2B)', 'traceability': 'Rastreabilidade', 'epcis': 'Repositório EPCIS',
    },
    'en-GB': {
        'defaultLink': 'Default link', 'defaultLinkMulti': 'Default link (per language)',
        'pip': 'Product information page', 'instructions': 'Instructions', 'support': 'Customer support',
        'certificationInfo': 'Certification and compliance', 'safetyInfo': 'Safety information',
        'epil': 'Electronic patient information leaflet', 'smpc': 'Information for healthcare professionals',
        'recallStatus': 'Recall status', 'quickStartGuide': 'Quick start guide',
        'tutorial': 'Tutorials', 'relatedVideo': 'Product video', 'serviceInfo': 'Servicing and maintenance',
        'whatsInTheBox': "What's in the box", 'faqs': 'Frequently asked questions',
        'registerProduct': 'Register product or warranty', 'purchaseSuppliesOrAccessories': 'Accessories and refills',
        'promotion': 'Promotion', 'hasRetailers': 'Where to buy', 'review': 'Reviews',
        'leaveReview': 'Leave a review', 'socialMedia': 'Social media',
        'sustainabilityInfo': 'Sustainability and recycling', 'nutritionalInfo': 'Nutritional information',
        'ingredientsInfo': 'Ingredients', 'allergenInfo': 'Allergens', 'recipeInfo': 'Recipes',
        'masterData': 'Master data (B2B)', 'traceability': 'Traceability', 'epcis': 'EPCIS repository',
    },
}

_BASE = """<!doctype html>
<html lang="{{ locale }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{ title }} | {{ product }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--blue:#002C6C;--orange:#F26334;--action:#CE3D0D;--link:#00799E;--ink:#121212;--text:#262626;--muted:#555F6D;
--line:#CDD5DF;--page:#F0F5FA;--sans:"Montserrat","Gotham SSm A","Gotham SSm B",Verdana,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--text);font:400 1rem/1.5 var(--sans)}
a{color:var(--link)}
header{background:#fff;box-shadow:0 2px 3px rgba(0,44,108,.2);position:relative}
.bar{max-width:60rem;margin:0 auto;padding:.6rem clamp(1rem,4vw,2rem);min-height:4.5rem;display:flex;align-items:center;gap:1rem}
.brand{display:flex;align-items:center;gap:1rem;color:var(--blue);text-decoration:none;min-width:0}
.brand img{height:2.75rem;width:auto;display:block}
.brand span{font-weight:500;padding-left:1rem;border-left:1px solid var(--line);line-height:1.25}
.lang{margin-left:auto;display:flex;align-items:center;gap:.35rem;color:var(--blue)}
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
li a{display:block;padding:.85rem 1rem;margin:.5rem 0;border:1px solid var(--line);border-left:4px solid var(--blue);
border-radius:4px;text-decoration:none;color:var(--ink);background:#FAFCFE}
li a:hover{background:var(--page);border-left-color:var(--action)}li strong{display:block;color:var(--blue);font-weight:600}
li small{color:var(--muted)}
footer{max-width:60rem;margin:0 auto;padding:0 clamp(1rem,4vw,2rem) 2rem;font-size:.8125rem;color:var(--muted)}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:560px){.brand span{font-size:.8125rem;padding-left:.75rem}.brand img{height:2.25rem}.lang svg{display:none}}
</style></head><body>
<header><div class="bar">
  <span class="brand">{% if logo %}<img src="{{ logo }}" alt="GS1" width="54" height="44">{% endif %}<span>{{ product }}</span></span>
  <label class="lang"><span class="vh">{{ language_label }}</span>
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm6.9 6h-3a15.7 15.7 0 0 0-1.4-3.6A8 8 0 0 1 18.9 8ZM12 4c.8 1.2 1.5 2.5 1.9 4h-3.8c.4-1.5 1.1-2.8 1.9-4ZM4.3 14a8.2 8.2 0 0 1 0-4h3.4a16.5 16.5 0 0 0 0 4H4.3Zm.8 2h3c.3 1.3.8 2.5 1.4 3.6A8 8 0 0 1 5.1 16ZM8.1 8h-3a8 8 0 0 1 4.4-3.6C8.9 5.5 8.4 6.7 8.1 8ZM12 20c-.8-1.2-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.8-1.9 4Zm2.3-6H9.7a14.7 14.7 0 0 1 0-4h4.6a14.7 14.7 0 0 1 0 4Zm.3 5.6c.6-1.1 1.1-2.3 1.4-3.6h3a8 8 0 0 1-4.4 3.6Zm1.7-5.6a16.5 16.5 0 0 0 0-4h3.4a8.2 8.2 0 0 1 0 4h-3.4Z"/></svg>
    <select id="lang">{% for code, name in locales.items() %}<option value="{{ code }}"{% if code == locale %} selected{% endif %}>{{ name }}</option>{% endfor %}</select>
  </label>
</div></header>
<section class="hero"><div><h1>{{ title }}</h1></div></section>
<main><div class="card">{{ body|safe }}</div></main>
{% if org %}<footer>{{ footer }} {% if org_url %}<a href="{{ org_url }}">{{ org }}</a>{% else %}{{ org }}{% endif %}.</footer>{% endif %}
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
    <li><a href="{{ l.href }}" rel="noopener"><strong>{{ l.title }}</strong>
      <small>{{ l.label }}{% if l.lang %} · {{ l.lang }}{% endif %}</small></a></li>
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
    return negotiate_locale(request.headers.get('Accept-Language', ''), request.cookies.get(LOCALE_COOKIE))


def _t(locale: str, key: str, **params) -> str:
    return TEXT[locale][key].format(**params)


def _label(locale: str, term: str) -> str:
    return LINK_TYPE_LABELS[locale].get(term, term)


def _level_label(locale: str, anchor: str) -> str:
    parts = anchor.split('/01/', 1)[-1].split('/')
    pairs = dict(zip(parts[1::2], parts[2::2]))
    if '21' in pairs:
        return _t(locale, 'level.serial', value=pairs['21'])
    if '10' in pairs:
        return _t(locale, 'level.lot', value=pairs['10'])
    if '22' in pairs:
        return _t(locale, 'level.variant', value=pairs['22'])
    return _t(locale, 'level.product')


def _levels(locale: str, linkset: list[dict]) -> list[dict]:
    levels = []
    for item in linkset:
        links, seen = [], set()
        for key, value in item.items():
            if not key.startswith('https://gs1.org/voc/') or key.endswith('/defaultLink') or key.endswith('/defaultLinkMulti'):
                continue
            term = key.rsplit('/', 1)[-1]
            for link in value:
                identity = (term, link.get('href'), tuple(link.get('hreflang') or []))
                if identity in seen:
                    continue
                seen.add(identity)
                links.append({
                    'href': link.get('href'), 'title': link.get('title') or term,
                    'label': f"{_label(locale, term)} (gs1:{term})",
                    'lang': ', '.join(link.get('hreflang') or []),
                })
        if links:
            levels.append({'label': _level_label(locale, item.get('anchor', '')),
                           'description': item.get('itemDescription') or item.get('description'),
                           'links': links})
    return levels


def _hri(identifiers: str, qualifier_path: str | None) -> str:
    parts = (identifiers + (qualifier_path or '')).strip('/').split('/')
    return '  '.join(f'({parts[i]}) {parts[i + 1]}' for i in range(0, len(parts) - 1, 2))


def _page(locale: str, title: str, body: str) -> str:
    return render_template_string(_BASE, locale=locale, title=title, product=PRODUCT_NAME, logo=LOGO_DATA_URI,
                                  org=ORG_NAME, org_url=ORG_URL, footer=_t(locale, 'footer'),
                                  language_label=_t(locale, 'language'), locales=SUPPORTED_LOCALES,
                                  cookie=LOCALE_COOKIE, body=body)


def render_linkset(identifiers: str, qualifier_path: str | None, linkset: list[dict]) -> str:
    locale = _request_locale()
    title = _t(locale, 'linkset.title')
    body = render_template_string("<p class='code'>{{ hri }}</p>" + _LINKS,
                                  hri=_hri(identifiers, qualifier_path), levels=_levels(locale, linkset))
    return _page(locale, title, body)


def render_error(status: int, identifiers: str, qualifier_path: str | None, linktype: str | None,
                 available: list[dict] | None) -> str:
    locale = _request_locale()
    if status == 400:
        title, text = _t(locale, 'error.400.title'), _t(locale, 'error.400.text')
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
        "<p class='muted'>{{ status_text }}</p>" + (_LINKS if available else ''),
        text=text, hri=_hri(identifiers, qualifier_path),
        status_text=_t(locale, 'status', status=status), levels=_levels(locale, available or []))
    return _page(locale, title, body)
