# Working on this repository with Claude Code

Instructions for Claude Code sessions on the **GS1 Digital Link Resolver CE — Expansion Pack** (branch
`gs1br/develop`, the default). The state of the work, the next item and anything not meant for a public
document arrive in the maintainer's handover at the start of each session; read it first. The README's
*Open backlog* is the reference for the items.

## Language

- Code, comments, identifiers, commit messages and every document: **British English only**. There are no
  Portuguese documents (since 14 October 2026); do not write any unless asked.
- User-facing texts of the software (portal, resolver pages, item's page, home page, e-mail messages) are in **twelve
  languages**: pt-BR, en-GB, es, fr, de, it, tr, zh-Hans, ja, ko, hi and ar (right to left; ADR 0014). **Every delivery
  ends with its texts in every language**: `portal/static/i18n.js` (pt-BR, en-GB) and `portal/static/locales/<tag>.json`,
  `portal/mailtexts.py` and `portal/mail_languages.json`, `web_server/src/page_texts.json`,
  `frontend_proxy_server/home/home.js`. `dev-tests/portal/test_i18n.py` fails on a text missing, empty or with other
  `{placeholders}` in any language. Translations other than pt-BR and en-GB are drafts until a native speaker reviews
  them; write new ones with `Documentation/translation-glossary.md`.
- The UI says *organisation / organização* and *Requests / Acessos*; code and technical documents say *tenant*
  and *request log*.
- Keep the official project's names and behaviour unless a change is deliberate and recorded in the CHANGELOG.
- No organisation name, domain or maintainer in the code or in public documents. Never ask for or print
  secrets.

## Commits and delivery

- Push straight to `gs1br/develop` (`git push -u origin gs1br/develop`); fetch and rebase first. Pushed
  commits are never rewritten.
- One topic per commit, with a message that explains why. Subjects carry an area prefix (`portal:`, `docs:`,
  `resolver, portal:`, `scripts:` …). Code and its technical documents go in one commit; then a `docs:` commit
  with the CHANGELOG, `features.md` and `history.md` citing the code commit's hash.
- Commit authorship and trailers: as the handover says.
- After a push that changes code or `dev-tests/`, read the CI run (`gh run list`, `gh run view --log-failed`).
  Pushes of documentation only (`Documentation/**`, `*.md`) start no run. The *database* job is
  `continue-on-error`: read each job, not only the run's colour.
- Claude cannot reach the staging server: give the maintainer the commands (`git pull`, and
  `docker compose up -d --build` after code changes; a backup first when stored data or services change), the
  expected output and a short browser checklist. A longer verification goes into a Claude Docs test plan with
  checkboxes. New settings go into `.env` with `printf … >> .env`, guarded by `grep -q '^NAME=' .env ||`.

## Keep the documents in step

- A user- or operator-visible change updates `Documentation/extensions/CHANGELOG.md`,
  `Documentation/features.md` and `Documentation/portal-user-guide.md`.
- `Documentation/developer-guide.md` changes with an endpoint, file, collection, service or function, and holds
  the check counts (section 13); `dev-tests/README.md` lists every test program.
- A new test program needs a `Program(...)` line in `dev-tests/test_programs.py`.
- Each feature row of `Documentation/features.md` cites the checks that prove it (*Checks* column); after adding or
  renaming checks, regenerate `Documentation/test-inventory.*` and the counts of the developer guide (section 14 there,
  *A feature, or a check*); `dev-tests/docs/test_docs.py` fails when they are out of step. A change to
  `portal/openapi.json` regenerates `Documentation/api-reference.md` (`portal/tools/gen_api_reference.py`).
- An ADR (`Documentation/adr/`) records deviations in the same delivery; a large item starts with its ADR.
- The README's *Open backlog* loses an item when it is done or dropped; `Documentation/history.md` records each
  session.
- A new e-mail message needs every language (`mailtexts.py`, `mail_languages.json`) and a category in
  `notify.TEMPLATES`. A new route under `/portal/api/v1` needs its description in `portal/openapi.json`, and every new
  message code every language (`i18n.js` and `locales/`).
- A new field in the request log's event: `request_log.event()`, ADR 0006 §3.1, `requestlog.row()`, the CSV
  columns, the developer guide and `test_request_log.py`'s list of documented fields.

## Tests

The session start hook (`.claude/hooks/session-start.sh`) installs the same pieces and pinned versions as the
CI (`.github/actions/dev-tests-setup/action.yml`) into `~/.cache/dev-tests` and exports the variables the
programs read. Every test must pass before a push.

```bash
DEV_TESTS_STRICT=1 python3 -m pytest dev-tests -m "resolver or portal or home or install"   # about 3 minutes
DEV_TESTS_STRICT=1 python3 -m pytest dev-tests -m e2e                                       # about 7 minutes
python3 -m pytest dev-tests -k requestlog                                                   # one program
```

- Run long groups in the background and poll; a background run can die when the environment pauses: rerun,
  never assume.
- The sandbox cannot reach MongoDB downloads or Docker Hub: the portal's database is `mongomock`, and the
  `database` group (`test_store_mongodb.py`) runs on CI only. mongomock deletes documents whose TTL date has
  passed when they are read: check what was written, not only what a query returns.
- Prove a new check can fail (mutation checks); restore every mutated file and compare checksums.
- After a visual change, `python3 dev-tests/docs/screenshots.py` regenerates the guide's images; commit only
  those whose content changed.
- No linter is configured: `python3 -m py_compile` for Python, `node --check` for JavaScript.

## Working with the maintainer

- The conversation is in Portuguese. The maintainer is new to Git and prefers step-by-step instructions with the
  expected output.
- Questions: 2–3 options with the recommended one first. When the maintainer is away, take the recommended
  option, say so at the top of the work, and carry on.
- Before implementing a screen, show mock-ups: drive the real portal with Playwright, inject HTML/CSS and
  deliver PNGs.
- At the end of each backlog item or step of a large item, or when the conversation has grown long, write an
  updated handover for the next session.
