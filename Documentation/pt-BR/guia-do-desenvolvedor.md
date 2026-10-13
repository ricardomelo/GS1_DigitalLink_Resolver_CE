# Guia do desenvolvedor

Como o GS1 Digital Link Resolver CE — Expansion Pack é construído: os serviços, cada arquivo-fonte escrito
ou alterado pelo fork, a API e os arquivos de dados do portal, os testes e como estendê-lo. Leia junto com
as docstrings do código, que descrevem cada função (em inglês), e com a
[documentação das extensões](../extensions/README.md) (em inglês), que registra as regras detalhadas e as
decisões de projeto.

*English version: [developer guide](../developer-guide.md).* Instalação e configuração estão no
[README](../../README.md); o uso do portal, no [guia do portal](guia-do-portal.md).

Os nomes de arquivos, funções, variáveis e mensagens aparecem como estão no código, em inglês.

## Sumário

1. [Arquitetura](#1-arquitetura)
2. [Estrutura do repositório](#2-estrutura-do-repositório)
3. [Serviços e configuração](#3-serviços-e-configuração)
4. [Fluxos das requisições](#4-fluxos-das-requisições)
5. [Back-end do portal (`portal/`)](#5-back-end-do-portal-portal)
6. [Front-end do portal (`portal/static/`)](#6-front-end-do-portal-portalstatic)
7. [API do portal](#7-api-do-portal)
8. [Arquivos de dados do portal](#8-arquivos-de-dados-do-portal)
9. [Mudanças no Resolver (`web_server/`)](#9-mudanças-no-resolver-web_server)
10. [Mudanças na API de cadastro (`data_entry_server/`)](#10-mudanças-na-api-de-cadastro-data_entry_server)
11. [Proxy e página inicial (`frontend_proxy_server/`)](#11-proxy-e-página-inicial-frontend_proxy_server)
12. [Scripts (`scripts/`)](#12-scripts-scripts)
13. [Testes de desenvolvimento (`dev-tests/`)](#13-testes-de-desenvolvimento-dev-tests)
14. [Como estender](#14-como-estender)
15. [Convenções](#15-convenções)

## 1. Arquitetura

```
 Navegador ─── HTTPS ───► nginx do host (TLS) ──► 127.0.0.1:8080
                                                   │
                         frontend-proxy-service (nginx)
                           ├─ = /, /home/…            → página inicial (estática, na imagem do proxy)
                           ├─ /                       → web-service:4000         resolução (pública)
                           ├─ /api, /swaggerui        → data-entry-service:3000  API de cadastro (token)
                           └─ /portal/                → portal-service:8000      portal de gestão de links
                                                            │ Bearer SESSION_TOKEN, rede interna
                                                            ▼
                                                  data-entry-service:3000/api
 web-service ─┐
 data-entry ──┼──► database-service (MongoDB 27017): resolver_ce (cadastros), resolver_portal (portal)
 portal ──────┘    o portal com usuário próprio, readWrite só em resolver_portal
```

- **web-service** (oficial, alterado) responde às URIs GS1 Digital Link: redirecionamentos, linksets,
  páginas HTML.
- **data-entry-service** (oficial, alterado) é a API JSON que grava os cadastros no MongoDB.
- **portal-service** (novo) é uma aplicação Flask com gunicorn. Ele serve as páginas do portal e é o único
  cliente da API de cadastro usado por pessoas: o navegador fala com `/portal/api/*` usando um documento
  JSON simples e nunca vê o token da API. O portal valida, lê o estado atual, escolhe uma sequência segura
  de chamadas à API e registra quem alterou o quê. Os dados do próprio portal (usuários, metadados dos
  cadastros, diário, entradas recusadas, caches) ficam num banco próprio, `resolver_portal`, acessado por um
  usuário próprio ([ADR 0001](adr/0001-estado-do-portal-no-mongodb.md)).
- **portal-db-init** (novo, roda uma vez) cria ou atualiza esse usuário e termina; o portal sobe depois dele.
- **frontend-proxy-service** (oficial, alterado) encaminha os caminhos acima e serve a página inicial.
- **database-service** (oficial) é o MongoDB.

O Resolver e o portal validam com o **GS1 Barcode Syntax Engine**: o Resolver pelo pacote Node oficial
`gs1encoder` (toda requisição), o portal pela biblioteca C e pelo binding Python da GS1 (atributos de
dados). As regras de chaves e qualificadores do próprio portal espelham o engine e são comparadas com ele
nos testes.

## 2. Estrutura do repositório

Os arquivos acrescentados pelo fork estão marcados como **novo**; os outros são arquivos oficiais com
alterações.

```
.env.example                     padrões de configuração (versionado); o .env guarda os valores da instalação
docker-compose.yml               cinco serviços; .env lido por todos; endereços de bind; volumes nomeados
data_entry_server/src/
  data_entry_namespace.py        /summary, token no /index, BearerAuth no Swagger
  data_entry_logic.py            read_summary()
  data_entry_db.py               read_all_documents()
web_server/src/
  web_logic.py                   subida na hierarquia, formas de linkType, escolha do link, regras de 404, linkset
  web_namespace.py               caminho original, resposta HTML ou JSON, arquivo de descrição, query string,
                                 requisições /eh… e /ex…
  epc_binary.py                  novo: EPC em binário (eh/ex) decodificado para GS1 Digital Link
  tdt/                           novo: artefatos do EPC Tag Data Translation 2.2 (arquivos da GS1, sem alteração)
  web_pages.py                   novo: páginas HTML (erros, linkset) em pt-BR e en-GB
  public/gs1resolver.json        modelo do arquivo de descrição
frontend_proxy_server/
  nginx.conf                     rotas para /, /home/, /portal/, /api, /swaggerui
  home/                          novo: index.html, home.css, home.js, imagens
portal/                          novo: o portal de gestão de links
  app.py                         aplicação Flask: páginas, API, sessões, tarefas em segundo plano
  gs1.py                         chaves, qualificadores, prefixos, tipos de link, idiomas, URIs Digital Link
  syntax.py                      atributos de dados pelo GS1 Barcode Syntax Engine
  label.py                       etiquetas com QR Code (SVG, PNG)
  sheet.py                       importação e exportação de planilhas
  linkcheck.py                   verificador de links com proteção contra SSRF
  store.py                       o banco do portal: conexão, índices, configurações, trava compartilhada
  users.py                       cadastro de usuários e perfis
  meta.py                        quem criou e quem alterou por último cada cadastro
  journal.py                     histórico dos cadastros e auditoria, retenção
  migrate.py                     migração única dos arquivos das versões anteriores para o banco
  db_init.py                     cria o usuário do banco do portal (serviço portal-db-init)
  create_user.py                 administração de usuários pela linha de comando
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  tools/build-syntax-engine.sh   compila o engine (biblioteca C + binding Python)
  assets/fonts/                  Liberation Sans para o texto da etiqueta (OFL)
  Dockerfile, requirements.txt
scripts/                         novo: install.sh, templates/, resolver-backup.sh, resolver-backup.cron
dev-tests/                       novo: testes de desenvolvimento, a camada pytest e o script de screenshots
.github/workflows/dev-tests.yml  novo: integração contínua (testes de desenvolvimento no GitHub Actions)
.github/actions/dev-tests-setup/ novo: preparação do runner para os testes, com as versões fixadas
Documentation/                   índice, guia do portal, funcionalidades, histórico, guia do desenvolvedor,
                                 pt-BR/ (esta documentação em português), extensions/ (documentação
                                 detalhada, changelog), images/, upstream-README.md
tests/, useful_external_python_scripts/   oficiais
```

## 3. Serviços e configuração

| Serviço | Build | Porta | Volumes |
|---|---|---|---|
| `database-service` | `database_server/` | `${DATABASE_BIND_ADDRESS:-0.0.0.0}:27017` | dados do banco |
| `data-entry-service` | `data_entry_server/` | interna 3000 | — |
| `web-service` | `web_server/` | interna 4000 | — |
| `portal-db-init` | `portal/` (`python db_init.py`, roda uma vez a cada início) | — | — |
| `portal-service` | `portal/` (dois estágios: syntax engine, aplicação) | interna 8000 | `resolver-portal-config:/app/config` |
| `frontend-proxy-service` | `frontend_proxy_server/` | `${PROXY_BIND_ADDRESS:-0.0.0.0}:8080` | — |

Todos os serviços leem o `.env.example` e depois o `.env` (Compose ≥ 2.24, `required: false`), então o
`.env` guarda só o que a instalação muda. Os endereços de bind são lidos pelo próprio Compose, só do
`.env`. As variáveis estão descritas no `.env.example` e na seção *Configuration* do README; o portal
também lê `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD`, `PORTAL_DB_HOST` (ou `PORTAL_DB_URI`),
`PORTAL_JOURNAL_*_DAYS`, `PORTAL_SESSION_IDLE_MINUTES`, `PORTAL_SESSION_MAX_HOURS`, `PORTAL_SECRET_KEY`,
`PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT` e `PORTAL_CONFIG_DIR` (e `PORTAL_*_FILE`, os arquivos que a
migração lê). Só o `portal-db-init` recebe o `MONGO_URI` root; o do portal fica vazio.

## 4. Fluxos das requisições

**Uma leitura do código.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. O engine confere a
URI; o Resolver lê o documento de `/01/09506000134352`, escolhe a entrada do conjunto de qualificadores
(subindo para uma entrada menos específica quando não há uma exata), escolhe o link por `linkType`,
idioma, tipo de mídia e contexto, e responde `307` para ele, acrescentando a query string da leitura
exatamente como foi enviada.

**Uma etiqueta NFC com um EPC.** `GET /eh30164596f40c0e5cbe991a83` (ou `/exMBZFlvQMDly-mRqD`) → proxy →
web-service. O segmento único casa com a RE3 da URI Syntax 1.7, então `epc_binary.decompress()` o converte
em `/01/09528765123457/21/123456789123` (mais uma query string quando a etiqueta traz atributos de dados);
daí em diante a requisição é resolvida como a leitura acima, com os atributos decodificados antes da query
string da própria requisição.

**Salvar um cadastro no portal.** O navegador envia `POST /portal/api/record` com `key`, `value`,
`qualifiers`, `description` e `links`. O `app.py`:

1. confere a sessão, o perfil (editor) e o prefixo de empresa GS1 do identificador;
2. `build_document()` valida tudo com o `gs1.py` e monta o documento Resolver CE v3;
3. `store_record()` lê o documento atual (`GET /api/01/…`) e escolhe as chamadas: entrada nova →
   `POST /api/new`; entrada existente → `PUT` (mescla) e depois um `DELETE` parcial dos destinos que o
   usuário removeu, nessa ordem, para o cadastro nunca ficar sem destinos;
4. `record_change()` atualiza os metadados do cadastro (`record_meta`) e acrescenta uma versão ao diário;
5. responde um código de mensagem (`save.created`, `save.updated`), traduzido pelo navegador.

**Excluir um cadastro de uma chave.** A API só exclui o documento inteiro, então `delete_record()` exclui
e regrava as outras entradas com `POST /api/new`; se isso falhar, o documento original é restaurado.

**Importar uma planilha.** `POST /import/preview` lê o arquivo (`sheet.py`), valida cada linha com as
regras do editor, compara com o Resolver e guarda o plano em memória sob um token (30 minutos).
`POST /import/apply` executa o plano numa thread em segundo plano com `store_record()`; o navegador
acompanha por `GET /import/status`.

**Verificar links.** `POST /links/check` (editor) ou `POST /links/jobs` (todos os cadastros, prévia da
importação) iniciam uma tarefa em segundo plano; `linkcheck.check_many()` confere cada endereço uma vez;
`GET /links/jobs/{token}` informa o progresso e os problemas; a última verificação completa fica no banco
(configuração `lastFullCheck`) para `GET /links/last`. Os planos de importação e o progresso das tarefas
continuam na memória do único worker do gunicorn até a etapa 3 do
[ADR 0001](adr/0001-estado-do-portal-no-mongodb.md) levá-los para um worker.

## 5. Back-end do portal (`portal/`)

### `app.py` — a aplicação

Organizado em seções (linhas de comentário `# ---- …`):

| Seção | Conteúdo |
|---|---|
| configuration | ambiente, configurações do Flask (cookie de sessão `gs1resolver_portal`, HttpOnly, SameSite=Lax, Secure em HTTPS, validade renovada a cada uso), loggers (`portal`, `portal.audit`); no início `migrate.run()`, `journal.apply_retention()` e depois o primeiro usuário por `PORTAL_ADMIN_*` |
| authentication | `LoginThrottle` (5 falhas → 15 minutos, por usuário e por endereço, na coleção `login_failures`), `current_user()` com a impressão digital da senha, `require_login`, `role_required()`, `allowed()` / `check_access()` para os prefixos, conferência da origem nas gravações, cabeçalhos de segurança, tratadores de erro |
| resolver API client | `resolver()` (uma chamada à API com o token), `read_entries()`, `find_entry()`, `describe_entry()` (produto, qualificado ou outro), `record_change()` |
| form → Resolver CE v3 | `request_key()`, `request_qualifiers()`, `build_document()` |
| pages and assets | `/portal/`, `/portal/login`, arquivos estáticos (`PUBLIC_ASSETS` antes de entrar, `PRIVATE_ASSETS` depois) |
| portal API | entrar, sair, senha, saúde, `/config`, `/record` (GET, POST, DELETE) com `store_record()`, `/records` |
| spreadsheets | `/export`, `/import/preview`, `/import/apply`, `/import/status`, `_run_import()` |
| link checker | `/links/check`, `/links/jobs`, `/links/jobs/{token}`, `/links/last`, `_run_link_job()` |
| governance | `/users` (GET, POST, PUT, DELETE, reset), `/history`, `/audit`, `/audit.csv` |
| labels | `qr_version()`, `qr_error_level()`, `/digital-link`, `/qrcode` |

Erros são exceções com um código de mensagem: `gs1.ValidationError` (422), `AccessDenied` (403),
`users.UserError` (422), `UpstreamError` (502/503, detalhe só no log). Importações e verificações de
links ainda ficam em memória; por isso o portal roda um único worker do gunicorn, com threads, até a etapa 3
do ADR 0001.

### `gs1.py` — regras GS1

- `PRIMARY_KEYS`: AI → (nome, validador) para as 16 chaves primárias da URI Syntax 1.7 §4.3. Os
  validadores são montados com funções pequenas: `_numeric_key(length)`, `_with_serial(base, serial_max,
  filler)`, `_alnum_key(maximum)`, `_itip`, `_gmn` (par de caracteres, `gmn_check_pair()`), `_cpid`,
  `_gcn`, `_gtin` (`normalise_gtin()`, qualquer tamanho → 14 dígitos).
- `KEY_SHAPES`: para cada chave, os conjuntos alternativos de qualificadores permitidos juntos e quais são
  obrigatórios; `QUALIFIER_FORMATS` e `QUALIFIER_ORDER`, `normalise_qualifiers()` (formato, combinação e a
  ordem da §4.9), `parse_qualifier_text()` (`(10)L1(21)S1` ou `/10/L1/21/S1`), `is_valid_qualifier_set()`,
  `qualifier_list()` / `pairs_from()` (Resolver CE `[{AI: valor}]` ↔ pares), `qualifier_path()`,
  `qualifiers_match()`.
- Modelo de cadastro do GS1-Conformant Resolver 1.2.1 §2.5.9: `INFORMATIVE_QUALIFIERS` (em 01 e 8006, com o
  AI 21 os AIs 22 e 10 são informativos), `split_informative()` (os qualificadores de um Digital Link → os do
  cadastro e os informativos), `join_informative()` (o caminho de volta, na ordem do caminho) e
  `has_key_level()` (se a chave pode ter cadastro sem qualificadores: o 415 não pode). No `app.py`,
  `request_record()` identifica o cadastro pelos qualificadores dele; abrir, salvar, excluir e histórico usam
  isso, enquanto a etiqueta e o QR Code usam todos os qualificadores. `key_record_document()` monta o
  cadastro da chave pedido ao salvar (`keyRecord`).
- `normalise_key()`, `anchor_for()`, `split_anchor()`, `digital_link()`, `hri_lines()`, `element_string()`.
- `company_part()` / `within_prefixes()` para a governança; `link_key()` (tipo + idiomas + contexto).
- `normalise_language()` (qualquer tag BCP 47).
- Texto: `without_invisible()`, `ascii_digits()`, `clean_text()` (NFC, sem caracteres de controle),
  `normalise_url()` (só HTTPS, sem espaços nem caracteres invisíveis), `guess_media_type()`.
- `LINK_TYPES` (29 tipos de link GS1, agrupados), `LANGUAGES`, `MAX_DESCRIPTION`.

### `syntax.py` — atributos de dados

`Engine` (uma instância, `syntax.ENGINE`) carrega a `libgs1encoders.so` e o binding Python da GS1 de
`GS1_SYNTAX_ENGINE_DIR` (compilados por `tools/build-syntax-engine.sh`, versão 1.4.1). Sem eles,
`available` é falso e a opção some. A partir do Syntax Dictionary do engine (`parse_dictionary()`) ele
monta os atributos permitidos na query string (AIs marcados com `?`), as famílias de AIs decimais
(`decimal_families()`, `310n`…) e os AIs que pertencem ao caminho de cada chave. `describe()` alimenta o
`/config`; `resolve_decimal()` converte `123,45` numa família; `digital_link()` confere os atributos de um
cadastro (dia 00, repetidos, AIs do caminho recusados, depois os linters e as regras de associação do
próprio engine) e devolve a URI e as linhas de HRI, ou lança `ValidationError` com um código de mensagem.
As chamadas ao engine são serializadas por um lock.

### `label.py` — etiquetas com QR Code

`LabelOptions` (URI, linhas de HRI, mostrar HRI, versão, nível) → `symbol()` (segno, `micro=False`,
`boost_error=False`; `DoesNotFit` com a versão necessária e o nível que cabe) → `_layout()` (módulos, zona
de silêncio de 4, texto de 2,2 mm com as métricas da Liberation Sans) → `render_svg()` (milímetros com
X = 0,495 mm, texto como contornos dos glifos) ou `render_png()`.

### `sheet.py` — planilhas

`FORMATS` (limites por formato), `detect_format()`, `read_table()` (`_read_xlsx`, `_read_csv` com detecção
de codificação e separador), `map_header()` (títulos de coluna em qualquer idioma, apelido antigo `gtin`),
`parse_rows()` (linhas → cadastros, com todos os erros de linha), `export_rows()`, `write_csv()`,
`write_xlsx()` (com abas de referência), `protect()` / `unprotect()` contra fórmulas.

### `linkcheck.py` — verificador de links

`check_url()` (cache de 10 minutos na coleção `linkcheck_cache`, comum a todas as réplicas) → `_check()`: segue os redirecionamentos manualmente (no máximo 5),
resolve cada host e recusa endereços privados, de loopback e link-local a cada passo, usa `HEAD` e recorre
ao `GET` sem ler o corpo, aponta rebaixamentos de HTTPS para HTTP. `check_many()` usa um pool de threads
com progresso.

### `store.py`, `users.py`, `meta.py`, `journal.py` — o banco do portal

O `store.py` guarda um cliente do MongoDB por processo (`store.db()`, criado e indexado na primeira chamada;
`store.col(nome)`), as configurações de conexão (`PORTAL_DB_*`, ou `PORTAL_DB_URI`; `mongomock://` nos
testes de desenvolvimento), datas em UTC (`now()`, `iso()`, `parse_iso()`), valores na coleção `settings`
(`get_setting()`, `set_setting()`) e `lock(nome)`, uma trava exclusiva comum a todos os processos (um
documento `lock:<nome>` em `settings`; uma trava mais velha que `hold_seconds` é quebrada). O `users.py`
grava sob a trava `users`, para que dois administradores não removam o último administrador ativo no mesmo
instante; também gera os hashes das senhas (Werkzeug), gasta o mesmo tempo para usuários inexistentes e
calcula a impressão digital da sessão. O `meta.py` guarda criação e última alteração de cada cadastro. O
`journal.py` grava um documento por evento, com sua categoria (`session`, `record`, `admin`) e `expiresAt`;
`for_record()` e `search()` mantêm a saída das antigas linhas do `journal.jsonl`; `apply_retention()`
atualiza o `expiresAt` quando `PORTAL_JOURNAL_*_DAYS` muda. A seção 8 lista as coleções.

### `migrate.py`, `db_init.py`

`migrate.run(config_dir)` leva `users.json`, `records-meta.json` e `journal.jsonl` para coleções vazias uma
única vez, sob a trava `migration`, com `_id` fixos para que uma importação interrompida termine no início
seguinte; os arquivos viram `*.migrated`. O `db_init.py` (serviço `portal-db-init`) conecta com o
`MONGO_URI` root e cria o usuário do portal, ou atualiza sua senha e permissões; recusa `admin`, `local`,
`config` e `resolver_ce` como banco do portal.

### `create_user.py`

`docker compose exec portal-service python create_user.py <nome> [--role …] [--prefixes …] [--remove]`
cria um usuário ou define a senha (pedida duas vezes), o perfil e os prefixos, ou exclui um usuário.

## 6. Front-end do portal (`portal/static/`)

Sem framework e sem etapa de build: HTML, CSS e JavaScript puros servidos como arquivos estáticos.

| Arquivo | Papel |
|---|---|
| `index.html` | a página do portal: cabeçalho com menus de idioma e de usuário, editor (três passos, outros cadastros, histórico), bloco da etiqueta, lista de registros, usuários, auditoria, janelas (opções, importação), o modelo de uma linha de destino |
| `login.html`, `login.js` | página de entrada |
| `password.js` | botão de mostrar/ocultar em cada campo de senha |
| `i18n.js` | catálogo de mensagens (pt-BR, en-GB) e motor de tradução |
| `app.js` | todo o resto; um mapa das seções está no início do arquivo |
| `app.css` | estilos; media queries depois das regras que alteram |

**Visões.** O fragmento do endereço escolhe a visão (`#records`, `#users`, `#audit`, senão o editor), então
o botão voltar do navegador e os favoritos funcionam (`applyView()`).

**Tradução.** Os elementos declaram seus textos: `data-i18n="chave"`, `data-i18n-params='{…}'`,
`data-i18n-attr="placeholder:chave;aria-label:chave"`. `I18N.apply()` renderiza todos; `I18N.set(el,
chave, params)` define um; `t(chave, params)` devolve um texto. O idioma vem da escolha salva, do cookie
`gs1resolver_lang` (compartilhado com a página inicial e as páginas do Resolver) ou do navegador. As
respostas do servidor trazem códigos (`save.updated`, `key.checkDigit`…) com parâmetros, renderizados pelo
mesmo catálogo.

**Validação.** `readKey()` e `readQualifiers()` repetem as regras do servidor para dar retorno imediato; o
servidor confere de novo e é a autoridade.

**Lista de registros.** `loadRecords()` busca `/records` uma vez; `renderRecords()` filtra no navegador por
tipo de chave (`#records-key`), qualificador (`qualifierMatches()`), autor, problemas de link e texto
(`fold()` ignora maiúsculas e acentos). `parseCode()` lê um GS1 Digital Link colado ou uma element string
com parênteses, e `codeRank()` ordena os cadastros pela relação com ele (exato, mais geral, mais
específico).

## 7. API do portal

Base `/portal/api`, cookie de sessão, JSON. Gravações exigem a `Origin` do próprio portal e corpo JSON.
Toda chamada confere o perfil e limita os identificadores aos prefixos de empresa GS1 do usuário. Erros
respondem `{"code": "...", "params": {...}}`.

| Método e caminho | Perfil | Para quê |
|---|---|---|
| `POST /login` `{username, password}` | — | Entrar (429 `auth.locked` quando bloqueado) |
| `POST /logout` | — | Sair |
| `POST /password` `{currentPassword, newPassword}` | qualquer | Trocar a senha; outras sessões são encerradas |
| `GET /config` | qualquer | Usuário, perfil, prefixos, endereço do Resolver, tipos de link, chaves com qualificadores e combinações, idiomas, limites de importação, atributos de dados, limites da sessão (`session`: `idleSeconds`, `warningSeconds`, `endsIn`, `maxHours`) |
| `GET /session` | qualquer (também enquanto uma nova senha é exigida) | Renova a sessão; responde os mesmos limites da sessão |
| `GET /record?key=&value=&qualifiers=/10/L1` | leitor | Um cadastro: `exists`, `description`, `links`, `defaultLinkType`, `sharedDefaultLinkType`, `digitalLink`, `otherEntries` (cada um com `informative`), `qualifiers` (os do cadastro), `informative` (digitados) e `storedInformative`, `hasKeyRecord` |
| `POST /record` `{key, value, qualifiers, description, links:[{linkType, url, title, hreflang, forwardQueryString}], keyRecord?}` | editor | Criar (201) ou substituir (200); o primeiro link é o principal. Com número de série, 22 e 10 em `qualifiers` são gravados como informativos. `keyRecord: {mode: copy\|target, description, url}` cria antes o cadastro da chave (`save.createdWithKey`, `keyRecordCreated`) |
| `DELETE /record?key=&value=&qualifiers=` | editor | Excluir um cadastro, mantendo os outros da chave |
| `GET /records` | leitor | Todos os cadastros com tipo, qualificadores, `informative`, descrição, tipo principal, número de links, criado/alterado por e quando, `noKeyRecord`, `breaksRules` |
| `POST /export` `{format: xlsx\|csv, labels}` | leitor | Planilha com todos os cadastros |
| `POST /import/preview` `{filename, data (base64), labels, checkLinks}` | editor | Validação e comparação; `token`, `records` (com `informative`, `informativeBefore`, `noKeyRecord`), `errors`, `counts`, `links`, `keysWithoutRecord` |
| `POST /import/apply` `{token, createKeyRecords?}` · `GET /import/status?token=` | editor | Gravar uma importação conferida (com `createKeyRecords`, antes os cadastros das chaves); progresso e resultados |
| `POST /links/check` `{urls}` | editor | Verificar endereços (editor) |
| `POST /links/jobs` `{scope: all\|urls}` · `GET /links/jobs/{token}` · `GET /links/last` | editor · editor · leitor | Verificação de links em segundo plano |
| `GET /history?key=&value=&qualifiers=` | leitor | Versões de um cadastro, com conteúdo |
| `GET /users` · `POST /users` · `PUT /users/{nome}` · `POST /users/{nome}/reset` · `DELETE /users/{nome}` | administrador | Administração de usuários; senhas temporárias na resposta |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | administrador | Auditoria |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | leitor | Digital Link com atributos de dados conferidos pelo engine; nada é gravado |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:valor` | leitor | Etiqueta; cabeçalhos `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`; 422 `qr.tooSmall` / `qr.tooLong` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable"}` |

## 8. Dados do portal

O banco do portal (`PORTAL_DB_NAME`, padrão `resolver_portal`), incluído no dump diário do MongoDB.
Decisões e seus motivos: [ADR 0001](adr/0001-estado-do-portal-no-mongodb.md).

| Coleção | `_id` e conteúdo | Índices |
|---|---|---|
| `users` | nome de usuário; `hash`, `role`, `prefixes`, `disabled`, `mustChange`, `created`, `lastLogin` | — |
| `record_meta` | chave do cadastro (GTIN pelos 14 dígitos, as outras chaves por `AI/valor`, mais o caminho dos qualificadores); `createdAt`, `createdBy`, `updatedAt`, `updatedBy` | — |
| `journal` | ObjectId (`jsonl-<linha>` nos eventos migrados); `at` (data), `user`, `action`, `category`, `anchor`, `qpath`, `doc`, `detail`, `expiresAt`. Ações de cadastro `create`, `update`, `delete` (com o conteúdo do cadastro), `import`; outras: `login`, `login-failed`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove` | data; cadastro + data; usuário + data; categoria; TTL em `expiresAt` |
| `login_failures` | `key` (`user:<nome>` ou `addr:<endereço>`), `at` | chave + data; TTL de 15 minutos em `at` |
| `linkcheck_cache` | endereço; `result`, `expiresAt` | TTL em `expiresAt` |
| `settings` | `lastFullCheck`, `journalRetention`, `migration` e os documentos `lock:<nome>` | — |

Retenção do diário: um evento é guardado por `PORTAL_JOURNAL_SESSION_DAYS` (180), `PORTAL_JOURNAL_RECORD_DAYS`
(0) ou `PORTAL_JOURNAL_ADMIN_DAYS` (0) dias a partir do fim do dia em que aconteceu; 0 guarda para sempre.

O volume `resolver-portal-config` (`/app/config`, no backup diário) guarda o `secret.key`, a chave de sessão
usada quando `PORTAL_SECRET_KEY` não está definida, e os arquivos das versões anteriores renomeados
`*.migrated`.

## 9. Mudanças no Resolver (`web_server/`)

- `web_logic.py`: `normalise_linktype()` (todas as formas aceitas de tipo de link),
  `_parse_qualifier_path()` e `_entry_applies()` (subida na hierarquia: uma entrada vale quando todos os
  seus qualificadores estão na requisição, com modelos como `{0}` aceitando qualquer valor; a entrada mais
  específica responde primeiro — uma série ou TPX (`_UNIT_QUALIFIERS`) antes de qualquer lote ou variante,
  depois mais qualificadores antes de menos; qualificadores informativos nunca são lidos),
  `_qualifier_path_from()` (valores com percent-encoding), `_find_linktype_key()`, `_public_link()` (só campos
  públicos; `fwqs` retirado), `format_linkset_for_external_use()` (RFC 9264 ou JSON-LD); 404 quando falta o
  tipo de link.
  Escolha do link (item 1.5): `_handle_link_type()` segue a seção 2.6.3 — sem `linkType` só `gs1:defaultLink`
  e `gs1:defaultLinkMulti` concorrem, e uma variante só vence quando a requisição a indica; `choose_links()`
  (tipo de mídia, depois `_language_match()` com `language_ranges()` — pesos q, busca da RFC 4647 — depois
  contexto) substitui os `_match_*()` oficiais; `with_default_multi()` publica e usa vários links do tipo
  principal da chave como `gs1:defaultLinkMulti`; um 300 leva a âncora do seu nível.
  `format_linkset_for_external_use()` escreve toda chave de tipo de link por `public_linktype_key()`, de modo
  que os clientes veem o namespace `gs1:` da seção 2.14 (`GS1_VOC`, `https://ref.gs1.org/voc/`), enquanto os
  documentos mantêm as chaves `https://gs1.org/voc/`, que `_find_linktype_key()` e o código de cadastro usam.
  `_test_gs1_digital_link_syntax()` envia `https://id.gs1.org` + o caminho codificado ao `callGS1encoder.js`,
  que usa o leitor de Digital Link do engine (`dataStr`) para uma URI e mantém `aiDataStr` para uma element
  string.
- `web_namespace.py`: `_request_segments()` e `_resolve_path()` (o caminho a partir da URI original,
  `RAW_URI`, cada segmento decodificado separadamente, para o `%2F` ficar no seu valor),
  `_extract_query_strings()` (a query string original), `_wants_html()` (navegador, cliente de API, ou sem
  cabeçalho `Accept`: HTML), `_resolver_description()` (arquivo de descrição a partir de `FQDN`, `RESOLVER_*`
  e `RESOLVER_TERMS_URL`, sem `_id`), `_bad_request()`, `_append_query()` (query string unida com `&`), o 300
  como linkset ou página, `_latin1()` (cabeçalhos `Location` seguros), barra no final aceita.
- `web_namespace.py`, item 1.6: `_handle_request()` envia um segmento que casa com
  `epc_binary.COMPRESSED_EPC` (RE3) para `_resolve_compressed_epc()`: decodifica, confere os atributos de
  dados junto com o caminho por `_test_gs1_digital_link_syntax()` (o `_SAFE_GS1_PATTERN` admite `?`, `=` e
  `&` para isso) e chama `_process_response()` com os atributos decodificados seguidos da query string da
  requisição; um `EpcDecodeError` responde 400 com o motivo. Os demais segmentos únicos continuam indo para o
  toolkit oficial (compressão antiga do Digital Link 1.1).
- `epc_binary.py` (novo, item 1.6), a partir do EPCB 1.0.0, do TDS 2.3 e do TDT 2.2:
  - `compression_bits()` (`eh`: 4 bits por caractere; `ex`: 6 bits, alfabeto da RFC 4648, seção 5);
    `decode_binary()` escolhe o esquema pelo cabeçalho de 8 bits (`prefixMatch` do nível BINARY; os
    cabeçalhos `++` de `PLUS_PLUS` apontam para o esquema `+` correspondente); `decompress()` faz as duas
    coisas. O resultado, `DecodedEpc`, dá `path()` (chave primária e seus `gs1DigitalLinkKeyQualifiers` na
    ordem, valores com percent-encoding), `query()` (os demais AIs) e `uri(stem)`, além do esquema, filtro,
    bit de toggle e hostname.
  - Esquemas anteriores ao TDS 2.0, `_decode_tdt_scheme()`: a opção do nível BINARY cujo `pattern` casa;
    cada campo como inteiro ou, com `compaction`, como caracteres (`_decode_characters()`); preenchimento
    conforme o nível de saída ou, na falta dele, o nível tag-encoding (figura 3-6 do TDT); regras EXTRACT do
    BINARY e FORMAT do GS1_DIGITAL_LINK (`_call_rule()`: SUBSTR, CONCAT, GS1CHECKSUM, codificações URL/URN);
    a `grammar` do nível preenchida e lida de volta como pares AI/valor. Nada específico de um esquema está
    no código.
  - Esquemas `+` e `++`, `_decode_plus_scheme()`: toggle, filtro e data do DSGTIN+ a partir do artefato; os
    valores de `encodedAI` por `_ai_value()` (linha da Tabela F → `_component()`, um ramo por método do TDS
    14.5); `_hostname()` para `++` (URN Code 40 ou 7 bits com as tabelas de otimização `_HOST_TABLE_A` e
    `_HOST_TABLES_B`, transcritas das Tabelas 14-11 a 14-15 do TDS); `_aidc_data()` para o que vem depois
    (TDS 15.3: Tabela K para o tamanho do AI; para quando restam menos de 8 bits ou há um cabeçalho zero com
    menos de 72 bits).
  - Rigor: os bits depois dos dados precisam ser zero, os valores precisam ser plausíveis (datas, dígitos,
    conjuntos de caracteres, tamanhos), cada AI aparece uma vez. As conferências finais por AI (associações,
    formatos) ficam com o GS1 Barcode Syntax Engine, no servidor web.
  - `tdt/` guarda os arquivos da GS1 como publicados (rascunhos de 18/11/2024 do TDT 2.2), com `+` nos nomes
    como no manifest; para atualizar, substitua os arquivos e rode `dev-tests/resolver/test_epc_binary.py`.
    `TDT_DIR` aponta para outro lugar, se preciso.
- `web_pages.py` (novo): `render_error()` e `render_linkset()` (também a página de escolha do 300, com o
  linkset embutido em JSON-LD) em pt-BR / en-GB, `negotiate_locale()`, o rodapé do operador, só destinos
  `http(s)` como links.

A tabela com cada mudança de comportamento e a cláusula do padrão correspondente está na documentação das
extensões (*Resolver CE changes*).

## 10. Mudanças na API de cadastro (`data_entry_server/`)

- `GET /api/summary[?links=true]` (`DocSummary` → `read_summary()` → `read_all_documents()`): uma linha
  por entrada (âncora, qualificadores, descrição, tipo principal, número de links e, opcionalmente, os
  links).
- `GET /api/index` passou a exigir o token; toda operação protegida declara `security='BearerAuth'`.
- `registration_problem()` (chamada por `create_document()` e `update_document()`): os qualificadores que
  cada chave aceita (`KEY_QUALIFIERS`, URI Syntax 1.7 §4.9), 415 exige 8020, e as regras 1 e 2 do
  GS1-Conformant Resolver 1.2.1 §2.5.9 (235 sozinho; nada de 22 ou 10 com 21). Os valores não são
  conferidos, para que modelos como `{lotnumber}` continuem funcionando; o portal os confere por completo.
- `informativeQualifiers` (`INFORMATIVE_QUALIFIERS`): numa entrada de série de 01 ou 8006, uma lista no
  formato de `qualifiers`, gravada ao lado dela no MongoDB, devolvida pelo `GET` e pelo `/summary`, mesclada
  pelo `PUT` (ausente: mantida; lista vazia: apagada) e por um upsert na mesma entrada. Declarada no modelo
  do Swagger.

## 11. Proxy e página inicial (`frontend_proxy_server/`)

O `nginx.conf` serve `/` e `/home/…` a partir da imagem, envia os caminhos `/` ao web-service (a URI
original, `proxy_pass http://resolver-web/api$request_uri`, para o `%2F` e a query string chegarem como
foram enviados; o nome do upstream é também o cabeçalho Host que o servidor web recebe, então precisa ser um
nome de host válido), `/api` e
`/swaggerui` ao data-entry-service e `/portal/` ao portal-service (com `/portal` → `/portal/`). O
`home/home.js` lê o operador em `/.well-known/gs1resolver` e compartilha a escolha de idioma com o portal.

## 12. Scripts (`scripts/`)

- `install.sh`: instalador para Ubuntu 22.04/24.04 (verificações, perguntas com os valores anteriores como
  padrão, Docker, nginx do host com Certbot ou certificado existente ou proxy externo, `.env` com segredos
  gerados, inicialização, cron de backup). Pode ser rodado de novo; `--non-interactive` lê todas as
  respostas de variáveis de ambiente. Os modelos do site nginx ficam em `templates/`.
- `resolver-backup.sh` + `resolver-backup.cron`: dump do MongoDB pelo contêiner (todos os bancos, o do
  portal incluído) e arquivo do volume do portal, 14 dias guardados.

## 13. Testes de desenvolvimento (`dev-tests/`)

Não precisam de Docker; cada programa termina com status 1 em caso de falha. Os programas do portal usam o
`mongomock` (`PORTAL_DB_URI=mongomock://`, um banco por programa); com `PORTAL_DB_URI` apontando para um
MongoDB real, rodam contra ele. Preparação e comandos em
`dev-tests/README.md`.

| Programa | Verificações | Cobre |
|---|---:|---|
| `resolver/test_resolver.py` | 194 | código do Resolver e da API de cadastro pelo test client do Flask: todas as chaves e cadastros qualificados, subida na hierarquia, tipos de link, regras de 404, schema do linkset, repasse de atributos, schema do arquivo de descrição, páginas HTML, requisições `/eh…` e `/ex…` |
| `resolver/test_epc_binary.py` | 163 | decodificador de EPC em binário: exemplos do EPCB, todos os vetores do anexo E.3 do TDS 2.3 (`eh` e `ex`), dados +AIDC, hostnames `++`, recusas, RE3, artefatos do TDT contra o seu schema; 800 EPCs aleatórios comparados com o `epc-tds` quando `EPC_TDS` está definido (162 sem ele) |
| `resolver/test_gs1_suite.py` | 215 | suíte de testes de Resolver da GS1, com o JavaScript sem alteração no Chromium, contra o código do web server por HTTP; uma versão em Python do seu `tester.php`; sete cenários; precisa de `GS1_RESOLVER_TESTSUITE` e `AJV_DIST` (pulado sem eles) |
| `resolver/test_data_entry_api.py` | 53 | token em toda operação protegida; regras de cadastro do §2.5.9 e qualificadores informativos |
| `portal/test_keys.py` | 137 | chaves e qualificadores, comparados com o GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | perfis, prefixos, usuários, histórico, auditoria |
| `portal/test_sheet.py` | 43 | planilhas, limites por formato |
| `portal/test_special_chars.py` | 57 | caracteres especiais |
| `portal/test_data_attributes.py` | 83 | atributos de dados, famílias decimais, opções do QR (precisa de `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | verificador de links, proteção contra SSRF |
| `portal/test_portal_config.py` | 13 | configuração e inicialização, limites da sessão |
| `portal/test_session.py` | 30 | limites da sessão (15 s sem uso no teste): regras do servidor, aviso, renovação pelo uso, outras abas, limite absoluto, os dois idiomas; aviso da comunidade no rodapé (cerca de dois minutos) |
| `portal/test_store.py` | 58 | a camada de dados do portal: configurações de conexão, índices, a trava compartilhada (também entre dois administradores ao mesmo tempo), usuários, metadados dos cadastros, diário e retenção, bloqueio de entrada, migração dos arquivos antigos (também interrompida e retomada) |
| `portal/test_store_mongodb.py` | 76 | num MongoDB real (`PORTAL_TEST_MONGO_URI`, só no CI): o usuário criado pelo `db_init.py` e suas permissões, o `test_store.py` de novo como esse usuário, o monitor de TTL |
| `portal/test_registration.py` | 26 | §2.5.9 pela API do portal: qualificadores informativos (salvar, abrir, histórico, lista, exportar, importar), cadastros contra a regra 2, o cadastro da chave ao salvar e ao importar |
| `portal/test_portal_e2e.py` | 186 | o portal no Chromium contra o `mock_data_entry.py`, desktop e celular; também roda sem o engine |
| `home/test_home.py` | 55 | página inicial com um nginx real, sem o quadro da sintaxe, aviso da comunidade; rotas do proxy, incluindo que o cabeçalho Host enviado a cada upstream é aceito pelo Werkzeug |
| `install/test_install.sh` | 57 | instalador com simulações (Compose v2) |

**pytest e integração contínua.** O `dev-tests/test_programs.py` roda cada programa acima como um teste
pytest (um subprocesso a partir da raiz do repositório): status 0 sem linha `FAIL` passa; caso contrário, o
relatório mostra as linhas `FAIL` e o fim da saída; um programa que só imprimiu `SKIP` é pulado. Marcadores
os agrupam: `resolver` (Resolver, EPC binário, API de cadastro, suíte da GS1), `portal` (os programas do
portal sem navegador), `e2e` (`test_portal_e2e.py` com e sem o engine, `test_session.py`), `home`, `install`
(rodado por `sudo` sem senha quando não se é root), `database` (`test_store_mongodb.py`). O `dev-tests/conftest.py` impede que o pytest importe os
programas, registra os marcadores e imprime ao final a contagem de verificações de cada programa (e também
no resumo da execução do GitHub Actions). Com `DEV_TESTS_STRICT=1`, um programa falha quando uma variável de
ambiente de que precisa não está definida ou aponta para um caminho inexistente (`needs_env`), quando uma
variável que não é caminho não está definida (`needs_var`), quando um comando de que precisa não está no
PATH, ou quando imprime `SKIP`. Para acrescentar um programa: escreva-o com linhas
`PASS`/`FAIL` e status de saída, acrescente uma linha `Program(...)` a `PROGRAMS` (grupo, caminho, as
variáveis e comandos de que precisa) e uma linha à tabela acima.

O `.github/workflows/dev-tests.yml` roda um job por grupo, em paralelo, a cada push e pull request para
`gs1br/develop` (não para mudanças só em `Documentation/` ou em arquivos Markdown), em modo estrito. O job
`database` sobe um contêiner de serviço `mongo:7` e roda nele os grupos `portal` e `database`. `e2e`,
`install` e `database` são informativos (`continue-on-error`) até provarem estabilidade. A action composta
`.github/actions/dev-tests-setup` instala só o que o job pede e exporta as variáveis: Python 3.12 e Node.js 24
como nas imagens; `gs1encoder`, `epc-tds` e `ajv-dist` em versões fixadas (cache pela versão); o engine do
portal compilado pelo `portal/tools/build-syntax-engine.sh` (cache pelo script, que fixa o release); o
Chromium (cache pela versão do Playwright); a suíte da GS1 no commit `32597c1`; nginx; Docker Compose
v2.29.7. Mude uma versão ali, num lugar só; mantenha o `gs1encoder` no release que o script compila.

O `docs/screenshots.py` regenera as imagens do README e do guia do portal em inglês e em português a partir
do portal real, com dados de exemplo (logotipo GS1 oculto). Versione só as imagens que realmente mudaram.

## 14. Como estender

**Um texto da interface.** Acrescente a chave aos dois idiomas do `i18n.js` (`pt-BR` e `en-GB`) e use-a com
`data-i18n` ou `I18N.set()`. Mensagens do servidor são códigos: lance `ValidationError("meu.codigo",
param=…)` e acrescente `meu.codigo` aos dois idiomas.

**Um idioma.** Copie um bloco de idioma do `i18n.js`, traduza, acrescente-o a `SUPPORTED` e
`LOCALE_MATCHERS`; faça o mesmo em `web_pages.py` (`TEXT`, `LINK_TYPE_LABELS`) e em `home/home.js`.

**Um tipo de link.** Acrescente uma linha a `LINK_TYPES` no `gs1.py` e o nome e a descrição em `linkTypes`
nos dois idiomas; considere o `activeLinkTypes` em `web_server/src/public/gs1resolver.json`.

**Uma chave primária ou um qualificador** (numa versão futura do padrão). Acrescente o validador a
`PRIMARY_KEYS`, as combinações a `KEY_SHAPES` e os formatos a `QUALIFIER_FORMATS` no `gs1.py`; espelhe no
`app.js` (`NUMERIC_KEYS`, `readKey()`, `QUAL_ORDER`, `QUAL_FORMATS`); acrescente os textos `key.<AI>.*` /
`qual.<AI>.*`; amplie o `dev-tests/portal/test_keys.py` e compare com o engine.

**Um endpoint da API.** Acrescente a rota na seção certa do `app.py` com `@require_login` e, para
gravações, `@role_required("editor")`; chame `check_access()` para cada identificador; responda com
códigos de `message()`; registre com `audit.info()` e `log_event()`; acrescente testes; liste-o neste guia,
na versão em inglês e no README.

**Um esquema EPC ou uma nova versão do TDT.** Copie os novos arquivos de definição e tabelas para
`web_server/src/tdt/` (mantendo o `+` nos nomes) e atualize o `manifest.json`; esquemas anteriores ao TDS
2.0 não precisam de código. Um esquema `+` só precisa de código para um formato da Tabela F ou método do
TDS 14.5 que `_component()` não conheça; um esquema `++`, só de uma entrada em `PLUS_PLUS` enquanto o TDT
não tiver artefato para ele. Acrescente o vetor do anexo E do TDS ao `test_epc_binary.py`.

**O syntax engine.** Mude a tag em `portal/tools/build-syntax-engine.sh` e, para manter os dois engines
juntos, fixe a mesma versão do `gs1encoder` em `web_server/Dockerfile`; rode todos os testes.

## 15. Convenções

- Código, comentários, identificadores, mensagens de commit e documentos em inglês britânico; textos para
  o usuário em pt-BR e en-GB; a documentação de uso também em português (`Documentation/pt-BR/`).
- Nomes de variáveis e comportamento oficiais mantidos; mudanças deliberadas documentadas no changelog.
- Nenhum nome de organização nem valor de instância no código: `FQDN`, `RESOLVER_ORG_*`,
  `RESOLVER_CONTACT_*`.
- Segredos nunca impressos nem versionados; o `.env.example` guarda só padrões de desenvolvimento.
- Um assunto por commit, com mensagem explicando o porquê; todos os testes passam antes da entrega.
- Docstrings em todas as funções escritas para o fork; as funções oficiais mantêm a forma original.
- Ao mudar um documento que tem versão nas duas línguas, atualize as duas.
