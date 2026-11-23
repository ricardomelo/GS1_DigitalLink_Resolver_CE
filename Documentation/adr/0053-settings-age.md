# ADR 0053 — A limit on the age of the portal's settings in the resolver

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); the threat T-R6 (*a stale answer served after a change*) and the hazard H-15 (*a change does not take effect*) of the [threat model](../threat-model.md); finding F-033 (a residual of [ADR 0051](0051-records-unavailable.md) and [ADR 0052](0052-database-time-budget.md), run) |
| Decided by | the owner's standing instruction for the assessment's residuals, the owner away: the recommended option taken — each cache of the portal's settings notes its last good read; once its reads have failed for longer than `RESOLVER_SETTINGS_MAX_AGE_S` (15 minutes by default), the values whose absence is the safer answer are no longer used (forwarding, brands, appearance) and the others are kept (domains, strict mode, retention); an error line in the log, the state in the heartbeat and an alert by the portal's monitor. Not taken: dropping every cache after the limit (an organisation's domain would answer for every key, and links the strict mode withholds would be given); keeping every value and only alerting (a forwarding rule a server administrator switched off would keep sending scans elsewhere for as long as the process lives); stopping the resolver, or answering 503 to every scan, once a cache is stale (scans whose records can be read would fail too); a new field in the request log for answers given without forwarding (one more column for a rare state that the log line and the alert already report) |
| Amends | [ADR 0018](0018-forwarding.md) (rules and the resolver of last resort stop after the limit), [ADR 0011](0011-item-page.md) and [ADR 0019](0019-appearance.md) (brands and appearance likewise), [ADR 0008](0008-monitoring-and-alerts.md) (a new check, `settings`); the official resolver's heartbeat, deliberately (a field added); recorded in the CHANGELOG |

## 1. Context

The resolver keeps six caches of settings that the portal writes to its own database: the organisations' domains
(`domains.py`, read again after 60 seconds), forwarding by prefix and the resolver of last resort (`forwarding.py`,
30 seconds), the strict mode (`resolution.py`, 60 seconds), the brands of the item's page (`landing.py`), the
installation's appearance (`web_pages.py`, 30 seconds) and the request log's retention (`request_log.py`). When a read
fails each logs a warning and keeps the values it read last, with no limit on their age and nothing else to tell the
operator. Run with a prefix rule and the resolver of last resort read once, then every read failing and the rule
disabled in the database: the rule and the resolver of last resort were still applied after one hour, one day and
thirty days.

During a whole outage of MongoDB this does no harm: the portal cannot change the settings either, so the values kept
are the last ones written, and since ADR 0052 every scan that needs a record is answered *try again* within seconds.
The harm is when the resolver cannot read the portal's database while the portal can: its MongoDB user loses its read
on the portal's database, a document its code cannot parse, a network path broken for the resolver only. Then a
forwarding rule or the resolver of last resort that a server administrator switched off keeps sending scans to another
resolver, and an organisation's brand removed in the portal keeps its verified site on the item's page, indefinitely.

## 2. Decision

1. **The age of each cache.** Each cache notes when it last read the portal's database (`settings_age.Age`); the start
   of the process counts as a read. Its values are *stale* while its reads have failed since then and for longer than
   the limit. A cache that is not used is not read, and is not stale: only failed reads count, and the first failed
   read after a long quiet time makes it stale at once, since its values are that old.
2. **The setting.** `RESOLVER_SETTINGS_MAX_AGE_S`, in seconds, from 60 to 86,400; 900 (15 minutes) when unset. Any
   other value is not used: the resolver warns at start and uses 900. The resolver's log says the limit at start.
   `.env.example` documents it, commented out.
3. **What a stale cache does.** Each cache takes the answer that is safer without it:

   | Cache | Once stale | Why |
   |---|---|---|
   | Forwarding: prefix rules | not applied: the key is answered from this resolver's records (or *try again* while they cannot be read, ADR 0051) | a rule sends a person's scan to a third party; after the limit the resolver cannot know the operator still wants it |
   | Forwarding: the resolver of last resort | not used: a key nobody registered is a 404 | the same |
   | Brands of the item's page | none: the page without an organisation's brand and its verified site | a brand states that a site is the organisation's |
   | Appearance | the original appearance | the operator's look only; the safer default is the project's |
   | Domains | kept | without them an organisation's domain would answer for every organisation's keys |
   | Strict mode | kept | without it a link the strict mode withholds would be given |
   | Request log retention | kept | it decides only when events expire |

4. **The alert.** The resolver's log has one error line when a cache becomes stale (the cache, its age, the limit and
   what the resolver does meanwhile) and one information line when it reads the database again; the warning of each
   failed read is unchanged. `GET /heartbeat` answers `"settings": "stale"` while one of the six caches is stale, else
   `"current"`; it reads each cache whose period has passed first, so a quiet resolver is checked too. The portal's
   monitor reads the heartbeat through the proxy every round (`monitor.check_settings()`, the check `settings`) and
   raises an alert at once while it says `stale` (the resolver has already waited the limit), with a reminder every 24
   hours and a message when it says `current` again (messages `alert-settings-stale` and `alert-settings-current`, in
   twelve languages, to the server administrators who want alerts). A heartbeat that does not answer, or says nothing
   about the settings (a resolver older than this decision), is *unknown*: the check `resolver` covers a resolver that
   does not answer.

## 3. Consequences

- A rule, the resolver of last resort or a brand switched off in the portal stops being applied within the limit even
  when the resolver cannot read the change; the operator is told by e-mail within one more round of the monitor.
- During a whole outage longer than the limit, prefixes that a rule forwarded are answered *try again* instead of
  being forwarded, and keys nobody registered 404 instead of going to the resolver of last resort: the resolver no
  longer vouches for settings it cannot read. An operator who prefers the old behaviour for longer outages can raise
  the limit to a day.
- The portal shows the check among the operation's checks of the overview and in the alert history (*Resolver's
  settings*); the heartbeat's answer has one field more, which a client that reads only `response_message` ignores.

## 4. Residuals

- Each resolver process (two per container by default, and each replica) keeps its own caches; the heartbeat answers
  for the process that receives it, so the monitor samples one process per round and an alert can come and go while
  only some processes are stale.
- During a whole outage of MongoDB the portal's monitor cannot record its checks either (ADR 0008), so this alert
  covers the partial failures described above, not a whole outage.
- The heartbeat is public, like the rest of the resolver: anyone can learn that its settings are stale, nothing more
  (no cache, age or error is named there; the log has them).
- A domain map never read since the process started is empty: a domain then answers as the installation's own name,
  for every key, as before this decision (the records cannot be read either while the database is down at start).

## 5. Delivery

`web_server/src/settings_age.py` (new: `SETTING`, `DEFAULT_S`, `MIN_S`, `MAX_S`, `setting_s()`, `invalid()`,
`limit()`, `Age`, `state()`); the six caches (`domains.DomainMap`, `forwarding.Forwarding`, `resolution.StrictMode`,
`landing.BrandMap`, `web_pages.Appearance`, `request_log.Retention`: an `age` and a public `refresh()`);
`web_server/src/web_namespace.py` (`SETTINGS_CACHES`, the heartbeat's `settings`); `web_server/src/__init__.py` (the
warning and the log line at start); `portal/monitor.py` (`heartbeat_url()`, `check_settings()`, the check `settings`);
`portal/mailtexts.py`, `portal/mail_languages.json` and `portal/notify.py` (the two messages); `portal/static/app.js`,
`i18n.js` and `locales/` (the check's name in the overview and the alert history); `.env.example`. Tests:
`test_settings_age.py` (new: the setting; forwarding through Flask's test client within and past the limit, the log
lines, the database back; the age counted from the last good read; brands and appearance dropped; domains, strict mode
and retention kept; the heartbeat) and `test_monitor.py` (the check through a stand-in proxy: ok, alert, reminder,
unknown, resolved, the messages).
