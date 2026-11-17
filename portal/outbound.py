"""
Requests the portal sends to addresses its users chose (Documentation/adr/0029-outbound-requests.md): the link checker,
single sign-on's discovery, keys and token exchange, and the check of a QR code domain.

A host name is resolved once; every address it resolves to must be global (not private, loopback, link-local, shared,
reserved, …, nor an IPv4 address of those kinds inside an IPv6 one); the connection is then made to one of those
checked addresses, never to a name resolved again. The request keeps the name: the Host header, the name sent in TLS
(SNI) and the certificate's check are those of the name, so a site behind a shared address answers as usual and a
certificate is verified as before. A name whose answer changes between the check and the connection (DNS rebinding)
therefore cannot lead a request into the server's own network.

Redirects are never followed here: a caller that follows them (the link checker) calls request() again for each hop,
which checks the new name in the same way. Proxies from the environment are not used (a proxy would resolve the name
itself).

request() raises PrivateAddress (an address that is not global), Unresolvable (the name has no address), BadAddress
(not an http(s) address, user information, no host), or the requests exceptions of the connection.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

MAX_ADDRESSES = 3          # addresses tried in turn when one does not connect (IPv6 without a route, for instance)
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class OutboundError(Exception):
    """An address the portal does not contact."""


class PrivateAddress(OutboundError):
    """The name resolves to at least one address that is not global."""


class Unresolvable(OutboundError):
    """The name has no address."""


class BadAddress(OutboundError):
    """Not an http(s) address with a host, or one with user information."""


def is_global(address: str) -> bool:
    """Whether an address may be contacted: global, and so is an IPv4 address carried inside an IPv6 one (mapped,
    6to4, the NAT64 well-known prefix)."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6:
        inner = ip.ipv4_mapped or ip.sixtofour
        if inner is None and ip in NAT64:
            inner = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if inner is not None and not inner.is_global:
            return False
    return ip.is_global


def addresses(host: str, port: int = 443, allow_private: bool = False) -> list[str]:
    """The addresses of a name, resolved once, in the resolver's order; every one checked. Raises Unresolvable or
    PrivateAddress."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise Unresolvable(host)
    found = list(dict.fromkeys(info[4][0] for info in infos))
    if not found:
        raise Unresolvable(host)
    if not allow_private and not all(is_global(a) for a in found):
        raise PrivateAddress(host)
    return found


def public_host(host: str) -> bool | None:
    """True if every address of the name is global, False if one is not, None if it has none (for a check made when a
    setting is saved; a request is checked again by request())."""
    try:
        addresses(host)
    except Unresolvable:
        return None
    except PrivateAddress:
        return False
    return True


class _PinnedAdapter(HTTPAdapter):
    """Connects to one checked address, keeping the name for TLS (SNI and the certificate's check)."""

    def __init__(self, address: str, name: str):
        self.address, self.name = address, name
        super().__init__(max_retries=0)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        host_params = {**host_params, "host": self.address}
        if host_params.get("scheme") == "https":
            pool_kwargs = {**pool_kwargs, "server_hostname": self.name, "assert_hostname": self.name}
        return host_params, pool_kwargs


def target(url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, Host header) of an address; raises BadAddress."""
    try:
        parts = urlsplit(str(url))
        port = parts.port
    except ValueError:
        raise BadAddress(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        raise BadAddress(url)
    port = port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port, parts.netloc


def request(method: str, url: str, allow_private: bool = False, **kwargs) -> requests.Response:
    """One request to an address chosen by a user, without following redirects, connected to an address of the name
    checked once (see the module's description). kwargs are those of requests (timeout, headers, data, stream)."""
    scheme, host, port, host_header = target(url)
    found = addresses(host, port, allow_private)
    headers = {**(kwargs.pop("headers", None) or {}), "Host": host_header}
    kwargs.pop("allow_redirects", None)
    last = None
    for address in found[:MAX_ADDRESSES]:
        with requests.Session() as session:
            session.trust_env = False                   # no proxy: it would resolve the name again
            session.mount(f"{scheme}://", _PinnedAdapter(address, host))
            try:
                return session.request(method, url, headers=headers, allow_redirects=False, **kwargs)
            except requests.ConnectionError as exc:     # this address does not connect: the next one, if any
                last = exc
    raise last
