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
| 10 — tenants | 13/10 | ADR 0002, depois duas entregas de código (`1590b7e`, `675b6ca`), o commit de documentação e uma correção (`7c10048`) | item 2.4: organizações donas de prefixos de empresa GS1, o administrador do servidor, acesso de suporte, uma trilha de auditoria por organização, um e-mail por usuário |
| 11 — uma fonte única para as regras GS1 | 13/10 | ADR 0003, depois três entregas de código (`8e3d9c7`, `6f6ce19`, `e7c5a6d`) e o commit de documentação | item 2.5: uma versão do engine para todos os serviços, chaves, qualificadores e formatos do GS1 Barcode Syntax Dictionary, as mensagens do engine traduzidas, uma verificação semanal de atualizações |
| 12 — e-mail e a API das organizações | 14/10 | ADRs 0004 e 0005, uma correção do instalador (`f3d127d`), quatro entregas de código (`03c924b`, `fbe86f0`, `bb0b496`, `c469f29`) e dois commits de documentação | item 3.1: e-mail por um relay autenticado, convites, recuperação de senha por link de uso único, avisos de segurança e avisos de tarefas terminadas com preferências por usuário; item 3.2: uma API versionada para os sistemas das organizações, com chaves de API |
| 13 — o registro de acessos | 14/10 | ADR 0006, duas entregas de código (`d633fcb`, `7b8967a`) e o commit de documentação | item 4.1: toda requisição de resolução registrada pelo Resolver sem dados pessoais, contagens diárias por chave, uma tela Acessos, as chamadas da API das organizações registradas |

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

## Sessão 10 — tenants (item 2.4)

O responsável abriu a sessão e a deixou correr enquanto estava ausente, pedindo a opção recomendada em toda
pergunta. O fork estava em `fd8f67c` e a linha de base passou (1.350 verificações fora do navegador e 366 nele,
como no CI). A leitura do portal mostrou que uma única função, `allowed()`, já ficava entre todas as rotas e os
cadastros: limitá-la ao tenant da requisição limitaria tudo de uma vez.

Os nove pontos do item foram decididos pelas opções recomendadas e registrados no
[ADR 0002](adr/0002-organizacoes.md) (etapa 1): uma coleção `tenants`, com um tenant por usuário; os
administradores do operador como administradores do servidor, sem papel novo; acesso de suporte só de leitura,
com motivo, registrado na trilha do tenant; prefixos sobrepostos recusados; nada migrado (os usuários de hoje
passam a ser do operador, dono de tudo o que nenhum tenant tem); posse derivada do prefixo; um campo `tenant` nos
eventos do diário; um e-mail opcional e único; três entregas. O operador como dono dos prefixos sem tenant é o que
permite atualizar uma instalação sem mudança nenhuma: até existir o primeiro tenant, toda regra dá a resposta de
hoje.

| Commit | Mudança |
|---|---|
| `4bb39cd` | docs: ADR 0002 nos dois idiomas (etapa 1) |
| `1590b7e` | etapa 2: `portal/tenants.py`; usuários com tenant e e-mail; `set_scope()` e `allowed()` pelo dono; a conferência do worker antes de cada cadastro importado; diário, histórico, metadados dos cadastros e a última verificação completa de links por escopo; API de tenants e de suporte; `create_user.py --tenant --email`; `test_tenants.py` |
| `675b6ca` | etapa 3: tela Organizações, acesso de suporte e sua faixa, organização e e-mail em Usuários, organização no menu da conta e na auditoria; traduções; e2e; guias do usuário e imagens |

Toda proteção da etapa 2 passou por teste de mutação: doze mudanças no código (a posse fora do `allowed()`,
usuários de outro tenant gerenciáveis, sobreposições aceitas, a conferência do worker removida, a visão do
operador na auditoria ampliada, metadados mostrados a todo escopo, tenants desativados ainda entrando, acesso de
suporte podendo gravar, administradores de tenant contados como o último administrador do servidor, os prefixos de
um usuário de tenant sem conferência, o painel Histórico e a consulta do diário sem o tenant) fazem o
`test_tenants.py` falhar, cada uma. As consultas novas também rodaram no FerretDB, até onde suas lacunas conhecidas
deixam. Não foi possível mostrar mock-ups antes de construir as telas, como o responsável costuma pedir: as imagens
das telas prontas (as do guia do usuário) foram entregues para revisão antes de a atualização chegar à
homologação. Ainda não confirmado na homologação nem no CI.

Antes de a atualização ser entregue, o teste de implantação da sessão 11 descobriu que o `portal/Dockerfile`
copiava os módulos do portal pelo nome e deixava de fora o `tenants.py`: o portal do `1590b7e` não teria subido
num contêiner. A imagem agora copia todos os módulos, e o `test_deploy.py` sobe o portal a partir dos arquivos que
a imagem teria (`7c10048`).

## Sessão 11 — uma fonte única para as regras GS1 (item 2.5)

Ainda com o responsável ausente, e com o item 2.4 ainda sem push, o responsável pediu para seguir com o próximo
item em cima dele, para entregar os dois juntos. As regras GS1 do portal estavam escritas três vezes (Python,
JavaScript e a comparação dos testes com o engine), o Resolver e a API de cadastro instalavam a versão do engine
mais nova no momento do build, e as recusas do engine chegavam em inglês à interface em português.

As quatro perguntas do item foram decididas pelas opções recomendadas e registradas no
[ADR 0003](adr/0003-regras-gs1-do-dicionario.md): as regras geradas do dicionário num arquivo versionado e conferido
por um teste, de modo que o portal também funciona sem o engine; uma versão no `docker-compose.yml`; toda mensagem
da versão fixada traduzida, com um teste; uma tarefa semanal que abre uma issue em vez de um pull request.

| Commit | Mudança |
|---|---|
| `8d50280` | docs: ADR 0003 nos dois idiomas (etapa 1) |
| `7c10048` | deploy: todos os módulos do portal na imagem (a correção do item 2.4, acima) |
| `8e3d9c7` | etapa 2: `x-gs1-syntax-engine` no `docker-compose.yml`, um argumento de build para os cinco serviços, o `gs1encoder` fixado nas imagens oficiais, o script de build e o CI lendo o mesmo valor; `test_deploy.py` e `test_keys.py` conferem |
| `6f6ce19` | etapa 3: o `gs1_dictionary.json` e seu gerador, `gs1dict.py`, o `gs1.py` montado a partir dele, as regras do navegador vindas do `/config`, a comparação para a issue semanal, o workflow semanal; `test_dictionary.py` |
| `e7c5a6d` | etapa 4: a tabela de mensagens do engine e quem as reconhece, as 211 mensagens nos dois idiomas, nomes em português para (7041) e (8040)–(8043); `test_engine_messages.py` |

As tabelas montadas do dicionário foram comparadas com as escritas à mão antes de substituí-las: as únicas
diferenças foram a forma de escrever as formas de duas chaves (417 e 8004, que aceitam os mesmos cadastros) e os
nomes internos dos qualificadores. A comparação para a issue semanal foi experimentada com os dicionários reais da
1.1.0 e da 1.4.1 (mostra os AIs (7041) e (8040)–(8043) acrescentados e, no sentido inverso, que o portal não
conseguiria montar as regras com o dicionário mais antigo). Todo teste novo passou por teste de mutação (três
mudanças para a versão, cinco para o dicionário, oito para as mensagens). A API do GitHub não estava ao alcance do
ambiente de trabalho, então a primeira execução real do workflow semanal será no GitHub. Ainda não confirmado na
homologação nem no CI.

## Sessão 12 — e-mail (item 3.1) e a API das organizações (item 3.2)

O responsável ainda não conseguia chegar à estação de trabalho nem ao servidor para aplicar o bundle cumulativo dos
itens 2.4 e 2.5, e pediu para seguir com o próximo item e entregar tudo num único bundle a partir de `fd8f67c`,
tomando a opção recomendada em toda pergunta. Ele enviou na conversa o bundle das sessões 10 e 11; a base em cima
dele bateu exatamente com o fim da sessão 11 (1.904 verificações).

Toda pergunta do [ADR 0004](adr/0004-e-mail.md) foi decidida pela opção recomendada: envio SMTP a um relay escolhido
pelo operador (587 STARTTLS ou 465 TLS, já que a porta 25 é bloqueada no Azure), configurações no `.env` e e-mail
desligado sem elas; mensagens como tarefas do worker existente, com novas tentativas; links de uso único guardados
como hash, com o token no fragmento do endereço; convites por padrão quando há endereço; recuperação com a mesma
resposta para todos; avisos de segurança sempre e avisos de tarefas a pedido, no idioma do usuário; textos no
código; Mailpit num perfil do compose para experimentar; três entregas.

| Commit | Mudança |
|---|---|
| `a0ccc6a` | docs: ADR 0004 nos dois idiomas (etapa 1) |
| `f3d127d` | install: nenhuma configuração gravada duas vezes no `.env` numa nova execução (um defeito mais antigo achado pelo teste do relay) |
| `03c924b` | etapa 2: `mail.py`, `mailtexts.py`, `tokens.py`, `notify.py`; a tarefa `mail` e `notBefore`; recuperação, links, convites, redefinições por link, avisos e preferências no `app.py`; a etapa do relay no instalador; Mailpit; `test_mail.py` com um relay SMTP próprio |
| `fbe86f0` | etapa 3: os formulários de recuperação e de link da página de entrada, o convite na tela de usuários, Opções → E-mail, as imagens dos guias do usuário; `test_mail_e2e.py` |

Escrever o teste do instalador para o relay mostrou que uma nova execução gravava `FQDN`, `TLS_MODE`, uma
quantidade de réplicas e mais duas configurações duas vezes no `.env`, o valor antigo por último, de modo que uma
mudança feita pelo instalador não valia: a conferência das chaves gerenciadas procurava o nome seguido de um
espaço, e os nomes no fim de uma linha da lista são seguidos de uma quebra de linha. Corrigido no seu próprio
commit, com uma conferência de que nenhuma chave aparece duas vezes. O teste no navegador da página do link mostrou
que um link colado numa página de entrada aberta muda só o fragmento e não carrega a página de novo; a página agora
escuta essa mudança. As 16 proteções do servidor e a retirada do token da barra de endereço passaram por teste de
mutação; uma mutação (o link de uma conta desativada aceito) escapou no início e ganhou a sua conferência. A imagem
do Mailpit não pode ser baixada no ambiente de trabalho, então a primeira execução dela é na homologação. Ainda não
confirmado na homologação nem no CI.

**Item 3.2, na mesma noite.** Com o item 3.1 entregue, o responsável pediu para seguir com o próximo item, e decidiu
que os commits ainda sem push deveriam ter o Claude como autor e ele como coautor (até então ele era o autor e o
Claude o coautor). Os quinze commits a partir de `fd8f67c` foram reescritos em ordem: nos documentos de cada commit,
os hashes dos commits anteriores já reescritos foram trocados, o que funcionou porque nenhum commit cita um posterior
(conferido antes); o resultado diferia da árvore antiga só nesses hashes (94 linhas). Desde então os commits são
feitos assim.

Toda pergunta do [ADR 0005](adr/0005-api-das-organizacoes.md) foi decidida pela opção recomendada: a API servida pelo
portal em `/portal/api/v1`, de modo que todas as regras valem sem mudança; chaves que pertencem às organizações e
são criadas pelos seus administradores (um administrador do servidor só para os cadastros do operador);
`rk_<id>.<segredo>` mostrada uma vez, só o SHA-256 guardado; escopos, prefixos opcionais, validade obrigatória; um
limite de requisições por chave no MongoDB; criação e revogação de chaves no diário, mudanças como eventos de
cadastro de `api:<id>`; e-mail quando uma chave é criada e antes de expirar; uma descrição OpenAPI 3.1 escrita à mão
e conferida por um teste.

| Commit | Mudança |
|---|---|
| `326566d` | docs: ADR 0005 nos dois idiomas (etapa 1) |
| `bb0b496` | etapa 2: `apikeys.py`, `api_v1.py`, `openapi.json`; endpoints de chaves, `remove_record()` e `label_response()` compartilhados com a API, o aviso de validade e a limpeza de hora em hora do worker; `test_api.py` |
| `c469f29` | etapa 3: a tela de chaves de API e as suas imagens, a correção do menu, os guias do usuário; `test_api_e2e.py` |

As dezesseis proteções do servidor passaram por teste de mutação; uma mutação (o aviso de validade pego de novo)
fez o `expiring()` girar para sempre, o que o teste não deixa passar, mas interrompeu o script de mutação por tempo
esgotado. O teste no navegador achou dois defeitos antes da entrega: uma chave de mensagem escrita duas vezes no
catálogo (o cabeçalho de coluna "Criada" substituía a mensagem "Chave … criada"), agora recusada por um teste, e uma
chave nova deixada na página depois de sair da tela, agora retirada. Ainda não confirmado na homologação nem no CI.

## Sessão 13 — o registro das requisições ao Resolver (item 4.1)

O responsável ainda não conseguia chegar à estação nem ao servidor, e pediu para seguir com o handover e entregar um
bundle com tudo desde `fd8f67c`, escolhendo a opção recomendada em toda pergunta. Ele mandou o bundle da sessão 12 na
conversa; a base sobre ele bateu com o fim da sessão 12 (1.743 verificações sem navegador, 465 no Chromium).

Toda pergunta do [ADR 0006](adr/0006-registro-de-requisicoes.md) foi decidida pela opção recomendada: o próprio
Resolver registra cada requisição, depois de responder, a partir do que a resolução sabe; nada que identifique o
cliente (nenhum endereço, nem com hash; nenhum User-Agent, só uma classe de dispositivo; só o host de origem; só os AIs
de números de série e atributos de dados); uma fila limitada e uma thread de gravação por processo; um banco próprio,
`resolver_log`, legível pelo usuário do portal, com expiração por evento (90 dias); agregados diários por chave feitos
pelo worker no fuso da instalação (800 dias); a posse derivada da parte da empresa na hora da consulta; os
administradores do servidor veem a instalação inteira; as chamadas da API das organizações registradas pelo portal;
três entregas.

| Commit | Mudança |
|---|---|
| `e519771` | docs: ADR 0006 nos dois idiomas (etapa 1) |
| `d633fcb` | etapa 2: `web_server/src/request_log.py` e os ganchos do Resolver; o papel de leitura no `db_init.py`; `portal/requestlog.py` (escopo, listagem, agregados na manutenção, chamadas da API); os endpoints do portal; o backup sem `resolver_log`; o fuso no instalador; `test_request_log.py`, `test_requestlog.py` |
| `7b8967a` | etapa 3: a tela Acessos e a sua imagem, a seção 16 dos guias do usuário; `test_requests_e2e.py` |

As respostas do Resolver tinham de ficar exatamente como eram, mas o registro precisa de dois fatos que só a
resolução conhece: o nível do cadastro que respondeu e o motivo de um 404. O `web_logic` os devolve em chaves privadas
dos seus resultados, que o `web_namespace` retira antes de responder; os testes comparam as respostas 404 e 300 com o
formato oficial. O mongomock apaga, na leitura, documentos cuja data de TTL já passou, então um registro desligado por
uma expiração de zero dias parecia vazio de qualquer jeito: a mutação "desligamento ignorado" escapou até o teste
contar também o que o gravador gravou. Outra mutação que escapou mostrou um teste que procurava um padrão já escapado,
que não acha nada com ou sem escape. O teste no navegador achou o novo item de menu fora da lista dos itens que fecham
o menu. 26 mutações, todas pegas.

**Testes na homologação, 14 de outubro.** O responsável aplicou o bundle na estação e na homologação e seguiu um plano
de testes cobrindo tudo desde `fd8f67c` (sessões 10 a 13). O CI ficou verde em todos os jobs. Dois achados não eram do
código: o `.env` tinha três configurações duplicadas de antes da correção do instalador da sessão 12 (`f3d127d` evita
duplicatas novas, mas não retira as antigas), retiradas à mão; e a verificação semanal do motor falhou porque um fork
no GitHub vem com Issues desligado (Settings → Features → Issues), e depois disso rodou verde. Organizações, as regras
GS1, e-mail, a API de organizações e a tela Acessos funcionaram como descrito. O backup diário falhou: `d633fcb`
deixava `resolver_log` de fora com `--nsExclude`, uma opção do `mongorestore` que o `mongodump` não tem, e o script
parava sem mensagem própria, deixando um arquivo pela metade. `c1b3f78` devolve o registro ao backup (é pequeno e
limitado pela expiração), avisa `ERROR`, apaga o arquivo pela metade, e o `test_deploy.py` agora roda o script com um
`docker` substituto e confere as opções do dump (62 verificações).

## Como as principais áreas evoluíram

| Área | 1.0.0 (sessão 1) | Agora |
|---|---|---|
| Identificação | GTIN + lote opcional | 16 chaves primárias e 9 qualificadores, com as combinações do padrão |
| Etiquetas | PNG/SVG, HRI sim/não, marca opcional | HRI completo/chave/nenhum, versão e correção do QR, atributos de dados, sem marca |
| Achar cadastros | abrir um GTIN por vez | lista de registros, busca por texto, filtros por tipo de chave, qualificador, autor e problemas de link, busca por código, outros cadastros da chave |
| Trabalho em lote | nenhum | exportação XLSX/CSV e importação em duas etapas |
| Uso | nada registrado | toda requisição de resolução registrada sem dados pessoais, contagens diárias por chave, uma tela Acessos por escopo |
| Integração | a API de cadastro oficial e o seu único token mestre | uma API versionada para os sistemas de cada organização, com chaves de API (escopos, prefixos, validade, um limite de requisições) e uma descrição OpenAPI |
| Qualidade dos destinos | nenhuma | verificador de links no editor, em todos os cadastros e na importação |
| Contas | usuários pela linha de comando, todos iguais | perfis, prefixos, organizações (tenants) com usuários e auditoria próprios, um administrador do servidor com acesso de suporte, tela de usuários, senhas temporárias ou convites por e-mail, recuperação de senha por e-mail, avisos de segurança, histórico, auditoria, no banco próprio do portal |
| Instalação | manual, com patch | fork git, configuração em camadas, instalador para Ubuntu, backup |
| Resolução | GTIN e lote, links comprimidos do Digital Link 1.1 | todas as chaves e qualificadores, as regras do Resolver 1.2.1, EPC em binário de etiquetas NFC (`/eh…`, `/ex…`) |
| Testes | 69 verificações | 2.133 verificações em 28 programas de teste (um deles a própria suíte de testes da GS1), além do teste do instalador (87); rodam pelo pytest e no GitHub Actions, o portal e seus workers de tarefas também num MongoDB real |
| Implantação | um contêiner por serviço, servidor embutido do Flask, proxy reiniciado à mão | quantas réplicas se queira dos quatro serviços sem estado (definidas no `.env`), gunicorn em todos os serviços web, um proxy que acompanha as réplicas pelo DNS do Docker |
| Documentação | README do pacote, documento de passagem | README, guia do portal, funcionalidades, histórico, guia do desenvolvedor (em inglês e português), documentação das extensões, changelog |

## Decisões que ficam, a não ser que sejam revistas de propósito

1. Nomes de variáveis e comportamento oficiais são mantidos; mudanças deliberadas vão para o changelog.
2. Nenhum valor de instância no código: domínio pelo `FQDN`, operador por `RESOLVER_ORG_*` / `RESOLVER_CONTACT_*`.
3. O portal é o back-end entre o navegador e a API; o token nunca chega ao navegador.
4. A validação espelha o GS1 Barcode Syntax Engine; limites deliberados ficam documentados. Desde a sessão 11,
   chaves, qualificadores e formatos são montados a partir do dicionário da versão única do engine escrita no
   `docker-compose.yml`, que todos os serviços usam ([ADR 0003](adr/0003-regras-gs1-do-dicionario.md)).
5. Resolver: `linkType` desconhecido é 404 (exigido pelo padrão); subida série → lote → variante → chave;
   query strings repassadas sem mudança e nunca julgadas.
6. Perfis leitor < editor < administrador conferidos em toda chamada; prefixos de empresa GS1 limitam
   todas as telas. Um cadastro pertence ao tenant cujo prefixo inicia sua chave, ou ao operador; toda chamada
   fica limitada ao tenant da requisição; o administrador do servidor só chega aos dados de um tenant pelo acesso
   de suporte, só de leitura e registrado ([ADR 0002](adr/0002-organizacoes.md)).
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
14. O e-mail passa por um relay escolhido pelo operador, como tarefas do worker; sem relay nada muda. Os links de
    uso único são guardados como hash e levados no fragmento do endereço; a recuperação de senha responde igual
    para todos; os avisos de segurança não podem ser desligados ([ADR 0004](adr/0004-e-mail.md)).
15. Os sistemas das organizações usam a API versionada do próprio portal (`/portal/api/v1`) com chaves que os seus
    administradores criam; uma chave age como um usuário da sua organização agiria, sob todas as regras do portal;
    só o hash de uma chave é guardado ([ADR 0005](adr/0005-api-das-organizacoes.md)).
16. O Resolver registra cada requisição que responde, em segundo plano e sem nada que identifique a pessoa que leu;
    os eventos brutos expiram, as contagens diárias por chave ficam; de quem são os eventos é decidido na hora da
    consulta, pela chave ([ADR 0006](adr/0006-registro-de-requisicoes.md)).

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
- Antes de acrescentar uma dimensão ao controle de acesso, ache o único ponto por onde todas as rotas já passam
  (`allowed()`): mudar ali limita todas as rotas de uma vez, e os testes existentes mostram que nada mais mudou.
- Um dono novo para tudo o que não tem dono (o operador) permite chegar a um modelo sem migração: até existir o
  primeiro tenant, toda regra dá a resposta antiga.
- Uma lista de arquivos mantida à mão num Dockerfile se afasta do código: um módulo novo faltou na imagem com todos
  os testes passando, porque os testes rodavam a árvore de fontes. Teste o que a imagem vai conter.
- Antes de gerar uma tabela que substitui uma escrita à mão, compare as duas: as diferenças são erros do gerador ou
  da tabela antiga, e as duas pedem uma decisão.
- O teste de uma funcionalidade nova lê o que o código antigo grava: conferir o `.env` do instalador para o relay
  revelou configurações gravadas duas vezes, o valor antigo por último, um defeito mais antigo que a
  funcionalidade. Confira a saída, não só os valores que deviam mudar.
- Um link que difere da página aberta só depois do `#` não carrega a página de novo: um código que lê o fragmento
  ao carregar também precisa escutar o `hashchange`. O mesmo vale para o que uma visão deixa para trás: uma chave
  mostrada uma vez ficava na página quando a visão mudava, até sair da visão passar a retirá-la.
- Um catálogo de mensagens mantido à mão pode ter a mesma chave duas vezes, e a segunda vence em silêncio: um teste
  agora recusa isso.
- Um substituto de teste pode fazer mais do que a peça real de um jeito que esconde um defeito: o mongomock apaga
  documentos vencidos na leitura, então uma expiração de zero dias parecia um registro desligado. Confira o efeito em
  si (o que foi gravado), não só o que uma consulta devolve.
- Uma mutação que faz o código girar para sempre é pega (o teste não passa), mas pode parar um laço de mutações que
  espera por ela: dê a cada execução o seu próprio limite de tempo e trate o tempo esgotado como pego.

## Pendências

- Aviso aos mantenedores oficiais sobre o `GET /api/index` público (redigido).
- Troca dos segredos de desenvolvimento da instalação de homologação (uma opção do instalador é candidata).
- Uma instalação nova com `scripts/install.sh` numa máquina limpa (só a reexecução foi comprovada).
- A verificação final do instalador usa só o `/portal/healthz`; deveria também pedir algo ao Resolver pelo
  proxy (item 7.2).
- Uma cópia do backup fora do servidor e um ensaio de restauração.
- Os itens 2.4, 2.5, 3.1, 3.2 e 4.1 na homologação e no CI (sessões 10 a 13): faltam o push do responsável, o resumo do
  CI, as conferências da atualização na homologação, a primeira execução da verificação semanal do engine, um primeiro
  teste do e-mail com o Mailpit e depois com o relay da organização, e as primeiras requisições registradas na
  homologação.
- O `/heartbeat` do próprio Resolver responde 500 (código oficial: um recurso do Flask-RESTX devolve uma resposta do
  `jsonify` dentro de uma tupla); a verificação de saúde do portal usa a da API de cadastro, então nada depende dele.
  Candidato a uma correção pequena e a uma issue no projeto oficial.
- Revisão dos 221 nomes de AIs em português e das mensagens do engine em português; decisão sobre o logotipo GS1
  na página inicial e nas páginas do Resolver.

Próximos passos: o backlog em aberto, na ordem combinada, está no README ([Backlog em aberto](README.md#backlog-em-aberto)).
