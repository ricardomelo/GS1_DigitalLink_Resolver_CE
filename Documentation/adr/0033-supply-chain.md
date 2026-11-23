# ADR 0033 — Supply chain: everything fetched by hash, digest or commit; updates proposed weekly; scanning and an SBOM

| | |
|---|---|
| Status | **Accepted** (21 November 2026); step 1 and step 2 delivered the same day |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-I5 and gap G-18 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): lock files with hashes resolved together, images by tag and digest, actions by commit, Node.js from the official image, Dependabot for the updates; scanning and the SBOM in a second step, with pip-audit, npm audit and Trivy fetched by hash, and a reviewed list of accepted vulnerabilities that expire |

## 1. Context

An installation is built from code that is not in this repository: Python packages from PyPI, npm packages, base
images from Docker Hub, GitHub Actions, and whatever a build step downloads. Whoever can replace one of them can run
code inside the resolver, the portal or the CI. Before this decision:

- the portal's Python dependencies were ranges (`flask>=3.1,<4`), so each build took whatever was newest; the
  resolver's and the data entry API's were pinned, but only the direct ones, and nothing carried a hash: a file
  replaced on the index, or a compromised release inside a range, was installed without notice;
- every base image was a mutable tag (`python:3.12-slim-bookworm`, `nginx:1.30-alpine`, `mongo:7-jammy`), as was the
  CI's MongoDB service and every action (`actions/checkout@v7`): a tag can be moved to other content at any time;
- the resolver's and the data entry API's images piped NodeSource's setup script into `bash` as root, and then ran
  `npm init es6`, which fetches the newest release of the npm package `create-es6` and runs it (an "initializer");
  `gs1encoder` was installed without a lock file;
- nothing scanned the dependencies or the images for known vulnerabilities, there was no SBOM, no update automation
  and no `SECURITY.md` saying how to report a weakness.

What was already in place: the GS1 Barcode Syntax Engine's release written once and checked weekly (ADR 0003), the
resolver's direct dependencies pinned, and read-only permissions for the CI.

## 2. Decision

### 2.1 Step 1 — pinned by content, updated on purpose (21 November 2026)

1. **Python lock files with hashes.** Each Python service keeps its direct dependencies in `requirements.in` (the
   portal's ranges, the official services' pins) and installs `requirements.txt`, which lists every package, direct
   or not, at one version with the SHA-256 of each of its files on PyPI. The images install it with
   `pip install --require-hashes --no-deps`: a package missing from the lock, a different version or a file whose hash
   differs stops the build.
2. **One resolution for the tests and the images.** `dev-tests/requirements.in` names the three services' `.in` files
   and the test tools; `dev-tests/lock-dependencies.sh` resolves it first (with uv, for Python 3.12 on every
   platform), then each service's lock inside it (`-c`), so a package has the same version and hashes in every image,
   in the CI and in the cloud sessions' hook, all of which install `dev-tests/requirements.txt` with
   `--require-hashes`. The development tests therefore test the versions the images run.
3. **Node.js from the official image, npm from a lock file.** A build stage `node` starts from
   `node:24-bookworm-slim` by digest, installs `gs1encoder` with `npm ci --omit=dev --ignore-scripts` from
   `package-lock.json` (its SHA-512 integrity), and refuses a lock whose `gs1encoder` is not the release
   `docker-compose.yml` names. The final image receives only `node` (at `/usr/bin/node`, where the service starts
   it) and the package; neither NodeSource's script, nor `npm init`, nor npm itself remains. `nano` still comes, as in
   the official image, from Debian's signed repository.
4. **Images by tag and digest.** Every `FROM`, the composition's `mailpit` and the CI's MongoDB service are written
   `name:tag@sha256:<digest of the multi-platform index>`. The tag keeps the line the earlier ADRs chose and says what
   it is; Docker uses the digest alone.
5. **Actions by commit.** Every action is the repository's own or `owner/action@<40-character commit>  # vX.Y.Z`;
   `actions/checkout` keeps no credentials (`persist-credentials: false`).
6. **Updates proposed, not taken.** `.github/dependabot.yml` asks Dependabot for weekly pull requests against
   `master`, grouped per ecosystem: the four Python locks, the two npm locks (`gs1encoder` excepted: it follows
   the engine's own weekly check, because `docker-compose.yml` names its release for every service), the five
   Dockerfiles' digests within their tag (a new Python, nginx, MongoDB or Node.js line stays a deliberate change), the
   composition and the actions. A proposal is merged like any change, after every development test passes; when it
   touches a package the tests' lock also holds, `dev-tests/lock-dependencies.sh` is run on its branch.
   Dependabot reads this file from the default branch (`master`): the proposals start with the release that carries
   it. The repository's owner also switches on Dependabot alerts and private vulnerability reporting in its settings.
7. **A disclosure policy.** `SECURITY.md` asks for reports through GitHub's private vulnerability reporting, names the
   supported versions and says that a weakness in the official project's code is also reported upstream.
8. **A check that keeps it so.** `dev-tests/install/test_supply_chain.py` fails when an image or an action is named by
   tag only, a download is piped into a shell, `npm init` runs an initializer, npm installs other than with
   `npm ci --ignore-scripts`, pip installs without `--require-hashes`, a lock line lacks a hash or a pin, a direct
   dependency is missing or outside its specifier, a service's lock differs from the tests', the npm lock names another
   engine release, or Dependabot misses a directory.

### 2.2 Step 2 — known vulnerabilities and an SBOM (21 November 2026)

1. **A workflow of its own.** `.github/workflows/supply-chain.yml` runs on a push or pull request that changes a lock
   file, a `.in` file, a `package.json`, a Dockerfile, `docker-compose.yml`, the engine's build script, a workflow or
   `.github/supply-chain/`; every Monday at 04:41 UTC (before Dependabot's proposals, from the default branch, where
   GitHub reads schedules); by hand; and on a published release. Its permissions are `contents: read`, but for the
   release job, which may write to the release.
2. **The lock files.** `pip-audit` reads each of the four Python locks with `--require-hashes --disable-pip` (it
   resolves nothing and installs nothing) and `npm audit --package-lock-only` each toolkit's lock;
   `.github/supply-chain/audit.py` reads the six JSON reports and fails on a known vulnerability **with a correction
   available**, of any severity: a correction is a lock update, cheap and reviewed by the tests. A vulnerability
   without a correction is listed in the run's summary, not failed. A missing or unreadable report fails the job: a
   scan that did not run is never taken for a clean one.
3. **The images.** The five images are built as `docker compose build` builds them (which also proves, on every such
   change, that the locks install in the images and that the digests exist), and **Trivy** scans each one: its system
   packages and the language packages it holds (the Python site-packages, `gs1encoder`). A vulnerability rated HIGH or
   CRITICAL with a correction available fails the job; every vulnerability found is kept in the run's JSON report.
   Debian and Ubuntu list many low-rated or uncorrected vulnerabilities that a release cannot change; the digest
   updates Dependabot proposes each week bring the corrections the distributions publish.
4. **The SBOM.** Trivy writes a CycloneDX SBOM of each image; the images job keeps them (with the reports) as the
   run's artefact for 90 days, and the release job builds the images from the release's tag and attaches
   `resolver-<tag>-<service>.cdx.json` to the GitHub release (`gh release upload`, the job's own token).
5. **Accepted vulnerabilities.** `.github/supply-chain/accepted.yaml`, in Trivy's ignore-file format, read by Trivy
   and by `audit.py`: each entry names the advisory (CVE, GHSA or PYSEC; an alias matches too), a statement (why it
   does not reach the installation, or what waits for the correction), the review date and an expiry **at most 90
   days later**; after it, the scan fails again and the entry is reviewed anew. An entry is the last resort, after an
   update of the package, the lock or the digest proved impossible. An entry may name `paths` (files of an image):
   Trivy then accepts it only there, and `audit.py` never applies it to a lock file.
6. **The tools fetched by hash.** pip-audit (and PyYAML for `audit.py`) from `.github/supply-chain/requirements.txt`,
   locked with hashes by `dev-tests/lock-dependencies.sh` and installed with `--require-hashes --no-deps` (Dependabot
   proposes its updates); Trivy by `.github/supply-chain/install-trivy.sh`, from its GitHub release by version, refused
   unless its SHA-256 is the one written there (updated by hand: Dependabot does not read it); npm audit from the
   runner's Node.js. No third-party action does the scanning.
7. **The first scan, run in the development sandbox before the workflow existed,** found 48 known vulnerabilities
   with corrections in the locks of step 1: Pillow 12.3.0 (43, five CRITICAL; corrected in 13.0.0) in the portal's
   lock, and PyMongo 4.16.0 (5, three HIGH; corrected in 4.18.3) in all four. The same delivery moved Pillow to
   13.0.0 (`portal/requirements.in`: `>=13.0,<14`) and PyMongo to 4.19.0, also in the resolver's and the data entry
   API's pins (a deliberate change of the official services' versions, recorded in the CHANGELOG); 4.19.0 rather
   than the newest 4.20.1, released two days before, which had not yet had time to be reviewed by others.
8. **The first run on GitHub** (on 3d69fbb) built the five images, which proved that the locks install in them, and
   found HIGH vulnerabilities with corrections in two. The proxy's libxml2 was corrected in Alpine but not yet in
   the `nginx:1.30-alpine` digest: its Dockerfile now runs `apk upgrade --no-cache`, as the database image runs
   `apt-get dist-upgrade`. The database image's were all in files of the official `mongo:7-jammy` image that no
   update of ours can reach: `gosu` built with Go 1.24.6 (26, one CRITICAL), MongoDB's database tools with an old
   `golang.org/x/net` (one, in its HTML parser) and the entrypoint's `js-yaml` (three). Each was reviewed (what runs
   the file, what input reaches it) and accepted in `accepted.yaml` for those paths only, until 19 February 2027.
9. **Checks.** `test_supply_chain.py` also fails when the workflow misses a trigger, a lock, a toolkit or an image of
   the composition, writes outside the release job, stops failing on a correctable HIGH or CRITICAL vulnerability or
   attaching the SBOMs; when Trivy loses its version or hash check; when an accepted entry lacks a statement or a date
   or lasts more than 90 days; and it runs `audit.py` on made-up reports (a correction fails, none does not, an
   accepted identifier or alias counts until its expiry day, an unreadable or missing report fails).

## 3. Options considered

| Question | Chosen | Not chosen |
|---|---|---|
| Lock tool | uv (`uv pip compile --universal --generate-hashes`): one resolution valid for every platform, fast, the same `requirements.txt` format pip reads | pip-tools (one platform per run, slower; the format is the same, so either can write the files); Poetry or Pipenv (a new project format for three services that use plain requirements files) |
| One lock or one per service | one per service, each inside the tests' lock | one shared lock (every image would install the others' packages); independent locks (the tests could run versions no image has) |
| Base image references | tag and digest | digest only (unreadable, and Dependabot could no longer tell the line); tag only (the weakness) |
| Node.js | the official `node` image's binary, by digest | NodeSource's repository with its signing key (a third-party repository and an unpinned package); Debian's `nodejs` (version 18, too old) |
| Updates | Dependabot, grouped weekly, against the development branch | Renovate (an external application to install); none (a pinned digest no longer receives the line's security releases, which the tag used to bring at each `--pull`) |
| Scanning | in a second step, in a workflow of its own | inside the development tests' workflow (a vulnerability published overnight would turn every unrelated push red); now (the build of every image in the CI is a change of its own) |
| Image scanner and SBOM writer | Trivy, one tool for both, by version and SHA-256 from its release, a release more than two weeks old | Grype and Syft (two tools for the same result); Trivy's or Anchore's GitHub Actions (a third-party action by tag runs with the job's token: Trivy's own actions had their tags moved to a credential stealer on 19 March 2026, alongside a malicious Trivy 0.69.4, GHSA-69fq-xp46-6x23); Docker Scout (an account) |
| Python scanner | pip-audit (PyPI's and OSV's advisories), alongside Trivy's view of the same packages inside the images | Trivy alone (one advisory source for both); Safety (an account for the current database) |
| What fails | locks: any severity with a correction; images: HIGH and CRITICAL with a correction | everything found (the distributions' uncorrected vulnerabilities would keep it red); CRITICAL only (too late) |
| Accepted vulnerabilities | a reviewed list with statement, review date and an expiry of at most 90 days | `.trivyignore` identifiers without reasons; no list (one uncorrectable vulnerability would keep the workflow red until its correction) |

## 4. Consequences

- A build installs exactly what was locked or fails; a package, image or action replaced at its source is refused.
  The resolver's and the data entry API's images no longer run a downloaded script as root nor fetch an unpinned
  initializer, and no longer carry npm or curl.
- The portal moves from "newest within the range at each build" to the locked versions: its packages change only
  through a reviewed update (Dependabot's or the lock script's).
- Base images no longer pick up their line's security releases at each `docker compose build --pull`: they arrive as
  Dependabot's weekly proposal, merged after the tests. An operator who builds without merging keeps the digest of
  the release installed.
- A new Python dependency means editing a `.in` file and running `dev-tests/lock-dependencies.sh` (needs uv and PyPI);
  the check above fails otherwise. A new engine release also means its `package-lock.json` in both toolkits
  (`npm install --package-lock-only --save-exact gs1encoder@<release>`); the image build refuses a mismatch.
- The test tools' npm packages (`epc-tds`, `ajv-dist`, the CI's `gs1encoder`) and the CI's downloads (Docker Compose,
  nginx.org's package, GS1's repositories at fixed commits) are pinned by version or commit but not by hash; they never
  reach an image.
- A vulnerability published overnight turns the weekly run of the supply-chain workflow red without any change in the
  repository: the answer is an update (Dependabot's proposal or `lock-dependencies.sh --upgrade-package`), or, as a
  last resort, an entry in `accepted.yaml`. The development tests stay green meanwhile.
- The SBOM describes the image built by the release job from the tag; an operator's own build of the same tag
  installs the same locked packages and digests, but its system packages are those of the digest, so it matches the
  SBOM unless the repository's digests were updated in between.
- Trivy's version is updated by hand, after reading its release notes.

## 5. Delivery

Step 1 (21 November 2026): `requirements.in` and locked `requirements.txt` for `portal/`, `web_server/src/`,
`data_entry_server/src/` and `dev-tests/`; `dev-tests/lock-dependencies.sh`; `package.json` and `package-lock.json` in
both toolkits; the five Dockerfiles, `docker-compose.yml`, the two workflows and the composite action;
`.github/dependabot.yml`; `SECURITY.md`; the cloud sessions' hook. Checks in `dev-tests/install/test_supply_chain.py`.
Step 2 (21 November 2026): `.github/workflows/supply-chain.yml`; `.github/supply-chain/` (`audit.py`,
`accepted.yaml`, `install-trivy.sh`, `requirements.in` and `requirements.txt`); `dev-tests/lock-dependencies.sh` and
`.github/dependabot.yml` for the tools' lock; Pillow 13.0.0 and PyMongo 4.19.0 in the locks. Checks added to
`dev-tests/install/test_supply_chain.py`.
