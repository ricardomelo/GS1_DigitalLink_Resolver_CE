# ADR 0047 — The GS1 Digital Link Toolkit's Node.js processes bounded

| | |
|---|---|
| Status | **Accepted** (22 November 2026) |
| Backlog item | 10.1, the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-R3 and gap G-3 of the [threat model](../threat-model.md); finding U-002 (code from the official project) |
| Decided by | the owner's standing instruction for the assessment's findings, the owner away: the recommended option taken. Not taken: decompressing in the resolver's own process (no maintained Python implementation of GS1 Digital Link compression; porting the toolkit's 8,000 lines is a delivery of its own, kept as a residual); a long-running Node.js worker answering over a pipe (a second service to supervise, for a form of the link that few labels carry); settings in `.env` for the limits (no operator has needed to change them; constants in one place) |
| Changes | the official code (`web_server/src/web_logic.py`), deliberately; recorded in the CHANGELOG |

## 1. Context

A path of one segment that is neither a file of the resolver nor an EPC binary string (`/eh…`, `/ex…`, decoded in
the resolver's own process, `epc_binary.py`) may be a compressed GS1 Digital Link (URI Syntax 1.7,
section 6). The official code asks the GS1 Digital Link Toolkit, which runs in Node.js: a new process for every such
request, whatever the segment held, and waited for without a time limit. A Node.js start-up costs about 40 ms of CPU;
every `/wp-login.php` or `/.env` that scanners send paid it, eight threads of each server process could be waiting
on such processes at once, and a process that never ended held its thread for ever. The rate limits of
[ADR 0031](0031-request-limits.md) bound how often one address can ask, not what each request costs. The same
function serves the syntax check's fallback when the GS1 Barcode Syntax Engine's library is missing, and the
`?compress=true` answer.

## 2. Decision

1. **Refused by pattern first.** A compressed GS1 Digital Link is written in the URI-safe base64 alphabet: a segment
   that is not 4 to 1,024 characters of `A–Z a–z 0–9 - _` is answered 400 (*not a GS1 Digital Link*) without
   starting Node.js (`web_logic.COMPRESSED_DL`). The shortest key compresses to 7 characters.
2. **At most two processes at once** in each server process (`TOOLKIT_PROCESSES`; gunicorn runs `WEB_CONCURRENCY`
   of them): a request waits up to one second for a turn (`TOOLKIT_WAIT`), then the resolver answers **503 with
   `Retry-After: 1`** — an HTML page (*please try again in a moment*) for a browser, JSON otherwise — and starts no
   process. 503, not 400: the link may well be valid.
3. **A time limit.** A process still running after 3 seconds (`TOOLKIT_TIMEOUT`; they answer in about 40 ms) is
   killed and the request answered 503 the same way; its slot is given back.
4. **Recent answers kept.** The toolkit's answer for a segment, decompressed or refused, is kept per server process
   (4,096 segments, the oldest making room): the same compressed code scanned again starts no process. A timeout or
   a full house is not kept.
5. The same limits apply to the syntax check's Node.js fallback and to compression (`_run_toolkit()`); a busy
   toolkit makes a resolution 503 there too, and `?compress=true` answers `response_status` 503 in its body.
6. The toolkit's error output is no longer sent to the client in the 400 answer for a segment that does not
   decompress (it goes to the service's log): the answer says *Not a GS1 Digital Link*.

## 3. Consequences

- Scanners' paths cost a regular expression; the resolver's threads can no longer all be taken by Node.js processes,
  and none waits more than about four seconds for one.
- A flood of distinct base64url segments still starts processes, two at a time per server process: compressed links
  may then answer 503 for a moment, while uncompressed links and EPC binary strings, answered in process, are not
  affected. The proxy's limits per address still apply first.
- The request log records a 503 as *error*, as before for answers of 500 and above.

## 4. Residuals

- Decompression in the resolver's own process (no Node.js at all for resolution) is not done: a port of the toolkit's
  decompression, checked against it on the GS1 test suite, would remove the last process started by a request.
- The limits are constants in `web_logic.py`, not settings.

## 5. Delivery

`web_server/src/web_logic.py` (`COMPRESSED_DL`, `TOOLKIT_PROCESSES`, `TOOLKIT_WAIT`, `TOOLKIT_TIMEOUT`,
`ToolkitBusy`, `_run_toolkit()`, `_uncompressed()`; `uncompress_gs1_digital_link()`, `compress_gs1_digital_link()`
and `_call_gs1_toolkit()` through `_run_toolkit()`); `web_server/src/web_namespace.py` (`_unavailable()`, 503 with
`Retry-After` from the three resolution routes). The 503 page uses the existing texts *error.other* (twelve
languages): no new text.
Tests: `test_resolver.py` (segments that cannot be compressed links refused without a process; a real compressed link
decompressed by the real toolkit and resolved, then answered from memory; a segment that does not decompress refused
and remembered, without the toolkit's error text; a process that never ends killed within the limit, 503 with
`Retry-After` in JSON and HTML, asked again next time, every slot given back; every slot taken: 503 without a process;
eight requests at once never more than two processes; without the engine's library, a busy toolkit makes a resolution
503 and a compression `response_status` 503).
