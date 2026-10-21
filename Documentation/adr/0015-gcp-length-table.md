# ADR 0015 — The GS1 Company Prefix's length from GS1's table

| | |
|---|---|
| Status | **Accepted** (17 October 2026). Implemented in one delivery |
| Backlog item | 9.9 — the GS1 Company Prefix's length from GS1's table |
| Decided by | the owner of the branch, away during the session, who asked for the recommended option on every point of section 4 |

## 1. Context

A GS1 key does not say where its GS1 Company Prefix ends: a GTIN `07898357410015` may hold a prefix of 7, 9 or another
number of digits. The portal needed that length in one place so far — the EPC's partition (ADR 0010) — and took it
from the organisation's prefixes or from the person's choice. Item 9.10 (an EPC for every key) needs it for every key,
and an organisation's prefixes are often not the GS1 Company Prefix itself: they are what the operator typed when
creating the organisation, and can be shorter (several prefixes at once) or longer (a part of one).

GS1 publishes the length of every GS1 Company Prefix by its first digits: the **GCP length table**, an XML file
`GCPPrefixFormatList` (root `<GCPPrefixFormatList date="…">`, one `<entry prefix="…" gcpLength="…"/>` per range). The
list of 17 September 2026 holds 212,486 entries: prefixes of 3 to 12 digits, none the start of another, lengths 6 to
12, and 0 for ranges that are not GS1 Company Prefixes (restricted circulation numbers, coupons, ISBN…). Its header says
it is © GS1 AISBL and **password-protected since December 2025**. This fork is public, so the table cannot be in the
repository, nor downloaded by the installation.

## 2. Decision

1. **The server administrator uploads GS1's file** in the portal, on the *Organisations* screen (*GS1 Company Prefix
   length table*), and each later version the same way; nothing is downloaded automatically. The screen shows the
   list's date, its number of prefixes, who uploaded it and when. A list **older** than the one in use is refused
   until the administrator confirms it. Server administrators with a terminal may also load it with
   `docker compose exec -T portal-service python gcp.py load - < GCPPrefixFormatList.xml`.
2. **The file is checked before anything changes**: an XML document without a DOCTYPE (no entities), the root
   `GCPPrefixFormatList` with an ISO 8601 `date`, only `entry` elements, each with a `prefix` of 1 to 12 digits and a
   `gcpLength` of 0 or 6 to 12, no prefix twice, at least one entry. A refusal names the first problem (and the entry);
   the table in use stays.
3. **Stored in the portal's database and swapped in one step**: one document (`gcp_table`, `_id` `current`) holding
   the list compacted (`prefix length` lines, gzip: about 0.5 MB for today's list), its date, counts and checksum.
   Replacing that document is atomic: every portal process sees the old table or the new one, never a mixture. The
   backup includes it with the rest of the portal's database.
4. **Lookup by the longest matching prefix** of the key's company part (`gs1.company_part()`: after a GTIN's indicator
   digit, an SSCC's extension digit, a GRAI's filler zero). **Length 0 means "not a GS1 Company Prefix"** and is shown
   as such. Each portal process loads the table when it first needs it and looks for a newer one at most once a
   minute.
5. **First uses**:
   - **the EPC's partition**: the person's choice first, then the table, then the organisation's (or the user's)
     prefixes, as before; the label studio says where the length came from. A key the table marks 0 has no EPC
     unless the person chooses a length;
   - **the company prefix shown in the editor**, under the key, with the table's date;
   - **a warning when an organisation's prefix disagrees with the table**, on its page and on the organisations' list:
     longer than GS1's company prefix there (a part of one company's prefix), shorter (it spans prefixes of a greater
     length), or in a range that is not a GS1 Company Prefix. The prefix is still accepted: an operator may have reasons
     (a test range, a Member Organisation's block), and the table can be older than the assignment.
6. **Without a table** everything works as before (the organisation's prefixes for the EPC, nothing shown in the
   editor, no warnings).

## 3. Design

- `portal/gcp.py`: `parse(data)` (gzip or plain XML; at most 64 MB once decompressed; `xml.etree` `iterparse`, a
  DOCTYPE refused before parsing) → `Table` (`date`, sorted prefixes, their lengths; `length_for(digits)`),
  `save(table, user, force)` (the older-list rule; `GcpError("gcp.older", date=…, current=…)`), `info()`, `current()`
  (the cached table, reloaded when the stored checksum changes, checked at most every 60 s), `lookup(anchor)` →
  `{prefix, length, date}`, `check_prefix(prefix)` → `{status: ok|longer|shorter|notGcp|unknown, length}`; a command
  line (`load FILE|-` `[--force]`, `info`).
- The browser compresses the file with `CompressionStream("gzip")` and sends it as the request's body
  (`application/gzip`): today's 9.2 MB list becomes about 0.7 MB, within the 1 MB the proxies and the portal accept for a
  request. The portal decompresses and parses it; about a second for today's list.
- `GET /portal/api/gcp` (server administrators): the table in use; `POST /portal/api/gcp[?confirm=1]` (server
  administrators outside support access): the upload; `GET /portal/api/gcp/lookup?key=&value=` (any user): the company
  prefix of a key; `GET /config` says whether a table is loaded (`gcpTable`: `{date, count}` or `null`); the
  organisation's page and `GET /tenants` add `prefixChecks`. Journal: `gcp-upload`.
- `epc_of_record()` takes the length from the table between the person's choice and the prefixes (`prefixFrom`:
  `chosen`, `table`, `prefixes`).

## 4. Options considered

| Point | Chosen (recommended) | Not chosen |
|---|---|---|
| Where the table comes from | uploaded by the server administrator | committed to the repository (GS1's, restricted, the fork is public); downloaded by the installation (password-protected since December 2025) |
| Where it is kept | one document in the portal's database, swapped at once | a file on the server (one more volume, not in the backup, not shared by replicas); one document per entry (212,486 writes, a swap needing two collections) |
| Sending a 9 MB file through 1 MB limits | compressed in the browser | raising the body limits of the host's nginx, the installation's proxy and the portal (the host's site is generated once by the installer and would need editing on every server) |
| An older list | refused unless confirmed | always accepted (an old file picked by mistake would silently replace a newer one); never accepted (no way back after a bad list) |
| An organisation's prefix that disagrees | a warning | refused (would block organisations whose prefixes are deliberately shorter or longer, and test ranges) |
| Length 0 | "not a GS1 Company Prefix", no EPC unless chosen | treated as unknown (would hide that the key is not a GS1 key of a company) |

## 5. Consequences

- New collection `gcp_table` (one document); new module `portal/gcp.py`; no new dependency.
- Each portal process holds the table in memory once used (about 15 MB for today's list).
- The table ages: the screen shows its date, and GS1 publishes new versions; the operator uploads them. Since 21
  October 2026 the monitoring reports a list `PORTAL_MONITOR_GCP_DAYS` (90) days old or more, by e-mail weekly and on
  the screen ([ADR 0008](0008-monitoring-and-alerts.md), section 3.1).
- A list larger than about 1.4 times today's would no longer fit the 1 MB limit once compressed: the command line
  stays available, or the limit is raised.

## 6. Delivery

This record; `portal/gcp.py`, the routes, the panel on *Organisations*, the editor's line, the warnings, the EPC's
partition; tests with a small table of their own in GS1's format (`test_gcp.py`, and Chromium checks in
`test_gcp_e2e.py`), mutation-checked; the parser and the timings checked once against GS1's real list of 17 September
2026 (not kept); texts in the eleven languages; the documentation.
