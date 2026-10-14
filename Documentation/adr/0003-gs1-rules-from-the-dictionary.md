# ADR 0003 — One source for the GS1 rules: the GS1 Barcode Syntax Dictionary

| | |
|---|---|
| Status | **Accepted** (13 October 2026) and **implemented** in four steps: 1 (this record), 2 (one engine release), 3 (rules generated from the dictionary, the weekly check), 4 (engine messages translated, new AIs named); see section 3.6 |
| Backlog item | 2.5 — one source for the GS1 rules |
| Decided by | the owner of the branch, on the options of section 4 (all four recommended) |

## 1. Context

Three places hold GS1 rules today:

| Where | What | Release |
|---|---|---|
| `portal/gs1.py` | the 16 primary keys of GS1 Digital Link URI Syntax 1.7 and their formats, the key qualifiers and their paths, written by hand to mirror the GS1 Barcode Syntax Engine (`test_keys.py` compares them) | none: whatever was copied |
| `portal/syntax.py` | data attributes (§4.10): titles, formats and the AIs allowed in each key's path, read from the engine's `gs1-syntax-dictionary.txt`; values checked by the engine's C library | 1.4.1, pinned in `portal/tools/build-syntax-engine.sh` |
| `web_server/` (the resolver) and `data_entry_server/` | every request path, and every record the data entry API receives, checked by the engine's WebAssembly build (`callGS1encoder.js`) | **not pinned**: both Dockerfiles run `npm install gs1encoder`, so each build takes the latest release |

Consequences: a change of the dictionary (a new AI, a new qualifier, a new format) reaches the resolver at its
next build, unannounced, while the portal's hand-written tables stay as they were; the portal can accept a
record the resolver refuses, or refuse one it accepts. The development tests and CI pin 1.4.1 for both engines
in a third place (`.github/actions/dev-tests-setup/action.yml`). The engine's messages are English only and the
portal shows them as they come (`attr.invalid`), in a portal that is otherwise in Portuguese and English.

The dictionary of 1.4.1 (release 2026-01-27) already describes AIs (7041) UFRGT UNIT TYPE and (8040)–(8043)
IMEI, IMEI2, ESIM, PSIM. None of them is a GS1 Digital Link data attribute (no `?` flag) and none is a key or a
qualifier, so the portal never names them today.

## 2. Decision

1. **The rules of keys, qualifiers and formats come from the dictionary**, through a file generated from it,
   `portal/gs1_dictionary.json`, kept in git: every AI with its title, flags, components (type, length,
   linters), `req`, `ex` and `dlpkey`, and the release. A script (`portal/tools/gen_dictionary.py`) writes it from
   the engine's dictionary; a development test fails when the file differs from the pinned release's dictionary.
   `gs1.py` builds its tables from the file; the portal still works without the engine.
2. **What the portal deliberately does differently stays, in one list of exceptions** in `gs1.py`, each with its
   reason: ITIP without (22) (erratum E2), the narrower character sets of keys and qualifiers, the short names of
   the keys (from URI Syntax §4.3, which the dictionary does not carry). A key or qualifier whose format the
   portal cannot check yet (a linter it does not know) makes the generator and the tests fail, instead of being
   accepted unchecked.
3. **One engine release for the portal, the resolver and the data entry API, written once, in
   `docker-compose.yml`** (an extension field passed to the images as a build argument). The resolver and the data
   entry API install `gs1encoder@<release>`; the portal's
   build script builds that release; the CI set-up action and the development tests read it from the compose
   file; a test fails when any of them differs.
4. **Every message of the pinned engine is translated.** A table generated from the engine's source (its English
   error templates and its linters' messages) turns an engine message into a message code and parameters; the
   portal renders it in the user's language (`engine.*` keys in `i18n.js`, the English one being the engine's own
   text). A test fails when the pinned release has a message without a translation.
5. **A weekly scheduled job proposes updates**: a GitHub Actions workflow looks for a newer engine release; when
   there is one it regenerates the dictionary file and the message table for it, runs the portal's tests with it,
   and opens an issue (one per release) saying what changed: AIs added, removed or changed, new data attributes,
   messages without a translation, test results. Updating stays a reviewed change of the one release.
6. **AIs (7041) and (8040)–(8043)**: named wherever the portal names AIs (titles from the dictionary, Portuguese
   names beside the other 216), and accepted by the portal exactly as the dictionary says: today not as data
   attributes nor qualifiers. When a dictionary release makes them data attributes, they appear in the editor
   with no code change.

## 3. Design

### 3.1 `portal/gs1_dictionary.json`

```json
{"release": "1.4.1", "dictionary": "2026-01-27",
 "ais": {"01": {"title": "GTIN", "flags": "*?", "components": [{"type": "N", "min": 14, "max": 14,
          "optional": false, "linters": ["csum", "gcppos2"]}], "req": [], "ex": [["255"], ["37"]],
          "dlpkey": [["22", "10", "21"], ["235"]]}, …}}
```

Ranges (`3100-3105`) are expanded. `req` and `ex` keep the dictionary's groups (`01+21` is one group). The file
is written sorted, so a new release shows as a readable diff.

### 3.2 Keys and qualifiers built from the file

- **Primary keys**: the AIs with `dlpkey`. Each key's validator is chosen from the shape of its components: one
  numeric component with `csum` (GLN, SSCC, GSRN, GSIN, GTIN with its shorter forms); a numeric base with `csum`
  and an optional serial (GDTI, GCN, GRAI with its leading `zero`); GTIN + `pieceoftotal` (ITIP); alphanumeric with
  `gcppos1` (GINC, GIAI), with `csumalpha` (GMN), in character set 39 (CPID). Lengths, maxima and serial lengths
  come from the components. The portal's message codes stay as they are.
- **Qualifiers**: the AIs in the `dlpkey` sequences, in the dictionary's order; each sequence is a shape of
  optional qualifiers; a qualifier the key's `req` names becomes required (415 needs 8020). Formats from their
  components, with the linters `nozeroprefix` (8011) and `importeridx` (7040).
- **Linters the portal implements**: `csum`, `csumalpha`, `gcppos1`, `gcppos2`, `zero`, `pieceoftotal`,
  `nozeroprefix`, `importeridx`. Any other linter on a key or qualifier fails the generator.
- **Exceptions** (`PORTAL_EXCEPTIONS`): ITIP without (22) (erratum E2, the engine refuses 22 without 01);
  alphanumeric keys in letters, digits, `.` and `-`; qualifiers in letters, digits, `.`, `_` and `-`; CPID without
  `#` and `/`; the short names of the keys.
- `syntax.py` reads titles, data attributes and path AIs from the same file, so the editor offers data attributes
  from the pinned dictionary even before the engine is loaded (values are still checked by the engine).

### 3.3 One release

`docker-compose.yml` gains `x-gs1-syntax-engine: &gs1-syntax-engine "1.4.1"`, used as the build argument
`GS1_SYNTAX_ENGINE_RELEASE` of `web-service`, `data-entry-service` and the three services built from `./portal`.
The resolver's and the data entry API's Dockerfiles install `gs1encoder@${GS1_SYNTAX_ENGINE_RELEASE}`;
the portal's Dockerfile passes it to `build-syntax-engine.sh`. The CI set-up action reads the release from the
compose file. A development test checks that every place agrees and that `gs1_dictionary.json` was generated
from that release.

### 3.4 Engine messages

`portal/tools/gen_engine_messages.py` reads the pinned engine's `tr_EN.h` (about 95 templates) and its linters'
messages (about 85), and writes `portal/engine_messages.json`: for each, a code and a pattern that recovers the
parameters (`AI (%.*s) value is too long` → `engine.AI_VALUE_IS_TOO_LONG` with `ai`). `syntax.py` matches the
engine's message and answers `attr.engine` with the code and the parameters (the English text kept for the log);
the browser renders `engine.*` from `i18n.js`. A message no pattern matches is shown as today, in English.

### 3.5 The weekly job

`.github/workflows/engine-update.yml`: weekly and on demand; reads the pinned release; asks GitHub for the latest
release of `gs1/gs1-syntax-engine`; if newer and no issue with its title is open, builds it, regenerates the two
files into a work folder, compares them with the committed ones (`portal/tools/dictionary_diff.py`), runs the
portal group of the development tests against it, and opens an issue with the summary. Permissions: `contents:
read`, `issues: write`. It never changes the branch.

### 3.6 As implemented

- Step 2 put the release in `docker-compose.yml` and the build arguments in place; the weekly job came with step 3,
  because it needs the generator and the comparison (`portal/tools/dictionary_diff.py`), which also says whether the
  portal can build its rules from the new dictionary. The job uses the new release in its own copy of the
  repository (the compose value rewritten there), so the CI set-up action builds and installs it unchanged; only
  numbered releases count (the repository also has old date tags).
- `gs1dict.py` holds the parser and the reader; `gs1_dictionary.json` has one AI per line. The portal image copies
  every `*.json` of `portal/` with its modules (`test_deploy.py` starts the portal from the image's files).
- Beyond section 3.2: the browser no longer repeats lengths and formats either. `/config` sends `rules`
  (`gs1.browser_rules()`: each key's check as a kind and its numbers, each qualifier's pattern and maximum length,
  the order), and `app.js` checks from them; a Pay-to GLN (415), which had no live check in the browser, now has
  one. The qualifiers' names in `QUALIFIER_FORMATS` are now the dictionary's titles (they are not shown).
- Two keys' shapes are written differently and accept exactly the same records: 417 and 8004 were "alone, or with
  7040 required" and are now "7040 optional", as the dictionary writes them.
- Step 4, the messages (section 3.4 as built): release 1.4.1 has 94 templates and 117 linters' messages, all
  translated. The build script also copies the engine's message sources (`source/`) into the build. The parameters
  are numbered (`{p1}`, `{p2}`… in the order of the template), not named, since a template does not say what each
  one is; a linter's message, or another template's, inside a message is recognised as a message of its own
  (`AI (17): The date contains an illegal month of the year.` → `engine.AI_LINTER_ERROR` with `p1` `17` and `p2`
  `engine.lint.ILLEGAL_MONTH`), and the most specific template is tried first. The refusal keeps its code
  `attr.invalid` and its English `detail`, and gains `message` (code and parameters); the browser shows the
  translated text in place of `detail` (`i18n.js`). The association rules keep their own messages (`attr.requires`,
  `attr.pair`, `attr.unknown`), which name the AI as the user chose it. The recogniser is `portal/engine_messages.py`;
  `gen_engine_messages.py --summary` gives the weekly issue the messages that need a translation.
- The new AIs got Portuguese names (221 named in all); being neither data attributes nor qualifiers in 1.4.1, they
  appear only where a message names them.

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the portal's rules come from | a file generated from the dictionary, in git, checked by a test | the dictionary read at start-up (the engine would become mandatory); the engine validating everything (the Python checks and their messages gone, the portal dependent on the engine) |
| Where the release is written | `docker-compose.yml`, one value | a default in each Dockerfile and script, compared by a test; `.env` (each server on its own release) |
| Which engine messages are translated | all of the pinned release, checked by a test | the frequent ones; none |
| How updates are proposed | a weekly job that opens an issue | a pull request opened by the job (more permissions; CI does not run on a bot's pull request with the default token); a script run by hand |
| Deliveries | four steps | two larger steps |

## 5. Consequences

- A new dictionary release reaches the portal, the resolver and the data entry API together, only when the
  release in `docker-compose.yml` changes, after review; no service changes behaviour by being rebuilt.
- Pinning `gs1encoder` in the official Dockerfiles is a deliberate change to official code (CHANGELOG).
- The hand-written tables of `gs1.py` disappear; adding a key or qualifier the dictionary already describes needs
  no code, unless it brings a format the portal cannot check, which the tests then say.
- Engine messages appear in Portuguese; a new release with new messages is flagged by the weekly issue and by the
  tests before it is adopted.
- The weekly job needs GitHub's API without a token of the owner's: the default `GITHUB_TOKEN` with `issues: write`.

## 6. Configuration added

None in `.env`. `docker-compose.yml` holds the release (an extension field, read by Compose itself).

## 7. Delivery

1. This record (both languages).
2. One release (`docker-compose.yml`, the three Dockerfiles, the build script, the CI set-up action, a consistency
   test) and the weekly workflow.
3. `gs1_dictionary.json`, its generator and test; `gs1.py` and `syntax.py` built from it.
4. Engine messages translated; AIs (7041) and (8040)–(8043) named; documentation.
