"use strict";

/* Sign-in page: posts the credentials as JSON and moves on to the portal. With e-mail on, it also offers password
   recovery and handles the single-use links of invitations and recovery messages (#invite=… or #reset=…), whose
   token is in the fragment of the address so that it never reaches a server log
   (Documentation/adr/0004-e-mail.md). */
const $ = sel => document.querySelector(sel);
const FORMS = ["#login-form", "#forgot-form", "#link-form", "#sso-form"];
let linkToken = null;
let minLength = 12;

function showStatus(kind, code, params, box = "#login-status") {
  const el = $(box);
  el.className = "status is-" + kind;
  I18N.set(el, code, params);
  el.hidden = false;
}

function showForm(id) {
  FORMS.forEach(sel => { $(sel).hidden = sel !== id; });
  FORMS.filter(sel => sel !== "#login-form").forEach(sel => { $(sel.replace("-form", "-status")).hidden = true; });
}

function buildLocaleMenu() {
  const select = $("#locale");
  select.replaceChildren(...I18N.SUPPORTED.map(loc => new Option(I18N.nameOf(loc), loc)));
  select.value = I18N.locale;
  select.addEventListener("change", () => I18N.setLocale(select.value));
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return { res, data: await res.json().catch(() => ({})) };
}

/* Runs a request with its button disabled and labelled as working; restores the button afterwards. */
async function busy(button, workingKey, idleKey, action) {
  button.disabled = true;
  I18N.set(button, workingKey);
  try {
    return await action();
  } finally {
    button.disabled = false;
    I18N.set(button, idleKey);
  }
}

async function signIn(event) {
  event.preventDefault();
  const username = $("#username").value.trim();
  const password = $("#password").value;
  if (!username || !password) {
    showStatus("error", "login.missing");
    (username ? $("#password") : $("#username")).focus();
    return;
  }
  try {
    const { res, data } = await busy($("#login-submit"), "login.submitting", "login.submit",
                                     () => post("api/login", { username, password, language: I18N.locale }));
    if (res.ok) {
      location.replace("./#overview");
      return;
    }
    showStatus("error", data.code || "error.unexpected", data.params || { status: res.status });
    $("#password").value = "";
    $("#password").focus();
  } catch {
    showStatus("error", "error.network");
  }
}

/* ------------------------------------------------------------------ password recovery */
async function loginOptions() {
  try {
    const res = await fetch("api/login/options", { credentials: "same-origin", headers: { Accept: "application/json" } });
    return await res.json();
  } catch {
    return {};
  }
}

/* ------------------------------------------------------------------ single sign-on (ADR 0012) */
function openSso() {
  showForm("#sso-form");
  const typed = $("#username").value.trim();
  if (typed.includes("@")) $("#sso-email").value = typed;
  $("#sso-email").focus();
}

async function ssoStart(event) {
  event.preventDefault();
  const email = $("#sso-email").value.trim();
  if (!email.includes("@")) {
    showStatus("error", "sso.emailInvalid", null, "#sso-status");
    $("#sso-email").focus();
    return;
  }
  try {
    const { res, data } = await busy($("#sso-submit"), "login.ssoGoing", "login.ssoSubmit",
                                     () => post("api/sso/start", { email, language: I18N.locale }));
    if (res.ok && data.url) {
      location.assign(data.url);
      return;
    }
    showStatus("error", data.code || "error.unexpected", data.params || { status: res.status }, "#sso-status");
  } catch {
    showStatus("error", "error.network", null, "#sso-status");
  }
}

function openForgot() {
  showForm("#forgot-form");
  $("#forgot-login").value = $("#username").value.trim();
  $("#forgot-login").focus();
}

async function forgot(event) {
  event.preventDefault();
  const login = $("#forgot-login").value.trim();
  if (!login) {
    showStatus("error", "password.recoveryMissing", null, "#forgot-status");
    $("#forgot-login").focus();
    return;
  }
  try {
    const { res, data } = await busy($("#forgot-submit"), "login.sending", "login.forgotSubmit",
                                     () => post("api/password/forgot", { login, language: I18N.locale }));
    showStatus(res.ok ? "ok" : "error", data.code || "error.unexpected", data.params || { status: res.status }, "#forgot-status");
  } catch {
    showStatus("error", "error.network", null, "#forgot-status");
  }
}

/* ------------------------------------------------------------------ invitation and recovery links */
function backToSignIn() {
  showForm("#login-form");
  $("#username").focus();
}

async function openLink(purpose, token) {
  linkToken = token;
  // The token leaves the address bar (and the history) at once; it stays only in this page's memory.
  history.replaceState(null, "", location.pathname + location.search);
  showForm("#link-form");
  const title = purpose === "invite" ? "login.linkTitleInvite" : "login.linkTitleReset";
  I18N.set($("#link-title"), title);
  try {
    const { res, data } = await post("api/password/link/check", { token });
    if (!res.ok) {
      showStatus("error", data.code || "error.unexpected", data.params || { status: res.status }, "#link-status");
      return;
    }
    minLength = data.min || minLength;
    I18N.set($("#link-title"), data.purpose === "invite" ? "login.linkTitleInvite" : "login.linkTitleReset");
    I18N.set($("#link-lede"), data.purpose === "invite" ? "login.linkLedeInvite" : "login.linkLedeReset");
    I18N.set($("#link-hint"), "login.linkHint", { min: minLength });
    $("#link-user").textContent = data.user;
    $("#link-username").value = data.user;       // lets password managers pair the new password with the account
    $("#link-fields").hidden = false;
    $("#link-password").focus();
  } catch {
    showStatus("error", "error.network", null, "#link-status");
  }
}

async function setPassword(event) {
  event.preventDefault();
  const password = $("#link-password").value;
  if (password.length < minLength) return showStatus("error", "password.tooShort", { min: minLength }, "#link-status");
  if (password !== $("#link-confirm").value) return showStatus("error", "password.mismatch", null, "#link-status");
  try {
    const { res, data } = await busy($("#link-submit"), "login.submitting", "login.linkSubmit",
                                     () => post("api/password/link", { token: linkToken, newPassword: password,
                                                                       language: I18N.locale }));
    if (!res.ok) {
      showStatus("error", data.code || "error.unexpected", data.params || { status: res.status }, "#link-status");
      if (data.code === "password.linkInvalid") $("#link-fields").hidden = true;
      return;
    }
    linkToken = null;
    $("#link-form").reset();
    showForm("#login-form");
    showStatus("ok", "password.set");
    $("#username").value = data.user || $("#link-username").value;
    $("#password").focus();
  } catch {
    showStatus("error", "error.network", null, "#link-status");
  }
}

/* ------------------------------------------------------------------ start */
buildLocaleMenu();
I18N.apply();
const reason = new URLSearchParams(location.search).get("reason");
if (reason === "expired") showStatus("error", "login.expired");
if (reason === "signedOut") showStatus("ok", "login.signedOut");
if (reason === "passwordChanged") showStatus("ok", "login.passwordChanged");
const ssoReason = new URLSearchParams(location.search).get("sso");   // the provider's round trip ended here
if (ssoReason && /^[A-Za-z]+$/.test(ssoReason)) showStatus("error", "sso." + ssoReason);
$("#login-form").addEventListener("submit", signIn);
$("#forgot-form").addEventListener("submit", forgot);
$("#link-form").addEventListener("submit", setPassword);
$("#forgot-open").addEventListener("click", openForgot);
$("#forgot-back").addEventListener("click", backToSignIn);
$("#link-back").addEventListener("click", backToSignIn);
$("#sso-open").addEventListener("click", openSso);
$("#sso-back").addEventListener("click", backToSignIn);
$("#sso-form").addEventListener("submit", ssoStart);
const LINK = /^#(invite|reset)=([A-Za-z0-9_-]{20,100})$/;
const link = LINK.exec(location.hash);
if (link) openLink(link[1], link[2]);
else $("#username").focus();
// A link pasted into the address bar of this page changes only the fragment: the page is not loaded again.
window.addEventListener("hashchange", () => {
  const pasted = LINK.exec(location.hash);
  if (pasted) {
    $("#link-form").reset();
    $("#link-fields").hidden = true;
    openLink(pasted[1], pasted[2]);
  }
});
loginOptions().then(options => {
  const offered = Boolean(options.passwordRecovery);
  $("#forgot-open").hidden = !offered;
  $("#sso-open").hidden = !options.sso;
  I18N.set($("#login-help"), offered ? "login.helpRecovery" : "login.help");
});
