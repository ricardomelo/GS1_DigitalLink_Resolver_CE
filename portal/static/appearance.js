"use strict";

/*
 * The installation's appearance on the portal's pages (Documentation/adr/0019-appearance.md): the title in place of
 * "GS1 Resolver Community Edition" (in the header and in every text, through I18N.setProduct) and the operator's logo.
 * The colours come with appearance.css, linked after app.css. Loaded after i18n.js, for anyone (the sign-in page and
 * the privacy notice too).
 */
const Appearance = (() => {
  let data = null;

  function show(found) {
    data = found;
    document.querySelectorAll(".site-header .brand img").forEach(img => { img.src = found.logo; });
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
