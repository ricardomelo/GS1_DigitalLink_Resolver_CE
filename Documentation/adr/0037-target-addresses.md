# ADR 0037 — Target addresses: forms refused, hosts listed per organisation

| | |
|---|---|
| Status | **Accepted** (21 November 2026) |
| Backlog item | 10.1, phase 1 of the security assessment ([ADR 0020](0020-security-assessment.md)); threat T-D2, gap G-12 of the [threat model](../threat-model.md); finding F-020 |
| Decided by | the owner of the branch's standing instruction (take the recommended option and carry on): the deceptive and private forms refused for every organisation; an optional list of hosts per organisation (and for the operator's keys), empty by default, applied to every link type when a record is saved. A list made mandatory for safety-critical types, and a check of the records already saved, were not taken |
| Amends | the target rule of the editor (`gs1.normalise_url()`, HTTPS only, no spaces or invisible characters) and the forwarding destinations of [ADR 0018](0018-forwarding.md) |

## 1. Context

A target is where a scan sends a person's browser. The portal accepted any `https:` address without spaces or control
characters, so an editor, an API key or an import could save:

- **user information** before the host: `https://www.brand.example@evil.example.net/` opens `evil.example.net`, while
  a reader of the address, in the editor or in a printed list, sees the brand first;
- **address literals**: `https://10.0.0.5/`, `https://[::1]/`, and the forms a browser still reads as an IPv4 address
  (`https://2130706433/`, `0x7f.1`, `0177.0.0.1`, `127.1`, full-width digits);
- **names that are not public**: `localhost`, a name without a dot, `.local`, `.internal`, `.lan`, `home.arpa`…,
  which send the person scanning to a device on their own network (a router's page, a printer, an intranet);
- **any host at all**, so that one compromised editor's account or API key can point an organisation's products to a
  look-alike site with nothing to stop it but the link check and the history.

The resolver does not fetch the target; the link checker does, and connects only to public addresses (F-011,
`outbound.py`). The risk is the person who scans: phishing through a trusted product code, and requests to their own
network.

## 2. Decision

### 2.1 Forms refused for every organisation

`gs1.target_host_problem()`, called by `gs1.normalise_url()` (the editor, the tenant API, imports, a restored version:
all through `build_document()`) and by `forwarding.check_target()` (forwarding destinations and the resolver of last
resort), refuses with a message code of its own:

| Form | Code |
|---|---|
| anything before an `@` in the authority (user name, password, even empty) | `link.urlUserInfo` |
| an IPv6 address; a host whose last label is a number, in decimal, octal or `0x` hexadecimal (the WHATWG URL Standard's "ends in a number": the browser reads it as IPv4) | `link.urlAddress` |
| a name without a dot, an empty label, a character other than letters, digits, `-` and `_` in ASCII (a `%` would be decoded by the browser), or a top-level name of `gs1.PRIVATE_TOP_NAMES`: `localhost`, `local`, `localdomain`, `internal`, `intranet`, `lan`, `home`, `corp`, `test`, `onion`, `alt`, `arpa` | `link.urlHost` |
| a port that is not a number | `link.urlInvalid` |

The host is read as a browser reads it (UTS #46): compatibility forms folded (NFKC) and the ideographic full stops
(`。`, `．`, `｡`) taken as dots, so `127。0。0。１` is refused like `127.0.0.1`. Names outside ASCII are kept (the
resolver sends them in Punycode). Ports on a public name, a trailing dot and underscores stay accepted. The
documentation names `example` and `invalid` are not refused: no resolver answers them, so they reach nothing, and the
tests and the guides use them. Forwarding destinations keep their own earlier refusal of user information
(`forwarding.urlInvalid`).

### 2.2 Hosts listed per organisation

- An organisation's administrators (their own organisation only; another's answers 404 `tenants.unknown`) and the
  server administrators (any organisation, and the operator's scope for the keys no organisation holds) set a list of
  host names on the organisation's page, tab *Targets* (`PUT /portal/api/targets/hosts` `{tenant, hosts}`), read only
  in support access (403 `targets.readOnly`). Stored as the organisation's `targetHosts` (with `targetHostsUpdated`,
  `targetHostsBy`) or the setting `targets.hosts`; `portal/targets.py`.
- **Empty (the default) accepts any public host**, as before: nothing changes for an installation until someone lists
  hosts.
- Entries are cleaned: lower case, a leading `*.` or dot dropped, Punycode for names outside ASCII, repeats removed,
  sorted; each must pass §2.1 (`targets.hostInvalid`: no scheme, path, port, `@` or address), at most 50
  (`targets.tooMany`).
- With hosts listed, `build_document()` saves a record only when each target's host **is one of them or a name under
  one** (`shop.example.com` under `example.com`; not `evilexample.com`, not `example.com.evil.net`), compared in
  Punycode: `link.urlNotAllowed` with the host and the target's position (an import reports its row). The list that
  applies is the one of the organisation holding the key (`tenants.owner()`), the operator's for the other keys.
- The record's own page (`gs1:defaultLink` to `…?linkType=linkset&view=page`) is not checked when its host is the
  installation's or one of its verified domains (`own_page()`); a page-like address on any other host is checked like
  any target.
- Each change is journalled once as `target-hosts` (`hosts=` the list, or `-`), in the organisation's trail or the
  operator's.
- The list applies when a record is saved: records saved before keep their targets until they are edited.

### 2.3 Alternatives not taken

- *A list mandatory for safety-critical types* (G-12 as written): every installation would stop saving recall and
  leaflet links on the update until someone configured a list; the optional list gives the same protection to the
  organisations that want it, for every type. Still possible as a setting later.
- *Resolving the name at save time and refusing private addresses*: a public name can be pointed at a private address
  after the save (DNS rebinding), and the person's own network decides what such a name reaches; the forms of §2.1
  are the part a check at save time can settle.
- *Checking the records already saved when a list is set*: needs reading every record of the organisation through
  the data entry API; the link check of the records' page shows each target, and a later item can add a report.
- *Refusing the forms in the resolver*: records written by other tools through the official data entry API would
  still redirect; the official service's behaviour is kept (its token is closed to the internet, ADR 0021).

## 3. Consequences

- Finding F-020 fixed for every write through the portal: the deceptive and private forms cannot be saved, and an
  organisation can restrict its targets to its own sites.
- An editor who saves a record whose earlier target uses a refused form, or a host the list does not hold, must
  correct it first: the message names the address and the reason.
- Residuals: records saved before keep their targets (no report of those outside a list or using a refused form); the
  official data entry API, open only to listed addresses, still accepts any target; a public name may resolve to a
  private address; a list is optional and the same for every link type; `PRIVATE_TOP_NAMES` is a constant.
- Tests: `test_targets.py` (every refused form, the accepted ones, the editor, the API, imports, forwarding, the list:
  who may set it, cleaning, refusals, matching, the item's page, the operator's scope, support access, the journal).
