"use strict";

/*
 * Home page behaviour: language (same choice as the portal and the resolver pages), the resolver
 * root taken from the address bar, the operator's name taken from the resolver description file,
 * and the collapsible menu on small screens.
 *
 * Language choice follows the portal (portal/static/i18n.js): the browser's saved choice, then the
 * gs1resolver_lang cookie, then navigator.languages. Changing it here writes both, so the portal and
 * the resolver's own pages open in the same language.
 *
 * Elements opt in declaratively:
 *   data-i18n="key"                    → textContent
 *   data-i18n-attr="aria-label:key"    → attribute values
 * To add a locale: copy one block of CATALOGUE, translate it, add it to SUPPORTED and LOCALE_MATCHERS.
 */
(() => {
  const SUPPORTED = ["pt-BR", "en-GB"];
  const DEFAULT_LOCALE = "en-GB";
  const STORAGE_KEY = "gs1resolver.portal.locale";   // shared with the portal (same origin)
  const COOKIE_NAME = "gs1resolver_lang";            // shared with the resolver's HTML pages
  const LOCALE_MATCHERS = [["pt", "pt-BR"], ["en", "en-GB"]];
  const DESCRIPTION_FILE = "/.well-known/gs1resolver";

  const CATALOGUE = {
    "pt-BR": {
      "locale.name": "Português (Brasil)",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Pular para o conteúdo",
      "header.language": "Idioma",
      "nav.label": "Menu principal",
      "nav.toggle": "Menu",
      "nav.portal": "Cadastro de links",
      "nav.api": "API do Resolver",
      "nav.standard": "Padrão GS1 Digital Link",
      "nav.github": "Código-fonte (GitHub)",
      "link.external": "(site externo)",
      "hero.title": "Resolver GS1 Digital Link",
      "hero.lede": "Este endereço resolve GS1 Digital Links: quem lê o QR Code de um produto é levado às informações publicadas pela empresa dona da marca.",
      "here.title": "Neste Resolver",
      "card.portal.title": "Portal de cadastro de links",
      "card.portal.text": "Cadastre GTINs e lotes e defina para onde leva o QR Code GS1 Digital Link de cada produto. Requer usuário e senha.",
      "card.portal.action": "Abrir o portal",
      "card.api.title": "API do Resolver (Swagger UI)",
      "card.api.text": "Documentação interativa da API de cadastro do Resolver CE, a página exibida antes na raiz deste endereço. Para integrações entre sistemas; gravar exige token de acesso.",
      "refs.title": "Referências GS1",
      "card.standard.title": "Padrão GS1 Digital Link",
      "card.standard.text": "Sintaxe URI, resolvers conformes e documentos relacionados no GS1 Reference.",
      "card.gs1.text": "A organização que desenvolve e mantém os padrões GS1 de identificação, códigos de barras e compartilhamento de dados.",
      "card.github.title": "GS1 Resolver CE no GitHub",
      "card.github.text": "Código aberto (Apache 2.0) do Resolver usado por este serviço.",
      "syntax.title": "Como é um GS1 Digital Link",
      "syntax.gtin": "GTIN, o identificador do produto (14 dígitos)",
      "syntax.lot": "Lote (opcional)",
      "syntax.rootLabel": "Raiz deste Resolver",
      "syntax.description": "Arquivo de descrição do Resolver",
      "footer.operatedBy": "Operado por",
    },
    "en-GB": {
      "locale.name": "English (UK)",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Skip to content",
      "header.language": "Language",
      "nav.label": "Main menu",
      "nav.toggle": "Menu",
      "nav.portal": "Manage links",
      "nav.api": "Resolver API",
      "nav.standard": "GS1 Digital Link standard",
      "nav.github": "Source code (GitHub)",
      "link.external": "(external site)",
      "hero.title": "GS1 Digital Link resolver",
      "hero.lede": "This address resolves GS1 Digital Links: scanning the QR code on a product takes you to the information its brand owner has published.",
      "here.title": "On this resolver",
      "card.portal.title": "Link management portal",
      "card.portal.text": "Register GTINs and batches and choose where each product's GS1 Digital Link QR code leads. Requires a username and password.",
      "card.portal.action": "Open the portal",
      "card.api.title": "Resolver API (Swagger UI)",
      "card.api.text": "Interactive documentation of the Resolver CE data entry API, previously shown at the root of this address. For system integrations; writing requires an access token.",
      "refs.title": "GS1 references",
      "card.standard.title": "GS1 Digital Link standard",
      "card.standard.text": "URI syntax, conformant resolvers and related documents on GS1 Reference.",
      "card.gs1.text": "The organisation that develops and maintains the GS1 identification, barcode and data sharing standards.",
      "card.github.title": "GS1 Resolver CE on GitHub",
      "card.github.text": "Open-source code (Apache 2.0) of the resolver behind this service.",
      "syntax.title": "What a GS1 Digital Link looks like",
      "syntax.gtin": "GTIN, the product identifier (14 digits)",
      "syntax.lot": "Batch or lot (optional)",
      "syntax.rootLabel": "Root of this resolver",
      "syntax.description": "Resolver description file",
      "footer.operatedBy": "Operated by",
    },
  };

  const $ = sel => document.querySelector(sel);
  document.documentElement.classList.add("js");

  /* ---------------------------------------------------------------- language */
  function readCookie(name) {
    const entry = document.cookie.split("; ").find(c => c.startsWith(name + "="));
    return entry ? decodeURIComponent(entry.slice(name.length + 1)) : null;
  }

  function detect() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.includes(saved)) return saved;
    } catch { /* storage unavailable: fall back to the cookie and browser languages */ }
    const cookie = readCookie(COOKIE_NAME);
    if (SUPPORTED.includes(cookie)) return cookie;
    for (const tag of navigator.languages || [navigator.language || ""]) {
      const lower = String(tag).toLowerCase();
      const match = LOCALE_MATCHERS.find(([prefix]) => lower === prefix || lower.startsWith(prefix + "-"));
      if (match) return match[1];
    }
    return DEFAULT_LOCALE;
  }

  let locale = detect();

  function t(key) {
    return CATALOGUE[locale][key] ?? CATALOGUE[DEFAULT_LOCALE][key] ?? key;
  }

  function apply() {
    document.documentElement.lang = locale;
    document.title = t(document.body.dataset.titleKey || "page.title");
    document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-attr]").forEach(el => {
      el.dataset.i18nAttr.split(";").forEach(pair => {
        const [attr, key] = pair.split(":");
        if (attr && key) el.setAttribute(attr.trim(), t(key.trim()));
      });
    });
  }

  function setLocale(next) {
    if (!SUPPORTED.includes(next)) return;
    locale = next;
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* not persisted */ }
    document.cookie = `${COOKIE_NAME}=${encodeURIComponent(next)}; path=/; max-age=31536000; SameSite=Lax` +
      (location.protocol === "https:" ? "; Secure" : "");
    apply();
  }

  function initLocalePicker() {
    const select = $("#locale");
    for (const loc of SUPPORTED) select.add(new Option(CATALOGUE[loc]["locale.name"], loc));
    select.value = locale;
    select.hidden = false;
    select.addEventListener("change", () => setLocale(select.value));
  }

  /* ---------------------------------------------------------------- resolver root */
  // Taken from the address bar, so the page never needs editing for a new domain.
  function showResolverRoot() {
    const root = location.origin;
    $("#resolver-root").textContent = root;
    $("#resolver-root-full").textContent = root;
  }

  /* ---------------------------------------------------------------- operator */
  // The operator's name comes from the resolver description file (contact.fn), which every
  // GS1-Conformant Resolver publishes. If it cannot be read the footer simply omits it.
  async function showOperator() {
    try {
      const response = await fetch(DESCRIPTION_FILE, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const description = await response.json();
      const name = description && description.contact && description.contact.fn;
      if (typeof name === "string" && name.trim()) {
        $("#operator-name").textContent = name.trim();
        $("#operator").hidden = false;
      }
    } catch { /* description file unavailable: nothing to show */ }
  }

  /* ---------------------------------------------------------------- menu on small screens */
  function initNavToggle() {
    const button = $("#nav-toggle");
    const nav = $("#site-nav");
    button.hidden = false;
    const setOpen = open => {
      nav.classList.toggle("is-open", open);
      button.setAttribute("aria-expanded", String(open));
    };
    button.addEventListener("click", () => setOpen(!nav.classList.contains("is-open")));
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && nav.classList.contains("is-open")) { setOpen(false); button.focus(); }
    });
  }

  // Loaded synchronously in <head> so the "js" class is set before first paint (no menu flash);
  // everything that touches the page waits for the document.
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    initLocalePicker();
    showResolverRoot();
    initNavToggle();
    showOperator();
  });
})();
