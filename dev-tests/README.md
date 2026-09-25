# Development tests

All run without Docker or MongoDB and exit with status 1 on any failure. Run them from the
repository root.

| Test | What it exercises | How to run |
|---|---|---|
| `resolver/test_resolver.py` | The **web and data entry code** of this repository (real data-entry authoring + real web server through Flask's test client): hierarchy walk-up, linkType forms, 404 rules, `fwqs`, linkset schema validation, JSON-LD, HTML pages and language choice, the resolver description file built from the environment, plus the upstream `tests/setup_test.py` expectations. | `pip install -r web_server/src/requirements.txt jsonschema`, then `python dev-tests/resolver/test_resolver.py` |
| `portal/test_portal_config.py` | **Portal start-up configuration**: public address from `RESOLVER_PUBLIC_URL` or `FQDN`, Secure cookie default, first user from `PORTAL_ADMIN_*` only while the store is empty. | `pip install -r portal/requirements.txt`, then `python dev-tests/portal/test_portal_config.py` |
| `portal/test_portal_e2e.py` | The **portal** in Chromium against `mock_data_entry.py`: sign-in, check-digit feedback, create with default link and `fwqs`, live language switch, labels (PNG decoded, SVG), user menu, password change, sign-out. | `pip install -r portal/requirements.txt playwright opencv-python-headless && playwright install chromium`, then `python dev-tests/portal/test_portal_e2e.py` |
| `home/test_home.py` | The **home page**: the real `frontend_proxy_server/nginx.conf` in a local nginx against mock upstreams (`/`, `/home/` assets and redirects, and every other path still reaching the resolver, data entry API and portal) and the page in Chromium (menu links, root-relative links, pt-BR/en-GB, resolver root from the address bar, operator from the description file, phone menu, no CSP violations, no-JavaScript fallback). | nginx on the PATH, `pip install playwright && playwright install chromium`, then `python dev-tests/home/test_home.py` (screenshots in a temporary folder, or in `HOME_TEST_SCREENSHOTS`) |

| `install/test_install.sh` | The **installer** in eight scenarios (fresh Let's Encrypt, re-run, hand-written `.env` on an existing installation, own certificate, external proxy, interactive answers with invalid input, refusals, proxy left pointing at recreated services) with stand-ins for apt-get, systemctl, docker, certbot and curl; the written `.env` is checked with the real `docker compose config` and the nginx site with the real `nginx -t`. | Linux, root, nginx, openssl and a Docker Compose v2 binary (`COMPOSE_BIN`, default `/tmp/docker-compose`), then `sudo dev-tests/install/test_install.sh` |

`resolver/linkset-schema.json` is a copy of https://ref.gs1.org/standards/resolver/linkset-schema.

The upstream integration test `tests/setup_test.py` needs the full stack running (`docker compose up -d`)
and reads the API token from `SESSION_TOKEN` (default `secret`, as in `.env.example`).
