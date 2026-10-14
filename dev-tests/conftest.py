"""pytest configuration for the development tests.

The development tests are standalone programs (``dev-tests/*/test_*.py`` and
``dev-tests/install/test_install.sh``): each prints ``PASS``/``FAIL`` lines and exits with
status 1 on a failure, and each can still be run by hand. ``test_programs.py`` is a thin layer
that runs every program as a subprocess, so that ``pytest dev-tests`` (and the continuous
integration workflow) can select, run and report them. See ``dev-tests/README.md``.
"""

from __future__ import annotations

import os

import pytest

# The programs themselves are not pytest modules: importing one would run it. Only
# test_programs.py, at the top of dev-tests/, is collected.
collect_ignore_glob = ["*/test_*.py", "docs/*"]

GROUPS = {
    "resolver": "resolver, EPC binary decoder, data entry API and GS1's resolver test suite",
    "portal": "portal programs without a browser",
    "e2e": "portal in Chromium (with and without the syntax engine) and session limits",
    "home": "home page and proxy routes through a real nginx",
    "install": "Ubuntu installer (root, nginx, Docker Compose v2)",
    "database": "the portal's database layer against a real MongoDB (PORTAL_TEST_MONGO_URI)",
}

_CHECKS = pytest.StashKey[dict]()
_FAILURES = pytest.StashKey[dict]()


def pytest_configure(config):
    for name, text in GROUPS.items():
        config.addinivalue_line("markers", f"{name}: {text}")
    config.stash[_CHECKS] = {}
    config.stash[_FAILURES] = {}


@pytest.fixture
def check_counts(request):
    """Where each program run records (passed, failed, skipped parts) for the summary."""
    return request.config.stash[_CHECKS]


@pytest.fixture
def failure_notes(request):
    """Where each failed program run records its FAIL lines (GitHub annotations, below)."""
    return request.config.stash[_FAILURES]


def _annotation(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the number of checks each program reported, as the README and the guides count them."""
    counts = config.stash.get(_CHECKS, {})
    if not counts:
        return
    terminalreporter.section("development test checks")
    width = max(len(name) for name in counts)
    for name, (passed, failed, skipped) in counts.items():
        extra = []
        if failed:
            extra.append(f"{failed} failed")
        if skipped:
            extra.append(f"{skipped} part(s) skipped")
        tail = f"  ({', '.join(extra)})" if extra else ""
        terminalreporter.write_line(f"{name:<{width}}  {passed:>4} passed{tail}")
    total = sum(p for p, _, _ in counts.values())
    terminalreporter.write_line(f"{'total':<{width}}  {total:>4} passed in {len(counts)} program run(s)")

    # On GitHub Actions the same table goes to the run's summary page, readable without the log.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        rows = ["| Program | Passed | Failed | Skipped parts |", "|---|---:|---:|---:|"]
        rows += [f"| `{name}` | {p} | {f} | {s} |" for name, (p, f, s) in counts.items()]
        rows.append(f"| **total** | **{total}** | {sum(f for _, f, _ in counts.values())} | "
                    f"{sum(s for _, _, s in counts.values())} |")
        title = os.environ.get("DEV_TESTS_TITLE", "Development test checks")
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"### {title}\n\n" + "\n".join(rows) + "\n\n")

    # And each failed program as an annotation of the job: the API gives annotations to whoever can read the
    # repository, also where the logs cannot be downloaded (a cloud session behind a proxy).
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for name, lines in list(config.stash.get(_FAILURES, {}).items())[:10]:
            terminalreporter.write_line(f"::error title=dev-tests {name}::" + _annotation("\n".join(lines)[:3000]))
