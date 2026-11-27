#!/usr/bin/env python3
"""
Development test for the supply chain (F-015; Documentation/adr/0033-supply-chain.md).

Checks, from the repository's files alone (no network, no Docker):
  * the Dockerfiles, docker-compose.yml and the workflows: every image taken from a registry is named by digest
    (name:tag@sha256:…), a stage of the same Dockerfile excepted;
  * every final image takes its distribution's security updates of the packages it holds (apt-get upgrade in the
    three Debian images, the database image's dist-upgrade, the proxy's apk upgrade), the package lists removed in
    the same layer, so that a correction published after the base image's digest still reaches the image;
  * the workflows and the composite action: every action is the repository's own (./…) or named by a 40-character
    commit with its release in a comment; every workflow states its permissions; checkout keeps no credentials;
  * no download is piped into a shell, no "npm init <initializer>" (it fetches and runs a package), npm installs only
    with "npm ci --ignore-scripts" from package-lock.json in the images;
  * the Python lock files (portal, resolver, data entry API, development tests): written by
    dev-tests/lock-dependencies.sh, each package once at one version with SHA-256 hashes, nothing else (no URL,
    no editable, no option that changes the index); every direct dependency of the .in file locked and allowed by its
    specifier; every service's lock inside the development tests' lock, at the same version and the same hashes;
  * pip in the images, the CI and the cloud session's hook installs a lock file with --require-hashes and --no-deps;
  * the npm lock files of the two toolkits: gs1encoder at the release docker-compose.yml names (x-gs1-syntax-engine),
    from the npm registry with a SHA-512 integrity, package.json naming that exact version; the image refuses a lock
    of another release;
  * Node.js copied into the resolver's and the data entry API's images where web_logic.py starts it;
  * Dependabot proposes updates for every directory with a lock file, a Dockerfile, the composition and the actions,
    against the development branch, and leaves gs1encoder alone; SECURITY.md says how to report privately;
  * the supply-chain workflow (step 2 of the ADR): on a change of a lock, a Dockerfile, the composition or a
    workflow, weekly, by hand and on a release; read-only but for the release job; pip-audit on the four Python
    locks and npm audit on the two npm locks; the five images built, scanned by Trivy against the reviewed list and
    described by a CycloneDX SBOM, kept as artefact and attached to the release; pip-audit from a lock with hashes,
    Trivy by version and SHA-256; every accepted vulnerability with a statement, a review date and an expiry within
    90 days; audit.py failing on a vulnerability with a correction, not on one without, honouring an accepted
    identifier or alias until its expiry, and on a report missing or unreadable.

Requirements: PyYAML, packaging (both in dev-tests/requirements.txt).
Run from anywhere:  python dev-tests/install/test_supply_chain.py
Exits with status 1 on any failure.
"""
import datetime
import importlib.util
import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = ["web_server/Dockerfile", "data_entry_server/Dockerfile", "portal/Dockerfile",
               "frontend_proxy_server/Dockerfile", "database_server/Dockerfile"]
SERVICE_LOCKS = ["portal/requirements.txt", "web_server/src/requirements.txt", "data_entry_server/src/requirements.txt"]
DEV_LOCK = "dev-tests/requirements.txt"
TOOLS_LOCK = ".github/supply-chain/requirements.txt"   # the supply-chain workflow's own tools, resolved on their own
WORKFLOW = ".github/workflows/supply-chain.yml"
ACCEPTED = ".github/supply-chain/accepted.yaml"
TOOLKITS = ["web_server/src/gs1-digitallink-toolkit", "data_entry_server/src/gs1-digitallink-toolkit"]
DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
results: list[tuple[bool, str]] = []


def check(condition, label: str, detail=None) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f"  → {detail}"))


def text(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def workflow_files() -> list[str]:
    files = sorted(str(p.relative_to(REPO)) for p in (REPO / ".github" / "workflows").glob("*.y*ml"))
    return files + sorted(str(p.relative_to(REPO)) for p in (REPO / ".github" / "actions").glob("*/action.y*ml"))


# ---------------------------------------------------------------------------------------------------------- images

def from_lines(dockerfile: str) -> list[tuple[str, str | None]]:
    """(image, stage name) of each FROM, continuation lines joined; --platform and similar flags dropped."""
    joined = re.sub(r"\\\n", " ", dockerfile)
    out = []
    for line in joined.splitlines():
        m = re.match(r"^\s*FROM\s+(.*)$", line, re.I)
        if not m:
            continue
        words = [w for w in m.group(1).split() if not w.startswith("--")]
        stage = words[2] if len(words) >= 3 and words[1].lower() == "as" else None
        out.append((words[0], stage))
    return out


def image_checks() -> None:
    for path in DOCKERFILES:
        stages: set[str] = set()
        froms = from_lines(text(path))
        check(froms, f"{path}: has FROM lines")
        for image, stage in froms:
            if image in stages:
                check(True, f"{path}: FROM {image} is a stage of the same file")
            else:
                check(DIGEST.match(image), f"{path}: FROM {image.split('@')[0]} named by digest", image)
            if stage:
                stages.add(stage)
        copies = re.findall(r"COPY\s+--from=(\S+)", text(path))
        for source in copies:
            known = source in stages or source in ("engine-tools", "git-dir") or DIGEST.match(source)
            check(known, f"{path}: COPY --from={source} is a stage, a named build context or an image by digest")
    compose = yaml.safe_load(text("docker-compose.yml"))
    for name, service in compose["services"].items():
        if "image" in service:
            check(DIGEST.match(service["image"]), f"docker-compose.yml: {name}'s image named by digest", service["image"])
    for path in workflow_files():
        doc = yaml.safe_load(text(path)) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for svc_name, svc in (job.get("services") or {}).items():
                check(DIGEST.match(str(svc.get("image", ""))), f"{path}: {job_name}'s service {svc_name} by digest",
                      svc.get("image"))
            container = job.get("container")
            if container:
                image = container if isinstance(container, str) else container.get("image", "")
                check(DIGEST.match(image), f"{path}: {job_name}'s container by digest", image)


def final_stage(dockerfile: str) -> str:
    """The last stage of a Dockerfile, continuation lines joined and comments dropped."""
    lines = [line for line in re.sub(r"\\\n", " ", dockerfile).splitlines() if not line.lstrip().startswith("#")]
    last = max(i for i, line in enumerate(lines) if re.match(r"^\s*FROM\s", line, re.I))
    return "\n".join(lines[last:])


SECURITY_UPDATES = {
    "web_server/Dockerfile": r"^RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/\*$",
    "data_entry_server/Dockerfile": r"^RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/\*$",
    "portal/Dockerfile": r"^RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/\*$",
    "database_server/Dockerfile": r"^RUN apt-get update -y && apt-get dist-upgrade -y$",
    "frontend_proxy_server/Dockerfile": r"^RUN apk upgrade --no-cache$",
}


def security_update_checks() -> None:
    check(set(SECURITY_UPDATES) == set(DOCKERFILES), "every image's Dockerfile has its security-update rule here")
    for path, rule in SECURITY_UPDATES.items():
        final = final_stage(text(path))
        check(re.search(rule, final, re.M), f"{path}: the final image takes its distribution's security updates of "
              "the packages it holds", rule)
        if "apt-get upgrade" in rule:
            run = re.search(r"^FROM\s.*?\n(.*?)^RUN apt-get update && apt-get upgrade", final, re.M | re.S)
            check(run and not re.search(r"^(COPY|ADD)\s", run.group(1), re.M),
                  f"{path}: the security updates run before the image's own files are copied")


# --------------------------------------------------------------------------------------------------------- actions

def steps_of(doc: dict) -> list[dict]:
    steps = list((doc.get("runs") or {}).get("steps") or [])
    for job in (doc.get("jobs") or {}).values():
        steps += job.get("steps") or []
    return steps


def action_checks() -> None:
    for path in workflow_files():
        raw = text(path)
        doc = yaml.safe_load(raw) or {}
        steps = steps_of(doc)
        uses = [s["uses"] for s in steps if "uses" in s]
        for ref in uses:
            if ref.startswith("./"):
                check((REPO / ref / "action.yml").exists(), f"{path}: local action {ref} exists")
                continue
            check(COMMIT.match(ref), f"{path}: {ref.split('@')[0]} named by commit", ref)
            line = next((l for l in raw.splitlines() if ref in l), "")
            check(re.search(r"#\s*v\d+(\.\d+)*\s*$", line), f"{path}: {ref.split('@')[0]}'s release in a comment",
                  line.strip())
        if "/workflows/" in path:
            check("permissions" in doc, f"{path}: states its permissions")
            check(all((s.get("with") or {}).get("persist-credentials") is False
                      for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")),
                  f"{path}: checkout keeps no credentials (persist-credentials: false)")


# ------------------------------------------------------------------------------------------------------- downloads

PIPED = re.compile(r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(-E\s+)?(ba|z|da)?sh\b")
NPM_INIT = re.compile(r"\bnpm\s+init\s+(?!-y\b|--yes\b)[^\s-]")


def scanned_files() -> list[str]:
    files = DOCKERFILES + workflow_files() + [".claude/hooks/session-start.sh", "docker-compose.yml"]
    files += sorted(str(p.relative_to(REPO)) for p in (REPO / "scripts").glob("*.sh"))
    files += ["portal/tools/build-syntax-engine.sh", "dev-tests/lock-dependencies.sh",
              ".github/supply-chain/install-trivy.sh"]
    return files


def download_checks() -> None:
    for path in scanned_files():
        body = re.sub(r"\\\n", " ", text(path))
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        check(not PIPED.search(code), f"{path}: no download piped into a shell", (PIPED.search(code) or [""])[0])
        check(not NPM_INIT.search(code), f"{path}: no npm init with an initializer", (NPM_INIT.search(code) or [""])[0])
    for path in DOCKERFILES:
        body = re.sub(r"\\\n", " ", text(path))
        runs = [l for l in body.splitlines() if re.match(r"^\s*RUN\b", l)]
        npm = [l for l in runs if re.search(r"\bnpm\s+(install|i|add|ci)\b", l)]
        check(all(re.search(r"\bnpm\s+ci\b", l) and "--ignore-scripts" in l for l in npm),
              f"{path}: npm only as 'npm ci --ignore-scripts'", npm)
        pip = [l for l in runs if re.search(r"\bpip3?\s+install\b", l)]
        check(all("--require-hashes" in l and "--no-deps" in l and re.search(r"-r\s+requirements\.txt\b", l)
                  for l in pip), f"{path}: pip installs requirements.txt with --require-hashes --no-deps", pip)
        if path.split("/")[0] in ("web_server", "data_entry_server", "portal"):
            check(pip, f"{path}: installs its Python packages with pip")
    for path in (".github/actions/dev-tests-setup/action.yml", ".claude/hooks/session-start.sh"):
        lines = [l for l in re.sub(r"\\\n", " ", text(path)).splitlines() if re.search(r"\bpip\s+install\b", l)]
        check(lines and all("--require-hashes" in l and "--no-deps" in l and f"-r {DEV_LOCK}" in l for l in lines),
              f"{path}: pip installs {DEV_LOCK} with --require-hashes --no-deps", lines)


# ------------------------------------------------------------------------------------------------------ Python locks

def parse_lock(path: str) -> dict[str, tuple[str, frozenset[str]]]:
    """name → (version, hashes) of a lock file; a line of another shape raises ValueError."""
    body = text(path)
    entries: dict[str, tuple[str, frozenset[str]]] = {}
    for block in re.sub(r"\\\n", " ", body).splitlines():
        line = block.split(" #")[0].strip() if not block.lstrip().startswith("#") else ""
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)\s*(;[^-]*)?((?:\s*--hash=sha256:[0-9a-f]{64})+)\s*$", line)
        if not m:
            raise ValueError(f"{path}: not 'name==version ; markers --hash=sha256:…': {line[:120]}")
        name = canonicalize_name(m.group(1))
        if name in entries:
            raise ValueError(f"{path}: {name} twice")
        entries[name] = (m.group(2), frozenset(re.findall(r"sha256:([0-9a-f]{64})", m.group(4))))
    return entries


def direct_requirements(path: str) -> list[Requirement]:
    out = []
    for raw in text(path).splitlines():
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-r "):
            continue
        out.append(Requirement(line))
    return out


def lock_checks() -> None:
    locks = {}
    for path in SERVICE_LOCKS + [DEV_LOCK, TOOLS_LOCK]:
        head = text(path).splitlines()[:2]
        check(len(head) == 2 and head[1].strip() == "#    dev-tests/lock-dependencies.sh",
              f"{path}: written by dev-tests/lock-dependencies.sh", head)
        try:
            locks[path] = parse_lock(path)
        except ValueError as exc:
            check(False, f"{path}: every line a pinned package with SHA-256 hashes", exc)
            continue
        check(locks[path] and all(h for _, h in locks[path].values()),
              f"{path}: every line a pinned package with SHA-256 hashes ({len(locks[path])} packages)")
        source = path.replace("requirements.txt", "requirements.in")
        reqs = direct_requirements(source)
        if path == DEV_LOCK:
            for inc in re.findall(r"^-r\s+(\S+)", text(source), re.M):
                reqs += direct_requirements(str((REPO / "dev-tests" / inc).resolve().relative_to(REPO)))
        missing = [str(r) for r in reqs if canonicalize_name(r.name) not in locks[path]]
        check(not missing, f"{source}: every direct dependency locked in {path}", missing)
        outside = [f"{r} → {locks[path][canonicalize_name(r.name)][0]}" for r in reqs
                   if canonicalize_name(r.name) in locks[path]
                   and not r.specifier.contains(locks[path][canonicalize_name(r.name)][0], prereleases=True)]
        check(not outside, f"{path}: every locked version allowed by {source}", outside)
    dev = locks.get(DEV_LOCK, {})
    for path in SERVICE_LOCKS:
        if path not in locks:
            continue
        differ = [f"{n} {v}" + ("" if n not in dev else f" (tests: {dev[n][0]})")
                  for n, (v, h) in locks[path].items() if dev.get(n) != (v, h)]
        check(dev and not differ, f"{path}: every package at the version and hashes of {DEV_LOCK}", differ)


# -------------------------------------------------------------------------------------------------------- npm locks

def engine_release() -> str:
    m = re.search(r'^x-gs1-syntax-engine: *&gs1-syntax-engine *"([^"]+)"', text("docker-compose.yml"), re.M)
    return m.group(1) if m else ""


def npm_checks() -> None:
    release = engine_release()
    check(release, "docker-compose.yml: x-gs1-syntax-engine names a release", release)
    locks = []
    for toolkit in TOOLKITS:
        package = json.loads(text(f"{toolkit}/package.json"))
        lock = json.loads(text(f"{toolkit}/package-lock.json"))
        locks.append(lock)
        deps = package.get("dependencies") or {}
        check(deps == {"gs1encoder": release}, f"{toolkit}/package.json: gs1encoder at exactly {release}, nothing else",
              deps)
        check(package.get("private") is True and not package.get("devDependencies"),
              f"{toolkit}/package.json: private, without development dependencies")
        check(lock.get("lockfileVersion", 0) >= 2, f"{toolkit}/package-lock.json: lockfileVersion 2 or later")
        entries = {k: v for k, v in (lock.get("packages") or {}).items() if k}
        check(entries.get("node_modules/gs1encoder", {}).get("version") == release,
              f"{toolkit}/package-lock.json: gs1encoder {release}", entries.get("node_modules/gs1encoder"))
        bad = [k for k, v in entries.items()
               if not re.match(r"^sha512-[A-Za-z0-9+/]{86}==$", v.get("integrity", ""))
               or not str(v.get("resolved", "")).startswith("https://registry.npmjs.org/")]
        check(entries and not bad, f"{toolkit}/package-lock.json: every package from the npm registry with a SHA-512 "
              "integrity", bad)
        root = (lock.get("packages") or {}).get("", {})
        check(root.get("dependencies") == deps, f"{toolkit}/package-lock.json: in step with package.json")
    check(len(locks) == 2 and locks[0]["packages"].get("node_modules/gs1encoder")
          == locks[1]["packages"].get("node_modules/gs1encoder"), "the two toolkits lock the same gs1encoder")
    for path in DOCKERFILES[:2]:
        body = text(path)
        check('packages["node_modules/gs1encoder"].version' in body and '"$locked" != "$GS1_SYNTAX_ENGINE_RELEASE"' in body,
              f"{path}: the build refuses a package-lock.json of another release than docker-compose.yml's")
        check(re.search(r"^COPY --from=node /usr/local/bin/node /usr/bin/node$", body, re.M)
              and re.search(r"^COPY --from=node /toolkit/node_modules /app/gs1-digitallink-toolkit/node_modules$",
                            body, re.M),
              f"{path}: node and the locked package copied from the stage 'node'")
    logic = text("web_server/src/web_logic.py")
    check(re.findall(r'^NODE_PATH = "([^"]+)"$', logic, re.M) == ["/usr/bin/node"] and "node_path" not in logic,
          "web_logic.py starts node where the image puts it (/usr/bin/node)")
    check(re.findall(r'^TOOLKIT_DIR = "([^"]+)"$', logic, re.M) == ["/app/gs1-digitallink-toolkit"]
          and "ADD src/gs1-digitallink-toolkit /app/gs1-digitallink-toolkit" in text("web_server/Dockerfile"),
          "web_logic.py runs the toolkit's scripts where the image puts them (/app/gs1-digitallink-toolkit)")


# ----------------------------------------------------------------------------------------------- updates and policy

def policy_checks() -> None:
    config = yaml.safe_load(text(".github/dependabot.yml"))
    updates = config.get("updates") or []
    covered: dict[str, set[str]] = {}
    for u in updates:
        dirs = u.get("directories") or [u.get("directory")]
        covered.setdefault(u["package-ecosystem"], set()).update(d.rstrip("/") or "/" for d in dirs if d)
        check(u.get("target-branch") == "gs1br/develop", f"dependabot.yml: {u['package-ecosystem']} against gs1br/develop")
    wanted = {"pip": {"/" + str(Path(p).parent) for p in SERVICE_LOCKS + [DEV_LOCK, TOOLS_LOCK]},
              "npm": {"/" + t for t in TOOLKITS},
              "docker": {"/" + str(Path(p).parent) for p in DOCKERFILES},
              "docker-compose": {"/"},
              "github-actions": {"/", "/.github/actions/dev-tests-setup"}}
    for ecosystem, dirs in wanted.items():
        check(dirs <= covered.get(ecosystem, set()), f"dependabot.yml: {ecosystem} for {sorted(dirs)}",
              sorted(dirs - covered.get(ecosystem, set())))
    npm = next((u for u in updates if u["package-ecosystem"] == "npm"), {})
    check(any(i.get("dependency-name") == "gs1encoder" for i in npm.get("ignore") or []),
          "dependabot.yml: gs1encoder left to the engine's weekly check")
    security = text("SECURITY.md")
    check("private vulnerability reporting" in security and "Do not open a public issue" in security,
          "SECURITY.md: reports go through GitHub's private vulnerability reporting, not public issues")


# ------------------------------------------------------------------------------------- scanning and SBOM (step 2)

def run_text(job: dict) -> str:
    return "\n".join(re.sub(r"\\\n\s*", " ", str(s.get("run", ""))) for s in job.get("steps") or [])


def workflow_checks() -> None:
    doc = yaml.safe_load(text(WORKFLOW))
    on = doc.get(True) or doc.get("on") or {}          # PyYAML reads the key "on" as True
    paths = set((on.get("push") or {}).get("paths") or [])
    wanted = {"**/requirements*.txt", "**/package-lock.json", "**/Dockerfile", "docker-compose.yml",
              ".github/workflows/**", ".github/supply-chain/**"}
    check(wanted <= paths, f"{WORKFLOW}: runs on a push that changes a lock, a Dockerfile, the composition or a "
          "workflow", sorted(wanted - paths))
    check(set((on.get("pull_request") or {}).get("paths") or []) == paths, f"{WORKFLOW}: the same paths on a pull request")
    check(on.get("schedule") and "workflow_dispatch" in on, f"{WORKFLOW}: weekly and by hand")
    check((on.get("release") or {}).get("types") == ["published"], f"{WORKFLOW}: on a published release")
    check(doc.get("permissions") == {"contents": "read"}, f"{WORKFLOW}: read-only by default", doc.get("permissions"))
    jobs = doc.get("jobs") or {}
    writers = {name: job.get("permissions") for name, job in jobs.items() if "permissions" in job}
    check(writers == {"release-sbom": {"contents": "write"}}, f"{WORKFLOW}: only the release job writes, and only "
          "contents", writers)
    check(str(jobs.get("release-sbom", {}).get("if", "")).replace(" ", "") == "github.event_name=='release'"
          and all(str(j.get("if", "")).replace(" ", "") == "github.event_name!='release'"
                  for n, j in jobs.items() if n != "release-sbom"),
          f"{WORKFLOW}: the release job runs on a release only, the scans on everything else")
    locks = run_text(jobs.get("locks", {}))
    check(re.search(r'pip"? install --require-hashes --no-deps -r \.github/supply-chain/requirements\.txt', locks),
          f"{WORKFLOW}: pip-audit installed from its lock with hashes")
    for lock in SERVICE_LOCKS + [DEV_LOCK]:
        check(lock in locks and "pip-audit\" -r \"$lock\" --require-hashes --disable-pip" in locks,
              f"{WORKFLOW}: pip-audit scans {lock}")
    for toolkit in TOOLKITS:
        check(toolkit in locks and "npm audit --package-lock-only --json" in locks, f"{WORKFLOW}: npm audit scans {toolkit}")
    check(f"audit.py --accepted {ACCEPTED}" in locks and "reports/*.json" in locks,
          f"{WORKFLOW}: every report read by audit.py against {ACCEPTED}")
    images = set(str((doc.get("env") or {}).get("IMAGES", "")).split())
    compose = yaml.safe_load(text("docker-compose.yml"))["services"]
    built = {n: json.dumps(s["build"], sort_keys=True) for n, s in compose.items() if "build" in s}
    uncovered = [n for n, b in built.items() if n not in images and b not in {built.get(i) for i in images}]
    check(len(images) == 5 and images <= set(built) and not uncovered,
          f"{WORKFLOW}: the five images, every image docker-compose.yml builds", sorted(images) + uncovered)
    for name in ("images", "release-sbom"):
        body = run_text(jobs.get(name, {}))
        check(".github/supply-chain/install-trivy.sh" in body and "docker compose build $IMAGES" in body
              and "for service in $IMAGES" in body and "--format cyclonedx" in body,
              f"{WORKFLOW}: {name} builds the five images with Trivy by hash and writes a CycloneDX SBOM of each")
    gate = run_text(jobs.get("images", {}))
    check(re.search(r"trivy\" image [^\n]*--severity HIGH,CRITICAL --ignore-unfixed[^\n]*--ignorefile " + re.escape(ACCEPTED)
                    + r" --exit-code 1", gate), f"{WORKFLOW}: each image fails on HIGH or CRITICAL with a correction, "
          f"against {ACCEPTED}")
    uploads = [s for s in jobs.get("images", {}).get("steps") or [] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    check(uploads and "sbom/" in str(uploads[0].get("with", {}).get("path")) and uploads[0].get("if") == "always()",
          f"{WORKFLOW}: the SBOMs and reports kept as the run's artefact")
    check(re.search(r'gh release upload "\$TAG" sbom/\*\.cdx\.json', run_text(jobs.get("release-sbom", {}))),
          f"{WORKFLOW}: the SBOMs attached to the release")
    trivy = text(".github/supply-chain/install-trivy.sh")
    check(re.search(r"^TRIVY_VERSION=\d+\.\d+\.\d+$", trivy, re.M) and re.search(r"^TRIVY_SHA256=[0-9a-f]{64}$", trivy, re.M)
          and "sha256sum --check --strict" in trivy and "https://github.com/aquasecurity/trivy/releases/download/" in trivy,
          "install-trivy.sh: Trivy from its release, by version, refused unless its SHA-256 matches")


def accepted_checks() -> None:
    doc = yaml.safe_load(text(ACCEPTED))
    entries = doc.get("vulnerabilities")
    check(isinstance(entries, list), f"{ACCEPTED}: a list of vulnerabilities (Trivy's ignore file format)")
    bad = []
    for entry in entries or []:
        ident = str(entry.get("id", ""))
        reviewed, expires = entry.get("reviewed"), entry.get("expired_at")
        dated = isinstance(reviewed, datetime.date) and isinstance(expires, datetime.date)
        if not (re.match(r"^(CVE-\d{4}-\d+|GHSA(-[0-9a-z]{4}){3}|PYSEC-\d{4}-\d+)$", ident)
                and str(entry.get("statement", "")).strip() and dated and 0 < (expires - reviewed).days <= 90):
            bad.append(entry)
    check(isinstance(entries, list) and not bad, f"{ACCEPTED}: every entry with an advisory, a statement, a review date "
          f"and an expiry within 90 days ({len(entries or [])} entries)", bad)


def load_audit():
    sys.dont_write_bytecode = True        # no __pycache__ left in .github/supply-chain
    spec = importlib.util.spec_from_file_location("supply_chain_audit", REPO / ".github" / "supply-chain" / "audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_checks() -> None:
    audit = load_audit()
    pip_fix = {"dependencies": [{"name": "pkg", "version": "1.0", "vulns": [
        {"id": "PYSEC-2026-1", "fix_versions": ["1.1"], "aliases": ["CVE-2026-11111", "GHSA-aaaa-bbbb-cccc"]}]}]}
    pip_nofix = {"dependencies": [{"name": "pkg", "version": "1.0", "vulns": [
        {"id": "PYSEC-2026-2", "fix_versions": [], "aliases": []}]}, {"name": "other", "version": "2", "vulns": []}]}
    npm_fix = {"auditReportVersion": 2, "vulnerabilities": {"minimist": {"range": "<=1.2.5", "fixAvailable": True,
               "via": [{"source": 1, "url": "https://github.com/advisories/GHSA-xvch-5gv4-984h"}]},
               "dependant": {"range": "1", "fixAvailable": True, "via": ["minimist"]}}}
    npm_nofix = {"auditReportVersion": 2, "vulnerabilities": {"minimist": {"range": "<=1.2.5", "fixAvailable": False,
                 "via": [{"source": 1, "url": "https://github.com/advisories/GHSA-xvch-5gv4-984h"}]}}}
    clean_npm = {"auditReportVersion": 2, "vulnerabilities": {}}

    def run(reports: list, accepted: str = "vulnerabilities: []\n", today: str = "2026-11-21") -> int:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, report in enumerate(reports):
                path = Path(tmp) / f"r{i}.json"
                if report is not None:
                    path.write_text(report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
                paths.append(str(path))
            (Path(tmp) / "accepted.yaml").write_text(accepted, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                return audit.main(["--accepted", str(Path(tmp) / "accepted.yaml"), "--today", today] + paths)

    def accept(ident: str, expires: str = "2027-01-01") -> str:
        return (f"vulnerabilities:\n  - id: {ident}\n    statement: test\n    reviewed: 2026-11-21\n"
                f"    expired_at: {expires}\n")

    check(run([pip_nofix, clean_npm]) == 0, "audit.py: a vulnerability without a correction is listed, not failed")
    check(run([pip_fix]) == 1, "audit.py: a Python vulnerability with a correction fails")
    check(run([pip_fix], accept("CVE-2026-11111")) == 0, "audit.py: an accepted alias of the advisory counts")
    check(run([pip_fix], accept("pysec-2026-1")) == 0, "audit.py: an accepted identifier counts, in any case")
    check(run([pip_fix], accept("CVE-2026-11111", "2026-11-20")) == 1, "audit.py: an expired acceptance no longer counts")
    check(run([pip_fix], accept("CVE-2026-11111", "2026-11-21")) == 0, "audit.py: an acceptance counts on its expiry day")
    check(run([pip_fix], accept("CVE-2026-11111").replace("    statement:", "    paths: [\"usr/bin/x\"]\n    statement:"))
          == 1, "audit.py: an entry limited to an image's paths does not accept a lock file's vulnerability")
    check(run([npm_fix]) == 1, "audit.py: an npm vulnerability with a correction fails")
    check(run([npm_nofix]) == 0, "audit.py: an npm vulnerability without a correction is listed, not failed")
    check(run([npm_fix], accept("GHSA-xvch-5gv4-984h")) == 1,
          "audit.py: a package affected only through another (via a name) still fails when it can be corrected")
    check(run([clean_npm, None]) == 2, "audit.py: a missing report fails as unreadable, never as clean")
    check(run(["{not json"]) == 2 and run([{"something": "else"}]) == 2, "audit.py: an unreadable report fails")


def main() -> int:
    for section in (image_checks, security_update_checks, action_checks, download_checks, lock_checks, npm_checks, policy_checks,
                    workflow_checks, accepted_checks, audit_checks):
        try:
            section()
        except Exception as exc:          # a piece missing or changed: reported as a failure, the other sections run
            check(False, f"{section.__name__}: runs to the end", f"{type(exc).__name__}: {exc}")
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
