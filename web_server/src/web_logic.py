import json
import logging
import os
import re
import subprocess
from typing import Any
from urllib.parse import quote, unquote


import web_db

logger = logging.getLogger(__name__)

# Pattern for validating GS1 Digital Link path segments (AI codes + values).
# Allows alphanumeric characters, hyphens, dots, underscores, percent-encoded bytes, and parentheses.
_SAFE_GS1_PATTERN = re.compile(r'^[A-Za-z0-9\-._~%()/:+]+$')


def _validate_gs1_input(value: str) -> str:
    """Reject values containing shell-special or unexpected characters before passing to subprocess."""
    if not _SAFE_GS1_PATTERN.match(value):
        raise ValueError(f"Invalid characters in GS1 input: {value!r}")
    return value


def _call_gs1_toolkit(ai_data_string: str) -> bool:
    """
    This function calls the GS1 Digital Link Toolkit to validate the syntax of a GS1 Digital Link URL.
    :param ai_data_string:
    :return:
    """
    _validate_gs1_input(ai_data_string)
    node_path = "/usr/bin/node"
    toolkit_path = "/app/gs1-digitallink-toolkit/callGS1encoder.js"

    process = subprocess.Popen([node_path, toolkit_path, ai_data_string],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        logger.warning("_call_gs1_toolkit error: %s", stderr.decode('utf-8'))
        return False

    return True


def uncompress_gs1_digital_link(compressed_link: str) -> dict[str, Any]:
    """
    This function checks if the AI data string is a compressed GS1 Digital link.
    The only library that does this id the GS1 Digital Link Toolkit GS1DigitalLinkToolkit.js
    :param compressed_link: The compressed link to check
    :return: The uncompressed GS1 Digital Link if the AI data string is compressed, otherwise a failure message.
    """
    _validate_gs1_input(compressed_link)
    node_path = "/usr/bin/node"
    toolkit_path = "/app/gs1-digitallink-toolkit/callGS1toolkit.js"
    process = subprocess.Popen([node_path, toolkit_path, compressed_link, 'uncompress'],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        logger.warning("uncompress_gs1_digital_link error: %s", stderr.decode('utf-8'))
        return {'result': False, 'error': stderr.decode('utf-8')}

    logger.debug('Decompression stdout: %s', stdout)
    return json.loads(stdout)


def compress_gs1_digital_link(uncompressed_link: str) -> dict[str, Any]:
    """
    This function compresses a GS1 Digital Link URL.
    The only library that does this id the GS1 Digital Link Toolkit GS1DigitalLinkToolkit.js
    :param uncompressed_link: The uncompressed link to compress
    :return: The compressed GS1 Digital Link URL if successful, otherwise a failure message.
    """
    _validate_gs1_input(uncompressed_link)
    node_path = "/usr/bin/node"
    toolkit_path = "/app/gs1-digitallink-toolkit/callGS1toolkit.js"

    process = subprocess.Popen([node_path, toolkit_path, uncompressed_link, 'compress'],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

    stdout, stderr = process.communicate()

    if process.returncode != 0:
        logger.warning("compress_gs1_digital_link error: %s", stderr.decode('utf-8'))
        return {'result': False, 'error': stderr.decode('utf-8')}

    return json.loads(stdout)


def _encode(value: str) -> str:
    """A path segment value, percent-encoded (every reserved character, '/' included)."""
    return quote(value, safe='')


def _encoded_identifier(identifier: str) -> str:
    """'/AI/value' with the value percent-encoded."""
    ai, _, value = identifier.strip('/').partition('/')
    return f'/{ai}/{_encode(value)}'


def _test_gs1_digital_link_syntax(url: str) -> bool:
    """
    Tests the path of a GS1 Digital Link (e.g. /01/09506000134352/10/A%2FB, values percent-encoded) with the
    GS1 Barcode Syntax Engine's own GS1 Digital Link parser, which checks what an element string cannot:
    the qualifiers of the key and their order (URI Syntax 1.7, section 4.9) and that no data attribute is in
    the path (section 4.10), besides lengths, character sets and check digits (GS1-Conformant Resolver
    1.2.1, section 2.4, tests 1 to 5). The domain is irrelevant to the check.
    """

    try:
        if url.count('/') < 2:
            return False
        return _call_gs1_toolkit('https://id.gs1.org' + url)

    except IndexError as e:
        logger.warning("URL is missing expected segments: %s", e)
        return False
    except KeyError as e:
        logger.warning("KeyError in _call_gs1_toolkit: %s", e)
        return False
    except Exception as e:
        logger.warning("Unexpected error in _test_gs1_digital_link_syntax: %s", e)
        return False


# The official _match_*() helpers and _get_appropriate_linktype_docs_list() were replaced by choose_links()
# (below): they failed on links without a media type and answered 300 where the standard expects the default.


def _do_qualifiers_match(qualifier_path: str | None, doc_qualifiers: list[dict[str, str]]) -> tuple[bool, list[dict[str, str]] | None]:
    """
    Checks if there is a match between the qualifier path and the document qualifiers.
    If the document qualifiers include template variables, this function replaces them
    with their actual values from the qualifier path.

    qualifiers are lists in the document with up to three sets of AI codes and values:
          [{'aiCode1': 'aiValue1'}, {'aiCode2': 'value2'}, {'aiCode3': 'value3'}
     They may be in a different order, so we need to check for a match with the qualifier path

    :param qualifier_path: A qualifier path to be checked for a match.
    :param doc_qualifiers: Document qualifiers that may include template variables.

    :return: A tuple where the first value indicates if a match is found
             (True if a match found, False otherwise), and the second value is a
             list of dictionaries containing the template variables replaced with
             their matching actual values, if any. Returns False and None if no match found.
    """
    try:
        # Handle the case where qualifier_path is None or empty
        if qualifier_path is None or qualifier_path == '/':
            # Return True only if doc_qualifiers is also empty
            return len(doc_qualifiers) == 0, []

        # Initialize the list to store template variables
        template_variable_list = []

        # Initialize the list to store qualifiers path
        qualifiers_path_list = []

        # Split the qualifier path into parts
        qualifier_path_parts = qualifier_path.split('/')

        # Iterate through qualifier path parts and construct the qualifiers path list
        for i in range(1, len(qualifier_path_parts), 2):
            qualifiers_path_list.append({qualifier_path_parts[i]: qualifier_path_parts[i + 1]})

        # Iterate through each doc qualifier
        for doc_qualifier in doc_qualifiers:
            # Process each key-value pair in the doc qualifier
            for key, value in doc_qualifier.items():
                # Check if the value is a template variable
                if value[0] == '{' and value[-1] == '}':
                    template_variable = value
                    # If the template variable is found in the qualifiers path list, replace it with the actual value
                    for qualifier_path_item in qualifiers_path_list:
                        if key in qualifier_path_item:
                            template_variable_list.append(
                                {
                                    'template_variable': template_variable,
                                    'value': qualifier_path_item[key]
                                })
                            doc_qualifier[key] = qualifier_path_item[key]

        # Check if qualifiers in the path list have a match in document qualifiers. If not, return False
        # Importantly, we return true if ANY qualifier in the path list is in the document qualifiers.
        # In resolver 1.x and 2.x, ALL qualifiers in the path list must be in the document qualifiers.
        no_qualifiers_match = True
        for qualifier_path_item in qualifiers_path_list:
            if qualifier_path_item in doc_qualifiers:
                no_qualifiers_match = False
                break

        if no_qualifiers_match:
            return False, None

        # If no issues encountered above, return True along with the template variable list
        return True, template_variable_list

    except KeyError as e:
        logger.warning('_do_qualifiers_match KeyError: %s', e)
        return False, [f"KeyError occurred. Details: {str(e)}"]
    except TypeError as e:
        logger.warning('_do_qualifiers_match TypeError: %s', e)
        return False, [f"TypeError occurred. Expected list or dictionary-like object. Details: {str(e)}"]
    except Exception as e:
        logger.warning('_do_qualifiers_match error: %s', e)
        return False, [f"Unexpected error occurred. Details: {str(e)}"]


def _author_link_header_with_pointer_to_linkset(linkset: list[dict[str, Any]]) -> str:
    """
    This function creates a Link header with a pointer to the linkset.
    This a change from previous versions of the GS1 Resolver Standard that tries to out all relevant links from
    the linkset into the Link header. This is not practical for large linksets and can overwhelm some web clients
    with the header size! This function replaces _author_compact_links_for_link_header(linkset) which did this.
    Example: Link: <{current URL, minus query string, + linkType=linkset>; rel="application/linkset"; type="application/linkset"; title="Linkset for {identifiers}"
    :param linkset (list): The input JSON data - to make this function backwards-compatible with _author_compact_links_for_link_header()
    :return: The Link header with a pointer to the linkset.
    """
    identifiers = linkset[0].get("anchor")
    return f'<https://{os.getenv("FQDN", "set-domain-name-in-env-variable-FQDN.com")}{identifiers}?linkType=linkset>; rel="linkset"; type="application/linkset+json"; title="Linkset for {identifiers}"'



def _process_serialised_identifier(identifier: str) -> dict[str, Any] | None:
    """
    Processes the serialised component of the identifier using binary search to find
    the longest prefix that matches a database document with template variables.

    Uses binary search over the identifier length to minimise DB calls (O(log n) instead of O(n)).
    After finding the boundary between found/not-found, it scans downward from the longest
    match to find one with template variables {0} or {1}.

    :param identifier: The identifier portion of the digital link .e.g. '/8004/0950600013430000001'
    :return: The wanted_db_document with the serialised component processed, or None if no match found.
    """
    min_len = 12
    max_len = len(identifier) - 1

    if max_len <= min_len:
        return None

    # Binary search: find the longest prefix that exists in the DB
    longest_found = -1
    lo, hi = min_len + 1, max_len
    while lo <= hi:
        mid = (lo + hi) // 2
        result = web_db.read_document(identifier[:mid])
        if result['response_status'] == 200:
            longest_found = mid
            lo = mid + 1  # try longer
        else:
            hi = mid - 1  # try shorter

    if longest_found == -1:
        return None

    # From the longest found match, scan downward looking for template variables
    for i in range(longest_found, min_len, -1):
        if i == longest_found:
            wanted_db_document = web_db.read_document(identifier[:i])
        else:
            wanted_db_document = web_db.read_document(identifier[:i])
        if wanted_db_document['response_status'] != 200:
            continue

        wanted_json = json.dumps(wanted_db_document['data'])

        if '{0}' not in wanted_json and '{1}' not in wanted_json:
            continue

        # Extract the matched value and the remainder
        ai_value = identifier[:i].split('/')[2]
        ai_partial_value = identifier.split('/')[2].replace(ai_value, '')

        # Replace template variables with actual values
        wanted_json = wanted_json.replace('{0}', ai_value)
        wanted_json = wanted_json.replace('{1}', ai_partial_value)

        wanted_db_document['data'] = json.loads(wanted_json)
        return wanted_db_document

    return None


def _validate_and_fetch_document(identifier: str, qualifier_path: str | None, doc_id: str) -> dict[str, Any]:
    """
    searches for a partial identifier match and returns the wanted_db_document if found.
    If not found, it will return the same wanted_db_document as before.

    :param identifier: The identifier portion of the digital link (e.g., '01/09550001563533')
    :param qualifier_path: The qualifier path of the digital link, if any (e.g., '/22/455') only used to validate syntax
    :param doc_id: The document ID to look up in the database.
    :return: the wanted_db_document from trying to read the document with the given doc_id
             from the database - or an error message if the document is not found.
    """
    try:
        # Concatenate the identifiers and qualifier_path to form the complete digital link
        digital_link = _encoded_identifier(identifier) + (qualifier_path if qualifier_path is not None else '')

        # Check if the digital link has valid syntax.
        dl_test_result = _test_gs1_digital_link_syntax(digital_link)

        # If the link syntax is invalid, return an error dictionary along with a `None` wanted_db_document.
        if not dl_test_result:
            logger.debug('Invalid GS1 Digital Link Syntax')
            return {"response_status": 400, "error": f"Invalid GS1 Digital Link syntax: {digital_link}"}

        # If the link syntax is valid, attempt to fetch the corresponding document from the database.
        logger.debug('identifier: %s', identifier)
        wanted_db_document = web_db.read_document(doc_id)

        if wanted_db_document['response_status'] == 200:
            # document found - there is nothing more we need to do here.
            return wanted_db_document

        # If we are being asked to search for GIAIs (8004), GRAIs (8003) or SSCCs (00) then an exact match may not
        # be immediately available as these are serialised identifiers.
        # _process_serialised_component() will search for a partial match and return
        # the wanted_db_document if found. If not found, it will return the same wanted_db_document as before.
        # If you wish you can add other AI codes to this list if you think you would like to apply the same
        # logic to them. For example, partial GTINs (01) might be useful. If so, just add their AI code with a
        # leading and trailing forward-slash to the 'prefixes' list below. e.g. adding GTIN:
        #     if any(identifier.startswith(prefix) for prefix in  = ['/8003/', '/8004/', '/00/', '/01/']):
        # We include both leading and trailing forward-slashes to ensure we are matching the AI code and not
        # a partial match of the AI value.
        if any(identifier.startswith(prefix) for prefix in ['/8003/', '/8004/', '/00/']):
            serialised_document = _process_serialised_identifier(identifier)
            if serialised_document is not None:
                return serialised_document

        # We have searched and there is no partial match that has template variables {0} or {1}
        return {"response_status": 404, "error": f"No document found for anchor: {doc_id}"}

    except ValueError as e:
        logger.warning('_validate_and_fetch_document ValueError: %s', e)
        return {"response_status": 400,
                "error": f"ValueError occurred. Possibly invalid identifiers or qualifier_path. Details: {str(e)}"}

    except TypeError as e:
        logger.warning('_validate_and_fetch_document TypeError: %s', e)
        return {"response_status": 400,
                "error": f"TypeError occurred. Expected string-like object. Details: {str(e)}"}

    except Exception as e:
        logger.error('_validate_and_fetch_document error: %s', e)
        return {"response_status": 500, "error": f"Unexpected error occurred. Details: {str(e)}"}


def _replace_linkset_template_variables(linkset: list[dict[str, Any]], template_variables_list: list[dict[str, str]]) -> list[dict[str, Any]] | dict[str, Any]:
    """
    if template_variables_list is not empty, we need to replace the template variables in the linkset
    # with the actual values from the qualifier_path. Fortunately _do_qualifiers_match() has done the
    # hard work for us and we can now replace the template variables with the actual values.

    :param linkset: A dictionary that contains the linkset data.
    :param template_variables_list: A list of dictionaries that contain the template variables and their actual values.
    :return: The linkset dictionary with the template variables replaced with the actual values.
    """
    try:
        if len(template_variables_list) > 0:
            linkset_json = json.dumps(linkset)
            for template_variable in template_variables_list:
                linkset_json = linkset_json.replace(template_variable['template_variable'],
                                                    template_variable['value'])
            linkset = json.loads(linkset_json)
        return linkset

    except KeyError as e:
        return {"response_status": 400, "error": f"KeyError occurred - {str(e)}"}

    except TypeError as e:
        logger.warning('replace_linkset_template_variables TypeError: %s', e)
        return {"response_status": 400,
                "error": f"TypeError occurred. Expected list or dictionary-like object - {str(e)}"}

    except json.JSONDecodeError as e:
        logger.warning('replace_linkset_template_variables JSONDecodeError: %s', e)
        return {"response_status": 400, "error": f"JSONDecodeError occurred. Invalid JSON format - {str(e)}"}

    except Exception as e:
        logger.error('replace_linkset_template_variables error: %s', e)
        return {"response_status": 500, "error": f"Unexpected error - {str(e)}"}



# ---------------------------------------------------------------------------------------------------------------
# Helpers for the qualifier hierarchy, linkType normalisation and linkset anchors.
# ---------------------------------------------------------------------------------------------------------------
_GS1_VOC_PREFIXES = ('https://gs1.org/voc/', 'http://gs1.org/voc/',
                     'https://ref.gs1.org/voc/', 'http://ref.gs1.org/voc/', 'gs1:')

# Canonical order of key qualifiers in a GS1 Digital Link path (URI Syntax 1.7, section 4.9); anything else last
_QUALIFIER_ORDER = ['22', '10', '21', '235', '8011', '254', '7040', '8020', '8019']


def normalise_linktype(linktype: str | None) -> str | None:
    """
    Accepts a link type in any of the forms seen in practice and returns the bare vocabulary term:
    'instructions', 'gs1:instructions', 'https://gs1.org/voc/instructions' and 'https://ref.gs1.org/voc/instructions'.
    The keywords 'linkset' and 'all' are handled before this function (unprefixed, as on the GS1 Global resolver).
    """
    if linktype is None:
        return None
    value = linktype.strip()
    for prefix in _GS1_VOC_PREFIXES:
        if value.lower().startswith(prefix):
            return value[len(prefix):]
    return value


def _parse_qualifier_path(qualifier_path: str | None) -> list[dict[str, str]]:
    if not qualifier_path:
        return []
    parts = [p for p in qualifier_path.strip('/').split('/') if p != '']
    # values arrive percent-encoded (a batch may contain '/', see web_namespace._request_segments)
    return [{parts[i]: unquote(parts[i + 1])} for i in range(0, len(parts) - 1, 2)]


_UNIT_QUALIFIERS = {'21', '235'}   # qualifiers that identify a single unit of a GTIN or ITIP


def _entry_applies(path_qualifiers: list[dict[str, str]], doc_qualifiers: list[dict[str, str]]) -> tuple[bool, list[dict[str, str]]]:
    """
    A document entry applies to the request when ALL of its qualifiers are present in the path (template
    variables such as {0} match any value of the same AI). The GTIN entry (no qualifiers) therefore applies to
    any batch/serial, and a batch entry to any serial within that batch: this is the "walk up the tree"
    described in sections 2.5.9 and 2.5.10 of the GS1-Conformant Resolver Standard.
    """
    path_map = {k: v for q in path_qualifiers for k, v in q.items()}
    template_variables = []
    for doc_qualifier in doc_qualifiers:
        for key, value in doc_qualifier.items():
            if key not in path_map:
                return False, []
            if isinstance(value, str) and value.startswith('{') and value.endswith('}'):
                template_variables.append({'template_variable': value, 'value': path_map[key]})
            elif value != path_map[key]:
                return False, []
    return True, template_variables


def _qualifier_path_from(doc_qualifiers: list[dict[str, str]], template_variables: list[dict[str, str]]) -> str:
    values = {t['template_variable']: t['value'] for t in template_variables}
    pairs = []
    for q in doc_qualifiers:
        for k, v in q.items():
            pairs.append((k, values.get(v, v)))
    pairs.sort(key=lambda kv: _QUALIFIER_ORDER.index(kv[0]) if kv[0] in _QUALIFIER_ORDER else len(_QUALIFIER_ORDER))
    return ''.join(f'/{k}/{_encode(v)}' for k, v in pairs)


def _find_linktype_key(linkset_item: dict[str, Any], short_linktype: str) -> str | None:
    """Finds the link type key in the linkset case-insensitively (defaultlink == defaultLink)."""
    wanted = f'https://gs1.org/voc/{short_linktype}'.lower()
    for key in linkset_item:
        if key.lower() == wanted:
            return key
    return None


def _public_link(link: dict[str, Any]) -> dict[str, Any]:
    """Drops null values (e.g. type=None), which make the linkset fail the official schema, and "fwqs": the
    query string is always passed on (GS1-Conformant Resolver 1.2.1, section 2.12; the option to switch
    it off was removed in release 1.2.0), so the attribute of older records means nothing any more."""
    return {k: v for k, v in link.items()
            if v is not None and k != 'fwqs' and not (k == 'hreflang' and v == [])}


def language_ranges(accept_language: list[str] | None) -> list[str]:
    """Accept-Language as language ranges, most preferred first: q-values honoured, q=0 dropped, case folded."""
    ranges = []
    for position, entry in enumerate(accept_language or []):
        tag, *params = [part.strip() for part in entry.split(';')]
        weight = 1.0
        for param in params:
            if param.lower().startswith('q='):
                try:
                    weight = float(param[2:])
                except ValueError:
                    weight = 0.0
        if tag and weight > 0:
            ranges.append((-weight, position, tag.lower()))
    return [tag for _, _, tag in sorted(ranges)]


def _language_match(links: list[dict[str, Any]], ranges: list[str]) -> list[dict[str, Any]] | None:
    """
    The links that best serve the language preferences, or None (RFC 4647 lookup). For each range, most
    preferred first: the links in exactly that language ('pt-br' → pt-BR), then in a shorter form of it
    ('pt-br' → pt), then in a more specific one ('pt' → pt-BR). The first range served decides.
    """
    def tags(link: dict[str, Any]) -> list[str]:
        return [str(t).lower() for t in (link.get('hreflang') or []) if t]
    for wanted in ranges:
        if wanted == '*':
            return list(links)
        candidate = wanted
        while candidate:
            hit = [link for link in links if candidate in tags(link)]
            if hit:
                return hit
            candidate = candidate.rpartition('-')[0]
        hit = [link for link in links if any(tag.startswith(wanted + '-') for tag in tags(link))]
        if hit:
            return hit
    return None


def _media_type(link: dict[str, Any]) -> str:
    return str(link.get('type') or '').split(';')[0].strip().lower()


def choose_links(links: list[dict[str, Any]], ranges: list[str], context: str | None,
                 media_types: list[str] | None) -> tuple[list[dict[str, Any]], bool]:
    """
    Best match among links of one link type (GS1-Conformant Resolver 1.2.1, section 2.6.3, in the order it
    suggests: media type, then language, then context). Returns the remaining links and whether the request
    decided anything (a media type, language or context matched). Links with no media type, language or
    context are handled like any other: nothing here fails on missing attributes.
    """
    pool, decided = list(links), False
    wanted_types = {m.strip().lower() for m in (media_types or []) if m and '*' not in m}
    if wanted_types:
        hit = [link for link in pool if _media_type(link) in wanted_types]
        if hit and len(hit) < len(pool):
            pool, decided = hit, True
    by_language = _language_match(pool, ranges)
    if by_language:
        pool, decided = by_language, True
    else:
        neutral = [link for link in pool if not link.get('hreflang') or 'und' in link.get('hreflang')]
        if neutral:
            pool = neutral
    if context:
        hit = [link for link in pool if context in (link.get('context') or [])]
        if hit:
            pool, decided = hit, True
    return pool, decided


def with_default_multi(item: dict[str, Any], default_linktype: str | None) -> dict[str, Any]:
    """
    The linkset item with gs1:defaultLinkMulti (section 2.5.8) when its links of the key's default link type
    are several (language variants of the default target): the resolver chooses among them by the request's
    preferences and falls back to gs1:defaultLink, and the linkset declares them as the standard requires.
    """
    short = normalise_linktype(default_linktype)
    key = _find_linktype_key(item, short) if short else None
    links = item.get(key) if key else None
    multi_key = _find_linktype_key(item, 'defaultLinkMulti')
    if isinstance(links, list) and len(links) > 1:
        item = {k: v for k, v in item.items() if k != multi_key}
        item['https://gs1.org/voc/defaultLinkMulti'] = [dict(link) for link in links]
    elif multi_key and isinstance(item[multi_key], dict):
        # the data entry API stores one link with several languages as a single object
        item = dict(item)
        item[multi_key] = [item[multi_key]]
    return item


def _handle_link_type(linktype: str | None, default_linktype: str, linkset: list[dict[str, Any]], accept_language_list: list[str], context: str | None, media_types_list: list[str] | None,
                      linkset_requested: bool = False) -> dict[str, Any]:
    """
    One level of the record: the response for the requested link type, or for no link type the default
    (GS1-Conformant Resolver 1.2.1, sections 2.6.1 to 2.6.3). 307 with the link, 300 with the links of that
    type when the request cannot decide among them, 404 when this level has nothing of that type.
    """
    try:
        if linkset_requested or linktype in ['all', 'linkset']:
            return {"response_status": 200, "data": linkset}
        item = with_default_multi(linkset[0], default_linktype)
        ranges = language_ranges(accept_language_list)

        if linktype is None:
            # Section 2.6.3, steps 3 and 4: only gs1:defaultLinkMulti and gs1:defaultLink compete; a language
            # variant wins only when the request decides it, otherwise the default link answers (examples 5-7).
            default_key = _find_linktype_key(item, 'defaultLink')
            default_link = item.get(default_key) if default_key else None
            if isinstance(default_link, list):
                default_link = default_link[0] if default_link else None
            multi_key = _find_linktype_key(item, 'defaultLinkMulti')
            if multi_key:
                pool, decided = choose_links(item[multi_key], ranges, context, media_types_list)
                if decided and pool:
                    hrefs = [link.get('href') for link in pool]
                    if default_link and default_link.get('href') in hrefs:
                        return {"response_status": 307, "data": default_link}
                    return {"response_status": 307, "data": pool[0]}
            if not default_link:
                return {"response_status": 404, "error": "No default link at this level"}
            return {"response_status": 307, "data": default_link}

        key = _find_linktype_key(item, normalise_linktype(linktype))
        if key is None:
            return {"response_status": 404, "error": f"Linktype not found in linkset: {linktype}"}
        links = item[key] if isinstance(item[key], list) else [item[key]]
        pool, _ = choose_links([link for link in links if isinstance(link, dict)], ranges, context, media_types_list)
        if not pool:
            return {"response_status": 404, "error": f"No link found for linktype: {linktype}"}
        if len(pool) == 1:
            return {"response_status": 307, "data": pool[0]}
        # Section 2.6.3, step 7: no best match among links of the same type (example 11)
        return {"response_status": 300, "data": pool, "linktype_key": key}

    except Exception as e:
        logger.error('handle_link_type error: %s', e)
        return {"response_status": 500, "error": f"Unexpected error occurred. Details: {str(e)}"}


def get_compressed_link(uncompressed_link: str) -> dict[str, Any]:
    try:
        compressed_link = compress_gs1_digital_link(uncompressed_link)
        if compressed_link.get('SUCCESS'):
            return {'response_status': 200, 'COMPRESSED_LINK': compressed_link['COMPRESSED']}
        return {'response_status': 400,
                'error': 'Compression failed. Check GS1 Digital Link syntax is correct before compressing'}

    except Exception as e:
        logger.warning('get_compressed_link error: %s', e)
        return {'response_status': 400,
                'error': 'Unexpected error occurred. Check GS1 Digital Link syntax is correct before compressing'}


def _clean_q_values_from_header_entries(header_values_list: list[str]) -> list[str]:
    """
    Returns a new list with quality-value parameters stripped (e.g., ';q=0.8').
    Does not mutate the input list.
    :param header_values_list:
    :return: cleaned list
    """
    return [entry.split(';')[0] for entry in header_values_list]


def format_linkset_for_external_use(response_data: dict[str, Any], identifiers: str, as_json_ld: bool = False) -> dict[str, Any]:
    """
    Builds the linkset for the client.
    - Default: plain RFC 9264 ({"linkset": [...]}) that validates against https://ref.gs1.org/standards/resolver/linkset-schema;
      the JSON-LD context is referenced in the Link header.
    - as_json_ld=True (Accept: application/ld+json): same content with the @context embedded (section 2.10).
    """
    fqdn = os.getenv('FQDN', 'replace_with_environment_variable_FQDN_see_README.com')
    linkset = []
    for item in response_data['data']:
        out = {}
        for key, value in item.items():
            if key.startswith('_'):
                continue
            if key == 'anchor':
                out['anchor'] = value if str(value).startswith('http') else f"https://{fqdn}{value}"
            elif key in ('itemDescription', 'description'):
                if value:
                    out[key] = value
            elif key.startswith('https://gs1.org/voc/') or key.startswith('http'):
                links = value if isinstance(value, list) else [value]
                clean = []
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    link = _public_link(link)
                    if 'hreflang' in link:
                        link['hreflang'] = [h for h in link['hreflang'] if h != 'und']
                        if not link['hreflang']:
                            del link['hreflang']
                    clean.append(link)
                if clean:
                    out[key] = clean
        linkset.append(out)

    if not as_json_ld:
        return {"linkset": linkset}

    ai_code = identifiers.split('/')[1]
    ai_value = identifiers.split('/')[2]
    response_linkset = {
        "@context": {
            "schema": "https://schema.org/",
            "gs1": "https://gs1.org/voc/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "dcterms": "http://purl.org/dc/terms/",
            "href": "@id",
            "hreflang": {"@id": "dcterms:language", "@container": "@set"},
            "title": {"@id": "dcterms:title"},
            "type": {"@id": "dcterms:format"},
            "itemDescription": {"@id": "rdfs:comment"},
            "linkset": "@nest"
        },
        "@id": f"https://{fqdn}/{ai_code}/{ai_value}",
        "gs1:elementStrings": f"({ai_code}){ai_value}",
        "linkset": linkset,
    }
    return response_linkset



def read_document(gs1dl_identifier: str, doc_id: str, qualifier_path: str | None = '/', linktype: str | None = None, accept_language_list: list[str] | None = None, context: str | None = None,
                  media_types_list: list[str] | None = None, linkset_requested: bool = False) -> tuple[dict[str, Any], str | None]:
    """
    Resolves the request by walking the GTIN hierarchy (GS1-Conformant Resolver Standard 2.5.9/2.5.10):
    entries that apply to the requested path are evaluated from the most specific (e.g. batch/lot) to the
    least specific (GTIN). Redirection: the first level holding the requested link wins; if none does,
    404 (section 2.6.2). Linkset: gathers the links of every applicable level, each with its own anchor.
    Always returns the tuple (response, Link header).
    """
    try:
        doc_data = _validate_and_fetch_document(gs1dl_identifier, qualifier_path, doc_id)
        if doc_data['response_status'] != 200:
            return doc_data, None

        database_doc = doc_data['data']
        accept_language_list = accept_language_list or []     # q-values kept: language_ranges() orders by them
        media_types_list = _clean_q_values_from_header_entries(media_types_list) if media_types_list else []
        default_linktype = database_doc.get('defaultLinktype', '')
        path_qualifiers = _parse_qualifier_path(qualifier_path)

        applicable = []
        for entry in database_doc['data']:
            doc_qualifiers = entry.get('qualifiers') or []
            applies, template_variables = _entry_applies(path_qualifiers, doc_qualifiers)
            if not applies:
                continue
            if template_variables:
                entry['linkset'] = _replace_linkset_template_variables(entry['linkset'], template_variables)
            entry['_qualifier_path'] = _qualifier_path_from(doc_qualifiers, template_variables)
            entry['linkset'] = [with_default_multi(item, default_linktype) for item in entry['linkset']]
            # Most granular first: a serial number (or TPX) names one unit, so its record outranks a batch or
            # variant record even with fewer qualifiers (GS1-Conformant Resolver 1.2.1, section 2.5.9, rule 4:
            # 01+21 before 01+22+10); otherwise the record with more qualifiers wins.
            entry['_specificity'] = (any(k in _UNIT_QUALIFIERS for q in doc_qualifiers for k in q), len(doc_qualifiers))
            applicable.append(entry)

        if not applicable:
            return {"response_status": 404, "error": f"No links found for {gs1dl_identifier}{qualifier_path or ''}"}, None

        applicable.sort(key=lambda e: e['_specificity'], reverse=True)
        identifier = _encoded_identifier(gs1dl_identifier)
        pointer = _author_link_header_with_pointer_to_linkset(
            [{"anchor": identifier + (qualifier_path or '').rstrip('/')}])

        if linkset_requested:
            merged = []
            for entry in applicable:
                for item in entry['linkset']:
                    item = dict(item)
                    item['anchor'] = identifier + entry['_qualifier_path']
                    merged.append(item)
            return {"response_status": 200, "data": merged}, pointer

        last_result = None
        for entry in applicable:
            result = _handle_link_type(linktype, default_linktype, entry['linkset'],
                                       accept_language_list, context, media_types_list)
            if result['response_status'] == 300:
                result['anchor'] = identifier + entry['_qualifier_path']   # the level whose links are offered
            if result['response_status'] in (300, 307):
                return result, pointer
            if result['response_status'] >= 500:
                return result, None
            last_result = result

        return last_result or {"response_status": 404, "error": "No link found"}, None

    except Exception as e:
        logger.error('read_document: Internal Server Error', exc_info=True)
        return {"response_status": 500, "error": "Internal Server Error: " + str(e)}, None
