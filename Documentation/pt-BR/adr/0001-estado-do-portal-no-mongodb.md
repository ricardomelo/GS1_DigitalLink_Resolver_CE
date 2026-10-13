# ADR 0001 — O estado do portal no MongoDB, tarefas em segundo plano num worker, mais de uma réplica

| | |
|---|---|
| Situação | **Aceito** (13 de outubro de 2026). Implementação em quatro etapas: 1 (este registro), 2 (os dados no MongoDB) e 3 (o worker de tarefas) concluídas |
| Item do backlog | 2.3 — arquitetura para escala e os dados do portal no MongoDB |
| Decidido por | o responsável pelo branch, sobre as opções da seção 4 |
| Inglês | [ADR 0001 in English](../../adr/0001-portal-state-in-mongodb.md) (versão de referência) |

## 1. Contexto

O portal foi escrito para rodar como **um único worker do gunicorn, com threads**. Foi uma simplificação
deliberada (decisão 10 do [histórico](../historico.md)), e ela aparece no lugar onde o portal guarda seu
estado.

**Arquivos no volume `resolver-portal-config`** (`/app/config`), cada um gravado de forma atômica sob uma
trava de arquivo:

| Arquivo | Módulo | Guarda |
|---|---|---|
| `users.json` | `portal/users.py` | contas: hash da senha, perfil, prefixos de empresa GS1, desativada, troca de senha obrigatória, criação, última entrada |
| `records-meta.json` | `portal/meta.py` | quem criou e quem alterou por último cada cadastro, e quando |
| `journal.jsonl` | `portal/journal.py` | histórico e auditoria: entradas, administração de usuários, cada alteração de cadastro com o conteúdo completo |
| `secret.key` | `portal/app.py` | a chave que assina os cookies de sessão, quando `PORTAL_SECRET_KEY` não está definida |

**Memória do único processo** (`portal/app.py`, `portal/linkcheck.py`):

| Estado | Duração | Serve para |
|---|---|---|
| `LoginThrottle` | 15 minutos | cinco entradas recusadas bloqueiam um nome de usuário ou um endereço |
| `IMPORTS` | 30 minutos | a prévia de uma importação de planilha (o plano) e, depois de aplicada, o progresso e os resultados |
| `LINK_JOBS` | 30 minutos | progresso e resultados de uma verificação de links sobre muitos cadastros |
| `LAST_FULL_CHECK` | até reiniciar | o resultado da última "verificar todos os cadastros", mostrado na lista |
| `linkcheck._cache` | 10 minutos | o resultado da verificação de um endereço, para não consultar o mesmo site duas vezes |

Importações e verificações de links rodam em **threads do processo web**. O diário é lido percorrendo o
arquivo inteiro. O portal propositalmente **não recebe credenciais do MongoDB**: o `docker-compose.yml`
deixa o `MONGO_URI` dele vazio, e ele só fala com a API de cadastro.

Consequências hoje:
- uma segunda réplica do portal teria seu próprio bloqueio de entrada, não veria uma importação com prévia
  feita na outra réplica e responderia "expirada" a um navegador que acompanha uma tarefa que ela não tem;
- reiniciar perde importações e verificações de links em andamento;
- o diário cresce sem limite, e cada consulta de histórico ou auditoria lê o arquivo todo;
- os itens 2.4 (organizações), 4.1 (registro das requisições ao Resolver) e 7.4 (teste de carga) precisam de
  estado compartilhado por vários processos.

Os serviços oficiais também não foram escritos para isso: `web-service` e `data-entry-service` usam o
servidor embutido do Flask (`python -m main` → `app.run()`), e todos os serviços do `docker-compose.yml` têm
um `container_name` fixo, que o Compose não aceita replicar.

## 2. Decisão

1. **Um banco de dados próprio do portal**, `resolver_portal`, no MongoDB existente, acessado por **um
   usuário próprio** com `readWrite` apenas nesse banco. O banco oficial `resolver_ce` e suas coleções não
   são tocados; o portal continua gravando cadastros pela API de cadastro, nunca diretamente. O portal nunca
   recebe as credenciais root.
2. **Tarefas em segundo plano numa coleção, executadas por um contêiner worker.** Importações e
   verificações de links viram documentos em `jobs`; um serviço `portal-worker` (a imagem do portal com
   outro comando) as assume uma por vez. Nenhuma infraestrutura nova. O processo web só enfileira tarefas e
   lê o progresso.
3. **Estado de curta duração em coleções que o próprio MongoDB limpa** (índices TTL): entradas recusadas,
   prévias de importação e resultados de tarefas, o cache do verificador de links.
4. **A chave de sessão no `.env`** (`PORTAL_SECRET_KEY`), gerada pelo instalador como os outros segredos e
   compartilhada por todas as réplicas. O arquivo `secret.key` continua como reserva para uma instalação com
   uma réplica do portal e sem chave no `.env`.
5. **Retenção do diário por idade, por categoria**, configurada no `.env` e aplicada pelo MongoDB (TTL):
   eventos de entrada e saída, 180 dias por padrão; versões de cadastros e administração, guardadas para
   sempre por padrão.
6. **Migração automática no início**: quando as coleções do portal estão vazias e os arquivos antigos
   existem, o portal os importa uma vez e os renomeia para `*.migrated`; eles ficam no volume como cópia.
7. **Testes**: os programas de teste atuais usam `mongomock` e continuam rodando sem Docker nem MongoDB; um
   job novo no CI roda os testes de armazenamento contra um contêiner `mongo:7` real.
8. **Quatro entregas**, cada uma com seu bundle e sua verificação no staging (seção 7).

## 3. Projeto

### 3.1 Banco, usuário e conexão

- Banco `resolver_portal` (`PORTAL_DB_NAME`), usuário `resolver_portal` (`PORTAL_DB_USERNAME`), senha
  `PORTAL_DB_PASSWORD`. O `.env.example` traz valores de desenvolvimento, como para os outros segredos; o
  instalador grava valores aleatórios no `.env`.
- O usuário é criado por **um serviço do Compose que roda uma vez e termina, `portal-db-init`**: a imagem do
  portal rodando o `portal/db_init.py`. Ele recebe o `MONGO_URI` root (como os serviços oficiais já recebem),
  cria o usuário, ou atualiza senha e permissões quando ele já existe, e sai. Python na imagem do portal, em
  vez de um script `mongosh` na imagem do banco, permite que os testes de desenvolvimento rodem o mesmo
  script contra um MongoDB real no CI. `portal-service` e `portal-worker` dependem dele com `condition: service_completed_successfully`.
  Assim, toda forma de subir o sistema (instalador, `docker compose up -d` manual, uma restauração) termina
  com o usuário e a senha certos, e mudar `PORTAL_DB_PASSWORD` no `.env` vale no próximo `up -d`. (Os
  scripts de `/docker-entrypoint-initdb.d` do próprio MongoDB só rodam num volume vazio, então não servem
  para instalações existentes.)
- O portal monta a conexão com essas variáveis e `PORTAL_DB_HOST` (padrão `database-service:27017`), com
  `authSource=resolver_portal`. O `MONGO_URI` continua vazio para o portal.
- `portal/store.py` guarda o cliente (um por processo, com o pool de conexões do `pymongo`), cria os índices
  no início e entrega aos outros módulos as suas coleções. As funções públicas de `users.py`, `meta.py` e
  `journal.py` mantêm nomes e resultados, então o `app.py` muda pouco.

### 3.2 Coleções

| Coleção | `_id` | Campos | Índices |
|---|---|---|---|
| `users` | nome de usuário | `hash`, `role`, `prefixes`, `disabled`, `mustChange`, `created`, `lastLogin` | — |
| `record_meta` | chave do cadastro (`meta.key()`) | `createdAt`, `createdBy`, `updatedAt`, `updatedBy` | — |
| `journal` | ObjectId (`jsonl-<linha>` quando migrado) | `at` (data), `user`, `action`, `category`, `anchor`, `qpath`, `doc`, `detail`, `expiresAt` | `{at: -1}`; `{anchor, qpath, at: -1}`; `{user, at: -1}`; `{category}`; TTL em `expiresAt` |
| `login_failures` | ObjectId | `key` (nome de usuário ou endereço), `at` (data) | `{key, at}`; TTL em `at`, 15 minutos |
| `jobs` | token | `type` (`import`, `linkcheck`), `user`, `state`, `created`, `queuedAt`, `startedAt`, `finishedAt`, `heartbeat`, `worker`, `attempts`, `done`, `total`, `error`, `expiresAt`; importações `plan`, `keyRecords`, `results`; verificações de links `scope`, `urls`, `problems`, `records` | `{state, created}`; TTL em `expiresAt` |
| `workers` (etapa 3) | nome do worker (`host:pid:modo`) | `seen`, `mode`, `job` | TTL em `seen`, 10 minutos |
| `linkcheck_cache` | endereço | `result`, `expiresAt` | TTL em `expiresAt` |
| `settings` | nome | `value` (`lastFullCheck`, `journalRetention`, `migration`); documentos de trava `lock:<nome>` | — |

Observações:
- **Último administrador ativo**: `users.update()` e `users.remove()` mantêm a regra. Um MongoDB sem replica
  set não tem transações entre documentos, então toda alteração de usuários roda sob uma trava comum a
  todos os processos (um documento `lock:users` em `settings`, criado com `_id` único; uma trava deixada por
  um processo que morreu é quebrada depois de um minuto): dois administradores agindo no mesmo instante não
  conseguem remover ambos o último.
- **Datas**: gravadas como datas BSON (o TTL precisa delas); a API continua devolvendo textos ISO 8601 com
  `Z`, então o navegador não vê mudança.
- **Tamanho**: um documento tem no máximo 16 MB. Uma importação é limitada a 5.000 linhas e 700 KB
  (`sheet.FORMATS`), então o plano e os resultados cabem num documento de tarefa.
- **`create_user.py`** mantém a linha de comando e grava pelo mesmo armazenamento.

### 3.3 Tarefas e o worker

- **Estados**: `prepared` (prévia de importação, aguardando *Aplicar*) → `queued` → `running` → `finished`
  ou `failed`. Uma verificação de links começa em `queued`.
- **Reserva**: o worker pega a tarefa `queued` mais antiga com `find_one_and_update`, marca `running`, o
  próprio nome e um `heartbeat`, e renova o heartbeat enquanto trabalha. Dois workers nunca pegam a mesma
  tarefa.
- **Worker que morre**: uma tarefa `running` cujo heartbeat tem mais de dois minutos volta a `queued` e
  continua a partir de `done` (cada cadastro de uma importação é uma gravação separada e repetível na API de
  cadastro).
- **Consulta**: parado, o worker procura trabalho a cada segundo. Change streams evitariam isso, mas exigem
  um replica set, que o MongoDB único de uma instalação padrão não tem.
- **Expiração**: `expiresAt` = 30 minutos depois da prévia ou do fim da tarefa, como hoje.
- **Escala**: uma tarefa por vez em cada worker; mais workers, mais tarefas em paralelo. O verificador de
  links mantém suas oito threads dentro de uma tarefa.

**Como ficou na etapa 3** (as escolhas do responsável nos pontos em aberto, todas as recomendadas, e detalhes
que a implementação acrescentou):
- **Onde as tarefas rodam**: `PORTAL_WORKER=external` (padrão) — o serviço `portal-worker`, a imagem do
  portal rodando `python worker.py`, sempre presente no `docker-compose.yml`; `embedded` — uma thread de
  worker dentro do processo do portal, para os testes de desenvolvimento e uma instalação sem esse serviço. Um
  worker por padrão; suas réplicas se decidem junto com as outras na etapa 4. Sem botão de cancelar por
  enquanto (um item posterior do backlog).
- **Uma importação interrompida continua** do primeiro cadastro não gravado. Depois de três retiradas da
  mesma tarefa (`attempts`), a tarefa de um worker calado falha com `job.interrupted` em vez de voltar à fila,
  para que uma tarefa que derruba seu worker não fique em ciclo para sempre; o que foi gravado fica. **Uma
  verificação de links recomeça** do primeiro endereço: seus resultados não são guardados um a um, e o cache
  do verificador (10 minutos) responde os endereços já conferidos.
- **Posse das gravações**: toda gravação de uma tarefa em execução só vale se a tarefa ainda for daquele
  worker; um worker que só estava lento, e cuja tarefa foi dada a outro, percebe (`JobLost`) e a larga.
- **Parada limpa**: no SIGTERM (`docker compose stop`, uma atualização) o worker termina o cadastro em mãos e
  devolve a tarefa à fila na hora, sem esperar os dois minutos; o serviço tem 30 segundos de tolerância.
- **Há um worker rodando?** Os workers se anunciam numa coleção `workers` a cada 10 segundos. Uma tarefa na
  fila há 15 segundos sem nenhum worker visto nos últimos 30 é informada como `stalled`, e o navegador avisa
  que o processador de tarefas não está em execução em vez de esperar calado; o `GET /portal/healthz` ganha
  `worker` (`ok` ou `unavailable`), e o instalador avisa quando o worker não se apresenta.
- **Validade das tarefas não terminadas**: uma tarefa na fila ou em execução expira depois de um dia, uma
  rede de segurança para tarefas que ninguém vai terminar.

### 3.4 Bloqueio de entrada e caches

- Cada entrada recusada insere um documento por chave (nome de usuário, endereço). A entrada é recusada
  enquanto uma das chaves tiver cinco falhas em 15 minutos; uma entrada aceita apaga as falhas das duas
  chaves. A regra e a resposta 429 não mudam; o estado agora é comum a todas as réplicas.
- O verificador de links lê e grava `linkcheck_cache` (10 minutos). `LAST_FULL_CHECK` vai para `settings`.

### 3.5 Retenção do diário

| Variável | Padrão | Ações |
|---|---|---|
| `PORTAL_JOURNAL_SESSION_DAYS` | 180 | `login`, `login-failed`, `logout` |
| `PORTAL_JOURNAL_RECORD_DAYS` | 0 (para sempre) | `create`, `update`, `delete`, `import` |
| `PORTAL_JOURNAL_ADMIN_DAYS` | 0 (para sempre) | `password-change`, `user-create`, `user-update`, `user-reset`, `user-remove`, `export` |

Um evento é guardado pelos dias da sua categoria contados a partir do fim do dia (UTC) em que aconteceu:
`expiresAt` = essa meia-noite + os dias, ou nenhum `expiresAt` quando o valor é 0; o monitor de TTL do
MongoDB o apaga depois desse prazo (ele roda mais ou menos uma vez por minuto). Dias inteiros deixam a regra
simples de enunciar e permitem que o portal, quando um valor muda, recalcule no início o `expiresAt` da
categoria com uma atualização por dia do diário (sob uma trava, para que as réplicas o façam uma vez só). O backup diário guarda
o que expira pelo seu próprio prazo (`RETENTION_DAYS`, 14 dias por padrão). O histórico de um cadastro fica
no diário, então limitar `PORTAL_JOURNAL_RECORD_DAYS` também limita até quando um cadastro pode ser
restaurado; os documentos de configuração dizem isso.

### 3.6 Migração das instalações existentes

No início, antes de atender requisições, o portal (um processo por vez, sob um documento de trava em
`settings`):
1. para cada um de `users.json`, `records-meta.json`, `journal.jsonl` que exista **e** cuja coleção esteja
   vazia, importa o conteúdo (usuários como estão, inclusive os de antes dos perfis; eventos do diário com
   suas datas e categorias);
2. renomeia cada arquivo importado para `*.migrated`, mantendo-o no volume;
3. registra as contagens em `settings.migration` e no log.

A importação é idempotente: um arquivo só é lido para uma coleção vazia, e um arquivo já renomeado não é
lido de novo. O primeiro usuário de `PORTAL_ADMIN_*` continua sendo criado quando a coleção de usuários
está vazia depois da migração. Sessões assinadas com um `secret.key` antigo continuam válidas enquanto essa
for a chave em uso; o instalador não copia nada do volume, então, quando ele grava `PORTAL_SECRET_KEY` pela
primeira vez, todos entram de novo uma vez.

### 3.7 Backup e restauração

- O `scripts/resolver-backup.sh` já faz o dump de todos os bancos como root, então `resolver_portal` entra
  sem mudança. O arquivo do volume continua enquanto o volume existir (os `*.migrated` e a chave reserva).
- Uma restauração com `mongorestore` traz `resolver_portal` de volta; o `portal-db-init` recria ou atualiza
  o usuário no início seguinte, então a restauração não precisa de passo extra. A seção de restauração da
  [documentação das extensões](../../extensions/README.md) é atualizada na etapa 2.

### 3.8 Réplicas (etapa 4)

- O portal, o worker, `web-service` e `data-entry-service` não guardam estado próprio depois da etapa 3.
- O `deploy.replicas` do Compose (ou `docker compose up --scale`) exige tirar as linhas fixas de
  `container_name` desses serviços: uma **mudança deliberada no código oficial**, registrada no changelog.
- O nginx resolve o nome de um serviço para o endereço de cada réplica quando inicia e distribui as
  requisições entre elas; o `depends_on … restart: true` já reinicia o proxy quando um serviço atrás dele é
  recriado.
- **A decidir com o responsável na etapa 4**: se `web-service` e `data-entry-service` passam do servidor
  embutido do Flask para o gunicorn (também mudança deliberada no código oficial), e o número padrão de
  réplicas de cada serviço.

## 4. Opções consideradas

| Ponto | Escolhida | Não escolhidas |
|---|---|---|
| Banco e acesso | banco próprio e usuário com o mínimo de permissões | coleções `portal_*` em `resolver_ce` (mistura com as coleções oficiais); o `MONGO_URI` root (acesso total para o portal) |
| Tarefas em segundo plano | coleção de tarefas + contêiner worker | Redis com RQ ou Celery (mais um serviço para instalar, proteger e incluir no backup); threads no portal com o estado no MongoDB (a tarefa morre com a réplica) |
| Bloqueio e caches | MongoDB com índices TTL | só o bloqueio no MongoDB (as prévias exigiriam sessão presa a uma réplica); tudo em memória (cada réplica com seu bloqueio) |
| Chave de sessão | `PORTAL_SECRET_KEY` no `.env` | guardada no MongoDB (a chave ficaria no dump do banco); arquivo num volume compartilhado (um volume mantido só para isso) |
| Retenção do diário | por idade, por categoria, TTL | por tamanho (poderia apagar o histórico de cadastros que nunca mudam); nenhuma |
| Migração | automática no início | comando rodado pelo operador ou pelo instalador (mais um passo a lembrar) |
| Testes | `mongomock` + um job com `mongo:7` real no CI | só `mongomock` (TTL e permissões nunca testados antes do staging); só MongoDB real (o ambiente de desenvolvimento não consegue rodá-lo) |
| Entrega | quatro etapas | duas etapas maiores |

## 5. Consequências

Melhor:
- qualquer serviço pode rodar com várias réplicas; reiniciar não perde mais importações nem verificações;
- um só bloqueio de entrada para toda a instalação;
- consultas de histórico e auditoria usam índices em vez de ler um arquivo;
- o diário para de crescer sem limite;
- organizações (2.4), o registro de requisições (4.1) e o teste de carga (7.4) têm onde guardar estado
  compartilhado.

Pior, e como fica contido:
- o portal passa a ter credenciais do banco: um usuário limitado a `resolver_portal`, nunca root;
- mais peças (`portal-db-init`, `portal-worker`): ambas usam imagens que a instalação já constrói;
- o worker consulta o MongoDB uma vez por segundo quando parado: uma consulta indexada, desprezível;
- `mongomock` não é o MongoDB: o job do CI com `mongo:7` real cobre índices TTL, as permissões do usuário e
  a migração e processos de worker dividindo a fila; ele é informativo até provar estabilidade. O ambiente de
  desenvolvimento não roda MongoDB, então o primeiro resultado real desse job vem do GitHub Actions.

## 6. Configuração acrescentada

| Variável | Padrão (`.env.example`) | Significado |
|---|---|---|
| `PORTAL_DB_NAME` | `resolver_portal` | o banco do portal |
| `PORTAL_DB_USERNAME` | `resolver_portal` | seu usuário |
| `PORTAL_DB_PASSWORD` | valor de desenvolvimento; aleatório pelo instalador | sua senha |
| `PORTAL_DB_HOST` | `database-service:27017` | servidor e porta |
| `PORTAL_SECRET_KEY` | vazio no `.env.example`; aleatório pelo instalador | assina os cookies de sessão |
| `PORTAL_JOURNAL_SESSION_DAYS` | 180 | seção 3.5 |
| `PORTAL_JOURNAL_RECORD_DAYS` | 0 | seção 3.5 |
| `PORTAL_JOURNAL_ADMIN_DAYS` | 0 | seção 3.5 |
| `PORTAL_WORKER` (etapa 3) | `external` | seção 3.3: o serviço `portal-worker`, ou `embedded` |

O instalador mantém os valores existentes e acrescenta as chaves novas ao `.env`.

## 7. Entregas

| Etapa | Conteúdo | Verificação no staging |
|---|---|---|
| 1 | este registro (inglês e português) | nenhuma (documentação) |
| 2 | `portal/store.py`, usuários, metadados dos cadastros, diário com retenção, entradas recusadas e caches no MongoDB; `portal-db-init`; migração; instalador; testes com `mongomock`; job do CI com `mongo:7`; documentação | os arquivos antigos viram `*.migrated`; usuários, histórico e auditoria iguais no portal; o bloqueio de entrada funciona |
| 3 | coleção `jobs` e o serviço `portal-worker`; importações e verificações de links por ele | uma importação e uma "verificar todos os cadastros" terminam, inclusive com o portal reiniciado no meio; uma importação interrompida por um reinício do worker termina |
| 4 | réplicas no Compose, sem nomes fixos de contêiner; os pontos da seção 3.8 | duas réplicas de cada serviço respondem; as verificações de resolução de sempre passam |
