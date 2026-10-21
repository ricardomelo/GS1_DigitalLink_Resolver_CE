"use strict";

/*
 * The installation's privacy notice (Documentation/adr/0017-privacy-notice.md).
 *
 * PrivacyText.render(box, text, values) turns the notice's plain text into elements — paragraphs split by blank lines,
 * "# " headings, "- " list items, addresses as links, {operator} and {days} replaced — with textContent only, never
 * markup, so a notice cannot carry a script. The administrators' screen of the portal uses it for its preview.
 *
 * On the public page (privacy.html, body[data-page="privacy"]) it shows the version in force, or the one of
 * ?version=n, or the default notice of the catalogues in the reader's language, with the list of versions.
 */
const PrivacyText = (() => {
  const URL_PATTERN = /https?:\/\/[^\s<>"]+[^\s<>".,;:!?)]/g;

  function inline(parent, text) {
    let last = 0;
    for (const match of text.matchAll(URL_PATTERN)) {
      parent.append(document.createTextNode(text.slice(last, match.index)));
      const a = document.createElement("a");
      a.href = match[0];
      a.rel = "noopener noreferrer";
      a.textContent = match[0];
      parent.append(a);
      last = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }

  function fill(text, values) {
    return text.replace(/\{(operator|days)\}/g, (all, name) => values[name] ?? all);
  }

  function render(box, text, values = {}) {
    box.replaceChildren();
    for (const block of fill(String(text || ""), values).replace(/\r\n?/g, "\n").split(/\n\s*\n/)) {
      const lines = block.split("\n").filter(line => line.trim());
      if (!lines.length) continue;
      if (lines.every(line => /^\s*-\s+/.test(line))) {
        const ul = document.createElement("ul");
        lines.forEach(line => { const li = document.createElement("li"); inline(li, line.replace(/^\s*-\s+/, "")); ul.append(li); });
        box.append(ul);
      } else if (lines.length === 1 && /^#\s+/.test(lines[0])) {
        const h = document.createElement(box.childElementCount ? "h3" : "h2");
        h.textContent = lines[0].replace(/^#\s+/, "");
        box.append(h);
      } else {
        const p = document.createElement("p");
        lines.forEach((line, i) => { if (i) p.append(document.createElement("br")); inline(p, line); });
        box.append(p);
      }
    }
  }

  return { render, fill };
})();

/* The public page */
(() => {
  if (document.body.dataset.page !== "privacy") return;
  const $ = s => document.querySelector(s);
  const asked = new URLSearchParams(location.search).get("version");
  let data = null;

  function when(iso) {
    return iso ? new Date(iso).toLocaleDateString(I18N.locale, { year: "numeric", month: "long", day: "numeric" }) : "";
  }

  function show() {
    if (!data) return;
    const values = { operator: data.operator || "—", days: String(data.days ?? "") };
    const shown = data.notice;
    PrivacyText.render($("#privacy-body"), shown ? shown.text : I18N.t("privacy.default"), values);
    I18N.set($("#privacy-version"), shown ? "privacy.versionOf" : "privacy.defaultLabel",
             shown ? { version: shown.version, when: when(shown.at) } : {});
    const older = shown && data.current && shown.version !== data.current;
    $("#privacy-older").hidden = !older;
    $("#privacy-history-box").hidden = !data.versions.length;
    $("#privacy-history").replaceChildren(...data.versions.map(v => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `?version=${v.version}`;
      a.textContent = I18N.t("privacy.versionOf", { version: v.version, when: when(v.at) });
      if (shown && v.version === shown.version) a.setAttribute("aria-current", "page");
      li.append(a);
      if (v.note) li.append(document.createTextNode(` — ${v.note}`));
      return li;
    }));
  }

  async function load() {
    const answer = await fetch("api/privacy" + (asked ? `?version=${encodeURIComponent(asked)}` : ""),
                               { credentials: "same-origin", headers: { Accept: "application/json" } });
    const body = await answer.json().catch(() => ({}));
    if (!answer.ok) {
      $("#privacy-status").hidden = false;
      I18N.set($("#privacy-status"), body.code || "error.unexpected", body.params || { status: answer.status });
      return;
    }
    data = body;
    show();
  }

  function buildLocaleMenu() {
    const select = $("#locale");
    select.replaceChildren(...I18N.MENU.map(loc => new Option(I18N.nameOf(loc), loc)));
    select.value = I18N.locale;
    select.addEventListener("change", () => I18N.setLocale(select.value));
  }

  I18N.ready.then(() => {
    I18N.apply();
    buildLocaleMenu();
    load();
  });
  document.addEventListener("localechange", () => { $("#locale").value = I18N.locale; show(); });
})();
