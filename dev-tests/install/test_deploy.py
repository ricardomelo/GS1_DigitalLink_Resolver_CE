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
  * the GeoIP database's monthly update (scripts/geoip-update.sh) with a stand-in "curl": the month's DB-IP file, or the
    previous month's, or GEOIP_URL from .env (never printed with its query string), gzip-compressed or not, checked
    and put in place in one step; a download that is not an MMDB keeps the old file, says ERROR and exits 1; and the
    resolver's container mounts the folder read only;
  * the upgrade of an official installation (scripts/upgrade-from-official.sh) with a stand-in "docker" and local
    repositories: a backup before anything changes, the branch switched in place, the credentials kept, the records
    compared, and refusals that change nothing;
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


def backup_copy_checks() -> None:
    """The off-server copy of each run (BACKUP_COPY_TO, item 7.2) with stand-in docker and rsync."""
    script = REPO / "scripts" / "resolver-backup.sh"
    for outcome in ("copied", "copy fails", "from .env", "off"):
        work = Path(tempfile.mkdtemp(prefix="backup-copy-test-"))
        bin_dir, backups, recorded, copied = work / "bin", work / "backups", work / "recorded", work / "rsync"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text("#!/bin/sh\ncase \"$*\" in *mongosh*) echo \"$*\" >> " + str(recorded)
                                        + " ;; *mongodump*) printf ARCHIVE ;; *) exit 0 ;; esac\n")
        (bin_dir / "rsync").write_text(f'#!/bin/sh\necho "$*" >> {copied}\n'
                                       + ("exit 23\n" if outcome == "copy fails" else "exit 0\n"))
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work),
               "BACKUP_DIR": str(backups)}
        env.pop("BACKUP_COPY_TO", None)
        if outcome in ("copied", "copy fails"):
            env["BACKUP_COPY_TO"] = "backup@vault.example.org:/srv/resolver/"
        elif outcome == "from .env":
            (work / ".env").write_text("BACKUP_COPY_TO='/mnt/offsite/resolver'\n")
        run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60, env=env)
        calls = copied.read_text() if copied.exists() else ""
        noted = recorded.read_text() if recorded.exists() else ""
        archives = sorted(backups.glob("resolver-*.archive.gz"))
        if outcome == "copied":
            check(run.returncode == 0 and " OK " in run.stdout and archives and str(archives[0]) in calls
                  and calls.strip().endswith("backup@vault.example.org:/srv/resolver/") and "--chmod=F600" in calls,
                  "backup copy: each run's archive copied to BACKUP_COPY_TO (one slash, files private)",
                  (run.returncode, calls, run.stdout[-200:]))
        elif outcome == "copy fails":
            check(run.returncode == 1 and "ERROR: the off-server copy" in run.stdout and archives
                  and "BACKUP_OK=0" in noted and "BACKUP_ERROR=the off-server copy failed" in noted,
                  "backup copy: a failed copy fails the run, keeps the local archive and is recorded",
                  (run.returncode, run.stdout[-200:], noted[-200:]))
        elif outcome == "from .env":
            check(run.returncode == 0 and calls.strip().endswith("/mnt/offsite/resolver/"),
                  "backup copy: the destination read from .env (cron runs without it in the environment)", calls)
        else:
            check(run.returncode == 0 and not calls, "backup copy: nothing copied without BACKUP_COPY_TO", calls)
        shutil.rmtree(work, ignore_errors=True)


def geoip_checks() -> None:
    """scripts/geoip-update.sh (ADR 0006, section 8) with a stand-in curl that serves an MMDB-like file."""
    script = REPO / "scripts" / "geoip-update.sh"
    marker = b"\xab\xcd\xefMaxMind.com"
    database = b"\0" * 2000 + marker + b"metadata"
    import gzip
    month = time.strftime("%Y-%m", time.gmtime())
    for case in ("this month", "previous month", "GEOIP_URL", "not a database", "nothing"):
        work = Path(tempfile.mkdtemp(prefix="geoip-test-"))
        bin_dir, served, calls = work / "bin", work / "served", work / "calls"
        bin_dir.mkdir()
        served.mkdir()
        (served / "good.gz").write_bytes(gzip.compress(database))
        (served / "plain").write_bytes(database)
        (served / "html").write_bytes(b"<html>" + b"x" * 3000 + b"</html>")
        # curl -fsSL --retry 2 --max-time 900 -o FILE URL: the last argument is the address, the one after -o the file
        rules = {"this month": f'*{month}*) cp {served}/good.gz "$out" ;;',
                 "previous month": f'*{month}*) exit 22 ;; *dbip-city-lite-*) cp {served}/good.gz "$out" ;;',
                 "GEOIP_URL": f'*geolite.example.org*) cp {served}/plain "$out" ;;',
                 "not a database": f'*) cp {served}/html "$out" ;;',
                 "nothing": ''}[case]
        (bin_dir / "curl").write_text('#!/bin/bash\nout=""; prev=""\nfor a in "$@"; do [[ $prev == -o ]] && out=$a; '
                                      f'prev=$a; done\necho "${{@: -1}}" >> {calls}\ncase "${{@: -1}}" in {rules} '
                                      '*) exit 22 ;; esac\n')
        (bin_dir / "curl").chmod(0o755)
        target = work / "geoip" / "dbip-city-lite.mmdb"
        target.parent.mkdir()
        target.write_bytes(b"OLD")
        if case == "GEOIP_URL":
            (work / ".env").write_text("GEOIP_URL='https://geolite.example.org/City.mmdb?license_key=SECRET42'\n")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work),
               "GEOIP_MIN_BYTES": "1000"}
        env.pop("GEOIP_URL", None)
        run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60, env=env)
        asked = calls.read_text().split() if calls.exists() else []
        leftovers = [p.name for p in target.parent.iterdir() if p.name != target.name]
        if case in ("this month", "previous month", "GEOIP_URL"):
            check(run.returncode == 0 and " OK: " in run.stdout and target.read_bytes() == database and not leftovers
                  and oct(target.stat().st_mode & 0o777) == "0o644",
                  f"GeoIP update ({case}): the file checked, put in place readable by the resolver, nothing left behind",
                  (run.returncode, run.stdout[-300:], leftovers))
        if case == "this month":
            check(asked == [f"https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"],
                  "GeoIP update: DB-IP's City Lite of the month by default", asked)
        elif case == "previous month":
            check(len(asked) == 2 and month in asked[0] and month not in asked[1] and "dbip-city-lite-" in asked[1],
                  "GeoIP update: the previous month's while the month's is not out", asked)
        elif case == "GEOIP_URL":
            check(asked == ["https://geolite.example.org/City.mmdb?license_key=SECRET42"]
                  and "SECRET42" not in run.stdout + run.stderr,
                  "GeoIP update: GEOIP_URL from .env (a file not compressed), its query string never printed",
                  (asked, run.stdout[-200:]))
        else:
            check(run.returncode == 1 and "ERROR" in run.stdout and target.read_bytes() == b"OLD" and not leftovers,
                  f"GeoIP update ({case}): ERROR, status 1, the old file kept, nothing left behind",
                  (run.returncode, run.stdout[-300:], leftovers))
        shutil.rmtree(work, ignore_errors=True)
    cron = (REPO / "scripts" / "geoip-update.cron").read_text()
    check(re.search(r"^\d+ \d+ \d+ \* \* root REPOSITORY/scripts/geoip-update\.sh ", cron, re.M),
          "GeoIP update: scheduled monthly as root by its cron file", cron[-200:])
    compose = (REPO / "docker-compose.yml").read_text()
    web = compose.split("  web-service:", 1)[1].split("\n  portal-db-init:", 1)[0]
    check("- ./geoip:/geoip:ro" in web, "GeoIP update: the resolver mounts the folder read only", web[-400:])
    env_example = (REPO / ".env.example").read_text()
    check("RESOLVER_GEOIP_DB=/geoip/dbip-city-lite.mmdb" in env_example and "RESOLVER_LOG_ADDRESS_HEADER=X-Real-IP"
          in env_example, "GeoIP update: .env.example names the file the resolver reads and the address header")


def rehearsal_checks() -> None:
    """scripts/restore-rehearsal.sh (item 7.2) with a stand-in docker: a throw-away container without network, the
    archive given to mongorestore, the counts compared, the container removed; refusals."""
    script = REPO / "scripts" / "restore-rehearsal.sh"
    text = script.read_text()
    found = re.search(r"COUNT_JS='(.*?)'\n", text, re.S)
    node = shutil.which("node")
    if node and found:
        js = Path(tempfile.mkdtemp()) / "count.js"
        js.write_text("const db = {adminCommand() { return {databases: []}; }, getSiblingDB() {}};\n"
                      "const print = console.log;\n" + found.group(1))
        syntax = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        check(syntax.returncode == 0, "rehearsal: the counting script is valid JavaScript", syntax.stderr[-300:])
    else:
        check(bool(found), "rehearsal: the counting script is found")
    restored_ok = "resolver_ce.gs1resolver 120\nresolver_portal.users 4\nresolver_portal.journal 900"
    live = "resolver_ce.gs1resolver 125\nresolver_portal.users 4\nresolver_portal.journal 950\nresolver_log.requests 10"
    for case, restored, restore_exit in (("good", restored_ok, 0), ("no users", "resolver_ce.gs1resolver 120", 0),
                                         ("restore fails", restored_ok, 1), ("no archive", restored_ok, 0)):
        work = Path(tempfile.mkdtemp(prefix="rehearsal-test-"))
        bin_dir, backups, calls, given = work / "bin", work / "backups", work / "calls", work / "stdin"
        bin_dir.mkdir()
        backups.mkdir()
        (bin_dir / "docker").write_text(f"""#!/bin/bash
echo "$*" >> {calls}
case "$*" in
  "compose images -q database-service") echo sha256:dbimage ;;
  *mongorestore*) cat > {given}; exit {restore_exit} ;;
  "exec resolver-restore-rehearsal mongosh --quiet --eval db.runCommand"*) exit 0 ;;
  "exec resolver-restore-rehearsal mongosh"*) cat {work / "restored"} ;;
  "compose exec -T"*) cat {work / "live"} ;;
  *) exit 0 ;;
esac
""")
        (bin_dir / "docker").chmod(0o755)
        (work / "restored").write_text(restored + "\n")
        (work / "live").write_text(live + "\n")
        if case != "no archive":
            (backups / "resolver-2026-10-13_0230.archive.gz").write_text("OLDER")
            newest = backups / "resolver-2026-10-14_0230.archive.gz"
            newest.write_text("NEWEST-ARCHIVE")
            os.utime(backups / "resolver-2026-10-13_0230.archive.gz", (1, 1))
        run = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work),
                                  "BACKUP_DIR": str(backups), "REHEARSAL_WAIT_SECONDS": "4"})
        log = calls.read_text() if calls.exists() else ""
        if case == "good":
            check(run.returncode == 0 and "OK: the archive restores" in run.stdout,
                  "rehearsal: a good archive restores (OK, status 0)", (run.returncode, run.stdout[-400:]))
            check(given.exists() and given.read_text() == "NEWEST-ARCHIVE", "rehearsal: the newest archive by default")
            check("run -d --name resolver-restore-rehearsal --network none sha256:dbimage" in log,
                  "rehearsal: a throw-away container of the database's image, without network", log[:300])
            check(log.strip().splitlines()[-1] == "rm -f resolver-restore-rehearsal",
                  "rehearsal: the container is removed at the end", log[-200:])
            check(re.search(r"resolver_ce\.gs1resolver\s+120\s+125", run.stdout)
                  and re.search(r"resolver_log\.requests\s+-\s+10", run.stdout),
                  "rehearsal: restored and live counts side by side", run.stdout[-500:])
        elif case == "no users":
            check(run.returncode == 1 and "MISSING: resolver_portal.users" in run.stdout,
                  "rehearsal: an archive without the portal's users fails", (run.returncode, run.stdout[-300:]))
        elif case == "restore fails":
            check(run.returncode == 1 and "ERROR: mongorestore could not restore" in run.stdout
                  and "rm -f resolver-restore-rehearsal" in log.strip().splitlines()[-1],
                  "rehearsal: a failed restore fails, the container still removed", (run.returncode, run.stdout[-300:]))
        else:
            check(run.returncode == 1 and "ERROR: no archive" in run.stdout and "run -d" not in log,
                  "rehearsal: no archive, no container", (run.returncode, run.stdout[-300:]))
        shutil.rmtree(work, ignore_errors=True)


def upgrade_checks() -> None:
    """scripts/upgrade-from-official.sh with a stand-in docker, an official clone and the Expansion Pack's branch in a
    local repository: checks first, the backup before anything changes, the containers stopped, the branch switched in
    the same folder (the official one kept), the credentials and token kept in .env for the installer, the records
    counted before and after; refusals that change nothing."""
    script = REPO / "scripts" / "upgrade-from-official.sh"
    found = re.search(r"COUNT_JS='(.*?)'\n", script.read_text(), re.S)
    node = shutil.which("node")
    if node and found:
        js = Path(tempfile.mkdtemp()) / "count.js"
        js.write_text("const db = {getSiblingDB() { return {getCollectionNames() { return []; }}; }};\n"
                      "const print = console.log;\n" + found.group(1).replace("'\"$RECORDS_DB\"'", "resolver_ce"))
        syntax = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        check(syntax.returncode == 0, "upgrade: the counting script is valid JavaScript", syntax.stderr[-300:])
    official_compose = ("services:\n  database-service:\n    volumes:\n      - resolver-database-volume:/data/db\n"
                        "  web-service: {}\nvolumes:\n  resolver-database-volume: {}\n")
    git_env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@example.org"}

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=git_env)

    def upgrade(case, args=("--yes",)):
        work = Path(tempfile.mkdtemp(prefix="upgrade-test-"))
        official, expansion, bin_dir = work / "official", work / "expansion", work / "bin"
        calls, backups = work / "calls", work / "backups"
        for folder in (official, expansion, bin_dir):
            folder.mkdir()
        # the Expansion Pack's branch, with a stand-in installer that records its call
        (expansion / "docker-compose.yml").write_text(official_compose + "  portal-service: {}\n")
        (expansion / "scripts").mkdir()
        (expansion / "scripts" / "install.sh").write_text(f"echo \"install $*\" >> {calls}; touch {work / 'installed'}\n")
        git(expansion, "init", "-q", "-b", "master")
        git(expansion, "add", "-A")
        git(expansion, "commit", "-q", "-m", "expansion")
        # the official installation
        (official / "docker-compose.yml").write_text(official_compose + ("  portal-service: {}\n" if case == "already" else ""))
        (official / ".env.example").write_text("MONGO_INITDB_ROOT_USERNAME=gs1resolver\nMONGO_INITDB_ROOT_PASSWORD=gs1resolver\n"
                                               "MONGO_URI=mongodb://gs1resolver:gs1resolver@database-service:27017\n"
                                               "SESSION_TOKEN=secret\n")
        if case == "own env":
            (official / ".env").write_text("MONGO_INITDB_ROOT_USERNAME=admin\nMONGO_INITDB_ROOT_PASSWORD='S3cret-pass'\n"
                                           "MONGO_URI='mongodb://admin:S3cret-pass@database-service:27017'\n"
                                           "SESSION_TOKEN='tok-123'\n")
        git(official, "init", "-q", "-b", "main")
        git(official, "add", "docker-compose.yml", ".env.example")
        git(official, "commit", "-q", "-m", "official")
        if case == "changed":
            (official / "docker-compose.yml").write_text(official_compose + "# a local change\n")
        password = "S3cret-pass" if case == "own env" else "gs1resolver"
        after = "gs1resolver 120\nlinktypes 3" if case == "fewer" else "gs1resolver 125\nlinktypes 3"
        (bin_dir / "docker").write_text(f"""#!/bin/bash
echo "$*" >> {calls}
case "$*" in
  "compose ps --status running --services") {"exit 0" if case == "stopped" else "echo database-service"} ;;
  *mongodump*) {"exit 1" if case == "dump fails" else "echo DUMP-ARCHIVE"} ;;
  *"compose exec -T -e U="*) input=$(cat)
     [[ "$*" == *"P={password}"* && "{case}" != "refused" ]] || exit 1
     if [[ $input == *ping* ]]; then echo 1
     elif [[ -e {work / 'installed'} ]]; then printf '{after}\\n'
     else printf 'gs1resolver 125\\nlinktypes 3\\n'; fi ;;
  *) exit 0 ;;
esac
""")
        (bin_dir / "docker").chmod(0o755)
        run = subprocess.run(["bash", str(script), *args], cwd=official, capture_output=True, text=True, timeout=120,
                             env={**git_env, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BACKUP_DIR": str(backups),
                                  "UPGRADE_REPOSITORY": str(expansion), "UPGRADE_LOG": str(work / "upgrade.log")})
        branch = git(official, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        return run, work, official, branch, (calls.read_text() if calls.exists() else ""), backups

    run, work, official, branch, calls, backups = upgrade("good")
    archives = list(backups.glob("pre-upgrade-*.archive.gz")) if backups.exists() else []
    check(run.returncode == 0 and "Upgrade done" in run.stdout, "upgrade: an official installation is upgraded",
          (run.returncode, run.stdout[-600:]))
    check(len(archives) == 1 and archives[0].read_text() == "DUMP-ARCHIVE\n" and archives[0].stat().st_mode & 0o777 == 0o600,
          "upgrade: a full backup first (mongodump, gzip), readable by its owner only", archives)
    lines = calls.splitlines()
    order = [next((i for i, l in enumerate(lines) if key in l), -1) for key in ("mongodump", "compose down", "install")]
    check(order[0] >= 0 and order == sorted(order) and "compose down --remove-orphans" in calls and " -v" not in calls,
          "upgrade: backup, then the official containers stopped (volume kept), then the installer", lines)
    check(branch == "master" and "main" in git(official, "branch").stdout,
          "upgrade: the Expansion Pack's branch in the same folder, the official branch kept", branch)
    env = (official / ".env").read_text()
    check("MONGO_INITDB_ROOT_PASSWORD='gs1resolver'" in env and "SESSION_TOKEN='secret'" in env
          and "MONGO_URI='mongodb://gs1resolver:gs1resolver@database-service:27017'" in env
          and (official / ".env").stat().st_mode & 0o777 == 0o600,
          "upgrade: the database's credentials and the API token written to .env for the installer to keep", env)
    check(re.search(r"gs1resolver: 125 before, 125 now", run.stdout) and "rotate-secrets.sh" in run.stdout
          and "git switch main" in run.stdout and str(archives[0]) in run.stdout if archives else False,
          "upgrade: the records compared; the default password's rotation and the way back told", run.stdout[-800:])
    shutil.rmtree(work, ignore_errors=True)

    run, work, official, branch, calls, backups = upgrade("good", ("--check",))
    check(run.returncode == 0 and "Nothing was changed" in run.stdout and branch == "main" and not backups.exists()
          and "compose down" not in calls and not (official / ".env").exists() and "gs1resolver 125" in run.stdout,
          "upgrade: --check only checks and counts", (run.returncode, run.stdout[-300:], calls))
    shutil.rmtree(work, ignore_errors=True)

    run, work, official, branch, calls, backups = upgrade("own env")
    env = (official / ".env").read_text()
    check(run.returncode == 0 and env.count("MONGO_INITDB_ROOT_PASSWORD=") == 1 and "S3cret-pass" in env
          and "rotate-secrets.sh" not in run.stdout and list(official.glob(".env.bak-*")),
          "upgrade: an .env of its own kept as it is (a copy aside), no rotation advised", (env, run.stdout[-300:]))
    shutil.rmtree(work, ignore_errors=True)

    for case, message in (("already", "already runs the Expansion Pack"), ("changed", "commit or put them aside"),
                          ("stopped", "database service is not running"), ("refused", "did not accept the credentials"),
                          ("dump fails", "mongodump failed")):
        run, work, official, branch, calls, backups = upgrade(case)
        check(run.returncode == 1 and message in run.stdout and branch == "main" and "compose down" not in calls
              and not list(backups.glob("*.gz") if backups.exists() else []),
              f"upgrade: {case}: refused, nothing changed", (run.returncode, run.stdout[-300:], calls))
        shutil.rmtree(work, ignore_errors=True)

    run, work, official, branch, calls, backups = upgrade("fewer")
    check(run.returncode == 1 and "fewer records" in run.stdout and "gs1resolver: 125 before, 120 now" in run.stdout
          and "mongorestore" in run.stdout, "upgrade: fewer records afterwards: status 1 and the way back",
          (run.returncode, run.stdout[-500:]))
    shutil.rmtree(work, ignore_errors=True)


def rotation_checks() -> None:
    """scripts/rotate-secrets.sh (item 7.2) with a stand-in docker: new values in .env, the old ones kept aside, the
    MongoDB root password changed in the database first and given on standard input, nothing secret printed."""
    script = REPO / "scripts" / "rotate-secrets.sh"
    old = {"SESSION_TOKEN": "a" * 64, "PORTAL_SECRET_KEY": "b" * 64, "PORTAL_DB_PASSWORD": "c" * 48,
           "MONGO_INITDB_ROOT_PASSWORD": "p@ss:w0rd!xyz"}
    env_text = ("MONGO_INITDB_ROOT_USERNAME=resolveradmin\n"
                f"MONGO_INITDB_ROOT_PASSWORD='{old['MONGO_INITDB_ROOT_PASSWORD']}'\n"
                "MONGO_URI='mongodb://resolveradmin:p%40ss%3Aw0rd%21xyz@database-service:27017'\n"
                f"SESSION_TOKEN='{old['SESSION_TOKEN']}'\nPORTAL_SECRET_KEY='{old['PORTAL_SECRET_KEY']}'\n"
                f"PORTAL_DB_PASSWORD='{old['PORTAL_DB_PASSWORD']}'\nFQDN='id.example.org'\n")

    def rotate(args, database_accepts=True):
        work = Path(tempfile.mkdtemp(prefix="rotate-test-"))
        bin_dir, calls, stdin = work / "bin", work / "calls", work / "stdin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(f"""#!/bin/bash
echo "$*" >> {calls}
case "$*" in
  *changeUserPassword*) cat > {stdin}; exit {0 if database_accepts else 1} ;;
  *) exit 0 ;;
esac
""")
        (bin_dir / "docker").chmod(0o755)
        (work / ".env").write_text(env_text)
        (work / ".env").chmod(0o600)
        run = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work)})
        new = dict(line.split("=", 1) for line in (work / ".env").read_text().splitlines() if "=" in line)
        new = {k: v.strip("'") for k, v in new.items()}
        backups = list(work.glob(".env.bak-*"))
        result = (run, new, backups, calls.read_text() if calls.exists() else "",
                  stdin.read_text() if stdin.exists() else "", work)
        return result

    run, new, backups, calls, given, work = rotate([])
    check(run.returncode == 0 and all(new[k] != v for k, v in old.items()),
          "rotation: every secret gets a new value", (run.returncode, run.stdout[-300:]))
    check(re.fullmatch(r"[0-9a-f]{64}", new["SESSION_TOKEN"]) and re.fullmatch(r"[0-9a-f]{64}", new["PORTAL_SECRET_KEY"])
          and re.fullmatch(r"[0-9a-f]{48}", new["PORTAL_DB_PASSWORD"])
          and re.fullmatch(r"[0-9a-f]{48}", new["MONGO_INITDB_ROOT_PASSWORD"]),
          "rotation: the installer's lengths (64 and 48 hexadecimal digits)")
    check(new["MONGO_URI"] == f"mongodb://resolveradmin:{new['MONGO_INITDB_ROOT_PASSWORD']}@database-service:27017",
          "rotation: MONGO_URI follows the new root password (an old percent-encoded one replaced)", new["MONGO_URI"])
    check(given.strip() == new["MONGO_INITDB_ROOT_PASSWORD"] and new["MONGO_INITDB_ROOT_PASSWORD"] not in calls,
          "rotation: the database's password changed first, given on standard input, never on a command line")
    check(calls.strip().splitlines()[-1] == "compose up -d", "rotation: the services recreated at the end", calls[-200:])
    check(len(backups) == 1 and oct(backups[0].stat().st_mode & 0o777) == "0o600"
          and backups[0].read_text() == env_text and oct((work / ".env").stat().st_mode & 0o777) == "0o600",
          "rotation: the previous .env kept (mode 600), the new one still 600")
    printed = run.stdout + run.stderr
    check(not any(v in printed for v in list(old.values()) + [new[k] for k in old]),
          "rotation: no secret printed, old or new", printed[-300:])
    check(new["FQDN"] == "id.example.org" and new["MONGO_INITDB_ROOT_USERNAME"] == "resolveradmin"
          and sum(1 for line in (work / ".env").read_text().splitlines() if line.startswith("SESSION_TOKEN=")) == 1,
          "rotation: other settings kept, each secret on one line")
    shutil.rmtree(work, ignore_errors=True)
    run, new, backups, calls, given, work = rotate(["token", "session"])
    check(run.returncode == 0 and new["SESSION_TOKEN"] != old["SESSION_TOKEN"]
          and new["PORTAL_DB_PASSWORD"] == old["PORTAL_DB_PASSWORD"]
          and new["MONGO_INITDB_ROOT_PASSWORD"] == old["MONGO_INITDB_ROOT_PASSWORD"] and "changeUserPassword" not in calls,
          "rotation: only the secrets named", run.stdout[-300:])
    shutil.rmtree(work, ignore_errors=True)
    run, new, backups, calls, given, work = rotate(["mongo"], database_accepts=False)
    check(run.returncode == 1 and new["MONGO_INITDB_ROOT_PASSWORD"] == old["MONGO_INITDB_ROOT_PASSWORD"]
          and "p%40ss" in new["MONGO_URI"] and "compose up -d" not in calls and "SKIPPED mongo" in run.stdout,
          "rotation: the database refusing the change leaves .env's password alone (status 1)",
          (run.returncode, run.stdout[-300:]))
    shutil.rmtree(work, ignore_errors=True)
    run, new, backups, calls, given, work = rotate(["everything"])
    check(run.returncode == 2 and not backups and new["SESSION_TOKEN"] == old["SESSION_TOKEN"],
          "rotation: an unknown name refused before anything changes", run.stdout[-200:])
    shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- the organisations' own domains
def domains_script_checks() -> None:
    """scripts/custom-domains.sh (Documentation/adr/0009-tenant-domains.md) with stand-in docker, nginx, systemctl and
    certbot: the verified direct domains read from the portal's database, a site written from the installer's template
    for each new one and Certbot asked for its certificate, names that are not host names refused before any file or
    command, sites of domains no longer verified reported, and CERTBOT_EMAIL required. Since section 7 of the ADR (item
    9.6): each domain's state reported to the portal (served with the certificate's end, failed with the next attempt),
    waits growing after failures, a domain waiting left alone, the run recorded, --quiet, the lock, the cron file."""
    import fcntl
    script = REPO / "scripts" / "custom-domains.sh"
    work = Path(tempfile.mkdtemp(prefix="domains-test-"))
    bin_dir, available, enabled, calls = work / "bin", work / "available", work / "enabled", work / "calls"
    listing = work / "domains.tsv"
    bin_dir.mkdir()
    (work / "scripts" / "templates").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "templates" / "nginx-site-http.conf", work / "scripts" / "templates")
    cert = work / "fullchain.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(work / "key.pem"),
                    "-out", str(cert), "-days", "30", "-subj", "/CN=id.acme.example"], capture_output=True, check=True)
    end = subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", str(cert)], capture_output=True,
                         text=True).stdout.strip().split("=", 1)[1]
    until = int(subprocess.run(["date", "-d", end, "+%s"], capture_output=True, text=True).stdout)
    now = int(time.time())
    # name, failed attempts, next attempt, state, the certificate's end — as the portal's database gives them
    listing.write_text("id.acme.example\t0\t0\t\t0\nbad;rm -rf x\t0\t0\t\t0\nshop.beta.example\t0\t0\t\t0\n"
                       f"late.example\t2\t{now + 3600}\tfailed\t0\nretry.example\t3\t{now - 60}\tfailed\t0\n"
                       f"cap.example\t9\t{now - 60}\tfailed\t0\n")
    stand_ins = {
        # "docker compose exec … mongosh": the domains for the script's query, every call kept (the values travel as
        # -e NAME=value, one per line in the file)
        "docker": f'printf "docker" >> {calls}; for a in "$@"; do printf " %s" "$a" >> {calls}; done; echo >> {calls}\n'
                  f'case "$*" in *"db.domains.find("*) cat {listing} ;; esac',
        "nginx": f'echo "nginx $*" >> {calls}',
        "systemctl": f'echo "systemctl $*" >> {calls}',
        # certbot adds the HTTPS server to the site, as the real one does; it fails for the domains not pointing here
        "certbot": f'echo "certbot $*" >> {calls}; d=$(echo "$*" | sed -n "s/.*-d \\([^ ]*\\).*/\\1/p"); '
                   f'case $d in id.acme.example) ;; *) exit 1 ;; esac; '
                   f'echo "    ssl_certificate {cert};" >> {available}/gs1resolver-domain-$d',
    }
    for name, body in stand_ins.items():
        (bin_dir / name).write_text("#!/bin/bash\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLVER_DIR": str(work),
           "NGINX_AVAILABLE": str(available), "NGINX_ENABLED": str(enabled), "LOCK_FILE": str(work / "lock")}
    env.pop("CERTBOT_EMAIL", None)

    def run(*args):
        if calls.exists():
            calls.unlink()
        done = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=60, env=env)
        return done, calls.read_text() if calls.exists() else ""

    def recorded(log, domain):
        """The values of the state recorded for a domain ({} when none)."""
        for line in log.splitlines():
            if f"D_NAME={domain} " in line + " ":
                return dict(re.findall(r"(D_[A-Z]+)=(\S*)", line))
        return {}

    result, log = run("apply")
    check(result.returncode == 1 and "CERTBOT_EMAIL is not set" in result.stdout and "D_OK=0" in log,
          "custom domains: apply needs CERTBOT_EMAIL (a failed run recorded)", result.stdout[-200:])
    (work / ".env").write_text("CERTBOT_EMAIL='ops@example.org'\nPORTAL_DB_NAME=resolver_portal\n")
    result, log = run("list")
    check(result.returncode == 0 and "id.acme.example: no site yet" in result.stdout
          and "bad;rm -rf x: refused" in result.stdout,
          "custom domains: list shows each verified direct domain and refuses a name that is not a host name",
          result.stdout)
    result, log = run("apply")
    site = available / "gs1resolver-domain-id.acme.example"
    text = site.read_text() if site.exists() else ""
    check("server_name id.acme.example;" in text and "proxy_pass http://127.0.0.1:8080;" in text
          and "proxy_set_header Host $host;" in text and (enabled / "gs1resolver-domain-id.acme.example").is_symlink(),
          "custom domains: apply writes a site from the installer's template and enables it", (result.stdout, text[:300]))
    check("certbot --nginx -d id.acme.example --non-interactive --agree-tos -m ops@example.org" in log
          and "certbot --nginx -d shop.beta.example" in log and "nginx -t" in log and "systemctl reload nginx" in log,
          "custom domains: nginx checked and reloaded, Certbot asked for each certificate", log[-600:])
    check("rm -rf" not in log.replace("bad;rm -rf x", "") and not any("bad" in p.name for p in available.iterdir())
          and "PORTAL_DB=resolver_portal" in log and "D_NAME=bad" not in log,
          "custom domains: a name that is not a host name reaches no file or command", log[-600:])
    served = recorded(log, "id.acme.example")
    check(served.get("D_STATE") == "served" and served.get("D_UNTIL") == str(until) and served.get("D_ATTEMPTS") == "0",
          "custom domains: a domain served reported to the portal with its certificate's end", served)
    failed = recorded(log, "shop.beta.example")
    check(failed.get("D_STATE") == "failed" and failed.get("D_ERROR") == "certificate" and failed.get("D_ATTEMPTS") == "1"
          and abs(int(failed.get("D_NEXT", 0)) - now - 5 * 60) < 30 and result.returncode == 1
          and "ERROR: Certbot could not obtain the certificate of shop.beta.example" in result.stdout,
          "custom domains: a failed certificate reported, the next attempt in 5 minutes, the run failing",
          (failed, result.stdout[-300:]))
    later = recorded(log, "retry.example")
    capped = recorded(log, "cap.example")
    check(later.get("D_ATTEMPTS") == "4" and abs(int(later.get("D_NEXT", 0)) - now - 40 * 60) < 30
          and capped.get("D_ATTEMPTS") == "10" and abs(int(capped.get("D_NEXT", 0)) - now - 360 * 60) < 30,
          "custom domains: each failure waits twice as long, at most 6 hours", (later, capped))
    check("certbot --nginx -d late.example" not in log and not recorded(log, "late.example")
          and "late.example: waiting after 2 failed attempt(s)" in result.stdout,
          "custom domains: a domain still waiting is left alone", result.stdout[-400:])
    check("D_OK=0" in log and "domains.hostRun" in log, "custom domains: the run recorded for the portal (failed)", log[-300:])
    check("--eval \"$JS\"" in log and "MONGO_INITDB_ROOT_PASSWORD\" --authenticationDatabase" in log
          and "ops@example.org" not in "".join(l for l in log.splitlines() if "mongosh" in l),
          "custom domains: the JavaScript goes to mongosh as a variable inside the container", log[:300])

    listing.write_text(f"id.acme.example\t0\t0\tserved\t{until}\nlate.example\t2\t{now + 3600}\tfailed\t0\n")
    result, log = run("apply", "--quiet")
    check(result.returncode == 0 and result.stdout == "" and log.count("certbot") == 0
          and not recorded(log, "id.acme.example") and "D_OK=1" in log,
          "custom domains: --quiet with nothing to do prints nothing, reports nothing new, records the run",
          (result.stdout, log[-300:]))
    listing.write_text(f"id.acme.example\t0\t0\tserved\t{until - 86400}\n")
    result, log = run("apply", "--quiet")
    check(recorded(log, "id.acme.example").get("D_UNTIL") == str(until) and result.stdout == "",
          "custom domains: a renewed certificate reported again", log[-300:])
    with open(work / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result, log = run("apply")
    check(result.returncode == 0 and "Another run is in progress" in result.stdout and log == "",
          "custom domains: a run while another holds the lock does nothing", (result.stdout, log[:200]))
    (available / "gs1resolver-domain-old.example").write_text("server {}\n")
    listing.write_text("id.acme.example\t0\t0\tserved\t0\n")
    result, log = run("list")
    check("old.example: site of a domain no longer verified" in result.stdout and "id.acme.example: site and certificate"
          in result.stdout, "custom domains: list reports sites of domains no longer verified", result.stdout)
    node = shutil.which("node")
    scripts_js = dict(re.findall(r"^(\w+_JS)='(.*?)'$", script.read_text(), re.M | re.S))
    if node:
        bad = []
        for name, js in scripts_js.items():
            path = work / f"{name}.js"
            path.write_text("const db = {};\n" + js)
            if subprocess.run([node, "--check", str(path)], capture_output=True).returncode:
                bad.append(name)
        check(sorted(scripts_js) == ["DOMAINS_JS", "RECORD_JS", "RUN_JS"] and not bad,
              "custom domains: the mongosh scripts are valid JavaScript", (sorted(scripts_js), bad))
    cron = (REPO / "scripts" / "custom-domains.cron").read_text()
    check(re.search(r"^\*/5 \* \* \* \* root REPOSITORY/scripts/custom-domains\.sh apply --quiet ", cron, re.M),
          "custom domains: scheduled every 5 minutes as root by its cron file, quiet", cron[-200:])
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
    # the resolver checks each GS1 Digital Link with the engine in its own process (web_server/src/gs1_syntax.py),
    # built in the image with the portal's script, which Compose hands over as the build context "engine-tools"
    web = (REPO / "web_server" / "Dockerfile").read_text()
    contexts = (((config or {}).get("services", {}).get("web-service", {}).get("build") or {})
                .get("additional_contexts") or {})
    check('build-syntax-engine.sh /opt/gs1-syntax-engine "$GS1_SYNTAX_ENGINE_RELEASE"' in web
          and "COPY --from=engine-tools build-syntax-engine.sh" in web
          and "COPY --from=syntax-engine /opt/gs1-syntax-engine /opt/gs1-syntax-engine" in web
          and "ENV GS1_SYNTAX_ENGINE_DIR=/opt/gs1-syntax-engine" in web
          and Path(contexts.get("engine-tools", "/nonexistent")).resolve() == (REPO / "portal" / "tools").resolve(),
          "engine release: web_server/Dockerfile builds the engine for the resolver's process with the portal's script",
          contexts)
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
    backup_copy_checks()
    geoip_checks()
    rehearsal_checks()
    upgrade_checks()
    rotation_checks()
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
