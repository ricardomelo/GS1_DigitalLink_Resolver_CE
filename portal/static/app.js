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
