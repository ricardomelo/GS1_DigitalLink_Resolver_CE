#!/usr/bin/env python3
"""
Development test for the least privilege of the services (F-012; Documentation/adr/0030-least-privilege-services.md).

Checks, without Docker or MongoDB:
  * docker-compose.yml through "docker compose config", without .env: MongoDB's root credentials (MONGO_URI,
    MONGO_INITDB_ROOT_*) reach only the database and portal-db-init, every other service sees them empty; the
    resolver and the data entry API start after portal-db-init has finished well; the database and the proxy are
    published on the host's loopback address unless .env names another; the five Python services' root file system
    read only with /tmp in memory (ADR 0061);
  * the Dockerfiles of the resolver, the data entry API and the portal: the image runs as a user of its own, not root,
    and its final stage installs no package from Debian's repository (the official images installed nano: an editor
    for whoever gets a shell in the container; finding U-006, ADR 0050);
  * service_db.py (the resolver's and the data entry API's connection): the URI built from <PREFIX>_DB_* with the
    credentials percent-encoded and authSource=admin, a complete <PREFIX>_DB_URI preferred, MONGO_URI only as a
    fallback with a warning, an error with nothing; the two copies are the same file;
  * portal/db_init.py with a stand-in MongoDB client: the two roles defined in admin with exactly the privileges of
    the ADR, the two users created in admin with their role only, then brought up to date; a service without a
    password left alone with a warning; MongoDB's root user refused as a service's user; no password printed; the
    example root password warned about outside development;
  * the collections the resolver's code uses are those its role grants (a new one fails here before a server);
  * .env.example's example passwords are those example_secrets.py refuses, and the installer and the rotation script
    handle the two new passwords.

Requirements: COMPOSE_BIN (a Docker Compose v2 binary), pymongo.
Run from anywhere:  python dev-tests/install/test_least_privilege.py
Exits with status 1 on any failure.
"""
import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = os.environ.get("COMPOSE_BIN", "")
ROOT_HOLDERS = {"database-service", "portal-db-init"}
results: list[tuple[bool, str]] = []


def check(condition, label: str, detail=None) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f"  → {detail}"))


def compose_config(env_lines: list[str]) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp, "interpolation.env")
        env_file.write_text("".join(line + "\n" for line in env_lines))
        run = subprocess.run([COMPOSE, "--project-directory", str(REPO), "-f", str(REPO / "docker-compose.yml"),
                              "--env-file", str(env_file), "config", "--format", "json"],
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp},
                             capture_output=True, text=True)
    if run.returncode:
        print(run.stderr[-400:])
        return None
    return json.loads(run.stdout)


def published(service: dict, target: int) -> str | None:
    for port in service.get("ports", []):
        if int(port.get("target", 0)) == target:
            return port.get("host_ip", "")
    return None


# --------------------------------------------------------------------------- docker-compose.yml
def compose_checks() -> None:
    config = compose_config([])
    check(config is not None, "compose: the file is accepted without .env")
    if config is None:
        return
    services = config["services"]
    holders = sorted(name for name, svc in services.items()
                     if any((svc.get("environment") or {}).get(k) for k in
                            ("MONGO_URI", "MONGO_INITDB_ROOT_USERNAME", "MONGO_INITDB_ROOT_PASSWORD")))
    check(set(holders) == ROOT_HOLDERS, "compose: MongoDB's root credentials reach the database and portal-db-init only",
          holders)
    for name in ("web-service", "data-entry-service"):
        env = services[name].get("environment") or {}
        prefix = "RESOLVER" if name == "web-service" else "DATA_ENTRY"
        check(env.get(f"{prefix}_DB_USERNAME") and env.get(f"{prefix}_DB_PASSWORD"),
              f"compose: {name} receives its own user and password ({prefix}_DB_*)")
        deps = services[name].get("depends_on") or {}
        check(deps.get("portal-db-init", {}).get("condition") == "service_completed_successfully",
              f"compose: {name} starts after portal-db-init has made its user", deps)
    check(published(services["database-service"], 27017) == "127.0.0.1",
          "compose: without .env MongoDB is published on the host's loopback address only",
          services["database-service"].get("ports"))
    check(published(services["frontend-proxy-service"], 80) == "127.0.0.1"
          and services["frontend-proxy-service"]["environment"].get("PROXY_BIND_ADDRESS") == "127.0.0.1",
          "compose: without .env the proxy is published on the host's loopback address only (and told so)",
          services["frontend-proxy-service"].get("ports"))
    # read-only file systems (F-012 residual 2, ADR 0061): only /tmp in memory, with a size, and the declared volumes
    read_only = {"web-service": "64m", "data-entry-service": "64m", "portal-db-init": "64m",
                 "portal-service": "256m", "portal-worker": "256m"}
    for name, size in read_only.items():
        svc = services[name]
        check(svc.get("read_only") is True and svc.get("tmpfs") == [f"/tmp:size={size}"],
              f"compose: {name}'s root file system is read only, /tmp a memory file system of {size}",
              (svc.get("read_only"), svc.get("tmpfs")))
        writable = sorted(v.get("target") for v in svc.get("volumes") or [] if not v.get("read_only"))
        check(writable == (["/app/config"] if name in ("portal-service", "portal-worker") else []),
              f"compose: {name} writes to " + ("no volume but its configuration's (/app/config)"
                                               if name in ("portal-service", "portal-worker") else "no volume"), writable)
    check(not any(services[n].get("read_only") for n in ("database-service", "frontend-proxy-service")),
          "compose: the database and the proxy are not read only (the ADR's residual: the official image, the "
          "configuration written at start)")
    config = compose_config(["PROXY_BIND_ADDRESS=0.0.0.0", "DATABASE_BIND_ADDRESS=10.0.0.4"])
    if config is not None:
        services = config["services"]
        check(published(services["frontend-proxy-service"], 80) == "0.0.0.0"
              and published(services["database-service"], 27017) == "10.0.0.4",
              "compose: .env still chooses the addresses (PROXY_BIND_ADDRESS, DATABASE_BIND_ADDRESS)")


# --------------------------------------------------------------------------- Dockerfiles
def final_stage_user(dockerfile: Path) -> tuple[str | None, bool]:
    """The USER of the last stage, and whether it comes before the CMD."""
    lines = [line.strip() for line in dockerfile.read_text().splitlines()]
    last_from = max(i for i, line in enumerate(lines) if line.upper().startswith("FROM "))
    user, before_cmd = None, False
    for line in lines[last_from:]:
        if line.upper().startswith("USER "):
            user = line.split(None, 1)[1].strip()
        if line.upper().startswith("CMD "):
            before_cmd = user is not None
    return user, before_cmd


def dockerfile_checks() -> None:
    for folder in ("web_server", "data_entry_server", "portal"):
        user, before_cmd = final_stage_user(REPO / folder / "Dockerfile")
        check(user and user not in ("root", "0", "0:0") and before_cmd,
              f"{folder}/Dockerfile: the image runs as a user of its own, not root", user)
        text = (REPO / folder / "Dockerfile").read_text()
        check(user and re.search(rf"useradd [^\n]*--system[^\n]*\b{re.escape(user)}\b", text),
              f"{folder}/Dockerfile: that user is a system account made in the image", user)
        final = text.splitlines()[max(i for i, line in enumerate(text.splitlines())
                                       if line.strip().upper().startswith("FROM ")):]
        package = re.compile(r"\b(apt-get|apt|dpkg) +(install|-i)\b|\bnano\b")
        installs = [line.strip() for line in final if not line.strip().startswith("#") and package.search(line)]
        check(not installs, f"{folder}/Dockerfile: the final image installs no package from Debian's repository "
              "(no editor)", installs)


# --------------------------------------------------------------------------- service_db.py
def load(folder: Path, name: str):
    sys.path.insert(0, str(folder))
    try:
        sys.modules.pop(name, None)
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(folder))


@contextlib.contextmanager
def environment(**values):
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(("RESOLVER_DB_", "DATA_ENTRY_DB_", "MONGO_", "PORTAL_DB_", "FQDN")):
            del os.environ[key]
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


class Log:
    def __init__(self):
        self.lines = []

    def warning(self, message, *args):
        self.lines.append(message % args)


def service_db_checks() -> None:
    copies = {(REPO / f / "service_db.py").read_bytes() for f in ("web_server/src", "data_entry_server/src")}
    check(len(copies) == 1, "service_db.py: the same file in the resolver and the data entry API")
    service_db = load(REPO / "web_server" / "src", "service_db")
    with environment(RESOLVER_DB_USERNAME="resolver web", RESOLVER_DB_PASSWORD="p@ss:w/rd", MONGO_URI="mongodb://r:r@h"):
        log = Log()
        built = service_db.uri("RESOLVER", log)
        check(built == "mongodb://resolver+web:p%40ss%3Aw%2Frd@database-service:27017/?authSource=admin" and not log.lines,
              "service_db: the URI built from the service's user and password (percent-encoded, authSource=admin), "
              "not MONGO_URI", built)
        check(service_db.host_of(built) == "database-service:27017/?authSource=admin",
              "service_db: the host logged without the credentials")
    with environment(DATA_ENTRY_DB_USERNAME="u", DATA_ENTRY_DB_PASSWORD="p", DATA_ENTRY_DB_HOST="db.internal:27018"):
        check(service_db.uri("DATA_ENTRY").startswith("mongodb://u:p@db.internal:27018/"),
              "service_db: <PREFIX>_DB_HOST names another server")
    with environment(RESOLVER_DB_URI="mongodb://x:y@elsewhere/?tls=true", RESOLVER_DB_USERNAME="u", RESOLVER_DB_PASSWORD="p"):
        check(service_db.uri("RESOLVER") == "mongodb://x:y@elsewhere/?tls=true",
              "service_db: a complete <PREFIX>_DB_URI is preferred")
    with environment(MONGO_URI="mongodb://root:pw@database-service:27017"):
        log = Log()
        legacy = service_db.uri("RESOLVER", log)
        check(legacy == "mongodb://root:pw@database-service:27017" and log.lines and "root" in log.lines[0]
              and "pw" not in log.lines[0].replace("RESOLVER_DB_PASSWORD", ""),
              "service_db: MONGO_URI only as a fallback, with a warning naming the root user and not the password",
              log.lines)
    with environment():
        try:
            service_db.uri("DATA_ENTRY")
            check(False, "service_db: no connection settings at all is an error naming them")
        except RuntimeError as exc:
            check("DATA_ENTRY_DB_PASSWORD" in str(exc), "service_db: no connection settings at all is an error naming them")


# --------------------------------------------------------------------------- db_init.py
class FakeDatabase:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def command(self, name, value, **kw):
        self.client.calls.append((self.name, name, value, kw))
        if name == "rolesInfo":
            return {"roles": [{"role": value}] if (self.name, value) in self.client.roles else []}
        if name == "usersInfo":
            return {"users": [{"user": value}] if (self.name, value) in self.client.users else []}
        if name == "createRole":
            self.client.roles.add((self.name, value))
        if name == "createUser":
            self.client.users.add((self.name, value))
        return {"ok": 1}


class FakeClient:
    def __init__(self):
        self.calls, self.roles, self.users = [], set(), set()

    def __getitem__(self, name):
        return FakeDatabase(self, name)


def db_init_checks() -> None:
    db_init = load(REPO / "portal", "db_init")
    portal_db = "resolver_portal"
    expected_resolver = sorted(
        [("resolver_ce", "gs1resolver", ("find",))]
        + [(portal_db, c, ("find",)) for c in ("branding", "domains", "forwarding_rules", "settings", "tenants")]
        + [("resolver_log", c, ("createIndex", "insert", "update")) for c in ("request_counts", "requests")])
    expected_entry = [("resolver_ce", "gs1resolver", ("find", "insert", "remove", "update"))]

    def shape(privileges):
        return sorted((p["resource"]["db"], p["resource"]["collection"], tuple(sorted(p["actions"]))) for p in privileges)

    client = FakeClient()
    out = io.StringIO()
    with environment(RESOLVER_DB_USERNAME="resolver_web", RESOLVER_DB_PASSWORD="pw-resolver-77",
                     DATA_ENTRY_DB_USERNAME="resolver_data_entry", DATA_ENTRY_DB_PASSWORD="pw-entry-88",
                     MONGO_INITDB_ROOT_USERNAME="gs1resolver"), contextlib.redirect_stdout(out):
        db_init.service_users(client, portal_db)
    roles = {(db, value): kw for db, name, value, kw in client.calls if name == "createRole"}
    check(set(roles) == {("admin", "resolverService"), ("admin", "dataEntryService")},
          "db_init: the two services' roles defined in the admin database", sorted(roles))
    check(shape(roles.get(("admin", "resolverService"), {}).get("privileges", [])) == expected_resolver
          and roles[("admin", "resolverService")].get("roles") == [],
          "db_init: the resolver's role finds records and the portal's tenants, domains, settings, branding and "
          "forwarding rules, and writes the request log (insert, update, indexes), nothing else",
          shape(roles.get(("admin", "resolverService"), {}).get("privileges", [])))
    check(shape(roles.get(("admin", "dataEntryService"), {}).get("privileges", [])) == expected_entry
          and roles[("admin", "dataEntryService")].get("roles") == [],
          "db_init: the data entry API's role reads and writes the records, nothing else")
    users = {(db, value): kw for db, name, value, kw in client.calls if name == "createUser"}
    check(users.get(("admin", "resolver_web"), {}).get("roles") == [{"role": "resolverService", "db": "admin"}]
          and users[("admin", "resolver_web")].get("pwd") == "pw-resolver-77",
          "db_init: the resolver's user created in admin with its role only and the password of .env", users.keys())
    check(users.get(("admin", "resolver_data_entry"), {}).get("roles") == [{"role": "dataEntryService", "db": "admin"}]
          and users[("admin", "resolver_data_entry")].get("pwd") == "pw-entry-88",
          "db_init: the data entry API's user created in admin with its role only and the password of .env")
    check("pw-resolver-77" not in out.getvalue() and "pw-entry-88" not in out.getvalue()
          and out.getvalue().count("created") == 2, "db_init: says what it did, never a password", out.getvalue())

    client.calls.clear()
    out = io.StringIO()
    with environment(RESOLVER_DB_PASSWORD="new-pw-1", DATA_ENTRY_DB_PASSWORD="new-pw-2"), contextlib.redirect_stdout(out):
        db_init.service_users(client, "other_portal")
    names = [(db, name, value) for db, name, value, kw in client.calls if name in ("updateUser", "updateRole")]
    check(("admin", "updateUser", "resolver_web") in names and ("admin", "updateUser", "resolver_data_entry") in names
          and ("admin", "updateRole", "resolverService") in names
          and not any(name in ("createUser", "createRole") for db, name, value, kw in client.calls),
          "db_init: at the next start the users and roles are brought up to date (default user names), not made again",
          names)
    updated = [kw for db, name, value, kw in client.calls if name == "updateRole" and value == "resolverService"]
    check(updated and any(p["resource"]["db"] == "other_portal" for p in updated[0]["privileges"])
          and not any(p["resource"]["db"] == portal_db for p in updated[0]["privileges"]),
          "db_init: the resolver's role follows PORTAL_DB_NAME")

    client = FakeClient()
    out = io.StringIO()
    with environment(RESOLVER_DB_PASSWORD="pw-r"), contextlib.redirect_stdout(out):
        db_init.service_users(client, portal_db)
    made = [value for db, name, value, kw in client.calls if name in ("createUser", "updateUser")]
    check(made == ["resolver_web"] and "DATA_ENTRY_DB_PASSWORD is not set" in out.getvalue(),
          "db_init: a service without a password is left as it is, with a warning naming the setting", (made, out.getvalue()))

    for root_env in ({"MONGO_INITDB_ROOT_USERNAME": "boss"}, {"MONGO_URI": "mongodb://boss:pw@database-service:27017"}):
        client = FakeClient()
        with environment(RESOLVER_DB_USERNAME="boss", RESOLVER_DB_PASSWORD="pw", **root_env), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                db_init.service_users(client, portal_db)
                refused = False
            except RuntimeError as exc:
                refused = "root" in str(exc)
        check(refused and not any(name in ("createUser", "updateUser") and value == "boss"
                                  for db, name, value, kw in client.calls),
              f"db_init: MongoDB's root user refused as a service's user ({next(iter(root_env))})")

    # the example root password: warned about outside development (main() stops at the connection, port 9)
    for fqdn, warned in (("id.example.org", True), ("localhost", False)):
        env = {"MONGO_URI": "mongodb://gs1resolver:gs1resolver@127.0.0.1:9", "PORTAL_DB_PASSWORD": "x",
               "PORTAL_DB_INIT_TIMEOUT_MS": "200", "FQDN": fqdn,
               "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        run = subprocess.run([sys.executable, "db_init.py"], cwd=REPO / "portal", env=env, capture_output=True,
                             text=True, timeout=60)
        check(("example root password" in run.stdout) == warned and "gs1resolver:gs1resolver" not in run.stdout + run.stderr,
              f"db_init: the example root password {'warned about' if warned else 'not warned about'} when FQDN is "
              f"{fqdn}", run.stdout[-300:])

    # what it found, kept for the portal's monitoring (ADR 0062): the settings' names, never a value
    import inspect
    import mongomock
    portal_database = mongomock.MongoClient()[portal_db]
    db_init.record_examples(portal_database, ["MONGO_URI"])
    doc = portal_database["settings"].find_one({"_id": db_init.EXAMPLES_SETTING}) or {}
    check(doc.get("value", {}).get("names") == ["MONGO_URI"] and doc["value"].get("at") is not None
          and "gs1resolver" not in json.dumps(doc, default=str),
          "db_init: the example secrets found recorded in the portal's settings by name only (ADR 0062)", doc)
    db_init.record_examples(portal_database, [])
    check(portal_database["settings"].find_one({"_id": db_init.EXAMPLES_SETTING})["value"]["names"] == [],
          "db_init: …and cleared at the next start once changed")
    source = inspect.getsource(db_init.main)
    check("record_examples(database, examples)" in source
          and "examples = [] if example_secrets.development() else" in source,
          "db_init: main() records them at every start, none in development")


# --------------------------------------------------------------------------- the resolver's collections
def collections_checks() -> None:
    db_init = load(REPO / "portal", "db_init")
    src = REPO / "web_server" / "src"
    used, unresolved = set(), set()
    handle = r"""(?:\bdb|database\(\)|\.database|resolver_db)\[\s*"""
    for path in src.glob("*.py"):
        text = path.read_text()
        constants = dict(re.findall(r"""^([A-Z_]+)\s*=\s*['"]([A-Za-z0-9_]+)['"]""", text, re.M))
        used |= set(re.findall(handle + r"""['"]([A-Za-z0-9_]+)['"]\s*\]""", text))
        for name in re.findall(handle + r"""([A-Za-z_][A-Za-z0-9_.]*)\s*\]""", text):
            if name in constants:
                used.add(constants[name])
            else:
                unresolved.add(f"{path.name}: {name}")
        used |= {constants[c] for c in ("COLLECTION",) if c in constants and path.name == "request_log.py"}
    check(not unresolved, "every collection the resolver's code names is found (a literal or a module constant)",
          sorted(unresolved))
    granted = set(db_init.RESOLVER_PORTAL_COLLECTIONS) | set(db_init.LOG_COLLECTIONS) | {db_init.RECORDS}
    check(used and used <= granted, "the resolver's code uses only the collections its role grants",
          sorted(used - granted))
    check({"tenants", "domains", "settings", "branding", "forwarding_rules", "requests", "request_counts",
           "gs1resolver"} <= used,
          "the scan of the resolver's code finds the collections it is known to use", sorted(used))
    databases = set()
    for path in src.glob("*.py"):
        databases |= set(re.findall(r"""mongo\.cx\[\s*['"]([A-Za-z0-9_]+)['"]\s*\]""", path.read_text()))
    check(databases <= {"resolver_ce"}, "the resolver names no database but the records' and the two it is given",
          sorted(databases))


# --------------------------------------------------------------------------- settings and scripts
def settings_checks() -> None:
    example = (REPO / ".env.example").read_text()
    secrets = load(REPO / "portal", "example_secrets")
    for prefix, user, password in (("RESOLVER", "resolver_web", "resolver_web"),
                                   ("DATA_ENTRY", "resolver_data_entry", "resolver_data_entry")):
        check(re.search(rf"^{prefix}_DB_USERNAME={user}$", example, re.M)
              and re.search(rf"^{prefix}_DB_PASSWORD={password}$", example, re.M)
              and secrets.EXAMPLE_VALUES.get(f"{prefix}_DB_PASSWORD") == password,
              f".env.example: {prefix}_DB_USERNAME and _PASSWORD, the password one example_secrets.py refuses")
    install = (REPO / "scripts" / "install.sh").read_text()
    for name in ("RESOLVER_DB_PASSWORD", "DATA_ENTRY_DB_PASSWORD"):
        check(name in re.search(r'MANAGED_KEYS="([^"]*)"', install).group(1) and f"env_line {name} " in install
              and re.search(rf"{name} == {secrets.EXAMPLE_VALUES[name]}", install),
              f"installer: {name} written to .env, generated when missing or the example")
    rotate = (REPO / "scripts" / "rotate-secrets.sh").read_text()
    check(re.search(r"^ALL=\(.*\bresolver-db\b.*\bdata-entry-db\b.*\)", rotate, re.M)
          and "put RESOLVER_DB_PASSWORD" in rotate and "put DATA_ENTRY_DB_PASSWORD" in rotate,
          "rotation: resolver-db and data-entry-db among the secrets rotated by default")


def main() -> int:
    if not COMPOSE or not Path(COMPOSE).exists():
        print("FAIL COMPOSE_BIN is not set to a Docker Compose v2 binary")
        return 1
    for section in (compose_checks, dockerfile_checks, service_db_checks, db_init_checks, collections_checks,
                    settings_checks):
        try:
            section()
        except Exception as exc:          # a piece missing or changed: reported as a failure, the other sections run
            check(False, f"{section.__name__}: runs to the end", f"{type(exc).__name__}: {exc}")
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
