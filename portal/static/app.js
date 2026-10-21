"use strict";

/*
 * The portal page: one script, no build step and no framework. The server (portal/app.py) is the
 * authority on every rule; the checks here only give instant feedback. Texts come from I18N
 * (i18n.js) by message code, so the same code serves pt-BR and en-GB.
 *
 * Sections, in order:
 *   API ............................ api(): JSON calls to /portal/api/*, errors as ApiError(code, params)
 *   session clock .................. SessionClock: idle and absolute limits, warning, renewal on use
 *   GS1 rules, primary keys ........ readKey(): live validation of the identifier (URI Syntax 4.3)
 *   key qualifiers ................. fields per key, readQualifiers(): formats, shapes, order (4.4, 4.6, 4.9)
 *   label preview .................. renderPreview(): Digital Link, QR code image, options, downloads
 *   data attributes ................ attribute rows, combo box, decimal families, engine check (4.10)
 *   step 1 ......................... key type menu, openRecord()
 *   other records of the same key .. list under Open record: search, filter, unsaved-changes guard
 *   record list (#records) ......... views (applyView), then loading, filters, code search, rendering
 *   roles, history, users, audit ... read-only mode, versions of a record, administration screens
 *   link checker ................... editor, every record, import preview
 *   spreadsheets ................... export and two-step import with preview
 *   step 3 ......................... target rows (type, language, address, title, default)
 *   save / delete, user menu, options (password), language menu, start-up (init: every event handler)
 */

/* Base path of the portal (e.g. "/portal/"), so it works behind any prefix. */
const BASE = location.pathname.replace(/[^/]*$/, "");
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const { t } = I18N;

let CONFIG = null;
const state = {
  openKey: null,               // query string of the record currently open for editing
  exists: false,
  sharedDefaultLinkType: null, // set when other records on the same GTIN fix the default link type
  hasKeyRecord: true,          // whether the key has a record of its own (section 2.5.9)
  keyPromptDone: false,        // the user chose to save without it in this editing session
  pendingUnsaved: false,       // unsaved changes of a record whose identity was then changed
};

/* ------------------------------------------------------------------ API */
class ApiError extends Error {
  constructor(code, params = {}) {
    super(code);
    this.code = code;
    this.params = params;
  }
}

async function api(method, path, body) {
  const opts = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(BASE + "api/" + path, opts);
  } catch {
    throw new ApiError("error.network");
  }
  let data = null;
  try { data = await res.json(); } catch { /* response without JSON */ }
  if (res.status !== 401) SessionClock.contact();   // every answered call renews the session on the server
  if (res.status === 401 && data && data.code === "auth.required") {
    location.replace("login?reason=expired");   // session ended (timeout, sign-out elsewhere, password changed)
    throw new ApiError("auth.required");
  }
  if (!res.ok) {
    if (data && data.code) throw new ApiError(data.code, data.params || {});
    throw new ApiError("error.unexpected", { status: res.status });
  }
  return data;
}

/* ------------------------------------------------------------------ session clock
   The server ends a session after a period without calls (idle limit) and, whatever the use, some hours
   after the sign-in (absolute limit). This clock mirrors both so the page can warn before either end:
   - every answered call renews the idle limit (SessionClock.contact, called by api());
   - typing, clicking or scrolling without calling the server counts as use too: a quiet call renews the
     session once the last one is a few minutes old;
   - other tabs of the portal share the time of the last call through localStorage;
   - near the end a dialog offers to stay signed in (idle) or explains that a new sign-in is needed
     (absolute); at the end the page goes to the sign-in page. */
const SessionClock = (() => {
  const STORE = "gs1resolver.portal.lastContact";
  const state = { idleMs: 0, warnMs: 0, endAt: 0, maxHours: 0, lastContact: Date.now(), lastActivity: 0,
                  renewing: false, timer: null, shown: null, dismissedLimit: false };

  function share() {
    try { localStorage.setItem(STORE, String(state.lastContact)); } catch { /* storage blocked: this tab only */ }
  }
  function contact() {
    state.lastContact = Date.now();
    share();
    if (state.shown === "idle") hide();
  }
  function configure(info) {
    if (!info) return;
    state.idleMs = info.idleSeconds * 1000;
    state.warnMs = info.warningSeconds * 1000;
    state.endAt = Date.now() + info.endsIn * 1000;
    state.maxHours = info.maxHours;
  }
  function start(info) {
    configure(info);
    contact();
    const activity = () => { state.lastActivity = Date.now(); };
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach(type =>
      document.addEventListener(type, activity, { capture: true, passive: true }));
    window.addEventListener("storage", e => {
      if (e.key === STORE && Number(e.newValue) > state.lastContact) {
        state.lastContact = Number(e.newValue);
        if (state.shown === "idle") hide();
      }
    });
    $("#session-continue").addEventListener("click", renew);
    $("#session-signout").addEventListener("click", signOut);
    $("#session-close").addEventListener("click", () => { state.dismissedLimit = true; hide(); });
    $("#session-dialog").addEventListener("cancel", e => {   // Esc: stay signed in, or close the limit notice
      e.preventDefault();
      if (state.shown === "idle") renew(); else { state.dismissedLimit = true; hide(); }
    });
    state.timer = setInterval(tick, 1000);
  }
  async function renew() {
    if (state.renewing) return;
    state.renewing = true;
    try { configure(await api("GET", "session")); } catch { /* 401 already leads to the sign-in page */ }
    finally { state.renewing = false; }
  }
  function clock(ms) {
    const s = Math.max(0, Math.ceil(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  function show(kind, left) {
    const dialog = $("#session-dialog");
    if (kind === "idle") I18N.set($("#session-text"), "session.idle", { time: clock(left) });
    else I18N.set($("#session-text"), "session.limit", { time: clock(left), hours: state.maxHours });
    if (state.shown !== kind) {
      $("#session-continue").hidden = kind !== "idle";
      $("#session-close").hidden = kind === "idle";
      state.shown = kind;
      if (!dialog.open) dialog.showModal();
      (kind === "idle" ? $("#session-continue") : $("#session-close")).focus();
    }
  }
  function hide() {
    state.shown = null;
    const dialog = $("#session-dialog");
    if (dialog.open) dialog.close();
  }
  function tick() {
    if (!state.idleMs) return;
    const now = Date.now();
    const idleLeft = state.lastContact + state.idleMs - now;
    const limitLeft = state.endAt - now;
    if (Math.min(idleLeft, limitLeft) <= 0) {
      clearInterval(state.timer);
      location.replace("login?reason=expired");
      return;
    }
    // Work in the page without server calls: renew quietly before the warning would appear.
    if (!state.shown && state.lastActivity > state.lastContact
        && now - state.lastContact > Math.min(5 * 60 * 1000, state.idleMs / 3)) {
      renew();
      return;
    }
    if (limitLeft <= state.warnMs && limitLeft <= idleLeft) {
      if (!state.dismissedLimit || state.shown === "limit") show("limit", limitLeft);
    } else if (idleLeft <= state.warnMs) {
      show("idle", idleLeft);
    } else if (state.shown === "idle") {
      hide();
    }
  }
  return { start, contact };
})();

/* ------------------------------------------------------------------ GS1 rules (mirror of the back end, for instant feedback only) */
function checkDigit(body) {
  let sum = 0;
  [...body].reverse().forEach((d, i) => { sum += Number(d) * (i % 2 === 0 ? 3 : 1); });
  return (10 - (sum % 10)) % 10;
}

/* ------------------------------------------------------------------ primary identification keys
   GS1 Digital Link URI Syntax 1.7, section 4.3. The same rules as portal/gs1.py (which the server applies
   again), for live feedback while typing: the server describes each key's check, each qualifier's pattern and
   the qualifier order in CONFIG.rules, built from the GS1 Barcode Syntax Dictionary (ADR 0003), so nothing
   here repeats a length or a format. */
const CSET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz";
const CSET32 = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97];
const NUMERIC_KINDS = ["gtin", "numeric", "itip", "digitsSerial"];      // keys of digits only (gs1.NUMERIC_KINDS)
const rules = () => CONFIG?.rules || { keys: {}, qualifiers: {}, order: [], keyChars: "A-Za-z0-9.\\-", cset39Chars: "0-9A-Z\\-" };
const keyRule = ai => rules().keys[ai] || { kind: "none" };
const alnumPattern = () => new RegExp(`^[${rules().keyChars}]+$`);

function gmnPair(body) {
  let sum = 0;
  [...body].forEach((c, i) => { sum += CSET82.indexOf(c) * PRIMES[body.length - 1 - i]; });
  sum %= 1021;
  return CSET32[sum >> 5] + CSET32[sum & 31];
}

const fail = (key, params) => ({ ok: false, error: true, key, params });

function checkNumeric(value, length) {
  if (!/^\d+$/.test(value)) return fail("key.digitsOnly");
  if (value.length !== length) return { ok: false, key: "key.length", params: { expected: length, length: value.length } };
  const expected = checkDigit(value.slice(0, -1));
  return Number(value.at(-1)) === expected ? null : fail("key.checkDigit", { expected });
}

function checkAlnum(value, max, pattern = alnumPattern(), code = "key.chars") {
  if (value.length > max) return fail("key.tooLong", { max });
  if (!pattern.test(value)) return fail(code);
  if (value.length < 4 || !/^\d{4}/.test(value)) return fail("key.companyPrefix");
  return null;
}

function checkWithSerial(value, baseLength, serialMax, filler = "") {
  let body = value;
  if (filler) {
    if (!value.startsWith(filler)) return fail("key.graiZero");
    body = value.slice(filler.length);
  }
  const base = body.slice(0, baseLength), serial = body.slice(baseLength);
  if (base.length < baseLength || !/^\d+$/.test(base)) {
    return { ok: false, key: "key.baseDigits", params: { length: baseLength } };
  }
  const expected = checkDigit(base.slice(0, -1));
  if (Number(base.at(-1)) !== expected) return fail("key.checkDigit", { expected });
  if (serial.length > serialMax) return fail("key.serialTooLong", { max: serialMax });
  if (serial && !alnumPattern().test(serial)) return fail("key.chars");
  return null;
}

function currentKey() {
  return $("#key-type").value || "01";
}

/* The identifier typed in step 1: { ok, ai, value } or the reason it is not valid yet. */
/* Invisible characters that come with copied text (zero-width space, word joiner, byte order mark, soft
   hyphen, direction marks); removed from identifiers, as the server does (gs1.without_invisible). */
const INVISIBLE = /[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]/g;

function readKey() {
  const ai = currentKey();
  const raw = $("#key-value").value.replace(INVISIBLE, "").replace(/\s/g, "");
  if (ai === "01") {
    const digits = raw.replace(/[.\-]/g, "");
    if (!digits) return { ok: false, ai, key: "gtin.hint" };
    if (!/^\d+$/.test(digits)) return { ok: false, ai, error: true, key: "gtin.digitsOnly" };
    if (![8, 12, 13, 14].includes(digits.length)) {
      return { ok: false, ai, key: "gtin.typedLength", params: { length: digits.length } };
    }
    const expected = checkDigit(digits.slice(0, -1));
    if (Number(digits.at(-1)) !== expected) {
      return { ok: false, ai, error: true, key: "gtin.checkDigit", params: { expected } };
    }
    if (digits.length === 13 && digits[0] === "2") return { ok: false, ai, error: true, key: "gtin.restricted" };
    return { ok: true, ai, value: digits.padStart(14, "0"), key: "gtin.valid" };
  }
  if (!raw) return { ok: false, ai, key: `key.${ai}.hint` };
  const rule = keyRule(ai);
  const value = NUMERIC_KINDS.includes(rule.kind) ? raw.replace(/[.\-]/g, "") : raw;
  let problem = null;
  if (rule.kind === "numeric") problem = checkNumeric(value, rule.length);
  else if (rule.kind === "itip") {
    const length = rule.base + rule.extra, half = rule.extra / 2;
    if (!/^\d+$/.test(value)) problem = fail("key.digitsOnly");
    else if (value.length !== length) problem = { ok: false, key: "key.length", params: { expected: length, length: value.length } };
    else {
      const expected = checkDigit(value.slice(0, rule.base - 1));
      if (Number(value[rule.base - 1]) !== expected) problem = fail("key.checkDigit", { expected });
      else {
        const piece = Number(value.slice(rule.base, rule.base + half)), total = Number(value.slice(rule.base + half));
        if (!piece || !total || piece > total) problem = fail("key.itipPiece");
      }
    }
  } else if (rule.kind === "gmn") {
    problem = checkAlnum(value, rule.max);
    if (!problem && (value.length < 3 || value.slice(-2) !== gmnPair(value.slice(0, -2)))) {
      problem = fail("key.gmnPair", { expected: value.length < 3 ? "" : gmnPair(value.slice(0, -2)) });
    }
  } else if (rule.kind === "cpid") problem = checkAlnum(value, rule.max, new RegExp(`^[${rules().cset39Chars}]+$`), "key.cpidChars");
  else if (rule.kind === "alnum") problem = checkAlnum(value, rule.max);
  else if (rule.kind === "digitsSerial") {
    if (!/^\d+$/.test(value)) problem = fail("key.digitsOnly");
    else if (value.length < rule.min || value.length > rule.max) {
      problem = { ok: false, key: "key.lengthRange", params: { min: rule.min, max: rule.max, length: value.length } };
    } else {
      const expected = checkDigit(value.slice(0, rule.base - 1));
      if (Number(value[rule.base - 1]) !== expected) problem = fail("key.checkDigit", { expected });
    }
  } else if (rule.kind === "withSerial") problem = checkWithSerial(value, rule.base, rule.serialMax, rule.filler);
  if (problem) return { ...problem, ai };
  return { ok: true, ai, value, key: "key.valid" };
}

/* ------------------------------------------------------------------ key qualifiers
   URI Syntax 1.7, sections 4.4 (which AIs), 4.6 (formats) and 4.9 (order). The shapes (the qualifiers
   allowed together, and which are required), the order and each qualifier's pattern and maximum length come
   from the server configuration (gs1.KEY_SHAPES, gs1.browser_rules()). */
const qualOrder = () => rules().order;
const qualFormats = {};
function qualFormat(q) {
  const rule = rules().qualifiers[q];
  if (!rule) return [/^$/, 0];
  qualFormats[q] ||= [new RegExp(rule.pattern), rule.max];
  return qualFormats[q];
}

function keyConfig(ai) {
  return (CONFIG?.keys || []).find(k => k.code === ai) || { qualifiers: [], shapes: [[]] };
}

/* Required in every shape of the key (e.g. 8020 for AI 415): shown as required. A qualifier required
   only in an alternative shape (235 for UPUI, 7040 for FID/EOID/MID) is optional for the key. */
function alwaysRequired(ai, q) {
  return keyConfig(ai).shapes.every(shape => shape.some(x => x.ai === q && x.required));
}

function buildQualifierFields() {
  const ai = currentKey();
  const box = $("#qualifiers");
  const qualifiers = keyConfig(ai).qualifiers;
  box.replaceChildren(...qualifiers.map(q => {
    const field = document.createElement("div");
    field.className = "qual-field";
    field.dataset.ai = q;
    const label = document.createElement("label");
    label.htmlFor = "q-" + q;
    const name = document.createElement("span");
    I18N.set(name, `qual.${q}.label`);
    const note = document.createElement("span");
    note.className = "optional";
    I18N.set(note, alwaysRequired(ai, q) ? "qual.required" : "qual.optional");
    const tag = document.createElement("span");
    tag.className = "tag-info";
    I18N.set(tag, "informative.tag");
    label.append(name, " ", note, tag);
    const input = document.createElement("input");
    input.id = "q-" + q;
    input.className = "code";
    input.autocomplete = "off";
    input.maxLength = qualFormat(q)[1];
    input.inputMode = ["8011", "8019"].includes(q) ? "numeric" : "text";
    input.addEventListener("input", onIdentityChange);
    input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); openRecord(); } });
    const help = document.createElement("p");
    help.className = "qual-help";
    I18N.set(help, `qual.${q}.hint`);
    field.append(label, input, help);
    return field;
  }));
  $("#qualifiers-fieldset").hidden = qualifiers.length === 0;
}

/* The qualifiers typed in step 1: { ok, pairs: [[AI, value], …] in path order } or the problem. */
function readQualifiers() {
  const ai = currentKey();
  const given = {};
  for (const field of document.querySelectorAll("#qualifiers .qual-field")) {
    const q = field.dataset.ai;
    const value = $("input", field).value.replace(INVISIBLE, "").trim();
    if (!value) continue;
    if (!qualFormat(q)[0].test(value)) return { ok: false, error: true, key: "qualifier.invalid", params: { ai: q } };
    given[q] = value;
  }
  const names = Object.keys(given);
  for (const shape of keyConfig(ai).shapes) {
    const allowed = shape.map(x => x.ai);
    const required = shape.filter(x => x.required).map(x => x.ai);
    if (names.every(q => allowed.includes(q)) && required.every(q => q in given)) {
      return { ok: true, pairs: allowed.filter(q => q in given).map(q => [q, given[q]]) };
    }
  }
  const missing = keyConfig(ai).shapes.flatMap(shape => names.every(q => shape.some(x => x.ai === q))
    ? shape.filter(x => x.required && !(x.ai in given)).map(x => x.ai) : []);
  if (missing.length) return { ok: false, key: "qualifier.required", params: { ai: missing[0] } };
  const order = q => qualOrder().indexOf(q);
  return { ok: false, error: true, key: "qualifier.combination",
           params: { given: names.sort((a, b) => order(a) - order(b)).map(q => `(${q})`).join(" + ") } };
}

function qualifierPath(pairs) {
  return pairs.map(([q, v]) => `/${q}/${encodeURIComponent(v)}`).join("");
}

/* "Batch L1 · Serial S1" */
function qualText(pairs) {
  return (pairs || []).map(([q, v]) => t(`qual.${q}.item`, { value: v })).join(" · ");
}

/* GS1-Conformant Resolver 1.2.1, section 2.5.9, rule 2: with a serial number, the variant and batch of a GTIN
   or ITIP are not part of the record. The portal keeps them with the serial-number record as information
   (stored, searchable, printed in the QR code). { pairs: the record's qualifiers, informative }. */
function splitInformative(ai, pairs) {
  const rule = keyConfig(ai).informative;
  if (!rule || !(pairs || []).some(([q]) => q === rule.serial)) return { pairs: pairs || [], informative: [] };
  return { pairs: pairs.filter(([q]) => !rule.ais.includes(q)), informative: pairs.filter(([q]) => rule.ais.includes(q)) };
}

/* " · Batch B42 (informative)" after the record's own qualifiers, or "" */
function informativeText(pairs) {
  return pairs?.length ? " · " + t("informative.suffix", { list: qualText(pairs) }) : "";
}

/* What identifies the record being edited: key and the record's own qualifiers (not the informative ones). */
function recordKey(g, l) {
  return query(g, { pairs: splitInformative(g.ai, l.pairs).pairs });
}

function query(g, qual) {
  const params = new URLSearchParams({ key: g.ai, value: g.value });
  if (qual.pairs?.length) params.set("qualifiers", qual.pairs.map(([q, v]) => `/${q}/${v}`).join(""));
  return params.toString();
}

/* ------------------------------------------------------------------ label preview */
let qrTimer = null;
let previewSeq = 0;

/* RFID and NFC (the backlog's EPC/NFC label option; ADR 0010, section 8): for every key the EPC Tag Data Standard
   encodes, once the record holds what its scheme needs (CONFIG.epc: a qualifier such as a GTIN's serial number, or a
   serial component after the key's fixed digits), the EPC for the tag and the compressed GS1 Digital Link an NFC tag
   emits (eh…, ex…), computed by the server (portal/epc.py). */
let epcSeq = 0, epcFilterKind = null;
const EPC_TRADE_ITEMS = ["01", "8006"];           // the filter values named for trade items (TDS Table 10-2)

/* The filter's values: named for a trade item; for the other keys 0 ("all others", the default) and the numbers the
   Tag Data Standard keeps for each scheme. */
function fillEpcOptions(ai) {
  const kind = EPC_TRADE_ITEMS.includes(ai ?? "01") ? "trade" : "other";
  const prefix = $("#epc-prefix"), filter = $("#epc-filter");
  const keepPrefix = prefix.value;
  const keepFilter = kind === epcFilterKind && filter.value ? filter.value : kind === "trade" ? "1" : "0";
  prefix.replaceChildren(i18nOption("epc.prefixAuto", ""), ...[6, 7, 8, 9, 10, 11, 12].map(n =>
    new Option(t("epc.prefixDigits", { n }), String(n))));
  filter.replaceChildren(...[0, 1, 2, 3, 4, 5, 6, 7].map(n => new Option(
    kind === "trade" || n === 0 ? `${n} — ${t("epc.filter." + n)}` : String(n), String(n))));
  prefix.value = keepPrefix;
  filter.value = keepFilter;
  epcFilterKind = kind;
}

async function refreshEpc() {
  const g = readKey(), l = readQualifiers();
  const need = g.ok && l.ok ? CONFIG?.epc?.[g.ai] : undefined;
  const ready = need !== undefined && (!need.qualifier || (l.pairs || []).some(([q]) => q === need.qualifier))
    && (!need.serialAfter || g.value.length > need.serialAfter);
  $("#epc").hidden = !ready;
  if (ready && (EPC_TRADE_ITEMS.includes(g.ai) ? "trade" : "other") !== epcFilterKind) fillEpcOptions(g.ai);
  if (!ready || !$("#epc").open) return;
  const seq = ++epcSeq;
  const params = new URLSearchParams(query(g, l));
  params.set("filter", $("#epc-filter").value || "1");
  if ($("#epc-prefix").value) params.set("prefixLength", $("#epc-prefix").value);
  if ($("#opt-domain").value) params.set("domain", $("#opt-domain").value);
  try {
    const e = await api("GET", "epc?" + params.toString());
    if (seq !== epcSeq) return;
    const rows = [["epc.scheme", e.scheme.toUpperCase()], ["epc.hex", e.hex, true], ["epc.tagUri", e.tagUri],
                  ["epc.nfc", e.compressedHex, true], ["epc.nfcBase64", e.compressedBase64, true]];
    $("#epc-out").replaceChildren(...rows.flatMap(([key, value, copy]) => {
      const dd = el("dd", "", value);
      if (copy) {
        const b = el("button", "link-button", t("epc.copy"));
        b.type = "button";
        b.addEventListener("click", () => navigator.clipboard?.writeText(value));
        dd.append(b);
      }
      return [el("dt", "", t(key)), dd];
    }));
    I18N.set($("#epc-msg"), e.prefixFrom === "prefixes" ? "epc.prefixFound" : e.prefixFrom === "table" ? "epc.prefixTable"
      : null, { n: e.prefixLength, date: formatDay(e.tableDate) });
  } catch (err) {
    if (seq !== epcSeq) return;
    $("#epc-out").replaceChildren();
    I18N.set($("#epc-msg"), err.code, { ...err.params, date: formatDay(err.params?.date) });
  }
}

function renderPreview() {
  refreshEpc();
  const g = readKey();
  // EAN/UPC beside the QR code: for GTINs of consumer units only (indicator 0), as the server decides
  $("#opt-linear-field").hidden = !(g.ai === "01" && (!g.ok || g.value.startsWith("0")));
  fillSizeOptions();                             // the key's scanning environments (ADR 0010, section 7.6)
  const l = readQualifiers();
  const host = domainBase(g);
  const shown = g.ok ? g.value : "______________";
  const pairs = l.ok ? l.pairs : [];
  const ready = g.ok && l.ok;
  const attributes = readAttributes();
  const seq = ++previewSeq;

  drawDigitalLink(host, g, shown, pairs, "");
  if (!ready || !attributes.length) {
    I18N.set($("#attr-msg"), null);
    applyPreview(ready, g, l, ready ? `${host}/${g.ai}/${g.value}` + qualifierPath(pairs) : "", []);
    return;
  }
  // Data attributes are checked by the GS1 Barcode Syntax Engine on the server; until they are valid
  // nothing can be downloaded, so a code is never produced without the attributes the user asked for.
  applyPreview(false, g, l, "", attributes, "attrs.checking");
  clearTimeout(attrTimer);
  attrTimer = setTimeout(async () => {
    const body = { key: g.ai, value: g.value, qualifiers: Object.fromEntries(pairs),
                   attributes: attributes.map(([ai, value]) => ({ ai, value })), domain: $("#opt-domain").value };
    try {
      const result = await api("POST", "digital-link", body);
      if (seq !== previewSeq) return;
      drawDigitalLink(host, g, shown, pairs, result.uri.includes("?") ? result.uri.slice(result.uri.indexOf("?")) : "");
      showResolvedAttributes(attributes, result.hri.slice(result.hri.length - attributes.length));
      I18N.set($("#attr-msg"), "attrs.ok", { count: attributes.length });
      $("#attr-msg").className = "field-msg is-ok";
      applyPreview(true, g, l, result.uri, attributes);
    } catch (e) {
      if (seq !== previewSeq) return;
      const params = { ...e.params };
      if (Array.isArray(params.list)) params.list = attributeList(params.list);
      I18N.set($("#attr-msg"), e.code, params);
      $("#attr-msg").className = "field-msg is-error";
      applyPreview(false, g, l, "", attributes, "attrs.fixFirst");
    }
  }, 300);
}

/* Under each attribute converted by the server (decimal families, comma or point), how it went into the
   URI: "310n" with 123,45 → "In the URI: 3102=012345". */
function showResolvedAttributes(typed, lines) {
  const rows = $$("#attr-rows .attr-row").filter(row => row.aiCode() || $(".attr-value", row).value.trim());
  rows.forEach((row, index) => {
    const box = $(".attr-resolved", row);
    const match = /^\((\d+)\)(.*)$/.exec(lines[index] || "");
    const [ai, value] = typed[index] || [];
    const changed = match && (match[1] !== ai || match[2] !== value);
    box.hidden = !changed;
    if (!changed) { I18N.set(box, null); return; }
    // For a decimal family the fourth digit of the AI in the URI is the number of decimal places used
    const family = attributeByCode(match[1].slice(0, 3) + "n");
    const decimals = family && family.family && match[1].length === 4 ? Number(match[1][3]) : null;
    I18N.set(box, decimals === null ? "attrs.inUri" : decimals === 0 ? "attrs.inUri.noDecimals" : "attrs.inUri.decimals",
             { pair: `${match[1]}=${match[2]}`, n: decimals });
  });
}

/* The GS1 Digital Link in coloured segments: resolver, key, qualifiers, data attributes. */
function drawDigitalLink(host, g, shown, pairs, queryString) {
  const dl = $("#dl");
  dl.replaceChildren();
  const segment = (cls, text) => {
    const span = document.createElement("span");
    span.className = cls;
    span.textContent = text;
    dl.append(span);
  };
  segment("seg-host", host);
  segment("seg-key", `/${g.ai}/${shown}`);
  I18N.set($("#legend-key"), "legend.key", { ai: g.ai, name: t(`key.${g.ai}.short`) });
  const informative = splitInformative(g.ai, pairs).informative.map(([q]) => q);
  pairs.forEach(([q, v]) => segment(informative.includes(q) ? "seg-info" : "seg-qual", `/${q}/${encodeURIComponent(v)}`));
  $("#legend-lot").hidden = pairs.length === informative.length;
  $("#legend-info").hidden = informative.length === 0;
  // "?17=261231&3103=000500": one segment per attribute so long query strings wrap between them
  queryString.slice(1).split("&").filter(Boolean)
    .forEach((pair, i) => segment("seg-attr", (i ? "&" : "?") + pair));
  $("#legend-attr").hidden = !queryString;
}

/* Test, copy, downloads and the QR image, for a ready URI (or disabled, with a placeholder message).
   The image is fetched rather than set as <img src>: the response says which QR version and error
   correction level were used, and when the content does not fit a forced version the server explains
   why (qr.tooSmall, qr.tooLong), which is shown in place of the image. Downloads are enabled only once
   the image was drawn, so they never lead to an error. */
let qrObjectUrl = null;

function applyPreview(ready, g, l, uri, attributes, placeholder = "preview.qrPlaceholder") {
  const dl = $("#dl");
  toggleLink($("#test"), ready ? uri : null);
  const attrQuery = attributes.map(([ai, value]) => "&attr=" + encodeURIComponent(`${ai}:${value}`)).join("");
  const labelQuery = ready ? `${query(g, l)}&${labelOptionsQuery()}${attrQuery}` : "";
  setDownloads(null);
  if (ready) dl.href = uri; else dl.removeAttribute("href");
  $("#copy").disabled = !ready;
  $("#copy").dataset.uri = uri;

  clearTimeout(qrTimer);
  const seq = previewSeq;
  qrTimer = setTimeout(async () => {
    const box = $("#qr");
    if (!ready) {
      showQrMessage(placeholder);
      return;
    }
    try {
      const response = await fetch(`${BASE}api/qrcode?${labelQuery}`, { credentials: "same-origin" });
      if (seq !== previewSeq) return;
      if (!response.ok) {
        const body = await response.json().catch(() => ({ code: "error.unexpected" }));
        showQrError(body.code, body.params || {});
        return;
      }
      const blob = await response.blob();
      if (seq !== previewSeq) return;
      const img = new Image();
      img.alt = t("preview.qrAlt", { uri });
      img.onload = () => {
        box.replaceChildren(img);
        box.classList.remove("has-error");
        if (qrObjectUrl) URL.revokeObjectURL(qrObjectUrl);
        qrObjectUrl = img.src;
      };
      img.src = URL.createObjectURL(blob);
      const kind = response.headers.get("X-Symbol") || "qr";
      if (kind === "qr") {
        I18N.set($("#qr-info"), "preview.qrInfo", {
          version: Number(response.headers.get("X-QR-Version")),
          modules: Number(response.headers.get("X-QR-Modules")),
          level: response.headers.get("X-QR-Level") || "",
        });
      } else {
        const [rows, columns] = (response.headers.get("X-DM-Modules") || "x").split("x");
        I18N.set($("#qr-info"), "preview.dmInfo", { name: t("label.symbol." + kind), rows, columns,
                                                    x: response.headers.get("X-Dimension") || "" });
      }
      setDownloads(labelQuery);
    } catch {
      if (seq === previewSeq) showQrError("error.network", {});
    }
  }, 250);
}

function setDownloads(labelQuery) {
  toggleLink($("#download-png"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=png` : null);
  toggleLink($("#download-svg"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=svg` : null);
  toggleLink($("#download-pdf"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=pdf` : null);
  toggleLink($("#download-zip"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=zip` : null);
}

function showQrMessage(key) {
  const span = document.createElement("span");
  I18N.set(span, key);
  $("#qr").replaceChildren(span);
  $("#qr").classList.remove("has-error");
  I18N.set($("#qr-info"), null);
}

/* In place of the image: what went wrong and what to do (a forced QR version too small, content too long). */
function showQrError(code, params) {
  const panel = document.createElement("div");
  panel.className = "qr-error";
  panel.setAttribute("role", "alert");
  const mark = Object.assign(document.createElement("span"), { className: "qr-error-mark", textContent: "!" });
  mark.setAttribute("aria-hidden", "true");
  const title = document.createElement("strong");
  I18N.set(title, code, params);
  panel.append(mark, title);
  const fixes = code === "qr.tooSmall"
    ? ["qr.fix.version", ...(params.fittingLevel ? ["qr.fix.level"] : []), "qr.fix.content"]
    : code === "qr.tooLong" ? ["qr.fix.lowerLevel", "qr.fix.content"] : [];
  if (fixes.length) {
    const list = document.createElement("ul");
    fixes.forEach(key => {
      const li = document.createElement("li");
      I18N.set(li, key, params);
      list.append(li);
    });
    panel.append(list);
  }
  $("#qr").replaceChildren(panel);
  $("#qr").classList.add("has-error");
  I18N.set($("#qr-info"), null);
}

/* ---------------------------------------------------------------- data attributes
   GS1 Digital Link data attributes (URI Syntax 1.7, section 4.10): AIs such as expiry date or net weight
   written in the query string of the QR code. They are not stored on the resolver: they apply only to
   the code drawn now, and are cleared when another record is opened. The AIs, their names and formats
   come from the GS1 Barcode Syntax Dictionary (GET /portal/api/config, dataAttributes). */
let attrTimer = null;

// Offered first, in this order, when the record's key allows them (the full list follows)
const COMMON_ATTRIBUTES = ["17", "15", "11", "13", "16", "7003", "310n", "392n", "30", "422", "02", "37", "10"];

function attributeConfig() {
  return (CONFIG && CONFIG.dataAttributes) || { available: false };
}

/* An offered AI, a decimal family ("310n": decimals from the value typed) or a member of one ("3103":
   3 decimals, which the list does not show on its own but can be typed). */
function attributeByCode(code) {
  const ais = attributeConfig().ais || [];
  const found = ais.find(a => a.ai === code);
  if (found || !/^\d{4}$/.test(code || "")) return found;
  const family = ais.find(a => a.family && a.ai === code.slice(0, 3) + "n");
  return family && Number(code[3]) <= family.decimals
    ? { ...family, ai: code, family: false, fixedDecimals: Number(code[3]) } : undefined;
}

/* The AIs that can be attributes of the record being edited: the key itself and its qualifiers go in
   the path (a batch of a GTIN is its own record), so they are not offered. */
function attributesForKey() {
  const key = readKey().ai;
  const inPath = new Set([key, ...((attributeConfig().inPath || {})[key] || [])]);
  return (attributeConfig().ais || []).filter(a => !inPath.has(a.ai));
}

/* "(17) USE BY or EXPIRY", "17", "(17)" → "17"; "(310n) NET WEIGHT (kg)" → "310n" */
function attributeCode(text) {
  const match = String(text || "").trim().match(/^\(?(\d{3}n|\d{2,4})\)?/i);
  return match ? match[1].toLowerCase() : "";
}

/* "(392n) Preço de item de medida variável (PRICE)" in Portuguese; "(392n) PRICE", the GS1 data title, in
   English. Names of the families serve their members: (3922) is named as (392n). */
function attributeName(attribute) {
  const key = `ai.${attribute.ai}`;
  const familyKey = `ai.${attribute.ai.slice(0, 3)}n`;
  const name = I18N.has(key) ? t(key) : (attribute.fixedDecimals !== undefined && I18N.has(familyKey) ? t(familyKey) : "");
  const title = attribute.title || "";
  return name && title ? `${name} (${title})` : name || title;
}

/* The same text in the field and in the list: the code, then the name */
function attributeLabel(attribute) {
  return `(${attribute.ai}) ${attributeName(attribute)}`;
}

/* A list of AIs in a message ("(30) Quantidade variável (VAR. COUNT), (31nn)…"): named when known. */
function attributeList(codes) {
  return (codes || []).map(code => { const a = attributeByCode(code); return a ? attributeLabel(a) : `(${code})`; }).join("; ");
}

function readAttributes() {
  if (!$("#opt-attrs").checked) return [];
  return $$("#attr-rows .attr-row")
    .map(row => [row.aiCode(), $(".attr-value", row).value.trim()])
    .filter(([ai, value]) => ai || value)
    .map(([ai, value]) => [ai || "?", value]);
}

/* Format hint for an AI, from its dictionary components: "6 digits · date YYMMDD". For decimal families and
   their members the number is typed as usual, with comma or point. */
function attributeHint(attribute) {
  if (attribute.family) {
    return t("attrs.decimal.family", { max: attribute.decimals, digits: attribute.components.at(-1).max,
                                       prefix: attribute.components.length > 1 ? t("attrs.decimal.currency") : "" });
  }
  if (attribute.fixedDecimals !== undefined) {
    return t("attrs.decimal.fixed", { n: attribute.fixedDecimals, digits: attribute.components.at(-1).max,
                                      prefix: attribute.components.length > 1 ? t("attrs.decimal.currency") : "" });
  }
  return attribute.components.map(c => {
    const size = t(`attrs.size.${c.type}.${c.min === c.max ? "fixed" : "var"}`, { n: c.max });
    const rules = c.linters.filter(l => I18N.has(`attrs.lint.${l}`)).map(l => t(`attrs.lint.${l}`));
    const text = [size, ...rules].join(" · ");
    return c.optional ? t("attrs.optional", { text }) : text;
  }).join(" + ");
}

/* Combo box for the AI: type to filter by number or name, or open the whole list with the arrow button,
   a click in the field (its text is selected, so typing replaces it) or the Down key. Works with touch,
   mouse and keyboard (ARIA 1.2 combobox with a listbox popup). */
let comboCount = 0;

function attributeCombo(onChange) {
  const id = `attr-combo-${++comboCount}`;
  const wrap = Object.assign(document.createElement("div"), { className: "combo" });
  const input = Object.assign(document.createElement("input"), {
    className: "attr-ai", autocomplete: "off", spellcheck: false, type: "text" });
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${id}-list`);
  input.dataset.i18nAttr = "placeholder:attrs.aiPlaceholder;aria-label:attrs.ai";
  const toggle = Object.assign(document.createElement("button"), { type: "button", className: "combo-toggle", tabIndex: -1 });
  toggle.dataset.i18nAttr = "aria-label:attrs.showList;title:attrs.showList";
  const list = Object.assign(document.createElement("ul"), { className: "combo-list", id: `${id}-list`, hidden: true });
  list.setAttribute("role", "listbox");
  list.dataset.i18nAttr = "aria-label:attrs.ai";
  wrap.append(input, toggle, list);

  let selected = "";                 // chosen AI code
  let options = [];                  // option elements currently listed
  let active = -1;

  const setActive = index => {
    if (!options[index]) index = -1;             // nothing matches the filter
    options.forEach((o, i) => o.classList.toggle("is-active", i === index));
    active = index;
    if (index >= 0) {
      input.setAttribute("aria-activedescendant", options[index].id);
      options[index].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const render = filter => {
    const all = attributesForKey();
    const byCode = new Map(all.map(a => [a.ai, a]));
    const words = fold(filter).split(/\s+/).filter(Boolean);
    const digits = String(filter || "").replace(/[()\s]/g, "");
    const matches = a => !words.length || (/^\d+$/.test(digits)
      ? (a.family ? a.ai.slice(0, 3).startsWith(digits.slice(0, 3)) && (digits.length < 4 || Number(digits[3]) <= a.decimals)
                  : a.ai.startsWith(digits))
      : words.every(w => fold(attributeLabel(a)).includes(w)));
    const groups = words.length ? [[null, all.filter(matches)]]
      : [["attrs.common", COMMON_ATTRIBUTES.map(code => byCode.get(code)).filter(Boolean)], ["attrs.all", all]];
    list.replaceChildren();
    options = [];
    for (const [heading, items] of groups) {
      if (heading && items.length) {
        const li = Object.assign(document.createElement("li"), { className: "combo-group" });
        li.setAttribute("role", "presentation");
        I18N.set(li, heading);
        list.append(li);
      }
      for (const attribute of items) {
        const li = Object.assign(document.createElement("li"), { className: "combo-option",
          id: `${id}-${heading ? heading.split(".").pop() : "m"}-${attribute.ai}` });
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(attribute.ai === selected));
        li.dataset.ai = attribute.ai;
        const code = Object.assign(document.createElement("span"), { className: "combo-code", textContent: `(${attribute.ai})` });
        li.append(code, " ", attributeName(attribute));
        list.append(li);
        options.push(li);
      }
    }
    if (!options.length) {
      const li = Object.assign(document.createElement("li"), { className: "combo-empty" });
      li.setAttribute("role", "presentation");
      I18N.set(li, "attrs.noMatch");
      list.append(li);
    }
  };

  const open = filter => {
    render(filter);
    list.hidden = false;
    wrap.classList.add("is-open");
    input.setAttribute("aria-expanded", "true");
    const current = options.findIndex(o => o.dataset.ai === selected);
    setActive(current >= 0 ? current : (filter ? 0 : -1));
  };
  const close = () => {
    list.hidden = true;
    wrap.classList.remove("is-open");
    input.setAttribute("aria-expanded", "false");
    setActive(-1);
  };
  const choose = code => {
    const attribute = attributeByCode(code);
    selected = attribute ? code : "";
    input.value = attribute ? attributeLabel(attribute) : input.value;
    close();
    onChange();
  };
  // Text typed without picking from the list: "17" or "(17)" becomes (17) and its name
  const settleTyped = () => {
    const code = attributeCode(input.value);
    if (!code) {                      // left after searching by name without picking: back to the choice
      const chosen = attributeByCode(selected);
      if (chosen) input.value = attributeLabel(chosen);
      return;
    }
    const attribute = attributesForKey().find(a => a.ai === code) || (code.length === 4 && attributeByCode(code));
    if (attribute && input.value !== attributeLabel(attribute)) {
      selected = code;
      input.value = attributeLabel(attribute);
      onChange();
    } else if (!attribute) {
      selected = code;                 // unknown or not allowed: the server says why
    }
  };

  input.addEventListener("click", () => {
    if (list.hidden) { input.select(); open(""); }
  });
  input.addEventListener("input", () => {
    // A number chooses ("17", "3103"); an emptied field clears the choice; any other text only searches
    // the list and keeps the attribute already chosen until another one is picked
    const typed = attributeCode(input.value);
    if (typed || !input.value.trim()) selected = typed;
    open(input.value);
    onChange();
  });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (list.hidden) { open(""); return; }
      const next = active + (e.key === "ArrowDown" ? 1 : -1);
      setActive(Math.max(0, Math.min(options.length - 1, next)));
    } else if (e.key === "Enter" && !list.hidden && active >= 0) {
      e.preventDefault();
      choose(options[active].dataset.ai);
    } else if (e.key === "Escape" && !list.hidden) {
      e.preventDefault();
      close();
      const attribute = attributeByCode(selected);
      if (attribute) input.value = attributeLabel(attribute);
    }
  });
  input.addEventListener("blur", () => setTimeout(() => {
    if (!wrap.contains(document.activeElement)) { close(); settleTyped(); }
  }, 0));
  // pointerdown + preventDefault keeps the focus in the field, so the list does not close before the click
  toggle.addEventListener("pointerdown", e => e.preventDefault());
  toggle.addEventListener("click", () => {
    if (list.hidden) { input.focus(); input.select(); open(""); } else { close(); }
  });
  list.addEventListener("pointerdown", e => e.preventDefault());
  list.addEventListener("click", e => {
    const option = e.target.closest(".combo-option");
    if (option) choose(option.dataset.ai);
  });

  return {
    element: wrap,
    input,
    code: () => selected || attributeCode(input.value),
    set(code) { selected = code; const a = attributeByCode(code); input.value = a ? attributeLabel(a) : code; },
    refresh() { const a = attributeByCode(selected); if (a && document.activeElement !== input) input.value = attributeLabel(a); },
    focus() { input.focus(); },
  };
}

function iconButton(className, text, i18nKey, onClick) {
  const button = Object.assign(document.createElement("button"), { type: "button", className: `attr-btn ${className}`, textContent: text });
  button.dataset.i18nAttr = `aria-label:${i18nKey};title:${i18nKey}`;
  button.addEventListener("click", onClick);
  return button;
}

function refreshAttributeRows() {
  const rows = $$("#attr-rows .attr-row");
  rows.forEach((row, index) => {
    $(".attr-up", row).disabled = index === 0;
    $(".attr-down", row).disabled = index === rows.length - 1;
  });
  $("#attr-add").disabled = rows.length >= (attributeConfig().max || 10);
}

function addAttributeRow(ai = "", value = "") {
  const row = document.createElement("div");
  row.className = "attr-row";
  const valueInput = Object.assign(document.createElement("input"), {
    className: "attr-value code", value, autocomplete: "off", spellcheck: false });
  valueInput.dataset.i18nAttr = "aria-label:attrs.value;placeholder:attrs.valuePlaceholder";
  const hint = Object.assign(document.createElement("small"), { className: "attr-hint" });
  const resolved = Object.assign(document.createElement("small"), { className: "attr-resolved", hidden: true });

  const describe = () => {
    const attribute = attributeByCode(combo.code());
    hint.textContent = attribute ? attributeHint(attribute) : "";
    valueInput.maxLength = attribute ? attribute.components.reduce((n, c) => n + c.max, 0) : 90;
    const decimal = attribute && (attribute.family || attribute.fixedDecimals !== undefined);
    valueInput.maxLength = decimal ? 30 : valueInput.maxLength;
    valueInput.inputMode = decimal ? "decimal"
      : attribute && attribute.components.every(c => c.type === "N") ? "numeric" : "text";
  };
  const combo = attributeCombo(() => { describe(); renderPreview(); });
  if (ai) combo.set(ai);
  const move = direction => {
    const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (direction < 0) sibling.before(row); else sibling.after(row);
    refreshAttributeRows();
    // keep the focus on the same button unless it became disabled at the end of the list
    const button = $(direction < 0 ? ".attr-up" : ".attr-down", row);
    (button.disabled ? $(direction < 0 ? ".attr-down" : ".attr-up", row) : button).focus();
    renderPreview();
  };
  const up = iconButton("attr-up", "↑", "attrs.up", () => move(-1));
  const down = iconButton("attr-down", "↓", "attrs.down", () => move(1));
  const remove = iconButton("attr-remove", "×", "attrs.remove", () => {
    row.remove();
    if (!$$("#attr-rows .attr-row").length) addAttributeRow();
    refreshAttributeRows();
    renderPreview();
  });
  valueInput.addEventListener("input", renderPreview);
  const tools = Object.assign(document.createElement("div"), { className: "attr-tools" });
  tools.append(up, down, remove);
  row.append(combo.element, tools, valueInput, hint, resolved);
  row.aiCode = () => combo.code();
  row.describe = () => { combo.refresh(); describe(); };   // on a change of language: names and hints
  row.focusAi = () => combo.focus();
  $("#attr-rows").append(row);
  I18N.apply(row);
  describe();
  refreshAttributeRows();
  return row;
}

function resetAttributes() {
  const had = $("#opt-attrs").checked;
  $("#attr-rows").replaceChildren();
  $("#opt-attrs").checked = false;
  $("#attrs").hidden = true;
  I18N.set($("#attr-msg"), null);
  if (had) renderPreview();
}

function setupAttributes() {
  const config = attributeConfig();
  $("#opt-attrs-choice").hidden = !config.available;
  if (!config.available) return;
  $("#opt-attrs").addEventListener("change", () => {
    $("#attrs").hidden = !$("#opt-attrs").checked;
    if ($("#opt-attrs").checked && !$$("#attr-rows .attr-row").length) addAttributeRow().focusAi();
    renderPreview();
  });
  $("#attr-add").addEventListener("click", () => addAttributeRow().focusAi());
  document.addEventListener("localechange", () => $$("#attr-rows .attr-row").forEach(row => row.describe()));
}

/* Label options: human readable interpretation (every element string, only the key, none), QR version
   (automatic by default) and error correction level (M by default). Remembered in the browser.
   The preview image is the exported label itself, so what is shown is what is downloaded. */
const LABEL_OPTIONS_KEY = "gs1resolver.portal.labelOptions";
const LABEL_DEFAULTS = { hri: "full", version: "auto", ecl: "m", size: "100", linear: "none", symbol: "qr", env: "retail",
                         hritext: "outline" };

function labelOptionsQuery() {
  const symbol = $("#opt-symbol").value;
  const params = new URLSearchParams({ hri: $("#opt-hri").value });
  if (symbol === "qr") { params.set("version", $("#opt-version").value); params.set("ecl", $("#opt-ecl").value); }
  else params.set("symbol", symbol);
  params.set("env", $("#opt-env").value);
  if ($("#opt-hritext").value === "text") params.set("hritext", "text");
  if ($("#opt-size").value !== "100") params.set("size", $("#opt-size").value);
  if (!$("#opt-linear-field").hidden && $("#opt-linear").value !== "none") params.set("linear", $("#opt-linear").value);
  if ($("#opt-domain").value) params.set("domain", $("#opt-domain").value);
  return params.toString();
}

/* The domain in the QR code (Documentation/adr/0009-tenant-domains.md): "" (the default of the record's prefix, else
   the installation's), "installation", or a verified domain of the scope. The same rule as the server's
   domains.label_base(), so that the address drawn under the code is the one in it. */
function fillDomainOption() {
  const list = CONFIG?.domains?.verified || [];
  const select = $("#opt-domain");
  const previous = select.value;
  $("#opt-domain-field").hidden = !list.length;
  const host = url => url.replace(/^https?:\/\//, "");
  select.replaceChildren(i18nOption("label.domainDefault", ""),
    new Option(host(CONFIG?.domains?.installation || CONFIG?.resolver || ""), "installation"),
    ...list.map(d => new Option(host(d.url), d.domain)));
  select.value = [...select.options].some(o => o.value === previous) ? previous : "";
}

function domainBase(g) {
  if (!CONFIG) return "";
  const list = CONFIG.domains?.verified || [];
  const choice = $("#opt-domain").value;
  if (choice === "installation") return CONFIG.resolver;
  if (choice) return (list.find(d => d.domain === choice) || { url: CONFIG.resolver }).url;
  if (!g.ok) return CONFIG.resolver;
  const part = ["01", "8006", "00", "8003"].includes(g.ai) ? g.value.slice(1) : g.value;
  let best = null, length = -1;
  list.forEach(d => (d.defaultFor || []).forEach(p => {
    if (part.startsWith(p) && p.length > length) { best = d; length = p.length; }
  }));
  return best ? best.url : CONFIG.resolver;
}

/* The scanning environments of the key (label.environments_for() on the server): its own tables, else the trade
   items'; direct part marking for every key. The first is the key's default. */
function environmentsFor(ai) {
  const envs = CONFIG?.labelEnvironments || {};
  const own = new Set(Object.values(envs).flatMap(e => e.keys || []));
  return Object.keys(envs).sort((a, b) => envs[a].rank - envs[b].rank).filter(name => envs[name].anyKey
    || (envs[name].keys ? envs[name].keys.includes(ai) : !own.has(ai)));
}

/* "80 % (X 0.396 mm)": each size with the 2D symbol's X-dimension in the scanning environment, in the user's number
   format; only the sizes within the environment's ranges (with an EAN/UPC beside, its range too). The environment
   offers its own 2D symbols and the linear symbol when it takes one, and only the key's environments are offered
   (ADR 0010, section 7). */
function fillSizeOptions() {
  const envs = CONFIG?.labelEnvironments;
  if (envs) {
    const allowed = environmentsFor(readKey().ai || "01");
    for (const o of $("#opt-env").options) o.hidden = o.disabled = !allowed.includes(o.value);
    if (!allowed.includes($("#opt-env").value)) $("#opt-env").value = allowed[0];
  }
  const env = envs?.[$("#opt-env").value] || { x: [0.396, 0.495, 0.990], sizes: [80, 90, 100, 120, 150, 200],
                                                symbols: ["qr", "dm", "gs1dm"], linearX: [0.264, 0.330, 0.660] };
  for (const o of $("#opt-symbol").options) o.hidden = o.disabled = !env.symbols.includes(o.value);
  if (!env.symbols.includes($("#opt-symbol").value)) $("#opt-symbol").value = env.symbols[0];
  const qr = $("#opt-symbol").value === "qr";
  $("#opt-version-field").hidden = $("#opt-ecl-field").hidden = !qr;
  $("#opt-linear-field").classList.toggle("env-off", !env.linearX);
  if (!env.linearX) $("#opt-linear").value = "none";
  const withLinear = env.linearX && !$("#opt-linear-field").hidden && $("#opt-linear").value !== "none";
  const sizes = withLinear ? env.sizesWithLinear : env.sizes;
  const format = new Intl.NumberFormat(I18N.locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  [...$("#opt-size").options].forEach(o => {
    const size = Number(o.value);
    o.textContent = t(size === 100 ? "label.size.target" : "label.size.option", { size, x: format.format(env.x[1] * size / 100) });
    o.hidden = o.disabled = !sizes.includes(size);
  });
  if (!sizes.includes(Number($("#opt-size").value))) $("#opt-size").value = sizes.includes(100) ? "100" : String(sizes[0]);
}

function setupLabelOptions() {
  fillSizeOptions();
  document.addEventListener("localechange", fillSizeOptions);
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(LABEL_OPTIONS_KEY) || "{}");
  } catch { /* defaults */ }
  if (typeof saved.hri === "boolean") saved.hri = saved.hri ? "full" : "none";   // earlier versions: on/off
  const fields = { hri: "#opt-hri", version: "#opt-version", ecl: "#opt-ecl", size: "#opt-size", linear: "#opt-linear",
                   symbol: "#opt-symbol", env: "#opt-env", hritext: "#opt-hritext" };
  for (const [name, selector] of Object.entries(fields)) {
    const select = $(selector);
    const value = saved[name] ?? LABEL_DEFAULTS[name];
    select.value = [...select.options].some(o => o.value === value) ? value : LABEL_DEFAULTS[name];
    select.addEventListener("change", () => {
      if (["env", "symbol", "linear"].includes(name)) fillSizeOptions();
      try {
        localStorage.setItem(LABEL_OPTIONS_KEY, JSON.stringify(
          Object.fromEntries(Object.entries(fields).map(([n, sel]) => [n, $(sel).value]))));
      } catch { /* not persisted */ }
      renderPreview();
    });
  }
  fillSizeOptions();                             // a saved size the saved environment does not allow
}

function toggleLink(a, href) {
  if (href) { a.href = href; a.removeAttribute("aria-disabled"); }
  else { a.removeAttribute("href"); a.setAttribute("aria-disabled", "true"); }
}

/* ------------------------------------------------------------------ step 1: identify the product */
/* Key type changed: label, hint, keyboard and the batch option follow the key. */
function onKeyTypeChange() {
  const ai = currentKey();
  const input = $("#key-value");
  I18N.set($("#key-label"), ai === "01" ? "gtin.label" : `key.${ai}.label`);
  input.setAttribute("data-i18n-attr", `placeholder:${ai === "01" ? "gtin.placeholder" : `key.${ai}.placeholder`}`);
  input.placeholder = t(ai === "01" ? "gtin.placeholder" : `key.${ai}.placeholder`);
  const numeric = NUMERIC_KINDS.includes(keyRule(ai).kind);
  input.inputMode = numeric ? "numeric" : "text";
  // room for the spaces and hyphens people type between digit groups
  input.maxLength = ai === "01" ? 20 : numeric ? 34 : 40;
  buildQualifierFields();
  if (CONFIG) $$("#links .link-type").forEach(select => fillTypeSelect(select, select.value));   // the key type's order
  onIdentityChange();
}

function fillKeyTypes() {
  const select = $("#key-type");
  const current = select.value || "01";
  select.replaceChildren(...(CONFIG?.keys || [{ code: "01" }]).map(k => {
    const option = new Option("", k.code);
    option.dataset.i18n = `key.${k.code}.name`;
    option.textContent = t(`key.${k.code}.name`);
    return option;
  }));
  select.value = current;
}

/* The key's GS1 Company Prefix under the key, by GS1's GCP length table when one is loaded (ADR 0015). */
let gcpSeq = 0, gcpTimer = null;

function formatDay(iso) {
  return iso ? new Intl.DateTimeFormat(I18N.locale, { dateStyle: "short", timeZone: "UTC" }).format(new Date(iso)) : "—";
}

function refreshGcpHint(g) {
  const box = $("#gcp-hint");
  clearTimeout(gcpTimer);
  if (!CONFIG?.gcpTable || !g.ok) { box.hidden = true; return; }
  const seq = ++gcpSeq;
  gcpTimer = setTimeout(async () => {
    try {
      const found = await api("GET", "gcp/lookup?" + new URLSearchParams({ key: g.ai, value: g.value }));
      if (seq !== gcpSeq) return;
      if (!found.date) { box.hidden = true; return; }
      const date = formatDay(found.date);
      if (found.length === 0) I18N.set(box, "gcp.editorNotGcp", { date });
      else if (found.length === null) I18N.set(box, "gcp.editorUnknown", { date });
      else I18N.set(box, "gcp.editorLine", { prefix: found.prefix, n: found.length, date });
      box.className = "field-msg gcp-hint" + (found.length === 0 ? " is-warn" : "");
      box.hidden = false;
    } catch {
      if (seq === gcpSeq) box.hidden = true;
    }
  }, 250);
}

function onIdentityChange() {
  const g = readKey();
  const l = readQualifiers();
  const gtinMsg = $("#key-msg");
  I18N.set(gtinMsg, g.key, g.params);
  gtinMsg.className = "field-msg" + (g.error ? " is-error" : g.ok ? " is-ok" : "");
  const qualMsg = $("#qual-msg");
  I18N.set(qualMsg, l.ok ? null : l.key, l.params);
  qualMsg.className = "field-msg" + (l.error ? " is-error" : "");

  $("#open").disabled = !(CONFIG && g.ok && l.ok);
  refreshGcpHint(g);
  markInformative(g, l);
  renderScope(g, l);
  // The batch or variant of a serial number is informative: changing it keeps the record open
  const key = g.ok && l.ok ? recordKey(g, l) : null;
  if (state.openKey && key !== state.openKey) {
    state.pendingUnsaved = hasUnsavedChanges(true);   // asked about before another record is opened
    state.openKey = null;
    $("#editor").disabled = true;
    setOpenMessage("open.changed");
  }
  renderPreview();
}

/* With a serial number, the variant and batch fields of a GTIN or ITIP are marked as informative. */
function markInformative(g, l) {
  const rule = keyConfig(g.ai).informative;
  const serial = rule && $(`#q-${rule.serial}`)?.value.trim();
  for (const field of $$("#qualifiers .qual-field")) {
    field.classList.toggle("is-informative", Boolean(serial) && rule.ais.includes(field.dataset.ai));
  }
}

/* "This record applies to: …" under the qualifiers, in plain words, with what happens to codes that have no
   record of their own (the resolver walks up to a less specific record, section 2.5.9). */
function renderScope(g, l) {
  const box = $("#scope");
  if (!g.ok || !l.ok || !keyConfig(g.ai).qualifiers.length) { box.hidden = true; return; }
  const { pairs, informative } = splitInformative(g.ai, l.pairs);
  const name = t(`key.${g.ai}.short`);
  I18N.set($("#scope-what"), pairs.length ? null : g.ai === "01" ? "scope.everyUnit" : "scope.wholeKey", { name });
  if (pairs.length) $("#scope-what").textContent = qualText(pairs);
  const notes = [];
  if (informative.length) notes.push(["scope.informative", { list: qualText(informative) }]);
  if (!pairs.length) notes.push(["scope.keyFallback", { name }]);
  else if (pairs.some(([q]) => q === "21" || q === "235")) notes.push(["scope.unitFallback", { name }]);
  else notes.push(["scope.narrowFallback", { name }]);
  $("#scope-notes").replaceChildren(...notes.map(([k, params]) => {
    const li = document.createElement("li");
    I18N.set(li, k, params);
    return li;
  }));
  box.hidden = false;
}

/* The open message may have a second sentence listing other records on the same GTIN. */
function setOpenMessage(key, params, otherEntries = []) {
  const box = $("#open-msg");
  const main = document.createElement("span");
  I18N.set(main, key, params);
  const parts = [main];
  if (otherEntries.length) {
    const extra = document.createElement("span");
    I18N.set(extra, otherEntries.length === 1 ? "open.othersOne" : "open.othersCount", { count: otherEntries.length });
    parts.push(" ", extra);
  }
  box.replaceChildren(...parts);
  renderOthers(otherEntries);
}

/* ---------------------------------------------------------------- other records of the same key
   Below "Open record": the other records of the key (the product itself, batches, serials, variants…),
   with a text search, a filter by key qualifier, five rows in view at a time (the list scrolls) and a
   button to open each one. Opening asks first when the record being edited has unsaved changes. */
const othersState = { entries: [] };

function otherApplies(entry) {
  if (entry.kind === "product") return t("others.product");
  if (entry.kind === "other") return entry.value;
  return qualText(entry.qualifiers) + informativeText(entry.informative);
}

function renderOthers(entries) {
  othersState.entries = entries || [];
  renderLandingUse();
  const box = $("#others");
  box.hidden = !othersState.entries.length;
  if (box.hidden) return;
  I18N.set($("#others-title"), "others.title", { count: othersState.entries.length, key: t(`key.${readKey().ai}.short`) });
  // Filter: every key qualifier present in the list
  const present = [...new Set(othersState.entries.flatMap(e => [...(e.qualifiers || []), ...(e.informative || [])].map(([q]) => q)))]
    .sort((a, b) => qualOrder().indexOf(a) - qualOrder().indexOf(b));
  const filter = $("#others-filter");
  const previous = filter.value;
  filter.replaceChildren(new Option(t("others.filter.all"), ""),
    ...(othersState.entries.some(e => e.kind === "product") ? [new Option(t("others.filter.product"), "product")] : []),
    ...present.map(q => new Option(t(`qual.${q}.label`), q)));
  filter.value = [...filter.options].some(o => o.value === previous) ? previous : "";
  $("#others-search").value = "";
  drawOthers();
}

function drawOthers() {
  const words = fold($("#others-search").value).split(/\s+/).filter(Boolean);
  const kind = $("#others-filter").value;
  const shown = othersState.entries.filter(e =>
    (!kind || (kind === "product" ? e.kind === "product"
                                   : [...(e.qualifiers || []), ...(e.informative || [])].some(([q]) => q === kind)))
    && words.every(w => fold(`${otherApplies(e)} ${e.description || ""}`).includes(w)));
  const body = $("#others-body");
  body.replaceChildren(...shown.map(entry => {
    const tr = document.createElement("tr");
    const cell = (className, text) => Object.assign(document.createElement("td"), { className, textContent: text });
    const when = cell("col-when", entry.updatedAt ? formatWhen(entry.updatedAt) : "—");
    if (entry.updatedBy) when.append(Object.assign(document.createElement("small"), { textContent: entry.updatedBy }));
    const action = document.createElement("td");
    const button = Object.assign(document.createElement("button"), { type: "button", className: "btn btn-ghost others-open" });
    I18N.set(button, "others.open");
    if (entry.kind === "other") {
      button.disabled = true;                 // created by another tool with qualifiers the portal does not edit
      button.title = t("records.otherHint");
    } else {
      button.setAttribute("aria-label", t("others.openAria", { what: otherApplies(entry) }));
      button.addEventListener("click", () => openOther(entry));
    }
    action.append(button);
    tr.append(cell("col-applies", otherApplies(entry)), cell("col-desc", entry.description || "—"),
              cell("col-links num", String(entry.links ?? "")), when, action);
    return tr;
  }));
  I18N.set($("#others-foot"), shown.length > 5 ? "others.footScroll" : "others.foot",
           { shown: shown.length, total: othersState.entries.length });
  fitOthers();
}

/* Exactly five rows in view: the header plus the first five rows as drawn (rows can wrap). */
function fitOthers() {
  const scroll = $("#others-scroll");
  if ($("#others").hidden) return;
  scroll.style.maxHeight = "";
  const head = $("thead", scroll).getBoundingClientRect().height;
  const rows = $$("#others-body tr").slice(0, 5).reduce((n, r) => n + r.getBoundingClientRect().height, 0);
  if ($$("#others-body tr").length > 5) scroll.style.maxHeight = `${Math.ceil(head + rows) + 1}px`;
}

/* The record being edited as it would be saved, to tell whether it has unsaved changes. */
function editorSnapshot() {
  const { key, description, links, landingPage } = collect();
  const informative = splitInformative(key, readQualifiers().pairs || []).informative;
  return JSON.stringify({ description, links, landingPage, informative });
}

/* Whether the open record has unsaved changes. With targetsOnly the informative batch and variant are left
   out: when the key or qualifiers have just changed, they belong to the new identity, not to the record. */
function hasUnsavedChanges(targetsOnly = false) {
  if (!state.openKey || $("#editor").disabled || state.snapshot === undefined) return false;
  const now = JSON.parse(editorSnapshot()), then = JSON.parse(state.snapshot);
  if (targetsOnly) { delete now.informative; delete then.informative; }
  return JSON.stringify(now) !== JSON.stringify(then);
}

async function openOther(entry) {
  if (hasUnsavedChanges() && !await ask(t("others.confirmDiscard"), { danger: true })) return;
  state.snapshot = editorSnapshot();         // confirmed: do not ask again in openRecord
  const values = Object.fromEntries([...(entry.qualifiers || []), ...(entry.informative || [])]);
  for (const field of document.querySelectorAll("#qualifiers .qual-field")) {
    $("input", field).value = values[field.dataset.ai] || "";
  }
  onIdentityChange();
  await openRecord();
  $("#open").scrollIntoView({ block: "start", behavior: "smooth" });
}

async function openRecord() {
  const g = readKey(), l = readQualifiers();
  if (!CONFIG || !g.ok || !l.ok) return;
  if ((state.pendingUnsaved || hasUnsavedChanges()) && !await ask(t("others.confirmDiscard"), { danger: true })) return;
  state.pendingUnsaved = false;
  const button = $("#open");
  button.disabled = true;
  setOpenMessage("open.loading");
  hideStatus();
  try {
    const record = await api("GET", "record?" + query(g, l));
    state.openKey = recordKey(g, l);
    state.hasKeyRecord = record.hasKeyRecord !== false;
    state.keyPromptDone = false;
    // A serial number opened without its batch or variant shows the stored ones; typed ones that differ are
    // kept (they replace the stored ones on saving) and the difference is pointed out.
    const typed = splitInformative(g.ai, l.pairs).informative;
    const stored = record.storedInformative || [];
    let informativeNote = null;
    if (!typed.length && stored.length) {
      for (const [q, v] of stored) { const input = $(`#q-${q}`); if (input) input.value = v; }
      onIdentityChange();
    } else if (record.exists && JSON.stringify(typed) !== JSON.stringify(stored)) {
      informativeNote = stored.length ? ["informative.differs", { stored: qualText(stored) }] : ["informative.added", {}];
    }
    state.exists = record.exists;
    resetAttributes();                  // data attributes belong to the code drawn for one item, not the record
    state.sharedDefaultLinkType = record.sharedDefaultLinkType;
    $("#description").value = record.description || "";
    $("#links").replaceChildren();
    // a new record starts with the choice of the key's own record
    $("#landing-page").checked = !!record.landingPage || (!record.exists && !!record.keyRecordLanding);
    if (record.links.length) record.links.forEach(addRow);
    else addRow({ linkType: record.sharedDefaultLinkType && record.sharedDefaultLinkType !== "gs1:defaultLink"
                            ? record.sharedDefaultLinkType : "gs1:pip" });
    refreshDefault();

    setOpenMessage(record.exists ? "open.found" : "open.new", {}, record.otherEntries);
    if (informativeNote) {
      I18N.set($("#qual-msg"), ...informativeNote);
      $("#qual-msg").className = "field-msg is-warn";
    }
    state.snapshot = editorSnapshot();         // unsaved changes are measured from here
    $("#delete").hidden = !record.exists;
    $("#history-toggle").hidden = false;
    $("#history-panel").hidden = true;
    $("#history-toggle").setAttribute("aria-expanded", "false");
    lockForReader();
    setPublished(record.exists);
    $("#editor").disabled = false;
    $("#description").focus();
  } catch (e) {
    setOpenMessage(e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

function setPublished(published) {
  const el = $("#state");
  I18N.set(el, published ? "state.live" : "state.draft");
  el.classList.toggle("is-live", published);
}

/* ------------------------------------------------------------------ record list (#records) */
const records = { all: [], loaded: false };

function isRecordsView() { return location.hash.split("?")[0] === "#records"; }

const VIEWS = { "#records": "records", "#users": "users", "#audit": "audit", "#tenants": "tenants", "#apikeys": "apikeys",
                "#requests": "requests", "#overview": "overview", "#domains": "domains",
                "#branding": "branding", "#sso": "sso", "#organisation": "organisation", "#alerts": "alerts",
                "#privacy": "privacy", "#forwarding": "forwarding", "#appearance": "appearance" };

/* Shows the editor, the record list, the user administration, the organisations or the audit trail, following
   the address (#records, #users, #tenants, #audit), so the browser's back button and bookmarks work. Users and the
   audit trail follow the account's role (a server administrator in support access is a reader of records but
   still an administrator); organisations are for server administrators. */
function applyView() {
  let view = VIEWS[location.hash.split("?")[0]] || "editor";      // "#records?key=01&…": the list's filters
  if ((view === "users" || view === "audit" || view === "apikeys" || view === "domains"
       || view === "branding" || view === "sso" || view === "organisation" || view === "alerts") && CONFIG
      && CONFIG.accountRole !== "admin") view = "editor";
  if (["tenants", "privacy", "forwarding", "appearance"].includes(view) && CONFIG && !CONFIG.serverAdmin) view = "editor";
  $("#editor-view").hidden = view !== "editor";
  $("#records-view").hidden = view !== "records";
  $("#users-view").hidden = view !== "users";
  $("#tenants-view").hidden = view !== "tenants";
  $("#audit-view").hidden = view !== "audit";
  $("#apikeys-view").hidden = view !== "apikeys";
  $("#requests-view").hidden = view !== "requests";
  $("#overview-view").hidden = view !== "overview";
  $("#domains-view").hidden = view !== "domains";
  $("#branding-view").hidden = view !== "branding";
  $("#sso-view").hidden = view !== "sso";
  $("#organisation-view").hidden = view !== "organisation";
  $("#alerts-view").hidden = view !== "alerts";
  $("#privacy-view").hidden = view !== "privacy";
  $("#forwarding-view").hidden = view !== "forwarding";
  $("#appearance-view").hidden = view !== "appearance";
  markCurrent(view);
  if (view !== "apikeys") forgetNewKey();
  const titles = { editor: "intro", records: "records", users: "users", audit: "audit", tenants: "tenants",
                   apikeys: "apikeys", requests: "requests", overview: "overview", domains: "domains",
                   branding: "branding", sso: "sso", organisation: "org", alerts: "alerts", privacy: "privacy",
                   forwarding: "forwarding", appearance: "appearance" };
  I18N.set($("#hero-title"), `${titles[view]}.title`);
  I18N.set($("#hero-lede"), `${titles[view]}.lede`);
  const link = $("#hero-link");
  link.href = view === "editor" ? "#records" : "#";
  I18N.set(link, view === "editor" ? "records.link" : "records.back");
  if (view === "records") loadRecords();
  if (view === "users" && CONFIG) loadUsers();
  if (view === "tenants" && CONFIG) loadTenants();
  if (view === "audit" && CONFIG) loadAudit();
  if (view === "apikeys" && CONFIG) loadApiKeys();
  if (view === "requests" && CONFIG) loadRequestsView();
  if (view === "overview" && CONFIG) loadOverview();
  if (view === "domains" && CONFIG) loadDomains();
  if (view === "branding" && CONFIG) loadBranding();
  if (view === "sso" && CONFIG) loadSso();
  if (view === "organisation" && CONFIG) loadOrganisation();
  if (view === "alerts" && CONFIG) loadOrganisations().then(() => loadAlerts());
  if (view === "privacy" && CONFIG) loadPrivacy();
  if (view === "forwarding" && CONFIG) loadForwarding();
  if (view === "appearance" && CONFIG) loadAppearance();
}

/* ------------------------------------------------------------------ the appearance (ADR 0019)
   Server administrators set the installation's title, logo and colours; the preview follows the form, the server
   checks every value (the contrast of white text too) and "Restore the original" removes them all. */
const appearanceState = { data: null, logo: null, icon: null };

function appearanceStatus(kind, key, params) {
  const box = $("#appearance-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

function previewAppearance() {
  const box = $("#appearance-preview");
  box.style.setProperty("--preview-colour", $("#appearance-colour").value);
  box.style.setProperty("--preview-action", $("#appearance-action").value);
  box.style.setProperty("--preview-accent", $("#appearance-accent").value);
  const title = $("#appearance-name").value.trim() || appearanceState.data?.defaults.title || "";
  $("#appearance-preview-title").textContent = title;
  $("#appearance-preview-tab-title").textContent = title;          // the browser's tab: the icon and the title
  const data = appearanceState.data;
  $("#appearance-preview-logo").src = appearanceState.logo
    || ($("#appearance-logo-original").checked || !data ? "logo.svg" : data.logo);
  $("#appearance-preview-icon").src = appearanceState.icon
    || ($("#appearance-icon-original").checked || !data ? "favicon.png" : data.icon);
}

function renderAppearance() {
  const data = appearanceState.data;
  if (!data) return;
  const readOnly = Boolean(CONFIG?.support);
  $("#appearance-name").value = data.original ? "" : data.title;
  $("#appearance-name").placeholder = data.defaults.title;
  for (const field of ["colour", "action", "accent"]) $("#appearance-" + field).value = data[field].toLowerCase();
  for (const field of ["logo", "icon"]) {
    $(`#appearance-${field}`).value = "";
    appearanceState[field] = null;
    $(`#appearance-${field}-original`).checked = false;
  }
  $("#appearance-logo-original").closest("label").hidden = !data.customLogo;
  $("#appearance-icon-original").closest("label").hidden = !data.customIcon;
  if (data.original) I18N.set($("#appearance-state"), "appearance.stateOriginal");
  else I18N.set($("#appearance-state"), "appearance.stateChanged",
                { when: formatWhen(data.updated), user: data.updatedBy || "" });
  $("#appearance-reset").hidden = data.original;
  for (const field of $$("#appearance-form input, #appearance-form button")) field.disabled = readOnly;
  if (readOnly) appearanceStatus("warn", "appearance.readOnly");
  previewAppearance();
}

async function loadAppearance() {
  try {
    appearanceState.data = await api("GET", "appearance");
    renderAppearance();
  } catch (e) {
    appearanceStatus("error", e.code, e.params);
  }
}

/* The pages' own look follows at once: the header's title and logo, and the colours (appearance.css again) */
function showAppearance(found) {
  appearanceState.data = found;
  Appearance.show(found);
  const sheet = $('link[href^="appearance.css"]');
  if (sheet) sheet.href = "appearance.css?v=" + Date.now();
  renderAppearance();
}

/* The logo or the icon chosen: read for the preview and the request (field: "logo" or "icon") */
async function pickAppearanceImage(field) {
  const file = $(`#appearance-${field}`).files[0];
  appearanceState[field] = null;
  if (file) {
    if (file.size > 200 * 1024) {
      $(`#appearance-${field}`).value = "";
      appearanceStatus("error", "branding.logoTooLarge", { max: 200 });
    } else {
      appearanceState[field] = await readFile(file);
      $(`#appearance-${field}-original`).checked = false;
    }
  }
  previewAppearance();
}

async function saveAppearance(event) {
  event.preventDefault();
  const body = { title: $("#appearance-name").value.trim(), colour: $("#appearance-colour").value,
                 action: $("#appearance-action").value, accent: $("#appearance-accent").value };
  for (const field of ["logo", "icon"]) {
    if (appearanceState[field]) body[field] = appearanceState[field];
    else if ($(`#appearance-${field}-original`).checked) body[field] = "";
  }
  try {
    const answer = await api("PUT", "appearance", body);
    showAppearance(answer.appearance);
    appearanceStatus("ok", answer.code, answer.params);
  } catch (e) {
    appearanceStatus("error", e.code, e.params);
  }
}

async function resetAppearance() {
  if (!(await ask(t("appearance.confirmReset")))) return;
  try {
    const answer = await api("DELETE", "appearance");
    showAppearance(answer.appearance);
    appearanceStatus("ok", answer.code, answer.params);
  } catch (e) {
    appearanceStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ forwarding (ADR 0018)
   Server administrators set the resolver of last resort (a key this resolver does not know goes there) and the prefix
   rules (every key of a prefix goes to its destination). The server checks every value; the screen shows its answer. */
const forwardingState = { data: null, editing: null };

function forwardingStatus(kind, key, params) {
  const box = $("#forwarding-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

function renderForwarding() {
  const data = forwardingState.data;
  if (!data) return;
  const fb = data.fallback;
  $("#fallback-enabled").checked = fb.enabled;
  $("#fallback-url").value = fb.url === fb.default ? "" : fb.url;
  $("#fallback-url").placeholder = fb.default;
  I18N.set($("#fallback-state"), fb.enabled ? "forwarding.fallbackOnState" : "forwarding.fallbackOffState",
           { url: fb.url });
  $("#forwarding-rules").replaceChildren(...data.rules.map(rule => {
    const tr = el("tr", rule.enabled ? "" : "is-off");
    const toggle = el("input");
    toggle.type = "checkbox";
    toggle.checked = rule.enabled;
    toggle.setAttribute("aria-label", t("forwarding.enabled") + " " + rule.prefix);
    toggle.disabled = data.readOnly;
    toggle.addEventListener("change", () => saveRule(null, { ...rule, enabled: toggle.checked }));
    const enabledCell = el("td");
    enabledCell.append(toggle);
    const actions = el("td", "forwarding-row-actions");
    if (!data.readOnly) {
      const edit = el("button", "btn btn-ghost btn-small", t("forwarding.edit"));
      edit.type = "button";
      edit.addEventListener("click", () => editRule(rule));
      const remove = el("button", "btn btn-ghost btn-small", t("forwarding.remove"));
      remove.type = "button";
      remove.addEventListener("click", () => removeRule(rule));
      actions.append(edit, remove);
    }
    const organisations = el("td", rule.organisations.length ? "is-warn" : "", rule.organisations.join(", ") || "—");
    tr.append(el("td", "code forwarding-prefix", rule.prefix), el("td", "code", rule.target),
              el("td", "", t(rule.mode === "fixed" ? "forwarding.mode.fixedShort" : "forwarding.mode.pathShort")),
              enabledCell, organisations, el("td", "", rule.note || ""),
              el("td", "", rule.updated ? `${formatWhen(rule.updated)} · ${rule.updatedBy || ""}` : ""), actions);
    return tr;
  }));
  $("#forwarding-empty").hidden = data.rules.length > 0;
  for (const field of $$("#forwarding-fallback-form input, #forwarding-fallback-form button, " +
                         "#forwarding-rule-form input, #forwarding-rule-form select, #forwarding-rule-form button")) {
    field.disabled = data.readOnly;
  }
  if (data.readOnly) forwardingStatus("warn", "forwarding.readOnly");
}

async function loadForwarding() {
  try {
    forwardingState.data = await api("GET", "forwarding");
    renderForwarding();
  } catch (e) {
    forwardingStatus("error", e.code, e.params);
  }
}

function resetRuleForm() {
  forwardingState.editing = null;
  $("#forwarding-rule-form").reset();
  $("#rule-prefix").readOnly = false;
  $("#rule-enabled").checked = true;
  I18N.set($("#rule-save"), "forwarding.add");
  $("#rule-cancel").hidden = true;
}

function editRule(rule) {
  forwardingState.editing = rule.prefix;
  $("#rule-prefix").value = rule.prefix;
  $("#rule-prefix").readOnly = true;
  $("#rule-target").value = rule.target;
  $("#rule-mode").value = rule.mode;
  $("#rule-note").value = rule.note || "";
  $("#rule-enabled").checked = rule.enabled;
  I18N.set($("#rule-save"), "forwarding.saveRule");
  $("#rule-cancel").hidden = false;
  $("#rule-target").focus();
}

async function saveFallback(event) {
  event.preventDefault();
  try {
    const answer = await api("PUT", "forwarding/fallback", { enabled: $("#fallback-enabled").checked,
                                                             url: $("#fallback-url").value.trim() });
    forwardingState.data = answer;
    renderForwarding();
    forwardingStatus("ok", answer.code, answer.params);
  } catch (e) {
    forwardingStatus("error", e.code, e.params);
  }
}

/* A rule from the form (event) or from a row's switch (rule) */
async function saveRule(event, rule) {
  if (event) event.preventDefault();
  const editing = rule ? rule.prefix : forwardingState.editing;
  const body = rule ? { target: rule.target, mode: rule.mode, enabled: rule.enabled, note: rule.note }
    : { prefix: $("#rule-prefix").value.trim(), target: $("#rule-target").value.trim(), mode: $("#rule-mode").value,
        enabled: $("#rule-enabled").checked, note: $("#rule-note").value };
  try {
    const answer = editing ? await api("PUT", "forwarding/rules/" + encodeURIComponent(editing), body)
                           : await api("POST", "forwarding/rules", body);
    forwardingState.data = answer;
    if (!rule) resetRuleForm();
    renderForwarding();
    const saved = answer.rules.find(r => r.prefix === answer.params.prefix);
    if (saved && saved.enabled && saved.organisations.length) {
      forwardingStatus("warn", "forwarding.ruleSavedOverlap", { prefix: saved.prefix,
                                                                names: saved.organisations.join(", ") });
    } else {
      forwardingStatus("ok", answer.code, answer.params);
    }
  } catch (e) {
    forwardingStatus("error", e.code, e.params);
    if (rule) renderForwarding();               // the switch back as it was
  }
}

async function removeRule(rule) {
  if (!(await ask(t("forwarding.confirmRemove", { prefix: rule.prefix })))) return;
  try {
    const answer = await api("DELETE", "forwarding/rules/" + encodeURIComponent(rule.prefix));
    forwardingState.data = answer;
    if (forwardingState.editing === rule.prefix) resetRuleForm();
    renderForwarding();
    forwardingStatus("ok", answer.code, answer.params);
  } catch (e) {
    forwardingStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ the privacy notice (ADR 0017)
   Server administrators write the installation's notice; each publication is a new version. The text starts from the
   version in force, or the default notice in the administrator's language; the preview uses the public page's own
   renderer (privacy.js). */
const privacyState = { data: null };

function privacyStatus(kind, key, params) {
  const box = $("#privacy-admin-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

async function loadPrivacy() {
  // The hint names the two words replaced in the text: kept as they are written
  I18N.set($("#privacy-text-hint"), "privacy.textHint", { operator: "{operator}", days: "{days}" });
  try {
    const data = privacyState.data = await api("GET", "privacy");
    const notice = data.versions.length ? (await api("GET", "privacy?version=" + data.current)).notice : null;
    I18N.set($("#privacy-state"), notice ? "privacy.versionOf" : "privacy.defaultInUse",
             notice ? { version: notice.version, when: formatWhen(notice.at) } : {});
    const box = $("#privacy-text");
    if (!box.dataset.edited) box.value = notice ? notice.text : t("privacy.default");
    $("#privacy-versions").replaceChildren(...data.versions.map(v => {
      const tr = el("tr");
      const view = el("a", "", t("privacy.view"));
      view.href = "privacy?version=" + v.version;
      view.target = "_blank";
      view.rel = "noopener";
      [el("td", "num", String(v.version)), el("td", "", formatWhen(v.at)), el("td", "", v.by || ""),
       el("td", "", v.note || "")].forEach(td => tr.append(td));
      const action = el("td");
      action.append(view);
      tr.append(action);
      return tr;
    }));
    const readOnly = Boolean(CONFIG.support);
    $("#privacy-text").readOnly = readOnly;
    $("#privacy-publish").hidden = readOnly;
    if (readOnly) privacyStatus("warn", "privacy.readOnly");
  } catch (e) {
    privacyStatus("error", e.code, e.params);
  }
}

function previewPrivacy() {
  const data = privacyState.data || {};
  const box = $("#privacy-preview");
  PrivacyText.render(box, $("#privacy-text").value, { operator: data.operator || "—", days: String(data.days ?? "") });
  box.hidden = false;
}

async function publishPrivacy(event) {
  event.preventDefault();
  const next = (privacyState.data?.current || 0) + 1;
  if (!(await ask(t("privacy.confirmPublish", { version: next })))) return;
  try {
    const answer = await api("PUT", "privacy", { text: $("#privacy-text").value, note: $("#privacy-note").value });
    delete $("#privacy-text").dataset.edited;
    $("#privacy-note").value = "";
    await loadPrivacy();
    privacyStatus("ok", answer.code, answer.params);
  } catch (e) {
    privacyStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ navigation (ADR 0013) */
/* The sidebar of wide screens: the screens of the user menu (.nav-item), with the same rules of who sees which (their
   classes), folded to icons on request (remembered in this browser). */
const SIDEBAR_KEY = "portal.sidebar";

function buildSidebar() {
  const list = $("#sidebar-list");
  list.replaceChildren(...$$(".menu-panel a.nav-item").map(item => {
    const li = el("li");
    const link = item.cloneNode(true);
    link.removeAttribute("id");
    link.removeAttribute("role");
    link.className = item.className.replace("menu-item", "sidebar-item");
    link.dataset.for = item.id;
    const label = $("span", link);
    if (label) link.title = t(label.dataset.i18n);
    li.append(link);
    return li;
  }));
  I18N.apply(list);
  let folded = false;
  try { folded = localStorage.getItem(SIDEBAR_KEY) === "folded"; } catch { /* storage refused: unfolded */ }
  foldSidebar(folded);
  markCurrent(VIEWS[location.hash.split("?")[0]] || "editor");
}

function foldSidebar(folded) {
  document.body.classList.toggle("sidebar-folded", folded);
  $("#sidebar-toggle").setAttribute("aria-expanded", String(!folded));
  $("#sidebar-toggle").setAttribute("aria-label", t(folded ? "nav.unfold" : "nav.fold"));
  $("#sidebar-toggle").title = t(folded ? "nav.unfold" : "nav.fold");
  try { localStorage.setItem(SIDEBAR_KEY, folded ? "folded" : "open"); } catch { /* not remembered */ }
}

/* The current screen marked in the sidebar and the menu. */
function markCurrent(view) {
  const target = view === "editor" ? "#editor" : "#" + view;
  for (const link of $$(".sidebar-item, .menu-panel a.nav-item")) {
    if (link.getAttribute("href") === target) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

/* ------------------------------------------------------------------ prefixes as rows (ADR 0013) */
/* One GS1 Company Prefix per row, with "Add GCP" and a remove button on each; each row checked as it is typed (4 to
   12 digits); mark(prefix) points out the row a refusal of the server names. Returns { values(), mark() }. */
function prefixRows(container, values = [], { editable = true } = {}) {
  container.replaceChildren();
  const list = el("ul", "prefix-list");
  const add = el("button", "btn btn-ghost prefix-add");
  add.type = "button";
  I18N.set(add, "prefixes.add");
  const row = value => {
    const li = el("li", "prefix-row");
    const input = el("input");
    input.value = value || ""; input.inputMode = "numeric"; input.autocomplete = "off"; input.maxLength = 12;
    input.setAttribute("aria-label", t("prefixes.one"));
    input.disabled = !editable;
    const msg = el("span", "field-msg is-error prefix-msg");
    input.addEventListener("input", () => {
      const v = input.value.trim();
      const bad = v && !/^\d{4,12}$/.test(v);
      li.classList.toggle("is-invalid", Boolean(bad));
      input.setAttribute("aria-invalid", String(Boolean(bad)));
      msg.textContent = bad ? t("prefixes.invalid") : "";
    });
    li.append(input);
    if (editable) {
      const remove = el("button", "btn btn-danger-ghost prefix-remove", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", t("prefixes.remove"));
      remove.title = t("prefixes.remove");
      remove.addEventListener("click", () => { li.remove(); if (!list.children.length) list.append(row("")); });
      li.append(remove);
    }
    li.append(msg);
    return li;
  };
  (values.length ? values : [""]).forEach(v => list.append(row(v)));
  add.addEventListener("click", () => { const li = row(""); list.append(li); $("input", li).focus(); });
  container.append(list);
  if (editable) container.append(add);
  return {
    values: () => $$("input", list).map(i => i.value.trim()).filter(Boolean),
    valid: () => $$("input", list).every(i => !i.value.trim() || /^\d{4,12}$/.test(i.value.trim())),
    mark(prefix) {
      for (const li of $$(".prefix-row", list)) {
        const hit = prefix && $("input", li).value.trim() === prefix;
        li.classList.toggle("is-invalid", hit);
        if (hit) $("input", li).focus();
      }
    },
  };
}

/* ------------------------------------------------------------------ users' prefixes picked (ADR 0013) */
/* A searchable list of the organisation's prefixes with checkboxes; a longer prefix inside one of them can be added
   from the search box. Without prefixes to pick from (the operator's users), a text field as before. */
function prefixPicker(available, selected = [], label = "users.prefixes") {
  if (!available || !available.length) {
    const input = el("input");
    input.value = selected.join(", ");
    input.autocomplete = "off";
    input.setAttribute("aria-label", t(label));
    input.placeholder = t("users.allPrefixes");
    input.value_ = () => prefixesFrom(input.value);
    input.getValues = () => prefixesFrom(input.value);
    return input;
  }
  const box = el("details", "prefix-picker");
  const summary = el("summary");
  const panel = el("div", "picker-panel");
  const search = el("input");
  search.type = "search"; search.autocomplete = "off";
  search.setAttribute("aria-label", t("prefixes.search"));
  search.placeholder = t("prefixes.search");
  const list = el("ul", "picker-list");
  const addButton = el("button", "btn btn-ghost picker-add");
  addButton.type = "button"; addButton.hidden = true;
  const chosen = new Set(selected);
  const options = [...new Set([...available, ...selected])].sort();
  const refreshSummary = () => {
    summary.textContent = chosen.size ? (chosen.size <= 3 ? [...chosen].sort().join(", ")
      : t("prefixes.count", { count: chosen.size })) : t("users.allPrefixes");
  };
  const draw = () => {
    const words = search.value.trim();
    list.replaceChildren(...options.filter(p => p.includes(words)).map(p => {
      const li = el("li");
      const lab = el("label", "choice");
      const cb = el("input");
      cb.type = "checkbox"; cb.value = p; cb.checked = chosen.has(p);
      cb.addEventListener("change", () => { cb.checked ? chosen.add(p) : chosen.delete(p); refreshSummary(); });
      lab.append(cb, el("span", "", p));
      li.append(lab);
      return li;
    }));
    const longer = /^\d{5,12}$/.test(words) && !options.includes(words) && available.some(p => words.startsWith(p));
    addButton.hidden = !longer;
    if (longer) addButton.textContent = t("prefixes.addLonger", { prefix: words });
  };
  addButton.addEventListener("click", () => {
    const p = search.value.trim();
    options.push(p); options.sort(); chosen.add(p); search.value = ""; draw(); refreshSummary();
  });
  search.addEventListener("input", draw);
  panel.append(search, list, addButton);
  box.append(summary, panel);
  box.setAttribute("aria-label", t(label));
  refreshSummary(); draw();
  box.getValues = () => [...chosen].sort();
  return box;
}

/* The prefixes an organisation's users may be limited to: its own (null for the operator's users). */
function tenantPrefixes(tenantId) {
  if (!tenantId) return null;
  if (CONFIG.tenant && CONFIG.tenant.id === tenantId) return CONFIG.tenant.prefixes || [];
  return (people.tenants.find(tn => tn.id === tenantId) || {}).prefixes || [];
}

function newUserPicker() {
  const tenant = CONFIG.serverAdmin ? $("#new-user-tenant").value : CONFIG.tenant?.id;
  const picker = prefixPicker(tenantPrefixes(tenant), [], "users.prefixes");
  picker.id = "new-user-prefixes";
  $("#new-user-prefixes").replaceWith(picker);
}

/* ------------------------------------------------------------------ organisations for server administrators */
let organisations = [];

async function loadOrganisations() {
  if (!CONFIG?.serverAdmin || CONFIG.support) return;
  try {
    organisations = (await api("GET", "tenants")).tenants || [];
  } catch { organisations = []; }
  for (const box of [$("#overview-tenant"), $("#alerts-tenant")]) {
    const was = box.value;
    box.replaceChildren(i18nOption(box.id === "overview-tenant" ? "overview.scopeWhole" : "users.anyTenant", ""),
                        i18nOption(box.id === "overview-tenant" ? "users.operatorName" : "alerts.installation",
                                   box.id === "overview-tenant" ? "operator" : "-"),
                        ...organisations.map(o => new Option(o.name, o.id)));
    box.value = [...box.options].some(o => o.value === was) ? was : "";
  }
}

/* ------------------------------------------------------------------ an organisation's page (ADR 0013) */
const orgState = { data: null, tab: "prefixes", rows: null };

function orgId() {
  return new URLSearchParams(location.hash.split("?")[1] || "").get("id") || "";
}

async function loadOrganisation() {
  const id = orgId();
  I18N.set($("#org-summary"), "records.loading");
  try {
    orgState.data = await api("GET", "organisation" + (id ? "?id=" + encodeURIComponent(id) : ""));
    renderOrganisation();
  } catch (e) {
    orgStatus("error", e.code, e.params);
  }
}

function orgStatus(kind, key, params) {
  const box = $("#org-status");
  box.hidden = !key;
  box.className = "status " + (kind === "ok" ? "is-ok" : "is-error");
  I18N.set(box, key, params);
}

function renderOrganisation() {
  const d = orgState.data;
  if (!d) return;
  $("#org-name").textContent = d.operator ? t("org.operatorTitle") : d.name;
  $("#org-summary").textContent = [
    d.operator ? t("org.operatorNote") : t(d.disabled ? "users.disabled" : "users.active"),
    d.records === null ? "" : t("org.records", { count: d.records }),
    t("org.usersCount", { count: d.users.length })].filter(Boolean).join(" · ");
  if (d.operator && orgState.tab === "prefixes") orgState.tab = "users";       // the operator holds no prefix of its own
  for (const tab of $$("#org-tabs [role=tab]")) {
    const on = tab.dataset.tab === orgState.tab;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    tab.hidden = d.operator && tab.dataset.tab === "prefixes";
  }
  const panel = $("#org-panel");
  panel.setAttribute("aria-labelledby", "org-tab-" + orgState.tab);
  panel.replaceChildren(...orgPanel(d, orgState.tab));
}

/* A link to the screen that changes a part, or the way there for a server administrator (support access). */
function orgManage(screen, ownScreen) {
  const d = orgState.data;
  const p = el("p", "org-manage");
  const mine = !CONFIG.serverAdmin || CONFIG.support || d.operator || ownScreen;
  if (mine) {
    const a = el("a", "", t("org.manage"));
    a.href = screen;
    p.append(a);
  } else if (!d.operator) {
    const b = el("button", "btn btn-ghost", t("org.throughSupport"));
    b.type = "button";
    b.addEventListener("click", () => openSupport({ id: d.id, name: d.name }));
    p.append(b);
  }
  return p;
}

function orgTable(headers, rows) {
  const wrap = el("div", "table-wrap");
  const table = el("table", "records-table org-table");
  const head = el("tr");
  headers.forEach(h => head.append(Object.assign(el("th", "", t(h)), { scope: "col" })));
  const thead = el("thead"); thead.append(head);
  const tbody = el("tbody");
  rows.forEach(cells => {
    const tr = el("tr");
    cells.forEach((c, i) => {
      const td = el("td");
      if (c instanceof Node) td.append(c); else td.textContent = c;
      td.dataset.label = t(headers[i]);
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  return wrap;
}

function orgPanel(d, tab) {
  const empty = key => el("p", "records-empty", t(key));
  if (tab === "prefixes") {
    const box = el("div", "prefix-rows");
    orgState.rows = prefixRows(box, d.prefixes, { editable: d.canEditPrefixes });
    const out = [el("p", "field-msg", t(d.canEditPrefixes ? "org.prefixesHint" : "org.prefixesReadOnly")), box];
    const warnings = prefixWarnings(d.prefixChecks);
    if (warnings) { warnings.id = "org-gcp-warnings"; out.push(warnings); }
    if (d.canEditPrefixes) {
      const save = el("button", "btn btn-primary", t("org.savePrefixes"));
      save.type = "button";
      save.id = "org-save-prefixes";
      save.addEventListener("click", saveOrgPrefixes);
      out.push(save);
    }
    return out;
  }
  if (tab === "users") {
    return d.users.length ? [orgTable(["users.name", "users.role", "users.prefixes", "users.email", "users.state"],
      d.users.map(u => [u.username, t("role." + u.role), u.prefixes.length ? u.prefixes.join(", ") : t("users.allPrefixes"),
                        u.email || "—", t(u.disabled ? "users.disabled" : u.invited ? "users.invitedState" : "users.active")])),
      orgManage("#users", true)] : [empty("org.noUsers"), orgManage("#users", true)];
  }
  if (tab === "domains") {
    return [d.domains.length ? orgTable(["domains.domain", "org.domainState", "domains.defaults"],
      d.domains.map(x => [x.domain, t(x.verified ? "org.domainVerified" : "org.domainPending"),
                          (x.defaultFor || []).join(", ") || "—"])) : empty("org.noDomains"), orgManage("#domains", true)];
  }
  if (tab === "brands") {
    return [d.brands.length ? orgTable(["branding.prefix", "branding.name", "org.logo"],
      d.brands.map(b => [b.prefix === "*" ? t("branding.installation") : b.prefix, b.name || "—",
                         b.logo ? t("org.yes") : t("org.no")])) : empty("org.noBrands"), orgManage("#branding", false)];
  }
  if (tab === "sso") {
    const c = d.sso[0];
    return [c ? orgTable(["sso.issuer", "sso.domains", "org.ssoState"], [[c.issuer, c.domains.join(", ") || "—",
      t(c.enabled ? (c.passwordOff ? "org.ssoOnlySso" : "org.ssoOn") : "org.ssoOff")]]) : empty("org.noSso"),
      orgManage("#sso", true)];
  }
  if (tab === "apikeys") {
    return [d.apikeys.length ? orgTable(["apikeys.name", "apikeys.scopes", "apikeys.expires", "users.state"],
      d.apikeys.map(k => [k.name, k.scopes.join(", "), formatWhen(k.expiresAt), t("apikeys.state." + k.state)]))
      : empty("org.noKeys"), orgManage("#apikeys", false)];
  }
  if (tab === "exports") return orgExports(d);
  const link = el("p", "org-manage");
  const a = el("a", "", t("org.allAlerts"));
  a.href = "#alerts" + (CONFIG.serverAdmin && !CONFIG.support ? "?tenant=" + encodeURIComponent(d.operator ? "-" : d.id) : "");
  link.append(a);
  return [d.alerts.length ? alertsTable(d.alerts, false) : empty("alerts.none"), link];
}

/* The most rows one export of each role may hold (backlog item 9.8): set by the organisation's administrators (and by
   server administrators outside support access) within the installation's maximum; empty follows the maximum, 0 is
   no export. The operator's roles have no maximum; server administrators no limit. */
const EXPORT_ROLES = ["reader", "editor", "admin", "api"];

function exportRoleName(role) {
  return t(role === "api" ? "exports.role.api" : "role." + role);
}

function exportApplies(n, max, operator) {
  if (n === null || n === undefined) return t("exports.unlimited");
  if (n === 0) return t("exports.none");
  return t(!operator && max !== null && n === max ? "exports.upToMaximum" : "exports.upTo", { max: nf(n) });
}

function orgExports(d) {
  const x = d.exports, max = x.maximum;
  const out = [el("p", "field-msg", t(d.operator ? "exports.introOperator" : "exports.intro"))];
  if (!d.operator) {
    const note = el("p", "status is-warn org-exports-maximum",
                    max === null ? t("exports.noMaximum") : t("exports.maximumNote", { max: nf(max) }));
    note.id = "org-exports-maximum";
    out.push(note);
  }
  const rows = EXPORT_ROLES.map(role => {
    let field;
    if (role === "admin") {
      field = el("span", "muted", d.operator ? t("exports.serverAdmins") : "—");
    } else {
      field = el("input", "org-export-limit");
      Object.assign(field, { type: "number", min: "0", inputMode: "numeric", id: "org-export-" + role,
                             value: x.limits[role] ?? "", placeholder: t("exports.placeholder"), disabled: !x.editable });
      if (!d.operator && max !== null) field.max = String(max);
      field.dataset.role = role;
      field.setAttribute("aria-label", exportRoleName(role));
    }
    const own = x.limits[role];
    const above = !d.operator && max !== null && own !== undefined && own !== null && own > max;
    const applies = el("span", "", exportApplies(x.effective[role], max, d.operator)
                    + (above ? " · " + t("exports.aboveMaximum", { max: nf(max) }) : ""));
    applies.id = "org-export-applies-" + role;
    return [exportRoleName(role), field, applies];
  });
  out.push(orgTable(["exports.role", "exports.limit", "exports.applies"], rows));
  if (x.editable) {
    const save = el("button", "btn btn-primary", t("exports.save"));
    save.type = "button";
    save.id = "org-save-exports";
    save.addEventListener("click", saveOrgExports);
    out.push(save);
  } else {
    out.push(el("p", "field-msg", t("exports.readOnly")));
  }
  out.push(el("p", "field-msg", t("exports.journalNote")));
  return out;
}

async function saveOrgExports() {
  const d = orgState.data, limits = {};
  for (const input of $$("#org-panel .org-export-limit")) {
    if (!input.checkValidity()) {
      input.focus();
      orgStatus("error", "exports.invalid", { max: nf(d.operator || d.exports.maximum === null ? 10000000 : d.exports.maximum) });
      return;
    }
    limits[input.dataset.role] = input.value.trim() === "" ? null : Number(input.value);
  }
  try {
    const result = await api("PUT", "exports/limits", { tenant: d.id, limits });
    d.exports = { ...d.exports, ...result.exports };
    renderOrganisation();
    orgStatus("ok", result.code, result.params);
  } catch (e) {
    orgStatus("error", e.code, e.params && e.params.max !== undefined ? { ...e.params, max: nf(e.params.max) } : e.params);
  }
}

async function saveOrgPrefixes() {
  const d = orgState.data, rows = orgState.rows;
  if (!rows.valid()) { orgStatus("error", "prefixes.invalid"); return; }
  const prefixes = rows.values();
  if (!await ask(t("tenants.confirmPrefixes", { name: d.name }))) return;
  try {
    const result = await api("PUT", "tenants/" + encodeURIComponent(d.id), { prefixes });
    orgStatus("ok", result.code, result.params);
    await loadOrganisation();
  } catch (e) {
    orgStatus("error", e.code, e.params);
    rows.mark(e.params?.prefix);
  }
}

/* ------------------------------------------------------------------ alert history (ADR 0013) */
// An active alert in the overview's facts: a spike's count, the log's share of its space
function overviewAlert(a) {
  return t("overview.alert." + a.kind, { count: a.detail?.count ?? "", percent: nf(a.detail?.percent ?? 0) });
}

function alertText(a) {
  const d = a.detail || {};
  const what = a.kind === "404" ? t("overview.alert.404", { count: d.count ?? "" })
    : a.kind === "logspace" && d.percent !== undefined ? t("overview.alert.logspace", { percent: nf(d.percent) })
    : t("overview.check." + a.kind);
  const extra = d.error || d.reason || (d.host ? d.host : "") || "";
  return extra ? `${what} · ${extra}` : what;
}

function alertsTable(list, withOrganisation) {
  const headers = ["alerts.raised", "alerts.ended", "alerts.kind", ...(withOrganisation ? ["alerts.organisation"] : []),
                   "alerts.detail"];
  return orgTable(headers, list.map(a => [formatWhen(a.raisedAt), a.endedAt ? formatWhen(a.endedAt) : t("alerts.ongoing"),
    t("alerts.kind." + a.kind), ...(withOrganisation ? [a.organisation || t("alerts.installation")] : []), alertText(a)]));
}

async function loadAlerts(event) {
  event?.preventDefault();
  const kinds = $("#alerts-kind");
  if (!kinds.options.length) {
    kinds.replaceChildren(i18nOption("alerts.anyKind", ""),
                          ...["resolver", "backup", "certificate", "logspace", "404"].map(k => i18nOption("alerts.kind." + k, k)));
  }
  const fromHash = new URLSearchParams(location.hash.split("?")[1] || "").get("tenant");
  if (fromHash !== null && !event) $("#alerts-tenant").value = fromHash;
  const query = new URLSearchParams();
  if (CONFIG.serverAdmin && !CONFIG.support && $("#alerts-tenant").value) query.set("tenant", $("#alerts-tenant").value);
  for (const [name, box] of [["kind", "#alerts-kind"], ["from", "#alerts-from"], ["to", "#alerts-to"]]) {
    if ($(box).value) query.set(name, $(box).value);
  }
  try {
    const data = await api("GET", "alerts?" + query);
    const operator = CONFIG.serverAdmin && !CONFIG.support;
    $("#alerts-body").replaceChildren(...data.alerts.map(a => {
      const tr = el("tr");
      const cells = [formatWhen(a.raisedAt), a.endedAt ? formatWhen(a.endedAt) : t("alerts.ongoing"), t("alerts.kind." + a.kind),
                     ...(operator ? [a.organisation || t("alerts.installation")] : []), alertText(a)];
      if (!a.endedAt) tr.className = "is-alert";
      cells.forEach(c => tr.append(el("td", "", c)));
      return tr;
    }));
    $("#alerts-empty").hidden = data.alerts.length > 0;
    I18N.set($("#alerts-count"), "alerts.count", { count: data.alerts.length });
    I18N.set($("#alerts-note"), "alerts.note", { days: data.historyDays });
  } catch (e) {
    I18N.set($("#alerts-count"), e.code, e.params);
  }
}

/* ------------------------------------------------------------------ roles */
const isReader = () => CONFIG?.role === "reader";

/* Readers see records but cannot change them: fields are read-only and the write buttons hidden
   (body[data-role] in the style sheet). The server refuses writes anyway. */
function lockForReader() {
  if (!isReader()) return;
  document.querySelectorAll("#description, #links input, #links select, #links button")
    .forEach(el => { el.disabled = true; });
  $("#read-only-note").hidden = false;
}

/* ------------------------------------------------------------------ history of a record */
function formatWhen(iso) {
  return iso ? new Intl.DateTimeFormat(I18N.locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(iso)) : "—";
}

async function toggleHistory() {
  const panel = $("#history-panel");
  const button = $("#history-toggle");
  const open = panel.hidden;
  panel.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
  if (open) await loadHistory();
}

async function loadHistory() {
  const g = readKey(), q = readQualifiers();
  const list = $("#history-list");
  list.replaceChildren();
  I18N.set($("#history-msg"), "history.loading");
  try {
    const { versions } = await api("GET", "history?" + query(g, q));
    I18N.set($("#history-msg"), versions.length ? null : "history.none");
    list.replaceChildren(...versions.map((v, i) => {
      const li = document.createElement("li");
      const when = document.createElement("span"); when.className = "when"; when.textContent = formatWhen(v.at);
      const what = document.createElement("span"); I18N.set(what, "audit.action." + v.action);
      const who = document.createElement("span"); who.className = "who"; who.textContent = v.user;
      li.append(when, what, who);
      if (v.doc && v.action !== "delete" && i > 0 && !isReader()) {
        const restore = document.createElement("button");
        restore.type = "button"; restore.className = "btn btn-ghost";
        I18N.set(restore, "history.restore");
        restore.addEventListener("click", () => restoreVersion(v));
        li.append(restore);
      } else if (v.doc && v.action === "delete" && !isReader()) {
        const restore = document.createElement("button");
        restore.type = "button"; restore.className = "btn btn-ghost";
        I18N.set(restore, "history.restore");
        restore.addEventListener("click", () => restoreVersion(v));
        li.append(restore);
      }
      return li;
    }));
  } catch (e) {
    I18N.set($("#history-msg"), e.code, e.params);
  }
}

/* Brings a previous version into the form; nothing is saved until "Save links". */
function restoreVersion(version) {
  const doc = version.doc;
  $("#description").value = doc.itemDescription || "";
  $("#links").replaceChildren();
  const links = [...(doc.links || [])].sort((a, b) => (a.linktype !== doc.defaultLinktype) - (b.linktype !== doc.defaultLinktype));
  links.forEach(l => addRow({ linkType: l.linktype, url: l.href, title: l.title || "", hreflang: l.hreflang || ["pt"],
                              context: l.context || [] }));
  refreshDefault();
  showStatus("ok", "history.restored", { when: formatWhen(version.at), user: version.user });
  $("#description").focus();
}

/* ------------------------------------------------------------------ the portal's own dialogs */
/* A confirmation in the portal's style (Documentation/adr/0013-administration-and-navigation.md), in place of the
   browser's confirm(): resolves true when confirmed, false when cancelled or closed (Escape). danger: the confirming
   button in red, for what cannot be undone. */
function ask(text, { danger = false } = {}) {
  const dialog = $("#ask-dialog");
  $("#ask-text").textContent = text;
  $("#ask-ok").className = "btn " + (danger ? "btn-danger" : "btn-primary");
  dialog.returnValue = "";
  return new Promise(resolve => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
    $(danger ? "#ask-cancel" : "#ask-ok").focus();
  });
}

/* ------------------------------------------------------------------ user administration */
function prefixesFrom(text) {
  return String(text || "").split(/[\s,;]+/).map(p => p.trim()).filter(Boolean);
}

function usersStatus(kind, key, params) {
  const box = $("#users-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

function showTemporaryPassword(key, user, password) {
  I18N.set($("#temp-password-text"), key, { user });
  $("#temp-password-value").textContent = password;
  $("#temp-password").hidden = false;
}

function roleSelect(value) {
  const select = document.createElement("select");
  ["reader", "editor", "admin"].forEach(role => {
    const option = new Option("", role);
    option.dataset.i18n = "role." + role;
    option.textContent = t("role." + role);
    select.add(option);
  });
  select.value = value;
  return select;
}

const people = { all: [], tenants: [] };

/* An <option> whose text follows the language (data-i18n). */
function i18nOption(key, value, params) {
  const option = new Option("", value);
  option.dataset.i18n = key;
  if (params) option.dataset.i18nParams = JSON.stringify(params);
  option.textContent = t(key, params);
  return option;
}

/* The organisation selector of the new-user form and the organisation filter of the list (server
   administrators): the operator, then every organisation by name. */
function fillTenantSelectors() {
  const box = $("#new-user-tenant"), filter = $("#users-tenant-filter");
  const chosen = box.value, filtered = filter.value;
  box.replaceChildren(i18nOption("users.operator", ""), ...people.tenants.map(tn => new Option(tn.name, tn.id)));
  box.value = people.tenants.some(tn => tn.id === chosen) ? chosen : "";
  filter.replaceChildren(i18nOption("users.anyTenant", "*"), i18nOption("users.operatorName", ""),
                         ...people.tenants.map(tn => new Option(tn.name, tn.id)));
  filter.value = filtered === "" || people.tenants.some(tn => tn.id === filtered) ? filtered : "*";
}

function renderUsers() {
  const filter = $("#users-tenant-filter").value;
  const shown = CONFIG.serverAdmin && filter !== "*" ? people.all.filter(u => (u.tenant || "") === filter) : people.all;
  $("#users-body").replaceChildren(...shown.map(userRow));
}

async function loadUsers() {
  const roleBox = $("#new-user-role");
  if (!roleBox.options.length) {
    const template = roleSelect("editor");
    roleBox.replaceChildren(...template.options);
    roleBox.value = "editor";
  }
  if (!$("#users-tenant-filter").options.length) $("#users-tenant-filter").add(i18nOption("users.anyTenant", "*"));
  try {
    const data = await api("GET", "users");
    people.all = data.users;
    people.tenants = data.tenants || [];
    if (CONFIG.serverAdmin) fillTenantSelectors();
    newUserPicker();
    renderUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

function userRow(u) {
  const tr = document.createElement("tr");
  if (u.disabled) tr.className = "is-disabled";
  const cell = (label, content) => {
    const td = document.createElement("td");
    td.dataset.label = t(label);
    if (content instanceof Node) td.append(content); else td.textContent = content;
    tr.append(td);
    return td;
  };
  cell("users.name", u.username + (u.username === CONFIG.user ? " " + t("users.you") : ""));
  cell("users.tenant", u.tenant ? u.tenantName : t("users.operatorName")).classList.add("needs-server-admin");
  const role = roleSelect(u.role);
  role.setAttribute("aria-label", t("users.role"));
  cell("users.role", role);
  // the organisation's own prefixes to pick from (ADR 0013); the operator's users type them
  const prefixes = prefixPicker(tenantPrefixes(u.tenant), u.prefixes, "users.prefixes");
  cell("users.prefixes", prefixes);
  const email = document.createElement("input");
  email.type = "email"; email.maxLength = 254; email.autocomplete = "off";
  email.value = u.email || "";
  email.setAttribute("aria-label", t("users.email"));
  email.placeholder = t("users.emailPlaceholder");
  cell("users.email", email);
  cell("users.state", t(u.disabled ? "users.disabled" : u.invited ? "users.invitedState"
                        : u.mustChange ? "users.mustChange" : "users.active"));
  cell("users.lastLogin", formatWhen(u.lastLogin));
  const actions = document.createElement("div");
  actions.className = "user-actions";
  const button = (key, handler, cls = "btn-ghost") => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn " + cls;
    I18N.set(b, key);
    b.addEventListener("click", handler);
    actions.append(b);
  };
  button("users.save", () => saveUser(u.username, { role: role.value, prefixes: prefixes.getValues(),
                                                    email: email.value.trim() }), "btn-secondary");
  if (u.username !== CONFIG.user) {                // your own password: user menu → Options
    button(mailLink(u) && u.invited ? "users.resendInvite" : "users.resetPassword", () => resetUser(u));
    button(u.disabled ? "users.enable" : "users.disable", () => saveUser(u.username, { disabled: !u.disabled }));
    button("users.remove", () => removeUser(u.username), "btn-danger-ghost");
  }
  cell("users.actions", actions);
  return tr;
}

/* Whether a reset of this user goes by e-mail (a link) rather than a temporary password shown here. */
function mailLink(u) {
  return Boolean(CONFIG.mail?.enabled && u.email && !u.disabled && u.username !== CONFIG.user);
}

async function createUser(event) {
  event.preventDefault();
  $("#temp-password").hidden = true;
  try {
    const result = await api("POST", "users", {
      username: $("#new-user-name").value.trim(), role: $("#new-user-role").value,
      prefixes: $("#new-user-prefixes").getValues(), email: $("#new-user-email").value.trim(),
      invite: Boolean(CONFIG.mail?.enabled && $("#new-user-invite").checked),
      ...(CONFIG.serverAdmin ? { tenant: $("#new-user-tenant").value } : {}),
    });
    usersStatus("ok", result.code, result.params);
    if (result.password) showTemporaryPassword("users.tempPasswordNew", result.params.user, result.password);
    const tenant = $("#new-user-tenant").value;            // several users of one organisation in a row
    $("#users-create").reset();
    $("#new-user-role").value = "editor";
    $("#new-user-tenant").value = tenant;
    newUserPicker();
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

async function saveUser(username, changes) {
  try {
    const result = await api("PUT", "users/" + encodeURIComponent(username), changes);
    usersStatus("ok", result.code, result.params);
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

async function resetUser(u) {
  const username = u.username;
  const question = !mailLink(u) ? "users.confirmReset" : u.invited ? "users.confirmResendInvite" : "users.confirmResetLink";
  if (!await ask(t(question, { user: username }))) return;
  $("#temp-password").hidden = true;
  try {
    const result = await api("POST", `users/${encodeURIComponent(username)}/reset`, {});
    usersStatus("ok", result.code, result.params);
    if (result.password) showTemporaryPassword("users.tempPasswordReset", username, result.password);
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

async function removeUser(username) {
  if (!await ask(t("users.confirmRemove", { user: username }), { danger: true })) return;
  try {
    const result = await api("DELETE", "users/" + encodeURIComponent(username));
    usersStatus("ok", result.code, result.params);
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ API keys (administrators) */
function apikeysStatus(kind, key, params) {
  const box = $("#apikeys-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

/* The scope the keys belong to: the administrator's organisation, or the operator's records. */
function showApiKeysScope() {
  const tenant = CONFIG.tenant;
  if (tenant) I18N.set($("#apikeys-scope"), "apikeys.scopeTenant", { name: tenant.name });
  else I18N.set($("#apikeys-scope"), "apikeys.scopeOperator");
}

/* A new key is shown once: leaving the screen removes it from the page. */
function forgetNewKey() {
  $("#apikey-new").hidden = true;
  $("#apikey-value").textContent = "";
  $("#apikey-example").textContent = "";
}

async function loadApiKeys() {
  showApiKeysScope();
  try {
    const data = await api("GET", "keys");
    const days = $("#new-apikey-days");
    if (!days.options.length) {
      const choices = [30, 90, 180, 365].filter(d => d <= data.maxDays);
      days.replaceChildren(...choices.map(d => i18nOption("apikeys.daysOption", String(d), { days: d })));
      days.value = String(choices.includes(data.defaultDays) ? data.defaultDays : choices[choices.length - 1]);
    }
    $("#apikeys-body").replaceChildren(...data.keys.map(apiKeyRow));
    $("#apikeys-empty").hidden = data.keys.length > 0;
  } catch (e) {
    apikeysStatus("error", e.code, e.params);
  }
}

function apiKeyRow(k) {
  const tr = document.createElement("tr");
  if (k.state !== "active") tr.className = "is-disabled";
  const cell = (label, content) => {
    const td = document.createElement("td");
    td.dataset.label = t(label);
    if (content instanceof Node) td.append(content); else td.textContent = content;
    tr.append(td);
    return td;
  };
  const name = document.createElement("span");
  const id = document.createElement("code");
  id.textContent = k.id;
  name.append(k.name, document.createElement("br"), id);
  cell("apikeys.name", name);
  cell("apikeys.scopes", k.scopes.map(s => t("apikeys.scopeShort." + s)).join(", "));
  cell("users.prefixes", k.prefixes.length ? k.prefixes.join(", ") : t("users.allPrefixes"));
  cell("apikeys.createdAt", `${formatWhen(k.created)} · ${k.createdBy || "—"}`);
  cell("apikeys.expires", formatWhen(k.expiresAt));
  cell("apikeys.lastUsed", formatWhen(k.lastUsed));
  cell("users.state", k.state === "revoked" ? t("apikeys.stateRevoked", { user: k.revokedBy || "—" })
                                            : t("apikeys.state." + k.state));
  const actions = document.createElement("div");
  actions.className = "user-actions";
  if (k.state === "active") {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn btn-danger-ghost";
    I18N.set(b, "apikeys.revoke");
    b.addEventListener("click", () => revokeApiKey(k));
    actions.append(b);
  }
  cell("users.actions", actions);
  return tr;
}

async function createApiKey(event) {
  event.preventDefault();
  forgetNewKey();
  const scopes = [...document.querySelectorAll("#apikeys-create input[name=scope]:checked")].map(i => i.value);
  try {
    const result = await api("POST", "keys", {
      name: $("#new-apikey-name").value.trim(), scopes, days: Number($("#new-apikey-days").value),
      prefixes: prefixesFrom($("#new-apikey-prefixes").value),
    });
    apikeysStatus("ok", result.code, result.params);
    $("#apikey-value").textContent = result.key;
    const base = new URL("api/v1", location.href).href;
    $("#apikey-example").textContent =
      `curl -H "Authorization: Bearer ${result.key}" ${base}/\n` +
      `curl -H "Authorization: Bearer ${result.key}" "${base}/records?limit=10"`;
    $("#apikey-new").hidden = false;
    $("#new-apikey-name").value = "";
    $("#new-apikey-prefixes").value = "";
    loadApiKeys();
  } catch (e) {
    apikeysStatus("error", e.code, e.params);
  }
}

async function revokeApiKey(k) {
  if (!await ask(t("apikeys.confirmRevoke", { name: k.name }), { danger: true })) return;
  try {
    const result = await api("DELETE", "keys/" + encodeURIComponent(k.id));
    apikeysStatus("ok", result.code, result.params);
    loadApiKeys();
  } catch (e) {
    apikeysStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ organisations (server administrators) */
function tenantsStatus(kind, key, params) {
  const box = $("#tenants-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

let newTenantRows = null;

/* GS1's GCP length table (ADR 0015): the list in use, and a new one uploaded — compressed in the browser, so that
   GS1's 9 MB file passes the 1 MB limit of the proxies; the portal checks it before it replaces the one in use. */
async function showGcpTable() {
  try {
    const { table } = await api("GET", "gcp");
    if (table) I18N.set($("#gcp-current"), "gcp.current", { date: formatDay(table.date), count: nf(table.count),
                                                           user: table.uploadedBy, when: formatWhen(table.uploadedAt) });
    else I18N.set($("#gcp-current"), "gcp.none");
  } catch (e) {
    I18N.set($("#gcp-current"), e.code, e.params);
  }
}

async function postGcp(body, kind, confirm) {
  let res;
  try {
    res = await fetch(BASE + "api/gcp" + (confirm ? "?confirm=1" : ""), { method: "POST", credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": kind }, body });
  } catch {
    throw new ApiError("error.network");
  }
  SessionClock.contact();
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new ApiError(data?.code || "error.unexpected", data?.params || { status: res.status });
  return data;
}

function gcpStatus(kind, key, params) {
  const box = $("#gcp-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

async function uploadGcp(event) {
  event.preventDefault();
  const file = $("#gcp-file").files[0];
  if (!file) { gcpStatus("error", "gcp.noFile"); return; }
  const button = $("#gcp-upload");
  button.disabled = true;
  gcpStatus("", "gcp.uploading");
  const dates = p => ({ ...p, date: formatDay(p.date), current: formatDay(p.current),
                        count: p.count === undefined ? undefined : nf(p.count) });
  try {
    let body = file, kind = "application/xml";
    if (typeof CompressionStream === "function") {
      body = await new Response(file.stream().pipeThrough(new CompressionStream("gzip"))).blob();
      kind = "application/gzip";
    }
    let result;
    try {
      result = await postGcp(body, kind, false);
    } catch (e) {
      if (e.code !== "gcp.older" || !await ask(t("gcp.confirmOlder", dates(e.params)))) throw e;
      result = await postGcp(body, kind, true);
    }
    gcpStatus("ok", result.code, dates(result.params));
    $("#gcp-form").reset();
    CONFIG.gcpTable = { date: result.table.date, count: result.table.count };
    loadTenants();
  } catch (e) {
    gcpStatus("error", e.code, dates(e.params || {}));
  } finally {
    button.disabled = false;
  }
}

/* An organisation's prefixes that GS1's list sees otherwise (longer, shorter, not a company prefix, not listed):
   one warning line each; nothing when they agree or without a list. */
function prefixWarnings(checks) {
  const odd = (checks || []).filter(c => c.status !== "ok");
  if (!odd.length) return null;
  const box = el("div", "gcp-warnings");
  if (CONFIG?.gcpTable) box.append(el("p", "field-msg", t("gcp.checksTitle", { date: formatDay(CONFIG.gcpTable.date) })));
  for (const c of odd) box.append(el("p", "field-msg is-warn", t("gcp.check." + c.status, { prefix: c.prefix, n: c.length })));
  return box;
}

/* The most rows one export may hold in any organisation (backlog item 9.8); empty lifts it. */
async function saveExportMaximum(event) {
  event.preventDefault();
  const input = $("#export-maximum");
  if (!input.checkValidity()) { tenantsStatus("error", "exports.maximumInvalid", { max: nf(10000000) }); return; }
  try {
    const result = await api("PUT", "exports/maximum", { maximum: input.value.trim() === "" ? null : Number(input.value) });
    tenantsStatus("ok", result.code, result.params && result.params.max !== undefined ? { max: nf(result.params.max) } : {});
  } catch (e) {
    tenantsStatus("error", e.code, e.params && e.params.max !== undefined ? { max: nf(e.params.max) } : e.params);
  }
}

async function loadTenants() {
  if (!newTenantRows) newTenantRows = prefixRows($("#new-tenant-prefixes"));
  try {
    const data = await api("GET", "tenants");
    $("#export-maximum").value = data.exportMaximum ?? "";
    showGcpTable();
    $("#tenants-body").replaceChildren(...data.tenants.map(tenantRow));
    $("#tenants-empty").hidden = data.tenants.length > 0;
    if (data.operatorRecords === null) I18N.set($("#tenants-operator"), "tenants.recordsUnavailable");
    else I18N.set($("#tenants-operator"), "tenants.operatorRecords", { count: data.operatorRecords });
  } catch (e) {
    tenantsStatus("error", e.code, e.params);
  }
}

function tenantRow(tn) {
  const tr = document.createElement("tr");
  if (tn.disabled) tr.className = "is-disabled";
  const cell = (label, content) => {
    const td = document.createElement("td");
    td.dataset.label = t(label);
    if (content instanceof Node) td.append(content); else td.textContent = content;
    tr.append(td);
    return td;
  };
  const input = (field, value, label) => {
    const el = document.createElement("input");
    el.value = value; el.autocomplete = "off"; el.dataset.field = field;
    el.setAttribute("aria-label", t(label));
    return el;
  };
  const name = input("name", tn.name, "tenants.name");
  name.maxLength = 80;
  cell("tenants.name", name);
  const prefixCell = cell("tenants.prefixes", tn.prefixes.join(", "));         // changed on the organisation's page
  prefixCell.classList.add("code");
  const warnings = prefixWarnings(tn.prefixChecks);
  if (warnings) prefixCell.append(warnings);
  cell("tenants.users", String(tn.users)).classList.add("count");
  cell("tenants.records", tn.records === null ? "—" : String(tn.records)).classList.add("count");
  cell("users.state", t(tn.disabled ? "users.disabled" : "users.active"));
  const actions = document.createElement("div");
  actions.className = "user-actions";
  const button = (key, handler, cls = "btn-ghost") => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn " + cls;
    I18N.set(b, key);
    b.addEventListener("click", handler);
    actions.append(b);
    return b;
  };
  button("users.save", () => saveTenant(tn, { name: name.value, prefixes: tn.prefixes }), "btn-secondary");
  button("tenants.open", () => { location.hash = "#organisation?id=" + encodeURIComponent(tn.id); });
  button(tn.disabled ? "users.enable" : "users.disable", () => toggleTenant(tn));
  button("tenants.support", () => openSupport(tn));
  const remove = button("users.remove", () => removeTenant(tn), "btn-danger-ghost");
  if (tn.users) {                                    // only an organisation without users can be removed
    remove.disabled = true;
    remove.title = t("tenants.notEmptyHint");
  }
  cell("users.actions", actions);
  return tr;
}

async function createTenant(event) {
  event.preventDefault();
  if (!newTenantRows.valid()) { tenantsStatus("error", "prefixes.invalid"); return; }
  const name = $("#new-tenant-name").value.trim(), prefixes = newTenantRows.values();
  if (prefixes.length && !await ask(t("tenants.confirmCreate", { name, prefixes: prefixes.join(", ") }))) return;
  try {
    const result = await api("POST", "tenants", { name, prefixes });
    tenantsStatus("ok", result.code, result.params);
    $("#tenants-create").reset();
    newTenantRows = prefixRows($("#new-tenant-prefixes"));
    loadTenants();
  } catch (e) {
    tenantsStatus("error", e.code, e.params);
    newTenantRows.mark(e.params?.prefix);
  }
}

async function saveTenant(tn, changes) {
  const same = changes.prefixes.slice().sort().join(",") === tn.prefixes.join(",");
  if (!same && !await ask(t("tenants.confirmPrefixes", { name: tn.name }))) return;
  await tenantCall("PUT", tn, same ? { name: changes.name } : changes);
}

async function toggleTenant(tn) {
  if (!tn.disabled && !await ask(t("tenants.confirmDisable", { name: tn.name }), { danger: true })) return;
  await tenantCall("PUT", tn, { disabled: !tn.disabled });
}

async function removeTenant(tn) {
  if (!await ask(t("tenants.confirmRemove", { name: tn.name }), { danger: true })) return;
  await tenantCall("DELETE", tn);
}

async function tenantCall(method, tn, body) {
  try {
    const result = await api(method, "tenants/" + encodeURIComponent(tn.id), body);
    tenantsStatus("ok", result.code, result.params);
    loadTenants();
  } catch (e) {
    tenantsStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ support access */
let supportTenant = null;

function openSupport(tn) {
  supportTenant = tn;
  I18N.set($("#support-intro"), "support.intro", { name: tn.name });
  $("#support-reason").value = "";
  I18N.set($("#support-msg"), null);
  $("#support-dialog").showModal();
  $("#support-reason").focus();
}

async function startSupport(event) {
  event.preventDefault();
  try {
    await api("POST", "support", { tenant: supportTenant.id, reason: $("#support-reason").value });
  } catch (e) {
    I18N.set($("#support-msg"), e.code, e.params);
    return;
  }
  location.href = BASE + "#records";               // the page starts again in the organisation's scope
  location.reload();
}

async function endSupport() {
  try { await api("DELETE", "support"); } catch { /* the page starts again anyway */ }
  location.href = BASE + "#tenants";
  location.reload();
}

/* The account menu names the user's organisation (or says he is a server administrator); a banner shows an
   open support access. */
function showTenant() {
  const label = $("#user-tenant");
  label.hidden = !(CONFIG.tenant || CONFIG.serverAdmin);
  if (CONFIG.tenant) I18N.set(label, "menu.tenant", { name: CONFIG.tenant.name });
  else if (CONFIG.serverAdmin) I18N.set(label, "menu.serverAdmin");
  $("#support-banner").hidden = !CONFIG.support;
  if (CONFIG.support) I18N.set($("#support-text"), "support.banner", { name: CONFIG.support.name });
}

/* ------------------------------------------------------------------ audit trail */
function auditQuery() {
  const params = new URLSearchParams();
  [["user", "#audit-user"], ["from", "#audit-from"], ["to", "#audit-to"], ["q", "#audit-q"]]
    .forEach(([name, sel]) => { if ($(sel).value) params.set(name, $(sel).value); });
  return params.toString();
}

async function loadAudit(event) {
  if (event) event.preventDefault();
  const select = $("#audit-user");
  if (!select.options.length) {
    const any = new Option("", ""); any.dataset.i18n = "records.anyone"; any.textContent = t("records.anyone");
    select.add(any);
    try {
      const { users } = await api("GET", "users");
      users.forEach(u => select.add(new Option(u.username, u.username)));
    } catch { /* the filter still works by typing */ }
  }
  I18N.set($("#audit-count"), "records.loading");
  try {
    const { events } = await api("GET", "audit?" + auditQuery());
    $("#audit-body").replaceChildren(...events.map(e => {
      const tr = document.createElement("tr");
      const values = [formatWhen(e.at), e.user, e.tenantName || t("users.operatorName"), t("audit.action." + e.action),
                      e.anchor ? e.anchor + (e.qpath || "") : "", e.detail || ""];
      values.forEach((v, i) => {
        const td = document.createElement("td");
        if (i === 2) td.className = "audit-tenant-col";
        if (i === 4) td.className = "code";
        td.textContent = v;
        if (i === 1 && e.byOperator) {               // done by the operator (a server administrator) to this organisation
          const tag = document.createElement("span");
          tag.className = "by-operator";
          I18N.set(tag, "audit.byOperator");
          td.append(tag);
        }
        tr.append(td);
      });
      return tr;
    }));
    I18N.set($("#audit-count"), "audit.count", { count: events.length });
  } catch (e) {
    I18N.set($("#audit-count"), e.code, e.params);
  }
}

function downloadAudit() {
  location.href = BASE + "api/audit.csv?" + auditQuery();
}

/* ------------------------------------------------------------------ requests to the resolver (#requests)
   The log of resolver requests (Documentation/adr/0006-resolver-request-log.md), in the scope of the account: the
   last 30 days as bars, the latest requests with filters and pages, a CSV export, and for administrators the calls
   of the tenant API, and how long requests are kept (section 8). Nothing here identifies the people who scan: the
   server never stores it; the browser family and the approximate location (city) are derived when a scan arrives. */
const REQUEST_OUTCOMES = ["redirect", "notFound", "unknown", "noLink", "choice", "linkset", "invalid", "error", "compressed",
                          "page", "click", "forwarded", "fallback"];
const REQUEST_DEVICES = ["mobile", "tablet", "desktop", "automated", "unknown"];
const REQUEST_BROWSERS = ["chrome", "safari", "firefox", "edge", "samsung", "opera", "app", "other"];
const requestsState = { next: null, apiNext: null, tab: "resolver", retention: null };

function fillRequestFilters() {
  const outcome = $("#requests-outcome"), device = $("#requests-device"), browser = $("#requests-browser");
  if (outcome.options.length) return;
  outcome.append(i18nOption("requests.any", ""), ...REQUEST_OUTCOMES.map(o => i18nOption("requests.outcome." + o, o)));
  device.append(i18nOption("requests.any", ""), ...REQUEST_DEVICES.map(d => i18nOption("requests.device." + d, d)));
  browser.append(i18nOption("requests.any", ""), ...REQUEST_BROWSERS.map(b => i18nOption("requests.browser." + b, b)));
}

function requestsQuery() {
  const params = new URLSearchParams();
  [["from", "#requests-from"], ["to", "#requests-to"], ["code", "#requests-code"], ["outcome", "#requests-outcome"],
   ["device", "#requests-device"], ["browser", "#requests-browser"], ["country", "#requests-country"]]
    .forEach(([name, sel]) => { if ($(sel).value.trim()) params.set(name, $(sel).value.trim()); });
  if ($("#requests-automated").checked) params.set("automated", "1");
  return params;
}

function loadRequestsView() {
  fillRequestFilters();
  const days = CONFIG.requestLog?.days ?? 0;
  $("#requests-off").hidden = days > 0;
  document.body.dataset.requestsWhole = String(Boolean(CONFIG.requestLog?.whole));
  I18N.set($("#requests-privacy"), "requests.privacy", { days });
  showRequestsTab(CONFIG.accountRole === "admin" ? requestsState.tab : "resolver");
  loadRequestDays();
  loadRequests();
}

function showRequestsTab(tab) {
  requestsState.tab = tab;
  for (const name of ["resolver", "api", "retention"]) {
    $("#requests-" + name).hidden = tab !== name;
    $("#requests-tab-" + name).setAttribute("aria-selected", String(tab === name));
  }
  if (tab === "api") loadApiCalls();
  if (tab === "retention") loadRetention();
}

/* A place as "Campinas, Sao Paulo, BR", and the address that opens it in Google Maps: searched by its names, so the
   map shows the city itself and nothing more precise than the log holds (ADR 0006, section 8). */
function placeText(city, region, country) {
  return [city, region, country].filter(Boolean).join(", ");
}

function placeFromKey(key) {
  const [country, region, city] = String(key).split("|");
  return placeText(city, region, country);
}

function mapLink(text, place) {
  const a = el("a", "", text);
  a.href = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(place);
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.title = t("requests.mapTitle", { place });
  return a;
}

function formatBytes(n) {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${new Intl.NumberFormat(I18N.locale, { maximumFractionDigits: i ? 1 : 0 }).format(v)} ${units[i]}`;
}

/* The last 30 days: one bar per day, requests answered (redirects, choices, linksets) and not found (404) stacked;
   automated requests are left out of the bars and counted in the summary. */
async function loadRequestDays() {
  const chart = $("#requests-chart");
  try {
    const { days } = await api("GET", "requests/daily?days=30");
    const shown = days.map(d => {
      const missing = (d.outcome.unknown || 0) + (d.outcome.noLink || 0);
      return { day: d.day, total: Math.max(0, d.total - d.automated), missing, automated: d.automated };
    });
    const top = Math.max(1, ...shown.map(d => d.total));
    const total = shown.reduce((n, d) => n + d.total, 0);
    const missing = shown.reduce((n, d) => n + Math.min(d.missing, d.total), 0);
    const automated = shown.reduce((n, d) => n + d.automated, 0);
    I18N.set($("#requests-summary"), "requests.summary", { total, missing, automated });
    chart.setAttribute("aria-label", t("requests.summary", { total, missing, automated }));
    chart.replaceChildren(...shown.map(d => {
      const bar = document.createElement("div");
      bar.className = "requests-bar";
      const ok = document.createElement("span"), lost = document.createElement("span");
      const lostShare = Math.min(d.missing, d.total);
      ok.className = "bar-ok"; ok.style.height = `${((d.total - lostShare) / top) * 100}%`;
      lost.className = "bar-missing"; lost.style.height = `${(lostShare / top) * 100}%`;
      bar.append(lost, ok);
      const when = new Intl.DateTimeFormat(I18N.locale, { day: "2-digit", month: "2-digit" }).format(new Date(d.day + "T12:00:00"));
      bar.title = t("requests.dayTitle", { day: when, total: d.total, missing: lostShare });
      bar.dataset.day = d.day;
      return bar;
    }));
  } catch (e) {
    I18N.set($("#requests-summary"), e.code, e.params);
    chart.replaceChildren();
  }
}

function requestCell(tr, label, content, className) {
  const td = document.createElement("td");
  td.dataset.label = t(label);
  if (className) td.className = className;
  if (content instanceof Node) td.append(content); else td.textContent = content ?? "";
  tr.append(td);
  return td;
}

function requestRow(e) {
  const tr = document.createElement("tr");
  requestCell(tr, "audit.when", formatWhen(e.at));
  const code = e.anchor ? e.anchor + (e.qualifiers || "") : (e.path || "—");
  const codeCell = requestCell(tr, "requests.code", code, "code");
  if (e.attributes?.length) {
    const small = document.createElement("small");
    small.className = "muted";
    small.textContent = " ?" + e.attributes.join(" ");
    codeCell.append(small);
  }
  if (e.form && e.form !== "uri") {
    const tag = document.createElement("span");
    tag.className = "badge badge-unchanged";
    tag.textContent = e.form === "epc" ? (e.epc || "EPC") : t("requests.form." + e.form);
    codeCell.append(" ", tag);
  }
  const badge = document.createElement("span");
  badge.className = "badge requests-outcome is-" + e.outcome;
  I18N.set(badge, "requests.outcome." + e.outcome);
  requestCell(tr, "requests.outcome", badge);
  const answer = [];
  if (e.linkType) answer.push(t("requests.asked", { type: e.linkType }));
  if (e.level !== null && e.level !== undefined) answer.push(t("requests.level", { level: e.level || t("requests.keyLevel") }));
  if (e.target) answer.push("→ " + e.target);
  if (!answer.length) answer.push(String(e.status ?? ""));
  requestCell(tr, "requests.answer", answer.join(" · "));
  requestCell(tr, "requests.device", [t("requests.device." + (e.device || "unknown")),
                                       e.browser ? t("requests.browser." + e.browser) : "", e.referrer || ""]
    .filter(Boolean).join(" · "));
  requestCell(tr, "requests.language", e.language || "—");
  // "Campinas, Sao Paulo, BR" in the table, the region (state, province) when the GeoIP database knows it
  const place = placeText(e.city, e.region, e.country);
  requestCell(tr, "requests.location", e.city ? mapLink(place, place) : (place || "—"),
              "requests-place");
  requestCell(tr, "requests.ms", e.ms ?? "—", "num");
  requestCell(tr, "audit.tenant", e.organisation || t("users.operatorName"), "requests-org-col");
  return tr;
}

/* The map of the requests these filters select (ADR 0006, section 10; requests-map.js), drawn when its box is open */
async function loadRequestMap() {
  const box = $("#requests-map");
  if (!$("#requests-map-box").open) return;
  const status = el("p", "field-msg", t("requests.mapLoading"));
  box.replaceChildren(status);
  try {
    const data = await api("GET", "requests/places?" + requestsQuery().toString());
    await RequestsMap.render(box, data);
  } catch (e) {
    I18N.set(status, e.code || "requests.mapFailed", e.params);
    box.replaceChildren(status);
  }
}

async function loadRequests(event, more = false) {
  if (event) event.preventDefault();
  if (!more) loadRequestMap();
  const params = requestsQuery();
  if (more && requestsState.next) params.set("before", requestsState.next);
  if (!more) {
    $("#requests-body").replaceChildren();
    $("#requests-geo").hidden = true;
    I18N.set($("#requests-count"), "records.loading");
  }
  try {
    const data = await api("GET", "requests?" + params.toString());
    $("#requests-body").append(...data.events.map(requestRow));
    if (data.events.some(e => e.country)) $("#requests-geo").hidden = false;
    requestsState.next = data.next;
    $("#requests-more").hidden = !data.next;
    const shown = $("#requests-body").children.length;
    $("#requests-empty").hidden = shown > 0;
    I18N.set($("#requests-count"), data.next ? "requests.countMore" : "requests.count", { count: shown });
  } catch (e) {
    I18N.set($("#requests-count"), e.code, e.params);
  }
}

async function downloadRequests() {
  try {
    const res = await fetch(BASE + "api/requests.csv?" + requestsQuery().toString(), { credentials: "same-origin" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      I18N.set($("#requests-count"), body.code || "error.unexpected", body.params || { status: res.status });
      return;
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || "resolver-requests.csv";
    const a = el("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (e) {
    I18N.set($("#requests-count"), "error.network");
  }
}

async function loadApiCalls(event, more = false) {
  if (event) event.preventDefault();
  const params = new URLSearchParams();
  if ($("#requests-api-from").value) params.set("from", $("#requests-api-from").value);
  if ($("#requests-api-to").value) params.set("to", $("#requests-api-to").value);
  if (more && requestsState.apiNext) params.set("before", requestsState.apiNext);
  if (!more) { $("#requests-api-body").replaceChildren(); I18N.set($("#requests-api-count"), "records.loading"); }
  try {
    const data = await api("GET", "requests/api?" + params.toString());
    $("#requests-api-body").append(...data.calls.map(c => {
      const tr = document.createElement("tr");
      requestCell(tr, "audit.when", formatWhen(c.at));
      const key = document.createElement("span");
      if (c.key) {
        const id = document.createElement("code");
        id.textContent = c.key;
        key.append(c.keyName || "", c.keyName ? " " : "", id);
      } else {
        I18N.set(key, "requests.noKey");
      }
      requestCell(tr, "requests.key", key);
      requestCell(tr, "audit.tenant", c.organisation || t("users.operatorName"), "requests-org-col");
      requestCell(tr, "requests.operation", `${c.method} ${c.operation || ""}`, "code");
      requestCell(tr, "requests.status", c.status, "num");
      requestCell(tr, "requests.ms", c.ms ?? "—", "num");
      return tr;
    }));
    requestsState.apiNext = data.next;
    $("#requests-api-more").hidden = !data.next;
    const shown = $("#requests-api-body").children.length;
    $("#requests-api-empty").hidden = shown > 0;
    I18N.set($("#requests-api-count"), data.next ? "requests.countMore" : "requests.count", { count: shown });
  } catch (e) {
    I18N.set($("#requests-api-count"), e.code, e.params);
  }
}

/* How long requests are kept (ADR 0006, section 8): the installation's days, set by server administrators, and each
   organisation's, the same or fewer, set by its administrators; the space the log uses. */
async function loadRetention() {
  const box = $("#retention-status");
  box.hidden = true;
  try {
    requestsState.retention = await api("GET", "requests/retention");
    renderRetention();
  } catch (e) {
    box.hidden = false;
    box.className = "status is-error";
    I18N.set(box, e.code, e.params);
  }
}

function renderRetention() {
  const r = requestsState.retention;
  if (!r) return;
  $("#retention-off").hidden = r.enabled;
  $("#retention-global").hidden = !r.enabled;
  $("#retention-global-days").value = r.days;
  $("#retention-global-days").max = r.max;
  $("#retention-global-days").disabled = !r.canSetGlobal;
  $("#retention-global-save").hidden = !r.canSetGlobal;
  I18N.set($("#retention-default"), "requests.retentionDefault", { days: r.default });
  const space = $("#retention-space");
  space.hidden = !r.space;
  if (r.space) {
    if (r.space.bytes === null || r.space.bytes === undefined) {
      I18N.set(space, "requests.retentionSpaceUnknown", { events: nf(r.space.events) });
    } else {
      I18N.set(space, "requests.retentionSpace", { size: formatBytes(r.space.bytes), index: formatBytes(r.space.indexBytes),
                                                  events: nf(r.space.events) });
    }
  }
  // The most space the log may use (ADR 0006, section 9): server administrators only
  const limited = r.enabled && r.maxMegabytes !== null && r.maxMegabytes !== undefined;
  $("#retention-max").hidden = !limited;
  $("#retention-max-hint").hidden = !limited;
  if (limited) {
    const box = $("#retention-max-mb");
    box.value = r.maxBytes ? String(Math.round(r.maxBytes / 1048576)) : "";
    box.max = String(r.maxMegabytes);
    box.disabled = !r.canSetGlobal;
    $("#retention-max-save").hidden = !r.canSetGlobal;
  }
  const share = $("#retention-max-share");
  const used = r.space?.used;
  share.hidden = !limited || !r.maxBytes || used === null || used === undefined;
  if (!share.hidden) {
    const percent = Math.round(used / r.maxBytes * 1000) / 10;
    share.classList.toggle("is-warn", percent >= 80);
    I18N.set(share, "requests.spaceShare", { used: formatBytes(used), max: formatBytes(r.maxBytes), percent: nf(percent) });
  }
  $("#retention-orgs").hidden = !r.enabled || !r.organisations.length;
  $("#retention-orgs-body").replaceChildren(...r.organisations.map(o => {
    const tr = el("tr");
    tr.dataset.tenant = o.id;
    const days = el("input");
    days.type = "number"; days.min = "1"; days.max = String(r.days); days.inputMode = "numeric";
    days.className = "retention-days";
    days.value = o.logDays ?? "";
    days.placeholder = t("requests.retentionFollow", { days: r.days });
    days.disabled = !o.editable;
    days.setAttribute("aria-label", t("requests.retentionDaysOf", { name: o.name }));
    const daysCell = el("td");
    daysCell.dataset.label = t("requests.retentionDays");
    daysCell.append(days);
    const action = el("td");
    if (o.editable) {
      const save = el("button", "btn btn-ghost btn-small", t("users.save"));
      save.type = "button";
      save.addEventListener("click", () => saveRetention({ tenant: o.id, days: days.value.trim() === "" ? null : days.value.trim() }));
      action.append(save);
    }
    const name = el("td", "", o.name);
    name.dataset.label = t("audit.tenant");
    const events = el("td", "num", nf(o.space?.events ?? 0));
    events.dataset.label = t("requests.retentionEvents");
    const size = el("td", "num", formatBytes(o.space?.bytes));
    size.dataset.label = t("requests.retentionEstimate");
    tr.append(name, daysCell, events, size, action);
    return tr;
  }));
}

async function saveRetention(body) {
  const box = $("#retention-status");
  try {
    const answer = await api("PUT", "requests/retention", body);
    box.hidden = false;
    box.className = "status is-ok";
    if ("maxMegabytes" in body) {
      I18N.set(box, answer.maxBytes ? "requests.spaceSavedMax" : "requests.spaceSavedNone",
               { max: formatBytes(answer.maxBytes) });
    } else {
      I18N.set(box, "requests.retentionSavedDays", { days: answer.days });
    }
    await loadRetention();
    box.hidden = false;
    CONFIG.requestLog.days = requestsState.retention.scopeDays;
    I18N.set($("#requests-privacy"), "requests.privacy", { days: CONFIG.requestLog.days });
  } catch (e) {
    box.hidden = false;
    box.className = "status is-error";
    I18N.set(box, e.code, e.params);
  }
}

/* ------------------------------------------------------------------ domains (Documentation/adr/0009-tenant-domains.md)
   The organisation's own domains in the QR code: added, proved by a DNS TXT record, checked, given default prefixes,
   removed. A server administrator sees every domain and manages the operator's; support access is read only. */
const domainsState = { data: null };

function domainsStatus(kind, key, params) {
  const box = $("#domains-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

async function loadDomains() {
  try {
    const data = await api("GET", "domains");
    domainsState.data = data;
    renderDomains();
  } catch (e) {
    domainsStatus("error", e.code, e.params);
  }
}

function renderDomains() {
  const data = domainsState.data;
  if (!data) return;
  const who = CONFIG.support ? CONFIG.support.name : CONFIG.tenant ? CONFIG.tenant.name : t("users.operatorName");
  I18N.set($("#domains-scope"), data.every ? "domains.scopeEvery" : "domains.scope", { who });
  $("#domains-readonly").hidden = !data.readOnly;
  $("#domains-create").hidden = data.readOnly;
  // the server's task that gives verified domains their site and certificate (ADR 0009, section 7): server administrators
  const run = $("#domains-host-run");
  run.hidden = !data.hostRun;
  if (data.hostRun) {
    run.className = "field-msg" + (data.hostRun.late ? " is-error" : "");
    if (data.hostRun.late) {
      I18N.set(run, data.hostRun.at ? "domains.hostRunLate" : "domains.hostRunNever", { at: formatWhen(data.hostRun.at) });
    } else {
      I18N.set(run, "domains.hostRun", { at: formatWhen(data.hostRun.at) });
    }
  }
  $("#domains-list").replaceChildren(...data.domains.map(domainCard));
  $("#domains-empty").hidden = data.domains.length > 0;
  $("#domains-redirect-example").textContent =
    `# nginx (${t("domains.yourServer")})\nlocation ~ ^/gs1(/.*)$ {\n    return 307 https://${data.installation}$1$is_args$args;\n}\n\n` +
    `# Apache\nRedirectMatch 307 ^/gs1/(.*)$ https://${data.installation}/$1`;
}

function domainCard(d) {
  const editable = !domainsState.data.readOnly && !(domainsState.data.every && d.organisation);
  const card = el("article", "domain-card" + (d.verified ? " is-verified" : ""));
  card.dataset.domain = d.domain;
  const head = el("div", "domain-head");
  head.append(el("strong", "domain-name", d.domain + (d.stem || "")));
  head.append(el("span", "badge " + (d.verified ? "badge-created" : "badge-unchanged"),
                 t(d.verified ? "domains.verifiedBadge" : "domains.pendingBadge")));
  head.append(el("span", "badge badge-update", t("domains.mode." + d.mode)));
  if (d.certificate) {
    head.append(el("span", "badge domain-cert is-" + d.certificate.state, t("domains.cert." + d.certificate.state)));
  }
  if (domainsState.data.every) head.append(el("span", "muted", d.organisation || t("users.operatorName")));
  card.append(head);
  if (!d.verified) {
    const txt = el("div", "domain-txt");
    txt.append(el("p", "", t("domains.txtIntro")));
    const dl = el("dl", "overview-facts");
    dl.append(el("dt", "", t("domains.txtName")), el("dd", "code", d.txtName),
              el("dt", "", t("domains.txtValue")), el("dd", "code", d.txtValue));
    txt.append(dl);
    card.append(txt);
  } else {
    card.append(el("p", "field-msg", t("domains.seen", { verified: formatWhen(d.verifiedAt), seen: formatWhen(d.seenAt) })));
  }
  if (d.certificate) card.append(certificateLine(d.certificate));
  if (d.check) {
    const ok = d.check.ok;
    card.append(el("p", "field-msg " + (ok ? "is-ok" : "is-error"),
      t(ok ? "domains.checkOk" : d.check.problem, { domain: d.domain, detail: d.check.detail || "", url: d.check.url })
      + " · " + formatWhen(d.check.at)));
  }
  card.append(el("p", "field-msg", t("domains.defaultsNow", {
    prefixes: d.defaultFor.length ? d.defaultFor.join(", ") : t("domains.noDefaults") })));
  if (editable) {
    const form = el("form", "domain-edit");
    form.noValidate = true;
    const field = (labelKey, input) => { const l = el("label", "domain-field"); l.append(el("span", "", t(labelKey)), input); return l; };
    const prefixes = el("input"); prefixes.value = d.defaultFor.join(", "); prefixes.className = "domain-defaults";
    prefixes.placeholder = (domainsState.data.prefixes || []).join(", ");
    const stem = el("input"); stem.value = d.stem; stem.className = "domain-stem";
    const mode = el("select"); mode.className = "domain-mode";
    domainsState.data.modes.forEach(m => mode.append(i18nOption("domains.mode." + m, m)));
    mode.value = d.mode;
    form.append(field("domains.defaults", prefixes), field("domains.stem", stem), field("domains.mode", mode));
    const save = el("button", "btn btn-ghost", t("domains.save")); save.type = "submit";
    form.append(save);
    form.addEventListener("submit", e => { e.preventDefault(); domainCall("PUT", d, "",
      { defaultFor: prefixesFrom(prefixes.value), stem: stem.value, mode: mode.value }); });
    card.append(form);
    const actions = el("div", "user-actions");
    const button = (key, cls, fn) => { const b = el("button", "btn " + cls, t(key)); b.type = "button"; b.addEventListener("click", fn); actions.append(b); };
    if (!d.verified) button("domains.verify", "btn-primary", () => domainCall("POST", d, "/verify", {}));
    button("domains.check", "btn-ghost", () => domainCall("POST", d, "/check", {}));
    button("domains.remove", "btn-danger-ghost", async () => {
      if (await ask(t("domains.confirmRemove", { domain: d.domain }), { danger: true })) domainCall("DELETE", d, "");
    });
    card.append(actions);
  }
  return card;
}

/* What the server did for a verified domain pointing at it: pending until its task reports, then served (with the
   certificate's end) or failed (the reason and the next attempt). */
function certificateLine(c) {
  const p = el("p", "field-msg domain-cert-line" + (c.state === "served" ? " is-ok" : c.state === "failed" ? " is-error" : ""));
  if (c.state === "served") {
    p.textContent = c.until ? t("domains.certServedUntil", { until: formatWhen(c.until) }) : t("domains.certServed");
  } else if (c.state === "failed") {
    p.textContent = t("domains.certFailed", { reason: t("domains.certError." + (c.error || "certificate")),
                                              next: formatWhen(c.nextAttemptAt), attempts: c.attempts });
  } else {
    p.textContent = t("domains.certPending");
  }
  return p;
}

async function domainCall(method, d, suffix, body) {
  try {
    const result = await api(method, "domains/" + encodeURIComponent(d.domain) + suffix, body);
    domainsStatus(result.code && result.code !== "domains.checkOk" && suffix === "/check" ? "error" : "ok", result.code, result.params);
    await refreshDomainConfig();
    loadDomains();
  } catch (e) {
    domainsStatus("error", e.code, e.params);
  }
}

async function createDomain(event) {
  event.preventDefault();
  try {
    const result = await api("POST", "domains", { domain: $("#new-domain").value.trim(),
      stem: $("#new-domain-stem").value.trim(), mode: $("#new-domain-mode").value });
    domainsStatus("ok", result.code, result.params);
    $("#new-domain").value = ""; $("#new-domain-stem").value = "";
    loadDomains();
  } catch (e) {
    domainsStatus("error", e.code, e.params);
  }
}

/* A domain verified or given defaults changes what the label panel offers. */
async function refreshDomainConfig() {
  try {
    const fresh = await api("GET", "config");
    CONFIG.domains = fresh.domains;
    fillDomainOption();
  } catch { /* the next page load will have it */ }
}

/* ------------------------------------------------------------------ single sign-on (Documentation/adr/0012-single-sign-on.md)
   The organisation's OpenID Connect provider: issuer, client ID and secret (write-only), e-mail domains, on or off,
   password sign-in off. Administrators see their organisation's; a server administrator every one and the operator's;
   support access is read only. */
const ssoState = { data: null, extra: [] };

function ssoStatus(kind, key, params) {
  const box = $("#sso-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

async function loadSso() {
  try {
    ssoState.data = await api("GET", "sso");
    renderSso();
  } catch (e) {
    ssoStatus("error", e.code, e.params);
  }
}

function ssoScopeName(scope) {
  if (scope === "operator") return t("sso.operator");
  const org = (ssoState.data.organisations || []).find(o => o.id === scope);
  return org ? org.name : (CONFIG.tenant && CONFIG.tenant.id === scope ? CONFIG.tenant.name
                           : CONFIG.support && CONFIG.support.id === scope ? CONFIG.support.name : scope);
}

function renderSso() {
  const data = ssoState.data;
  if (!data) return;
  I18N.set($("#sso-scope"), data.every ? "sso.scopeEvery" : "sso.scope", { who: ssoScopeName(data.scope) });
  $("#sso-readonly").hidden = !data.readOnly;
  $("#sso-callback").textContent = data.callback;
  const configs = [...data.configs];
  const scopes = new Set(configs.map(c => c.scope));
  if (!data.every && !scopes.has(data.scope) && !data.readOnly) configs.push({ scope: data.scope, blank: true });
  ssoState.extra.filter(s => !scopes.has(s)).forEach(s => configs.push({ scope: s, blank: true }));
  $("#sso-list").replaceChildren(...configs.map(ssoCard));
  $("#sso-empty").hidden = configs.length > 0;
  $("#sso-add").hidden = !data.every;
  if (data.every) {
    const taken = new Set(configs.map(c => c.scope));
    const choices = [{ id: "operator", name: t("sso.operator") }, ...data.organisations].filter(o => !taken.has(o.id));
    $("#sso-add-scope").replaceChildren(...choices.map(o => new Option(o.name, o.id)));
    $("#sso-add").hidden = choices.length === 0;
  }
}

function ssoCard(c) {
  const editable = !ssoState.data.readOnly;
  const card = el("article", "domain-card" + (c.enabled ? " is-verified" : ""));
  card.dataset.scope = c.scope;
  const head = el("div", "domain-head");
  head.append(el("strong", "domain-name", ssoScopeName(c.scope)));
  if (!c.blank) {
    head.append(el("span", "badge " + (c.enabled ? "badge-created" : "badge-unchanged"), t(c.enabled ? "sso.on" : "sso.off")));
    head.append(el("span", "badge badge-update", t(c.secretSet ? "sso.secretSet" : "sso.secretMissing")));
    if (c.passwordOff) head.append(el("span", "badge badge-unchanged", t("sso.passwordOffBadge")));
  }
  card.append(head);
  if (c.lastLogin) card.append(el("p", "field-msg", t("sso.lastLogin", { when: formatWhen(c.lastLogin) })));
  if (c.lastError) card.append(el("p", "field-msg is-error", t("sso.lastError", {
    message: t(c.lastError.code) + (c.lastError.detail ? ` (${c.lastError.detail})` : ""), when: formatWhen(c.lastError.at) })));
  const form = el("form", "sso-form");
  form.noValidate = true;
  const field = (labelKey, input, hintKey, params) => {
    const l = el("label", "domain-field");
    l.append(el("span", "", t(labelKey)), input);
    if (hintKey) l.append(el("small", "muted", t(hintKey, params)));
    return l;
  };
  const input = (cls, value, type = "text") => { const i = el("input"); i.className = cls; i.type = type; i.value = value || "";
                                                 i.disabled = !editable; i.autocomplete = "off"; i.spellcheck = false; return i; };
  const issuer = input("sso-issuer", c.issuer, "url");
  const clientId = input("sso-client-id", c.clientId);
  const secret = input("sso-secret", "", "password");
  secret.autocomplete = "new-password";
  secret.placeholder = c.secretSet ? t("sso.secretKeep") : "";
  const domainsInput = input("sso-domains", (c.domains || []).join(", "));
  const check = (cls, checked, key) => { const l = el("label", "choice"); const b = el("input"); b.type = "checkbox";
                                         b.className = cls; b.checked = Boolean(checked); b.disabled = !editable;
                                         l.append(b, " ", el("span", "", t(key))); return l; };
  form.append(field("sso.issuer", issuer, "sso.issuerHint", { issuer: c.issuer || "https://…" }),
              field("sso.clientId", clientId), field("sso.clientSecret", secret),
              field("sso.domains", domainsInput, "sso.domainsHint"),
              check("sso-enabled", c.enabled, "sso.enabled"), check("sso-password-off", c.passwordOff, "sso.passwordOff"));
  card.append(form);
  card.append(el("p", "field-msg", t("sso.passwordOffHint")));
  const actions = el("div", "user-actions");
  const button = (key, cls, fn) => { const b = el("button", "btn " + cls, t(key)); b.type = "button"; b.addEventListener("click", fn); actions.append(b); };
  if (editable) {
    button("sso.save", "btn-primary", () => ssoCall("PUT", c.scope, "", {
      issuer: issuer.value.trim(), clientId: clientId.value.trim(), clientSecret: secret.value, domains: domainsInput.value,
      enabled: $(".sso-enabled", form).checked, passwordOff: $(".sso-password-off", form).checked }));
  }
  if (!c.blank) {
    button("sso.test", "btn-ghost", () => ssoCall("POST", c.scope, "/test", {}));
    if (editable) button("sso.remove", "btn-danger-ghost", async () => {
      if (await ask(t("sso.confirmRemove"), { danger: true })) ssoCall("DELETE", c.scope, "");
    });
  }
  card.append(actions);
  return card;
}

async function ssoCall(method, scope, suffix, body) {
  try {
    const result = await api(method, "sso/" + encodeURIComponent(scope) + suffix, body);
    const failed = suffix === "/test" && result.result && !result.result.ok;
    ssoStatus(failed ? "error" : "ok", result.code,
              failed ? { ...result.params, detail: result.result.detail } : result.params);
    if (suffix !== "/test") {
      ssoState.extra = ssoState.extra.filter(s => s !== scope);
      loadSso();
    }
  } catch (e) {
    ssoStatus("error", e.code, e.params);
  }
}

/* ------------------------------------------------------------------ the item's page (Documentation/adr/0011-item-page.md)
   Brands per prefix: the name, logo and colours the resolver's page of an item's links shows, and whether it offers
   Verified by GS1. An organisation's administrators brand prefixes inside theirs; a server administrator the
   operator's and the installation's default ("*"); support access is read only. */
const brandingState = { data: null };

function brandingStatus(kind, key, params) {
  const box = $("#branding-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

async function loadBranding() {
  try {
    brandingState.data = await api("GET", "branding");
    renderBranding();
  } catch (e) {
    brandingStatus("error", e.code, e.params);
  }
}

/* Black or white text on a colour, whichever reads better (as the resolver's page chooses). */
function textOn(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? "#000000" : "#FFFFFF";
}

function renderBranding() {
  const data = brandingState.data;
  if (!data) return;
  const who = CONFIG.support ? CONFIG.support.name : CONFIG.tenant ? CONFIG.tenant.name : t("users.operatorName");
  I18N.set($("#branding-scope"), "branding.scope", { who });
  $("#branding-readonly").hidden = !data.readOnly;
  $("#branding-form").hidden = data.readOnly;
  $("#branding-verified-off").hidden = data.verifiedOn;
  I18N.set($("#brand-logo-hint"), "branding.logoHint", { max: data.maxLogoKB });
  const options = [...data.prefixes, ...(data.installationDefault ? ["*"] : [])];
  $("#brand-prefixes").replaceChildren(...options.map(p => new Option(p === "*" ? t("branding.installation") : p, p)));
  $("#branding-list").replaceChildren(...data.brands.map(brandCard));
  $("#branding-empty").hidden = data.brands.length > 0;
}

function brandCard(b) {
  const card = el("article", "domain-card is-verified");
  card.dataset.prefix = b.prefix;
  const head = el("div", "domain-head");
  head.append(el("strong", "domain-name", b.prefix === "*" ? t("branding.installation") : b.prefix));
  head.append(el("span", "badge " + (b.verified ? "badge-created" : "badge-unchanged"),
                 t(b.verified ? "branding.verifiedOn" : "branding.verifiedOffBadge")));
  card.append(head);
  const preview = el("div", "brand-preview");
  preview.style.background = b.colour;
  preview.style.color = textOn(b.colour);
  if (b.logo) {
    const img = el("img");
    img.src = BASE + b.logo.url;
    img.alt = t("branding.logoAlt", { name: b.name || b.prefix });
    preview.append(img);
  }
  preview.append(el("span", "", b.name || t("branding.noName")));
  const sample = el("span", "brand-button", t("branding.sampleButton"));
  sample.style.background = b.accent;
  sample.style.color = textOn(b.accent);
  preview.append(sample);
  card.append(preview);
  card.append(el("p", "field-msg", t("branding.updated", { when: formatWhen(b.updated), who: b.updatedBy || "" })
    + (b.logo ? " · " + t("branding.logoSize", { width: b.logo.width, height: b.logo.height, kb: Math.ceil(b.logo.bytes / 1024) }) : "")));
  if (!brandingState.data.readOnly) {
    const actions = el("div", "user-actions");
    const button = (key, cls, fn) => { const x = el("button", "btn " + cls, t(key)); x.type = "button"; x.addEventListener("click", fn); actions.append(x); };
    button("branding.edit", "btn-ghost", () => {
      $("#brand-prefix").value = b.prefix;
      $("#brand-name").value = b.name;
      $("#brand-colour").value = b.colour.toLowerCase();
      $("#brand-accent").value = b.accent.toLowerCase();
      $("#brand-verified").checked = b.verified;
      $("#brand-logo").value = "";
      $("#brand-name").focus();
    });
    if (b.logo) button("branding.removeLogo", "btn-ghost", () => brandingCall("PUT", b.prefix, { logo: "" }));
    button("branding.remove", "btn-danger-ghost", async () => {
      if (await ask(t("branding.confirmRemove", { prefix: b.prefix }), { danger: true })) brandingCall("DELETE", b.prefix);
    });
    card.append(actions);
  }
  return card;
}

async function brandingCall(method, prefix, body) {
  try {
    const result = await api(method, "branding/" + encodeURIComponent(prefix), body);
    brandingStatus("ok", result.code, result.params);
    loadBranding();
    return true;
  } catch (e) {
    brandingStatus("error", e.code, e.params);
    return false;
  }
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function saveBranding(event) {
  event.preventDefault();
  const body = { name: $("#brand-name").value.trim(), colour: $("#brand-colour").value,
                 accent: $("#brand-accent").value, verified: $("#brand-verified").checked };
  const file = $("#brand-logo").files[0];
  if (file) {
    if (file.size > brandingState.data.maxLogoKB * 1024) {
      brandingStatus("error", "branding.logoTooLarge", { max: brandingState.data.maxLogoKB });
      return;
    }
    body.logo = await readFile(file);
  }
  const prefix = $("#brand-prefix").value.trim() || "-";
  if (await brandingCall("PUT", prefix, body)) {
    $("#branding-form").reset();
  }
}

/* ------------------------------------------------------------------ overview (Documentation/adr/0007-overview-indicators.md)
   The page opened after sign-in: indicators of the scope for the last 7, 30 or 90 days, each compared with the period
   before it. Everything is computed by the server (GET overview); this part only draws it. */
const overviewState = { data: null, loading: 0 };
const nf = n => new Intl.NumberFormat(I18N.locale).format(n);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/* A change against the previous period, as text: "+12 % vs. the previous 30 days", "new", or "no change". */
function changeText(value, previous, days) {
  if (previous === undefined || previous === null) return "";
  if (value === previous) return t("overview.same", { days });
  if (!previous) return t("overview.new", { days });
  const pct = Math.round(((value - previous) / previous) * 100);
  return t("overview.change", { change: (pct > 0 ? "+" : "") + nf(pct), days });
}

/* A tile: label, figure, and the change (green when it moves the right way: "up" or "down" is better). */
function tile(labelKey, value, opts = {}) {
  const box = el("div", "overview-tile" + (opts.warn ? " is-warn" : ""));
  box.append(el("span", "tile-label", t(labelKey, opts.params || {})));
  box.append(el("strong", "tile-value", value === null || value === undefined ? "—"
                                          : opts.text ? value : nf(value) + (opts.unit ? " " + opts.unit : "")));
  const change = opts.previous !== undefined ? changeText(value, opts.previous, overviewState.data.period.days) : opts.note;
  if (change) {
    const small = el("small", "tile-change", change);
    if (opts.previous !== undefined && opts.better && value !== opts.previous) {
      const up = value > opts.previous;
      small.classList.add((opts.better === "up") === up ? "is-good" : "is-bad");
    }
    box.append(small);
  }
  if (opts.id) box.id = opts.id;
  return box;
}

function share(part, whole) {
  return whole ? Math.round((part / whole) * 1000) / 10 : 0;
}

/* A small table of counts with their share, for devices, forms, languages, link types and key types. */
function shareTable(captionKey, pairs, labelOf) {
  const total = pairs.reduce((n, [, v]) => n + v, 0);
  const table = el("table", "records-table overview-table overview-share");
  const caption = captionKey ? el("caption", "", t(captionKey)) : null;
  const body = el("tbody");
  pairs.forEach(([name, n]) => {
    const tr = el("tr");
    const label = el("td", "", labelOf ? labelOf(name) : name);
    const count = el("td", "num", nf(n));
    const bar = el("td", "overview-share-bar");
    const fill = el("span");
    fill.style.width = `${share(n, total)}%`;
    bar.append(fill, el("small", "", `${nf(share(n, total))} %`));
    tr.append(label, count, bar);
    body.append(tr);
  });
  if (caption) table.append(caption);
  table.append(body);
  return pairs.length ? table : el("p", "records-empty", captionKey ? t(captionKey) + ": —" : "—");
}

function codeButton(code, labelKey) {
  const button = el("button", "btn btn-ghost btn-small", t(labelKey));
  button.type = "button";
  button.addEventListener("click", () => openFromList({ key: code.key, value: code.value, qualifiers: [] }));
  return button;
}

async function loadOverview() {
  const days = $("#overview-days").value || "30";
  const ticket = ++overviewState.loading;
  I18N.set($("#overview-status"), "records.loading");
  try {
    const tenant = CONFIG?.serverAdmin && !CONFIG.support ? $("#overview-tenant").value : "";
    const data = await api("GET", "overview?days=" + encodeURIComponent(days)
                                  + (tenant ? "&tenant=" + encodeURIComponent(tenant) : ""));
    if (ticket !== overviewState.loading) return;          // a newer period was chosen meanwhile
    overviewState.data = data;
    $("#overview-status").textContent = "";
    renderOverview();
  } catch (e) {
    if (ticket === overviewState.loading) I18N.set($("#overview-status"), e.code, e.params);
  }
}

function renderOverview() {
  const d = overviewState.data;
  if (!d) return;
  const days = d.period.days;
  const fmt = new Intl.DateTimeFormat(I18N.locale, { day: "2-digit", month: "2-digit", year: "numeric" });
  const day = iso => fmt.format(new Date(iso + "T12:00:00"));
  const chosen = d.scoped ? (d.organisation ? (organisations.find(o => o.id === d.organisation)?.name || d.organisation)
                                            : t("users.operatorName")) : null;
  const who = d.whole ? t("overview.scopeWhole") : chosen
    || (CONFIG.support ? CONFIG.support.name : CONFIG.tenant ? CONFIG.tenant.name : t("users.operatorName"));
  $("#overview-scope").textContent = t("overview.scope", { who, from: day(d.period.from), to: day(d.period.to),
                                                            zone: d.period.timeZone });
  $("#overview-off").hidden = d.logDays > 0;

  // Usage
  const u = d.usage;
  $("#overview-usage-tiles").replaceChildren(
    tile("overview.scans", u.scans, { previous: u.previous.scans, better: "up", id: "overview-tile-scans" }),
    tile("overview.automated", u.automated, { previous: u.previous.automated }),
    tile("overview.perDayAvg", new Intl.NumberFormat(I18N.locale, { maximumFractionDigits: 1 }).format(u.scans / days),
         { text: true }),
    tile("overview.codesScanned", u.topCodes.length >= 10 ? t("overview.tenOrMore") : u.topCodes.length,
         { text: u.topCodes.length >= 10 }),
    // The item's page (ADR 0011): shown once it has been used in either period
    ...(u.pageViews || u.clicks || u.previous.pageViews || u.previous.clicks ? [
      tile("overview.pageViews", u.pageViews, { previous: u.previous.pageViews, id: "overview-tile-pages" }),
      tile("overview.clicks", u.clicks, { previous: u.previous.clicks, id: "overview-tile-clicks" })] : []));
  const top = Math.max(1, ...u.perDay.map(x => x.scans));
  const chart = $("#overview-chart");
  chart.setAttribute("aria-label", t("overview.chartLabel", { scans: nf(u.scans), days }));
  chart.replaceChildren(...u.perDay.map(x => {
    const bar = el("div", "requests-bar");
    const ok = el("span", "bar-ok"), lost = el("span", "bar-missing");
    ok.style.height = `${((x.scans - x.notFound) / top) * 100}%`;
    lost.style.height = `${(x.notFound / top) * 100}%`;
    bar.append(lost, ok);
    bar.title = t("requests.dayTitle", { day: day(x.day), total: x.scans, missing: x.notFound });
    bar.dataset.day = x.day;
    return bar;
  }));
  $("#overview-top-body").replaceChildren(...u.topCodes.map(c => {
    const tr = el("tr");
    const code = el("td", "code");
    const link = el("a", "", c.anchor);
    link.href = "#";
    link.addEventListener("click", e => { e.preventDefault(); openFromList({ key: c.key, value: c.value, qualifiers: [] }); });
    code.append(link);
    tr.append(code, el("td", "num", nf(c.scans)), el("td", "num", nf(c.notFound)));
    return tr;
  }));
  $("#overview-top-empty").hidden = u.topCodes.length > 0;
  const devices = Object.entries(u.device).sort((a, b) => b[1] - a[1]);
  const forms = Object.entries(u.form).sort((a, b) => b[1] - a[1]);
  $("#overview-shares").replaceChildren(
    shareTable("overview.byDevice", devices, name => t("requests.device." + name)),
    shareTable("overview.byForm", forms, name => t("overview.form." + name)),
    shareTable("overview.byLanguage", u.language),
    shareTable("overview.byLinkType", u.linkType),
    shareTable("overview.byBrowser", u.browser || [], name => t("requests.browser." + name)),
    shareTable("overview.byCountry", u.country || []),
    shareTable("overview.byPlace", u.place || [], placeFromKey));

  // Resolution quality (every request, automated ones included)
  const q = d.quality;
  const answeredPct = q.requests ? share(q.answered, q.requests) : null;
  $("#overview-quality-tiles").replaceChildren(
    tile("overview.answeredShare", answeredPct === null ? null : `${nf(answeredPct)} %`, { text: true,
         note: t("overview.ofRequests", { n: nf(q.requests) }) }),
    tile("overview.q.unknown", q.unknown, { previous: q.previous.unknown, better: "down", warn: q.unknown > 0,
         id: "overview-tile-unknown" }),
    tile("overview.q.noLink", q.noLink, { previous: q.previous.noLink, better: "down", warn: q.noLink > 0 }),
    tile("overview.q.invalid", q.invalid, { previous: q.previous.invalid, better: "down" }),
    tile("overview.q.error", q.error, { previous: q.previous.error, better: "down", warn: q.error > 0 }),
    // sent to another resolver (ADR 0018): shown when there were any
    ...(q.forwarded || q.previous.forwarded ? [tile("overview.q.forwarded", q.forwarded, { previous: q.previous.forwarded })] : []),
    ...(q.fallback || q.previous.fallback ? [tile("overview.q.fallback", q.fallback, { previous: q.previous.fallback })] : []),
    tile("overview.avgMs", q.avgMs, { unit: "ms", note: q.p95Max !== null && q.p95Max !== undefined
         ? t("overview.p95Note", { ms: nf(q.p95Max) }) : "" }));
  const codeRows = (list, body, empty, actionKey) => {
    body.replaceChildren(...list.map(c => {
      const tr = el("tr");
      const code = el("td", "code", c.anchor);
      if (c.registered) code.append(" ", el("span", "badge badge-unchanged", t("overview.keyHasRecords")));
      const action = el("td", "");
      action.append(codeButton(c, c.registered === false ? actionKey : "overview.open"));
      tr.append(code, el("td", "num", nf(c.requests)), action);
      return tr;
    }));
    empty.hidden = list.length > 0;
  };
  codeRows(q.unknownCodes, $("#overview-unknown-body"), $("#overview-unknown-empty"), "overview.register");
  codeRows(q.noLinkCodes, $("#overview-nolink-body"), $("#overview-nolink-empty"), "overview.open");

  // Records
  const r = d.records;
  $("#overview-records-off").hidden = r.available !== false;
  const check = r.lastCheck;
  $("#overview-records-tiles").replaceChildren(...(r.available ? [
    tile("overview.r.records", r.records, { note: t("overview.r.keysNote", { n: nf(r.keys) }) }),
    tile("overview.r.noKeyRecord", r.noKeyRecord, { warn: r.noKeyRecord > 0 }),
    tile("overview.r.breaksRules", r.breaksRules, { warn: r.breaksRules > 0 }),
    tile("overview.r.noDescription", r.noDescription),
    tile("overview.r.notScanned", r.notScanned, { note: t("overview.r.notScannedNote", { days }) }),
    tile("overview.r.linkProblems", check ? r.linkProblems : null, { warn: r.linkProblems > 0,
         note: check ? t("overview.checkedAt", { when: formatWhen(check.at) }) : t("overview.neverChecked") }),
  ] : []));
  // From operation, what matters to every scope (ADR 0013): the last check of every link, how long requests are kept,
  // the scope's active alerts
  const alerts = r.alerts || [];
  const recordFacts = [
    ["overview.lastCheck", r.lastCheckAt ? formatWhen(r.lastCheckAt) : t("overview.neverChecked")],
    ["overview.op.logDays", d.logDays ? t("overview.op.logDaysValue", { days: d.logDays }) : t("overview.off")],
    ["overview.op.alerts", alerts.length ? alerts.map(a => overviewAlert(a)
      + " · " + t("overview.alertSince", { when: formatWhen(a.since) })).join("\n") : t("overview.op.noAlerts")]];
  $("#overview-records-facts").replaceChildren(...recordFacts.flatMap(([k, v]) =>
    [el("dt", "", t(k)), el("dd", k === "overview.op.alerts" && alerts.length ? "is-alert" : "", v)]));
  $("#overview-bykey").replaceChildren(r.available
    ? shareTable(null, Object.entries(r.byKey).sort((a, b) => b[1] - a[1]), ai => keyName(ai)) : "");
  $("#overview-quiet").replaceChildren(...(r.notScannedSample || []).map(a => el("li", "code", a)));
  $("#overview-quiet-empty").hidden = !r.available || (r.notScannedSample || []).length > 0;

  // Operation
  // Operation: the installation's, server administrators only (ADR 0013)
  const op = d.operation || {};
  $("#overview-operation-group").hidden = !d.operation;
  const facts = [];
  if ("worker" in op) facts.push(["overview.op.worker", op.worker ? t("overview.op.workers", { n: op.worker }) : t("overview.op.noWorker")]);
  if ("mail" in op) facts.push(["overview.op.mail", t(op.mail === "on" ? "overview.on" : "overview.off")]);
  if ("countedUntil" in op) facts.push(["overview.op.countedUntil", op.countedUntil ? day(op.countedUntil) : "—"]);
  // Monitoring (Documentation/adr/0008-monitoring-and-alerts.md): each check's state for server administrators
  const checkText = c => {
    if (!c) return t("overview.state.unknown");
    const d = c.detail || {};
    if (c.kind === "logspace" && d.reason === "noLimit") return t("overview.check.noLimit");
    const extra = c.kind === "backup" && d.at ? t("overview.check.backupAt", { when: formatWhen(d.at) })
      : c.kind === "certificate" && d.expires ? t("overview.check.certExpires", { when: formatWhen(d.expires), days: d.days })
      : c.kind === "logspace" && d.percent !== undefined
        ? t("overview.check.spaceUse", { percent: nf(d.percent), max: formatBytes(d.max) })
      : "";
    return t("overview.state." + (c.state || "unknown")) + (extra ? " · " + extra : "");
  };
  if (op.checks) ["resolver", "backup", "certificate", "logspace"].forEach(name => facts.push(["overview.check." + name, checkText(op.checks[name])]));
  if (d.operation) facts.push(["overview.op.alerts", (op.alerts || []).length
    ? op.alerts.map(a => overviewAlert(a) + " · " +
                         t("overview.alertSince", { when: formatWhen(a.since) })).join("\n")
    : t("overview.op.noAlerts")]);
  $("#overview-operation").replaceChildren(...facts.flatMap(([k, v]) => {
    const dd = el("dd", k === "overview.op.alerts" && (op.alerts || []).length ? "is-alert" : "", v);
    return [el("dt", "", t(k)), dd];
  }));

  // Forwarding: the installation's, server administrators (ADR 0018)
  const fw = d.forwarding;
  $("#overview-forwarding-group").hidden = !fw;
  if (fw) {
    $("#overview-forwarding-tiles").replaceChildren(
      tile("overview.f.fallback", t(fw.fallback.enabled ? "overview.on" : "overview.off"), { text: true,
           note: fw.fallback.enabled ? fw.fallback.url : "" }),
      tile("overview.f.fallbackRequests", fw.fallback.requests, { previous: fw.fallback.previous }),
      tile("overview.f.rulesActive", t("overview.f.rulesActiveValue", { active: fw.rules.active, total: fw.rules.total }),
           { text: true }),
      tile("overview.f.rulesRequests", fw.rules.requests, { previous: fw.rules.previous }));
    $("#overview-fallback-body").replaceChildren(...fw.fallback.topCodes.map(c => {
      const tr = el("tr");
      tr.append(el("td", "code", c.anchor), el("td", "num", nf(c.requests)));
      return tr;
    }));
    $("#overview-fallback-empty").hidden = fw.fallback.topCodes.length > 0;
    $("#overview-byrule-body").replaceChildren(...fw.rules.byRule.map(r => {
      const tr = el("tr", r.enabled ? "" : "is-off");
      tr.append(el("td", "code", r.prefix + (r.enabled ? "" : ` (${t("overview.off")})`)), el("td", "code", r.target),
                el("td", "num", nf(r.requests)));
      return tr;
    }));
    $("#overview-byrule-empty").hidden = fw.rules.byRule.length > 0;
  }

  // Governance (administrators)
  const gov = d.governance;
  $("#overview-governance").hidden = !gov;
  if (gov) {
    const changes = Object.values(gov.changes).reduce((n, v) => n + v, 0);
    $("#overview-governance-tiles").replaceChildren(
      tile("overview.g.changes", changes, { note: ["create", "update", "delete", "import"].filter(a => gov.changes[a])
           .map(a => t("overview.g.change." + a) + ": " + nf(gov.changes[a])).join(" · ") }),
      tile("overview.g.signIns", gov.signIns),
      tile("overview.g.signInsRefused", gov.signInsRefused, { warn: gov.signInsRefused > 0 }),
      tile("overview.g.exports", gov.exports),
      tile("overview.g.keysActive", gov.apiKeys.active, { note: gov.apiKeys.expiring
           ? t("overview.g.keysExpiringNote", { n: gov.apiKeys.expiring }) : "" , warn: gov.apiKeys.expiring > 0 }),
      tile("overview.g.apiCalls", gov.apiCalls.calls, { note: t("overview.g.apiRefusedNote", { n: nf(gov.apiCalls.refused) }) }));
    $("#overview-users-body").replaceChildren(...gov.byUser.map(([user, n]) => {
      const tr = el("tr");
      tr.append(el("td", "", user.startsWith("api:") ? t("overview.g.apiUser", { key: user.slice(4) }) : user),
                el("td", "num", nf(n)));
      return tr;
    }));
    $("#overview-users-empty").hidden = gov.byUser.length > 0;
    $("#overview-accounts").replaceChildren(shareTable(null,
      Object.entries(gov.users).sort((a, b) => b[1] - a[1]), role => t("overview.g.users." + role)));
  }
}

function keyName(ai) {
  return I18N.has(`key.${ai}.name`) ? t(`key.${ai}.name`) : `(${ai})`;
}

/* The labels of the export, in the user's language: every overview.* message and the names used in its lists. */
function overviewLabels() {
  const labels = {};
  for (const key of I18N.keys()) {
    if (key.startsWith("overview.") || key.startsWith("requests.device.") || key.startsWith("requests.browser.")) labels[key] = t(key, { days: overviewState.data?.period.days ?? 30 });
  }
  return labels;
}

async function exportOverview(format) {
  const days = $("#overview-days").value || "30";
  try {
    const res = await fetch(BASE + "api/overview/export", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format, days: Number(days), labels: overviewLabels(),
                             tenant: CONFIG?.serverAdmin && !CONFIG.support ? $("#overview-tenant").value : "" }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      I18N.set($("#overview-status"), body.code || "error.unexpected", body.params || { status: res.status });
      return;
    }
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `overview.${format}`;
    const a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (e) {
    I18N.set($("#overview-status"), "error.unexpected", { status: e.message });
  }
}

/* ------------------------------------------------------------------ record list: loading, filters, code search */
async function loadRecords() {
  I18N.set($("#records-count"), "records.loading");
  $("#records-body").replaceChildren();
  $("#records-empty").hidden = true;
  try {
    const data = await api("GET", "records");
    records.all = data.records || [];
    records.loaded = true;
    fillFilters();
    try { showLinkCheck(await api("GET", "links/last")); } catch { /* optional */ }
    filtersFromAddress();
    renderRecords();
    $("#records-search").focus();
  } catch (e) {
    I18N.set($("#records-count"), e.code, e.params);
  }
}

function fillUserFilter() {
  const select = $("#records-user");
  const current = select.value;
  const names = [...new Set(records.all.map(r => r.updatedBy).filter(Boolean))].sort();
  const any = new Option("", "");
  any.dataset.i18n = "records.anyone";
  any.textContent = t("records.anyone");
  select.replaceChildren(any, ...names.map(n => new Option(n, n)));
  select.value = names.includes(current) ? current : "";
}

/* Filters by primary key type (URI Syntax 4.3) and key qualifier (4.4). Each lists only what the
   records contain, with how many records the option selects; the qualifier filter follows the key type. */
/* Records that need attention (section 2.5.9): qualified records of a key without a record of its own, and
   serial numbers registered with their batch or variant (made before rule 2). The alert offers the first. */
function fillStateFilter() {
  const select = $("#records-state");
  const previous = select.value;
  const nokey = records.all.filter(r => r.noKeyRecord).length;
  const rules = records.all.filter(r => r.breaksRules).length;
  select.replaceChildren(new Option(t("records.state.any"), ""),
    ...(nokey ? [filterOption("nokey", t("records.state.nokey"), nokey)] : []),
    ...(rules ? [filterOption("rules", t("records.state.rules"), rules)] : []));
  keepChoice(select, previous);
  $("#records-alert").hidden = !nokey;
  if (nokey) I18N.set($("#records-alert-text"), nokey === 1 ? "records.alert.one" : "records.alert.many", { count: nokey });
  $("#records-rules-alert").hidden = !rules;
  if (rules) I18N.set($("#records-rules-text"), "records.rules.alert", { count: rules });
}

/* Serial numbers registered with their batch or variant: registered again as the serial number alone, the batch and
   variant kept as information (rule 2 of section 2.5.9). One record (from its row) or every one. */
async function fixSerials(body) {
  try {
    const result = await api("POST", "records/fix-serials", body);
    await loadRecords();
    I18N.set($("#records-count"), result.code, result.params);
  } catch (e) {
    I18N.set($("#records-count"), e.code, e.params);
  }
}

/* The list's filters in the address (#records?text=…&key=01&qualifier=…&user=…&state=…&problems=1), so that a
   filtered list can be bookmarked or sent to a colleague. */
const FILTER_FIELDS = { text: "#records-search", key: "#records-key", qualifier: "#records-qualifier",
                        user: "#records-user", state: "#records-state" };

function filtersFromAddress() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (![...params.keys()].length) return;
  const set = (name, value) => {
    const field = $(FILTER_FIELDS[name]);
    if (field.tagName === "SELECT" && ![...field.options].some(o => o.value === value)) return;
    field.value = value;
  };
  set("text", params.get("text") || "");
  set("key", params.get("key") || "");
  fillQualifierFilter();                                 // the qualifiers offered follow the key type
  for (const name of ["qualifier", "user", "state"]) set(name, params.get(name) || "");
  $("#records-problems").checked = params.get("problems") === "1" && !$("#records-problems-wrap").hidden;
}

function filtersToAddress() {
  if (!isRecordsView()) return;
  const params = new URLSearchParams();
  for (const [name, selector] of Object.entries(FILTER_FIELDS)) {
    const value = $(selector).value.trim();
    if (value) params.set(name, value);
  }
  if ($("#records-problems").checked) params.set("problems", "1");
  const query = params.toString();
  const wanted = "#records" + (query ? "?" + query : "");
  if (location.hash !== wanted) history.replaceState(null, "", location.pathname + location.search + wanted);
}

function fillFilters() {
  fillKeyFilter();
  fillQualifierFilter();
  fillUserFilter();
  fillStateFilter();
}

function filterOption(value, label, count) {
  return new Option(t("records.filter.option", { label, count }), value);
}

function keepChoice(select, previous) {
  select.value = [...select.options].some(o => o.value === previous) ? previous : "";
}

function fillKeyFilter() {
  const select = $("#records-key");
  const previous = select.value;
  const counts = {};
  records.all.forEach(r => { counts[r.key] = (counts[r.key] || 0) + 1; });
  const order = (CONFIG?.keys || []).map(k => k.code);   // the order of the editor's key list
  const codes = Object.keys(counts).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  select.replaceChildren(new Option(t("records.keyType.any"), ""),
    ...codes.map(code => filterOption(code, t(`key.${code}.name`), counts[code])));
  keepChoice(select, previous);
}

function fillQualifierFilter() {
  const select = $("#records-qualifier");
  const previous = select.value;
  const key = $("#records-key").value;
  const counts = {};
  const add = value => { counts[value] = (counts[value] || 0) + 1; };
  records.all.filter(r => !key || r.key === key).forEach(r => {
    if (r.kind === "product") add("none");
    else if (r.kind === "other") add("other");
    else new Set([...(r.qualifiers || []), ...(r.informative || [])].map(([q]) => q)).forEach(add);
  });
  select.replaceChildren(new Option(t("records.qualifier.any"), ""),
    ...(counts.none ? [filterOption("none", t("records.qualifier.none"), counts.none)] : []),
    ...qualOrder().filter(q => counts[q]).map(q => filterOption(q, t(`qual.${q}.label`), counts[q])),
    ...(counts.other ? [filterOption("other", t("records.qualifier.other"), counts.other)] : []));
  keepChoice(select, previous);
}

/* "none": records without qualifiers; "other": qualifier sets the portal does not manage; an AI: records
   that have that qualifier, alone or with others, or as information (the batch of a serial number). */
function qualifierMatches(r, choice) {
  if (!choice) return true;
  if (choice === "none") return r.kind === "product";
  if (choice === "other") return r.kind === "other";
  return [...(r.qualifiers || []), ...(r.informative || [])].some(([q]) => q === choice);
}

/* A GS1 Digital Link URI (any domain, any path before the key, query string ignored) or an element
   string with the AIs in brackets, pasted or scanned into the search box:
   { key, value, pairs, ignored } or null when the text is neither. Pairs are the key qualifiers of that
   key; other AIs (data attributes such as (17)) are listed in ignored, as the portal never stores them. */
/* What a scanner sends without brackets — raw scan data with a symbology identifier (]d2, ]Q3, ]C1…), an element
   string with ^ or the group separator, a long string of digits — or an RFID reader's EPC (hexadecimal, eh…, ex…):
   read by the server (the GS1 Barcode Syntax Engine, or the resolver for EPCs) into a bracketed element string. */
const SCANNED = /^(?:\][A-Za-z][0-9A-Za-z]|\d{16,}$)|[\x1d^]/;
const EPC = /^(?:eh[0-9a-f]{20,}|ex[0-9A-Za-z_-]{16,}|(?=[0-9a-f]*[a-f])[0-9a-f]{24,64})$/i;
const scans = new Map();            // text → {bracketed, source} or {code, params}
let scanTimer = null;

function scannedText(raw) {
  return (SCANNED.test(raw) || EPC.test(raw)) && !raw.startsWith("(") && !/^https?:\/\//i.test(raw);
}

function readScanned(raw) {
  if (scans.has(raw)) return;
  clearTimeout(scanTimer);
  scanTimer = setTimeout(async () => {
    try {
      scans.set(raw, await api("POST", "code/read", { text: raw }));
    } catch (e) {
      scans.set(raw, { code: e.code, params: e.params });
    }
    if ($("#records-search").value.replace(INVISIBLE, "").trim() === raw) renderRecords();
  }, 250);
}

function parseCode(text) {
  const typed = text.replace(INVISIBLE, "").trim();
  if (scannedText(typed)) {
    const read = scans.get(typed);
    if (!read) { readScanned(typed); return null; }
    if (!read.bracketed) return null;
    const code = parseCode(read.bracketed);
    if (code) code.read = { from: read.source, as: read.bracketed };
    return code;
  }
  const raw = text.replace(INVISIBLE, "").trim();
  const known = new Set((CONFIG?.keys || []).map(k => k.code));
  let elements = [], extra = [];
  if (raw.startsWith("(")) {
    const compact = raw.replace(/\s+/g, "");
    const found = [...compact.matchAll(/\((\d{2,4})\)([^()]+)/g)];
    if (!found.length || found.map(m => m[0]).join("") !== compact) return null;
    elements = found.map(m => [m[1], m[2]]);
  } else if (/^https?:\/\//i.test(raw)) {
    let url;
    try { url = new URL(raw); } catch { return null; }
    const parts = url.pathname.split("/").filter(Boolean).map(part => {
      try { return decodeURIComponent(part); } catch { return part; }
    });
    const start = parts.findIndex((part, i) => known.has(part) && i + 1 < parts.length);
    if (start < 0) return null;
    for (let i = start; i + 1 < parts.length; i += 2) elements.push([parts[i], parts[i + 1]]);
    // data attributes in the query string (?17=271231) are never qualifiers, and never stored
    extra = [...url.searchParams.keys()].filter(name => /^\d{2,4}$/.test(name));
  } else {
    return null;
  }
  let [[key, value]] = elements;
  if (!known.has(key)) return null;
  if (key === "01" && /^\d{8,13}$/.test(value)) value = value.padStart(14, "0");   // GTIN-8, -12, -13
  const allowed = keyConfig(key).qualifiers;
  const rest = elements.slice(1);
  return {
    key, value,
    pairs: rest.filter(([q]) => allowed.includes(q)),
    ignored: [...new Set([...rest.filter(([q]) => !allowed.includes(q)).map(([q]) => q), ...extra])],
  };
}

/* How a record relates to a code read in the search box: 0 = the exact record (same key and qualifier
   set), 1 = a less specific record (some of the code's qualifiers and nothing else, e.g. the batch of a
   serial number), 2 = a more specific record (every qualifier of the code and more, e.g. the serial
   numbers of a batch); -1 = not related (another batch, a variant when the code names a batch…). */
function codeRank(r, code) {
  if (r.key !== code.key || r.value !== code.value) return -1;
  if (r.kind === "other") return code.pairs.length ? -1 : 2;   // qualifiers the portal does not read
  const own = Object.fromEntries(r.qualifiers || []);
  const known = { ...Object.fromEntries(r.informative || []), ...own };    // with the informative batch/variant
  const wanted = Object.fromEntries(code.pairs);
  const record = splitInformative(code.key, code.pairs).pairs;            // what the code's own record would be
  const inCode = Object.entries(own).every(([q, v]) => wanted[q] === v);
  if (inCode && record.length === Object.keys(own).length && record.every(([q, v]) => own[q] === v)) return 0;
  if (inCode) return 1;
  return code.pairs.every(([q, v]) => known[q] === v) ? 2 : -1;
}

function codeText(code) {
  return [keyText(code.key, code.value), ...code.pairs.map(([q, v]) => keyText(q, v))].join(" ");
}

function filtersActive() {
  return Boolean($("#records-search").value.trim() || $("#records-key").value || $("#records-qualifier").value
                 || $("#records-user").value || $("#records-problems").checked || $("#records-state").value);
}

function clearFilters() {
  $("#records-search").value = "";
  $("#records-key").value = "";
  fillQualifierFilter();
  $("#records-qualifier").value = "";
  $("#records-user").value = "";
  $("#records-state").value = "";
  $("#records-problems").checked = false;
  renderRecords();
  $("#records-search").focus();
}

/* Case- and accent-insensitive text for searching ("Açaí" matches "acai"). */
function fold(text) {
  return String(text || "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

/* "(01) 07898357410015": the AI in brackets, as in the human readable interpretation. */
function keyText(ai, value) {
  return `(${ai}) ${value}`;
}

function scopeText(r) {
  if (r.kind === "qualified") return qualText(r.qualifiers) + informativeText(r.informative);
  if (r.kind !== "other" && r.key !== "01") return t("records.scope.key", { name: t(`key.${r.key}.short`) });
  if (r.kind === "other") {
    return t("records.scope.other", { value: r.other });
  }
  return t("records.scope.product");
}

function warnBadge(key, params) {
  const badge = document.createElement("span");
  badge.className = "badge-warn";
  I18N.set(badge, key, params);
  return badge;
}

function changedText(r) {
  if (!r.updatedAt) return null;
  const when = new Date(r.updatedAt);
  return new Intl.DateTimeFormat(I18N.locale, { dateStyle: "short", timeStyle: "short" }).format(when);
}

function renderRecords() {
  if (!records.loaded) return;
  const text = $("#records-search").value;
  // A GS1 Digital Link or a bracketed element string finds the records of that code; other text is searched word by word.
  const code = parseCode(text);
  // scanner data or an RFID EPC is a code, never words: while it is being read, nothing is filtered by text
  const words = code || scannedText(text.replace(INVISIBLE, "").trim()) ? [] : fold(text).split(/\s+/).filter(Boolean);
  const key = $("#records-key").value;
  const qualifier = $("#records-qualifier").value;
  const user = $("#records-user").value;
  const problemsOnly = $("#records-problems").checked;
  const status = $("#records-state").value;
  const rank = new Map(code ? records.all.map(r => [r, codeRank(r, code)]) : []);
  const shown = records.all
    .filter(r => !key || r.key === key)
    .filter(r => qualifierMatches(r, qualifier))
    .filter(r => !user || r.updatedBy === user)
    .filter(r => !problemsOnly || problemsOf(r).length > 0)
    .filter(r => !status || (status === "nokey" ? r.noKeyRecord : r.breaksRules))
    .filter(r => !code || rank.get(r) >= 0)
    .filter(r => {
      if (!words.length) return true;
      const haystack = fold([r.value, r.value.replace(/^0+/, ""), r.key, t(`key.${r.key}.short`), r.description,
                             [...(r.qualifiers || []), ...(r.informative || [])].map(p => p[1]).join(" "),
                             qualText(r.qualifiers), qualText(r.informative), r.other].join(" "));
      return words.every(w => haystack.includes(w));
    })
    // For a code: the exact record first, then the less specific ones (most qualifiers first).
    // Otherwise the most recently changed first; records without portal history after, by key.
    .sort((a, b) => (code ? rank.get(a) - rank.get(b) || (b.qualifiers || []).length - (a.qualifiers || []).length : 0)
                    || (b.updatedAt || "").localeCompare(a.updatedAt || "") || a.anchor.localeCompare(b.anchor)
                    || (a.qpath || "").localeCompare(b.qpath || ""));

  const hint = $("#records-code");
  const typed = text.replace(INVISIBLE, "").trim();
  const scanned = !code && scannedText(typed) ? (scans.get(typed) || { pending: true }) : null;
  hint.hidden = !code && !scanned;
  if (code) {
    hint.textContent = t("records.code", { code: codeText(code) })
      + (code.read ? " " + t(code.read.from === "epc" ? "records.codeReadEpc" : "records.codeRead", { as: code.read.as }) : "")
      + (code.ignored.length ? " " + t("records.codeIgnored", { ais: code.ignored.map(q => `(${q})`).join(" ") }) : "");
  } else if (scanned) {
    hint.textContent = scanned.pending ? t("records.codeReading") : t(scanned.code || "code.unreadable", scanned.params || {});
  }
  $("#records-clear").hidden = !filtersActive();

  const rows = shown.map(r => {
    const tr = document.createElement("tr");
    const cell = (label, content, cls) => {
      const td = document.createElement("td");
      td.dataset.label = t(label);
      if (cls) td.className = cls;
      if (content instanceof Node) td.append(content); else td.textContent = content;
      tr.append(td);
      return td;
    };
    let name;
    if (r.kind === "other") {
      // Created by another tool with a qualifier set the portal does not manage (e.g. a lot template such as {lotnumber}).
      name = document.createElement("span");
      name.textContent = r.description || r.value;
      name.title = t("records.otherHint");
    } else {
      name = document.createElement("a");
      name.href = "#";
      name.textContent = r.description || t("records.noDescription");
      name.addEventListener("click", e => { e.preventDefault(); openFromList(r); });
    }
    const product = cell("records.col.product", name);
    if (code && rank.get(r) === 0) {
      const badge = Object.assign(document.createElement("span"), { className: "badge badge-match", title: t("records.exactMatchHint") });
      badge.textContent = t("records.exactMatch");
      product.append(" ", badge);
      tr.classList.add("is-match");
    }
    cell("records.col.key", keyText(r.key, r.value), "code");
    const scope = cell("records.col.scope", scopeText(r));
    // section 2.5.9: no default link above this record, or a serial number registered with its batch
    if (r.noKeyRecord) scope.append(document.createElement("br"), warnBadge("records.badge.nokey", {
      what: r.key === "01" ? t("scope.everyUnit") : t("scope.wholeKey", { name: t(`key.${r.key}.short`) }) }));
    if (r.breaksRules) {
      scope.append(document.createElement("br"), warnBadge("records.badge.rules", {}));
      const fix = el("button", "link-button needs-editor records-fix", t("records.rules.fix"));
      fix.type = "button";
      fix.addEventListener("click", () => fixSerials({ key: r.key, value: r.value,
                                                     qualifiers: (r.qualifiers || []).map(([q, v]) => `/${q}/${v}`).join("") }));
      scope.append(" ", fix);
    }
    const linksCell = cell("records.col.links", String(r.links), "num");
    const problems = problemsOf(r);
    if (problems.length) {
      const warn = document.createElement("span");
      warn.className = "link-warn";
      warn.textContent = "⚠ " + problems.length;
      warn.title = problems.map(p => `${p.url} — ${problemText(p)}`).join("\n");
      warn.setAttribute("aria-label", t("records.problemBadge", { count: problems.length }));
      linksCell.append(warn);
    }
    const changed = changedText(r);
    if (changed) {
      const box = document.createElement("span");
      box.append(changed);
      const who = document.createElement("small");
      who.textContent = r.updatedBy;
      box.append(who);
      cell("records.col.changed", box, "changed");
    } else {
      cell("records.col.changed", t("records.noHistory"), "muted");
    }
    return tr;
  });
  $("#records-body").replaceChildren(...rows);

  const empty = $("#records-empty");
  empty.hidden = shown.length > 0;
  if (!shown.length) I18N.set(empty, records.all.length ? "records.noMatch" : "records.none");
  I18N.set($("#records-count"), "records.count", { shown: shown.length, total: records.all.length });
  records.shown = shown;
  filtersToAddress();
  // the spreadsheet holds what the list shows: every record, or only the filtered ones
  const filtered = filtersActive();
  for (const id of ["#records-export-xlsx", "#records-export-csv"]) {
    $(id).title = filtered ? t("records.exportFiltered", { count: shown.length }) : "";
  }
}

/* Opens a record of the list in the editor. */
async function openFromList(r) {
  history.pushState(null, "", location.pathname + location.search);
  applyView();
  $("#key-type").value = r.key;
  onKeyTypeChange();
  $("#key-value").value = r.value;
  (r.qualifiers || []).forEach(([q, v]) => { const input = $("#q-" + q); if (input) input.value = v; });
  onIdentityChange();
  window.scrollTo(0, 0);
  await openRecord();
  if (problemsOf(r).length) checkLinks();
}

/* ------------------------------------------------------------------ link checker */
const linkCheck = { last: null, polling: null };

function problemText(result) {
  return t(result.problem, result.params || {});
}

function problemsOf(r) {
  return linkCheck.last?.records?.[`${r.anchor}|${r.qpath || ""}`] || [];
}

/* Editor: checks the targets currently in the form and writes the result under each one. */
async function checkLinks() {
  const rows = [...document.querySelectorAll("#links .link-row")];
  const urls = rows.map(li => $(".url", li).value.trim()).filter(Boolean);
  const msg = $("#links-check-msg");
  if (!urls.length) return;
  const button = $("#check-links");
  button.disabled = true;
  msg.className = "field-msg";
  I18N.set(msg, "links.checking");
  rows.forEach(li => { $(".row-check", li).hidden = true; });
  try {
    const { results } = await api("POST", "links/check", { urls });
    const byUrl = Object.fromEntries(results.map(r => [r.url, r]));
    let problems = 0;
    rows.forEach(li => {
      const result = byUrl[$(".url", li).value.trim()];
      const box = $(".row-check", li);
      if (!result) return;
      box.hidden = false;
      box.className = "row-check " + (result.ok ? "is-ok" : "is-warn");
      box.textContent = result.ok ? t("links.rowOk", { status: result.status }) : "⚠ " + problemText(result);
      problems += result.ok ? 0 : 1;
    });
    msg.className = "field-msg" + (problems ? " warn-text" : " is-ok");
    I18N.set(msg, problems ? "links.checkProblems" : "links.checkOk", { count: problems });
  } catch (e) {
    I18N.set(msg, e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

function showLinkCheck(last) {
  linkCheck.last = last && last.checkedAt ? last : null;
  const msg = $("#records-check-msg");
  $("#records-problems-wrap").hidden = !linkCheck.last;
  if (!linkCheck.last) { I18N.set(msg, null); return; }
  const date = new Intl.DateTimeFormat(I18N.locale, { dateStyle: "short", timeStyle: "short" })
    .format(new Date(linkCheck.last.checkedAt));
  msg.className = "field-msg" + (Object.keys(linkCheck.last.records).length ? " warn-text" : " is-ok");
  I18N.set(msg, "records.checked", { date, count: Object.keys(linkCheck.last.records).length });
}

/* What to show while a background job waits for the job worker: "in the queue", or a warning when it has
   waited long with no worker running ("stalled"); null once it runs. */
function jobWaitKey(status) {
  if (status?.state !== "queued") return null;
  return status.stalled ? "job.stalled" : "job.queued";
}

/* Background job shared by the record list (every record) and the import preview (a list of URLs).
   onProgress(done, total, status) is called on every poll; a failed job throws its error code. */
async function runLinkJob(body, onProgress) {
  const job = await api("POST", "links/jobs", body);
  onProgress(0, job.total, { state: "queued" });
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 800));
    const status = await api("GET", "links/jobs/" + job.token);
    if (status.state === "finished") return status;
    if (status.state === "failed") throw new ApiError(status.error || "job.failed");
    onProgress(status.done, status.total, status);
  }
}

/* A progress message, or the queue message while the job waits; a stalled job is shown as a warning. */
function showJobProgress(msg, key, done, total, status) {
  msg.className = "field-msg" + (status?.stalled ? " warn-text" : "");
  I18N.set(msg, jobWaitKey(status) || key, { done, total });
}

async function checkAllLinks() {
  const button = $("#records-check");
  const msg = $("#records-check-msg");
  button.disabled = true;
  msg.className = "field-msg";
  try {
    const status = await runLinkJob({ scope: "all" },
      (done, total, job) => showJobProgress(msg, "records.checking", done, total, job));
    showLinkCheck(status);
    renderRecords();
  } catch (e) {
    I18N.set(msg, e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ spreadsheets: export and import */
const SHEET_COLUMNS = ["key", "value", "qualifiers", "description", "linkType", "url", "language", "title", "default", "forward"];
const importState = { token: null, polling: null, imported: false };

/* Texts the server writes into the file (it is language-neutral): headers in the current language,
   and, for imports, every accepted spelling of each header and of yes/no. */
function sheetLabels() {
  const headers = {}, aliases = {};
  SHEET_COLUMNS.forEach(c => { headers[c] = t("sheet.col." + c); aliases[c] = I18N.every("sheet.col." + c); });
  const linkTypes = {};
  (CONFIG?.linkTypes || []).forEach(({ code }) => { linkTypes[code] = I18N.linkType(code); });
  const keys = {};
  (CONFIG?.keys || []).forEach(({ code }) => { keys[code] = t(`key.${code}.name`); });
  aliases.value.push(...I18N.every("sheet.col.gtin"));         // spreadsheets made before other keys existed
  aliases.lot = I18N.every("sheet.col.lot");                   // and before the qualifiers column
  const languages = {};
  (CONFIG?.languages || []).forEach(code => { languages[code] = I18N.languageName(code); });
  return {
    headers, aliases, linkTypes, languages, keys,
    yes: t("sheet.yes"), no: t("sheet.no"),
    yesWords: I18N.every("sheet.yes"), noWords: I18N.every("sheet.no"),
    sheets: { links: t("sheet.links"), linkTypes: t("sheet.linkTypes"), languages: t("sheet.languages"), keys: t("sheet.keys") },
    codeHeader: t("sheet.code"), nameHeader: t("sheet.name"), descriptionHeader: t("sheet.description"),
    languagesNote: t("sheet.languagesNote"),
  };
}

async function exportSheet(format) {
  const button = $(format === "csv" ? "#records-export-csv" : "#records-export-xlsx");
  button.disabled = true;
  try {
    const res = await fetch(BASE + "api/export", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format, labels: sheetLabels(),
                             only: filtersActive() ? (records.shown || []).map(r => `${r.anchor}|${r.qpath || ""}`) : undefined }),
    });
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch { /* not JSON */ }
      throw new ApiError(data?.code || "error.unexpected", data?.params || { status: res.status });
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `resolver-links.${format}`;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (e) {
    I18N.set($("#records-count"), e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

function importStatus(kind, key, params) {
  const box = $("#import-status");
  box.hidden = !key;
  box.className = "status" + (kind ? " is-" + kind : "");
  if (key) I18N.set(box, key, params);
}

/* An error line of the import report: "Row 7: missing or unknown link type…". The import-specific
   wording is used when there is one; otherwise the editor's message. */
function importErrorText(error) {
  const params = { ...error.params };
  if (Array.isArray(params.columns)) params.columns = params.columns.map(c => t("sheet.col." + c)).join(", ");
  const key = I18N.has("import.err." + error.code) ? "import.err." + error.code : error.code;
  return `${t("import.row", { row: error.row })} ${t(key, params)}`;
}

async function checkImportLinks(links) {
  const msg = $("#import-links-msg");
  const list = $("#import-warnings");
  list.replaceChildren();
  msg.className = "field-msg";
  try {
    const status = await runLinkJob({ urls: links.map(l => l.url) },
      (done, total, job) => showJobProgress(msg, "import.linksChecking", done, total, job));
    const bad = Object.fromEntries(status.problems.map(p => [p.url, p]));
    const items = links.filter(l => bad[l.url]).map(l => {
      const li = document.createElement("li");
      li.textContent = `${t("import.row", { row: l.row })} ${l.url} — ${problemText(bad[l.url])}`;
      return li;
    });
    list.replaceChildren(...items);
    msg.className = "field-msg" + (items.length ? " warn-text" : " is-ok");
    I18N.set(msg, items.length ? "import.linksProblems" : "import.linksOk", { count: items.length });
  } catch (e) {
    I18N.set(msg, e.code, e.params);
  }
}

function openImport() {
  clearInterval(importState.polling);
  Object.assign(importState, { token: null, polling: null, imported: false });
  $("#import-file").value = "";
  $("#import-file").disabled = false;
  renderImportLimits();
  $("#import-report").hidden = true;
  $("#import-summary").hidden = false;
  $("#import-warnings").replaceChildren();
  I18N.set($("#import-links-msg"), null);
  importStatus(null, null);
  const apply = $("#import-apply");
  apply.disabled = true;
  apply.hidden = false;
  I18N.set(apply, "import.apply", { count: 0 });
  I18N.set($("#import-cancel"), "options.cancel");
  $("#import-dialog").showModal();
}

function closeImport() {
  clearInterval(importState.polling);
  $("#import-dialog").close();
  if (importState.imported) loadRecords();
}

/* Import limits per accepted format come from the server (sheet.FORMATS), so the dialog, the check
   below and the server never disagree. */
function importLimitFor(filename) {
  const name = String(filename || "").toLowerCase();
  return (CONFIG.importLimits || []).find(l => l.extensions.some(ext => name.endsWith(ext)));
}

function renderImportLimits() {
  const list = $("#import-limits");
  list.replaceChildren(...(CONFIG.importLimits || []).map(limit => {
    const li = document.createElement("li");
    I18N.set(li, "import.limit." + limit.format, { maxRows: limit.maxRows, maxKB: limit.maxKB });
    return li;
  }));
  $("#import-file").accept = [...(CONFIG.importLimits || []).flatMap(l => l.extensions),
    "text/csv", "text/plain", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"].join(",");
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new ApiError("import.unreadable"));
    reader.readAsDataURL(file);
  });
}

function scopeOf(item) {
  if (item.qualifiers?.length) {
    const before = item.informativeBefore
      ? " — " + t("import.informativeChange", { before: qualText(item.informativeBefore) || t("informative.none") }) : "";
    return qualText(item.qualifiers) + informativeText(item.informative) + before;
  }
  return item.key && item.key !== "01" ? t("records.scope.key", { name: t(`key.${item.key}.short`) }) : t("records.scope.product");
}

async function previewImport() {
  const file = $("#import-file").files[0];
  $("#import-report").hidden = true;
  $("#import-apply").disabled = true;
  if (!file) return;
  const limit = importLimitFor(file.name);
  if (limit && file.size > limit.maxKB * 1024) {
    importStatus("error", "import.tooBig", { max: limit.maxKB });
    return;
  }
  importStatus(null, "import.checking");
  try {
    const labels = sheetLabels();
    const report = await api("POST", "import/preview", {
      filename: file.name, content: await readAsBase64(file),
      labels: { aliases: labels.aliases, yes: labels.yesWords, no: labels.noWords },
    });
    importState.token = report.token;
    renderImportReport(report);
    if ($("#import-checklinks").checked && report.links.length) checkImportLinks(report.links);
  } catch (e) {
    importStatus("error", e.code, e.params);
  }
}

function renderImportReport(report) {
  const c = report.counts;
  importStatus(c.error ? "error" : null, c.error ? "import.errorsSkipped" : null);
  I18N.set($("#import-summary"), "import.summary", c);
  $("#import-errors").replaceChildren(...report.errors.map(error => {
    const li = document.createElement("li");
    li.textContent = importErrorText(error);
    return li;
  }));
  $("#import-body").replaceChildren(...report.records.map(item => importRow(item.rows, keyText(item.key || "01", item.value),
    scopeOf(item) + (item.noKeyRecord ? " — " + t("import.noKeyRecord") : ""), item.description, item.action)));
  $("#import-report").hidden = false;
  // section 2.5.9: keys the import would leave without a record of their own
  const keys = report.keysWithoutRecord || [];
  $("#import-keys").hidden = !keys.length;
  if (keys.length) {
    I18N.set($("#import-keys-text"), keys.length === 1 ? "import.keysOne" : "import.keysMany",
             { count: keys.length, list: keys.slice(0, 5).map(k => keyText(k.key, k.value)).join(", ")
                                         + (keys.length > 5 ? " …" : "") });
    $("#import-createkeys").checked = true;
  }
  const count = c.create + c.update;
  const apply = $("#import-apply");
  I18N.set(apply, "import.apply", { count });
  apply.disabled = count === 0;
}

function importRow(rows, gtin, scope, description, action) {
  const tr = document.createElement("tr");
  const badge = document.createElement("span");
  badge.className = "badge badge-" + action;
  I18N.set(badge, "import.action." + action);
  [rows.length > 1 ? `${rows[0]}–${rows.at(-1)}` : String(rows[0]), gtin, scope, description || "", badge]
    .forEach((content, i) => {
      const td = document.createElement("td");
      if (i === 1) td.className = "code";
      if (content instanceof Node) td.append(content); else td.textContent = content;
      tr.append(td);
    });
  return tr;
}

async function applyImport() {
  if (!importState.token) return;
  const apply = $("#import-apply");
  apply.disabled = true;
  $("#import-file").disabled = true;
  try {
    const started = await api("POST", "import/apply", { token: importState.token,
      createKeyRecords: !$("#import-keys").hidden && $("#import-createkeys").checked });
    importStatus(null, "job.queued", { done: 0, total: started.total });
    importState.polling = setInterval(pollImport, 700);
  } catch (e) {
    importStatus("error", e.code, e.params);
  }
}

async function pollImport() {
  let status;
  try {
    status = await api("GET", "import/status?token=" + encodeURIComponent(importState.token));
  } catch (e) {
    clearInterval(importState.polling);
    importStatus("error", e.code, e.params);
    return;
  }
  if (status.state === "failed") {
    clearInterval(importState.polling);
    importStatus("error", status.error || "job.failed");
    return;
  }
  if (status.state !== "finished") {
    importStatus(status.stalled ? "warn" : null, jobWaitKey(status) || "import.running",
                 { done: status.done, total: status.total });
    return;
  }
  clearInterval(importState.polling);
  importState.imported = true;
  const count = action => status.results.filter(r => r.action === action).length;
  const failed = count("failed");
  importStatus(failed ? "error" : "ok", "import.done", { created: count("created"), updated: count("updated"), failed });
  $("#import-errors").replaceChildren(...status.results.filter(r => r.action === "failed").map(r => {
    const li = document.createElement("li");
    li.textContent = importErrorText({ row: r.rows[0], code: r.code, params: r.params || {} });
    return li;
  }));
  $("#import-body").replaceChildren(...status.results.map(r => importRow(r.rows, keyText(r.key, r.value),
    scopeOf(r), r.description, r.action)));
  $("#import-summary").hidden = true;          // the preview counts no longer apply
  $("#import-apply").hidden = true;
  I18N.set($("#import-cancel"), "import.close");
}

/* ------------------------------------------------------------------ step 3: targets */
/* The link types in groups, the groups in the order that suits the key type (item 9.4: every link type of the GS1
   Web Vocabulary; CONFIG.linkTypeOrder[ai]). Called again with the select's value when the key type changes. */
function fillTypeSelect(select, value) {
  const order = CONFIG.linkTypeOrder?.[currentKey()] || CONFIG.linkTypeOrder?.["*"] || [];
  const groups = new Map(order.map(group => [group, []]));
  CONFIG.linkTypes.forEach(({ code, group }) => {
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(code);
  });
  select.replaceChildren(...[...groups].filter(([, codes]) => codes.length).map(([group, codes]) => {
    const optgroup = document.createElement("optgroup");
    optgroup.dataset.i18nGroup = group;
    optgroup.label = t("group." + group);
    codes.forEach(code => {
      const option = new Option("", code);
      option.dataset.i18nType = code;
      optgroup.append(option);
    });
    return optgroup;
  }));
  if (value && !CONFIG.linkTypes.some(x => x.code === value)) {
    const option = new Option("", value);   // link type created outside the portal
    option.dataset.i18nType = value;
    select.append(option);
  }
  select.value = value || "gs1:pip";
  I18N.apply(select);
}

/* Every language a target may be in (CONFIG.languages: ISO 639-1 and the common regional tags), each named by the
   browser in the page's language, names in the Latin alphabet first (I18N.byScript). The rows' language field opens
   one shared list under it — on focus, with its button or the arrow keys — scrolled, and filtered by the language
   being typed (the text after the last comma); choosing one writes its code there. */
const languagePicker = { options: [], input: null, shown: [], active: -1 };

function fillLanguages() {
  const codes = CONFIG?.languages || [];
  languagePicker.options = I18N.byScript(codes, code => I18N.languageName(code))
    .map(code => ({ code, name: I18N.languageName(code) }));
}

const foldText = text => String(text).normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase();

function openLanguagePicker(input) {
  const picker = languagePicker;
  picker.input = input;
  const typed = foldText(input.value.split(",").pop().trim());
  const exact = picker.options.some(o => o.code.toLowerCase() === typed);
  // Names or codes that start with what is typed first, then names that hold it
  const starts = o => foldText(o.name).startsWith(typed) || o.code.toLowerCase().startsWith(typed);
  picker.shown = !typed || exact ? picker.options
    : [...picker.options.filter(starts), ...picker.options.filter(o => !starts(o) && foldText(o.name).includes(typed))];
  picker.active = -1;
  const total = picker.options.length;
  I18N.set($("#language-picker-head"), picker.shown.length === total ? "link.languageCount"
    : picker.shown.length ? "link.languageFiltered" : "link.languageNone", { shown: nf(picker.shown.length), total: nf(total) });
  $("#language-picker-list").replaceChildren(...picker.shown.map((o, i) => {
    const li = el("li", "", o.name);
    li.id = `language-option-${i}`;
    li.setAttribute("role", "option");
    li.dataset.code = o.code;
    li.append(el("span", "code", o.code));
    li.addEventListener("mousedown", e => { e.preventDefault(); chooseLanguage(o.code); });
    return li;
  }));
  // The one list moves under the field (or above it, when the window has more room there) and scrolls with the page
  const box = $("#language-picker"), rect = input.getBoundingClientRect();
  input.parentElement.append(box);
  box.classList.toggle("up", window.innerHeight - rect.bottom < 300 && rect.top > window.innerHeight - rect.bottom);
  box.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function closeLanguagePicker() {
  $("#language-picker").hidden = true;
  languagePicker.input?.setAttribute("aria-expanded", "false");
  languagePicker.input?.removeAttribute("aria-activedescendant");
}

function moveLanguage(step) {
  const picker = languagePicker, items = $("#language-picker-list").children;
  if (!items.length) return;
  picker.active = (picker.active + step + items.length) % items.length;
  [...items].forEach((li, i) => li.setAttribute("aria-selected", String(i === picker.active)));
  items[picker.active].scrollIntoView({ block: "nearest" });
  picker.input.setAttribute("aria-activedescendant", items[picker.active].id);
}

function chooseLanguage(code) {
  const input = languagePicker.input;
  if (!input) return;
  const parts = input.value.split(",").map(p => p.trim());
  parts[parts.length - 1] = code;
  input.value = parts.filter(Boolean).join(", ");
  closeLanguagePicker();
  input.dispatchEvent(new Event("change"));
}

function setupLanguageField(input) {
  const toggle = input.parentElement.querySelector(".combo-toggle");
  input.addEventListener("focus", () => openLanguagePicker(input));
  input.addEventListener("input", () => openLanguagePicker(input));
  input.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== input) closeLanguagePicker(); }, 120));
  input.addEventListener("keydown", e => {
    const open = !$("#language-picker").hidden && languagePicker.input === input;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) openLanguagePicker(input);
      moveLanguage(e.key === "ArrowDown" ? 1 : -1);
    } else if (e.key === "Enter" && open && languagePicker.active >= 0) {
      e.preventDefault();
      chooseLanguage(languagePicker.shown[languagePicker.active].code);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      closeLanguagePicker();
    }
  });
  toggle.addEventListener("mousedown", e => {
    e.preventDefault();
    if (!$("#language-picker").hidden && languagePicker.input === input) closeLanguagePicker();
    else { input.focus(); openLanguagePicker(input); }
  });
}

/* A row's languages from its field: tags (pt, pt-BR) or names as the list shows them, separated by commas;
   null when one is not a well-formed tag. */
const LANGUAGE_TAG = /^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|\d{3}))?(-([A-Za-z0-9]{5,8}|\d[A-Za-z0-9]{3}))*$/;

function readLanguages(text) {
  const names = new Map((CONFIG?.languages || []).map(code => [I18N.languageName(code).toLocaleLowerCase(), code]));
  const tags = String(text || "").split(",").map(part => part.trim()).filter(Boolean).map(part => {
    const named = /\(([^)]+)\)$/.exec(part);                    // "Português (pt)", as a list option reads
    return named ? named[1] : names.get(part.toLocaleLowerCase()) || part;
  });
  return tags.length && tags.every(tag => tag === "und" || LANGUAGE_TAG.test(tag)) ? tags : null;
}

function fillLanguageSelect(input, hreflang) {
  input.value = hreflang.join(", ");
  input.title = hreflang.map(code => I18N.languageName(code)).join(", ");
}

function refreshRowHelp(li) {
  const [label, help] = I18N.linkType($(".link-type", li).value);
  $(".row-help", li).textContent = help;
  $(".title", li).placeholder = label;
}

function defaultLanguage() {
  const code = I18N.locale.slice(0, 2);
  return CONFIG.languages.includes(code) ? code : CONFIG.languages[0];
}

function addRow(data = {}) {
  const li = $("#link-row").content.firstElementChild.cloneNode(true);
  const uid = `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const fields = li.querySelectorAll(".row-grid select, .row-grid input");
  li.querySelectorAll(".row-grid label").forEach((label, i) => {
    fields[i].id = `${uid}-${i}`;
    label.htmlFor = fields[i].id;
  });

  const typeSelect = $(".link-type", li);
  fillTypeSelect(typeSelect, data.linkType);
  const hreflang = data.hreflang && data.hreflang.length ? data.hreflang : [defaultLanguage()];
  const languageField = $(".language", li);
  fillLanguageSelect(languageField, hreflang);
  setupLanguageField(languageField);
  li.dataset.hreflang = JSON.stringify(hreflang);
  li.dataset.context = JSON.stringify(data.context || []);

  $(".url", li).value = data.url || "";
  $(".title", li).value = data.title || "";

  typeSelect.addEventListener("change", () => { refreshRowHelp(li); refreshDefault(); });
  languageField.addEventListener("change", () => {
    const tags = readLanguages(languageField.value);
    languageField.setAttribute("aria-invalid", String(!tags));
    languageField.classList.toggle("is-invalid", !tags);
    if (tags) {
      li.dataset.hreflang = JSON.stringify(tags);
      fillLanguageSelect(languageField, tags);
    }
  });
  $(".url", li).addEventListener("blur", e => {
    const value = e.target.value.trim();
    if (value && !/^[a-z]+:\/\//i.test(value)) e.target.value = "https://" + value;
  });
  $(".make-default", li).addEventListener("click", () => {
    $("#links").prepend(li);
    refreshDefault();
    $(".link-type", li).focus();
  });
  $(".remove", li).addEventListener("click", () => {
    if ($("#links").children.length === 1) {
      showStatus("error", "links.minOne");
      return;
    }
    li.remove();
    refreshDefault();
  });

  I18N.apply(li);
  refreshRowHelp(li);
  $("#links").append(li);
  refreshDefault();
  return li;
}

/* The first target is the default link (gs1:defaultLink), unless the item's page is. Each record chooses for itself
   (ADR 0011, amendment): a key whose records use the page has explicit default links, one per record, written by the
   server. Otherwise, when other records share the key (product/batches), the default link type is shared and must be
   kept; ticking the page turns them to explicit default links on saving, each keeping its own target. */
const LANDING_TYPE = "gs1:defaultLink";

function currentDefaultType() {
  const first = $("#links .link-row .link-type");
  return $("#landing-page").checked ? LANDING_TYPE : (first ? first.value : null);
}

function refreshDefault() {
  const msg = $("#default-msg");
  const landing = $("#landing-page").checked;
  $("#links").classList.toggle("landing", landing);
  const current = currentDefaultType(), shared = state.sharedDefaultLinkType;
  if (!current || !shared || landing) {
    I18N.set(msg, landing && shared ? "landing.switches" : null);
    msg.className = "field-msg";
    return;
  }
  const mismatch = current !== shared;
  I18N.set(msg, mismatch ? "default.sharedLocal" : "default.shared", { linkType: shared });
  msg.className = "field-msg" + (mismatch ? " is-error" : "");
}

/* How the key's other records use the item's page, above the targets: the choice for this record is made knowing
   theirs (a scan of the key alone, or of a batch without a record, reaches the key's own record). */
function renderLandingUse() {
  const box = $("#landing-others");
  const entries = othersState.entries;
  box.hidden = !entries.length;
  if (box.hidden) return;
  const name = e => e.kind === "product" ? t("landing.keyRecord", { key: t(`key.${readKey().ai}.short`) }) : otherApplies(e);
  const list = items => items.slice(0, 3).map(name).join("; ")
    + (items.length > 3 ? " " + t("landing.more", { count: items.length - 3 }) : "");
  const page = entries.filter(e => e.landingPage), own = entries.filter(e => !e.landingPage);
  box.textContent = [page.length ? t("landing.othersPage", { list: list(page) }) : "",
                     own.length ? t("landing.othersOwn", { list: list(own) }) : ""].filter(Boolean).join(" ");
}

function collect() {
  const g = readKey(), l = readQualifiers();
  return {
    key: g.ai,
    value: g.value,
    qualifiers: Object.fromEntries(l.pairs || []),
    description: $("#description").value,
    defaultLinkType: $("#links .link-row .link-type").value,
    landingPage: $("#landing-page").checked,
    links: [...document.querySelectorAll("#links .link-row")].map(li => ({
      linkType: $(".link-type", li).value,
      url: $(".url", li).value.trim(),
      title: $(".title", li).value.trim(),
      hreflang: JSON.parse(li.dataset.hreflang),
      context: JSON.parse(li.dataset.context),
    })),
  };
}

/* ------------------------------------------------------------------ save / delete */
async function save(event) {
  event.preventDefault();
  if (!state.openKey) return;
  if ($("#links .language.is-invalid")) {             // a language typed that is no language tag (item 9.4)
    showStatus("error", "link.languageInvalid");
    $("#links .language.is-invalid").focus();
    return;
  }
  const body = collect();
  if (needsKeyRecord(body)) {
    const choice = await askKeyRecord(body);
    if (!choice) return;                             // cancelled: nothing saved
    if (choice.mode === "none") state.keyPromptDone = true;
    else body.keyRecord = choice;
  }
  const button = $("#save");
  button.disabled = true;
  I18N.set(button, "save.saving");
  hideStatus();
  try {
    const result = await api("POST", "record", body);
    if (result.keyRecordCreated) {
      state.hasKeyRecord = true;
      refreshOthers();
    }
    state.snapshot = editorSnapshot();
    state.exists = true;
    $("#delete").hidden = false;
    setPublished(true);
    showStatus("ok", result.code);
    checkLinks();                       // warns about targets that do not answer; never blocks the save
  } catch (e) {
    showStatus("error", e.code, e.params);
  } finally {
    button.disabled = false;
    I18N.set(button, "save.button");
  }
}

/* GS1-Conformant Resolver 1.2.1, section 2.5.9: for any code "there SHALL be a default link available either at
   the entry level or at a higher level". Saving a qualified record of a key without a record of its own asks
   whether to create that record too (copying the targets, recommended), with another target, or not. */
function needsKeyRecord(body) {
  const own = splitInformative(body.key, readQualifiers().pairs || []).pairs;
  return keyConfig(body.key).keyLevel && own.length > 0 && !state.hasKeyRecord && !state.keyPromptDone;
}

function askKeyRecord(body) {
  const dialog = $("#keyrecord-dialog");
  const g = readKey();
  const own = splitInformative(g.ai, readQualifiers().pairs || []).pairs;
  const name = t(`key.${g.ai}.short`);
  const what = g.ai === "01" ? t("scope.everyUnit") : t("scope.wholeKey", { name });
  I18N.set($("#keyrecord-title"), "keyRecord.title", { what });
  I18N.set($("#keyrecord-intro"), "keyRecord.intro", { record: qualText(own), key: keyText(g.ai, g.value), name });
  I18N.set($("#keyrecord-copy"), "keyRecord.copy", { what });
  I18N.set($("#keyrecord-target"), "keyRecord.target", { what });
  I18N.set($("#keyrecord-none"), "keyRecord.none", { record: qualText(own) });
  I18N.set($("#keyrecord-noneHint"), "keyRecord.noneHint", { name });
  I18N.set($("#keyrecord-description-label"), "keyRecord.description", { what });
  I18N.set($("#keyrecord-type"), "keyRecord.type", { type: I18N.linkTypeOption(body.defaultLinkType),
                                                     language: I18N.languageName(body.links[0]?.hreflang?.[0] || "") });
  $("#keyrecord-links").replaceChildren(...body.links.map(l => Object.assign(document.createElement("li"), {
    textContent: `${I18N.linkTypeOption(l.linkType)} — ${l.url}` })));
  $("#keyrecord-description").value = body.description;
  $("#keyrecord-url").value = "";
  I18N.set($("#keyrecord-msg"), null);
  const radios = $$("#keyrecord-dialog input[name=keyrecord]");
  const mark = () => radios.forEach(r => r.closest(".choice-card").classList.toggle("sel", r.checked));
  radios[0].checked = true;
  mark();
  const sync = () => {
    mark();
    const mode = radios.find(r => r.checked).value;
    $("#keyrecord-description").disabled = mode === "none";
    if (mode === "target") $("#keyrecord-url").focus();
  };
  radios.forEach(r => { r.onchange = sync; });
  sync();
  dialog.showModal();
  return new Promise(resolve => {
    const finish = value => {
      dialog.onclose = null;
      dialog.close();
      resolve(value);
    };
    $("#keyrecord-save").onclick = () => {
      const mode = radios.find(r => r.checked).value;
      const url = $("#keyrecord-url").value.trim();
      if (mode === "target" && !/^https?:\/\/\S+$/i.test(url)) {
        I18N.set($("#keyrecord-msg"), "keyRecord.urlRequired");
        $("#keyrecord-url").focus();
        return;
      }
      finish({ mode, url, description: $("#keyrecord-description").value.trim() });
    };
    $("#keyrecord-cancel").onclick = () => finish(null);
    $("#keyrecord-close").onclick = () => finish(null);
    dialog.onclose = () => resolve(null);           // Escape
  });
}

/* The other records of the key, again (after a save that created the key's own record). */
async function refreshOthers() {
  const g = readKey(), l = readQualifiers();
  try {
    const record = await api("GET", "record?" + query(g, l));
    setOpenMessage("open.found", {}, record.otherEntries);
  } catch { /* the list stays as it was */ }
}

/* ---------------------------------------------------------------- copy targets from another record */
const copyState = { records: null, chosen: null };

async function openCopy() {
  const pop = $("#copy-pop");
  if (!pop.hidden) { closeCopy(); return; }
  pop.hidden = false;
  $("#copy-from").setAttribute("aria-expanded", "true");
  copyState.chosen = null;
  $("#copy-search").value = "";
  updateCopyButtons();
  try {
    copyState.records = (await api("GET", "records")).records.filter(r => r.kind !== "other");
  } catch (e) {
    copyState.records = [];
    I18N.set($("#copy-msg"), e.code, e.params);
  }
  drawCopyList();
  $("#copy-search").focus();
}

function closeCopy() {
  $("#copy-pop").hidden = true;
  $("#copy-from").setAttribute("aria-expanded", "false");
  I18N.set($("#copy-msg"), "copy.note");
}

function drawCopyList() {
  const g = readKey();
  const own = state.openKey;
  const words = fold($("#copy-search").value).split(/\s+/).filter(Boolean);
  const list = (copyState.records || [])
    .filter(r => query({ ai: r.key, value: r.value }, { pairs: r.qualifiers }) !== own)
    .filter(r => words.every(w => fold([r.value, r.description, scopeText(r)].join(" ")).includes(w)))
    // records of the same key first, then the most recently changed
    .sort((a, b) => (b.value === g.value) - (a.value === g.value) || (b.updatedAt || "").localeCompare(a.updatedAt || ""))
    .slice(0, 8);
  $("#copy-list").replaceChildren(...list.map(r => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.tabIndex = 0;
    const name = Object.assign(document.createElement("strong"), { textContent: r.description || keyText(r.key, r.value) });
    const what = Object.assign(document.createElement("span"), { className: "code",
                               textContent: `${keyText(r.key, r.value)} · ${scopeText(r)}` });
    const count = Object.assign(document.createElement("span"), { className: "copy-count",
                                textContent: t(r.links === 1 ? "copy.oneTarget" : "copy.targets", { count: r.links }) });
    li.append(name, what, count);
    const choose = () => {
      copyState.chosen = r;
      $$("#copy-list li").forEach(x => x.setAttribute("aria-selected", String(x === li)));
      updateCopyButtons();
    };
    li.addEventListener("click", choose);
    li.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } });
    return li;
  }));
  if (!list.length) I18N.set($("#copy-msg"), "copy.none");
  else I18N.set($("#copy-msg"), "copy.note");
}

function updateCopyButtons() {
  $("#copy-append").disabled = $("#copy-replace").disabled = !copyState.chosen;
}

/* Puts the chosen record's targets in the form, after the current ones or instead of them. */
async function copyTargets(replace) {
  const r = copyState.chosen;
  if (!r) return;
  try {
    const source = await api("GET", "record?" + query({ ai: r.key, value: r.value }, { pairs: r.qualifiers }));
    if (replace) $("#links").replaceChildren();
    source.links.forEach(addRow);
    refreshDefault();
    closeCopy();
    showStatus("ok", replace ? "copy.replaced" : "copy.appended", { count: source.links.length });
  } catch (e) {
    I18N.set($("#copy-msg"), e.code, e.params);
  }
}

async function remove() {
  const g = readKey(), l = readQualifiers();
  const own = splitInformative(g.ai, l.pairs || []).pairs;
  const target = own.length
    ? t("delete.targetQualified", { qualifiers: qualText(own), key: keyText(g.ai, g.value) })
    : t("delete.targetBase", { key: keyText(g.ai, g.value) });
  if (!await ask(t("delete.confirm", { target }), { danger: true })) return;
  try {
    const result = await api("DELETE", "record?" + query(g, l));
    showStatus("ok", result.code);
    state.exists = false;
    $("#delete").hidden = true;
    setPublished(false);
  } catch (e) {
    showStatus("error", e.code, e.params);
  }
}

function showStatus(kind, code, params) {
  const el = $("#status");
  el.className = "status is-" + kind;
  I18N.set(el, code, params);
  el.hidden = false;
  el.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function hideStatus() {
  $("#status").hidden = true;
}

/* ------------------------------------------------------------------ user menu */
function setupUserMenu() {
  const menu = $("#user-menu");
  const button = $("#user-button");
  const items = () => [...menu.querySelectorAll(".menu-item")];
  const open = (focusFirst) => {
    menu.classList.add("is-open");
    button.setAttribute("aria-expanded", "true");
    if (focusFirst) items()[0].focus();
  };
  const close = (returnFocus) => {
    menu.classList.remove("is-open");
    button.setAttribute("aria-expanded", "false");
    if (returnFocus) button.focus();
  };
  button.addEventListener("click", () => (menu.classList.contains("is-open") ? close() : open(false)));
  button.addEventListener("keydown", e => { if (e.key === "ArrowDown") { e.preventDefault(); open(true); } });
  menu.addEventListener("keydown", e => {
    const list = items();
    const i = list.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); close(true); }
    if (e.key === "ArrowDown" && i >= 0) { e.preventDefault(); list[(i + 1) % list.length].focus(); }
    if (e.key === "ArrowUp" && i >= 0) { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
  });
  document.addEventListener("click", e => { if (!menu.contains(e.target)) close(false); });
  // A choice closes the menu even while the pointer is still over it (the menu also opens on hover): it stays
  // closed until the pointer leaves, instead of covering the page that was chosen.
  const dismiss = () => { close(false); menu.classList.add("is-dismissed"); };
  menu.addEventListener("mouseleave", () => menu.classList.remove("is-dismissed"));
  $("#menu-options").addEventListener("click", () => { dismiss(); openOptions(); });
  ["#menu-overview", "#menu-editor", "#menu-records", "#menu-requests", "#menu-users", "#menu-tenants", "#menu-domains",
   "#menu-branding", "#menu-sso", "#menu-apikeys", "#menu-audit"].forEach(sel => $(sel).addEventListener("click", dismiss));
  $("#menu-logout").addEventListener("click", signOut);
}

async function signOut() {
  try { await api("POST", "logout", {}); } catch { /* signed out locally anyway */ }
  location.replace("login?reason=signedOut");
}

/* ------------------------------------------------------------------ options: change password */
function openOptions(mustChange = false) {
  const form = $("#password-form");
  form.reset();
  $("#must-change-note").hidden = !mustChange;
  $("#password-status").hidden = true;
  I18N.set($("#password-cancel"), "options.cancel");
  fillPreferences();
  $("#options-dialog").showModal();
  $("#current-password").focus();
}

function passwordStatus(kind, code, params) {
  const el = $("#password-status");
  el.className = "status is-" + kind;
  I18N.set(el, code, params);
  el.hidden = false;
}

async function changePassword(event) {
  event.preventDefault();
  const current = $("#current-password").value;
  const next = $("#new-password").value;
  if (!current || !next) return passwordStatus("error", "password.missing");
  if (next.length < 12) return passwordStatus("error", "password.tooShort", { min: 12 });
  if (next !== $("#confirm-password").value) return passwordStatus("error", "password.mismatch");
  const button = $("#password-save");
  button.disabled = true;
  try {
    const result = await api("POST", "password", { currentPassword: current, newPassword: next });
    $("#password-form").reset();
    passwordStatus("ok", result.code);
    if (CONFIG?.mustChange) {                   // temporary password replaced: the portal is now usable
      CONFIG.mustChange = false;
      $("#must-change-note").hidden = true;
    }
    I18N.set($("#password-cancel"), "options.close");
  } catch (e) {
    passwordStatus("error", e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ options: e-mail preferences */
function prefsStatus(kind, code, params) {
  const el = $("#prefs-status");
  el.hidden = !code;
  el.className = "status" + (kind ? " is-" + kind : "");
  if (code) I18N.set(el, code, params);
}

function fillPreferences() {
  const prefs = CONFIG?.preferences;
  if (!CONFIG?.mail?.enabled || !prefs) return;
  if (prefs.email) I18N.set($("#prefs-address"), "prefs.address", { email: prefs.email });
  else I18N.set($("#prefs-address"), "prefs.noAddress");
  const select = $("#prefs-language");
  if (!select.options.length) select.replaceChildren(...I18N.MENU.map(loc => new Option(I18N.nameOf(loc), loc)));
  select.value = prefs.language || I18N.locale;
  $("#prefs-jobs").checked = Boolean(prefs.notify?.jobs);
  $("#prefs-alerts").checked = prefs.notify?.alerts !== false;
  prefsStatus(null, null);
}

async function savePreferences(event) {
  event.preventDefault();
  const button = $("#prefs-save");
  button.disabled = true;
  try {
    const result = await api("PUT", "preferences", { language: $("#prefs-language").value,
                                                     notify: { jobs: $("#prefs-jobs").checked,
                                                               alerts: $("#prefs-alerts").checked } });
    CONFIG.preferences = result.preferences;
    prefsStatus("ok", result.code);
  } catch (e) {
    prefsStatus("error", e.code, e.params);
  } finally {
    button.disabled = false;
  }
}

function setupOptions() {
  const dialog = $("#options-dialog");
  $("#options-close").addEventListener("click", () => dialog.close());
  $("#password-cancel").addEventListener("click", () => dialog.close());
  $("#password-form").addEventListener("submit", changePassword);
  $("#prefs-form").addEventListener("submit", savePreferences);
  dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });   // click on the backdrop
}

/* ------------------------------------------------------------------ language menu */
function buildLocaleMenu() {
  const select = $("#locale");
  select.replaceChildren(...I18N.MENU.map(loc => new Option(I18N.nameOf(loc), loc)));
  select.value = I18N.locale;
  select.addEventListener("change", () => I18N.setLocale(select.value));
}

document.addEventListener("localechange", () => {
  $("#locale").value = I18N.locale;
  document.querySelectorAll("#links .link-row").forEach(refreshRowHelp);
  renderPreview();   // refreshes the QR code's alternative text
});

/* ------------------------------------------------------------------ start-up */
async function init() {
  // An invitation or recovery link opened while someone is signed in in this browser: the sign-in page redirected
  // here, keeping the fragment. The link is for choosing a password, so this session ends and the page goes back.
  if (/^#(invite|reset)=/.test(location.hash)) {
    try { await api("POST", "logout", {}); } catch { /* signed out locally anyway */ }
    location.replace("login" + location.hash);
    return;
  }
  await I18N.ready;                       // the language's catalogue (ADR 0014)
  buildLocaleMenu();
  I18N.apply();
  setupUserMenu();
  setupOptions();
  setupLabelOptions();

  // Events first: the page responds even before the configuration arrives.
  $("#key-type").addEventListener("change", () => { $("#key-value").value = ""; onKeyTypeChange(); $("#key-value").focus(); });
  $("#key-value").addEventListener("input", onIdentityChange);

  $("#key-value").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); openRecord(); } });
  $("#open").addEventListener("click", openRecord);
  $("#others-search").addEventListener("input", drawOthers);
  $("#others-filter").addEventListener("change", drawOthers);
  window.addEventListener("resize", fitOthers);
  document.addEventListener("localechange", () => { if (othersState.entries.length) renderOthers(othersState.entries); });
  $("#add").addEventListener("click", () => $(".url", addRow()).focus());
  $("#landing-page").addEventListener("change", refreshDefault);
  $("#copy-from").addEventListener("click", openCopy);
  $("#copy-cancel").addEventListener("click", closeCopy);
  $("#copy-search").addEventListener("input", drawCopyList);
  $("#copy-append").addEventListener("click", () => copyTargets(false));
  $("#copy-replace").addEventListener("click", () => copyTargets(true));
  $("#copy-pop").addEventListener("keydown", e => { if (e.key === "Escape") { closeCopy(); $("#copy-from").focus(); } });
  $("#records-state").addEventListener("change", renderRecords);
  $("#records-alert-show").addEventListener("click", () => { $("#records-state").value = "nokey"; renderRecords(); });
  $("#records-rules-show").addEventListener("click", () => { $("#records-state").value = "rules"; renderRecords(); });
  $("#records-rules-fix").addEventListener("click", async () => {
    if (await ask(t("records.rules.confirmAll"))) fixSerials({ all: true });
  });
  $("#form").addEventListener("submit", save);
  $("#delete").addEventListener("click", remove);
  $("#copy").addEventListener("click", async e => {
    const button = e.currentTarget;
    await navigator.clipboard.writeText(button.dataset.uri);
    I18N.set(button, "preview.copied");
    setTimeout(() => I18N.set(button, "preview.copy"), 1800);
  });

  $("#records-search").addEventListener("input", renderRecords);
  $("#history-toggle").addEventListener("click", toggleHistory);
  $("#users-create").addEventListener("submit", createUser);
  $("#apikeys-create").addEventListener("submit", createApiKey);
  $("#apikey-copy").addEventListener("click", () => navigator.clipboard?.writeText($("#apikey-value").textContent));
  $("#temp-password-copy").addEventListener("click", () => navigator.clipboard?.writeText($("#temp-password-value").textContent));
  $("#audit-filters").addEventListener("submit", loadAudit);
  $("#users-tenant-filter").addEventListener("change", renderUsers);
  $("#tenants-create").addEventListener("submit", createTenant);
  $("#export-maximum-form").addEventListener("submit", saveExportMaximum);
  $("#gcp-form").addEventListener("submit", uploadGcp);
  $("#support-form").addEventListener("submit", startSupport);
  $("#support-cancel").addEventListener("click", () => $("#support-dialog").close());
  $("#support-leave").addEventListener("click", endSupport);
  $("#audit-csv").addEventListener("click", downloadAudit);
  $("#requests-filters").addEventListener("submit", e => loadRequests(e));
  $("#requests-map-box").addEventListener("toggle", () => loadRequestMap());
  $("#requests-more").addEventListener("click", () => loadRequests(null, true));
  $("#requests-csv").addEventListener("click", downloadRequests);
  $("#requests-tab-resolver").addEventListener("click", () => showRequestsTab("resolver"));
  $("#requests-tab-api").addEventListener("click", () => showRequestsTab("api"));
  $("#requests-tab-retention").addEventListener("click", () => showRequestsTab("retention"));
  $("#retention-global").addEventListener("submit", e => {
    e.preventDefault();
    saveRetention({ days: $("#retention-global-days").value.trim() });
  $("#retention-max").addEventListener("submit", e => {
    e.preventDefault();
    const value = $("#retention-max-mb").value.trim();
    saveRetention({ maxMegabytes: value === "" ? null : value });
  });
  });
  $("#requests-api-filters").addEventListener("submit", e => loadApiCalls(e));
  $("#requests-api-more").addEventListener("click", () => loadApiCalls(null, true));
  $("#overview-days").addEventListener("change", () => loadOverview());
  $("#domains-create").addEventListener("submit", createDomain);
  $("#branding-form").addEventListener("submit", saveBranding);
  fillEpcOptions();
  $("#epc").addEventListener("toggle", refreshEpc);
  $("#epc-prefix").addEventListener("change", refreshEpc);
  $("#epc-filter").addEventListener("change", refreshEpc);
  document.addEventListener("localechange", () => { fillEpcOptions(readKey().ai); refreshEpc(); });
  $("#sso-add").addEventListener("submit", e => {
    e.preventDefault();
    ssoState.extra.push($("#sso-add-scope").value);
    renderSso();
  });
  document.addEventListener("localechange", () => { if (ssoState.data && !$("#sso-view").hidden) renderSso(); });
  document.addEventListener("localechange", () => { if (brandingState.data && !$("#branding-view").hidden) renderBranding(); });
  $("#opt-domain").addEventListener("change", renderPreview);
  document.addEventListener("localechange", () => { if (domainsState.data && !$("#domains-view").hidden) renderDomains(); });
  $("#overview-xlsx").addEventListener("click", () => exportOverview("xlsx"));
  $("#overview-csv").addEventListener("click", () => exportOverview("csv"));
  document.addEventListener("localechange", () => { if (overviewState.data && !$("#overview-view").hidden) renderOverview(); });
  $("#records-problems").addEventListener("change", renderRecords);
  $("#records-check").addEventListener("click", checkAllLinks);
  $("#check-links").addEventListener("click", checkLinks);
  $("#records-export-xlsx").addEventListener("click", () => exportSheet("xlsx"));
  $("#records-export-csv").addEventListener("click", () => exportSheet("csv"));
  $("#records-import").addEventListener("click", openImport);
  $("#import-file").addEventListener("change", previewImport);
  $("#import-apply").addEventListener("click", applyImport);
  $("#import-cancel").addEventListener("click", closeImport);
  $("#import-close").addEventListener("click", closeImport);
  $("#import-dialog").addEventListener("cancel", e => { e.preventDefault(); closeImport(); });
  $("#records-user").addEventListener("change", renderRecords);
  $("#records-key").addEventListener("change", () => { fillQualifierFilter(); renderRecords(); });
  $("#records-qualifier").addEventListener("change", renderRecords);
  $("#records-clear").addEventListener("click", clearFilters);
  $("#records-new").addEventListener("click", e => {
    e.preventDefault();
    history.pushState(null, "", location.pathname + location.search);
    applyView();
    resetAttributes();
    $("#key-value").focus();
  });
  window.addEventListener("hashchange", applyView);
  $("#ask-ok").addEventListener("click", () => $("#ask-dialog").close("ok"));
  $("#ask-cancel").addEventListener("click", () => $("#ask-dialog").close("cancel"));
  $("#sidebar-toggle").addEventListener("click", () => foldSidebar(!document.body.classList.contains("sidebar-folded")));
  $("#new-user-tenant").addEventListener("change", newUserPicker);
  $("#overview-tenant").addEventListener("change", loadOverview);
  $("#alerts-filters").addEventListener("submit", loadAlerts);
  $("#privacy-form").addEventListener("submit", publishPrivacy);
  $("#forwarding-fallback-form").addEventListener("submit", saveFallback);
  $("#forwarding-rule-form").addEventListener("submit", e => saveRule(e));
  $("#rule-cancel").addEventListener("click", resetRuleForm);
  $("#appearance-form").addEventListener("submit", saveAppearance);
  $("#appearance-form").addEventListener("input", previewAppearance);
  $("#appearance-logo").addEventListener("change", () => pickAppearanceImage("logo"));
  $("#appearance-icon").addEventListener("change", () => pickAppearanceImage("icon"));
  $("#appearance-reset").addEventListener("click", resetAppearance);
  document.addEventListener("localechange", renderForwarding);
  $("#privacy-preview-button").addEventListener("click", previewPrivacy);
  $("#privacy-text").addEventListener("input", e => { e.target.dataset.edited = "1"; });
  for (const tab of $$("#org-tabs [role=tab]")) {
    tab.addEventListener("click", () => { orgState.tab = tab.dataset.tab; renderOrganisation(); });
  }
  $("#org-tabs").addEventListener("keydown", e => {             // arrow keys move between the tabs
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = $$("#org-tabs [role=tab]").filter(x => !x.hidden);
    const at = tabs.indexOf(document.activeElement);
    const next = tabs[(at + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    orgState.tab = next.dataset.tab; renderOrganisation(); next.focus();
  });
  document.addEventListener("localechange", () => {
    buildSidebar();
    if (!$("#organisation-view").hidden) renderOrganisation();
    if (!$("#alerts-view").hidden) loadAlerts({ preventDefault() {} });
  });
  document.addEventListener("localechange", () => {            // dates, scope texts and filter names follow the language
    if (records.loaded) fillFilters();
    renderRecords();
  });
  applyView();

  try {
    CONFIG = await api("GET", "config");
  } catch (e) {
    showStatus("error", "error.config", { detail: t(e.code, e.params) });
    return;
  }
  document.body.dataset.role = CONFIG.role;
  document.body.dataset.accountRole = CONFIG.accountRole;
  document.body.dataset.serverAdmin = String(Boolean(CONFIG.serverAdmin));
  document.body.dataset.export = CONFIG.exportLimit === 0 ? "off" : "on";   // export limits (items 7.1, 9.8)
  document.body.dataset.operatorView = String(Boolean(CONFIG.serverAdmin && !CONFIG.support));
  document.body.dataset.mail = CONFIG.mail?.enabled ? "on" : "off";
  showTenant();
  buildSidebar();
  loadOrganisations();
  SessionClock.start(CONFIG.session);
  setupAttributes();
  fillDomainOption();
  fillSizeOptions();                             // the scanning environments come with the configuration
  fillLanguages();
  document.addEventListener("localechange", fillLanguages);
  window.addEventListener("resize", closeLanguagePicker);
  fillKeyTypes();
  onKeyTypeChange();
  applyView();                                   // administrator views need the role
  if (CONFIG.mustChange) openOptions(true);
  $("#user-name").textContent = CONFIG.user;
  $("#password-username").value = CONFIG.user;   // lets password managers pair the new password with the account
  onIdentityChange();
}

init();
