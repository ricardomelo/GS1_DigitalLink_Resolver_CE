# ADR 0006 — O registro das requisições ao Resolver

| | |
|---|---|
| Situação | **Aceita** (14 de outubro de 2026). A implementar em três etapas: 1 (este registro), 2 (o registro no servidor: captura no Resolver, agregados diários e leitura no portal, as chamadas da API das organizações), 3 (a tela *Acessos*) |
| Item do backlog | 4.1 — registro das requisições ao Resolver |
| Decidido por | o dono do branch, que pediu a opção recomendada em todos os pontos da seção 4 |
| Inglês | [ADR 0006 in English](../../adr/0006-resolver-request-log.md) (versão de referência) |

## 1. Contexto

O Resolver responde a cada leitura de um GS1 Digital Link, mas nada registra o que ele respondeu. Ninguém sabe dizer
com que frequência o QR de um produto é lido, quais códigos são lidos sem estar cadastrados (404), quais links são
servidos, quanto tempo as respostas levam ou se uma etiqueta impressa tem um erro. Os próximos itens do backlog
precisam exatamente disso: os indicadores da página inicial (4.2), os alertas de picos de 404 (4.3), o resumo
semanal (4.4) e os cliques da página de links (6.1). O ADR 0005 também deixou as leituras da API das organizações
sem registro, para este item.

O log de acesso dos processos do Resolver (o do gunicorn, na saída padrão) tem uma linha por requisição, mas só na
saída do contêiner, com o endereço do cliente às claras, sem o resultado da resolução, e se perde quando o contêiner
é recriado.

Restrições:

- **A resolução não pode ficar mais lenta nem falhar** por causa do registro: é o caminho de que todo código impresso
  depende.
- **Privacidade desde a concepção** (LGPD, GDPR): uma leitura é feita por uma pessoa, muitas vezes num celular; o
  registro deve responder perguntas sobre produtos, não sobre pessoas.
- O Resolver roda em várias réplicas e processos (ADR 0001); o MongoDB é o único armazenamento compartilhado.
- A posse dos cadastros é derivada dos prefixos de empresa GS1 e pode mudar (ADR 0002): o histórico deve
  acompanhá-la.
- O Resolver é o componente oficial; o seu comportamento (respostas, cabeçalhos, corpos) não pode mudar.

## 2. Decisão

1. **O próprio Resolver registra cada requisição de resolução**, no fim da requisição, a partir do que a resolução
   sabe: URIs GS1 Digital Link, as comprimidas, strings binárias EPC (`/eh…`, `/ex…`) e as requisições `?compress`.
   Não são registrados: `/heartbeat`, `/favicon.ico`, `/robots.txt`, `/.well-known/gs1resolver`, a página inicial,
   o portal, a API de cadastro.
2. **O que um evento guarda**: o horário; o método; a forma da requisição (sem compressão, comprimida, binário EPC e o
   seu esquema); a chave primária (AI e valor) e a parte onde começa o seu prefixo de empresa GS1; os qualificadores
   (AI e valor — **só o AI para um número de série (21) ou um TPX (235)**, que identificam uma unidade); os AIs dos
   atributos de dados da query string (**nunca os valores**); o tipo de link pedido; o resultado (redirecionamento,
   escolha entre links, linkset, código desconhecido, nenhum link daquele tipo, requisição inválida, erro, link
   comprimido) com o status HTTP; o nível do cadastro que respondeu; o host do destino; o tempo gasto; o idioma
   preferido; uma **classe de dispositivo** (celular, tablet, computador, automatizado, desconhecido) deduzida do
   User-Agent; o **host** de quem indicou (Referer); opcionalmente o país, quando um proxy na frente da instalação o
   envia num cabeçalho. **Nunca guardados**: o endereço do cliente em qualquer forma (nem com hash), o User-Agent, o
   Referer completo, cookies, valores de atributos de dados e de qualificadores de unidade, qualquer outro cabeçalho.
3. **Gravação assíncrona**: cada processo põe os eventos numa fila limitada em memória (10.000 eventos); uma thread
   em segundo plano os insere em lotes (até 500, pelo menos uma vez por segundo). Uma fila cheia ou um banco
   indisponível descarta eventos, conta-os e escreve um aviso no máximo uma vez por minuto; a resposta à leitura
   nunca espera pelo banco. Numa parada normal a thread grava o que tem.
4. **Armazenamento**: um banco próprio, **`resolver_log`**, coleção `requests`, gravado pelo Resolver com a conexão
   que ele já tem; cada evento leva a sua data de expiração (TTL), **`RESOLVER_LOG_DAYS`, 90 dias por padrão**; `0`
   desliga o registro. O usuário de banco do portal recebe acesso de **leitura** a `resolver_log` (`portal-db-init`),
   nunca de escrita. O backup diário deixa `resolver_log` de fora: os eventos brutos duram pouco, e o que fica está
   nos agregados abaixo.
5. **Agregados diários** no banco do portal (`request_daily`): a manutenção de hora em hora do worker (ADR 0005)
   conta os eventos de cada dia por chave primária — totais, resultados, classes de dispositivo, formas, idiomas,
   tipos de link, requisições automatizadas, tempo gasto — mais um documento por dia para a instalação inteira com os
   percentis 50, 95 e 99 do tempo gasto. Os dias são os do **`PORTAL_TIME_ZONE`** (UTC por padrão; o instalador grava
   o fuso do servidor). Um dia é contado de novo até terminar; os agregados ficam **`PORTAL_STATS_DAYS`, 800 dias
   por padrão** (dá para comparar um mês com o mesmo mês do ano anterior).
6. **Atribuição na hora da consulta**: eventos e agregados guardam a chave, nunca a organização. Os eventos de uma
   organização são aqueles cuja parte da empresa começa por um dos seus prefixos; os do operador são o resto. Um
   prefixo que passa de uma organização para outra leva o seu histórico junto.
7. **Quem vê o quê**: todo usuário vê os eventos dos cadastros ao seu alcance (a sua organização, os seus próprios
   prefixos, qualquer perfil); durante um acesso de suporte, os da organização. **Os administradores do servidor
   veem a instalação inteira** (todas as organizações, e requisições sem chave, como as inválidas), com a
   organização de cada evento — o operador mantém o Resolver e precisa ver o que chega a ele, e o registro não guarda
   nada sobre as pessoas que leem. Exportar o registro é um evento do diário (`requests-export`).
8. **As chamadas da API das organizações** (ADR 0005) são registradas pelo portal numa coleção própria,
   `api_requests`: horário, id da chave, organização, método, operação (o modelo da rota, nunca o cadastro nem a
   query string), status, tempo gasto; a mesma retenção, `RESOLVER_LOG_DAYS`. Os administradores veem as da sua
   organização; os administradores do servidor, as de todas.
9. **Uma tela *Acessos*** (etapa 3): as requisições dos últimos 30 dias em barras diárias, as últimas requisições
   com filtros (período, código, resultado, classe de dispositivo, requisições automatizadas ocultas por padrão), uma
   exportação CSV e, para administradores, uma segunda aba com as chamadas da API das organizações. Os indicadores
   propriamente ditos são o item 4.2.

## 3. Projeto

### 3.1 Um evento (`resolver_log.requests`, `web_server/src/request_log.py`)

```
{"t": <data>, "expiresAt": <data>, "m": "GET", "f": "uri" | "compressed" | "epc", "epc": "sgtin-96",
 "ai": "01", "v": "07898357410015", "cp": "7898357410015",
 "q": {"10": "L1", "21": null}, "da": ["17", "3103"], "lt": "pip",
 "s": 307, "o": "redirect", "lvl": "/10/L1", "to": "www.example.org", "ms": 12,
 "lang": "pt-br", "dev": "mobile", "ref": "www.example.com", "c": "BR",
 "p": "/wp-login.php"}
```

| Campo | Conteúdo |
|---|---|
| `t`, `expiresAt` | horário da requisição (UTC) e da sua exclusão (`t` + `RESOLVER_LOG_DAYS`, índice TTL) |
| `m`, `f`, `epc` | GET ou HEAD; `uri`, `compressed`, `epc`; o esquema EPC (só com `f` = `epc`) |
| `ai`, `v`, `cp` | a chave primária como resolvida (um GTIN-13 já como GTIN-14) e a sua parte da empresa: depois do dígito indicador de um GTIN ou ITIP, do dígito de extensão de um SSCC e do dígito de preenchimento de um GRAI (como `gs1.company_part()` no portal) |
| `q` | os qualificadores do caminho; `null` para 21 e 235 |
| `da` | AIs dos atributos de dados da query string (nomes de 2 a 4 dígitos) |
| `lt` | o tipo de link pedido, sem o endereço do vocabulário (`pip`); `linkset` para um linkset; ausente para o padrão |
| `s`, `o` | status HTTP e resultado: `redirect` 307, `choice` 300, `linkset` 200, `unknown` 404 (nenhum cadastro se aplica), `noLink` 404 (um cadastro se aplica, sem link daquele tipo), `invalid` 400, `error` 5xx, `compressed` 200 |
| `lvl` | o nível que respondeu (`""` para a chave, `/10/L1` para um lote; valores de unidade como `*`); só redirecionamento e escolha |
| `to` | host do destino (só redirecionamento) |
| `ms` | milissegundos da chegada da requisição ao Resolver até a resposta |
| `lang` | a primeira faixa de idioma do Accept-Language, em minúsculas (`pt-br`), ausente para `*` ou nenhuma |
| `dev` | `mobile`, `tablet`, `desktop`, `automated` (robôs de busca, prévias de link, monitores, ferramentas de linha de comando e bibliotecas), `unknown` (sem User-Agent) |
| `ref` | host do Referer, quando houver |
| `c` | código de país de duas letras do cabeçalho indicado em `RESOLVER_LOG_COUNTRY_HEADER` (vazio por padrão: sem país) |
| `p` | os primeiros 200 caracteres do caminho, só numa requisição inválida em que nenhuma chave pôde ser lida (para reconhecer sondagens) |

As rotas do Resolver preenchem em `flask.g` os campos que conhecem; um gancho `after_request` acrescenta status,
destino, tempo e cabeçalhos, e enfileira o evento. `web_logic.read_document()` devolve o nível e o motivo de um 404 em
chaves privadas (`_level`, `_outcome`) que `web_namespace` retira antes de responder, de modo que nenhuma resposta
muda.

Índices, criados pelo Resolver na primeira gravação: `t`; `cp` + `t`; `ai` + `v` + `t`; `expiresAt` (TTL).

### 3.2 Agregados diários (`request_daily`, `portal/requestlog.py`)

```
{"_id": "2026-10-14|01|07898357410015", "day": "2026-10-14", "ai": "01", "v": "07898357410015", "cp": "…",
 "total": 41, "automated": 3, "outcome": {"redirect": 37, "unknown": 0, …}, "device": {"mobile": 30, …},
 "form": {"uri": 40, "compressed": 1}, "language": [["pt-br", 33], ["en", 5]], "linkType": [["pip", 2]],
 "ms": 492, "msMax": 61, "expiresAt": <data>}
{"_id": "2026-10-14|*", "day": "2026-10-14", "total": 1290, …, "p50": 9, "p95": 31, "p99": 80}
```

Uma agregação por dia (`$match` no intervalo UTC do dia, um `$group` por chave, resultado, dispositivo, forma, idioma
e tipo de link), consolidada em Python. Listas em vez de subdocumentos onde os nomes vêm das requisições (tipos de
link podem ter pontos). Sob um bloqueio (`store.lock("request-stats")`); uma réplica que o encontra ocupado pula a
execução. A configuração `requestStats.finalUntil` guarda o último dia contado depois de terminado; cada execução
conta de novo do dia seguinte até hoje. Documentos de um dia que não são mais produzidos são removidos.

### 3.3 Leitura no portal

| Chamada | Quem | Resposta |
|---|---|---|
| `GET /portal/api/requests?from=&to=&code=&outcome=&device=&automated=&before=&limit=` | qualquer usuário | os eventos mais novos no escopo, no máximo `limit` (1–500, 200); `next` para a página seguinte |
| `GET /portal/api/requests.csv` (mesmos filtros) | qualquer usuário | até 50.000 eventos em CSV (UTF-8 com BOM, `;`, células protegidas); diário `requests-export` |
| `GET /portal/api/requests/daily?days=30` | qualquer usuário | requisições por dia no escopo, dos agregados, com as de hoje dos eventos brutos |
| `GET /portal/api/requests/api?from=&to=&key=&before=&limit=` | administradores | as chamadas da API das organizações no escopo |

O escopo é um filtro sobre `cp`: os prefixos de uma organização (ancorados, de `g.tenants`), os prefixos do próprio
usuário, ou, para os usuários do operador, "nenhum dos prefixos das organizações"; nenhum para um administrador do
servidor fora de um acesso de suporte. `/portal/api/config` ganha `requestLog: {"days": …}` (0: o registro está
desligado).

### 3.4 Como foi implementado (etapa 2)

- Um administrador do servidor **limitado a prefixos de empresa GS1** não vê a instalação inteira: como qualquer
  usuário do operador, vê os eventos do operador dentro dos seus prefixos (`app.log_sees_everything()`: um
  administrador do servidor fora de um acesso de suporte e sem prefixos).
- Classe de dispositivo: `unknown` também para um User-Agent que não corresponde a nada; as pilhas HTTP de apps nativos
  (okhttp, Dalvik, CFNetwork) contam como `mobile`, verificadas antes do padrão de tablet (o User-Agent de um app
  Android não tem "Mobile").
- Os agregados são gravados um documento por vez (`replace_one` com uma marca de execução), não numa gravação em lote;
  um dia com dezenas de milhares de chaves leva proporcionalmente mais tempo (o item 7.4 mede isso).
- As chamadas da API das organizações guardam o modelo da rota como o Flask o nomeia
  (`/portal/api/v1/records/<key>/<path:value>`), e a chave também quando uma chamada foi recusada depois de a chave
  ser reconhecida (limite de requisições, escopo).
- O instalador não pergunta o fuso; grava o do servidor (`timedatectl`, `/etc/timezone` ou o link `/etc/localtime`),
  mantém um valor existente e recusa um que não seja um nome IANA. A imagem do portal ganha o `tzdata`, para que os
  nomes funcionem qualquer que seja o conteúdo da imagem de base.

## 4. Opções consideradas

| Ponto | Escolhida (recomendada) | Não escolhidas |
|---|---|---|
| Onde as requisições são capturadas | no Resolver, depois da resolução (conhece o resultado, o nível, o tipo de link) | o log de acesso do nginx enviado ao MongoDB (outro serviço; o nginx não conhece resultado nem nível e vê o endereço do cliente); o portal (não vê as leituras) |
| O que identifica o cliente | nada | o endereço às claras (dado pessoal, regras de retenção); um hash diário com sal do endereço e do User-Agent (ainda dado pseudonimizado, pouco útil antes de o 4.2 pedir) |
| Qualificadores de unidade e atributos de dados | só os AIs | os valores (um número de série lido num horário e lugar pode identificar um comprador) |
| Gravação | uma fila limitada e lotes por processo; eventos descartados quando ela enche | uma inserção por requisição (soma o tempo do banco a cada leitura); um serviço coletor separado (mais uma peça) |
| Onde os eventos ficam | um banco próprio, `resolver_log`, legível pelo portal | o `resolver_ce` do Resolver (o portal precisaria ler cadastros que a API já lhe dá); o banco do portal (o Resolver precisaria das credenciais do portal) |
| Retenção | data de expiração por evento, 90 dias; agregados 800 dias | uma coleção limitada (o tamanho decide, não a idade); uma coleção de séries temporais (não existe nos substitutos de teste, mais difícil de consultar por chave) |
| Agregados | diários por chave, pelo worker, no fuso da instalação | por hora (mais documentos, pouco uso antes do 4.2); no Resolver (as réplicas competiriam); nenhum (todo indicador leria os eventos brutos) |
| Atribuição | na hora da consulta, pela parte da empresa | gravada em cada evento (errada depois que um prefixo muda de dono) |
| Administradores do servidor | a instalação inteira | só os cadastros do operador (os 404 de códigos desconhecidos e as sondagens não seriam vistos por ninguém) |
| Chamadas da API das organizações | registradas pelo portal, só o modelo da rota | não registradas (o ADR 0005 prometeu); no registro do Resolver (requisições de outro componente) |
| Entrega | três etapas: registro, servidor, tela | uma etapa |

## 5. Consequências

- A instalação passa a saber como os seus códigos são usados e onde a resolução falha, sem registrar nada sobre as
  pessoas que leem: nenhum endereço, nenhum User-Agent, nenhum número de série, nenhum valor de atributo de dados. Um
  aviso de privacidade do operador pode dizer isso.
- Sob carga pesada ou com o banco fora do ar, alguns eventos podem se perder; a resolução nunca é afetada. Os eventos
  perdidos são contados na saída do Resolver.
- Os eventos brutos crescem com o tráfego: cerca de 300 bytes cada, mais índices; com um milhão de leituras por dia e
  90 dias, uns 30 GB. `RESOLVER_LOG_DAYS` é a alavanca; os agregados continuam pequenos (um documento por chave e dia).
- O backup não guarda mais `resolver_log`; uma restauração começa com o registro bruto vazio e os agregados do
  backup.
- Um portal que usa um banco externo por `PORTAL_DB_URI` só lê o registro se aquele servidor também tiver o
  `resolver_log`.
- As requisições feitas pelas próprias verificações da instalação (os `curl` do plano de testes, a suíte de testes da
  GS1) também são registradas, como `automated`.

## 6. Configuração acrescentada

| Variável | Padrão | |
|---|---|---|
| `RESOLVER_LOG_DAYS` | 90 | dias em que os eventos brutos (e as chamadas da API das organizações) são guardados; 0 desliga o registro |
| `RESOLVER_LOG_COUNTRY_HEADER` | vazio | um cabeçalho com o código de país de duas letras posto por um proxy na frente da instalação (por exemplo `CF-IPCountry`) |
| `PORTAL_TIME_ZONE` | UTC | o fuso dos dias dos agregados (nome IANA, por exemplo `America/Sao_Paulo`); o instalador grava o do servidor |
| `PORTAL_STATS_DAYS` | 800 | dias em que os agregados diários são guardados |

## 7. Entrega

1. Este registro (nos dois idiomas).
2. No servidor: `web_server/src/request_log.py` e os ganchos no Resolver; o papel de leitura em `db_init.py`;
   `portal/requestlog.py` (escopo, leitura, agregados na manutenção do worker), as chamadas da API das organizações, os
   endpoints do portal; o backup sem `resolver_log`; o fuso no instalador; testes de desenvolvimento.
3. A tela *Acessos*, o teste de ponta a ponta, imagens, os guias do usuário e do desenvolvedor.
