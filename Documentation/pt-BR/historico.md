# Histórico do Expansion Pack

Como o GS1 Digital Link Resolver CE — Expansion Pack cresceu a partir do GS1 Resolver CE v3 oficial,
sessão por sessão, com as decisões tomadas no caminho e os motivos. A lista dia a dia das mudanças está no
[CHANGELOG](../extensions/CHANGELOG.md) (em inglês); o que cada funcionalidade faz hoje está em
[funcionalidades](funcionalidades.md).

*English version: [history](../history.md).*

O trabalho foi feito em quatro sessões entre 22 de setembro e 1º de outubro de 2026, sobre uma instalação
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
| 6 — EPC em binário | 02/10 | `51a0da8`, `895c4b1` e o commit de documentação | `/eh…` e `/ex…` descomprimidos para todos os esquemas EPC que têm GS1 Digital Link (item 1.6), a partir dos artefatos do TDT 2.2 e do TDS 2.3; mais quatro candidatos a errata |

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
para que cada um possa ser oferecido depois ao projeto oficial separadamente.

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
| `895c4b1` | Resolver: `/eh…` e `/ex…` resolvidos como o GS1 Digital Link descomprimido (F6, restante do F7); atributos de dados conferidos pelo engine e repassados; 400 quando a cadeia não decodifica |

Decisões do responsável: o decodificador cobre todos os esquemas de uma vez (clássicos, `+` com dados
+AIDC, `++`); qualificadores trazidos pela etiqueta vão para o caminho e atributos de dados para a query
string repassada ao destino; o hostname dentro de um EPC `++` é ignorado e o Resolver mantém o próprio
domínio. A implementação lê os artefatos do TDT (sem código específico por esquema para os clássicos) em
vez de usar a biblioteca `epc-tds`, que conhece só parte dos esquemas clássicos e nada do TDS 2.0; o
`epc-tds` serve de conferência independente nos testes.

Candidatos a errata encontrados ao decodificar: E8 (EPCB 4.2.2), E9 (anexo E.3 do TDS 2.3: cabeçalhos de
SSCC++ e ITIP++, hostnames de SGTIN++ e DSGTIN++, uma EPC URI), E10 (Tabelas 14-14 e 14-15 do TDS 2.3), E11
(artefato do TDT do CPI-var) — seção 6 da revisão de conformidade.

## Como as principais áreas evoluíram

| Área | 1.0.0 (sessão 1) | Agora |
|---|---|---|
| Identificação | GTIN + lote opcional | 16 chaves primárias e 9 qualificadores, com as combinações do padrão |
| Etiquetas | PNG/SVG, HRI sim/não, marca opcional | HRI completo/chave/nenhum, versão e correção do QR, atributos de dados, sem marca |
| Achar cadastros | abrir um GTIN por vez | lista de registros, busca por texto, filtros por tipo de chave, qualificador, autor e problemas de link, busca por código, outros cadastros da chave |
| Trabalho em lote | nenhum | exportação XLSX/CSV e importação em duas etapas |
| Qualidade dos destinos | nenhuma | verificador de links no editor, em todos os cadastros e na importação |
| Contas | usuários pela linha de comando, todos iguais | perfis, prefixos, tela de usuários, senhas temporárias, histórico, auditoria |
| Instalação | manual, com patch | fork git, configuração em camadas, instalador para Ubuntu, backup |
| Resolução | GTIN e lote, links comprimidos do Digital Link 1.1 | todas as chaves e qualificadores, as regras do Resolver 1.2.1, EPC em binário de etiquetas NFC (`/eh…`, `/ex…`) |
| Testes | 69 verificações | 1.042 verificações em 13 programas de teste, além do teste do instalador |
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
7. Os arquivos do portal (`users.json`, `secret.key`, `records-meta.json`, `journal.jsonl`) ficam no
   volume de configuração e entram no backup diário.
8. Etiquetas: X = 0,495 mm, texto de 2,2 mm, zona de silêncio de 4X; correção de erros exatamente como
   escolhida; sem marca GS1.
9. Atributos de dados vão só para o QR Code e são validados pelo engine da GS1.
10. Um único worker do gunicorn com threads.
11. O cadastro segue o Resolver 2.5.9: com número de série, lote e variante são qualificadores informativos
    do cadastro; todo cadastro qualificado deve ter acima dele o cadastro da chave.
12. O EPC em binário é decodificado a partir dos artefatos do TDT da GS1, incluídos sem alteração;
    qualificadores vindos da etiqueta vão para o caminho, atributos de dados para a query string; o hostname
    de um `++` é ignorado.

## Lições aprendidas

- Testar com dados criados por outras ferramentas; os cadastros de exemplo oficiais revelaram suposições.
- O nginx resolve os nomes dos upstreams na inicialização: o proxy precisa reiniciar quando um serviço é
  recriado.
- `docker compose restart` mantém o ambiente antigo; use `up -d` depois de editar o `.env`.
- O syntax engine recusa algumas combinações que a gramática da URI permite (22 no ITIP): conferir com o
  engine.
- A gramática da §4.10 da GS1 tem um erro de digitação (`shipToaAdd…` para (4302)/(4303)).
- Conferir afirmações no código antes de documentá-las.
- Mostrar layouts como imagens antes de construí-los.
- Ler as regras de ordenação da norma, não só os conjuntos: a regra 4 do 2.5.9 também ordena os cadastros
  (a série antes do lote), o que a subida na hierarquia não seguia.
- Artefatos legíveis por máquina e exemplos resolvidos também têm erros (um nome de campo num rascunho do
  TDT, cabeçalhos no anexo E.3): decodificar todos os vetores publicados e comparar com uma implementação
  independente.
- Ler o modelo de processamento, não só os dados: o artefato do SGCN-96 precisa das regras EXTRACT do seu
  nível BINARY, que a leitura só do nível de saída deixou passar.

## Pendências

- Aviso aos mantenedores oficiais sobre o `GET /api/index` público (redigido).
- Troca dos segredos de desenvolvimento da instalação de homologação (uma opção do instalador é candidata).
- Uma instalação nova com `scripts/install.sh` numa máquina limpa (só a reexecução foi comprovada).
- Um registro da suíte de conformidade da GS1 contra o Resolver de homologação.
- Uma cópia do backup fora do servidor e um ensaio de restauração.
- Revisão dos 216 nomes de AIs em português; decisão sobre o logotipo GS1 na página inicial e nas páginas
  do Resolver.

Próximos passos candidatos: ler os dados brutos do leitor de código de barras (FNC1/GS) na busca por código
usando o syntax engine, exportar só os registros filtrados, escolha do
tamanho da etiqueta e exportação em PDF, login único (SSO), rotação do diário, monitoramento de saúde, CI
com os testes de desenvolvimento e pull requests pequenos para o projeto oficial.
