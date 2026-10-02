import json
import logging
import os
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from flask import request, abort, Response, send_from_directory, jsonify, make_response
from flask_restx import Namespace, Resource

import epc_binary
import web_logic
import web_pages

web_namespace = Namespace('', description='Resolver web operations')
static_folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')

logger = logging.getLogger(__name__)


@web_namespace.route('/favicon.ico')
class Favicon(Resource):
    def get(self) -> Response:
        """
        Serve the favicon.ico file.
        """
        return send_from_directory(static_folder_path, 'favicon.ico')

    def options(self) -> tuple[dict[str, str], int]:
        """
        Handle unsupported HTTP methods gracefully for /favicon.ico.
        """
        return {'error': 'Method not allowed'}, 405


@web_namespace.route('/robots.txt')
class RobotsTxt(Resource):
    def get(self) -> Response:
        """
        Serve the robots.txt file.
        """
        return send_from_directory(static_folder_path, 'robots.txt')

    def options(self) -> tuple[dict[str, str], int]:
        """
        Handle unsupported HTTP methods gracefully for /robots.txt.
        """
        return {'error': 'Method not allowed'}, 405


@web_namespace.route('/heartbeat')
class Heartbeat(Resource):
    def get(self) -> tuple[Response, int]:
        """
        Return a simple heartbeat response to indicate the application is running.
        """
        return jsonify({'response_message': 'Server is running!'}), 200

    def head(self) -> Response:
        """
        Handle HEAD requests for /heartbeat. Return headers without a body.
        """
        response = make_response('', 200)  # Empty body with status code 200
        return response

    def options(self) -> tuple[dict[str, str], int]:
        """
        Handle unsupported HTTP methods gracefully for /heartbeat.
        """
        return {'error': 'Method not allowed'}, 405

@web_namespace.route('/<non_gs1dl_request>')
class DocOperationsNonGS1DigitalLinkRequest(Resource):
    @web_namespace.doc(description="Process non GS1 Digital Link requests (which can include compressed GS1 DLs)")
    def get(self, non_gs1dl_request: str) -> Response | tuple[Any, int]:
        response = self._handle_request(non_gs1dl_request)
        return response

    def head(self, non_gs1dl_request: str) -> Response:
        response_tuple = self._handle_request(non_gs1dl_request)

        # If the response from GET is a tuple, unpack it
        if isinstance(response_tuple, tuple):
            response_data, status_code = response_tuple
            response = make_response(response_data, status_code)
        else:
            response = make_response(response_tuple)
        return response

    def options(self, non_gs1dl_request: str | None = None) -> Response:
        """
        Handle HTTP OPTIONS requests. Returns allowed methods
        """
        # Constructs a response indicating available methods
        response = Response()
        response.headers['Allow'] = 'GET, HEAD, OPTIONS'
        return response

    def _handle_request(self, non_gs1dl_request: str) -> Response | tuple[Any, int]:
        if epc_binary.COMPRESSED_EPC.fullmatch(non_gs1dl_request):
            return _resolve_compressed_epc(non_gs1dl_request)
        try:
            logger.info('Non-GS1DL request received')
            decompress_result = web_logic.uncompress_gs1_digital_link(non_gs1dl_request)
            logger.debug('Decompress result: %s', decompress_result)
            if decompress_result['SUCCESS']:
                # Process decompressed result
                anchor_ai_code = list(decompress_result['identifiers'][0].keys())[0]
                anchor_ai = list(decompress_result['identifiers'][0].values())[0]
                identifiers = f'/{anchor_ai_code}/{anchor_ai}'
                doc_id = f'{anchor_ai_code}_{anchor_ai}'
                qualifiers = ['{0}/{1}'.format(list(d.keys())[0], quote(str(list(d.values())[0]), safe=''))
                              for d in decompress_result['qualifiers']]
                qualifier_path = '/' + '/'.join(qualifiers) if qualifiers else None
                return _process_response(doc_id, identifiers, qualifier_path or None,
                                         query_strings=_extract_query_strings(request))
            # Not a compressed GS1 Digital Link (nor anything else the resolver knows): 400, as section 2.4.1
            # asks for a request that is not a valid GS1 Digital Link URI (was 500)
            return _bad_request('/' + non_gs1dl_request, decompress_result.get('error', 'Not a GS1 Digital Link'))

        except Exception as e:
            logger.warning('Error getting document: %s', e)
            return _bad_request('/' + non_gs1dl_request, 'Not a GS1 Digital Link')


@web_namespace.route('/<anchor_ai_code>/<anchor_ai>')
class DocOperationsIdentifiersOnly(Resource):
    @web_namespace.doc(description="Get a document from the incoming URL (GS1 identifiers only)")
    def get(self, anchor_ai_code: str, anchor_ai: str) -> Response | tuple[Any, int]:
        try:
            # Ensure that a Resolver Description File is returned
            if anchor_ai_code == '.well-known' and anchor_ai == 'gs1resolver':
                return _resolver_description()

            return _resolve_path(anchor_ai_code, [anchor_ai_code, anchor_ai])

        except Exception as e:
            logger.warning('Error getting document: %s', e)
            abort(500, description="Error getting document")

    def head(self, anchor_ai_code: str, anchor_ai: str) -> Response:
        # Reuse the get logic to construct a proper Response object
        response_tuple = self.get(anchor_ai_code, anchor_ai)

        # If the response from GET is a tuple, unpack it
        if isinstance(response_tuple, tuple):
            response_data, status_code = response_tuple
            response = make_response(response_data, status_code)
        else:
            response = make_response(response_tuple)

        # Clear the body for the HEAD request
        response.data = ''
        return response

    def options(self, anchor_ai_code: str | None = None, anchor_ai: str | None = None) -> Response:
        # Response with allowed methods
        response = Response()
        response.headers['Allow'] = 'GET, HEAD, OPTIONS'
        return response


@web_namespace.route('/<anchor_ai_code>/<anchor_ai>/<path:extra_segments>')
class DocOperationsResource(Resource):
    def get(self, anchor_ai_code: str, anchor_ai: str, extra_segments: str | None = None) -> Response | tuple[Any, int]:
        try:
            logger.debug("Extra segments: %s", extra_segments)
            return _resolve_path(anchor_ai_code, [anchor_ai_code, anchor_ai, *(extra_segments or '').split('/')])

        except Exception as e:
            logger.warning('Error getting document: %s', e)
            abort(500, description="Error getting document")

    def head(self, anchor_ai_code: str, anchor_ai: str, extra_segments: str | None = None) -> Response:
        response_tuple = self.get(anchor_ai_code, anchor_ai, extra_segments)
        if isinstance(response_tuple, tuple):
            response_data, status_code = response_tuple
            response = make_response(response_data, status_code)
        else:
            response = make_response(response_tuple)

        response.data = ''
        return response

    def options(self, anchor_ai_code: str | None = None, anchor_ai: str | None = None, extra_segments: str | None = None) -> Response:
        response = Response()
        response.headers['Allow'] = 'GET, HEAD, OPTIONS'
        return response


# This function is used to extract the query strings from the request and return them as a list of parameters
# as well obtain the three contexts that are used in the web_logic.py file. Note that the decision to
# return a linkset rather than attempt a 307 redirect is made here by setting the linkset_requested variable
# should the 'Accept' header contain 'application/linkset+json' or 'application/json'
def _request_segments(anchor_ai_code: str) -> list[str] | None:
    """
    The path segments of the request as the client sent them, each percent-decoded on its own, from the AI of
    the primary key on. Werkzeug (and nginx before it) decode %2F into '/' in the path, which would split a
    value such as batch A/B (82-character set, URI Syntax 1.7, section 4.2) into two segments; the raw
    request URI keeps it whole. None when the server does not provide the raw URI.
    """
    raw = request.environ.get('RAW_URI') or request.environ.get('REQUEST_URI')
    if not raw:
        return None
    raw_segments = [unquote(s) for s in urlsplit(raw).path.split('/') if s]
    decoded = [s for s in request.path.split('/') if s]
    if anchor_ai_code not in decoded:
        return None
    start = decoded.index(anchor_ai_code)          # segments of the mount point (/api) contain no %2F
    segments = raw_segments[start:]
    return segments if segments and segments[0] == anchor_ai_code else None


def _resolve_path(anchor_ai_code: str, fallback_segments: list[str]) -> Response | tuple[Any, int]:
    """Resolves /AI/value[/qualifier/value...] taken from the raw request URI (see _request_segments)."""
    segments = _request_segments(anchor_ai_code) or [s for s in fallback_segments if s != '']
    anchor_ai = _confirm_gtin_14(segments[1], anchor_ai_code)
    identifiers = f'/{anchor_ai_code}/{anchor_ai}'
    doc_id = f'{anchor_ai_code}_{anchor_ai}'
    # values percent-encoded, so that a '/' inside one stays inside it (web_logic decodes them)
    qualifier_path = ''.join('/' + quote(s, safe='') for s in segments[2:])
    logger.debug('Processed identifiers and qualifiers: %s', identifiers + qualifier_path)
    compress = request.args.get('compress', None)
    return _process_response(doc_id, identifiers, qualifier_path=qualifier_path or None, compress=compress,
                             query_strings=_extract_query_strings(request))


def _resolve_compressed_epc(segment: str) -> Response | tuple[Any, int]:
    """
    /eh… or /ex…: an EPC binary string in a compressed GS1 Digital Link URI (EPCB 1.0.0, section 4.2; RE3 of
    URI Syntax 1.7, section 6.1.2), which a GS1-Conformant resolver SHALL decompress (Resolver 1.2.1,
    section 2.3). It is resolved as the equivalent fully uncompressed GS1 Digital Link URI on this resolver's
    own stem, which is also the anchor of any linkset: key qualifiers in the path, data attributes (a DSGTIN+
    date, +AIDC data) in the query string, passed on to the target before the request's own query string
    (section 2.12). The hostname of a '++' EPC is not used. A string that does not decode is answered 400.
    """
    try:
        epc = epc_binary.decompress(segment)
    except epc_binary.EpcDecodeError as e:
        logger.info('EPC binary string not decoded: %s', e)
        return _bad_request('/' + segment, f'Not a decodable EPC binary string: {e}')
    path, attributes = epc.path(), epc.query()
    logger.debug('%s decoded as %s %s?%s (hostname %s)', segment, epc.scheme, path, attributes, epc.hostname)
    if attributes and not web_logic._test_gs1_digital_link_syntax(f'{path}?{attributes}'):
        # the path alone is checked again when the document is read; the data attributes only here
        return _bad_request('/' + segment, f'The GS1 Digital Link decoded from the {epc.scheme} EPC is not valid: '
                                           f'{path}?{attributes}')
    segments = [unquote(s) for s in path.split('/') if s]
    identifiers = f'/{segments[0]}/{segments[1]}'
    qualifier_path = ''.join('/' + quote(s, safe='') for s in segments[2:])
    own_query = _extract_query_strings(request)
    query_strings = '&'.join(q for q in (attributes, own_query) if q)
    return _process_response(f'{segments[0]}_{segments[1]}', identifiers, qualifier_path=qualifier_path or None,
                             compress=request.args.get('compress', None), query_strings=query_strings)


def _bad_request(path: str, error: str) -> Response | tuple[Any, int]:
    """400 for a request that is not a valid GS1 Digital Link URI (section 2.4.1): HTML page or JSON."""
    if _wants_html():
        return Response(web_pages.render_error(400, path, None, None, None), status=400, mimetype='text/html')
    return {'response_status': 400, 'error': error}, 400


def _resolver_description() -> Response:
    """
    Resolver Description File (GS1-Conformant Resolver standard, section 3).
    public/gs1resolver.json holds everything that does not depend on the installation; the resolver
    root and the operator's contact details come from the environment (FQDN and RESOLVER_*, see
    .env.example), so the same image serves any domain without editing the file.
    """
    with open(os.path.join(static_folder_path, 'gs1resolver.json'), encoding='utf-8') as fh:
        description = json.load(fh)
    description.pop('_id', None)                     # internal field of the official file
    terms = os.getenv('RESOLVER_TERMS_URL', '').strip()
    if terms:
        description['termsOfUse'] = terms            # the operator's own terms of use, when there are any

    fqdn = os.getenv('FQDN', '').strip()
    if fqdn:
        description['resolverRoot'] = f'https://{fqdn}'

    org_name = os.getenv('RESOLVER_ORG_NAME', '').strip()
    if org_name:
        address = {key: os.getenv(var, '').strip() for key, var in (
            ('streetAddress', 'RESOLVER_CONTACT_STREET'),
            ('locality', 'RESOLVER_CONTACT_LOCALITY'),
            ('region', 'RESOLVER_CONTACT_REGION'),
            ('postal-code', 'RESOLVER_CONTACT_POSTCODE'),
            ('country-name', 'RESOLVER_CONTACT_COUNTRY'))}
        contact: dict[str, Any] = {'fn': org_name}
        address = {key: value for key, value in address.items() if value}
        if address:
            contact['hasAddress'] = address
        url = os.getenv('RESOLVER_ORG_URL', '').strip()
        if url:
            # vCard property (the schema allows it beside fn and hasAddress); the home page links the
            # operator's name to it, as the footer of the resolver's pages does
            contact['hasURL'] = url
        telephone = os.getenv('RESOLVER_CONTACT_TELEPHONE', '').strip()
        if telephone:
            contact['hasTelephone'] = telephone if telephone.startswith('tel:') else 'tel:' + telephone.replace(' ', '-')
        description['contact'] = contact

    response = make_response(json.dumps(description, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


def _get_request_parameters() -> tuple[list[str], str | None, str | None, list[str] | None, bool]:
    query_strings = request.args

    # do we have a 'linktype' query string? Bear in mind it might be in mixed case such as 'linkType'
    # so we will need to parse the list looking for a match where we compare lowercase values
    linktype = next((value for key, value in query_strings.items() if key.lower() == 'linktype'), None)

    # is 'context' in the query string? Do the same as for linkype to avoid case mismatch.
    context = next((value for key, value in query_strings.items() if key.lower() == 'context'), None)

    # construct the response_query_string
    response_query_string = '&'.join(f'{key}={value}' for key, value in query_strings.items())

    # do we have an 'accept-language' header?
    accept_language_list = request.headers.get('Accept-Language', 'und').split(',')

    # do we have an 'accept' header?
    linktype_is_linkset = linktype is not None and linktype.strip() in ('all', 'linkset')
    if request.headers.get('Accept'):
        media_types_list = request.headers['Accept'].split(',')
        accept = request.headers['Accept']
        linkset_requested = ('application/linkset+json' in accept or 'application/json' in accept
                             or 'application/ld+json' in accept or linktype_is_linkset)
    else:
        media_types_list = None
        linkset_requested = linktype_is_linkset

    return accept_language_list, context, linktype, media_types_list, linkset_requested


def _confirm_gtin_14(anchor_ai: str, anchor_ai_code: str) -> str:
    # if the anchor_ai_code is '01' and the length of the anchor_ai is 13, add a leading zero
    # to cope with GRIN-13 entries
    if anchor_ai_code == '01' and len(anchor_ai) == 13:
        anchor_ai = '0' + anchor_ai
    return anchor_ai


def _extract_query_strings(req: request) -> str:
    """
    The query string exactly as sent (section 2.12: the resolver SHALL transmit its entirety). Decoding and
    re-encoding it changed it: the ';' delimiter of URI Syntax 1.7, section 4.11, became %3B and a key
    without a value gained '='.
    """
    return req.query_string.decode('utf-8', 'replace')


# Allowed Content-Type values that may be reflected from the Accept header
_ALLOWED_CONTENT_TYPES = frozenset([
    'application/json',
    'application/linkset+json',
])


JSON_LD_CONTEXT = 'https://ref.gs1.org/standards/resolver/linkset-context'


def _wants_html() -> bool:
    """A browser asking for a page (explicit text/html and no JSON type), or a request with no Accept header
    at all (section 2.10: HTML when the media type is unspecified). curl and apps, which send Accept: */*,
    keep receiving JSON."""
    accept = request.headers.get('Accept')
    if accept is None:
        return True
    return 'text/html' in accept and not any(t in accept for t in ('json',))


def _append_query(href: str, query_strings: str) -> str:
    return href + ('&' if '?' in href else '?') + query_strings


def _process_response(doc_id: str, identifiers: str, qualifier_path: str | None = None, compress: str | None = None, query_strings: str = '') -> Response | tuple[Any, int]:
    accept_language_list, context, linktype, media_types_list, linkset_requested = _get_request_parameters()

    if compress:
        uncompressed_link = identifiers
        if qualifier_path:
            uncompressed_link += qualifier_path
        logger.debug('Compressing link %s', uncompressed_link)
        response_data = web_logic.get_compressed_link(uncompressed_link)
        return response_data, 200

    response_data, link_header = web_logic.read_document(identifiers, doc_id, qualifier_path, linktype,
                                                         accept_language_list, context, media_types_list,
                                                         linkset_requested)
    status = response_data['response_status']

    # ---------------------------------------------------------------- erros (400/404/500)
    if status >= 400:
        if _wants_html():
            available = None
            if status == 404 and linktype:
                # Section 2.6.2: on a 404 for a missing linkType the resolver MAY list the links that are available.
                ls_data, _ = web_logic.read_document(identifiers, doc_id, qualifier_path, None,
                                                     accept_language_list, context, None, True)
                if ls_data['response_status'] == 200:
                    available = web_logic.format_linkset_for_external_use(ls_data, identifiers)['linkset']
            html = web_pages.render_error(status, identifiers, qualifier_path, linktype, available)
            return Response(html, status=status, mimetype='text/html')
        return response_data, status

    link_values = []
    if link_header:
        link_values.append(link_header)
    link_values.append(f'<{JSON_LD_CONTEXT}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"')
    link_header = ', '.join(link_values)

    # ---------------------------------------------------------------- linkset
    if linkset_requested:
        accept = request.headers.get('Accept', '')
        if _wants_html():
            linkset = web_logic.format_linkset_for_external_use(response_data, identifiers)['linkset']
            # section 2.10: the HTML page carries the linkset as JSON-LD too
            json_ld = web_logic.format_linkset_for_external_use(response_data, identifiers, as_json_ld=True)
            response = Response(web_pages.render_linkset(identifiers, qualifier_path, linkset, json_ld),
                                status=200, mimetype='text/html')
        else:
            as_json_ld = 'application/ld+json' in accept
            body = web_logic.format_linkset_for_external_use(response_data, identifiers, as_json_ld=as_json_ld)
            if as_json_ld:
                content_type = 'application/ld+json'
            elif 'application/json' in accept and 'application/linkset+json' not in accept:
                content_type = 'application/json'
            else:
                content_type = 'application/linkset+json'
            response = Response(json.dumps(body, ensure_ascii=False), status=200, content_type=content_type)
        response.headers['Link'] = _latin1(link_header)
        return response

    # ---------------------------------------------------------------- redirecionamento
    if status == 307:
        target = response_data['data']
        response = Response(status=307)
        location = target['href']
        # Section 2.12: the whole query string is passed on, always. "fwqs": false in older records is
        # ignored: release 1.2.0 of the standard removed the option to switch it off.
        if query_strings:
            location = _append_query(location, query_strings)
        response.headers['Location'] = location
        response.headers['Link'] = _latin1(link_header)
        return response

    if status == 300:
        # Section 2.6.3, step 7: the links of the requested type among which the request could not decide,
        # as a linkset (section 2.10) of the level that holds them; an HTML page for browsers.
        choice = {'response_status': 300, 'data': [{'anchor': response_data.get('anchor', identifiers),
                                                     response_data.get('linktype_key'): response_data['data']}]}
        linkset = web_logic.format_linkset_for_external_use(choice, identifiers)
        if _wants_html():
            json_ld = web_logic.format_linkset_for_external_use(choice, identifiers, as_json_ld=True)
            response = Response(web_pages.render_linkset(identifiers, qualifier_path, linkset['linkset'], json_ld,
                                                         choice=True), status=300, mimetype='text/html')
        else:
            response = Response(json.dumps(linkset, ensure_ascii=False), status=300,
                                content_type='application/linkset+json')
        response.headers['Link'] = _latin1(link_header)
        return response

    return response_data, status


def _latin1(value: str) -> str:
    try:
        return value.encode('latin-1').decode('ascii')
    except UnicodeError:
        return value.encode('unicode_escape').decode('ascii')
