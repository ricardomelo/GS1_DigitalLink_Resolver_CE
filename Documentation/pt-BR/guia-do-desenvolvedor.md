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
 data-entry ──┴──► database-service (MongoDB 27017)
```

- **web-service** (oficial, alterado) responde às URIs GS1 Digital Link: redirecionamentos, linksets,
  páginas HTML.
- **data-entry-service** (oficial, alterado) é a API JSON que grava os cadastros no MongoDB.
- **portal-service** (novo) é uma aplicação Flask com gunicorn. Ele serve as páginas do portal e é o único
  cliente da API de cadastro usado por pessoas: o navegador fala com `/portal/api/*` usando um documento
  JSON simples e nunca vê o token da API. O portal valida, lê o estado atual, escolhe uma sequência segura
  de chamadas à API e registra quem alterou o quê.
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
  web_logic.py                   subida na hierarquia, formas de linkType, regras de 404, linkset, fwqs
  web_namespace.py               resposta HTML ou JSON, arquivo de descrição, repasse da query string
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
  users.py                       cadastro de usuários e perfis
  meta.py                        quem criou e quem alterou por último cada cadastro
  journal.py                     histórico dos cadastros e auditoria
  create_user.py                 administração de usuários pela linha de comando
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  tools/build-syntax-engine.sh   compila o engine (biblioteca C + binding Python)
  assets/fonts/                  Liberation Sans para o texto da etiqueta (OFL)
  Dockerfile, requirements.txt
scripts/                         novo: install.sh, templates/, resolver-backup.sh, resolver-backup.cron
dev-tests/                       novo: testes de desenvolvimento e o script de screenshots
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
| `portal-service` | `portal/` (dois estágios: syntax engine, aplicação) | interna 8000 | `resolver-portal-config:/app/config` |
| `frontend-proxy-service` | `frontend_proxy_server/` | `${PROXY_BIND_ADDRESS:-0.0.0.0}:8080` | — |

Todos os serviços leem o `.env.example` e depois o `.env` (Compose ≥ 2.24, `required: false`), então o
`.env` guarda só o que a instalação muda. Os endereços de bind são lidos pelo próprio Compose, só do
`.env`. As variáveis estão descritas no `.env.example` e na seção *Configuration* do README; o portal
também lê `PORTAL_SESSION_HOURS`, `PORTAL_SECRET_KEY`, `PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT`
e, nos testes, os caminhos `PORTAL_*_FILE` / `PORTAL_CONFIG_DIR`.

## 4. Fluxos das requisições

**Uma leitura do código.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. O engine confere a
URI; o Resolver lê o documento de `/01/09506000134352`, escolhe a entrada do conjunto de qualificadores
(subindo para uma entrada menos específica quando não há uma exata), escolhe o link por `linkType`,
idioma, tipo de mídia e contexto, e responde `307` para ele, acrescentando a query string da leitura a não
ser que o link tenha `"fwqs": false`.

**Salvar um cadastro no portal.** O navegador envia `POST /portal/api/record` com `key`, `value`,
`qualifiers`, `description` e `links`. O `app.py`:

1. confere a sessão, o perfil (editor) e o prefixo de empresa GS1 do identificador;
2. `build_document()` valida tudo com o `gs1.py` e monta o documento Resolver CE v3;
3. `store_record()` lê o documento atual (`GET /api/01/…`) e escolhe as chamadas: entrada nova →
   `POST /api/new`; entrada existente → `PUT` (mescla) e depois um `DELETE` parcial dos destinos que o
   usuário removeu, nessa ordem, para o cadastro nunca ficar sem destinos;
4. `record_change()` atualiza o `records-meta.json` e acrescenta uma versão ao `journal.jsonl`;
5. responde um código de mensagem (`save.created`, `save.updated`), traduzido pelo navegador.

**Excluir um cadastro de uma chave.** A API só exclui o documento inteiro, então `delete_record()` exclui
e regrava as outras entradas com `POST /api/new`; se isso falhar, o documento original é restaurado.

**Importar uma planilha.** `POST /import/preview` lê o arquivo (`sheet.py`), valida cada linha com as
regras do editor, compara com o Resolver e guarda o plano em memória sob um token (30 minutos).
`POST /import/apply` executa o plano numa thread em segundo plano com `store_record()`; o navegador
acompanha por `GET /import/status`.

**Verificar links.** `POST /links/check` (editor) ou `POST /links/jobs` (todos os cadastros, prévia da
importação) iniciam uma tarefa em segundo plano; `linkcheck.check_many()` confere cada endereço uma vez;
`GET /links/jobs/{token}` informa o progresso e os problemas; a última verificação completa fica em
memória para `GET /links/last`.

## 5. Back-end do portal (`portal/`)

### `app.py` — a aplicação

Organizado em seções (linhas de comentário `# ---- …`):

| Seção | Conteúdo |
|---|---|
| configuration | ambiente, configurações do Flask (cookie de sessão `gs1resolver_portal`, HttpOnly, SameSite=Lax, Secure em HTTPS, validade renovada a cada uso), loggers (`portal`, `portal.audit`), primeiro usuário por `PORTAL_ADMIN_*` |
| authentication | `Throttle` (5 falhas → 15 minutos, por usuário e por endereço), `current_user()` com a impressão digital da senha, `require_login`, `role_required()`, `allowed()` / `check_access()` para os prefixos, conferência da origem nas gravações, cabeçalhos de segurança, tratadores de erro |
| resolver API client | `resolver()` (uma chamada à API com o token), `read_entries()`, `find_entry()`, `describe_entry()` (produto, qualificado ou outro), `record_change()` |
| form → Resolver CE v3 | `request_key()`, `request_qualifiers()`, `build_document()` |
| pages and assets | `/portal/`, `/portal/login`, arquivos estáticos (`PUBLIC_ASSETS` antes de entrar, `PRIVATE_ASSETS` depois) |
| portal API | entrar, sair, senha, saúde, `/config`, `/record` (GET, POST, DELETE) com `store_record()`, `/records` |
| spreadsheets | `/export`, `/import/preview`, `/import/apply`, `/import/status`, `_run_import()` |
| link checker | `/links/check`, `/links/jobs`, `/links/jobs/{token}`, `/links/last`, `_run_link_job()` |
| governance | `/users` (GET, POST, PUT, DELETE, reset), `/history`, `/audit`, `/audit.csv` |
| labels | `qr_version()`, `qr_error_level()`, `/digital-link`, `/qrcode` |

Erros são exceções com um código de mensagem: `gs1.ValidationError` (422), `AccessDenied` (403),
`users.UserError` (422), `UpstreamError` (502/503, detalhe só no log). Importações, verificações de links
e o bloqueio de tentativas ficam em memória; por isso o portal roda um único worker do gunicorn, com
threads.

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

`check_url()` (cache de 10 minutos) → `_check()`: segue os redirecionamentos manualmente (no máximo 5),
resolve cada host e recusa endereços privados, de loopback e link-local a cada passo, usa `HEAD` e recorre
ao `GET` sem ler o corpo, aponta rebaixamentos de HTTPS para HTTP. `check_many()` usa um pool de threads
com progresso.

### `users.py`, `meta.py`, `journal.py` — arquivos do portal

Pequenos armazenamentos para os arquivos da seção 8. Toda gravação é atômica (arquivo temporário +
renomear, modo 600) e serializada por um lock de arquivo, então o portal e o `create_user.py` podem
trabalhar ao mesmo tempo. O `users.py` também gera os hashes das senhas (Werkzeug), gasta o mesmo tempo para
usuários inexistentes e calcula a impressão digital da sessão. `journal.search()` filtra eventos por
usuário, datas, texto e permissão de prefixo.

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
| `GET /config` | qualquer | Usuário, perfil, prefixos, endereço do Resolver, tipos de link, chaves com qualificadores e combinações, idiomas, limites de importação, atributos de dados |
| `GET /record?key=&value=&qualifiers=/10/L1` | leitor | Um cadastro: `exists`, `description`, `links`, `defaultLinkType`, `sharedDefaultLinkType`, `digitalLink`, `otherEntries` |
| `POST /record` `{key, value, qualifiers, description, links:[{linkType, url, title, hreflang, forwardQueryString}]}` | editor | Criar (201) ou substituir (200); o primeiro link é o principal |
| `DELETE /record?key=&value=&qualifiers=` | editor | Excluir um cadastro, mantendo os outros da chave |
| `GET /records` | leitor | Todos os cadastros com tipo, qualificadores, descrição, tipo principal, número de links, criado/alterado por e quando |
| `POST /export` `{format: xlsx\|csv, labels}` | leitor | Planilha com todos os cadastros |
| `POST /import/preview` `{filename, data (base64), labels, checkLinks}` | editor | Validação e comparação; `token`, `records`, `errors`, `counts`, `links` |
| `POST /import/apply` `{token}` · `GET /import/status?token=` | editor | Gravar uma importação conferida; progresso e resultados |
| `POST /links/check` `{urls}` | editor | Verificar endereços (editor) |
| `POST /links/jobs` `{scope: all\|urls}` · `GET /links/jobs/{token}` · `GET /links/last` | editor · editor · leitor | Verificação de links em segundo plano |
| `GET /history?key=&value=&qualifiers=` | leitor | Versões de um cadastro, com conteúdo |
| `GET /users` · `POST /users` · `PUT /users/{nome}` · `POST /users/{nome}/reset` · `DELETE /users/{nome}` | administrador | Administração de usuários; senhas temporárias na resposta |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | administrador | Auditoria |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | leitor | Digital Link com atributos de dados conferidos pelo engine; nada é gravado |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:valor` | leitor | Etiqueta; cabeçalhos `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`; 422 `qr.tooSmall` / `qr.tooLong` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable"}` |

## 8. Arquivos de dados do portal

Todos no volume `resolver-portal-config` (`/app/config`), incluídos no backup diário.

| Arquivo | Conteúdo |
|---|---|
| `users.json` | `{"maria": {"hash", "role", "prefixes": ["7891234"], "disabled", "mustChange", "created", "lastLogin"}}`; arquivos de antes dos perfis (`{"nome": "<hash>"}`) são lidos como administradores |
| `secret.key` | chave aleatória que assina os cookies de sessão (a não ser que `PORTAL_SECRET_KEY` esteja definida) |
| `records-meta.json` | `{"09506000134352/10/L2026A": {"createdAt", "createdBy", "updatedAt", "updatedBy"}}`; cadastros de GTIN pela chave de 14 dígitos, as outras chaves por `AI/valor` |
| `journal.jsonl` | um evento JSON por linha: `{"at", "user", "action", "anchor"?, "qpath"?, "doc"?, "detail"?}`; ações de cadastro `create`, `update`, `delete` (com o conteúdo do cadastro), `import`; outras: `login`, `login-failed`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove` |

## 9. Mudanças no Resolver (`web_server/`)

- `web_logic.py`: `normalise_linktype()` (todas as formas aceitas de tipo de link),
  `_parse_qualifier_path()` e `_entry_applies()` (subida na hierarquia: uma entrada vale quando todos os
  seus qualificadores estão na requisição, com modelos como `{0}` aceitando qualquer valor; a entrada mais
  específica responde primeiro), `_qualifier_path_from()`, `_find_linktype_key()`, `_public_link()` (só
  campos públicos, `fwqs` mantido), `format_linkset_for_external_use()` (RFC 9264 ou JSON-LD); 404 quando
  falta o tipo de link.
- `web_namespace.py`: `_wants_html()` (navegador ou cliente de API), `_resolver_description()` (arquivo de
  descrição a partir de `FQDN` e `RESOLVER_*`), `_append_query()` (query string unida com `&`, respeitando
  `fwqs`), `_latin1()` (cabeçalhos `Location` seguros), barra no final aceita.
- `web_pages.py` (novo): `render_error()` e `render_linkset()` em pt-BR / en-GB, `negotiate_locale()`, o
  rodapé do operador, só destinos `http(s)` como links.

A tabela com cada mudança de comportamento e a cláusula do padrão correspondente está na documentação das
extensões (*Resolver CE changes*).

## 10. Mudanças na API de cadastro (`data_entry_server/`)

- `GET /api/summary[?links=true]` (`DocSummary` → `read_summary()` → `read_all_documents()`): uma linha
  por entrada (âncora, qualificadores, descrição, tipo principal, número de links e, opcionalmente, os
  links).
- `GET /api/index` passou a exigir o token; toda operação protegida declara `security='BearerAuth'`.

## 11. Proxy e página inicial (`frontend_proxy_server/`)

O `nginx.conf` serve `/` e `/home/…` a partir da imagem, envia os caminhos `/` ao web-service, `/api` e
`/swaggerui` ao data-entry-service e `/portal/` ao portal-service (com `/portal` → `/portal/`). O
`home/home.js` lê o operador em `/.well-known/gs1resolver`, pega a raiz do Resolver da barra de endereços e
compartilha a escolha de idioma com o portal.

## 12. Scripts (`scripts/`)

- `install.sh`: instalador para Ubuntu 22.04/24.04 (verificações, perguntas com os valores anteriores como
  padrão, Docker, nginx do host com Certbot ou certificado existente ou proxy externo, `.env` com segredos
  gerados, inicialização, cron de backup). Pode ser rodado de novo; `--non-interactive` lê todas as
  respostas de variáveis de ambiente. Os modelos do site nginx ficam em `templates/`.
- `resolver-backup.sh` + `resolver-backup.cron`: dump do MongoDB pelo contêiner e arquivo do volume do
  portal, 14 dias guardados.

## 13. Testes de desenvolvimento (`dev-tests/`)

Não precisam de Docker; cada programa termina com status 1 em caso de falha. Preparação e comandos em
`dev-tests/README.md`.

| Programa | Verificações | Cobre |
|---|---:|---|
| `resolver/test_resolver.py` | 128 | código do Resolver e da API de cadastro pelo test client do Flask: todas as chaves e cadastros qualificados, subida na hierarquia, tipos de link, regras de 404, schema do linkset, repasse de atributos, schema do arquivo de descrição, páginas HTML |
| `resolver/test_data_entry_api.py` | 25 | token em toda operação protegida |
| `portal/test_keys.py` | 137 | chaves e qualificadores, comparados com o GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | perfis, prefixos, usuários, histórico, auditoria |
| `portal/test_sheet.py` | 42 | planilhas, limites por formato |
| `portal/test_special_chars.py` | 57 | caracteres especiais |
| `portal/test_data_attributes.py` | 83 | atributos de dados, famílias decimais, opções do QR (precisa de `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | verificador de links, proteção contra SSRF |
| `portal/test_portal_config.py` | 9 | configuração e inicialização |
| `portal/test_portal_e2e.py` | 163 | o portal no Chromium contra o `mock_data_entry.py`, desktop e celular; também roda sem o engine |
| `home/test_home.py` | 44 | página inicial com um nginx real |
| `install/test_install.sh` | — | instalador com simulações (Compose v2) |

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
