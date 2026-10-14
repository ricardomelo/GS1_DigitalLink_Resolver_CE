"""Runs every development test program as one pytest test.

Each program prints ``PASS <check>`` and ``FAIL <check>`` lines and exits with status 1 on a
failure (see ``dev-tests/README.md``). This layer runs it in a subprocess from the repository
root, with the environment of the caller, and turns the result into a pytest outcome:

* exit status 0 and no ``FAIL`` line: passed (the number of checks is shown in the summary);
* otherwise: failed, with the ``FAIL`` lines and the end of the output in the report;
* a program that only printed ``SKIP`` (a missing optional piece): skipped.

Programs are grouped with markers, so that a part can be run on its own::

    pytest dev-tests -m resolver
    pytest dev-tests -m "portal or home"
    pytest dev-tests -k gs1_suite

**Strict mode.** With ``DEV_TESTS_STRICT=1`` (set by the continuous integration workflow) a
program whose external pieces are missing fails instead of skipping them: every environment
variable it needs must name an existing path, every command it needs must be on the PATH, and
a ``SKIP`` line is a failure. A cache restored empty or an engine that did not build cannot then
pass unnoticed. Variables that are not paths (a MongoDB URI) are listed in ``needs_var`` and only
need to be set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
STRICT = os.environ.get("DEV_TESTS_STRICT", "") not in ("", "0", "false", "no")
TIMEOUT = int(os.environ.get("DEV_TESTS_TIMEOUT", "1200"))


@dataclass
class Program:
    name: str
    group: str
    path: str
    needs_env: tuple[str, ...] = ()
    needs_cmd: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    root: bool = False
    needs_var: tuple[str, ...] = ()


PROGRAMS = [
    Program("resolver", "resolver", "resolver/test_resolver.py", ("GS1_SYNTAX_ENGINE",), ("node",)),
    Program("gs1_suite", "resolver", "resolver/test_gs1_suite.py",
            ("GS1_RESOLVER_TESTSUITE", "AJV_DIST", "GS1_SYNTAX_ENGINE"), ("node",)),
    Program("epc_binary", "resolver", "resolver/test_epc_binary.py", ("EPC_TDS",), ("node",)),
    Program("data_entry_api", "resolver", "resolver/test_data_entry_api.py"),
    Program("keys", "portal", "portal/test_keys.py", ("GS1_SYNTAX_ENGINE",), ("node",)),
    Program("dictionary", "portal", "portal/test_dictionary.py", ("GS1_SYNTAX_ENGINE_DIR",)),
    Program("engine_messages", "portal", "portal/test_engine_messages.py", ("GS1_SYNTAX_ENGINE_DIR",)),
    Program("governance", "portal", "portal/test_governance.py"),
    Program("sheet", "portal", "portal/test_sheet.py"),
    Program("special_chars", "portal", "portal/test_special_chars.py"),
    Program("data_attributes", "portal", "portal/test_data_attributes.py", ("GS1_SYNTAX_ENGINE_DIR",)),
    Program("linkcheck", "portal", "portal/test_linkcheck.py"),
    Program("portal_config", "portal", "portal/test_portal_config.py"),
    Program("registration", "portal", "portal/test_registration.py"),
    Program("store", "portal", "portal/test_store.py"),
    Program("jobs", "portal", "portal/test_jobs.py"),
    Program("tenants", "portal", "portal/test_tenants.py"),
    Program("store_mongodb", "database", "portal/test_store_mongodb.py", needs_var=("PORTAL_TEST_MONGO_URI",)),
    Program("portal_e2e", "e2e", "portal/test_portal_e2e.py", ("GS1_SYNTAX_ENGINE_DIR",)),
    Program("portal_e2e_without_engine", "e2e", "portal/test_portal_e2e.py",
            env={"GS1_SYNTAX_ENGINE_DIR": "/nonexistent"}),
    Program("session", "e2e", "portal/test_session.py"),
    Program("home", "home", "home/test_home.py", needs_cmd=("nginx",)),
    Program("install", "install", "install/test_install.sh", ("COMPOSE_BIN",), ("nginx", "openssl"), root=True),
    Program("deploy", "install", "install/test_deploy.py", ("COMPOSE_BIN",), ("ps",)),
]


def _missing(program: Program) -> list[str]:
    """External pieces of a program that are not there."""
    missing = []
    for var in program.needs_env:
        value = os.environ.get(var)
        if not value:
            missing.append(f"{var} is not set")
        elif not Path(value).exists():
            missing.append(f"{var}={value} does not exist")
    missing += [f"{var} is not set" for var in program.needs_var if not os.environ.get(var)]
    missing += [f"'{cmd}' is not on the PATH" for cmd in program.needs_cmd if not shutil.which(cmd)]
    return missing


def _command(program: Program) -> list[str]:
    script = str(REPO / "dev-tests" / program.path)
    if program.path.endswith(".sh"):
        command = ["bash", script]
        if program.root and os.geteuid() != 0:
            # The installer test must run as root; sudo resets the environment, so the variables
            # it reads are passed on explicitly. (Git lets root read the repository of the user who
            # ran sudo, so the test's "git ls-files" still works.)
            if not shutil.which("sudo") or subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode:
                pytest.skip("needs root (or password-less sudo)")
            passed_on = [f"{k}={os.environ[k]}" for k in ("PATH", "COMPOSE_BIN") if k in os.environ]
            command = ["sudo", "-n", "env", *passed_on, *command]
        return command
    return [sys.executable, script]


def _lines(output: str, prefix: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(prefix)]


@pytest.mark.parametrize(
    "program",
    [pytest.param(p, id=p.name, marks=getattr(pytest.mark, p.group)) for p in PROGRAMS],
)
def test_program(program: Program, check_counts):
    missing = _missing(program)
    if missing and STRICT:
        pytest.fail(f"{program.name}: " + "; ".join(missing) + " (DEV_TESTS_STRICT is set)", pytrace=False)

    env = {**os.environ, **program.env}
    try:
        run = subprocess.run(_command(program), cwd=REPO, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"").decode("utf-8", errors="replace")
        tail = "\n".join(output.splitlines()[-30:])
        pytest.fail(f"{program.name}: no result after {TIMEOUT} s\n{tail}", pytrace=False)

    # Some programs print bytes that are not UTF-8 (output of other tools): never let that hide a result.
    output = run.stdout.decode("utf-8", errors="replace")
    passed, failed, skipped = _lines(output, "PASS"), _lines(output, "FAIL"), _lines(output, "SKIP")
    check_counts[program.name] = (len(passed), len(failed), len(skipped))

    if run.returncode != 0 or failed:
        tail = "\n".join(output.splitlines()[-30:])
        report = "\n".join(failed[:50]) or "(no FAIL line)"
        pytest.fail(f"{program.name}: exit status {run.returncode}, {len(failed)} failed check(s)\n"
                    f"{report}\n--- end of the output ---\n{tail}", pytrace=False)
    if skipped and STRICT:
        pytest.fail(f"{program.name}: parts skipped (DEV_TESTS_STRICT is set)\n" + "\n".join(skipped),
                    pytrace=False)
    if not passed:
        if skipped:
            pytest.skip("; ".join(line.removeprefix("SKIP").strip(" :") for line in skipped))
        pytest.fail(f"{program.name}: exit status 0 but no PASS line", pytrace=False)
