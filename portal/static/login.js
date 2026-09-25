"use strict";

/* Sign-in page: posts the credentials as JSON and moves on to the portal. */
const $ = sel => document.querySelector(sel);

function showStatus(kind, code, params) {
  const el = $("#login-status");
  el.className = "status is-" + kind;
  I18N.set(el, code, params);
  el.hidden = false;
}

function buildLocaleMenu() {
  const select = $("#locale");
  select.replaceChildren(...I18N.SUPPORTED.map(loc => new Option(I18N.nameOf(loc), loc)));
  select.value = I18N.locale;
  select.addEventListener("change", () => I18N.setLocale(select.value));
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
  const button = $("#login-submit");
  button.disabled = true;
  I18N.set(button, "login.submitting");
  try {
    const res = await fetch("api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      location.replace("./");
      return;
    }
    showStatus("error", data.code || "error.unexpected", data.params || { status: res.status });
    $("#password").value = "";
    $("#password").focus();
  } catch {
    showStatus("error", "error.network");
  } finally {
    button.disabled = false;
    I18N.set(button, "login.submit");
  }
}

buildLocaleMenu();
I18N.apply();
const reason = new URLSearchParams(location.search).get("reason");
if (reason === "expired") showStatus("error", "login.expired");
if (reason === "signedOut") showStatus("ok", "login.signedOut");
if (reason === "passwordChanged") showStatus("ok", "login.passwordChanged");
$("#login-form").addEventListener("submit", signIn);
$("#username").focus();
