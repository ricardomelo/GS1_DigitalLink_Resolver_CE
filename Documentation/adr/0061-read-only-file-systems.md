# ADR 0061 — Read-only file systems for the Python services

| | |
|---|---|
| Status | **Accepted** (28 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-I1 and control G-11 of the [threat model](../threat-model.md); the second residual of finding F-012 ([ADR 0030](0030-least-privilege-services.md)) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — `read_only: true` and a size-limited `/tmp` in memory for the resolver, the data entry API, `portal-db-init`, the portal and its worker. Not taken: the proxy and the database (below); a `/tmp` on disk (a volume would keep what an attacker wrote across restarts) |
| Amends | [ADR 0030](0030-least-privilege-services.md) (its residual *read-only file systems not done*) |

## 1. Context

Since ADR 0030 the Python services run as an unprivileged user (uid 10001), but their root file system stayed
writable wherever that user may write. A flaw that lets a request write a file — in the services' own code or in a
library — could leave something behind for the process to load later, or fill the container's disk.

## 2. Decision

1. **Read only.** `docker-compose.yml` gives the resolver (`web-service`), the data entry API, `portal-db-init`, the
   portal and the worker `read_only: true` (YAML anchors `x-read-only` and `x-read-only-portal`).
2. **`/tmp` in memory.** Each has a `tmpfs` on `/tmp`, emptied at every start: 64 MB for the resolver, the data entry
   API and `portal-db-init` (gunicorn's worker files), 256 MB for the portal and the worker, whose spreadsheet exports
   write each sheet through temporary files (openpyxl) and whose uploads of large files may spool there.
3. **What stays writable.** The portal's and the worker's configuration volume (`/app/config`: the keys made when
   none is given, files moved once into the database); the resolver's GeoIP folder stays read only. Nothing else:
   the images already avoid writing (`PYTHONDONTWRITEBYTECODE` in the portal; the Python files of the two official
   services cannot be compiled to bytecode and run from source).
4. **Not read only.** The proxy writes its configuration from its settings when it starts (`api-access.sh` into
   `/etc/nginx`) and nginx needs `/var/cache/nginx` and its PID file; the database is the official MongoDB image
   (its entry point writes during the first initialisation). Both keep a writable file system: a residual.

## 3. Consequences

- A process of the five services can write only to `/tmp`, in memory and bounded, and the portal also to its
  configuration volume.
- Running a shell in such a container (`docker compose exec`) and editing a file there no longer works; changes go
  through the repository and a build, as they should.
- A library that tries to write a cache outside `/tmp` fails at that point: the operator's test plan exercises the
  portal's labels, exports, imports and link checks on staging after the update.

## 4. Checks

`test_least_privilege` (each of the five services read only with `/tmp` of its size; no writable volume but the
portal's configuration; the proxy and the database not read only). 3 mutations, all caught. The services running
read only are verified on staging (the containers cannot be started in the development sandbox).
