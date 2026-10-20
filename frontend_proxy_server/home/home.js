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
 * Twelve languages, as in the portal (Documentation/adr/0014-interface-languages.md); Arabic right to left. A new
 * text needs every language (dev-tests/portal/test_i18n.py checks them).
 */
(() => {
  const SUPPORTED = ["pt-BR", "en-GB", "es", "fr", "de", "it", "tr", "zh-Hans", "ja", "ko", "hi", "ar"];
  const RIGHT_TO_LEFT = ["ar"];
  const DEFAULT_LOCALE = "en-GB";
  const STORAGE_KEY = "gs1resolver.portal.locale";   // shared with the portal (same origin)
  const COOKIE_NAME = "gs1resolver_lang";            // shared with the resolver's HTML pages
  const LOCALE_MATCHERS = [["pt", "pt-BR"], ["en", "en-GB"], ["es", "es"], ["fr", "fr"], ["de", "de"], ["it", "it"],
                           ["tr", "tr"], ["zh", "zh-Hans"], ["ja", "ja"], ["ko", "ko"], ["hi", "hi"], ["ar", "ar"]];
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
      "card.portal.text": "Cadastre produtos, lotes, séries, locais, unidades logísticas, documentos e ativos identificados com chaves GS1 e defina para onde leva o QR Code GS1 Digital Link de cada um. Requer usuário e senha.",
      "card.portal.action": "Abrir o portal",
      "card.api.title": "API do Resolver (Swagger UI)",
      "card.api.text": "Documentação interativa da API de cadastro do Resolver CE, a página exibida antes na raiz deste endereço. Para integrações entre sistemas; gravar exige token de acesso.",
      "refs.title": "Referências GS1",
      "card.standard.title": "Padrão GS1 Digital Link",
      "card.standard.text": "Sintaxe URI, resolvers conformes e documentos relacionados no GS1 Reference.",
      "card.gs1.text": "A organização que desenvolve e mantém os padrões GS1 de identificação, códigos de barras e compartilhamento de dados.",
      "card.github.title": "GS1 Resolver CE no GitHub",
      "card.github.text": "Código aberto (Apache 2.0) do Resolver usado por este serviço.",
      "footer.operatedBy": "Operado por",
      "footer.notice": "Software mantido pela sua comunidade, não pela GS1 nem por qualquer Organização-Membro GS1. Quem opera esta instalação é responsável pelo seu uso.",
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
      "card.portal.text": "Register products, batches, serial numbers, locations, logistic units, documents and assets identified by GS1 keys and choose where each GS1 Digital Link QR code leads. Requires a username and password.",
      "card.portal.action": "Open the portal",
      "card.api.title": "Resolver API (Swagger UI)",
      "card.api.text": "Interactive documentation of the Resolver CE data entry API, previously shown at the root of this address. For system integrations; writing requires an access token.",
      "refs.title": "GS1 references",
      "card.standard.title": "GS1 Digital Link standard",
      "card.standard.text": "URI syntax, conformant resolvers and related documents on GS1 Reference.",
      "card.gs1.text": "The organisation that develops and maintains the GS1 identification, barcode and data sharing standards.",
      "card.github.title": "GS1 Resolver CE on GitHub",
      "card.github.text": "Open-source code (Apache 2.0) of the resolver behind this service.",
      "footer.operatedBy": "Operated by",
      "footer.notice": "Software maintained by its community, not by GS1 or any GS1 Member Organisation. Whoever operates this installation is responsible for its use.",
    },
    "es": {
      "locale.name": "Español",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Ir al contenido",
      "header.language": "Idioma",
      "nav.label": "Menú principal",
      "nav.toggle": "Menú",
      "nav.portal": "Gestionar enlaces",
      "nav.api": "API del resolver",
      "nav.standard": "Estándar GS1 Digital Link",
      "nav.github": "Código fuente (GitHub)",
      "link.external": "(sitio externo)",
      "hero.title": "Resolver GS1 Digital Link",
      "hero.lede": "Esta dirección resuelve GS1 Digital Links: al leer el código QR de un producto, llega a la información que ha publicado el propietario de su marca.",
      "here.title": "En este resolver",
      "card.portal.title": "Portal de gestión de enlaces",
      "card.portal.text": "Registre productos, lotes, números de serie, ubicaciones, unidades logísticas, documentos y activos identificados con claves GS1 y elija adónde lleva cada código QR GS1 Digital Link. Requiere nombre de usuario y contraseña.",
      "card.portal.action": "Abrir el portal",
      "card.api.title": "API del resolver (Swagger UI)",
      "card.api.text": "Documentación interactiva de la API de entrada de datos de Resolver CE, que antes se mostraba en la raíz de esta dirección. Para integraciones de sistemas; la escritura requiere un token de acceso.",
      "refs.title": "Referencias de GS1",
      "card.standard.title": "Estándar GS1 Digital Link",
      "card.standard.text": "Sintaxis de URI, resolvers conformes y documentos relacionados en GS1 Reference.",
      "card.gs1.text": "La organización que desarrolla y mantiene los estándares GS1 de identificación, códigos de barras e intercambio de datos.",
      "card.github.title": "GS1 Resolver CE en GitHub",
      "card.github.text": "Código abierto (Apache 2.0) del resolver en el que se basa este servicio.",
      "footer.operatedBy": "Operado por",
      "footer.notice": "Software mantenido por su comunidad, no por GS1 ni por ninguna Organización Miembro de GS1. Quien opera esta instalación es responsable de su uso.",
    },
    "fr": {
      "locale.name": "Français",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Aller au contenu",
      "header.language": "Langue",
      "nav.label": "Menu principal",
      "nav.toggle": "Menu",
      "nav.portal": "Gérer les liens",
      "nav.api": "API du résolveur",
      "nav.standard": "Norme GS1 Digital Link",
      "nav.github": "Code source (GitHub)",
      "link.external": "(site externe)",
      "hero.title": "Résolveur GS1 Digital Link",
      "hero.lede": "Cette adresse résout les GS1 Digital Links : scanner le QR code d’un produit vous mène aux informations publiées par le propriétaire de sa marque.",
      "here.title": "Sur ce résolveur",
      "card.portal.title": "Portail de gestion des liens",
      "card.portal.text": "Enregistrez des produits, lots, numéros de série, lieux, unités logistiques, documents et actifs identifiés par des clés GS1, et choisissez où mène chaque QR code GS1 Digital Link. Nécessite un nom d’utilisateur et un mot de passe.",
      "card.portal.action": "Ouvrir le portail",
      "card.api.title": "API du résolveur (Swagger UI)",
      "card.api.text": "Documentation interactive de l’API de saisie des données de Resolver CE, auparavant affichée à la racine de cette adresse. Pour l’intégration de systèmes ; l’écriture nécessite un jeton d’accès.",
      "refs.title": "Références GS1",
      "card.standard.title": "Norme GS1 Digital Link",
      "card.standard.text": "Syntaxe des URI, résolveurs conformes et documents associés sur GS1 Reference.",
      "card.gs1.text": "L’organisation qui élabore et maintient les normes GS1 d’identification, de codes-barres et de partage de données.",
      "card.github.title": "GS1 Resolver CE sur GitHub",
      "card.github.text": "Code open source (Apache 2.0) du résolveur sur lequel repose ce service.",
      "footer.operatedBy": "Exploité par",
      "footer.notice": "Logiciel maintenu par sa communauté, et non par GS1 ni par une organisation membre de GS1. L’exploitant de cette installation est responsable de son utilisation.",
    },
    "de": {
      "locale.name": "Deutsch",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Zum Inhalt springen",
      "header.language": "Sprache",
      "nav.label": "Hauptmenü",
      "nav.toggle": "Menü",
      "nav.portal": "Links verwalten",
      "nav.api": "Resolver-API",
      "nav.standard": "Standard GS1 Digital Link",
      "nav.github": "Quellcode (GitHub)",
      "link.external": "(externe Website)",
      "hero.title": "GS1-Digital-Link-Resolver",
      "hero.lede": "Diese Adresse löst GS1 Digital Links auf: Wenn Sie den QR-Code auf einem Produkt scannen, gelangen Sie zu den Informationen, die sein Markeninhaber veröffentlicht hat.",
      "here.title": "Auf diesem Resolver",
      "card.portal.title": "Linkverwaltungsportal",
      "card.portal.text": "Erfassen Sie Produkte, Chargen, Seriennummern, Standorte, logistische Einheiten, Dokumente und Anlagegüter, die mit GS1-Schlüsseln identifiziert sind, und legen Sie fest, wohin jeder GS1-Digital-Link-QR-Code führt. Erfordert Benutzername und Passwort.",
      "card.portal.action": "Portal öffnen",
      "card.api.title": "Resolver-API (Swagger UI)",
      "card.api.text": "Interaktive Dokumentation der Dateneingabe-API von Resolver CE, die früher im Stammverzeichnis dieser Adresse angezeigt wurde. Für Systemintegrationen; Schreiben erfordert ein Zugriffstoken.",
      "refs.title": "GS1-Referenzen",
      "card.standard.title": "Standard GS1 Digital Link",
      "card.standard.text": "URI-Syntax, konforme Resolver und zugehörige Dokumente auf GS1 Reference.",
      "card.gs1.text": "Die Organisation, die die GS1-Standards für Identifikation, Barcodes und Datenaustausch entwickelt und pflegt.",
      "card.github.title": "GS1 Resolver CE auf GitHub",
      "card.github.text": "Open-Source-Code (Apache 2.0) des Resolvers hinter diesem Dienst.",
      "footer.operatedBy": "Betrieben von",
      "footer.notice": "Software, die von ihrer Community gepflegt wird, nicht von GS1 oder einer GS1-Mitgliedsorganisation. Wer diese Installation betreibt, ist für ihre Nutzung verantwortlich.",
    },
    "it": {
      "locale.name": "Italiano",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "Vai al contenuto",
      "header.language": "Lingua",
      "nav.label": "Menu principale",
      "nav.toggle": "Menu",
      "nav.portal": "Gestisci i link",
      "nav.api": "API del resolver",
      "nav.standard": "Standard GS1 Digital Link",
      "nav.github": "Codice sorgente (GitHub)",
      "link.external": "(sito esterno)",
      "hero.title": "Resolver GS1 Digital Link",
      "hero.lede": "Questo indirizzo risolve i GS1 Digital Link: scansionando il QR code su un prodotto si accede alle informazioni pubblicate dal titolare del marchio.",
      "here.title": "Su questo resolver",
      "card.portal.title": "Portale di gestione dei link",
      "card.portal.text": "Registri prodotti, lotti, numeri di serie, ubicazioni, unità logistiche, documenti e beni identificati da chiavi GS1 e scelga dove porta ciascun QR code GS1 Digital Link. Richiede nome utente e password.",
      "card.portal.action": "Apri il portale",
      "card.api.title": "API del resolver (Swagger UI)",
      "card.api.text": "Documentazione interattiva dell'API di inserimento dati di Resolver CE, mostrata in precedenza alla radice di questo indirizzo. Per le integrazioni di sistema; la scrittura richiede un token di accesso.",
      "refs.title": "Riferimenti GS1",
      "card.standard.title": "Standard GS1 Digital Link",
      "card.standard.text": "Sintassi degli URI, resolver conformi e documenti correlati su GS1 Reference.",
      "card.gs1.text": "L'organizzazione che sviluppa e mantiene gli standard GS1 di identificazione, codici a barre e condivisione dei dati.",
      "card.github.title": "GS1 Resolver CE su GitHub",
      "card.github.text": "Codice open source (Apache 2.0) del resolver alla base di questo servizio.",
      "footer.operatedBy": "Gestito da",
      "footer.notice": "Software mantenuto dalla sua comunità, non da GS1 né da alcuna Organizzazione Membro GS1. Chi gestisce questa installazione è responsabile del suo utilizzo.",
    },
    "tr": {
      "locale.name": "Türkçe",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "İçeriğe geç",
      "header.language": "Dil",
      "nav.label": "Ana menü",
      "nav.toggle": "Menü",
      "nav.portal": "Bağlantıları yönet",
      "nav.api": "Çözümleyici API'si",
      "nav.standard": "GS1 Digital Link standardı",
      "nav.github": "Kaynak kodu (GitHub)",
      "link.external": "(harici site)",
      "hero.title": "GS1 Digital Link çözümleyicisi",
      "hero.lede": "Bu adres GS1 Digital Link'leri çözümler: bir ürünün QR kodunu okuttuğunuzda marka sahibinin yayımladığı bilgilere ulaşırsınız.",
      "here.title": "Bu çözümleyicide",
      "card.portal.title": "Bağlantı yönetim portalı",
      "card.portal.text": "GS1 anahtarlarıyla tanımlanan ürünleri, partileri, seri numaralarını, konumları, lojistik birimleri, belgeleri ve varlıkları kaydedin ve her GS1 Digital Link QR kodunun nereye götüreceğini seçin. Kullanıcı adı ve parola gerektirir.",
      "card.portal.action": "Portalı aç",
      "card.api.title": "Çözümleyici API'si (Swagger UI)",
      "card.api.text": "Daha önce bu adresin kökünde gösterilen Resolver CE veri giriş API'sinin etkileşimli belgeleri. Sistem entegrasyonları için; yazmak bir erişim belirteci gerektirir.",
      "refs.title": "GS1 kaynakları",
      "card.standard.title": "GS1 Digital Link standardı",
      "card.standard.text": "GS1 Reference'ta URI sözdizimi, uyumlu çözümleyiciler ve ilgili belgeler.",
      "card.gs1.text": "GS1 tanımlama, barkod ve veri paylaşımı standartlarını geliştiren ve sürdüren kuruluş.",
      "card.github.title": "GitHub'da GS1 Resolver CE",
      "card.github.text": "Bu hizmetin arkasındaki çözümleyicinin açık kaynak kodu (Apache 2.0).",
      "footer.operatedBy": "İşleten",
      "footer.notice": "Yazılım, GS1 veya herhangi bir GS1 Üye Kuruluşu tarafından değil, topluluğu tarafından sürdürülmektedir. Bu kurulumu işleten kişi veya kuruluş, kullanımından sorumludur.",
    },
    "zh-Hans": {
      "locale.name": "中文（简体）",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "跳至内容",
      "header.language": "语言",
      "nav.label": "主菜单",
      "nav.toggle": "菜单",
      "nav.portal": "管理链接",
      "nav.api": "解析器API",
      "nav.standard": "GS1 Digital Link标准",
      "nav.github": "源代码（GitHub）",
      "link.external": "（外部网站）",
      "hero.title": "GS1 Digital Link解析器",
      "hero.lede": "此地址用于解析GS1 Digital Link：扫描产品上的二维码，即可查看品牌所有者发布的信息。",
      "here.title": "此解析器提供",
      "card.portal.title": "链接管理门户",
      "card.portal.text": "注册以GS1标识代码标识的产品、批次、序列号、位置、物流单元、文件和资产，并选择每个GS1 Digital Link二维码的跳转目标。需要用户名和密码。",
      "card.portal.action": "打开门户",
      "card.api.title": "解析器API（Swagger UI）",
      "card.api.text": "Resolver CE数据录入API的交互式文档，以前显示在此地址的根目录。用于系统集成；写入数据需要访问令牌。",
      "refs.title": "GS1参考资料",
      "card.standard.title": "GS1 Digital Link标准",
      "card.standard.text": "GS1 Reference上的URI语法、合规解析器及相关文档。",
      "card.gs1.text": "负责制定和维护GS1标识、条码和数据共享标准的组织。",
      "card.github.title": "GitHub上的GS1 Resolver CE",
      "card.github.text": "此服务所用解析器的开源代码（Apache 2.0）。",
      "footer.operatedBy": "运营方：",
      "footer.notice": "本软件由其社区维护，而非由GS1或任何GS1成员组织维护。本安装的运营者对其使用负责。",
    },
    "ja": {
      "locale.name": "日本語",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "本文へスキップ",
      "header.language": "言語",
      "nav.label": "メインメニュー",
      "nav.toggle": "メニュー",
      "nav.portal": "リンクを管理",
      "nav.api": "リゾルバーAPI",
      "nav.standard": "GS1 Digital Link 標準",
      "nav.github": "ソースコード（GitHub）",
      "link.external": "（外部サイト）",
      "hero.title": "GS1 Digital Link リゾルバー",
      "hero.lede": "このアドレスは GS1 Digital Link を解決します。製品のQRコードをスキャンすると、ブランドの所有者が公開した情報が表示されます。",
      "here.title": "このリゾルバーの機能",
      "card.portal.title": "リンク管理ポータル",
      "card.portal.text": "GS1識別キーで識別される製品、ロット、シリアル番号、場所、物流単位、文書、資産を登録し、各 GS1 Digital Link QRコードのリンク先を選択します。ユーザー名とパスワードが必要です。",
      "card.portal.action": "ポータルを開く",
      "card.api.title": "リゾルバーAPI（Swagger UI）",
      "card.api.text": "Resolver CE のデータ入力APIの対話型ドキュメントです（以前はこのアドレスのルートに表示されていました）。システム連携用で、書き込みにはアクセストークンが必要です。",
      "refs.title": "GS1の参考資料",
      "card.standard.title": "GS1 Digital Link 標準",
      "card.standard.text": "GS1 Reference に掲載されている、URI構文、準拠リゾルバー、関連文書。",
      "card.gs1.text": "GS1の識別、バーコード、データ共有に関する標準を策定・維持している組織。",
      "card.github.title": "GitHub の GS1 Resolver CE",
      "card.github.text": "このサービスを支えるリゾルバーのオープンソースコード（Apache 2.0）。",
      "footer.operatedBy": "運用者：",
      "footer.notice": "このソフトウェアはコミュニティによって保守されており、GS1やGS1加盟組織によるものではありません。このインストール環境の運用者が、その利用について責任を負います。",
    },
    "ko": {
      "locale.name": "한국어",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "본문으로 건너뛰기",
      "header.language": "언어",
      "nav.label": "주 메뉴",
      "nav.toggle": "메뉴",
      "nav.portal": "링크 관리",
      "nav.api": "리졸버 API",
      "nav.standard": "GS1 Digital Link 표준",
      "nav.github": "소스 코드(GitHub)",
      "link.external": "(외부 사이트)",
      "hero.title": "GS1 Digital Link 리졸버",
      "hero.lede": "이 주소는 GS1 Digital Link를 리졸브합니다. 제품의 QR 코드를 스캔하면 브랜드 소유자가 게시한 정보로 이동합니다.",
      "here.title": "이 리졸버에서",
      "card.portal.title": "링크 관리 포털",
      "card.portal.text": "GS1 키로 식별되는 제품, 로트, 일련번호, 위치, 물류 단위, 문서 및 자산을 등록하고 각 GS1 Digital Link QR 코드가 연결될 곳을 선택합니다. 사용자 이름과 비밀번호가 필요합니다.",
      "card.portal.action": "포털 열기",
      "card.api.title": "리졸버 API(Swagger UI)",
      "card.api.text": "이전에 이 주소의 루트에 표시되던 Resolver CE 데이터 입력 API의 대화형 문서입니다. 시스템 연동용이며, 쓰기에는 접근 토큰이 필요합니다.",
      "refs.title": "GS1 참고 자료",
      "card.standard.title": "GS1 Digital Link 표준",
      "card.standard.text": "GS1 Reference에 있는 URI 구문, 표준을 준수하는 리졸버 및 관련 문서입니다.",
      "card.gs1.text": "GS1 식별, 바코드 및 데이터 공유 표준을 개발하고 유지 관리하는 기관입니다.",
      "card.github.title": "GitHub의 GS1 Resolver CE",
      "card.github.text": "이 서비스를 구동하는 리졸버의 오픈 소스 코드(Apache 2.0)입니다.",
      "footer.operatedBy": "운영:",
      "footer.notice": "이 소프트웨어는 GS1 또는 GS1 회원기관이 아닌 커뮤니티에서 유지 관리합니다. 이 설치 환경의 운영자가 사용에 대한 책임을 집니다.",
    },
    "hi": {
      "locale.name": "हिन्दी",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "सामग्री पर जाएँ",
      "header.language": "भाषा",
      "nav.label": "मुख्य मेनू",
      "nav.toggle": "मेनू",
      "nav.portal": "लिंक प्रबंधित करें",
      "nav.api": "रिज़ॉल्वर API",
      "nav.standard": "GS1 Digital Link मानक",
      "nav.github": "सोर्स कोड (GitHub)",
      "link.external": "(बाहरी साइट)",
      "hero.title": "GS1 Digital Link रिज़ॉल्वर",
      "hero.lede": "यह पता GS1 Digital Link को रिज़ॉल्व करता है: किसी उत्पाद पर QR कोड स्कैन करने से आप उस जानकारी तक पहुँचते हैं जो उसके ब्रांड स्वामी ने प्रकाशित की है।",
      "here.title": "इस रिज़ॉल्वर पर",
      "card.portal.title": "लिंक प्रबंधन पोर्टल",
      "card.portal.text": "GS1 कुंजियों से पहचाने जाने वाले उत्पाद, बैच, सीरियल नंबर, स्थान, लॉजिस्टिक इकाइयाँ, दस्तावेज़ और एसेट पंजीकृत करें और चुनें कि हर GS1 Digital Link QR कोड कहाँ ले जाए। उपयोगकर्ता नाम और पासवर्ड आवश्यक है।",
      "card.portal.action": "पोर्टल खोलें",
      "card.api.title": "रिज़ॉल्वर API (Swagger UI)",
      "card.api.text": "Resolver CE डेटा एंट्री API का इंटरैक्टिव दस्तावेज़ीकरण, जो पहले इस पते के रूट पर दिखाया जाता था। सिस्टम इंटीग्रेशन के लिए; लिखने के लिए एक्सेस टोकन आवश्यक है।",
      "refs.title": "GS1 संदर्भ",
      "card.standard.title": "GS1 Digital Link मानक",
      "card.standard.text": "GS1 Reference पर URI सिंटैक्स, अनुरूप रिज़ॉल्वर और संबंधित दस्तावेज़।",
      "card.gs1.text": "वह संगठन जो GS1 पहचान, बारकोड और डेटा साझाकरण मानक विकसित करता है और उनका रखरखाव करता है।",
      "card.github.title": "GitHub पर GS1 Resolver CE",
      "card.github.text": "इस सेवा के पीछे के रिज़ॉल्वर का ओपन-सोर्स कोड (Apache 2.0)।",
      "footer.operatedBy": "संचालक",
      "footer.notice": "इस सॉफ़्टवेयर का रखरखाव इसका समुदाय करता है, GS1 या कोई GS1 सदस्य संगठन नहीं। इस इंस्टॉलेशन को चलाने वाला इसके उपयोग के लिए उत्तरदायी है।",
    },
    "ar": {
      "locale.name": "العربية",
      "page.title": "GS1 Resolver Community Edition",
      "page.skip": "انتقل إلى المحتوى",
      "header.language": "اللغة",
      "nav.label": "القائمة الرئيسية",
      "nav.toggle": "القائمة",
      "nav.portal": "إدارة الروابط",
      "nav.api": "API المحلِّل",
      "nav.standard": "معيار GS1 Digital Link",
      "nav.github": "الشيفرة المصدرية (GitHub)",
      "link.external": "(موقع خارجي)",
      "hero.title": "محلِّل GS1 Digital Link",
      "hero.lede": "يحلّل هذا العنوان روابط GS1 Digital Link: مسح رمز QR الموجود على المنتج ينقلك إلى المعلومات التي نشرها مالك علامته التجارية.",
      "here.title": "على هذا المحلِّل",
      "card.portal.title": "بوابة إدارة الروابط",
      "card.portal.text": "سجِّل المنتجات والدفعات والأرقام التسلسلية والمواقع والوحدات اللوجستية والمستندات والأصول المعرَّفة بمفاتيح GS1، واختر إلى أين يقود كل رمز QR بتقنية GS1 Digital Link. يتطلب اسم مستخدم وكلمة مرور.",
      "card.portal.action": "فتح البوابة",
      "card.api.title": "API المحلِّل (Swagger UI)",
      "card.api.text": "توثيق تفاعلي لواجهة API الخاصة بإدخال البيانات في Resolver CE، كان يُعرض سابقًا في جذر هذا العنوان. لتكامل الأنظمة؛ وتتطلب الكتابة رمز وصول.",
      "refs.title": "مراجع GS1",
      "card.standard.title": "معيار GS1 Digital Link",
      "card.standard.text": "صياغة URI، والمحلِّلات المطابقة للمعيار، والوثائق ذات الصلة على GS1 Reference.",
      "card.gs1.text": "المنظمة التي تطوّر معايير GS1 للتعريف والباركود ومشاركة البيانات وتصونها.",
      "card.github.title": "GS1 Resolver CE على GitHub",
      "card.github.text": "الشيفرة المفتوحة المصدر (Apache 2.0) للمحلِّل الذي تقوم عليه هذه الخدمة.",
      "footer.operatedBy": "يشغّله",
      "footer.notice": "برنامج يصونه مجتمعه، لا GS1 ولا أي منظمة عضو في GS1. ويتحمّل من يشغّل هذا التثبيت مسؤولية استخدامه.",
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
      if (SUPPORTED.includes(saved) && CATALOGUE[saved]) return saved;
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
    return (CATALOGUE[locale] || {})[key] ?? CATALOGUE[DEFAULT_LOCALE][key] ?? key;
  }

  function apply() {
    document.documentElement.lang = locale;
    document.documentElement.dir = RIGHT_TO_LEFT.includes(locale) ? "rtl" : "ltr";
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

  /* Names written in the Latin alphabet first, alphabetically (accents ignored), then the others by their script, as
     the portal's menus (portal/static/i18n.js, byScript). */
  function menuOrder(codes) {
    const name = loc => CATALOGUE[loc]["locale.name"];
    const latin = /^\p{Script=Latin}/u;
    const folded = text => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    return [...codes].sort((a, b) => {
      const na = name(a), nb = name(b), la = latin.test(na), lb = latin.test(nb);
      if (la !== lb) return la ? -1 : 1;
      if (!la) return na.codePointAt(0) - nb.codePointAt(0) || (na < nb ? -1 : na > nb ? 1 : 0);
      return folded(na) < folded(nb) ? -1 : folded(na) > folded(nb) ? 1 : 0;
    });
  }

  function initLocalePicker() {
    const select = $("#locale");
    for (const loc of menuOrder(SUPPORTED.filter(l => CATALOGUE[l]))) select.add(new Option(CATALOGUE[loc]["locale.name"], loc));
    select.value = locale;
    select.hidden = false;
    select.addEventListener("change", () => setLocale(select.value));
  }

  /* ---------------------------------------------------------------- operator */
  // The operator's name comes from the resolver description file (contact.fn), which every
  // GS1-Conformant Resolver publishes, and links to contact.hasURL when that is a web address (the
  // same RESOLVER_ORG_URL the footer of the resolver's pages uses). If the file cannot be read the
  // footer simply omits the operator.
  function webAddress(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value.trim());
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch {
      return null;
    }
  }

  async function showOperator() {
    try {
      const response = await fetch(DESCRIPTION_FILE, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const description = await response.json();
      const contact = (description && description.contact) || {};
      const name = contact.fn;
      if (typeof name === "string" && name.trim()) {
        const target = $("#operator-name");
        const href = webAddress(contact.hasURL);
        if (href) {
          const link = document.createElement("a");
          link.className = "ext";
          link.href = href;
          link.rel = "noopener";
          link.textContent = name.trim();
          const hint = document.createElement("span");
          hint.className = "visually-hidden";
          hint.dataset.i18n = "link.external";
          hint.textContent = t("link.external");
          link.append(hint);
          target.replaceChildren(link);
        } else {
          target.textContent = name.trim();
        }
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
    initNavToggle();
    showOperator();
  });
})();
