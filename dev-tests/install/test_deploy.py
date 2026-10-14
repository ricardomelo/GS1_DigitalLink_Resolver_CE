#!/usr/bin/env python3
"""
Development test for the deployment of several replicas (item 2.3, step 4 of ADR 0001).

Checks, without Docker:
  * docker-compose.yml through "docker compose config": the four stateless services (web-service,
    data-entry-service, portal-service, portal-worker) have no fixed container_name and take their number
    of replicas (*_REPLICAS) and of server processes (*_PROCESSES → WEB_CONCURRENCY) from .env, with the
    defaults 1 and 2; the database and the proxy stay single and keep their names; a bad value is refused;
  * the proxy: an nginx image that supports "resolve" in upstream blocks, and every proxy_pass of
    nginx.conf going to an upstream whose servers are looked up again in Docker's DNS;
  * the servers: each Dockerfile's CMD (gunicorn) started here as the image would start it, with the bind
    address changed to a free local port: it runs WEB_CONCURRENCY processes, answers, logs the request,
    and stops cleanly on SIGTERM within Docker's stop period;
  * the portal's fallback session key (secret.key, when PORTAL_SECRET_KEY is not set): processes starting
    at the same moment all end up with the same, complete key;
  * one GS1 Barcode Syntax Engine release (ADR 0003): written once in docker-compose.yml, given to every image
    that checks GS1 data as a build argument, used by their Dockerfiles, the portal's build script and the
    CI set-up action without a release of their own, and the one portal/gs1_dictionary.json was made from;
  * the daily backup (scripts/resolver-backup.sh) with a stand-in "docker": mongodump is given only options
    mongodump has (--nsExclude is mongorestore's: the backup failed on a server with it), a failed dump says
    ERROR, exits with status 1 and leaves no partial file, a good one writes the archive and says OK;
  * the portal image's files: the portal server is started from a folder assembled by the COPY instructions
    of portal/Dockerfile (not from the source folder), and every module and data file of portal/ is in it,
    so a file left out of the image fails here rather than on a server.

Requirements: COMPOSE_BIN (a Docker Compose v2 binary), the Python packages of the three services
(gunicorn among them), mongomock. The resolver's servers run without MongoDB here: only answers that need
no database are requested.
Run from anywhere:  python dev-tests/install/test_deploy.py
Exits with status 1 on any failure.
"""
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = os.environ.get("COMPOSE_BIN") or shutil.which("docker-compose") or ""
SCALABLE = ("web-service", "data-entry-service", "portal-service", "portal-worker")
REPLICA_KEYS = {"web-service": "WEB_SERVICE_REPLICAS", "data-entry-service": "DATA_ENTRY_SERVICE_REPLICAS",
                "portal-service": "PORTAL_SERVICE_REPLICAS", "portal-worker": "PORTAL_WORKER_REPLICAS"}
PROCESS_KEYS = {"web-service": "WEB_SERVICE_PROCESSES", "data-entry-service": "DATA_ENTRY_SERVICE_PROCESSES",
                "portal-service": "PORTAL_SERVICE_PROCESSES"}
STOP_PERIOD = 10                     # seconds Docker waits after SIGTERM before SIGKILL (Compose default)

results: list[tuple[bool, str]] = []


def check(condition, label: str, detail=None) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f" — {detail}"))


# --------------------------------------------------------------------------- the daily backup
# Options of mongodump (MongoDB Database Tools 100.x, "mongodump --help"); --nsInclude/--nsExclude/--nsFrom/--nsTo are
# mongorestore's only.
MONGODUMP_OPTIONS = {"-h", "--host", "--port", "--uri", "-u", "--username", "-p", "--password",
                     "--authenticationDatabase", "--authenticationMechanism", "--awsSessionToken", "--gssapiServiceName",
                     "--gssapiHostName", "--ssl", "--tls", "--sslCAFile", "--tlsCAFile", "--sslPEMKeyFile",
                     "--tlsCertificateKeyFile", "-d", "--db", "-c", "--collection", "-q", "--query", "--queryFile",
                     "--readPreference", "--forceTableScan", "--gzip", "-o", "--out", "--archive", "--oplog",
                     "--dumpDbUsersAndRoles", "--excludeCollection", "--excludeCollectionsWithPrefix", "-j",
                     "--numParallelCollections", "--viewsAsCollections", "-v", "--verbose", "--quiet", "--config",
                     "--compressors"}


def backup_checks() -> None:
    script = REPO / "scripts" / "resolver-backup.sh"
    text = script.read_text()
    found = re.search(r"'(mongodump [^']*)'", text)
    command = found.group(1) if found else ""
    options = {word.split("=", 1)[0] for word in shlex.split(command.replace('"$', '"X'))[1:] if word.startswith("-")}
    check(command and options <= MONGODUMP_OPTIONS,
          "backup: mongodump is given only options mongodump has", sorted(options - MONGODUMP_OPTIONS))
    # the JavaScript the result's record gives mongosh is valid (node checks its syntax; db is mongosh's)
    found = re.search(r'--eval "(.*?)"\'', text, re.S)
    script_js = found.group(1).replace('\\"', '"') if found else ""
    node = shutil.which("node")
    if node and script_js:
        js = Path(tempfile.mkdtemp()) / "record.js"
        js.write_text("const db = {settings: {findOne() {}, replaceOne() {}}};\n" + script_js)
        syntax = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        check(syntax.returncode == 0 and "backup.last" in script_js, "backup: the record's mongosh script is valid JavaScript",
              syntax.stderr[-300:])
    else:
        check(bool(script_js), "backup: the record's mongosh script is found", text[-300:])
    for outcome, docker in (("fails", 'echo "error parsing command line options" >&2; exit 2'),
                            ("works", 'printf "ARCHIVE-BYTES"')):
        work = Path(tempfile.mkdtemp(prefix="backup-test-"))
        bin_dir, backups = work / "bin", work / "backups"
        bin_dir.mkdir()
        stand_in = bin_dir / "docker"
        # "docker compose exec …" dumps (or fails); "docker compose ps" lists no running portal
        # "docker compose exec … mongosh" records the result: its arguments are kept in a file (the result's record
        # fails in the first run, which must not change the backup's outcome)
        recorded = work / "recorded"
        record = f'echo "$*" >> {recorded}; ' + ("exit 1" if outcome == "fails" else "exit 0")
        stand_in.write_text("#!/bin/sh\ncase \"$*\" in *mongosh*) " + record + " ;; *mongodump*) " + docker
                            + " ;; *) exit 0 ;; esac\n")
        stand_in.chmod(0o755)
        run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                                  "RESOLVER_DIR": str(work), "BACKUP_DIR": str(backups)})
        left = sorted(p.name for p in backups.iterdir()) if backups.exists() else []
        if outcome == "fails":
            check(run.returncode == 1 and "ERROR: database backup failed" in run.stdout and not left,
                  "backup: a failed dump says ERROR, exits 1 and leaves no partial file",
                  (run.returncode, run.stdout[-200:], left))
            noted = recorded.read_text() if recorded.exists() else ""
            check("BACKUP_OK=0" in noted and "BACKUP_ERROR=the database dump failed" in noted
                  and "BACKUP_DB=resolver_portal" in noted and "database-service" in noted,
                  "backup: a failure is recorded for the portal's monitoring (ADR 0008)", noted[:300])
            check("WARNING: the result was not recorded" in run.stdout and run.returncode == 1,
                  "backup: a record that cannot be written is only a warning", run.stdout[-200:])
        else:
            archives = [n for n in left if n.endswith(".archive.gz")]
            check(run.returncode == 0 and " OK " in run.stdout and len(archives) == 1
                  and (backups / archives[0]).read_text() == "ARCHIVE-BYTES" and not any(n.endswith(".tmp") for n in left),
                  "backup: a good dump writes the archive and says OK", (run.returncode, run.stdout[-200:], left))
            noted = recorded.read_text() if recorded.exists() else ""
            check("BACKUP_OK=1" in noted and f"BACKUP_FILE={backups / archives[0]}" in noted if archives else False,
                  "backup: a good run is recorded with its file", noted[:300])
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- the organisations' own domains
def domains_script_checks() -> None:
    """scripts/custom-domains.sh (Documentation/adr/0009-tenant-domains.md) with stand-in docker, nginx, systemctl and
    certbot: the verified direct domains read from the portal's database, a site written from the installer's template
    for each new one and Certbot asked for its certificate, names that are not host names refused before any file or
    command, sites of domains no longer verified reported, and CERTBOT_EMAIL required."""
    script = REPO / "scripts" / "custom-domains.sh"
    work = Path(tempfile.mkdtemp(prefix="domains-test-"))
    bin_dir, available, enabled, calls = work / "bin", work / "available", work / "enabled", work / "calls"
    bin_dir.mkdir()
    (work / "scripts" / "templates").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "templates" / "nginx-site-http.conf", work / "scripts" / "templates")
    names = "id.acme.example\nbad;rm -rf x\nshop.beta.example\n"
    stand_ins = {
        # "docker compose exec … mongosh": the verified direct domains, one per line (one of them not a host name)
        "docker": f'echo "docker $*" >> {calls}; case "$*" in *mongosh*) printf "{names}" ;; esac',
        "nginx": f'echo "nginx $*" >> {calls}',
        "systemctl": f'echo "systemctl $*" >> {calls}',
        # certbot adds the HTTPS server to the site, as the real one does
        "certbot": f'echo "certbot $*" >> {calls}; d=$(echo "$*" | sed -n "s/.*-d \\([^ ]*\\).*/\\1/p"); '
                   f'echo "    ssl_certificate /etc/letsencrypt/live/$d/fullchain.pem;" >> {available}/gs1resolver-domain-$d',
    }
    for name, body in stand_ins.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work),
           "NGINX_AVAILABLE": str(available), "NGINX_ENABLED": str(enabled)}
    env.pop("CERTBOT_EMAIL", None)
    run = subprocess.run(["bash", str(script), "apply"], capture_output=True, text=True, timeout=60, env=env)
    check(run.returncode == 1 and "CERTBOT_EMAIL is not set" in run.stdout,
          "custom domains: apply needs CERTBOT_EMAIL", run.stdout[-200:])
    (work / ".env").write_text("CERTBOT_EMAIL='ops@example.org'\nPORTAL_DB_NAME=resolver_portal\n")
    run = subprocess.run(["bash", str(script), "list"], capture_output=True, text=True, timeout=60, env=env)
    check(run.returncode == 0 and "id.acme.example: no site yet" in run.stdout and "bad;rm -rf x: refused" in run.stdout,
          "custom domains: list shows each verified direct domain and refuses a name that is not a host name", run.stdout)
    run = subprocess.run(["bash", str(script), "apply"], capture_output=True, text=True, timeout=60, env=env)
    log = calls.read_text() if calls.exists() else ""
    site = available / "gs1resolver-domain-id.acme.example"
    text = site.read_text() if site.exists() else ""
    check(run.returncode == 0 and "server_name id.acme.example;" in text and "proxy_pass http://127.0.0.1:8080;" in text
          and "proxy_set_header Host $host;" in text and (enabled / "gs1resolver-domain-id.acme.example").is_symlink(),
          "custom domains: apply writes a site from the installer's template and enables it", (run.stdout, text[:300]))
    check("certbot --nginx -d id.acme.example --non-interactive --agree-tos -m ops@example.org" in log
          and "certbot --nginx -d shop.beta.example" in log and "nginx -t" in log and "systemctl reload nginx" in log,
          "custom domains: nginx checked and reloaded, Certbot asked for each certificate", log)
    check("rm -rf" not in log.replace("bad;rm -rf x", "") and not any("bad" in p.name for p in available.iterdir())
          and "resolver_portal" in log and "PORTAL_DB=resolver_portal" in log,
          "custom domains: a name that is not a host name reaches no file or command", log)
    certbot_calls = log.count("certbot --nginx")
    run = subprocess.run(["bash", str(script), "apply"], capture_output=True, text=True, timeout=60, env=env)
    log = calls.read_text()
    check(log.count("certbot --nginx") == certbot_calls and "id.acme.example: already served" in run.stdout,
          "custom domains: a domain already served is left alone", run.stdout)
    (available / "gs1resolver-domain-old.example").write_text("server {}\n")
    run = subprocess.run(["bash", str(script), "list"], capture_output=True, text=True, timeout=60, env=env)
    check("old.example: site of a domain no longer verified" in run.stdout and "id.acme.example: site and certificate"
          in run.stdout, "custom domains: list reports sites of domains no longer verified", run.stdout)
    shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- docker-compose.yml
def compose_config(env_lines: list[str]) -> tuple[dict | None, str]:
    """The configuration as Compose resolves it, with these lines as the installation's .env (and
    nothing from the caller's environment or from a .env in the repository)."""
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp, "interpolation.env")
        env_file.write_text("".join(line + "\n" for line in env_lines))
        run = subprocess.run([COMPOSE, "--project-directory", str(REPO), "-f", str(REPO / "docker-compose.yml"),
                              "--env-file", str(env_file), "config", "--format", "json"],
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp},
                             capture_output=True, text=True)
    if run.returncode:
        return None, run.stderr
    return json.loads(run.stdout), run.stderr


ENGINE_SERVICES = ("web-service", "data-entry-service", "portal-service", "portal-worker", "portal-db-init")


def release_checks() -> None:
    """One release of the GS1 Barcode Syntax Engine for every service, written once (ADR 0003)."""
    sys.path.insert(0, str(REPO / "dev-tests"))
    from engine_release import engine_release  # noqa: PLC0415
    release = engine_release()
    config, err = compose_config([])
    args = {name: ((config or {}).get("services", {}).get(name, {}).get("build") or {}).get("args", {})
            for name in ENGINE_SERVICES}
    check(all(a.get("GS1_SYNTAX_ENGINE_RELEASE") == release for a in args.values()),
          f"engine release {release}: the build argument of every service that checks GS1 data", args or err)
    for folder in ("web_server", "data_entry_server"):
        text = (REPO / folder / "Dockerfile").read_text()
        check("ARG GS1_SYNTAX_ENGINE_RELEASE\n" in text and 'gs1encoder@$GS1_SYNTAX_ENGINE_RELEASE' in text
              and not re.search(r"npm install[^\n]*gs1encoder(\s|$)", text),
              f"engine release: {folder}/Dockerfile installs gs1encoder at the build argument's release")
    portal = (REPO / "portal" / "Dockerfile").read_text()
    check("ARG GS1_SYNTAX_ENGINE_RELEASE" in portal and 'build-syntax-engine.sh /opt/gs1-syntax-engine "$GS1_SYNTAX_ENGINE_RELEASE"' in portal,
          "engine release: portal/Dockerfile builds the engine at the build argument's release")
    script = (REPO / "portal" / "tools" / "build-syntax-engine.sh").read_text()
    action = (REPO / ".github" / "actions" / "dev-tests-setup" / "action.yml").read_text()
    pinned = re.compile(r"(RELEASE=\$\{2:-\d|GS1ENCODER_VERSION=\d)")
    check(not pinned.search(script) and not pinned.search(action) and "x-gs1-syntax-engine" in action,
          "engine release: neither the build script nor the CI set-up action holds a release of its own")
    dictionary = REPO / "portal" / "gs1_dictionary.json"
    if dictionary.exists():
        made_from = json.loads(dictionary.read_text()).get("release")
        check(made_from == release, f"engine release: portal/gs1_dictionary.json made from {release}", made_from)


def compose_checks() -> None:
    config, err = compose_config([])
    check(config is not None, "docker compose config accepts the file without .env", err)
    if config is None:
        return
    services = config["services"]
    for name in SCALABLE:
        check("container_name" not in services[name], f"{name}: no fixed container_name (Compose can replicate it)")
        check(services[name].get("deploy", {}).get("replicas") == 1, f"{name}: one replica by default")
    for name, fixed in (("database-service", "database-server"), ("frontend-proxy-service", "frontend-proxy-server")):
        check(services[name].get("container_name") == fixed and "replicas" not in services[name].get("deploy", {}),
              f"{name}: stays single, keeps the official name {fixed}")
    for name in PROCESS_KEYS:
        check(services[name].get("environment", {}).get("WEB_CONCURRENCY") == "2",
              f"{name}: two server processes by default (WEB_CONCURRENCY)")
    proxy_deps = services["frontend-proxy-service"].get("depends_on", {})
    check(set(proxy_deps) == {"web-service", "data-entry-service", "portal-service"}
          and not any(dep.get("restart") for dep in proxy_deps.values()),
          "the proxy starts after the three services and is no longer restarted when they change")

    lines = [f"{key}={n}" for n, key in enumerate(REPLICA_KEYS.values(), start=2)]
    lines += ["WEB_SERVICE_PROCESSES=4", "PORTAL_SERVICE_PROCESSES=3"]
    config, err = compose_config(lines)
    check(config is not None, "docker compose config accepts replica and process counts from .env", err)
    if config is not None:
        services = config["services"]
        got = {name: services[name]["deploy"]["replicas"] for name in SCALABLE}
        check(got == {name: n for n, name in enumerate(REPLICA_KEYS, start=2)},
              "each service takes its own number of replicas from .env", got)
        got = {name: services[name]["environment"]["WEB_CONCURRENCY"] for name in PROCESS_KEYS}
        check(got == {"web-service": "4", "data-entry-service": "2", "portal-service": "3"},
              "each service takes its own number of processes from .env", got)
        check("WEB_CONCURRENCY" not in services["portal-worker"].get("environment", {}),
              "the job worker is not a web server (one job at a time per replica)")

    config, err = compose_config(["WEB_SERVICE_REPLICAS=two"])
    check(config is None and "replicas" in err, "a replica count that is not a number is refused", err.strip()[-120:])


# --------------------------------------------------------------------------- proxy
def proxy_checks() -> None:
    dockerfile = (REPO / "frontend_proxy_server" / "Dockerfile").read_text()
    found = re.search(r"^FROM nginx:(\d+)\.(\d+)(?:\.(\d+))?", dockerfile, re.M)
    version = tuple(int(x or 0) for x in found.groups()) if found else ()
    check(version >= (1, 27, 3),
          f"proxy image nginx {'.'.join(map(str, version))} supports \"resolve\" in upstream blocks (1.27.3 or later)")

    conf = (REPO / "frontend_proxy_server" / "nginx.conf").read_text()
    conf = re.sub(r"#.*", "", conf)
    upstreams = dict(re.findall(r"upstream\s+([\w-]+)\s*\{([^}]*)\}", conf))
    check(re.search(r"^\s*resolver\s+127\.0\.0\.11\s+valid=\d+s\b", conf, re.M) is not None,
          "nginx asks Docker's DNS (127.0.0.11) with a short validity")
    targets = re.findall(r"proxy_pass\s+http://([\w-]+)", conf)
    check(targets and all(t in upstreams for t in targets),
          f"every proxy_pass goes to an upstream block ({', '.join(sorted(set(targets)))})")
    expected = {"web-service:4000", "data-entry-service:3000", "portal-service:8000"}
    servers = {}
    for name, body in upstreams.items():
        for address, params in re.findall(r"server\s+(\S+)([^;]*);", body):
            servers[address] = ("resolve" in params.split(), "zone" in body)
    check(set(servers) == expected and all(r and z for r, z in servers.values()),
          "each service's upstream is resolved at run time (\"resolve\", shared zone)", servers)


# --------------------------------------------------------------------------- servers
def image_tree(dockerfile: Path, context: Path) -> Path:
    """A folder with the files the COPY instructions of a Dockerfile put in its working directory (copies
    from another build stage left out), to start a server as the image would."""
    text = re.sub(r"\\\n\s*", " ", dockerfile.read_text())
    tree = Path(tempfile.mkdtemp(prefix="deploy-image-"))
    for line in text.splitlines():
        parts = shlex.split(line.strip())
        if not parts or parts[0] != "COPY" or any(p.startswith("--from") for p in parts):
            continue
        *sources, target = [p for p in parts[1:] if not p.startswith("--")]
        destination = tree / target.removeprefix("/app/").removeprefix("./").lstrip("/")
        for source in sources:
            for path in sorted(context.glob(source)):
                if path.is_dir():
                    shutil.copytree(path, destination if not target.endswith("/") or len(sources) == 1
                                    else destination / path.name, dirs_exist_ok=True)
                else:
                    destination.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination / path.name)
    return tree


def image_files_checks(tree: Path) -> None:
    """Every Python module and JSON data file at the top of portal/ is in the image."""
    wanted = sorted(p.name for p in (REPO / "portal").iterdir() if p.suffix in (".py", ".json"))
    missing = [name for name in wanted if not (tree / name).exists()]
    check(not missing, f"portal image: every module and data file of portal/ is copied ({len(wanted)})", missing)
    check((tree / "static" / "app.js").exists() and (tree / "assets").is_dir(),
          "portal image: static files and assets are copied")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def image_command(dockerfile: Path) -> tuple[list[str], dict[str, str]]:
    """The CMD (exec form) and the ENV values of a Dockerfile."""
    text = dockerfile.read_text()
    cmd = json.loads(re.findall(r"^CMD\s+(\[.*\])\s*$", text, re.M)[-1])
    env = {}
    for line in re.findall(r"^ENV\s+(.+)$", text, re.M):
        parts = shlex.split(line)
        if len(parts) == 2 and "=" not in parts[0]:
            env[parts[0]] = parts[1]
        else:
            env.update(p.split("=", 1) for p in parts if "=" in p)
    return cmd, env


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError as error:
        return 0, str(error)


def children(pid: int) -> list[int]:
    run = subprocess.run(["ps", "-o", "pid=", "--ppid", str(pid)], capture_output=True, text=True)
    return [int(x) for x in run.stdout.split()]


def server_checks(label: str, dockerfile: Path, workdir: Path, path: str, expect, env_extra: dict[str, str]) -> None:
    cmd, image_env = image_command(dockerfile)
    check(cmd[:1] == ["gunicorn"] and "--threads" in cmd and "--workers" not in cmd,
          f"{label}: the image runs gunicorn, with the process count left to WEB_CONCURRENCY")
    check(image_env.get("WEB_CONCURRENCY") == "2", f"{label}: the image's default is two processes")
    port = free_port()
    cmd = list(cmd)
    cmd[cmd.index("--bind") + 1] = f"127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PORTAL_", "MONGO_", "WEB_CONCURRENCY"))}
    env.update(image_env)
    env.update(env_extra)
    env["WEB_CONCURRENCY"] = "3"
    log = tempfile.TemporaryFile()
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=workdir, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        status, body = 0, ""
        while time.monotonic() - started < 30 and proc.poll() is None:
            status, body = get(f"http://127.0.0.1:{port}{path}")
            if status:
                break
            time.sleep(0.3)
        check(status == 200 and expect(body), f"{label}: answers GET {path} under gunicorn", (status, body[:200]))
        time.sleep(0.5)
        workers = children(proc.pid)
        check(len(workers) == 3, f"{label}: WEB_CONCURRENCY=3 → three server processes", workers)
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(timeout=STOP_PERIOD)
        except subprocess.TimeoutExpired:
            code = None
        check(code == 0, f"{label}: stops cleanly on SIGTERM within Docker's {STOP_PERIOD}-second stop period", code)
        log.seek(0)
        output = log.read().decode("utf-8", "replace")
        check(f'"GET {path} HTTP/1.1" 200' in output, f"{label}: requests are logged (docker compose logs)")
        check("Control socket listening" not in output, f"{label}: no gunicorn control socket", output[-300:])
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()


def secret_key_checks() -> None:
    """Six portal processes start at once on an empty volume without PORTAL_SECRET_KEY."""
    portal = REPO / "portal"
    probe = "import app; print('KEY=' + app.app.secret_key.decode())"
    for attempt in range(2):
        config = tempfile.mkdtemp(prefix="deploy-secret-")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PORTAL_", "RESOLVER_"))}
        env.update(SESSION_TOKEN="tok", FQDN="id.example.org", PORTAL_CONFIG_DIR=config,
                   PORTAL_DB_URI=os.environ.get("PORTAL_DB_URI") or "mongomock://",
                   PORTAL_DB_NAME=f"devtest_deploy_{os.getpid()}_{attempt}")
        procs = [subprocess.Popen([sys.executable, "-c", probe], cwd=portal, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
        keys = []
        for proc in procs:
            out, _ = proc.communicate(timeout=120)
            keys += [line[4:] for line in out.splitlines() if line.startswith("KEY=")]
        on_disk = Path(config, "secret.key").read_text().strip() if Path(config, "secret.key").exists() else ""
        leftovers = [p.name for p in Path(config).iterdir() if p.name.startswith("secret.key.")]
        check(len(keys) == 6 and len(set(keys)) == 1 and re.fullmatch(r"[0-9a-f]{64}", keys[0] or "")
              and keys[0] == on_disk,
              f"secret.key (run {attempt + 1}): six processes starting together share one complete key", set(keys))
        check(not leftovers, f"secret.key (run {attempt + 1}): no draft files left", leftovers)
        shutil.rmtree(config, ignore_errors=True)

    # The same race made certain: eight threads ask for the key at once while writing it is slow. A key file
    # that becomes visible before its content (the earlier code) gives some of them an empty key.
    config = tempfile.mkdtemp(prefix="deploy-secret-")
    race = ("import os, secrets, threading, time, app\n"
            f"app.CONFIG_DIR = {config!r}; os.environ.pop('PORTAL_SECRET_KEY', None)\n"
            "real = secrets.token_hex\n"
            "secrets.token_hex = lambda n=32: (time.sleep(0.3), real(n))[1]\n"
            "gate, keys = threading.Barrier(8), []\n"
            "def ask():\n"
            "    gate.wait()\n"
            "    try: keys.append(app._secret_key().decode())\n"
            "    except Exception as exc: keys.append(f'error: {exc}')\n"
            "threads = [threading.Thread(target=ask) for _ in range(8)]\n"
            "[t.start() for t in threads]; [t.join() for t in threads]\n"
            "print('KEYS=' + '|'.join(keys))\n")
    env.update(PORTAL_CONFIG_DIR=tempfile.mkdtemp(prefix="deploy-secret-"), PORTAL_SECRET_KEY="import-only")
    run = subprocess.run([sys.executable, "-c", race], cwd=portal, env=env, capture_output=True, text=True)
    keys = next((line[5:].split("|") for line in run.stdout.splitlines() if line.startswith("KEYS=")), [])
    check(len(keys) == 8 and len(set(keys)) == 1 and re.fullmatch(r"[0-9a-f]{64}", keys[0]),
          "secret.key: eight threads at once while the key is slow to write all get the same complete key",
          set(keys) or run.stderr[-300:])
    shutil.rmtree(config, ignore_errors=True)

    config = tempfile.mkdtemp(prefix="deploy-secret-")
    env.pop("PORTAL_SECRET_KEY", None)
    Path(config, "secret.key").write_text("")
    env.update(PORTAL_CONFIG_DIR=config)
    run = subprocess.run([sys.executable, "-c", probe], cwd=portal, env=env, capture_output=True, text=True)
    check(run.returncode != 0 and "secret.key is empty" in run.stderr,
          "an empty secret.key stops the portal instead of signing sessions with an empty key")
    shutil.rmtree(config, ignore_errors=True)


def main() -> int:
    if not COMPOSE or not Path(COMPOSE).exists():
        print("FAIL COMPOSE_BIN is not set to a Docker Compose v2 binary")
        return 1
    compose_checks()
    backup_checks()
    domains_script_checks()
    release_checks()
    proxy_checks()
    no_db = "mongodb://127.0.0.1:9/?serverSelectionTimeoutMS=300"
    server_checks("web-service", REPO / "web_server" / "Dockerfile", REPO / "web_server" / "src",
                  "/api/.well-known/gs1resolver",
                  lambda body: json.loads(body).get("resolverRoot") == "https://id.example.org",
                  {"MONGO_URI": no_db, "FQDN": "id.example.org"})
    server_checks("data-entry-service", REPO / "data_entry_server" / "Dockerfile", REPO / "data_entry_server" / "src",
                  "/api/swagger.json", lambda body: "paths" in json.loads(body),
                  {"MONGO_URI": no_db, "SESSION_TOKEN": "tok"})
    config = tempfile.mkdtemp(prefix="deploy-portal-")
    portal_tree = image_tree(REPO / "portal" / "Dockerfile", REPO / "portal")
    image_files_checks(portal_tree)
    server_checks("portal-service", REPO / "portal" / "Dockerfile", portal_tree, "/portal/healthz",
                  lambda body: json.loads(body).get("portal") == "ok",
                  {"SESSION_TOKEN": "tok", "FQDN": "id.example.org", "PORTAL_CONFIG_DIR": config,
                   "PORTAL_DB_URI": os.environ.get("PORTAL_DB_URI") or "mongomock://",
                   "PORTAL_DB_NAME": f"devtest_deploy_portal_{os.getpid()}",
                   "PORTAL_SECRET_KEY": "deploy-test-key", "DATA_ENTRY_URL": "http://127.0.0.1:9/api"})
    shutil.rmtree(config, ignore_errors=True)
    shutil.rmtree(portal_tree, ignore_errors=True)
    secret_key_checks()
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
