# ADR 0030 — The official services without MongoDB's root user, as users of their own; loopback by default

| | |
|---|---|
| Status | **Accepted** (17 November 2026); its residual on read-only file systems answered for the Python services by [ADR 0061](0061-read-only-file-systems.md) (28 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threats T-I1 and T-I2 and controls G-2 and G-11 of the [threat model](../threat-model.md) |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): a MongoDB user per official service made by portal-db-init, images that do not run as root, the host's loopback address as the default, the example passwords refused |

## 1. Context

The resolver (`web-service`) parses every anonymous request that reaches the installation; the data entry API
(`data-entry-service`) every request of the systems allowed to call it. Both connected to MongoDB with
`MONGO_URI`, **MongoDB's root user**: a flaw in either — in its code, in a library, in the GS1 toolkit's Node.js
process the resolver starts — would hand the attacker every database, the portal's users, sessions, API keys and
journal included, and the right to create users. The portal had already been given a user of its own
([ADR 0001](0001-portal-state-in-mongodb.md), section 3.1); the two services that came from the official project had
not. Both also ran as `root` inside their containers.

Started without `.env` (a manual `docker compose up -d`), the composition published MongoDB (port 27017) and the proxy
(port 8080) on **every interface** of the host, with the public example credentials of `.env.example`. The installer
writes loopback addresses and new secrets; a manual start did not, and nothing refused to start.

## 2. Decision

### 2.1 A MongoDB user per official service, made by portal-db-init

`portal-db-init` (`portal/db_init.py`, the one-shot service that already makes the portal's user at every
`docker compose up`) also creates, or brings up to date, two users in MongoDB's `admin` database, each with a role of
its own defined there (a role defined in another database may hold privileges on that database only):

| Service | User (setting, default) | Role | Privileges |
|---|---|---|---|
| resolver | `RESOLVER_DB_USERNAME`, `resolver_web` | `resolverService` | `find` on `resolver_ce.gs1resolver` and on the portal's `tenants`, `domains`, `settings`, `branding` and `forwarding_rules`; `insert`, `update` and `createIndex` on `resolver_log.requests` and `resolver_log.request_counts` |
| data entry API | `DATA_ENTRY_DB_USERNAME`, `resolver_data_entry` | `dataEntryService` | `find`, `insert`, `update` and `remove` on `resolver_ce.gs1resolver` |

The passwords are `RESOLVER_DB_PASSWORD` and `DATA_ENTRY_DB_PASSWORD`; like the portal's, the password in `.env` is
applied at every start, so a missing or rotated one needs no step in the database. A service whose password is empty is
left as it is, with a warning; MongoDB's root user is refused as a service's user. The resolver's role follows
`PORTAL_DB_NAME`.

The resolver may not read the portal's users, sessions, API keys, single sign-on configurations, jobs or journal, nor
write anything but its request log; the data entry API sees nothing but the records. Neither can create users.

### 2.2 The services connect as their users; only portal-db-init holds the root connection

`web-service` and `data-entry-service` receive `MONGO_URI` and `MONGO_INITDB_ROOT_*` **empty**, as the portal and its
worker already did, and start after `portal-db-init` has finished well (`service_completed_successfully`).
`service_db.uri(prefix)` (one file, copied into both images) builds their connection from `<PREFIX>_DB_USERNAME`,
`<PREFIX>_DB_PASSWORD` and `<PREFIX>_DB_HOST` (default `database-service:27017`, `authSource=admin`), or takes a
complete `<PREFIX>_DB_URI`; with neither, it falls back to `MONGO_URI` with a warning, which serves a service started
by hand only. The log names the host, never the credentials.

### 2.3 The images do not run as root

The resolver's and the data entry API's Dockerfiles create a system user (`useradd --system`, uid 10001) and switch to
it (`USER`) before the command, as the portal's image already did. Nothing in `/app` is written at run time; gunicorn
uses `/tmp`, and the Node.js process the resolver starts for compressed links only reads its files.

### 2.4 The host's loopback address by default

`docker-compose.yml` publishes MongoDB and the proxy on `127.0.0.1` unless `.env` names another address
(`DATABASE_BIND_ADDRESS`, `PROXY_BIND_ADDRESS`, both still read by Compose). The installer writes both as before
(loopback, or `0.0.0.0` for an external proxy on another machine), so an installation made by it is unchanged; a
manual start without `.env` no longer exposes the database or plain HTTP to the network.

### 2.5 The example passwords refused

`example_secrets.py` ([ADR 0021](0021-data-entry-api-closed.md), section 2.7) adds the example values of the two new
passwords: outside development (`FQDN` a real host) the resolver refuses to start with `RESOLVER_DB_PASSWORD=resolver_web`
and the data entry API with `DATA_ENTRY_DB_PASSWORD=resolver_data_entry`, naming the setting. MongoDB's example root
password stays a warning, now printed by `portal-db-init` (the only service that holds it), for the reason ADR 0021
gives: the installer keeps it for a database created with it, and `scripts/rotate-secrets.sh mongo` changes it.

The installer generates both passwords when they are missing or the examples (an existing installation gets them at
its next run); `scripts/rotate-secrets.sh` rotates them (`resolver-db`, `data-entry-db`, among the default set).

## 3. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Who makes the users | `portal-db-init`, at every start | MongoDB's `/docker-entrypoint-initdb.d` (runs on an empty volume only: existing installations would never get the users); a new one-shot service (a second image and step for the same root connection) |
| Granularity | roles with privileges per collection | MongoDB's built-in `read`/`readWrite` per database (the resolver would read the portal's users, sessions and keys) |
| Where the users live | `admin`, with roles defined there | each service's database (a role there cannot reach the portal's or the log's database) |
| An existing `.env` without the new passwords | the example values of `.env.example`, refused outside development until the operator adds new ones (or reruns the installer) | a password derived from the root password (the services would need the root password again); a silent fallback to `MONGO_URI` in the composition (keeps the weakness) |
| The root password | warned about, held by `portal-db-init` only | refused (would stop installations upgraded from the official project with its default) |
| Published ports | loopback by default | no published MongoDB port at all (the backup and the operators' tools run inside the container already, but some operators connect from the host) |

## 4. Consequences

- A flaw in the resolver or the data entry API no longer reaches the portal's users, sessions, keys or journal, nor
  lets an attacker create database users; the resolver cannot change a record.
- **An existing installation must add the two passwords before updating** (or rerun the installer): without them the
  resolver and the data entry API refuse to start on a real domain. The release notes and the staging steps say so:
  `grep -q '^RESOLVER_DB_PASSWORD=' .env || printf 'RESOLVER_DB_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> .env`, the
  same for `DATA_ENTRY_DB_PASSWORD`, then `docker compose up -d --build`.
- The resolver and the data entry API start a few seconds later (after `portal-db-init`); if it fails (the database
  unreachable, the root credentials wrong), they do not start, as the portal already did not.
- A manual start without `.env` answers on `http://127.0.0.1:8080` only; to reach it from another machine, set
  `PROXY_BIND_ADDRESS=0.0.0.0` in `.env` (or use the installer).
- The resolver reads every document of the five collections of the portal's database it is given; nothing secret may be stored there (single
  sign-on configurations, users, sessions and API keys are in collections of their own). A new collection the resolver
  reads needs its privilege here; `dev-tests/install/test_least_privilege.py` fails until it has it.
- The proxy (nginx) still starts as root and serves through its worker processes, as the official image does; MongoDB's
  own image runs as its `mongodb` user.

## 5. Delivery

In one step (17 November 2026): `portal/db_init.py` (`service_users()`, `resolver_privileges()`,
`data_entry_privileges()`, `ensure_user()`, `root_username()`, the root password's warning); `service_db.py` (new, in
`web_server/src` and `data_entry_server/src`); both services' `__init__.py`; `example_secrets.py` (three copies); both
Dockerfiles; `docker-compose.yml`; `.env.example`; `scripts/install.sh`; `scripts/rotate-secrets.sh`. Checks in
`dev-tests/install/test_least_privilege.py` (new), `dev-tests/install/test_deploy.py`,
`dev-tests/install/test_install.sh` and, against a real MongoDB, `dev-tests/portal/test_store_mongodb.py`.
