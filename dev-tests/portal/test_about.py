"""
The About page (Documentation/adr/0024-name-and-about.md): the version written at the image's build (version.json),
read back only in its expected shape, git asked in the portal's folder without it, "unknown" without git; the
repository's address made public (ssh and scp-like addresses rewritten, user names, passwords and tokens removed, local
paths, localhost and IP addresses refused for the official repository); GET /portal/api/about for anyone with exactly
its six fields; the page, its script and the links to it (user menu before Options, sign-in page, home page);
portal/third_party.json in step with Documentation/third-party.md; the texts of every language.

  pip install -r portal/requirements.txt mongomock
  python dev-tests/portal/test_about.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
REPO = os.path.join(PORTAL, "..")
CONFIG = tempfile.mkdtemp()
sys.path[:0] = [HERE, PORTAL]

os.environ.update(DATA_ENTRY_URL="http://127.0.0.1:9/api", SESSION_TOKEN="tok-about-secret",
                  PORTAL_CONFIG_DIR=CONFIG, PORTAL_ORIGIN="https://id.example.org", PORTAL_COOKIE_SECURE="false",
                  RESOLVER_PUBLIC_URL="https://id.example.org", RESOLVER_ORG_NAME="Example Operator")
os.environ.setdefault("PORTAL_DB_URI", "mongomock://")
os.environ.setdefault("PORTAL_DB_NAME", f"devtest_about_{os.getpid()}")
os.environ["PORTAL_WORKER"] = "external"
os.environ["PORTAL_MONITOR_MINUTES"] = "0"

import about  # noqa: E402
import app as portal  # noqa: E402

failures = []
LANGS = ("pt-BR", "en-GB", "es", "fr", "de", "it", "tr", "zh-Hans", "ja", "ko", "hi", "ar")
OFFICIAL = "https://github.com/gs1/GS1_DigitalLink_Resolver_CE"


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ the repository's public address
cases = {
    "git@github.com:acme/resolver.git": "https://github.com/acme/resolver",
    "ssh://git@github.com/acme/resolver.git": "https://github.com/acme/resolver",
    "ssh://git@gitlab.example.com:2222/group/sub/resolver.git": "https://gitlab.example.com/group/sub/resolver",
    "https://github.com/acme/resolver": "https://github.com/acme/resolver",
    "https://github.com/acme/resolver.git/": "https://github.com/acme/resolver",
    "http://git.example.org/acme/resolver": "https://git.example.org/acme/resolver",
    "https://x-access-token:ghp_SECRET123@github.com/acme/resolver.git": "https://github.com/acme/resolver",
    "https://user:password@GitHub.com/acme/resolver": "https://github.com/acme/resolver",
    "https://oauth2:glpat-SECRET@gitlab.com/acme/resolver.git": "https://gitlab.com/acme/resolver",
}
wrong = {u: about.public_address(u) for u, want in cases.items() if about.public_address(u) != want}
check(f"public address: ssh and scp-like rewritten, .git dropped, https, credentials removed ({len(cases)} cases)",
      not wrong, wrong)
check("…no user name, password or token survives", not any(
      s in (about.public_address(u) or "") for u in cases for s in ("SECRET", "password", "user", "git@", "oauth2")))
refused = ["", None, "   ", "/srv/git/resolver", "file:///srv/git/resolver", "../resolver",
           "http://local_proxy@127.0.0.1:41000/git/acme/resolver", "https://localhost/acme/resolver",
           "https://[::1]/acme/resolver", "https://10.0.0.5/acme/resolver", "https://gitserver/acme/resolver",
           "https://github.com/", "https://github.com/acme/../../etc", "https://github.com/acme/re solver",
           "ftp://github.com/acme/resolver", "javascript:alert(1)", "https://github.com/acme/<script>",
           "C:\\repos\\resolver"]
let_through = {u: about.public_address(u) for u in refused if about.public_address(u) is not None}
check(f"…local paths, localhost, IP addresses, single names, odd schemes and characters refused ({len(refused)})",
      not let_through, let_through)

# ------------------------------------------------------------------ what version.json may hold
good = {"version": "v3.1.1-42-g1a2b3c4", "commit": "1A2B3C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F9A0B",
        "date": "2026-11-15T16:59:34+00:00", "repository": "git@github.com:acme/resolver.git", "secret": "x"}
cleaned = about.clean(good)
check("version.json read back: four fields, the commit in lower case, the address made public, nothing else",
      cleaned == {"version": "v3.1.1-42-g1a2b3c4", "commit": good["commit"].lower(), "date": good["date"],
                  "repository": "https://github.com/acme/resolver"}, cleaned)
bad = about.clean({"version": "<b>1</b>", "commit": "not-a-hash", "date": "yesterday",
                   "repository": "http://127.0.0.1/x"})
check("…values of another shape dropped (markup, a non-hash, a free date, a local address)", bad == {}, bad)
check("…something that is not an object gives nothing", about.clean([1, 2]) == {} and about.clean("x") == {})


def repo_with_tag(tmp):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                            "GIT_CONFIG_GLOBAL": os.devnull})
    git("init", "-q")
    with open(os.path.join(tmp, "f.txt"), "w") as fh:
        fh.write("x")
    git("add", "f.txt")
    git("commit", "-q", "-m", "first")
    git("tag", "v9.8.7")
    git("remote", "add", "origin", "https://x-access-token:ghp_TOKEN@github.com/acme/resolver.git")


with tempfile.TemporaryDirectory() as tmp:
    repo_with_tag(tmp)
    found = about.from_git(tmp)
    check("from git: the tag as the version, the full commit, its date and the origin without its token",
          found.get("version") == "v9.8.7" and re.fullmatch(r"[0-9a-f]{40}", found.get("commit", "")) is not None
          and found.get("date", "").startswith("20") and found.get("repository") == "https://github.com/acme/resolver",
          found)
    target = os.path.join(tmp, "version.json")
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        written = about.write(target)
    finally:
        os.chdir(cwd)
    check("the build stage's step writes version.json from the checkout",
          json.load(open(target)) == written == found, written)

    # build(): version.json first, else git in the portal's folder
    original_file, original_git = about.VERSION_FILE, about.from_git
    try:
        about.VERSION_FILE = target
        about.build.cache_clear()
        check("build(): version.json written at the image's build is what the portal shows",
              about.build() == found, about.build())
        about.from_git = lambda cwd=None: {"commit": "f" * 40, "version": "from-git"}
        with open(target, "w") as fh:
            fh.write("{broken")
        about.build.cache_clear()
        check("…a broken file: git in the portal's folder instead, the portal starts",
              about.build().get("version") == "from-git")
        with open(target, "w") as fh:
            json.dump({"version": "v1"}, fh)
        about.build.cache_clear()
        check("…a file without a commit: git instead", about.build().get("version") == "from-git")
        about.VERSION_FILE = os.path.join(tmp, "absent.json")
        about.from_git = lambda cwd=None: {}
        about.build.cache_clear()
        facts = about.facts("")
        check("…no file and no git: version unknown, the official repository linked, no operator",
              facts["version"] is None and facts["commit"] is None and facts["date"] is None
              and facts["repository"] == OFFICIAL and facts["operator"] is None, facts)
    finally:
        about.VERSION_FILE, about.from_git = original_file, original_git
        about.build.cache_clear()

with tempfile.TemporaryDirectory() as tmp:
    check("from git: a folder outside any checkout gives nothing", about.from_git(tmp) == {})
    target = os.path.join(tmp, "version.json")
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        about.write(target)
    finally:
        os.chdir(cwd)
    check("…and the build stage then writes {} (the build never fails for it)", json.load(open(target)) == {})
    real = about._git
    about._git = lambda *a, **k: None
    try:
        check("…no git installed: nothing, no error", about.from_git(PORTAL) == {})
    finally:
        about._git = real

# ------------------------------------------------------------------ the API and the page, for anyone
anyone = portal.app.test_client()
r = anyone.get("/portal/api/about")
data = r.get_json() or {}
check("GET /portal/api/about for anyone: 200 with exactly version, commit, date, repository, operator, components",
      r.status_code == 200 and set(data) == {"version", "commit", "date", "repository", "operator", "components"},
      (r.status_code, sorted(data)))
check("…the operator's name (RESOLVER_ORG_NAME)", data.get("operator") == "Example Operator", data.get("operator"))
check("…the development checkout's commit, found by git in the portal's folder",
      re.fullmatch(r"[0-9a-f]{40}", data.get("commit") or "") is not None, data.get("commit"))
check("…a public https:// repository address", (data.get("repository") or "").startswith("https://"),
      data.get("repository"))
body = r.get_data(as_text=True)
check("…no secret or setting in the answer", "tok-about-secret" not in body and "mongomock" not in body
      and "PORTAL_" not in body and "127.0.0.1" not in body)
hits = about.build.cache_info().hits
check("…read once, not asked of git at every request", anyone.get("/portal/api/about").get_json() == data
      and about.build.cache_info().hits == hits + 1)

r = anyone.get("/portal/about")
html = r.get_data(as_text=True)
check("the page /portal/about for anyone, with its own script, the footer's notice and the link to the privacy notice",
      r.status_code == 200 and '<script src="about.js"></script>' in html and 'data-page="about"' in html
      and 'data-i18n="footer.notice"' in html and '<a href="privacy"' in html, r.status_code)
check("…its script without signing in", anyone.get("/portal/about.js").status_code == 200)
check("…the software's own name in the heading, not replaced by an operator's title (no class product there)",
      '<span class="about-name">GS1 Digital Link Resolver Suite</span>' in html)
script = read("portal", "static", "about.js")
check("…the documents linked at the running commit, else the default branch",
      "/blob/${ref}/" in script and 'data.commit || "master"' in script and "LICENSE" in script
      and "Documentation/third-party.md" in script)
check("…values written as text and only https addresses as links (no innerHTML)",
      "innerHTML" not in script and "^https:\\/\\/" in script)

# ------------------------------------------------------------------ the links to it
index = read("portal", "static", "index.html")
item = re.search(r'<a class="([^"]*)" role="menuitem" href="/portal/about" id="menu-about">', index)
check("user menu: About for every role (a nav-item, so the sidebar copies it), before Options",
      item is not None and "nav-item" in item.group(1) and "needs-" not in item.group(1)
      and index.index('id="menu-about"') < index.index('id="menu-options"') and 'data-i18n="menu.about"' in index)
check("sign-in page: About beside the privacy notice in the footer",
      '<a href="about" data-i18n="footer.about"></a> · <a href="privacy"' in read("portal", "static", "login.html"))
check("home page: About beside the privacy notice in the footer",
      '<a href="/portal/about" data-i18n="footer.about">' in read("frontend_proxy_server", "home", "index.html"))
pages = read("web_server", "src", "web_pages.py") + read("web_server", "src", "landing.py")
check("the resolver's pages do not link it (they belong to the brand owner's product)", "/portal/about" not in pages)

# ------------------------------------------------------------------ third_party.json and third-party.md
items = json.loads(read("portal", "third_party.json"))
check("third_party.json: name, group, licence and an https address for each, four groups, no duplicates",
      all(set(i) == {"name", "group", "licence", "url"} and i["group"] in about.GROUPS
          and i["url"].startswith("https://") and i["name"] and i["licence"] for i in items)
      and {i["group"] for i in items} == set(about.GROUPS) and len({i["name"] for i in items}) == len(items),
      [i for i in items if i.get("group") not in about.GROUPS])
check("…served whole by the API", len(data.get("components", [])) == len(items))
doc = read("Documentation", "third-party.md")
plain = re.sub(r"[*`]", "", doc)
absent = [i["name"] for i in items if i["name"] not in plain]
check("…every component named in Documentation/third-party.md", not absent, absent)
rows = []
for heading in ("## Components installed or shipped with it", "## Data and services from outside"):
    section = plain.split(heading, 1)[1].split("\n## ", 1)[0]
    rows += [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| ---")][1:]
NOT_COMPONENTS = ("Google Maps",)      # a link people may follow, nothing the software is made of
uncovered = [r.split("|")[1].strip() for r in rows
             if not any(n in r for n in NOT_COMPONENTS) and not any(i["name"] in r for i in items)]
check(f"…and every row of its tables of components and data in the file ({len(rows)} rows)", rows and not uncovered,
      uncovered)

# ------------------------------------------------------------------ texts
keys = sorted(set(re.findall(r'data-i18n="([^"]+)"', read("portal", "static", "about.html")))
              | set(re.findall(r'"(about\.[A-Za-z.]+)"', script))
              | {f"about.group.{g}" for g in about.GROUPS} | {"menu.about", "footer.about"})
i18n = read("portal", "static", "i18n.js")
start = i18n.index("const CATALOGUE = {")
missing = []
for tag in ("pt-BR", "en-GB"):
    block = i18n[i18n.index(f'    "{tag}": {{', start):]
    block = block[:block.index("\n    }")]
    missing += [(tag, k) for k in keys if f'      "{k}":' not in block]
for tag in LANGS[2:]:
    texts = json.loads(read("portal", "static", "locales", tag + ".json"))
    missing += [(tag, k) for k in keys if not texts.get(k)]
check(f"every text of the page and its links in the twelve languages ({len(keys)} keys)", not missing, missing[:10])
home = read("frontend_proxy_server", "home", "home.js")
check("…the home page's link in its twelve languages", home.count('"footer.about":') == len(LANGS))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
