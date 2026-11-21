# Security policy

The GS1 Digital Link Resolver Suite answers the scans of printed codes, some of them on medicines and medical devices,
so a weakness can lead a person to wrong or missing information. Please report one privately, as below, and give us the
time to correct it before it is made public.

## Supported versions

| Version | Supported |
|---|---|
| The latest release (branch `master`, tag `vX.Y.Z`) | Yes |
| The development branch (`gs1br/develop`) | Yes: corrections land here first |
| Earlier releases | No: upgrade to the latest release |

## Reporting a vulnerability

- Use **GitHub's private vulnerability reporting**: the repository's *Security* tab, *Report a vulnerability*. The report
  is seen only by the repository's maintainers.
- Do not open a public issue, pull request or discussion about it.
- Say what is affected (service, file or address), how to reproduce it, the version or commit, and what an attacker or a
  person scanning a code would get. A proof of concept against your own installation is welcome; please do not test
  against installations you do not operate.

We aim to acknowledge a report within five working days and to agree a date for the correction and its disclosure with
you. Corrections are described in `Documentation/extensions/CHANGELOG.md` once released; you are credited there if you
wish.

## Code that came from the official project

The resolver, the data entry API and the database service started as the official GS1 Resolver Community Edition. A
weakness found in that code is corrected here and, with your agreement, reported to the official project's maintainers
as well.

## How the supply chain is protected

Every Python package is installed from a lock file with its file hashes, every npm package from `package-lock.json`,
every base image by digest and every GitHub Action by commit; Dependabot proposes the updates once a week. The
*Supply chain* workflow scans the lock files (pip-audit, npm audit) and the five images (Trivy) for known
vulnerabilities on every change and every week, and each release carries a CycloneDX SBOM of each image
(`Documentation/adr/0033-supply-chain.md`).
