# Histórico do Expansion Pack

Como o GS1 Digital Link Resolver CE — Expansion Pack cresceu a partir do GS1 Resolver CE v3 oficial,
sessão por sessão, com as decisões tomadas no caminho e os motivos. A lista dia a dia das mudanças está no
[CHANGELOG](../extensions/CHANGELOG.md) (em inglês); o que cada funcionalidade faz hoje está em
[funcionalidades](funcionalidades.md).

*English version: [history](../history.md).*

O trabalho foi feito em seis sessões entre 22 de setembro e 2 de outubro de 2026, sobre uma instalação
de homologação do Resolver operada pelo mantenedor. Cada incremento foi testado nessa instalação antes de
o próximo começar.

## Linha do tempo

| Sessão | Datas (2026) | Entrega | Resultado |
|---|---|---|---|
| 0 — ponto de partida | março | commit oficial `bf885fd` | GS1 Resolver CE v3, cadastro só por API JSON |
| 1 — portal 1.0.0 | até 23/09 | pacote zip com um patch sobre o código oficial | portal para GTINs e lotes, correções de conformidade, etiquetas, backup |
| 2 — o fork | 25 a 29/09 | 21 commits, `d51e398` → `7e7a62a` | fork com histórico git, instalador, todas as chaves e qualificadores, planilhas, verificador de links, governança |
| 3 — Expansion Pack | 29 e 30/09 | 22 commits, `d4e5584` → `cf5ce10` | caracteres especiais, atributos de dados, opções do QR, novo layout do editor, outros cadastros da chave |
| 4 — busca e documentação | 30/09 a 01/10 | `f4f3071` e os commits de documentação | filtros por tipo de chave e qualificador, busca por código, guia do portal, funcionalidades, este histórico, guia do desenvolvedor, docstrings, versão em português |
| 5 — revisão de conformidade e 2.5.9 | 01/10 | `324d85b` → `db8e342` e os commits de documentação | revisão de conformidade cláusula a cláusula, modelo de cadastro do Resolver 2.5.9 (lote e variante informativos numa série), um link padrão acima de todo cadastro, correções de resolução (item 1.5) |
| 6 — EPC em binário | 02/10 | `51a0da8` → `4b9a7be` e os commits de documentação | `/eh…` e `/ex…` descomprimidos para todos os esquemas EPC que têm GS1 Digital Link (item 1.6), a partir dos artefatos do TDT 2.2 e do TDS 2.3; nome do upstream do proxy corrigido (toda resolução pelo nginx dava 500 desde o 1.5); mais quatro candidatos a errata; confirmado na homologação |
| 7 — suíte de testes da GS1 | 02/10 | `bc573c4` → `386a8c3` | a própria suíte da GS1 aprovada na homologação (31 de 31), tipos de link publicados em `https://ref.gs1.org/voc/` (F22), errata E12, backlog em aberto no README |
| 8 — backlog, ajustes rápidos, CI | 13/10 | `bc1c86b`, `1a1ca59`, `d68a883` e os commits de documentação | backlog reordenado em torno de tenants, e-mail, chaves de API e domínios próprios; sessão de 30 minutos sem uso com aviso e limite de 12 horas; quadro da sintaxe retirado da página inicial; aviso da comunidade; testes de desenvolvimento pelo pytest e no GitHub Actions |
| 9 — arquitetura para escala | 13/10 | ADR 0001, depois três entregas de código (`d783f3d`, `a072e9d`, `20f3304`) e os commits de documentação | item 2.3: o estado do portal no MongoDB, as tarefas em segundo plano num serviço worker, réplicas de todos os serviços sem estado atrás de um proxy que as acha sozinho; gunicorn em todos os serviços web; nginx 1.30 |

Ao fim da sessão 4, o fork altera ou acrescenta 70 arquivos do projeto oficial (cerca de 16.000 linhas
acrescentadas) e é coberto por 739 verificações nos testes de desenvolvimento, além do teste do
instalador.

## Sessão 0 — o projeto oficial

GS1 Resolver Community Edition v3 (commit oficial `bf885fdf4888f0395229478bf6b50342c1f761a8`, março de
2026): um Resolver em Python (`web_server`), uma API de cadastro (`data_entry_server`), MongoDB e um
front-end nginx, executados com Docker Compose. Os cadastros são feitos enviando documentos JSON no formato
Resolver CE v3 com um token bearer, o que exige conhecimento técnico. A suíte de conformidade da GS1,
rodada contra uma instalação, mostrou vários defeitos (ver sessão 1).

## Sessão 1 — um portal para usuários leigos (versão 1.0.0)

**Objetivo.** Permitir que pessoas que não são desenvolvedoras cadastrem para onde leva o QR Code de um
produto, e corrigir os defeitos de conformidade encontrados no Resolver.

**Arquitetura escolhida.** Um serviço novo, `portal-service` (Flask com gunicorn), serve as páginas *e*
conversa com a API de cadastro do lado do servidor. O token da API nunca chega ao navegador, e o portal
escolhe a sequência segura de chamadas — a API acrescenta no `POST /new`, mescla no `PUT` e exclui
documentos inteiros no `DELETE`, então um formulário ingênuo duplicaria ou perderia destinos. Esse
"back-end para o front-end" continua sendo o núcleo do projeto.

**Entregue** como pacote zip (portal, `gs1br-resolver.patch` para o código oficial, override do Compose,
arquivo de descrição, script de backup, testes, `SHA256SUMS`), instalado no servidor de homologação e
confirmado funcionando em 23 de setembro como checkpoint 1.0.0:

- formulário em três passos: GTIN com conferência do dígito verificador e lote opcional, descrição,
  destinos com tipo de link, idioma, destino principal e repasse de parâmetros por destino (`fwqs`);
- etiquetas com QR Code (PNG, SVG em milímetros) seguindo as dimensões do *QR Codes powered by GS1*, com
  uma marca opcional (depois retirada);
- português do Brasil e inglês britânico, com troca ao vivo, códigos de mensagem traduzidos no navegador
  e a escolha compartilhada com as páginas do Resolver por um cookie;
- entrada com cookie de sessão, bloqueio depois de cinco falhas, troca de senha que encerra as outras
  sessões;
- correções no Resolver: subida de um lote desconhecido para o GTIN, barra no final, todas as formas de
  `linkType`, 404 para tipo de link ausente, linkset RFC 9264 válido no schema da GS1, cabeçalho do
  contexto JSON-LD, `fwqs`, páginas HTML para navegadores;
- arquivo de descrição com a raiz real do Resolver, portas 8080 e 27017 presas a 127.0.0.1, backup diário
  do MongoDB;
- testes de desenvolvimento: 53 verificações do Resolver e 16 do portal num navegador real.

**Aprendido na instalação.** `FQDN` precisa ter só o domínio (um valor com `https://` gerava
`https://https://…` nos linksets); o Docker publica portas passando por cima do firewall do host, então
atrás de um proxy TLS as portas precisam ficar em 127.0.0.1; para reaplicar um patch, os arquivos devem ser
restaurados do `HEAD`, e não do índice do git, que guardava uma cópia já modificada.

**Ficou em aberto.** Troca dos segredos de desenvolvimento, um registro da suíte de conformidade, uma cópia
do backup fora do servidor e uma lista de melhorias: lista de registros, planilhas, verificador de links,
números de série e variantes, perfis e prefixos, histórico e auditoria.

## Sessão 2 — o fork e as grandes funcionalidades

**Do patch para o fork.** Manter um patch sobre uma cópia intocada do projeto oficial era frágil. O
trabalho passou para um fork do repositório oficial no GitHub (branch `gs1br/develop`, tornado o branch
padrão) — o primeiro projeto do mantenedor no GitHub. Cada incremento é entregue como um git bundle que o
mantenedor aplica na estação de trabalho e envia com push; o servidor acompanha com
`git pull && docker compose up -d --build`. O conteúdo da 1.0.0 foi reescrito em sete commits por assunto,
para que cada um possa ser revisado separadamente.

| Commit | Mudança | Por quê |
|---|---|---|
| `d51e398` | `.env.example` com padrões de desenvolvimento + `.env` opcional para os valores reais; variáveis de bind | manter os nomes de variável oficiais e versionar só padrões seguros |
| `766a652` | correções de conformidade do Resolver e páginas HTML; arquivo de descrição pela configuração | vindo da 1.0.0, agora como commit revisável |
| `126f507` | o portal (primeiro usuário por `PORTAL_ADMIN_*`, volume de configuração nomeado) | vindo da 1.0.0 |
| `ec1f1d7` | página inicial em `/` | a raiz de um Resolver deve se explicar a uma pessoa |
| `ba0c293` | backup do banco e do volume do portal | usuários e metadados ficam fora do MongoDB |
| `0733a3f`, `539bab0` | testes de desenvolvimento; documentação das extensões e changelog | |
| `e11f630` | `scripts/install.sh` para Ubuntu 22.04/24.04 | um terceiro deve conseguir instalar sem conhecer este histórico |
| `5f8c7d7` | o Compose reinicia o proxy quando um serviço é recriado | o nginx resolve os nomes dos upstreams só na inicialização |
| `a49f24d` | navegação de volta à página inicial | |
| `db56b22` | lista de registros com busca; `GET /api/summary` | uma chamada para todos os cadastros em vez de uma por identificador |
| `1941e75` | token em `/api/index`; `BearerAuth` no Swagger | o `/api/index` oficial listava publicamente todos os identificadores (um aviso aos mantenedores oficiais foi redigido) |
| `429dce7`, `7339e3c` | importação/exportação de planilhas com prévia; qualquer idioma BCP 47, modelos de lote, todas as linhas erradas de uma vez | trabalho em lote; testar com cadastros de outras ferramentas revelou suposições |
| `0da20ee` | verificador de links com proteção contra SSRF | destinos quebrados são o defeito mais comum de um Resolver |
| `e181ccc` | todas as chaves primárias da URI Syntax 1.7 §4.3 | o portal só aceitava GTIN |
| `67d40bb` | todos os qualificadores (§4.4, 4.6, 4.9); AI 415 + 8020 | completa o lado de identificação do padrão |
| `f14d8c4`, `85346a3` | README do fork com screenshots; README oficial guardado à parte | |
| `71b15f2` | governança: perfis, prefixos de empresa GS1 por usuário, tela de usuários, histórico do cadastro, auditoria | necessária antes de alguém além do operador usar o portal |
| `7e7a62a` | marca GS1 retirada das etiquetas; nome do AI 415; qualificador 235 chamado de TPX | etiquetas não podem sugerir endosso |

**Decisões desta sessão.** A validação espelha o GS1 Barcode Syntax Engine e os testes comparam os dois;
valores alfanuméricos limitados a letras, números, `.`, `-` (e `_` nos qualificadores); ITIP oferecido sem
o qualificador 22, que o engine recusa; o prefixo de empresa GS1 de um identificador é lido depois do
dígito indicador (GTIN-14, ITIP), do dígito de extensão (SSCC) ou do zero inicial (GRAI); usuários criados
antes dos perfis são administradores; um único worker do gunicorn com threads, porque o bloqueio de
tentativas e as tarefas em segundo plano ficam em memória.

## Sessão 3 — "Expansion Pack": robustez e atributos de dados

O fork ganhou o nome público *GS1 Digital Link Resolver CE — Expansion Pack*, e o README deixou de citar
organização ou mantenedor: instalações de terceiros não devem ser associadas a nenhuma organização GS1. O
operador mostrado em cada instalação vem só do `.env` dela.

| Commit | Mudança | Por quê |
|---|---|---|
| `d4e5584`, `e99fc21` | título do README; créditos sem o mantenedor | neutralidade do projeto publicado |
| `9d12f9d` | limites de importação por formato mostrados na janela; célula enorme de CSV não causa mais erro 500 | o usuário precisa saber os limites antes de enviar |
| `1b58bfd` | caracteres especiais: só dígitos ASCII, invisíveis removidos, texto NFC, endereços seguros, proteção contra fórmulas na exportação, importação UTF-16, registro seguro nos logs | texto copiado de documentos e planilhas traz caracteres invisíveis e parecidos |
| `3f1ff37` | senhas com caracteres especiais no instalador | |
| `b33def6`, `92bfb5d` | nomes dos níveis na página HTML do linkset; só destinos `http(s)` viram links | clareza; a API aceita qualquer `href`, então `javascript:` nunca pode virar link |
| `13dbf05` | documentação das extensões reescrita para todas as chaves e qualificadores | |
| `289822d` → `764e360` | rodapé do operador retirado e depois restaurado | o nome do operador já era configurável, então podia ficar |
| `cc72145` | nome do operador com link para `RESOLVER_ORG_URL` (`contact.hasURL`) | |
| `4b42c6f` | **atributos de dados** (§4.10) nos QR Codes, validados pelo GS1 Barcode Syntax Engine 1.4.1 (biblioteca C + binding Python compilados num estágio do Docker) | o engine da própria GS1 em vez de reimplementar centenas de regras de AIs; atributos nunca são gravados |
| `1525f82` | versão e correção de erros do QR, modos de HRI, caixa de combinação de atributos, botão de mostrar senha | a arte precisa de tamanho fixo; a lista nativa falhava no celular |
| `1746f19` | bloco da etiqueta embaixo do formulário em qualquer largura | escolhido entre duas maquetes (B) |
| `e71384d` | famílias decimais (310n, 392n…), sem limite de 10 atributos | as pessoas digitam `1,5 kg`, não `3103=001500` |
| `08570e4`, `cf5ce10` | outros cadastros da mesma chave embaixo de *Abrir cadastro*; 216 nomes de AIs em português; erros de associação traduzidos | um GTIN com dezenas de lotes precisa de lista; nomes no idioma do usuário |

Toda funcionalidade com layout visível foi mostrada antes como maquete — imagens geradas a partir do portal
real — e aprovada antes de ser implementada. As imagens do README são regeneradas por um script, com o
logotipo GS1 oculto.

## Sessão 4 — busca por tipo de chave e qualificador; documentação

| Commit | Mudança |
|---|---|
| `f4f3071` | filtros da lista de registros por tipo de chave primária e por qualificador, com contagens; um GS1 Digital Link colado ou uma element string com parênteses acha o cadastro exato e os relacionados |
| `d11c369` | "mais um cadastro" no singular embaixo de *Abrir cadastro* |
| `52a1087` | docstrings em todas as funções escritas para o fork; mapa do `app.js` |
| documentação | guia do portal com screenshots, funcionalidades, histórico, guia do desenvolvedor, índice, README; depois a versão em português do Brasil, com screenshots em pt-BR |

O pedido de filtrar por "key attributes" foi entendido como os qualificadores de chave do padrão: atributos
de dados nunca são gravados, então não há como filtrá-los.

## Sessão 5 — revisão de conformidade e o modelo de cadastro do 2.5.9

| Commit | Mudança |
|---|---|
| `324d85b`, `b2bda36` | [revisão de conformidade](revisao-de-conformidade.md) do branch frente à URI Syntax 1.7 e ao Resolver 1.2.1: 23 achados, 7 candidatos a errata, resultados da homologação; itens 1.5 (correções de resolução) e 1.6 (EPC binary) propostos |
| `61babe1` | a API de cadastro recusa cadastros contra o 2.5.9 e guarda `informativeQualifiers`; o Resolver prefere o cadastro da série ao do lote |
| `83d1ba0` | portal: lote e variante de uma série são informativos (proposta C dos mock-ups), *Este cadastro vale para*; parte servidor do cadastro da chave |
| `3a49ca9` | portal: diálogo que oferece o cadastro da chave ao salvar, filtro *Situação* e alerta, importação de chaves sem cadastro, *Copiar destinos de…*, confirmação no *Abrir cadastro* |
| `4f81234` | Resolver e proxy (item 1.5): resposta padrão e `gs1:defaultLinkMulti`, escolha do link (exemplos 5 a 13), caminhos conferidos pelo leitor de Digital Link do engine, `%2F` em valores, query string original, 400 em vez de 500, 300 como linkset, JSON-LD no HTML, arquivo de descrição |
| `db8e342` | portal (item 1.5): saiu a opção de repasse da query string por destino; `RESOLVER_TERMS_URL` |

Decisões do responsável: a opção por link de não repassar a query string sai (item 1.5, F14); lote e
variante de uma série ficam no banco como informação, e não só no QR Code, para poderem ser buscados,
filtrados e exportados; o cadastro da chave é oferecido, com os mesmos destinos pré-selecionados.

## Sessão 6 — EPC em binário

| Commit | Mudança |
|---|---|
| `51a0da8` | `epc_binary.py`: EPC em binário decodificado para GS1 Digital Link — esquemas anteriores ao TDS 2.0 inteiramente a partir dos artefatos do TDT 2.2 (agora em `web_server/src/tdt/`), esquemas `+` com a Tabela F e seus dados +AIDC, esquemas `++` com o hostname; o `test_epc_binary.py` confere todos os vetores do anexo E.3 do TDS 2.3 e 800 EPCs aleatórios contra a biblioteca `epc-tds` |
| `b9a7631` | proxy: o upstream `resolver_web` do item 1.5 renomeado para `resolver-web` — o Werkzeug recusava o sublinhado no cabeçalho Host, então toda resolução pelo nginx dava 500 na homologação desde o 1.5; o `test_home.py` agora confere o cabeçalho Host |
| `895c4b1` | Resolver: `/eh…` e `/ex…` resolvidos como o GS1 Digital Link descomprimido (F6, restante do F7); atributos de dados conferidos pelo engine e repassados; 400 quando a cadeia não decodifica |

Decisões do responsável: o decodificador cobre todos os esquemas de uma vez (clássicos, `+` com dados
+AIDC, `++`); qualificadores trazidos pela etiqueta vão para o caminho e atributos de dados para a query
string repassada ao destino; o hostname dentro de um EPC `++` é ignorado e o Resolver mantém o próprio
domínio. A implementação lê os artefatos do TDT (sem código específico por esquema para os clássicos) em
vez de usar a biblioteca `epc-tds`, que conhece só parte dos esquemas clássicos e nada do TDS 2.0; o
`epc-tds` serve de conferência independente nos testes.

Homologação (2 de outubro, pelo proxy): um GTIN cadastrado `/01/…` → 307; o mesmo GTIN como SGTIN-96 nas
formas `eh` e `ex` → 307 para o mesmo destino; um SGTIN+ com lote 123 e validade em +AIDC → 307 para o
destino do cadastro do lote, com `?17=261231`; um GID-96 → 400 com o motivo. A primeira tentativa deu 500 em
tudo: foi assim que apareceu o defeito do nome do upstream do item 1.5.

Candidatos a errata encontrados ao decodificar: E8 (EPCB 4.2.2), E9 (anexo E.3 do TDS 2.3: cabeçalhos de
SSCC++ e ITIP++, hostnames de SGTIN++ e DSGTIN++, uma EPC URI), E10 (Tabelas 14-14 e 14-15 do TDS 2.3), E11
(artefato do TDT do CPI-var) — seção 6 da revisão de conformidade.

## Sessão 7 — suíte de testes de Resolver da GS1 (item 1.4)

| Commit | Mudança |
|---|---|
| `bc573c4` | Resolver: linksets e contexto JSON-LD escrevem os tipos de link `gs1:` em `https://ref.gs1.org/voc/` (Resolver 2.14, F22); documentos gravados sem alteração |
| `cc95d77` | `test_gs1_suite.py`: a suíte de testes de Resolver da GS1, com o JavaScript sem alteração, no Chromium contra o código do Resolver, com uma versão em Python do seu auxiliar PHP; sete cenários |

O código da suíte foi lido e executado no ambiente de desenvolvimento antes de o responsável rodá-la na
homologação. Homologação (2 de outubro, `ef96276`, um GTIN com link padrão em português e inglês e
instruções nos dois idiomas): **31 de 31 testes aprovados**. No ambiente de desenvolvimento resta uma
divergência, que a homologação não exercita: sob um lote com link padrão próprio, a suíte espera as
variantes de idioma do padrão do GTIN (errata E12; o Resolver mantém o padrão do lote). Depois da instalação do `bc573c4`: 31 de 31 de novo,
tipos de link em `https://ref.gs1.org/voc/` e as verificações F9-F13 da revisão de conformidade todas como
esperado (307 para o link padrão, 400, 400, 307 subindo com `%2F`, query string repassada como enviada). O GTIN da
verificação habitual de cada instalação respondeu 404 na mesma ocasião: o cadastro dele tinha sido apagado na
homologação, e um GTIN válido sem cadastro é um 404 (2.4.1). O backlog em aberto passou a constar do README.

Decisões do responsável: os tipos de link são publicados em `https://ref.gs1.org/voc/` (opção B do F22); o
comportamento da E12 é mantido e vira errata e issue para a suíte.

## Sessão 8 — backlog reordenado, ajustes rápidos (item 2.1), integração contínua (item 2.2)

| Commit | Mudança |
|---|---|
| `bc1c86b` | backlog do README reescrito a partir das anotações do responsável de 13 de outubro: ajustes rápidos, arquitetura para escala com os dados do portal no MongoDB, tenants com administradores do servidor e do tenant, e-mail, uma API do tenant com chaves de API, analytics por tenant com exportação, o domínio do próprio tenant no QR Code, Verified by GS1 na página de destinos, um teste de carga |
| `1a1ca59` | portal: a sessão termina após 30 minutos sem uso e 12 horas depois da entrada, com aviso dois minutos antes, renovação enquanto o usuário trabalha e compartilhada entre abas; página inicial sem o quadro da sintaxe GS1 Digital Link; aviso da comunidade no README, na documentação e nos rodapés; `test_session.py` |
| `d68a883` | integração contínua (item 2.2): o `dev-tests/test_programs.py` roda todos os programas de teste pelo pytest, por grupo, com um modo estrito; workflow `.github/workflows/dev-tests.yml` com cinco jobs paralelos e uma action de preparação que fixa todas as versões; o `main.yml` vazio removido; selo de status |

Depois de uma pausa de 2 a 13 de outubro, o fork, o projeto oficial e a suíte da GS1 não tinham mudado. As
anotações do responsável foram avaliadas uma a uma: todas ficaram, algumas fundidas a itens existentes. A
ordem põe o armazenamento de dados do portal e os tenants antes da API, do e-mail e dos analytics, porque os
três precisam saber de quem são os dados que tratam. Duas anotações tiveram o escopo ajustado: o link do
Verified by GS1 fica só na página de destinos, já que o tipo de link `gs1:verificationService` designa um
serviço GS1 Lightweight Messaging, não uma página web; e o domínio próprio de um tenant só responde pelos
prefixos desse tenant, depois de uma prova por DNS de que o domínio é dele.

Decisões do responsável: o aviso não nomeia organizações ("não pela GS1 nem por qualquer Organização-Membro
GS1"); a sessão termina após 30 minutos sem uso, com aviso dois minutos antes e limite de 12 horas por
entrada, ambos configuráveis.

Compilação do engine de sintaxe do portal no ambiente de desenvolvimento: o arquivo da release não pôde ser
baixado ali, então a mesma tag foi clonada com git e compilada com os passos do script (o script não mudou).

Integração contínua (item 2.2). Decisões do responsável: uma camada fina de pytest sobre os programas
existentes (não uma reescrita das verificações); cinco jobs em paralelo; todos obrigatórios, menos o portal
no Chromium e o instalador, que começam como informativos; um selo de status no README. Antes de escrever o
workflow a linha de base foi rodada de novo (`a6be2ad`: 194 e 215 verificações, depois todos os programas), e
ficou provado que a camada sabe falhar: uma mudança proposital no verificador de links fez duas verificações
falharem, e a camada as relatou. Os passos de preparação também rodaram com Python 3.12, uma pasta de cache
limpa e as versões npm fixadas, como num runner: todos os programas passaram. O teste do instalador, que
precisa de root, rodou como usuário comum com sudo sem senha. Os logs das execuções do GitHub Actions exigem
login, então os primeiros resultados vêm do responsável.
A primeira execução (Development tests #1, em `c7ca3aa`) passou em todos os jobs em 5 minutos e 42 segundos,
sem cache, e cada programa relatou as mesmas contagens de verificações do ambiente de desenvolvimento.

## Sessão 9 — arquitetura para escala e os dados do portal no MongoDB (item 2.3)

O fork, o projeto oficial e a suíte da GS1 não mudaram desde a sessão 8; a linha de base passou (1.143
verificações em 14 programas, como no CI). A leitura do portal confirmou onde fica seu estado e encontrou
mais estado em memória do que o previsto (prévias de importação, a última verificação de todos os links, o
cache do verificador). Mostrou também que os serviços oficiais do Resolver e da API de cadastro usam o
servidor embutido do Flask e que todo serviço do Compose tem um nome de contêiner fixo, que o Compose não
replica; os dois pontos ficam para a etapa 4.

O responsável decidiu os oito pontos do item, todos nas opções recomendadas: um banco próprio do portal com
usuário de permissões mínimas; tarefas em segundo plano numa coleção do MongoDB executadas por um contêiner
worker; entradas recusadas e caches em coleções com índices TTL; a chave de sessão no `.env`; retenção do
diário por idade, por categoria; migração automática no início; `mongomock` nos programas de teste mais um
job do CI com MongoDB real; quatro entregas. Elas estão registradas no
[ADR 0001](adr/0001-estado-do-portal-no-mongodb.md) (etapa 1).

| Commit | Mudança |
|---|---|
| `f9c38a2` | docs: o título "Como as principais áreas evoluíram" restaurado nos dois históricos (perdido num commit de documentação da sessão 8) |
| `076f19a` | ADR 0001 em inglês e português (etapa 1) |
| `d783f3d` | etapa 2: `store.py`, usuários, metadados dos cadastros, diário com retenção, entradas recusadas e caches no MongoDB; `migrate.py`; `db_init.py` e o serviço `portal-db-init`; o instalador gera `PORTAL_DB_PASSWORD` e `PORTAL_SECRET_KEY`; `test_store.py`, `test_store_mongodb.py` e o job do CI num MongoDB real |
| `d7644b1` | docs: a etapa 2 no changelog, nas funcionalidades e nos históricos |
| `a072e9d` | etapa 3: `jobs.py` e `worker.py`; importações e verificações de links como tarefas; o serviço `portal-worker` e `PORTAL_WORKER`; mensagens de fila, de "não está em execução" e de falha no navegador; `worker` na verificação de saúde e nas conferências do instalador; `test_jobs.py`, `test_worker_processes.py`, cenários de e2e e do instalador |
| `f1e4577` | docs: etapa 3 no changelog, nas funcionalidades e nos históricos |
| `20f3304` | etapa 4: réplicas (`deploy.replicas` a partir do `.env`, sem `container_name` fixo nos serviços replicáveis); gunicorn no Resolver e na API de cadastro, `WEB_CONCURRENCY` processos em todos; nginx 1.30 com `resolve` em todos os upstreams; a chave de sessão reserva do portal segura com inícios simultâneos; quantidades de réplicas no instalador; jobs e2e e do instalador obrigatórios; `test_deploy.py`, réplicas no `test_home.py` e no `test_install.sh` |
| `c426dfd` | docs: etapa 4 no changelog, nas funcionalidades e nos históricos |
| `3298da7` | dev-tests: todas as pastas temporárias do nginx na pasta de trabalho do teste do proxy (a primeira execução do CI no nginx do nginx.org) |

Etapa 2. Três detalhes mudaram durante a construção, e o ADR 0001 foi alinhado: o usuário do portal é
criado por um script Python na imagem do portal (`db_init.py`), para que o CI rode o mesmo script contra um
MongoDB real; a regra que mantém o último administrador roda sob um documento de trava comum a todos os
processos, porque um MongoDB sem replica set não tem transações entre documentos; e a retenção do diário
conta dias inteiros a partir do fim do dia do evento, o que permite aplicar um valor alterado um dia por vez
(o mongomock não calcula datas numa atualização). O ambiente de desenvolvimento não consegue baixar o
MongoDB, então os programas rodam no mongomock ali e num contêiner de serviço `mongo:7` real no CI; o job do
CI começa como informativo. Uma mutação proposital (sem trava nas alterações de usuários) passou de início
pela verificação de remoção simultânea, porque o mongomock raramente intercala as duas threads; foi
acrescentada uma verificação determinística (uma alteração espera enquanto outro processo segura a trava),
que a pega. A etapa 2 foi confirmada no staging (2 usuários, 3 metadados de cadastro e 55 eventos do diário
migrados), e o job do CI num MongoDB real passou nas suas 76 verificações na primeira execução.

Etapa 3. O responsável decidiu os quatro pontos em aberto nas opções recomendadas: `PORTAL_WORKER=external`
(o serviço `portal-worker`, sempre no Compose) ou `embedded` (uma thread do portal, para os testes e uma
instalação sem o serviço); uma importação interrompida continua do primeiro cadastro não gravado; um worker
até a etapa 4; sem botão de cancelar por enquanto. A implementação acrescentou, e o ADR 0001 agora registra:
um limite de três tentativas por tarefa, para que uma tarefa que derruba seu worker não fique em ciclo;
gravações que só valem se a tarefa ainda for do worker (`JobLost`); devolução imediata no SIGTERM; anúncios
dos workers, para que o navegador diga que nenhum worker está rodando em vez de esperar calado, e para que a
verificação de saúde e o instalador o informem; uma verificação de links que recomeça em vez de continuar (o
cache responde o que já foi feito). Os programas que rodam importações usam o worker embutido; o
`test_jobs.py` comanda os workers diretamente, e o `test_worker_processes.py` inicia o `worker.py` como
processos que dividem uma fila, o que exige um MongoDB real: ele roda no job "database" do CI. No ambiente de
desenvolvimento ele também foi rodado contra o FerretDB (um servidor compatível com o MongoDB sobre SQLite,
baixado do GitHub) com os índices TTL desligados: passou, e uma mutação proposital (retirar também tarefas
em execução) reprovou três das suas verificações. A etapa 3 foi confirmada na homologação: o worker se
apresentou, a verificação de saúde o informou, *Verificar links* e uma importação da planilha exportada
terminaram, uma verificação esperou com o aviso de "fora do ar" enquanto o worker estava parado e terminou
quando ele voltou; a execução do CI do `f1e4577` ficou verde nos seis jobs (161 verificações no MongoDB real).

Etapa 4. O responsável escolheu, tudo nas opções recomendadas: nginx 1.30 achando as réplicas sozinho;
gunicorn em todos os serviços web; quantidades de réplicas no `.env`, uma de cada por padrão; os jobs e2e e
do instalador obrigatórios já, o do MongoDB real informativo mais um tempo. Só os três serviços replicáveis
que tinham nome fixo de contêiner o perderam; o banco e o proxy, que não podem ser replicados, mantêm os nomes
oficiais. A leitura da configuração mostrou que o plano do ADR (o nginx consultando os nomes na
inicialização, reiniciado pelo Compose quando um serviço é recriado) atenderia as réplicas que existiam
quando o proxy iniciou, mas nunca uma acrescentada depois, e que o `--scale` é esquecido na atualização
seguinte; daí o `resolve` nos blocos upstream, que exige o nginx 1.27.3 ou posterior e levou a imagem do proxy
do 1.25.1 ao ramo estável 1.30, e as quantidades no `.env`, que o instalador agora grava. Rodar vários
processos do gunicorn expôs uma condição de corrida no `secret.key` reserva do portal (um processo podia ler
o arquivo que outro criara mas ainda não gravara, e assinar sessões com uma chave vazia): a chave agora é
gravada com outro nome e ligada ao nome final. Inícios simultâneos de seis processos não reproduziram a
corrida; uma verificação determinística (oito threads pedindo a chave enquanto gravá-la é lento) reprova o
código anterior e passa agora. O teste do proxy roda a configuração real no nginx 1.30 (compilado do código
no ambiente de desenvolvimento, do nginx.org no CI) com um pequeno servidor DNS próprio, que responde os nomes
dos serviços com réplicas em `127.0.0.x`, e o `test_deploy.py` inicia o comando gunicorn de cada imagem. Um
ensaio no ambiente de desenvolvimento pôs duas réplicas gunicorn do Resolver e da API de cadastro atrás desse
proxy: as requisições foram repartidas por igual; os cadastros em si não puderam ser gravados, porque o
FerretDB recusa chaves com ponto, que os cadastros oficiais usam.

A etapa 4 foi confirmada na homologação: depois de um backup e das quatro quantidades de réplicas definidas
como 2 no `.env`, o `docker compose up -d --build` trocou os contêineres de nome fixo por dois de cada serviço
(`gs1_digitallink_resolver_ce-web-service-1`, `-2`, …) ao lado dos únicos `database-server` e
`frontend-proxy-server`; a verificação de saúde, as duas resoluções pelo proxy e os dois anúncios de worker
ficaram como esperado; doze resoluções foram repartidas seis e seis entre as duas réplicas do `web-service`; no
navegador, entrar, passar de tela em tela entre réplicas, salvar um produto e um lote, exportar, importar e
redirecionar funcionaram; a suíte de testes de Resolver da GS1 passou de novo contra o Resolver agora no
gunicorn. A primeira execução do CI do `c426dfd` ficou verde, exceto o teste do proxy, que parou antes da
primeira verificação: o nginx do pacote do nginx.org guarda suas pastas temporárias em `/var/cache/nginx`, que
o usuário do runner não consegue criar; o teste agora mantém todas as pastas temporárias na sua pasta de
trabalho (`3298da7`).

## Como as principais áreas evoluíram

| Área | 1.0.0 (sessão 1) | Agora |
|---|---|---|
| Identificação | GTIN + lote opcional | 16 chaves primárias e 9 qualificadores, com as combinações do padrão |
| Etiquetas | PNG/SVG, HRI sim/não, marca opcional | HRI completo/chave/nenhum, versão e correção do QR, atributos de dados, sem marca |
| Achar cadastros | abrir um GTIN por vez | lista de registros, busca por texto, filtros por tipo de chave, qualificador, autor e problemas de link, busca por código, outros cadastros da chave |
| Trabalho em lote | nenhum | exportação XLSX/CSV e importação em duas etapas |
| Qualidade dos destinos | nenhuma | verificador de links no editor, em todos os cadastros e na importação |
| Contas | usuários pela linha de comando, todos iguais | perfis, prefixos, tela de usuários, senhas temporárias, histórico, auditoria, no banco próprio do portal |
| Instalação | manual, com patch | fork git, configuração em camadas, instalador para Ubuntu, backup |
| Resolução | GTIN e lote, links comprimidos do Digital Link 1.1 | todas as chaves e qualificadores, as regras do Resolver 1.2.1, EPC em binário de etiquetas NFC (`/eh…`, `/ex…`) |
| Testes | 69 verificações | 1.502 verificações em 18 programas de teste (um deles a própria suíte de testes da GS1), além do teste do instalador (68); rodam pelo pytest e no GitHub Actions, o portal e seus workers de tarefas também num MongoDB real |
| Implantação | um contêiner por serviço, servidor embutido do Flask, proxy reiniciado à mão | quantas réplicas se queira dos quatro serviços sem estado (definidas no `.env`), gunicorn em todos os serviços web, um proxy que acompanha as réplicas pelo DNS do Docker |
| Documentação | README do pacote, documento de passagem | README, guia do portal, funcionalidades, histórico, guia do desenvolvedor (em inglês e português), documentação das extensões, changelog |

## Decisões que ficam, a não ser que sejam revistas de propósito

1. Nomes de variáveis e comportamento oficiais são mantidos; mudanças deliberadas vão para o changelog.
2. Nenhum valor de instância no código: domínio pelo `FQDN`, operador por `RESOLVER_ORG_*` / `RESOLVER_CONTACT_*`.
3. O portal é o back-end entre o navegador e a API; o token nunca chega ao navegador.
4. A validação espelha o GS1 Barcode Syntax Engine; limites deliberados ficam documentados.
5. Resolver: `linkType` desconhecido é 404 (exigido pelo padrão); subida série → lote → variante → chave;
   query strings repassadas sem mudança e nunca julgadas.
6. Perfis leitor < editor < administrador conferidos em toda chamada; prefixos de empresa GS1 limitam
   todas as telas.
7. Os dados do portal (usuários, metadados dos cadastros, diário, entradas recusadas, caches) ficam num
   banco próprio no MongoDB da instalação, acessado por um usuário limitado a ele, e entram no backup
   diário; a chave de sessão vem do `.env` ([ADR 0001](adr/0001-estado-do-portal-no-mongodb.md); até a
   sessão 9, arquivos no volume de configuração).
8. Etiquetas: X = 0,495 mm, texto de 2,2 mm, zona de silêncio de 4X; correção de erros exatamente como
   escolhida; sem marca GS1.
9. Atributos de dados vão só para o QR Code e são validados pelo engine da GS1.
10. Importações e verificações de links são tarefas no banco do portal, executadas pelo serviço
    `portal-worker`; nada no portal depende da memória de um processo. O Resolver, a API de cadastro, o portal
    e o worker rodam em `*_REPLICAS` contêineres definidos no `.env`, os serviços web no gunicorn com vários
    processos; o proxy acha as réplicas pelo DNS do Docker; o banco e o proxy rodam uma vez só (ADR 0001,
    etapa 4).
11. O cadastro segue o Resolver 2.5.9: com número de série, lote e variante são qualificadores informativos
    do cadastro; todo cadastro qualificado deve ter acima dele o cadastro da chave.
12. O EPC em binário é decodificado a partir dos artefatos do TDT da GS1, incluídos sem alteração;
    qualificadores vindos da etiqueta vão para o caminho, atributos de dados para a query string; o hostname
    de um `++` é ignorado.
13. Os linksets escrevem os tipos de link `gs1:` em `https://ref.gs1.org/voc/` (Resolver 2.14); os
    documentos gravados mantêm as chaves oficiais `https://gs1.org/voc/`.

## Lições aprendidas

- Testar com dados criados por outras ferramentas; os cadastros de exemplo oficiais revelaram suposições.
- O nginx resolve os nomes dos upstreams na inicialização: o proxy precisa reiniciar quando um serviço é
  recriado. Desde a sessão 9 ele pergunta de novo ao DNS do Docker a cada 10 segundos (`resolve`, nginx 1.27.3
  ou posterior), o que também acha réplicas acrescentadas depois que ele iniciou; um reinício não acharia.
- `docker compose restart` mantém o ambiente antigo; use `up -d` depois de editar o `.env`.
- O syntax engine recusa algumas combinações que a gramática da URI permite (22 no ITIP): conferir com o
  engine.
- A gramática da §4.10 da GS1 tem um erro de digitação (`shipToaAdd…` para (4302)/(4303)).
- Conferir afirmações no código antes de documentá-las.
- Mostrar layouts como imagens antes de construí-los.
- Ler as regras de ordenação da norma, não só os conjuntos: a regra 4 do 2.5.9 também ordena os cadastros
  (a série antes do lote), o que a subida na hierarquia não seguia.
- Um dublê de teste esconde o que o componente real confere: o upstream simulado do teste do proxy aceitava
  qualquer cabeçalho Host, então o upstream `resolver_web` do item 1.5 (recusado pelo Werkzeug) passou em
  todos os testes e quebrou todas as resoluções na homologação. Conferir resoluções pelo proxy depois de cada
  instalação, não só o `/portal/healthz`.
- Artefatos legíveis por máquina e exemplos resolvidos também têm erros (um nome de campo num rascunho do
  TDT, cabeçalhos no anexo E.3): decodificar todos os vetores publicados e comparar com uma implementação
  independente.
- Ler o modelo de processamento, não só os dados: o artefato do SGCN-96 precisa das regras EXTRACT do seu
  nível BINARY, que a leitura só do nível de saída deixou passar.
- Rodar uma suíte de conformidade no ambiente de desenvolvimento antes de rodá-la de verdade: o código dela,
  sem alteração, contra o código real do Resolver previu o resultado da homologação e achou a única
  divergência antes da execução do responsável.
- Uma suíte de testes traz a leitura que os seus autores fazem do padrão: conferir cada falha com o texto
  antes de mudar o código (E12).
- Quando o banco real não roda onde os testes são escritos, um substituto compatível ainda exercita o que o
  mongomock não consegue (processos separados dividindo um banco), mas as lacunas dele precisam ser
  separadas dos defeitos: o FerretDB 1.24 não tem índices TTL e recusa arrays aninhados e chaves com ponto, que
  o MongoDB aceita.
- Um worker precisa dizer que está vivo: sem anúncios, uma tarefa na fila sem nenhum worker rodando espera
  calada, e nada diz ao usuário ou ao instalador por quê.
- Um arquivo que outros processos podem ler no mesmo instante precisa aparecer completo: grave-o com outro
  nome e ligue ou renomeie para o lugar. Para testar uma corrida assim, deixe a parte lenta mais lenta no
  teste em vez de esperar que inícios simultâneos se encontrem.
- Confira um plano contra a forma como ele vai ser operado: reiniciar o proxy quando um serviço é recriado
  funciona com um contêiner por serviço, não com um contêiner acrescentado ao lado dos outros.
- Uma ferramenta de outro empacotador se comporta diferente em detalhes: o nginx do Ubuntu e o do nginx.org
  guardam as pastas temporárias em lugares diferentes. Reproduza as condições do runner do CI (os caminhos do
  pacote, um usuário que não é root) antes de culpar o código.

## Pendências

- Aviso aos mantenedores oficiais sobre o `GET /api/index` público (redigido).
- Troca dos segredos de desenvolvimento da instalação de homologação (uma opção do instalador é candidata).
- Uma instalação nova com `scripts/install.sh` numa máquina limpa (só a reexecução foi comprovada).
- A verificação final do instalador usa só o `/portal/healthz`; deveria também pedir algo ao Resolver pelo
  proxy (item 7.2).
- Uma cópia do backup fora do servidor e um ensaio de restauração.
- Revisão dos 216 nomes de AIs em português; decisão sobre o logotipo GS1 na página inicial e nas páginas
  do Resolver.

Próximos passos: o backlog em aberto, na ordem combinada, está no README ([Backlog em aberto](README.md#backlog-em-aberto)).
