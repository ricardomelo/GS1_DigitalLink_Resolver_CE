# ADR 0024 — The name GS1 Digital Link Resolver Suite and an About page

| | |
|---|---|
| Status | **Accepted** (15 November 2026) |
| Backlog item | the owner's request of 15 November 2026 (before F-005) |
| Decided by | the owner: the name *GS1 Digital Link Resolver Suite*; an About section in the portal's menu, on its sign-in page and in the home page's footer, in the twelve languages; the origin and every third-party component named with its licence. Taken as recommended under the owner's standing instruction: the details of sections 2.2 to 2.6 |

## 1. Context

The fork began as an *Expansion Pack* of the official GS1 Digital Link Resolver CE: a few conformance fixes and a
portal. It is now a link management suite — organisations, users, labels, EPC, domains, forwarding, monitoring, a
request log, an item's page, an installer — and the name undersells it. Its pages say *GS1 Resolver Community Edition*
(the official project's name, which an operator may replace since ADR 0019), and nothing in the software says what it
is, where its code lives, which version is running, under which licence, or what it is made of. The owner's other
tool, gs1-label-studio, has an About section with that information.

The name must keep *GS1*, *Digital Link* and *Resolver*, the words people search for. *Studio* was rejected: it sounds
like an editor only.

## 2. Decision

### 2.1 The name

1. **The project is called GS1 Digital Link Resolver Suite.** It replaces *GS1 Digital Link Resolver CE — Expansion
   Pack* in the README, the documents, the scripts' messages, the default privacy notice of the twelve languages and the
   tests. `Documentation/history.md` and the CHANGELOG's earlier entries keep the old name as history.
2. **The pages' default title becomes the new name**: the portal (its screens, sign-in, privacy notice, About), the
   home page and the resolver's pages (`RESOLVER_PRODUCT_NAME`'s default). An operator's own title (ADR 0019) still
   replaces it. It is a product name and is not translated, like *GS1 Resolver Community Edition* before it. An
   appearance stored before the change whose title is exactly *GS1 Resolver Community Edition* was saved with the title
   left empty: it is read as the new default, its colours and images kept (ADR 0019 §7).
3. **What the official project's integrations read keeps its name**: the resolver's description
   (`/.well-known/gs1resolver.json`, `"name"`) and the titles of the resolver's and the data entry API's OpenAPI
   descriptions stay *GS1 Resolver Community Edition*: they describe the official services, which the suite keeps
   (CLAUDE.md, *Keep the official project's names and behaviour*).
4. The fork remains a derivative work of the official GS1 Digital Link Resolver CE under the Apache License 2.0, and
   says so wherever the name appears for the first time (README, About). The name does not suggest that GS1 publishes or
   endorses it: the About page carries the trademark notice of `Documentation/third-party.md`.

### 2.2 Where the About page is

5. **One public page, `/portal/about`**, like the privacy notice (ADR 0017): open to anyone, signed in or not, in the
   reader's language, with the same header (operator's title and logo) and footer. Linked from:
   - the portal's user menu and its sidebar (*About*, for every role, before *Options*);
   - the sign-in page's footer, beside *Privacy notice*;
   - the home page's footer, beside *Privacy notice*.
   The resolver's pages (item's page, error pages) do not link it: they belong to the brand owner's product.

### 2.3 What it says

6. In this order:
   1. **What it is**: the name, one sentence (a resolver for GS1 Digital Link with a portal to manage links,
      organisations and labels), and *operated by* the operator's name when one is set.
   2. **Version**: the published version (`git describe --tags`, e.g. `v3.1.1-42-g1a2b3c4`), the commit (short hash,
      linked to that commit in the repository) and its date.
   3. **Source code and licence**: the repository's address, the Apache License 2.0 (linked to `LICENSE` at that
      commit) and one sentence: free to use, change and redistribute, commercially or not; provided "as is".
   4. **Documentation**: the portal's user guide, the README (installation and operation), the developer guide, the
      features list and the changelog, each linked at the running commit, so the manual matches the software.
   5. **Origin**: built on the official GS1 Digital Link Resolver CE (linked to `github.com/gs1/GS1_DigitalLink_Resolver_CE`),
      © GS1 AISBL, Apache 2.0; changes recorded in the changelog (Apache 2.0, section 4 b).
   6. **Made with**: every third-party component and data source with its licence and a link to its project, in four
      groups — *GS1 standards and tools*, *Platform*, *Libraries*, *Data and fonts* — and a link to
      `Documentation/third-party.md` for the full text (what each is used for, MongoDB's SSPL, the operator's duties).
   7. **Trademarks and responsibility**: *GS1*, the GS1 logo and *GS1 Digital Link* are trademarks of GS1 AISBL; this
      software is maintained by its community, not by GS1 or any GS1 Member Organisation; whoever operates the
      installation is responsible for it (the footer's notice, already in the twelve languages).
7. **The list of components is data, not text**: `portal/third_party.json` (name, group, licence, project address).
   Only the group headings and the sentences are translated; names and licences are not. A development test fails
   when a component of `Documentation/third-party.md`'s tables is missing from the file, or the other way round.

### 2.4 The version shown

8. **Written when the portal's image is built**, from the checkout's own Git data: `docker-compose.yml` gives the
   portal's build an additional context `git-dir: ./.git`; a separate stage of `portal/Dockerfile` (the same Python
   image, `git` installed there only) runs `git describe --tags --always`, `git log -1 --format=%H %cI` and
   `git remote get-url origin`, and writes `/app/version.json`. The final image receives that file alone, not the
   history. The usual update, `git pull && docker compose up -d --build`, refreshes it with no other step.
9. **The repository's address comes from the checkout's `origin`**, made a public `https://` address (an `ssh`
   address is rewritten, user names and tokens are removed). No organisation's or maintainer's address is written in
   the code: an installation cloned from the official repository, or from another fork, shows its own.
10. **Without Git data** (the development tests, a copy without `.git`): `version.json` is absent; the portal asks
    `git` in its own folder when it can, otherwise the page says *version unknown* and links the documents of the
    official repository's default branch. A broken or absent file never stops the portal.
11. `GET /portal/api/about` returns `{version, commit, date, repository, operator, components}` for anyone; the page is
    drawn from it. It names no secret, setting or host.

### 2.5 Languages

12. Every new text in the twelve languages (`i18n.js`, `locales/<tag>.json`, `home.js`); translations other than
    pt-BR and en-GB are drafts, as always (ADR 0014).

### 2.6 What the owner changes outside the code

13. The GitHub repository's name and description (Settings), the upstream branch's pull request text
    (`pr-body-upstream.md`) and gs1-label-studio's About, which names the old name. A renamed repository keeps
    redirecting its old address, so clones and the upgrade script keep working.

## 3. Consequences

- Operators see the new name on their pages after an update, unless they set their own title.
- Every image build of the portal reads `.git`: the stage that runs `git` is rebuilt at every commit; the final image
  only gains one small file.
- The upstream branch offered to GS1 carries the new name as well; GS1 may ask for another, and the pull request says
  so.

## 4. Alternatives not taken

- *Keep "Expansion Pack"*: the owner's decision is a new name.
- *The version as a build argument filled by the installer*: `docker compose up -d --build` alone, the documented
  update, would show no version.
- *The About as a screen of the portal's application*: people who are not signed in (the sign-in page, the home page)
  could not open it.
- *Hand-written translated descriptions of every component*: 50 names in twelve languages, out of step with
  `third-party.md`; the full descriptions stay in that document.
