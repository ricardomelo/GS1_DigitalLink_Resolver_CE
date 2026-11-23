"""
Requests to addresses the portal's users choose (portal/outbound.py, Documentation/adr/0029-outbound-requests.md):
which addresses count as global (IPv4 inside IPv6 included); a name resolved once, every address checked; the
connection made to the address checked, never to the name resolved again (DNS rebinding), with the name kept in the
Host header, in TLS (SNI) and in the certificate's check; the next address tried when one does not connect; no
redirect followed; no proxy from the environment; addresses refused before any request (scheme, user information,
port). Single sign-on's requests and the check of a QR code domain go through it. A local HTTP and HTTPS server, a
stand-in name resolver and a recorder of the addresses dialled; no Internet needed.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_outbound.py
"""
import http.server
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal")))
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ["PORTAL_DB_NAME"] = f"devtest_outbound_{os.getpid()}"
os.environ["PORTAL_SSO_ALLOW_INSECURE"] = ""

import requests  # noqa: E402
import urllib3.util.connection as u3c  # noqa: E402

import domains  # noqa: E402
import outbound  # noqa: E402
import sso  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


# ------------------------------------------------------------------ servers
SEEN = []          # (path, Host header, SNI name) of every request answered


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Host"), getattr(self.connection, "sni", None)))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_GET

    def log_message(self, *args):
        pass


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


PLAIN = serve(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler))

WORK = tempfile.mkdtemp()


def certificate(name):
    key, crt = os.path.join(WORK, name + ".key"), os.path.join(WORK, name + ".crt")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", f"/CN={name}",
                    "-addext", f"subjectAltName=DNS:{name}", "-keyout", key, "-out", crt],
                   check=True, capture_output=True)
    return key, crt


class TlsServer(http.server.ThreadingHTTPServer):
    """HTTPS with the certificate of one name; records the name each client sent in TLS (SNI)."""

    def __init__(self, name):
        super().__init__(("127.0.0.1", 0), Handler)
        key, self.crt = certificate(name)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(self.crt, key)
        self.context.sni_callback = lambda sock, server_name, ctx: setattr(sock, "sni_name", server_name)

    def handle_error(self, request, client_address):
        pass                                              # a client that refuses the certificate resets the connection

    def get_request(self):
        sock, address = super().get_request()
        wrapped = self.context.wrap_socket(sock, server_side=True)
        wrapped.sni = getattr(wrapped, "sni_name", None)
        return wrapped, address


TLS = TlsServer("pinned.test")
TLS_PORT = serve(TLS)

# ------------------------------------------------------------------ a stand-in resolver and dialler
real_getaddrinfo, real_connect = socket.getaddrinfo, u3c.create_connection
NAMES = {}         # name → list of answers, one per resolution (the last one repeats)
ASKED = {}         # name → number of resolutions
DIALLED = []
REFUSE = {"93.184.216.34", "127.0.0.3"}   # dialled addresses refused at once (no network here; a dead address)


def fake_getaddrinfo(host, port=None, *args, **kwargs):
    if host in NAMES:
        ASKED[host] = ASKED.get(host, 0) + 1
        answers = NAMES[host]
        found = answers[min(ASKED[host], len(answers)) - 1]
        if not found:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a, port or 0) if ":" not in a else (a, port or 0, 0, 0)) for a in found]
    return real_getaddrinfo(host, port, *args, **kwargs)


def fake_connect(address, *args, **kwargs):
    DIALLED.append(address[0])
    if address[0] in REFUSE:
        raise ConnectionRefusedError("refused by the test")
    return real_connect(address, *args, **kwargs)


socket.getaddrinfo, u3c.create_connection = fake_getaddrinfo, fake_connect


def attempt(*args, **kwargs):
    """outbound.request(), or the name of the exception it raised (a failed check prints FAIL, never stops the test)."""
    try:
        return outbound.request(*args, **kwargs)
    except Exception as exc:                            # noqa: BLE001
        return type(exc).__name__


def status_of(answer):
    return answer if isinstance(answer, str) else answer.status_code


def reset():
    SEEN.clear()
    DIALLED.clear()
    ASKED.clear()


# ------------------------------------------------------------------ which addresses are global
for address in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
                "192.0.2.1", "::1", "::", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
                "64:ff9b::a00:1", "64:ff9b::7f00:1", "2002:a00:1::1", "2002:7f00:1::1", "fe80::1%eth0", "not-an-ip"):
    check(f"not global: {address}", not outbound.is_global(address))
for address in ("93.184.216.34", "8.8.8.8", "2001:4860:4860::8888", "::ffff:8.8.8.8", "64:ff9b::808:808"):
    check(f"global: {address}", outbound.is_global(address))

# ------------------------------------------------------------------ resolved once, every address checked
NAMES.update({"public.test": [["93.184.216.34", "2001:4860:4860::8888"]], "mixed.test": [["93.184.216.34", "10.0.0.5"]],
              "none.test": [[]], "inner.test": [["::ffff:192.168.0.1"]]})
check("addresses(): every address of a public name, in order",
      outbound.addresses("public.test") == ["93.184.216.34", "2001:4860:4860::8888"])
for name, error in (("mixed.test", outbound.PrivateAddress), ("inner.test", outbound.PrivateAddress),
                    ("none.test", outbound.Unresolvable)):
    try:
        outbound.addresses(name)
        raised = None
    except outbound.OutboundError as exc:
        raised = type(exc)
    check(f"addresses(): {name} → {error.__name__}", raised is error, raised)
check("public_host(): True, False, None", (outbound.public_host("public.test"), outbound.public_host("mixed.test"),
                                          outbound.public_host("none.test")) == (True, False, None))
check("addresses(allow_private=True): a private name accepted (development tests only)",
      outbound.addresses("mixed.test", allow_private=True) == ["93.184.216.34", "10.0.0.5"])

# ------------------------------------------------------------------ refused before any request
reset()
for url in ("ftp://public.test/", "https://user:pw@public.test/", "https://user@public.test/", "https:///path",
            "https://public.test:99999/", "javascript:alert(1)", "public.test/x"):
    raised = status_of(attempt("GET", url, timeout=2))
    check(f"refused before any request: {url}", raised == "BadAddress", raised)
check("nothing resolved or dialled for those addresses", not ASKED and not DIALLED, (ASKED, DIALLED))

# ------------------------------------------------------------------ DNS rebinding
NAMES["rebind.test"] = [["93.184.216.34"], ["127.0.0.1"]]
reset()
raised = status_of(attempt("GET", f"http://rebind.test:{PLAIN}/ok", timeout=2))
check("rebinding: the request is made to the address checked (refused here), not to the name's next answer",
      raised == "ConnectionError" and DIALLED == ["93.184.216.34"] and not SEEN and ASKED["rebind.test"] == 1,
      (raised, DIALLED, SEEN, ASKED))
NAMES["rebind2.test"] = [["127.0.0.1"], ["10.9.9.9"]]
reset()
raised = status_of(attempt("GET", f"http://rebind2.test:{PLAIN}/ok", timeout=2))
check("a private first answer is refused without a connection", raised == "PrivateAddress" and not DIALLED, DIALLED)

# ------------------------------------------------------------------ the checked address, the name kept
NAMES["pinned.test"] = [["127.0.0.1"], ["10.255.255.1"]]       # a second resolution would lead nowhere
reset()
answer = attempt("GET", f"http://pinned.test:{PLAIN}/ok", allow_private=True, timeout=3)
check("plain HTTP: connected to the address resolved once; the Host header is the name with its port",
      status_of(answer) == 200 and DIALLED == ["127.0.0.1"] and SEEN == [("/ok", f"pinned.test:{PLAIN}", None)]
      and ASKED["pinned.test"] == 1, (status_of(answer), DIALLED, SEEN, ASKED))
reset()
answer = attempt("GET", f"https://pinned.test:{TLS_PORT}/ok", allow_private=True, timeout=3, verify=TLS.crt)
check("HTTPS: connected to the address checked; SNI and Host are the name; the certificate verified for the name",
      status_of(answer) == 200 and DIALLED == ["127.0.0.1"]
      and SEEN == [("/ok", f"pinned.test:{TLS_PORT}", "pinned.test")], (status_of(answer), DIALLED, SEEN))
NAMES["other.test"] = [["127.0.0.1"]]
reset()
raised = status_of(attempt("GET", f"https://other.test:{TLS_PORT}/ok", allow_private=True, timeout=3, verify=TLS.crt))
check("HTTPS: a certificate for another name is refused (checked against the name, not the address)",
      raised == "SSLError" and not SEEN, (raised, SEEN))
reset()
answer = attempt("GET", f"http://pinned.test:{PLAIN}/redirect", allow_private=True, timeout=3)
check("a redirect is returned, never followed", status_of(answer) == 302 and answer.headers["Location"] == "/ok"
      and [s[0] for s in SEEN] == ["/redirect"], (status_of(answer), SEEN))
reset()
answer = attempt("POST", f"http://pinned.test:{PLAIN}/token", allow_private=True, timeout=3,
                 data={"a": "b"}, headers={"Host": "evil.test", "Accept": "application/json"})
check("POST works; a Host header given by the caller is replaced by the name's",
      status_of(answer) == 200 and SEEN == [("/token", f"pinned.test:{PLAIN}", None)], SEEN)

# ------------------------------------------------------------------ the next address when one does not connect
NAMES["two.test"] = [["127.0.0.3", "127.0.0.1"]]
reset()
answer = attempt("GET", f"http://two.test:{PLAIN}/ok", allow_private=True, timeout=3)
check("an address that does not connect: the next checked one is tried", status_of(answer) == 200
      and DIALLED == ["127.0.0.3", "127.0.0.1"], (status_of(answer), DIALLED))
NAMES["many.test"] = [["127.0.0.3", "127.0.0.4", "127.0.0.5", "127.0.0.1"]]
REFUSE.update({"127.0.0.4", "127.0.0.5"})
reset()
raised = status_of(attempt("GET", f"http://many.test:{PLAIN}/ok", allow_private=True, timeout=3))
check(f"at most {outbound.MAX_ADDRESSES} addresses tried", outbound.MAX_ADDRESSES == 3 and raised == "ConnectionError"
      and DIALLED == ["127.0.0.3", "127.0.0.4", "127.0.0.5"], (raised, DIALLED))

# ------------------------------------------------------------------ no proxy from the environment
saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")}
os.environ.update(HTTP_PROXY="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9", NO_PROXY="", no_proxy="")
reset()
try:
    status = status_of(attempt("GET", f"http://pinned.test:{PLAIN}/ok", allow_private=True, timeout=3))
finally:
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
check("a proxy in the environment is not used (it would resolve the name itself)", status == 200 and SEEN, status)

# ------------------------------------------------------------------ single sign-on and the domain check use it
NAMES["idp.test"] = [["93.184.216.34"], ["93.184.216.34"], ["127.0.0.1"]]   # check_url(), the request, then the attack
NAMES["idp-private.test"] = [["10.0.0.7"]]
reset()
try:
    sso._get_json(f"https://idp.test:{TLS_PORT}/.well-known/openid-configuration")
    code = None
except sso.SsoError as exc:
    code = exc.code
except requests.RequestException as exc:
    code = type(exc).__name__
check("SSO discovery: connected to the address checked (rebinding name: refused here, the local server not reached)",
      code == "ConnectionError" and DIALLED == ["93.184.216.34"] and not SEEN, (code, DIALLED, SEEN))
reset()
try:
    sso._send("POST", f"https://idp-private.test:{TLS_PORT}/token", data={})
    code = None
except sso.SsoError as exc:
    code = exc.code
check("SSO token request to a private address: sso.issuerPrivate, nothing dialled",
      code == "sso.issuerPrivate" and not DIALLED, (code, DIALLED))
NAMES["idp-gone.test"] = [[]]
try:
    sso._get_json("https://idp-gone.test/.well-known/openid-configuration")
    code = None
except requests.ConnectionError:
    code = "ConnectionError"
except sso.SsoError as exc:
    code = exc.code
check("SSO: a provider name without an address is a connection failure", code == "ConnectionError", code)
NAMES["dom.test"] = [["93.184.216.34"], ["127.0.0.1"]]
reset()
try:
    domains.probe(f"https://dom.test:{TLS_PORT}/.well-known/gs1resolver")
    code = None
except requests.ConnectionError:
    code = "ConnectionError"
check("domain check: connected to the address checked (rebinding name), the local server not reached",
      code == "ConnectionError" and DIALLED == ["93.184.216.34"] and not SEEN, (code, DIALLED, SEEN))
try:
    domains.probe(f"https://idp-private.test:{TLS_PORT}/")
    code = None
except PermissionError:
    code = "PermissionError"
check("domain check: a private address raises PermissionError (domains.checkPrivate)", code == "PermissionError", code)
try:
    domains.probe("https://idp-gone.test/")
    code = None
except requests.ConnectionError:
    code = "ConnectionError"
check("domain check: a name without an address is unreachable (domains.checkUnreachable)",
      code == "ConnectionError", code)

socket.getaddrinfo, u3c.create_connection = real_getaddrinfo, real_connect
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
