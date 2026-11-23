# ADR 0055 — A public record of the security and resilience assessment

| | |
|---|---|
| Status | **Accepted** (23 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the owner's request of 22 November 2026 |
| Decided by | the owner, who asked for a public record of everything the assessment evaluated and fixed without opening gaps, and chose the recommended form: one document, `Documentation/security-assessment.md`, with a table of the fixed findings. Not taken: one public page per finding (more to keep in step, and a page per entry invites the detail a reproduction needs); publishing the private register once every finding is fixed (it holds places in the code, reproductions and experiment scripts, which the record must not); the changelog alone (it is ordered by delivery, not by finding, and says nothing of the method) |
| Amends | [ADR 0020](0020-security-assessment.md) §2.3 (public model, private findings): fixed findings now also have a public record |

## 1. Context

The assessment of [ADR 0020](0020-security-assessment.md) keeps concrete weaknesses in a private register until they
are fixed; the public documents are the threat model, which names gaps as missing *controls*, and the changelog, which
describes each fix at the level an operator needs. By 22 November 2026 every finding of the register (33 in the fork's
code, F-001 to F-033, and 6 in code that came from the official project, U-001 to U-006) was fixed on `gs1br/develop`
and released in 3.2.0. Nothing public said so in one place: what was looked at, how, what was found and fixed, and
with what proof. The resolver is meant for medicines and medical devices; a validation, an operator choosing the
software or GS1's maintainers reading the upstream pull request will ask for exactly that.

## 2. Decision

1. **`Documentation/security-assessment.md`** is the public record. It says why the assessment was made and what it
   covers; its method (the threat model, the phases, the confidence of a finding, the proof by a development test that
   fails before the fix, mutation checks, the continuous integration, the test plans run on staging, and what it is
   not: an independent penetration test); one table of the fixed findings; the resilience and performance work; the
   hardening still in progress, by category; and what operators should do.
2. **The table** has one row per fixed finding: its identifier, a **neutral title** that says what is stronger now,
   the area, the severity the finding had before its fix, the ADR, the commit that completed the fix and the release
   that carries it. The official project's findings are listed like the fork's own (the owner's decision of
   14 November 2026, ADR 0020 §2.3).
3. **Never in the record**: a weakness not yet fixed described as a weakness (open residuals appear only as *hardening
   in progress*, by category); steps or payloads that would reproduce a finding; the experiment scripts; internal host
   names, addresses or the staging installation; the private register's places in the code. The host's nginx
   (finding F-030) is said no more than as advice to keep it up to date.
4. **When a row is added**: only once the fix is on `gs1br/develop`, in the delivery that fixes it (the changelog,
   which is public, describes it there too). A release then carries it to `master`: the record recommends releasing
   soon after a security fix, so that installations that follow releases receive it.
5. **Links**: the README's documentation table, the documentation index, the threat model and `SECURITY.md` point to
   the record. The private register stays in the owner's folder; the record never links to it.

## 3. Consequences

- A reader sees in one page what the assessment covered and fixed, with the ADR and the commit to read further; a
  validation has a starting point that is not the code.
- The record is one more document to keep in step: each fix of a finding adds its row, each release fills its column.
- Open residuals stay invisible as weaknesses; the categories tell a reader that the work goes on, not where.

## 4. Delivery

`Documentation/security-assessment.md` (new); links in `README.md`, `Documentation/README.md` (the index and the ADR
list), `Documentation/threat-model.md` and `SECURITY.md`; this ADR and the amendment noted in ADR 0020; the rule added
to the repository's conventions for keeping documents in step.
