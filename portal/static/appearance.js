"use strict";

/*
 * The installation's appearance on the portal's pages (Documentation/adr/0019-appearance.md): the title in place of
 * "GS1 Resolver Community Edition" (in the header and in every text, through I18N.setProduct), the operator's logo and
 * the icon of the browsers' tabs. The portal serves each page with them already in it (appearance.page()); this keeps
 * them in step after a change. The colours come with appearance.css, linked after app.css. Loaded after i18n.js, for
 * anyone (the sign-in page and the privacy notice too).
 */
const Appearance = (() => {
  let data = null;

  function show(found) {
    data = found;
    document.querySelectorAll(".site-header .brand img").forEach(img => { img.src = found.logo; });
    document.querySelectorAll('link[rel="icon"]').forEach(link => { link.removeAttribute("type"); link.href = found.icon; });
    I18N.setProduct(found.original ? null : found.title);
  }

  async function load() {
    try {
      const answer = await fetch("api/appearance", { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (answer.ok) show(await answer.json());
    } catch { /* the original stays */ }
  }

  I18N.ready.then(load);
  return { show, reload: load, get data() { return data; } };
})();
