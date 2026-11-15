"use strict";

/*
 * The About page (about.html, Documentation/adr/0024-name-and-about.md): drawn from GET api/about — the version written
 * at the image's build, the repository, the operator's name and the third-party components of portal/third_party.json.
 * The documents are linked at the running commit, so the manual matches the software; without a known commit, on the
 * repository's default branch. Every value goes in with textContent or as a checked https address, never as markup.
 */
(() => {
  const $ = s => document.querySelector(s);
  const DOCS = [["about.docs.guide", "Documentation/portal-user-guide.md"], ["about.docs.readme", "README.md"],
                ["about.docs.developer", "Documentation/developer-guide.md"], ["about.docs.features", "Documentation/features.md"],
                ["about.docs.changelog", "Documentation/extensions/CHANGELOG.md"]];
  const GROUPS = ["gs1", "platform", "libraries", "data"];
  let data = null;

  const safe = url => (/^https:\/\/[^\s"<>]+$/.test(url || "") ? url : null);

  function link(a, url) {
    const ok = safe(url);
    if (ok) a.href = ok; else a.removeAttribute("href");
    return a;
  }

  function when(iso) {
    return iso ? new Date(iso).toLocaleDateString(I18N.locale, { year: "numeric", month: "long", day: "numeric" }) : "";
  }

  function show() {
    if (!data) return;
    const repo = data.repository;
    const ref = data.commit || "master";
    const at = path => `${repo}/blob/${ref}/${path}`;

    const operator = $("#about-operator");
    operator.hidden = !data.operator;
    if (data.operator) I18N.set(operator, "about.operatedBy", { operator: data.operator });

    const version = $("#about-version");
    version.replaceChildren();
    if (data.commit) {
      const strong = document.createElement("strong");
      strong.textContent = data.version || data.commit.slice(0, 7);
      const commit = link(document.createElement("a"), `${repo}/commit/${data.commit}`);
      commit.rel = "noopener noreferrer";
      commit.textContent = data.commit.slice(0, 7);
      commit.className = "mono";
      const [before, after] = I18N.t("about.commit", { commit: "\u0000", date: when(data.date) }).split("\u0000");
      version.append(strong, document.createElement("br"), before ?? "", commit, after ?? "");
    } else {
      version.textContent = I18N.t("about.unknown");
    }

    const repository = link($("#about-repository"), repo);
    repository.textContent = repo;
    link($("#about-licence"), at("LICENSE"));
    link($("#about-third-party"), at("Documentation/third-party.md"));

    $("#about-docs").replaceChildren(...DOCS.map(([key, path]) => {
      const li = document.createElement("li");
      const a = link(document.createElement("a"), at(path));
      a.rel = "noopener noreferrer";
      a.textContent = I18N.t(key);
      li.append(a);
      return li;
    }));

    $("#about-components").replaceChildren(...GROUPS.map(group => {
      const box = document.createElement("section");
      box.className = "about-group";
      const h = document.createElement("h3");
      h.textContent = I18N.t(`about.group.${group}`);
      const ul = document.createElement("ul");
      ul.append(...data.components.filter(c => c.group === group).map(c => {
        const li = document.createElement("li");
        const a = link(document.createElement("a"), c.url);
        a.rel = "noopener noreferrer";
        a.textContent = c.name;
        const licence = document.createElement("span");
        licence.className = "about-licence";
        licence.textContent = c.licence;
        li.append(a, " ", licence);
        return li;
      }));
      box.append(h, ul);
      return box;
    }));
  }

  async function load() {
    let answer = null, body = {};
    try {
      answer = await fetch("api/about", { credentials: "same-origin", headers: { Accept: "application/json" } });
      body = await answer.json().catch(() => ({}));
    } catch { /* network: reported below */ }
    if (!answer || !answer.ok) {
      $("#about-status").hidden = false;
      I18N.set($("#about-status"), body.code || "error.unexpected", body.params || { status: answer ? answer.status : 0 });
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
