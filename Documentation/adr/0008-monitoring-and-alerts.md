# ADR 0008 — Monitoring and alerts by e-mail

| | |
|---|---|
| Status | **Accepted** (14 October 2026). Implemented in one delivery |
| Backlog item | 4.3 — monitoring and alerts by e-mail |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

An installation fails quietly: a resolver that stops answering is noticed by whoever scans a code, a daily backup
that fails (as on 14 October, ADR 0006 section 3.4) by whoever needs it, an expired certificate by every phone at
once. Item 4.1 showed that a printed code nobody registered produces 404s nobody sees. The backlog asks for
**monitoring and alerts by e-mail**: the resolver down (checked through the proxy), a failed backup, spikes of 404,
certificate expiry. E-mail exists since item 3.1 (ADR 0004): an authenticated relay, a queue of messages sent by the
worker, categories that users may switch off.

Constraints:

- No new service and no external monitoring system: the job worker (ADR 0001) already runs in every installation.
- The worker runs in several replicas: a check must be made once, and an alert sent once.
- An alert that repeats every few minutes is switched off and then ignored: one message when something goes wrong,
  one when it is right again, and a reminder a day while it lasts.
- The backup runs on the host (cron), outside the containers; the worker cannot read the host's files.
- Organisations see only their own codes (ADR 0002): a spike of 404 on an organisation's prefixes is told to that
  organisation's administrators; the installation's problems to the server administrators.

## 2. Decision

1. **The worker checks every 5 minutes** (`PORTAL_MONITOR_MINUTES`), outside any job, under a lock (`monitor`) that
   one replica takes without waiting; the others skip that round.
2. **Four checks**, each with a state kept in the portal's collection `alerts` (`ok`, `alert`, `unknown`):
   - **resolver** — a request **through the proxy** (`PORTAL_MONITOR_URL`, by default the resolver's description
     file `http://frontend-proxy-service/.well-known/gs1resolver`) must answer 200 within 10 seconds; and, when
     `PORTAL_MONITOR_PROBE` names a GS1 Digital Link path of a registered code, that path a 2xx or 3xx. An alert after
     **two failed rounds in a row** (a restart is not an outage);
   - **backup** — the backup script records each run in the portal's database (setting `backup.last`: when, OK or
     the error, the file and its size). An alert when the last run failed, or when the last good one is older than
     `PORTAL_MONITOR_BACKUP_HOURS` (26); unknown until the first run is recorded;
   - **certificate** — a TLS connection to `PORTAL_MONITOR_TLS_HOST` (by default `FQDN`) on port 443, once an hour:
     an alert when the certificate expires within `PORTAL_MONITOR_CERT_DAYS` (21) or is already invalid; unknown
     when the host cannot be reached (no message: a server that cannot reach its own name is common behind NAT) or
     when the host is `localhost` (development);
   - **404 spikes** — requests answered "code not registered" (outcome `unknown`) in the last hour, for the whole
     installation and for each organisation: a spike when they are at least `PORTAL_ALERT_404_MIN` (20) **and** at
     least `PORTAL_ALERT_404_FACTOR` (3) times the hourly average of the 7 days before (from the daily counts); the
     message names the most requested codes.
3. **Messages**: a message when a check goes into alert, a reminder every 24 hours while it lasts, and a message when
   it is resolved (except for 404 spikes, which simply end). The category **alerts** is optional and **on by
   default**; each user may switch it off in Options → E-mail. Recipients: server administrators for the resolver,
   the backup, the certificate and the installation's spikes; an organisation's administrators for its spikes.
4. **Shown in the portal**: the overview's *Operation* group lists the active alerts of the scope (server
   administrators: every one; an organisation's administrators and users: its spikes) and the state of each check.
5. **The backup script writes its result** with `mongosh` inside the database container (the root credentials stay
   in the container), and a failure to write it never fails the backup.

## 3. Design

### 3.1 State (`alerts`, `portal/monitor.py`)

```
{_id: "resolver" | "backup" | "certificate" | "logspace" | "404:*" | "404:<tenant id>",
 state: "ok" | "alert" | "unknown", since, checkedAt, failures (resolver), detail: {…},
 notifiedAt (the last message), notifiedLevel (logspace: the step last told), tenant (404 of an organisation)}
```

`logspace`, the request log's space against its limit, was added on 20 October 2026
(ADR 0006, section 9): an alert from 80 % of the limit with a message at each further step of 5 points, no reminder.

`run()` (in `app.MONITORING`) takes the lock, runs each check, updates its document and decides the messages:
`ok → alert` sends *alert*, `alert` for 24 hours more sends *reminder*, `alert → ok` sends *resolved* (not for spikes).

### 3.2 The backup's record

`scripts/resolver-backup.sh` ends (OK or ERROR) with:

```
docker compose exec -T -e BACKUP_OK=… -e BACKUP_FILE=… -e BACKUP_SIZE=… -e BACKUP_ERROR=… database-service \
  sh -c 'mongosh … "$PORTAL_DB_NAME" --eval "db.settings.replaceOne({_id: \"backup.last\"}, …, {upsert: true})"'
```

### 3.3 Messages (`mailtexts.py`, category `alerts`)

`alert-resolver-down`, `alert-resolver-up`, `alert-backup-failed`, `alert-backup-ok`, `alert-certificate`,
`alert-certificate-ok`, `alert-404-spike`; `alert-log-space`, `alert-log-space-ok` (ADR 0006, section 9); in every
language of ADR 0014.

### 3.4 Configuration

| Variable | Default | |
|---|---|---|
| `PORTAL_MONITOR_MINUTES` | 5 | how often the worker checks; 0 switches monitoring off |
| `PORTAL_MONITOR_URL` | `http://frontend-proxy-service/.well-known/gs1resolver` | the resolver through the proxy |
| `PORTAL_MONITOR_PROBE` | empty | a GS1 Digital Link path of a registered code, checked through the proxy too |
| `PORTAL_MONITOR_BACKUP_HOURS` | 26 | the longest time without a good backup |
| `PORTAL_MONITOR_TLS_HOST` | `FQDN` | the host whose certificate is checked (empty or `localhost`: not checked) |
| `PORTAL_MONITOR_CERT_DAYS` | 21 | an alert when the certificate expires within this many days |
| `PORTAL_ALERT_404_MIN` | 20 | the fewest 404 `unknown` in an hour that make a spike |
| `PORTAL_ALERT_404_FACTOR` | 3 | how many times the usual hourly number a spike is |

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Who checks | the job worker, every 5 minutes, under a lock | a new monitoring service (another moving part); an external SaaS monitor (outside the installation, needs an account); cron on the host (cannot send the portal's messages) |
| Resolver check | through the proxy, two failed rounds | the web service directly (misses a broken proxy); one failed round (alerts on every restart) |
| Backup | the script records its result in the database | the worker reads the host's log (not mounted); a mounted backup folder (another volume, permissions) |
| Certificate | TLS to the public name from the worker | reading `/etc/letsencrypt` (host files, Certbot only); the backup script (once a day, on the host) |
| 404 spikes | per hour, absolute minimum and a factor of the 7-day hourly average | a fixed threshold (wrong for both small and large installations); per key (too many messages) |
| Repetition | alert, a daily reminder, resolved | every round (noise); only the first (forgotten) |
| Category | optional, on by default | always on (cannot be silenced by a user who is not responsible); off by default (nobody would know) |

## 5. Consequences

- Installations with e-mail get alerts without configuration; without e-mail the states are still shown in the
  overview.
- The backup script needs the portal's database name (`PORTAL_DB_NAME`, `resolver_portal` by default); an old
  installation keeps working, its backups simply are not seen until the script is updated (`git pull`).
- A worker replica spends a few seconds every 5 minutes on the checks.
- The certificate check needs the server to reach its own public name; where it cannot, the state stays unknown.

## 6. Delivery

One delivery: this record; `portal/monitor.py`, the worker's second schedule, the category and messages, the backup
script's record, the overview's alerts; `test_monitor.py`, `test_deploy.py` (the script's record); the
documentation.
