"""The About page's facts (Documentation/adr/0024-name-and-about.md): which version runs, where its code lives, what it
is made of.

The version is written when the portal's image is built: a stage of portal/Dockerfile runs this module as a script
("python about.py write /version.json") in a copy of the checkout's .git and the final image receives version.json
alone. Without that file (the development tests, a copy without .git) the portal asks git in its own folder; without
git either, the version is unknown and the documents are linked on the official repository's default branch. Nothing
here stops the portal: a missing or broken file, an absent git or a strange address all give "unknown".

Only the standard library is used, so the build stage needs no package of the portal's.
"""
import ipaddress
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, "version.json")
COMPONENTS_FILE = os.path.join(HERE, "third_party.json")
# Where the documents are linked when the running checkout is not known (ADR 0024, section 2.4, point 10)
OFFICIAL_REPOSITORY = "https://github.com/gs1/GS1_DigitalLink_Resolver_CE"
DEFAULT_BRANCH = "master"
GROUPS = ("gs1", "platform", "libraries", "data")

_SCP = re.compile(r"^(?:[^@/\s]+@)?([A-Za-z0-9.-]+):(?!//)(.+)$")      # git@host:owner/repo.git
_HASH = re.compile(r"^[0-9a-f]{7,64}$")


def public_address(url: str | None) -> str | None:
    """The checkout's origin as a public https:// address: an ssh or scp-like address rewritten, user names, passwords
    and tokens removed, the .git suffix dropped. None for anything that is not a public host (a local path, localhost,
    an IP address, a name without a dot) or not an address at all: the caller then uses the official repository."""
    text = (url or "").strip()
    if not text or any(c.isspace() for c in text):
        return None
    scp = _SCP.match(text)
    if scp and "://" not in text:
        host, path = scp.group(1), scp.group(2)
    else:
        try:
            parts = urlsplit(text)
        except ValueError:
            return None
        if parts.scheme not in ("https", "http", "ssh", "git", "git+ssh"):
            return None
        host, path = parts.hostname or "", parts.path
    host = host.lower().rstrip(".")
    path = re.sub(r"\.git/?$", "", path.strip("/")).strip("/")
    if not host or "." not in host or host == "localhost" or host.endswith(".localhost") or not path:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9._~/-]+", path) or ".." in path.split("/"):
        return None
    return f"https://{host}/{path}"


def _git(*args: str, cwd: str = HERE) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def from_git(cwd: str = HERE) -> dict:
    """The version, commit, date and public repository address of the checkout git finds from cwd; {} without one."""
    head = _git("log", "-1", "--format=%H %cI", cwd=cwd)
    if not head or " " not in head:
        return {}
    commit, date = head.split(" ", 1)
    return clean({"version": _git("describe", "--tags", "--always", cwd=cwd), "commit": commit, "date": date,
                  "repository": public_address(_git("remote", "get-url", "origin", cwd=cwd))})


def clean(data) -> dict:
    """Only the four expected fields, each a short string of the expected shape; anything else dropped."""
    if not isinstance(data, dict):
        return {}
    out = {}
    version = data.get("version")
    if isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", version):
        out["version"] = version
    commit = data.get("commit")
    if isinstance(commit, str) and _HASH.match(commit.lower()):
        out["commit"] = commit.lower()
    date = data.get("date")
    if isinstance(date, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT[0-9:.+Z-]{8,20}", date):
        out["date"] = date
    repository = data.get("repository")
    if isinstance(repository, str):
        address = public_address(repository)
        if address:
            out["repository"] = address
    return out


@lru_cache(maxsize=1)
def build() -> dict:
    """The running version: version.json written at the image's build, else git in the portal's folder, else {}."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            found = clean(json.load(fh))
        if found.get("commit"):
            return found
    except (OSError, ValueError):
        pass
    return from_git()


@lru_cache(maxsize=1)
def components() -> list:
    """The third-party components and data of the page's 'Made with' (portal/third_party.json), in its order."""
    try:
        with open(COMPONENTS_FILE, encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        return []
    keep = ("name", "group", "licence", "url")
    return [{k: str(item[k]) for k in keep} for item in items
            if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in keep) and item["group"] in GROUPS]


def facts(operator: str = "") -> dict:
    """What GET /portal/api/about answers (ADR 0024, section 2.4, point 11): no secret, setting or host of its own."""
    found = build()
    return {"version": found.get("version"), "commit": found.get("commit"), "date": found.get("date"),
            "repository": found.get("repository") or OFFICIAL_REPOSITORY, "operator": operator or None,
            "components": components()}


def write(path: str) -> dict:
    """The build stage's step: version.json from git in the current folder; {} (and the portal says 'unknown') when
    git finds nothing, so a build never fails for it."""
    found = from_git(os.getcwd())
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(found, fh)
    return found


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "write":
        print(json.dumps(write(sys.argv[2])))
    else:
        sys.exit("usage: python about.py write <path of version.json>")
