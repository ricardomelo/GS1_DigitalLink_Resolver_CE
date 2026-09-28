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

function readGtin() {
  const digits = $("#gtin").value.replace(/[\s.\-]/g, "");
  if (!digits) return { ok: false, key: "gtin.hint" };
  if (!/^\d+$/.test(digits)) return { ok: false, error: true, key: "gtin.digitsOnly" };
  if (![8, 12, 13, 14].includes(digits.length)) {
    return { ok: false, key: "gtin.typedLength", params: { length: digits.length } };
  }
  const expected = checkDigit(digits.slice(0, -1));
  if (Number(digits.at(-1)) !== expected) {
    return { ok: false, error: true, key: "gtin.checkDigit", params: { expected } };
  }
  if (digits.length === 13 && digits[0] === "2") return { ok: false, error: true, key: "gtin.restricted" };
  return { ok: true, gtin14: digits.padStart(14, "0"), key: "gtin.valid" };
}

function readLot() {
  if (!$('input[name="scope"][value="lot"]').checked) return { ok: true, lot: null };
  const lot = $("#lot").value.trim();
  if (!lot) return { ok: false, key: "lot.required" };
  if (!/^[A-Za-z0-9._\-]{1,20}$/.test(lot)) return { ok: false, error: true, key: "lot.invalid" };
  return { ok: true, lot };
}

function query(g, l) {
  const params = new URLSearchParams({ gtin: g.gtin14 });
  if (l.lot) params.set("lot", l.lot);
  return params.toString();
}

/* ------------------------------------------------------------------ label preview */
let qrTimer = null;

function renderPreview() {
  const g = readGtin();
  const l = readLot();
  const host = CONFIG ? CONFIG.resolver : "";
  const gtin = g.ok ? g.gtin14 : "______________";
  const lot = l.lot || null;

  const dl = $("#dl");
  dl.replaceChildren();
  const segment = (cls, text) => {
    const span = document.createElement("span");
    span.className = cls;
    span.textContent = text;
    dl.append(span);
  };
  segment("seg-host", host);
  segment("seg-key", `/01/${gtin}`);
  if (lot) segment("seg-qual", `/10/${encodeURIComponent(lot)}`);
  $("#legend-lot").hidden = !lot;

  const ready = g.ok && l.ok;
  const uri = ready ? `${host}/01/${g.gtin14}` + (lot ? `/10/${encodeURIComponent(lot)}` : "") : "";
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

/* Label options: human readable interpretation (default on) and GS1® branding (pilot, default off).
   The preview image is the exported label itself, so what is shown is what is downloaded. */
const LABEL_OPTIONS_KEY = "gs1resolver.portal.labelOptions";

function labelOptionsQuery() {
  return `hri=${$("#opt-hri").checked ? 1 : 0}&brand=${$("#opt-brand").checked ? 1 : 0}`;
}

function setupLabelOptions() {
  try {
    const saved = JSON.parse(localStorage.getItem(LABEL_OPTIONS_KEY) || "{}");
    if (typeof saved.hri === "boolean") $("#opt-hri").checked = saved.hri;
    if (typeof saved.brand === "boolean") $("#opt-brand").checked = saved.brand;
  } catch { /* defaults */ }
  ["#opt-hri", "#opt-brand"].forEach(sel => $(sel).addEventListener("change", () => {
    try {
      localStorage.setItem(LABEL_OPTIONS_KEY, JSON.stringify({ hri: $("#opt-hri").checked, brand: $("#opt-brand").checked }));
    } catch { /* not persisted */ }
    renderPreview();
  }));
}

function toggleLink(a, href) {
  if (href) { a.href = href; a.removeAttribute("aria-disabled"); }
  else { a.removeAttribute("href"); a.setAttribute("aria-disabled", "true"); }
}

/* ------------------------------------------------------------------ step 1: identify the product */
function onIdentityChange() {
  const g = readGtin();
  const l = readLot();
  const gtinMsg = $("#gtin-msg");
  I18N.set(gtinMsg, g.key, g.params);
  gtinMsg.className = "field-msg" + (g.error ? " is-error" : g.ok ? " is-ok" : "");
  const lotMsg = $("#lot-msg");
  I18N.set(lotMsg, l.error ? l.key : "lot.hint");
  lotMsg.className = "field-msg" + (l.error ? " is-error" : "");

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
  const g = readGtin(), l = readLot();
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

/* Shows the editor or the record list, following the address (#records), so the browser's
   back button and bookmarks work. */
function applyView() {
  const list = isRecordsView();
  $("#editor-view").hidden = list;
  $("#records-view").hidden = !list;
  I18N.set($("#hero-title"), list ? "records.title" : "intro.title");
  I18N.set($("#hero-lede"), list ? "records.lede" : "intro.lede");
  const link = $("#hero-link");
  link.href = list ? "#" : "#records";
  I18N.set(link, list ? "records.back" : "records.link");
  if (list) loadRecords();
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

function scopeText(r) {
  if (r.kind === "lot") return t("records.scope.lot", { value: r.lot });
  if (r.kind === "other") {
    let value = r.qualifiers;
    try { value = Object.entries(JSON.parse(r.qualifiers)).map(([ai, v]) => `(${ai}) ${v}`).join(" "); } catch { /* as sent */ }
    return t("records.scope.other", { value });
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
      const haystack = fold([r.gtin, r.gtin.replace(/^0+/, ""), r.description, r.lot, r.qualifiers].join(" "));
      return words.every(w => haystack.includes(w));
    })
    // Most recently changed first; records without portal history after, by GTIN.
    .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "") || a.gtin.localeCompare(b.gtin)
                    || (a.lot || "").localeCompare(b.lot || ""));

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
      // Created by another tool with qualifiers the portal does not edit (e.g. serial numbers).
      name = document.createElement("span");
      name.textContent = r.description || r.gtin;
      name.title = t("records.otherHint");
    } else {
      name = document.createElement("a");
      name.href = "#";
      name.textContent = r.description || t("records.noDescription");
      name.addEventListener("click", e => { e.preventDefault(); openFromList(r); });
    }
    cell("records.col.product", name);
    cell("records.col.gtin", r.gtin, "code");
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
  $("#gtin").value = r.gtin;
  $(`input[name="scope"][value="${r.kind === "lot" ? "lot" : "product"}"]`).checked = true;
  $("#lot-wrap").hidden = r.kind !== "lot";
  $("#lot").value = r.lot || "";
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
  return linkCheck.last?.records?.[`${r.gtin}|${r.lot || ""}`] || [];
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
const SHEET_COLUMNS = ["gtin", "lot", "description", "linkType", "url", "language", "title", "default", "forward"];
const MAX_IMPORT_BYTES = 700 * 1024;
const importState = { token: null, polling: null, imported: false };

/* Texts the server writes into the file (it is language-neutral): headers in the current language,
   and, for imports, every accepted spelling of each header and of yes/no. */
function sheetLabels() {
  const headers = {}, aliases = {};
  SHEET_COLUMNS.forEach(c => { headers[c] = t("sheet.col." + c); aliases[c] = I18N.every("sheet.col." + c); });
  const linkTypes = {};
  (CONFIG?.linkTypes || []).forEach(({ code }) => { linkTypes[code] = I18N.linkType(code); });
  const languages = {};
  (CONFIG?.languages || []).forEach(code => { languages[code] = I18N.languageName(code); });
  return {
    headers, aliases, linkTypes, languages,
    yes: t("sheet.yes"), no: t("sheet.no"),
    yesWords: I18N.every("sheet.yes"), noWords: I18N.every("sheet.no"),
    sheets: { links: t("sheet.links"), linkTypes: t("sheet.linkTypes"), languages: t("sheet.languages") },
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

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new ApiError("import.unreadable"));
    reader.readAsDataURL(file);
  });
}

function scopeOf(item) {
  return item.lot ? t("records.scope.lot", { value: item.lot }) : t("records.scope.product");
}

async function previewImport() {
  const file = $("#import-file").files[0];
  $("#import-report").hidden = true;
  $("#import-apply").disabled = true;
  if (!file) return;
  if (file.size > MAX_IMPORT_BYTES) {
    importStatus("error", "import.tooBig", { max: MAX_IMPORT_BYTES / 1024 });
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
  $("#import-body").replaceChildren(...report.records.map(item => importRow(item.rows, item.gtin, scopeOf(item),
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
  $("#import-body").replaceChildren(...status.results.map(r => importRow(r.rows, r.gtin,
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
  const g = readGtin(), l = readLot();
  return {
    gtin: g.gtin14,
    lot: l.lot,
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
  const g = readGtin(), l = readLot();
  const target = l.lot
    ? t("delete.targetLot", { lot: l.lot, gtin: g.gtin14 })
    : t("delete.targetGtin", { gtin: g.gtin14 });
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
  $("#menu-records").addEventListener("click", () => close(false));   // the link itself changes the view
  $("#menu-logout").addEventListener("click", signOut);
}

async function signOut() {
  try { await api("POST", "logout", {}); } catch { /* signed out locally anyway */ }
  location.replace("login?reason=signedOut");
}

/* ------------------------------------------------------------------ options: change password */
function openOptions() {
  const form = $("#password-form");
  form.reset();
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
  $("#gtin").addEventListener("input", onIdentityChange);
  $("#lot").addEventListener("input", onIdentityChange);
  document.querySelectorAll('input[name="scope"]').forEach(radio => radio.addEventListener("change", () => {
    $("#lot-wrap").hidden = !$('input[name="scope"][value="lot"]').checked;
    onIdentityChange();
  }));
  $("#gtin").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); openRecord(); } });
  $("#lot").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); openRecord(); } });
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
    $("#gtin").focus();
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
  $("#user-name").textContent = CONFIG.user;
  $("#password-username").value = CONFIG.user;   // lets password managers pair the new password with the account
  onIdentityChange();
}

init();
