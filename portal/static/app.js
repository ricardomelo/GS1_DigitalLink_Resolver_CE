"use strict";

/* Base path of the portal (e.g. "/portal/"), so it works behind any prefix. */
const BASE = location.pathname.replace(/[^/]*$/, "");
const $ = (sel, root = document) => root.querySelector(sel);
const { t } = I18N;

let CONFIG = null;
const state = {
  openKey: null,               // query string of the record currently open for editing
  exists: false,
  sharedDefaultLinkType: null, // set when other records on the same GTIN fix the default link type
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
    label.append(name, " ", note);
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

function query(g, qual) {
  const params = new URLSearchParams({ key: g.ai, value: g.value });
  if (qual.pairs?.length) params.set("qualifiers", qual.pairs.map(([q, v]) => `/${q}/${v}`).join(""));
  return params.toString();
}

/* ------------------------------------------------------------------ label preview */
let qrTimer = null;

function renderPreview() {
  const g = readKey();
  const l = readQualifiers();
  const host = CONFIG ? CONFIG.resolver : "";
  const shown = g.ok ? g.value : "______________";
  const pairs = l.ok ? l.pairs : [];

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
  pairs.forEach(([q, v]) => segment("seg-qual", `/${q}/${encodeURIComponent(v)}`));
  $("#legend-lot").hidden = pairs.length === 0;

  const ready = g.ok && l.ok;
  const uri = ready ? `${host}/${g.ai}/${g.value}` + qualifierPath(pairs) : "";
  toggleLink($("#test"), ready ? uri : null);
  const labelQuery = `${query(g, l)}&${labelOptionsQuery()}`;
  toggleLink($("#download-png"), ready ? `${BASE}api/qrcode?${labelQuery}&format=png` : null);
  toggleLink($("#download-svg"), ready ? `${BASE}api/qrcode?${labelQuery}&format=svg` : null);
  if (ready) dl.href = uri; else dl.removeAttribute("href");
  $("#copy").disabled = !ready;
  $("#copy").dataset.uri = uri;

  clearTimeout(qrTimer);
  qrTimer = setTimeout(() => {
    const box = $("#qr");
    if (!ready) {
      const span = document.createElement("span");
      I18N.set(span, "preview.qrPlaceholder");
      box.replaceChildren(span);
      return;
    }
    const img = new Image();
    img.alt = t("preview.qrAlt", { uri });
    img.src = `${BASE}api/qrcode?${labelQuery}`;
    img.onload = () => box.replaceChildren(img);
  }, 250);
}

/* Label option: human readable interpretation (default on).
   The preview image is the exported label itself, so what is shown is what is downloaded. */
const LABEL_OPTIONS_KEY = "gs1resolver.portal.labelOptions";

function labelOptionsQuery() {
  return `hri=${$("#opt-hri").checked ? 1 : 0}`;
}

function setupLabelOptions() {
  try {
    const saved = JSON.parse(localStorage.getItem(LABEL_OPTIONS_KEY) || "{}");
    if (typeof saved.hri === "boolean") $("#opt-hri").checked = saved.hri;
  } catch { /* defaults */ }
  $("#opt-hri").addEventListener("change", () => {
    try {
      localStorage.setItem(LABEL_OPTIONS_KEY, JSON.stringify({ hri: $("#opt-hri").checked }));
    } catch { /* not persisted */ }
    renderPreview();
  });
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
  const key = g.ok && l.ok ? query(g, l) : null;
  if (state.openKey && key !== state.openKey) {
    state.openKey = null;
    $("#editor").disabled = true;
    setOpenMessage("open.changed");
  }
  renderPreview();
}

/* The open message may have a second sentence listing other records on the same GTIN. */
function setOpenMessage(key, params, otherEntries = []) {
  const box = $("#open-msg");
  const main = document.createElement("span");
  I18N.set(main, key, params);
  const parts = [main];
  if (otherEntries.length) {
    const extra = document.createElement("span");
    I18N.set(extra, "open.others", { entries: otherEntries });
    parts.push(" ", extra);
  }
  box.replaceChildren(...parts);
}

async function openRecord() {
  const g = readKey(), l = readQualifiers();
  if (!CONFIG || !g.ok || !l.ok) return;
  const button = $("#open");
  button.disabled = true;
  setOpenMessage("open.loading");
  hideStatus();
  try {
    const record = await api("GET", "record?" + query(g, l));
    state.openKey = query(g, l);
    state.exists = record.exists;
    state.sharedDefaultLinkType = record.sharedDefaultLinkType;
    $("#description").value = record.description || "";
    $("#links").replaceChildren();
    if (record.links.length) record.links.forEach(addRow);
    else addRow({ linkType: record.sharedDefaultLinkType || "gs1:pip" });
    refreshDefault();

    setOpenMessage(record.exists ? "open.found" : "open.new", {}, record.otherEntries);
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
                              context: l.context || [], forwardQueryString: l.fwqs !== false }));
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

async function loadRecords() {
  I18N.set($("#records-count"), "records.loading");
  $("#records-body").replaceChildren();
  $("#records-empty").hidden = true;
  try {
    const data = await api("GET", "records");
    records.all = data.records || [];
    records.loaded = true;
    fillUserFilter();
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

/* Case- and accent-insensitive text for searching ("Açaí" matches "acai"). */
function fold(text) {
  return String(text || "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

/* "(01) 07898357410015": the AI in brackets, as in the human readable interpretation. */
function keyText(ai, value) {
  return `(${ai}) ${value}`;
}

function scopeText(r) {
  if (r.kind === "qualified") return qualText(r.qualifiers);
  if (r.kind !== "other" && r.key !== "01") return t("records.scope.key", { name: t(`key.${r.key}.short`) });
  if (r.kind === "other") {
    return t("records.scope.other", { value: r.other });
  }
  return t("records.scope.product");
}

function changedText(r) {
  if (!r.updatedAt) return null;
  const when = new Date(r.updatedAt);
  return new Intl.DateTimeFormat(I18N.locale, { dateStyle: "short", timeStyle: "short" }).format(when);
}

function renderRecords() {
  if (!records.loaded) return;
  const words = fold($("#records-search").value).split(/\s+/).filter(Boolean);
  const user = $("#records-user").value;
  const problemsOnly = $("#records-problems").checked;
  const shown = records.all
    .filter(r => !user || r.updatedBy === user)
    .filter(r => !problemsOnly || problemsOf(r).length > 0)
    .filter(r => {
      if (!words.length) return true;
      const haystack = fold([r.value, r.value.replace(/^0+/, ""), r.key, t(`key.${r.key}.short`), r.description,
                             (r.qualifiers || []).map(p => p[1]).join(" "), qualText(r.qualifiers), r.other].join(" "));
      return words.every(w => haystack.includes(w));
    })
    // Most recently changed first; records without portal history after, by GTIN.
    .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "") || a.anchor.localeCompare(b.anchor)
                    || (a.qpath || "").localeCompare(b.qpath || ""));

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
    cell("records.col.product", name);
    cell("records.col.key", keyText(r.key, r.value), "code");
    cell("records.col.scope", scopeText(r));
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
  if (item.qualifiers?.length) return qualText(item.qualifiers);
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
  $("#import-body").replaceChildren(...report.records.map(item => importRow(item.rows, keyText(item.key || "01", item.value), scopeOf(item),
    item.description, item.action)));
  $("#import-report").hidden = false;
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
    const started = await api("POST", "import/apply", { token: importState.token });
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
  $(".forward", li).checked = data.forwardQueryString !== false;

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
      forwardQueryString: $(".forward", li).checked,
    })),
  };
}

/* ------------------------------------------------------------------ save / delete */
async function save(event) {
  event.preventDefault();
  if (!state.openKey) return;
  const button = $("#save");
  button.disabled = true;
  I18N.set(button, "save.saving");
  hideStatus();
  try {
    const result = await api("POST", "record", collect());
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

async function remove() {
  const g = readKey(), l = readQualifiers();
  const target = l.pairs?.length
    ? t("delete.targetQualified", { qualifiers: qualText(l.pairs), key: keyText(g.ai, g.value) })
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
  $("#add").addEventListener("click", () => $(".url", addRow()).focus());
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
  $("#records-new").addEventListener("click", e => {
    e.preventDefault();
    history.pushState(null, "", location.pathname + location.search);
    applyView();
    $("#key-value").focus();
  });
  window.addEventListener("hashchange", applyView);
  document.addEventListener("localechange", renderRecords);   // dates and scope texts follow the language
  applyView();

  try {
    CONFIG = await api("GET", "config");
  } catch (e) {
    showStatus("error", "error.config", { detail: t(e.code, e.params) });
    return;
  }
  document.body.dataset.role = CONFIG.role;
  fillKeyTypes();
  onKeyTypeChange();
  applyView();                                   // administrator views need the role
  if (CONFIG.mustChange) openOptions(true);
  $("#user-name").textContent = CONFIG.user;
  $("#password-username").value = CONFIG.user;   // lets password managers pair the new password with the account
  onIdentityChange();
}

init();
