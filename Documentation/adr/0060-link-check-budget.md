# ADR 0060 — A daily budget of link checks per organisation

| | |
|---|---|
| Status | **Accepted** (28 November 2026); §5 (the same day): one check per organisation, atomically (the second residual of finding F-011) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-S2 and control G-17 of the [threat model](../threat-model.md); the first residual of finding F-011 ([ADR 0029](0029-outbound-requests.md) §3) |
| Decided by | the owner's standing instruction for the assessment's residuals (every residual, one per delivery, in the proposed order), the owner away: the recommended option taken — a number of addresses each organisation may have checked a day, counted atomically when a check is asked for, the same for every organisation, set by the operator. Not taken: a limit per organisation set in the portal (a screen and a setting for a need nobody has named; the operator's one number can be raised); counting only the requests actually made (cached answers are cheap, but the count would be known only as the check runs, after it was accepted); giving back what a stopped check did not request |
| Amends | [ADR 0029](0029-outbound-requests.md) §3 (*Limits*: a daily budget was not chosen then) |

## 1. Context

Every editor can ask the portal to check the targets of every record of the organisation (up to 5,000 addresses a
check, one check of the organisation at a time) or of one record (up to 20, answered at once and not a job). Nothing
bounded how many checks a day an editor could ask for, so the server could be made to send an unbounded number of
requests to third parties, whatever ADR 0029's limits per check and per host.

## 2. Decision

1. **A day's budget per organisation.** `linkcheck.reserve(tenant, count)` counts the addresses a check asks for in
   a document per organisation and day of the installation (`PORTAL_TIME_ZONE`) in the collection
   `linkcheck_budget` (`{_id: "<tenant or ->|<day>", tenant, day, n, expiresAt}`, deleted two days later by a TTL
   index). The operator's codes (no organisation) have a day of their own.
2. **Atomic.** One conditional update with `upsert` (`n` at most the limit less the count); when the day's document
   does not leave room the insert fails on its `_id` and the check is refused with nothing counted, so two checks
   started at once cannot both pass the limit.
3. **Where.** The check of many addresses (`POST /portal/api/links/jobs`: every record, or the import's preview)
   counts its addresses after the limits of ADR 0029 (5,000, one at a time), before the job is queued; the record's
   own check (`POST /portal/api/links/check`) counts its distinct addresses. A refusal answers **422
   `linkcheck.budget`** with `max` and `left` (twelve languages) and an audit line
   `action=linkcheck-refused reason=budget`.
4. **How much.** `PORTAL_LINKCHECK_DAILY_LIMIT`, by default **20,000** addresses a day (four checks of every record
   at the largest size); 0 switches the budget off; a value that is not a whole number is logged and the default
   applies. Addresses are counted when asked for, cached or not, and a stopped check gives nothing back.
5. **When the database cannot be written** the check goes ahead (logged): a check of many addresses cannot be queued
   without the database anyway, and the record's own check is at most 20 addresses.

## 3. Consequences

- An editor cannot make the portal send more than the day's budget of requests to third parties for the
  organisation; the next day (of the installation's time zone) starts again.
- An organisation that checks every record of a large catalogue several times a day may reach the limit; the operator
  can raise it in `.env`. The message says how many addresses are left today.
- One more small collection in the portal's database (one document per organisation and day).

## 4. Checks

`test_linkcheck` (the default and a malformed value, counting, a refusal with what is left and nothing counted,
exactly what is left, other organisations and the operator, more than a day at once, the document and its expiry, the
next day, 0, a database that cannot be written) and `test_jobs` (a check of many addresses refused before it is
queued with `max` and `left`, what is left still checked, the record's own check refused, each address counted once).

## 5. One check per organisation, atomically (28 November 2026)

The second residual of finding F-011: `start_link_job()` tested for a check of the organisation queued or running
(`jobs.active()`, ADR 0029) and then created the job, so two starts at the same moment — two editors, or two replicas
of the portal — could both pass the test and queue two checks. The owner was away; the recommended option was taken.

- The test, the budget's reservation (§2) and the job's creation run under one lock per organisation shared by every
  replica (`store.lock("linkcheck-start:<tenant or ->")`, the portal's existing lock documents): a second start waits
  for the first and then sees its job.
- A start that still finds the lock taken after `LINK_START_WAIT` (5 seconds) answers `linkcheck.busy`, as when a
  check is under way; a lock older than `LINK_START_HOLD` (30 seconds) belongs to a process that died and is broken.
- Not taken: a unique index on the jobs of a type and organisation in the states *queued* and *running* (a partial
  index with `$in` needs MongoDB 6.0's operators in `partialFilterExpression`, and a job's state changes as it runs).
- **Residual.** A queued check that no worker takes (no worker running) still blocks the organisation's checks until
  its user stops it or it expires (24 hours); its status says it is stalled.

Checks: `test_jobs` (two starts at once of one organisation: one job and `linkcheck.busy`, with the gap between the
test and the creation widened; a start that waits too long for the lock; the lock given back). 3 mutations, all
caught.
