"use strict";

/*
 * The portal page: one script, no build step and no framework. The server (portal/app.py) is the
 * authority on every rule; the checks here only give instant feedback. Texts come from I18N
 * (i18n.js) by message code, so the same code serves pt-BR and en-GB.
 *
 * Sections, in order:
 *   API ............................ api(): JSON calls to /portal/api/*, errors as ApiError(code, params)
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

/* ------------------------------------------------------------------ GS1 rules (mirror of the back end, for instant feedback only) */
function checkDigit(body) {
  let sum = 0;
  [...body].reverse().forEach((d, i) => { sum += Number(d) * (i % 2 === 0 ? 3 : 1); });
  return (10 - (sum % 10)) % 10;
}

/* ------------------------------------------------------------------ primary identification keys
   GS1 Digital Link URI Syntax 1.7, section 4.3. The same rules as portal/gs1.py (which the server
   applies again): live feedback while typing. */
const CSET82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz";
const CSET32 = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97];
const NUMERIC_KEYS = { "414": 13, "417": 13, "8017": 18, "8018": 18, "00": 18, "402": 17 };
const ALNUM = /^[A-Za-z0-9.\-]+$/;

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

function checkAlnum(value, max, pattern = ALNUM, code = "key.chars") {
  if (value.length > max) return fail("key.tooLong", { max });
  if (!pattern.test(value)) return fail(code);
  if (value.length < 4 || !/^\d{4}/.test(value)) return fail("key.companyPrefix");
  return null;
}

function checkWithSerial(value, serialMax, filler = "") {
  let body = value;
  if (filler) {
    if (!value.startsWith(filler)) return fail("key.graiZero");
    body = value.slice(filler.length);
  }
  const base = body.slice(0, 13), serial = body.slice(13);
  if (base.length < 13 || !/^\d+$/.test(base)) return { ok: false, key: "key.baseDigits", params: { length: 13 } };
  const expected = checkDigit(base.slice(0, -1));
  if (Number(base.at(-1)) !== expected) return fail("key.checkDigit", { expected });
  if (serial.length > serialMax) return fail("key.serialTooLong", { max: serialMax });
  if (serial && !ALNUM.test(serial)) return fail("key.chars");
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
  const value = ai in NUMERIC_KEYS || ["8006", "255"].includes(ai) ? raw.replace(/[.\-]/g, "") : raw;
  let problem = null;
  if (ai in NUMERIC_KEYS) problem = checkNumeric(value, NUMERIC_KEYS[ai]);
  else if (ai === "8006") {
    if (!/^\d+$/.test(value)) problem = fail("key.digitsOnly");
    else if (value.length !== 18) problem = { ok: false, key: "key.length", params: { expected: 18, length: value.length } };
    else {
      const expected = checkDigit(value.slice(0, 13));
      if (Number(value[13]) !== expected) problem = fail("key.checkDigit", { expected });
      else {
        const piece = Number(value.slice(14, 16)), total = Number(value.slice(16, 18));
        if (!piece || !total || piece > total) problem = fail("key.itipPiece");
      }
    }
  } else if (ai === "8013") {
    problem = checkAlnum(value, 25);
    if (!problem && (value.length < 3 || value.slice(-2) !== gmnPair(value.slice(0, -2)))) {
      problem = fail("key.gmnPair", { expected: value.length < 3 ? "" : gmnPair(value.slice(0, -2)) });
    }
  } else if (ai === "8010") problem = checkAlnum(value, 30, /^[0-9A-Z\-]+$/, "key.cpidChars");
  else if (ai === "401" || ai === "8004") problem = checkAlnum(value, 30);
  else if (ai === "255") {
    if (!/^\d+$/.test(value)) problem = fail("key.digitsOnly");
    else if (value.length < 13 || value.length > 25) {
      problem = { ok: false, key: "key.lengthRange", params: { min: 13, max: 25, length: value.length } };
    } else {
      const expected = checkDigit(value.slice(0, 12));
      if (Number(value[12]) !== expected) problem = fail("key.checkDigit", { expected });
    }
  } else if (ai === "253") problem = checkWithSerial(value, 17);
  else if (ai === "8003") problem = checkWithSerial(value, 16, "0");
  if (problem) return { ...problem, ai };
  return { ok: true, ai, value, key: "key.valid" };
}

/* ------------------------------------------------------------------ key qualifiers
   URI Syntax 1.7, sections 4.4 (which AIs), 4.6 (formats) and 4.9 (order). The shapes (the qualifiers
   allowed together, and which are required) come from the server configuration (gs1.KEY_SHAPES). */
const QUAL_ORDER = ["22", "10", "21", "235", "8011", "254", "7040", "8020", "8019"];
const QCHARS = "[A-Za-z0-9._\\-]";
const QUAL_FORMATS = {
  "22": [new RegExp(`^${QCHARS}{1,20}$`), 20], "10": [new RegExp(`^${QCHARS}{1,20}$`), 20],
  "21": [new RegExp(`^${QCHARS}{1,20}$`), 20], "235": [new RegExp(`^${QCHARS}{1,28}$`), 28],
  "8011": [/^[1-9]\d{0,11}$/, 12], "254": [new RegExp(`^${QCHARS}{1,20}$`), 20],
  "7040": [/^\d[A-Za-z0-9._\-]{2}[A-Za-z0-9_\-]$/, 4], "8020": [new RegExp(`^${QCHARS}{1,25}$`), 25],
  "8019": [/^\d{1,10}$/, 10],
};

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
    input.maxLength = QUAL_FORMATS[q][1];
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
    if (!QUAL_FORMATS[q][0].test(value)) return { ok: false, error: true, key: "qualifier.invalid", params: { ai: q } };
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
  const order = q => QUAL_ORDER.indexOf(q);
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

function renderPreview() {
  const g = readKey();
  const l = readQualifiers();
  const host = CONFIG ? CONFIG.resolver : "";
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
                   attributes: attributes.map(([ai, value]) => ({ ai, value })) };
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
      I18N.set($("#qr-info"), "preview.qrInfo", {
        version: Number(response.headers.get("X-QR-Version")),
        modules: Number(response.headers.get("X-QR-Modules")),
        level: response.headers.get("X-QR-Level") || "",
      });
      setDownloads(labelQuery);
    } catch {
      if (seq === previewSeq) showQrError("error.network", {});
    }
  }, 250);
}

function setDownloads(labelQuery) {
  toggleLink($("#download-png"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=png` : null);
  toggleLink($("#download-svg"), labelQuery ? `${BASE}api/qrcode?${labelQuery}&format=svg` : null);
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
const LABEL_DEFAULTS = { hri: "full", version: "auto", ecl: "m" };

function labelOptionsQuery() {
  return new URLSearchParams({ hri: $("#opt-hri").value, version: $("#opt-version").value, ecl: $("#opt-ecl").value }).toString();
}

function setupLabelOptions() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(LABEL_OPTIONS_KEY) || "{}");
  } catch { /* defaults */ }
  if (typeof saved.hri === "boolean") saved.hri = saved.hri ? "full" : "none";   // earlier versions: on/off
  const fields = { hri: "#opt-hri", version: "#opt-version", ecl: "#opt-ecl" };
  for (const [name, selector] of Object.entries(fields)) {
    const select = $(selector);
    const value = saved[name] ?? LABEL_DEFAULTS[name];
    select.value = [...select.options].some(o => o.value === value) ? value : LABEL_DEFAULTS[name];
    select.addEventListener("change", () => {
      try {
        localStorage.setItem(LABEL_OPTIONS_KEY, JSON.stringify(
          Object.fromEntries(Object.entries(fields).map(([n, sel]) => [n, $(sel).value]))));
      } catch { /* not persisted */ }
      renderPreview();
    });
  }
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
  const numeric = ai === "01" || ai in NUMERIC_KEYS || ["8006", "255"].includes(ai);
  input.inputMode = numeric ? "numeric" : "text";
  // room for the spaces and hyphens people type between digit groups
  input.maxLength = ai === "01" ? 20 : numeric ? 34 : 40;
  buildQualifierFields();
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
  const box = $("#others");
  box.hidden = !othersState.entries.length;
  if (box.hidden) return;
  I18N.set($("#others-title"), "others.title", { count: othersState.entries.length, key: t(`key.${readKey().ai}.short`) });
  // Filter: every key qualifier present in the list
  const present = [...new Set(othersState.entries.flatMap(e => [...(e.qualifiers || []), ...(e.informative || [])].map(([q]) => q)))]
    .sort((a, b) => QUAL_ORDER.indexOf(a) - QUAL_ORDER.indexOf(b));
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
  const { key, description, links } = collect();
  const informative = splitInformative(key, readQualifiers().pairs || []).informative;
  return JSON.stringify({ description, links, informative });
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
  if (hasUnsavedChanges() && !confirm(t("others.confirmDiscard"))) return;
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
  if ((state.pendingUnsaved || hasUnsavedChanges()) && !confirm(t("others.confirmDiscard"))) return;
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
    if (record.links.length) record.links.forEach(addRow);
    else addRow({ linkType: record.sharedDefaultLinkType || "gs1:pip" });
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

function isRecordsView() { return location.hash === "#records"; }

const VIEWS = { "#records": "records", "#users": "users", "#audit": "audit" };

/* Shows the editor, the record list, the user administration or the audit trail, following the
   address (#records, #users, #audit), so the browser's back button and bookmarks work. */
function applyView() {
  let view = VIEWS[location.hash] || "editor";
  if ((view === "users" || view === "audit") && CONFIG && CONFIG.role !== "admin") view = "editor";
  $("#editor-view").hidden = view !== "editor";
  $("#records-view").hidden = view !== "records";
  $("#users-view").hidden = view !== "users";
  $("#audit-view").hidden = view !== "audit";
  const titles = { editor: "intro", records: "records", users: "users", audit: "audit" };
  I18N.set($("#hero-title"), `${titles[view]}.title`);
  I18N.set($("#hero-lede"), `${titles[view]}.lede`);
  const link = $("#hero-link");
  link.href = view === "editor" ? "#records" : "#";
  I18N.set(link, view === "editor" ? "records.link" : "records.back");
  if (view === "records") loadRecords();
  if (view === "users" && CONFIG) loadUsers();
  if (view === "audit" && CONFIG) loadAudit();
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

async function loadUsers() {
  const roleBox = $("#new-user-role");
  if (!roleBox.options.length) {
    const template = roleSelect("editor");
    roleBox.replaceChildren(...template.options);
    roleBox.value = "editor";
  }
  try {
    const { users } = await api("GET", "users");
    $("#users-body").replaceChildren(...users.map(userRow));
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
  const role = roleSelect(u.role);
  role.setAttribute("aria-label", t("users.role"));
  cell("users.role", role);
  const prefixes = document.createElement("input");
  prefixes.value = u.prefixes.join(", ");
  prefixes.setAttribute("aria-label", t("users.prefixes"));
  prefixes.placeholder = t("users.allPrefixes");
  cell("users.prefixes", prefixes);
  cell("users.state", t(u.disabled ? "users.disabled" : u.mustChange ? "users.mustChange" : "users.active"));
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
  button("users.save", () => saveUser(u.username, { role: role.value, prefixes: prefixesFrom(prefixes.value) }), "btn-secondary");
  if (u.username !== CONFIG.user) {                // your own password: user menu → Options
    button("users.resetPassword", () => resetUser(u.username));
    button(u.disabled ? "users.enable" : "users.disable", () => saveUser(u.username, { disabled: !u.disabled }));
    button("users.remove", () => removeUser(u.username), "btn-danger-ghost");
  }
  cell("users.actions", actions);
  return tr;
}

async function createUser(event) {
  event.preventDefault();
  $("#temp-password").hidden = true;
  try {
    const result = await api("POST", "users", {
      username: $("#new-user-name").value.trim(), role: $("#new-user-role").value,
      prefixes: prefixesFrom($("#new-user-prefixes").value),
    });
    usersStatus("ok", "users.created", result.params);
    showTemporaryPassword("users.tempPasswordNew", result.params.user, result.password);
    $("#users-create").reset();
    $("#new-user-role").value = "editor";
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

async function resetUser(username) {
  if (!confirm(t("users.confirmReset", { user: username }))) return;
  try {
    const result = await api("POST", `users/${encodeURIComponent(username)}/reset`, {});
    usersStatus("ok", result.code, result.params);
    showTemporaryPassword("users.tempPasswordReset", username, result.password);
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
}

async function removeUser(username) {
  if (!confirm(t("users.confirmRemove", { user: username }))) return;
  try {
    const result = await api("DELETE", "users/" + encodeURIComponent(username));
    usersStatus("ok", result.code, result.params);
    loadUsers();
  } catch (e) {
    usersStatus("error", e.code, e.params);
  }
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
      const values = [formatWhen(e.at), e.user, t("audit.action." + e.action),
                      e.anchor ? e.anchor + (e.qpath || "") : "", e.detail || ""];
      values.forEach((v, i) => {
        const td = document.createElement("td");
        if (i === 3) td.className = "code";
        td.textContent = v;
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
    ...QUAL_ORDER.filter(q => counts[q]).map(q => filterOption(q, t(`qual.${q}.label`), counts[q])),
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
function parseCode(text) {
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
  const words = code ? [] : fold(text).split(/\s+/).filter(Boolean);
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
  hint.hidden = !code;
  if (code) {
    hint.textContent = t("records.code", { code: codeText(code) })
      + (code.ignored.length ? " " + t("records.codeIgnored", { ais: code.ignored.map(q => `(${q})`).join(" ") }) : "");
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
    if (r.breaksRules) scope.append(document.createElement("br"), warnBadge("records.badge.rules", {}));
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

/* Background job shared by the record list (every record) and the import preview (a list of URLs). */
async function runLinkJob(body, onProgress) {
  const job = await api("POST", "links/jobs", body);
  onProgress(0, job.total);
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 800));
    const status = await api("GET", "links/jobs/" + job.token);
    if (status.state === "finished") return status;
    onProgress(status.done, status.total);
  }
}

async function checkAllLinks() {
  const button = $("#records-check");
  const msg = $("#records-check-msg");
  button.disabled = true;
  msg.className = "field-msg";
  try {
    const status = await runLinkJob({ scope: "all" }, (done, total) => I18N.set(msg, "records.checking", { done, total }));
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
      body: JSON.stringify({ format, labels: sheetLabels() }),
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
      (done, total) => I18N.set(msg, "import.linksChecking", { done, total }));
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
    importStatus(null, "import.running", { done: 0, total: started.total });
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
  if (status.state !== "finished") {
    importStatus(null, "import.running", { done: status.done, total: status.total });
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
function fillTypeSelect(select, value) {
  const groups = new Map();
  CONFIG.linkTypes.forEach(({ code, group }) => {
    if (!groups.has(group)) {
      const optgroup = document.createElement("optgroup");
      optgroup.dataset.i18nGroup = group;
      groups.set(group, optgroup);
      select.append(optgroup);
    }
    const option = new Option("", code);
    option.dataset.i18nType = code;
    groups.get(group).append(option);
  });
  if (value && !CONFIG.linkTypes.some(x => x.code === value)) {
    const option = new Option("", value);   // link type created outside the portal
    option.dataset.i18nType = value;
    select.append(option);
  }
  select.value = value || "gs1:pip";
}

function fillLanguageSelect(select, hreflang) {
  CONFIG.languages.forEach(code => {
    const option = new Option("", code);
    option.dataset.i18nLang = code;
    select.append(option);
  });
  if (hreflang.length > 1 || !CONFIG.languages.includes(hreflang[0])) {
    select.append(new Option(hreflang.join(", "), "__keep"));   // preserved as-is
    select.value = "__keep";
  } else {
    select.value = hreflang[0];
  }
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
  const languageSelect = $(".language", li);
  fillLanguageSelect(languageSelect, hreflang);
  li.dataset.hreflang = JSON.stringify(hreflang);
  li.dataset.context = JSON.stringify(data.context || []);

  $(".url", li).value = data.url || "";
  $(".title", li).value = data.title || "";

  typeSelect.addEventListener("change", () => { refreshRowHelp(li); refreshDefault(); });
  languageSelect.addEventListener("change", () => {
    if (languageSelect.value !== "__keep") li.dataset.hreflang = JSON.stringify([languageSelect.value]);
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

/* The first target is the default link (gs1:defaultLink). When other records share the GTIN
   (product/batches), the default link type is shared and must be kept. */
function refreshDefault() {
  const msg = $("#default-msg");
  const first = $("#links .link-row .link-type");
  if (!first || !state.sharedDefaultLinkType) {
    I18N.set(msg, null);
    msg.className = "field-msg";
    return;
  }
  const mismatch = first.value !== state.sharedDefaultLinkType;
  I18N.set(msg, mismatch ? "default.sharedLocal" : "default.shared", { linkType: state.sharedDefaultLinkType });
  msg.className = "field-msg" + (mismatch ? " is-error" : "");
}

function collect() {
  const g = readKey(), l = readQualifiers();
  return {
    key: g.ai,
    value: g.value,
    qualifiers: Object.fromEntries(l.pairs || []),
    description: $("#description").value,
    defaultLinkType: $("#links .link-row .link-type").value,
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
  if (!confirm(t("delete.confirm", { target }))) return;
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
  $("#menu-options").addEventListener("click", () => { close(false); openOptions(); });
  ["#menu-records", "#menu-users", "#menu-audit"].forEach(sel => $(sel).addEventListener("click", () => close(false)));
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

function setupOptions() {
  const dialog = $("#options-dialog");
  $("#options-close").addEventListener("click", () => dialog.close());
  $("#password-cancel").addEventListener("click", () => dialog.close());
  $("#password-form").addEventListener("submit", changePassword);
  dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });   // click on the backdrop
}

/* ------------------------------------------------------------------ language menu */
function buildLocaleMenu() {
  const select = $("#locale");
  select.replaceChildren(...I18N.SUPPORTED.map(loc => new Option(I18N.nameOf(loc), loc)));
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
  $("#copy-from").addEventListener("click", openCopy);
  $("#copy-cancel").addEventListener("click", closeCopy);
  $("#copy-search").addEventListener("input", drawCopyList);
  $("#copy-append").addEventListener("click", () => copyTargets(false));
  $("#copy-replace").addEventListener("click", () => copyTargets(true));
  $("#copy-pop").addEventListener("keydown", e => { if (e.key === "Escape") { closeCopy(); $("#copy-from").focus(); } });
  $("#records-state").addEventListener("change", renderRecords);
  $("#records-alert-show").addEventListener("click", () => { $("#records-state").value = "nokey"; renderRecords(); });
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
  $("#temp-password-copy").addEventListener("click", () => navigator.clipboard?.writeText($("#temp-password-value").textContent));
  $("#audit-filters").addEventListener("submit", loadAudit);
  $("#audit-csv").addEventListener("click", downloadAudit);
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
  setupAttributes();
  fillKeyTypes();
  onKeyTypeChange();
  applyView();                                   // administrator views need the role
  if (CONFIG.mustChange) openOptions(true);
  $("#user-name").textContent = CONFIG.user;
  $("#password-username").value = CONFIG.user;   // lets password managers pair the new password with the account
  onIdentityChange();
}

init();
