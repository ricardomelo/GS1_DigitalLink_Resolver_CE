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
 portal ──────┘    o portal e o portal-worker com usuário próprio, readWrite só em resolver_portal
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
- **portal-worker** (novo) executa as tarefas em segundo plano do portal (importações de planilhas,
  verificações de links) a partir da coleção `jobs`: a imagem do portal com `python worker.py`. O processo web
  só enfileira tarefas e lê seu estado, então nenhuma tarefa depende do processo que a aceitou.
- **frontend-proxy-service** (oficial, alterado) encaminha os caminhos acima e serve a página inicial.
- **database-service** (oficial) é o MongoDB.

**Réplicas.** web-service, data-entry-service, portal-service e portal-worker não guardam estado próprio, então
cada um roda em `*_REPLICAS` contêineres (`.env`, padrão 1; o `deploy.replicas` do Compose), sem
`container_name` fixo. Os três serviços web rodam o gunicorn com `WEB_CONCURRENCY` processos de oito threads
cada (`*_PROCESSES` no `.env`, padrão 2). O proxy acha todas as réplicas pelo DNS do Docker, consultado de novo
a cada 10 segundos (`resolve` nos blocos upstream do `nginx.conf`, nginx 1.30); o banco e o proxy rodam uma
vez só, com os nomes de contêiner oficiais ([ADR 0001](adr/0001-estado-do-portal-no-mongodb.md), etapa 4).

O Resolver e o portal validam com o **GS1 Barcode Syntax Engine**: o Resolver pelo pacote Node oficial
`gs1encoder` (toda requisição), o portal pela biblioteca C e pelo binding Python da GS1 (atributos de
dados). **Uma versão para todos**, escrita uma vez no `docker-compose.yml` (`x-gs1-syntax-engine`) e passada a
toda imagem como argumento de build `GS1_SYNTAX_ENGINE_RELEASE` ([ADR 0003](adr/0003-regras-gs1-do-dicionario.md));
a API de entrada de dados instala o mesmo pacote. As regras de chaves e qualificadores do próprio portal espelham
o engine e são comparadas com ele nos testes.

## 2. Estrutura do repositório

Os arquivos acrescentados pelo fork estão marcados como **novo**; os outros são arquivos oficiais com
alterações.

```
.env.example                     padrões de configuração (versionado); o .env guarda os valores da instalação
docker-compose.yml               sete serviços (quatro com réplicas), mais o mailpit no perfil mail-test; .env lido por todos; endereços de bind; volumes nomeados
data_entry_server/src/
  data_entry_namespace.py        /summary, token no /index, BearerAuth no Swagger
  data_entry_logic.py            read_summary()
  data_entry_db.py               read_all_documents()
web_server/src/
  web_logic.py                   subida na hierarquia, formas de linkType, escolha do link, regras de 404, linkset
  web_namespace.py               caminho original, resposta HTML ou JSON, arquivo de descrição, query string,
                                 requisições /eh… e /ex…
  epc_binary.py                  novo: EPC em binário (eh/ex) decodificado para GS1 Digital Link
  request_log.py                 novo: o registro das requisições ao Resolver: o que é guardado, uma fila e uma thread de gravação (ADR 0006)
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
  tenants.py                     tenants: organizações donas de prefixos de empresa GS1 (ADR 0002)
  meta.py                        quem criou e quem alterou por último cada cadastro
  journal.py                     histórico dos cadastros e auditoria, retenção
  migrate.py                     migração única dos arquivos das versões anteriores para o banco
  jobs.py                        tarefas em segundo plano: estados, retirada, sinal de vida, o anúncio do worker
  worker.py                      o worker de tarefas (serviço portal-worker, ou uma thread com PORTAL_WORKER=embedded)
  mail.py                        e-mail de saída por um relay SMTP; "python mail.py test <endereço>" (ADR 0004)
  mailtexts.py                   os textos das mensagens de e-mail, nos dois idiomas
  tokens.py                      links de uso único: convites e recuperação de senha
  notify.py                      notificações: categorias, as escolhas do usuário, a tarefa "mail"
  apikeys.py                     chaves da API das organizações: criação, hash, revogação, limite de requisições (ADR 0005)
  api_v1.py                      a API das organizações, /portal/api/v1 (importada no fim do app.py), com as chamadas registradas
  requestlog.py                  o registro de requisições como o portal o lê: escopo, listagem, contagens diárias, chamadas da API (ADR 0006)
  openapi.json                   a sua descrição OpenAPI 3.1, servida em /portal/api/v1/openapi.json
  db_init.py                     cria o usuário do banco do portal (serviço portal-db-init)
  create_user.py                 administração de usuários pela linha de comando
  static/                        index.html, login.html, app.js, login.js, password.js, i18n.js, app.css
  gs1dict.py                     o GS1 Barcode Syntax Dictionary: leitor do texto e do gs1_dictionary.json (ADR 0003)
  gs1_dictionary.json            o dicionário da versão do engine no docker-compose.yml, gerado
  engine_messages.py             reconhece as mensagens do engine como códigos de mensagem (traduzidos no i18n.js)
  engine_messages.json           os modelos de mensagem do engine e as mensagens dos linters, gerado
  tools/build-syntax-engine.sh   compila o engine (biblioteca C + binding Python, dicionário, fontes das mensagens)
  tools/gen_dictionary.py        escreve (ou confere com --check) o gs1_dictionary.json a partir de um engine
  tools/gen_engine_messages.py   escreve (ou confere com --check, compara com --summary) o engine_messages.json
  tools/dictionary_diff.py       o que muda entre dois dicionários gerados (a issue semanal)
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

| Serviço | Build | Porta | Volumes | Contêineres |
|---|---|---|---|---|
| `database-service` | `database_server/` | `${DATABASE_BIND_ADDRESS:-0.0.0.0}:27017` | dados do banco | 1 (`database-server`) |
| `data-entry-service` | `data_entry_server/` (gunicorn) | interna 3000 | — | `DATA_ENTRY_SERVICE_REPLICAS` |
| `web-service` | `web_server/` (gunicorn) | interna 4000 | — | `WEB_SERVICE_REPLICAS` |
| `portal-db-init` | `portal/` (`python db_init.py`, roda uma vez a cada início) | — | — | 1 |
| `portal-service` | `portal/` (dois estágios: syntax engine, aplicação; gunicorn) | interna 8000 | `resolver-portal-config:/app/config` | `PORTAL_SERVICE_REPLICAS` |
| `portal-worker` | `portal/` (`python worker.py`) | — | `resolver-portal-config:/app/config` | `PORTAL_WORKER_REPLICAS` |
| `frontend-proxy-service` | `frontend_proxy_server/` (nginx 1.30) | `${PROXY_BIND_ADDRESS:-0.0.0.0}:8080` | — | 1 (`frontend-proxy-server`) |
| `mailpit` | imagem `axllent/mailpit`, só no perfil `mail-test` (um relay de teste, [ADR 0004](adr/0004-e-mail.md)) | `127.0.0.1:8025` (suas páginas e API) | — | nenhum, a menos que iniciado com `--profile mail-test` |

Todos os serviços leem o `.env.example` e depois o `.env` (Compose ≥ 2.24, `required: false`), então o
`.env` guarda só o que a instalação muda. Os endereços de bind, as quantidades de réplicas (`*_REPLICAS`) e
as de processos (`*_PROCESSES`, passadas aos contêineres como `WEB_CONCURRENCY`) são lidos pelo próprio
Compose, só do `.env`. As variáveis estão descritas no `.env.example` e na seção *Configuration* do README; o portal
também lê `PORTAL_DB_NAME`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD`, `PORTAL_DB_HOST` (ou `PORTAL_DB_URI`),
`PORTAL_JOURNAL_*_DAYS`, `PORTAL_SESSION_IDLE_MINUTES`, `PORTAL_SESSION_MAX_HOURS`, `PORTAL_SECRET_KEY`,
`PORTAL_COOKIE_SECURE`, `PORTAL_LINKCHECK_TIMEOUT`, `PORTAL_WORKER`, `PORTAL_CONFIG_DIR` (e `PORTAL_*_FILE`, os
arquivos que a migração lê) e, para o e-mail, `PORTAL_MAIL_HOST`, `PORTAL_MAIL_PORT`, `PORTAL_MAIL_SECURITY`,
`PORTAL_MAIL_USERNAME`, `PORTAL_MAIL_PASSWORD`, `PORTAL_MAIL_FROM`, `PORTAL_MAIL_REPLY_TO`, `PORTAL_MAIL_CA_FILE`,
`PORTAL_MAIL_TIMEOUT`, `PORTAL_INVITE_HOURS` e `PORTAL_RESET_MINUTES`, e para a API das organizações
`PORTAL_API_RATE_PER_MINUTE` e `PORTAL_API_KEY_MAX_DAYS`, e para o registro de requisições `RESOLVER_LOG_DAYS`,
`PORTAL_TIME_ZONE` e `PORTAL_STATS_DAYS`. O Resolver lê `RESOLVER_LOG_DAYS` e `RESOLVER_LOG_COUNTRY_HEADER` e grava o seu
registro com o `MONGO_URI` root que já tem. Do lado do portal, só o `portal-db-init` recebe o `MONGO_URI` root; o do
portal e o do worker ficam vazios. O worker tem as configurações do portal (ele importa o `app.py` e faz a mesma inicialização, o que é
seguro sob as travas compartilhadas).

## 4. Fluxos das requisições

**Uma leitura do código.** `GET /01/09506000134352/10/L2026A` → proxy → web-service. O engine confere a
URI; o Resolver lê o documento de `/01/09506000134352`, escolhe a entrada do conjunto de qualificadores
(subindo para uma entrada menos específica quando não há uma exata), escolhe o link por `linkType`,
idioma, tipo de mídia e contexto, e responde `307` para ele, acrescentando a query string da leitura
exatamente como foi enviada.

**O evento da requisição** ([ADR 0006](adr/0006-registro-de-requisicoes.md)). Toda rota de resolução chama
`request_log.note()` com o que sabe (forma, chave, qualificadores, query string, tipo de link pedido, idiomas, o nível
que respondeu e, num 404, se nenhum cadastro se aplicou ou se faltou o link daquele tipo); `web_logic.read_document()`
passa os dois últimos nas chaves privadas `_level` e `_outcome`, que `_process_response()` retira antes de responder. O
gancho `after_request` da aplicação (`request_log.record()`) acrescenta status, host do destino, tempo gasto, classe
de dispositivo, host do Referer e país, e põe o evento na fila do processo; a thread de gravação insere lotes em
`resolver_log.requests`. A manutenção de hora em hora do worker (`requestlog.aggregate()`) conta cada dia em
`request_daily`.

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
regras do editor, compara com o Resolver e guarda o plano como uma tarefa `prepared` (30 minutos).
`POST /import/apply` a coloca na fila; um worker a retira e o `run_import_job()` grava os cadastros um a um
com `store_record()`, guardando cada resultado logo em seguida; o navegador acompanha por
`GET /import/status`.

**Verificar links.** `POST /links/check` confere de uma vez os poucos destinos de um cadastro.
`POST /links/jobs` (todos os cadastros, prévia da importação) coloca uma tarefa na fila; o `run_link_job()` do
worker confere cada endereço uma vez com `linkcheck.check_many()`; `GET /links/jobs/{token}` informa o
progresso e os problemas; a última verificação completa fica no banco (configuração `lastFullCheck`) para
`GET /links/last`.

**Uma tarefa em segundo plano** ([ADR 0001](adr/0001-estado-do-portal-no-mongodb.md), seção 3.3). Estados
`prepared` → `queued` → `running` → `finished` ou `failed`. O worker devolve à fila as tarefas de workers
calados (`requeue_stale()`: sinal de vida com mais de dois minutos; depois de três tentativas a tarefa falha
com `job.interrupted`), retira atomicamente a tarefa mais antiga da fila (`claim()`) e a executa enquanto uma
thread renova o sinal de vida a cada 10 segundos. Toda gravação de uma tarefa em execução (`Reporter`) só vale
se a tarefa ainda for daquele worker; senão, `JobLost`, e o worker a larga. Uma importação continua do
primeiro cadastro não feito (gravar um cadastro de novo é seguro); uma verificação de links recomeça, e o
cache responde o que já foi conferido. No SIGTERM o worker termina o cadastro em mãos e devolve a tarefa à
fila na hora (`release()`). Uma tarefa na fila há 15 segundos sem nenhum worker anunciado nos últimos 30 é
informada como `stalled`, e o navegador avisa que o processador de tarefas não está em execução. Com
`PORTAL_WORKER=embedded` uma thread de worker roda dentro do processo do portal (testes de desenvolvimento,
instalação mínima); o portal a acorda quando coloca uma tarefa na fila.

## 5. Back-end do portal (`portal/`)

### `app.py` — a aplicação

Organizado em seções (linhas de comentário `# ---- …`):

| Seção | Conteúdo |
|---|---|
| configuration | ambiente, configurações do Flask (cookie de sessão `gs1resolver_portal`, HttpOnly, SameSite=Lax, Secure em HTTPS, validade renovada a cada uso), loggers (`portal`, `portal.audit`); no início `migrate.run()`, `journal.apply_retention()` e depois o primeiro usuário por `PORTAL_ADMIN_*` |
| authentication | `LoginThrottle` (5 falhas → 15 minutos, por usuário e por endereço, na coleção `login_failures`), `current_user()` com a impressão digital da senha e `tenant_blocked()`, `set_scope()` e `require_login`, `role_required()`, `admin_required`, `server_admin_required`, `allowed()` / `check_access()` (dono do identificador = escopo da requisição, depois os prefixos do usuário), `log_event()` (tenant e `byOperator` de cada evento), conferência da origem nas gravações, cabeçalhos de segurança, tratadores de erro |
| resolver API client | `resolver()` (uma chamada à API com o token), `read_entries()`, `find_entry()`, `describe_entry()` (produto, qualificado ou outro), `record_change()` |
| form → Resolver CE v3 | `request_key()`, `request_qualifiers()`, `build_document()` |
| pages and assets | `/portal/`, `/portal/login`, arquivos estáticos (`PUBLIC_ASSETS` antes de entrar, `PRIVATE_ASSETS` depois) |
| portal API | entrar, sair, senha, saúde, `/config`, `/record` (GET, POST, DELETE) com `store_record()`, `/records` |
| spreadsheets | `/export`, `/import/preview`, `/import/apply`, `/import/status`, `run_import_job()` (executada pelo worker) |
| link checker | `/links/check`, `/links/jobs`, `/links/jobs/{token}`, `/links/last`, `run_link_job()` (executada pelo worker) |
| governance | `/users` (GET, POST, PUT, DELETE, reset) com `managed_account()`; `/tenants` (GET, POST, PUT, DELETE) com `record_owners()`; `/support` (POST, DELETE); `/history`, `/audit`, `/audit.csv` |
| labels | `qr_version()`, `qr_error_level()`, `/digital-link`, `/qrcode` |
| background jobs | `JOB_RUNNERS` (tipo de tarefa → função, para o `worker.py`); o worker embutido quando `PORTAL_WORKER=embedded` |

Erros são exceções com um código de mensagem: `gs1.ValidationError` (422), `AccessDenied` (403),
`users.UserError` (422), `UpstreamError` (502/503, detalhe só no log). Desde a etapa 3 do ADR 0001 nada no
portal depende da memória de um processo: o gunicorn roda `WEB_CONCURRENCY` processos (dois por padrão) com
oito threads cada, em cada réplica. O `_secret_key()` grava o `secret.key` reserva num arquivo próprio e o liga
ao nome final, então processos que iniciam juntos leem todos uma mesma chave completa.

### `gs1.py` — regras GS1

- **Montadas a partir do dicionário** ([ADR 0003](adr/0003-regras-gs1-do-dicionario.md)): o `_build()` lê o
  `gs1_dictionary.json` (`gs1dict.load()`) na importação. `PRIMARY_KEYS`: AI → (nome, validador) para todo AI com
  `dlpkey` (as 16 chaves da URI Syntax 1.7 §4.3), na ordem e com os nomes curtos de
  `PORTAL_EXCEPTIONS["key_names"]` (uma chave que um dicionário posterior acrescente vem por último, com o título
  dele). O `key_validator()` escolhe o validador pela forma dos componentes da chave e seus linters
  (`_numeric_key`, `_itip`, `_digits_with_serial`, `_with_serial`, `_alnum_key`, `_gmn` com `gmn_check_pair()`,
  `_cpid`, `_gtin` para `short_gtin`), com os tamanhos do dicionário, e lhe dá um `.spec` que o navegador repete. O
  `qualifier_pattern()` monta o padrão de cada qualificador pelos seus componentes. Só `KNOWN_LINTERS` são aceitos:
  qualquer outro levanta `gs1dict.DictionaryError` na importação.
- `PORTAL_EXCEPTIONS`: o que o portal faz diferente de propósito, cada item com o motivo (conjuntos de caracteres
  de chaves, qualificadores e CPID; ITIP sem 22; GTINs curtos; nomes das chaves). `browser_rules()`: as
  conferências, padrões, tamanhos máximos e a ordem enviados ao navegador no `/config` (`rules`).
- `KEY_SHAPES`: para cada chave, os conjuntos alternativos de qualificadores permitidos juntos e quais são
  obrigatórios (do `dlpkey`: uma alternativa posterior se distingue pelo primeiro qualificador; um qualificador
  no `req` da chave é obrigatório); `QUALIFIER_FORMATS` e `QUALIFIER_ORDER`, `normalise_qualifiers()` (formato, combinação e a
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
`GS1_SYNTAX_ENGINE_DIR` (compilados por `tools/build-syntax-engine.sh` na versão do `docker-compose.yml`). Sem eles,
`available` é falso e a opção some. A partir do Syntax Dictionary do engine (`parse_dictionary()`) ele
monta os atributos permitidos na query string (AIs marcados com `?`), as famílias de AIs decimais
(`decimal_families()`, `310n`…) e os AIs que pertencem ao caminho de cada chave. `describe()` alimenta o
`/config`; `resolve_decimal()` converte `123,45` numa família; `digital_link()` confere os atributos de um
cadastro (dia 00, repetidos, AIs do caminho recusados, depois os linters e as regras de associação do
próprio engine) e devolve a URI e as linhas de HRI, ou lança `ValidationError` com um código de mensagem.
As chamadas ao engine são serializadas por um lock. As demais recusas do engine são `attr.invalid` com o texto em
inglês em `detail` e, quando o `engine_messages.recognise()` conhece o texto, `message`: `{code: "engine.<CODE>",
params: {p1, p2…}}`, sendo a mensagem de um linter dentro dela `engine.lint.<CODE>`. O `i18n.js` tem os dois idiomas
de toda mensagem do engine (a inglesa é o texto do engine) e mostra a tradução no lugar do `detail`.

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

### `store.py`, `users.py`, `tenants.py`, `meta.py`, `journal.py` — o banco do portal

O `store.py` guarda um cliente do MongoDB por processo (`store.db()`, criado e indexado na primeira chamada;
`store.col(nome)`), as configurações de conexão (`PORTAL_DB_*`, ou `PORTAL_DB_URI`; `mongomock://` nos
testes de desenvolvimento), datas em UTC (`now()`, `iso()`, `parse_iso()`), valores na coleção `settings`
(`get_setting()`, `set_setting()`) e `lock(nome)`, uma trava exclusiva comum a todos os processos (um
documento `lock:<nome>` em `settings`; uma trava mais velha que `hold_seconds` é quebrada). O `users.py`
grava sob a trava `users`, para que dois administradores não removam o último administrador ativo no mesmo
instante; também gera os hashes das senhas (Werkzeug), gasta o mesmo tempo para usuários inexistentes e
calcula a impressão digital da sessão. O `users.py` também guarda o tenant e o e-mail do usuário
(`clean_email()`, único), confere que os prefixos de um usuário de tenant ficam dentro dos do tenant e os de um
usuário do operador fora dos de qualquer tenant (`_check_scope()`), e só conta administradores do operador como
administradores do servidor (`is_server_admin()`). O `tenants.py` cria, altera e remove tenants sob a mesma trava
`users` (as regras cruzam as duas coleções: `_check_prefixes()`) e responde `owner(anchor, tenants)`, o tenant
que tem o prefixo de um identificador ([ADR 0002](adr/0002-organizacoes.md)). O `meta.py` guarda criação e
última alteração de cada cadastro, com o tenant que a fez (`visible()` a esconde dos outros escopos). O
`journal.py` grava um documento por evento, com sua categoria (`session`, `record`, `admin`), seu `tenant` e
`byOperator`, e `expiresAt`; `for_record()` (por escopo) e `search()` (com `scope_query()`) mantêm a saída das
antigas linhas do `journal.jsonl`; `apply_retention()` atualiza o `expiresAt` quando `PORTAL_JOURNAL_*_DAYS`
muda. A seção 8 lista as coleções.

**Escopo de uma requisição (ADR 0002).** `set_scope()` põe em `g` a conta (`user`, `account_role`,
`account_tenant`, `server_admin`), todos os tenants (`tenants`, lidos uma vez por requisição) e o que vale:
`tenant` (o tenant do usuário, o tenant de um acesso de suporte aberto, ou `None` para o operador), `role` e
`prefixes` (leitor e o tenant inteiro durante o acesso de suporte), `support`. `allowed()` admite um identificador
cujo dono é `g.tenant` e que está em `g.prefixes`. O worker chama `set_scope()` para o usuário de uma importação
e confere `allowed()` de novo antes de gravar cada cadastro.

### `jobs.py`, `worker.py`

O `jobs.py` é a fila: `create()`, `get()` (a tarefa do usuário, de um tipo, não expirada), `queue_prepared()`,
`status()` (estado, progresso, `stalled`, `error`) e, para os workers, `announce()` / `withdraw()` /
`workers_alive()`, `requeue_stale()`, `claim()` (a tarefa mais antiga da fila cujo `notBefore`, se houver, já
passou), `Reporter` (`beat()`, `progress()`, `record()`, `check_stop()`, `finish(remove=…)`, `defer(seconds)` —
de volta à fila para mais tarde, levantando `Deferred` —, `give_up(code)`), `release()`, `fail()`. Os tipos são
`import`, `linkcheck` e `mail`. Entre as tarefas, mais ou menos uma vez por hora (`HOUSEKEEPING_SECONDS`), o
worker roda o `app.HOUSEKEEPING` (`Worker.housekeep()`; uma tarefa que falha é registrada e as outras rodam): hoje o
`notify_expiring_keys()`. Os tempos são constantes no início (`HEARTBEAT_SECONDS` 10,
`STALE_SECONDS` 120, `MAX_ATTEMPTS` 3, `WORKER_ALIVE_SECONDS` 30, `STALLED_SECONDS` 15, validades de 30 minutos
e de um dia). O `worker.py` tem `Worker` (`run_once()`, `loop()`, `stop()`), `start_embedded()`, `wake()` e
`main()` (o serviço: SIGTERM e SIGINT o param depois do item em mãos); `IN_WORKER_PROCESS` impede que o
`app.py` inicie um worker embutido dentro do processo do worker.

### `mail.py`, `mailtexts.py`, `tokens.py`, `notify.py` — e-mail

[ADR 0004](adr/0004-e-mail.md). O `mail.py` lê `PORTAL_MAIL_*` a cada chamada (`settings()`, `problems()`,
`enabled()`: desligado sem servidor, e com um erro registrado uma vez quando as configurações não combinam), monta
uma mensagem (`message()`: texto simples com alternativa HTML, `Auto-Submitted: auto-generated`, um `Message-ID` do
domínio do remetente) e a envia por uma conexão própria (`send()`): com `starttls` o relay precisa oferecer
STARTTLS antes de qualquer credencial ser enviada, com `tls` a conexão é TLS desde o início, com `none` não há
criptografia nem autenticação (relays de teste). O certificado é sempre verificado (`PORTAL_MAIL_CA_FILE`
acrescenta uma autoridade). `MailError.temporary` separa a falta de conexão, um tempo esgotado ou uma resposta
4xx de uma resposta 5xx ou de um certificado recusado. `python mail.py test <endereço>` envia uma mensagem de
teste na hora e mostra o resultado.

O `mailtexts.py` guarda `TEXTS` (um assunto e um texto simples por mensagem e idioma) e `SIGNATURE`;
`compose(template, language, **params)` preenche os marcadores (um desconhecido continua visível) e faz a
alternativa HTML (escapada, links clicáveis); `language()` converte o idioma de uma página em `pt-BR` ou `en-GB`.
O `tokens.py` emite links de uso único: `issue(user, purpose)` (o link anterior com aquele propósito para de
funcionar; só o SHA-256 é guardado), `peek()`, `consume()` (atômico: `find_one_and_delete`), `purge()`, `link()`; a
validade vem de `PORTAL_INVITE_HOURS` e `PORTAL_RESET_MINUTES`.

O `notify.py` associa cada mensagem a uma categoria (`TEMPLATES`, `CATEGORIES`: `account` e `security` sempre
enviadas, `jobs` opcional e desligada por padrão), confere o destinatário (`reachable()`: ativo, de um tenant
ativo; `wants()`: a escolha do usuário para as categorias opcionais), compõe a mensagem no idioma do usuário e
enfileira uma tarefa `mail` (`send()`, que nunca levanta exceção: a ação que causou a mensagem já aconteceu). O
`run_mail_job()` (em `app.JOB_RUNNERS`) pula uma conta que não pode mais receber, envia, devolve a tarefa à fila por
`RETRY_MINUTES` (1, 5, 15, 60, 120) depois de uma falha temporária (`Reporter.defer()`), a faz falhar depois de uma
definitiva ou da última tentativa (`Reporter.give_up()`, diário `mail-failed` com o modelo e a resposta do relay)
e retira `text` e `html` da tarefa depois de enviada ou falhada.

No `app.py`: `send_link()` (emite um link e enfileira a sua mensagem; o link é retirado quando nada pôde ser
enfileirado), `forgot_password()` (a mesma resposta e pelo menos `RECOVERY_SECONDS` para qualquer entrada; limites
`RECOVERY_PER_LOGIN` e `RECOVERY_PER_ADDRESS` por `LoginThrottle.over()`), `check_password_link()` e
`set_password_by_link()` (`BAD_LINKS_PER_ADDRESS`; a senha definida, os outros links e as sessões da conta
encerrados, uma conta bloqueada liberada), `preferences_of()` e as chamadas de preferências, e as chamadas de
`notify.send()` depois de uma troca de senha, de uma troca de endereço de e-mail, do acesso errado que bloqueia uma
conta, de uma importação e de uma verificação de todos os cadastros. O `create_user()` convida quando pedido, com o
e-mail ligado e um endereço; o `reset_user()` envia um link quando pode (um novo convite para um usuário convidado)
e senão gera uma senha temporária como antes. O `users.py` ganha os campos `invited`, `language`,
`languageChosen` e `notify`, e `clear_password()`, `find_login()` (um nome de usuário, sem diferenciar maiúsculas,
ou um endereço), `note_language()` e `set_preferences()`; `create()` sem senha cria uma conta convidada.

### `apikeys.py`, `api_v1.py`, `openapi.json` — a API das organizações

[ADR 0005](adr/0005-api-das-organizacoes.md). O `apikeys.py` mantém a coleção `api_keys`: `create(name, scopes, days,
prefixes, tenant, created_by)` confere nome, escopos, dias e prefixos (`users._check_scope()`, sob a trava `users`),
recusa mais de `MAX_ACTIVE_KEYS` chaves ativas por escopo e devolve `rk_<id>.<segredo>` uma vez (só o SHA-256 do
segredo é guardado); `load(tenant)`, `public()`, `state()` (`active`, `expired`, `revoked`), `revoke()` (no escopo),
`authenticate()` (formato, id, comparação do hash em tempo constante, situação), `count_request()` (um contador por
chave e minuto em `api_rate`, compartilhado pelas réplicas; a primeira requisição de um minuto grava `lastUsed`) e
`expiring()` (pega cada chave que expira em até uma semana uma vez, de forma atômica).

O `api_v1.py` acrescenta as rotas de `/portal/api/v1` à aplicação do portal. `require_key(scope)` lê a chave do
cabeçalho, a recusa (401 `api.keyMissing` / `api.keyInvalid`, também para uma organização desativada), conta a
requisição (429 `api.rateLimit` com `Retry-After`), confere o escopo (403 `api.scope`) e chama
`app.set_scope("api:<id>", …)` com a organização da chave, o perfil que os seus escopos implicam e os seus prefixos,
de modo que o `allowed()` e todas as regras valem. Os tratadores usam `build_document()`, `store_record()`,
`remove_record()` e `label_response()`, que os endpoints do próprio portal também usam. O `openapi.json` é escrito à
mão; o `test_api.py` o confere contra as rotas e valida respostas com os seus esquemas. No `app.py`: os endpoints de
chaves (`list_api_keys()`, `create_api_key()`, `revoke_api_key()`, sempre no escopo da própria conta),
`notify_expiring_keys()` e `HOUSEKEEPING`.

### `requestlog.py` — o registro das requisições ao Resolver

[ADR 0006](adr/0006-registro-de-requisicoes.md). O Resolver grava os eventos (`web_server/src/request_log.py`, seção
9); este módulo os lê pelo cliente do próprio portal (`store.db().client["resolver_log"]`, só leitura para o usuário
do portal). `scope_filter(tenants, tenant, prefixes, whole)` transforma o escopo de uma requisição num filtro sobre a
parte da empresa `cp` dos eventos (os prefixos de uma organização, ancorados; para o operador, chaves que nenhum
prefixo de organização inicia; restrito aos prefixos do próprio usuário); `app.log_sees_everything()` é verdadeiro
para um administrador do servidor fora de um acesso de suporte e sem prefixos próprios, que vê todos os eventos,
também os sem chave. `list_events(args, scope)` aplica os filtros (`from`/`to` como dias do `PORTAL_TIME_ZONE`, `code`
como âncora, valor de chave, GTIN-13 ou prefixo, `outcome` com `notFound` para os dois 404, `device`, requisições
automatizadas fora a menos que pedidas) e pagina com `before` = `<horário>|<id>` da última linha. `per_day()` lê
`request_daily` para os dias passados e os eventos brutos para hoje. `aggregate()` (em `app.HOUSEKEEPING`) pega a trava
`request-stats` sem esperar (outra réplica com ela: pula), conta cada dia a partir do seguinte ao
`requestStats.finalUntil` (na primeira vez, do evento mais antigo) até hoje com `count_day()` — um `$match` + `$group`
por chave, resultado, dispositivo, forma, idioma e tipo de link, consolidado em Python num documento por chave e um por
dia (`|*`) com percentis do tempo gasto, gravado com uma marca de execução e os documentos do dia de outras execuções
removidos — e então registra o último dia terminado (dez minutos depois da meia-noite, ontem). `record_api_call()` e
`list_api_calls()` guardam e listam as chamadas da API das organizações (`api_requests`); o `api_v1.py` registra cada
chamada num gancho `after_request`, com a chave vista (também uma recusada), o modelo da rota, status e tempo.

### `migrate.py`, `db_init.py`

`migrate.run(config_dir)` leva `users.json`, `records-meta.json` e `journal.jsonl` para coleções vazias uma
única vez, sob a trava `migration`, com `_id` fixos para que uma importação interrompida termine no início
seguinte; os arquivos viram `*.migrated`. O `db_init.py` (serviço `portal-db-init`) conecta com o
`MONGO_URI` root e cria o usuário do portal, ou atualiza sua senha e permissões (`readWrite` no seu banco, `read`
no `resolver_log`); recusa `admin`, `local`, `config`, `resolver_ce` e `resolver_log` como banco do portal.

### `create_user.py`

`docker compose exec portal-service python create_user.py <nome> [--role …] [--prefixes …] [--tenant …] [--email …] [--remove]`
cria um usuário ou define a senha (pedida duas vezes), o perfil, os prefixos e o e-mail, ou exclui um usuário.
`--tenant` (nome ou id) põe um usuário novo numa organização; sem ele o usuário é do operador.

## 6. Front-end do portal (`portal/static/`)

Sem framework e sem etapa de build: HTML, CSS e JavaScript puros servidos como arquivos estáticos.

| Arquivo | Papel |
|---|---|
| `index.html` | a página do portal: cabeçalho com menus de idioma e de usuário, editor (três passos, outros cadastros, histórico), bloco da etiqueta, lista de registros, usuários, auditoria, janelas (opções, importação), o modelo de uma linha de destino |
| `login.html`, `login.js` | página de entrada; com e-mail também *Esqueceu a senha?* e a página que um link abre (`#invite=…` / `#reset=…`: o token é lido, retirado da barra de endereço na hora e enviado; um link colado numa página aberta é tratado pelo `hashchange`) |
| `password.js` | botão de mostrar/ocultar em cada campo de senha |
| `i18n.js` | catálogo de mensagens (pt-BR, en-GB) e motor de tradução |
| `app.js` | todo o resto; um mapa das seções está no início do arquivo |
| `app.css` | estilos; media queries depois das regras que alteram |

**Visões.** O fragmento do endereço escolhe a visão (`#records`, `#requests`, `#users`, `#audit`, senão o editor), então
o botão voltar do navegador e os favoritos funcionam (`applyView()`).

**Tradução.** Os elementos declaram seus textos: `data-i18n="chave"`, `data-i18n-params='{…}'`,
`data-i18n-attr="placeholder:chave;aria-label:chave"`. `I18N.apply()` renderiza todos; `I18N.set(el,
chave, params)` define um; `t(chave, params)` devolve um texto. O idioma vem da escolha salva, do cookie
`gs1resolver_lang` (compartilhado com a página inicial e as páginas do Resolver) ou do navegador. As
respostas do servidor trazem códigos (`save.updated`, `key.checkDigit`…) com parâmetros, renderizados pelo
mesmo catálogo.

**Validação.** `readKey()` e `readQualifiers()` repetem as regras do servidor para dar retorno imediato, a partir
das conferências, padrões, tamanhos e da ordem que o servidor manda em `CONFIG.rules` (`gs1.browser_rules()`,
montado do dicionário); nada no `app.js` repete um tamanho ou um formato. O servidor confere de novo e é a
autoridade.

**E-mail ([ADR 0004](adr/0004-e-mail.md)).** `body[data-mail="on"]` (de `CONFIG.mail.enabled`) mostra os
elementos `.needs-mail`: a caixa de convite do formulário de novo usuário, a seção *E-mail* de Opções
(`fillPreferences()`, `savePreferences()`). `mailLink(u)` diz se uma redefinição vai por e-mail (a pergunta e o
texto do botão seguem ela). `init()` encerra a sessão e volta à página de entrada quando encontra um fragmento de
convite ou recuperação (um link aberto com alguém conectado: a página de entrada redirecionou para cá).

**Chaves de API ([ADR 0005](adr/0005-api-das-organizacoes.md)).** A visão `#apikeys` (administradores) lista as
chaves do escopo da própria conta (`loadApiKeys()`, `apiKeyRow()`), cria uma (`createApiKey()`: a chave e um exemplo
aparecem uma vez) e revoga (`revokeApiKey()`). `forgetNewKey()` retira uma chave nova da página quando se sai da
visão.

**Acessos ([ADR 0006](adr/0006-registro-de-requisicoes.md)).** A visão `#requests` (todos os usuários) desenha os
últimos 30 dias (`loadRequestDays()`: uma barra por dia a partir de `/requests/daily`, respondidas e não encontradas
empilhadas, as automatizadas contadas à parte), lista as últimas requisições (`loadRequests()`, `requestRow()`,
páginas com `next`, os filtros de `requestsQuery()`), as exporta (`downloadRequests()`) e, para administradores,
mostra as chamadas da API das organizações numa segunda aba (`showRequestsTab()`, `loadApiCalls()`).
`body[data-requests-whole]` (de `CONFIG.requestLog.whole`) mostra a coluna da organização. As linhas levam
`data-label` para o layout de celular.

**Lista de registros.** `loadRecords()` busca `/records` uma vez; `renderRecords()` filtra no navegador por
tipo de chave (`#records-key`), qualificador (`qualifierMatches()`), autor, problemas de link e texto
(`fold()` ignora maiúsculas e acentos). `parseCode()` lê um GS1 Digital Link colado ou uma element string
com parênteses, e `codeRank()` ordena os cadastros pela relação com ele (exato, mais geral, mais
específico).

## 7. API do portal

Base `/portal/api`, cookie de sessão, JSON. Gravações exigem a `Origin` do próprio portal e corpo JSON.
Toda chamada confere o perfil e limita os identificadores ao escopo da requisição (o tenant do usuário, um
acesso de suporte, ou o operador) e aos prefixos de empresa GS1 do usuário. Erros respondem
`{"code": "...", "params": {...}}`. "Administrador" abaixo é um administrador de tenant ou do servidor;
"adm. do servidor", um administrador do operador.

| Método e caminho | Perfil | Para quê |
|---|---|---|
| `POST /login` `{username, password}` | — | Entrar (429 `auth.locked` quando bloqueado) |
| `POST /logout` | — | Sair |
| `POST /password` `{currentPassword, newPassword}` | qualquer | Trocar a senha; outras sessões são encerradas; uma mensagem de segurança quando o e-mail está ligado |
| `GET /login/options` | — | `{passwordRecovery}`: se a página de acesso oferece recuperação (e-mail ligado) |
| `POST /password/forgot` `{login, language}` | — | Link de recuperação por e-mail para a conta desse nome de usuário ou endereço, quando ela pode entrar e tem endereço; sempre `password.recoverySent` (404 `password.recoveryOff` com o e-mail desligado, 429 `password.recoveryLimit`) |
| `POST /password/link/check` `{token}` · `POST /password/link` `{token, newPassword, language}` | — | Um link de uso único: `{user, purpose, min}` ou 410 `password.linkInvalid`; depois a senha definida (`password.set`, `purpose`), o link consumido (429 `password.linkLimit` depois de dez links inválidos de um endereço) |
| `GET /preferences` · `PUT /preferences` `{language, notify: {jobs}}` | qualquer | O endereço de e-mail do usuário (só leitura), o idioma das suas mensagens e as categorias opcionais (`preferences.saved`, `preferences.languageInvalid`, `preferences.categoryUnknown`) |
| `GET /config` | qualquer | Usuário, perfil (o que vale), `accountRole`, `serverAdmin`, `tenant` e `support` (`{id, name, disabled}` ou `null`), prefixos, endereço do Resolver, tipos de link, chaves com qualificadores e combinações, idiomas, limites de importação, atributos de dados, limites da sessão (`session`: `idleSeconds`, `warningSeconds`, `endsIn`, `maxHours`), `mail` (`{enabled}`), `requestLog` (`{days, whole}`: a retenção do registro, 0 quando desligado, e se o usuário vê a instalação inteira) e `preferences` (como `GET /preferences`) |
| `GET /session` | qualquer (também enquanto uma nova senha é exigida) | Renova a sessão; responde os mesmos limites da sessão |
| `GET /record?key=&value=&qualifiers=/10/L1` | leitor | Um cadastro: `exists`, `description`, `links`, `defaultLinkType`, `sharedDefaultLinkType`, `digitalLink`, `otherEntries` (cada um com `informative`), `qualifiers` (os do cadastro), `informative` (digitados) e `storedInformative`, `hasKeyRecord` |
| `POST /record` `{key, value, qualifiers, description, links:[{linkType, url, title, hreflang, forwardQueryString}], keyRecord?}` | editor | Criar (201) ou substituir (200); o primeiro link é o principal. Com número de série, 22 e 10 em `qualifiers` são gravados como informativos. `keyRecord: {mode: copy\|target, description, url}` cria antes o cadastro da chave (`save.createdWithKey`, `keyRecordCreated`) |
| `DELETE /record?key=&value=&qualifiers=` | editor | Excluir um cadastro, mantendo os outros da chave |
| `GET /records` | leitor | Todos os cadastros com tipo, qualificadores, `informative`, descrição, tipo principal, número de links, criado/alterado por e quando, `noKeyRecord`, `breaksRules` |
| `POST /export` `{format: xlsx\|csv, labels}` | leitor | Planilha com todos os cadastros |
| `POST /import/preview` `{filename, data (base64), labels, checkLinks}` | editor | Validação e comparação; `token`, `records` (com `informative`, `informativeBefore`, `noKeyRecord`), `errors`, `counts`, `links`, `keysWithoutRecord` |
| `POST /import/apply` `{token, createKeyRecords?}` · `GET /import/status?token=` | editor | Colocar na fila do worker uma importação conferida (com `createKeyRecords`, antes os cadastros das chaves); `state` (`queued`, `running`, `finished`, `failed`), `done`, `total`, `stalled`, `error` e, ao terminar, os resultados |
| `POST /links/check` `{urls}` | editor | Verificar endereços (editor) |
| `POST /links/jobs` `{scope: all\|urls}` · `GET /links/jobs/{token}` · `GET /links/last` | editor · editor · leitor | Verificação de links em segundo plano (estado: `state` `queued`\|`running`\|`finished`\|`failed`, `done`, `total`, `stalled`, `error`) |
| `GET /history?key=&value=&qualifiers=` | leitor | Versões de um cadastro feitas no escopo da requisição, com conteúdo |
| `GET /users` · `POST /users` `{username, role, prefixes, email, tenant}` · `PUT /users/{nome}` `{role, prefixes, email, disabled}` · `POST /users/{nome}/reset` · `DELETE /users/{nome}` | administrador | Administração de usuários: o adm. do servidor gerencia todos os usuários (`tenant` escolhe a organização; a resposta do GET acrescenta `tenants`), o administrador de um tenant os usuários do seu tenant; `tenantName` e `invited` em cada usuário; senhas temporárias na resposta. Com o e-mail ligado: `POST /users` com `invite` e um endereço responde `users.invited` sem senha; `reset` responde `users.resetSent` (um link por e-mail) para um usuário com endereço |
| `GET /tenants` · `POST /tenants` `{name, prefixes}` · `PUT /tenants/{id}` `{name, prefixes, disabled}` · `DELETE /tenants/{id}` | adm. do servidor | Organizações; o GET acrescenta `users` e `records` por tenant e `operatorRecords` |
| `POST /support` `{tenant, reason}` · `DELETE /support` | adm. do servidor | Abrir e fechar o acesso de suporte, só leitura, a um tenant, registrado na trilha dele |
| `GET /audit` · `GET /audit.csv` (`user`, `from`, `to`, `q`, `limit`) | administrador | Auditoria do escopo: a de um tenant; a do operador mais o que usuários do operador fizeram a tenants; a de um tenant durante o acesso de suporte. Os eventos levam `tenant`, `tenantName`, `byOperator`; o CSV acrescenta `organisation` e `by_operator` |
| `POST /digital-link` `{key, value, qualifiers, attributes:[{ai, value}]}` | leitor | Digital Link com atributos de dados conferidos pelo engine; nada é gravado |
| `GET /qrcode?key=&value=&qualifiers=&format=png\|svg&hri=full\|key\|none&version=auto\|1-40&ecl=l\|m\|q\|h&attr=AI:valor` | leitor | Etiqueta; cabeçalhos `X-QR-Version`, `X-QR-Level`, `X-QR-Modules`; 422 `qr.tooSmall` / `qr.tooLong` |
| `GET /requests?from=&to=&code=&outcome=&device=&automated=&before=&limit=` | qualquer | Requisições ao Resolver no escopo da requisição ([ADR 0006](adr/0006-registro-de-requisicoes.md)), as mais novas primeiro, no máximo `limit` (1–500, 200): `events` (`at`, `method`, `form`, `epc`, `key`, `value`, `anchor`, `qualifiers`, `attributes`, `linkType`, `status`, `outcome`, `level`, `target`, `ms`, `language`, `device`, `referrer`, `country`, `path`, e `organisation` para a instalação inteira), `next`, `days`, `whole`; 422 `requests.badDate` / `requests.badFilter`, 503 `requests.unavailable` |
| `GET /requests.csv` (mesmos filtros) | qualquer | Até 50.000 delas em CSV (UTF-8 com BOM, `;`, células protegidas); diário `requests-export` |
| `GET /requests/daily?days=30` | qualquer | `days`: `[{day, total, automated, outcome}]`, do mais antigo ao mais novo, no escopo (dias passados de `request_daily`, hoje dos eventos); `timeZone` |
| `GET /requests/api?from=&to=&key=&before=&limit=` | admin | As chamadas da API das organizações do escopo (as de todas as organizações para um administrador do servidor): `calls` (`at`, `key`, `keyName`, `organisation`, `method`, `operation`, `status`, `ms`), `next`, `whole` |
| `GET /portal/healthz` | — | `{"portal": "ok", "resolver": "ok"\|"unavailable", "worker": "ok"\|"unavailable", "mail": "on"\|"off"}` |
| `GET /keys` · `POST /keys` `{name, scopes, days, prefixes}` · `DELETE /keys/{id}` | administrador | Chaves da API das organizações no escopo da própria conta (a organização de um administrador de organização; o operador para um administrador do servidor, também em acesso de suporte): a lista com `scopes`, `maxDays`, `defaultDays`, `ratePerMinute`; a criação responde `key` (mostrada uma vez) e `item`; o DELETE revoga |

A **API das organizações** (`/portal/api/v1`, uma chave de API em vez da sessão) está descrita no
`portal/openapi.json` e no README (*API das organizações*): `GET /`, `GET /records`, `GET`/`PUT`/`DELETE
/records/{key}/{value}`, `GET /labels/{key}/{value}`, `GET /openapi.json`.

## 8. Dados do portal

O banco do portal (`PORTAL_DB_NAME`, padrão `resolver_portal`), incluído no dump diário do MongoDB.
Decisões e seus motivos: [ADR 0001](adr/0001-estado-do-portal-no-mongodb.md).

| Coleção | `_id` e conteúdo | Índices |
|---|---|---|
| `users` | nome de usuário; `hash` (vazio enquanto convidado, ou depois de uma redefinição por link), `role`, `prefixes`, `tenant` (ausente nos usuários do operador), `email` (opcional), `disabled`, `mustChange`, `created`, `lastLogin`, `invited`, `language`, `languageChosen`, `notify` (os quatro últimos ausentes quando vazios) | — |
| `tenants` | `t-` + 12 dígitos hexadecimais; `name`, `prefixes`, `disabled`, `created`, `createdBy` ([ADR 0002](adr/0002-organizacoes.md)) | — |
| `record_meta` | chave do cadastro (GTIN pelos 14 dígitos, as outras chaves por `AI/valor`, mais o caminho dos qualificadores); `createdAt`, `createdBy`, `updatedAt`, `updatedBy`, `tenant` (ausente para o operador) | — |
| `journal` | ObjectId (`jsonl-<linha>` nos eventos migrados); `at` (data), `user`, `action`, `category`, `tenant` (ausente para o operador), `byOperator`, `anchor`, `qpath`, `doc`, `detail`, `expiresAt`. Ações de cadastro `create`, `update`, `delete` (com o conteúdo do cadastro), `import`; outras: `login`, `login-failed`, `login-refused`, `logout`, `password-change`, `export`, `user-create`, `user-update`, `user-reset`, `user-remove`, `tenant-create`, `tenant-update`, `tenant-remove`, `support-open` (o motivo em `detail`), `support-close`, `password-recovery`, `password-reset`, `invite-accepted`, `preferences`, `mail-failed` (nunca um endereço de e-mail), `api-key-create`, `api-key-revoke`; as mudanças feitas pela API das organizações levam o usuário `api:<id da chave>` | data; cadastro + data; usuário + data; tenant + data; categoria; TTL em `expiresAt` |
| `login_failures` | `key` (`user:<nome>` ou `addr:<endereço>`; pedidos de recuperação `forgot-user:<entrada>` e `forgot-addr:<endereço>`; links inválidos `link-addr:<endereço>`), `at` | chave + data; TTL de 15 minutos em `at` |
| `linkcheck_cache` | endereço; `result`, `expiresAt` | TTL em `expiresAt` |
| `jobs` | token; `type` (`import`, `linkcheck`, `mail`), `user`, `state`, `created`, `queuedAt`, `startedAt`, `finishedAt`, `heartbeat`, `worker`, `attempts`, `done`, `total`, `expiresAt`, `error`, `notBefore`; importações `plan`, `keyRecords`, `results`; verificações de links `scope`, `urls` (`[{url, records}]`), `problems`, `records` (`[{record, problems}]`); mensagens `to`, `subject`, `text` e `html` (retirados depois de enviada ou falhada), `template`, `tries`, `lastError`, `sent` ou `skipped` | estado + criação; TTL em `expiresAt` |
| `api_keys` | 12 dígitos hexadecimais (o id da chave); `hash` (SHA-256 do segredo), `name`, `tenant` (ausente para o operador), `scopes`, `prefixes`, `created`, `createdBy`, `expiresAt`, `lastUsed`, `revoked`, `revokedBy`, `expiryNotice` ([ADR 0005](adr/0005-api-das-organizacoes.md)) | tenant + criação; validade |
| `api_rate` | `<id da chave>:<minuto>`; `n`, `at` | TTL de 2 minutos em `at` |
| `tokens` | SHA-256 do token de um link de uso único; `purpose` (`invite`, `reset`), `user`, `created`, `expiresAt` ([ADR 0004](adr/0004-e-mail.md)) | usuário + propósito; TTL em `expiresAt` |
| `workers` | nome do worker (`host:pid:modo`); `seen`, `mode`, `job` | TTL de 10 minutos em `seen` |
| `request_daily` | `<dia>\|<AI>\|<valor>` (o dia de uma chave) ou `<dia>\|*` (o dia da instalação); `day`, `ai`, `v`, `cp`, `total`, `automated`, `outcome`, `device`, `form` (contagens por nome), `language`, `linkType` (`[[nome, contagem]]`, no máximo 20), `ms` (soma), `msMax`, no dia da instalação também `keys`, `p50`, `p95`, `p99`; `run`, `expiresAt` ([ADR 0006](adr/0006-registro-de-requisicoes.md)) | dia; parte da empresa + dia; TTL em `expiresAt` |
| `api_requests` | ObjectId; `t`, `key` (ausente sem uma chave válida), `tenant` (ausente para o operador), `m`, `op` (o modelo da rota), `s`, `ms`, `expiresAt` | data; tenant + data; TTL em `expiresAt` |
| `settings` | `lastFullCheck` (a do operador) e `lastFullCheck:<tenant>`, `journalRetention`, `migration`, `requestStats.finalUntil` (o último dia terminado contado) e os documentos `lock:<nome>` | — |

O registro do próprio Resolver é outro banco, **`resolver_log`**, que o usuário do portal só pode ler: a sua coleção
`requests` guarda um evento por requisição de resolução (campos no [ADR 0006](adr/0006-registro-de-requisicoes.md),
seção 3.1; índices em horário, parte da empresa + horário, chave + horário, TTL em `expiresAt`). O backup diário o
guarda.

Retenção do diário: um evento é guardado por `PORTAL_JOURNAL_SESSION_DAYS` (180), `PORTAL_JOURNAL_RECORD_DAYS`
(0) ou `PORTAL_JOURNAL_ADMIN_DAYS` (0) dias a partir do fim do dia em que aconteceu; 0 guarda para sempre.

O volume `resolver-portal-config` (`/app/config`, no backup diário) guarda o `secret.key`, a chave de sessão
usada quando `PORTAL_SECRET_KEY` não está definida (comum a todos os processos e réplicas do portal no mesmo
host Docker, que montam o mesmo volume), e os arquivos das versões anteriores renomeados `*.migrated`.

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
- `request_log.py` (novo, [ADR 0006](adr/0006-registro-de-requisicoes.md)): `note()` (chamada pelas rotas; marca a
  requisição como uma a registrar), `start()` e `record()` (os ganchos `before_request` / `after_request` da
  aplicação, postos em `create_app()`), `event()` (o documento guardado: `qualifiers()` guarda só o AI de 21 e 235,
  `attribute_ais()` só os AIs da query string, `masked_level()`, `device_class()` — automatizado primeiro, depois as
  pilhas HTTP de apps, tablet, celular, computador —, `language()`, `host_of()`, `company_part()`), `outcome()`, e
  `Writer`: uma fila limitada por processo (iniciada no primeiro evento e de novo depois de um fork), uma thread daemon
  que grava lotes de até 500 com uma nova tentativa, eventos perdidos contados (`lost_total`) e avisados no máximo uma
  vez por minuto, `flush()` (testes, e na saída). `create_app()` dá ao gravador `mongo.cx["resolver_log"]["requests"]`,
  a menos que um teste tenha posto outra coleção. `web_logic.read_document()` e `_validate_and_fetch_document()`
  acrescentam `_level` (o nível que respondeu um 307 ou 300) e `_outcome` (`unknown` ou `noLink` num 404) para o
  registro; `web_namespace._process_response()` retira os dois antes de responder.
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
`/swaggerui` ao data-entry-service e `/portal/` ao portal-service (com `/portal` → `/portal/`). Cada
serviço é um bloco upstream (`resolver-web`, `data-entry`, `portal`) cujo servidor é o nome do serviço com
`resolve` e uma `zone` compartilhada: o nginx pergunta ao DNS do Docker (`resolver 127.0.0.11 valid=10s`) o
endereço de cada réplica, de novo a cada 10 segundos, reparte as requisições entre elas em turnos e passa a
outra réplica quando uma recusa a conexão. Ele inicia mesmo quando um serviço ainda não tem endereço (os
caminhos desse serviço respondem 502 até ter). Isso exige o nginx 1.27.3 ou posterior; a imagem é
`nginx:1.30-alpine` (recompilada com `docker compose build --pull` para receber uma nova correção de
segurança do ramo 1.30). O
`home/home.js` lê o operador em `/.well-known/gs1resolver` e compartilha a escolha de idioma com o portal.

## 12. Scripts (`scripts/`)

- `install.sh`: instalador para Ubuntu 22.04/24.04 (verificações, perguntas com os valores anteriores como
  padrão, Docker, nginx do host com Certbot ou certificado existente ou proxy externo, `.env` com segredos
  gerados e as quantidades de réplicas — não perguntadas; 1, o ambiente ou o `.env` existente, de 1 a 20 —,
  inicialização, cron de backup). Pode ser rodado de novo; `--non-interactive` lê todas as
  respostas de variáveis de ambiente. Os modelos do site nginx ficam em `templates/`.
- `resolver-backup.sh` + `resolver-backup.cron`: dump do MongoDB pelo contêiner (todos os bancos, o do
  portal e o registro de requisições incluídos) e arquivo do volume do portal, 14 dias guardados; um dump que falha
  diz `ERROR`, não deixa arquivo parcial e sai com status 1.
- O `install.sh` também grava `PORTAL_TIME_ZONE` (não pergunta: o ambiente, o `.env` existente, senão o fuso do
  servidor pelo `timedatectl`, `/etc/timezone` ou o link `/etc/localtime`, senão UTC).

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
| `resolver/test_request_log.py` | 73 | o registro das requisições ao Resolver ([ADR 0006](adr/0006-registro-de-requisicoes.md)) pelo cliente de teste do Flask no mongomock: cada campo do evento de um redirecionamento, níveis, qualificadores de unidade guardados só como AIs, todos os resultados (código desconhecido, tipo de link ausente, escolha, linkset, requisição inválida, sondagem, link comprimido, `?compress`, binário EPC), HEAD, idiomas, o que nunca é guardado (endereço, User-Agent, Referer completo, valores de atributos de dados e números de série), rotas não registradas, respostas inalteradas, o cabeçalho de país, retenção e desligamento, índices, classes de dispositivo, e que um banco que não responde ou falha nunca segura uma requisição (eventos perdidos e contados, lotes de 500) |
| `portal/test_dictionary.py` | 30 | as regras GS1 do dicionário (ADR 0003): o `gs1_dictionary.json` exatamente o que o dicionário da versão fixada dá, o leitor, chaves, formas, ordem e formatos montados dele com as exceções do portal, um formato maior ou uma chave nova sem código, um linter ou forma desconhecidos parando a montagem, as regras enviadas ao navegador, os AIs (7041) e (8040)–(8043) e seus nomes em português, a comparação da issue semanal |
| `portal/test_engine_messages.py` | 26 | as mensagens do engine (ADR 0003): o `engine_messages.json` exatamente o que as fontes da versão fixada dão, os dois idiomas de toda mensagem com os mesmos parâmetros (a inglesa é o texto do engine), toda mensagem e mensagem de linter reconhecida como ela mesma, as recusas do portal levando a mensagem, a comparação da issue semanal |
| `portal/test_keys.py` | 138 | chaves e qualificadores, comparados com o GS1 Syntax Engine |
| `portal/test_governance.py` | 35 | perfis, prefixos, usuários, histórico, auditoria |
| `portal/test_sheet.py` | 43 | planilhas, limites por formato |
| `portal/test_special_chars.py` | 57 | caracteres especiais |
| `portal/test_data_attributes.py` | 83 | atributos de dados, famílias decimais, opções do QR (precisa de `GS1_SYNTAX_ENGINE_DIR`) |
| `portal/test_linkcheck.py` | 16 | verificador de links, proteção contra SSRF |
| `portal/test_portal_config.py` | 13 | configuração e inicialização, limites da sessão |
| `portal/test_session.py` | 30 | limites da sessão (15 s sem uso no teste): regras do servidor, aviso, renovação pelo uso, outras abas, limite absoluto, os dois idiomas; aviso da comunidade no rodapé (cerca de dois minutos) |
| `portal/test_store.py` | 58 | a camada de dados do portal: configurações de conexão, índices, a trava compartilhada (também entre dois administradores ao mesmo tempo), usuários, metadados dos cadastros, diário e retenção, bloqueio de entrada, migração dos arquivos antigos (também interrompida e retomada) |
| `portal/test_tenants.py` | 82 | tenants ([ADR 0002](adr/0002-organizacoes.md)): uma instalação sem tenants igual a antes; tenants e seus prefixos (nomes, sobreposições, redundância, usuários do operador no caminho); os cadastros e usuários do operador; administradores de tenant e seus usuários; endereços de e-mail; cadastros, histórico, lista, exportação e importações por tenant, e a conferência do worker antes de cada cadastro; prefixos mudando de dono; a trilha de auditoria por tenant e seu CSV; acesso de suporte; tenants desativados e removidos; resultados da verificação de links por escopo; posse por tipo de chave; a linha de comando; as mensagens dos dois idiomas (mesmas chaves, toda chave da página e todo código de mensagem do servidor traduzidos) |
| `portal/test_mail.py` | 138 | e-mail ([ADR 0004](adr/0004-e-mail.md)) contra um relay SMTP do próprio teste (`fake_smtp.py`: STARTTLS ou TLS com um certificado descartável, autenticação, recusas sob demanda): configurações que não combinam, envio com STARTTLS e TLS, cabeçalhos e a alternativa HTML, falhas temporárias e definitivas, credenciais nunca enviadas sem criptografia, o comando de teste; os textos dos dois idiomas; links de uso único (só o hash, uma vez, substituídos, expirados, apagados); `notBefore` e `defer()`; com o e-mail desligado nada muda; convites, recuperação de senha (a mesma resposta e o mesmo tempo para qualquer entrada, limites, quem não recebe nada), redefinições por um administrador, avisos de segurança, preferências, avisos de tarefas terminadas; novas tentativas, falhas, uma mensagem pulada para uma conta desativada no meio do caminho, nenhum endereço no diário; todo código de mensagem traduzido. Toda proteção conferida por mutação |
| `portal/test_api.py` | 92 | a API das organizações e as suas chaves ([ADR 0005](adr/0005-api-das-organizacoes.md)): chaves criadas, listadas e revogadas só no escopo do próprio administrador (também em acesso de suporte), as regras de uma chave (nome, escopos, dias, prefixos, 20 ativas), a chave completa uma vez e só o hash guardado, o criador avisado por e-mail; autenticação (ausente, errada, revogada, expirada, organização desativada), sessões e chaves separadas; cadastros listados em páginas, lidos, gravados (regras GS1, cadastro de outro dono recusado, sem CORS), excluídos; etiquetas; escopos, os prefixos de uma chave, as chaves do operador; o diário (`api:<id>`); o limite de requisições e o último uso; o aviso de validade e a limpeza do worker; a descrição OpenAPI contra as rotas e as respostas; os dois idiomas. Toda proteção conferida por mutação |
| `portal/test_requestlog.py` | 74 | o registro de requisições no portal ([ADR 0006](adr/0006-registro-de-requisicoes.md)): quem vê quais eventos (uma organização, os prefixos de um usuário, o operador, administradores do servidor com a organização de cada evento, um administrador do servidor limitado, acesso de suporte, um prefixo que muda de organização), filtros (resultado, dispositivo, automatizadas, código como GTIN-13, GTIN-14, prefixo, âncora; dias do `PORTAL_TIME_ZONE`), páginas com empates, o CSV (fórmulas protegidas, a coluna da organização, o diário), os agregados diários (por chave e da instalação, percentis, validade, dias terminados, substituição, a trava, o desligamento, um fuso desconhecido), requisições por dia por escopo, as chamadas da API das organizações (nunca o cadastro nem o segredo; quem as vê), a configuração, um registro ilegível, as mensagens dos dois idiomas |
| `portal/test_jobs.py` | 70 | tarefas em segundo plano: estados, validade, retirada atômica, posse das gravações, workers calados devolvidos e falha depois de três tentativas, o anúncio do worker, `stalled`, a verificação de saúde, o laço do worker (erros, sinal de vida, parada e devolução, `JobLost`), o worker embutido e `PORTAL_WORKER`; importações pela API (fila, worker, diário, outro usuário, um worker que morre antes e depois de gravar um cadastro, uma falha); verificações de links pela API (todos os cadastros, uma lista, uma parada que cancela os endereços pendentes) |
| `portal/test_worker_processes.py` | 13 | o `worker.py` como processos reais num MongoDB real (rodado pelo `test_store_mongodb.py`): dois workers dividem a fila sem pegar a mesma tarefa duas vezes; o SIGTERM devolve a tarefa e o outro worker a termina; depois de um SIGKILL, um worker novo continua a tarefa quando o sinal de vida fica velho |
| `portal/test_store_mongodb.py` | 165 | num MongoDB real (`PORTAL_TEST_MONGO_URI`, só no CI): o usuário criado pelo `db_init.py` e suas permissões (lê o registro de requisições, não grava nele); `test_store.py`, `test_jobs.py` e `test_worker_processes.py` de novo como esse usuário (com suas linhas repassadas); o monitor de TTL, também para tarefas e anúncios antigos de workers |
| `portal/test_registration.py` | 26 | §2.5.9 pela API do portal: qualificadores informativos (salvar, abrir, histórico, lista, exportar, importar), cadastros contra a regra 2, o cadastro da chave ao salvar e ao importar |
| `portal/test_mail_e2e.py` | 37 | as telas de e-mail no Chromium com o relay do `fake_smtp.py`: recuperação na página de entrada (a mesma resposta para qualquer entrada), um convite pela tela de usuários, a página que um link abre (nome de usuário, o token fora da barra de endereço, senhas curtas e diferentes recusadas, a largura de um celular), um link usado duas vezes, um link aberto com outra pessoa conectada, uma recuperação encerrando a sessão aberta do usuário, Opções → E-mail mantido, uma redefinição por link, todo texto da página de entrada traduzido, e as mesmas telas com o e-mail desligado |
| `portal/test_requests_e2e.py` | 28 | a tela Acessos no Chromium ([ADR 0006](adr/0006-registro-de-requisicoes.md)): o item de menu para todo usuário (e o menu que fecha), 30 barras a partir dos agregados e dos eventos de hoje, as últimas requisições (coluna da organização para o administrador do servidor, esquema EPC, nível, série como `/21/*`), a página seguinte, filtros (não encontradas, um GTIN-13, automatizadas), a exportação CSV, o acesso de suporte, inglês, um leitor de uma organização (sem coluna da organização, sem a aba da API), as chamadas da API de um administrador sem o segredo da chave, a largura de um celular, o registro desligado |
| `portal/test_api_e2e.py` | 21 | a tela de chaves de API no Chromium: o administrador de uma organização cria uma chave (mostrada uma vez com um exemplo), um sistema a usa por `/portal/api/v1`, o cadastro mostra `api:<id>`, sair da tela retira a chave da página, revogar na tela a para na hora, a auditoria, os dois idiomas, a largura de um celular, as chaves do operador para um administrador do servidor, nenhuma tela para um editor |
| `portal/test_portal_e2e.py` | 211 | o portal no Chromium contra o `mock_data_entry.py`, desktop e celular, com um worker embutido (também parado: as mensagens de fila e de "não está em execução", uma tarefa que falha); organizações, um administrador de tenant e o acesso de suporte nos dois idiomas; também roda sem o engine (166) |
| `home/test_home.py` | 68 | página inicial com um nginx real (1.27.3 ou posterior: `NGINX_BIN` ou o PATH), sem o quadro da sintaxe, aviso da comunidade; rotas do proxy, incluindo que o cabeçalho Host enviado a cada upstream é aceito pelo Werkzeug; réplicas por um servidor DNS simulado que responde os nomes dos serviços com endereços `127.0.0.x`: o nginx inicia quando um serviço não tem endereço e o acha depois, reparte as requisições entre duas réplicas, acompanha uma terceira acrescentada e duas retiradas sem reiniciar, e nenhuma requisição falha enquanto réplicas param |
| `install/test_install.sh` | 87 | instalador com simulações (Compose v2), incluindo um portal cujo worker de tarefas não sobe; quantidades de réplicas gravadas, mantidas, tomadas do ambiente e recusadas quando inválidas; o fuso das contagens de requisições (o do servidor, do ambiente, recusado quando não é um nome); o relay de e-mail (desligado por padrão, gravado com STARTTLS ou TLS, a senha mantida e nunca mostrada, desligado, um relay de teste definido à mão mantido, recusas); nenhuma configuração gravada duas vezes no `.env` |
| `install/test_deploy.py` | 62 | o backup diário com um `docker` substituto (só opções que o `mongodump` tem; um dump que falha: `ERROR`, status 1, nenhum arquivo parcial; um bom: o arquivo, `OK`); `docker compose config` das réplicas e quantidades de processos (padrões, valores do `.env`, um valor recusado, nomes mantidos pelo banco e pelo proxy); a versão do nginx da imagem do proxy e o `resolve` em todos os upstreams; o `CMD` gunicorn de cada imagem iniciado localmente (três processos, uma resposta, a requisição no log, parada limpa com SIGTERM em até 10 s); a chave de sessão reserva do portal com seis processos iniciando juntos e oito threads enquanto gravá-la é lento; o portal iniciado a partir dos arquivos que as linhas `COPY` do seu Dockerfile põem na imagem, entre eles todo módulo e arquivo de dados de `portal/`; uma versão do engine, só no `docker-compose.yml`, passada a toda imagem (ADR 0003) |

**pytest e integração contínua.** O `dev-tests/test_programs.py` roda cada programa acima como um teste
pytest (um subprocesso a partir da raiz do repositório): status 0 sem linha `FAIL` passa; caso contrário, o
relatório mostra as linhas `FAIL` e o fim da saída; um programa que só imprimiu `SKIP` é pulado. Marcadores
os agrupam: `resolver` (Resolver, EPC binário, API de cadastro, suíte da GS1), `portal` (os programas do
portal sem navegador), `e2e` (`test_portal_e2e.py` com e sem o engine, `test_session.py`, `test_mail_e2e.py`, `test_api_e2e.py`, `test_requests_e2e.py`), `home`, `install`
(o instalador por `sudo` sem senha quando não se é root, e o `test_deploy.py`), `database` (`test_store_mongodb.py`). O `dev-tests/conftest.py` impede que o pytest importe os
programas, registra os marcadores e imprime ao final a contagem de verificações de cada programa (e também
no resumo da execução do GitHub Actions). Com `DEV_TESTS_STRICT=1`, um programa falha quando uma variável de
ambiente de que precisa não está definida ou aponta para um caminho inexistente (`needs_env`), quando uma
variável que não é caminho não está definida (`needs_var`), quando um comando de que precisa não está no
PATH, ou quando imprime `SKIP`. Para acrescentar um programa: escreva-o com linhas
`PASS`/`FAIL` e status de saída, acrescente uma linha `Program(...)` a `PROGRAMS` (grupo, caminho, as
variáveis e comandos de que precisa) e uma linha à tabela acima.

Um segundo workflow, `.github/workflows/engine-update.yml` (semanal, às segundas 09:37 UTC, e sob demanda), abre
uma issue quando o GS1 Barcode Syntax Engine tem versão mais nova que `x-gs1-syntax-engine`: usa a versão nova na
sua própria cópia, regenera o dicionário, compara (`tools/dictionary_diff.py`), roda o grupo `portal` e escreve os
dois na issue; uma issue por versão; nunca faz push (`contents: read`, `issues: write`). Um fork no GitHub vem com Issues desligado, e o job falha com
"repository has disabled issues": ligue em Settings → Features → Issues.

O `.github/workflows/dev-tests.yml` roda um job por grupo, em paralelo, a cada push e pull request para
`gs1br/develop` (não para mudanças só em `Documentation/` ou em arquivos Markdown), em modo estrito. O job
`database` sobe um contêiner de serviço `mongo:7` e roda nele os grupos `portal` e `database`. O `database` é
informativo (`continue-on-error`) até provar estabilidade; `e2e` e `install` começaram assim e são
obrigatórios desde a etapa 4 do item 2.3. A action composta
`.github/actions/dev-tests-setup` instala só o que o job pede e exporta as variáveis: Python 3.12 e Node.js 24
como nas imagens; `gs1encoder`, `epc-tds` e `ajv-dist` em versões fixadas (cache pela versão, a do `gs1encoder`
lida do `docker-compose.yml`); o engine do portal compilado pelo `portal/tools/build-syntax-engine.sh` nessa versão
(cache pela versão e pelo script); o
Chromium (cache pela versão do Playwright); a suíte da GS1 no commit `32597c1`; o nginx do Ubuntu para o instalador e o
nginx 1.30.5 do nginx.org para o teste do proxy; Docker Compose v2.29.7. Mude uma versão ali, num lugar só; a versão do engine não fica ali, e sim no `docker-compose.yml`.

O `docs/screenshots.py` regenera as imagens do README e do guia do portal em inglês e em português a partir
do portal real, com dados de exemplo (logotipo GS1 oculto). Versione só as imagens que realmente mudaram. As
imagens de e-mail (`mail_images()`) são feitas com o e-mail ligado só para elas, contra o relay do `fake_smtp.py`.

## 14. Como estender

**Um texto da interface.** Acrescente a chave aos dois idiomas do `i18n.js` (`pt-BR` e `en-GB`) e use-a com
`data-i18n` ou `I18N.set()`. Mensagens do servidor são códigos: lance `ValidationError("meu.codigo",
param=…)` e acrescente `meu.codigo` aos dois idiomas.

**Um idioma.** Copie um bloco de idioma do `i18n.js`, traduza, acrescente-o a `SUPPORTED` e
`LOCALE_MATCHERS`; faça o mesmo em `web_pages.py` (`TEXT`, `LINK_TYPE_LABELS`) e em `home/home.js`.

**Um tipo de link.** Acrescente uma linha a `LINK_TYPES` no `gs1.py` e o nome e a descrição em `linkTypes`
nos dois idiomas; considere o `activeLinkTypes` em `web_server/src/public/gs1resolver.json`.

**Uma chave primária ou um qualificador** (de um dicionário posterior). Vêm com o dicionário: atualize o engine
(abaixo) e regenere o `gs1_dictionary.json`. Só é preciso código quando o formato novo tem uma forma ou um linter
que o `key_validator()` / `qualifier_pattern()` não conhecem (a montagem para e diz qual; a issue semanal também):
acrescente a conferência no `gs1.py` e o tipo do `.spec` no `readKey()` do `app.js`. Acrescente os textos
`key.<AI>.*` / `qual.<AI>.*` e um nome em `PORTAL_EXCEPTIONS["key_names"]`; amplie o `dev-tests/portal/test_keys.py`.

**Um endpoint da API.** Acrescente a rota na seção certa do `app.py` com `@require_login` e, para
gravações, `@role_required("editor")`; chame `check_access()` para cada identificador; responda com
códigos de `message()`; registre com `audit.info()` e `log_event()`; acrescente testes; liste-o neste guia,
na versão em inglês e no README.

**Um esquema EPC ou uma nova versão do TDT.** Copie os novos arquivos de definição e tabelas para
`web_server/src/tdt/` (mantendo o `+` nos nomes) e atualize o `manifest.json`; esquemas anteriores ao TDS
2.0 não precisam de código. Um esquema `+` só precisa de código para um formato da Tabela F ou método do
TDS 14.5 que `_component()` não conheça; um esquema `++`, só de uma entrada em `PLUS_PLUS` enquanto o TDT
não tiver artefato para ele. Acrescente o vetor do anexo E do TDS ao `test_epc_binary.py`.

**O syntax engine.** A tarefa semanal *GS1 Barcode Syntax Engine update check*
(`.github/workflows/engine-update.yml`) abre uma issue quando há versão mais nova, com o que muda no dicionário, as
mensagens do engine que precisam de tradução e o resultado dos testes do portal. Para atualizar, mude a versão num
lugar só, `x-gs1-syntax-engine` no `docker-compose.yml`; compile o engine (`portal/tools/build-syntax-engine.sh
<pasta>`), regenere o dicionário (`python portal/tools/gen_dictionary.py <pasta>`) e as mensagens (`python
portal/tools/gen_engine_messages.py <pasta>`), acrescente as mensagens novas ou alteradas aos dois idiomas do
`i18n.js` (`engine.*`; a inglesa é o texto do engine, com os parâmetros como `{p1}`, `{p2}`…), rode todos os testes
e faça o commit; no servidor, `docker compose up -d --build`. Toda imagem, o script de build, o CI e os testes seguem
a versão única (o `test_deploy.py` falha quando algo guarda uma versão própria; o `test_dictionary.py` e o
`test_engine_messages.py`, quando um arquivo foi feito de outra versão ou falta a tradução de uma mensagem).

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
