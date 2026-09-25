#!/usr/bin/env python3
"""
Development test for the home page served at "/" (release 1.1.0).

Runs the real frontend_proxy_server/nginx.conf in a local nginx (service host names replaced by
mock upstreams, the image path replaced by frontend_proxy_server/home) and checks:
  * routing: "/" and its assets are served by nginx; every other path still reaches the resolver,
    the data entry API and the portal exactly as before;
  * the page in Chromium: menu links, language detection and switching (shared cookie/storage),
    resolver root taken from the address bar, operator name from /.well-known/gs1resolver,
    collapsible menu on a phone-sized screen, no Content Security Policy violations, and the
    English fallback without JavaScript.

Requirements: nginx on the PATH, `pip install playwright && playwright install chromium`.
Run from anywhere:  python dev-tests/home/test_home.py
Exits with status 1 on any failure.
"""
import http.server
import json
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

DESCRIPTION = {"name": "Test resolver", "resolverRoot": "https://id.example.org", "contact": {"fn": "Example Org"}}

results: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mock_upstream(name: str) -> int:
    """An upstream that answers every request with its own name and the path it received."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if name == "resolver" and self.path.startswith("/api/.well-known/gs1resolver"):
                body = json.dumps(DESCRIPTION).encode()
                content_type = "application/json"
            else:
                body = json.dumps({"upstream": name, "path": self.path}).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    port = free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port


def start_nginx(workdir: Path) -> tuple[subprocess.Popen, int]:
    ports = {"web-service:4000": mock_upstream("resolver"),
             "data-entry-service:3000": mock_upstream("data-entry"),
             "portal-service:8000": mock_upstream("portal")}
    listen = free_port()
    conf = NGINX_CONF.read_text()
    conf = re.sub(r"^user\s+\S+;\n", "", conf, flags=re.M)
    conf = conf.replace("/var/log/nginx/error.log", str(workdir / "error.log"))
    conf = conf.replace("/var/log/nginx/access.log", str(workdir / "access.log"))
    conf = conf.replace("/var/run/nginx.pid", str(workdir / "nginx.pid"))
    conf = conf.replace("listen 80;", f"listen 127.0.0.1:{listen};")
    conf = conf.replace(MOUNT_PATH, str(HOME_DIR))
    for host, port in ports.items():
        conf = conf.replace(host, f"127.0.0.1:{port}")
    conf = conf.replace("http {", f"http {{\n    client_body_temp_path {workdir}/body;\n"
                                  f"    proxy_temp_path {workdir}/proxy;\n", 1)
    (workdir / "nginx.conf").write_text(conf)
    subprocess.run(["nginx", "-t", "-q", "-c", str(workdir / "nginx.conf"), "-p", str(workdir)], check=True)
    proc = subprocess.Popen(["nginx", "-c", str(workdir / "nginx.conf"), "-p", str(workdir), "-g", "daemon off;"])
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
        ("/api/docs", "data-entry", "/api/docs"),
        ("/swaggerui/swagger-ui.css", "data-entry", "/swaggerui/swagger-ui.css"),
        ("/portal/", "portal", "/portal/"),
    ]
    for path, upstream, received in expectations:
        status, _, body = fetch(base + path)
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        check(status == 200 and data.get("upstream") == upstream and data.get("path") == received,
              f"GET {path} → {upstream} ({received}), unchanged")

    status, _, body = fetch(base + "/.well-known/gs1resolver")
    check(status == 200 and json.loads(body).get("contact", {}).get("fn") == "Example Org",
          "GET /.well-known/gs1resolver → resolver description file, unchanged")


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
        check(page.locator("#resolver-root-full").inner_text() == f"http://127.0.0.1:{port}",
              "resolver root taken from the address bar")
        check(page.locator("#operator-name").inner_text() == "Example Org", "operator from the description file")
        check(page.locator("#nav-toggle").is_hidden() and page.locator("#site-nav").is_visible(),
              "desktop: menu visible, no menu button")
        check(page.locator("a.ext").count() == 6 and
              page.locator("a.ext .visually-hidden").first.inner_text() == "(site externo)",
              "external links are marked (icon and accessible text)")
        page.screenshot(path=str(shots / "home-desktop-pt.png"), full_page=True)

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
        check(page.locator("#resolver-root").inner_text() == f"http://localhost:{port}",
              "another host name → the page shows that host (domain independent)")
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
    if not shutil.which("nginx"):
        print("nginx not found on the PATH")
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="home-test-"))
    shots = Path(os.environ.get("HOME_TEST_SCREENSHOTS", workdir / "screenshots"))
    shots.mkdir(parents=True, exist_ok=True)
    proc, port = start_nginx(workdir)
    try:
        base = f"http://127.0.0.1:{port}"
        routing_checks(base)
        browser_checks(base, port, shots)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; screenshots in {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
