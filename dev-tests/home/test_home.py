#!/usr/bin/env python3
"""
Development test for the home page served at "/" (release 1.1.0).

Runs the real frontend_proxy_server/nginx.conf in a local nginx (Docker's DNS replaced by a small DNS
server of the test that answers the service names with mock upstreams on 127.0.0.x, the image path
replaced by frontend_proxy_server/home) and checks:
  * routing: "/" and its assets are served by nginx; every other path still reaches the resolver,
    the data entry API and the portal exactly as before;
  * replicas (item 2.3, step 4): nginx starts while a service is missing and finds it later, shares
    the requests among every address a service name has, follows replicas added and removed without a
    restart, and skips a replica that has gone away;
  * the page in Chromium: menu links, language detection and switching (shared cookie/storage),
    resolver root taken from the address bar, operator name from /.well-known/gs1resolver,
    collapsible menu on a phone-sized screen, no Content Security Policy violations, and the
    English fallback without JavaScript.

Requirements: nginx 1.27.3 or later ("resolve" in upstream blocks; the proxy image runs 1.30) on the
PATH or in NGINX_BIN, `pip install playwright && playwright install chromium`.
Run from anywhere:  python dev-tests/home/test_home.py
Exits with status 1 on any failure.
"""
import http.server
import json
import struct
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PACKAGE = Path(__file__).resolve().parents[2]
NGINX_CONF = PACKAGE / "frontend_proxy_server" / "nginx.conf"
HOME_DIR = PACKAGE / "frontend_proxy_server" / "home"
MOUNT_PATH = "/usr/share/nginx/home"   # where the proxy image keeps the files

NGINX = os.environ.get("NGINX_BIN", "nginx")
RESOLVE_SINCE = (1, 27, 3)          # first open-source nginx with "resolve" in upstream blocks
PORTS = {"web-service": 4000, "data-entry-service": 3000, "portal-service": 8000}   # as in nginx.conf
UPSTREAM_NAMES = {"web-service": "resolver", "data-entry-service": "data-entry", "portal-service": "portal"}

DESCRIPTION = {"name": "Test resolver", "resolverRoot": "https://id.example.org",
               "contact": {"fn": "Example Org", "hasURL": "https://www.example.org/"}}

results: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label)


def host_accepted(host: str | None) -> bool:
    """Whether Werkzeug (the web servers behind the proxy) accepts this Host header."""
    if not host:
        return False
    try:
        from werkzeug.sansio.utils import get_host
    except ImportError:                                   # same rule: hostname characters and an optional port
        return re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", host) is not None
    try:
        get_host("http", host)
        return True
    except Exception:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StubDNS:
    """A DNS server for nginx's "resolver": A records for the service names, changed while nginx runs,
    as Docker's DNS changes when Compose adds or removes replicas. Other names: NXDOMAIN."""

    def __init__(self) -> None:
        self.records: dict[str, list[str]] = {}
        self.queries = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                data, peer = self.sock.recvfrom(512)
                self.sock.sendto(self.answer(data), peer)
            except OSError:
                return

    def answer(self, query: bytes) -> bytes:
        qid, _flags = struct.unpack("!HH", query[:4])
        labels, i = [], 12
        while query[i]:
            labels.append(query[i + 1:i + 1 + query[i]].decode("ascii", "replace"))
            i += 1 + query[i]
        question = query[12:i + 5]                       # name, type, class
        qtype = struct.unpack("!H", query[i + 1:i + 3])[0]
        name = ".".join(labels).lower()
        self.queries += 1
        addresses = list(self.records.get(name, [])) if qtype == 1 else []
        rcode = 0 if name in self.records else 3
        header = struct.pack("!HHHHHH", qid, 0x8180 | rcode, 1, len(addresses), 0, 0)
        answers = b"".join(struct.pack("!HHHIH", 0xC00C, 1, 1, 5, 4) + socket.inet_aton(a) for a in addresses)
        return header + question + answers


class Replica:
    """One replica of a service: an HTTP server on its own loopback address (127.0.0.x) and the service's
    port, answering every request with the service's name, its own address and the path it received."""

    def __init__(self, name: str, address: str, port: int) -> None:
        self.address = address

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if name == "resolver" and self.path.startswith("/api/.well-known/gs1resolver"):
                    body = json.dumps(DESCRIPTION).encode()
                else:
                    body = json.dumps({"upstream": name, "replica": address, "path": self.path,
                                       "host": self.headers.get("Host")}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer((address, port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def nginx_version() -> tuple[int, ...]:
    run = subprocess.run([NGINX, "-v"], capture_output=True, text=True)
    found = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", run.stderr + run.stdout)
    return tuple(int(x) for x in found.groups()) if found else ()


def free_port_on(addresses: list[str]) -> int:
    """A port that is free on every one of these loopback addresses."""
    for _ in range(50):
        port = free_port()
        try:
            for address in addresses:
                with socket.socket() as s:
                    s.bind((address, port))
            return port
        except OSError:
            continue
    raise RuntimeError("no common free port")


def start_nginx(workdir: Path, dns: StubDNS, ports: dict[str, int]) -> tuple[subprocess.Popen, int]:
    """nginx with the real configuration; the service names keep their names (the stub DNS answers them)
    and get free ports; Docker's DNS becomes the stub, asked again after one second instead of ten."""
    listen = free_port()
    (workdir / "logs").mkdir(exist_ok=True)           # nginx's built-in error log, before it reads the file
    conf = NGINX_CONF.read_text()
    conf = re.sub(r"^user\s+\S+;\n", "", conf, flags=re.M)
    conf = conf.replace("/var/log/nginx/error.log", str(workdir / "error.log"))
    conf = conf.replace("/var/log/nginx/access.log", str(workdir / "access.log"))
    conf = conf.replace("/var/run/nginx.pid", str(workdir / "nginx.pid"))
    conf = conf.replace("listen 80;", f"listen 127.0.0.1:{listen};")
    conf = conf.replace(MOUNT_PATH, str(HOME_DIR))
    for service, port in ports.items():
        conf = conf.replace(f"{service}:{PORTS[service]}", f"{service}:{port}")
    conf = conf.replace("resolver 127.0.0.11 valid=10s", f"resolver 127.0.0.1:{dns.port} valid=1s")
    # Every temporary folder in the work folder: a build's defaults (/var/lib/nginx on Ubuntu,
    # /var/cache/nginx in nginx.org's packages) cannot be created by a user who is not root.
    temp = "".join(f"    {kind}_temp_path {workdir}/{kind};\n"
                   for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    conf = conf.replace("http {", "http {\n" + temp, 1)
    (workdir / "nginx.conf").write_text(conf)
    test = subprocess.run([NGINX, "-t", "-q", "-c", str(workdir / "nginx.conf"), "-p", str(workdir)],
                          capture_output=True, text=True)
    if test.returncode:
        message = " / ".join(line for line in test.stderr.splitlines() if "[alert]" not in line)
        check(False, f"nginx accepts the configuration ({message})")
        raise SystemExit(1)
    proc = subprocess.Popen([NGINX, "-c", str(workdir / "nginx.conf"), "-p", str(workdir), "-g", "daemon off;"])
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", listen), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc, listen


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url: str, accept: str = "*/*"):
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"Accept": accept})
    try:
        with opener.open(request) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8", "replace")


def routing_checks(base: str) -> None:
    status, headers, body = fetch(base + "/")
    check(status == 200 and "text/html" in headers.get("Content-Type", ""), "GET / → 200 text/html")
    check('id="site-nav"' in body, "GET / serves the home page, not the resolver")
    csp = headers.get("Content-Security-Policy", "")
    check("default-src 'self'" in csp and "frame-ancestors 'none'" in csp, "GET / carries the Content Security Policy")
    check(headers.get("X-Content-Type-Options") == "nosniff", "GET / carries X-Content-Type-Options")

    status, _, body = fetch(base + "/?utm_source=test")
    check(status == 200 and 'id="site-nav"' in body, "GET /?query → home page")

    status, _, body = fetch(base + "/", accept="application/json")
    check(status == 200 and 'id="site-nav"' in body, "GET / with Accept: application/json → home page (no resolver content at /)")

    for asset, kind in [("home.css", "text/css"), ("home.js", "javascript"), ("gs1-logo.png", "image/png"), ("favicon.png", "image/png")]:
        status, headers, _ = fetch(base + "/home/" + asset)
        check(status == 200 and kind in headers.get("Content-Type", ""), f"GET /home/{asset} → 200 {kind}")

    for path in ["/home", "/home/"]:
        status, headers, _ = fetch(base + path)
        check(status == 301 and headers.get("Location", "").endswith("/"), f"GET {path} → 301 to /")

    status, _, _ = fetch(base + "/home/does-not-exist.txt")
    check(status == 404, "GET /home/<unknown> → 404 (no directory listing, no fall-through)")

    expectations = [
        ("/01/09506000134352", "resolver", "/api/01/09506000134352"),
        ("/01/09506000134352/10/ABC123?linkType=gs1:pip", "resolver", "/api/01/09506000134352/10/ABC123?linkType=gs1:pip"),
        ("/homepage", "resolver", "/api/homepage"),
        # a value with "/" (%2F) and the ';' delimiter reach the resolver exactly as sent (URI Syntax 4.2, 4.11)
        ("/01/09506000134352/10/A%2FB?17=261231;3103=000189", "resolver", "/api/01/09506000134352/10/A%2FB?17=261231;3103=000189"),
        ("/api/docs", "data-entry", "/api/docs"),
        ("/swaggerui/swagger-ui.css", "data-entry", "/swaggerui/swagger-ui.css"),
        ("/portal/", "portal", "/portal/"),
        # an EPC binary string (item 1.6) is a single segment for the resolver
        ("/eh30164596f40c0e5cbe991a83", "resolver", "/api/eh30164596f40c0e5cbe991a83"),
    ]
    for path, upstream, received in expectations:
        status, _, body = fetch(base + path)
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        check(status == 200 and data.get("upstream") == upstream and data.get("path") == received,
              f"GET {path} → {upstream} ({received}), unchanged")
        # The Host header nginx sends must be one the upstream's Werkzeug accepts: with "proxy_pass
        # http://resolver_web/…" and no Host header, nginx sent "resolver_web", which Werkzeug 3.1 refuses
        # (an underscore is not a hostname character), so every resolution through the proxy was a 500.
        check(host_accepted(data.get("host")), f"GET {path}: Host header {data.get('host')!r} accepted by Werkzeug")

    status, _, body = fetch(base + "/.well-known/gs1resolver")
    check(status == 200 and json.loads(body).get("contact", {}).get("fn") == "Example Org",
          "GET /.well-known/gs1resolver → resolver description file, unchanged")


class Cluster:
    """The replicas behind the proxy and the stub DNS that names them."""

    def __init__(self, dns: StubDNS, ports: dict[str, int]) -> None:
        self.dns, self.ports, self.replicas = dns, ports, {}

    def add(self, service: str, address: str) -> None:
        self.replicas[(service, address)] = Replica(UPSTREAM_NAMES[service], address, self.ports[service])
        self.dns.records[service] = self.dns.records.get(service, []) + [address]

    def forget(self, service: str, address: str) -> None:
        """Takes the address out of the DNS answer (Compose removed the container's name)."""
        self.dns.records[service] = [a for a in self.dns.records[service] if a != address]

    def stop(self, service: str, address: str) -> None:
        self.replicas.pop((service, address)).stop()


def replicas_seen(base: str, path: str, count: int) -> tuple[list[str], list[int]]:
    """The replica that answered each of `count` requests, and the statuses of those that failed."""
    seen, errors = [], []
    for _ in range(count):
        status, _, body = fetch(base + path)
        if status != 200:
            errors.append(status)
            continue
        seen.append(json.loads(body).get("replica"))
    return seen, errors


def wait_for(predicate, seconds: float = 8.0) -> float | None:
    """Seconds until predicate() held, or None."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if predicate():
            return time.monotonic() - started
        time.sleep(0.2)
    return None


def startup_checks(base: str, cluster: Cluster) -> None:
    """nginx was started while portal-service had no address (a service still starting, or stopped)."""
    status, _, body = fetch(base + "/")
    check(status == 200 and 'id="site-nav"' in body, "nginx starts while a service name has no address yet")
    status, _, _ = fetch(base + "/portal/")
    check(status in (502, 503), f"…and answers that service's paths with an error meanwhile ({status})")
    # nginx asks the DNS in the background as it starts: the other services answer within moments.
    took = wait_for(lambda: fetch(base + "/01/09506000134352")[0] == 200, 3)
    check(took is not None, "…while the other services answer")
    cluster.add("portal-service", "127.0.0.4")
    took = wait_for(lambda: fetch(base + "/portal/")[0] == 200)
    check(took is not None, "the service is found once its name has an address, without restarting nginx"
          + (f" ({took:.1f} s)" if took is not None else ""))


def replica_checks(base: str, cluster: Cluster) -> None:
    resolve = "/01/09506000134352"
    seen, errors = replicas_seen(base, resolve, 6)
    check(not errors and set(seen) == {"127.0.0.2"}, "one replica of web-service: every request reaches it")

    cluster.add("web-service", "127.0.0.5")
    took = wait_for(lambda: "127.0.0.5" in replicas_seen(base, resolve, 4)[0])
    check(took is not None, "a second replica of web-service is found without restarting nginx")
    seen, errors = replicas_seen(base, resolve, 20)
    check(not errors and seen.count("127.0.0.2") >= 8 and seen.count("127.0.0.5") >= 8,
          f"two replicas share the requests ({seen.count('127.0.0.2')} / {seen.count('127.0.0.5')} of 20)")

    cluster.add("web-service", "127.0.0.6")
    took = wait_for(lambda: "127.0.0.6" in replicas_seen(base, resolve, 6)[0])
    check(took is not None, "a third replica is added the same way (scale up)")

    # Scale down: the containers stop before nginx has asked the DNS again; the requests that meet a
    # stopped replica go on to another one (proxy_next_upstream), so none of them fails.
    cluster.stop("web-service", "127.0.0.5")
    cluster.stop("web-service", "127.0.0.6")
    seen, errors = replicas_seen(base, resolve, 20)
    check(not errors and set(seen) == {"127.0.0.2"},
          "replicas stopped before the DNS changes: requests go to the remaining one, none fails"
          + (f" (errors {errors})" if errors else ""))
    cluster.forget("web-service", "127.0.0.5")
    cluster.forget("web-service", "127.0.0.6")
    time.sleep(2.5)                                       # longer than "valid" in the test configuration
    seen, errors = replicas_seen(base, resolve, 10)
    check(not errors and set(seen) == {"127.0.0.2"}, "after the DNS changes, the remaining replica answers alone")

    for service, first, second, path in (("portal-service", "127.0.0.4", "127.0.0.7", "/portal/"),
                                         ("data-entry-service", "127.0.0.3", "127.0.0.8", "/api/docs")):
        cluster.add(service, second)
        took = wait_for(lambda: second in replicas_seen(base, path, 4)[0])
        seen, errors = replicas_seen(base, path, 10)
        check(took is not None and not errors and set(seen) == {first, second},
              f"two replicas of {service} share {path}")
    check(cluster.dns.queries > 0, "nginx asked the DNS for the service names")


def browser_checks(base: str, port: int, shots: Path) -> None:
    expected_links = {
        "/portal/", "/api/docs",
        "https://ref.gs1.org/standards/digital-link/",
        "https://www.gs1.org/",
        "https://github.com/gs1/GS1_DigitalLink_Resolver_CE",
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Portuguese system, desktop
        context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900})
        page = context.new_page()
        csp_errors = []
        page.on("console", lambda m: csp_errors.append(m.text) if "Content Security Policy" in m.text else None)
        # Google Fonts are not reachable from the test machine: answer them empty instead of waiting.
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                   lambda route: route.fulfill(status=200, body="", content_type="text/css"))
        page.goto(base + "/")
        page.wait_for_function("document.querySelector('#operator') && !document.querySelector('#operator').hidden")

        hrefs = page.eval_on_selector_all("#site-nav a", "els => els.map(a => a.getAttribute('href'))")
        check(set(hrefs) == expected_links and len(hrefs) == 5, "menu has exactly the five requested links")
        internal = [h for h in hrefs if not h.startswith("https://")]
        check(all(h.startswith("/") and "//" not in h for h in internal),
              "links to this installation are root-relative (no domain in the page)")
        check(page.locator("html").get_attribute("lang") == "pt-BR", "Portuguese system → pt-BR")
        check(page.locator("h1").inner_text() == "Resolver GS1 Digital Link", "hero title in Portuguese")
        check(page.locator("#site-nav a[href='/portal/']").inner_text() == "Cadastro de links", "menu text in Portuguese")
        check(page.locator(".syntax, #resolver-root").count() == 0 and page.locator("main aside").count() == 0,
              "no GS1 Digital Link syntax box on the home page")
        check("não pela GS1 nem por qualquer Organização-Membro GS1" in page.locator("#notice").inner_text()
              and "responsável pelo seu uso" in page.locator("#notice").inner_text(),
              "footer notice in Portuguese: community software, operator responsible")
        operator_link = page.locator("#operator-name a")
        check(operator_link.count() == 1 and operator_link.get_attribute("href") == "https://www.example.org/"
              and operator_link.evaluate("a => a.firstChild.textContent") == "Example Org"
              and operator_link.locator(".visually-hidden").inner_text() == "(site externo)",
              "operator from the description file, linked to contact.hasURL as an external link")
        check(page.locator("#nav-toggle").is_hidden() and page.locator("#site-nav").is_visible(),
              "desktop: menu visible, no menu button")
        check(page.locator("a.ext").count() == 7 and
              page.locator("a.ext .visually-hidden").first.inner_text() == "(site externo)",
              "external links are marked (icon and accessible text)")
        page.screenshot(path=str(shots / "home-desktop-pt.png"), full_page=True)

        # Without hasURL, or with an address that is not a web address, the name is plain text
        for url, label in ((None, "no hasURL"), ("javascript:alert(1)", "javascript: address"),
                           ("ftp://example.org/", "ftp address")):
            if url is None:
                DESCRIPTION["contact"].pop("hasURL", None)
            else:
                DESCRIPTION["contact"]["hasURL"] = url
            page.goto(base + "/")
            page.locator("#operator").wait_for(state="visible")    # no wait_for_function: the page's CSP forbids eval
            check(page.locator("#operator-name a").count() == 0 and page.locator("#operator-name").inner_text() == "Example Org",
                  f"operator as plain text ({label})")
        DESCRIPTION["contact"]["hasURL"] = "https://www.example.org/"

        page.select_option("#locale", "en-GB")
        check(page.locator("h1").inner_text() == "GS1 Digital Link resolver", "language menu switches to English live")
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        stored = page.evaluate("localStorage.getItem('gs1resolver.portal.locale')")
        check(cookies.get("gs1resolver_lang") == "en-GB" and stored == "en-GB",
              "choice written to the shared cookie and the portal's storage key")
        check(page.title() == "GS1 Resolver Community Edition", "page title")
        page.screenshot(path=str(shots / "home-desktop-en.png"), full_page=True)

        page.locator(".card-main h3 a").click()
        page.wait_for_load_state()
        check(page.url == base + "/portal/", "portal card opens /portal/ on the same host")
        check(not csp_errors, "no Content Security Policy violations" + (f": {csp_errors}" if csp_errors else ""))
        context.close()

        # Same page reached through another host name: the root follows the address bar
        context = browser.new_context(locale="en-GB")
        page = context.new_page()
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                   lambda route: route.fulfill(status=200, body="", content_type="text/css"))
        page.goto(f"http://localhost:{port}/")
        check("not by GS1 or any GS1 Member Organisation" in page.locator("#notice").inner_text()
              and page.locator("h1").inner_text() == "GS1 Digital Link resolver",
              "another host name → same page, footer notice in English")
        context.close()

        # English system but Portuguese chosen earlier on the resolver pages (cookie only)
        context = browser.new_context(locale="en-GB")
        context.add_cookies([{"name": "gs1resolver_lang", "value": "pt-BR", "url": base + "/"}])
        page = context.new_page()
        page.goto(base + "/")
        check(page.locator("html").get_attribute("lang") == "pt-BR", "gs1resolver_lang cookie honoured")
        context.close()

        # Phone
        context = browser.new_context(locale="pt-BR", viewport={"width": 390, "height": 844},
                                      device_scale_factor=2, is_mobile=True, has_touch=True)
        page = context.new_page()
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                   lambda route: route.fulfill(status=200, body="", content_type="text/css"))
        page.goto(base + "/")
        toggle = page.locator("#nav-toggle")
        check(toggle.is_visible() and page.locator("#site-nav").is_hidden(), "phone: menu collapsed behind the button")
        page.screenshot(path=str(shots / "home-phone.png"), full_page=True)
        toggle.click()
        check(page.locator("#site-nav").is_visible() and toggle.get_attribute("aria-expanded") == "true",
              "phone: button opens the menu")
        page.screenshot(path=str(shots / "home-phone-menu.png"))
        page.keyboard.press("Escape")
        check(page.locator("#site-nav").is_hidden() and toggle.get_attribute("aria-expanded") == "false",
              "phone: Escape closes the menu")
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        check(scroll_width <= 390, "phone: no horizontal scrolling")
        context.close()

        # Without JavaScript: English fallback, menu visible, links still work
        context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.goto(base + "/")
        check(page.locator("h1").inner_text() == "GS1 Digital Link resolver" and
              page.locator("#site-nav").is_visible() and page.locator("#nav-toggle").is_hidden(),
              "without JavaScript: English text, menu visible")
        context.close()

        browser.close()


def main() -> int:
    if not shutil.which(NGINX):
        print(f"FAIL nginx not found ({NGINX})")
        return 1
    version = nginx_version()
    if version < RESOLVE_SINCE:
        print(f"FAIL nginx {'.'.join(map(str, version)) or '?'} is too old: \"resolve\" in upstream blocks needs "
              f"{'.'.join(map(str, RESOLVE_SINCE))} or later (set NGINX_BIN or install nginx from nginx.org)")
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="home-test-"))
    shots = Path(os.environ.get("HOME_TEST_SCREENSHOTS", workdir / "screenshots"))
    shots.mkdir(parents=True, exist_ok=True)
    dns = StubDNS()
    ports = {service: free_port_on([f"127.0.0.{n}" for n in range(2, 10)]) for service in PORTS}
    cluster = Cluster(dns, ports)
    cluster.add("web-service", "127.0.0.2")
    cluster.add("data-entry-service", "127.0.0.3")
    proc, port = start_nginx(workdir, dns, ports)          # portal-service has no address yet
    try:
        base = f"http://127.0.0.1:{port}"
        startup_checks(base, cluster)
        routing_checks(base)
        replica_checks(base, cluster)
        browser_checks(base, port, shots)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; screenshots in {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
