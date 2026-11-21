#!/usr/bin/env python3
"""
Development test for the supply chain (F-015; Documentation/adr/0033-supply-chain.md).

Checks, from the repository's files alone (no network, no Docker):
  * the Dockerfiles, docker-compose.yml and the workflows: every image taken from a registry is named by digest
    (name:tag@sha256:…), a stage of the same Dockerfile excepted;
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
    against the development branch, and leaves gs1encoder alone; SECURITY.md says how to report privately.

Requirements: PyYAML, packaging (both in dev-tests/requirements.txt).
Run from anywhere:  python dev-tests/install/test_supply_chain.py
Exits with status 1 on any failure.
"""
import json
import re
import sys
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[2]
DOCKERFILES = ["web_server/Dockerfile", "data_entry_server/Dockerfile", "portal/Dockerfile",
               "frontend_proxy_server/Dockerfile", "database_server/Dockerfile"]
SERVICE_LOCKS = ["portal/requirements.txt", "web_server/src/requirements.txt", "data_entry_server/src/requirements.txt"]
DEV_LOCK = "dev-tests/requirements.txt"
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
    files += ["portal/tools/build-syntax-engine.sh", "dev-tests/lock-dependencies.sh"]
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
    for path in SERVICE_LOCKS + [DEV_LOCK]:
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
    check(re.findall(r'node_path = "([^"]+)"', logic) and set(re.findall(r'node_path = "([^"]+)"', logic)) == {"/usr/bin/node"},
          "web_logic.py starts node where the image puts it (/usr/bin/node)")


# ----------------------------------------------------------------------------------------------- updates and policy

def policy_checks() -> None:
    config = yaml.safe_load(text(".github/dependabot.yml"))
    updates = config.get("updates") or []
    covered: dict[str, set[str]] = {}
    for u in updates:
        dirs = u.get("directories") or [u.get("directory")]
        covered.setdefault(u["package-ecosystem"], set()).update(d.rstrip("/") or "/" for d in dirs if d)
        check(u.get("target-branch") == "gs1br/develop", f"dependabot.yml: {u['package-ecosystem']} against gs1br/develop")
    wanted = {"pip": {"/" + str(Path(p).parent) for p in SERVICE_LOCKS + [DEV_LOCK]},
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


def main() -> int:
    for section in (image_checks, action_checks, download_checks, lock_checks, npm_checks, policy_checks):
        try:
            section()
        except Exception as exc:          # a piece missing or changed: reported as a failure, the other sections run
            check(False, f"{section.__name__}: runs to the end", f"{type(exc).__name__}: {exc}")
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
