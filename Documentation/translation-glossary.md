# Translation guide for the interface languages

How the texts of the portal, its e-mails, the resolver's pages, the item's page and the home page are translated into
the eleven languages of the interface ([ADR 0014](adr/0014-interface-languages.md)). The translations other than
Brazilian Portuguese and British English were drafted by Claude from the English with these rules, and are to be
reviewed by a native speaker of each language before production. A new text is written in English, then in every
language with the same rules; `dev-tests/portal/test_i18n.py` checks that none is missing.

Where the texts live: `portal/static/i18n.js` (pt-BR, en-GB) and `portal/static/locales/<tag>.json` (the others),
`portal/mailtexts.py` and `portal/mail_languages.json`, `web_server/src/page_texts.json`,
`frontend_proxy_server/home/home.js`. `python portal/tools/i18n_catalogue.py check` compares every portal catalogue with
the English one.

## Rules

1. **Keys never change.** Translate only the values.
2. **Placeholders** `{name}`, `{count}`, `{p1}` … stay exactly as written (same names, braces, no spaces); move them
   where your grammar needs them. Do not translate inside the braces.
3. **Keep unchanged**: link type codes (`gs1:pip`), GS1 key abbreviations (GTIN, GLN, SSCC, GRAI, GIAI, GSRN, GDTI,
   GINC, GSIN, CPID, GMN, GCN, ITIP, UPUI, PGLN…), AI numbers like `(01)` `(10)` `(21)`, `GS1 Digital Link`,
   `GS1 Resolver Community Edition`, `Verified by GS1`, `EPC`, `EPCIS`, `RFID`, `NFC`, `QR code` may be localised if
   your language has a usual form (e.g. Japanese QRコード), `Data Matrix`, `GS1 DataMatrix`, `EAN-13`, `UPC-A`, `HRI`,
   `JSON`, `CSV`, `XLSX`, `PDF`, `SVG`, `PNG`, `ZIP`, `HTTP`, `HTTPS`, `DNS`, `TXT`, `CNAME`, `OpenID Connect`,
   `OIDC`, `SSO` (you may add the local term), `API`, `Swagger UI`, `GitHub`, `Let's Encrypt`, `nginx`, `Certbot`,
   `Google Maps`, `DB-IP`, environment variable names (`RESOLVER_LOG_DAYS`, `PORTAL_…`), file and path names
   (`scripts/custom-domains.sh`, `/etc/cron.d/…`, `.env`), command lines, URLs, e-mail addresses, examples such as
   `id.yourbrand.com`, `/gs1`, `pt-BR`, numbers and units (mm, ms, KB).
4. **Line breaks**: e-mail bodies contain `\n` line breaks and blank lines (`\n\n`); keep exactly the same number of
   `\n` and the same paragraph structure. Keep the signature's lines.
5. **Register**: polite and direct, as good software in your language: German *Sie*, French *vous*, Spanish *usted*
   (neutral Latin American/European Spanish, no regionalisms), Italian *Lei* (or impersonal forms), Japanese です・ます
   (buttons short: 保存, 削除), Korean 합니다/하십시오체 in messages and short nouns on buttons, Simplified Chinese
   for mainland users, Hindi with *आप* (keep common English IT words when Hindi users use them: पोर्टल, लिंक, ईमेल),
   Modern Standard Arabic.
6. **Short UI labels stay short** (buttons, menu items, column headers, badges): they sit in narrow places. Do not
   add explanations that are not in the English.
7. **Punctuation and quotes** of your language (« » in French with non-breaking spaces is fine; „ " in German;
   「」 in Japanese; Arabic comma ، and question mark ؟). Escape double quotes inside JSON strings.
8. **Consistency**: one term per concept across all files. Glossary below (your language's column, adapted when
   your language's GS1 Member Organisation uses another usual term).
9. `locale.name` is the language's name in itself, as listed in ADR 0014.
10. Messages of the GS1 Barcode Syntax Engine (`engine.*` keys) explain data errors (check digits, lengths, character
   sets, dates); translate them precisely, keeping AI numbers and placeholders.
11. Link types (`linkTypes` of the portal's catalogues): the name is a short title (what a button says: "Product information page",
   "Where to buy"); the explanation one or two sentences for the editor. `linkLabels` in `page_texts.json` are short public
   names of the same link types: keep them consistent with the portal's names (shorter is fine).

## Glossary (English → meaning to keep)

| English | Meaning / usual translation hints |
|---|---|
| resolver | the service answering scans of GS1 Digital Links; keep "resolver" (or the usual GS1 term of your language, e.g. es "resolver", fr "résolveur", de "Resolver", it "resolver", ja リゾルバー, ko 리졸버, zh 解析器, hi रिज़ॉल्वर, ar المحلِّل) |
| link management portal / the portal | the web application for registering links (es portal de gestión de enlaces, de Linkverwaltungsportal, ja リンク管理ポータル…) |
| record | one registration of a key (and its qualifiers) with its links (es registro, fr enregistrement, de Eintrag, it record/registrazione, ja レコード, ko 레코드, zh 记录, hi रिकॉर्ड, ar سجل) |
| target / link | the address a scan leads to (es destino/enlace, fr cible/lien, de Ziel/Link…) |
| default target / default link | what a plain scan opens |
| link type | es tipo de enlace, fr type de lien, de Linktyp, it tipo di link, ja リンクタイプ, ko 링크 유형, zh 链接类型, hi लिंक प्रकार, ar نوع الرابط |
| item's page | the resolver's page listing all links of an item (es página del artículo, fr page de l'article, de Artikelseite, it pagina dell'articolo, ja アイテムページ, ko 품목 페이지, zh 商品页面, hi आइटम पेज, ar صفحة المنتج) |
| key / primary key / key qualifier | GS1 identification key (es clave GS1, fr clé GS1, de GS1-Schlüssel, ja GS1識別キー, zh GS1标识代码…) / qualifier (es calificador, fr qualificatif, de Qualifikator…) |
| GS1 Company Prefix (GCP) | es Prefijo de Empresa GS1, fr préfixe d'entreprise GS1, de GS1-Basisnummer, it prefisso aziendale GS1, ja GS1事業者コード, ko GS1 업체코드, zh GS1厂商识别代码, hi GS1 कंपनी प्रीफ़िक्स, ar بادئة شركة GS1 |
| batch/lot | es lote, fr lot, de Charge, it lotto, ja ロット, ko 로트, zh 批次, hi बैच, ar دفعة |
| serial number | es número de serie, fr numéro de série, de Seriennummer, it numero di serie, ja シリアル番号, ko 일련번호, zh 序列号, hi सीरियल नंबर, ar الرقم التسلسلي |
| data attribute | AI data carried in the query string (expiry date, weight…) |
| organisation (tenant) | a company using the installation (es organización, fr organisation, de Organisation, it organizzazione, ja 組織, ko 조직, zh 组织, hi संगठन, ar مؤسسة) |
| operator / server administrator | who runs the installation / its top administrators |
| support access | read-only access of the operator to an organisation's data |
| scan | a reading of the code by a phone or scanner |
| request log / Requests | the log of what the resolver answered |
| label | the printable symbol image (QR code / Data Matrix) with its text |
| import / export / spreadsheet | es importar / exportar / hoja de cálculo… |
| sign in / sign out | es iniciar sesión / cerrar sesión, fr se connecter / se déconnecter, de anmelden / abmelden… |
| audit trail | history of who changed what |
| API key | es clave de API, fr clé d'API, de API-Schlüssel… |
| single sign-on | es inicio de sesión único, fr authentification unique, de Single Sign-on… |
| overview | the dashboard after sign-in |
